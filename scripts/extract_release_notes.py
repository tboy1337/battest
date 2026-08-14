#!/usr/bin/env python3
"""Print the changelog section that matches the project version."""

from __future__ import annotations

import logging
from pathlib import Path
import re
import sys
import tomllib

LOGGER = logging.getLogger("extract_release_notes")
_CHANGELOG = Path(__file__).resolve().parent.parent / "docs" / "CHANGELOG.md"
_PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"
_SECTION_RE = re.compile(r"^## \[(?P<version>[^\]]+)\].*$", re.MULTILINE)


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)8s] %(name)s: %(message)s",
    )


def project_version(pyproject_path: Path = _PYPROJECT) -> str:
    """Return [project].version from pyproject.toml."""
    LOGGER.info("reading project version path=%s", pyproject_path)
    try:
        loaded = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        LOGGER.error("cannot read pyproject.toml: %s", exc)
        raise SystemExit(f"Cannot read {pyproject_path}: {exc}") from exc
    project = loaded.get("project")
    if not isinstance(project, dict):
        LOGGER.error("pyproject.toml missing [project] table")
        raise SystemExit(f"Missing [project] table in {pyproject_path}")
    value = project.get("version")
    if not isinstance(value, str) or not value.strip():
        LOGGER.error("pyproject.toml missing project.version")
        raise SystemExit(f"Missing project.version in {pyproject_path}")
    version = value.strip()
    LOGGER.info("project version=%s", version)
    return version


def _section_body(
    text: str, matches: list[re.Match[str]], selected: re.Match[str]
) -> str:
    start_index = matches.index(selected)
    start = selected.start()
    if start_index + 1 < len(matches):
        end = matches[start_index + 1].start()
    else:
        end = len(text)
    section = text[start:end].strip()
    body = "\n".join(section.splitlines()[1:]).strip()
    if not section or not body:
        LOGGER.error("changelog section %s is empty", selected.group("version"))
        raise SystemExit(f"Changelog section [{selected.group('version')}] is empty")
    return section


def extract_latest_section(changelog_path: Path = _CHANGELOG) -> str:
    """Return markdown for the most recent versioned changelog block."""
    LOGGER.info("reading changelog path=%s", changelog_path)
    text = changelog_path.read_text(encoding="utf-8")
    matches = list(_SECTION_RE.finditer(text))
    versioned = [
        match
        for match in matches
        if match.group("version").strip().lower() != "unreleased"
    ]
    if not versioned:
        LOGGER.error("no version sections in %s", changelog_path)
        raise SystemExit(f"No version sections found in {changelog_path}")

    selected = versioned[0]
    section = _section_body(text, matches, selected)
    LOGGER.info(
        "extracted latest section version=%s bytes=%s",
        selected.group("version"),
        len(section),
    )
    return section


def extract_section_for_version(changelog_path: Path, version: str) -> str:
    """Return the changelog section whose heading matches version."""
    LOGGER.info("reading changelog path=%s version=%s", changelog_path, version)
    text = changelog_path.read_text(encoding="utf-8")
    matches = list(_SECTION_RE.finditer(text))
    selected = next(
        (match for match in matches if match.group("version").strip() == version),
        None,
    )
    if selected is None:
        LOGGER.error("changelog missing section [%s]", version)
        raise SystemExit(f"No changelog section [{version}] found in {changelog_path}")
    section = _section_body(text, matches, selected)
    LOGGER.info(
        "extracted section version=%s bytes=%s",
        selected.group("version"),
        len(section),
    )
    return section


def main() -> None:
    """Write the changelog section for the current project version to stdout."""
    _configure_logging()
    version = project_version(_PYPROJECT)
    sys.stdout.write(extract_section_for_version(_CHANGELOG, version))


if __name__ == "__main__":
    main()
