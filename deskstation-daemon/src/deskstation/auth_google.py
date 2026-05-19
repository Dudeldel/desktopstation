"""Google OAuth2 setup utility.

One-shot CLI helper that performs the OAuth2 local-server flow for Gmail +
Google Chat + Google Calendar and persists a refresh token to disk. Subsequent
daemon runs load the token via :func:`load_credentials` to call Google APIs.

The OAuth client JSON (from Google Cloud Console, Desktop application type) is
expected at ``~/.config/deskstation/google_client.json`` and the resulting
refresh token is written to ``~/.config/deskstation/google_token.json`` with
mode 0o600.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import structlog

_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/chat.spaces.readonly",
    "https://www.googleapis.com/auth/chat.messages.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
]
_DEFAULT_CLIENT_PATH = Path("~/.config/deskstation/google_client.json").expanduser()
_DEFAULT_TOKEN_PATH = Path("~/.config/deskstation/google_token.json").expanduser()

_log = structlog.get_logger(__name__)


def run_oauth_flow(
    client_path: Path | None = None,
    token_path: Path | None = None,
    *,
    flow_factory: Callable[[Path, list[str]], Any] | None = None,
) -> None:
    """Run the OAuth2 installed-app flow and persist the refresh token.

    Idempotent: if a valid token already exists at ``token_path`` (or can be
    refreshed), prints a confirmation and returns without opening a browser.

    The ``flow_factory`` hook lets tests inject a fake flow; production code
    uses :class:`InstalledAppFlow.from_client_secrets_file`.
    """
    # Exit codes used here:
    #   2 - missing client.json (bad setup / input)
    #   3 - flow or load_credentials failure (runtime error, e.g. corrupt token)
    resolved_client = client_path if client_path is not None else _DEFAULT_CLIENT_PATH
    resolved_token = token_path if token_path is not None else _DEFAULT_TOKEN_PATH

    if not resolved_client.exists():
        print(
            f"error: OAuth client JSON not found at {resolved_client}\n"
            "Create a Desktop application OAuth client in the Google Cloud Console "
            "(https://console.cloud.google.com/apis/credentials), download the JSON, "
            f"and place it at {resolved_client}.",
            file=sys.stderr,
        )
        sys.exit(2)

    # Idempotent path: existing token still good (or refreshable).
    if resolved_token.exists():
        try:
            existing = load_credentials(resolved_token)
        except Exception as e:
            print(f"error: failed to load existing token: {e}", file=sys.stderr)
            sys.exit(3)
        if existing is not None and getattr(existing, "valid", False):
            print("Google credentials already valid; no action needed.")
            return

    try:
        if flow_factory is not None:
            flow = flow_factory(resolved_client, _SCOPES)
        else:
            # Lazy import — google libs are heavy and the daemon path skips this.
            # google-auth-oauthlib has no py.typed marker, hence the ignore.
            from google_auth_oauthlib.flow import (  # type: ignore[import-untyped]
                InstalledAppFlow,
            )

            flow = InstalledAppFlow.from_client_secrets_file(str(resolved_client), scopes=_SCOPES)

        creds = flow.run_local_server(port=0, open_browser=True)
        resolved_token.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(resolved_token, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "w") as f:
                f.write(creds.to_json())
        finally:
            # Belt-and-suspenders: umask may relax the mode.
            os.chmod(resolved_token, 0o600)
        print(f"Google credentials saved to {resolved_token} (scopes: {', '.join(_SCOPES)})")
    except SystemExit:
        raise
    except Exception as e:
        print(f"error: OAuth flow failed: {e}", file=sys.stderr)
        sys.exit(3)


def load_credentials(token_path: Path | None = None) -> Any | None:
    """Load saved Google credentials, refreshing if expired.

    Returns ``None`` if the token file does not exist. Refreshed credentials
    are written back atomically (tmp file + rename) with mode 0o600.

    The return type is ``Any`` because ``google.oauth2.credentials.Credentials``
    ships without type stubs (no py.typed); typing it as a string forward-ref
    would still be opaque to mypy. Callers should treat it as a duck-typed
    Credentials-like object.
    """
    resolved = token_path if token_path is not None else _DEFAULT_TOKEN_PATH
    if not resolved.exists():
        return None

    # Lazy import — keeps daemon cold start fast when no Google integration is set up.
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    # from_authorized_user_file is untyped in google-auth (no py.typed marker).
    creds = Credentials.from_authorized_user_file(str(resolved), _SCOPES)  # type: ignore[no-untyped-call]
    if not creds.valid and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        tmp = resolved.parent / (resolved.name + ".tmp")
        try:
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                f.write(creds.to_json())
            os.chmod(tmp, 0o600)
            os.replace(tmp, resolved)
        except Exception:
            # Don't leak a partial tmp file if write/replace failed midway.
            tmp.unlink(missing_ok=True)
            raise
        _log.info("google_token_refreshed", path=str(resolved))
    return creds
