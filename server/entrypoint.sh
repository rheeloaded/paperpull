#!/bin/sh
# Runs as root only long enough to do what needs root, then hands everything
# to the user pp.
#
#   - pp takes the person's own NAS ids (PUID, PGID), so the documents it
#     writes into a shared folder belong to them
#   - pp joins the group that owns a graphics card passed in, if any
#   - the browser volume is root's, and pp may only read it
#   - Chrome is downloaded or brought up to date (chrome.sh), since apt
#     needs root to read Google's package list
#   - nothing pp runs may gain a privilege by starting a program, unless
#     Chrome's setuid sandbox was chosen (see "On Synology" in SERVER.md)
set -eu

# An id as a plain number, its leading zeros dropped, when it is a number
# from $2 to 4294967294, the largest id Linux gives. 4294967295 is -1 to
# the kernel, and setpriv given it leaves the user as it was, root.
plain_id() {
  case "$1" in ""|*[!0-9]*) return 1 ;; esac
  set -- "${1#"${1%%[!0]*}"}" "$2"
  set -- "${1:-0}" "$2"
  [ ${#1} -le 10 ] && [ "$1" -ge "$2" ] && [ "$1" -le 4294967294 ] && echo "$1"
}

puid_given="${PUID:-1000}"
pgid_given="${PGID:-1000}"
if ! PUID=$(plain_id "$puid_given" 1) || ! PGID=$(plain_id "$pgid_given" 0); then
  echo "PUID must be a number from 1 to 4294967294, and PGID one from 0 to 4294967294," >&2
  echo "such as 1000, not \"$puid_given\" and \"$pgid_given\"." >&2
  exit 1
fi

# The user and group files in use, the image's own (kept in /etc/paperpull)
# with pp given PUID and PGID, and with pp a member of each group in $3, a
# list of numbers. A number no group has gets a group of its own, dri and
# the number. $1 is the folder of the image's files, $2 where they are
# written.
user_files() {
  awk -F: -v OFS=: -v uid="$PUID" -v gid="$PGID" \
    '$1 == "pp" { $3 = uid; $4 = gid } { print }' "$1/passwd" >"$2/passwd.new" || return 1
  awk -F: -v OFS=: -v gid="$PGID" -v joins=" $3 " '
    $1 == "pp" { $3 = gid }
    {
      seen[$3] = 1
      if ($1 != "pp" && index(joins, " " $3 " ") && ("," $4 ",") !~ /,pp,/) {
        $4 = ($4 == "" ? "pp" : $4 ",pp")
      }
      print
    }
    END {
      n = split(joins, wanted, " ")
      for (i = 1; i <= n; i++) {
        if (!(wanted[i] in seen)) { print "dri" wanted[i] ":x:" wanted[i] ":pp"; seen[wanted[i]] = 1 }
      }
    }' "$1/group" >"$2/group.new" || return 1
  chmod 644 "$2/passwd.new" "$2/group.new" || return 1
  mv -f "$2/passwd.new" "$2/passwd" || return 1
  mv -f "$2/group.new" "$2/group"
}

# A graphics card's device nodes belong to a group of the host's own, whose
# number the image cannot know in advance, so pp joins whichever group owns
# each node.
joins=""
if [ -d /dev/dri ]; then
  for node in /dev/dri/*; do
    [ -c "$node" ] || continue
    gid=$(stat -c %g "$node" 2>/dev/null) || continue
    case "$gid" in ""|*[!0-9]*) continue ;; esac
    joins="$joins $gid"
  done
fi

# /etc/passwd and /etc/group are links to these, written anew at every
# start, so that the image's own files can stay read-only (read_only in the
# compose files, with /run in memory). /run/paperpull is root's, made
# before anything runs as pp, and pp can write nothing in it.
if ! { mkdir -p /run/paperpull && chmod 755 /run/paperpull \
       && user_files /etc/paperpull /run/paperpull "$joins"; }; then
  echo "PaperPull could not write its user's ids into /run/paperpull. With read_only: true in" >&2
  echo "the compose file, /run has to be listed under tmpfs, as in the compose.yaml it came with." >&2
  exit 1
fi

mkdir -p /data /profiles /config /browser
# The signed-in profiles and the settings belong to pp alone. After a change
# of PUID, what an earlier start wrote follows it. A file with a second name
# keeps its owner, since pp could have given that name to a file of root's
# on the same file system, the image's own programs among them where
# /home/pp is not in memory, and chown would then hand that file to pp.
# Links are never followed.
find /profiles /config /home/pp -xdev ! -type l \( -type d -o -links 1 \) -exec chown pp:pp {} +
chmod 700 /profiles /config
# A shared folder may refuse a change of owner, which is fine as long as pp
# can write to it.
chown pp:pp /data 2>/dev/null || true
# Chrome's folder belongs to root, and pp may only read it, so nothing
# running as pp can put a folder or a file there for chrome.sh, which runs
# as root, to take for Chrome's. A volume made from an older image has pp as
# the owner of its top folder. Only that folder is given back to root, and
# never what is inside it, so that anything pp put there stays pp's and
# chrome.sh will not make it setuid. Where it cannot be given back,
# chrome.sh sets up no setuid helper either.
if ! { chown 0:0 /browser && chmod 0755 /browser; }; then
  echo "[chrome] /browser could not be given to root, so no setuid sandbox helper is set up in it." >&2
fi

if ! /opt/paperpull/server/chrome.sh; then
  echo "PaperPull cannot start without Chrome. See the lines above." >&2
  exit 1
fi

# No program pp starts gains a privilege from a setuid bit or a file
# capability. no-new-privileges in the compose files does the same for the
# whole container, and this holds it for pp under a compose file without it
# too. Chrome's setuid helper is the one exception, since it works only
# through its setuid bit, and chrome.sh sets that bit, on a file of root's,
# only where the person chose the setuid sandbox.
helper=/browser/current/opt/google/chrome/chrome-sandbox
no_new_privs=--no-new-privs
if [ -u "$helper" ] && [ "$(stat -L -c %u "$helper" 2>/dev/null)" = 0 ]; then no_new_privs=""; fi

# shellcheck disable=SC2086
exec setpriv --reuid=pp --regid=pp --init-groups $no_new_privs env HOME=/home/pp USER=pp \
  /opt/paperpull/server/start.sh "$@"
