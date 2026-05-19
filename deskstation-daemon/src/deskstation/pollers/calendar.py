"""Real Calendar poller: drives screen_1.next_meeting from Google Calendar.

Inherits from :class:`MockPoller` for the per-tick exception logging
convention, but overrides ``run_forever()`` to adapt the sleep interval
between ticks. The polling cadence is:

- ``near_interval_sec`` (default 60 s) when the soonest meeting starts
  within ``near_window_sec`` (default 30 min), or is currently ongoing
  (started but not ended). This keeps the meeting-bar countdown fresh
  when the user actually cares.
- ``far_interval_sec`` (default 300 s) otherwise. The Calendar API has a
  generous quota but there's no reason to hammer it every minute when
  the next meeting is hours away.

Error policy mirrors :class:`GmailPoller`:
- :class:`GoogleCalendarAuthError`: log once, set ``_auth_failed``,
  re-raise so the ``run_forever`` wrapper logs the failure. Subsequent
  ticks short-circuit so we don't spam the log every interval.
- :class:`GoogleCalendarTransientError`: log a warning and return —
  UIState keeps the last good ``next_meeting``.

UIState merge note: ``UIState.set_screen_1`` (M5.6) uses an ``_UNSET``
sentinel for ``next_meeting`` so the Jira poller's
``set_screen_1(today_tasks=..., queued_tasks=...)`` no longer clobbers
the meeting bar each tick. Verified before wiring.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog

from deskstation.bridge.protocol import MeetingBar
from deskstation.clients.gcal import (
    GoogleCalendarAuthError,
    GoogleCalendarClient,
    GoogleCalendarTransientError,
    Meeting,
)
from deskstation.pollers.mock import MockPoller

if TYPE_CHECKING:
    from deskstation.ui_state import UIState

log = structlog.get_logger(__name__)


def _format_time_range(start: datetime, end: datetime) -> str:
    """Render ``HH:MM-HH:MM`` in the system's local timezone.

    ``astimezone()`` without an argument uses the process's local TZ — in
    production that's the user's wall clock. Tests should not assert exact
    strings without controlling TZ.
    """
    start_local = start.astimezone()
    end_local = end.astimezone()
    return f"{start_local.strftime('%H:%M')}-{end_local.strftime('%H:%M')}"


def _pick_soonest(meetings: list[Meeting], now: datetime) -> Meeting | None:
    """Return the soonest meeting that hasn't ended yet, or ``None``."""
    future = [m for m in meetings if m.end > now]
    if not future:
        return None
    return min(future, key=lambda m: m.start)


class CalendarPoller(MockPoller):
    def __init__(
        self,
        ui_state: UIState,
        client: GoogleCalendarClient,
        *,
        near_interval_sec: float = 60.0,
        far_interval_sec: float = 300.0,
        near_window_sec: float = 30 * 60,
    ) -> None:
        super().__init__(ui_state, interval_sec=far_interval_sec)
        self._client = client
        self._near_interval = near_interval_sec
        self._far_interval = far_interval_sec
        self._near_window = near_window_sec
        self._auth_failed = False
        self._meetings: list[Meeting] = []

    @property
    def auth_failed(self) -> bool:
        return self._auth_failed

    async def tick(self) -> None:
        if self._auth_failed:
            return

        try:
            meetings = await self._client.list_upcoming(window_hours=36)
        except GoogleCalendarAuthError as exc:
            log.error("calendar_poller_auth_failed", error=str(exc))
            self._auth_failed = True
            raise
        except GoogleCalendarTransientError as exc:
            log.warning("calendar_poller_transient_error", error=str(exc))
            return

        self._meetings = meetings
        next_meeting = self._build_meeting_bar(meetings)
        self.ui_state.set_screen_1(next_meeting=next_meeting)

    async def run_forever(self) -> None:
        """Override to adapt the sleep interval each iteration.

        The base ``MockPoller.run_forever`` uses a fixed ``interval_sec``.
        Calendar wants short polling near a meeting and long polling
        otherwise, so we recompute the sleep duration after every tick.
        """
        while True:
            try:
                await self.tick()
            except Exception as exc:
                log.warning("calendar_poller_tick_error", error=str(exc))
            sleep_sec = self._compute_next_interval()
            await asyncio.sleep(sleep_sec)

    def _build_meeting_bar(self, meetings: list[Meeting]) -> MeetingBar | None:
        now = datetime.now(UTC)
        soonest = _pick_soonest(meetings, now)
        if soonest is None:
            return None
        in_minutes = int((soonest.start - now).total_seconds() / 60)
        return MeetingBar(
            title=soonest.title,
            time=_format_time_range(soonest.start, soonest.end),
            join_url=soonest.join_url,
            in_minutes=in_minutes,
        )

    def _compute_next_interval(self) -> float:
        if not self._meetings:
            return self._far_interval
        now = datetime.now(UTC)
        soonest = _pick_soonest(self._meetings, now)
        if soonest is None:
            return self._far_interval
        seconds_to_start = (soonest.start - now).total_seconds()
        # Ongoing (started but not ended) → still "near": user wants the
        # bar updating with elapsed time / a fresh join_url.
        if seconds_to_start < 0:
            return self._near_interval
        if seconds_to_start <= self._near_window:
            return self._near_interval
        return self._far_interval
