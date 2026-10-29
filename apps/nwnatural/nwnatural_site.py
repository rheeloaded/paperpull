"""ALL NW Natural selectors, URLs, and page behavior live here.

When NW Natural or its payment portal changes, repair this file only.

STATUS: built 2026-10-29 from a signed-in survey of a real account, with
nothing pressed by the app.

SEEN SIGNED IN, 2026-10-29 (shapes only, no values kept):

  * NW Natural's bills live on its Paymentus payment portal,
    https://ipn2.paymentus.com/cp/, reached from nwnatural.com after the
    account holder signs in. The session is the portal's cookie plus a
    CSRF_TOKEN every link of the portal carries, so it lives in the tab the
    account holder signed in with: nothing here opens a portal page by
    address.
  * The portal's Bill History link, /cp/bills.action?CSRF_TOKEN=...&
    dateFrom.day=&dateFrom.month=&dateFrom.year=, draws one table headed
    Account | Due Amount | Due Date | Action, a row per bill with a "View"
    link. Asked with an early dateFrom it lists the whole history on one
    page (84 bills, 2019 to 2026), with padding rows of empty cells.
  * A bill's View link, /cp/view-external-bill.action?CSRF_TOKEN=...&
    accountId=&accthid=&accountNumber=&accountNumberHash=&docRef=&
    hashedDocRef=&target=, answers a plain GET with the bill itself:
    application/pdf, a body starting %PDF, no redirect.
  * So a run reads the Bill History link off the open portal page, fetches
    it from inside that page with an early dateFrom, and fetches each bill's
    View address the same way. Nothing is clicked and the tab is not moved.
  * The portal loads DataDome bot protection, which passed the account
    holder's own Chrome. The page warns of a session timeout.

Sign-in, with any verification code, is the account holder's own, in the
browser.

SAFETY (a payment portal that can pay, schedule and enroll):
  This module is strictly READ-ONLY. It presses nothing, fills nothing and
  submits nothing. It must NEVER activate any control that pays, schedules
  or cancels a payment, sets up autopay or Equal Pay, adds a bank account or
  card, enrolls in paperless or any program, starts, stops or moves service,
  changes notifications, or signs out. FORBIDDEN_CONTROL_RE is the guard; a
  control must ALSO match one of the anchored document actions
  (SAFE_DOC_CONTROL_RES), and the shared core guards are consulted every
  time.
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

log = logging.getLogger("nwnatural_docs.site")


def _words():
    """This app's own words for paperpull_core.words."""
    return _words_for("NW Natural", sys.modules[__name__])


# ---------------------------------------------------------------------------
# Addresses
# ---------------------------------------------------------------------------
BASE = "https://www.nwnatural.com"
PORTAL_HOST = "ipn2.paymentus.com"
PORTAL = f"https://{PORTAL_HOST}/cp"
HISTORY_PATH = "/cp/bills.action"
DOCUMENTS_PATH = HISTORY_PATH
DOCUMENTS_URL = PORTAL + "/bills.action"
# What discovery records as every bill's href. A bill's View address holds
# the session's token, so it is never kept: the bill is found again by its
# due date when it is fetched.
DOWNLOAD_PATH = "/cp/view-external-bill.action"
STATEMENTS_URL = DOCUMENTS_URL
BILLING_URL = DOCUMENTS_URL
URLS = {
    # The account holder signs in on nwnatural.com and goes on to the
    # portal from there.
    "home": f"{BASE}/",
    "login": f"{BASE}/",
    "documents": DOCUMENTS_URL,
    "statements": DOCUMENTS_URL,
}

LOGIN_URL_MARKERS = ["/login", "/signin", "/sign-in", "session-expired", "logout"]

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
    r"\bequal\s+pay\b|\bsmart\s+energy\b|\brebates?\b|\bcarbon\s+offset|\bgas\s+leak\b|"
    r"\brebalance\b|\bliquidate\b|\bdetails\b)", re.I)

# The document actions this app would ever accept, anchored whole: the
# portal's own "View Your Detailed Bill PDF", "Download Your Solar Bill" and
# "View Bill", and the "View Utility Bill" its rules name. Nothing looser,
# so a label carrying anything more is refused.
# The one link each bill row offers. This app presses it never; it is named
# here for the survey's verdicts.
SAFE_DOC_CONTROL_RES = (
    re.compile(r"^view$", re.I),
    re.compile(r"^(view|download)\s+(your\s+)?(detailed\s+)?(utility\s+|gas\s+)?bill(\s+\(?pdf\)?)?$", re.I),
)

