"""Pydantic models for battest fixture documents and runtime cases."""

from __future__ import annotations

from enum import Enum
import math
from pathlib import Path
import re
from typing import Annotated, Any

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from battest.constants import (
    COMMAND_NAME_PATTERN,
    MAX_JOBS,
    MAX_REGEX_PATTERN_LENGTH,
    WINDOWS_RESERVED_DEVICE_NAMES,
)
from battest.logging_config import get_logger

LOGGER = get_logger("models")
_COMMAND_EXTENSIONS = (".exe", ".cmd", ".bat", ".com")
_COMMAND_NAME_RE = re.compile(COMMAND_NAME_PATTERN)
_NESTED_QUANTIFIER_RE = re.compile(r"\((?:\?[P:=!<][^)]*)?[^()]*[+*{][^()]*\)[+*?{]")


def require_finite_positive(value: float) -> float:
    """Reject NaN and inf so timeouts cannot hang or crash the runner."""
    if not math.isfinite(value) or value <= 0:
        raise ValueError("must be a finite number greater than 0")
    return value


FinitePositiveFloat = Annotated[float, AfterValidator(require_finite_positive)]


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
    equals_file: str | None = Field(default=None, min_length=1)
    contains: str | None = Field(default=None, min_length=1)
    regex: str | None = None
    empty: bool | None = None
    newline: NewlineMode = NewlineMode.AUTO

    @field_validator("regex")
    @classmethod
    def regex_must_compile(cls, value: str | None) -> str | None:
        """Reject patterns that cannot be compiled, are too long, or nested-quantify."""
        if value is None:
            return None
        if len(value) > MAX_REGEX_PATTERN_LENGTH:
            LOGGER.warning(
                "rejecting regex longer than %s characters", MAX_REGEX_PATTERN_LENGTH
            )
            raise ValueError(
                f"regex pattern exceeds {MAX_REGEX_PATTERN_LENGTH} characters"
            )
        if _NESTED_QUANTIFIER_RE.search(value):
            LOGGER.warning("rejecting regex with nested quantifiers")
            raise ValueError(
                "regex pattern has nested quantifiers that can hang the runner"
            )
        try:
            re.compile(value)
        except re.error as exc:
            raise ValueError(f"invalid regex: {exc}") from exc
        return value

    def has_constraint(self) -> bool:
        """Return True when at least one comparison is configured."""
        if self.newline != NewlineMode.AUTO:
            return True
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

    path: str = Field(min_length=1)
    exists: bool | None = None
    not_exists: bool | None = None
    contains: str | None = Field(default=None, min_length=1)
    equals: str | None = None
    equals_file: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def reject_conflicting_existence(self) -> FileMatcher:
        """Reject exists and not_exists both set to True."""
        if self.not_exists is False:
            raise ValueError("not_exists must be true when set")
        if self.exists is True and self.not_exists is True:
            raise ValueError("file matcher cannot set both exists and not_exists")
        missing = self.exists is False or self.not_exists is True
        has_content = any(
            value is not None
            for value in (self.contains, self.equals, self.equals_file)
        )
        if missing and has_content:
            raise ValueError(
                "file matcher cannot combine absence with contains, equals, "
                "or equals_file"
            )
        if (
            self.exists is None
            and self.not_exists is None
            and self.contains is None
            and self.equals is None
            and self.equals_file is None
        ):
            raise ValueError(
                "file matcher must set exists, not_exists, contains, equals, "
                "or equals_file"
            )
        return self


class CallExpectation(BaseModel):
    """Assertion against recorded mock argv lines."""

    model_config = ConfigDict(extra="forbid")

    args_contains: str | None = Field(default=None, min_length=1)
    not_called: bool | None = None

    @model_validator(mode="after")
    def require_constraint(self) -> CallExpectation:
        """Require args_contains or not_called so empty expectations cannot pass."""
        if self.not_called is False:
            raise ValueError("not_called must be true when set")
        if self.not_called is True and self.args_contains is not None:
            raise ValueError(
                "call expectation cannot set both args_contains and not_called"
            )
        if self.args_contains is None and self.not_called is not True:
            raise ValueError("call expectation must set args_contains or not_called")
        return self


class MockSpec(BaseModel):
    """PATH stub for an external command."""

    model_config = ConfigDict(extra="forbid")

    exit_code: int = Field(default=0, ge=0, le=255)
    stdout: str = ""
    stderr: str = ""
    record_calls: bool = True
    expect_calls: list[CallExpectation] = Field(default_factory=list)

    @model_validator(mode="after")
    def expect_calls_require_recording(self) -> MockSpec:
        """Reject expect_calls when call logs are not recorded."""
        if self.expect_calls and not self.record_calls:
            raise ValueError("expect_calls requires record_calls to be true")
        return self


def _require_string_mapping(raw: object, label: str) -> dict[str, str]:
    """Reject non-string environment values so YAML numbers cannot silently pass."""
    if not isinstance(raw, dict):
        raise ValueError(f"{label} must be a mapping of strings")
    mapped: dict[str, str] = {}
    for key, value in raw.items():
        if not isinstance(value, str):
            raise ValueError(f"{label} {key!r} must be a string")
        mapped[str(key)] = value
    return mapped


