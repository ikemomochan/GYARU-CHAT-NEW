from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from app.chat import ChatService
from app.config import get_settings
from app.core.session_state import (
    DialogueStrategy,
    InMemorySessionStore,
    StrategySelection,
)
from app.schemas import ChatMessage, ChatRequest


class FakeStrategySelector:
    def __init__(self, strategy: DialogueStrategy = DialogueStrategy.LISTEN) -> None:
        self.calls = []
        self.strategy = strategy

    def select(self, **kwargs):
        self.calls.append(kwargs)
        return StrategySelection(
            strategy=self.strategy,
            perspective_ready=self.strategy is not DialogueStrategy.LISTEN,
            reason="テスト用の戦略選択",
            topic="研究",
            known_context="研究が行き詰まっている",
            user_need="話を続けたい",
        )


class FakeResponseGenerator:
    def __init__(self) -> None:
        self.calls = []

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        return "そうなんだ。何があったの？"


class FakeToneCorrector:
    def __init__(self) -> None:
        self.calls = []

    def correct(self, **kwargs):
        self.calls.append(kwargs)
        return "そーなんだ。何あったん？"


class FakePrincipleRetriever:
    def __init__(self) -> None:
        self.queries = []

    def retrieve_context(self, query: str):
        self.queries.append(query)
        return ["自分の意思を大切にする"]


class FakeFewShotRetriever:
    def __init__(self) -> None:
        self.calls = []

    def retrieve_examples(self, query: str, top_k: int):
        self.calls.append((query, top_k))
        return [{"input": "そうなんだ", "output": "そーなんだ"}]


def build_service(strategy: DialogueStrategy = DialogueStrategy.LISTEN):
    selector = FakeStrategySelector(strategy)
    generator = FakeResponseGenerator()
    tone_corrector = FakeToneCorrector()
    principle_retriever = FakePrincipleRetriever()
    few_shot_retriever = FakeFewShotRetriever()
    store = InMemorySessionStore()
    service = ChatService(
        settings=replace(get_settings(), openai_api_key="test-key"),
        session_store=store,
        strategy_selector=selector,
        response_generator=generator,
        tone_corrector=tone_corrector,
        principle_retriever=principle_retriever,
        few_shot_retriever=few_shot_retriever,
    )
    return (
        service,
        selector,
        generator,
        tone_corrector,
        principle_retriever,
        few_shot_retriever,
    )


def test_chat_generates_then_corrects_tone_and_commits_final_reply() -> None:
    service, selector, generator, corrector, principles, few_shots = build_service()
    request = ChatRequest(
        message="研究が行き詰まってる",
        user_id="user-1",
        conversation_id="conversation-1",
        history=[ChatMessage(role="assistant", content="今日はどしたん？")],
    )

    result = asyncio.run(service.reply(request))

    assert result.reply == "そーなんだ。何あったん？"
    assert result.recalled_memories == 0
    assert result.retrieved_examples == 1
    assert result.retrieved_principles == 0
    assert "reason" not in result.model_dump()
    assert selector.calls[0]["history"] == [
        {"role": "assistant", "content": "今日はどしたん？"}
    ]
    assert generator.calls[0]["selection"].strategy is DialogueStrategy.LISTEN
    assert generator.calls[0]["retrieved_context"] == []
    assert corrector.calls[0]["draft"] == "そうなんだ。何があったの？"
    assert corrector.calls[0]["strategy"] is DialogueStrategy.LISTEN
    assert corrector.calls[0]["examples"] == [
        {"input": "そうなんだ", "output": "そーなんだ"}
    ]
    assert principles.queries == []
    assert few_shots.calls[0][1] == service.settings.style_top_k

    state = service.get_session_state("user-1", "conversation-1")
    assert state.topic == "研究"
    assert state.known_context == "研究が行き詰まっている"
    assert state.strategy_history[0].response == result.reply


def test_next_strategy_selection_receives_previous_strategy_history() -> None:
    service, selector, *_ = build_service()
    first_request = ChatRequest(
        message="研究が行き詰まってる",
        user_id="user-1",
        conversation_id="conversation-1",
    )
    asyncio.run(service.reply(first_request))

    asyncio.run(
        service.reply(
            ChatRequest(
                message="結果が思った通りにならない",
                user_id="user-1",
                conversation_id="conversation-1",
                history=[
                    ChatMessage(role="user", content=first_request.message),
                    ChatMessage(role="assistant", content="そーなんだ。何あったん？"),
                ],
            )
        )
    )

    second_state = selector.calls[1]["state"]
    assert second_state.strategy_history[0].strategy is DialogueStrategy.LISTEN
    assert selector.calls[1]["history"][0]["content"] == first_request.message


@pytest.mark.parametrize(
    "strategy",
    [DialogueStrategy.ADVICE, DialogueStrategy.SYMPATHY],
)
def test_advice_and_sympathy_use_the_same_principle_rag(strategy) -> None:
    service, _, generator, _, principles, _ = build_service(strategy)

    result = asyncio.run(
        service.reply(
            ChatRequest(
                message="仕事を抱えすぎてる",
                user_id="user-1",
                conversation_id="conversation-1",
            )
        )
    )

    assert len(principles.queries) == 1
    assert "仕事を抱えすぎてる" in principles.queries[0]
    assert generator.calls[0]["retrieved_context"] == [
        "自分の意思を大切にする"
    ]
    assert result.retrieved_examples == 1
    assert result.retrieved_principles == 1


def test_reset_session_only_clears_requested_conversation() -> None:
    service, *_ = build_service()
    for conversation_id in ("conversation-1", "conversation-2"):
        asyncio.run(
            service.reply(
                ChatRequest(
                    message="話を聞いて",
                    user_id="user-1",
                    conversation_id=conversation_id,
                )
            )
        )

    service.reset_session("user-1", "conversation-1")

    assert service.get_session_state("user-1", "conversation-1").topic == ""
    assert service.get_session_state("user-1", "conversation-2").topic == "研究"
