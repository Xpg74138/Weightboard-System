@echo off
rem Usage: run_gui_debug.cmd [--demo | COM3 [9600]]
setlocal
call "%~dp0python_env.cmd"
if errorlevel 1 exit /b 2
pushd "%UI_ROOT%"
if not exist artifacts\logs mkdir artifacts\logs
set "ARG1=%~1"
if "%ARG1%"=="" goto :noargs
if "%ARG1:~0,1%"=="-" goto :options
if "%~2"=="" (
    call "%~dp0run_gui.cmd" --port "%~1" --parse-log "artifacts\logs\parse_debug.log"
) else (
    call "%~dp0run_gui.cmd" --port "%~1" --baud "%~2" --parse-log "artifacts\logs\parse_debug.log"
)
goto :done
:noargs
call "%~dp0run_gui.cmd" --parse-log "artifacts\logs\parse_debug.log"
goto :done
:options
call "%~dp0run_gui.cmd" --parse-log "artifacts\logs\parse_debug.log" %*
:done
set "RESULT=%ERRORLEVEL%"
popd
exit /b %RESULT%
