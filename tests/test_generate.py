"""Tests for catalog generate-and-check."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType

import pytest

from battest.spec import packaged_data_path


def _load_script(filename: str, module_name: str) -> ModuleType:
    path = Path(__file__).resolve().parent.parent / "scripts" / filename
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _load_generate_module() -> ModuleType:
    return _load_script("generate_spec_data.py", "generate_spec_data")


def test_packaged_data_path_exists() -> None:
    path = packaged_data_path("commands.yaml")
    assert path.is_file()


def test_copy_and_check(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_generate_module()
    package_data = tmp_path / "data"
    monkeypatch.setattr(module, "PACKAGE_DATA", package_data)
    copy_catalogs = getattr(module, "copy_catalogs")
    catalogs_match = getattr(module, "catalogs_match")
    main = getattr(module, "main")
    written = copy_catalogs()
    assert written
    assert catalogs_match() is True
    (package_data / "commands.yaml").write_text("drift\n", encoding="utf-8")
    assert catalogs_match() is False
    assert main(["--check"]) == 1
    assert main([]) == 0
    assert catalogs_match() is True


def _region(covered_lines: int, num_statements: int) -> dict[str, object]:
    return {
        "summary": {
            "covered_lines": covered_lines,
            "num_statements": num_statements,
            "covered_branches": 0,
            "num_branches": 0,
        }
    }


def _coverage_json(
    *,
    covered_lines: int = 9,
    num_statements: int = 10,
    covered_branches: int = 9,
    num_branches: int = 10,
    functions: dict[str, dict[str, object]] | None = None,
    classes: dict[str, dict[str, object]] | None = None,
) -> dict[str, object]:
    file_functions = functions if functions is not None else {"run": _region(1, 1)}
    file_classes = classes if classes is not None else {"Runner": _region(1, 1)}
    return {
        "files": {
            "src/battest/demo.py": {
                "summary": {
                    "covered_lines": covered_lines,
                    "num_statements": num_statements,
                    "covered_branches": covered_branches,
                    "num_branches": num_branches,
                },
                "functions": file_functions,
                "classes": file_classes,
            }
        },
        "totals": {
            "covered_lines": covered_lines,
            "num_statements": num_statements,
            "covered_branches": covered_branches,
            "num_branches": num_branches,
        },
    }


def test_coverage_gate_helpers() -> None:
    module = _load_script("check_coverage.py", "check_coverage")
    assert module.ratio_percent(9, 10) == 90.0
    assert module.ratio_percent(0, 0) == 100.0
    passing = module.MetricPercents(line=91.0, branch=90.0, function=95.0, class_=92.0)
    assert module.failures(passing, {"demo.py": passing}) == []
    failing = module.MetricPercents(line=89.0, branch=90.0, function=95.0, class_=92.0)
    assert module.failures(failing, {}) == ["line"]
    file_fail = module.MetricPercents(
        line=80.0, branch=100.0, function=100.0, class_=100.0
    )
    overall_ok = module.MetricPercents(
        line=100.0, branch=100.0, function=100.0, class_=100.0
    )
    assert module.failures(overall_ok, {"demo.py": file_fail}) == ["demo.py:line"]


def test_coverage_gate_measure_and_main(tmp_path: Path) -> None:
    module = _load_script("check_coverage.py", "check_coverage")
    good = tmp_path / "good.json"
    good.write_text(json.dumps(_coverage_json()), encoding="utf-8")
    overall, files = module.measure(good)
    assert overall.line == 90.0
    assert overall.branch == 90.0
    assert overall.function == 100.0
    assert overall.class_ == 100.0
    assert "src/battest/demo.py" in files
    assert module.main(["--json", str(good)]) == 0

    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(_coverage_json(covered_lines=8)), encoding="utf-8")
    assert module.main(["--json", str(bad)]) == 1
    missing = tmp_path / "missing.json"
    assert module.main(["--json", str(missing)]) == 2
    invalid = tmp_path / "invalid.json"
    invalid.write_text("{not-json", encoding="utf-8")
    assert module.main(["--json", str(invalid)]) == 2
    empty = tmp_path / "empty.json"
    empty.write_bytes(b"\xff")
    assert module.main(["--json", str(empty)]) == 2


def test_coverage_gate_oserror(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_script("check_coverage.py", "check_coverage")
    report = tmp_path / "cov.json"
    report.write_text("{}", encoding="utf-8")

    def boom(_path: Path) -> tuple[object, dict[str, object]]:
        raise OSError("denied")

    monkeypatch.setattr(module, "measure", boom)
    assert module.main(["--json", str(report)]) == 2


def test_coverage_gate_skips_module_regions_and_empty_bodies() -> None:
    module = _load_script("check_coverage.py", "check_coverage")
    report = module.CoverageReport.model_validate(
        _coverage_json(
            functions={
                "": _region(0, 3),
                "covered": _region(2, 2),
                "empty": _region(0, 0),
                "missed": _region(0, 4),
            },
            classes={"": _region(0, 1), "Keeper": _region(1, 1)},
        )
    )
    demo = report.files["src/battest/demo.py"]
    percents = module.percents_for_summary(report.totals, demo.functions, demo.classes)
    assert percents.function == pytest.approx(200.0 / 3.0)
    assert percents.class_ == 100.0


def _llvm_count(covered: int, total: int) -> dict[str, object]:
    percent = 0.0 if total == 0 else 100.0 * covered / total
    return {
        "count": total,
        "covered": covered,
        "percent": percent,
        "notcovered": max(total - covered, 0),
    }


def _llvm_summary(
    *,
    lines: tuple[int, int] = (9, 10),
    functions: tuple[int, int] = (9, 10),
    regions: tuple[int, int] = (9, 10),
    branches: tuple[int, int] = (0, 0),
) -> dict[str, object]:
    return {
        "lines": _llvm_count(*lines),
        "functions": _llvm_count(*functions),
        "regions": _llvm_count(*regions),
        "branches": _llvm_count(*branches),
    }


def _llvm_json(
    *,
    filename: str | None = None,
    summary: dict[str, object] | None = None,
    extra_files: list[dict[str, object]] | None = None,
    totals: dict[str, object] | None = None,
) -> dict[str, object]:
    source = (
        filename
        if filename is not None
        else str(Path("repo") / "stub" / "src" / "lib.rs")
    )
    file_summary = summary if summary is not None else _llvm_summary()
    files = [{"filename": source, "summary": file_summary}]
    if extra_files:
        files.extend(extra_files)
    return {
        "data": [
            {
                "files": files,
                "totals": totals if totals is not None else file_summary,
            }
        ]
    }


def test_rust_coverage_gate_helpers() -> None:
    module = _load_script("check_rust_coverage.py", "check_rust_coverage")
    assert module.ratio_percent(9, 10) == 90.0
    assert module.ratio_percent(0, 0) == 100.0
    assert module.is_stub_source(str(Path("repo") / "stub" / "src" / "lib.rs")) is True
    assert (
        module.is_stub_source(str(Path("repo") / "stub" / "tests" / "cli.rs")) is False
    )
    assert module.is_stub_source(str(Path("other") / "src" / "lib.rs")) is False
    passing = module.MetricPercents(line=91.0, branch=90.0, function=95.0, region=92.0)
    assert module.failures(passing, {"lib.rs": passing}) == []
    failing = module.MetricPercents(line=89.0, branch=90.0, function=95.0, region=92.0)
    assert module.failures(failing, {}) == ["line"]
    file_fail = module.MetricPercents(
        line=100.0, branch=100.0, function=80.0, region=100.0
    )
    overall_ok = module.MetricPercents(
        line=100.0, branch=100.0, function=100.0, region=100.0
    )
    assert module.failures(overall_ok, {"lib.rs": file_fail}) == ["lib.rs:function"]
    command = module.llvm_cov_command("cargo", Path("out.json"))
    assert "--fail-under-lines" in command
    assert "--fail-under-functions" in command
    assert "--fail-under-regions" in command
    assert "--fail-under-file-lines" in command


def test_rust_coverage_measure_uses_regions_as_branch_when_empty(
    tmp_path: Path,
) -> None:
    module = _load_script("check_rust_coverage.py", "check_rust_coverage")
    report = tmp_path / "cov.json"
    report.write_text(json.dumps(_llvm_json()), encoding="utf-8")
    overall, files = module.measure(report)
    assert overall.line == 90.0
    assert overall.function == 90.0
    assert overall.region == 90.0
    assert overall.branch == 90.0
    assert files
    assert module.main(["--skip-collect", "--json", str(report)]) == 0


def test_rust_coverage_measure_uses_real_branch_counters(tmp_path: Path) -> None:
    module = _load_script("check_rust_coverage.py", "check_rust_coverage")
    summary = _llvm_summary(branches=(8, 10), regions=(10, 10))
    report = tmp_path / "cov.json"
    report.write_text(
        json.dumps(_llvm_json(summary=summary, totals=summary)), encoding="utf-8"
    )
    overall, _files = module.measure(report)
    assert overall.branch == 80.0
    assert overall.region == 100.0
    assert module.main(["--skip-collect", "--json", str(report)]) == 1


def test_rust_coverage_gate_errors(tmp_path: Path) -> None:
    module = _load_script("check_rust_coverage.py", "check_rust_coverage")
    missing = tmp_path / "missing.json"
    assert module.main(["--skip-collect", "--json", str(missing)]) == 2
    invalid = tmp_path / "invalid.json"
    invalid.write_text("{not-json", encoding="utf-8")
    assert module.main(["--skip-collect", "--json", str(invalid)]) == 2
    empty = tmp_path / "empty.json"
    empty.write_bytes(b"\xff")
    assert module.main(["--skip-collect", "--json", str(empty)]) == 2
    no_data = tmp_path / "nodata.json"
    no_data.write_text(json.dumps({"data": []}), encoding="utf-8")
    assert module.main(["--skip-collect", "--json", str(no_data)]) == 2
    skipped = tmp_path / "vendor.json"
    skipped.write_text(
        json.dumps(
            _llvm_json(
                filename=str(Path("vendor") / "other.rs"),
                summary=_llvm_summary(lines=(1, 10)),
                totals=_llvm_summary(),
            )
        ),
        encoding="utf-8",
    )
    overall, files = module.measure(skipped)
    assert files == {}
    assert overall.line == 90.0


def test_rust_coverage_overall_uses_stub_src_not_totals(tmp_path: Path) -> None:
    module = _load_script("check_rust_coverage.py", "check_rust_coverage")
    stub = _llvm_summary(lines=(9, 10), functions=(9, 10), regions=(9, 10))
    tests = _llvm_summary(lines=(0, 100), functions=(0, 10), regions=(0, 100))
    inflated = _llvm_summary(lines=(9, 110), functions=(9, 20), regions=(9, 110))
    report = tmp_path / "cov.json"
    report.write_text(
        json.dumps(
            _llvm_json(
                summary=stub,
                extra_files=[
                    {
                        "filename": str(Path("repo") / "stub" / "tests" / "cli.rs"),
                        "summary": tests,
                    }
                ],
                totals=inflated,
            )
        ),
        encoding="utf-8",
    )
    overall, files = module.measure(report)
    assert overall.line == 90.0
    assert files
    assert all("src" in name.replace("\\", "/") for name in files)


def test_rust_coverage_collect_report_requires_tools(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_script("check_rust_coverage.py", "check_rust_coverage")
    output = tmp_path / "out.json"

    monkeypatch.setattr(module.shutil, "which", lambda _name: None)
    assert module.collect_report(output) == 2

    def which_cargo_only(name: str) -> str | None:
        if name == "cargo":
            return "cargo"
        return None

    monkeypatch.setattr(module.shutil, "which", which_cargo_only)
    assert module.collect_report(output) == 2

    monkeypatch.setattr(module.shutil, "which", lambda _name: "tool")
    monkeypatch.setattr(module, "STUB_MANIFEST", tmp_path / "missing.toml")
    assert module.collect_report(output) == 2


def test_rust_coverage_collect_report_runs_llvm_cov(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_script("check_rust_coverage.py", "check_rust_coverage")
    output = tmp_path / "nested" / "out.json"
    monkeypatch.setattr(module.shutil, "which", lambda _name: "tool")
    monkeypatch.setattr(module, "STUB_MANIFEST", tmp_path / "Cargo.toml")
    (tmp_path / "Cargo.toml").write_text("[package]\n", encoding="utf-8")
    seen: list[list[str]] = []

    def fake_run(command: list[str], cwd: Path, check: bool) -> object:
        seen.append(command)

        class Completed:
            returncode = 0

        assert cwd == module.REPO_ROOT
        assert check is False
        return Completed()

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    assert module.collect_report(output) == 0
    assert seen
    assert str(output) in seen[0]
    assert output.parent.is_dir()

    def boom(command: list[str], cwd: Path, check: bool) -> object:
        class Completed:
            returncode = 9

        return Completed()

    monkeypatch.setattr(module.subprocess, "run", boom)
    assert module.collect_report(output) == 9


def test_rust_coverage_main_collect_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_script("check_rust_coverage.py", "check_rust_coverage")

    def fail_collect(_output: Path) -> int:
        return 3

    monkeypatch.setattr(module, "collect_report", fail_collect)
    assert module.main(["--json", str(tmp_path / "out.json")]) == 3


def test_rust_coverage_measure_oserror(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_script("check_rust_coverage.py", "check_rust_coverage")
    report = tmp_path / "cov.json"
    report.write_text(json.dumps(_llvm_json()), encoding="utf-8")

    def boom(_path: Path) -> tuple[object, dict[str, object]]:
        raise OSError("denied")

    monkeypatch.setattr(module, "measure", boom)
    assert module.main(["--skip-collect", "--json", str(report)]) == 2
