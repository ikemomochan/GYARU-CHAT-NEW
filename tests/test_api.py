from dataclasses import replace
from types import SimpleNamespace

from fastapi.testclient import TestClient

import app.main as main
from app.core.llm import LanguageModelRateLimitError
from app.core.trial_access import TrialCookieSigner, TrialUsageStore
from app.schemas import ChatResponse


class FakeChatService:
    def __init__(self) -> None:
        self.reset_calls = []
        self.closed = False

    def reset_session(self, user_id: str, conversation_id: str) -> None:
        self.reset_calls.append((user_id, conversation_id))

    def close(self) -> None:
        self.closed = True

    async def reply(self, _request) -> ChatResponse:
        return ChatResponse(
            reply="返事",
            recalled_memories=0,
            retrieved_examples=0,
        )


class FakeServiceGetter:
    def __init__(self, service: FakeChatService) -> None:
        self.service = service

    def __call__(self) -> FakeChatService:
        return self.service

    def cache_info(self):
        return SimpleNamespace(currsize=1)

    def cache_clear(self) -> None:
        pass


class RateLimitedChatService(FakeChatService):
    async def reply(self, _request):
        raise LanguageModelRateLimitError


def test_ui_and_public_config_are_available_without_api_key(monkeypatch) -> None:
    monkeypatch.setattr(
        main,
        "settings",
        replace(
            main.settings,
            openai_api_key="",
            reset_state_on_start=False,
        ),
    )
    main.get_chat_service.cache_clear()
    with TestClient(main.app) as client:
        index = client.get("/")
        config = client.get("/api/config")

    assert index.status_code == 200
    assert "りりめろ" in index.text
    assert "あーし、おしゃべり系ギャルのりりめろ💖いっぱい話そー" in index.text
    assert "style.css?v=usage-notice-20260816" in index.text
    assert "app.js?v=usage-notice-20260816" in index.text
    assert "相談事が得意なAIだから" in index.text
    assert "体験版だから10回だけ入力できるよ" in index.text
    assert "確認したよ" in index.text
    assert "interactive-widget=resizes-content" in index.text
    assert config.status_code == 200
    assert config.json()["llm_provider"] == "openai"
    assert config.json()["strategy_model"] == "gpt-5.6-luna"
    assert config.json()["response_model"] == "gpt-5.6-luna"
    assert config.json()["tone_model"] == "gpt-5.6-luna"
    assert config.json()["rag_enabled"] is True
    assert config.json()["chat_model"] == "gpt-5.6-luna"
    assert config.json()["style_model"] == "gpt-5.6-luna"
    assert config.json()["runtime_id"]
    assert config.json()["api_key_configured"] is False


def test_ui_hides_model_chain_and_uses_mobile_background() -> None:
    script = (main.STATIC_DIR / "app.js").read_text(encoding="utf-8")
    styles = (main.STATIC_DIR / "style.css").read_text(encoding="utf-8")

    assert "strategy_model" not in script
    assert "response_model" not in script
    assert "tone_model" not in script
    assert "value = crypto.randomUUID()" not in script
    assert "function createClientId()" in script
    assert "REQUEST_TIMEOUT_MS = 90_000" in script
    assert "function syncVisualViewport()" in script
    assert 'window.visualViewport?.addEventListener("resize"' in script
    assert 'style.setProperty("--app-height"' in script
    assert "input.disabled = value" not in script
    assert 'fetch("/api/trial/status")' in script
    assert 'fetch("/api/debug/unlock"' in script
    assert 'TRIAL_USED_KEY = "ririmero-trial-used"' in script
    assert 'NOTICE_ACCEPTED_KEY = "ririmero-usage-notice"' in script
    assert "!noticeAccepted || !trialReady || trialLocked" in script
    assert 'form.classList.toggle("hidden", trialLocked)' in script
    assert "requestAnimationFrame(scrollMessagesToBottom)" in script
    assert "サーバーを再起動したので" not in script
    assert "あーし、おしゃべり系ギャルのりりめろ💖いっぱい話そー" in script
    assert 'url("/fig/UI-background.png")' in styles
    assert ".assistant .bubble" in styles
    assert "background: #cdfffc" in styles
    assert "background: #ffffff" in styles
    assert "backdrop-filter" not in styles
    assert "height: var(--app-height, 100dvh)" in styles
    assert "position: fixed" in styles
    assert "grid-row: 4" in styles