BILL_CONTROL_RE = re.compile(r"^\s*view\s*$", re.I)

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
    """nwnatural.com answered as a signed-out session: its sign-in page,
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
# Hosts. Exact, parsed, no subdomain wildcard, and a bill only from the one
# PDF address.
# ---------------------------------------------------------------------------
# The site and the account API its signed-in pages fetch from (seen
# 2026-10-29). Exact hosts only; analytics and cookie hosts are not allowed.
# ---------------------------------------------------------------------------
# Hosts. Exact, parsed, no subdomain wildcard.
# ---------------------------------------------------------------------------
# NW Natural's site, where the account holder signs in, and the one
# Paymentus host its bills were seen on (2026-10-29).
ALLOWED_HOSTS = {"www.nwnatural.com", PORTAL_HOST}
BILL_ID_RE = re.compile(r"bill-[0-9]{4}-[0-9]{2}-[0-9]{2}")
# Bill History lists every bill from this day on. A start this early takes
# the whole history the portal keeps (eight years were seen).
HISTORY_FROM = (1, 1, 2000)
MAX_LIST_BYTES = 5 * 1024 * 1024
MAX_PDF_BYTES = 25 * 1024 * 1024


def is_safe_url(url: str) -> bool:
    """True only for an https URL on exactly the Paymentus portal host or
    www.nwnatural.com."""
    return _host_allows(url, ALLOWED_HOSTS, subdomains=False)


def _portal_url(url: str, path: str) -> bool:
    if not is_safe_url(url):
        return False
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    return parts.netloc == PORTAL_HOST and parts.path == path and not parts.fragment


def is_history_url(url: str) -> bool:
    """The portal's own Bill History address, with its CSRF token."""
    if not _portal_url(url, HISTORY_PATH):
        return False
    return "CSRF_TOKEN" in parse_qs(urlsplit(url).query)


def is_download_url(url: str) -> bool:
    """A bill's own View address: the portal host, the view path, the
    session's CSRF token and a document reference."""
    if not _portal_url(url, DOWNLOAD_PATH):
        return False
    q = parse_qs(urlsplit(url).query)
    return all(q.get(k) for k in ("CSRF_TOKEN", "docRef", "hashedDocRef"))


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
    # The bill's View address in this session, CSRF token and all. Valid
    # only while the session lasts, so it is never recorded.
    bill_ref: str = ""


class ListStopped(Exception):
    """The list has a part this could not read, so what was read is not all
    of it. `docs` holds what was read before it stopped."""

    def __init__(self, why: str, docs=None):
        super().__init__(why)
        self.docs = list(docs or [])


def _on_portal(page) -> bool:
    try:
        return urlsplit(page.url or "").netloc == PORTAL_HOST and is_safe_url(page.url or "")
    except ValueError:
        return False


_HISTORY_LINK_JS = r"""() => {
  const a = [...document.querySelectorAll('a[href]')].find(x => x.textContent.trim() === 'Bill History');
  return a ? new URL(a.getAttribute('href'), location.href).href : '';
}"""


def history_url(page) -> str:
    """The Bill History address the open portal page links to, its start
    moved back to HISTORY_FROM, or "" when the page shows no such link."""
    try:
        href = page.evaluate(_HISTORY_LINK_JS) or ""
    except Exception:
        return ""
    if not is_history_url(href):
        return ""
    parts = urlsplit(href)
    q = parse_qs(parts.query, keep_blank_values=True)
    day, month, year = HISTORY_FROM
    q["dateFrom.day"], q["dateFrom.month"], q["dateFrom.year"] = [str(day)], [str(month)], [str(year)]
    url = parts._replace(query=urlencode(q, doseq=True)).geturl()
    return url if is_history_url(url) else ""


_LIST_JS = r"""async ([url]) => {
  let r;
  try { r = await fetch(url, {credentials: 'include', redirect: 'manual'}); }
  catch (e) { return {status: 0, failed: true}; }
  if (r.type === 'opaqueredirect' || r.redirected) return {status: r.status, redirected: true};
  let html = '';
  try { html = await ppText(r); } catch (e) { if (ppRefused(e)) throw e; }
  const doc = new DOMParser().parseFromString(html, 'text/html');
  const text = (el) => (el ? el.textContent : '').replace(/\s+/g, ' ').trim();
  const password = !!doc.querySelector("input[type='password']");
  let table = null, heads = [];
  for (const t of doc.querySelectorAll('table')) {
    const h = [...t.querySelectorAll('thead th, tr:first-child th')].map(text);
    if (h.some(x => /^due date$/i.test(x))) { table = t; heads = h; break; }
  }
  if (!table) return {status: r.status, table: false, password: password};
  const rows = [];
  for (const tr of table.querySelectorAll('tbody tr')) {
    const cells = [...tr.cells].map(text);
    if (!cells.some(Boolean)) continue;
    const views = [...tr.querySelectorAll('a[href]')].filter(a => text(a) === 'View')
      .map(a => new URL(a.getAttribute('href'), url).href);
    rows.push({cells: cells, views: views});
  }
  return {status: r.status, table: true, heads: heads, rows: rows, password: password};
}"""


