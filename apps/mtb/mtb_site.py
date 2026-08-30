"""ALL M&T Bank selectors, URLs, and page behavior live here.

When M&T changes its site, repair this file only.

STATUS, read before trusting anything below.

  CONFIRMED from the public site, 2026-08-22:
    * the mortgage is serviced inside M&T's own online banking at
      onlinebanking.mtb.com, not a third-party subservicer. Sign-in starts
      at www.mtb.com/log-in and lands there.

  NOT YET CONFIRMED, and deliberately not guessed:
    * where mortgage statements and documents live once signed in
    * how a statement PDF is delivered (download event, blob tab, or a
      generated-report flow)

  There are NO guessed document URLs here. The AAFMAA app lost a day to four
  invented .aspx names and the Discover app once ended a live session on a
  logoff page the same way. goto_documents works from the page the user left
  open, and --diagnose records where every link points so the real routes get
  written in from evidence.

SAFETY (this is a BANK, and a mortgage can move real money):
  Strictly READ-ONLY. It opens the document/statement area, reads the list,
  and downloads PDFs M&T already generated. It must NEVER activate a control
  that pays the mortgage, sets up or edits autopay, moves money, transfers,
  sends a wire or Zelle, changes escrow, applies for anything, or changes a
  setting. A control must clear FORBIDDEN_CONTROL_RE *and* match
  SAFE_DOC_CONTROL_RE, and every URL requested must be on an M&T host. There
  is deliberately no code here that submits a form or confirms a dialog.

Documents are genuine PDF downloads, captured via the Playwright download
event -> download.save_as(), until diagnose shows otherwise.
"""
from __future__ import annotations

import base64
import html as _html
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

log = logging.getLogger("mtb_docs.site")

# Sign-in starts here and lands on onlinebanking.mtb.com. Both are M&T hosts.
BASE = "https://onlinebanking.mtb.com"
LOGIN_START = "https://www.mtb.com/log-in"
# Every host this app will talk to, and no others. is_safe_url() checks this
# exact set, parsed, so a request can only ever go to M&T.
ALLOWED_HOSTS = {"onlinebanking.mtb.com", "m.mtb.com", "www.mtb.com", "mtb.com"}

URLS = {
    "home": f"{BASE}/",
    "login": LOGIN_START,
}
# Empty on purpose: routes are written from diagnose evidence, not invented.
DOCUMENT_URL_CANDIDATES: list = []

LOGIN_URL_MARKERS = ["/logon", "/login", "/signin", "/auth", "/idp", "/mfa",
                     "/verify", "logon.mtb"]

# ---------------------------------------------------------------------------
# HARD SAFETY GUARD - never click anything matching this. Tuned for a bank.
# ---------------------------------------------------------------------------
# Word-stem note: an earlier version used \bchange\b, \bedit\b, \bupdate\b and
# bare "remove"/"apply". A review found the plurals and tenses walked straight
# through - "Save Changes", "Document Removal", "Loss Mitigation Application"
# all passed. Verb families are matched with their endings now, and anything
# that reads like a settings control is refused outright.
FORBIDDEN_CONTROL_RE = re.compile(
    r"(transfer|deposit|withdraw|wire\b|move\s+money|send\s+money|zelle|"
    r"pay\b|payment|pay\s+bills?|bill\s*pay|autopay|auto-?pay|schedul|"
    r"buy|sell|trade|place\s+order|rebalance|reallocate|"
    r"appl(y|ies|ied|ication)|open\s+\w*\s*account|get\s+(a\s+)?(quote|started|loan)|"
    r"add\s+funds|check\b|cash\s+a\s+check|mobile\s+deposit|external\s+account|"
    r"link\s+(bank|account)|add\s+(a\s+)?(bank|account)|"
    r"dispute|report\s+(a\s+)?(problem|fraud|lost|stolen)|lock\s+card|unlock\s+card|"
    r"activat|replace\s+card|order\s+checks|stop\s+payment|"
    # verb families, endings included
    r"\bchang(e|es|ed|ing)\b|\bedit(s|ed|ing)?\b|\bupdat(e|es|ed|ing)\b|"
    r"set\s+up|enabl|disabl|delet|remov(e|es|ed|ing|al)|"
    # anything that reads like a settings/preferences control
    r"\boptions?\b|\bsettings?\b|\bpreferences?\b|^\s*save\s*$|save\s+(changes?|settings?|preferences?|profile)|manage|"
    r"enroll|consent|opt\s*(in|out)|paperless|turn\s+(on|off)|"
    r"beneficiar|payee|contact\s+info|password|username|"
    r"file\s+a\s+claim|start\s+a\s+claim|renew|cancel|close\s+account|"
    r"escrow\s+(analysis\s+)?(change|adjust)|make\s+(a\s+)?payment|"
    r"pay\s+(my\s+)?(mortgage|loan|bill)|principal[\s-]*(only)?\s*payment|"
    r"recast|refinanc|forbear|modif|\bpayoff\b|loss\s+mitigation|defer|"
    r"skip\s+a?\s*payment|recurring|one[\s-]*time|"
    r"send\b|submit|confirm|continue|next|agree|accept|sign\b|authorize)", re.I)

