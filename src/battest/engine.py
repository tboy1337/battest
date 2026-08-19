"""Execute batch scripts under real cmd.exe with isolation."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Protocol

from battest.assertlib import evaluate_case
from battest.constants import (
    BATTEST_PREFIX,
    ENV_DUMP_NAME,
    KILL_DRAIN_TIMEOUT_SECONDS,
    TEARDOWN_MIN_SECONDS,
    WRAPPER_NAME,
)
from battest.encoding import console_encoding, decode_output
from battest.envsnap import filter_helper_vars, parse_set_output
from battest.logging_config import get_logger
from battest.mocks import (
    MockError,
    effective_mocks,
    read_call_logs,
    warn_internal_absolute_paths,
    write_mock_tree,
)
from battest.models import Case, EngineConfig, Outcome, RunResult

LOGGER = get_logger("engine")
CREATE_NEW_PROCESS_GROUP = 0x00000200


@dataclass(frozen=True)
class PreparedWork:
    """Isolated workdir paths and environment for one case."""

    wrapper: Path
    mock_dir: Path | None
    env: dict[str, str]
    setup_path: Path | None
    teardown_path: Path | None


_WRAPPER_UNSAFE_CHARS = frozenset('"%\r\n')


def build_wrapper_text(sut_relative: str) -> str:
    """Return wrapper cmd text that calls sut_relative beside the wrapper."""
    LOGGER.debug("building wrapper for relative sut %s", sut_relative)
    return (
        "@echo off\n"
        f'call "%~dp0{sut_relative}" %*\n'
        'set "BATTEST_RC=%ERRORLEVEL%"\n'
        f'set > "%~dp0{ENV_DUMP_NAME}"\n'
        "exit /b %BATTEST_RC%\n"
    )


def wrapper_sut_relative(work_dir: Path, sut_path: Path) -> str:
    """Return a cmd-safe path from the wrapper directory to the copied script."""
    try:
        relative = sut_path.resolve().relative_to(work_dir.resolve())
    except ValueError as exc:
        raise ValueError(f"script path escapes work directory: {sut_path}") from exc
    text = str(relative).replace("/", "\\")
    if not text.isascii() or any(char in text for char in _WRAPPER_UNSAFE_CHARS):
        LOGGER.warning("wrapper-relative script path is not cmd-safe: %s", sut_path)
        raise ValueError(f"script path is not safe for cmd.exe wrapper: {sut_path}")
    LOGGER.debug("wrapper relative sut=%s", text)
    return text


class EngineError(RuntimeError):
    """Raised when the host cannot execute batch tests."""


class TerminableProcess(Protocol):
    """Process that can be drained and killed after a timeout.

    ``communicate`` matches :meth:`subprocess.Popen.communicate` so a real
    ``Popen`` is a structural subtype.
    """

    def communicate(  # pylint: disable=redefined-builtin
        self, input: bytes | None = None, timeout: float | None = None
    ) -> tuple[bytes, bytes]:
        """Read remaining stdout and stderr."""

    def kill(self) -> None:
        """Forcibly terminate the process."""

    def poll(self) -> int | None:
        """Return the exit code when the process has exited, else None."""

    def wait(self, timeout: float | None = None) -> int:
        """Wait for the process to exit, optionally bounded by timeout."""


def require_windows() -> None:
    """Raise EngineError when cmd.exe execution is unavailable."""
    if sys.platform != "win32":
        raise EngineError("battest run requires Windows cmd.exe")


def system32_executable(name: str) -> str:
    """Return System32\\name when that file exists, otherwise the bare name."""
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    candidate = Path(system_root) / "System32" / name
    if candidate.is_file():
        LOGGER.debug("resolved system32 executable %s", candidate)
        return str(candidate)
    LOGGER.debug("system32 executable %s missing; using bare name %s", candidate, name)
    return name


def cmd_executable() -> str:
    """Return the absolute path to cmd.exe when possible."""
    return system32_executable("cmd.exe")


def build_cmd_line(wrapper: Path, args: list[str]) -> list[str]:
    """Build a cmd.exe /d /s /c invocation that preserves arguments."""
    inner = subprocess.list2cmdline(["call", str(wrapper), *args])
    return [cmd_executable(), "/d", "/s", "/c", inner]


def kill_process_tree(pid: int) -> None:
    """Kill a process and its descendants on Windows."""
    LOGGER.warning("killing process tree pid=%s", pid)
    taskkill = system32_executable("taskkill.exe")
    try:
        completed = subprocess.run(
            [taskkill, "/F", "/T", "/PID", str(pid)],
            check=False,
            capture_output=True,
            text=True,
            timeout=KILL_DRAIN_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        LOGGER.error("taskkill timed out for pid=%s", pid)
        return
    if completed.returncode != 0:
        LOGGER.warning(
            "taskkill pid=%s returned %s stderr=%s",
            pid,
            completed.returncode,
            completed.stderr,
        )


def drain_after_timeout(
    process: TerminableProcess, timeout_seconds: float
) -> tuple[bytes, bytes]:
    """Collect remaining output after a kill, bounded by timeout_seconds."""
    try:
        return process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        LOGGER.error("process did not exit after timeout; sending kill")
        process.kill()
        try:
            return process.communicate(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            LOGGER.error("process still alive after kill")
            return b"", b""


def abandon_lingering_process(process: TerminableProcess) -> None:
    """Kill and wait with a bound; never block forever if the child survives."""
    if process.poll() is not None:
        return
    LOGGER.error("process still running after drain; killing and abandoning")
    process.kill()
    try:
        process.wait(timeout=KILL_DRAIN_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        LOGGER.error("abandoning still-alive process after wait timeout")


def _close_process_streams(process: subprocess.Popen[bytes]) -> None:
    # subprocess type stubs expose stdio as IO[Any]; closing is still required.
    for stream in (process.stdin, process.stdout, process.stderr):  # type: ignore[misc]
        if stream is None:  # type: ignore[misc]
            continue
        try:
            stream.close()  # type: ignore[misc]
        except OSError:
            LOGGER.debug("failed to close process stream", exc_info=True)


def _seed_work_dir(work_dir: Path, copy_paths: list[Path], base_dir: Path) -> None:
    resolved_base = base_dir.resolve()
    for source in copy_paths:
        relative = source.resolve().relative_to(resolved_base)
        destination = work_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        LOGGER.debug("seeding %s -> %s", source, destination)
        if source.is_dir():
            shutil.copytree(source, destination, dirs_exist_ok=True)
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
    LOGGER.debug("exec command=%s cwd=%s timeout=%s", command, cwd, timeout_seconds)
    if timeout_seconds <= 0:
        LOGGER.error(
            "timeout already expired before spawn command=%s timeout=%s",
            command,
            timeout_seconds,
        )
        return -1, "", "", True
    stdin_bytes = _encode_stdin(stdin_text, encoding)
    creationflags = CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    timed_out = False
    stdout_bytes = b""
    stderr_bytes = b""
    exit_code = -1
    # Popen.__exit__ waits forever; after timeout we must bound that wait ourselves.
    process = subprocess.Popen(  # pylint: disable=consider-using-with
        command,
        cwd=str(cwd),
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=creationflags,
    )
    try:
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
            stdout_bytes, stderr_bytes = drain_after_timeout(
                process, KILL_DRAIN_TIMEOUT_SECONDS
            )
            abandon_lingering_process(process)
        exit_code = process.returncode if process.returncode is not None else -1
    finally:
        _close_process_streams(process)
        if process.poll() is None:
            abandon_lingering_process(process)
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


def _strip_inherited_helper_vars(env: dict[str, str]) -> None:
    """Drop host BATTEST_* keys so runner/CI helper names cannot leak into the SUT."""
    for key in [name for name in env if name.upper().startswith(BATTEST_PREFIX)]:
        LOGGER.debug("dropping inherited helper env %s", key)
        env.pop(key)


def _overlay_case_env(env: dict[str, str], case_env: dict[str, str]) -> None:
    """Apply fixture env. PATH replaces inherited PATH regardless of key case."""
    overlay: tuple[str, str] | None = None
    for key, value in case_env.items():
        if key.upper() == "PATH":
            overlay = (str(key), str(value))
            continue
        env[str(key)] = str(value)
    if overlay is None:
        LOGGER.debug("fixture env has no PATH overlay")
        return
    overlay_key, overlay_path = overlay
    inherited_key = collapse_path_keys(env)
    env.pop(inherited_key, None)
    env[overlay_key] = overlay_path
    LOGGER.debug(
        "fixture PATH overlay key=%s replaced inherited key=%s",
        overlay_key,
        inherited_key,
    )


def _combined_env(
    case: Case,
    work_dir: Path,
    mock_dir: Path | None,
) -> dict[str, str]:
    env = {str(key): str(value) for key, value in os.environ.items()}
    _strip_inherited_helper_vars(env)
    collapse_path_keys(env)
    _overlay_case_env(env, case.env)
    env["NoDefaultCurrentDirectoryInEXEPath"] = "1"
    path_key = collapse_path_keys(env)
    if mock_dir is not None:
        env[path_key] = str(mock_dir) + os.pathsep + env.get(path_key, "")
        LOGGER.debug("PATH prefixed with mock dir %s key=%s", mock_dir, path_key)
    LOGGER.debug(
        "combined env work_dir=%s helper_battest_keys_injected=false", work_dir
    )
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


def resolved_timeout(case: Case, config: EngineConfig) -> float:
    """Return the case timeout, or the engine default when the case omitted one."""
    if case.timeout_seconds is not None:
        return case.timeout_seconds
    return config.default_timeout_seconds


def remaining_timeout(deadline: float) -> float:
    """Seconds left until deadline, never negative."""
    return max(0.0, deadline - time.perf_counter())


def teardown_timeout(deadline: float) -> float:
    """Seconds for teardown: remaining budget, never below TEARDOWN_MIN_SECONDS."""
    return max(remaining_timeout(deadline), TEARDOWN_MIN_SECONDS)


def _encode_stdin(stdin_text: str, encoding: str) -> bytes | None:
    if not stdin_text:
        return None
    try:
        return stdin_text.encode(encoding)
    except UnicodeEncodeError:
        LOGGER.error(
            "stdin contains characters that cannot be encoded as %s",
            encoding,
        )
        raise


def _snapshot_env(work_dir: Path, encoding: str) -> dict[str, str]:
    env_dump = work_dir / ENV_DUMP_NAME
    if not env_dump.is_file():
        return {}
    return filter_helper_vars(
        parse_set_output(env_dump.read_text(encoding=encoding, errors="replace"))
    )


def _relocated_path(work_dir: Path, source: Path, base_dir: Path) -> Path:
    relative = source.resolve().relative_to(base_dir.resolve())
    return work_dir / relative


def _run_setup(
    case: Case,
    work_dir: Path,
    env: dict[str, str],
    timeout: float,
    encoding: str,
    setup_path: Path | None,
) -> str | None:
    if setup_path is None:
        return None
    try:
        setup_exit, _, setup_err, setup_timeout = _run_process(
            build_cmd_line(setup_path, []),
            work_dir,
            env,
            "",
            timeout,
            encoding,
        )
    except OSError as exc:
        LOGGER.error("setup failed for %s: %s", case.case_id, exc)
        return f"setup failed: {exc}"
    if setup_timeout or setup_exit != 0:
        message = (
            f"setup failed exit={setup_exit} timeout={setup_timeout} "
            f"stderr={setup_err.strip()}"
        )
        LOGGER.error("%s", message)
        return message
    return None


def _run_teardown(
    case: Case,
    work_dir: Path,
    env: dict[str, str],
    timeout: float,
    encoding: str,
    teardown_path: Path | None,
) -> str | None:
    if teardown_path is None:
        return None
    try:
        exit_code, _, stderr, timed_out = _run_process(
            build_cmd_line(teardown_path, []),
            work_dir,
            env,
            "",
            timeout,
            encoding,
        )
    except OSError as exc:
        LOGGER.error("teardown failed for %s: %s", case.case_id, exc)
        return f"teardown failed: {exc}"
    if timed_out or exit_code != 0:
        message = (
            f"teardown failed exit={exit_code} timeout={timed_out} "
            f"stderr={stderr.strip()}"
        )
        LOGGER.error("%s", message)
        return message
    return None


def _apply_teardown_result(result: RunResult, teardown_error: str | None) -> RunResult:
    if teardown_error is None:
        return result
    warnings = list(result.warnings) + [teardown_error]
    outcome = Outcome.ERROR if result.outcome == Outcome.PASS else result.outcome
    error_message = (
        teardown_error if result.outcome == Outcome.PASS else result.error_message
    )
    return RunResult(
        case_id=result.case_id,
        description=result.description,
        outcome=outcome,
        exit_code=result.exit_code,
        stdout=result.stdout,
        stderr=result.stderr,
        env=result.env,
        mock_calls=result.mock_calls,
        failures=result.failures,
        duration_seconds=result.duration_seconds,
        error_message=error_message,
        warnings=warnings,
    )


def _evaluate_after_run(
    case: Case,
    config: EngineConfig,
    work_dir: Path,
    mock_dir: Path | None,
    encoding: str,
    timeout: float,
    warnings: list[str],
    duration: float,
    exit_code: int,
    stdout: str,
    stderr: str,
    timed_out: bool,
) -> RunResult:
    captured_env = _snapshot_env(work_dir, encoding)
    try:
        mock_calls = read_call_logs(mock_dir) if mock_dir is not None else {}
    except MockError as exc:
        LOGGER.error("cannot read call logs for %s: %s", case.case_id, exc)
        return RunResult(
            case_id=case.case_id,
            description=case.description,
            outcome=Outcome.ERROR,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            env=captured_env,
            duration_seconds=duration,
            error_message=str(exc),
            warnings=warnings,
        )
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


def _error_result(
    case: Case, started: float, warnings: list[str], message: str
) -> RunResult:
    return RunResult(
        case_id=case.case_id,
        description=case.description,
        outcome=Outcome.ERROR,
        error_message=message,
        duration_seconds=time.perf_counter() - started,
        warnings=warnings,
    )


def _prepare_work_dir(case: Case, config: EngineConfig, work_dir: Path) -> PreparedWork:
    base_dir = case.source_path.parent
    to_copy = list(case.copy_paths)
    to_copy.append(case.script_path)
    if case.setup_path is not None:
        to_copy.append(case.setup_path)
    if case.teardown_path is not None:
        to_copy.append(case.teardown_path)
    _seed_work_dir(work_dir, to_copy, base_dir)
    mocks = effective_mocks(case.mocks, case.allow, config.safe_defaults)
    mock_dir = write_mock_tree(work_dir, mocks) if mocks else None
    sut_path = _relocated_path(work_dir, case.script_path, base_dir)
    wrapper = work_dir / WRAPPER_NAME
    wrapper.write_text(
        build_wrapper_text(wrapper_sut_relative(work_dir, sut_path)),
        encoding="utf-8",
    )
    env = _combined_env(case, work_dir, mock_dir)
    setup_path = (
        _relocated_path(work_dir, case.setup_path, base_dir)
        if case.setup_path is not None
        else None
    )
    teardown_path = (
        _relocated_path(work_dir, case.teardown_path, base_dir)
        if case.teardown_path is not None
        else None
    )
    return PreparedWork(
        wrapper=wrapper,
        mock_dir=mock_dir,
        env=env,
        setup_path=setup_path,
        teardown_path=teardown_path,
    )


def _run_sut(
    case: Case,
    config: EngineConfig,
    work_dir: Path,
    prepared: PreparedWork,
    encoding: str,
    timeout: float,
    deadline: float,
    warnings: list[str],
    started: float,
) -> RunResult:
    setup_error = _run_setup(
        case,
        work_dir,
        prepared.env,
        remaining_timeout(deadline),
        encoding,
        prepared.setup_path,
    )
    if setup_error is not None:
        return _error_result(case, started, warnings, setup_error)
    try:
        command = build_cmd_line(prepared.wrapper, case.args)
        exit_code, stdout, stderr, timed_out = _run_process(
            command,
            work_dir,
            prepared.env,
            case.stdin,
            remaining_timeout(deadline),
            encoding,
        )
    except UnicodeEncodeError as exc:
        message = f"stdin cannot be encoded as {encoding}: {exc}"
        LOGGER.error("sut failed for %s: %s", case.case_id, message)
        return _error_result(case, started, warnings, message)
    except OSError as exc:
        LOGGER.error("sut failed for %s: %s", case.case_id, exc)
        return _error_result(case, started, warnings, str(exc))
    duration = time.perf_counter() - started
    return _evaluate_after_run(
        case,
        config,
        work_dir,
        prepared.mock_dir,
        encoding,
        timeout,
        warnings,
        duration,
        exit_code,
        stdout,
        stderr,
        timed_out,
    )


def execute_case(case: Case, config: EngineConfig) -> RunResult:
    """Run one case under cmd.exe, then evaluate assertions, then teardown."""
    require_windows()
    started = time.perf_counter()
    warnings = _script_warnings(case)
    encoding = console_encoding()
    timeout = resolved_timeout(case, config)
    LOGGER.info(
        "execute_case id=%s script=%s timeout=%s safe_defaults=%s",
        case.case_id,
        case.script_path,
        timeout,
        config.safe_defaults,
    )
    with tempfile.TemporaryDirectory(
        prefix="battest-", ignore_cleanup_errors=True
    ) as raw_temp:
        work_dir = Path(raw_temp)
        try:
            prepared = _prepare_work_dir(case, config, work_dir)
        except (OSError, ValueError, MockError) as exc:
            LOGGER.error("case %s failed before execution: %s", case.case_id, exc)
            return _error_result(case, started, warnings, str(exc))
        deadline = time.perf_counter() + timeout
        result = _run_sut(
            case,
            config,
            work_dir,
            prepared,
            encoding,
            timeout,
            deadline,
            warnings,
            started,
        )
        teardown_error = _run_teardown(
            case,
            work_dir,
            prepared.env,
            teardown_timeout(deadline),
            encoding,
            prepared.teardown_path,
        )
        return _apply_teardown_result(result, teardown_error)


def execute_cases(cases: list[Case], config: EngineConfig) -> list[RunResult]:
    """Execute cases sequentially or with a thread pool."""
    LOGGER.info("execute_cases count=%s jobs=%s", len(cases), config.jobs)
    if config.jobs <= 1 or len(cases) <= 1:
        return [execute_case(case, config) for case in cases]
    slotted: list[RunResult | None] = [None] * len(cases)
    with ThreadPoolExecutor(max_workers=config.jobs) as pool:
        future_map = {
            pool.submit(execute_case, case, config): index
            for index, case in enumerate(cases)
        }
        for future in as_completed(future_map):
            index = future_map[future]
            case = cases[index]
            try:
                slotted[index] = future.result()
            except Exception as exc:
                LOGGER.error("case %s raised %s", case.case_id, exc, exc_info=True)
                slotted[index] = RunResult(
                    case_id=case.case_id,
                    description=case.description,
                    outcome=Outcome.ERROR,
                    error_message=str(exc),
                )
    results: list[RunResult] = []
    for index, result in enumerate(slotted):
        if result is not None:
            results.append(result)
            continue
        case = cases[index]
        LOGGER.error("case %s produced no result", case.case_id)
        results.append(
            RunResult(
                case_id=case.case_id,
                description=case.description,
                outcome=Outcome.ERROR,
                error_message="worker produced no result",
            )
        )
    return results
