# Start Streamline

This is the Windows PowerShell startup procedure for the Streamline proof of
concept. Run commands from:

```powershell
cd "C:\Users\Gan Ming Hui\Projects\Streamline"
```

Do not print or paste the contents of `.env` into a terminal, log, issue, or
chat. The application loads credentials from the root `.env` automatically.

## One-command startup

From the repository root, run:

```powershell
powershell -ExecutionPolicy Bypass -File .\start_app.ps1
```

The Windows batch wrapper provides the shortest command:

```bat
start_app.bat
```

Git Bash, Linux, and macOS users can run:

```bash
bash ./start_app.sh
```

The launcher opens separate backend and frontend PowerShell terminals, waits
for ports 8756 and 5173, and opens `http://localhost:5173` automatically. It
does not start duplicate services when either port is already listening.

Options:

```powershell
# Start without opening a browser
.\start_app.ps1 -NoBrowser

# Do not run npm install even when frontend/node_modules is absent
.\start_app.ps1 -SkipFrontendInstall
```

## Stop everything

Use the stop flag with the same launcher family:

```powershell
# PowerShell
.\start_app.ps1 -Stop
```

```bat
REM Command Prompt / batch wrapper
start_app.bat -Stop
```

```bash
# Git Bash, Linux, or macOS
bash ./start_app.sh --stop
```

The stop command checks the process command line before terminating listeners
on frontend port 5173, backend port 8756, and OpenCode port 4097. It refuses to
terminate an unrelated program that happens to occupy one of those ports.

## 1. Check configuration

```powershell
.\backend\.venv\Scripts\python.exe -m codirector.cli check-config
```

This confirms whether AI, Twitch, and OBS settings exist without displaying
secret values. It does not prove that a token is still accepted by Twitch.

## 2. Renew Twitch authorization when necessary

If Twitch reports `Invalid or unauthorized Access Token passed`, run:

```powershell
.\backend\.venv\Scripts\python.exe backend\tools\twitch_oauth.py
```

Complete Twitch authorization in the browser. A localhost browser error is
expected after Twitch redirects. Copy the complete URL from the browser address
bar and paste it into the helper. The helper updates
`TWITCH_USER_ACCESS_TOKEN` and `TWITCH_REFRESH_TOKEN` in `.env` without
displaying either token.

The user access token needs the `chat:read` scope.

## 3. Test live Twitch chat capture

The Twitch listener may be started before or after the stream goes live.
Starting it first is preferable because it confirms the connection before test
comments are sent.

Terminal 1:

```powershell
cd "C:\Users\Gan Ming Hui\Projects\Streamline"
.\backend\.venv\Scripts\python.exe -m codirector.cli listen-twitch
```

After it displays the listening message:

1. Start the Twitch stream from the phone.
2. Open the channel chat using one or more viewer accounts.
3. Send realistic comments containing at least three recognized content words.
4. Press `Ctrl+C` in Terminal 1 to stop the listener.

`listen-twitch` is read-only. It cannot send Twitch messages and does not call
OBS. It currently prints an LLM proposal only after a cluster reaches three
distinct users. Repeated comments from one account do not increase the unique
user count, so a single-user test can verify IRC only through a raw diagnostic
listener, not through visible proposal output.

## 4. Start the backend API

Terminal 1:

```powershell
cd "C:\Users\Gan Ming Hui\Projects\Streamline"
.\backend\.venv\Scripts\python.exe -m codirector.api.server
```

The backend listens on `127.0.0.1:8756` by default.

## 5. Start the frontend

Terminal 2:

```powershell
cd "C:\Users\Gan Ming Hui\Projects\Streamline\frontend"
npm install
npm run dev
```

Open the local URL printed by Vite. Vite proxies `/api` and `/ws` to the
backend at `127.0.0.1:8756`.

## Live Twitch dashboard behavior

Starting the backend now connects the read-only Twitch adapter automatically.
Comments appear immediately in Recent Twitch Chat. Accepted comments are
clustered and sent to reasoning when 50 representative texts accumulate or the
temporary 10-second test deadline expires. Validated model output appears in
LLM Analysis. Restore `chat_batch_max_wait_s` to `120` in `config/app.yaml`
after live testing.

OBS and ASR are still separate integrations and may remain down while the
Twitch-to-reasoning dashboard path works.

Assist-mode Accept also records and removes a queue item without executing its
proposed OBS action. Treat the current build as a proof of concept, not a
complete live production controller.

## Stop the app

Press `Ctrl+C` in each terminal. If a process does not stop, identify only the
specific listener before terminating it:

```powershell
Get-NetTCPConnection -LocalPort 8756 -State Listen |
  Select-Object LocalAddress,LocalPort,OwningProcess
```

Then inspect that exact PID:

```powershell
Get-Process -Id PROCESS_ID
```
