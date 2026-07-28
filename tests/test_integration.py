"""Integration tests with real UDP sockets."""

import asyncio

import pytest

from udp_win_wsl_bridge.service import UDPBridgeService


@pytest.mark.asyncio
async def test_end_to_end_packet_round_trip():
    """Full integration: real UDP sockets, real packet forwarding and response."""
    # Start a simple UDP echo server to simulate WSL service
    echo_received = asyncio.Event()

    class EchoProtocol(asyncio.DatagramProtocol):
        def __init__(self):
            self.transport = None

        def connection_made(self, transport):
            self.transport = transport

        def datagram_received(self, data, addr):
            self.transport.sendto(data, addr)
            echo_received.set()

    loop = asyncio.get_running_loop()

    # Bind echo server on a random port
    echo_transport, _ = await loop.create_datagram_endpoint(
        EchoProtocol, local_addr=("127.0.0.1", 0)
    )
    echo_port = echo_transport.get_extra_info("sockname")[1]

    # Start the bridge pointing at the echo server
    service = UDPBridgeService(
        wsl_host="127.0.0.1",
        listen_port=0,  # OS picks a free port
        wsl_port=echo_port,
        idle_timeout=5.0,
        max_sessions=10,
        retry_attempts=1,
        retry_delay=0.0,
    )

    # Start bridge on a random port
    bridge_transport, _ = await loop.create_datagram_endpoint(
        lambda: __import__(
            "udp_win_wsl_bridge.protocols", fromlist=["UDPBridgeProtocol"]
        ).UDPBridgeProtocol(service),
        local_addr=("127.0.0.1", 0),
    )
    service.bridge_transport = bridge_transport
    bridge_port = bridge_transport.get_extra_info("sockname")[1]

    # Send a packet to the bridge from a "client"
    response_received = asyncio.Event()
    received_data = []

    class ClientProtocol(asyncio.DatagramProtocol):
        def datagram_received(self, data, addr):
            received_data.append(data)
            response_received.set()

    client_transport, _ = await loop.create_datagram_endpoint(
        ClientProtocol, local_addr=("127.0.0.1", 0)
    )

    test_payload = b"hello WSL"
    client_transport.sendto(test_payload, ("127.0.0.1", bridge_port))

    # Wait for the round trip
    await asyncio.wait_for(response_received.wait(), timeout=2.0)

    assert received_data == [test_payload]
    assert service.total_sessions_created == 1
    assert service.total_packets_forwarded == 1
    assert service.total_packets_received == 1

    # Cleanup
    client_transport.close()
    bridge_transport.close()
    echo_transport.close()
    await service._close_all_sessions()


@pytest.mark.asyncio
async def test_concurrent_packets_from_same_client_no_session_leak():
    """Fire N packets from the same new client simultaneously.

    The _creating guard must ensure only one session is created.
    """
    loop = asyncio.get_running_loop()

    # Echo server
    class EchoProtocol(asyncio.DatagramProtocol):
        def connection_made(self, transport):
            self.transport = transport

        def datagram_received(self, data, addr):
            self.transport.sendto(data, addr)

    echo_transport, _ = await loop.create_datagram_endpoint(
        EchoProtocol, local_addr=("127.0.0.1", 0)
    )
    echo_port = echo_transport.get_extra_info("sockname")[1]

    service = UDPBridgeService(
        wsl_host="127.0.0.1",
        listen_port=0,
        wsl_port=echo_port,
        idle_timeout=5.0,
        max_sessions=100,
        retry_attempts=1,
        retry_delay=0.0,
    )

    from udp_win_wsl_bridge.protocols import UDPBridgeProtocol

    bridge_transport, _ = await loop.create_datagram_endpoint(
        lambda: UDPBridgeProtocol(service),
        local_addr=("127.0.0.1", 0),
    )
    service.bridge_transport = bridge_transport

    # Simulate 20 concurrent packets from the same client address
    fake_client = ("127.0.0.1", 44444)
    tasks = [
        asyncio.create_task(service.forward_to_wsl(f"pkt-{i}".encode(), fake_client))
        for i in range(20)
    ]
    await asyncio.gather(*tasks)

    # Only one session should have been created
    assert service.total_sessions_created == 1
    assert fake_client in service.sessions

    # Cleanup
    bridge_transport.close()
    echo_transport.close()
    await service._close_all_sessions()
