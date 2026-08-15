#!/usr/bin/env python3
"""Print [project].version from pyproject.toml at a git revision."""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
import tomllib

LOGGER = logging.getLogger("read_git_pyproject_version")


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)8s] %(name)s: %(message)s",
    )


def git_pyproject_text(revision: str) -> str:
    """Return UTF-8 pyproject.toml contents at revision.

    subprocess.check_output returns bytes unless encoding is set. tomllib.loads
    requires str, so this always decodes as UTF-8.
    """
    spec = f"{revision}:pyproject.toml"
    LOGGER.info("reading git object spec=%s", spec)
    try:
        text = subprocess.check_output(
            ["git", "show", spec],
            encoding="utf-8",
        )
    except (OSError, subprocess.CalledProcessError, UnicodeError) as exc:
        LOGGER.error("cannot read %s: %s", spec, exc)
        raise SystemExit(f"Cannot read {spec}: {exc}") from exc
    LOGGER.info("read git object spec=%s bytes=%s", spec, len(text.encode("utf-8")))
    return text


def version_from_toml(text: str, source: str) -> str:
    """Return [project].version from a TOML document string."""
    LOGGER.info("parsing project version source=%s", source)
    try:
        loaded = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        LOGGER.error("invalid TOML from %s: %s", source, exc)
        raise SystemExit(f"Could not parse {source}: {exc}") from exc
    project = loaded.get("project")
    if not isinstance(project, dict):
        LOGGER.error("%s missing [project] table", source)
        raise SystemExit(f"Could not read previous version from {source}")
    value = project.get("version")
    if not isinstance(value, str) or not value.strip():
        LOGGER.error("%s missing project.version", source)
        raise SystemExit(f"Could not read previous version from {source}")
    version = value.strip()
    LOGGER.info("version=%s source=%s", version, source)
    return version


def read_git_project_version(revision: str) -> str:
    """Return [project].version from pyproject.toml at a git revision."""
    spec = f"{revision}:pyproject.toml"
    return version_from_toml(git_pyproject_text(revision), spec)


def main(argv: list[str] | None = None) -> None:
    """Write the git revision's project version to stdout."""
    _configure_logging()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "revision",
        help="Git revision whose pyproject.toml version should be printed",
    )
    args = parser.parse_args(argv)
    sys.stdout.write(read_git_project_version(args.revision))
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
