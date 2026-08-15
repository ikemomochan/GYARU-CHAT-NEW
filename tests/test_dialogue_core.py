from __future__ import annotations

import json

from app.core.response_generator import ResponseGenerator
from app.core.session_state import (
    DialogueStrategy,
    SafetyLevel,
    SessionState,
    StrategyRecord,
    StrategySelection,
)
from app.core.strategy_selector import StrategySelector
from app.core.tone_corrector import ToneCorrector
from app.dialogue_prompts.response_prompt import build_response_system_prompt
from app.dialogue_prompts.strategy_prompt import STRATEGY_SYSTEM_PROMPT
from app.dialogue_prompts.tone_prompt import TONE_SYSTEM_PROMPT
from app.gyaru_principles import GYARU_PRINCIPLES


class FakeLanguageModel:
    def __init__(self) -> None:
        self.text_calls = []
        self.structured_calls = []

    def generate_text(self, **kwargs):
        self.text_calls.append(kwargs)
        return "それ言われたんだ。"

    def generate_structured(self, **kwargs):
        self.structured_calls.append(kwargs)
        return StrategySelection(
            strategy=DialogueStrategy.LISTEN,
            perspective_ready=False,
            reason="ユーザーが出来事を話している途中",
            topic="上司との関係",
            known_context="上司と噛み合わない",
            user_need="話を聞いてほしい",
        )


def test_strategy_selector_receives_history_state_and_principles() -> None:
    llm = FakeLanguageModel()
    selector = StrategySelector(llm, "selector-model", 1000)
    state = SessionState(
        strategy_history=[
            StrategyRecord(
                strategy=DialogueStrategy.LISTEN,
                reason="状況が不明だった",
                response="何があったん？",
            )
        ]
    )

    selection = selector.select(
        history=[{"role": "assistant", "content": "何があったん？"}],
        latest_message="上司と話が噛み合わない",
        state=state,
        principles=GYARU_PRINCIPLES,
        safety_identifier="safe-id",
    )

    payload = json.loads(llm.structured_calls[0]["messages"][0]["content"])
    assert selection.strategy is DialogueStrategy.LISTEN
    assert payload["conversation_history"][-1]["content"] == (
        "上司と話が噛み合わない"
    )
    assert payload["session_state"]["strategy_history"][0]["strategy"] == (
        "LISTEN"
    )
    assert payload["gyaru_principles"] == list(GYARU_PRINCIPLES)
    assert llm.structured_calls[0]["output_type"] is StrategySelection
    assert "ANSWERやTASKはありません" in STRATEGY_SYSTEM_PROMPT
    assert "LISTENが直近5回連続" in STRATEGY_SYSTEM_PROMPT
    assert "ADVICEかSYMPATHY" in STRATEGY_SYSTEM_PROMPT


def test_response_generator_only_receives_dialogue_inputs() -> None:
    llm = FakeLanguageModel()
    generator = ResponseGenerator(llm, "response-model", 1000)
    state = SessionState(
        topic="上司との関係",
        known_context="上司と噛み合わない",
        user_need="話を聞いてほしい",
    )
    selection = StrategySelection(
        strategy=DialogueStrategy.LISTEN,
        perspective_ready=False,
        reason="まだ話している途中",
    )

    result = generator.generate(
        history=[],
        latest_message="上司と噛み合わない",
        state=state,
        selection=selection,
        principles=GYARU_PRINCIPLES,
        retrieved_context=[],
        safety_identifier="safe-id",
    )

    payload = json.loads(llm.text_calls[0]["messages"][0]["content"])
    assert result == "それ言われたんだ。"
    assert set(payload) == {
        "conversation_history",
        "session_state",
        "selected_strategy",
        "gyaru_principles",
        "retrieved_context",
    }
    assert payload["selected_strategy"]["strategy"] == "LISTEN"
    assert "reason" not in payload["selected_strategy"]
    assert "strategy_history" not in payload["session_state"]
    prompt = llm.text_calls[0]["system_prompt"]
    assert prompt == build_response_system_prompt(selection)
    assert "今回はLISTEN" in prompt
    assert "友達の話にDM" in prompt
    assert "質問は会話を続けるためのおまけ" in prompt
    assert "今回はADVICE" not in prompt
    assert "人間として同じ経験をしたふり" in prompt
    assert llm.text_calls[0]["max_output_tokens"] == 120


