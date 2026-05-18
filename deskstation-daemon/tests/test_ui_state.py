"""Tests for UIState aggregator: dispatch, rate-limiting, coalescing, resend_all."""

import asyncio

from deskstation.bridge.mock_bridge import MockBridge
from deskstation.bridge.protocol import (
    JiraTask,
    MeetingBar,
    Notification,
    PomodoroFullscreenData,
    PomodoroFullscreenMsg,
    PullRequest,
    Screen1Msg,
    Screen2Msg,
    Screen3Msg,
    Screen4Msg,
    StandupItem,
    TodoItem,
    TopBarData,
    TopBarMsg,
)
from deskstation.ui_state import UIState

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_top_bar(clock: str = "12:00") -> TopBarData:
    return TopBarData(
        clock=clock,
        date="pon 18.05",
        weather="18°C",
        claude_usage="47%",
        pomodoro_counter=2,
    )


# ---------------------------------------------------------------------------
# Setter dispatch tests — one per setter
# ---------------------------------------------------------------------------


async def test_set_top_bar_dispatches() -> None:
    bridge = MockBridge()
    ui = UIState(bridge)
    data = _make_top_bar("09:00")
    ui.set_top_bar(data)
    msg = await asyncio.wait_for(bridge.received(), timeout=1.0)
    assert isinstance(msg, TopBarMsg)
    assert msg.data.clock == "09:00"


async def test_set_screen_1_dispatches() -> None:
    bridge = MockBridge()
    ui = UIState(bridge)
    tasks = [JiraTask(key="DEV-1", summary="Fix bug", status="In Progress")]
    ui.set_screen_1(today_tasks=tasks)
    msg = await asyncio.wait_for(bridge.received(), timeout=1.0)
    assert isinstance(msg, Screen1Msg)
    assert msg.data.today_tasks[0].key == "DEV-1"


async def test_set_screen_2_dispatches() -> None:
    bridge = MockBridge()
    ui = UIState(bridge)
    notifs = [
        Notification(
            source="gmail",
            sender="Boss",
            preview="Meeting?",
            time_ago="3m ago",
            id="n1",
        )
    ]
    ui.set_screen_2(notifications=notifs)
    msg = await asyncio.wait_for(bridge.received(), timeout=1.0)
    assert isinstance(msg, Screen2Msg)
    assert msg.data.notifications[0].id == "n1"


async def test_set_screen_3_dispatches() -> None:
    bridge = MockBridge()
    ui = UIState(bridge)
    prs = [
        PullRequest(
            id="pr-1",
            title="Add feature",
            author="alice",
            repo="backend",
            status="open",
            ci="passing",
        )
    ]
    ui.set_screen_3(prs=prs)
    msg = await asyncio.wait_for(bridge.received(), timeout=1.0)
    assert isinstance(msg, Screen3Msg)
    assert msg.data.prs[0].id == "pr-1"


async def test_set_screen_4_dispatches() -> None:
    bridge = MockBridge()
    ui = UIState(bridge)
    items = [TodoItem(id="t1", text="Write tests", done=False)]
    ui.set_screen_4(items=items)
    msg = await asyncio.wait_for(bridge.received(), timeout=1.0)
    assert isinstance(msg, Screen4Msg)
    assert msg.data.items[0].id == "t1"


async def test_set_pomodoro_overlay_dispatches() -> None:
    bridge = MockBridge()
    ui = UIState(bridge)
    data = PomodoroFullscreenData(visible=True, task_key="DEV-99", elapsed_sec=300)
    ui.set_pomodoro_overlay(data)
    msg = await asyncio.wait_for(bridge.received(), timeout=1.0)
    assert isinstance(msg, PomodoroFullscreenMsg)
    assert msg.data.task_key == "DEV-99"
    assert msg.data.elapsed_sec == 300


# ---------------------------------------------------------------------------
# Rate-limit test: 10 rapid calls → at most 2 sends in 250 ms
# ---------------------------------------------------------------------------


