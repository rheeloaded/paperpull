"""Direct PDF generation and validation.

Never uses the Windows Print or Save As dialog. PDFs are produced by:
  1. Capturing a Playwright download event (download.save_as), or
  2. Chromium DevTools Page.printToPDF on the printable page (works in the
     headed supervised browser), or
  3. A short-lived *local* headless Chromium that takes the signed-in
     session's cookies for the provider's own hosts and renders the
     printable URL with page.pdf(), loading nothing the app's guard refuses.

Validation uses pypdf locally.
"""
from __future__ import annotations

import base64
import html as _html
import logging
import re
from pathlib import Path
from typing import Iterable, NamedTuple, Optional

from . import browser as _launcher
from . import intake as _intake
from . import pdf_reader as _pdf_reader
from .characters import whole_characters
from .identity import MIN_TEXT, amount_variants, date_variants, on_its_own
from .models import ValidationResult

log = logging.getLogger("paperpull.pdf")

# ---------------------------------------------------------------------------
# Provider binding
# ---------------------------------------------------------------------------
# Everything in this module is provider-agnostic except three facts, the name
# that validating a PDF must not be satisfied by, the host to use as
# <base href> when re-rendering a saved HTML snapshot, and the name shown in a
# failure message. The app binds its AppSpec once at import time.

_SPEC = None


def bind(spec) -> None:
    """Attach this process's AppSpec. Called by the app's storage shim."""
    global _SPEC
    _SPEC = spec


def _provider_name() -> str:
    return _SPEC.provider if _SPEC else "the provider"


def _provider_token() -> str:
    return _SPEC.token if _SPEC else ""


_NOT_ALNUM = re.compile(r"[^0-9a-z]")


def _plain(value) -> str:
    """Lowercase letters and digits only, so Lowe's, LOWES and lowes are
    one word."""
    return _NOT_ALNUM.sub("", str(value or "").lower())


def _provider_words() -> set:
    """The provider's own name, as the bound AppSpec gives it.

    Never evidence that a PDF is one purchase's receipt. Every page of the
    provider's site carries it, the order list, the sign-in page and the
    front page included. On 2026-09-29 a Walmart order list, printed after
    a sign-in in the middle of a run, passed the check on the word Walmart
    alone and was filed as an online order's invoice, marked downloaded so
    the real one would never be asked for."""
    if not _SPEC:
        return set()
    return {w for w in (_plain(_SPEC.token), _plain(_SPEC.provider)) if w}


def _base_href() -> str:
    if _SPEC and _SPEC.base_url:
        return _SPEC.base_url
    return ""



PDF_MAGIC = b"%PDF-"

# window.print() suppression: installed as an init script on the automation
# profile so a receipt page calling window.print() never opens the native
# dialog. The page's printable content still renders normally; we then use
# Page.printToPDF. (Only affects the dedicated automation profile.)
PRINT_SUPPRESS_INIT_SCRIPT = """
(() => {
  try {
    const orig = window.print ? window.print.bind(window) : null;
    window.__paperpullOriginalPrint = orig;
    window.__paperpullPrintCalled = false;
    window.print = function () {
      window.__paperpullPrintCalled = true;
      // Snapshot the printing document RIGHT NOW: sites often build the
      // print view in a temporary iframe and remove it immediately after
      // print() returns. Stash the HTML on the top window so the automation
      // can retrieve exactly what the print dialog would have rendered.
      try {
        const html = document.documentElement.outerHTML;
        window.__paperpullPrintHTML = html;
        try {
          window.top.__paperpullPrintHTML = html;
          window.top.__paperpullPrintCalled = true;
        } catch (e) {}
      } catch (e) {}
    };
  } catch (e) {}
})();
"""

PRINT_RESTORE_SCRIPT = """
(() => {
  try {
    if (window.__paperpullOriginalPrint) {
      window.print = window.__paperpullOriginalPrint;
    }
  } catch (e) {}
})();
"""

PRINT_TO_PDF_OPTIONS = {
    "printBackground": True,
    "preferCSSPageSize": True,
    "displayHeaderFooter": False,
    "paperWidth": 8.5,
    "paperHeight": 11,
    "marginTop": 0.4,
    "marginBottom": 0.4,
    "marginLeft": 0.4,
    "marginRight": 0.4,
}


# Hide everything except the receipt container (and its ancestor chain) so
# the printed PDF contains only the receipt, no page navigation or buttons.
ISOLATE_SCRIPT = """
(sel) => {
  const el = document.querySelector(sel);
  if (!el) return false;
  let node = el;
  while (node && node.parentElement) {
    const parent = node.parentElement;
    for (const sib of parent.children) {
      if (sib !== node && !['SCRIPT','STYLE','LINK'].includes(sib.tagName)) {
        sib.style.setProperty('display', 'none', 'important');
      }
    }
    node.style.setProperty('position', 'static', 'important');
    node.style.setProperty('overflow', 'visible', 'important');
    node.style.setProperty('max-height', 'none', 'important');
    node.style.setProperty('height', 'auto', 'important');
    node.style.setProperty('margin', '0', 'important');
    node = parent;
  }
  document.body.style.setProperty('height', 'auto', 'important');
  document.documentElement.style.setProperty('height', 'auto', 'important');
  return true;
}
"""


def isolate_for_print(page, selector: str) -> bool:
    """Restrict the page to just the receipt element before printing.
    Returns True if the selector was found and isolation applied."""
    try:
        return bool(page.evaluate(ISOLATE_SCRIPT, selector))
    except Exception:
        return False


# Tag the smallest element containing every given text needle. Used to find
# the receipts column on pages without stable ids/landmarks (the provider's
# receipts page has no #content or <main>; everything sits in div#__next).
ISOLATE_BY_TEXT_SCRIPT = """
(needles) => {
  needles = needles.map(n => n.toLowerCase());
  let best = null, bestLen = Infinity;
  for (const el of document.querySelectorAll('div,section,article,main')) {
    const t = (el.innerText || '').toLowerCase();
    if (!t) continue;
    if (needles.every(n => t.includes(n)) && t.length < bestLen) {
      best = el;
      bestLen = t.length;
    }
  }
  if (!best) return false;
  best.setAttribute('data-paperpull-isolate', '1');
  return true;
}
"""

# On the Online "Receipts and invoices" page, gift-receipt blocks render
# inline next to the official Store Receipt. Hide every topmost container
# that mentions gift receipts but no store receipt, so saved PDFs contain
# only official receipts (spec: never save gift receipts).
HIDE_GIFT_RECEIPTS_SCRIPT = """
() => {
  const giftRe = /gift\\s+receipt/i;
  const storeRe = /store\\s+receipt/i;
  let hidden = 0;
  const root = document.querySelector('[data-paperpull-isolate]')
               || document.querySelector('#content')
               || document.querySelector('main') || document.body;
  for (const el of root.querySelectorAll('*')) {
    const t = el.innerText || '';
    if (!giftRe.test(t) || storeRe.test(t)) continue;
    const parent = el.parentElement;
    if (parent && storeRe.test(parent.innerText || '')) {
      el.style.setProperty('display', 'none', 'important');
      hidden++;
    }
  }
  return hidden;
}
"""


