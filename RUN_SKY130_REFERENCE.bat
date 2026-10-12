@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src"
set "DISTRO=Ubuntu"
if not "%~1"=="" set "DISTRO=%~1"
set "DEMO=%~dp0validation\PICADS_SKY130_DEMO"
echo ================================================================
echo PICADS - REAL SKY130 reference chip via WSL LibreLane
echo Requires: runnable WSL distro, Yosys, Docker + LibreLane.
echo No installation, uninstallation or source replacement occurs.
echo Outputs are written under validation\PICADS_SKY130_DEMO.
echo This is a standard-cell reference, NOT a custom TFT mask.
echo ================================================================
if not exist "%DEMO%" mkdir "%DEMO%"
for %%F in (chip.yaml circuit.py design.mcd architecture.co) do (
  if not exist "%DEMO%\%%F" copy "%~dp0examples\first_physical_chip\%%F" "%DEMO%\%%F" >nul
)
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
echo.
echo [1/3] Enable this COPY of the first-chip demo for SKY130 / WSL %DISTRO% ...
%PYCMD% -m chipcompiler configure-physical "%DEMO%" --wsl-distribution "%DISTRO%" --pdk sky130A
if errorlevel 1 goto fail
echo.
echo [2/3] Checking physical design prerequisites ...
%PYCMD% -m chipcompiler physical-preflight "%DEMO%"
echo.
echo [3/3] Running real Yosys + LibreLane physical implementation ...
%PYCMD% -m chipcompiler physical "%DEMO%"
set "RET=%ERRORLEVEL%"
echo.
echo Build report: %DEMO%\build\latest\report.json
echo Tool logs:    %DEMO%\build\latest\yosys.log
 echo              %DEMO%\build\latest\physical.log
echo If completed, open %DEMO%\build\latest\layout_artifacts.json
pause
exit /b %RET%
:fail
echo.
echo Configuration failed. Source examples have not been overwritten.
pause
exit /b 1
