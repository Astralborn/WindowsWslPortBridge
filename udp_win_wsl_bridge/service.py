"""UDP Bridge Service implementation."""

import asyncio
import logging
import time

from .models import ClientAddr, ClientSession
from .protocols import UDPBridgeProtocol, WSLProtocol

logger = logging.getLogger(__name__)


class UDPBridgeService:
    """Main UDP bridge service that forwards packets between Windows and WSL."""

    def __init__(
        self,
        wsl_host: str,
        listen_port: int,
        wsl_port: int,
        idle_timeout: float,
        max_sessions: int = 1000,
        retry_attempts: int = 3,
        retry_delay: float = 1.0,
    ) -> None:
        """Initialize UDP bridge service.

        :param wsl_host: WSL IP address
        :param listen_port: Port to listen on Windows
        :param wsl_port: Target port in WSL
        :param idle_timeout: Session idle timeout in seconds
        :param max_sessions: Maximum concurrent sessions
        :param retry_attempts: Connection retry attempts
        :param retry_delay: Delay between retries in seconds
        :return: None
        """
        self.wsl_host = wsl_host
        self.listen_port = listen_port
        self.wsl_port = wsl_port
        self.idle_timeout = idle_timeout
        self.max_sessions = max_sessions
        self.retry_attempts = retry_attempts
        self.retry_delay = retry_delay
        self.sessions: dict[ClientAddr, ClientSession] = {}
        self.shutdown_event = asyncio.Event()
        self.bridge_transport: asyncio.DatagramTransport | None = None
        self._cleanup_task: asyncio.Task | None = None
        # Track in-flight forwarding tasks so they can't be GC'd mid-execution.
        self._pending_tasks: set[asyncio.Task] = set()
        # Clients whose session is currently being created — prevents a race
        # where two packets from the same new client both trigger _create_session.
        self._creating: set[ClientAddr] = set()
        self.total_sessions_created = 0
        self.total_packets_forwarded = 0
        self.total_packets_received = 0

    def track_task(self, task: asyncio.Task) -> None:
        """Keep a strong reference to a task until it completes.

        Without this, asyncio may silently GC tasks before they finish,
        causing dropped packets.

        :param task: Task to track
        :return: None
        """
        self._pending_tasks.add(task)
        task.add_done_callback(self._pending_tasks.discard)

    async def start(self) -> None:
        """Start the UDP bridge service.

        :return: None
        """
        loop = asyncio.get_running_loop()
        self.bridge_transport, _ = await loop.create_datagram_endpoint(
            lambda: UDPBridgeProtocol(self),
            local_addr=("0.0.0.0", self.listen_port),
        )
        try:
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())
            await self.shutdown_event.wait()
        except Exception:
            self.bridge_transport.close()
            raise

    async def forward_to_wsl(self, data: bytes, client: ClientAddr) -> None:
        """Forward UDP packet from client to WSL.

        :param data: UDP packet data
        :param client: Client address tuple (IP, port)
        :return: None
        """
        # Guard: bridge_transport must be ready before we can relay responses.
        if self.bridge_transport is None:
            logger.warning("Bridge transport not ready, dropping packet from %s", client)
            return

        if len(self.sessions) >= self.max_sessions and client not in self.sessions:
            logger.warning("Session limit reached (%d), rejecting %s", self.max_sessions, client)
            return

        if client not in self.sessions:
            # Guard against concurrent packets from the same new client both
            # triggering _create_session simultaneously, which would leak a session.
            if client in self._creating:
                logger.debug("Session creation in progress for %s, dropping packet", client)
                return
            self._creating.add(client)
            try:
                session = await self._create_session(client)
            finally:
                self._creating.discard(client)
            if session is None:
                return
            self.sessions[client] = session
            self.total_sessions_created += 1
            logger.info("Session created: %s (total: %d)", client, self.total_sessions_created)

        session = self.sessions[client]
        try:
            session.refresh()
            session.transport.sendto(data)
            session.packets_forwarded += 1
            self.total_packets_forwarded += 1
            logger.debug("%s -> WSL (%d bytes)", client, len(data))
        except Exception as exc:
            logger.error("Failed to forward packet from %s: %s", client, exc)
            await self._cleanup_session(client)

    async def _create_session(self, client: ClientAddr) -> ClientSession | None:
        """Create a new WSL session for a client, with retry logic.

        :param client: Client address tuple
        :return: ClientSession on success, None on failure
        """
        if self.bridge_transport is None:
            raise RuntimeError("bridge_transport must be set before creating sessions")
        for attempt in range(self.retry_attempts):
            try:
                transport, protocol = await asyncio.get_running_loop().create_datagram_endpoint(
                    lambda: WSLProtocol(client, self.bridge_transport, self),
                    remote_addr=(self.wsl_host, self.wsl_port),
                )
                return ClientSession(transport=transport, protocol=protocol)
            except Exception as exc:
                if attempt == self.retry_attempts - 1:
                    logger.error(
                        "Failed to create session for %s after %d attempt(s): %s",
                        client, self.retry_attempts, exc,
                    )
                    return None
                logger.warning(
                    "Session creation attempt %d failed for %s: %s, retrying in %ss...",
                    attempt + 1, client, exc, self.retry_delay,
                )
                await asyncio.sleep(self.retry_delay)
        return None

    async def _cleanup_loop(self) -> None:
        """Background loop to clean up idle sessions.

        Sleep interval is half the idle_timeout so we catch stale sessions
        promptly, regardless of how short the timeout is configured.

        :return: None
        """
        sleep_interval = max(0.5, self.idle_timeout / 2)
        while not self.shutdown_event.is_set():
            await asyncio.sleep(sleep_interval)
            now = time.time()
            stale = [
                addr for addr, s in self.sessions.items()
                if now - s.last_active > self.idle_timeout
            ]
            if stale:
                await asyncio.gather(*[self._cleanup_session(addr) for addr in stale])

            if self.sessions:
                logger.debug(
                    "Active sessions: %d/%d, Total packets: %d sent, %d received",
                    len(self.sessions), self.max_sessions,
                    self.total_packets_forwarded, self.total_packets_received,
                )

    async def _cleanup_session(self, addr: ClientAddr) -> None:
        """Close and remove a specific session.

        :param addr: Client address to clean up
        :return: None
        """
        session = self.sessions.pop(addr, None)
        if session is None:
            return
        logger.debug("Closing session: %s", addr)
        try:
            session.transport.close()
        except Exception as exc:
            logger.warning("Error closing session %s: %s", addr, exc)

    async def _close_all_sessions(self) -> None:
        """Close all active sessions concurrently.

        :return: None
        """
        if self.sessions:
            await asyncio.gather(*[
                self._cleanup_session(addr) for addr in list(self.sessions.keys())
            ])

    def shutdown(self) -> None:
        """Signal the bridge to shut down.

        Actual teardown happens in :meth:`async_shutdown`; this method only
        sets the event so it is safe to call from synchronous contexts.

        :return: None
        """
        logger.info("Shutting down bridge")
        self.shutdown_event.set()

        if self._cleanup_task:
            self._cleanup_task.cancel()

    async def async_shutdown(self) -> None:
        """Perform a full graceful shutdown asynchronously.

        Waits for the cleanup task to finish, waits for all pending forwarding
        tasks, closes every session, then closes the bridge transport.

        :return: None
        """
        self.shutdown()

        # Wait for the background cleanup task to finish cancelling.
        if self._cleanup_task:
            try:
                await self._cleanup_task
            except (asyncio.CancelledError, Exception):
                pass

        # Wait for any in-flight forwarding tasks.
        if self._pending_tasks:
            await asyncio.gather(*self._pending_tasks, return_exceptions=True)

        await self._close_all_sessions()

        logger.info(
            "Final stats: %d sessions created, %d packets sent, %d packets received",
            self.total_sessions_created, self.total_packets_forwarded,
            self.total_packets_received,
        )

        if self.bridge_transport:
            self.bridge_transport.close()

