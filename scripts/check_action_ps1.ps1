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

# Pin exact Gallery versions. -SkipPublisherCheck is required on GitHub-hosted
# Windows images where PSGallery Authenticode often fails to chain.
$scriptAnalyzerVersion = [version]'1.24.0'
$pesterVersion = [version]'5.7.1'

$analyzerInstalled = Get-Module -ListAvailable -Name PSScriptAnalyzer |
    Where-Object { $_.Version -eq $scriptAnalyzerVersion }
if (-not $analyzerInstalled) {
    Install-Module -Name PSScriptAnalyzer -RequiredVersion $scriptAnalyzerVersion -Force -Scope CurrentUser -SkipPublisherCheck
}
$pesterInstalled = Get-Module -ListAvailable -Name Pester |
    Where-Object { $_.Version -eq $pesterVersion }
if (-not $pesterInstalled) {
    Install-Module -Name Pester -RequiredVersion $pesterVersion -Force -Scope CurrentUser -SkipPublisherCheck
}
Import-Module -Name Pester -RequiredVersion $pesterVersion

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
