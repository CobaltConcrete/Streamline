import { api, CodirectorState } from "../hooks/useEventStream";

const AUTONOMY_LEVELS: Array<"OBSERVE" | "ASSIST" | "CO_DIRECT"> = ["OBSERVE", "ASSIST", "CO_DIRECT"];
const HEALTH_ORDER = ["obs", "twitch", "asr", "reasoning"];
const HEALTH_LABEL: Record<string, string> = { obs: "OBS", twitch: "Twitch", asr: "ASR", reasoning: "Reasoning" };

// Status is conveyed by shape AND text, not colour alone (§5.11 NFR-08 echo).
const STATUS_GLYPH: Record<string, string> = { ok: "●", degraded: "▲", down: "✕" };

export function Header({ state }: { state: CodirectorState }) {
  return (
    <header className="header">
      <div className="header-title">
        <span className="brand">AI Stream Co-Director</span>
        <span className={`ws-indicator ${state.connected ? "ok" : "down"}`}>
          {state.connected ? "connected" : "reconnecting…"}
        </span>
      </div>

      <div className="autonomy-selector" role="radiogroup" aria-label="Autonomy level">
        {AUTONOMY_LEVELS.map((level) => (
          <button
            key={level}
            role="radio"
            aria-checked={state.autonomy === level}
            className={`autonomy-btn ${state.autonomy === level ? "active" : ""}`}
            disabled={state.killSwitchEngaged && level !== "OBSERVE"}
            onClick={() => api.setAutonomy(level)}
          >
            {level.replace("_", "-")}
          </button>
        ))}
      </div>

      <div className="health-dots" aria-label="Component health">
        {HEALTH_ORDER.map((name) => {
          const h = state.health[name] ?? { status: "down", detail: "unknown" };
          return (
            <span key={name} className={`health-dot ${h.status}`} title={`${HEALTH_LABEL[name]}: ${h.detail}`}>
              <span aria-hidden="true">{STATUS_GLYPH[h.status] ?? "?"}</span> {HEALTH_LABEL[name]}
            </span>
          );
        })}
      </div>

      {state.killSwitchEngaged ? (
        <button className="kill-switch resume" onClick={() => api.resume()}>
          Resume (paused)
        </button>
      ) : (
        <button className="kill-switch" onClick={() => api.killSwitch()} title="Hotkey: Ctrl+Alt+K">
          Kill Switch
        </button>
      )}
    </header>
  );
}
