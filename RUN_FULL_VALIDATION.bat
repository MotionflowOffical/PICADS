@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src"
echo ============================================================
echo PICADS v0.16.5 - Full automatic verification
 echo This installs Python dependencies if missing, then runs
 echo compiler tests, GUI smoke, generated hardware simulations,
 echo and actual installed EDA tools. It does NOT install EDA/PDKs.
echo The results will be packaged in validation\diagnostics.zip.
echo ============================================================
where py >nul 2>nul
if not errorlevel 1 (
    set "PYCMD=py -3"
) else (
    where python >nul 2>nul
    if errorlevel 1 (
      echo ERROR: Neither Python nor Windows Python launcher exists.
      pause
      exit /b 1
    )
    set "PYCMD=python"
)
%PYCMD% -m chipcompiler.system_validation --install-python-deps --output validation\PICADS_v0.16.5_diagnostics %*
set "RET=%ERRORLEVEL%"
echo.
echo Diagnostic ZIP: validation\PICADS_v0.16.5_diagnostics.zip
echo RETURN CODE: %RET%  ^(0=all requested stages passed, 2=partial/unavailable, 1=failure^)
echo Please send the ZIP back for analysis.
pause
exit /b %RET%
