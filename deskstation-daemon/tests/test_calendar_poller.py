"""Tests for the real CalendarPoller (M5.6).

Uses a hand-rolled fake GoogleCalendarClient. The real client is covered
by test_gcal_client.py via the service_factory hook, so here we only
verify poller wiring + adaptive-interval logic.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from deskstation.bridge.mock_bridge import MockBridge
from deskstation.bridge.protocol import Screen1Msg
from deskstation.clients.gcal import (
    GoogleCalendarAuthError,
    GoogleCalendarTransientError,
    Meeting,
)
from deskstation.pollers.calendar import CalendarPoller
from deskstation.ui_state import UIState


class _FakeCalendarClient:
    def __init__(self, responses: list[list[Meeting] | Exception]) -> None:
        self._responses = list(responses)
        self.calls: list[int] = []

    async def list_upcoming(self, window_hours: int = 36) -> list[Meeting]:
        self.calls.append(window_hours)
        if not self._responses:
            raise AssertionError("FakeCalendarClient: no more queued responses")
        nxt = self._responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


def _meeting(
    event_id: str,
    title: str,
    start: datetime,
    end: datetime,
    join_url: str = "https://meet.google.com/abc-defg-hij",
) -> Meeting:
    return Meeting(
        id=event_id,
        title=title,
        start=start,
        end=end,
        join_url=join_url,
    )


def _make_poller(
    responses: list[list[Meeting] | Exception],
    *,
    near_interval_sec: float = 60.0,
    far_interval_sec: float = 300.0,
    near_window_sec: float = 30 * 60,
) -> tuple[CalendarPoller, UIState, MockBridge, _FakeCalendarClient]:
    bridge = MockBridge()
    ui = UIState(bridge)
    client = _FakeCalendarClient(responses)
    poller = CalendarPoller(
        ui,
        client,  # type: ignore[arg-type]
        near_interval_sec=near_interval_sec,
        far_interval_sec=far_interval_sec,
        near_window_sec=near_window_sec,
    )
    return poller, ui, bridge, client


async def test_tick_pushes_meeting_bar() -> None:
    now = datetime.now(UTC)
    start = now + timedelta(minutes=5)
    end = now + timedelta(minutes=20)
    meeting = _meeting(
        "ev1",
        "Standup",
        start,
        end,
        join_url="https://meet.google.com/standup",
    )
    poller, _ui, bridge, _ = _make_poller([[meeting]])

    await poller.tick()

    msg = await bridge.received()
    assert isinstance(msg, Screen1Msg)
    assert msg.data.next_meeting is not None
    bar = msg.data.next_meeting
    assert bar.title == "Standup"
    assert bar.join_url == "https://meet.google.com/standup"
    # Allow a tiny tolerance because ``now`` inside the poller is read
    # again with ``datetime.now(UTC)``.
    assert bar.in_minutes in (4, 5)


def test_compute_interval_near() -> None:
    poller, _, _, _ = _make_poller([])
    now = datetime.now(UTC)
    poller._meetings = [
        _meeting("ev1", "Soon", now + timedelta(minutes=10), now + timedelta(minutes=25)),
    ]
    assert poller._compute_next_interval() == 60.0


def test_compute_interval_far() -> None:
    poller, _, _, _ = _make_poller([])
    now = datetime.now(UTC)
    poller._meetings = [
        _meeting("ev1", "Later", now + timedelta(hours=2), now + timedelta(hours=3)),
    ]
    assert poller._compute_next_interval() == 300.0


def test_compute_interval_no_meetings() -> None:
    poller, _, _, _ = _make_poller([])
    assert poller._meetings == []
    assert poller._compute_next_interval() == 300.0


def test_compute_interval_ongoing_meeting() -> None:
    poller, _, _, _ = _make_poller([])
    now = datetime.now(UTC)
    poller._meetings = [
        _meeting(
            "ev1",
            "Ongoing",
            now - timedelta(minutes=5),
            now + timedelta(minutes=25),
        ),
    ]
    # Ongoing meeting → near interval per the docstring.
    assert poller._compute_next_interval() == 60.0


async def test_auth_error_short_circuits() -> None:
    poller, _, _, client = _make_poller([GoogleCalendarAuthError("401")])

    with pytest.raises(GoogleCalendarAuthError):
        await poller.tick()

    assert poller.auth_failed is True
    calls_after_first = len(client.calls)
    # Second tick must short-circuit and not touch the client.
    await poller.tick()
    assert len(client.calls) == calls_after_first


async def test_transient_error_leaves_state_intact() -> None:
    poller, ui, _, _ = _make_poller([GoogleCalendarTransientError("503")])
    set_screen_1 = MagicMock()
    ui.set_screen_1 = set_screen_1  # type: ignore[method-assign]

    await poller.tick()  # must not raise

    set_screen_1.assert_not_called()


async def test_lookup_meeting_url_returns_join_url() -> None:
    """After a tick populates _meetings, lookup returns the right URL."""
    now = datetime.now(UTC)
    start = now + timedelta(minutes=5)
    end = now + timedelta(minutes=20)
    meeting = _meeting(
        "ev-42",
        "Standup",
        start,
        end,
        join_url="https://meet.google.com/standup-link",
    )
    poller, _ui, bridge, _ = _make_poller([[meeting]])

    await poller.tick()
    await bridge.received()  # drain emission

    assert poller.lookup_meeting_url("ev-42") == "https://meet.google.com/standup-link"


async def test_lookup_meeting_url_unknown_returns_none() -> None:
    poller, _, _, _ = _make_poller([])
    assert poller.lookup_meeting_url("does-not-exist") is None


async def test_no_future_meetings_clears_meeting_bar() -> None:
    now = datetime.now(UTC)
    # Only past-and-ended meeting in response.
    past = _meeting(
        "ev_past",
        "Past meeting",
        now - timedelta(hours=2),
        now - timedelta(hours=1),
    )
    poller, _ui, bridge, _ = _make_poller([[past]])

    await poller.tick()

    msg = await bridge.received()
    assert isinstance(msg, Screen1Msg)
    assert msg.data.next_meeting is None
