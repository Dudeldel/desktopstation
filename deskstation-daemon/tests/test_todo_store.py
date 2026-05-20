from pathlib import Path

from deskstation.store.todo_store import (
    parse_todo_file,
    rewrite_line_toggled,
    todo_line_id,
)


def test_parses_simple_lines(tmp_path: Path) -> None:
    p = tmp_path / "todo.md"
    p.write_text(
        "# my todos\n"
        "- [ ] write spec !high #docs @2026-05-25\n"
        "- [x] done item\n"
        "free-form note\n"
        "- [ ] another\n",
        encoding="utf-8",
    )
    items = parse_todo_file(p)
    texts = [i.text for i in items]
    assert texts == ["write spec !high #docs @2026-05-25", "done item", "another"]
    assert [i.done for i in items] == [False, True, False]
    assert items[0].id == todo_line_id(line_no=2, text="write spec !high #docs @2026-05-25")


def test_rewrite_line_toggled_idempotent(tmp_path: Path) -> None:
    p = tmp_path / "todo.md"
    p.write_text(
        "- [ ] alpha\n- [ ] beta\n- [x] gamma\n",
        encoding="utf-8",
    )
    rewrite_line_toggled(p, line_no=1, want_done=True)
    assert p.read_text("utf-8") == ("- [x] alpha\n- [ ] beta\n- [x] gamma\n")
    rewrite_line_toggled(p, line_no=1, want_done=True)
    assert p.read_text("utf-8").startswith("- [x] alpha\n")
    rewrite_line_toggled(p, line_no=1, want_done=False)
    assert p.read_text("utf-8").startswith("- [ ] alpha\n")


def test_rewrite_preserves_indent_and_eol(tmp_path: Path) -> None:
    p = tmp_path / "todo.md"
    p.write_bytes(b"  - [ ] indented\r\n  - [ ] other\r\n")
    rewrite_line_toggled(p, line_no=1, want_done=True)
    assert p.read_bytes() == b"  - [x] indented\r\n  - [ ] other\r\n"
