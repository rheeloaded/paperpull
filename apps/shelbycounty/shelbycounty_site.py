"""ALL apps2.shelbycountytrustee.com selectors, URLs, and page behavior live here.

When the Shelby County Trustee changes its lookup, repair this file only.

STATUS: mapped against the household's parcel on 2026-10-12 with a read-only
survey and one press of Print Receipt. The Trustee's Tax Query app is public:
there is no sign-in, no session, no challenge. Login opens the parcel's page.

  * /Parcel?parcel=<id> (server-rendered): Parcel Details, QUICK ACTIONS
    (PRINT NOTICE, disabled at a zero balance; LEGAL DESCRIPTION; two GIS
    links marked EXTERNAL; MAKE PAYMENT EXTERNAL) and BILLING HISTORY, a
    table BILL # | YEAR | TAX AUTHORITY | TAX DUE | INTEREST | TOTAL FEES |
    TOTAL DUE | ASSESSMENT, ten rows a page, with a footer "PAGE x OF y ...
    TOTAL RECORDS: n" and PREVIOUS / NEXT buttons. Each BILL # links to
    /Transaction?billNumberData=<base64 of the whole bill row, owner and
    parcel included>. That address is read from the row and navigated to,
    and never written down anywhere.
  * /Transaction: PAYMENT HISTORY, a table PRINT | RECEIPT# | DATE | TYPE |
    AMOUNT with the same footer and pager; each row's "Print Receipt" is a
    link. Pressing it makes the page build the receipt as a PDF Blob and
    call window.open on its object URL, then revoke the URL. No request
    leaves the browser for the document.
  * The documents are therefore taken by a hook armed before the press
    (_arm_blob_hook): it keeps every Blob the page creates, with its type
    and the object URL's origin, and replaces window.open with a recorder
    that opens nothing. One press must make exactly one Blob of type
    application/pdf on this host's origin, asked to open at that same URL,
    whose bytes start with %PDF-; anything else is refused.

SAFETY (a tax site whose main purpose is paying):
  Strictly READ-ONLY. The only controls pressed are a receipt row's
  "Print Receipt", the "Print Notice" button when a balance is due, and a
  table's NEXT button, each through is_safe_control. FORBIDDEN_CONTROL_RE
  refuses pay, payment, make payment, cart, checkout, proceed, wallet,
  e-check, card, ManagedPay, enroll, sign up, eBill, autopay, appeal, apply,
  redeem, register, subscribe, external, GIS, legal description, search,
  columns, rows... The payment site, payments.shelbycountytrustee.com
  (payit901), is never an allowed host; after every navigation and every
  press the tab must still be on this host and no other tab may have
  opened, or the run stops. There is no code here that submits a form or
  confirms a dialog.

PRIVACY: the parcel id is config, registered as a private word with its
spellings, as are the owner and location the parcel page shows. Records keep
tax year, receipt date and category only; href stays empty; no log or trace
line formats an address.

KNOWN CEILINGS (ponytail: left as they are until a run shows otherwise)
  * One parcel per config; a second parcel is a second config (add-account).
  * The notice (bill) exists online only while a balance is due; a paid-up
    parcel yields receipts alone.
  * Two receipts for one tax year on one day (seen: tax year 2019, two
    payments on one date) are told apart by the last four digits of their
    receipt numbers, carried in the title as "(#1234)". Only then; a lone
    receipt's number is never written. Two receipts sharing date and last
    four stop the list.
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

from paperpull_core import pdf_reader
from paperpull_core import intake
from paperpull_core.controls import SETTINGS_CONTROL_RE, AUTH_CONTROL_RE
from paperpull_core import pressing
from paperpull_core.redact import redact, set_private_words, private_words  # noqa: F401  (re-exported)
from paperpull_core.urls import is_safe_url as _host_allows
from paperpull_core.dates import last_day as _last_day
from paperpull_core.dates import checked as _checked_date
from paperpull_core.dates import full_year as _full_year
# re-exported: the docs module calls it as site.set_download_dir
from paperpull_core.capture import set_download_dir  # noqa: F401
from paperpull_core.words import words_for as _words_for
from paperpull_core.characters import whole_characters

log = logging.getLogger("shelbycounty_docs.site")


def _words():
    return _words_for("Shelby County Trustee", sys.modules[__name__])


# ---------------------------------------------------------------------------
# Addresses. The parcel comes from config at startup (configure()).
# ---------------------------------------------------------------------------
BASE = "https://apps2.shelbycountytrustee.com"
PARCEL_PAGE = f"{BASE}/Parcel"
BILLING_URL = PARCEL_PAGE
STATEMENTS_URL = PARCEL_PAGE
TAX_URL = PARCEL_PAGE
URLS = {"home": f"{BASE}/", "login": PARCEL_PAGE, "documents": PARCEL_PAGE, "statements": PARCEL_PAGE, "tax": PARCEL_PAGE}

_PARCEL = ""


def configure(parcel_id: str, owner: str = "") -> None:
    """Point this module at the household's parcel. The id is registered as
    a private word in every spelling, so no diagnostic can carry it."""
    global _PARCEL
    _PARCEL = re.sub(r"\s+", " ", str(parcel_id or "")).strip()
    words = [w for w in (owner, _PARCEL, _PARCEL.replace(" ", ""), _PARCEL.replace(" ", "-")) if w]
    set_private_words(sorted(set(private_words()) | set(words)))
    URLS["login"] = URLS["documents"] = parcel_url() if _PARCEL else PARCEL_PAGE


def is_configured() -> bool:
    return bool(_PARCEL)


def parcel_url() -> str:
    from urllib.parse import quote
    return f"{PARCEL_PAGE}?parcel={quote(_PARCEL)}"


# A public site, so a run never signs in. Landing on a sign-in or account page
# anyway (the payment site, a redirect) is a page this app has no business on.
LOGIN_URL_MARKERS = ["/login", "/signin", "/sign-in", "/account/login", "/authorize", "payit901"]

FORBIDDEN_CONTROL_RE = re.compile(
    r"(\bpay\b|\bpaying\b|\bpayments?\b|make\s+(a\s+)?payment|\bpayit\b|\bpayit901\b|\bcart\b|"
    r"\bcheck\s*out\b|\bcheckout\b|\bproceed\b|\bcontinue\b|\bwallet\b|\be-?check\b|\bcard\b|"
    r"\bmanaged\s*pay\b|\bquarterly\b|\barrangement\b|\bpartial\b|\benroll|\bsign\s*up\b|\be-?bill\b|"
    r"\bautopay\b|\bschedul(e|es|ed|ing)\b|\bchange\b|\bowner\s+name\b|\bappeal\b|\bfreeze\b|\brelief\b|"
    r"\bappl(y|ies|ied|ication)\b|\bbid\b|\btax\s+sale\b|\bredeem\b|\bregister\b|\bnewsletter\b|"
    r"\bnotify\b|\bsubscribe\b|\bexternal\b|\bgis\b|\blegal\b|\bdescription\b|\bsearch\b|\bowner\b|"
    r"\bparcel\b|\bcolumns?\b|\brows\b|\bsubmit\b|\bconfirm\b|\byes\b|\bagree\b|\baccept\b|"
    r"\bauthori[sz]e\b|\bdelete\b|\bremove\b|\bcancel\b|\bclose\b|\bedit\b|\bupdate\b|\bsettings?\b|"
    r"\bprofile\b|\bemail\b|\bshare\b|\bchat\b|\bcontact\b|\bmy\s+account\b|\bback\b|\bhome\b)", re.I)

SAFE_DOC_CONTROL_RE = re.compile(
    r"(^\s*(?:(?:print|view|download)\s+)?(?:property\s+tax\s+)?(?:receipt|notice)\b(?:\s+balances?\s+due)?\s*$|"
    r"^\s*next\s*$|^\s*previous\s*$)", re.I)

BILL_CONTROL_RE = re.compile(r"^\s*print\s+(receipt|notice)\b", re.I)

SECURITY_CHALLENGE_MARKERS = ["are you a robot", "captcha", "access denied"]
RATE_LIMIT_MARKERS = ["too many requests", "rate limit", "try again later", "temporarily unavailable", "http error 429"]
# What the page says when its data did not come. "No transactions for selected
# tax year" is a valid empty answer and is not among these.
DATA_ERROR_MARKERS = ["failed to fetch", "data retrieval error", "error retrieving", "something went wrong"]

FALLBACK = {
    "doc_row": "table tbody tr",
    "doc_link": "a[href*='Transaction?billNumberData=']",
    "download_control": "a:has-text('Print Receipt'), button:has-text('Print Notice')",
    "page_ready": "table",
    "next_page": "button:has-text('NEXT')",
}

# ---------------------------------------------------------------------------
# Date parsing (shared shape with the other apps)
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


# ---------------------------------------------------------------------------
# Session / safety
# ---------------------------------------------------------------------------



def looks_signed_out(page) -> bool:
    """There is nothing to sign in to, so a sign-in address or a password
    field means the tab is not on the lookup at all. A page that cannot say
    where it is raises, which the core treats as a refusal."""
    url = (page.url or "").lower()
    if any(m in url for m in LOGIN_URL_MARKERS):
        return True
    try:
        if page.locator("input[type='password']").count() > 0:
            return True
    except Exception:
        pass
    return False


def _body_text(page, limit: int = 4000) -> str:
    try:
        return (page.locator("body").inner_text(timeout=5000) or "")[:limit].lower()
    except Exception:
        return ""


def detect_security_challenge(page) -> Optional[str]:
    """A robot check or throttling notice, or the page saying its data did
    not come. Visible text only."""
    hay = _body_text(page, 2500)
    for m in SECURITY_CHALLENGE_MARKERS:
        if m in hay:
            return f"Security challenge detected: '{m}'"
    for m in RATE_LIMIT_MARKERS:
        if m in hay:
            return f"Possible rate limiting detected: '{m}'"
    return None


def is_safe_control(name: str) -> bool:
    """Deny by default: an unreadable label is refused, then this app's
    blocklist, then the shared core guards, and only then the allowlist,
    which here names only Print Receipt, Print Notice, NEXT and PREVIOUS."""
    name = re.sub(r"\s+", " ", name or "").strip()
    if not name:
        return False
    if FORBIDDEN_CONTROL_RE.search(name):
        return False
    if SETTINGS_CONTROL_RE.search(name) or AUTH_CONTROL_RE.search(name):
        return False
    return bool(SAFE_DOC_CONTROL_RE.search(name))


# ---------------------------------------------------------------------------
# Hosts. One exact host for pages; the same origin, exactly, for the blob a
# press makes. The payment site is on neither list.
# ---------------------------------------------------------------------------
ALLOWED_HOSTS = {"apps2.shelbycountytrustee.com"}
DOWNLOAD_HOSTS = {"apps2.shelbycountytrustee.com"}
BLOB_ORIGIN = "https://apps2.shelbycountytrustee.com"
DOCUMENT_PATH_RE = re.compile(r"(?!)")   # matches nothing: no document here has a path of its own


def document_id_of(path: str) -> str:
    return ""


def is_safe_url(url: str) -> bool:
    """True only for an https URL on exactly this provider's host."""
    return _host_allows(url, ALLOWED_HOSTS, subdomains=False)


