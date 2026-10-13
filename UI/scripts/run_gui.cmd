@echo off
rem Usage: run_gui.cmd [--demo | --version | COM3 [9600]]
setlocal
call "%~dp0python_env.cmd"
if errorlevel 1 exit /b 2
pushd "%UI_ROOT%"
"%PY%" -c "import PyQt5, serial" >nul 2>nul
if errorlevel 1 (
    echo [INFO] Installing GUI dependencies...
    "%PY%" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] Dependency installation failed.
        popd
        exit /b 2
    )
)
set "ARG1=%~1"
if "%ARG1%"=="" goto :noargs
if "%ARG1:~0,1%"=="-" goto :options
if "%~2"=="" (
    "%PY%" -B -m sensor_hub --port "%~1"
) else (
    "%PY%" -B -m sensor_hub --port "%~1" --baud "%~2"
)
goto :done
:noargs
"%PY%" -B -m sensor_hub
goto :done
:options
"%PY%" -B -m sensor_hub %*
:done
set "RESULT=%ERRORLEVEL%"
popd
exit /b %RESULT%
