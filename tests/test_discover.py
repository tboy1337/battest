"""Tests for fixture discovery."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from battest.discover import default_root, discover_cases, iter_fixture_files
from battest.schema import SchemaError
from battest.spec import spec_exec_corpus_path


def test_iter_fixture_files_finds_manifest_and_case_dir(tmp_path: Path) -> None:
    case_dir = tmp_path / "alpha"
    case_dir.mkdir()
    (case_dir / "input.cmd").write_text("@echo off\n", encoding="utf-8")
    (case_dir / "expect.yaml").write_text(
        "description: alpha\nexpect:\n  exit_code: 0\n",
        encoding="utf-8",
    )
    (tmp_path / "beta.battest.yaml").write_text(
        "description: beta\nscript: alpha/input.cmd\nexpect:\n  exit_code: 0\n",
        encoding="utf-8",
    )
    (tmp_path / "ignore.txt").write_text("no", encoding="utf-8")
    found = {path.name for path in iter_fixture_files(tmp_path)}
    assert "expect.yaml" in found
    assert "beta.battest.yaml" in found
    assert "ignore.txt" not in found


def test_discover_cases_loads_both_shapes(tmp_path: Path) -> None:
    case_dir = tmp_path / "alpha"
    case_dir.mkdir()
    (case_dir / "input.cmd").write_text("@echo off\n", encoding="utf-8")
    (case_dir / "expect.yaml").write_text(
        "description: alpha\nexpect:\n  exit_code: 0\n",
        encoding="utf-8",
    )
    cases = discover_cases(tmp_path)
    assert len(cases) == 1
    assert cases[0].description == "alpha"
    assert cases[0].case_id == "alpha"


def test_discover_relative_case_ids_are_unique(tmp_path: Path) -> None:
    script = "@echo off\nexit /b 0\n"
    for folder in ("a", "b"):
        nested = tmp_path / folder
        nested.mkdir()
        (nested / "hello.cmd").write_text(script, encoding="utf-8")
        (nested / "hello.battest.yaml").write_text(
            "description: hello\nscript: hello.cmd\nexpect:\n  exit_code: 0\n",
            encoding="utf-8",
        )
    cases = discover_cases(tmp_path)
    assert sorted(item.case_id for item in cases) == ["a/hello", "b/hello"]


def test_discover_single_file_keeps_stem_id(tmp_path: Path) -> None:
    nested = tmp_path / "a"
    nested.mkdir()
    (nested / "hello.cmd").write_text("@echo off\n", encoding="utf-8")
    manifest = nested / "hello.battest.yaml"
    manifest.write_text(
        "description: hello\nscript: hello.cmd\nexpect:\n  exit_code: 0\n",
        encoding="utf-8",
    )
    cases = discover_cases(manifest)
    assert [item.case_id for item in cases] == ["hello"]


def test_discover_duplicate_case_ids_raise(tmp_path: Path) -> None:
    (tmp_path / "run.cmd").write_text("@echo off\n", encoding="utf-8")
    (tmp_path / "dup.battest.yaml").write_text(
        "description: one\nscript: run.cmd\nexpect:\n  exit_code: 0\n",
        encoding="utf-8",
    )
    case_dir = tmp_path / "dup"
    case_dir.mkdir()
    (case_dir / "input.cmd").write_text("@echo off\n", encoding="utf-8")
    (case_dir / "expect.yaml").write_text(
        "description: two\nexpect:\n  exit_code: 0\n",
        encoding="utf-8",
    )
    with pytest.raises(SchemaError, match="duplicate case id"):
        discover_cases(tmp_path)


def test_default_root_prefers_tests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    monkeypatch.chdir(tmp_path)
    assert default_root() == tests_dir


def test_default_root_falls_back_to_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    assert default_root() == tmp_path


def test_include_spec_exec_when_absent(tmp_path: Path) -> None:
    (tmp_path / "input.cmd").write_text("@echo off\n", encoding="utf-8")
    (tmp_path / "solo.battest.yaml").write_text(
        "description: solo\nscript: input.cmd\nexpect:\n  exit_code: 0\n",
        encoding="utf-8",
    )
    cases = discover_cases(tmp_path, include_spec_exec=True, repo_root=tmp_path)
    assert len(cases) == 1


def test_include_spec_exec_discovers_corpus(tmp_path: Path) -> None:
    corpus = tmp_path / "vendor" / "batch-spec" / "corpus" / "exec" / "sample"
    corpus.mkdir(parents=True)
    (corpus / "input.cmd").write_text("@echo off\n", encoding="utf-8")
    (corpus / "expect.yaml").write_text(
        "description: corpus-exec\nexpect:\n  exit_code: 0\n",
        encoding="utf-8",
    )
    cases = discover_cases(tmp_path, include_spec_exec=True, repo_root=tmp_path)
    assert [item.description for item in cases] == ["corpus-exec"]


def test_spec_exec_corpus_path_none_for_empty_root(tmp_path: Path) -> None:
    assert spec_exec_corpus_path(tmp_path) is None


def test_iter_fixture_files_missing(tmp_path: Path) -> None:
    with pytest.raises(SchemaError, match="does not exist"):
        iter_fixture_files(tmp_path / "missing")


def test_iter_skips_vendor(tmp_path: Path) -> None:
    vendor = tmp_path / "vendor" / "nested"
    vendor.mkdir(parents=True)
    (vendor / "hidden.battest.yaml").write_text(
        "description: hidden\nexpect:\n  exit_code: 0\n",
        encoding="utf-8",
    )
    cargo_target = tmp_path / "target" / "debug"
    cargo_target.mkdir(parents=True)
    (cargo_target / "hidden.battest.yaml").write_text(
        "description: cargo-target\nexpect:\n  exit_code: 0\n",
        encoding="utf-8",
    )
    found = iter_fixture_files(tmp_path)
    assert found == []
    venv = tmp_path / "venv" / "nested"
    venv.mkdir(parents=True)
    (venv / "hidden.battest.yaml").write_text(
        "description: venv-hidden\nexpect:\n  exit_code: 0\n",
        encoding="utf-8",
    )
    assert iter_fixture_files(tmp_path) == []
    path = tmp_path / "one.battest.yaml"
    path.write_text("description: one\nexpect:\n  exit_code: 0\n", encoding="utf-8")
    assert iter_fixture_files(path) == [path]


def test_iter_skips_when_root_itself_is_vendor(tmp_path: Path) -> None:
    vendor = tmp_path / "vendor"
    vendor.mkdir()
    (vendor / "hidden.battest.yaml").write_text(
        "description: hidden\nexpect:\n  exit_code: 0\n",
        encoding="utf-8",
    )
    assert iter_fixture_files(vendor) == []


def test_iter_fixture_files_logs_walk_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    (tmp_path / "keep.battest.yaml").write_text(
        "description: keep\nexpect:\n  exit_code: 0\n",
        encoding="utf-8",
    )
    original = os.walk

    def wrapping_walk(
        top: str | os.PathLike[str],
        topdown: bool = True,
        onerror: object = None,
        followlinks: bool = False,
    ) -> object:
        if callable(onerror):
            onerror(PermissionError("locked-dir"))
        return original(top, topdown=topdown, onerror=onerror, followlinks=followlinks)

    monkeypatch.setattr(os, "walk", wrapping_walk)
    with caplog.at_level("WARNING", logger="battest.discover"):
        found = iter_fixture_files(tmp_path)
    assert any(path.name == "keep.battest.yaml" for path in found)
    assert "locked-dir" in caplog.text


def test_iter_fixture_files_walk_oserror_returns_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def boom_walk(_top: object, **_kwargs: object) -> object:
        raise OSError("cannot walk")

    monkeypatch.setattr(os, "walk", boom_walk)
    with caplog.at_level("ERROR", logger="battest.discover"):
        assert iter_fixture_files(tmp_path) == []
    assert "cannot walk" in caplog.text


def test_iter_fixture_files_walk_iteration_oserror(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def flaky_walk(top: object, **_kwargs: object) -> object:
        yield str(top), [], ["keep.battest.yaml"]
        raise OSError("mid-walk")

    monkeypatch.setattr(os, "walk", flaky_walk)
    with caplog.at_level("ERROR", logger="battest.discover"):
        found = iter_fixture_files(tmp_path)
    assert any(path.name == "keep.battest.yaml" for path in found)
    assert "mid-walk" in caplog.text
