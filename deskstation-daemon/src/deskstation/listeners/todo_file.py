"""Watchdog-driven todo.md listener.

On startup parses the file and pushes screen_4. Subscribes to filesystem
modify/create/move events for the file's parent directory (some editors
write via "create temp + rename", so a directory watch catches both).
Re-parses on any event whose target path matches our watched file.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

import structlog
from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.api import BaseObserver

from deskstation.bridge.protocol import TodoItem
from deskstation.store.todo_store import (
    TodoLine,
    parse_todo_file,
    rewrite_line_toggled,
)

if TYPE_CHECKING:
    from deskstation.ui_state import UIState

log = structlog.get_logger(__name__)


class _Handler(FileSystemEventHandler):
    def __init__(self, listener: TodoFileListener) -> None:
        self._listener = listener

    def on_modified(self, event: FileSystemEvent) -> None:
        self._listener._on_fs_event(event)

    def on_created(self, event: FileSystemEvent) -> None:
        self._listener._on_fs_event(event)

    def on_moved(self, event: FileSystemEvent) -> None:
        self._listener._on_fs_event(event)


class TodoFileListener:
    def __init__(self, ui_state: UIState, path: Path) -> None:
        self._ui = ui_state
        self._path = Path(path).expanduser()
        self._items: list[TodoLine] = []
        self._observer: BaseObserver | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def current_items(self) -> list[TodoLine]:
        return list(self._items)

    def reparse_now(self) -> None:
        self._items = parse_todo_file(self._path)
        items = [TodoItem(id=t.id, text=t.text, done=t.done) for t in self._items]
        self._ui.set_screen_4(items)

    async def toggle(self, todo_id: str) -> None:
        match = next((t for t in self._items if t.id == todo_id), None)
        if match is None:
            log.warning("todo_toggle_unknown_id", todo_id=todo_id)
            return
        try:
            rewrite_line_toggled(
                self._path,
                line_no=match.line_no,
                want_done=not match.done,
            )
        except (FileNotFoundError, IndexError, ValueError) as exc:
            log.warning(
                "todo_toggle_rewrite_failed",
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return
        # Optimistic reparse — the watchdog event will fire too, but we
        # don't want to wait for it.
        self.reparse_now()

    def start(self) -> None:
        if self._observer is not None:
            return
        self._loop = asyncio.get_running_loop()
        self._observer = Observer()
        watch_dir = str(self._path.parent)
        self._observer.schedule(_Handler(self), watch_dir, recursive=False)
        self._observer.start()
        self.reparse_now()

    def stop(self) -> None:
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=2.0)
            self._observer = None

    # Internal — called from the watchdog thread.
    def _on_fs_event(self, event: FileSystemEvent) -> None:
        try:
            ev_path = Path(_as_str(event.src_path)).resolve()
        except OSError:
            return
        try:
            target = self._path.resolve()
        except OSError:
            return
        if ev_path != target:
            dest = _as_str(getattr(event, "dest_path", ""))
            if not dest:
                return
            try:
                if Path(dest).resolve() != target:
                    return
            except OSError:
                return
        loop = self._loop
        if loop is None:
            return
        loop.call_soon_threadsafe(self.reparse_now)


def _as_str(p: str | bytes) -> str:
    """watchdog's event paths are typed ``bytes | str``; normalise to str."""
    if isinstance(p, bytes):
        return p.decode("utf-8", errors="replace")
    return p
