"""AT-06 (§6.5): creator presses the kill switch during an active sequence.
Expected: pending requests stop within 250ms; OBS is frozen exactly as-is
(no attempted restoration — that's rollback's job, and rollback is
creator-initiated only, §5.9); autonomy moves to paused."""
import asyncio
import time

from codirector.adapters.obs.mock import MockOBSProvider
from codirector.core.models import Decision, Proposal
from codirector.orchestrator.obs_orchestrator import OBSOrchestrator
from codirector.policy.catalog import ActionCatalog

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


def _decision(decision_id: str) -> Decision:
    proposal = Proposal(
        cluster_id="c1", decision_type="SURFACE", action_id="show_question_overlay",
        parameters={}, representative_text="what keyboard do you use", response_angle="angle",
        relevance=0.9, rationale="rationale",
    )
    return Decision(
        decision_id=decision_id, correlation_id="corr-1", proposal=proposal,
        score=0.9, score_breakdown={}, created_at=0.0, expires_at=100.0, expected_pre_state={},
        policy_result="allowed",
    )


async def test_at06_kill_switch_freezes_within_250ms_and_leaves_obs_as_is():
    provider = MockOBSProvider()
    orchestrator = OBSOrchestrator(provider)
    action = CATALOG.get("show_question_overlay")

    # Simulate an in-flight, slow OBS call (a real overlay/effect sequence
    # mid-flight) so the kill switch has something active to cancel.
    original_set_input_text = provider.set_input_text

    async def slow_set_input_text(*args, **kwargs):
        await asyncio.sleep(2.0)
        await original_set_input_text(*args, **kwargs)

    provider.set_input_text = slow_set_input_text

    exec_task = asyncio.create_task(orchestrator.execute(_decision("in-flight"), action))
    await asyncio.sleep(0.05)  # let it actually start the slow call

    t0 = time.monotonic()
    orchestrator.kill_switch()
    result = await exec_task
    elapsed_ms = (time.monotonic() - t0) * 1000

    assert elapsed_ms < 250
    assert result.status == "frozen"
    assert "AI_Question_Text" not in provider.input_text  # never actually wrote the overlay text
    assert orchestrator.kill_switch_engaged is True

    # A second action attempted after the freeze is refused outright, not
    # queued, not retried.
    result2 = await orchestrator.execute(_decision("after-freeze"), action)
    assert result2.status == "frozen"
    assert provider.set_input_text_calls == []
