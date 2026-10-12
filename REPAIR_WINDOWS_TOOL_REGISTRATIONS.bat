@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
where py >nul 2>nul
if not errorlevel 1 (set "PYRUN=py -3") else (set "PYRUN=python")
echo PICADS - Offline KiCad/OSS CAD Suite tool registration repair
echo No archives will be downloaded; KiCad and OSS CAD Suite will not be reinstalled.
%PYRUN% -m chipcompiler.windows_registration_repair
set "RESULT=%ERRORLEVEL%"
echo.
echo Then run RUN_WINDOWS_TOOL_AUDIT.bat and send its ZIP if anything remains unavailable.
pause
exit /b %RESULT%
