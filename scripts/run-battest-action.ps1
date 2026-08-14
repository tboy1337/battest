#Requires -Version 5.1
<#
.SYNOPSIS
    Composite GitHub Action entrypoint that invokes battest on a Windows runner.

.DESCRIPTION
    Reads BATTEST_PATH, BATTEST_EXTRA_ARGS, and BATTEST_SAFE_DEFAULTS from the
    environment. Writes a JUnit path under RUNNER_TEMP, then runs
    python -m battest. Extra-args tokens are never echoed.
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-BattestSafeDefaultsFlag {
    <#
    .SYNOPSIS
        Map the Action safe-defaults input to a battest CLI flag.
    #>
    [CmdletBinding()]
    [OutputType([string])]
    param(
        [Parameter(Mandatory = $false)]
        [AllowEmptyString()]
        [string]$Value = ''
    )

    $disabled = @('false', '0', 'no', 'off')
    $normalized = $Value.Trim().ToLowerInvariant()
    if ($disabled -contains $normalized) {
        return '--no-safe-defaults'
    }
    return '--safe-defaults'
}

function Convert-BattestExtraArg {
    <#
    .SYNOPSIS
        Parse extra-args as a JSON string array or space-separated tokens.
    #>
    [CmdletBinding()]
    [OutputType([string[]])]
    param(
        [Parameter(Mandatory = $false)]
        [AllowEmptyString()]
        [string]$Extra = ''
    )

    $trimmed = $Extra.Trim()
    if (-not $trimmed) {
        return [string[]]@()
    }
    if (-not $trimmed.StartsWith('[')) {
        return [string[]]@(
            $trimmed.Split(' ', [System.StringSplitOptions]::RemoveEmptyEntries)
        )
    }
    try {
        if ($PSVersionTable.PSVersion.Major -ge 6) {
            $parsed = ConvertFrom-Json -InputObject $trimmed -NoEnumerate
        }
        else {
            $parsed = ConvertFrom-Json -InputObject $trimmed
        }
    }
    catch {
        throw "battest extra-args is not valid JSON: $_"
    }
    if ($null -eq $parsed) {
        return [string[]]@()
    }
    if ($parsed -is [System.Management.Automation.PSCustomObject]) {
        throw 'battest extra-args JSON must be an array of strings'
    }
    $tokens = [System.Collections.Generic.List[string]]::new()
    foreach ($item in @($parsed)) {
        if ($item -is [System.Management.Automation.PSCustomObject]) {
            throw 'battest extra-args JSON must be an array of strings'
        }
        if ($item -isnot [string]) {
            throw 'battest extra-args JSON must be an array of strings'
        }
        $tokens.Add($item)
    }
    return [string[]]$tokens.ToArray()
}

function Invoke-BattestPython {
    <#
    .SYNOPSIS
        Run python with the given argument vector and return its exit code.
    #>
    [CmdletBinding()]
    [OutputType([int])]
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    & python @Arguments
    return [int]$LASTEXITCODE
}

function Invoke-BattestAction {
    <#
    .SYNOPSIS
        Create the JUnit placeholder, invoke battest, and write GITHUB_OUTPUT.
    #>
    [CmdletBinding()]
    [OutputType([int])]
    param()

    if (-not $env:RUNNER_TEMP) {
        throw 'RUNNER_TEMP is not set'
    }
    if (-not $env:GITHUB_OUTPUT) {
        throw 'GITHUB_OUTPUT is not set'
    }

    $target = ''
    if ($null -ne $env:BATTEST_PATH) {
        $target = $env:BATTEST_PATH.Trim()
    }
    $extra = ''
    if ($null -ne $env:BATTEST_EXTRA_ARGS) {
        $extra = $env:BATTEST_EXTRA_ARGS.Trim()
    }
    $safeValue = ''
    if ($null -ne $env:BATTEST_SAFE_DEFAULTS) {
        $safeValue = $env:BATTEST_SAFE_DEFAULTS
    }
    $safe = Get-BattestSafeDefaultsFlag -Value $safeValue
    $extraArgs = Convert-BattestExtraArg -Extra $extra
    $junit = Join-Path -Path $env:RUNNER_TEMP -ChildPath 'battest-junit.xml'
    New-Item -ItemType File -Path $junit -Force | Out-Null
    Add-Content -LiteralPath $env:GITHUB_OUTPUT -Value "junit-xml=$junit" -Encoding utf8

    $cmdArgs = [System.Collections.Generic.List[string]]::new()
    foreach ($token in @('-m', 'battest', 'run')) {
        $cmdArgs.Add($token)
    }
    if ($target) {
        $cmdArgs.Add($target)
    }
    foreach ($token in $extraArgs) {
        $cmdArgs.Add($token)
    }
    foreach ($token in @($safe, '--junit-xml', $junit)) {
        $cmdArgs.Add($token)
    }

    if ($target) {
        [Console]::Out.WriteLine("Starting battest; target=$target")
    }
    else {
        [Console]::Out.WriteLine('Starting battest; target=(CLI default)')
    }

    $code = Invoke-BattestPython -Arguments ([string[]]$cmdArgs.ToArray())
    return $code
}

if ($MyInvocation.InvocationName -ne '.') {
    $script:ActionExitCode = Invoke-BattestAction
    exit $script:ActionExitCode
}
