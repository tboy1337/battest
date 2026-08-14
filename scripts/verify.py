#!/usr/bin/env python3
"""Local quality and test verification for battest."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
import shutil
import subprocess
import sys

LOGGER = logging.getLogger("verify")
REPO_ROOT = Path(__file__).resolve().parent.parent


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)8s] %(name)s: %(message)s",
    )


def _run(command: list[str], skip: bool) -> int:
    if skip:
        LOGGER.info("skipping: %s", " ".join(command))
        return 0
    LOGGER.info("running: %s", " ".join(command))
    completed = subprocess.run(command, cwd=REPO_ROOT, check=False)
    if completed.returncode != 0:
        LOGGER.error("command failed (%s): %s", completed.returncode, " ".join(command))
    return completed.returncode


def main(argv: list[str] | None = None) -> int:
    """Run format, lint, type-check, audit, and pytest."""
    _configure_logging()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-format", action="store_true")
    parser.add_argument("--skip-lint", action="store_true")
    parser.add_argument("--skip-audit", action="store_true")
    parser.add_argument("--skip-tests", action="store_true")
    args = parser.parse_args(argv)
    python = sys.executable
    cargo = shutil.which("cargo")
    if cargo is None:
        LOGGER.error("cargo is required for stub crate checks")
        return 2
    cargo_audit = shutil.which("cargo-audit")
    steps: list[tuple[list[str], bool]] = [
        ([python, "scripts/generate_spec_data.py", "--check"], False),
        (
            [python, "-m", "black", "--check", "src", "tests", "scripts"],
            args.skip_format,
        ),
        (
            [python, "-m", "isort", "--check-only", "src", "tests", "scripts"],
            args.skip_format,
        ),
        (
            [cargo, "fmt", "--all", "--check", "--manifest-path", "stub/Cargo.toml"],
            args.skip_format,
        ),
        ([python, "-m", "mypy", "src/battest", "tests", "scripts"], args.skip_lint),
        ([python, "-m", "pylint", "src/battest"], args.skip_lint),
        (
            [
                python,
                "-m",
                "bandit",
                "-r",
                "src/battest",
                "-c",
                "pyproject.toml",
                "-ll",
                "-q",
            ],
            args.skip_lint,
        ),
        (
            [
                cargo,
                "clippy",
                "--manifest-path",
                "stub/Cargo.toml",
                "--all-targets",
                "--locked",
                "--",
                "-D",
                "warnings",
            ],
            args.skip_lint,
        ),
        (
            [
                python,
                "-m",
                "pip_audit",
                "-r",
                "requirements.txt",
                "-r",
                "requirements-dev.txt",
            ],
            args.skip_audit,
        ),
        (
            [cargo, "audit", "--file", "stub/Cargo.lock"],
            args.skip_audit or cargo_audit is None,
        ),
        ([python, "-m", "pytest"], args.skip_tests),
        (
            [
                cargo,
                "test",
                "--manifest-path",
                "stub/Cargo.toml",
                "--locked",
                "--all-targets",
            ],
            args.skip_tests,
        ),
    ]
    if cargo_audit is None:
        LOGGER.info("cargo-audit not on PATH; skipping rust advisory audit")
    for command, skip in steps:
        code = _run(command, skip)
        if code != 0:
            return code
    LOGGER.info("verify succeeded")
    return 0


if __name__ == "__main__":
    sys.exit(main())