async def test_rate_limit_top_bar() -> None:
    bridge = MockBridge()
    ui = UIState(bridge)

    # Fire 10 updates immediately — first one fires right away (no previous send),
    # subsequent ones should coalesce into a single deferred send.
    for i in range(10):
        ui.set_top_bar(_make_top_bar(f"{i:02d}:00"))

    # Allow the rate-limit window (0.2 s) plus a generous buffer.
    await asyncio.sleep(0.3)

    # At most 2 messages: one immediate + one delayed (coalesced)
    size = bridge._outbound.qsize()
    assert size <= 2, f"expected ≤2 messages, got {size}"
    assert size >= 1, "expected at least 1 message"


# ---------------------------------------------------------------------------
# Coalesce: the deferred send carries the LAST state
# ---------------------------------------------------------------------------


async def test_coalesce_last_value_wins() -> None:
    bridge = MockBridge()
    ui = UIState(bridge)

    # First call — fires immediately (no prior send, no rate limit debt)
    ui.set_top_bar(_make_top_bar("00:00"))
    # Drain the immediate send so the queue is empty
    first = await asyncio.wait_for(bridge.received(), timeout=1.0)
    assert isinstance(first, TopBarMsg)
    assert first.data.clock == "00:00"

    # Now, within the 0.2 s window, fire several updates.
    # Only the last one should land in the deferred send.
    for i in range(1, 9):
        ui.set_top_bar(_make_top_bar(f"{i:02d}:00"))
    ui.set_top_bar(_make_top_bar("FINAL"))

    # Wait for the deferred send to fire.
    await asyncio.sleep(0.3)

    # There should be exactly one more message and it must carry the last value.
    assert bridge._outbound.qsize() == 1
    second = await bridge.received()
    assert isinstance(second, TopBarMsg)
    assert second.data.clock == "FINAL"


# ---------------------------------------------------------------------------
# resend_all: 6 messages (top_bar + 4 screens + pomodoro_fullscreen)
# ---------------------------------------------------------------------------


async def test_resend_all_sends_six_messages() -> None:
    bridge = MockBridge()
    ui = UIState(bridge)

    # Optionally set some state to make sure the right data is pushed.
    ui.set_screen_4(items=[TodoItem(id="x1", text="Item", done=False)])
    # Drain that one dispatch so the queue starts clean for resend_all.
    await asyncio.wait_for(bridge.received(), timeout=1.0)

    await ui.resend_all()

    assert bridge._outbound.qsize() == 6


async def test_resend_all_message_types() -> None:
    bridge = MockBridge()
    ui = UIState(bridge)

    await ui.resend_all()

    msgs = [await bridge.received() for _ in range(6)]
    types = {type(m).__name__ for m in msgs}
    assert types == {
        "TopBarMsg",
        "Screen1Msg",
        "Screen2Msg",
        "Screen3Msg",
        "Screen4Msg",
        "PomodoroFullscreenMsg",
    }


# ---------------------------------------------------------------------------
# set_screen_1 keyword combinations
# ---------------------------------------------------------------------------


async def test_set_screen_1_meeting() -> None:
    bridge = MockBridge()
    ui = UIState(bridge)

    meeting = MeetingBar(title="Standup", time="09:00-09:15", in_minutes=5)
    ui.set_screen_1(next_meeting=meeting)
    msg = await asyncio.wait_for(bridge.received(), timeout=1.0)
    assert isinstance(msg, Screen1Msg)
    assert msg.data.next_meeting is not None
    assert msg.data.next_meeting.title == "Standup"


async def test_set_screen_3_standup() -> None:
    bridge = MockBridge()
    ui = UIState(bridge)

    standup = [StandupItem(text="Wrote tests", done=True)]
    ui.set_screen_3(standup=standup)
    msg = await asyncio.wait_for(bridge.received(), timeout=1.0)
    assert isinstance(msg, Screen3Msg)
    assert msg.data.standup[0].done is True
