"""ALL myenergycenter.com selectors, URLs, and page behavior live here.

When SDG&E changes My Energy Center, repair this file only.

STATUS: mapped against a signed-in account on 2026-10-12, read-only, with no
control pressed. Everything this app takes is on one page of one host,
https://myenergycenter.com/portal/BillingHistory/index, so NOTHING IS EVER
CLICKED HERE:

  * Billing History's own script asks the portal for the bill list and
    draws it as #billHistoryTable, one `tr` per bill carrying the bill's
    invoice id ("ISU" and twelve digits) as its `invoiceid` attribute and
    the statement date, "Sep 12, 2026", in the column headed Statement
    Date, after a control column and before Due Date. The rows are read
    from the page as drawn, and this app sends no list request of its own.
  * A bill's PDF is a plain GET of
    /portal/BillingHistory/DownloadBillPdf?invoiceId=<id> on the same host,
    which the page's own "View Your Detailed Bill PDF" link opens in a new
    tab: 200, application/pdf, body starting %PDF, no redirect. It is
    fetched here with the session's cookies through paperpull_core.redirects,
    no redirect followed, after the id has been found on exactly one row of
    a freshly opened list with the same statement date.
  * A signed-out request for that address answers 302 to
    /portal/PreLogin/Validate, and the portal's scripts treat a JSON body
    with StatusCode 401 as signed out. Either, or an HTML page where a PDF
    was expected, raises SessionExpired, and the run stops for the account
    holder rather than filing the bill for manual review.

Sign-in (password, SMS code, reCAPTCHA) is the account holder's own, in the
browser. No other host is ever allowed: not www.sdge.com, not the
smartcmobile.net API host, not the paymentus.com payment host.

SAFETY (a utility account that can pay, enroll and start or stop service):
  This module is strictly READ-ONLY. It presses nothing, changes no select,
  and fills nothing. It must NEVER activate any control that pays, sets up
  autopay or a payment arrangement, adds a bank account, changes a pricing
  plan, enrolls in paperless or anything else, starts, stops or transfers
  service, changes notifications, or signs out. FORBIDDEN_CONTROL_RE is kept
  for the survey's verdicts and for any future repair that reaches for a
  control; a control must ALSO match one of the anchored document actions
  (SAFE_DOC_CONTROL_RES), and the shared core guards are consulted every
  time.

KNOWN CEILINGS (left as they are until a run shows otherwise)
  * One account. The account selector (#accountList) is read, never
    changed. With more than one account offered, only the one the page has
    selected is listed, and the run says so once.
  * The empty list has not been seen. A table whose only body cell is the
    table plugin's "No data available in table" stops the list, after a
    further wait for rows, until a real empty history has been seen.
  * One page of the table seen. The live table has no table plugin API and
    no info line, so nothing on the page says how many bills it holds. The
    read waits for the row count to settle, and the list stops on anything
    near the table that looks like a pager or a show-more control, or on
    hidden row numbers that do not run from 1 to the rows read. A count of
    the plugin's own, if the plugin comes back, must agree with the rows
    read too. A history past ten bills has not been seen.
  * Two bills on one statement date stop the list, since a bill's file is
    named by its date alone. None was seen.
  * A bill's date is read from the Statement Date column alone, found by
    its header. The header has been named but its whole text never seen,
    so the one header cell holding the words statement and date is taken,
    and Diagnose writes the header cells it read. A table with no single
    such column, a row that does not line up with the header, or a row
    whose Statement Date cell is blank stops the list rather than taking
    the Due Date or any other column's date. None of these was seen.
  * Solar (NBT) bills are fetched by the same address and filed as ordinary
    bills. Solar Billing Plans is never visited.
  * About two years of bills are online; older ones are not offered.
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
from paperpull_core import redirects
from paperpull_core.controls import SETTINGS_CONTROL_RE, AUTH_CONTROL_RE
from paperpull_core.ready import count_settles, ready, url_matches
from paperpull_core.redact import private_words, redact, set_private_words  # noqa: F401  (re-exported)
from paperpull_core.urls import is_safe_url as _host_allows
from paperpull_core.dates import last_day as _last_day
from paperpull_core.dates import checked as _checked_date
from paperpull_core.dates import full_year as _full_year
from paperpull_core.words import words_for as _words_for

log = logging.getLogger("sdge_docs.site")


def _words():
    """This app's own words for paperpull_core.words."""
    return _words_for("SDG&E", sys.modules[__name__])


