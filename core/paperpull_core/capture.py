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

from .receipt_pdf import ZIP_MAGIC
from .redact import redact

log = logging.getLogger("paperpull.capture")

# A browser writes a download under a temporary name and renames it when it
# finishes, so a file still carrying one of these is not ours yet.
UNFINISHED = (".crdownload", ".part", ".partial", ".tmp", ".download")


# -- what a document looks like -------------------------------------------------
#
# A PDF begins with this, and so does every document an app files.
#
# Some providers hand a tax form over as a ZIP holding its PDF, and every
# docs module has a branch that opens one with receipt_pdf.open_zip.
# MEASURED 2026-09-29 on Chromium 153, a
# ZIP a page hands over is always a download, sent as application/zip or as
# application/octet-stream, with an attachment header or without, and from
# a link that opens a new tab as well. Its answer cannot be read off the
# response, as no download's can, so its bytes are only ever in the event's
# own file or in the folder the browser was pointed at, and take_download
# and take_new_pdf are the only readers of either. Until then both took a
# PDF alone, and that branch never ran in any app that takes a download
# through them (core/tests/test_every_app_opens_a_zipped_download.py).
#
# A ZIP is taken only when the caller says it can open one, zip_ok. Delivery
# reads the folder through take_new_pdf as well, and it checks a document's
# identity from its text, which a ZIP does not have.
PDF_MAGIC = b"%PDF-"


def is_document(data, zip_ok: bool = False) -> bool:
    """Whether bytes that begin with `data` are a document an app can take.
    A PDF, and with `zip_ok` a ZIP as well, which the app then opens."""
    head = bytes(data[:5]) if data else b""
    return head == PDF_MAGIC or (bool(zip_ok) and head[:4] == ZIP_MAGIC)


# -- a browser pointed at a folder ---------------------------------------------
#
# MEASURED 2026-09-29 on Windows, in Chromium 149, 151 and 153 and Edge 154,
# attached over DevTools and launched alike, headed and headless. Once
# set_download_dir has pointed the browser at a folder, the browser writes
# each download there under the site's own name, as "<name>.crdownload"
# while it arrives, and that file is the ONLY copy. Playwright still raises
# the download event, and the event's save_as then writes an empty file
# without complaint. A finished file of the same name already in the folder
# is written over in place. Given a relative folder, as an install gives it
# by default, the browser canceled every download instead.
#
# Eleven apps took the empty file for a failure, asked the provider for the
# document a second time, saved that answer and left the browser's file in
# the folder, a second copy of every document that outlived the archived
# one. core/tests/test_every_app_leaves_no_copy.py drives each app that
# points the browser at a folder, in a real browser, to hold all of this.
#
# Not every browser does this. A tester's Chrome 154 on macOS, attached over
# DevTools, gave the download event the whole file and left no copy in the
# output folder (#57, 2026-09-29), and why is not known. So take_download
# keeps the event's file whenever it is a PDF, and goes to the folder only
# when it is not.

def set_download_dir(page, dirpath) -> None:
    """Point the attached browser's downloads at `dirpath`, over CDP.

    Best effort on purpose. A browser that refuses is not a reason to stop
    a run, because the app still has the other ways of taking a document,
    and the failure is written down rather than raised.

    It reaches the browser's own context, the one an attached browser is
    used through. A context made with new_context is not pointed anywhere.

    The folder is made absolute first. An install passes it relative by
    default, output_dir being ".", and given a relative folder Chromium and
    Edge on Windows accept the setting and then cancel every download
    (measured 2026-09-29). In those browsers, no download had landed in
    such an install before this. The setting lasts while the app is
    attached, and the browser's own folder is back once it has gone.
    """
    try:
        folder = Path(dirpath).resolve()
        folder.mkdir(parents=True, exist_ok=True)
        cdp = page.context.new_cdp_session(page)
        cdp.send("Browser.setDownloadBehavior",
                 {"behavior": "allow", "downloadPath": str(folder), "eventsEnabled": True})
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


def _starts_like(path, zip_ok: bool = False) -> bool:
    """Whether the file at `path` begins like a document (is_document)."""
    try:
        with open(path, "rb") as f:
            return is_document(f.read(5), zip_ok)
    except OSError:
        return False


def _documents(dl_dir, names, zip_ok: bool) -> list:
    """Those of `names` in `dl_dir` that are finished, not empty, and begin
    like a document."""
    out = []
    for name in names:
        path = Path(dl_dir) / name
        try:
            if path.stat().st_size and _starts_like(path, zip_ok):
                out.append(path)
        except OSError:
            continue
    return out


def _all_same(paths) -> bool:
    """Whether every one of `paths` holds the same bytes, as a second
    download of the same document does."""
    try:
        first = paths[0]
        size = first.stat().st_size
        return all(p.stat().st_size == size and filecmp.cmp(str(first), str(p), shallow=False)
                   for p in paths[1:])
    except (OSError, IndexError):
        return False


