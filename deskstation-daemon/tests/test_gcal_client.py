"""Tests for the Google Calendar API client (M5.6).

The googleapiclient discovery service is replaced via the
``service_factory`` hook — no real HTTP calls, no live discovery doc
fetch.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from googleapiclient.errors import HttpError

from deskstation.clients.gcal import (
    GoogleCalendarAuthError,
    GoogleCalendarClient,
)
from deskstation.store.api_cache import ApiCache


class _FakeExec:
    def __init__(self, payload: dict[str, Any] | Exception) -> None:
        self._payload = payload

    def execute(self) -> dict[str, Any]:
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class _FakeEventsEndpoint:
    def __init__(self, response: dict[str, Any] | Exception) -> None:
        self._response = response
        self.list_calls: list[dict[str, Any]] = []

    def list(self, **kwargs: Any) -> _FakeExec:
        self.list_calls.append(kwargs)
        return _FakeExec(self._response)


class _FakeService:
    def __init__(self, events_endpoint: _FakeEventsEndpoint) -> None:
        self._events = events_endpoint

    def events(self) -> _FakeEventsEndpoint:
        return self._events


def _make_client(
    tmp_path: Path,
    service: _FakeService,
) -> tuple[GoogleCalendarClient, ApiCache]:
    cache = ApiCache(tmp_path / "cache.sqlite3")
    client = GoogleCalendarClient(
        credentials=MagicMock(),
        cache=cache,
        service_factory=lambda _c: service,
    )
    return client, cache


def _http_error(status: int) -> HttpError:
    resp = MagicMock()
    resp.status = status
    resp.reason = "Boom"
    return HttpError(resp=resp, content=b"")


def _meet_event(
    event_id: str,
    summary: str,
    start_iso: str,
    end_iso: str,
    hangout: str = "https://meet.google.com/abc-defg-hij",
) -> dict[str, Any]:
    return {
        "id": event_id,
        "summary": summary,
        "start": {"dateTime": start_iso},
        "end": {"dateTime": end_iso},
        "hangoutLink": hangout,
    }


# ---------------------------------------------------------------------------
# list_upcoming
# ---------------------------------------------------------------------------


async def test_list_upcoming_returns_meetings(tmp_path: Path) -> None:
    events_resp = {
        "items": [
            _meet_event(
                "ev1",
                "Standup",
                "2026-05-19T09:00:00Z",
                "2026-05-19T09:15:00Z",
                hangout="https://meet.google.com/aaa-bbb-ccc",
            ),
            _meet_event(
                "ev2",
                "Design review",
                "2026-05-19T11:00:00+02:00",
                "2026-05-19T12:00:00+02:00",
                hangout="https://meet.google.com/xxx-yyy-zzz",
            ),
        ]
    }
    events_ep = _FakeEventsEndpoint(events_resp)
    service = _FakeService(events_ep)
    client, _ = _make_client(tmp_path, service)

    meetings = await client.list_upcoming(window_hours=36)

    assert [m.id for m in meetings] == ["ev1", "ev2"]
    assert meetings[0].title == "Standup"
    assert meetings[0].join_url == "https://meet.google.com/aaa-bbb-ccc"
    # Z normalised to +00:00; result in UTC.
    assert meetings[0].start == datetime(2026, 5, 19, 9, 0, tzinfo=UTC)
    assert meetings[0].end == datetime(2026, 5, 19, 9, 15, tzinfo=UTC)
    # +02:00 normalised to UTC.
    assert meetings[1].start == datetime(2026, 5, 19, 9, 0, tzinfo=UTC)
    # The service was invoked with the expected arguments.
    assert len(events_ep.list_calls) == 1
    call = events_ep.list_calls[0]
    assert call["calendarId"] == "primary"
    assert call["singleEvents"] is True
    assert call["orderBy"] == "startTime"
    assert call["maxResults"] == 20


async def test_list_upcoming_filters_no_hangout_link(tmp_path: Path) -> None:
    events_resp = {
        "items": [
            _meet_event(
                "ev_meet",
                "With Meet",
                "2026-05-19T09:00:00Z",
                "2026-05-19T09:15:00Z",
            ),
            {
                "id": "ev_no_meet",
                "summary": "No Meet",
                "start": {"dateTime": "2026-05-19T10:00:00Z"},
                "end": {"dateTime": "2026-05-19T10:30:00Z"},
                # no hangoutLink
            },
        ]
    }
    client, _ = _make_client(tmp_path, _FakeService(_FakeEventsEndpoint(events_resp)))

    meetings = await client.list_upcoming(window_hours=36)

    assert [m.id for m in meetings] == ["ev_meet"]


async def test_list_upcoming_skips_all_day_events(tmp_path: Path) -> None:
    events_resp = {
        "items": [
            _meet_event(
                "ev_timed",
                "Timed meeting",
                "2026-05-19T09:00:00Z",
                "2026-05-19T09:15:00Z",
            ),
            {
                "id": "ev_all_day",
                "summary": "All-day company event",
                # only date — no dateTime
                "start": {"date": "2026-05-19"},
                "end": {"date": "2026-05-20"},
                "hangoutLink": "https://meet.google.com/all-day-link",
            },
        ]
    }
    client, _ = _make_client(tmp_path, _FakeService(_FakeEventsEndpoint(events_resp)))

    meetings = await client.list_upcoming(window_hours=36)

    assert [m.id for m in meetings] == ["ev_timed"]


async def test_caches_successful_response(tmp_path: Path) -> None:
    events_resp = {
        "items": [
            _meet_event(
                "ev1",
                "Cached meeting",
                "2026-05-19T09:00:00Z",
                "2026-05-19T09:15:00Z",
            ),
        ]
    }
    client, cache = _make_client(tmp_path, _FakeService(_FakeEventsEndpoint(events_resp)))

    await client.list_upcoming(window_hours=36)

    entry = cache.get("gcal:upcoming:36")
    assert entry is not None
    payload, _ = entry
    decoded = json.loads(payload)
    assert decoded[0]["id"] == "ev1"
    assert decoded[0]["title"] == "Cached meeting"


async def test_falls_back_to_cache_on_http_error(tmp_path: Path) -> None:
    cache = ApiCache(tmp_path / "cache.sqlite3")
    cached_meeting = {
        "id": "cached1",
        "title": "Cached meeting",
        "start_iso": datetime(2026, 5, 19, 9, 0, tzinfo=UTC).isoformat(),
        "end_iso": datetime(2026, 5, 19, 9, 30, tzinfo=UTC).isoformat(),
        "join_url": "https://meet.google.com/cached",
    }
    cache.put("gcal:upcoming:36", json.dumps([cached_meeting]).encode())

    events_ep = _FakeEventsEndpoint(_http_error(503))
    service = _FakeService(events_ep)
    client = GoogleCalendarClient(
        credentials=MagicMock(),
        cache=cache,
        service_factory=lambda _c: service,
    )

    meetings = await client.list_upcoming(window_hours=36)

    assert len(meetings) == 1
    assert meetings[0].id == "cached1"
    assert meetings[0].title == "Cached meeting"
    assert meetings[0].join_url == "https://meet.google.com/cached"


async def test_401_raises_auth_error_no_cache(tmp_path: Path) -> None:
    cache = ApiCache(tmp_path / "cache.sqlite3")
    # Pre-populated cache — assert the 401 path does NOT consult it.
    cache.put("gcal:upcoming:36", json.dumps([]).encode())
    events_ep = _FakeEventsEndpoint(_http_error(401))
    service = _FakeService(events_ep)
    client = GoogleCalendarClient(
        credentials=MagicMock(),
        cache=cache,
        service_factory=lambda _c: service,
    )

    with pytest.raises(GoogleCalendarAuthError):
        await client.list_upcoming(window_hours=36)
