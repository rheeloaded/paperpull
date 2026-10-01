"""ALL Robinhood.com selectors, URLs, and page behavior live here.

When Robinhood changes its site, repair this file only.

SAFETY (this is a brokerage / crypto account):
  This module is strictly READ-ONLY. It navigates to the reports/statements
  and tax areas, reads a list of documents, and downloads the PDFs Robinhood
  already generated. It must NEVER activate any control that buys, sells,
  trades, places or cancels an order, transfers/withdraws/deposits money,
  moves or converts crypto, exercises options, closes a position, stakes, or
  changes any setting. FORBIDDEN_CONTROL_RE is the guard; a control must ALSO
  look like a document action (SAFE_DOC_CONTROL_RE) before it may be clicked.
  There is no code here that submits a form or confirms a dialog.

Documents are genuine PDF downloads (not rendered pages). Robinhood is a
heavy React SPA backed by a JSON API, so - like the USAA project - discovery
prefers capturing the documents API response, with table scraping as a
fallback. The selectors are verified against the live signed-in pages (see
the date recorded under this docstring). When the provider redesigns, run
`diagnose.bat` and repair the FALLBACK entries + goto_documents URLs +
collect_documents_via_api matcher against Diagnostics/.
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

from paperpull_core.dates import last_day as _last_day
from paperpull_core.dates import checked as _checked_date
from paperpull_core.controls import click_next_page as _click_next_page

log = logging.getLogger("robinhood_docs.site")

BASE = "https://robinhood.com"
URLS = {
    "home": f"{BASE}/",
    "login": f"{BASE}/login",
    # Document-area candidates (Robinhood moves these around). goto_documents
    # tries each; if none render a list, it uses whatever page is open.
    "documents": f"{BASE}/account/reports-and-statements/documents",
    "statements": f"{BASE}/account/reports-and-statements/statements",
    "documents_alt": f"{BASE}/documents",
    "tax_center": f"{BASE}/account/reports-and-statements/tax-center",
}
DOCUMENT_URL_CANDIDATES = [URLS["documents"], URLS["statements"],
                           URLS["documents_alt"], URLS["tax_center"]]

LOGIN_URL_MARKERS = ["/login", "/signin", "/sign-in", "/auth", "/mfa",
                     "/verification", "/challenge"]

# ---------------------------------------------------------------------------
# HARD SAFETY GUARD - never click anything matching this. Tuned for a
# brokerage / crypto account.
# ---------------------------------------------------------------------------
FORBIDDEN_CONTROL_RE = re.compile(
    r"(buy\b|sell\b|trade\b|place\s+order|review\s+order|submit\s+order|"
    r"cancel\s+order|market\s+order|limit\s+order|stop\s+order|"
    r"transfer|withdraw|deposit|wire\b|move\s+money|send\b|receive\b|"
    r"convert|swap\b|exchange\b|stake\b|unstake\b|earn\b|lend\b|"
    r"exercise|close\s+position|sell\s+all|liquidate|"
    r"options?\b|margin\b|borrow\b|gold\b|subscribe|"
    r"apply|open\s+\w*\s*account|fund\b|add\s+money|link\s+(bank|account)|"
    r"enable|disable|activate|\bchange\s+|\bedit\s+|\bupdate\s+|set\s+up|"
    r"delete|remove|close\s+account|beneficiar|password|"
    r"generate\s+report|create\s+report|generate\b|"
    r"confirm|continue|next\b|agree|accept|authorize)", re.I)

SAFE_DOC_CONTROL_RE = re.compile(
    r"(download|view|open|print|pdf|statement|document|1099|1042|"
    r"tax|report|export)", re.I)

SECURITY_CHALLENGE_MARKERS = [
    "enter the code", "verification code", "6-digit", "two-factor",
    "two-step", "authenticator", "confirm your identity", "verify your identity",
    "we sent a code", "device approval", "approve this login", "unusual",
    "are you a robot", "captcha", "let's verify", "check your email",
    "check your phone", "your session has expired", "log back in",
]

RATE_LIMIT_MARKERS = [
    "too many requests", "rate limit", "try again later",
    "temporarily unavailable", "http error 429", "unusual traffic",
]

# ---------------------------------------------------------------------------
# Fallback selectors (repair after diagnose)
# ---------------------------------------------------------------------------
FALLBACK = {
    "doc_row": ("table tbody tr, [role='row'], [class*='documentRow'], "
                "[class*='DocumentRow'], [class*='row'][class*='document'], "
                "[data-testid*='document'], li[class*='document']"),
    "doc_link": ("a[href*='.pdf'], a[href*='document'], a[href*='statement'], "
                 "a[download], button[class*='download']"),
    "download_control": "a[download], a[href$='.pdf'], button:has-text('Download')",
    "page_ready": ("table, [role='row'], [class*='document'], [class*='statement'], "
                   "main, [role='main']"),
    "next_page": ("a[aria-label*='Next' i], button[aria-label*='Next' i], "
                  "[class*='next']"),
}

# ---------------------------------------------------------------------------
# Date parsing (shared with the other projects)
# ---------------------------------------------------------------------------
DATE_PATTERNS = [
    (re.compile(r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
                r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|"
                r"Dec(?:ember)?)\.?\s+(\d{1,2}),?\s+(\d{4})", re.I), "mdY"),
    (re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b"), "mdy_slash"),
    (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})(?!\d)"), "iso"),
]
_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
MONTH_YEAR_RE = re.compile(
    r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
    r"Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    r"\s+(\d{4})", re.I)
QUARTER_RE = re.compile(r"\bQ([1-4])\s*[' ]?\s*(\d{4})\b", re.I)
YEAR_RE = re.compile(r"\b(19|20)(\d{2})\b")


def _parse_date_from_page(text: str) -> Optional[str]:
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


def parse_date(text):
    """The date this provider's page is showing, as YYYY-MM-DD.

    The reading is below, unchanged. This only refuses to believe a result
    that names a day which does not exist, because a reference number is
    shaped like a date and used to be taken for one."""
    return _checked_date(_parse_date_from_page(text), None)


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


# The year a tax form prints for itself. Every 1099 names it beside the
# form, "2025 1099-DIV" or "Form 1099-B 2025", or in the words "Tax Year
# 2025". A year that is part of an amount, an id or a date is not one, so
# "2025.50", "2025-0045" and "2025/01" are ruled out, and so is a year with
# a letter or a digit against it.
_PRINTED_YEAR = r"(?<![\w.,$\-/])((?:19|20)\d{2})(?!\d|[.,\-/]\d)"
_PRINTED_TAX_YEAR_RES = (
    re.compile(r"\btax\s+year\s*:?\s*" + _PRINTED_YEAR, re.I),
    re.compile(_PRINTED_YEAR + r"\s+tax\s+(?:year|information|reporting)\b", re.I),
    re.compile(_PRINTED_YEAR + r"(?:\s*\*\s*|\s+)(?:consolidated\s+)?(?:form\s+)?"
               r"(?:1099|1042-?S|5498)\b", re.I),
    re.compile(r"\b(?:form\s+)?(?:1099|1042-?S|5498)(?:-[A-Z]{1,4})?\*?[ \t]+"
               + _PRINTED_YEAR, re.I),
)


def printed_tax_year(text: str, today=None) -> str:
    """The tax year a saved form prints, or "".

    For a form the page gave no year. The year most of those places name,
    when it is more than half of them, and only a year that has ended,
    since a form for a year still running does not exist yet. Anything
    less certain gives "", and the form keeps the name it has."""
    from collections import Counter
    from datetime import date as _date
    this_year = (today or _date.today()).year
    said = Counter()
    for rx in _PRINTED_TAX_YEAR_RES:
        for m in rx.finditer(text or ""):
            if int(m.group(1)) < this_year:
                said[m.group(1)] += 1
    if not said:
        return ""
    year, n = said.most_common(1)[0]
    return year if n * 2 > sum(said.values()) else ""


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
            return f"Possible rate limiting detected: '{m}'"
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
# Documents page
# ---------------------------------------------------------------------------

def goto_documents(page) -> bool:
    """Navigate to a document area. The page already open is checked
    FIRST, so one the person navigated to by hand is read as it is. The
    candidate loop used to run unconditionally, which replaced a hand
    opened page and, when every candidate missed, left the browser on a
    dead page outside the signed-in app (#30, found on Navy Federal, the
    same shape here)."""
    try:
        if (is_safe_url(page.url or "") and not looks_signed_out(page)
                and page.locator(FALLBACK["doc_row"]).count() > 1):
            return True
    except Exception:
        pass
    for url in DOCUMENT_URL_CANDIDATES:
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3500)
            if looks_signed_out(page):
                return False
            try:
                page.wait_for_selector(FALLBACK["page_ready"], timeout=12000)
            except Exception:
                pass
            if page.locator(FALLBACK["doc_row"]).count() > 1:
                return True
        except Exception as e:
            log.info("documents URL %s failed: %s", url, e)
    try:
        link = page.get_by_role("link", name=re.compile(
            r"(documents?|statements?|reports?|tax)", re.I))
        if link.count() > 0:
            label = link.first.inner_text(timeout=1500) or ""
            if not FORBIDDEN_CONTROL_RE.search(label):
                link.first.click()
                page.wait_for_timeout(3000)
                return page.locator(FALLBACK["doc_row"]).count() > 1
    except Exception:
        pass
    return page.locator(FALLBACK["doc_row"]).count() > 1


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
    """Click 'View More' / 'Show more' repeatedly until the full list loads.
    Robinhood's 'View More' is an <a> link (not a button), so both roles are
    tried."""
    pat = re.compile(r"^\s*(show|load|view|see)\s+more\s*$|^\s*view\s+all\s*$|^\s*older\s*$", re.I)
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
    """One page forward, through a control that says it pages forward.

    Judged by an allowlist in the core rather than by FORBIDDEN_CONTROL_RE,
    because that blocklist refuses the word "next". Correctly, since "Next"
    is also what a wizard's commit button says, and fatally here, because it
    meant this could never page forward at all and the run reported success
    having seen only the first page.
    """
    return _click_next_page(page, FALLBACK["next_page"])


@dataclass
class RawDoc:
    title: str
    account: str = ""
    date_text: str = ""
    href: str = ""
    text: str = ""
    row_index: int = -1
    kind: str = "doc"
    # The tax year the page shows beside a tax form whose own name carries
    # none, "" otherwise. The download presses only a control of this year.
    tax_year: str = ""


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
    """Scrape document rows from the visible table/list (fallback path)."""
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


def collect_documents_via_api(page) -> List[dict]:
    """Capture Robinhood's documents JSON API as the page loads/pages. Repair
    the URL/response matcher after diagnose. Returns raw document dicts."""
    batches: List[list] = []

    def on_resp(r):
        try:
            u = r.url
            if not re.search(r"document|statement|report", u, re.I):
                return
            if "json" not in (r.headers.get("content-type", "") or "").lower():
                return
            data = json.loads(r.text())
            # Robinhood list endpoints usually return {"results":[...]} or a
            # bare list. Accept either.
            items = None
            if isinstance(data, dict):
                for k in ("results", "documents", "data", "items"):
                    if isinstance(data.get(k), list):
                        items = data[k]
                        break
            elif isinstance(data, list):
                items = data
            if items:
                batches.append(items)
        except Exception:
            pass

    page.on("response", on_resp)
    try:
        goto_documents(page)
        page.wait_for_timeout(3500)
        last = -1
        stagnant = 0
        for _ in range(150):
            for _ in range(3):
                page.mouse.wheel(0, 5000)
                page.wait_for_timeout(700)
            advanced = next_page(page)
            total = sum(len(b) for b in batches)
            if total == last and not advanced:
                stagnant += 1
                if stagnant >= 3:
                    break
            else:
                stagnant = 0
                last = total
    finally:
        try:
            page.remove_listener("response", on_resp)
        except Exception:
            pass

    docs: dict = {}
    for batch in batches:
        for d in batch:
            if not isinstance(d, dict):
                continue
            did = d.get("id") or d.get("documentId") or d.get("url")
            if did and did not in docs:
                docs[did] = d
    return list(docs.values())


_BLOB_FETCH_JS = r"""async () => {
    const f = document.querySelector("iframe[src^='blob:']");
    if (!f || !f.src) return null;
    const r = await fetch(f.src);
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
    # try a genuine download first
    try:
        with page.expect_download(timeout=20000) as dl:
            try:
                page.goto(full)
            except Exception as e:
                if "download is starting" not in str(e).lower():
                    raise
        from paperpull_core.receipt_pdf import save_download
        save_download(dl.value, out_path)
        return True
    except Exception:
        pass
    # inline PDF (blob iframe) fallback
    try:
        page.wait_for_selector("iframe[src^='blob:']", timeout=15000)
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


# ---------------------------------------------------------------------------
# Robinhood document pages (verified 2026-07). Each document is an
# <a download href="#"> whose own text is the title (statements) or whose
# ancestor holds the title (tax "Download PDF"). Clicking it fires a real
# download event. Statements live on per-account pages; tax docs on the tax
# center. Trade confirmations are intentionally not listed here (out of scope).
# ---------------------------------------------------------------------------
# Every statements page this app reads, with the account each belongs to as
# a file name says it. The individual investing account says nothing,
# because every statement saved before a second page was read is keyed and
# named without one, and a key that changed would fetch them all again.
#
# Robinhood Crypto statements were left out when this app was built, only
# because the account it was built on does not trade crypto. A tester who
# does got none of them (#62). The page was on this list before and is read
# the same way as the individual one, under the same guards.
STATEMENT_PAGES = [
    (f"{BASE}/account/reports-statements/individual", ""),
    (f"{BASE}/account/reports-statements/crypto", "Crypto"),
]
STATEMENT_URLS = [url for url, _account in STATEMENT_PAGES]
TAX_URL = f"{BASE}/account/reports-statements/tax"


def document_source_urls() -> List[Tuple[str, str]]:
    """(url, source_label) pairs to scan for downloadable documents."""
    pairs = [(u, f"{a.lower()} statements" if a else "statements")
             for u, a in STATEMENT_PAGES]
    pairs.append((TAX_URL, "tax"))
    return pairs


def account_for(source_url: str) -> str:
    """The account a statements page belongs to. "" for the individual
    investing page, and for any page that is not a statements page."""
    return dict(STATEMENT_PAGES).get(source_url or "", "")


def at_address(current: str, wanted: str) -> bool:
    """True when the tab is on the page it was sent to.

    The query and the fragment may differ, the host and the path may not.
    An address Robinhood sends elsewhere, an account without crypto say,
    is not the page that was asked for, and what it lists is not read as
    that page's documents."""
    from urllib.parse import urlparse
    try:
        now, want = urlparse(current or ""), urlparse(wanted or "")
    except ValueError:
        return False
    return (now.scheme == want.scheme and bool(want.hostname)
            and (now.hostname or "").lower() == want.hostname.lower()
            and now.path.rstrip("/") == want.path.rstrip("/"))


# What discovery and the download both run in the page, so the control that
# is pressed is always the one that was listed.
#
# A tax form's title line does not always carry its year. Robinhood can
# show "Consolidated 1099" with the year somewhere else. Read from the title
# alone the form had no date, and the file was named 0000-00-00 (#62).
# Forms of different years that share a title were also one document, since
# they were told apart by the title alone, so all but the first were dropped
# without a word.
#
# Only on the tax page, and only words that name a tax year as such, "Tax
# year 2025", "2025 tax year", "2025 tax documents" or "Tax forms for 2025".
# A bare year is not one. It can be when a form came out, and "2025 tax
# season" is the season a 2024 form is filed in. Nor is a year inside an id
# or an account, "Account ID 2023-0045" or "(...2021)". A form nothing
# names a tax year for keeps no date rather than a guessed one, and the
# year it prints is read once it is saved.
#
# taxYearOf reads the year in this order, and gives "" rather than guess.
#   1. The form's own card, the nearest box around its control that holds
#      its title and something more, and no other form's control. A card
#      that names two tax years names none.
#   2. The nearest text above the control, outside every other form's card,
#      that is such words and nothing else, or a heading holding them with
#      no date beside them. One among several, tabs or buttons or a
#      dropdown, counts only when it is the chosen one, since the last tab
#      before the list is the nearest and says nothing.
_PAGE_JS_LIB = r"""
  const TITLE_RE = /([A-Z][a-z]+ \d{4}[^\n]*Statement|[^\n]*Consolidated[^\n]*1099[^\n]*|[^\n]*Form 1099[^\n]*|[^\n]*\b1099\b[^\n]*|[^\n]*\b1042-?S\b[^\n]*|[^\n]*\b5498\b[^\n]*)/;
  const TAX_TITLE_RE = /\b(1099|1042-?S|5498)\b/i;
  const ANY_YEAR_RE = /\b(19|20)\d{2}\b/;
  // A year written as a year, and never part of an id, an account or a date.
  const Y = String.raw`(?<![\w.\-\/])((?:19|20)\d{2})(?!\d|[.\-\/]\d)`;
  const NAMED = [
    String.raw`tax\s+year\s*:?\s*` + Y,
    Y + String.raw`\s+tax\s+(?:year|documents?|forms?)\b`,
    String.raw`tax\s+(?:documents?|forms?)\s+for\s+` + Y,
  ];
  const PHRASES = NAMED.map(p => new RegExp(String.raw`\b` + p, 'gi'));
  const YEAR_HEADING = new RegExp(String.raw`^(?:` + NAMED.join('|') + String.raw`)\s*[\u25BE\u25BC\u2304\u02C5]?$`, 'i');
  const A_DATE = /\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?\s+\d{1,2}\b|\b\d{1,2}[\/.-]\d{1,2}[\/.-]\d{2,4}\b/i;

  function ownLabel(el) {
    return ((el.innerText || '') + ' ' + (el.getAttribute('aria-label') || '')).trim();
  }
  function isPdfControl(el) {
    const own = ownLabel(el);
    if (/download\s*csv/i.test(own)) return false;
    if (/download\s*pdf/i.test(own)) return true;
    return el.hasAttribute('download') && TITLE_RE.test(own);
  }
  function holdsAnother(node, el) {
    for (const c of node.querySelectorAll('a[download], a, button, [role=button]')) {
      if (c === el || c.contains(el) || el.contains(c)) continue;
      if (isPdfControl(c)) return true;
    }
    return false;
  }
  function textOf(node) {
    let t = node.innerText || '';
    for (const s of node.querySelectorAll('select, [role=listbox], [role=menu]')) {
      const st = s.innerText || '';
      if (st.trim()) t = t.split(st).join('\n');
    }
    return t;
  }
  // The tax year the text names as such, null when it names two,
  // undefined when it names none.
  function yearIn(text) {
    const said = new Set();
    for (const re of PHRASES) for (const m of text.matchAll(re)) said.add(m[1]);
    if (said.size > 1) return null;
    if (said.size === 1) return [...said][0];
    return undefined;
  }
  function cardOf(el) {
    let node = el;
    for (let i = 0; i < 8 && node && node !== document.body; i++) {
      const t = node.innerText || '';
      if (TITLE_RE.test(t) && t.split('\n').filter(s => s.trim()).length > 1) {
        if (t.length > 600 || holdsAnother(node, el)) return null;
        return node;
      }
      node = node.parentElement;
    }
    return null;
  }
  function labelOf(e) {
    if (e.tagName === 'SELECT') {
      const o = e.options[e.selectedIndex];
      return o ? o.text.replace(/\s+/g, ' ').trim() : '';
    }
    if (e.closest('select')) return '';
    return (e.innerText || '').replace(/\s+/g, ' ').trim();
  }
  function isHeading(e) {
    return /^H[1-6]$/.test(e.tagName) || e.getAttribute('role') === 'heading'
      || e.tagName === 'LEGEND' || e.tagName === 'CAPTION';
  }
  function isChoice(e) {
    if (e.tagName === 'SELECT') return true;
    if (e.closest('[role=tablist], [role=radiogroup], [role=listbox], [role=menu], [role=menubar]')) return true;
    if (e.closest('[role=tab], [role=radio], [role=option], [role=menuitemradio]')) return true;
    const box = e.closest('button, a, [role=button], label, li') || e;
    for (const s of [box.previousElementSibling, box.nextElementSibling]) {
      if (s && YEAR_HEADING.test(labelOf(s))) return true;
    }
    return false;
  }
  function isChosen(e) {
    if (e.tagName === 'SELECT') return true;
    let n = e;
    for (let i = 0; i < 4 && n; i++, n = n.parentElement) {
      for (const a of ['aria-selected', 'aria-checked', 'aria-pressed']) {
        if (n.getAttribute(a) === 'true') return true;
      }
      const cur = n.getAttribute('aria-current');
      if (cur && cur !== 'false') return true;
      if (n.tagName === 'LABEL' && n.querySelector('input:checked')) return true;
    }
    return false;
  }
  function inAnotherCard(e, el) {
    for (let n = e; n && n !== document.body; n = n.parentElement) {
      if (n.contains(el)) return false;
      if (holdsAnother(n, el)) return true;
    }
    return false;
  }
  function headingYear(el) {
    const all = Array.from(document.body.querySelectorAll('*'));
    for (let i = all.indexOf(el) - 1; i >= 0; i--) {
      const e = all[i];
      if (e.contains(el)) continue;
      if (e.tagName !== 'SELECT' && !e.getClientRects().length) continue;
      const text = labelOf(e);
      if (!text || text.length > 80) continue;
      if (!YEAR_HEADING.test(text) && !(isHeading(e) && !A_DATE.test(text))) continue;
      const y = yearIn(text);
      if (y === null) return '';
      if (!y) continue;
      if (inAnotherCard(e, el)) continue;
      if (isChoice(e) && !isChosen(e)) continue;
      return y;
    }
    return '';
  }
  function taxYearOf(el) {
    const card = cardOf(el);
    if (card) {
      const y = yearIn(textOf(card));
      if (y === null) return '';
      if (y) return y;
    }
    return headingYear(el);
  }
"""

_COLLECT_JS = r"""(readYears) => {""" + _PAGE_JS_LIB + r"""
  const out = [];
  const seen = new Set();
  for (const el of document.querySelectorAll("a[download], a, button, [role=button]")) {
    const own = ((el.innerText||'') + ' ' + (el.getAttribute('aria-label')||'')).trim();
    const hasDlAttr = el.hasAttribute('download');
    const isPdfBtn = /download\s*pdf/i.test(own);
    const isCsvBtn = /download\s*csv/i.test(own);
    let title = '', is_pdf = false;
    if (hasDlAttr && !isCsvBtn && TITLE_RE.test(own)) {
      // statement link: <a download> whose own text IS the title
      title = own; is_pdf = true;
    } else if (isPdfBtn) {
      // tax 'Download PDF' button: the title lives in an ancestor
      let node = el;
      for (let i = 0; i < 12 && node; i++) {
        node = node.parentElement;
        const m = ((node && node.innerText) || '').match(TITLE_RE);
        if (m) { title = m[1]; break; }
      }
      is_pdf = true;
    } else {
      continue;  // CSV buttons, plain title links, nav, etc.
    }
    title = title.replace(/\s+/g, ' ').replace(/\s*Download (PDF|CSV)\s*/gi, ' ').trim();
    if (!title || title.length < 4) continue;
    // On the tax page, a tax form whose name has no year is one document
    // per tax year it is shown under. Everything else, and everything on
    // any other page, is told apart by its title, as before. A reading that
    // fails leaves the form undated, never the page unread.
    let year = '';
    if (readYears && TAX_TITLE_RE.test(title) && !ANY_YEAR_RE.test(title)) {
      try { year = taxYearOf(el) || ''; } catch (e) { year = ''; }
    }
    const key = title.toLowerCase() + (year ? '|' + year : '');
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({title: title.slice(0, 160), is_pdf, year});
  }
  return out;
}"""

_YEAR_OF_JS = r"""el => {""" + _PAGE_JS_LIB + r"""
  return taxYearOf(el);
}"""

TAX_TITLE_RE = re.compile(r"\b(1099|1042-?S|5498)\b", re.I)


def tax_year_of(title: str, year, today=None) -> str:
    """The year the page showed beside a tax form, when the form's title
    carries none, or "".

    Only a year that has ended. A form for a year still running does not
    exist yet, so a year that has not ended is some other date's year, an
    issue date or the copyright line, and is never believed."""
    from datetime import date as _date
    year = str(year or "").strip()
    if not TAX_TITLE_RE.search(title or "") or not re.fullmatch(r"(19|20)\d{2}", year):
        return ""
    if int(year) >= (today or _date.today()).year:
        return ""
    return year


def collect_download_docs(page, tax_page: bool = False) -> List[RawDoc]:
    """Every downloadable PDF document on the current page (skips CSV-only
    items like the tax transactions export).

    `tax_page` is True only for the tax documents page, the one page where
    what surrounds a tax form is read for its year. A form a statements
    page lists is dated by its title alone, as it always was, because the
    years around it there are statement years."""
    docs: List[RawDoc] = []
    try:
        items = page.evaluate(_COLLECT_JS, bool(tax_page))
    except Exception:
        items = []
    for it in items:
        if not it.get("is_pdf"):
            continue
        title = _html.unescape(it.get("title", "")).strip()
        if not title:
            continue
        date_text, _ = parse_period_date(title)
        # A tax form whose own title names no date is filed at the end of
        # the tax year the page shows beside it, the way this app files
        # every tax form whose title does name its year.
        tax_year = "" if (date_text or not tax_page) else tax_year_of(title, it.get("year"))
        if tax_year:
            date_text = f"{tax_year}-12-31"
        docs.append(RawDoc(title=title[:200], date_text=date_text or "",
                           href="", text=title, kind="doc", tax_year=tax_year))
    # A title shown with a year and also without one is kept once, with the
    # year. Told apart by the title alone it was always one document, and the
    # undated one would press the first control of that title, whatever its
    # year, and save a second copy of it as 0000-00-00.
    dated = {d.title for d in docs if d.tax_year}
    return [d for d in docs if d.date_text or d.title not in dated]


def download_named(page, title: str, out_path, year: str = "") -> bool:
    """Click the download control for the document whose title matches, and
    capture the resulting download event to out_path.

    `year` is the tax year discovery read beside a form whose title has
    none. Forms of several years can share one title, so only a control the
    same reading places in that year is pressed, and no control at all is
    pressed when none is."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    needle = re.sub(r"\s+", " ", title).strip()[:30]

    # find the matching download control (its own text or an ancestor's holds
    # the title). Only follow controls that pass the safety guard for their
    # visible label (download/view) - never a forbidden one.
    control = None
    try:
        loc = page.locator("a[download], a, button, [role='button']")
        for i in range(min(loc.count(), 400)):
            el = loc.nth(i)
            try:
                own = (el.inner_text(timeout=400) or "") + " " + \
                    (el.get_attribute("aria-label") or "")
            except Exception:
                continue
            has_dl_attr = el.get_attribute("download") is not None
            if not (has_dl_attr or re.search(r"download", own, re.I)):
                continue
            if re.search(r"csv", own, re.I):
                continue
            if FORBIDDEN_CONTROL_RE.search(own) and not has_dl_attr:
                continue
            # match by own text or ancestor text containing the title
            hay = own
            if needle.lower() not in hay.lower():
                try:
                    hay = el.evaluate(
                        "el => { let n = el; for (let i=0;i<6 && n;i++){ n=n.parentElement;"
                        " if(n && (n.innerText||'').length>10) return n.innerText; } return ''; }")
                except Exception:
                    hay = ""
            if needle.lower() not in (hay or "").lower():
                continue
            if year:
                try:
                    shown = el.evaluate(_YEAR_OF_JS) or ""
                except Exception:
                    shown = ""
                if shown != year:
                    continue
            control = el
            break
    except Exception:
        pass
    if control is None:
        log.info("download control not found for %r%s", title,
                 f" of tax year {year}" if year else "")
        return False
    return _click_and_capture(page, control, title, out_path)


# Robinhood changed how a statement is served, some time between August and
# September 2026. The "Download PDF" control is now an <a href="#"> whose
# click handler calls
#     https://api.robinhood.com/documents/<id>/download/?redirect=false
# which answers with JSON, {"download_url": "https://mountain-storage.s3
# .amazonaws.com/...?response-content-type=application/pdf&..."}, a pre-signed
# link. The page then opens that link in a NEW TAB. No browser download event
# is ever fired, so a 45 second wait for one timed out on every new statement
# while the older ones skipped as already done, which is exactly how it looked
# in the panel.
#
# So both are watched. A download event, if Robinhood ever goes back to one,
# and that JSON response, from which the PDF is fetched directly. Any tab the
# site opens is closed again, because three of them were left behind per run.
#
# The pre-signed link points at Amazon S3, not robinhood.com, so it fails the
# app's own host check by design. It is allowed through a separate, narrower
# check that matches ONE exact host, the bucket Robinhood's own API names, and
# only for a URL that arrived inside that API's response. A wildcard on
# amazonaws.com would let any bucket anyone controls through.
DOCUMENT_STORE_HOSTS = {"mountain-storage.s3.amazonaws.com"}
_DOWNLOAD_API_RE = re.compile(r"^https://api\.robinhood\.com/documents/[^/]+/download/")


def is_document_store_url(url: str) -> bool:
    """True only for an https URL on the exact bucket host Robinhood's own
    API hands back. Exact equality, never a suffix, never a wildcard."""
    from urllib.parse import urlparse
    try:
        got = urlparse(url or "")
    except ValueError:
        return False
    if got.scheme != "https" or not got.hostname:
        return False
    if got.username or got.password:
        return False
    return got.hostname.lower().rstrip(".") in DOCUMENT_STORE_HOSTS


def _click_and_capture(page, control, title: str, out_path) -> bool:
    """Click a download control and take the PDF however Robinhood serves it."""
    import json as _json
    import time as _time
    from paperpull_core.receipt_pdf import save_download

    got = {"download": None, "response": None}
    popups = []

    def on_download(d):
        got["download"] = d

    def on_response(r):
        try:
            if r.status == 200 and _DOWNLOAD_API_RE.match(r.url):
                got["response"] = r
        except Exception:
            pass

    def on_page(p):
        # A plain function, not list.append. Playwright tags the handler it
        # is given with an attribute, and a bound builtin cannot carry one.
        popups.append(p)

    ctx = page.context
    page.on("download", on_download)
    page.on("response", on_response)
    ctx.on("page", on_page)
    try:
        control.click()
        deadline = _time.time() + 45
        while _time.time() < deadline and not (got["download"] or got["response"]):
            page.wait_for_timeout(250)
    except Exception as e:
        log.info("download click failed for %r: %s", title, e)
        return False
    finally:
        try:
            page.remove_listener("download", on_download)
            page.remove_listener("response", on_response)
            ctx.remove_listener("page", on_page)
        except Exception:
            pass
        # The site opens the PDF in a new tab. It is not the tab we work in
        # and it must not pile up.
        for p in popups:
            try:
                p.close()
            except Exception:
                pass

    if got["download"] is not None:
        try:
            save_download(got["download"], out_path)
            return True
        except Exception as e:
            log.info("saving the download for %r failed: %s", title, e)
            return False

    if got["response"] is None:
        log.info("no download event and no document response for %r within 45s",
                 title)
        return False

    try:
        body = _json.loads(got["response"].text() or "{}")
    except Exception as e:
        log.info("document response for %r was not JSON: %s", title, e)
        return False
    url = str((body or {}).get("download_url") or "")
    if not is_document_store_url(url):
        # The host only, never the link, which is signed. It is what says
        # whether a page serves its documents from another bucket, which a
        # statements page read for the first time might.
        from urllib.parse import urlparse
        try:
            host = urlparse(url).hostname or "none"
        except ValueError:
            host = "unreadable"
        log.error("refusing to fetch %r from an unexpected host (%s)", title, host)
        return False
    try:
        # page.request shares the browser's cookie jar and follows redirects.
        # The link is pre-signed so it needs neither, but this is the one
        # fetch path in Playwright that returns raw bytes without a download
        # event, which is the whole point.
        resp = page.request.get(url, timeout=60000)
        data = resp.body() if resp.ok else b""
    except Exception as e:
        log.info("fetching the PDF for %r failed: %s", title, e)
        return False
    if not data or b"%PDF-" not in data[:1024]:
        log.info("fetched %d bytes for %r but it is not a PDF", len(data), title)
        return False
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(data)
    return True


# ---------------------------------------------------------------------------
# Host allowlist. Added repo-wide after a review found this app would fetch or
# navigate to whatever URL a stored record or a page attribute contained, using
# the live signed-in session. Parsed, never a string prefix, so a lookalike
# host cannot walk through.
# ---------------------------------------------------------------------------
ALLOWED_HOSTS = {'robinhood.com'}


def is_safe_url(url: str) -> bool:
    """True only for an https URL on one of this provider's own hosts.

    The check itself lives in the core, so all of them answer the same way.
    This app keeps the hosts, which is the part that really is its own."""
    from paperpull_core.urls import is_safe_url as _host_allows
    return _host_allows(url, ALLOWED_HOSTS)
