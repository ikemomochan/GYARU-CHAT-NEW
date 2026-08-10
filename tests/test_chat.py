from __future__ import annotations

import asyncio
from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.chat import ChatService
from app.config import get_settings
from app.prompts import (
    SIMPLE_CHAT_SYSTEM_PROMPT,
    build_chat_system_prompt,
)
from app.schemas import ChatRequest


class FakeResponses:
    def __init__(self) -> None:
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(output_text="覚えてるよ〜！猫が好きだったよね🐈")


class FakeBaseModel:
    def __init__(self) -> None:
        self.calls = []

    def generate(self, system_prompt, messages, safety_identifier):
        self.calls.append((system_prompt, messages, safety_identifier))
        return "覚えています。猫が好きでしたね。"


class FakeMemory:
    def __init__(self) -> None:
        self.saved = None
        self.closed = False
        self.was_reset = False

    def search(self, query: str, user_id: str):
        return ["ユーザーは猫が好き"]

    def reconcile_conversation(self, *args):
        self.saved = args
        return 1

    def close(self):
        self.closed = True

    def reset(self):
        self.was_reset = True


class FakeRetriever:
    def retrieve(self, query: str, top_k: int):
        return [
            {
                "id": f"example-{index}",
                "input": f"標準表現 {index}",
                "output": f"ギャル表現 {index}",
                "score": 1.0 - index / 10,
            }
            for index in range(1, 6)
        ]


class FakeConversation:
    def __init__(self) -> None:
        self.saved = None
        self.was_reset = False

    def get_summary(self, user_id: str, conversation_id: str):
        return "猫について話している"

    def record_and_maybe_summarize(self, *args):
        self.saved = args
        return False

    def reset(self):
        self.was_reset = True


class DisabledAuxiliaryService:
    def __getattr__(self, name):
        raise AssertionError(f"prompt-only mode unexpectedly used {name}")


def test_chat_combines_memory_rag_and_saves_conversation() -> None:
    responses = FakeResponses()
    client = SimpleNamespace(responses=responses)
    memory = FakeMemory()
    conversation = FakeConversation()
    base_model = FakeBaseModel()
    settings = replace(get_settings(), openai_api_key="test-key")
    service = ChatService(
        settings=settings,
        client=client,
        memory_service=memory,
        retriever=FakeRetriever(),
        conversation_service=conversation,
        base_model_service=base_model,
    )

    result = asyncio.run(
        service.reply(
            ChatRequest(
                message="私が好きな動物は？",
                user_id="user-1",
                conversation_id="conversation-1",
            )
        )
    )

    assert result.reply == "覚えてるよ〜！猫が好きだったよね🐈"
    assert result.recalled_memories == 1
    assert result.retrieved_examples == 5
    assert len(result.referenced_examples) == 5
    assert result.referenced_examples[0].id == "example-1"
    assert result.referenced_examples[0].source_text == "標準表現 1"
    assert result.referenced_examples[0].gyaru_text == "ギャル表現 1"
    assert result.referenced_examples[0].score == 0.9
    assert len(base_model.calls) == 1
    assert "ユーザーは猫が好き" in base_model.calls[0][0]
    assert "猫について話している" in base_model.calls[0][0]
    assert "標準表現 1" not in base_model.calls[0][0]
    assert len(responses.calls) == 1
    assert "標準表現 1" in responses.calls[0]["input"][0]["content"]
    assert "覚えています。猫が好きでしたね。" in responses.calls[0]["input"][0]["content"]
    assert memory.saved[0] == "私が好きな動物は？"
    assert memory.saved[1] == result.reply
    assert conversation.saved[2] == "私が好きな動物は？"


def test_reset_state_clears_memory_and_conversation() -> None:
    responses = FakeResponses()
    memory = FakeMemory()
    conversation = FakeConversation()
    service = ChatService(
        settings=replace(get_settings(), openai_api_key="test-key"),
        client=SimpleNamespace(responses=responses),
        memory_service=memory,
        retriever=FakeRetriever(),
        conversation_service=conversation,
    )

    service.reset_state()

    assert memory.was_reset is True
    assert conversation.was_reset is True


@pytest.mark.parametrize(
    ("mode", "expected_prompt"),
    [
        ("simple", SIMPLE_CHAT_SYSTEM_PROMPT),
        ("prompt", build_chat_system_prompt([], conversation_summary="")),
    ],
)
def test_prompt_only_modes_skip_mem0_rag_summary_and_style_check(
    mode: str,
    expected_prompt: str,
) -> None:
    responses = FakeResponses()
    base_model = FakeBaseModel()
    disabled = DisabledAuxiliaryService()
    service = ChatService(
        settings=replace(get_settings(), mode=mode, openai_api_key="test-key"),
        client=SimpleNamespace(responses=responses),
        memory_service=disabled,
        retriever=disabled,
        conversation_service=disabled,
        base_model_service=base_model,
    )

    result = asyncio.run(
        service.reply(
            ChatRequest(
                message="今日は何をしよう？",
                user_id="user-1",
                conversation_id="conversation-1",
            )
        )
    )

    assert result.reply == "覚えています。猫が好きでしたね。"
    assert result.recalled_memories == 0
    assert result.retrieved_examples == 0
    assert result.referenced_examples == []
    assert result.warnings == []
    assert base_model.calls[0][0] == expected_prompt
    assert responses.calls == []
