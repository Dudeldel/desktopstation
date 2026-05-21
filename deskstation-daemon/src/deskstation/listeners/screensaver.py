"""Listens to org.freedesktop.ScreenSaver.ActiveChanged on the session bus.

Active=True → host is locked; Active=False → host is unlocked. The session
bus may also expose org.gnome.ScreenSaver or org.kde.ScreenSaver with the same
interface; we match on the well-known org.freedesktop.ScreenSaver path which
all major DEs expose.

The listener is signal-driven: it adds a dbus match rule and installs a
message handler on the bus. Each ``ActiveChanged(b)`` signal received is
turned into a coroutine call on the daemon's main event loop (the bus
handler may run on a different thread / context depending on dbus_next's
internals, so we hop loops via ``asyncio.run_coroutine_threadsafe``).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import structlog
from dbus_next import BusType, Message, MessageType  # type: ignore[attr-defined]
from dbus_next.aio import MessageBus  # type: ignore[attr-defined]

log = structlog.get_logger(__name__)

OnLockChange = Callable[[bool], Awaitable[None] | None]


def classify_signal(msg: Message) -> bool | None:
    """Return the lock-state bool if ``msg`` is an ActiveChanged signal, else None.

    Pulled out as a free function so tests can exercise the dispatch logic
    without spinning up a real dbus connection.
    """
    if msg.message_type != MessageType.SIGNAL:
        return None
    if msg.interface != "org.freedesktop.ScreenSaver":
        return None
    if msg.member != "ActiveChanged":
        return None
    body = msg.body or []
    if not body or not isinstance(body[0], bool):
        return None
    return body[0]


class ScreensaverListener:
    """Subscribes to the freedesktop ScreenSaver ActiveChanged signal."""

    def __init__(self, on_change: OnLockChange) -> None:
        self._on_change = on_change
        self._bus: MessageBus | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    async def start(self) -> None:
        bus = await MessageBus(bus_type=BusType.SESSION).connect()
        # Add a match rule for the ActiveChanged signal. We do not narrow
        # by sender — KDE / GNOME / cinnamon all emit on different bus
        # names but on the same interface.
        await bus.call(
            Message(
                destination="org.freedesktop.DBus",
                path="/org/freedesktop/DBus",
                interface="org.freedesktop.DBus",
                member="AddMatch",
                signature="s",
                body=[
                    "type='signal',interface='org.freedesktop.ScreenSaver',member='ActiveChanged'"
                ],
            )
        )
        bus.add_message_handler(self._on_message)
        self._bus = bus
        self._loop = asyncio.get_running_loop()
        log.info("screensaver_listener_active")

    async def stop(self) -> None:
        if self._bus is not None:
            self._bus.disconnect()  # type: ignore[no-untyped-call]
            self._bus = None

    def _on_message(self, msg: Message) -> bool:
        # Returning True swallows the message; we should NOT swallow other
        # handlers' messages — let the dispatcher see it again. Return False.
        locked = classify_signal(msg)
        if locked is None:
            return False
        loop = self._loop
        if loop is None:
            return False

        async def _dispatch() -> None:
            try:
                result = self._on_change(locked)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:
                log.warning(
                    "screensaver_dispatch_failed",
                    error=str(exc),
                    error_type=type(exc).__name__,
                )

        asyncio.run_coroutine_threadsafe(_dispatch(), loop)
        return False
