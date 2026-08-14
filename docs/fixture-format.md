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
Overlay ids become `name[id]`. Mock `exit_code` values must be 0–255 (cmd
`ERRORLEVEL` range). `copy` entries are placed in the isolated work dir using
the relative path from the fixture file; paths that escape the fixture
directory are rejected.

## Case directory

Mirrors batch-spec `corpus/parse/`:

```text
cases/echo-hello/input.cmd
cases/echo-hello/expect.yaml
```

Omit `script` when `input.cmd` sits beside `expect.yaml`.

## Output matchers

`equals`, `equals_file`, `contains`, `regex`, `empty`. `newline` is `auto`
(default), `lf`, or `crlf`. `auto` treats `\r\n` and `\n` as equal.

## Environment matchers

A plain mapping is NAME=value. `unset` lists names that must be absent from the
process environment after the script returns. `setlocal` inside the script hides
locals, matching cmd.exe.

## Discovery

`battest run [path]` walks `*.battest.yaml` and `expect.yaml`+`input.cmd`.
Default path is `./tests` when that directory exists, otherwise the current
directory. `vendor/`, `.git/`, and virtualenv directories are skipped.
Scanning a directory uses root-relative case ids (`a/hello`, `b/hello`) so
parallel runs cannot collide. Duplicate ids are a schema error. Running a
single file keeps the stem id (`hello`). File matcher paths cannot escape the
isolated work directory.
