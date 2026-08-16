from __future__ import annotations

import asyncio

from app.config import get_settings
from app.schemas import ChatMessage, ChatRequest
from app.simple_chat import SIMPLE_GYARU_SYSTEM_PROMPT, SimpleGyaruChatService


class FakeLanguageModel:
    def __init__(self) -> None:
        self.calls = []

    def generate_text(self, **kwargs):
        self.calls.append(kwargs)
        return "ギャルの返答"


def test_simple_condition_uses_only_one_line_system_prompt() -> None:
    llm = FakeLanguageModel()
    service = SimpleGyaruChatService(get_settings(), llm=llm)
    request = ChatRequest(
        message="今日つかれた",
        user_id="anonymous-id",
        conversation_id="experiment:SIMPLE",
        history=[ChatMessage(role="assistant", content="どしたん？")],
    )

    response = asyncio.run(service.reply(request))

    assert SIMPLE_GYARU_SYSTEM_PROMPT == "あなたはギャルです"
    assert llm.calls[0]["system_prompt"] == "あなたはギャルです"
    assert llm.calls[0]["messages"] == [
        {"role": "assistant", "content": "どしたん？"},
        {"role": "user", "content": "今日つかれた"},
    ]
    assert response.reply == "ギャルの返答"
    assert response.retrieved_examples == 0
    assert response.retrieved_principles == 0
