@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_server.ps1" %*
if errorlevel 1 (
  pause
  exit /b 1
)
endlocal

