"""Tests for version resolution and package exports."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from pathlib import Path

import pytest

import battest
from battest._version import _fallback_version, get_version


def test_version_is_pep440_like() -> None:
    version = get_version()
    assert version[0].isdigit()
    assert battest.__version__ == version
    assert battest.__license__ == "AGPL-3.0-or-later"
    assert "load_case" in battest.__all__


def test_fallback_version_missing_and_without_version_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "battest._version._pyproject_path", lambda: tmp_path / "missing.toml"
    )
    assert _fallback_version() == "unknown"
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("[project]\nname = 'battest'\n", encoding="utf-8")
    monkeypatch.setattr("battest._version._pyproject_path", lambda: pyproject)
    assert _fallback_version() == "unknown"


def test_get_version_uses_installed_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("[project]\nname = 'battest'\n", encoding="utf-8")
    monkeypatch.setattr("battest._version._pyproject_path", lambda: pyproject)
    monkeypatch.setattr("battest._version.version", lambda _name: "9.9.9")
    assert get_version() == "9.9.9"


def test_get_version_package_not_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "battest._version._pyproject_path", lambda: tmp_path / "missing.toml"
    )

    def boom(_name: str) -> str:
        raise PackageNotFoundError(_name)

    monkeypatch.setattr("battest._version.version", boom)
    assert get_version() == "unknown"
