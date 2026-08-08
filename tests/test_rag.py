from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.rag import FewShotRetriever, cosine_similarity


class FakeEmbeddings:
    def __init__(self) -> None:
        self.calls = 0

    def create(self, *, model: str, input: str | list[str]):
        self.calls += 1
        values = input if isinstance(input, list) else [input]
        vectors = []
        for value in values:
            if "りんご" in value:
                vector = [1.0, 0.0]
            elif "コード" in value:
                vector = [0.0, 1.0]
            else:
                vector = [0.5, 0.5]
            vectors.append(SimpleNamespace(embedding=vector))
        return SimpleNamespace(data=vectors)


def test_cosine_similarity() -> None:
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_retriever_ranks_and_reuses_cache(tmp_path: Path) -> None:
    examples_path = tmp_path / "examples.json"
    cache_path = tmp_path / "cache.json"
    examples_path.write_text(
        json.dumps(
            [
                {"input": "りんごが好き", "output": "果物の話"},
                {"input": "コードを直したい", "output": "開発の話"},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    embeddings = FakeEmbeddings()
    client = SimpleNamespace(embeddings=embeddings)

    retriever = FewShotRetriever(
        client=client,
        model="fake-model",
        examples_path=examples_path,
        cache_path=cache_path,
    )
    result = retriever.retrieve("りんごについて", top_k=1)
    assert result[0]["output"] == "果物の話"
    assert cache_path.exists()
    assert embeddings.calls == 2  # build index + embed query

    second = FewShotRetriever(
        client=client,
        model="fake-model",
        examples_path=examples_path,
        cache_path=cache_path,
    )
    second.retrieve("コードについて", top_k=1)
    assert embeddings.calls == 3  # cached index + one new query


def test_gyaru_jsonl_is_loaded_as_paraphrase_pairs(tmp_path: Path) -> None:
    embeddings = FakeEmbeddings()
    retriever = FewShotRetriever(
        client=SimpleNamespace(embeddings=embeddings),
        model="fake-model",
        examples_path=Path("data/gyaru_rag_documents.jsonl"),
        cache_path=tmp_path / "cache.json",
    )

    examples = retriever._load_examples()

    assert len(examples) >= 5
    assert examples[0]["input"] == "水菜を買ってきました！！牛肉がいいやつで、野菜は軽くと言われました。"
    assert examples[0]["output"] == "意味がわかりませんでした、、"
