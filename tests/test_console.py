from __future__ import annotations

import asyncio
from dataclasses import replace

from app.config import get_settings
from app.console import ConsoleSession
from app.schemas import ChatResponse


class FakeChatService:
    def __init__(self) -> None:
        self.requests = []
        self.reset_calls = []

    async def reply(self, request):
        self.requests.append(request)
        return ChatResponse(
            reply=f"返答{len(self.requests)}",
            recalled_memories=0,
            retrieved_examples=0,
        )

    def reset_session(self, user_id: str, conversation_id: str) -> None:
        self.reset_calls.append((user_id, conversation_id))


def test_console_session_passes_recent_conversation_history() -> None:
    service = FakeChatService()
    settings = replace(get_settings(), chat_history_limit=2)
    session = ConsoleSession(service, settings)

    assert asyncio.run(session.reply("最初")) == "返答1"
    assert asyncio.run(session.reply("次")) == "返答2"

    assert service.requests[0].history == []
    assert [message.model_dump() for message in service.requests[1].history] == [
        {"role": "user", "content": "最初"},
        {"role": "assistant", "content": "返答1"},
    ]
    assert [message.content for message in session.history] == ["次", "返答2"]


def test_console_session_reset_starts_a_new_conversation() -> None:
    service = FakeChatService()
    session = ConsoleSession(service, get_settings())
    old_conversation_id = session.conversation_id

    asyncio.run(session.reply("最初"))
    session.reset()

    assert service.reset_calls == [(session.user_id, old_conversation_id)]
    assert session.conversation_id != old_conversation_id
    assert session.history == []
