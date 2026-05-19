"""Shared time-formatting helpers for pollers.

Kept here so gmail/gchat/calendar pollers don't cross-import from each other
just for cosmetic formatting.
"""

from __future__ import annotations

from datetime import UTC, datetime


def format_time_ago(received_at: datetime) -> str:
    """Produce strings like "5m temu", "2h temu", "1d temu".

    Uses datetime.now(UTC) for the reference. Future-dated inputs (clock skew)
    clamp to 0 → "0m temu".
    """
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
