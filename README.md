# 🚀 UDP Windows-to-WSL Port Bridge

> A production-ready async UDP bridge enabling seamless communication between Windows
> and WSL with enterprise-grade features.

![Python](https://img.shields.io/badge/Python-3776AB?style=flat-square&logo=python&logoColor=white)
![Asyncio](https://img.shields.io/badge/asyncio-3776AB?style=flat-square&logo=python&logoColor=white)
![Platform](https://img.shields.io/badge/Windows%20%2B%20WSL-0078D4?style=flat-square&logo=windows&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-yellow?style=flat-square&logo=opensourceinitiative&logoColor=white)
![pytest](https://img.shields.io/badge/pytest-0A9EDC?style=flat-square&logo=pytest&logoColor=white)

------------------------------------------------------------------------

## 📌 Overview

Windows provides a built-in TCP port proxy:

```bash
netsh interface portproxy
```

However, **UDP is not supported**.

This project implements a **UDP port bridge** using Python and `asyncio`,
allowing Windows applications to communicate with UDP services running inside WSL.

------------------------------------------------------------------------

## 📝 Summary

**WindowsWslPortBridge** is a lightweight, production-ready UDP proxy written entirely
in Python. It was built to solve a real gap in the Windows networking stack — `netsh
interface portproxy` only supports TCP, leaving UDP without a native solution.

### What it does
The bridge listens for incoming UDP packets on a Windows port, creates a dedicated
per-client outbound socket into WSL, forwards the packet, and relays the response back
to the original sender. Each client gets its own isolated session so multiple concurrent
flows never interfere with each other.


### Test suite
Key scenarios covered: concurrent session creation race condition, retry exhaustion,
idle session cleanup, graceful shutdown, stale transport handling, and all CLI error paths.

------------------------------------------------------------------------

## 📋 Table of Contents

- [📌 Overview](#-overview)
- [📝 Summary](#-summary)
- [✨ Features](#-features)
- [🎬 Quick Demo](#-quick-demo)
- [🏗 Architecture](#-architecture)
- [🔎 How It Works](#-how-it-works)
- [⚙️ Installation](#️-installation)
- [▶️ Usage](#️-usage)
- [📊 Monitoring & Logging](#-monitoring--logging)
- [🧪 Running Tests](#-running-tests)
- [🧠 Design Decisions](#-design-decisions)
- [🛠 Use Cases](#-use-cases)
- [🐛 Troubleshooting](#-troubleshooting)
- [📄 License](#-license)
- [⭐ Contributing](#-contributing)
- [🔗 Related Projects](#-related-projects)

------------------------------------------------------------------------

## ✨ Features

- 🔄 UDP forwarding (Windows → WSL)
- ⚡ Fully asynchronous (`asyncio`)
- 👥 Per-client session isolation
- 🧹 Automatic idle session cleanup
- 📦 Zero external dependencies
- 🧵 Supports concurrent UDP clients
- 🪶 Lightweight & efficient
- 🛡️ DoS protection (session limits)
- 🔁 Connection retry logic
- 📊 Session statistics & monitoring
- 📝 Structured logging with levels
- ✅ Configuration validation
- 🪟 Windows-optimized (Ctrl+C graceful shutdown)

------------------------------------------------------------------------

## 🎬 Quick Demo

```powershell
# Terminal 1 (WSL): Start a UDP listener
wsl -e bash -c "nc -u -l -p 5060"

# Terminal 2 (Windows): Start the bridge
uv run udp-bridge --log-level DEBUG

# Terminal 3 (Windows): Send a test packet
python -c "import socket; s=socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.sendto(b'Hello WSL!', ('127.0.0.1', 5060))"
```

You should see `Hello WSL!` appear in Terminal 1.

------------------------------------------------------------------------

## 🏗 Architecture

### Component Diagram

![Architecture Diagram](docs/images/architecture.svg)

### Data Flow

```mermaid
flowchart LR
    C1[UDP Client 1] -->|:5060| L
    C2[UDP Client 2] -->|:5060| L
    CN[UDP Client N] -->|:5060| L

    subgraph Windows ["🪟 Windows Host"]
        L[UDPBridgeProtocol\nlisten 0.0.0.0:5060]
        L --> SM[Session Manager\nforward_to_wsl]
        SM --> P1[WSLProtocol\nclient 1]
        SM --> P2[WSLProtocol\nclient 2]
        SM --> PN[WSLProtocol\nclient N]
    end

    subgraph WSL2 ["🐧 WSL2"]
        SVC[UDP Service\nyour app :5060]
    end

    P1 <-->|UDP| SVC
    P2 <-->|UDP| SVC
    PN <-->|UDP| SVC

    SVC -.->|response| P1
    P1 -.->|bridge_transport.sendto| L
    SVC -.->|response| P2
    P2 -.->|bridge_transport.sendto| L
    SVC -.->|response| PN
    PN -.->|bridge_transport.sendto| L
    L -.->|relay| C1
    L -.->|relay| C2
    L -.->|relay| CN
```

------------------------------------------------------------------------

## 🔎 How It Works

### Packet Flow (Sequence Diagram)

```mermaid
sequenceDiagram
    participant C as UDP Client
    participant B as UDPBridgeProtocol<br/>(Windows :5060)
    participant SM as Session Manager
    participant W as WSLProtocol<br/>(per-client socket)
    participant S as UDP Service<br/>(WSL :5060)

    C->>B: UDP packet
    B->>SM: forward_to_wsl(data, client_addr)

    alt New client
        SM->>W: create_datagram_endpoint()
        Note over SM,W: Retry up to retry_attempts times<br/>with retry_delay seconds between each
        W-->>SM: transport + protocol ready
        SM->>SM: sessions[client_addr] = ClientSession
    end

    SM->>SM: session.refresh()
    SM->>W: transport.sendto(data)
    SM->>SM: packets_forwarded += 1 + total_packets_forwarded += 1
    W->>S: UDP packet (forwarded)

    S->>W: datagram_received(response, addr)
    W->>W: session.refresh() + packets_received += 1 + total_packets_received += 1
    W->>B: bridge_transport.sendto(response, client_addr)
    B->>C: UDP response (relayed)

    loop Every max(0.5, idle_timeout / 2) seconds
        SM->>SM: now - session.last_active > idle_timeout
        SM->>W: transport.close() — remove stale session
    end
```

------------------------------------------------------------------------

## ⚙️ Installation

### Requirements

- **Python 3.8+**
- **[uv](https://docs.astral.sh/uv/)** — fast Python package manager (`pip install uv` or see [uv docs](https://docs.astral.sh/uv/getting-started/installation/))
- **Windows 10/11** with WSL2 installed
- **A WSL instance** running the UDP service you want to bridge to

### Quick Start

```powershell
# Clone the repository
git clone https://github.com/astralborn/WindowsWslPortBridge.git
cd WindowsWslPortBridge

# Set up the environment and install the package
uv sync

# Run the bridge
uv run udp-bridge
```

### Install with dev dependencies (for running tests and linting)

```powershell
uv sync --extra dev
```

### No External Runtime Dependencies

This bridge uses only Python standard library modules — no third-party packages are needed at runtime.

### Project Structure

```
WindowsWslPortBridge/
├── .gitignore
├── LICENSE
├── README.md
├── pyproject.toml
├── uv.lock                             ← pinned dependency lockfile
├── docs/
│   └── images/
│       └── architecture.svg        ← component diagram
├── tests/                          ← test suite
│   ├── __init__.py
│   ├── test_cli.py                 # CLI argument parsing & config creation
│   ├── test_config_and_utils.py    # BridgeConfig validation, detect_wsl_ip, logging
│   ├── test_protocols.py           # UDPBridgeProtocol & WSLProtocol
│   └── test_service.py             # UDPBridgeService (session lifecycle, shutdown)
└── udp_win_wsl_bridge/             ← installable package
    ├── __init__.py                 # Package exports
    ├── __main__.py                 # Entry point (supports both run modes)
    ├── cli.py                      # Argument parsing
    ├── config.py                   # Configuration dataclass & validation
    ├── logging_utils.py            # Logging setup
    ├── models.py                   # ClientSession data model
    ├── protocols.py                # asyncio DatagramProtocol implementations
    ├── service.py                  # Main UDPBridgeService
    └── utils.py                    # WSL IP auto-detection
```

------------------------------------------------------------------------

## ▶️ Usage

### Basic Usage

```powershell
uv run udp-bridge
```

### Custom WSL IP

```powershell
uv run udp-bridge --wsl-host 172.25.224.1
```

### Custom Ports

```powershell
uv run udp-bridge --listen-port 9000 --wsl-port 9000
```

### Advanced Configuration

```powershell
uv run udp-bridge --listen-port 5060 --wsl-port 5060 --timeout 30 --max-sessions 5000 --log-level INFO
```

### Debug Mode

```powershell
uv run udp-bridge --log-level DEBUG
```

### All Parameters

| Argument           | Description                                   | Default |
|--------------------|-----------------------------------------------|---------|
| `--wsl-host`       | WSL IP address (auto-detected if omitted)     | auto    |
| `--listen-port`    | UDP port to listen on (Windows side)          | `5060`  |
| `--wsl-port`       | Target UDP port inside WSL                    | `5060`  |
| `--timeout`        | Idle session timeout in seconds               | `5.0`   |
| `--max-sessions`   | Maximum concurrent sessions                   | `1000`  |
| `--retry-attempts` | Max connection attempts per session (min 1)   | `3`     |
| `--retry-delay`    | Delay between retry attempts in seconds       | `1.0`   |
| `--log-level`      | Logging level: DEBUG / INFO / WARNING / ERROR | `INFO`  |

------------------------------------------------------------------------

## 📊 Monitoring & Logging

### Log Levels

- **DEBUG** — detailed packet flow, per-session stats every cleanup cycle
- **INFO** — session creation, shutdown events
- **WARNING** — retry attempts, session limit reached
- **ERROR** — connection failures, unexpected errors

### Example Output

```
[2026-04-03 12:00:00] INFO: Starting UDP bridge: 5060 -> 172.25.224.1:5060
[2026-04-03 12:00:00] INFO: Listening on ('0.0.0.0', 5060) -> WSL 172.25.224.1:5060
[2026-04-03 12:00:05] INFO: Session created: ('192.168.1.100', 12345) (total: 1)
[2026-04-03 12:00:05] DEBUG: 192.168.1.100:12345 -> WSL (42 bytes)
[2026-04-03 12:00:05] DEBUG: WSL -> ('192.168.1.100', 12345) (42 bytes)
[2026-04-03 12:00:15] DEBUG: Active sessions: 1/1000, Total packets: 5 sent, 5 received
[2026-04-03 12:00:30] INFO: Shutting down bridge
[2026-04-03 12:00:30] INFO: Final stats: 1 sessions created, 5 packets sent, 5 packets received
```

### Graceful Shutdown

Press **Ctrl+C** to shut down cleanly — all active sessions are closed, pending
packets are flushed, and final statistics are printed.

------------------------------------------------------------------------

## 🧪 Running Tests

```powershell
# Install dev dependencies first (if not already done)
uv sync --extra dev

# Run all tests
uv run pytest

# Run with verbose output
uv run pytest -v

# Run a specific test file
uv run pytest tests/test_service.py
uv run pytest tests/test_protocols.py
uv run pytest tests/test_cli.py
uv run pytest tests/test_config_and_utils.py
```

### Test Suite Coverage

| Test file | What it covers | Tests |
|---|---|---|
| `test_config_and_utils.py` | `BridgeConfig` validation, `detect_wsl_ip`, `setup_logging` | 21 |
| `test_service.py` | Session lifecycle, retry logic, cleanup loop, shutdown | 25 |
| `test_protocols.py` | `UDPBridgeProtocol` & `WSLProtocol` behaviour | 10 |
| `test_cli.py` | Argument parsing, config creation, error exits | 8 |
| **Total** | **All modules** | **66** |

------------------------------------------------------------------------

## 🧠 Design Decisions

### Why per-client session mapping?

UDP is connectionless, but most protocols follow a request-response pattern.
Mapping one outbound socket per client prevents packet mixing between clients,
session state conflicts, and response routing errors.

### Why asyncio?

Non-blocking I/O lets a single thread handle many concurrent clients efficiently,
with minimal memory overhead and a clean event-driven structure.

### Why track forwarding tasks explicitly?

`asyncio.create_task()` without storing a reference allows the event loop to
garbage-collect tasks before they finish, silently dropping packets. Every
forwarding task is held in `_pending_tasks` and removed only on completion.

------------------------------------------------------------------------

## 🛠 Use Cases

- 🎮 Game server development inside WSL
- 📡 SIP / RTP testing
- 🌐 DNS service testing
- 📊 Telemetry & metrics pipelines
- 🔬 Custom UDP protocol development

------------------------------------------------------------------------

## 🐛 Troubleshooting

### "Port already in use" (WinError 10048)

```powershell
# Find what is using the port
netstat -ano | findstr :5060

# Kill it (replace 1234 with the actual PID)
taskkill /PID 1234 /F

# Or use a different port
uv run udp-bridge --listen-port 5061
```

### "ImportError: attempted relative import with no known parent package"

You ran `python __main__.py` from inside the `udp_win_wsl_bridge\` folder.
Use `uv run` from the project root instead:

```powershell
# Correct — from WindowsWslPortBridge\
uv run udp-bridge
```

### "WSL hostname command timed out" / auto-detect fails

```powershell
# Get your WSL IP manually
wsl hostname -I

# Pass it explicitly
uv run udp-bridge --wsl-host 172.25.224.1
```

### "Session limit reached"

```powershell
uv run udp-bridge --max-sessions 5000 --log-level DEBUG
```

### "Failed to create session after N attempts"

```powershell
# Increase retries and make sure your WSL service is running first
uv run udp-bridge --retry-attempts 5 --retry-delay 2.0
```

### General debugging

```powershell
uv run udp-bridge --log-level DEBUG
```

------------------------------------------------------------------------

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.

**Author**: Stanislav Nikolaievskyi
**Version**: 1.0.0

------------------------------------------------------------------------

## ⭐ Contributing

Contributions, issues, and feature requests are welcome!

### Development Setup

```powershell
git clone https://github.com/astralborn/WindowsWslPortBridge.git
cd WindowsWslPortBridge
uv sync --extra dev
uv run pytest
```

### Linting & Type Checking

```powershell
uv run ruff check .
uv run ty check udp_win_wsl_bridge
```

### Submitting Changes

1. Fork the repository
2. Create a feature branch
3. Add or update tests for your change
4. Submit a pull request

If you find this useful, consider giving it a ⭐ on GitHub!

------------------------------------------------------------------------

## 🔗 Related Projects

- [netsh interface portproxy](https://learn.microsoft.com/en-us/windows-server/networking/technologies/netsh/netsh-interface-portproxy) — Built-in Windows TCP port proxy (no UDP support)
- [WSL2 networking](https://learn.microsoft.com/en-us/windows/wsl/networking) — Official WSL networking documentation
