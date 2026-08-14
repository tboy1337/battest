"""Tests for batch-spec catalog loading."""

from __future__ import annotations

from pathlib import Path

from battest.spec import load_catalog, spec_exec_corpus_path


def test_load_catalog_has_commands() -> None:
    catalog = load_catalog()
    assert catalog.is_internal("del")
    assert catalog.is_internal("DEL")
    assert not catalog.is_internal("ipconfig")
    assert "ipconfig" in catalog.stock_utilities
    assert catalog.is_deprecated("wmic")
    assert catalog.is_removed("edlin")


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
