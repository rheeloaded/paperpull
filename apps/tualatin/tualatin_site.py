"""ALL tualatin.merchanttransact.com selectors, URLs, and page behavior live here.

When Tualatin Water's billing portal, CivicPay Online, changes, repair
this file only.

STATUS: built 2026-10-29 from a signed-in survey of a real account, with
nothing pressed by the app.

SEEN SIGNED IN, 2026-10-29 (shapes only, no values kept):

  * Tualatin Water's utility bills (water, sewer, stormwater, parks and
    road fees) are on CivicPay Online at
    https://tualatin.merchanttransact.com/. Its session is a cookie, so a
    page is opened by its address.
  * /secure/Activity draws one table headed Transaction Date | Transaction
    Type | Description | Amount | Balance, a row per transaction, Billing
    and Payment alike (48 rows seen, 24 bills, no pager or count). A
    Billing row links to its bill, /secure/MyBill/<bill number>.
  * A bill's Print My Bill link, /secure/MyBill/<bill number>/Print, is an
    HTML page, not a PDF: the printed bill, with Bill Details, Billing Date,
    Due Date, the charges, Total Amount Due and the meter readings. It
    carries no bill number in its text; its Billing Date was each bill's
    Transaction Date on Activity.
  * So a run reads Activity, fetches each bill's print page from inside the
    signed-in page with its stylesheets and images from the portal host
    written into it, and draws it as a PDF with every script, frame and
    form taken out, offline (paperpull_core.receipt_pdf.print_html_inert_to_pdf).
    Drawn without its stylesheet, the page lost the look of the bill. Nothing
    is clicked. A bill is known by its bill number.
  * What is written into the page counts against one budget: the page,
    each stylesheet as written in and each image as its data address.
    Each answer is read through the core's bounded reader, and one that
    does not fit is left out and noted in the trace.

Sign-in is the account holder's own, in the browser.

SAFETY (a payment portal that can pay, schedule and enroll):
  This module is strictly READ-ONLY. It presses nothing, fills nothing and
  submits nothing. It must NEVER activate any control that pays, schedules
  or cancels a payment, sets up autopay, adds a bank account or card,
  enrolls in paperless, exports, changes the account, or signs out.
  FORBIDDEN_CONTROL_RE is the guard; a control must ALSO match one of the
  anchored document actions (SAFE_DOC_CONTROL_RES), and the shared core
  guards are consulted every time.
"""
from __future__ import annotations

import logging
import re
import sys
from dataclasses import dataclass
from datetime import date as _date
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import urlsplit

from paperpull_core import intake
from paperpull_core import pdf_reader
from paperpull_core.controls import SETTINGS_CONTROL_RE, AUTH_CONTROL_RE
from paperpull_core.redact import private_words, redact, set_private_words  # noqa: F401  (re-exported)
from paperpull_core.urls import is_safe_url as _host_allows
from paperpull_core.dates import last_day as _last_day
from paperpull_core.dates import checked as _checked_date
from paperpull_core.dates import full_year as _full_year
from paperpull_core.words import shape as _shape
from paperpull_core.words import words_for as _words_for

log = logging.getLogger("tualatin_docs.site")


def _words():
    """This app's own words for paperpull_core.words."""
    return _words_for("Tualatin Water", sys.modules[__name__])


# ---------------------------------------------------------------------------
# Addresses
# ---------------------------------------------------------------------------
PORTAL_HOST = "tualatin.merchanttransact.com"
BASE = f"https://{PORTAL_HOST}"
DOCUMENTS_PATH = "/secure/Activity"
DOCUMENTS_URL = BASE + DOCUMENTS_PATH
DOWNLOAD_PATH = "/secure/MyBill"
STATEMENTS_URL = DOCUMENTS_URL
BILLING_URL = DOCUMENTS_URL
URLS = {
    "home": f"{BASE}/",
    "login": f"{BASE}/",
    "documents": DOCUMENTS_URL,
    "statements": DOCUMENTS_URL,
}

LOGIN_URL_MARKERS = ["/login", "loginredirect", "/account/signin", "/signin", "logout"]

