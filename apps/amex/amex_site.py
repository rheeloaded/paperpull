"""ALL American Express selectors, URLs, and page behavior live here.

When Amex changes its site, repair THIS file only.

SAFETY (this is a credit-card account):
  This module is strictly READ-ONLY. It navigates to the statements / documents
  / year-end-summary / tax areas, reads a list of documents, and downloads the
  PDFs Amex already generated. It must NEVER activate any control that pays a
  bill, transfers a balance, moves money, redeems rewards/points, applies for a
  card or product, disputes a charge, books travel, cancels a card, or changes
  any setting. FORBIDDEN_CONTROL_RE is the guard; a control must ALSO look like
  a document action (SAFE_DOC_CONTROL_RE) before it may be clicked. There is no
  code here that submits a form or confirms a dialog.

Amex is a heavy React SPA behind Akamai. The signed-in browser session (opened
by login.bat and attached over CDP) carries the auth, so this module only reads
and clicks document/download controls. Statement PDFs may be plain <a> download
links, may sit behind a period selector, or may be produced by a JSON/PDF
endpoint - collect_download_docs + download_named handle the link case and are
refined against the real DOM via diagnose.bat.
"""
# Site layer verified working against the live site: 2026-08
from __future__ import annotations

import base64
import html as _html
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

log = logging.getLogger("amex_docs.site")

BASE = "https://global.americanexpress.com"
URLS = {
    "home": "https://www.americanexpress.com/",
    "login": "https://www.americanexpress.com/en-us/account/login/",
    "dashboard": f"{BASE}/dashboard",
    # Document-area candidates (Amex moves these around). goto_documents tries
    # each; if none render a list, it uses whatever page is open.
    "statements": f"{BASE}/activity/statements",
    "documents": f"{BASE}/activity/document-center",
    "year_end": f"{BASE}/spending-report",
    "tax": f"{BASE}/activity/statements",
}
DOCUMENT_URL_CANDIDATES = [URLS["statements"], URLS["documents"],
                           URLS["year_end"]]

LOGIN_URL_MARKERS = ["/login", "/logon", "/signin", "/sign-in", "/auth",
                     "/mfa", "/verification", "/challenge", "myca/logon"]

# ---------------------------------------------------------------------------
# HARD SAFETY GUARD - never click anything matching this. Tuned for a
# credit-card account.
# ---------------------------------------------------------------------------
FORBIDDEN_CONTROL_RE = re.compile(
    r"(pay\b|pay\s+bill|make\s+a?\s*payment|autopay|auto\s*pay|"
    r"balance\s+transfer|transfer|withdraw|deposit|wire\b|move\s+money|"
    r"send\b|redeem|reward|points\b|membership\s+rewards|cash\s*back\b|"
    r"apply|apply\s+now|add\s+card|add\s+account|link\s+(bank|account)|"
    r"dispute|report\s+(fraud|lost|stolen)|book\b|travel\b|reservation|"
    r"cancel|close\s+account|activate|replace\s+card|lock\b|freeze\b|"
    r"enable|disable|change\s+|edit\s+|update\s+|set\s+up|manage\b|"
    r"delete|remove|beneficiar|password|username|"
    r"enroll|subscribe|upgrade|offer\b|refer\b|"
    r"confirm|continue|next\b|agree|accept|authorize|submit)", re.I)

SAFE_DOC_CONTROL_RE = re.compile(
    r"(download|view|open|print|pdf|statement|document|summary|"
    r"year.?end|1099|1098|tax|export)", re.I)

SECURITY_CHALLENGE_MARKERS = [
    "enter the code", "verification code", "6-digit", "one-time code",
    "two-factor", "two-step", "authenticator", "confirm your identity",
    "verify your identity", "we sent a code", "we'll send", "check your email",
    "check your phone", "your session has expired", "log back in",
    "are you a robot", "captcha", "let's confirm it's you", "unusual activity",
]

RATE_LIMIT_MARKERS = [
    "too many requests", "rate limit", "try again later",
    "temporarily unavailable", "http error 429", "unusual traffic",
    "access denied", "reference #",
]

