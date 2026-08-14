"""Load and validate battest YAML documents."""

from __future__ import annotations

from importlib import resources
import json
from pathlib import Path
from typing import Any, Mapping

from pydantic import ValidationError
import yaml

from battest.logging_config import get_logger
from battest.models import (
    Case,
    CaseDocument,
    Expect,
    MockSpec,
    ParamOverlay,
    merge_expect,
    merge_mocks,
)
from battest.spec import load_catalog

LOGGER = get_logger("schema")


class SchemaError(ValueError):
    """Raised when a fixture document is missing, malformed, or incomplete."""


def schema_payload() -> dict[str, Any]:
    """Return the bundled JSON Schema object."""
    traversable = resources.files("battest") / "data" / "battest-expect.schema.json"
    with resources.as_file(traversable) as path:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise SchemaError("bundled JSON Schema is not an object")
    return loaded


def load_yaml_mapping(path: Path) -> dict[str, Any]:
    """Read a YAML file and require a mapping at the root."""
    LOGGER.info("loading yaml %s", path)
    if not path.is_file():
        raise SchemaError(f"fixture file not found: {path}")
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise SchemaError(f"invalid YAML in {path}: {exc}") from exc
    if not isinstance(loaded, dict):
        raise SchemaError(f"fixture root must be a mapping: {path}")
    return {str(key): value for key, value in loaded.items()}


def parse_document(payload: Mapping[str, Any], source: Path) -> CaseDocument:
    """Validate a mapping as a CaseDocument."""
    LOGGER.debug(
        "validating document source=%s keys=%s", source, sorted(payload.keys())
    )
    try:
        document = CaseDocument.model_validate(dict(payload))
    except ValidationError as exc:
        raise SchemaError(f"invalid fixture {source}: {exc}") from exc
    return document


def _resolve_optional(base_dir: Path, value: str | None) -> Path | None:
    if value is None:
        return None
    path = (
        (base_dir / value).resolve() if not Path(value).is_absolute() else Path(value)
    )
    return path


def _require_script(base_dir: Path, document: CaseDocument, source: Path) -> Path:
    if document.script:
        script_path = _resolve_optional(base_dir, document.script)
        if script_path is None or not script_path.is_file():
            raise SchemaError(f"script not found for {source}: {document.script}")
        return script_path
    sibling = base_dir / "input.cmd"
    if sibling.is_file():
        return sibling.resolve()
    raise SchemaError(f"{source} must set script or sit beside input.cmd")


def _collect_warnings(document: CaseDocument, script_path: Path) -> list[str]:
    catalog = load_catalog()
    warnings: list[str] = []
    command_names = set(document.mocks.keys())
    command_names.update(document.allow)
    for name in sorted(command_names):
        lowered = name.lower()
        if catalog.is_deprecated(lowered):
            message = f"command '{name}' is deprecated in batch-spec"
            LOGGER.warning("%s", message)
            warnings.append(message)
        if catalog.is_removed(lowered):
            message = f"command '{name}' is removed in batch-spec"
            LOGGER.warning("%s", message)
            warnings.append(message)
        if catalog.is_internal(lowered):
            message = (
                f"command '{name}' is a cmd.exe internal and cannot be PATH-mocked"
            )
            LOGGER.warning("%s", message)
            warnings.append(message)
    try:
        script_text = script_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        LOGGER.error("failed to read script %s: %s", script_path, exc)
        script_text = ""
    for token in catalog.invalid_tilde_forms(script_text):
        message = f"invalid percent-tilde form {token} in {script_path.name}"
        LOGGER.warning("%s", message)
        warnings.append(message)
    arg_blob = " ".join(document.args)
    for token in catalog.invalid_tilde_forms(arg_blob):
        message = f"invalid percent-tilde form {token} in args"
        LOGGER.warning("%s", message)
        warnings.append(message)
    return warnings


def _copy_paths(base_dir: Path, names: list[str], source: Path) -> list[Path]:
    resolved: list[Path] = []
    resolved_base = base_dir.resolve()
    for name in names:
        path = _resolve_optional(base_dir, name)
        if path is None or not path.exists():
            raise SchemaError(f"copy path not found for {source}: {name}")
        try:
            path.resolve().relative_to(resolved_base)
        except ValueError as exc:
            raise SchemaError(
                f"copy path escapes fixture directory for {source}: {name}"
            ) from exc
        resolved.append(path)
    return resolved


