"""Cluster, Proposal, and Decision data contracts — build spec v1.0 §4.2-4.4.

Kept in one module (not split across clustering/reasoning/policy) because all
three are imported by clustering.py, adapters/reasoning/*, scoring.py, and
policy/engine.py — a shared home avoids a circular-import cycle between those.
"""
from typing import Literal

from pydantic import BaseModel, Field


class Cluster(BaseModel):
    cluster_id: str
    kind: Literal["question", "topic", "reaction"]
    representative_text: str  # verbatim from one member message
    member_event_ids: list[str]
    unique_user_ids: set[str]
    first_seen: float  # monotonic
    last_seen: float
    novelty: float  # 0-1, distance from recent clusters
    surfaced_at: float | None = None


class Proposal(BaseModel):
    """§4.3 — the reasoning provider returns only this. Anything else is a
    schema failure and fails closed (extra='forbid')."""

    model_config = {"extra": "forbid"}

    cluster_id: str
    decision_type: Literal["SURFACE", "HOLD", "IGNORE"]
    action_id: str | None = None  # must exist in the catalog, else rejected
    parameters: dict[str, str | int] = Field(default_factory=dict)
    representative_text: str
    response_angle: str = Field(max_length=140)  # private hint for the creator
    relevance: float = Field(ge=0.0, le=1.0)  # model's view of topical fit
    rationale: str = Field(max_length=200)


class ReasoningResponse(BaseModel):
    model_config = {"extra": "forbid"}

    proposals: list[Proposal] = Field(default_factory=list, max_length=5)


class Decision(BaseModel):
    """§4.4 — assembled locally. expires_at/expected_pre_state are never taken
    from the model (see D-12: model-supplied wall-clock expiry was a v0.1 bug)."""

    decision_id: str
    correlation_id: str
    proposal: Proposal
    score: float  # local, §5.6
    score_breakdown: dict[str, float]
    created_at: float  # monotonic
    expires_at: float  # monotonic, assigned locally
    expected_pre_state: dict[str, str]  # assigned locally from live OBS state
    policy_result: Literal["allowed", "rejected", "held"] | None = None
    policy_rule_id: str | None = None
