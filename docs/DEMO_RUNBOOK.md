# Demo Runbook

Target: working proof-of-concept demonstrated on a live Twitch stream (build
spec v1.0, front matter). This runbook is produced at M7 and should be kept
in sync with `config/action_catalog.yaml` — if the catalog changes, update
the beat sheet's action IDs and cooldowns to match.

> **Current status:** this is the target rehearsal sequence, not a claim that
> a complete live demo is ready. The server wires Twitch to reasoning, but does not yet wire ASR and OBS into
> `Pipeline`; Assist approval does not execute OBS actions; the global hotkey
> is not registered; and the chat harness does not inject into the server.
> Complete those items and two clean rehearsals before using this runbook live.

## 1. OBS setup

Scene collection used for the demo:

| Scene | Purpose | Phase role (see `codirector/core/phase.py`) |
|---|---|---|
| `Gameplay` | Main content scene | `ACTIVE` |
| `BRB` | Break scene | `BREAK` |
| `Starting Soon` | Pre-show | `STARTING` |
| `Ending` | Outro | `ENDING` |

Required OBS inputs/sources (must exist under these exact names before
startup — the app resolves and disables any action whose target can't be
found, per R-OBS-03, rather than crashing):

- **`AI_Question_Text`** — a Text (GDI+) source used by `show_question_overlay`.
  Native OBS text rendering; no HTML/DOM involved (see `AT-09` below for why
  that matters).
- **`AI_Support_Text`** — a Text (GDI+) source used by `show_support_overlay`.
- **`CameraFrame`** — a scene item in `Gameplay`, toggled by `toggle_camera_frame`,
  with a `HypeGlow` filter attached for `trigger_hype_filter`.
- **Overlay Browser Source** (optional, for the public-facing overlay demo):
  add a Browser Source pointing at `http://127.0.0.1:8756/overlay.html`
  (served from `frontend/public/overlay.html` once the frontend is built).
  Its CSP permits only same-origin static styles/scripts and the local overlay
  WebSocket. Nothing needs to be configured in OBS beyond the URL.

Control-center window: open `http://127.0.0.1:8756/` in a normal browser
window on a second monitor (D-1 — no game-process injection, no packaging).

**Screenshot**: capture one of the control center mid-demo (autonomy
selector, health dots, an active queue card, and the decision log all
visible) and drop it in this directory as `control_center.png` before the
live demo — a static description isn't a substitute for seeing the actual
layout during rehearsal.

## 2. Config used for the demo

`config/action_catalog.yaml` (as of this writing):

| Action ID | Type | Risk | Cooldown | Budget/session |
|---|---|---|---|---|
| `show_question_overlay` | overlay_text | low | 45s | 30 |
| `show_support_overlay` | overlay_text | low | 20s | 50 |
| `toggle_camera_frame` | item_visibility | low | 30s | 40 |
| `trigger_hype_filter` | filter_toggle | low | 60s | 15 |
| `switch_to_break_scene` | scene_switch | medium | 300s | 4 (requires confirmation) |

Persona: `config/personas/conversational.yaml` (`surface_min_score: 0.55`,
`max_queue_items: 3`, `max_prompts_per_minute: 2`).

## 3. Beat sheet

The following beat sheet is executable only after the current-status blockers
above are resolved.

1. **Start in Observe.** Launch the backend (`python -m codirector.api.server`
   from `backend/`), open the control center. Autonomy selector shows
   `OBSERVE`; health dots are red/`✕` until adapters connect.
2. **Show clustering working.** Run `python tools/chat_harness.py --rate 300
   --duration 20` (or read real chat) and narrate the console output —
   paraphrased questions collapsing into one signal is the whole pitch.
3. **Switch to Assist.** Click `ASSIST` in the header. Explain that proposals
   now reach the private queue but nothing executes autonomously.
4. **Approve one question overlay.** When a card appears in the Interaction
   queue, click **Accept**. (If nothing surfaces within ~20s, see Failure
   plan below.)
5. **Switch to Co-direct.** Click `CO-DIRECT`. Explain the risk gate: only
   `risk: low` actions may now fire on their own.
6. **Let one fire automatically.** Wait for a low-risk action (e.g. another
   question cluster clearing the score threshold) — the Decision log shows
   it going straight to `executed` without a manual Accept.
7. **Trigger a synthetic raid.** Run `python tools/chat_harness.py --raid`
   in another terminal (see §5 below) — the support overlay should fire
   immediately even if you're mid-sentence, and a separate private prompt
   appears in the queue (AT-02's exact scenario).
8. **Press the kill switch.** Click **Kill Switch** in the header (or the
   global hotkey, `Ctrl+Alt+K`, which works even if the browser tab doesn't
   have focus). Autonomy snaps to `OBSERVE`, the button becomes **Resume
   (paused)**, and OBS is left exactly as it was — nothing reverts.

## 4. Failure plan

The kill switch is the universal escape for every beat below — if a step
misbehaves in a way that isn't covered here, press it, say "that's the
safety net working as designed," and move to the next beat.

| Beat | If it doesn't fire | Say / do |
|---|---|---|
| 2 (clustering) | Console shows one cluster per message, not compression | Increase `--rate`; explain the >=3-unique-user floor (R-CTX-03) needs enough distinct chatters |
| 4 (Assist approve) | Nothing surfaces | Explain phase gating — the demo speech may be continuous (ACTIVE_SPEAKING); pause talking for 2s to hit ACTIVE_SILENT |
| 6 (auto-fire) | Action stays in "held"/never executes | Check the autonomy selector actually shows CO-DIRECT and the action's risk is `low` in the catalog table above |
| 7 (raid) | Overlay doesn't appear | Check `AI_Support_Text` input name matches the catalog exactly; check OBS health dot is green |
| Any | OBS looks wrong afterward | Kill switch, then manually fix the scene in OBS — rollback is a separate, deliberate action (§5.9), never automatic |

## 5. Twitch CLI commands (synthetic events — real donations can't be used)

```bash
# From backend/, with the venv active:
python tools/chat_harness.py --rate 120 --duration 30      # sustained synthetic chat
python tools/chat_harness.py --raid                         # one synthetic raid, then exit
```

`chat_harness.py` refuses to run if `config/app.yaml` has
`environment: production` (R-TST-01), and every generated event is tagged
with a `harness:` prefix. At present the CLI prints generated events; it does
not deliver them to the FastAPI process or audit database.

## 6. Rehearsal log

| Date | Runner | Outcome | Notes |
|---|---|---|---|
| _(fill in before the live demo)_ | | | |
| _(fill in before the live demo)_ | | | |

Two clean, dated, signed-off runs are required here before the live demo
(§10) — this table starts empty because none have been run outside this
build session yet.
