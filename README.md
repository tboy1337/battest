# battest

Runtime test runner for Windows batch files (`.bat` / `.cmd`). battest launches
real `cmd.exe`, then asserts on exit code, stdout, stderr, environment, and
filesystem side effects.

It is a **trusted-fixture runner**, not a sandbox. Destructive scripts can still
harm the host. Use `--safe-defaults` (or the GitHub Action, which enables it)
and a disposable VM or CI runner for untrusted suites. Details:
[Safety](docs/safety.md).

battest is a sibling of [Blinter](https://github.com/tboy1337/Blinter) (static
analysis) and [batch-spec](https://github.com/tboy1337/batch-spec) (language
spec). It does not depend on Blinter.

**Requirements:** Python 3.11+ and Windows for `battest run`. License:
AGPL-3.0-or-later ([COPYING](COPYING)).

## Quick start

```text
pip install battest
```

Create `hello.cmd`:

```bat
@echo off
echo hello
exit /b 0
```

Create `hello.battest.yaml` next to it:

```yaml
description: hello prints hello
script: hello.cmd
expect:
  exit_code: 0
  stdout:
    contains: hello
```

Run:

```text
battest run hello.battest.yaml
```

`python -m battest` is the same as `battest`. A passing case prints `PASS`. A
failing case prints a diff and exits `1`. Invalid YAML or usage exits `2`.

Case-directory form (batch-spec corpus layout) is equivalent:

```text
tests/hello/input.cmd
tests/hello/expect.yaml
```

Then `battest run tests`. From this repository, `battest run examples` runs the
bundled fixtures.

CLI `--safe-defaults` is **off**. The GitHub Action turns it **on**. That flag
PATH-stubs common destructive externals (`format`, `shutdown`, `reg`, and
others); it does not isolate the filesystem. See [CLI](docs/cli.md) and
[Mocking](docs/mocking.md).

## GitHub Action

Requires a Windows runner. Use the moving major tag (`@v1`), not a commit SHA.

```yaml
jobs:
  test-batch:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v7
      - id: battest
        uses: tboy1337/battest@v1
        with:
          path: tests
          safe-defaults: "true"
      - uses: actions/upload-artifact@v7
        if: always()
        with:
          name: battest-junit
          path: ${{ steps.battest.outputs.junit-xml }}
```

Inputs, outputs, and `--` before `path` are documented in
[GitHub Action](docs/github-action.md).

## Installation

### pip (recommended)

```text
pip install battest
```

Wheels on PyPI are published from the GitHub `pypi` environment with
`pypa/gh-action-pypi-publish@release/v1` and the project-scoped
`PYPI_BATTEST` secret until a matching Trusted Publisher is registered on
PyPI. See [Security](docs/SECURITY.md).

### Standalone executable (no Python)

Run this from **cmd.exe** (not PowerShell). It downloads the bootstrap script,
installs the latest `battest.exe` to `%LOCALAPPDATA%\Programs\battest\bin`,
adds that directory to your user `PATH`, and returns the installer exit code
after deleting the downloaded `.cmd`:

```text
curl -L https://raw.githubusercontent.com/tboy1337/battest/main/scripts/install_battest.cmd -o install_battest.cmd && call install_battest.cmd & set "BATTEST_INSTALL_EXIT=%ERRORLEVEL%" & del install_battest.cmd & exit /b %BATTEST_INSTALL_EXIT%
```

The installer always fetches the latest GitHub release and verifies the zip
SHA-256 digest before extract. Download URLs must be `https` on `github.com`,
`objects.githubusercontent.com`, or `release-assets.githubusercontent.com`.
The bootstrap `.cmd` itself is not digest-pinned; the exe payload is. Pinning
the curl URL to a release tag (instead of `main`) is stricter if you want a
known installer script. Restart the terminal or IDE after install so `PATH`
updates are visible.

**Manual zip:** download `Battest-vX.Y.Z.zip` from
[GitHub Releases](https://github.com/tboy1337/battest/releases) and run
`Battest-vX.Y.Z\battest.exe`. Some antivirus products flag PyInstaller unpacking
as a false positive. The source is public; pip avoids that class of heuristic.

### Uninstall

Standalone install (cmd.exe):

```text
curl -L https://raw.githubusercontent.com/tboy1337/battest/main/scripts/uninstall_battest.cmd -o uninstall_battest.cmd && call uninstall_battest.cmd & set "BATTEST_UNINSTALL_EXIT=%ERRORLEVEL%" & del uninstall_battest.cmd & exit /b %BATTEST_UNINSTALL_EXIT%
```

pip:

```text
pip uninstall battest
```

## Python API

```python
from battest import load_case, run_case, run_cases

cases = load_case("hello.battest.yaml")
result = run_case(cases[0], safe_defaults=False)
results = run_cases(cases, jobs=1, safe_defaults=False)
```

`run_case` / `run_cases` require Windows `cmd.exe`. `safe_defaults` defaults to
off, matching the CLI. Full notes: [CLI](docs/cli.md).

## Development

Clone this repository and run `python scripts/verify.py` (format, types, lint,
pytest, and the PATH-mock stub checks). Stub build details:
[PATH mock stub crate](docs/stub.md).

## Documentation

Getting started:

- [Fixture format](docs/fixture-format.md)
- [CLI](docs/cli.md)
- [GitHub Action](docs/github-action.md)

Behavior:

- [Mocking external commands](docs/mocking.md)
- [PATH mock stub crate](docs/stub.md)
- [Encoding](docs/encoding.md)
- [Safety](docs/safety.md)
- [Security](docs/SECURITY.md)
- [Changelog](docs/CHANGELOG.md)
