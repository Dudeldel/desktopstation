"""Tests for the real JiraPoller (M4.4).

Uses a hand-rolled fake JiraClient — the real client is covered by
test_jira_client.py via respx, so here we only verify poller wiring.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from deskstation.bridge.mock_bridge import MockBridge
from deskstation.bridge.protocol import Screen1Msg
from deskstation.clients.jira import Issue, JiraAuthError, JiraTransientError
from deskstation.pollers.jira import JiraPoller
from deskstation.ui_state import UIState


class _FakeJiraClient:
    """Minimal JiraClient stand-in. Each `search()` call pops from `responses`."""

    def __init__(self, responses: list[list[Issue] | Exception]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, list[str]]] = []

    async def search(
        self,
        jql: str,
        fields: list[str],
        max_results: int = 50,
    ) -> list[Issue]:
        self.calls.append((jql, fields))
        if not self._responses:
            raise AssertionError("FakeJiraClient: no more queued responses")
        nxt = self._responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


def _issue(key: str, summary: str, status: str = "To Do") -> Issue:
    return Issue(
        key=key,
        summary=summary,
        status=status,
        status_category="To Do",
        assignee_email="me@example.com",
    )


def _make_poller(
    responses: list[list[Issue] | Exception],
    project_key: str = "DEV",
) -> tuple[JiraPoller, UIState, MockBridge, _FakeJiraClient]:
    bridge = MockBridge()
    ui = UIState(bridge)
    client = _FakeJiraClient(responses)
    poller = JiraPoller(ui, client, project_key, interval_sec=60.0)  # type: ignore[arg-type]
    return poller, ui, bridge, client


async def test_poller_pushes_screen_1_with_both_lists() -> None:
    my = [_issue("DEV-1", "Fix bug A"), _issue("DEV-2", "Fix bug B")]
    sprint = [_issue("DEV-3", "Sprint task X"), _issue("DEV-4", "Sprint task Y")]
    poller, ui, bridge, _ = _make_poller([my, sprint])

    set_screen_1 = MagicMock(wraps=ui.set_screen_1)
    ui.set_screen_1 = set_screen_1  # type: ignore[method-assign]

    await poller.tick()

    set_screen_1.assert_called_once()
    kwargs = set_screen_1.call_args.kwargs
    assert [t.key for t in kwargs["today_tasks"]] == ["DEV-1", "DEV-2"]
    assert [t.key for t in kwargs["queued_tasks"]] == ["DEV-3", "DEV-4"]
    # Drain any pending send so the test doesn't leak a task warning.
    msg = await bridge.received()
    assert isinstance(msg, Screen1Msg)


async def test_poller_builds_task_summary_index() -> None:
    my = [_issue("DEV-1", "My summary one")]
    sprint = [_issue("DEV-99", "Sprint summary")]
    poller, _, _, _ = _make_poller([my, sprint])

    await poller.tick()

    assert poller.lookup_summary("DEV-1") == "My summary one"
    assert poller.lookup_summary("DEV-99") == "Sprint summary"
    assert poller.lookup_summary("DEV-NONEXISTENT") is None


async def test_poller_handles_transient_error() -> None:
    poller, ui, _, _ = _make_poller([JiraTransientError("503")])
    set_screen_1 = MagicMock()
    ui.set_screen_1 = set_screen_1  # type: ignore[method-assign]

    await poller.tick()  # should not raise

    set_screen_1.assert_not_called()


async def test_poller_handles_auth_error_then_short_circuits() -> None:
    poller, _, _, client = _make_poller([JiraAuthError("401")])

    with pytest.raises(JiraAuthError):
        await poller.tick()

    assert poller.auth_failed is True
    calls_after_first = len(client.calls)
    # Second tick must short-circuit and not touch the client.
    await poller.tick()
    assert len(client.calls) == calls_after_first


async def test_poller_uses_configured_project_key() -> None:
    poller, _, _, client = _make_poller([[], []], project_key="ACME")

    await poller.tick()

    # Two calls: my-tasks JQL, then sprint JQL — second should contain project key.
    assert len(client.calls) == 2
    sprint_jql, _ = client.calls[1]
    assert "ACME" in sprint_jql


async def test_poller_replaces_index_each_tick() -> None:
    """Stale entries should be pruned when subsequent ticks return fewer issues."""
    poller, _, _, _ = _make_poller(
        [
            [_issue("DEV-1", "first")],
            [_issue("DEV-2", "second")],
            [_issue("DEV-3", "third")],
            [],
        ]
    )
    await poller.tick()
    assert poller.lookup_summary("DEV-1") == "first"

    await poller.tick()
    # First-tick entries should be gone.
    assert poller.lookup_summary("DEV-1") is None
    assert poller.lookup_summary("DEV-3") == "third"


async def test_poller_handles_empty_results() -> None:
    poller, _ui, bridge, _ = _make_poller([[], []])
    await poller.tick()
    msg = await bridge.received()
    assert isinstance(msg, Screen1Msg)
    assert msg.data.today_tasks == []
    assert msg.data.queued_tasks == []
