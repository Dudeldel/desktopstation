"""Tests for SerialBridge with a fake stream pair."""

import asyncio

import pytest

from deskstation.bridge.protocol import HeartbeatMsg, HelloMsg, ToastData, ToastMsg
from deskstation.bridge.serial_bridge import SerialBridge


class FakeStreamPair:
    """Bidirectional in-memory streams that look like asyncio.StreamReader/StreamWriter."""

    def __init__(self) -> None:
        self.host_to_device: asyncio.Queue[bytes] = asyncio.Queue()
        self.device_to_host: asyncio.Queue[bytes] = asyncio.Queue()
        self.closed = False
        self.eof_after_first_read = False
        self._buffer = b""

    # ---- writer-side (host writes) ----
    def write(self, data: bytes) -> None:
        self.host_to_device.put_nowait(data)

    async def drain(self) -> None:
        return

    def close(self) -> None:
        self.closed = True

    def is_closing(self) -> bool:
        return self.closed

    async def wait_closed(self) -> None:
        return

    # ---- reader-side (host reads from device) ----
    async def readline(self) -> bytes:
        if self.eof_after_first_read and self._buffer:
            data, self._buffer = self._buffer, b""
            self.eof_after_first_read = False
            return data
        if self.closed:
            return b""
        try:
            chunk = await asyncio.wait_for(self.device_to_host.get(), timeout=1.0)
        except TimeoutError:
            return b""
        return chunk

    async def push_line(self, line: str) -> None:
        await self.device_to_host.put((line + "\n").encode("utf-8"))


@pytest.fixture
def fake_pair() -> FakeStreamPair:
    return FakeStreamPair()


@pytest.fixture
def bridge(fake_pair: FakeStreamPair) -> SerialBridge:
    async def factory() -> tuple[FakeStreamPair, FakeStreamPair]:
        return fake_pair, fake_pair

    return SerialBridge(connection_factory=factory, reconnect_interval_sec=0.01)  # type: ignore[arg-type]


async def test_send_writes_to_serial(bridge: SerialBridge, fake_pair: FakeStreamPair) -> None:
    msg = ToastMsg(data=ToastData(text="hello"))
    await bridge.send(msg)
    raw = await fake_pair.host_to_device.get()
    assert raw == (msg.model_dump_json() + "\n").encode("utf-8")
    await bridge.close()


async def test_stream_yields_parsed_envelopes(
    bridge: SerialBridge, fake_pair: FakeStreamPair
) -> None:
    await fake_pair.push_line(
        '{"v":1,"type":"hello","data":{"firmware_version":"0.1.0","free_heap":152340,"psram_free":8123456}}'
    )
    async for env in bridge.stream():
        assert isinstance(env, HelloMsg)
        assert env.data.firmware_version == "0.1.0"
        break
    await bridge.close()


async def test_stream_skips_malformed_line(bridge: SerialBridge, fake_pair: FakeStreamPair) -> None:
    await fake_pair.push_line("garbage not json {{")
    await fake_pair.push_line('{"v":1,"type":"heartbeat","data":{}}')
    async for env in bridge.stream():
        assert isinstance(env, HeartbeatMsg)
        break
    await bridge.close()
