"""Generic bounded queue with oldest-dropped semantics — build spec v1.0
§5.3 R-CHT-03. Used by adapters that can receive events faster than the
pipeline consumes them (Twitch chat under load being the primary case)."""
import asyncio
from dataclasses import dataclass, field


@dataclass
class BoundedDropOldestQueue[T]:
    maxsize: int = 1000
    _queue: asyncio.Queue = field(init=False, repr=False)
    drop_count: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        self._queue = asyncio.Queue(maxsize=self.maxsize)

    def put_nowait(self, item: T) -> None:
        if self._queue.full():
            try:
                self._queue.get_nowait()  # drop the oldest
                self.drop_count += 1
            except asyncio.QueueEmpty:
                pass
        self._queue.put_nowait(item)

    async def get(self) -> T:
        return await self._queue.get()

    def qsize(self) -> int:
        return self._queue.qsize()
