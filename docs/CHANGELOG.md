# Changelog

All notable changes to battest are documented in this file. Release tags follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [1.0.3] - 2026-08-15

Production audit: installer integrity, Windows device path confinement, and
fail-loud fixture loading.

- The standalone installer verifies the GitHub release-asset SHA-256 digest
  (`digest` on the Releases API) after download and before extract. A missing
  digest is a hard failure. The GitHub API request uses TLS 1.2 and a
  `battest-installer` User-Agent.
- Fixture `script`, `setup`, `teardown`, `copy`, `equals_file`, and
  `files[].path` values cannot be rooted, cannot contain `..`, and cannot name
  reserved Windows devices (`nul`, `con`, `aux`, `clock$`, and the rest).
  JSON Schema patterns match those runtime rules.
- Unreadable scripts fail at load time instead of skipping tilde warnings.
  Wrapper-relative script names must be ASCII so cmd.exe cannot mis-decode
  the UTF-8 wrapper.
- Destructive-internal absolute-path warnings also match `C:/...`, quoted
  targets, and `/flag` forms such as `del /f /q C:\Windows\Temp\x.txt`.
- The uninstaller kill helper is kept in parity with
  `scripts/installer_ps/Stop-BattestInstalledProcess.ps1`.
- CI and Action docs continue to pin GitHub Actions to version tags,
  not commit SHAs.

## [1.0.2] - 2026-08-15

Production audit: confinement, mock fail-closed, installer, and release gating.

- PATH-mocking a cmd.exe internal is a `MockError` at stub write time, not a
  silent skip, so the Python API cannot run the real internal.
- Fixture `script`, `setup`, `teardown`, `copy`, and `equals_file` paths reject
  drive-relative and other rooted values (`C:foo`, UNC), not only
  `Path.is_absolute()`.
- Fixture `regex` also rejects quantified alternation such as `(a|a)*`. Nested
  quantifiers and the 512-character cap remain.
- Uninstaller uses delayed `errorlevel` after `rmdir`, exits `1` when removal
  fails, kills only `%LOCALAPPDATA%\Programs\battest\bin\battest.exe`, and
  matches PATH entries by exact segment.
- CI reads `[project].version` with `tomllib`, including the previous commit's
  `pyproject.toml` via UTF-8 `git show` (bytes cannot be passed to
  `tomllib.loads`). It dogfoods examples against the committed stub before
  rebuilding it, creates the GitHub Release only after wheels exist, then
  publishes to PyPI with `twine --skip-existing`.
- JSON Schema rejects reserved device stems, caps `regex` length, and rejects
  rooted file matcher paths. Editors still require lowercase command names.
- CI and Action docs continue to pin GitHub Actions to version tags, not commit
  SHAs.

## [1.0.1] - 2026-08-15

Production audit fixes for release metadata, CI, and fixture loading.

- GitHub Actions concurrency no longer cancels in-progress `main` runs, so a
  version-bump release cannot be aborted mid-publish.
- Release notes are taken from the changelog section that matches
  `[project].version`. A missing or empty section fails CI instead of
  publishing notes from an older version.
- PyPI classifier is Production/Stable. README and Action docs describe the
  published package instead of a pre-release tree.
- `requirements-dev.txt` includes Blinter so it matches `pip install -e ".[dev]"`.
- Fixture load rejects missing or escaping `equals_file` paths as schema errors.
  File matcher `path` values cannot be absolute.
- CI and Action docs continue to pin GitHub Actions to version tags, not commit
  SHAs.

## [1.0.0] - 2026-08-14

First public release: `battest run`, PATH mocks, composite Action, and the
Rust stub helper.

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

[1.0.3]: https://github.com/tboy1337/battest/releases/tag/v1.0.3
[1.0.2]: https://github.com/tboy1337/battest/releases/tag/v1.0.2
[1.0.1]: https://github.com/tboy1337/battest/releases/tag/v1.0.1
[1.0.0]: https://github.com/tboy1337/battest/releases/tag/v1.0.0
