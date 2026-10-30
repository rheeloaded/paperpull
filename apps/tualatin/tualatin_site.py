"""ALL tualatin.merchanttransact.com selectors, URLs, and page behavior live here.

When the City of Tualatin's billing portal changes, repair this file only.

STATUS: built 2026-10-29 from a signed-in survey of a real account, with
nothing pressed by the app.

SEEN SIGNED IN, 2026-10-29 (shapes only, no values kept):

  * The City of Tualatin's utility bills (water, sewer, stormwater, parks
    and road fees) are on CivicPay Online at
    https://tualatin.merchanttransact.com/. Its session is a cookie, so a
    page is opened by its address.
  * /secure/Activity draws one table headed Transaction Date | Transaction
    Type | Description | Amount | Balance, a row per transaction, Billing
    and Payment alike (48 rows seen, 24 bills). A Billing row links to its
    bill, /secure/MyBill/<bill number>.
  * A bill's Print My Bill link, /secure/MyBill/<bill number>/Print, is an
    HTML page, not a PDF: the printed bill, with Bill Details, Billing Date,
    Due Date, the charges, Total Amount Due and the meter readings.
  * So a run reads Activity, fetches each bill's print page from inside the
    signed-in page with its stylesheets and images from the portal host
    written into it, and draws it as a PDF with every script, frame and
    form taken out, offline (paperpull_core.receipt_pdf.print_html_inert_to_pdf).
    Drawn without its stylesheet, the page lost the look of the bill. Nothing
    is clicked. A bill is known by its bill number.

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
import json
import re
import sys
from dataclasses import dataclass
from datetime import date as _date
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import parse_qs, urlencode, urlsplit

from paperpull_core import intake
from paperpull_core.controls import SETTINGS_CONTROL_RE, AUTH_CONTROL_RE
from paperpull_core.redact import private_words, redact, set_private_words  # noqa: F401  (re-exported)
from paperpull_core.urls import is_safe_url as _host_allows
from paperpull_core.dates import last_day as _last_day
from paperpull_core.dates import checked as _checked_date
from paperpull_core.dates import full_year as _full_year
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


# A bill row's statement date, exactly as the table writes it: "Sep 12, 2026".
_DUE_DATE_RE = _STATEMENT_DATE_RE = re.compile(
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
    """tualatin.merchanttransact.com answered as a signed-out session: its sign-in page,
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
# Words every printed bill carries, read before the page is drawn as a PDF.
PRINT_MARKERS = ("Bill Details", "Billing Date", "Total Amount Due")
MAX_PAGE_BYTES = 5 * 1024 * 1024


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
  let table = null, heads = [];
  for (const t of document.querySelectorAll('table')) {
    const h = [...t.querySelectorAll('th')].map(text);
    if (h.some(x => /^transaction date$/i.test(x))) { table = t; heads = h; break; }
  }
  const account = [...document.querySelectorAll('h1,h2,h3,h4')].map(text).filter(s => /[0-9]/.test(s));
  if (!table) return {table: false, account: account};
  const rows = [...table.querySelectorAll('tbody tr')].map(tr => ({
    cells: [...tr.cells].map(text),
    bills: [...tr.querySelectorAll('a[href]')].map(a => a.getAttribute('href')).filter(h => /\/secure\/MyBill\//.test(h))
  }));
  return {table: true, heads: heads, rows: rows, account: account};
}"""


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
        page.wait_for_selector("table tbody tr", timeout=timeout_ms)
    except Exception:
        if looks_signed_out(page):
            raise SessionExpired("the payment portal showed its sign-in page")
        raise ListStopped("the Activity table did not finish loading")
    try:
        seen = page.evaluate(_ROWS_JS) or {}
    except Exception as e:
        raise ListStopped(f"the Activity table could not be read ({type(e).__name__})")
    if not seen.get("table"):
        raise ListStopped("Activity shows no transaction table")
    _keep_private(seen.get("account"))
    return seen


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
    dated by the row's Transaction Date. Payments are passed over. A header
    with no single Transaction Date or Transaction Type column, a Billing
    row with no single bill link, a link that is not a bill's, a date that
    is not a calendar date, or one bill number twice stops the list,
    carrying what was read before it."""
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
        if cells[at_type] != "Billing":
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
    try:
        collect_download_docs(page)
        return True
    except (SessionExpired, ListStopped) as e:
        log.info("Activity could not be read: %s", e)
        return False


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


def table_header(page) -> dict:
    """For Diagnose, the Activity table's header cells as read."""
    try:
        seen = page.evaluate(_ROWS_JS) or {}
    except Exception:
        seen = {}
    heads = [str(h or "") for h in seen.get("heads") or []]
    return {"cells": heads, "statement_date_column": heads.index("Transaction Date") if "Transaction Date" in heads else None}


def collect_download_docs(page) -> List[RawDoc]:
    """Every bill on Activity. Nothing is pressed. A list that cannot be
    read whole raises ListStopped holding what was read, and a signed-out
    portal raises SessionExpired."""
    seen = _open(page)
    return bills_of(seen.get("heads"), seen.get("rows"))