def is_download_url(url: str) -> bool:
    """True only for a blob: URL whose origin is exactly this provider's."""
    u = str(url or "")
    if not u.startswith("blob:"):
        return False
    try:
        parts = urlsplit(u[len("blob:"):])
    except ValueError:
        return False
    return (parts.scheme == "https" and (parts.hostname or "").lower() == "apps2.shelbycountytrustee.com"
            and parts.port is None and not parts.username)


class ListStopped(Exception):
    """The list has a part this could not read, so what was read is not all
    of it. `docs` holds what was read before it stopped."""

    def __init__(self, why: str, docs=None):
        super().__init__(why)
        self.docs = list(docs or [])


def tabs_now(page) -> set:
    """The tabs open in the browser before a navigation or a press, so
    settled_here can tell a tab that opened from one that was already there
    (the panel's own sign-in tab, a tab left from an earlier run)."""
    try:
        return set(page.context.pages)
    except Exception:
        return set()


def settled_here(page, what: str = "the page", before: Optional[set] = None) -> None:
    """After a navigation or a press: the tab is still on this host and no
    tab has opened since `before`. Anything else is a run that stops; a tab
    that opened is closed first, since it may be the payment site. With no
    `before`, every other tab counts as opened."""
    extra = []
    try:
        extra = [p for p in page.context.pages if p is not page and (before is None or p not in before)]
    except Exception:
        pass
    for p in extra:
        try:
            p.close()
        except Exception:
            pass
    if extra:
        raise ListStopped("%s opened another tab, which was closed" % what)
    if not is_safe_url(page.url or ""):
        raise ListStopped("%s settled off the Trustee's lookup" % what)


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
    # The tax year and, for a receipt, the row's date, which together are
    # how the document is found again. Never a bill or receipt number.
    tax_year: str = ""


