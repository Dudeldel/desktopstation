"""Parse + safely-rewrite a Markdown todo file.

Lines that match ``^(\\s*)- \\[( |x|X)\\] (.+?)\\s*$`` become TodoLines. Free-form
lines are ignored. Line numbers are 1-indexed (matches what most editors show);
this is the authoritative ID seed.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

_LINE_RE = re.compile(r"^(?P<indent>\s*)- \[(?P<box> |x|X)\] (?P<text>.+?)\s*$")


@dataclass(frozen=True)
class TodoLine:
    id: str
    line_no: int  # 1-indexed
    text: str
    done: bool


def todo_line_id(line_no: int, text: str) -> str:
    """Stable ID = first 12 hex chars of SHA-1(line_no || '\\x00' || text)."""
    h = hashlib.sha1(f"{line_no}\x00{text}".encode()).hexdigest()
    return h[:12]


def parse_todo_file(path: Path) -> list[TodoLine]:
    if not path.exists():
        return []
    items: list[TodoLine] = []
    with path.open("r", encoding="utf-8") as f:
        for idx, raw in enumerate(f, start=1):
            line = raw.rstrip("\n").rstrip("\r")
            m = _LINE_RE.match(line)
            if m is None:
                continue
            text = m.group("text")
            done = m.group("box").lower() == "x"
            items.append(
                TodoLine(
                    id=todo_line_id(line_no=idx, text=text),
                    line_no=idx,
                    text=text,
                    done=done,
                )
            )
    return items


def rewrite_line_toggled(path: Path, line_no: int, want_done: bool) -> None:
    """Rewrite a single line's checkbox in place. Preserves indent + EOLs.

    Bytes-level so Windows CRLF / mixed CRLF+LF endings survive untouched.
    Classic-Mac CR-only line endings are NOT recognised as terminators
    (the whole file becomes one line). Raises FileNotFoundError if path is
    missing; IndexError if line_no is out of range; ValueError if the
    target line is not a parseable todo entry.
    """
    raw = path.read_bytes()
    parts: list[bytes] = []
    start = 0
    i = 0
    while i < len(raw):
        if raw[i : i + 2] == b"\r\n":
            parts.append(raw[start : i + 2])
            i += 2
            start = i
        elif raw[i : i + 1] == b"\n":
            parts.append(raw[start : i + 1])
            i += 1
            start = i
        else:
            i += 1
    if start < len(raw):
        parts.append(raw[start:])
    if not 1 <= line_no <= len(parts):
        raise IndexError(f"line {line_no} not in file (have {len(parts)} lines)")
    idx = line_no - 1
    line = parts[idx]
    if line.endswith(b"\r\n"):
        eol = b"\r\n"
        body = line[:-2]
    elif line.endswith(b"\n"):
        eol = b"\n"
        body = line[:-1]
    else:
        eol = b""
        body = line
    decoded = body.decode("utf-8")
    m = _LINE_RE.match(decoded)
    if m is None:
        raise ValueError(f"line {line_no} is not a todo entry: {decoded!r}")
    new_box = "x" if want_done else " "
    new_body = f"{m.group('indent')}- [{new_box}] {m.group('text')}"
    parts[idx] = new_body.encode("utf-8") + eol
    path.write_bytes(b"".join(parts))
