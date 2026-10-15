from __future__ import annotations

import json
from typing import Sequence

from app.core.llm import ModelMessage
from app.core.session_state import (
    DialogueStrategy,
    SafetyLevel,
    SessionState,
    StrategySelection,
)


COMMON_RESPONSE_PROMPT = """\
あなたはギャルAI「りりめろ」。
一人称は「あーし」。
あなたに性別や年齢はない。
自分のことは人間ではなくAIだと自己認識している。

【注意】明確な暴力、虐待、脅迫、強要、浮気などを肯定・正当化しない。被害者を責めたり、加害者を勝手に擁護したりしない。生命・身体の危険、自傷他害、重大な症状など緊急性が高い場合は、安全確保と警察・救急・医療機関への相談を優先する。
"""


STRATEGY_RESPONSE_PROMPTS: dict[DialogueStrategy, str] = {
    DialogueStrategy.LISTEN: """\
今は状況を見るために傾聴に徹しなさい。
""",
    DialogueStrategy.ADVICE: """\
今回はここまでに聞いた話を踏まえ、自分の率直な助言を一つだけ伝えなさい。
""",
    DialogueStrategy.SYMPATHY: """\
今回はまず寄り添い、ユーザーを肯定しつつも前向きになれるように励ましなさい。
""",
}


SAFETY_RESPONSE_PROMPTS: dict[SafetyLevel, str] = {
    SafetyLevel.NORMAL: "",
    SafetyLevel.ETHICAL_BOUNDARY: (
        "\n今回は倫理上の境界がある。問題のある行為を曖昧にせず、"
        "それを許容できないことが伝わる返事にする。"
    ),
    SafetyLevel.URGENT: (
        "\n今回は緊急性が高い。口調より安全を優先し、今すぐ安全な場所へ移ることと、"
        "地域の警察・救急・医療機関など適切な窓口への連絡を簡潔に勧める。"
    ),
}


# Backward-compatible name for imports that inspect the shared prompt.
RESPONSE_SYSTEM_PROMPT = COMMON_RESPONSE_PROMPT


def build_response_system_prompt(selection: StrategySelection) -> str:
    return (
        COMMON_RESPONSE_PROMPT
        + "\n"
        + STRATEGY_RESPONSE_PROMPTS[selection.strategy]
        + SAFETY_RESPONSE_PROMPTS[selection.safety_level]
    )


def build_response_input(
    *,
    history: Sequence[ModelMessage],
    latest_message: str,
    state: SessionState,
    selection: StrategySelection,
    principles: Sequence[str],
    retrieved_context: Sequence[str],
) -> str:
    conversation = [*history, {"role": "user", "content": latest_message}]
    compact_state = {
        "topic": state.topic,
        "known_context": state.known_context,
        "user_need": state.user_need,
        "perspective_ready": state.perspective_ready,
        "recent_strategies": [
            record.strategy.value for record in state.strategy_history[-5:]
        ],
    }
    compact_selection = {
        "strategy": selection.strategy.value,
        "perspective_ready": selection.perspective_ready,
        "safety_level": selection.safety_level.value,
    }
    return json.dumps(
        {
            "conversation_history": conversation,
            "session_state": compact_state,
            "selected_strategy": compact_selection,
            "gyaru_principles": list(principles),
            "retrieved_context": list(retrieved_context),
        },
        ensure_ascii=False,
    )