def _ask_list(page, url: str) -> dict:
    try:
        got = intake.evaluate(page, _LIST_JS, [url], limit=MAX_LIST_BYTES) or {}
    except intake.TooLarge:
        raise ListStopped("the bill history page is larger than any history")
    if got.get("redirected") or got.get("status") in (401, 403) or got.get("password"):
        raise SessionExpired("the payment portal's session has ended")
    if got.get("status") != 200:
        raise ListStopped(f"the bill history was answered with {got.get('status')}")
    if not got.get("table"):
        raise SessionExpired("the payment portal answered without its bill history")
    return got


def bill_day(text) -> Optional[str]:
    """A Due Date cell, "Oct 12, 2026", as YYYY-MM-DD, or None when the
    whole cell is not a calendar date."""
    m = _DUE_DATE_RE.fullmatch(re.sub(r"\s+", " ", str(text or "")).strip())
    if not m:
        return None
    try:
        return _date(int(m.group(3)), _MONTHS[m.group(1)[:3].lower()], int(m.group(2))).isoformat()
    except (KeyError, ValueError):
        return None


def bills_of(heads: list, rows: list) -> List[RawDoc]:
    """RawDocs from the Bill History rows, one per row with a View link,
    dated by its Due Date column. A header with no single Due Date column,
    a row with no View link or more than one, a View address that is not a
    bill's, a date that is not a calendar date, or two bills of one date
    stops the list, carrying what was read before it, since a bill is found
    again by its date. Nothing from a row but its date is said."""
    docs: List[RawDoc] = []
    found = [i for i, h in enumerate(heads or []) if re.fullmatch(r"due date", str(h or ""), re.I)]
    if len(found) != 1:
        raise ListStopped("the bill history shows no single Due Date column")
    col = found[0]
    dates = set()
    for r in rows or []:
        cells, views = (r or {}).get("cells") or [], (r or {}).get("views") or []
        if len(views) != 1:
            raise ListStopped("a bill row carries no single View link", docs)
        if not is_download_url(views[0]):
            raise ListStopped("a bill's View address is not one this can read", docs)
        if col >= len(cells):
            raise ListStopped("a bill's row does not line up with the header", docs)
        iso = bill_day(cells[col])
        if not iso:
            raise ListStopped("a bill's due date is not a calendar date", docs)
        if iso in dates:
            raise ListStopped("two bills carry one due date", docs)
        dates.add(iso)
        title = f"NW Natural Bill {iso}"
        docs.append(RawDoc(title=title, date_text=iso, href=DOWNLOAD_PATH, text=title,
                           row_index=len(docs), kind="statement",
                           document_id=f"bill-{iso}", bill_ref=views[0]))
    return docs


def _keep_private(rows) -> None:
    """Register each row's account number, part by part, as a private word,
    so nothing said or written by the run carries it."""
    found = []
    for r in rows or []:
        for c in (r or {}).get("cells") or []:
            if re.fullmatch(r"[0-9]{5,}-?[0-9]*", str(c or "")):
                found.append(str(c))
    parts = {part for w in found for part in re.split(r"[\s,.#/-]+", w) if re.search(r"[0-9]", part)}
    parts |= set(found)
    if parts - set(private_words()):
        set_private_words(private_words() + sorted(parts - set(private_words())))


def _all_bills(page) -> List[RawDoc]:
    if looks_signed_out(page):
        raise SessionExpired("nwnatural.com showed its sign-in page")
    if not _on_portal(page):
        raise ListStopped("the tab is not on NW Natural's payment portal; open your bills there "
                          "in the sign-in window")
    url = history_url(page)
    if not url:
        raise ListStopped("the payment portal page shows no Bill History link")
    got = _ask_list(page, url)
    _keep_private(got.get("rows"))
    return bills_of(got.get("heads"), got.get("rows"))


def goto_documents(page) -> bool:
    """Whether the tab is on the payment portal with its Bill History link.
    Nothing is opened by address: the portal's links carry a token of the
    session the account holder signed in with, so this works only in that
    tab."""
    return _on_portal(page) and bool(history_url(page))


