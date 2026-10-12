@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src"
set "OUT=validation\PICADS_v0.16.0_automated_diagnostics"
if not exist "validation" mkdir "validation"
if not exist "%OUT%" mkdir "%OUT%"
set "STARTLOG=%OUT%\launcher.log"
echo PICADS v0.16.0 Windows automatic test bootstrap>"%STARTLOG%"
echo Test started: %DATE% %TIME%>>"%STARTLOG%"
echo. 
echo ========================================================
echo PICADS - ONE-COMMAND AUTOMATED FEATURE TESTS
echo Output: %OUT%.zip
echo Work is done on temporary copies, not your projects.
echo ========================================================
where py >nul 2>nul
if not errorlevel 1 (
  set "PY=py -3"
) else (
  where python >nul 2>nul
  if errorlevel 1 (
    echo Python 3 not found. See the diagnostic ZIP.>>"%STARTLOG%"
    echo ERROR: Python 3.10 or later is required.
    call :PYTHON_MISSING
    pause
    exit /b 1
  )
  set "PY=python"
)
%PY% --version >>"%STARTLOG%" 2>&1
%PY% -c "import yaml,pycparser,pytest,PySide6" >nul 2>nul
if errorlevel 1 (
  echo Missing Python test dependencies; attempting user-profile installation.
  echo Attempted user-profile installation of GUI and test packages.>>"%STARTLOG%"
  %PY% -m pip install --user "PyYAML>=6.0" "pycparser>=2.22,<4" "pytest>=8" "PySide6>=6.6" >"%OUT%\python_setup.log" 2>&1
  if errorlevel 1 (
    echo WARNING: Some Python dependencies could not be installed.
    echo Python package installation FAILED; see python_setup.log.>>"%STARTLOG%"
  ) else (
    echo Python dependency installation completed.>>"%STARTLOG%"
  )
) else (
  echo Python test and GUI dependencies already installed.>>"%STARTLOG%"
)
echo.
echo Running automated tests. Native physical checks can take considerable time.
%PY% -m chipcompiler.feature_validation --output "%OUT%" %*
set "RC=%ERRORLEVEL%"
echo.
if exist "%OUT%.zip" (
  echo ========================================================
  echo UPLOAD THIS ONE FILE:
  echo %OUT%.zip
  echo ========================================================
) else (
  echo ERROR: No diagnostics ZIP could be created.
  echo Check the Python installation and the console error above.
)
echo Result code: %RC%  [0=checks passed, 2=partial/unavailable, 1=failed]
echo A PARTIAL result is normal when EDA tools or a PDK are missing.
echo You can also test the GUI manually with RUN_GUI.bat.
pause
exit /b %RC%

:PYTHON_MISSING
rem Windows includes PowerShell on most supported releases; package the startup error
rem so a missing Python installation can still be reported as one ZIP.
where powershell >nul 2>nul
if not errorlevel 1 powershell -NoProfile -Command "Compress-Archive -Path '%OUT%\*' -DestinationPath '%OUT%.zip' -Force" >nul 2>nul
exit /b 0
