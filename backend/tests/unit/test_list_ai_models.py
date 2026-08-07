import io
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import list_ai_models


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def _response(payload):
    return _Response(json.dumps(payload).encode("utf-8"))


def test_missing_keys_are_explicitly_not_available():
    rows = [
        row
        for spec in list_ai_models.provider_specs({})
        for row in list_ai_models.discover_models(spec, {}, timeout_s=1)
    ]

    assert len(rows) == 4
    assert {row.provider for row in rows} == {"OpenCode", "OpenRouter", "Anthropic", "OpenAI"}
    assert all(row.status == "NOT AVAILABLE" for row in rows)
    assert "OPENCODE_API_KEY" in rows[0].display_name


def test_each_provider_uses_its_native_model_endpoint_and_authentication():
    values = {
        "OPENCODE_API_KEY": "opencode-secret",
        "OPENROUTER_API_KEY": "openrouter-secret",
        "CLAUDE_API_KEY": "claude-secret",
        "OPENAI_API_KEY": "openai-secret",
        "OPENAI_ORGANIZATION": "org-id",
        "OPENAI_PROJECT": "project-id",
    }
    seen = []

    def fake_urlopen(request, timeout):
        seen.append((request.full_url, dict(request.header_items()), timeout))
        return _response({"data": [{"id": "model-1", "name": "Model One"}]})

    with patch("list_ai_models.urllib.request.urlopen", side_effect=fake_urlopen):
        rows = [
            row
            for spec in list_ai_models.provider_specs(values)
            for row in list_ai_models.discover_models(spec, values, timeout_s=7)
        ]

    assert all(row.status == "AVAILABLE" for row in rows)
    assert [entry[0] for entry in seen] == [
        "https://opencode.ai/zen/v1/models",
        "https://openrouter.ai/api/v1/models/user",
        "https://api.anthropic.com/v1/models?limit=1000",
        "https://api.openai.com/v1/models",
    ]
    assert seen[0][1]["Authorization"] == "Bearer opencode-secret"
    assert seen[1][1]["Authorization"] == "Bearer openrouter-secret"
    assert seen[2][1]["X-api-key"] == "claude-secret"
    assert seen[2][1]["Anthropic-version"] == "2023-06-01"
    assert seen[3][1]["Authorization"] == "Bearer openai-secret"
    assert seen[3][1]["Openai-organization"] == "org-id"
    assert seen[3][1]["Openai-project"] == "project-id"


def test_rendered_table_does_not_contain_credentials():
    secret = "never-print-this-secret"
    spec = list_ai_models.ProviderSpec(
        "OpenAI", ("OPENAI_API_KEY",), "https://api.openai.com/v1", "models", "openai"
    )
    with patch(
        "list_ai_models.urllib.request.urlopen",
        return_value=_response({"data": [{"id": "gpt-test", "name": "Test"}]}),
    ):
        rows = list_ai_models.discover_models(
            spec, {"OPENAI_API_KEY": secret}, timeout_s=1
        )

    table = list_ai_models.render_table(rows)
    assert secret not in table
    assert "gpt-test" in table
    assert "AVAILABLE" in table


def test_custom_completion_url_is_normalized_to_models_base():
    spec = list_ai_models.ProviderSpec(
        "OpenRouter",
        ("OPENROUTER_API_KEY",),
        "https://example.test/v1/chat/completions",
        "models/user",
        "bearer",
    )
    with patch(
        "list_ai_models.urllib.request.urlopen",
        return_value=_response({"data": []}),
    ) as urlopen:
        list_ai_models.discover_models(
            spec, {"OPENROUTER_API_KEY": "secret"}, timeout_s=1
        )

    assert urlopen.call_args.args[0].full_url == "https://example.test/v1/models/user"


def test_usage_without_required_keys_is_explicit():
    with patch("list_ai_models._resolve_opencode", return_value=None):
        rows = [
            row
            for spec in list_ai_models.provider_specs({})
            for row in list_ai_models.discover_usage(spec, {}, timeout_s=1, days=30)
        ]

    assert len(rows) == 4
    assert all(row.status == "NOT AVAILABLE" for row in rows)
    assert "OpenCode CLI" in rows[0].detail
    assert "OPENROUTER_API_KEY" in rows[1].detail
    assert "ANTHROPIC_ADMIN_KEY" in rows[2].detail
    assert "OPENAI_ADMIN_KEY" in rows[3].detail


