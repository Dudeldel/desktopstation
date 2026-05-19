"""Merge notifications from multiple sources into a single screen_2 view.

The Gmail poller (M5.2), Google Chat poller (M5.3), and dbus listener
(M5.4) each produce a list of :class:`Notification` independently. Before
M5.5 each source called :meth:`UIState.set_screen_2` directly, which
caused last-writer-wins clobbering. This engine becomes the single owner
of the ``screen_2`` dispatch:

* Each source pushes its current list via :meth:`Screen2Merger.update`.
* The merger combines the per-source lists, dedupes by
  ``(source_key, id)`` (so two sources can emit the same id without
  shadowing each other), sorts by ``(source_priority, in_source_index)``,
  caps the result at :attr:`MAX_ITEMS`, and calls
  :meth:`UIState.set_screen_2` exactly once.

Source priority is defined by :attr:`Screen2Merger._priority` and ranks
dbus (real-time desktop notifications) above polled sources (Gmail,
Chat). Unknown source keys fall to the bottom of the ranking.

The :class:`Notification` model has no timestamp; the in-source-index of
each notification is used as a recency proxy (each poller emits newest
first today, so index 0 is the most recent within its source).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from deskstation.bridge.protocol import Notification

if TYPE_CHECKING:
    from deskstation.ui_state import UIState


class Screen2Merger:
    """Aggregates notifications from multiple sources into a single screen_2 view."""

    MAX_ITEMS = 16

    # Higher priority sources rank first (lower rank number = higher priority).
    # dbus desktop notifications are real-time and the highest signal; the
    # polled Gmail / Chat sources fall behind. Sources not in this list
    # receive a rank one greater than any listed source, so they end up at
    # the bottom but are still emitted.
    _priority: tuple[str, ...] = ("dbus", "gmail", "gchat")

    def __init__(self, ui_state: UIState) -> None:
        self._ui = ui_state
        self._by_source: dict[str, list[Notification]] = {}

    def update(self, source_key: str, notifications: list[Notification]) -> None:
        """Replace this source's notifications and re-emit screen_2."""
        self._by_source[source_key] = list(notifications)
        self._emit()

    def refresh(self) -> None:
        """Re-merge and re-emit without changing any source's contents."""
        self._emit()

    def _priority_rank(self, source_key: str) -> int:
        try:
            return self._priority.index(source_key)
        except ValueError:
            return len(self._priority)

    def _emit(self) -> None:
        merged = self._merge()
        self._ui.set_screen_2(notifications=merged)

    def _merge(self) -> list[Notification]:
        # Dedup is scoped per source: the key is ``(source_key, id)`` so two
        # different sources emitting the same id string (e.g. "1") don't
        # shadow each other. Within a single source, last write wins on an
        # id collision — which shouldn't happen anyway given each source
        # emits its own id space.
        dedup: dict[tuple[str, str], tuple[int, int, Notification]] = {}
        for source_key, lst in self._by_source.items():
            rank = self._priority_rank(source_key)
            for idx, notification in enumerate(lst):
                dedup[(source_key, notification.id)] = (rank, idx, notification)

        # Sort by (priority_rank, in_source_index) for a deterministic order.
        sorted_entries = sorted(dedup.values(), key=lambda e: (e[0], e[1]))

        return [e[2] for e in sorted_entries[: self.MAX_ITEMS]]
