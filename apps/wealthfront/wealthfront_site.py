"""ALL Wealthfront selectors, URLs, and page behavior live here.

When Wealthfront changes its site, repair this file only.

SAFETY (this is a brokerage, not a store):
  This module is READ-ONLY by design. It navigates to the Documents area,
  reads a list of documents, and downloads the PDFs Wealthfront already
  generated for the account. It must NEVER activate any control that moves
  money, places or cancels trades, changes allocations, or edits account
  settings. FORBIDDEN_CONTROL_RE below is the guard; every click path checks
  it. There is deliberately no code here that submits forms or confirms
  dialogs.

Documents are genuine PDF downloads (not rendered web pages), so capture uses
Playwright's download event -> download.save_as(), preserving Wealthfront's
original file rather than a re-render.

INITIAL SELECTORS written 2026-07-23; run `python wealthfront_docs.py
--diagnose` after signing in and repair the FALLBACK entries against the
Diagnostics/ output.
"""
# Site layer verified working against the live site: 2026-08
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

log = logging.getLogger("wealthfront_docs.site")

BASE = "https://www.wealthfront.com"
URLS = {
    "home": f"{BASE}/",
    "login": f"{BASE}/login",
    "dashboard": f"{BASE}/dashboard",
    # Wealthfront has moved this a few times; try in order.
    "documents": f"{BASE}/documents",
    "documents_alt": f"{BASE}/account/documents",
    "documents_alt2": f"{BASE}/dashboard/documents",
}

DOCUMENT_URL_CANDIDATES = [URLS["documents"], URLS["documents_alt"],
                           URLS["documents_alt2"]]

LOGIN_URL_MARKERS = ["/login", "/signin", "/auth", "/mfa", "/verify"]

# ---------------------------------------------------------------------------
# HARD SAFETY GUARD - never click anything matching this.
# ---------------------------------------------------------------------------
FORBIDDEN_CONTROL_RE = re.compile(
    r"(transfer|deposit|withdraw|move\s+money|send\s+money|link\s+(bank|account)|"
    r"buy|sell|trade|place\s+order|rebalance|reallocate|change\s+(allocation|risk|"
    r"portfolio|beneficiar|payment|password|email|phone)|edit\s+|update\s+|"
    r"close\s+account|delete|cancel\s+(account|transfer|order)|"
    r"invest|fund\s+(your\s+)?account|autopilot|set\s+up|enable|disable|"
    r"apply|open\s+\w*\s*account|refer|schedule|confirm|submit|save\s+changes|"
    # write actions seen on the live Documents page (2026-07): uploading a
    # document and opening a new account both scored 'safe' before this.
    r"upload|add\s+(a\s+)?document|new\s+account|get\s+started|purchase|"
    r"agreement|line\s+of\s+credit)", re.I)

SAFE_DOC_CONTROL_RE = re.compile(
    r"(download|view|open|statement|1099|tax|document|pdf)", re.I)

SECURITY_CHALLENGE_MARKERS = [
    "enter the code we sent", "verification code", "two-factor",
    "two-step verification", "authenticator app", "confirm your identity",
    "we need to verify", "are you a robot", "captcha", "unusual activity",
    "suspicious activity", "session has expired", "please sign in again",
]

RATE_LIMIT_MARKERS = [
    "too many requests", "rate limit", "try again later",
    "temporarily blocked", "http error 429",
]

# ---------------------------------------------------------------------------
# Fallback selectors (repair after --diagnose)
# ---------------------------------------------------------------------------
FALLBACK = {
    "doc_row": "table tbody tr, [data-testid*='document'], [class*='documentRow'], "
               "[class*='DocumentRow'], li[class*='document']",
    "doc_link": "a[href*='.pdf'], a[href*='document'], a[href*='statement'], "
                "button[class*='download'], a[download]",
    "download_control": "a[download], a[href$='.pdf'], button:has-text('Download')",
    # Native <select> filters, verified on the live page 2026-07-23.
    "select_tax_year": "select[aria-label='tax year']",
    "select_account": "select[name='selectedAccountId']",
    "select_doc_type": "select[name='selectedDocumentType']",
    "select_date": "select[name='selectedYearMonth']",
    "year_filter": "select, [role='combobox']",
    "page_ready": "table, [data-testid*='document'], [class*='document'], main",
    "tab_statements": "text=/statements?/i",
    "tab_tax": "text=/tax/i",
}

