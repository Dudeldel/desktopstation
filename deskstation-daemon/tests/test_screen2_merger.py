"""Tests for the Screen2Merger (M5.5).

The merger owns the ``screen_2`` dispatch. Each source pushes its current
list via ``update(source_key, notifications)``; the merger dedupes by id
(highest-priority source wins), sorts by ``(priority_rank, in_source_index)``,
caps at ``MAX_ITEMS``, and calls ``UIState.set_screen_2`` exactly once.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

from deskstation.bridge.mock_bridge import MockBridge
from deskstation.bridge.protocol import Notification, Screen2Msg
from deskstation.clients.gchat import ChatMessage, Space
from deskstation.clients.gmail import GmailMessage
from deskstation.engines.screen2_merger import Screen2Merger
from deskstation.pollers.gchat import GoogleChatPoller
from deskstation.pollers.gmail import GmailPoller
from deskstation.ui_state import UIState


def _n(
    notification_id: str,
    *,
    source: str = "gmail",
    sender: str = "Alice",
    preview: str = "hi",
) -> Notification:
    return Notification(
        source=source,  # type: ignore[arg-type]
        sender=sender,
        preview=preview,
        time_ago="just now",
        id=notification_id,
    )


async def test_single_source_push_emits_to_ui() -> None:
    bridge = MockBridge()
    ui = UIState(bridge)
    merger = Screen2Merger(ui)

    n1 = _n("m1", source="gmail")
    n2 = _n("m2", source="gmail")

    merger.update("gmail", [n1, n2])

    msg = await bridge.received()
    assert isinstance(msg, Screen2Msg)
    assert [n.id for n in msg.data.notifications] == ["m1", "m2"]


async def test_within_source_dedupe_by_id_last_write_wins() -> None:
    """Re-updating the same source with the same id replaces the prior entry.

    Dedup is scoped to ``(source_key, id)``: two calls to ``update`` for
    the same source key replace that source's list entirely, so the second
    push wins.
    """
    bridge = MockBridge()
    ui = UIState(bridge)
    merger = Screen2Merger(ui)

    n_first = _n("x", source="gmail", sender="first")
    n_second = _n("x", source="gmail", sender="second")

    merger.update("gmail", [n_first])
    await bridge.received()  # drain the first emission
    merger.update("gmail", [n_second])

    msg = await bridge.received()
    assert isinstance(msg, Screen2Msg)
    assert len(msg.data.notifications) == 1
    assert msg.data.notifications[0].sender == "second"


async def test_dedup_is_scoped_to_source() -> None:
    """Different sources can emit notifications with the same id without collision.

    Dedup is keyed on ``(source_key, id)`` so cross-source id collisions
    (e.g. dbus and gmail both emitting id="1") do not shadow each other —
    both survive into the merged output.
    """
    bridge = MockBridge()
    ui = UIState(bridge)
    merger = Screen2Merger(ui)

    n_gmail = _n("X", source="gmail", sender="from_gmail")
    n_dbus = _n("X", source="system", sender="from_dbus")

    merger.update("gmail", [n_gmail])
    await bridge.received()  # drain the gmail-only emission
    merger.update("dbus", [n_dbus])

    msg = await bridge.received()
    assert isinstance(msg, Screen2Msg)
    # Both survive — same id, different source → no shadow.
    assert len(msg.data.notifications) == 2
    senders = {n.sender for n in msg.data.notifications}
    assert senders == {"from_gmail", "from_dbus"}
    # dbus ranks above gmail, so it appears first.
    assert msg.data.notifications[0].sender == "from_dbus"
    assert msg.data.notifications[1].sender == "from_gmail"


async def test_source_priority_order() -> None:
    bridge = MockBridge()
    ui = UIState(bridge)
    merger = Screen2Merger(ui)

    n_d = _n("d1", source="system", sender="dbus")
    n_g = _n("g1", source="gmail", sender="gmail")
    n_c = _n("c1", source="chat", sender="chat")

    merger.update("gmail", [n_g])
    await bridge.received()
    merger.update("gchat", [n_c])
    await bridge.received()
    merger.update("dbus", [n_d])

    msg = await bridge.received()
    assert isinstance(msg, Screen2Msg)
    assert [n.id for n in msg.data.notifications] == ["d1", "g1", "c1"]


async def test_in_source_order_preserved() -> None:
    bridge = MockBridge()
    ui = UIState(bridge)
    merger = Screen2Merger(ui)

    n_a = _n("a", source="gmail")
    n_b = _n("b", source="gmail")
    n_c = _n("c", source="gmail")

    merger.update("gmail", [n_a, n_b, n_c])

    msg = await bridge.received()
    assert isinstance(msg, Screen2Msg)
    assert [n.id for n in msg.data.notifications] == ["a", "b", "c"]


async def test_cap_at_16_items() -> None:
    bridge = MockBridge()
    ui = UIState(bridge)
    merger = Screen2Merger(ui)

    big = [_n(f"m{i:02d}", source="gmail") for i in range(20)]
    merger.update("gmail", big)

    msg = await bridge.received()
    assert isinstance(msg, Screen2Msg)
    assert len(msg.data.notifications) == Screen2Merger.MAX_ITEMS
    # Preserves in-source order, so the first 16 are kept.
    assert [n.id for n in msg.data.notifications] == [f"m{i:02d}" for i in range(16)]


async def test_replace_source_drops_old_entries() -> None:
    bridge = MockBridge()
    ui = UIState(bridge)
    merger = Screen2Merger(ui)

    merger.update("gmail", [_n("a", source="gmail"), _n("b", source="gmail")])
    await bridge.received()

    merger.update("gmail", [_n("c", source="gmail")])
    msg = await bridge.received()
    assert isinstance(msg, Screen2Msg)
    assert [n.id for n in msg.data.notifications] == ["c"]


async def test_update_unknown_source_key_is_accepted() -> None:
    bridge = MockBridge()
    ui = UIState(bridge)
    merger = Screen2Merger(ui)

    n_known = _n("k1", source="gmail")
    n_future = _n("f1", source="system")

    merger.update("gmail", [n_known])
    await bridge.received()
    merger.update("future_source", [n_future])

    msg = await bridge.received()
    assert isinstance(msg, Screen2Msg)
    # The unknown source ranks below all listed sources → "f1" is last.
    assert [n.id for n in msg.data.notifications] == ["k1", "f1"]


# ---------------------------------------------------------------------------
# Poller integration with the merger.
# ---------------------------------------------------------------------------


class _FakeGmailClient:
    def __init__(self, messages: list[GmailMessage]) -> None:
        self._messages = messages

    async def list_unread_recent(
        self, query: str = "is:unread newer_than:1d"
    ) -> list[GmailMessage]:
        return list(self._messages)


def _gmail_msg(msg_id: str) -> GmailMessage:
    return GmailMessage(
        id=msg_id,
        sender="Alice",
        subject="subj",
        snippet="snip",
        received_at=datetime.now(UTC) - timedelta(minutes=5),
    )


async def test_gmail_poller_with_merger_routes_through_it() -> None:
    bridge = MockBridge()
    ui = UIState(bridge)
    merger = MagicMock(spec=Screen2Merger)
    client = _FakeGmailClient([_gmail_msg("m1"), _gmail_msg("m2")])
    poller = GmailPoller(
        ui,
        client,  # type: ignore[arg-type]
        interval_sec=60.0,
        merger=merger,
    )

    await poller.tick()

    merger.update.assert_called_once()
    args, _ = merger.update.call_args
    assert args[0] == "gmail"
    assert [n.id for n in args[1]] == ["m1", "m2"]


class _FakeGoogleChatClient:
    def __init__(self, spaces: list[Space], messages: list[ChatMessage]) -> None:
        self._spaces = spaces
        self._messages = messages

    async def list_spaces(self) -> list[Space]:
        return list(self._spaces)

    async def list_recent_messages(self, space_name: str, since: datetime) -> list[ChatMessage]:
        return list(self._messages)


def _chat_msg(name: str, text: str = "hello") -> ChatMessage:
    return ChatMessage(
        name=name,
        space_name="spaces/dm1",
        sender_display_name="Bob",
        text=text,
        create_time=datetime.now(UTC) - timedelta(minutes=2),
    )


async def test_register_url_and_lookup() -> None:
    """register_url stores a URL; lookup returns it; unknown id returns None."""
    bridge = MockBridge()
    ui = UIState(bridge)
    merger = Screen2Merger(ui)

    # Register URL without yet pushing notifications: the lookup index
    # is independent of the surviving-id prune until update() runs.
    merger.register_url("m1", "https://mail.google.com/mail/u/0/#inbox/m1")
    assert merger.lookup_url("m1") == "https://mail.google.com/mail/u/0/#inbox/m1"
    assert merger.lookup_url("unknown") is None


async def test_register_url_pruned_when_source_replaces() -> None:
    """A URL registered for an id is dropped when the source no longer emits that id."""
    bridge = MockBridge()
    ui = UIState(bridge)
    merger = Screen2Merger(ui)

    n_x = _n("x", source="gmail")
    merger.register_url("x", "https://example.com/x")
    merger.update("gmail", [n_x])
    await bridge.received()  # drain emission
    assert merger.lookup_url("x") == "https://example.com/x"

    # Re-push gmail with a different notification — "x" should be pruned.
    n_y = _n("y", source="gmail")
    merger.register_url("y", "https://example.com/y")
    merger.update("gmail", [n_y])
    await bridge.received()

    assert merger.lookup_url("x") is None
    assert merger.lookup_url("y") == "https://example.com/y"


async def test_gchat_poller_with_merger_routes_through_it() -> None:
    bridge = MockBridge()
    ui = UIState(bridge)
    merger = MagicMock(spec=Screen2Merger)
    spaces = [Space(name="spaces/dm1", display_name="(dm)", type="DIRECT_MESSAGE")]
    msgs = [_chat_msg("spaces/dm1/messages/1"), _chat_msg("spaces/dm1/messages/2")]
    client = _FakeGoogleChatClient(spaces, msgs)
    poller = GoogleChatPoller(
        ui,
        client,  # type: ignore[arg-type]
        my_email="jakub@example.com",
        interval_sec=60.0,
        merger=merger,
    )

    await poller.tick()

    merger.update.assert_called_once()
    args, _ = merger.update.call_args
    assert args[0] == "gchat"
    assert [n.id for n in args[1]] == [
        "spaces/dm1/messages/1",
        "spaces/dm1/messages/2",
    ]
