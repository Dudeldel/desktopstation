"""Typed loader for the gitignored secrets file.

Secrets live in `~/.config/deskstation/secrets.yaml` (mode 0600). Per the
architecture spec, secrets never leave the host: the daemon loads them at
startup and uses them to authenticate outbound API calls, but they are not
serialized into any payload sent to the ESP32.
"""

from __future__ import annotations

from pathlib import Path

import structlog
import yaml
from pydantic import BaseModel, ConfigDict

_DEFAULT_PATH = Path("~/.config/deskstation/secrets.yaml").expanduser()

_log = structlog.get_logger(__name__)


class JiraSecrets(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_url: str
    email: str
    api_token: str


class BitbucketSecrets(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace: str
    email: str
    api_token: str


class Secrets(BaseModel):
    model_config = ConfigDict(extra="forbid")
    jira: JiraSecrets | None = None
    bitbucket: BitbucketSecrets | None = None


def load_secrets(path: Path | None = None) -> Secrets:
    """Load secrets from YAML, returning an empty Secrets() if file is missing.

    Warns (but does not fail) if the file's permission bits are not 0o600.
    """
    resolved = path if path is not None else _DEFAULT_PATH
    if not resolved.exists():
        return Secrets()

    mode = resolved.stat().st_mode & 0o777
    if mode != 0o600:
        _log.warning("secrets_permissions_too_open", path=str(resolved), mode=oct(mode))

    with resolved.open() as f:
        data = yaml.safe_load(f) or {}
    return Secrets.model_validate(data)
