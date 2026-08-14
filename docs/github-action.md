# GitHub Action

The composite action lives at the repository root (`action.yml`) so consumers
can write `uses: tboy1337/battest@main` today. Pin a published release tag
(for example `@v0.1.0`) rather than a floating branch once that tag exists.
It must run on a **Windows** runner (`runs-on: windows-*`).

```yaml
jobs:
  test-batch:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v7
      - id: battest
        uses: tboy1337/battest@main
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
| `path` | empty (CLI default) | Discovery path |
| `extra-args` | empty | Extra `battest run` arguments. A JSON array of strings (starts with `[`) is parsed as argv. Every element must be a JSON string; objects, numbers, booleans, and `null` fail the action. Otherwise the value is split on spaces, so quoted paths with spaces are not supported in the space-split form. Invalid JSON fails the action with an explicit error |
| `safe-defaults` | `true` | Stub destructive externals. Enabled unless the value is `false`, `0`, `no`, or `off` (case-insensitive). The Action default is on; the CLI default is off |
| `python-version` | `3.14` | Python used to install battest |

Outputs:

| Name | Meaning |
|---|---|
| `junit-xml` | Path to the JUnit XML report under `$RUNNER_TEMP`. Set even when battest exits non-zero, so a later `if: always()` upload step can attach the report |

The action fails if `RUNNER_OS` is not Windows. Inputs are passed through
environment variables so they are not interpolated into the PowerShell script.
