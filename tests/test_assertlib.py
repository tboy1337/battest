"""Tests for assertion helpers."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from battest.assertlib import (
    _match_one_call,
    apply_newline_mode,
    evaluate_case,
    match_env,
    match_exit_code,
    match_files,
    match_mock_calls,
    match_output,
    newline_requirement_failure,
    unified_diff_text,
)
from battest.constants import MAX_REGEX_PATTERN_LENGTH
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
    assert apply_newline_mode("a\r\nb\r\n", NewlineMode.LF) == "a\nb\n"
    with pytest.raises(ValueError, match="unhandled newline mode"):
        apply_newline_mode("x", cast(NewlineMode, object()))
    with pytest.raises(ValueError, match="unhandled newline mode"):
        newline_requirement_failure("x", cast(NewlineMode, object()))


def test_crlf_mode_requires_crlf_and_accepts_lf_expected() -> None:
    assert newline_requirement_failure("hello\n", NewlineMode.CRLF) is not None
    assert newline_requirement_failure("hello\r\n", NewlineMode.CRLF) is None
    failures = match_output(
        "stdout",
        OutputMatcher(equals="hello\n", newline=NewlineMode.CRLF),
        "hello\r\n",
        Path("."),
        200,
    )
    assert failures == []
    lone_lf = match_output(
        "stdout",
        OutputMatcher(equals="hello\n", newline=NewlineMode.CRLF),
        "hello\n",
        Path("."),
        200,
    )
    assert lone_lf
    assert "lone LF" in lone_lf[0].message


def test_lf_mode_rejects_cr() -> None:
    assert newline_requirement_failure("hello\r\n", NewlineMode.LF) is not None
    assert newline_requirement_failure("hello\n", NewlineMode.LF) is None
    failures = match_output(
        "stdout",
        OutputMatcher(equals="hello\n", newline=NewlineMode.LF),
        "hello\n",
        Path("."),
        200,
    )
    assert failures == []
    crlf_actual = match_output(
        "stdout",
        OutputMatcher(equals="hello\n", newline=NewlineMode.LF),
        "hello\r\n",
        Path("."),
        200,
    )
    assert crlf_actual
    assert "CR bytes" in crlf_actual[0].message


def test_newline_only_matcher_enforces_line_endings() -> None:
    matcher = OutputMatcher(newline=NewlineMode.LF)
    assert matcher.has_constraint() is True
    failures = match_output("stdout", matcher, "hello\r\n", Path("."), 200)
    assert failures
    assert "CR bytes" in failures[0].message
    assert match_output("stdout", matcher, "hello\n", Path("."), 200) == []


@pytest.mark.parametrize(
    "text",
    [
        "",
        "plain",
        "a\nb\n",
        "a\r\nb\r\n",
        "a\rb\r",
        "mix\r\n\n\rend",
        "\r",
        "\n",
        "\r\n",
    ],
)
def test_newline_auto_strips_carriage_returns(text: str) -> None:
    normalized = apply_newline_mode(text, NewlineMode.AUTO)
    assert "\r" not in normalized
    assert apply_newline_mode(normalized, NewlineMode.AUTO) == normalized


def test_match_output_equals_success() -> None:
    failures = match_output(
        "stdout",
        OutputMatcher(equals="hello\n", newline=NewlineMode.AUTO),
        "hello\r\n",
        Path("."),
        200,
    )
    assert failures == []


def test_match_output_equals_mismatch() -> None:
    failures = match_output(
        "stdout",
        OutputMatcher(equals="hello\n"),
        "goodbye\n",
        Path("."),
        200,
    )
    assert failures
    assert "did not equal" in failures[0].message


def test_match_output_equals_file_content_mismatch(tmp_path: Path) -> None:
    golden = tmp_path / "expected.txt"
    golden.write_text("hello\n", encoding="utf-8")
    failures = match_output(
        "stdout",
        OutputMatcher(equals_file="expected.txt"),
        "goodbye\n",
        tmp_path,
        200,
    )
    assert failures
    assert "did not equal file" in failures[0].message


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


def test_match_output_empty_false() -> None:
    empty = match_output("stdout", OutputMatcher(empty=False), "", Path("."), 200)
    assert empty
    nonempty = match_output(
        "stdout", OutputMatcher(empty=False), "payload", Path("."), 200
    )
    assert nonempty == []


def test_match_output_regex_and_equals_file(tmp_path: Path) -> None:
    expected = tmp_path / "out.txt"
    expected.write_text("abc\n", encoding="utf-8")
    matcher = OutputMatcher(equals_file="out.txt", regex="a.c")
    assert match_output("stdout", matcher, "abc\n", tmp_path, 200) == []
    failed = match_output("stdout", matcher, "zzz\n", tmp_path, 200)
    assert len(failed) >= 1


def test_match_output_equals_file_rejects_escape(tmp_path: Path) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_text("classified\n", encoding="utf-8")
    source = tmp_path / "src"
    source.mkdir()
    failures = match_output(
        "stdout",
        OutputMatcher(equals_file="../secret.txt"),
        "classified\n",
        source,
        200,
    )
    assert failures
    assert "escapes" in failures[0].message


def test_match_output_equals_file_rejects_absolute(tmp_path: Path) -> None:
    golden = tmp_path / "expected.txt"
    golden.write_text("abc\n", encoding="utf-8")
    failures = match_output(
        "stdout",
        OutputMatcher(equals_file=str(golden)),
        "abc\n",
        tmp_path,
        200,
    )
    assert failures
    assert "escapes" in failures[0].message
    drive_relative = match_output(
        "stdout",
        OutputMatcher(equals_file="C:foo"),
        "abc\n",
        tmp_path,
        200,
    )
    assert drive_relative
    assert "escapes" in drive_relative[0].message
    unc = match_output(
        "stdout",
        OutputMatcher(equals_file="\\\\server\\share\\out.txt"),
        "abc\n",
        tmp_path,
        200,
    )
    assert unc
    assert "escapes" in unc[0].message


def test_invalid_regex_is_rejected_at_model() -> None:
    with pytest.raises(ValueError, match="invalid regex"):
        OutputMatcher(regex="(")


def test_nested_quantifier_regex_is_rejected_at_model() -> None:
    with pytest.raises(ValueError, match="nested quantifiers"):
        OutputMatcher(regex="(a+)+")
    with pytest.raises(ValueError, match="nested quantifiers"):
        OutputMatcher(regex="(a*)*")


def test_quantified_alternation_regex_is_rejected_at_model() -> None:
    with pytest.raises(ValueError, match="quantified alternation"):
        OutputMatcher(regex="(a|a)*")
    with pytest.raises(ValueError, match="quantified alternation"):
        OutputMatcher(regex="(a|aa)+")


def test_regex_pattern_length_is_capped() -> None:
    with pytest.raises(ValueError, match="exceeds"):
        OutputMatcher(regex="a" * (MAX_REGEX_PATTERN_LENGTH + 1))


def test_match_output_invalid_regex_is_failure() -> None:
    matcher = OutputMatcher.model_construct(regex="(")
    failures = match_output("stdout", matcher, "abc", Path("."), 200)
    assert failures
    assert "invalid regex" in failures[0].message


def test_match_output_equals_file_missing_is_failure(tmp_path: Path) -> None:
    matcher = OutputMatcher(equals_file="missing-golden.txt")
    failures = match_output("stdout", matcher, "abc\n", tmp_path, 200)
    assert len(failures) == 1
    assert "missing-golden.txt" in failures[0].message


def test_match_output_equals_file_invalid_utf8_is_failure(tmp_path: Path) -> None:
    golden = tmp_path / "expected.txt"
    golden.write_bytes(b"\xff\xfe not utf-8")
    failures = match_output(
        "stdout",
        OutputMatcher(equals_file="expected.txt"),
        "hello\n",
        tmp_path,
        200,
    )
    assert len(failures) == 1
    assert (
        "unreadable" in failures[0].message.lower()
        or "utf" in failures[0].message.lower()
    )


def test_match_output_regex_does_not_normalize_pattern() -> None:
    failures = match_output(
        "stdout",
        OutputMatcher(regex="foo\rbar", newline=NewlineMode.AUTO),
        "foo\nbar",
        Path("."),
        200,
    )
    assert failures
    assert "did not match regex" in failures[0].message


def test_match_exit_code() -> None:
    assert match_exit_code(0, 0) == []
    assert match_exit_code(0, 1)
    assert match_exit_code(None, 7) == []


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


def test_match_files_rejects_path_escape(tmp_path: Path) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_text("classified", encoding="utf-8")
    work = tmp_path / "work"
    work.mkdir()
    failures = match_files(
        [FileMatcher(path="../secret.txt", exists=True)],
        work,
        tmp_path,
        200,
    )
    assert failures
    assert (
        "work" in failures[0].message.lower() or "escap" in failures[0].message.lower()
    )


def test_match_files_equals_file_missing_is_failure(tmp_path: Path) -> None:
    (tmp_path / "out.txt").write_text("hello", encoding="utf-8")
    failures = match_files(
        [FileMatcher(path="out.txt", equals_file="no-such-golden.txt")],
        tmp_path,
        tmp_path,
        200,
    )
    assert failures
    assert "no-such-golden.txt" in failures[0].message


def test_match_files_exists_and_not_exists(tmp_path: Path) -> None:
    (tmp_path / "present.txt").write_text("x", encoding="utf-8")
    missing = match_files(
        [FileMatcher(path="absent.txt", exists=True)],
        tmp_path,
        tmp_path,
        200,
    )
    assert missing
    present = match_files(
        [FileMatcher(path="present.txt", not_exists=True)],
        tmp_path,
        tmp_path,
        200,
    )
    assert present


def test_match_files_content_checks(tmp_path: Path) -> None:
    (tmp_path / "out.txt").write_text("hello", encoding="utf-8")
    golden = tmp_path / "expected.txt"
    golden.write_text("hello", encoding="utf-8")
    wrong_golden = tmp_path / "other.txt"
    wrong_golden.write_text("other", encoding="utf-8")
    missing_file = match_files(
        [FileMatcher(path="nope.txt", contains="x")],
        tmp_path,
        tmp_path,
        200,
    )
    assert "file not found" in missing_file[0].message
    contains_miss = match_files(
        [FileMatcher(path="out.txt", contains="zzz")],
        tmp_path,
        tmp_path,
        200,
    )
    assert "did not contain" in contains_miss[0].message
    equals_file_miss = match_files(
        [FileMatcher(path="out.txt", equals_file="other.txt")],
        tmp_path,
        tmp_path,
        200,
    )
    assert "did not equal" in equals_file_miss[0].message


def test_match_files_exists_false_means_absent(tmp_path: Path) -> None:
    (tmp_path / "present.txt").write_text("x", encoding="utf-8")
    absent_ok = match_files(
        [FileMatcher(path="gone.txt", exists=False)],
        tmp_path,
        tmp_path,
        200,
    )
    assert absent_ok == []
    present_fail = match_files(
        [FileMatcher(path="present.txt", exists=False)],
        tmp_path,
        tmp_path,
        200,
    )
    assert present_fail
    assert "absent" in present_fail[0].message


def test_read_equals_file_oserror(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    golden = tmp_path / "golden.txt"
    golden.write_text("expected", encoding="utf-8")
    original = Path.read_text

    def boom(self: Path, *args: object, **kwargs: object) -> str:
        if self.resolve() == golden.resolve():
            raise OSError("locked-golden")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", boom)
    failures = match_output(
        "stdout",
        OutputMatcher(equals_file="golden.txt"),
        "expected",
        tmp_path,
        200,
    )
    assert failures
    assert "equals_file unreadable" in failures[0].message
    assert "locked-golden" in failures[0].message


def test_match_output_truncates_large_actual() -> None:
    huge = "x" * 5000
    failures = match_output(
        "stdout",
        OutputMatcher(contains="missing"),
        huge,
        Path("."),
        40,
    )
    assert failures
    assert failures[0].actual is not None
    assert len(failures[0].actual) < 80
    assert "truncated" in failures[0].actual


def test_match_files_read_oserror(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "out.txt"
    target.write_text("hello", encoding="utf-8")
    original = Path.read_text

    def boom(self: Path, *args: object, **kwargs: object) -> str:
        if self.resolve() == target.resolve():
            raise OSError("denied")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", boom)
    failures = match_files(
        [FileMatcher(path="out.txt", contains="hello")],
        tmp_path,
        tmp_path,
        200,
    )
    assert failures
    assert "failed to read" in failures[0].message
    assert "denied" in failures[0].message


def test_match_files_invalid_utf8_is_failure(tmp_path: Path) -> None:
    target = tmp_path / "out.bin"
    target.write_bytes(b"\xff\xfe binary")
    failures = match_files(
        [FileMatcher(path="out.bin", contains="hello")],
        tmp_path,
        tmp_path,
        200,
    )
    assert failures
    assert "not valid utf-8" in failures[0].message


def test_match_mock_calls() -> None:
    mocks = {
        "ipconfig": MockSpec(expect_calls=[CallExpectation(args_contains="/flushdns")])
    }
    assert match_mock_calls(mocks, {"ipconfig": ["/flushdns"]}) == []
    assert match_mock_calls(mocks, {"ipconfig": ["/all"]})
    unused = {"net": MockSpec(expect_calls=[CallExpectation(not_called=True)])}
    assert match_mock_calls(unused, {"net": []}) == []
    assert match_mock_calls(unused, {"net": ["session"]})
    with pytest.raises(ValueError, match="args_contains or not_called"):
        CallExpectation()
    with pytest.raises(ValueError, match="not_called"):
        CallExpectation(not_called=False)


def test_match_one_call_without_constraint_is_noop() -> None:
    empty = CallExpectation.model_construct()
    assert _match_one_call("net", empty, ["session"], 2000) == []


def test_match_mock_calls_whitespace_only_line_counts_as_call() -> None:
    unused = {"net": MockSpec(expect_calls=[CallExpectation(not_called=True)])}
    failures = match_mock_calls(unused, {"net": ["   "]})
    assert failures


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
    failed = evaluate_case(case, 1, "nope\n", "err", {}, tmp_path, {}, 200)
    assert len(failed) >= 2
    kinds = {item.kind for item in failed}
    assert "exit_code" in kinds
    assert "stdout" in kinds
