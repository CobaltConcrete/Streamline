from codirector.core.context import ContextWindow
from codirector.core.events import ChatMessageEvent


def _msg(event_id: str, event_time: float) -> ChatMessageEvent:
    return ChatMessageEvent(
        event_id=event_id,
        event_time=event_time,
        ingest_time=event_time,
        wall_time="1970-01-01T00:00:00.000Z",
        trust="viewer",
        user_id="u1",
        display_name="u1",
        text="hi",
    )


def test_window_eviction():
    window = ContextWindow(window_s=90.0)
    window.add(_msg("e1", 0.0), now=0.0)
    window.add(_msg("e2", 30.0), now=30.0)
    window.add(_msg("e3", 100.0), now=100.0)  # e1 (t=0) is now 100s old, outside 90s window

    ids = [e.event_id for e in window.events()]
    assert "e1" not in ids
    assert ids == ["e2", "e3"]


def test_window_retains_exactly_window_s():
    window = ContextWindow(window_s=10.0)
    for i in range(20):
        window.add(_msg(f"e{i}", float(i)), now=float(i))
    # at now=19, cutoff=9, so events with event_time >= 9 survive: e9..e19
    ids = [e.event_id for e in window.events()]
    assert ids == [f"e{i}" for i in range(9, 20)]
