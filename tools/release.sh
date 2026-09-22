#!/usr/bin/env bash
# Publish a release that is already tagged and built.
#
#     bash tools/release.sh 0.30.2
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

TAG="v$VERSION"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
WORK="$HERE/.release/$VERSION"
NOTES="$HERE/.release/notes-$VERSION.md"

cd "$HERE"
[ -f "$NOTES" ] || { echo "no notes at $NOTES" >&2; exit 2; }
git rev-parse "$TAG" >/dev/null 2>&1 || { echo "no tag $TAG" >&2; exit 2; }

echo "waiting for the package runs on $TAG ..."
for name in "Windows package" "macOS package"; do
  id=$(gh run list --limit 20 --json databaseId,name,headBranch \
       --jq "[.[] | select(.name==\"$name\" and .headBranch==\"$TAG\")] | first | .databaseId")
  [ -n "$id" ] && [ "$id" != "null" ] || { echo "no $name run for $TAG" >&2; exit 1; }
  until [ "$(gh run view "$id" --json status --jq .status)" = "completed" ]; do sleep 20; done
  [ "$(gh run view "$id" --json conclusion --jq .conclusion)" = "success" ] \
    || { echo "$name run $id did not succeed" >&2; exit 1; }
  echo "  $name run $id: success"
  rm -rf "$WORK/$name"; mkdir -p "$WORK/$name"
  gh run download "$id" -D "$WORK/$name" >/dev/null
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
gh release create "$TAG" --title "PaperPull $VERSION" --notes-file "$NOTES" \
  "${EXTRA[@]}" "$WORK/flat/"*

gh release view "$TAG" --json isDraft,isPrerelease,assets \
  --jq '{draft: .isDraft, prerelease: .isPrerelease, assets: [.assets[].name]}'
rm -rf "$WORK"
echo "done. https://github.com/rheeloaded/paperpull/releases/tag/$TAG"
