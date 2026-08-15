# Fixture format

battest accepts two equivalent shapes. Runtime loading validates documents with
the Pydantic models in the package. `schema/battest-expect.schema.json` is the
editor/CI catalog (copied into package data); it is not the loader. JSON Schema
`commandName` keys must already be lowercase stems; runtime also accepts mixed
case and a trailing `.exe` / `.cmd` / `.bat` / `.com` suffix and normalizes
them. JSON Schema rejects reserved device names, rooted `files[].path` values,
`files[].path` entries that contain `..`, and `regex` strings longer than 512
characters.

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
Overlay ids become `name[id]` and must be unique. Overlay `mocks`, `allow`, and
`args` are validated the same way as the base document: mocking a cmd.exe
internal is a schema error, `allow` of an internal warns, and invalid `%~`
forms in overlay args warn. Mock `exit_code` values must be 0–255 (cmd
`ERRORLEVEL` range). `copy` entries are placed in the isolated work dir using
the relative path from the fixture file; paths that escape the fixture
directory are rejected. `script`, `setup`, and `teardown` are copied into the
work directory using that same relative layout, so `%~dp0` is the workdir copy
of the script directory. Sibling files that are not the script, setup, or
teardown still need `copy:`. `equals_file` paths are likewise confined to the
fixture directory (absolute paths and `..` escapes are rejected). Missing
`equals_file` targets are schema errors at load time, not later case failures.

`setup` runs before the script under test. The case timeout starts after
workdir prep (copying fixtures and PATH stubs). `timeout_seconds` (and the CLI
`--timeout` default) must be a finite number greater than 0; `nan` and `inf`
are schema errors. Setup, the script, and teardown share the remaining
wall-clock budget. After the budget expires, teardown still runs with at least
five seconds. Assertions (exit code, output, env, files, mock calls) run
against the work directory **before** `teardown`. `teardown` always runs when
it is set, including after a failed `setup`. A failing teardown turns an
otherwise passing case into `ERROR`. Mock command names are case-insensitive;
duplicate names such as `IPCONFIG` and `ipconfig` in the same mapping are a
schema error. A trailing `.exe` / `.cmd` / `.bat` / `.com` suffix is stripped
(`ipconfig.exe` is stored as `ipconfig`). Mock and `allow` names must be simple
executable stems (no path separators) and cannot be Windows reserved device
names such as `nul` or `con`. The same reserved-device rule applies to
`script`, `setup`, `teardown`, `copy`, `equals_file`, and `files[].path`.
`exists: false` means the path must be absent (same as
`not_exists: true`). `not_exists: false` is rejected.

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
schema error. Nested quantifiers such as `(a+)+`, quantified alternation such
as `(a|a)*`, and patterns longer than 512 characters are rejected at load
time. `regex` is matched against newline-normalized captured text; the
pattern itself is not rewritten. `empty: true` treats surrounding whitespace
as empty; `empty: false` fails when the stripped text is empty. `contains` and
mock `args_contains` must be
non-empty; `""` is a schema error. A non-UTF-8 `equals_file` or workdir file
read for `contains`/`equals` is a case failure, not a runner crash. Each
`files` entry must set at least one of `exists`, `not_exists`, `contains`,
`equals`, or `equals_file`. `exists: false` / `not_exists: true` asserts
absence and cannot be combined with content matchers. `not_called: true`
cannot be combined with `args_contains`. A matcher with only `newline: lf` or
`newline: crlf` still enforces those line endings.

## Environment matchers

A plain mapping is NAME=value. `unset` lists names that must be absent from the
process environment after the script returns. `setlocal` inside the script hides
locals, matching cmd.exe.

## Discovery

`battest run [path]` walks `*.battest.yaml` and `expect.yaml`+`input.cmd`.
Default path is `./tests` when that directory contains battest fixtures
(`*.battest.yaml` or `expect.yaml` beside `input.cmd`); otherwise the current
directory. These directory names are skipped: `.git`, `.mypy_cache`,
`.pytest_cache`, `.venv`, `__pycache__`, `build`, `dist`, `htmlcov`, `target`,
`vendor`, `venv`. Scanning a directory uses root-relative case ids
(`a/hello`, `b/hello`) so parallel runs cannot collide. Duplicate ids are a
schema error. Running a single file keeps the stem id (`hello`). File matcher
paths must be relative to the isolated work directory; absolute paths, `..`
segments, and reserved Windows device names are schema errors. Paths that
still escape that directory at assertion time fail the case.
