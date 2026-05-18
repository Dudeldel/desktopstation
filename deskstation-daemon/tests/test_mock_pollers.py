"""Tests for mock data pollers (M2 dev mode).

Strategy: instantiate each poller with a real UIState(MockBridge()), call tick() once,
await asyncio.sleep(0.05) to let the UIState's create_task flush, then assert the
correct envelope type arrived on the bridge.
"""

import asyncio

import pytest

from deskstation.bridge.mock_bridge import MockBridge
from deskstation.bridge.protocol import (
    Screen1Msg,
    Screen2Msg,
    Screen3Msg,
    Screen4Msg,
    TopBarMsg,
)
from deskstation.pollers.mock import (
    Screen1Poller,
    Screen2Poller,
    Screen3Poller,
    Screen4Poller,
    TopBarPoller,
    start_all_mocks,
)
from deskstation.ui_state import UIState

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ui() -> tuple[UIState, MockBridge]:
    bridge = MockBridge()
    ui = UIState(bridge)
    return ui, bridge


async def _drain_one(bridge: MockBridge) -> object:
    return await asyncio.wait_for(bridge.received(), timeout=1.0)


# ---------------------------------------------------------------------------
# TopBarPoller
# ---------------------------------------------------------------------------


async def test_top_bar_poller_sends_top_bar_msg() -> None:
    ui, bridge = _make_ui()
    poller = TopBarPoller(ui, interval_sec=60.0)
    await poller.tick()
    await asyncio.sleep(0.05)
    msg = await _drain_one(bridge)
    assert isinstance(msg, TopBarMsg)


async def test_top_bar_poller_clock_format() -> None:
    ui, bridge = _make_ui()
    poller = TopBarPoller(ui, interval_sec=60.0)
    await poller.tick()
    await asyncio.sleep(0.05)
    msg = await _drain_one(bridge)
    assert isinstance(msg, TopBarMsg)
    # HH:MM format
    parts = msg.data.clock.split(":")
    assert len(parts) == 2
    assert parts[0].isdigit() and parts[1].isdigit()


async def test_top_bar_poller_date_has_pl_day() -> None:
    ui, bridge = _make_ui()
    poller = TopBarPoller(ui, interval_sec=60.0)
    await poller.tick()
    await asyncio.sleep(0.05)
    msg = await _drain_one(bridge)
    assert isinstance(msg, TopBarMsg)
    # Date must have two parts: day-name and dd.mm
    parts = msg.data.date.split()
    assert len(parts) == 2
    assert "." in parts[1]


async def test_top_bar_poller_claude_usage_percent() -> None:
    ui, bridge = _make_ui()
    poller = TopBarPoller(ui, interval_sec=60.0)
    await poller.tick()
    await asyncio.sleep(0.05)
    msg = await _drain_one(bridge)
    assert isinstance(msg, TopBarMsg)
    assert msg.data.claude_usage.endswith("%")


async def test_top_bar_poller_pomodoro_counter_non_negative() -> None:
    ui, bridge = _make_ui()
    poller = TopBarPoller(ui, interval_sec=60.0)
    await poller.tick()
    await asyncio.sleep(0.05)
    msg = await _drain_one(bridge)
    assert isinstance(msg, TopBarMsg)
    assert msg.data.pomodoro_counter >= 0


# ---------------------------------------------------------------------------
# Screen1Poller
# ---------------------------------------------------------------------------


async def test_screen1_poller_sends_screen1_msg() -> None:
    ui, bridge = _make_ui()
    poller = Screen1Poller(ui, interval_sec=60.0)
    await poller.tick()
    await asyncio.sleep(0.05)
    msg = await _drain_one(bridge)
    assert isinstance(msg, Screen1Msg)


async def test_screen1_poller_today_tasks_count() -> None:
    ui, bridge = _make_ui()
    poller = Screen1Poller(ui, interval_sec=60.0)
    await poller.tick()
    await asyncio.sleep(0.05)
    msg = await _drain_one(bridge)
    assert isinstance(msg, Screen1Msg)
    assert 3 <= len(msg.data.today_tasks) <= 5


async def test_screen1_poller_queued_tasks_count() -> None:
    ui, bridge = _make_ui()
    poller = Screen1Poller(ui, interval_sec=60.0)
    await poller.tick()
    await asyncio.sleep(0.05)
    msg = await _drain_one(bridge)
    assert isinstance(msg, Screen1Msg)
    assert 2 <= len(msg.data.queued_tasks) <= 4


