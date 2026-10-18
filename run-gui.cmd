@echo off
setlocal
REM Opens the native Windows app. No WSL or virtualization required.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1" -Gui %*
set "toolkitExit=%ERRORLEVEL%"
if not "%toolkitExit%"=="0" pause
exit /b %toolkitExit%
