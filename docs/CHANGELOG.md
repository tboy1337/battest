# Changelog

All notable changes to battest are documented in this file. Release tags follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [1.0.9] - 2026-08-20

GitHub Action Marketplace listing and installer-test hygiene.

- Action `name` is `battest Action` with branding (`check-square`, `blue`).
- Installer tests assert the parsed GitHub asset-host allowlist and URI host
  check. The regex timeout test builds its nested-quantifier pattern at
  runtime so CodeQL does not treat those fixtures as URL sanitizers or a
  shipped ReDoS expression.

## [1.0.8] - 2026-08-20

Production audit: Job assign fail-loud, env-dump integrity, installer host
allowlist, and packaging/CI hygiene.

- `AssignProcessToJobObject` failure is a case `ERROR`. battest does not resume
  `cmd.exe` outside the job. The job handle is closed if `Popen` fails. An
  abandoned process skips `rmtree` of the workdir. JUnit duration includes
  teardown.
- After seeding, a non-file env dump path is `ERROR` before spawn. After a
  finished run, missing or non-file dumps are `ERROR` when `expect.env` is set.
  Env dumps, `equals_file`, and `files[]` reads are capped at 10 MiB.
  `copy:` refuses junctions/symlinks whose target escapes the fixture tree.
- Host environment is inherited except stripped `BATTEST_*`. CI secrets that
  are not named `BATTEST_*` can reach the SUT and JUnit. `expect_calls` is not
  a security boundary; call logs live in the writable workdir.
- Installer download URLs must be `https` on GitHub asset hosts. Package smoke
  asserts packaged catalogs and schema. Non-Windows unit coverage does not use
  the 90% floor (Windows jobs still do). PSGallery installs pin exact
  PSScriptAnalyzer and Pester versions.
- Packaged catalog YAML uses the same bounded loader as fixtures. Regex
  workers get `multiprocessing.freeze_support()` from `execute_case`. Invalid
  regex patterns fail immediately without spawning a worker.
- GitHub Action consumers should use `tboy1337/battest@v1`. Release CI moves
  that major tag to each `v1.x.x` GitHub release.

## [1.0.7] - 2026-08-19

Production audit: timeout kill order, resume fail-loud, arg expansion, and
release gating.

- Timeout and output overflow close the Job Object first (`KILL_ON_JOB_CLOSE`),
  then `taskkill` if needed, then join capture threads. Custom pipe readers
  are not mixed with `communicate()`. A failed `NtResumeProcess` or missing
  process handle is a case `ERROR`; a suspended `cmd.exe` is not left until
  timeout. Job Object WinAPI calls use explicit HANDLE/BOOL ctypes prototypes.
- Fixture `args` also reject `%` and `!` so `cmd /c` cannot expand host or
  delayed-expansion variables. Mock stdout/stderr sidecars are written in the
  console code page; unencodable mock text is a `MockError`.
- Relative `%CD%` dumps are resolved against the case workdir. Missing env
  dumps log a warning. `battest` console-script entry calls
  `multiprocessing.freeze_support()` for regex workers.
- Push CI publishes GitHub and PyPI only on a version bump or a missing tag.
  Package smoke asserts the console script and packaged `battest_stub.exe`.

## [1.0.6] - 2026-08-19

Production audit: Job Object isolation, output caps, Trusted Publishing, and
installer/Action hardening.

- Windows cases run inside a Job Object (`KILL_ON_JOB_CLOSE`). `cmd.exe` is
  started suspended, assigned, then resumed. Capture is capped at 10 MiB per
  stream. Abandoned processes cannot be a clean PASS. A `%CD%` outside the
  workdir is a warning, not a fail.
- Fixture `args` reject cmd metacharacters (`"&|<>^` and newlines). Host
  `BATTEST_*` is still stripped; wrapper dumps keep fixture `BATTEST_*` except
  `BATTEST_RC`. File matchers default to UTF-8 and exact newlines.
