"""Tests for console and JUnit reporting."""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from typing import cast

import pytest

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
    with pytest.raises(ValueError, match="unhandled outcome"):
        outcome_handled(cast(Outcome, object()))


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
    assert "expected:" in text
    assert exit_status(results) == 1
    assert exit_status([_result(Outcome.PASS)]) == 0


def test_render_console_includes_diff() -> None:
    stream = StringIO()
    result = RunResult(
        case_id="diff",
        description="desc",
        outcome=Outcome.FAIL,
        failures=[
            AssertionFailure(
                kind="stdout",
                message="mismatch",
                diff="--- expected\n+++ actual\n",
            )
        ],
        duration_seconds=0.01,
    )
    render_console([result], stream)
    assert "--- expected" in stream.getvalue()


def test_render_console_message_only_failure() -> None:
    stream = StringIO()
    result = RunResult(
        case_id="plain",
        description="desc",
        outcome=Outcome.FAIL,
        failures=[AssertionFailure(kind="stdout", message="no extras")],
        duration_seconds=0.01,
    )
    render_console([result], stream)
    text = stream.getvalue()
    assert "no extras" in text
    assert "expected:" not in text


def test_unhandled_outcome_in_reports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bogus = RunResult.model_construct(
        case_id="x",
        description="d",
        outcome=cast(Outcome, object()),
        failures=[],
        duration_seconds=0.01,
        warnings=[],
    )
    with pytest.raises(ValueError, match="unhandled outcome"):
        render_console([bogus], StringIO())
    with pytest.raises(ValueError, match="unhandled outcome"):
        write_junit_xml([bogus], tmp_path / "junit.xml")
    monkeypatch.setattr("battest.report.outcome_handled", lambda _outcome: "X")
    with pytest.raises(ValueError, match="unhandled outcome"):
        render_console([bogus], StringIO())


def test_failure_block_truncates_huge_actual() -> None:
    huge = "y" * 5000
    stream = StringIO()
    result = RunResult(
        case_id="big",
        description="desc",
        outcome=Outcome.FAIL,
        failures=[
            AssertionFailure(
                kind="stdout",
                message="mismatch",
                expected="short",
                actual=huge,
            )
        ],
        duration_seconds=0.01,
    )
    render_console([result], stream)
    text = stream.getvalue()
    assert "truncated" in text
    assert huge not in text


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


def test_write_junit_xml_empty_failure_and_missing_messages(tmp_path: Path) -> None:
    path = tmp_path / "junit.xml"
    write_junit_xml(
        [
            RunResult(
                case_id="empty-fail",
                description="d",
                outcome=Outcome.FAIL,
                failures=[],
                duration_seconds=0.01,
            ),
            RunResult(
                case_id="err",
                description="d",
                outcome=Outcome.ERROR,
                duration_seconds=0.01,
            ),
            RunResult(
                case_id="to",
                description="d",
                outcome=Outcome.TIMEOUT,
                duration_seconds=0.01,
            ),
        ],
        path,
    )
    text = path.read_text(encoding="utf-8")
    assert 'message="failed"' in text
    assert 'message="error"' in text
    assert 'message="timeout"' in text
