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
    It 'includes check_action_ps1.ps1 in analyzer paths' {
        $paths = Get-PowerShellAnalyzePaths -ScriptsRoot $script:ScriptsRoot
        $names = $paths | ForEach-Object { Split-Path -Path $_ -Leaf }
        $names | Should -Contain 'check_action_ps1.ps1'
    }

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
                        browser_download_url = 'https://github.com/tboy1337/battest/releases/download/v0.1.0/Battest-v0.1.0.zip'
                        digest               = 'sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef'
                    }
                )
            }
        }

        $output = & $fixturePath
        $LASTEXITCODE | Should -Be 0
        $output | Should -Be 'https://github.com/tboy1337/battest/releases/download/v0.1.0/Battest-v0.1.0.zip v0.1.0 sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef'
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
                        browser_download_url = 'https://github.com/tboy1337/battest/releases/download/v0.1.0/Battest-v0.1.0.zip'
                    }
                )
            }
        }

        $output = & $fixturePath
        $LASTEXITCODE | Should -Be 0
        $output | Should -Be 'NO_DIGEST'
    }

    It 'outputs BAD_URL when the download host is not GitHub' {
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
        $output | Should -Be 'BAD_URL'
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
    It 'invokes the fixture and skips a case-insensitive trailing-slash PATH entry' {
        $fixturePath = Join-Path $script:InstallerPsRoot 'Update-BattestUserPath.ps1'
        $tempRoot = Join-Path $env:TEMP ('battest-path-' + [guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Path $tempRoot | Out-Null
        $binPath = Join-Path $tempRoot 'bin'
        $original = [Environment]::GetEnvironmentVariable('Path', 'User')
        try {
            $existing = $binPath.ToLowerInvariant() + '\'
            [Environment]::SetEnvironmentVariable('Path', "$existing;C:\Windows", 'User')
            $scriptBody = (Get-Content -LiteralPath $fixturePath -Raw).Replace(
                '__BATTEST_BIN__', $binPath
            ).Replace('__BATTEST_TEMP__', $tempRoot)
            $runner = Join-Path $tempRoot 'run-path.ps1'
            Set-Content -LiteralPath $runner -Value $scriptBody
            & $runner
            $LASTEXITCODE | Should -Be 0
            $after = [Environment]::GetEnvironmentVariable('Path', 'User')
            $after | Should -Be "$existing;C:\Windows"
            Test-Path -LiteralPath "${tempRoot}_session_path.txt" | Should -BeTrue
        }
        finally {
            [Environment]::SetEnvironmentVariable('Path', $original, 'User')
            Remove-Item -LiteralPath "${tempRoot}_session_path.txt" -Force -ErrorAction SilentlyContinue
            Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
        }
    }

    It 'invokes the fixture and appends the bin directory when it is absent' {
        $fixturePath = Join-Path $script:InstallerPsRoot 'Update-BattestUserPath.ps1'
        $tempRoot = Join-Path $env:TEMP ('battest-path-add-' + [guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Path $tempRoot | Out-Null
        $binPath = Join-Path $tempRoot 'bin'
        $original = [Environment]::GetEnvironmentVariable('Path', 'User')
        try {
            [Environment]::SetEnvironmentVariable('Path', 'C:\Existing', 'User')
            $scriptBody = (Get-Content -LiteralPath $fixturePath -Raw).Replace(
                '__BATTEST_BIN__', $binPath
            ).Replace('__BATTEST_TEMP__', $tempRoot)
            $runner = Join-Path $tempRoot 'run-path.ps1'
            Set-Content -LiteralPath $runner -Value $scriptBody
            & $runner
            $LASTEXITCODE | Should -Be 0
            $after = [Environment]::GetEnvironmentVariable('Path', 'User')
            $after | Should -Be "C:\Existing;$binPath"
        }
        finally {
            [Environment]::SetEnvironmentVariable('Path', $original, 'User')
            Remove-Item -LiteralPath "${tempRoot}_session_path.txt" -Force -ErrorAction SilentlyContinue
            Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

Describe 'Remove-BattestUserPath.ps1' {
    It 'invokes the fixture and removes a case-insensitive trailing-slash PATH segment' {
        $fixturePath = Join-Path $script:InstallerPsRoot 'Remove-BattestUserPath.ps1'
        $tempRoot = Join-Path $env:TEMP ('battest-path-rm-' + [guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Path $tempRoot | Out-Null
        $binPath = Join-Path $tempRoot 'bin'
        $original = [Environment]::GetEnvironmentVariable('Path', 'User')
        try {
            [Environment]::SetEnvironmentVariable('Path', "C:\Alpha;$binPath\;C:\Beta", 'User')
            $scriptBody = (Get-Content -LiteralPath $fixturePath -Raw).Replace(
                '__BATTEST_BIN__', $binPath
            )
            $runner = Join-Path $tempRoot 'run-remove-path.ps1'
            Set-Content -LiteralPath $runner -Value $scriptBody
            & $runner
            $LASTEXITCODE | Should -Be 0
            $after = [Environment]::GetEnvironmentVariable('Path', 'User')
            $after | Should -Be 'C:\Alpha;C:\Beta'
        }
        finally {
            [Environment]::SetEnvironmentVariable('Path', $original, 'User')
            Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

Describe 'Expand-BattestArchive.ps1' {
    It 'extracts the versioned Battest layout and rejects zip-slip entries' {
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $fixturePath = Join-Path $script:InstallerPsRoot 'Expand-BattestArchive.ps1'
        $tempRoot = Join-Path $env:TEMP ('battest-expand-' + [guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Path $tempRoot | Out-Null
        try {
            $okZip = Join-Path $tempRoot 'ok.zip'
            $okArchive = [IO.Compression.ZipFile]::Open($okZip, 'Create')
            try {
                $entry = $okArchive.CreateEntry('Battest-v0.1.0/battest.exe')
                $stream = $entry.Open()
                try {
                    $payload = [Text.Encoding]::ASCII.GetBytes('exe')
                    $stream.Write($payload, 0, $payload.Length)
                }
                finally {
                    $stream.Dispose()
                }
            }
            finally {
                $okArchive.Dispose()
            }
            $okDest = Join-Path $tempRoot 'okdest'
            $okBody = (Get-Content -LiteralPath $fixturePath -Raw).Replace(
                '__BATTEST_TEMP__', $okDest
            ).Replace('__BATTEST_VERSION__', 'v0.1.0')
            $okRunner = Join-Path $tempRoot 'run-ok-expand.ps1'
            Set-Content -LiteralPath $okRunner -Value $okBody
            Copy-Item -LiteralPath $okZip -Destination "$okDest.zip"
            & $okRunner
            $LASTEXITCODE | Should -Be 0
            Test-Path -LiteralPath (Join-Path $okDest 'Battest-v0.1.0\battest.exe') | Should -BeTrue

            $slipZip = Join-Path $tempRoot 'slip.zip'
            $slipArchive = [IO.Compression.ZipFile]::Open($slipZip, 'Create')
            try {
                $entry = $slipArchive.CreateEntry('../evil.exe')
                $stream = $entry.Open()
                try {
                    $payload = [Text.Encoding]::ASCII.GetBytes('evil')
                    $stream.Write($payload, 0, $payload.Length)
                }
                finally {
                    $stream.Dispose()
                }
            }
            finally {
                $slipArchive.Dispose()
            }
            $slipDest = Join-Path $tempRoot 'slipdest'
            $slipBody = (Get-Content -LiteralPath $fixturePath -Raw).Replace(
                '__BATTEST_TEMP__', $slipDest
            ).Replace('__BATTEST_VERSION__', 'v0.1.0')
            $slipRunner = Join-Path $tempRoot 'run-slip-expand.ps1'
            Set-Content -LiteralPath $slipRunner -Value $slipBody
            Copy-Item -LiteralPath $slipZip -Destination "$slipDest.zip"
            & $slipRunner
            $LASTEXITCODE | Should -Be 1
        }
        finally {
            Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}
