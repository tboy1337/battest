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
directory and prepends that directory to `PATH`. Mock keys are executable stems:
`ipconfig.exe` is treated as `ipconfig`. Path separators and Windows reserved
device names (`nul`, `con`, `prn`, `com1`–`com9`, `lpt1`–`lpt9`) are schema
errors so a fixture cannot write stub files outside the mock directory. Using `.exe` matters: a batch
script that runs `ipconfig` without `CALL` never returns if the shadow is a
`.cmd` file. Sidecar files (`ipconfig.stdout`, `ipconfig.stderr`,
`ipconfig.exit`) supply canned output and the exit code. When call recording
is enabled (the default), battest pre-creates `_calls/ipconfig.log` and each
invocation appends one JSON array of argv strings (so arguments that contain
spaces stay distinct). `expect_calls.args_contains` is still a substring match,
so `/flushdns` matches `["/flushdns"]`.

The stub binary is `src/battest/data/battest_stub.exe`, built from the
`stub/` crate:

```text
python scripts/build_stub.py
```

See [PATH mock stub crate](stub.md) for rustfmt, cargo check, clippy, tests,
and coverage.

`expect_calls` with `not_called: true` asserts the stub was never invoked.
Each `expect_calls` entry must set `args_contains` or `not_called: true`, not
both. `args_contains` must be a non-empty string. `not_called: false` is
rejected. `expect_calls` requires `record_calls: true` (the default); a fixture
that sets `record_calls: false` together with `expect_calls` is a schema error.

Set `record_calls: false` to skip creating `_calls/<command>.log`. The stub
appends argv only when that log file already exists, so call recording stays
off. Do not combine that with `expect_calls`.

## Safe defaults

`battest run --safe-defaults` (and the GitHub Action default) auto-stubs:

- `format`
- `shutdown`
- `reg`
- `diskpart`
- `bcdedit`
- `cipher`
- `netsh`
- `takeown`
- `wmic`

The stub exits `1` and writes `battest: blocked by --safe-defaults: <name>` to
stderr. A case may replace the stub with its own `mocks:` entry or list the
command under `allow:`.

## Internals

Relative `del out.txt` only affects the isolated working directory. Scripts
that write via `%~dp0` also stay inside that workdir copy. A destructive
internal (`copy`, `del`, `erase`, `move`, `rd`, `ren`, `rename`, `rmdir`)
used with an absolute path (`del C:\Windows\...`) cannot be mocked; battest
emits a warning. Run those cases in a disposable VM.
