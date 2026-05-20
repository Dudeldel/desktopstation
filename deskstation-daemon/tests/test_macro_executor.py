from deskstation.config import MacroDef
from deskstation.executors.macros import MacroExecutor


async def test_run_by_id_executes_commands_in_order() -> None:
    calls: list[list[str]] = []

    async def fake_run_argv(argv: list[str], timeout: float) -> tuple[int, bytes, bytes]:
        calls.append(argv)
        return 0, b"", b""

    ex = MacroExecutor(
        [MacroDef(id="alpha", label="A", commands=[["echo", "1"], ["echo", "2"]])],
        run_argv=fake_run_argv,
    )
    await ex.run_by_id("alpha")
    assert calls == [["echo", "1"], ["echo", "2"]]


async def test_run_by_id_unknown_logs_and_skips() -> None:
    async def fake_run_argv(argv: list[str], timeout: float) -> tuple[int, bytes, bytes]:
        raise AssertionError("should not be called")

    ex = MacroExecutor([], run_argv=fake_run_argv)
    await ex.run_by_id("nope")  # no raise


async def test_run_by_id_continues_on_nonzero_exit() -> None:
    calls: list[list[str]] = []
    returns: list[tuple[int, bytes, bytes]] = [(1, b"", b"boom"), (0, b"", b"")]

    async def fake_run_argv(argv: list[str], timeout: float) -> tuple[int, bytes, bytes]:
        calls.append(argv)
        return returns.pop(0)

    ex = MacroExecutor(
        [MacroDef(id="m", label="M", commands=[["false"], ["echo", "ok"]])],
        run_argv=fake_run_argv,
    )
    await ex.run_by_id("m")
    assert calls == [["false"], ["echo", "ok"]]
