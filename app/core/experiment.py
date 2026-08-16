from __future__ import annotations

import csv
import hashlib
import hmac
import io
import json
import math
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any


class ExperimentPhase(str, Enum):
    WAITING = "WAITING"
    SIMPLE = "SIMPLE"
    TRANSITION = "TRANSITION"
    FULL = "FULL"
    COMPLETE = "COMPLETE"


@dataclass(frozen=True)
class ExperimentState:
    experiment_id: str
    phase: ExperimentPhase
    started: bool
    remaining_seconds: int
    phase_seconds: int


class DeviceCookieSigner:
    def __init__(self, secret: str) -> None:
        self.secret = secret.encode("utf-8")

    def new_token(self) -> tuple[str, str]:
        device_id = uuid.uuid4().hex
        return device_id, f"{device_id}.{self._sign(device_id)}"

    def verify(self, token: str | None) -> str | None:
        if not token:
            return None
        try:
            device_id, signature = token.split(".", maxsplit=1)
            uuid.UUID(hex=device_id)
        except (ValueError, AttributeError):
            return None
        expected = self._sign(device_id)
        return device_id if hmac.compare_digest(signature, expected) else None

    def _sign(self, value: str) -> str:
        return hmac.new(
            self.secret,
            value.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()


class ExperimentStore:
    """Stores experiment timing and research logs separately from model state."""

    def __init__(self, path: Path, clock=time.time) -> None:
        self.path = path
        self.clock = clock
        self._lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS experiments (
                    experiment_id TEXT PRIMARY KEY,
                    device_id TEXT NOT NULL UNIQUE,
                    created_at REAL NOT NULL,
                    started_at REAL,
                    full_started_at REAL
                );

                CREATE TABLE IF NOT EXISTS experiment_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    experiment_id TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY (experiment_id)
                        REFERENCES experiments(experiment_id)
                        ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_experiment_messages_lookup
                ON experiment_messages(experiment_id, phase, id);
                """
            )
            columns = {
                str(row[1])
                for row in connection.execute("PRAGMA table_info(experiments)")
            }
            if "full_started_at" not in columns:
                connection.execute(
                    "ALTER TABLE experiments ADD COLUMN full_started_at REAL"
                )

    def status(
        self,
        device_id: str,
        phase_seconds: int,
    ) -> ExperimentState:
        experiment = self._get_or_create(device_id)
        return self._state_from_row(experiment, phase_seconds)

    def start(
        self,
        device_id: str,
        phase_seconds: int,
    ) -> ExperimentState:
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT experiment_id, device_id, created_at, started_at,
                       full_started_at
                FROM experiments WHERE device_id = ?
                """,
                (device_id,),
            ).fetchone()
            if row is None:
                now = self.clock()
                experiment_id = uuid.uuid4().hex
                connection.execute(
                    """
                    INSERT INTO experiments
                        (experiment_id, device_id, created_at, started_at,
                         full_started_at)
                    VALUES (?, ?, ?, ?, NULL)
                    """,
                    (experiment_id, device_id, now, now),
                )
                row = (experiment_id, device_id, now, now, None)
            elif row[3] is None:
                started_at = self.clock()
                connection.execute(
                    "UPDATE experiments SET started_at = ? WHERE device_id = ?",
                    (started_at, device_id),
                )
                row = (row[0], row[1], row[2], started_at, row[4])
            connection.commit()
        return self._state_from_row(row, phase_seconds)

    def advance_to_full(
        self,
        device_id: str,
        phase_seconds: int,
    ) -> ExperimentState:
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT experiment_id, device_id, created_at, started_at,
                       full_started_at
                FROM experiments WHERE device_id = ?
                """,
                (device_id,),
            ).fetchone()
            if row is None:
                connection.rollback()
                raise ValueError("experiment was not found")
            state = self._state_from_row(row, phase_seconds)
            if state.phase is not ExperimentPhase.TRANSITION:
                connection.rollback()
                return state
            full_started_at = self.clock()
            connection.execute(
                """
                UPDATE experiments SET full_started_at = ?
                WHERE device_id = ?
                """,
                (full_started_at, device_id),
            )
            connection.commit()
            row = (row[0], row[1], row[2], row[3], full_started_at)
        return self._state_from_row(row, phase_seconds)

    def history(
        self,
        experiment_id: str,
        phase: ExperimentPhase,
        limit: int,
    ) -> list[dict[str, str]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT role, content FROM (
                    SELECT id, role, content
                    FROM experiment_messages
                    WHERE experiment_id = ? AND phase = ?
                    ORDER BY id DESC LIMIT ?
                ) ORDER BY id ASC
                """,
                (experiment_id, phase.value, limit),
            ).fetchall()
        return [{"role": str(row[0]), "content": str(row[1])} for row in rows]

    def append_turn(
        self,
        experiment_id: str,
        phase: ExperimentPhase,
        user_message: str,
        assistant_message: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        now = self.clock()
        metadata_json = json.dumps(metadata or {}, ensure_ascii=False)
        with self._lock, self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO experiment_messages
                    (experiment_id, phase, role, content, created_at, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        experiment_id,
                        phase.value,
                        "user",
                        user_message,
                        now,
                        "{}",
                    ),
                    (
                        experiment_id,
                        phase.value,
                        "assistant",
                        assistant_message,
                        now,
                        metadata_json,
                    ),
                ],
            )

    def export_csv(self) -> str:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    e.experiment_id,
                    e.device_id,
                    e.created_at,
                    e.started_at,
                    e.full_started_at,
                    m.id,
                    m.phase,
                    m.role,
                    m.content,
                    m.created_at,
                    m.metadata_json
                FROM experiments e
                LEFT JOIN experiment_messages m
                    ON m.experiment_id = e.experiment_id
                ORDER BY e.created_at, m.id
                """
            ).fetchall()
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(
            [
                "experiment_id",
                "device_id",
                "experiment_created_at",
                "experiment_started_at",
                "full_phase_started_at",
                "message_id",
                "phase",
                "role",
                "content",
                "message_created_at",
                "metadata_json",
            ]
        )
        writer.writerows(self._csv_safe_row(row) for row in rows)
        return output.getvalue()

    def reset_device(self, device_id: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute(
                "DELETE FROM experiments WHERE device_id = ?",
                (device_id,),
            )

    def reset_all(self) -> None:
        with self._lock, self._connect() as connection:
            connection.execute("DELETE FROM experiment_messages")
            connection.execute("DELETE FROM experiments")

    def _get_or_create(self, device_id: str) -> tuple[Any, ...]:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT experiment_id, device_id, created_at, started_at,
                       full_started_at
                FROM experiments WHERE device_id = ?
                """,
                (device_id,),
            ).fetchone()
            if row is not None:
                return row
            now = self.clock()
            experiment_id = uuid.uuid4().hex
            connection.execute(
                """
                INSERT INTO experiments
                    (experiment_id, device_id, created_at, started_at,
                     full_started_at)
                VALUES (?, ?, ?, NULL, NULL)
                """,
                (experiment_id, device_id, now),
            )
            return (experiment_id, device_id, now, None, None)

    def _state_from_row(
        self,
        row: tuple[Any, ...],
        phase_seconds: int,
    ) -> ExperimentState:
        experiment_id = str(row[0])
        started_at = row[3]
        if started_at is None:
            return ExperimentState(
                experiment_id=experiment_id,
                phase=ExperimentPhase.WAITING,
                started=False,
                remaining_seconds=phase_seconds,
                phase_seconds=phase_seconds,
            )
        now = self.clock()
        elapsed = max(0.0, now - float(started_at))
        if elapsed < phase_seconds:
            phase = ExperimentPhase.SIMPLE
            remaining = math.ceil(phase_seconds - elapsed)
        elif row[4] is None:
            phase = ExperimentPhase.TRANSITION
            remaining = phase_seconds
        else:
            full_elapsed = max(0.0, now - float(row[4]))
            if full_elapsed < phase_seconds:
                phase = ExperimentPhase.FULL
                remaining = math.ceil(phase_seconds - full_elapsed)
            else:
                phase = ExperimentPhase.COMPLETE
                remaining = 0
        return ExperimentState(
            experiment_id=experiment_id,
            phase=phase,
            started=True,
            remaining_seconds=remaining,
            phase_seconds=phase_seconds,
        )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @staticmethod
    def _csv_safe_row(row: tuple[Any, ...]) -> list[Any]:
        values = list(row)
        content_index = 8
        if len(values) > content_index and isinstance(values[content_index], str):
            content = values[content_index]
            if content.startswith(("=", "+", "-", "@")):
                values[content_index] = "'" + content
        return values
