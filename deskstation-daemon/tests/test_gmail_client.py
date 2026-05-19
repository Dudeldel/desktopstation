"""Tests for the Gmail API client (M5.2).

The googleapiclient discovery service is replaced via the ``service_factory``
hook — no real HTTP calls, no live discovery doc fetch.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from googleapiclient.errors import HttpError

from deskstation.clients.gmail import (
    GmailAuthError,
    GmailClient,
    GmailMessage,
    GmailTransientError,
    _extract_sender,
    _parse_internal_date,
)
from deskstation.store.api_cache import ApiCache

_DEFAULT_QUERY = "is:unread newer_than:1d"


def _cache_key(query: str = _DEFAULT_QUERY) -> str:
    return f"gmail:unread:{hashlib.sha256(query.encode()).hexdigest()[:16]}"


def _make_detail(
    msg_id: str,
    from_header: str,
    subject: str,
    snippet: str,
    internal_date_ms: str,
) -> dict[str, Any]:
    return {
        "id": msg_id,
        "snippet": snippet,
        "internalDate": internal_date_ms,
        "payload": {
            "headers": [
                {"name": "From", "value": from_header},
                {"name": "Subject", "value": subject},
            ]
        },
    }


class _FakeService:
    """googleapiclient.discovery.build replacement.

    Models the chained call ``service.users().messages().list(...).execute()``
    and ``service.users().messages().get(...).execute()``. The list response
    and a queue of get responses (one per id) are programmable. Each call may
    be an Exception, in which case ``.execute()`` raises it.
    """

    def __init__(
        self,
        list_response: dict[str, Any] | Exception,
        get_responses: dict[str, dict[str, Any] | Exception] | None = None,
    ) -> None:
        self._list_response = list_response
        self._get_responses = get_responses or {}
        self.list_calls: list[dict[str, Any]] = []
        self.get_calls: list[dict[str, Any]] = []

    def users(self) -> _FakeService:
        return self

    def messages(self) -> _FakeService:
        return self

    def list(self, **kwargs: Any) -> _FakeExec:
        self.list_calls.append(kwargs)
        return _FakeExec(self._list_response)

    def get(self, **kwargs: Any) -> _FakeExec:
        self.get_calls.append(kwargs)
        msg_id = kwargs["id"]
        resp = self._get_responses.get(msg_id)
        if resp is None:
            raise AssertionError(f"unexpected get() for id={msg_id}")
        return _FakeExec(resp)


class _FakeExec:
    def __init__(self, payload: dict[str, Any] | Exception) -> None:
        self._payload = payload

    def execute(self) -> dict[str, Any]:
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


def _make_client(
    tmp_path: Path,
    service: _FakeService,
) -> tuple[GmailClient, ApiCache]:
    cache = ApiCache(tmp_path / "cache.sqlite3")
    client = GmailClient(
        credentials=MagicMock(),  # only the factory touches this — opaque here
        cache=cache,
        service_factory=lambda _c: service,
    )
    return client, cache


def _http_error(status: int) -> HttpError:
    resp = MagicMock()
    resp.status = status
    resp.reason = "Boom"
    return HttpError(resp=resp, content=b"")


# ---------------------------------------------------------------------------
# list_unread_recent
# ---------------------------------------------------------------------------


async def test_list_unread_recent_returns_messages(tmp_path: Path) -> None:
    list_resp = {"messages": [{"id": "m1"}, {"id": "m2"}]}
    detail_m1 = _make_detail(
        "m1",
        "Alice Example <alice@example.com>",
        "Hello world",
        "Snippet for m1",
        "1700000000000",
    )
    detail_m2 = _make_detail(
        "m2",
        "bob@example.com",
        "Re: status",
        "Snippet for m2",
        "1700000060000",
    )
    service = _FakeService(list_resp, {"m1": detail_m1, "m2": detail_m2})
    client, _ = _make_client(tmp_path, service)

    msgs = await client.list_unread_recent()

    assert len(msgs) == 2
    assert msgs[0] == GmailMessage(
        id="m1",
        sender="Alice Example",
        subject="Hello world",
        snippet="Snippet for m1",
        received_at=datetime.fromtimestamp(1700000000.0, tz=UTC),
    )
    assert msgs[1].sender == "bob@example.com"
    assert msgs[1].subject == "Re: status"
    # Verify list was called with the expected query.
    assert service.list_calls == [{"userId": "me", "q": _DEFAULT_QUERY}]
    # Each get used format=metadata and the two expected headers.
    for call in service.get_calls:
        assert call["format"] == "metadata"
        assert call["metadataHeaders"] == ["From", "Subject"]


async def test_caches_successful_response(tmp_path: Path) -> None:
    list_resp = {"messages": [{"id": "m1"}]}
    detail = _make_detail("m1", "alice@example.com", "Subj", "snip", "1700000000000")
    service = _FakeService(list_resp, {"m1": detail})
    client, cache = _make_client(tmp_path, service)

    await client.list_unread_recent()

    entry = cache.get(_cache_key())
    assert entry is not None
    payload, _ = entry
    assert isinstance(payload, bytes)
    data = json.loads(payload)
    assert data[0]["id"] == "m1"
    assert data[0]["sender"] == "alice@example.com"


async def test_falls_back_to_cache_on_http_error(tmp_path: Path) -> None:
    # Pre-populate cache with one message dict.
    cache = ApiCache(tmp_path / "cache.sqlite3")
    cached_msg = {
        "id": "cached1",
        "sender": "Cached Person",
        "subject": "Cached subject",
        "snippet": "Cached snippet",
        "received_at_iso": datetime(2024, 1, 1, 12, 0, tzinfo=UTC).isoformat(),
    }
    cache.put(_cache_key(), json.dumps([cached_msg]).encode())

    # 503 on the initial list() call.
    service = _FakeService(_http_error(503), {})
    client = GmailClient(
        credentials=MagicMock(),
        cache=cache,
        service_factory=lambda _c: service,
    )

    msgs = await client.list_unread_recent()

    assert len(msgs) == 1
    assert msgs[0].id == "cached1"
    assert msgs[0].sender == "Cached Person"


async def test_no_cache_on_transient_raises(tmp_path: Path) -> None:
    service = _FakeService(_http_error(503), {})
    client, _ = _make_client(tmp_path, service)

    with pytest.raises(GmailTransientError):
        await client.list_unread_recent()


async def test_401_raises_auth_error_no_cache_consult(tmp_path: Path) -> None:
    cache = ApiCache(tmp_path / "cache.sqlite3")
    # Populate cache; assert the 401 path does NOT consult it.
    cache.put(
        _cache_key(),
        json.dumps(
            [
                {
                    "id": "cached",
                    "sender": "x",
                    "subject": "y",
                    "snippet": "z",
                    "received_at_iso": datetime(2024, 1, 1, tzinfo=UTC).isoformat(),
                }
            ]
        ).encode(),
    )
    service = _FakeService(_http_error(401), {})
    client = GmailClient(
        credentials=MagicMock(),
        cache=cache,
        service_factory=lambda _c: service,
    )

    with pytest.raises(GmailAuthError):
        await client.list_unread_recent()


# ---------------------------------------------------------------------------
# _extract_sender
# ---------------------------------------------------------------------------


def test_extract_sender_with_display_name() -> None:
    assert _extract_sender("John Smith <john@example.com>") == "John Smith"


def test_extract_sender_email_only() -> None:
    assert _extract_sender("john@example.com") == "john@example.com"


def test_extract_sender_empty() -> None:
    assert _extract_sender("") == "Unknown"


# ---------------------------------------------------------------------------
# _parse_internal_date
# ---------------------------------------------------------------------------


def test_parse_internal_date() -> None:
    dt = _parse_internal_date("1700000000000")
    assert dt.tzinfo is UTC
    assert dt == datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC)
