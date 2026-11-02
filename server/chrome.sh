#!/bin/sh
# Download Chrome from Google into the browser volume, or bring it up to
# date, and point /browser/current at it. Runs as root at every start.
#
# Chrome is never part of the image. apt fetches it from Google's own
# package list and checks it against Google's signing key, whose fingerprint
# the image was built against (see the Dockerfile). The package is unpacked
# into the volume rather than installed, so a new image does not mean a new
# download, and only the newest version and the one before it are kept.
#
# Without a connection the Chrome already in the volume is used. With none
# there, it says so and the container stops.
set -eu

BROWSER=/browser
# apt's package lists and what it said, kept in root's own /run rather than
# in the image's /var/lib/apt, so the image's files can stay read-only
# (read_only in the compose files, with /run in memory), and never at a
# fixed name in /tmp, where pp may write.
APT_DIR=/run/paperpull/apt
APT_LOG=$APT_DIR/apt.log
APT="-o Dir::Etc::sourcelist=sources.list.d/paperpull-chrome.list -o Dir::Etc::sourceparts=- -o APT::Get::List-Cleanup=0 -o APT::Sandbox::User=root -o Dir::State::Lists=$APT_DIR/lists"
mkdir -p "$APT_DIR/lists/partial"
chmod 700 "$APT_DIR"

say() { echo "[chrome] $*"; }

installed() {
  [ -x "$BROWSER/$1/opt/google/chrome/chrome" ]
}

# CAP_SYS_ADMIN in this container's bounding set, bit 21 of CapBnd, which it
# holds only when the person added it with cap_add.
given_sys_admin() {
  bnd=$(awk '/^CapBnd:/ {print $2}' /proc/self/status 2>/dev/null)
  case "$bnd" in ""|*[!0-9a-fA-F]*) return 1 ;; esac
  [ $(( (0x$bnd >> 21) & 1 )) -eq 1 ]
}

# The seccomp-bpf filter, the other half of Chrome's sandbox, asked of the
# server's own host check (paperpull_core.host_sandbox), so there is one
# probe. Anything but a yes counts as no.
kernel_has_seccomp() {
  python -c "import sys; from paperpull_core.host_sandbox import check; sys.exit(0 if check().seccomp_bpf == 'yes' else 1)" 2>/dev/null
}

# no-new-privileges, on for this container, keeps the kernel from honoring
# any setuid bit, the helper's among them. Asked of the kernel through the
# same host check, since the NoNewPrivs line of /proc/self/status came only
# in Linux 4.10, later than some of the kernels the helper is for.
no_new_privileges() {
  python -c "import sys; from paperpull_core.host_sandbox import no_new_privs; sys.exit(0 if no_new_privs() else 1)" 2>/dev/null
}

SETUID_SANDBOX=0
if given_sys_admin; then
  if ! kernel_has_seccomp; then
    say "The container has SYS_ADMIN, but this kernel has no seccomp, so Chrome's setuid sandbox helper"
    say "is not set up, since Chrome would have only half its sandbox. See \"On Synology\" in SERVER.md."
  elif no_new_privileges; then
    say "The container has SYS_ADMIN, but no-new-privileges is on, which turns every setuid bit off,"
    say "so Chrome's setuid sandbox helper is not set up. See \"On Synology\" in SERVER.md."
  else
    SETUID_SANDBOX=1
  fi
fi

have=""
if [ -L "$BROWSER/current" ]; then
  have=$(basename "$(readlink "$BROWSER/current")")
fi

wanted=""
# shellcheck disable=SC2086
if apt-get update $APT >"$APT_LOG" 2>&1; then
  # shellcheck disable=SC2086
  wanted=$(apt-cache policy $APT google-chrome-stable | awk '/Candidate:/ {print $2}')
  [ "$wanted" = "(none)" ] && wanted=""
fi

# Everyone may read Chrome and run it, the user pp among them, whatever the
# package's own folder modes were. Done at every start, so a Chrome unpacked
# by an earlier version of this script is put right too.
readable() {
  chmod -R a+rX "$BROWSER/$1"
  sandbox_helpers "$1"
}

