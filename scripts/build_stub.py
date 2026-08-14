#!/usr/bin/env python3
"""Build the battest PATH-mock stub and copy it into package data."""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path
import shutil
import subprocess
import sys

LOGGER = logging.getLogger("build_stub")

REPO_ROOT = Path(__file__).resolve().parent.parent
STUB_DIR = REPO_ROOT / "stub"
STUB_MANIFEST = STUB_DIR / "Cargo.toml"
PACKAGE_DATA = REPO_ROOT / "src" / "battest" / "data"
PACKAGED_EXE_NAME = "battest_stub.exe"


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)8s] %(name)s: %(message)s",
    )


def cargo_executable() -> str:
    """Return the cargo binary name, raising if it is not on PATH."""
    cargo = shutil.which("cargo")
    if cargo is None:
        raise FileNotFoundError("cargo is required to build battest-stub")
    LOGGER.info("using cargo executable %s", cargo)
    return cargo


def windows_release_env() -> dict[str, str]:
    """Return cargo env with MSVC reproducible-link flags on Windows."""
    env = os.environ.copy()
    if sys.platform != "win32":
        LOGGER.debug("skipping MSVC RUSTFLAGS on %s", sys.platform)
        return env
    extra = "-C link-arg=/Brepro -C debuginfo=0"
    existing = env.get("RUSTFLAGS", "").strip()
    env["RUSTFLAGS"] = f"{existing} {extra}".strip() if existing else extra
    LOGGER.info("Windows release RUSTFLAGS=%s", env["RUSTFLAGS"])
    return env


def release_artifact() -> Path:
    """Return the cargo --release output path for this platform."""
    target = STUB_DIR / "target" / "release"
    if sys.platform == "win32":
        return target / "battest-stub.exe"
    return target / "battest-stub"


def packaged_exe() -> Path:
    """Return the Windows PE copied into the Python package data directory."""
    return PACKAGE_DATA / PACKAGED_EXE_NAME


def build_release() -> Path:
    """Compile battest-stub in release mode and return the artifact path."""
    if not STUB_MANIFEST.is_file():
        raise FileNotFoundError(f"missing stub crate: {STUB_MANIFEST}")
    command = [
        cargo_executable(),
        "build",
        "--release",
        "--manifest-path",
        str(STUB_MANIFEST),
        "--locked",
    ]
    LOGGER.info("running %s", " ".join(command))
    completed = subprocess.run(
        command,
        cwd=REPO_ROOT,
        check=False,
        env=windows_release_env(),
    )
    if completed.returncode != 0:
        raise RuntimeError(f"cargo build failed with exit {completed.returncode}")
    artifact = release_artifact()
    if not artifact.is_file():
        raise FileNotFoundError(f"cargo did not produce {artifact}")
    LOGGER.info("built stub artifact %s size=%s", artifact, artifact.stat().st_size)
    return artifact


def copy_packaged_exe(artifact: Path) -> Path:
    """Copy the Windows stub into src/battest/data/battest_stub.exe."""
    if sys.platform != "win32":
        LOGGER.info(
            "skipping package-data copy on %s; packaged stub remains %s",
            sys.platform,
            packaged_exe(),
        )
        return packaged_exe()
    PACKAGE_DATA.mkdir(parents=True, exist_ok=True)
    destination = packaged_exe()
    shutil.copyfile(artifact, destination)
    LOGGER.info("copied %s -> %s", artifact, destination)
    return destination


def main(argv: list[str] | None = None) -> int:
    """Build the stub crate; copy the PE into package data on Windows."""
    _configure_logging()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    LOGGER.info("stub dir=%s package_data=%s", STUB_DIR, PACKAGE_DATA)
    try:
        artifact = build_release()
        copy_packaged_exe(artifact)
    except (FileNotFoundError, RuntimeError) as exc:
        LOGGER.error("%s", exc)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
