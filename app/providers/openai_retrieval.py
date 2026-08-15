from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from typing import Any

from openai import OpenAI

from app.rag import FewShotRetriever, cosine_similarity


class OpenAIFewShotExampleRetriever:
    """Adapts the existing few-shot embedding retriever to the active flow."""

    def __init__(self, retriever: FewShotRetriever) -> None:
        self.retriever = retriever

    def retrieve_examples(
        self,
        query: str,
        top_k: int,
    ) -> list[dict[str, Any]]:
        return self.retriever.retrieve(query, top_k=top_k)


class OpenAIPrincipleRetriever:
    """Embedding RAG for optional gyaru-principle reference documents."""

    def __init__(
        self,
        client: OpenAI,
        model: str,
        documents_path: Path,
        cache_path: Path,
        top_k: int,
    ) -> None:
        self.client = client
        self.model = model
        self.documents_path = documents_path
        self.cache_path = cache_path
        self.top_k = top_k
        self._documents: list[str] | None = None
        self._vectors: list[list[float]] | None = None
        self._lock = threading.Lock()

    def retrieve_context(self, query: str) -> list[str]:
        self._ensure_index()
        assert self._documents is not None
        assert self._vectors is not None
        if not self._documents:
            return []

        result = self.client.embeddings.create(model=self.model, input=query)
        query_vector = result.data[0].embedding
        ranked = sorted(
            zip(self._documents, self._vectors, strict=True),
            key=lambda pair: cosine_similarity(query_vector, pair[1]),
            reverse=True,
        )
        return [document for document, _ in ranked[: self.top_k]]

    def _ensure_index(self) -> None:
        if self._documents is not None and self._vectors is not None:
            return
        with self._lock:
            if self._documents is not None and self._vectors is not None:
                return
            documents = self._load_documents()
            if not documents:
                self._documents = []
                self._vectors = []
                return

            content_hash = hashlib.sha256(
                json.dumps(documents, ensure_ascii=False).encode("utf-8")
            ).hexdigest()
            vectors = self._load_cache(content_hash)
            if vectors is None:
                result = self.client.embeddings.create(
                    model=self.model,
                    input=documents,
                )
                vectors = [item.embedding for item in result.data]
                self._save_cache(content_hash, vectors)
            if len(vectors) != len(documents):
                raise RuntimeError("principle RAG cache has an invalid size")
            self._documents = documents
            self._vectors = vectors

    def _load_documents(self) -> list[str]:
        if not self.documents_path.exists():
            raise FileNotFoundError(
                f"gyaru principle documents were not found: {self.documents_path}"
            )
        documents: list[str] = []
        for line_number, line in enumerate(
            self.documents_path.read_text(encoding="utf-8").splitlines(),
            start=1,
        ):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"invalid JSONL at line {line_number}: {self.documents_path}"
                ) from exc
            if not isinstance(record, dict):
                raise ValueError(
                    "each gyaru principle JSONL line must be an object"
                )
            text = record.get("text") or record.get("document")
            if not text and record.get("principle"):
                parts = []
                if record.get("title"):
                    parts.append(f"題名: {record['title']}")
                parts.append(f"原則: {record['principle']}")
                if record.get("caution"):
                    parts.append(f"注意: {record['caution']}")
                quotes = record.get("quotes")
                if isinstance(quotes, list):
                    clean_quotes = [
                        str(quote).strip()
                        for quote in quotes
                        if str(quote).strip()
                    ]
                    if clean_quotes:
                        parts.append("発話例: " + " / ".join(clean_quotes))
                text = "\n".join(parts)
            if not text:
                raise ValueError(
                    "each gyaru principle JSONL record needs text, document, "
                    "or principle"
                )
            documents.append(str(text))
        return documents

    def _load_cache(self, content_hash: str) -> list[list[float]] | None:
        if not self.cache_path.exists():
            return None
        try:
            cache = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if cache.get("model") != self.model or cache.get("hash") != content_hash:
            return None
        vectors = cache.get("vectors")
        return vectors if isinstance(vectors, list) else None

    def _save_cache(self, content_hash: str, vectors: list[list[float]]) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(
            json.dumps(
                {
                    "model": self.model,
                    "hash": content_hash,
                    "vectors": vectors,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
