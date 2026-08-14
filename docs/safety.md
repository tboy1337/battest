# Safety

battest is not a sandbox. It runs real `cmd.exe`. Destructive scripts can still
harm the machine.

Mitigations that **are** included:

- Isolated temporary working directory per case
- `cmd.exe /d` so AutoRun is disabled
- Fixture `script`, `setup`, `teardown`, `copy`, and `equals_file` paths must
  stay under the fixture directory
- Optional `--safe-defaults` PATH stubs for `format`, `shutdown`, `reg`,
  `diskpart`, `bcdedit`, `cipher`, `netsh`, `takeown`, and `wmic`
- Timeouts that kill the process tree (`taskkill /T`)
- Warnings for cmd internals used with absolute paths

Mitigations that **are not** included:

- Blocking `del C:\...` / `rd /s` internals
- Network isolation
- Registry virtualization
- Timeouts on fixture `regex` matchers (catastrophic patterns can hang the
  runner; treat fixture authors as trusted)

For untrusted or destructive suites, use a disposable VM or CI
`windows-latest` runner, enable `--safe-defaults`, and mock every external the
script calls.
