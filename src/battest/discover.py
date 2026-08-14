"""Discover battest fixture files."""

from __future__ import annotations

import os
from pathlib import Path

from battest.constants import DISCOVERY_SKIP_DIR_NAMES
from battest.logging_config import get_logger
from battest.models import Case
from battest.schema import (
    SchemaError,
    fixture_stem,
    load_cases_from_path,
    relative_case_id,
)
from battest.spec import spec_exec_corpus_path

LOGGER = get_logger("discover")


def default_root(cwd: Path | None = None) -> Path:
    """Return ./tests when it exists, otherwise the current directory."""
    base = Path.cwd() if cwd is None else cwd
    tests_dir = base / "tests"
    if tests_dir.is_dir():
        LOGGER.info("default discovery root %s", tests_dir)
        return tests_dir
    LOGGER.info("default discovery root %s", base)
    return base


def _should_skip_dir(path: Path) -> bool:
    return path.name in DISCOVERY_SKIP_DIR_NAMES


def _log_walk_error(exc: OSError) -> None:
    LOGGER.warning("skipping unreadable directory during discovery: %s", exc)


def iter_fixture_files(root: Path) -> list[Path]:
    """Return sorted fixture paths under root."""
    if root.is_file():
        LOGGER.debug("discovery target is file %s", root)
        return [root]
    if not root.is_dir():
        raise SchemaError(f"discovery path does not exist: {root}")
    found: list[Path] = []
    try:
        LOGGER.debug("walking discovery path %s", root)
        walker = os.walk(root, onerror=_log_walk_error)
    except OSError as exc:
        LOGGER.error("cannot walk discovery path %s: %s", root, exc)
        return []
    try:
        for dirpath, dir_names, file_names in walker:
            current_dir = Path(dirpath)
            dir_names[:] = [
                name for name in dir_names if name not in DISCOVERY_SKIP_DIR_NAMES
            ]
            if _should_skip_dir(current_dir):
                continue
            for file_name in file_names:
                path = current_dir / file_name
                if file_name.endswith(".battest.yaml"):
                    found.append(path)
                    continue
                if file_name == "expect.yaml" and (current_dir / "input.cmd").is_file():
                    found.append(path)
    except OSError as exc:
        LOGGER.error("cannot walk discovery path %s: %s", root, exc)
    unique = sorted(set(found))
    LOGGER.info("discovered %s fixture file(s) under %s", len(unique), root)
    return unique


def _cases_from_root(root: Path) -> list[Case]:
    cases: list[Case] = []
    single_file = root.is_file()
    discovery_root = root.parent if single_file else root
    for fixture in iter_fixture_files(root):
        base_case_id = (
            fixture_stem(fixture)
            if single_file
            else relative_case_id(fixture, discovery_root)
        )
        loaded = load_cases_from_path(fixture, base_case_id=base_case_id)
        LOGGER.debug("loaded %s cases from %s", len(loaded), fixture)
        cases.extend(loaded)
    return cases


def _ensure_unique_case_ids(cases: list[Case]) -> None:
    seen: dict[str, Path] = {}
    for case in cases:
        previous = seen.get(case.case_id)
        if previous is not None:
            raise SchemaError(
                f"duplicate case id {case.case_id!r}: {previous} and {case.source_path}"
            )
        seen[case.case_id] = case.source_path


def discover_cases(
    root: Path,
    *,
    include_spec_exec: bool = False,
    repo_root: Path | None = None,
) -> list[Case]:
    """Load every fixture under root, optionally including batch-spec corpus/exec."""
    cases = _cases_from_root(root)
    if include_spec_exec:
        corpus = spec_exec_corpus_path(repo_root)
        if corpus is not None and corpus.resolve() != root.resolve():
            LOGGER.info("including spec exec corpus %s", corpus)
            cases.extend(_cases_from_root(corpus))
        else:
            LOGGER.info("spec exec corpus absent or already included")
    _ensure_unique_case_ids(cases)
    LOGGER.info("total cases discovered: %s", len(cases))
    return cases
