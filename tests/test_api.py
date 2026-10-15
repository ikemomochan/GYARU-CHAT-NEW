from dataclasses import replace
from types import SimpleNamespace

from fastapi.testclient import TestClient

import app.main as main
from app.core.chat_log import ChatLogStore
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
    def __init__(self, reply: str = "フル返答") -> None:
        self.reply_text = reply
        self.requests = []
        self.closed = False

    async def reply(self, request) -> ChatResponse:
        self.requests.append(request)
        return ChatResponse(
            reply=self.reply_text,
            recalled_memories=0,
            retrieved_examples=0,
            strategy="LISTEN",
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


def _payload(message: str = "こんにちは", conversation_id: str = "conversation-1") -> dict:
    return {
        "message": message,
        "user_id": "browser-user",
        "conversation_id": conversation_id,
        "history": [],
    }


def _configure_chat(monkeypatch, tmp_path):
    clock = FakeClock()
    store = ChatLogStore(tmp_path / "chat.db", clock=clock)
    legacy_store = ExperimentStore(tmp_path / "experiment.db", clock=clock)
    service = FakeChatService()
    monkeypatch.setattr(main, "chat_log_store", store)
    monkeypatch.setattr(main, "experiment_store", legacy_store)
    monkeypatch.setattr(
        main,
        "device_cookie_signer",
        DeviceCookieSigner("test-device-secret"),
    )
    monkeypatch.setattr(main, "get_chat_service", FakeServiceGetter(service))
    monkeypatch.setattr(
        main,
        "settings",
        replace(
            main.settings,
            openai_api_key="test-key",
            chat_admin_code="admin-code",
        ),
    )
    main.chat_rate_limiter.reset()
    return clock, store, service


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
    assert "Ririmero" in index.text
    assert "時間制限なしで話せます" not in index.text
    assert "会話内容はこのサーバーに保存されます" not in index.text
    assert "前半" not in index.text
    assert "07:00" not in index.text
    assert "style.css?v=english-ui-20260906" in index.text
    assert "app.js?v=english-ui-20260906" in index.text
    assert config.status_code == 200
    assert config.json()["llm_provider"] == "openai"
    assert config.json()["api_key_configured"] is False


def test_mobile_ui_has_no_experiment_or_trial_limit() -> None:
    script = (main.STATIC_DIR / "app.js").read_text(encoding="utf-8")
    styles = (main.STATIC_DIR / "style.css").read_text(encoding="utf-8")

    assert 'fetch("/api/experiment/status"' not in script
    assert 'fetch("/api/experiment/advance"' not in script
    assert "setInterval" not in script
    assert "TRIAL_USED_KEY" not in script
    assert "new-chat-button" in script
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


def test_unlimited_chat_uses_full_service_server_history_and_exports_logs(
    monkeypatch,
    tmp_path,
) -> None:
    _, _, service = _configure_chat(monkeypatch, tmp_path)

    with TestClient(main.app, base_url="https://testserver") as client:
        first = client.post("/api/chat", json=_payload("最初の発話"))
        second = client.post("/api/chat", json=_payload("次の発話"))
        export = client.get(
            "/api/admin/export",
            headers={"X-Admin-Code": "admin-code"},
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["reply"] == "フル返答"
    assert service.requests[0].history == []
    assert [message.model_dump() for message in service.requests[1].history] == [
        {"role": "user", "content": "最初の発話"},
        {"role": "assistant", "content": "フル返答"},
    ]
    assert export.status_code == 200
    assert "最初の発話" in export.text
    assert "次の発話" in export.text
    assert "full_dialogue_architecture" in export.text


def test_conversation_ids_have_separate_server_histories(monkeypatch, tmp_path) -> None:
    _, _, service = _configure_chat(monkeypatch, tmp_path)

    with TestClient(main.app) as client:
        client.post("/api/chat", json=_payload("会話A", "conversation-a"))
        client.post("/api/chat", json=_payload("会話B", "conversation-b"))

    assert service.requests[0].history == []
    assert service.requests[1].history == []


def test_admin_export_rejects_wrong_code(monkeypatch, tmp_path) -> None:
    _configure_chat(monkeypatch, tmp_path)
    with TestClient(main.app) as client:
        response = client.get(
            "/api/admin/export",
            headers={"X-Admin-Code": "wrong"},
        )

    assert response.status_code == 401


def test_legacy_experiment_export_remains_available(monkeypatch, tmp_path) -> None:
    _, _, _ = _configure_chat(monkeypatch, tmp_path)
    with TestClient(main.app) as client:
        response = client.get(
            "/api/experiment/admin/export",
            headers={"X-Admin-Code": "admin-code"},
        )

    assert response.status_code == 200
    assert "experiment_id" in response.text


def test_openai_rate_limit_is_explained(monkeypatch, tmp_path) -> None:
    _configure_chat(monkeypatch, tmp_path)
    service = RateLimitedChatService()
    monkeypatch.setattr(main, "get_chat_service", FakeServiceGetter(service))

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
