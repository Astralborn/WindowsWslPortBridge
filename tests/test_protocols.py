"""Tests for UDPBridgeProtocol and WSLProtocol."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from udp_win_wsl_bridge.models import ClientSession
from udp_win_wsl_bridge.protocols import UDPBridgeProtocol, WSLProtocol

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_mock_transport() -> MagicMock:
    t = MagicMock(spec=asyncio.DatagramTransport)
    t.sendto = MagicMock()
    t.close = MagicMock()
    t.get_extra_info = MagicMock(return_value=("0.0.0.0", 5060))
    return t


def make_mock_service() -> MagicMock:
    svc = MagicMock()
    svc.wsl_host = "127.0.0.1"
    svc.wsl_port = 5061
    svc.sessions = {}
    svc.total_packets_received = 0
    svc.forward_to_wsl = AsyncMock()
    svc.track_task = MagicMock()
    svc.bridge_transport = make_mock_transport()
    svc.bridge_transport.is_closing.return_value = False
    return svc


def make_mock_session() -> ClientSession:
    return ClientSession(
        transport=make_mock_transport(),
        protocol=MagicMock(),
    )


# ---------------------------------------------------------------------------
# UDPBridgeProtocol
# ---------------------------------------------------------------------------

def test_bridge_protocol_connection_made_stores_transport():
    svc = make_mock_service()
    proto = UDPBridgeProtocol(svc)
    transport = make_mock_transport()

    proto.connection_made(transport)

    assert proto.transport is transport


@pytest.mark.asyncio
async def test_bridge_protocol_datagram_received_schedules_task():
    """datagram_received must call track_task with a coroutine task."""
    svc = make_mock_service()
    proto = UDPBridgeProtocol(svc)

    proto.datagram_received(b"hello", ("1.2.3.4", 1234))
    # Allow the event loop to schedule the task
    await asyncio.sleep(0)

    svc.track_task.assert_called_once()
    svc.forward_to_wsl.assert_awaited_once_with(b"hello", ("1.2.3.4", 1234))


def test_bridge_protocol_error_received_does_not_raise():
    svc = make_mock_service()
    proto = UDPBridgeProtocol(svc)
    # Must not raise
    proto.error_received(OSError("test error"))


# ---------------------------------------------------------------------------
# WSLProtocol
# ---------------------------------------------------------------------------

def test_wsl_protocol_connection_made_stores_transport():
    svc = make_mock_service()
    proto = WSLProtocol(("1.2.3.4", 1000), svc.bridge_transport, svc)
    transport = make_mock_transport()

    proto.connection_made(transport)

    assert proto.transport is transport


def test_wsl_protocol_datagram_received_relays_to_client():
    """Response from WSL must be forwarded back to the original client."""
    svc = make_mock_service()
    client_addr = ("1.2.3.4", 1000)
    session = make_mock_session()
    svc.sessions[client_addr] = session

    proto = WSLProtocol(client_addr, svc.bridge_transport, svc)
    proto.datagram_received(b"response", ("127.0.0.1", 5061))

    svc.bridge_transport.sendto.assert_called_once_with(b"response", client_addr)


def test_wsl_protocol_datagram_received_refreshes_session_and_increments_counters():
    svc = make_mock_service()
    client_addr = ("1.2.3.4", 1000)
    session = make_mock_session()
    original_last_active = session.last_active
    svc.sessions[client_addr] = session

    proto = WSLProtocol(client_addr, svc.bridge_transport, svc)
    proto.datagram_received(b"pong", ("127.0.0.1", 5061))

    assert session.last_active >= original_last_active
    assert session.packets_received == 1
    assert svc.total_packets_received == 1


def test_wsl_protocol_datagram_received_no_session_still_relays():
    """Even without a matching session the packet must still be relayed."""
    svc = make_mock_service()
    client_addr = ("9.9.9.9", 9999)

    proto = WSLProtocol(client_addr, svc.bridge_transport, svc)
    proto.datagram_received(b"data", ("127.0.0.1", 5061))

    svc.bridge_transport.sendto.assert_called_once_with(b"data", client_addr)
    assert svc.total_packets_received == 0


def test_wsl_protocol_datagram_received_drops_when_bridge_closing():
    """If the bridge transport is closing the response must be dropped silently."""
    svc = make_mock_service()
    svc.bridge_transport.is_closing.return_value = True
    client_addr = ("1.2.3.4", 1000)

    proto = WSLProtocol(client_addr, svc.bridge_transport, svc)
    proto.datagram_received(b"data", ("127.0.0.1", 5061))

    svc.bridge_transport.sendto.assert_not_called()


def test_wsl_protocol_datagram_received_drops_when_bridge_is_none():
    """If service.bridge_transport is None the response must be dropped silently."""
    svc = make_mock_service()
    svc.bridge_transport = None
    client_addr = ("1.2.3.4", 1000)

    proto = WSLProtocol(client_addr, MagicMock(), svc)
    proto.datagram_received(b"data", ("127.0.0.1", 5061))
    # No exception raised — test passes if we reach here


def test_wsl_protocol_connection_lost_without_exception():
    svc = make_mock_service()
    proto = WSLProtocol(("1.2.3.4", 1000), svc.bridge_transport, svc)
    proto.connection_lost(None)


def test_wsl_protocol_connection_lost_with_exception_does_not_raise():
    svc = make_mock_service()
    proto = WSLProtocol(("1.2.3.4", 1000), svc.bridge_transport, svc)
    proto.connection_lost(OSError("reset by peer"))


def test_wsl_protocol_error_received_does_not_raise():
    svc = make_mock_service()
    proto = WSLProtocol(("1.2.3.4", 1000), svc.bridge_transport, svc)
    proto.error_received(OSError("network unreachable"))

