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


def _boolean(name: str, default: bool) -> bool:
    raw_value = os.getenv(name, str(default)).strip().lower()
    if raw_value in {"1", "true", "yes", "on"}:
        return True
    if raw_value in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be true or false")


@dataclass(frozen=True)
class Settings:
    mode: str
    openai_api_key: str
    anthropic_api_key: str
    base_model_provider: str
    base_model: str
    style_model: str
    memory_model: str
    summary_model: str
    embedding_model: str
    reasoning_effort: str
    memory_top_k: int
    rag_top_k: int
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

    @property
    def openai_api_key_configured(self) -> bool:
        key = self.openai_api_key.strip()
        return bool(key) and key != "sk-your-key-here"

    @property
    def anthropic_api_key_configured(self) -> bool:
        key = self.anthropic_api_key.strip()
        return bool(key) and key != "sk-ant-your-key-here"

    @property
    def missing_api_keys(self) -> tuple[str, ...]:
        missing: list[str] = []
        # Mem0 mode always needs OpenAI for style, memory, summaries, and embeddings.
        if (
            self.base_model_provider == "openai" or self.mode == "Mem0"
        ) and not self.openai_api_key_configured:
            missing.append("OPENAI_API_KEY")
        if (
            self.base_model_provider == "anthropic"
            and not self.anthropic_api_key_configured
        ):
            missing.append("ANTHROPIC_API_KEY")
        return tuple(missing)

    @property
    def api_key_configured(self) -> bool:
        return not self.missing_api_keys


@lru_cache
def get_settings() -> Settings:
    raw_mode = os.getenv("MODE", "Mem0").strip().lower()
    modes = {"simple": "simple", "prompt": "prompt", "mem0": "Mem0"}
    if raw_mode not in modes:
        raise ValueError("MODE must be one of: simple, prompt, Mem0")

    base_model_provider = os.getenv("BASE_MODEL_PROVIDER", "openai").lower()
    allowed_providers = {"openai", "anthropic"}
    if base_model_provider not in allowed_providers:
        raise ValueError(
            "BASE_MODEL_PROVIDER must be one of: "
            + ", ".join(sorted(allowed_providers))
        )

    reasoning_effort = os.getenv("OPENAI_REASONING_EFFORT", "low").lower()
    allowed_efforts = {"none", "low", "medium", "high", "xhigh", "max"}
    if reasoning_effort not in allowed_efforts:
        raise ValueError(
            "OPENAI_REASONING_EFFORT must be one of: "
            + ", ".join(sorted(allowed_efforts))
        )

    return Settings(
        mode=modes[raw_mode],
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
        base_model_provider=base_model_provider,
        base_model=os.getenv("BASE_MODEL", "gpt-5.6-sol"),
        style_model=os.getenv("OPENAI_STYLE_MODEL", "gpt-5.6-luna"),
        memory_model=os.getenv("OPENAI_MEMORY_MODEL", "gpt-5.6-luna"),
        summary_model=os.getenv("OPENAI_SUMMARY_MODEL", "gpt-5.6-luna"),
        embedding_model=os.getenv(
            "OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"
        ),
        reasoning_effort=reasoning_effort,
        memory_top_k=_positive_int("MEMORY_TOP_K", 5),
        rag_top_k=max(5, _positive_int("RAG_TOP_K", 5)),
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
    )
