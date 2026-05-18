"""In-memory bridge implementation for tests and dev-mode without ESP32."""

import asyncio
from collections.abc import AsyncIterator

from deskstation.bridge.protocol import Envelope


class MockBridge:
    """Two-queue in-memory bridge.

    - `send()` puts on outbound queue (test reads via `received()`)
    - `stream()` yields from inbound queue (test injects via `inject()`)
    """

    def __init__(self) -> None:
        self._inbound: asyncio.Queue[Envelope] = asyncio.Queue()
        self._outbound: asyncio.Queue[Envelope] = asyncio.Queue()
        self._closed = False

    async def send(self, envelope: Envelope) -> None:
        if self._closed:
            raise RuntimeError("bridge closed")
        await self._outbound.put(envelope)

    async def stream(self) -> AsyncIterator[Envelope]:
        while not self._closed:
            try:
                yield await asyncio.wait_for(self._inbound.get(), timeout=0.05)
            except TimeoutError:
                continue

    async def close(self) -> None:
        self._closed = True

    # ---- test helpers ----

    async def inject(self, envelope: Envelope) -> None:
        """Inject an envelope as if it arrived from the other end."""
        await self._inbound.put(envelope)

    async def received(self) -> Envelope:
        """Pop the next envelope from the outbound queue (what daemon sent)."""
        return await self._outbound.get()
