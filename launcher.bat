@echo off
title PZ Save Manager
cd /d "%~dp0"
echo Starting PZ Save Manager...
echo.
echo The web interface will open in your browser.
echo Keep this window open while using the app.
echo.
call .venv\Scripts\python -m pz_save_manager gui --no-browser 2>nul
if %errorlevel% neq 0 (
    echo.
    echo First run detected — installing...
    python -m venv .venv
    call .venv\Scripts\pip install -e . -q
    echo.
    echo Starting PZ Save Manager...
    start http://127.0.0.1:8080
    call .venv\Scripts\python -m pz_save_manager gui --no-browser
)
pause
