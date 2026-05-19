"""Merge notifications from multiple sources into a single screen_2 view.

The Gmail poller (M5.2), Google Chat poller (M5.3), and dbus listener
(M5.4) each produce a list of :class:`Notification` independently. Before
M5.5 each source called :meth:`UIState.set_screen_2` directly, which
caused last-writer-wins clobbering. This engine becomes the single owner
of the ``screen_2`` dispatch:

* Each source pushes its current list via :meth:`Screen2Merger.update`.
* The merger combines the per-source lists, dedupes by ``id`` keeping the
  entry from the highest-priority source, sorts by
  ``(source_priority, in_source_index)``, caps the result at
  :attr:`MAX_ITEMS`, and calls :meth:`UIState.set_screen_2` exactly once.

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
        # Build a list of (priority_rank, in_source_index, source_key, Notification)
        # for every notification across all sources.
        entries: list[tuple[int, int, str, Notification]] = []
        for source_key, lst in self._by_source.items():
            rank = self._priority_rank(source_key)
            for idx, notification in enumerate(lst):
                entries.append((rank, idx, source_key, notification))

        # Dedup by id, keeping the entry with the LOWEST priority rank
        # (i.e. highest-priority source). On ties, keep the earlier
        # in-source-index (more recent within that source).
        best: dict[str, tuple[int, int, str, Notification]] = {}
        for entry in entries:
            rank, idx, _src, notification = entry
            prev = best.get(notification.id)
            if prev is None:
                best[notification.id] = entry
                continue
            prev_rank, prev_idx, _, _ = prev
            if (rank, idx) < (prev_rank, prev_idx):
                best[notification.id] = entry

        # Sort by (priority_rank, in_source_index) for a deterministic order.
        sorted_entries = sorted(best.values(), key=lambda e: (e[0], e[1]))

        return [e[3] for e in sorted_entries[: self.MAX_ITEMS]]
