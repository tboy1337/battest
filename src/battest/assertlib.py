"""Assertions and readable failure diffs."""

from __future__ import annotations

import difflib
from pathlib import Path
import re
from typing import Never

from battest.constants import DEFAULT_MAX_DIFF
from battest.logging_config import get_logger
from battest.models import (
    AssertionFailure,
    CallExpectation,
    Case,
    EnvExpect,
    FileMatcher,
    MockSpec,
    NewlineMode,
    OutputMatcher,
)

LOGGER = get_logger("assertlib")


def unified_diff_text(expected: str, actual: str, max_diff: int) -> str:
    """Return a unified diff, truncated to max_diff characters."""
    rendered = "".join(
        difflib.unified_diff(
            expected.splitlines(keepends=True),
            actual.splitlines(keepends=True),
            fromfile="expected",
            tofile="actual",
        )
    )
    if len(rendered) > max_diff:
        return rendered[:max_diff] + "\n... (truncated)"
    return rendered


def apply_newline_mode(text: str, mode: NewlineMode) -> str:
    """Normalize newlines according to matcher mode."""
    match mode:
        case NewlineMode.AUTO | NewlineMode.LF:
            return text.replace("\r\n", "\n").replace("\r", "\n")
        case NewlineMode.CRLF:
            return text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\r\n")
        case _:
            unreachable: Never = mode
            raise ValueError(f"unhandled newline mode: {unreachable}")


def newline_requirement_failure(actual: str, mode: NewlineMode) -> str | None:
    """Return a failure message when actual line endings violate mode."""
    match mode:
        case NewlineMode.AUTO:
            return None
        case NewlineMode.LF:
            if "\r" in actual:
                return "contained CR bytes; newline: lf requires LF-only line endings"
            return None
        case NewlineMode.CRLF:
            if "\n" in actual.replace("\r\n", ""):
                return "contained lone LF; newline: crlf requires CRLF line endings"
            return None
        case _:
            unreachable: Never = mode
            raise ValueError(f"unhandled newline mode: {unreachable}")


def confined_source_path(source_dir: Path, relative: str) -> Path | None:
    """Return source_dir/relative when it stays inside source_dir, else None."""
    if Path(relative).is_absolute():
        LOGGER.warning("path %s is absolute; rejected", relative)
        return None
    return confined_work_path(source_dir, relative)


def _read_equals_file(source_dir: Path, relative: str) -> tuple[str | None, str | None]:
    path = confined_source_path(source_dir, relative)
    if path is None:
        return None, f"equals_file escapes source directory: {relative}"
    try:
        return path.read_text(encoding="utf-8"), None
    except FileNotFoundError:
        LOGGER.error("equals_file missing %s", path)
        return None, f"equals_file not found: {relative}"
    except UnicodeDecodeError as exc:
        LOGGER.error("equals_file is not utf-8 %s: %s", path, exc)
        return None, f"equals_file unreadable: {relative} (not valid utf-8: {exc})"
    except OSError as exc:
        LOGGER.error("equals_file unreadable %s: %s", path, exc)
        return None, f"equals_file unreadable: {relative} ({exc})"


def confined_work_path(work_dir: Path, relative: str) -> Path | None:
    """Return work_dir/relative when it stays inside work_dir, else None."""
    resolved_root = work_dir.resolve()
    try:
        candidate = (work_dir / relative).resolve()
        candidate.relative_to(resolved_root)
    except (OSError, ValueError):
        LOGGER.warning("path %s escapes work dir %s", relative, work_dir)
        return None
    return candidate


def _clip(text: str | None, max_diff: int) -> str | None:
    if text is None:
        return None
    if len(text) <= max_diff:
        return text
    return text[:max_diff] + "\n... (truncated)"


def _fail(
    kind: str,
    message: str,
    expected: str | None = None,
    actual: str | None = None,
    diff: str | None = None,
    max_diff: int = DEFAULT_MAX_DIFF,
) -> AssertionFailure:
    LOGGER.debug("assertion failure kind=%s message=%s", kind, message)
    return AssertionFailure(
        kind=kind,
        message=message,
        expected=_clip(expected, max_diff),
        actual=_clip(actual, max_diff),
        diff=_clip(diff, max_diff),
    )


