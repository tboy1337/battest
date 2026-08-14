"""Package version resolution."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import sys
import tomllib

from battest.logging_config import get_logger

__author__ = "tboy1337"
__license__ = "AGPL-3.0-or-later"

_PACKAGE_NAME = "battest"
LOGGER = get_logger("version")


def _pyproject_path() -> Path:
    """Return pyproject.toml for source trees or PyInstaller bundles."""
    frozen_raw: object = getattr(sys, "frozen", False)
    if frozen_raw is True:
        meipass_raw: object = getattr(sys, "_MEIPASS", "")
        if isinstance(meipass_raw, str) and meipass_raw:
            bundled = Path(meipass_raw) / "pyproject.toml"
            LOGGER.debug("frozen pyproject candidate path=%s", bundled)
            if bundled.is_file():
                return bundled
    return Path(__file__).resolve().parent.parent.parent / "pyproject.toml"


def _fallback_version() -> str:
    """Read version from pyproject.toml when the package is not installed."""
    pyproject = _pyproject_path()
    if not pyproject.is_file():
        LOGGER.debug("pyproject missing path=%s", pyproject)
        return "unknown"
    try:
        loaded = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        LOGGER.warning(
            "failed to parse pyproject.toml path=%s error=%s", pyproject, exc
        )
        return "unknown"
    project = loaded.get("project")
    if not isinstance(project, dict):
        LOGGER.warning("pyproject.toml missing [project] table path=%s", pyproject)
        return "unknown"
    value = project.get("version")
    if isinstance(value, str) and value.strip():
        LOGGER.debug("pyproject version=%s path=%s", value.strip(), pyproject)
        return value.strip()
    LOGGER.warning("pyproject.toml missing project.version path=%s", pyproject)
    return "unknown"


def get_version() -> str:
    """Return the package version, preferring pyproject.toml when it is present."""
    if _pyproject_path().is_file():
        pyproject_version = _fallback_version()
        if pyproject_version != "unknown":
            LOGGER.debug("using pyproject version=%s", pyproject_version)
            return pyproject_version
    try:
        installed = version(_PACKAGE_NAME)
    except PackageNotFoundError:
        LOGGER.debug("package metadata missing; falling back to pyproject")
        return _fallback_version()
    LOGGER.debug("using installed metadata version=%s", installed)
    return installed


__version__ = get_version()
