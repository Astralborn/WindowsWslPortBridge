"""Logging utilities for UDP bridge."""

import logging


def setup_logging(level: str = "INFO") -> None:
    """Setup logging configuration.

    :param level: Logging level (DEBUG, INFO, WARNING, ERROR)
    :return: None
    """
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format='[%(asctime)s] %(name)s %(levelname)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

