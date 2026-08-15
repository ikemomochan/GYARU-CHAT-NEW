from __future__ import annotations

from typing import Sequence

from app.core.llm import LanguageModel, ModelMessage
from app.core.session_state import (
    DialogueStrategy,
    SafetyLevel,
    SessionState,
    StrategySelection,
)
from app.dialogue_prompts.strategy_prompt import (
    STRATEGY_SYSTEM_PROMPT,
    build_strategy_input,
)


class StrategySelector:
    MAX_CONSECUTIVE_LISTEN = 5

    def __init__(
        self,
        llm: LanguageModel,
        model: str,
        max_output_tokens: int,
    ) -> None:
        self.llm = llm
        self.model = model
        self.max_output_tokens = max_output_tokens

    def select(
        self,
        *,
        history: Sequence[ModelMessage],
        latest_message: str,
        state: SessionState,
        principles: Sequence[str],
        safety_identifier: str,
    ) -> StrategySelection:
        selection = self._select(
            history=history,
            latest_message=latest_message,
            state=state,
            principles=principles,
            safety_identifier=safety_identifier,
        )
        if selection.safety_level is SafetyLevel.URGENT:
            return selection.model_copy(
                update={
                    "strategy": DialogueStrategy.ADVICE,
                    "perspective_ready": True,
                }
            )

        if (
            selection.strategy is DialogueStrategy.LISTEN
            and self._consecutive_listen_count(state)
            >= self.MAX_CONSECUTIVE_LISTEN
        ):
            corrected = self._select(
                history=history,
                latest_message=latest_message,
                state=state,
                principles=principles,
                safety_identifier=safety_identifier,
                correction=(
                    "LISTENがすでに5回連続しています。今回は必ずADVICEまたは"
                    "SYMPATHYを選んでください。"
                ),
            )
            if corrected.strategy is DialogueStrategy.LISTEN:
                return corrected.model_copy(
                    update={
                        "strategy": DialogueStrategy.SYMPATHY,
                        "perspective_ready": True,
                        "reason": (
                            f"{corrected.reason} "
                            "連続LISTEN上限のためSYMPATHYへ移行"
                        ),
                    }
                )
            return corrected
        return selection

    def _select(
        self,
        *,
        history: Sequence[ModelMessage],
        latest_message: str,
        state: SessionState,
        principles: Sequence[str],
        safety_identifier: str,
        correction: str = "",
    ) -> StrategySelection:
        content = build_strategy_input(
            history=history,
            latest_message=latest_message,
            state=state,
            principles=principles,
        )
        if correction:
            content = f"{content}\n\n<correction>{correction}</correction>"
        return self.llm.generate_structured(
            model=self.model,
            system_prompt=STRATEGY_SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": content,
                }
            ],
            output_type=StrategySelection,
            max_output_tokens=min(self.max_output_tokens, 800),
            safety_identifier=safety_identifier,
        )

    @staticmethod
    def _consecutive_listen_count(state: SessionState) -> int:
        count = 0
        for record in reversed(state.strategy_history):
            if record.strategy is not DialogueStrategy.LISTEN:
                break
            count += 1
        return count
