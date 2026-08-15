from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager
from functools import lru_cache

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.chat import ChatService
from app.config import PROJECT_ROOT, get_settings
from app.schemas import (
    ChatRequest,
    ChatResponse,
    PublicConfig,
    SessionResetRequest,
)


logger = logging.getLogger(__name__)
settings = get_settings()
STATIC_DIR = PROJECT_ROOT / "app" / "static"
FIG_DIR = PROJECT_ROOT / "fig"
RUNTIME_ID = uuid.uuid4().hex

@lru_cache
def get_chat_service() -> ChatService:
    return ChatService(settings)


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    if get_chat_service.cache_info().currsize:
        get_chat_service().close()
        get_chat_service.cache_clear()


app = FastAPI(title="Ririmero Dialogue Chat", version="0.2.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/fig", StaticFiles(directory=FIG_DIR), name="fig")


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
        reset_state_on_start=settings.reset_state_on_start,
        llm_provider=settings.llm_provider,
        strategy_model=settings.strategy_model,
        response_model=settings.response_model,
        tone_model=settings.tone_model,
        rag_enabled=True,
        chat_model=settings.chat_model,
        style_model=settings.style_model,
        memory_model=settings.memory_model,
        summary_model=settings.summary_model,
        embedding_model=settings.embedding_model,
        rag_top_k=settings.rag_top_k,
        memory_top_k=settings.memory_top_k,
        api_key_configured=settings.api_key_configured,
    )


@app.post("/api/session/reset")
async def reset_session(request: SessionResetRequest) -> dict[str, str]:
    if get_chat_service.cache_info().currsize:
        get_chat_service().reset_session(
            request.user_id,
            request.conversation_id,
        )
    return {"status": "ok"}


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    if not settings.api_key_configured:
        raise HTTPException(
            status_code=503,
            detail=".env の OPENAI_API_KEY を設定してください。",
        )
    try:
        return await get_chat_service().reply(request)
    except Exception as exc:
        logger.exception("Chat request failed")
        raise HTTPException(
            status_code=502,
            detail="応答の生成に失敗しました。サーバーログを確認してください。",
        ) from exc
