# Changelog

## Unreleased

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

## 0.1.0

Initial public tree: `battest run`, PATH mocks, composite Action, and the
Rust stub helper.
