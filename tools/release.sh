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
  "$GH" run download "$id" -D "$WORK/$name" >/dev/null
done

echo "checking the files against the checksums the runs published ..."
mkdir -p "$WORK/flat"
find "$WORK" -name "SHA256SUMS.txt" | while read -r sums; do
  (cd "$(dirname "$sums")" && sha256sum -c --ignore-missing SHA256SUMS.txt)
done
for f in "$WORK"/*/*/PaperPull-"$VERSION"-setup.exe \
         "$WORK"/*/*/PaperPull-"$VERSION".zip \
         "$WORK"/*/*/PaperPull-"$VERSION"-arm64.dmg; do
  [ -f "$f" ] && cp "$f" "$WORK/flat/"
done
ls -1 "$WORK/flat"

echo
echo "publishing $TAG ..."
"$GH" release create "$TAG" --title "PaperPull $VERSION" --notes-file "$NOTES" \
  "${EXTRA[@]}" "$WORK/flat/"*

"$GH" release view "$TAG" --json isDraft,isPrerelease,assets \
  --jq '{draft: .isDraft, prerelease: .isPrerelease, assets: [.assets[].name]}'
rm -rf "$WORK"
echo "done. https://github.com/rheeloaded/paperpull/releases/tag/$TAG"