_ISO_RE = re.compile(r"^(?:19|20)\d{2}-\d{2}-\d{2}$")
_MDY_RE = re.compile(r"^(\d{1,2})/(\d{1,2})/((?:19|20)\d{2})$")
_YEAR4_RE = re.compile(r"^(?:19|20)\d{2}$")
_FOOTER_RE = re.compile(r"PAGE\s+(\d+)\s+OF\s+(\d+).*?TOTAL\s+RECORDS:\s*(\d+)", re.I | re.S)
_RECEIPT_TITLE_RE = re.compile(r"^Property Tax Receipt Tax Year ((?:19|20)\d{2})(?: \(#(\d{4})\))?$")
_NOTICE_TITLE_RE = re.compile(r"^Property Tax Notice Tax Year ((?:19|20)\d{2})$")


def valid_iso(text: str) -> bool:
    t = (text or "").strip()
    if not _ISO_RE.match(t):
        return False
    try:
        return _date.fromisoformat(t).isoformat() == t
    except ValueError:
        return False


def mdy_to_iso(text: str) -> str:
    """"11/23/2016" -> "2016-11-23", or "" when it is not a calendar date."""
    m = _MDY_RE.match((text or "").strip())
    if not m:
        return ""
    try:
        return _date(int(m.group(3)), int(m.group(1)), int(m.group(2))).isoformat()
    except ValueError:
        return ""


def footer_counts(text: str) -> Optional[Tuple[int, int, int]]:
    """(page, pages, total records) from a table's footer text, or None."""
    m = _FOOTER_RE.search((text or "").replace("\n", " "))
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


# The two tables, read as cells. Each row also says whether it carries a
# Transaction link (a bill) or a Print Receipt link (a receipt); the link's
# address is never returned to Python by this reader.
_ROWS_JS = r"""() => [...document.querySelectorAll('table tbody tr')].map((tr, i) => ({
  i: i,
  cells: [...tr.querySelectorAll('td')].map(td => (td.innerText || '').replace(/\s+/g, ' ').trim()),
  hasBillLink: !!tr.querySelector("a[href*='Transaction?billNumberData=']"),
  hasPrintReceipt: !!tr.querySelector('a'),
  printLabel: (tr.querySelector('a') ? (tr.querySelector('a').innerText || '') : '').replace(/\s+/g, ' ').trim()
}))"""
_FOOTER_JS = r"""() => { const b = document.body ? (document.body.innerText || '') : ''; const i = b.search(/PAGE\s+\d+\s+OF\s+\d+/i); return i < 0 ? '' : b.slice(i, i + 200); }"""


