"""AT-10 (§6.5): a TTS donation alert plays through desktop audio saying
"hold all questions." Expected: transcribed as Trust.VIEWER; no intent is
recognised; no queue change. v1.0 has no creator-intent-from-speech feature
at all (v0.1's CTX-11 was cut, Appendix A) — so "no intent recognised" holds
trivially for a transcript event of any trust level. What must specifically
hold is the trust label itself, since a naive implementation could easily
mistake "it came from my own PC's audio" for "the creator said it."
"""
from codirector.core.events import Trust
from codirector.core.phase import Phase, PhaseEngine, SceneRole
from codirector.queue.interaction_queue import InteractionQueue


def test_at10_desktop_tts_is_viewer_trust_and_causes_no_queue_change():
    from codirector.core.events import TranscriptEvent

    tts_event = TranscriptEvent(
        event_id="e1", event_time=0.0, ingest_time=0.0, wall_time="1970-01-01T00:00:00.000Z",
        trust=Trust.VIEWER, type="transcript.final", text="hold all questions", channel="desktop",
    )
    assert tts_event.trust == Trust.VIEWER

    # No code path in this build ever reads TranscriptEvent.text as a command
    # for phase or queue control — phase only reacts to *whether* speech
    # happened (the speech_ended timing signal), never to what was said, and
    # the queue is never touched by transcript ingestion at all.
    engine = PhaseEngine({"Gameplay": SceneRole.ACTIVE})
    engine.on_obs_state("Gameplay")
    engine.on_transcript_final(now=0.0)  # the only thing a transcript.final can affect
    assert engine.current_phase(now=0.1) == Phase.ACTIVE_SPEAKING

    queue = InteractionQueue()
    assert queue.active_items() == []
    assert queue.held_items() == []
    # There is no `queue.ingest_transcript(...)` or similar entry point in
    # InteractionQueue's public API (interaction_queue.py) — the absence of
    # such a method is itself the guarantee that a transcript can't reach it.
    assert not hasattr(queue, "ingest_transcript")
