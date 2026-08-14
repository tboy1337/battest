#Requires -Version 5.1
<#
.SYNOPSIS
    Run PSScriptAnalyzer and Pester against the composite action script.
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
$actionScript = Join-Path -Path $PSScriptRoot -ChildPath 'run-battest-action.ps1'
$pesterTests = Join-Path -Path $repoRoot -ChildPath 'tests\test_run_battest_action.ps1'

if (-not (Get-Module -ListAvailable -Name PSScriptAnalyzer)) {
    Install-Module -Name PSScriptAnalyzer -Force -Scope CurrentUser -SkipPublisherCheck
}
$pester5 = Get-Module -ListAvailable -Name Pester |
    Where-Object { $_.Version.Major -ge 5 }
if (-not $pester5) {
    Install-Module -Name Pester -Force -Scope CurrentUser -SkipPublisherCheck -MinimumVersion 5.0.0
}
Import-Module -Name Pester -MinimumVersion 5.0.0

$analyzer = Invoke-ScriptAnalyzer -Path $actionScript -Severity @('Error', 'Warning')
if ($analyzer) {
    $analyzer | Format-Table -AutoSize | Out-String | Write-Output
    throw 'PSScriptAnalyzer reported issues'
}

$pesterConfig = New-PesterConfiguration
$pesterConfig.Run.Path = $pesterTests
$pesterConfig.Run.Exit = $true
$pesterConfig.Output.Verbosity = 'Detailed'
Invoke-Pester -Configuration $pesterConfig
