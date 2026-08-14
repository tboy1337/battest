# Fixture format

battest accepts two equivalent shapes. Runtime loading validates documents with
the Pydantic models in the package. `schema/battest-expect.schema.json` is the
editor/CI catalog (copied into package data); it is not the loader.

## Manifest file

Any `*.battest.yaml` file:

```yaml
description: tool under test
script: deploy.cmd
args: ["--dry-run"]
stdin: ""
env:
  FOO: bar
timeout_seconds: 30
setup: setup.cmd
teardown: teardown.cmd
copy:
  - fixtures/input.txt
allow:
  - reg
mocks:
  ipconfig:
    exit_code: 0
    stdout: "ok\r\n"
    expect_calls:
      - args_contains: "/flushdns"
expect:
  exit_code: 0
  stdout:
    contains: ok
    newline: auto
  stderr:
    empty: true
  env:
    FOO: bar
    unset:
      - TEMPVAR
  files:
    - path: out.txt
      exists: true
      contains: done
params:
  - id: fails
    args: ["--bad"]
    expect:
      exit_code: 1
```

If `params` is present, battest runs the base document **and** each overlay.
Overlay ids become `name[id]` and must be unique. Mock `exit_code` values must
be 0–255 (cmd `ERRORLEVEL` range). `copy` entries are placed in the isolated
work dir using the relative path from the fixture file; paths that escape the
fixture directory are rejected. `script`, `setup`, `teardown`, and `equals_file`
paths are likewise confined to the fixture directory (absolute paths and `..`
escapes are rejected).

`setup` runs before the script under test. Assertions (exit code, output, env,
files, mock calls) run against the work directory **before** `teardown`.
`teardown` always runs when it is set, including after a failed `setup`. A
failing teardown turns an otherwise passing case into `ERROR`.

## Case directory

Mirrors batch-spec `corpus/parse/`:

```text
cases/echo-hello/input.cmd
cases/echo-hello/expect.yaml
```

Omit `script` when `input.cmd` sits beside `expect.yaml`.

## Output matchers

`equals`, `equals_file`, `contains`, `regex`, `empty`. `newline` is `auto`
(default), `lf`, or `crlf`. `auto` treats `\r\n` and `\n` as equal. `lf`
requires the captured text to contain no CR bytes. `crlf` requires CRLF line
endings in the captured text (lone LF fails) and canonicalizes expected YAML
LF to CRLF so authors can write logical lines. Invalid `regex` patterns are a
schema error.

## Environment matchers

A plain mapping is NAME=value. `unset` lists names that must be absent from the
process environment after the script returns. `setlocal` inside the script hides
locals, matching cmd.exe.

## Discovery

`battest run [path]` walks `*.battest.yaml` and `expect.yaml`+`input.cmd`.
Default path is `./tests` when that directory exists, otherwise the current
directory. These directory names are skipped: `.git`, `.mypy_cache`,
`.pytest_cache`, `.venv`, `__pycache__`, `build`, `dist`, `htmlcov`, `target`,
`vendor`, `venv`. Scanning a directory uses root-relative case ids
(`a/hello`, `b/hello`) so parallel runs cannot collide. Duplicate ids are a
schema error. Running a single file keeps the stem id (`hello`). File matcher
paths cannot escape the isolated work directory.
