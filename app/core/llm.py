from __future__ import annotations

from typing import Protocol, Sequence, TypeVar

from pydantic import BaseModel


StructuredOutput = TypeVar("StructuredOutput", bound=BaseModel)
ModelMessage = dict[str, str]


class LanguageModel(Protocol):
    """Minimal interface implemented by OpenAI and future local-model adapters."""

    def generate_text(
        self,
        *,
        model: str,
        system_prompt: str,
        messages: Sequence[ModelMessage],
        max_output_tokens: int,
        safety_identifier: str,
    ) -> str: ...

    def generate_structured(
        self,
        *,
        model: str,
        system_prompt: str,
        messages: Sequence[ModelMessage],
        output_type: type[StructuredOutput],
        max_output_tokens: int,
        safety_identifier: str,
    ) -> StructuredOutput: ...
