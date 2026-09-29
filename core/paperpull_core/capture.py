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

import base64
import filecmp
import logging
import os
import re
import shutil
from pathlib import Path
from typing import Optional

from .redact import redact

log = logging.getLogger("paperpull.capture")

# A browser writes a download under a temporary name and renames it when it
# finishes, so a file still carrying one of these is not ours yet.
UNFINISHED = (".crdownload", ".part", ".partial", ".tmp", ".download")


# -- a browser pointed at a folder ---------------------------------------------
#
# MEASURED 2026-09-29 on Chromium 149, 151 and 153 and Edge 154, attached
# over DevTools and launched alike, headed and headless. Once
# set_download_dir has pointed the browser at a folder, the browser writes
# each download there under the site's own name, as "<name>.crdownload"
# while it arrives, and that file is the ONLY copy. Playwright still raises
# the download event, and the event's save_as then writes an empty file
# without complaint. A finished file of the same name already in the folder
# is written over in place.
#
# Eleven apps took the empty file for a failure, asked the provider for the
# document a second time, saved that answer and left the browser's file in
# the folder, a second copy of every document that outlived the archived
# one. core/tests/test_every_app_leaves_no_copy.py drives each app that
# points the browser at a folder, in a real browser, to hold all of this.

def set_download_dir(page, dirpath) -> None:
    """Point the attached browser's downloads at `dirpath`, over CDP.

    Best effort on purpose. A browser that refuses is not a reason to stop
    a run, because the app still has the other ways of taking a document,
    and the failure is written down rather than raised.

    It reaches the browser's own context, the one an attached browser is
    used through. A context made with new_context is not pointed anywhere.
    """
    try:
        Path(dirpath).mkdir(parents=True, exist_ok=True)
        cdp = page.context.new_cdp_session(page)
        cdp.send("Browser.setDownloadBehavior",
                 {"behavior": "allow", "downloadPath": str(dirpath), "eventsEnabled": True})
    except Exception as e:
        log.info("set_download_dir failed: %s", e)


class Snapshot(set):
    """The names in a download folder at one moment, as a set of names like
    it always was, which also remembers each file's size and modification
    time.

    The browser writes a finished file of the same name over the old one
    in place, so compared by name alone that download never arrives. One
    file left in the folder under a provider's usual name hid every later
    download of that name, for good."""

    def __init__(self, names=(), stamps=None):
        super().__init__(names)
        self.stamps = dict(stamps or {})


def _stamp(path) -> tuple:
    st = os.stat(path)
    return st.st_size, st.st_mtime_ns


def snapshot(dl_dir) -> set:
    """What is in the download folder now, to compare against later."""
    if not dl_dir:
        return Snapshot()
    try:
        names = os.listdir(dl_dir)
    except OSError:
        return Snapshot()
    stamps = {}
    for name in names:
        try:
            stamps[name] = _stamp(os.path.join(dl_dir, name))
        except OSError:
            pass
    return Snapshot(names, stamps)


def arrived(dl_dir, before) -> list:
    """Finished files in `dl_dir` that were not there at `before`, or have
    been written again since, in name order.

    A file written again is seen only when `before` came from snapshot().
    A plain set of names still works and sees new names only."""
    if not dl_dir:
        return []
    try:
        names = sorted(os.listdir(dl_dir))
    except OSError:
        return []
    stamps = getattr(before, "stamps", None) or {}
    out = []
    for name in names:
        if name.lower().endswith(UNFINISHED):
            continue
        if name not in before:
            out.append(name)
            continue
        if name in stamps:
            try:
                if _stamp(os.path.join(dl_dir, name)) != stamps[name]:
                    out.append(name)
            except OSError:
                pass
    return out


def earlier_finished(dl_dir, before) -> int:
    """How many downloads that were still being written at `before` have
    finished, or gone, since.

    An earlier capture that gave up can leave its download arriving, and it
    can finish under any name, including this one's. While one has, the
    folder cannot say which file is whose. Newrez learned this on a tester's
    account (#38)."""
    if not dl_dir:
        return 0
    try:
        now = set(os.listdir(dl_dir))
    except OSError:
        return 0
    return len({n for n in before if n.lower().endswith(UNFINISHED)} - now)


def _starts_like_pdf(path) -> bool:
    try:
        with open(path, "rb") as f:
            return f.read(5) == b"%PDF-"
    except OSError:
        return False


