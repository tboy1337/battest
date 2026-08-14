"""Public Python API for loading and running battest cases."""

from __future__ import annotations

from pathlib import Path

from battest.constants import DEFAULT_MAX_DIFF, DEFAULT_TIMEOUT_SECONDS
from battest.discover import discover_cases
from battest.engine import execute_case, execute_cases
from battest.models import Case, EngineConfig, RunResult
from battest.schema import load_cases_from_path


def load_case(path: str | Path) -> list[Case]:
    """Load and expand cases from a fixture file or discovery root."""
    resolved = Path(path)
    if resolved.is_file():
        return load_cases_from_path(resolved)
    return discover_cases(resolved)


def run_case(
    case: Case,
    *,
    safe_defaults: bool = False,
    max_diff: int = DEFAULT_MAX_DIFF,
    timeout_seconds: float | None = None,
) -> RunResult:
    """Execute a single resolved case."""
    config = EngineConfig(
        safe_defaults=safe_defaults,
        max_diff=max_diff,
        jobs=1,
        default_timeout_seconds=(
            timeout_seconds if timeout_seconds is not None else DEFAULT_TIMEOUT_SECONDS
        ),
    )
    return execute_case(case, config)


def run_cases(
    cases: list[Case],
    *,
    safe_defaults: bool = False,
    max_diff: int = DEFAULT_MAX_DIFF,
    jobs: int = 1,
    timeout_seconds: float | None = None,
) -> list[RunResult]:
    """Execute many resolved cases."""
    config = EngineConfig(
        safe_defaults=safe_defaults,
        max_diff=max_diff,
        jobs=jobs,
        default_timeout_seconds=(
            timeout_seconds if timeout_seconds is not None else DEFAULT_TIMEOUT_SECONDS
        ),
    )
    return execute_cases(cases, config)
