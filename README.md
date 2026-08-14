# battest

Runtime test runner for Windows batch files (`.bat` / `.cmd`). battest executes
real `cmd.exe`, then asserts on exit code, stdout, stderr, environment, and
filesystem side effects.

battest is a sibling of [Blinter](https://github.com/tboy1337/Blinter) (static
analysis) and [batch-spec](https://github.com/tboy1337/batch-spec) (language
spec). It does not depend on Blinter.

**Requirements:** Python 3.11+ and Windows (for `battest run`). License:
AGPL-3.0-or-later ([COPYING](COPYING)). Changelog: [docs/CHANGELOG.md](docs/CHANGELOG.md).

A version bump of `[project].version` in `pyproject.toml` on `main` is the
release trigger (Windows exe zip, GitHub Release, and PyPI). Do not bump the
version until the `PYPI_BATTEST` GitHub Actions secret is set.

## Installation

**Option 1: Install via pip (recommended)**

```text
pip install battest
```

**Option 2: Standalone executable (no Python)**

If you prefer a standalone `.exe` over pip, use the one-line installer:

```text
curl -L https://raw.githubusercontent.com/tboy1337/battest/main/scripts/install_battest.cmd -o install_battest.cmd && (call install_battest.cmd || cd .) && del install_battest.cmd
```

This installs the latest `battest.exe` to `%LOCALAPPDATA%\Programs\battest\bin`,
adds it to your user `PATH`, and handles updates automatically. Restart your
terminal or IDE after installation for `PATH` changes to take effect.

**Manual zip download (fallback):**

- Download the latest `Battest-vX.Y.Z.zip` from
  [GitHub Releases](https://github.com/tboy1337/battest/releases)
- Extract the archive; the executable is `Battest-vX.Y.Z\battest.exe`
- Some antivirus software may flag the executable as a false positive due to
  PyInstaller's runtime unpacking behavior. The executable is safe (all source
  code is open for inspection). pip installation avoids that issue.

### Uninstall

**Standalone executable (one-line installer):**

```text
curl -L https://raw.githubusercontent.com/tboy1337/battest/main/scripts/uninstall_battest.cmd -o uninstall_battest.cmd && (call uninstall_battest.cmd || cd .) && del uninstall_battest.cmd
```

**pip installation:**

```text
pip uninstall battest
```

## Five-minute start

1. Install from PyPI (or git until the first release is published):

```text
pip install battest
```

Until a PyPI release exists:

```text
pip install git+https://github.com/tboy1337/battest.git
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
- [Changelog](docs/CHANGELOG.md)
- [Encoding](docs/encoding.md)
- [Safety](docs/safety.md)
- [Security](docs/SECURITY.md)

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
