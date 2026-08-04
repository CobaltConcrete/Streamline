"""Minimal end-to-end wiring used by the acceptance tests (§6.5) and,
eventually, the live app entrypoint. Ties together: Clusterer -> (micro-batch
for chat / immediate for support, R-CHT-04) -> ReasoningProvider -> Scorer ->
{PolicyEngine for action-bearing proposals, InteractionQueue for the private
view} -> Decision list.

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
from codirector.core.clustering import Clusterer, eligible_clusters
from codirector.core.events import ChatMessageEvent, SupportEvent
from codirector.core.models import Cluster, Decision, Proposal
from codirector.core.phase import PhaseEngine, is_safe_window
from codirector.core.scoring import score_proposal
from codirector.policy.catalog import ActionCatalog
from codirector.policy.engine import PolicyEngine
from codirector.queue.interaction_queue import InteractionQueue


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
        self._pending_cluster_ids: set[str] = set()
        self._already_surfaced_cluster_ids: set[str] = set()

    def _cluster_context(self, cluster: Cluster) -> dict:
        return {
            "cluster_id": cluster.cluster_id,
            "kind": cluster.kind,
            "unique_user_count": len(cluster.unique_user_ids),
            "representative_text": cluster.representative_text,
        }

    async def ingest_chat(self, event: ChatMessageEvent, now: float) -> Cluster:
        cluster = self._clusterer.add_message(event, now)
        if cluster.cluster_id not in self._already_surfaced_cluster_ids:
            self._pending_cluster_ids.add(cluster.cluster_id)
        return cluster

    async def flush_batch(
        self, now: float, live_obs_state: dict[str, str], assumed_pre_state: dict[str, str] | None = None
    ) -> list[Decision]:
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
