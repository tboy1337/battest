#Requires -Version 5.1
try {
$binPath = '__BATTEST_BIN__'
$path = [Environment]::GetEnvironmentVariable('Path', 'User')
if (-not $path) { $path = '' }
$segments = $path -split ';' | Where-Object { $_ -ne '' }
if ($segments -notcontains $binPath) {
if (-not $path) { $newPath = $binPath } else { $newPath = $path.TrimEnd(';') + ';' + $binPath }
[Environment]::SetEnvironmentVariable('Path', $newPath, 'User')
Write-Host 'battest added to User PATH permanently'
}
else {
Write-Host 'battest already in User PATH'
}
exit 0
}
catch {
Write-Host "ERROR: $_"
exit 1
}