def test_ui_background_image_is_served() -> None:
    with TestClient(main.app) as client:
        response = client.get("/fig/UI-background.png")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert len(response.content) > 1_000_000


def test_chat_explains_missing_api_key(monkeypatch) -> None:
    monkeypatch.setattr(
        main,
        "settings",
        replace(
            main.settings,
            openai_api_key="",
            reset_state_on_start=False,
        ),
    )
    main.get_chat_service.cache_clear()
    with TestClient(main.app) as client:
        response = client.post(
            "/api/chat",
            json={
                "message": "こんにちは",
                "user_id": "test-user",
                "conversation_id": "test-conversation",
                "history": [],
            },
        )

    assert response.status_code == 503
    assert "OPENAI_API_KEY" in response.json()["detail"]


def test_session_reset_endpoint_clears_server_side_state(monkeypatch) -> None:
    service = FakeChatService()
    monkeypatch.setattr(main, "get_chat_service", FakeServiceGetter(service))

    with TestClient(main.app) as client:
        response = client.post(
            "/api/session/reset",
            json={
                "user_id": "test-user",
                "conversation_id": "test-conversation",
            },
        )

    assert response.status_code == 200
    assert service.reset_calls == [("test-user", "test-conversation")]


def test_openai_rate_limit_is_explained_and_retryable(monkeypatch) -> None:
    service = RateLimitedChatService()
    monkeypatch.setattr(main, "get_chat_service", FakeServiceGetter(service))
    monkeypatch.setattr(
        main,
        "settings",
        replace(main.settings, openai_api_key="test-key"),
    )
    main.chat_rate_limiter.reset()

    with TestClient(main.app) as client:
        response = client.post(
            "/api/chat",
            json={
                "message": "こんにちは",
                "user_id": "test-user",
                "conversation_id": "test-conversation",
                "history": [],
            },
        )

    assert response.status_code == 429
    assert response.headers["retry-after"] == "30"
    assert "OpenAI側" in response.json()["detail"]


def test_rate_limit_key_separates_clients_on_the_same_ip() -> None:
    request = SimpleNamespace(
        headers={"x-forwarded-for": "203.0.113.1"},
        client=SimpleNamespace(host="127.0.0.1"),
    )

    assert main._client_key(request, "phone") != main._client_key(request, "pc")


def test_trial_locks_after_limit_and_debug_code_unlocks(
    monkeypatch,
    tmp_path,
) -> None:
    service = FakeChatService()
    monkeypatch.setattr(main, "get_chat_service", FakeServiceGetter(service))
    monkeypatch.setattr(
        main,
        "settings",
        replace(
            main.settings,
            openai_api_key="test-key",
            trial_message_limit=2,
            debug_access_code="owner-code",
        ),
    )
    monkeypatch.setattr(
        main,
        "trial_usage_store",
        TrialUsageStore(tmp_path / "trial.db"),
    )
    monkeypatch.setattr(
        main,
        "trial_cookie_signer",
        TrialCookieSigner("test-signing-secret", 3600),
    )
    monkeypatch.setattr(
        main,
        "debug_cookie_signer",
        TrialCookieSigner("test-debug-secret", 3600),
    )
    main.chat_rate_limiter.reset()
    main.debug_unlock_rate_limiter.reset()

    payload = {
        "message": "こんにちは",
        "user_id": "test-user",
        "conversation_id": "test-conversation",
        "history": [],
    }
    with TestClient(main.app, base_url="https://testserver") as client:
        initial = client.get("/api/trial/status")
        first = client.post("/api/chat", json=payload)
        second = client.post("/api/chat", json=payload)
        blocked = client.post("/api/chat", json=payload)
        unlocked = client.post(
            "/api/debug/unlock",
            json={"access_code": "owner-code"},
        )
        unlimited = client.post("/api/chat", json=payload)

    assert initial.json()["remaining"] == 2
    assert first.json()["trial_remaining"] == 1
    assert second.json()["trial_remaining"] == 0
    assert second.json()["trial_locked"] is True
    assert blocked.status_code == 403
    assert blocked.json()["detail"]["code"] == "trial_limit_reached"
    assert unlocked.status_code == 200
    assert unlocked.json()["debug_unlimited"] is True
    assert unlimited.status_code == 200
    assert unlimited.json()["debug_unlimited"] is True
    assert unlimited.json()["trial_remaining"] is None
