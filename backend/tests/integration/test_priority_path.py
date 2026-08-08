"""R-CHT-04: support events bypass micro-batching — scored/proposed
immediately via Pipeline.ingest_support, unlike chat which only produces
decisions after an explicit flush_batch() call."""
from codirector.adapters.base import ReasoningPrompt
from codirector.adapters.obs.mock import MockOBSProvider
from codirector.core.autonomy import AutonomyLevel
from codirector.core.chat_filter import ChatCommentFilter
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


def _build_pipeline(**pipeline_options) -> Pipeline:
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
        chat_filter=ChatCommentFilter(min_recognized_words=1),
        **pipeline_options,
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


async def test_chat_batch_is_ready_on_count_or_deadline_and_resets_after_flush():
    pipeline = _build_pipeline(chat_batch_max_representative_texts=2, chat_batch_max_wait_s=120)

    first = ChatMessageEvent(
        event_id="c1", event_time=10.0, ingest_time=10.0,
        wall_time="1970-01-01T00:00:10.000Z", trust="viewer",
        user_id="u1", display_name="u1", text="hello streamer",
    )
    duplicate = first.model_copy(
        update={"event_id": "c2", "event_time": 11.0, "ingest_time": 11.0, "user_id": "u2"}
    )
    second_representative = first.model_copy(
        update={
            "event_id": "c3", "event_time": 12.0, "ingest_time": 12.0,
            "user_id": "u3", "text": "which mechanical keyboard works best",
        }
    )

    await pipeline.ingest_chat(first, now=10.0)
    assert pipeline.pending_representative_text_count == 1
    assert pipeline.chat_batch_ready(now=129.9) is False
    assert pipeline.chat_batch_ready(now=130.0) is True

    await pipeline.ingest_chat(duplicate, now=11.0)
    assert pipeline.accepted_chat_count == 2
    assert pipeline.pending_representative_text_count == 1
    assert pipeline.chat_batch_ready(now=11.0) is False

    await pipeline.ingest_chat(second_representative, now=12.0)
    assert pipeline.pending_representative_text_count == 2
    assert pipeline.chat_batch_ready(now=12.0) is True
    await pipeline.flush_batch(now=12.0, live_obs_state={"program_scene": "Gameplay"})
    assert pipeline.accepted_chat_count == 0
    assert pipeline.pending_representative_text_count == 0
    assert pipeline.chat_batch_ready(now=500.0) is False


async def test_filtered_chat_does_not_consume_batch_capacity_or_start_timer():
    pipeline = _build_pipeline(chat_batch_max_representative_texts=1, chat_batch_max_wait_s=1)
    emoji = ChatMessageEvent(
        event_id="emoji", event_time=0.0, ingest_time=0.0,
        wall_time="1970-01-01T00:00:00.000Z", trust="viewer",
        user_id="u1", display_name="u1", text="😂🔥",
    )
    gibberish = emoji.model_copy(
        update={"event_id": "gibberish", "user_id": "u2", "text": "asdfgh qwrty"}
    )

    assert await pipeline.ingest_chat(emoji, now=0.0) is None
    assert await pipeline.ingest_chat(gibberish, now=5.0) is None
    assert pipeline.accepted_chat_count == 0
    assert pipeline.chat_batch_ready(now=100.0) is False
    assert pipeline.filtered_chat_counts == {"emoji_only": 1, "unintelligible": 1}
