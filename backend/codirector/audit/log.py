"""Audit log — build spec v1.0 D-14, §5.9/§8.3, R-AUD-01/02, R-TST-01.
SQLite, single file, local. Every proposal/policy-result/action/outcome is
one row keyed by decision_id, traceable end to end by correlation_id.

R-SAF-08 ("no secret in any ... log line") is satisfied by construction, not
by redaction here: Decision/Proposal (core/models.py) have no field that can
carry a credential — there is nothing to accidentally log.
"""
import json
import sqlite3
import time
from pathlib import Path

from codirector.core.models import Decision
from codirector.orchestrator.obs_orchestrator import ExecutionResult

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


class AuditLog:
    def __init__(self, db_path: str | Path) -> None:
        self._conn = sqlite3.connect(str(db_path))
        self._conn.executescript(_SCHEMA_PATH.read_text(encoding="utf-8"))
        self._conn.commit()

    def record_decision(
        self,
        decision: Decision,
        execution_result: ExecutionResult | None = None,
        synthetic: bool = False,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO audit_log (
                decision_id, correlation_id, wall_time, monotonic_time,
                decision_type, action_id, parameters_json, representative_text,
                rationale, score, score_breakdown_json, expires_at,
                expected_pre_state_json, policy_result, policy_rule_id,
                execution_status, execution_detail, synthetic
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(decision_id) DO UPDATE SET
                policy_result=excluded.policy_result,
                policy_rule_id=excluded.policy_rule_id,
                execution_status=excluded.execution_status,
                execution_detail=excluded.execution_detail
            """,
            (
                decision.decision_id,
                decision.correlation_id,
                time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
                decision.created_at,
                decision.proposal.decision_type,
                decision.proposal.action_id,
                json.dumps(decision.proposal.parameters),
                decision.proposal.representative_text,
                decision.proposal.rationale,
                decision.score,
                json.dumps(decision.score_breakdown),
                decision.expires_at,
                json.dumps(decision.expected_pre_state),
                decision.policy_result,
                decision.policy_rule_id,
                execution_result.status if execution_result else None,
                execution_result.detail if execution_result else None,
                int(synthetic),
            ),
        )
        self._conn.commit()

    def record_outcome(self, decision_id: str, outcome: str) -> bool:
        cur = self._conn.execute(
            "UPDATE audit_log SET creator_outcome = ? WHERE decision_id = ?", (outcome, decision_id)
        )
        self._conn.commit()
        return cur.rowcount > 0

    def trace_by_correlation_id(self, correlation_id: str) -> list[dict]:
        cur = self._conn.execute(
            "SELECT * FROM audit_log WHERE correlation_id = ? ORDER BY monotonic_time", (correlation_id,)
        )
        columns = [d[0] for d in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]

    def get(self, decision_id: str) -> dict | None:
        cur = self._conn.execute("SELECT * FROM audit_log WHERE decision_id = ?", (decision_id,))
        row = cur.fetchone()
        if row is None:
            return None
        columns = [d[0] for d in cur.description]
        return dict(zip(columns, row))

    def close(self) -> None:
        self._conn.close()
