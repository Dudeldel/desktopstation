"""Tests for UIState aggregator: dispatch, rate-limiting, coalescing, resend_all."""

import asyncio

from deskstation.bridge.mock_bridge import MockBridge
from deskstation.bridge.protocol import (
    FullscreenData,
    FullscreenMsg,
    JiraTask,
    LockStateMsg,
    MacroListItem,
    MacroListMsg,
    MeetingBar,
    Notification,
    PomodoroStateData,
    PomodoroStateMsg,
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


async def _drain_pending(ui: UIState) -> None:
    """Await every currently scheduled UIState send task."""
    pending = list(ui._pending.values())
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


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


async def test_set_pomodoro_state_dispatches() -> None:
    bridge = MockBridge()
    ui = UIState(bridge)
    data = PomodoroStateData(
        state="active",
        remaining_sec=1200,
        total_sec=1500,
        task_key="DEV-99",
        task_summary="Fix login",
        pomodoro_number_today=1,
    )
    ui.set_pomodoro_state(data)
    msg = await asyncio.wait_for(bridge.received(), timeout=1.0)
    assert isinstance(msg, PomodoroStateMsg)
    assert msg.data.task_key == "DEV-99"
    assert msg.data.remaining_sec == 1200


async def test_set_macro_list_dispatches() -> None:
    bridge = MockBridge()
    ui = UIState(bridge)
    ui.set_macro_list(
        [
            MacroListItem(id="MAKRO", label="Test"),
            MacroListItem(id="dev", label="Start work", icon="play", color="green"),
        ]
    )
    msg = await asyncio.wait_for(bridge.received(), timeout=1.0)
    assert isinstance(msg, MacroListMsg)
    assert [m.id for m in msg.data.macros] == ["MAKRO", "dev"]
    # Optional fields default cleanly:
    assert msg.data.macros[0].icon == ""
    assert msg.data.macros[0].color == "gray"
    assert msg.data.macros[1].icon == "play"
    assert msg.data.macros[1].color == "green"


async def test_set_locked_true_dispatches() -> None:
    bridge = MockBridge()
    ui = UIState(bridge)
    ui.set_locked(True)
    msg = await asyncio.wait_for(bridge.received(), timeout=1.0)
    assert isinstance(msg, LockStateMsg)
    assert msg.data.locked is True


async def test_set_locked_false_dispatches() -> None:
    bridge = MockBridge()
    ui = UIState(bridge)
    ui.set_locked(False)
    msg = await asyncio.wait_for(bridge.received(), timeout=1.0)
    assert isinstance(msg, LockStateMsg)
    assert msg.data.locked is False


async def test_resend_all_carries_current_lock_state() -> None:
    # If the panel reboots while host is locked, resend_all must push
    # locked=True so the overlay re-appears on the next snapshot.
    bridge = MockBridge()
    ui = UIState(bridge)
    ui.set_locked(True)
    await _drain_pending(ui)
    # Drain whatever the setter pushed.
    while not bridge._outbound.empty():
        await bridge.received()

    await ui.resend_all()

    seen: list[LockStateMsg] = []
    while not bridge._outbound.empty():
        msg = await bridge.received()
        if isinstance(msg, LockStateMsg):
            seen.append(msg)
    assert len(seen) == 1
    assert seen[0].data.locked is True


async def test_set_fullscreen_dispatches() -> None:
    bridge = MockBridge()
    ui = UIState(bridge)
    data = FullscreenData(
        kind="break_short",
        title="Krótka przerwa",
        message="Wstań",
        duration_sec=300,
    )
    ui.set_fullscreen(data)
    msg = await asyncio.wait_for(bridge.received(), timeout=1.0)
    assert isinstance(msg, FullscreenMsg)
    assert msg.data.kind == "break_short"


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
# resend_all: 8 messages
# (top_bar + 4 screens + pomodoro_state + lock_state + macro_list)
# ---------------------------------------------------------------------------


async def test_resend_all_sends_eight_messages() -> None:
    bridge = MockBridge()
    ui = UIState(bridge)

    # Optionally set some state to make sure the right data is pushed.
    ui.set_screen_4(items=[TodoItem(id="x1", text="Item", done=False)])
    # Drain that one dispatch so the queue starts clean for resend_all.
    await asyncio.wait_for(bridge.received(), timeout=1.0)

    await ui.resend_all()

    assert bridge._outbound.qsize() == 8


async def test_resend_all_message_types() -> None:
    bridge = MockBridge()
    ui = UIState(bridge)

    await ui.resend_all()

    msgs = [await bridge.received() for _ in range(8)]
    types = {type(m).__name__ for m in msgs}
    assert types == {
        "TopBarMsg",
        "Screen1Msg",
        "Screen2Msg",
        "Screen3Msg",
        "Screen4Msg",
        "PomodoroStateMsg",
        "LockStateMsg",
        "MacroListMsg",
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


# ---------------------------------------------------------------------------
# Per-field top_bar setters (M6.1)
# ---------------------------------------------------------------------------


async def _drain_all_top_bar(bridge: MockBridge) -> list[TopBarMsg]:
    """Drain all messages on bridge, returning only TopBarMsg envelopes."""
    out: list[TopBarMsg] = []
    while not bridge._outbound.empty():
        msg = await bridge.received()
        if isinstance(msg, TopBarMsg):
            out.append(msg)
    return out


async def test_set_weather_patches_only_weather_field() -> None:
    bridge = MockBridge()
    ui = UIState(bridge)
    ui.set_top_bar(
        TopBarData(
            clock="10:00",
            date="śr 20.05",
            weather="",
            claude_usage="",
            pomodoro_counter=2,
        )
    )
    await _drain_pending(ui)

    ui.set_weather("18°C ☀")
    await _drain_pending(ui)

    sent = await _drain_all_top_bar(bridge)
    assert sent[-1].data.weather == "18°C ☀"
    assert sent[-1].data.clock == "10:00"
    assert sent[-1].data.date == "śr 20.05"
    assert sent[-1].data.claude_usage == ""
    assert sent[-1].data.pomodoro_counter == 2


async def test_set_claude_usage_patches_only_claude_field() -> None:
    bridge = MockBridge()
    ui = UIState(bridge)
    ui.set_top_bar(
        TopBarData(
            clock="10:00",
            date="śr 20.05",
            weather="18°C ☀",
            claude_usage="",
            pomodoro_counter=0,
        )
    )
    await _drain_pending(ui)

    ui.set_claude_usage("47%")
    await _drain_pending(ui)

    sent = await _drain_all_top_bar(bridge)
    assert sent[-1].data.claude_usage == "47%"
    assert sent[-1].data.weather == "18°C ☀"
    assert sent[-1].data.clock == "10:00"
    assert sent[-1].data.date == "śr 20.05"
    assert sent[-1].data.pomodoro_counter == 0


async def test_set_clock_patches_clock_and_date() -> None:
    bridge = MockBridge()
    ui = UIState(bridge)
    ui.set_top_bar(
        TopBarData(
            clock="--:--",
            date="",
            weather="18°C ☀",
            claude_usage="47%",
            pomodoro_counter=3,
        )
    )
    await _drain_pending(ui)

    ui.set_clock(clock="10:32", date="śr 20.05")
    await _drain_pending(ui)

    sent = await _drain_all_top_bar(bridge)
    assert sent[-1].data.clock == "10:32"
    assert sent[-1].data.date == "śr 20.05"
    assert sent[-1].data.weather == "18°C ☀"
    assert sent[-1].data.claude_usage == "47%"
    assert sent[-1].data.pomodoro_counter == 3