def _rows(page) -> list:
    try:
        return page.evaluate(_ROWS_JS) or []
    except Exception:
        return []


def _footer(page) -> Optional[Tuple[int, int, int]]:
    try:
        return footer_counts(page.evaluate(_FOOTER_JS) or "")
    except Exception:
        return None


def _press_next(page) -> bool:
    """Press the table's NEXT once. False when it is disabled or absent.
    ListStopped when it is refused or the rows did not change."""
    loc = page.get_by_role("button", name=re.compile(r"^\s*next\s*$", re.I))
    try:
        if loc.count() == 0 or loc.first.is_disabled():
            return False
        label = (loc.first.inner_text(timeout=1000) or "").strip()
    except Exception as e:
        raise ListStopped("the table's NEXT could not be read (%s)" % type(e).__name__)
    if not is_safe_control(label):
        raise ListStopped("the guard refused the table's NEXT")
    before = _rows(page)
    tabs = tabs_now(page)
    try:
        # A NEXT turned off where the footer says more pages stops the run
        # (core STOPS), since the rest of the list cannot be read.
        pressing.click(page, loc.first, css=pressing.BUTTONS, what="the table's NEXT", words=_words(),
                       step="page the table")
    except pressing.Stop:
        raise
    except Exception as e:
        raise ListStopped("the table's NEXT could not be pressed (%s)" % type(e).__name__)
    settled_here(page, "pressing NEXT", tabs)
    for _ in range(30):
        page.wait_for_timeout(300)
        if _rows(page) != before:
            return True
    raise ListStopped("the rows stayed the same after NEXT was pressed")


def read_whole_table(page, what: str) -> list:
    """Every row of the table on the page, page by page through NEXT, and
    only when the footer's counts agree: the last page reached and as many
    rows read as TOTAL RECORDS says. A table without a footer, or one whose
    counts do not add up, stops the list. An empty table ("No transactions")
    is a valid answer and comes back as []."""
    rows: list = []
    footer = _footer(page)
    first = _rows(page)
    if footer is None:
        if not first and says_no_rows(page):
            return []
        raise ListStopped("the %s table shows no PAGE / TOTAL RECORDS footer" % what)
    page_no, pages, total = footer
    if page_no != 1:
        raise ListStopped("the %s table starts at page %d, not its first" % (what, page_no))
    if pages < 1 or total < 0:
        raise ListStopped("the %s table's footer makes no sense" % what)
    for expected in range(1, 201):
        now_no, now_pages, now_total = footer
        if (now_no, now_pages, now_total) != (expected, pages, total):
            raise ListStopped("the %s table's footer changed while paging" % what)
        rows.extend(_rows(page))
        if now_no >= pages:
            break
        if not _press_next(page):
            raise ListStopped("the %s table says more pages but NEXT is off" % what)
        footer = _footer(page)
        if footer is None:
            raise ListStopped("the %s table lost its footer while paging" % what)
    else:
        raise ListStopped("the %s table runs past 200 pages" % what)
    if len(rows) != total:
        raise ListStopped("the %s table read %d rows where it says %d" % (what, len(rows), total))
    return rows


_NO_ROWS_RE = re.compile(r"no transactions|no records|no payment", re.I)


def says_no_rows(page) -> bool:
    """The page says, in words, that the table is empty."""
    return bool(_NO_ROWS_RE.search(_body_text(page, 4000)))


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

def _wait_for_table(page, timeout_ms: int = 30000) -> bool:
    """The table's first row, or the page saying in words that it is empty.
    One selector engine at a time: Playwright reads "a, text=b" as CSS and
    refuses it."""
    try:
        page.wait_for_selector("table tbody tr", timeout=timeout_ms)
        return True
    except Exception:
        return says_no_rows(page)


def _data_error(page) -> Optional[str]:
    hay = _body_text(page, 3000)
    for m in DATA_ERROR_MARKERS:
        if m in hay:
            return m
    return None


def landed_on_parcel(url: str) -> bool:
    """Whether this address is the configured parcel's own page: the lookup's
    host, the Parcel path, and exactly one parcel value equal to the one in
    config.json. A redirect to any other parcel's page, or to the bare
    lookup, is not the documents page, whatever it shows."""
    from urllib.parse import urlsplit, parse_qs
    if not is_configured() or not is_safe_url(url):
        return False
    parts = urlsplit(url)
    if parts.path.rstrip("/") != "/Parcel":
        return False
    seen = parse_qs(parts.query).get("parcel", [])
    return len(seen) == 1 and re.sub(r"\s+", " ", seen[0]).strip() == _PARCEL


