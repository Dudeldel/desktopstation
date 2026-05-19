"""Tests for the Google OAuth setup utility (M5.1).

All tests inject a fake `InstalledAppFlow` via the `flow_factory` parameter or
patch the credential loaders, so no real network calls happen.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from deskstation import auth_google


def _make_fake_factory(token_json: str = '{"refresh_token": "fake"}') -> MagicMock:
    """Build a flow_factory MagicMock whose flow.run_local_server returns fake creds."""
    fake_creds = MagicMock()
    fake_creds.to_json.return_value = token_json
    fake_flow = MagicMock()
    fake_flow.run_local_server.return_value = fake_creds
    factory = MagicMock(return_value=fake_flow)
    return factory


def test_runs_flow_and_writes_token_with_correct_perms(tmp_path: Path) -> None:
    client_path = tmp_path / "client.json"
    client_path.write_text('{"installed": {"client_id": "x"}}')
    token_path = tmp_path / "token.json"

    token_json = '{"refresh_token": "fake", "token": "abc"}'
    factory = _make_fake_factory(token_json)

    auth_google.run_oauth_flow(
        client_path=client_path,
        token_path=token_path,
        flow_factory=factory,
    )

    assert token_path.exists()
    assert token_path.read_text() == token_json
    mode = token_path.stat().st_mode & 0o777
    assert mode == 0o600, f"expected 0o600 got {oct(mode)}"
    factory.assert_called_once_with(client_path, auth_google._SCOPES)


def test_missing_client_json_exits_with_code_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "missing.json"
    token = tmp_path / "token.json"

    with pytest.raises(SystemExit) as excinfo:
        auth_google.run_oauth_flow(client_path=missing, token_path=token)

    assert excinfo.value.code == 2
    captured = capsys.readouterr()
    assert "Google Cloud Console" in captured.err
    assert str(missing) in captured.err


def test_existing_valid_token_is_idempotent(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    client_path = tmp_path / "client.json"
    client_path.write_text("{}")
    token_path = tmp_path / "token.json"
    token_path.write_text('{"refresh_token": "r"}')

    fake_valid = MagicMock()
    fake_valid.valid = True

    factory = _make_fake_factory()
    with patch.object(auth_google, "load_credentials", return_value=fake_valid) as m_load:
        auth_google.run_oauth_flow(
            client_path=client_path,
            token_path=token_path,
            flow_factory=factory,
        )
        m_load.assert_called_once_with(token_path)

    factory.assert_not_called()
    captured = capsys.readouterr()
    assert "already valid" in captured.out


def test_load_credentials_returns_none_when_missing(tmp_path: Path) -> None:
    result = auth_google.load_credentials(tmp_path / "nope.json")
    assert result is None


def test_load_credentials_refreshes_when_expired(tmp_path: Path) -> None:
    token_path = tmp_path / "token.json"
    token_path.write_text('{"refresh_token": "r", "token": "old"}')

    fake_creds = MagicMock()
    fake_creds.valid = False
    fake_creds.expired = True
    fake_creds.refresh_token = "r"
    fake_creds.to_json.return_value = '{"refresh_token": "r", "token": "new"}'

    def _refresh(_req: object) -> None:
        fake_creds.valid = True

    fake_creds.refresh.side_effect = _refresh

    with (
        patch(
            "google.oauth2.credentials.Credentials.from_authorized_user_file",
            return_value=fake_creds,
        ),
        patch("google.auth.transport.requests.Request", return_value=MagicMock()),
    ):
        result = auth_google.load_credentials(token_path)

    assert result is fake_creds
    fake_creds.refresh.assert_called_once()
    # File rewritten with new token JSON, atomic rename means .tmp is gone.
    assert token_path.read_text() == '{"refresh_token": "r", "token": "new"}'
    assert not (tmp_path / "token.json.tmp").exists()
    mode = token_path.stat().st_mode & 0o777
    assert mode == 0o600, f"expected 0o600, got {oct(mode)}"


def test_load_credentials_no_refresh_when_valid(tmp_path: Path) -> None:
    """Sanity: valid creds should not trigger refresh nor rewrite the file."""
    token_path = tmp_path / "token.json"
    original = '{"refresh_token": "r", "token": "fine"}'
    token_path.write_text(original)

    fake_creds = MagicMock()
    fake_creds.valid = True
    fake_creds.expired = False

    with patch(
        "google.oauth2.credentials.Credentials.from_authorized_user_file",
        return_value=fake_creds,
    ):
        result = auth_google.load_credentials(token_path)

    assert result is fake_creds
    fake_creds.refresh.assert_not_called()
    assert token_path.read_text() == original


def test_token_with_no_refresh_token_still_runs_flow(tmp_path: Path) -> None:
    """If a token exists but isn't valid and has no refresh_token, re-run the flow."""
    client_path = tmp_path / "client.json"
    client_path.write_text("{}")
    token_path = tmp_path / "token.json"
    token_path.write_text('{"token": "stale"}')

    fake_invalid = MagicMock()
    fake_invalid.valid = False
    factory = _make_fake_factory()

    with patch.object(auth_google, "load_credentials", return_value=fake_invalid):
        auth_google.run_oauth_flow(
            client_path=client_path,
            token_path=token_path,
            flow_factory=factory,
        )

    factory.assert_called_once()
    written = json.loads(token_path.read_text())
    assert written == {"refresh_token": "fake"}