# ---------------------------------------------------------------------------
# Addresses
# ---------------------------------------------------------------------------
BASE = "https://myenergycenter.com"
PORTAL = f"{BASE}/portal"
DOCUMENTS_PATH = "/portal/BillingHistory/index"
DOCUMENTS_URL = BASE + DOCUMENTS_PATH
# The one path a bill is fetched from. It is what discovery records as a
# bill's href, with no query: the invoice id is the record's document_id and
# the query is built from it, checked, only when the bill is fetched.
DOWNLOAD_PATH = "/portal/BillingHistory/DownloadBillPdf"
STATEMENTS_URL = DOCUMENTS_URL
BILLING_URL = DOCUMENTS_URL
URLS = {
    "home": f"{PORTAL}/",
    # A signed-out visit is sent on to /portal/PreLogin/Validate, where the
    # account holder signs in.
    "login": f"{PORTAL}/",
    "documents": DOCUMENTS_URL,
    "statements": DOCUMENTS_URL,
}

LOGIN_URL_MARKERS = ["/prelogin/", "/accounts/logout", "/account/login", "/login"]

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
    r"\brebalance\b|\bliquidate\b|\bdetails\b)", re.I)

# The document actions this app would ever accept, anchored whole: the
# portal's own "View Your Detailed Bill PDF", "Download Your Solar Bill" and
# "View Bill", and the "View Utility Bill" its rules name. Nothing looser,
# so a label carrying anything more is refused.
SAFE_DOC_CONTROL_RES = (
    re.compile(r"^(view|download)\s+(your\s+)?(detailed\s+)?(utility\s+)?bill(\s+pdf)?$", re.I),
    re.compile(r"^(view|download)\s+your\s+solar\s+bill$", re.I),
)

# A control that fetches one bill, for the survey.
BILL_CONTROL_RE = re.compile(r"(view\s+your\s+detailed\s+bill\s+pdf|download\s+your\s+solar\s+bill|^\s*view\s+bill\s*$)", re.I)

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
BILL_ROW = "#billHistoryTable tbody tr[invoiceid]"
EMPTY_CELL = "#billHistoryTable tbody td.dataTables_empty"
EMPTY_TEXT_RE = re.compile(r"no data available in table", re.I)

# Fallback selectors (used by --diagnose and the journal).
FALLBACK = {
    "doc_row": BILL_ROW,
    "doc_link": "a#downloadBillingHisotry",
    "download_control": "a#downloadBillingHisotry",
    "page_ready": "#billHistoryTable",
    "account_select": "select#accountList",
}

# ---------------------------------------------------------------------------
# Date parsing (verbatim from the Nelnet app; the bill rows use
# statement_date below, which reads one shape only)
# ---------------------------------------------------------------------------
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