def test_opencode_usage_uses_local_cli_and_preserves_native_report():
    spec = list_ai_models.provider_specs({})[0]
    reports = {}
    completed = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout="Tokens  12,345\nCost  $1.23\nModels  model-a",
        stderr="",
    )
    with (
        patch(
            "list_ai_models._resolve_opencode", return_value=r"C:\bin\opencode.cmd"
        ),
        patch("list_ai_models.subprocess.run", return_value=completed) as run,
    ):
        rows = list_ai_models.discover_usage(
            spec, {}, timeout_s=4, days=7, reports=reports
        )

    assert rows[0].status == "AVAILABLE"
    assert rows[0].value == "see report below"
    assert "Zen credit balance" in rows[0].detail
    assert reports["OpenCode"] == completed.stdout
    assert run.call_args.args[0] == [
        r"C:\bin\opencode.cmd",
        "stats",
        "--days",
        "7",
        "--models",
        "10",
    ]


def test_opencode_usage_reports_cli_failure_without_hiding_other_providers():
    spec = list_ai_models.provider_specs({})[0]
    completed = subprocess.CompletedProcess(
        args=[], returncode=1, stdout="", stderr="database unavailable"
    )
    with (
        patch("list_ai_models._resolve_opencode", return_value="opencode"),
        patch("list_ai_models.subprocess.run", return_value=completed),
    ):
        rows = list_ai_models.discover_usage(spec, {}, timeout_s=1, days=30)

    assert rows[0].status == "ERROR"
    assert rows[0].detail == "database unavailable"


def test_opencode_can_be_installed_automatically_before_collecting_stats():
    spec = list_ai_models.provider_specs({})[0]
    installed = subprocess.CompletedProcess(args=[], returncode=0, stdout="ok", stderr="")
    stats = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="Tokens  100", stderr=""
    )
    reports = {}
    with (
        patch(
            "list_ai_models._resolve_opencode",
            side_effect=[None, r"C:\npm\opencode.cmd"],
        ),
        patch("list_ai_models.shutil.which", return_value=r"C:\node\npm.cmd"),
        patch("list_ai_models.subprocess.run", side_effect=[installed, stats]) as run,
    ):
        rows = list_ai_models.discover_usage(
            spec,
            {},
            timeout_s=2,
            days=30,
            reports=reports,
            install_opencode=True,
        )

    assert rows[0].status == "AVAILABLE"
    assert reports["OpenCode"] == "Tokens  100"
    assert run.call_args_list[0].args[0] == [
        r"C:\node\npm.cmd",
        "install",
        "-g",
        "opencode-ai",
    ]


def test_openrouter_standard_key_reports_usage_table_rows():
    spec = list_ai_models.provider_specs({})[1]
    payload = {
        "data": {
            "usage": 12.5,
            "usage_daily": 1.25,
            "usage_weekly": 4,
            "usage_monthly": 10,
            "limit_remaining": 7.5,
        }
    }
    with patch(
        "list_ai_models.urllib.request.urlopen",
        return_value=_response(payload),
    ) as urlopen:
        rows = list_ai_models.discover_usage(
            spec, {"OPENROUTER_API_KEY": "secret"}, timeout_s=1, days=30
        )

    assert urlopen.call_args.args[0].full_url == "https://openrouter.ai/api/v1/key"
    assert len(rows) == 5
    assert rows[0].value == "$12.5000 USD"
    assert rows[-1].metric == "Spending limit remaining"


def test_admin_cost_reports_are_normalized_to_usd():
    specs = list_ai_models.provider_specs({})
    anthropic_response = {
        "data": [{"results": [{"amount": "123.45"}, {"amount": "76.55"}]}]
    }
    openai_response = {
        "data": [
            {
                "results": [
                    {"amount": {"value": 1.25, "currency": "usd"}},
                    {"amount": {"value": 0.75, "currency": "usd"}},
                ]
            }
        ]
    }
    with patch(
        "list_ai_models.urllib.request.urlopen",
        side_effect=[_response(anthropic_response), _response(openai_response)],
    ) as urlopen:
        anthropic_rows = list_ai_models.discover_usage(
            specs[2], {"ANTHROPIC_ADMIN_KEY": "admin-secret"}, timeout_s=1, days=7
        )
        openai_rows = list_ai_models.discover_usage(
            specs[3], {"OPENAI_ADMIN_KEY": "admin-secret"}, timeout_s=1, days=7
        )

    assert anthropic_rows[0].value == "$2.0000 USD"
    assert openai_rows[0].value == "$2.0000 USD"
    assert "/organizations/cost_report?" in urlopen.call_args_list[0].args[0].full_url
    assert "/organization/costs?" in urlopen.call_args_list[1].args[0].full_url


def test_usage_table_contains_status_without_credentials():
    secret = "never-print-admin-secret"
    rows = [
        list_ai_models.UsageRow(
            "OpenAI", "NOT AVAILABLE", "Cost", "-", "requires OPENAI_ADMIN_KEY"
        )
    ]

    table = list_ai_models.render_usage_table(rows)
    assert secret not in table
    assert "NOT AVAILABLE" in table
    assert "OPENAI_ADMIN_KEY" in table
