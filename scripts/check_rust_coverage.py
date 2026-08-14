#!/usr/bin/env python3
"""Fail when stub crate line, branch, function, or region coverage is below 90%."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import logging
from pathlib import Path
import shutil
import subprocess
import sys

from pydantic import BaseModel, ConfigDict, Field, ValidationError

LOGGER = logging.getLogger("check_rust_coverage")
MIN_PERCENT = 90.0
KINDS = ("line", "branch", "function", "region")
REPO_ROOT = Path(__file__).resolve().parent.parent
STUB_MANIFEST = REPO_ROOT / "stub" / "Cargo.toml"
DEFAULT_JSON = REPO_ROOT / "stub" / "target" / "llvm-cov.json"


class _IgnoreExtra(BaseModel):
    model_config = ConfigDict(extra="ignore")


class CountPercent(_IgnoreExtra):
    count: int
    covered: int
    percent: float = 0.0
    notcovered: int = 0


def _empty_counts() -> CountPercent:
    return CountPercent(count=0, covered=0)


class CoverageSummary(_IgnoreExtra):
    lines: CountPercent
    functions: CountPercent
    regions: CountPercent
    branches: CountPercent = Field(default_factory=_empty_counts)
    instantiations: CountPercent | None = None
    mcdc: CountPercent | None = None


class FileEntry(_IgnoreExtra):
    filename: str
    summary: CoverageSummary


class ExportData(_IgnoreExtra):
    files: list[FileEntry]
    totals: CoverageSummary


class LlvmExport(_IgnoreExtra):
    data: list[ExportData]


@dataclass(frozen=True)
class MetricPercents:
    line: float
    branch: float
    function: float
    region: float

    def as_map(self) -> dict[str, float]:
        """Return metric names matching KINDS."""
        return {
            "line": self.line,
            "branch": self.branch,
            "function": self.function,
            "region": self.region,
        }


def ratio_percent(covered: int, total: int) -> float:
    """Return a percentage, treating an empty denominator as 100."""
    if total <= 0:
        LOGGER.debug("empty total; treating coverage as 100")
        return 100.0
    return 100.0 * covered / total


def percents_for_summary(summary: CoverageSummary) -> MetricPercents:
    """Compute line, branch, function, and region percents for one scope."""
    branch_count = summary.branches.count
    if branch_count <= 0:
        LOGGER.debug(
            "LLVM branch counters are empty; using region coverage as the branch metric"
        )
        branch = ratio_percent(summary.regions.covered, summary.regions.count)
    else:
        branch = ratio_percent(summary.branches.covered, branch_count)
    return MetricPercents(
        line=ratio_percent(summary.lines.covered, summary.lines.count),
        branch=branch,
        function=ratio_percent(summary.functions.covered, summary.functions.count),
        region=ratio_percent(summary.regions.covered, summary.regions.count),
    )


def is_stub_source(filename: str) -> bool:
    """Return True when `filename` is production source under stub/src."""
    parts = Path(filename).parts
    try:
        stub_index = parts.index("stub")
    except ValueError:
        LOGGER.debug("skipping non-stub path %s", filename)
        return False
    return stub_index + 1 < len(parts) and parts[stub_index + 1] == "src"


def load_report(path: Path) -> LlvmExport:
    """Parse and validate an llvm-cov JSON export."""
    LOGGER.info("loading llvm-cov JSON %s", path)
    if not path.is_file():
        raise FileNotFoundError(f"llvm-cov JSON missing: {path}")
    text = path.read_text(encoding="utf-8")
    return LlvmExport.model_validate_json(text)


def measure(path: Path) -> tuple[MetricPercents, dict[str, MetricPercents]]:
    """Load llvm-cov JSON and return overall plus per-file percents."""
    report = load_report(path)
    if not report.data:
        raise ValueError("llvm-cov JSON has no data entries")
    payload = report.data[0]
    files: dict[str, MetricPercents] = {}
    for entry in payload.files:
        if not is_stub_source(entry.filename):
            LOGGER.debug("skipping non-source %s", entry.filename)
            continue
        files[entry.filename] = percents_for_summary(entry.summary)
    overall = percents_for_summary(payload.totals)
    if payload.totals.branches.count <= 0:
        LOGGER.info(
            "LLVM branch counters are empty; using region coverage as the branch metric"
        )
    LOGGER.info(
        "coverage line=%.2f branch=%.2f function=%.2f region=%.2f files=%s",
        overall.line,
        overall.branch,
        overall.function,
        overall.region,
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


def llvm_cov_command(cargo: str, output: Path) -> list[str]:
    """Return the cargo llvm-cov command that writes JSON to `output`."""
    return [
        cargo,
        "llvm-cov",
        "--manifest-path",
        str(STUB_MANIFEST),
        "--locked",
        "--all-targets",
        "--json",
        "--output-path",
        str(output),
        "--fail-under-lines",
        "90",
        "--fail-under-functions",
        "90",
        "--fail-under-regions",
        "90",
        "--fail-under-file-lines",
        "90",
    ]


def collect_report(output: Path) -> int:
    """Run cargo llvm-cov and write JSON to `output`."""
    cargo = shutil.which("cargo")
    if cargo is None:
        LOGGER.error("cargo is required for stub coverage")
        return 2
    if shutil.which("cargo-llvm-cov") is None:
        LOGGER.error(
            "cargo-llvm-cov is required for stub coverage; "
            "install with: cargo install cargo-llvm-cov"
        )
        return 2
    if not STUB_MANIFEST.is_file():
        LOGGER.error("missing stub crate: %s", STUB_MANIFEST)
        return 2
    output.parent.mkdir(parents=True, exist_ok=True)
    command = llvm_cov_command(cargo, output)
    LOGGER.info("running: %s", " ".join(command))
    completed = subprocess.run(command, cwd=REPO_ROOT, check=False)
    if completed.returncode != 0:
        LOGGER.error("cargo llvm-cov failed (%s)", completed.returncode)
    return completed.returncode


def main(argv: list[str] | None = None) -> int:
    """Exit 1 when any stub coverage metric is below 90%."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)8s] %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--json",
        type=Path,
        default=DEFAULT_JSON,
        help="llvm-cov JSON export (default: stub/target/llvm-cov.json)",
    )
    parser.add_argument(
        "--skip-collect",
        action="store_true",
        help="Do not run cargo llvm-cov; only evaluate an existing JSON file",
    )
    args = parser.parse_args(argv)
    if not args.skip_collect:
        collect_code = collect_report(args.json)
        if collect_code != 0:
            return collect_code
    try:
        overall, files = measure(args.json)
    except FileNotFoundError as exc:
        LOGGER.error("%s", exc)
        return 2
    except (OSError, UnicodeError, ValidationError, ValueError) as exc:
        LOGGER.error("cannot read llvm-cov JSON %s: %s", args.json, exc)
        return 2
    missing = failures(overall, files)
    if missing:
        LOGGER.error("rust coverage gate failed: %s", ", ".join(missing))
        return 1
    LOGGER.info("rust coverage gate passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
