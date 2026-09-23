"""Taking a PDF the provider produced, rather than making one ourselves.

receipt_pdf.py renders a page we are looking at. This is the other half,
for a site that hands over a real PDF of its own: the browser downloads it
to a folder, or opens it in a tab, and the app has to end up with the bytes
in the right file.

The pieces here are the ones that need nothing from a provider. Whichever
app is asking, a finished download is a file that is not still being
written, and pointing a browser's downloads at a folder is the same CDP
call every time. Eleven apps had a copy of each, all descended from one
scaffold, so every provider added since made another.
"""
from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

log = logging.getLogger("paperpull.capture")

# A browser writes a download under a temporary name and renames it when it
# finishes, so a file still carrying one of these is not ours yet.
UNFINISHED = (".crdownload", ".part", ".partial", ".tmp", ".download")


def set_download_dir(page, dirpath) -> None:
    """Point the attached browser's downloads at `dirpath`, over CDP.

    Best effort on purpose. A browser that refuses is not a reason to stop
    a run, because the app still has the other ways of taking a document,
    and the failure is written down rather than raised.
    """
    try:
        Path(dirpath).mkdir(parents=True, exist_ok=True)
        cdp = page.context.new_cdp_session(page)
        cdp.send("Browser.setDownloadBehavior",
                 {"behavior": "allow", "downloadPath": str(dirpath), "eventsEnabled": True})
    except Exception as e:
        log.info("set_download_dir failed: %s", e)


def snapshot(dl_dir) -> set:
    """What is in the download folder now, to compare against later."""
    try:
        return set(os.listdir(dl_dir)) if dl_dir else set()
    except OSError:
        return set()


def take_new_pdf(dl_dir, before: set, out_path: Path) -> bool:
    """Move a finished PDF that appeared in `dl_dir` since `before` to
    `out_path`.

    A file still downloading is skipped, and so is one that is empty or
    does not start with the PDF marker, because a site that answers an
    expired link with an HTML error page still produces a file.
    """
    if not dl_dir:
        return False
    try:
        names = [f for f in os.listdir(dl_dir)
                 if f not in before and not f.lower().endswith(UNFINISHED)]
    except OSError:
        return False
    for name in names:
        src = Path(dl_dir) / name
        try:
            if src.stat().st_size == 0 or src.read_bytes()[:5] != b"%PDF-":
                continue
            if out_path.exists():
                out_path.unlink()
            shutil.move(str(src), str(out_path))
            return True
        except OSError:
            continue
    return False
