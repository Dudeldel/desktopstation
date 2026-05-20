"""Subprocess macro runner.

The ESP can only ever send ``macro_trigger.name``; this class looks the name
up in a fixed in-memory map populated from ``config.yaml`` at startup, so the
firmware cannot inject arbitrary commands. All argv vectors are executed with
``shell=False``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from deskstation.config import MacroDef

log = structlog.get_logger(__name__)

RunArgvFn = Callable[[list[str], float], Awaitable[tuple[int, bytes, bytes]]]


async def _default_run_argv(argv: list[str], timeout: float) -> tuple[int, bytes, bytes]:
    # Unlike the ccusage poller in M6.3 — which lets TimeoutError propagate so
    # the surrounding interval loop can decide what to do — macros need to
    # keep going to the next command even when one stalls. So we swallow the
    # timeout here and surface it as rc=124 (matching coreutils' ``timeout(1)``).
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
        return 124, b"", b"timeout"
    return proc.returncode or 0, stdout, stderr


class MacroExecutor:
    def __init__(
        self,
        definitions: list[MacroDef],
        timeout_sec: float = 10.0,
        run_argv: RunArgvFn | None = None,
    ) -> None:
        self._by_id = {d.id: d for d in definitions}
        self._timeout = timeout_sec
        self._run_argv: RunArgvFn = run_argv or _default_run_argv

    async def run_by_id(self, macro_id: str) -> None:
        macro = self._by_id.get(macro_id)
        if macro is None:
            log.warning("macro_unknown_id", macro_id=macro_id)
            return
        log.info("macro_start", macro_id=macro_id, label=macro.label)
        for argv in macro.commands:
            try:
                rc, _stdout, stderr = await self._run_argv(argv, self._timeout)
            except Exception as exc:
                # A bad command (e.g., missing binary → FileNotFoundError)
                # should not poison the rest of a multi-step macro.
                log.warning(
                    "macro_command_exception",
                    argv=argv,
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
                continue
            if rc != 0:
                log.warning(
                    "macro_command_nonzero",
                    argv=argv,
                    rc=rc,
                    stderr=stderr[:200].decode("utf-8", errors="replace"),
                )
        log.info("macro_done", macro_id=macro_id)
