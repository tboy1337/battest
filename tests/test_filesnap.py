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


def test_file_text_rejects_escape(tmp_path: Path) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_text("classified", encoding="utf-8")
    work = tmp_path / "work"
    work.mkdir()
    assert file_text(work, "../secret.txt") is None


def test_file_text_oserror(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "yes.txt"
    target.write_text("abc", encoding="utf-8")

    def boom(self: Path, *args: object, **kwargs: object) -> str:
        raise OSError("denied")

    monkeypatch.setattr(Path, "read_text", boom)
    assert file_text(tmp_path, "yes.txt") is None


def test_snapshot_missing_root(tmp_path: Path) -> None:
    assert snapshot_files(tmp_path / "missing") == {}


def test_snapshot_skips_directories(tmp_path: Path) -> None:
    (tmp_path / "subdir").mkdir()
    (tmp_path / "keep.txt").write_text("ok", encoding="utf-8")
    snapshot = snapshot_files(tmp_path)
    assert snapshot == {"keep.txt": b"ok"}


def test_snapshot_read_oserror(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "keep.txt"
    target.write_text("ok", encoding="utf-8")

    def boom(self: Path) -> bytes:
        raise OSError("denied")

    monkeypatch.setattr(Path, "read_bytes", boom)
    assert snapshot_files(tmp_path) == {}


def test_snapshot_skips_empty_relative(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "keep.txt").write_text("ok", encoding="utf-8")
    original = Path.rglob

    def with_root(self: Path, pattern: str) -> object:
        if self.resolve() == tmp_path.resolve():
            yield self
        yield from original(self, pattern)

    monkeypatch.setattr(Path, "rglob", with_root)
    assert snapshot_files(tmp_path) == {"keep.txt": b"ok"}