def take_new_pdf(dl_dir, before: set, out_path: Path, *, zip_ok: bool = False) -> bool:
    """Move a finished PDF that appeared in `dl_dir` since `before` to
    `out_path`.

    A file still downloading is skipped, and so is one that is empty or
    does not start with the PDF marker, because a site that answers an
    expired link with an HTML error page still produces a file.

    A file written again in place since `before` counts as appeared, when
    `before` came from snapshot(). Nothing is taken while a download that
    was still being written at `before` has finished since, because it may
    have finished as the very file that looks new, and nothing is taken
    when two PDFs that differ arrived, since the folder cannot say which
    is this document. Newrez learned both on a tester's account (#38).

    With `zip_ok` a ZIP is taken as well, for an app that opens one, and
    it is a document in every rule above. A ZIP and a PDF that arrived
    together are two documents, and neither is taken.
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
    docs = _documents(dl_dir, names, zip_ok)
    if len(docs) > 1 and not _all_same(docs):
        log.info("%d different documents arrived in the download folder, so none "
                 "was taken as this one", len(docs))
        return False
    for src in docs:
        try:
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


def take_download(download, dl_dir, before, out_path, *, zip_ok: bool = False) -> str:
    """Save a download the page raised, from wherever its bytes really are.
    Says "event" or "folder" for where they came from, or "" when neither
    held a PDF. With `zip_ok` a ZIP is taken as well, for an app that opens
    one, and counts as a document in everything below.

    The event's own file is used when it is a PDF, which is what a browser
    that was never pointed at a folder gives. Otherwise the file the
    browser wrote into `dl_dir` is moved to `out_path`. Moved, so no copy
    of the document stays behind, and taken rather than asked for again,
    so the provider is asked once.

    The folder's file is taken only when the folder can say it is this
    download's. It carries the event's name, or the " (2)" form of it,
    every PDF that arrived since `before` is that same document, and no
    download that was still being written at `before` has finished since.

    A download event is not tied to the press that caused it, and one the
    last press started can arrive during this capture and raise the first
    event (#38). Two reviews found that the event's name alone then took
    it as this document. With another PDF there as well, nothing is taken,
    and the app's own ways of telling decide, as they did before. A
    download the last press started that lands before this press's own
    does is the only new PDF when it lands, and cannot be told from it
    here, as it never could."""
    out_path = Path(out_path)
    saved = False
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        download.save_as(str(out_path))
        saved = True
    except Exception as e:
        log.info("saving the download event failed: %s", e)
    if saved and _starts_like(out_path, zip_ok):
        return "event"
    # An empty file under a document's name is the one thing a failed
    # capture must never leave, and here it would be the event's.
    try:
        if out_path.exists() and not _starts_like(out_path, zip_ok):
            out_path.unlink()
    except OSError:
        pass
    if not dl_dir:
        return ""
    try:
        name = download.suggested_filename or ""
    except Exception:
        name = ""
    names = arrived(dl_dir, before)
    mine = _named(names, name)
    if not mine:
        return ""
    if earlier_finished(dl_dir, before):
        log.info("an earlier download finished during this one, so the download "
                 "folder cannot say which file is this document")
        return ""
    src = Path(dl_dir) / mine[0]
    docs = _documents(dl_dir, names, zip_ok)
    if src not in docs:
        return ""
    if len(docs) > 1 and not _all_same(docs):
        log.info("%d different documents arrived in the download folder, so none "
                 "was taken as this download", len(docs))
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
    try:
        home = folder.resolve()
    except (OSError, RuntimeError):
        home = folder
    by_size: dict = {}
    for item in archived or ():
        try:
            if not item or not isinstance(item, (str, os.PathLike)):
                continue
            path = Path(item)
            if not path.is_file() or path.parent.resolve() == home:
                continue
            size = path.stat().st_size
        except (OSError, ValueError, RuntimeError):
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

def fetch_pdf(page, href: str, is_safe_url, *, zip_ok: bool = False) -> Optional[bytes]:
    """A PDF link fetched from inside the signed-in page, cookies and all.
    None unless the address passes the app's guard and the answer really is
    a PDF, or with `zip_ok` a ZIP for the app to open."""
    if not is_safe_url(href):
        return None
    try:
        resp = page.context.request.get(href, timeout=60000)
        body = resp.body() if resp.ok else b""
    except Exception as e:
        log.info("fetch %s failed: %s", redact(href)[:80], e)
        return None
    return body if is_document(body, zip_ok) else None


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


# -- an answer that held nothing ----------------------------------------------
#
# MEASURED 2026-10-05 in Chromium 153 attached over DevTools, with every
# scaffold capture pressed against made-up pages in Playwright 1.62 and
# 1.63. A PDF the page fetches and reads with Response.blob() leaves the
# browser holding nothing of the answer it came in. Playwright 1.62 then
# asked the address again by itself, through the browser, for any answer
# with a length, and handed over the PDF. 1.63 asks again only for a GET of
# a font, image, manifest, media, script, stylesheet or text track, so a
# fetch or a page's answer now reads empty, without raising. One the page
# reads as an array buffer, a stream or through XMLHttpRequest still reads
# whole.
#
# Where the page also hands the PDF over as a download, at a blob address
# in a tab of its own, or by moving the tab to it, the capture still has
# it. Where the page keeps it and draws it itself, or shows it in a frame of
# its own page, a tab whose blob address it let go, or a data address, that
# empty answer was the only trace of it.

# How long asking again may take.
ASK_AGAIN_MS = 60000

# The page's own fetch, with the page's cookies, refusing a redirect, given
# up after `ms` whether or not the page's fetch heeds the signal, since a
# site can wrap fetch and pass the call on without it.
ASK_AGAIN_JS = r"""async ({url, ms}) => {
    const late = new Promise((_, no) => setTimeout(() => no(new Error('no answer in time')), ms));
    const ask = (async () => {
        const r = await fetch(url, {credentials: 'include', redirect: 'error',
                                    signal: AbortSignal.timeout(ms)});
        if (!r.ok) return null;
        const buf = new Uint8Array(await r.arrayBuffer());
        let s = '';
        for (let i = 0; i < buf.length; i += 0x8000) {
            s += String.fromCharCode.apply(null, buf.subarray(i, i + 0x8000));
        }
        return btoa(s);
    })();
    return await Promise.race([ask, late]);
}"""


def ask_again(page, answers: list, out_path: Path, is_safe_url, *, zip_ok: bool = False) -> bool:
    """The document behind the one answer a press read empty, asked for once
    more and written to `out_path`. True when it was.

    `answers` holds (method, address) for each answer to a request the press
    made that called itself a PDF and read empty. A capture calls this only
    once nothing else has brought the document, so a download, a tab or a
    second control the same press leads to has had its whole time first.
    Nothing is asked unless there is exactly one, and it answered a GET on
    an address the app's guard allows. Two could be two documents, a
    statement and a notice, and which one is this cannot be told, and a POST
    is never sent twice. It is asked from inside the page with the page's
    own fetch, so it goes with the browser's own cookies and is seen as
    the page, and only while the tab is on a site the guard allows, since a
    tab the press sent elsewhere, a sign-in page on another host or a
    viewer, would see the document's address in its own page. A redirect is
    refused rather than followed. Only a PDF, or with `zip_ok` a ZIP, is
    kept. `answers` is empty afterwards."""
    held = list(dict.fromkeys(answers))
    answers.clear()
    if not held:
        return False
    if len(held) > 1:
        log.info("%d answers held no PDF, and none was asked for again, since which "
                 "is this document cannot be told", len(held))
        return False
    method, url = held[0]
    if method != "GET":
        log.info("an answer to a %s held no PDF, and a %s is never sent twice", method, method)
        return False
    if not is_safe_url(url):
        return False
    try:
        where = page.url or ""
    except Exception:
        where = ""
    if where.startswith("blob:"):
        where = where[len("blob:"):]
    if not is_safe_url(where):
        log.info("the tab is not on the provider's site, so nothing was asked again")
        return False
    try:
        b64 = page.evaluate(ASK_AGAIN_JS, {"url": url, "ms": ASK_AGAIN_MS})
        data = base64.b64decode(b64) if b64 else b""
    except Exception as e:
        log.info("asking again for %s failed: %s", redact(url)[:80],
                 (str(e).splitlines() or [type(e).__name__])[0][:90])
        return False
    if is_document(data, zip_ok):
        out_path.write_bytes(data)
        return True
    log.info("asked again, %s gave no document", redact(url)[:80])
    return False


class RequestsSince:
    """The requests a press makes, from its own tab or a tab opened since it
    began, so an answer can be tied to that press.

    A late answer to the last document's press was saved under this one's
    name in E*TRADE (#36) and Newrez (#38), and State Farm saved a PDF that
    loaded in a tab of the person's that was already open (#37). So a request
    made before the press, or from a tab that was open before it, is not the
    press's, nor is one whose tab cannot be named, a service worker's. A
    redirect counts as the request it began with. Nothing in here raises."""

    def __init__(self, page, before=()):
        self._page = page
        self._before = list(before)
        self._made: list = []
        self._context = None
        try:
            self._context = page.context
            self._context.on("request", self._heard)
        except Exception:
            self._context = None

    def _heard(self, request):
        try:
            owner = request.frame.page
        except Exception:
            return
        try:
            if owner is self._page or not any(owner is p for p in self._before):
                self._made.append(request)
        except Exception:
            pass

    def made(self, request) -> bool:
        """Whether `request`, or the request its redirects began with, is one
        this press made."""
        try:
            first = request
            for _ in range(20):
                earlier = getattr(first, "redirected_from", None)
                if earlier is None:
                    break
                first = earlier
            return any(r is first for r in self._made)
        except Exception:
            return False

    def stop(self) -> None:
        if self._context is not None:
            try:
                self._context.remove_listener("request", self._heard)
            except Exception:
                pass
            self._context = None
