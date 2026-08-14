#!/usr/bin/env python3
"""Fail when line, branch, function, or class coverage is below 90%."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import logging
from pathlib import Path
import sys

from pydantic import BaseModel, ConfigDict, Field, ValidationError

LOGGER = logging.getLogger("check_coverage")
MIN_PERCENT = 90.0
KINDS = ("line", "branch", "function", "class")
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_JSON = REPO_ROOT / "coverage.json"


class _IgnoreExtra(BaseModel):
    """Pydantic base that ignores unknown coverage.json fields."""

    model_config = ConfigDict(extra="ignore")


class RegionSummary(_IgnoreExtra):
    """Covered and total statement/branch counts for one coverage region."""

    covered_lines: int
    num_statements: int
    covered_branches: int = 0
    num_branches: int = 0


class RegionReport(_IgnoreExtra):
    """Named function or class coverage payload wrapping a region summary."""

    summary: RegionSummary


class FileCoverage(_IgnoreExtra):
    """Per-file coverage.json entry including function and class maps."""

    summary: RegionSummary
    functions: dict[str, RegionReport] = Field(default_factory=dict)
    classes: dict[str, RegionReport] = Field(default_factory=dict)


class CoverageReport(_IgnoreExtra):
    """Top-level coverage.json document with per-file and totals summaries."""

    files: dict[str, FileCoverage]
    totals: RegionSummary


@dataclass(frozen=True)
class MetricPercents:
    """Line, branch, function, and class coverage percentages."""

    line: float
    branch: float
    function: float
    class_: float

    def as_map(self) -> dict[str, float]:
        """Return metric names matching KINDS."""
        return {
            "line": self.line,
            "branch": self.branch,
            "function": self.function,
            "class": self.class_,
        }


def ratio_percent(covered: int, total: int) -> float:
    """Return a percentage, treating an empty denominator as 100."""
    if total <= 0:
        LOGGER.debug("empty total; treating coverage as 100")
        return 100.0
    return 100.0 * covered / total


def _region_hit(region: RegionReport) -> bool:
    """Return True when a named function or class was entered (any covered line).

    This is dead-code detection, not a substitute for line coverage of the body.
    """
    statements = region.summary.num_statements
    if statements <= 0:
        return True
    return region.summary.covered_lines > 0


def _named_region_counts(regions: dict[str, RegionReport]) -> tuple[int, int]:
    hit = 0
    total = 0
    for name, region in regions.items():
        if name == "":
            LOGGER.debug("skipping module-level region")
            continue
        total += 1
        if _region_hit(region):
            hit += 1
        else:
            LOGGER.debug("uncovered region %s", name)
    return hit, total


def percents_for_summary(
    summary: RegionSummary,
    functions: dict[str, RegionReport],
    classes: dict[str, RegionReport],
) -> MetricPercents:
    """Compute line, branch, function, and class percents for one scope."""
    function_hit, function_total = _named_region_counts(functions)
    class_hit, class_total = _named_region_counts(classes)
    return MetricPercents(
        line=ratio_percent(summary.covered_lines, summary.num_statements),
        branch=ratio_percent(summary.covered_branches, summary.num_branches),
        function=ratio_percent(function_hit, function_total),
        class_=ratio_percent(class_hit, class_total),
    )


def load_report(path: Path) -> CoverageReport:
    """Parse and validate a coverage.py JSON report."""
    LOGGER.info("loading coverage JSON %s", path)
    if not path.is_file():
        raise FileNotFoundError(f"coverage JSON missing: {path}")
    text = path.read_text(encoding="utf-8")
    return CoverageReport.model_validate_json(text)


def measure(path: Path) -> tuple[MetricPercents, dict[str, MetricPercents]]:
    """Load coverage JSON and return overall plus per-file percents."""
    report = load_report(path)
    overall_functions: dict[str, RegionReport] = {}
    overall_classes: dict[str, RegionReport] = {}
    files: dict[str, MetricPercents] = {}
    for filename, file_coverage in report.files.items():
        LOGGER.debug("measuring file %s", filename)
        files[filename] = percents_for_summary(
            file_coverage.summary, file_coverage.functions, file_coverage.classes
        )
        for name, region in file_coverage.functions.items():
            if name == "":
                continue
            overall_functions[f"{filename}:{name}"] = region
        for name, region in file_coverage.classes.items():
            if name == "":
                continue
            overall_classes[f"{filename}:{name}"] = region
    overall = percents_for_summary(report.totals, overall_functions, overall_classes)
    LOGGER.info(
        "coverage line=%.2f branch=%.2f function=%.2f class=%.2f files=%s",
        overall.line,
        overall.branch,
        overall.function,
        overall.class_,
        len(files),
    )
    return overall, files


def failures(
    overall: MetricPercents,
    files: dict[str, MetricPercents],
    minimum: float = MIN_PERCENT,
) -> list[str]:
    """Return metric names that fall below the minimum percent."""
    missing: list[str] = []
    mapping = overall.as_map()
    for kind in KINDS:
        value = mapping[kind]
        if value < minimum:
            LOGGER.error("overall %s coverage %.2f is below %.2f", kind, value, minimum)
            missing.append(kind)
        else:
            LOGGER.info("overall %s coverage %.2f meets %.2f", kind, value, minimum)
    for filename, percents in files.items():
        file_map = percents.as_map()
        for kind in KINDS:
            value = file_map[kind]
            label = f"{filename}:{kind}"
            if value < minimum:
                LOGGER.error("%s coverage %.2f is below %.2f", label, value, minimum)
                missing.append(label)
            else:
                LOGGER.debug("%s coverage %.2f meets %.2f", label, value, minimum)
    return missing


def main(argv: list[str] | None = None) -> int:
    """Exit 1 when any coverage metric is below 90%."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)8s] %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--json",
        type=Path,
        default=DEFAULT_JSON,
        help="coverage.py JSON report (default: coverage.json)",
    )
    args = parser.parse_args(argv)
    try:
        overall, files = measure(args.json)
    except FileNotFoundError as exc:
        LOGGER.error("%s", exc)
        return 2
    except (OSError, UnicodeError, ValidationError) as exc:
        LOGGER.error("cannot read coverage JSON %s: %s", args.json, exc)
        return 2
    missing = failures(overall, files)
    if missing:
        LOGGER.error("coverage gate failed: %s", ", ".join(missing))
        return 1
    LOGGER.info("coverage gate passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
