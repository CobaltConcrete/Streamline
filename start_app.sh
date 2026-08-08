#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
frontend_directory="$project_root/frontend"
dashboard_url="http://localhost:5173"

stop_unix_listener() {
  local port="$1"
  local expected="$2"
  local label="$3"
  local pids
  if ! command -v lsof >/dev/null 2>&1; then
    echo "lsof is required to stop services safely on this platform." >&2
    return 1
  fi
  pids="$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)"
  if [[ -z "$pids" ]]; then
    echo "$label is not listening on port $port."
    return
  fi
  for pid in $pids; do
    command_line="$(ps -p "$pid" -o command= 2>/dev/null || true)"
    if [[ ! "$command_line" =~ $expected ]]; then
      echo "Refusing to stop PID $pid on port $port; command was: $command_line" >&2
      continue
    fi
    kill "$pid"
    echo "Stopped $label (PID $pid, port $port)."
  done
}

if [[ "${1:-}" == "-stop" || "${1:-}" == "--stop" ]]; then
  if command -v powershell.exe >/dev/null 2>&1; then
    if command -v cygpath >/dev/null 2>&1; then
      powershell_script="$(cygpath -w "$project_root/start_app.ps1")"
    else
      powershell_script="$project_root/start_app.ps1"
    fi
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$powershell_script" -Stop
  else
    stop_unix_listener 5173 '(vite|npm.*run dev)' 'frontend'
    stop_unix_listener 8756 'codirector\.api\.server' 'backend'
    sleep 0.5
    stop_unix_listener 4097 'opencode.*serve.*4097' 'OpenCode server'
  fi
  exit 0
fi

if [[ -x "$project_root/backend/.venv/Scripts/python.exe" ]]; then
  backend_python="$project_root/backend/.venv/Scripts/python.exe"
elif [[ -x "$project_root/backend/.venv/bin/python" ]]; then
  backend_python="$project_root/backend/.venv/bin/python"
else
  echo "Backend virtual environment not found under backend/.venv" >&2
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "npm was not found on PATH. Install Node.js 20 or newer." >&2
  exit 1
fi

pids=()

cleanup() {
  if ((${#pids[@]})); then
    kill "${pids[@]}" 2>/dev/null || true
    wait "${pids[@]}" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

if curl --silent --fail http://127.0.0.1:8756/api/health >/dev/null 2>&1; then
  echo "Backend is already running on port 8756."
else
  (
    cd "$project_root"
    exec "$backend_python" -u -m codirector.api.server
  ) &
  backend_pid=$!
  pids+=("$backend_pid")
  echo "Backend started (PID $backend_pid)."
fi

if curl --silent --fail "$dashboard_url" >/dev/null 2>&1; then
  echo "Frontend is already running on port 5173."
else
  (
    cd "$frontend_directory"
    if [[ ! -d node_modules ]]; then
      npm install
    fi
    exec npm run dev
  ) &
  frontend_pid=$!
  pids+=("$frontend_pid")
  echo "Frontend started (PID $frontend_pid)."
fi

echo "Waiting for backend and frontend..."
for _ in {1..120}; do
  backend_ready=false
  frontend_ready=false
  curl --silent --fail http://127.0.0.1:8756/api/health >/dev/null 2>&1 && backend_ready=true
  curl --silent --fail "$dashboard_url" >/dev/null 2>&1 && frontend_ready=true
  if [[ "$backend_ready" == true && "$frontend_ready" == true ]]; then
    echo "Streamline is ready: $dashboard_url"
    if command -v cmd.exe >/dev/null 2>&1; then
      cmd.exe /c start "" "$dashboard_url" >/dev/null 2>&1 || true
    elif command -v open >/dev/null 2>&1; then
      open "$dashboard_url" >/dev/null 2>&1 || true
    elif command -v xdg-open >/dev/null 2>&1; then
      xdg-open "$dashboard_url" >/dev/null 2>&1 || true
    fi
    echo "Press Ctrl+C to stop processes started by this script."
    while true; do sleep 3600; done
  fi
  sleep 0.5
done

echo "Services did not become ready within 60 seconds." >&2
exit 1
