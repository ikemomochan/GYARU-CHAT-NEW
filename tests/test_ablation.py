from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from app.ablation import load_user_inputs, run_ablation
from app.config import get_settings
from app.dialogue_prompts.response_prompt import COMMON_RESPONSE_PROMPT
from app.schemas import ChatResponse


class FakeChatService:
    def __init__(self) -> None:
        self.requests = []
        self.reset_calls = []

    async def reply(self, request):
        self.requests.append(request)
        return ChatResponse(
            reply=f"応答{len(self.requests)}",
            recalled_memories=0,
            retrieved_examples=2,
            retrieved_principles=1,
            strategy="LISTEN" if len(self.requests) % 2 else "ADVICE",
            strategy_reason="テスト選択",
            safety_level="NORMAL",
        )

    def reset_session(self, user_id: str, conversation_id: str) -> None:
        self.reset_calls.append((user_id, conversation_id))


def test_load_user_inputs_requires_ten_nonblank_messages(tmp_path) -> None:
    path = tmp_path / "inputs.json"
    path.write_text(
        json.dumps({"messages": [f"入力{i}" for i in range(1, 11)]}),
        encoding="utf-8",
    )

    assert load_user_inputs(path) == [f"入力{i}" for i in range(1, 11)]

    path.write_text(json.dumps({"messages": ["入力"] * 9}), encoding="utf-8")
    with pytest.raises(ValueError, match="ちょうど10件"):
        load_user_inputs(path)

    path.write_text(
        json.dumps({"messages": ["入力"] * 9 + [""]}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="10件目が空"):
        load_user_inputs(path)


def test_run_ablation_logs_all_rounds_and_resets_history(tmp_path) -> None:
    service = FakeChatService()
    settings = replace(get_settings(), chat_history_limit=12)
    messages = [f"固定入力{i}" for i in range(1, 11)]
    now = datetime(2026, 10, 15, 12, 34, 56, tzinfo=timezone.utc)

    count = asyncio.run(
        run_ablation(
            service,
            settings,
            messages,
            tmp_path,
            rounds=2,
            progress=None,
            clock=lambda: now,
        )
    )

    assert count == 20
    assert len(service.requests) == 20
    assert service.requests[0].history == []
    assert service.requests[10].history == []
    assert len(service.requests[9].history) == 12
    assert len(service.reset_calls) == 2

    conversation_records = [
        json.loads(line)
        for line in (tmp_path / "conversations.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert len(conversation_records) == 20
    assert conversation_records[0]["round"] == 1
    assert conversation_records[10]["round"] == 2
    assert conversation_records[1]["selected_strategy"] == "ADVICE"
    assert conversation_records[10]["history_before"] == []

    response_records = [
        json.loads(line)
        for line in (tmp_path / "responses.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert [record["response"] for record in response_records[:2]] == [
        "応答1",
        "応答2",
    ]

    metadata = json.loads(
        (tmp_path / "run_metadata.json").read_text(encoding="utf-8")
    )
    assert metadata["status"] == "completed"
    assert metadata["expected_responses"] == 20
    assert metadata["completed_responses"] == 20
    assert metadata["models"]["embedding"] == "text-embedding-3-small"
    assert (
        tmp_path / "common_response_prompt.txt"
    ).read_text(encoding="utf-8") == COMMON_RESPONSE_PROMPT
    strategy_prompts = json.loads(
        (tmp_path / "strategy_response_prompts.json").read_text(
            encoding="utf-8"
        )
    )
    assert set(strategy_prompts) == {"LISTEN", "ADVICE", "SYMPATHY"}


def test_run_ablation_keeps_partial_logs_on_failure(tmp_path) -> None:
    class FailingService(FakeChatService):
        async def reply(self, request):
            if len(self.requests) == 1:
                raise RuntimeError("API failed")
            return await super().reply(request)

    service = FailingService()
    messages = [f"固定入力{i}" for i in range(1, 11)]

    with pytest.raises(RuntimeError, match="API failed"):
        asyncio.run(
            run_ablation(
                service,
                get_settings(),
                messages,
                tmp_path,
                progress=None,
            )
        )

    metadata = json.loads(
        (tmp_path / "run_metadata.json").read_text(encoding="utf-8")
    )
    assert metadata["status"] == "failed"
    assert metadata["completed_responses"] == 1
    assert (tmp_path / "errors.jsonl").exists()
