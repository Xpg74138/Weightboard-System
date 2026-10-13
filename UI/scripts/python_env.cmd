@echo off
rem Shared interpreter selection. Call from a launcher inside SETLOCAL.
for %%I in ("%~dp0..") do set "UI_ROOT=%%~fI"
set "PY=python"
if exist "%UI_ROOT%\.venv\Scripts\python.exe" set "PY=%UI_ROOT%\.venv\Scripts\python.exe"
if defined SENSOR_HUB_PYTHON set "PY=%SENSOR_HUB_PYTHON%"
set "PYTHONIOENCODING=utf-8"
"%PY%" --version >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python not found. Install Python or set SENSOR_HUB_PYTHON.
    exit /b 2
)
exit /b 0
