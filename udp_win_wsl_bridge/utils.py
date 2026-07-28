"""Utility functions for UDP bridge."""

import ipaddress
import subprocess


def detect_wsl_ip() -> str:
    """Detect WSL IP address using wsl hostname command.

    :return: WSL IP address as string
    :raises RuntimeError: If WSL detection fails or times out
    """
    try:
        result = subprocess.run(
            ["wsl", "hostname", "-I"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
        parts = result.stdout.strip().split()
        if not parts:
            raise RuntimeError("No IP returned from WSL")

        ip = parts[0]
        ipaddress.ip_address(ip)  # Validate
        return ip
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("WSL hostname command timed out") from exc
    except (subprocess.CalledProcessError, ValueError) as exc:
        raise RuntimeError(f"Failed to detect WSL IP: {exc}") from exc
