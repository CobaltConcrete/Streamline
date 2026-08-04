# AI Stream Co-Director

Local-first proof of concept for a Twitch/OBS production assistant. It
prioritizes audience moments, proposes creator prompts, and gates a small
allowlist of OBS actions through deterministic safety policy.

The repository uses a conventional full-stack layout: `backend/` contains the
Python service, `frontend/` contains the React control center, and shared
runtime configuration lives in `config/`. Read [`AGENTS.md`](AGENTS.md) for
architecture, conventions, and current implementation gaps. The authoritative
product/build contract is
[`AI_Stream_Co_Director_PRD_v0.1.docx`](AI_Stream_Co_Director_PRD_v0.1.docx),
especially its second-half Build Specification v1.0.

## Prerequisites

- Python 3.11
- Node.js 20 or newer and npm
- OBS Studio with OBS WebSocket enabled when using OBS actions
- A Twitch account token with `chat:read` when using live Twitch chat

## Install

From the repository root, create the Python environment and install the
backend plus development/test dependencies through `requirements.txt`:

```powershell
py -3.11 -m venv backend\.venv
.\backend\.venv\Scripts\python.exe -m pip install --upgrade pip
.\backend\.venv\Scripts\python.exe -m pip install -r requirements.txt

cd frontend
npm install
cd ..
```

The dependency definitions in `backend/pyproject.toml` remain canonical;
`requirements.txt` is a convenient root-level installer. For optional local
Parakeet ASR support, install `-e ".\backend[asr]"` after preparing a compatible
NVIDIA/CUDA environment.

## Configure credentials

Edit the git-ignored [`.env`](.env) file, or copy [`.env.example`](.env.example)
if it is missing:

```powershell
Copy-Item .env.example .env
```

Add at least one AI key. With `AI_PROVIDER=auto`, the first configured key is
used in this order: OpenCode Zen, OpenRouter, Anthropic/Claude, then OpenAI.
Set `AI_PROVIDER` to a provider name to force a specific integration.

For Twitch, set `TWITCH_CHANNEL` to the broadcaster login and
`TWITCH_USER_ACCESS_TOKEN` to a Twitch **user access token** with `chat:read`
scope. A username alone cannot authenticate chat access.

Check configuration without displaying secret values:

```powershell
.\backend\.venv\Scripts\python.exe -m codirector.cli check-config
```

## Run the application

For development, start the backend and frontend in separate terminals from the
repository root:

```powershell
# Terminal 1: API and WebSocket server at http://127.0.0.1:8756
.\backend\.venv\Scripts\python.exe -m codirector.api.server

# Terminal 2: React development server
cd frontend
npm run dev
```

Open the URL printed by Vite. Its development proxy forwards `/api` and `/ws`
to the backend. To serve a production frontend from FastAPI instead, run
`npm run build` in `frontend/`, start the backend, and open
`http://127.0.0.1:8756`.

To verify the live Twitch-to-AI path, run the read-only listener. It waits
until at least three distinct viewers form an eligible chat cluster, then
prints the selected provider's schema-validated proposal:

```powershell
.\backend\.venv\Scripts\python.exe -m codirector.cli listen-twitch
```

This command never writes to Twitch and never touches OBS. Stop any process
with `Ctrl+C`.

## Test and lint

```powershell
.\backend\.venv\Scripts\python.exe -m pytest backend\tests -q
.\backend\.venv\Scripts\python.exe -m ruff check backend\codirector backend\tools backend\tests

cd frontend
npm run lint
npm run build
```

The FastAPI server currently exposes the control center and its state APIs,
while `listen-twitch` is the separate real integration smoke test. Automatic
wiring of Twitch, ASR, and OBS into the long-running server pipeline remains
future work; see `AGENTS.md` for the precise limitations.
