"""Tests for version resolution and package exports."""

from __future__ import annotations

import battest
from battest._version import get_version


def test_version_is_pep440_like() -> None:
    version = get_version()
    assert version[0].isdigit()
    assert battest.__version__ == version
    assert battest.__license__ == "AGPL-3.0-or-later"
    assert "load_case" in battest.__all__
