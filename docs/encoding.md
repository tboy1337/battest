# Encoding

`cmd.exe` writes stdout/stderr using the console output code page
(`GetConsoleOutputCP`). battest decodes captured bytes with that encoding and
falls back to charset-normalizer when the bytes are not valid.

Matchers use `newline: auto` by default, so `\r\n` and `\n` compare equal.
Set `newline: crlf` on an `equals` matcher to require CRLF bytes.

Fixture YAML and `input.cmd` files should be UTF-8. If a script under test is
OEM-encoded, keep expected `equals` strings in the same logical text; battest
compares decoded strings, not raw bytes.
