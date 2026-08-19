#Requires -Version 5.1
$tls = [Net.SecurityProtocolType]::Tls12
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor $tls
$headers = @{ 'User-Agent' = 'battest-installer'; 'Accept' = 'application/vnd.github+json' }
$uri = 'https://api.github.com/repos/tboy1337/battest/releases/latest'
try {
    $release = Invoke-RestMethod -Uri $uri -Headers $headers
}
catch {
    Write-Output 'NOT_FOUND'; exit 0
}
if (-not $release -or $release.prerelease -or $release.draft) { Write-Output 'NOT_FOUND'; exit 0 }
$asset = $release.assets | Where-Object { $_.name -like 'Battest-v*.zip' } | Select-Object -First 1
if (-not $asset) { Write-Output 'NOT_FOUND'; exit 0 }
$digest = $null
if ($asset.PSObject.Properties['digest'] -and $asset.digest) { $digest = [string]$asset.digest }
if (-not $digest) { Write-Output 'NO_DIGEST'; exit 0 }
$line = $asset.browser_download_url + ' ' + $release.tag_name + ' ' + $digest
Write-Output $line
