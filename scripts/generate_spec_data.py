#!/usr/bin/env python3
"""Copy batch-spec catalogs into the battest package data directory."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
import shutil
import sys

LOGGER = logging.getLogger("generate_spec_data")

REPO_ROOT = Path(__file__).resolve().parent.parent
VENDOR_DATA = REPO_ROOT / "vendor" / "batch-spec" / "data"
PACKAGE_DATA = REPO_ROOT / "src" / "battest" / "data"
CATALOG_NAMES = ("commands.yaml", "expansion.yaml")
SCHEMA_NAME = "battest-expect.schema.json"
SCHEMA_SOURCE = REPO_ROOT / "schema" / SCHEMA_NAME


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)8s] %(name)s: %(message)s",
    )


def catalog_sources() -> tuple[Path, ...]:
    """Return vendor catalog paths, raising if the submodule is missing."""
    if not VENDOR_DATA.is_dir():
        raise FileNotFoundError(
            "vendor/batch-spec/data is missing; initialize the git submodule"
        )
    missing = [name for name in CATALOG_NAMES if not (VENDOR_DATA / name).is_file()]
    if missing:
        raise FileNotFoundError("vendor catalogs missing: " + ", ".join(missing))
    return tuple(VENDOR_DATA / name for name in CATALOG_NAMES)


def copy_catalogs() -> list[Path]:
    """Copy vendor catalogs and JSON Schema into src/battest/data."""
    PACKAGE_DATA.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for source in catalog_sources():
        destination = PACKAGE_DATA / source.name
        shutil.copyfile(source, destination)
        LOGGER.info("copied %s -> %s", source, destination)
        written.append(destination)
    if not SCHEMA_SOURCE.is_file():
        raise FileNotFoundError(f"JSON Schema missing: {SCHEMA_SOURCE}")
    schema_dest = PACKAGE_DATA / SCHEMA_NAME
    shutil.copyfile(SCHEMA_SOURCE, schema_dest)
    LOGGER.info("copied %s -> %s", SCHEMA_SOURCE, schema_dest)
    written.append(schema_dest)
    return written


def catalogs_match() -> bool:
    """Return True when packaged catalogs match the vendor submodule."""
    matched = True
    for source in catalog_sources():
        destination = PACKAGE_DATA / source.name
        if not destination.is_file():
            LOGGER.error("packaged catalog missing: %s", destination)
            matched = False
            continue
        if source.read_bytes() != destination.read_bytes():
            LOGGER.error("catalog drift: %s does not match %s", destination, source)
            matched = False
        else:
            LOGGER.info("catalog ok: %s", destination.name)
    schema_dest = PACKAGE_DATA / SCHEMA_NAME
    if not SCHEMA_SOURCE.is_file() or not schema_dest.is_file():
        LOGGER.error("JSON Schema missing at %s or %s", SCHEMA_SOURCE, schema_dest)
        matched = False
    elif SCHEMA_SOURCE.read_bytes() != schema_dest.read_bytes():
        LOGGER.error("schema drift: %s does not match %s", schema_dest, SCHEMA_SOURCE)
        matched = False
    else:
        LOGGER.info("schema ok: %s", SCHEMA_NAME)
    return matched


def main(argv: list[str] | None = None) -> int:
    """Generate or check packaged batch-spec catalogs."""
    _configure_logging()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail if packaged catalogs differ from vendor/batch-spec",
    )
    args = parser.parse_args(argv)
    LOGGER.info(
        "mode=%s vendor=%s dest=%s",
        "check" if args.check else "copy",
        VENDOR_DATA,
        PACKAGE_DATA,
    )
    try:
        if args.check:
            return 0 if catalogs_match() else 1
        copy_catalogs()
        return 0
    except FileNotFoundError as exc:
        LOGGER.error("%s", exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
