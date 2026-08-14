#Requires -Version 5.1
try {
$binPath = '__BATTEST_BIN__'
$path = [Environment]::GetEnvironmentVariable('Path', 'User')
if (-not $path) { Write-Host 'User PATH is empty'; exit 0 }
if ($path -like "*$binPath*") {
$pathArray = $path -split ';' | Where-Object { $_ -ne '' -and $_ -ne $binPath }
$newPath = $pathArray -join ';'
[Environment]::SetEnvironmentVariable('Path', $newPath, 'User')
Write-Host 'battest removed from User PATH'
}
else {
Write-Host 'battest not found in User PATH'
}
exit 0
}
catch {
Write-Host "ERROR: $_"
exit 1
}
