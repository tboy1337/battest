@echo off
setlocal enabledelayedexpansion

REM ============================================================================
REM battest Installer/Updater
REM Purpose: Download and install the latest battest release to %LOCALAPPDATA%
REM Author: tboy1337
REM Repository: https://github.com/tboy1337/battest
REM ============================================================================

REM Attempt to change to system drive to avoid issues with current directory/drive
cd /d "%SystemDrive%" >nul 2>&1
if %errorlevel% neq 0 (
    echo Failed to change to %SystemDrive%. Error code: %errorlevel%
)

REM Check if running as administrator (script should run as normal user)
net session >nul 2>&1
if %errorlevel% equ 0 (
    echo ERROR: This script is intended to be run as a user. Please run without administrator privileges.
    goto :error_exit
)

REM Check if curl is installed
where curl >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Curl is not installed or in PATH.
    goto :error_exit
)

echo +===========================+
echo + battest Installer/Updater +
echo +===========================+
echo.

set BATTEST_DIR=%LOCALAPPDATA%\Programs\battest
set BATTEST_BIN=%BATTEST_DIR%\bin
set BATTEST_RELEASE_FILE=%BATTEST_DIR%\installed_release.txt
set BATTEST_TEMP=%TEMP%\battest_install_%RANDOM%_%RANDOM%
set BATTEST_BACKUP=%TEMP%\battest_backup_%RANDOM%_%RANDOM%
set /a MIN_DOWNLOAD_BYTES=500*1000

REM Detect latest battest version and download URL from GitHub API
set BATTEST_URL=
set BATTEST_VERSION=
set "PS_GET_RELEASE=%BATTEST_TEMP%_get_release.ps1"

call :write_get_release_script
for /f "tokens=1,2,3" %%a in ('powershell -NoProfile -ExecutionPolicy Bypass -File "%PS_GET_RELEASE%" 2^>nul') do (
    set BATTEST_URL=%%a
    set BATTEST_VERSION=%%b
    set BATTEST_DIGEST=%%c
)
if exist "!PS_GET_RELEASE!" del /F /Q "!PS_GET_RELEASE!" >nul 2>&1

if "!BATTEST_URL!"=="NO_DIGEST" (
    echo ERROR: GitHub release asset is missing a SHA-256 digest.
    echo.
    echo Cannot verify the download. Please try again later.
    goto :error_exit
)

if "!BATTEST_URL!"=="NOT_FOUND" (
    echo ERROR: Failed to find Windows download URL from GitHub API.
    echo.
    echo Please check your internet connection and try again.
    goto :error_exit
)

if "!BATTEST_URL!"=="" (
    echo ERROR: Failed to detect latest battest version.
    echo.
    echo Please check your internet connection and try again.
    goto :error_exit
)

if "!BATTEST_VERSION!"=="" (
    echo ERROR: Failed to parse battest version from GitHub API response.
    echo.
    echo Cannot proceed with installation.
    goto :error_exit
)

if "!BATTEST_DIGEST!"=="" (
    echo ERROR: Failed to parse SHA-256 digest from GitHub API response.
    echo.
    echo Cannot verify the download. Cannot proceed with installation.
    goto :error_exit
)

echo Latest battest release: !BATTEST_VERSION!
echo.

REM Create installation directory if it does not exist
if not exist "%BATTEST_BIN%" (
    mkdir "%BATTEST_BIN%" >nul 2>&1
    if !errorlevel! neq 0 (
        echo ERROR: Failed to create installation directory: %BATTEST_BIN%
        echo Error code: !errorlevel!
        goto :error_exit
    )
)

REM Check current installation
set CURRENT_VERSION=
set NEEDS_BACKUP=0

if exist "%BATTEST_BIN%\battest.exe" (
    set "VERSION_TEMP=%TEMP%\battest_version_%RANDOM%_%RANDOM%.txt"
    "%BATTEST_BIN%\battest.exe" --version > "!VERSION_TEMP!" 2>&1
    if !errorlevel! equ 0 (
        for /f "usebackq tokens=*" %%v in ("!VERSION_TEMP!") do set CURRENT_VERSION=%%v
        del /F /Q "!VERSION_TEMP!" >nul 2>&1
        if not "!CURRENT_VERSION!"=="" (
            echo Current installed version: !CURRENT_VERSION!
            echo.
        )
    ) else (
        if exist "!VERSION_TEMP!" del /F /Q "!VERSION_TEMP!" >nul 2>&1
    )
)

