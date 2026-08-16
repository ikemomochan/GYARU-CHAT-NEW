from dataclasses import replace
from types import SimpleNamespace

from fastapi.testclient import TestClient

import app.main as main
from app.core.experiment import DeviceCookieSigner, ExperimentStore
from app.core.llm import LanguageModelRateLimitError
from app.schemas import ChatResponse


class FakeClock:
    def __init__(self) -> None:
        self.value = 1_000.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class FakeChatService:
    def __init__(self, reply: str, strategy: str) -> None:
        self.reply_text = reply
        self.strategy = strategy
        self.requests = []
        self.closed = False

    async def reply(self, request) -> ChatResponse:
        self.requests.append(request)
        return ChatResponse(
            reply=self.reply_text,
            recalled_memories=0,
            retrieved_examples=0,
            strategy=self.strategy,
            strategy_reason="test reason",
            safety_level="NORMAL",
        )

    def close(self) -> None:
        self.closed = True


class RateLimitedChatService(FakeChatService):
    async def reply(self, _request):
        raise LanguageModelRateLimitError


class FakeServiceGetter:
    def __init__(self, service) -> None:
        self.service = service

    def __call__(self):
        return self.service

    def cache_info(self):
        return SimpleNamespace(currsize=1)

    def cache_clear(self) -> None:
        pass


def _payload(message: str = "こんにちは") -> dict:
    return {
        "message": message,
        "user_id": "browser-user",
        "conversation_id": "browser-conversation",
        "history": [],
    }


def _configure_experiment(monkeypatch, tmp_path):
    clock = FakeClock()
    store = ExperimentStore(tmp_path / "experiment.db", clock=clock)
    simple = FakeChatService("シンプル返答", "SIMPLE_PROMPT")
    full = FakeChatService("フル返答", "LISTEN")
    monkeypatch.setattr(main, "experiment_store", store)
    monkeypatch.setattr(
        main,
        "device_cookie_signer",
        DeviceCookieSigner("test-device-secret"),
    )
    monkeypatch.setattr(main, "get_simple_chat_service", FakeServiceGetter(simple))
    monkeypatch.setattr(main, "get_chat_service", FakeServiceGetter(full))
    monkeypatch.setattr(
        main,
        "settings",
        replace(
            main.settings,
            openai_api_key="test-key",
            experiment_phase_seconds=240,
            experiment_admin_code="admin-code",
        ),
    )
    main.chat_rate_limiter.reset()
    return clock, store, simple, full


def test_ui_and_public_config_are_available_without_api_key(monkeypatch) -> None:
    monkeypatch.setattr(
        main,
        "settings",
        replace(main.settings, openai_api_key="", reset_state_on_start=False),
    )
    main.get_chat_service.cache_clear()
    with TestClient(main.app) as client:
        index = client.get("/")
        config = client.get("/api/config")

    assert index.status_code == 200
    assert "りりめろ実験" in index.text
    assert "前半：シンプルなギャルAI" in index.text
    assert "後半を始める" in index.text
    assert "style.css?v=experiment-20260817" in index.text
    assert "app.js?v=experiment-20260817" in index.text
    assert "相談事が得意なAIだから" not in index.text
    assert "10回だけ" not in index.text
    assert config.status_code == 200
    assert config.json()["llm_provider"] == "openai"
    assert config.json()["api_key_configured"] is False


def test_mobile_ui_uses_timer_and_phase_switch_without_trial_limit() -> None:
    script = (main.STATIC_DIR / "app.js").read_text(encoding="utf-8")
    styles = (main.STATIC_DIR / "style.css").read_text(encoding="utf-8")

    assert 'fetch("/api/experiment/status"' in script
    assert 'fetch("/api/experiment/advance"' in script
    assert "window.setInterval(refreshExperimentStatus, 1000)" in script
    assert "resetPhaseHistory" in script
    assert "TRIAL_USED_KEY" not in script
    assert "NOTICE_ACCEPTED_KEY" not in script
    assert "trial-lock" not in styles
    assert 'url("/fig/UI-background.png")' in styles
    assert "height: var(--app-height, 100dvh)" in styles


def test_ui_background_image_is_served() -> None:
    with TestClient(main.app) as client:
        response = client.get("/fig/UI-background.png")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert len(response.content) > 1_000_000


def test_chat_explains_missing_api_key(monkeypatch) -> None:
    monkeypatch.setattr(main, "settings", replace(main.settings, openai_api_key=""))
    with TestClient(main.app) as client:
        response = client.post("/api/chat", json=_payload())

    assert response.status_code == 503
    assert "OPENAI_API_KEY" in response.json()["detail"]


def test_two_phase_experiment_clears_model_history_and_exports_logs(
    monkeypatch,
    tmp_path,
) -> None:
    clock, _, simple, full = _configure_experiment(monkeypatch, tmp_path)

    with TestClient(main.app, base_url="https://testserver") as client:
        waiting = client.get("/api/experiment/status")
        simple_reply = client.post("/api/chat", json=_payload("前半の発話"))

        clock.advance(241)
        transition = client.get("/api/experiment/status")
        blocked = client.post("/api/chat", json=_payload("境界の発話"))
        advanced = client.post("/api/experiment/advance")
        full_reply = client.post("/api/chat", json=_payload("後半の発話"))

        export = client.get(
            "/api/experiment/admin/export",
            headers={"X-Admin-Code": "admin-code"},
        )

        clock.advance(241)
        completed = client.get("/api/experiment/status")
        ended = client.post("/api/chat", json=_payload("終了後"))

    assert waiting.json()["phase"] == "WAITING"
    assert waiting.json()["remaining_seconds"] == 240
    assert simple_reply.status_code == 200
    assert simple_reply.json()["reply"] == "シンプル返答"
    assert simple.requests[0].history == []
    assert transition.json()["phase"] == "TRANSITION"
    assert blocked.status_code == 409
    assert advanced.json()["phase"] == "FULL"
    assert full_reply.status_code == 200
    assert full_reply.json()["reply"] == "フル返答"
    assert full.requests[0].history == []
    assert completed.json()["phase"] == "COMPLETE"
    assert ended.status_code == 403
    assert export.status_code == 200
    assert "前半の発話" in export.text
    assert "後半の発話" in export.text
    assert "simple_prompt" in export.text
    assert "full_dialogue_architecture" in export.text


def test_admin_export_rejects_wrong_code(monkeypatch, tmp_path) -> None:
    _configure_experiment(monkeypatch, tmp_path)
    with TestClient(main.app) as client:
        response = client.get(
            "/api/experiment/admin/export",
            headers={"X-Admin-Code": "wrong"},
        )

    assert response.status_code == 401


def test_openai_rate_limit_is_explained(monkeypatch, tmp_path) -> None:
    _configure_experiment(monkeypatch, tmp_path)
    service = RateLimitedChatService("", "SIMPLE_PROMPT")
    monkeypatch.setattr(main, "get_simple_chat_service", FakeServiceGetter(service))

    with TestClient(main.app) as client:
        response = client.post("/api/chat", json=_payload())

    assert response.status_code == 429
    assert response.headers["retry-after"] == "30"
    assert "OpenAI側" in response.json()["detail"]


def test_rate_limit_key_separates_devices_on_the_same_ip() -> None:
    request = SimpleNamespace(
        headers={"x-forwarded-for": "203.0.113.1"},
        client=SimpleNamespace(host="127.0.0.1"),
    )

    assert main._client_key(request, "phone") != main._client_key(request, "pc")
