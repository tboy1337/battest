"""Tests for the battest CLI and public API."""

from __future__ import annotations

from pathlib import Path
import runpy
import sys

import pytest
import yaml

from battest.api import load_case, run_case, run_cases
from battest.cli import build_parser, main
from battest.engine import EngineError
from battest.models import Case, EngineConfig, Expect, Outcome, RunResult


def test_run_as_module(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("battest.cli.main", lambda argv=None: 0)
    with pytest.raises(SystemExit) as caught:
        runpy.run_module("battest.__main__", run_name="__main__")
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


def test_main_writes_junit_on_schema_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("battest.cli.require_windows", lambda: None)
    bad = tmp_path / "bad.battest.yaml"
    bad.write_text("description: x\n", encoding="utf-8")
    junit = tmp_path / "junit.xml"
    assert main(["run", str(bad), "--junit-xml", str(junit)]) == 2
    assert junit.is_file()
    text = junit.read_text(encoding="utf-8")
    assert "<error" in text
    assert "invalid fixture" in text


def test_main_writes_junit_when_no_fixtures(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("battest.cli.require_windows", lambda: None)
    junit = tmp_path / "out" / "junit.xml"
    assert main(["run", str(tmp_path), "--junit-xml", str(junit)]) == 2
    assert junit.is_file()
    assert "no battest fixtures" in junit.read_text(encoding="utf-8")


def test_main_writes_junit_when_path_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("battest.cli.require_windows", lambda: None)
    junit = tmp_path / "junit.xml"
    missing = tmp_path / "missing-battest-fixtures"
    assert main(["run", str(missing), "--junit-xml", str(junit)]) == 2
    assert junit.is_file()
    assert "does not exist" in junit.read_text(encoding="utf-8")


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
        assert config.default_timeout_seconds == 30.0
        assert cases[0].timeout_seconds is None
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


def test_main_forwards_cli_timeout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    script = tmp_path / "input.cmd"
    script.write_text("@echo off\n", encoding="utf-8")
    (tmp_path / "ok.battest.yaml").write_text(
        "description: ok\nscript: input.cmd\nexpect:\n  exit_code: 0\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("battest.cli.require_windows", lambda: None)
    seen: list[EngineConfig] = []

    def fake_execute(cases: list[Case], config: EngineConfig) -> list[RunResult]:
        seen.append(config)
        assert cases[0].timeout_seconds is None
        return [
            RunResult(
                case_id=cases[0].case_id,
                description=cases[0].description,
                outcome=Outcome.PASS,
            )
        ]

    monkeypatch.setattr("battest.cli.execute_cases", fake_execute)
    assert main(["run", str(tmp_path), "--timeout", "7"]) == 0
    assert seen[0].default_timeout_seconds == 7.0


def test_main_rejects_non_positive_timeout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    script = tmp_path / "input.cmd"
    script.write_text("@echo off\n", encoding="utf-8")
    (tmp_path / "ok.battest.yaml").write_text(
        "description: ok\nscript: input.cmd\nexpect:\n  exit_code: 0\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("battest.cli.require_windows", lambda: None)
    called = {"execute": False}

    def fake_execute(_cases: list[Case], _config: EngineConfig) -> list[RunResult]:
        called["execute"] = True
        return []

    monkeypatch.setattr("battest.cli.execute_cases", fake_execute)
    assert main(["run", str(tmp_path), "--timeout", "0"]) == 2
    assert main(["run", str(tmp_path), "--timeout", "-1"]) == 2
    assert called["execute"] is False


def test_main_rejects_jobs_less_than_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    script = tmp_path / "input.cmd"
    script.write_text("@echo off\n", encoding="utf-8")
    (tmp_path / "ok.battest.yaml").write_text(
        "description: ok\nscript: input.cmd\nexpect:\n  exit_code: 0\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("battest.cli.require_windows", lambda: None)
    called = {"execute": False}

    def fake_execute(_cases: list[Case], _config: EngineConfig) -> list[RunResult]:
        called["execute"] = True
        return []

    monkeypatch.setattr("battest.cli.execute_cases", fake_execute)
    assert main(["run", str(tmp_path), "--jobs", "0"]) == 2
    assert main(["run", str(tmp_path), "--jobs", "-3"]) == 2
    assert called["execute"] is False


def test_main_rejects_max_diff_less_than_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    script = tmp_path / "input.cmd"
    script.write_text("@echo off\n", encoding="utf-8")
    (tmp_path / "ok.battest.yaml").write_text(
        "description: ok\nscript: input.cmd\nexpect:\n  exit_code: 0\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("battest.cli.require_windows", lambda: None)
    called = {"execute": False}

    def fake_execute(_cases: list[Case], _config: EngineConfig) -> list[RunResult]:
        called["execute"] = True
        return []

    monkeypatch.setattr("battest.cli.execute_cases", fake_execute)
    assert main(["run", str(tmp_path), "--max-diff", "0"]) == 2
    assert main(["run", str(tmp_path), "--max-diff", "-4"]) == 2
    assert called["execute"] is False


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


def test_main_junit_oserror(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
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
                case_id=cases[0].case_id,
                description=cases[0].description,
                outcome=Outcome.PASS,
            )
        ],
    )

    def boom_write(_results: list[RunResult], _path: Path) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("battest.cli.write_junit_xml", boom_write)
    junit = tmp_path / "junit.xml"
    assert main(["run", str(tmp_path), "--junit-xml", str(junit)]) == 2


def test_load_case_file_and_dir(tmp_path: Path) -> None:
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


@pytest.mark.windows
def test_run_case_success_on_windows(tmp_path: Path) -> None:
    script = tmp_path / "input.cmd"
    script.write_text("@echo off\r\necho api-ok\r\nexit /b 0\r\n", encoding="utf-8")
    manifest = tmp_path / "ok.battest.yaml"
    manifest.write_text(
        "\n".join(
            [
                "description: api success",
                "script: input.cmd",
                "expect:",
                "  exit_code: 0",
                "  stdout:",
                "    contains: api-ok",
            ]
        ),
        encoding="utf-8",
    )
    cases = load_case(manifest)
    result = run_case(cases[0])
    assert result.outcome == Outcome.PASS
    results = run_cases(cases)
    assert results[0].outcome == Outcome.PASS


def test_root_action_yml_is_composite() -> None:
    root = Path(__file__).resolve().parent.parent
    action_path = root / "action.yml"
    script_path = root / "scripts" / "run-battest-action.ps1"
    assert action_path.is_file(), "action.yml must live at the repository root"
    assert (
        script_path.is_file()
    ), "composite action must invoke scripts/run-battest-action.ps1"
    loaded = yaml.safe_load(action_path.read_text(encoding="utf-8"))
    assert loaded["runs"]["using"] == "composite"
    assert "junit-xml" in loaded["outputs"]
    run_source = "\n".join(str(step.get("run", "")) for step in loaded["runs"]["steps"])
    env_blob = "\n".join(str(step.get("env", "")) for step in loaded["runs"]["steps"])
    assert "${{ inputs.path }}" not in run_source
    assert "${{ inputs.extra-args }}" not in run_source
    assert "${{ inputs.safe-defaults }}" not in run_source
    assert "BATTEST_PATH" in env_blob
    assert "BATTEST_EXTRA_ARGS" in env_blob
    assert "BATTEST_SAFE_DEFAULTS" in env_blob
    assert "run-battest-action.ps1" in run_source
    assert "ConvertFrom-Json" not in run_source
    script = script_path.read_text(encoding="utf-8")
    create_at = script.index("New-Item -ItemType File -Path $junit")
    python_at = script.index("Invoke-BattestPython -Arguments")
    assert create_at < python_at
    assert "junit-xml=$junit" in script
    assert "& python @Arguments" in script
    assert "ConvertFrom-Json" in script
    assert "extra-args is not valid JSON" in script
    assert "JSON must be an array of strings" in script
    assert "Starting battest" in script
    assert "Write-Host" not in script
    assert "cmdArgs -join" not in script
