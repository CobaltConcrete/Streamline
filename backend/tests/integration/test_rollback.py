from codirector.adapters.obs.mock import MockOBSProvider
from codirector.core.models import Decision, Proposal
from codirector.orchestrator.obs_orchestrator import OBSOrchestrator
from codirector.orchestrator.rollback import rollback
from codirector.policy.catalog import ActionCatalog

CATALOG = ActionCatalog.model_validate(
    {
        "version": 1,
        "actions": [
            {
                "id": "show_question_overlay",
                "type": "overlay_text",
                "risk": "low",
                "target": {"input_name": "AI_Question_Text"},
                "limits": {"max_length": 120, "duration_ms": 8000, "cooldown_s": 45, "max_per_session": 30},
                "reversible": True,
            }
        ],
    }
)


async def test_restores_prior_state():
    provider = MockOBSProvider()
    provider.input_text["AI_Question_Text"] = "previous text"
    orchestrator = OBSOrchestrator(provider)
    action = CATALOG.get("show_question_overlay")

    proposal = Proposal(
        cluster_id="c1",
        decision_type="SURFACE",
        action_id="show_question_overlay",
        parameters={},
        representative_text="new overlay text",
        response_angle="angle",
        relevance=0.9,
        rationale="rationale",
    )
    decision = Decision(
        decision_id="d1",
        correlation_id="corr-1",
        proposal=proposal,
        score=0.9,
        score_breakdown={},
        created_at=0.0,
        expires_at=100.0,
        expected_pre_state={},
        policy_result="allowed",
    )

    result = await orchestrator.execute(decision, action)
    assert result.status == "executed"
    assert provider.input_text["AI_Question_Text"] == "new overlay text"

    rollback_result = await rollback(orchestrator, "d1")
    assert rollback_result.succeeded is True
    assert provider.input_text["AI_Question_Text"] == "previous text"


async def test_rollback_unknown_decision_fails_cleanly():
    provider = MockOBSProvider()
    orchestrator = OBSOrchestrator(provider)
    result = await rollback(orchestrator, "does-not-exist")
    assert result.succeeded is False
