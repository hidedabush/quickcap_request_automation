@echo off
REM Launches the QuickCap automation from any terminal (plain Windows
REM PowerShell, PowerShell 7/pwsh, or cmd.exe) -- no venv activation and
REM no PowerShell execution-policy involved, since .bat files aren't
REM subject to it. Works by calling the venv's quickcap.exe directly, by
REM its absolute path, from wherever this file happens to live.
setlocal
set "SCRIPT_DIR=%~dp0"
set "EXE=%SCRIPT_DIR%.venv\Scripts\quickcap.exe"

if not exist "%EXE%" (
    echo quickcap.exe not found at "%EXE%"
    echo Run setup first -- see README.md, "Quick Start" section.
    exit /b 1
)

"%EXE%" %*
exit /b %ERRORLEVEL%
