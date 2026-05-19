"""Async Jira Cloud REST client with cache fallback.

Wraps the subset of the Jira Cloud REST API v3 (plus Agile v1.0 for sprints)
that the daemon needs: JQL search, active sprint lookup, and worklog posting.

Two design rules from the M4 plan:

* **Reads cache-through.** Every successful GET-style response is stored in the
  M4.1 `ApiCache` keyed by query shape. On transient errors (network failure,
  5xx, timeouts) the client falls back to the cached bytes and re-parses them,
  so the UI keeps rendering a last-known-good snapshot when Jira is flaky.
* **Auth failures never touch the cache.** 401/403 means the credentials are
  wrong; pretending otherwise would mask a config error indefinitely.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
import structlog

from deskstation.store.api_cache import ApiCache

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class Issue:
    key: str
    summary: str
    status: str
    status_category: str
    assignee_email: str | None


@dataclass(frozen=True)
class SprintInfo:
    id: int
    name: str
    state: str
    start_iso: str | None
    end_iso: str | None


class JiraError(Exception):
    """Base class for Jira client errors."""


class JiraTransientError(JiraError):
    """Network/5xx/timeout and no cache available."""


class JiraAuthError(JiraError):
    """401/403 — credentials are wrong; never falls back to cache."""


def _parse_issues(body: bytes) -> list[Issue]:
    payload = json.loads(body)
    issues: list[Issue] = []
    for item in payload.get("issues", []):
        fields = item["fields"]
        assignee = fields.get("assignee") or {}
        issues.append(
            Issue(
                key=item["key"],
                summary=fields["summary"],
                status=fields["status"]["name"],
                status_category=fields["status"]["statusCategory"]["name"],
                assignee_email=assignee.get("emailAddress"),
            )
        )
    return issues


def _parse_first_sprint(body: bytes) -> SprintInfo | None:
    payload = json.loads(body)
    values = payload.get("values") or []
    if not values:
        return None
    item = values[0]
    return SprintInfo(
        id=int(item["id"]),
        name=item["name"],
        state=item["state"],
        start_iso=item.get("startDate"),
        end_iso=item.get("endDate"),
    )


def _format_started(started: datetime | None) -> str:
    moment = started if started is not None else datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.000%z")


class JiraClient:
    """Async Jira REST client. Use one per daemon process; call `aclose()` on shutdown."""

    def __init__(
        self,
        base_url: str,
        email: str,
        api_token: str,
        cache: ApiCache,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._auth = httpx.BasicAuth(email, api_token)
        self._cache = cache
        if http_client is not None:
            self._http = http_client
            self._owns_http = False
        else:
            self._http = httpx.AsyncClient(
                auth=self._auth,
                timeout=httpx.Timeout(10.0),
            )
            self._owns_http = True

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def search(
        self,
        jql: str,
        fields: list[str],
        max_results: int = 50,
    ) -> list[Issue]:
        url = f"{self._base_url}/rest/api/3/search/jql"
        body: dict[str, Any] = {"jql": jql, "fields": fields, "maxResults": max_results}
        jql_hash = hashlib.sha256(jql.encode()).hexdigest()[:16]
        cache_key = f"jira:search:{jql_hash}:{max_results}"

        try:
            response = await self._http.post(url, json=body, auth=self._auth)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status in (httpx.codes.UNAUTHORIZED, httpx.codes.FORBIDDEN):
                log.warning("jira_request_failed", endpoint="search", status=status)
                raise JiraAuthError(f"Jira auth failed: {status}") from exc
            if status >= 500:
                return self._search_cache_fallback(cache_key, exc)
            log.warning("jira_request_failed", endpoint="search", status=status)
            raise JiraTransientError(f"Jira search failed: {status}") from exc
        except httpx.HTTPError as exc:
            return self._search_cache_fallback(cache_key, exc)

        self._cache.put(cache_key, response.content)
        log.debug("jira_request", endpoint="search", status=response.status_code)
        return _parse_issues(response.content)

    def _search_cache_fallback(self, cache_key: str, exc: Exception) -> list[Issue]:
        entry = self._cache.get(cache_key)
        if entry is None:
            log.warning("jira_request_failed", endpoint="search", error=str(exc))
            raise JiraTransientError("Jira search failed and no cache available") from exc
        payload, fetched_at = entry
        log.info("jira_request_cache_hit", endpoint="search", fetched_at=fetched_at.isoformat())
        return _parse_issues(payload)

    async def get_sprint(self, board_id: int) -> SprintInfo | None:
        url = f"{self._base_url}/rest/agile/1.0/board/{board_id}/sprint"
        cache_key = f"jira:sprint:{board_id}"

        try:
            response = await self._http.get(url, params={"state": "active"}, auth=self._auth)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status in (httpx.codes.UNAUTHORIZED, httpx.codes.FORBIDDEN):
                log.warning("jira_request_failed", endpoint="get_sprint", status=status)
                raise JiraAuthError(f"Jira auth failed: {status}") from exc
            if status >= 500:
                return self._sprint_cache_fallback(cache_key, exc)
            log.warning("jira_request_failed", endpoint="get_sprint", status=status)
            raise JiraTransientError(f"Jira get_sprint failed: {status}") from exc
        except httpx.HTTPError as exc:
            return self._sprint_cache_fallback(cache_key, exc)

        self._cache.put(cache_key, response.content)
        log.debug("jira_request", endpoint="get_sprint", status=response.status_code)
        return _parse_first_sprint(response.content)

    def _sprint_cache_fallback(self, cache_key: str, exc: Exception) -> SprintInfo | None:
        entry = self._cache.get(cache_key)
        if entry is None:
            log.warning("jira_request_failed", endpoint="get_sprint", error=str(exc))
            raise JiraTransientError("Jira get_sprint failed and no cache available") from exc
        payload, fetched_at = entry
        log.info(
            "jira_request_cache_hit",
            endpoint="get_sprint",
            fetched_at=fetched_at.isoformat(),
        )
        return _parse_first_sprint(payload)

    async def add_worklog(
        self,
        issue_key: str,
        seconds: int,
        started: datetime | None = None,
    ) -> bool:
        url = f"{self._base_url}/rest/api/3/issue/{issue_key}/worklog"
        body: dict[str, Any] = {
            "timeSpentSeconds": seconds,
            "started": _format_started(started),
        }

        try:
            response = await self._http.post(url, json=body, auth=self._auth)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status in (httpx.codes.UNAUTHORIZED, httpx.codes.FORBIDDEN):
                log.warning("jira_request_failed", endpoint="add_worklog", status=status)
                raise JiraAuthError(f"Jira auth failed: {status}") from exc
            log.warning("jira_request_failed", endpoint="add_worklog", status=status)
            return False
        except httpx.HTTPError as exc:
            log.warning("jira_request_failed", endpoint="add_worklog", error=str(exc))
            return False

        log.debug("jira_request", endpoint="add_worklog", status=response.status_code)
        return response.status_code in (200, 201)
