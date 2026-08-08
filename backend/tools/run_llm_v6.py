"""Run the reproducible V6 50-cluster OpenCode structured-output comparison."""

import argparse
import asyncio
import json
import os
import shutil
import time
from pathlib import Path
from typing import Any

import aiohttp
from pydantic import ValidationError

from codirector.adapters.reasoning.http import _REASONING_SCHEMA, _SYSTEM_PROMPT, _clean_json
from codirector.config.loader import load_environment
from codirector.core.models import ReasoningResponse

ROOT = Path(__file__).resolve().parents[2]
RESULTS_PATH = ROOT / "docs" / "LLM_STRUCTURED_OUTPUT_V6_RESULTS.json"
MODELS = [
    "deepseek-v4-flash-free",
    "ling-3.0-tiny-free",
    "laguna-s-2.1-free",
    "longcat-2.0-free",
    "nemotron-3-ultra-free",
    "mimo-v2.5-free",
]
TEXTS = [
    "what microphone are you using today?",
    "what keyboard and switches are you using?",
    "what lights are you using for the stream?",
    "what camera are you using right now?",
    "what chair do you use for long streams?",
    "what monitor do you use for gaming?",
    "what upload speed do you stream with?",
    "what bitrate are you streaming at today?",
    "how do you organize all your OBS scenes?",
    "what audio interface is your microphone plugged into?",
    "what headphones are you wearing on stream?",
    "how did you set up your streaming desk?",
    "where did you get the decorations behind you?",
    "what days do you normally go live?",
    "why did you pick this game today?",
    "what difficulty are you playing this on?",
    "what character build are you going for?",
    "what weapons are you running for this build?",
    "how are you planning to beat this boss?",
    "which route are you taking through this map?",
    "what controller settings are you using here?",
    "what mouse sensitivity do you play on?",
    "what graphics settings are you playing with?",
    "what computer upgrade helped your stream most?",
    "what graphics card is in your computer?",
    "what processor are you gaming and streaming on?",
    "how much memory does your streaming computer have?",
    "what drive do you save your recordings on?",
    "how do you keep your computer cool while streaming?",
    "did you make this stream overlay yourself?",
    "where did you get your stream alert sounds?",
    "who made the emotes for your channel?",
    "what chat rules do your moderators usually enforce?",
    "how do we join your discord server safely?",
    "when are you doing viewer games again?",
    "where do you post your stream highlights?",
    "what do you use to edit your videos?",
    "what playlist is playing in the background?",
    "where do you find music that is safe to stream?",
    "what snacks do you eat during long streams?",
    "what are you drinking on stream today?",
    "how often do you take breaks while streaming?",
    "do you warm up your voice before streaming?",
    "what goals are you working toward this month?",
    "what helped your channel grow the most?",
    "what advice would you give a new streamer?",
    "are you planning streams with other creators?",
    "are you entering tournaments for this game?",
    "when are you doing another charity stream?",
    "what game are you playing after this one?",
]


def clusters() -> list[dict[str, Any]]:
    kinds = ("question", "topic", "reaction")
    return [
        {
            "cluster_id": f"cluster-{index:02d}",
            "kind": kinds[(index - 1) % len(kinds)],
            "unique_user_count": index,
            "representative_text": text,
        }
        for index, text in enumerate(TEXTS, 1)
    ]


def user_input() -> str:
    return json.dumps(
        {"session_summary": "", "clusters": clusters(), "persona": {}},
        ensure_ascii=False,
    )


def system_input(mode: str) -> str:
    if mode == "system_prompt":
        return (
            f"{_SYSTEM_PROMPT}\nReturn JSON only. It must validate against this exact JSON Schema: "
            + json.dumps(_REASONING_SCHEMA, ensure_ascii=False, separators=(",", ":"))
        )
    return _SYSTEM_PROMPT


def validate(value: Any) -> tuple[bool, str, int]:
    try:
        response = ReasoningResponse.model_validate(value)
    except (ValidationError, TypeError) as exc:
        return False, f"local_schema_failure: {exc}", 0
    known = {item["cluster_id"]: item["representative_text"] for item in clusters()}
    for proposal in response.proposals:
        if proposal.cluster_id not in known:
            return False, f"invented_cluster_id: {proposal.cluster_id}", len(response.proposals)
        if proposal.representative_text != known[proposal.cluster_id]:
            return False, f"representative_text_not_verbatim: {proposal.cluster_id}", len(response.proposals)
    return True, "success", len(response.proposals)


def text_value(message: dict) -> str:
    return "".join(
        part.get("text", "")
        for part in message.get("parts", [])
        if part.get("type") == "text"
    )


