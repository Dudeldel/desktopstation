"""Tests for the on-demand standup brief assembler (M6.6)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock

from deskstation.clients.bitbucket import Pr
from deskstation.clients.jira import Issue
from deskstation.engines.standup import StandupEngine


async def test_build_brief_merges_three_sources() -> None:
    jira_client = AsyncMock()
    jira_client.search.return_value = [
        Issue(
            key="DEV-1",
            summary="Wrapping up the foo refactor",
            status="Done",
            status_category="Done",
            assignee_email=None,
        ),
    ]
    bb_client = AsyncMock()
    bb_client.list_my_merged_prs_since.return_value = [
        Pr(
            id="42",
            title="Fix flaky test",
            repo="service-a",
            author_username="me",
            source_branch="fix/flaky",
            dest_branch="main",
            age_hours=12.0,
            approvals=1,
            approvals_required=0,
            kind="mine",
        ),
    ]

    async def fake_git_log(
        repo: Path,
        since: datetime,
        until: datetime,
        author_email: str,
    ) -> list[str]:
        return ["fix(api): tidy headers", "chore: bump deps"]

    pushed: list = []

    class FakeUI:
        def set_fullscreen(self, data) -> None:
            pushed.append(data)

    eng = StandupEngine(
        FakeUI(),  # type: ignore[arg-type]
        jira_client=jira_client,
        bitbucket_client=bb_client,
        bitbucket_username="me",
        repos=[Path("/tmp/repo1")],
        git_author_email="me@example.com",
        git_log=fake_git_log,
    )
    now = datetime(2026, 5, 20, 9, 0, tzinfo=UTC)
    await eng.build_and_push(now=now)
    assert len(pushed) == 1
    msg = pushed[0]
    assert msg.kind == "standup"
    assert "DEV-1" in msg.message
    assert "Fix flaky test" in msg.message
    assert "fix(api): tidy headers" in msg.message


async def test_build_brief_handles_empty_sources() -> None:
    jira_client = AsyncMock()
    jira_client.search.return_value = []
    bb_client = AsyncMock()
    bb_client.list_my_merged_prs_since.return_value = []

    async def fake_git_log(
        repo: Path,
        since: datetime,
        until: datetime,
        author_email: str,
    ) -> list[str]:
        return []

    pushed: list = []

    class FakeUI:
        def set_fullscreen(self, data) -> None:
            pushed.append(data)

    eng = StandupEngine(
        FakeUI(),  # type: ignore[arg-type]
        jira_client=jira_client,
        bitbucket_client=bb_client,
        bitbucket_username="me",
        repos=[],
        git_author_email="me@example.com",
        git_log=fake_git_log,
    )
    await eng.build_and_push()
    assert pushed[0].kind == "standup"
    assert pushed[0].message  # non-empty