if exist "%BATTEST_RELEASE_FILE%" (
    REM LINT:IGNORE SEC001
    set /p INSTALLED_RELEASE=<"%BATTEST_RELEASE_FILE%"
    if not "!INSTALLED_RELEASE!"=="" (
        if /i not "!INSTALLED_RELEASE:~0,1!"=="v" set "INSTALLED_RELEASE="
    )
    if "!INSTALLED_RELEASE!"=="!BATTEST_VERSION!" (
        echo battest !BATTEST_VERSION! is already installed and up to date.
        goto :end
    )
    if exist "%BATTEST_BIN%\battest.exe" (
        echo Upgrading from !INSTALLED_RELEASE! to !BATTEST_VERSION!...
        echo.
        set NEEDS_BACKUP=1
    )
) else if exist "%BATTEST_BIN%\battest.exe" (
    echo Existing installation found without release marker.
    echo.
    echo Upgrading to !BATTEST_VERSION!...
    echo.
    set NEEDS_BACKUP=1
) else (
    echo No existing installation found.
    echo.
    echo Installing battest !BATTEST_VERSION!...
    echo.
)

REM Backup existing installation if upgrading
if !NEEDS_BACKUP! equ 1 (
    echo Creating backup of existing installation...
    echo.
    mkdir "%BATTEST_BACKUP%" >nul 2>&1
    if exist "%BATTEST_BIN%\battest.exe" copy /Y "%BATTEST_BIN%\battest.exe" "%BATTEST_BACKUP%\" >nul 2>&1
    if exist "%BATTEST_RELEASE_FILE%" copy /Y "%BATTEST_RELEASE_FILE%" "%BATTEST_BACKUP%\" >nul 2>&1

    if exist "%BATTEST_BIN%\battest.exe" del /F /Q "%BATTEST_BIN%\battest.exe" >nul 2>&1
)

REM Download battest
echo Downloading battest !BATTEST_VERSION! from:
echo !BATTEST_URL!
echo.
curl -L -f --progress-bar -o "%BATTEST_TEMP%.zip" "!BATTEST_URL!" 2>&1
if !errorlevel! neq 0 (
    echo.
    echo ERROR: Failed to download battest. Error code: !errorlevel!
    echo.
    echo This could be due to:
    echo - Network connectivity issues
    echo - Invalid download URL
    goto :error_restore
)

REM Validate downloaded file exists and has content
if not exist "%BATTEST_TEMP%.zip" (
    echo ERROR: Downloaded file not found at %BATTEST_TEMP%.zip
    goto :error_restore
)

set FILESIZE=0
set "PS_FILE_SIZE=%BATTEST_TEMP%_file_size.ps1"
call :write_file_size_script
for /f "delims=" %%S in ('powershell -NoProfile -ExecutionPolicy Bypass -File "!PS_FILE_SIZE!" 2^>nul') do (
    set FILESIZE=%%S
)
if exist "!PS_FILE_SIZE!" del /F /Q "!PS_FILE_SIZE!" >nul 2>&1

if !FILESIZE! lss !MIN_DOWNLOAD_BYTES! (
    echo ERROR: Downloaded file is too small ^(!FILESIZE! bytes^). Download may be corrupted.
    goto :error_restore
)

REM Verify SHA-256 digest published by GitHub for this release asset
echo.
echo Verifying SHA-256 digest...
echo.
set "PS_HASH=%BATTEST_TEMP%_hash.ps1"
call :write_hash_script
powershell -NoProfile -ExecutionPolicy Bypass -File "!PS_HASH!" 2>&1
if !errorlevel! neq 0 (
    echo ERROR: SHA-256 verification failed.
    goto :error_restore
)
if exist "!PS_HASH!" del /F /Q "!PS_HASH!" >nul 2>&1

REM Extract battest
echo.
echo Extracting battest...
echo.
set "PS_EXPAND=%BATTEST_TEMP%_expand.ps1"
call :write_expand_script
powershell -NoProfile -ExecutionPolicy Bypass -File "!PS_EXPAND!" 2>&1
if !errorlevel! neq 0 (
    echo ERROR: Failed to extract battest archive. Error code: !errorlevel!
    goto :error_restore
)
if exist "!PS_EXPAND!" del /F /Q "!PS_EXPAND!" >nul 2>&1

REM Locate extracted executable
set BATTEST_SOURCE_EXE=
set "BATTEST_SOURCE_EXE=%BATTEST_TEMP%\Battest-!BATTEST_VERSION!\battest.exe"
if not exist "!BATTEST_SOURCE_EXE!" (
    set BATTEST_SOURCE_EXE=
    for /f "tokens=*" %%f in ('dir /s /b "%BATTEST_TEMP%\battest.exe" 2^>nul') do (
        set BATTEST_SOURCE_EXE=%%f
        goto :found_exe
    )
)

if "!BATTEST_SOURCE_EXE!"=="" (
    echo ERROR: battest executable not found in extracted archive.
    echo.
    echo Expected layout: Battest-!BATTEST_VERSION!\battest.exe
    echo The archive structure may have changed or be corrupted.
    goto :error_restore
)

REM Resume install after executable path is resolved
:found_exe

