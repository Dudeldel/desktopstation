"""Real Gmail poller: drives screen_2 notifications from unread inbox.

Inherits from `MockPoller` purely for the `run_forever()` + tick-error
wrapper. Per tick it asks the `GmailClient` for unread messages from the
last day, maps them into the protocol's `Notification` model, exposes the
result via `latest_notifications()` for the M5.5 Screen2Merger, and (for
now in standalone M5.2) pushes them directly to screen_2.

Error policy mirrors `JiraPoller` / `BitbucketPoller`:
- `GmailAuthError`: log once, set `auth_failed`, re-raise so the
  `MockPoller.run_forever()` wrapper logs the failure. Subsequent ticks
  short-circuit so we don't spam the log every interval.
- `GmailTransientError`: log a warning and return — UIState keeps the
  last good values.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog

from deskstation.bridge.protocol import Notification
from deskstation.clients.gmail import (
    GmailAuthError,
    GmailClient,
    GmailTransientError,
)
from deskstation.pollers.mock import MockPoller

if TYPE_CHECKING:
    from deskstation.engines.screen2_merger import Screen2Merger
    from deskstation.ui_state import UIState

log = structlog.get_logger(__name__)


def _format_time_ago(received_at: datetime) -> str:
    """Produce Polish 'X temu' strings: minutes / hours / days."""
    now = datetime.now(UTC)
    if received_at.tzinfo is None:
        received_at = received_at.replace(tzinfo=UTC)
    delta = now - received_at
    total_seconds = max(int(delta.total_seconds()), 0)
    if total_seconds < 3600:
        minutes = max(total_seconds // 60, 0)
        return f"{minutes}m temu"
    if total_seconds < 86400:
        return f"{total_seconds // 3600}h temu"
    return f"{total_seconds // 86400}d temu"


class GmailPoller(MockPoller):
    def __init__(
        self,
        ui_state: UIState,
        client: GmailClient,
        interval_sec: float = 60.0,
        merger: Screen2Merger | None = None,
    ) -> None:
        super().__init__(ui_state, interval_sec)
        self._client = client
        self._merger = merger
        self._auth_failed = False
        self._latest: list[Notification] = []

    @property
    def auth_failed(self) -> bool:
        return self._auth_failed

    async def tick(self) -> None:
        if self._auth_failed:
            return

        try:
            messages = await self._client.list_unread_recent()
        except GmailAuthError as exc:
            log.error("gmail_poller_auth_failed", error=str(exc))
            self._auth_failed = True
            raise
        except GmailTransientError as exc:
            log.warning("gmail_poller_transient_error", error=str(exc))
            return

        self._latest = [
            Notification(
                source="gmail",
                sender=m.sender,
                preview=m.subject,
                time_ago=_format_time_ago(m.received_at),
                id=m.id,
            )
            for m in messages
        ]
        # M5.5: when a Screen2Merger is wired in (production main.py),
        # route through it so gmail+chat+dbus get merged rather than
        # clobbering one another. When no merger is supplied (standalone
        # tests, manual experiments), keep the direct push so the poller
        # is still usable on its own.
        if self._merger is not None:
            # M5.7: register a deep-link to the Gmail web UI for each
            # message so a notification_action event from the firmware
            # can xdg-open the right URL. Register BEFORE update() so the
            # post-update prune doesn't drop entries we just added.
            for m in messages:
                self._merger.register_url(m.id, f"https://mail.google.com/mail/u/0/#inbox/{m.id}")
            self._merger.update("gmail", list(self._latest))
        else:
            self.ui_state.set_screen_2(notifications=list(self._latest))

    def latest_notifications(self) -> list[Notification]:
        return list(self._latest)
