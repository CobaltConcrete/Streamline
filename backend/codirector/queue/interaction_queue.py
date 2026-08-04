"""Interaction queue — build spec v1.0 §5.10, ENG-01/02/03/06/07. At most 3
active items; a 4th evicts the lowest-scored (unless everything active is
pinned, in which case the newcomer waits). Items held while the phase isn't a
safe window release at the next safe window in score order (highest first).
"""
from dataclasses import dataclass

from codirector.core.models import Decision

_SNOOZE_S = 60.0
_RATE_WINDOW_S = 60.0


@dataclass
class QueueItem:
    decision: Decision
    pinned: bool = False
    snoozed_until: float | None = None


class InteractionQueue:
    def __init__(self, max_items: int = 3, max_prompts_per_minute: int = 2) -> None:
        self._max_items = max_items
        self._max_prompts_per_minute = max_prompts_per_minute
        self._active: list[QueueItem] = []
        self._held: list[QueueItem] = []
        self._surface_timestamps: list[float] = []
        self.expired_log: list[str] = []

    def offer(self, decision: Decision, phase_is_safe: bool, now: float) -> str:
        """Returns "surfaced" or "held". R-ENG-02: held while phase is unsafe."""
        item = QueueItem(decision=decision)
        if not phase_is_safe:
            self._held.append(item)
            return "held"
        return self._try_surface(item, now)

    def _try_surface(self, item: QueueItem, now: float) -> str:
        self._prune_rate_window(now)
        if len(self._surface_timestamps) >= self._max_prompts_per_minute:  # R-ENG-04
            self._held.append(item)
            return "held"

        if len(self._active) >= self._max_items:  # R-ENG-01
            evictable = [i for i in self._active if not i.pinned]
            if not evictable:
                self._held.append(item)
                return "held"
            lowest = min(evictable, key=lambda i: i.decision.score)
            self._active.remove(lowest)

        self._active.append(item)
        self._surface_timestamps.append(now)
        return "surfaced"

    def release_held(self, phase_is_safe: bool, now: float) -> list[str]:
        """R-ENG-03: held items release at the next safe window, highest
        score first."""
        if not phase_is_safe:
            return []
        released: list[str] = []
        still_held: list[QueueItem] = []
        for item in sorted(self._held, key=lambda i: -i.decision.score):
            if item.snoozed_until is not None and item.snoozed_until > now:
                still_held.append(item)
                continue
            result = self._try_surface(item, now)
            if result == "surfaced":
                released.append(item.decision.decision_id)
            else:
                still_held.append(item)
        self._held = still_held
        return released

    def expire_items(self, now: float) -> list[str]:
        """R-ENG-05: expired items are removed silently and logged."""
        expired_ids: list[str] = []

        keep_active = []
        for item in self._active:
            if item.decision.expires_at <= now:
                expired_ids.append(item.decision.decision_id)
            else:
                keep_active.append(item)
        self._active = keep_active

        keep_held = []
        for item in self._held:
            if item.decision.expires_at <= now:
                expired_ids.append(item.decision.decision_id)
            else:
                keep_held.append(item)
        self._held = keep_held

        self.expired_log.extend(expired_ids)
        return expired_ids

    def accept(self, decision_id: str) -> bool:
        return self._remove(decision_id)

    def dismiss(self, decision_id: str) -> bool:
        return self._remove(decision_id)

    def snooze(self, decision_id: str, now: float, duration_s: float = _SNOOZE_S) -> bool:
        for item in self._active:
            if item.decision.decision_id == decision_id:
                self._active.remove(item)
                item.snoozed_until = now + duration_s
                self._held.append(item)
                return True
        return False

    def pin(self, decision_id: str) -> bool:
        for item in self._active:
            if item.decision.decision_id == decision_id:
                item.pinned = True
                return True
        return False

    def clear_pending(self) -> list[str]:
        """Remove every active/held item when automation enters a safe state.

        A kill switch or adapter disconnect must abandon pending work rather
        than allowing stale decisions to fire after resume (R-SAF-04/05).
        """
        removed = [item.decision.decision_id for item in (*self._active, *self._held)]
        self._active.clear()
        self._held.clear()
        return removed

    def _remove(self, decision_id: str) -> bool:
        for collection in (self._active, self._held):
            for item in collection:
                if item.decision.decision_id == decision_id:
                    collection.remove(item)
                    return True
        return False

    def _prune_rate_window(self, now: float) -> None:
        self._surface_timestamps = [t for t in self._surface_timestamps if now - t < _RATE_WINDOW_S]

    def active_items(self) -> list[QueueItem]:
        return list(self._active)

    def held_items(self) -> list[QueueItem]:
        return list(self._held)
