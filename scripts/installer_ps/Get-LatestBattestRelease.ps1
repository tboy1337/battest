#Requires -Version 5.1
$tls = [Net.SecurityProtocolType]::Tls12
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor $tls
$headers = @{ 'User-Agent' = 'battest-installer'; 'Accept' = 'application/vnd.github+json' }
$uri = 'https://api.github.com/repos/tboy1337/battest/releases?per_page=100'
$releases = Invoke-RestMethod -Uri $uri -Headers $headers
$release = $releases | Where-Object { -not $_.prerelease -and -not $_.draft } | Select-Object -First 1
if (-not $release) { Write-Output 'NOT_FOUND'; exit 0 }
$asset = $release.assets | Where-Object { $_.name -like 'Battest-v*.zip' } | Select-Object -First 1
if (-not $asset) { Write-Output 'NOT_FOUND'; exit 0 }
$digest = $null
if ($asset.PSObject.Properties['digest'] -and $asset.digest) { $digest = [string]$asset.digest }
if (-not $digest) { Write-Output 'NO_DIGEST'; exit 0 }
$line = $asset.browser_download_url + ' ' + $release.tag_name + ' ' + $digest
Write-Output $line
