"""Tests for the SQLite-backed pomodoro counter store."""

from datetime import date, datetime, timedelta
from pathlib import Path

from deskstation.store.pomodoro_store import PomodoroStore


def test_empty_count_today(tmp_path: Path) -> None:
    store = PomodoroStore(tmp_path / "pomo.sqlite3")
    assert store.count_completed_today() == 0


def test_log_completed_increments_count(tmp_path: Path) -> None:
    store = PomodoroStore(tmp_path / "pomo.sqlite3")
    store.log("completed", task_key="DEV-1", duration_sec=1500)
    store.log("completed", task_key="DEV-2", duration_sec=1500)
    assert store.count_completed_today() == 2


def test_cancelled_does_not_increment(tmp_path: Path) -> None:
    store = PomodoroStore(tmp_path / "pomo.sqlite3")
    store.log("completed", task_key="DEV-1", duration_sec=1500)
    store.log("cancelled", task_key="DEV-2", duration_sec=400)
    store.log("cancelled", task_key=None, duration_sec=120)
    assert store.count_completed_today() == 1


def test_count_filters_by_day(tmp_path: Path) -> None:
    store = PomodoroStore(tmp_path / "pomo.sqlite3")
    # Yesterday: 3 completed, today: 1 completed.
    yesterday = datetime.now() - timedelta(days=1)
    for _ in range(3):
        store.log("completed", task_key="DEV-A", duration_sec=1500, when=yesterday)
    store.log("completed", task_key="DEV-B", duration_sec=1500)

    assert store.count_completed_today() == 1
    assert store.count_completed_today(today=yesterday.date()) == 3


def test_loose_pomodoro_no_task_key(tmp_path: Path) -> None:
    store = PomodoroStore(tmp_path / "pomo.sqlite3")
    store.log("completed", task_key=None, duration_sec=1500)
    assert store.count_completed_today() == 1


def test_persists_across_reopen(tmp_path: Path) -> None:
    db = tmp_path / "pomo.sqlite3"
    store = PomodoroStore(db)
    store.log("completed", task_key="DEV-1", duration_sec=1500)
    store.close()

    store2 = PomodoroStore(db)
    assert store2.count_completed_today() == 1


def test_count_with_explicit_date(tmp_path: Path) -> None:
    store = PomodoroStore(tmp_path / "pomo.sqlite3")
    custom_day = date(2026, 1, 15)
    when = datetime(2026, 1, 15, 10, 30)
    store.log("completed", task_key="DEV-1", duration_sec=1500, when=when)
    assert store.count_completed_today(today=custom_day) == 1
    assert store.count_completed_today(today=date(2026, 1, 16)) == 0
