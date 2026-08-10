from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager
from dataclasses import replace
from functools import lru_cache

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.chat import ChatService
from app.config import PROJECT_ROOT, get_settings
from app.schemas import ChatRequest, ChatResponse, PublicConfig


logger = logging.getLogger(__name__)
settings = get_settings()
STATIC_DIR = PROJECT_ROOT / "app" / "static"
RUNTIME_ID = uuid.uuid4().hex

@lru_cache
def get_chat_service() -> ChatService:
    return ChatService(settings)


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.mode == "Mem0" and settings.reset_state_on_start:
        if settings.api_key_configured:
            get_chat_service().reset_state()
        else:
            reset_settings = replace(
                settings, openai_api_key="reset-only-placeholder"
            )
            reset_service = ChatService(reset_settings)
            try:
                reset_service.reset_state()
            finally:
                reset_service.close()
    yield
    if get_chat_service.cache_info().currsize:
        get_chat_service().close()
        get_chat_service.cache_clear()


app = FastAPI(title="Mem0 + RAG Chat", version="0.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/config", response_model=PublicConfig)
async def public_config() -> PublicConfig:
    return PublicConfig(
        runtime_id=RUNTIME_ID,
        mode=settings.mode,
        reset_state_on_start=(
            settings.reset_state_on_start and settings.mode == "Mem0"
        ),
        base_model_provider=settings.base_model_provider,
        base_model=settings.base_model,
        style_model=settings.style_model,
        memory_model=settings.memory_model,
        summary_model=settings.summary_model,
        embedding_model=settings.embedding_model,
        rag_top_k=settings.rag_top_k,
        memory_top_k=settings.memory_top_k,
        api_key_configured=settings.api_key_configured,
        missing_api_keys=list(settings.missing_api_keys),
    )


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    if not settings.api_key_configured:
        missing_keys = ", ".join(settings.missing_api_keys)
        raise HTTPException(
            status_code=503,
            detail=f".env の {missing_keys} を設定してください。",
        )
    try:
        return await get_chat_service().reply(request)
    except Exception as exc:
        logger.exception("Chat request failed")
        raise HTTPException(
            status_code=502,
            detail="応答の生成に失敗しました。サーバーログを確認してください。",
        ) from exc
