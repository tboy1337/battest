"""Tests for logging configuration."""

from __future__ import annotations

import logging
import sys

from battest.logging_config import configure_logging, get_logger


def test_configure_logging_idempotent() -> None:
    first = configure_logging(logging.DEBUG)
    second = configure_logging(logging.INFO)
    assert first is second
    assert first.level == logging.INFO
    child = get_logger("cli")
    assert child.name == "battest.cli"
    assert get_logger("battest").name == "battest"
    assert get_logger("battest.engine").name == "battest.engine"
    assert any(isinstance(handler, logging.NullHandler) for handler in first.handlers)
    streams = [
        handler
        for handler in first.handlers
        if isinstance(handler, logging.StreamHandler)
        and getattr(handler, "stream", None) is sys.stderr
    ]
    assert len(streams) == 1
