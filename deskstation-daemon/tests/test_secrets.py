"""Tests for the secrets loader."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import structlog

from deskstation.secrets import Secrets, load_secrets


def test_missing_file_returns_empty_secrets(tmp_path: Path) -> None:
    secrets = load_secrets(tmp_path / "nope.yaml")
    assert isinstance(secrets, Secrets)
    assert secrets.jira is None
    assert secrets.bitbucket is None


def test_empty_file_returns_empty_secrets(tmp_path: Path) -> None:
    p = tmp_path / "secrets.yaml"
    p.write_text("")
    os.chmod(p, 0o600)
    secrets = load_secrets(p)
    assert secrets.jira is None
    assert secrets.bitbucket is None


def test_jira_only_section(tmp_path: Path) -> None:
    p = tmp_path / "secrets.yaml"
    p.write_text(
        "jira:\n"
        "  base_url: https://example.atlassian.net\n"
        "  email: me@example.com\n"
        "  api_token: token-abc\n"
    )
    os.chmod(p, 0o600)
    secrets = load_secrets(p)
    assert secrets.jira is not None
    assert secrets.jira.base_url == "https://example.atlassian.net"
    assert secrets.jira.email == "me@example.com"
    assert secrets.jira.api_token == "token-abc"
    assert secrets.bitbucket is None


def test_both_sections(tmp_path: Path) -> None:
    p = tmp_path / "secrets.yaml"
    p.write_text(
        "jira:\n"
        "  base_url: https://example.atlassian.net\n"
        "  email: me@example.com\n"
        "  api_token: token-abc\n"
        "bitbucket:\n"
        "  workspace: my-workspace\n"
        "  email: me@example.com\n"
        "  api_token: token-xyz\n"
    )
    os.chmod(p, 0o600)
    secrets = load_secrets(p)
    assert secrets.jira is not None
    assert secrets.bitbucket is not None
    assert secrets.bitbucket.workspace == "my-workspace"
    assert secrets.bitbucket.api_token == "token-xyz"
    # username is optional and must default to None when absent.
    assert secrets.bitbucket.username is None


def test_bitbucket_username_optional_and_loaded(tmp_path: Path) -> None:
    p = tmp_path / "secrets.yaml"
    p.write_text(
        "bitbucket:\n"
        "  workspace: my-ws\n"
        "  email: jakub.dudek@wfirma.pl\n"
        "  api_token: redacted\n"
        "  username: jdudek\n"
    )
    os.chmod(p, 0o600)
    secrets = load_secrets(p)
    assert secrets.bitbucket is not None
    assert secrets.bitbucket.username == "jdudek"


def test_malformed_yaml_raises(tmp_path: Path) -> None:
    p = tmp_path / "secrets.yaml"
    p.write_text("jira: [unbalanced\n")
    os.chmod(p, 0o600)
    import yaml

    with pytest.raises(yaml.YAMLError):
        load_secrets(p)


def test_too_open_permissions_logs_warning(tmp_path: Path) -> None:
    p = tmp_path / "secrets.yaml"
    p.write_text(
        "jira:\n"
        "  base_url: https://example.atlassian.net\n"
        "  email: me@example.com\n"
        "  api_token: token-abc\n"
    )
    os.chmod(p, 0o644)

    cap = structlog.testing.LogCapture()
    structlog.configure(processors=[cap])
    try:
        secrets = load_secrets(p)
    finally:
        structlog.reset_defaults()

    assert secrets.jira is not None
    assert any(entry.get("event") == "secrets_permissions_too_open" for entry in cap.entries)
