from __future__ import annotations

import asyncio
from dataclasses import replace
from types import SimpleNamespace

from app.chat import ChatService
from app.config import get_settings
from app.schemas import ChatRequest


class FakeResponses:
    def __init__(self) -> None:
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        outputs = [
            "覚えています。猫が好きでしたね。",
            "覚えてるよ〜！猫が好きだったよね🐈",
        ]
        return SimpleNamespace(output_text=outputs[len(self.calls) - 1])


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
            {"input": f"標準表現 {index}", "output": f"ギャル表現 {index}"}
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


def test_chat_combines_memory_rag_and_saves_conversation() -> None:
    responses = FakeResponses()
    client = SimpleNamespace(responses=responses)
    memory = FakeMemory()
    conversation = FakeConversation()
    settings = replace(get_settings(), openai_api_key="test-key")
    service = ChatService(
        settings=settings,
        client=client,
        memory_service=memory,
        retriever=FakeRetriever(),
        conversation_service=conversation,
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
    assert len(responses.calls) == 2
    assert "ユーザーは猫が好き" in responses.calls[0]["instructions"]
    assert "猫について話している" in responses.calls[0]["instructions"]
    assert "標準表現 1" not in responses.calls[0]["instructions"]
    assert "標準表現 1" in responses.calls[1]["input"][0]["content"]
    assert "覚えています。猫が好きでしたね。" in responses.calls[1]["input"][0]["content"]
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
