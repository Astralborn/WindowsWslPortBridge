"""Tests for UDPBridgeService."""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from udp_win_wsl_bridge.models import ClientSession
from udp_win_wsl_bridge.service import UDPBridgeService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_service(**kwargs) -> UDPBridgeService:
    defaults = {
        "wsl_host": "127.0.0.1",
        "listen_port": 15060,
        "wsl_port": 15061,
        "idle_timeout": 5.0,
        "max_sessions": 10,
        "retry_attempts": 3,
        "retry_delay": 0.0,
    }
    defaults.update(kwargs)
    return UDPBridgeService(**defaults)


def make_mock_transport() -> MagicMock:
    t = MagicMock()
    t.sendto = MagicMock()
    t.close = MagicMock()
    return t


def make_mock_session(last_active: float | None = None) -> ClientSession:
    session = ClientSession(
        transport=make_mock_transport(),
        protocol=MagicMock(),
    )
    if last_active is not None:
        session.last_active = last_active
    return session


# ---------------------------------------------------------------------------
# track_task
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_track_task_removes_on_completion():
    svc = make_service()

    async def noop():
        pass

    task = asyncio.create_task(noop())
    svc.track_task(task)
    assert task in svc._pending_tasks
    await task
    # Callback fires synchronously when the task result is retrieved
    await asyncio.sleep(0)
    assert task not in svc._pending_tasks


# ---------------------------------------------------------------------------
# forward_to_wsl – session limit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_forward_rejects_when_session_limit_reached():
    svc = make_service(max_sessions=2)
    svc.bridge_transport = make_mock_transport()

    # Pre-fill sessions up to the limit
    svc.sessions[("1.1.1.1", 1001)] = make_mock_session()
    svc.sessions[("1.1.1.2", 1002)] = make_mock_session()

    new_client = ("1.1.1.3", 1003)
    await svc.forward_to_wsl(b"hello", new_client)

    assert new_client not in svc.sessions
    assert svc.total_packets_forwarded == 0


@pytest.mark.asyncio
async def test_forward_allows_existing_client_at_limit():
    """An existing client must still get through even when the session limit
    is fully saturated."""
    svc = make_service(max_sessions=1)
    svc.bridge_transport = make_mock_transport()

    existing = ("1.1.1.1", 1001)
    session = make_mock_session()
    svc.sessions[existing] = session

    await svc.forward_to_wsl(b"hello", existing)

    session.transport.sendto.assert_called_once_with(b"hello")
    assert svc.total_packets_forwarded == 1


# ---------------------------------------------------------------------------
# forward_to_wsl – session creation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_forward_creates_new_session():
    svc = make_service()
    svc.bridge_transport = make_mock_transport()

    mock_transport = make_mock_transport()
    mock_protocol = MagicMock()

    loop = asyncio.get_running_loop()
    with patch.object(
        loop,
        "create_datagram_endpoint",
        new_callable=AsyncMock,
        return_value=(mock_transport, mock_protocol),
    ):
        client = ("2.2.2.2", 2000)
        await svc.forward_to_wsl(b"data", client)

    assert client in svc.sessions
    assert svc.total_sessions_created == 1
    assert svc.total_packets_forwarded == 1


@pytest.mark.asyncio
async def test_forward_drops_when_bridge_transport_not_ready():
    svc = make_service()
    # bridge_transport is None (not started)

    client = ("3.3.3.3", 3000)
    await svc.forward_to_wsl(b"data", client)

    assert client not in svc.sessions
    assert svc.total_packets_forwarded == 0