def match_output(
    stream_name: str,
    matcher: OutputMatcher | None,
    actual: str,
    source_dir: Path,
    max_diff: int,
) -> list[AssertionFailure]:
    """Evaluate stdout/stderr matchers."""
    if matcher is None or not matcher.has_constraint():
        return []
    failures: list[AssertionFailure] = []
    actual_cmp = apply_newline_mode(actual, matcher.newline)
    requirement = newline_requirement_failure(actual, matcher.newline)
    if requirement is not None:
        failures.append(_fail(stream_name, f"{stream_name} {requirement}"))
    if matcher.empty is True and actual_cmp.strip() != "":
        failures.append(
            _fail(
                stream_name,
                f"{stream_name} was not empty",
                expected="",
                actual=actual,
                diff=unified_diff_text("", actual_cmp, max_diff),
                max_diff=max_diff,
            )
        )
    if matcher.empty is False and actual_cmp.strip() == "":
        failures.append(_fail(stream_name, f"{stream_name} was empty"))
    if matcher.equals is not None:
        expected_cmp = apply_newline_mode(matcher.equals, matcher.newline)
        if actual_cmp != expected_cmp:
            failures.append(
                _fail(
                    stream_name,
                    f"{stream_name} did not equal expected text",
                    expected=matcher.equals,
                    actual=actual,
                    diff=unified_diff_text(expected_cmp, actual_cmp, max_diff),
                    max_diff=max_diff,
                )
            )
    if matcher.equals_file is not None:
        expected_text, error = _read_equals_file(source_dir, matcher.equals_file)
        if error is not None:
            failures.append(
                _fail(
                    stream_name,
                    f"{stream_name} {error}",
                    expected=matcher.equals_file,
                    max_diff=max_diff,
                )
            )
        else:
            assert expected_text is not None
            expected_cmp = apply_newline_mode(expected_text, matcher.newline)
            if actual_cmp != expected_cmp:
                failures.append(
                    _fail(
                        stream_name,
                        f"{stream_name} did not equal file {matcher.equals_file}",
                        expected=expected_text,
                        actual=actual,
                        diff=unified_diff_text(expected_cmp, actual_cmp, max_diff),
                        max_diff=max_diff,
                    )
                )
    if matcher.contains is not None:
        needle = apply_newline_mode(matcher.contains, matcher.newline)
        if needle not in actual_cmp:
            failures.append(
                _fail(
                    stream_name,
                    f"{stream_name} did not contain expected text",
                    expected=matcher.contains,
                    actual=actual,
                    max_diff=max_diff,
                )
            )
    if matcher.regex is not None:
        pattern = matcher.regex
        try:
            matched = re.search(pattern, actual_cmp, re.MULTILINE)
        except re.error as exc:
            failures.append(
                _fail(
                    stream_name,
                    f"{stream_name} invalid regex: {exc}",
                    expected=matcher.regex,
                    actual=actual,
                    max_diff=max_diff,
                )
            )
        else:
            if matched is None:
                failures.append(
                    _fail(
                        stream_name,
                        f"{stream_name} did not match regex",
                        expected=matcher.regex,
                        actual=actual,
                        max_diff=max_diff,
                    )
                )
    return failures


def match_exit_code(expected: int | None, actual: int | None) -> list[AssertionFailure]:
    """Compare exit codes when an expectation is set."""
    if expected is None:
        return []
    if actual != expected:
        return [
            _fail(
                "exit_code",
                f"exit code {actual} != {expected}",
                expected=str(expected),
                actual=str(actual),
            )
        ]
    return []


def match_env(
    expect: EnvExpect | None, actual: dict[str, str]
) -> list[AssertionFailure]:
    """Compare selected environment variables."""
    if expect is None:
        return []
    failures: list[AssertionFailure] = []
    lookup = {name.upper(): (name, value) for name, value in actual.items()}
    for name, expected_value in expect.values.items():
        found = lookup.get(name.upper())
        if found is None:
            failures.append(
                _fail(
                    "env",
                    f"environment variable {name} was not set",
                    expected=expected_value,
                )
            )
            continue
        _, actual_value = found
        if actual_value != expected_value:
            failures.append(
                _fail(
                    "env",
                    f"environment variable {name} mismatch",
                    expected=expected_value,
                    actual=actual_value,
                )
            )
    for name in expect.unset:
        if name.upper() in lookup:
            _, actual_value = lookup[name.upper()]
            failures.append(
                _fail(
                    "env",
                    f"environment variable {name} should be unset",
                    expected="",
                    actual=actual_value,
                )
            )
    return failures


