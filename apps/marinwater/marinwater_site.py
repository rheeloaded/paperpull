"""Read Marin Water bills from its signed-in Paymentus portal.

The portal's View Bill History link returns a table with Account, Bill Date
and Action columns. Each View Bill link is a signed GET to the fixed DataProse
PDF reader. No payment controls are pressed. Session tokens and signed links
stay in memory, and the PDF request carries no Paymentus cookies.
"""
from __future__ import annotations

import logging
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import date as _date
from hashlib import sha256
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import parse_qs, urlsplit

from paperpull_core import shared_folder
from paperpull_core import intake, refused
from paperpull_core.controls import SETTINGS_CONTROL_RE, AUTH_CONTROL_RE
from paperpull_core.redact import private_words, redact, set_private_words  # noqa: F401  (re-exported)
from paperpull_core.urls import is_safe_url as _host_allows
from paperpull_core.dates import last_day as _last_day
from paperpull_core.dates import checked as _checked_date
from paperpull_core.dates import full_year as _full_year
from paperpull_core.failure import error_kind
from paperpull_core.words import words_for as _words_for

log = logging.getLogger("marinwater_docs.site")


def _words():
    """This app's own words for paperpull_core.words."""
    return _words_for("Marin Water", sys.modules[__name__])


# ---------------------------------------------------------------------------
# Addresses
# ---------------------------------------------------------------------------
BASE = "https://ipn4.paymentus.com"
PORTAL_HOST = "ipn4.paymentus.com"
PORTAL = f"https://{PORTAL_HOST}/cp"
HISTORY_PATH = "/cp/view-bill-history.action"
DOCUMENTS_PATH = HISTORY_PATH
DOCUMENTS_URL = BASE + HISTORY_PATH
# Discovery records the generic path. Signed per-bill viewer URLs stay in memory.
VIEWER_HOST = "solsearcher.dataprose.com"
DOWNLOAD_PATH = "/resource/SSEPDFExtractor.dll"
STATEMENTS_URL = DOCUMENTS_URL
BILLING_URL = DOCUMENTS_URL
URLS = {
    "home": f"{PORTAL}/mwdc",
    "login": f"{PORTAL}/mwdc",
    "account": f"{PORTAL}/landing.action",
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

BILL_CONTROL_RE = re.compile(r"^\s*view bill\s*$", re.I)

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


# A bill row's bill date, exactly as the table writes it: "Sep 12, 2026".
_BILL_DATE_RE = re.compile(
    r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+([0-9]{1,2}),\s+([0-9]{4})")


# ---------------------------------------------------------------------------
# Session / safety
# ---------------------------------------------------------------------------

class SessionExpired(Exception):
    """The payment portal answered as a signed-out session: its sign-in
    page, a redirect, a 401, or a 403 that is not its bot protection's. The
    run stops for the account holder."""


class Challenged(Exception):
    """The portal's bot protection (DataDome) answered in place of the
    portal. The account holder answers it in the browser, so the run stops
    once and says so rather than calling the session signed out."""


# The password fields that make a page a sign-in page, here and for the
# core's recorder. The contributor's signed-in Paymentus landing page keeps a
# password field it never draws, so only the fields the page draws count, as
# for Consorsbank (#178). The core takes this value and no other
# (recorder.DRAWN_PASSWORD_FIELD). Login never rests on it, since it says
# signed in only once Bill History is read whole.
PASSWORD_FIELD = "input[type='password']:visible"


def looks_signed_out(page) -> bool:
    """The sign-in page by its address or a drawn password field. A page
    whose address cannot be read raises, and a page whose fields cannot be
    counted is called signed out, the safe answer."""
    path = urlsplit(page.url or "").path.lower()
    if any(m in path for m in LOGIN_URL_MARKERS):
        return True
    try:
        if page.locator(PASSWORD_FIELD).count() > 0:
            return True
    except Exception:
        return True
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
# Marin Water's designated Paymentus host. No other Paymentus hosts are allowed.
ALLOWED_HOSTS = {PORTAL_HOST}
BILL_ID_RE = re.compile(r"bill-(?P<date>[0-9]{4}-[0-9]{2}-[0-9]{2})(?:-(?P<digest>[a-f0-9]{64}))?")
MAX_LIST_BYTES = 5 * 1024 * 1024
MAX_PDF_BYTES = 25 * 1024 * 1024


def is_safe_url(url: str) -> bool:
    """True only for HTTPS on exactly the Paymentus portal host."""
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
    fields = parse_qs(urlsplit(url).query)
    return all(len(fields.get(key, ())) == 1 for key in ("CSRF_TOKEN", "accountId", "accthid"))


def is_download_url(url: str) -> bool:
    """Only the exact document viewer, and only its opaque bill link."""
    if not _host_allows(url, {VIEWER_HOST}, subdomains=False):
        return False
    parts = urlsplit(url)
    return (parts.netloc == VIEWER_HOST and parts.path == DOWNLOAD_PATH and not parts.fragment
            and 0 < len(parts.query) <= 4096 and "&" not in parts.query
            and not re.search(r"[\s\x00-\x1f\x7f]", parts.query))


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
    bill_ref: str = field(default="", repr=False)


class ListStopped(Exception):
    """The list has a part this could not read, so what was read is not all
    of it. `docs` holds what was read before it stopped."""

    def __init__(self, why: str, docs=None):
        super().__init__(why)
        self.docs = list(docs or [])


class SeveralAccounts(ListStopped):
    """Bill History lists the bills of more than one account. A bill is
    known by its bill date alone, so two accounts' bills could not be told
    apart, and nothing is listed."""

    def __init__(self, count: int):
        super().__init__(f"the bill history lists the bills of {count} accounts, and this app reads one")
        self.count = count


def on_portal(page) -> bool:
    """Whether the tab is on Paymentus’s customer portal."""
    return _on_portal(page)


def _on_portal(page) -> bool:
    try:
        url = page.url or ""
        parts = urlsplit(url)
        return is_safe_url(url) and parts.netloc == PORTAL_HOST and parts.path.startswith("/cp/")
    except ValueError:
        return False


def _is_marin_water(page) -> bool:
    """Paymentus serves multiple utilities on this host. Check the merchant."""
    try:
        return bool(page.evaluate(r"""() => {
          const brand = /\bmarin(?: municipal)? water\b/i;
          return brand.test(document.title) ||
              Array.from(document.querySelectorAll('img[alt], img[title], h1, h2')).some(
                  el => brand.test(el.alt || el.title || el.innerText || ''));
        }"""))
    except Exception:
        return False


_HISTORY_LINK_JS = r"""() => {
  return [...document.querySelectorAll('a[href]')]
    .filter(el => /^View Bill History$/i.test(el.textContent.replace(/\s+/g, ' ').trim()))
    .map(el => el.href);
}"""


def _history_urls(page) -> set[str]:
    try:
        hrefs = page.evaluate(_HISTORY_LINK_JS) or []
    except Exception:
        return set()
    return {href for href in hrefs if is_history_url(href)}


def history_url(page) -> str:
    """The portal's exact history link. No date or account parameters are synthesized."""
    urls = _history_urls(page)
    return next(iter(urls)) if len(urls) == 1 else ""


_LIST_JS = r"""async ([url]) => {
  let r;
  try { r = await fetch(url, {credentials: 'same-origin', redirect: 'manual'}); }
  catch (e) { return {status: 0, failed: true}; }
  if (r.type === 'opaqueredirect' || r.redirected) return {status: r.status, redirected: true};
  let html = '';
  try { html = await ppText(r); } catch (e) { if (ppRefused(e)) throw e; }
  // DataDome answers a 403 of its own, marked in its headers or its page.
  if (r.status === 403 && (r.headers.get('x-datadome') || r.headers.get('x-dd-b')
                           || /captcha-delivery|datadome/i.test(html))) {
    return {status: r.status, challenge: true};
  }
  const doc = new DOMParser().parseFromString(html, 'text/html');
  const text = (el) => (el ? el.textContent : '').replace(/\s+/g, ' ').trim();
  const password = !!doc.querySelector("input[type='password']");
  const brand = /\bmarin(?: municipal)? water\b/i;
  if (!brand.test(doc.title) && ![...doc.querySelectorAll('img[alt], img[title]')]
      .some(el => brand.test(el.alt || el.title))) {
    return {status: r.status, wrongMerchant: true, password};
  }
  let table = null, heads = [];
  for (const t of doc.querySelectorAll('table')) {
    const h = [...t.querySelectorAll('thead th, tr:first-child th')].map(text);
    if (h.some(x => /^bill date$/i.test(x))) { table = t; heads = h; break; }
  }
  if (!table) return {status: r.status, table: false, password: password};
  const rows = [];
  for (const tr of table.querySelectorAll('tbody tr')) {
    if ([...tr.cells].every(cell => cell.tagName === 'TH')) continue;
    const cells = [...tr.cells].map(text);
    if (!cells.some(Boolean)) continue;
    const views = [...tr.querySelectorAll('a[href]')].filter(a => /^view bill$/i.test(text(a)))
      .map(a => new URL(a.getAttribute('href'), url).href);
    rows.push({cells: cells, views: views});
  }
  // A pager offering another page: a control in a pager, not disabled,
  // reading Next, an arrow, or a page number past the first.
  const off = (el) => el.hasAttribute('disabled') || el.getAttribute('aria-disabled') === 'true'
    || /\bdisabled\b/.test(el.className || '') || /\bdisabled\b/.test((el.parentElement || {}).className || '');
  let pager = false;
  for (const box of doc.querySelectorAll('.pagination, .pager, .dataTables_paginate, [class*="paginat"], nav[aria-label*="pag" i]')) {
    for (const el of box.querySelectorAll('a, button')) {
      const t = text(el);
      if (!off(el) && (/^(next|more|>|›|»|>>)$/i.test(t) || (/^[0-9]+$/.test(t) && +t > 1))) pager = true;
    }
  }
  // A count the page gives of its own rows, as "Showing 1 to 84 of 84" or
  // "Page 1 of 3".
  // Text nodes joined with a space, since textContent runs neighbors
  // together ("Next" and "Page 1 of 3" read as "NextPage 1 of 3").
  const parts = [], walk = doc.createTreeWalker(doc.body || doc, NodeFilter.SHOW_TEXT);
  while (walk.nextNode()) parts.push(walk.currentNode.nodeValue);
  const all = parts.join(' ').replace(/\s+/g, ' ');
  let count = null, m;
  if ((m = all.match(/showing\s+([0-9]+)\s*(?:to|-|–)\s*([0-9]+)\s+of\s+([0-9]+)/i))) count = +m[3];
  if ((m = all.match(/page\s+([0-9]+)\s+of\s+([0-9]+)/i)) && +m[2] > 1) pager = true;
  return {status: r.status, table: true, heads: heads, rows: rows, password: password,
          pager: pager, count: count};
}"""


def _ask_list(page, url: str) -> dict:
    if not is_history_url(url):
        raise ListStopped("the bill history link did not match the expected portal route")
    try:
        got = intake.evaluate(page, _LIST_JS, [url], limit=MAX_LIST_BYTES) or {}
    except intake.TooLarge:
        raise ListStopped("the bill history page is larger than any history")
    if got.get("challenge"):
        raise Challenged("the payment portal's bot protection asked to check the browser")
    if got.get("redirected") or got.get("status") in (401, 403) or got.get("password"):
        raise SessionExpired("the payment portal's session has ended")
    if got.get("status") != 200:
        raise ListStopped(f"the bill history was answered with {got.get('status')}")
    if got.get("wrongMerchant"):
        raise ListStopped("the bill history did not identify Marin Water")
    if not got.get("table"):
        raise ListStopped("the payment portal answered without its bill history")
    return got


def bill_day(text) -> Optional[str]:
    """A Bill Date cell, "Oct 12, 2026", as YYYY-MM-DD, or None when the
    whole cell is not a calendar date."""
    m = _BILL_DATE_RE.fullmatch(re.sub(r"\s+", " ", str(text or "")).strip())
    if not m:
        return None
    try:
        return _date(int(m.group(3)), _MONTHS[m.group(1)[:3].lower()], int(m.group(2))).isoformat()
    except (KeyError, ValueError):
        return None


def _column(heads: list, name: str) -> int:
    found = [i for i, h in enumerate(heads or []) if re.fullmatch(name, str(h or ""), re.I)]
    if len(found) != 1:
        raise ListStopped(f"the bill history shows no single {name.title()} column")
    return found[0]


def bills_of(heads: list, rows: list) -> List[RawDoc]:
    """RawDocs from the Bill History rows, one per row with a View link,
    dated by its Bill Date column. The rows must all be of one account: a
    sign-in whose history holds more raises SeveralAccounts and nothing is
    listed. A header with no
    single Account or Bill Date column, a row with no account, no View link
    or more than one, a View address that is not a bill's, or a date that
    is not a calendar date stops the list, carrying what was read before
    it. Bill dates shared by multiple rows are resolved after the history
    has been read. Nothing from a row but its date is said."""
    col, acct_col = _column(heads, "bill date"), _column(heads, "account")
    accounts = {str(c[acct_col]).strip() for c in ((r or {}).get("cells") or [] for r in rows or [])
                if acct_col < len(c) and str(c[acct_col]).strip()}
    if len(accounts) > 1:
        raise SeveralAccounts(len(accounts))
    docs: List[RawDoc] = []
    for r in rows or []:
        cells, views = (r or {}).get("cells") or [], (r or {}).get("views") or []
        if max(col, acct_col) >= len(cells):
            raise ListStopped("a bill's row does not line up with the header", docs)
        if not str(cells[acct_col]).strip():
            raise ListStopped("a bill row names no account", docs)
        if len(views) != 1:
            raise ListStopped("a bill row carries no single View link", docs)
        if not is_download_url(views[0]):
            raise ListStopped("a bill's View address is not one this can read", docs)
        iso = bill_day(cells[col])
        if not iso:
            raise ListStopped("a Bill Date cell is not a calendar date", docs)
        title = f"Marin Water Bill {iso}"
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
        raise SessionExpired("ipn4.paymentus.com showed its sign-in page")
    if not _on_portal(page):
        raise ListStopped("the tab is not on Marin Water's payment portal; open your bills there "
                          "in the sign-in window")
    if not _is_marin_water(page):
        raise ListStopped("the Paymentus tab does not identify Marin Water")
    urls = _history_urls(page)
    if len(urls) > 1:
        raise SeveralAccounts(len(urls))
    if not urls:
        raise ListStopped("the payment portal page shows no View Bill History link")
    url = next(iter(urls))
    got = _ask_list(page, url)
    rows = got.get("rows") or []
    _keep_private(rows)
    _RUN["facts"] = {"heads": list(got.get("heads") or [])[:12], "rows": len(rows),
                     "pager": bool(got.get("pager")), "count": got.get("count")}
    # One page was seen holding every bill. A pager, or a count that is not
    # the rows read, says this page is not the whole of it.
    if got.get("pager"):
        raise ListStopped("the bill history shows a pager, and this app reads one page")
    count = got.get("count")
    if isinstance(count, int) and not isinstance(count, bool) and count != len(rows):
        raise ListStopped(f"the bill history says it holds {count} bills and {len(rows)} were read")
    docs = bills_of(got.get("heads"), rows)
    # An empty history has not been seen, and a refused start date or a
    # token that lost its account would look just like one.
    if not docs:
        raise ListStopped("the bill history shows no bills, and an empty history has not been "
                          "seen, so this stops rather than call it complete")
    return docs


def goto_documents(page) -> bool:
    """Whether the tab is on the payment portal with its Bill History link.
    Nothing is opened by address: the portal's links carry a token of the
    session the account holder signed in with, so this works only in that
    tab."""
    return _on_portal(page) and bool(history_url(page))


def bill_list_opens(page) -> bool:
    """Whether the bill history could be read whole, which only the signed-in
    portal tab allows. The portal's bot protection raises Challenged, for
    the caller to say so."""
    try:
        _all_bills(page)
        return True
    except (SessionExpired, ListStopped) as e:
        log.info("the bill history could not be read: %s", error_kind(e))
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


# The list as this run last read it, View addresses and all, so each bill
# is not a fresh read of the whole history, and what Diagnose says of the
# table. In memory for the run only.
_RUN: dict = {}


def _read(page, viewer, split_dates) -> List[RawDoc]:
    """Read the bill history and keep it for the run. A read that fails
    leaves the list already kept as it was."""
    _RUN.pop("facts", None)
    bills = _resolve_bill_ids(page, _all_bills(page), viewer, split_dates)
    _RUN["bills"] = bills
    return bills


def list_facts() -> dict:
    """For Diagnose: the header of the table last read, its row count,
    whether it showed a pager, and the count it gave, if any."""
    return dict(_RUN.get("facts") or {})


def collect_download_docs(page, *, viewer=None, split_dates=(), resolve_ids=True) -> List[RawDoc]:
    """Every bill in the bill history, kept for this run's downloads.
    Nothing is pressed and the tab is not navigated. A list that cannot be
    read whole raises ListStopped holding what was read, a signed-out
    portal raises SessionExpired, and its bot protection Challenged.
    Diagnose can look at the rows without requesting PDFs."""
    if not resolve_ids:
        return _all_bills(page)
    return _read(page, viewer, split_dates)


def _pdf_bytes(page, bill: RawDoc, trace: Optional[list], viewer) -> bytes:
    """Download an allowlisted PDF without the Paymentus browser session."""
    if (viewer is None or not _on_portal(page) or not _is_marin_water(page)
            or not is_download_url(bill.bill_ref)):
        return b""
    response = None
    try:
        response = viewer.get(bill.bill_ref, max_redirects=0, timeout=20000,
                              headers={"Accept": "application/pdf"})
        status = response.status
        is_pdf = response.headers.get("content-type", "").split(";", 1)[0].lower() == "application/pdf"
        if trace is not None:
            trace.append({"note": "fetched", "host": VIEWER_HOST, "status": status,
                          "type": "application/pdf" if is_pdf else "other"})
        if status in (401, 403):
            raise SessionExpired("the bill viewer refused the document link")
        if status != 200 or not is_pdf:
            return b""
        data = intake.body(response, limit=MAX_PDF_BYTES)
    except SessionExpired:
        raise
    except Exception as exc:
        log.info("fetching the bill failed (%s)", type(exc).__name__)
        if trace is not None:
            trace.append({"note": "fetch failed", "error": type(exc).__name__})
        return b""
    finally:
        if response is not None:
            try:
                response.dispose()
            except Exception:
                pass
    return data if data.startswith(b"%PDF-") else b""


def _resolve_bill_ids(page, bills: List[RawDoc], viewer, split_dates) -> List[RawDoc]:
    """Use PDF content to distinguish same-date bills across new signed URLs."""
    by_date: dict[str, list[RawDoc]] = defaultdict(list)
    for bill in bills:
        by_date[bill.date_text].append(bill)
    known = set(split_dates)
    resolved = []
    incomplete = False
    for day, group in by_date.items():
        # Repeated rows with the very same link represent one bill.
        links = {bill.bill_ref: bill for bill in group}
        if len(links) == 1 and day not in known:
            resolved.append(next(iter(links.values())))
            continue
        variants = {}
        for bill in links.values():
            try:
                data = _pdf_bytes(page, bill, None, viewer)
            except SessionExpired:
                # Bill History just loaded, so a refusal by the separate PDF
                # viewer is an unresolved bill instead of a Paymentus sign-out.
                data = b""
            if not data:
                incomplete = True
                break
            doc_id = f"bill-{day}-{sha256(data).hexdigest()}"
            variants.setdefault(doc_id, replace(bill, document_id=doc_id))
        else:
            resolved.extend(variants.values())
    if incomplete:
        raise ListStopped("some bills sharing a date could not be identified", resolved)
    return resolved


def _fetch(page, bill: RawDoc, out_path: Path, trace: Optional[list], viewer) -> bool:
    data = _pdf_bytes(page, bill, trace, viewer)
    if not data:
        return False
    identity = BILL_ID_RE.fullmatch(bill.document_id)
    expected = identity.group("digest") if identity else None
    if expected and sha256(data).hexdigest() != expected:
        if trace is not None:
            trace.append({"note": "PDF did not match the selected bill"})
        return False
    out_path.parent.mkdir(parents=True, exist_ok=True)
    shared_folder.write_bytes(out_path, data)
    return True


# What the trace says of a bill the viewer refused right after Bill History
# was read again, which the run counts (marinwater_docs.App.download_one).
REFUSED_AFTER_A_FRESH_LIST = "the bill was refused right after the list was read"


def download_bill(page, dl_dir, iso_date: str, out_path, title: str = "",
                  trace: Optional[list] = None, href: str = "",
                  document_id: str = "", *, viewer=None, split_dates=(),
                  read_again: bool = True) -> bool:
    """Save the bill discovery recorded for `iso_date`. The list this run
    read is used when there is one; it is read again when there is none,
    and once more when the bill is not in it or is not answered with a PDF,
    since a View address lasts only as long as the session's token. The
    bill is fetched only when exactly one bill has its recorded identity.
    `dl_dir` is unused:
    nothing goes through the browser's downloads. Nothing is pressed.
    Challenged, and SessionExpired and ListStopped from reading the list,
    propagate to the run, so a list that stops stops the run once. A list
    that does not answer, shows no bill, or reaches a page that stops
    answering raises ListStopped too, since it says neither that the
    session ended nor that it holds (refused.list_again). A refusal of the
    bill itself right after the list was read and answered fails this bill
    alone, since the session plainly works."""
    out_path = Path(out_path)
    identity = BILL_ID_RE.fullmatch(document_id or "")
    if href != DOWNLOAD_PATH or not identity or identity.group("date") != iso_date:
        log.info("no bill was recorded for this document")
        if trace is not None:
            trace.append({"note": "no recorded bill"})
        return False
    why = ""
    known = set(split_dates)
    if identity.group("digest"):
        known.add(iso_date)
    # With read_again False, as once the viewer has refused bills right after
    # fresh lists, a list this run read already is used and not read again.
    passes = (False, True) if _RUN.get("bills") is not None else (True,)
    if not read_again and _RUN.get("bills") is not None:
        passes = (False,)
    for fresh in passes:
        if fresh:
            # Read for this bill, or again after a View address the run read
            # earlier was refused. A history that does not answer, or shows
            # no bill, stops the run with the list unread, since every bill
            # after this one would read the same list (refused.list_again).
            refused.list_again(lambda: _read(page, viewer, known), SessionExpired, ListStopped,
                               stops=(Challenged,))
        found = [d for d in _RUN["bills"] if d.document_id == document_id]
        if len(found) > 1:
            why = "multiple bills share this identity"
            break
        if not found:
            why = "no bill matches the recorded identity"
            continue
        try:
            if _fetch(page, found[0], out_path, trace, viewer):
                return True
            why = "the bill was not answered with a PDF"
        except SessionExpired:
            # A refusal of a View address this run read earlier may be its
            # token running out, so the list is read again first. Refused
            # right after a list that answered, it is this bill's alone.
            why = REFUSED_AFTER_A_FRESH_LIST if fresh else "the bill was refused"
    log.info("the selected bill was not downloaded")
    if trace is not None:
        trace.append({"note": "not taken", "why": why})
    return False


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
    parts = urlsplit(page.url or "")
    out = {"url": redact(parts._replace(query="", fragment="").geturl()), "title": ""}
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
