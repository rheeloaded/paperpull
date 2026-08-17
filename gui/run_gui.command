#!/usr/bin/env bash
# Control panel for the downloader apps (macOS / Linux).
#
# Optional: point it at your existing working copies instead of ../apps:
#     export APPS_ROOT="$HOME/Documents/Receipt and Statement Downloader"
#     ./run_gui.command
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -x ".venv/bin/python" ]; then
    echo "Setting up the GUI virtual environment..."
    python3 -m venv .venv
    .venv/bin/python -m pip install --upgrade pip
    .venv/bin/pip install -r requirements.txt
fi

echo
echo "Opening http://127.0.0.1:8765"
(sleep 2 && open http://127.0.0.1:8765 2>/dev/null || true) &
.venv/bin/python -m uvicorn app:app --port 8765
