"""Pomodoro state machine engine.

States: idle | active | paused | short_break | long_break

Transitions (callers come from the bridge dispatcher; the 1 Hz tick comes from
the engine's own run() task):

  start_task(key, summary)             → active(total=pomodoro_sec)
  start_loose()                        → active(total=pomodoro_sec, no task)
  pause()        active                → paused
  resume()       paused                → active
  stop_with_log() active|paused        → log "completed", counter += 1,
                                         long_break (every Nth) or short_break
  cancel()       any non-idle          → log "cancelled" if active/paused,
                                         then idle
  skip_break()   short_break|long_break → idle
  tick()         active|short_break|long_break
                                       → remaining_sec -= 1; on zero, same as
                                         stop_with_log (active) or end-break.

The engine pushes a `pomodoro_state` snapshot on every transition and on
every tick, and a `fullscreen` snapshot once when a break starts, plus a
top_bar update with the bumped counter after a completion.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

from deskstation.bridge.protocol import (
    FullscreenData,
    PomodoroStateData,
    PomodoroStateName,
)
from deskstation.clients.jira import JiraAuthError

if TYPE_CHECKING:
    from deskstation.store.pomodoro_store import PomodoroStore
    from deskstation.ui_state import UIState

log = structlog.get_logger(__name__)


@dataclass
class _State:
    state: PomodoroStateName = "idle"
    remaining_sec: int = 0
    total_sec: int = 0
    task_key: str | None = None
    task_summary: str | None = None
    pomodoro_number_today: int = 0


@dataclass(frozen=True)
class PomodoroConfig:
    pomodoro_sec: int = 25 * 60
    short_break_sec: int = 5 * 60
    long_break_sec: int = 20 * 60
    long_break_every: int = 4  # every Nth completed pomodoro triggers a long break
    tick_interval_sec: float = 1.0


class PomodoroEngine:
    def __init__(
        self,
        ui_state: UIState,
        store: PomodoroStore,
        config: PomodoroConfig | None = None,
        task_index: Callable[[str], str | None] | None = None,
        worklog: Callable[[str, int], Awaitable[bool]] | None = None,
    ) -> None:
        self._ui = ui_state
        self._store = store
        self._cfg = config if config is not None else PomodoroConfig()
        self._s = _State(pomodoro_number_today=store.count_completed_today())
        self._task: asyncio.Task[None] | None = None
        self._task_index = task_index
        self._worklog = worklog
        self._worklog_disabled: bool = False
        self._bg_tasks: set[asyncio.Task[None]] = set()

    # ------------------------------------------------------------------ inspection

    def is_focus_state(self) -> bool:
        """True iff pomodoro is in any non-idle state — used by the reminders engine."""
        return self._s.state != "idle"

    def snapshot(self) -> PomodoroStateData:
        """Return the current state as the same shape the firmware receives."""
        return PomodoroStateData(
            state=self._s.state,
            remaining_sec=max(0, self._s.remaining_sec),
            total_sec=self._s.total_sec,
            task_key=self._s.task_key,
            task_summary=self._s.task_summary,
            pomodoro_number_today=self._s.pomodoro_number_today,
        )

    # ------------------------------------------------------------------ lifecycle

    def start(self) -> asyncio.Task[None]:
        """Start the 1 Hz tick loop. Returns the asyncio Task for cancellation."""
        if self._task is not None and not self._task.done():
            return self._task
        # Emit initial state immediately so the firmware sees idle from boot.
        self._push_state()
        self._task = asyncio.create_task(self._run(), name="pomodoro_engine")
        return self._task

    async def _run(self) -> None:
        try:
            while True:
                await asyncio.sleep(self._cfg.tick_interval_sec)
                self.tick()
        except asyncio.CancelledError:
            return

    # ------------------------------------------------------------------ actions

    def start_task(self, key: str, summary: str | None = None) -> None:
        if summary is None and self._task_index is not None:
            looked_up = self._task_index(key)
            if looked_up is not None:
                summary = looked_up
        self._s = _State(
            state="active",
            remaining_sec=self._cfg.pomodoro_sec,
            total_sec=self._cfg.pomodoro_sec,
            task_key=key,
            task_summary=summary,
            pomodoro_number_today=self._s.pomodoro_number_today,
        )
        log.info("pomodoro_started", task_key=key)
        self._push_state()

    def start_loose(self) -> None:
        self._s = _State(
            state="active",
            remaining_sec=self._cfg.pomodoro_sec,
            total_sec=self._cfg.pomodoro_sec,
            pomodoro_number_today=self._s.pomodoro_number_today,
        )
        log.info("pomodoro_started_loose")
        self._push_state()

    def pause(self) -> None:
        if self._s.state != "active":
            return
        self._s.state = "paused"
        log.info("pomodoro_paused", remaining_sec=self._s.remaining_sec)
        self._push_state()

    def resume(self) -> None:
        if self._s.state != "paused":
            return
        self._s.state = "active"
        log.info("pomodoro_resumed", remaining_sec=self._s.remaining_sec)
        self._push_state()

    def stop_with_log(self) -> None:
        if self._s.state in ("active", "paused"):
            self._complete()

    def cancel(self) -> None:
        if self._s.state in ("active", "paused"):
            elapsed = max(0, self._s.total_sec - self._s.remaining_sec)
            self._store.log("cancelled", task_key=self._s.task_key, duration_sec=elapsed)
            log.info("pomodoro_cancelled", task_key=self._s.task_key, elapsed_sec=elapsed)
            self._go_idle()
        elif self._s.state in ("short_break", "long_break"):
            self._go_idle()

    def skip_break(self) -> None:
        if self._s.state in ("short_break", "long_break"):
            log.info("pomodoro_skip_break")
            self._go_idle()

    # ------------------------------------------------------------------ tick

    def tick(self) -> None:
        """Advance the engine by one second. Called by the run() loop or by tests."""
        if self._s.state not in ("active", "short_break", "long_break"):
            return
        self._s.remaining_sec -= 1
        if self._s.remaining_sec <= 0:
            if self._s.state == "active":
                self._complete()
                return
            # Break ended naturally.
            self._go_idle()
            return
        self._push_state()

    # ------------------------------------------------------------------ internal

    def _complete(self) -> None:
        elapsed = self._s.total_sec - max(0, self._s.remaining_sec)
        if elapsed <= 0:
            elapsed = self._s.total_sec
        self._store.log("completed", task_key=self._s.task_key, duration_sec=elapsed)
        new_count = self._store.count_completed_today()
        is_long = new_count > 0 and (new_count % self._cfg.long_break_every == 0)
        break_state: PomodoroStateName = "long_break" if is_long else "short_break"
        break_total = self._cfg.long_break_sec if is_long else self._cfg.short_break_sec

        prev_key = self._s.task_key
        prev_summary = self._s.task_summary
        self._s = _State(
            state=break_state,
            remaining_sec=break_total,
            total_sec=break_total,
            task_key=prev_key,
            task_summary=prev_summary,
            pomodoro_number_today=new_count,
        )
        log.info(
            "pomodoro_completed",
            task_key=prev_key,
            elapsed_sec=elapsed,
            pomodoro_number_today=new_count,
            next_break=break_state,
        )
        self._push_state()
        self._push_break_fullscreen(is_long, break_total)
        self._ui.set_pomodoros_today(new_count)

        if prev_key is not None and self._worklog is not None and not self._worklog_disabled:
            cb = self._worklog
            bg = asyncio.create_task(self._invoke_worklog(cb, prev_key, elapsed))
            self._bg_tasks.add(bg)
            bg.add_done_callback(self._bg_tasks.discard)

    async def _invoke_worklog(
        self,
        cb: Callable[[str, int], Awaitable[bool]],
        key: str,
        seconds: int,
    ) -> None:
        try:
            ok = await cb(key, seconds)
            if not ok:
                log.warning("worklog_failed", task_key=key, seconds=seconds)
            else:
                log.info("worklog_posted", task_key=key, seconds=seconds, success=ok)
        except JiraAuthError as exc:
            self._worklog_disabled = True
            log.error("worklog_disabled_auth_error", task_key=key, error=str(exc))
        except Exception as exc:
            log.warning("worklog_raised", task_key=key, error=str(exc))

    def _go_idle(self) -> None:
        self._s = _State(pomodoro_number_today=self._s.pomodoro_number_today)
        self._push_state()

    def _push_state(self) -> None:
        self._ui.set_pomodoro_state(
            PomodoroStateData(
                state=self._s.state,
                remaining_sec=max(0, self._s.remaining_sec),
                total_sec=self._s.total_sec,
                task_key=self._s.task_key,
                task_summary=self._s.task_summary,
                pomodoro_number_today=self._s.pomodoro_number_today,
            )
        )

    def _push_break_fullscreen(self, is_long: bool, duration: int) -> None:
        if is_long:
            data = FullscreenData(
                kind="break_long",
                title="Długa przerwa",
                message="Czas na dłuższą przerwę",
                submessage="Przejdź się, rozciągnij — wrócisz świeży.",
                duration_sec=duration,
                activities=["stretch", "walk", "water"],
                dismissible=True,
            )
        else:
            data = FullscreenData(
                kind="break_short",
                title="Krótka przerwa",
                message="Wstań i napij się wody",
                submessage="Spójrz w dal przez 20 sekund.",
                duration_sec=duration,
                activities=["water", "eyes"],
                dismissible=True,
            )
        self._ui.set_fullscreen(data)
