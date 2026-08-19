"""Tests for PATH stub mocking."""

from __future__ import annotations

from pathlib import Path

import pytest

from battest.mocks import (
    MockError,
    _confined_mock_path,
    effective_mocks,
    read_call_logs,
    stub_executable,
    warn_internal_absolute_paths,
    write_mock_tree,
)
from battest.models import MockSpec


def test_effective_mocks_safe_defaults() -> None:
    merged = effective_mocks({}, [], safe_defaults=True)
    assert "format" in merged
    assert "reg" in merged
    assert "netsh" in merged
    assert "cipher" in merged
    assert "takeown" in merged
    assert "wmic" in merged
    assert merged["format"].exit_code == 1


def test_effective_mocks_respects_allow_and_existing() -> None:
    existing = {"reg": MockSpec(exit_code=0)}
    merged = effective_mocks(existing, ["format"], safe_defaults=True)
    assert merged["reg"].exit_code == 0
    assert "format" not in merged


def test_effective_mocks_disabled() -> None:
    assert effective_mocks({}, [], safe_defaults=False) == {}


def test_effective_mocks_skips_internal_safe_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("battest.mocks.SAFE_DEFAULT_COMMANDS", ("del",))
    merged = effective_mocks({}, [], safe_defaults=True)
    assert "del" not in merged


def test_stub_executable_is_packaged() -> None:
    path = stub_executable()
    assert path.is_file()
    assert path.stat().st_size > 0


def test_stub_executable_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "battest.mocks.packaged_data_path",
        lambda name: tmp_path / name,
    )
    with pytest.raises(MockError, match="battest_stub.exe"):
        stub_executable()


def test_write_and_read_call_logs(tmp_path: Path) -> None:
    mock_dir = write_mock_tree(
        tmp_path,
        {"ipconfig": MockSpec(exit_code=0, stdout="flushed\n", stderr="")},
    )
    stub = mock_dir / "ipconfig.exe"
    assert stub.is_file()
    log = mock_dir / "_calls" / "ipconfig.log"
    log.write_text("/flushdns\n", encoding="utf-8")
    recorded = read_call_logs(mock_dir)
    assert recorded["ipconfig"] == ["/flushdns"]


def test_write_mock_tree_sidecars(tmp_path: Path) -> None:
    mock_dir = write_mock_tree(
        tmp_path,
        {"net": MockSpec(exit_code=2, stdout="out", stderr="err")},
    )
    assert (mock_dir / "net.exe").is_file()
    assert (mock_dir / "net.exit").read_text(encoding="utf-8") == "2"
    assert (mock_dir / "net.stdout").read_text(encoding="utf-8") == "out"
    assert (mock_dir / "net.stderr").read_text(encoding="utf-8") == "err"


def test_write_mock_tree_without_call_recording(tmp_path: Path) -> None:
    mock_dir = write_mock_tree(
        tmp_path,
        {"net": MockSpec(exit_code=0, record_calls=False)},
    )
    assert (mock_dir / "net.exe").is_file()
    assert not (mock_dir / "_calls" / "net.log").exists()


def test_write_mock_tree_rejects_internals(tmp_path: Path) -> None:
    with pytest.raises(MockError, match="internal"):
        write_mock_tree(tmp_path, {"del": MockSpec(exit_code=0)})


def test_write_mock_tree_rejects_escaping_and_reserved_names(tmp_path: Path) -> None:
    with pytest.raises(MockError, match="invalid command name"):
        write_mock_tree(tmp_path, {"../evil": MockSpec(exit_code=0)})
    with pytest.raises(MockError, match="reserved"):
        write_mock_tree(tmp_path, {"nul": MockSpec(exit_code=0)})


def test_confined_mock_path_rejects_separators_and_escapes(tmp_path: Path) -> None:
    mock_dir = tmp_path / "mocks"
    mock_dir.mkdir()
    with pytest.raises(MockError, match="plain file name"):
        _confined_mock_path(mock_dir, "evil", "../evil.exe")
    with pytest.raises(MockError, match="outside the mock directory"):
        _confined_mock_path(mock_dir, "evil", "..")


def test_read_call_logs_missing_dir(tmp_path: Path) -> None:
    assert read_call_logs(tmp_path) == {}


def test_read_call_logs_unreadable_raises(tmp_path: Path) -> None:
    mock_dir = tmp_path / "_battest_mocks"
    call_dir = mock_dir / "_calls"
    call_dir.mkdir(parents=True)
    log_path = call_dir / "ipconfig.log"
    log_path.mkdir()
    with pytest.raises(MockError, match="cannot read call log"):
        read_call_logs(mock_dir)


def test_warn_internal_absolute_paths() -> None:
    warnings = warn_internal_absolute_paths(r"del C:\Windows\Temp\x.txt")
    assert warnings
    assert "cannot be PATH-mocked" in warnings[0]
    assert warn_internal_absolute_paths("del relative.txt") == []
    forward = warn_internal_absolute_paths("del C:/Windows/Temp/x.txt")
    assert forward
    assert "C:/Windows/Temp/x.txt" in forward[0]
    quoted = warn_internal_absolute_paths(r'del "C:\Windows\Temp\x.txt"')
    assert quoted
    flagged = warn_internal_absolute_paths(r"del /f /q C:\Windows\Temp\x.txt")
    assert flagged
    quoted_forward = warn_internal_absolute_paths('rd /s /q "C:/Windows/Temp"')
    assert quoted_forward
    spaced = warn_internal_absolute_paths(r'del "C:\Program Files\x.txt"')
    assert spaced
    assert r"C:\Program Files\x.txt" in spaced[0]
    colon_switch = warn_internal_absolute_paths(r"del /a:h C:\Windows\Temp\x.txt")
    assert colon_switch
    assert r"C:\Windows\Temp\x.txt" in colon_switch[0]
    assert warn_internal_absolute_paths(r"xcopy C:\Windows\Temp\x.txt") == []


def test_warn_internal_absolute_paths_skips_empty_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeMatch:
        def group(self, name: str) -> str | None:
            if name == "verb":
                return "del"
            return None

    class FakePattern:
        def finditer(self, _text: str) -> list[FakeMatch]:
            return [FakeMatch()]

    monkeypatch.setattr("battest.mocks._ABS_PATH_RE", FakePattern())
    assert warn_internal_absolute_paths(r"del C:\Windows\Temp\x.txt") == []
