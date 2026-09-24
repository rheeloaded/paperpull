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
import logging
import os
import shutil
from pathlib import Path
from typing import Optional

from .redact import redact

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
