"""Tests for heartbeat sender and connection monitor."""

import asyncio

from deskstation.bridge.heartbeat import ConnectionMonitor, heartbeat_sender
from deskstation.bridge.mock_bridge import MockBridge
from deskstation.bridge.protocol import HeartbeatMsg


async def test_heartbeat_sender_emits_at_interval() -> None:
    bridge = MockBridge()
    task = asyncio.create_task(heartbeat_sender(bridge, interval_sec=0.05))
    await asyncio.sleep(0.17)  # at least 3 ticks
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    count = 0
    while not bridge._outbound.empty():
        env = bridge._outbound.get_nowait()
        assert isinstance(env, HeartbeatMsg)
        count += 1
    assert count >= 3
    await bridge.close()


async def test_connection_monitor_initially_connected() -> None:
    mon = ConnectionMonitor(timeout_sec=10.0)
    assert mon.is_connected is True


async def test_connection_monitor_detects_disconnect() -> None:
    mon = ConnectionMonitor(timeout_sec=0.1)
    task = asyncio.create_task(mon.watchdog(poll_interval_sec=0.02))
    await asyncio.sleep(0.18)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert mon.is_connected is False


async def test_connection_monitor_reconnects_on_rx() -> None:
    mon = ConnectionMonitor(timeout_sec=0.05)
    task = asyncio.create_task(mon.watchdog(poll_interval_sec=0.02))
    await asyncio.sleep(0.12)
    assert mon.is_connected is False
    mon.mark_rx()
    assert mon.is_connected is True
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
