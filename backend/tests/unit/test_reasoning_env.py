import pytest

from codirector.adapters.base import ReasoningPrompt
from codirector.adapters.reasoning.http import (
    AIAPIReasoningProvider,
    MissingAIProviderError,
    resolve_ai_provider,
)


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