# ---------------------------------------------------------------------------
# HARD SAFETY GUARD. Tuned for a utility portal. Every stem anchored so
# "Bill" is not "billing plan" and "Download" is not "load".
# ---------------------------------------------------------------------------
FORBIDDEN_CONTROL_RE = re.compile(
    r"(\bpay\b|\bpaying\b|\bpayments?\b|\bpay\s*now\b|\bautopay\b|\bauto\s*-?\s*pay\b|\btext\s+to\s+pay\b|"
    r"\bguest\s+pay\b|\bbank|\barrangements?\b|\blevel\s+pay\b|\bbudget\s+billing\b|\bpricing\s+plans?\b|"
    r"\brate\s+plans?\b|\bbilling\s+plans?\b|\bchange\s+plan\b|\bpaperless\b|\benroll|\bunenroll|\bsign\s*up\b|"
    r"\bregist(er|ration)\b|\bstart\s+service\b|\bstop\s+service\b|\bmove\s+service\b|\bmove\s*-?\s*(in|out)\b|"
    r"\btransfer|\bnotifications?\b|\bsign\s*(out|off)\b|\blog\s*(out|off)\b|\blogout\b|\bletters?\b|"
    r"\bexcel\b|\bexport\b|\bcsv\b|\bhistory\b|\bextension\b|\bwallet\b|\bschedul(e|es|ed|ing)\b|\bdonat|"
    r"\bprograms?\b|\bprofile\b|\bsettings?\b|\bpreferences?\b|\bsave\b|\bsubmit\b|\bconfirm\b|\bcontinue\b|"
    r"\bdelet(e|es|ed|ing)\b|\bremov(e|es|ed|ing|al)\b|\bcancel\b|\bedit(s|ed|ing)?\b|\bupdat(e|es|ed|ing)\b|"
    r"\bchang(e|es|ed|ing)\b|\bmanage\b|\bturn\s+(on|off)\b|\bopt\s*-?\s*(in|out)\b|\bclose\b|\bupload\b|"
    r"\bemail\b|\bshare\b|\bchat\b|\bcontact\b|\brequest(s|ed|ing)?\b|\boutages?\b|\bbuy\b|\bsell\b|\border\b|"
    r"\bdeposit|\bwithdraw|\bagree\b|\baccept\b|\bauthori[sz]e\b|\bverify\b|\bpassword\b|\busername\b|"
    r"\bmy\s+wallet\b|\bpaperless\b|\bexcel\b|\bcsv\b|\bexport\b|"
    r"\brebalance\b|\bliquidate\b|\bdetails\b)", re.I)

# The document actions this app would ever accept, anchored whole: the
# portal's own "View Your Detailed Bill PDF", "Download Your Solar Bill" and
# "View Bill", and the "View Utility Bill" its rules name. Nothing looser,
# so a label carrying anything more is refused.
# The links that lead to a bill. This app presses none of them; they are
# named here for the survey's verdicts.
SAFE_DOC_CONTROL_RES = (
    re.compile(r"^billing$", re.I),
    re.compile(r"^print\s+my\s+bill$", re.I),
    re.compile(r"^(view|download)\s+(your\s+)?(detailed\s+)?(utility\s+|water\s+)?bill(\s+\(?pdf\)?)?$", re.I),
)

BILL_CONTROL_RE = re.compile(r"^\s*(billing|print\s+my\s+bill)\s*$", re.I)

SECURITY_CHALLENGE_MARKERS = [
    "enter the code", "verification code", "6-digit", "7-digit", "two-factor",
    "two-step", "authenticator", "confirm your identity", "verify your identity",
    "we sent a code", "device approval", "approve this login",
    "are you a robot", "captcha", "let's verify", "check your email",
    "check your phone", "your session has expired", "log back in",
    "access denied",
]

RATE_LIMIT_MARKERS = [
    "too many requests", "rate limit", "try again later",
    "temporarily unavailable", "http error 429", "unusual traffic",
]

# A bill's row on Billing History, and the table plugin's own cell for a
# table with no rows.
# For Diagnose's counts only: the bill rows the portal draws.
BILL_ROW = "table tbody tr"

FALLBACK = {
    "doc_row": BILL_ROW,
    "page_ready": "table",
}

