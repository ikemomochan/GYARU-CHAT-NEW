from __future__ import annotations

from types import SimpleNamespace

from app.providers.openai_retrieval import OpenAIPrincipleRetriever


class FailIfCalledEmbeddings:
    def create(self, **kwargs):
        raise AssertionError("empty principle file must not call embeddings")


class FakeOpenAIClient:
    embeddings = FailIfCalledEmbeddings()


def test_empty_principle_rag_file_returns_no_context(tmp_path) -> None:
    documents_path = tmp_path / "principles.jsonl"
    documents_path.write_text("", encoding="utf-8")
    retriever = OpenAIPrincipleRetriever(
        client=FakeOpenAIClient(),
        model="embedding-model",
        documents_path=documents_path,
        cache_path=tmp_path / "cache.json",
        top_k=5,
    )

    assert retriever.retrieve_context("相談内容") == []
    assert not (tmp_path / "cache.json").exists()


class FakeEmbeddings:
    def __init__(self) -> None:
        self.inputs = []

    def create(self, *, model, input):
        self.inputs.append(input)
        values = input if isinstance(input, list) else [input]
        return SimpleNamespace(
            data=[
                SimpleNamespace(embedding=[1.0, float(index)])
                for index, _ in enumerate(values)
            ]
        )


def test_principle_record_format_is_converted_to_retrievable_text(tmp_path) -> None:
    documents_path = tmp_path / "principles.jsonl"
    documents_path.write_text(
        '{"id":"mind_self","title":"自分軸","principle":"自分の意思を大切にする。",'
        '"caution":"他人を軽視することとは異なる。","quotes":[]}\n',
        encoding="utf-8",
    )
    embeddings = FakeEmbeddings()
    client = SimpleNamespace(embeddings=embeddings)
    retriever = OpenAIPrincipleRetriever(
        client=client,
        model="embedding-model",
        documents_path=documents_path,
        cache_path=tmp_path / "cache.json",
        top_k=5,
    )

    result = retriever.retrieve_context("自分の意思")

    assert result == [
        "題名: 自分軸\n原則: 自分の意思を大切にする。\n"
        "注意: 他人を軽視することとは異なる。"
    ]
    assert len(embeddings.inputs) == 2
