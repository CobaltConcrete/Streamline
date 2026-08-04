"""Rollback — build spec v1.0 §5.9. A separate, creator-initiated action,
never automatic (never triggered by the kill switch, never retried by
the pipeline). Restores the prior state captured by OBSOrchestrator before
the original action executed (R-ORC-03)."""
from dataclasses import dataclass

from codirector.orchestrator.obs_orchestrator import ActionType, OBSOrchestrator


@dataclass
class RollbackResult:
    decision_id: str
    succeeded: bool
    detail: str


async def rollback(orchestrator: OBSOrchestrator, decision_id: str) -> RollbackResult:
    prior = orchestrator.prior_state_for(decision_id)
    if prior is None:
        return RollbackResult(decision_id, False, "no prior state recorded (action was not reversible, or unknown decision_id)")

    executed = orchestrator._executed.get(decision_id)
    if executed is None or executed.status not in ("executed", "state_mismatch"):
        return RollbackResult(decision_id, False, "action was never executed; nothing to roll back")

    provider = orchestrator._provider
    try:
        if prior.action_type == ActionType.OVERLAY_TEXT:
            action = _find_action_for_decision(orchestrator, decision_id)
            await provider.set_input_text(action.target.input_name, prior.values["text"])
        elif prior.action_type == ActionType.SCENE_SWITCH:
            await provider.set_scene(prior.values["scene"])
        elif prior.action_type == ActionType.ITEM_VISIBILITY:
            action = _find_action_for_decision(orchestrator, decision_id)
            item_id = provider.resolve_item_id(action.target.scene_name, action.target.item_name)
            await provider.set_item_visibility(action.target.scene_name, item_id, prior.values["visible"])
        elif prior.action_type == ActionType.FILTER_TOGGLE:
            action = _find_action_for_decision(orchestrator, decision_id)
            await provider.set_filter_enabled(action.target.source_name, action.target.filter_name, prior.values["enabled"])
        else:
            return RollbackResult(decision_id, False, f"unsupported action type {prior.action_type}")
    except Exception as exc:  # noqa: BLE001
        return RollbackResult(decision_id, False, f"rollback failed: {exc}")

    return RollbackResult(decision_id, True, "prior state restored")


def _find_action_for_decision(orchestrator: OBSOrchestrator, decision_id: str):
    """Rollback needs the action's target (input/scene/item/filter name),
    which isn't stored in PriorState itself. Callers of rollback() in
    practice pass this via the audit log lookup; here the orchestrator is
    asked to keep a small side-table so rollback stays a pure function of
    (orchestrator, decision_id) for testability."""
    action = orchestrator._decision_actions.get(decision_id)
    if action is None:
        raise KeyError(f"no action recorded for decision {decision_id}")
    return action