# ---------------------------------------------------------------------------
# _create_session – retry logic
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_session_succeeds_after_retries():
    svc = make_service(retry_attempts=3, retry_delay=0.0)
    svc.bridge_transport = make_mock_transport()

    mock_transport = make_mock_transport()
    mock_protocol = MagicMock()
    call_count = 0

    async def flaky_endpoint(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise OSError("connection refused")
        return mock_transport, mock_protocol

    loop = asyncio.get_running_loop()
    with patch.object(loop, "create_datagram_endpoint", side_effect=flaky_endpoint):
        session = await svc._create_session(("4.4.4.4", 4000))

    assert session is not None
    assert call_count == 3


@pytest.mark.asyncio
async def test_create_session_returns_none_after_all_retries_fail():
    svc = make_service(retry_attempts=2, retry_delay=0.0)
    svc.bridge_transport = make_mock_transport()

    loop = asyncio.get_running_loop()
    with patch.object(
        loop,
        "create_datagram_endpoint",
        new_callable=AsyncMock,
        side_effect=OSError("always fails"),
    ):
        session = await svc._create_session(("5.5.5.5", 5000))

    assert session is None


# ---------------------------------------------------------------------------
# _cleanup_session
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cleanup_session_removes_and_closes():
    svc = make_service()
    addr = ("6.6.6.6", 6000)
    session = make_mock_session()
    svc.sessions[addr] = session

    await svc._cleanup_session(addr)

    assert addr not in svc.sessions
    session.transport.close.assert_called_once()


@pytest.mark.asyncio
async def test_cleanup_session_is_idempotent():
    """Cleaning up an already-removed session must not raise."""
    svc = make_service()
    await svc._cleanup_session(("7.7.7.7", 7000))  # Not in sessions – should be silent


# ---------------------------------------------------------------------------
# _cleanup_loop – idle detection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cleanup_loop_removes_stale_sessions():
    svc = make_service(idle_timeout=0.1)
    svc.bridge_transport = make_mock_transport()

    addr = ("8.8.8.8", 8000)
    stale_session = make_mock_session(last_active=time.time() - 1.0)
    svc.sessions[addr] = stale_session

    # _cleanup_loop sleeps max(0.5, idle_timeout/2) before its first tick,
    # so we must wait at least 0.6 s to guarantee one cleanup pass runs.
    task = asyncio.create_task(svc._cleanup_loop())
    await asyncio.sleep(0.6)
    # Signal shutdown so the loop exits cleanly after finishing its current
    # cleanup pass, avoiding a race where cancel() interrupts the gather.
    svc.shutdown_event.set()
    await asyncio.wait_for(task, timeout=1.0)

    assert addr not in svc.sessions
    stale_session.transport.close.assert_called_once()


# ---------------------------------------------------------------------------
# shutdown / async_shutdown
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cleanup_loop_keeps_active_sessions():
    """Sessions whose last_active is within the idle window must be kept."""
    svc = make_service(idle_timeout=60.0)
    svc.bridge_transport = make_mock_transport()

    addr = ("8.8.8.9", 8001)
    active_session = make_mock_session(last_active=time.time())
    svc.sessions[addr] = active_session

    # sleep_interval = max(0.5, 60/2) = 30 s, so we only need one short tick
    # to confirm no cleanup ran.  Cancel after the first sleep finishes.
    task = asyncio.create_task(svc._cleanup_loop())
    await asyncio.sleep(0.6)
    svc.shutdown_event.set()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # The session must still be present — it was not stale
    assert addr in svc.sessions
    active_session.transport.close.assert_not_called()


@pytest.mark.asyncio
async def test_forward_cleans_up_session_on_sendto_error():
    """If sendto raises the session must be removed."""
    svc = make_service()
    svc.bridge_transport = make_mock_transport()

    addr = ("10.0.0.1", 1000)
    broken_transport = make_mock_transport()
    broken_transport.sendto.side_effect = OSError("broken pipe")
    svc.sessions[addr] = make_mock_session()
    svc.sessions[addr].transport = broken_transport

    await svc.forward_to_wsl(b"data", addr)

    assert addr not in svc.sessions
    broken_transport.close.assert_called_once()


@pytest.mark.asyncio
async def test_close_all_sessions_clears_everything():
    svc = make_service()
    transports = []
    for i in range(3):
        t = make_mock_transport()
        transports.append(t)
        session = make_mock_session()
        session.transport = t
        svc.sessions[(f"10.0.0.{i}", 5000 + i)] = session

    await svc._close_all_sessions()

    assert not svc.sessions
    for t in transports:
        t.close.assert_called_once()


# ---------------------------------------------------------------------------
# shutdown / async_shutdown
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_forward_drops_when_session_creation_fails():
    """If _create_session returns None the packet must be silently dropped."""
    svc = make_service()
    svc.bridge_transport = make_mock_transport()

    client = ("5.5.5.5", 5000)
    loop = asyncio.get_running_loop()
    with patch.object(
        loop,
        "create_datagram_endpoint",
        new_callable=AsyncMock,
        side_effect=OSError("connect failed"),
    ):
        await svc.forward_to_wsl(b"data", client)

    assert client not in svc.sessions
    assert svc.total_sessions_created == 0


@pytest.mark.asyncio
async def test_cleanup_session_handles_close_exception():
    """If transport.close() raises, _cleanup_session must still remove the session."""
    svc = make_service()
    addr = ("6.6.6.6", 6000)
    broken_transport = make_mock_transport()
    broken_transport.close.side_effect = OSError("already closed")
    session = make_mock_session()
    session.transport = broken_transport
    svc.sessions[addr] = session

    await svc._cleanup_session(addr)

    assert addr not in svc.sessions


@pytest.mark.asyncio
async def test_cleanup_loop_logs_when_active_sessions_remain():
    """The debug log branch (if self.sessions) must be exercised."""
    # idle_timeout=60 → session won't go stale, but sleep_interval=max(0.5,30)=30
    # so we use idle_timeout=1 → sleep_interval=max(0.5,0.5)=0.5, and the session
    # stays fresh because last_active is refreshed to time.time() just before the tick.
    svc = make_service(idle_timeout=60.0)
    svc.bridge_transport = make_mock_transport()

    addr = ("7.7.7.7", 7000)
    svc.sessions[addr] = make_mock_session(last_active=time.time())

    # Override sleep_interval so the loop ticks quickly
    original_max = max
    call_count = 0

    def fast_max(a, b):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return 0.5  # first call inside _cleanup_loop: make it tick fast
        return original_max(a, b)

    with patch("udp_win_wsl_bridge.service.max", side_effect=fast_max):
        task = asyncio.create_task(svc._cleanup_loop())
        await asyncio.sleep(0.6)
        svc.shutdown_event.set()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert addr in svc.sessions


@pytest.mark.asyncio
async def test_start_binds_and_waits_for_shutdown():
    """start() must create the datagram endpoint and exit once shutdown fires."""
    svc = make_service()
    mock_transport = make_mock_transport()

    loop = asyncio.get_running_loop()
    with patch.object(
        loop,
        "create_datagram_endpoint",
        new_callable=AsyncMock,
        return_value=(mock_transport, MagicMock()),
    ):

        async def _trigger_shutdown():
            await asyncio.sleep(0.05)
            svc.shutdown()

        await asyncio.gather(svc.start(), _trigger_shutdown())

    assert svc.bridge_transport is mock_transport


# ---------------------------------------------------------------------------
# shutdown / async_shutdown
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_shutdown_cancels_cleanup_task():
    """shutdown() must cancel _cleanup_task when it is set."""
    svc = make_service()
    mock_task = MagicMock(spec=asyncio.Task)
    svc._cleanup_task = mock_task

    svc.shutdown()

    mock_task.cancel.assert_called_once()
    assert svc.shutdown_event.is_set()


@pytest.mark.asyncio
async def test_async_shutdown_closes_all_sessions():
    svc = make_service()
    svc.bridge_transport = make_mock_transport()

    for i in range(3):
        svc.sessions[(f"9.9.9.{i}", 9000 + i)] = make_mock_session()

    await svc.async_shutdown()

    assert not svc.sessions
    svc.bridge_transport.close.assert_called_once()


@pytest.mark.asyncio
async def test_async_shutdown_awaits_pending_tasks():
    svc = make_service()
    svc.bridge_transport = make_mock_transport()
    completed = []

    async def slow_task():
        await asyncio.sleep(0.05)
        completed.append(True)

    task = asyncio.create_task(slow_task())
    svc.track_task(task)

    await svc.async_shutdown()

    assert completed == [True]


# ---------------------------------------------------------------------------
# ClientSession.refresh
# ---------------------------------------------------------------------------


def test_session_refresh_updates_last_active():
    session = make_mock_session()
    old_time = 1000.0
    session.last_active = old_time
    session.refresh(ts=old_time + 1.0)
    assert session.last_active == old_time + 1.0


def test_session_refresh_uses_current_time_when_no_ts():
    session = make_mock_session()
    session.last_active = 0.0
    session.refresh()
    assert session.last_active > 0.0
