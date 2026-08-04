"""In-process application state shared by the REST routes and the WebSocket
broadcaster — build spec v1.0 §5.11, D-15. A single AppState instance is
created at server startup and injected into every request."""
import time
from dataclasses import dataclass

from fastapi import WebSocket

from codirector.config.models import PersonaConfig
from codirector.core.autonomy import AutonomyLevel
from codirector.core.models import Decision
from codirector.policy.catalog import ActionCatalog
from codirector.queue.interaction_queue import InteractionQueue

_DECISION_LOG_CAP = 200


@dataclass
class ComponentHealth:
    status: str = "down"
    detail: str = "not started"


class AppState:
    def __init__(self, persona: PersonaConfig, catalog: ActionCatalog) -> None:
        self.persona = persona
        self.catalog = catalog
        # R-AUT-01: OBSERVE on every app start. Never persisted (R-AUT-02) —
        # there is deliberately no code path that loads this from disk.
        self.autonomy: AutonomyLevel = AutonomyLevel.OBSERVE
        self.kill_switch_engaged = False
        self.queue = InteractionQueue(
            max_items=persona.thresholds.max_queue_items,
            max_prompts_per_minute=persona.thresholds.max_prompts_per_minute,
        )
        self.health: dict[str, ComponentHealth] = {
            name: ComponentHealth() for name in ("obs", "twitch", "asr", "reasoning")
        }
        self.decision_log: list[Decision] = []
        self._websockets: list[WebSocket] = []
        self._overlay_websockets: list[WebSocket] = []

    def set_autonomy(self, level: AutonomyLevel) -> None:
        # R-AUT-03: the system itself never silently escalates — this method
        # is only ever invoked from an explicit POST /api/autonomy call, i.e.
        # a deliberate creator UI action. It does not gate the *direction* of
        # the change (creators can freely step down too).
        self.autonomy = level

    def engage_kill_switch(self) -> list[str]:
        """Enter the local safe state and abandon every pending decision."""
        self.kill_switch_engaged = True
        self.autonomy = AutonomyLevel.OBSERVE
        return self.queue.clear_pending()

    def resume_automation(self) -> None:
        """Leave the paused state without restoring the previous autonomy."""
        self.kill_switch_engaged = False

    def record_decision(self, decision: Decision) -> None:
        self.decision_log.insert(0, decision)
        del self.decision_log[_DECISION_LOG_CAP:]

    def register_websocket(self, ws: WebSocket) -> None:
        self._websockets.append(ws)

    def unregister_websocket(self, ws: WebSocket) -> None:
        if ws in self._websockets:
            self._websockets.remove(ws)

    async def broadcast(self, message: dict) -> None:
        dead = []
        for ws in self._websockets:
            try:
                await ws.send_json(message)
            except Exception:  # noqa: BLE001 — a broken socket shouldn't affect the others
                dead.append(ws)
        for ws in dead:
            self.unregister_websocket(ws)

    def register_overlay_websocket(self, ws: WebSocket) -> None:
        self._overlay_websockets.append(ws)

    def unregister_overlay_websocket(self, ws: WebSocket) -> None:
        if ws in self._overlay_websockets:
            self._overlay_websockets.remove(ws)

    async def broadcast_overlay_text(self, text: str) -> None:
        """Feeds frontend/public/overlay.html — the bounded OBS Browser
        Source surface, kept structurally separate from the control-center
        WebSocket (§5.11/R-SAF-06) so a control-center bug can never leak
        into what the public overlay renders."""
        dead = []
        for ws in self._overlay_websockets:
            try:
                await ws.send_json({"text": text})
            except Exception:  # noqa: BLE001
                dead.append(ws)
        for ws in dead:
            self.unregister_overlay_websocket(ws)

    def snapshot(self) -> dict:
        return {
            "type": "snapshot",
            "autonomy": self.autonomy.value,
            "kill_switch_engaged": self.kill_switch_engaged,
            "health": {name: {"status": h.status, "detail": h.detail} for name, h in self.health.items()},
            "queue": _serialize_queue(self.queue),
            "decision_log": [_serialize_decision(d) for d in self.decision_log[:50]],
        }


def _serialize_queue(queue: InteractionQueue) -> dict:
    def item_view(item):
        return {
            "decision_id": item.decision.decision_id,
            "representative_text": item.decision.proposal.representative_text,
            "response_angle": item.decision.proposal.response_angle,
            "score": item.decision.score,
            "score_breakdown": item.decision.score_breakdown,
            "expires_at": item.decision.expires_at,
            # Browser clocks do not share Python's monotonic epoch. Sending
            # the remaining duration keeps the countdown correct without
            # ever mixing monotonic time with Unix wall time.
            "expires_in_s": max(0.0, item.decision.expires_at - time.monotonic()),
            "pinned": item.pinned,
        }

    return {
        "active": [item_view(i) for i in queue.active_items()],
        "held_count": len(queue.held_items()),
    }


def _serialize_decision(decision: Decision) -> dict:
    return {
        "decision_id": decision.decision_id,
        "correlation_id": decision.correlation_id,
        "decision_type": decision.proposal.decision_type,
        "action_id": decision.proposal.action_id,
        "representative_text": decision.proposal.representative_text,
        "score": decision.score,
        "policy_result": decision.policy_result,
        "policy_rule_id": decision.policy_rule_id,
        "created_at": decision.created_at,
    }
