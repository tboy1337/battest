# GitHub Action

The composite action lives at the repository root (`action.yml`) so consumers
can write `uses: tboy1337/battest@v0.1.0`. It must run on **Windows**.

```yaml
jobs:
  test-batch:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v7
      - id: battest
        uses: tboy1337/battest@v0.1.0
        with:
          path: tests
          safe-defaults: "true"
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: battest-junit
          path: ${{ steps.battest.outputs.junit-xml }}
```

Inputs:

| Name | Default | Meaning |
|---|---|---|
| `path` | empty (CLI default) | Discovery path |
| `extra-args` | empty | Extra `battest run` arguments. A JSON array of strings (starts with `[`) is parsed as argv; otherwise the value is split on spaces, so quoted paths with spaces are not supported in the space-split form. Invalid JSON fails the action with an explicit error. JSON objects are rejected; the value must be an array |
| `safe-defaults` | `true` | Stub destructive externals. Enabled unless the value is `false`, `0`, `no`, or `off` (case-insensitive) |
| `python-version` | `3.14` | Python used to install battest |

Outputs:

| Name | Meaning |
|---|---|
| `junit-xml` | Path to the JUnit XML report under `$RUNNER_TEMP`. Set even when battest exits non-zero, so a later `if: always()` upload step can attach the report |

The action fails if `RUNNER_OS` is not Windows. Inputs are passed through
environment variables so they are not interpolated into the PowerShell script.
