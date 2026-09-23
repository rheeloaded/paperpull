#!/usr/bin/env bash
# Publish a release that is already tagged and built.
#
#     bash tools/release.sh 0.31.0
#     bash tools/release.sh 0.31.0-kroger.1 --prerelease
#
# It finds the two package runs for the tag, waits for them if they are
# still going, downloads their artifacts, checks every file against the
# checksums the runs published, and then creates the release with the
# notes at .release/notes-<version>.md.
#
# The workflows deliberately publish nothing on their own, so this is the
# one step that makes a build public, and a person runs it.
set -euo pipefail

VERSION="${1:-}"
shift || true
EXTRA=("$@")
if [ -z "$VERSION" ]; then
  echo "usage: bash tools/release.sh <version> [--prerelease]" >&2
  exit 2
fi

# The GitHub CLI is installed for Windows, and the bash this runs under is
# not always the one that has it on its PATH. Started from cmd, `bash` can
# be the WSL one, whose PATH is a Linux PATH with no gh on it at all. So
# look for it rather than assuming, and say where to get it if it is
# genuinely not installed.
GH="${GH:-}"
if [ -z "$GH" ]; then
  if command -v gh >/dev/null 2>&1; then
    GH="$(command -v gh)"
  else
    for candidate in \
      "/c/Program Files/GitHub CLI/gh.exe" \
      "/c/Program Files (x86)/GitHub CLI/gh.exe" \
      "/mnt/c/Program Files/GitHub CLI/gh.exe" \
      "/mnt/c/Program Files (x86)/GitHub CLI/gh.exe" \
      "${LOCALAPPDATA:-/nonexistent}/Programs/GitHub CLI/gh.exe" \
      "${LOCALAPPDATA:-/nonexistent}/Microsoft/WinGet/Links/gh.exe"
    do
      if [ -x "$candidate" ]; then GH="$candidate"; break; fi
    done
  fi
fi
if [ -z "$GH" ]; then
  echo "the GitHub CLI is not on this shell's PATH and is not where it installs to." >&2
  echo "install it from https://cli.github.com, or set GH to its full path and run again." >&2
  exit 2
fi
"$GH" auth status >/dev/null 2>&1 || {
  echo "the GitHub CLI is not signed in. run: \"$GH\" auth login" >&2
  exit 2
}

# Under WSL that CLI is a Windows program, and a Windows program cannot
# follow /mnt/c. Handed one, it wrote 326 MB of artifacts into a folder
# called mnt off the root of the drive and reported nothing wrong, and the
# upload then had nothing to upload. Every path it is given is translated
# now. Git Bash does that translation itself, so there it is left alone.
GH_WANTS_WINDOWS_PATHS=0
case "$GH" in
  /mnt/*) command -v wslpath >/dev/null 2>&1 && GH_WANTS_WINDOWS_PATHS=1 ;;
esac
winpath() {
  if [ "$GH_WANTS_WINDOWS_PATHS" = 1 ]; then wslpath -w "$1"; else printf '%s' "$1"; fi
}

TAG="v$VERSION"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
WORK="$HERE/.release/$VERSION"
NOTES="$HERE/.release/notes-$VERSION.md"

cd "$HERE"
[ -f "$NOTES" ] || { echo "no notes at $NOTES" >&2; exit 2; }
git rev-parse "$TAG" >/dev/null 2>&1 || { echo "no tag $TAG" >&2; exit 2; }

echo "waiting for the package runs on $TAG ..."
for name in "Windows package" "macOS package"; do
  id=$("$GH" run list --limit 20 --json databaseId,name,headBranch \
       --jq "[.[] | select(.name==\"$name\" and .headBranch==\"$TAG\")] | first | .databaseId")
  id="$(printf '%s' "$id" | tr -d '\r')"
  [ -n "$id" ] && [ "$id" != "null" ] || { echo "no $name run for $TAG" >&2; exit 1; }
  until [ "$("$GH" run view "$id" --json status --jq .status | tr -d '\r')" = "completed" ]; do sleep 20; done
  [ "$("$GH" run view "$id" --json conclusion --jq .conclusion | tr -d '\r')" = "success" ] \
    || { echo "$name run $id did not succeed" >&2; exit 1; }
  echo "  $name run $id: success"
  rm -rf "$WORK/$name"; mkdir -p "$WORK/$name"
  "$GH" run download "$id" -D "$(winpath "$WORK/$name")" >/dev/null
  # A download that landed somewhere else says nothing, so it is caught
  # here rather than at the end with an empty folder to upload.
  [ -n "$(find "$WORK/$name" -type f -print -quit)" ] \
    || { echo "$name downloaded no file into $WORK/$name" >&2; exit 1; }
done

rm -rf "$WORK/flat"; mkdir -p "$WORK/flat"
for f in "$WORK"/*/*/PaperPull-"$VERSION"-setup.exe \
         "$WORK"/*/*/PaperPull-"$VERSION".zip \
         "$WORK"/*/*/PaperPull-"$VERSION"-arm64.dmg; do
  [ -f "$f" ] && cp "$f" "$WORK/flat/"
done

# Each artifact comes down into a folder of its own, and one run's list of
# checksums covers files that are now in three of them, so the checking is
# done where the files about to be uploaded are. The Windows run writes its
# list with carriage returns on the ends of the lines, which made every
# name in it a name no file has, and a check that verifies nothing at all
# reports success at having found nothing to do. So the line endings come
# off, and a list that verified nothing is an error here.
echo "checking the files against the checksums the runs published ..."
SUMS="$(find "$WORK" -name "SHA256SUMS.txt")"
[ -n "$SUMS" ] || { echo "nothing that came down carries a SHA256SUMS.txt" >&2; exit 1; }
CHECKED=0
while IFS= read -r sums; do
  [ -n "$sums" ] || continue
  tr -d '\r' < "$sums" > "$WORK/flat/.sums"
  wanted=$(cd "$WORK/flat" && awk '{print $NF}' .sums | while read -r n; do
             [ -f "$n" ] && echo "$n"; done | wc -l)
  if [ "$wanted" -gt 0 ]; then
    (cd "$WORK/flat" && sha256sum -c --ignore-missing .sums)
    CHECKED=$((CHECKED + wanted))
  fi
  rm -f "$WORK/flat/.sums"
done <<SUMSLIST
$SUMS
SUMSLIST
[ "$CHECKED" -gt 0 ] || { echo "no file was checked against a published checksum" >&2; exit 1; }

ASSETS=()
for f in "$WORK/flat"/*; do
  [ -f "$f" ] && ASSETS+=("$(winpath "$f")")
done
[ "${#ASSETS[@]}" -gt 0 ] || { echo "nothing to upload from $WORK/flat" >&2; exit 1; }
ls -1 "$WORK/flat"

echo
echo "publishing $TAG ..."
"$GH" release create "$TAG" --title "PaperPull $VERSION" --notes-file "$(winpath "$NOTES")" \
  ${EXTRA[@]+"${EXTRA[@]}"} "${ASSETS[@]}"

"$GH" release view "$TAG" --json isDraft,isPrerelease,assets \
  --jq '{draft: .isDraft, prerelease: .isPrerelease, assets: [.assets[].name]}'
rm -rf "$WORK"
echo "done. https://github.com/rheeloaded/paperpull/releases/tag/$TAG"
