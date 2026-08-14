"""Tests for version resolution, release notes, and executable metadata."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
import importlib.util
from pathlib import Path
import sys
import tomllib
from types import ModuleType

import pytest

import battest
from battest._version import _fallback_version, _pyproject_path, get_version

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_script(filename: str) -> ModuleType:
    """Load a repo script module by filename for unit tests."""
    path = REPO_ROOT / "scripts" / filename
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[path.stem] = module
    spec.loader.exec_module(module)
    return module


def test_version_is_pep440_like() -> None:
    version = get_version()
    assert version[0].isdigit()
    assert battest.__version__ == version
    assert battest.__license__ == "AGPL-3.0-or-later"
    assert "load_case" in battest.__all__
    pyproject = _pyproject_path()
    assert pyproject.name == "pyproject.toml"
    assert pyproject.is_file()


def test_package_ships_py_typed_marker() -> None:
    marker = Path(battest.__file__).resolve().parent / "py.typed"
    assert marker.is_file(), "PEP 561 requires src/battest/py.typed"


def test_fallback_version_missing_and_without_version_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "battest._version._pyproject_path", lambda: tmp_path / "missing.toml"
    )
    assert _fallback_version() == "unknown"
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("[project]\nname = 'battest'\n", encoding="utf-8")
    monkeypatch.setattr("battest._version._pyproject_path", lambda: pyproject)
    assert _fallback_version() == "unknown"
    pyproject.write_text("project = 'not-a-table'\n", encoding="utf-8")
    assert _fallback_version() == "unknown"


def test_get_version_prefers_pyproject_over_installed_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nversion = "0.0.1"\n', encoding="utf-8")
    monkeypatch.setattr("battest._version._pyproject_path", lambda: pyproject)
    monkeypatch.setattr("battest._version.version", lambda _name: "9.9.9")
    assert get_version() == "0.0.1"


def test_pyproject_path_uses_meipass_when_frozen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundled = tmp_path / "pyproject.toml"
    bundled.write_text('[project]\nversion = "9.9.9"\n', encoding="utf-8")
    monkeypatch.setattr("battest._version.sys.frozen", True, raising=False)
    monkeypatch.setattr("battest._version.sys._MEIPASS", str(tmp_path), raising=False)
    assert _pyproject_path() == bundled
    assert get_version() == "9.9.9"


def test_get_version_package_not_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "battest._version._pyproject_path", lambda: tmp_path / "missing.toml"
    )

    def boom(_name: str) -> str:
        raise PackageNotFoundError(_name)

    monkeypatch.setattr("battest._version.version", boom)
    assert get_version() == "unknown"


def test_get_version_falls_back_to_pyproject(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nversion = "1.2.3"\n', encoding="utf-8")
    monkeypatch.setattr("battest._version._pyproject_path", lambda: pyproject)

    def boom(_name: str) -> str:
        raise PackageNotFoundError(_name)

    monkeypatch.setattr("battest._version.version", boom)
    assert get_version() == "1.2.3"


def test_fallback_version_invalid_toml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("this is not toml {", encoding="utf-8")
    monkeypatch.setattr("battest._version._pyproject_path", lambda: pyproject)
    assert _fallback_version() == "unknown"


def test_get_version_uses_metadata_when_pyproject_version_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("[project]\nname = 'battest'\n", encoding="utf-8")
    monkeypatch.setattr("battest._version._pyproject_path", lambda: pyproject)
    monkeypatch.setattr("battest._version.version", lambda _name: "8.8.8")
    assert get_version() == "8.8.8"


def test_generate_file_version_info_invalid_pyproject(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_script("generate_file_version_info.py")
    (tmp_path / "pyproject.toml").write_text("this is not toml {", encoding="utf-8")
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "OUTPUT", tmp_path / "file_version_info.txt")
    assert module.main() == 1


def test_pyproject_path_frozen_without_bundled_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("battest._version.sys.frozen", True, raising=False)
    monkeypatch.setattr("battest._version.sys._MEIPASS", str(tmp_path), raising=False)
    resolved = _pyproject_path()
    assert resolved.name == "pyproject.toml"
    assert resolved != tmp_path / "pyproject.toml"


def test_pyproject_path_frozen_with_empty_meipass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("battest._version.sys.frozen", True, raising=False)
    monkeypatch.setattr("battest._version.sys._MEIPASS", "", raising=False)
    resolved = _pyproject_path()
    assert resolved.name == "pyproject.toml"
    assert resolved.is_file()


def test_version_tuple_pads_short_versions() -> None:
    module = _load_script("generate_file_version_info.py")
    assert module._version_tuple("1") == (1, 0, 0)
    assert module._version_tuple("1.2") == (1, 2, 0)
    assert module._version_tuple("1.2.3") == (1, 2, 3)


def test_build_version_info_includes_pyproject_version() -> None:
    module = _load_script("generate_file_version_info.py")
    project_version = module._read_project_version(REPO_ROOT / "pyproject.toml")
    content = module._build_version_info(project_version)
    assert f"u'{project_version}'" in content
    major, minor, patch = module._version_tuple(project_version)
    assert f"filevers=({major}, {minor}, {patch}, 0)" in content
    assert "battest.exe" in content
    assert "AGPL-3.0-or-later" in content


def test_read_project_version_rejects_invalid_tables(tmp_path: Path) -> None:
    module = _load_script("generate_file_version_info.py")
    missing_project = tmp_path / "no-project.toml"
    missing_project.write_text("name = 'x'\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Missing \\[project\\]"):
        module._read_project_version(missing_project)
    missing_version = tmp_path / "no-version.toml"
    missing_version.write_text("[project]\nname = 'battest'\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Missing project.version"):
        module._read_project_version(missing_version)


def test_generate_file_version_info_writes_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_script("generate_file_version_info.py")
    output = tmp_path / "file_version_info.txt"
    monkeypatch.setattr(module, "ROOT", REPO_ROOT)
    monkeypatch.setattr(module, "OUTPUT", output)
    assert module.main() == 0
    assert output.is_file()
    assert "VSVersionInfo(" in output.read_text(encoding="utf-8")


def test_generate_file_version_info_missing_pyproject(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_script("generate_file_version_info.py")
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "OUTPUT", tmp_path / "file_version_info.txt")
    assert module.main() == 2


def test_extract_release_notes_skips_unreleased(tmp_path: Path) -> None:
    module = _load_script("extract_release_notes.py")
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(
        "# Changelog\n\n## [Unreleased]\n\nWIP\n\n"
        "## [1.2.3] - 2026-08-14\n\n### Added\n\n- thing\n\n"
        "## [1.2.2] - 2026-08-01\n\n- older\n",
        encoding="utf-8",
    )
    section = module.extract_latest_section(changelog)
    assert section.startswith("## [1.2.3]")
    assert "thing" in section
    assert "WIP" not in section
    assert "1.2.2" not in section


def test_extract_release_notes_requires_versioned_section(tmp_path: Path) -> None:
    module = _load_script("extract_release_notes.py")
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("# Changelog\n\n## [Unreleased]\n\nnotes\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="No version sections"):
        module.extract_latest_section(changelog)
    empty = tmp_path / "empty.md"
    empty.write_text("# Changelog\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="No version sections"):
        module.extract_latest_section(empty)


def test_extract_release_notes_rejects_empty_version_block(tmp_path: Path) -> None:
    module = _load_script("extract_release_notes.py")
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("## [1.0.0]\n\n## [0.9.0]\n- older\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="empty"):
        module.extract_latest_section(changelog)


def test_extract_release_notes_main_writes_stdout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _load_script("extract_release_notes.py")
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("## [2.0.0] - 2026-01-01\n\n- shipped\n", encoding="utf-8")
    monkeypatch.setattr(module, "_CHANGELOG", changelog)
    monkeypatch.setattr(module, "project_version", lambda _path=None: "2.0.0")
    module.main()
    captured = capsys.readouterr()
    assert "2.0.0" in captured.out
    assert "shipped" in captured.out


def test_extract_release_notes_requires_matching_project_version(
    tmp_path: Path,
) -> None:
    module = _load_script("extract_release_notes.py")
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(
        "## [1.0.0] - 2026-08-14\n\n- first\n\n## [0.9.0] - 2026-01-01\n\n- older\n",
        encoding="utf-8",
    )
    section = module.extract_section_for_version(changelog, "1.0.0")
    assert section.startswith("## [1.0.0]")
    assert "first" in section
    assert "older" not in section
    with pytest.raises(SystemExit, match=r"\[2\.0\.0\]"):
        module.extract_section_for_version(changelog, "2.0.0")


def test_project_version_reads_pyproject(tmp_path: Path) -> None:
    module = _load_script("extract_release_notes.py")
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nversion = "3.2.1"\n', encoding="utf-8")
    assert module.project_version(pyproject) == "3.2.1"
    missing = tmp_path / "missing.toml"
    with pytest.raises(SystemExit, match="Cannot read"):
        module.project_version(missing)
    pyproject.write_text("name = 'battest'\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="Missing \\[project\\]"):
        module.project_version(pyproject)
    pyproject.write_text("[project]\nname = 'battest'\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="Missing project.version"):
        module.project_version(pyproject)


def test_changelog_documents_current_version() -> None:
    version = get_version()
    changelog = (REPO_ROOT / "docs" / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"## [{version}]" in changelog


def test_dev_requirements_match_pyproject_extra() -> None:
    pyproject = tomllib.loads(
        (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    extra = set(pyproject["project"]["optional-dependencies"]["dev"])
    listed: set[str] = set()
    for line in (
        (REPO_ROOT / "requirements-dev.txt").read_text(encoding="utf-8").splitlines()
    ):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("-r "):
            continue
        listed.add(stripped)
    assert listed == extra


def test_suite_does_not_use_hypothesis() -> None:
    banned = "".join(("hypo", "thesis"))
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert banned not in pyproject.lower()
    requirements_dev = (REPO_ROOT / "requirements-dev.txt").read_text(encoding="utf-8")
    assert banned not in requirements_dev.lower()
    for path in (REPO_ROOT / "tests").rglob("*.py"):
        if path.resolve() == Path(__file__).resolve():
            continue
        text = path.read_text(encoding="utf-8")
        assert banned not in text.lower(), path


def test_battest_spec_is_console_onefile_without_icon() -> None:
    spec = (REPO_ROOT / "battest.spec").read_text(encoding="utf-8")
    assert "src/battest/__main__.py" in spec
    assert 'name="battest"' in spec
    assert "upx=False" in spec
    assert 'version="file_version_info.txt"' in spec
    assert "pyproject.toml" in spec
    assert "battest/data" in spec
    assert "icon=" not in spec
    assert '"subprocess"' not in spec
