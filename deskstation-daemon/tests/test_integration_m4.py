"""M4.6 integration tests: end-to-end Jira poller wiring + mock skip behaviour."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import respx

from deskstation.bridge.mock_bridge import MockBridge
from deskstation.bridge.protocol import Screen1Msg
from deskstation.clients.jira import JiraClient
from deskstation.pollers.jira import JQL_MY_TASKS, JiraPoller
from deskstation.pollers.mock import start_all_mocks
from deskstation.store.api_cache import ApiCache
from deskstation.ui_state import UIState

BASE_URL = "https://example.atlassian.net"

_MY_TASKS_PAYLOAD = {
    "issues": [
        {
            "key": "DEV-100",
            "fields": {
                "summary": "Refaktor pomodoro engine",
                "status": {
                    "name": "In Progress",
                    "statusCategory": {"name": "In Progress"},
                },
                "assignee": {"emailAddress": "me@example.com"},
            },
        },
        {
            "key": "DEV-101",
            "fields": {
                "summary": "Naprawa race condition",
                "status": {
                    "name": "To Do",
                    "statusCategory": {"name": "To Do"},
                },
                "assignee": {"emailAddress": "me@example.com"},
            },
        },
    ]
}

_SPRINT_PAYLOAD = {
    "issues": [
        {
            "key": "DEV-200",
            "fields": {
                "summary": "Integracja z Calendar",
                "status": {
                    "name": "To Do",
                    "statusCategory": {"name": "To Do"},
                },
                "assignee": None,
            },
        },
        {
            "key": "DEV-201",
            "fields": {
                "summary": "Widget pogody w top bar",
                "status": {
                    "name": "To Do",
                    "statusCategory": {"name": "To Do"},
                },
                "assignee": None,
            },
        },
        {
            "key": "DEV-202",
            "fields": {
                "summary": "Testy integracyjne M4",
                "status": {
                    "name": "To Do",
                    "statusCategory": {"name": "To Do"},
                },
                "assignee": None,
            },
        },
    ]
}


def _route_search(request: httpx.Request) -> httpx.Response:
    """Inspect the JQL in the POST body and return the matching fixture."""
    body = json.loads(request.content)
    jql = body.get("jql", "")
    if jql == JQL_MY_TASKS:
        return httpx.Response(200, json=_MY_TASKS_PAYLOAD)
    if "openSprints()" in jql:
        return httpx.Response(200, json=_SPRINT_PAYLOAD)
    return httpx.Response(400, json={"errorMessages": [f"unexpected JQL: {jql}"]})


async def test_jira_poller_to_bridge_end_to_end(tmp_path: Path) -> None:
    cache = ApiCache(tmp_path / "cache.sqlite3")
    bridge = MockBridge()
    ui_state = UIState(bridge)
    client = JiraClient(
        base_url=BASE_URL,
        email="user@example.com",
        api_token="secret-token",
        cache=cache,
    )
    poller = JiraPoller(ui_state, client, project_key="DEV", interval_sec=60.0)

    try:
        with respx.mock(base_url=BASE_URL) as router:
            router.post("/rest/api/3/search/jql").mock(side_effect=_route_search)
            await poller.tick()

            # Drain bridge messages until we see a Screen1Msg (UIState's send
            # is scheduled via create_task — give it a moment to fire).
            screen1: Screen1Msg | None = None
            for _ in range(5):
                msg = await asyncio.wait_for(bridge.received(), timeout=1.0)
                if isinstance(msg, Screen1Msg):
                    screen1 = msg
                    break
            assert screen1 is not None, "no Screen1Msg observed on bridge"

            # today_tasks come from the "my tasks" mock response.
            assert [t.key for t in screen1.data.today_tasks] == ["DEV-100", "DEV-101"]
            assert screen1.data.today_tasks[0].summary == "Refaktor pomodoro engine"

            # queued_tasks come from the "sprint" mock response.
            assert [t.key for t in screen1.data.queued_tasks] == [
                "DEV-200",
                "DEV-201",
                "DEV-202",
            ]
            assert screen1.data.queued_tasks[1].summary == "Widget pogody w top bar"

            # Summary index contains issues from BOTH lists.
            assert poller.lookup_summary("DEV-100") == "Refaktor pomodoro engine"
            assert poller.lookup_summary("DEV-200") == "Integracja z Calendar"
            assert poller.lookup_summary("DEV-NOPE") is None
    finally:
        await client.aclose()


async def test_start_all_mocks_skip_disables_listed_pollers(tmp_path: Path) -> None:
    bridge = MockBridge()
    ui_state = UIState(bridge)

    # Default: all 5 mock pollers run.
    tasks = start_all_mocks(ui_state, interval_sec=3600.0)
    try:
        assert len(tasks) == 5
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    # With skip: only the unlisted ones run.
    tasks = start_all_mocks(ui_state, interval_sec=3600.0, skip={"screen_1", "screen_3"})
    try:
        assert len(tasks) == 3
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    # Unknown keys are silently ignored.
    tasks = start_all_mocks(ui_state, interval_sec=3600.0, skip={"bogus_key"})
    try:
        assert len(tasks) == 5
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    # Empty set behaves like None.
    tasks = start_all_mocks(ui_state, interval_sec=3600.0, skip=set())
    try:
        assert len(tasks) == 5
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


# Third test (optional in the brief): the main._run() skip-building logic is
# entangled with config + secrets loading, signal handlers, and the bridge
# stream consumer — replicating it without booting the daemon would duplicate
# the wiring without adding signal. The behaviour is already covered by:
#   * the unit test above (skip parameter honoured by start_all_mocks)
#   * a code-level review of main.py that adds "screen_1" iff jira_poller is
#     constructed and "screen_3" iff bitbucket_poller is constructed.
# So this third test is intentionally omitted.
