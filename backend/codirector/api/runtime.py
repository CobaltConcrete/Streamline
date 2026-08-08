"""Live Twitch-to-reasoning runtime owned by the FastAPI application."""

import asyncio
import time
import uuid
from contextlib import suppress
from datetime import UTC, datetime

from codirector.adapters.base import ReasoningPrompt, ReasoningProvider
from codirector.adapters.twitch.client import TwitchAdapter
from codirector.api.state import AppState
from codirector.core.chat_filter import ChatCommentFilter
from codirector.core.clustering import Clusterer
from codirector.core.events import ChatMessageEvent, SupportEvent


def _wall_time() -> str:
    return datetime.now(UTC).isoformat()


class LiveChatRuntime:
    """Collect filtered Twitch chat, flush batches, and publish LLM results."""

    def __init__(
        self,
        *,
        state: AppState,
        twitch: TwitchAdapter,
        reasoning: ReasoningProvider,
        clusterer: Clusterer,
        chat_filter: ChatCommentFilter,
        max_representative_texts: int,
        max_wait_s: float,
    ) -> None:
        self.state = state
        self._twitch = twitch
        self._reasoning = reasoning
        self._clusterer = clusterer
        self._chat_filter = chat_filter
        self._max_representative_texts = max_representative_texts
        self._max_wait_s = max_wait_s
        self._pending_cluster_ids: set[str] = set()
        self._processed_cluster_ids: set[str] = set()
        self._batch_started_at: float | None = None
        self._lock = asyncio.Lock()
        self._tasks: list[asyncio.Task] = []
        self._stopping = False

    async def start(self) -> None:
        self.state.health["twitch"].status = "degraded"
        self.state.health["twitch"].detail = "connecting"
        self.state.health["reasoning"].status = "ok"
        self.state.health["reasoning"].detail = "configured; waiting for a chat batch"
        await self.state.broadcast({"type": "health_changed", "health": self._health()})
        reasoning_start = getattr(self._reasoning, "start", None)
        if reasoning_start is not None:
            await reasoning_start()
        await self._twitch.connect()
        self._tasks = [
            asyncio.create_task(self._consume_twitch(), name="twitch-chat-consumer"),
            asyncio.create_task(self._deadline_loop(), name="chat-batch-deadline"),
            asyncio.create_task(self._health_loop(), name="twitch-health-monitor"),
        ]

    async def stop(self) -> None:
        self._stopping = True
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with suppress(asyncio.CancelledError):
                await task
        await self._twitch.disconnect()
        reasoning_stop = getattr(self._reasoning, "stop", None)
        if reasoning_stop is not None:
            await reasoning_stop()
        self.state.health["twitch"].status = "down"
        self.state.health["twitch"].detail = "stopped"

    async def _consume_twitch(self) -> None:
        async for event in self._twitch.events():
            if isinstance(event, ChatMessageEvent):
                await self.handle_chat(event)
            elif isinstance(event, SupportEvent):
                await self.state.broadcast(
                    {"type": "support_received", "support_type": event.type}
                )

    async def handle_chat(self, event: ChatMessageEvent, now: float | None = None) -> None:
        """Ingest one event; public for deterministic runtime tests."""
        current = time.monotonic() if now is None else now
        result = self._chat_filter.evaluate(event.text)
        chat_item = {
            "message_id": event.event_id,
            "display_name": event.display_name,
            "text": event.text,
            "accepted": result.accepted,
            "filter_reason": result.reason,
            "received_at": _wall_time(),
        }
        self.state.record_chat(chat_item)
        await self.state.broadcast(
            {"type": "chat_received", "chat": chat_item, "recent_chat": self.state.recent_chat}
        )
        if not result.accepted:
            return

        should_flush = False
        async with self._lock:
            cluster = self._clusterer.add_message(event, current)
            if cluster.cluster_id not in self._processed_cluster_ids:
                self._pending_cluster_ids.add(cluster.cluster_id)
                if self._batch_started_at is None:
                    self._batch_started_at = current
            should_flush = len(self._pending_cluster_ids) >= self._max_representative_texts
        if should_flush:
            await self.flush_batch(current)

    async def flush_if_due(self, now: float | None = None) -> bool:
        current = time.monotonic() if now is None else now
        async with self._lock:
            due = (
                self._batch_started_at is not None
                and current - self._batch_started_at >= self._max_wait_s
            )
        if due:
            await self.flush_batch(current)
        return due

    async def flush_batch(self, now: float | None = None) -> None:
        async with self._lock:
            if not self._pending_cluster_ids:
                return
            pending_ids = set(self._pending_cluster_ids)
            self._pending_cluster_ids.clear()
            self._processed_cluster_ids.update(pending_ids)
            self._batch_started_at = None
            clusters_by_id = {
                cluster.cluster_id: cluster
                for cluster in self._clusterer.clusters()
                if cluster.cluster_id in pending_ids
            }

        clusters = sorted(clusters_by_id.values(), key=lambda item: item.first_seen)
        context = [
            {
                "cluster_id": cluster.cluster_id,
                "kind": cluster.kind,
                "unique_user_count": len(cluster.unique_user_ids),
                "representative_text": cluster.representative_text,
            }
            for cluster in clusters
        ]
        batch_id = str(uuid.uuid4())
        self.state.health["reasoning"].status = "degraded"
        self.state.health["reasoning"].detail = f"analyzing {len(context)} representative texts"
        await self.state.broadcast({"type": "health_changed", "health": self._health()})
        started = time.perf_counter()
        response = await self._reasoning.propose(
            ReasoningPrompt(
                session_summary="",
                cluster_context=context,
                persona=self.state.persona.model_dump(),
            )
        )
        elapsed = time.perf_counter() - started
        counts = {
            cluster.cluster_id: len(cluster.unique_user_ids) for cluster in clusters
        }
        analyzed_at = _wall_time()
        items = [
            {
                "batch_id": batch_id,
                "cluster_id": proposal.cluster_id,
                "decision_type": proposal.decision_type,
                "representative_text": proposal.representative_text,
                "unique_user_count": counts.get(proposal.cluster_id, 0),
                "response_angle": proposal.response_angle,
                "relevance": proposal.relevance,
                "rationale": proposal.rationale,
                "analyzed_at": analyzed_at,
            }
            for proposal in response.proposals
        ]
        batch = {
            "batch_id": batch_id,
            "representative_text_count": len(context),
            "proposal_count": len(items),
            "elapsed_seconds": round(elapsed, 3),
            "completed_at": analyzed_at,
        }
        self.state.record_analysis(items, batch)
        self.state.health["reasoning"].status = "ok" if items else "degraded"
        provider_error = getattr(self._reasoning, "last_error", "")
        self.state.health["reasoning"].detail = (
            f"last batch: {len(items)} proposals from {len(context)} representatives in {elapsed:.1f}s"
            + (f"; {provider_error}" if provider_error else "")
        )
        await self.state.broadcast(
            {
                "type": "analysis_completed",
                "analysis_results": self.state.analysis_results,
                "last_batch": batch,
                "health": self._health(),
            }
        )

    async def _deadline_loop(self) -> None:
        while not self._stopping:
            await asyncio.sleep(min(0.25, self._max_wait_s))
            await self.flush_if_due()

    async def _health_loop(self) -> None:
        previous: tuple[str, str] | None = None
        while not self._stopping:
            health = self._twitch.health
            current = (health.status, health.detail)
            if current != previous:
                self.state.health["twitch"].status = health.status
                self.state.health["twitch"].detail = health.detail
                await self.state.broadcast({"type": "health_changed", "health": self._health()})
                previous = current
            await asyncio.sleep(0.25)

    def _health(self) -> dict:
        return {
            name: {"status": health.status, "detail": health.detail}
            for name, health in self.state.health.items()
        }
