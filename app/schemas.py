from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=20_000)

    @field_validator("content")
    @classmethod
    def content_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("content must not be blank")
        return value


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=20_000)
    user_id: str = Field(min_length=1, max_length=128)
    conversation_id: str = Field(min_length=1, max_length=128)
    history: list[ChatMessage] = Field(default_factory=list, max_length=50)

    @field_validator("message", "user_id", "conversation_id")
    @classmethod
    def values_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value must not be blank")
        return value


class ChatResponse(BaseModel):
    reply: str
    recalled_memories: int
    retrieved_examples: int
    referenced_examples: list["ReferencedExample"] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ReferencedExample(BaseModel):
    id: str
    source_text: str
    gyaru_text: str
    score: float | None = None


class PublicConfig(BaseModel):
    runtime_id: str
    mode: Literal["simple", "prompt", "Mem0"]
    reset_state_on_start: bool
    base_model_provider: str
    base_model: str
    style_model: str
    memory_model: str
    summary_model: str
    embedding_model: str
    rag_top_k: int
    memory_top_k: int
    api_key_configured: bool
    missing_api_keys: list[str]
