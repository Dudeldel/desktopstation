"""Unit tests for ScreensaverListener.

A real session bus is integration-only. These tests exercise the pure
``classify_signal`` helper and the listener's constructor; ``start()`` and
``stop()`` are only smoke-checked indirectly through main.py wiring.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from dbus_next import MessageType  # type: ignore[attr-defined]

from deskstation.listeners.screensaver import (
    ACCEPTED_INTERFACES,
    ScreensaverListener,
    classify_signal,
)


def _fake_msg(
    *,
    message_type: Any = MessageType.SIGNAL,
    interface: str | None = "org.freedesktop.ScreenSaver",
    member: str | None = "ActiveChanged",
    body: list[Any] | None = None,
) -> MagicMock:
    msg = MagicMock()
    msg.message_type = message_type
    msg.interface = interface
    msg.member = member
    msg.body = body if body is not None else [True]
    return msg


def test_classify_signal_returns_true_for_locked() -> None:
    assert classify_signal(_fake_msg(body=[True])) is True


def test_classify_signal_returns_false_for_unlocked() -> None:
    assert classify_signal(_fake_msg(body=[False])) is False


def test_classify_signal_ignores_non_signal() -> None:
    assert classify_signal(_fake_msg(message_type=MessageType.METHOD_CALL)) is None


def test_classify_signal_ignores_wrong_interface() -> None:
    assert classify_signal(_fake_msg(interface="org.freedesktop.Notifications")) is None


@pytest.mark.parametrize("interface", ACCEPTED_INTERFACES)
def test_classify_signal_accepts_each_de_interface(interface: str) -> None:
    # Every accepted DE interface must classify true/false correctly. The
    # GNOME case in particular regressed against a real Ubuntu Wayland
    # session that emits on org.gnome.ScreenSaver, not the freedesktop name.
    assert classify_signal(_fake_msg(interface=interface, body=[True])) is True
    assert classify_signal(_fake_msg(interface=interface, body=[False])) is False


def test_classify_signal_ignores_wrong_member() -> None:
    assert classify_signal(_fake_msg(member="SomeOtherSignal")) is None


def test_classify_signal_handles_empty_body() -> None:
    assert classify_signal(_fake_msg(body=[])) is None


def test_classify_signal_handles_non_bool_body() -> None:
    assert classify_signal(_fake_msg(body=["not a bool"])) is None
    assert classify_signal(_fake_msg(body=[1])) is None


def test_constructor_stores_callback() -> None:
    cb_calls: list[bool] = []

    async def cb(locked: bool) -> None:
        cb_calls.append(locked)

    listener = ScreensaverListener(cb)
    assert listener._on_change is cb
    assert listener._bus is None
    assert listener._loop is None


def test_on_message_returns_false_when_not_started() -> None:
    """If the listener hasn't started (no loop captured), drop without crashing."""
    listener = ScreensaverListener(lambda _: None)
    # A valid ActiveChanged signal — but loop is None so dispatch should no-op.
    result = listener._on_message(_fake_msg(body=[True]))
    assert result is False


def test_on_message_returns_false_for_irrelevant_msg() -> None:
    listener = ScreensaverListener(lambda _: None)
    result = listener._on_message(_fake_msg(interface="org.freedesktop.Notifications"))
    assert result is False
