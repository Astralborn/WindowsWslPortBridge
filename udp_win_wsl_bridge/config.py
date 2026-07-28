"""Configuration for UDP bridge."""

from dataclasses import dataclass


@dataclass
class BridgeConfig:
    """Configuration for the UDP bridge service."""

    wsl_host: str
    listen_port: int = 5060
    wsl_port: int = 5060
    idle_timeout: float = 5.0
    max_sessions: int = 1000
    retry_attempts: int = 3
    retry_delay: float = 1.0
    log_level: str = "INFO"

    def validate(self) -> None:
        """Validate configuration values.

        :raises ValueError: If configuration is invalid
        """
        if not (1 <= self.listen_port <= 65535):
            raise ValueError("Listen port must be 1-65535")
        if not (1 <= self.wsl_port <= 65535):
            raise ValueError("WSL port must be 1-65535")
        if self.idle_timeout <= 0:
            raise ValueError("Timeout must be positive")
        if self.max_sessions <= 0:
            raise ValueError("Max sessions must be positive")
        if self.retry_attempts < 1:
            raise ValueError(
                "retry_attempts must be >= 1 (use 1 for a single attempt with no retries)"
            )
        if self.retry_delay < 0:
            raise ValueError("Retry delay must be non-negative")
