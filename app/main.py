from __future__ import annotations

import hashlib
import logging
import secrets
import time
import uuid
from contextlib import asynccontextmanager
from functools import lru_cache

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.chat import ChatService
from app.config import PROJECT_ROOT, get_settings
from app.core.llm import (
    LanguageModelConnectionError,
    LanguageModelRateLimitError,
    LanguageModelTimeoutError,
)
from app.core.rate_limit import RateLimitExceeded, SlidingWindowRateLimiter
from app.core.trial_access import (
    TrialCookieSigner,
    TrialLimitExceeded,
    TrialUsage,
    TrialUsageStore,
)
from app.schemas import (
    ChatRequest,
    ChatResponse,
    DebugUnlockRequest,
    PublicConfig,
    SessionResetRequest,
    TrialStatus,
)


logger = logging.getLogger(__name__)
settings = get_settings()
STATIC_DIR = PROJECT_ROOT / "app" / "static"
FIG_DIR = PROJECT_ROOT / "fig"
RUNTIME_ID = uuid.uuid4().hex
TRIAL_DEVICE_COOKIE = "ririmero_trial_device"
DEBUG_ACCESS_COOKIE = "ririmero_debug_access"
COOKIE_MAX_AGE_SECONDS = 31_536_000
signing_secret = settings.trial_signing_secret or hashlib.sha256(
    (settings.openai_api_key or RUNTIME_ID).encode("utf-8")
).hexdigest()
trial_cookie_signer = TrialCookieSigner(
    signing_secret,
    debug_ttl_seconds=settings.debug_token_ttl_seconds,
)
debug_cookie_signer = TrialCookieSigner(
    settings.debug_token_secret or signing_secret,
    debug_ttl_seconds=settings.debug_token_ttl_seconds,
)
trial_usage_store = TrialUsageStore(settings.trial_db_path)
chat_rate_limiter = SlidingWindowRateLimiter(
    limit=settings.chat_rate_limit,
    window_seconds=settings.chat_rate_window_seconds,
)
debug_unlock_rate_limiter = SlidingWindowRateLimiter(
    limit=5,
    window_seconds=300,
)


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


@app.get("/api/trial/status", response_model=TrialStatus)
async def trial_status(request: Request, response: Response) -> TrialStatus:
    response.headers["Cache-Control"] = "no-store"
    device_id = _get_or_create_device(request, response)
    return _build_trial_status(request, device_id)


