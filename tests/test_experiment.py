from __future__ import annotations

import asyncio
import csv
from pathlib import Path

from app.schemas import ChatResponse
from scripts.run_mode_experiment import load_inputs, run_mode


class FakeChatService:
    def __init__(self) -> None:
        self.requests = []
        self.reset_count = 0
        self.closed = False

    async def reply(self, request):
        self.requests.append(request)
        return ChatResponse(
            reply=f"response-{len(self.requests)}",
            recalled_memories=0,
            retrieved_examples=0,
        )

    def reset_state(self) -> None:
        self.reset_count += 1

    def close(self) -> None:
        self.closed = True


def test_load_inputs_reads_first_non_empty_csv_cell(tmp_path: Path) -> None:
    input_path = tmp_path / "test.csv"
    input_path.write_text("1文目,\n,2文目\n\n", encoding="utf-8")

    assert load_inputs(input_path) == ["1文目", "2文目"]


def test_run_mode_resets_each_round_and_records_every_response(
    tmp_path: Path,
) -> None:
    service = FakeChatService()
    output_path = tmp_path / "simple.csv"

    errors = asyncio.run(
        run_mode(
            mode="simple",
            service=service,
            messages=["1文目", "2文目"],
            rounds=2,
            run_id="test-run",
            output_path=output_path,
        )
    )

    with output_path.open("r", encoding="utf-8-sig", newline="") as source:
        rows = list(csv.DictReader(source))

    assert errors == 0
    assert len(rows) == 4
    assert [row["round"] for row in rows] == ["1", "1", "2", "2"]
    assert [row["turn"] for row in rows] == ["1", "2", "1", "2"]
    assert [row["output"] for row in rows] == [
        "response-1",
        "response-2",
        "response-3",
        "response-4",
    ]
    assert len(service.requests[0].history) == 0
    assert len(service.requests[1].history) == 2
    assert len(service.requests[2].history) == 0
    assert len(service.requests[3].history) == 2
    assert service.reset_count == 3
    assert service.closed is True
