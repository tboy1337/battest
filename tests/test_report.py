"""Tests for console and JUnit reporting."""

from __future__ import annotations

from io import StringIO
from pathlib import Path

from battest.models import AssertionFailure, Outcome, RunResult
from battest.report import exit_status, outcome_handled, render_console, write_junit_xml


def _result(outcome: Outcome, case_id: str = "c") -> RunResult:
    failures = []
    if outcome == Outcome.FAIL:
        failures = [
            AssertionFailure(kind="exit_code", message="bad", expected="0", actual="1")
        ]
    error = None
    if outcome in {Outcome.ERROR, Outcome.TIMEOUT}:
        error = "boom"
    return RunResult(
        case_id=case_id,
        description="desc",
        outcome=outcome,
        failures=failures,
        error_message=error,
        duration_seconds=0.01,
        warnings=["note"],
    )


def test_outcome_handled_exhaustive() -> None:
    assert outcome_handled(Outcome.PASS) == "PASS"
    assert outcome_handled(Outcome.FAIL) == "FAIL"
    assert outcome_handled(Outcome.ERROR) == "ERROR"
    assert outcome_handled(Outcome.TIMEOUT) == "TIMEOUT"


def test_render_console_and_exit_status() -> None:
    stream = StringIO()
    results = [
        _result(Outcome.PASS, "ok"),
        _result(Outcome.FAIL, "bad"),
        _result(Outcome.ERROR, "err"),
        _result(Outcome.TIMEOUT, "to"),
    ]
    render_console(results, stream)
    text = stream.getvalue()
    assert "PASS ok" in text
    assert "FAIL bad" in text
    assert "ERROR err" in text
    assert "TIMEOUT to" in text
    assert "warning: note" in text
    assert exit_status(results) == 1
    assert exit_status([_result(Outcome.PASS)]) == 0


def test_write_junit_xml(tmp_path: Path) -> None:
    path = tmp_path / "out" / "junit.xml"
    write_junit_xml(
        [
            _result(Outcome.PASS, "ok"),
            _result(Outcome.FAIL, "bad"),
            _result(Outcome.ERROR, "err"),
            _result(Outcome.TIMEOUT, "to"),
        ],
        path,
    )
    text = path.read_text(encoding="utf-8")
    assert 'tests="4"' in text
    assert "<failure" in text
    assert "<error" in text
    assert 'name="ok"' in text
