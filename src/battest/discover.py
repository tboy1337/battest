"""Discover battest fixture files."""

from __future__ import annotations

from pathlib import Path

from battest.constants import DISCOVERY_SKIP_DIR_NAMES
from battest.logging_config import get_logger
from battest.models import Case
from battest.schema import SchemaError, load_cases_from_path
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


def iter_fixture_files(root: Path) -> list[Path]:
    """Return sorted fixture paths under root."""
    if root.is_file():
        LOGGER.debug("discovery target is file %s", root)
        return [root]
    if not root.is_dir():
        raise SchemaError(f"discovery path does not exist: {root}")
    found: list[Path] = []
    for current_dir, dir_names, file_names in root.walk():
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
    unique = sorted(set(found))
    LOGGER.info("discovered %s fixture file(s) under %s", len(unique), root)
    return unique


def discover_cases(
    root: Path,
    *,
    include_spec_exec: bool = False,
    repo_root: Path | None = None,
) -> list[Case]:
    """Load every fixture under root, optionally including batch-spec corpus/exec."""
    cases: list[Case] = []
    for fixture in iter_fixture_files(root):
        loaded = load_cases_from_path(fixture)
        LOGGER.debug("loaded %s cases from %s", len(loaded), fixture)
        cases.extend(loaded)
    if include_spec_exec:
        corpus = spec_exec_corpus_path(repo_root)
        if corpus is not None and corpus.resolve() != root.resolve():
            LOGGER.info("including spec exec corpus %s", corpus)
            for fixture in iter_fixture_files(corpus):
                cases.extend(load_cases_from_path(fixture))
        else:
            LOGGER.info("spec exec corpus absent or already included")
    LOGGER.info("total cases discovered: %s", len(cases))
    return cases
