from pathlib import Path

import pytest
from pydantic import ValidationError

from codirector.config.loader import get_twitch_token, load_app_config
from codirector.config.models import PersonaConfig

CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "app.yaml"


def _persona(**weight_overrides):
    weights = {
        "relevance": 0.30,
        "breadth": 0.25,
        "novelty": 0.15,
        "urgency": 0.15,
        "support_tier": 0.15,
    }
    weights.update(weight_overrides)
    return {
        "name": "conversational",
        "weights": weights,
        "thresholds": {"surface_min_score": 0.55, "max_queue_items": 3, "max_prompts_per_minute": 2},
        "banned_topics": [],
    }


def test_weights_must_sum_to_one():
    with pytest.raises(ValidationError):
        PersonaConfig.model_validate(_persona(relevance=0.9))


def test_weights_summing_to_one_loads():
    persona = PersonaConfig.model_validate(_persona())
    assert persona.name == "conversational"


def test_environment_overrides_channel_provider_and_timeout(monkeypatch):
    monkeypatch.setenv("TWITCH_CHANNEL", "#my_stream")
    monkeypatch.setenv("AI_PROVIDER", "openai")
    monkeypatch.setenv("AI_REQUEST_TIMEOUT_S", "4.5")

    config = load_app_config(CONFIG_PATH)

    assert config.twitch.channel == "my_stream"
    assert config.reasoning.provider == "openai"
    assert config.reasoning.timeout_s == 4.5


def test_twitch_access_token_comes_from_environment(monkeypatch):
    monkeypatch.setenv("TWITCH_USER_ACCESS_TOKEN", "oauth:test-token")
    assert get_twitch_token() == "test-token"
