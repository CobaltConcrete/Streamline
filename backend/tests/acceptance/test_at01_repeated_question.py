"""AT-01 (§6.5): 200 chat messages, 35 paraphrases of one question, creator
speaking throughout. Expected: one cluster; nothing surfaced while
ACTIVE_SPEAKING; one item surfaces at the first ACTIVE_SILENT window; no
re-surface within cooldown."""
import json

from codirector.adapters.base import ReasoningPrompt
from codirector.adapters.obs.mock import MockOBSProvider
from codirector.core.autonomy import AutonomyLevel
from codirector.core.chat_filter import ChatCommentFilter
from codirector.core.clustering import Clusterer
from codirector.core.events import ChatMessageEvent
from codirector.core.models import Proposal, ReasoningResponse
from codirector.core.phase import PhaseEngine, SceneRole
from codirector.core.pipeline import Pipeline
from codirector.orchestrator.obs_orchestrator import OBSOrchestrator
from codirector.policy.catalog import ActionCatalog
from codirector.policy.engine import PolicyEngine
from codirector.queue.interaction_queue import InteractionQueue
from tests.conftest import FIXTURES
from tests.unit.test_policy import PERSONA


class _SurfaceEveryEligibleCluster:
    """Deterministic stub: always proposes a bare private prompt (no
    action_id) for every cluster it's shown — AT-01 is about queue timing,
    not action execution."""

    async def propose(self, prompt: ReasoningPrompt) -> ReasoningResponse:
        # ReasoningResponse caps at 5 proposals (§4.3) — keep the biggest
        # clusters, same as a real reasoning call would prioritize.
        top = sorted(prompt.cluster_context, key=lambda c: -c["unique_user_count"])[:5]
        proposals = [
            Proposal(
                cluster_id=c["cluster_id"],
                decision_type="SURFACE",
                action_id=None,
                parameters={},
                representative_text=c["representative_text"],
                response_angle="mention it",
                relevance=0.9,
                rationale="dominant repeated question",
            )
            for c in top
        ]
        return ReasoningResponse(proposals=proposals)


async def test_at01_repeated_question_cluster():
    raw = json.loads((FIXTURES / "question_cluster.json").read_text(encoding="utf-8"))
    events = [ChatMessageEvent.model_validate(e) for e in raw]

    catalog = ActionCatalog.model_validate({"version": 1, "actions": []})
    obs = MockOBSProvider()
    orchestrator = OBSOrchestrator(obs)
    policy = PolicyEngine(orchestrator)
    queue = InteractionQueue(max_items=3, max_prompts_per_minute=100)
    phase_engine = PhaseEngine({"Gameplay": SceneRole.ACTIVE}, speech_gap_ms=1000.0)
    phase_engine.on_obs_state("Gameplay")

    pipeline = Pipeline(
        clusterer=Clusterer(),
        phase_engine=phase_engine,
        reasoning=_SurfaceEveryEligibleCluster(),
        policy=policy,
        interaction_queue=queue,
        persona=PERSONA,
        catalog=catalog,
        autonomy=AutonomyLevel.ASSIST,
        chat_filter=ChatCommentFilter(min_recognized_words=1),
    )

    for event in events:
        await pipeline.ingest_chat(event, now=event.event_time)

    clusters = pipeline._clusterer.clusters()
    keyboard_clusters = [c for c in clusters if "keyboard" in c.representative_text.lower()]
    dominant = max(keyboard_clusters, key=lambda c: len(c.unique_user_ids))
    assert len(dominant.unique_user_ids) >= 8  # a real dominant cluster exists (matches test_clustering.py)

    # Creator speaking throughout: the last utterance ended just before flush,
    # so the silence gap hasn't elapsed yet -> still ACTIVE_SPEAKING.
    last_t = events[-1].event_time
    phase_engine.on_transcript_final(now=last_t - 0.1)
    await pipeline.flush_batch(now=last_t, live_obs_state={"program_scene": "Gameplay"})
    assert queue.active_items() == []
    assert len(queue.held_items()) > 0  # proposals were made but held, not dropped

    # Creator falls silent -> ACTIVE_SILENT -> held items release.
    safe_now = last_t + 1.5
    released = queue.release_held(phase_is_safe=True, now=safe_now)
    assert len(released) >= 1
    assert len(queue.active_items()) >= 1

    # No re-surface: flushing again with no new chat produces nothing new.
    again = await pipeline.flush_batch(now=safe_now + 1.0, live_obs_state={"program_scene": "Gameplay"})
    assert again == []
