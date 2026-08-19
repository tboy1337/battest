@echo off
setlocal enabledelayedexpansion

REM ============================================================================
REM battest Uninstaller
REM Purpose: Remove battest from %LOCALAPPDATA% and user PATH
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

set BATTEST_DIR=%LOCALAPPDATA%\Programs\battest
set BATTEST_BIN=%BATTEST_DIR%\bin
set BATTEST_RELEASE_FILE=%BATTEST_DIR%\installed_release.txt
set BATTEST_TEMP=%TEMP%\battest_uninstall_%RANDOM%_%RANDOM%
set REMOVAL_FAILED=0

echo +=====================+
echo + battest Uninstaller +
echo +=====================+
echo.

REM Check if battest is installed
if not exist "%BATTEST_BIN%" (
    echo battest installation not found at: %BATTEST_BIN%
    echo.
    echo Nothing to uninstall.
    goto :end
)

if not exist "%BATTEST_BIN%\battest.exe" (
    if not exist "%BATTEST_RELEASE_FILE%" (
        echo battest installation not found at: %BATTEST_BIN%
        echo.
        echo Nothing to uninstall.
        goto :end
    )
)

REM Display current version if available
if exist "%BATTEST_BIN%\battest.exe" (
    echo Current installed version:
    "%BATTEST_BIN%\battest.exe" --version 2>nul
    echo.
)

if exist "%BATTEST_RELEASE_FILE%" (
    REM LINT:IGNORE SEC001
    set /p INSTALLED_RELEASE=<"%BATTEST_RELEASE_FILE%"
    if not "!INSTALLED_RELEASE!"=="" (
        if /i not "!INSTALLED_RELEASE:~0,1!"=="v" set "INSTALLED_RELEASE="
    )
    if not "!INSTALLED_RELEASE!"=="" (
        echo Installed release: !INSTALLED_RELEASE!
        echo.
    )
)

echo Removing battest from: %BATTEST_DIR%
echo.

REM Terminate running battest processes before file removal
echo.
echo Checking for running battest processes...
echo.

set PROCESSES_KILLED=0
set "PS_KILL=%BATTEST_TEMP%_kill.ps1"
call :write_kill_script
powershell -NoProfile -ExecutionPolicy Bypass -File "!PS_KILL!"
if !errorlevel! equ 0 (
    echo Terminated battest.exe in %BATTEST_BIN%
    set PROCESSES_KILLED=1
) else if !errorlevel! equ 2 (
    echo No running battest processes found for %BATTEST_BIN%\battest.exe
) else (
    echo WARNING: Failed to terminate %BATTEST_BIN%\battest.exe
)
if exist "!PS_KILL!" del /F /Q "!PS_KILL!" >nul 2>&1

if !PROCESSES_KILLED! equ 1 (
    echo.
    echo Waiting for processes to fully terminate...
    timeout /t 2 /nobreak >nul 2>&1
    echo.
)

REM Remove battest executables and release marker
echo Removing battest files...
echo.

set REMOVAL_FAILED=0
if exist "%BATTEST_BIN%\battest.exe" (
    del /F /Q "%BATTEST_BIN%\battest.exe" >nul 2>&1
    if !errorlevel! equ 0 (
        echo Removed battest.exe
    ) else (
        echo ERROR: Failed to remove battest.exe. Error code: !errorlevel!
        set REMOVAL_FAILED=1
    )
)

if exist "%BATTEST_RELEASE_FILE%" (
    del /F /Q "%BATTEST_RELEASE_FILE%" >nul 2>&1
    if !errorlevel! equ 0 (
        echo Removed installed_release.txt
    ) else (
        echo ERROR: Failed to remove installed_release.txt. Error code: !errorlevel!
        set REMOVAL_FAILED=1
    )
)

if !REMOVAL_FAILED! equ 1 (
    echo.
    echo WARNING: Some files could not be removed.
    echo This may be because they are still in use or protected.
    echo.
)

