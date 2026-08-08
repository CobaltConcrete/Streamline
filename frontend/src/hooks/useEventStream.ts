import { useEffect, useRef, useState } from "react";

export interface HealthStatus {
  status: "ok" | "degraded" | "down";
  detail: string;
}

export interface QueueItemView {
  decision_id: string;
  representative_text: string;
  response_angle: string;
  score: number;
  score_breakdown: Record<string, number>;
  expires_at: number;
  expires_in_s: number;
  pinned: boolean;
}

export interface DecisionLogEntry {
  decision_id: string;
  correlation_id: string;
  decision_type: "SURFACE" | "HOLD" | "IGNORE";
  action_id: string | null;
  representative_text: string;
  score: number;
  policy_result: "allowed" | "rejected" | "held" | null;
  policy_rule_id: string | null;
  created_at: number;
}

export interface RecentChatItem {
  message_id: string;
  display_name: string;
  text: string;
  accepted: boolean;
  filter_reason: "emoji_only" | "unintelligible" | null;
  received_at: string;
}

export interface AnalysisResult {
  batch_id: string;
  cluster_id: string;
  decision_type: "SURFACE" | "HOLD" | "IGNORE";
  representative_text: string;
  unique_user_count: number;
  response_angle: string;
  relevance: number;
  rationale: string;
  analyzed_at: string;
}

export interface BatchSummary {
  batch_id: string;
  representative_text_count: number;
  proposal_count: number;
  elapsed_seconds: number;
  completed_at: string;
}

export interface CodirectorState {
  connected: boolean;
  autonomy: "OBSERVE" | "ASSIST" | "CO_DIRECT";
  killSwitchEngaged: boolean;
  health: Record<string, HealthStatus>;
  activeQueue: QueueItemView[];
  heldCount: number;
  decisionLog: DecisionLogEntry[];
  recentChat: RecentChatItem[];
  analysisResults: AnalysisResult[];
  lastBatch: BatchSummary | null;
}

const INITIAL_STATE: CodirectorState = {
  connected: false,
  autonomy: "OBSERVE",
  killSwitchEngaged: false,
  health: {},
  activeQueue: [],
  heldCount: 0,
  decisionLog: [],
  recentChat: [],
  analysisResults: [],
  lastBatch: null,
};

// Single WebSocket hook — §5.11: "No routing, no state library beyond React
// state and one WebSocket hook."
export function useEventStream() {
  const [state, setState] = useState<CodirectorState>(INITIAL_STATE);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    let cancelled = false;
    let socket: WebSocket;

    function connect() {
      socket = new WebSocket(`${location.origin.replace(/^http/, "ws")}/ws`);
      wsRef.current = socket;

      socket.onopen = () => setState((s) => ({ ...s, connected: true }));
      socket.onclose = () => {
        setState((s) => ({ ...s, connected: false }));
        if (!cancelled) setTimeout(connect, 1000);
      };
      socket.onmessage = (event) => {
        const msg = JSON.parse(event.data);
        setState((s) => applyMessage(s, msg));
      };
    }

    connect();
    return () => {
      cancelled = true;
      socket?.close();
    };
  }, []);

  return state;
}

function applyMessage(s: CodirectorState, msg: any): CodirectorState {
  switch (msg.type) {
    case "snapshot":
      return {
        ...s,
        autonomy: msg.autonomy,
        killSwitchEngaged: msg.kill_switch_engaged,
        health: msg.health,
        activeQueue: msg.queue.active,
        heldCount: msg.queue.held_count,
        decisionLog: msg.decision_log,
        recentChat: msg.recent_chat ?? [],
        analysisResults: msg.analysis_results ?? [],
        lastBatch: msg.last_batch ?? null,
      };
    case "autonomy_changed":
      return { ...s, autonomy: msg.level };
    case "kill_switch_activated":
      return {
        ...s,
        killSwitchEngaged: true,
        autonomy: "OBSERVE",
        activeQueue: msg.queue?.active ?? [],
        heldCount: msg.queue?.held_count ?? 0,
      };
    case "resumed":
      return { ...s, killSwitchEngaged: false };
    case "queue_changed":
      return { ...s, activeQueue: msg.queue.active, heldCount: msg.queue.held_count };
    case "health_changed":
      return { ...s, health: msg.health };
    case "chat_received":
      return { ...s, recentChat: msg.recent_chat };
    case "analysis_completed":
      return {
        ...s,
        health: msg.health,
        analysisResults: msg.analysis_results,
        lastBatch: msg.last_batch,
      };
    default:
      return s;
  }
}

async function post(path: string) {
  const resp = await fetch(`/api${path}`, { method: "POST", headers: { "Content-Type": "application/json" } });
  if (!resp.ok) throw new Error(`${path} failed: ${resp.status}`);
  return resp.json();
}

export const api = {
  setAutonomy: (level: "OBSERVE" | "ASSIST" | "CO_DIRECT") =>
    fetch("/api/autonomy", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ level }),
    }),
  killSwitch: () => post("/kill-switch"),
  resume: () => post("/resume"),
  accept: (id: string) => post(`/queue/${id}/accept`),
  dismiss: (id: string) => post(`/queue/${id}/dismiss`),
  snooze: (id: string) => post(`/queue/${id}/snooze`),
  pin: (id: string) => post(`/queue/${id}/pin`),
};
