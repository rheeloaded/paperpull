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

    PAPERLESS_CONSUME_DIR   the folder, /paperless unless set. Nothing is
                            copied when no folder is there.
    PAPERLESS_SUBFOLDERS    1 puts each provider's documents in a folder of
                            that provider's name, which Paperless makes a
                            tag when PAPERLESS_CONSUMER_SUBDIRS_AS_TAGS is on.
"""
from __future__ import annotations

import filecmp
import json
import os
import re
import shutil
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


def free_name(dest: Path, src: Path) -> Optional[Path]:
    """Where to copy src in dest, or None when the same file is already there."""
    candidate = dest / src.name
    n = 2
    while candidate.exists():
        if candidate.is_file() and filecmp.cmp(candidate, src, shallow=False):
            return None
        candidate = dest / ("%s (%d)%s" % (src.stem, n, src.suffix))
        n += 1
    return candidate


def copy_into(dest: Path, src: Path) -> bool:
    """Copy one file, whole or not at all. False when it was already there."""
    target = free_name(dest, src)
    if target is None:
        return False
    part = target.with_name("." + target.name + ".part")
    try:
        shutil.copyfile(src, part)
        os.replace(part, target)
    finally:
        if part.exists():
            part.unlink()
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
    copied = there = 0
    for src in files:
        if copy_into(dest, src):
            copied += 1
        else:
            there += 1
    said = "Copied %d new document%s to Paperless (%s)." % (
        copied, "" if copied == 1 else "s", dest)
    if there:
        said += " %d %s already there." % (there, "was" if there == 1 else "were")
    print(said)
    return 0


if __name__ == "__main__":
    sys.exit(main())
