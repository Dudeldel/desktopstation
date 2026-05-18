"""Pydantic models for the serial protocol envelope (M1 subset).

Only 5 message types are defined here: hello, heartbeat, toast, ack, screen_changed.
Field shapes match `docs/spec/02-serial-protocol.md` (lines 334-471) exactly.
Additional types arrive in later milestones (M2+) and extend the per-type union.
"""

import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

MAX_LINE_BYTES = 4096


class HelloData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    firmware_version: str
    free_heap: int
    psram_free: int


class HeartbeatData(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ToastData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str
    level: Literal["info", "warning", "error"] = "info"


class AckData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    of_type: str


class ScreenChangedData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    screen: int
    via: Literal["swipe", "dot_click", "autoscroll"]


class HelloMsg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    v: Literal[1] = 1
    type: Literal["hello"] = "hello"
    data: HelloData


class HeartbeatMsg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    v: Literal[1] = 1
    type: Literal["heartbeat"] = "heartbeat"
    data: HeartbeatData


class ToastMsg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    v: Literal[1] = 1
    type: Literal["toast"] = "toast"
    data: ToastData


class AckMsg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    v: Literal[1] = 1
    type: Literal["ack"] = "ack"
    data: AckData


class ScreenChangedMsg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    v: Literal[1] = 1
    type: Literal["screen_changed"] = "screen_changed"
    data: ScreenChangedData


Envelope = Annotated[
    HelloMsg | HeartbeatMsg | ToastMsg | AckMsg | ScreenChangedMsg,
    Field(discriminator="type"),
]

_ENVELOPE_ADAPTER: TypeAdapter[Envelope] = TypeAdapter(Envelope)


def parse_envelope(line: str) -> Envelope:
    """Parse a single newline-delimited JSON line into an Envelope.

    Raises ValueError on malformed JSON or oversized line, ValidationError on schema mismatch.
    """
    if len(line.encode("utf-8")) > MAX_LINE_BYTES:
        raise ValueError(f"line too long: {len(line)} bytes (max {MAX_LINE_BYTES})")
    try:
        obj = json.loads(line)
    except json.JSONDecodeError as e:
        raise ValueError(f"malformed JSON: {e}") from e
    return _ENVELOPE_ADAPTER.validate_python(obj)


def serialize_envelope(envelope: Envelope) -> str:
    """Serialize an Envelope to a JSON string (no trailing newline)."""
    return envelope.model_dump_json()
