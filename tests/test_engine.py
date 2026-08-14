"""Tests for encoding helpers and cmd.exe engine."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import pytest

from battest.encoding import console_encoding, decode_output
from battest.engine import (
    EngineError,
    _combined_env,
    build_cmd_line,
    cmd_executable,
    collapse_path_keys,
    execute_case,
    execute_cases,
    kill_process_tree,
    require_windows,
)
from battest.models import Case, EngineConfig, Expect, Outcome, OutputMatcher, RunResult
from battest.schema import load_cases_from_path


def test_decode_output_empty_and_utf8() -> None:
    assert decode_output(b"", "utf-8") == ""
    assert decode_output(b"hello", "utf-8") == "hello"


def test_decode_output_fallback() -> None:
    text = decode_output(b"\xff\xfe h", "utf-8")
    assert isinstance(text, str)
    assert text != ""


def test_console_encoding_is_string() -> None:
    encoding = console_encoding()
    assert isinstance(encoding, str)
    assert encoding


def test_build_cmd_line_uses_cmd_d_s_c(tmp_path: Path) -> None:
    wrapper = tmp_path / "w.cmd"
    command = build_cmd_line(wrapper, ["a", "b c"])
    assert command[1:4] == ["/d", "/s", "/c"]
    assert "call" in command[-1]


def test_cmd_executable_string() -> None:
    assert "cmd" in cmd_executable().lower()


def test_require_windows_on_non_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    with pytest.raises(EngineError, match="Windows"):
        require_windows()


def test_collapse_path_keys_last_duplicate_wins() -> None:
    env = {"Path": "a", "PATH": "b", "FOO": "1"}
    key = collapse_path_keys(env)
    assert key == "PATH"
    assert env == {"FOO": "1", "PATH": "b"}


def test_collapse_path_keys_preserves_windows_casing() -> None:
    env = {"Path": "a"}
    assert collapse_path_keys(env) == "Path"
    assert env == {"Path": "a"}


def test_combined_env_prefixes_mock_and_collapses_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("Path", "C:\\Windows")
    script = tmp_path / "run.cmd"
    script.write_text("@echo off\n", encoding="utf-8")
    case = Case(
        case_id="t",
        description="t",
        source_path=tmp_path / "t.yaml",
        script_path=script,
        env={"PATH": "C:\\custom"},
        expect=Expect(),
    )
    mock_dir = tmp_path / "mocks"
    mock_dir.mkdir()
    env = _combined_env(case, tmp_path, mock_dir)
    path_keys = [key for key in env if key.upper() == "PATH"]
    assert len(path_keys) == 1
    value = env[path_keys[0]]
    assert value.startswith(str(mock_dir))
    assert "C:\\custom" in value
    assert env["NoDefaultCurrentDirectoryInEXEPath"] == "1"


def test_kill_process_tree_invokes_taskkill(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[list[str]] = []

    def fake_run(
        command: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        seen.append(command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    kill_process_tree(1234)
    assert seen[0][:3] == ["taskkill", "/F", "/T"]


def _write_case(tmp_path: Path, body: str, yaml_body: str, name: str = "run") -> Case:
    script = tmp_path / f"{name}.cmd"
    script.write_text(body, encoding="utf-8")
    manifest = tmp_path / f"{name}.battest.yaml"
    manifest.write_text(yaml_body, encoding="utf-8")
    cases = load_cases_from_path(manifest)
    return cases[0]


@pytest.mark.windows
def test_engine_echo_and_exit(tmp_path: Path) -> None:
    case = _write_case(
        tmp_path,
        "@echo off\r\necho hello-battest\r\nexit /b 7\r\n",
        "\n".join(
            [
                "description: echo",
                "script: run.cmd",
                "expect:",
                "  exit_code: 7",
                "  stdout:",
                "    contains: hello-battest",
            ]
        ),
    )
    result = execute_case(case, EngineConfig())
    assert result.outcome == Outcome.PASS
    assert result.exit_code == 7


@pytest.mark.windows
def test_engine_env_leak_versus_setlocal(tmp_path: Path) -> None:
    leaked = _write_case(
        tmp_path,
        "@echo off\r\nset LEAKEDVAR=visible\r\nexit /b 0\r\n",
        "\n".join(
            [
                "description: leak",
                "script: run.cmd",
                "expect:",
                "  exit_code: 0",
                "  env:",
                "    LEAKEDVAR: visible",
            ]
        ),
        name="run",
    )
    result = execute_case(leaked, EngineConfig())
    assert result.outcome == Outcome.PASS
    hidden_script = tmp_path / "hidden.cmd"
    hidden_script.write_text(
        "@echo off\r\nsetlocal\r\nset HIDDENVAR=nope\r\nexit /b 0\r\n",
        encoding="utf-8",
    )
    hidden_yaml = tmp_path / "hidden.battest.yaml"
    hidden_yaml.write_text(
        "\n".join(
            [
                "description: hidden",
                "script: hidden.cmd",
                "expect:",
                "  exit_code: 0",
                "  env:",
                "    unset: [HIDDENVAR]",
            ]
        ),
        encoding="utf-8",
    )
    hidden = load_cases_from_path(hidden_yaml)[0]
    hidden_result = execute_case(hidden, EngineConfig())
    assert hidden_result.outcome == Outcome.PASS


@pytest.mark.windows
def test_engine_file_and_stderr(tmp_path: Path) -> None:
    case = _write_case(
        tmp_path,
        "@echo off\r\necho out-text\r\necho err-text 1>&2\r\necho file-text>out.txt\r\nexit /b 0\r\n",
        "\n".join(
            [
                "description: streams",
                "script: run.cmd",
                "expect:",
                "  exit_code: 0",
                "  stdout:",
                "    contains: out-text",
                "  stderr:",
                "    contains: err-text",
                "  files:",
                "    - path: out.txt",
                "      exists: true",
                "      contains: file-text",
            ]
        ),
    )
    result = execute_case(case, EngineConfig())
    assert result.outcome == Outcome.PASS, result.failures


@pytest.mark.windows
def test_engine_setup_teardown_and_copy(tmp_path: Path) -> None:
    (tmp_path / "seed.txt").write_text("seeded", encoding="utf-8")
    (tmp_path / "setup.cmd").write_text(
        "@echo off\r\necho setup-ran>setup.txt\r\nexit /b 0\r\n",
        encoding="utf-8",
    )
    (tmp_path / "teardown.cmd").write_text(
        "@echo off\r\nexit /b 0\r\n", encoding="utf-8"
    )
    case = _write_case(
        tmp_path,
        "@echo off\r\nexit /b 0\r\n",
        "\n".join(
            [
                "description: hooks",
                "script: run.cmd",
                "setup: setup.cmd",
                "teardown: teardown.cmd",
                "copy: [seed.txt]",
                "expect:",
                "  exit_code: 0",
                "  files:",
                "    - path: setup.txt",
                "      exists: true",
                "    - path: seed.txt",
                "      contains: seeded",
            ]
        ),
    )
    result = execute_case(case, EngineConfig())
    assert result.outcome == Outcome.PASS, result.failures


@pytest.mark.windows
def test_engine_timeout(tmp_path: Path) -> None:
    case = _write_case(
        tmp_path,
        "@echo off\r\nping 127.0.0.1 -n 20 >nul\r\nexit /b 0\r\n",
        "\n".join(
            [
                "description: timeout",
                "script: run.cmd",
                "timeout_seconds: 1",
                "expect:",
                "  exit_code: 0",
            ]
        ),
    )
    result = execute_case(case, EngineConfig())
    assert result.outcome == Outcome.TIMEOUT


@pytest.mark.windows
def test_engine_path_mock(tmp_path: Path) -> None:
    case = _write_case(
        tmp_path,
        "@echo off\r\nipconfig /flushdns\r\nexit /b %errorlevel%\r\n",
        "\n".join(
            [
                "description: mock ipconfig",
                "script: run.cmd",
                "mocks:",
                "  ipconfig:",
                "    exit_code: 0",
                "    stdout: flushed-ok",
                "    expect_calls:",
                "      - args_contains: /flushdns",
                "expect:",
                "  exit_code: 0",
                "  stdout:",
                "    contains: flushed-ok",
            ]
        ),
    )
    result = execute_case(case, EngineConfig())
    assert result.outcome == Outcome.PASS, (
        result.failures,
        result.stdout,
        result.stderr,
    )


@pytest.mark.windows
def test_engine_path_mock_returns_to_caller(tmp_path: Path) -> None:
    case = _write_case(
        tmp_path,
        "@echo off\r\nnet session\r\necho after-net\r\nexit /b 0\r\n",
        "\n".join(
            [
                "description: mock net then continue",
                "script: run.cmd",
                "mocks:",
                "  net:",
                "    exit_code: 0",
                "    expect_calls:",
                "      - args_contains: session",
                "expect:",
                "  exit_code: 0",
                "  stdout:",
                "    contains: after-net",
            ]
        ),
    )
    result = execute_case(case, EngineConfig())
    assert result.outcome == Outcome.PASS, (
        result.failures,
        result.stdout,
        result.stderr,
    )


@pytest.mark.windows
def test_engine_safe_defaults_blocks_format(tmp_path: Path) -> None:
    case = _write_case(
        tmp_path,
        "@echo off\r\nformat Z: /y\r\nexit /b %errorlevel%\r\n",
        "\n".join(
            [
                "description: format blocked",
                "script: run.cmd",
                "expect:",
                "  exit_code: 1",
                "  stderr:",
                "    contains: safe-defaults",
            ]
        ),
    )
    result = execute_case(case, EngineConfig(safe_defaults=True))
    assert result.outcome == Outcome.PASS, (
        result.failures,
        result.stdout,
        result.stderr,
    )


@pytest.mark.windows
def test_engine_failure_outcome(tmp_path: Path) -> None:
    case = _write_case(
        tmp_path,
        "@echo off\r\nexit /b 0\r\n",
        "description: fail\nscript: run.cmd\nexpect:\n  exit_code: 1\n",
    )
    result = execute_case(case, EngineConfig())
    assert result.outcome == Outcome.FAIL


@pytest.mark.windows
def test_execute_cases_jobs(tmp_path: Path) -> None:
    first = _write_case(
        tmp_path,
        "@echo off\r\nexit /b 0\r\n",
        "description: one\nscript: run.cmd\nexpect:\n  exit_code: 0\n",
        name="run",
    )
    second_script = tmp_path / "two.cmd"
    second_script.write_text("@echo off\r\nexit /b 0\r\n", encoding="utf-8")
    second_yaml = tmp_path / "two.battest.yaml"
    second_yaml.write_text(
        "description: two\nscript: two.cmd\nexpect:\n  exit_code: 0\n",
        encoding="utf-8",
    )
    second = load_cases_from_path(second_yaml)[0]
    results = execute_cases([first, second], EngineConfig(jobs=2))
    assert [item.outcome for item in results] == [Outcome.PASS, Outcome.PASS]


@pytest.mark.windows
def test_engine_setup_error(tmp_path: Path) -> None:
    (tmp_path / "setup.cmd").write_text("@echo off\r\nexit /b 9\r\n", encoding="utf-8")
    case = _write_case(
        tmp_path,
        "@echo off\r\nexit /b 0\r\n",
        "\n".join(
            [
                "description: setup fail",
                "script: run.cmd",
                "setup: setup.cmd",
                "expect:",
                "  exit_code: 0",
            ]
        ),
    )
    result = execute_case(case, EngineConfig())
    assert result.outcome == Outcome.ERROR
    assert result.error_message is not None
    assert "setup failed" in result.error_message


def test_execute_cases_worker_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    script = tmp_path / "input.cmd"
    script.write_text("@echo off\n", encoding="utf-8")
    first = Case(
        case_id="a",
        description="a",
        source_path=tmp_path / "expect.yaml",
        script_path=script,
        expect=Expect(exit_code=0),
    )
    second = first.model_copy(update={"case_id": "b", "description": "b"})

    def boom(_case: Case, _config: EngineConfig) -> RunResult:
        raise RuntimeError("boom")

    monkeypatch.setattr("battest.engine.execute_case", boom)
    results = execute_cases([first, second], EngineConfig(jobs=2))
    assert [item.outcome for item in results] == [Outcome.ERROR, Outcome.ERROR]


def test_execute_case_requires_windows(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    script = tmp_path / "input.cmd"
    script.write_text("@echo off\n", encoding="utf-8")
    case = Case(
        case_id="x",
        description="x",
        source_path=tmp_path / "expect.yaml",
        script_path=script,
        expect=Expect(exit_code=0, stdout=OutputMatcher(contains="x")),
    )
    with pytest.raises(EngineError):
        execute_case(case, EngineConfig())
