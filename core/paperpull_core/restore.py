"""Put the page back the way it was found.

Saving a document means taking everything except the document off the
screen. The page is a shop, the receipt is a dialog on top of it, and
printing what the browser has means hiding the shop. That is a display
change, it lives only in the tab, and the next navigation throws it
away.

The trouble is a run that does not navigate. Costco's receipt is a
dialog with no address of its own, so the second document of a run was
looked for on a page where every element had been set to display none
and none of it could be clicked. The first document worked and every one
after it failed, and from outside that is indistinguishable from a page
that did not load. It cost two live runs to find, and the fix at the
time was to reload before each one, which works and is a page load per
document.

So a capture is stateful and this is the invariant. Take a snapshot
before, put it back after, in a finally, and record whether the putting
back worked. Any app's isolation is covered, whatever it touches and
however it is written, because the snapshot is of the page rather than
of the change.

WHAT IT REMEMBERS

Each element's own `style` attribute, as it was, kept on the element as
a property rather than an attribute so it changes nothing a page can
see and nothing a screenshot would show. An element that had no style
attribute is remembered as having none, and gets none back.

That covers the inline changes an isolation makes. It does not cover a
class added to an element or a stylesheet rewritten, and an app doing
either should say so rather than rely on this.
"""
from __future__ import annotations

from typing import Optional

from .failure import _count, error_kind

# Every element with a style attribute of its own, plus every element an
# isolation is about to touch. Walking the whole document is one pass and
# a few milliseconds, and it is the only way to know what "as it was"
# means for an element that had no style at all.
_SNAPSHOT_JS = r"""
() => {
  let n = 0;
  for (const el of document.querySelectorAll('*')) {
    // A property and not an attribute, so nothing about the page
    // changes and nothing new appears in its markup.
    if (el.__ppStyle === undefined) {
      el.__ppStyle = el.getAttribute('style');
      n += 1;
    }
  }
  document.documentElement.__ppStyle =
    document.documentElement.getAttribute('style');
  return n;
}
"""

_RESTORE_JS = r"""
() => {
  let restored = 0, changed = 0;
  const put = (el) => {
    if (el.__ppStyle === undefined) return;
    const was = el.__ppStyle;
    const now = el.getAttribute('style');
    if (now !== was) changed += 1;
    if (was === null) el.removeAttribute('style');
    else el.setAttribute('style', was);
    delete el.__ppStyle;
    restored += 1;
  };
  put(document.documentElement);
  for (const el of document.querySelectorAll('*')) put(el);
  // What the page looks like now that it is back, which is the thing
  // worth checking rather than the thing worth assuming.
  let visible = 0;
  for (const el of document.querySelectorAll('body *')) {
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) continue;
    const s = getComputedStyle(el);
    if (s.display !== 'none' && s.visibility !== 'hidden') visible += 1;
  }
  return {restored: restored, changed: changed, visible: visible,
          body_overflow: getComputedStyle(document.body).overflow};
}
"""


def snapshot(page) -> int:
    """Remember every element's own style. Returns how many, or 0."""
    try:
        return _count(page.evaluate(_SNAPSHOT_JS))
    except Exception:
        return 0


def restore(page) -> dict:
    """Put them all back, and say what the page looks like afterwards.

    `ok` is the answer to the only question that matters, which is
    whether there is anything on screen to work with now."""
    try:
        raw = page.evaluate(_RESTORE_JS)
    except Exception as e:
        return {"ok": False, "evaluation": error_kind(e)}
    if not isinstance(raw, dict):
        return {"ok": False, "evaluation": "unreadable"}
    out = {"restored": _count(raw.get("restored")),
           "changed": _count(raw.get("changed")),
           "visible_after": _count(raw.get("visible")),
           "locked_after": raw.get("body_overflow") == "hidden"}
    out["ok"] = bool(out["visible_after"]) and not out["locked_after"]
    return out


class restoring:
    """A capture, with the page put back afterwards whatever happens.

        with restoring(page, journal=self.journal):
            site.isolate_receipt(page)
            render_to_pdf(page)

    The putting back is in a finally, because the case that matters is
    the one where the rendering raised. A run that fails on one document
    and leaves the page hidden fails on every document after it for a
    reason that has nothing to do with them."""

    def __init__(self, page, journal=None, note: str = "restore the page"):
        self.page = page
        self.journal = journal
        self.note = note
        self.result: Optional[dict] = None

    def __enter__(self):
        snapshot(self.page)
        return self

    def __exit__(self, kind, value, tb):
        self.result = restore(self.page)
        if self.journal is not None:
            try:
                self.journal.result(
                    self.note if self.result.get("ok")
                    else "could not put the page back",
                    **{k: v for k, v in self.result.items() if k != "ok"})
            except Exception:
                pass
        return False  # never swallow the thing that actually went wrong
