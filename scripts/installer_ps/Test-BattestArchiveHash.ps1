#Requires -Version 5.1
$expected = $env:BATTEST_DIGEST
$path = '__BATTEST_TEMP__.zip'
if (-not $expected) {
Write-Host 'ERROR: GitHub asset digest is missing.'
exit 1
}
$prefix = 'sha256:'
if (-not $expected.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
Write-Host "ERROR: GitHub asset digest is not SHA-256: $expected"
exit 1
}
$hex = $expected.Substring($prefix.Length)
if ($hex.Length -ne 64) {
Write-Host 'ERROR: GitHub SHA-256 digest has unexpected length.'
exit 1
}
foreach ($ch in $hex.ToCharArray()) {
if ($ch -notmatch '[0-9a-fA-F]') {
Write-Host 'ERROR: GitHub SHA-256 digest is not hexadecimal.'
exit 1
}
}
try {
$actual = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
}
catch {
Write-Host "ERROR: $_"
exit 1
}
if ($actual -ne $hex.ToLowerInvariant()) {
Write-Host "ERROR: SHA-256 mismatch (expected $hex, got $actual)."
exit 1
}
Write-Host 'SHA-256 digest verified'
exit 0
