from __future__ import annotations

import hashlib
import logging
import secrets
import time
import uuid
from contextlib import asynccontextmanager
from functools import lru_cache

from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.chat import ChatService
from app.config import PROJECT_ROOT, get_settings
from app.core.experiment import (
    DeviceCookieSigner,
    ExperimentPhase,
    ExperimentState,
    ExperimentStore,
)
from app.core.llm import (
    LanguageModelConnectionError,
    LanguageModelRateLimitError,
    LanguageModelTimeoutError,
)
from app.core.rate_limit import RateLimitExceeded, SlidingWindowRateLimiter
from app.schemas import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    ExperimentStatusResponse,
    PublicConfig,
)
from app.simple_chat import SimpleGyaruChatService


logger = logging.getLogger(__name__)
settings = get_settings()
STATIC_DIR = PROJECT_ROOT / "app" / "static"
FIG_DIR = PROJECT_ROOT / "fig"
RUNTIME_ID = uuid.uuid4().hex
EXPERIMENT_DEVICE_COOKIE = "ririmero_experiment_device"
COOKIE_MAX_AGE_SECONDS = 31_536_000
device_secret = settings.experiment_device_secret or hashlib.sha256(
    (settings.openai_api_key or RUNTIME_ID).encode("utf-8")
).hexdigest()
device_cookie_signer = DeviceCookieSigner(device_secret)
experiment_store = ExperimentStore(settings.experiment_db_path)
chat_rate_limiter = SlidingWindowRateLimiter(
    limit=settings.chat_rate_limit,
    window_seconds=settings.chat_rate_window_seconds,
)


@lru_cache
def get_chat_service() -> ChatService:
    return ChatService(settings)


@lru_cache
def get_simple_chat_service() -> SimpleGyaruChatService:
    return SimpleGyaruChatService(settings)


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    if get_chat_service.cache_info().currsize:
        get_chat_service().close()
        get_chat_service.cache_clear()
    get_simple_chat_service.cache_clear()


app = FastAPI(title="Ririmero Experiment Chat", version="0.3.0", lifespan=lifespan)
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


@app.get("/api/experiment/status", response_model=ExperimentStatusResponse)
async def experiment_status(
    request: Request,
    response: Response,
) -> ExperimentStatusResponse:
    response.headers["Cache-Control"] = "no-store"
    device_id = _get_or_create_device(request, response)
    return _status_response(
        experiment_store.status(device_id, settings.experiment_phase_seconds)
    )


@app.post("/api/experiment/advance", response_model=ExperimentStatusResponse)
async def advance_experiment(
    request: Request,
    response: Response,
) -> ExperimentStatusResponse:
    device_id = _get_or_create_device(request, response)
    state = experiment_store.advance_to_full(
        device_id,
        settings.experiment_phase_seconds,
    )
    if state.phase is not ExperimentPhase.FULL:
        raise HTTPException(
            status_code=409,
            detail="前半の4分が終了してから後半へ進めます。",
        )
    return _status_response(state)


