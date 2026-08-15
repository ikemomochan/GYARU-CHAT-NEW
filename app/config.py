from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


def _path_from_env(name: str, default: str) -> Path:
    value = Path(os.getenv(name, default))
    return value if value.is_absolute() else PROJECT_ROOT / value


def _positive_int(name: str, default: int) -> int:
    raw_value = os.getenv(name, str(default))
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value < 1:
        raise ValueError(f"{name} must be greater than zero")
    return value


def _nonnegative_int(name: str, default: int) -> int:
    raw_value = os.getenv(name, str(default))
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value < 0:
        raise ValueError(f"{name} must be zero or greater")
    return value


def _boolean(name: str, default: bool) -> bool:
    raw_value = os.getenv(name, str(default)).strip().lower()
    if raw_value in {"1", "true", "yes", "on"}:
        return True
    if raw_value in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be true or false")


@dataclass(frozen=True)
class Settings:
    llm_provider: str
    strategy_model: str
    response_model: str
    tone_model: str
    openai_api_key: str
    chat_model: str
    style_model: str
    memory_model: str
    summary_model: str
    embedding_model: str
    reasoning_effort: str
    openai_timeout_seconds: int
    openai_max_retries: int
    memory_top_k: int
    rag_top_k: int
    style_top_k: int
    principle_rag_top_k: int
    chat_rate_limit: int
    chat_rate_window_seconds: int
    chat_history_limit: int
    summary_trigger_messages: int
    max_output_tokens: int
    reset_state_on_start: bool
    mem0_vector_path: Path
    mem0_history_db_path: Path
    mem0_collection_name: str
    conversation_db_path: Path
    rag_examples_path: Path
    rag_cache_path: Path
    style_examples_path: Path
    style_cache_path: Path
    principle_rag_path: Path
    principle_rag_cache_path: Path

    @property
    def api_key_configured(self) -> bool:
        if self.llm_provider != "openai":
            return True
        key = self.openai_api_key.strip()
        return bool(key) and key != "sk-your-key-here"


@lru_cache
def get_settings() -> Settings:
    llm_provider = os.getenv("LLM_PROVIDER", "openai").strip().lower()
    if not llm_provider:
        raise ValueError("LLM_PROVIDER must not be blank")

    legacy_chat_model = os.getenv("OPENAI_CHAT_MODEL", "gpt-5.6-luna")
    reasoning_effort = os.getenv("OPENAI_REASONING_EFFORT", "low").lower()
    allowed_efforts = {"none", "low", "medium", "high", "xhigh", "max"}
    if reasoning_effort not in allowed_efforts:
        raise ValueError(
            "OPENAI_REASONING_EFFORT must be one of: "
            + ", ".join(sorted(allowed_efforts))
        )

    return Settings(
        llm_provider=llm_provider,
        strategy_model=os.getenv("STRATEGY_MODEL", legacy_chat_model),
        response_model=os.getenv("RESPONSE_MODEL", legacy_chat_model),
        tone_model=os.getenv("TONE_MODEL", legacy_chat_model),
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        chat_model=legacy_chat_model,
        style_model=os.getenv("OPENAI_STYLE_MODEL", "gpt-5.6-luna"),
        memory_model=os.getenv("OPENAI_MEMORY_MODEL", "gpt-5.6-luna"),
        summary_model=os.getenv("OPENAI_SUMMARY_MODEL", "gpt-5.6-luna"),
        embedding_model=os.getenv(
            "OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"
        ),
        reasoning_effort=reasoning_effort,
        openai_timeout_seconds=_positive_int("OPENAI_TIMEOUT_SECONDS", 30),
        openai_max_retries=_nonnegative_int("OPENAI_MAX_RETRIES", 1),
        memory_top_k=_positive_int("MEMORY_TOP_K", 5),
        rag_top_k=max(5, _positive_int("RAG_TOP_K", 5)),
        style_top_k=_positive_int("STYLE_TOP_K", 5),
        principle_rag_top_k=_positive_int("PRINCIPLE_RAG_TOP_K", 5),
        chat_rate_limit=_positive_int("CHAT_RATE_LIMIT", 12),
        chat_rate_window_seconds=_positive_int(
            "CHAT_RATE_WINDOW_SECONDS", 60
        ),
        chat_history_limit=_positive_int("CHAT_HISTORY_LIMIT", 12),
        summary_trigger_messages=_positive_int("SUMMARY_TRIGGER_MESSAGES", 12),
        max_output_tokens=_positive_int("MAX_OUTPUT_TOKENS", 1000),
        reset_state_on_start=_boolean("RESET_STATE_ON_START", True),
        mem0_vector_path=_path_from_env(
            "MEM0_VECTOR_PATH", ".data/mem0_qdrant"
        ),
        mem0_history_db_path=_path_from_env(
            "MEM0_HISTORY_DB_PATH", ".data/mem0_history.db"
        ),
        mem0_collection_name=os.getenv(
            "MEM0_COLLECTION_NAME", "gyaru_chat_memories"
        ),
        conversation_db_path=_path_from_env(
            "CONVERSATION_DB_PATH", ".data/conversations.db"
        ),
        rag_examples_path=_path_from_env(
            "RAG_EXAMPLES_PATH", "data/gyaru_rag_documents.jsonl"
        ),
        rag_cache_path=_path_from_env(
            "RAG_CACHE_PATH", ".data/few_shot_embeddings.json"
        ),
        style_examples_path=_path_from_env(
            "STYLE_EXAMPLES_PATH", "data/gyaru_rag_documents.jsonl"
        ),
        style_cache_path=_path_from_env(
            "STYLE_CACHE_PATH", ".data/style_embeddings.json"
        ),
        principle_rag_path=_path_from_env(
            "PRINCIPLE_RAG_PATH", "data/gyaru_principles_rag.jsonl"
        ),
        principle_rag_cache_path=_path_from_env(
            "PRINCIPLE_RAG_CACHE_PATH",
            ".data/gyaru_principle_embeddings.json",
        ),
    )