DATE_PATTERNS = [
    (re.compile(r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
                r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|"
                r"Dec(?:ember)?)\.?\s+(\d{1,2}),?\s+(\d{4})", re.I), "mdY"),
    (re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b"), "mdy_slash"),
    (re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{2})\b"), "mdy_slash2"),
    (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})(?!\d)"), "iso"),
]
_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
MONTH_YEAR_RE = re.compile(
    r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
    r"Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    r"\s+(\d{4})", re.I)
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
            if kind == "mdy_slash2":
                return f"{_full_year(m.group(3)):04d}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
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
    m = YEAR_RE.search(text)
    if m:
        year = int(m.group(1) + m.group(2))
        return f"{year:04d}-12-31", str(year)
    return None, ""


# ---------------------------------------------------------------------------
# Session / safety
# ---------------------------------------------------------------------------

class SessionExpired(Exception):
    """CivicPay Online answered as a signed-out session: its sign-in page,
    a redirect where a bill was asked for, a 401 or 403, or a print page
    asking for a password. The run stops for the account holder."""


def looks_signed_out(page) -> bool:
    """The sign-in page by its address or a password field. A page whose
    address cannot be read raises, and is never called signed in."""
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
    """Names the passcode, CAPTCHA or throttling prompt on screen, or None.
    Visible text only. A page that shows a bill row is not a challenge,
    whatever its text says further down."""
    try:
        if page.get_by_role("link", name=BILL_CONTROL_RE).count() > 0:
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
    """Deny by default: an unreadable label is refused, then this app's
    blocklist, then the shared core guards, and only then the anchored
    document actions."""
    name = re.sub(r"\s+", " ", name or "").strip()
    if not name:
        return False
    if FORBIDDEN_CONTROL_RE.search(name):
        return False
    if SETTINGS_CONTROL_RE.search(name) or AUTH_CONTROL_RE.search(name):
        return False
    return any(rx.match(name) for rx in SAFE_DOC_CONTROL_RES)


# ---------------------------------------------------------------------------
# Hosts. Exact, parsed, no subdomain wildcard.
# ---------------------------------------------------------------------------
ALLOWED_HOSTS = {PORTAL_HOST}
BILL_NUMBER_RE = re.compile(r"[0-9]{5,12}")
_BILL_PATH_RE = re.compile(r"/secure/MyBill/([0-9]{5,12})")
_PRINT_PATH_RE = re.compile(r"/secure/MyBill/([0-9]{5,12})/Print")
_ROW_DATE_RE = re.compile(r"([0-9]{1,2})/([0-9]{1,2})/([0-9]{4})")
# Words every printed bill carries, read off the page as fetched, before
# anything is written into it, and again off the PDF drawn from it.
PRINT_MARKERS = ("Bill Details", "Billing Date", "Total Amount Due")
_BILLING_DATE_RE = re.compile(r"Billing Date\s*:?\s*([0-9]{1,2})/([0-9]{1,2})/([0-9]{4})", re.I)
# The row types Activity holds. A bill is a document and a payment is not;
# any other type stops the list, so an adjustment or a final bill under a
# type of its own is named where the run prints why it stopped, through the
# app's words so a name in it is never printed, rather than passed over.
BILL_TYPE = "Billing"
KNOWN_TYPES = frozenset({BILL_TYPE, "Payment"})
_TYPE_WORD_RE = re.compile(r"[A-Za-z][A-Za-z /]{0,29}")
MAX_PAGE_BYTES = 5 * 1024 * 1024
# How long one fetch of a print page, a stylesheet or an image may take.
FETCH_MS = 30000


def is_safe_url(url: str) -> bool:
    """True only for an https URL on exactly tualatin.merchanttransact.com."""
    return _host_allows(url, ALLOWED_HOSTS, subdomains=False)


def bill_path(number: str) -> str:
    """A bill's own page, or "" when the number is not one."""
    return f"/secure/MyBill/{number}" if BILL_NUMBER_RE.fullmatch(number or "") else ""


def print_url(number: str) -> str:
    """A bill's print page, the one its Print My Bill link opens."""
    path = bill_path(number)
    url = f"{BASE}{path}/Print" if path else ""
    return url if is_download_url(url) else ""


def is_download_url(url: str) -> bool:
    """True only for a bill's print page on the portal's own host."""
    if not is_safe_url(url):
        return False
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    return bool(_PRINT_PATH_RE.fullmatch(parts.path)) and not parts.query and not parts.fragment


@dataclass
class RawDoc:
    title: str
    account: str = ""
    date_text: str = ""
    href: str = ""
    text: str = ""
    row_index: int = -1
    kind: str = "doc"
    document_id: str = ""


class ListStopped(Exception):
    """The list has a part this could not read, so what was read is not all
    of it. `docs` holds what was read before it stopped."""

    def __init__(self, why: str, docs=None):
        super().__init__(why)
        self.docs = list(docs or [])


def _settled_here(page) -> bool:
    url = page.url or ""
    try:
        return is_safe_url(url) and urlsplit(url).path.rstrip("/") == DOCUMENTS_PATH
    except ValueError:
        return False


_ROWS_JS = r"""() => {
  const text = (el) => (el ? el.textContent : '').replace(/\s+/g, ' ').trim();
  let table = null, heads = [], tables = 0;
  for (const t of document.querySelectorAll('table')) {
    const h = [...t.querySelectorAll('th')].map(text);
    if (h.some(x => /^transaction date$/i.test(x))) { tables++; if (!table) { table = t; heads = h; } }
  }
  const account = [...document.querySelectorAll('h1,h2,h3,h4')].map(text).filter(s => /[0-9]/.test(s));
  if (!table) return {table: false, account: account};
  const rows = [...table.querySelectorAll('tbody tr')].map(tr => ({
    cells: [...tr.cells].map(text),
    bills: [...tr.querySelectorAll('a[href]')].map(a => a.getAttribute('href')).filter(h => /\/secure\/MyBill\//.test(h))
  }));
  // What would say the table is not every transaction: a pager offering
  // another page or a control loading more, a count of its own or a
  // filtered view, a date filter, a choice of accounts or service
  // locations, or a second transaction table.
  const off = (el) => el.hasAttribute('disabled') || el.getAttribute('aria-disabled') === 'true'
    || /\bdisabled\b/.test(el.className || '') || /\bdisabled\b/.test((el.parentElement || {}).className || '');
  let pager = false;
  const onward = (t) => /^(next|more|older)\b/i.test(t) || /^[>›»]+$/.test(t);
  for (const box of document.querySelectorAll('.pagination, .pager, .dataTables_paginate, .dt-paging, [class*="paginat"], [class*="paging"], nav[aria-label*="pag" i]')) {
    for (const el of box.querySelectorAll('a, button')) {
      const t = text(el);
      if (!off(el) && (onward(t) || (/^[0-9]+$/.test(t) && +t > 1))) pager = true;
    }
  }
  for (const el of document.querySelectorAll('a, button, input[type="button"], input[type="submit"]')) {
    if (!off(el) && /^(load|show|view|see)\s+(more|all|older)\b/i.test(text(el) || el.value || '')) pager = true;
  }
  // innerText keeps the line breaks textContent runs together, so
  // "$100.00" and "Page 1 of 3" never read as one word.
  const all = (document.body ? document.body.innerText : '').replace(/\s+/g, ' ');
  let count = null, m;
  if ((m = all.match(/showing\s+([0-9]+)\s*(?:to|-|–)\s*([0-9]+)\s+of\s+([0-9]+)/i))) count = +m[3];
  if ((m = all.match(/page\s+([0-9]+)\s+of\s+([0-9]+)/i)) && +m[2] > 1) pager = true;
  const filtered = /filtered\s+from\s+[0-9,]+/i.test(all);
  const named = (el) => [el.name, el.id, el.getAttribute('aria-label'), el.getAttribute('placeholder'),
                         ...[...(el.labels || [])].map(text)].join(' ');
  const fields = [...document.querySelectorAll('input, select')].filter(el => el.type !== 'hidden');
  const dated = fields.some(el => el.type === 'date' || el.type === 'month'
    || /\b(date|from|to|start|end|period|range|year|month|days)\b/i.test(named(el).replace(/([a-z])([A-Z])/g, '$1 $2')));
  const accounts = fields.filter(el => el.tagName === 'SELECT'
      && /account|location|service|address|premise|property|meter/i.test(named(el)))
    .reduce((n, el) => Math.max(n, el.options.length), 0);
  return {table: true, heads: heads, rows: rows, account: account, pager: pager, count: count,
          dated: dated, accounts: accounts, filtered: filtered, tables: tables};
}"""

# How many rows the Activity table has drawn so far.
_ROW_COUNT_JS = r"""() => [...document.querySelectorAll('table')].filter(t =>
  [...t.querySelectorAll('th')].some(th => /^\s*transaction date\s*$/i.test(th.textContent || '')))
  .reduce((n, t) => n + t.querySelectorAll('tbody tr').length, 0)"""
SETTLE_MS = 1000
SETTLE_ROUNDS = 10

# Whether the Activity table itself has drawn its rows, not any table.
_TABLE_DRAWN_JS = r"""() => [...document.querySelectorAll('table')].some(t =>
  [...t.querySelectorAll('th')].some(th => /^\s*transaction date\s*$/i.test(th.textContent || ''))
  && t.querySelector('tbody tr'))"""


def _open(page, timeout_ms: int = 30000) -> dict:
    """Open Activity by its address, the portal keeping its session in a
    cookie, and read its transaction table as drawn. Raises SessionExpired
    when the portal shows its sign-in page and ListStopped when the table
    never draws. Nothing is pressed."""
    try:
        page.goto(DOCUMENTS_URL, wait_until="domcontentloaded", timeout=60000)
    except Exception as e:
        log.info("opening Activity failed (%s)", type(e).__name__)
    if looks_signed_out(page):
        raise SessionExpired("the payment portal showed its sign-in page")
    if not _settled_here(page):
        raise SessionExpired("the payment portal sent Activity somewhere else")
    try:
        page.wait_for_function(_TABLE_DRAWN_JS, timeout=timeout_ms)
    except Exception:
        if looks_signed_out(page):
            raise SessionExpired("the payment portal showed its sign-in page")
        raise ListStopped("the Activity table did not finish loading")
    # Rows drawn one at a time after the first are waited for: the table
    # is read once its row count has held for a moment.
    before = None
    for _ in range(SETTLE_ROUNDS):
        try:
            now = page.evaluate(_ROW_COUNT_JS)
        except Exception:
            now = None
        if now == before:
            break
        before = now
        page.wait_for_timeout(SETTLE_MS)
    else:
        raise ListStopped("the Activity table was still drawing rows")
    try:
        seen = page.evaluate(_ROWS_JS) or {}
    except Exception as e:
        raise ListStopped(f"the Activity table could not be read ({type(e).__name__})")
    if not seen.get("table"):
        raise ListStopped("Activity shows no transaction table")
    _keep_private(seen.get("account"))
    return seen


def _whole(seen: dict) -> None:
    """Stop the list when Activity shows anything saying its table is not
    every transaction. None of it was seen on 2026-10-29."""
    if seen.get("pager"):
        raise ListStopped("Activity shows a pager, and this app reads one page")
    if seen.get("filtered"):
        raise ListStopped("Activity shows a filtered view, so its table may not hold every transaction")
    tables = seen.get("tables")
    if isinstance(tables, int) and tables > 1:
        raise ListStopped("Activity shows more than one transaction table, and this app reads one")
    if seen.get("dated"):
        raise ListStopped("Activity shows a date filter, so its table may not hold every transaction")
    accounts = seen.get("accounts")
    if isinstance(accounts, int) and accounts > 1:
        raise ListStopped("Activity offers a choice of accounts or service locations, and this app reads one")
    count = seen.get("count")
    drawn = sum(1 for r in seen.get("rows") or [] if any((r or {}).get("cells") or []))
    if isinstance(count, int) and not isinstance(count, bool) and count != drawn:
        raise ListStopped(f"Activity says it holds {count} transactions and {drawn} were read")


def _keep_private(words) -> None:
    """Register the account number Activity shows as a private word."""
    parts = set()
    for w in words or []:
        for part in re.split(r"[\s,.#/]+", str(w or "")):
            if re.search(r"[0-9]", part):
                parts.add(part)
                parts.update(p for p in part.split("-") if re.search(r"[0-9]", p))
    if parts - set(private_words()):
        set_private_words(private_words() + sorted(parts - set(private_words())))


def row_day(text) -> Optional[str]:
    """A Transaction Date cell, "09/30/2026", as YYYY-MM-DD, or None when
    the whole cell is not a calendar date."""
    m = _ROW_DATE_RE.fullmatch(str(text or "").strip())
    if not m:
        return None
    try:
        return _date(int(m.group(3)), int(m.group(1)), int(m.group(2))).isoformat()
    except ValueError:
        return None


def bills_of(heads: list, rows: list) -> List[RawDoc]:
    """RawDocs from the Activity rows of type Billing, one per bill number,
    dated by the row's Transaction Date. Payments are passed over. A row of
    a type this app does not know, a header with no single Transaction
    Date or Transaction Type column, a Billing row with no single bill
    link, a link that is not a bill's, a date that is not a calendar date,
    or one bill number twice stops the list, carrying what was read before
    it. Nothing from a row but its date and the name of its type is said."""
    docs: List[RawDoc] = []
    heads = [str(h or "").strip().lower() for h in heads or []]
    if heads.count("transaction date") != 1 or heads.count("transaction type") != 1:
        raise ListStopped("Activity shows no single Transaction Date and Transaction Type column")
    at_date, at_type = heads.index("transaction date"), heads.index("transaction type")
    seen = set()
    for r in rows or []:
        cells, links = (r or {}).get("cells") or [], (r or {}).get("bills") or []
        if max(at_date, at_type) >= len(cells):
            if not any(cells):
                continue
            raise ListStopped("an Activity row does not line up with the header", docs)
        kind = cells[at_type]
        if kind not in KNOWN_TYPES:
            named = f" '{_shape(kind, _words())}'" if _TYPE_WORD_RE.fullmatch(kind or "") else ""
            raise ListStopped(f"an Activity row is of a type{named} this app does not know", docs)
        if kind != BILL_TYPE:
            continue
        if len(links) != 1:
            raise ListStopped("a Billing row carries no single bill link", docs)
        m = _BILL_PATH_RE.fullmatch(urlsplit(links[0]).path if "://" in links[0] else links[0])
        if not m:
            raise ListStopped("a bill link is not one this can read", docs)
        number = m.group(1)
        iso = row_day(cells[at_date])
        if not iso:
            raise ListStopped("a bill's date is not a calendar date", docs)
        if number in seen:
            raise ListStopped("one bill appears twice", docs)
        seen.add(number)
        title = f"Tualatin Water Bill {iso}"
        docs.append(RawDoc(title=title, date_text=iso, href=bill_path(number), text=title,
                           row_index=len(docs), kind="statement", document_id=number))
    return docs


def goto_documents(page) -> bool:
    """Open Activity and read its table. False when it showed the sign-in
    page, settled elsewhere, or did not finish drawing."""
    try:
        _open(page)
        return True
    except (SessionExpired, ListStopped) as e:
        log.info("Activity did not open: %s", e)
        return False


def bill_list_opens(page) -> bool:
    """Whether Activity opened and could be read whole, which only a
    signed-in portal allows."""
    return bill_list_state(page)[0]


def bill_list_state(page) -> Tuple[bool, str]:
    """Whether Activity was read whole, and when its table was read but
    stopped, why. A table that never opened gives no reason."""
    try:
        seen = _open(page)
    except (SessionExpired, ListStopped) as e:
        log.info("Activity could not be read: %s", e)
        return False, ""
    try:
        _bills(seen)
        return True, ""
    except ListStopped as stop:
        log.info("Activity was read but stopped: %s", stop)
        return False, str(stop)


def scroll_full_page(page, rounds: int = 8, delay_ms: int = 600) -> None:
    try:
        for _ in range(rounds):
            page.mouse.wheel(0, 3000)
            page.wait_for_timeout(delay_ms)
    except Exception:
        pass


def expand_all(page) -> None:
    """Nothing to press: every transaction is a row of the one table."""
    return None


def table_facts(page) -> dict:
    """For Diagnose: the Activity table's header as read, its rows, and
    whether it shows a pager, a count, a date filter or a choice of
    accounts."""
    try:
        seen = page.evaluate(_ROWS_JS) or {}
    except Exception:
        seen = {}
    return {"heads": [str(h or "") for h in seen.get("heads") or []][:12],
            "rows": len(seen.get("rows") or []), "pager": bool(seen.get("pager")),
            "count": seen.get("count"), "date_filter": bool(seen.get("dated")),
            "account_choices": seen.get("accounts") or 0, "filtered": bool(seen.get("filtered")),
            "tables": seen.get("tables") or 0}


def _bills(seen: dict) -> List[RawDoc]:
    _whole(seen)
    docs = bills_of(seen.get("heads"), seen.get("rows"))
    # An Activity with no bills has not been seen, and a table that lost
    # its rows would look just like one.
    if not docs:
        raise ListStopped("Activity shows no bills, and an Activity without any has not been seen, "
                          "so this stops rather than call it complete")
    return docs


def collect_download_docs(page) -> List[RawDoc]:
    """Every bill on Activity. Nothing is pressed. A list that cannot be
    read whole raises ListStopped holding what was read, and a signed-out
    portal raises SessionExpired."""
    return _bills(_open(page))


_PRINT_JS = r"""async ([url, origin, limit, ms]) => {
  // Every answer is read no further than `n` bytes: past that its body is
  // cancelled and it comes back as over. Each fetch gives up after `ms`.
  const upTo = (c, n) => {
    let seen = 0;
    const cap = new TransformStream({transform(chunk, ctl) {
      seen += chunk.byteLength;
      if (seen > n) ctl.error(new Error('over')); else ctl.enqueue(chunk);
    }});
    return new Response(c.body ? c.body.pipeThrough(cap) : null);
  };
  const ask = (at) => fetch(at, {credentials: 'include', redirect: 'manual', signal: AbortSignal.timeout(ms)});
  let r;
  try { r = await ask(url); }
  catch (e) { return {status: 0, failed: true}; }
  if (r.type === 'opaqueredirect' || r.redirected) return {status: r.status, redirected: true};
  const type = r.headers.get('content-type') || '';
  if (r.status !== 200 || !/html/i.test(type)) return {status: r.status, type: type};
  if (Number(r.headers.get('content-length')) > limit) {
    try { if (r.body) await r.body.cancel(); } catch (e) {}
    return {status: r.status, type: type, too_big: true};
  }
  let html;
  try { html = await ppText(upTo(r, limit)); }
  catch (e) {
    if (ppRefused(e) || String((e && e.message) || e) === 'over') return {status: r.status, type: type, too_big: true};
    return {status: 0, failed: true};
  }
  const doc = new DOMParser().parseFromString(html, 'text/html');
  // What the page says, and whether it asks for a password, read before
  // anything is written into it, so a stylesheet's words never count.
  const said = (doc.body ? doc.body.textContent : '').replace(/\s+/g, ' ').trim().slice(0, 20000);
  const password = !!doc.querySelector('input[type="password" i]');
  // The printed bill's own look: its stylesheets and images, fetched from
  // the portal's own origin (scheme, host and port) and written into the
  // page, so the offline, script-free drawing shows them without loading
  // anything. Everything written counts against one budget, the page
  // itself first, each stylesheet as written and each image as its data
  // address. Each answer is read no further than what is left, and after
  // the first that does not fit nothing more is asked for. What is left
  // out is named.
  const size = (t) => new TextEncoder().encode(t).length;
  let spent = size(html), full = false;
  const left = () => limit - spent;
  const dropped = [], inlined = {css: 0, img: 0};
  const own = (href) => { try { const u = new URL(href, url); return u.origin === origin ? u.href : ''; } catch (e) { return ''; } };
  const over = () => { full = true; return {why: 'over the budget'}; };
  const take = async (at, kind) => {
    if (full || left() <= 0) return over();
    let c;
    try { c = await ask(at); }
    catch (e) { return {why: 'not fetched'}; }
    const got = c.headers.get('content-type') || '';
    if (c.type === 'opaqueredirect' || c.status !== 200 || !kind.test(got)) {
      try { if (c.body) await c.body.cancel(); } catch (e) {}
      return {why: 'answered ' + c.status};
    }
    if (Number(c.headers.get('content-length')) > left()) {
      try { if (c.body) await c.body.cancel(); } catch (e) {}
      return over();
    }
    try { return {buf: await ppRead(upTo(c, left())), type: got}; }
    catch (e) {
      if (ppRefused(e) || String((e && e.message) || e) === 'over') return over();
      return {why: 'not read'};
    }
  };
  for (const link of [...doc.querySelectorAll('link[rel~="stylesheet"][href]')]) {
    const at = own(link.getAttribute('href'));
    if (!at) continue;
    const got = await take(at, /css/i);
    // An @import, written plainly or with an escape in its name, would
    // reach past what was checked, and a "<" could close the style element
    // and draw markup into the bill, so none of them stays.
    const css = got.buf ? new TextDecoder().decode(got.buf)
      .replace(/@import[^;]*;?/gi, '').replace(/@\\[^;{]*;?/g, '').replace(/</g, '\\3c ') : '';
    if (!got.buf || size(css) > left()) {
      if (got.buf) full = true;
      dropped.push({kind: 'stylesheet', why: got.why || 'over the budget'});
      continue;
    }
    spent += size(css);
    const style = doc.createElement('style');
    // A stylesheet for the screen alone stays one, so it never shapes the
    // printed bill.
    if (link.getAttribute('media')) style.setAttribute('media', link.getAttribute('media'));
    style.textContent = css;
    link.replaceWith(style);
    inlined.css++;
  }
  for (const img of [...doc.querySelectorAll('img[src]')]) {
    const at = own(img.getAttribute('src'));
    if (!at) continue;
    const got = await take(at, /^image\/(png|jpe?g|gif|webp)/i);
    const head = got.buf ? 'data:' + got.type.split(';')[0].trim() + ';base64,' : '';
    if (!got.buf || head.length + 4 * Math.ceil(got.buf.length / 3) > left()) {
      if (got.buf) full = true;
      dropped.push({kind: 'image', why: got.why || 'over the budget'});
      continue;
    }
    let s = '';
    for (let i = 0; i < got.buf.length; i += 0x8000) {
      s += String.fromCharCode.apply(null, got.buf.subarray(i, i + 0x8000));
    }
    const data = head + btoa(s);
    spent += data.length;
    img.setAttribute('src', data);
    inlined.img++;
  }
  return {status: r.status, type: type, html: '<!doctype html>' + doc.documentElement.outerHTML,
          said: said, password: password, inlined: inlined, dropped: dropped};
}"""


def is_printed_bill(said: str) -> bool:
    """Whether a print page's text is a bill: every one of PRINT_MARKERS is
    in it, in any case, since the bill's stylesheet draws some of them in
    capitals in the PDF."""
    text = re.sub(r"\s+", " ", said or "").lower()
    return all(m.lower() in text for m in PRINT_MARKERS)


def billing_date(said: str) -> Optional[str]:
    """The Billing Date a print page's text gives, as YYYY-MM-DD, or None."""
    m = _BILLING_DATE_RE.search(re.sub(r"\s+", " ", said or ""))
    if not m:
        return None
    try:
        return _date(int(m.group(3)), int(m.group(1)), int(m.group(2))).isoformat()
    except ValueError:
        return None


def _fetch(page, number: str, iso_date: str, out_path: Path, trace: Optional[list]) -> bool:
    """Fetch the bill's print page from inside the signed-in page, with its
    own stylesheets and images from the portal host written into it, and
    draw it as a PDF with every script, frame and form taken out, offline
    (receipt_pdf.print_html_inert_to_pdf). A redirect, a refusal or a page
    asking for a password is the portal saying the session has ended. A
    page that is not a printed bill, or is one of another Billing Date than
    the Activity row's, is refused without a file, and so is a PDF whose
    own text does not read as that bill, a stylesheet having hidden part of
    it say. A stylesheet or image left out is noted in the trace."""
    from paperpull_core import receipt_pdf
    url = print_url(number)
    if not url:
        return False
    try:
        got = intake.evaluate(page, _PRINT_JS, [url, BASE, MAX_PAGE_BYTES, FETCH_MS],
                              limit=MAX_PAGE_BYTES) or {}
    except intake.TooLarge:
        return False
    except Exception as e:
        log.info("fetching the bill failed (%s)", type(e).__name__)
        if trace is not None:
            trace.append({"note": "fetch failed", "error": type(e).__name__})
        return False
    dropped = [d for d in got.get("dropped") or [] if isinstance(d, dict)]
    written = got.get("inlined")
    if trace is not None:
        trace.append({"note": "fetched", "host": PORTAL_HOST, "status": got.get("status"),
                      "type": str(got.get("type") or "")[:30], "written": written})
        for d in dropped[:20]:
            trace.append({"note": "left out", "kind": str(d.get("kind"))[:12], "why": str(d.get("why"))[:30]})
    if got.get("redirected") or got.get("status") in (401, 403):
        raise SessionExpired("the payment portal's session has ended")
    if got.get("too_big"):
        log.warning("the print page of the bill dated %s is larger than the %d MB MAX_PAGE_BYTES "
                    "in tualatin_site.py, so it was not read", iso_date, MAX_PAGE_BYTES // (1024 * 1024))
        return False
    html = got.get("html") or ""
    if got.get("status") != 200 or "html" not in str(got.get("type") or "").lower():
        return False
    # The page as written out again can be larger than as read, "&" coming
    # back as "&amp;", so what is drawn is measured too.
    if len(html.encode("utf-8", "replace")) > MAX_PAGE_BYTES:
        log.warning("the bill dated %s written out is larger than the %d MB MAX_PAGE_BYTES "
                    "in tualatin_site.py, so it was not drawn", iso_date, MAX_PAGE_BYTES // (1024 * 1024))
        return False
    if got.get("password"):
        raise SessionExpired("the payment portal answered a bill with its sign-in page")
    said = str(got.get("said") or "")
    if not is_printed_bill(said):
        log.info("the print page did not read as a bill")
        return False
    if billing_date(said) != iso_date:
        log.info("the print page is of another Billing Date than its Activity row")
        if trace is not None:
            trace.append({"note": "another billing date"})
        return False
    if dropped:
        log.warning("%d stylesheet(s) or image(s) of the bill dated %s were left out of its PDF",
                    len(dropped), iso_date)
    tmp = out_path.with_name(out_path.name + ".drawing")
    try:
        try:
            receipt_pdf.print_html_inert_to_pdf(page, html, tmp, base=f"{BASE}/")
        except Exception as e:
            log.info("drawing the bill as a PDF failed (%s)", type(e).__name__)
            return False
        if not (tmp.is_file() and tmp.read_bytes()[:5] == b"%PDF-"):
            return False
        # The stylesheets went in after the page's text was read, so the
        # PDF they shaped is read too, for the same words and Billing Date.
        drawn = drawn_text(tmp)
        if not is_printed_bill(drawn) or billing_date(drawn) != iso_date:
            log.info("the PDF drawn for the bill dated %s does not read as that bill", iso_date)
            if trace is not None:
                trace.append({"note": "drawn pdf is not the bill"})
            return False
        tmp.replace(out_path)
        return True
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass


def drawn_text(path) -> str:
    """Every page's text of a PDF drawn here, or "" when it cannot be read."""
    try:
        return " ".join(pdf_reader.page_texts(Path(path)))
    except Exception:
        return ""


def download_bill(page, dl_dir, iso_date: str, out_path, title: str = "",
                  trace: Optional[list] = None, href: str = "",
                  document_id: str = "") -> bool:
    """Save the bill discovery recorded with bill number `document_id`,
    dated `iso_date`. Activity is opened again and the bill is fetched only
    when exactly one Billing row there carries that number and date.
    `dl_dir` is unused. Nothing is pressed. SessionExpired propagates, and
    so does ListStopped when Activity cannot be read again, since every
    bill after this one would read the same list."""
    out_path = Path(out_path)
    number = (document_id or "").strip()
    if not BILL_NUMBER_RE.fullmatch(number) or href != bill_path(number):
        log.info("no bill was recorded for this document")
        if trace is not None:
            trace.append({"note": "no recorded bill"})
        return False
    try:
        found = [d for d in _bills(_open(page))
                 if d.document_id == number and d.date_text == (iso_date or "")]
    except ListStopped as stop:
        log.info("the bill list stopped while looking for the bill dated %s: %s", iso_date, stop)
        raise
    if len(found) != 1:
        log.info("%d rows match the recorded bill and date %s, none taken", len(found), iso_date)
        if trace is not None:
            trace.append({"note": "no single row matches the record", "matches": len(found)})
        return False
    return _fetch(page, number, iso_date, out_path, trace)


# ---------------------------------------------------------------------------
# Diagnose. Loose, redacted scrape and a survey of the signed-in page.
# No screenshot.
# ---------------------------------------------------------------------------
_ROW_JS = r"""() => {
  const out = [];
  for (const tr of document.querySelectorAll('table tr, [role=row]')) {
    const txt = (tr.innerText || '').trim();
    if (!txt) continue;
    const link = tr.querySelector("a[href]");
    out.push({text: txt.slice(0, 200), href: link ? link.getAttribute('href') : ''});
  }
  return out.slice(0, 200);
}"""

SURVEY_LINK_RE = re.compile(r"^\s*(billing\s+history|view\s+bill\s+history)\s*$", re.I)


def collect_documents(page) -> List[RawDoc]:
    """Loose row scrape used only by --diagnose, digits masked."""
    docs: List[RawDoc] = []
    seen = set()
    try:
        rows = page.evaluate(_ROW_JS)
    except Exception:
        rows = []
    for i, r in enumerate(rows):
        text = redact((r.get("text") or "").strip())
        if not text:
            continue
        has_date = parse_date(text) or MONTH_YEAR_RE.search(text)
        href = redact(r.get("href", "") or "")
        if not (has_date or href or "download" in text.lower()):
            continue
        title = text.splitlines()[0][:200]
        date_text = next((ln for ln in text.splitlines()
                          if parse_date(ln) or MONTH_YEAR_RE.search(ln)), "")
        key = (title, date_text, href, text[:60])
        if key in seen:
            continue
        seen.add(key)
        docs.append(RawDoc(title=re.sub(r"\s+", " ", title), date_text=date_text,
                           href=href, text=text[:400], row_index=i))
    docs.sort(key=lambda d: 0 if d.date_text else 1)
    return docs


def _page_summary(page) -> dict:
    out = {"url": redact(page.url or ""), "title": ""}
    try:
        out["title"] = redact(page.title() or "")
    except Exception:
        pass
    try:
        heads = page.locator("h1, h2, h3").all_inner_texts()
        out["headings"] = [redact(h.strip())[:80] for h in heads if h.strip()][:30]
    except Exception:
        out["headings"] = []
    controls = []
    for role in ("link", "button", "tab", "menuitem"):
        try:
            loc = page.get_by_role(role)
            for i in range(min(loc.count(), 100)):
                el = loc.nth(i)
                try:
                    text = (el.inner_text(timeout=300) or "").strip()
                except Exception:
                    text = ""
                if not text:
                    try:
                        text = (el.get_attribute("aria-label") or "").strip()
                    except Exception:
                        text = ""
                if not text:
                    continue
                href = ""
                if role == "link":
                    try:
                        href = el.get_attribute("href") or ""
                    except Exception:
                        pass
                controls.append({"role": role, "text": redact(text)[:60],
                                 "href": redact(href)[:120],
                                 "safe": is_safe_control(text),
                                 "bill": bool(BILL_CONTROL_RE.search(text)),
                                 "survey": bool(SURVEY_LINK_RE.match(text.strip()))})
        except Exception:
            pass
    out["controls"] = controls
    out["bill_controls"] = sum(1 for c in controls if c["bill"])
    return out


def survey(page, dwell_ms: int = 4000, max_follow: int = 0) -> dict:
    """What the signed-in page looks like, without downloading anything.
    Records the page's headings and controls with the guard's verdict.
    Follows nothing and listens to nothing, since this app presses no
    control at all and a survey is not a reason to start. No screenshot."""
    report = {"pages": []}
    page.wait_for_timeout(dwell_ms)
    report["pages"].append(_page_summary(page))
    return report
