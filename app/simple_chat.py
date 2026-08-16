from __future__ import annotations

import asyncio

from app.config import Settings
from app.core.llm import LanguageModel
from app.providers.factory import build_language_model
from app.schemas import ChatRequest, ChatResponse


SIMPLE_GYARU_SYSTEM_PROMPT = "あなたはギャルです"


class SimpleGyaruChatService:
    """Baseline condition with only the requested one-line system prompt."""

    def __init__(
        self,
        settings: Settings,
        llm: LanguageModel | None = None,
    ) -> None:
        self.settings = settings
        self.llm = llm or build_language_model(settings)

    async def reply(self, request: ChatRequest) -> ChatResponse:
        messages = [
            *[message.model_dump() for message in request.history],
            {"role": "user", "content": request.message},
        ]
        reply = await asyncio.to_thread(
            self.llm.generate_text,
            model=self.settings.response_model,
            system_prompt=SIMPLE_GYARU_SYSTEM_PROMPT,
            messages=messages,
            max_output_tokens=min(self.settings.max_output_tokens, 600),
            safety_identifier=request.user_id,
        )
        return ChatResponse(
            reply=reply.strip(),
            recalled_memories=0,
            retrieved_examples=0,
            retrieved_principles=0,
            strategy="SIMPLE_PROMPT",
        )