def take_new_pdf(dl_dir, before: set, out_path: Path) -> bool:
    """Move a finished PDF that appeared in `dl_dir` since `before` to
    `out_path`.

    A file still downloading is skipped, and so is one that is empty or
    does not start with the PDF marker, because a site that answers an
    expired link with an HTML error page still produces a file.

    A file written again in place since `before` counts as appeared, when
    `before` came from snapshot(). Nothing is taken while a download that
    was still being written at `before` has finished since, because it may
    have finished as the very file that looks new.
    """
    if not dl_dir:
        return False
    out_path = Path(out_path)
    # Listed first and checked after, so an earlier download that finishes
    # in between is seen as finished rather than taken.
    names = arrived(dl_dir, before)
    if names and earlier_finished(dl_dir, before):
        log.info("an earlier download finished during this one, so the download "
                 "folder cannot say which file is this document")
        return False
    for name in names:
        src = Path(dl_dir) / name
        try:
            if src.stat().st_size == 0 or not _starts_like_pdf(src):
                continue
            if out_path.exists():
                out_path.unlink()
            shutil.move(str(src), str(out_path))
            return True
        except OSError:
            continue
    return False


def _named(names, name: str) -> list:
    """Those of `names` that are `name`, or the browser's " (2)" form of it,
    which it writes when a download of that name is still arriving."""
    if not name:
        return []
    stem, ext = os.path.splitext(name)
    again = re.compile(r"^%s \(\d+\)%s$" % (re.escape(stem), re.escape(ext)), re.I)
    return [n for n in names if n.casefold() == name.casefold() or again.match(n)]


def take_download(download, dl_dir, before, out_path) -> str:
    """Save a download the page raised, from wherever its bytes really are.
    Says "event" or "folder" for where they came from, or "" when neither
    held a PDF.

    The event's own file is used when it is a PDF, which is what a browser
    that was never pointed at a folder gives. Otherwise the file the
    browser wrote into `dl_dir` is moved to `out_path`. Moved, so no copy
    of the document stays behind, and taken rather than asked for again,
    so the provider is asked once.

    The folder's file is taken only when the folder can say it is this
    download's. It carries the event's name, or the " (2)" form of it, it
    is the only such file that arrived since `before`, and no download that
    was still being written at `before` has finished since."""
    out_path = Path(out_path)
    saved = False
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        download.save_as(str(out_path))
        saved = True
    except Exception as e:
        log.info("saving the download event failed: %s", e)
    if saved and _starts_like_pdf(out_path):
        return "event"
    # An empty file under a document's name is the one thing a failed
    # capture must never leave, and here it would be the event's.
    try:
        if out_path.exists() and not _starts_like_pdf(out_path):
            out_path.unlink()
    except OSError:
        pass
    if not dl_dir:
        return ""
    try:
        name = download.suggested_filename or ""
    except Exception:
        name = ""
    mine = _named(arrived(dl_dir, before), name)
    if not mine:
        return ""
    if earlier_finished(dl_dir, before):
        log.info("an earlier download finished during this one, so the download "
                 "folder cannot say which file is this document")
        return ""
    if len(mine) > 1:
        log.info("%d files in the download folder could be this download, "
                 "so none was taken", len(mine))
        return ""
    src = Path(dl_dir) / mine[0]
    if not _starts_like_pdf(src):
        return ""
    try:
        if out_path.exists():
            out_path.unlink()
        shutil.move(str(src), str(out_path))
    except OSError as e:
        log.info("could not move the downloaded file: %s", e)
        return ""
    return "folder"


def _same(a: Path, b: Path) -> bool:
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def clear_copies(dl_dir, before, saved) -> int:
    """Remove files that arrived in `dl_dir` since `before` and are exact
    copies of `saved`. Says how many.

    A capture can end up with its document some other way, read off the
    answer in flight or asked for again, while the browser also saved it
    into the folder. That file is the same document, and left there it is
    a copy nobody knows about, which outlives the archived one when that is
    deleted after an import. Nothing that differs from `saved` by a single
    byte is touched, whoever put it there, because the browser saves
    whatever else was downloaded in it into the same folder."""
    if not dl_dir or not saved:
        return 0
    saved = Path(saved)
    try:
        size = saved.stat().st_size
    except OSError:
        return 0
    if not size:
        return 0
    gone = 0
    for name in arrived(dl_dir, before):
        path = Path(dl_dir) / name
        try:
            if path.stat().st_size != size or _same(path, saved):
                continue
            if filecmp.cmp(str(path), str(saved), shallow=False):
                path.unlink()
                gone += 1
        except OSError:
            continue
    return gone


