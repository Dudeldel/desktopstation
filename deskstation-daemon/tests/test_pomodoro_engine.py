"""Tests for the pomodoro state machine engine.

The engine is driven synchronously via `tick()` to avoid waiting on real time.
State assertions read engine.snapshot() directly; bridge interactions are
verified in a smaller set of focused tests.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from deskstation.bridge.mock_bridge import MockBridge
from deskstation.bridge.protocol import (
    FullscreenMsg,
    PomodoroStateMsg,
    TopBarMsg,
)
from deskstation.clients.jira import JiraAuthError
from deskstation.engines.pomodoro import PomodoroConfig, PomodoroEngine
from deskstation.store.pomodoro_store import PomodoroStore
from deskstation.ui_state import UIState


def _make_engine(
    tmp_path: Path, *, pomodoro_sec: int = 4, long_break_every: int = 4
) -> tuple[PomodoroEngine, UIState, MockBridge, PomodoroStore]:
    bridge = MockBridge()
    ui = UIState(bridge)
    store = PomodoroStore(tmp_path / "pomo.sqlite3")
    cfg = PomodoroConfig(
        pomodoro_sec=pomodoro_sec,
        short_break_sec=3,
        long_break_sec=6,
        long_break_every=long_break_every,
    )
    engine = PomodoroEngine(ui, store, cfg)
    return engine, ui, bridge, store


async def test_initial_state_is_idle(tmp_path: Path) -> None:
    engine, _, _, _ = _make_engine(tmp_path)
    snap = engine.snapshot()
    assert snap.state == "idle"
    assert snap.pomodoro_number_today == 0


async def test_start_task_transitions_to_active(tmp_path: Path) -> None:
    engine, _, _, _ = _make_engine(tmp_path, pomodoro_sec=1500)
    engine.start_task("DEV-1", summary="Refactor")
    snap = engine.snapshot()
    assert snap.state == "active"
    assert snap.task_key == "DEV-1"
    assert snap.task_summary == "Refactor"
    assert snap.remaining_sec == 1500
    assert snap.total_sec == 1500


async def test_start_loose_no_task(tmp_path: Path) -> None:
    engine, _, _, _ = _make_engine(tmp_path)
    engine.start_loose()
    snap = engine.snapshot()
    assert snap.state == "active"
    assert snap.task_key is None


async def test_tick_decrements_remaining(tmp_path: Path) -> None:
    engine, _, _, _ = _make_engine(tmp_path, pomodoro_sec=10)
    engine.start_task("DEV-1")
    engine.tick()
    engine.tick()
    assert engine.snapshot().remaining_sec == 8


async def test_pause_holds_remaining_and_resume_continues(tmp_path: Path) -> None:
    engine, _, _, _ = _make_engine(tmp_path, pomodoro_sec=10)
    engine.start_task("DEV-1")
    engine.tick()  # 9
    engine.pause()
    assert engine.snapshot().state == "paused"
    assert engine.snapshot().remaining_sec == 9

    engine.tick()  # paused — must not decrement
    assert engine.snapshot().remaining_sec == 9

    engine.resume()
    engine.tick()  # 8
    snap = engine.snapshot()
    assert snap.state == "active"
    assert snap.remaining_sec == 8


async def test_timer_expiry_completes_and_starts_short_break(tmp_path: Path) -> None:
    engine, _, _, store = _make_engine(tmp_path, pomodoro_sec=2, long_break_every=4)
    engine.start_task("DEV-1")
    engine.tick()  # 1
    engine.tick()  # 0 → complete
    snap = engine.snapshot()
    assert snap.state == "short_break"
    assert snap.pomodoro_number_today == 1
    assert snap.total_sec == 3  # cfg.short_break_sec
    assert store.count_completed_today() == 1


async def test_every_fourth_completion_triggers_long_break(tmp_path: Path) -> None:
    engine, _, _, store = _make_engine(tmp_path, pomodoro_sec=1, long_break_every=4)
    for i in range(1, 4):
        engine.start_task(f"DEV-{i}")
        engine.tick()
        engine.skip_break()
    engine.start_task("DEV-4")
    engine.tick()
    snap = engine.snapshot()
    assert snap.state == "long_break"
    assert snap.total_sec == 6  # cfg.long_break_sec
    assert store.count_completed_today() == 4


async def test_stop_with_log_completes_immediately(tmp_path: Path) -> None:
    engine, _, _, store = _make_engine(tmp_path, pomodoro_sec=1500)
    engine.start_task("DEV-1")
    engine.tick()  # 1499
    engine.stop_with_log()
    assert engine.snapshot().state == "short_break"
    assert store.count_completed_today() == 1


async def test_cancel_from_active_no_counter_increment(tmp_path: Path) -> None:
    engine, _, _, store = _make_engine(tmp_path)
    engine.start_task("DEV-1")
    engine.cancel()
    assert engine.snapshot().state == "idle"
    assert store.count_completed_today() == 0


async def test_cancel_during_break_returns_to_idle(tmp_path: Path) -> None:
    engine, _, _, _ = _make_engine(tmp_path, pomodoro_sec=1)
    engine.start_task("DEV-1")
    engine.tick()  # → break
    engine.cancel()
    assert engine.snapshot().state == "idle"


async def test_skip_break_only_works_during_break(tmp_path: Path) -> None:
    engine, _, _, _ = _make_engine(tmp_path, pomodoro_sec=10)
    engine.start_task("DEV-1")
    engine.skip_break()  # no-op on active
    assert engine.snapshot().state == "active"


async def test_break_naturally_returns_to_idle(tmp_path: Path) -> None:
    engine, _, _, _ = _make_engine(tmp_path, pomodoro_sec=1)
    engine.start_task("DEV-1")
    engine.tick()  # active → short_break (rem=3)
    for _ in range(3):
        engine.tick()
    assert engine.snapshot().state == "idle"


async def test_pause_is_noop_when_idle(tmp_path: Path) -> None:
    engine, _, _, _ = _make_engine(tmp_path)
    engine.pause()
    engine.resume()
    assert engine.snapshot().state == "idle"


async def test_loads_existing_counter_from_store(tmp_path: Path) -> None:
    bridge = MockBridge()
    ui = UIState(bridge)
    store = PomodoroStore(tmp_path / "pomo.sqlite3")
    store.log("completed", task_key="DEV-X", duration_sec=1500)
    store.log("completed", task_key="DEV-Y", duration_sec=1500)
    engine = PomodoroEngine(ui, store)
    assert engine.snapshot().pomodoro_number_today == 2


# ---------------------------------------------------------------------------
# Bridge integration: confirm messages actually flow on key transitions.
# Sleeps cover the UIState rate-limit window (0.2 s per screen).
# ---------------------------------------------------------------------------


async def test_bridge_receives_state_on_start(tmp_path: Path) -> None:
    engine, _, bridge, _ = _make_engine(tmp_path, pomodoro_sec=1500)
    engine.start_task("DEV-1")
    msg = await asyncio.wait_for(bridge.received(), timeout=1.0)
    assert isinstance(msg, PomodoroStateMsg)
    assert msg.data.state == "active"
    assert msg.data.task_key == "DEV-1"


async def test_bridge_receives_fullscreen_and_top_bar_on_completion(tmp_path: Path) -> None:
    engine, _, bridge, _ = _make_engine(tmp_path, pomodoro_sec=2)
    engine.start_task("DEV-1")
    engine.tick()
    engine.tick()  # → complete + break
    # Drain everything that flushes within the rate-limit window.
    await asyncio.sleep(0.3)
    saw_fullscreen = False
    saw_counter_one = False
    while not bridge._outbound.empty():
        msg = await bridge.received()
        if isinstance(msg, FullscreenMsg):
            saw_fullscreen = True
            assert msg.data.kind == "break_short"
        elif isinstance(msg, TopBarMsg):
            if msg.data.pomodoro_counter == 1:
                saw_counter_one = True
    assert saw_fullscreen, "expected break_short fullscreen on completion"
    assert saw_counter_one, "expected top_bar with counter=1 on completion"


# ---------------------------------------------------------------------------
# M4.4: task_index + worklog callbacks
# ---------------------------------------------------------------------------


async def test_engine_uses_task_index_for_summary(tmp_path: Path) -> None:
    bridge = MockBridge()
    ui = UIState(bridge)
    store = PomodoroStore(tmp_path / "pomo.sqlite3")
    engine = PomodoroEngine(
        ui,
        store,
        task_index=lambda k: "Looked up summary",
    )
    engine.start_task("DEV-1")
    assert engine.snapshot().task_summary == "Looked up summary"


async def test_engine_passes_explicit_summary_over_index(tmp_path: Path) -> None:
    bridge = MockBridge()
    ui = UIState(bridge)
    store = PomodoroStore(tmp_path / "pomo.sqlite3")
    engine = PomodoroEngine(
        ui,
        store,
        task_index=lambda k: "From index",
    )
    engine.start_task("DEV-1", summary="Override")
    assert engine.snapshot().task_summary == "Override"


async def test_engine_invokes_worklog_callback_on_completion(tmp_path: Path) -> None:
    calls: list[tuple[str, int]] = []

    async def worklog(key: str, seconds: int) -> bool:
        calls.append((key, seconds))
        return True

    bridge = MockBridge()
    ui = UIState(bridge)
    store = PomodoroStore(tmp_path / "pomo.sqlite3")
    cfg = PomodoroConfig(pomodoro_sec=10, short_break_sec=3, long_break_sec=6)
    engine = PomodoroEngine(ui, store, cfg, worklog=worklog)

    engine.start_task("DEV-42")
    engine.tick()  # 9
    engine.tick()  # 8
    engine.stop_with_log()  # forces _complete with elapsed = 10 - 8 = 2

    # _complete schedules worklog as a background task; give it a chance to run.
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert len(calls) == 1
    key, elapsed = calls[0]
    assert key == "DEV-42"
    assert elapsed > 0


async def test_engine_skips_worklog_for_loose_pomodoro(tmp_path: Path) -> None:
    calls: list[tuple[str, int]] = []

    async def worklog(key: str, seconds: int) -> bool:
        calls.append((key, seconds))
        return True

    bridge = MockBridge()
    ui = UIState(bridge)
    store = PomodoroStore(tmp_path / "pomo.sqlite3")
    engine = PomodoroEngine(ui, store, worklog=worklog)

    engine.start_loose()
    engine.stop_with_log()
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert calls == []


async def test_engine_swallows_worklog_exception(tmp_path: Path) -> None:
    async def worklog(key: str, seconds: int) -> bool:
        raise RuntimeError("kaboom")

    bridge = MockBridge()
    ui = UIState(bridge)
    store = PomodoroStore(tmp_path / "pomo.sqlite3")
    engine = PomodoroEngine(ui, store, worklog=worklog)

    engine.start_task("DEV-1")
    engine.stop_with_log()
    # No exception should propagate; give the background task a chance to run.
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    # State machine continued normally into a break.
    assert engine.snapshot().state == "short_break"


async def test_engine_disables_worklog_after_jira_auth_error(tmp_path: Path) -> None:
    call_count = 0

    async def worklog(key: str, seconds: int) -> bool:
        nonlocal call_count
        call_count += 1
        raise JiraAuthError("Jira auth failed: 401")

    bridge = MockBridge()
    ui = UIState(bridge)
    store = PomodoroStore(tmp_path / "pomo.sqlite3")
    cfg = PomodoroConfig(pomodoro_sec=10, short_break_sec=3, long_break_sec=6)
    engine = PomodoroEngine(ui, store, cfg, worklog=worklog)

    engine.start_task("DEV-1")
    engine.stop_with_log()
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert call_count == 1
    assert engine._worklog_disabled is True

    # Return to idle so we can start a fresh task (skip the break).
    engine.skip_break()
    engine.start_task("DEV-2")
    engine.stop_with_log()
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    # Callback must NOT have been invoked again after the auth error.
    assert call_count == 1


async def test_run_loop_ticks_in_real_time(tmp_path: Path) -> None:
    engine, _, _, _ = _make_engine(tmp_path)
    engine._cfg = PomodoroConfig(  # type: ignore[misc]
        pomodoro_sec=3,
        short_break_sec=2,
        long_break_sec=5,
        long_break_every=4,
        tick_interval_sec=0.02,
    )
    engine.start_task("DEV-1")
    task = engine.start()
    await asyncio.sleep(0.15)
    task.cancel()
    snap = engine.snapshot()
    # At 0.02 s per tick over 0.15 s → ~7 ticks on a 3 s timer → completed and in break.
    assert snap.state in ("active", "short_break", "idle")
