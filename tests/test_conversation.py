from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from app.config import get_settings
from app.conversation import ConversationService


class FakeResponses:
    def __init__(self) -> None:
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(output_text="- 猫について相談中\n- 次は名前を決める")


def test_rolling_summary_is_persisted(tmp_path: Path) -> None:
    responses = FakeResponses()
    client = SimpleNamespace(responses=responses)
    settings = replace(
        get_settings(),
        conversation_db_path=tmp_path / "conversations.db",
        summary_trigger_messages=2,
    )
    service = ConversationService(settings, client)

    updated = service.record_and_maybe_summarize(
        "user-1",
        "conversation-1",
        "猫を飼いたい",
        "どんな猫がいい？",
    )

    assert updated is True
    assert service.get_summary("user-1", "conversation-1").startswith("- 猫")
    assert len(responses.calls) == 1


def test_summary_waits_until_threshold(tmp_path: Path) -> None:
    responses = FakeResponses()
    client = SimpleNamespace(responses=responses)
    settings = replace(
        get_settings(),
        conversation_db_path=tmp_path / "conversations.db",
        summary_trigger_messages=4,
    )
    service = ConversationService(settings, client)

    updated = service.record_and_maybe_summarize(
        "user-1",
        "conversation-1",
        "こんにちは",
        "こんにちは！",
    )

    assert updated is False
    assert service.get_summary("user-1", "conversation-1") == ""
    assert responses.calls == []


def test_reset_deletes_messages_and_summaries(tmp_path: Path) -> None:
    responses = FakeResponses()
    client = SimpleNamespace(responses=responses)
    settings = replace(
        get_settings(),
        conversation_db_path=tmp_path / "conversations.db",
        summary_trigger_messages=2,
    )
    service = ConversationService(settings, client)
    service.record_and_maybe_summarize(
        "user-1", "conversation-1", "猫を飼いたい", "いいね"
    )

    service.reset()

    assert service.get_summary("user-1", "conversation-1") == ""
    _, _, pending = service._summary_state("user-1", "conversation-1")
    assert pending == []
