#!/bin/sh
# Runs as pp. The virtual screen the providers' sign-in browsers open on,
# its window manager and the screen sharing server, then the panel.
#
# Only the panel listens beyond the container, behind its password. The
# screen sharing server listens inside the container only, and the browser
# screen reaches it through the panel, on the panel's port and behind the
# same password (gui/server_mode.py).
set -u
LOGS=/config/logs
mkdir -p "$LOGS"

# The panel listens on the network only as PaperPull Server, which never
# answers without a password, whatever the environment was given.
export PAPERPULL_SERVER=1

# A container started again keeps its /tmp, so the last start's screen lock
# is still there and would stop the screen from starting. Nothing is running
# yet, so it is stale.
rm -f /tmp/.X99-lock /tmp/.X11-unix/X99

Xvfb :99 -screen 0 "${SCREEN:-1600x1000x24}" -nolisten tcp >"$LOGS/xvfb.log" 2>&1 &
i=0
while [ ! -e /tmp/.X11-unix/X99 ] && [ $i -lt 40 ]; do sleep 0.25; i=$((i + 1)); done
if [ ! -e /tmp/.X11-unix/X99 ]; then
  echo "The virtual screen did not start, see $LOGS/xvfb.log" >&2
  exit 1
fi
fluxbox >"$LOGS/fluxbox.log" 2>&1 &
x11vnc -display :99 -forever -shared -localhost -rfbport 5900 -nopw -quiet \
  >"$LOGS/x11vnc.log" 2>&1 &

cd /opt/paperpull/gui
exec python -m uvicorn app:app --host 0.0.0.0 --port 8765 --ws websockets-sansio
