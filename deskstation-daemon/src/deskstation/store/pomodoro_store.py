"""SQLite-backed daily pomodoro counter.

One row per (date, kind) pair where `kind` distinguishes counted completions
from non-counted cancels. M3 only counts `completed`; cancels are logged for
future audits without affecting the daily count.

The counter resets at midnight LOCAL time. Resetting is implicit: queries
filter by `today`'s date, so a fresh day reads zero from the table without any
delete step.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Literal

PomodoroLogKind = Literal["completed", "cancelled"]

_DEFAULT_PATH = Path("~/.local/share/deskstation/state/pomodoro.sqlite3").expanduser()


_SCHEMA = """
CREATE TABLE IF NOT EXISTS pomodoro_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    day         TEXT    NOT NULL,           -- ISO yyyy-mm-dd, local time
    completed_at TEXT   NOT NULL,           -- ISO datetime, local time
    kind        TEXT    NOT NULL,           -- 'completed' | 'cancelled'
    task_key    TEXT,                       -- nullable for loose pomodoros
    duration_sec INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS pomodoro_log_day_kind ON pomodoro_log (day, kind);
"""


class PomodoroStore:
    """Thin SQLite wrapper. Synchronous; the engine calls these inline from its
    asyncio loop — each call is cheap (single-row insert / count query)."""

    def __init__(self, db_path: Path | None = None) -> None:
        self._path = db_path if db_path is not None else _DEFAULT_PATH
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def log(
        self,
        kind: PomodoroLogKind,
        *,
        task_key: str | None,
        duration_sec: int,
        when: datetime | None = None,
    ) -> None:
        moment = when if when is not None else datetime.now()
        self._conn.execute(
            "INSERT INTO pomodoro_log (day, completed_at, kind, task_key, duration_sec) "
            "VALUES (?, ?, ?, ?, ?)",
            (moment.date().isoformat(), moment.isoformat(), kind, task_key, duration_sec),
        )
        self._conn.commit()

    def count_completed_today(self, today: date | None = None) -> int:
        d = today if today is not None else date.today()
        cur = self._conn.execute(
            "SELECT COUNT(*) FROM pomodoro_log WHERE day = ? AND kind = 'completed'",
            (d.isoformat(),),
        )
        (count,) = cur.fetchone()
        return int(count)
