@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
where py >nul 2>nul
if not errorlevel 1 (
  set "PYRUN=py -3"
) else (
  set "PYRUN=python"
)
echo PICADS Windows dependency audit. No software will be downloaded or installed.
%PYRUN% -m chipcompiler.windows_tool_audit --output validation\PICADS_v0.16.5_tools_diagnostics.zip
set "RESULT=%ERRORLEVEL%"
echo.
echo Please upload: validation\PICADS_v0.16.5_tools_diagnostics.zip
if not "%RESULT%"=="0" echo Audit failed. Copy the console error message into the chat.
pause
exit /b %RESULT%
