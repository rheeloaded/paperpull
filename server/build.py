"""Build the PaperPull Server image from the files git tracks, and no others.

    python server/build.py                  build paperpull-server:<VERSION> and :dev
    python server/build.py --save FILE.tar  and write it to a file a NAS can import

Docker is handed a folder made here, not the working copy. It holds only
the files git tracks, from the places the image needs (ALLOWED), without
tests, desktop launchers or pictures (left_out), and with text files given
LF line endings, since a Windows checkout carries CRLF and a shell script
with CRLF does not run.

A working copy holds things no image may carry, a provider's downloads, its
records, a signed-in browser profile. None of them is tracked, so none of
them reaches the image this way, whatever else is in the folder. That is an
allowlist on purpose. A list of what to keep out would be the one thing
standing between a person's statements and a published image.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath

REPO = Path(__file__).resolve().parents[1]

ALLOWED = ("VERSION", "LICENSE", "LICENSE-MIT", "NOTICE.md", "TRADEMARK.md",
           "paperpull.py", "core/", "apps/", "gui/", "packaging/paperpull.ico",
           "tools/add_account.py", "server/")
LEFT_OUT_PARTS = {"tests", ".venv", "__pycache__", "browser-profile", "Diagnostics"}
LEFT_OUT_SUFFIXES = (".pdf", ".png", ".gif", ".jpg", ".jpeg", ".bat", ".cmd",
                     ".command", ".csv", ".xlsx", ".zip", ".tar", ".gz")
TEXT_SUFFIXES = (".py", ".sh", ".json", ".txt", ".md", ".toml", ".yaml", ".yml",
                 ".ini", ".cfg", ".html", ".css", ".js")
TEXT_NAMES = ("VERSION", "LICENSE", "LICENSE-MIT", "Dockerfile")


def allowed(path: str) -> bool:
    return any(path == a or (a.endswith("/") and path.startswith(a)) for a in ALLOWED)


def left_out(path: str) -> bool:
    p = PurePosixPath(path)
    return (any(part in LEFT_OUT_PARTS for part in p.parts)
            or p.suffix.lower() in LEFT_OUT_SUFFIXES)


def selected(paths) -> list:
    """The tracked paths that go into the image, in the order given."""
    return [p for p in paths if allowed(p) and not left_out(p)]


def is_text(path: str) -> bool:
    p = PurePosixPath(path)
    return p.suffix.lower() in TEXT_SUFFIXES or p.name in TEXT_NAMES


def tracked(repo: Path = REPO) -> list:
    out = subprocess.run(["git", "-C", str(repo), "ls-files", "-z"],
                         capture_output=True, check=True).stdout
    return [p for p in out.decode("utf-8").split("\0") if p]


def make_context(dest: Path, repo: Path = REPO) -> int:
    """Fill `dest` with the image's files. Returns how many."""
    count = 0
    for rel in selected(tracked(repo)):
        src = repo / rel
        if not src.is_file():       # tracked but deleted in this working copy
            continue
        out = dest / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        data = src.read_bytes()
        if is_text(rel):
            data = data.replace(b"\r\n", b"\n")
        out.write_bytes(data)
        count += 1
    return count


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--save", metavar="FILE", help="also write the image to FILE with docker save")
    ap.add_argument("--name", default="paperpull-server", help="image name, default %(default)s")
    args = ap.parse_args(argv)

    version = (REPO / "VERSION").read_text(encoding="utf-8").strip()
    tags = ["%s:%s" % (args.name, version), "%s:dev" % args.name]
    ctx = Path(tempfile.mkdtemp(prefix="paperpull-server-"))
    try:
        n = make_context(ctx)
        print("build context, %d tracked files in %s" % (n, ctx), flush=True)
        cmd = ["docker", "build", "-f", str(ctx / "server" / "Dockerfile")]
        for tag in tags:
            cmd += ["-t", tag]
        r = subprocess.run(cmd + [str(ctx)])
        if r.returncode:
            return r.returncode
    finally:
        shutil.rmtree(ctx, ignore_errors=True)

    # Docker's image store reports the layers as they download, compressed,
    # while the listing reports what they take on disk once unpacked.
    content = subprocess.run(["docker", "image", "inspect", tags[0], "--format", "{{.Size}}"],
                             capture_output=True, text=True).stdout.strip()
    disk = subprocess.run(["docker", "image", "ls", tags[0], "--format", "{{.Size}}"],
                          capture_output=True, text=True).stdout.strip().splitlines()
    print("built %s" % ", ".join(tags), flush=True)
    if content.isdigit():
        print("  about %.0f MB to download" % (int(content) / 1e6), flush=True)
    if disk:
        print("  %s on disk" % disk[0], flush=True)
    if args.save:
        subprocess.run(["docker", "save", "-o", args.save, tags[0]], check=True)
        print("saved %s, %.0f MB" % (args.save, Path(args.save).stat().st_size / 1e6))
    return 0


if __name__ == "__main__":
    sys.exit(main())
