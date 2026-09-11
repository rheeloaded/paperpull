#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

echo "=== PG&E Documents setup ==="

PY3="$(command -v python3 || true)"
if [ -z "$PY3" ]; then
    echo "Python 3 was not found. Install it from https://www.python.org/downloads/"
    echo "or with Homebrew:  brew install python"
    exit 1
fi
echo "Using Python: $PY3"

"$PY3" -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

if [ -f "../../core/pyproject.toml" ]; then
    .venv/bin/pip install -e ../../core
else
    .venv/bin/pip install core/paperpull_core-*.whl
fi

echo
echo "Setup complete. Next step: ./login.command and sign in to PG&E Documents."
