# GitHub Action

The composite action in this repository must run on **Windows**.

```yaml
jobs:
  test-batch:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v5
      - uses: tboy1337/battest@v0.1.0
        with:
          path: tests
          safe-defaults: "true"
```

Inputs:

| Name | Default | Meaning |
|---|---|---|
| `path` | empty (CLI default) | Discovery path |
| `extra-args` | empty | Extra `battest run` arguments |
| `safe-defaults` | `true` | Stub destructive externals |
| `python-version` | `3.14` | Python used to install battest |

The action fails if `RUNNER_OS` is not Windows. JUnit XML is written under
`$RUNNER_TEMP`.