def match_files(
    matchers: list[FileMatcher],
    work_dir: Path,
    source_dir: Path,
    max_diff: int,
) -> list[AssertionFailure]:
    """Compare filesystem expectations against the isolated working directory."""
    failures: list[AssertionFailure] = []
    for matcher in matchers:
        path = confined_work_path(work_dir, matcher.path)
        if path is None:
            failures.append(
                _fail("files", f"path escapes work directory: {matcher.path}")
            )
            continue
        exists = path.is_file() or path.is_dir()
        missing = matcher.exists is False or matcher.not_exists is True
        if matcher.exists is True and not exists:
            failures.append(_fail("files", f"expected path to exist: {matcher.path}"))
        if missing and exists:
            failures.append(
                _fail("files", f"expected path to be absent: {matcher.path}")
            )
        if (
            matcher.contains is not None
            or matcher.equals is not None
            or matcher.equals_file is not None
        ):
            if not path.is_file():
                failures.append(
                    _fail("files", f"file not found for content check: {matcher.path}")
                )
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                LOGGER.error("failed to read %s: %s", path, exc)
                failures.append(
                    _fail(
                        "files",
                        f"failed to read {matcher.path} for content check: {exc}",
                    )
                )
                continue
            if matcher.contains is not None and matcher.contains not in text:
                failures.append(
                    _fail(
                        "files",
                        f"file {matcher.path} did not contain expected text",
                        expected=matcher.contains,
                        actual=text,
                        max_diff=max_diff,
                    )
                )
            if matcher.equals is not None and text != matcher.equals:
                failures.append(
                    _fail(
                        "files",
                        f"file {matcher.path} content mismatch",
                        expected=matcher.equals,
                        actual=text,
                        diff=unified_diff_text(matcher.equals, text, max_diff),
                        max_diff=max_diff,
                    )
                )
            if matcher.equals_file is not None:
                expected_text, error = _read_equals_file(
                    source_dir, matcher.equals_file
                )
                if error is not None:
                    failures.append(_fail("files", error, max_diff=max_diff))
                    continue
                assert expected_text is not None
                if text != expected_text:
                    failures.append(
                        _fail(
                            "files",
                            f"file {matcher.path} did not equal {matcher.equals_file}",
                            expected=expected_text,
                            actual=text,
                            diff=unified_diff_text(expected_text, text, max_diff),
                            max_diff=max_diff,
                        )
                    )
    return failures


def match_mock_calls(
    mocks: dict[str, MockSpec],
    recorded: dict[str, list[str]],
    max_diff: int = DEFAULT_MAX_DIFF,
) -> list[AssertionFailure]:
    """Evaluate expect_calls against recorded PATH-stub argv lines."""
    failures: list[AssertionFailure] = []
    for name, spec in mocks.items():
        lines = recorded.get(name.lower(), [])
        for expectation in spec.expect_calls:
            failures.extend(_match_one_call(name, expectation, lines, max_diff))
    return failures


def _match_one_call(
    name: str,
    expectation: CallExpectation,
    lines: list[str],
    max_diff: int,
) -> list[AssertionFailure]:
    if expectation.not_called is True:
        if lines:
            return [
                _fail(
                    "mocks",
                    f"expected {name} not to be called",
                    expected="",
                    actual="\n".join(lines),
                    max_diff=max_diff,
                )
            ]
        return []
    if expectation.args_contains is not None:
        needle = expectation.args_contains
        if not any(needle in line for line in lines):
            return [
                _fail(
                    "mocks",
                    f"{name} was not called with arguments containing {needle!r}",
                    expected=needle,
                    actual="\n".join(lines),
                    max_diff=max_diff,
                )
            ]
    return []


def evaluate_case(
    case: Case,
    exit_code: int | None,
    stdout: str,
    stderr: str,
    env: dict[str, str],
    work_dir: Path,
    mock_calls: dict[str, list[str]],
    max_diff: int,
) -> list[AssertionFailure]:
    """Run every configured assertion for a case."""
    LOGGER.info("evaluating assertions case_id=%s exit=%s", case.case_id, exit_code)
    source_dir = case.source_path.parent
    failures: list[AssertionFailure] = []
    failures.extend(match_exit_code(case.expect.exit_code, exit_code))
    failures.extend(
        match_output("stdout", case.expect.stdout, stdout, source_dir, max_diff)
    )
    failures.extend(
        match_output("stderr", case.expect.stderr, stderr, source_dir, max_diff)
    )
    failures.extend(match_env(case.expect.env, env))
    failures.extend(match_files(case.expect.files, work_dir, source_dir, max_diff))
    failures.extend(match_mock_calls(case.mocks, mock_calls, max_diff))
    LOGGER.info("assertion failures case_id=%s count=%s", case.case_id, len(failures))
    return failures