def _case_from_document(
    document: CaseDocument,
    source: Path,
    case_id: str,
    args: list[str],
    stdin: str,
    env: dict[str, str],
    mocks: dict[str, MockSpec],
    expect: Expect,
    timeout_seconds: float | None,
    allow: list[str],
) -> Case:
    base_dir = source.parent
    script_path = _require_script(base_dir, document, source)
    setup_path = _resolve_optional(base_dir, document.setup)
    teardown_path = _resolve_optional(base_dir, document.teardown)
    if document.setup and (setup_path is None or not setup_path.is_file()):
        raise SchemaError(f"setup script not found for {source}: {document.setup}")
    if document.teardown and (teardown_path is None or not teardown_path.is_file()):
        raise SchemaError(
            f"teardown script not found for {source}: {document.teardown}"
        )
    warnings = _collect_warnings(document, script_path)
    LOGGER.info(
        "resolved case id=%s script=%s args=%s timeout=%s mocks=%s",
        case_id,
        script_path,
        args,
        timeout_seconds,
        sorted(mocks.keys()),
    )
    return Case(
        case_id=case_id,
        description=document.description,
        source_path=source,
        script_path=script_path,
        args=list(args),
        stdin=stdin,
        env=dict(env),
        timeout_seconds=timeout_seconds,
        setup_path=setup_path,
        teardown_path=teardown_path,
        mocks=mocks,
        expect=expect,
        allow=list(allow),
        copy_paths=_copy_paths(base_dir, document.copy_files, source),
        warnings=warnings,
    )


def _apply_overlay(document: CaseDocument, overlay: ParamOverlay) -> tuple[
    list[str],
    str,
    dict[str, str],
    dict[str, MockSpec],
    Expect,
    float | None,
    list[str],
]:
    args = list(overlay.args) if overlay.args is not None else list(document.args)
    stdin = document.stdin if overlay.stdin is None else overlay.stdin
    env = dict(document.env)
    if overlay.env:
        env.update(overlay.env)
    mocks = merge_mocks(document.mocks, overlay.mocks)
    expect = merge_expect(document.expect, overlay.expect)
    timeout_seconds = (
        document.timeout_seconds
        if overlay.timeout_seconds is None
        else overlay.timeout_seconds
    )
    allow = list(document.allow)
    if overlay.allow:
        allow.extend(overlay.allow)
    return args, stdin, env, mocks, expect, timeout_seconds, allow


def fixture_stem(source: Path) -> str:
    """Return the default case id stem for a fixture path."""
    if source.name.endswith(".battest.yaml"):
        return source.name[: -len(".battest.yaml")]
    if source.name == "expect.yaml":
        return source.parent.name
    return source.stem


def relative_case_id(source: Path, root: Path) -> str:
    """Return a discovery-root-relative case id for a fixture file."""
    stem = fixture_stem(source)
    try:
        relative = source.parent.resolve().relative_to(root.resolve())
    except ValueError:
        LOGGER.warning(
            "fixture %s is outside discovery root %s; using stem id", source, root
        )
        return stem
    if source.name == "expect.yaml":
        if not relative.parts:
            return stem
        return relative.as_posix()
    if relative.parts:
        return f"{relative.as_posix()}/{stem}"
    return stem


def expand_cases(
    document: CaseDocument, source: Path, *, base_case_id: str | None = None
) -> list[Case]:
    """Expand a document into one case, or base plus each params entry."""
    stem = fixture_stem(source) if base_case_id is None else base_case_id
    cases: list[Case] = []
    base = _case_from_document(
        document,
        source,
        stem,
        list(document.args),
        document.stdin,
        dict(document.env),
        dict(document.mocks),
        document.expect,
        document.timeout_seconds,
        list(document.allow),
    )
    cases.append(base)
    for overlay in document.params:
        (
            args,
            stdin,
            env,
            mocks,
            expect,
            timeout_seconds,
            allow,
        ) = _apply_overlay(document, overlay)
        case_id = f"{stem}[{overlay.id}]"
        cases.append(
            _case_from_document(
                document,
                source,
                case_id,
                args,
                stdin,
                env,
                mocks,
                expect,
                timeout_seconds,
                allow,
            )
        )
    LOGGER.info("expanded %s into %s case(s)", source, len(cases))
    return cases


def load_cases_from_path(path: Path, *, base_case_id: str | None = None) -> list[Case]:
    """Load and expand cases from a YAML fixture file."""
    payload = load_yaml_mapping(path)
    document = parse_document(payload, path)
    return expand_cases(document, path, base_case_id=base_case_id)
