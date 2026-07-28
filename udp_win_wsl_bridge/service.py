"""UDP Bridge Service implementation."""

import asyncio
import time
from typing import Dict, Optional, Set

from .logging_utils import log
from .models import ClientAddr, ClientSession
from .protocols import UDPBridgeProtocol, WSLProtocol


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
        self.sessions: Dict[ClientAddr, ClientSession] = {}
        self.shutdown_event = asyncio.Event()
        self.bridge_transport: Optional[asyncio.DatagramTransport] = None
        self._cleanup_task: Optional[asyncio.Task] = None
        # Track in-flight forwarding tasks so they can't be GC'd mid-execution.
        self._pending_tasks: Set[asyncio.Task] = set()
        # Clients whose session is currently being created — prevents a race
        # where two packets from the same new client both trigger _create_session.
        self._creating: Set[ClientAddr] = set()
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
            log(f"Bridge transport not ready, dropping packet from {client}", "WARNING")
            return

        if len(self.sessions) >= self.max_sessions and client not in self.sessions:
            log(f"Session limit reached ({self.max_sessions}), rejecting {client}", "WARNING")
            return

        if client not in self.sessions:
            # Guard against concurrent packets from the same new client both
            # triggering _create_session simultaneously, which would leak a session.
            if client in self._creating:
                log(f"Session creation in progress for {client}, dropping packet", "DEBUG")
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
            log(f"Session created: {client} (total: {self.total_sessions_created})")

        session = self.sessions[client]
        try:
            session.refresh()
            session.transport.sendto(data)
            session.packets_forwarded += 1
            self.total_packets_forwarded += 1
            log(f"{client} -> WSL ({len(data)} bytes)", "DEBUG")
        except Exception as exc:
            log(f"Failed to forward packet from {client}: {exc}", "ERROR")
            await self._cleanup_session(client)

    async def _create_session(self, client: ClientAddr) -> Optional[ClientSession]:
        """Create a new WSL session for a client, with retry logic.

        :param client: Client address tuple
        :return: ClientSession on success, None on failure
        """
        assert self.bridge_transport is not None, "bridge_transport must be set before creating sessions"
        for attempt in range(self.retry_attempts):
            try:
                transport, protocol = await asyncio.get_running_loop().create_datagram_endpoint(
                    lambda c=client: WSLProtocol(c, self.bridge_transport, self),
                    remote_addr=(self.wsl_host, self.wsl_port),
                )
                return ClientSession(transport=transport, protocol=protocol)
            except Exception as exc:
                if attempt == self.retry_attempts - 1:
                    log(
                        f"Failed to create session for {client} after "
                        f"{self.retry_attempts} attempt(s): {exc}",
                        "ERROR",
                    )
                    return None
                log(
                    f"Session creation attempt {attempt + 1} failed for {client}: "
                    f"{exc}, retrying in {self.retry_delay}s...",
                    "WARNING",
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
                log(
                    f"Active sessions: {len(self.sessions)}/{self.max_sessions}, "
                    f"Total packets: {self.total_packets_forwarded} sent, "
                    f"{self.total_packets_received} received",
                    "DEBUG",
                )

    async def _cleanup_session(self, addr: ClientAddr) -> None:
        """Close and remove a specific session.

        :param addr: Client address to clean up
        :return: None
        """
        session = self.sessions.pop(addr, None)
        if session is None:
            return
        log(f"Closing session: {addr}", "DEBUG")
        try:
            session.transport.close()
        except Exception as exc:
            log(f"Error closing session {addr}: {exc}", "WARNING")

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
        log("Shutting down bridge")
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

        log(
            f"Final stats: {self.total_sessions_created} sessions created, "
            f"{self.total_packets_forwarded} packets sent, "
            f"{self.total_packets_received} packets received"
        )

        if self.bridge_transport:
            self.bridge_transport.close()

