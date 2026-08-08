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

After installation and credential setup, start both backend and frontend on Windows with:

```powershell
.\start_app.bat
```

PowerShell and Bash alternatives are `start_app.ps1` and `start_app.sh`; see
`START_APP.md` for options and behavior. Each launcher also accepts a stop flag:
`start_app.bat -Stop`, `start_app.ps1 -Stop`, or `start_app.sh --stop`.

The dependency definitions in `backend/pyproject.toml` remain canonical;
`requirements.txt` is the root-level installer and applies the tested pins in
`requirements-lock.txt` for a reproducible Python 3.12 Windows environment.
For optional local
Parakeet ASR support, install `-e ".\backend[asr]"` after preparing a compatible
NVIDIA/CUDA environment.

## Configure credentials

Edit the git-ignored [`.env`](.env) file, or copy [`.env.example`](.env.example)
if it is missing:

```powershell
Copy-Item .env.example .env
```

Never commit `.env`. It contains Twitch and AI credentials and is ignored by
Git.

## Twitch tokens and running the app

### 1. Configure `.env`

Create an application in the Twitch Developer Console and register this OAuth
redirect URL (or the value you choose for `TWITCH_REDIRECT_URI`):

```text
https://localhost:3000/
```

Set the following fields in the root `.env` file. Do not put real secret
values in `.env.example`:

```dotenv
AI_PROVIDER=opencode
OPENCODE_API_KEY=your_opencode_key

TWITCH_CHANNEL=your_broadcaster_login
TWITCH_CLIENT_ID=your_twitch_application_client_id
TWITCH_CLIENT_SECRET=your_twitch_application_client_secret
TWITCH_REDIRECT_URI=https://localhost:3000/

# The OAuth helper fills these two fields.
TWITCH_USER_ACCESS_TOKEN=
TWITCH_REFRESH_TOKEN=
```

`TWITCH_CHANNEL` is the channel login from its URL, without `#`; for example,
`https://twitch.tv/example_name` uses `TWITCH_CHANNEL=example_name`.

### 2. Obtain the Twitch user and refresh tokens

From the repository root, run:

```powershell
.\backend\.venv\Scripts\python.exe backend\tools\twitch_oauth.py
```

The helper opens Twitch authorization and requests the read-only `chat:read`
scope. After authorization, the browser may show a localhost connection error;
this is expected. Copy the complete URL from the browser address bar and paste
it into the helper. It validates the callback and writes both tokens into
`.env` without printing their values.

If Twitch later reports `Invalid or unauthorized Access Token passed`, rerun
the same helper to renew authorization.

### 3. Verify configuration

```powershell
.\backend\.venv\Scripts\python.exe -m codirector.cli check-config
```

This reports whether Twitch and AI settings are present without displaying
secret values. A successful live connection is shown on the dashboard after
startup as `Twitch: connected`.

### 4. Start backend and frontend

Windows Command Prompt or a double-click in File Explorer:

```bat
start_app.bat
```

PowerShell:

```powershell
.\start_app.ps1
```

Git Bash, Linux, or macOS:

```bash
bash ./start_app.sh
```

The launcher starts both services and opens the dashboard at
`http://localhost:5173`. Twitch chat can connect before the stream goes live,
so it is preferable to start Streamline first and then start the stream.

Send a comment containing at least three recognized content words, such as
`this is a dashboard test`. It appears immediately in Recent Twitch Chat. The
current test configuration sends its representative cluster to the LLM after
10 seconds or after 50 representative texts accumulate, whichever happens
first.

### 5. Stop all services

Use the matching launcher:

```bat
start_app.bat -Stop
```

```powershell
.\start_app.ps1 -Stop
```

```bash
bash ./start_app.sh --stop
```

Add at least one AI key. With `AI_PROVIDER=auto`, the first configured key is
used in this order: OpenCode Zen, OpenRouter, Anthropic/Claude, then OpenAI.
Set `AI_PROVIDER` to a provider name to force a specific integration.

Chat is filtered and batched locally before reasoning so rejected comments do
not consume LLM input. Configure the limits in `config/app.yaml`:

```yaml
pipeline:
  chat_batch_max_representative_texts: 50
  chat_batch_max_wait_s: 10 # temporary live-test setting; restore to 120 later
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

FastAPI now owns the live read-only Twitch adapter. Every received comment is
pushed immediately to the private Recent Twitch Chat panel with its filter
status. When the batch closes, all accepted representative texts and their
unique-user counts are sent to reasoning; validated proposals are published to
the LLM Analysis panel. The current 10-second deadline is intentionally short
for integration testing and should be restored to 120 seconds for normal use.

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
