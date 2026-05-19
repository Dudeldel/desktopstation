"""Async Bitbucket Cloud REST client with cache fallback.

Wraps the subset of the Bitbucket Cloud REST API 2.0 that the daemon needs:
listing the current user's open pull requests, listing PRs awaiting the user's
review across a fixed set of repos, and fetching the latest pipeline run for
a given repo/branch.

Mirrors the M4.2 Jira client design:

* **Reads cache-through.** Every successful GET response is stored in the M4.1
  `ApiCache` keyed by query shape. On transient errors (network failure, 5xx,
  timeouts) the client falls back to the cached bytes and re-parses them
  through the same helpers, so the UI keeps rendering a last-known-good
  snapshot when Bitbucket is flaky.
* **Auth failures never touch the cache.** 401/403 means the credentials are
  wrong; pretending otherwise would mask a config error indefinitely.

Pagination (`next` cursor on Bitbucket responses) is intentionally not
implemented in M4 — `pagelen=50` is the hard cap. TODO: revisit if we ever
exceed 50 review PRs per repo.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

import httpx
import structlog

from deskstation.store.api_cache import ApiCache

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class Pr:
    id: str
    title: str
    repo: str
    author_username: str
    source_branch: str
    dest_branch: str
    age_hours: float
    approvals: int
    approvals_required: int
    kind: Literal["mine", "review"]


@dataclass(frozen=True)
class PipelineRun:
    repo: str
    branch: str
    state: str
    started_iso: str
    completed_iso: str | None


class BitbucketError(Exception):
    """Base class for Bitbucket client errors."""


class BitbucketTransientError(BitbucketError):
    """Network/5xx/timeout and no cache available."""


class BitbucketAuthError(BitbucketError):
    """401/403 — credentials are wrong; never falls back to cache."""


def _parse_created_age_hours(created_on: str, now: datetime) -> float:
    created = datetime.fromisoformat(created_on)
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    return (now - created).total_seconds() / 3600


def _parse_pr_item(item: dict[str, Any], kind: Literal["mine", "review"], now: datetime) -> Pr:
    participants = item.get("participants") or []
    approvals = sum(1 for p in participants if p.get("approved"))
    return Pr(
        id=str(item["id"]),
        title=item["title"],
        repo=item["destination"]["repository"]["name"],
        author_username=item["author"]["nickname"],
        source_branch=item["source"]["branch"]["name"],
        dest_branch=item["destination"]["branch"]["name"],
        age_hours=_parse_created_age_hours(item["created_on"], now),
        approvals=approvals,
        approvals_required=0,
        kind=kind,
    )


def _parse_prs(body: bytes, kind: Literal["mine", "review"]) -> list[Pr]:
    payload = json.loads(body)
    now = datetime.now(UTC)
    return [_parse_pr_item(item, kind, now) for item in payload.get("values", [])]


def _parse_first_pipeline(body: bytes, repo: str, branch: str) -> PipelineRun | None:
    payload = json.loads(body)
    values = payload.get("values") or []
    if not values:
        return None
    item = values[0]
    return PipelineRun(
        repo=repo,
        branch=branch,
        state=item["state"]["name"],
        started_iso=item["created_on"],
        completed_iso=item.get("completed_on"),
    )


class BitbucketClient:
    """Async Bitbucket REST client. Use one per daemon process; call `aclose()` on shutdown."""

    def __init__(
        self,
        workspace: str,
        email: str,
        api_token: str,
        cache: ApiCache,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = "https://api.bitbucket.org"
        self._workspace = workspace
        self._auth = httpx.BasicAuth(email, api_token)
        self._cache = cache
        if http_client is not None:
            self._http = http_client
            self._owns_http = False
        else:
            self._http = httpx.AsyncClient(timeout=httpx.Timeout(10.0))
            self._owns_http = True

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def list_my_open_prs(self, username: str) -> list[Pr]:
        url = f"{self._base_url}/2.0/pullrequests/{username}"
        params: dict[str, Any] = {"state": "OPEN", "pagelen": 50}
        cache_key = f"bitbucket:my_prs:{username}"

        try:
            response = await self._http.get(url, params=params, auth=self._auth)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status in (httpx.codes.UNAUTHORIZED, httpx.codes.FORBIDDEN):
                log.warning("bitbucket_request_failed", endpoint="list_my_open_prs", status=status)
                raise BitbucketAuthError(f"Bitbucket auth failed: {status}") from exc
            if status >= 500:
                return self._my_prs_cache_fallback(cache_key, exc)
            log.warning("bitbucket_request_failed", endpoint="list_my_open_prs", status=status)
            raise BitbucketTransientError(f"Bitbucket list_my_open_prs failed: {status}") from exc
        except httpx.HTTPError as exc:
            return self._my_prs_cache_fallback(cache_key, exc)

        self._cache.put(cache_key, response.content)
        log.debug("bitbucket_request", endpoint="list_my_open_prs", status=response.status_code)
        return _parse_prs(response.content, kind="mine")

    def _my_prs_cache_fallback(self, cache_key: str, exc: Exception) -> list[Pr]:
        entry = self._cache.get(cache_key)
        if entry is None:
            log.warning("bitbucket_request_failed", endpoint="list_my_open_prs", error=str(exc))
            raise BitbucketTransientError(
                "Bitbucket list_my_open_prs failed and no cache available"
            ) from exc
        payload, fetched_at = entry
        log.info(
            "bitbucket_request_cache_hit",
            endpoint="list_my_open_prs",
            fetched_at=fetched_at.isoformat(),
        )
        return _parse_prs(payload, kind="mine")

    async def list_review_prs(self, username: str, repos: list[str]) -> list[Pr]:
        results: list[Pr] = []
        for repo in repos:
            url = f"{self._base_url}/2.0/repositories/{self._workspace}/{repo}/pullrequests"
            q_value = f'reviewers.username="{username}" AND state="OPEN"'
            params: dict[str, Any] = {"q": q_value, "pagelen": 50}
            cache_key = f"bitbucket:review_prs:{username}:{repo}"

            try:
                response = await self._http.get(url, params=params, auth=self._auth)
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if status in (httpx.codes.UNAUTHORIZED, httpx.codes.FORBIDDEN):
                    log.warning(
                        "bitbucket_request_failed",
                        endpoint="list_review_prs",
                        repo=repo,
                        status=status,
                    )
                    raise BitbucketAuthError(f"Bitbucket auth failed: {status}") from exc
                if status >= 500:
                    cached = self._review_prs_cache_lookup(cache_key, repo, exc)
                    if cached is not None:
                        results.extend(cached)
                    continue
                log.warning(
                    "bitbucket_request_failed",
                    endpoint="list_review_prs",
                    repo=repo,
                    status=status,
                )
                continue
            except httpx.HTTPError as exc:
                cached = self._review_prs_cache_lookup(cache_key, repo, exc)
                if cached is not None:
                    results.extend(cached)
                continue

            self._cache.put(cache_key, response.content)
            log.debug(
                "bitbucket_request",
                endpoint="list_review_prs",
                repo=repo,
                status=response.status_code,
            )
            results.extend(_parse_prs(response.content, kind="review"))

        return results

    def _review_prs_cache_lookup(
        self, cache_key: str, repo: str, exc: Exception
    ) -> list[Pr] | None:
        entry = self._cache.get(cache_key)
        if entry is None:
            log.warning(
                "bitbucket_request_failed_skipping_repo",
                endpoint="list_review_prs",
                repo=repo,
                error=str(exc),
            )
            return None
        payload, fetched_at = entry
        log.info(
            "bitbucket_request_cache_hit",
            endpoint="list_review_prs",
            repo=repo,
            fetched_at=fetched_at.isoformat(),
        )
        return _parse_prs(payload, kind="review")

    async def latest_pipeline(self, repo: str, branch: str = "main") -> PipelineRun | None:
        url = f"{self._base_url}/2.0/repositories/{self._workspace}/{repo}/pipelines/"
        params: dict[str, Any] = {
            "sort": "-created_on",
            "pagelen": 1,
            "target.branch": branch,
        }
        cache_key = f"bitbucket:pipeline:{repo}:{branch}"

        try:
            response = await self._http.get(url, params=params, auth=self._auth)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status in (httpx.codes.UNAUTHORIZED, httpx.codes.FORBIDDEN):
                log.warning("bitbucket_request_failed", endpoint="latest_pipeline", status=status)
                raise BitbucketAuthError(f"Bitbucket auth failed: {status}") from exc
            if status >= 500:
                return self._pipeline_cache_fallback(cache_key, repo, branch, exc)
            log.warning("bitbucket_request_failed", endpoint="latest_pipeline", status=status)
            raise BitbucketTransientError(f"Bitbucket latest_pipeline failed: {status}") from exc
        except httpx.HTTPError as exc:
            return self._pipeline_cache_fallback(cache_key, repo, branch, exc)

        self._cache.put(cache_key, response.content)
        log.debug("bitbucket_request", endpoint="latest_pipeline", status=response.status_code)
        return _parse_first_pipeline(response.content, repo, branch)

    def _pipeline_cache_fallback(
        self, cache_key: str, repo: str, branch: str, exc: Exception
    ) -> PipelineRun | None:
        entry = self._cache.get(cache_key)
        if entry is None:
            log.warning("bitbucket_request_failed", endpoint="latest_pipeline", error=str(exc))
            raise BitbucketTransientError(
                "Bitbucket latest_pipeline failed and no cache available"
            ) from exc
        payload, fetched_at = entry
        log.info(
            "bitbucket_request_cache_hit",
            endpoint="latest_pipeline",
            fetched_at=fetched_at.isoformat(),
        )
        return _parse_first_pipeline(payload, repo, branch)
