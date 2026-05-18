@echo off
title PZ Save Manager
cd /d "%~dp0"

if not exist ".venv" (
    echo First run -- setting up...
    python -m venv .venv
    call .venv\Scripts\pip install -e . -q
    echo Done!
)

echo Starting PZ Save Manager...
echo Open http://127.0.0.1:8080 in your browser
call .venv\Scripts\python -m pz_save_manager gui
pause
