import json

import pytest

from deskstation.pollers.claude_usage import ClaudeUsagePoller, format_usage


def test_format_usage_percent() -> None:
    assert format_usage(47.0) == "47%"
    assert format_usage(0.0) == "0%"
    assert format_usage(99.9) == "100%"


async def test_poller_patches_when_subprocess_returns_json(monkeypatch: pytest.MonkeyPatch) -> None:
    pushed: list[str] = []

    class FakeUI:
        def set_claude_usage(self, v: str) -> None:
            pushed.append(v)

    async def fake_run_argv(argv: list[str], timeout: float) -> tuple[int, bytes, bytes]:
        assert argv == ["ccusage", "--json"]
        return 0, json.dumps({"percent_today": 47.0}).encode(), b""

    monkeypatch.setattr(
        "deskstation.pollers.claude_usage._run_argv",
        fake_run_argv,
    )
    poller = ClaudeUsagePoller(FakeUI(), command=["ccusage", "--json"])  # type: ignore[arg-type]
    await poller.tick()
    assert pushed == ["47%"]
    assert not poller.disabled


async def test_poller_disables_on_missing_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    pushed: list[str] = []

    class FakeUI:
        def set_claude_usage(self, v: str) -> None:
            pushed.append(v)

    async def fake_run_argv(argv: list[str], timeout: float) -> tuple[int, bytes, bytes]:
        raise FileNotFoundError("ccusage")

    monkeypatch.setattr(
        "deskstation.pollers.claude_usage._run_argv",
        fake_run_argv,
    )
    poller = ClaudeUsagePoller(FakeUI(), command=["ccusage", "--json"])  # type: ignore[arg-type]
    await poller.tick()
    assert pushed == []
    assert poller.disabled
    # Second tick is a no-op.
    await poller.tick()
    assert pushed == []
