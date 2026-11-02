#!/bin/sh
# Runs as pp. The virtual screen the providers' sign-in browsers open on,
# its window manager and the screen sharing server, a check of Chrome's
# sandbox, then the panel.
#
# Only the panel listens beyond the container, behind its password. The
# screen sharing server listens inside the container only, and the browser
# screen reaches it through the panel, on the panel's port and behind the
# same password (gui/server_mode.py).
set -u

# Never as root, whatever ids the entrypoint was given. Chrome refuses root
# anyway, and the panel and the screen have no need of it.
if [ "$(id -u)" = 0 ]; then
  echo "PaperPull will not run its panel and browsers as root. Check PUID in the compose file." >&2
  exit 1
fi

LOGS=/config/logs
mkdir -p "$LOGS"

# The panel listens on the network only as PaperPull Server, which never
# answers without a password, whatever the environment was given.
export PAPERPULL_SERVER=1

# A container started again keeps its /tmp, so the last start's screen lock
# is still there and would stop the screen from starting. Nothing is running
# yet, so it is stale.
rm -f /tmp/.X99-lock /tmp/.X11-unix/X99

# Each signed-in profile's own lock, for the same reason. Chrome names its
# lock after the computer and the browser's process, and a container started
# again has new process numbers, and a new computer name once it is made
# anew from a newer image. A lock left by a browser that was open when the
# container stopped made Chrome take the profile for one in use elsewhere,
# so the sign-in window never opened its debugging port (#78). No browser is
# open yet, and only this container's browsers use /profiles.
find "${PAPERPULL_PROFILES:-/profiles}" -mindepth 2 -maxdepth 2 \
  \( -name SingletonLock -o -name SingletonSocket -o -name SingletonCookie \) \
  -exec rm -f {} + 2>/dev/null

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

# Whether this host can give Chrome its sandbox, said in one line of the
# container's log, as pp, the user Chrome runs as. A host that cannot, such
# as Synology DSM, whose kernel has no user namespaces, otherwise showed
# only a black Browser Screen (#110). It never stops the start.
python -m paperpull_core.host_sandbox || true

cd /opt/paperpull/gui
exec python -m uvicorn app:app --host 0.0.0.0 --port 8765 --ws websockets-sansio
