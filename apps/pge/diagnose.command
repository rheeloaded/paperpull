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

"$PY" pge_docs.py --diagnose $CFG
