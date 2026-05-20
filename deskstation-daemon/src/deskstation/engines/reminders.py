"""Water/eyes reminders for the idle (non-pomodoro) state.

When the pomodoro engine reports a non-idle state, this engine is silent —
the break overlay already nudges the user. While pomodoro is idle, this
engine alternates water -> eyes -> water -> ... every ``interval_sec`` and
pushes a dismissible fullscreen snapshot.
"""

from __future__ import annotations

import asyncio
from itertools import cycle
from typing import TYPE_CHECKING

import structlog

from deskstation.bridge.protocol import FullscreenData, FullscreenKind

if TYPE_CHECKING:
    from deskstation.engines.pomodoro import PomodoroEngine
    from deskstation.ui_state import UIState

log = structlog.get_logger(__name__)


_REMINDER_CYCLE: tuple[tuple[FullscreenKind, str, str], ...] = (
    ("water", "Czas na wodę", "Wypij szklankę wody"),
    ("eyes", "Daj odpocząć oczom", "Spójrz na ~6 m przez ~20 s"),
)


class RemindersEngine:
    def __init__(
        self,
        ui_state: UIState,
        pomodoro: PomodoroEngine,
        interval_sec: float,
    ) -> None:
        self._ui = ui_state
        self._pomodoro = pomodoro
        self._interval = interval_sec

    async def run_forever(self) -> None:
        cycler = cycle(_REMINDER_CYCLE)
        while True:
            await asyncio.sleep(self._interval)
            if self._pomodoro.is_focus_state():
                continue
            kind, title, message = next(cycler)
            log.info("reminder_push", kind=kind)
            self._ui.set_fullscreen(
                FullscreenData(
                    kind=kind,
                    title=title,
                    message=message,
                    duration_sec=20,
                    dismissible=True,
                )
            )