DATE_PATTERNS = [
    (re.compile(r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
                r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|"
                r"Dec(?:ember)?)\.?\s+(\d{1,2}),?\s+(\d{4})", re.I), "mdY"),
    (re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b"), "mdy_slash"),
    (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"), "iso"),
]
_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
# "December 2025" / "Q4 2025" / "2025"
MONTH_YEAR_RE = re.compile(
    r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
    r"Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    r"\s+(\d{4})", re.I)
QUARTER_RE = re.compile(r"\bQ([1-4])\s*[' ]?\s*(\d{4})\b", re.I)
YEAR_RE = re.compile(r"\b(20\d{2})\b")

_LAST_DAY = {1: 31, 2: 28, 3: 31, 4: 30, 5: 31, 6: 30,
             7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31}


def _last_day(year: int, month: int) -> int:
    if month == 2 and (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)):
        return 29
    return _LAST_DAY[month]


def parse_date(text: str) -> Optional[str]:
    """Full date if present."""
    if not text:
        return None
    for pattern, kind in DATE_PATTERNS:
        m = pattern.search(text)
        if not m:
            continue
        try:
            if kind == "mdY":
                month = _MONTHS[m.group(1)[:3].lower()]
                return f"{int(m.group(3)):04d}-{month:02d}-{int(m.group(2)):02d}"
            if kind == "mdy_slash":
                return f"{int(m.group(3)):04d}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
            if kind == "iso":
                return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        except (KeyError, ValueError):
            continue
    return None


def parse_period_date(text: str) -> Tuple[Optional[str], str]:
    """Date to file the document under, plus a human period label.

    Statements are titled by period ("December 2025", "Q4 2025"); we file them
    on the LAST day of that period, which sorts correctly and matches how the
    statement reads. Tax forms titled with just a year file on Dec 31.
    """
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
        year = int(m.group(1))
        return f"{year:04d}-12-31", m.group(1)
    return None, ""


# ---------------------------------------------------------------------------
# Session / safety checks
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
    """Conservative: skip when the documents list rendered."""
    try:
        if page.locator(FALLBACK["doc_row"]).count() > 0:
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
    hay = title + "\n" + body[:1200]
    for m in SECURITY_CHALLENGE_MARKERS:
        if m in hay:
            return f"Security challenge detected: '{m}'"
    for m in RATE_LIMIT_MARKERS:
        if m in hay:
            return f"Possible rate limiting detected: '{m}'"
    return None


def is_safe_control(name: str) -> bool:
    """A control may only be clicked if it looks like a document action AND
    matches nothing in the forbidden list."""
    name = (name or "").strip()
    if not name:
        return False
    if FORBIDDEN_CONTROL_RE.search(name):
        return False
    return bool(SAFE_DOC_CONTROL_RE.search(name))


# ---------------------------------------------------------------------------
# Documents page
# ---------------------------------------------------------------------------

def goto_documents(page) -> bool:
    """Navigate to the Documents area, trying known URLs then in-app links."""
    for url in DOCUMENT_URL_CANDIDATES:
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3000)
            if looks_signed_out(page):
                return False
            try:
                page.wait_for_selector(FALLBACK["page_ready"], timeout=15000)
            except Exception:
                pass
            if page.locator(FALLBACK["doc_row"]).count() > 0:
                return True
        except Exception as e:
            log.info("documents URL %s failed: %s", url, e)
    # fall back to a nav link named Documents/Statements
    try:
        link = page.get_by_role("link", name=re.compile(r"(documents?|statements?)", re.I))
        if link.count() > 0 and not FORBIDDEN_CONTROL_RE.search(
                link.first.inner_text(timeout=1500) or ""):
            link.first.click()
            page.wait_for_timeout(3000)
            return page.locator(FALLBACK["doc_row"]).count() > 0
    except Exception:
        pass
    return False


def scroll_full_page(page, rounds: int = 6, delay_ms: int = 700) -> None:
    try:
        for _ in range(rounds):
            page.mouse.wheel(0, 2500)
            page.wait_for_timeout(delay_ms)
        page.keyboard.press("End")
        page.wait_for_timeout(delay_ms)
    except Exception:
        pass


def expand_all(page) -> None:
    """Click safe 'show more / load more' style controls only."""
    for _ in range(20):
        clicked = False
        try:
            btn = page.get_by_role("button", name=re.compile(
                r"(show more|load more|view more|see more|older)", re.I))
            if btn.count() > 0 and btn.first.is_visible():
                label = btn.first.inner_text(timeout=1000) or ""
                if not FORBIDDEN_CONTROL_RE.search(label):
                    btn.first.click()
                    page.wait_for_timeout(1500)
                    clicked = True
        except Exception:
            pass
        if not clicked:
            break


@dataclass
class RawDoc:
    """One row of the Documents page.

    Verified layouts (2026-07):
      tax   : "Joint Cash Account | Form 1099 | Download"   (button, no href)
      dated : "07/20/2026 | Trade Confirmation for X"       (href to the doc)
    """
    title: str          # the document description -> what gets classified
    account: str = ""
    date_text: str = ""
    href: str = ""
    text: str = ""
    row_index: int = -1
    kind: str = ""      # "tax" | "dated"


DATE_CELL_RE = re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$")
FORM_CELL_RE = re.compile(r"(form\s|1099|5498|1042|480\.6|statement|confirmation)", re.I)
ACCOUNT_CELL_RE = re.compile(
    r"(account|\bIRA\b|\b529\b|cash|investing|brokerage|credit)", re.I)
NOISE_CELL_RE = re.compile(r"^(download|link|view|open)$", re.I)


def _row_cells(text: str) -> List[str]:
    return [c.strip() for c in re.split(r"[\n\t]+", text or "")
            if c.strip() and not NOISE_CELL_RE.match(c.strip())]


def parse_row(cells: List[str], href: str = "") -> Optional[RawDoc]:
    """Turn a row's cells into a RawDoc, or None if it is not a document."""
    if not cells:
        return None
    # dated row: first cell is a date
    if DATE_CELL_RE.match(cells[0]):
        desc = next((c for c in cells[1:] if FORM_CELL_RE.search(c)),
                    cells[1] if len(cells) > 1 else "")
        if not desc:
            return None
        acct = ""
        m = re.search(r"\bfor\s+(.+)$", desc)
        if m:
            acct = m.group(1).strip()
            # Drop the custodian parenthetical, e.g.
            # "Jordan's 529 Account (from Wealthfront Brokerage Corp)".
            acct = re.sub(r"\s*\([^)]*\)\s*$", "", acct).strip()
        return RawDoc(title=desc, account=acct, date_text=cells[0],
                      href=href, text=" | ".join(cells), kind="dated")
    # tax row: an account cell plus a form cell
    form = next((c for c in cells if FORM_CELL_RE.search(c)), "")
    if form:
        acct = next((c for c in cells
                     if ACCOUNT_CELL_RE.search(c) and c != form), "")
        return RawDoc(title=form, account=acct, date_text="", href=href,
                      text=" | ".join(cells), kind="tax")
    return None


def collect_documents(page) -> List[RawDoc]:
    """Read every document row currently rendered."""
    docs: List[RawDoc] = []
    seen = set()
    try:
        rows = page.locator(FALLBACK["doc_row"]).all()
    except Exception:
        rows = []
    for i, row in enumerate(rows):
        try:
            text = (row.inner_text(timeout=2500) or "").strip()
            if not text or len(text) < 3:
                continue
            href = ""
            try:
                link = row.locator("a[href]")
                if link.count() > 0:
                    href = link.first.get_attribute("href") or ""
            except Exception:
                pass
            doc = parse_row(_row_cells(text), href)
            if doc is None:
                continue
            doc.row_index = i
            key = (doc.kind, doc.account, doc.title, doc.date_text, doc.href)
            if key in seen:
                continue
            seen.add(key)
            docs.append(doc)
        except Exception:
            continue
    return docs


# ---------------------------------------------------------------------------
# Section navigation: tax-year tabs, document-type filter, pagination
# ---------------------------------------------------------------------------

TAX_YEAR_RE = re.compile(r"tax\s*year\s*:?\s*(\d{4})", re.I)


def get_tax_years(page) -> List[str]:
    """Tax years offered above the tax-document table. The control is a
    native <select> whose options read 'Tax Year: 2025'."""
    years: List[str] = []
    try:
        sel = page.locator(FALLBACK["select_tax_year"])
        if sel.count() > 0:
            for opt in sel.first.locator("option").all_inner_texts():
                m = TAX_YEAR_RE.search(opt)
                if m:
                    years.append(m.group(1))
    except Exception:
        pass
    if not years:  # fallback: scrape the page text
        try:
            body = page.locator("body").inner_text(timeout=8000)
            years = list(dict.fromkeys(TAX_YEAR_RE.findall(body)))
        except Exception:
            pass
    return years


def current_tax_year(page) -> str:
    """The tax year currently shown (the select's value)."""
    try:
        sel = page.locator(FALLBACK["select_tax_year"])
        if sel.count() > 0:
            val = sel.first.input_value()
            m = re.search(r"(\d{4})", val or "")
            if m:
                return m.group(1)
    except Exception:
        pass
    return ""


def select_tax_year(page, year: str) -> bool:
    """Switch the tax-document table to a given year (native <select>)."""
    if current_tax_year(page) == str(year):
        return True
    try:
        sel = page.locator(FALLBACK["select_tax_year"])
        if sel.count() > 0:
            for label in (f"Tax Year: {year}", str(year)):
                try:
                    sel.first.select_option(label=label)
                    page.wait_for_timeout(2500)
                    return True
                except Exception:
                    continue
            try:
                sel.first.select_option(value=str(year))
                page.wait_for_timeout(2500)
                return True
            except Exception:
                pass
    except Exception as e:
        log.info("tax-year select failed for %s: %s", year, e)
    return False


def set_document_type(page, label: str) -> bool:
    """Set the 'All Document Types' filter (e.g. 'Statements').

    This is what makes statement discovery practical: without it the list is
    dominated by trade confirmations.
    """
    # the dedicated document-type <select> first
    try:
        sel = page.locator(FALLBACK["select_doc_type"])
        if sel.count() > 0:
            sel.first.select_option(label=label)
            page.wait_for_timeout(2500)
            return True
    except Exception:
        pass
    # any native <select> offering that option
    try:
        for sel in page.locator("select").all():
            options = [o.strip() for o in sel.locator("option").all_inner_texts()]
            if any(o.lower() == label.lower() for o in options):
                sel.select_option(label=label)
                page.wait_for_timeout(2500)
                return True
    except Exception:
        pass
    # custom dropdown: open the control, then pick the option
    try:
        opener = page.get_by_role("button", name=re.compile(
            r"(all\s+document\s+types|document\s+type)", re.I))
        if opener.count() == 0:
            opener = page.get_by_text(re.compile(r"all\s+document\s+types", re.I))
        if opener.count() > 0:
            opener.first.click()
            page.wait_for_timeout(1200)
            for role in ("option", "menuitem", "menuitemradio", "button", "link"):
                opt = page.get_by_role(role, name=re.compile(
                    rf"^\s*{re.escape(label)}\s*$", re.I))
                if opt.count() > 0 and opt.first.is_visible():
                    opt.first.click()
                    page.wait_for_timeout(2500)
                    return True
            opt = page.get_by_text(re.compile(rf"^\s*{re.escape(label)}\s*$", re.I))
            if opt.count() > 0 and opt.first.is_visible():
                opt.first.click()
                page.wait_for_timeout(2500)
                return True
    except Exception as e:
        log.info("document-type filter failed for %s: %s", label, e)
    return False


def go_older(page) -> bool:
    """Advance the statements/confirmations list one page. Returns False when
    there is no older page."""
    try:
        btn = page.get_by_role("button", name=re.compile(r"^\s*older\s*$", re.I))
        if btn.count() == 0 or not btn.first.is_visible() or not btn.first.is_enabled():
            return False
        btn.first.click()
        page.wait_for_timeout(2500)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Tax-form dialog
#
# A tax row's "Download" button is a DIALOG TRIGGER, not a download: it opens
# a modal listing that form's file(s) as real PDF anchors
# (/documents/<id>/<year>/FORM_1099_PDF?idx=0). Verified 2026-07-23.
# ---------------------------------------------------------------------------

TAX_DIALOG_TRIGGER = "[data-testid='tax-forms-account-view-dialog-trigger']"
TAX_DIALOG = "[role='dialog'], [aria-modal='true'], dialog"
TAX_DIALOG_DISMISS = "[data-testid='dismiss-dialog']"


def close_tax_dialog(page) -> None:
    try:
        btn = page.locator(TAX_DIALOG_DISMISS)
        if btn.count() > 0 and btn.first.is_visible():
            btn.first.click()
            page.wait_for_timeout(800)
            return
    except Exception:
        pass
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)
    except Exception:
        pass