# "save" was deliberately REMOVED from this allowlist and added to the
# blocklist above. On a portal that can move money a bare "Save" is far more
# likely to commit a settings change than to save a PDF, and the real document
# controls all say download / view / open / print / pdf.
SAFE_DOC_CONTROL_RE = re.compile(
    r"(download|view|open|print|pdf|statement|document|1099|1098|"
    r"declaration|policy|tax|e-?statement)", re.I)

SECURITY_CHALLENGE_MARKERS = [
    "enter the code we sent", "enter your verification code", "verification code",
    "one-time", "one time pin", "security code", "we sent a code",
    "two-factor", "two-step", "authenticator", "confirm your identity",
    "verify your identity", "we need to verify", "unusual activity",
    "are you a robot", "captcha", "unable to verify", "trouble verifying",
    "your session has expired", "please log on again",
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
                "[class*='DocumentRow'], [class*='statement-row'], "
                "[data-testid*='document'], li[class*='document']"),
    "doc_link": ("a[href*='.pdf'], a[href*='document'], a[href*='statement'], "
                 "a[download], button[class*='download']"),
    "download_control": "a[download], a[href$='.pdf'], button:has-text('Download')",
    "page_ready": ("table, [role='row'], [class*='document'], [class*='statement'], "
                   "main, [role='main']"),
    "account_select": "select, [role='combobox']",
    "next_page": ("a[aria-label*='Next' i], button[aria-label*='Next' i], "
                  ".pagination-next, [class*='next']"),
    "show_more": "button, a",
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
    """Date to file a document under, plus a human period label. Statements
    titled by period ("December 2025", "Q4 2025", "2025") file on the last
    day of that period."""
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
    """Conservative: if a document list rendered, it is a normal page."""
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
    """A control may be clicked only if it looks like a document action AND
    matches nothing in the forbidden list."""
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

def is_safe_url(url: str) -> bool:
    """On an M&T host, by parsed comparison, never a string prefix.

    A mortgage servicer can move money, so every URL this app fetches must be
    on M&T's own host. Parsed and allowlisted, so a suffix host
    (onlinebanking.mtb.com.evil.test) or a userinfo host
    (onlinebanking.mtb.com@evil.test) cannot walk through.
    """
    from urllib.parse import urlparse
    try:
        got = urlparse(url or "")
    except ValueError:
        return False
    if got.scheme != "https" or not got.hostname:
        return False
    if (got.hostname or "").lower() not in ALLOWED_HOSTS:
        return False
    if got.username or got.password:
        return False
    return True


def goto_documents(page) -> bool:
    """Deliberately does NOT navigate.

    M&T's statement list only appears after you select the account and click
    View, and this app never submits that form (see SECURITY.md). An earlier
    version navigated here and clicked a "Statements" nav link, which reloaded
    the page and WIPED the very list the user had created, so discovery always
    read zero. So this only confirms you are still signed in. The actual
    reading is collect_statement_rows, which scans every open tab and frame for
    the statements you listed and the tax page it can open itself.
    """
    return not looks_signed_out(page)


# NOTE: the Navy Federal scaffolding this app was cloned from once sat
# here - a table scraper, a documents-JSON listener, a blob-iframe
# capture, a deep-link downloader, and "show more"/"next page" clickers.
# None of it was reachable, all of it described a DIFFERENT bank's DOM
# (including a stale "verified" date), and four of those functions
# clicked page controls with no safety check at all. Dead code near a
# mortgage is a loaded gun, so it was removed rather than left to be
# revived by a future repair. M&T's real mechanism is below.

