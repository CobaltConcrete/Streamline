from unittest.mock import patch

import pytest

from codirector.adapters.base import ReasoningPrompt
from codirector.adapters.reasoning.http import (
    AIAPIReasoningProvider,
    MissingAIProviderError,
    resolve_ai_provider,
)
from codirector.config.models import ReasoningConfig


def test_auto_provider_uses_documented_key_priority():
    settings = resolve_ai_provider(
        {
            "AI_PROVIDER": "auto",
            "OPENCODE_API_KEY": "opencode-secret",
            "OPENROUTER_API_KEY": "openrouter-secret",
            "ANTHROPIC_API_KEY": "anthropic-secret",
            "OPENAI_API_KEY": "openai-secret",
        }
    )
    assert settings.name == "opencode"
    assert settings.endpoint == "https://opencode.ai/zen/v1/responses"


def test_auto_provider_falls_through_and_accepts_claude_alias():
    settings = resolve_ai_provider({"AI_PROVIDER": "auto", "CLAUDE_API_KEY": "claude-secret"})
    assert settings.name == "anthropic"
    assert settings.model == "claude-sonnet-5"


def test_explicit_provider_requires_its_own_key():
    with pytest.raises(MissingAIProviderError, match="OPENAI_API_KEY"):
        resolve_ai_provider({"OPENROUTER_API_KEY": "other-secret"}, requested="openai")


def test_openrouter_request_authenticates_without_putting_key_in_prompt():
    settings = resolve_ai_provider(
        {"OPENROUTER_API_KEY": "router-secret"}, requested="openrouter"
    )
    provider = AIAPIReasoningProvider(settings, env={"OPENROUTER_APP_NAME": "Test App"})
    prompt = ReasoningPrompt(
        session_summary="creator is answering setup questions",
        cluster_context=[
            {
                "cluster_id": "c1",
                "kind": "question",
                "unique_user_count": 4,
                "representative_text": "what keyboard do you use?",
            }
        ],
        persona={"name": "conversational"},
    )

    headers, payload = provider._request(prompt)

    assert headers["authorization"] == "Bearer router-secret"
    assert headers["X-OpenRouter-Title"] == "Test App"
    assert "router-secret" not in str(payload)
    assert payload["response_format"]["type"] == "json_schema"
    schema = payload["response_format"]["json_schema"]["schema"]
    proposal_schema = schema["properties"]["proposals"]["items"]
    assert set(schema["required"]) == set(schema["properties"])
    assert set(proposal_schema["required"]) == set(proposal_schema["properties"])


def test_system_prompt_mode_embeds_schema_and_omits_native_attribute():
    settings = resolve_ai_provider({"OPENCODE_API_KEY": "key"}, requested="opencode")
    provider = AIAPIReasoningProvider(settings, structured_output_mode="system_prompt")
    prompt = ReasoningPrompt(session_summary="", cluster_context=[], persona={})

    _headers, payload = provider._request(prompt)

    assert "text" not in payload
    assert "exact JSON Schema" in payload["input"][0]["content"]
    assert '"proposals"' in payload["input"][0]["content"]


def test_reasoning_config_defaults_to_attribute_and_deepseek_with_fallbacks():
    config = ReasoningConfig()

    assert config.structured_output_mode == "attribute"
    assert config.model == "deepseek-v4-flash-free"
    assert config.fallback_models[0] == "longcat-2.0-free"


def test_response_parsing_supports_each_provider_shape():
    cases = [
        ({"OPENCODE_API_KEY": "key"}, "opencode", {"output_text": '{"proposals":[]}'}),
        (
            {"OPENROUTER_API_KEY": "key"},
            "openrouter",
            {"choices": [{"message": {"content": '{"proposals":[]}'}}]},
        ),
        (
            {"ANTHROPIC_API_KEY": "key"},
            "anthropic",
            {"content": [{"type": "text", "text": '{"proposals":[]}'}]},
        ),
    ]
    for env, requested, response in cases:
        settings = resolve_ai_provider(env, requested=requested)
        provider = AIAPIReasoningProvider(settings, env=env)
        assert provider._response_text(response) == '{"proposals":[]}'


async def test_schema_failure_is_retried_up_to_third_attempt():
    settings = resolve_ai_provider({"OPENCODE_API_KEY": "key"}, requested="opencode")
    provider = AIAPIReasoningProvider(settings, max_attempts=3)
    prompt = ReasoningPrompt(
        session_summary="",
        cluster_context=[
            {
                "cluster_id": "c1",
                "kind": "question",
                "unique_user_count": 4,
                "representative_text": "what microphone do you use today",
            }
        ],
        persona={},
    )
    payloads = iter(
        [
            {"output_text": "not json"},
            {"output_text": "[]"},
            {
                "output_text": (
                    '{"proposals":[{"cluster_id":"c1","decision_type":"SURFACE",'
                    '"action_id":null,"parameters":{},"representative_text":"changed",'
                    '"response_angle":"answer it","relevance":0.9,'
                    '"rationale":"timely question"}]}'
                )
            },
        ]
    )
    calls = 0

    class Response:
        def raise_for_status(self):
            return None

        async def json(self):
            return next(payloads)

    class RequestContext:
        async def __aenter__(self):
            return Response()

        async def __aexit__(self, *_args):
            return None

    class Session:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        def post(self, *_args, **_kwargs):
            nonlocal calls
            calls += 1
            return RequestContext()

    with patch("codirector.adapters.reasoning.http.aiohttp.ClientSession", Session):
        result = await provider.propose(prompt)

    assert calls == 3
    assert len(result.proposals) == 1
    assert result.proposals[0].representative_text == "what microphone do you use today"


async def test_exhausted_primary_model_moves_to_configured_fallback():
    settings = resolve_ai_provider({"OPENCODE_API_KEY": "key"}, requested="opencode")
    provider = AIAPIReasoningProvider(
        settings,
        max_attempts=1,
        fallback_models=["ling-3.0-tiny-free"],
    )
    prompt = ReasoningPrompt(session_summary="", cluster_context=[], persona={})
    responses = iter([{"output_text": "not json"}, {"output_text": '{"proposals":[]}'}])
    models = []

    class Response:
        def raise_for_status(self):
            return None

        async def json(self):
            return next(responses)

    class RequestContext:
        async def __aenter__(self):
            return Response()

        async def __aexit__(self, *_args):
            return None

    class Session:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        def post(self, *_args, **kwargs):
            models.append(kwargs["json"]["model"])
            return RequestContext()

    with patch("codirector.adapters.reasoning.http.aiohttp.ClientSession", Session):
        result = await provider.propose(prompt)

    assert result.proposals == []
    assert models == [settings.model, "ling-3.0-tiny-free"]
