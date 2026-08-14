"""Shared pytest configuration for battest."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session", autouse=True)
def _ensure_packaged_data() -> None:
    """Fail the session when packaged catalogs drift from vendor data."""
    script = ROOT / "scripts" / "generate_spec_data.py"
    completed = subprocess.run(
        [sys.executable, str(script), "--check"],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"generate_spec_data --check failed: {completed.stdout}\n{completed.stderr}"
        )


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    """Skip Windows-only tests on other platforms."""
    if sys.platform == "win32":
        return
    skip_windows = pytest.mark.skip(reason="requires Windows cmd.exe")
    for item in items:
        if item.get_closest_marker("windows") is not None:
            item.add_marker(skip_windows)
