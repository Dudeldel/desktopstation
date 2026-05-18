"""Test pydantic envelope models for serial protocol M1 subset."""

import pytest
from pydantic import ValidationError

from deskstation.bridge.protocol import (
    AckData,
    AckMsg,
    Envelope,
    HeartbeatData,
    HeartbeatMsg,
    HelloData,
    HelloMsg,
    ScreenChangedData,
    ScreenChangedMsg,
    ToastData,
    ToastMsg,
    parse_envelope,
    serialize_envelope,
)


def test_parse_hello() -> None:
    line = (
        '{"v":1,"type":"hello",'
        '"data":{"firmware_version":"0.1.0","free_heap":152340,"psram_free":8123456}}'
    )
    env = parse_envelope(line)
    assert isinstance(env, HelloMsg)
    assert env.data.firmware_version == "0.1.0"
    assert env.data.free_heap == 152340
    assert env.data.psram_free == 8123456


def test_parse_heartbeat() -> None:
    line = '{"v":1,"type":"heartbeat","data":{}}'
    env = parse_envelope(line)
    assert isinstance(env, HeartbeatMsg)


def test_parse_toast() -> None:
    line = '{"v":1,"type":"toast","data":{"text":"hi","level":"warning"}}'
    env = parse_envelope(line)
    assert isinstance(env, ToastMsg)
    assert env.data.text == "hi"
    assert env.data.level == "warning"


def test_parse_toast_defaults_to_info() -> None:
    line = '{"v":1,"type":"toast","data":{"text":"hi"}}'
    env = parse_envelope(line)
    assert isinstance(env, ToastMsg)
    assert env.data.level == "info"


def test_parse_ack() -> None:
    line = '{"v":1,"type":"ack","data":{"of_type":"screen_1"}}'
    env = parse_envelope(line)
    assert isinstance(env, AckMsg)
    assert env.data.of_type == "screen_1"


def test_parse_screen_changed() -> None:
    line = '{"v":1,"type":"screen_changed","data":{"screen":2,"via":"swipe"}}'
    env = parse_envelope(line)
    assert isinstance(env, ScreenChangedMsg)
    assert env.data.screen == 2
    assert env.data.via == "swipe"


def test_serialize_roundtrip() -> None:
    envelopes: list[Envelope] = [
        HelloMsg(data=HelloData(firmware_version="0.1.0", free_heap=152340, psram_free=8123456)),
        HeartbeatMsg(data=HeartbeatData()),
        ToastMsg(data=ToastData(text="hello", level="error")),
        AckMsg(data=AckData(of_type="screen_1")),
        ScreenChangedMsg(data=ScreenChangedData(screen=2, via="dot_click")),
    ]
    for env in envelopes:
        line = serialize_envelope(env)
        assert not line.endswith("\n")  # serialize does not include newline
        parsed = parse_envelope(line)
        assert parsed.type == env.type
        assert parsed.data == env.data


def test_parse_rejects_unknown_type() -> None:
    line = '{"v":1,"type":"top_bar","data":{}}'
    with pytest.raises(ValidationError):
        parse_envelope(line)


def test_parse_rejects_wrong_version() -> None:
    line = '{"v":2,"type":"heartbeat","data":{}}'
    with pytest.raises(ValidationError):
        parse_envelope(line)


def test_parse_rejects_malformed_json() -> None:
    line = "not json {{{"
    with pytest.raises(ValueError):
        parse_envelope(line)


def test_parse_rejects_missing_data_field() -> None:
    line = '{"v":1,"type":"toast","data":{}}'  # toast wymaga text
    with pytest.raises(ValidationError):
        parse_envelope(line)


def test_parse_rejects_extra_fields_in_data() -> None:
    line = '{"v":1,"type":"heartbeat","data":{"surprise":"value"}}'
    with pytest.raises(ValidationError):
        parse_envelope(line)


def test_parse_rejects_invalid_toast_level() -> None:
    # "warn" is not valid — spec/02 uses "warning"
    line = '{"v":1,"type":"toast","data":{"text":"hi","level":"warn"}}'
    with pytest.raises(ValidationError):
        parse_envelope(line)


def test_parse_rejects_invalid_screen_changed_via() -> None:
    line = '{"v":1,"type":"screen_changed","data":{"screen":2,"via":"teleport"}}'
    with pytest.raises(ValidationError):
        parse_envelope(line)


def test_parse_rejects_oversized_line() -> None:
    big = '{"v":1,"type":"toast","data":{"text":"' + ("x" * 5000) + '"}}'
    assert len(big) > 4096
    with pytest.raises(ValueError, match="too long"):
        parse_envelope(big)
