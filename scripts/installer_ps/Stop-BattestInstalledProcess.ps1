#Requires -Version 5.1
try {
$target = '__BATTEST_BIN__\battest.exe'
$procs = Get-Process -Name battest -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -and ($_.Path -ieq $target) }
if (-not $procs) { exit 2 }
$procs | Stop-Process -Force
exit 0
}
catch {
Write-Host "ERROR: $_"
exit 1
}
