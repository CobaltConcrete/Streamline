"""REST routes — build spec v1.0 §5.11. Config over REST, live event stream
over WS (ws.py). Every mutating endpoint here is the "explicit UI action"
that R-AUT-03 and R-SAF-04 require — there is no other code path that changes
autonomy or engages the kill switch.
"""
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from codirector.api.state import AppState, _serialize_decision, _serialize_queue
from codirector.core.autonomy import AutonomyLevel

router = APIRouter(prefix="/api")


def _state(request: Request) -> AppState:
    return request.app.state.codirector


@router.get("/health")
async def get_health(request: Request):
    state = _state(request)
    return {name: {"status": h.status, "detail": h.detail} for name, h in state.health.items()}


@router.get("/autonomy")
async def get_autonomy(request: Request):
    state = _state(request)
    return {"level": state.autonomy.value, "kill_switch_engaged": state.kill_switch_engaged}


class AutonomySetRequest(BaseModel):
    level: Literal["OBSERVE", "ASSIST", "CO_DIRECT"]


@router.post("/autonomy")
async def set_autonomy(request: Request, body: AutonomySetRequest):
    state = _state(request)
    if state.kill_switch_engaged and body.level != "OBSERVE":
        # R-SAF-04: pending/paused state requires explicit resume first.
        raise HTTPException(status_code=409, detail="kill switch engaged; call /api/resume before changing autonomy")
    state.set_autonomy(AutonomyLevel(body.level))
    await state.broadcast({"type": "autonomy_changed", "level": state.autonomy.value})
    return {"level": state.autonomy.value}


@router.post("/kill-switch")
async def kill_switch(request: Request):
    state = _state(request)
    cleared_ids = state.engage_kill_switch()
    await state.broadcast(
        {
            "type": "kill_switch_activated",
            "cleared_decision_ids": cleared_ids,
            "queue": _serialize_queue(state.queue),
        }
    )
    return {
        "kill_switch_engaged": True,
        "autonomy": state.autonomy.value,
        "cleared_pending": len(cleared_ids),
    }


@router.post("/resume")
async def resume(request: Request):
    state = _state(request)
    state.resume_automation()
    await state.broadcast({"type": "resumed"})
    return {"kill_switch_engaged": False}


@router.get("/queue")
async def get_queue(request: Request):
    return _serialize_queue(_state(request).queue)


@router.post("/queue/{decision_id}/accept")
async def accept_item(request: Request, decision_id: str):
    state = _state(request)
    if not state.queue.accept(decision_id):
        raise HTTPException(status_code=404, detail="decision not found in queue")
    await state.broadcast({"type": "queue_changed", "queue": _serialize_queue(state.queue)})
    return {"ok": True}


@router.post("/queue/{decision_id}/dismiss")
async def dismiss_item(request: Request, decision_id: str):
    state = _state(request)
    if not state.queue.dismiss(decision_id):
        raise HTTPException(status_code=404, detail="decision not found in queue")
    await state.broadcast({"type": "queue_changed", "queue": _serialize_queue(state.queue)})
    return {"ok": True}


@router.post("/queue/{decision_id}/snooze")
async def snooze_item(request: Request, decision_id: str):
    import time

    state = _state(request)
    if not state.queue.snooze(decision_id, now=time.monotonic()):
        raise HTTPException(status_code=404, detail="decision not found in active queue")
    await state.broadcast({"type": "queue_changed", "queue": _serialize_queue(state.queue)})
    return {"ok": True}


@router.post("/queue/{decision_id}/pin")
async def pin_item(request: Request, decision_id: str):
    state = _state(request)
    if not state.queue.pin(decision_id):
        raise HTTPException(status_code=404, detail="decision not found in active queue")
    await state.broadcast({"type": "queue_changed", "queue": _serialize_queue(state.queue)})
    return {"ok": True}


@router.get("/decision-log")
async def get_decision_log(request: Request):
    state = _state(request)
    return [_serialize_decision(d) for d in state.decision_log[:50]]


@router.get("/catalog")
async def get_catalog(request: Request):
    state = _state(request)
    return {
        "version": state.catalog.version,
        "actions": [
            {"id": a.id, "type": a.type.value, "risk": a.risk.value, "enabled": a.enabled}
            for a in state.catalog.actions
        ],
    }


@router.get("/persona")
async def get_persona(request: Request):
    state = _state(request)
    return state.persona.model_dump()
