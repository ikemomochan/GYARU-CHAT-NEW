from dataclasses import replace

from fastapi.testclient import TestClient

import app.main as main


def test_ui_and_public_config_are_available_without_api_key(monkeypatch) -> None:
    monkeypatch.setattr(
        main,
        "settings",
        replace(
            main.settings,
            mode="Mem0",
            openai_api_key="",
            reset_state_on_start=False,
        ),
    )
    main.get_chat_service.cache_clear()
    with TestClient(main.app) as client:
        index = client.get("/")
        config = client.get("/api/config")

    assert index.status_code == 200
    assert "Mem0 Chat" in index.text
    assert config.status_code == 200
    assert config.json()["mode"] == "Mem0"
    assert config.json()["base_model_provider"] == "openai"
    assert config.json()["base_model"] == "gpt-5.6-sol"
    assert config.json()["style_model"] == "gpt-5.6-luna"
    assert config.json()["runtime_id"]
    assert config.json()["api_key_configured"] is False
    assert config.json()["missing_api_keys"] == ["OPENAI_API_KEY"]


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


def test_chat_explains_missing_anthropic_api_key(monkeypatch) -> None:
    monkeypatch.setattr(
        main,
        "settings",
        replace(
            main.settings,
            openai_api_key="test-openai-key",
            anthropic_api_key="",
            base_model_provider="anthropic",
            base_model="claude-sonnet-5",
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
    assert "ANTHROPIC_API_KEY" in response.json()["detail"]
