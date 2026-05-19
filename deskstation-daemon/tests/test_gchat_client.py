"""Tests for the Google Chat API client (M5.3).

The googleapiclient discovery service is replaced via the
``service_factory`` hook — no real HTTP calls, no live discovery doc
fetch.
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

from deskstation.clients.gchat import (
    ChatMessage,
    GoogleChatAuthError,
    GoogleChatClient,
    Space,
    _parse_chat_message,
    _parse_space,
)
from deskstation.store.api_cache import ApiCache


def _messages_cache_key(space_name: str) -> str:
    return f"gchat:messages:{hashlib.sha256(space_name.encode()).hexdigest()[:16]}"


class _FakeMessagesEndpoint:
    def __init__(self, response: dict[str, Any] | Exception) -> None:
        self._response = response
        self.calls: list[dict[str, Any]] = []

    def list(self, **kwargs: Any) -> _FakeExec:
        self.calls.append(kwargs)
        return _FakeExec(self._response)


class _FakeSpacesEndpoint:
    """Models ``service.spaces()`` and ``service.spaces().messages()``.

    ``list_responses`` is consumed FIFO for paginated ``spaces.list`` calls;
    ``messages_responses`` is indexed by ``parent`` argument.
    """

    def __init__(
        self,
        list_responses: list[dict[str, Any] | Exception],
        messages_responses: dict[str, dict[str, Any] | Exception] | None = None,
    ) -> None:
        self._list_responses = list(list_responses)
        self._messages_responses = messages_responses or {}
        self.list_calls: list[dict[str, Any]] = []
        self.messages_list_calls: list[dict[str, Any]] = []

    def list(self, **kwargs: Any) -> _FakeExec:
        self.list_calls.append(kwargs)
        if not self._list_responses:
            raise AssertionError("no more queued spaces.list responses")
        return _FakeExec(self._list_responses.pop(0))

    def messages(self) -> _FakeMessagesProxy:
        return _FakeMessagesProxy(self)


class _FakeMessagesProxy:
    def __init__(self, parent: _FakeSpacesEndpoint) -> None:
        self._parent = parent

    def list(self, **kwargs: Any) -> _FakeExec:
        self._parent.messages_list_calls.append(kwargs)
        parent_name = kwargs["parent"]
        resp = self._parent._messages_responses.get(parent_name)
        if resp is None:
            raise AssertionError(f"unexpected messages.list parent={parent_name}")
        return _FakeExec(resp)


class _FakeService:
    def __init__(self, spaces_endpoint: _FakeSpacesEndpoint) -> None:
        self._spaces_endpoint = spaces_endpoint

    def spaces(self) -> _FakeSpacesEndpoint:
        return self._spaces_endpoint


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
    my_email: str = "jakub@example.com",
) -> tuple[GoogleChatClient, ApiCache]:
    cache = ApiCache(tmp_path / "cache.sqlite3")
    client = GoogleChatClient(
        credentials=MagicMock(),
        cache=cache,
        my_email=my_email,
        service_factory=lambda _c: service,
    )
    return client, cache


def _http_error(status: int) -> HttpError:
    resp = MagicMock()
    resp.status = status
    resp.reason = "Boom"
    return HttpError(resp=resp, content=b"")


# ---------------------------------------------------------------------------
# list_spaces
# ---------------------------------------------------------------------------


async def test_list_spaces_filters_to_dm_and_space(tmp_path: Path) -> None:
    list_resp = {
        "spaces": [
            {"name": "spaces/dm1", "displayName": "", "type": "DIRECT_MESSAGE"},
            {"name": "spaces/room1", "displayName": "Engineering", "type": "SPACE"},
            {"name": "spaces/ext1", "displayName": "External thing", "type": "EXTERNAL"},
        ]
    }
    spaces_ep = _FakeSpacesEndpoint([list_resp])
    service = _FakeService(spaces_ep)
    client, _ = _make_client(tmp_path, service)

    spaces = await client.list_spaces()

    assert [s.name for s in spaces] == ["spaces/dm1", "spaces/room1"]
    # DM fallback display name applied.
    assert spaces[0].display_name == "(direct message)"
    assert spaces[1].display_name == "Engineering"
    assert spaces[1].type == "SPACE"


async def test_pagination_returns_combined_pages(tmp_path: Path) -> None:
    page1 = {
        "spaces": [
            {"name": "spaces/dm1", "displayName": "", "type": "DIRECT_MESSAGE"},
        ],
        "nextPageToken": "tok",
    }
    page2 = {
        "spaces": [
            {"name": "spaces/room1", "displayName": "Eng", "type": "SPACE"},
        ],
        # no nextPageToken — pagination ends.
    }
    spaces_ep = _FakeSpacesEndpoint([page1, page2])
    service = _FakeService(spaces_ep)
    client, _ = _make_client(tmp_path, service)

    spaces = await client.list_spaces()

    assert [s.name for s in spaces] == ["spaces/dm1", "spaces/room1"]
    # Second call passes pageToken.
    assert len(spaces_ep.list_calls) == 2
    assert spaces_ep.list_calls[0] == {}
    assert spaces_ep.list_calls[1] == {"pageToken": "tok"}


# ---------------------------------------------------------------------------
# list_recent_messages
# ---------------------------------------------------------------------------


async def test_list_recent_messages_returns_parsed_objects(tmp_path: Path) -> None:
    space_name = "spaces/dm1"
    messages_resp = {
        "messages": [
            {
                "name": f"{space_name}/messages/m1",
                "sender": {"displayName": "Alice"},
                "text": "Hello",
                "createTime": "2026-05-19T12:00:00Z",
            },
            {
                "name": f"{space_name}/messages/m2",
                "sender": {"displayName": "Bob"},
                "text": "Hey",
                "createTime": "2026-05-19T12:05:00.500Z",
            },
        ]
    }
    spaces_ep = _FakeSpacesEndpoint(
        list_responses=[],
        messages_responses={space_name: messages_resp},
    )
    service = _FakeService(spaces_ep)
    client, _ = _make_client(tmp_path, service)

    since = datetime(2026, 5, 19, 11, 0, tzinfo=UTC)
    msgs = await client.list_recent_messages(space_name, since=since)

    assert len(msgs) == 2
    assert msgs[0] == ChatMessage(
        name=f"{space_name}/messages/m1",
        space_name=space_name,
        sender_display_name="Alice",
        text="Hello",
        create_time=datetime(2026, 5, 19, 12, 0, tzinfo=UTC),
    )
    assert msgs[1].sender_display_name == "Bob"
    # Filter built from since.isoformat().
    assert len(spaces_ep.messages_list_calls) == 1
    call = spaces_ep.messages_list_calls[0]
    assert call["parent"] == space_name
    assert call["filter"].startswith('createTime > "2026-05-19T11:00:00')


async def test_falls_back_to_cache_on_http_error(tmp_path: Path) -> None:
    space_name = "spaces/dm1"
    cache = ApiCache(tmp_path / "cache.sqlite3")
    cached_msg = {
        "name": f"{space_name}/messages/cached1",
        "space_name": space_name,
        "sender_display_name": "Cached Person",
        "text": "Cached body",
        "create_time_iso": datetime(2024, 1, 1, 12, 0, tzinfo=UTC).isoformat(),
    }
    cache.put(_messages_cache_key(space_name), json.dumps([cached_msg]).encode())

    spaces_ep = _FakeSpacesEndpoint(
        list_responses=[],
        messages_responses={space_name: _http_error(503)},
    )
    service = _FakeService(spaces_ep)
    client = GoogleChatClient(
        credentials=MagicMock(),
        cache=cache,
        my_email="x@example.com",
        service_factory=lambda _c: service,
    )

    msgs = await client.list_recent_messages(space_name, since=datetime(2024, 1, 1, tzinfo=UTC))

    assert len(msgs) == 1
    assert msgs[0].name == f"{space_name}/messages/cached1"
    assert msgs[0].sender_display_name == "Cached Person"


async def test_401_raises_auth_error_no_cache(tmp_path: Path) -> None:
    cache = ApiCache(tmp_path / "cache.sqlite3")
    # Populate cache; assert the 401 path does NOT consult it.
    cache.put("gchat:spaces", json.dumps([]).encode())
    spaces_ep = _FakeSpacesEndpoint([_http_error(401)])
    service = _FakeService(spaces_ep)
    client = GoogleChatClient(
        credentials=MagicMock(),
        cache=cache,
        my_email="x@example.com",
        service_factory=lambda _c: service,
    )

    with pytest.raises(GoogleChatAuthError):
        await client.list_spaces()


# ---------------------------------------------------------------------------
# parse helpers
# ---------------------------------------------------------------------------


def test_parse_chat_message_handles_missing_text() -> None:
    item = {
        "name": "spaces/dm1/messages/m1",
        "sender": {"displayName": "Alice"},
        # No "text" key — attachment-only message.
        "createTime": "2026-05-19T12:00:00Z",
    }
    msg = _parse_chat_message(item, "spaces/dm1")
    assert msg.text == ""
    assert msg.sender_display_name == "Alice"
    assert msg.create_time == datetime(2026, 5, 19, 12, 0, tzinfo=UTC)


def test_parse_space_falls_back_to_direct_message_label() -> None:
    item = {"name": "spaces/dm1", "type": "DIRECT_MESSAGE"}
    space = _parse_space(item)
    assert space == Space(
        name="spaces/dm1",
        display_name="(direct message)",
        type="DIRECT_MESSAGE",
    )

    # Explicit empty string is also normalised to the fallback.
    item2 = {"name": "spaces/dm2", "displayName": "   ", "type": "DIRECT_MESSAGE"}
    assert _parse_space(item2).display_name == "(direct message)"
