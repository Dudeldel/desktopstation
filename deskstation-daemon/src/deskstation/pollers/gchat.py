"""Real Google Chat poller: drives screen_2 notifications from Chat DMs + @-mentions.

Inherits from :class:`MockPoller` purely for the ``run_forever()`` +
tick-error wrapper. Per tick it asks the :class:`GoogleChatClient` for
the user's spaces and recent messages, filters to DMs + @-mentions of the
user, maps them into the protocol's :class:`Notification` model, exposes
the result via :meth:`latest_notifications` for the M5.5 Screen2Merger,
and (for now in standalone M5.3) pushes them directly to screen_2.

Error policy mirrors :class:`GmailPoller`:

* :class:`GoogleChatAuthError`: log once, set ``auth_failed``, re-raise
  so the ``MockPoller.run_forever()`` wrapper logs the failure. Subsequent
  ticks short-circuit so we don't spam the log every interval.
* :class:`GoogleChatTransientError` from ``list_spaces``: log a warning
  and return — UIState keeps the last good values.
* :class:`GoogleChatTransientError` from a single ``list_recent_messages``
  call: log a warning and skip just that space — we still emit
  notifications from the spaces that succeeded.

``_last_check`` is only advanced after a successful pass so a partial
failure doesn't lose messages on the next tick.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import structlog

from deskstation.bridge.protocol import Notification
from deskstation.clients.gchat import (
    GoogleChatAuthError,
    GoogleChatClient,
    GoogleChatTransientError,
)
from deskstation.pollers.gmail import _format_time_ago
from deskstation.pollers.mock import MockPoller

# TODO(M5.x cleanup): ``_format_time_ago`` is now used by both the Gmail
# and Chat pollers. Move to a shared ``deskstation.pollers._time`` helper
# module once dbus / calendar pollers land in M5.4 / M5.6.

if TYPE_CHECKING:
    from deskstation.ui_state import UIState

log = structlog.get_logger(__name__)


class GoogleChatPoller(MockPoller):
    def __init__(
        self,
        ui_state: UIState,
        client: GoogleChatClient,
        my_email: str,
        interval_sec: float = 60.0,
    ) -> None:
        super().__init__(ui_state, interval_sec)
        self._client = client
        self._my_email = my_email
        self._auth_failed = False
        self._latest: list[Notification] = []
        # Start the window one hour back so the very first tick has a
        # reasonable look-behind without dumping the full history.
        self._last_check: datetime = datetime.now(UTC) - timedelta(hours=1)

    @property
    def auth_failed(self) -> bool:
        return self._auth_failed

    async def tick(self) -> None:
        if self._auth_failed:
            return

        try:
            spaces = await self._client.list_spaces()
        except GoogleChatAuthError as exc:
            log.error("gchat_poller_auth_failed", error=str(exc))
            self._auth_failed = True
            raise
        except GoogleChatTransientError as exc:
            log.warning("gchat_poller_transient_error", error=str(exc))
            return

        my_local_part = self._my_email.split("@")[0]
        mention_token = f"@{my_local_part}"

        notifications: list[Notification] = []
        for space in spaces:
            try:
                messages = await self._client.list_recent_messages(
                    space.name, since=self._last_check
                )
            except GoogleChatAuthError:
                # Propagate — auth doesn't get better by trying another space.
                self._auth_failed = True
                raise
            except GoogleChatTransientError as exc:
                log.warning(
                    "gchat_poller_space_transient_error",
                    space=space.name,
                    error=str(exc),
                )
                continue

            for msg in messages:
                if space.type == "DIRECT_MESSAGE":
                    include = True
                else:
                    # TODO(M5.x): use Chat's ``annotations`` field for
                    # proper USER_MENTION detection instead of substring
                    # matching against the email local-part. For M5.3 this
                    # primitive heuristic is sufficient.
                    include = mention_token in (msg.text or "")
                if not include:
                    continue
                notifications.append(
                    Notification(
                        source="chat",
                        sender=msg.sender_display_name,
                        preview=msg.text[:100],
                        time_ago=_format_time_ago(msg.create_time),
                        id=msg.name,
                    )
                )

        self._latest = notifications
        # M5.5 (Screen2Merger) will replace this direct push with a merge
        # of gmail+chat+dbus sources via ``self.latest_notifications()``.
        # For M5.3 standalone the poller is one of (potentially) several
        # sources writing to screen_2 — see TODO in main.py.
        self.ui_state.set_screen_2(notifications=list(self._latest))

        # Only advance the window once a full pass has been collected.
        self._last_check = datetime.now(UTC)

    def latest_notifications(self) -> list[Notification]:
        return list(self._latest)
