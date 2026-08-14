"""Tests for YAML schema loading and param expansion."""

from __future__ import annotations

from pathlib import Path

import pytest

from battest.models import CaseDocument, OutputMatcher
from battest.schema import (
    SchemaError,
    load_cases_from_path,
    parse_document,
    schema_payload,
)


def _write_script(folder: Path, name: str = "input.cmd") -> Path:
    path = folder / name
    path.write_text("@echo off\r\necho hi\r\nexit /b 0\r\n", encoding="utf-8")
    return path


def test_schema_payload_is_object() -> None:
    payload = schema_payload()
    assert payload["title"] == "battest fixture document"
    assert "expect" in payload["$defs"]


def test_parse_document_rejects_empty_description() -> None:
    with pytest.raises(SchemaError):
        parse_document(
            {"description": "  ", "expect": {"exit_code": 0}}, Path("x.yaml")
        )


def test_load_case_directory(tmp_path: Path) -> None:
    _write_script(tmp_path)
    (tmp_path / "expect.yaml").write_text(
        "description: hello case\nexpect:\n  exit_code: 0\n",
        encoding="utf-8",
    )
    cases = load_cases_from_path(tmp_path / "expect.yaml")
    assert len(cases) == 1
    assert cases[0].case_id == tmp_path.name
    assert cases[0].script_path.name == "input.cmd"


def test_load_manifest_with_script(tmp_path: Path) -> None:
    script = _write_script(tmp_path, "tool.cmd")
    manifest = tmp_path / "tool.battest.yaml"
    manifest.write_text(
        "description: tool\nscript: tool.cmd\nexpect:\n  exit_code: 0\n",
        encoding="utf-8",
    )
    cases = load_cases_from_path(manifest)
    assert cases[0].script_path == script.resolve()


def test_missing_fixture_file(tmp_path: Path) -> None:
    with pytest.raises(SchemaError, match="not found"):
        load_cases_from_path(tmp_path / "nope.yaml")


def test_root_must_be_mapping(tmp_path: Path) -> None:
    path = tmp_path / "list.battest.yaml"
    path.write_text("- just a list\n", encoding="utf-8")
    with pytest.raises(SchemaError, match="mapping"):
        load_cases_from_path(path)


def test_setup_missing(tmp_path: Path) -> None:
    (tmp_path / "run.cmd").write_text("@echo off\n", encoding="utf-8")
    manifest = tmp_path / "run.battest.yaml"
    manifest.write_text(
        "description: setup\nscript: run.cmd\nsetup: missing.cmd\nexpect:\n  exit_code: 0\n",
        encoding="utf-8",
    )
    with pytest.raises(SchemaError, match="setup script"):
        load_cases_from_path(manifest)
    manifest = tmp_path / "missing.battest.yaml"
    manifest.write_text(
        "description: missing\nexpect:\n  exit_code: 0\n",
        encoding="utf-8",
    )
    with pytest.raises(SchemaError, match="input.cmd"):
        load_cases_from_path(manifest)


def test_params_expand_base_and_overlay(tmp_path: Path) -> None:
    _write_script(tmp_path, "run.cmd")
    manifest = tmp_path / "run.battest.yaml"
    manifest.write_text(
        "\n".join(
            [
                "description: matrix",
                "script: run.cmd",
                "args: [a]",
                "expect:",
                "  exit_code: 0",
                "params:",
                "  - id: other",
                "    args: [b]",
                "    expect:",
                "      exit_code: 1",
            ]
        ),
        encoding="utf-8",
    )
    cases = load_cases_from_path(manifest)
    assert [item.case_id for item in cases] == ["run", "run[other]"]
    assert cases[0].args == ["a"]
    assert cases[1].args == ["b"]
    assert cases[1].expect.exit_code == 1
    assert cases[0].expect.exit_code == 0


def test_deprecated_command_warning(tmp_path: Path) -> None:
    _write_script(tmp_path, "run.cmd")
    manifest = tmp_path / "run.battest.yaml"
    manifest.write_text(
        "\n".join(
            [
                "description: deprecated mock",
                "script: run.cmd",
                "mocks:",
                "  wmic:",
                "    exit_code: 0",
                "expect:",
                "  exit_code: 0",
            ]
        ),
        encoding="utf-8",
    )
    cases = load_cases_from_path(manifest)
    assert any("deprecated" in item for item in cases[0].warnings)


def test_internal_mock_warning(tmp_path: Path) -> None:
    _write_script(tmp_path, "run.cmd")
    manifest = tmp_path / "run.battest.yaml"
    manifest.write_text(
        "\n".join(
            [
                "description: internal mock",
                "script: run.cmd",
                "mocks:",
                "  del:",
                "    exit_code: 0",
                "expect:",
                "  exit_code: 0",
            ]
        ),
        encoding="utf-8",
    )
    cases = load_cases_from_path(manifest)
    assert any("internal" in item for item in cases[0].warnings)


def test_invalid_yaml(tmp_path: Path) -> None:
    path = tmp_path / "bad.battest.yaml"
    path.write_text(":\n  -", encoding="utf-8")
    with pytest.raises(SchemaError, match="invalid YAML"):
        load_cases_from_path(path)


def test_env_expect_plain_mapping() -> None:
    document = parse_document(
        {
            "description": "env",
            "script": "x.cmd",
            "expect": {"env": {"FOO": "bar", "unset": ["BAZ"]}},
        },
        Path("doc.yaml"),
    )
    assert document.expect.env is not None
    assert document.expect.env.values["FOO"] == "bar"
    assert document.expect.env.unset == ["BAZ"]


def test_file_matcher_conflict() -> None:
    with pytest.raises(SchemaError):
        parse_document(
            {
                "description": "files",
                "expect": {
                    "files": [{"path": "a.txt", "exists": True, "not_exists": True}]
                },
            },
            Path("doc.yaml"),
        )


def test_timeout_must_be_positive() -> None:
    with pytest.raises(SchemaError):
        parse_document(
            {"description": "t", "timeout_seconds": 0, "expect": {"exit_code": 0}},
            Path("doc.yaml"),
        )


def test_copy_path_must_exist(tmp_path: Path) -> None:
    _write_script(tmp_path, "run.cmd")
    manifest = tmp_path / "run.battest.yaml"
    manifest.write_text(
        "description: copy\nscript: run.cmd\ncopy: [missing.txt]\nexpect:\n  exit_code: 0\n",
        encoding="utf-8",
    )
    with pytest.raises(SchemaError, match="copy path"):
        load_cases_from_path(manifest)


def test_output_matcher_roundtrip() -> None:
    matcher = OutputMatcher(contains="hello world", newline="auto")
    restored = OutputMatcher.model_validate(matcher.model_dump())
    assert restored.contains == "hello world"


def test_case_document_dump_roundtrip() -> None:
    document = CaseDocument.model_validate(
        {"description": "round", "expect": {"exit_code": 7, "stdout": {"empty": True}}}
    )
    restored = CaseDocument.model_validate(document.model_dump())
    assert restored.expect.exit_code == 7
    assert restored.expect.stdout is not None
    assert restored.expect.stdout.empty is True
