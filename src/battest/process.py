"""Spawn, cap, and tear down cmd.exe processes for one battest case."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from typing import BinaryIO, Protocol

from battest.constants import KILL_DRAIN_TIMEOUT_SECONDS, MAX_CAPTURE_BYTES
from battest.encoding import decode_output
from battest.logging_config import get_logger

LOGGER = get_logger("process")
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_SUSPENDED = 0x00000004
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_STREAM_CHUNK_SIZE = 65_536
_NTSTATUS_SUCCESS = 0


@dataclass(frozen=True)
class ProcessResult:
    """Bounded result of one cmd.exe invocation."""

    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool
    overflowed: bool = False
    abandoned: bool = False
    pid: int | None = None


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


class JobObjectBasicLimitInformation(ctypes.Structure):
    """JOBOBJECT_BASIC_LIMIT_INFORMATION for SetInformationJobObject."""

    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", ctypes.c_uint32),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", ctypes.c_uint32),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", ctypes.c_uint32),
        ("SchedulingClass", ctypes.c_uint32),
    ]


class IoCounters(ctypes.Structure):
    """IO_COUNTERS nested inside JOBOBJECT_EXTENDED_LIMIT_INFORMATION."""

    _fields_ = [
        ("ReadOperationCount", ctypes.c_uint64),
        ("WriteOperationCount", ctypes.c_uint64),
        ("OtherOperationCount", ctypes.c_uint64),
        ("ReadTransferCount", ctypes.c_uint64),
        ("WriteTransferCount", ctypes.c_uint64),
        ("OtherTransferCount", ctypes.c_uint64),
    ]


class JobObjectExtendedLimitInformation(ctypes.Structure):
    """JOBOBJECT_EXTENDED_LIMIT_INFORMATION including kill-on-close flags."""

    _fields_ = [
        ("BasicLimitInformation", JobObjectBasicLimitInformation),
        ("IoInfo", IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


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


def abandon_lingering_process(process: TerminableProcess) -> bool:
    """Kill and wait with a bound; never block forever if the child survives."""
    if process.poll() is not None:
        return False
    LOGGER.error("process still running after drain; killing and abandoning")
    process.kill()
    try:
        process.wait(timeout=KILL_DRAIN_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        LOGGER.error("abandoning still-alive process after wait timeout")
        return True
    return process.poll() is None


def close_process_streams(process: subprocess.Popen[bytes]) -> None:
    """Close stdio handles; subprocess stubs type these streams as Any."""
    for stream in (process.stdin, process.stdout, process.stderr):  # type: ignore[misc]
        if stream is None:  # type: ignore[misc]
            continue
        try:
            stream.close()  # type: ignore[misc]
        except OSError:
            LOGGER.debug("failed to close process stream", exc_info=True)


def encode_stdin(stdin_text: str, encoding: str) -> bytes | None:
    """Encode stdin for the child, failing loudly on unencodable characters."""
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


def coerce_process_result(raw: object) -> ProcessResult:
    """Accept ProcessResult or the 4-tuple used by engine test doubles."""
    if isinstance(raw, ProcessResult):
        return raw
    if isinstance(raw, tuple) and len(raw) == 4:
        exit_code, stdout, stderr, timed_out = raw
        if (
            isinstance(exit_code, int)
            and isinstance(stdout, str)
            and isinstance(stderr, str)
            and isinstance(timed_out, bool)
        ):
            return ProcessResult(exit_code, stdout, stderr, timed_out)
    raise TypeError(f"unexpected process result: {raw!r}")


def ctypes_windll() -> object | None:
    """Return ctypes.windll when present (Windows)."""
    return getattr(ctypes, "windll", None)


def _try_set_winapi(
    func: object, *, restype: object, argtypes: tuple[object, ...]
) -> None:
    """Set ctypes restype/argtypes when the object supports it."""
    try:
        setattr(func, "restype", restype)
        setattr(func, "argtypes", list(argtypes))
    except (AttributeError, TypeError):
        LOGGER.debug("cannot set ctypes prototypes on %r", func)


def _configure_kernel32(kernel32: object) -> None:
    """Type Job Object APIs so 64-bit HANDLEs are not truncated to c_int."""
    _try_set_winapi(
        kernel32.CreateJobObjectW,  # type: ignore[union-attr]
        restype=wintypes.HANDLE,
        argtypes=(wintypes.LPVOID, wintypes.LPCWSTR),
    )
    _try_set_winapi(
        kernel32.SetInformationJobObject,  # type: ignore[union-attr]
        restype=wintypes.BOOL,
        argtypes=(
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
        ),
    )
    _try_set_winapi(
        kernel32.AssignProcessToJobObject,  # type: ignore[union-attr]
        restype=wintypes.BOOL,
        argtypes=(wintypes.HANDLE, wintypes.HANDLE),
    )
    _try_set_winapi(
        kernel32.CloseHandle,  # type: ignore[union-attr]
        restype=wintypes.BOOL,
        argtypes=(wintypes.HANDLE,),
    )


def _kernel32() -> object | None:
    windll = ctypes_windll()
    if windll is None:
        return None
    kernel32: object = windll.kernel32  # type: ignore[union-attr]
    _configure_kernel32(kernel32)
    return kernel32


def _handle_as_int(raw: object) -> int:
    """Coerce a ctypes HANDLE, integer, or None to a comparable int."""
    if raw is None or raw is False:
        return 0
    if isinstance(raw, int):
        return int(raw)
    converter = getattr(raw, "__int__", None)
    if callable(converter):
        try:
            converted = converter()
        except (TypeError, ValueError, OverflowError):
            LOGGER.error("unusable Win32 handle %r", raw)
            return 0
        if isinstance(converted, int):
            return converted
    LOGGER.error("unusable Win32 handle %r", raw)
    return 0


def _create_kill_on_close_job() -> int | None:
    """Create a Windows job that kills members when the handle is closed."""
    if sys.platform != "win32":
        return None
    kernel32 = _kernel32()
    if kernel32 is None:
        return None
    handle = _handle_as_int(kernel32.CreateJobObjectW(None, None))  # type: ignore[union-attr]
    if handle == 0:
        LOGGER.warning("CreateJobObjectW failed; falling back to taskkill")
        return None
    info = JobObjectExtendedLimitInformation()
    info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    ok = kernel32.SetInformationJobObject(  # type: ignore[union-attr]
        handle,
        JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
        ctypes.byref(info),
        ctypes.sizeof(info),
    )
    if not ok:
        LOGGER.warning("SetInformationJobObject failed; closing unused job")
        kernel32.CloseHandle(handle)  # type: ignore[union-attr]
        return None
    LOGGER.debug("created kill-on-close job handle=%s", handle)
    return handle


def _nt_resume_process(process_handle: int) -> int:
    """Resume every thread in a CREATE_SUSPENDED process via ntdll."""
    ntdll = ctypes.WinDLL("ntdll")
    _try_set_winapi(
        ntdll.NtResumeProcess,
        restype=ctypes.c_long,
        argtypes=(wintypes.HANDLE,),
    )
    return int(ntdll.NtResumeProcess(process_handle))


def _assign_and_resume(process: subprocess.Popen[bytes], job_handle: int) -> None:
    """Assign a suspended process to the job, then resume it.

    Popen closes the primary thread handle after CreateProcess, so
    ResumeThread is unavailable. NtResumeProcess is required. A missing
    handle or a failed resume leaves the child suspended, so this raises
    OSError and the caller must kill the tree.
    """
    kernel32 = _kernel32()
    if kernel32 is None:
        LOGGER.error("Win32 APIs unavailable; cannot resume suspended cmd.exe")
        raise OSError("Win32 APIs unavailable; cannot resume suspended cmd.exe")
    raw_handle = getattr(process, "_handle", None)
    if raw_handle is None:
        LOGGER.error("process has no _handle; cannot resume pid=%s", process.pid)
        raise OSError("process has no _handle; cannot resume suspended cmd.exe")
    process_handle = _handle_as_int(raw_handle)
    if process_handle == 0:
        LOGGER.error("process _handle is null; cannot resume pid=%s", process.pid)
        raise OSError("process _handle is null; cannot resume suspended cmd.exe")
    if not kernel32.AssignProcessToJobObject(job_handle, process_handle):  # type: ignore[union-attr]
        LOGGER.error(
            "AssignProcessToJobObject failed pid=%s; refusing to resume "
            "unisolated cmd.exe",
            process.pid,
        )
        raise OSError(
            f"AssignProcessToJobObject failed pid={process.pid}; "
            "refusing to resume cmd.exe outside the job"
        )
    status = _nt_resume_process(process_handle)
    if status != _NTSTATUS_SUCCESS:
        LOGGER.error("NtResumeProcess failed pid=%s status=%s", process.pid, status)
        raise OSError(
            f"NtResumeProcess failed pid={process.pid} status={status}; "
            "refusing to leave a suspended cmd.exe"
        )
    LOGGER.debug("assigned and resumed pid=%s job=%s", process.pid, job_handle)


def _close_job(job_handle: int | None) -> None:
    if job_handle is None or sys.platform != "win32":
        return
    kernel32 = _kernel32()
    if kernel32 is None:
        return
    if not kernel32.CloseHandle(job_handle):  # type: ignore[union-attr]
        LOGGER.error("CloseHandle failed for job handle=%s", job_handle)
    else:
        LOGGER.debug("closed job handle=%s (kill-on-close)", job_handle)


def _stop_job_and_tree(
    process: subprocess.Popen[bytes], job_handle: int | None
) -> None:
    """Close the job first (KILL_ON_JOB_CLOSE), then taskkill if needed."""
    LOGGER.warning("stopping captured process pid=%s job=%s", process.pid, job_handle)
    _close_job(job_handle)
    if process.poll() is None and process.pid is not None:
        kill_process_tree(process.pid)


def _read_capped_stream(
    stream: BinaryIO,
    max_bytes: int,
    chunks: list[bytes],
    overflow: list[bool],
) -> None:
    total = 0
    try:
        while True:
            data = stream.read(_STREAM_CHUNK_SIZE)
            if not data:
                return
            if overflow[0]:
                continue
            remaining = max_bytes - total
            if remaining <= 0:
                overflow[0] = True
                continue
            if len(data) > remaining:
                chunks.append(data[:remaining])
                total += remaining
                overflow[0] = True
                continue
            chunks.append(data)
            total += len(data)
    except OSError:
        LOGGER.debug("stream reader stopped", exc_info=True)


def _write_stdin(stream: BinaryIO | None, payload: bytes | None) -> None:
    if stream is None:
        return
    try:
        if payload:
            stream.write(payload)
            stream.flush()
    except OSError:
        LOGGER.warning("failed to write stdin", exc_info=True)
    finally:
        try:
            stream.close()
        except OSError:
            LOGGER.debug("failed to close stdin", exc_info=True)


def _join_readers(readers: list[threading.Thread]) -> None:
    for thread in readers:
        thread.join(timeout=KILL_DRAIN_TIMEOUT_SECONDS)
        if thread.is_alive():
            LOGGER.error("stream reader %s did not exit after kill", thread.name)


def _wait_capped(
    process: subprocess.Popen[bytes],
    stdin_bytes: bytes | None,
    timeout_seconds: float,
    max_bytes: int,
    job_handle: int | None,
) -> tuple[bytes, bytes, bool, bool, int | None]:
    stdout_chunks: list[bytes] = []
    stderr_chunks: list[bytes] = []
    stdout_overflow = [False]
    stderr_overflow = [False]
    readers: list[threading.Thread] = []
    stdout = process.stdout
    stderr = process.stderr
    if stdout is not None:
        thread = threading.Thread(
            target=_read_capped_stream,
            args=(stdout, max_bytes, stdout_chunks, stdout_overflow),
            daemon=True,
            name="battest-stdout",
        )
        readers.append(thread)
        thread.start()
    if stderr is not None:
        thread = threading.Thread(
            target=_read_capped_stream,
            args=(stderr, max_bytes, stderr_chunks, stderr_overflow),
            daemon=True,
            name="battest-stderr",
        )
        readers.append(thread)
        thread.start()
    _write_stdin(process.stdin, stdin_bytes)
    deadline = time.perf_counter() + timeout_seconds
    timed_out = False
    overflowed = False
    remaining_job = job_handle
    while process.poll() is None:
        if stdout_overflow[0] or stderr_overflow[0]:
            overflowed = True
            LOGGER.error(
                "process output exceeded %s bytes pid=%s",
                max_bytes,
                process.pid,
            )
            break
        if time.perf_counter() >= deadline:
            timed_out = True
            LOGGER.error("process timed out pid=%s", process.pid)
            break
        time.sleep(0.01)
    if stdout_overflow[0] or stderr_overflow[0]:
        overflowed = True
    if timed_out or overflowed:
        _stop_job_and_tree(process, remaining_job)
        remaining_job = None
    _join_readers(readers)
    return (
        b"".join(stdout_chunks),
        b"".join(stderr_chunks),
        timed_out,
        overflowed,
        remaining_job,
    )


def _creation_flags(job_handle: int | None) -> int:
    """Return CreateProcess flags for an optional kill-on-close job."""
    if sys.platform != "win32":
        return 0
    flags = CREATE_NEW_PROCESS_GROUP
    if job_handle is not None:
        flags |= CREATE_SUSPENDED
    return flags


def _spawn_captured_process(
    command: list[str],
    cwd: Path,
    env: dict[str, str],
    creationflags: int,
) -> subprocess.Popen[bytes]:
    """Start the child with pipes; caller owns wait and handle cleanup."""
    return subprocess.Popen(  # pylint: disable=consider-using-with
        command,
        cwd=str(cwd),
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=creationflags,
    )


def _cleanup_spawned_process(
    process: subprocess.Popen[bytes] | None,
    job_handle: int | None,
    abandoned: bool,
) -> bool:
    """Close pipes, kill leftovers, and close the job even if Popen failed."""
    still_abandoned = abandoned
    if process is not None:
        close_process_streams(process)
        if process.poll() is None:
            still_abandoned = abandon_lingering_process(process) or still_abandoned
    _close_job(job_handle)
    return still_abandoned


def run_process(
    command: list[str],
    cwd: Path,
    env: dict[str, str],
    stdin_text: str,
    timeout_seconds: float,
    encoding: str,
    max_bytes: int | None = None,
) -> ProcessResult:
    """Run command with a timeout, output cap, and optional Windows job."""
    limit = MAX_CAPTURE_BYTES if max_bytes is None else max_bytes
    LOGGER.debug("exec command=%s cwd=%s timeout=%s", command, cwd, timeout_seconds)
    if timeout_seconds <= 0:
        LOGGER.error(
            "timeout already expired before spawn command=%s timeout=%s",
            command,
            timeout_seconds,
        )
        return ProcessResult(-1, "", "", True)
    stdin_bytes = encode_stdin(stdin_text, encoding)
    job_handle = _create_kill_on_close_job()
    timed_out = False
    overflowed = False
    abandoned = False
    stdout_bytes = b""
    stderr_bytes = b""
    exit_code = -1
    pid: int | None = None
    process: subprocess.Popen[bytes] | None = None
    try:
        process = _spawn_captured_process(
            command, cwd, env, _creation_flags(job_handle)
        )
        pid = process.pid
        if job_handle is not None:
            try:
                _assign_and_resume(process, job_handle)
            except OSError:
                if process.pid is not None:
                    kill_process_tree(process.pid)
                raise
        stdout_bytes, stderr_bytes, timed_out, overflowed, job_handle = _wait_capped(
            process,
            stdin_bytes,
            timeout_seconds,
            limit,
            job_handle,
        )
        if timed_out or overflowed:
            abandoned = abandon_lingering_process(process)
        exit_code = process.returncode if process.returncode is not None else -1
    finally:
        abandoned = _cleanup_spawned_process(process, job_handle, abandoned)
    stdout = decode_output(stdout_bytes or b"", encoding)
    stderr = decode_output(stderr_bytes or b"", encoding)
    LOGGER.info(
        "exec finished exit=%s timeout=%s overflow=%s abandoned=%s "
        "stdout_len=%s stderr_len=%s pid=%s",
        exit_code,
        timed_out,
        overflowed,
        abandoned,
        len(stdout),
        len(stderr),
        pid,
    )
    return ProcessResult(
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        timed_out=timed_out,
        overflowed=overflowed,
        abandoned=abandoned,
        pid=pid,
    )


def is_path_outside_directory(candidate: str, root: Path) -> bool:
    """Return True when candidate resolves outside root.

    Absolute paths are resolved as given. Relative dumps are resolved against
    ``root`` (the case workdir), not the runner's current directory.
    """
    stripped = candidate.strip().strip('"')
    if not stripped:
        return False
    try:
        raw = Path(stripped)
        resolved = raw.resolve() if raw.is_absolute() else (root / raw).resolve()
        resolved.relative_to(root.resolve())
    except (OSError, ValueError):
        return True
    return False
