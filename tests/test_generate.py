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
