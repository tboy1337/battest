"""Tests for encoding helpers and cmd.exe engine."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import time

try:
    import _winapi
except ImportError:
    _winapi = None  # type: ignore[assignment]

import pytest
from pytest_mock import MockerFixture

from battest.constants import (
    CWD_DUMP_NAME,
    ENV_DUMP_NAME,
    MAX_CAPTURE_BYTES,
    TEARDOWN_MIN_SECONDS,
    WRAPPER_NAME,
)
from battest.encoding import console_encoding, decode_output
from battest.engine import (
    EngineError,
    _combined_env,
    _evaluate_after_run,
    _prepare_work_dir,
    _reject_blocking_env_dump,
    _run_process,
    _script_warnings,
    _seed_work_dir,
    _snapshot_env,
    build_wrapper_text,
    collapse_path_keys,
    execute_case,
    execute_cases,
    remaining_timeout,
    require_windows,
    resolved_timeout,
    teardown_timeout,
    wrapper_sut_relative,
)
from battest.mocks import MockError
from battest.models import (
    Case,
    EngineConfig,
    EnvExpect,
    Expect,
    MockSpec,
    Outcome,
    OutputMatcher,
    RunResult,
)
from battest.process import (
    ProcessResult,
    _assign_and_resume,
    _close_job,
    _create_kill_on_close_job,
    _handle_as_int,
    _join_readers,
    _read_capped_stream,
    _write_stdin,
    abandon_lingering_process,
    build_cmd_line,
    close_process_streams,
    cmd_executable,
    coerce_process_result,
    is_path_outside_directory,
    kill_process_tree,
    system32_executable,
)
from battest.schema import load_cases_from_path


def test_decode_output_empty_and_utf8() -> None:
    assert decode_output(b"", "utf-8") == ""
    assert decode_output(b"hello", "utf-8") == "hello"


def test_decode_output_fallback() -> None:
    text = decode_output(b"\xff\xfe h", "utf-8")
    assert isinstance(text, str)
    assert text


def test_console_encoding_is_string() -> None:
    encoding = console_encoding()
    assert isinstance(encoding, str)
    assert encoding


def test_console_encoding_non_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    assert console_encoding() == "utf-8"


def test_console_encoding_code_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")

    class FakeKernel:
        def __init__(self, code_page: int, oem: int = 0, acp: int = 0) -> None:
            self._code_page = code_page
            self._oem = oem
            self._acp = acp

        def GetConsoleOutputCP(self) -> int:
            return self._code_page

        def GetOEMCP(self) -> int:
            return self._oem

        def GetACP(self) -> int:
            return self._acp

    class FakeCtypes:
        def __init__(self, code_page: int, oem: int = 0, acp: int = 0) -> None:
            self.windll = type("W", (), {"kernel32": FakeKernel(code_page, oem, acp)})()

    monkeypatch.setattr("battest.encoding.ctypes", FakeCtypes(437))
    assert console_encoding() == "cp437"
    monkeypatch.setattr("battest.encoding.ctypes", FakeCtypes(65001))
    assert console_encoding() == "utf-8"
    monkeypatch.setattr("battest.encoding.ctypes", FakeCtypes(0))
    assert console_encoding() == "utf-8"
    monkeypatch.setattr("battest.encoding.ctypes", FakeCtypes(0, oem=437))
    assert console_encoding() == "cp437"
    monkeypatch.setattr("battest.encoding.ctypes", FakeCtypes(0, oem=0, acp=1252))
    assert console_encoding() == "cp1252"


def test_console_encoding_without_windll(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")

    class FakeCtypes:
        windll = None

    monkeypatch.setattr("battest.encoding.ctypes", FakeCtypes())
    assert console_encoding() == "utf-8"


def test_decode_output_replace_when_undetected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class EmptyDetect:
        def best(self) -> None:
            return None

    monkeypatch.setattr("battest.encoding.from_bytes", lambda _data: EmptyDetect())
    text = decode_output(b"\xff", "ascii")
    assert "\ufffd" in text


def test_build_cmd_line_uses_cmd_d_s_c(tmp_path: Path) -> None:
    wrapper = tmp_path / "w.cmd"
    command = build_cmd_line(wrapper, ["a", "b c"])
    assert command[1:4] == ["/d", "/s", "/c"]
    assert "call" in command[-1]


def test_cmd_executable_string() -> None:
    assert "cmd" in cmd_executable().lower()


def test_cmd_executable_falls_back_when_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SystemRoot", str(tmp_path))
    assert cmd_executable() == "cmd.exe"


def test_system32_executable_prefers_file_then_falls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    system32 = tmp_path / "System32"
    system32.mkdir()
    taskkill = system32 / "taskkill.exe"
    taskkill.write_bytes(b"MZ")
    monkeypatch.setenv("SystemRoot", str(tmp_path))
    assert system32_executable("taskkill.exe") == str(taskkill)
    monkeypatch.setenv("SystemRoot", str(tmp_path / "missing-root"))
    assert system32_executable("taskkill.exe") == "taskkill.exe"


def test_seed_work_dir_copies_directory(tmp_path: Path) -> None:
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    (fixtures / "a.txt").write_text("nested", encoding="utf-8")
    work = tmp_path / "work"
    work.mkdir()
    _seed_work_dir(work, [fixtures], tmp_path)
    assert (work / "fixtures" / "a.txt").read_text(encoding="utf-8") == "nested"


def test_seed_work_dir_overlapping_directories(tmp_path: Path) -> None:
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    (fixtures / "a.txt").write_text("nested", encoding="utf-8")
    nested = fixtures / "sub"
    nested.mkdir()
    (nested / "b.txt").write_text("inner", encoding="utf-8")
    work = tmp_path / "work"
    work.mkdir()
    _seed_work_dir(work, [fixtures, nested], tmp_path)
    assert (work / "fixtures" / "a.txt").read_text(encoding="utf-8") == "nested"
    assert (work / "fixtures" / "sub" / "b.txt").read_text(encoding="utf-8") == "inner"


def test_script_warnings_oserror(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    script = tmp_path / "run.cmd"
    script.write_text("@echo off\n", encoding="utf-8")
    case = Case(
        case_id="t",
        description="t",
        source_path=tmp_path / "t.yaml",
        script_path=script,
        expect=Expect(exit_code=0),
        warnings=["existing"],
    )

    def boom(self: Path, *args: object, **kwargs: object) -> str:
        raise OSError("locked")

    monkeypatch.setattr(Path, "read_text", boom)
    with caplog.at_level("ERROR", logger="battest.engine"):
        warnings = _script_warnings(case)
    assert warnings == ["existing"]
    assert "cannot read script" in caplog.text


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


@pytest.mark.parametrize("key", ["Path", "PATH", "path"])
def test_collapse_path_keys_keeps_one_path(key: str) -> None:
    value = r"C:\Windows\System32"
    env = {key: value, "FOO": "1"}
    kept = collapse_path_keys(env)
    path_keys = [name for name in env if name.upper() == "PATH"]
    assert kept.upper() == "PATH"
    assert path_keys == [kept]
    assert env[kept] == value


def test_resolved_timeout_uses_config_when_case_omits(tmp_path: Path) -> None:
    script = tmp_path / "run.cmd"
    script.write_text("@echo off\n", encoding="utf-8")
    omitted = Case(
        case_id="t",
        description="t",
        source_path=tmp_path / "t.yaml",
        script_path=script,
        timeout_seconds=None,
        expect=Expect(),
    )
    config = EngineConfig(default_timeout_seconds=1.5)
    assert resolved_timeout(omitted, config) == 1.5
    explicit = omitted.model_copy(update={"timeout_seconds": 12.0})
    assert resolved_timeout(explicit, config) == 12.0
    assert remaining_timeout(time.perf_counter() - 5.0) == 0.0


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
    assert "BATTEST_SUT" not in env
    assert "BATTEST_ENVFILE" not in env


def test_combined_env_case_path_wins_over_posix_path_and_PATH(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fixture PATH must replace inherited Path/PATH even when both exist."""
    monkeypatch.setattr(
        "battest.engine.os.environ",
        {
            "PATH": "C:\\from-process",
            "Path": "C:\\Windows",
            "OTHER": "keep",
        },
    )
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
    assert "C:\\from-process" not in value
    assert "C:\\Windows" not in value
    assert env["OTHER"] == "keep"


