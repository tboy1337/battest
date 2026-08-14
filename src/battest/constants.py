"""Shared constants for battest."""

from __future__ import annotations

SAFE_DEFAULT_COMMANDS: tuple[str, ...] = (
    "bcdedit",
    "cipher",
    "diskpart",
    "format",
    "netsh",
    "reg",
    "shutdown",
    "takeown",
    "wmic",
)

INTERNAL_DESTRUCTIVE_VERBS: tuple[str, ...] = (
    "copy",
    "del",
    "erase",
    "move",
    "rd",
    "ren",
    "rename",
    "rmdir",
)

BATTEST_PREFIX = "BATTEST_"
ENV_DUMP_NAME = "_battest_env.txt"
WRAPPER_NAME = "_battest_wrapper.cmd"
MOCK_DIR_NAME = "_battest_mocks"
CALL_LOG_DIR = "_calls"
HELPER_NAMES: frozenset[str] = frozenset({ENV_DUMP_NAME, WRAPPER_NAME, MOCK_DIR_NAME})

DISCOVERY_SKIP_DIR_NAMES: frozenset[str] = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "htmlcov",
        "target",
        "vendor",
        "venv",
    }
)

DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_MAX_DIFF = 2000
KILL_DRAIN_TIMEOUT_SECONDS = 5.0
VALID_MODIFIER_CHARS = "nxfpdstaz"
PERCENT_TILDE_PATTERN = r"%~([A-Za-z$]*)(\d|\*)"
