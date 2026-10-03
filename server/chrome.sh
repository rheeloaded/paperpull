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
APT_LOG=/tmp/chrome-apt.log
APT="-o Dir::Etc::sourcelist=sources.list.d/paperpull-chrome.list -o Dir::Etc::sourceparts=- -o APT::Get::List-Cleanup=0 -o APT::Sandbox::User=root"

say() { echo "[chrome] $*"; }

installed() {
  [ -x "$BROWSER/$1/opt/google/chrome/chrome" ]
}

have=""
if [ -L "$BROWSER/current" ]; then
  have=$(basename "$(readlink "$BROWSER/current")")
fi

wanted=""
# shellcheck disable=SC2086
if apt-get update $APT >"$APT_LOG" 2>&1; then
  wanted=$(apt-cache policy google-chrome-stable | awk '/Candidate:/ {print $2}')
  [ "$wanted" = "(none)" ] && wanted=""
fi

# Everyone may read Chrome and run it, the user pp among them, whatever the
# package's own folder modes were. Done at every start, so a Chrome unpacked
# by an earlier version of this script is put right too.
readable() {
  chmod -R a+rX "$BROWSER/$1"
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
# Chrome's own sandbox needs no helper that runs as root here, it uses the
# container's user namespaces, so the helper is not left setuid in a volume.
chmod 0755 "$BROWSER/$wanted.part/opt/google/chrome/chrome-sandbox" 2>/dev/null || true
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
