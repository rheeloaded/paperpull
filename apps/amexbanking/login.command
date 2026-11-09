#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

CFG=""
if [ "${1:-}" != "" ]; then CFG="--config config.$1.json"; fi

PY=.venv/bin/python
if [ ! -x "$PY" ]; then
    PY=../../gui/.venv/bin/python
    if [ ! -x "$PY" ] || ! "$PY" -c 'import importlib.util as u, sys; sys.exit(not all(map(u.find_spec, ["paperpull_core", "playwright", "pypdf"])))' >/dev/null 2>&1; then
        if [ -f ../../setup-all.command ]; then
            echo "This app is not set up yet. Run setup-all.command in the PaperPull folder first."
        else
            echo "This app is not set up yet - run ./setup.command first."
        fi
        exit 1
    fi
fi

echo '============================================================'
echo 'American Express Banking - sign in'
echo '============================================================'
echo 'Your Edge or Chrome will open. Then:'
echo '1. Sign in to American Express (do all the 2FA / verification yourself)'
echo '2. Go to your Checking or Savings account and open Statements / Documents'
echo '3. LEAVE THAT BROWSER WINDOW OPEN - do not close it'
echo '4. Then run:  ./paperpull amexbanking diagnose   (a safe look, downloads nothing)'

"$PY" amexbanking_docs.py --open-browser $CFG
