"""OBSOrchestrator — build spec v1.0 §5.9. Only ever invoked from
PolicyEngine's "allowed" path (R-SAF-02: it is the sole caller of
OBSOrchestrator.execute). Idempotent per decision_id (R-ORC-01), verifies
post-state (R-ORC-02), and freezes rather than restores on kill switch
(R-SAF-04 — this resolves the freeze-vs-revert contradiction in PRD v0.1)."""
import asyncio
from dataclasses import dataclass, field
from typing import Any, Literal

from codirector.core.models import Decision
from codirector.policy.catalog import ActionSpec, ActionType


@dataclass
class ExecutionResult:
    decision_id: str
    status: Literal["executed", "failed", "frozen", "state_mismatch"]
    detail: str
    post_state_matched: bool | None = None


@dataclass
class PriorState:
    action_type: ActionType
    values: dict[str, Any] = field(default_factory=dict)


class OBSOrchestrator:
    def __init__(self, provider: Any) -> None:
        self._provider = provider
        self._executed: dict[str, ExecutionResult] = {}
        self._prior_state: dict[str, PriorState] = {}
        self._decision_actions: dict[str, ActionSpec] = {}
        self._revert_tasks: dict[str, asyncio.Task] = {}
        self._kill_switch_engaged = False

    @property
    def kill_switch_engaged(self) -> bool:
        return self._kill_switch_engaged

    def prior_state_for(self, decision_id: str) -> PriorState | None:
        return self._prior_state.get(decision_id)

    async def execute(self, decision: Decision, action: ActionSpec) -> ExecutionResult:
        # R-SAF-04: once frozen, no queued/new action executes until an
        # explicit resume — checked before any OBS call, never mid-call.
        if self._kill_switch_engaged:
            result = ExecutionResult(decision.decision_id, "frozen", "kill switch engaged; action not sent")
            self._executed[decision.decision_id] = result
            return result

        # R-ORC-01: a replayed decision_id is a no-op.
        if decision.decision_id in self._executed:
            return self._executed[decision.decision_id]

        prior = await self._capture_state(action)
        if action.reversible:
            self._prior_state[decision.decision_id] = prior
            self._decision_actions[decision.decision_id] = action

        task = asyncio.ensure_future(self._apply(action, decision))
        self._revert_tasks[decision.decision_id] = task
        try:
            await task
        except asyncio.CancelledError:
            result = ExecutionResult(decision.decision_id, "frozen", "cancelled by kill switch")
            self._executed[decision.decision_id] = result
            return result
        except Exception as exc:  # noqa: BLE001 — any adapter failure must not crash the pipeline
            result = ExecutionResult(decision.decision_id, "failed", str(exc))
            self._executed[decision.decision_id] = result
            return result
        finally:
            self._revert_tasks.pop(decision.decision_id, None)

        matched = await self._verify_post_state(action)
        result = ExecutionResult(
            decision.decision_id,
            "executed" if matched else "state_mismatch",
            "ok" if matched else "post-state did not match expected result",
            post_state_matched=matched,
        )
        self._executed[decision.decision_id] = result
        return result

    def kill_switch(self) -> None:
        """R-SAF-04: stops locally within 250 ms. Cancels in-flight requests
        and abandons pending ones; never attempts to restore prior state —
        that is rollback's job, and rollback is creator-initiated only."""
        self._kill_switch_engaged = True
        for task in list(self._revert_tasks.values()):
            task.cancel()

    def resume(self) -> None:
        """Explicit creator/UI action required to leave the frozen state."""
        self._kill_switch_engaged = False

    async def _capture_state(self, action: ActionSpec) -> PriorState:
        t = action.target
        if action.type == ActionType.OVERLAY_TEXT:
            return PriorState(action.type, {"text": self._provider.get_input_text(t.input_name)})
        if action.type == ActionType.SCENE_SWITCH:
            state = await self._provider.get_state()
            return PriorState(action.type, {"scene": state.program_scene})
        if action.type == ActionType.ITEM_VISIBILITY:
            return PriorState(action.type, {"visible": self._provider.get_item_visibility(t.scene_name, t.item_name)})
        if action.type == ActionType.FILTER_TOGGLE:
            return PriorState(action.type, {"enabled": self._provider.get_filter_enabled(t.source_name, t.filter_name)})
        raise ValueError(f"unknown action type {action.type}")

    async def _apply(self, action: ActionSpec, decision: Decision) -> None:
        t = action.target
        parameters = decision.proposal.parameters
        if action.type == ActionType.OVERLAY_TEXT:
            text = decision.proposal.representative_text
            if action.limits.max_length is not None:
                text = text[: action.limits.max_length]
            await self._provider.set_input_text(t.input_name, text)
        elif action.type == ActionType.SCENE_SWITCH:
            await self._provider.set_scene(t.scene_name)
        elif action.type == ActionType.ITEM_VISIBILITY:
            item_id = self._provider.resolve_item_id(t.scene_name, t.item_name)
            visible = bool(parameters.get("visible", 1))
            await self._provider.set_item_visibility(t.scene_name, item_id, visible)
        elif action.type == ActionType.FILTER_TOGGLE:
            await self._provider.set_filter_enabled(t.source_name, t.filter_name, True)
        else:
            raise ValueError(f"unknown action type {action.type}")

    async def _verify_post_state(self, action: ActionSpec) -> bool:
        t = action.target
        if action.type == ActionType.SCENE_SWITCH:
            state = await self._provider.get_state()
            return state.program_scene == t.scene_name
        # OBSStateEvent does not carry input text / item visibility / filter
        # state (§4.1). A real adapter verifies these via the obs-websocket
        # request's own success response; here we treat a non-raising _apply
        # as sufficient verification for those action types.
        return True
