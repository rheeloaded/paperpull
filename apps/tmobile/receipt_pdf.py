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
from typing import Iterable, Optional

from models import ValidationResult

log = logging.getLogger("tmobile_docs.pdf")

PDF_MAGIC = b"%PDF-"

# window.print() suppression: installed as an init script on the automation
# profile so a receipt page calling window.print() never opens the native
# dialog. The page's printable content still renders normally; we then use
# Page.printToPDF. (Only affects the dedicated automation profile.)
PRINT_SUPPRESS_INIT_SCRIPT = """
(() => {
  try {
    const orig = window.print ? window.print.bind(window) : null;
    window.__rhDocsOriginalPrint = orig;
    window.__rhDocsPrintCalled = false;
    window.print = function () {
      window.__rhDocsPrintCalled = true;
      // Snapshot the printing document RIGHT NOW: sites often build the
      // print view in a temporary iframe and remove it immediately after
      // print() returns. Stash the HTML on the top window so the automation
      // can retrieve exactly what the print dialog would have rendered.
      try {
        const html = document.documentElement.outerHTML;
        window.__rhDocsPrintHTML = html;
        try {
          window.top.__rhDocsPrintHTML = html;
          window.top.__rhDocsPrintCalled = true;
        } catch (e) {}
      } catch (e) {}
    };
  } catch (e) {}
})();
"""

PRINT_RESTORE_SCRIPT = """
(() => {
  try {
    if (window.__rhDocsOriginalPrint) {
      window.print = window.__rhDocsOriginalPrint;
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
# the printed PDF contains only the receipt — no page navigation or buttons.
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
# the receipts column on pages without stable ids/landmarks (T-Mobile's
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
  best.setAttribute('data-rh-docs-isolate', '1');
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
  const root = document.querySelector('[data-rh-docs-isolate]')
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
        isolate_for_print(page, "[data-rh-docs-isolate='1']")
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
        return bool(page.evaluate("() => window.__rhDocsPrintCalled === true"))
    except Exception:
        return False


def restore_print(page) -> None:
    """Restore the page's original window.print after PDF creation."""
    try:
        page.evaluate(PRINT_RESTORE_SCRIPT)
    except Exception:
        pass


def print_page_to_pdf(page, out_path: Path) -> None:
    """Render the current page to a PDF file via CDP Page.printToPDF.

    Applies print media emulation first so print-specific CSS is used.
    Raises on failure so the caller can fall back.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
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
            page.emulate_media(media=None)
        except Exception:
            pass


def print_html_to_pdf(page, html: str, out_path: Path) -> None:
    """Render an HTML snapshot (the exact document a print dialog would have
    printed) to PDF in a temporary tab of the same browser context."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if "<base" not in html.lower():
        html = re.sub(r"(<head[^>]*>)",
                      lambda m: m.group(1) + '<base href="https://tmobile.com/">',
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
        html = page.evaluate("() => window.__rhDocsPrintHTML || null")
        if html and len(html) > 500:
            return html
    except Exception:
        pass
    return None


def clear_print_snapshot(page) -> None:
    try:
        page.evaluate("() => { window.__rhDocsPrintHTML = null; "
                      "window.__rhDocsPrintCalled = false; }")
    except Exception:
        pass


def print_frame_to_pdf(page, frame, out_path: Path) -> None:
    """Render a print-iframe's formatted HTML to PDF."""
    print_html_to_pdf(page, frame.content(), out_path)


def render_url_headless(playwright, storage_state: dict, url: str,
                        out_path: Path, wait_ms: int = 4000) -> None:
    """Fallback: render *url* to PDF in a temporary local headless Chromium
    that reuses the signed-in cookies. page.pdf() is headless-only, which is
    why this exists."""
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
    """Some T-Mobile tax forms (e.g. 1099-R) download as a ZIP holding the
    PDF(s) rather than a bare PDF."""
    try:
        with open(path, "rb") as f:
            return f.read(4) == ZIP_MAGIC
    except OSError:
        return False


def extract_pdfs_from_zip(zip_path: Path, primary_out: Path) -> list:
    """Extract every PDF from a downloaded ZIP.

    The first PDF is written to *primary_out*; any others get a
    ' (n of N)' suffix. The ZIP itself is removed. Returns the saved paths.
    """
    import shutil
    import zipfile

    zip_path = Path(zip_path)
    primary_out = Path(primary_out)
    saved = []
    try:
        # Read the listing and CLOSE the archive before renaming it: on
        # Windows an open file cannot be moved (WinError 32).
        with zipfile.ZipFile(zip_path) as z:
            names = [n for n in z.namelist() if n.lower().endswith(".pdf")]
        if not names:
            return []
        tmp = zip_path.with_suffix(".zip.tmp")
        zip_path.replace(tmp)
        with zipfile.ZipFile(tmp) as z2:
            for i, name in enumerate(names):
                if i == 0:
                    target = primary_out
                else:
                    target = primary_out.with_name(
                        f"{primary_out.stem} ({i + 1} of {len(names)}).pdf")
                    n = 1
                    while target.exists():
                        n += 1
                        target = primary_out.with_name(
                            f"{primary_out.stem} ({i + 1} of {len(names)}) ({n}).pdf")
                with z2.open(name) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                saved.append(target)
        tmp.unlink(missing_ok=True)
    except Exception as e:
        log.warning("ZIP extraction failed for %s: %s", zip_path, e)
        return []
    return saved


def save_download(download, out_path: Path) -> None:
    """Save a Playwright download event directly to its final path."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    download.save_as(str(out_path))


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_pdf(path: Path, min_bytes: int = 3000,
                 expect_tokens: Optional[Iterable[str]] = None) -> ValidationResult:
    """Verify a saved PDF: exists, non-trivial size, PDF signature, opens
    with pypdf, has >= 1 page. Optionally check extracted text for expected
    tokens (T-Mobile, date, order number, item names). An image-based PDF with
    little text is NOT rejected for missing tokens."""
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
        head = path.open("rb").read(1024)
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
    if expect_tokens:
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

            token_found = any(t and _has(t) for t in expect_tokens)
            if text_lower.strip() and not token_found:
                # Text was extractable but none of the expected tokens appear.
                return ValidationResult(
                    False, "Extractable text does not mention T-Mobile/order details",
                    size_bytes=size, page_count=pages, text_token_found=False)
            # Little/no extractable text: likely image-based PDF -> accept.
        except Exception:
            pass  # text extraction problems never fail an otherwise-valid PDF

    return ValidationResult(True, "OK", size_bytes=size, page_count=pages,
                            text_token_found=token_found)


def expected_tokens_for(purchase) -> list:
    """Tokens whose presence in the PDF text confirms it is the right receipt."""
    tokens = ["tmobile"]
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
    return tokens