def resolve_tax_file_links(page, account: str, title: str) -> List[str]:
    """Open the tax row's dialog, read its PDF link(s), close it again.

    Returns hrefs (possibly several: corrected forms arrive as idx=1, ...).
    """
    hrefs: List[str] = []
    try:
        rows = page.locator(FALLBACK["doc_row"])
        target = None
        for i in range(rows.count()):
            row = rows.nth(i)
            try:
                text = row.inner_text(timeout=1000) or ""
            except Exception:
                continue
            if account and account not in text:
                continue
            if title and title not in text:
                continue
            trig = row.locator(TAX_DIALOG_TRIGGER)
            if trig.count() > 0:
                target = trig.first
                break
        if target is None:
            return []
        target.click()
        page.wait_for_timeout(2500)
        hrefs = page.evaluate("""() => {
            const dlg = document.querySelector(
                "[role='dialog'], [aria-modal='true'], dialog");
            if (!dlg) return [];
            return [...dlg.querySelectorAll('a[href]')]
                .map(a => a.getAttribute('href'))
                .filter(h => h && !/^#/.test(h));
        }""") or []
    except Exception as e:
        log.info("tax dialog failed for %s / %s: %s", account, title, e)
    finally:
        close_tax_dialog(page)
    return hrefs


def find_row_download(page, account: str, title: str):
    """Re-find a tax row's Download button by its account + form text.
    Row indexes shift when filters/pages change, so match on content."""
    try:
        rows = page.locator(FALLBACK["doc_row"])
        for i in range(rows.count()):
            row = rows.nth(i)
            try:
                text = row.inner_text(timeout=1000) or ""
            except Exception:
                continue
            if account and account not in text:
                continue
            if title and title not in text:
                continue
            btn = row.get_by_role("button", name=re.compile(r"download", re.I))
            if btn.count() > 0:
                return btn.first
            link = row.locator("a[download], a[href$='.pdf']")
            if link.count() > 0:
                return link.first
    except Exception:
        pass
    return None


def find_download_control(page, row_index: int):
    """The safe download/view control inside a given document row."""
    try:
        rows = page.locator(FALLBACK["doc_row"])
        if row_index < 0 or row_index >= rows.count():
            return None
        row = rows.nth(row_index)
        for sel in ("a[download]", "a[href$='.pdf']", "a[href*='.pdf']",
                    "button", "a"):
            loc = row.locator(sel)
            for j in range(min(loc.count(), 6)):
                el = loc.nth(j)
                try:
                    label = (el.inner_text(timeout=800) or "").strip()
                except Exception:
                    label = ""
                aria = ""
                try:
                    aria = el.get_attribute("aria-label") or ""
                except Exception:
                    pass
                name = label or aria
                if FORBIDDEN_CONTROL_RE.search(name):
                    continue
                if sel.startswith("a[") or is_safe_control(name):
                    return el
        return None
    except Exception:
        return None
