"""R-CHT-04: support events bypass micro-batching — scored/proposed
immediately via Pipeline.ingest_support, unlike chat which only produces
decisions after an explicit flush_batch() call."""
from codirector.adapters.base import ReasoningPrompt
from codirector.adapters.obs.mock import MockOBSProvider
from codirector.core.autonomy import AutonomyLevel
from codirector.core.clustering import Clusterer
from codirector.core.events import ChatMessageEvent, SupportEvent
from codirector.core.models import Proposal, ReasoningResponse
from codirector.core.phase import PhaseEngine, SceneRole
from codirector.core.pipeline import Pipeline
from codirector.orchestrator.obs_orchestrator import OBSOrchestrator
from codirector.policy.catalog import ActionCatalog
from codirector.policy.engine import PolicyEngine
from codirector.queue.interaction_queue import InteractionQueue
from tests.unit.test_policy import PERSONA


class _AlwaysSurface:
    async def propose(self, prompt: ReasoningPrompt) -> ReasoningResponse:
        c = prompt.cluster_context[0]
        return ReasoningResponse(
            proposals=[
                Proposal(
                    cluster_id=c["cluster_id"], decision_type="SURFACE", action_id=None,
                    parameters={}, representative_text=c["representative_text"], response_angle="angle",
                    relevance=0.9, rationale="rationale",
                )
            ]
        )


def _build_pipeline() -> Pipeline:
    catalog = ActionCatalog.model_validate({"version": 1, "actions": []})
    obs = MockOBSProvider()
    orchestrator = OBSOrchestrator(obs)
    policy = PolicyEngine(orchestrator)
    queue = InteractionQueue(max_items=3, max_prompts_per_minute=100)
    phase_engine = PhaseEngine({"Gameplay": SceneRole.ACTIVE})
    phase_engine.on_obs_state("Gameplay")
    return Pipeline(
        clusterer=Clusterer(), phase_engine=phase_engine, reasoning=_AlwaysSurface(), policy=policy,
        interaction_queue=queue, persona=PERSONA, catalog=catalog, autonomy=AutonomyLevel.ASSIST,
    )


async def test_support_event_bypasses_batch():
    pipeline = _build_pipeline()

    # A chat message alone produces nothing until flush_batch() is called.
    chat_event = ChatMessageEvent(
        event_id="c1", event_time=0.0, ingest_time=0.0, wall_time="1970-01-01T00:00:00.000Z",
        trust="viewer", user_id="u1", display_name="u1", text="hello",
    )
    await pipeline.ingest_chat(chat_event, now=0.0)
    assert pipeline._queue.active_items() == []  # nothing yet — still batched, unflushed

    # A support event produces a decision immediately, in the same call.
    support_event = SupportEvent(
        event_id="s1", event_time=0.0, ingest_time=0.0, wall_time="1970-01-01T00:00:00.000Z",
        trust="platform_verified", type="support.cheer", user_id="u2", display_name="u2",
        message="thanks!", amount=100,
    )
    decisions = await pipeline.ingest_support(support_event, now=0.0, live_obs_state={"program_scene": "Gameplay"})
    assert len(decisions) == 1
    assert pipeline._queue.active_items() != [] or pipeline._queue.held_items() != []
