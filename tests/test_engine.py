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
    _run_process,
    _script_warnings,
    _seed_work_dir,
    build_cmd_line,
    cmd_executable,
    collapse_path_keys,
    drain_after_timeout,
    execute_case,
    execute_cases,
    kill_process_tree,
    require_windows,
    resolved_timeout,
)
from battest.models import (
    Case,
    EngineConfig,
    Expect,
    MockSpec,
    Outcome,
    OutputMatcher,
    RunResult,
)
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


def test_console_encoding_non_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    assert console_encoding() == "utf-8"


def test_console_encoding_code_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")

    class FakeKernel:
        def __init__(self, code_page: int) -> None:
            self._code_page = code_page

        def GetConsoleOutputCP(self) -> int:
            return self._code_page

    class FakeCtypes:
        def __init__(self, code_page: int) -> None:
            self.windll = type("W", (), {"kernel32": FakeKernel(code_page)})()

    monkeypatch.setattr("battest.encoding.ctypes", FakeCtypes(437))
    assert console_encoding() == "cp437"
    monkeypatch.setattr("battest.encoding.ctypes", FakeCtypes(65001))
    assert console_encoding() == "utf-8"
    monkeypatch.setattr("battest.encoding.ctypes", FakeCtypes(0))
    assert console_encoding() == "utf-8"


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


def test_seed_work_dir_copies_directory(tmp_path: Path) -> None:
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    (fixtures / "a.txt").write_text("nested", encoding="utf-8")
    work = tmp_path / "work"
    work.mkdir()
    _seed_work_dir(work, [fixtures], tmp_path)
    assert (work / "fixtures" / "a.txt").read_text(encoding="utf-8") == "nested"


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
    timeouts: list[object] = []

    def fake_run(
        command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        seen.append(command)
        timeouts.append(kwargs.get("timeout"))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    kill_process_tree(1234)
    assert seen[0][:3] == ["taskkill", "/F", "/T"]
    assert timeouts[0] is not None


def test_kill_process_tree_timeout_is_logged(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def fake_run(*_args: object, **_kwargs: object) -> None:
        raise subprocess.TimeoutExpired(cmd="taskkill", timeout=1)

    monkeypatch.setattr(subprocess, "run", fake_run)
    with caplog.at_level("ERROR", logger="battest.engine"):
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


def test_drain_after_timeout_kills_when_communicate_hangs() -> None:
    class FakeProcess:
        def __init__(self) -> None:
            self.killed = False
            self.calls = 0

        def communicate(
            self, input: bytes | None = None, timeout: float | None = None
        ) -> tuple[bytes, bytes]:
            self.calls += 1
            if self.calls == 1:
                raise subprocess.TimeoutExpired(cmd="x", timeout=timeout or 0)
            return b"out", b"err"

        def kill(self) -> None:
            self.killed = True

    fake = FakeProcess()
    stdout, stderr = drain_after_timeout(fake, 0.1)
    assert fake.killed is True
    assert stdout == b"out"
    assert stderr == b"err"


def test_drain_after_timeout_returns_empty_if_kill_hangs() -> None:
    class HangProcess:
        def communicate(
            self, input: bytes | None = None, timeout: float | None = None
        ) -> tuple[bytes, bytes]:
            raise subprocess.TimeoutExpired(cmd="x", timeout=timeout or 0)

        def kill(self) -> None:
            return None

    stdout, stderr = drain_after_timeout(HangProcess(), 0.01)
    assert stdout == b""
    assert stderr == b""


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
    class OkProcess:
        pid = 7
        returncode = 3

        def __init__(self, *args: object, **kwargs: object) -> None:
            return None

        def __enter__(self) -> OkProcess:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def communicate(
            self, input: bytes | None = None, timeout: float | None = None
        ) -> tuple[bytes, bytes]:
            assert input == b"hi"
            return b"out", b"err"

    monkeypatch.setattr("battest.engine.subprocess.Popen", OkProcess)
    exit_code, stdout, stderr, timed_out = _run_process(
        ["cmd"], tmp_path, {}, "hi", 1.0, "utf-8"
    )
    assert exit_code == 3
    assert stdout == "out"
    assert stderr == "err"
    assert timed_out is False

    class TimeoutProcess:
        pid = None
        returncode = None

        def __init__(self, *args: object, **kwargs: object) -> None:
            return None

        def __enter__(self) -> TimeoutProcess:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def communicate(
            self, input: bytes | None = None, timeout: float | None = None
        ) -> tuple[bytes, bytes]:
            raise subprocess.TimeoutExpired(cmd="x", timeout=timeout or 0)

    killed: list[int] = []
    monkeypatch.setattr("battest.engine.subprocess.Popen", TimeoutProcess)
    monkeypatch.setattr("battest.engine.kill_process_tree", killed.append)
    monkeypatch.setattr(
        "battest.engine.drain_after_timeout", lambda _proc, _timeout: (b"", b"")
    )
    exit_code, stdout, stderr, timed_out = _run_process(
        ["cmd"], tmp_path, {}, "", 0.1, "utf-8"
    )
    assert timed_out is True
    assert exit_code == -1
    assert killed == []


def test_run_process_warns_when_stdin_cannot_encode(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    class OkProcess:
        pid = 1
        returncode = 0

        def __init__(self, *args: object, **kwargs: object) -> None:
            return None

        def __enter__(self) -> OkProcess:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def communicate(
            self, input: bytes | None = None, timeout: float | None = None
        ) -> tuple[bytes, bytes]:
            assert input is not None
            assert b"?" in input
            return b"", b""

    monkeypatch.setattr("battest.engine.subprocess.Popen", OkProcess)
    with caplog.at_level("WARNING", logger="battest.engine"):
        _run_process(["cmd"], tmp_path, {}, "café", 1.0, "ascii")
    assert "cannot be encoded" in caplog.text


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
            "FOO=bar\nBATTEST_X=1\n", encoding="utf-8"
        )
        return 0, "ok", "", True

    calls["n"] = 0
    monkeypatch.setattr("battest.engine._run_process", succeed_with_dump)
    timed = execute_case(case, EngineConfig())
    assert timed.outcome == Outcome.TIMEOUT
    assert timed.env["FOO"] == "bar"
    assert "BATTEST_X" not in timed.env
