"""Tests for the PATH-mock stub build script."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from types import ModuleType

import pytest


def _load_build_stub_module() -> ModuleType:
    path = Path(__file__).resolve().parent.parent / "scripts" / "build_stub.py"
    spec = importlib.util.spec_from_file_location("build_stub", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["build_stub"] = module
    spec.loader.exec_module(module)
    return module


def test_packaged_exe_path() -> None:
    module = _load_build_stub_module()
    packaged_exe = getattr(module, "packaged_exe")
    path = packaged_exe()
    assert path.name == "battest_stub.exe"
    assert path.parent.name == "data"


def test_release_artifact_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_build_stub_module()
    monkeypatch.setattr(module.sys, "platform", "win32")
    artifact = getattr(module, "release_artifact")()
    assert artifact.name == "battest-stub.exe"


def test_release_artifact_posix(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_build_stub_module()
    monkeypatch.setattr(module.sys, "platform", "linux")
    artifact = getattr(module, "release_artifact")()
    assert artifact.name == "battest-stub"


def test_cargo_executable_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_build_stub_module()
    monkeypatch.setattr(module.shutil, "which", lambda _name: None)
    with pytest.raises(FileNotFoundError, match="cargo"):
        getattr(module, "cargo_executable")()


def test_copy_packaged_exe_skips_on_posix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_build_stub_module()
    monkeypatch.setattr(module.sys, "platform", "linux")
    monkeypatch.setattr(module, "PACKAGE_DATA", tmp_path)
    destination = getattr(module, "copy_packaged_exe")(tmp_path / "battest-stub")
    assert destination == tmp_path / "battest_stub.exe"
    assert not destination.exists()


def test_copy_packaged_exe_on_windows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_build_stub_module()
    monkeypatch.setattr(module.sys, "platform", "win32")
    monkeypatch.setattr(module, "PACKAGE_DATA", tmp_path)
    artifact = tmp_path / "built.exe"
    artifact.write_bytes(b"MZ")
    destination = getattr(module, "copy_packaged_exe")(artifact)
    assert destination.read_bytes() == b"MZ"


def test_main_missing_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_build_stub_module()
    monkeypatch.setattr(module, "STUB_MANIFEST", tmp_path / "missing.toml")
    monkeypatch.setattr(module.shutil, "which", lambda _name: "cargo")
    assert getattr(module, "main")([]) == 2
