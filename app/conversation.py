from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

from openai import OpenAI

from app.config import Settings
from app.prompts import CONVERSATION_SUMMARY_PROMPT


class ConversationService:
    """Stores server-side conversation turns and maintains a rolling summary."""

    def __init__(self, settings: Settings, client: OpenAI) -> None:
        self.settings = settings
        self.client = client
        self.path = settings.conversation_db_path
        self._summary_lock = threading.Lock()
        self._initialize()

    def get_summary(self, user_id: str, conversation_id: str) -> str:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT summary
                FROM conversation_summaries
                WHERE conversation_id = ? AND user_id = ?
                """,
                (conversation_id, user_id),
            ).fetchone()
        return str(row[0]) if row else ""

    def reset(self) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM conversation_messages")
            connection.execute("DELETE FROM conversation_summaries")
            connection.execute(
                "DELETE FROM sqlite_sequence WHERE name = 'conversation_messages'"
            )

    def record_and_maybe_summarize(
        self,
        user_id: str,
        conversation_id: str,
        user_message: str,
        assistant_message: str,
    ) -> bool:
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO conversation_messages
                    (conversation_id, user_id, role, content)
                VALUES (?, ?, ?, ?)
                """,
                [
                    (conversation_id, user_id, "user", user_message),
                    (conversation_id, user_id, "assistant", assistant_message),
                ],
            )

        with self._summary_lock:
            current_summary, last_message_id, pending = self._summary_state(
                user_id, conversation_id
            )
            if len(pending) < self.settings.summary_trigger_messages:
                return False

            response = self.client.responses.create(
                model=self.settings.summary_model,
                instructions=CONVERSATION_SUMMARY_PROMPT,
                input=[
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "existing_summary": current_summary,
                                "new_messages": [
                                    {"role": role, "content": content}
                                    for _, role, content in pending
                                ],
                            },
                            ensure_ascii=False,
                        ),
                    }
                ],
                reasoning={"effort": self.settings.reasoning_effort},
                max_output_tokens=min(self.settings.max_output_tokens, 800),
                safety_identifier=self._safety_identifier(user_id),
            )
            summary = response.output_text.strip()
            if not summary:
                raise RuntimeError("conversation summary was empty")

            newest_message_id = max(message_id for message_id, _, _ in pending)
            self._save_summary(
                user_id,
                conversation_id,
                summary,
                max(last_message_id, newest_message_id),
            )
            return True

    def _summary_state(
        self, user_id: str, conversation_id: str
    ) -> tuple[str, int, list[tuple[int, str, str]]]:
        with self._connect() as connection:
            summary_row = connection.execute(
                """
                SELECT summary, last_message_id
                FROM conversation_summaries
                WHERE conversation_id = ? AND user_id = ?
                """,
                (conversation_id, user_id),
            ).fetchone()
            summary = str(summary_row[0]) if summary_row else ""
            last_message_id = int(summary_row[1]) if summary_row else 0
            pending = connection.execute(
                """
                SELECT id, role, content
                FROM conversation_messages
                WHERE conversation_id = ? AND user_id = ? AND id > ?
                ORDER BY id ASC
                LIMIT 100
                """,
                (conversation_id, user_id, last_message_id),
            ).fetchall()
        return summary, last_message_id, [tuple(row) for row in pending]

    def _save_summary(
        self,
        user_id: str,
        conversation_id: str,
        summary: str,
        last_message_id: int,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO conversation_summaries
                    (conversation_id, user_id, summary, last_message_id, updated_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(conversation_id) DO UPDATE SET
                    user_id = excluded.user_id,
                    summary = excluded.summary,
                    last_message_id = excluded.last_message_id,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (conversation_id, user_id, summary, last_message_id),
            )

    def _initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS conversation_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_conversation_messages_scope
                ON conversation_messages(conversation_id, user_id, id);

                CREATE TABLE IF NOT EXISTS conversation_summaries (
                    conversation_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    last_message_id INTEGER NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=30)

    @staticmethod
    def _safety_identifier(user_id: str) -> str:
        import hashlib

        return hashlib.sha256(user_id.encode("utf-8")).hexdigest()