def _env_mapping_must_be_strings(value: object) -> object:
    """Reject non-string values in a fixture env mapping."""
    if value is None or not isinstance(value, dict):
        return value
    return _require_string_mapping(value, "environment value")


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
        if values_raw is not None:
            merged.update(_require_string_mapping(values_raw, "environment value"))
        merged.update(_require_string_mapping(extras, "environment value"))
        return {"values": merged, "unset": unset_raw}

    @field_validator("values", mode="before")
    @classmethod
    def values_must_be_strings(cls, value: object) -> object:
        """Reject non-string entries in an explicit values mapping."""
        if value is None or not isinstance(value, dict):
            return value
        return _require_string_mapping(value, "environment value")


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
    timeout_seconds: FinitePositiveFloat | None = None
    allow: list[str] | None = None

    @field_validator("allow")
    @classmethod
    def overlay_allow_names_must_be_safe(
        cls, value: list[str] | None
    ) -> list[str] | None:
        """Normalize overlay allow entries to safe command stems."""
        if value is None:
            return None
        return [normalize_command_name(item) for item in value]

    @field_validator("id")
    @classmethod
    def id_not_empty(cls, value: str) -> str:
        """Require a non-empty overlay id."""
        stripped = value.strip()
        if not stripped:
            raise ValueError("param id must not be empty")
        return stripped

    @field_validator("env", mode="before")
    @classmethod
    def overlay_env_values_must_be_strings(cls, value: object) -> object:
        """Reject non-string overlay environment values."""
        return _env_mapping_must_be_strings(value)

    @field_validator("mocks")
    @classmethod
    def lowercase_overlay_mock_keys(
        cls, value: dict[str, MockSpec] | None
    ) -> dict[str, MockSpec] | None:
        """Normalize overlay mock command names to lowercase."""
        if value is None:
            return None
        return lowercase_mock_mapping(value)


class CaseDocument(BaseModel):
    """Raw YAML document before path resolution and param expansion."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    description: str
    script: str | None = None
    args: list[str] = Field(default_factory=list)
    stdin: str = ""
    env: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: FinitePositiveFloat | None = None
    setup: str | None = None
    teardown: str | None = None
    mocks: dict[str, MockSpec] = Field(default_factory=dict)
    expect: Expect
    params: list[ParamOverlay] = Field(default_factory=list)
    allow: list[str] = Field(default_factory=list)
    copy_files: list[str] = Field(default_factory=list, alias="copy")

    @field_validator("allow")
    @classmethod
    def document_allow_names_must_be_safe(cls, value: list[str]) -> list[str]:
        """Normalize allow entries to safe command stems."""
        return [normalize_command_name(item) for item in value]

    @field_validator("description")
    @classmethod
    def description_not_empty(cls, value: str) -> str:
        """Require a non-empty description."""
        stripped = value.strip()
        if not stripped:
            raise ValueError("description must not be empty")
        return stripped

    @field_validator("env", mode="before")
    @classmethod
    def document_env_values_must_be_strings(cls, value: object) -> object:
        """Reject non-string case environment values."""
        return _env_mapping_must_be_strings(value)

    @field_validator("mocks")
    @classmethod
    def lowercase_mock_keys(cls, value: dict[str, MockSpec]) -> dict[str, MockSpec]:
        """Normalize mock command names to lowercase."""
        return lowercase_mock_mapping(value)


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
    timeout_seconds: FinitePositiveFloat | None = None
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
    max_diff: int = Field(default=2000, ge=1)
    jobs: int = Field(default=1, ge=1, le=MAX_JOBS)
    default_timeout_seconds: FinitePositiveFloat = 30.0


def normalize_command_name(name: str) -> str:
    """Return a lowercase executable stem, rejecting paths and reserved devices."""
    stripped = name.strip()
    lowered = stripped.lower()
    for suffix in _COMMAND_EXTENSIONS:
        if lowered.endswith(suffix) and len(lowered) > len(suffix):
            lowered = lowered[: -len(suffix)]
            break
    if not _COMMAND_NAME_RE.fullmatch(lowered):
        LOGGER.warning("rejecting invalid command name %r", name)
        raise ValueError(
            f"invalid command name {name!r}; use a simple executable stem "
            "(letters, digits, dot, underscore, hyphen; no path separators)"
        )
    device = lowered.split(".", 1)[0]
    if device in WINDOWS_RESERVED_DEVICE_NAMES:
        LOGGER.warning("rejecting reserved Windows device name %r", name)
        raise ValueError(f"command name {name!r} is a reserved Windows device name")
    LOGGER.debug("normalized command name %r -> %s", name, lowered)
    return lowered


def lowercase_mock_mapping(value: dict[str, MockSpec]) -> dict[str, MockSpec]:
    """Normalize mock command names and reject case-insensitive duplicates."""
    lowered: dict[str, MockSpec] = {}
    for name, spec in value.items():
        key = normalize_command_name(name)
        if key in lowered:
            raise ValueError(f"duplicate mock command name {name!r} (case-insensitive)")
        lowered[key] = spec
    return lowered


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
    merged = {name.lower(): spec for name, spec in base.items()}
    if overlay:
        for name, spec in overlay.items():
            merged[name.lower()] = spec
    return merged