REM Install battest executable
echo Installing battest executable...
echo.
copy /Y "!BATTEST_SOURCE_EXE!" "%BATTEST_BIN%\battest.exe" >nul 2>&1
if !errorlevel! neq 0 (
    echo ERROR: Failed to install battest.exe. Error code: !errorlevel!
    echo.
    echo Installation failed. Check if files are in use or if you have write permissions.
    goto :error_restore
)
echo Installed battest.exe

REM Verify installation
echo.
echo Verifying installation...
echo.
if not exist "%BATTEST_BIN%\battest.exe" (
    echo ERROR: battest.exe not found after installation at %BATTEST_BIN%\battest.exe
    goto :error_restore
)

"%BATTEST_BIN%\battest.exe" --version 2>&1
if !errorlevel! neq 0 (
    echo ERROR: battest.exe failed to execute. Error code: !errorlevel!
    goto :error_restore
)

REM Write release marker
echo !BATTEST_VERSION!> "%BATTEST_RELEASE_FILE%"
if !errorlevel! neq 0 (
    echo WARNING: Failed to write release marker at %BATTEST_RELEASE_FILE%
    echo.
)

REM Update PATH environment variable
echo.
echo Updating PATH environment variable...
echo.
set "PS_UPDATE_PATH=%BATTEST_TEMP%_update_path.ps1"
call :write_update_path_script
powershell -NoProfile -ExecutionPolicy Bypass -File "!PS_UPDATE_PATH!" 2>&1
if !errorlevel! neq 0 (
    echo WARNING: Failed to update User PATH environment variable.
    echo You may need to manually add %BATTEST_BIN% to your PATH.
    echo.
)
if exist "!PS_UPDATE_PATH!" del /F /Q "!PS_UPDATE_PATH!" >nul 2>&1

REM Update PATH for current session
set "PATH=%PATH%;%BATTEST_BIN%"

REM Success! Clean up temporary files and backup
call :cleanup
REM LINT:IGNORE SEC003
if exist "%BATTEST_BACKUP%" rmdir /S /Q "%BATTEST_BACKUP%" >nul 2>&1

echo.
echo +============================================================+
echo + SUCCESS: battest !BATTEST_VERSION! installed successfully! +
echo +============================================================+
echo.
echo Installation directory: %BATTEST_BIN%
echo.
echo Note: You may need to restart your terminal or IDE to use battest commands.
echo In the current session, battest commands should already be available.
echo.
goto :end

REM Write PowerShell script to fetch latest release URL, tag, and digest
:write_get_release_script
(
echo $tls = [Net.SecurityProtocolType]::Tls12
echo [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor $tls
echo $headers = @{ 'User-Agent' = 'battest-installer'; 'Accept' = 'application/vnd.github+json' }
echo $uri = 'https://api.github.com/repos/tboy1337/battest/releases?per_page=100'
echo $releases = Invoke-RestMethod -Uri $uri -Headers $headers
echo $release = $releases ^| Where-Object { -not $_.prerelease -and -not $_.draft } ^| Select-Object -First 1
echo if (-not $release^) { Write-Output 'NOT_FOUND'; exit 0 }
echo $asset = $release.assets ^| Where-Object { $_.name -like 'Battest-v*.zip' } ^| Select-Object -First 1
echo if (-not $asset^) { Write-Output 'NOT_FOUND'; exit 0 }
echo $digest = $null
echo if ($asset.PSObject.Properties['digest'] -and $asset.digest^) { $digest = [string]$asset.digest }
echo if (-not $digest^) { Write-Output 'NO_DIGEST'; exit 0 }
echo $line = $asset.browser_download_url + ' ' + $release.tag_name + ' ' + $digest
echo Write-Output $line
) > "!PS_GET_RELEASE!"
exit /b 0

REM Write PowerShell script to verify the GitHub SHA-256 digest
:write_hash_script
(
echo $expected = $env:BATTEST_DIGEST
echo $path = '%BATTEST_TEMP%.zip'
echo if (-not $expected^) {
echo Write-Host 'ERROR: GitHub asset digest is missing.'
echo exit 1
echo }
echo $prefix = 'sha256:'
echo if (-not $expected.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase^)^) {
echo Write-Host "ERROR: GitHub asset digest is not SHA-256: $expected"
echo exit 1
echo }
echo $hex = $expected.Substring($prefix.Length^)
echo if ($hex.Length -ne 64^) {
echo Write-Host 'ERROR: GitHub SHA-256 digest has unexpected length.'
echo exit 1
echo }
echo foreach ($ch in $hex.ToCharArray(^)^) {
echo if ($ch -notmatch '[0-9a-fA-F]'^) {
echo Write-Host 'ERROR: GitHub SHA-256 digest is not hexadecimal.'
echo exit 1
echo }
echo }
echo try {
echo $actual = (Get-FileHash -LiteralPath $path -Algorithm SHA256^).Hash.ToLowerInvariant(^)
echo }
echo catch {
echo Write-Host "ERROR: $_"
echo exit 1
echo }
echo if ($actual -ne $hex.ToLowerInvariant(^)^) {
echo Write-Host "ERROR: SHA-256 mismatch (expected $hex, got $actual^)."
echo exit 1
echo }
echo Write-Host 'SHA-256 digest verified'
echo exit 0
) > "!PS_HASH!"
exit /b 0

