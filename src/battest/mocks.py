"""PATH-based stubs for external Windows commands."""

from __future__ import annotations

from pathlib import Path
import re
import shutil

from battest.constants import (
    CALL_LOG_DIR,
    INTERNAL_DESTRUCTIVE_VERBS,
    MOCK_DIR_NAME,
    SAFE_DEFAULT_COMMANDS,
)
from battest.logging_config import get_logger
from battest.models import MockSpec, normalize_command_name
from battest.spec import load_catalog, packaged_data_path

LOGGER = get_logger("mocks")

_ABS_PATH_RE = re.compile(
    r"\b(?P<verb>"
    + "|".join(re.escape(verb) for verb in INTERNAL_DESTRUCTIVE_VERBS)
    + r")\b(?:\s+/[^\s&|<>\"]+)*\s+(?:"
    r"\"(?P<quoted>(?:[A-Za-z]:[\\/]|\\\\)[^\"]+)\""
    r"|"
    r"(?P<unquoted>(?:[A-Za-z]:[\\/]|\\\\)[^\s&|<>\"]+)"
    r")",
    re.IGNORECASE,
)


class MockError(RuntimeError):
    """Raised when an executable stub cannot be produced."""


def stub_executable() -> Path:
    """Return the packaged battest stub executable."""
    path = packaged_data_path("battest_stub.exe")
    if not path.is_file():
        raise MockError(
            "battest_stub.exe is missing; build it with "
            "python scripts/build_stub.py (requires Rust/cargo)"
        )
    return path


def warn_internal_absolute_paths(script_text: str) -> list[str]:
    """Return warnings for destructive internals used with absolute paths."""
    warnings: list[str] = []
    for match in _ABS_PATH_RE.finditer(script_text):
        verb = match.group("verb")
        target = match.group("quoted") or match.group("unquoted")
        if not target:
            continue
        message = (
            f"internal command '{verb}' targets absolute path '{target}' "
            "and cannot be PATH-mocked; run that case in a disposable VM"
        )
        LOGGER.warning("%s", message)
        warnings.append(message)
    return warnings


def effective_mocks(
    case_mocks: dict[str, MockSpec],
    allow: list[str],
    safe_defaults: bool,
) -> dict[str, MockSpec]:
    """Merge case mocks with optional deny-list stubs."""
    merged = {name.lower(): spec for name, spec in case_mocks.items()}
    allowed = {name.lower() for name in allow}
    if not safe_defaults:
        LOGGER.debug("safe-defaults disabled; mocks=%s", sorted(merged.keys()))
        return merged
    catalog = load_catalog()
    for name in SAFE_DEFAULT_COMMANDS:
        lowered = name.lower()
        if lowered in merged or lowered in allowed:
            continue
        if catalog.is_internal(lowered):
            LOGGER.debug("skipping internal safe-default %s", lowered)
            continue
        LOGGER.info("applying safe-default stub for %s", lowered)
        merged[lowered] = MockSpec(
            exit_code=1,
            stdout="",
            stderr=f"battest: blocked by --safe-defaults: {lowered}\r\n",
            record_calls=True,
        )
    return merged


def _confined_mock_path(mock_dir: Path, command: str, filename: str) -> Path:
    """Join filename under mock_dir and reject path separators or escapes."""
    if Path(filename).name != filename:
        LOGGER.error("mock artifact %r is not a plain file name", filename)
        raise MockError(f"mock artifact {filename!r} is not a plain file name")
    path = (mock_dir / filename).resolve()
    try:
        path.relative_to(mock_dir.resolve())
    except ValueError as exc:
        LOGGER.error("mock command %r escapes mock directory", command)
        raise MockError(
            f"mock command {command!r} would write outside the mock directory"
        ) from exc
    return path


def write_mock_tree(root: Path, mocks: dict[str, MockSpec]) -> Path:
    """Copy exe stubs and sidecar files into root; return the mock directory."""
    mock_dir = root / MOCK_DIR_NAME
    call_dir = mock_dir / CALL_LOG_DIR
    call_dir.mkdir(parents=True, exist_ok=True)
    catalog = load_catalog()
    source_exe = stub_executable()
    for name, spec in mocks.items():
        try:
            lowered = normalize_command_name(name)
        except ValueError as exc:
            raise MockError(str(exc)) from exc
        if catalog.is_internal(lowered):
            LOGGER.error("refusing to PATH-mock internal command %s", lowered)
            raise MockError(
                f"command '{lowered}' is a cmd.exe internal and cannot be PATH-mocked"
            )
        stub_path = _confined_mock_path(mock_dir, lowered, f"{lowered}.exe")
        shutil.copyfile(source_exe, stub_path)
        _confined_mock_path(mock_dir, lowered, f"{lowered}.exit").write_text(
            str(spec.exit_code), encoding="utf-8"
        )
        if spec.record_calls:
            _confined_mock_path(call_dir, lowered, f"{lowered}.log").write_text(
                "", encoding="utf-8"
            )
        if spec.stdout:
            _confined_mock_path(mock_dir, lowered, f"{lowered}.stdout").write_text(
                spec.stdout, encoding="utf-8"
            )
        if spec.stderr:
            _confined_mock_path(mock_dir, lowered, f"{lowered}.stderr").write_text(
                spec.stderr, encoding="utf-8"
            )
        LOGGER.debug(
            "wrote mock stub %s exit=%s stdout_len=%s stderr_len=%s",
            stub_path,
            spec.exit_code,
            len(spec.stdout),
            len(spec.stderr),
        )
    return mock_dir


def read_call_logs(mock_dir: Path) -> dict[str, list[str]]:
    """Read recorded argv lines per mocked command."""
    call_dir = mock_dir / CALL_LOG_DIR
    recorded: dict[str, list[str]] = {}
    if not call_dir.is_dir():
        return recorded
    for log_path in sorted(call_dir.glob("*.log")):
        try:
            lines = [
                line.rstrip("\r")
                for line in log_path.read_text(
                    encoding="utf-8", errors="replace"
                ).splitlines()
            ]
        except OSError as exc:
            LOGGER.error("cannot read call log %s: %s", log_path, exc)
            raise MockError(f"cannot read call log {log_path}: {exc}") from exc
        recorded[log_path.stem] = lines
        LOGGER.debug("call log %s lines=%s", log_path.stem, len(lines))
    return recorded
