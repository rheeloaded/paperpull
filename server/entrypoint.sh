#!/bin/sh
# Runs as root only long enough to do what needs root, then hands everything
# to the user pp.
#
#   - pp takes the person's own NAS ids (PUID, PGID), so the documents it
#     writes into a shared folder belong to them
#   - Chrome is downloaded or brought up to date (chrome.sh), since apt
#     needs root to read Google's package list
#   - pp joins the group that owns a graphics card passed in, if any
set -eu

PUID="${PUID:-1000}"
PGID="${PGID:-1000}"
if [ "$(id -g pp)" != "$PGID" ]; then groupmod -o -g "$PGID" pp; fi
if [ "$(id -u pp)" != "$PUID" ]; then usermod -o -u "$PUID" pp; fi

mkdir -p /data /profiles /config /browser
# The signed-in profiles and the settings belong to pp alone. After a change
# of PUID, what an earlier start wrote follows it.
chown -R pp:pp /profiles /config /home/pp
chmod 700 /profiles /config
# A shared folder may refuse a change of owner, which is fine as long as pp
# can write to it.
chown pp:pp /data 2>/dev/null || true

if ! /opt/paperpull/server/chrome.sh; then
  echo "PaperPull cannot start without Chrome. See the lines above." >&2
  exit 1
fi

# A graphics card's device nodes belong to a group of the host's own, whose
# number the image cannot know in advance, so pp joins whichever group owns
# each node. A failure here costs only the card, never the start.
if [ -d /dev/dri ]; then
  for node in /dev/dri/*; do
    [ -c "$node" ] || continue
    gid=$(stat -c %g "$node")
    grp=$(getent group "$gid" | cut -d: -f1 || true)
    if [ -z "$grp" ]; then grp="dri$gid"; groupadd -o -g "$gid" "$grp" || true; fi
    usermod -aG "$grp" pp || true
  done
fi

exec setpriv --reuid=pp --regid=pp --init-groups env HOME=/home/pp USER=pp \
  /opt/paperpull/server/start.sh "$@"
