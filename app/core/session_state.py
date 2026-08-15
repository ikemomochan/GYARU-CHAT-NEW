from __future__ import annotations

import threading
from enum import Enum

from pydantic import BaseModel, Field, model_validator


class DialogueStrategy(str, Enum):
    LISTEN = "LISTEN"
    ADVICE = "ADVICE"
    SYMPATHY = "SYMPATHY"


class SafetyLevel(str, Enum):
    NORMAL = "NORMAL"
    ETHICAL_BOUNDARY = "ETHICAL_BOUNDARY"
    URGENT = "URGENT"


class StrategyRecord(BaseModel):
    strategy: DialogueStrategy
    reason: str
    response: str


class SessionState(BaseModel):
    topic: str = ""
    known_context: str = ""
    user_need: str = ""
    strategy_history: list[StrategyRecord] = Field(default_factory=list)
    perspective_ready: bool = False

    def with_selection(self, selection: "StrategySelection") -> "SessionState":
        return self.model_copy(
            deep=True,
            update={
                "topic": selection.topic.strip() or self.topic,
                "known_context": (
                    selection.known_context.strip() or self.known_context
                ),
                "user_need": selection.user_need.strip() or self.user_need,
                "perspective_ready": selection.perspective_ready,
            },
        )


class StrategySelection(BaseModel):
    strategy: DialogueStrategy
    perspective_ready: bool
    reason: str = Field(min_length=1)
    topic: str = ""
    known_context: str = ""
    user_need: str = ""
    safety_level: SafetyLevel = SafetyLevel.NORMAL

    @model_validator(mode="after")
    def action_strategies_are_ready(self) -> "StrategySelection":
        if self.strategy in {
            DialogueStrategy.ADVICE,
            DialogueStrategy.SYMPATHY,
        }:
            self.perspective_ready = True
        return self


class InMemorySessionStore:
    """Keeps state only for the lifetime of the current server process."""

    def __init__(self, history_limit: int = 50) -> None:
        self.history_limit = history_limit
        self._states: dict[tuple[str, str], SessionState] = {}
        self._lock = threading.RLock()

    def get(self, user_id: str, conversation_id: str) -> SessionState:
        key = (user_id, conversation_id)
        with self._lock:
            state = self._states.get(key, SessionState())
            return state.model_copy(deep=True)

    def commit(
        self,
        user_id: str,
        conversation_id: str,
        selection: StrategySelection,
        response: str,
    ) -> SessionState:
        key = (user_id, conversation_id)
        with self._lock:
            state = self._states.get(key, SessionState()).with_selection(selection)
            state.strategy_history.append(
                StrategyRecord(
                    strategy=selection.strategy,
                    reason=selection.reason,
                    response=response,
                )
            )
            state.strategy_history = state.strategy_history[-self.history_limit :]
            self._states[key] = state
            return state.model_copy(deep=True)

    def reset_session(self, user_id: str, conversation_id: str) -> None:
        with self._lock:
            self._states.pop((user_id, conversation_id), None)

    def reset_all(self) -> None:
        with self._lock:
            self._states.clear()
