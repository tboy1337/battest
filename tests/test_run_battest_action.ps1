#Requires -Version 5.1

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

BeforeAll {
    $script:ActionScript = Join-Path -Path $PSScriptRoot -ChildPath '..\scripts\run-battest-action.ps1'
    . $script:ActionScript
}

Describe 'Get-BattestSafeDefaultsFlag' {
    It 'enables safe-defaults for empty, true, and unknown values' {
        Get-BattestSafeDefaultsFlag -Value '' | Should -Be '--safe-defaults'
        Get-BattestSafeDefaultsFlag -Value 'true' | Should -Be '--safe-defaults'
        Get-BattestSafeDefaultsFlag -Value 'YES' | Should -Be '--safe-defaults'
    }

    It 'disables safe-defaults for false, 0, no, and off' {
        Get-BattestSafeDefaultsFlag -Value 'false' | Should -Be '--no-safe-defaults'
        Get-BattestSafeDefaultsFlag -Value '0' | Should -Be '--no-safe-defaults'
        Get-BattestSafeDefaultsFlag -Value 'NO' | Should -Be '--no-safe-defaults'
        Get-BattestSafeDefaultsFlag -Value 'Off' | Should -Be '--no-safe-defaults'
    }
}

Describe 'Convert-BattestExtraArg' {
    It 'returns an empty array for blank extra-args' {
        Convert-BattestExtraArg -Extra '' | Should -HaveCount 0
        Convert-BattestExtraArg -Extra '   ' | Should -HaveCount 0
    }

    It 'parses a JSON string array' {
        $result = Convert-BattestExtraArg -Extra '["--jobs","1"]'
        $result | Should -Be @('--jobs', '1')
    }

    It 'splits space-separated tokens when the value is not JSON' {
        $result = Convert-BattestExtraArg -Extra '--jobs 1 --verbose'
        $result | Should -Be @('--jobs', '1', '--verbose')
    }

    It 'rejects invalid JSON' {
        { Convert-BattestExtraArg -Extra '[not-json' } | Should -Throw '*not valid JSON*'
    }

    It 'treats a JSON object as a single space-separated token' {
        $result = Convert-BattestExtraArg -Extra '{"jobs":1}'
        $result | Should -Be @('{"jobs":1}')
    }

    It 'rejects JSON arrays that are not all strings' {
        { Convert-BattestExtraArg -Extra '[1,2]' } | Should -Throw '*array of strings*'
        { Convert-BattestExtraArg -Extra '[{"a":1}]' } | Should -Throw '*array of strings*'
    }
}

Describe 'Invoke-BattestAction' {
    BeforeEach {
        $script:Work = Join-Path -Path ([System.IO.Path]::GetTempPath()) -ChildPath (
            'battest-action-' + [guid]::NewGuid().ToString('N')
        )
        New-Item -ItemType Directory -Path $script:Work | Out-Null
        $env:RUNNER_TEMP = $script:Work
        $env:GITHUB_OUTPUT = Join-Path -Path $script:Work -ChildPath 'github-output.txt'
        New-Item -ItemType File -Path $env:GITHUB_OUTPUT | Out-Null
        $env:BATTEST_PATH = 'examples'
        $env:BATTEST_EXTRA_ARGS = '["--jobs","1"]'
        $env:BATTEST_SAFE_DEFAULTS = 'true'
        $script:CapturedArgs = $null
        Mock Invoke-BattestPython {
            $script:CapturedArgs = $PesterBoundParameters['Arguments']
            return 0
        }
    }

    AfterEach {
        Remove-Item -LiteralPath $script:Work -Recurse -Force -ErrorAction SilentlyContinue
        Remove-Item Env:RUNNER_TEMP -ErrorAction SilentlyContinue
        Remove-Item Env:GITHUB_OUTPUT -ErrorAction SilentlyContinue
        Remove-Item Env:BATTEST_PATH -ErrorAction SilentlyContinue
        Remove-Item Env:BATTEST_EXTRA_ARGS -ErrorAction SilentlyContinue
        Remove-Item Env:BATTEST_SAFE_DEFAULTS -ErrorAction SilentlyContinue
    }

    It 'creates the JUnit placeholder, invokes python, and records the output path' {
        $code = Invoke-BattestAction
        $code | Should -Be 0
        $junit = Join-Path -Path $script:Work -ChildPath 'battest-junit.xml'
        Test-Path -LiteralPath $junit | Should -BeTrue
        (Get-Content -LiteralPath $env:GITHUB_OUTPUT -Raw) | Should -Match 'junit-xml='
        $script:CapturedArgs[0] | Should -Be '-m'
        $script:CapturedArgs[1] | Should -Be 'battest'
        $script:CapturedArgs | Should -Contain '--safe-defaults'
        $script:CapturedArgs | Should -Contain '--junit-xml'
        $script:CapturedArgs | Should -Contain 'examples'
        $script:CapturedArgs | Should -Contain '--jobs'
        $script:CapturedArgs | Should -Contain '1'
    }

    It 'passes through a non-zero battest exit code' {
        Mock Invoke-BattestPython { return 2 }
        Invoke-BattestAction | Should -Be 2
        $junit = Join-Path -Path $script:Work -ChildPath 'battest-junit.xml'
        Test-Path -LiteralPath $junit | Should -BeTrue
    }

    It 'does not echo extra-args tokens' {
        $source = Get-Content -LiteralPath $script:ActionScript -Raw
        $source | Should -Not -Match 'Write-Host'
        $source | Should -Not -Match 'cmdArgs -join'
        $source | Should -Match 'Starting battest'
        Invoke-BattestAction | Should -Be 0
        $script:CapturedArgs | Should -Contain '--jobs'
    }
}
