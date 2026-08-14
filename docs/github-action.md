# GitHub Action

The composite action lives at the repository root (`action.yml`) so consumers
can write `uses: tboy1337/battest@v1.0.1`. Pin a published release tag rather
than a floating branch. Do not pin this action to a commit SHA.
It must run on a **Windows** runner (`runs-on: windows-*`).

```yaml
jobs:
  test-batch:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v7
      - id: battest
        uses: tboy1337/battest@v1.0.1
        with:
          path: tests
          safe-defaults: "true"
      - uses: actions/upload-artifact@v7
        if: always()
        with:
          name: battest-junit
          path: ${{ steps.battest.outputs.junit-xml }}
```

Inputs:

| Name | Default | Meaning |
|---|---|---|
| `path` | empty (CLI default: `./tests` only if it has battest fixtures, else cwd) | Discovery path. Set this explicitly in consumer workflows |
| `extra-args` | empty | Extra `battest run` arguments. A JSON array of strings (starts with `[`) is parsed as argv. `[]` means no extra arguments. Every element must be a JSON string; objects, numbers, booleans, and `null` fail the action. Otherwise the value is split on spaces, so quoted paths with spaces are not supported in the space-split form. Invalid JSON fails the action with an explicit error. Action-owned `--junit-xml` and `--safe-defaults` / `--no-safe-defaults` are appended after extra-args so those inputs always win |
| `safe-defaults` | `true` | Stub destructive externals. Enabled unless the value is `false`, `0`, `no`, or `off` (case-insensitive). The Action default is on; the CLI default is off |
| `python-version` | `3.14` | Python used to install battest |

Outputs:

| Name | Meaning |
|---|---|
| `junit-xml` | Path to the JUnit XML report under `$RUNNER_TEMP`. Set even when battest exits non-zero, so a later `if: always()` upload step can attach the report |

The action fails if `RUNNER_OS` is not Windows. Pip cache hashing resolves
`GITHUB_ACTION_PATH` to a canonical path first because `uses: ./` sets that
variable to a directory ending in `.`, which `actions/setup-python` rejects.
Inputs are passed through
environment variables so they are not interpolated into the PowerShell script.
The run step invokes [`scripts/run-battest-action.ps1`](../scripts/run-battest-action.ps1).
That script creates a unique JUnit path (`battest-junit-<guid>.xml`) under
`$RUNNER_TEMP` before calling battest so two Action steps in one job cannot
clobber each other, and does not echo `extra-args` tokens (they can be
sensitive). Action-owned
`--junit-xml` and `--safe-defaults` / `--no-safe-defaults` are passed after
`extra-args`, so those Action inputs cannot be overridden. battest itself
still overwrites the file after a completed run, and writes a one-testcase
error suite when discovery or usage fails with `--junit-xml`.
