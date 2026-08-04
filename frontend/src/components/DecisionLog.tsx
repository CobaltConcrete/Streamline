import { DecisionLogEntry } from "../hooks/useEventStream";

function outcomeLabel(entry: DecisionLogEntry): string {
  if (entry.policy_result === "allowed") return "executed";
  if (entry.policy_result === "rejected") return `rejected (rule ${entry.policy_rule_id})`;
  if (entry.policy_result === "held") return "held";
  return entry.decision_type.toLowerCase();
}

export function DecisionLog({ entries }: { entries: DecisionLogEntry[] }) {
  return (
    <section className="decision-log" aria-label="Decision log">
      <h2>Decision log</h2>
      {entries.length === 0 ? (
        <p className="queue-empty">No decisions yet this session.</p>
      ) : (
        <ol className="decision-log-list">
          {entries.map((entry) => (
            <li key={entry.decision_id} className={`decision-row outcome-${entry.policy_result ?? entry.decision_type}`}>
              <span className="decision-type">{entry.decision_type}</span>
              <span className="decision-text">{entry.representative_text}</span>
              {entry.action_id && <span className="decision-action">{entry.action_id}</span>}
              <span className="decision-outcome">{outcomeLabel(entry)}</span>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
