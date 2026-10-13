@echo off
setlocal
cd /d "%~dp0"
set "DISTRO=Ubuntu"
if exist "%~dp0dependencies\librelane\wsl_distribution.txt" (
    set /p DISTRO=<"%~dp0dependencies\librelane\wsl_distribution.txt"
)
if not "%~1"=="" set "DISTRO=%~1"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0CHECK_PHYSICAL_DOCKER_WSL.ps1" -Distribution "%DISTRO%"
echo.
pause