def isolate_online_receipts(page) -> None:
    """Isolate the receipts column of the Online receipts page and hide
    gift-receipt blocks before printing."""
    found = False
    try:
        found = bool(page.evaluate(ISOLATE_BY_TEXT_SCRIPT,
                                   ["store receipt", "receipts and invoices"]))
    except Exception:
        pass
    if found:
        isolate_for_print(page, "[data-paperpull-isolate='1']")
    else:
        for sel in ("#content", "main"):
            if isolate_for_print(page, sel):
                break
    try:
        page.evaluate(HIDE_GIFT_RECEIPTS_SCRIPT)
    except Exception:
        pass


def install_print_suppression(page) -> None:
    """Belt-and-suspenders: run the print-suppression override immediately in
    every current frame (main + iframes). add_init_script only covers frames
    created AFTER it is set; a receipt view already present, or one rendered
    without a fresh document, can still hold the native window.print. Call
    this right after navigating and again right before clicking a print
    control."""
    for frame in page.frames:
        try:
            frame.evaluate(PRINT_SUPPRESS_INIT_SCRIPT)
        except Exception:
            pass


def was_print_called(page) -> bool:
    try:
        return bool(page.evaluate("() => window.__paperpullPrintCalled === true"))
    except Exception:
        return False


def restore_print(page) -> None:
    """Restore the page's original window.print after PDF creation."""
    try:
        page.evaluate(PRINT_RESTORE_SCRIPT)
    except Exception:
        pass


# What the page is laid out for now. Playwright cannot be asked what it was
# told to emulate, so the page is asked what it matches.
_MEDIA_NOW = "() => matchMedia('print').matches ? 'print' : 'screen'"


def print_page_to_pdf(page, out_path: Path) -> None:
    """Render the current page to a PDF file via CDP Page.printToPDF.

    Applies print media emulation first so print-specific CSS is used, then
    puts back the media the page was in, print only when a caller had set
    it. This used to end with emulate_media(media=None), which in Playwright
    for Python leaves the emulation as it is ("null" takes it off). The page
    stayed in print through every navigation after it, so everything an app
    read after its first print was read in the printed layout, and the tab
    somebody was watching showed that layout until the run ended.
    Raises on failure so the caller can fall back.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        before = page.evaluate(_MEDIA_NOW)
    except Exception:
        before = None
    try:
        page.emulate_media(media="print")
    except Exception:
        pass
    try:
        session = page.context.new_cdp_session(page)
        try:
            data = printed_pdf(session, PRINT_TO_PDF_OPTIONS)
        finally:
            try:
                session.detach()
            except Exception:
                pass
        if not data.startswith(PDF_MAGIC):
            raise RuntimeError("printToPDF returned non-PDF data")
        out_path.write_bytes(data)
    finally:
        try:
            page.emulate_media(media="print" if before == "print" else "null")
        except Exception:
            pass


def printed_pdf(session, options) -> bytes:
    """The PDF Page.printToPDF makes of a page, over the CDP `session`, read
    from the browser a piece at a time and refused past the limit
    (intake.DOCUMENT_BYTES), the way Playwright's own page.pdf() reads it.
    A page can lay itself out as long as it likes, and asked for whole the
    PDF came back as one message of any size. Raises TooLarge."""
    result = session.send("Page.printToPDF", dict(options, transferMode="ReturnAsStream"))
    handle = result.get("stream")
    if not handle:
        # A browser that answers with the data itself.
        return _intake.decode(result.get("data") or "")
    parts, got = [], 0
    try:
        while True:
            piece = session.send("IO.read", {"handle": handle, "size": 1 << 20})
            data = piece.get("data") or ""
            chunk = base64.b64decode(data) if piece.get("base64Encoded") else data.encode("latin-1")
            got += len(chunk)
            if got > _intake.DOCUMENT_BYTES:
                raise _intake.refuse("The printed page", size=got)
            parts.append(chunk)
            if piece.get("eof"):
                break
    finally:
        try:
            session.send("IO.close", {"handle": handle})
        except Exception:
            pass
    return b"".join(parts)


def print_html_to_pdf(page, html: str, out_path: Path) -> None:
    """Render an HTML snapshot (the exact document a print dialog would have
    printed) to PDF in a temporary tab of the same browser context."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    base = _base_href()
    if base and "<base" not in html.lower():
        html = re.sub(r"(<head[^>]*>)",
                      lambda m: m.group(1) + f'<base href="{base}">',
                      html, count=1, flags=re.I)
    tmp = page.context.new_page()
    try:
        tmp.set_content(html, wait_until="load")
        tmp.wait_for_timeout(1500)
        print_page_to_pdf(tmp, out_path)
    finally:
        try:
            tmp.close()
        except Exception:
            pass


_ACTIVE_NAMES = r"script|iframe|frame|frameset|object|embed|applet|form|base|link|meta"
# One active tag, opening or closing. A tag with no ">" runs to the end of the
# page and goes with it, so no start is ever scanned to the end twice.
_ACTIVE_TAG_RE = re.compile(r"<\s*+(/?)\s*+(%s)\b[^>]*+>?" % _ACTIVE_NAMES, re.I)
# These are taken out with everything up to their closing tag.
_ACTIVE_ELEMENTS = {"script", "iframe", "frameset", "object", "applet", "form"}
# Looser than the strip: no closing ">" is needed, so an unclosed "<script"
# left at the end of the page is still seen.
_ACTIVE_LEFT_RE = re.compile(r"<\s*+/?\s*+(%s)\b" % _ACTIVE_NAMES, re.I)
# HTML's own whitespace, narrower than Python's \s. To a browser a no-break
# space is part of a name or a value, never a gap between them.
_W = "\t\n\f\r "
# One attribute as a browser's tokenizer reads it, a name, which may start
# with "=" and may hold quotes, then an optional "=" and value. A quote opens
# a value only right after "=", and one with no partner runs to the end of
# the page. A bare value runs to whitespace or ">".
_NAME = r"[^%s/>][^%s/>=]*+" % (_W, _W)
_VALUE = r"(?:\"[^\"]*+\"?|'[^']*+'?|[^%s>]*+)" % _W
_EQUALS = r"[%s]*+=[%s]*+" % (_W, _W)
# A whole tag, or a comment. A comment runs to its own "-->" (or "--!>", or
# ends at once as "<!-->"), and a quote inside it opens nothing, so a later
# tag is never read as part of it. "<!", "<?" and "</" with no name end at
# the first ">", as a browser reads them. Possessive, and a tag with no ">"
# runs to the end of the page, so the scan stays linear on a page of broken
# tags.
_TAG_RE = re.compile(
    r"<!--(?:-?>|(?:[^-]++|-(?!-!?>))*+(?:--!?>)?)"
    r"|(</?[a-zA-Z][^%s/>]*+)((?:[%s/]++|%s(?:%s%s)?)*+)(>?)"
    r"|<(?:[!?]|/(?![a-zA-Z]))[^>]*+>?" % (_W, _W, _NAME, _EQUALS, _VALUE))
