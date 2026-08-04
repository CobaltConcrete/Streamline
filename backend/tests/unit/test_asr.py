"""R-ASR-01/02, exercised against MockASRProvider (§8.1: every protocol has a
deterministic mock used everywhere except a live GPU demo)."""
import asyncio

from codirector.adapters.asr.mock import MockASRProvider
from tests.conftest import FIXTURES


async def test_partial_and_final_timestamps():
    provider = MockASRProvider(FIXTURES / "transcript_session.json")
    events = []
    await provider.start(lambda e: events.append(e))
    await asyncio.sleep(0.2)
    await provider.stop()

    assert any(e.type == "transcript.partial" for e in events)
    assert any(e.type == "transcript.final" for e in events)
    for e in events:
        assert isinstance(e.event_time, float)
        assert isinstance(e.ingest_time, float)


async def test_speech_ended_marker():
    provider = MockASRProvider(FIXTURES / "transcript_session.json")
    events = []
    await provider.start(lambda e: events.append(e))
    await asyncio.sleep(0.2)
    await provider.stop()

    speech_ended = [e for e in events if e.type == "transcript.speech_ended"]
    assert len(speech_ended) > 0
    for e in speech_ended:
        assert isinstance(e.event_time, float)
