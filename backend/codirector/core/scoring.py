"""Deterministic local scoring — build spec v1.0 §5.6. The model contributes
only `relevance`; everything else is computed locally from observable
features. Pure function: same inputs always produce the same score, `now` is
always passed in rather than read from the clock (R-SCO-01)."""
from codirector.config.models import PersonaConfig
from codirector.core.models import Cluster, Proposal

FACTORS = ("relevance", "breadth", "novelty", "urgency", "support_tier")


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _tier_lookup(is_support_event: bool) -> float:
    return 1.0 if is_support_event else 0.0


def score_proposal(
    proposal: Proposal,
    cluster: Cluster,
    persona: PersonaConfig,
    now: float,
    decision_ttl_s: float,
    is_support_event: bool = False,
    model_reported_confidence: float | None = None,
) -> tuple[float, dict[str, float]]:
    """`model_reported_confidence` is accepted only so callers have one place
    to thread the model's own (uncalibrated) confidence value through to the
    audit log (Appendix B). D-11/R-SCO-03: it must never affect the returned
    score or breakdown — it is intentionally unused in the computation below.
    """
    values = {
        "relevance": proposal.relevance,
        "breadth": min(len(cluster.unique_user_ids) / 8, 1.0),
        "novelty": cluster.novelty,
        "urgency": _clamp(1 - (now - cluster.first_seen) / decision_ttl_s, 0.0, 1.0),
        "support_tier": _tier_lookup(is_support_event),
    }
    weights = persona.weights
    score = (
        weights.relevance * values["relevance"]
        + weights.breadth * values["breadth"]
        + weights.novelty * values["novelty"]
        + weights.urgency * values["urgency"]
        + weights.support_tier * values["support_tier"]
    )
    return score, values
