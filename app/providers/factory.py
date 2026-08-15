from __future__ import annotations

from app.config import Settings
from app.core.llm import LanguageModel
from app.core.retrieval import DialogueContextRetriever, FewShotExampleRetriever


def _build_openai_client(settings: Settings):
    from openai import OpenAI

    return OpenAI(
        api_key=settings.openai_api_key,
        timeout=settings.openai_timeout_seconds,
        max_retries=settings.openai_max_retries,
    )


def build_language_model(settings: Settings) -> LanguageModel:
    if settings.llm_provider == "openai":
        from app.providers.openai_provider import OpenAILanguageModel

        client = _build_openai_client(settings)
        return OpenAILanguageModel(client, settings.reasoning_effort)
    raise ValueError(
        f"LLM provider '{settings.llm_provider}' has no installed adapter"
    )


def build_few_shot_retriever(settings: Settings) -> FewShotExampleRetriever:
    if settings.llm_provider == "openai":
        from app.providers.openai_retrieval import OpenAIFewShotExampleRetriever
        from app.rag import FewShotRetriever

        client = _build_openai_client(settings)
        return OpenAIFewShotExampleRetriever(
            FewShotRetriever(
                client=client,
                model=settings.embedding_model,
                examples_path=settings.style_examples_path,
                cache_path=settings.style_cache_path,
            )
        )
    raise ValueError(
        f"LLM provider '{settings.llm_provider}' has no few-shot retriever adapter"
    )


def build_principle_retriever(settings: Settings) -> DialogueContextRetriever:
    if settings.llm_provider == "openai":
        from app.providers.openai_retrieval import OpenAIPrincipleRetriever

        return OpenAIPrincipleRetriever(
            client=_build_openai_client(settings),
            model=settings.embedding_model,
            documents_path=settings.principle_rag_path,
            cache_path=settings.principle_rag_cache_path,
            top_k=settings.principle_rag_top_k,
        )
    raise ValueError(
        f"LLM provider '{settings.llm_provider}' has no principle retriever adapter"
    )
