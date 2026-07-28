# AGENTS.md

Instructions for AI agents working on this repository.

## Project Overview

UDP port bridge between Windows and WSL. Listens on a Windows port, forwards UDP packets to a service inside WSL, and relays responses back. Built with Python asyncio.

## Tech Stack

- Python 3.10+
- asyncio (DatagramProtocol)
- uv (package manager)
- pytest + pytest-asyncio + pytest-cov (testing, 90% branch coverage enforced)
- ruff (linting + formatting)
- ty (type checking, source package only)

## Development Commands

```bash
# Install dependencies
uv sync --dev

# Run linter
uv run ruff check .

# Run formatter
uv run ruff format .

# Check formatting (CI mode)
uv run ruff format --check .

# Run type checker (source only, tests excluded)
uv run ty check udp_win_wsl_bridge

# Run tests with coverage
uv run pytest --cov --cov-report=term-missing

# Run tests without coverage (faster)
uv run pytest --tb=short -q

# Run the bridge
uv run udp-bridge --wsl-host 172.x.x.x --listen-port 5060
```

## Project Structure

```
udp_win_wsl_bridge/
├── __init__.py      # Package exports, version via importlib.metadata
├── __main__.py      # Entry point, signal handling, asyncio.run
├── cli.py           # Argument parsing, config creation
├── config.py        # BridgeConfig dataclass with validation
├── models.py        # ClientSession, ClientAddr type alias
├── protocols.py     # UDPBridgeProtocol (listener), WSLProtocol (per-client)
├── service.py       # UDPBridgeService (core logic, session management)
├── logging_utils.py # Logging setup (basicConfig only)
├── utils.py         # WSL IP auto-detection
└── py.typed         # PEP 561 marker
tests/
├── test_cli.py              # CLI argument parsing tests
├── test_config_and_utils.py # Config validation + detect_wsl_ip
├── test_integration.py      # Real UDP socket end-to-end tests
├── test_main_smoke.py       # Subprocess smoke tests for entry point
├── test_protocols.py        # Protocol unit tests
└── test_service.py          # Service logic unit tests
```

## Code Conventions

- Type hints: use native syntax (`dict`, `tuple`, `X | None`) — no `typing.Optional` or `typing.Dict`
- Logging: use `logging.getLogger(__name__)` per module — no custom wrappers
- Imports: sorted by ruff (isort-compatible)
- Line length: 100 chars
- Formatting: ruff format (black-compatible)
- No runtime `assert` for validation — use `if not ...: raise`
- Tests: use `pytest.mark.asyncio` for async tests, mock transports with `MagicMock`

## Key Design Decisions

- Each client gets a dedicated WSL-bound socket (`WSLProtocol`) for correct reply routing
- `_creating` set prevents race conditions when concurrent packets arrive from the same new client
- `track_task()` prevents asyncio from GC'ing in-flight forwarding tasks
- Session cleanup runs on a timer at `idle_timeout / 2` interval
- Graceful shutdown: signal → set event → drain tasks → close sessions → close listener
- Version is single-sourced from package metadata (`importlib.metadata`)

## CI Pipeline

GitHub Actions runs on every push/PR to `main`:
1. **lint** — `ruff check` + `ruff format --check`
2. **typecheck** — `ty check udp_win_wsl_bridge`
3. **test** — pytest with coverage on Python 3.10–3.13 × Ubuntu + Windows

## Before Submitting Changes

1. `uv run ruff check .` — must pass with zero errors
2. `uv run ruff format --check .` — must pass
3. `uv run ty check udp_win_wsl_bridge` — must pass
4. `uv run pytest --cov` — all tests must pass, coverage ≥ 90%
5. Add tests for any new functionality
6. Do not break Windows compatibility (this is a Windows-only tool)
