from __future__ import annotations

import hashlib
import json
import math
import threading
from pathlib import Path
from typing import Any

from openai import OpenAI


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        raise ValueError("embedding dimensions do not match")
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return sum(a * b for a, b in zip(left, right, strict=True)) / (
        left_norm * right_norm
    )


class FewShotRetriever:
    def __init__(
        self,
        client: OpenAI,
        model: str,
        examples_path: Path,
        cache_path: Path,
    ) -> None:
        self.client = client
        self.model = model
        self.examples_path = examples_path
        self.cache_path = cache_path
        self._lock = threading.Lock()
        self._examples: list[dict[str, Any]] | None = None
        self._vectors: list[list[float]] | None = None

    def retrieve(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        self._ensure_index()
        assert self._examples is not None
        assert self._vectors is not None

        query_result = self.client.embeddings.create(model=self.model, input=query)
        query_vector = query_result.data[0].embedding
        ranked = sorted(
            (
                (example, cosine_similarity(query_vector, vector))
                for example, vector in zip(
                    self._examples, self._vectors, strict=True
                )
            ),
            key=lambda pair: pair[1],
            reverse=True,
        )
        return [
            {**example, "score": score}
            for example, score in ranked[:top_k]
        ]

    def _ensure_index(self) -> None:
        if self._examples is not None and self._vectors is not None:
            return

        with self._lock:
            if self._examples is not None and self._vectors is not None:
                return
            examples = self._load_examples()
            content_hash = hashlib.sha256(
                json.dumps(examples, ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest()

            cached_vectors = self._load_cache(content_hash)
            if cached_vectors is None:
                result = self.client.embeddings.create(
                    model=self.model,
                    input=[str(example["input"]) for example in examples],
                )
                cached_vectors = [item.embedding for item in result.data]
                self._save_cache(content_hash, cached_vectors)

            if len(cached_vectors) != len(examples):
                raise RuntimeError("few-shot embedding cache has an invalid size")
            self._examples = examples
            self._vectors = cached_vectors

    def _load_examples(self) -> list[dict[str, Any]]:
        if not self.examples_path.exists():
            raise FileNotFoundError(
                f"few-shot examples were not found: {self.examples_path}"
            )
        if self.examples_path.suffix.lower() == ".jsonl":
            examples = self._load_jsonl_examples()
        else:
            examples = json.loads(self.examples_path.read_text(encoding="utf-8"))
        if not isinstance(examples, list) or not examples:
            raise ValueError("few-shot examples must be a non-empty JSON array")
        for example in examples:
            if not isinstance(example, dict) or not {
                "input",
                "output",
            }.issubset(example):
                raise ValueError("each few-shot example needs input and output")
        return examples

    def _load_jsonl_examples(self) -> list[dict[str, Any]]:
        examples: list[dict[str, Any]] = []
        for line_number, line in enumerate(
            self.examples_path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"invalid JSONL at line {line_number}: {self.examples_path}"
                ) from exc

            metadata = record.get("metadata", {})
            source_text = metadata.get("source_text") or record.get("document")
            gyaru_text = metadata.get("gyaru_text")
            if not source_text or not gyaru_text:
                raise ValueError(
                    "each gyaru JSONL record needs metadata.source_text "
                    "and metadata.gyaru_text"
                )
            examples.append(
                {
                    "id": record.get("id", f"line-{line_number}"),
                    "input": str(source_text),
                    "output": str(gyaru_text),
                }
            )
        return examples

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
        payload = {"model": self.model, "hash": content_hash, "vectors": vectors}
        self.cache_path.write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
