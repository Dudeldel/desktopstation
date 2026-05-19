"""Daemon configuration loaded from YAML + env."""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field


class SerialConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    device: str = "/dev/ttyACM0"
    baudrate: int = 921600
    reconnect_interval_sec: float = 2.0


class BridgeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["serial", "mock"] = "serial"


class HeartbeatConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    interval_sec: float = 5.0
    timeout_sec: float = 15.0


class LoggingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    file: Path = Field(default=Path("~/.local/share/deskstation/logs/daemon.jsonl"))
    pretty_console: bool = False


class MockConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    interval_sec: float = 5.0


class JiraPollerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_key: str = ""
    poll_interval_sec: float = 60.0
    enabled: bool = True


class BitbucketPollerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace: str = ""
    repos: list[str] = Field(default_factory=list)
    poll_interval_sec: float = 60.0
    enabled: bool = True


class GmailPollerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = True
    poll_interval_sec: float = 60.0


class GoogleChatPollerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = True
    poll_interval_sec: float = 60.0
    # ``my_email`` is the user's primary Google account email — used as the
    # @-mention heuristic key (local-part) and to detect DMs. The poller
    # only activates when this is non-empty (no sensible default).
    my_email: str = ""


class DbusListenerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = True
    app_name_patterns: list[str] = Field(
        default_factory=lambda: ["WhatsApp*", "Messenger*", "Slack*"]
    )
    buffer_size: int = 32


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")
    serial: SerialConfig = Field(default_factory=SerialConfig)
    bridge: BridgeConfig = Field(default_factory=BridgeConfig)
    heartbeat: HeartbeatConfig = Field(default_factory=HeartbeatConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    mock: MockConfig = Field(default_factory=MockConfig)
    jira: JiraPollerConfig = Field(default_factory=JiraPollerConfig)
    bitbucket: BitbucketPollerConfig = Field(default_factory=BitbucketPollerConfig)
    gmail: GmailPollerConfig = Field(default_factory=GmailPollerConfig)
    gchat: GoogleChatPollerConfig = Field(default_factory=GoogleChatPollerConfig)
    dbus: DbusListenerConfig = Field(default_factory=DbusListenerConfig)


def load_config(path: Path | None = None) -> Config:
    """Load config from YAML file, falling back to defaults if file missing.

    Resolution order:
    1. Explicit `path` argument
    2. `./config.yaml` in cwd
    3. `~/.config/deskstation/config.yaml`
    4. all defaults
    """
    candidates: list[Path] = []
    if path is not None:
        candidates.append(path)
    candidates.append(Path("config.yaml"))
    candidates.append(Path("~/.config/deskstation/config.yaml").expanduser())

    for candidate in candidates:
        if candidate.exists():
            with candidate.open() as f:
                data = yaml.safe_load(f) or {}
            return Config.model_validate(data)

    return Config()
