@echo off
chcp 65001 >nul 2>&1
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
title PZ Save Manager
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" goto :run

echo First run - setting up virtual environment...
echo.

REM Remove a partial/broken .venv left from a previous failed attempt
if exist ".venv" rmdir /s /q .venv

REM Prefer the py launcher (most reliable on Windows). Fall back to python.
where py >nul 2>&1
if not errorlevel 1 (
    py -3 -m venv .venv
    goto :installed
)
where python >nul 2>&1
if not errorlevel 1 (
    python -m venv .venv
    goto :installed
)

echo ERROR: Python 3.10 or newer was not found on PATH.
echo Install it from https://www.python.org/downloads/
echo Make sure to check "Add Python to PATH" during installation.
echo.
pause
exit /b 1

:installed
if not exist ".venv\Scripts\python.exe" (
    echo ERROR: Failed to create the virtual environment.
    echo If "python" opened the Microsoft Store, install Python from
    echo https://www.python.org/downloads/ instead and try again.
    echo.
    pause
    exit /b 1
)

call .venv\Scripts\python -m pip install -e . -q
echo Done!
echo.

:run
echo Starting PZ Save Manager...
echo Open http://127.0.0.1:8080 in your browser
echo.
call .venv\Scripts\pz-saves gui
pause
