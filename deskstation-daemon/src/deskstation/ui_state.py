"""In-memory aggregator that builds per-screen snapshots and pushes them to the bridge.

Per spec/02-serial-protocol.md: host pushes full snapshots, rate-limit 5 msg/s/screen.
"""

import asyncio
import time
from typing import TYPE_CHECKING

import structlog

from deskstation.bridge.protocol import (
    FullscreenData,
    FullscreenMsg,
    JiraTask,
    MeetingBar,
    Notification,
    PomodoroStateData,
    PomodoroStateMsg,
    PullRequest,
    Screen1Data,
    Screen1Msg,
    Screen2Data,
    Screen2Msg,
    Screen3Data,
    Screen3Msg,
    Screen4Data,
    Screen4Msg,
    StandupItem,
    TodoItem,
    TopBarData,
    TopBarMsg,
)

if TYPE_CHECKING:
    from deskstation.bridge.interface import BridgeProtocol

log = structlog.get_logger(__name__)

_RATE_LIMIT_PER_SEC = 5
_MIN_INTERVAL_SEC = 1.0 / _RATE_LIMIT_PER_SEC


class UIState:
    """Per-screen mutable state. Setters trigger a dispatch (rate-limited)."""

    def __init__(self, bridge: "BridgeProtocol") -> None:
        self._bridge = bridge
        self._last_send: dict[str, float] = {}
        self._pending: dict[str, asyncio.Task[None]] = {}

        # Screen state
        self._top_bar = TopBarData(
            clock="--:--",
            date="",
            weather="",
            claude_usage="",
            pomodoro_counter=0,
        )
        self._screen_1 = Screen1Data()
        self._screen_2 = Screen2Data()
        self._screen_3 = Screen3Data()
        self._screen_4 = Screen4Data()
        self._pomodoro_state = PomodoroStateData(state="idle")
        self._fullscreen: FullscreenData | None = None

    # ---- setters ----

    def set_top_bar(self, data: TopBarData) -> None:
        self._top_bar = data
        self._schedule_send("top_bar")

    def set_screen_1(
        self,
        today_tasks: list[JiraTask] | None = None,
        queued_tasks: list[JiraTask] | None = None,
        next_meeting: MeetingBar | None = None,
    ) -> None:
        if today_tasks is not None:
            self._screen_1.today_tasks = today_tasks
        if queued_tasks is not None:
            self._screen_1.queued_tasks = queued_tasks
        self._screen_1.next_meeting = next_meeting
        self._schedule_send("screen_1")

    def set_screen_2(self, notifications: list[Notification]) -> None:
        self._screen_2.notifications = notifications
        self._schedule_send("screen_2")

    def set_screen_3(
        self,
        prs: list[PullRequest] | None = None,
        standup: list[StandupItem] | None = None,
    ) -> None:
        if prs is not None:
            self._screen_3.prs = prs
        if standup is not None:
            self._screen_3.standup = standup
        self._schedule_send("screen_3")

    def set_screen_4(self, items: list[TodoItem]) -> None:
        self._screen_4.items = items
        self._schedule_send("screen_4")

    def set_pomodoro_state(self, data: PomodoroStateData) -> None:
        self._pomodoro_state = data
        self._schedule_send("pomodoro_state")

    def set_fullscreen(self, data: FullscreenData | None) -> None:
        """Set or clear the break/reminder overlay. None clears (no message sent;
        firmware dismisses via fullscreen_dismiss feedback)."""
        self._fullscreen = data
        if data is not None:
            self._schedule_send("fullscreen")

    # ---- dispatch ----

    def _build_msg(self, key: str) -> object:
        if key == "top_bar":
            return TopBarMsg(data=self._top_bar)
        if key == "screen_1":
            return Screen1Msg(data=self._screen_1)
        if key == "screen_2":
            return Screen2Msg(data=self._screen_2)
        if key == "screen_3":
            return Screen3Msg(data=self._screen_3)
        if key == "screen_4":
            return Screen4Msg(data=self._screen_4)
        if key == "pomodoro_state":
            return PomodoroStateMsg(data=self._pomodoro_state)
        if key == "fullscreen":
            if self._fullscreen is None:
                raise ValueError("fullscreen requested but none set")
            return FullscreenMsg(data=self._fullscreen)
        raise ValueError(f"unknown key: {key}")

    def _schedule_send(self, key: str) -> None:
        """Rate-limited dispatch. If a send is already pending for this key, drop."""
        if key in self._pending and not self._pending[key].done():
            return  # coalesce — pending send will pick up the latest state
        self._pending[key] = asyncio.create_task(self._send(key))

    async def _send(self, key: str) -> None:
        elapsed = time.monotonic() - self._last_send.get(key, 0.0)
        if elapsed < _MIN_INTERVAL_SEC:
            await asyncio.sleep(_MIN_INTERVAL_SEC - elapsed)
        try:
            msg = self._build_msg(key)
            await self._bridge.send(msg)  # type: ignore[arg-type]
            self._last_send[key] = time.monotonic()
            log.debug("ui_state_sent", screen=key)
        except Exception as e:
            log.warning("ui_state_send_failed", screen=key, error=str(e))

    async def resend_all(self) -> None:
        """Push current state for every screen + top_bar + pomodoro_state. Use on reconnect.

        fullscreen is not resent — if a break overlay was active and the link
        dropped, the engine will re-trigger it through its own state ticks.
        """
        keys = (
            "top_bar",
            "screen_1",
            "screen_2",
            "screen_3",
            "screen_4",
            "pomodoro_state",
        )
        for key in keys:
            try:
                await self._bridge.send(self._build_msg(key))  # type: ignore[arg-type]
                self._last_send[key] = time.monotonic()
            except Exception as e:
                log.warning("ui_state_resend_failed", screen=key, error=str(e))
