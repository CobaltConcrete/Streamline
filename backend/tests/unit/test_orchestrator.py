from codirector.adapters.obs.mock import MockOBSProvider
from codirector.core.models import Decision, Proposal
from codirector.orchestrator.obs_orchestrator import OBSOrchestrator
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
            },
            {
                "id": "switch_to_break_scene",
                "type": "scene_switch",
                "risk": "medium",
                "target": {"scene_name": "BRB"},
                "limits": {"cooldown_s": 300, "max_per_session": 4},
                "reversible": True,
            },
        ],
    }
)


def _decision(decision_id="d1", action_id="show_question_overlay", text="what keyboard do you use"):
    proposal = Proposal(
        cluster_id="c1",
        decision_type="SURFACE",
        action_id=action_id,
        parameters={},
        representative_text=text,
        response_angle="angle",
        relevance=0.9,
        rationale="rationale",
    )
    return Decision(
        decision_id=decision_id,
        correlation_id="corr-1",
        proposal=proposal,
        score=0.9,
        score_breakdown={},
        created_at=0.0,
        expires_at=100.0,
        expected_pre_state={},
        policy_result="allowed",
    )


async def test_idempotent():
    provider = MockOBSProvider()
    orchestrator = OBSOrchestrator(provider)
    action = CATALOG.get("show_question_overlay")
    decision = _decision()

    r1 = await orchestrator.execute(decision, action)
    assert r1.status == "executed"
    assert provider.set_input_text_calls == [("AI_Question_Text", "what keyboard do you use")]

    r2 = await orchestrator.execute(decision, action)  # replay
    assert r2 is r1
    # No second OBS call was made.
    assert provider.set_input_text_calls == [("AI_Question_Text", "what keyboard do you use")]


async def test_post_state_recorded_for_scene_switch():
    provider = MockOBSProvider(scenes=["Gameplay", "BRB"], program_scene="Gameplay")
    orchestrator = OBSOrchestrator(provider)
    action = CATALOG.get("switch_to_break_scene")
    decision = _decision(decision_id="d2", action_id="switch_to_break_scene", text="")

    result = await orchestrator.execute(decision, action)
    assert result.status == "executed"
    assert result.post_state_matched is True
    assert provider.program_scene == "BRB"
