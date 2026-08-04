# Backend Agent Notes

Read the repository-root `AGENTS.md` first.

The backend is organized by responsibility: `adapters/` for external systems,
`core/` for pure event/context/decision logic, `policy/` for deny-by-default
authorization, `orchestrator/` for OBS effects and rollback, `queue/` for the
three-item creator queue, `audit/` for SQLite, and `api/` for REST/WebSocket
presentation state.

Do not bypass `PolicyEngine`, mutate event trust, read secrets outside
`config/loader.py`, or put real external calls in tests. Async tests use
`pytest-asyncio` auto mode. Pass clocks explicitly in core tests; use short
real waits only for behavior that is specifically about scheduling latency.

Commands from this directory:

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\python.exe -m ruff check codirector tools
.\.venv\Scripts\python.exe -m codirector.cli check-config
.\.venv\Scripts\python.exe -m codirector.cli listen-twitch
.\.venv\Scripts\python.exe -m codirector.api.server
```