def goto_documents(page) -> bool:
    """Open the parcel's page by its address, and say it is open only when
    the page landed on that parcel. No click. With no parcel configured the
    bare lookup is opened, which carries no parcel's data, and the answer
    is no."""
    if not is_configured():
        log.error("parcel_id is empty in config.json, so there is no documents page to open")
    before = tabs_now(page)
    try:
        page.goto(parcel_url() if is_configured() else PARCEL_PAGE,
                  wait_until="domcontentloaded", timeout=60000)
    except Exception as e:
        log.info("opening the parcel page failed (%s)", type(e).__name__)
        return False
    try:
        settled_here(page, "opening the parcel page", before)
    except ListStopped as stop:
        log.info("%s", stop)
        return False
    if not landed_on_parcel(page.url or ""):
        log.info("the page did not land on the configured parcel")
        return False
    if not _wait_for_table(page):
        return False
    _register_page_words(page)
    return _data_error(page) is None


def forms_page_links_statements(page) -> bool:
    """What the login check asks: the parcel page shows its billing table."""
    return bool(_rows(page))


_LABELLED_JS = r"""(label) => { const b = document.body ? document.body.innerText : ''; const re = new RegExp(label + '\\s*\\n\\s*([^\\n]+)', 'i'); const m = b.match(re); return m ? m[1].trim() : ''; }"""


def _register_page_words(page) -> None:
    """The owner and location the parcel page prints join the private
    words, so a survey or a failure file cannot carry them."""
    words = []
    for label in ("PRIMARY OWNER", "LOCATION", "MAILING ADDRESS"):
        try:
            v = page.evaluate(_LABELLED_JS, label) or ""
        except Exception:
            v = ""
        if v:
            words.append(v)
            words += [w for w in re.split(r"[\s,]+", v) if len(w) >= 4 and not w.isdigit()]
    base = [w for w in (_PARCEL, _PARCEL.replace(" ", ""), _PARCEL.replace(" ", "-")) if w]
    set_private_words(sorted(set(private_words()) | set(base) | set(words)))


def scroll_full_page(page, rounds: int = 4, delay_ms: int = 400) -> None:
    try:
        for _ in range(rounds):
            page.mouse.wheel(0, 3000)
            page.wait_for_timeout(delay_ms)
    except Exception:
        pass


def expand_all(page) -> None:
    return None


def balance_due(page) -> bool:
    """Whether the parcel page shows a non-zero TOTAL BALANCE."""
    try:
        v = page.evaluate(_LABELLED_JS, "TOTAL BALANCE") or ""
    except Exception:
        return False
    return bool(re.search(r"[1-9]", re.sub(r"[^\d.]", "", v)))


def bill_rows(rows: list) -> List[dict]:
    """The billing table's rows as {year, i}; a row without a 4-digit year
    or a Transaction link, or two rows for one year, stops the list."""
    out = []
    seen = set()
    for r in rows:
        cells = r.get("cells") or []
        if len(cells) < 2 or not r.get("hasBillLink"):
            raise ListStopped("a billing row has no bill link")
        year = cells[1].strip()
        if not _YEAR4_RE.match(year):
            raise ListStopped("a billing row's year is not a year")
        if year in seen:
            raise ListStopped("two bills for tax year %s" % year)
        seen.add(year)
        out.append({"year": year, "i": int(r.get("i", -1))})
    return out


def receipt_docs(rows: list, year: str) -> List[RawDoc]:
    """One RawDoc per receipt row of a Transaction page: title names the
    tax year, date is the row's own date. A row without a calendar date or
    a Print Receipt link, or two receipts on one date for one year, stops
    the list, since the page shows nothing else that tells them apart."""
    parsed = []
    for r in rows:
        cells = r.get("cells") or []
        if len(cells) < 3:
            raise ListStopped("a receipt row has too few cells")
        if not r.get("hasPrintReceipt") or not BILL_CONTROL_RE.match(r.get("printLabel") or ""):
            raise ListStopped("a receipt row has no Print Receipt link")
        iso = mdy_to_iso(cells[2])
        if not iso:
            raise ListStopped("a receipt row's date is not a calendar date")
        parsed.append((iso, re.sub(r"\D", "", cells[1])[-4:]))
    by_date: dict = {}
    for iso, _ in parsed:
        by_date[iso] = by_date.get(iso, 0) + 1
    out: List[RawDoc] = []
    seen = set()
    for iso, last4 in parsed:
        title = f"Property Tax Receipt Tax Year {year}"
        if by_date[iso] > 1:
            # Two payments on one day: the receipt number's last four tell
            # them apart, and only then is any part of it written down.
            if len(last4) != 4:
                raise ListStopped("two receipts on %s for tax year %s and no receipt number to tell them apart" % (iso, year))
            title += f" (#{last4})"
        if (iso, title) in seen:
            raise ListStopped("two receipts on %s for tax year %s share a receipt number ending" % (iso, year))
        seen.add((iso, title))
        out.append(RawDoc(title=title, date_text=iso, text=f"Shelby County Trustee receipt {year}", kind="tax", tax_year=year))
    return out


