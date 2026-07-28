"""Tests for CLI argument parsing and config creation."""

import argparse
from unittest.mock import patch

import pytest

from udp_win_wsl_bridge.cli import create_config_from_args, parse_args
from udp_win_wsl_bridge.config import BridgeConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_args(**overrides) -> argparse.Namespace:
    defaults = {
        "wsl_host": None,
        "listen_port": 5060,
        "wsl_port": 5060,
        "timeout": 5.0,
        "max_sessions": 1000,
        "retry_attempts": 3,
        "retry_delay": 1.0,
        "log_level": "INFO",
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


# ---------------------------------------------------------------------------
# parse_args
# ---------------------------------------------------------------------------

def test_parse_args_defaults(monkeypatch):
    """parse_args must return correct defaults when no flags are passed."""
    monkeypatch.setattr("sys.argv", ["udp-bridge"])
    args = parse_args()

    assert args.listen_port == 5060
    assert args.wsl_port == 5060
    assert args.timeout == 5.0
    assert args.max_sessions == 1000
    assert args.retry_attempts == 3
    assert args.retry_delay == 1.0
    assert args.log_level == "INFO"
    assert args.wsl_host is None


def test_parse_args_custom_values(monkeypatch):
    monkeypatch.setattr("sys.argv", [
        "udp-bridge",
        "--wsl-host", "192.168.1.50",
        "--listen-port", "6000",
        "--wsl-port", "6001",
        "--timeout", "10.0",
        "--max-sessions", "500",
        "--retry-attempts", "5",
        "--retry-delay", "2.0",
        "--log-level", "DEBUG",
    ])
    args = parse_args()

    assert args.wsl_host == "192.168.1.50"
    assert args.listen_port == 6000
    assert args.wsl_port == 6001
    assert args.timeout == 10.0
    assert args.max_sessions == 500
    assert args.retry_attempts == 5
    assert args.retry_delay == 2.0
    assert args.log_level == "DEBUG"


# ---------------------------------------------------------------------------
# create_config_from_args
# ---------------------------------------------------------------------------

def test_create_config_uses_explicit_wsl_host():
    args = make_args(wsl_host="10.0.0.1")
    config = create_config_from_args(args)

    assert isinstance(config, BridgeConfig)
    assert config.wsl_host == "10.0.0.1"
    assert config.listen_port == 5060


def test_create_config_all_fields_propagated():
    args = make_args(
        wsl_host="10.0.0.2",
        listen_port=7000,
        wsl_port=7001,
        timeout=15.0,
        max_sessions=200,
        retry_attempts=2,
        retry_delay=0.5,
        log_level="DEBUG",
    )
    config = create_config_from_args(args)

    assert config.wsl_port == 7001
    assert config.idle_timeout == 15.0
    assert config.max_sessions == 200
    assert config.retry_attempts == 2
    assert config.retry_delay == 0.5
    assert config.log_level == "DEBUG"


def test_create_config_auto_detects_wsl_ip():
    """When wsl_host is None, detect_wsl_ip should be called."""
    args = make_args(wsl_host=None)
    with patch("udp_win_wsl_bridge.cli.detect_wsl_ip", return_value="172.20.0.1") as mock_detect:
        config = create_config_from_args(args)

    mock_detect.assert_called_once()
    assert config.wsl_host == "172.20.0.1"


def test_create_config_exits_on_invalid_explicit_ip():
    """An invalid IP string for wsl_host must trigger sys.exit(1)."""
    args = make_args(wsl_host="not-an-ip")
    with pytest.raises(SystemExit) as exc_info:
        create_config_from_args(args)
    assert exc_info.value.code == 1


def test_create_config_exits_when_wsl_detection_fails():
    """A RuntimeError from detect_wsl_ip must trigger sys.exit(1)."""
    args = make_args(wsl_host=None)
    with patch("udp_win_wsl_bridge.cli.detect_wsl_ip", side_effect=RuntimeError("WSL not running")):
        with pytest.raises(SystemExit) as exc_info:
            create_config_from_args(args)
    assert exc_info.value.code == 1


def test_create_config_exits_on_invalid_port():
    """An out-of-range port must fail validation and trigger sys.exit(1)."""
    args = make_args(wsl_host="10.0.0.1", listen_port=0)
    with pytest.raises(SystemExit) as exc_info:
        create_config_from_args(args)
    assert exc_info.value.code == 1

