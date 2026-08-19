"""Execute batch scripts under real cmd.exe with isolation."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import multiprocessing
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time

from battest.assertlib import evaluate_case, read_capped_bytes
from battest.constants import (
    BATTEST_PREFIX,
    CWD_DUMP_NAME,
    ENV_DUMP_NAME,
    MAX_CAPTURE_BYTES,
    TEARDOWN_MIN_SECONDS,
    WRAPPER_NAME,
)
from battest.encoding import console_encoding
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
from battest.process import (
    ProcessResult,
    build_cmd_line,
    coerce_process_result,
    is_path_outside_directory,
    run_process,
)

LOGGER = get_logger("engine")


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
        f'> "%~dp0{CWD_DUMP_NAME}" echo %CD%\n'
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


def require_windows() -> None:
    """Raise EngineError when cmd.exe execution is unavailable."""
    if sys.platform != "win32":
        raise EngineError("battest run requires Windows cmd.exe")


def _run_process(
    command: list[str],
    cwd: Path,
    env: dict[str, str],
    stdin_text: str,
    timeout_seconds: float,
    encoding: str,
) -> ProcessResult:
    return run_process(command, cwd, env, stdin_text, timeout_seconds, encoding)


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
    helper_from_fixture = any(
        key.upper().startswith(BATTEST_PREFIX) for key in case.env
    )
    LOGGER.debug(
        "combined env work_dir=%s fixture_battest_keys=%s",
        work_dir,
        helper_from_fixture,
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


def _snapshot_env(
    work_dir: Path,
    encoding: str,
    *,
    require_file: bool = False,
) -> dict[str, str]:
    env_dump = work_dir / ENV_DUMP_NAME
    if env_dump.exists() and not env_dump.is_file():
        LOGGER.error("env dump is not a regular file at %s", env_dump)
        raise ValueError(f"env dump is not a regular file: {env_dump}")
    if not env_dump.is_file():
        if require_file:
            LOGGER.error("env dump missing at %s", env_dump)
            raise ValueError(f"env dump missing: {env_dump}")
        LOGGER.warning(
            "env dump missing at %s; treating captured env as empty", env_dump
        )
        return {}
    data, error = read_capped_bytes(env_dump)
    if error is not None:
        LOGGER.error("cannot read env dump %s: %s", env_dump, error)
        raise ValueError(f"env dump unreadable: {env_dump} ({error})")
    if data is None:
        raise ValueError(f"env dump unreadable: {env_dump}")
    return filter_helper_vars(parse_set_output(data.decode(encoding, errors="replace")))


def _reject_blocking_env_dump(work_dir: Path) -> None:
    """Refuse to start when the wrapper env dump path is blocked by a non-file."""
    env_dump = work_dir / ENV_DUMP_NAME
    if env_dump.exists() and not env_dump.is_file():
        LOGGER.error("env dump path is not a regular file: %s", env_dump)
        raise ValueError(f"env dump path is not a regular file: {env_dump}")


def _cwd_warning(work_dir: Path, encoding: str) -> str | None:
    dump = work_dir / CWD_DUMP_NAME
    if not dump.is_file():
        return None
    try:
        text = dump.read_text(encoding=encoding, errors="replace").strip()
    except OSError as exc:
        LOGGER.error("cannot read cwd dump %s: %s", dump, exc)
        return None
    if not text:
        return None
    if not is_path_outside_directory(text, work_dir):
        return None
    message = (
        f"script changed directory to {text!r}, which is outside the isolated "
        "working directory; relative filesystem operations are no longer confined"
    )
    LOGGER.warning("%s", message)
    return message


def _relocated_path(work_dir: Path, source: Path, base_dir: Path) -> Path:
    relative = source.resolve().relative_to(base_dir.resolve())
    return work_dir / relative


def _invoke_process(
    command: list[str],
    cwd: Path,
    env: dict[str, str],
    stdin_text: str,
    timeout: float,
    encoding: str,
) -> ProcessResult:
    return coerce_process_result(
        _run_process(command, cwd, env, stdin_text, timeout, encoding)
    )


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
        result = _invoke_process(
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
    if result.timed_out or result.exit_code != 0 or result.overflowed:
        message = (
            f"setup failed exit={result.exit_code} timeout={result.timed_out} "
            f"stderr={result.stderr.strip()}"
        )
        if result.overflowed:
            message = f"setup output exceeded capture limit; {message}"
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
        result = _invoke_process(
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
    if result.timed_out or result.exit_code != 0 or result.overflowed:
        message = (
            f"teardown failed exit={result.exit_code} timeout={result.timed_out} "
            f"stderr={result.stderr.strip()}"
        )
        if result.overflowed:
            message = f"teardown output exceeded capture limit; {message}"
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


def _with_duration(result: RunResult, started: float) -> RunResult:
    """Stamp wall-clock duration after teardown has finished."""
    return RunResult(
        case_id=result.case_id,
        description=result.description,
        outcome=result.outcome,
        exit_code=result.exit_code,
        stdout=result.stdout,
        stderr=result.stderr,
        env=result.env,
        mock_calls=result.mock_calls,
        failures=result.failures,
        duration_seconds=time.perf_counter() - started,
        error_message=result.error_message,
        warnings=result.warnings,
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
    captured_env: dict[str, str] = {}
    require_file = case.expect.env is not None and not timed_out
    try:
        captured_env = _snapshot_env(work_dir, encoding, require_file=require_file)
    except ValueError as exc:
        LOGGER.error("cannot snapshot env for %s: %s", case.case_id, exc)
        return RunResult(
            case_id=case.case_id,
            description=case.description,
            outcome=Outcome.ERROR,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            duration_seconds=duration,
            error_message=str(exc),
            warnings=warnings,
        )
    cwd_warning = _cwd_warning(work_dir, encoding)
    if cwd_warning is not None:
        warnings = list(warnings) + [cwd_warning]
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


def _prepare_work_dir(
    case: Case,
    config: EngineConfig,
    work_dir: Path,
    *,
    encoding: str = "utf-8",
) -> PreparedWork:
    base_dir = case.source_path.parent
    to_copy = list(case.copy_paths)
    to_copy.append(case.script_path)
    if case.setup_path is not None:
        to_copy.append(case.setup_path)
    if case.teardown_path is not None:
        to_copy.append(case.teardown_path)
    _seed_work_dir(work_dir, to_copy, base_dir)
    _reject_blocking_env_dump(work_dir)
    mocks = effective_mocks(case.mocks, case.allow, config.safe_defaults)
    mock_dir = write_mock_tree(work_dir, mocks, encoding=encoding) if mocks else None
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


_FILE_ATTRIBUTE_REPARSE_POINT = 0x400


def _is_reparse_point(path: Path) -> bool:
    """True for symlinks and Windows junctions without following the target."""
    if path.is_symlink():
        return True
    try:
        stats = path.lstat()
    except OSError:
        return False
    try:
        attrs = stats.st_file_attributes
    except AttributeError:
        return False
    return bool(attrs & _FILE_ATTRIBUTE_REPARSE_POINT)


def _path_escapes(path: Path, base: Path) -> bool:
    try:
        path.resolve().relative_to(base)
    except (OSError, ValueError):
        return True
    return False


def _copy_seed_entry(source: Path, destination: Path, resolved_base: Path) -> None:
    """Copy one fixture path without following escaping junctions or symlinks."""
    if _is_reparse_point(source):
        if _path_escapes(source, resolved_base):
            LOGGER.error(
                "seed path %s is a symlink or junction that escapes %s",
                source,
                resolved_base,
            )
            raise ValueError(
                f"copy path {source} is a symlink or junction that escapes "
                f"the fixture directory {resolved_base}"
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, destination, dirs_exist_ok=True, symlinks=True)
            return
        shutil.copy2(source, destination, follow_symlinks=False)
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        destination.mkdir(parents=True, exist_ok=True)
        for child in source.iterdir():
            _copy_seed_entry(child, destination / child.name, resolved_base)
        return
    shutil.copy2(source, destination)


def _seed_work_dir(work_dir: Path, copy_paths: list[Path], base_dir: Path) -> None:
    resolved_base = base_dir.resolve()
    for source in copy_paths:
        try:
            # Do not follow junctions/symlinks when computing the destination
            # name; escaping links are rejected in _copy_seed_entry.
            relative = source.absolute().relative_to(resolved_base)
        except ValueError as exc:
            LOGGER.error(
                "seed path %s is not under fixture directory %s",
                source,
                resolved_base,
            )
            raise ValueError(
                f"copy path {source} is a symlink or junction that escapes "
                f"the fixture directory {resolved_base}"
            ) from exc
        destination = work_dir / relative
        LOGGER.debug("seeding %s -> %s", source, destination)
        _copy_seed_entry(source, destination, resolved_base)


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
        result = _invoke_process(
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
    extra_warnings = list(warnings)
    if result.abandoned:
        message = (
            f"abandoned still-alive process pid={result.pid} " f"workdir={work_dir}"
        )
        LOGGER.error("%s", message)
        extra_warnings.append(message)
    if result.overflowed:
        message = (
            f"captured output exceeded the {MAX_CAPTURE_BYTES} byte limit; "
            "output was truncated"
        )
        LOGGER.error("%s", message)
        duration = time.perf_counter() - started
        return RunResult(
            case_id=case.case_id,
            description=case.description,
            outcome=Outcome.ERROR,
            exit_code=result.exit_code,
            stdout=result.stdout,
            stderr=result.stderr,
            duration_seconds=duration,
            error_message=message,
            warnings=extra_warnings,
        )
    if result.abandoned and not result.timed_out:
        duration = time.perf_counter() - started
        return RunResult(
            case_id=case.case_id,
            description=case.description,
            outcome=Outcome.ERROR,
            exit_code=result.exit_code,
            stdout=result.stdout,
            stderr=result.stderr,
            duration_seconds=duration,
            error_message=extra_warnings[-1],
            warnings=extra_warnings,
        )
    duration = time.perf_counter() - started
    return _evaluate_after_run(
        case,
        config,
        work_dir,
        prepared.mock_dir,
        encoding,
        timeout,
        extra_warnings,
        duration,
        result.exit_code,
        result.stdout,
        result.stderr,
        result.timed_out,
    )


def execute_case(case: Case, config: EngineConfig) -> RunResult:
    """Run one case under cmd.exe, then evaluate assertions, then teardown."""
    multiprocessing.freeze_support()
    require_windows()
    started = time.perf_counter()
    warnings = _script_warnings(case)
    encoding = console_encoding()
    timeout = resolved_timeout(case, config)
    LOGGER.info(
        "execute_case id=%s script=%s timeout=%s encoding=%s safe_defaults=%s",
        case.case_id,
        case.script_path,
        timeout,
        encoding,
        config.safe_defaults,
    )
    work_dir = Path(tempfile.mkdtemp(prefix="battest-"))
    result: RunResult | None = None
    try:
        try:
            prepared = _prepare_work_dir(case, config, work_dir, encoding=encoding)
        except (OSError, ValueError, MockError) as exc:
            LOGGER.error("case %s failed before execution: %s", case.case_id, exc)
            result = _error_result(case, started, warnings, str(exc))
            return result
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
        result = _apply_teardown_result(result, teardown_error)
        return _with_duration(result, started)
    finally:
        abandoned = result is not None and any(
            "abandoned still-alive" in item for item in result.warnings
        )
        if abandoned:
            LOGGER.error(
                "leaving work dir %s because a process was abandoned", work_dir
            )
        else:
            try:
                shutil.rmtree(work_dir)
            except OSError as exc:
                LOGGER.error("failed to remove work dir %s: %s", work_dir, exc)


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
