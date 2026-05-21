"""Listen for org.freedesktop.Notifications.Notify on the session bus.

WhatsApp Web / Messenger / Slack / KDE notifications are emitted as
``Notify`` method calls on the well-known ``org.freedesktop.Notifications``
interface. To observe them (and not just notifications addressed to us),
we ask the session bus to make us a *monitor* via
``org.freedesktop.DBus.Monitoring.BecomeMonitor``.

Captured notifications are buffered in a small ring; the Screen2Merger
(M5.5) is responsible for reading ``snapshot()`` and producing the
``screen_2`` payload.
"""

from __future__ import annotations

import collections
import fnmatch
from typing import Literal

import structlog
from dbus_next import BusType, Message  # type: ignore[attr-defined]
from dbus_next.aio import MessageBus  # type: ignore[attr-defined]

from deskstation.bridge.protocol import Notification

log = structlog.get_logger(__name__)


# Minimal introspection XML for org.freedesktop.DBus that exposes the
# Monitoring interface. dbus-next's built-in introspection of the bus
# driver does include Monitoring on modern dbus-daemons, but providing
# this explicitly avoids relying on the running broker's exposure.
_DBUS_INTROSPECTION_XML = """<!DOCTYPE node PUBLIC
 "-//freedesktop//DTD D-BUS Object Introspection 1.0//EN"
 "http://www.freedesktop.org/standards/dbus/1.0/introspect.dtd">
<node>
  <interface name="org.freedesktop.DBus.Monitoring">
    <method name="BecomeMonitor">
      <arg type="as" name="rules" direction="in"/>
      <arg type="u" name="flags" direction="in"/>
    </method>
  </interface>
</node>
"""


class DbusNotificationListener:
    """Subscribe to ``Notify`` signals/calls and buffer matching ones.

    Uses dbus-next's monitoring API ("eavesdrop") so that we receive
    ``Notify`` messages emitted by other apps (Chromium PWAs, Slack, KDE,
    etc.), not just ones addressed to us.

    Monitoring requires the calling process to be authorized. On most
    Ubuntu systems with default session-bus policy, the user's own session
    bus allows monitoring by the same user without extra config. If the
    bus rejects monitoring, ``start()`` raises and the daemon's main loop
    logs a warning and continues (no dbus notifications, but the rest
    works).
    """

    def __init__(
        self,
        *,
        app_name_patterns: list[str] | None = None,
        buffer_size: int = 32,
    ) -> None:
        # ``app_name_patterns``: list of fnmatch glob patterns that an
        # emitted Notify's ``app_name`` must match to be captured.
        # ``None`` / empty = match all.
        # Example: ``["WhatsApp*", "Messenger*", "Chromium", "Slack"]``.
        self._patterns: list[str] = list(app_name_patterns or [])
        self._buffer: collections.deque[Notification] = collections.deque(maxlen=buffer_size)
        self._bus: MessageBus | None = None
        self._counter: int = 0

    async def start(self) -> None:
        """Connect to session bus, become a monitor, install handler.

        Raises whatever dbus_next raises if the bus rejects monitoring —
        the daemon's main loop is expected to catch and log a warning.
        """
        bus = await MessageBus(bus_type=BusType.SESSION).connect()
        try:
            from dbus_next.introspection import Node

            node = Node.parse(_DBUS_INTROSPECTION_XML)
            proxy = bus.get_proxy_object("org.freedesktop.DBus", "/org/freedesktop/DBus", node)
            monitoring = proxy.get_interface("org.freedesktop.DBus.Monitoring")
            await monitoring.call_become_monitor(  # type: ignore[attr-defined]
                ["interface='org.freedesktop.Notifications',member='Notify'"],
                0,
            )
        except Exception:
            # Make sure we don't leak a half-connected bus if monitoring
            # is denied or the introspection import fails.
            bus.disconnect()  # type: ignore[no-untyped-call]
            raise

        bus.add_message_handler(self._on_message)
        self._bus = bus

    async def stop(self) -> None:
        """Disconnect from bus."""
        if self._bus is not None:
            self._bus.disconnect()  # type: ignore[no-untyped-call]
            self._bus = None

    def _on_message(self, msg: Message) -> bool:
        """Handler installed on the bus.

        Returns ``True`` if the message is one we care about (Notify),
        ``False`` otherwise so other handlers can still see it.
        """
        if msg.interface != "org.freedesktop.Notifications" or msg.member != "Notify":
            return False

        body = msg.body or []
        # Notify signature: (susssasa{sv}i) — but a monitor may also see
        # malformed messages; be defensive.
        if len(body) < 5:
            return True

        app_name = body[0] if isinstance(body[0], str) else ""
        summary = body[3] if isinstance(body[3], str) else ""
        preview = body[4] if isinstance(body[4], str) else ""

        if not self.matches_pattern(app_name):
            return True

        self._counter += 1
        notification = Notification(
            source=self._classify_source(app_name),
            sender=summary or app_name,
            preview=preview,
            time_ago="just now",
            id=f"dbus-{self._counter}",
        )
        self._buffer.append(notification)
        log.debug(
            "dbus_notification_captured",
            app_name=app_name,
            summary=summary,
            source=notification.source,
        )
        return True

    def snapshot(self) -> list[Notification]:
        """Return buffered notifications, newest first."""
        return list(reversed(list(self._buffer)))

    def matches_pattern(self, app_name: str) -> bool:
        """Public for testability."""
        if not self._patterns:
            return True
        lower = app_name.lower()
        return any(fnmatch.fnmatch(lower, p.lower()) for p in self._patterns)

    def _classify_source(self, app_name: str) -> Literal["whatsapp", "messenger", "chat", "system"]:
        """Public for testability."""
        lower = app_name.lower()
        if "whatsapp" in lower:
            return "whatsapp"
        if "messenger" in lower or "facebook" in lower:
            return "messenger"
        # Google Chat PWA / hangouts. Catches "Google Chat", "chat.google.com",
        # and the legacy "hangouts*" naming.
        if "chat.google.com" in lower or "google chat" in lower or "hangouts" in lower:
            return "chat"
        return "system"
