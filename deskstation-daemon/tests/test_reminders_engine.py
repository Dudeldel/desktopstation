import asyncio
from unittest.mock import MagicMock

from deskstation.engines.reminders import RemindersEngine


async def test_alternates_water_and_eyes() -> None:
    pushed: list[str] = []

    class FakeUI:
        def set_fullscreen(self, data: object) -> None:
            pushed.append(data.kind)  # type: ignore[attr-defined]

    pomodoro = MagicMock()
    pomodoro.is_focus_state.return_value = False  # idle

    eng = RemindersEngine(FakeUI(), pomodoro, interval_sec=0.02)  # type: ignore[arg-type]

    task = asyncio.create_task(eng.run_forever())
    await asyncio.sleep(0.2)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert len(pushed) >= 4, f"expected >= 4 ticks, got {len(pushed)}: {pushed}"
    assert pushed[:4] == ["water", "eyes", "water", "eyes"]


async def test_skips_when_pomodoro_focused() -> None:
    pushed: list[str] = []

    class FakeUI:
        def set_fullscreen(self, data: object) -> None:
            pushed.append(data.kind)  # type: ignore[attr-defined]

    pomodoro = MagicMock()
    pomodoro.is_focus_state.return_value = True  # always focused

    eng = RemindersEngine(FakeUI(), pomodoro, interval_sec=0.05)  # type: ignore[arg-type]
    task = asyncio.create_task(eng.run_forever())
    await asyncio.sleep(0.2)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert pushed == []