# Inside one tag, after its name, each gap, and each attribute's name and
# value, in the same reading as _TAG_RE.
_IN_TAG_RE = re.compile(r"([%s/]++)|(%s)(?:(%s)(%s))?" % (_W, _NAME, _EQUALS, _VALUE))
# Elements whose body a browser reads as text up to the element's own end
# tag, never as tags or comments, so a "<!--" or a quote there opens
# nothing. Script and iframe go whole in _drop_active. Inside svg or math
# these names hold markup instead, and the page does not say which reading
# the browser takes, so the body is made text in either one
# (_raw_text_body).
_RAW_TEXT_END_RES = {
    name: re.compile(r"</%s(?=[%s/>])" % (name, _W), re.I | re.A)
    for name in ("style", "title", "textarea", "xmp", "noembed", "noframes")}
_TAG_OPENER_RE = re.compile(r"<(?=[a-zA-Z!/?])")
_COMMENT_CLOSE_RE = re.compile(r"--!?>")
_HANDLER_RE = re.compile(r"on[a-z]+", re.I)
# A browser reads "src=x/onerror=y" as one bare value. The part from the
# handler's name on is taken out of it all the same.
_IN_VALUE_RE = re.compile(r"(?<=[/\"'])on[a-z]+[%s]*+=.*" % _W, re.I | re.S)
_URL_ATTRS = {"href", "src", "action", "formaction", "xlink:href"}
_C0_AND_SPACE = "".join(chr(c) for c in range(33))
# The whitespace runs here and in the two tag patterns above are possessive
# (Python 3.11 and later), so a run of spaces with nothing after it is read
# once, not again for every way of splitting it. "<" and 20,000 spaces took
# 45 seconds before, under 0.15 after.
_JS_URL_RE = re.compile(r"(href|src|action|formaction|xlink:href)\s*+=\s*+([\"']?)\s*+javascript:[^\"'>\s]*", re.I)
_MAX_STRIPS = 20


def _drop_active(html: str) -> str:
    """The HTML with each active tag taken out, and with a script, frame,
    object, applet or form element everything up to its closing tag, or to
    the end of the page when it has none. The
    closing tag found for a name is remembered, so a page of unclosed
    "<script>" tags is read once, not once for each."""
    out, pos, closes = [], 0, {}
    while True:
        m = _ACTIVE_TAG_RE.search(html, pos)
        if m is None:
            out.append(html[pos:])
            return "".join(out)
        out.append(html[pos:m.start()])
        pos = m.end()
        name = m.group(2).lower()
        if not m.group(1) and name in _ACTIVE_ELEMENTS:
            found = closes.get(name)
            if found is None or (found is not False and found.start() < pos):
                found = re.compile(r"<\s*/\s*%s\s*>" % name, re.I).search(html, pos) or False
                closes[name] = found
            # One never closed runs to the end of the page, as a browser reads
            # it, so what it held is never shown as the page's own text.
            pos = found.end() if found is not False else len(html)


class UnsafeHtml(ValueError):
    """The HTML still held an active tag after every strip, and is not drawn."""


def _script_url(value: str) -> bool:
    """Whether an attribute value is a javascript: URL as a browser reads
    it, with character references decoded, tabs and newlines anywhere
    dropped, and leading spaces and control characters stripped."""
    if value[:1] in ("'", '"'):
        value = value[1:-1] if len(value) > 1 and value[-1] == value[0] else value[1:]
    for v in (value, _html.unescape(value)):
        v = re.sub(r"[\t\n\r]", "", v).lstrip(_C0_AND_SPACE)
        if v[:11].lower() == "javascript:":
            return True
    return False


def _strip_attribute(m) -> str:
    if m.group(1):
        return m.group(1)
    name, equals, value = m.group(2), m.group(3) or "", m.group(4) or ""
    if _HANDLER_RE.fullmatch(name):
        return ""
    if equals and name.lower() in _URL_ATTRS and _script_url(value):
        q = value[:1] if value[:1] in ("'", '"') else ""
        return f"{name}{equals}{q}#{q}"
    if value[:1] not in ("'", '"'):
        value = _IN_VALUE_RE.sub("", value)
    return name + equals + value


def _strip_tag(m) -> str:
    """One token of _TAG_RE with its handlers taken out and its javascript:
    URLs made "#". A comment, or a "<!" or "<?" token, is left as it is."""
    if m.group(1) is None:
        return m.group(0)
    return m.group(1) + _IN_TAG_RE.sub(_strip_attribute, m.group(2)) + m.group(3)


def _raw_text_body(body: str) -> str:
    """The body of a raw-text element with each "<" that could open a tag
    or a comment written "&lt;", so no reading finds a tag in it. A comment
    that closes inside the body is kept as written, since a style may hold
    its rules in one, and it is text or a comment in either reading. Once no
    comment closes after a point, none is looked for again, so the body is
    read once. A title or textarea shows the same characters as before."""
    out, pos, closes = [], 0, True
    while True:
        m = _TAG_OPENER_RE.search(body, pos)
        if m is None:
            out.append(body[pos:])
            return "".join(out)
        start = m.start()
        out.append(body[pos:start])
        end = None
        if body.startswith("<!--", start):
            rest = start + 4
            if body.startswith(">", rest):
                end = rest + 1
            elif body.startswith("->", rest):
                end = rest + 2
            elif closes:
                close = _COMMENT_CLOSE_RE.search(body, rest)
                closes = close is not None
                end = close.end() if close else None
        if end is None:
            out.append("&lt;")
            pos = start + 1
        else:
            out.append(body[start:end])
            pos = end


def _strip_tags(html: str) -> str:
    """Each token of _TAG_RE through _strip_tag, and the body of a raw-text
    element (_RAW_TEXT_END_RES) kept as text up to its own end tag, or to
    the end of the page when it has none (_raw_text_body). A body is passed
    over once and the scan goes on from its end tag, so the page is read
    once."""
    out, pos = [], 0
    while True:
        m = _TAG_RE.search(html, pos)
        if m is None:
            out.append(html[pos:])
            return "".join(out)
        out.append(html[pos:m.start()])
        out.append(_strip_tag(m))
        pos = m.end()
        name = (m.group(1) or "")[1:]
        end_re = _RAW_TEXT_END_RES.get(name.lower()) if m.group(3) and name.isascii() else None
        if end_re is not None:
            end = end_re.search(html, pos)
            stop = end.start() if end else len(html)
            out.append(_raw_text_body(html[pos:stop]))
            pos = stop


def _strip_once(html: str) -> str:
    out = _drop_active(html)
    out = _strip_tags(out)
    return _JS_URL_RE.sub(r"\1=\2#", out)


