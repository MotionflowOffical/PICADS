@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src"
echo ===========================================================
echo PICADS - LibreLane WSL backend diagnostic (read-only)
echo Checks the previously installed Ubuntu backend; no setup.
echo ===========================================================
where py >nul 2>nul
if not errorlevel 1 (
  py -3 -m chipcompiler dependencies wsl-status
) else (
  python -m chipcompiler dependencies wsl-status
)
echo.
echo Status READY means the local WSL tools are reachable now.
echo Projects still need tools.execution: wsl and wsl_distribution: Ubuntu.
pause
