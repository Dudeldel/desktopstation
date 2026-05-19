"""Tests for the Bitbucket REST client."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from deskstation.clients.bitbucket import (
    BitbucketAuthError,
    BitbucketClient,
    BitbucketTransientError,
    PipelineRun,
)
from deskstation.store.api_cache import ApiCache

BASE_URL = "https://api.bitbucket.org"
WORKSPACE = "acme"
USERNAME = "alice"
EMAIL = "alice@example.com"
TOKEN = "secret-token"


def _make_pr_payload(
    *,
    pr_id: int = 1,
    title: str = "Fix bug",
    repo: str = "backend",
    author: str = "alice",
    source: str = "feature/x",
    dest: str = "main",
    created_on: str = "2026-05-19T10:00:00+00:00",
    participants: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "id": pr_id,
        "title": title,
        "destination": {
            "repository": {"name": repo},
            "branch": {"name": dest},
        },
        "source": {"branch": {"name": source}},
        "author": {"nickname": author},
        "created_on": created_on,
        "participants": participants if participants is not None else [],
    }


def _make_client(tmp_path: Path) -> tuple[BitbucketClient, ApiCache]:
    cache = ApiCache(tmp_path / "cache.sqlite3")
    client = BitbucketClient(
        workspace=WORKSPACE,
        email=EMAIL,
        api_token=TOKEN,
        cache=cache,
    )
    return client, cache


async def test_list_my_open_prs_success(tmp_path: Path) -> None:
    client, _ = _make_client(tmp_path)
    payload = {
        "values": [
            _make_pr_payload(
                pr_id=42,
                title="Refactor auth",
                repo="backend",
                source="feature/auth",
                dest="main",
            ),
            _make_pr_payload(
                pr_id=43,
                title="Add metrics",
                repo="frontend",
                source="feature/metrics",
                dest="develop",
            ),
        ]
    }
    try:
        with respx.mock(base_url=BASE_URL) as router:
            router.get(f"/2.0/pullrequests/{USERNAME}").mock(
                return_value=httpx.Response(200, json=payload)
            )
            prs = await client.list_my_open_prs(USERNAME)

        assert len(prs) == 2
        assert prs[0].id == "42"
        assert prs[0].title == "Refactor auth"
        assert prs[0].repo == "backend"
        assert prs[0].source_branch == "feature/auth"
        assert prs[0].dest_branch == "main"
        assert prs[0].kind == "mine"
        assert prs[0].approvals_required == 0
        assert prs[1].id == "43"
        assert prs[1].title == "Add metrics"
        assert prs[1].repo == "frontend"
        assert prs[1].source_branch == "feature/metrics"
        assert prs[1].dest_branch == "develop"
        assert prs[1].kind == "mine"
    finally:
        await client.aclose()


async def test_list_my_open_prs_age_hours(tmp_path: Path) -> None:
    client, _ = _make_client(tmp_path)
    created = (datetime.now(UTC) - timedelta(hours=5)).isoformat()
    payload = {"values": [_make_pr_payload(created_on=created)]}
    try:
        with respx.mock(base_url=BASE_URL) as router:
            router.get(f"/2.0/pullrequests/{USERNAME}").mock(
                return_value=httpx.Response(200, json=payload)
            )
            prs = await client.list_my_open_prs(USERNAME)

        assert len(prs) == 1
        # Within tolerance — call may take a few ms.
        assert prs[0].age_hours == pytest.approx(5.0, abs=0.05)
    finally:
        await client.aclose()


async def test_list_my_open_prs_approvals_counted(tmp_path: Path) -> None:
    client, _ = _make_client(tmp_path)
    payload = {
        "values": [
            _make_pr_payload(
                participants=[
                    {"user": {"nickname": "bob"}, "approved": True},
                    {"user": {"nickname": "carol"}, "approved": False},
                ]
            )
        ]
    }
    try:
        with respx.mock(base_url=BASE_URL) as router:
            router.get(f"/2.0/pullrequests/{USERNAME}").mock(
                return_value=httpx.Response(200, json=payload)
            )
            prs = await client.list_my_open_prs(USERNAME)

        assert len(prs) == 1
        assert prs[0].approvals == 1
    finally:
        await client.aclose()


async def test_list_my_open_prs_caches_response(tmp_path: Path) -> None:
    client, cache = _make_client(tmp_path)
    payload = {"values": [_make_pr_payload()]}
    try:
        with respx.mock(base_url=BASE_URL) as router:
            router.get(f"/2.0/pullrequests/{USERNAME}").mock(
                return_value=httpx.Response(200, json=payload)
            )
            await client.list_my_open_prs(USERNAME)

        entry = cache.get(f"bitbucket:my_prs:{USERNAME}")
        assert entry is not None
        cached_payload, _ = entry
        assert json.loads(cached_payload) == payload
    finally:
        await client.aclose()


async def test_list_my_open_prs_500_falls_back_to_cache(tmp_path: Path) -> None:
    client, cache = _make_client(tmp_path)
    payload = {
        "values": [
            _make_pr_payload(pr_id=42, title="Cached PR", repo="backend"),
            _make_pr_payload(pr_id=43, title="Another", repo="frontend"),
        ]
    }
    cache.put(f"bitbucket:my_prs:{USERNAME}", json.dumps(payload).encode())

    try:
        with respx.mock(base_url=BASE_URL) as router:
            router.get(f"/2.0/pullrequests/{USERNAME}").mock(return_value=httpx.Response(500))
            prs = await client.list_my_open_prs(USERNAME)

        # Equality on the fields that don't depend on `now`.
        assert len(prs) == 2
        assert [p.id for p in prs] == ["42", "43"]
        assert [p.title for p in prs] == ["Cached PR", "Another"]
        assert [p.repo for p in prs] == ["backend", "frontend"]
        assert all(p.kind == "mine" for p in prs)
    finally:
        await client.aclose()


async def test_list_my_open_prs_500_no_cache_raises(tmp_path: Path) -> None:
    client, _ = _make_client(tmp_path)
    try:
        with respx.mock(base_url=BASE_URL) as router:
            router.get(f"/2.0/pullrequests/{USERNAME}").mock(return_value=httpx.Response(500))
            with pytest.raises(BitbucketTransientError):
                await client.list_my_open_prs(USERNAME)
    finally:
        await client.aclose()


async def test_list_my_open_prs_401_raises_auth(tmp_path: Path) -> None:
    client, cache = _make_client(tmp_path)
    payload = {"values": [_make_pr_payload()]}
    cache.put(f"bitbucket:my_prs:{USERNAME}", json.dumps(payload).encode())
    try:
        with respx.mock(base_url=BASE_URL) as router:
            router.get(f"/2.0/pullrequests/{USERNAME}").mock(return_value=httpx.Response(401))
            with pytest.raises(BitbucketAuthError):
                await client.list_my_open_prs(USERNAME)
    finally:
        await client.aclose()


async def test_list_review_prs_aggregates_across_repos(tmp_path: Path) -> None:
    client, _ = _make_client(tmp_path)
    payload_a = {"values": [_make_pr_payload(pr_id=10, title="A", repo="repo-a")]}
    payload_b = {"values": [_make_pr_payload(pr_id=20, title="B", repo="repo-b")]}
    try:
        with respx.mock(base_url=BASE_URL) as router:
            router.get(f"/2.0/repositories/{WORKSPACE}/repo-a/pullrequests").mock(
                return_value=httpx.Response(200, json=payload_a)
            )
            router.get(f"/2.0/repositories/{WORKSPACE}/repo-b/pullrequests").mock(
                return_value=httpx.Response(200, json=payload_b)
            )
            prs = await client.list_review_prs(USERNAME, ["repo-a", "repo-b"])

        assert len(prs) == 2
        assert [p.id for p in prs] == ["10", "20"]
        assert [p.title for p in prs] == ["A", "B"]
        assert [p.repo for p in prs] == ["repo-a", "repo-b"]
        assert all(p.kind == "review" for p in prs)
    finally:
        await client.aclose()


async def test_list_review_prs_partial_failure_skips_repo(tmp_path: Path) -> None:
    client, _ = _make_client(tmp_path)
    payload_a = {"values": [_make_pr_payload(pr_id=10, title="A", repo="repo-a")]}
    try:
        with respx.mock(base_url=BASE_URL) as router:
            router.get(f"/2.0/repositories/{WORKSPACE}/repo-a/pullrequests").mock(
                return_value=httpx.Response(200, json=payload_a)
            )
            router.get(f"/2.0/repositories/{WORKSPACE}/repo-b/pullrequests").mock(
                return_value=httpx.Response(500)
            )
            prs = await client.list_review_prs(USERNAME, ["repo-a", "repo-b"])

        assert len(prs) == 1
        assert prs[0].id == "10"
        assert prs[0].title == "A"
        assert prs[0].repo == "repo-a"
        assert prs[0].kind == "review"
    finally:
        await client.aclose()


async def test_latest_pipeline_success(tmp_path: Path) -> None:
    client, _ = _make_client(tmp_path)
    payload = {
        "values": [
            {
                "state": {"name": "SUCCESSFUL"},
                "created_on": "2026-05-19T09:00:00+00:00",
                "completed_on": "2026-05-19T09:05:00+00:00",
            }
        ]
    }
    try:
        with respx.mock(base_url=BASE_URL) as router:
            router.get(f"/2.0/repositories/{WORKSPACE}/backend/pipelines/").mock(
                return_value=httpx.Response(200, json=payload)
            )
            run = await client.latest_pipeline("backend")

        assert run == PipelineRun(
            repo="backend",
            branch="main",
            state="SUCCESSFUL",
            started_iso="2026-05-19T09:00:00+00:00",
            completed_iso="2026-05-19T09:05:00+00:00",
        )
    finally:
        await client.aclose()


async def test_latest_pipeline_returns_none_when_empty(tmp_path: Path) -> None:
    client, _ = _make_client(tmp_path)
    try:
        with respx.mock(base_url=BASE_URL) as router:
            router.get(f"/2.0/repositories/{WORKSPACE}/backend/pipelines/").mock(
                return_value=httpx.Response(200, json={"values": []})
            )
            run = await client.latest_pipeline("backend")

        assert run is None
    finally:
        await client.aclose()


async def test_latest_pipeline_with_branch_param(tmp_path: Path) -> None:
    client, _ = _make_client(tmp_path)
    payload = {
        "values": [
            {
                "state": {"name": "IN_PROGRESS"},
                "created_on": "2026-05-19T09:00:00+00:00",
            }
        ]
    }
    try:
        with respx.mock(base_url=BASE_URL) as router:
            route = router.get(f"/2.0/repositories/{WORKSPACE}/backend/pipelines/").mock(
                return_value=httpx.Response(200, json=payload)
            )
            run = await client.latest_pipeline("backend", branch="develop")

        assert run is not None
        assert run.branch == "develop"
        assert run.state == "IN_PROGRESS"
        assert run.completed_iso is None
        assert route.called
        request = route.calls.last.request
        assert request.url.params["target.branch"] == "develop"
        assert request.url.params["sort"] == "-created_on"
        assert request.url.params["pagelen"] == "1"
    finally:
        await client.aclose()
