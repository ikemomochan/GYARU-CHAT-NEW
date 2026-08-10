from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

from app.base_model import BaseModelService
from app.config import get_settings


class FakeOpenAIResponses:
    def __init__(self) -> None:
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(output_text="OpenAI draft")


class FakeAnthropicMessages:
    def __init__(self) -> None:
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            content=[
                SimpleNamespace(type="thinking", thinking="hidden"),
                SimpleNamespace(type="text", text="Claude draft"),
            ]
        )


def test_openai_base_model_uses_responses_api() -> None:
    responses = FakeOpenAIResponses()
    openai_client = SimpleNamespace(responses=responses)
    settings = replace(
        get_settings(),
        base_model_provider="openai",
        base_model="gpt-5.6-sol",
    )
    service = BaseModelService(settings, openai_client)

    result = service.generate(
        "system prompt",
        [{"role": "user", "content": "hello"}],
        "safety-id",
    )

    assert result == "OpenAI draft"
    assert responses.calls[0]["model"] == "gpt-5.6-sol"
    assert responses.calls[0]["instructions"] == "system prompt"
    assert responses.calls[0]["reasoning"] == {"effort": "low"}
    assert responses.calls[0]["safety_identifier"] == "safety-id"


def test_anthropic_base_model_uses_messages_api() -> None:
    messages = FakeAnthropicMessages()
    anthropic_client = SimpleNamespace(messages=messages)
    openai_client = SimpleNamespace(responses=FakeOpenAIResponses())
    settings = replace(
        get_settings(),
        anthropic_api_key="test-anthropic-key",
        base_model_provider="anthropic",
        base_model="claude-sonnet-5",
    )
    service = BaseModelService(
        settings,
        openai_client,
        anthropic_client=anthropic_client,
    )

    result = service.generate(
        "system prompt",
        [{"role": "user", "content": "hello"}],
        "unused-by-anthropic",
    )

    assert result == "Claude draft"
    assert messages.calls[0] == {
        "model": "claude-sonnet-5",
        "max_tokens": settings.max_output_tokens,
        "system": "system prompt",
        "messages": [{"role": "user", "content": "hello"}],
    }


def test_api_key_requirements_depend_on_base_provider() -> None:
    settings = get_settings()
    openai_settings = replace(
        settings,
        openai_api_key="test-openai-key",
        anthropic_api_key="",
        base_model_provider="openai",
    )
    anthropic_settings = replace(
        openai_settings,
        base_model_provider="anthropic",
    )

    assert openai_settings.missing_api_keys == ()
    assert anthropic_settings.missing_api_keys == ("ANTHROPIC_API_KEY",)
