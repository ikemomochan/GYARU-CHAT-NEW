from __future__ import annotations

import asyncio
import hashlib
from typing import Any

from openai import OpenAI

from app.base_model import BaseModelService
from app.config import Settings
from app.conversation import ConversationService
from app.memory import MemoryService
from app.prompts import (
    SIMPLE_CHAT_SYSTEM_PROMPT,
    OUTPUT_CHECK_PROMPT,
    build_chat_system_prompt,
    build_output_check_input,
)
from app.rag import FewShotRetriever
from app.schemas import ChatRequest, ChatResponse, ReferencedExample


class ChatService:
    def __init__(
        self,
        settings: Settings,
        client: OpenAI | None = None,
        memory_service: MemoryService | None = None,
        retriever: FewShotRetriever | None = None,
        conversation_service: ConversationService | None = None,
        base_model_service: BaseModelService | None = None,
    ) -> None:
        self.settings = settings
        openai_api_key = (
            settings.openai_api_key
            if settings.openai_api_key_configured
            else "unused-openai-key"
        )
        self.client = client or OpenAI(api_key=openai_api_key)
        self.memory: MemoryService | None = memory_service
        self.retriever: FewShotRetriever | None = retriever
        self.conversation: ConversationService | None = conversation_service
        if settings.mode == "Mem0":
            self.memory = self.memory or MemoryService(settings, self.client)
            self.retriever = self.retriever or FewShotRetriever(
                client=self.client,
                model=settings.embedding_model,
                examples_path=settings.rag_examples_path,
                cache_path=settings.rag_cache_path,
            )
            self.conversation = self.conversation or ConversationService(
                settings, self.client
            )
        self.base_model = base_model_service or BaseModelService(
            settings, self.client
        )

    async def reply(self, request: ChatRequest) -> ChatResponse:
        if self.settings.mode != "Mem0":
            return await self._reply_prompt_only(request)

        if (
            self.memory is None
            or self.retriever is None
            or self.conversation is None
        ):
            raise RuntimeError("Mem0 mode services are not initialized")

        memory_result, example_result, summary_result = await asyncio.gather(
            asyncio.to_thread(self.memory.search, request.message, request.user_id),
            asyncio.to_thread(
                self.retriever.retrieve, request.message, self.settings.rag_top_k
            ),
            asyncio.to_thread(
                self.conversation.get_summary,
                request.user_id,
                request.conversation_id,
            ),
            return_exceptions=True,
        )

        warnings: list[str] = []
        memories: list[str]
        examples: list[dict[str, Any]]
        conversation_summary: str

        if isinstance(memory_result, Exception):
            memories = []
            warnings.append(
                "長期記憶の検索に失敗したため、今回は記憶なしで応答しました。"
            )
        else:
            memories = memory_result

        if isinstance(example_result, Exception):
            examples = []
            warnings.append(
                "few-shot例の検索に失敗したため、今回は例なしで応答しました。"
            )
        else:
            examples = example_result

        if isinstance(summary_result, Exception):
            conversation_summary = ""
            warnings.append(
                "会話要約を読み込めなかったため、直近履歴だけで応答しました。"
            )
        else:
            conversation_summary = summary_result

        history = request.history[-self.settings.chat_history_limit :]
        input_messages = [message.model_dump() for message in history]
        input_messages.append({"role": "user", "content": request.message})
        system_prompt = build_chat_system_prompt(
            memories, conversation_summary=conversation_summary
        )

        draft = await asyncio.to_thread(
            self.base_model.generate,
            system_prompt,
            input_messages,
            self._safety_identifier(request.user_id),
        )

        try:
            style_response = await asyncio.to_thread(
                self.client.responses.create,
                model=self.settings.style_model,
                instructions=OUTPUT_CHECK_PROMPT,
                input=[
                    {
                        "role": "user",
                        "content": build_output_check_input(draft, examples),
                    }
                ],
                reasoning={"effort": self.settings.reasoning_effort},
                max_output_tokens=self.settings.max_output_tokens,
                safety_identifier=self._safety_identifier(request.user_id),
            )
            reply = style_response.output_text.strip()
            if not reply:
                raise RuntimeError("style check returned an empty response")
        except Exception:
            reply = draft
            warnings.append(
                "口調の最終チェックに失敗したため、内容生成時の回答をそのまま返しました。"
            )

        memory_write, summary_write = await asyncio.gather(
            asyncio.to_thread(
                self.memory.reconcile_conversation,
                request.message,
                reply,
                request.user_id,
                request.conversation_id,
            ),
            asyncio.to_thread(
                self.conversation.record_and_maybe_summarize,
                request.user_id,
                request.conversation_id,
                request.message,
                reply,
            ),
            return_exceptions=True,
        )

        if isinstance(memory_write, Exception):
            warnings.append(
                "応答は完了しましたが、長期記憶の追加・修正処理に失敗しました。"
            )
        if isinstance(summary_write, Exception):
            warnings.append(
                "応答は完了しましたが、会話要約を更新できませんでした。"
            )

        return ChatResponse(
            reply=reply,
            recalled_memories=len(memories),
            retrieved_examples=len(examples),
            referenced_examples=[
                ReferencedExample(
                    id=str(example.get("id", f"rank-{index}")),
                    source_text=str(example["input"]),
                    gyaru_text=str(example["output"]),
                    score=(
                        float(example["score"])
                        if example.get("score") is not None
                        else None
                    ),
                )
                for index, example in enumerate(examples, start=1)
            ],
            warnings=warnings,
        )

    async def _reply_prompt_only(self, request: ChatRequest) -> ChatResponse:
        history = request.history[-self.settings.chat_history_limit :]
        input_messages = [message.model_dump() for message in history]
        input_messages.append({"role": "user", "content": request.message})
        system_prompt = (
            SIMPLE_CHAT_SYSTEM_PROMPT
            if self.settings.mode == "simple"
            else build_chat_system_prompt([], conversation_summary="")
        )
        reply = await asyncio.to_thread(
            self.base_model.generate,
            system_prompt,
            input_messages,
            self._safety_identifier(request.user_id),
        )
        return ChatResponse(
            reply=reply,
            recalled_memories=0,
            retrieved_examples=0,
        )

    def close(self) -> None:
        if self.memory is not None:
            self.memory.close()

    def reset_state(self) -> None:
        if self.settings.mode != "Mem0":
            return
        if self.conversation is not None:
            self.conversation.reset()
        if self.memory is not None:
            self.memory.reset()

    @staticmethod
    def _safety_identifier(user_id: str) -> str:
        return hashlib.sha256(user_id.encode("utf-8")).hexdigest()
