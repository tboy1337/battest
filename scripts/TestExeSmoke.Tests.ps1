#Requires -Version 5.1

BeforeAll {
    . (Join-Path $PSScriptRoot 'TestExeSmoke.Helpers.ps1')
}

Describe 'Format-CliArgument' {
    It 'returns an empty string for no arguments' {
        Format-CliArgument -CliArgs @() | Should -Be ''
    }

    It 'joins arguments and quotes values that contain spaces' {
        Format-CliArgument -CliArgs @('run', 'my fixture.yaml') |
            Should -Be 'run "my fixture.yaml"'
    }
}

Describe 'Invoke-SmokeTest' {
    It 'records a passing check' {
        Initialize-SmokeTestState
        Invoke-SmokeTest 'ok' { $true } | Out-Null
        $state = Get-SmokeTestState
        $state.Passed | Should -Be 1
        $state.Total | Should -Be 1
        $state.Failures.Count | Should -Be 0
    }

    It 'records a failing check' {
        Initialize-SmokeTestState
        Invoke-SmokeTest 'bad' { throw 'boom' } | Out-Null
        $state = Get-SmokeTestState
        $state.Passed | Should -Be 0
        $state.Total | Should -Be 1
        $state.Failures[0] | Should -Match 'boom'
    }
}

Describe 'Test-NoRuntimeCrash' {
    It 'rejects Python traceback output' {
        { Test-NoRuntimeCrash -Output 'Traceback (most recent call last)' } |
            Should -Throw -ExpectedMessage '*runtime crash*'
    }
}

Describe 'New-ExeSmokeFixtureRoot' {
    It 'creates a hello fixture pair' {
        $root = New-ExeSmokeFixtureRoot
        try {
            Test-Path -LiteralPath (Join-Path $root 'hello.cmd') | Should -BeTrue
            Test-Path -LiteralPath (Join-Path $root 'hello.battest.yaml') | Should -BeTrue
        }
        finally {
            if (Test-Path -LiteralPath $root) {
                Remove-Item -LiteralPath $root -Recurse -Force
            }
        }
    }
}
