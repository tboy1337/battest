#Requires -Version 5.1
try {
$binPath = '__BATTEST_BIN__'
$path = [Environment]::GetEnvironmentVariable('Path', 'User')
if (-not $path) { $path = '' }
$segments = @($path -split ';' | Where-Object { $_ -ne '' })
$normalizedBin = $binPath.TrimEnd('\')
$cmp = [System.StringComparison]::OrdinalIgnoreCase
$already = $false
foreach ($seg in $segments) {
if ([string]::Equals($seg.TrimEnd('\'), $normalizedBin, $cmp)) {
$already = $true
break
}
}
if (-not $already) {
if (-not $path) { $newPath = $binPath } else { $newPath = $path.TrimEnd(';') + ';' + $binPath }
[Environment]::SetEnvironmentVariable('Path', $newPath, 'User')
Write-Host 'battest added to User PATH permanently'
}
else {
Write-Host 'battest already in User PATH'
}
$sessionSegments = @($env:Path -split ';' | Where-Object { $_ -ne '' })
$seen = @{}
$sessionOut = New-Object System.Collections.Generic.List[string]
foreach ($seg in $sessionSegments) {
$key = $seg.TrimEnd('\').ToLowerInvariant()
if ($seen.Contains($key)) { continue }
$seen[$key] = $true
[void]$sessionOut.Add($seg)
}
if (-not $seen.Contains($normalizedBin.ToLowerInvariant())) {
[void]$sessionOut.Add($binPath)
}
$sessionPathFile = '__BATTEST_TEMP___session_path.txt'
Set-Content -LiteralPath $sessionPathFile -Value ($sessionOut -join ';') -Encoding ASCII -NoNewline
exit 0
}
catch {
Write-Host "ERROR: $_"
exit 1
}
