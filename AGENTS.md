# Agent Guide

## Project overview

This repository is a proof-of-concept AI Stream Co-Director for solo Twitch
creators using OBS. It clusters audience messages, tracks stream phase from
OBS and speech activity, proposes a small private interaction queue, and
allows only catalogued OBS actions through a deterministic policy engine.

The authoritative spec is
`AI_Stream_Co_Director_PRD_v0.1.docx`. The second half, titled **AI Stream
Co-Director - Build Specification v1.0**, replaces conflicting v0.1 details.
In particular: Twitch only, no gameplay capture/telemetry, no outbound chat or
voice, Python 3.12, React 18, local SQLite, and OBSERVE on every startup.

Major pieces:

- `backend/codirector/`: FastAPI/asyncio backend, adapters,
  clustering/scoring, policy, OBS orchestration, audit storage, and API.
- `frontend/`: React 18 + TypeScript + Vite control center and a
  separately secured OBS browser overlay.
- `config/`: runtime configuration and deny-by-default action catalog.
  Credentials come from the root `.env` or OS keyring, never YAML.
- `backend/tests/`: unit, integration, and deterministic
  acceptance coverage mapped to build-spec requirement IDs.
- `requirements.txt`: root convenience installer for the backend and dev
  tooling; `backend/pyproject.toml` is the canonical dependency declaration.

## Setup and commands

Backend (Python 3.12):

```powershell
Copy-Item .env.example .env # from the repository root, if .env is absent
# Fill in one AI key plus TWITCH_CHANNEL/TWITCH_USER_ACCESS_TOKEN.
py -3.12 -m venv backend\.venv
.\backend\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\backend\.venv\Scripts\python.exe -m pytest backend\tests -q
.\backend\.venv\Scripts\python.exe -m ruff check backend\codirector backend\tools backend\tests
.\backend\.venv\Scripts\python.exe -m codirector.cli --mock demo-action
.\backend\.venv\Scripts\python.exe backend\tools\twitch_oauth.py # interactive Twitch OAuth setup
.\backend\.venv\Scripts\python.exe backend\tools\list_ai_models.py # live provider model inventory
.\backend\.venv\Scripts\python.exe backend\tools\list_ai_models.py --check-usage
.\backend\.venv\Scripts\python.exe backend\tools\list_ai_models.py --check-usage --install-opencode
.\backend\.venv\Scripts\python.exe -m codirector.cli check-config
.\backend\.venv\Scripts\python.exe -m codirector.cli listen-twitch # real read-only integration smoke test
.\backend\.venv\Scripts\python.exe -m codirector.api.server
```

Real Parakeet ASR additionally needs
`.\backend\.venv\Scripts\python.exe -m pip install -e ".\backend[asr]"`, a
compatible NVIDIA GPU/CUDA stack, and a cached model checkpoint.

Frontend:

```powershell
cd frontend
npm install
npm run dev
npm run lint
npm run build
```

The Vite dev server proxies `/api` and `/ws` to `127.0.0.1:8756`. A production
frontend build is served by FastAPI from `/`.

## Conventions

- `PolicyEngine` is the only code allowed to call
  `OBSOrchestrator.execute()`. The import-graph test enforces this.
- Provider interfaces have deterministic mocks. Automated tests must not call
  OBS, Twitch, a reasoning service, or a GPU model.
- Trust is assigned at ingestion and immutable. Desktop-audio transcripts are
  always viewer-authored; only microphone transcripts may be creator-trusted.
- Use `time.monotonic()` for expiry/cooldown logic; use wall time only for logs
  and display. Send durations, not server monotonic timestamps, to browsers.
- Unknown actions/config values fail closed. Never add OBS object names outside
  `config/action_catalog.yaml`.
- Chat filtering is local and deterministic: emoji/symbol-only comments and
  comments below the configurable three-recognized-English-word default do not
  enter batches; common reaction tokens such as `pog`/`lol` never count toward
  that floor. Accepted chat currently makes a batch ready at 50 representative
  texts or 10 seconds, whichever occurs first; 10 seconds is a temporary live
  test setting intended to return to 120 seconds.
- Public overlay content must remain plain text. Keep `overlay.html`,
  `overlay.js`, and `overlay.css` isolated and CSP-restricted.