def test_combined_env_without_fixture_path_keeps_inherited(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "battest.engine.os.environ",
        {"PATH": "C:\\Windows", "FOO": "1"},
    )
    script = tmp_path / "run.cmd"
    script.write_text("@echo off\n", encoding="utf-8")
    case = Case(
        case_id="t",
        description="t",
        source_path=tmp_path / "t.yaml",
        script_path=script,
        env={"FOO": "bar"},
        expect=Expect(),
    )
    env = _combined_env(case, tmp_path, None)
    path_keys = [key for key in env if key.upper() == "PATH"]
    assert len(path_keys) == 1
    assert env[path_keys[0]] == "C:\\Windows"
    assert env["FOO"] == "bar"


def test_combined_env_strips_inherited_battest_helpers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(
        "battest.engine.os.environ",
        {
            "PATH": "C:\\Windows",
            "BATTEST_SUT": "leaked",
            "battest_envfile": "also-leaked",
            "FOO": "keep",
        },
    )
    script = tmp_path / "run.cmd"
    script.write_text("@echo off\n", encoding="utf-8")
    case = Case(
        case_id="t",
        description="t",
        source_path=tmp_path / "t.yaml",
        script_path=script,
        env={"BATTEST_CUSTOM": "from-fixture"},
        expect=Expect(),
    )
    with caplog.at_level("DEBUG", logger="battest.engine"):
        env = _combined_env(case, tmp_path, None)
    assert "BATTEST_SUT" not in env
    assert "battest_envfile" not in env
    assert env["BATTEST_CUSTOM"] == "from-fixture"
    assert env["FOO"] == "keep"
    assert "fixture_battest_keys=True" in caplog.text


def test_evaluate_after_run_errors_when_call_logs_unreadable(
    tmp_path: Path, mocker: MockerFixture
) -> None:
    script = tmp_path / "run.cmd"
    script.write_text("@echo off\n", encoding="utf-8")
    case = Case(
        case_id="t",
        description="t",
        source_path=tmp_path / "t.yaml",
        script_path=script,
        expect=Expect(),
    )
    mocker.patch(
        "battest.engine.read_call_logs",
        side_effect=MockError("cannot read call log ipconfig.log"),
    )
    result = _evaluate_after_run(
        case,
        EngineConfig(),
        tmp_path,
        tmp_path / "mocks",
        "utf-8",
        30.0,
        [],
        0.1,
        0,
        "",
        "",
        False,
    )
    assert result.outcome == Outcome.ERROR
    assert result.error_message is not None
    assert "cannot read call log" in result.error_message


