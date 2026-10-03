@echo off
setlocal DisableDelayedExpansion
cd /d "%~dp0"
set "PYTHONHOME="
set "PYTHONPATH="
set "PYTHONNOUSERSITE=1"
if not exist "%~dp0.venv\Scripts\python.exe" (
    echo Please run install.bat first.
    pause
    exit /b 1
)
"%~dp0.venv\Scripts\python.exe" -u "%~dp0webview_app.py"
set "app_result=%errorlevel%"
if not "%app_result%"=="0" (
    echo.
    echo Startup failed. Check the error above. Run install.bat to repair dependencies.
    pause
)
exit /b %app_result%
