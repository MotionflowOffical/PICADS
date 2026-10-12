@echo off
setlocal
cd /d "%~dp0"
echo PICADS v0.16.6: launching required v1.0 feature verification only.
call "%~dp0RUN_PICADS_AUTOTEST.bat" %*
exit /b %ERRORLEVEL%
