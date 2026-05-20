"""M6 integration smoke: every poller/listener/engine fakes its external
dependency and we verify the cross-component effects observable on
``UIState`` and via the bridge.

Each test boots only the components needed for the property under test
to keep the wiring legible; no end-to-end daemon startup. The point of
the integration layer is to verify cross-component wiring through real
:class:`UIState` and real :class:`MockBridge`, rather than fakes-of-fakes
— each individual component already has unit-test coverage.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock

from deskstation.bridge.mock_bridge import MockBridge
from deskstation.bridge.protocol import (
    FullscreenMsg,
    TopBarData,
    TopBarMsg,
)
from deskstation.clients.openmeteo import WeatherSnapshot
from deskstation.config import MacroDef
from deskstation.engines.standup import StandupEngine
from deskstation.executors.macros import MacroExecutor
from deskstation.listeners.todo_file import TodoFileListener
from deskstation.pollers.weather import WeatherPoller, format_weather
from deskstation.ui_state import UIState


async def _drain_ui_state(ui: UIState) -> None:
    """Wait for any pending UIState dispatch tasks to finish.

    ``UIState`` schedules sends via ``asyncio.create_task`` and rate-limits
    them; the test needs to await those tasks before reading the bridge.
    """
    pending = [t for t in ui._pending.values() if not t.done()]
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


async def _drain_bridge(bridge: MockBridge, timeout: float = 0.2) -> list[object]:
    """Pop every envelope currently sitting in the outbound queue."""
    out: list[object] = []
    while True:
        try:
            env = await asyncio.wait_for(bridge.received(), timeout=timeout)
        except TimeoutError:
            break
        out.append(env)
    return out


async def test_weather_patches_top_bar() -> None:
    """WeatherPoller → UIState.set_weather → TopBarMsg with the new weather
    field, and neighbouring fields (clock) untouched.
    """
    bridge = MockBridge()
    ui = UIState(bridge)
    # Pre-populate the rest of top_bar so the per-field patch is observable.
    ui.set_top_bar(
        TopBarData(
            clock="10:00",
            date="śr 20.05",
            weather="",
            claude_usage="",
            pomodoro_counter=0,
        )
    )
    await _drain_ui_state(ui)
    # Drop the initial TopBarMsg so we look at the patch in isolation.
    await _drain_bridge(bridge)

    client = AsyncMock()
    client.current.return_value = WeatherSnapshot(temp_c=18.4, weather_code=0)
    poller = WeatherPoller(ui, client, latitude=0.0, longitude=0.0)
    await poller.tick()
    await _drain_ui_state(ui)

    sent = await _drain_bridge(bridge)
    top_bars = [m for m in sent if isinstance(m, TopBarMsg)]
    assert top_bars, f"expected a TopBarMsg, got {[type(m).__name__ for m in sent]}"
    assert top_bars[-1].data.weather == format_weather(WeatherSnapshot(temp_c=18.4, weather_code=0))
    # Confirms the per-field setter doesn't clobber neighbours.
    assert top_bars[-1].data.clock == "10:00"
    assert top_bars[-1].data.date == "śr 20.05"


async def test_todo_toggle_round_trip(tmp_path: Path) -> None:
    """TodoFileListener.toggle rewrites the file in-place and reparses,
    and the toggled state survives the round trip.
    """
    p = tmp_path / "todo.md"
    p.write_text("- [ ] alpha\n- [ ] beta\n", encoding="utf-8")

    bridge = MockBridge()
    ui = UIState(bridge)
    listener = TodoFileListener(ui, p)
    listener.reparse_now()

    items = listener.current_items()
    assert [t.text for t in items] == ["alpha", "beta"]
    assert all(not t.done for t in items)

    await listener.toggle(items[1].id)
    assert p.read_text(encoding="utf-8") == "- [ ] alpha\n- [x] beta\n"

    # The optimistic reparse should have flipped the in-memory state too.
    assert listener.current_items()[1].done is True


async def test_macro_executor_invokes_argv() -> None:
    """MacroExecutor.run_by_id resolves the id and calls run_argv with the
    declared argv vector(s) — the ESP can only ever name a macro by id, not
    inject an argv.
    """
    calls: list[list[str]] = []

    async def fake_run_argv(argv: list[str], timeout: float) -> tuple[int, bytes, bytes]:
        calls.append(argv)
        return 0, b"", b""

    ex = MacroExecutor(
        [
            MacroDef(
                id="m1",
                label="M1",
                commands=[["true"], ["echo", "hi"]],
            )
        ],
        run_argv=fake_run_argv,
    )
    await ex.run_by_id("m1")
    assert calls == [["true"], ["echo", "hi"]]

    # Unknown id is a no-op (logged, but does not raise).
    await ex.run_by_id("does-not-exist")
    assert calls == [["true"], ["echo", "hi"]]


async def test_standup_builds_fullscreen() -> None:
    """StandupEngine merges Jira + Bitbucket + git_log (all empty here),
    builds a fullscreen brief, and pushes it through UIState → MockBridge.
    """
    bridge = MockBridge()
    ui = UIState(bridge)

    jira = AsyncMock()
    jira.search.return_value = []
    bb = AsyncMock()
    bb.list_my_merged_prs_since.return_value = []

    async def empty_git_log(
        repo: Path,
        since: datetime,
        until: datetime,
        author_email: str,
    ) -> list[str]:
        return []

    eng = StandupEngine(
        ui,
        jira_client=jira,
        bitbucket_client=bb,
        bitbucket_username="me",
        repos=[],
        git_author_email="me@example.com",
        git_log=empty_git_log,
    )
    await eng.build_and_push(now=datetime(2026, 5, 20, tzinfo=UTC))
    await _drain_ui_state(ui)

    sent = await _drain_bridge(bridge)
    fullscreens = [m for m in sent if isinstance(m, FullscreenMsg)]
    assert fullscreens, (
        f"expected at least one FullscreenMsg, got {[type(m).__name__ for m in sent]}"
    )
    assert fullscreens[-1].data.kind == "standup"
    # Empty-source fallback message is in Polish per the spec.
    assert "24 h" in fullscreens[-1].data.message
