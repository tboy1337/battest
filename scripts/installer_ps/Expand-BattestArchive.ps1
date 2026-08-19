#Requires -Version 5.1
try {
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zipPath = '__BATTEST_TEMP__.zip'
$destRoot = '__BATTEST_TEMP__'
$releaseTag = '__BATTEST_VERSION__'
$destFull = [IO.Path]::GetFullPath($destRoot)
if (-not $destFull.EndsWith('\')) { $destFull = $destFull + '\' }
$archive = [IO.Compression.ZipFile]::OpenRead($zipPath)
try {
foreach ($entry in $archive.Entries) {
$target = [IO.Path]::GetFullPath((Join-Path $destFull $entry.FullName))
if (-not $target.StartsWith($destFull, [StringComparison]::OrdinalIgnoreCase)) {
Write-Host ('ERROR: archive entry escapes destination: ' + $entry.FullName)
exit 1
}
}
}
finally {
$archive.Dispose()
}
if (-not (Test-Path -LiteralPath $destRoot)) {
New-Item -ItemType Directory -Path $destRoot -Force | Out-Null
}
Expand-Archive -LiteralPath $zipPath -DestinationPath $destRoot -Force
$expected = Join-Path $destRoot ('Battest-' + $releaseTag + '\battest.exe')
if (-not (Test-Path -LiteralPath $expected)) {
Write-Host ('ERROR: expected Battest-' + $releaseTag + '\battest.exe under extract directory')
exit 1
}
exit 0
}
catch {
Write-Host "ERROR: $_"
exit 1
}
