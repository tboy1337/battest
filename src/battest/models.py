"""Pydantic models for battest fixture documents and runtime cases."""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class NewlineMode(str, Enum):
    """How stdout/stderr newline bytes are compared."""

    AUTO = "auto"
    CRLF = "crlf"
    LF = "lf"


class Outcome(str, Enum):
    """Terminal status of a single case run."""

    PASS = "PASS"
    FAIL = "FAIL"
    ERROR = "ERROR"
    TIMEOUT = "TIMEOUT"


class OutputMatcher(BaseModel):
    """Matchers applied to captured stdout or stderr."""

    model_config = ConfigDict(extra="forbid")

    equals: str | None = None
    equals_file: str | None = None
    contains: str | None = None
    regex: str | None = None
    empty: bool | None = None
    newline: NewlineMode = NewlineMode.AUTO

    def has_constraint(self) -> bool:
        """Return True when at least one comparison is configured."""
        return any(
            value is not None
            for value in (
                self.equals,
                self.equals_file,
                self.contains,
                self.regex,
                self.empty,
            )
        )


class FileMatcher(BaseModel):
    """Matchers applied to a path relative to the isolated working directory."""

    model_config = ConfigDict(extra="forbid")

    path: str
    exists: bool | None = None
    not_exists: bool | None = None
    contains: str | None = None
    equals: str | None = None
    equals_file: str | None = None

    @model_validator(mode="after")
    def reject_conflicting_existence(self) -> FileMatcher:
        """Reject exists and not_exists both set to True."""
        if self.exists is True and self.not_exists is True:
            raise ValueError("file matcher cannot set both exists and not_exists")
        return self


class CallExpectation(BaseModel):
    """Assertion against recorded mock argv lines."""

    model_config = ConfigDict(extra="forbid")

    args_contains: str | None = None
    not_called: bool | None = None


class MockSpec(BaseModel):
    """PATH stub for an external command."""

    model_config = ConfigDict(extra="forbid")

    exit_code: int = Field(default=0, ge=0, le=255)
    stdout: str = ""
    stderr: str = ""
    record_calls: bool = True
    expect_calls: list[CallExpectation] = Field(default_factory=list)


class EnvExpect(BaseModel):
    """Expected process environment after the script returns."""

    model_config = ConfigDict(extra="forbid")

    values: dict[str, str] = Field(default_factory=dict)
    unset: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def coerce_mapping(cls, data: object) -> object:
        """Accept a plain NAME=value mapping or an explicit values/unset object."""
        if not isinstance(data, dict):
            return data
        keys = set(data.keys())
        if keys <= {"values", "unset"}:
            return data
        unset_raw = data.get("unset", [])
        values_raw = data.get("values")
        extras = {
            key: value for key, value in data.items() if key not in {"values", "unset"}
        }
        merged: dict[str, str] = {}
        if isinstance(values_raw, dict):
            merged.update({str(key): str(value) for key, value in values_raw.items()})
        merged.update({str(key): str(value) for key, value in extras.items()})
        return {"values": merged, "unset": unset_raw}


class Expect(BaseModel):
    """Assertions evaluated against a completed run."""

    model_config = ConfigDict(extra="forbid")

    exit_code: int | None = None
    stdout: OutputMatcher | None = None
    stderr: OutputMatcher | None = None
    env: EnvExpect | None = None
    files: list[FileMatcher] = Field(default_factory=list)


class ParamOverlay(BaseModel):
    """Optional overlay that expands one document into a matrix row."""

    model_config = ConfigDict(extra="forbid")

    id: str
    args: list[str] | None = None
    stdin: str | None = None
    env: dict[str, str] | None = None
    mocks: dict[str, MockSpec] | None = None
    expect: Expect | None = None
    timeout_seconds: float | None = Field(default=None, gt=0)
    allow: list[str] | None = None


class CaseDocument(BaseModel):
    """Raw YAML document before path resolution and param expansion."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    description: str
    script: str | None = None
    args: list[str] = Field(default_factory=list)
    stdin: str = ""
    env: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: float | None = Field(default=None, gt=0)
    setup: str | None = None
    teardown: str | None = None
    mocks: dict[str, MockSpec] = Field(default_factory=dict)
    expect: Expect
    params: list[ParamOverlay] = Field(default_factory=list)
    allow: list[str] = Field(default_factory=list)
    copy_files: list[str] = Field(default_factory=list, alias="copy")

    @field_validator("description")
    @classmethod
    def description_not_empty(cls, value: str) -> str:
        """Require a non-empty description."""
        stripped = value.strip()
        if not stripped:
            raise ValueError("description must not be empty")
        return stripped


class Case(BaseModel):
    """Fully resolved runnable test case."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    case_id: str
    description: str
    source_path: Path
    script_path: Path
    args: list[str] = Field(default_factory=list)
    stdin: str = ""
    env: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: float | None = Field(default=None, gt=0)
    setup_path: Path | None = None
    teardown_path: Path | None = None
    mocks: dict[str, MockSpec] = Field(default_factory=dict)
    expect: Expect
    allow: list[str] = Field(default_factory=list)
    copy_paths: list[Path] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class AssertionFailure(BaseModel):
    """One failed comparison with a human-readable diff."""

    model_config = ConfigDict(extra="forbid")

    kind: str
    message: str
    expected: str | None = None
    actual: str | None = None
    diff: str | None = None


class RunResult(BaseModel):
    """Outcome of executing and asserting one case."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    description: str
    outcome: Outcome
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    env: dict[str, str] = Field(default_factory=dict)
    mock_calls: dict[str, list[str]] = Field(default_factory=dict)
    failures: list[AssertionFailure] = Field(default_factory=list)
    duration_seconds: float = 0.0
    error_message: str | None = None
    warnings: list[str] = Field(default_factory=list)


class EngineConfig(BaseModel):
    """Runtime options for the execution engine."""

    model_config = ConfigDict(extra="forbid")

    safe_defaults: bool = False
    max_diff: int = 2000
    jobs: int = Field(default=1, ge=1)
    default_timeout_seconds: float = Field(default=30.0, gt=0)


def merge_expect(base: Expect, overlay: Expect | None) -> Expect:
    """Replace provided overlay fields while keeping unspecified base fields."""
    if overlay is None:
        return base.model_copy(deep=True)
    payload: dict[str, Any] = base.model_dump()
    dumped = overlay.model_dump(exclude_unset=True)
    for key, value in dumped.items():
        if value is not None:
            payload[key] = value
    return Expect.model_validate(payload)


def merge_mocks(
    base: dict[str, MockSpec],
    overlay: dict[str, MockSpec] | None,
) -> dict[str, MockSpec]:
    """Return base mocks with overlay keys replacing matching command names."""
    merged = dict(base)
    if overlay:
        merged.update(overlay)
    return merged
