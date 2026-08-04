"""AT-05 (§6.5): the reasoning provider exceeds its expiry window. Expected:
the decision is discarded as stale (rule 10, expiry); no action executes;
the real HTTP provider fails closed (empty proposals) on any network error,
including a timeout, rather than raising into the pipeline."""
from codirector.adapters.base import ReasoningPrompt
from codirector.adapters.obs.mock import MockOBSProvider
from codirector.adapters.reasoning.http import HTTPReasoningProvider
from codirector.core.autonomy import AutonomyLevel
from codirector.core.models import Cluster
from codirector.orchestrator.obs_orchestrator import OBSOrchestrator
from codirector.policy.catalog import ActionCatalog
from codirector.policy.engine import PolicyEngine
from tests.unit.test_policy import PERSONA

CATALOG = ActionCatalog.model_validate(
    {
        "version": 1,
        "actions": [
            {
                "id": "show_question_overlay", "type": "overlay_text", "risk": "low",
                "target": {"input_name": "AI_Question_Text"},
                "limits": {"max_length": 120, "duration_ms": 8000, "cooldown_s": 45, "max_per_session": 30},
                "reversible": True,
            }
        ],
    }
)


async def test_http_provider_fails_closed_when_unreachable():
    # Nothing is listening on this local port — connection fails immediately,
    # exercising the same "any provider error -> fail closed" branch a real
    # timeout would (aiohttp.ClientTimeout raises the same broad exception
    # class hierarchy this provider's blanket except catches).
    provider = HTTPReasoningProvider(endpoint="http://127.0.0.1:1/propose", model="test-model", timeout_s=0.5)

    response = await provider.propose(
        ReasoningPrompt(session_summary="", cluster_context=[], persona={})
    )
    assert response.proposals == []


async def test_at05_stale_decision_discarded_no_action_executes():
    obs = MockOBSProvider()
    orchestrator = OBSOrchestrator(obs)
    policy = PolicyEngine(orchestrator)

    cluster = Cluster(
        cluster_id="c1", kind="question", representative_text="what keyboard do you use",
        member_event_ids=["e1"], unique_user_ids={"u1", "u2", "u3"},
        first_seen=0.0, last_seen=0.0, novelty=0.8,
    )
    proposal = {
        "cluster_id": "c1", "decision_type": "SURFACE", "action_id": "show_question_overlay",
        "parameters": {}, "representative_text": "what keyboard do you use",
        "response_angle": "angle", "relevance": 0.9, "rationale": "rationale",
    }

    # The reasoning call was assigned a 20s expiry when it started at t=0, but
    # took so long to come back that "now" (evaluation time) is already t=25.
    decision = await policy.evaluate(
        raw_proposal=proposal, cluster=cluster, persona=PERSONA, autonomy=AutonomyLevel.CO_DIRECT,
        catalog=CATALOG, live_obs_state={"program_scene": "Gameplay"},
        now=25.0, score=0.9, score_breakdown={"relevance": 0.9},
        expires_at=20.0, expected_pre_state={"program_scene": "Gameplay"}, correlation_id="corr-1",
    )

    assert decision.policy_result == "rejected"
    assert decision.policy_rule_id == "10"
    assert decision.decision_id not in policy.execution_results  # never reached the orchestrator
    assert obs.set_input_text_calls == []
