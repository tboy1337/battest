#Requires -Version 5.1
BeforeAll {
    . (Join-Path $PSScriptRoot 'InstallerPs.Helpers.ps1')
    $script:ScriptsRoot = $PSScriptRoot
    $script:InstallerPsRoot = Join-Path $PSScriptRoot 'installer_ps'
    $script:AnalyzerSettings = Join-Path $PSScriptRoot 'PSScriptAnalyzerSettings.psd1'
}

Describe 'Installer batch PowerShell parity' {
    It 'matches fixture content for each write_*_script block' {
        $pairs = Get-InstallerPsParityPairs -ScriptsRoot $script:ScriptsRoot -InstallerPsRoot $script:InstallerPsRoot
        $pairs.Count | Should -Be 7

        foreach ($pair in $pairs) {
            $normalizedExtracted = Normalize-InstallerPsText -Content $pair.Extracted
            $normalizedFixture = Normalize-InstallerPsText -Content $pair.FixtureBody
            $normalizedExtracted | Should -Be $normalizedFixture `
                -Because "parity failed for $($pair.CmdFile):$($pair.Label) -> $($pair.Fixture)"
        }
    }
}

Describe 'Installer PowerShell PSScriptAnalyzer' {
    It 'reports no warnings for installer fixtures and smoke scripts' {
        if (-not (Get-Module -ListAvailable -Name PSScriptAnalyzer)) {
            Set-ItResult -Inconclusive -Because 'PSScriptAnalyzer is not installed'
            return
        }

        $paths = Get-PowerShellAnalyzePaths -ScriptsRoot $script:ScriptsRoot
        $issues = Invoke-InstallerPsScriptAnalyzer -Paths $paths -SettingsPath $script:AnalyzerSettings
        if ($issues) {
            $formatted = $issues | Format-Table RuleName, ScriptName, Line, Message -Wrap | Out-String
            throw "PSScriptAnalyzer findings:`n$formatted"
        }
    }
}

Describe 'Get-LatestBattestRelease.ps1' {
    It 'outputs NOT_FOUND when the latest-release API fails' {
        $fixturePath = Join-Path $script:InstallerPsRoot 'Get-LatestBattestRelease.ps1'
        Mock Invoke-RestMethod { throw '404' }

        $output = & $fixturePath
        $LASTEXITCODE | Should -Be 0
        $output | Should -Be 'NOT_FOUND'
    }

    It 'outputs URL, tag, and digest when a matching asset exists' {
        $fixturePath = Join-Path $script:InstallerPsRoot 'Get-LatestBattestRelease.ps1'
        Mock Invoke-RestMethod {
            return [PSCustomObject]@{
                prerelease = $false
                draft      = $false
                tag_name   = 'v0.1.0'
                assets     = @(
                    [PSCustomObject]@{
                        name                 = 'Battest-v0.1.0.zip'
                        browser_download_url = 'https://example.com/Battest-v0.1.0.zip'
                        digest               = 'sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef'
                    }
                )
            }
        }

        $output = & $fixturePath
        $LASTEXITCODE | Should -Be 0
        $output | Should -Be 'https://example.com/Battest-v0.1.0.zip v0.1.0 sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef'
    }

    It 'outputs NO_DIGEST when the asset digest is missing' {
        $fixturePath = Join-Path $script:InstallerPsRoot 'Get-LatestBattestRelease.ps1'
        Mock Invoke-RestMethod {
            return [PSCustomObject]@{
                prerelease = $false
                draft      = $false
                tag_name   = 'v0.1.0'
                assets     = @(
                    [PSCustomObject]@{
                        name                 = 'Battest-v0.1.0.zip'
                        browser_download_url = 'https://example.com/Battest-v0.1.0.zip'
                    }
                )
            }
        }

        $output = & $fixturePath
        $LASTEXITCODE | Should -Be 0
        $output | Should -Be 'NO_DIGEST'
    }

    It 'outputs NOT_FOUND when the latest release is a prerelease' {
        $fixturePath = Join-Path $script:InstallerPsRoot 'Get-LatestBattestRelease.ps1'
        Mock Invoke-RestMethod {
            return [PSCustomObject]@{
                prerelease = $true
                draft      = $false
                tag_name   = 'v0.2.0-rc.1'
                assets     = @()
            }
        }

        $output = & $fixturePath
        $LASTEXITCODE | Should -Be 0
        $output | Should -Be 'NOT_FOUND'
    }
}

