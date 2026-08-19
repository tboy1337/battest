"""Parse cmd.exe `set` dumps into environment mappings."""

from __future__ import annotations

from battest.constants import BATTEST_RC_NAME
from battest.logging_config import get_logger

LOGGER = get_logger("envsnap")


def parse_set_output(text: str) -> dict[str, str]:
    """Parse `set` command output into a name-to-value mapping."""
    env: dict[str, str] = {}
    for raw_line in text.split("\n"):
        line = raw_line.rstrip("\r")
        if not line or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if not name:
            continue
        env[name] = value
    LOGGER.debug("parsed %s environment variables from set dump", len(env))
    return env


def filter_helper_vars(env: dict[str, str]) -> dict[str, str]:
    """Drop wrapper-owned BATTEST_RC from an env snapshot."""
    filtered = {
        name: value for name, value in env.items() if name.upper() != BATTEST_RC_NAME
    }
    LOGGER.debug("filtered helper env vars kept=%s", len(filtered))
    return filtered
