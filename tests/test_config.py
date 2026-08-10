from dataclasses import replace

import pytest

from app.config import get_settings


@pytest.mark.parametrize(
    ("raw_mode", "expected_mode"),
    [("simple", "simple"), ("prompt", "prompt"), ("Mem0", "Mem0")],
)
def test_mode_is_loaded_from_environment(
    monkeypatch,
    raw_mode: str,
    expected_mode: str,
) -> None:
    monkeypatch.setenv("MODE", raw_mode)
    get_settings.cache_clear()
    try:
        assert get_settings().mode == expected_mode
    finally:
        get_settings.cache_clear()


def test_invalid_mode_is_rejected(monkeypatch) -> None:
    monkeypatch.setenv("MODE", "unknown")
    get_settings.cache_clear()
    try:
        with pytest.raises(ValueError, match="MODE must be one of"):
            get_settings()
    finally:
        get_settings.cache_clear()


def test_prompt_only_anthropic_does_not_require_openai_key() -> None:
    settings = replace(
        get_settings(),
        mode="prompt",
        base_model_provider="anthropic",
        openai_api_key="",
        anthropic_api_key="test-anthropic-key",
    )

    assert settings.missing_api_keys == ()
