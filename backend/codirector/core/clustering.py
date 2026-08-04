"""Local (no-LLM) clustering — build spec v1.0 §5-6, R-CTX-02/03/04. Groups
near-duplicate chat messages by token-overlap similarity so the reasoning
provider sees one representative item per topic instead of every message.

This is a heuristic, not semantic embeddings — acceptable per §7 M2's own
framing ("local clustering (no LLM)"). A cluster's *centroid* is the union of
every member's tokens seen so far, which lets loosely related paraphrases
join transitively as the cluster's vocabulary grows, without needing every
pair of messages to share a word directly.
"""
import re
import uuid
from dataclasses import dataclass, field

from codirector.core.events import ChatMessageEvent, SupportEvent, TranscriptEvent
from codirector.core.models import Cluster

_CREATOR_SPEECH_USER_ID = "creator"

_STOPWORDS = {
    "the", "a", "an", "is", "are", "do", "does", "you", "your", "to", "of", "in", "on",
    "for", "and", "that", "this", "it", "what", "whats", "that's", "yo", "u", "ur",
    "pls", "please", "info", "name", "brand", "plz", "rn", "today", "have", "has",
    "with", "at", "as", "be", "can", "could", "would", "should", "i", "im", "my",
}

_QUESTION_STARTERS = ("what", "why", "how", "who", "when", "where", "which", "can", "do", "is", "yo")

# A tiny, generically-useful abbreviation table (not fixture-specific slang
# invention) — chat commonly abbreviates common nouns, and folding these
# before tokenizing meaningfully improves recall without semantic modeling.
_SYNONYMS = {"kb": "keyboard"}


def _tokenize(text: str) -> set[str]:
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    tokens = set()
    for word in text.split():
        word = _SYNONYMS.get(word, word)
        if word in _STOPWORDS or len(word) <= 1:
            continue
        # naive suffix stripping to fold minor plural/gerund variants together
        for suffix in ("ing", "es", "s"):
            if word.endswith(suffix) and len(word) > len(suffix) + 2:
                word = word[: -len(suffix)]
                break
        tokens.add(word)
    return tokens


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    # Require at least two overlapping tokens (or a perfect single-token
    # match) before a small set's Jaccard ratio alone can trigger a merge —
    # otherwise one coincidental shared filler word between otherwise
    # unrelated short messages produces a spuriously high ratio.
    intersection = a & b
    if len(intersection) < 2 and a != b:
        return 0.0
    return len(intersection) / len(a | b)


def _looks_like_question(text: str) -> bool:
    t = text.strip().lower()
    if t.endswith("?"):
        return True
    return t.startswith(_QUESTION_STARTERS)


@dataclass
class Clusterer:
    similarity_threshold: float = 0.24
    cluster_ttl_s: float = 90.0
    _clusters: dict[str, Cluster] = field(default_factory=dict)
    _centroid_tokens: dict[str, set[str]] = field(default_factory=dict)
    _novelty_pool: list[set[str]] = field(default_factory=list)

    def add_message(self, event: ChatMessageEvent, now: float) -> Cluster:
        tokens = _tokenize(event.text)
        best_id, best_score = None, 0.0
        for cid, centroid in self._centroid_tokens.items():
            if now - self._clusters[cid].last_seen > self.cluster_ttl_s:
                continue  # expired; do not merge into a stale cluster
            score = _jaccard(tokens, centroid)
            if score > best_score:
                best_id, best_score = cid, score

        if best_id is not None and best_score >= self.similarity_threshold:
            cluster = self._clusters[best_id]
            updated = cluster.model_copy(
                update={
                    "member_event_ids": [*cluster.member_event_ids, event.event_id],
                    "unique_user_ids": cluster.unique_user_ids | {event.user_id},
                    "last_seen": now,
                }
            )
            self._clusters[best_id] = updated
            self._centroid_tokens[best_id] = self._centroid_tokens[best_id] | tokens
            return updated

        cid = str(uuid.uuid4())
        cluster = Cluster(
            cluster_id=cid,
            kind="question" if _looks_like_question(event.text) else "topic",
            representative_text=event.text,
            member_event_ids=[event.event_id],
            unique_user_ids={event.user_id},
            first_seen=now,
            last_seen=now,
            novelty=self._novelty(tokens),
        )
        self._clusters[cid] = cluster
        self._centroid_tokens[cid] = tokens
        self._novelty_pool.append(tokens)
        if len(self._novelty_pool) > 50:
            self._novelty_pool.pop(0)
        return cluster

    def add_support_event(self, event: SupportEvent, now: float) -> Cluster:
        """Support events (subs/cheers/raids) are each their own cluster —
        R-CHT-04's bypass-the-batch treatment means there's no accumulation
        window to merge them within. kind="reaction": §4.2 has no dedicated
        "support" kind, and a verified support event is exactly the kind of
        celebratory/reaction-worthy moment that category describes."""
        cid = str(uuid.uuid4())
        text = event.message or f"{event.display_name} — {event.type}"
        cluster = Cluster(
            cluster_id=cid,
            kind="reaction",
            representative_text=text,
            member_event_ids=[event.event_id],
            unique_user_ids={event.user_id},
            first_seen=now,
            last_seen=now,
            novelty=1.0,
        )
        self._clusters[cid] = cluster
        self._centroid_tokens[cid] = _tokenize(text)
        return cluster

    def ingest_transcript(self, event: TranscriptEvent, now: float) -> Cluster | None:
        """R-ASR-03: partial transcripts are provisional and get rewritten by
        the final — only "transcript.final" ever becomes a cluster member, so
        a superseded partial can never create a duplicate. speech_ended is a
        phase-inference marker (§5.5), not clusterable content."""
        if event.type != "transcript.final":
            return None
        pseudo_message = ChatMessageEvent(
            event_id=event.event_id,
            event_time=event.event_time,
            ingest_time=event.ingest_time,
            wall_time=event.wall_time,
            trust=event.trust,
            user_id=_CREATOR_SPEECH_USER_ID,
            display_name="creator",
            text=event.text,
        )
        return self.add_message(pseudo_message, now)

    def _novelty(self, tokens: set[str]) -> float:
        if not self._novelty_pool:
            return 1.0
        max_sim = max((_jaccard(tokens, prev) for prev in self._novelty_pool), default=0.0)
        return max(0.0, 1.0 - max_sim)

    def evict_expired(self, now: float) -> list[str]:
        expired = [cid for cid, c in self._clusters.items() if now - c.last_seen > self.cluster_ttl_s]
        for cid in expired:
            del self._clusters[cid]
            del self._centroid_tokens[cid]
        return expired

    def clusters(self) -> list[Cluster]:
        return list(self._clusters.values())


def eligible_clusters(clusters: list[Cluster], min_unique_users: int = 3) -> list[Cluster]:
    """R-CTX-03/04: a cluster must have >= min_unique_users distinct authors
    to be eligible for surfacing. This is what keeps 20 identical spam
    messages from 2 accounts from ever reaching the reasoning provider."""
    return [c for c in clusters if len(c.unique_user_ids) >= min_unique_users]
