"""Package version resolution."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import tomllib

__author__ = "tboy1337"
__license__ = "AGPL-3.0-or-later"

_PACKAGE_NAME = "battest"


def _pyproject_path() -> Path:
    """Return pyproject.toml for a source checkout."""
    return Path(__file__).resolve().parent.parent.parent / "pyproject.toml"


def _fallback_version() -> str:
    """Read version from pyproject.toml when the package is not installed."""
    pyproject = _pyproject_path()
    if not pyproject.is_file():
        return "unknown"
    try:
        loaded = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError):
        return "unknown"
    project = loaded.get("project")
    if not isinstance(project, dict):
        return "unknown"
    value = project.get("version")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return "unknown"


def get_version() -> str:
    """Return the installed package version, falling back to pyproject.toml."""
    try:
        return version(_PACKAGE_NAME)
    except PackageNotFoundError:
        return _fallback_version()


__version__ = get_version()
