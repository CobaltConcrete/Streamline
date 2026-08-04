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
voice, Python 3.11, React 18, local SQLite, and OBSERVE on every startup.

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

Backend (Python 3.11 required by the build spec):

```powershell
Copy-Item .env.example .env # from the repository root, if .env is absent
# Fill in one AI key plus TWITCH_CHANNEL/TWITCH_USER_ACCESS_TOKEN.
py -3.11 -m venv backend\.venv
.\backend\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\backend\.venv\Scripts\python.exe -m pytest backend\tests -q
.\backend\.venv\Scripts\python.exe -m ruff check backend\codirector backend\tools backend\tests
.\backend\.venv\Scripts\python.exe -m codirector.cli --mock demo-action
.\backend\.venv\Scripts\python.exe -m codirector.cli check-config
.\backend\.venv\Scripts\python.exe -m codirector.cli listen-twitch # real read-only integration smoke test
.\backend\.venv\Scripts\python.exe -m codirector.api.server
```

Real Parakeet ASR additionally needs `pip install -e ".[asr]"`, a compatible
NVIDIA GPU/CUDA stack, and a cached model checkpoint.

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
- Public overlay content must remain plain text. Keep `overlay.html`,
  `overlay.js`, and `overlay.css` isolated and CSP-restricted.
- Unit logic gets explicit time inputs. Integration/acceptance tests use mocks
  and deterministic fixtures.

## Current limitations and gotchas

- The policy pipeline and real adapters exist, but the FastAPI server does not
  yet instantiate and continuously wire Twitch + ASR + OBS into `Pipeline`.
  The dashboard therefore remains empty when only the server is launched.
- Because that live runtime is absent, the API kill switch clears the UI queue
  and forces OBSERVE, but the server is not yet connected to a live
  `OBSOrchestrator`; the global hotkey class is also not registered at startup.
- Assist-mode **Accept** currently records/removes a queue item only; it does
  not execute a proposed OBS action. Do not present the current build as a
  complete live demo until approval execution is wired through policy.
- `tools/chat_harness.py` generates tagged synthetic events but does not inject
  them into the running server yet.
- `.env` AI selection is OpenCode, OpenRouter, Anthropic/Claude, then OpenAI;
  `AI_PROVIDER` can force one. `TWITCH_CLIENT_ID`, `TWITCH_CLIENT_SECRET`, and
  `TWITCH_REFRESH_TOKEN` are documented for future OAuth renewal/EventSub, but
  the current IRC adapter directly consumes `TWITCH_USER_ACCESS_TOKEN` only.
- NeMo ASR and the real OBS/Twitch connections have not been exercised live.
  The content-safety banned-term set is a test placeholder, not a production
  moderation vocabulary.
- The local ignored `backend/.venv` was created with Python 3.10 because this
  workstation lacks 3.11. Package metadata correctly requires 3.11; recreate
  the environment with Python 3.11 before release validation.
- `docs/DEMO_RUNBOOK.md` is a target rehearsal guide. Its screenshot and two
  signed rehearsal rows are intentionally still missing.

Keep this file concise and update it whenever these facts change.