def test_kill_process_tree_invokes_taskkill(mocker: MockerFixture) -> None:
    seen: list[list[str]] = []
    timeouts: list[object] = []

    def fake_run(
        command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        seen.append(command)
        timeouts.append(kwargs.get("timeout"))
        return subprocess.CompletedProcess(command, 0)

    mocker.patch("battest.process.subprocess.run", fake_run)
    kill_process_tree(1234)
    assert Path(seen[0][0]).name.lower() in {"taskkill", "taskkill.exe"}
    assert seen[0][1:4] == ["/F", "/T", "/PID"]
    assert seen[0][4] == "1234"
    assert timeouts[0] is not None


def test_kill_process_tree_logs_nonzero_return(
    mocker: MockerFixture, caplog: pytest.LogCaptureFixture
) -> None:
    def fake_run(
        command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            command, 1, stdout="", stderr="Access denied"
        )

    mocker.patch("battest.process.subprocess.run", fake_run)
    with caplog.at_level("WARNING", logger="battest.process"):
        kill_process_tree(55)
    assert "returned 1" in caplog.text
    assert "Access denied" in caplog.text


def test_kill_process_tree_timeout_is_logged(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def fake_run(*_args: object, **_kwargs: object) -> None:
        raise subprocess.TimeoutExpired(cmd="taskkill", timeout=1)

    monkeypatch.setattr("battest.process.subprocess.run", fake_run)
    with caplog.at_level("ERROR", logger="battest.process"):
        kill_process_tree(99)
    assert "taskkill timed out" in caplog.text


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
def test_engine_asserts_before_teardown_deletes_files(tmp_path: Path) -> None:
    (tmp_path / "setup.cmd").write_text(
        "@echo off\r\necho setup-ran>setup.txt\r\nexit /b 0\r\n",
        encoding="utf-8",
    )
    (tmp_path / "teardown.cmd").write_text(
        "@echo off\r\ndel setup.txt\r\nexit /b 0\r\n",
        encoding="utf-8",
    )
    case = _write_case(
        tmp_path,
        "@echo off\r\nexit /b 0\r\n",
        "\n".join(
            [
                "description: teardown deletes asserted file",
                "script: run.cmd",
                "setup: setup.cmd",
                "teardown: teardown.cmd",
                "expect:",
                "  exit_code: 0",
                "  files:",
                "    - path: setup.txt",
                "      exists: true",
                "      contains: setup-ran",
            ]
        ),
    )
    result = execute_case(case, EngineConfig())
    assert result.outcome == Outcome.PASS, result.failures


@pytest.mark.windows
def test_engine_setup_failure_still_runs_teardown(tmp_path: Path) -> None:
    (tmp_path / "setup.cmd").write_text("@echo off\r\nexit /b 9\r\n", encoding="utf-8")
    (tmp_path / "teardown.cmd").write_text(
        "@echo off\r\necho torn-down>torn.txt\r\nexit /b 0\r\n",
        encoding="utf-8",
    )
    case = _write_case(
        tmp_path,
        "@echo off\r\nexit /b 0\r\n",
        "\n".join(
            [
                "description: setup fail still tears down",
                "script: run.cmd",
                "setup: setup.cmd",
                "teardown: teardown.cmd",
                "expect:",
                "  exit_code: 0",
            ]
        ),
    )
    result = execute_case(case, EngineConfig())
    assert result.outcome == Outcome.ERROR
    assert result.error_message is not None
    assert "setup failed" in result.error_message


@pytest.mark.windows
def test_engine_teardown_failure_errors_passing_case(tmp_path: Path) -> None:
    (tmp_path / "teardown.cmd").write_text(
        "@echo off\r\nexit /b 4\r\n", encoding="utf-8"
    )
    case = _write_case(
        tmp_path,
        "@echo off\r\nexit /b 0\r\n",
        "\n".join(
            [
                "description: teardown fails",
                "script: run.cmd",
                "teardown: teardown.cmd",
                "expect:",
                "  exit_code: 0",
            ]
        ),
    )
    result = execute_case(case, EngineConfig())
    assert result.outcome == Outcome.ERROR
    assert result.error_message is not None
    assert "teardown failed" in result.error_message


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
def test_engine_dp0_write_stays_in_workdir(tmp_path: Path) -> None:
    case = _write_case(
        tmp_path,
        '@echo off\r\necho leaked> "%~dp0leaked.txt"\r\nexit /b 0\r\n',
        "\n".join(
            [
                "description: dp0 isolation",
                "script: run.cmd",
                "expect:",
                "  exit_code: 0",
                "  files:",
                "    - path: leaked.txt",
                "      exists: true",
            ]
        ),
    )
    result = execute_case(case, EngineConfig())
    assert result.outcome == Outcome.PASS, result.failures
    assert not (tmp_path / "leaked.txt").exists()


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
        description="alpha",
        source_path=tmp_path / "expect.yaml",
        script_path=script,
        expect=Expect(exit_code=0),
    )
    second = first.model_copy(update={"case_id": "b", "description": "beta"})

    def boom(_case: Case, _config: EngineConfig) -> RunResult:
        raise RuntimeError("boom")

    monkeypatch.setattr("battest.engine.execute_case", boom)
    results = execute_cases([first, second], EngineConfig(jobs=2))
    assert [item.outcome for item in results] == [Outcome.ERROR, Outcome.ERROR]
    assert [item.description for item in results] == ["alpha", "beta"]
    assert results[0].error_message == "boom"


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


def test_seed_work_dir_preserves_relative_layout(tmp_path: Path) -> None:
    base = tmp_path / "fixture"
    nested = base / "fixtures"
    nested.mkdir(parents=True)
    (nested / "seed.txt").write_text("seeded", encoding="utf-8")
    work = tmp_path / "work"
    work.mkdir()
    _seed_work_dir(work, [nested / "seed.txt"], base)
    assert (work / "fixtures" / "seed.txt").read_text(encoding="utf-8") == "seeded"


def test_prepare_work_dir_copies_script_setup_teardown(tmp_path: Path) -> None:
    script = tmp_path / "run.cmd"
    script.write_text("@echo off\n", encoding="utf-8")
    setup = tmp_path / "setup.cmd"
    setup.write_text("@echo off\n", encoding="utf-8")
    teardown = tmp_path / "teardown.cmd"
    teardown.write_text("@echo off\n", encoding="utf-8")
    case = Case(
        case_id="t",
        description="t",
        source_path=tmp_path / "t.yaml",
        script_path=script,
        setup_path=setup,
        teardown_path=teardown,
        expect=Expect(exit_code=0),
    )
    work = tmp_path / "work"
    work.mkdir()
    prepared = _prepare_work_dir(case, EngineConfig(), work)
    copied_script = work / "run.cmd"
    assert copied_script.is_file()
    assert copied_script.resolve() != script.resolve()
    assert "BATTEST_SUT" not in prepared.env
    assert "BATTEST_ENVFILE" not in prepared.env
    wrapper_text = (work / WRAPPER_NAME).read_text(encoding="utf-8")
    assert "%~dp0run.cmd" in wrapper_text
    assert "_bt_env" not in wrapper_text
    assert "_bt_sut" not in wrapper_text
    assert (work / "setup.cmd").is_file()
    assert (work / "teardown.cmd").is_file()


def test_seed_work_dir_rejects_escaping_symlink(tmp_path: Path) -> None:
    base = tmp_path / "fixtures"
    base.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("classified", encoding="utf-8")
    link = base / "link.txt"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("creating symlinks is not permitted on this host")
    work = tmp_path / "work"
    work.mkdir()
    with pytest.raises(ValueError, match="symlink or junction"):
        _seed_work_dir(work, [link], base)


def test_seed_work_dir_rejects_escaping_junction(tmp_path: Path) -> None:
    if _winapi is None:
        pytest.skip("junctions are not available on this host")
    base = tmp_path / "fixtures"
    base.mkdir()
    outside = tmp_path / "secret-dir"
    outside.mkdir()
    (outside / "secret.txt").write_text("classified", encoding="utf-8")
    link = base / "leak"
    try:
        _winapi.CreateJunction(str(outside), str(link))
    except OSError:
        pytest.skip("creating junctions is not permitted on this host")
    work = tmp_path / "work"
    work.mkdir()
    with pytest.raises(ValueError, match="symlink or junction"):
        _seed_work_dir(work, [link], base)


def test_teardown_oserror_is_logged(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr("battest.engine.require_windows", lambda: None)
    monkeypatch.setattr("battest.engine.console_encoding", lambda: "utf-8")
    teardown = tmp_path / "teardown.cmd"
    teardown.write_text("@echo off\n", encoding="utf-8")
    script = tmp_path / "run.cmd"
    script.write_text("@echo off\n", encoding="utf-8")
    case = Case(
        case_id="t",
        description="t",
        source_path=tmp_path / "t.yaml",
        script_path=script,
        teardown_path=teardown,
        expect=Expect(exit_code=0),
    )
    calls = {"n": 0}

    def fake_run(
        _command: list[str],
        _cwd: Path,
        _env: dict[str, str],
        _stdin: str,
        _timeout: float,
        _encoding: str,
    ) -> tuple[int, str, str, bool]:
        calls["n"] += 1
        if calls["n"] >= 2:
            raise OSError("teardown boom")
        return 0, "", "", False

    monkeypatch.setattr("battest.engine._run_process", fake_run)
    with caplog.at_level("ERROR", logger="battest.engine"):
        result = execute_case(case, EngineConfig())
    assert result.outcome == Outcome.ERROR
    assert result.error_message is not None
    assert "teardown boom" in result.error_message
    assert "teardown boom" in caplog.text


def test_setup_oserror_is_logged(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr("battest.engine.require_windows", lambda: None)
    monkeypatch.setattr("battest.engine.console_encoding", lambda: "utf-8")
    setup = tmp_path / "setup.cmd"
    setup.write_text("@echo off\n", encoding="utf-8")
    script = tmp_path / "run.cmd"
    script.write_text("@echo off\n", encoding="utf-8")
    case = Case(
        case_id="s",
        description="s",
        source_path=tmp_path / "s.yaml",
        script_path=script,
        setup_path=setup,
        expect=Expect(exit_code=0),
    )

    def fake_run(
        _command: list[str],
        _cwd: Path,
        _env: dict[str, str],
        _stdin: str,
        _timeout: float,
        _encoding: str,
    ) -> tuple[int, str, str, bool]:
        raise OSError("setup boom")

    monkeypatch.setattr("battest.engine._run_process", fake_run)
    with caplog.at_level("ERROR", logger="battest.engine"):
        result = execute_case(case, EngineConfig())
    assert result.outcome == Outcome.ERROR
    assert result.error_message is not None
    assert "setup boom" in result.error_message
    assert "setup boom" in caplog.text


def test_sut_oserror_is_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr("battest.engine.require_windows", lambda: None)
    monkeypatch.setattr("battest.engine.console_encoding", lambda: "utf-8")
    script = tmp_path / "run.cmd"
    script.write_text("@echo off\n", encoding="utf-8")
    case = Case(
        case_id="x",
        description="x",
        source_path=tmp_path / "x.yaml",
        script_path=script,
        expect=Expect(exit_code=0),
    )

    def fake_run(
        _command: list[str],
        _cwd: Path,
        _env: dict[str, str],
        _stdin: str,
        _timeout: float,
        _encoding: str,
    ) -> tuple[int, str, str, bool]:
        raise OSError("cmd missing")

    monkeypatch.setattr("battest.engine._run_process", fake_run)
    with caplog.at_level("ERROR", logger="battest.engine"):
        result = execute_case(case, EngineConfig())
    assert result.outcome == Outcome.ERROR
    assert result.error_message is not None
    assert "cmd missing" in result.error_message
    assert "cmd missing" in caplog.text


def test_mock_error_becomes_error_result(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("battest.engine.require_windows", lambda: None)
    monkeypatch.setattr("battest.engine.console_encoding", lambda: "utf-8")
    script = tmp_path / "run.cmd"
    script.write_text("@echo off\n", encoding="utf-8")
    case = Case(
        case_id="m",
        description="m",
        source_path=tmp_path / "m.yaml",
        script_path=script,
        mocks={"ipconfig": MockSpec()},
        expect=Expect(exit_code=0),
    )

    def boom(_root: Path, _mocks: dict[str, MockSpec], **_kwargs: object) -> Path:
        raise MockError("battest_stub.exe is missing")

    monkeypatch.setattr("battest.engine.write_mock_tree", boom)
    result = execute_case(case, EngineConfig())
    assert result.outcome == Outcome.ERROR
    assert result.error_message is not None
    assert "battest_stub.exe is missing" in result.error_message


def test_prepare_valueerror_is_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("battest.engine.require_windows", lambda: None)
    monkeypatch.setattr("battest.engine.console_encoding", lambda: "utf-8")
    script = tmp_path / "run.cmd"
    script.write_text("@echo off\n", encoding="utf-8")
    case = Case(
        case_id="v",
        description="v",
        source_path=tmp_path / "v.yaml",
        script_path=script,
        expect=Expect(exit_code=0),
    )

    def boom(_work_dir: Path, _copy_paths: list[Path], _base_dir: Path) -> None:
        raise ValueError("path escapes fixture directory")

    monkeypatch.setattr("battest.engine._seed_work_dir", boom)
    result = execute_case(case, EngineConfig())
    assert result.outcome == Outcome.ERROR
    assert result.error_message is not None
    assert "path escapes fixture directory" in result.error_message


def test_teardown_failure_keeps_fail_outcome(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("battest.engine.require_windows", lambda: None)
    monkeypatch.setattr("battest.engine.console_encoding", lambda: "utf-8")
    teardown = tmp_path / "teardown.cmd"
    teardown.write_text("@echo off\n", encoding="utf-8")
    script = tmp_path / "run.cmd"
    script.write_text("@echo off\n", encoding="utf-8")
    case = Case(
        case_id="t",
        description="t",
        source_path=tmp_path / "t.yaml",
        script_path=script,
        teardown_path=teardown,
        expect=Expect(exit_code=0),
    )
    calls = {"n": 0}

    def fake_run(
        _command: list[str],
        _cwd: Path,
        _env: dict[str, str],
        _stdin: str,
        _timeout: float,
        _encoding: str,
    ) -> tuple[int, str, str, bool]:
        calls["n"] += 1
        if calls["n"] == 1:
            return 1, "", "", False
        return 4, "", "teardown-err", False

    monkeypatch.setattr("battest.engine._run_process", fake_run)
    result = execute_case(case, EngineConfig())
    assert result.outcome == Outcome.FAIL
    assert any("teardown failed" in item for item in result.warnings)


def test_run_process_success_and_timeout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class OkStdin:
        def write(self, data: bytes) -> int:
            assert data == b"hi"
            return len(data)

        def flush(self) -> None:
            return None

        def close(self) -> None:
            return None

    class OnceReader:
        def __init__(self, payload: bytes) -> None:
            self._payload = payload
            self._sent = False

        def read(self, _size: int = -1) -> bytes:
            if self._sent:
                return b""
            self._sent = True
            return self._payload

        def close(self) -> None:
            return None

    class OkProcessFixed:
        pid = 7
        returncode = 3

        def __init__(self, *args: object, **kwargs: object) -> None:
            self.stdin = OkStdin()
            self.stdout = OnceReader(b"out")
            self.stderr = OnceReader(b"err")

        def communicate(
            self, input: bytes | None = None, timeout: float | None = None
        ) -> tuple[bytes, bytes]:
            return b"out", b"err"

        def poll(self) -> int | None:
            return self.returncode

        def wait(self, timeout: float | None = None) -> int:
            return 3

        def kill(self) -> None:
            return None

    monkeypatch.setattr("battest.process.subprocess.Popen", OkProcessFixed)
    monkeypatch.setattr("battest.process._create_kill_on_close_job", lambda: None)
    result = _run_process(["cmd"], tmp_path, {}, "hi", 1.0, "utf-8")
    assert result.exit_code == 3
    assert result.stdout == "out"
    assert result.stderr == "err"
    assert result.timed_out is False

    class TimeoutProcess:
        pid = None
        returncode = None
        waited: list[float | None] = []

        def __init__(self, *args: object, **kwargs: object) -> None:
            self.stdin = OkStdin()
            self.stdout = OnceReader(b"")
            self.stderr = OnceReader(b"")

        def communicate(
            self, input: bytes | None = None, timeout: float | None = None
        ) -> tuple[bytes, bytes]:
            raise subprocess.TimeoutExpired(cmd="x", timeout=timeout or 0)

        def poll(self) -> int | None:
            return self.returncode

        def wait(self, timeout: float | None = None) -> int:
            self.waited.append(timeout)
            raise subprocess.TimeoutExpired(cmd="x", timeout=timeout or 0)

        def kill(self) -> None:
            return None

    killed: list[int] = []
    monkeypatch.setattr("battest.process.subprocess.Popen", TimeoutProcess)
    monkeypatch.setattr("battest.process.kill_process_tree", killed.append)
    result = _run_process(["cmd"], tmp_path, {}, "", 0.1, "utf-8")
    assert result.timed_out is True
    assert result.exit_code == -1
    assert killed == []
    assert TimeoutProcess.waited


def test_run_process_does_not_spawn_when_timeout_already_expired(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    spawned: list[object] = []

    class BoomProcess:
        def __init__(self, *args: object, **kwargs: object) -> None:
            spawned.append(args)
            raise AssertionError("Popen must not run when timeout is already expired")

    monkeypatch.setattr("battest.process.subprocess.Popen", BoomProcess)
    result = _run_process(["cmd"], tmp_path, {}, "", 0.0, "utf-8")
    assert result.timed_out is True
    assert result.exit_code == -1
    assert result.stdout == ""
    assert result.stderr == ""
    assert spawned == []


def test_execute_case_times_out_without_spawning_when_budget_already_gone(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("battest.engine.require_windows", lambda: None)
    monkeypatch.setattr("battest.engine.console_encoding", lambda: "utf-8")
    monkeypatch.setattr("battest.engine.remaining_timeout", lambda _deadline: 0.0)
    spawned: list[object] = []

    def track_popen(*args: object, **kwargs: object) -> object:
        spawned.append(args)
        raise AssertionError("Popen must not run when the case budget is gone")

    monkeypatch.setattr("battest.process.subprocess.Popen", track_popen)
    script = tmp_path / "run.cmd"
    script.write_text("@echo off\n", encoding="utf-8")
    case = Case(
        case_id="t",
        description="t",
        source_path=tmp_path / "t.yaml",
        script_path=script,
        expect=Expect(exit_code=0),
    )
    result = execute_case(case, EngineConfig())
    assert result.outcome == Outcome.TIMEOUT
    assert spawned == []


def test_execute_case_setup_timeout_does_not_spawn_when_budget_gone(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("battest.engine.require_windows", lambda: None)
    monkeypatch.setattr("battest.engine.console_encoding", lambda: "utf-8")
    monkeypatch.setattr("battest.engine.remaining_timeout", lambda _deadline: 0.0)
    spawned: list[object] = []

    def track_popen(*args: object, **kwargs: object) -> object:
        spawned.append(args)
        raise AssertionError("Popen must not run when the case budget is gone")

    monkeypatch.setattr("battest.process.subprocess.Popen", track_popen)
    script = tmp_path / "run.cmd"
    script.write_text("@echo off\n", encoding="utf-8")
    setup = tmp_path / "setup.cmd"
    setup.write_text("@echo off\n", encoding="utf-8")
    case = Case(
        case_id="t",
        description="t",
        source_path=tmp_path / "t.yaml",
        script_path=script,
        setup_path=setup,
        expect=Expect(exit_code=0),
    )
    result = execute_case(case, EngineConfig())
    assert result.outcome == Outcome.ERROR
    assert result.error_message is not None
    assert "setup failed" in result.error_message
    assert "timeout=True" in result.error_message
    assert spawned == []


def test_run_process_errors_when_stdin_cannot_encode(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    spawned: list[object] = []

    class BoomProcess:
        def __init__(self, *args: object, **kwargs: object) -> None:
            spawned.append(args)
            raise AssertionError("Popen must not run when stdin cannot encode")

    monkeypatch.setattr("battest.process.subprocess.Popen", BoomProcess)
    with caplog.at_level("ERROR", logger="battest.process"):
        with pytest.raises(UnicodeEncodeError):
            _run_process(["cmd"], tmp_path, {}, "café", 1.0, "ascii")
    assert "cannot be encoded" in caplog.text
    assert spawned == []


def test_execute_case_errors_when_stdin_cannot_encode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("battest.engine.require_windows", lambda: None)
    monkeypatch.setattr("battest.engine.console_encoding", lambda: "ascii")
    spawned: list[object] = []

    def track_popen(*args: object, **kwargs: object) -> object:
        spawned.append(args)
        raise AssertionError("Popen must not run when stdin cannot encode")

    monkeypatch.setattr("battest.process.subprocess.Popen", track_popen)
    script = tmp_path / "run.cmd"
    script.write_text("@echo off\n", encoding="utf-8")
    case = Case(
        case_id="t",
        description="t",
        source_path=tmp_path / "t.yaml",
        script_path=script,
        stdin="café",
        expect=Expect(exit_code=0),
    )
    result = execute_case(case, EngineConfig())
    assert result.outcome == Outcome.ERROR
    assert result.error_message is not None
    assert "stdin" in result.error_message.lower()
    assert spawned == []


def test_execute_cases_preserves_duplicate_case_ids(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    script = tmp_path / "input.cmd"
    script.write_text("@echo off\n", encoding="utf-8")
    first = Case(
        case_id="dup",
        description="alpha",
        source_path=tmp_path / "expect.yaml",
        script_path=script,
        expect=Expect(exit_code=0),
    )
    second = first.model_copy(update={"description": "beta"})

    def fake_execute(case: Case, _config: EngineConfig) -> RunResult:
        return RunResult(
            case_id=case.case_id,
            description=case.description,
            outcome=Outcome.PASS,
        )

    monkeypatch.setattr("battest.engine.execute_case", fake_execute)
    results = execute_cases([first, second], EngineConfig(jobs=2))
    assert [item.description for item in results] == ["alpha", "beta"]
    assert [item.case_id for item in results] == ["dup", "dup"]


def test_execute_cases_missing_worker_result(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    script = tmp_path / "input.cmd"
    script.write_text("@echo off\n", encoding="utf-8")
    first = Case(
        case_id="a",
        description="alpha",
        source_path=tmp_path / "expect.yaml",
        script_path=script,
        expect=Expect(exit_code=0),
    )
    second = first.model_copy(update={"case_id": "b", "description": "beta"})

    def fake_execute(case: Case, _config: EngineConfig) -> RunResult:
        return RunResult(
            case_id=case.case_id,
            description=case.description,
            outcome=Outcome.PASS,
        )

    monkeypatch.setattr("battest.engine.execute_case", fake_execute)
    monkeypatch.setattr("battest.engine.as_completed", lambda _futures: [])
    results = execute_cases([first, second], EngineConfig(jobs=2))
    assert [item.outcome for item in results] == [Outcome.ERROR, Outcome.ERROR]
    assert results[0].error_message == "worker produced no result"
    assert results[1].error_message == "worker produced no result"


def test_execute_case_setup_timeout_and_env_dump(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("battest.engine.require_windows", lambda: None)
    monkeypatch.setattr("battest.engine.console_encoding", lambda: "utf-8")
    script = tmp_path / "run.cmd"
    script.write_text("@echo off\n", encoding="utf-8")
    setup = tmp_path / "setup.cmd"
    setup.write_text("@echo off\n", encoding="utf-8")
    teardown = tmp_path / "teardown.cmd"
    teardown.write_text("@echo off\n", encoding="utf-8")
    case = Case(
        case_id="t",
        description="t",
        source_path=tmp_path / "t.yaml",
        script_path=script,
        setup_path=setup,
        teardown_path=teardown,
        mocks={"net": MockSpec(exit_code=0)},
        expect=Expect(exit_code=0),
        stdin="in",
    )
    calls = {"n": 0}

    def fail_setup(
        _command: list[str],
        cwd: Path,
        _env: dict[str, str],
        _stdin: str,
        _timeout: float,
        _encoding: str,
    ) -> tuple[int, str, str, bool]:
        calls["n"] += 1
        if calls["n"] == 1:
            return 9, "", "setup-err", False
        return 0, "", "", False

    monkeypatch.setattr("battest.engine._run_process", fail_setup)
    failed = execute_case(case, EngineConfig())
    assert failed.outcome == Outcome.ERROR
    assert failed.error_message is not None
    assert "setup failed" in failed.error_message
    assert calls["n"] == 2

    def succeed_with_dump(
        _command: list[str],
        cwd: Path,
        _env: dict[str, str],
        _stdin: str,
        _timeout: float,
        _encoding: str,
    ) -> tuple[int, str, str, bool]:
        calls["n"] += 1
        if calls["n"] == 1:
            return 0, "", "", False
        (cwd / "_battest_env.txt").write_text(
            "FOO=bar\nBATTEST_X=1\nBATTEST_RC=0\n", encoding="utf-8"
        )
        return 0, "ok", "", True

    calls["n"] = 0
    monkeypatch.setattr("battest.engine._run_process", succeed_with_dump)
    timed = execute_case(case, EngineConfig())
    assert timed.outcome == Outcome.TIMEOUT
    assert timed.env["FOO"] == "bar"
    assert timed.env["BATTEST_X"] == "1"
    assert "BATTEST_RC" not in timed.env


def test_setup_sut_teardown_share_one_deadline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("battest.engine.require_windows", lambda: None)
    monkeypatch.setattr("battest.engine.console_encoding", lambda: "utf-8")
    script = tmp_path / "run.cmd"
    script.write_text("@echo off\n", encoding="utf-8")
    setup = tmp_path / "setup.cmd"
    setup.write_text("@echo off\n", encoding="utf-8")
    teardown = tmp_path / "teardown.cmd"
    teardown.write_text("@echo off\n", encoding="utf-8")
    case = Case(
        case_id="t",
        description="t",
        source_path=tmp_path / "t.yaml",
        script_path=script,
        setup_path=setup,
        teardown_path=teardown,
        expect=Expect(exit_code=0),
    )
    seen: list[float] = []

    def fake_run(
        _command: list[str],
        _cwd: Path,
        _env: dict[str, str],
        _stdin: str,
        timeout: float,
        _encoding: str,
    ) -> tuple[int, str, str, bool]:
        seen.append(timeout)
        time.sleep(0.15)
        return 0, "", "", False

    monkeypatch.setattr("battest.engine._run_process", fake_run)
    result = execute_case(case, EngineConfig(default_timeout_seconds=5.0))
    assert result.outcome == Outcome.PASS
    assert len(seen) == 3
    assert seen[0] <= 5.0
    assert seen[1] < seen[0]
    assert seen[2] >= TEARDOWN_MIN_SECONDS


def test_teardown_timeout_never_below_minimum() -> None:
    assert teardown_timeout(time.perf_counter() - 10.0) == TEARDOWN_MIN_SECONDS
    future = time.perf_counter() + 30.0
    assert teardown_timeout(future) >= TEARDOWN_MIN_SECONDS


def test_abandon_lingering_process_skips_exited() -> None:
    class Dead:
        def poll(self) -> int | None:
            return 0

        def kill(self) -> None:
            raise AssertionError("should not kill exited process")

        def wait(self, timeout: float | None = None) -> int:
            return 0

        def communicate(
            self, input: bytes | None = None, timeout: float | None = None
        ) -> tuple[bytes, bytes]:
            return b"", b""

    abandon_lingering_process(Dead())


def test_abandon_lingering_process_bounded_wait(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class Zombie:
        killed = False

        def poll(self) -> int | None:
            return None

        def kill(self) -> None:
            self.killed = True

        def wait(self, timeout: float | None = None) -> int:
            raise subprocess.TimeoutExpired(cmd="x", timeout=timeout or 0)

        def communicate(
            self, input: bytes | None = None, timeout: float | None = None
        ) -> tuple[bytes, bytes]:
            return b"", b""

    zombie = Zombie()
    with caplog.at_level("ERROR", logger="battest.process"):
        abandon_lingering_process(zombie)
    assert zombie.killed is True
    assert "abandoning still-alive" in caplog.text


def test_deadline_starts_after_prepare(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("battest.engine.require_windows", lambda: None)
    monkeypatch.setattr("battest.engine.console_encoding", lambda: "utf-8")
    script = tmp_path / "run.cmd"
    script.write_text("@echo off\n", encoding="utf-8")
    case = Case(
        case_id="t",
        description="t",
        source_path=tmp_path / "t.yaml",
        script_path=script,
        expect=Expect(exit_code=0),
    )
    original_prepare = _prepare_work_dir

    def slow_prepare(
        prepared_case: Case,
        config: EngineConfig,
        work_dir: Path,
        **_kwargs: object,
    ) -> object:
        time.sleep(0.25)
        return original_prepare(prepared_case, config, work_dir, **_kwargs)

    seen: list[float] = []

    def fake_run(
        _command: list[str],
        _cwd: Path,
        _env: dict[str, str],
        _stdin: str,
        timeout: float,
        _encoding: str,
    ) -> tuple[int, str, str, bool]:
        seen.append(timeout)
        return 0, "", "", False

    monkeypatch.setattr("battest.engine._prepare_work_dir", slow_prepare)
    monkeypatch.setattr("battest.engine._run_process", fake_run)
    result = execute_case(case, EngineConfig(default_timeout_seconds=5.0))
    assert result.outcome == Outcome.PASS
    assert seen
    assert seen[0] > 4.7


@pytest.mark.windows
def test_engine_hides_battest_helper_env_from_sut(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BATTEST_SUT", "leaked-from-host")
    case = _write_case(
        tmp_path,
        "@echo off\r\necho SUT=%BATTEST_SUT%\r\nexit /b 0\r\n",
        "\n".join(
            [
                "description: hide helper env",
                "script: run.cmd",
                "expect:",
                "  exit_code: 0",
                "  stdout:",
                '    contains: "SUT="',
            ]
        ),
    )
    result = execute_case(case, EngineConfig())
    assert result.outcome == Outcome.PASS
    assert "run.cmd" not in result.stdout


@pytest.mark.windows
def test_engine_sut_cannot_redirect_env_dump(tmp_path: Path) -> None:
    outside = tmp_path / "pwned-env.txt"
    case = _write_case(
        tmp_path,
        "\r\n".join(
            [
                "@echo off",
                f'set "_bt_env={outside}"',
                "set MARKER=ok",
                "exit /b 0",
                "",
            ]
        ),
        "\n".join(
            [
                "description: env dump must stay in workdir",
                "script: run.cmd",
                "expect:",
                "  exit_code: 0",
                "  env:",
                "    MARKER: ok",
            ]
        ),
    )
    result = execute_case(case, EngineConfig())
    assert result.outcome == Outcome.PASS
    assert not outside.exists()
    assert result.env.get("MARKER") == "ok"


def test_build_wrapper_text_uses_dp0() -> None:
    text = build_wrapper_text("sub\\run.cmd")
    assert "%~dp0sub\\run.cmd" in text
    assert "%~dp0_battest_env.txt" in text
    assert f"%~dp0{CWD_DUMP_NAME}" in text
    assert "BATTEST_RC" in text
    assert "_bt_env" not in text


def test_wrapper_sut_relative_rejects_unsafe_names(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    sut = work / "run.cmd"
    sut.write_text("@echo off\n", encoding="utf-8")
    assert wrapper_sut_relative(work, sut) == "run.cmd"
    nested = work / "sub"
    nested.mkdir()
    nested_sut = nested / "run.cmd"
    nested_sut.write_text("@echo off\n", encoding="utf-8")
    relative = wrapper_sut_relative(work, nested_sut)
    assert "sub" in relative
    assert "run.cmd" in relative
    with pytest.raises(ValueError, match="escapes"):
        wrapper_sut_relative(work, tmp_path / "outside.cmd")
    with pytest.raises(ValueError, match="not safe"):
        wrapper_sut_relative(work, work / 'a"b.cmd')
    percent = work / "a%b.cmd"
    percent.write_text("@echo off\n", encoding="utf-8")
    with pytest.raises(ValueError, match="not safe"):
        wrapper_sut_relative(work, percent)
    non_ascii = work / "café.cmd"
    non_ascii.write_text("@echo off\n", encoding="utf-8")
    with pytest.raises(ValueError, match="not safe"):
        wrapper_sut_relative(work, non_ascii)


def test_close_process_streams_oserror(caplog: pytest.LogCaptureFixture) -> None:
    class BoomStream:
        def close(self) -> None:
            raise OSError("already closed")

    class Proc:
        stdin = BoomStream()
        stdout = BoomStream()
        stderr = None

    with caplog.at_level("DEBUG", logger="battest.process"):
        close_process_streams(Proc())
    assert "failed to close process stream" in caplog.text


def test_is_path_outside_directory(tmp_path: Path) -> None:
    inside = tmp_path / "work"
    inside.mkdir()
    assert is_path_outside_directory(str(inside), inside) is False
    assert is_path_outside_directory(str(inside / "child"), inside) is False
    assert is_path_outside_directory(str(tmp_path / "other"), inside) is True
    assert is_path_outside_directory("", inside) is False
    child = inside / "child"
    child.mkdir()
    assert is_path_outside_directory("child", inside) is False
    assert is_path_outside_directory("..", inside) is True


def test_snapshot_env_warns_when_dump_missing(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level("WARNING", logger="battest.engine"):
        assert _snapshot_env(tmp_path, "utf-8") == {}
    assert "env dump missing" in caplog.text


def test_snapshot_env_errors_when_required_dump_missing(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="env dump missing"):
        _snapshot_env(tmp_path, "utf-8", require_file=True)


def test_snapshot_env_errors_when_dump_is_directory(tmp_path: Path) -> None:
    (tmp_path / ENV_DUMP_NAME).mkdir()
    with pytest.raises(ValueError, match="not a regular file"):
        _snapshot_env(tmp_path, "utf-8")


def test_snapshot_env_errors_when_dump_exceeds_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dump = tmp_path / ENV_DUMP_NAME
    dump.write_text("A=1\n", encoding="utf-8")

    def tiny_read(
        _path: Path, max_bytes: int = MAX_CAPTURE_BYTES
    ) -> tuple[bytes | None, str | None]:
        return None, f"exceeded {max_bytes} byte limit"

    monkeypatch.setattr("battest.engine.read_capped_bytes", tiny_read)
    with pytest.raises(ValueError, match="unreadable"):
        _snapshot_env(tmp_path, "utf-8")


def test_cwd_outside_workdir_appends_warning(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("battest.engine.require_windows", lambda: None)
    monkeypatch.setattr("battest.engine.console_encoding", lambda: "utf-8")
    script = tmp_path / "run.cmd"
    script.write_text("@echo off\n", encoding="utf-8")
    case = Case(
        case_id="t",
        description="t",
        source_path=tmp_path / "t.yaml",
        script_path=script,
        expect=Expect(exit_code=0),
    )

    def fake_run(
        _command: list[str],
        cwd: Path,
        _env: dict[str, str],
        _stdin: str,
        _timeout: float,
        _encoding: str,
    ) -> tuple[int, str, str, bool]:
        outside = tmp_path / "outside-of-workdir"
        (cwd / CWD_DUMP_NAME).write_text(f"{outside}\n", encoding="utf-8")
        return 0, "", "", False

    monkeypatch.setattr("battest.engine._run_process", fake_run)
    result = execute_case(case, EngineConfig())
    assert result.outcome == Outcome.PASS
    assert any("changed directory" in item for item in result.warnings)


def test_overflowed_output_is_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("battest.engine.require_windows", lambda: None)
    monkeypatch.setattr("battest.engine.console_encoding", lambda: "utf-8")
    script = tmp_path / "run.cmd"
    script.write_text("@echo off\n", encoding="utf-8")
    case = Case(
        case_id="t",
        description="t",
        source_path=tmp_path / "t.yaml",
        script_path=script,
        expect=Expect(exit_code=0),
    )

    def fake_run(
        _command: list[str],
        _cwd: Path,
        _env: dict[str, str],
        _stdin: str,
        _timeout: float,
        _encoding: str,
    ) -> ProcessResult:
        return ProcessResult(
            0,
            "x" * 20,
            "",
            False,
            overflowed=True,
            pid=42,
        )

    monkeypatch.setattr("battest.engine._run_process", fake_run)
    result = execute_case(case, EngineConfig())
    assert result.outcome == Outcome.ERROR
    assert result.error_message is not None
    assert (
        "capture" in result.error_message.lower()
        or "byte limit" in result.error_message
    )


def test_abandoned_process_is_not_pass(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("battest.engine.require_windows", lambda: None)
    monkeypatch.setattr("battest.engine.console_encoding", lambda: "utf-8")
    script = tmp_path / "run.cmd"
    script.write_text("@echo off\n", encoding="utf-8")
    case = Case(
        case_id="t",
        description="t",
        source_path=tmp_path / "t.yaml",
        script_path=script,
        expect=Expect(exit_code=0),
    )

    def fake_run(
        _command: list[str],
        _cwd: Path,
        _env: dict[str, str],
        _stdin: str,
        _timeout: float,
        _encoding: str,
    ) -> ProcessResult:
        return ProcessResult(0, "ok", "", False, abandoned=True, pid=99)

    monkeypatch.setattr("battest.engine._run_process", fake_run)
    result = execute_case(case, EngineConfig())
    assert result.outcome == Outcome.ERROR
    assert any("abandoned" in item for item in result.warnings)


def test_run_process_caps_stream_bytes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class QuietStdin:
        def write(self, data: bytes) -> int:
            return len(data)

        def flush(self) -> None:
            return None

        def close(self) -> None:
            return None

    class OnceReader:
        def __init__(self, payload: bytes) -> None:
            self._payload = payload
            self._sent = False

        def read(self, _size: int = -1) -> bytes:
            if self._sent:
                return b""
            self._sent = True
            return self._payload

        def close(self) -> None:
            return None

    class FloodProcess:
        pid = 11
        returncode = 0

        def __init__(self, *args: object, **kwargs: object) -> None:
            self.stdin = QuietStdin()
            self.stdout = OnceReader(b"x" * 50)
            self.stderr = OnceReader(b"")

        def communicate(
            self, input: bytes | None = None, timeout: float | None = None
        ) -> tuple[bytes, bytes]:
            return b"", b""

        def poll(self) -> int | None:
            return 0

        def wait(self, timeout: float | None = None) -> int:
            return 0

        def kill(self) -> None:
            return None

        def __enter__(self) -> FloodProcess:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    def fake_taskkill(
        *_args: object, **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(["taskkill"], 0, "", "")

    monkeypatch.setattr("battest.process.subprocess.Popen", FloodProcess)
    monkeypatch.setattr("battest.process.subprocess.run", fake_taskkill)
    monkeypatch.setattr("battest.process._create_kill_on_close_job", lambda: None)
    from battest.process import run_process as run_proc

    result = run_proc(["cmd"], tmp_path, {}, "", 1.0, "utf-8", max_bytes=10)
    assert result.overflowed is True
    assert len(result.stdout.encode("utf-8")) <= 10


@pytest.mark.windows
def test_timeout_does_not_abandon_when_job_kills_tree(tmp_path: Path) -> None:
    script = tmp_path / "run.cmd"
    script.write_text(
        "@echo off\r\nping -n 30 127.0.0.1 >nul\r\nexit /b 0\r\n", encoding="utf-8"
    )
    manifest = tmp_path / "run.battest.yaml"
    manifest.write_text(
        "description: long ping\nscript: run.cmd\ntimeout_seconds: 1\nexpect:\n  exit_code: 0\n",
        encoding="utf-8",
    )
    from battest.schema import load_cases_from_path

    case = load_cases_from_path(manifest)[0]
    result = execute_case(case, EngineConfig())
    assert result.outcome == Outcome.TIMEOUT
    assert not any("abandoned still-alive" in item for item in result.warnings)
    assert MAX_CAPTURE_BYTES >= 1


def test_coerce_process_result_rejects_unexpected_shapes() -> None:
    good = ProcessResult(0, "a", "b", False)
    assert coerce_process_result(good) is good
    coerced = coerce_process_result((2, "out", "err", True))
    assert coerced.exit_code == 2
    assert coerced.timed_out is True
    with pytest.raises(TypeError, match="unexpected process result"):
        coerce_process_result("nope")
    with pytest.raises(TypeError, match="unexpected process result"):
        coerce_process_result((1, "a", "b"))
    with pytest.raises(TypeError, match="unexpected process result"):
        coerce_process_result((1, "a", "b", "no"))


def test_abandon_lingering_process_false_when_already_exited() -> None:
    class Dead:
        def poll(self) -> int | None:
            return 0

        def kill(self) -> None:
            raise AssertionError("kill must not run")

        def wait(self, timeout: float | None = None) -> int:
            raise AssertionError("wait must not run")

    assert abandon_lingering_process(Dead()) is False


def test_abandon_lingering_process_true_when_wait_times_out() -> None:
    class Stuck:
        def poll(self) -> int | None:
            return None

        def kill(self) -> None:
            return None

        def wait(self, timeout: float | None = None) -> int:
            raise subprocess.TimeoutExpired(cmd="x", timeout=timeout or 0)

    assert abandon_lingering_process(Stuck()) is True


def test_abandon_lingering_process_true_when_poll_stays_none() -> None:
    class Zombie:
        def poll(self) -> int | None:
            return None

        def kill(self) -> None:
            return None

        def wait(self, timeout: float | None = None) -> int:
            return 0

    assert abandon_lingering_process(Zombie()) is True


def test_close_process_streams_skips_none_and_oserror() -> None:
    class Boom:
        def close(self) -> None:
            raise OSError("busy")

    class FakePopen:
        stdin = None
        stdout = Boom()
        stderr = None

    close_process_streams(FakePopen())


def test_write_stdin_handles_none_payload_and_oserror(
    caplog: pytest.LogCaptureFixture,
) -> None:
    _write_stdin(None, b"x")

    class BoomStream:
        def write(self, _data: bytes) -> int:
            raise OSError("pipe")

        def flush(self) -> None:
            return None

        def close(self) -> None:
            raise OSError("close")

    with caplog.at_level("WARNING", logger="battest.process"):
        _write_stdin(BoomStream(), b"payload")
    assert "failed to write stdin" in caplog.text


def test_read_capped_stream_overflow_and_oserror() -> None:
    class Chunked:
        def __init__(self) -> None:
            self._reads = 0

        def read(self, _size: int = -1) -> bytes:
            self._reads += 1
            if self._reads == 1:
                return b"abcdef"
            if self._reads == 2:
                return b"more"
            if self._reads == 3:
                raise OSError("broken")
            return b""

    chunks: list[bytes] = []
    overflow = [False]
    _read_capped_stream(Chunked(), 3, chunks, overflow)
    assert overflow[0] is True
    assert b"".join(chunks) == b"abc"

    class ExactThenMore:
        def __init__(self) -> None:
            self._reads = 0

        def read(self, _size: int = -1) -> bytes:
            self._reads += 1
            if self._reads == 1:
                return b"abc"
            if self._reads == 2:
                return b"z"
            return b""

    exact_chunks: list[bytes] = []
    exact_overflow = [False]
    _read_capped_stream(ExactThenMore(), 3, exact_chunks, exact_overflow)
    assert exact_overflow[0] is True
    assert b"".join(exact_chunks) == b"abc"


def test_job_helpers_when_windll_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("battest.process.ctypes_windll", lambda: None)
    assert _create_kill_on_close_job() is None
    with pytest.raises(OSError, match="Win32 APIs unavailable"):
        _assign_and_resume(object(), 1)
    _close_job(1)


def test_job_create_and_assign_failure_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Kernel:
        def CreateJobObjectW(self, *_args: object) -> int:
            return 0

        def SetInformationJobObject(self, *_args: object) -> int:
            return 0

        def CloseHandle(self, *_args: object) -> int:
            return 0

        def AssignProcessToJobObject(self, *_args: object) -> int:
            return 0

    class Windll:
        kernel32 = Kernel()

    monkeypatch.setattr("battest.process.ctypes_windll", lambda: Windll())
    assert _create_kill_on_close_job() is None

    class SetFailKernel(Kernel):
        def CreateJobObjectW(self, *_args: object) -> int:
            return 9

    class SetFailWindll:
        kernel32 = SetFailKernel()

    monkeypatch.setattr("battest.process.ctypes_windll", lambda: SetFailWindll())
    assert _create_kill_on_close_job() is None

    class CloseFailWindll:
        kernel32 = Kernel()

    monkeypatch.setattr("battest.process.ctypes_windll", lambda: CloseFailWindll())
    _close_job(5)

    class Process:
        pid = 4
        _handle = 11

    monkeypatch.setattr("battest.process.ctypes_windll", lambda: Windll())
    monkeypatch.setattr("battest.process._nt_resume_process", lambda _handle: 0)
    with pytest.raises(OSError, match="AssignProcessToJobObject failed"):
        _assign_and_resume(Process(), 7)

    class AssignOkKernel(Kernel):
        def AssignProcessToJobObject(self, *_args: object) -> int:
            return 1

    class AssignOkWindll:
        kernel32 = AssignOkKernel()

    monkeypatch.setattr("battest.process.ctypes_windll", lambda: AssignOkWindll())
    monkeypatch.setattr("battest.process._nt_resume_process", lambda _handle: 1)
    with pytest.raises(OSError, match="NtResumeProcess failed"):
        _assign_and_resume(Process(), 7)

    monkeypatch.setattr("battest.process._nt_resume_process", lambda _handle: 0)
    _assign_and_resume(Process(), 7)

    class NoHandle:
        pid = 8

    with pytest.raises(OSError, match="no _handle"):
        _assign_and_resume(NoHandle(), 7)

    class ZeroHandle:
        pid = 9
        _handle = 0

    with pytest.raises(OSError, match="null"):
        _assign_and_resume(ZeroHandle(), 7)

    assert _handle_as_int(None) == 0
    assert _handle_as_int(False) == 0
    assert _handle_as_int(object()) == 0


def test_join_readers_logs_when_thread_stays_alive(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class Stuck:
        name = "battest-stdout"

        def join(self, timeout: float | None = None) -> None:
            return None

        def is_alive(self) -> bool:
            return True

    with caplog.at_level("ERROR", logger="battest.process"):
        _join_readers([Stuck()])  # type: ignore[list-item]
    assert "did not exit after kill" in caplog.text


def test_run_process_kills_before_joining_readers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class QuietStdin:
        def write(self, data: bytes) -> int:
            return len(data)

        def flush(self) -> None:
            return None

        def close(self) -> None:
            return None

    class BlockUntilKilled:
        def __init__(self, owner: object) -> None:
            self._owner = owner

        def read(self, _size: int = -1) -> bytes:
            while getattr(self._owner, "returncode") is None:
                time.sleep(0.01)
            return b""

        def close(self) -> None:
            return None

    class StickyProcess:
        pid = 42
        returncode: int | None = None

        def __init__(self, *args: object, **kwargs: object) -> None:
            self.stdin = QuietStdin()
            self.stdout = BlockUntilKilled(self)
            self.stderr = BlockUntilKilled(self)

        def communicate(
            self, input: bytes | None = None, timeout: float | None = None
        ) -> tuple[bytes, bytes]:
            raise AssertionError("communicate must not run after custom readers")

        def poll(self) -> int | None:
            return self.returncode

        def wait(self, timeout: float | None = None) -> int:
            if self.returncode is None:
                raise subprocess.TimeoutExpired(cmd="x", timeout=timeout or 0)
            return self.returncode

        def kill(self) -> None:
            self.returncode = -9

    holder: list[StickyProcess] = []

    def fake_popen(*_args: object, **_kwargs: object) -> StickyProcess:
        process = StickyProcess()
        holder.append(process)
        return process

    def fake_kill(_pid: int) -> None:
        holder[0].returncode = -9

    monkeypatch.setattr("battest.process.subprocess.Popen", fake_popen)
    monkeypatch.setattr("battest.process.kill_process_tree", fake_kill)
    monkeypatch.setattr("battest.process._create_kill_on_close_job", lambda: None)
    from battest.process import run_process as run_proc

    started = time.perf_counter()
    result = run_proc(["cmd"], tmp_path, {}, "", 0.05, "utf-8")
    assert result.timed_out is True
    assert time.perf_counter() - started < 2.0
    assert holder[0].returncode == -9


def test_run_process_keeps_truncated_extra_drain(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class QuietStdin:
        def write(self, data: bytes) -> int:
            return len(data)

        def flush(self) -> None:
            return None

        def close(self) -> None:
            return None

    class OnceReader:
        def __init__(self, payload: bytes) -> None:
            self._payload = payload
            self._sent = False

        def read(self, _size: int = -1) -> bytes:
            if self._sent:
                return b""
            self._sent = True
            return self._payload

        def close(self) -> None:
            return None

    class AliveThenDead:
        pid = 21
        returncode: int | None = None

        def __init__(self, *args: object, **kwargs: object) -> None:
            self.stdin = QuietStdin()
            self.stdout = OnceReader(b"x" * 50)
            self.stderr = OnceReader(b"y" * 50)
            self._polls = 0

        def communicate(
            self, input: bytes | None = None, timeout: float | None = None
        ) -> tuple[bytes, bytes]:
            raise AssertionError("communicate must not run after custom readers")

        def poll(self) -> int | None:
            self._polls += 1
            if self._polls < 8:
                return None
            self.returncode = 1
            return 1

        def wait(self, timeout: float | None = None) -> int:
            self.returncode = 1
            return 1

        def kill(self) -> None:
            return None

        def __enter__(self) -> AliveThenDead:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    monkeypatch.setattr("battest.process.subprocess.Popen", AliveThenDead)
    monkeypatch.setattr(
        "battest.process.subprocess.run",
        lambda *_a, **_k: subprocess.CompletedProcess(["taskkill"], 0, "", ""),
    )
    monkeypatch.setattr("battest.process._create_kill_on_close_job", lambda: None)
    from battest.process import run_process as run_proc

    result = run_proc(["cmd"], tmp_path, {}, "", 2.0, "utf-8", max_bytes=4)
    assert result.overflowed is True
    assert len(result.stdout.encode("utf-8")) <= 4
    assert len(result.stderr.encode("utf-8")) <= 4


def test_run_process_closes_job_when_popen_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    closed: list[int | None] = []
    monkeypatch.setattr("battest.process._create_kill_on_close_job", lambda: 99)
    monkeypatch.setattr(
        "battest.process._close_job", lambda handle: closed.append(handle)
    )

    def boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("spawn failed")

    monkeypatch.setattr("battest.process.subprocess.Popen", boom)
    from battest.process import run_process as run_proc

    with pytest.raises(OSError, match="spawn failed"):
        run_proc(["cmd"], tmp_path, {}, "", 1.0, "utf-8")
    assert closed == [99]


def test_missing_env_dump_with_expect_env_is_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("battest.engine.require_windows", lambda: None)
    monkeypatch.setattr("battest.engine.console_encoding", lambda: "utf-8")
    script = tmp_path / "run.cmd"
    script.write_text("@echo off\n", encoding="utf-8")
    case = Case(
        case_id="t",
        description="t",
        source_path=tmp_path / "t.yaml",
        script_path=script,
        expect=Expect(exit_code=0, env=EnvExpect(unset=["SECRET"])),
    )

    def fake_run(
        _command: list[str],
        _cwd: Path,
        _env: dict[str, str],
        _stdin: str,
        _timeout: float,
        _encoding: str,
    ) -> tuple[int, str, str, bool]:
        return 0, "", "", False

    monkeypatch.setattr("battest.engine._run_process", fake_run)
    result = execute_case(case, EngineConfig())
    assert result.outcome == Outcome.ERROR
    assert result.error_message is not None
    assert "env dump missing" in result.error_message


def test_duration_includes_teardown(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("battest.engine.require_windows", lambda: None)
    monkeypatch.setattr("battest.engine.console_encoding", lambda: "utf-8")
    teardown = tmp_path / "teardown.cmd"
    teardown.write_text("@echo off\n", encoding="utf-8")
    script = tmp_path / "run.cmd"
    script.write_text("@echo off\n", encoding="utf-8")
    case = Case(
        case_id="t",
        description="t",
        source_path=tmp_path / "t.yaml",
        script_path=script,
        teardown_path=teardown,
        expect=Expect(exit_code=0),
    )

    def fake_run(
        command: list[str],
        cwd: Path,
        _env: dict[str, str],
        _stdin: str,
        _timeout: float,
        _encoding: str,
    ) -> tuple[int, str, str, bool]:
        dump = cwd / ENV_DUMP_NAME
        if not dump.is_file():
            dump.write_text("A=1\n", encoding="utf-8")
        if any("teardown.cmd" in str(part) for part in command):
            time.sleep(0.25)
        return 0, "", "", False

    monkeypatch.setattr("battest.engine._run_process", fake_run)
    result = execute_case(case, EngineConfig())
    assert result.outcome == Outcome.PASS
    assert result.duration_seconds >= 0.2


def test_abandoned_process_skips_rmtree(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("battest.engine.require_windows", lambda: None)
    monkeypatch.setattr("battest.engine.console_encoding", lambda: "utf-8")
    script = tmp_path / "run.cmd"
    script.write_text("@echo off\n", encoding="utf-8")
    case = Case(
        case_id="t",
        description="t",
        source_path=tmp_path / "t.yaml",
        script_path=script,
        expect=Expect(exit_code=0),
    )

    def fake_run(
        _command: list[str],
        _cwd: Path,
        _env: dict[str, str],
        _stdin: str,
        _timeout: float,
        _encoding: str,
    ) -> ProcessResult:
        return ProcessResult(1, "", "", False, abandoned=True, pid=4242)

    removed: list[Path] = []
    monkeypatch.setattr("battest.engine._run_process", fake_run)
    monkeypatch.setattr(
        "battest.engine.shutil.rmtree", lambda path: removed.append(path)
    )
    result = execute_case(case, EngineConfig())
    assert result.outcome == Outcome.ERROR
    assert any("abandoned still-alive" in item for item in result.warnings)
    assert removed == []


def test_prepare_rejects_blocking_env_dump_directory(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    (work / ENV_DUMP_NAME).mkdir()
    with pytest.raises(ValueError, match="not a regular file"):
        _reject_blocking_env_dump(work)
