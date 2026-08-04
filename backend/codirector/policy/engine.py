"""The deterministic policy engine — build spec v1.0 §5.7. The sole gateway to
OBS (§3 invariant, R-SAF-02): PolicyEngine.evaluate() is the only place an
action_id is authorized, and OBSOrchestrator.execute() must only ever be
called from here.

Every check fails closed, in the fixed order below. Each rejection records
its rule ID so R-POL-01 can assert per-rule behaviour independently.
"""
import uuid
from dataclasses import dataclass, field

from pydantic import ValidationError

from codirector.config.models import PersonaConfig
from codirector.core.autonomy import AutonomyLevel
from codirector.core.models import Cluster, Decision, Proposal
from codirector.orchestrator.obs_orchestrator import ExecutionResult, OBSOrchestrator
from codirector.policy import content_safety
from codirector.policy.catalog import ActionCatalog, ActionSpec, ActionType, RiskLevel

RULE_NAMES = {
    "1": "schema",
    "2": "action_exists",
    "3": "autonomy",
    "4": "parameters",
    "5": "score_threshold",
    "6": "cooldown",
    "7": "budget",
    "8": "content_safety",
    "9": "pre_state",
    "10": "expiry",
}

_ALLOWED_PARAM_KEYS: dict[ActionType, set[str]] = {
    ActionType.OVERLAY_TEXT: {"duration_ms"},
    ActionType.SCENE_SWITCH: set(),
    ActionType.ITEM_VISIBILITY: {"visible"},
    ActionType.FILTER_TOGGLE: {"duration_ms"},
}


@dataclass
class _SessionState:
    last_executed: dict[str, float] = field(default_factory=dict)
    executed_count: dict[str, int] = field(default_factory=dict)