# ===========================================================================
# M&T document collection. CONFIRMED against a live account 2026-08-22.
#
# Two server-rendered pages, both with real download URLs (no SPA, no blob):
#   Statements: onlinebanking.mtb.com/Statements/StatementsAndNotices
#     rows are <a href="/Statements/FetchStatementandNotices?t=<TYPE>&a=..&
#     dt=MM/DD/YYYY&stmtId=..">. t=MTGSTMT is a mortgage statement, t=YESTMT a
#     year-end statement.
#   Tax:        m.mtb.com/TaxDocuments/TaxDocumentCenter
#     rows are <a href="/TaxDocuments/FetchTaxDocument?documentkey=..">, the
#     1098 mortgage-interest statements.
#
# A document is identified by its own href. Downloading is a plain GET of that
# href with the session cookie, host-checked first. The ONLY thing ever clicked
# is a collapsed year section, and that click is guarded like any other.
# ===========================================================================
STATEMENTS_URL = f"{BASE}/Statements/StatementsAndNotices"
TAX_URL = "https://m.mtb.com/TaxDocuments/TaxDocumentCenter"

_STMT_TYPE = {"MTGSTMT": "Mortgage Statement", "YESTMT": "Year-End Statement"}

# The two document endpoints, matched against the URL's PATH, never as a
# substring of the whole URL. A review showed the old substring test accepted
# /Payments/SchedulePayment?FetchStatementandNotices=1&dt=... - an on-host URL
# that passes the host allowlist and would then be fetched with the live
# session cookie. Matching the path closes that.
_STMT_PATH = "/statements/fetchstatementandnotices"
_TAX_PATH = "/taxdocuments/fetchtaxdocument"

_COLLECT_JS = r"""() => [...document.querySelectorAll('a')]
    .map(a => ({label:(a.innerText||'').replace(/\s+/g,' ').trim(),
                href:a.getAttribute('href')||''}))
    .filter(x => /FetchStatementandNotices|FetchTaxDocument/i.test(x.href))"""


def _abs(href: str) -> str:
    href = href or ""
    if not href.strip():
        return ""
    if href.startswith("http"):
        return href
    # tax links are relative to m.mtb.com, statement links to onlinebanking
    base = "https://m.mtb.com" if "/TaxDocument" in href else BASE
    return base + href


def _endpoint_of(url: str) -> Optional[str]:
    """Return "statement" or "tax" only if the URL's PATH really is one of the
    two document endpoints on an M&T host. Anything else returns None and is
    refused, so a crafted query string cannot smuggle another route through."""
    if not is_safe_url(url):
        return None
    from urllib.parse import urlparse
    try:
        path = (urlparse(url).path or "").lower().rstrip("/")
    except ValueError:
        return None
    if path == _STMT_PATH:
        return "statement"
    if path == _TAX_PATH:
        return "tax"
    return None


def is_mt_frame(frame) -> bool:
    """True only for a frame actually loaded from an M&T host.

    The collector walks every frame of every tab in the attached browser, which
    is the user's ordinary Chrome. Without this, it would read links from - and
    click inside - whatever unrelated sites happen to be open.
    """
    try:
        url = frame.url or ""
    except Exception:
        return False
    if not url.startswith("https://"):
        return False
    from urllib.parse import urlparse
    try:
        return (urlparse(url).hostname or "").lower() in ALLOWED_HOSTS
    except ValueError:
        return False


def _date_from_stmt_href(href: str, label: str) -> str:
    m = re.search(r"[?&]dt=(\d{1,2})/(\d{1,2})/(\d{4})", href)
    if m:
        mo, dy, yr = (int(x) for x in m.groups())
        if 1 <= mo <= 12 and 1 <= dy <= 31:
            return f"{yr:04d}-{mo:02d}-{dy:02d}"
    d = parse_date(label) or ""
    if d:
        return d
    dd, _ = parse_period_date(label)
    return dd or ""


def _doc_id(href: str) -> str:
    """A stable identity from the href: the stmtId or documentkey token. Two
    statements in one month, or two 1098s, differ here even when their titles
    and dates match, so neither collapses into one record."""
    m = re.search(r"[?&](?:stmtId|documentkey)=([^&]+)", href, re.I)
    return m.group(1)[:60] if m else href[-60:]


_TAX_ROWS_JS = r"""() => {
  const out = [];
  for (const tr of document.querySelectorAll('tr')) {
    const a = tr.querySelector('a[href*="FetchTaxDocument"]');
    if (!a) continue;
    const text = (tr.innerText || '').replace(/\s+/g, ' ').trim();
    const ym = text.match(/(20\d{2})/);
    out.push({href: a.getAttribute('href') || '', text: text.slice(0, 200),
              year: ym ? ym[1] : ''});
  }
  return out;
}"""


