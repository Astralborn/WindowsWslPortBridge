"""Smoke test for __main__.py entry point."""

import subprocess
import sys


def test_main_module_shows_help():
    """python -m udp_win_wsl_bridge --help must exit 0 and show usage."""
    result = subprocess.run(
        [sys.executable, "-m", "udp_win_wsl_bridge", "--help"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert "UDP Windows-to-WSL Bridge" in result.stdout
    assert "--listen-port" in result.stdout


def test_main_module_invalid_args_exits_nonzero():
    """An invalid argument must cause a non-zero exit."""
    result = subprocess.run(
        [sys.executable, "-m", "udp_win_wsl_bridge", "--not-a-flag"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode != 0