def inert_html(html: str, base: str) -> str:
    """The HTML with every way to run code or load a frame taken out, and a
    <base> of the caller's choosing: scripts, frames, objects, forms, link
    and meta tags, the supplied base, inline event handlers and javascript:
    URLs. Styles and images stay, since they are what a printed statement
    needs.

    Each tag is read as a browser's tokenizer reads it. A comment runs to its
    own "-->", a quote opens a value only right after "=", and a URL is
    tested with its character references decoded, so "&#106avascript:" is
    a javascript: URL here as it is in the browser. The body of a style,
    title, textarea, xmp, noembed or noframes element is text up to its own
    end tag, as the browser reads it, and a "<!--" there hides nothing.

    Taking a tag out can join the text on either side of it into a new one,
    so "<li<link>nk ...>" becomes a link tag once the inner one is gone. The
    strip is repeated until a pass changes nothing, and if an active tag is
    still there after that, UnsafeHtml is raised and nothing is drawn. Belt
    and braces: the page it is rendered in has JavaScript off and every
    request aborted."""
    out = html or ""
    for _ in range(_MAX_STRIPS):
        stripped = _strip_once(out)
        if stripped == out:
            break
        out = stripped
    if _ACTIVE_LEFT_RE.search(out) or _strip_once(out) != out:
        raise UnsafeHtml("an active tag was left after stripping")
    tag = f'<base href="{base}">' if base else ""
    # A head tag ends at its own ">", and the search stops at the next "<",
    # so a page of unclosed "<head" is not scanned to its end once for each.
    if re.search(r"<head[^<>]*+>", out, re.I):
        out = re.sub(r"(<head[^<>]*+>)", lambda m: m.group(1) + tag, out, count=1, flags=re.I)
    else:
        out = f"<html><head>{tag}</head><body>{out}</body></html>"
    return out


def print_html_inert_to_pdf(page, html: str, out_path: Path, base: Optional[str] = None) -> None:
    """Render HTML the app fetched itself, not a page the browser already
    showed, to a PDF without letting it run: active content is stripped
    (inert_html) and the page it is drawn in belongs to a fresh browser
    context with JavaScript off and none of the signed-in session's cookies.
    `base` defaults to the bound provider's. Raises on failure, UnsafeHtml
    when the page is refused before drawing. A page whose context is not of
    a browser (a persistent profile's) has nothing to draw in, and raises."""
    out_path = Path(out_path)
    # Stripped before any context is opened, so a page refused (UnsafeHtml)
    # opens nothing at all.
    inert = inert_html(html, base if base is not None else _base_href())
    out_path.parent.mkdir(parents=True, exist_ok=True)
    browser = getattr(page.context, "browser", None)
    if browser is None:
        raise RuntimeError("no browser to render in")
    ctx = browser.new_context(java_script_enabled=False, accept_downloads=False)
    try:
        # Offline: the stripped page may still name outside addresses in
        # styles and images, and none is fetched. Text is what a statement
        # needs, and a missing logo is not a loss.
        ctx.route("**/*", lambda route: route.abort())
        tmp = ctx.new_page()
        tmp.set_content(inert, wait_until="load")
        tmp.wait_for_timeout(1500)
        print_page_to_pdf(tmp, out_path)
    finally:
        try:
            ctx.close()
        except Exception:
            pass


def get_print_snapshot(page) -> Optional[str]:
    """HTML stashed by the print hook at the moment print() was called
    (from the main window or any same-origin iframe), or None."""
    try:
        html = page.evaluate("() => window.__paperpullPrintHTML || null")
        if html and len(html) > 500:
            return html
    except Exception:
        pass
    return None


def clear_print_snapshot(page) -> None:
    try:
        page.evaluate("() => { window.__paperpullPrintHTML = null; "
                      "window.__paperpullPrintCalled = false; }")
    except Exception:
        pass


def print_frame_to_pdf(page, frame, out_path: Path) -> None:
    """Render a print-iframe's formatted HTML to PDF."""
    print_html_to_pdf(page, frame.content(), out_path)


# What the headless renderer lets through, by the kind of request Chromium
# names it. The provider's own hosts, as the app's guard says, answer the
# page, its frames and every redirect on the way to them, and what the page
# draws itself with and reads. An app's asset hosts, its provider's own
# static servers, answer only what a page is drawn with and never a page.
# Anything else is refused, the beacons, reports, prefetches, event streams
# and worker scripts among them, since a printed receipt needs none of them.
_OWN_HOST_LOADS = frozenset(("Document", "Stylesheet", "Script", "Image", "Font",
                             "XHR", "Fetch"))
_ASSET_LOADS = frozenset(("Stylesheet", "Script", "Image", "Font"))

# Ways a page reaches a host that never pause as a request, so the policy
# below cannot refuse them one by one. None is needed to draw a receipt, so
# a page in the renderer has none of them. A worker never runs this script,
# and a prefetch the page's speculation rules ask for, or a report the
# browser sends for it, never pauses either, which is why the browser is
# also left no address for any host but the app's (_resolver_rules).
NO_SOCKETS_INIT_SCRIPT = r"""
(() => {
  for (const name of ["WebSocket", "WebSocketStream", "WebTransport",
                      "RTCPeerConnection", "webkitRTCPeerConnection"]) {
    try {
      Object.defineProperty(window, name, {value: undefined, writable: false,
                                           configurable: false});
    } catch (e) {}
  }
})();
"""


def _host_of(url: str) -> str:
    from urllib.parse import urlsplit
    try:
        return urlsplit(url or "").hostname or ""
    except ValueError:
        return ""


def _allowed(url: str, kind: str, is_safe_url, is_asset_url=None) -> bool:
    """Whether the renderer lets a request of this kind go to `url`."""
    if kind != "Document" and str(url).startswith(("data:", "blob:")):
        # Made inside the page, so no host is asked for it.
        return True
    if kind in _OWN_HOST_LOADS and is_safe_url(url):
        return True
    return bool(is_asset_url is not None and kind in _ASSET_LOADS and is_asset_url(url))


