#Requires -Version 5.1
try {
$binPath = '__BATTEST_BIN__'
$path = [Environment]::GetEnvironmentVariable('Path', 'User')
if (-not $path) { Write-Host 'User PATH is empty'; exit 0 }
$segments = @($path -split ';' | Where-Object { $_ -ne '' })
$normalizedBin = $binPath.TrimEnd('\')
$cmp = [System.StringComparison]::OrdinalIgnoreCase
$pathArray = @($segments | Where-Object { -not [string]::Equals($_.TrimEnd('\'), $normalizedBin, $cmp) })
if ($pathArray.Count -ne $segments.Count) {
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
