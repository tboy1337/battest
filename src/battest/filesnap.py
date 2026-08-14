"""Filesystem snapshots of an isolated working directory."""

from __future__ import annotations

from pathlib import Path

from battest.constants import HELPER_NAMES
from battest.logging_config import get_logger

LOGGER = get_logger("filesnap")


def snapshot_files(root: Path) -> dict[str, bytes]:
    """Return relative POSIX paths mapped to file bytes under root."""
    snapshot: dict[str, bytes] = {}
    if not root.is_dir():
        LOGGER.warning("snapshot root does not exist: %s", root)
        return snapshot
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        parts = relative.parts
        if not parts:
            continue
        if parts[0] in HELPER_NAMES:
            continue
        if not path.is_file():
            continue
        key = relative.as_posix()
        try:
            snapshot[key] = path.read_bytes()
        except OSError as exc:
            LOGGER.error("failed to read %s: %s", path, exc)
    LOGGER.info("file snapshot root=%s files=%s", root, len(snapshot))
    return snapshot


def file_text(root: Path, relative: str) -> str | None:
    """Return decoded text for a relative path, or None if missing."""
    path = root / relative
    if not path.is_file():
        LOGGER.debug("file missing: %s", path)
        return None
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        LOGGER.error("failed to read text %s: %s", path, exc)
        return None
