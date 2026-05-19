"""Tests for M5.7 dispatch handlers: notification_action + meeting_join.

The dispatcher resolves an id from the firmware into a URL (via the
Screen2Merger url index or the CalendarPoller meeting list) and runs
``xdg-open`` off the event loop. Lookup failures are logged warnings —
they must not raise.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from deskstation.bridge.heartbeat import ConnectionMonitor
from deskstation.bridge.mock_bridge import MockBridge
from deskstation.bridge.protocol import (
    MeetingJoinData,
    MeetingJoinMsg,
    NotificationActionData,
    NotificationActionMsg,
    NotificationClickedData,
    NotificationClickedMsg,
)
from deskstation.clients.gcal import Meeting
from deskstation.engines.screen2_merger import Screen2Merger
from deskstation.main import DispatchContext, _dispatch, _xdg_open
from deskstation.pollers.calendar import CalendarPoller
from deskstation.ui_state import UIState


def _make_calendar_poller_with_meeting(meeting: Meeting) -> CalendarPoller:
    bridge = MockBridge()
    ui = UIState(bridge)
    client = MagicMock()  # not used; lookup reads from _meetings directly
    poller = CalendarPoller(ui, client)
    poller._meetings = [meeting]
    return poller


async def _run_dispatch_once(
    bridge: MockBridge,
    *,
    merger: Screen2Merger | None = None,
    calendar_poller: CalendarPoller | None = None,
) -> None:
    """Run _dispatch until the inbound queue is drained, then cancel.

    The dispatcher is an infinite async generator over ``bridge.stream()``.
    We schedule it as a task, wait long enough for it to consume the
    queued envelopes, then cancel.
    """
    ui = UIState(bridge)
    monitor = ConnectionMonitor()
    pomodoro = MagicMock()
    ctx = DispatchContext(
        bridge=bridge,
        monitor=monitor,
        ui_state=ui,
        pomodoro=pomodoro,
        merger=merger,
        calendar_poller=calendar_poller,
    )
    task = asyncio.create_task(_dispatch(ctx))
    # Give the dispatcher loop time to consume injected envelopes. The
    # MockBridge.stream() polls with a 50 ms timeout, so 200 ms is plenty
    # for a single envelope.
    await asyncio.sleep(0.2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_xdg_open_runs_in_thread() -> None:
    """The helper must use asyncio.to_thread so it doesn't block the loop."""
    with patch("deskstation.main.subprocess.run") as mock_run:
        await _xdg_open("https://example.com")
    mock_run.assert_called_once_with(["xdg-open", "https://example.com"], check=False)


async def test_notification_action_runs_xdg_open() -> None:
    bridge = MockBridge()
    ui = UIState(bridge)
    merger = Screen2Merger(ui)
    merger.register_url("n1", "https://mail.google.com/mail/u/0/#inbox/n1")

    await bridge.inject(NotificationActionMsg(data=NotificationActionData(id="n1")))

    with patch("deskstation.main.subprocess.run") as mock_run:
        await _run_dispatch_once(bridge, merger=merger)

    mock_run.assert_called_once_with(
        ["xdg-open", "https://mail.google.com/mail/u/0/#inbox/n1"],
        check=False,
    )


async def test_notification_clicked_legacy_synonym() -> None:
    """The legacy ``notification_clicked`` message resolves the same way."""
    bridge = MockBridge()
    ui = UIState(bridge)
    merger = Screen2Merger(ui)
    merger.register_url("n1", "https://example.com/legacy")

    await bridge.inject(NotificationClickedMsg(data=NotificationClickedData(id="n1")))

    with patch("deskstation.main.subprocess.run") as mock_run:
        await _run_dispatch_once(bridge, merger=merger)

    mock_run.assert_called_once_with(
        ["xdg-open", "https://example.com/legacy"],
        check=False,
    )


async def test_meeting_join_runs_xdg_open() -> None:
    now = datetime.now(UTC)
    meeting = Meeting(
        id="m1",
        title="Standup",
        start=now + timedelta(minutes=5),
        end=now + timedelta(minutes=20),
        join_url="https://meet.google.com/abc-defg",
    )
    poller = _make_calendar_poller_with_meeting(meeting)
    bridge = MockBridge()

    await bridge.inject(MeetingJoinMsg(data=MeetingJoinData(id="m1")))

    with patch("deskstation.main.subprocess.run") as mock_run:
        await _run_dispatch_once(bridge, calendar_poller=poller)

    mock_run.assert_called_once_with(
        ["xdg-open", "https://meet.google.com/abc-defg"],
        check=False,
    )


async def test_unknown_id_logs_warning_no_xdg_open() -> None:
    """An unknown notification id is a no-op (warning only) — no xdg-open."""
    bridge = MockBridge()
    ui = UIState(bridge)
    merger = Screen2Merger(ui)
    # Index intentionally empty.

    await bridge.inject(NotificationActionMsg(data=NotificationActionData(id="unknown")))

    with patch("deskstation.main.subprocess.run") as mock_run:
        await _run_dispatch_once(bridge, merger=merger)

    mock_run.assert_not_called()


async def test_no_merger_logs_warning_no_xdg_open() -> None:
    """When merger is None (Google not configured), notification_action is a silent no-op."""
    bridge = MockBridge()

    await bridge.inject(NotificationActionMsg(data=NotificationActionData(id="anything")))

    with patch("deskstation.main.subprocess.run") as mock_run:
        await _run_dispatch_once(bridge, merger=None, calendar_poller=None)

    mock_run.assert_not_called()


async def test_meeting_join_unknown_id_no_xdg_open() -> None:
    poller = _make_calendar_poller_with_meeting(
        Meeting(
            id="m1",
            title="Some",
            start=datetime.now(UTC) + timedelta(minutes=5),
            end=datetime.now(UTC) + timedelta(minutes=20),
            join_url="https://meet.google.com/x",
        )
    )
    bridge = MockBridge()
    await bridge.inject(MeetingJoinMsg(data=MeetingJoinData(id="does-not-exist")))

    with patch("deskstation.main.subprocess.run") as mock_run:
        await _run_dispatch_once(bridge, calendar_poller=poller)

    mock_run.assert_not_called()


async def test_unknown_envelope_type_logs_and_continues() -> None:
    """A future envelope class not in ``_HANDLERS`` must not crash the loop.

    Locks in the openness of the handler table: adding a new envelope type
    in protocol.py without a matching handler should degrade to a logged
    warning, not a dispatcher exception.
    """

    class _FakeData:
        id = "f1"

    class _UnknownEnvelope:
        """Not a Pydantic model, deliberately not in ``_HANDLERS``."""

        data = _FakeData()

    bridge = MockBridge()
    # Bypass MockBridge.inject() typing — the whole point is that this
    # envelope class isn't in the Envelope union.
    await bridge._inbound.put(_UnknownEnvelope())  # type: ignore[arg-type]
    # Follow with a real envelope to prove the loop kept going.
    await bridge.inject(NotificationActionMsg(data=NotificationActionData(id="real")))

    ui = UIState(bridge)
    merger = Screen2Merger(ui)
    merger.register_url("real", "https://example.com/after-unknown")

    with patch("deskstation.main.subprocess.run") as mock_run:
        await _run_dispatch_once(bridge, merger=merger)

    # The loop survived the unknown envelope and dispatched the next one.
    mock_run.assert_called_once_with(
        ["xdg-open", "https://example.com/after-unknown"],
        check=False,
    )
