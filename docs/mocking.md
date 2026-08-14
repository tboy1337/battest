# Mocking

cmd.exe **internals** (`del`, `copy`, `rd`, …) cannot be shadowed via `PATH`.
battest only stubs **external** commands (`ipconfig`, `reg`, `net`, `timeout`,
`format`, …) listed in batch-spec `stock_windows_utilities`.

## Per-case mocks

```yaml
mocks:
  ipconfig:
    exit_code: 0
    stdout: "Successfully flushed the DNS Resolver Cache.\r\n"
    record_calls: true
    expect_calls:
      - args_contains: "/flushdns"
```

battest copies a small native stub as `ipconfig.exe` (not `.cmd`) into a temp
directory and prepends that directory to `PATH`. Using `.exe` matters: a batch
script that runs `ipconfig` without `CALL` never returns if the shadow is a
`.cmd` file. Sidecar files (`ipconfig.stdout`, `ipconfig.stderr`,
`ipconfig.exit`) supply canned output and the exit code. When call recording
is enabled (the default), battest pre-creates `_calls/ipconfig.log` and each
invocation appends argv.

The stub binary is `src/battest/data/battest_stub.exe`, built from the
`stub/` crate:

```text
python scripts/build_stub.py
```

See [PATH mock stub crate](stub.md) for rustfmt, cargo check, clippy, tests,
and coverage.

`expect_calls` with `not_called: true` asserts the stub was never invoked.
Each `expect_calls` entry must set `args_contains` or `not_called`.

Set `record_calls: false` to skip creating `_calls/<command>.log`. The stub
appends argv only when that log file already exists, so call recording stays
off.

## Safe defaults

`battest run --safe-defaults` (and the GitHub Action default) auto-stubs:

- `format`
- `shutdown`
- `reg`
- `diskpart`
- `bcdedit`

The stub exits `1` and writes `battest: blocked by --safe-defaults: <name>` to
stderr. A case may replace the stub with its own `mocks:` entry or list the
command under `allow:`.

## Internals

Relative `del out.txt` only affects the isolated working directory. An internal
used with an absolute path (`del C:\Windows\...`) cannot be mocked; battest
emits a warning. Run those cases in a disposable VM.
