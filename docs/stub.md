# PATH mock stub crate

The `stub/` crate is the native helper battest copies as `<command>.exe` when
mocking external Windows commands. Runtime Python still only needs the
prebuilt PE at `src/battest/data/battest_stub.exe`.

## Layout

```text
stub/Cargo.toml
stub/src/lib.rs      # sidecar, exit code, JSON call-log logic
stub/src/main.rs     # thin binary; logs argv only if `_calls/<stem>.log` exists
stub/tests/cli.rs    # runs the compiled stub like PATH mocks do
```

## Commands

From the repository root (Rust stable with `rustfmt`, `clippy`, and
`llvm-tools-preview`, plus `cargo-llvm-cov`):

```text
cargo fmt --all --check --manifest-path stub/Cargo.toml
cargo check --manifest-path stub/Cargo.toml --all-targets --locked
cargo clippy --manifest-path stub/Cargo.toml --all-targets --locked -- -D warnings
cargo test --manifest-path stub/Cargo.toml --locked --all-targets
cargo audit --file stub/Cargo.lock
python scripts/check_rust_coverage.py
```

`check_rust_coverage.py` runs `cargo llvm-cov` and fails unless line, branch,
function, and region coverage are each at least 90% overall and per file under
`stub/src`. LLVM branch counters need nightly; on stable the gate uses region
coverage as the branch metric. Install the collector with
`cargo install cargo-llvm-cov`.

Each logged line is a JSON array of argv strings. Missing sidecar files still
mean empty stdout/stderr and exit `0`. If a sidecar or call log exists but
cannot be read or written, the stub exits `1` instead of swallowing the error.
Rebuild the packaged Windows stub after changing the crate (Windows only copies
the PE into package data):

```text
python scripts/build_stub.py
```

`python scripts/verify.py` runs the format, type-check, clippy, test, and
coverage commands above alongside the Python checks.
