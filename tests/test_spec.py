"""Tests for batch-spec catalog loading."""

from __future__ import annotations

from pathlib import Path

import pytest

from battest.spec import (
    SpecCatalog,
    _load_yaml_mapping,
    _string_key_set,
    _string_list_set,
    load_catalog,
    packaged_data_path,
    spec_exec_corpus_path,
)


def test_load_catalog_has_commands() -> None:
    catalog = load_catalog()
    assert catalog.is_internal("del")
    assert catalog.is_internal("DEL")
    assert not catalog.is_internal("ipconfig")
    assert "ipconfig" in catalog.stock_utilities
    assert catalog.is_deprecated("wmic")
    assert catalog.is_removed("edlin")
    assert "edlin" in catalog.removed_commands
    assert "wmic" in catalog.deprecated_commands
    assert "del" in catalog.internal_commands
    assert catalog.stock_utilities


def test_invalid_tilde_forms() -> None:
    catalog = load_catalog()
    assert catalog.invalid_tilde_forms("%~q1")
    assert catalog.invalid_tilde_forms("%~*")
    assert catalog.invalid_tilde_forms("%~dpnx0") == []
    assert catalog.invalid_tilde_forms("%~1") == []


def test_spec_exec_present_when_created(tmp_path: Path) -> None:
    corpus = tmp_path / "vendor" / "batch-spec" / "corpus" / "exec"
    corpus.mkdir(parents=True)
    assert spec_exec_corpus_path(tmp_path) == corpus


def test_catalog_helpers_and_packaged_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert _string_key_set(["not", "a", "dict"]) == frozenset()
    assert _string_list_set("not-a-list") == frozenset()
    catalog = SpecCatalog({}, {"valid_modifier_chars": ""})
    assert catalog.invalid_tilde_forms("%~f1") == []
    listed = tmp_path / "list.yaml"
    listed.write_text("- just a list\n", encoding="utf-8")
    with pytest.raises(ValueError, match="mapping"):
        _load_yaml_mapping(listed)
    original = Path.is_file

    def missing_adjacent(self: Path) -> bool:
        if self.name in {"commands.yaml", "expansion.yaml"}:
            return False
        return original(self)

    monkeypatch.setattr(Path, "is_file", missing_adjacent)
    path = packaged_data_path("commands.yaml")
    assert path.name == "commands.yaml"
