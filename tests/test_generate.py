"""Tests for catalog generate-and-check."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from types import ModuleType

import pytest

from battest.spec import packaged_data_path


def _load_generate_module() -> ModuleType:
    path = Path(__file__).resolve().parent.parent / "scripts" / "generate_spec_data.py"
    spec = importlib.util.spec_from_file_location("generate_spec_data", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["generate_spec_data"] = module
    spec.loader.exec_module(module)
    return module


def test_packaged_data_path_exists() -> None:
    path = packaged_data_path("commands.yaml")
    assert path.is_file()


def test_copy_and_check(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_generate_module()
    package_data = tmp_path / "data"
    monkeypatch.setattr(module, "PACKAGE_DATA", package_data)
    copy_catalogs = getattr(module, "copy_catalogs")
    catalogs_match = getattr(module, "catalogs_match")
    main = getattr(module, "main")
    written = copy_catalogs()
    assert written
    assert catalogs_match() is True
    (package_data / "commands.yaml").write_text("drift\n", encoding="utf-8")
    assert catalogs_match() is False
    assert main(["--check"]) == 1
    assert main([]) == 0
    assert catalogs_match() is True
