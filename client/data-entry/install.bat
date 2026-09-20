@echo off
setlocal DisableDelayedExpansion
cd /d "%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
set "install_result=%errorlevel%"
echo.
if not "%install_result%"=="0" echo Installation failed. See the message above and .runtime\install.log.
pause
exit /b %install_result%
