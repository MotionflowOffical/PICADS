@echo off
setlocal
cd /d "%~dp0"
echo This command will install PySide6, PyYAML, pycparser and pytest into your configured Python environment.
echo It does not create a venv and it does not install any EDA tools.
choice /m "Continue"
if errorlevel 2 exit /b 1
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 -m pip install -e ".[gui,test]"
) else (
  python -m pip install -e ".[gui,test]"
)
if errorlevel 1 (
  echo Installation failed. No fallback used.
  pause
  exit /b 1
)
echo Dependencies installed. Run RUN_GUI.bat.
pause
endlocal
