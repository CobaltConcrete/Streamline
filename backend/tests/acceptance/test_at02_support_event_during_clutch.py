"""AT-02 (§6.5): a raid arrives while the creator is mid-sentence. Expected:
an approved low-distraction overlay may fire immediately; the private
prompt is held until the next safe window; both share a correlation_id."""
from codirector.adapters.base import ReasoningPrompt
from codirector.adapters.obs.mock import MockOBSProvider
from codirector.core.autonomy import AutonomyLevel
from codirector.core.clustering import Clusterer
from codirector.core.events import SupportEvent
from codirector.core.models import Proposal, ReasoningResponse
from codirector.core.phase import PhaseEngine, SceneRole
from codirector.core.pipeline import Pipeline
from codirector.orchestrator.obs_orchestrator import OBSOrchestrator
from codirector.policy.catalog import ActionCatalog
from codirector.policy.engine import PolicyEngine
from codirector.queue.interaction_queue import InteractionQueue
from tests.unit.test_policy import PERSONA

CATALOG = ActionCatalog.model_validate(
    {
        "version": 1,
        "actions": [
            {
                "id": "show_support_overlay",
                "type": "overlay_text",
                "risk": "low",
                "target": {"input_name": "AI_Support_Text"},
                "limits": {"max_length": 120, "duration_ms": 6000, "cooldown_s": 20, "max_per_session": 50},
                "reversible": True,
            }
        ],
    }
)


class _RaidReasoning:
    """Deterministic stub: emits both the overlay action proposal and a
    separate private-prompt proposal for the same raid cluster."""

    async def propose(self, prompt: ReasoningPrompt) -> ReasoningResponse:
        cluster_id = prompt.cluster_context[0]["cluster_id"]
        text = prompt.cluster_context[0]["representative_text"]
        return ReasoningResponse(
            proposals=[
                Proposal(
                    cluster_id=cluster_id, decision_type="SURFACE", action_id="show_support_overlay",
                    parameters={}, representative_text=text, response_angle="thank the raider",
                    relevance=0.95, rationale="verified raid event",
                ),
                Proposal(
                    cluster_id=cluster_id, decision_type="SURFACE", action_id=None,
                    parameters={}, representative_text=text, response_angle="mention the raid verbally",
                    relevance=0.95, rationale="verified raid event, private prompt",
                ),
            ]
        )


async def test_at02_raid_overlay_fires_immediately_private_prompt_held():
    obs = MockOBSProvider(scenes=["Gameplay"], program_scene="Gameplay", known_inputs=["AI_Support_Text"])
    orchestrator = OBSOrchestrator(obs)
    policy = PolicyEngine(orchestrator)
    queue = InteractionQueue(max_items=3, max_prompts_per_minute=100)
    phase_engine = PhaseEngine({"Gameplay": SceneRole.ACTIVE}, speech_gap_ms=1000.0)
    phase_engine.on_obs_state("Gameplay")
    phase_engine.on_transcript_final(now=99.95)  # creator mid-sentence right up to the raid

    pipeline = Pipeline(
        clusterer=Clusterer(), phase_engine=phase_engine, reasoning=_RaidReasoning(), policy=policy,
        interaction_queue=queue, persona=PERSONA, catalog=CATALOG, autonomy=AutonomyLevel.CO_DIRECT,
    )

    raid_event = SupportEvent(
        event_id="raid-1", event_time=100.0, ingest_time=100.0, wall_time="1970-01-01T00:00:00.000Z",
        trust="platform_verified", type="support.raid", user_id="raider1", display_name="RaiderOne",
        message=None, amount=250,
    )
    decisions = await pipeline.ingest_support(raid_event, now=100.0, live_obs_state={"program_scene": "Gameplay"})

    assert len(decisions) == 2
    correlation_ids = {d.correlation_id for d in decisions}
    assert len(correlation_ids) == 1  # both events share a correlation_id

    action_decision = next(d for d in decisions if d.proposal.action_id is not None)
    assert action_decision.policy_result == "allowed"
    assert policy.execution_results[action_decision.decision_id].status == "executed"
    assert obs.input_text["AI_Support_Text"]  # overlay actually rendered

    private_decision = next(d for d in decisions if d.proposal.action_id is None)
    assert queue.active_items() == []
    assert any(i.decision.decision_id == private_decision.decision_id for i in queue.held_items())
