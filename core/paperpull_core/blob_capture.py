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
"""
from __future__ import annotations

import base64
import logging
from typing import Optional, Tuple

log = logging.getLogger(__name__)

HOOK_JS = r"""() => {
  window.__paperpullBlobs = [];
  window.__paperpullNames = [];
  window.__paperpullOpened = [];
  if (window.__paperpullBlobHook) return true;
  window.__paperpullBlobHook = true;
  // The addresses the page asks to open in a new tab, so a caller can tell
  // the PDF it opened from any other the page makes.
  const opener = window.open;
  window.open = function (url) {
    try { window.__paperpullOpened.push(String(url || '')); } catch (e) {}
    return opener.apply(this, arguments);
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
      if (this.download) window.__paperpullNames.push({href: this.href, name: String(this.download)});
      if (this.target === '_blank') window.__paperpullOpened.push(String(this.href || ''));
    } catch (e) {}
    return clicked.apply(this, arguments);
  };
  return true;
}"""

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
