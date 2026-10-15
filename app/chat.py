from __future__ import annotations

import asyncio
import hashlib
import logging

from app.config import Settings
from app.core.llm import LanguageModel
from app.core.response_generator import ResponseGenerator
from app.core.session_state import InMemorySessionStore, SessionState
from app.core.strategy_selector import StrategySelector
from app.gyaru_principles import GYARU_PRINCIPLES
from app.providers.factory import build_language_model
from app.schemas import ChatRequest, ChatResponse


logger = logging.getLogger(__name__)


class ChatService:
    """Runs strategy selection and direct response generation without RAG."""

    def __init__(
        self,
        settings: Settings,
        llm: LanguageModel | None = None,
        session_store: InMemorySessionStore | None = None,
        strategy_selector: StrategySelector | None = None,
        response_generator: ResponseGenerator | None = None,
    ) -> None:
        self.settings = settings
        if strategy_selector is None or response_generator is None:
            llm = llm or build_language_model(settings)
        self.strategy_selector = strategy_selector or StrategySelector(
            llm=llm,
            model=settings.strategy_model,
            max_output_tokens=settings.max_output_tokens,
        )
        self.response_generator = response_generator or ResponseGenerator(
            llm=llm,
            model=settings.response_model,
        )
        self.sessions = session_store or InMemorySessionStore()

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

        reply = await asyncio.to_thread(
            self.response_generator.generate,
            history=history,
            latest_message=request.message,
            state=response_state,
            selection=selection,
            principles=GYARU_PRINCIPLES,
            retrieved_context=[],
            safety_identifier=safety_identifier,
        )
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
            retrieved_examples=0,
            retrieved_principles=0,
            warnings=[],
            strategy=selection.strategy.value,
            strategy_reason=selection.reason,
            safety_level=selection.safety_level.value,
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
        pass

    @staticmethod
    def _safety_identifier(user_id: str) -> str:
        return hashlib.sha256(user_id.encode("utf-8")).hexdigest()
