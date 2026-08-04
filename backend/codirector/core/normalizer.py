"""Event normalizer — build spec v1.0 §8 component table: "common event
schema, deduplication, trust classification, PII redaction, rate limiting,
and backpressure." Per-adapter dedup/backpressure already exists where the
protocol is source-specific (Twitch message IDs, §5.3); this is the
cross-source safety net that sits between every adapter and the EventBus so a
duplicate event_id from *any* source is only ever forwarded once.

Trust classification and PII handling are intentionally NOT done here: trust
is assigned once, immutably, by the producing adapter (R-SAF-03), and content
safety/redaction is tier-specific (private vs public, §5.8) and applied at
the point of surfacing/rendering — not by mutating stored events, which would
break Cluster.representative_text's "verbatim from one member message"
contract (§4.2).
"""
from codirector.core.bus import EventBus
from codirector.core.events import Event


class Normalizer:
    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._seen_ids: set[str] = set()
        self.duplicate_count = 0

    async def ingest(self, event: Event) -> bool:
        """Returns True if the event was forwarded, False if it was a
        duplicate (already-seen event_id) and therefore dropped."""
        if event.event_id in self._seen_ids:
            self.duplicate_count += 1
            return False
        self._seen_ids.add(event.event_id)
        await self._bus.publish(event.type, event)
        return True
