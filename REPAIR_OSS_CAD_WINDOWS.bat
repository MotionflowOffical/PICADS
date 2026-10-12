@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src"
echo ========================================================
echo PICADS - OFFLINE OSS CAD SUITE REGISTRATION REPAIR
echo ========================================================
echo This DOES NOT download or extract the 2GB OSS CAD Suite.
echo It reuses dependencies\oss-cad-suite\ and registers real Windows executables.
echo It does not remove or overwrite KiCad or any chip projects.
echo.
where py >nul 2>nul
if not errorlevel 1 (
  set "PYCMD=py -3"
) else (
  where python >nul 2>nul
  if errorlevel 1 (
    echo ERROR: Python not found.
    pause
    exit /b 1
  )
  set "PYCMD=python"
)
%PYCMD% -m chipcompiler dependencies repair oss-cad-suite
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
  echo.
  echo Registration repair failed. Your existing OSS CAD Suite files were preserved.
) else (
  echo.
  echo Registration repair completed. You can now run RUN_PICADS_AUTOTEST.bat.
)
pause
exit /b %RC%