def _open_bill(page, index: int) -> None:
    """Open the Transaction page of the billing row at `index` by the
    address its own link carries, read in the page and handed to goto
    without passing through any log."""
    href = page.evaluate("(i) => { const tr = document.querySelectorAll('table tbody tr')[i]; const a = tr && tr.querySelector(\"a[href*='Transaction?billNumberData=']\"); return a ? a.getAttribute('href') : ''; }", index)
    if not href:
        raise ListStopped("a billing row's link could not be read")
    url = href if href.startswith("http") else BASE + "/" + href.lstrip("/")
    if not is_safe_url(url):
        raise ListStopped("a billing row links off the Trustee's lookup")
    tabs = tabs_now(page)
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
    except Exception as e:
        raise ListStopped("a bill's Transaction page did not open (%s)" % type(e).__name__)
    settled_here(page, "opening a bill's Transaction page", tabs)
    if not _wait_for_table(page, 20000):
        raise ListStopped("a bill's Transaction page showed neither its table nor an empty-state notice")
    err = _data_error(page)
    if err:
        raise ListStopped("the Transaction page says %r" % err)


def _back_to_parcel(page) -> None:
    if not goto_documents(page):
        raise ListStopped("the parcel page did not open again")


def collect_download_docs(page) -> List[RawDoc]:
    """Every receipt of every bill in the parcel's billing history, newest
    tax year first, and the current notice while a balance is due. Nothing
    is pressed but NEXT. Anything unreadable raises ListStopped holding
    what was read."""
    if not goto_documents(page):
        raise ListStopped("the parcel page did not open")
    docs: List[RawDoc] = []
    bills = bill_rows(read_whole_table(page, "billing history"))
    if not bills:
        # A parcel always has bills, so no row is a page that did not draw
        # its table, never an empty history ("No payment is due" on the
        # page reads as no rows).
        raise ListStopped("the parcel's billing history shows no bill")
    if balance_due(page):
        newest = max(b["year"] for b in bills)
        docs.append(RawDoc(title=f"Property Tax Notice Tax Year {newest}", date_text=f"{newest}-12-31",
                           text=f"Shelby County Trustee notice {newest}", kind="tax", tax_year=newest))
    for b in sorted(bills, key=lambda x: x["year"], reverse=True):
        try:
            _back_to_parcel(page)
            idx = _bill_index(page, b["year"])
            _open_bill(page, idx)
            docs.extend(receipt_docs(read_whole_table(page, "payment history"), b["year"]))
        except ListStopped as stop:
            stop.docs = docs + stop.docs
            raise
    return docs


def _row_matches(r: dict, iso: str, last4: str) -> bool:
    cells = r.get("cells") or []
    if len(cells) < 3 or mdy_to_iso(cells[2]) != iso:
        return False
    return not last4 or re.sub(r"\D", "", cells[1])[-4:] == last4


def _receipt_index(page, iso: str, last4: str = "") -> int:
    """The current payment-history row index of the one receipt dated
    `iso` (and, when given, whose receipt number ends in `last4`), paging
    to it with NEXT. Exactly one row on that page must match."""
    for _ in range(200):
        hits = [r for r in _rows(page) if _row_matches(r, iso, last4)]
        if len(hits) > 1:
            raise ListStopped("two receipts dated %s on one page" % iso)
        if hits:
            return int(hits[0]["i"])
        if not _press_next(page):
            break
    raise ListStopped("no receipt dated %s in the payment history" % iso)


def _bill_index(page, year: str) -> int:
    """The current billing-table row index for tax year `year`, paging to
    it with NEXT. Exactly one row must carry the year."""
    for _ in range(50):
        hits = [r for r in _rows(page) if len(r.get("cells") or []) > 1 and r["cells"][1].strip() == year]
        if len(hits) > 1:
            raise ListStopped("two bills for tax year %s" % year)
        if hits:
            return int(hits[0]["i"])
        if not _press_next(page):
            break
    raise ListStopped("no bill for tax year %s on the billing history" % year)


# ---------------------------------------------------------------------------
# The press and the blob it makes
# ---------------------------------------------------------------------------
_ARM_JS = r"""() => {
  window.__pp = {blobs: [], opened: []};
  const oc = URL.createObjectURL.bind(URL);
  URL.createObjectURL = function (b) { const u = oc(b); window.__pp.blobs.push({blob: b, type: (b && b.type) || '', size: (b && b.size) || 0, url: String(u)}); return u; };
  window.open = function (u, t, f) { window.__pp.opened.push(String(u)); return null; };
}"""
_RESULT_JS = r"""async () => {
  const s = window.__pp || {blobs: [], opened: []};
  const out = {blobs: s.blobs.map(b => ({type: b.type, size: b.size, url: b.url})), opened: s.opened.slice(), b64: ''};
  if (s.blobs.length === 1) {
    const bytes = await ppBlob(s.blobs[0].blob);
    let bin = ''; for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
    out.b64 = btoa(bin);
  }
  return out;
}"""


def _arm_blob_hook(page) -> None:
    page.evaluate(_ARM_JS)


def accept_blob(result: dict) -> Tuple[bytes, str]:
    """(bytes, "") when exactly one Blob was made, of type application/pdf,
    on this host's origin, asked to open at that same address, with bytes
    that start with %PDF-. Otherwise (b"", why)."""
    blobs = list(result.get("blobs") or [])
    opened = list(result.get("opened") or [])
    if len(blobs) != 1:
        return b"", "%d blobs were made" % len(blobs)
    b = blobs[0]
    if str(b.get("type") or "") != "application/pdf":
        return b"", "the blob's type is not application/pdf"
    if not is_download_url(str(b.get("url") or "")):
        return b"", "the blob is not on this host's origin"
    if len(opened) != 1 or opened[0] != b.get("url"):
        return b"", "the page asked to open %d addresses, not the blob" % len(opened)
    try:
        data = intake.decode(result.get("b64") or "")
    except Exception:
        return b"", "the blob's bytes could not be read"
    if data[:5] != b"%PDF-":
        return b"", "the blob is not a PDF"
    return data, ""


