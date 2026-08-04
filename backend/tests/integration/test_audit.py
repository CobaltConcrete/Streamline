"""R-AUD-01/02: every proposal/policy-result/action/outcome is logged with a
correlation_id, and the full trace is queryable end to end."""
import tempfile
from pathlib import Path

from codirector.audit.log import AuditLog
from codirector.core.models import Decision, Proposal
from codirector.orchestrator.obs_orchestrator import ExecutionResult


def _decision(decision_id: str, correlation_id: str, policy_result: str, rule_id: str | None = None) -> Decision:
    proposal = Proposal(
        cluster_id="c1", decision_type="SURFACE", action_id="show_question_overlay",
        parameters={}, representative_text="what keyboard do you use", response_angle="angle",
        relevance=0.9, rationale="rationale",
    )
    return Decision(
        decision_id=decision_id, correlation_id=correlation_id, proposal=proposal,
        score=0.8, score_breakdown={"relevance": 0.8}, created_at=1.0, expires_at=21.0,
        expected_pre_state={"program_scene": "Gameplay"}, policy_result=policy_result, policy_rule_id=rule_id,
    )


def test_full_trace():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "audit.sqlite"
        log = AuditLog(db_path)

        d1 = _decision("d1", "corr-1", "allowed")
        log.record_decision(d1, execution_result=ExecutionResult("d1", "executed", "ok", post_state_matched=True))
        log.record_outcome("d1", "accepted")

        row = log.get("d1")
        assert row["decision_id"] == "d1"
        assert row["correlation_id"] == "corr-1"
        assert row["policy_result"] == "allowed"
        assert row["execution_status"] == "executed"
        assert row["creator_outcome"] == "accepted"
        log.close()


def test_trace_by_correlation_id():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "audit.sqlite"
        log = AuditLog(db_path)

        # Two decisions sharing one correlation_id (e.g. AT-02's overlay + private prompt).
        log.record_decision(_decision("d1", "corr-shared", "allowed"))
        log.record_decision(_decision("d2", "corr-shared", "held"))
        log.record_decision(_decision("d3", "corr-other", "rejected", rule_id="2"))

        trace = log.trace_by_correlation_id("corr-shared")
        assert {row["decision_id"] for row in trace} == {"d1", "d2"}

        other = log.trace_by_correlation_id("corr-other")
        assert [row["decision_id"] for row in other] == ["d3"]
        log.close()


def test_synthetic_events_are_tagged():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "audit.sqlite"
        log = AuditLog(db_path)
        log.record_decision(_decision("d1", "corr-1", "allowed"), synthetic=True)
        row = log.get("d1")
        assert row["synthetic"] == 1
        log.close()
