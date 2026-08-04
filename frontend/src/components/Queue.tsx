import { useEffect, useState } from "react";
import { api, QueueItemView } from "../hooks/useEventStream";

function useCountdown(expiresInSeconds: number) {
  const [deadline, setDeadline] = useState(
    () => performance.now() / 1000 + Math.max(0, expiresInSeconds),
  );
  const [remaining, setRemaining] = useState(() => Math.max(0, expiresInSeconds));

  useEffect(() => {
    const nextDeadline = performance.now() / 1000 + Math.max(0, expiresInSeconds);
    setDeadline(nextDeadline);
    setRemaining(Math.max(0, expiresInSeconds));
  }, [expiresInSeconds]);

  useEffect(() => {
    const id = setInterval(
      () => setRemaining(Math.max(0, deadline - performance.now() / 1000)),
      500,
    );
    return () => clearInterval(id);
  }, [deadline]);
  return remaining;
}

function QueueCard({ item }: { item: QueueItemView }) {
  const remaining = useCountdown(item.expires_in_s);
  const pct = Math.max(0, Math.min(1, remaining / 30));

  return (
    <li className="queue-card" aria-label={`Queued item, ${item.pinned ? "pinned" : "not pinned"}`}>
      <div className="queue-card-ring" style={{ ["--pct" as any]: pct }} aria-hidden="true" />
      <div className="queue-card-body">
        <p className="queue-card-text">{item.representative_text}</p>
        <p className="queue-card-angle">{item.response_angle}</p>
        <p className="queue-card-score">score {item.score.toFixed(2)}</p>
      </div>
      <div className="queue-card-actions">
        <button onClick={() => api.accept(item.decision_id)}>Accept</button>
        <button onClick={() => api.dismiss(item.decision_id)}>Dismiss</button>
        <button onClick={() => api.snooze(item.decision_id)}>Snooze</button>
        <button onClick={() => api.pin(item.decision_id)} disabled={item.pinned}>
          {item.pinned ? "Pinned" : "Pin"}
        </button>
      </div>
    </li>
  );
}

export function Queue({ items, heldCount }: { items: QueueItemView[]; heldCount: number }) {
  return (
    <section className="queue" aria-label="Interaction queue">
      <h2>
        Interaction queue <span className="held-count">({heldCount} held)</span>
      </h2>
      {items.length === 0 ? (
        <p className="queue-empty">Nothing surfaced right now.</p>
      ) : (
        <ul className="queue-list">
          {items.map((item) => (
            <QueueCard key={item.decision_id} item={item} />
          ))}
        </ul>
      )}
    </section>
  );
}
