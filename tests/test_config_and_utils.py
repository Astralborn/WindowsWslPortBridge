"""Tests for BridgeConfig validation and utility functions."""

import logging
import subprocess

# ---------------------------------------------------------------------------
# BridgeConfig.validate
# ---------------------------------------------------------------------------
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from udp_win_wsl_bridge.config import BridgeConfig
from udp_win_wsl_bridge.logging_utils import setup_logging
from udp_win_wsl_bridge.utils import detect_wsl_ip


def make_valid_config(**overrides: Any) -> BridgeConfig:
    defaults: dict[str, Any] = {
        "wsl_host": "127.0.0.1",
        "listen_port": 5060,
        "wsl_port": 5060,
        "idle_timeout": 5.0,
        "max_sessions": 100,
        "retry_attempts": 3,
        "retry_delay": 1.0,
    }
    defaults.update(overrides)
    return BridgeConfig(**defaults)  # type: ignore[arg-type]


@pytest.mark.parametrize("port_field", ["listen_port", "wsl_port"])
@pytest.mark.parametrize("bad_port", [0, -1, 65536, 99999])
def test_invalid_port_raises(port_field, bad_port):
    cfg = make_valid_config(**{port_field: bad_port})
    with pytest.raises(ValueError):
        cfg.validate()


def test_valid_port_boundary():
    make_valid_config(listen_port=1, wsl_port=65535).validate()


def test_zero_idle_timeout_raises():
    with pytest.raises(ValueError):
        make_valid_config(idle_timeout=0.0).validate()


def test_negative_idle_timeout_raises():
    with pytest.raises(ValueError):
        make_valid_config(idle_timeout=-1.0).validate()


def test_zero_max_sessions_raises():
    with pytest.raises(ValueError):
        make_valid_config(max_sessions=0).validate()


def test_zero_retry_attempts_raises():
    """retry_attempts must be >= 1 (at least one attempt)."""
    with pytest.raises(ValueError):
        make_valid_config(retry_attempts=0).validate()


def test_one_retry_attempt_is_valid():
    """1 means 'try once, no retries' – must be accepted."""
    make_valid_config(retry_attempts=1).validate()


def test_negative_retry_delay_raises():
    with pytest.raises(ValueError):
        make_valid_config(retry_delay=-0.1).validate()


def test_zero_retry_delay_is_valid():
    """Zero delay between retries is allowed."""
    make_valid_config(retry_delay=0.0).validate()


# ---------------------------------------------------------------------------
# detect_wsl_ip
# ---------------------------------------------------------------------------


def test_detect_wsl_ip_returns_first_ip():
    mock_result = MagicMock()
    mock_result.stdout = "172.25.224.1 172.25.224.2\n"
    with patch("udp_win_wsl_bridge.utils.subprocess.run", return_value=mock_result):
        ip = detect_wsl_ip()
    assert ip == "172.25.224.1"


def test_detect_wsl_ip_raises_on_timeout():
    with patch(
        "udp_win_wsl_bridge.utils.subprocess.run", side_effect=subprocess.TimeoutExpired("wsl", 10)
    ):
        with pytest.raises(RuntimeError, match="timed out"):
            detect_wsl_ip()


def test_detect_wsl_ip_raises_on_empty_output():
    mock_result = MagicMock()
    mock_result.stdout = "   \n"
    with patch("udp_win_wsl_bridge.utils.subprocess.run", return_value=mock_result):
        with pytest.raises(RuntimeError, match="No IP"):
            detect_wsl_ip()


def test_detect_wsl_ip_raises_on_invalid_ip():
    mock_result = MagicMock()
    mock_result.stdout = "not-an-ip\n"
    with patch("udp_win_wsl_bridge.utils.subprocess.run", return_value=mock_result):
        with pytest.raises(RuntimeError):
            detect_wsl_ip()


def test_detect_wsl_ip_raises_on_process_error():
    with patch(
        "udp_win_wsl_bridge.utils.subprocess.run",
        side_effect=subprocess.CalledProcessError(1, "wsl"),
    ):
        with pytest.raises(RuntimeError):
            detect_wsl_ip()


def test_detect_wsl_ip_picks_first_when_multiple_valid():
    """When WSL returns multiple valid IPs, only the first should be used."""
    mock_result = MagicMock()
    mock_result.stdout = "10.0.0.1 192.168.1.100 172.16.0.5\n"
    with patch("udp_win_wsl_bridge.utils.subprocess.run", return_value=mock_result):
        ip = detect_wsl_ip()
    assert ip == "10.0.0.1"


def test_detect_wsl_ip_with_single_ip():
    """When WSL returns exactly one IP."""
    mock_result = MagicMock()
    mock_result.stdout = "192.168.50.2\n"
    with patch("udp_win_wsl_bridge.utils.subprocess.run", return_value=mock_result):
        ip = detect_wsl_ip()
    assert ip == "192.168.50.2"


# ---------------------------------------------------------------------------
# setup_logging
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("level", ["DEBUG", "INFO", "WARNING", "ERROR"])
def test_setup_logging_accepts_valid_levels(level):
    """setup_logging must configure the root logger without raising."""
    root = logging.getLogger()
    # Remove existing handlers so basicConfig actually applies the new level
    original_handlers = root.handlers[:]
    root.handlers.clear()
    try:
        setup_logging(level)
        assert root.level == getattr(logging, level)
    finally:
        root.handlers = original_handlers
