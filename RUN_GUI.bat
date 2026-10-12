@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
  set "PY=py -3"
) else (
  set "PY=python"
)
set "PYTHONPATH=%~dp0src"
%PY% -c "import yaml,pycparser,PySide6" >nul 2>nul
if errorlevel 1 (
  echo [MISSING DEPENDENCY] PySide6, PyYAML, or pycparser is not available.
  echo Run SETUP_GUI_WINDOWS.bat explicitly to install GUI dependencies.
  pause
  exit /b 2
)
%PY% -m chipcompiler gui "%~dp0examples\alu_slice_component"
if errorlevel 1 pause
endlocal
