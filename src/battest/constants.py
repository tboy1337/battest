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
BATTEST_RC_NAME = "BATTEST_RC"
ENV_DUMP_NAME = "_battest_env.txt"
CWD_DUMP_NAME = "_battest_cd.txt"
WRAPPER_NAME = "_battest_wrapper.cmd"
MOCK_DIR_NAME = "_battest_mocks"
CALL_LOG_DIR = "_calls"

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
TEARDOWN_MIN_SECONDS = 5.0
MAX_CAPTURE_BYTES = 10 * 1024 * 1024
MAX_REGEX_MATCH_SECONDS = 2.0
MAX_JOBS = 256
CMD_UNSAFE_ARG_CHARS = frozenset('"&|<>^\r\n')
MAX_FIXTURE_BYTES = 1_048_576
MAX_YAML_ALIASES = 256
COMMAND_NAME_MAX_LENGTH = 63
COMMAND_NAME_PATTERN = (
    rf"^[a-z0-9](?:[a-z0-9._-]{{0,{COMMAND_NAME_MAX_LENGTH - 2}}}[a-z0-9])?$"
)
MAX_REGEX_PATTERN_LENGTH = 512
VALID_MODIFIER_CHARS = "nxfpdstaz"
WINDOWS_RESERVED_DEVICE_NAMES: frozenset[str] = frozenset(
    {
        "aux",
        "clock$",
        "con",
        "conin$",
        "conout$",
        "nul",
        "prn",
        *(f"com{index}" for index in range(1, 10)),
        *(f"lpt{index}" for index in range(1, 10)),
    }
)
PERCENT_TILDE_PATTERN = r"%~([A-Za-z$]*)(\d|\*)"
