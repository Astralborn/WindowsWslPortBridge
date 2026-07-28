"""Data models for UDP bridge."""

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import asyncio

    from .protocols import WSLProtocol

ClientAddr = tuple[str, int]


@dataclass
class ClientSession:
    """Represents a client session with WSL.

    ``last_active`` is the single source of truth for session activity.
    Always update it via :meth:`refresh` rather than writing the field directly.
    """

    transport: "asyncio.DatagramTransport"
    protocol: "WSLProtocol"
    last_active: float = field(default_factory=time.time)
    created_at: float = field(default_factory=time.time)
    packets_forwarded: int = 0
    packets_received: int = 0

    def refresh(self, ts: float | None = None) -> None:
        """Update last_active to the current time (or a provided timestamp).

        :param ts: Timestamp to use; defaults to :func:`time.time`.
        :return: None
        """
        self.last_active = ts if ts is not None else time.time()
