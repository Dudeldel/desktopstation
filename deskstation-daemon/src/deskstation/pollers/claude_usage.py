"""Claude usage poller — shells out to ``ccusage --json`` (configurable argv).

Expects stdout to be JSON of the shape ``{"percent_today": <float 0-100>}``.
Falls back to scanning common alternative key names (``percent``, ``usage_pct``)
so other tooling can be slotted in by config without touching code. On missing
binary (``FileNotFoundError``) the poller logs once and sets ``disabled = True``,
short-circuiting future ticks.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from deskstation.ui_state import UIState

log = structlog.get_logger(__name__)

RunArgvFn = Callable[[list[str], float], Awaitable[tuple[int, bytes, bytes]]]

_PERCENT_KEYS = ("percent_today", "percent", "usage_pct")


async def _run_argv(argv: list[str], timeout: float) -> tuple[int, bytes, bytes]:
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise
    return proc.returncode or 0, stdout, stderr


def format_usage(pct: float) -> str:
    clamped = max(0.0, min(pct, 100.0))
    return f"{round(clamped)}%"


def _parse_percent(stdout: bytes) -> float | None:
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    for key in _PERCENT_KEYS:
        if key in data:
            try:
                return float(data[key])
            except (TypeError, ValueError):
                return None
    return None


class ClaudeUsagePoller:
    def __init__(
        self,
        ui_state: UIState,
        command: list[str],
        interval_sec: float = 5 * 60,
        timeout_sec: float = 10.0,
        run_argv: RunArgvFn | None = None,
    ) -> None:
        self._ui = ui_state
        self._cmd = command
        self.interval_sec = interval_sec
        self._timeout = timeout_sec
        self._run_argv: RunArgvFn = run_argv or _run_argv
        self.disabled = False

    async def tick(self) -> None:
        if self.disabled:
            return
        try:
            rc, stdout, stderr = await self._run_argv(self._cmd, self._timeout)
        except FileNotFoundError:
            log.warning("claude_usage_binary_missing", command=self._cmd[0])
            self.disabled = True
            return
        except TimeoutError:
            log.warning("claude_usage_timeout", command=self._cmd)
            return
        if rc != 0:
            log.warning(
                "claude_usage_nonzero_exit",
                command=self._cmd,
                rc=rc,
                stderr=stderr[:200].decode("utf-8", errors="replace"),
            )
            return
        pct = _parse_percent(stdout)
        if pct is None:
            log.warning(
                "claude_usage_parse_failed",
                stdout=stdout[:200].decode("utf-8", errors="replace"),
            )
            return
        self._ui.set_claude_usage(format_usage(pct))

    async def run_forever(self) -> None:
        while True:
            await self.tick()
            await asyncio.sleep(self.interval_sec)
