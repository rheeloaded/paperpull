"""A PDF the page builds in its own memory, kept as it is made.

Some sites build a document in the page and hand it to the browser as a
blob: address, opened in a new tab or saved through an anchor. American
Family opens each statement in a new tab at blob:https://myaccount.amfam.com/...
(#45), and Apple Card saves each statement through an anchor (#52, whose
own copy of this lives in apps/applecard). A page can revoke such an
address the moment the tab has it, and after that nothing can read it back
by its address. So URL.createObjectURL is wrapped to keep a reference to
every PDF blob the page makes, and the blob itself is read afterwards,
whatever became of its address.

The wrapper passes everything through unchanged, so the page and the
browser do exactly what they would have done. Nothing is pressed, blocked
or suppressed. Arming it again forgets what was kept, so a document is only
ever taken from a blob made after its own press began.

The same wrapper counts the tabs the page asks for. The page knows it asked
the moment it asks, and Playwright hears of the tab some time later, after
the press has taken its document from the page on a busy machine. A press
that closed only the tabs Playwright had heard of left that one open in the
person's browser, so close_new_tabs waits for it first.
"""
from __future__ import annotations

import base64
import logging
import time
from typing import Optional, Tuple

log = logging.getLogger(__name__)

HOOK_JS = r"""() => {
  window.__paperpullBlobs = [];
  window.__paperpullNames = [];
  window.__paperpullOpened = [];
  window.__paperpullTabs = [];
  if (window.__paperpullBlobHook) return true;
  window.__paperpullBlobHook = true;
  // The addresses the page asks to open in a new tab, so a caller can tell
  // the PDF it opened from any other the page makes, and the new tabs that
  // makes, each window that came back, or true for one that cannot be
  // followed. A window comes back unless the browser refused one, or the
  // page asked for none to come back. A window the page had opened before,
  // which a name sends it back to, a frame of this page or the page itself
  // is no new tab.
  const opener = window.open;
  const known = new WeakSet();
  window.open = function (url, target, features) {
    try { window.__paperpullOpened.push(String(url || '')); } catch (e) {}
    const opened = opener.apply(this, arguments);
    try {
      const where = String(target || '_blank').toLowerCase();
      const apart = /noopener|noreferrer/.test(String(features || '').toLowerCase());
      const away = !['_self', '_parent', '_top'].includes(where);
      if (away && opened) {
        const fresh = !known.has(opened) && opened.top === opened && opened !== window.top;
        known.add(opened);
        if (fresh) window.__paperpullTabs.push(opened);
      } else if (away && apart) {
        window.__paperpullTabs.push(true);
      }
    } catch (e) {}
    return opened;
  };
  const made = URL.createObjectURL.bind(URL);
  URL.createObjectURL = function (obj) {
    const url = made(obj);
    try {
      if (obj instanceof Blob && ['application/pdf', 'application/octet-stream', ''].includes(obj.type)) {
        window.__paperpullBlobs.push({url, blob: obj});
      }
    } catch (e) {}
    return url;
  };
  const clicked = HTMLAnchorElement.prototype.click;
  HTMLAnchorElement.prototype.click = function () {
    try {
      // A download mark with no name given is still one.
      if (this.hasAttribute('download')) window.__paperpullNames.push({href: this.href, name: String(this.download)});
      if (this.target === '_blank') {
        window.__paperpullOpened.push(String(this.href || ''));
        // A link that saves what it points at opens no tab, a bare download
        // mark with no name included.
        if (!this.hasAttribute('download')) window.__paperpullTabs.push(true);
      }
    } catch (e) {}
    return clicked.apply(this, arguments);
  };
  return true;
}"""

# How many of the new tabs the page asked for since it was last armed are
# still open, or -1 when this window was never armed, a page that has moved
# on since. One that closed itself, as a tab does when what it was sent to
# turns into a download, is no longer waited for. One asked for with no
# window back, or by a link, cannot be followed, so if it never comes, or
# turns into a download, it costs the whole wait.
TABS_JS = r"""() => Array.isArray(window.__paperpullTabs)
  ? window.__paperpullTabs.filter((w) => { try { return w === true || !w.closed; } catch (e) { return true; } }).length
  : -1"""

