from __future__ import annotations

from types import SimpleNamespace

from app.providers.openai_provider import OpenAILanguageModel


class FakeResponses:
    def __init__(self) -> None:
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(output_text="応答")


class FakeClient:
    def __init__(self) -> None:
        self.responses = FakeResponses()


def test_text_generation_omits_output_limit_when_none() -> None:
    client = FakeClient()
    model = OpenAILanguageModel(client, "low")

    result = model.generate_text(
        model="gpt-6-luna",
        system_prompt="system",
        messages=[{"role": "user", "content": "message"}],
        max_output_tokens=None,
        safety_identifier="safe-id",
    )

    assert result == "応答"
    assert "max_output_tokens" not in client.responses.calls[0]
