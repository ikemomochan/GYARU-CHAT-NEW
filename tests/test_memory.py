from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

from app.config import get_settings
from app.memory import (
    MemoryAction,
    MemoryExtraction,
    MemoryReconciliation,
    MemoryService,
)


class FakeParsedResponses:
    def __init__(self) -> None:
        self.calls = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs["text_format"] is MemoryExtraction:
            parsed = MemoryExtraction(facts=["ユーザーは紅茶が好き"])
        else:
            parsed = MemoryReconciliation(
                actions=[MemoryAction(event="ADD", text="ユーザーは紅茶が好き")]
            )
        return SimpleNamespace(output_parsed=parsed)


class FakeMem0:
    def __init__(self) -> None:
        self.added = []
        self.updated = []
        self.deleted = []

    def search(self, **kwargs):
        return {"results": []}

    def add(self, text, **kwargs):
        self.added.append((text, kwargs))

    def update(self, memory_id, **kwargs):
        self.updated.append((memory_id, kwargs))

    def delete(self, memory_id):
        self.deleted.append(memory_id)


def test_reconciliation_pipeline_adds_raw_mem0_memory() -> None:
    responses = FakeParsedResponses()
    client = SimpleNamespace(responses=responses)
    service = MemoryService(
        replace(get_settings(), openai_api_key="test-key"), client
    )
    fake_mem0 = FakeMem0()
    service._memory = fake_mem0

    applied = service.reconcile_conversation(
        "紅茶が好き",
        "覚えておくね",
        "user-1",
        "conversation-1",
    )

    assert applied == 1
    assert fake_mem0.added[0][0] == "ユーザーは紅茶が好き"
    assert fake_mem0.added[0][1]["infer"] is False
    assert len(responses.calls) == 2


def test_apply_plan_restricts_updates_and_deletes_to_retrieved_ids() -> None:
    client = SimpleNamespace(responses=FakeParsedResponses())
    service = MemoryService(
        replace(get_settings(), openai_api_key="test-key"), client
    )
    fake_mem0 = FakeMem0()
    service._memory = fake_mem0
    plan = MemoryReconciliation(
        actions=[
            MemoryAction(event="UPDATE", memory_id="known", text="新しい情報"),
            MemoryAction(event="DELETE", memory_id="unknown"),
            MemoryAction(event="ADD", text="追加情報"),
        ]
    )

    applied = service._apply_plan(
        plan,
        [{"id": "known", "memory": "古い情報"}],
        "user-1",
        "conversation-1",
    )

    assert applied == 2
    assert fake_mem0.updated[0][0] == "known"
    assert fake_mem0.deleted == []
    assert fake_mem0.added[0][0] == "追加情報"