def clear_archived_copies(dl_dir, archived) -> tuple:
    """Remove files in `dl_dir` that are exact copies of a document in
    `archived`, the paths an app's own records name. Says how many went and
    how many stayed.

    Before 2026-09-29 eleven apps left the browser's file of every document
    they saved in their download folder. This clears those, and only those.
    A file goes when its bytes are exactly a document the archive still
    holds, so nothing is lost. Anything else stays, a file still arriving,
    one the archive has no copy of, and one whose document was deleted
    from the archive after an import, since then nothing proves it is a
    copy.

    Best effort, like set_download_dir. It runs as a run starts, and a
    record it cannot read is skipped rather than a reason to stop."""
    if not dl_dir:
        return 0, 0
    folder = Path(dl_dir)
    try:
        here = [p for p in folder.iterdir()
                if p.is_file() and not p.name.lower().endswith(UNFINISHED)]
    except OSError:
        return 0, 0
    if not here:
        return 0, 0
    by_size: dict = {}
    for item in archived or ():
        try:
            if not item or not isinstance(item, (str, os.PathLike)):
                continue
            path = Path(item)
            if not path.is_file() or path.parent.resolve() == folder.resolve():
                continue
            size = path.stat().st_size
        except (OSError, ValueError):
            continue
        if size:
            by_size.setdefault(size, []).append(path)
    removed = kept = 0
    for path in here:
        try:
            twins = by_size.get(path.stat().st_size, ())
            if any(filecmp.cmp(str(path), str(t), shallow=False) for t in twins):
                path.unlink()
                removed += 1
                continue
        except OSError:
            pass
        kept += 1
    # Said on the run that clears something, and not on every run after it
    # while files the archive cannot vouch for stay.
    if removed:
        log.info("removed %d exact copies of archived documents from %s, and left "
                 "%d other files there", removed, folder.name, kept)
    return removed, kept


# -- a PDF the page fetches for us ---------------------------------------------
#
# Some documents cannot be reached with an ordinary request, because the
# session lives in the browser. The page fetches them for us and hands back
# base64. Four versions of this snippet were in the apps. Two built the
# base64 one byte at a time, which is correct and slow enough to notice on a
# large statement. One, U.S. Bank's, checks the address again inside the page
# and refuses to follow a redirect, which none of the others do.
#
# This is the chunked one, with the in-page check available rather than
# assumed, so an app keeps whatever it does today and can be tightened
# deliberately instead of by accident.

FETCH_AS_B64 = r"""async ({url, hosts, subdomains, noRedirect}) => {
    if (hosts && hosts.length) {
        const target = new URL(url, location.href);
        const origin = target.protocol === "blob:" ? new URL(url.slice(5)) : target;
        const host = (origin.hostname || "").toLowerCase().replace(/\.$/, "");
        const allowed = hosts.some(h => host === h || (subdomains && host.endsWith("." + h)));
        if (origin.protocol !== "https:" || origin.username || origin.password
                || (origin.port && origin.port !== "443") || !allowed) {
            throw new Error("Refusing an off-host document request");
        }
    }
    const opts = noRedirect ? {redirect: 'error', credentials: 'include'}
                            : {credentials: 'include'};
    const r = await fetch(url, opts);
    if (!r.ok) return null;
    const buf = new Uint8Array(await r.arrayBuffer());
    let s = '';
    for (let i = 0; i < buf.length; i += 0x8000) {
        s += String.fromCharCode.apply(null, buf.subarray(i, i + 0x8000));
    }
    return btoa(s);
}"""


# The same fetch, answering with what came back as well as the bytes.
#
# Four call sites in two apps asked this for a dictionary and got a
# string, because each app used to carry its own copy that answered with
# one and the shared version answers with base64 alone. One of them read
# `.get("b64")` off it and a tester's full run died on the thirteenth
# receipt with AttributeError (#43).
#
# The dictionary is kept rather than the call sites flattened, because
# two of the four are survey code, and the status and the content type
# are exactly what settles a round when a link answers with something
# other than a document.
FETCH_WITH_STATUS = r"""async ({url, hosts, subdomains, noRedirect}) => {
    if (hosts && hosts.length) {
        const target = new URL(url, location.href);
        const origin = target.protocol === "blob:" ? new URL(url.slice(5)) : target;
        const host = (origin.hostname || "").toLowerCase().replace(/\.$/, "");
        const allowed = hosts.some(h => host === h || (subdomains && host.endsWith("." + h)));
        if (origin.protocol !== "https:" || origin.username || origin.password
                || (origin.port && origin.port !== "443") || !allowed) {
            throw new Error("Refusing an off-host document request");
        }
    }
    const opts = noRedirect ? {redirect: 'error', credentials: 'include'}
                            : {credentials: 'include'};
    const r = await fetch(url, opts);
    const out = {status: r.status, type: (r.headers.get('content-type') || '')};
    if (!r.ok) return out;
    const buf = new Uint8Array(await r.arrayBuffer());
    let s = '';
    for (let i = 0; i < buf.length; i += 0x8000) {
        s += String.fromCharCode.apply(null, buf.subarray(i, i + 0x8000));
    }
    out.b64 = btoa(s);
    return out;
}"""


