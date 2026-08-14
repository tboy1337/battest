"""Logging helpers for battest."""

from __future__ import annotations

import logging
import sys

LOGGER_NAME = "battest"
_FORMAT = "%(asctime)s [%(levelname)8s] %(name)s: %(message)s"


def configure_logging(level: int = logging.INFO) -> logging.Logger:
    """Configure the battest logger once and return it."""
    logger = logging.getLogger(LOGGER_NAME)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter(_FORMAT))
        logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False
    logger.debug("logging configured at level %s", level)
    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a child logger under the battest namespace."""
    if name is None or name == LOGGER_NAME:
        return logging.getLogger(LOGGER_NAME)
    if name.startswith(LOGGER_NAME + "."):
        return logging.getLogger(name)
    return logging.getLogger(f"{LOGGER_NAME}.{name}")
