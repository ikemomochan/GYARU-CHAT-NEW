from __future__ import annotations

from typing import Any

from anthropic import Anthropic
from openai import OpenAI

from app.config import Settings


class BaseModelService:
    """Generate the content draft with the configured model provider."""

    def __init__(
        self,
        settings: Settings,
        openai_client: OpenAI,
        anthropic_client: Anthropic | None = None,
    ) -> None:
        self.settings = settings
        self.openai_client = openai_client
        self._anthropic_client = anthropic_client

    def generate(
        self,
        system_prompt: str,
        messages: list[dict[str, str]],
        safety_identifier: str,
    ) -> str:
        if self.settings.base_model_provider == "openai":
            return self._generate_with_openai(
                system_prompt, messages, safety_identifier
            )
        if self.settings.base_model_provider == "anthropic":
            return self._generate_with_anthropic(system_prompt, messages)
        raise ValueError(
            f"Unsupported base model provider: {self.settings.base_model_provider}"
        )

    def _generate_with_openai(
        self,
        system_prompt: str,
        messages: list[dict[str, str]],
        safety_identifier: str,
    ) -> str:
        response = self.openai_client.responses.create(
            model=self.settings.base_model,
            instructions=system_prompt,
            input=messages,
            reasoning={"effort": self.settings.reasoning_effort},
            max_output_tokens=self.settings.max_output_tokens,
            safety_identifier=safety_identifier,
        )
        return self._require_text(response.output_text, "OpenAI")

    def _generate_with_anthropic(
        self,
        system_prompt: str,
        messages: list[dict[str, str]],
    ) -> str:
        if self._anthropic_client is None:
            self._anthropic_client = Anthropic(
                api_key=self.settings.anthropic_api_key
            )
        response = self._anthropic_client.messages.create(
            model=self.settings.base_model,
            max_tokens=self.settings.max_output_tokens,
            system=system_prompt,
            messages=messages,
        )
        output_text = "".join(
            str(getattr(block, "text", ""))
            for block in response.content
            if getattr(block, "type", None) == "text"
        )
        return self._require_text(output_text, "Anthropic")

    @staticmethod
    def _require_text(value: Any, provider: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise RuntimeError(f"{provider} returned an empty response")
        return text
