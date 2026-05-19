"""Async Google Chat API client with cache fallback.

Wraps the subset of the Chat v1 REST API the daemon needs: listing DM /
SPACE spaces the user is a member of and fetching recent messages from a
given space since a timestamp.

Mirrors :mod:`deskstation.clients.gmail` (M5.2) exactly:

* **Reads cache-through.** Parsed results are JSON-encoded and stored in
  the M4.1 :class:`ApiCache`. On transient errors (network failure, 5xx,
  timeouts) the client falls back to the cached bytes so the UI keeps
  rendering a last-known-good snapshot when Chat is flaky.
* **Auth failures never touch the cache.** 401/403 means the credentials
  are wrong/expired; pretending otherwise would mask a config error.

Note on shared Google client base: this is the 3rd Google API client
shape we'd be writing (Gmail, Chat, Calendar M5.6). Reviewers have
repeatedly said "wait for the 3rd-4th instance before extracting." The
duplication here is structural enough (error mapping, service factory,
cache fallback pattern) that an extraction is justified, but Calendar
(M5.6) is not yet written and its cache semantics may differ slightly
(date-range queries with different stable-key needs). Decision for M5.3:
mirror the Gmail pattern one more time; revisit during M5.6 once we can
see the third concrete shape and design the base around all three.
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
class Space:
    name: str  # "spaces/AAAA..." resource name (used as id)
    display_name: str
    type: str  # "DIRECT_MESSAGE" or "SPACE"


@dataclass(frozen=True)
class ChatMessage:
    name: str  # "spaces/.../messages/..." resource name (used as id)
    space_name: str
    sender_display_name: str
    text: str
    create_time: datetime  # parsed from RFC3339 string


class GoogleChatError(Exception):
    """Base class for Google Chat client errors."""


class GoogleChatTransientError(GoogleChatError):
    """Network/5xx/timeout and no cache available."""


class GoogleChatAuthError(GoogleChatError):
    """401/403 — credentials are wrong; never falls back to cache."""


# ---------------------------------------------------------------------------
# Module-private parse helpers
# ---------------------------------------------------------------------------


def _parse_rfc3339(value: str) -> datetime:
    """Parse a Chat RFC3339 ``createTime`` string into a UTC datetime.

    Examples: ``"2026-05-19T12:34:56.789Z"`` or
    ``"2026-05-19T12:34:56+00:00"``. We normalise ``Z`` → ``+00:00`` so
    :func:`datetime.fromisoformat` accepts it on Python 3.11+.
    """
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _parse_space(item: dict[str, Any]) -> Space:
    """Extract a :class:`Space` from a Chat ``spaces.list`` element.

    DMs often have an empty ``displayName`` — fall back to a friendly
    placeholder.
    """
    display_name = (item.get("displayName") or "").strip()
    if not display_name:
        display_name = "(direct message)"
    return Space(
        name=item["name"],
        display_name=display_name,
        type=item.get("type", ""),
    )


def _parse_chat_message(item: dict[str, Any], space_name: str) -> ChatMessage:
    """Extract a :class:`ChatMessage` from a Chat ``messages.list`` element.

    Chat allows messages with only attachments — ``text`` may be missing
    entirely. ``formattedText`` may also be present; we prefer the plain
    ``text`` field when both are available (per the task spec).
    """
    sender = item.get("sender") or {}
    sender_display = (sender.get("displayName") or "").strip() or "Unknown"
    text_value = item.get("text")
    if not text_value:
        text_value = item.get("formattedText") or ""
    return ChatMessage(
        name=item["name"],
        space_name=space_name,
        sender_display_name=sender_display,
        text=text_value,
        create_time=_parse_rfc3339(item["createTime"]),
    )


# ---------------------------------------------------------------------------
# Cache (de)serialisation
# ---------------------------------------------------------------------------


def _space_to_dict(s: Space) -> dict[str, Any]:
    return {"name": s.name, "display_name": s.display_name, "type": s.type}


def _dict_to_space(d: dict[str, Any]) -> Space:
    return Space(name=d["name"], display_name=d["display_name"], type=d["type"])


def _msg_to_dict(m: ChatMessage) -> dict[str, Any]:
    return {
        "name": m.name,
        "space_name": m.space_name,
        "sender_display_name": m.sender_display_name,
        "text": m.text,
        "create_time_iso": m.create_time.isoformat(),
    }


def _dict_to_msg(d: dict[str, Any]) -> ChatMessage:
    created = datetime.fromisoformat(d["create_time_iso"])
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    return ChatMessage(
        name=d["name"],
        space_name=d["space_name"],
        sender_display_name=d["sender_display_name"],
        text=d["text"],
        create_time=created,
    )


def _default_service_factory(credentials: Any) -> Any:
    # cache_discovery=False mirrors GmailClient — skips the on-disk
    # discovery doc cache we don't need and suppresses the oauth2client
    # cache warning.
    return _gapi_build("chat", "v1", credentials=credentials, cache_discovery=False)


# Bound on pagination work — single page is enough for typical users, but
# we follow ``nextPageToken`` up to this cap so a large org with many DMs
# doesn't get silently truncated.
_MAX_PAGES = 3


class GoogleChatClient:
    """Async Google Chat API client.

    One per daemon process; the underlying googleapiclient service is GC'd
    at process exit (no ``aclose()`` needed).
    """

    def __init__(
        self,
        credentials: Any,
        cache: ApiCache,
        my_email: str,
        service_factory: Callable[[Any], Any] | None = None,
    ) -> None:
        factory = service_factory if service_factory is not None else _default_service_factory
        # Build once: googleapiclient.discovery.build does a discovery doc
        # fetch on first call which is slow.
        self._service = factory(credentials)
        self._cache = cache
        self._my_email = my_email

    async def list_spaces(self) -> list[Space]:
        cache_key = "gchat:spaces"
        try:
            spaces = await asyncio.to_thread(self._fetch_spaces)
        except HttpError as exc:
            status = getattr(getattr(exc, "resp", None), "status", None)
            if status in (401, 403):
                log.warning("gchat_request_failed", endpoint="list_spaces", status=status)
                raise GoogleChatAuthError(f"Google Chat auth failed: {status}") from exc
            log.warning("gchat_request_failed", endpoint="list_spaces", status=status)
            return self._cache_fallback_spaces(cache_key, exc)
        except Exception as exc:
            log.warning("gchat_request_failed", endpoint="list_spaces", error=str(exc))
            return self._cache_fallback_spaces(cache_key, exc)

        payload = json.dumps([_space_to_dict(s) for s in spaces]).encode()
        self._cache.put(cache_key, payload)
        log.debug("gchat_request", endpoint="list_spaces", count=len(spaces))
        return spaces

    async def list_recent_messages(self, space_name: str, since: datetime) -> list[ChatMessage]:
        space_hash = hashlib.sha256(space_name.encode()).hexdigest()[:16]
        cache_key = f"gchat:messages:{space_hash}"
        try:
            messages = await asyncio.to_thread(self._fetch_messages, space_name, since)
        except HttpError as exc:
            status = getattr(getattr(exc, "resp", None), "status", None)
            if status in (401, 403):
                log.warning(
                    "gchat_request_failed",
                    endpoint="list_recent_messages",
                    status=status,
                )
                raise GoogleChatAuthError(f"Google Chat auth failed: {status}") from exc
            log.warning(
                "gchat_request_failed",
                endpoint="list_recent_messages",
                status=status,
            )
            return self._cache_fallback_messages(cache_key, exc)
        except Exception as exc:
            log.warning(
                "gchat_request_failed",
                endpoint="list_recent_messages",
                error=str(exc),
            )
            return self._cache_fallback_messages(cache_key, exc)

        payload = json.dumps([_msg_to_dict(m) for m in messages]).encode()
        self._cache.put(cache_key, payload)
        log.debug(
            "gchat_request",
            endpoint="list_recent_messages",
            space=space_name,
            count=len(messages),
        )
        return messages

    # ------------------------------------------------------------------
    # sync workers (run inside asyncio.to_thread)
    # ------------------------------------------------------------------

    def _fetch_spaces(self) -> list[Space]:
        """List spaces, page through up to ``_MAX_PAGES``, filter to DM/SPACE."""
        out: list[Space] = []
        page_token: str | None = None
        for _ in range(_MAX_PAGES):
            req = (
                self._service.spaces().list(pageToken=page_token)
                if page_token
                else self._service.spaces().list()
            )
            resp = req.execute()
            for item in resp.get("spaces", []) or []:
                try:
                    space = _parse_space(item)
                except (KeyError, TypeError, ValueError) as exc:
                    # Per-entry failure isolation (reviewer feedback from M5.2):
                    # skip a malformed entry rather than poison the whole list.
                    log.warning(
                        "gchat_skip_malformed_space",
                        error=str(exc),
                        name=item.get("name") if isinstance(item, dict) else None,
                    )
                    continue
                if space.type in ("DIRECT_MESSAGE", "SPACE"):
                    out.append(space)
            page_token = resp.get("nextPageToken") or None
            if not page_token:
                break
        return out

    def _fetch_messages(self, space_name: str, since: datetime) -> list[ChatMessage]:
        # Chat API filter syntax: ``createTime > "2026-05-19T12:00:00Z"``.
        # ``since.isoformat()`` produces ``+00:00`` offsets which Chat
        # accepts.
        flt = f'createTime > "{since.isoformat()}"'
        resp = self._service.spaces().messages().list(parent=space_name, filter=flt).execute()
        out: list[ChatMessage] = []
        for item in resp.get("messages", []) or []:
            try:
                out.append(_parse_chat_message(item, space_name))
            except (KeyError, TypeError, ValueError) as exc:
                # Per-message failure isolation — a single bad entry must
                # not poison the whole list.
                log.warning(
                    "gchat_skip_malformed_message",
                    error=str(exc),
                    name=item.get("name") if isinstance(item, dict) else None,
                )
                continue
        return out

    # ------------------------------------------------------------------
    # cache fallback helpers
    # ------------------------------------------------------------------

    def _cache_fallback_spaces(self, cache_key: str, exc: Exception) -> list[Space]:
        entry = self._cache.get(cache_key)
        if entry is None:
            log.warning("gchat_request_failed_no_cache", error=str(exc))
            raise GoogleChatTransientError(
                "Google Chat list_spaces failed and no cache available"
            ) from exc
        payload, fetched_at = entry
        log.info("gchat_request_cache_hit", fetched_at=fetched_at.isoformat())
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as decode_exc:
            raise GoogleChatTransientError("Google Chat cache corrupted") from decode_exc
        return [_dict_to_space(d) for d in data]

    def _cache_fallback_messages(self, cache_key: str, exc: Exception) -> list[ChatMessage]:
        entry = self._cache.get(cache_key)
        if entry is None:
            log.warning("gchat_request_failed_no_cache", error=str(exc))
            raise GoogleChatTransientError(
                "Google Chat list_recent_messages failed and no cache available"
            ) from exc
        payload, fetched_at = entry
        log.info("gchat_request_cache_hit", fetched_at=fetched_at.isoformat())
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as decode_exc:
            raise GoogleChatTransientError("Google Chat cache corrupted") from decode_exc
        return [_dict_to_msg(d) for d in data]
