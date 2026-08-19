"""Tests for the battest CLI and public API."""

from __future__ import annotations

import logging
from pathlib import Path
import re
import runpy
import sys

import pytest
import yaml

from battest.api import load_case, run_case, run_cases
from battest.cli import build_parser, main
from battest.constants import MAX_JOBS
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


def test_main_calls_freeze_support(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[bool] = []
    monkeypatch.setattr(
        "battest.cli.multiprocessing.freeze_support",
        lambda: called.append(True),
    )
    assert main([]) == 2
    assert called == [True]


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


def test_main_rejects_non_finite_timeout(
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
    assert main(["run", str(tmp_path), "--timeout", "nan"]) == 2
    assert main(["run", str(tmp_path), "--timeout", "inf"]) == 2
    assert main(["run", str(tmp_path), "--timeout=-inf"]) == 2
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
    assert main(["run", str(tmp_path), "--jobs", str(MAX_JOBS + 1)]) == 2
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


def test_main_junit_oserror_preserves_fail_exit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
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
                outcome=Outcome.FAIL,
            )
        ],
    )

    def boom_write(_results: list[RunResult], _path: Path) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("battest.cli.write_junit_xml", boom_write)
    junit = tmp_path / "junit.xml"
    assert main(["run", str(tmp_path), "--junit-xml", str(junit)]) == 1