# ---------------------------------------------------------------------------
# Fallback selectors (repair after diagnose)
# ---------------------------------------------------------------------------
FALLBACK = {
    "doc_row": ("table tbody tr, [role='row'], [class*='statement-row'], "
                "[class*='StatementRow'], [class*='document'], "
                "[data-testid*='statement'], [data-testid*='document'], "
                "li[class*='statement'], li[class*='document']"),
    "doc_link": ("a[href*='.pdf'], a[href*='statement'], a[href*='document'], "
                 "a[download], button[class*='download'], "
                 "button[aria-label*='download' i]"),
    "download_control": ("a[download], a[href$='.pdf'], "
                         "button:has-text('Download'), "
                         "[aria-label*='Download' i]"),
    "page_ready": ("table, [role='row'], [class*='statement'], "
                   "[class*='document'], main, [role='main']"),
    "next_page": ("a[aria-label*='Next' i], button[aria-label*='Next' i], "
                  "[class*='next']"),
    "period_select": ("select[name*='statement' i], select[name*='period' i], "
                      "select[aria-label*='statement' i], "
                      "[role='combobox'][aria-label*='statement' i]"),
}

# ---------------------------------------------------------------------------
# Date parsing (shared with the other projects)
# ---------------------------------------------------------------------------
DATE_PATTERNS = [
    (re.compile(r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
                r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|"
                r"Dec(?:ember)?)\.?\s+(\d{1,2}),?\s+(\d{4})", re.I), "mdY"),
    (re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b"), "mdy_slash"),
    (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"), "iso"),
]
_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
MONTH_YEAR_RE = re.compile(
    r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
    r"Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    r"\s+(\d{4})", re.I)
QUARTER_RE = re.compile(r"\bQ([1-4])\s*[' ]?\s*(\d{4})\b", re.I)
YEAR_RE = re.compile(r"\b(19|20)(\d{2})\b")
_LAST_DAY = {1: 31, 2: 28, 3: 31, 4: 30, 5: 31, 6: 30,
             7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31}


def _last_day(year: int, month: int) -> int:
    if month == 2 and (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)):
        return 29
    return _LAST_DAY[month]


def parse_date(text: str) -> Optional[str]:
    if not text:
        return None
    for pattern, kind in DATE_PATTERNS:
        m = pattern.search(text)
        if not m:
            continue
        try:
            if kind == "mdY":
                return f"{int(m.group(3)):04d}-{_MONTHS[m.group(1)[:3].lower()]:02d}-{int(m.group(2)):02d}"
            if kind == "mdy_slash":
                return f"{int(m.group(3)):04d}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
            if kind == "iso":
                return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        except (KeyError, ValueError):
            continue
    return None


def parse_period_date(text: str) -> Tuple[Optional[str], str]:
    text = text or ""
    exact = parse_date(text)
    if exact:
        return exact, ""
    m = MONTH_YEAR_RE.search(text)
    if m:
        month = _MONTHS[m.group(1)[:3].lower()]
        year = int(m.group(2))
        return f"{year:04d}-{month:02d}-{_last_day(year, month):02d}", m.group(0)
    m = QUARTER_RE.search(text)
    if m:
        q, year = int(m.group(1)), int(m.group(2))
        month = q * 3
        return f"{year:04d}-{month:02d}-{_last_day(year, month):02d}", f"Q{q} {year}"
    m = YEAR_RE.search(text)
    if m:
        year = int(m.group(1) + m.group(2))
        return f"{year:04d}-12-31", str(year)
    return None, ""


# ---------------------------------------------------------------------------
# Session / safety
# ---------------------------------------------------------------------------

def looks_signed_out(page) -> bool:
    url = (page.url or "").lower()
    if any(m in url for m in LOGIN_URL_MARKERS):
        return True
    try:
        if page.locator("input[type='password']").count() > 0:
            return True
    except Exception:
        pass
    return False


def detect_security_challenge(page) -> Optional[str]:
    try:
        if page.locator(FALLBACK["doc_row"]).count() > 2:
            return None
    except Exception:
        pass
    try:
        title = (page.title() or "").lower()
    except Exception:
        title = ""
    try:
        body = page.locator("body").inner_text(timeout=5000).lower()
    except Exception:
        body = ""
    hay = title + "\n" + body[:1500]
    for m in SECURITY_CHALLENGE_MARKERS:
        if m in hay:
            return f"Security challenge detected: '{m}'"
    for m in RATE_LIMIT_MARKERS:
        if m in hay:
            return f"Possible rate limiting / bot block detected: '{m}'"
    return None


def is_safe_control(name: str) -> bool:
    name = (name or "").strip()
    if not name:
        return False
    if FORBIDDEN_CONTROL_RE.search(name):
        return False
    # The shared core guard is consulted as well as this app's own blocklist.
    # A repo-wide review found each app had drifted its own way and every one
    # of them let settings controls through ("Save Changes", "Document
    # Removal", "Turn off"). Centralising it means the next gap is fixed once
    # rather than nineteen times.
    try:
        from paperpull_core.controls import SETTINGS_CONTROL_RE, AUTH_CONTROL_RE
        if SETTINGS_CONTROL_RE.search(name) or AUTH_CONTROL_RE.search(name):
            return False
    except Exception:
        pass
    return bool(SAFE_DOC_CONTROL_RE.search(name))


# ---------------------------------------------------------------------------
# Documents page navigation
# ---------------------------------------------------------------------------

def goto_documents(page) -> bool:
    """Reach the PDF Statements page ('Statements and Year End Summaries') by
    CLICKING within the SPA. Amex holds the session in an in-memory token, so a
    hard page.goto drops the session and bounces to login - we never use it for
    authenticated pages. Ready when statement download-buttons are present."""
    if looks_signed_out(page):
        return False
    try:
        url = page.url or ""
        if "/activity/statements" not in url:
            if "/activity" not in url:
                link = page.get_by_role("link", name=re.compile(
                    r"statements?\s*&\s*activity", re.I))
                if link.count() and link.first.is_visible():
                    link.first.click()
                    page.wait_for_timeout(5000)
            pdf = page.locator(
                "[data-testid='goToPdfLinkLg'], [data-testid='goToPdfLinkSm']")
            if pdf.count() == 0:
                pdf = page.get_by_role("link", name=re.compile(
                    r"go to pdf statements", re.I))
            if pdf.count() and pdf.first.is_visible():
                pdf.first.click()
                page.wait_for_timeout(6000)
        try:
            page.wait_for_selector("[data-testid*='download-button']", timeout=12000)
        except Exception:
            pass
        expand_sections(page)
        return page.locator("[data-testid*='download-button']").count() > 0
    except Exception as e:
        log.info("goto_documents (click-nav) failed: %s", e)
        return page.locator("[data-testid*='download-button']").count() > 0


def expand_sections(page) -> None:
    """Open the collapsible 'Older Statements' and 'Year End Summary' sections
    so their download buttons become clickable. 'Older Statements' is expanded
    by default; 'Year End Summary' is collapsed - only click a header whose
    aria-expanded is 'false' (clicking an open one would collapse it)."""
    for label in (r"older\s+statements", r"year.?end\s+summary"):
        try:
            hdr = page.get_by_role("button", name=re.compile(label, re.I))
            for i in range(min(hdr.count(), 3)):
                el = hdr.nth(i)
                if not el.is_visible():
                    continue
                if (el.get_attribute("aria-expanded") or "").lower() == "false":
                    el.click()
                    page.wait_for_timeout(1500)
                break
        except Exception:
            continue


def scroll_full_page(page, rounds: int = 8, delay_ms: int = 700) -> None:
    try:
        for _ in range(rounds):
            page.mouse.wheel(0, 3000)
            page.wait_for_timeout(delay_ms)
        page.keyboard.press("End")
        page.wait_for_timeout(delay_ms)
    except Exception:
        pass


def expand_all(page) -> None:
    """Click 'View More' / 'Show more' / 'Load more' repeatedly until the full
    list loads. Amex uses both <button> and <a>, so both roles are tried."""
    pat = re.compile(
        r"^\s*(show|load|view|see)\s+more\s*$|^\s*view\s+all\s*$|"
        r"^\s*(show|see)\s+(all|older)\s*$|^\s*older\s*$", re.I)
    for _ in range(60):
        clicked = False
        for role in ("button", "link"):
            try:
                loc = page.get_by_role(role, name=pat)
                if loc.count() > 0 and loc.first.is_visible():
                    label = loc.first.inner_text(timeout=1000) or ""
                    if not FORBIDDEN_CONTROL_RE.search(label):
                        loc.first.click()
                        page.wait_for_timeout(1600)
                        clicked = True
                        break
            except Exception:
                continue
        if not clicked:
            break


def next_page(page) -> bool:
    try:
        loc = page.locator(FALLBACK["next_page"])
        if loc.count() > 0 and loc.first.is_visible() and loc.first.is_enabled():
            label = (loc.first.inner_text(timeout=800) or "") + \
                (loc.first.get_attribute("aria-label") or "")
            if FORBIDDEN_CONTROL_RE.search(label):
                return False
            loc.first.click()
            page.wait_for_timeout(2500)
            return True
    except Exception:
        pass
    return False


@dataclass
class RawDoc:
    title: str
    account: str = ""
    date_text: str = ""
    href: str = ""
    text: str = ""
    row_index: int = -1
    kind: str = "doc"


_ROW_JS = r"""() => {
  const out = [];
  for (const tr of document.querySelectorAll('table tr, [role=row]')) {
    const tds = [...tr.querySelectorAll('td, [role=cell]')].map(c => (c.innerText || '').trim());
    if (tds.length < 2) continue;
    const link = tr.querySelector("a[href]");
    out.push({cells: tds.slice(0, 6),
              href: link ? link.getAttribute('href') : ''});
  }
  return out;
}"""


def collect_documents(page) -> List[RawDoc]:
    """Scrape document rows from the visible table/list (diagnose + fallback)."""
    docs: List[RawDoc] = []
    seen = set()
    try:
        rows = page.evaluate(_ROW_JS)
    except Exception:
        rows = []
    for i, r in enumerate(rows):
        cells = [c for c in (r.get("cells") or []) if c]
        if not cells:
            continue
        text = " | ".join(cells)
        has_date = parse_date(text) or MONTH_YEAR_RE.search(text) or YEAR_RE.search(text)
        href = r.get("href", "")
        if not (has_date or href or "download" in text.lower()):
            continue
        title = _html.unescape(cells[0])
        date_text = next((c for c in cells if parse_date(c) or MONTH_YEAR_RE.search(c)), "")
        key = (title, date_text, href, text[:60])
        if key in seen:
            continue
        seen.add(key)
        docs.append(RawDoc(title=re.sub(r"\s+", " ", title)[:200], date_text=date_text,
                           href=href, text=text[:400], row_index=i))
    return docs


# ---------------------------------------------------------------------------
# Downloadable-document collection (verified 2026-07 against the live site).
#
# On the "Statements and Year End Summaries" page every document is a
# <button> whose data-testid encodes its category AND date, e.g.
#   myca-activity-statements/common/Table/recent-statements/2020-01-15/download-button
#   myca-activity-statements/common/Table/older-statements/2019-01-15/download-button
#   myca-activity-statements/common/Table/year-end-summary/2019/download-button
# (dates above are invented. A real testid carries a real closing date,
#  which would publish the account's billing-cycle day.)
# Each date appears twice (a desktop + a hidden mobile copy of the same
# testid), so results are de-duped by (category, date). page.evaluate is
# blocked by Amex (eval lockdown), so this uses locators only.
# ---------------------------------------------------------------------------
_STMT_TESTID_RE = re.compile(r"/(recent|older)-statements/(\d{4}-\d{2}-\d{2})/download-button")
_YE_TESTID_RE = re.compile(r"/year-end-summary/(\d{4})/download-button")
_MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July",
                "August", "September", "October", "November", "December"]


def _human_date(iso: str) -> str:
    try:
        y, m, d = iso.split("-")
        return f"{_MONTH_NAMES[int(m) - 1]} {int(d)}, {y}"
    except Exception:
        return iso


def collect_download_docs(page) -> List[RawDoc]:
    """Every downloadable statement + year-end summary on the statements page,
    read from the download-button testids (deduped by category+date)."""
    docs: List[RawDoc] = []
    seen = set()
    loc = page.locator("[data-testid*='download-button']")
    try:
        n = loc.count()
    except Exception:
        n = 0
    for i in range(n):
        try:
            tid = loc.nth(i).get_attribute("data-testid") or ""
        except Exception:
            continue
        m = _STMT_TESTID_RE.search(tid)
        if m:
            date = m.group(2)
            if ("stmt", date) in seen:
                continue
            seen.add(("stmt", date))
            human = _human_date(date)
            docs.append(RawDoc(title=f"Monthly Statement - {human}", date_text=date,
                               href=tid, text=f"Monthly Statement {human}", kind="statement"))
            continue
        m = _YE_TESTID_RE.search(tid)
        if m:
            year = m.group(1)
            if ("ye", year) in seen:
                continue
            seen.add(("ye", year))
            docs.append(RawDoc(title=f"{year} Year-End Summary", date_text=f"{year}-12-31",
                               href=tid, text=f"{year} Year-End Summary", kind="year-end"))
    return docs


def _first_visible(loc):
    try:
        n = loc.count()
    except Exception:
        return None
    for i in range(n):
        el = loc.nth(i)
        try:
            if el.is_visible():
                return el
        except Exception:
            continue
    return loc.first if (n and loc.count()) else None


def _select_pdf_radio(page) -> bool:
    """In the 'Select File Type' dialog, choose the plain PDF option (never the
    screen-reader / Excel / CSV / Quicken / Quickbooks variants)."""
    for sel in ("input[type='radio'][value='statement_pdf']",
                "input[type='radio'][value*='pdf' i]"):
        loc = page.locator(sel)
        try:
            n = loc.count()
        except Exception:
            n = 0
        for i in range(n):
            el = loc.nth(i)
            v = (el.get_attribute("value") or "").lower()
            if "accessible" in v or "screen" in v:
                continue
            try:
                if el.is_visible():
                    el.check(force=True, timeout=3000)
                    return True
            except Exception:
                continue
    return False


# The "Select File Type" dialog's confirm button renders its label as an icon
# glyph (its accessible name is unreliable), but it carries a stable test id.
_DIALOG_CONFIRM_SEL = (
    "[data-test-id='myca-activity-download-footer-download-confirm-anchor'], "
    "[id*='download-confirm'][id$='-anchor']")
# The dialog is "open" when its PDF radio or its confirm button is present.
_DIALOG_OPEN_SEL = "input[type='radio'][value*='pdf' i], " + _DIALOG_CONFIRM_SEL


def _dialog_download_button(page, timeout: int = 8000):
    """The confirm 'Download' button INSIDE the file-type dialog, matched by its
    stable test id (not by accessible name, which is just an icon glyph)."""
    loc = page.locator(_DIALOG_CONFIRM_SEL)
    try:
        loc.first.wait_for(state="visible", timeout=timeout)
    except Exception:
        pass
    vb = _first_visible(loc)
    if vb is not None:
        return vb
    # last resort: a visible button named Download that is not a row button
    cands = page.get_by_role("button", name=re.compile(r"^\s*download\s*$", re.I))
    for i in range(min(_safe_count(cands), 12)):
        el = cands.nth(i)
        try:
            tid = el.get_attribute("data-testid") or ""
            if el.is_visible() and not tid.endswith("download-button"):
                return el
        except Exception:
            continue
    return None


def _safe_count(loc) -> int:
    try:
        return loc.count()
    except Exception:
        return 0


def _dismiss_dialog(page) -> None:
    """Close any open file-type dialog (Cancel/Close, else Escape) so it does
    not intercept clicks on the next document."""
    try:
        for _ in range(3):
            if _safe_count(page.locator(_DIALOG_OPEN_SEL)) == 0:
                return
            closed = False
            for name in (r"^\s*cancel\s*$", r"^\s*close\s*$"):
                c = page.get_by_role("button", name=re.compile(name, re.I))
                if _safe_count(c) and c.first.is_visible():
                    try:
                        c.first.click(timeout=1500)
                        closed = True
                        break
                    except Exception:
                        pass
            if not closed:
                page.keyboard.press("Escape")
            page.wait_for_timeout(700)
    except Exception:
        pass


def download_document(page, category: str, date: str, out_path) -> bool:
    """Download one statement / year-end-summary PDF: click its row Download
    button, choose 'Billing Statement (PDF)' in the Select File Type dialog,
    click the dialog's confirm Download, and capture the download event.
    Retries once because Amex's dialog occasionally fails to open/settle."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if category == "Year-End Summary":
        sel = f"[data-testid$='/year-end-summary/{date[:4]}/download-button']"
    else:
        sel = f"[data-testid$='/{date}/download-button']"

    from receipt_pdf import save_download
    for attempt in range(2):
        _dismiss_dialog(page)       # clear any stale/prior dialog
        expand_sections(page)       # Older Statements / Year End Summary open

        btn = _first_visible(page.locator(sel))
        if btn is None:
            log.info("row download button not found for %s %s (sel=%s)", category, date, sel)
            return False
        try:
            btn.click(force=True, timeout=8000)
        except Exception as e:
            log.info("row download click failed for %s %s: %s", category, date, e)
            continue

        # wait for the file-type dialog to actually open
        try:
            page.wait_for_selector(_DIALOG_OPEN_SEL, timeout=10000)
        except Exception:
            log.info("file-type dialog did not open for %s %s (attempt %d)",
                     category, date, attempt + 1)
            continue

        _select_pdf_radio(page)
        confirm = _dialog_download_button(page)
        if confirm is None:
            log.info("dialog confirm button not found for %s %s (attempt %d)",
                     category, date, attempt + 1)
            _dismiss_dialog(page)
            continue

        try:
            with page.expect_download(timeout=45000) as dl:
                # The click's own post-action navigation wait can time out even
                # though the download fires; swallow it and let expect_download
                # capture the event.
                try:
                    confirm.click(force=True, timeout=8000)
                except Exception:
                    pass
            save_download(dl.value, out_path)
            _dismiss_dialog(page)
            return True
        except Exception as e:
            log.info("dialog download failed for %s %s (attempt %d): %s",
                     category, date, attempt + 1, e)
            _dismiss_dialog(page)
            continue
    return False


_BLOB_FETCH_JS = r"""async () => {
    const f = document.querySelector("iframe[src^='blob:'], embed[src^='blob:']");
    const src = f && f.src;
    if (!src) return null;
    const r = await fetch(src);
    const buf = new Uint8Array(await r.arrayBuffer());
    let s = ''; for (let i = 0; i < buf.length; i++) s += String.fromCharCode(buf[i]);
    return btoa(s);
}"""


def download_by_url(page, url: str, out_path) -> bool:
    """Download a document PDF from a direct/API URL. Handles both a real file
    download and an inline blob-iframe render."""
    if not url:
        return False
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    full = url if url.startswith("http") else BASE + url
    # A stored record must not be able to steer this anywhere but the
    # provider's own site. Before this check the value went straight to
    # page.goto in the signed-in tab.
    if not is_safe_url(full):
        log.error("refusing a URL that is not on this provider's host")
        return False
    try:
        with page.expect_download(timeout=25000) as dl:
            try:
                page.goto(full)
            except Exception as e:
                if "download is starting" not in str(e).lower():
                    raise
        from receipt_pdf import save_download
        save_download(dl.value, out_path)
        return True
    except Exception:
        pass
    try:
        page.wait_for_selector("iframe[src^='blob:'], embed[src^='blob:']", timeout=15000)
        page.wait_for_timeout(1200)
        b64 = page.evaluate(_BLOB_FETCH_JS)
        if b64:
            data = base64.b64decode(b64)
            if b"%PDF-" in data[:1024]:
                out_path.write_bytes(data)
                return True
    except Exception as e:
        log.info("download_by_url blob fallback failed for %s: %s", url, e)
    return False


def download_named(page, title: str, out_path) -> bool:
    """Click the download control for the document whose title/date matches, and
    capture the resulting download event to out_path. Falls back to a direct PDF
    href if clicking does not fire a download event."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    needle = re.sub(r"\s+", " ", title).strip()
    date_hint, _ = parse_period_date(title)

    control = None
    href_hit = ""
    try:
        loc = page.locator("a[download], a[href*='.pdf'], a, button, [role='button']")
        for i in range(min(loc.count(), 500)):
            el = loc.nth(i)
            try:
                own = (el.inner_text(timeout=400) or "") + " " + \
                    (el.get_attribute("aria-label") or "")
            except Exception:
                continue
            href = el.get_attribute("href") or ""
            has_dl_attr = el.get_attribute("download") is not None
            is_pdf_href = bool(re.search(r"\.pdf(\?|$)", href, re.I))
            says_dl = bool(re.search(r"download|\bpdf\b|save\s+pdf|view\s+pdf", own, re.I))
            if not (has_dl_attr or is_pdf_href or says_dl):
                continue
            if re.search(r"\b(csv|excel|xlsx?|ofx|qfx|qbo)\b", own, re.I):
                continue
            if FORBIDDEN_CONTROL_RE.search(own) and not (has_dl_attr or is_pdf_href):
                continue
            hay = own
            if needle.lower()[:30] not in hay.lower():
                try:
                    hay = el.evaluate(
                        "el => { let n = el; for (let i=0;i<8 && n;i++){ n=n.parentElement;"
                        " if(n && (n.innerText||'').length>8) return n.innerText; } return ''; }")
                except Exception:
                    hay = ""
            hay_l = (hay or "").lower()
            matched = needle.lower()[:30] in hay_l
            if not matched and date_hint:
                dm = MONTH_YEAR_RE.search(needle)
                if dm and dm.group(0).lower() in hay_l:
                    matched = True
            if matched:
                control = el
                href_hit = href if (is_pdf_href or has_dl_attr) else ""
                break
    except Exception:
        pass

    if control is None:
        log.info("download control not found for %r", title)
        return False

    from receipt_pdf import save_download
    try:
        with page.expect_download(timeout=45000) as dl:
            control.click()
        save_download(dl.value, out_path)
        return True
    except Exception as e:
        log.info("download click did not fire an event for %r: %s", title, e)
    if href_hit:
        return download_by_url(page, href_hit, out_path)
    return False


# ---------------------------------------------------------------------------
# Document source pages. document_source_urls() yields (url, label) pairs that
# cmd_discover scans. Repair the URLs after diagnose.bat confirms the real ones.
# ---------------------------------------------------------------------------
STATEMENT_URLS = [
    URLS["statements"],
]
YEAR_END_URL = URLS["year_end"]
TAX_URL = URLS["tax"]


def document_source_urls() -> List[Tuple[str, str]]:
    """(url, source_label) pairs to scan for downloadable documents."""
    pairs = [(u, "statements") for u in STATEMENT_URLS]
    pairs.append((YEAR_END_URL, "year-end"))
    if TAX_URL not in [u for u, _ in pairs]:
        pairs.append((TAX_URL, "tax"))
    return pairs


def find_row_download(page, title: str, date_text: str = ""):
    """Re-find a row's safe download control by its text (diagnose helper)."""
    try:
        rows = page.locator(FALLBACK["doc_row"])
        for i in range(rows.count()):
            row = rows.nth(i)
            try:
                text = row.inner_text(timeout=800) or ""
            except Exception:
                continue
            if title and title[:40] not in text:
                continue
            if date_text and date_text not in text:
                continue
            link = row.locator("a[download], a[href$='.pdf'], a[href*='.pdf']")
            if link.count() > 0:
                return link.first
            for b in row.locator("button, a").all():
                try:
                    label = (b.inner_text(timeout=600) or "") + \
                        (b.get_attribute("aria-label") or "")
                except Exception:
                    label = ""
                if is_safe_control(label):
                    return b
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Host allowlist. Added repo-wide after a review found this app would fetch or
# navigate to whatever URL a stored record or a page attribute contained, using
# the live signed-in session. Parsed, never a string prefix, so a lookalike
# host cannot walk through.
# ---------------------------------------------------------------------------
ALLOWED_HOSTS = {'americanexpress.com'}


def is_safe_url(url: str) -> bool:
    """True only for an https URL on one of this provider's own hosts."""
    from urllib.parse import urlparse
    try:
        got = urlparse(url or "")
    except ValueError:
        return False
    if got.scheme != "https" or not got.hostname:
        return False
    if got.username or got.password:
        return False
    host = got.hostname.lower().rstrip(".")
    return any(host == h or host.endswith("." + h) for h in ALLOWED_HOSTS)
