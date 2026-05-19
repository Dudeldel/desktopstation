"""Async Google Calendar API client with cache fallback.

Wraps the subset of the Calendar v3 REST API the daemon needs: listing
upcoming Meet-enabled events within a sliding window starting at "now".

Mirrors :mod:`deskstation.clients.gmail` and :mod:`deskstation.clients.gchat`:

* **Reads cache-through.** Parsed results are JSON-encoded and stored in
  the M4.1 :class:`ApiCache`. On transient errors (network failure, 5xx,
  timeouts) the client falls back to the cached bytes so the UI keeps
  rendering a last-known-good meeting bar when Calendar is flaky.
* **Auth failures never touch the cache.** 401/403 means the credentials
  are wrong/expired; pretending otherwise would mask a config error
  indefinitely.

Shared-base extraction decision (3rd Google client):
``gmail.py`` / ``gchat.py`` / ``gcal.py`` all share roughly:
service factory, HttpError → status → 401/403 → AuthError split,
cache_fallback envelope. Concretely, each client has its own dataclasses,
its own per-endpoint cache keys, its own parse helpers, and its own
``_fetch_*`` shape (single call here, paginated in chat, list+get in
gmail). The fallback skeleton is ~10 lines per endpoint, and the
per-endpoint divergence already lives in ``_fetch_*`` and the
serialisation pair. Pulling out a 10-line helper would not delete real
duplication — and the bodies that vary (HttpError mapping, log keys,
error type) would still need per-client overrides. Leaving the three as
parallel implementations for now; revisit if a 4th Google client lands
that can't share the same skeleton.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from googleapiclient.discovery import build as _gapi_build  # type: ignore[import-untyped]
from googleapiclient.errors import HttpError  # type: ignore[import-untyped]

from deskstation.store.api_cache import ApiCache

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class Meeting:
    id: str  # Calendar event id
    title: str  # summary
    start: datetime  # UTC
    end: datetime  # UTC
    join_url: str  # hangoutLink


class GoogleCalendarError(Exception):
    """Base class for Google Calendar client errors."""


class GoogleCalendarTransientError(GoogleCalendarError):
    """Network/5xx/timeout and no cache available."""


class GoogleCalendarAuthError(GoogleCalendarError):
    """401/403 — credentials are wrong; never falls back to cache."""


# ---------------------------------------------------------------------------
# Parse / cache (de)serialisation helpers
# ---------------------------------------------------------------------------


def _parse_rfc3339(value: str) -> datetime:
    """Parse a Calendar RFC3339 ``dateTime`` string into a UTC datetime.

    Calendar typically returns strings like ``"2026-05-19T12:34:56+02:00"``
    or ``"2026-05-19T10:34:56Z"``. Normalise ``Z`` → ``+00:00`` so
    :func:`datetime.fromisoformat` accepts it on Python 3.11+, then
    convert to UTC for storage/comparison.
    """
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _parse_meeting(item: dict[str, Any]) -> Meeting | None:
    """Extract a :class:`Meeting` from a Calendar ``events.list`` element.

    Returns ``None`` when the event isn't a Meet-enabled timed event:
    - Missing ``hangoutLink`` → skip (no Meet URL → nothing to join).
    - All-day events (``start.date`` instead of ``start.dateTime``) →
      skip. The meeting bar shows clock-times; an all-day calendar block
      is not what the user means by "next meeting".
    """
    join_url = item.get("hangoutLink")
    if not join_url:
        return None
    start = item.get("start") or {}
    end = item.get("end") or {}
    start_dt_raw = start.get("dateTime")
    end_dt_raw = end.get("dateTime")
    if not start_dt_raw or not end_dt_raw:
        # All-day or malformed — skip.
        return None
    return Meeting(
        id=item["id"],
        title=(item.get("summary") or "").strip() or "(no title)",
        start=_parse_rfc3339(start_dt_raw),
        end=_parse_rfc3339(end_dt_raw),
        join_url=join_url,
    )


def _meeting_to_dict(m: Meeting) -> dict[str, Any]:
    return {
        "id": m.id,
        "title": m.title,
        "start_iso": m.start.isoformat(),
        "end_iso": m.end.isoformat(),
        "join_url": m.join_url,
    }


def _dict_to_meeting(d: dict[str, Any]) -> Meeting:
    start = datetime.fromisoformat(d["start_iso"])
    if start.tzinfo is None:
        start = start.replace(tzinfo=UTC)
    end = datetime.fromisoformat(d["end_iso"])
    if end.tzinfo is None:
        end = end.replace(tzinfo=UTC)
    return Meeting(
        id=d["id"],
        title=d["title"],
        start=start,
        end=end,
        join_url=d["join_url"],
    )


def _default_service_factory(credentials: Any) -> Any:
    # cache_discovery=False mirrors GmailClient / GoogleChatClient — skips
    # the on-disk discovery doc cache we don't need and suppresses the
    # oauth2client cache warning.
    return _gapi_build("calendar", "v3", credentials=credentials, cache_discovery=False)


class GoogleCalendarClient:
    """Async Google Calendar API client.

    One per daemon process; the underlying googleapiclient service is GC'd
    at process exit. ``aclose()`` is a no-op kept for symmetry with the
    httpx-based clients.
    """

    def __init__(
        self,
        credentials: Any,
        cache: ApiCache,
        service_factory: Callable[[Any], Any] | None = None,
    ) -> None:
        factory = service_factory if service_factory is not None else _default_service_factory
        self._service = factory(credentials)
        self._cache = cache

    async def list_upcoming(self, window_hours: int = 36) -> list[Meeting]:
        """List Meet-enabled events starting within ``window_hours`` of now.

        ``singleEvents=True`` expands recurring events into single instances
        so the poller doesn't need any special recurrence handling.
        """
        cache_key = f"gcal:upcoming:{window_hours}"
        try:
            meetings = await asyncio.to_thread(self._fetch_upcoming, window_hours)
        except HttpError as exc:
            status = getattr(getattr(exc, "resp", None), "status", None)
            if status in (401, 403):
                log.warning("gcal_request_failed", endpoint="list_upcoming", status=status)
                raise GoogleCalendarAuthError(f"Google Calendar auth failed: {status}") from exc
            log.warning("gcal_request_failed", endpoint="list_upcoming", status=status)
            return self._cache_fallback(cache_key, exc)
        except Exception as exc:
            log.warning("gcal_request_failed", endpoint="list_upcoming", error=str(exc))
            return self._cache_fallback(cache_key, exc)

        payload = json.dumps([_meeting_to_dict(m) for m in meetings]).encode()
        self._cache.put(cache_key, payload)
        log.debug("gcal_request", endpoint="list_upcoming", count=len(meetings))
        return meetings

    async def aclose(self) -> None:
        """No-op; kept for symmetry with httpx-based clients."""
        return None

    # ------------------------------------------------------------------
    # sync workers (run inside asyncio.to_thread)
    # ------------------------------------------------------------------

    def _fetch_upcoming(self, window_hours: int) -> list[Meeting]:
        now = datetime.now(UTC)
        time_max = now + timedelta(hours=window_hours)
        resp = (
            self._service.events()
            .list(
                calendarId="primary",
                timeMin=now.isoformat(),
                timeMax=time_max.isoformat(),
                singleEvents=True,
                orderBy="startTime",
                maxResults=20,
            )
            .execute()
        )
        out: list[Meeting] = []
        for item in resp.get("items", []) or []:
            try:
                meeting = _parse_meeting(item)
            except (KeyError, TypeError, ValueError) as exc:
                # Per-entry failure isolation: one malformed event must not
                # poison the whole list (consistent with gchat M5.3 review
                # feedback).
                log.warning(
                    "gcal_skip_malformed_event",
                    error=str(exc),
                    id=item.get("id") if isinstance(item, dict) else None,
                )
                continue
            if meeting is not None:
                out.append(meeting)
        return out

    # ------------------------------------------------------------------
    # cache fallback
    # ------------------------------------------------------------------

    def _cache_fallback(self, cache_key: str, exc: Exception) -> list[Meeting]:
        entry = self._cache.get(cache_key)
        if entry is None:
            log.warning("gcal_request_failed_no_cache", error=str(exc))
            raise GoogleCalendarTransientError(
                "Google Calendar list_upcoming failed and no cache available"
            ) from exc
        payload, fetched_at = entry
        log.info("gcal_request_cache_hit", fetched_at=fetched_at.isoformat())
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as decode_exc:
            raise GoogleCalendarTransientError("Google Calendar cache corrupted") from decode_exc
        return [_dict_to_meeting(d) for d in data]
