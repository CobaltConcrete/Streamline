"""AT-12 (§6.5): the app restarts mid-session while in Co-direct. Expected:
restarts in Observe; expired proposals are discarded; state is refreshed."""
from codirector.api.state import AppState
from codirector.core.autonomy import AutonomyLevel
from codirector.core.models import Decision, Proposal
from codirector.policy.catalog import ActionCatalog
from tests.unit.test_policy import PERSONA


def _decision(decision_id: str, expires_at: float) -> Decision:
    proposal = Proposal(
        cluster_id="c1", decision_type="SURFACE", action_id=None, parameters={},
        representative_text="text", response_angle="angle", relevance=0.8, rationale="rationale",
    )
    return Decision(
        decision_id=decision_id, correlation_id="corr-1", proposal=proposal,
        score=0.8, score_breakdown={}, created_at=0.0, expires_at=expires_at, expected_pre_state={},
    )


def test_at12_restart_always_lands_in_observe():
    catalog = ActionCatalog.model_validate({"version": 1, "actions": []})

    session_before_restart = AppState(persona=PERSONA, catalog=catalog)
    session_before_restart.set_autonomy(AutonomyLevel.CO_DIRECT)
    assert session_before_restart.autonomy == AutonomyLevel.CO_DIRECT

    # "Restart" = a brand new process, therefore a brand new AppState. There
    # is no code path that loads a prior autonomy value from disk (R-AUT-02)
    # — constructing a fresh instance IS the restart, and it always starts
    # OBSERVE (R-AUT-01) regardless of what the previous instance held.
    session_after_restart = AppState(persona=PERSONA, catalog=catalog)
    assert session_after_restart.autonomy == AutonomyLevel.OBSERVE


def test_at12_expired_proposals_discarded_on_resume():
    catalog = ActionCatalog.model_validate({"version": 1, "actions": []})
    state = AppState(persona=PERSONA, catalog=catalog)

    # Proposals queued before the "restart" carried an expiry relative to the
    # old session's clock; simulate that time has moved well past it.
    state.queue.offer(_decision("stale-1", expires_at=10.0), phase_is_safe=True, now=0.0)
    state.queue.offer(_decision("stale-2", expires_at=10.0), phase_is_safe=False, now=0.0)
    assert len(state.queue.active_items()) == 1
    assert len(state.queue.held_items()) == 1

    expired = state.queue.expire_items(now=100.0)  # "resume" happens long after expiry
    assert set(expired) == {"stale-1", "stale-2"}
    assert state.queue.active_items() == []
    assert state.queue.held_items() == []
