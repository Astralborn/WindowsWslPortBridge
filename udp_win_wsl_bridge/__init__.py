"""UDP Windows-to-WSL Port Bridge Package."""

from importlib.metadata import version

from .config import BridgeConfig
from .models import ClientAddr, ClientSession
from .service import UDPBridgeService

__version__ = version("udp-win-wsl-bridge")
__author__ = "Stanislav Nikolaievskyi"
__license__ = "MIT"

__all__ = [
    "UDPBridgeService",
    "ClientSession",
    "ClientAddr",
    "BridgeConfig",
]
