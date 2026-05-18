"""Heartbeat sender + ConnectionMonitor for disconnect detection."""

import asyncio
import time

import structlog

from deskstation.bridge.interface import BridgeProtocol
from deskstation.bridge.protocol import HeartbeatData, HeartbeatMsg

log = structlog.get_logger(__name__)


async def heartbeat_sender(bridge: BridgeProtocol, interval_sec: float = 5.0) -> None:
    """Push a heartbeat envelope every `interval_sec`. Runs until cancelled."""
    while True:
        try:
            await bridge.send(HeartbeatMsg(data=HeartbeatData()))
        except Exception as e:
            log.warning("heartbeat_send_failed", error=str(e))
        await asyncio.sleep(interval_sec)


class ConnectionMonitor:
    """Tracks last-received timestamp; flips state on timeout / recovery."""

    def __init__(self, timeout_sec: float = 15.0) -> None:
        self._timeout = timeout_sec
        self._last_rx = time.monotonic()
        self._connected = True

    @property
    def is_connected(self) -> bool:
        return self._connected

    def mark_rx(self) -> None:
        self._last_rx = time.monotonic()
        if not self._connected:
            log.info("reconnected")
            self._connected = True

    async def watchdog(self, poll_interval_sec: float = 1.0) -> None:
        """Loop: every `poll_interval_sec` check elapsed-since-rx; flip state on threshold."""
        while True:
            await asyncio.sleep(poll_interval_sec)
            elapsed = time.monotonic() - self._last_rx
            if elapsed > self._timeout and self._connected:
                log.warning("disconnected", elapsed_sec=elapsed)
                self._connected = False
