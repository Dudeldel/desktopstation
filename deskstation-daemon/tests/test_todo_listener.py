import asyncio
from pathlib import Path

from watchdog.events import FileModifiedEvent, FileMovedEvent

from deskstation.listeners.todo_file import TodoFileListener


async def test_listener_initial_parse(tmp_path: Path) -> None:
    p = tmp_path / "todo.md"
    p.write_text("- [ ] alpha\n- [x] beta\n", encoding="utf-8")
    pushed: list[list[tuple[str, bool]]] = []

    class FakeUI:
        def set_screen_4(self, items: list) -> None:
            pushed.append([(i.text, i.done) for i in items])

    listener = TodoFileListener(FakeUI(), p)  # type: ignore[arg-type]
    listener.reparse_now()
    assert pushed == [[("alpha", False), ("beta", True)]]


async def test_listener_toggle_rewrites_and_reparses(tmp_path: Path) -> None:
    p = tmp_path / "todo.md"
    p.write_text("- [ ] alpha\n", encoding="utf-8")
    pushed: list[list[tuple[str, bool]]] = []

    class FakeUI:
        def set_screen_4(self, items: list) -> None:
            pushed.append([(i.text, i.done) for i in items])

    listener = TodoFileListener(FakeUI(), p)  # type: ignore[arg-type]
    listener.reparse_now()
    items = listener.current_items()
    assert items[0].done is False
    await listener.toggle(items[0].id)
    assert p.read_text(encoding="utf-8") == "- [x] alpha\n"
    assert pushed[-1] == [("alpha", True)]


async def test_listener_toggle_unknown_id_is_noop(tmp_path: Path) -> None:
    p = tmp_path / "todo.md"
    p.write_text("- [ ] alpha\n", encoding="utf-8")

    class FakeUI:
        def set_screen_4(self, items: list) -> None:
            pass

    listener = TodoFileListener(FakeUI(), p)  # type: ignore[arg-type]
    listener.reparse_now()
    await listener.toggle("nope")  # must not raise
    assert p.read_text(encoding="utf-8") == "- [ ] alpha\n"


async def test_on_fs_event_ignores_unrelated_paths(tmp_path: Path) -> None:
    p = tmp_path / "todo.md"
    p.write_text("- [ ] alpha\n", encoding="utf-8")

    reparsed: list[None] = []

    class FakeUI:
        def set_screen_4(self, items: list) -> None:
            reparsed.append(None)

    listener = TodoFileListener(FakeUI(), p)  # type: ignore[arg-type]
    listener.reparse_now()
    reparsed.clear()
    # Manually wire a loop ref since we're not calling start().
    listener._loop = asyncio.get_running_loop()
    listener._on_fs_event(FileModifiedEvent(str(tmp_path / "other.md")))
    await asyncio.sleep(0)  # let any scheduled call_soon run
    assert reparsed == []


async def test_on_fs_event_triggers_reparse_on_rename_into_target(tmp_path: Path) -> None:
    p = tmp_path / "todo.md"
    p.write_text("- [ ] alpha\n", encoding="utf-8")

    reparsed: list[None] = []

    class FakeUI:
        def set_screen_4(self, items: list) -> None:
            reparsed.append(None)

    listener = TodoFileListener(FakeUI(), p)  # type: ignore[arg-type]
    listener.reparse_now()
    reparsed.clear()
    listener._loop = asyncio.get_running_loop()
    # Simulate an editor's "write temp + rename onto target" sequence.
    listener._on_fs_event(FileMovedEvent(str(tmp_path / ".todo.md.tmp"), str(p)))
    await asyncio.sleep(0)
    assert reparsed == [None]
