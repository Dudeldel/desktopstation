"""M5.8 integration tests: end-to-end wiring of M5 sources.

Mirrors :mod:`tests.test_integration_m4`'s pattern (full client / poller
/ UIState / MockBridge chain), but for the M5 stack:

* Gmail + Chat pollers both routed through the :class:`Screen2Merger` so
  a single merged :class:`Screen2Msg` reaches the bridge. The chat
  filter excludes a non-mention SPACE message — proving the merger is
  not a pass-through.
* A :class:`CalendarPoller` populated via the ``service_factory`` hook
  on :class:`GoogleCalendarClient`, then a ``meeting_join{id}`` event
  injected on the bridge — the dispatcher must resolve the id to the
  meeting's ``join_url`` and shell out to ``xdg-open``.

The Google clients are stubbed via the same ``service_factory`` injection
hook used in :mod:`tests.test_gmail_client` / :mod:`tests.test_gchat_client`
/ :mod:`tests.test_gcal_client` — no real HTTP, no live discovery doc.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from deskstation.bridge.heartbeat import ConnectionMonitor
from deskstation.bridge.mock_bridge import MockBridge
from deskstation.bridge.protocol import (
    MeetingJoinData,
    MeetingJoinMsg,
    Screen2Msg,
)
from deskstation.clients.gcal import GoogleCalendarClient
from deskstation.clients.gchat import ChatMessage, Space
from deskstation.clients.gmail import GmailClient
from deskstation.engines.screen2_merger import Screen2Merger
from deskstation.main import DispatchContext, _dispatch
from deskstation.pollers.calendar import CalendarPoller
from deskstation.pollers.gchat import GoogleChatPoller
from deskstation.pollers.gmail import GmailPoller
from deskstation.store.api_cache import ApiCache
from deskstation.ui_state import UIState

_MY_EMAIL = "me@example.com"


# ---------------------------------------------------------------------------
# Gmail fake service (service_factory shape)
# ---------------------------------------------------------------------------


class _FakeExec:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def execute(self) -> dict[str, Any]:
        return self._payload


class _FakeGmailService:
    """Models the ``users().messages().list / get`` chain."""

    def __init__(
        self,
        list_response: dict[str, Any],
        get_responses: dict[str, dict[str, Any]],
    ) -> None:
        self._list_response = list_response
        self._get_responses = get_responses

    def users(self) -> _FakeGmailService:
        return self

    def messages(self) -> _FakeGmailService:
        return self

    def list(self, **_kwargs: Any) -> _FakeExec:
        return _FakeExec(self._list_response)

    def get(self, **kwargs: Any) -> _FakeExec:
        msg_id = kwargs["id"]
        return _FakeExec(self._get_responses[msg_id])


def _gmail_detail(
    msg_id: str,
    from_header: str,
    subject: str,
    snippet: str,
    internal_date_ms: str,
) -> dict[str, Any]:
    return {
        "id": msg_id,
        "snippet": snippet,
        "internalDate": internal_date_ms,
        "payload": {
            "headers": [
                {"name": "From", "value": from_header},
                {"name": "Subject", "value": subject},
            ]
        },
    }


# ---------------------------------------------------------------------------
# Chat fake — uses the in-process ChatMessage / Space dataclasses by
# stubbing the GoogleChatClient methods directly rather than the service
# chain. The methods we replace are exactly what GoogleChatPoller calls.
# ---------------------------------------------------------------------------


class _StubGoogleChatClient:
    """Lightweight stand-in for :class:`GoogleChatClient`.

    The real client is exercised by ``test_gchat_client.py`` already;
    here we only need to feed the poller through the merger.
    """

    def __init__(
        self,
        spaces: list[Space],
        messages_by_space: dict[str, list[ChatMessage]],
    ) -> None:
        self._spaces = spaces
        self._messages_by_space = messages_by_space

    async def list_spaces(self) -> list[Space]:
        return list(self._spaces)

    async def list_recent_messages(self, space_name: str, since: datetime) -> list[ChatMessage]:
        return list(self._messages_by_space.get(space_name, []))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_gmail_chat_merge_to_screen_2(tmp_path: Path) -> None:
    """Gmail + Chat clients (mocked) → pollers → Screen2Merger → UIState → MockBridge.

    Asserts both gmail-sourced and chat-sourced notifications land in a
    single Screen2Msg with the expected priority ordering and that the
    non-mention SPACE message is filtered out (proving the merger isn't
    a pass-through).
    """
    cache = ApiCache(tmp_path / "cache.sqlite3")
    bridge = MockBridge()
    ui = UIState(bridge)
    merger = Screen2Merger(ui)

    # Gmail: two unread messages.
    list_resp = {"messages": [{"id": "g1"}, {"id": "g2"}]}
    detail_g1 = _gmail_detail(
        "g1",
        "Alice Example <alice@example.com>",
        "Hello world",
        "Snippet for g1",
        "1700000000000",
    )
    detail_g2 = _gmail_detail(
        "g2",
        "bob@example.com",
        "Re: status",
        "Snippet for g2",
        "1700000060000",
    )
    gmail_service = _FakeGmailService(list_resp, {"g1": detail_g1, "g2": detail_g2})
    gmail_client = GmailClient(
        credentials=MagicMock(),
        cache=cache,
        service_factory=lambda _c: gmail_service,
    )
    gmail_poller = GmailPoller(ui, gmail_client, interval_sec=60.0, merger=merger)

    # Chat: one DM message (always included) + one non-mention SPACE
    # message (must be filtered out).
    dm = Space(name="spaces/dm1", display_name="(direct message)", type="DIRECT_MESSAGE")
    room = Space(name="spaces/room1", display_name="Engineering", type="SPACE")
    now = datetime.now(UTC)
    dm_msg = ChatMessage(
        name="spaces/dm1/messages/c1",
        space_name="spaces/dm1",
        sender_display_name="Carol",
        text="hi there",
        create_time=now - timedelta(minutes=2),
    )
    room_msg = ChatMessage(
        name="spaces/room1/messages/c2",
        space_name="spaces/room1",
        sender_display_name="Dan",
        text="general chatter, no ping for anyone",
        create_time=now - timedelta(minutes=3),
    )
    gchat_stub = _StubGoogleChatClient(
        spaces=[dm, room],
        messages_by_space={
            dm.name: [dm_msg],
            room.name: [room_msg],
        },
    )
    gchat_poller = GoogleChatPoller(
        ui,
        gchat_stub,  # type: ignore[arg-type]
        my_email=_MY_EMAIL,
        interval_sec=60.0,
        merger=merger,
    )

    # Tick both. UIState coalesces sends per screen, so after each tick a
    # fresh Screen2Msg is sent.
    await gmail_poller.tick()
    await gchat_poller.tick()

    # Drain the bridge. Each tick produces one Screen2Msg; the second
    # contains the merged result (gmail still present + chat added).
    msgs: list[Screen2Msg] = []
    while True:
        try:
            env = await asyncio.wait_for(bridge.received(), timeout=0.2)
        except TimeoutError:
            break
        assert isinstance(env, Screen2Msg), (
            f"expected Screen2Msg, got {type(env).__name__}: {env!r}"
        )
        msgs.append(env)

    assert msgs, "expected at least one Screen2Msg on the bridge"
    final = msgs[-1]

    # 2 gmail + 1 chat DM = 3 notifications. The non-mention SPACE message
    # is excluded by the poller, never reaches the merger.
    ids = [n.id for n in final.data.notifications]
    sources = {n.id: n.source for n in final.data.notifications}
    assert len(final.data.notifications) == 3, (
        f"expected 3 merged notifications, got {len(final.data.notifications)}: {ids}"
    )
    assert set(ids) == {"g1", "g2", "spaces/dm1/messages/c1"}
    assert sources["spaces/dm1/messages/c1"] == "chat"
    assert sources["g1"] == "gmail"
    assert "spaces/room1/messages/c2" not in ids, (
        "non-mention SPACE message must be filtered out by GoogleChatPoller"
    )

    # Priority ordering: dbus > gmail > gchat. With no dbus source, gmail
    # entries precede chat entries in the merged list.
    first_chat_idx = next(i for i, n in enumerate(final.data.notifications) if n.source == "chat")
    last_gmail_idx = max(i for i, n in enumerate(final.data.notifications) if n.source == "gmail")
    assert last_gmail_idx < first_chat_idx, (
        "gmail notifications must rank before chat in the merger ordering"
    )

    # Deep-link registration: both sources register URLs through the merger.
    assert merger.lookup_url("g1") == "https://mail.google.com/mail/u/0/#inbox/g1"
    chat_url = merger.lookup_url("spaces/dm1/messages/c1")
    assert chat_url is not None and "spaces%2Fdm1" in chat_url


async def test_meeting_join_via_dispatcher_runs_xdg_open(tmp_path: Path) -> None:
    """End-to-end: CalendarPoller populated via service_factory → MeetingJoinMsg → xdg-open."""
    cache = ApiCache(tmp_path / "cache.sqlite3")
    bridge = MockBridge()
    ui = UIState(bridge)

    # Meeting starts in 5 minutes; the gcal client returns a Calendar API
    # event shape, the client parses it, the poller stashes the result.
    now = datetime.now(UTC)
    start = now + timedelta(minutes=5)
    end = now + timedelta(minutes=35)

    def _iso(dt: datetime) -> str:
        return dt.isoformat().replace("+00:00", "Z")

    events_resp = {
        "items": [
            {
                "id": "evt-42",
                "summary": "Sprint planning",
                "hangoutLink": "https://meet.google.com/xyz-abcd-efg",
                "start": {"dateTime": _iso(start)},
                "end": {"dateTime": _iso(end)},
            }
        ]
    }

    class _FakeCalendarEvents:
        def list(self, **_kwargs: Any) -> _FakeExec:
            return _FakeExec(events_resp)

    class _FakeCalendarService:
        def events(self) -> _FakeCalendarEvents:
            return _FakeCalendarEvents()

    calendar_client = GoogleCalendarClient(
        credentials=MagicMock(),
        cache=cache,
        service_factory=lambda _c: _FakeCalendarService(),
    )
    calendar_poller = CalendarPoller(
        ui,
        calendar_client,
        near_interval_sec=60.0,
        far_interval_sec=300.0,
        near_window_sec=1800.0,
    )

    # Populate _meetings.
    await calendar_poller.tick()
    assert calendar_poller.lookup_meeting_url("evt-42") == "https://meet.google.com/xyz-abcd-efg"

    # Inject a MeetingJoinMsg and run the dispatcher just long enough to
    # consume it. Mirrors the pattern in tests/test_dispatch_actions.py.
    await bridge.inject(MeetingJoinMsg(data=MeetingJoinData(id="evt-42")))

    monitor = ConnectionMonitor()
    pomodoro = MagicMock()

    with patch("deskstation.main.subprocess.run") as mock_run:
        ctx = DispatchContext(
            bridge=bridge,
            monitor=monitor,
            ui_state=ui,
            pomodoro=pomodoro,
            merger=None,
            calendar_poller=calendar_poller,
        )
        task = asyncio.create_task(_dispatch(ctx))
        # MockBridge.stream() polls with a 50 ms timeout; 200 ms is enough
        # for a single envelope to be consumed.
        await asyncio.sleep(0.2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    mock_run.assert_called_once_with(
        ["xdg-open", "https://meet.google.com/xyz-abcd-efg"],
        check=False,
    )