- Unit logic gets explicit time inputs. Integration/acceptance tests use mocks
  and deterministic fixtures.

## Next milestone: creator microphone ASR

The next developer is expected to wire creator-microphone ASR into the live
FastAPI runtime. Implement the following contract rather than treating ASR as
an independent demo:

- Capture only the creator's configured microphone. Do not ingest desktop,
  game, browser, Twitch, or other system audio. The microphone stream may be
  observed continuously by local VAD, but ASR inference and transcript
  accumulation begin only when speech starts.
- Accumulate partial recognition internally while the creator is speaking.
  Emit exactly one creator-trusted `transcript.final` after VAD detects speech
  end. Partial transcripts must never trigger queue resolution, reasoning, or
  OBS actions and must be replaced by the final transcript rather than stored
  as separate statements.
- Keep the final transcript in local SQLite with session ID, transcript/event
  ID, start/end wall timestamps, text, and available confidence metadata.
  Broadcast final transcripts to the private dashboard; never send them to the
  public overlay. Add an explicit retention setting and deletion path rather
  than retaining microphone transcripts indefinitely.
- Wire final transcripts to two separate consumers: addressed-interaction
  detection and OBS layout-intent detection. They may share the same final
  transcript event but must have separate schemas, confidence thresholds,
  audit records, and failure handling.

### Addressed-interaction detection

- Compare each final creator transcript against currently surfaced/held
  interaction-queue items and their representative text. Example: the queue
  contains `What microphone are you using?` and the creator says `I am using
  Mic ABC`; the item should become visibly **addressed**.
- Do not implement this by calling the existing Accept endpoint. Accept means
  creator approval and currently removes an item; addressed is an observed
  resolution state. Add an explicit queue `addressed`/`resolved` transition,
  retain it in the decision/audit log, and broadcast the updated queue so the
  dashboard can show a tick automatically.
- Any model-assisted matcher must return a strict grounded schema containing
  only existing decision IDs plus evidence/confidence. Reject invented IDs,
  changed representative text, low confidence, invalid JSON, and additional
  fields. A transcript may address zero, one, or several active items.
- Matching must not reveal viewer IDs or credentials. Provide only the final
  creator transcript and the minimum queue fields needed for comparison.

### Transcript-driven OBS layouts

- Let creators configure logical layout intents such as `gameplay` and
  `viewer_interaction`, mapping each logical ID to an enabled action in
  `config/action_catalog.yaml`. Never let a transcript or model supply an
  arbitrary OBS scene/source name.
- Analyze only final creator transcripts and return a strict intent such as
  `gameplay | viewer_interaction | no_change`, with confidence and rationale.
  Examples include returning to gameplay discussion versus explicitly talking
  to viewers; ambiguous speech must produce `no_change`.
- Layout switching must still flow through `PolicyEngine`, the sole caller of
  `OBSOrchestrator.execute()`. OBSERVE records the proposal only, ASSIST queues
  creator approval, and CO_DIRECT may execute only a catalogued low-risk action
  that passes every existing policy check. Transcript trust never bypasses
  autonomy, cooldown, pre-state, kill-switch, or allowlist rules.
- Add debounce/hysteresis and a cooldown so adjacent transcript segments do
  not flap between layouts. Do not issue an action when the requested logical
  layout is already active.

Use deterministic mock audio/VAD/ASR/reasoning/OBS fixtures in automated tests.
Required coverage includes partial-to-final replacement, silence/no-speech,
one final event per utterance, addressed/not-addressed/low-confidence cases,
grounding against queue IDs, both layout intents, ambiguous `no_change`,
cooldown/idempotence, every autonomy level, kill switch, and restart cleanup.
Real microphone/GPU and OBS checks belong in an explicitly invoked smoke test,
never the normal test suite.

### ASR/frontend ownership split

Two developers will work concurrently and **must use separate feature
branches**. Neither developer should work directly on `main`:

- **Dev 1 — `feature/asr-runtime`:** creator microphone/VAD/ASR lifecycle,
  SQLite transcript persistence/retention, automatic checkoff when surfaced
  interactions have been addressed, transcript-driven OBS layout intent,
  queue state transitions, policy/OBS integration, REST/WebSocket
  serialization, and deterministic backend tests.
