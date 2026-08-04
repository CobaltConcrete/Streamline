from codirector.core.models import Decision, Proposal
from codirector.queue.interaction_queue import InteractionQueue


def _decision(decision_id: str, score: float) -> Decision:
    proposal = Proposal(
        cluster_id=f"c-{decision_id}", decision_type="SURFACE", action_id=None,
        parameters={}, representative_text=f"text {decision_id}", response_angle="angle",
        relevance=0.8, rationale="rationale",
    )
    return Decision(
        decision_id=decision_id, correlation_id=f"corr-{decision_id}", proposal=proposal,
        score=score, score_breakdown={}, created_at=0.0, expires_at=1000.0, expected_pre_state={},
    )


def test_held_until_safe_window():
    q = InteractionQueue(max_items=3, max_prompts_per_minute=100)
    result = q.offer(_decision("d0", 0.9), phase_is_safe=False, now=0.0)
    assert result == "held"
    assert q.active_items() == []
    assert len(q.held_items()) == 1

    released = q.release_held(phase_is_safe=True, now=1.0)
    assert released == ["d0"]
    assert [i.decision.decision_id for i in q.active_items()] == ["d0"]
    assert q.held_items() == []


def test_release_order():
    q = InteractionQueue(max_items=3, max_prompts_per_minute=100)
    q.offer(_decision("low", 0.5), phase_is_safe=False, now=0.0)
    q.offer(_decision("high", 0.95), phase_is_safe=False, now=0.0)
    q.offer(_decision("mid", 0.7), phase_is_safe=False, now=0.0)

    released = q.release_held(phase_is_safe=True, now=1.0)
    assert released == ["high", "mid", "low"]  # highest score first
