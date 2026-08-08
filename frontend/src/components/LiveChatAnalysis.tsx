import {
  AnalysisResult,
  BatchSummary,
  RecentChatItem,
} from "../hooks/useEventStream";

function filterLabel(item: RecentChatItem) {
  if (item.accepted) return "accepted";
  if (item.filter_reason === "emoji_only") return "filtered: emoji/emote only";
  return "filtered: fewer than 3 recognized content words";
}

export function LiveChatAnalysis({
  chat,
  analyses,
  lastBatch,
}: {
  chat: RecentChatItem[];
  analyses: AnalysisResult[];
  lastBatch: BatchSummary | null;
}) {
  return (
    <>
      <section className="live-chat" aria-label="Recent Twitch chat">
        <h2>Recent Twitch chat</h2>
        {chat.length === 0 ? (
          <p className="queue-empty">Waiting for Twitch comments.</p>
        ) : (
          <ol className="chat-list">
            {chat.map((item) => (
              <li key={item.message_id} className={item.accepted ? "chat-accepted" : "chat-filtered"}>
                <div>
                  <strong>{item.display_name}</strong> {item.text}
                </div>
                <span>{filterLabel(item)}</span>
              </li>
            ))}
          </ol>
        )}
      </section>

      <section className="llm-analysis" aria-label="LLM analysis results">
        <h2>LLM analysis</h2>
        {lastBatch && (
          <p className="batch-summary">
            Last batch: {lastBatch.representative_text_count} representative texts →{" "}
            {lastBatch.proposal_count} proposals in {lastBatch.elapsed_seconds.toFixed(1)}s
          </p>
        )}
        {analyses.length === 0 ? (
          <p className="queue-empty">No completed LLM batch yet.</p>
        ) : (
          <ol className="analysis-list">
            {analyses.map((item, index) => (
              <li key={`${item.batch_id}-${item.cluster_id}-${index}`}>
                <header>
                  <span className={`analysis-decision decision-${item.decision_type.toLowerCase()}`}>
                    {item.decision_type}
                  </span>
                  <span>{item.unique_user_count} unique user{item.unique_user_count === 1 ? "" : "s"}</span>
                  <span>relevance {item.relevance.toFixed(2)}</span>
                </header>
                <p className="analysis-text">{item.representative_text}</p>
                <p><strong>Response angle:</strong> {item.response_angle}</p>
                <p><strong>Rationale:</strong> {item.rationale}</p>
              </li>
            ))}
          </ol>
        )}
      </section>
    </>
  );
}
