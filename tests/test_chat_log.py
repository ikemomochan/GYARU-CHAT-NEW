import csv
import io
import json
from pathlib import Path

from app.core.chat_log import ChatLogStore


def test_append_history_and_export(tmp_path: Path) -> None:
    store = ChatLogStore(tmp_path / "chat.db", clock=lambda: 1234.5)

    store.append_turn(
        "device-1",
        "user-1",
        "conversation-1",
        "相談したい",
        "どしたん？",
        {"strategy": "LISTEN"},
    )

    assert store.history("device-1", "conversation-1", 12) == [
        {"role": "user", "content": "相談したい"},
        {"role": "assistant", "content": "どしたん？"},
    ]
    rows = list(csv.DictReader(io.StringIO(store.export_csv())))
    assert len(rows) == 2
    assert rows[0]["device_id"] == "device-1"
    assert rows[0]["content"] == "相談したい"
    assert json.loads(rows[1]["metadata_json"])["strategy"] == "LISTEN"


def test_history_is_scoped_by_device_and_conversation(tmp_path: Path) -> None:
    store = ChatLogStore(tmp_path / "chat.db")
    store.append_turn("device-a", "user-a", "same-id", "A", "A返答")
    store.append_turn("device-b", "user-b", "same-id", "B", "B返答")

    assert store.history("device-a", "same-id", 12)[0]["content"] == "A"
    assert store.history("device-b", "same-id", 12)[0]["content"] == "B"


def test_csv_export_neutralizes_spreadsheet_formulas(tmp_path: Path) -> None:
    store = ChatLogStore(tmp_path / "chat.db")
    store.append_turn("device", "user", "conversation", "=1+1", "+cmd")

    rows = list(csv.DictReader(io.StringIO(store.export_csv())))
    assert rows[0]["content"] == "'=1+1"
    assert rows[1]["content"] == "'+cmd"
