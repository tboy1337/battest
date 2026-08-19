"""Public Python API for loading and running battest cases."""

from __future__ import annotations

from pathlib import Path

from battest.constants import DEFAULT_MAX_DIFF, DEFAULT_TIMEOUT_SECONDS
from battest.discover import discover_cases
from battest.engine import execute_case, execute_cases
from battest.logging_config import get_logger
from battest.models import Case, EngineConfig, RunResult
from battest.schema import load_cases_from_path

LOGGER = get_logger("api")


def load_case(path: str | Path, *, include_spec_exec: bool = False) -> list[Case]:
    """Load and expand cases from a fixture file or discovery root."""
    resolved = Path(path)
    LOGGER.info(
        "api load_case path=%s include_spec_exec=%s", resolved, include_spec_exec
    )
    if resolved.is_file():
        loaded = load_cases_from_path(resolved)
        LOGGER.info("api load_case file=%s cases=%s", resolved, len(loaded))
        return loaded
    loaded = discover_cases(resolved, include_spec_exec=include_spec_exec)
    LOGGER.info("api load_case dir=%s cases=%s", resolved, len(loaded))
    return loaded


def run_case(
    case: Case,
    *,
    safe_defaults: bool = False,
    max_diff: int = DEFAULT_MAX_DIFF,
    timeout_seconds: float | None = None,
) -> RunResult:
    """Execute a single resolved case."""
    LOGGER.info(
        "api run_case id=%s safe_defaults=%s timeout=%s",
        case.case_id,
        safe_defaults,
        timeout_seconds,
    )
    config = EngineConfig(
        safe_defaults=safe_defaults,
        max_diff=max_diff,
        jobs=1,
        default_timeout_seconds=(
            timeout_seconds if timeout_seconds is not None else DEFAULT_TIMEOUT_SECONDS
        ),
    )
    result = execute_case(case, config)
    LOGGER.info("api run_case id=%s outcome=%s", case.case_id, result.outcome.value)
    return result


def run_cases(
    cases: list[Case],
    *,
    safe_defaults: bool = False,
    max_diff: int = DEFAULT_MAX_DIFF,
    jobs: int = 1,
    timeout_seconds: float | None = None,
) -> list[RunResult]:
    """Execute many resolved cases."""
    LOGGER.info(
        "api run_cases count=%s jobs=%s safe_defaults=%s timeout=%s",
        len(cases),
        jobs,
        safe_defaults,
        timeout_seconds,
    )
    config = EngineConfig(
        safe_defaults=safe_defaults,
        max_diff=max_diff,
        jobs=jobs,
        default_timeout_seconds=(
            timeout_seconds if timeout_seconds is not None else DEFAULT_TIMEOUT_SECONDS
        ),
    )
    results = execute_cases(cases, config)
    LOGGER.info("api run_cases completed count=%s", len(results))
    return results
