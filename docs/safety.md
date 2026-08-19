# Safety

battest is not a sandbox. It runs real `cmd.exe`. Destructive scripts can still
harm the machine. Report security issues as described in [SECURITY.md](SECURITY.md).

Mitigations that **are** included:

- Isolated temporary working directory per case. `script`, `setup`, and
  `teardown` are copied into that directory, so `%~dp0` resolves to the copy
  rather than the fixture tree. Extra sibling files still need `copy:`.
  Isolation of relative internals such as `del` lasts only until the script
  `cd`s away; battest warns when the post-run `%CD%` is outside the workdir.
- `cmd.exe /d` so AutoRun is disabled
- Fixture `script`, `setup`, `teardown`, `copy`, and `equals_file` paths must
  stay under the fixture directory (absolute, drive-relative, and UNC paths
  are rejected). Those paths, and `files[].path`, cannot name reserved Windows
  devices such as `nul` or `con`. `files[].path` also cannot contain `..`.
- Optional `--safe-defaults` PATH stubs for `format`, `shutdown`, `reg`,
  `diskpart`, `bcdedit`, `cipher`, `netsh`, `takeown`, and `wmic`. This is a
  deny list of common destructive externals, not a sandbox. The CLI default is
  off; the GitHub Action default is on.
- A single wall-clock timeout that starts after workdir prep (seeding and PATH
  stubs). Setup, the script under test, and teardown share that remaining
  budget. If the remaining budget is already gone, setup and the script are
  not spawned. After expiry, teardown still gets at least five seconds.
- Windows Job Objects with `KILL_ON_JOB_CLOSE`. `cmd.exe` is started
  suspended, assigned to the job, then resumed. The job handle is closed in
  `finally` so leftover children die with the runner. `taskkill /F /T` remains
  a fallback; if a process is still alive after that, the case is TIMEOUT or
  ERROR and a warning names the pid.
- Captured stdout and stderr are capped at 10 MiB each. Overflow kills the job
  and is a case `ERROR` with truncated output kept for the report.
- Fixture YAML is loaded with `yaml.SafeLoader` and at most 256 aliases.
  Nesting that overflows Python recursion is a schema error. This is not a
  sandbox for untrusted authors; it only bounds alias bombs and stack depth.
- Helper `BATTEST_*` variables are not injected into the script environment.
  Inherited host `BATTEST_*` keys are stripped before the script runs so a
  runner or CI job cannot leak helper names into the case. Fixture `env` can
  still set `BATTEST_*` values. The wrapper calls the copied script via `%~dp0`
  and writes the env dump next to the wrapper, so a script cannot redirect that
  dump by changing variables.
- Warnings for destructive cmd internals (`copy`, `del`, `erase`, `move`,
  `rd`, `ren`, `rename`, `rmdir`) used with absolute paths, including
  `C:\...`, `C:/...`, quoted targets with spaces
  (`del "C:\Program Files\x.txt"`), and `/flag` switches such as
  `del /f /q C:\Windows\Temp\x.txt` and `del /a:h C:\Windows\Temp\x.txt`,
  plus `%SystemRoot%` / `%SystemDrive%` forms next to those verbs
- Fixture `regex` matchers are evaluated in a killed worker process with a
  2-second bound. Nested quantifiers such as `(a+)+`, quantified alternation
  such as `(a|a)*`, and patterns longer than 512 characters are still rejected
  at load time; JSON Schema only bounds length

Mitigations that **are not** included:

- Blocking `del C:\...` / `rd /s` internals
- Network isolation
- Registry virtualization
- A filesystem sandbox after the script changes directory

For untrusted or destructive suites, use a disposable VM or CI
`windows-latest` runner, enable `--safe-defaults`, and mock every external the
script calls.
