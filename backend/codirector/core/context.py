"""Rolling context window — build spec v1.0 §5-6 CTX-06/R-CTX-01. Retains
exactly `rolling_window_s` of events (by event_time), evicting anything older
whenever a new event arrives or eviction is explicitly requested."""
from collections import deque
from dataclasses import dataclass, field

from codirector.core.events import Event


@dataclass
class ContextWindow:
    window_s: float

    _events: deque = field(default_factory=deque, init=False, repr=False)

    def add(self, event: Event, now: float) -> None:
        self._events.append(event)
        self.evict(now)

    def evict(self, now: float) -> None:
        cutoff = now - self.window_s
        while self._events and self._events[0].event_time < cutoff:
            self._events.popleft()

    def events(self) -> list[Event]:
        return list(self._events)

    def __len__(self) -> int:
        return len(self._events)
