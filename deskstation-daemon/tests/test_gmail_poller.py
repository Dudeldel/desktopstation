"""Tests for the real GmailPoller (M5.2).

Uses a hand-rolled fake GmailClient — the real client is covered by
test_gmail_client.py via the service_factory hook, so here we only verify
poller wiring.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from deskstation.bridge.mock_bridge import MockBridge
from deskstation.bridge.protocol import Screen2Msg
from deskstation.clients.gmail import GmailAuthError, GmailMessage, GmailTransientError
from deskstation.pollers.gmail import GmailPoller, _format_time_ago
from deskstation.ui_state import UIState


class _FakeGmailClient:
    """Minimal GmailClient stand-in: FIFO queue of responses, like the
    bitbucket poller fake. Each call pops the next response off the queue.
    """

    def __init__(self, responses: list[list[GmailMessage] | Exception]) -> None:
        self._responses = list(responses)
        self.calls: list[str] = []

    async def list_unread_recent(
        self, query: str = "is:unread newer_than:1d"
    ) -> list[GmailMessage]:
        self.calls.append(query)
        if not self._responses:
            raise AssertionError("FakeGmailClient: no more queued responses")
        nxt = self._responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


def _msg(msg_id: str, sender: str = "alice@example.com", subject: str = "subj") -> GmailMessage:
    return GmailMessage(
        id=msg_id,
        sender=sender,
        subject=subject,
        snippet="snip",
        received_at=datetime.now(UTC) - timedelta(minutes=5),
    )


def _make_poller(
    responses: list[list[GmailMessage] | Exception],
) -> tuple[GmailPoller, UIState, MockBridge, _FakeGmailClient]:
    bridge = MockBridge()
    ui = UIState(bridge)
    client = _FakeGmailClient(responses)
    poller = GmailPoller(ui, client, interval_sec=60.0)  # type: ignore[arg-type]
    return poller, ui, bridge, client


async def test_poller_pushes_screen_2() -> None:
    msgs = [_msg("m1", sender="Alice", subject="Hello"), _msg("m2", sender="Bob")]
    poller, _ui, bridge, _ = _make_poller([msgs])

    await poller.tick()

    msg = await bridge.received()
    assert isinstance(msg, Screen2Msg)
    assert [n.id for n in msg.data.notifications] == ["m1", "m2"]
    assert msg.data.notifications[0].source == "gmail"
    assert msg.data.notifications[0].sender == "Alice"
    assert msg.data.notifications[0].preview == "Hello"


async def test_poller_handles_auth_error_then_short_circuits() -> None:
    poller, _, _, client = _make_poller([GmailAuthError("401")])

    with pytest.raises(GmailAuthError):
        await poller.tick()

    assert poller.auth_failed is True
    calls_after_first = len(client.calls)
    # Second tick must short-circuit and not touch the client.
    await poller.tick()
    assert len(client.calls) == calls_after_first


async def test_poller_handles_transient_error() -> None:
    poller, ui, _, _ = _make_poller([GmailTransientError("503")])
    set_screen_2 = MagicMock()
    ui.set_screen_2 = set_screen_2  # type: ignore[method-assign]

    await poller.tick()  # must not raise

    set_screen_2.assert_not_called()


async def test_poller_exposes_latest_notifications() -> None:
    msgs = [_msg("m1"), _msg("m2")]
    poller, _, _bridge, _ = _make_poller([msgs])

    await poller.tick()

    latest = poller.latest_notifications()
    assert [n.id for n in latest] == ["m1", "m2"]
    # Mutating the returned list must not affect the poller's internal state.
    latest.clear()
    assert [n.id for n in poller.latest_notifications()] == ["m1", "m2"]


# ---------------------------------------------------------------------------
# _format_time_ago
# ---------------------------------------------------------------------------


def test_format_time_ago_recent() -> None:
    received = datetime.now(UTC) - timedelta(minutes=5, seconds=2)
    assert _format_time_ago(received) == "5m temu"


def test_format_time_ago_hours() -> None:
    received = datetime.now(UTC) - timedelta(hours=2, minutes=5)
    assert _format_time_ago(received) == "2h temu"


def test_format_time_ago_days() -> None:
    received = datetime.now(UTC) - timedelta(hours=25)
    assert _format_time_ago(received) == "1d temu"