_PRINT_JS = r"""async ([url, host, limit]) => {
  let r;
  try { r = await fetch(url, {credentials: 'include', redirect: 'manual'}); }
  catch (e) { return {status: 0, failed: true}; }
  if (r.type === 'opaqueredirect' || r.redirected) return {status: r.status, redirected: true};
  const type = r.headers.get('content-type') || '';
  let html = '';
  try { html = await ppText(r); } catch (e) { if (ppRefused(e)) throw e; }
  if (r.status !== 200 || !/html/i.test(type)) return {status: r.status, type: type, html: html};
  // The printed bill's own look: its stylesheets and images, fetched from
  // the portal's own host and written into the page, so the offline,
  // script-free drawing shows them without loading anything.
  const doc = new DOMParser().parseFromString(html, 'text/html');
  let spent = 0;
  const own = (href) => { try { const u = new URL(href, url); return u.protocol === 'https:' && u.host === host ? u.href : ''; } catch (e) { return ''; } };
  const inlined = {css: 0, img: 0};
  for (const link of [...doc.querySelectorAll('link[rel~="stylesheet"][href]')]) {
    const at = own(link.getAttribute('href'));
    if (!at) continue;
    try {
      const c = await fetch(at, {credentials: 'include', redirect: 'manual'});
      if (c.status !== 200 || !/css/i.test(c.headers.get('content-type') || '')) continue;
      const text = await c.text();
      spent += text.length;
      if (spent > limit) break;
      const style = doc.createElement('style');
      style.textContent = text;
      link.replaceWith(style);
      inlined.css++;
    } catch (e) {}
  }
  for (const img of [...doc.querySelectorAll('img[src]')]) {
    const at = own(img.getAttribute('src'));
    if (!at) continue;
    try {
      const c = await fetch(at, {credentials: 'include', redirect: 'manual'});
      const kind = c.headers.get('content-type') || '';
      if (c.status !== 200 || !/^image\/(png|jpe?g|gif|webp)/i.test(kind)) continue;
      const blob = await c.blob();
      spent += blob.size;
      if (spent > limit) break;
      img.setAttribute('src', await new Promise((ok, no) => { const f = new FileReader(); f.onload = () => ok(f.result); f.onerror = no; f.readAsDataURL(blob); }));
      inlined.img++;
    } catch (e) {}
  }
  return {status: r.status, type: type, html: '<!doctype html>' + doc.documentElement.outerHTML, inlined: inlined};
}"""


def is_printed_bill(html: str) -> bool:
    """Whether a print page is a bill: every one of PRINT_MARKERS is on it,
    and no password field."""
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html or ""))
    return all(m in text for m in PRINT_MARKERS) and not re.search(r"type=['\"]?password", html or "", re.I)


def _fetch(page, number: str, out_path: Path, trace: Optional[list]) -> bool:
    """Fetch the bill's print page from inside the signed-in page, with its
    own stylesheets and images from the portal host written into it, and
    draw it as a PDF with every script, frame and form taken out, offline
    (receipt_pdf.print_html_inert_to_pdf). A redirect or a refusal is the
    portal saying the session has ended; a page that is not a printed bill
    is refused without a file."""
    from paperpull_core import receipt_pdf
    url = print_url(number)
    if not url:
        return False
    try:
        got = intake.evaluate(page, _PRINT_JS, [url, PORTAL_HOST, MAX_PAGE_BYTES], limit=MAX_PAGE_BYTES) or {}
    except intake.TooLarge:
        return False
    except Exception as e:
        log.info("fetching the bill failed (%s)", type(e).__name__)
        if trace is not None:
            trace.append({"note": "fetch failed", "error": type(e).__name__})
        return False
    if trace is not None:
        trace.append({"note": "fetched", "host": PORTAL_HOST, "status": got.get("status"),
                      "type": str(got.get("type") or "")[:30]})
    if got.get("redirected") or got.get("status") in (401, 403):
        raise SessionExpired("the payment portal's session has ended")
    html = got.get("html") or ""
    if got.get("status") != 200 or "html" not in str(got.get("type") or ""):
        return False
    if not is_printed_bill(html):
        if re.search(r"type=['\"]?password", html, re.I):
            raise SessionExpired("the payment portal answered a bill with its sign-in page")
        log.info("the print page did not read as a bill")
        return False
    try:
        receipt_pdf.print_html_inert_to_pdf(page, html, out_path, base=f"{BASE}/")
    except Exception as e:
        log.info("drawing the bill as a PDF failed (%s)", type(e).__name__)
        return False
    return out_path.is_file() and out_path.read_bytes()[:5] == b"%PDF-"


def download_bill(page, dl_dir, iso_date: str, out_path, title: str = "",
                  trace: Optional[list] = None, href: str = "",
                  document_id: str = "") -> bool:
    """Save the bill discovery recorded with bill number `document_id`,
    dated `iso_date`. Activity is opened again and the bill is fetched only
    when exactly one Billing row there carries that number and date.
    `dl_dir` is unused. Nothing is pressed. SessionExpired propagates."""
    out_path = Path(out_path)
    number = (document_id or "").strip()
    if not BILL_NUMBER_RE.fullmatch(number) or href != bill_path(number):
        log.info("no bill was recorded for this document")
        if trace is not None:
            trace.append({"note": "no recorded bill"})
        return False
    try:
        seen = _open(page)
        found = [d for d in bills_of(seen.get("heads"), seen.get("rows"))
                 if d.document_id == number and d.date_text == (iso_date or "")]
    except ListStopped as stop:
        log.info("the bill list stopped while looking for the bill dated %s: %s", iso_date, stop)
        return False
    if len(found) != 1:
        log.info("%d rows match the recorded bill and date %s, none taken", len(found), iso_date)
        if trace is not None:
            trace.append({"note": "no single row matches the record", "matches": len(found)})
        return False
    return _fetch(page, number, out_path, trace)


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