class PolicyEngine:
    """§3's one invariant: this is the only component permitted to call
    OBSOrchestrator.execute() (R-SAF-02). It therefore owns the orchestrator
    instance outright — nothing else is handed a reference to it."""

    def __init__(self, orchestrator: OBSOrchestrator) -> None:
        self._state = _SessionState()
        self._orchestrator = orchestrator
        self.execution_results: dict[str, ExecutionResult] = {}

    def _reject(
        self,
        *,
        proposal: Proposal,
        cluster_id: str,
        correlation_id: str,
        now: float,
        score: float,
        score_breakdown: dict[str, float],
        expires_at: float,
        expected_pre_state: dict[str, str],
        rule_id: str,
    ) -> Decision:
        return Decision(
            decision_id=str(uuid.uuid4()),
            correlation_id=correlation_id,
            proposal=proposal,
            score=score,
            score_breakdown=score_breakdown,
            created_at=now,
            expires_at=expires_at,
            expected_pre_state=expected_pre_state,
            policy_result="rejected",
            policy_rule_id=rule_id,
        )

    async def evaluate(
        self,
        *,
        raw_proposal: dict,
        cluster: Cluster,
        persona: PersonaConfig,
        autonomy: AutonomyLevel,
        catalog: ActionCatalog,
        live_obs_state: dict[str, str],
        now: float,
        score: float,
        score_breakdown: dict[str, float],
        expires_at: float,
        expected_pre_state: dict[str, str],
        correlation_id: str,
    ) -> Decision:
        # Rule 1 — schema. A malformed/extra-key payload cannot become a
        # Proposal at all (extra="forbid"), so there is no valid object to
        # embed in the rejected Decision; synthesize a minimal safe stand-in.
        try:
            proposal = Proposal.model_validate(raw_proposal)
        except ValidationError as exc:
            placeholder = Proposal(
                cluster_id=cluster.cluster_id,
                decision_type="IGNORE",
                action_id=None,
                parameters={},
                representative_text=cluster.representative_text[:200],
                response_angle="",
                relevance=0.0,
                rationale=("schema validation failed: " + str(exc))[:200],
            )
            return self._reject(
                proposal=placeholder,
                cluster_id=cluster.cluster_id,
                correlation_id=correlation_id,
                now=now,
                score=score,
                score_breakdown=score_breakdown,
                expires_at=expires_at,
                expected_pre_state=expected_pre_state,
                rule_id="1",
            )

        def reject(rule_id: str) -> Decision:
            return self._reject(
                proposal=proposal,
                cluster_id=cluster.cluster_id,
                correlation_id=correlation_id,
                now=now,
                score=score,
                score_breakdown=score_breakdown,
                expires_at=expires_at,
                expected_pre_state=expected_pre_state,
                rule_id=rule_id,
            )

        # HOLD/IGNORE (or SURFACE with no action) never reach OBS — nothing
        # here to gate. Record as "held", not a rejection: none of rules 2-10
        # apply to a proposal that isn't requesting execution.
        if proposal.decision_type != "SURFACE" or proposal.action_id is None:
            return Decision(
                decision_id=str(uuid.uuid4()),
                correlation_id=correlation_id,
                proposal=proposal,
                score=score,
                score_breakdown=score_breakdown,
                created_at=now,
                expires_at=expires_at,
                expected_pre_state=expected_pre_state,
                policy_result="held",
                policy_rule_id=None,
            )

        # Rule 2 — action exists (and its target resolved successfully at startup).
        action: ActionSpec | None = catalog.get(proposal.action_id)
        if action is None or not action.enabled:
            return reject("2")

        # Rule 3 — autonomy. OBSERVE permits nothing; ASSIST routes to the
        # approval queue rather than autonomous execution (handled upstream,
        # never reaches "allowed" here); CO_DIRECT permits risk:low only.
        if not (autonomy == AutonomyLevel.CO_DIRECT and action.risk == RiskLevel.LOW):
            return reject("3")

        # Rule 4 — parameters: every key declared for the action type, every
        # value within the catalog's limits.
        allowed_keys = _ALLOWED_PARAM_KEYS[action.type]
        for key, value in proposal.parameters.items():
            if key not in allowed_keys:
                return reject("4")
            if key == "duration_ms":
                if not isinstance(value, int) or value <= 0:
                    return reject("4")
                if action.limits.duration_ms is not None and value > action.limits.duration_ms:
                    return reject("4")
            if key == "visible" and (not isinstance(value, int) or value not in (0, 1)):
                return reject("4")

        # Rule 5 — score threshold.
        if score < persona.thresholds.surface_min_score:
            return reject("5")

        # Rule 6 — cooldown.
        last = self._state.last_executed.get(action.id, float("-inf"))
        if now - last < action.limits.cooldown_s:
            return reject("6")

        # Rule 7 — budget.
        if self._state.executed_count.get(action.id, 0) >= action.limits.max_per_session:
            return reject("7")

        # Rule 8 — content safety (public surface: OBS overlay).
        candidate_text = proposal.representative_text
        result = content_safety.check_public(candidate_text, max_length=action.limits.max_length)
        if not result.safe:
            return reject("8")

        # Rule 9 — pre-state drift. Reject and let the caller refresh state;
        # never retry blindly.
        for key, expected_value in expected_pre_state.items():
            if live_obs_state.get(key) != expected_value:
                return reject("9")

        # Rule 10 — expiry.
        if now >= expires_at:
            return reject("10")

        # All checks passed: authorize execution. This is the only call site
        # of OBSOrchestrator.execute() in the codebase (R-SAF-02) — enforced
        # by tests/unit/test_import_graph.py, which greps the rest of the
        # source tree for the pattern and fails if it appears anywhere else.
        self._state.last_executed[action.id] = now
        self._state.executed_count[action.id] = self._state.executed_count.get(action.id, 0) + 1
        decision = Decision(
            decision_id=str(uuid.uuid4()),
            correlation_id=correlation_id,
            proposal=proposal,
            score=score,
            score_breakdown=score_breakdown,
            created_at=now,
            expires_at=expires_at,
            expected_pre_state=expected_pre_state,
            policy_result="allowed",
            policy_rule_id=None,
        )
        self.execution_results[decision.decision_id] = await self._orchestrator.execute(decision, action)
        return decision
