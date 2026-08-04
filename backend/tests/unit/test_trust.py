"""R-SAF-03: desktop-audio transcripts can never carry Trust.CREATOR — a TTS
donation readout is viewer-authored, not the creator speaking. Enforced at
the schema level (events.py) so no adapter can construct around it."""
import pytest
from pydantic import ValidationError

from codirector.adapters.asr.parakeet import ParakeetASRProvider
from codirector.core.events import Trust


def test_desktop_audio_is_viewer_trust():
    with pytest.raises(ValidationError):
        _build_transcript(channel="desktop", trust=Trust.CREATOR)

    event = _build_transcript(channel="desktop", trust=Trust.VIEWER)
    assert event.trust == Trust.VIEWER


def test_mic_audio_may_carry_creator_trust():
    event = _build_transcript(channel="mic", trust=Trust.CREATOR)
    assert event.trust == Trust.CREATOR


def test_parakeet_provider_assigns_trust_from_channel_not_content():
    mic_provider = ParakeetASRProvider(channel="mic")
    desktop_provider = ParakeetASRProvider(channel="desktop")
    assert mic_provider._trust == Trust.CREATOR
    assert desktop_provider._trust == Trust.VIEWER


def _build_transcript(channel: str, trust: Trust):
    from codirector.core.events import TranscriptEvent

    return TranscriptEvent(
        event_id="e1", event_time=0.0, ingest_time=0.0, wall_time="1970-01-01T00:00:00.000Z",
        trust=trust, type="transcript.final", text="hold all questions", channel=channel,
    )
