#Requires -Version 5.1
<#
.SYNOPSIS
    Run PSScriptAnalyzer and Pester against action, installer, and exe-smoke scripts.
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
$analyzerSettings = Join-Path -Path $PSScriptRoot -ChildPath 'PSScriptAnalyzerSettings.psd1'
. (Join-Path -Path $PSScriptRoot -ChildPath 'InstallerPs.Helpers.ps1')

if (-not (Get-Module -ListAvailable -Name PSScriptAnalyzer)) {
    Install-Module -Name PSScriptAnalyzer -Force -Scope CurrentUser -SkipPublisherCheck
}
$pester5 = Get-Module -ListAvailable -Name Pester |
    Where-Object { $_.Version.Major -ge 5 }
if (-not $pester5) {
    Install-Module -Name Pester -Force -Scope CurrentUser -SkipPublisherCheck -MinimumVersion 5.0.0
}
Import-Module -Name Pester -MinimumVersion 5.0.0

$analyzePaths = Get-PowerShellAnalyzePaths -ScriptsRoot $PSScriptRoot
foreach ($path in $analyzePaths) {
    if (-not (Test-Path -LiteralPath $path)) {
        throw "PowerShell script missing: $path"
    }
}

$issues = Invoke-InstallerPsScriptAnalyzer -Paths $analyzePaths -SettingsPath $analyzerSettings
if ($issues) {
    $issues | Format-Table -AutoSize | Out-String | Write-Output
    throw 'PSScriptAnalyzer reported issues'
}

$pesterPaths = @(
    (Join-Path -Path $repoRoot -ChildPath 'tests\test_run_battest_action.ps1'),
    (Join-Path -Path $PSScriptRoot -ChildPath 'TestInstallerPs.Tests.ps1'),
    (Join-Path -Path $PSScriptRoot -ChildPath 'TestExeSmoke.Tests.ps1')
)

$pesterConfig = New-PesterConfiguration
$pesterConfig.Run.Path = $pesterPaths
$pesterConfig.Run.Exit = $true
$pesterConfig.Output.Verbosity = 'Detailed'
Invoke-Pester -Configuration $pesterConfig
