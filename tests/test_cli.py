"""Tests for the battest CLI and public API."""

from __future__ import annotations

from pathlib import Path
import runpy
import sys

import pytest

from battest.api import load_case, run_case, run_cases
from battest.cli import build_parser, main
from battest.engine import EngineError
from battest.models import Case, EngineConfig, Expect, Outcome, RunResult


def test_run_as_module(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("battest.cli.main", lambda argv=None: 0)
    with pytest.raises(SystemExit) as caught:
        runpy.run_module("battest", run_name="__main__")
    assert caught.value.code == 0
    parser = build_parser()
    args = parser.parse_args(["run"])
    assert args.command == "run"
    assert args.safe_defaults is False
    assert args.jobs == 1


def test_main_without_command_is_usage() -> None:
    assert main([]) == 2


def test_main_no_fixtures(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("battest.cli.require_windows", lambda: None)
    assert main(["run", str(tmp_path)]) == 2


def test_main_schema_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("battest.cli.require_windows", lambda: None)
    bad = tmp_path / "bad.battest.yaml"
    bad.write_text("description: x\n", encoding="utf-8")
    assert main(["run", str(bad)]) == 2


def test_main_engine_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def raise_engine() -> None:
        raise EngineError("nope")

    monkeypatch.setattr("battest.cli.require_windows", raise_engine)
    assert main(["run", str(tmp_path)]) == 2


def test_main_run_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    script = tmp_path / "input.cmd"
    script.write_text("@echo off\n", encoding="utf-8")
    manifest = tmp_path / "ok.battest.yaml"
    manifest.write_text(
        "description: ok\nscript: input.cmd\nexpect:\n  exit_code: 0\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("battest.cli.require_windows", lambda: None)

    def fake_execute(cases: list[Case], config: EngineConfig) -> list[RunResult]:
        assert config.jobs == 1
        return [
            RunResult(
                case_id=cases[0].case_id,
                description=cases[0].description,
                outcome=Outcome.PASS,
            )
        ]

    monkeypatch.setattr("battest.cli.execute_cases", fake_execute)
    junit = tmp_path / "junit.xml"
    assert main(["run", str(tmp_path), "--junit-xml", str(junit)]) == 0
    assert junit.is_file()


def test_main_run_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    script = tmp_path / "input.cmd"
    script.write_text("@echo off\n", encoding="utf-8")
    (tmp_path / "ok.battest.yaml").write_text(
        "description: ok\nscript: input.cmd\nexpect:\n  exit_code: 0\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("battest.cli.require_windows", lambda: None)
    monkeypatch.setattr(
        "battest.cli.execute_cases",
        lambda cases, config: [
            RunResult(
                case_id="x",
                description="x",
                outcome=Outcome.FAIL,
            )
        ],
    )
    assert main(["run", str(tmp_path), "--safe-defaults", "--jobs", "2"]) == 1


def test_main_execute_engine_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    script = tmp_path / "input.cmd"
    script.write_text("@echo off\n", encoding="utf-8")
    (tmp_path / "ok.battest.yaml").write_text(
        "description: ok\nscript: input.cmd\nexpect:\n  exit_code: 0\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("battest.cli.require_windows", lambda: None)

    def boom(_cases: list[Case], _config: EngineConfig) -> list[RunResult]:
        raise EngineError("cannot exec")

    monkeypatch.setattr("battest.cli.execute_cases", boom)
    assert main(["run", str(tmp_path), "--verbose", "--include-spec-exec"]) == 2
    script = tmp_path / "input.cmd"
    script.write_text("@echo off\n", encoding="utf-8")
    manifest = tmp_path / "ok.battest.yaml"
    manifest.write_text(
        "description: ok\nscript: input.cmd\nexpect:\n  exit_code: 0\n",
        encoding="utf-8",
    )
    from_file = load_case(manifest)
    from_dir = load_case(tmp_path)
    assert len(from_file) == 1
    assert len(from_dir) == 1
    assert from_file[0].description == "ok"


def test_run_case_and_run_cases_require_windows(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    script = tmp_path / "input.cmd"
    script.write_text("@echo off\n", encoding="utf-8")
    case = Case(
        case_id="x",
        description="x",
        source_path=tmp_path / "expect.yaml",
        script_path=script,
        expect=Expect(exit_code=0),
    )
    with pytest.raises(EngineError):
        run_case(case)
    with pytest.raises(EngineError):
        run_cases([case], jobs=2)