@app.post("/api/debug/unlock", response_model=TrialStatus)
async def debug_unlock(
    request: Request,
    response: Response,
    unlock_request: DebugUnlockRequest,
) -> TrialStatus:
    try:
        debug_unlock_rate_limiter.acquire(_client_key(request, "debug-unlock"))
    except RateLimitExceeded as exc:
        raise HTTPException(
            status_code=429,
            detail="試行回数が多すぎます。少し待ってから試してください。",
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc
    if not settings.debug_access_code:
        raise HTTPException(
            status_code=503,
            detail="実装者用コードがサーバーに設定されていません。",
        )
    if not secrets.compare_digest(
        unlock_request.access_code,
        settings.debug_access_code,
    ):
        raise HTTPException(status_code=401, detail="コードが違います。")

    device_id = _get_or_create_device(request, response)
    debug_token, expires_at = debug_cookie_signer.new_debug_token(device_id)
    response.set_cookie(
        DEBUG_ACCESS_COOKIE,
        debug_token,
        max_age=max(1, expires_at - int(time.time())),
        httponly=True,
        secure=_uses_secure_cookies(request),
        samesite="strict",
    )
    return _build_trial_status(request, device_id, debug_unlimited=True)


@app.post("/api/chat", response_model=ChatResponse)
async def chat(
    request: Request,
    response: Response,
    chat_request: ChatRequest,
) -> ChatResponse:
    if not settings.api_key_configured:
        raise HTTPException(
            status_code=503,
            detail=".env の OPENAI_API_KEY を設定してください。",
        )
    try:
        chat_rate_limiter.acquire(_client_key(request, chat_request.user_id))
    except RateLimitExceeded as exc:
        raise HTTPException(
            status_code=429,
            detail="送信が少し速すぎるみたい。少し待ってから試してね。",
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc
    device_id = _get_or_create_device(request, response)
    debug_unlimited = _has_debug_access(request, device_id)
    usage: TrialUsage | None = None
    if not debug_unlimited:
        try:
            usage = trial_usage_store.consume(
                device_id,
                settings.trial_message_limit,
            )
        except TrialLimitExceeded as exc:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "trial_limit_reached",
                    "message": (
                        f"体験版の{settings.trial_message_limit}回分を"
                        "使い切りました。"
                    ),
                },
            ) from exc
    try:
        chat_response = await get_chat_service().reply(chat_request)
    except LanguageModelRateLimitError as exc:
        _refund_trial(device_id, debug_unlimited)
        raise HTTPException(
            status_code=429,
            detail="OpenAI側が混み合っています。30秒ほど待ってから送ってね。",
            headers={"Retry-After": "30"},
        ) from exc
    except LanguageModelTimeoutError as exc:
        _refund_trial(device_id, debug_unlimited)
        raise HTTPException(
            status_code=504,
            detail="応答に時間がかかりすぎました。もう一度送ってみてね。",
        ) from exc
    except LanguageModelConnectionError as exc:
        _refund_trial(device_id, debug_unlimited)
        raise HTTPException(
            status_code=503,
            detail="OpenAIに接続できませんでした。少し待ってから試してね。",
        ) from exc
    except Exception as exc:
        _refund_trial(device_id, debug_unlimited)
        logger.exception("Chat request failed")
        raise HTTPException(
            status_code=502,
            detail="応答の生成に失敗しました。サーバーログを確認してください。",
        ) from exc
    return chat_response.model_copy(
        update={
            "trial_remaining": usage.remaining if usage else None,
            "trial_locked": usage.locked if usage else False,
            "debug_unlimited": debug_unlimited,
        }
    )


def _client_key(request: Request, user_id: str) -> str:
    forwarded_for = request.headers.get("x-forwarded-for", "")
    address = forwarded_for.split(",", maxsplit=1)[0].strip()
    if not address and request.client:
        address = request.client.host
    identity = f"{address or 'unknown'}:{user_id}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _get_or_create_device(request: Request, response: Response) -> str:
    device_id = trial_cookie_signer.verify_device_token(
        request.cookies.get(TRIAL_DEVICE_COOKIE)
    )
    if device_id:
        return device_id
    device_id, token = trial_cookie_signer.new_device_token()
    response.set_cookie(
        TRIAL_DEVICE_COOKIE,
        token,
        max_age=COOKIE_MAX_AGE_SECONDS,
        httponly=True,
        secure=_uses_secure_cookies(request),
        samesite="lax",
    )
    return device_id


def _has_debug_access(request: Request, device_id: str) -> bool:
    return debug_cookie_signer.verify_debug_token(
        request.cookies.get(DEBUG_ACCESS_COOKIE),
        device_id,
    )


def _build_trial_status(
    request: Request,
    device_id: str,
    *,
    debug_unlimited: bool | None = None,
) -> TrialStatus:
    usage = trial_usage_store.status(device_id, settings.trial_message_limit)
    if debug_unlimited is None:
        debug_unlimited = _has_debug_access(request, device_id)
    return TrialStatus(
        limit=usage.limit,
        used=usage.used,
        remaining=usage.remaining,
        locked=usage.locked and not debug_unlimited,
        debug_unlimited=debug_unlimited,
    )


def _refund_trial(device_id: str, debug_unlimited: bool) -> None:
    if not debug_unlimited:
        trial_usage_store.refund(device_id)


def _uses_secure_cookies(request: Request) -> bool:
    forwarded_proto = request.headers.get("x-forwarded-proto", "")
    return request.url.scheme == "https" or forwarded_proto == "https"
