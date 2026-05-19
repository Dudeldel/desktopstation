"""Tests for the real GoogleChatPoller (M5.3).

Uses a hand-rolled fake GoogleChatClient — the real client is covered by
test_gchat_client.py via the service_factory hook.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from deskstation.bridge.mock_bridge import MockBridge
from deskstation.bridge.protocol import Screen2Msg
from deskstation.clients.gchat import (
    ChatMessage,
    GoogleChatAuthError,
    GoogleChatTransientError,
    Space,
)
from deskstation.pollers.gchat import GoogleChatPoller
from deskstation.ui_state import UIState

_MY_EMAIL = "jakub@example.com"


class _FakeGoogleChatClient:
    """Programmable fake.

    ``spaces_responses`` is FIFO; each ``list_spaces`` call pops the
    next entry. ``messages_responses`` maps ``space_name`` -> FIFO list
    of responses for that space.
    """

    def __init__(
        self,
        spaces_responses: list[list[Space] | Exception],
        messages_responses: dict[str, list[list[ChatMessage] | Exception]] | None = None,
    ) -> None:
        self._spaces_responses = list(spaces_responses)
        self._messages_responses: dict[str, list[list[ChatMessage] | Exception]] = {
            k: list(v) for k, v in (messages_responses or {}).items()
        }
        self.list_spaces_calls = 0
        self.list_messages_calls: list[tuple[str, datetime]] = []

    async def list_spaces(self) -> list[Space]:
        self.list_spaces_calls += 1
        if not self._spaces_responses:
            raise AssertionError("FakeGoogleChatClient: no more queued spaces responses")
        nxt = self._spaces_responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt

    async def list_recent_messages(self, space_name: str, since: datetime) -> list[ChatMessage]:
        self.list_messages_calls.append((space_name, since))
        queue = self._messages_responses.get(space_name)
        if not queue:
            raise AssertionError(
                f"FakeGoogleChatClient: no queued messages response for {space_name}"
            )
        nxt = queue.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


def _dm(name: str = "spaces/dm1") -> Space:
    return Space(name=name, display_name="(direct message)", type="DIRECT_MESSAGE")


def _room(name: str = "spaces/room1") -> Space:
    return Space(name=name, display_name="Engineering", type="SPACE")


def _msg(
    name: str,
    text: str,
    sender: str = "Alice",
    space_name: str = "spaces/dm1",
    age: timedelta = timedelta(minutes=5),
) -> ChatMessage:
    return ChatMessage(
        name=name,
        space_name=space_name,
        sender_display_name=sender,
        text=text,
        create_time=datetime.now(UTC) - age,
    )


def _make_poller(
    client: _FakeGoogleChatClient,
) -> tuple[GoogleChatPoller, UIState, MockBridge]:
    bridge = MockBridge()
    ui = UIState(bridge)
    poller = GoogleChatPoller(ui, client, my_email=_MY_EMAIL, interval_sec=60.0)  # type: ignore[arg-type]
    return poller, ui, bridge


async def test_dm_messages_always_included() -> None:
    dm = _dm()
    client = _FakeGoogleChatClient(
        spaces_responses=[[dm]],
        messages_responses={
            dm.name: [
                [
                    _msg(f"{dm.name}/messages/m1", text="plain hi", space_name=dm.name),
                    _msg(
                        f"{dm.name}/messages/m2",
                        text="no mention either",
                        sender="Bob",
                        space_name=dm.name,
                    ),
                ]
            ]
        },
    )
    poller, _, bridge = _make_poller(client)

    await poller.tick()

    msg = await bridge.received()
    assert isinstance(msg, Screen2Msg)
    notifs = msg.data.notifications
    assert [n.id for n in notifs] == [
        f"{dm.name}/messages/m1",
        f"{dm.name}/messages/m2",
    ]
    assert notifs[0].source == "chat"
    assert notifs[0].sender == "Alice"
    assert notifs[0].preview == "plain hi"


async def test_space_messages_filtered_to_mentions_only() -> None:
    room = _room()
    client = _FakeGoogleChatClient(
        spaces_responses=[[room]],
        messages_responses={
            room.name: [
                [
                    _msg(
                        f"{room.name}/messages/m1",
                        text="general chatter, no ping",
                        space_name=room.name,
                    ),
                    _msg(
                        f"{room.name}/messages/m2",
                        text=f"hey @{_MY_EMAIL.split('@')[0]} could you check?",
                        space_name=room.name,
                    ),
                ]
            ]
        },
    )
    poller, _, bridge = _make_poller(client)

    await poller.tick()

    msg = await bridge.received()
    assert isinstance(msg, Screen2Msg)
    notifs = msg.data.notifications
    # Only the @-mention message is included.
    assert [n.id for n in notifs] == [f"{room.name}/messages/m2"]


async def test_poller_handles_auth_error_short_circuits() -> None:
    client = _FakeGoogleChatClient(
        spaces_responses=[GoogleChatAuthError("401")],
    )
    poller, _, _ = _make_poller(client)

    with pytest.raises(GoogleChatAuthError):
        await poller.tick()

    assert poller.auth_failed is True
    calls_after_first = client.list_spaces_calls
    # Second tick must short-circuit and not touch the client.
    await poller.tick()
    assert client.list_spaces_calls == calls_after_first


async def test_poller_handles_transient_error_on_list_spaces() -> None:
    client = _FakeGoogleChatClient(
        spaces_responses=[GoogleChatTransientError("503")],
    )
    poller, ui, _ = _make_poller(client)
    set_screen_2 = MagicMock()
    ui.set_screen_2 = set_screen_2  # type: ignore[method-assign]

    await poller.tick()  # must not raise

    set_screen_2.assert_not_called()
    # _last_check must not have moved forward since we never completed a pass.
    # (We can't assert exact value, but the next tick should fetch from the
    # same window — exercised below.)


async def test_poller_skips_individual_space_on_transient_error() -> None:
    good = _dm("spaces/dm_good")
    bad = _dm("spaces/dm_bad")
    client = _FakeGoogleChatClient(
        spaces_responses=[[good, bad]],
        messages_responses={
            good.name: [[_msg(f"{good.name}/messages/m1", text="hello", space_name=good.name)]],
            bad.name: [GoogleChatTransientError("503")],
        },
    )
    poller, _, bridge = _make_poller(client)

    await poller.tick()  # must not raise

    msg = await bridge.received()
    assert isinstance(msg, Screen2Msg)
    notifs = msg.data.notifications
    assert [n.id for n in notifs] == [f"{good.name}/messages/m1"]


async def test_poller_updates_last_check_after_success() -> None:
    dm = _dm()
    client = _FakeGoogleChatClient(
        spaces_responses=[[dm], [dm]],
        messages_responses={
            dm.name: [
                [_msg(f"{dm.name}/messages/m1", text="hi", space_name=dm.name)],
                [],  # second tick: empty result.
            ]
        },
    )
    poller, _, _ = _make_poller(client)

    before = datetime.now(UTC)
    await poller.tick()
    after_first = datetime.now(UTC)

    # The since timestamp used on the second tick must be ≥ when the first
    # tick completed.
    await poller.tick()
    assert len(client.list_messages_calls) == 2
    first_since = client.list_messages_calls[0][1]
    second_since = client.list_messages_calls[1][1]
    # The first since is roughly 1h ago (constructor default), the second
    # since must be >= the time we finished the first tick.
    assert first_since < before
    assert second_since >= before
    assert second_since <= after_first + timedelta(seconds=5)