def test_main_usage_junit_oserror(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("battest.cli.require_windows", lambda: None)

    def boom_usage(_path: Path, _message: str) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("battest.cli.write_usage_junit", boom_usage)
    junit = tmp_path / "junit.xml"
    assert main(["run", str(tmp_path), "--junit-xml", str(junit)]) == 2


def test_main_engine_config_validation_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    script = tmp_path / "input.cmd"
    script.write_text("@echo off\n", encoding="utf-8")
    (tmp_path / "ok.battest.yaml").write_text(
        "description: ok\nscript: input.cmd\nexpect:\n  exit_code: 0\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("battest.cli.require_windows", lambda: None)

    def boom_config(**_kwargs: object) -> EngineConfig:
        return EngineConfig(default_timeout_seconds=float("nan"))

    monkeypatch.setattr("battest.cli.EngineConfig", boom_config)
    assert main(["run", str(tmp_path)]) == 2


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


def test_load_case_include_spec_exec_when_absent(tmp_path: Path) -> None:
    script = tmp_path / "input.cmd"
    script.write_text("@echo off\n", encoding="utf-8")
    manifest = tmp_path / "ok.battest.yaml"
    manifest.write_text(
        "description: ok\nscript: input.cmd\nexpect:\n  exit_code: 0\n",
        encoding="utf-8",
    )
    cases = load_case(tmp_path, include_spec_exec=True)
    assert len(cases) == 1
    assert cases[0].description == "ok"


def test_load_case_logs(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    script = tmp_path / "input.cmd"
    script.write_text("@echo off\n", encoding="utf-8")
    manifest = tmp_path / "ok.battest.yaml"
    manifest.write_text(
        "description: ok\nscript: input.cmd\nexpect:\n  exit_code: 0\n",
        encoding="utf-8",
    )
    with caplog.at_level(logging.INFO, logger="battest.api"):
        loaded = load_case(manifest)
    assert len(loaded) == 1
    assert "api load_case" in caplog.text


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


def test_run_case_rejects_non_finite_timeout(tmp_path: Path) -> None:
    script = tmp_path / "input.cmd"
    script.write_text("@echo off\n", encoding="utf-8")
    case = Case(
        case_id="x",
        description="x",
        source_path=tmp_path / "expect.yaml",
        script_path=script,
        expect=Expect(exit_code=0),
    )
    with pytest.raises(EngineError, match="finite"):
        run_case(case, timeout_seconds=float("inf"))
    with pytest.raises(EngineError, match="finite"):
        run_cases([case], timeout_seconds=float("nan"))


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


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _load_ci_workflow() -> dict[str, object]:
    path = _repo_root() / ".github" / "workflows" / "CI.yml"
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def test_root_action_yml_resolves_pip_cache_path() -> None:
    action_path = _repo_root() / "action.yml"
    raw = action_path.read_text(encoding="utf-8")
    loaded = yaml.safe_load(raw)
    steps = loaded["runs"]["steps"]
    pip_cache = next(step for step in steps if step.get("id") == "pip-cache")
    setup_python = next(
        step
        for step in steps
        if str(step.get("uses", "")).startswith("actions/setup-python@")
    )
    assert pip_cache["shell"] == "pwsh"
    run_text = str(pip_cache["run"])
    assert "Resolve-Path" in run_text
    assert "GITHUB_ACTION_PATH" in run_text
    assert "github.action_path }}/pyproject.toml" not in raw
    assert (
        setup_python["with"]["cache-dependency-path"]
        == "${{ steps.pip-cache.outputs.path }}"
    )
    names = [step.get("name") for step in steps]
    assert names.index("Resolve pip cache dependency path") < names.index(
        "Set up Python"
    )


def test_ci_windows_pytest_rebuilds_stub_without_pe_byte_match() -> None:
    workflow = _load_ci_workflow()
    jobs = workflow["jobs"]
    assert isinstance(jobs, dict)
    test_windows = jobs["test-windows"]
    assert isinstance(test_windows, dict)
    steps = test_windows["steps"]
    assert isinstance(steps, list)
    rebuild = next(
        step
        for step in steps
        if isinstance(step, dict) and step.get("name") == "Rebuild PATH-mock stub"
    )
    assert "build_stub.py" in str(rebuild.get("run"))
    names = [
        step.get("name") for step in steps if isinstance(step, dict) and "name" in step
    ]
    assert names.index("Run example suites with committed stub") < names.index(
        "Rebuild PATH-mock stub"
    )
    assert names.index("Rebuild PATH-mock stub") < names.index("Run full tests")
    assert "Run example suites with rebuilt stub" in names
    drift_steps = [
        step
        for step in steps
        if isinstance(step, dict)
        and "battest_stub.exe" in str(step.get("run", ""))
        and "git diff" in str(step.get("run", ""))
    ]
    assert drift_steps == []


def test_ci_unit_job_does_not_fail_coverage_on_non_windows() -> None:
    workflow = _load_ci_workflow()
    jobs = workflow["jobs"]
    assert isinstance(jobs, dict)
    test_unit = jobs["test-unit"]
    assert isinstance(test_unit, dict)
    steps = test_unit["steps"]
    assert isinstance(steps, list)
    run_step = next(
        step
        for step in steps
        if isinstance(step, dict) and step.get("name") == "Run unit tests"
    )
    command = str(run_step.get("run"))
    assert 'pytest -m "not windows"' in command
    assert "--cov-fail-under=0" in command


def test_ci_dependency_graph_does_not_block_release() -> None:
    workflow = _load_ci_workflow()
    jobs = workflow["jobs"]
    assert isinstance(jobs, dict)
    dependency_graph = jobs["dependency-graph"]
    check_version = jobs["check-version"]
    assert isinstance(dependency_graph, dict)
    assert isinstance(check_version, dict)
    assert dependency_graph.get("continue-on-error") is not True
    submit = next(
        step
        for step in dependency_graph["steps"]
        if isinstance(step, dict) and step.get("name") == "Submit dependency snapshot"
    )
    assert submit.get("continue-on-error") is not True
    needs = check_version["needs"]
    assert isinstance(needs, list)
    assert "dependency-graph" not in needs
    assert "test-windows" in needs
    assert "action-windows" in needs
    assert "package-smoke" in needs


def test_ci_action_dogfood_records_discovery_failure_without_continue_on_error() -> (
    None
):
    workflow = _load_ci_workflow()
    jobs = workflow["jobs"]
    assert isinstance(jobs, dict)
    action_windows = jobs["action-windows"]
    assert isinstance(action_windows, dict)
    steps = action_windows["steps"]
    assert isinstance(steps, list)
    fail_step = next(
        step
        for step in steps
        if isinstance(step, dict)
        and step.get("name") == "Dogfood missing discovery path"
    )
    assert fail_step.get("continue-on-error") is not True
    assert fail_step.get("uses") is None
    fail_run = str(fail_step.get("run"))
    assert "run-battest-action.ps1" in fail_run
    assert "Invoke-BattestAction" in fail_run
    assert "PSNativeCommandUseErrorActionPreference" in fail_run
    assert "expected battest to fail" in fail_run
    assert "exit 0" in fail_run
    assert_step = next(
        step
        for step in steps
        if isinstance(step, dict)
        and step.get("name") == "Assert JUnit written on discovery failure"
    )
    assert_run = str(assert_step.get("run"))
    assert "does not exist" in assert_run


def test_ci_retries_release_when_version_tag_is_missing() -> None:
    workflow = _load_ci_workflow()
    jobs = workflow["jobs"]
    assert isinstance(jobs, dict)
    check_version = jobs["check-version"]
    assert isinstance(check_version, dict)
    checkout = next(
        step
        for step in check_version["steps"]
        if isinstance(step, dict) and step.get("uses") == "actions/checkout@v7"
    )
    assert checkout["with"]["fetch-tags"] is True
    decide = next(
        step
        for step in check_version["steps"]
        if isinstance(step, dict) and step.get("id") == "check"
    )
    script = str(decide.get("run"))
    assert 'git rev-parse --verify --quiet "refs/tags/v${NEW_VERSION}"' in script
    assert "tag v${NEW_VERSION} is missing; releasing." in script
    assert "should_release=true" in script
    assert "should_release=false" in script
    assert "should_publish_pypi=true" in script
    assert "should_publish_pypi=false" in script
    assert "Skipping GitHub assets and PyPI" in script
    assert "Skipping GitHub release rewrite and PyPI." in script
    assert "skip-existing" not in script
    assert "github.event.inputs.force" in script
    assert "python scripts/read_git_pyproject_version.py HEAD^" in script
    assert "subprocess.check_output(['git', 'show', 'HEAD^:pyproject.toml'])" not in (
        script
    )
    version_step = next(
        step
        for step in check_version["steps"]
        if isinstance(step, dict) and step.get("id") == "version"
    )
    assert "tomllib" in str(version_step.get("run"))


def test_ci_codeql_rust_fetches_locked_crate_graph() -> None:
    workflow = _load_ci_workflow()
    jobs = workflow["jobs"]
    assert isinstance(jobs, dict)
    codeql = jobs["codeql"]
    assert isinstance(codeql, dict)
    steps = codeql["steps"]
    assert isinstance(steps, list)
    names = [
        step.get("name") for step in steps if isinstance(step, dict) and "name" in step
    ]
    assert names.index("Set up Rust") < names.index("Fetch Rust crate graph")
    assert names.index("Fetch Rust crate graph") < names.index("Initialize CodeQL")
    fetch = next(
        step
        for step in steps
        if isinstance(step, dict) and step.get("name") == "Fetch Rust crate graph"
    )
    assert fetch.get("if") == "matrix.language == 'rust'"
    assert "cargo fetch --locked --manifest-path stub/Cargo.toml" in str(
        fetch.get("run")
    )
    uses = [
        str(step.get("uses", ""))
        for step in steps
        if isinstance(step, dict) and step.get("uses")
    ]
    assert any(item.startswith("github/codeql-action/init@") for item in uses)
    assert any(item.startswith("dtolnay/rust-toolchain@") for item in uses)


def test_ci_release_jobs_are_atomic() -> None:
    workflow = _load_ci_workflow()
    jobs = workflow["jobs"]
    assert isinstance(jobs, dict)
    create_release = jobs["create-release"]
    publish_pypi = jobs["publish-pypi"]
    assert isinstance(create_release, dict)
    assert isinstance(publish_pypi, dict)
    assert create_release["needs"] == [
        "check-version",
        "build-windows",
        "build-wheels",
    ]
    assert publish_pypi["needs"] == [
        "check-version",
        "build-wheels",
        "create-release",
    ]
    publish_if = str(publish_pypi.get("if"))
    assert "needs.create-release.result == 'success'" in publish_if
    assert "should_release == 'false'" not in publish_if
    assert "skip-existing" not in publish_if
    assert publish_pypi.get("environment") == "pypi"
    permissions = publish_pypi.get("permissions")
    assert isinstance(permissions, dict)
    assert permissions.get("id-token") == "write"
    steps = create_release["steps"]
    assert isinstance(steps, list)
    download_names = [
        step.get("name")
        for step in steps
        if isinstance(step, dict) and step.get("name")
    ]
    assert "Download Windows build" in download_names
    assert "Download Python dist" in download_names
    assert "Move major version tag" in download_names
    move_major = next(
        step
        for step in steps
        if isinstance(step, dict) and step.get("name") == "Move major version tag"
    )
    move_run = str(move_major.get("run"))
    move_env = move_major.get("env")
    assert isinstance(move_env, dict)
    assert "GITHUB_TOKEN" in str(move_env.get("GH_TOKEN"))
    assert "git/refs/tags/v${MAJOR}" in move_run
    assert "force=true" in move_run
    assert "refs/tags/v${MAJOR}" in move_run
    release = next(
        step
        for step in steps
        if isinstance(step, dict) and step.get("name") == "Create GitHub Release"
    )
    artifacts = str(release.get("with", {}).get("artifacts", ""))
    assert "Battest-v${{ needs.check-version.outputs.version }}.zip" in artifacts
    assert "./python-dist/*" in artifacts
    assert "github.event.inputs.force == 'true'" in str(
        release.get("with", {}).get("allowUpdates")
    )
    publish = next(
        step
        for step in publish_pypi["steps"]
        if isinstance(step, dict) and step.get("name") == "Publish to PyPI"
    )
    publish_run = str(publish.get("run"))
    publish_env = publish.get("env")
    assert isinstance(publish_env, dict)
    assert "twine upload dist/*" in publish_run
    assert "--skip-existing" not in publish_run
    assert "secrets.PYPI_BATTEST" in str(publish_env.get("TWINE_PASSWORD"))
    workflow_text = (_repo_root() / ".github" / "workflows" / "CI.yml").read_text(
        encoding="utf-8"
    )
    assert "pypa/gh-action-pypi-publish" not in workflow_text
    assert "skip-existing" not in workflow_text
    assert "workflow_dispatch:" in workflow_text
    assert "force:" in workflow_text
    assert "default: false" in workflow_text
    check_version = jobs["check-version"]
    concurrency = check_version["concurrency"]
    assert isinstance(concurrency, dict)
    assert concurrency["group"] == "battest-release"
    assert concurrency["cancel-in-progress"] is False
    build_windows = jobs["build-windows"]
    windows_names = [
        step.get("name")
        for step in build_windows["steps"]
        if isinstance(step, dict) and step.get("name")
    ]
    assert "Smoke test executable" in windows_names
    assert "Install battest for parity checks" in windows_names
    assert windows_names.index(
        "Install battest for parity checks"
    ) < windows_names.index("Smoke test executable")
    assert windows_names.index("Smoke test executable") < windows_names.index(
        "Package executable for release"
    )
    build_wheels = jobs["build-wheels"]
    assert build_wheels["if"] == (
        "needs.check-version.outputs.should_publish_pypi == 'true'"
    )


def test_ci_package_smoke_builds_and_checks_dist() -> None:
    workflow = _load_ci_workflow()
    jobs = workflow["jobs"]
    assert isinstance(jobs, dict)
    package_smoke = jobs["package-smoke"]
    assert isinstance(package_smoke, dict)
    steps = package_smoke["steps"]
    assert isinstance(steps, list)
    names = [
        step.get("name") for step in steps if isinstance(step, dict) and "name" in step
    ]
    assert "Build sdist and wheel" in names
    assert "Check dist" in names
    assert "Install wheel and import battest" in names
    build = next(
        step
        for step in steps
        if isinstance(step, dict) and step.get("name") == "Build sdist and wheel"
    )
    check = next(
        step
        for step in steps
        if isinstance(step, dict) and step.get("name") == "Check dist"
    )
    install = next(
        step
        for step in steps
        if isinstance(step, dict)
        and step.get("name") == "Install wheel and import battest"
    )
    assert "python -m build" in str(build.get("run"))
    assert "twine check dist/*" in str(check.get("run"))
    assert "import battest" in str(install.get("run"))
    assert "console_scripts" in str(install.get("run"))
    assert "battest_stub.exe" in str(install.get("run"))
    assert "commands.yaml" in str(install.get("run"))
    assert "expansion.yaml" in str(install.get("run"))
    assert "battest-expect.schema.json" in str(install.get("run"))
    assert "stub_executable" in str(install.get("run"))


def test_ci_cancels_in_progress_pull_requests_only() -> None:
    workflow = _load_ci_workflow()
    concurrency = workflow["concurrency"]
    assert isinstance(concurrency, dict)
    assert concurrency["group"] == "ci-${{ github.workflow }}-${{ github.ref }}"
    assert (
        concurrency["cancel-in-progress"]
        == "${{ github.event_name == 'pull_request' }}"
    )


def test_github_actions_are_not_pinned_to_shas() -> None:
    sha_uses = re.compile(r"uses:\s+\S+@[0-9a-fA-F]{40}\b")
    files = [_repo_root() / "action.yml"]
    workflows = _repo_root() / ".github" / "workflows"
    files.extend(sorted(workflows.glob("*.yml")))
    files.extend(sorted(workflows.glob("*.yaml")))
    for path in files:
        text = path.read_text(encoding="utf-8")
        match = sha_uses.search(text)
        assert match is None, f"{path} pins an action to a commit SHA: {match.group(0)}"


def test_examples_load() -> None:
    cases = load_case(_repo_root() / "examples")
    ids = {case.case_id for case in cases}
    assert "hello" in ids
    assert "windowsrescue/flush_dns" in ids


@pytest.mark.windows
def test_examples_run() -> None:
    cases = load_case(_repo_root() / "examples")
    results = run_cases(cases, safe_defaults=True, jobs=1)
    assert results
    assert all(result.outcome == Outcome.PASS for result in results)
