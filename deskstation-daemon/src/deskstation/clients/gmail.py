"""Async Gmail API client with cache fallback.

Wraps the subset of the Gmail v1 REST API the daemon needs: listing the
current user's unread messages from the last day and fetching minimal
metadata (sender, subject, snippet, internalDate) for each.

Mirrors the M4 Jira/Bitbucket client design:

* **Reads cache-through.** The parsed list of message dicts is JSON-encoded
  and stored in the M4.1 `ApiCache` keyed by query hash. On transient errors
  (network failure, 5xx, timeouts) the client falls back to the cached
  bytes and re-hydrates them through the same helpers, so the UI keeps
  rendering a last-known-good snapshot when Gmail is flaky.
* **Auth failures never touch the cache.** 401/403 means the credentials
  are wrong/expired; pretending otherwise would mask a config error
  indefinitely.

The underlying ``googleapiclient.discovery.build`` call is synchronous and
slow (one-time discovery doc fetch), so we build the service once in
``__init__`` and reuse it. Each Gmail API call is sync — we wrap individual
``.execute()`` calls in ``asyncio.to_thread`` so the event loop is never
blocked.

Pagination (Gmail's ``nextPageToken``) is intentionally not implemented in
M5 — the first page (up to 100 messages by default) is sufficient for the
notification list. TODO: revisit if we ever need to scroll past day-old
unread.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import structlog
from googleapiclient.discovery import build as _gapi_build  # type: ignore[import-untyped]
from googleapiclient.errors import HttpError  # type: ignore[import-untyped]

from deskstation.store.api_cache import ApiCache

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class GmailMessage:
    id: str
    sender: str
    subject: str
    snippet: str
    received_at: datetime


class GmailError(Exception):
    """Base class for Gmail client errors."""


class GmailTransientError(GmailError):
    """Network/5xx/timeout and no cache available."""


class GmailAuthError(GmailError):
    """401/403 — credentials are wrong; never falls back to cache."""


def _extract_sender(from_header: str) -> str:
    """Parse an RFC 5322 ``From`` header into a display name.

    - ``"John Smith <john@example.com>"`` -> ``"John Smith"``
    - ``"john@example.com"`` -> ``"john@example.com"``
    - empty / whitespace -> ``"Unknown"``
    """
    raw = (from_header or "").strip()
    if not raw:
        return "Unknown"
    if "<" in raw:
        display = raw.split("<", 1)[0].strip().strip('"').strip()
        if display:
            return display
        # No display part — fall through to address inside <>.
        addr = raw.split("<", 1)[1].rsplit(">", 1)[0].strip()
        return addr or "Unknown"
    return raw


def _parse_internal_date(ms: str) -> datetime:
    """Gmail's ``internalDate`` is a string of epoch milliseconds (UTC)."""
    return datetime.fromtimestamp(int(ms) / 1000.0, tz=UTC)


def _msg_to_dict(msg: GmailMessage) -> dict[str, Any]:
    return {
        "id": msg.id,
        "sender": msg.sender,
        "subject": msg.subject,
        "snippet": msg.snippet,
        "received_at_iso": msg.received_at.isoformat(),
    }


def _dict_to_msg(d: dict[str, Any]) -> GmailMessage:
    received = datetime.fromisoformat(d["received_at_iso"])
    if received.tzinfo is None:
        received = received.replace(tzinfo=UTC)
    return GmailMessage(
        id=d["id"],
        sender=d["sender"],
        subject=d["subject"],
        snippet=d["snippet"],
        received_at=received,
    )


def _default_service_factory(credentials: Any) -> Any:
    # cache_discovery=False suppresses an oauth2client cache warning and skips
    # a slow on-disk discovery doc cache we don't need.
    return _gapi_build("gmail", "v1", credentials=credentials, cache_discovery=False)


class GmailClient:
    """Async Gmail API client. One per daemon process; no aclose() needed —
    the underlying googleapiclient service is GC'd at process exit."""

    def __init__(
        self,
        credentials: Any,
        cache: ApiCache,
        service_factory: Callable[[Any], Any] | None = None,
    ) -> None:
        factory = service_factory if service_factory is not None else _default_service_factory
        # Build once: googleapiclient.discovery.build does a discovery doc
        # fetch on first call which is slow.
        self._service = factory(credentials)
        self._cache = cache

    async def list_unread_recent(
        self, query: str = "is:unread newer_than:1d"
    ) -> list[GmailMessage]:
        query_hash = hashlib.sha256(query.encode()).hexdigest()[:16]
        cache_key = f"gmail:unread:{query_hash}"

        try:
            messages = await asyncio.to_thread(self._fetch_messages, query)
        except HttpError as exc:
            status = getattr(getattr(exc, "resp", None), "status", None)
            if status in (401, 403):
                log.warning("gmail_request_failed", endpoint="list_unread_recent", status=status)
                raise GmailAuthError(f"Gmail auth failed: {status}") from exc
            log.warning("gmail_request_failed", endpoint="list_unread_recent", status=status)
            return self._cache_fallback(cache_key, exc)
        except Exception as exc:
            # Network / timeout / discovery refresh failure.
            log.warning("gmail_request_failed", endpoint="list_unread_recent", error=str(exc))
            return self._cache_fallback(cache_key, exc)

        payload = json.dumps([_msg_to_dict(m) for m in messages]).encode()
        self._cache.put(cache_key, payload)
        log.debug("gmail_request", endpoint="list_unread_recent", count=len(messages))
        return messages

    def _fetch_messages(self, query: str) -> list[GmailMessage]:
        """Synchronous list + per-id metadata fetch. Run inside ``to_thread``."""
        # TODO(M6): pagination (nextPageToken). First page = 100 messages is
        # plenty for the M5 notification list.
        list_resp = self._service.users().messages().list(userId="me", q=query).execute()
        items = list_resp.get("messages", []) or []
        out: list[GmailMessage] = []
        for item in items:
            msg_id = item["id"]
            detail = (
                self._service.users()
                .messages()
                .get(
                    userId="me",
                    id=msg_id,
                    format="metadata",
                    metadataHeaders=["From", "Subject"],
                )
                .execute()
            )
            headers = {h["name"]: h["value"] for h in detail.get("payload", {}).get("headers", [])}
            from_header = headers.get("From", "")
            subject = headers.get("Subject", "")
            snippet = detail.get("snippet", "")
            internal = detail.get("internalDate", "0")
            out.append(
                GmailMessage(
                    id=msg_id,
                    sender=_extract_sender(from_header),
                    subject=subject,
                    snippet=snippet,
                    received_at=_parse_internal_date(internal),
                )
            )
        return out

    def _cache_fallback(self, cache_key: str, exc: Exception) -> list[GmailMessage]:
        entry = self._cache.get(cache_key)
        if entry is None:
            log.warning("gmail_request_failed_no_cache", error=str(exc))
            raise GmailTransientError(
                "Gmail list_unread_recent failed and no cache available"
            ) from exc
        payload, fetched_at = entry
        log.info("gmail_request_cache_hit", fetched_at=fetched_at.isoformat())
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as decode_exc:
            raise GmailTransientError("Gmail cache corrupted") from decode_exc
        return [_dict_to_msg(d) for d in data]
