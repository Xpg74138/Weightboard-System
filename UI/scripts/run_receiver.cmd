@echo off
rem Usage: run_receiver.cmd COM3 [9600], or run_receiver.cmd --help
setlocal
call "%~dp0python_env.cmd"
if errorlevel 1 exit /b 2
pushd "%UI_ROOT%"
"%PY%" -c "import serial" >nul 2>nul
if errorlevel 1 (
    "%PY%" -m pip install -r requirements.txt
    if errorlevel 1 (
        popd
        exit /b 2
    )
)
set "ARG1=%~1"
if "%ARG1%"=="" goto :help
if "%ARG1:~0,1%"=="-" goto :options
set "BAUD=%~2"
if "%BAUD%"=="" set "BAUD=9600"
if not exist artifacts\logs mkdir artifacts\logs
"%PY%" -B -m tools.receiver --port "%~1" --baud "%BAUD%" --framing line --show-gap -o "artifacts\logs\recv.log"
goto :done
:help
"%PY%" -B -m tools.receiver --help
goto :done
:options
"%PY%" -B -m tools.receiver %*
:done
set "RESULT=%ERRORLEVEL%"
popd
exit /b %RESULT%
