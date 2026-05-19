"""Tests for the SQLite-backed API response cache."""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from pathlib import Path

from deskstation.store.api_cache import ApiCache


def test_empty_get_returns_none(tmp_path: Path) -> None:
    cache = ApiCache(tmp_path / "cache.sqlite3")
    assert cache.get("jira:issues:DEV") is None
    assert cache.age_sec("jira:issues:DEV") is None


def test_put_get_round_trip_preserves_bytes(tmp_path: Path) -> None:
    cache = ApiCache(tmp_path / "cache.sqlite3")
    payload = b'{"hello": "world", "n": 42}'
    cache.put("k", payload)
    entry = cache.get("k")
    assert entry is not None
    got_payload, fetched_at = entry
    assert got_payload == payload
    assert isinstance(fetched_at, datetime)


def test_age_sec_is_small_right_after_put(tmp_path: Path) -> None:
    cache = ApiCache(tmp_path / "cache.sqlite3")
    cache.put("k", b"x")
    time.sleep(0.01)
    age = cache.age_sec("k")
    assert age is not None
    assert 0.0 <= age < 5.0


def test_put_with_explicit_datetime_is_honored(tmp_path: Path) -> None:
    cache = ApiCache(tmp_path / "cache.sqlite3")
    moment = datetime.now() - timedelta(hours=1)
    cache.put("k", b"x", fetched_at=moment)
    entry = cache.get("k")
    assert entry is not None
    _, fetched_at = entry
    assert fetched_at == moment
    age = cache.age_sec("k")
    assert age is not None
    assert age > 3500.0  # roughly an hour


def test_put_replaces_existing_value(tmp_path: Path) -> None:
    cache = ApiCache(tmp_path / "cache.sqlite3")
    cache.put("k", b"first")
    cache.put("k", b"second")
    entry = cache.get("k")
    assert entry is not None
    payload, _ = entry
    assert payload == b"second"


def test_persists_across_reopen(tmp_path: Path) -> None:
    db = tmp_path / "cache.sqlite3"
    cache = ApiCache(db)
    cache.put("k", b"persisted")
    cache.close()

    cache2 = ApiCache(db)
    entry = cache2.get("k")
    assert entry is not None
    payload, _ = entry
    assert payload == b"persisted"
