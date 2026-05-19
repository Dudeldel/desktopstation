"""Real Bitbucket poller: drives screen_3 with merged PRs + CI state.

Inherits from `MockPoller` purely for the `run_forever()` + tick-error wrapper.
Per tick it asks the `BitbucketClient` for the current user's open PRs and any
PRs awaiting review across the configured repos, merges them (review first,
then mine), fetches the latest pipeline state for each configured repo, and
pushes a `screen_3` snapshot to UIState.

Error policy mirrors `JiraPoller`:
- `BitbucketAuthError`: log once, set `auth_failed`, re-raise so the
  `MockPoller.run_forever()` wrapper logs the failure. Subsequent ticks
  short-circuit so we don't spam the log every interval.
- `BitbucketTransientError`: log a warning and return — UIState keeps the
  last good values. Transient errors from individual `latest_pipeline` calls
  are caught per-repo so a single flaky repo doesn't blank the whole screen.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

import structlog

from deskstation.bridge.protocol import PullRequest
from deskstation.clients.bitbucket import (
    BitbucketAuthError,
    BitbucketClient,
    BitbucketTransientError,
    Pr,
)
from deskstation.pollers.mock import MockPoller

if TYPE_CHECKING:
    from deskstation.ui_state import UIState

log = structlog.get_logger(__name__)


_CiLiteral = Literal["passing", "failing", "running", "unknown"]


def _state_to_ci(state: str | None) -> _CiLiteral:
    """Map a Bitbucket pipeline state to the PullRequest.ci literal."""
    if state == "SUCCESSFUL":
        return "passing"
    if state == "FAILED":
        return "failing"
    if state in ("PENDING", "IN_PROGRESS"):
        return "running"
    # STOPPED, None, anything else.
    return "unknown"


class BitbucketPoller(MockPoller):
    def __init__(
        self,
        ui_state: UIState,
        client: BitbucketClient,
        username: str,
        repos: list[str],
        interval_sec: float = 60.0,
    ) -> None:
        super().__init__(ui_state, interval_sec)
        self._client = client
        self._username = username
        self._repos = list(repos)  # defensive copy
        self.auth_failed = False

    async def tick(self) -> None:
        if self.auth_failed:
            return

        try:
            my_prs = await self._client.list_my_open_prs(self._username)
            review_prs = await self._client.list_review_prs(self._username, self._repos)
        except BitbucketAuthError:
            self.auth_failed = True
            log.error("bitbucket_poller_auth_failed")
            raise
        except BitbucketTransientError as exc:
            log.warning("bitbucket_poller_transient_error", error=str(exc))
            return

        # Pipelines per repo. Auth errors propagate; transient errors only skip
        # that repo so a single flaky pipeline doesn't blank the whole screen.
        pipeline_map: dict[str, str] = {}
        for repo in self._repos:
            try:
                run = await self._client.latest_pipeline(repo)
            except BitbucketAuthError:
                self.auth_failed = True
                log.error("bitbucket_poller_auth_failed")
                raise
            except BitbucketTransientError as exc:
                log.warning(
                    "bitbucket_poller_transient_error",
                    endpoint="latest_pipeline",
                    repo=repo,
                    error=str(exc),
                )
                continue
            if run is None:
                continue
            pipeline_map[repo] = run.state

        # Review PRs come first — review-needed work should sit above one's own.
        merged: list[Pr] = list(review_prs) + list(my_prs)
        mapped = [self._to_pull_request(pr, pipeline_map) for pr in merged]

        self.ui_state.set_screen_3(prs=mapped)

    @staticmethod
    def _to_pull_request(pr: Pr, pipeline_map: dict[str, str]) -> PullRequest:
        # M4 placeholder: only review-kind vs open. Wiring "approved" /
        # "changes_requested" from pr.approvals + per-participant state is a M6
        # follow-up (PR detail polish).
        status: Literal["open", "needs_review"] = "needs_review" if pr.kind == "review" else "open"
        return PullRequest(
            id=pr.id,
            title=pr.title,
            author=pr.author_username,
            repo=pr.repo,
            status=status,
            ci=_state_to_ci(pipeline_map.get(pr.repo)),
        )
