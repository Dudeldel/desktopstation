"""Real clock + date poller — replaces the mock TopBarPoller's clock/date.

Resolution: minutes. Runs once at start, then sleeps until the next top-of-minute
and repeats. Survives a ``set_top_bar`` from elsewhere (mock fallback) because
``UIState.set_clock`` patches only its two fields.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from deskstation.ui_state import UIState

log = structlog.get_logger(__name__)

_PL_DAY = {
    "Mon": "pon",
    "Tue": "wt",
    "Wed": "śr",
    "Thu": "czw",
    "Fri": "pt",
    "Sat": "sob",
    "Sun": "ndz",
}


def _now() -> datetime:
    return datetime.now()


def format_clock_date(dt: datetime) -> tuple[str, str]:
    clock = dt.strftime("%H:%M")
    date = f"{_PL_DAY[dt.strftime('%a')]} {dt.strftime('%d.%m')}"
    return clock, date


class ClockPoller:
    def __init__(self, ui_state: UIState) -> None:
        self._ui = ui_state

    def tick_sync(self) -> None:
        clock, date = format_clock_date(_now())
        self._ui.set_clock(clock=clock, date=date)

    async def run_forever(self) -> None:
        while True:
            try:
                self.tick_sync()
            except Exception as exc:
                log.warning("clock_tick_error", error=str(exc))
            now = _now()
            sleep_sec = 60 - now.second + 0.05
            await asyncio.sleep(sleep_sec)
