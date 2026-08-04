import { useEffect } from "react";
import { api, useEventStream } from "./hooks/useEventStream";
import { Header } from "./components/Header";
import { Queue } from "./components/Queue";
import { DecisionLog } from "./components/DecisionLog";

export default function App() {
  const state = useEventStream();

  // Browser-focused convenience binding; the OS-level global hotkey (works
  // even when this tab isn't focused) is registered by the backend — see
  // codirector/safety/hotkey.py.
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.ctrlKey && e.altKey && e.key.toLowerCase() === "k") {
        e.preventDefault();
        api.killSwitch();
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  return (
    <div className="app">
      <Header state={state} />
      <main className="main">
        <Queue items={state.activeQueue} heldCount={state.heldCount} />
        <DecisionLog entries={state.decisionLog} />
      </main>
    </div>
  );
}
