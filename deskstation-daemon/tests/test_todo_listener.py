from pathlib import Path

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