def pdf_text(data: bytes) -> str:
    """The text a PDF prints, read with pypdf, with the raw bytes added
    behind it. The lookup builds its PDFs with jsPDF, uncompressed, so even
    a page pypdf cannot read still carries its printed text in the bytes."""
    text = ""
    try:
        text = whole_characters("\n".join(pdf_reader.page_texts(data)))
    except Exception as e:
        log.info("the PDF's text could not be read with pypdf (%s)", type(e).__name__)
    return text + "\n" + data.decode("latin-1", "replace")


def pdf_names_receipt(data: bytes, date_text: str, receipt_no: str) -> str:
    """Why the PDF is not the receipt row that was pressed, or "" when its
    text carries the row's date and its receipt number. Printed dates may
    pad the month and day or not, so all four spellings are looked for,
    with any whitespace the text puts between runs allowed inside the
    number and the date."""
    digits = re.sub(r"\D", "", receipt_no or "")
    if not digits:
        return "the row carries no receipt number"
    m = re.match(r"^\s*(\d{1,2})/(\d{1,2})/(\d{4})\s*$", date_text or "")
    if not m:
        return "the row's date is not one this can look for"
    mo, d, y = (int(m.group(1)), int(m.group(2)), m.group(3))
    text = pdf_text(data)
    date_re = re.compile(r"\b0?%d\s*/\s*0?%d\s*/\s*%s\b" % (mo, d, y))
    if not date_re.search(text):
        return "the PDF does not name the receipt's date"
    number_re = re.compile(r"(?<!\d)" + r"\s*".join(digits) + r"(?!\d)")
    if not number_re.search(text):
        return "the PDF does not name the receipt's number"
    return ""


def pdf_names_notice(data: bytes, year: str) -> str:
    """Why the PDF is not the tax notice for `year`, or ""."""
    text = pdf_text(data)
    if not re.search(r"notice", text, re.I):
        return "the PDF does not read as a notice"
    if not re.search(r"(?<!\d)%s(?!\d)" % re.escape(str(year or "")), text):
        return "the PDF does not name the tax year"
    return ""


def _press_for_blob(page, control, label: str, out_path: Path, trace: Optional[list],
                    css: str = pressing.LINKS, expect=None) -> bool:
    if not is_safe_control(label):
        if trace is not None:
            trace.append({"note": "control refused by the guard"})
        return False
    _arm_blob_hook(page)
    tabs = tabs_now(page)
    try:
        pressing.click(page, control, css=css, what=label, words=_words(),
                       step="press a document's print control")
    except pressing.TurnedOff:
        # One row's control turned off leaves that document for review and
        # the run goes on to the next.
        log.info("the print control is turned off on the page, so nothing was pressed and the "
                 "document is left for review")
        if trace is not None:
            trace.append({"note": "print control turned off"})
        return False
    except pressing.Stop:
        raise
    except Exception as e:
        if trace is not None:
            trace.append({"note": "click failed", "error": type(e).__name__})
        return False
    # The capture is read only once it has held still: the same count of
    # blobs and of open requests across three polls half a second apart,
    # after the first blob came. A second blob or a late open therefore
    # lands in the capture and is refused, instead of arriving after the
    # first one was taken.
    seen = (0, 0); still = 0
    for _ in range(40):
        page.wait_for_timeout(500)
        try:
            now = tuple(page.evaluate("() => [(window.__pp && window.__pp.blobs.length) || 0, (window.__pp && window.__pp.opened.length) || 0]"))
        except Exception:
            now = (0, 0)
        if now[0] and now == seen:
            still += 1
            if still >= 3:
                break
        else:
            still = 0
        seen = now
    try:
        settled_here(page, "the press", tabs)
    except ListStopped as stop:
        if trace is not None:
            trace.append({"note": "stopped after the press", "why": str(stop)})
        return False
    try:
        result = intake.evaluate(page, _RESULT_JS)
    except Exception as e:
        if trace is not None:
            trace.append({"note": "the blob could not be read", "error": type(e).__name__})
        return False
    data, why = accept_blob(result or {})
    made = list((result or {}).get("blobs") or [{}])
    if trace is not None:
        trace.append({"note": "blob accepted" if data else "blob refused", "why": why,
                      "count": len(made) if made != [{}] else 0, "type": str(made[0].get("type", ""))[:30]})
    if not data:
        return False
    # The PDF has to be the document that was pressed: its own text names
    # the row's date and receipt number (or the notice's tax year).
    wrong = expect(data) if expect else ""
    if wrong:
        if trace is not None:
            trace.append({"note": "pdf refused", "why": wrong})
        log.info("the PDF was not kept: %s", wrong)
        return False
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(data)
    return True


