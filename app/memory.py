from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Literal

from openai import OpenAI
from pydantic import BaseModel, Field

from app.config import Settings
from app.prompts import MEMORY_EXTRACTION_PROMPT, MEMORY_RECONCILIATION_PROMPT


class MemoryExtraction(BaseModel):
    facts: list[str] = Field(default_factory=list)
    forget_requests: list[str] = Field(default_factory=list)


class MemoryAction(BaseModel):
    event: Literal["ADD", "UPDATE", "DELETE", "NONE"]
    memory_id: str = ""
    text: str = ""


class MemoryReconciliation(BaseModel):
    actions: list[MemoryAction] = Field(default_factory=list)


class MemoryService:
    """Mem0 storage/search plus app-owned extraction and reconciliation."""

    def __init__(self, settings: Settings, client: OpenAI) -> None:
        self.settings = settings
        self.client = client
        self._memory: Any | None = None
        self._lock = threading.Lock()

    def search(self, query: str, user_id: str) -> list[str]:
        return [
            record["memory"]
            for record in self._search_records(
                query, user_id, self.settings.memory_top_k
            )
        ]

    def reset(self) -> None:
        self._get_memory().reset()

    def reconcile_conversation(
        self,
        user_message: str,
        assistant_message: str,
        user_id: str,
        conversation_id: str,
    ) -> int:
        extraction = self._extract_memories(user_message, assistant_message, user_id)
        if not extraction.facts and not extraction.forget_requests:
            return 0

        lookup_query = "\n".join(
            [*extraction.facts, *extraction.forget_requests]
        )
        existing = self._search_records(
            lookup_query,
            user_id,
            max(10, self.settings.memory_top_k),
        )
        plan = self._reconcile(extraction, existing, user_id)
        return self._apply_plan(plan, existing, user_id, conversation_id)

    def _extract_memories(
        self, user_message: str, assistant_message: str, user_id: str
    ) -> MemoryExtraction:
        response = self.client.responses.parse(
            model=self.settings.memory_model,
            instructions=MEMORY_EXTRACTION_PROMPT,
            input=[
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "user_message": user_message,
                            "assistant_message": assistant_message,
                        },
                        ensure_ascii=False,
                    ),
                }
            ],
            text_format=MemoryExtraction,
            reasoning={"effort": self.settings.reasoning_effort},
            max_output_tokens=self.settings.max_output_tokens,
            safety_identifier=self._safety_identifier(user_id),
        )
        if response.output_parsed is None:
            raise RuntimeError("memory extraction returned no structured output")
        return response.output_parsed

    def _reconcile(
        self,
        extraction: MemoryExtraction,
        existing: list[dict[str, str]],
        user_id: str,
    ) -> MemoryReconciliation:
        response = self.client.responses.parse(
            model=self.settings.memory_model,
            instructions=MEMORY_RECONCILIATION_PROMPT,
            input=[
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "existing_memories": existing,
                            "new_facts": extraction.facts,
                            "forget_requests": extraction.forget_requests,
                        },
                        ensure_ascii=False,
                    ),
                }
            ],
            text_format=MemoryReconciliation,
            reasoning={"effort": self.settings.reasoning_effort},
            max_output_tokens=self.settings.max_output_tokens,
            safety_identifier=self._safety_identifier(user_id),
        )
        if response.output_parsed is None:
            raise RuntimeError("memory reconciliation returned no structured output")
        return response.output_parsed

    def _apply_plan(
        self,
        plan: MemoryReconciliation,
        existing: list[dict[str, str]],
        user_id: str,
        conversation_id: str,
    ) -> int:
        memory = self._get_memory()
        existing_ids = {record["id"] for record in existing}
        touched_ids: set[str] = set()
        applied = 0

        for action in plan.actions:
            text = action.text.strip()
            memory_id = action.memory_id.strip()

            if action.event == "ADD":
                if not text:
                    continue
                memory.add(
                    text,
                    user_id=user_id,
                    metadata={"conversation_id": conversation_id},
                    infer=False,
                )
                applied += 1
            elif action.event == "UPDATE":
                if (
                    not text
                    or memory_id not in existing_ids
                    or memory_id in touched_ids
                ):
                    continue
                memory.update(memory_id, text=text)
                touched_ids.add(memory_id)
                applied += 1
            elif action.event == "DELETE":
                if memory_id not in existing_ids or memory_id in touched_ids:
                    continue
                memory.delete(memory_id)
                touched_ids.add(memory_id)
                applied += 1

        return applied

    def _search_records(
        self, query: str, user_id: str, top_k: int
    ) -> list[dict[str, str]]:
        result = self._get_memory().search(
            query=query,
            filters={"user_id": user_id},
            top_k=top_k,
        )
        entries = result.get("results", result) if isinstance(result, dict) else result
        if not isinstance(entries, list):
            return []

        records = []
        for entry in entries:
            if not isinstance(entry, dict) or not entry.get("memory"):
                continue
            memory_id = entry.get("id") or entry.get("memory_id")
            if memory_id:
                records.append(
                    {"id": str(memory_id), "memory": str(entry["memory"])}
                )
        return records

    def close(self) -> None:
        if self._memory is None:
            return
        close_memory = getattr(self._memory, "close", None)
        if callable(close_memory):
            close_memory()
        vector_store = getattr(self._memory, "vector_store", None)
        client = getattr(vector_store, "client", None)
        close_vector_store = getattr(client, "close", None)
        if callable(close_vector_store):
            close_vector_store()
        self._memory = None

    def _get_memory(self) -> Any:
        if self._memory is not None:
            return self._memory
        with self._lock:
            if self._memory is not None:
                return self._memory

            from mem0 import Memory

            self._ensure_directory(self.settings.mem0_vector_path)
            self._ensure_directory(self.settings.mem0_history_db_path.parent)
            config = {
                "version": "v1.1",
                "llm": {
                    "provider": "openai",
                    "config": {
                        "api_key": self.settings.openai_api_key,
                        "model": self.settings.memory_model,
                    },
                },
                "embedder": {
                    "provider": "openai",
                    "config": {
                        "api_key": self.settings.openai_api_key,
                        "model": self.settings.embedding_model,
                    },
                },
                "vector_store": {
                    "provider": "qdrant",
                    "config": {
                        "collection_name": self.settings.mem0_collection_name,
                        "path": str(self.settings.mem0_vector_path),
                        "on_disk": True,
                    },
                },
                "history_db_path": str(self.settings.mem0_history_db_path),
            }
            self._memory = Memory.from_config(config)
            return self._memory

    @staticmethod
    def _ensure_directory(path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _safety_identifier(user_id: str) -> str:
        import hashlib

        return hashlib.sha256(user_id.encode("utf-8")).hexdigest()
