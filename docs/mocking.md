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
`ipconfig.exit`) supply canned output and the exit code. Each invocation
appends argv to `_calls/ipconfig.log`.

The stub binary is `src/battest/data/battest_stub.exe`, built from
`battest_stub.rs`:

```text
rustc -O -C debuginfo=0 -o src/battest/data/battest_stub.exe src/battest/data/battest_stub.rs
```

`expect_calls` with `not_called: true` asserts the stub was never invoked.

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
