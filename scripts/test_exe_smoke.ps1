#Requires -Version 5.1
<#
.SYNOPSIS
    Smoke tests for the PyInstaller-built battest.exe and parity with python -m battest.

.DESCRIPTION
    Used by CI and locally after building dist\battest.exe. Creates ephemeral fixtures,
    runs functional exe scenarios, then compares exe output to the editable Python CLI.

.PARAMETER ExePath
    Path to battest.exe (default: dist\battest.exe under RepoRoot).

.PARAMETER RepoRoot
    Repository root directory (default: parent of the scripts folder).

.PARAMETER PythonPath
    Python interpreter for parity checks (default: venv\Scripts\python.exe under RepoRoot).
#>
[CmdletBinding()]
param(
    [string]$ExePath = "",
    [string]$RepoRoot = "",
    [string]$PythonPath = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "TestExeSmoke.Helpers.ps1")

if (-not $RepoRoot) {
    $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}

if (-not $ExePath) {
    $ExePath = Join-Path $RepoRoot "dist\battest.exe"
}

if (-not $PythonPath) {
    $PythonPath = Join-Path $RepoRoot "venv\Scripts\python.exe"
}

$ExePath = (Resolve-Path -LiteralPath $ExePath).Path
if (-not (Test-Path -LiteralPath $PythonPath)) {
    throw "Python interpreter not found for parity checks: $PythonPath"
}
$PythonPath = (Resolve-Path -LiteralPath $PythonPath).Path

$pyprojectPath = Join-Path $RepoRoot "pyproject.toml"
$versionMatch = Select-String -Path $pyprojectPath -Pattern '^version = "(.+)"'
if (-not $versionMatch) {
    throw "Could not read project version from $pyprojectPath"
}
$ExpectedVersion = $versionMatch.Matches[0].Groups[1].Value

Initialize-SmokeTestState

$FixtureRoot = New-ExeSmokeFixtureRoot

try {
    Invoke-SmokeTest "exe 01 version" {
        $result = Invoke-BattestProcess -Binary $ExePath -CliArgs @("--version") -WorkingDirectory $FixtureRoot
        if ($result.ExitCode -ne 0) {
            throw "exit $($result.ExitCode): $($result.Output)"
        }
        if ($result.Output -notmatch [regex]::Escape($ExpectedVersion)) {
            throw "expected version $ExpectedVersion in output"
        }
        Test-NoRuntimeCrash -Output $result.Output
    }

    Invoke-SmokeTest "exe 02 help" {
        $result = Invoke-BattestProcess -Binary $ExePath -CliArgs @("--help") -WorkingDirectory $FixtureRoot
        if ($result.ExitCode -ne 0) {
            throw "exit $($result.ExitCode): $($result.Output)"
        }
        if ($result.Output -notmatch "usage:") {
            throw "expected usage text"
        }
        Test-NoRuntimeCrash -Output $result.Output
    }

    Invoke-SmokeTest "exe 03 no args usage" {
        $result = Invoke-BattestProcess -Binary $ExePath -CliArgs @() -WorkingDirectory $FixtureRoot
        if ($result.ExitCode -ne 2) {
            throw "expected exit 2 for missing command, got $($result.ExitCode): $($result.Output)"
        }
        Test-NoRuntimeCrash -Output $result.Output
    }

    Invoke-SmokeTest "exe 04 run fixture" {
        $result = Invoke-BattestProcess -Binary $ExePath -CliArgs @(
            "run", "hello.battest.yaml"
        ) -WorkingDirectory $FixtureRoot
        if ($result.ExitCode -ne 0) {
            throw "exit $($result.ExitCode): $($result.Output)"
        }
        if ($result.Output -notmatch "PASS") {
            throw "expected PASS in output: $($result.Output)"
        }
        Test-NoRuntimeCrash -Output $result.Output
    }

    Invoke-SmokeTest "exe 05 missing path" {
        $result = Invoke-BattestProcess -Binary $ExePath -CliArgs @(
            "run", "missing-battest-fixtures"
        ) -WorkingDirectory $FixtureRoot
        if ($result.ExitCode -ne 2) {
            throw "expected exit 2 for missing path, got $($result.ExitCode): $($result.Output)"
        }
        Test-NoRuntimeCrash -Output $result.Output
    }

    Invoke-SmokeTest "parity 01 version" {
        $pythonResult = Invoke-BattestProcess -Binary $PythonPath -CliArgs @(
            "-m", "battest", "--version"
        ) -WorkingDirectory $FixtureRoot
        $exeResult = Invoke-BattestProcess -Binary $ExePath -CliArgs @(
            "--version"
        ) -WorkingDirectory $FixtureRoot
        if ($pythonResult.ExitCode -ne $exeResult.ExitCode) {
            throw "exit mismatch py=$($pythonResult.ExitCode) exe=$($exeResult.ExitCode)"
        }
        if ($pythonResult.Output -notmatch [regex]::Escape($ExpectedVersion)) {
            throw "python version output missing $ExpectedVersion"
        }
        if ($exeResult.Output -notmatch [regex]::Escape($ExpectedVersion)) {
            throw "exe version output missing $ExpectedVersion"
        }
    }

    Invoke-SmokeTest "parity 02 run fixture" {
        $pythonResult = Invoke-BattestProcess -Binary $PythonPath -CliArgs @(
            "-m", "battest", "run", "hello.battest.yaml"
        ) -WorkingDirectory $FixtureRoot
        $exeResult = Invoke-BattestProcess -Binary $ExePath -CliArgs @(
            "run", "hello.battest.yaml"
        ) -WorkingDirectory $FixtureRoot
        if ($pythonResult.ExitCode -ne $exeResult.ExitCode) {
            throw "exit mismatch py=$($pythonResult.ExitCode) exe=$($exeResult.ExitCode)"
        }
        Test-NoRuntimeCrash -Output $pythonResult.Output
        Test-NoRuntimeCrash -Output $exeResult.Output
    }

    $state = Get-SmokeTestState
    Write-Output "---"
    Write-Output "RESULT: $($state.Passed) / $($state.Total) passed"

    if ($state.Failures.Count -gt 0) {
        Write-Output "FAILURES:"
        foreach ($failure in $state.Failures) {
            Write-Output "  $failure"
        }
        exit 1
    }
}
finally {
    if (Test-Path -LiteralPath $FixtureRoot) {
        Remove-Item -LiteralPath $FixtureRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
