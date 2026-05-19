"""Tests for the real BitbucketPoller (M4.5).

Uses a hand-rolled fake BitbucketClient — the real client is covered by
test_bitbucket_client.py via respx, so here we only verify poller wiring.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from deskstation.bridge.mock_bridge import MockBridge
from deskstation.bridge.protocol import Screen3Msg
from deskstation.clients.bitbucket import (
    BitbucketAuthError,
    BitbucketTransientError,
    PipelineRun,
    Pr,
)
from deskstation.pollers.bitbucket import BitbucketPoller, _state_to_ci
from deskstation.ui_state import UIState


class _FakeBitbucketClient:
    """Minimal BitbucketClient stand-in with FIFO queues per method.

    Each call pops the next response off the corresponding queue. An exhausted
    queue raises AssertionError so accidental over-calls are caught loudly.
    Mirrors the pattern in `test_jira_poller.py::_FakeJiraClient`.
    """

    def __init__(
        self,
        my_prs: list[list[Pr] | Exception],
        review_prs: list[list[Pr] | Exception],
        pipelines: dict[str, list[PipelineRun | None | Exception]] | None = None,
    ) -> None:
        self._my_prs = list(my_prs)
        self._review_prs = list(review_prs)
        self._pipelines: dict[str, list[PipelineRun | None | Exception]] = {
            k: list(v) for k, v in (pipelines or {}).items()
        }
        self.my_prs_calls: list[str] = []
        self.review_prs_calls: list[tuple[str, list[str]]] = []
        self.pipeline_calls: list[str] = []

    async def list_my_open_prs(self, username: str) -> list[Pr]:
        self.my_prs_calls.append(username)
        if not self._my_prs:
            raise AssertionError("unexpected call to list_my_open_prs")
        nxt = self._my_prs.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt

    async def list_review_prs(self, username: str, repos: list[str]) -> list[Pr]:
        self.review_prs_calls.append((username, list(repos)))
        if not self._review_prs:
            raise AssertionError("unexpected call to list_review_prs")
        nxt = self._review_prs.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt

    async def latest_pipeline(self, repo: str, branch: str = "main") -> PipelineRun | None:
        self.pipeline_calls.append(repo)
        queue = self._pipelines.get(repo)
        if not queue:
            raise AssertionError("unexpected call to latest_pipeline")
        nxt = queue.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


def _pr(
    pr_id: str,
    title: str,
    repo: str,
    author: str,
    kind: str,
) -> Pr:
    return Pr(
        id=pr_id,
        title=title,
        repo=repo,
        author_username=author,
        source_branch="feature/x",
        dest_branch="main",
        age_hours=1.0,
        approvals=0,
        approvals_required=0,
        kind=kind,  # type: ignore[arg-type]
    )


def _pipeline(repo: str, state: str) -> PipelineRun:
    return PipelineRun(
        repo=repo,
        branch="main",
        state=state,
        started_iso="2026-05-19T10:00:00+00:00",
        completed_iso="2026-05-19T10:05:00+00:00",
    )


def _make_poller(
    my_prs: list[list[Pr] | Exception],
    review_prs: list[list[Pr] | Exception],
    pipelines: dict[str, list[PipelineRun | None | Exception]] | None = None,
    repos: list[str] | None = None,
    username: str = "alice",
) -> tuple[BitbucketPoller, UIState, MockBridge, _FakeBitbucketClient]:
    bridge = MockBridge()
    ui = UIState(bridge)
    client = _FakeBitbucketClient(my_prs, review_prs, pipelines)
    poller = BitbucketPoller(
        ui,
        client,  # type: ignore[arg-type]
        username,
        repos if repos is not None else ["app"],
        interval_sec=60.0,
    )
    return poller, ui, bridge, client


async def test_poller_pushes_screen_3() -> None:
    my = [_pr("1", "my pr", "app", "alice", "mine")]
    review = [_pr("2", "review me", "app", "bob", "review")]
    pipelines: dict[str, list[PipelineRun | None | Exception]] = {
        "app": [_pipeline("app", "SUCCESSFUL")],
    }
    poller, _ui, bridge, _ = _make_poller([my], [review], pipelines, repos=["app"])

    await poller.tick()

    msg = await bridge.received()
    assert isinstance(msg, Screen3Msg)
    assert [p.id for p in msg.data.prs] == ["2", "1"]  # review first
    # Both PRs in repo "app", pipeline SUCCESSFUL -> ci="passing"
    assert all(p.ci == "passing" for p in msg.data.prs)


def test_poller_state_to_ci_mapping() -> None:
    assert _state_to_ci("SUCCESSFUL") == "passing"
    assert _state_to_ci("FAILED") == "failing"
    assert _state_to_ci("PENDING") == "running"
    assert _state_to_ci("IN_PROGRESS") == "running"
    assert _state_to_ci("STOPPED") == "unknown"
    assert _state_to_ci(None) == "unknown"
    assert _state_to_ci("UNKNOWN_STATE") == "unknown"


async def test_poller_handles_transient_error_on_my_prs() -> None:
    # my_prs raises -> review_prs is never reached, so no entry needed there.
    poller, ui, _, client = _make_poller(
        [BitbucketTransientError("503")],
        [],
    )
    set_screen_3 = MagicMock()
    ui.set_screen_3 = set_screen_3  # type: ignore[method-assign]

    await poller.tick()  # must not raise

    set_screen_3.assert_not_called()
    # pipeline shouldn't have been called either — we bailed before that step.
    assert client.pipeline_calls == []


async def test_poller_handles_auth_error_then_short_circuits() -> None:
    # Only the first tick reaches the fake; second tick is guarded by
    # auth_failed and must short-circuit before any client call. So we
    # enqueue exactly one response for my_prs and nothing else.
    poller, _, _, client = _make_poller(
        [BitbucketAuthError("401")],
        [],
    )

    with pytest.raises(BitbucketAuthError):
        await poller.tick()

    assert poller.auth_failed is True
    calls_after_first = len(client.my_prs_calls)
    # Second tick must short-circuit and not touch the client.
    await poller.tick()
    assert len(client.my_prs_calls) == calls_after_first
    assert client.review_prs_calls == []
    assert client.pipeline_calls == []


async def test_poller_pipeline_error_skips_repo() -> None:
    my = [_pr("1", "my pr in app", "app", "alice", "mine")]
    review = [_pr("2", "review me in backend", "backend", "bob", "review")]
    pipelines: dict[str, list[PipelineRun | None | Exception]] = {
        "app": [BitbucketTransientError("pipeline 503")],
        "backend": [_pipeline("backend", "SUCCESSFUL")],
    }
    poller, _ui, bridge, _ = _make_poller([my], [review], pipelines, repos=["app", "backend"])

    await poller.tick()

    msg = await bridge.received()
    assert isinstance(msg, Screen3Msg)
    by_repo = {p.repo: p.ci for p in msg.data.prs}
    assert by_repo["app"] == "unknown"
    assert by_repo["backend"] == "passing"


async def test_poller_handles_no_pipeline_data() -> None:
    my = [_pr("1", "my pr", "app", "alice", "mine")]
    review = [_pr("2", "review me", "app", "bob", "review")]
    pipelines: dict[str, list[PipelineRun | None | Exception]] = {"app": [None]}
    poller, _ui, bridge, _ = _make_poller([my], [review], pipelines, repos=["app"])

    await poller.tick()

    msg = await bridge.received()
    assert isinstance(msg, Screen3Msg)
    assert all(p.ci == "unknown" for p in msg.data.prs)


async def test_poller_status_kind_mapping() -> None:
    my = [_pr("1", "mine", "app", "alice", "mine")]
    review = [_pr("2", "reviewer", "app", "bob", "review")]
    poller, _ui, bridge, _ = _make_poller([my], [review], {"app": [None]}, repos=["app"])

    await poller.tick()

    msg = await bridge.received()
    assert isinstance(msg, Screen3Msg)
    by_id = {p.id: p.status for p in msg.data.prs}
    assert by_id["2"] == "needs_review"
    assert by_id["1"] == "open"
