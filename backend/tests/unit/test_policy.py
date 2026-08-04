from codirector.adapters.obs.mock import MockOBSProvider
from codirector.config.models import PersonaConfig
from codirector.core.autonomy import AutonomyLevel
from codirector.core.models import Cluster
from codirector.orchestrator.obs_orchestrator import OBSOrchestrator
from codirector.policy.catalog import ActionCatalog
from codirector.policy.engine import PolicyEngine

CATALOG = ActionCatalog.model_validate(
    {
        "version": 1,
        "actions": [
            {
                "id": "show_question_overlay",
                "type": "overlay_text",
                "risk": "low",
                "target": {"input_name": "AI_Question_Text"},
                "limits": {"max_length": 120, "duration_ms": 8000, "cooldown_s": 45, "max_per_session": 2},
                "reversible": True,
            }
        ],
    }
)

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
        "cluster_id": "c1",
        "kind": "question",
        "representative_text": "what keyboard do you use",
        "member_event_ids": ["e1"],
        "unique_user_ids": {"u1", "u2", "u3"},
        "first_seen": 0.0,
        "last_seen": 0.0,
        "novelty": 0.8,
    }
    base.update(overrides)
    return Cluster(**base)


def _valid_raw_proposal(**overrides):
    base = {
        "cluster_id": "c1",
        "decision_type": "SURFACE",
        "action_id": "show_question_overlay",
        "parameters": {},
        "representative_text": "what keyboard do you use",
        "response_angle": "mention the keyboard brand",
        "relevance": 0.9,
        "rationale": "high relevance question cluster",
    }
    base.update(overrides)
    return base


def _new_engine() -> PolicyEngine:
    provider = MockOBSProvider()
    orchestrator = OBSOrchestrator(provider)
    return PolicyEngine(orchestrator)


async def _evaluate(engine=None, **kwargs):
    engine = engine or _new_engine()
    defaults = {
        "raw_proposal": _valid_raw_proposal(),
        "cluster": _cluster(),
        "persona": PERSONA,
        "autonomy": AutonomyLevel.CO_DIRECT,
        "catalog": CATALOG,
        "live_obs_state": {"program_scene": "Gameplay"},
        "now": 1000.0,
        "score": 0.9,
        "score_breakdown": {"relevance": 0.9},
        "expires_at": 1020.0,
        "expected_pre_state": {"program_scene": "Gameplay"},
        "correlation_id": "corr-1",
    }
    defaults.update(kwargs)
    return await engine.evaluate(**defaults)


async def test_happy_path_is_allowed():
    engine = _new_engine()
    decision = await _evaluate(engine)
    assert decision.policy_result == "allowed"
    assert decision.policy_rule_id is None
    assert engine.execution_results[decision.decision_id].status == "executed"


async def test_rule_1_rejects_schema():
    decision = await _evaluate(raw_proposal={**_valid_raw_proposal(), "extra_field": "not allowed"})
    assert decision.policy_result == "rejected"
    assert decision.policy_rule_id == "1"


async def test_rule_2_rejects_unknown_action():
    decision = await _evaluate(raw_proposal=_valid_raw_proposal(action_id="delete_source"))
    assert decision.policy_result == "rejected"
    assert decision.policy_rule_id == "2"


async def test_rule_3_rejects_observe_autonomy():
    decision = await _evaluate(autonomy=AutonomyLevel.OBSERVE)
    assert decision.policy_result == "rejected"
    assert decision.policy_rule_id == "3"


async def test_rule_3_rejects_assist_autonomy():
    decision = await _evaluate(autonomy=AutonomyLevel.ASSIST)
    assert decision.policy_result == "rejected"
    assert decision.policy_rule_id == "3"


async def test_rule_4_rejects_bad_parameter_key():
    decision = await _evaluate(raw_proposal=_valid_raw_proposal(parameters={"unexpected_key": 1}))
    assert decision.policy_result == "rejected"
    assert decision.policy_rule_id == "4"


async def test_rule_4_rejects_parameter_over_limit():
    decision = await _evaluate(raw_proposal=_valid_raw_proposal(parameters={"duration_ms": 99999}))
    assert decision.policy_result == "rejected"
    assert decision.policy_rule_id == "4"


async def test_rule_5_rejects_low_score():
    decision = await _evaluate(score=0.1)
    assert decision.policy_result == "rejected"
    assert decision.policy_rule_id == "5"


async def test_rule_6_rejects_within_cooldown():
    engine = _new_engine()
    first = await _evaluate(engine, now=1000.0)
    assert first.policy_result == "allowed"
    second = await _evaluate(engine, now=1010.0)  # cooldown_s=45, only 10s elapsed
    assert second.policy_result == "rejected"
    assert second.policy_rule_id == "6"


async def test_rule_7_rejects_over_budget():
    engine = _new_engine()
    # max_per_session=2 for this action; cooldown_s=45 so space calls out.
    r1 = await _evaluate(engine, now=0.0)
    r2 = await _evaluate(engine, now=100.0)
    r3 = await _evaluate(engine, now=200.0)
    assert r1.policy_result == "allowed"
    assert r2.policy_result == "allowed"
    assert r3.policy_result == "rejected"
    assert r3.policy_rule_id == "7"


async def test_rule_8_rejects_unsafe_public_text():
    decision = await _evaluate(
        raw_proposal=_valid_raw_proposal(representative_text="contact me at leak@example.com"),
    )
    assert decision.policy_result == "rejected"
    assert decision.policy_rule_id == "8"


async def test_rule_9_rejects_pre_state_drift():
    decision = await _evaluate(live_obs_state={"program_scene": "BRB"})
    assert decision.policy_result == "rejected"
    assert decision.policy_rule_id == "9"


async def test_rule_10_rejects_expired_decision():
    decision = await _evaluate(now=2000.0, expires_at=1500.0)
    assert decision.policy_result == "rejected"
    assert decision.policy_rule_id == "10"


async def test_extra_keys_rejected():
    decision = await _evaluate(raw_proposal={**_valid_raw_proposal(), "obs_password": "leak"})
    assert decision.policy_result == "rejected"
    assert decision.policy_rule_id == "1"


async def test_unknown_action_rejected():
    decision = await _evaluate(raw_proposal=_valid_raw_proposal(action_id="not_in_catalog"))
    assert decision.policy_result == "rejected"
    assert decision.policy_rule_id == "2"


async def test_hold_and_ignore_never_gate_through_execution_rules():
    decision = await _evaluate(raw_proposal=_valid_raw_proposal(decision_type="HOLD", action_id=None))
    assert decision.policy_result == "held"
    assert decision.policy_rule_id is None
