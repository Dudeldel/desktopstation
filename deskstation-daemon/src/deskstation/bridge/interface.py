"""Bridge interface — abstraction over USB serial / mock for testability."""

from collections.abc import AsyncIterator
from typing import Protocol

from deskstation.bridge.protocol import Envelope


class BridgeProtocol(Protocol):
    """Bidirectional channel for envelopes.

    Implementations: SerialBridge (USB CDC) and MockBridge (in-memory).
    """

    async def send(self, envelope: Envelope) -> None:
        """Send an envelope to the other end. Raises on permanent failure."""
        ...

    def stream(self) -> AsyncIterator[Envelope]:
        """Async iterator over incoming envelopes. Yields until closed."""
        ...

    async def close(self) -> None:
        """Close the bridge. After this, send() raises and stream() ends."""
        ...
