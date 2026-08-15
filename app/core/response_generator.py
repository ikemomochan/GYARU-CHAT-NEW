from __future__ import annotations

from typing import Sequence

from app.core.llm import LanguageModel, ModelMessage
from app.core.session_state import SessionState, StrategySelection
from app.dialogue_prompts.response_prompt import (
    build_response_input,
    build_response_system_prompt,
)


class ResponseGenerator:
    def __init__(
        self,
        llm: LanguageModel,
        model: str,
        max_output_tokens: int,
    ) -> None:
        self.llm = llm
        self.model = model
        self.max_output_tokens = max_output_tokens

    def generate(
        self,
        *,
        history: Sequence[ModelMessage],
        latest_message: str,
        state: SessionState,
        selection: StrategySelection,
        principles: Sequence[str],
        retrieved_context: Sequence[str],
        safety_identifier: str,
    ) -> str:
        response = self.llm.generate_text(
            model=self.model,
            system_prompt=build_response_system_prompt(selection),
            messages=[
                {
                    "role": "user",
                    "content": build_response_input(
                        history=history,
                        latest_message=latest_message,
                        state=state,
                        selection=selection,
                        principles=principles,
                        retrieved_context=retrieved_context,
                    ),
                }
            ],
            max_output_tokens=min(self.max_output_tokens, 120),
            safety_identifier=safety_identifier,
        ).strip()
        if not response:
            raise RuntimeError("response generator returned an empty response")
        return response