class _RequestPolicy:
    """Every request the renderer's browser pauses, of every page, frame,
    window and worker and every hop of every redirect, held before it is
    sent and let through only when the app's guards accept it.

    Playwright's own routing cannot do this. It hears a request once and
    follows every redirect after that with nothing asked (1.63's
    coreBundle.js continues a request it was handed as a redirect without
    calling the route). Chromium's Fetch domain, turned on for the whole
    browser, pauses each hop as a request of its own. The browser is the
    renderer's own and holds nothing else. What Chromium sends without
    pausing it, a socket, a prefetch, a report, finds no address for any
    other host (_resolver_rules)."""

    def __init__(self, browser, is_safe_url, is_asset_url=None):
        self.is_safe_url = is_safe_url
        self.is_asset_url = is_asset_url
        # (kind, frame id, host) of every request refused, noted before the
        # browser is told, so a navigation that fails has its reason here.
        self.refused = []
        self._cdp = browser.new_browser_cdp_session()
        self._cdp.on("Fetch.requestPaused", self._paused)
        self._cdp.send("Fetch.enable", {"patterns": [
            {"urlPattern": "*", "requestStage": "Request"}]})

    def _paused(self, event: dict) -> None:
        url = (event.get("request") or {}).get("url") or ""
        kind = event.get("resourceType") or ""
        try:
            ok = _allowed(url, kind, self.is_safe_url, self.is_asset_url)
        except Exception:
            # A guard that cannot answer has not said yes.
            ok = False
        if not ok:
            self.refused.append((kind, event.get("frameId"), _host_of(url)))
        try:
            if ok:
                self._cdp.send("Fetch.continueRequest", {"requestId": event["requestId"]})
            else:
                self._cdp.send("Fetch.failRequest", {"requestId": event["requestId"],
                                                     "errorReason": "BlockedByClient"})
        except Exception:
            # The browser is closing, and the request goes with it.
            pass

    def page_refused(self, frame_id):
        """The host of the first page refused in the frame `frame_id`, the
        tab's own, or "" when none was."""
        for kind, frame, host in self.refused:
            if kind == "Document" and frame == frame_id:
                return host or "an address that is not the provider's"
        return ""


def _state_for(storage_state, url: str, is_safe_url) -> dict:
    """The part of the signed-in session the renderer is given, the cookies
    and site storage of hosts the app's guard accepts and nothing of any
    other site the person's browser holds. A cookie names a host and no
    scheme or port, so it is asked about as an address on its host reached
    the way `url` is. The page is let load from no other host, so a cookie
    left out here could never have been sent."""
    from urllib.parse import urlsplit
    state = storage_state if isinstance(storage_state, dict) else {}
    try:
        parts = urlsplit(url or "")
        scheme, port = parts.scheme, parts.port
    except ValueError:
        return {"cookies": [], "origins": []}

    def accepted(address: str) -> bool:
        try:
            return bool(is_safe_url(address))
        except Exception:
            return False

    def host_ok(domain) -> bool:
        host = str(domain or "").strip().lstrip(".")
        if not host or "/" in host or ":" in host or "@" in host:
            return False
        return accepted("%s://%s%s/" % (scheme, host, ":%d" % port if port else ""))

    cookies = [c for c in state.get("cookies") or []
               if isinstance(c, dict) and host_ok(c.get("domain"))]
    origins = [o for o in state.get("origins") or []
               if isinstance(o, dict) and accepted(str(o.get("origin") or "") + "/")]
    return {"cookies": cookies, "origins": origins}


PROXY_REFUSED = (
    "The fallback print does not go through a proxy. Its browser is given an "
    "address for the provider's own hosts and no other, and this computer's "
    "proxy is not one of them, so the page was not opened.")

_HOST_NAME = re.compile(r"(\*\.)?[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*")


def _resolver_rules(hosts) -> str:
    """Chromium's --host-resolver-rules for a browser that finds an address
    for these hosts and no other, "*.target.com" naming every host under
    target.com. Whatever the page sends without a request the policy
    pauses then reaches none of the others, an address written in bare
    numbers included unless it is named here. A proxy set for the whole
    computer is not named either, so behind one the page does not load at
    all and render_url_headless says why. ValueError for a host that is not
    a plain name, since the rules are one line Chromium reads and a comma in
    a name would add a rule of its own."""
    names = [str(h).strip().lower().rstrip(".") for h in (hosts or [])]
    if not names:
        raise ValueError("render_url_headless needs the hosts its page may reach")
    bad = [n for n in names if not _HOST_NAME.fullmatch(n)]
    if bad:
        raise ValueError("not a host name the renderer can be left to reach, %r" % bad)
    return "--host-resolver-rules=MAP * ~NOTFOUND , " + " , ".join(
        "EXCLUDE %s" % n for n in names)


def _print_checked(page, out_path: Path, still_the_providers) -> None:
    """Print the page, asking still_the_providers before and after, and
    remove what was printed when the page left while it printed."""
    still_the_providers()
    page.emulate_media(media="print")
    page.pdf(path=str(out_path), format="Letter", print_background=True,
             prefer_css_page_size=True, display_header_footer=False,
             margin={"top": "0.4in", "bottom": "0.4in",
                     "left": "0.4in", "right": "0.4in"})
    try:
        still_the_providers()
    except ValueError:
        # Left while it printed, so what was printed is in doubt.
        out_path.unlink(missing_ok=True)
        raise


def _tab_frame_id(context, page) -> str:
    """The id Chromium gives the tab's own frame, to tell its pages from
    those of the frames inside it and of any window it opens."""
    session = context.new_cdp_session(page)
    try:
        return session.send("Page.getFrameTree")["frameTree"]["frame"]["id"]
    finally:
        try:
            session.detach()
        except Exception:
            pass


def render_url_headless(playwright, storage_state: dict, url: str,
                        out_path: Path, wait_ms: int = 4000,
                        is_safe_url=None, is_asset_url=None, hosts=None) -> None:
    """Fallback: render *url* to PDF in a temporary local headless Chromium
    that reuses the signed-in cookies. page.pdf() is headless-only, which is
    why this exists.

    `is_safe_url` is the app's own guard and is required. The address has
    to pass it, and so does every page the tab is sent to, every redirect on
    the way and everything the page loads, while `is_asset_url`, when an app
    gives one, lets its provider's own static hosts serve what the page is
    drawn with and never a page. Every other request the browser pauses is
    refused before it is sent (_RequestPolicy). `hosts`, also required,
    names every host either guard accepts ("*.target.com" for all under
    it), and the browser finds an address for no other, which holds what
    it sends without pausing (_resolver_rules). It is reached from a
    page-supplied address and only ever runs after the ordinary path has
    already failed, which is exactly when that address is least
    trustworthy. Until 2026-10 only the first address was checked, and a
    redirect from it was followed anywhere with every cookie of the
    person's browser and printed.

    Nothing is printed when the tab was sent off the provider's hosts at any
    point, or is not on them at the moment of printing, and a PDF already
    written then is removed. Raises ValueError for those, SandboxRefused
    when the browser's sandbox cannot start, NoOwnChromium when Playwright's
    own Chromium is not on this computer, RuntimeError(PROXY_REFUSED)
    behind a proxy, and Playwright's own error when the page could not be
    opened at all.
    """
    if is_safe_url is None:
        raise ValueError("render_url_headless needs the app's is_safe_url")
    rules = _resolver_rules(hosts)
    if not is_safe_url(url):
        raise ValueError("refusing to render an address that is not the "
                         "provider's: %r" % (url or "")[:120])
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        browser = _launcher.sandboxed_launch(playwright.chromium, headless=True, args=[rules])
    except Exception as e:
        # Playwright's own Chromium is not on this computer, the usual case
        # where sign-in uses the person's own browser. Its words tell the
        # reader to run a command the packaged app does not have (#131).
        if _launcher.is_missing_chromium(e):
            raise _launcher.NoOwnChromium(_launcher.missing_chromium_words()) from None
        raise
    try:
        policy = _RequestPolicy(browser, is_safe_url, is_asset_url)
        context = browser.new_context(storage_state=_state_for(storage_state, url, is_safe_url),
                                      service_workers="block", accept_downloads=False)
        context.add_init_script(PRINT_SUPPRESS_INIT_SCRIPT)
        context.add_init_script(NO_SOCKETS_INIT_SCRIPT)
        page = context.new_page()
        tab = _tab_frame_id(context, page)

        def still_the_providers() -> None:
            sent_to = policy.page_refused(tab)
            if sent_to:
                raise ValueError("refusing to print, the page was sent on to %s, "
                                 "which is not the provider's" % sent_to)
            if not is_safe_url(page.url):
                raise ValueError("refusing to print a page that is not the "
                                 "provider's: %r" % (page.url or "")[:120])

        try:
            page.goto(url, wait_until="networkidle", timeout=60000)
        except Exception as e:
            # Sent elsewhere is said as such. Any other failure, a refused
            # connection or a page that never came, keeps its own words,
            # since the tab never left the blank page it started on.
            sent_to = policy.page_refused(tab)
            if sent_to:
                raise ValueError("refusing to print, the page was sent on to %s, "
                                 "which is not the provider's" % sent_to) from e
            if "ERR_PROXY_CONNECTION_FAILED" in str(e):
                raise RuntimeError(PROXY_REFUSED) from e
            raise
        page.wait_for_timeout(wait_ms)
        _print_checked(page, out_path, still_the_providers)
    finally:
        browser.close()


