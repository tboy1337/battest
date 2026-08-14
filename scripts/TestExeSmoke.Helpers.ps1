#Requires -Version 5.1
<#
.SYNOPSIS
    Helper functions for battest.exe smoke testing.
#>
Set-StrictMode -Version Latest

$script:SmokeTestState = @{
    Passed   = 0
    Total    = 0
    Failures = [System.Collections.Generic.List[string]]::new()
}

function Initialize-SmokeTestState {
    $script:SmokeTestState.Passed = 0
    $script:SmokeTestState.Total = 0
    $script:SmokeTestState.Failures = [System.Collections.Generic.List[string]]::new()
}

function Get-SmokeTestState {
    return [PSCustomObject]@{
        Passed   = $script:SmokeTestState.Passed
        Total    = $script:SmokeTestState.Total
        Failures = $script:SmokeTestState.Failures
    }
}

function Format-CliArgument {
    param([string[]]$CliArgs)

    if (-not $CliArgs -or $CliArgs.Count -eq 0) {
        return ""
    }

    return ($CliArgs | ForEach-Object {
            if ($_ -match '\s') {
                '"' + ($_ -replace '"', '""') + '"'
            }
            else {
                $_
            }
        }) -join " "
}

function Invoke-BattestProcess {
    param(
        [string]$Binary,
        [string[]]$CliArgs,
        [string]$WorkingDirectory
    )

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $Binary
    $psi.WorkingDirectory = $WorkingDirectory
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.CreateNoWindow = $true
    $psi.Arguments = Format-CliArgument -CliArgs $CliArgs

    $process = [System.Diagnostics.Process]::Start($psi)
    if (-not $process) {
        throw "Failed to start process: $Binary"
    }

    $stdout = $process.StandardOutput.ReadToEnd()
    $stderr = $process.StandardError.ReadToEnd()
    $process.WaitForExit()

    return [PSCustomObject]@{
        ExitCode = $process.ExitCode
        Stdout   = $stdout
        Stderr   = $stderr
        Output   = "$stdout$stderr"
    }
}

function Test-NoRuntimeCrash {
    param([string]$Output)

    if ($Output -match 'Traceback \(most recent call last\)|ModuleNotFoundError|ImportError') {
        throw "runtime crash detected: $Output"
    }
}

function Invoke-SmokeTest {
    param(
        [string]$Name,
        [scriptblock]$Check
    )

    $script:SmokeTestState.Total++
    try {
        & $Check
        $script:SmokeTestState.Passed++
        Write-Output "PASS: $Name"
    }
    catch {
        $script:SmokeTestState.Failures.Add("$Name - $($_.Exception.Message)")
        Write-Output "FAIL: $Name - $($_.Exception.Message)"
    }
}

function New-ExeSmokeFixtureRoot {
    [CmdletBinding(SupportsShouldProcess = $true)]
    param()

    if (-not $PSCmdlet.ShouldProcess("temporary smoke-test fixtures", "Create")) {
        throw "Fixture creation was not confirmed."
    }

    $utf8NoBom = [System.Text.UTF8Encoding]::new($false)
    $fixtureRoot = New-Item -ItemType Directory -Path (
        Join-Path ([System.IO.Path]::GetTempPath()) ("battest-exe-smoke-" + [guid]::NewGuid().ToString())
    )

    [System.IO.File]::WriteAllText(
        (Join-Path $fixtureRoot "hello.cmd"),
        "@echo off`r`necho hello`r`nexit /b 0`r`n",
        $utf8NoBom
    )
    [System.IO.File]::WriteAllText(
        (Join-Path $fixtureRoot "hello.battest.yaml"),
        "description: hello prints hello`r`nscript: hello.cmd`r`nexpect:`r`n  exit_code: 0`r`n  stdout:`r`n    contains: hello`r`n",
        $utf8NoBom
    )

    return $fixtureRoot.FullName
}
