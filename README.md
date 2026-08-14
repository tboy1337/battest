# battest

Runtime test runner for Windows batch files (`.bat` / `.cmd`). battest executes
real `cmd.exe`, then asserts on exit code, stdout, stderr, environment, and
filesystem side effects.

battest is a sibling of [Blinter](https://github.com/tboy1337/Blinter) (static
analysis) and [batch-spec](https://github.com/tboy1337/batch-spec) (language
spec). It does not depend on Blinter.

**Requirements:** Python 3.12+ and Windows (for `battest run`). License:
AGPL-3.0-or-later.

## Five-minute start

1. Install:

```text
pip install battest
```

2. Create `hello.cmd`:

```bat
@echo off
echo hello
exit /b 0
```

3. Create `hello.battest.yaml` next to it:

```yaml
description: hello prints hello
script: hello.cmd
expect:
  exit_code: 0
  stdout:
    contains: hello
```

4. Run:

```text
battest run hello.battest.yaml
```

A passing case prints `PASS hello ...`. A failing case prints a diff and exits
with status `1`. Invalid YAML exits with status `2`.

Case-directory form (same as batch-spec's corpus layout):

```text
tests/hello/input.cmd
tests/hello/expect.yaml
```

Then `battest run tests`.

## Documentation

- [Fixture format](docs/fixture-format.md)
- [CLI](docs/cli.md)
- [Mocking external commands](docs/mocking.md)
- [PATH mock stub crate](docs/stub.md)
- [GitHub Action](docs/github-action.md)
- [Encoding](docs/encoding.md)
- [Safety](docs/safety.md)

## Development

```text
git clone --recurse-submodules https://github.com/tboy1337/battest.git
cd battest
python -m pip install -e ".[dev]"
python scripts/generate_spec_data.py
python scripts/verify.py
```

Rust (PATH-mock stub crate in `stub/`):

```text
cargo test --manifest-path stub/Cargo.toml --locked --all-targets
python scripts/check_rust_coverage.py
python scripts/build_stub.py
```

On Windows, `battest run examples` dogfoods `examples/hello` and
WindowsRescue `flush_dns.cmd` under PATH stubs.
