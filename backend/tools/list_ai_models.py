# ruff: noqa: UP017 -- Local validation also runs on Python 3.10; datetime.UTC is 3.11+.
"""List models available through every configured AI provider.

Credentials are loaded from the repository-root .env (with process environment
variables taking precedence), used only in request headers, and never printed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from dotenv import dotenv_values

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENV_FILE = REPO_ROOT / ".env"
ANSI_ESCAPE_RE = re.compile(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    key_names: tuple[str, ...]
    base_url: str
    models_path: str
    auth_style: str


@dataclass(frozen=True)
class ModelRow:
    provider: str
    status: str
    model_id: str
    display_name: str


@dataclass(frozen=True)
class UsageRow:
    provider: str
    status: str
    metric: str
    value: str
    detail: str = ""


def _setting(values: Mapping[str, str], name: str, default: str = "") -> str:
    return values.get(name, default).strip()


def load_settings(env_file: Path) -> dict[str, str]:
    if not env_file.is_file():
        raise FileNotFoundError(f"environment file not found: {env_file}")
    values = {key: value or "" for key, value in dotenv_values(env_file).items()}
    # Match normal dotenv behavior: explicit process values override .env.
    values.update({key: value for key, value in os.environ.items() if value})
    return values


def provider_specs(values: Mapping[str, str]) -> list[ProviderSpec]:
    return [
        ProviderSpec(
            name="OpenCode",
            key_names=("OPENCODE_API_KEY",),
            base_url=_setting(values, "OPENCODE_BASE_URL", "https://opencode.ai/zen/v1"),
            models_path="models",
            auth_style="bearer",
        ),
        ProviderSpec(
            name="OpenRouter",
            key_names=("OPENROUTER_API_KEY",),
            base_url=_setting(
                values, "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
            ),
            models_path="models/user",
            auth_style="bearer",
        ),
        ProviderSpec(
            name="Anthropic",
            key_names=("ANTHROPIC_API_KEY", "CLAUDE_API_KEY"),
            base_url=_setting(values, "ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1"),
            models_path="models?limit=1000",
            auth_style="anthropic",
        ),
        ProviderSpec(
            name="OpenAI",
            key_names=("OPENAI_API_KEY",),
            base_url=_setting(values, "OPENAI_BASE_URL", "https://api.openai.com/v1"),
            models_path="models",
            auth_style="openai",
        ),
    ]


def _api_base(base_url: str) -> str:
    base = base_url.rstrip("/")
    for suffix in ("/responses", "/chat/completions", "/messages"):
        if base.endswith(suffix):
            return base[: -len(suffix)]
    return base


def _api_key(spec: ProviderSpec, values: Mapping[str, str]) -> str:
    return next((_setting(values, name) for name in spec.key_names if _setting(values, name)), "")


def _headers(spec: ProviderSpec, api_key: str, values: Mapping[str, str]) -> dict[str, str]:
    headers = {"Accept": "application/json", "User-Agent": "Streamline-CoDirector/0.1"}
    if spec.auth_style == "anthropic":
        headers.update({"x-api-key": api_key, "anthropic-version": "2023-06-01"})
    else:
        headers["Authorization"] = f"Bearer {api_key}"

    if spec.auth_style == "openai":
        organization = _setting(values, "OPENAI_ORGANIZATION")
        project = _setting(values, "OPENAI_PROJECT")
        if organization:
            headers["OpenAI-Organization"] = organization
        if project:
            headers["OpenAI-Project"] = project
    return headers


def _error_detail(exc: urllib.error.HTTPError) -> str:
    try:
        payload = json.loads(exc.read().decode("utf-8"))
        error = payload.get("error", payload)
        if isinstance(error, dict):
            detail = error.get("message") or error.get("type")
        else:
            detail = error
        if isinstance(detail, str) and detail.strip():
            return detail.strip().replace("\n", " ")[:120]
    except (UnicodeDecodeError, json.JSONDecodeError):
        pass
    return f"HTTP {exc.code}"


def _fetch_json(
    endpoint: str, headers: Mapping[str, str], *, timeout_s: float
) -> tuple[dict[str, Any] | None, str | None]:
    request = urllib.request.Request(endpoint, headers=dict(headers), method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        return None, _error_detail(exc)
    except (urllib.error.URLError, TimeoutError) as exc:
        reason = getattr(exc, "reason", exc)
        return None, f"request failed: {reason}"
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError):
        return None, "provider returned invalid JSON"
    if not isinstance(payload, dict):
        return None, "provider returned an invalid response"
    return payload, None


def discover_models(
    spec: ProviderSpec,
    values: Mapping[str, str],
    *,
    timeout_s: float,
) -> list[ModelRow]:
    api_key = _api_key(spec, values)
    if not api_key:
        expected = " or ".join(spec.key_names)
        return [ModelRow(spec.name, "NOT AVAILABLE", "-", f"missing {expected}")]

    endpoint = f"{_api_base(spec.base_url)}/{spec.models_path}"
    request = urllib.request.Request(
        endpoint,
        headers=_headers(spec, api_key, values),
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        return [ModelRow(spec.name, "ERROR", "-", _error_detail(exc))]
    except (urllib.error.URLError, TimeoutError) as exc:
        reason = getattr(exc, "reason", exc)
        return [ModelRow(spec.name, "ERROR", "-", f"request failed: {reason}")]
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError):
        return [ModelRow(spec.name, "ERROR", "-", "provider returned invalid JSON")]

    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        return [ModelRow(spec.name, "ERROR", "-", "response has no model list")]

    models: list[ModelRow] = []
    for item in data:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            continue
        display_name = item.get("display_name") or item.get("name") or ""
        models.append(
            ModelRow(
                spec.name,
                "AVAILABLE",
                item["id"],
                str(display_name),
            )
        )
    if not models:
        return [ModelRow(spec.name, "AVAILABLE", "-", "no models returned")]
    return sorted(models, key=lambda row: row.model_id.lower())


def _money(value: object, *, minor_units: bool = False) -> str:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return "unknown"
    if minor_units:
        amount /= Decimal(100)
    return f"${amount:,.4f} USD"


def _usage_period(days: int) -> tuple[datetime, datetime]:
    end = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return end - timedelta(days=days), end


def _base_headers() -> dict[str, str]:
    return {"Accept": "application/json", "User-Agent": "Streamline-CoDirector/0.1"}


def _openrouter_usage(
    spec: ProviderSpec, values: Mapping[str, str], *, timeout_s: float
) -> list[UsageRow]:
    api_key = _api_key(spec, values)
    if not api_key:
        return [UsageRow(spec.name, "NOT AVAILABLE", "-", "-", "missing OPENROUTER_API_KEY")]
    headers = _base_headers()
    headers["Authorization"] = f"Bearer {api_key}"
    payload, error = _fetch_json(
        f"{_api_base(spec.base_url)}/key", headers, timeout_s=timeout_s
    )
    if error:
        return [UsageRow(spec.name, "ERROR", "-", "-", error)]
    data = payload.get("data") if payload else None
    if not isinstance(data, dict):
        return [UsageRow(spec.name, "ERROR", "-", "-", "response has no usage data")]

    metrics = (
        ("All-time key usage", "usage"),
        ("Daily key usage", "usage_daily"),
        ("Weekly key usage", "usage_weekly"),
        ("Monthly key usage", "usage_monthly"),
        ("Spending limit remaining", "limit_remaining"),
    )
    rows = [
        UsageRow(spec.name, "AVAILABLE", label, _money(data[field]))
        for label, field in metrics
        if data.get(field) is not None
    ]
    return rows or [UsageRow(spec.name, "AVAILABLE", "Usage", "not reported")]


def _resolve_opencode(values: Mapping[str, str]) -> str | None:
    command_name = _setting(values, "OPENCODE_CLI_PATH", "opencode")
    configured_path = Path(command_name).expanduser()
    if configured_path.is_file():
        return str(configured_path.resolve())
    executable = shutil.which(command_name)
    if executable:
        return executable

    # npm's global shim directory is not always added to PATH on Windows.
    npm = shutil.which("npm")
    if not npm:
        return None
    try:
        prefix_result = subprocess.run(
            [npm, "prefix", "-g"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if prefix_result.returncode != 0 or not prefix_result.stdout.strip():
        return None
    prefix = Path(prefix_result.stdout.strip())
    candidates = (
        prefix / "opencode.cmd",
        prefix / "opencode.exe",
        prefix / "bin" / "opencode",
    )
    return next((str(candidate) for candidate in candidates if candidate.is_file()), None)


def _install_opencode(
    values: Mapping[str, str], *, timeout_s: float
) -> tuple[str | None, str | None]:
    npm = shutil.which("npm")
    if not npm:
        return None, "npm is required for automatic OpenCode installation but was not found"
    try:
        result = subprocess.run(
            [npm, "install", "-g", "opencode-ai"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(timeout_s, 180),
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"automatic OpenCode installation failed: {exc}"
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        return None, f"npm install failed: {detail[:100]}"
    executable = _resolve_opencode(values)
    if not executable:
        return None, "OpenCode installed, but its executable could not be located"
    return executable, None


def _opencode_usage(
    values: Mapping[str, str],
    *,
    timeout_s: float,
    days: int,
    install_missing: bool,
) -> tuple[list[UsageRow], str | None]:
    executable = _resolve_opencode(values)
    install_error = None
    if not executable and install_missing:
        executable, install_error = _install_opencode(values, timeout_s=timeout_s)
    if not executable:
        detail = install_error or (
            "OpenCode CLI not found; rerun with --install-opencode, or set "
            "OPENCODE_CLI_PATH"
        )
        return (
            [
                UsageRow(
                    "OpenCode",
                    "NOT AVAILABLE",
                    f"Local usage (last {days} days)",
                    "-",
                    detail,
                )
            ],
            None,
        )

    command = [
        executable,
        "stats",
        "--days",
        str(days),
        "--models",
        "10",
    ]
    environment = dict(os.environ)
    # Avoid terminal control codes in captured output when the CLI honors these conventions.
    environment.update({"NO_COLOR": "1", "FORCE_COLOR": "0"})
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
            check=False,
            env=environment,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return [UsageRow("OpenCode", "ERROR", "Local session usage", "-", str(exc)[:120])], None

    stdout = ANSI_ESCAPE_RE.sub("", result.stdout).strip()
    stderr = ANSI_ESCAPE_RE.sub("", result.stderr).strip()
    if result.returncode != 0:
        detail = stderr or stdout or f"opencode stats exited with code {result.returncode}"
        return [UsageRow("OpenCode", "ERROR", "Local session usage", "-", detail[:120])], None
    report = stdout or stderr
    if not report:
        return (
            [UsageRow("OpenCode", "AVAILABLE", "Local session usage", "no data", "opencode stats")],
            None,
        )
    return (
        [
            UsageRow(
                "OpenCode",
                "AVAILABLE",
                f"Local usage (last {days} days)",
                "see report below",
                "opencode stats; does not include hosted Zen credit balance",
            )
        ],
        report,
    )


def _openai_usage(
    spec: ProviderSpec, values: Mapping[str, str], *, timeout_s: float, days: int
) -> list[UsageRow]:
    admin_key = _setting(values, "OPENAI_ADMIN_KEY")
    if not admin_key:
        return [
            UsageRow(
                spec.name,
                "NOT AVAILABLE",
                f"Cost (last {days} days)",
                "-",
                "requires OPENAI_ADMIN_KEY; standard API keys cannot read organization costs",
            )
        ]
    start, _ = _usage_period(days)
    query = urlencode({"start_time": int(start.timestamp()), "limit": days})
    headers = _base_headers()
    headers["Authorization"] = f"Bearer {admin_key}"
    payload, error = _fetch_json(
        f"{_api_base(spec.base_url)}/organization/costs?{query}",
        headers,
        timeout_s=timeout_s,
    )
    if error:
        return [UsageRow(spec.name, "ERROR", "-", "-", error)]
    total = Decimal(0)
    try:
        for bucket in payload.get("data", []):
            for result in bucket.get("results", []):
                total += Decimal(str(result["amount"]["value"]))
    except (AttributeError, KeyError, TypeError, InvalidOperation):
        return [UsageRow(spec.name, "ERROR", "-", "-", "invalid organization costs response")]
    return [UsageRow(spec.name, "AVAILABLE", f"Cost (last {days} days)", _money(total))]


def _anthropic_usage(
    spec: ProviderSpec, values: Mapping[str, str], *, timeout_s: float, days: int
) -> list[UsageRow]:
    admin_key = _setting(values, "ANTHROPIC_ADMIN_KEY")
    if not admin_key:
        return [
            UsageRow(
                spec.name,
                "NOT AVAILABLE",
                f"Cost (last {days} days)",
                "-",
                "requires ANTHROPIC_ADMIN_KEY; unavailable to individual accounts",
            )
        ]
    start, end = _usage_period(days)
    query = urlencode(
        {
            "starting_at": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "ending_at": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "bucket_width": "1d",
            "limit": days,
        }
    )
    headers = _base_headers()
    headers.update({"x-api-key": admin_key, "anthropic-version": "2023-06-01"})
    payload, error = _fetch_json(
        f"{_api_base(spec.base_url)}/organizations/cost_report?{query}",
        headers,
        timeout_s=timeout_s,
    )
    if error:
        return [UsageRow(spec.name, "ERROR", "-", "-", error)]
    total_minor_units = Decimal(0)
    try:
        for bucket in payload.get("data", []):
            for result in bucket.get("results", []):
                total_minor_units += Decimal(str(result["amount"]))
    except (AttributeError, KeyError, TypeError, InvalidOperation):
        return [UsageRow(spec.name, "ERROR", "-", "-", "invalid organization costs response")]
    return [
        UsageRow(
            spec.name,
            "AVAILABLE",
            f"Cost (last {days} days)",
            _money(total_minor_units, minor_units=True),
        )
    ]


def discover_usage(
    spec: ProviderSpec,
    values: Mapping[str, str],
    *,
    timeout_s: float,
    days: int,
    reports: dict[str, str] | None = None,
    install_opencode: bool = False,
) -> list[UsageRow]:
    if spec.name == "OpenCode":
        rows, report = _opencode_usage(
            values,
            timeout_s=timeout_s,
            days=days,
            install_missing=install_opencode,
        )
        if reports is not None and report:
            reports[spec.name] = report
        return rows
    if spec.name == "OpenRouter":
        return _openrouter_usage(spec, values, timeout_s=timeout_s)
    if spec.name == "OpenAI":
        return _openai_usage(spec, values, timeout_s=timeout_s, days=days)
    if spec.name == "Anthropic":
        return _anthropic_usage(spec, values, timeout_s=timeout_s, days=days)

    return [UsageRow(spec.name, "UNSUPPORTED", "Usage", "-", "unknown provider")]


def _truncate(value: str, width: int) -> str:
    if len(value) <= width:
        return value
    return value[: width - 3] + "..."


def render_table(rows: list[ModelRow]) -> str:
    headers = ("Provider", "Status", "Model ID", "Display name / detail")
    raw = [(row.provider, row.status, row.model_id, row.display_name) for row in rows]
    model_width = min(60, max(len(headers[2]), *(len(row[2]) for row in raw)))
    detail_width = min(60, max(len(headers[3]), *(len(row[3]) for row in raw)))
    widths = (
        max(len(headers[0]), *(len(row[0]) for row in raw)),
        max(len(headers[1]), *(len(row[1]) for row in raw)),
        model_width,
        detail_width,
    )

    def line(parts: tuple[str, str, str, str]) -> str:
        clipped = tuple(_truncate(value, width) for value, width in zip(parts, widths, strict=True))
        return "| " + " | ".join(value.ljust(width) for value, width in zip(clipped, widths, strict=True)) + " |"

    separator = "+-" + "-+-".join("-" * width for width in widths) + "-+"
    output = [separator, line(headers), separator]
    output.extend(line(row) for row in raw)
    output.append(separator)
    return "\n".join(output)


def render_usage_table(rows: list[UsageRow]) -> str:
    headers = ("Provider", "Status", "Metric", "Value", "Detail")
    raw = [
        (row.provider, row.status, row.metric, row.value, row.detail)
        for row in rows
    ]
    widths = tuple(
        min(72 if index == 4 else 40, max(len(headers[index]), *(len(row[index]) for row in raw)))
        for index in range(len(headers))
    )

    def line(parts: tuple[str, str, str, str, str]) -> str:
        clipped = tuple(
            _truncate(value, width) for value, width in zip(parts, widths, strict=True)
        )
        return (
            "| "
            + " | ".join(
                value.ljust(width) for value, width in zip(clipped, widths, strict=True)
            )
            + " |"
        )

    separator = "+-" + "-+-".join("-" * width for width in widths) + "-+"
    output = [separator, line(headers), separator]
    output.extend(line(row) for row in raw)
    output.append(separator)
    return "\n".join(output)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="List models available to each AI provider configured in .env."
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=DEFAULT_ENV_FILE,
        help="dotenv file to read (default: repository-root .env)",
    )
    parser.add_argument(
        "--provider",
        choices=("all", "opencode", "openrouter", "anthropic", "openai"),
        default="all",
        help="query one provider instead of all providers",
    )
    parser.add_argument("--timeout", type=float, default=15.0, help="request timeout in seconds")
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="maximum model rows per provider; 0 prints all models",
    )
    parser.add_argument(
        "--check-usage",
        action="store_true",
        help="show available usage/cost data instead of model inventory",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="cost-report window for OpenAI/Anthropic (1-30 days; default: 30)",
    )
    parser.add_argument(
        "--install-opencode",
        action="store_true",
        help="install the official opencode-ai npm package if the CLI is missing",
    )
    return parser.parse_args()


def run(args: argparse.Namespace) -> int:
    if args.install_opencode and not args.check_usage:
        print("--install-opencode requires --check-usage", file=sys.stderr)
        return 1
    try:
        values = load_settings(args.env_file.resolve())
    except FileNotFoundError as exc:
        print(f"Model discovery failed: {exc}", file=sys.stderr)
        return 1

    specs = provider_specs(values)
    if args.provider != "all":
        specs = [spec for spec in specs if spec.name.lower() == args.provider]

    if args.check_usage:
        if not 1 <= args.days <= 30:
            print("Usage discovery failed: --days must be between 1 and 30", file=sys.stderr)
            return 1
        reports: dict[str, str] = {}
        usage_rows = []
        for spec in specs:
            usage_rows.extend(
                discover_usage(
                    spec,
                    values,
                    timeout_s=args.timeout,
                    days=args.days,
                    reports=reports,
                    install_opencode=args.install_opencode,
                )
            )
        print(render_usage_table(usage_rows))
        for provider, report in reports.items():
            print(f"\n{provider} local session statistics\n{'-' * 33}\n{report}")
        return 0 if not any(row.status == "ERROR" for row in usage_rows) else 2

    rows: list[ModelRow] = []
    for spec in specs:
        provider_rows = discover_models(spec, values, timeout_s=args.timeout)
        if args.limit > 0 and len(provider_rows) > args.limit:
            omitted = len(provider_rows) - args.limit
            provider_rows = provider_rows[: args.limit]
            provider_rows.append(ModelRow(spec.name, "TRUNCATED", "-", f"{omitted} more; rerun without --limit"))
        rows.extend(provider_rows)

    print(render_table(rows))
    return 0 if not any(row.status == "ERROR" for row in rows) else 2


def main() -> None:
    raise SystemExit(run(parse_args()))


if __name__ == "__main__":
    main()
