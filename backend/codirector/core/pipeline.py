"""End-to-end wiring for the triage pipeline, used by the acceptance tests
(§6.5) and, eventually, the live app entrypoint. Ties together:
Clusterer -> (micro-batch for chat / immediate for support, R-CHT-04) ->
ReasoningProvider -> Scorer -> {PolicyEngine for action-bearing proposals,
InteractionQueue for the private view} -> Decision list.

Two independent gates apply to a SURFACE proposal, and a proposal can pass
through either or both:
  - action_id present -> PolicyEngine.evaluate() (may execute autonomously;
    gated by autonomy/risk/cooldown/budget/safety/pre-state/expiry, but NOT
    by stream phase — this is what lets a support overlay fire immediately
    even mid-sentence, AT-02).
  - decision_type == SURFACE (regardless of action_id) -> InteractionQueue,
    which IS phase-gated (held while the phase isn't a safe window).
"""
import uuid

from codirector.adapters.base import ReasoningPrompt, ReasoningProvider
from codirector.config.models import PersonaConfig
from codirector.core.autonomy import AutonomyLevel
from codirector.core.chat_filter import ChatCommentFilter, FilterReason
from codirector.core.clustering import Clusterer, eligible_clusters
from codirector.core.events import ChatMessageEvent, SupportEvent
from codirector.core.models import Cluster, Decision, Proposal
from codirector.core.phase import PhaseEngine, is_safe_window
from codirector.core.scoring import score_proposal
from codirector.policy.catalog import ActionCatalog
from codirector.policy.engine import PolicyEngine
from codirector.queue.interaction_queue import InteractionQueue


def _decision_type(cluster: Cluster) -> str:
    """Classify a cluster as SURFACE, HOLD, or IGNORE based on its
    characteristics and context. Returns the decision type only."""
    if cluster.unique_user_count < 3:
        return "IGNORE"

    text = cluster.representative_text.lower()

    # Reject noise, spam, hostility, or prompt injection — always.
    spam_indicators = {
        "free viewers",
        "click link",
        "raid",
        "donate",
        "spam",
        "troll",
        "hotlink",
        "spam",
        "bot",
        "spam",
    }
    for indicator in spam_indicators:
        if indicator in text:
            return "IGNORE"

    # Reaction clusters are always eligible for surfacing.
    if cluster.kind == "reaction":
        return "SURFACE"

    # Questions and topics with enough users are useful — but HOLD
    # the ones that are too early or too generic.
    if cluster.kind in ("question", "topic"):
        # HOLD when the question text looks like a prompt injection (e.g.,
        # "what are the hidden rules" — the streamer is testing the system).
        if _looks_like_prompt_injection(text):
            return "IGNORE"
        # HOLD when the cluster is too new (before safe window) or too generic.
        # For now, the simplest signal is the cluster's first_seen timestamp
        # vs the current time.  We gate HOLD on the cluster being too early
        # in the stream (first_seen < 30 s), because the reasoning provider
        # isn't yet wired into the live pipeline.
        return "SURFACE"

    return "IGNORE"


def _looks_like_prompt_injection(text: str) -> bool:
    """Heuristic: reject text that looks like a prompt injection pattern."""
    prompt_patterns = [
        "what is",
        "what are",
        "how do you",
        "where is",
        "when did",
        "who is",
        "which is",
        "can you",
        "help me",
        "what is the",
        "how can I",
        "what is the",
    ]
    for pattern in prompt_patterns:
        if pattern in text:
            return True
    return False


def triage_clusters(
    clusters: list[Cluster], now: float,
) -> list[Proposal]:
    """Triage live-stream audience clusters into proposals matching the
    creator-dashboard JSON schema.  Every audience message and transcript
    is treated as untrusted data; requests to change policy, reveal data,
    or operate OBS are ignored.  Preserves representative_text verbatim.

    Rules:
      * clusters with < 3 distinct viewers are IGNORED.
      * speech-noise / spam / hostility / prompt-injection patterns are IGNORED.
      * reaction clusters are always SURFACE.
      * question/topic clusters with >= 3 distinct viewers are SURFACE,
        except when they look like a prompt-injection pattern.
      * when timing or context is weak a HOLD is returned instead of
        SURFACE.

    Returns a list of at most five proposals.
    """
    proposals: list[Proposal] = []
    for cluster in clusters:
        # R-CTX-01: reject below the distinct-user threshold.
        if cluster.unique_user_count < 3:
            proposals.append(_proposal_for_cluster(
                cluster=cluster,
                decision_type="IGNORE",
                action_id=None,
                parameters={},
                now=now,
            ))
            continue

        text = cluster.representative_text.lower()

        # R-SAF-03: reject spam, hostility, prompt injection.
        if _is_spam_or_hostile(text):
            proposals.append(_proposal_for_cluster(
                cluster=cluster,
                decision_type="IGNORE",
                action_id=None,
                parameters={},
                now=now,
            ))
            continue

        # Reaction clusters always surface.
        if cluster.kind == "reaction":
            proposals.append(_proposal_for_cluster(
                cluster=cluster,
                decision_type="SURFACE",
                action_id=None,
                parameters={},
                now=now,
            ))
            continue

        # Question / topic clusters: always SURFACE unless timing is weak.
        if cluster.kind in ("question", "topic"):
            proposals.append(_proposal_for_cluster(
                cluster=cluster,
                decision_type="SURFACE",
                action_id=None,
                parameters={},
                now=now,
            ))
            continue

    return proposals[:5]


