"""Execute batch scripts under real cmd.exe with isolation."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

from battest.assertlib import evaluate_case
from battest.constants import ENV_DUMP_NAME, WRAPPER_NAME
from battest.encoding import console_encoding, decode_output
from battest.envsnap import filter_helper_vars, parse_set_output
from battest.logging_config import get_logger
from battest.mocks import (
    effective_mocks,
    read_call_logs,
    warn_internal_absolute_paths,
    write_mock_tree,
)
from battest.models import Case, EngineConfig, Outcome, RunResult

LOGGER = get_logger("engine")
CREATE_NEW_PROCESS_GROUP = 0x00000200

_WRAPPER_TEMPLATE = """@echo off
call "%BATTEST_SUT%" %*
set BATTEST_RC=%ERRORLEVEL%
set > "%BATTEST_ENVFILE%"
exit /b %BATTEST_RC%
"""


class EngineError(RuntimeError):
    """Raised when the host cannot execute batch tests."""


def require_windows() -> None:
    """Raise EngineError when cmd.exe execution is unavailable."""
    if sys.platform != "win32":
        raise EngineError("battest run requires Windows cmd.exe")


def cmd_executable() -> str:
    """Return the absolute path to cmd.exe when possible."""
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    candidate = Path(system_root) / "System32" / "cmd.exe"
    if candidate.is_file():
        return str(candidate)
    return "cmd.exe"


def build_cmd_line(wrapper: Path, args: list[str]) -> list[str]:
    """Build a cmd.exe /d /s /c invocation that preserves arguments."""
    inner = subprocess.list2cmdline(["call", str(wrapper), *args])
    return [cmd_executable(), "/d", "/s", "/c", inner]


def kill_process_tree(pid: int) -> None:
    """Kill a process and its descendants on Windows."""
    LOGGER.warning("killing process tree pid=%s", pid)
    subprocess.run(
        ["taskkill", "/F", "/T", "/PID", str(pid)],
        check=False,
        capture_output=True,
        text=True,
    )


def _seed_work_dir(work_dir: Path, copy_paths: list[Path]) -> None:
    for source in copy_paths:
        destination = work_dir / source.name
        LOGGER.info("seeding %s -> %s", source, destination)
        if source.is_dir():
            shutil.copytree(source, destination)
        else:
            shutil.copy2(source, destination)


def _run_process(
    command: list[str],
    cwd: Path,
    env: dict[str, str],
    stdin_text: str,
    timeout_seconds: float,
    encoding: str,
) -> tuple[int, str, str, bool]:
    LOGGER.info("exec command=%s cwd=%s timeout=%s", command, cwd, timeout_seconds)
    stdin_bytes = stdin_text.encode(encoding, errors="replace") if stdin_text else None
    creationflags = CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    timed_out = False
    stdout_bytes = b""
    stderr_bytes = b""
    exit_code = -1
    with subprocess.Popen(
        command,
        cwd=str(cwd),
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=creationflags,
    ) as process:
        try:
            stdout_bytes, stderr_bytes = process.communicate(
                input=stdin_bytes,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            timed_out = True
            LOGGER.error("process timed out pid=%s", process.pid)
            if process.pid is not None:
                kill_process_tree(process.pid)
            stdout_bytes, stderr_bytes = process.communicate()
        exit_code = process.returncode if process.returncode is not None else -1
    stdout = decode_output(stdout_bytes or b"", encoding)
    stderr = decode_output(stderr_bytes or b"", encoding)
    LOGGER.info(
        "exec finished exit=%s timeout=%s stdout_len=%s stderr_len=%s",
        exit_code,
        timed_out,
        len(stdout),
        len(stderr),
    )
    return exit_code, stdout, stderr, timed_out


def collapse_path_keys(env: dict[str, str]) -> str:
    """Keep a single PATH entry. Later duplicate keys win (case overlay)."""
    value = ""
    kept_key = "Path"
    for key in list(env):
        if key.upper() == "PATH":
            kept_key = key
            value = env.pop(key)
    env[kept_key] = value
    return kept_key


def _combined_env(case: Case, work_dir: Path, mock_dir: Path | None) -> dict[str, str]:
    env = {str(key): str(value) for key, value in os.environ.items()}
    env.update(case.env)
    env["BATTEST_SUT"] = str(case.script_path)
    env["BATTEST_ENVFILE"] = str(work_dir / ENV_DUMP_NAME)
    env["NoDefaultCurrentDirectoryInEXEPath"] = "1"
    path_key = collapse_path_keys(env)
    if mock_dir is not None:
        env[path_key] = str(mock_dir) + os.pathsep + env.get(path_key, "")
        LOGGER.info("PATH prefixed with mock dir %s key=%s", mock_dir, path_key)
    return env


def _script_warnings(case: Case) -> list[str]:
    warnings = list(case.warnings)
    try:
        text = case.script_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        LOGGER.error("cannot read script for warnings %s: %s", case.script_path, exc)
        return warnings
    warnings.extend(warn_internal_absolute_paths(text))
    return warnings


def execute_case(case: Case, config: EngineConfig) -> RunResult:
    """Run one case under cmd.exe, then evaluate assertions."""
    require_windows()
    started = time.perf_counter()
    warnings = _script_warnings(case)
    encoding = console_encoding()
    timeout = case.timeout_seconds or config.default_timeout_seconds
    LOGGER.info(
        "execute_case id=%s script=%s timeout=%s safe_defaults=%s",
        case.case_id,
        case.script_path,
        timeout,
        config.safe_defaults,
    )
    with tempfile.TemporaryDirectory(prefix="battest-") as raw_temp:
        work_dir = Path(raw_temp)
        _seed_work_dir(work_dir, case.copy_paths)
        mocks = effective_mocks(case.mocks, case.allow, config.safe_defaults)
        mock_dir = write_mock_tree(work_dir, mocks) if mocks else None
        wrapper = work_dir / WRAPPER_NAME
        wrapper.write_text(_WRAPPER_TEMPLATE, encoding="utf-8")
        env = _combined_env(case, work_dir, mock_dir)
        if case.setup_path is not None:
            setup_cmd = build_cmd_line(case.setup_path, [])
            setup_exit, _, setup_err, setup_timeout = _run_process(
                setup_cmd, work_dir, env, "", timeout, encoding
            )
            if setup_timeout or setup_exit != 0:
                duration = time.perf_counter() - started
                message = (
                    f"setup failed exit={setup_exit} timeout={setup_timeout} "
                    f"stderr={setup_err.strip()}"
                )
                LOGGER.error("%s", message)
                return RunResult(
                    case_id=case.case_id,
                    description=case.description,
                    outcome=Outcome.ERROR,
                    error_message=message,
                    duration_seconds=duration,
                    warnings=warnings,
                )
        command = build_cmd_line(wrapper, case.args)
        try:
            exit_code, stdout, stderr, timed_out = _run_process(
                command, work_dir, env, case.stdin, timeout, encoding
            )
        finally:
            if case.teardown_path is not None:
                try:
                    _run_process(
                        build_cmd_line(case.teardown_path, []),
                        work_dir,
                        env,
                        "",
                        timeout,
                        encoding,
                    )
                except OSError as exc:
                    LOGGER.error("teardown failed for %s: %s", case.case_id, exc)
        env_dump = work_dir / ENV_DUMP_NAME
        captured_env: dict[str, str] = {}
        if env_dump.is_file():
            captured_env = filter_helper_vars(
                parse_set_output(
                    env_dump.read_text(encoding=encoding, errors="replace")
                )
            )
        mock_calls = read_call_logs(mock_dir) if mock_dir is not None else {}
        duration = time.perf_counter() - started
        if timed_out:
            return RunResult(
                case_id=case.case_id,
                description=case.description,
                outcome=Outcome.TIMEOUT,
                exit_code=exit_code,
                stdout=stdout,
                stderr=stderr,
                env=captured_env,
                mock_calls=mock_calls,
                duration_seconds=duration,
                error_message=f"timed out after {timeout}s",
                warnings=warnings,
            )
        failures = evaluate_case(
            case,
            exit_code,
            stdout,
            stderr,
            captured_env,
            work_dir,
            mock_calls,
            config.max_diff,
        )
        outcome = Outcome.FAIL if failures else Outcome.PASS
        return RunResult(
            case_id=case.case_id,
            description=case.description,
            outcome=outcome,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            env=captured_env,
            mock_calls=mock_calls,
            failures=failures,
            duration_seconds=duration,
            warnings=warnings,
        )


def execute_cases(cases: list[Case], config: EngineConfig) -> list[RunResult]:
    """Execute cases sequentially or with a thread pool."""
    LOGGER.info("execute_cases count=%s jobs=%s", len(cases), config.jobs)
    if config.jobs <= 1 or len(cases) <= 1:
        return [execute_case(case, config) for case in cases]
    results_by_id: dict[str, RunResult] = {}
    with ThreadPoolExecutor(max_workers=config.jobs) as pool:
        future_map = {
            pool.submit(execute_case, case, config): case.case_id for case in cases
        }
        for future in as_completed(future_map):
            case_id = future_map[future]
            try:
                results_by_id[case_id] = future.result()
            except Exception as exc:
                LOGGER.error("case %s raised %s", case_id, exc)
                results_by_id[case_id] = RunResult(
                    case_id=case_id,
                    description=case_id,
                    outcome=Outcome.ERROR,
                    error_message=str(exc),
                )
    return [results_by_id[case.case_id] for case in cases]
