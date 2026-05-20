"""Tests for the real ClockPoller (M6.1)."""

from datetime import datetime
from unittest.mock import patch

import pytest

from deskstation.pollers.clock import ClockPoller, format_clock_date


def test_format_clock_date_polish_abbrev():
    sample = datetime(2026, 5, 20, 10, 32)  # śr 20.05
    assert format_clock_date(sample) == ("10:32", "śr 20.05")


@pytest.mark.asyncio
async def test_clock_poller_pushes_one_tick(monkeypatch):
    pushed: list[tuple[str, str]] = []

    class FakeUI:
        def set_clock(self, clock, date):
            pushed.append((clock, date))

    poller = ClockPoller(FakeUI())  # type: ignore[arg-type]
    fixed = datetime(2026, 5, 20, 9, 5)
    with patch("deskstation.pollers.clock._now", return_value=fixed):
        poller.tick_sync()
    assert pushed == [("09:05", "śr 20.05")]
