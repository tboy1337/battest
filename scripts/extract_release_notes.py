#!/usr/bin/env python3
"""Print the latest versioned release-notes section from docs/CHANGELOG.md."""

from __future__ import annotations

import logging
from pathlib import Path
import re
import sys

LOGGER = logging.getLogger("extract_release_notes")
_CHANGELOG = Path(__file__).resolve().parent.parent / "docs" / "CHANGELOG.md"
_SECTION_RE = re.compile(r"^## \[(?P<version>[^\]]+)\].*$", re.MULTILINE)


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)8s] %(name)s: %(message)s",
    )


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
    start_index = matches.index(selected)
    start = selected.start()
    if start_index + 1 < len(matches):
        end = matches[start_index + 1].start()
    else:
        end = len(text)
    section = text[start:end].strip()
    body = "\n".join(section.splitlines()[1:]).strip()
    if not section or not body:
        LOGGER.error("latest changelog section is empty")
        raise SystemExit("Latest changelog section is empty")
    LOGGER.info(
        "extracted section version=%s bytes=%s",
        selected.group("version"),
        len(section),
    )
    return section


def main() -> None:
    """Write the latest versioned changelog section to stdout."""
    _configure_logging()
    sys.stdout.write(extract_latest_section(_CHANGELOG))


if __name__ == "__main__":
    main()
