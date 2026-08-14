"""Tests for environment snapshot parsing."""

from __future__ import annotations

import pytest

from battest.envsnap import filter_helper_vars, parse_set_output


def test_parse_set_output_splits_on_first_equals() -> None:
    text = "FOO=bar\nPATH=C:\\a;C:\\b=c\n\n=ignored\n"
    env = parse_set_output(text)
    assert env["FOO"] == "bar"
    assert env["PATH"] == "C:\\a;C:\\b=c"
    assert "" not in env


def test_filter_helper_vars() -> None:
    env = filter_helper_vars(
        {"FOO": "1", "BATTEST_SUT": "x", "battest_envfile": "y", "Path": "z"}
    )
    assert env == {"FOO": "1", "Path": "z"}


@pytest.mark.parametrize(
    "mapping",
    [
        {},
        {"FOO": "bar"},
        {"EMPTY": ""},
        {"EQUALS": "a=b=c"},
        {"PATH": r"C:\a;C:\b"},
        {"A": "one", "B": "two"},
        {"SPACES": "hello world"},
        {"UNICODE": "café"},
    ],
)
def test_parse_set_output_roundtrip(mapping: dict[str, str]) -> None:
    dumped = "\n".join(f"{name}={value}" for name, value in mapping.items())
    assert parse_set_output(dumped) == mapping
    assert parse_set_output("") == {}