# A PDF blob the page made since the hook was armed, as base64, with the name
# its anchor gave it, or empty. Without `want` the newest. With it, only one
# at an address `want` names, the addresses in want.urls or, with
# want.opened, one the page asked to open in a new tab, and only when
# exactly one PDF is there, since two would be a guess. Anything that does
# not begin with the PDF marker, or is implausibly small or large, is passed
# over.
TAKE_JS = r"""async (want) => {
  const blobs = window.__paperpullBlobs || [];
  const names = window.__paperpullNames || [];
  // An address is compared without its fragment. A page that opens
  // blob:...#page=1 opens the same blob (review of 0.41.0).
  const bare = (u) => String(u || '').split('#')[0];
  const allowed = want ? new Set([...(want.urls || []),
                                  ...(want.opened ? (window.__paperpullOpened || []) : [])].map(bare)) : null;
  const pdfs = [];
  for (let i = blobs.length - 1; i >= 0; i--) {
    const {url, blob} = blobs[i];
    if (allowed && !allowed.has(bare(url))) continue;
    if (!blob || blob.size < 100 || blob.size > 30000000) continue;
    const head = new Uint8Array(await blob.slice(0, 5).arrayBuffer());
    if (String.fromCharCode(...head) !== '%PDF-') continue;
    pdfs.push({url, blob});
    if (!allowed) break;
  }
  if (pdfs.length !== 1) return {b64: '', name: '', count: blobs.length, matched: pdfs.length};
  const {url, blob} = pdfs[0];
  const buf = new Uint8Array(await blob.arrayBuffer());
  let s = '';
  for (let j = 0; j < buf.length; j += 0x8000) s += String.fromCharCode.apply(null, buf.subarray(j, j + 0x8000));
  const named = names.filter(n => n.href === url).map(n => n.name);
  return {b64: btoa(s), name: named.length ? named[named.length - 1] : '', count: blobs.length, matched: 1};
}"""


def arm(page) -> bool:
    """Start keeping the PDF blobs the page makes, and forget any kept for
    an earlier document. False when the page could not be asked."""
    try:
        return bool(page.evaluate(HOOK_JS))
    except Exception as e:
        log.info("blob hook not armed: %s", e)
        return False


def take(page, urls: Optional[list] = None, opened: bool = False) -> Optional[Tuple[bytes, str]]:
    """A PDF the page made since it was armed, and the name the page gave it
    if it saved it through an anchor, or None.

    Without arguments the newest. A caller that knows which blob is its
    document says so, since the newest can be another the same press made,
    or a late one from an earlier press. `urls`, addresses such as the one a
    tab it opened shows, and `opened`, any address the page itself asked to
    open in a new tab. Then only a PDF at one of those is taken, and only
    when there is exactly one."""
    want = {"urls": list(urls or []), "opened": bool(opened)} if (urls or opened) else None
    try:
        got = page.evaluate(TAKE_JS, want)
    except Exception:
        return None
    if not isinstance(got, dict) or not got.get("b64"):
        return None
    try:
        data = base64.b64decode(got["b64"])
    except Exception:
        return None
    if data[:5] != b"%PDF-":
        return None
    return data, str(got.get("name") or "")


# The addresses of the links with a download mark the page clicked since it
# was armed, oldest first, or null when this window was never armed.
SAVED_JS = r"""() => Array.isArray(window.__paperpullNames)
  ? window.__paperpullNames.map((n) => String((n && n.href) || '')) : null"""


def saved_links(page) -> Optional[list]:
    """The addresses of the links with a download mark the page clicked since
    it was armed, oldest first, or None when the page cannot say, one never
    armed or one that has moved on since. A page saves a document it built
    or fetched this way, and the address says where that document is, a
    blob of the page's own or an address of the site's. The name the page
    gave the file is not here, since a provider can name a statement after
    the account it belongs to."""
    try:
        got = page.evaluate(SAVED_JS)
    except Exception:
        return None
    return [str(h) for h in got] if isinstance(got, list) else None


def tabs_asked(page) -> Optional[int]:
    """How many of the new tabs the page asked for since it was last armed
    are still open, or None when it cannot say, a page that has moved on
    since or was never armed."""
    try:
        n = page.evaluate(TABS_JS)
    except Exception:
        return None
    return n if isinstance(n, int) and n >= 0 else None


def close_new_tabs(page, before, armed_at=None, wait_ms: int = 5000) -> None:
    """Close every tab that opened since `before`, which holds the tabs that
    were open before the press.

    A tab the page asked for since it was last armed, when `armed_at` held
    the open tabs, that Playwright has not heard of yet is waited for first,
    `wait_ms` at most, since closing only the tabs already heard of left it
    open (a full run on a busy machine, 2026-10-01). A page that cannot say
    what it asked for is not waited on. Nothing here raises."""
    try:
        ctx = page.context
        since = before if armed_at is None else armed_at
        deadline = time.monotonic() + wait_ms / 1000.0
        while len([p for p in ctx.pages if p not in since]) < (tabs_asked(page) or 0):
            if time.monotonic() >= deadline:
                log.info("a tab the page asked for never came in %d ms", wait_ms)
                break
            try:
                ctx.wait_for_event("page", timeout=200)
            except Exception as e:
                if type(e).__name__ != "TimeoutError":
                    log.info("could not wait for a tab: %s", e)
                    break
        opened = [p for p in ctx.pages if p not in before]
    except Exception as e:
        log.info("could not tell which tabs a press opened: %s", e)
        return
    for extra in opened:
        try:
            extra.close()
        except Exception:
            pass
