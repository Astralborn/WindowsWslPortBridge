"""Protocol implementations for UDP bridge."""

import asyncio
from typing import TYPE_CHECKING, Optional

from .logging_utils import log
from .models import ClientAddr

if TYPE_CHECKING:
    from .service import UDPBridgeService


class UDPBridgeProtocol(asyncio.DatagramProtocol):
    """Protocol for the main UDP bridge listener."""

    def __init__(self, service: "UDPBridgeService") -> None:
        """Initialize UDP bridge protocol.

        :param service: UDP bridge service instance
        :return: None
        """
        self.service = service
        self.transport: Optional[asyncio.DatagramTransport] = None

    def connection_made(self, transport: asyncio.DatagramTransport) -> None:
        """Called when connection is established.

        :param transport: Datagram transport instance
        :return: None
        """
        self.transport = transport
        log(
            f"Listening on {transport.get_extra_info('sockname')} "
            f"-> WSL {self.service.wsl_host}:{self.service.wsl_port}"
        )

    def datagram_received(self, data: bytes, addr: ClientAddr) -> None:
        """Handle incoming UDP datagram.

        Schedules forwarding as a tracked task so it cannot be silently
        garbage-collected by the event loop before completion.

        :param data: Received data
        :param addr: Source address
        :return: None
        """
        task = asyncio.create_task(self.service.forward_to_wsl(data, addr))
        self.service.track_task(task)

    def error_received(self, exc: Exception) -> None:
        """Handle socket error.

        :param exc: Exception that occurred
        :return: None
        """
        log(f"Bridge socket error: {exc}", "ERROR")


class WSLProtocol(asyncio.DatagramProtocol):
    """Protocol for individual client sessions to WSL.

    This class no longer owns ``last_active``; the parent
    :class:`~.models.ClientSession` is the single source of truth.
    """

    def __init__(
        self,
        client_addr: ClientAddr,
        bridge_transport: asyncio.DatagramTransport,
        service: "UDPBridgeService",
    ) -> None:
        """Initialize WSL protocol for client session.

        :param client_addr: Client address tuple
        :param bridge_transport: Bridge transport for sending responses
        :param service: UDP bridge service instance
        :return: None
        """
        self.client_addr = client_addr
        # Do NOT store bridge_transport directly — read it from the service
        # at relay time so we always use the current (non-stale) transport.
        self.service = service
        self.transport: Optional[asyncio.DatagramTransport] = None

    def connection_made(self, transport: asyncio.DatagramTransport) -> None:
        """Called when connection is established.

        :param transport: Datagram transport instance
        :return: None
        """
        self.transport = transport

    def connection_lost(self, exc: Optional[Exception]) -> None:
        """Called when connection is lost.

        :param exc: Exception that caused the loss, or None
        :return: None
        """
        if exc:
            log(f"Connection lost for {self.client_addr}: {exc}", "WARNING")

    def datagram_received(self, data: bytes, addr: ClientAddr) -> None:
        """Handle response from WSL service.

        Refreshes the session timestamp via the session object (single
        source of truth) and relays the response to the original client.

        :param data: Response data from WSL
        :param addr: WSL service address
        :return: None
        """
        bridge_transport = self.service.bridge_transport
        if bridge_transport is None or bridge_transport.is_closing():
            log(f"Bridge transport unavailable, dropping WSL response for {self.client_addr}", "WARNING")
            return

        session = self.service.sessions.get(self.client_addr)
        if session:
            session.refresh()
            session.packets_received += 1
            self.service.total_packets_received += 1

        bridge_transport.sendto(data, self.client_addr)
        log(f"WSL -> {self.client_addr} ({len(data)} bytes)", "DEBUG")

    def error_received(self, exc: Exception) -> None:
        """Handle WSL session error.

        :param exc: Exception that occurred
        :return: None
        """
        log(f"WSL session error {self.client_addr}: {exc}", "ERROR")