REM Write PowerShell script to return downloaded archive size in bytes
:write_file_size_script
(
echo $item = Get-Item -LiteralPath '%BATTEST_TEMP%.zip' -ErrorAction Stop
echo Write-Output $item.Length
) > "!PS_FILE_SIZE!"
exit /b 0

REM Write PowerShell script to expand the downloaded archive
:write_expand_script
(
echo try {
echo Expand-Archive -LiteralPath '%BATTEST_TEMP%.zip' -DestinationPath '%BATTEST_TEMP%' -Force
echo exit 0
echo }
echo catch {
echo Write-Host "ERROR: $_"
echo exit 1
echo }
) > "!PS_EXPAND!"
exit /b 0

REM Write PowerShell script to add battest bin directory to user PATH
:write_update_path_script
(
echo try {
echo $binPath = '%BATTEST_BIN%'
echo $path = [Environment]::GetEnvironmentVariable('Path', 'User'^)
echo if (-not $path^) { $path = '' }
echo $segments = $path -split ';' ^| Where-Object { $_ -ne '' }
echo if ($segments -notcontains $binPath^) {
echo if (-not $path^) { $newPath = $binPath } else { $newPath = $path.TrimEnd(';'^) + ';' + $binPath }
echo [Environment]::SetEnvironmentVariable('Path', $newPath, 'User'^)
echo Write-Host 'battest added to User PATH permanently'
echo }
echo else {
echo Write-Host 'battest already in User PATH'
echo }
echo exit 0
echo }
echo catch {
echo Write-Host "ERROR: $_"
echo exit 1
echo }
) > "!PS_UPDATE_PATH!"
exit /b 0

REM Subroutine: remove temporary install files and helper scripts
:cleanup
if exist "%BATTEST_TEMP%.zip" del /F /Q "%BATTEST_TEMP%.zip" >nul 2>&1
REM LINT:IGNORE SEC003
if exist "%BATTEST_TEMP%" rmdir /S /Q "%BATTEST_TEMP%" >nul 2>&1
if exist "%BATTEST_TEMP%_get_release.ps1" del /F /Q "%BATTEST_TEMP%_get_release.ps1" >nul 2>&1
if exist "%BATTEST_TEMP%_file_size.ps1" del /F /Q "%BATTEST_TEMP%_file_size.ps1" >nul 2>&1
if exist "%BATTEST_TEMP%_hash.ps1" del /F /Q "%BATTEST_TEMP%_hash.ps1" >nul 2>&1
if exist "%BATTEST_TEMP%_expand.ps1" del /F /Q "%BATTEST_TEMP%_expand.ps1" >nul 2>&1
if exist "%BATTEST_TEMP%_update_path.ps1" del /F /Q "%BATTEST_TEMP%_update_path.ps1" >nul 2>&1
exit /b 0

REM Restore previous installation after a failed upgrade, then clean up
:error_restore
if !NEEDS_BACKUP! equ 1 (
    if exist "%BATTEST_BACKUP%" (
        echo.
        echo Attempting to restore previous installation...
        if exist "%BATTEST_BACKUP%\battest.exe" (
            copy /Y "%BATTEST_BACKUP%\battest.exe" "%BATTEST_BIN%\" >nul 2>&1
            if !errorlevel! neq 0 (
                echo WARNING: Failed to restore battest.exe from backup.
            )
        )
        if exist "%BATTEST_BACKUP%\installed_release.txt" (
            copy /Y "%BATTEST_BACKUP%\installed_release.txt" "%BATTEST_DIR%\" >nul 2>&1
            if !errorlevel! neq 0 (
                echo WARNING: Failed to restore installed_release.txt from backup.
            )
        )
        echo Previous installation restored.
        echo.
    )
)
call :cleanup
REM LINT:IGNORE SEC003
if exist "%BATTEST_BACKUP%" rmdir /S /Q "%BATTEST_BACKUP%" >nul 2>&1
goto :error_exit

REM Print failure message and exit with error code
:error_exit
echo.
echo +========================================================+
echo + Installation failed. Please review the errors above. +
echo +========================================================+
echo.
echo For help, visit: https://github.com/tboy1337/battest/issues
echo.
timeout /t 5 /nobreak
endlocal
exit /b 1

REM Successful completion
:end
endlocal
exit /b 0
