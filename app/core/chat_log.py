from __future__ import annotations

import csv
import io
import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any


class ChatLogStore:
    """Persist successful chat turns for later administrative review."""

    def __init__(self, path: Path, clock=time.time) -> None:
        self.path = path
        self.clock = clock
        self._lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def append_turn(
        self,
        device_id: str,
        user_id: str,
        conversation_id: str,
        user_message: str,
        assistant_message: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        now = self.clock()
        metadata_json = json.dumps(
            metadata or {}, ensure_ascii=False, separators=(",", ":")
        )
        with self._lock, self._connect() as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute(
                """
                INSERT INTO chat_conversations
                    (device_id, conversation_id, user_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(device_id, conversation_id) DO UPDATE SET
                    user_id = excluded.user_id,
                    updated_at = excluded.updated_at
                """,
                (device_id, conversation_id, user_id, now, now),
            )
            connection.executemany(
                """
                INSERT INTO chat_messages
                    (device_id, conversation_id, role, content, created_at,
                     metadata_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        device_id,
                        conversation_id,
                        "user",
                        user_message,
                        now,
                        "{}",
                    ),
                    (
                        device_id,
                        conversation_id,
                        "assistant",
                        assistant_message,
                        now,
                        metadata_json,
                    ),
                ],
            )

    def history(
        self,
        device_id: str,
        conversation_id: str,
        limit: int,
    ) -> list[dict[str, str]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT role, content
                FROM chat_messages
                WHERE device_id = ? AND conversation_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (device_id, conversation_id, limit),
            ).fetchall()
        return [
            {"role": role, "content": content}
            for role, content in reversed(rows)
        ]

    def export_csv(self) -> str:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    c.device_id,
                    c.conversation_id,
                    c.user_id,
                    c.created_at,
                    c.updated_at,
                    m.id,
                    m.role,
                    m.content,
                    m.created_at,
                    m.metadata_json
                FROM chat_conversations c
                LEFT JOIN chat_messages m
                    ON m.device_id = c.device_id
                    AND m.conversation_id = c.conversation_id
                ORDER BY c.created_at, m.id
                """
            ).fetchall()
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(
            [
                "device_id",
                "conversation_id",
                "user_id",
                "conversation_created_at",
                "conversation_updated_at",
                "message_id",
                "role",
                "content",
                "message_created_at",
                "metadata_json",
            ]
        )
        writer.writerows(self._csv_safe_row(row) for row in rows)
        return output.getvalue()

    def _initialize(self) -> None:
        with self._lock, self._connect() as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_conversations (
                    device_id TEXT NOT NULL,
                    conversation_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (device_id, conversation_id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_id TEXT NOT NULL,
                    conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY (device_id, conversation_id)
                        REFERENCES chat_conversations(device_id, conversation_id)
                        ON DELETE CASCADE
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_chat_messages_conversation
                ON chat_messages(device_id, conversation_id, id)
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    @staticmethod
    def _csv_safe_row(row: tuple[Any, ...]) -> tuple[Any, ...]:
        return tuple(ChatLogStore._csv_safe_value(value) for value in row)

    @staticmethod
    def _csv_safe_value(value: Any) -> Any:
        if isinstance(value, str) and value.startswith(("=", "+", "-", "@")):
            return "'" + value
        return value
