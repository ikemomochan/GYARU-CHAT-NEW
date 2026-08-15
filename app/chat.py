from __future__ import annotations

import asyncio
import hashlib
import logging
from typing import Any

from app.config import Settings
from app.core.llm import LanguageModel
from app.core.retrieval import DialogueContextRetriever, FewShotExampleRetriever
from app.core.response_generator import ResponseGenerator
from app.core.session_state import (
    DialogueStrategy,
    InMemorySessionStore,
    SessionState,
)
from app.core.strategy_selector import StrategySelector
from app.core.tone_corrector import ToneCorrector
from app.gyaru_principles import GYARU_PRINCIPLES
from app.providers.factory import (
    build_few_shot_retriever,
    build_language_model,
    build_principle_retriever,
)
from app.schemas import ChatRequest, ChatResponse


logger = logging.getLogger(__name__)


class ChatService:
    """Orchestrates strategy, optional principle RAG, response, and tone."""

    def __init__(
        self,
        settings: Settings,
        llm: LanguageModel | None = None,
        session_store: InMemorySessionStore | None = None,
        strategy_selector: StrategySelector | None = None,
        response_generator: ResponseGenerator | None = None,
        tone_corrector: ToneCorrector | None = None,
        principle_retriever: DialogueContextRetriever | None = None,
        few_shot_retriever: FewShotExampleRetriever | None = None,
    ) -> None:
        self.settings = settings
        if (
            strategy_selector is None
            or response_generator is None
            or tone_corrector is None
        ):
            llm = llm or build_language_model(settings)
        self.strategy_selector = strategy_selector or StrategySelector(
            llm=llm,
            model=settings.strategy_model,
            max_output_tokens=settings.max_output_tokens,
        )
        self.response_generator = response_generator or ResponseGenerator(
            llm=llm,
            model=settings.response_model,
            max_output_tokens=settings.max_output_tokens,
        )
        self.tone_corrector = tone_corrector or ToneCorrector(
            llm=llm,
            model=settings.tone_model,
            max_output_tokens=settings.max_output_tokens,
        )
        self.sessions = session_store or InMemorySessionStore()
        self.principle_retriever = (
            principle_retriever or build_principle_retriever(settings)
        )
        self.few_shot_retriever = (
            few_shot_retriever or build_few_shot_retriever(settings)
        )

    async def reply(self, request: ChatRequest) -> ChatResponse:
        history = [message.model_dump() for message in request.history]
        state = self.sessions.get(request.user_id, request.conversation_id)
        safety_identifier = self._safety_identifier(request.user_id)

        selection = await asyncio.to_thread(
            self.strategy_selector.select,
            history=history,
            latest_message=request.message,
            state=state,
            principles=GYARU_PRINCIPLES,
            safety_identifier=safety_identifier,
        )
        response_state = state.with_selection(selection)

        warnings: list[str] = []
        principle_context: list[str] = []
        if selection.strategy in {
            DialogueStrategy.ADVICE,
            DialogueStrategy.SYMPATHY,
        }:
            query = self._retrieval_query(request.message, response_state)
            try:
                principle_context = await asyncio.to_thread(
                    self.principle_retriever.retrieve_context,
                    query,
                )
            except Exception:
                logger.exception("Optional gyaru-principle RAG failed")
                warnings.append(
                    "ギャル原則の補足資料を取得できなかったため、"
                    "今回はその資料なしで応答しました。"
                )

        draft = await asyncio.to_thread(
            self.response_generator.generate,
            history=history,
            latest_message=request.message,
            state=response_state,
            selection=selection,
            principles=GYARU_PRINCIPLES,
            retrieved_context=principle_context,
            safety_identifier=safety_identifier,
        )

        style_examples: list[dict[str, Any]] = []
        try:
            style_examples = await asyncio.to_thread(
                self.few_shot_retriever.retrieve_examples,
                f"{request.message}\n{draft}",
                self.settings.style_top_k,
            )
        except Exception:
            logger.exception("Few-shot style retrieval failed")
            warnings.append(
                "口調の参照例を取得できなかったため、"
                "今回は参照例なしで口調を整えました。"
            )

        try:
            reply = await asyncio.to_thread(
                self.tone_corrector.correct,
                history=history,
                latest_message=request.message,
                draft=draft,
                strategy=selection.strategy,
                safety_level=selection.safety_level,
                examples=style_examples,
                safety_identifier=safety_identifier,
            )
        except Exception:
            logger.exception("Tone correction failed")
            warnings.append(
                "口調補正に失敗したため、補正前の応答を表示しています。"
            )
            reply = draft
        self.sessions.commit(
            request.user_id,
            request.conversation_id,
            selection,
            reply,
        )
        logger.info(
            "Dialogue strategy: conversation=%s strategy=%s ready=%s reason=%s",
            request.conversation_id,
            selection.strategy.value,
            selection.perspective_ready,
            selection.reason,
        )

        return ChatResponse(
            reply=reply,
            recalled_memories=0,
            retrieved_examples=len(style_examples),
            retrieved_principles=len(principle_context),
            warnings=warnings,
        )

    def get_session_state(
        self,
        user_id: str,
        conversation_id: str,
    ) -> SessionState:
        return self.sessions.get(user_id, conversation_id)

    def reset_session(self, user_id: str, conversation_id: str) -> None:
        self.sessions.reset_session(user_id, conversation_id)

    def reset_state(self) -> None:
        self.sessions.reset_all()

    def close(self) -> None:
        for retriever in (
            self.principle_retriever,
            self.few_shot_retriever,
        ):
            close_retriever = getattr(retriever, "close", None)
            if callable(close_retriever):
                close_retriever()

    @staticmethod
    def _retrieval_query(message: str, state: SessionState) -> str:
        parts = [message, state.topic, state.known_context, state.user_need]
        return "\n".join(part.strip() for part in parts if part.strip())

    @staticmethod
    def _safety_identifier(user_id: str) -> str:
        return hashlib.sha256(user_id.encode("utf-8")).hexdigest()
