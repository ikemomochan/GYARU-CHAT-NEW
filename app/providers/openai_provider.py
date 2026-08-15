from __future__ import annotations

from typing import Sequence, TypeVar

from openai import OpenAI
from pydantic import BaseModel

from app.core.llm import ModelMessage


StructuredOutput = TypeVar("StructuredOutput", bound=BaseModel)


class OpenAILanguageModel:
    def __init__(self, client: OpenAI, reasoning_effort: str) -> None:
        self.client = client
        self.reasoning_effort = reasoning_effort

    def generate_text(
        self,
        *,
        model: str,
        system_prompt: str,
        messages: Sequence[ModelMessage],
        max_output_tokens: int,
        safety_identifier: str,
    ) -> str:
        response = self.client.responses.create(
            model=model,
            instructions=system_prompt,
            input=list(messages),
            reasoning={"effort": self.reasoning_effort},
            max_output_tokens=max_output_tokens,
            safety_identifier=safety_identifier,
        )
        text = response.output_text.strip()
        if not text:
            raise RuntimeError("OpenAI returned an empty response")
        return text

    def generate_structured(
        self,
        *,
        model: str,
        system_prompt: str,
        messages: Sequence[ModelMessage],
        output_type: type[StructuredOutput],
        max_output_tokens: int,
        safety_identifier: str,
    ) -> StructuredOutput:
        response = self.client.responses.parse(
            model=model,
            instructions=system_prompt,
            input=list(messages),
            text_format=output_type,
            reasoning={"effort": self.reasoning_effort},
            max_output_tokens=max_output_tokens,
            safety_identifier=safety_identifier,
        )
        if response.output_parsed is None:
            raise RuntimeError("OpenAI returned no structured output")
        return response.output_parsed
