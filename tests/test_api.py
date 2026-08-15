from dataclasses import replace
from types import SimpleNamespace

from fastapi.testclient import TestClient

import app.main as main


class FakeChatService:
    def __init__(self) -> None:
        self.reset_calls = []
        self.closed = False

    def reset_session(self, user_id: str, conversation_id: str) -> None:
        self.reset_calls.append((user_id, conversation_id))

    def close(self) -> None:
        self.closed = True


class FakeServiceGetter:
    def __init__(self, service: FakeChatService) -> None:
        self.service = service

    def __call__(self) -> FakeChatService:
        return self.service

    def cache_info(self):
        return SimpleNamespace(currsize=1)

    def cache_clear(self) -> None:
        pass


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
    assert "style.css?v=mobile-solid-20260815" in index.text
    assert "app.js?v=mobile-http-20260815" in index.text
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
    assert "サーバーを再起動したので" not in script
    assert "あーし、おしゃべり系ギャルのりりめろ💖いっぱい話そー" in script
    assert 'url("/fig/UI-background.png")' in styles
    assert ".assistant .bubble" in styles
    assert "background: #cdfffc" in styles
    assert "background: #ffffff" in styles
    assert "backdrop-filter" not in styles


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