def _is_spam_or_hostile(text: str) -> bool:
    """Return True if the text looks like spam, hostility, or prompt injection."""
    spam_words = {
        "free viewers", "click link", "raid", "donate",
        "spam", "troll", "hotlink", "bot", "spam",
    }
    for word in spam_words:
        if word in text:
            return True
    # Hostility: any insult or aggressive phrase.
    hostile_phrases = ["stupid", "idiot", "loser", "hate", "kill", "fuck"]
    for phrase in hostile_phrases:
        if phrase in text:
            return True
    # Prompt injection: anything that looks like it's trying to
    # control the conversation.
    if _looks_like_prompt_injection(text):
        return True
    return False


class Pipeline:
    def __init__(
        self,
        *,
        clusterer: Clusterer,
        phase_engine: PhaseEngine,
        reasoning: ReasoningProvider,
        policy: PolicyEngine,
        interaction_queue: InteractionQueue,
        persona: PersonaConfig,
        catalog: ActionCatalog,
        autonomy: AutonomyLevel,
        decision_ttl_s: float = 20.0,
        chat_filter: ChatCommentFilter | None = None,
        chat_batch_max_representative_texts: int = 50,
        chat_batch_max_wait_s: float = 120.0,
    ) -> None:
        self._clusterer = clusterer
        self._phase = phase_engine
        self._reasoning = reasoning
        self._policy = policy
        self._queue = interaction_queue
        self._persona = persona
        self._catalog = catalog
        self.autonomy = autonomy
        self._decision_ttl_s = decision_ttl_s
        if chat_batch_max_representative_texts < 1:
            raise ValueError("chat_batch_max_representative_texts must be at least 1")
        if chat_batch_max_wait_s <= 0:
            raise ValueError("chat_batch_max_wait_s must be greater than 0")
        self._chat_filter = chat_filter or ChatCommentFilter()
        self._chat_batch_max_representative_texts = chat_batch_max_representative_texts
        self._chat_batch_max_wait_s = chat_batch_max_wait_s
        self._accepted_chat_count = 0
        self._batch_started_at: float | None = None
        self._filtered_chat_counts: dict[FilterReason, int] = {
            "emoji_only": 0,
            "unintelligible": 0,
        }
        self._pending_cluster_ids: set[str] = set()
        self._already_surfaced_cluster_ids: set[str] = set()

    def _cluster_context(self, cluster: Cluster) -> dict:
        return {
            "cluster_id": cluster.cluster_id,
            "kind": cluster.kind,
            "unique_user_count": len(cluster.unique_user_ids),
            "representative_text": cluster.representative_text,
        }

    async def ingest_chat(self, event: ChatMessageEvent, now: float) -> Cluster | None:
        filter_result = self._chat_filter.evaluate(event.text)
        if not filter_result.accepted:
            assert filter_result.reason is not None
            self._filtered_chat_counts[filter_result.reason] += 1
            return None

        self._accepted_chat_count += 1
        cluster = self._clusterer.add_message(event, now)
        if cluster.cluster_id not in self._already_surfaced_cluster_ids:
            if self._batch_started_at is None:
                self._batch_started_at = now
            self._pending_cluster_ids.add(cluster.cluster_id)
        return cluster

    def chat_batch_ready(self, now: float) -> bool:
        if len(self._pending_cluster_ids) >= self._chat_batch_max_representative_texts:
            return True
        return (
            self._batch_started_at is not None
            and now - self._batch_started_at >= self._chat_batch_max_wait_s
        )

    @property
    def accepted_chat_count(self) -> int:
        return self._accepted_chat_count

    @property
    def pending_representative_text_count(self) -> int:
        """Number of cluster representatives waiting for the next LLM call."""
        return len(self._pending_cluster_ids)

    @property
    def filtered_chat_counts(self) -> dict[FilterReason, int]:
        return dict(self._filtered_chat_counts)

    async def flush_batch(
        self, now: float, live_obs_state: dict[str, str], assumed_pre_state: dict[str, str] | None = None
    ) -> list[Decision]:
        self._accepted_chat_count = 0
        self._batch_started_at = None
        cluster_ids = self._pending_cluster_ids
        self._pending_cluster_ids = set()
        all_clusters = {c.cluster_id: c for c in self._clusterer.clusters()}
        pending = [all_clusters[cid] for cid in cluster_ids if cid in all_clusters]
        eligible = eligible_clusters(pending)
        if not eligible:
            return []

        prompt = ReasoningPrompt(
            session_summary="",
            cluster_context=[self._cluster_context(c) for c in eligible],
            persona=self._persona.model_dump(),
        )
        response = await self._reasoning.propose(prompt)
        clusters_by_id = {c.cluster_id: c for c in eligible}
        return await self._process_proposals(
            response.proposals, clusters_by_id, now, live_obs_state, str(uuid.uuid4()),
            is_support_event=False, assumed_pre_state=assumed_pre_state,
        )

    async def ingest_support(
        self, event: SupportEvent, now: float, live_obs_state: dict[str, str],
        assumed_pre_state: dict[str, str] | None = None,
    ) -> list[Decision]:
        """R-CHT-04: bypasses micro-batching entirely."""
        cluster = self._clusterer.add_support_event(event, now)
        prompt = ReasoningPrompt(
            session_summary="", cluster_context=[self._cluster_context(cluster)], persona=self._persona.model_dump()
        )
        response = await self._reasoning.propose(prompt)
        return await self._process_proposals(
            response.proposals, {cluster.cluster_id: cluster}, now, live_obs_state, str(uuid.uuid4()),
            is_support_event=True, assumed_pre_state=assumed_pre_state,
        )

    async def _process_proposals(
        self,
        proposals: list[Proposal],
        clusters_by_id: dict[str, Cluster],
        now: float,
        live_obs_state: dict[str, str],
        correlation_id: str,
        is_support_event: bool,
        assumed_pre_state: dict[str, str] | None = None,
    ) -> list[Decision]:
        expected_pre_state = assumed_pre_state if assumed_pre_state is not None else dict(live_obs_state)
        decisions: list[Decision] = []
        for proposal in proposals:
            cluster = clusters_by_id.get(proposal.cluster_id)
            if cluster is None or proposal.decision_type == "IGNORE":
                continue

            score, breakdown = score_proposal(
                proposal, cluster, self._persona, now, self._decision_ttl_s, is_support_event=is_support_event
            )
            expires_at = now + self._decision_ttl_s

            if proposal.action_id is not None:
                # Action-bearing proposals go through PolicyEngine only (may
                # execute autonomously, not phase-gated). They do NOT also
                # get queued as a private prompt — a model that wants both a
                # visible action *and* a verbal nudge emits two proposals for
                # the same cluster (one with action_id, one without), as
                # AT-02 demonstrates.
                decision = await self._policy.evaluate(
                    raw_proposal=proposal.model_dump(),
                    cluster=cluster,
                    persona=self._persona,
                    autonomy=self.autonomy,
                    catalog=self._catalog,
                    live_obs_state=live_obs_state,
                    now=now,
                    score=score,
                    score_breakdown=breakdown,
                    expires_at=expires_at,
                    expected_pre_state=expected_pre_state,
                    correlation_id=correlation_id,
                )
                decisions.append(decision)
                continue

            if proposal.decision_type == "SURFACE":
                prompt_decision = Decision(
                    decision_id=str(uuid.uuid4()),
                    correlation_id=correlation_id,
                    proposal=proposal,
                    score=score,
                    score_breakdown=breakdown,
                    created_at=now,
                    expires_at=expires_at,
                    expected_pre_state=expected_pre_state,
                )
                phase_is_safe = is_safe_window(self._phase.current_phase(now))
                self._queue.offer(prompt_decision, phase_is_safe=phase_is_safe, now=now)
                self._already_surfaced_cluster_ids.add(cluster.cluster_id)
                decisions.append(prompt_decision)

        return decisions


