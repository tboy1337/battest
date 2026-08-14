# PATH mock stub crate

The `stub/` crate is the native helper battest copies as `<command>.exe` when
mocking external Windows commands. Runtime Python still only needs the
prebuilt PE at `src/battest/data/battest_stub.exe`.

## Layout

```text
stub/Cargo.toml
stub/src/lib.rs      # sidecar, exit code, call-log logic
stub/src/main.rs     # thin binary
stub/tests/cli.rs    # runs the compiled stub like PATH mocks do
```

## Commands

From the repository root (Rust stable with `rustfmt` and `clippy`):

```text
cargo fmt --all --check --manifest-path stub/Cargo.toml
cargo clippy --manifest-path stub/Cargo.toml --all-targets --locked -- -D warnings
cargo test --manifest-path stub/Cargo.toml --locked --all-targets
cargo audit --file stub/Cargo.lock
```

Coverage (CI uses the same flags):

```text
cargo llvm-cov --manifest-path stub/Cargo.toml --locked --all-targets --fail-under-lines 90 --fail-under-branches 90
```

Rebuild the packaged Windows stub after changing the crate (Windows only copies
the PE into package data):

```text
python scripts/build_stub.py
```

`python scripts/verify.py` runs the format, clippy, and test commands above
alongside the Python checks.
