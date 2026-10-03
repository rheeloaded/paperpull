#!/bin/sh
# Runs as pp. The virtual screen the providers' sign-in browsers open on,
# its window manager, the screen sharing server and the web page that shows
# it, then the panel.
#
# Everything here listens inside the container only. Step two of the server
# plan puts the panel on the network behind a password and shows the screen
# through it. Until then nothing is published.
set -u
LOGS=/config/logs
mkdir -p "$LOGS"

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
websockify --web /usr/share/novnc 127.0.0.1:6080 127.0.0.1:5900 \
  >"$LOGS/websockify.log" 2>&1 &

cd /opt/paperpull/gui
exec python -m uvicorn app:app --host 127.0.0.1 --port 8765
