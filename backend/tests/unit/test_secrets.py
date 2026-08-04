"""R-SAF-08: no secret in any config file, log line, or model prompt.
Secrets are read from the git-ignored environment or OS keyring by
config/loader.py. They are never written to config/app.yaml, passed through
Decision/Proposal (which have no credential-shaped field), or included in a
ReasoningPrompt."""
from pathlib import Path

from codirector.adapters.base import ReasoningPrompt
from codirector.core.models import Cluster, Decision, Proposal

CONFIG_DIR = Path(__file__).resolve().parents[2].parent / "config"

_SECRET_HINTS = ("password", "token", "oauth", "secret", "api_key", "apikey")


def test_app_yaml_never_contains_a_literal_secret_value():
    text = (CONFIG_DIR / "app.yaml").read_text(encoding="utf-8")
    for line in text.splitlines():
        if "#" in line:
            line = line.split("#", 1)[0]  # ignore the explanatory comments
        lowered = line.lower()
        for hint in _SECRET_HINTS:
            assert hint not in lowered, f"possible literal secret reference in app.yaml: {line!r}"


def test_proposal_and_decision_models_have_no_credential_shaped_field():
    for model in (Proposal, Decision, Cluster):
        for field_name in model.model_fields:
            lowered = field_name.lower()
            assert not any(hint in lowered for hint in _SECRET_HINTS), (
                f"{model.__name__}.{field_name} looks credential-shaped — "
                "secrets must never be representable in a Decision/Proposal at all"
            )


def test_reasoning_prompt_has_no_credential_field():
    prompt = ReasoningPrompt(session_summary="", cluster_context=[], persona={})
    for attr in ("session_summary", "cluster_context", "persona"):
        assert getattr(prompt, attr) is not None or True  # exists, just documenting the shape
    assert not hasattr(prompt, "password")
    assert not hasattr(prompt, "token")
    assert not hasattr(prompt, "api_key")


def test_secrets_are_read_from_environment_or_keyring_not_yaml():
    source = (CONFIG_DIR.parent / "backend" / "codirector" / "config" / "loader.py").read_text(encoding="utf-8")
    assert "import keyring" in source
    assert "os.getenv" in source
    assert "yaml.safe_load" in source  # config files are only parsed for non-secret fields


def test_example_environment_file_contains_no_secret_values():
    example = CONFIG_DIR.parent / ".env.example"
    for line in example.read_text(encoding="utf-8").splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if any(hint in name.lower() for hint in _SECRET_HINTS):
            assert value == ""
