#!/usr/bin/env bash
# PaperPull - one-shot setup (macOS / Linux)
#
# Creates a virtual environment for every app plus the GUI, installs the
# shared core into each, and downloads Playwright's Chromium once (it is then
# shared by all of them). This takes a few minutes the first time.
set -uo pipefail
cd "$(dirname "$0")"

echo "============================================================"
echo " PaperPull - one-shot setup"
echo "============================================================"
echo

if ! command -v python3 >/dev/null 2>&1; then
    echo "Python 3 was not found."
    echo "Install it from https://www.python.org/downloads/ or with Homebrew:"
    echo "    brew install python"
    exit 1
fi
echo "Using Python: $(python3 --version) at $(command -v python3)"
echo

# A plain string, not an array: macOS still ships bash 3.2, where
# ${#arr[@]} on an EMPTY array trips "unbound variable" under set -u.
failed=""
first=1

for app in apps/*/; do
    name="$(basename "$app")"
    [ -f "$app/requirements.txt" ] || continue
    printf '  %-14s ' "$name"

    # Reuse an existing environment. Rebuilding one that is in use fails,
    # and re-running setup should be safe.
    if [ ! -x "$app/.venv/bin/python" ]; then
        if ! python3 -m venv "$app/.venv" >/dev/null 2>&1; then
            echo "FAILED (venv)"; failed="$failed $name"; continue
        fi
    fi
    if ! "$app/.venv/bin/pip" install -q -r "$app/requirements.txt" >/dev/null 2>&1; then
        echo "FAILED (requirements)"; failed="$failed $name"; continue
    fi
    if ! "$app/.venv/bin/pip" install -q -e core >/dev/null 2>&1; then
        echo "FAILED (core)"; failed="$failed $name"; continue
    fi
    # Chromium is downloaded once and reused by every later app.
    if [ $first -eq 1 ]; then
        "$app/.venv/bin/python" -m playwright install chromium >/dev/null 2>&1 && first=0
    fi
    echo "ok"
done

echo
printf '  %-14s ' "gui"
if { [ -x gui/.venv/bin/python ] || python3 -m venv gui/.venv >/dev/null 2>&1; } &&
   gui/.venv/bin/pip install -q -r gui/requirements.txt >/dev/null 2>&1; then
    echo "ok"
else
    echo "FAILED"; failed="$failed gui"
fi

chmod +x apps/*/*.command gui/*.command 2>/dev/null || true

echo
if [ -z "$failed" ]; then
    echo "All set. Next: open an app folder and run ./login.command,"
    echo "or start the control panel with gui/run_gui.command"
else
    echo "Finished, but these need a look:$failed"
    echo "Run that app's ./setup.command on its own to see the error."
fi
