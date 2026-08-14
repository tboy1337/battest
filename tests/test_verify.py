"""Tests for scripts/verify.py."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from types import ModuleType

import pytest


def _load_verify() -> ModuleType:
    path = Path(__file__).resolve().parent.parent / "scripts" / "verify.py"
    spec = importlib.util.spec_from_file_location("verify", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["verify"] = module
    spec.loader.exec_module(module)
    return module


def test_build_steps_include_rust_typecheck_lint_and_coverage() -> None:
    module = _load_verify()
    steps = module.build_steps(
        python="python",
        cargo="cargo",
        cargo_audit="cargo-audit",
        skip_format=False,
        skip_lint=False,
        skip_audit=False,
        skip_tests=False,
    )
    joined = [" ".join(command) for command, _skip in steps]
    assert any("cargo check " in item and "stub/Cargo.toml" in item for item in joined)
    assert any("clippy" in item and "stub/Cargo.toml" in item for item in joined)
    assert any("cargo fmt " in item for item in joined)
    assert any("check_rust_coverage.py" in item for item in joined)
    assert any("cargo test " in item and "stub/Cargo.toml" in item for item in joined)
    assert any("check_coverage.py" in item for item in joined)


def test_build_steps_honor_skip_flags() -> None:
    module = _load_verify()
    steps = module.build_steps(
        python="python",
        cargo="cargo",
        cargo_audit=None,
        skip_format=True,
        skip_lint=True,
        skip_audit=True,
        skip_tests=True,
    )
    skipped = {tuple(command): skip for command, skip in steps}
    fmt = ("cargo", "fmt", "--all", "--check", "--manifest-path", "stub/Cargo.toml")
    check = (
        "cargo",
        "check",
        "--manifest-path",
        "stub/Cargo.toml",
        "--all-targets",
        "--locked",
    )
    clippy_head = ("cargo", "clippy", "--manifest-path", "stub/Cargo.toml")
    assert skipped[fmt] is True
    assert skipped[check] is True
    assert any(skip and command[:4] == list(clippy_head) for command, skip in steps)
    assert any(
        skip and command[-1] == "scripts/check_rust_coverage.py"
        for command, skip in steps
    )
    assert any(skip and command[1] == "audit" for command, skip in steps)


def test_main_requires_cargo(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_verify()
    monkeypatch.setattr(module.shutil, "which", lambda _name: None)
    assert module.main(["--skip-tests"]) == 2


def test_main_runs_pipeline_and_stops_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_verify()
    seen: list[list[str]] = []

    def fake_which(name: str) -> str | None:
        if name == "cargo":
            return "cargo"
        return None

    def fake_run(command: list[str], skip: bool) -> int:
        if skip:
            return 0
        seen.append(command)
        if command[-1] == "scripts/generate_spec_data.py" or (
            len(command) >= 2 and command[1] == "scripts/generate_spec_data.py"
        ):
            return 0
        if "black" in command:
            return 7
        return 0

    monkeypatch.setattr(module.shutil, "which", fake_which)
    monkeypatch.setattr(module, "_run", fake_run)
    assert module.main([]) == 7
    assert seen


def test_main_succeeds_when_all_steps_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_verify()
    seen: list[tuple[list[str], bool]] = []

    def fake_which(name: str) -> str | None:
        mapping = {"cargo": "cargo", "cargo-audit": "cargo-audit"}
        return mapping.get(name)

    def fake_run(command: list[str], skip: bool) -> int:
        seen.append((command, skip))
        return 0

    monkeypatch.setattr(module.shutil, "which", fake_which)
    monkeypatch.setattr(module, "_run", fake_run)
    assert (
        module.main(["--skip-format", "--skip-lint", "--skip-audit", "--skip-tests"])
        == 0
    )
    assert any(
        command[-1] == "scripts/check_rust_coverage.py" and skip
        for command, skip in seen
    )
