-- Tamper-evident-in-spirit session audit log — build spec v1.0 D-14,
-- Appendix B, R-AUD-01/02. Single SQLite file, no server, no migrations
-- (POC). Every proposal/policy-result/action/outcome is one row, traceable
-- end to end via correlation_id.
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id TEXT NOT NULL UNIQUE,
    correlation_id TEXT NOT NULL,
    wall_time TEXT NOT NULL,
    monotonic_time REAL NOT NULL,
    decision_type TEXT NOT NULL,
    action_id TEXT,
    parameters_json TEXT NOT NULL,
    representative_text TEXT NOT NULL,
    rationale TEXT NOT NULL,
    score REAL NOT NULL,
    score_breakdown_json TEXT NOT NULL,
    expires_at REAL NOT NULL,
    expected_pre_state_json TEXT NOT NULL,
    policy_result TEXT,
    policy_rule_id TEXT,
    execution_status TEXT,
    execution_detail TEXT,
    creator_outcome TEXT,
    synthetic INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_audit_correlation ON audit_log(correlation_id);
CREATE INDEX IF NOT EXISTS idx_audit_decision ON audit_log(decision_id);