def download_bill(page, dl_dir, iso_date: str, out_path, title: str = "",
                  trace: Optional[list] = None, href: str = "") -> bool:
    """Save one document: a receipt by its tax year and date, found again on
    its bill's Transaction page and taken by pressing its own Print Receipt
    under the blob hook; or the notice by pressing Print Notice on the
    parcel page while a balance is due.

    A parcel page that will not open again, a billing history with no bill
    or a table that cannot be read whole raises ListStopped, as it does for
    discovery, since every document after this one reads the same pages."""
    out_path = Path(out_path)
    t = (title or "").strip()
    try:
        m = _NOTICE_TITLE_RE.match(t)
        if m:
            _back_to_parcel(page)
            if not balance_due(page):
                log.info("no balance is due, so there is no notice to print")
                return False
            # Print Notice prints the newest bill's notice, so a notice
            # listed for an older year is not pressed for.
            bills = bill_rows(read_whole_table(page, "billing history"))
            if not bills:
                raise ListStopped("the parcel's billing history shows no bill")
            if max(b["year"] for b in bills) != m.group(1):
                log.info("the newest bill is not this notice's tax year, none pressed")
                if trace is not None:
                    trace.append({"note": "notice year is not the newest bill's"})
                return False
            btn = page.get_by_role("button", name=re.compile(r"^\s*print\s+notice\b", re.I))
            if btn.count() != 1 or btn.first.is_disabled():
                log.info("Print Notice is not a single enabled control")
                return False
            return _press_for_blob(page, btn.first, (btn.first.inner_text(timeout=1000) or "").split("\n")[0],
                                   out_path, trace, css=pressing.BUTTONS, expect=lambda d: pdf_names_notice(d, m.group(1)))
        m = _RECEIPT_TITLE_RE.match(t)
        if not m or not valid_iso(iso_date):
            log.info("not a title and date this app knows how to fetch")
            return False
        year, last4 = m.group(1), m.group(2) or ""
        _back_to_parcel(page)
        bill_idx = _bill_index(page, year)
        _open_bill(page, bill_idx)
        # The whole payment history, read through its footer, has to carry
        # the date (and receipt-number ending) exactly once before anything
        # is pressed.
        rows = read_whole_table(page, "payment history")
        hits = [r for r in rows if _row_matches(r, iso_date, last4)]
        if len(hits) != 1:
            log.info("%d receipt rows carry this date, none pressed", len(hits))
            if trace is not None:
                trace.append({"note": "no single receipt row for the date", "matches": len(hits)})
            return False
        # Then the page is opened again at its first page and the row found
        # on the page it sits on, since a row's index is its own page's.
        _back_to_parcel(page)
        _open_bill(page, _bill_index(page, year))
        row_idx = _receipt_index(page, iso_date, last4)
        link = page.locator("table tbody tr").nth(row_idx).get_by_role("link", name=re.compile(r"^\s*print\s+receipt\s*$", re.I))
        if link.count() != 1:
            return False
        cells = hits[0].get("cells") or []
        return _press_for_blob(page, link.first, (link.first.inner_text(timeout=1000) or ""), out_path, trace,
                               css=pressing.LINKS, expect=lambda d: pdf_names_receipt(d, cells[2], cells[1]))
    except ListStopped as stop:
        log.info("the list stopped while looking for the document: %s", stop)
        raise


# ---------------------------------------------------------------------------
# Diagnose: a survey with the private words taken out, no screenshot.
# ---------------------------------------------------------------------------

def collect_documents(page) -> List[RawDoc]:
    out: List[RawDoc] = []
    for r in _rows(page)[:40]:
        cells = r.get("cells") or []
        out.append(RawDoc(title=redact(" | ".join(cells))[:120], date_text=mdy_to_iso(cells[2]) if len(cells) > 2 else "",
                          text=redact(" | ".join(cells))[:200], row_index=int(r.get("i", -1))))
    return out


def _page_summary(page) -> dict:
    out = {"url": redact(urlsplit(page.url or "").path), "title": ""}
    try:
        out["title"] = redact(page.title() or "")
    except Exception:
        pass
    try:
        out["headings"] = [redact(h.strip())[:60] for h in page.locator("h1, h2, h3").all_inner_texts() if h.strip()][:20]
    except Exception:
        out["headings"] = []
    controls = []
    for role in ("link", "button"):
        try:
            loc = page.get_by_role(role)
            for i in range(min(loc.count(), 60)):
                try:
                    text = (loc.nth(i).inner_text(timeout=300) or "").strip()
                except Exception:
                    text = ""
                if text:
                    controls.append({"role": role, "text": redact(text)[:50], "safe": is_safe_control(text),
                                     "bill": bool(BILL_CONTROL_RE.match(text))})
        except Exception:
            pass
    out["controls"] = controls
    out["footer"] = _footer(page)
    return out


def survey(page, dwell_ms: int = 3000, max_follow: int = 0) -> dict:
    """The parcel page's headings, controls with the guard's verdict and
    the table footer. Follows nothing, listens to nothing, no screenshot."""
    report = {"pages": [], "responses": []}
    page.wait_for_timeout(dwell_ms)
    report["pages"].append(_page_summary(page))
    return report
