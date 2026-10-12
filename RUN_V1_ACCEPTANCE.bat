@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src"
echo =============================================================
echo PICADS v0.16.6 - Original v1.0 workflow acceptance
 echo Source -> DLS -> RTL -> Yosys -> LibreLane -> GDS evidence
 echo Optional PySide6 GUI smoke test. Actual installed tools only.
echo No signoff result is invented; PDK qualification is separate.
echo =============================================================
where py >nul 2>nul
if not errorlevel 1 (
  set "PYCMD=py -3"
) else (
  where python >nul 2>nul
  if errorlevel 1 (
    echo ERROR: Python is not installed.
    pause
    exit /b 1
  )
  set "PYCMD=python"
)
%PYCMD% -m chipcompiler.acceptance --output validation\PICADS_v0.16.6_v1_acceptance %*
set "RET=%ERRORLEVEL%"
echo.
echo SEND THIS FILE: validation\PICADS_v0.16.6_v1_acceptance.zip
 echo EXIT STATUS: %RET%  ^(0=stages tested, 2=partial dependencies, 1=failure^)
pause
exit /b %RET%