- Regex matchers run in a killed worker with a 2-second bound. JUnit write
  failures after a FAIL run return exit 1. The PATH-mock stub writes each call
  log line with one `write_all` then `sync_data`.
- The installer requires `Battest-<tag>\battest.exe`, refuses zip-slip
  entries, and propagates bootstrap ERRORLEVEL after deleting the downloaded
  `.cmd`. Session PATH is deduped like user PATH. The Action passes `--`
  before `path`.
- CI release concurrency is `battest-release` (`cancel-in-progress: false`).
  `workflow_dispatch` has `force` (default false) and does not rewrite an
  existing GitHub tag unless forced. PyPI upload uses twine from environment
  `pypi` with the `PYPI_BATTEST` token.
  `build-windows` smokes `battest.exe` before zipping; package-smoke imports
  the wheel.

## [1.0.5] - 2026-08-19

Production audit: timeout-budget spawn, installer PATH matching, YAML alias
limits, and release packaging.

- Setup and the script under test are not spawned when the shared timeout
  budget is already gone (`communicate(timeout=0)` is never used). A spent
  SUT budget is `TIMEOUT`; a spent setup budget stays `ERROR`.
- Stdin that cannot encode to the console code page is a case `ERROR` instead
  of replacing bytes with `?`.
- Parallel `run_cases` / `execute_cases` keep one result per input case even
  when `case_id` values are duplicated.
- Fixture YAML may use at most 256 aliases; deeper nesting that overflows
  Python recursion is a schema error. Packaged spec catalogs are unchanged.
- Installer PATH add/remove compares segments case-insensitively and treats a
  trailing backslash as equivalent, so a second install does not duplicate the
  entry.
- CI builds and twine-checks the sdist and wheel on every run, and GitHub
  Releases attach those artifacts next to the Windows zip. Actions stay on
  version tags, not commit SHAs.
- Directory `load_case(..., include_spec_exec=True)` matches the CLI flag.

## [1.0.4] - 2026-08-19

Production audit: host env isolation, destructive-path warnings, installer
release lookup, CodeQL, and PyInstaller spec cleanup.

- Inherited host `BATTEST_*` variables are stripped before the script runs, so
  a runner or CI job cannot leak helper names into the case. Fixture `env` can
  still set `BATTEST_*` values.
- Destructive-internal absolute-path warnings match quoted paths with spaces
  (`del "C:\Program Files\x.txt"`) and switches with a colon
  (`del /a:h C:\Windows\Temp\x.txt`).
- Fixture YAML larger than 1 MiB is a schema error at load time.
- CodeQL Rust analysis fetches the locked `stub/` crate graph before init so
  rust-analyzer can expand macros. Actions stay on version tags, not commit
  SHAs.
- The standalone installer queries GitHub `releases/latest` instead of paging
  100 releases.
- PyInstaller spec no longer passes removed WinSxS/`cipher` Analysis arguments.

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
- Stub CLI tests fsync the copied helper and retry `ETXTBSY` on exec as well
  as copy, so `cargo llvm-cov` on Linux overlayfs does not fail with
  "Text file busy".
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
  publishes to PyPI with `twine`.
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

[1.0.9]: https://github.com/tboy1337/battest/releases/tag/v1.0.9
[1.0.8]: https://github.com/tboy1337/battest/releases/tag/v1.0.8
[1.0.7]: https://github.com/tboy1337/battest/releases/tag/v1.0.7
[1.0.6]: https://github.com/tboy1337/battest/releases/tag/v1.0.6
[1.0.5]: https://github.com/tboy1337/battest/releases/tag/v1.0.5
[1.0.4]: https://github.com/tboy1337/battest/releases/tag/v1.0.4
[1.0.3]: https://github.com/tboy1337/battest/releases/tag/v1.0.3
[1.0.2]: https://github.com/tboy1337/battest/releases/tag/v1.0.2
[1.0.1]: https://github.com/tboy1337/battest/releases/tag/v1.0.1
[1.0.0]: https://github.com/tboy1337/battest/releases/tag/v1.0.0
