"""Tests for filesystem snapshots."""

from __future__ import annotations

from pathlib import Path

import pytest

from battest.filesnap import file_text, snapshot_files


def test_snapshot_skips_helper_dirs(tmp_path: Path) -> None:
    (tmp_path / "keep.txt").write_text("ok", encoding="utf-8")
    helper = tmp_path / "_battest_mocks"
    helper.mkdir()
    (helper / "ipconfig.cmd").write_text("@echo off\n", encoding="utf-8")
    (tmp_path / "_battest_env.txt").write_text("FOO=1\n", encoding="utf-8")
    snapshot = snapshot_files(tmp_path)
    assert snapshot == {"keep.txt": b"ok"}


def test_file_text_missing(tmp_path: Path) -> None:
    assert file_text(tmp_path, "nope.txt") is None
    (tmp_path / "yes.txt").write_text("abc", encoding="utf-8")
    assert file_text(tmp_path, "yes.txt") == "abc"


def test_file_text_oserror(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "yes.txt"
    target.write_text("abc", encoding="utf-8")

    def boom(self: Path, *args: object, **kwargs: object) -> str:
        raise OSError("denied")

    monkeypatch.setattr(Path, "read_text", boom)
    assert file_text(tmp_path, "yes.txt") is None


def test_snapshot_missing_root(tmp_path: Path) -> None:
    assert snapshot_files(tmp_path / "missing") == {}
