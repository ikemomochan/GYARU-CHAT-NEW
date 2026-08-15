from __future__ import annotations

from typing import Any, Protocol


class DialogueContextRetriever(Protocol):
    """Optional dialogue RAG slot; core principles never depend on it."""

    def retrieve_context(self, query: str) -> list[str]: ...


class NoOpDialogueRetriever:
    def retrieve_context(self, query: str) -> list[str]:
        return []


class FewShotExampleRetriever(Protocol):
    """Retrieves human-written examples used only for tone correction."""

    def retrieve_examples(
        self,
        query: str,
        top_k: int,
    ) -> list[dict[str, Any]]: ...


class NoOpFewShotExampleRetriever:
    def retrieve_examples(
        self,
        query: str,
        top_k: int,
    ) -> list[dict[str, Any]]:
        return []
