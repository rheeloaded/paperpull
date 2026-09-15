#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
PY=.venv/bin/python

CFG=""
if [ "${1:-}" != "" ]; then CFG="--config config.$1.json"; fi

if [ ! -x "$PY" ]; then
    echo "This app is not set up yet - run ./setup.command first."
    exit 1
fi

echo '============================================================'
echo 'PG&E Documents - sign in'
echo '============================================================'
echo 'A normal Chromium window will open. Then:'
echo '1. Sign in to PG&E (do all the 2FA / device approval yourself)'
echo '2. Go to Billing and payments (your statement history)'
echo '3. LEAVE THAT BROWSER WINDOW OPEN - do not close it'

"$PY" pge_docs.py --open-browser $CFG