async def test_screen1_poller_first_tick_has_meeting() -> None:
    """tick_count=0 → next_meeting should be the fake meeting (0 % 3 == 0)."""
    ui, bridge = _make_ui()
    poller = Screen1Poller(ui, interval_sec=60.0)
    await poller.tick()
    await asyncio.sleep(0.05)
    msg = await _drain_one(bridge)
    assert isinstance(msg, Screen1Msg)
    assert msg.data.next_meeting is not None


async def test_screen1_poller_second_tick_no_meeting() -> None:
    """tick_count=1 → no meeting (1 % 3 != 0)."""
    ui, bridge = _make_ui()
    poller = Screen1Poller(ui, interval_sec=60.0)
    # First tick
    await poller.tick()
    await asyncio.sleep(0.05)
    await _drain_one(bridge)
    # Second tick
    await poller.tick()
    await asyncio.sleep(0.05)
    msg = await _drain_one(bridge)
    assert isinstance(msg, Screen1Msg)
    assert msg.data.next_meeting is None


async def test_screen1_tasks_have_required_fields() -> None:
    ui, bridge = _make_ui()
    poller = Screen1Poller(ui, interval_sec=60.0)
    await poller.tick()
    await asyncio.sleep(0.05)
    msg = await _drain_one(bridge)
    assert isinstance(msg, Screen1Msg)
    for task in msg.data.today_tasks:
        assert task.key.startswith("DEV-")
        assert len(task.summary) > 0
        assert len(task.status) > 0


# ---------------------------------------------------------------------------
# Screen2Poller
# ---------------------------------------------------------------------------


async def test_screen2_poller_sends_screen2_msg() -> None:
    ui, bridge = _make_ui()
    poller = Screen2Poller(ui, interval_sec=60.0)
    await poller.tick()
    await asyncio.sleep(0.05)
    msg = await _drain_one(bridge)
    assert isinstance(msg, Screen2Msg)


async def test_screen2_poller_has_notification() -> None:
    ui, bridge = _make_ui()
    poller = Screen2Poller(ui, interval_sec=60.0)
    await poller.tick()
    await asyncio.sleep(0.05)
    msg = await _drain_one(bridge)
    assert isinstance(msg, Screen2Msg)
    assert len(msg.data.notifications) == 1


async def test_screen2_poller_accumulates_up_to_8() -> None:
    ui, bridge = _make_ui()
    poller = Screen2Poller(ui, interval_sec=60.0)
    for _ in range(10):
        await poller.tick()
        await asyncio.sleep(0.05)
        await _drain_one(bridge)

    # After 10 ticks, deque maxlen=8 means at most 8 notifications
    await poller.tick()
    await asyncio.sleep(0.05)
    msg = await _drain_one(bridge)
    assert isinstance(msg, Screen2Msg)
    assert len(msg.data.notifications) <= 8


async def test_screen2_poller_notification_source_valid() -> None:
    ui, bridge = _make_ui()
    poller = Screen2Poller(ui, interval_sec=60.0)
    await poller.tick()
    await asyncio.sleep(0.05)
    msg = await _drain_one(bridge)
    assert isinstance(msg, Screen2Msg)
    valid_sources = {"gmail", "chat", "messenger", "whatsapp", "system"}
    for notif in msg.data.notifications:
        assert notif.source in valid_sources


# ---------------------------------------------------------------------------
# Screen3Poller
# ---------------------------------------------------------------------------


async def test_screen3_poller_sends_screen3_msg() -> None:
    ui, bridge = _make_ui()
    poller = Screen3Poller(ui, interval_sec=60.0)
    await poller.tick()
    await asyncio.sleep(0.05)
    msg = await _drain_one(bridge)
    assert isinstance(msg, Screen3Msg)


async def test_screen3_poller_prs_count() -> None:
    ui, bridge = _make_ui()
    poller = Screen3Poller(ui, interval_sec=60.0)
    await poller.tick()
    await asyncio.sleep(0.05)
    msg = await _drain_one(bridge)
    assert isinstance(msg, Screen3Msg)
    assert 2 <= len(msg.data.prs) <= 4


async def test_screen3_poller_standup_count() -> None:
    ui, bridge = _make_ui()
    poller = Screen3Poller(ui, interval_sec=60.0)
    await poller.tick()
    await asyncio.sleep(0.05)
    msg = await _drain_one(bridge)
    assert isinstance(msg, Screen3Msg)
    assert len(msg.data.standup) == 3


