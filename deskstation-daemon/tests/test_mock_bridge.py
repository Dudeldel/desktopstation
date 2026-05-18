"""Tests for the in-memory MockBridge."""

import pytest

from deskstation.bridge.mock_bridge import MockBridge
from deskstation.bridge.protocol import HeartbeatData, HeartbeatMsg, HelloData, HelloMsg


async def test_send_appears_in_outbound() -> None:
    bridge = MockBridge()
    msg = HeartbeatMsg(data=HeartbeatData())
    await bridge.send(msg)
    received = await bridge.received()
    assert received == msg
    await bridge.close()


async def test_injected_message_appears_in_stream() -> None:
    bridge = MockBridge()
    msg = HelloMsg(data=HelloData(firmware_version="0.1.0", free_heap=100000, psram_free=8000000))
    await bridge.inject(msg)
    async for env in bridge.stream():
        assert env == msg
        break
    await bridge.close()


async def test_send_after_close_raises() -> None:
    bridge = MockBridge()
    await bridge.close()
    with pytest.raises(RuntimeError, match="closed"):
        await bridge.send(HeartbeatMsg(data=HeartbeatData()))


async def test_stream_ends_after_close() -> None:
    bridge = MockBridge()
    await bridge.close()
    received = []
    async for env in bridge.stream():
        received.append(env)
    assert received == []
