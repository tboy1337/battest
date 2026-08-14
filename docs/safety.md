# Safety

battest is not a sandbox. It runs real `cmd.exe`. Destructive scripts can still
harm the machine.

Mitigations that **are** included:

- Isolated temporary working directory per case
- `cmd.exe /d` so AutoRun is disabled
- Optional `--safe-defaults` PATH stubs for `format`, `shutdown`, `reg`,
  `diskpart`, and `bcdedit`
- Timeouts that kill the process tree (`taskkill /T`)
- Warnings for cmd internals used with absolute paths

Mitigations that **are not** included:

- Blocking `del C:\...` / `rd /s` internals
- Network isolation
- Registry virtualization

For untrusted or destructive suites, use a disposable VM or CI
`windows-latest` runner, enable `--safe-defaults`, and mock every external the
script calls.
