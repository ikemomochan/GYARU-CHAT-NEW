from __future__ import annotations

import hashlib
import hmac
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TrialUsage:
    used: int
    limit: int

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used)

    @property
    def locked(self) -> bool:
        return self.used >= self.limit


class TrialLimitExceeded(Exception):
    def __init__(self, usage: TrialUsage) -> None:
        self.usage = usage
        super().__init__("trial message limit reached")


class TrialUsageStore:
    """SQLite-backed usage counter for a single Render web service."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS trial_usage (
                    device_id TEXT PRIMARY KEY,
                    used INTEGER NOT NULL CHECK (used >= 0),
                    updated_at INTEGER NOT NULL
                )
                """
            )

    def status(self, device_id: str, limit: int) -> TrialUsage:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT used FROM trial_usage WHERE device_id = ?",
                (device_id,),
            ).fetchone()
        return TrialUsage(used=int(row[0]) if row else 0, limit=limit)

    def consume(self, device_id: str, limit: int) -> TrialUsage:
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT used FROM trial_usage WHERE device_id = ?",
                (device_id,),
            ).fetchone()
            used = int(row[0]) if row else 0
            if used >= limit:
                connection.rollback()
                raise TrialLimitExceeded(TrialUsage(used=used, limit=limit))
            used += 1
            connection.execute(
                """
                INSERT INTO trial_usage (device_id, used, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(device_id) DO UPDATE SET
                    used = excluded.used,
                    updated_at = excluded.updated_at
                """,
                (device_id, used, int(time.time())),
            )
            connection.commit()
        return TrialUsage(used=used, limit=limit)

    def refund(self, device_id: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE trial_usage
                SET used = MAX(0, used - 1), updated_at = ?
                WHERE device_id = ?
                """,
                (int(time.time()), device_id),
            )

    def reset(self) -> None:
        with self._lock, self._connect() as connection:
            connection.execute("DELETE FROM trial_usage")

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=5)


class TrialCookieSigner:
    def __init__(self, secret: str, debug_ttl_seconds: int) -> None:
        self.secret = secret.encode("utf-8")
        self.debug_ttl_seconds = debug_ttl_seconds

    def new_device_token(self) -> tuple[str, str]:
        device_id = uuid.uuid4().hex
        return device_id, f"{device_id}.{self._sign(f'device:{device_id}')}"

    def verify_device_token(self, token: str | None) -> str | None:
        if not token:
            return None
        try:
            device_id, signature = token.split(".", maxsplit=1)
            uuid.UUID(hex=device_id)
        except (ValueError, AttributeError):
            return None
        expected = self._sign(f"device:{device_id}")
        return device_id if hmac.compare_digest(signature, expected) else None

    def new_debug_token(self, device_id: str) -> tuple[str, int]:
        expires_at = int(time.time()) + self.debug_ttl_seconds
        payload = f"debug:{device_id}:{expires_at}"
        return f"{expires_at}.{self._sign(payload)}", expires_at

    def verify_debug_token(
        self,
        token: str | None,
        device_id: str,
    ) -> bool:
        if not token:
            return False
        try:
            raw_expiry, signature = token.split(".", maxsplit=1)
            expires_at = int(raw_expiry)
        except (ValueError, AttributeError):
            return False
        if expires_at < int(time.time()):
            return False
        expected = self._sign(f"debug:{device_id}:{expires_at}")
        return hmac.compare_digest(signature, expected)

    def _sign(self, payload: str) -> str:
        return hmac.new(
            self.secret,
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