- **Dev 2 — `feature/frontend-dashboard`:** improve the private React
  dashboard's appearance, clarity, responsiveness, accessibility, and overall
  user friendliness. This includes presentation for live chat, batches, LLM
  analysis, queue state, eventual addressed ticks, transcripts, and layout
  status using the agreed backend contracts.

Create each branch from the same current `main` baseline, commit only relevant
work, and merge through separate pull requests. Dev 1 should avoid editing
`frontend/`; Dev 2 should avoid changing backend behavior, database schemas,
policy, or provider code. Do not share a working branch, force-push over the
other developer, or resolve conflicts by discarding unfamiliar changes.

The likely shared boundary is the WebSocket/API contract in
`backend/codirector/api/state.py`, `backend/codirector/api/routes.py`, and
`frontend/src/hooks/useEventStream.ts`. Dev 1 owns the backend payload and must
document it with contract tests and example fixtures. Dev 2 consumes that
contract. Any rename or incompatible payload change must be agreed before
implementation; prefer additive fields/messages so both branches can merge
cleanly.

Branch setup in each developer's own clone/worktree:

```powershell
# Dev 1
git switch main
git pull --ff-only origin main
git switch -c feature/asr-runtime

# Dev 2 (run separately in Dev 2's clone/worktree)
git switch main
git pull --ff-only origin main
git switch -c feature/frontend-dashboard
```

Use stable, additive WebSocket messages with these minimum shapes (exact naming
may be refined once, then covered by contract tests):

```json
{"type":"transcript_final","transcript":{"transcript_id":"...","text":"...","started_at":"...","ended_at":"...","confidence":0.0}}
```

```json
{"type":"queue_item_addressed","decision_id":"...","addressed_at":"...","evidence":"...","confidence":0.0,"queue":{}}
```

```json
{"type":"layout_intent","intent":"gameplay|viewer_interaction|no_change","confidence":0.0,"rationale":"...","action_id":null,"status":"proposed|queued|executed|rejected"}
```

Include the latest final transcripts, addressed state, and current/pending
layout intent in the initial WebSocket snapshot so a browser refresh restores
the private UI. Browser payloads use wall timestamps/durations, never server
monotonic timestamps. Do not remove or rename current Twitch/chat/analysis
snapshot fields while the frontend work is in progress.

## Current limitations and gotchas

- FastAPI now owns the live read-only Twitch-to-reasoning runtime and publishes
  immediate filter status plus completed LLM batches to the private dashboard.
  ASR and OBS are not yet wired into that runtime. The API kill switch clears
  the UI queue and forces OBSERVE, but is not connected to a live
  `OBSOrchestrator`; the global hotkey class is also not registered at startup.
- Assist-mode **Accept** currently records/removes a queue item only; it does
  not execute a proposed OBS action. Do not present the current build as a
  complete live demo until approval execution is wired through policy.
- `tools/chat_harness.py` generates tagged synthetic events but does not inject
  them into the running server yet.
- `.env` AI selection is OpenCode, OpenRouter, Anthropic/Claude, then OpenAI;
  `AI_PROVIDER` can force one. `TWITCH_CLIENT_ID`, `TWITCH_CLIENT_SECRET`, and
  `TWITCH_REFRESH_TOKEN` support the interactive OAuth setup helper, but the
  running IRC adapter still directly consumes `TWITCH_USER_ACCESS_TOKEN` and
  does not automatically refresh an expired token.
- Reasoning defaults to OpenCode `deepseek-v4-flash-free`, then the free-model
  fallback list in `config/app.yaml`. Native schema attributes are the default;
  `structured_output_mode: system_prompt` retains the tested prompt-only path.
- AI usage discovery runs the local `opencode stats` CLI report (configured by
  `OPENCODE_CLI_PATH`); it cannot retrieve the hosted Zen credit balance.
- NeMo ASR and the real OBS connection have not been exercised live. Twitch
  IRC capture and OpenCode structured reasoning have been exercised live. The
  content-safety banned-term set is a test placeholder, not a production
  moderation vocabulary.
- The local ignored `backend/.venv` uses Python 3.12, matching the package
  metadata and documented development environment.
- `docs/DEMO_RUNBOOK.md` is a target rehearsal guide. Its screenshot and two
  signed rehearsal rows are intentionally still missing.

Keep this file concise and update it whenever these facts change.
