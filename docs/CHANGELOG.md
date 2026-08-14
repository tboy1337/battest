# Changelog

All notable changes to battest are documented in this file. Release tags follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

Production-readiness fixes for the runner, GitHub Action, and PATH-mock stub.

- Fixture `PATH` now replaces inherited `Path`/`PATH` even when both keys exist
  (POSIX-style environments and tests).
- Default discovery uses `./tests` only when that directory contains battest
  fixtures; otherwise it uses the current directory.
- Composite Action JUnit reports use a unique `battest-junit-<guid>.xml` name
  so two Action steps in one job cannot clobber each other.
- JSON Schema `commandName` matches the runtime lowercase stem rules.
- Nested-quantifier and over-long fixture `regex` patterns are rejected at
  load time.
- CodeQL Rust analysis uses `build-mode: none`.
- Stub crate toolchain is pinned to Rust 1.97.1; Windows PE rebuilds use
  MSVC `/Brepro`. Stub I/O failures print `battest-stub:` on stderr.
- CI releases follow Blinter: bump `[project].version` in `pyproject.toml` on
  `main` to build `battest.exe`, create a GitHub Release, and publish to PyPI.
  A later `main` push still releases if that version tag is missing (retry
  after a failed first attempt). Dependency Graph submission cannot block
  release. Windows pytest rebuilds the PATH-mock stub but does not require a
  byte-identical PE against GitHub-hosted MSVC.
- CI and `scripts/verify.py` lint first-party batch scripts with Blinter
  (`scripts/blinter.ini` for installers; default rules for `examples/`).

## [0.1.0] - 2026-08-14

Initial public tree: `battest run`, PATH mocks, composite Action, and the
Rust stub helper.

[0.1.0]: https://github.com/tboy1337/battest/releases/tag/v0.1.0
