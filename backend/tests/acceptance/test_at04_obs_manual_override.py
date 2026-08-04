"""AT-04 (§6.5): the creator manually changes scene 200ms before a queued AI
sequence would execute. Expected: pre-state mismatch cancels the action; no
scene change happens via the AI path; no blind retry."""
from codirector.adapters.base import ReasoningPrompt
from codirector.adapters.obs.mock import MockOBSProvider
from codirector.core.autonomy import AutonomyLevel
from codirector.core.clustering import Clusterer
from codirector.core.events import ChatMessageEvent
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
                "id": "switch_to_break_scene",
                "type": "scene_switch",
                "risk": "low",
                "target": {"scene_name": "BRB"},
                "limits": {"cooldown_s": 300, "max_per_session": 4},
                "reversible": True,
            }
        ],
    }
)


class _ProposeSceneSwitch:
    async def propose(self, prompt: ReasoningPrompt) -> ReasoningResponse:
        c = prompt.cluster_context[0]
        return ReasoningResponse(
            proposals=[
                Proposal(
                    cluster_id=c["cluster_id"], decision_type="SURFACE", action_id="switch_to_break_scene",
                    parameters={}, representative_text=c["representative_text"], response_angle="",
                    relevance=0.95, rationale="scripted break transition",
                )
            ]
        )


async def test_at04_manual_scene_change_cancels_queued_action():
    obs = MockOBSProvider(scenes=["Gameplay", "BRB"], program_scene="Gameplay")
    orchestrator = OBSOrchestrator(obs)
    policy = PolicyEngine(orchestrator)
    queue = InteractionQueue()
    phase_engine = PhaseEngine({"Gameplay": SceneRole.ACTIVE, "BRB": SceneRole.BREAK})
    phase_engine.on_obs_state("Gameplay")

    pipeline = Pipeline(
        clusterer=Clusterer(), phase_engine=phase_engine, reasoning=_ProposeSceneSwitch(), policy=policy,
        interaction_queue=queue, persona=PERSONA, catalog=CATALOG, autonomy=AutonomyLevel.CO_DIRECT,
    )

    # 4 distinct viewers trigger the cluster that leads to the proposed scene switch.
    for i in range(4):
        event = ChatMessageEvent(
            event_id=f"e{i}", event_time=float(i), ingest_time=float(i),
            wall_time="1970-01-01T00:00:00.000Z", trust="viewer",
            user_id=f"user_{i}", display_name=f"user_{i}", text="lets take a break soon",
        )
        await pipeline.ingest_chat(event, now=float(i))

    # The AI's decision assumed pre-state program_scene="Gameplay" (still true
    # when the batch was queued 200ms ago), but by the time it's evaluated the
    # creator has *manually* already switched to BRB themselves — a fresh
    # live-state read reflects that, while the assumption is stale.
    obs.program_scene = "BRB"
    live_state = await obs.get_state()
    decisions = await pipeline.flush_batch(
        now=4.0,
        live_obs_state={"program_scene": live_state.program_scene},
        assumed_pre_state={"program_scene": "Gameplay"},
    )

    assert len(decisions) == 1
    assert decisions[0].policy_result == "rejected"
    assert decisions[0].policy_rule_id == "9"  # pre_state drift
    assert obs.set_scene_calls == []  # the orchestrator was never invoked
    assert obs.program_scene == "BRB"  # the creator's manual choice stands, untouched
