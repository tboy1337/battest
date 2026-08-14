"""Tests for YAML schema loading and param expansion."""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError
import pytest

from battest.models import (
    CaseDocument,
    EngineConfig,
    Expect,
    MockSpec,
    OutputMatcher,
    merge_expect,
    merge_mocks,
)
from battest.schema import (
    SchemaError,
    fixture_stem,
    load_cases_from_path,
    parse_document,
    relative_case_id,
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
    exit_schema = payload["$defs"]["mockSpec"]["properties"]["exit_code"]
    assert exit_schema["minimum"] == 0
    assert exit_schema["maximum"] == 255


def test_schema_payload_rejects_non_object(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("battest.schema.json.loads", lambda _text: ["not-an-object"])
    with pytest.raises(SchemaError, match="not an object"):
        schema_payload()


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
    manifest.write_text(
        "description: teardown\nscript: run.cmd\nteardown: missing.cmd\n"
        "expect:\n  exit_code: 0\n",
        encoding="utf-8",
    )
    with pytest.raises(SchemaError, match="teardown script"):
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


def test_params_overlay_timeout(tmp_path: Path) -> None:
    _write_script(tmp_path, "run.cmd")
    manifest = tmp_path / "run.battest.yaml"
    manifest.write_text(
        "\n".join(
            [
                "description: matrix",
                "script: run.cmd",
                "expect:",
                "  exit_code: 0",
                "params:",
                "  - id: slow",
                "    timeout_seconds: 5",
            ]
        ),
        encoding="utf-8",
    )
    cases = load_cases_from_path(manifest)
    assert cases[0].timeout_seconds is None
    assert cases[1].timeout_seconds == 5.0


def test_relative_case_id_outside_root(tmp_path: Path) -> None:
    other = tmp_path / "other"
    other.mkdir()
    fixture = other / "tool.battest.yaml"
    fixture.write_text("x", encoding="utf-8")
    assert relative_case_id(fixture, tmp_path / "root") == "tool"


def test_relative_case_id_nested_expect_yaml(tmp_path: Path) -> None:
    nested = tmp_path / "suite" / "alpha"
    nested.mkdir(parents=True)
    fixture = nested / "expect.yaml"
    fixture.write_text("x", encoding="utf-8")
    assert relative_case_id(fixture, tmp_path) == "suite/alpha"


def test_relative_case_id_expect_yaml_at_root(tmp_path: Path) -> None:
    fixture = tmp_path / "expect.yaml"
    fixture.write_text("x", encoding="utf-8")
    assert relative_case_id(fixture, tmp_path) == tmp_path.name


def test_fixture_stem_plain_yaml() -> None:
    assert fixture_stem(Path("foo.yaml")) == "foo"
    assert fixture_stem(Path("hello.battest.yaml")) == "hello"


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


def test_removed_command_warning(tmp_path: Path) -> None:
    _write_script(tmp_path, "run.cmd")
    manifest = tmp_path / "run.battest.yaml"
    manifest.write_text(
        "\n".join(
            [
                "description: removed mock",
                "script: run.cmd",
                "mocks:",
                "  edlin:",
                "    exit_code: 0",
                "expect:",
                "  exit_code: 0",
            ]
        ),
        encoding="utf-8",
    )
    cases = load_cases_from_path(manifest)
    assert any("removed" in item for item in cases[0].warnings)


def test_invalid_tilde_in_script_and_args(tmp_path: Path) -> None:
    (tmp_path / "run.cmd").write_text("@echo off\r\necho %~q1\r\n", encoding="utf-8")
    manifest = tmp_path / "run.battest.yaml"
    manifest.write_text(
        "\n".join(
            [
                "description: tilde",
                "script: run.cmd",
                "args: ['%~*']",
                "expect:",
                "  exit_code: 0",
            ]
        ),
        encoding="utf-8",
    )
    cases = load_cases_from_path(manifest)
    joined = " ".join(cases[0].warnings)
    assert "%~q1" in joined
    assert "%~*" in joined


def test_script_read_oserror_skips_tilde_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_script(tmp_path, "run.cmd")
    manifest = tmp_path / "run.battest.yaml"
    manifest.write_text(
        "description: locked\nscript: run.cmd\nexpect:\n  exit_code: 0\n",
        encoding="utf-8",
    )
    original = Path.read_text

    def maybe_boom(self: Path, *args: object, **kwargs: object) -> str:
        if self.suffix.lower() == ".cmd":
            raise OSError("locked")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", maybe_boom)
    cases = load_cases_from_path(manifest)
    assert cases[0].script_path.name == "run.cmd"


def test_params_overlay_env_and_allow(tmp_path: Path) -> None:
    _write_script(tmp_path, "run.cmd")
    manifest = tmp_path / "run.battest.yaml"
    manifest.write_text(
        "\n".join(
            [
                "description: matrix",
                "script: run.cmd",
                "env:",
                "  BASE: '1'",
                "allow:",
                "  - format",
                "expect:",
                "  exit_code: 0",
                "params:",
                "  - id: extra",
                "    env:",
                "      EXTRA: '2'",
                "    allow:",
                "      - reg",
                "    stdin: overlay-in",
            ]
        ),
        encoding="utf-8",
    )
    cases = load_cases_from_path(manifest)
    overlay = cases[1]
    assert overlay.env["BASE"] == "1"
    assert overlay.env["EXTRA"] == "2"
    assert overlay.allow == ["format", "reg"]
    assert overlay.stdin == "overlay-in"


def test_script_file_missing(tmp_path: Path) -> None:
    manifest = tmp_path / "run.battest.yaml"
    manifest.write_text(
        "description: missing script\nscript: nope.cmd\nexpect:\n  exit_code: 0\n",
        encoding="utf-8",
    )
    with pytest.raises(SchemaError, match="script not found"):
        load_cases_from_path(manifest)


def test_internal_mock_is_schema_error(tmp_path: Path) -> None:
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
    with pytest.raises(SchemaError, match="internal"):
        load_cases_from_path(manifest)


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


def test_env_expect_values_object() -> None:
    document = parse_document(
        {
            "description": "env",
            "script": "x.cmd",
            "expect": {"env": {"values": {"FOO": "bar"}, "unset": ["BAZ"]}},
        },
        Path("doc.yaml"),
    )
    assert document.expect.env is not None
    assert document.expect.env.values["FOO"] == "bar"
    assert document.expect.env.unset == ["BAZ"]


def test_env_expect_values_and_extras() -> None:
    document = parse_document(
        {
            "description": "env",
            "script": "x.cmd",
            "expect": {"env": {"values": {"FOO": "bar"}, "BAZ": "qux"}},
        },
        Path("doc.yaml"),
    )
    assert document.expect.env is not None
    assert document.expect.env.values["FOO"] == "bar"
    assert document.expect.env.values["BAZ"] == "qux"


def test_env_expect_rejects_non_mapping() -> None:
    with pytest.raises(SchemaError):
        parse_document(
            {"description": "env", "expect": {"env": ["FOO"]}},
            Path("doc.yaml"),
        )


def test_merge_expect_and_mocks_none_overlay() -> None:
    base = Expect(exit_code=0)
    assert merge_expect(base, None).exit_code == 0
    assert merge_mocks({"net": MockSpec(exit_code=1)}, None) == {
        "net": MockSpec(exit_code=1)
    }
    merged = merge_mocks({"net": MockSpec(exit_code=1)}, {"net": MockSpec(exit_code=2)})
    assert merged["net"].exit_code == 2
    mixed = merge_mocks(
        {"Format": MockSpec(exit_code=1)}, {"format": MockSpec(exit_code=3)}
    )
    assert mixed == {"format": MockSpec(exit_code=3)}
    skipped = merge_expect(Expect(exit_code=1), Expect(exit_code=None))
    assert skipped.exit_code == 1


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


def test_omitted_timeout_seconds_is_none() -> None:
    document = parse_document(
        {"description": "t", "expect": {"exit_code": 0}},
        Path("doc.yaml"),
    )
    assert document.timeout_seconds is None


def test_explicit_timeout_seconds_is_kept() -> None:
    document = parse_document(
        {"description": "t", "timeout_seconds": 12.5, "expect": {"exit_code": 0}},
        Path("doc.yaml"),
    )
    assert document.timeout_seconds == 12.5


def test_loaded_case_omits_timeout_when_yaml_omits(tmp_path: Path) -> None:
    _write_script(tmp_path, "run.cmd")
    manifest = tmp_path / "run.battest.yaml"
    manifest.write_text(
        "description: tool\nscript: run.cmd\nexpect:\n  exit_code: 0\n",
        encoding="utf-8",
    )
    cases = load_cases_from_path(manifest)
    assert cases[0].timeout_seconds is None


def test_param_overlay_timeout_must_be_positive() -> None:
    with pytest.raises(SchemaError):
        parse_document(
            {
                "description": "t",
                "expect": {"exit_code": 0},
                "params": [{"id": "slow", "timeout_seconds": 0}],
            },
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


def test_copy_path_is_resolved(tmp_path: Path) -> None:
    _write_script(tmp_path, "run.cmd")
    nested = tmp_path / "fixtures"
    nested.mkdir()
    seed = nested / "seed.txt"
    seed.write_text("ok", encoding="utf-8")
    manifest = tmp_path / "run.battest.yaml"
    manifest.write_text(
        "description: copy\nscript: run.cmd\ncopy: [fixtures/seed.txt]\n"
        "expect:\n  exit_code: 0\n",
        encoding="utf-8",
    )
    cases = load_cases_from_path(manifest)
    assert cases[0].copy_paths == [seed.resolve()]


def test_copy_path_must_stay_under_fixture_dir(tmp_path: Path) -> None:
    _write_script(tmp_path, "run.cmd")
    outside = tmp_path.parent / "battest-outside.txt"
    outside.write_text("nope", encoding="utf-8")
    manifest = tmp_path / "run.battest.yaml"
    manifest.write_text(
        "description: copy\nscript: run.cmd\ncopy: [../battest-outside.txt]\n"
        "expect:\n  exit_code: 0\n",
        encoding="utf-8",
    )
    with pytest.raises(SchemaError, match="escap"):
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


def test_mock_exit_code_must_be_byte_range() -> None:
    with pytest.raises(SchemaError):
        parse_document(
            {
                "description": "mock",
                "expect": {"exit_code": 0},
                "mocks": {"ipconfig": {"exit_code": 256}},
            },
            Path("doc.yaml"),
        )
    with pytest.raises(SchemaError):
        parse_document(
            {
                "description": "mock",
                "expect": {"exit_code": 0},
                "mocks": {"ipconfig": {"exit_code": -1}},
            },
            Path("doc.yaml"),
        )


def test_mock_exit_code_accepts_byte_boundaries() -> None:
    document = parse_document(
        {
            "description": "mock",
            "expect": {"exit_code": 0},
            "mocks": {"ipconfig": {"exit_code": 255}, "net": {"exit_code": 0}},
        },
        Path("doc.yaml"),
    )
    assert document.mocks["ipconfig"].exit_code == 255
    assert document.mocks["net"].exit_code == 0


def test_duplicate_param_ids_are_schema_error(tmp_path: Path) -> None:
    _write_script(tmp_path, "run.cmd")
    manifest = tmp_path / "run.battest.yaml"
    manifest.write_text(
        "\n".join(
            [
                "description: matrix",
                "script: run.cmd",
                "expect:",
                "  exit_code: 0",
                "params:",
                "  - id: other",
                "  - id: other",
            ]
        ),
        encoding="utf-8",
    )
    with pytest.raises(SchemaError, match="duplicate case id"):
        load_cases_from_path(manifest)


def test_empty_param_id_is_rejected() -> None:
    with pytest.raises(SchemaError):
        parse_document(
            {
                "description": "t",
                "expect": {"exit_code": 0},
                "params": [{"id": "  "}],
            },
            Path("doc.yaml"),
        )


def test_empty_file_matcher_path_is_rejected() -> None:
    with pytest.raises(SchemaError):
        parse_document(
            {
                "description": "t",
                "expect": {"files": [{"path": ""}]},
            },
            Path("doc.yaml"),
        )


def test_schema_payload_call_expectation_requires_constraint() -> None:
    payload = schema_payload()
    call_schema = payload["$defs"]["callExpectation"]
    assert "anyOf" in call_schema
    file_schema = payload["$defs"]["fileMatcher"]
    assert "not" in file_schema


def test_engine_config_max_diff_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        EngineConfig(max_diff=0)