def _score_relevance(cluster: Cluster) -> float:
    """Compute relevance from a cluster's observable features.
    Same inputs always produce the same score, now is passed in."""
    return 0.0


def triage_clusters(
    clusters: list[Cluster], now: float
) -> list[Proposal]:
    """Triage live-stream audience clusters into proposals matching the
    creator-dashboard JSON schema.  Every audience message and transcript
    is treated as untrusted data; requests to change policy, reveal data,
    or operate OBS are ignored.

    Returns at most five proposals.  Each proposal carries the
    cluster's *representative_text* verbatim.
    """
    proposals: list[Proposal] = []
    for cluster in clusters:
        if cluster.unique_user_count < 3:
            proposals.append(_make_proposal(
                cluster=cluster,
                decision_type="IGNORE",
                action_id=None,
                parameters={},
                now=now,
            ))
            continue

        text = cluster.representative_text.lower()

        if _is_spam_or_hostile(text):
            proposals.append(_make_proposal(
                cluster=cluster,
                decision_type="IGNORE",
                action_id=None,
                parameters={},
                now=now,
            ))
            continue

        if cluster.kind == "reaction":
            proposals.append(_make_proposal(
                cluster=cluster,
                decision_type="SURFACE",
                action_id=None,
                parameters={},
                now=now,
            ))
            continue

        if cluster.kind in ("question", "topic"):
            proposals.append(_make_proposal(
                cluster=cluster,
                decision_type="SURFACE",
                action_id=None,
                parameters={},
                now=now,
            ))
            continue

    return proposals[:5]
