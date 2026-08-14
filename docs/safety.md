# Safety

battest is not a sandbox. It runs real `cmd.exe`. Destructive scripts can still
harm the machine. Report security issues as described in [SECURITY.md](SECURITY.md).

Mitigations that **are** included:

- Isolated temporary working directory per case. `script`, `setup`, and
  `teardown` are copied into that directory, so `%~dp0` resolves to the copy
  rather than the fixture tree. Extra sibling files still need `copy:`.
- `cmd.exe /d` so AutoRun is disabled
- Fixture `script`, `setup`, `teardown`, `copy`, and `equals_file` paths must
  stay under the fixture directory
- Optional `--safe-defaults` PATH stubs for `format`, `shutdown`, `reg`,
  `diskpart`, `bcdedit`, `cipher`, `netsh`, `takeown`, and `wmic`. This is a
  deny list of common destructive externals, not a sandbox. The CLI default is
  off; the GitHub Action default is on.
- A single wall-clock timeout that starts after workdir prep (seeding and PATH
  stubs). Setup, the script under test, and teardown share that remaining
  budget. After expiry, teardown still gets at least five seconds.
- `taskkill /T` on timeout, then a bounded wait so a surviving child cannot
  hang the runner
- Helper `BATTEST_*` variables are not injected into the script environment.
  The wrapper calls the copied script via `%~dp0` and writes the env dump next
  to the wrapper, so a script cannot redirect that dump by changing variables.
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
