from codirector.core.models import Decision, Proposal
from codirector.queue.interaction_queue import InteractionQueue


def _decision(decision_id: str, score: float, expires_at: float = 1000.0) -> Decision:
    proposal = Proposal(
        cluster_id=f"c-{decision_id}",
        decision_type="SURFACE",
        action_id=None,
        parameters={},
        representative_text=f"text {decision_id}",
        response_angle="angle",
        relevance=0.8,
        rationale="rationale",
    )
    return Decision(
        decision_id=decision_id,
        correlation_id=f"corr-{decision_id}",
        proposal=proposal,
        score=score,
        score_breakdown={},
        created_at=0.0,
        expires_at=expires_at,
        expected_pre_state={},
    )


def test_max_three_evicts_lowest():
    q = InteractionQueue(max_items=3, max_prompts_per_minute=100)
    for i, score in enumerate([0.9, 0.8, 0.7]):
        assert q.offer(_decision(f"d{i}", score), phase_is_safe=True, now=float(i)) == "surfaced"
    assert {i.decision.decision_id for i in q.active_items()} == {"d0", "d1", "d2"}

    # A 4th, higher-scored item evicts the lowest-scored active item (d2, 0.7).
    result = q.offer(_decision("d3", 0.95), phase_is_safe=True, now=10.0)
    assert result == "surfaced"
    ids = {i.decision.decision_id for i in q.active_items()}
    assert ids == {"d0", "d1", "d3"}
    assert "d2" not in ids


def test_rate_limit():
    q = InteractionQueue(max_items=3, max_prompts_per_minute=2)
    assert q.offer(_decision("d0", 0.9), phase_is_safe=True, now=0.0) == "surfaced"
    assert q.offer(_decision("d1", 0.9), phase_is_safe=True, now=1.0) == "surfaced"
    # Third surface within the same 60s window exceeds max_prompts_per_minute.
    result = q.offer(_decision("d2", 0.9), phase_is_safe=True, now=2.0)
    assert result == "held"
    assert any(i.decision.decision_id == "d2" for i in q.held_items())


def test_expiry_logged():
    q = InteractionQueue(max_items=3, max_prompts_per_minute=100)
    q.offer(_decision("d0", 0.9, expires_at=10.0), phase_is_safe=True, now=0.0)
    expired = q.expire_items(now=11.0)
    assert expired == ["d0"]
    assert q.expired_log == ["d0"]
    assert q.active_items() == []


def test_kill_switch_clear_abandons_active_and_held_items():
    q = InteractionQueue(max_items=3, max_prompts_per_minute=100)
    q.offer(_decision("active", 0.9), phase_is_safe=True, now=0.0)
    q.offer(_decision("held", 0.8), phase_is_safe=False, now=0.0)

    assert set(q.clear_pending()) == {"active", "held"}
    assert q.active_items() == []
    assert q.held_items() == []