def test_response_prompt_is_selected_per_strategy() -> None:
    advice = StrategySelection(
        strategy=DialogueStrategy.ADVICE,
        perspective_ready=True,
        reason="状況を理解できた",
    )
    sympathy = StrategySelection(
        strategy=DialogueStrategy.SYMPATHY,
        perspective_ready=True,
        reason="寄り添いが必要",
    )

    advice_prompt = build_response_system_prompt(advice)
    sympathy_prompt = build_response_system_prompt(sympathy)

    assert "今回はADVICE" in advice_prompt
    assert "今回はLISTEN" not in advice_prompt
    assert "今回はSYMPATHY" in sympathy_prompt
    assert "今回はLISTEN" not in sympathy_prompt
    assert "任意に参考にしてよい" in advice_prompt
    assert "任意に参考にしてよい" in sympathy_prompt


def test_tone_corrector_uses_few_shots_without_selecting_strategy() -> None:
    llm = FakeLanguageModel()
    corrector = ToneCorrector(llm, "tone-model", 1000)

    result = corrector.correct(
        history=[{"role": "assistant", "content": "何があったん？"}],
        latest_message="仕事が多い",
        draft="それは大変そう。",
        strategy=DialogueStrategy.SYMPATHY,
        safety_level=SafetyLevel.NORMAL,
        examples=[{"input": "そうですね", "output": "あーね"}],
        safety_identifier="safe-id",
    )

    payload = json.loads(llm.text_calls[0]["messages"][0]["content"])
    assert result == "それ言われたんだ。"
    assert payload["draft"] == "それは大変そう。"
    assert payload["strategy"] == "SYMPATHY"
    assert payload["few_shot_examples"] == [
        {"standard": "そうですね", "gyaru": "あーね"}
    ]
    assert llm.text_calls[0]["system_prompt"] == TONE_SYSTEM_PROMPT
    assert "話し方だけ" in TONE_SYSTEM_PROMPT
    assert "戦略を変更しない" in TONE_SYSTEM_PROMPT
    assert "質問の対象と抽象度を変えない" in TONE_SYSTEM_PROMPT


def test_selector_forces_transition_after_five_consecutive_listens() -> None:
    llm = FakeLanguageModel()
    selector = StrategySelector(llm, "selector-model", 1000)
    state = SessionState(
        strategy_history=[
            StrategyRecord(
                strategy=DialogueStrategy.LISTEN,
                reason="状況を聞いている",
                response=f"質問{index}",
            )
            for index in range(5)
        ]
    )

    selection = selector.select(
        history=[],
        latest_message="まだ大変",
        state=state,
        principles=GYARU_PRINCIPLES,
        safety_identifier="safe-id",
    )

    assert len(llm.structured_calls) == 2
    assert selection.strategy is DialogueStrategy.SYMPATHY
    assert selection.perspective_ready is True
    assert "連続LISTEN上限" in selection.reason


class UrgentLanguageModel(FakeLanguageModel):
    def generate_structured(self, **kwargs):
        self.structured_calls.append(kwargs)
        return StrategySelection(
            strategy=DialogueStrategy.LISTEN,
            perspective_ready=False,
            reason="生命・身体の危険がある",
            safety_level=SafetyLevel.URGENT,
        )


def test_urgent_safety_level_forces_advice() -> None:
    llm = UrgentLanguageModel()
    selector = StrategySelector(llm, "selector-model", 1000)

    selection = selector.select(
        history=[],
        latest_message="今すぐ危険がある",
        state=SessionState(),
        principles=GYARU_PRINCIPLES,
        safety_identifier="safe-id",
    )

    assert selection.strategy is DialogueStrategy.ADVICE
    assert selection.perspective_ready is True
    assert selection.safety_level is SafetyLevel.URGENT