# A bill row's statement date, exactly as the table writes it: "Sep 12, 2026".
_STATEMENT_DATE_RE = re.compile(
    r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+([0-9]{1,2}),\s+([0-9]{4})")
# The words that head the column that date is read from. A header holding
# both, as "Statement Date" or "Statement Date *" does, and "Due Date" does
# not, since the live header has only been named, never seen whole.
STATEMENT_HEAD_WORDS = frozenset({"statement", "date"})


def statement_date(text) -> Optional[str]:
    """A bill row's statement date as YYYY-MM-DD, or None. The whole cell
    must be the date and the day must exist; nothing is found inside other
    text."""
    m = _STATEMENT_DATE_RE.fullmatch(re.sub(r"\s+", " ", str(text or "")).strip())
    if not m:
        return None
    try:
        return _date(int(m.group(3)), _MONTHS[m.group(1).lower()], int(m.group(2))).isoformat()
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Session / safety
# ---------------------------------------------------------------------------

class SessionExpired(Exception):
    """My Energy Center answered as a signed-out session: its sign-in page,
    a redirect where a bill was asked for, a 401, or an HTML or JSON body
    where a PDF was expected. The run stops for the account holder."""


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
# Hosts. Exact, parsed, no subdomain wildcard, and a bill only from its own
# path with exactly one well-formed invoice id.
# ---------------------------------------------------------------------------
ALLOWED_HOSTS = {"myenergycenter.com"}
INVOICE_ID_RE = re.compile(r"ISU[0-9]{12}")
_DOWNLOAD_QUERY_RE = re.compile(r"invoiceId=ISU[0-9]{12}")


def is_safe_url(url: str) -> bool:
    """True only for an https URL on exactly myenergycenter.com."""
    return _host_allows(url, ALLOWED_HOSTS, subdomains=False)


def is_download_url(url: str) -> bool:
    """True only for a bill's own address: exactly this host, exactly the
    download path, and a query that is one invoiceId of the right shape,
    written plainly. Also the only redirect target paperpull_core.redirects
    may follow, so a redirect to the sign-in page is handed back, never
    followed."""
    if not is_safe_url(url):
        return False
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    return (parts.path == DOWNLOAD_PATH and not parts.fragment
            and bool(_DOWNLOAD_QUERY_RE.fullmatch(parts.query or "")))


def download_url(invoice_id: str) -> str:
    """The address of the bill with this invoice id, or "" when the id is
    not one."""
    if not INVOICE_ID_RE.fullmatch(invoice_id or ""):
        return ""
    url = f"{BASE}{DOWNLOAD_PATH}?invoiceId={invoice_id}"
    return url if is_download_url(url) else ""


# ---------------------------------------------------------------------------
# Bills. Read from the rows Billing History draws; nothing is pressed.
# ---------------------------------------------------------------------------

@dataclass
class RawDoc:
    title: str
    account: str = ""
    date_text: str = ""
    href: str = ""
    text: str = ""
    row_index: int = -1
    kind: str = "doc"
    # The bill's invoice id, which is what the bill is fetched by and what
    # tells two bills apart.
    document_id: str = ""


class ListStopped(Exception):
    """The list has a part this could not read, so what was read is not all
    of it. `docs` holds what was read before it stopped."""

    def __init__(self, why: str, docs=None):
        super().__init__(why)
        self.docs = list(docs or [])


# Each bill row's invoice id and cells, the table's header cells, and the
# empty-table cell's text. Each cell carries the column it starts at, how
# many it spans and how many rows it is tall, so a row's Statement Date
# cell is the one under that header (header_layout), wherever the table
# puts it, and a row that may not line up with the header is known. Since
# November 2026 each bill row starts with a cell the page hides, holding
# only the row's number, with no header cell above it. Each row says what
# that cell holds, as its number, and past_row_number decides whether the
# cell is passed over. Any other hidden cell, in the header or a row, still
# counts as a column, so a table that hides some of its columns is read by
# where each cell sits in the table. A bill is dated by the cell under
# Statement Date there, seen or hidden, and cells that do not line up stop
# the list. What is drawn near the table is read too, for shows_more. Read
# only, and nothing on the page is changed.
_ROWS_JS = r"""() => {
  const table = document.querySelector('#billHistoryTable');
  if (!table) return null;
  const text = (cell) => (cell.textContent || '').replace(/\s+/g, ' ').trim();
  const rowNumber = (td) => td.tagName === 'TD' && (td.colSpan || 1) === 1 && td.rowSpan === 1
    && getComputedStyle(td).display === 'none' && /^\d+$/.test(text(td));
  // A header cell's column counts what spans down into its row from above
  // as well as what is before it, as the table itself lays them out.
  const heads = [];
  const taken = new Set();
  Array.from(table.tHead ? table.tHead.rows : []).forEach((tr, r) => {
    let at = 0;
    for (const th of tr.cells) {
      while (taken.has(r + ':' + at)) at++;
      const wide = th.colSpan || 1;
      heads.push({text: text(th), at: at, wide: wide, tall: th.rowSpan});
      for (let down = 0; down < (th.rowSpan || 1); down++)
        for (let across = 0; across < wide; across++) taken.add((r + down) + ':' + (at + across));
      at += wide;
    }
  });
  const rows = [];
  for (const tr of table.querySelectorAll('tbody tr[invoiceid]')) {
    const cells = [];
    let at = 0;
    for (const td of tr.cells) {
      cells.push({text: text(td), at: at, wide: td.colSpan || 1, tall: td.rowSpan});
      at += td.colSpan || 1;
    }
    const first = tr.cells[0];
    rows.push({id: tr.getAttribute('invoiceid') || '', cells: cells,
               number: first && rowNumber(first) ? text(first) : ''});
  }
  const empty = table.querySelector('tbody td.dataTables_empty');
  // The table plugin keeps only the page it shows in the DOM, so what it
  // says of the whole table is read too, from its API and its info line.
  let api = null;
  try {
    const $ = window.jQuery;
    if ($ && $.fn && $.fn.dataTable && $.fn.dataTable.isDataTable(table)) {
      const dt = $(table).DataTable();
      const info = dt.page.info();
      api = {total: info.recordsTotal, shown: info.recordsDisplay, search: String(dt.search() || '')};
    }
  } catch (e) {
    api = {unreadable: true};
  }
  const line = document.querySelector('#billHistoryTable_info');
  // What a person sees near the table, for shows_more. Near is over the
  // table's own width and within 200 pixels above or below it. Inside the
  // table it is the footer and the last row, and never the other rows,
  // since a bill's detail rows hold that bill's own links.
  const box = table.getBoundingClientRect();
  const last = Array.from(table.querySelectorAll('tbody tr')).pop();
  const near = (el) => {
    if (table.contains(el) && !el.closest('tfoot') && el.closest('tr') !== last) return false;
    const b = el.getBoundingClientRect();
    return b.width > 0 && b.height > 0 && getComputedStyle(el).visibility !== 'hidden'
      && b.left < box.right && b.right > box.left
      && b.top < box.bottom + 200 && b.bottom > box.top - 200;
  };
  const around = Array.from(document.querySelectorAll('body *')).filter(near).map((el) => ({
    said: (text(el) || el.getAttribute('aria-label') || el.getAttribute('title')
           || (el.tagName === 'INPUT' ? el.value : '') || '').slice(0, 60),
    press: el.matches('a, button, input, [role="button"], [role="link"], [onclick]'),
    pager: el.matches('[class*="pagina" i], [id*="pagina" i], [class*="pager" i], '
                      + '[id*="pager" i], [aria-label*="pagina" i]')}));
  return {rows: rows, heads: heads, empty: empty ? text(empty) : '',
          api: api, info: line ? text(line) : '', around: around};
}"""

# The table plugin's info line, "Showing 1 to 10 of 24 entries", and the
# "(filtered from N total entries)" it adds under a search.
INFO_TOTAL_RE = re.compile(r"\bof\s+([\d,]+)\s+entries\b", re.IGNORECASE)
INFO_FILTERED_RE = re.compile(r"\bfiltered\b", re.IGNORECASE)

# What says the table may hold more bills than it shows, among what is drawn
# near it (shows_more). A show-more control's words, whole, in any element,
# since a page can make a plain span one with a click handler of its own.
_LISTED = r"(?:bills?|statements?|invoices?|rows?|results?|records?|entries|items?|history)"
SHOW_MORE_RE = re.compile(
    r"(?:show|load|view|see|get|display)(?:\s+[0-9]+)?\s+"
    r"(?:more|all|older|earlier|previous|additional)(?:\s+" + _LISTED + r")?"
    r"|(?:more|older|earlier|previous)\s+" + _LISTED, re.IGNORECASE)
# A pager's line, "1 to 10 of 24" or "Page 1 of 3", inside whatever it says.
PAGE_LINE_RE = re.compile(
    r"\b[0-9]+\s*(?:-|\u2013|to)\s*[0-9]+\s+of\s+[0-9]+\b|\bpage\s+[0-9]+\s+of\s+[0-9]+\b",
    re.IGNORECASE)
# A step of a pager, whole, which counts only on something that can be
# pressed, since a detail row can head a column Previous or First.
PAGE_STEP_RE = re.compile(
    r"(?:next|previous|prev|older|newer|first|last|more)(?:\s+(?:page|[0-9]+))?"
    r"|(?:go\s+to\s+)?page\s+[0-9]+", re.IGNORECASE)
PAGE_ARROW_RE = re.compile(r"[<>\u00ab\u00bb\u2039\u203a]+")

# What would identify the account holder on Billing History: every value of
# the account selector's options and each bill row's contract account. Read
# only to be registered as private words; never logged or returned past
# redact's word list.
_ACCOUNT_JS = r"""() => {
  const out = {count: 0, words: []};
  const sel = document.querySelector('select#accountList');
  if (sel) {
    out.count = sel.options.length;
    for (const o of sel.options) {
      for (const a of ['value', 'accountnumber', 'contractaccount', 'address'])
        out.words.push(o.getAttribute(a) || '');
      out.words.push(o.textContent || '');
    }
  }
  for (const tr of document.querySelectorAll('#billHistoryTable tr[contractaccount]'))
    out.words.push(tr.getAttribute('contractaccount') || '');
  for (const el of document.querySelectorAll('.filter-option, .filter-option-inner-inner'))
    out.words.push(el.textContent || '');
  return out;
}"""

_told_of_accounts = False


def _guard_account(page) -> None:
    """Register what names the account as private words, beside the owner's
    name already there, and say once when the selector offers more than one
    account. The selection is never changed (KNOWN CEILINGS)."""
    global _told_of_accounts
    try:
        seen = page.evaluate(_ACCOUNT_JS) or {}
    except Exception as e:
        log.info("the account selector could not be read (%s)", type(e).__name__)
        return
    # Registered part by part, as redact applies them anywhere in a string:
    # a part of four letters or more, or one with a digit. "CA" or "St" would
    # turn "CAPTCHA" and "Statement" into "[name]" in every diagnostic.
    parts = {part for w in (seen.get("words") or []) for part in re.split(r"[\s,.#/-]+", str(w or ""))
             if len(part) >= 4 or re.search(r"[0-9]", part)}
    if parts - set(private_words()):
        set_private_words(private_words() + sorted(parts - set(private_words())))
    try:
        count = int(seen.get("count") or 0)
    except (TypeError, ValueError):
        count = 0
    if count > 1 and not _told_of_accounts:
        _told_of_accounts = True
        log.warning("My Energy Center offers %d accounts; only the one selected on "
                    "Billing History is listed. Choose another there yourself to list it.", count)


def _tabs(page) -> int:
    try:
        return len(page.context.pages)
    except Exception:
        return -1


def _settled_here(page) -> bool:
    """Whether the tab is at Billing History's own address on the portal's
    own host. goto follows redirects, and only this page is read."""
    url = page.url or ""
    try:
        return is_safe_url(url) and urlsplit(url).path == DOCUMENTS_PATH
    except ValueError:
        return False


def _open(page, timeout_ms: int = 30000) -> None:
    """Open Billing History by its address and wait for its bill rows, or
    for its explicit empty-table cell. Raises SessionExpired when the portal
    shows its sign-in page and ListStopped when the list does not finish
    drawing. Nothing is pressed."""
    before = _tabs(page)
    try:
        page.goto(DOCUMENTS_URL, wait_until="domcontentloaded", timeout=60000)
    except Exception as e:
        log.info("opening Billing History failed (%s)", type(e).__name__)
        if looks_signed_out(page):
            raise SessionExpired("My Energy Center showed its sign-in page")
        raise ListStopped("Billing History did not open")
    if before >= 0 and _tabs(page) > before:
        # Not this run's tab, and nothing here acts on it; the survey vendor
        # the portal loads can open one.
        log.info("a tab opened while Billing History loaded; it was left alone")
    if looks_signed_out(page):
        raise SessionExpired("My Energy Center showed its sign-in page")
    if not _settled_here(page):
        raise ListStopped("Billing History settled off its own address")
    try:
        page.wait_for_selector(f"{BILL_ROW}, {EMPTY_CELL}", timeout=timeout_ms)
    except Exception:
        if looks_signed_out(page):
            raise SessionExpired("My Energy Center showed its sign-in page")
        raise ListStopped("the billing history did not finish loading")
    _guard_account(page)


# How long the count of bill rows has to stand still before the rows are
# read, and how long that wait may take in all. It is longer than the gap
# of a second and a half between two batches a probe drew, and it is paid
# once per read of the list.
ROWS_QUIET_MS = 3000
ROWS_BUDGET_MS = 20000
# ready() ends as soon as its invariant holds, so has(BILL_ROW) would end
# this wait on the first row. No address matches this, so the wait lasts
# until count_settles itself ends. That is why the journal says a further
# bill row never became ready on a list that settled, which is the answer
# this wait is after.
_NO_FURTHER_ROW = url_matches(r"(?!)")
# The run's journal, handed over by the app, so what the wait found is
# written down. None when nobody set one.
_journal = None


def set_journal(journal) -> None:
    global _journal
    _journal = journal


def _rows_settled(page) -> bool:
    """Whether the count of bill rows stood still for ROWS_QUIET_MS. The
    wait for rows ends on the first one, and rows can be drawn in batches.
    count_settles ending with _NO_FURTHER_ROW unmet is what ready() calls
    not_satisfied, which here is the count having settled. A count still
    moving at the end of ROWS_BUDGET_MS, or one that could not be asked, is
    anything else."""
    got = ready(page, [count_settles(BILL_ROW, quiet_ms=ROWS_QUIET_MS)], _NO_FURTHER_ROW,
                ROWS_BUDGET_MS, journal=_journal, name="a further bill row")
    return [a.outcome for a in got.attempts] == ["not_satisfied"]


def _bills(page) -> List[RawDoc]:
    """Every bill row on the open Billing History. A table showing only its
    empty cell is given a further wait for rows, since the table plugin can
    draw that cell, "Loading..." or "No data available in table", before
    the page's own request has filled it. A table still without rows after
    that stops the list: this app has never seen a billing history with no
    bills, so an empty table is not read as one. Rows are read once their
    count has settled, and a count that does not settle stops the list. The
    session is asked again after each wait, since a sign-out can land
    during it."""
    seen = _read_rows(page)
    if seen is not None and not seen.get("rows"):
        try:
            page.wait_for_selector(BILL_ROW, timeout=10000)
        except Exception:
            pass
        if looks_signed_out(page):
            raise SessionExpired("My Energy Center showed its sign-in page")
        seen = _read_rows(page)
    settled = True
    if seen is not None and seen.get("rows"):
        settled = _rows_settled(page)
        if looks_signed_out(page):
            raise SessionExpired("My Energy Center showed its sign-in page")
        seen = _read_rows(page)
    if seen is None:
        raise ListStopped("Billing History shows no bill table")
    rows = seen.get("rows") or []
    if rows:
        docs = bills_of(rows, seen.get("heads"))
        if not settled:
            raise ListStopped("the bill rows were still being drawn", docs)
        _whole_table(seen, docs)
        return docs
    if EMPTY_TEXT_RE.fullmatch(seen.get("empty") or ""):
        # ponytail: fail closed until a real empty history has been seen;
        # then this can become an empty list.
        raise ListStopped("Billing History drew its empty table, which this app does not yet read as no bills")
    raise ListStopped("the billing history did not finish loading")


def shows_more(around) -> bool:
    """Whether anything drawn near the bill table, as _ROWS_JS reads it,
    looks like a pager or a show-more control. Only whole phrases count, and
    a step of a pager or a page number only on something that can be
    pressed, so a bill's own links and a column's heading are not taken for
    one. One page number alone says there are no others, so it takes two."""
    pages = set()
    for el in around or []:
        said = str(el.get("said") or "")
        words = re.sub(r"^[^0-9a-z]+|[^0-9a-z]+$", "", said, flags=re.IGNORECASE)
        if el.get("pager") or SHOW_MORE_RE.fullmatch(words) or PAGE_LINE_RE.search(said):
            return True
        if el.get("press"):
            if PAGE_STEP_RE.fullmatch(words) or PAGE_ARROW_RE.fullmatch(said):
                return True
            if re.fullmatch(r"[0-9]{1,3}", words):
                pages.add(words)
    return len(pages) >= 2


def numbers_in_place(rows) -> bool:
    """Whether every row carrying a hidden row number carries its own place
    among the rows read, counted from 1. A row with no such number is not
    asked. Rows numbered from 11 are a second page, and a gap is a bill the
    table did not draw."""
    return all(not r.get("number") or str(r["number"]).lstrip("0") == str(place)
               for place, r in enumerate(rows or [], 1))


def _whole_table(seen: dict, docs: List[RawDoc]) -> None:
    """Stop the list unless the rows read may be every bill the table holds.
    The table plugin draws one page of rows at a time (ten by default) and
    can filter them by a remembered search, so rows alone never prove the
    whole history. Its API's totals, when it answers, and its info line,
    when drawn, must both agree with the rows read and show no filter. The
    live table has neither, so nothing on the page counts its bills. So
    anything near it that looks like a pager or a show-more control stops
    the list, and the hidden row numbers must run from 1 to the rows read."""
    n = len(docs)
    api = seen.get("api")
    if isinstance(api, dict):
        if api.get("unreadable"):
            raise ListStopped("the bill table's own count could not be read", docs)
        total, shown = api.get("total"), api.get("shown")
        if api.get("search") or total != shown:
            raise ListStopped("the bill table is filtered by a search", docs)
        if total != n:
            raise ListStopped(f"the bill table holds {total} bills and {n} were drawn", docs)
    info = str(seen.get("info") or "")
    if info:
        if INFO_FILTERED_RE.search(info):
            raise ListStopped("the bill table is filtered by a search", docs)
        m = INFO_TOTAL_RE.search(info)
        if not m:
            raise ListStopped("the bill table's own count could not be read", docs)
        total = int(m.group(1).replace(",", ""))
        if total != n:
            raise ListStopped(f"the bill table holds {total} bills and {n} were drawn", docs)
    if shows_more(seen.get("around")):
        raise ListStopped("the bill table shows a pager or a show-more control", docs)
    if not numbers_in_place(seen.get("rows")):
        raise ListStopped(f"the bill table's hidden row numbers do not run from 1 to {n}", docs)


def _read_rows(page):
    try:
        seen = page.evaluate(_ROWS_JS)
    except Exception as e:
        log.info("reading the bill rows failed (%s)", type(e).__name__)
        return None
    return seen if isinstance(seen, dict) else None


def table_header(page) -> dict:
    """For Diagnose, the bill table's header cells as read and where the
    Statement Date column was found in them, None when it was not."""
    seen = _read_rows(page) or {}
    heads = seen.get("heads") or []
    layout = header_layout(heads)
    return {"cells": [str(h.get("text") or "") for h in heads if isinstance(h, dict)],
            "statement_date_column": layout[0] if layout else None}


def _laid_out(cell) -> bool:
    """Whether a cell as _ROWS_JS reads it has a column, a width and a
    height. A rowspan of 0 reads as no height."""
    return (isinstance(cell, dict)
            and all(isinstance(cell.get(k), int) for k in ("at", "wide", "tall"))
            and cell["at"] >= 0 and cell["wide"] >= 1 and cell["tall"] >= 1)


def header_layout(heads) -> Optional[Tuple[int, int]]:
    """The column the table's header names Statement Date, and how many
    columns the header covers, as _ROWS_JS reads its cells. None when a
    header cell has no height, which would put the cells of the header rows
    below it in the wrong columns, or when no header cell holds both words
    of STATEMENT_HEAD_WORDS, more than one does, or the one that does spans
    several columns."""
    heads = list(heads or [])
    if not heads or not all(_laid_out(h) for h in heads):
        return None
    found = [h for h in heads
             if STATEMENT_HEAD_WORDS <= set(re.findall(r"[a-z]+", str(h.get("text") or "").lower()))]
    if len(found) != 1 or found[0]["wide"] != 1:
        return None
    return found[0]["at"], max(h["at"] + h["wide"] for h in heads)


def statement_cell(cells, column: int, width: int) -> Optional[str]:
    """The text of a row's cell in this column, or None when the row does
    not line up with the header. Its cells have to sit side by side from
    the first column to the header's last, each one row tall, since a cell
    taller than its row moves the next row's cells out of their columns,
    and the one in this column has to be that column's alone."""
    at, text = 0, None
    for c in cells or []:
        if not _laid_out(c) or c["at"] != at or c["tall"] != 1:
            return None
        if at <= column < at + c["wide"]:
            if c["wide"] != 1:
                return None
            text = str(c.get("text") or "")
        at += c["wide"]
    return text if at == width else None


def past_row_number(row: dict, layout: Tuple[int, int]) -> list:
    """A row's cells as they sit under the header. A first cell the page
    hides, holding only the row's number, has no header cell above it in the
    live table, so it is passed over. Only there, with Statement Date the
    header's first column and the row exactly one column wider than the
    header. Under any other first column that cell can be a real column
    with some other cell left without a header, and passing it over would
    put a Due Date under Statement Date, so the row keeps every cell and
    does not line up."""
    cells = (row or {}).get("cells") or []
    column, width = layout
    if not (row or {}).get("number") or column != 0 or not all(_laid_out(c) for c in cells):
        return cells
    if sum(c["wide"] for c in cells) != width + 1:
        return cells
    return [dict(c, at=c["at"] - 1) for c in cells[1:]]


def bills_of(rows: list, heads: Optional[list]) -> List[RawDoc]:
    """RawDocs from the bill rows as read, one per invoice id. A table with
    no single Statement Date column, an id that is not "ISU" and twelve
    digits, a row that does not line up with the header, a Statement Date
    cell that is blank or not a calendar date, one id on two rows, or two
    bills on one statement date stops the list,
    carrying what was read before it. The date is never taken from another
    column, since the Due Date beside it is a date too. A bill's file is
    named by its date, and the end of its invoice id is added only when a
    file of that name is already in the folder (sdge_docs.told_apart_by),
    so two bills of one date are not filed. The page's own words stay out
    of what is said, since it is printed and logged."""
    docs: List[RawDoc] = []
    seen = set()
    dates = set()
    layout = header_layout(heads)
    for r in rows:
        if layout is None:
            raise ListStopped("the bill table's header shows no single Statement Date column", docs)
        inv = str((r or {}).get("id") or "")
        if not INVOICE_ID_RE.fullmatch(inv):
            raise ListStopped("a bill's invoice id is not one this can read", docs)
        text = statement_cell(past_row_number(r, layout), *layout)
        if text is None:
            raise ListStopped("a bill's row does not line up with the table's header", docs)
        if not text.strip():
            raise ListStopped("a bill's Statement Date cell is blank", docs)
        iso = statement_date(text)
        if not iso:
            raise ListStopped("a bill's statement date is not a calendar date", docs)
        if inv in seen:
            raise ListStopped("two bill rows carry one invoice id", docs)
        if iso in dates:
            raise ListStopped("two bills carry one statement date", docs)
        seen.add(inv)
        dates.add(iso)
        title = f"SDG&E Bill {iso}"
        docs.append(RawDoc(title=title, date_text=iso, href=DOWNLOAD_PATH, text=title,
                           row_index=len(docs), kind="statement", document_id=inv))
    return docs


def goto_documents(page) -> bool:
    """Open Billing History by its address and wait for its list. False
    when it showed the sign-in page, settled elsewhere, or did not finish
    drawing. No click, no banner handling."""
    try:
        _open(page)
        return True
    except (SessionExpired, ListStopped) as e:
        log.info("Billing History did not open: %s", e)
        return False


def bill_list_opens(page) -> bool:
    """Whether Billing History opened and its list could be read whole,
    which only a signed-in page allows."""
    try:
        collect_download_docs(page)
        return True
    except (SessionExpired, ListStopped) as e:
        log.info("Billing History could not be read: %s", e)
        return False


def scroll_full_page(page, rounds: int = 8, delay_ms: int = 600) -> None:
    try:
        for _ in range(rounds):
            page.mouse.wheel(0, 3000)
            page.wait_for_timeout(delay_ms)
    except Exception:
        pass


def expand_all(page) -> None:
    """Nothing to press: every bill is a row of the one table."""
    return None


def collect_download_docs(page) -> List[RawDoc]:
    """Every bill on Billing History. Nothing is pressed. A list that will
    not open or cannot be read raises ListStopped holding what was read, and
    a signed-out portal raises SessionExpired."""
    _open(page)
    return _bills(page)


def _fetch(page, invoice_id: str, out_path: Path, trace: Optional[list]) -> bool:
    """GET the bill's own address with the session's cookies, no redirect
    followed, and keep it only when it is a PDF (application/pdf, whatever
    its case or content-disposition, and a body starting %PDF). A redirect,
    a 401 or 403, or an HTML or JSON body is the portal saying the session
    has ended."""
    url = download_url(invoice_id)
    if not url:
        if trace is not None:
            trace.append({"note": "bill address refused"})
        return False
    try:
        resp = redirects.get(page.context.request, url, is_download_url, hops=0, timeout=60000)
    except redirects.TooManyRedirects:
        raise SessionExpired("the bill's address sent the request on")
    except Exception as e:
        log.info("fetching the bill failed (%s)", type(e).__name__)
        if trace is not None:
            trace.append({"note": "fetch failed", "error": type(e).__name__})
        return False
    ctype = (resp.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
    if trace is not None:
        trace.append({"note": "fetched", "host": "myenergycenter.com", "status": resp.status,
                      "type": ctype[:30]})
    if resp.status in redirects.REDIRECTS or resp.status in (401, 403) \
            or (resp.status == 200 and (ctype.startswith("text/") or "json" in ctype)):
        _let_go(resp)
        raise SessionExpired("My Energy Center answered a bill with a sign-in response")
    if resp.status != 200 or ctype != "application/pdf":
        _let_go(resp)
        return False
    try:
        body = intake.body(resp)
    except intake.TooLarge:
        return False
    if body[:5] != b"%PDF-":
        # A sign-in page or a JSON error labeled as a PDF is still the
        # portal saying the session has ended.
        if body.lstrip()[:1] in (b"<", b"{", b"["):
            raise SessionExpired("My Energy Center answered a bill with a sign-in body")
        return False
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(body)
    return True


def _let_go(resp) -> None:
    try:
        resp.dispose()
    except Exception:
        pass


def download_bill(page, dl_dir, iso_date: str, out_path, title: str = "",
                  trace: Optional[list] = None, href: str = "",
                  document_id: str = "") -> bool:
    """Save the bill discovery recorded with invoice id `document_id`, dated
    `iso_date`. Billing History is opened again and the bill is fetched only
    when exactly one row there carries that same invoice id and statement
    date. `dl_dir` is unused: nothing here goes through the browser's
    downloads. Nothing is pressed. SessionExpired propagates to the run, and
    so does ListStopped when Billing History cannot be read again, since
    every bill after this one would read the same list."""
    out_path = Path(out_path)
    inv = (document_id or "").strip()
    if href != DOWNLOAD_PATH or not INVOICE_ID_RE.fullmatch(inv):
        log.info("no bill address was recorded for this document")
        if trace is not None:
            trace.append({"note": "no recorded bill"})
        return False
    try:
        _open(page)
        found = [d for d in _bills(page) if d.document_id == inv and d.date_text == (iso_date or "")]
    except ListStopped as stop:
        log.info("the bill list stopped while looking for the bill dated %s: %s", iso_date, stop)
        raise
    if len(found) != 1:
        log.info("%d rows match the recorded invoice id and date %s, none taken", len(found), iso_date)
        if trace is not None:
            trace.append({"note": "no single row matches the record", "matches": len(found)})
        return False
    return _fetch(page, inv, out_path, trace)


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
