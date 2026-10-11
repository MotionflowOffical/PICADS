@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src"
where py >nul 2>nul
if %errorlevel%==0 (py -3 -m pytest -q) else (python -m pytest -q)
if errorlevel 1 (echo TEST FAILURE: Inspect the output above.) else (echo Tests passed.)
pause
endlocal
