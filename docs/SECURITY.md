# Security

Report vulnerabilities privately to `tboy1337@proton.me`. Do not open a public
issue for a security report until a fix is available or the maintainer says
otherwise.

battest is not a sandbox. It runs real `cmd.exe` against the fixtures you
point it at. A malicious or destructive suite can still harm the host. See
[Safety](safety.md) for the mitigations that are included and those that are
not.

Please include:

- battest version or git commit
- operating system and Python version
- a minimal fixture or command that demonstrates the issue
- impact (for example unexpected file writes, PATH-stub bypass, report spoofing)

PATH-mock stubs only intercept the named external executables they replace.
They do not virtualize the filesystem, registry, or network.

PyPI uploads run from GitHub Actions environment `pypi` with
`pypa/gh-action-pypi-publish@release/v1`. The job still has `id-token: write`
for Trusted Publishing, but PyPI currently has no matching GitHub publisher
(`tboy1337/battest`, workflow `CI.yml`, environment `pypi`), so uploads use
the project-scoped `PYPI_BATTEST` secret. After that publisher is added on
PyPI, remove the `password` input and delete the secret.
