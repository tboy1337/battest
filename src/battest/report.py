"""Console and JUnit XML reporting."""

from __future__ import annotations

from pathlib import Path
from typing import Never, TextIO
import xml.etree.ElementTree as element_tree

from battest.constants import DEFAULT_MAX_DIFF
from battest.logging_config import get_logger
from battest.models import AssertionFailure, Outcome, RunResult

LOGGER = get_logger("report")


def xml_safe_text(value: str) -> str:
    """Replace characters that XML 1.0 cannot represent with U+FFFD."""
    cleaned_chars: list[str] = []
    changed = False
    for char in value:
        code = ord(char)
        allowed = (
            code in {0x9, 0xA, 0xD}
            or 0x20 <= code <= 0xD7FF
            or 0xE000 <= code <= 0xFFFD
            or 0x10000 <= code <= 0x10FFFF
        )
        if allowed:
            cleaned_chars.append(char)
        else:
            cleaned_chars.append("\ufffd")
            changed = True
    cleaned = "".join(cleaned_chars)
    if changed:
        LOGGER.debug("replaced illegal XML 1.0 characters in report text")
    return cleaned


def outcome_handled(outcome: Outcome) -> str:
    """Return the canonical label for an outcome (exhaustive)."""
    match outcome:
        case Outcome.PASS:
            return "PASS"
        case Outcome.FAIL:
            return "FAIL"
        case Outcome.ERROR:
            return "ERROR"
        case Outcome.TIMEOUT:
            return "TIMEOUT"
        case _:
            unreachable: Never = outcome
            raise ValueError(f"unhandled outcome: {unreachable}")


def _clip_report(text: str, max_diff: int = DEFAULT_MAX_DIFF) -> str:
    if len(text) <= max_diff:
        return text
    return text[:max_diff] + "\n... (truncated)"


def _failure_block(failures: list[AssertionFailure]) -> str:
    lines: list[str] = []
    for failure in failures:
        lines.append(f"{failure.kind}: {failure.message}")
        if failure.diff:
            lines.append(_clip_report(failure.diff.rstrip()))
        elif failure.expected is not None or failure.actual is not None:
            lines.append(f"  expected: {_clip_report(repr(failure.expected))}")
            lines.append(f"  actual:   {_clip_report(repr(failure.actual))}")
    return "\n".join(lines)


def render_console(results: list[RunResult], stream: TextIO) -> None:
    """Write pytest-like pass/fail lines and a summary."""
    passed = failed = errored = timed_out = 0
    for result in results:
        label = outcome_handled(result.outcome)
        duration = f"{result.duration_seconds:.3f}s"
        LOGGER.debug(
            "case %s outcome=%s duration=%s",
            result.case_id,
            result.outcome,
            duration,
        )
        stream.write(f"{label} {result.case_id} ({duration}) {result.description}\n")
        for warning in result.warnings:
            stream.write(f"  warning: {warning}\n")
        match result.outcome:
            case Outcome.PASS:
                passed += 1
            case Outcome.FAIL:
                failed += 1
                stream.write(_failure_block(result.failures) + "\n")
            case Outcome.ERROR:
                errored += 1
                stream.write(f"  error: {result.error_message}\n")
            case Outcome.TIMEOUT:
                timed_out += 1
                stream.write(f"  timeout: {result.error_message}\n")
            case _:
                unreachable: Never = result.outcome
                raise ValueError(f"unhandled outcome: {unreachable}")
    total = len(results)
    stream.write(
        f"\n{total} cases: {passed} passed, {failed} failed, "
        f"{errored} errors, {timed_out} timeouts\n"
    )
    LOGGER.info(
        "summary total=%s passed=%s failed=%s errors=%s timeouts=%s",
        total,
        passed,
        failed,
        errored,
        timed_out,
    )


def write_usage_junit(path: Path, message: str) -> None:
    """Write a one-testcase error suite for CLI usage or schema failures."""
    write_junit_xml(
        [
            RunResult(
                case_id="battest",
                description="battest run",
                outcome=Outcome.ERROR,
                error_message=message,
            )
        ],
        path,
    )


def write_junit_xml(results: list[RunResult], path: Path) -> None:
    """Write an xunit2-style JUnit XML report."""
    failures = sum(1 for item in results if item.outcome == Outcome.FAIL)
    errors = sum(
        1 for item in results if item.outcome in {Outcome.ERROR, Outcome.TIMEOUT}
    )
    total_time = sum(item.duration_seconds for item in results)
    suites = element_tree.Element("testsuites")
    suite = element_tree.SubElement(
        suites,
        "testsuite",
        {
            "name": "battest",
            "tests": str(len(results)),
            "failures": str(failures),
            "errors": str(errors),
            "skipped": "0",
            "time": f"{total_time:.3f}",
        },
    )
    for result in results:
        case = element_tree.SubElement(
            suite,
            "testcase",
            {
                "name": xml_safe_text(result.case_id),
                "classname": "battest",
                "time": f"{result.duration_seconds:.3f}",
            },
        )
        match result.outcome:
            case Outcome.PASS:
                pass
            case Outcome.FAIL:
                failure_message = (
                    result.failures[0].message if result.failures else "failed"
                )
                failure = element_tree.SubElement(
                    case,
                    "failure",
                    {"message": xml_safe_text(failure_message)},
                )
                failure.text = xml_safe_text(_failure_block(result.failures))
            case Outcome.ERROR:
                error = element_tree.SubElement(
                    case,
                    "error",
                    {"message": xml_safe_text(result.error_message or "error")},
                )
                error.text = xml_safe_text(result.error_message or "")
            case Outcome.TIMEOUT:
                error = element_tree.SubElement(
                    case,
                    "error",
                    {"message": xml_safe_text(result.error_message or "timeout")},
                )
                error.text = xml_safe_text(result.error_message or "timeout")
            case _:
                unreachable: Never = result.outcome
                raise ValueError(f"unhandled outcome: {unreachable}")
    tree = element_tree.ElementTree(suites)
    path.parent.mkdir(parents=True, exist_ok=True)
    tree.write(path, encoding="utf-8", xml_declaration=True)
    LOGGER.info("wrote junit xml %s", path)


def exit_status(results: list[RunResult]) -> int:
    """Return process exit code 1 when any case failed, timed out, or errored."""
    for result in results:
        if result.outcome != Outcome.PASS:
            return 1
    return 0
