"""OpenCode Server structured-output provider verified by the V5/V6 matrix."""

import asyncio
import json
import os
import shutil
import time
from contextlib import suppress
from pathlib import Path
from typing import Literal

import aiohttp
from pydantic import ValidationError

from codirector.adapters.base import ReasoningPrompt
from codirector.adapters.reasoning.http import (
    _EMPTY,
    _REASONING_SCHEMA,
    _clean_json,
    _ground_response,
    _system_prompt,
)
from codirector.core.models import ReasoningResponse


class OpenCodeServerReasoningProvider:
    """Own or reuse a local OpenCode server and require strict output."""

    def __init__(
        self,
        *,
        models: list[str],
        structured_output_mode: Literal["attribute", "system_prompt"],
        max_attempts: int,
        timeout_s: float,
        server_url: str = "http://127.0.0.1:4097",
        cli_path: str = "opencode",
        workdir: Path | None = None,
    ) -> None:
        self.models = list(dict.fromkeys(models))
        self.structured_output_mode = structured_output_mode
        self.max_attempts = max_attempts
        self.timeout_s = timeout_s
        self.server_url = server_url.rstrip("/")
        self.cli_path = cli_path
        self.workdir = workdir or Path.cwd()
        self._process: asyncio.subprocess.Process | None = None
        self.last_error = "not started"

    async def start(self) -> None:
        if await self._server_ready():
            self.last_error = ""
            return
        executable = shutil.which(self.cli_path) or self.cli_path
        command_path = Path(executable)
        if command_path.suffix.casefold() in {".cmd", ".bat"}:
            native_binary = (
                command_path.parent / "node_modules" / "opencode-ai" / "bin" / "opencode.exe"
            )
            if native_binary.exists():
                executable = str(native_binary)
        config = {
            "provider": {
                "opencode": {
                    "models": {
                        "deepseek-v4-flash-free": {
                            "variants": {
                                "no-thinking": {"reasoningEffort": "none"}
                            }
                        }
                    }
                }
            }
        }
        env = os.environ.copy()
        env["OPENCODE_CONFIG_CONTENT"] = json.dumps(config)
        port = self.server_url.rsplit(":", 1)[-1]
        self._process = await asyncio.create_subprocess_exec(
            executable,
            "serve",
            "--hostname",
            "127.0.0.1",
            "--port",
            port,
            "--pure",
            cwd=self.workdir,
            env=env,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if await self._server_ready():
                self.last_error = ""
                return
            if self._process.returncode is not None:
                break
            await asyncio.sleep(0.25)
        raise RuntimeError("OpenCode server did not become ready")

    async def stop(self) -> None:
        if self._process is None or self._process.returncode is not None:
            return
        self._process.terminate()
        try:
            await asyncio.wait_for(self._process.wait(), timeout=10)
        except TimeoutError:
            self._process.kill()
            await self._process.wait()

    async def propose(self, prompt: ReasoningPrompt) -> ReasoningResponse:
        input_text = json.dumps(
            {
                "session_summary": prompt.session_summary,
                "clusters": prompt.cluster_context,
                "persona": prompt.persona,
            },
            ensure_ascii=False,
        )
        for model in self.models:
            for _attempt in range(self.max_attempts):
                try:
                    value = await self._request(model, input_text)
                    result = ReasoningResponse.model_validate(value)
                    self.last_error = ""
                    return _ground_response(result, prompt)
                except (
                    aiohttp.ClientError,
                    TimeoutError,
                    ValueError,
                    TypeError,
                    KeyError,
                    ValidationError,
                ) as exc:
                    self.last_error = f"{model}: {type(exc).__name__}: {exc}"
        return _EMPTY

    async def _request(self, model: str, input_text: str):
        timeout = aiohttp.ClientTimeout(total=self.timeout_s)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                f"{self.server_url}/session", json={"title": "Streamline live reasoning"}
            ) as response:
                response.raise_for_status()
                session_id = (await response.json())["id"]
            body = {
                "model": {"providerID": "opencode", "modelID": model},
                "system": _system_prompt(self.structured_output_mode),
                "parts": [{"type": "text", "text": input_text}],
            }
            if model == "deepseek-v4-flash-free":
                body["variant"] = "no-thinking"
            if self.structured_output_mode == "attribute":
                body["format"] = {
                    "type": "json_schema",
                    "schema": _REASONING_SCHEMA,
                    "retryCount": 3,
                }
            try:
                async with session.post(
                    f"{self.server_url}/session/{session_id}/message", json=body
                ) as response:
                    response.raise_for_status()
                    raw = await response.json(content_type=None)
            finally:
                with suppress(aiohttp.ClientError, TimeoutError):
                    await session.delete(f"{self.server_url}/session/{session_id}")

        if self.structured_output_mode == "attribute":
            structured = raw.get("info", {}).get("structured")
            if structured is None:
                raise ValueError("OpenCode response omitted info.structured")
            return structured
        text = "".join(
            part.get("text", "")
            for part in raw.get("parts", [])
            if part.get("type") == "text"
        )
        return json.loads(_clean_json(text))

    async def _server_ready(self) -> bool:
        try:
            timeout = aiohttp.ClientTimeout(total=1)
            async with (
                aiohttp.ClientSession(timeout=timeout) as session,
                session.get(self.server_url) as response,
            ):
                return response.status < 500
        except (aiohttp.ClientError, TimeoutError):
            return False
