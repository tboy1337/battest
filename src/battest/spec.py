"""Load batch-spec command and expansion catalogs."""

from __future__ import annotations

from functools import lru_cache
from importlib import resources
from pathlib import Path
import re
import shutil
import tempfile
import threading
from typing import Mapping

from battest.constants import PERCENT_TILDE_PATTERN, VALID_MODIFIER_CHARS
from battest.logging_config import get_logger

LOGGER = get_logger("spec")
_TILDE_RE = re.compile(PERCENT_TILDE_PATTERN, re.IGNORECASE)
_EXTRACT_LOCK = threading.Lock()
_EXTRACT_ROOT: tempfile.TemporaryDirectory[str] | None = None
_EXTRACTED: dict[str, Path] = {}


class SpecCatalog:
    """In-memory view of batch-spec command and expansion catalogs."""

    def __init__(
        self,
        commands: Mapping[str, object],
        expansion: Mapping[str, object],
    ) -> None:
        self._commands = dict(commands)
        self._expansion = dict(expansion)
        self._deprecated = _string_key_set(commands.get("deprecated_commands"))
        self._removed = _string_key_set(commands.get("removed_commands"))
        self._internal = _string_list_set(commands.get("cmd_internal_commands"))
        self._stock = _string_list_set(commands.get("stock_windows_utilities"))
        modifier_chars = expansion.get("valid_modifier_chars")
        if isinstance(modifier_chars, str) and modifier_chars:
            self._modifier_chars = frozenset(modifier_chars.lower())
        else:
            self._modifier_chars = frozenset(VALID_MODIFIER_CHARS)

    @property
    def deprecated_commands(self) -> frozenset[str]:
        """Command names marked deprecated in batch-spec."""
        return self._deprecated

    @property
    def removed_commands(self) -> frozenset[str]:
        """Command names marked removed in batch-spec."""
        return self._removed

    @property
    def internal_commands(self) -> frozenset[str]:
        """cmd.exe internal verbs that cannot be PATH-shadowed."""
        return self._internal

    @property
    def stock_utilities(self) -> frozenset[str]:
        """Stock Windows utilities that can be PATH-shadowed."""
        return self._stock

    def is_internal(self, name: str) -> bool:
        """Return True if name is a cmd.exe internal."""
        return name.lower() in self._internal

    def is_deprecated(self, name: str) -> bool:
        """Return True if name is deprecated."""
        return name.lower() in self._deprecated

    def is_removed(self, name: str) -> bool:
        """Return True if name is removed from modern Windows."""
        return name.lower() in self._removed

    def invalid_tilde_forms(self, text: str) -> list[str]:
        """Return %~ forms in text that use letters outside valid_modifier_chars."""
        found: list[str] = []
        for match in _TILDE_RE.finditer(text):
            modifiers = match.group(1) or ""
            parameter = match.group(2) or ""
            token = match.group(0)
            if parameter == "*":
                found.append(token)
                continue
            letters = [char.lower() for char in modifiers if char != "$"]
            if any(char not in self._modifier_chars for char in letters):
                found.append(token)
        LOGGER.debug("tilde scan text_len=%s invalid=%s", len(text), found)
        return found


def _string_key_set(value: object) -> frozenset[str]:
    if not isinstance(value, dict):
        return frozenset()
    return frozenset(str(key).lower() for key in value.keys())


def _string_list_set(value: object) -> frozenset[str]:
    if not isinstance(value, list):
        return frozenset()
    return frozenset(str(item).lower() for item in value)


def _load_yaml_mapping(path: Path) -> dict[str, object]:
    """Parse packaged catalog YAML with the same alias and size bounds as fixtures.

    Inline import avoids a circular import: schema.py loads catalogs via
    spec.load_catalog at module level.
    """
    LOGGER.debug("loading yaml mapping from %s", path)
    # schema.py imports load_catalog at module level; keep this import lazy.
    from battest.schema import (  # isort: skip  # pylint: disable=import-outside-toplevel
        SchemaError,
        load_yaml_mapping,
    )

    try:
        loaded = load_yaml_mapping(path)
    except SchemaError as exc:
        raise ValueError(str(exc)) from exc
    return {str(key): value for key, value in loaded.items()}


def packaged_data_path(name: str) -> Path:
    """Return a filesystem path to a packaged data file that outlives this call."""
    adjacent = Path(__file__).resolve().parent / "data" / name
    if adjacent.is_file():
        LOGGER.debug("packaged data adjacent path=%s", adjacent)
        return adjacent
    with _EXTRACT_LOCK:
        cached = _EXTRACTED.get(name)
        if cached is not None and cached.is_file():
            LOGGER.debug("packaged data cached path=%s", cached)
            return cached
        traversable = resources.files("battest") / "data" / name
        with resources.as_file(traversable) as path:
            source = Path(path)
            # Process-lifetime extract dir so zip/egg installs keep a real path.
            global _EXTRACT_ROOT  # pylint: disable=global-statement
            if _EXTRACT_ROOT is None:
                # Kept for process lifetime; closing would delete extracted files.
                _EXTRACT_ROOT = (
                    tempfile.TemporaryDirectory(  # pylint: disable=consider-using-with
                        prefix="battest-data-"
                    )
                )
            destination = Path(_EXTRACT_ROOT.name) / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
            _EXTRACTED[name] = destination
            LOGGER.debug("packaged data extracted path=%s", destination)
            return destination


@lru_cache(maxsize=1)
def load_catalog() -> SpecCatalog:
    """Load packaged commands.yaml and expansion.yaml."""
    commands_path = packaged_data_path("commands.yaml")
    expansion_path = packaged_data_path("expansion.yaml")
    LOGGER.info(
        "loading spec catalogs commands=%s expansion=%s", commands_path, expansion_path
    )
    catalog = SpecCatalog(
        _load_yaml_mapping(commands_path),
        _load_yaml_mapping(expansion_path),
    )
    LOGGER.info(
        "catalog loaded internals=%s stock=%s deprecated=%s",
        len(catalog.internal_commands),
        len(catalog.stock_utilities),
        len(catalog.deprecated_commands),
    )
    return catalog


def spec_exec_corpus_path(repo_root: Path | None = None) -> Path | None:
    """Return batch-spec corpus/exec if present, else None."""
    roots: list[Path] = []
    if repo_root is not None:
        roots.append(repo_root)
    roots.append(Path.cwd())
    package_root = Path(__file__).resolve().parent.parent.parent
    roots.append(package_root)
    for root in roots:
        candidate = root / "vendor" / "batch-spec" / "corpus" / "exec"
        LOGGER.debug("checking spec exec corpus at %s", candidate)
        if candidate.is_dir():
            LOGGER.info("found spec exec corpus at %s", candidate)
            return candidate
    LOGGER.info("spec exec corpus not present; skipping")
    return None
