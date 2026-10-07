@echo off
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
if defined SRC_PYTHON goto run
if exist "toolkit\python.exe" (
    set "SRC_PYTHON=%~dp0toolkit\python.exe"
    goto run
)
if exist "runtime\python.exe" (
    set "SRC_PYTHON=%~dp0runtime\python.exe"
    goto run
)
if exist ".venv\Scripts\python.exe" (
    set "SRC_PYTHON=%~dp0.venv\Scripts\python.exe"
    goto run
)
where python >nul 2>nul
if errorlevel 1 (
    echo Set SRC_PYTHON to an existing SRC Python executable.
    pause
    exit /b 1
)
set "SRC_PYTHON=python"
:run
"%SRC_PYTHON%" "tools\launch_webui.py"
if errorlevel 1 pause
