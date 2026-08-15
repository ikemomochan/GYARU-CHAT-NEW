from __future__ import annotations

from typing import Any, Sequence

from app.core.llm import LanguageModel, ModelMessage
from app.core.session_state import DialogueStrategy, SafetyLevel
from app.dialogue_prompts.tone_prompt import TONE_SYSTEM_PROMPT, build_tone_input


class ToneCorrector:
    """Edits surface style without selecting or changing dialogue strategy."""

    def __init__(
        self,
        llm: LanguageModel,
        model: str,
        max_output_tokens: int,
    ) -> None:
        self.llm = llm
        self.model = model
        self.max_output_tokens = max_output_tokens

    def correct(
        self,
        *,
        history: Sequence[ModelMessage],
        latest_message: str,
        draft: str,
        strategy: DialogueStrategy,
        safety_level: SafetyLevel,
        examples: Sequence[dict[str, Any]],
        safety_identifier: str,
    ) -> str:
        response = self.llm.generate_text(
            model=self.model,
            system_prompt=TONE_SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": build_tone_input(
                        history=history,
                        latest_message=latest_message,
                        draft=draft,
                        strategy=strategy,
                        safety_level=safety_level,
                        examples=examples,
                    ),
                }
            ],
            # Reasoning models count internal reasoning toward this limit. Keep
            # enough headroom even though the visible reply itself is short.
            max_output_tokens=min(self.max_output_tokens, 600),
            safety_identifier=safety_identifier,
        ).strip()
        if not response:
            raise RuntimeError("tone corrector returned an empty response")
        return response
