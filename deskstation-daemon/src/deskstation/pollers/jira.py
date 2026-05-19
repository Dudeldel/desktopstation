"""Real Jira poller: drives screen_1 + maintains a task summary index.

Inherits from `MockPoller` purely for the `run_forever()` + tick-error wrapper.
Per tick it issues two JQL searches (my open tasks + active sprint), maps the
results into the protocol's `JiraTask` model, pushes them to UIState, and
rebuilds a `key -> summary` cache that the pomodoro engine consults when a
task is started without an explicit summary.

Error policy:
- `JiraAuthError`: log once, set `auth_failed`, re-raise so the
  `MockPoller.run_forever()` wrapper logs the failure. Subsequent ticks
  short-circuit so we don't spam the log every interval.
- `JiraTransientError`: log a warning and return — UIState keeps the last
  good values.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from deskstation.bridge.protocol import JiraTask
from deskstation.clients.jira import (
    Issue,
    JiraAuthError,
    JiraClient,
    JiraTransientError,
)
from deskstation.pollers.mock import MockPoller

if TYPE_CHECKING:
    from deskstation.ui_state import UIState

log = structlog.get_logger(__name__)

JQL_MY_TASKS = (
    "assignee = currentUser() AND statusCategory != Done "
    'AND status in (Draft, "To Do", "In Progress") '
    "ORDER BY updated DESC"
)

_FIELDS = ["summary", "status", "assignee"]


class JiraPoller(MockPoller):
    def __init__(
        self,
        ui_state: UIState,
        client: JiraClient,
        project_key: str,
        interval_sec: float = 60.0,
    ) -> None:
        super().__init__(ui_state, interval_sec)
        self._client = client
        self._project_key = project_key
        self._sprint_jql = f'project = "{project_key}" AND sprint in openSprints() ORDER BY status'
        self._task_summary_index: dict[str, str] = {}
        self.auth_failed = False

    async def tick(self) -> None:
        if self.auth_failed:
            return

        try:
            my_tasks = await self._client.search(JQL_MY_TASKS, fields=_FIELDS)
            sprint_tasks = await self._client.search(self._sprint_jql, fields=_FIELDS)
        except JiraAuthError:
            self.auth_failed = True
            log.error("jira_poller_auth_failed")
            raise
        except JiraTransientError as exc:
            log.warning("jira_poller_transient_error", error=str(exc))
            return

        today = [self._to_task(issue) for issue in my_tasks]
        queued = [self._to_task(issue) for issue in sprint_tasks]

        self.ui_state.set_screen_1(today_tasks=today, queued_tasks=queued)

        # Replace the index entirely so stale entries get pruned.
        index: dict[str, str] = {}
        for issue in my_tasks:
            index[issue.key] = issue.summary
        for issue in sprint_tasks:
            index[issue.key] = issue.summary
        self._task_summary_index = index

    def lookup_summary(self, key: str) -> str | None:
        return self._task_summary_index.get(key)

    @staticmethod
    def _to_task(issue: Issue) -> JiraTask:
        return JiraTask(
            key=issue.key,
            summary=issue.summary,
            status=issue.status,
            is_current=False,
        )
