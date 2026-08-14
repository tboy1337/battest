#Requires -Version 5.1
$item = Get-Item -LiteralPath '__BATTEST_TEMP__.zip' -ErrorAction Stop
Write-Output $item.Length
