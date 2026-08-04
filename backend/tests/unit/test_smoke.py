"""M0 exit criterion: pytest runs green with zero real dependencies."""
import asyncio

from codirector.adapters.asr.mock import MockASRProvider
from codirector.adapters.base import ReasoningPrompt
from codirector.adapters.obs.mock import MockOBSProvider
from codirector.adapters.reasoning.mock import MockReasoningProvider
from codirector.adapters.twitch.mock import MockTwitchProvider
from codirector.config.loader import load_app_config, load_persona
from codirector.core.bus import EventBus
from tests.conftest import FIXTURES

CONFIG_DIR = FIXTURES.parents[2] / "config"


def test_config_loads():
    app_cfg = load_app_config(CONFIG_DIR / "app.yaml")
    assert app_cfg.autonomy.startup_level == "OBSERVE"
    persona = load_persona(CONFIG_DIR / "personas" / "conversational.yaml")
    assert persona.name == "conversational"


async def test_event_bus_pubsub():
    bus = EventBus()
    received = []
    bus.subscribe("topic.a", lambda payload: received.append(payload))
    await bus.publish("topic.a", {"hello": "world"})
    assert received == [{"hello": "world"}]


async def test_mock_obs_provider_roundtrip():
    obs = MockOBSProvider()
    await obs.connect()
    await obs.set_scene("BRB")
    state = await obs.get_state()
    assert state.program_scene == "BRB"
    assert obs.health.status == "ok"


async def test_mock_twitch_provider_replays_fixture():
    provider = MockTwitchProvider(FIXTURES / "question_cluster.json")
    await provider.connect()
    count = 0
    async for _event in provider.events():
        count += 1
    assert count == 200


async def test_mock_asr_provider_emits_events():
    provider = MockASRProvider(FIXTURES / "transcript_session.json")
    events = []
    await provider.start(lambda e: events.append(e))
    await asyncio.sleep(0.2)
    await provider.stop()
    assert len(events) > 0


async def test_mock_reasoning_provider_is_deterministic():
    provider = MockReasoningProvider()
    prompt = ReasoningPrompt(
        session_summary="",
        cluster_context=[
            {
                "cluster_id": "c1",
                "kind": "question",
                "unique_user_count": 5,
                "representative_text": "what keyboard do you use",
            }
        ],
        persona={},
    )
    r1 = await provider.propose(prompt)
    r2 = await provider.propose(prompt)
    assert r1.model_dump() == r2.model_dump()