# chrome-sandbox is Chrome's setuid helper, and the package ships it setuid
# root. Where the kernel gives user namespaces, Chrome's sandbox needs no
# helper that runs as root, so by default no copy in the volume keeps the
# bit. Some NAS kernels, Synology's among them, have no user namespaces at
# all, and there Chrome builds the same sandbox through this helper, which
# needs CAP_SYS_ADMIN to make the sandbox's namespaces. So in a container
# given SYS_ADMIN with cap_add, on a kernel with seccomp, see "On Synology"
# in SERVER.md, the helper of the Chrome in use ($1) is made setuid root,
# once every copy has lost the bit, so taking SYS_ADMIN away again, or an
# older Chrome kept beside the new one, leaves none behind. The sandbox is
# on either way, this is never --no-sandbox. Runs after the recursive chmod
# above, and a link to a helper is never followed.
#
# The bit goes only on a helper root alone could have put there, see
# may_be_setuid, and a file is never given to root to make it so. Code
# running as pp that could plant a file, or change one, which then became
# setuid root, would be root itself, holding SYS_ADMIN besides.
sandbox_helpers() {
  for entry in "$BROWSER"/*; do
    [ -L "$entry" ] && continue
    helper="$entry/opt/google/chrome/chrome-sandbox"
    { [ -f "$helper" ] && [ ! -L "$helper" ]; } || continue
    chmod u-s,g-s "$helper" 2>/dev/null || true
  done
  [ "$SETUID_SANDBOX" = 1 ] || return 0
  if ! why=$(may_be_setuid "$1"); then
    say "The container has SYS_ADMIN, but Chrome's setuid sandbox helper is not set up, since ${why:-its folders could not be checked}."
    return 0
  fi
  if ! chmod 4755 "$BROWSER/$1/opt/google/chrome/chrome-sandbox"; then
    say "Chrome's setuid sandbox helper could not be set up."
    return 0
  fi
  say "The container has SYS_ADMIN, so Chrome's setuid sandbox helper is set up, for a kernel without user namespaces."
  if awk -v dir="$BROWSER" '$2 == dir {print $4}' /proc/mounts | grep -qw nosuid; then
    say "But $BROWSER is mounted nosuid, so the kernel ignores the helper's setuid bit, and where"
    say "the kernel has no user namespaces Chrome will refuse to start. Mount it without nosuid."
  fi
}

# Whether the helper of the Chrome in $BROWSER/$1 may be made setuid root.
# It must be a plain file with one name, belonging to root's user and
# group, and every folder from $BROWSER down to it must be root's alone and
# no link. A second name for the file, made anywhere on the same file
# system, would keep the bit after this one is gone. When it may not, says
# why, for the log.
may_be_setuid() {
  file="$BROWSER/$1/opt/google/chrome/chrome-sandbox"
  for dir in "$BROWSER" "$BROWSER/$1" "$BROWSER/$1/opt" "$BROWSER/$1/opt/google" \
             "$BROWSER/$1/opt/google/chrome"; do
    if [ -L "$dir" ] || [ ! -d "$dir" ]; then
      echo "$dir is a link or not a folder"
      return 1
    fi
    root_alone "$dir" || return 1
  done
  if [ -L "$file" ] || [ ! -f "$file" ]; then
    echo "$file is a link or not a plain file"
    return 1
  fi
  root_alone "$file" || return 1
  group=$(status_of "$file" %g)
  if [ "$group" != 0 ]; then
    echo "$file belongs to group ${group:-unknown}, not to root"
    return 1
  fi
  links=$(status_of "$file" %h)
  if [ "$links" != 1 ]; then
    echo "$file has ${links:-an unknown number of} names, where it may have only one"
    return 1
  fi
}

# Whether root alone owns a path, as its owner and with no group and nobody
# else allowed to write to it, so nothing running as pp could have made it
# or changed it since. When not, says why.
root_alone() {
  owner=$(status_of "$1" %u)
  mode=$(status_of "$1" %a)
  case "$owner" in ""|*[!0-9]*) echo "the owner of $1 could not be read"; return 1 ;; esac
  case "$mode" in ""|*[!0-7]*) echo "the mode of $1 could not be read"; return 1 ;; esac
  if [ "$owner" != 0 ]; then
    echo "$1 belongs to user $owner, not to root"
    return 1
  fi
  if [ $(( 0$mode & 022 )) -ne 0 ]; then
    echo "users other than root may write to $1"
    return 1
  fi
}

# One field of a path's own status, a link never followed, by the letter
# stat gives it (%u owner, %g group, %a mode in octal, %h number of names),
# or nothing when it cannot be read. GNU's stat and busybox's both take it.
status_of() {
  stat -c "$2" "$1" 2>/dev/null || true
}

if [ -z "$wanted" ]; then
  if [ -n "$have" ] && installed "$have"; then
    readable "$have"
    say "Google could not be reached to look for a newer Chrome, so Chrome $have is used."
    exit 0
  fi
  say "Chrome is not downloaded yet, and Google could not be reached."
  say "The container needs to reach dl.google.com once, when it first starts."
  sed 's/^/[chrome]   /' "$APT_LOG" | tail -5
  exit 1
fi

if [ "$wanted" = "$have" ] && installed "$have"; then
  readable "$have"
  say "Chrome $have is up to date."
  exit 0
fi

say "Downloading Chrome $wanted from Google."
work=$(mktemp -d)
# shellcheck disable=SC2086
if ! (cd "$work" && apt-get download $APT "google-chrome-stable=$wanted") >>"$APT_LOG" 2>&1; then
  rm -rf "$work"
  if [ -n "$have" ] && installed "$have"; then
    readable "$have"
    say "The download did not finish, so Chrome $have is used for now."
    exit 0
  fi
  say "The download did not finish."
  sed 's/^/[chrome]   /' "$APT_LOG" | tail -5
  exit 1
fi

rm -rf "$BROWSER/$wanted.part" "$BROWSER/$wanted"
dpkg-deb -x "$work"/google-chrome-stable_*.deb "$BROWSER/$wanted.part"
rm -rf "$work"
readable "$wanted.part"
mv "$BROWSER/$wanted.part" "$BROWSER/$wanted"
ln -sfn "$wanted" "$BROWSER/current.new"
mv -T "$BROWSER/current.new" "$BROWSER/current"

# Older versions go. The links are skipped, since a link to a folder given
# to rm with a slash after it would empty the folder it points at.
for entry in "$BROWSER"/*; do
  [ -L "$entry" ] && continue
  [ -d "$entry" ] || continue
  name=$(basename "$entry")
  [ "$name" = "$wanted" ] || [ "$name" = "$have" ] || rm -rf "$entry"
done
say "Chrome $wanted is ready."
