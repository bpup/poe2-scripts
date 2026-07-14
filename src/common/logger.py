"""Structured logging for PoE2 multi-client auto-follow."""

import logging
import sys
from pathlib import Path
from typing import Optional

ROOT_LOGGER_NAME = "poe2_follow"


def setup_logging(level: int = logging.INFO, log_file: Optional[str] = None) -> None:
    """Configure root logger with console and optional file output.

    Args:
        level: Log level for console output (default: INFO).
        log_file: Optional file path for persistent debug logs.
    """
    root = logging.getLogger(ROOT_LOGGER_NAME)
    root.setLevel(logging.DEBUG)  # root is always DEBUG; handlers filter

    if root.handlers:
        return

    fmt = logging.Formatter(
        "[%(asctime)s] [%(levelname)7s] [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    console.setFormatter(fmt)
    root.addHandler(console)

    if log_file:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(str(path), encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)


def get_logger(name: str) -> logging.Logger:
    """Get a child logger under the poe2_follow namespace."""
    return logging.getLogger(f"{ROOT_LOGGER_NAME}.{name}")
