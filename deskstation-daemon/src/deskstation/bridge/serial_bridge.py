"""USB CDC serial bridge with auto-reconnect.

Uses pyserial-asyncio under the hood, but takes a `connection_factory` for testability.
"""
import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable

import structlog

from deskstation.bridge.protocol import Envelope, parse_envelope, serialize_envelope

log = structlog.get_logger(__name__)

ConnectionFactory = Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]]


def default_serial_factory(device: str, baudrate: int) -> ConnectionFactory:
    """Wrap pyserial-asyncio.open_serial_connection in a zero-arg async factory."""
    import serial_asyncio  # type: ignore[import-untyped]

    async def factory() -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        pair: tuple[asyncio.StreamReader, asyncio.StreamWriter] = (
            await serial_asyncio.open_serial_connection(url=device, baudrate=baudrate)
        )
        return pair

    return factory


class SerialBridge:
    """Async USB CDC bridge with reconnect loop."""

    def __init__(
        self,
        connection_factory: ConnectionFactory,
        reconnect_interval_sec: float = 2.0,
    ) -> None:
        self._factory = connection_factory
        self._reconnect_interval = reconnect_interval_sec
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()
        self._closed = False

    async def _connect(self) -> None:
        while not self._closed:
            try:
                self._reader, self._writer = await self._factory()
                log.info("serial_connected")
                return
            except OSError as e:
                log.warning("serial_connect_failed", error=str(e))
                await asyncio.sleep(self._reconnect_interval)

    async def send(self, envelope: Envelope) -> None:
        if self._closed:
            raise RuntimeError("bridge closed")
        async with self._lock:
            if self._writer is None or self._writer.is_closing():
                await self._connect()
            assert self._writer is not None
            line = serialize_envelope(envelope) + "\n"
            self._writer.write(line.encode("utf-8"))
            try:
                await self._writer.drain()
            except OSError as e:
                log.warning("serial_drain_failed", error=str(e))

    async def stream(self) -> AsyncIterator[Envelope]:
        if self._reader is None:
            await self._connect()
        while not self._closed:
            assert self._reader is not None
            try:
                raw = await self._reader.readline()
            except OSError as e:
                log.warning("serial_read_failed", error=str(e))
                await self._connect()
                continue
            if not raw:
                log.warning("serial_eof")
                await self._connect()
                continue
            try:
                line = raw.decode("utf-8").rstrip("\n").rstrip("\r")
            except UnicodeDecodeError as e:
                log.warning("serial_decode_failed", error=str(e))
                continue
            try:
                yield parse_envelope(line)
            except ValueError as e:
                log.warning("malformed_line", error=str(e), line=line[:200])
                continue
            except Exception as e:
                log.warning("validation_failed", error=str(e), line=line[:200])
                continue

    async def close(self) -> None:
        self._closed = True
        if self._writer is not None:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:
                pass
