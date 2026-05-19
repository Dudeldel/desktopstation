"""SQLite-backed cache for outbound API responses.

Used by the Jira / Bitbucket clients as a fallback so the UI can render a
last-known-good snapshot when the remote API is unreachable. Keys are
client-chosen strings (e.g. "jira:issues:DEV"); payloads are opaque bytes
(typically JSON-encoded by the caller).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

_DEFAULT_PATH = Path("~/.local/share/deskstation/state/api_cache.sqlite3").expanduser()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS api_cache (
  key TEXT PRIMARY KEY,
  payload BLOB NOT NULL,
  fetched_at TEXT NOT NULL  -- ISO datetime, local
);
"""


class ApiCache:
    """Thin SQLite wrapper. Synchronous; callers invoke from asyncio code on
    the same loop — each call is a single indexed row read/write."""

    def __init__(self, db_path: Path | None = None) -> None:
        self._path = db_path if db_path is not None else _DEFAULT_PATH
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def put(
        self,
        key: str,
        payload: bytes,
        fetched_at: datetime | None = None,
    ) -> None:
        moment = fetched_at if fetched_at is not None else datetime.now()
        self._conn.execute(
            "INSERT OR REPLACE INTO api_cache (key, payload, fetched_at) VALUES (?, ?, ?)",
            (key, payload, moment.isoformat()),
        )
        self._conn.commit()

    def get(self, key: str) -> tuple[bytes, datetime] | None:
        cur = self._conn.execute(
            "SELECT payload, fetched_at FROM api_cache WHERE key = ?",
            (key,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        payload, fetched_at = row
        return payload, datetime.fromisoformat(fetched_at)

    def age_sec(self, key: str) -> float | None:
        entry = self.get(key)
        if entry is None:
            return None
        _, fetched_at = entry
        return (datetime.now() - fetched_at).total_seconds()
