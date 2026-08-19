"""Bounded regex evaluation so fixture matchers cannot hang the runner."""

from __future__ import annotations

from multiprocessing import Pipe, Process
from multiprocessing.connection import Connection
import re

from battest.constants import MAX_REGEX_MATCH_SECONDS
from battest.logging_config import get_logger

LOGGER = get_logger("retimeout")


class RegexTimeoutError(RuntimeError):
    """Raised when a fixture regex exceeds the match time bound."""


def _search_worker(pattern: str, text: str, conn: Connection) -> None:
    try:
        matched = re.search(pattern, text, re.MULTILINE) is not None
        conn.send(("ok", matched))
    except re.error as exc:
        conn.send(("error", str(exc)))
    except Exception as exc:  # pylint: disable=broad-exception-caught
        conn.send(("error", str(exc)))
    finally:
        conn.close()


def search_with_timeout(
    pattern: str,
    text: str,
    timeout_seconds: float = MAX_REGEX_MATCH_SECONDS,
) -> bool:
    """Return whether pattern matches text, killing the worker on timeout."""
    LOGGER.debug(
        "regex search pattern_len=%s text_len=%s timeout=%s",
        len(pattern),
        len(text),
        timeout_seconds,
    )
    parent, child = Pipe(duplex=False)
    worker = Process(target=_search_worker, args=(pattern, text, child), daemon=True)
    worker.start()
    child.close()
    try:
        if parent.poll(timeout_seconds):
            status, payload = parent.recv()
            worker.join(timeout=1.0)
            if status == "error":
                raise re.error(str(payload))
            return bool(payload)
        LOGGER.error("regex match timed out after %s seconds", timeout_seconds)
        raise RegexTimeoutError(f"regex match exceeded {timeout_seconds} seconds")
    finally:
        if worker.is_alive():
            worker.terminate()
            worker.join(timeout=1.0)
        parent.close()
