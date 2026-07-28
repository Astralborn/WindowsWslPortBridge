"""
UDP Windows-to-WSL Port Bridge
============================

This service enables UDP communication between a Windows host and a
Windows Subsystem for Linux (WSL) instance.

The bridge listens for UDP packets on a specified port on Windows,
forwards them to a UDP service running inside WSL, and relays responses
back to the originating client. Per-client mappings are maintained to
support concurrent UDP flows, and idle connections are automatically
cleaned up.

The service supports graceful shutdown via Ctrl+C and is intended to run
as a long-lived background process on Windows.

Notes:
- Windows does not provide a built-in UDP port proxy equivalent to
  `netsh interface portproxy` (TCP-only).
- This bridge fills that gap using an asyncio-based implementation.

Typical use cases:
- SIP / RTP development and testing
- Local UDP services inside WSL
- Game servers and custom UDP protocols

The WSL IP address can be specified manually or auto-detected using
`wsl hostname -I`.
"""

import asyncio
import os
import signal
import sys

# ---------------------------------------------------------------------------
# Support BOTH run modes:
#   python -m udp_win_wsl_bridge        (standard, __package__ is set)
#   python udp_win_wsl_bridge/__main__.py  (direct, __package__ is None)
#
# When run directly Python sets __package__ to None, which breaks relative
# imports.  We detect this, insert the project root onto sys.path, and
# re-launch via runpy so the rest of the file executes with __package__
# correctly set to "udp_win_wsl_bridge".
# ---------------------------------------------------------------------------
if __package__ is None:
    # __file__ → .../udp_win_wsl_bridge/__main__.py
    # parent   → .../udp_bridge_pkg   (the project root)
    _pkg_dir = os.path.dirname(os.path.abspath(__file__))
    _root_dir = os.path.dirname(_pkg_dir)
    if _root_dir not in sys.path:
        sys.path.insert(0, _root_dir)
    import runpy
    runpy.run_module("udp_win_wsl_bridge", run_name="__main__", alter_sys=True)
    sys.exit(0)


async def main() -> None:
    """Main entry point for the UDP bridge service.

    :return: None
    """
    from .cli import create_config_from_args, parse_args
    from .logging_utils import log, setup_logging
    from .service import UDPBridgeService

    args = parse_args()

    # Setup logging
    setup_logging(args.log_level)

    # Create and validate config
    config = create_config_from_args(args)

    service = UDPBridgeService(
        wsl_host=config.wsl_host,
        listen_port=config.listen_port,
        wsl_port=config.wsl_port,
        idle_timeout=config.idle_timeout,
        max_sessions=config.max_sessions,
        retry_attempts=config.retry_attempts,
        retry_delay=config.retry_delay,
    )

    log(f"Starting UDP bridge: {config.listen_port} -> {config.wsl_host}:{config.wsl_port}")

    def _request_shutdown(sig: int, _frame: object) -> None:
        log(f"Received signal {sig}, shutting down…")
        service.shutdown()

    signal.signal(signal.SIGINT, _request_shutdown)
    # SIGBREAK is Ctrl+Break on Windows (not available on Unix)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, _request_shutdown)  # type: ignore[attr-defined]

    try:
        await service.start()
    except OSError as exc:
        if sys.platform == "win32" and getattr(exc, "winerror", None) == 10048:
            log(f"Port {config.listen_port} is already in use. Check if another instance is running.", "ERROR")
        else:
            log(f"OS error: {exc}", "ERROR")
    except asyncio.CancelledError:
        log("Service cancelled")
    except Exception as exc:
        log(f"Unexpected error: {exc}", "ERROR")
        raise
    finally:
        await service.async_shutdown()


def run() -> None:
    """Entry point for console script."""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass  # Clean exit — shutdown was already handled inside main()


if __name__ == "__main__":
    run()
