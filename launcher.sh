#!/usr/bin/env bash
# PZ Save Manager — one-click launcher (Linux/macOS)
set -e
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
    echo "First run — setting up..."
    python3 -m venv .venv
    .venv/bin/pip install -e . -q
    echo "Done!"
fi

echo "Starting PZ Save Manager..."
echo "Open http://127.0.0.1:8080 in your browser"
.venv/bin/python -c "from pz_save_manager.gui import run_gui; run_gui()"