async def wait_for_server(base_url: str) -> None:
    deadline = time.monotonic() + 30
    async with aiohttp.ClientSession() as session:
        while time.monotonic() < deadline:
            try:
                async with session.get(base_url, timeout=1) as response:
                    if response.status < 500:
                        return
            except (aiohttp.ClientError, TimeoutError):
                await asyncio.sleep(0.25)
    raise RuntimeError("OpenCode server did not become ready")


async def one_call(session: aiohttp.ClientSession, base_url: str, model: str, mode: str) -> dict:
    started = time.perf_counter()
    result = {"model": model, "mode": mode}
    try:
        async with session.post(f"{base_url}/session", json={"title": "Streamline V6"}) as response:
            session_data = await response.json()
            if response.status >= 400:
                raise RuntimeError(f"session HTTP {response.status}: {session_data}")
        session_id = session_data["id"]
        body: dict[str, Any] = {
            "model": {"providerID": "opencode", "modelID": model},
            "system": system_input(mode),
            "parts": [{"type": "text", "text": user_input()}],
        }
        if model == "deepseek-v4-flash-free":
            body["variant"] = "no-thinking"
        if mode == "attribute":
            body["format"] = {
                "type": "json_schema",
                "schema": _REASONING_SCHEMA,
                "retryCount": 3,
            }
        async with session.post(
            f"{base_url}/session/{session_id}/message", json=body
        ) as response:
            raw = await response.json(content_type=None)
            result["http_status"] = response.status
        result["elapsed_seconds"] = round(time.perf_counter() - started, 3)
        if result["http_status"] >= 400:
            result.update(success=False, detail=f"HTTP {result['http_status']}: {raw}")
            return result
        if mode == "attribute":
            value = raw.get("info", {}).get("structured")
            if value is None:
                result.update(success=False, detail="missing info.structured")
                return result
        else:
            output = text_value(raw).strip()
            result["output_preview"] = output[:500]
            try:
                value = json.loads(_clean_json(output))
            except (json.JSONDecodeError, TypeError) as exc:
                result.update(success=False, detail=f"json_parse_failure: {exc}")
                return result
        valid, detail, proposal_count = validate(value)
        result.update(success=valid, detail=detail, proposal_count=proposal_count)
        if valid:
            result["structured"] = value
        return result
    except (aiohttp.ClientError, TimeoutError, RuntimeError, KeyError) as exc:
        result.update(
            success=False,
            elapsed_seconds=round(time.perf_counter() - started, 3),
            detail=f"{type(exc).__name__}: {exc}",
        )
        return result


async def run(args: argparse.Namespace) -> None:
    load_environment(ROOT)
    port = args.port
    base_url = f"http://127.0.0.1:{port}"
    config = {
        "provider": {
            "opencode": {
                "models": {
                    "deepseek-v4-flash-free": {
                        "variants": {"no-thinking": {"reasoningEffort": "none"}}
                    }
                }
            }
        }
    }
    env = os.environ.copy()
    env["OPENCODE_CONFIG_CONTENT"] = json.dumps(config)
    executable = shutil.which(args.opencode) or args.opencode
    process = await asyncio.create_subprocess_exec(
        executable,
        "serve",
        "--hostname",
        "127.0.0.1",
        "--port",
        str(port),
        "--pure",
        cwd=ROOT,
        env=env,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    records: list[dict] = []
    try:
        await wait_for_server(base_url)
        timeout = aiohttp.ClientTimeout(total=args.timeout)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            for model in args.models:
                for mode in args.modes:
                    for attempt in range(1, args.attempts + 1):
                        print(f"{model} {mode} attempt {attempt}", flush=True)
                        record = await one_call(session, base_url, model, mode)
                        record["attempt"] = attempt
                        records.append(record)
                        RESULTS_PATH.write_text(
                            json.dumps(
                                {
                                    "metadata": {
                                        "opencode_version": "1.18.15",
                                        "attempts": args.attempts,
                                        "cluster_count": 50,
                                        "models": args.models,
                                        "modes": args.modes,
                                        "system_inputs": {
                                            mode: system_input(mode) for mode in args.modes
                                        },
                                        "user_input": json.loads(user_input()),
                                        "schema": _REASONING_SCHEMA,
                                    },
                                    "results": records,
                                },
                                ensure_ascii=False,
                                indent=2,
                            ),
                            encoding="utf-8",
                        )
                        print(json.dumps(record, ensure_ascii=False), flush=True)
    finally:
        if process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=10)
            except TimeoutError:
                process.kill()
                await process.wait()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", nargs="+", default=MODELS)
    parser.add_argument("--modes", nargs="+", choices=["attribute", "system_prompt"], default=["attribute", "system_prompt"])
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=150)
    parser.add_argument("--port", type=int, default=4098)
    parser.add_argument("--opencode", default=os.getenv("OPENCODE_CLI_PATH", "opencode"))
    return parser.parse_args()


if __name__ == "__main__":
    load_environment(ROOT)
    asyncio.run(run(parse_args()))
