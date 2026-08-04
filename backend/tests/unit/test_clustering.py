import json

from codirector.core.clustering import Clusterer, eligible_clusters
from codirector.core.events import ChatMessageEvent, TranscriptEvent
from tests.conftest import FIXTURES


def _msg(user_id: str, text: str, t: float) -> ChatMessageEvent:
    return ChatMessageEvent(
        event_id=f"{user_id}-{t}",
        event_time=t,
        ingest_time=t,
        wall_time="1970-01-01T00:00:00.000Z",
        trust="viewer",
        user_id=user_id,
        display_name=user_id,
        text=text,
    )


def test_paraphrases_cluster():
    raw = json.loads((FIXTURES / "question_cluster.json").read_text(encoding="utf-8"))
    events = [ChatMessageEvent.model_validate(e) for e in raw]

    clusterer = Clusterer()
    for event in events:
        clusterer.add_message(event, now=event.event_time)

    clusters = clusterer.clusters()
    # 200 raw messages must compress into far fewer clusters than that.
    assert len(clusters) < 40

    keyboard_clusters = [c for c in clusters if "keyboard" in c.representative_text.lower()]
    largest_keyboard_cluster = max(keyboard_clusters, key=lambda c: len(c.unique_user_ids))
    # A meaningful majority of the 35 keyboard paraphrases collapse into one
    # dominant cluster (heuristic token-overlap clustering, not embeddings —
    # perfect recall across every phrasing variant isn't the bar).
    assert len(largest_keyboard_cluster.unique_user_ids) >= 8

    # None of the 15 unrelated filler phrases leak into that dominant cluster.
    unrelated_markers = ("monitor specs", "sub goal", "day going", "streaming", "tips for beginners")
    assert not any(m in largest_keyboard_cluster.representative_text.lower() for m in unrelated_markers)


def test_unique_user_threshold():
    clusterer = Clusterer()
    t = 0.0
    for i in range(2):  # only 2 unique users
        clusterer.add_message(_msg(f"user_{i}", "what keyboard do you use", t), now=t)
        t += 0.1
    clusters = clusterer.clusters()
    assert eligible_clusters(clusters) == []  # below the 3-unique-user floor

    clusterer.add_message(_msg("user_2", "what keyboard do you use", t), now=t)
    clusters = clusterer.clusters()
    assert len(eligible_clusters(clusters)) == 1


def test_spam_does_not_qualify():
    clusterer = Clusterer()
    t = 0.0
    users = ["spammer_a", "spammer_b"]
    for i in range(20):
        clusterer.add_message(_msg(users[i % 2], "FREE VIEWERS CLICK LINK", t), now=t)
        t += 0.05
    clusters = clusterer.clusters()
    assert len(clusters) == 1  # 20 identical messages collapse into one cluster...
    assert eligible_clusters(clusters) == []  # ...but only 2 unique users, so it never qualifies


def test_partial_supersede_no_duplicates():
    raw = json.loads((FIXTURES / "transcript_session.json").read_text(encoding="utf-8"))
    events = [TranscriptEvent.model_validate(e) for e in raw]

    clusterer = Clusterer()
    processed = 0
    for event in events:
        result = clusterer.ingest_transcript(event, now=event.event_time)
        if result is not None:
            processed += 1

    final_count = sum(1 for e in events if e.type == "transcript.final")
    assert processed == final_count  # partials and speech_ended never contributed
    total_members = sum(len(c.member_event_ids) for c in clusterer.clusters())
    assert total_members == final_count  # no duplicate members from superseded partials
