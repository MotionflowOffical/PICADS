@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src"
where py >nul 2>nul
if not errorlevel 1 (
  set "PYCMD=py -3"
) else (
  set "PYCMD=python"
)
echo PICADS 0.16.6 - global source shared operator validation
%PYCMD% -m chipcompiler.global_validation --output validation\PICADS_v0.16.6_global_diagnostics %*
set "RET=%ERRORLEVEL%"
echo Diagnostics: validation\PICADS_v0.16.6_global_diagnostics.zip
echo Status: %RET%  ^(0=PASS; 2=PARTIAL missing native tools; 1=FAIL^)
pause
exit /b %RET%