ZIP_MAGIC = b"PK\x03\x04"


def is_zip(path: Path) -> bool:
    """Some providers hand a tax form over (a 1099-R, say) as a ZIP holding
    its PDF, or several, rather than a bare PDF."""
    try:
        with open(path, "rb") as f:
            return f.read(4) == ZIP_MAGIC
    except OSError:
        return False


class OpenedZip(NamedTuple):
    """What open_zip made of an archive.

    `pdf` is the document, now at the archive's own path, or None when the
    archive was not opened. `kept` is where the archive went then. `reason`
    says why in words for the record, and `failure` in the fixed words a
    failure file takes."""
    pdf: Optional[Path] = None
    kept: Optional[Path] = None
    reason: str = ""
    failure: str = ""


def _pdf_member(name: str, head: bytes) -> bool:
    """A file in an archive that is a PDF, by its name or by the PDF marker
    in its first kilobyte, the leeway the apps give any PDF answer."""
    return name.lower().endswith(".pdf") or b"%PDF-" in head


def open_zip(zip_path, set_aside=None) -> OpenedZip:
    """A ZIP a provider handed over for one document, opened only when
    which file is the document cannot be in doubt.

    Holding one PDF and nothing else, that PDF takes the archive's place,
    under the document's name, and is checked like any other. Folders,
    and the __MACOSX folder a Mac adds, are not files here.

    Holding anything else, nothing is filed. Of two PDFs either could be
    this document, and a PDF beside other files might not be it either.
    Filing the first PDF put a document under another's name before
    anything had checked it, the other PDFs went beside it unchecked, and
    the other files were lost. So the archive is kept whole in
    `set_aside`, Manual Review, under its own .zip name for a person to
    open. The same files arriving again on a later run are kept once.

    The PDF is written to a temporary file and put in place only once it
    is whole. Any failure leaves the archive kept, never half a PDF under
    a document's name, and never the only copy of the answer gone.

    An archive is kept the same way, unopened, when it is past a limit
    (intake). Larger than a document may be, listing more files than
    ZIP_MEMBERS, a file packed any way but stored or deflated (bzip2 and
    LZMA unpack a whole block at once, however large), or its PDF larger
    than a document may be or unpacking to more than ZIP_RATIO times its
    packed size. The PDF is counted as it is copied too, whatever the
    archive says of it.
    """
    import os
    import tempfile
    import zipfile

    zip_path = Path(zip_path)
    tmp = None
    pdfs = others = 0
    # Why the archive is past a limit, in words, or "". Kept only once the
    # archive is closed, for the same reason as above.
    refused = _archive_too_big(zip_path)
    try:
        # Written out and the archive CLOSED before anything is moved,
        # because on Windows an open file cannot be replaced (WinError 32).
        with (zipfile.ZipFile(zip_path) if not refused else _Nothing()) as z:
            listed = z.infolist()
            files = [i for i in listed
                     if not i.is_dir() and not i.filename.startswith("__MACOSX/")]
            if len(listed) > _intake.ZIP_MEMBERS:
                refused = ("The downloaded archive listed %d files, more than PaperPull "
                           "opens" % len(listed), "ZIP_MEMBERS", "lets an archive list more files")
            elif any(i.compress_type not in _ZIP_METHODS for i in files):
                refused = ("The downloaded archive was packed in a way PaperPull does not "
                           "open, only stored or deflated", "", "")
            found = []
            for info in files if not refused else ():
                with z.open(info) as src:
                    if _pdf_member(info.filename, src.read(1024)):
                        found.append(info)
            pdfs, others = len(found), len(files) - len(found)
            if pdfs == 1 and not others:
                refused = _unpacks_too_far(found[0])
            if pdfs == 1 and not others and not refused:
                fd, name = tempfile.mkstemp(prefix=".opening-", suffix=".tmp",
                                            dir=str(zip_path.parent))
                tmp = Path(name)
                with os.fdopen(fd, "wb") as dst, z.open(found[0]) as src:
                    whole = _copy_counted(src, dst, min(found[0].file_size,
                                                        _intake.DOCUMENT_BYTES))
                if not whole:
                    _discard(tmp)
                    tmp = None
                    refused = ("The PDF in the downloaded archive unpacked to more than "
                               "it said", "", "")
    except Exception as e:
        log.warning("could not open the archive %s: %s", zip_path.name, e)
        _discard(tmp)
        return _kept(zip_path, set_aside, "The downloaded archive could not be opened",
                     "the archive could not be opened")
    if refused:
        return _over_limit(zip_path, set_aside, *refused)
    if tmp is None:
        if not pdfs:
            what, failure = "The downloaded archive held no PDF", "the archive held no pdf"
        elif pdfs > 1:
            what = ("The downloaded archive held %d PDFs, and which one is this "
                    "document cannot be told" % pdfs)
            failure = "the archive held more than one pdf"
        else:
            what = "The downloaded archive held a PDF and %d other %s" % (
                others, "file" if others == 1 else "files")
            failure = "the archive held more than one file"
        return _kept(zip_path, set_aside, what, failure)
    try:
        os.replace(tmp, zip_path)
    except OSError as e:
        log.warning("could not put the PDF from %s in place: %s", zip_path.name, e)
        _discard(tmp)
        return _kept(zip_path, set_aside,
                     "The PDF in the downloaded archive could not be put in place",
                     "the archive could not be opened")
    return OpenedZip(pdf=zip_path)


