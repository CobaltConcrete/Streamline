"""Async pub/sub event bus. All pipeline components communicate only through
this — no component holds a direct reference to another's internals except the
one sanctioned exception (PolicyEngine -> OBSOrchestrator.execute, R-SAF-02)."""
import asyncio
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")
Handler = Callable[[T], Awaitable[None] | None]


class EventBus:
    """Topic-keyed async pub/sub. Topics are plain strings (e.g. an event's
    `type` field, or a synthetic topic like "decision.proposed"). A handler
    raising is logged and does not stop other handlers or the publisher."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[Handler]] = defaultdict(list)

    def subscribe(self, topic: str, handler: Handler) -> None:
        self._subscribers[topic].append(handler)

    def unsubscribe(self, topic: str, handler: Handler) -> None:
        handlers = self._subscribers.get(topic, [])
        if handler in handlers:
            handlers.remove(handler)

    async def publish(self, topic: str, payload: T) -> None:
        for handler in list(self._subscribers.get(topic, [])):
            try:
                result = handler(payload)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                logger.exception("event bus handler failed for topic=%s", topic)

    def publish_soon(self, topic: str, payload: T) -> None:
        """Schedule publish() on the running loop without awaiting — used by
        threadsafe callbacks (e.g. ASR worker thread via call_soon_threadsafe)."""
        asyncio.get_event_loop().create_task(self.publish(topic, payload))