def bill_list_opens(page) -> bool:
    """Whether the bill history could be read whole, which only the signed-in
    portal tab allows."""
    try:
        collect_download_docs(page)
        return True
    except (SessionExpired, ListStopped) as e:
        log.info("the bill history could not be read: %s", e)
        return False


def scroll_full_page(page, rounds: int = 8, delay_ms: int = 600) -> None:
    try:
        for _ in range(rounds):
            page.mouse.wheel(0, 3000)
            page.wait_for_timeout(delay_ms)
    except Exception:
        pass


def expand_all(page) -> None:
    """Nothing to press: the whole history is one page."""
    return None


def table_header(page) -> dict:
    """For Diagnose. The header is read from the fetched history, not here."""
    return {"cells": [], "statement_date_column": None}


def collect_download_docs(page) -> List[RawDoc]:
    """Every bill in the bill history. Nothing is pressed and the tab is not
    navigated. A list that cannot be read whole raises ListStopped holding
    what was read, and a signed-out portal raises SessionExpired."""
    return _all_bills(page)


_PDF_JS = r"""async ([url, limit]) => {
  let r;
  try { r = await fetch(url, {credentials: 'include', redirect: 'manual'}); }
  catch (e) { return {status: 0, failed: true}; }
  if (r.type === 'opaqueredirect' || r.redirected) return {status: r.status, redirected: true};
  const type = r.headers.get('content-type') || '';
  if (r.status !== 200) return {status: r.status, type: type};
  const buf = await ppRead(r);
  if (buf.length > limit) return {status: r.status, type: type, too_big: true};
  let s = '';
  for (let i = 0; i < buf.length; i += 0x8000) {
    s += String.fromCharCode.apply(null, buf.subarray(i, i + 0x8000));
  }
  return {status: r.status, type: type, b64: btoa(s)};
}"""


def _fetch(page, bill: RawDoc, out_path: Path, trace: Optional[list]) -> bool:
    """GET the bill's View address from inside the portal tab, the way its
    View link opens it, and keep the body only when it is a PDF. A redirect,
    a refusal, or an HTML body is the portal saying the session has ended."""
    if not is_download_url(bill.bill_ref):
        return False
    try:
        got = intake.evaluate(page, _PDF_JS, [bill.bill_ref, MAX_PDF_BYTES], limit=MAX_PDF_BYTES) or {}
    except intake.TooLarge:
        return False
    except Exception as e:
        log.info("fetching the bill failed (%s)", type(e).__name__)
        if trace is not None:
            trace.append({"note": "fetch failed", "error": type(e).__name__})
        return False
    ctype = str(got.get("type") or "").split(";", 1)[0].strip().lower()
    if trace is not None:
        trace.append({"note": "fetched", "host": PORTAL_HOST, "status": got.get("status"), "type": ctype[:30]})
    if got.get("redirected") or got.get("status") in (401, 403):
        raise SessionExpired("the payment portal's session has ended")
    if got.get("status") != 200 or not got.get("b64"):
        return False
    try:
        data = intake.decode(got["b64"], validate=True, limit=MAX_PDF_BYTES)
    except Exception:
        return False
    if data[:5] != b"%PDF-":
        if data.lstrip()[:1] in (b"<", b"{", b"["):
            raise SessionExpired("the payment portal answered a bill with a sign-in page")
        return False
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(data)
    return True


def download_bill(page, dl_dir, iso_date: str, out_path, title: str = "",
                  trace: Optional[list] = None, href: str = "",
                  document_id: str = "") -> bool:
    """Save the bill discovery recorded for `iso_date`. The bill history is
    read again, since a View address holds the session's token, and the bill
    is fetched only when exactly one bill there carries that date. `dl_dir`
    is unused: nothing goes through the browser's downloads. Nothing is
    pressed. SessionExpired propagates to the run."""
    out_path = Path(out_path)
    if href != DOWNLOAD_PATH or not BILL_ID_RE.fullmatch(document_id or "") \
            or document_id != f"bill-{iso_date}":
        log.info("no bill was recorded for this document")
        if trace is not None:
            trace.append({"note": "no recorded bill"})
        return False
    try:
        found = [d for d in _all_bills(page) if d.date_text == iso_date]
    except ListStopped as stop:
        log.info("the bill list stopped while looking for the bill dated %s: %s", iso_date, stop)
        return False
    if len(found) != 1:
        log.info("%d bills match the recorded date %s, none taken", len(found), iso_date)
        if trace is not None:
            trace.append({"note": "no single bill matches the record", "matches": len(found)})
        return False
    return _fetch(page, found[0], out_path, trace)


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