# The ways of packing a file that are read a piece at a time with a bound
# on what each piece unpacks to.
_ZIP_METHODS = (0, 8)  # zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED


class _Nothing:
    """An archive that is not opened, listing nothing."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    @staticmethod
    def infolist():
        return []


def _archive_too_big(path: Path) -> str:
    """Why an archive is not even listed, as (words, limit, what raising it
    does), or "". Larger than a
    document may be, or its own last record saying it lists more files
    than ZIP_MEMBERS. zipfile builds an entry for every file listed before
    anything can count them, and a 100 MB listing of two million names took
    gigabytes to build, so the count is read from that record first."""
    size = _intake.size_of(path)
    if size > _intake.DOCUMENT_BYTES:
        return ("The downloaded archive was larger than a document may be (%s)"
                % _intake._mb(size), "DOCUMENT_BYTES", "lets a larger one in")
    import zipfile
    try:
        with open(path, "rb") as f:
            # The record at the end of every ZIP, the ZIP64 one included,
            # read by zipfile's own reader of it.
            end = zipfile._EndRecData(f)
        listed = int(end[zipfile._ECD_ENTRIES_TOTAL]) if end else 0
        listing = int(end[zipfile._ECD_SIZE]) if end else 0
    except Exception:
        # Not readable here means zipfile will say why itself.
        return ""
    # zipfile reads entries until the listing's size is used up, whatever
    # the count says, so the size is held as well, at room for every file
    # allowed with a long name.
    if listed > _intake.ZIP_MEMBERS:
        return ("The downloaded archive listed %d files, more than PaperPull opens" % listed,
                "ZIP_MEMBERS", "lets an archive list more files")
    if listing > _intake.ZIP_MEMBERS * _LISTING_PER_FILE:
        return ("The downloaded archive's list of files was longer than PaperPull opens",
                "ZIP_MEMBERS", "lets an archive list more files")
    return ""


# Room in an archive's listing for one file, its fixed 46 bytes and a long
# name and extra fields.
_LISTING_PER_FILE = 2048


def _unpacks_too_far(info):
    """Why the one PDF in an archive is not unpacked, as (words, limit, what
    raising it does), or ""."""
    if info.file_size > _intake.DOCUMENT_BYTES:
        return ("The PDF in the downloaded archive was larger than a document may be "
                "(%s)" % _intake._mb(info.file_size), "DOCUMENT_BYTES", "lets a larger one in")
    if info.file_size > _intake.ZIP_RATIO_FROM and \
            info.file_size > _intake.ZIP_RATIO * max(1, info.compress_size):
        return ("The PDF in the downloaded archive unpacks to more than %d times its "
                "packed size" % _intake.ZIP_RATIO, "ZIP_RATIO", "lets a file unpack further")
    return ""


def _copy_counted(src, dst, limit: int) -> bool:
    """Copy `src` to `dst` a piece at a time, and False once more than
    `limit` bytes have come, with no more read."""
    got = 0
    while True:
        piece = src.read(min(1 << 20, limit - got + 1))
        if not piece:
            return True
        got += len(piece)
        if got > limit:
            return False
        dst.write(piece)


def _over_limit(path: Path, folder, what: str, limit: str = "", gives: str = "") -> OpenedZip:
    """An archive past a limit, said once and kept whole like any archive
    that is not opened, with which limit it met and where it is raised."""
    hint = _intake.raising(limit, gives) if limit else ""
    log.warning("%s, so it was not opened. %s", what, hint)
    print(("  %s, so it was not opened. %s" % (what, hint)).rstrip())
    kept = _kept(path, folder, what, "the archive was over a limit")
    # An app prints the reason and a full stop after it.
    return kept._replace(reason=kept.reason + ". " + hint.rstrip(".")) if hint else kept


def _discard(path) -> None:
    if path is not None:
        try:
            Path(path).unlink()
        except OSError:
            pass


def _kept(path: Path, folder, what: str, failure: str) -> OpenedZip:
    kept = _set_aside(path, folder)
    if kept is not None and kept != path:
        what = "%s, so it was kept in %s as %s" % (what, kept.parent.name, kept.name)
    return OpenedZip(kept=kept, reason=what, failure=failure)


def _set_aside(path: Path, folder=None) -> Optional[Path]:
    """An archive that was not opened, kept whole. Moved into `folder`
    under its own .zip name, or without one left where it landed, renamed
    to .zip when it wears a PDF's name, since a file that is not a PDF
    must not. An archive already kept under that name that holds the same
    files is the same answer again, and this one goes, so a document tried
    on every run does not pile up copies. None only when it is gone."""
    import shutil

    path = Path(path)
    if not path.exists():
        return None
    if folder is None and path.suffix.lower() != ".pdf":
        return path
    where = Path(folder) if folder is not None else path.parent
    try:
        where.mkdir(parents=True, exist_ok=True)
        target = where / (path.stem + ".zip")
        n = 1
        while target.exists():
            if _same_archive(target, path):
                path.unlink()
                return target
            n += 1
            target = where / ("%s (%d).zip" % (path.stem, n))
        shutil.move(str(path), str(target))
        return target
    except OSError as e:
        log.warning("could not keep the archive %s: %s", path.name, e)
        return path if path.exists() else None


def _same_archive(a: Path, b: Path) -> bool:
    """Whether two archives hold the same files. A ZIP built on request
    stamps each file with the moment it was built, so two answers holding
    the same documents differ in their bytes."""
    import filecmp
    import zipfile

    def listing(z):
        return sorted((i.filename, i.file_size, i.CRC) for i in z.infolist() if not i.is_dir())

    try:
        if _archive_too_big(a) or _archive_too_big(b):
            # Not listed at all, for the reason open_zip did not list it.
            return filecmp.cmp(str(a), str(b), shallow=False)
        with zipfile.ZipFile(a) as za, zipfile.ZipFile(b) as zb:
            return listing(za) == listing(zb)
    except Exception:
        try:
            return filecmp.cmp(str(a), str(b), shallow=False)
        except OSError:
            return False


def save_download(download, out_path: Path) -> None:
    """Save a Playwright download event directly to its final path.

    One larger than a document may be is never put there, and raises
    TooLarge (intake.save_download_as)."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    _intake.save_download_as(download, out_path)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def pdf_text(path: Path) -> str:
    """Every page's text, newline-joined. Empty on any failure, never raises,
    because a caller reparsing hundreds of receipts wants to skip one bad
    file rather than stop. Read within the limits of a PDF's time and
    memory (pdf_reader), and empty when one is passed."""
    try:
        return whole_characters("\n".join(_pdf_reader.page_texts(path)))
    except Exception:
        return ""