@app.get("/api/experiment/admin/export")
async def export_experiment_logs(
    admin_code: str | None = Header(default=None, alias="X-Admin-Code"),
) -> Response:
    _require_admin(admin_code)
    filename = time.strftime("ririmero-experiment-%Y%m%d-%H%M%S.csv")
    return Response(
        content="\ufeff" + experiment_store.export_csv(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post(
    "/api/experiment/admin/reset-current",
    response_model=ExperimentStatusResponse,
)
async def reset_current_experiment(
    request: Request,
    response: Response,
    admin_code: str | None = Header(default=None, alias="X-Admin-Code"),
) -> ExperimentStatusResponse:
    _require_admin(admin_code)
    device_id = _get_or_create_device(request, response)
    experiment_store.reset_device(device_id)
    return _status_response(
        experiment_store.status(device_id, settings.experiment_phase_seconds)
    )


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
    device_id = _get_or_create_device(request, response)
    try:
        chat_rate_limiter.acquire(_client_key(request, device_id))
    except RateLimitExceeded as exc:
        raise HTTPException(
            status_code=429,
            detail="送信が少し速すぎるみたい。少し待ってから試してね。",
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc

    state = experiment_store.start(device_id, settings.experiment_phase_seconds)
    if state.phase is ExperimentPhase.TRANSITION:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "experiment_transition",
                "message": "前半が終了しました。後半へ進んでください。",
            },
        )
    if state.phase is ExperimentPhase.COMPLETE:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "experiment_complete",
                "message": "8分間の実験は終了しました。",
            },
        )

    phase = state.phase
    history = experiment_store.history(
        state.experiment_id,
        phase,
        settings.chat_history_limit,
    )
    safety_id = hashlib.sha256(device_id.encode("utf-8")).hexdigest()
    effective_request = chat_request.model_copy(
        update={
            "user_id": safety_id,
            "conversation_id": f"{state.experiment_id}:{phase.value}",
            "history": [ChatMessage(**message) for message in history],
        }
    )
    try:
        if phase is ExperimentPhase.SIMPLE:
            chat_response = await get_simple_chat_service().reply(effective_request)
            condition = "simple_prompt"
        else:
            chat_response = await get_chat_service().reply(effective_request)
            condition = "full_dialogue_architecture"
    except LanguageModelRateLimitError as exc:
        raise HTTPException(
            status_code=429,
            detail="OpenAI側が混み合っています。30秒ほど待ってから送ってね。",
            headers={"Retry-After": "30"},
        ) from exc
    except LanguageModelTimeoutError as exc:
        raise HTTPException(
            status_code=504,
            detail="応答に時間がかかりすぎました。もう一度送ってみてね。",
        ) from exc
    except LanguageModelConnectionError as exc:
        raise HTTPException(
            status_code=503,
            detail="OpenAIに接続できませんでした。少し待ってから試してね。",
        ) from exc
    except Exception as exc:
        logger.exception("Chat request failed")
        raise HTTPException(
            status_code=502,
            detail="応答の生成に失敗しました。サーバーログを確認してください。",
        ) from exc

    experiment_store.append_turn(
        state.experiment_id,
        phase,
        chat_request.message,
        chat_response.reply,
        metadata={
            "condition": condition,
            "strategy": chat_response.strategy,
            "strategy_reason": chat_response.strategy_reason,
            "safety_level": chat_response.safety_level,
            "retrieved_examples": chat_response.retrieved_examples,
            "retrieved_principles": chat_response.retrieved_principles,
            "warnings": chat_response.warnings,
        },
    )
    current_state = experiment_store.status(
        device_id,
        settings.experiment_phase_seconds,
    )
    return chat_response.model_copy(
        update={
            "experiment_phase": current_state.phase.value,
            "experiment_remaining_seconds": current_state.remaining_seconds,
            "experiment_complete": (
                current_state.phase is ExperimentPhase.COMPLETE
            ),
        }
    )


def _status_response(state: ExperimentState) -> ExperimentStatusResponse:
    return ExperimentStatusResponse(
        experiment_id=state.experiment_id,
        phase=state.phase.value,
        started=state.started,
        remaining_seconds=state.remaining_seconds,
        phase_seconds=state.phase_seconds,
    )


def _client_key(request: Request, device_id: str) -> str:
    forwarded_for = request.headers.get("x-forwarded-for", "")
    address = forwarded_for.split(",", maxsplit=1)[0].strip()
    if not address and request.client:
        address = request.client.host
    identity = f"{address or 'unknown'}:{device_id}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _get_or_create_device(request: Request, response: Response) -> str:
    device_id = device_cookie_signer.verify(
        request.cookies.get(EXPERIMENT_DEVICE_COOKIE)
    )
    if device_id:
        return device_id
    device_id, token = device_cookie_signer.new_token()
    response.set_cookie(
        EXPERIMENT_DEVICE_COOKIE,
        token,
        max_age=COOKIE_MAX_AGE_SECONDS,
        httponly=True,
        secure=_uses_secure_cookies(request),
        samesite="lax",
    )
    return device_id


def _require_admin(admin_code: str | None) -> None:
    configured = settings.experiment_admin_code
    if not configured:
        raise HTTPException(
            status_code=503,
            detail="EXPERIMENT_ADMIN_CODE が設定されていません。",
        )
    if not admin_code or not secrets.compare_digest(admin_code, configured):
        raise HTTPException(status_code=401, detail="管理コードが違います。")


def _uses_secure_cookies(request: Request) -> bool:
    forwarded_proto = request.headers.get("x-forwarded-proto", "")
    return request.url.scheme == "https" or forwarded_proto == "https"
