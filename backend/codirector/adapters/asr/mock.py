"""Deterministic ASR provider that replays tests/fixtures/transcript_session.json.
Implements adapters.base.ASRProvider. Used everywhere except a live GPU demo."""
import asyncio
import json
import time
import uuid
from collections.abc import Callable
from pathlib import Path

from codirector.core.events import HealthEvent, TranscriptEvent


class MockASRProvider:
    def __init__(self, fixture_path: str | Path, replay_realtime: bool = False) -> None:
        self._fixture_path = Path(fixture_path)
        self._replay_realtime = replay_realtime
        self._running = False
        self._task: asyncio.Task | None = None
        self._status: str = "down"

    async def start(self, on_event: Callable[[TranscriptEvent], None]) -> None:
        self._running = True
        self._status = "ok"
        raw = json.loads(self._fixture_path.read_text(encoding="utf-8"))

        async def _replay():
            start_mono = time.monotonic()
            t0 = raw[0]["event_time"] if raw else 0.0
            for item in raw:
                if not self._running:
                    break
                if self._replay_realtime:
                    target = start_mono + (item["event_time"] - t0)
                    delay = target - time.monotonic()
                    if delay > 0:
                        await asyncio.sleep(delay)
                on_event(TranscriptEvent.model_validate(item))

        self._task = asyncio.create_task(_replay())

    async def stop(self) -> None:
        self._running = False
        self._status = "down"
        if self._task:
            self._task.cancel()

    @property
    def health(self) -> HealthEvent:
        now = time.monotonic()
        return HealthEvent(
            event_id=str(uuid.uuid4()),
            event_time=now,
            ingest_time=now,
            wall_time="1970-01-01T00:00:00.000Z",
            trust="system",
            component="asr",
            status=self._status,
            detail="mock replaying fixture" if self._status == "ok" else "mock stopped",
        )
