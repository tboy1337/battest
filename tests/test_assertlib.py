"""Tests for assertion helpers."""

from __future__ import annotations

from pathlib import Path

from battest.assertlib import (
    apply_newline_mode,
    evaluate_case,
    match_env,
    match_exit_code,
    match_files,
    match_mock_calls,
    match_output,
    unified_diff_text,
)
from battest.models import (
    CallExpectation,
    Case,
    EnvExpect,
    Expect,
    FileMatcher,
    MockSpec,
    NewlineMode,
    OutputMatcher,
)


def test_newline_auto_normalizes() -> None:
    assert apply_newline_mode("a\r\nb\r\n", NewlineMode.AUTO) == "a\nb\n"
    assert apply_newline_mode("a\r\nb\r\n", NewlineMode.CRLF) == "a\r\nb\r\n"


def test_match_output_equals_auto() -> None:
    matcher = OutputMatcher(equals="hello\n", newline=NewlineMode.AUTO)
    failures = match_output("stdout", matcher, "hello\r\n", Path("."), 200)
    assert failures == []


def test_match_output_contains_and_empty() -> None:
    empty_fail = match_output(
        "stderr",
        OutputMatcher(empty=True),
        "nope",
        Path("."),
        200,
    )
    assert empty_fail
    missing = match_output(
        "stdout",
        OutputMatcher(contains="needle"),
        "haystack",
        Path("."),
        200,
    )
    assert missing


def test_match_output_regex_and_equals_file(tmp_path: Path) -> None:
    expected = tmp_path / "out.txt"
    expected.write_text("abc\n", encoding="utf-8")
    matcher = OutputMatcher(equals_file=str(expected), regex="a.c")
    assert match_output("stdout", matcher, "abc\n", tmp_path, 200) == []
    failed = match_output("stdout", matcher, "zzz\n", tmp_path, 200)
    assert len(failed) >= 1


def test_match_exit_code() -> None:
    assert match_exit_code(0, 0) == []
    assert match_exit_code(0, 1)


def test_match_env_values_and_unset() -> None:
    expect = EnvExpect(values={"FOO": "bar"}, unset=["BAZ"])
    assert match_env(expect, {"FOO": "bar"}) == []
    assert match_env(expect, {"FOO": "nope"})
    assert match_env(expect, {"FOO": "bar", "BAZ": "1"})
    assert match_env(expect, {})


def test_match_files(tmp_path: Path) -> None:
    (tmp_path / "out.txt").write_text("hello world", encoding="utf-8")
    source = tmp_path / "expected.txt"
    source.write_text("hello world", encoding="utf-8")
    ok = match_files(
        [
            FileMatcher(
                path="out.txt",
                exists=True,
                contains="hello",
                equals_file="expected.txt",
            ),
            FileMatcher(path="missing.txt", not_exists=True),
        ],
        tmp_path,
        tmp_path,
        200,
    )
    assert ok == []
    bad = match_files(
        [FileMatcher(path="out.txt", equals="nope")],
        tmp_path,
        tmp_path,
        200,
    )
    assert bad


def test_match_mock_calls() -> None:
    mocks = {
        "ipconfig": MockSpec(expect_calls=[CallExpectation(args_contains="/flushdns")])
    }
    assert match_mock_calls(mocks, {"ipconfig": ["/flushdns"]}) == []
    assert match_mock_calls(mocks, {"ipconfig": ["/all"]})
    unused = {"net": MockSpec(expect_calls=[CallExpectation(not_called=True)])}
    assert match_mock_calls(unused, {"net": []}) == []
    assert match_mock_calls(unused, {"net": ["session"]})


def test_unified_diff_truncates() -> None:
    diff = unified_diff_text("a\n" * 50, "b\n" * 50, max_diff=40)
    assert "truncated" in diff


def test_evaluate_case_pass(tmp_path: Path) -> None:
    script = tmp_path / "input.cmd"
    script.write_text("@echo off\n", encoding="utf-8")
    manifest = tmp_path / "expect.yaml"
    manifest.write_text("x", encoding="utf-8")
    case = Case(
        case_id="t",
        description="t",
        source_path=manifest,
        script_path=script,
        expect=Expect(exit_code=0, stdout=OutputMatcher(contains="ok")),
    )
    failures = evaluate_case(case, 0, "ok\n", "", {}, tmp_path, {}, 200)
    assert failures == []