# The collapsed-year expander. Read its label first, click only if the label
# clears the blocklist, then re-count. Kept as three tiny reads so the click is
# a separate, guarded step rather than something buried in a bigger script.
_OPEN_TABLE_COUNT_JS = r"""() => document.querySelectorAll('span.open-table').length"""
_OPEN_TABLE_LABEL_JS = r"""() => {
  const s = document.querySelector('span.open-table');
  if (!s) return '';
  const h = s.closest('h2') || s.parentElement;
  return ((h ? h.innerText : s.innerText) || '').replace(/\s+/g, ' ').trim();
}"""
_OPEN_TABLE_CLICK_JS = r"""() => {
  const s = document.querySelector('span.open-table');
  if (!s) return false;
  s.click();
  return true;
}"""


def _tax_year(row_text: str, fallback: str) -> str:
    """The tax year of a 1098 row.

    Full dates are removed first. A row like "Available 01/15/2026 ... 1098 for
    2025" was previously read as 2026 - the availability date, not the tax
    year - which mis-titled and mis-dated the form. The bare year that is not
    part of a date is the tax year.
    """
    stripped = re.sub(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b", " ", row_text or "")
    m = re.search(r"\b(19|20)\d{2}\b", stripped)
    return m.group(0) if m else fallback


def collect_statement_rows(page) -> List[dict]:
    """Every statement and tax document, from both pages, newest first.

    Returns dicts {title, date, account, href, doc_id}. The orchestrator records
    the href as the document's identity and downloads it with a host-checked
    GET. Only frames served by M&T are read.
    """
    rows: List[dict] = []
    seen = set()

    def harvest_statement_links(links):
        added = 0
        for a in links:
            href = a.get("href") or ""
            if not href or href in seen:
                continue
            full = _abs(href)
            # Judge the PATH, not a substring of the URL. This is what stops a
            # crafted on-host link (a payment route carrying the endpoint name
            # as a query parameter) from being queued as a "statement".
            if _endpoint_of(full) != "statement":
                continue
            label = re.sub(r"\s+", " ", a.get("label") or "").strip()
            m = re.search(r"[?&]t=([A-Z]+)", href)
            # An unrecognised t= is NOT assumed to be a mortgage statement. The
            # page also offers notices and analysis statements; labelling one of
            # those "Mortgage Statement" would file it under a name that is
            # simply untrue. Unknown types keep the row's own text and land in
            # Other Documents, where they are visible rather than disguised.
            kind = m.group(1) if m else ""
            title = _STMT_TYPE.get(kind) or (label or f"M&T Document ({kind or 'unknown'})")
            seen.add(href)
            rows.append({"title": title, "date": _date_from_stmt_href(href, label),
                         "account": "", "href": full, "doc_id": _doc_id(full)})
            added += 1
        return added

    # STATEMENTS. The list only renders after you pick the account and click
    # View, and this app does not submit that form (see SECURITY.md). So you
    # list it and the app reads it - but the listed view is transient and the
    # tab it lives in is not predictable, so scan every tab. ONLY frames served
    # by M&T are touched: this is the user's ordinary browser, and reading links
    # out of (or clicking inside) unrelated sites would be indefensible.
    found_statements = 0
    try:
        pages = [p for p in page.context.pages if not p.is_closed()]
    except Exception:
        pages = [page]
    mt_frames = []
    for pg in pages:
        try:
            mt_frames.extend([fr for fr in pg.frames if is_mt_frame(fr)])
        except Exception:
            continue
    for fr in mt_frames:
        # The statements page shows one collapsed section PER YEAR, and only the
        # current year is open by default. Each collapsed year is a
        # <span class="open-table"> whose click fires a FetchYearlyStatements
        # GET that lists that year - a read, not a form submit. Expand them all
        # or five-plus years are silently missed (they were, until a user
        # noticed). The click is guarded like any other control, and the loop
        # stops the moment the count stops falling, so a span whose class never
        # flips is clicked once, not fifteen times.
        try:
            remaining = fr.evaluate(_OPEN_TABLE_COUNT_JS)
            for _ in range(20):
                if not remaining:
                    break
                label = fr.evaluate(_OPEN_TABLE_LABEL_JS) or ""
                if FORBIDDEN_CONTROL_RE.search(label):
                    log.warning("refusing to expand a section labelled %r", label[:40])
                    break
                if not fr.evaluate(_OPEN_TABLE_CLICK_JS):
                    break
                fr.wait_for_timeout(1200)
                now = fr.evaluate(_OPEN_TABLE_COUNT_JS)
                if now >= remaining:
                    log.warning("a year section did not open (%d left); reading "
                                "what is on screen. Expand the years yourself "
                                "and re-run if statements look short.", now)
                    break
                remaining = now
        except Exception as e:
            log.info("year expansion stopped: %s", str(e).splitlines()[0][:80])
        # Harvest regardless of whether expansion worked, so a failed expand
        # still yields the years already on screen.
        try:
            found_statements += harvest_statement_links(fr.evaluate(_COLLECT_JS) or [])
        except Exception as e:
            log.info("could not read links from a frame: %s",
                     str(e).splitlines()[0][:80])
    if found_statements == 0:
        log.warning("No statements found in any open tab. On the Statements and "
                    "Notices page, pick your account and click View so they "
                    "show, LEAVE that tab open, then re-run.")

    # TAX documents auto-list on their own page (a plain GET). Read them by
    # table ROW, not by bare anchor: the tax YEAR sits in a separate cell from
    # the link, and a row can carry more than one link, so anchor-only
    # collection loses the year and double-counts. One record per row.
    # Read the tax page the same way as statements: from an open tab, not by
    # navigating (which would hijack the statements tab). If the Tax Documents
    # page is open in any tab, its 1098s are collected; if not, they are simply
    # skipped with a hint, and statements still come through.
    found_tax = 0
    for fr in mt_frames:
        try:
            tax_rows = fr.evaluate(_TAX_ROWS_JS) or []
        except Exception:
            continue
        for r in tax_rows:
            href = r.get("href") or ""
            if not href or href in seen:
                continue
            full = _abs(href)
            if _endpoint_of(full) != "tax":
                continue
            seen.add(href)
            year = _tax_year(r.get("text") or "", r.get("year") or "")
            title = "1098 Mortgage Interest Statement"
            rows.append({
                "title": f"{year} {title}".strip() if year else title,
                "date": f"{year}-12-31" if year else "",
                "account": "", "href": full, "doc_id": _doc_id(full)})
            found_tax += 1
    if found_tax == 0:
        log.info("No tax documents found in an open tab. To include 1098s, open "
                 "the Tax Documents page (Statements > View Tax Documents) and "
                 "re-run.")

    rows.sort(key=lambda r: r["date"] or "", reverse=True)
    log.info("M&T: %d document(s) collected", len(rows))
    return rows


def ensure_statements(page) -> bool:
    """Only confirms you are still signed in, and never navigates.

    Download does not need the statements page at all: it GETs each document's
    own href (host-checked). Navigating here would reload and wipe the listed
    statements, so this leaves the page exactly as you left it.
    """
    return not looks_signed_out(page)


class SessionExpired(Exception):
    """The server answered a document request with a sign-in page."""


def _looks_like_login_html(body: bytes) -> bool:
    """A sign-in page returned where a PDF was expected.

    M&T answers an expired session with HTTP 200 and an HTML login page, not an
    error. Without this the caller files every remaining document as "manual
    review" and the run ends looking successful while having saved nothing.
    """
    head = body[:4000].lower()
    if b"<html" not in head and b"<!doctype" not in head:
        return False
    return any(m in head for m in (
        b"type=\"password\"", b"type='password'", b"sign on", b"sign in",
        b"log in", b"log on", b"session has expired", b"please log on"))


def download_statement(page, href: str, out_path) -> bool:
    """Save one document's PDF by a host-checked GET of its own href.

    href is the identity captured at discovery. It is re-checked here - both
    that the host is M&T's and that the PATH really is a document endpoint - so
    a stored or tampered value cannot send the session cookie somewhere else.
    Raises SessionExpired if the server hands back a sign-in page.
    """
    from pathlib import Path
    url = _abs(href)
    if _endpoint_of(url) is None:
        log.error("refusing a URL that is not an M&T document endpoint")
        return False
    # Redirects are capped and the FINAL url is re-checked: "every URL this app
    # requests is on an M&T host" has to hold for every hop, not just the first.
    # Exceeding the cap RAISES rather than returning a response, and an expired
    # session is exactly what produces a long redirect chain here (M&T bounces
    # a document request towards sign-in), so that is reported as an expired
    # session rather than as an unexplained failure.
    try:
        resp = page.context.request.get(url, max_redirects=3)
    except Exception as e:
        if "redirect" in str(e).lower():
            raise SessionExpired(
                "M&T redirected the document request, which means the "
                "signed-in session is no longer valid") from None
        log.warning("fetch failed: %s", str(e).splitlines()[0][:100])
        return False
    final = getattr(resp, "url", url) or url
    if not is_safe_url(final):
        log.error("refusing a redirect that left M&T's hosts")
        return False
    if not resp.ok:
        log.warning("fetch returned %s", resp.status)
        return False
    body = resp.body()
    if not body.startswith(b"%PDF"):
        if _looks_like_login_html(body):
            raise SessionExpired(
                "M&T returned a sign-in page instead of a document")
        log.warning("response was not a PDF (%d bytes)", len(body))
        return False
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(body)
    return True
