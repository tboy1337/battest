# CLI

```text
battest [--version] run [path] [--junit-xml FILE] [--jobs N]
        [--timeout SECONDS] [--max-diff N] [--safe-defaults]
        [--no-safe-defaults] [--include-spec-exec] [-v]
```

| Flag | Meaning |
|---|---|
| `path` | Fixture file or directory. Default: `./tests` when that directory contains battest fixtures (`*.battest.yaml` or `expect.yaml` beside `input.cmd`); otherwise the current directory |
| `--version` | Print the battest version and exit |
| `--junit-xml` | Write xunit2 JUnit XML. When this flag is set, usage, schema, empty-discovery, and engine errors (exit 2) still write a one-testcase error suite named `battest` |
| `--jobs` | Parallel case execution (each case has its own temp dir). Must be between 1 and 256 inclusive |
| `--timeout` | Default timeout when a case omits `timeout_seconds`. Must be a finite number greater than 0 (`nan` and `inf` are rejected) |
| `--max-diff` | Truncate failure diffs and captured expected/actual text to this many characters. Must be >= 1 |
| `--safe-defaults` | PATH-stub `format`, `shutdown`, `reg`, `diskpart`, `bcdedit`, `cipher`, `netsh`, `takeown`, `wmic` unless mocked or listed in `allow` |
| `--no-safe-defaults` | Disable those automatic stubs (CLI default) |
| `--include-spec-exec` | Also discover `vendor/batch-spec/corpus/exec` when that folder exists. The current batch-spec pin does not ship `corpus/exec`, so this flag is a no-op until that corpus is present |
| `-v` | Debug logging to stderr during `battest run`. INFO logs go to stderr after the CLI configures logging; `-v` switches to DEBUG. Library callers keep a NullHandler until they configure logging |

Exit codes: `0` all passed, `1` one or more FAIL/ERROR/TIMEOUT, `2` usage or
schema error.

`python -m battest` is equivalent to `battest`.

## Python API

```python
from battest import load_case, run_case, run_cases

cases = load_case("hello.battest.yaml")  # file or discovery directory
result = run_case(cases[0], safe_defaults=False)
results = run_cases(cases, jobs=1, safe_defaults=False)
```

`load_case` returns one or more resolved cases (param overlays expand).
`run_case` / `run_cases` require Windows `cmd.exe`. `safe_defaults` defaults
to off, matching the CLI.

Run Blinter separately if you want a static pre-check; battest does not invoke it.