async def test_screen3_poller_standup_has_done_flag() -> None:
    ui, bridge = _make_ui()
    poller = Screen3Poller(ui, interval_sec=60.0)
    await poller.tick()
    await asyncio.sleep(0.05)
    msg = await _drain_one(bridge)
    assert isinstance(msg, Screen3Msg)
    # At least one done, at least one not done in the fixed items
    done_flags = [item.done for item in msg.data.standup]
    assert True in done_flags
    assert False in done_flags


async def test_screen3_poller_pr_status_valid() -> None:
    ui, bridge = _make_ui()
    poller = Screen3Poller(ui, interval_sec=60.0)
    await poller.tick()
    await asyncio.sleep(0.05)
    msg = await _drain_one(bridge)
    assert isinstance(msg, Screen3Msg)
    valid_statuses = {"open", "approved", "needs_review", "changes_requested"}
    valid_ci = {"passing", "failing", "running", "unknown"}
    for pr in msg.data.prs:
        assert pr.status in valid_statuses
        assert pr.ci in valid_ci


# ---------------------------------------------------------------------------
# Screen4Poller
# ---------------------------------------------------------------------------


async def test_screen4_poller_sends_screen4_msg() -> None:
    ui, bridge = _make_ui()
    poller = Screen4Poller(ui, interval_sec=60.0)
    await poller.tick()
    await asyncio.sleep(0.05)
    msg = await _drain_one(bridge)
    assert isinstance(msg, Screen4Msg)


async def test_screen4_poller_item_count() -> None:
    ui, bridge = _make_ui()
    poller = Screen4Poller(ui, interval_sec=60.0)
    await poller.tick()
    await asyncio.sleep(0.05)
    msg = await _drain_one(bridge)
    assert isinstance(msg, Screen4Msg)
    assert len(msg.data.items) == 5


async def test_screen4_poller_toggles_item() -> None:
    """Two ticks should toggle two different items."""
    ui, bridge = _make_ui()
    poller = Screen4Poller(ui, interval_sec=60.0)

    await poller.tick()
    await asyncio.sleep(0.05)
    msg1 = await _drain_one(bridge)
    assert isinstance(msg1, Screen4Msg)
    done_after_tick1 = [item.done for item in msg1.data.items]

    await poller.tick()
    await asyncio.sleep(0.05)
    msg2 = await _drain_one(bridge)
    assert isinstance(msg2, Screen4Msg)
    done_after_tick2 = [item.done for item in msg2.data.items]

    # At least one flag should differ between ticks
    assert done_after_tick1 != done_after_tick2


async def test_screen4_poller_item_ids_stable() -> None:
    """Item IDs must remain stable across ticks (only done flags change)."""
    ui, bridge = _make_ui()
    poller = Screen4Poller(ui, interval_sec=60.0)

    await poller.tick()
    await asyncio.sleep(0.05)
    msg1 = await _drain_one(bridge)
    assert isinstance(msg1, Screen4Msg)
    ids1 = [item.id for item in msg1.data.items]

    await poller.tick()
    await asyncio.sleep(0.05)
    msg2 = await _drain_one(bridge)
    assert isinstance(msg2, Screen4Msg)
    ids2 = [item.id for item in msg2.data.items]

    assert ids1 == ids2


# ---------------------------------------------------------------------------
# start_all_mocks factory
# ---------------------------------------------------------------------------


async def test_start_all_mocks_returns_five_tasks() -> None:
    ui, _bridge = _make_ui()
    tasks = start_all_mocks(ui, interval_sec=3600.0)
    assert len(tasks) == 5
    for t in tasks:
        assert isinstance(t, asyncio.Task)
    # Cleanup
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


async def test_start_all_mocks_tasks_not_done_immediately() -> None:
    ui, _bridge = _make_ui()
    tasks = start_all_mocks(ui, interval_sec=3600.0)
    # Give the event loop a moment to start the tasks
    await asyncio.sleep(0.01)
    for t in tasks:
        assert not t.done(), f"Task {t} should still be running"
    # Cleanup
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.parametrize("n_ticks", [1, 3])
async def test_start_all_mocks_produces_messages(n_ticks: int) -> None:
    """After start_all_mocks + sleep, at least 5 messages land on the bridge."""
    ui, bridge = _make_ui()
    tasks = start_all_mocks(ui, interval_sec=0.05)
    # Sleep long enough for each poller to tick at least n_ticks times
    await asyncio.sleep(0.05 * n_ticks + 0.2)
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)

    # At least one message from each of the 5 pollers should be present
    assert bridge._outbound.qsize() >= 5
