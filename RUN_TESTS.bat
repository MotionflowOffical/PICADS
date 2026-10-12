@echo off
setlocal
cd /d "%~dp0"
echo PICADS v0.16.2: launching feature and extended regression tests.
call "%~dp0RUN_PICADS_AUTOTEST.bat" --full-regression --skip-native
exit /b %ERRORLEVEL%
