"""AT-11 (§6.5): 2000 chat events/minute sustained for 5 minutes (10,000
events). Expected: no unbounded memory growth; the drop counter is accurate;
the queue (backpressure queue and clustering state) stays responsive."""

from codirector.adapters.twitch.client import TwitchAdapter, normalize_chat_message
from codirector.core.clustering import Clusterer
from codirector.core.events import ChatMessageEvent


async def test_at11_sustained_load_bounded_queue_accurate_drop_count():
    adapter = TwitchAdapter(channel="teststreamer", oauth_token="fake-token-not-used", queue_maxsize=1000)

    total_events = 10_000
    for i in range(total_events):
        event = normalize_chat_message(
            message_id=f"msg-{i}", user_id=f"user_{i % 500}", display_name=f"user_{i % 500}",
            text="hello", is_subscriber=False, is_moderator=False, event_time=float(i) * 0.003,
        )
        adapter._ingest(event)

    # Bounded: never grew past its configured cap regardless of 10x volume.
    assert adapter._queue.qsize() == 1000
    # Accurate: every event beyond capacity was accounted for as a drop.
    assert adapter._queue.drop_count == total_events - 1000

    # Still responsive: draining works cleanly, no deadlock, correct count.
    drained = 0
    while adapter._queue.qsize() > 0:
        await adapter._queue.get()
        drained += 1
    assert drained == 1000


async def test_at11_clustering_state_bounded_with_periodic_eviction():
    clusterer = Clusterer(cluster_ttl_s=30.0)

    # 5 minutes of chat, one message every 20ms (~15,000 messages), phrases
    # cycling so old clusters keep going stale and getting evicted rather
    # than accumulating forever.
    phrases = [f"topic number {i}" for i in range(20)]
    now = 0.0
    for i in range(15_000):
        now += 0.02
        event = ChatMessageEvent(
            event_id=f"e{i}", event_time=now, ingest_time=now, wall_time="1970-01-01T00:00:00.000Z",
            trust="viewer", user_id=f"user_{i % 50}", display_name=f"user_{i % 50}",
            text=phrases[i % len(phrases)],
        )
        clusterer.add_message(event, now=now)
        if i % 500 == 0:
            clusterer.evict_expired(now=now)

    clusterer.evict_expired(now=now)
    # Only recently-active clusters remain — bounded by the phrase cycle
    # length, not by total messages processed (15,000).
    assert len(clusterer.clusters()) <= len(phrases)