def fetch_with_status(page, url: str, hosts=(), *, subdomains: bool = True,
                      no_redirect: bool = False) -> dict:
    """What `url` answered with, as {status, type, b64}, fetched by the
    page with its own session. Always a dictionary, so a caller reading a
    key off it cannot meet a string."""
    got = page.evaluate(FETCH_WITH_STATUS, {
        "url": url,
        "hosts": [str(h).lower().rstrip(".") for h in hosts],
        "subdomains": bool(subdomains),
        "noRedirect": bool(no_redirect),
    })
    return got if isinstance(got, dict) else {}


def fetch_as_b64(page, url: str, hosts=(), *, subdomains: bool = True,
                 no_redirect: bool = False):
    """The bytes of `url`, fetched by the page with its own session, as
    base64, or None. With `hosts`, the page checks the address itself
    before asking for it."""
    return page.evaluate(FETCH_AS_B64, {
        "url": url,
        "hosts": [str(h).lower().rstrip(".") for h in hosts],
        "subdomains": bool(subdomains),
        "noRedirect": bool(no_redirect),
    })


# -- a PDF the site opened somewhere ------------------------------------------
#
# Each of these was identical in the eleven apps cut from one scaffold. They
# take the app's own is_safe_url rather than closing over one, because the
# hosts are the part that is really per-provider and the rest is not.

def fetch_pdf(page, href: str, is_safe_url) -> Optional[bytes]:
    """A PDF link fetched from inside the signed-in page, cookies and all.
    None unless the address passes the app's guard and the answer really is
    a PDF."""
    if not is_safe_url(href):
        return None
    try:
        resp = page.context.request.get(href, timeout=60000)
        body = resp.body() if resp.ok else b""
    except Exception as e:
        log.info("fetch %s failed: %s", redact(href)[:80], e)
        return None
    return body if body[:5] == b"%PDF-" else None


def take_new_tab(page, new_pages, out_path: Path, is_safe_url) -> bool:
    """A PDF that a click opened in a new tab, written to `out_path`.

    A blob: tab was minted by the page itself and is read through the page
    that made it. Any other address is host checked before its bytes are
    fetched with the session.
    """
    for extra in new_pages:
        try:
            extra.wait_for_load_state("domcontentloaded", timeout=15000)
            url = extra.url or ""
            if url.startswith("blob:"):
                b64 = fetch_as_b64(page, url)
            elif is_safe_url(url):
                b64 = fetch_as_b64(extra, url)
            else:
                continue
            if not b64:
                continue
            data = base64.b64decode(b64)
            if data[:5] == b"%PDF-":
                out_path.write_bytes(data)
                return True
        except Exception as e:
            log.info("tab capture failed: %s", e)
    return False


def take_same_tab(page, start_url: str, out_path: Path, trace, is_safe_url) -> bool:
    """A PDF the click opened in this very tab, the way SMUD's vendor does
    it. The tab's address moved to a document, its bytes are fetched through
    the session, and the tab is sent back where it was."""
    url = page.url or ""
    if not url or url == start_url or not is_safe_url(url):
        return False
    kind = ""
    try:
        kind = (page.evaluate("() => document.contentType || ''") or "").lower()
    except Exception:
        pass
    if trace is not None:
        trace.append({"note": "the tab moved", "url": redact(url)[:160],
                      "content_type": kind[:40]})
    if "pdf" not in kind and not url.lower().split("?")[0].endswith(".pdf"):
        return False
    body = b""
    try:
        resp = page.context.request.get(url, timeout=60000)
        body = resp.body() if resp.ok else b""
    except Exception as e:
        log.info("same-tab fetch failed: %s", e)
    if body[:5] != b"%PDF-":
        try:
            b64 = fetch_as_b64(page, url)
            body = base64.b64decode(b64) if b64 else b""
        except Exception:
            body = b""
    # Back where it was, whether or not the bytes came, so the next row is
    # looked for on the list rather than inside a document.
    try:
        page.go_back(wait_until="domcontentloaded", timeout=15000)
        page.wait_for_timeout(1500)
    except Exception:
        pass
    if body[:5] == b"%PDF-":
        out_path.write_bytes(body)
        return True
    return False