Describe 'Test-BattestArchiveHash.ps1' {
    It 'accepts a matching SHA-256 digest and rejects a mismatch' {
        $fixturePath = Join-Path $script:InstallerPsRoot 'Test-BattestArchiveHash.ps1'
        $tempRoot = Join-Path $env:TEMP ('battest-hash-' + [guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Path $tempRoot | Out-Null
        try {
            $zipPath = Join-Path $tempRoot 'payload.zip'
            Set-Content -LiteralPath $zipPath -Value 'battest-hash-payload' -NoNewline
            $hash = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash.ToLowerInvariant()
            $scriptBody = (Get-Content -LiteralPath $fixturePath -Raw).Replace(
                '__BATTEST_TEMP__',
                (Join-Path $tempRoot 'payload')
            )
            $runner = Join-Path $tempRoot 'run-hash.ps1'
            Set-Content -LiteralPath $runner -Value $scriptBody

            $env:BATTEST_DIGEST = "sha256:$hash"
            & $runner
            $LASTEXITCODE | Should -Be 0

            $env:BATTEST_DIGEST = 'sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff'
            & $runner
            $LASTEXITCODE | Should -Be 1
        }
        finally {
            Remove-Item -LiteralPath Env:BATTEST_DIGEST -ErrorAction SilentlyContinue
            Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

Describe 'Update-BattestUserPath.ps1' {
    It 'treats PATH membership as case-insensitive and ignores a trailing backslash' {
        $binPath = 'C:\Users\Test\AppData\Local\Programs\battest\bin'
        $path = 'c:\users\test\appdata\local\programs\battest\bin\;C:\Windows'
        $segments = @($path -split ';' | Where-Object { $_ -ne '' })
        $normalizedBin = $binPath.TrimEnd('\')
        $already = $false
        foreach ($seg in $segments) {
            if ([string]::Equals($seg.TrimEnd('\'), $normalizedBin, [System.StringComparison]::OrdinalIgnoreCase)) {
                $already = $true
                break
            }
        }
        $already | Should -BeTrue
    }

    It 'builds a PATH value that appends the bin directory when absent' {
        $binPath = 'C:\Test\battest\bin'
        $path = 'C:\Existing'
        $segments = @($path -split ';' | Where-Object { $_ -ne '' })
        $normalizedBin = $binPath.TrimEnd('\')
        $already = $false
        foreach ($seg in $segments) {
            if ([string]::Equals($seg.TrimEnd('\'), $normalizedBin, [System.StringComparison]::OrdinalIgnoreCase)) {
                $already = $true
                break
            }
        }
        $already | Should -BeFalse
        $newPath = $path.TrimEnd(';') + ';' + $binPath
        $newPath | Should -Be 'C:\Existing;C:\Test\battest\bin'
    }
}

Describe 'Remove-BattestUserPath.ps1' {
    It 'removes a case-insensitive PATH segment including a trailing backslash' {
        $binPath = 'C:\Test\battest\bin'
        $path = 'C:\Alpha;c:\test\battest\bin\;C:\Beta'
        $segments = @($path -split ';' | Where-Object { $_ -ne '' })
        $normalizedBin = $binPath.TrimEnd('\')
        $cmp = [System.StringComparison]::OrdinalIgnoreCase
        $pathArray = @($segments | Where-Object { -not [string]::Equals($_.TrimEnd('\'), $normalizedBin, $cmp) })
        $newPath = $pathArray -join ';'
        $newPath | Should -Be 'C:\Alpha;C:\Beta'
    }
}
