"""Copy the documents a run saved into the folder Paperless consumes.

A PaperPull Server plug-in, and the first one. The panel runs it after every
run, hands it the run's description as JSON on stdin (gui/server_mode.py,
after_run), and shows what it prints in the run's output. It is a program of
its own and talks to PaperPull only through that description, which is how
every plug-in is meant to work.

Each new PDF is copied, never moved, so PaperPull keeps its own files and
its records of them. A copy is written under a name that starts with a dot
and then renamed, so Paperless, which skips such names, never picks up half
a file. A name already taken by a different file gets " (2)" and so on, and
the very same file already there is left alone.

Someone who can write to the shared data folder or the consume folder can
leave a link in either. So a document is read as a plain file of its own,
never through a link, the copy is written under a name nobody can guess and
opened so it can never be a file already there, a name a link holds counts
as taken, and a provider's folder that is a link is refused (a private
report of 2026-11-10).

    PAPERLESS_CONSUME_DIR   the folder, /paperless unless set. Nothing is
                            copied when no folder is there.
    PAPERLESS_SUBFOLDERS    1 puts each provider's documents in a folder of
                            that provider's name, which Paperless makes a
                            tag when PAPERLESS_CONSUMER_SUBDIRS_AS_TAGS is on.
"""
from __future__ import annotations

import json
import os
import re
import stat
import sys
from pathlib import Path
from typing import Optional

KINDS = (".pdf",)


def destination(event: dict) -> Path:
    dest = Path(os.environ.get("PAPERLESS_CONSUME_DIR") or "/paperless")
    if os.environ.get("PAPERLESS_SUBFOLDERS") == "1" and event.get("provider"):
        dest = dest / safe_name(str(event["provider"]))
    return dest


def safe_name(name: str) -> str:
    """A provider's name as a folder name, letters, digits, spaces and a few
    marks, so no name can climb out of the consume folder."""
    kept = re.sub(r"[^A-Za-z0-9 &'._-]", "", name).strip(" .")
    return kept or "PaperPull"


def open_plain(path: Path):
    """An open binary file on a plain file of its own at path, never one
    reached through a link at its name, a named pipe or a device. OSError
    for anything else."""
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
                 | getattr(os, "O_BINARY", 0))
    f = os.fdopen(fd, "rb")
    st = os.fstat(f.fileno())
    if not stat.S_ISREG(st.st_mode) or st.st_nlink > 1:
        f.close()
        raise OSError("%s is not a plain file of its own" % path)
    return f


def same_bytes(a: Path, data: bytes) -> bool:
    try:
        with open_plain(a) as f:
            return f.read(len(data) + 1) == data
    except OSError:
        return False


def free_name(dest: Path, src: Path, data: bytes) -> Optional[Path]:
    """Where to copy src in dest, or None when the same file is already
    there. A name anything holds, a link with nothing at its end among
    them, is taken."""
    candidate = dest / src.name
    n = 2
    while os.path.lexists(candidate):
        if same_bytes(candidate, data):
            return None
        candidate = dest / ("%s (%d)%s" % (src.stem, n, src.suffix))
        n += 1
    return candidate


def copy_into(dest: Path, src: Path) -> bool:
    """Copy one file, whole or not at all. False when it was already there."""
    with open_plain(src) as f:
        data = f.read()
    target = free_name(dest, src, data)
    if target is None:
        return False
    part = target.with_name(".%s.%s.part" % (target.name, os.urandom(6).hex()))
    fd = os.open(part, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
                 | getattr(os, "O_BINARY", 0), 0o666)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(data)
        os.replace(part, target)
    except BaseException:
        try:
            os.unlink(part)
        except OSError:
            pass
        raise
    return True


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except ValueError:
        print("The run's description could not be read, so nothing was copied.")
        return 1
    files = [Path(p) for p in event.get("new_files") or []]
    files = [p for p in files if p.suffix.lower() in KINDS and p.is_file()]
    if not files:
        return 0
    root = Path(os.environ.get("PAPERLESS_CONSUME_DIR") or "/paperless")
    if not root.is_dir():
        print("No Paperless folder is mounted at %s, so the %d new document%s stayed "
              "where PaperPull saved them." % (root, len(files), "" if len(files) == 1 else "s"))
        return 0
    dest = destination(event)
    dest.mkdir(exist_ok=True)
    junction = getattr(os.path, "isjunction", None)
    if not stat.S_ISDIR(os.lstat(dest).st_mode) or (junction and junction(dest)):
        print("%s is a link rather than a folder, so the %d new document%s stayed where "
              "PaperPull saved them. Remove it, and the next run copies them." % (
                  dest, len(files), "" if len(files) == 1 else "s"))
        return 0
    copied = there = refused = 0
    for src in files:
        try:
            if copy_into(dest, src):
                copied += 1
            else:
                there += 1
        except OSError:
            refused += 1
    said = "Copied %d new document%s to Paperless (%s)." % (
        copied, "" if copied == 1 else "s", dest)
    if there:
        said += " %d %s already there." % (there, "was" if there == 1 else "were")
    if refused:
        said += (" %d %s not copied, since %s a link or could not be read." % (
            refused, "was" if refused == 1 else "were", "it was" if refused == 1 else "each was"))
    print(said)
    return 0


if __name__ == "__main__":
    sys.exit(main())
