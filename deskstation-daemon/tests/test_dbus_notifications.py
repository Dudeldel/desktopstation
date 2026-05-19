"""Unit tests for DbusNotificationListener.

We do NOT spin up a real bus here. ``start()`` and ``stop()`` are
integration-only (covered by the M5.8 smoke test). Tests exercise the
pure-Python surface: pattern matching, source classification, the
ring-buffer behaviour, and ``_on_message`` filtering via fake messages.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from dbus_next import Message  # type: ignore[attr-defined]

from deskstation.bridge.protocol import Notification
from deskstation.listeners.dbus_notifications import DbusNotificationListener

# ---- matches_pattern ----


def test_matches_pattern_with_no_patterns() -> None:
    listener = DbusNotificationListener(app_name_patterns=None)
    assert listener.matches_pattern("anything") is True
    assert listener.matches_pattern("") is True


def test_matches_pattern_glob() -> None:
    listener = DbusNotificationListener(app_name_patterns=["WhatsApp*"])
    assert listener.matches_pattern("WhatsApp Web") is True
    assert listener.matches_pattern("Slack") is False


def test_matches_pattern_case_insensitive() -> None:
    listener = DbusNotificationListener(app_name_patterns=["whatsapp*"])
    assert listener.matches_pattern("WhatsApp Web") is True


# ---- _classify_source ----


def test_classify_source_whatsapp() -> None:
    listener = DbusNotificationListener()
    assert listener._classify_source("WhatsApp Web") == "whatsapp"
    assert listener._classify_source("whatsapp") == "whatsapp"


def test_classify_source_messenger() -> None:
    listener = DbusNotificationListener()
    assert listener._classify_source("Messenger") == "messenger"
    assert listener._classify_source("Facebook") == "messenger"


def test_classify_source_unknown() -> None:
    listener = DbusNotificationListener()
    assert listener._classify_source("Slack") == "system"
    assert listener._classify_source("KDE Connect") == "system"


# ---- buffer behaviour ----


def _push_n(listener: DbusNotificationListener, n: int) -> None:
    for i in range(n):
        listener._buffer.append(
            Notification(
                source="system",
                sender=f"s{i}",
                preview=f"p{i}",
                time_ago="just now",
                id=f"id-{i}",
            )
        )


def test_buffer_size_limits_capacity() -> None:
    listener = DbusNotificationListener(buffer_size=32)
    _push_n(listener, 40)
    snap = listener.snapshot()
    assert len(snap) == 32


def test_snapshot_newest_first() -> None:
    listener = DbusNotificationListener(buffer_size=8)
    _push_n(listener, 3)  # ids id-0, id-1, id-2 in append order
    snap = listener.snapshot()
    assert [n.id for n in snap] == ["id-2", "id-1", "id-0"]


# ---- _on_message ----


def _fake_message(
    *,
    interface: str,
    member: str,
    body: list[object],
) -> Message:
    msg = MagicMock(spec=Message)
    msg.interface = interface
    msg.member = member
    msg.body = body
    return msg


def test_on_message_filters_by_app_name() -> None:
    listener = DbusNotificationListener(app_name_patterns=["WhatsApp*"])
    # Notify signature body: app_name, replaces_id, app_icon, summary,
    # body, actions, hints, expire_timeout
    matching = _fake_message(
        interface="org.freedesktop.Notifications",
        member="Notify",
        body=[
            "WhatsApp Web",
            0,
            "",
            "Alice",
            "hi there",
            [],
            {},
            -1,
        ],
    )
    not_matching = _fake_message(
        interface="org.freedesktop.Notifications",
        member="Notify",
        body=[
            "Spotify",
            0,
            "",
            "Now Playing",
            "Some Song",
            [],
            {},
            -1,
        ],
    )

    assert listener._on_message(matching) is True
    assert listener._on_message(not_matching) is True

    snap = listener.snapshot()
    assert len(snap) == 1
    assert snap[0].source == "whatsapp"
    assert snap[0].sender == "Alice"
    assert snap[0].preview == "hi there"
    assert snap[0].time_ago == "just now"
    assert snap[0].id.startswith("dbus-")


def test_on_message_ignores_non_notify() -> None:
    listener = DbusNotificationListener()
    msg = _fake_message(
        interface="org.freedesktop.Notifications",
        member="GetServerInformation",
        body=[],
    )
    assert listener._on_message(msg) is False
    assert listener.snapshot() == []


def test_on_message_ignores_other_interface() -> None:
    listener = DbusNotificationListener()
    msg = _fake_message(
        interface="org.freedesktop.DBus",
        member="Notify",
        body=["WhatsApp", 0, "", "x", "y", [], {}, -1],
    )
    assert listener._on_message(msg) is False
    assert listener.snapshot() == []


def test_on_message_no_patterns_captures_everything() -> None:
    listener = DbusNotificationListener(app_name_patterns=None)
    msg = _fake_message(
        interface="org.freedesktop.Notifications",
        member="Notify",
        body=["Whatever", 0, "", "summary", "body", [], {}, -1],
    )
    assert listener._on_message(msg) is True
    snap = listener.snapshot()
    assert len(snap) == 1
    assert snap[0].source == "system"
    assert snap[0].sender == "summary"
