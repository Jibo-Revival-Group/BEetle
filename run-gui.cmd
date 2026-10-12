@echo off
setlocal
REM Uses the existing WSL2 / usbipd helper. No native Windows DFU backend.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1" -Gui %*
set "toolkitExit=%ERRORLEVEL%"
if not "%toolkitExit%"=="0" pause
exit /b %toolkitExit%