REM Remove battest from PATH
echo.
echo Removing battest from User PATH...
echo.
set "PS_REMOVE_PATH=%BATTEST_TEMP%_remove_path.ps1"
call :write_remove_path_script
powershell -NoProfile -ExecutionPolicy Bypass -File "!PS_REMOVE_PATH!" 2>&1
if !errorlevel! neq 0 (
    echo WARNING: Failed to remove battest from User PATH.
    echo You may need to manually remove it from your environment variables.
    echo.
)
if exist "!PS_REMOVE_PATH!" del /F /Q "!PS_REMOVE_PATH!" >nul 2>&1

REM Remove battest installation directory after file and PATH cleanup
echo.
echo Removing battest installation directory...
echo.
if exist "%BATTEST_DIR%" (
    REM LINT:IGNORE SEC003
    rmdir /S /Q "%BATTEST_DIR%" >nul 2>&1
    if !errorlevel! equ 0 (
        echo Installation directory removed: %BATTEST_DIR%
        echo.
    ) else (
        echo WARNING: Failed to remove installation directory. Error code: !errorlevel!
        echo.
        echo This may be because files are in use or protected.
        echo You can manually delete: %BATTEST_DIR%
        echo.
        set REMOVAL_FAILED=1
    )
)

REM Display final status
echo.
if !REMOVAL_FAILED! equ 1 (
    echo +========================================+
    echo + Uninstallation completed with warnings +
    echo +========================================+
    echo.
    echo Some files or directories could not be removed.
    echo Please review the warnings above and take manual action if needed.
) else (
    echo +============================================+
    echo + SUCCESS: battest uninstalled successfully! +
    echo +============================================+
)
echo.
echo Note: You may need to restart your terminal or IDE for PATH changes to take effect.
echo.
goto :end

REM Write powershell script to stop battest.exe only when it is the installed path
:write_kill_script
(
echo try {
echo $target = '%BATTEST_BIN%\battest.exe'
echo $procs = Get-Process -Name battest -ErrorAction SilentlyContinue ^|
echo     Where-Object { $_.Path -and ($_.Path -ieq $target^) }
echo if (-not $procs^) { exit 2 }
echo $procs ^| Stop-Process -Force
echo exit 0
echo }
echo catch {
echo Write-Host "ERROR: $_"
echo exit 1
echo }
) > "!PS_KILL!"
exit /b 0

REM Write powershell script to remove battest bin directory from user PATH
:write_remove_path_script
(
echo try {
echo $binPath = '%BATTEST_BIN%'
echo $path = [Environment]::GetEnvironmentVariable('Path', 'User'^)
echo if (-not $path^) { Write-Host 'User PATH is empty'; exit 0 }
echo $segments = @($path -split ';' ^| Where-Object { $_ -ne '' }^)
echo $normalizedBin = $binPath.TrimEnd('\'^)
echo $cmp = [System.StringComparison]::OrdinalIgnoreCase
echo $pathArray = @($segments ^| Where-Object { -not [string]::Equals($_.TrimEnd('\'^), $normalizedBin, $cmp^) }^)
echo if ($pathArray.Count -ne $segments.Count^) {
echo $newPath = $pathArray -join ';'
echo [Environment]::SetEnvironmentVariable('Path', $newPath, 'User'^)
echo Write-Host 'battest removed from User PATH'
echo }
echo else {
echo Write-Host 'battest not found in User PATH'
echo }
echo exit 0
echo }
echo catch {
echo Write-Host "ERROR: $_"
echo exit 1
echo }
) > "!PS_REMOVE_PATH!"
exit /b 0

REM Print failure message and exit with error code
:error_exit
echo.
echo +==========================================================+
echo + Uninstallation failed. Please review the errors above. +
echo +==========================================================+
echo.
timeout /t 5 /nobreak
endlocal
exit /b 1

REM Successful completion or removal warnings
:end
if %REMOVAL_FAILED% equ 1 (
    endlocal
    exit /b 1
)
endlocal
exit /b 0
