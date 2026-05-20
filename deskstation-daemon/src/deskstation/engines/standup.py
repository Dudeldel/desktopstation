"""On-demand standup brief assembler.

Sources (all bounded to a 24 h window ending at the current time):
  * Jira — issues resolved by current user in the last 24 h.
  * Bitbucket — PRs authored by current user, merged in the last 24 h.
  * git log — across configured local repos, ``--author=<email>``.

Output: a single ``fullscreen`` snapshot with ``kind="standup"`` and the
brief in ``message`` (newline-joined bullets), pushed via ``ui_state``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from deskstation.bridge.protocol import FullscreenData
from deskstation.clients.bitbucket import BitbucketAuthError
from deskstation.clients.jira import JiraAuthError, JiraTransientError

if TYPE_CHECKING:
    from deskstation.clients.bitbucket import BitbucketClient
    from deskstation.clients.jira import JiraClient
    from deskstation.ui_state import UIState

log = structlog.get_logger(__name__)

GitLogFn = Callable[[Path, datetime, datetime, str], Awaitable[list[str]]]

STANDUP_JQL = "assignee = currentUser() AND resolved >= -1d ORDER BY resolved DESC"
_MAX_COMMITS_PER_REPO = 5


async def _default_git_log(
    repo: Path,
    since: datetime,
    until: datetime,
    author_email: str,
) -> list[str]:
    if not repo.exists():
        return []
    args = [
        "git",
        "-C",
        str(repo),
        "log",
        f"--since={since.isoformat()}",
        f"--until={until.isoformat()}",
        f"--author={author_email}",
        "--pretty=format:%s",
    ]
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(),
            timeout=10.0,
        )
    except TimeoutError:
        proc.kill()
        await proc.wait()
        log.warning("git_log_timeout", repo=str(repo))
        return []
    if proc.returncode != 0:
        log.warning(
            "git_log_nonzero",
            repo=str(repo),
            rc=proc.returncode,
            stderr=stderr[:500].decode("utf-8", errors="replace"),
        )
        return []
    return [line for line in stdout.decode("utf-8").splitlines() if line.strip()]


class StandupEngine:
    """Builds and pushes a fullscreen standup brief on demand.

    The engine owns no background tasks — ``build_and_push`` is called by the
    ``standup_request`` dispatch handler when the ESP triggers the action.
    """

    def __init__(
        self,
        ui_state: UIState,
        jira_client: JiraClient | None,
        bitbucket_client: BitbucketClient | None,
        bitbucket_username: str,
        repos: list[Path],
        git_author_email: str,
        git_log: GitLogFn | None = None,
    ) -> None:
        self._ui = ui_state
        self._jira = jira_client
        self._bb = bitbucket_client
        self._bb_user = bitbucket_username
        self._repos = repos
        self._email = git_author_email
        self._git_log = git_log or _default_git_log

    async def _jira_lines(self) -> list[str]:
        if self._jira is None:
            return []
        try:
            issues = await self._jira.search(
                STANDUP_JQL,
                fields=["summary", "status"],
                max_results=20,
            )
        except (JiraAuthError, JiraTransientError) as exc:
            log.warning(
                "standup_jira_failed",
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return []
        return [f"{i.key} — {i.summary}" for i in issues]

    async def _bitbucket_lines(self, since: datetime) -> list[str]:
        if self._bb is None or not self._repos:
            return []
        try:
            prs = await self._bb.list_my_merged_prs_since(
                self._bb_user,
                since,
                [r.name for r in self._repos],
            )
        except BitbucketAuthError as exc:
            log.warning("standup_bitbucket_auth_failed", error=str(exc))
            return []
        except Exception as exc:
            log.warning(
                "standup_bitbucket_failed",
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return []
        return [f"PR — {p.title} ({p.repo})" for p in prs]

    async def _git_lines(self, since: datetime, until: datetime) -> list[str]:
        out: list[str] = []
        for repo in self._repos:
            try:
                lines = await self._git_log(repo, since, until, self._email)
            except Exception as exc:
                log.warning(
                    "standup_git_failed",
                    repo=str(repo),
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
                continue
            shown = lines[:_MAX_COMMITS_PER_REPO]
            out.extend(f"git — {line}" for line in shown)
            extra = len(lines) - _MAX_COMMITS_PER_REPO
            if extra > 0:
                out.append(f"git — … (+{extra} more in {repo.name})")
        return out

    async def build_and_push(self, now: datetime | None = None) -> None:
        now = now or datetime.now(UTC)
        since = now - timedelta(hours=24)
        results = await asyncio.gather(
            self._jira_lines(),
            self._bitbucket_lines(since),
            self._git_lines(since, now),
            return_exceptions=True,
        )
        bullets: list[str] = []
        for source_name, result in zip(
            ("jira", "bitbucket", "git"),
            results,
            strict=True,
        ):
            if isinstance(result, BaseException):
                log.warning(
                    "standup_source_unhandled_exception",
                    source=source_name,
                    error=str(result),
                    error_type=type(result).__name__,
                )
                continue
            bullets.extend(result)
        if not bullets:
            message = "Brak aktywności w ciągu ostatnich 24 h."
        else:
            message = "\n".join(f"• {b}" for b in bullets)
        self._ui.set_fullscreen(
            FullscreenData(
                kind="standup",
                title="Standup — wczoraj",
                message=message,
                dismissible=True,
            )
        )
