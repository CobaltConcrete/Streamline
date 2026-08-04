"""Deterministic Twitch provider that replays a fixture file. §8.2: "Fixtures
are the source of truth for mock providers. MockChatProvider replays a fixture
at either real time or fast-forward." Fast-forward (replay_realtime=False) is
the default so unit/integration tests stay fast and reproducible."""
import asyncio
import json
import time
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

from codirector.core.events import ChatMessageEvent, HealthEvent, SupportEvent

_EVENT_CLASS = {
    "chat.message": ChatMessageEvent,
    "support.sub": SupportEvent,
    "support.resub": SupportEvent,
    "support.cheer": SupportEvent,
    "support.raid": SupportEvent,
}


class MockTwitchProvider:
    def __init__(self, fixture_path: str | Path, replay_realtime: bool = False) -> None:
        self._fixture_path = Path(fixture_path)
        self._replay_realtime = replay_realtime
        self._connected = False
        self._seen_ids: set[str] = set()

    async def connect(self) -> None:
        self._connected = True

    async def events(self) -> AsyncIterator[ChatMessageEvent | SupportEvent]:
        raw = json.loads(self._fixture_path.read_text(encoding="utf-8"))
        start_mono = time.monotonic()
        fixture_t0 = raw[0]["event_time"] if raw else 0.0
        for item in raw:
            # R-CHT-02: duplicate message IDs are dropped.
            if item["event_id"] in self._seen_ids:
                continue
            self._seen_ids.add(item["event_id"])
            if self._replay_realtime:
                target = start_mono + (item["event_time"] - fixture_t0)
                delay = target - time.monotonic()
                if delay > 0:
                    await asyncio.sleep(delay)
            cls = _EVENT_CLASS[item["type"]]
            yield cls.model_validate(item)

    async def disconnect(self) -> None:
        self._connected = False

    @property
    def health(self) -> HealthEvent:
        now = time.monotonic()
        return HealthEvent(
            event_id=str(uuid.uuid4()),
            event_time=now,
            ingest_time=now,
            wall_time="1970-01-01T00:00:00.000Z",
            trust="system",
            component="twitch",
            status="ok" if self._connected else "down",
            detail="mock replaying fixture" if self._connected else "mock not connected",
        )
