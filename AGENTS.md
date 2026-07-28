# AGENTS.md

Instructions for AI agents working on this repository.

## Project Overview

UDP port bridge between Windows and WSL. Listens on a Windows port, forwards UDP packets to a service inside WSL, and relays responses back. Built with Python asyncio.

## Tech Stack

- Python 3.10+
- asyncio (DatagramProtocol)
- uv (package manager)
- pytest + pytest-asyncio (testing)
- ruff (linting + formatting)

## Development Commands

```bash
# Install dependencies
uv sync --dev

# Run linter
uv run ruff check .

# Run formatter check
uv run ruff format --check .

# Run tests
uv run pytest --tb=short -q

# Run the bridge
uv run udp-bridge --wsl-host 172.x.x.x --listen-port 5060
```

## Project Structure

```
udp_win_wsl_bridge/
├── __main__.py      # Entry point, signal handling, asyncio.run
├── cli.py           # Argument parsing, config creation
├── config.py        # BridgeConfig dataclass with validation
├── models.py        # ClientSession, ClientAddr type alias
├── protocols.py     # UDPBridgeProtocol (listener), WSLProtocol (per-client)
├── service.py       # UDPBridgeService (core logic, session management)
├── logging_utils.py # Logging setup
└── utils.py         # WSL IP auto-detection
tests/
├── test_cli.py
├── test_config_and_utils.py
├── test_protocols.py
└── test_service.py
```

## Code Conventions

- Type hints: use native syntax (`dict`, `tuple`, `X | None`) — no `typing.Optional` or `typing.Dict`
- Imports: sorted by ruff (isort-compatible)
- Line length: 100 chars
- Tests: use `pytest.mark.asyncio` for async tests, mock transports with `MagicMock`
- No runtime `assert` for validation — use `if not ...: raise`

## Key Design Decisions

- Each client gets a dedicated WSL-bound socket (`WSLProtocol`) for correct reply routing
- `_creating` set prevents race conditions when concurrent packets arrive from the same new client
- `track_task()` prevents asyncio from GC'ing in-flight forwarding tasks
- Session cleanup runs on a timer at `idle_timeout / 2` interval
- Graceful shutdown: signal → set event → drain tasks → close sessions → close listener

## Before Submitting Changes

1. `uv run ruff check .` — must pass with zero errors
2. `uv run ruff format --check .` — must pass
3. `uv run pytest` — all tests must pass
4. Add tests for any new functionality
5. Do not break Windows compatibility (this is a Windows-only tool)
