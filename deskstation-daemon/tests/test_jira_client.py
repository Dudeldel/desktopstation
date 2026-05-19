"""Tests for the Jira REST client."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import respx

from deskstation.clients.jira import (
    Issue,
    JiraAuthError,
    JiraClient,
    JiraTransientError,
    SprintInfo,
)
from deskstation.store.api_cache import ApiCache

BASE_URL = "https://example.atlassian.net"

_SEARCH_PAYLOAD = {
    "issues": [
        {
            "key": "DEV-1",
            "fields": {
                "summary": "Fix bug",
                "status": {
                    "name": "In Progress",
                    "statusCategory": {"name": "In Progress"},
                },
                "assignee": {"emailAddress": "alice@example.com"},
            },
        },
        {
            "key": "DEV-2",
            "fields": {
                "summary": "New feature",
                "status": {
                    "name": "To Do",
                    "statusCategory": {"name": "To Do"},
                },
                "assignee": None,
            },
        },
    ]
}


def _make_client(tmp_path: Path) -> tuple[JiraClient, ApiCache]:
    cache = ApiCache(tmp_path / "cache.sqlite3")
    client = JiraClient(
        base_url=BASE_URL,
        email="user@example.com",
        api_token="secret-token",
        cache=cache,
    )
    return client, cache


def _search_cache_key(jql: str, fields: list[str], max_results: int) -> str:
    import hashlib

    jql_hash = hashlib.sha256(jql.encode()).hexdigest()[:16]
    fields_hash = hashlib.sha256(",".join(sorted(fields)).encode()).hexdigest()[:8]
    return f"jira:search:{jql_hash}:{fields_hash}:{max_results}"


async def test_search_success_returns_issues(tmp_path: Path) -> None:
    client, _ = _make_client(tmp_path)
    try:
        with respx.mock(base_url=BASE_URL) as router:
            router.post("/rest/api/3/search/jql").mock(
                return_value=httpx.Response(200, json=_SEARCH_PAYLOAD)
            )
            issues = await client.search("project = DEV", ["summary", "status", "assignee"])

        assert issues == [
            Issue(
                key="DEV-1",
                summary="Fix bug",
                status="In Progress",
                status_category="In Progress",
                assignee_email="alice@example.com",
            ),
            Issue(
                key="DEV-2",
                summary="New feature",
                status="To Do",
                status_category="To Do",
                assignee_email=None,
            ),
        ]
    finally:
        await client.aclose()


async def test_search_caches_successful_response(tmp_path: Path) -> None:
    client, cache = _make_client(tmp_path)
    try:
        with respx.mock(base_url=BASE_URL) as router:
            router.post("/rest/api/3/search/jql").mock(
                return_value=httpx.Response(200, json=_SEARCH_PAYLOAD)
            )
            await client.search("project = DEV", ["summary"])

        entry = cache.get(_search_cache_key("project = DEV", ["summary"], 50))
        assert entry is not None
        payload, _ = entry
        assert json.loads(payload) == _SEARCH_PAYLOAD
    finally:
        await client.aclose()


async def test_search_500_falls_back_to_cache(tmp_path: Path) -> None:
    client, cache = _make_client(tmp_path)
    cache.put(
        _search_cache_key("project = DEV", ["summary"], 50),
        json.dumps(_SEARCH_PAYLOAD).encode(),
    )
    try:
        with respx.mock(base_url=BASE_URL) as router:
            router.post("/rest/api/3/search/jql").mock(return_value=httpx.Response(500))
            issues = await client.search("project = DEV", ["summary"])

        assert issues == [
            Issue(
                key="DEV-1",
                summary="Fix bug",
                status="In Progress",
                status_category="In Progress",
                assignee_email="alice@example.com",
            ),
            Issue(
                key="DEV-2",
                summary="New feature",
                status="To Do",
                status_category="To Do",
                assignee_email=None,
            ),
        ]
    finally:
        await client.aclose()


async def test_search_500_no_cache_raises_transient(tmp_path: Path) -> None:
    client, _ = _make_client(tmp_path)
    try:
        with respx.mock(base_url=BASE_URL) as router:
            router.post("/rest/api/3/search/jql").mock(return_value=httpx.Response(500))
            with pytest.raises(JiraTransientError):
                await client.search("project = DEV", ["summary"])
    finally:
        await client.aclose()


async def test_search_401_raises_auth_error(tmp_path: Path) -> None:
    client, cache = _make_client(tmp_path)
    cache.put(
        _search_cache_key("project = DEV", ["summary"], 50),
        json.dumps(_SEARCH_PAYLOAD).encode(),
    )
    try:
        with respx.mock(base_url=BASE_URL) as router:
            router.post("/rest/api/3/search/jql").mock(return_value=httpx.Response(401))
            with pytest.raises(JiraAuthError):
                await client.search("project = DEV", ["summary"])
    finally:
        await client.aclose()


async def test_get_sprint_active(tmp_path: Path) -> None:
    client, _ = _make_client(tmp_path)
    payload = {
        "values": [
            {
                "id": 42,
                "name": "Sprint 7",
                "state": "active",
                "startDate": "2026-05-12T08:00:00.000Z",
                "endDate": "2026-05-26T08:00:00.000Z",
            }
        ]
    }
    try:
        with respx.mock(base_url=BASE_URL) as router:
            router.get("/rest/agile/1.0/board/3/sprint").mock(
                return_value=httpx.Response(200, json=payload)
            )
            sprint = await client.get_sprint(3)

        assert sprint == SprintInfo(
            id=42,
            name="Sprint 7",
            state="active",
            start_iso="2026-05-12T08:00:00.000Z",
            end_iso="2026-05-26T08:00:00.000Z",
        )
    finally:
        await client.aclose()


async def test_get_sprint_returns_none_when_empty(tmp_path: Path) -> None:
    client, _ = _make_client(tmp_path)
    try:
        with respx.mock(base_url=BASE_URL) as router:
            router.get("/rest/agile/1.0/board/3/sprint").mock(
                return_value=httpx.Response(200, json={"values": []})
            )
            sprint = await client.get_sprint(3)

        assert sprint is None
    finally:
        await client.aclose()


async def test_add_worklog_posts_correct_body(tmp_path: Path) -> None:
    client, _ = _make_client(tmp_path)
    try:
        with respx.mock(base_url=BASE_URL) as router:
            route = router.post("/rest/api/3/issue/DEV-1/worklog").mock(
                return_value=httpx.Response(201, json={})
            )
            ok = await client.add_worklog("DEV-1", 1500)

        assert ok is True
        assert route.called
        request = route.calls.last.request
        body = json.loads(request.content)
        assert body["timeSpentSeconds"] == 1500
        assert isinstance(body["started"], str)
        assert body["started"].endswith("+0000")
        # Shape: YYYY-MM-DDTHH:MM:SS.000+0000
        assert len(body["started"]) == len("2026-05-19T10:30:00.000+0000")
        assert ".000+0000" in body["started"]
    finally:
        await client.aclose()


async def test_add_worklog_with_explicit_started(tmp_path: Path) -> None:
    client, _ = _make_client(tmp_path)
    started = datetime(2026, 5, 19, 10, 30, tzinfo=UTC)
    try:
        with respx.mock(base_url=BASE_URL) as router:
            route = router.post("/rest/api/3/issue/DEV-1/worklog").mock(
                return_value=httpx.Response(201, json={})
            )
            ok = await client.add_worklog("DEV-1", 600, started=started)

        assert ok is True
        body = json.loads(route.calls.last.request.content)
        assert body["started"] == "2026-05-19T10:30:00.000+0000"
        assert body["timeSpentSeconds"] == 600
    finally:
        await client.aclose()


async def test_add_worklog_401_raises(tmp_path: Path) -> None:
    client, _ = _make_client(tmp_path)
    try:
        with respx.mock(base_url=BASE_URL) as router:
            router.post("/rest/api/3/issue/DEV-1/worklog").mock(return_value=httpx.Response(401))
            with pytest.raises(JiraAuthError):
                await client.add_worklog("DEV-1", 600)
    finally:
        await client.aclose()


async def test_add_worklog_500_returns_false(tmp_path: Path) -> None:
    client, _ = _make_client(tmp_path)
    try:
        with respx.mock(base_url=BASE_URL) as router:
            router.post("/rest/api/3/issue/DEV-1/worklog").mock(return_value=httpx.Response(500))
            ok = await client.add_worklog("DEV-1", 600)

        assert ok is False
    finally:
        await client.aclose()
