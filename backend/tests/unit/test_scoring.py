from codirector.config.models import PersonaConfig
from codirector.core.models import Cluster, Proposal
from codirector.core.scoring import score_proposal

PERSONA = PersonaConfig.model_validate(
    {
        "name": "conversational",
        "weights": {"relevance": 0.30, "breadth": 0.25, "novelty": 0.15, "urgency": 0.15, "support_tier": 0.15},
        "thresholds": {"surface_min_score": 0.55, "max_queue_items": 3, "max_prompts_per_minute": 2},
        "banned_topics": [],
    }
)


def _cluster(**overrides):
    base = {
        "cluster_id": "c1", "kind": "question", "representative_text": "text",
        "member_event_ids": ["e1"], "unique_user_ids": {"u1", "u2", "u3", "u4"},
        "first_seen": 0.0, "last_seen": 0.0, "novelty": 0.5,
    }
    base.update(overrides)
    return Cluster(**base)


def _proposal(**overrides):
    base = {
        "cluster_id": "c1", "decision_type": "SURFACE", "action_id": "show_question_overlay",
        "parameters": {}, "representative_text": "text", "response_angle": "angle",
        "relevance": 0.8, "rationale": "rationale",
    }
    base.update(overrides)
    return Proposal(**base)


def test_pure_function():
    cluster = _cluster()
    proposal = _proposal()
    r1 = score_proposal(proposal, cluster, PERSONA, now=10.0, decision_ttl_s=20.0)
    r2 = score_proposal(proposal, cluster, PERSONA, now=10.0, decision_ttl_s=20.0)
    assert r1 == r2


def test_breakdown_complete():
    score, breakdown = score_proposal(_proposal(), _cluster(), PERSONA, now=5.0, decision_ttl_s=20.0)
    assert set(breakdown.keys()) == {"relevance", "breadth", "novelty", "urgency", "support_tier"}
    assert isinstance(score, float)


def test_model_confidence_is_inert():
    cluster = _cluster()
    proposal = _proposal()
    r1 = score_proposal(proposal, cluster, PERSONA, now=1.0, decision_ttl_s=20.0, model_reported_confidence=0.01)
    r2 = score_proposal(proposal, cluster, PERSONA, now=1.0, decision_ttl_s=20.0, model_reported_confidence=0.99)
    assert r1 == r2


def test_urgency_decays_toward_ttl():
    cluster = _cluster(first_seen=0.0)
    proposal = _proposal()
    _, early = score_proposal(proposal, cluster, PERSONA, now=1.0, decision_ttl_s=20.0)
    _, late = score_proposal(proposal, cluster, PERSONA, now=19.0, decision_ttl_s=20.0)
    assert early["urgency"] > late["urgency"]


def test_support_tier_only_for_support_events():
    cluster = _cluster()
    proposal = _proposal()
    _, chat = score_proposal(proposal, cluster, PERSONA, now=0.0, decision_ttl_s=20.0, is_support_event=False)
    _, support = score_proposal(proposal, cluster, PERSONA, now=0.0, decision_ttl_s=20.0, is_support_event=True)
    assert chat["support_tier"] == 0.0
    assert support["support_tier"] == 1.0
