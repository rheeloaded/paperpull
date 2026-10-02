"""Direct PDF generation and validation.

Never uses the Windows Print or Save As dialog. PDFs are produced by:
  1. Capturing a Playwright download event (download.save_as), or
  2. Chromium DevTools Page.printToPDF on the printable page (works in the
     headed supervised browser), or
  3. A short-lived *local* headless Chromium that shares the signed-in
     session state and renders the printable URL with page.pdf().

Validation uses pypdf locally.
"""
from __future__ import annotations

import base64
import logging
import re
from pathlib import Path
from typing import Iterable, NamedTuple, Optional

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
            result = session.send("Page.printToPDF", dict(PRINT_TO_PDF_OPTIONS))
            data = base64.b64decode(result["data"])
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


def render_url_headless(playwright, storage_state: dict, url: str,
                        out_path: Path, wait_ms: int = 4000,
                        is_safe_url=None) -> None:
    """Fallback: render *url* to PDF in a temporary local headless Chromium
    that reuses the signed-in cookies. page.pdf() is headless-only, which is
    why this exists.

    `is_safe_url` is the app's own guard, and the address has to pass it.
    Every other fetch in the project is host checked and this one was not,
    although it is reached from a page-supplied address and only ever runs
    after the ordinary path has already failed, which is exactly when that
    address is least trustworthy.
    """
    if is_safe_url is not None and not is_safe_url(url):
        raise ValueError("refusing to render an address that is not the "
                         "provider's: %r" % (url or "")[:120])
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    browser = playwright.chromium.launch(headless=True)
    try:
        context = browser.new_context(storage_state=storage_state)
        context.add_init_script(PRINT_SUPPRESS_INIT_SCRIPT)
        page = context.new_page()
        page.goto(url, wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(wait_ms)
        page.emulate_media(media="print")
        page.pdf(path=str(out_path), format="Letter", print_background=True,
                 prefer_css_page_size=True, display_header_footer=False,
                 margin={"top": "0.4in", "bottom": "0.4in",
                         "left": "0.4in", "right": "0.4in"})
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
    """
    import os
    import shutil
    import tempfile
    import zipfile

    zip_path = Path(zip_path)
    tmp = None
    pdfs = others = 0
    try:
        # Written out and the archive CLOSED before anything is moved,
        # because on Windows an open file cannot be replaced (WinError 32).
        with zipfile.ZipFile(zip_path) as z:
            files = [i for i in z.infolist()
                     if not i.is_dir() and not i.filename.startswith("__MACOSX/")]
            found = []
            for info in files:
                with z.open(info) as src:
                    if _pdf_member(info.filename, src.read(1024)):
                        found.append(info)
            pdfs, others = len(found), len(files) - len(found)
            if pdfs == 1 and not others:
                fd, name = tempfile.mkstemp(prefix=".opening-", suffix=".tmp",
                                            dir=str(zip_path.parent))
                tmp = Path(name)
                with os.fdopen(fd, "wb") as dst, z.open(found[0]) as src:
                    shutil.copyfileobj(src, dst)
    except Exception as e:
        log.warning("could not open the archive %s: %s", zip_path.name, e)
        _discard(tmp)
        return _kept(zip_path, set_aside, "The downloaded archive could not be opened",
                     "the archive could not be opened")
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
        with zipfile.ZipFile(a) as za, zipfile.ZipFile(b) as zb:
            return listing(za) == listing(zb)
    except Exception:
        try:
            return filecmp.cmp(str(a), str(b), shallow=False)
        except OSError:
            return False


def save_download(download, out_path: Path) -> None:
    """Save a Playwright download event directly to its final path."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    download.save_as(str(out_path))


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def pdf_text(path: Path) -> str:
    """Every page's text, newline-joined. Empty on any failure, never raises,
    because a caller reparsing hundreds of receipts wants to skip one bad
    file rather than stop."""
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        return "\n".join((pg.extract_text() or "") for pg in reader.pages)
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
    include the provider's name, which the name alone used to pass."""
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

    try:
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        pages = len(reader.pages)
    except Exception as e:
        return ValidationResult(False, f"pypdf could not open file: {e}", size_bytes=size)
    if pages < 1:
        return ValidationResult(False, "PDF has no pages", size_bytes=size, page_count=0)

    token_found = False
    tokens = [t for t in (expect_tokens or ()) if t]
    if tokens:
        try:
            text = ""
            for pg in reader.pages[:5]:
                text += pg.extract_text() or ""
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
