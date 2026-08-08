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

- Python 3.12
- Node.js 20 or newer and npm
- OBS Studio with OBS WebSocket enabled when using OBS actions
- A Twitch account token with `chat:read` when using live Twitch chat

## Install

From the repository root, create the Python environment and install the
backend plus development/test dependencies through `requirements.txt`:

```powershell
py -3.12 -m venv backend\.venv
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

After registering the Twitch application, put its Client ID and newly created
Client Secret in `.env`, then run the OAuth helper:

```powershell
.\backend\.venv\Scripts\python.exe backend\tools\twitch_oauth.py
```

The helper reads `TWITCH_CLIENT_ID`, `TWITCH_CLIENT_SECRET`, and the optional
`TWITCH_REDIRECT_URI` from `.env`; opens Twitch authorization with a fresh
anti-forgery state; and asks for the full callback URL. A localhost connection
failure in the browser is expected because the project does not run a trusted
local HTTPS callback server. Paste the URL from the address bar and the helper
will validate it, exchange the one-time code, and update
`TWITCH_USER_ACCESS_TOKEN` and `TWITCH_REFRESH_TOKEN` without displaying the
tokens. Use `--code-only` if you only want the short-lived authorization code.

Check configuration without displaying secret values:

```powershell
.\backend\.venv\Scripts\python.exe -m codirector.cli check-config
```

Chat is filtered and batched locally before reasoning so rejected comments do
not consume LLM input. Configure the limits in `config/app.yaml`:

```yaml
pipeline:
  chat_batch_max_representative_texts: 50
  chat_batch_max_wait_s: 120
  chat_filter_min_recognized_words: 3
```

A batch becomes ready when it contains 50 pending representative texts or the
time limit from its first pending representative text expires, whichever
happens first. Accepted comments are clustered as they arrive, so 50 copies of
the same question consume one representative-text slot while still updating
the cluster's member and unique-user counts. Emoji/symbol-only comments and
comments with fewer than three recognized English words are rejected without an
LLM call. Reaction-only terms such as `pog`, `lol`, `lmao`, `lel`, and `rofl`
and known Twitch/BTTV/FFZ/7TV emote names contribute zero toward the three-word
threshold. The filter intentionally has a static Twitch vocabulary, but
channel-specific emotes and non-English chat require future metadata-aware and
language-aware extensions.

Reasoning uses up to three attempts for retryable timeouts, transient HTTP
failures, invalid JSON, or schema-invalid output. Permanent client errors such
as invalid credentials or insufficient credit skip directly to the next model.
Retries apply to the compressed batch request, not separately to every raw
comment. Configure structured output and the OpenCode fallback order in
`config/app.yaml`:

```yaml
reasoning:
  structured_output_mode: attribute # or: system_prompt
  model: "deepseek-v4-flash-free"
  fallback_models:
    - "longcat-2.0-free"
    - "ling-3.0-tiny-free"
    - "mimo-v2.5-free"
    - "laguna-s-2.1-free"
    - "nemotron-3-ultra-free"
  timeout_s: 45
  max_attempts: 3
```

`attribute` is the default and sends the schema through the provider's native
structured-output field. `system_prompt` omits that field and embeds the exact
same schema in the system/developer prompt. Big Pickle is intentionally absent;
North Mini Code is disabled because its tested upstream authorization path was
unusable. The fallback list is used only with OpenCode, preventing OpenCode
model IDs from leaking into other provider integrations. The order reflects
the 50-representative-text V6 results, with LongCat first for its 3/3 native
schema success rate.

List the models available to every configured AI API key:

```powershell
.\backend\.venv\Scripts\python.exe backend\tools\list_ai_models.py
```

The output is an ASCII terminal table. Providers without a detected key are
shown as `NOT AVAILABLE`; invalid credentials or API failures are shown as
`ERROR`. The command never prints keys. By default it prints every model; use
`--limit 25` for a shorter table or `--provider openai` to query only one.

Check provider usage and recent organization costs:

```powershell
.\backend\.venv\Scripts\python.exe backend\tools\list_ai_models.py --check-usage
```

OpenCode runs the installed CLI's `opencode stats` command and prints its native
local-session token, cost, model, and tool report below the table. Ensure
`opencode` is on `PATH`, or let the tool install the official npm package and
continue automatically:

```powershell
.\backend\.venv\Scripts\python.exe backend\tools\list_ai_models.py --check-usage --install-opencode
```

The tool also checks npm's global directory when it is absent from `PATH`.
Alternatively, set `OPENCODE_CLI_PATH` in `.env` to its executable.
This local report does not include the hosted Zen credit balance. OpenRouter
reports per-key usage with `OPENROUTER_API_KEY`. OpenAI and Anthropic
organization cost reports require the separate optional `OPENAI_ADMIN_KEY` and
`ANTHROPIC_ADMIN_KEY`; ordinary inference keys cannot read those reports. The
window defaults to 30 days and can be changed with `--days 7` (maximum 30).

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
