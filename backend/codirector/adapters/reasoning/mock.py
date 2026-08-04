"""Deterministic reasoning provider — no network call. Same cluster_context in
the prompt always produces the same ReasoningResponse: relevance is derived
from a stable hash of the cluster text, never from a clock or RNG, so
acceptance tests are reproducible (§5.1)."""
import hashlib

from codirector.adapters.base import ReasoningPrompt
from codirector.core.models import Proposal, ReasoningResponse

_ACTION_BY_KIND = {
    "question": "show_question_overlay",
    "reaction": "trigger_hype_filter",
    "topic": None,
}


def _stable_unit_float(text: str) -> float:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) / 0xFFFFFFFF


class MockReasoningProvider:
    async def propose(self, prompt: ReasoningPrompt) -> ReasoningResponse:
        proposals: list[Proposal] = []
        for cluster in prompt.cluster_context[:5]:
            kind = cluster.get("kind", "topic")
            unique_users = cluster.get("unique_user_count", 0)
            text = cluster.get("representative_text", "")
            relevance = round(0.4 + 0.6 * _stable_unit_float(text), 3)
            if unique_users < 3:
                decision_type = "IGNORE"
            elif relevance < 0.5:
                decision_type = "HOLD"
            else:
                decision_type = "SURFACE"
            proposals.append(
                Proposal(
                    cluster_id=cluster["cluster_id"],
                    decision_type=decision_type,
                    action_id=_ACTION_BY_KIND.get(kind) if decision_type == "SURFACE" else None,
                    parameters={},
                    representative_text=text,
                    response_angle=(f"acknowledge: {text}"[:140]),
                    relevance=relevance,
                    rationale=(f"{kind} cluster with {unique_users} unique viewers"[:200]),
                )
            )
        return ReasoningResponse(proposals=proposals)