class OnItsOwn(tuple):
    """The ways one date or amount might print, any one of which names a
    purchase, found only as a number of its own (see identity.on_its_own).

    A plain token is found inside a longer number, so a purchase's
    "1/19/27" is found on a receipt printed "11/19/27". Uber hands its
    total and its printed dates this way (uber_site.receipt_tokens)."""


class Together(tuple):
    """Facts that name a purchase only together.

    Each member is the list of ways one fact might print, and every member
    has to be found somewhere in the text, each as a number of its own (see
    identity.on_its_own). See expected_tokens_for for the one pair asked for
    this way, a date and a total."""


def validate_pdf(path: Path, min_bytes: int = 3000,
                 expect_tokens: Optional[Iterable[str]] = None) -> ValidationResult:
    """Verify a saved PDF, that it exists, is not trivially small, carries
    the PDF signature, opens with pypdf and has a page. Optionally check
    extracted text for expected tokens, the facts that name one purchase
    (see expected_tokens_for).

    Any one token is enough, and a token that is only the provider's name
    never counts, from the caller or from an app's own list. See
    _provider_words for why. An image-based PDF with little text is NOT
    rejected for missing tokens, and neither is a scan whose few words
    include the provider's name, which the name alone used to pass.

    The PDF is read within the limits of a PDF's size, time and memory
    (pdf_reader), and one past a limit does not validate, with
    `over_limit` saying why. Like any PDF that does not validate, it is
    the caller's to keep where it keeps those, and it is never deleted
    here."""
    path = Path(path)
    if not path.exists():
        return ValidationResult(False, "File does not exist")
    size = path.stat().st_size
    if size == 0:
        return ValidationResult(False, "File is zero bytes", size_bytes=0)
    if size < min_bytes:
        return ValidationResult(False, f"File smaller than minimum ({size} < {min_bytes} bytes)",
                                size_bytes=size)
    try:
        with path.open("rb") as f:
            head = f.read(1024)
    except OSError as e:
        return ValidationResult(False, f"Cannot read file: {e}", size_bytes=size)
    if PDF_MAGIC not in head[:64]:
        return ValidationResult(False, "Missing %PDF signature", size_bytes=size)

    tokens = [t for t in (expect_tokens or ()) if t]
    read = _pdf_reader.read(path, text_pages=5 if tokens else 0)
    if read.over_limit:
        return ValidationResult(False, read.over_limit, size_bytes=size,
                                over_limit=read.over_limit)
    if not read.opened:
        return ValidationResult(False, f"pypdf could not open file: {read.error}",
                                size_bytes=size)
    pages = read.pages
    if pages < 1:
        return ValidationResult(False, "PDF has no pages", size_bytes=size, page_count=0)

    token_found = False
    if tokens and not read.text_error:
        # A page whose text could not be read leaves the text unchecked,
        # as it always did, since that never fails an otherwise good PDF.
        try:
            text = whole_characters("".join(read.texts))
            text_lower = text.lower()
            # POS receipts render with per-letter spacing ("T a r g e t"),
            # so also match against whitespace-squashed text.
            squashed = re.sub(r"\s+", "", text_lower)

            def _has(tok) -> bool:
                t = str(tok).lower()
                return t in text_lower or re.sub(r"\s+", "", t) in squashed

            def _found(tok) -> bool:
                if isinstance(tok, OnItsOwn):
                    return any(on_its_own(v, text_lower) for v in tok if v)
                if isinstance(tok, Together):
                    return all(any(on_its_own(v, text_lower) for v in fact if v)
                               for fact in tok)
                return _has(tok)

            provider = _provider_words()
            own = [t for t in tokens
                   if isinstance(t, (OnItsOwn, Together)) or _plain(t) not in provider]
            if own:
                token_found = any(_found(t) for t in own)
                missing = "this purchase's order number, date or items"
            else:
                # Nothing but the provider's name was asked for, so it is
                # all there is to look for, as it always was.
                token_found = any(_has(t) for t in tokens)
                missing = _provider_name()
            if text_lower.strip() and not token_found:
                # A scan with a few words of text on it, one of them the
                # provider's name, was accepted on that name. It still
                # is. Anything longer is a page, and a page that names
                # nothing of this purchase is somebody else's.
                scan = (bool(own) and len(squashed) < MIN_TEXT
                        and any(w in _plain(text) for w in provider))
                if not scan:
                    return ValidationResult(
                        False, f"Extractable text does not mention {missing}",
                        size_bytes=size, page_count=pages, text_token_found=False)
            # Little/no extractable text: likely image-based PDF -> accept.
        except Exception:
            pass  # text extraction problems never fail an otherwise-valid PDF

    return ValidationResult(True, "OK", size_bytes=size, page_count=pages,
                            text_token_found=token_found)


def expected_tokens_for(purchase, listed=None) -> list:
    """What a saved PDF has to mention to be this purchase's receipt.

    Its order number, its date written the ISO way, or the start of one of
    its items' names, and any one of them is enough. The provider's own
    name is not among them, see _provider_words.

    `listed` is the purchase as the order list showed it, the app's
    discovery record, from before any page of the purchase was read. Given
    it, the date the list showed, printed the ways a receipt prints a date,
    together with the total the list showed, is enough as well. It is for
    the apps whose receipts can carry no number and no item this check
    would find, a Meijer till receipt or a Costco gas receipt, which does
    not always say Costco either. The list's date and not the purchase's
    own, because a page read by mistake writes its date into the purchase,
    and a check built from it would pass the page it was read from. Where
    the list kept no record of the purchase, the purchase's own date and
    total stand in (see _a_listing)."""
    tokens = []
    if purchase.order_number:
        tokens.append(purchase.order_number)
        # order numbers sometimes render with dashes/spaces stripped
        tokens.append(re.sub(r"[^0-9A-Za-z]", "", purchase.order_number))
    if purchase.purchase_date:
        tokens.append(purchase.purchase_date)
    for item in purchase.items[:5]:
        name = (item.name or "").strip()
        if len(name) >= 6:
            tokens.append(name[:24])
    if listed is not None:
        if not _a_listing(listed):
            listed = purchase
        dates = date_variants(_as_listed(listed, "purchase_date")[:10])
        totals = amount_variants(_as_listed(listed, "total"))
        if dates and totals:
            tokens.append(Together((dates, totals)))
    return tokens


def _a_listing(record) -> bool:
    """Whether a record says what the list showed.

    A discovery record is the purchase as it was discovered, every field
    there even when empty. An app also writes a bare state into the same
    store as it goes, before this check among other places, and for a
    purchase the list never held that is all the record there is. It says
    nothing the list showed, so the purchase's own date and total stand in,
    as they do for no record at all. Taken for a listing, it left a Meijer
    till receipt with nothing to be named by, and it was put aside."""
    if isinstance(record, dict):
        return "purchase_date" in record or "total" in record
    return True


def _as_listed(record, name: str) -> str:
    """One field of a discovery record, or of a Purchase standing in for
    one."""
    if isinstance(record, dict):
        return str(record.get(name) or "")
    return str(getattr(record, name, "") or "")
