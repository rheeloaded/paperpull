"""ALL client.adviceworks.net selectors, URLs, and page behavior live here.

When Cetera changes its AdviceWorks client portal, repair this file only.

STATUS: built 2026-10-30 from a signed-in survey of a real account, with
nothing pressed by the app.

SEEN SIGNED IN, 2026-10-30 (shapes only, no values kept):

  * adviceworks.net hands a signed-in person to the client portal,
    https://client.adviceworks.net. Sign-in itself is an Azure B2C page on
    clientlogin.adviceworks.net, which this app never opens or reads.
  * My Documents' Statements & Notices page,
    https://client.adviceworks.net/my-docs/statements, talks to
    /integrate-api/cpstatement/v1/experience/ with two headers the page
    adds, `authorization` and `x-session-id`. The session's cookies alone
    are refused (403).
  * On load it asks POST statements?pageNum=1 with {accountList, quarter,
    year}: the person's accounts, each {accountNum ("XXXX-" and the last
    four digits), accountType, accountId, custodian}, and the current
    quarter. Asked with quarter and year "All" (the page's own choices) the
    answer is every statement, 25 a page, {statementData, totalItems}; rows
    are {accountNum, accountType, statementName, statementId, statementDate
    (epoch ms), statementDateFormated (MM/DD/YYYY)}. 56 seen across four
    accounts, 2025 to 2026, newest first.
  * It also asks GET accountQprs?quarter=all&year=all, the quarterly
    performance reports, {statementData, totalItems}; rows are
    {statementName ("YYYY Qn" and a household name), statementId (digits),
    statementDate, statementDateFormated, accountId, isRia}. 5 seen.
  * A statement's PDF is GET downloadStatement/<statementId, url-safe
    base64>?isStatementIdEncoded=true&statementType=STATEMENTS, the address
    the page's own download builds, with the two headers: application/pdf,
    a body starting %PDF. A report's is GET downloadQPRs/<statementId>
    ?statementType=QPR&isRiaStatement=<isRia> with the two headers and the
    report's accountId as an `accountId` header, as the page sends it.
  * So a run opens Statements & Notices by its address, takes the two
    headers and the account list off the page's own statements request,
    asks the same two lists from inside the page (every quarter, every
    year, page by page), and fetches each PDF the same way. Nothing is
    clicked. The header values stay in memory and are never written.

Sign-in, with any verification code, is the account holder's own, in the
browser.

SAFETY (a brokerage account that can trade, transfer and deposit):
  This module is strictly READ-ONLY. It presses nothing, fills nothing and
  submits nothing, and the only requests it sends are the page's own two
  document lists and the page's own document downloads. It must NEVER
  activate any control that trades, transfers, deposits a check, links a
  bank, changes eDelivery or any setting, messages an advisor, or signs
  out. FORBIDDEN_CONTROL_RE is the guard; a control must ALSO match one of
  the anchored document actions (SAFE_DOC_CONTROL_RES), and the shared
  core guards are consulted every time.
"""
from __future__ import annotations

import base64
import logging
import json
import re
import sys
from dataclasses import dataclass
from datetime import date as _date
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import parse_qs, urlsplit

from paperpull_core import intake
from paperpull_core.controls import SETTINGS_CONTROL_RE, AUTH_CONTROL_RE
from paperpull_core.redact import private_words, redact, set_private_words  # noqa: F401  (re-exported)
from paperpull_core.urls import is_safe_url as _host_allows
from paperpull_core.dates import last_day as _last_day
from paperpull_core.dates import checked as _checked_date
from paperpull_core.dates import full_year as _full_year
from paperpull_core.words import words_for as _words_for

log = logging.getLogger("cetera_docs.site")


def _words():
    """This app's own words for paperpull_core.words."""
    return _words_for("Cetera", sys.modules[__name__])


# ---------------------------------------------------------------------------
# Addresses
# ---------------------------------------------------------------------------
HOST = "client.adviceworks.net"
BASE = f"https://{HOST}"
API_PATH = "/integrate-api/cpstatement/v1/experience/"
API = BASE + API_PATH
LIST_PATH = API_PATH + "statements"
QPR_LIST_PATH = API_PATH + "accountQprs"
QPR_LIST_URL = BASE + QPR_LIST_PATH + "?quarter=all&year=all"
DOCUMENTS_PATH = "/my-docs/statements"
DOCUMENTS_URL = BASE + DOCUMENTS_PATH
# What discovery records as each document's href. The PDF address is built
# from the row a fresh list finds for the recorded id, checked.
DOWNLOAD_PATH = API_PATH + "downloadStatement"
QPR_DOWNLOAD_PATH = API_PATH + "downloadQPRs"
STATEMENTS_URL = DOCUMENTS_URL
BILLING_URL = DOCUMENTS_URL
URLS = {
    "home": f"{BASE}/dashboard",
    "login": f"{BASE}/dashboard",
    "documents": DOCUMENTS_URL,
    "statements": DOCUMENTS_URL,
}

LOGIN_URL_MARKERS = ["clientlogin.adviceworks.net", "/b2c_", "/login", "/signin", "/sign-in", "/logout"]

# ---------------------------------------------------------------------------
# HARD SAFETY GUARD. Tuned for a brokerage client portal. Every stem
# anchored so "Statements" is not "statement settings".
# ---------------------------------------------------------------------------
FORBIDDEN_CONTROL_RE = re.compile(
    r"(\bpay\b|\bpaying\b|\bpayments?\b|\bautopay\b|\bbank|\btrad(e|es|ed|ing)\b|\bbuy\b|\bsell\b|\border\b|"
    r"\brebalance\b|\bliquidate\b|\bredeem|\bexchange\b|\btransfer|\bdeposit|\bwithdraw|\bdistribution|"
    r"\bcontribut|\brollover\b|\bmove\s+money\b|\bcheck\s+deposit\b|\bedelivery\b|\be-?delivery\b|"
    r"\bpaperless\b|\bgo\s+green\b|\benroll|\bunenroll|\bsign\s*up\b|\bregist(er|ration)\b|"
    r"\bnotifications?\b|\balerts?\b|\bsign\s*(out|off)\b|\blog\s*(out|off)\b|\blogout\b|\bletters?\b|"
    r"\bturbo\s*tax\b|\bexcel\b|\bexport\b|\bcsv\b|\bofx\b|\bprograms?\b|\bprofile\b|\bsettings?\b|"
    r"\bpreferences?\b|\bsave\b|\bsubmit\b|\bconfirm\b|\bcontinue\b|\bapply\b|"
    r"\bdelet(e|es|ed|ing)\b|\bremov(e|es|ed|ing|al)\b|\bcancel\b|\bedit(s|ed|ing)?\b|\bupdat(e|es|ed|ing)\b|"
    r"\bchang(e|es|ed|ing)\b|\bmanage\b|\bturn\s+(on|off)\b|\bopt\s*-?\s*(in|out)\b|\bclose\b|\bupload\b|"
    r"\bemail\b|\bshare\b|\bchat\b|\bmessage|\bcontact\b|\brequest(s|ed|ing)?\b|\bschedul(e|es|ed|ing)\b|"
    r"\bagree\b|\baccept\b|\bauthori[sz]e\b|\bverify\b|\bpassword\b|\busername\b|\broadmap\b|"
    r"\bconsolidat|\bdetails\b)", re.I)

# The links that lead to a document. This app presses none of them; they
# are named here for the survey's verdicts.
SAFE_DOC_CONTROL_RES = (
    re.compile(r"^(view|download)\s+((brokerage|account)\s+)?statement(\s+\(?pdf\)?)?$", re.I),
    re.compile(r"^(view|download)\s+(quarterly\s+performance\s+)?report(\s+\(?pdf\)?)?$", re.I),
)

# The Statements tab of Statements & Notices, which only a signed-in page
# draws.
BILL_CONTROL_RE = re.compile(r"^\s*statements\s*$", re.I)

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

# For Diagnose's counts only: the rows of the statements table as drawn.
BILL_ROW = "table tbody tr"

FALLBACK = {
    "doc_row": BILL_ROW,
    "page_ready": "main",
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


# A document's date exactly as the API writes it: "09/30/2026".
_STATEMENT_DATE_RE = re.compile(r"([0-9]{2})/([0-9]{2})/([0-9]{4})")
# The words that head the table's date column, for Diagnose.
STATEMENT_HEAD_WORDS = frozenset({"date"})


def statement_date(text) -> Optional[str]:
    """A document's statementDateFormated as YYYY-MM-DD, or None. The whole
    value must be the date and the day must exist."""
    m = _STATEMENT_DATE_RE.fullmatch(str(text or "").strip())
    if not m:
        return None
    try:
        return _date(int(m.group(3)), int(m.group(1)), int(m.group(2))).isoformat()
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Session / safety
# ---------------------------------------------------------------------------

class SessionExpired(Exception):
    """The portal answered as a signed-out session: its sign-in page, a
    redirect where a document was asked for, a 401 or 403, or an HTML or
    JSON body where a PDF was expected. The run stops for the account
    holder."""


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
    Visible text only. A page that shows the Statements tab is not a
    challenge, whatever its text says further down."""
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
# Hosts. Exact, parsed, no subdomain wildcard, and a document only from its
# own two download addresses.
# ---------------------------------------------------------------------------
ALLOWED_HOSTS = {HOST}
PAGE_SIZE = 25
MAX_PAGES = 40
STATEMENT_ID_RE = re.compile(r"[A-Za-z0-9+/=_-]{16,400}")
QPR_ID_RE = re.compile(r"[0-9]{4,12}")
_ACCOUNT_NUM_RE = re.compile(r"XXXX-([0-9]{4})")
_ACCOUNT_ID_RE = re.compile(r"[0-9]{3,15}")
_NAME_RE = re.compile(r"[A-Za-z][A-Za-z ]{2,59}")
_QPR_NAME_RE = re.compile(r"([0-9]{4}) Q([1-4])\b.*")
_DOC_ID_RE = re.compile(r"statement-([0-9]{4})-([0-9]{8})|qpr-([0-9]{4,12})")
# The account fields the page's own request carries, and nothing else is
# sent back.
_ACCOUNT_KEYS = frozenset({"accountNum", "accountType", "accountId", "custodian", "isRia"})
MAX_LIST_BYTES = 5 * 1024 * 1024
MAX_PDF_BYTES = 40 * 1024 * 1024
# The only request headers taken from the page's own call. The values live
# in memory for one run and are never written, logged or printed.
_CARRIED_HEADERS = ("authorization", "x-session-id")


def is_safe_url(url: str) -> bool:
    """True only for an https URL on exactly client.adviceworks.net."""
    return _host_allows(url, ALLOWED_HOSTS, subdomains=False)


def _encoded(statement_id: str) -> str:
    return base64.b64encode(statement_id.encode()).decode().replace("+", "-").replace("/", "_")


def statement_url(statement_id: str) -> str:
    """A statement's own PDF address, the one the page's download builds,
    or "" when the id is not one."""
    if not STATEMENT_ID_RE.fullmatch(statement_id or ""):
        return ""
    url = f"{BASE}{DOWNLOAD_PATH}/{_encoded(statement_id)}?isStatementIdEncoded=true&statementType=STATEMENTS"
    return url if is_download_url(url) else ""


def qpr_url(statement_id: str, is_ria: bool) -> str:
    """A quarterly performance report's own PDF address, or "" when the id
    is not one."""
    if not QPR_ID_RE.fullmatch(statement_id or ""):
        return ""
    url = f"{BASE}{QPR_DOWNLOAD_PATH}/{statement_id}?statementType=QPR&isRiaStatement={'true' if is_ria else 'false'}"
    return url if is_download_url(url) else ""


def is_download_url(url: str) -> bool:
    """True only for a document's PDF address: this host, one of the two
    download paths with one id segment of its shape, and exactly the query
    the page's own download sends."""
    if not is_safe_url(url):
        return False
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    if parts.netloc != HOST or parts.fragment:
        return False
    q = parse_qs(parts.query, keep_blank_values=True)
    if any(len(v) != 1 for v in q.values()):
        return False
    head, _, seg = parts.path.rpartition("/")
    if head == DOWNLOAD_PATH:
        return (bool(re.fullmatch(r"[A-Za-z0-9_=-]{16,600}", seg))
                and q == {"isStatementIdEncoded": ["true"], "statementType": ["STATEMENTS"]})
    if head == QPR_DOWNLOAD_PATH:
        return (bool(QPR_ID_RE.fullmatch(seg)) and set(q) == {"statementType", "isRiaStatement"}
                and q["statementType"] == ["QPR"] and q["isRiaStatement"][0] in ("true", "false"))
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
    document_id: str = ""
    # What the PDF is asked by. Never recorded.
    statement_id: str = ""
    account_id: str = ""
    is_ria: bool = False


class ListStopped(Exception):
    """The list has a part this could not read, so what was read is not all
    of it. `docs` holds what was read before it stopped."""

    def __init__(self, why: str, docs=None):
        super().__init__(why)
        self.docs = list(docs or [])


@dataclass
class _Session:
    accounts: list
    headers: dict


def _accounts_of(method: str, url: str, post_data: Optional[str]) -> Optional[list]:
    """The account list the page's own statements request carries, when it
    is that request, else None."""
    if (method or "").upper() != "POST":
        return None
    try:
        parts = urlsplit(url or "")
    except ValueError:
        return None
    if parts.netloc != HOST or parts.path != LIST_PATH:
        return None
    try:
        body = json.loads(post_data or "")
    except (TypeError, ValueError):
        return None
    accounts = body.get("accountList") if isinstance(body, dict) else None
    if not isinstance(accounts, list) or not accounts:
        return None
    out = []
    for a in accounts:
        if not isinstance(a, dict) or not set(a) <= _ACCOUNT_KEYS:
            return None
        if not _ACCOUNT_NUM_RE.fullmatch(str(a.get("accountNum") or "")):
            return None
        if not _ACCOUNT_ID_RE.fullmatch(str(a.get("accountId") or "")):
            return None
        out.append(dict(a))
    return out


def _settled_here(page) -> bool:
    url = page.url or ""
    try:
        return is_safe_url(url) and urlsplit(url).path.rstrip("/") == DOCUMENTS_PATH
    except ValueError:
        return False


def _open(page, timeout_ms: int = 45000) -> _Session:
    """Open Statements & Notices by its address and take the account list
    and the two headers the page's own statements request carries. Raises
    SessionExpired when the site shows its sign-in page and ListStopped
    when the page never asks. Nothing is pressed."""
    got = []

    def seen(req):
        try:
            if not got and _accounts_of(req.method, req.url, req.post_data):
                got.append(req)
        except Exception:
            pass

    page.on("request", seen)
    try:
        try:
            page.goto(DOCUMENTS_URL, wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            log.info("opening Statements & Notices failed (%s)", type(e).__name__)
        waited = 0
        while not got and waited < timeout_ms:
            if looks_signed_out(page):
                break
            page.wait_for_timeout(250)
            waited += 250
    finally:
        try:
            page.remove_listener("request", seen)
        except Exception:
            pass
    if looks_signed_out(page):
        raise SessionExpired("the portal showed its sign-in page")
    if not got:
        raise ListStopped("Statements & Notices did not ask for its statements")
    if not _settled_here(page):
        raise ListStopped("Statements & Notices settled off its own address")
    req = got[0]
    try:
        headers = {k: v for k, v in req.all_headers().items() if k.lower() in _CARRIED_HEADERS and v}
    except Exception as e:
        raise ListStopped(f"the page's own request could not be read ({type(e).__name__})")
    if not headers.get("authorization"):
        raise ListStopped("the page's own statements request carried no authorization")
    accounts = _accounts_of(req.method, req.url, req.post_data)
    _keep_private([_ACCOUNT_NUM_RE.fullmatch(a["accountNum"]).group(1) for a in accounts]
                  + [str(a["accountId"]) for a in accounts])
    return _Session(accounts=accounts, headers=headers)


def _keep_private(words) -> None:
    parts = {str(w) for w in words or [] if w and len(str(w)) >= 4}
    if parts - set(private_words()):
        set_private_words(private_words() + sorted(parts - set(private_words())))


_ASK_JS = r"""async ([url, method, headers, body]) => {
  let r;
  try {
    const init = {method: method, credentials: 'include', redirect: 'manual',
                  headers: Object.assign({'content-type': 'application/json'}, headers)};
    if (body !== null) init.body = JSON.stringify(body);
    r = await fetch(url, init);
  } catch (e) { return {status: 0, failed: true}; }
  if (r.type === 'opaqueredirect' || r.redirected) return {status: r.status, redirected: true};
  let data = null;
  try { data = await ppJson(r); } catch (e) { if (ppRefused(e)) throw e; data = null; }
  return {status: r.status, data: data};
}"""


def _ask(page, session: _Session, url: str, body) -> dict:
    method = "GET" if body is None else "POST"
    try:
        got = intake.evaluate(page, _ASK_JS, [url, method, session.headers, body], limit=MAX_LIST_BYTES) or {}
    except intake.TooLarge:
        raise ListStopped("a document list is larger than any history")
    if got.get("redirected") or got.get("status") in (401, 403):
        raise SessionExpired("the portal refused the session")
    if got.get("status") != 200 or not isinstance(got.get("data"), dict):
        raise ListStopped(f"a document list was answered with {got.get('status')}")
    return got["data"]


def _total(answer) -> int:
    try:
        return int(str(answer.get("totalItems")))
    except (TypeError, ValueError):
        raise ListStopped("a document list does not say how many it holds")


def _ask_statements(page, session: _Session) -> Tuple[list, int]:
    """Every statement row, page by page, with every quarter and year."""
    body = {"accountList": session.accounts, "quarter": "All", "year": "All"}
    rows: list = []
    total = None
    for n in range(1, MAX_PAGES + 1):
        answer = _ask(page, session, f"{API}statements?pageNum={n}", body)
        total = _total(answer) if total is None else total
        part = answer.get("statementData")
        if not isinstance(part, list):
            raise ListStopped("the statement list holds no statements")
        rows += part
        if not part or len(rows) >= total:
            return rows, total
    raise ListStopped(f"the statement list runs past {MAX_PAGES} pages")


def _ask_reports(page, session: _Session) -> Tuple[list, int]:
    answer = _ask(page, session, QPR_LIST_URL, None)
    rows = answer.get("statementData")
    if not isinstance(rows, list):
        raise ListStopped("the report list holds no reports")
    return rows, _total(answer)


def statements_of(rows, total: int, accounts=None) -> List[RawDoc]:
    """RawDocs from the statement rows, one per statement, known by its
    account's last four digits and its date. A row that is not one, an
    account the page did not ask for, a date that is not a calendar date,
    two statements of one account and date, or fewer rows than the list
    says it holds stops the list, carrying what was read before it."""
    known = None if accounts is None else {a["accountNum"] for a in accounts}
    docs: List[RawDoc] = []
    ids = set()
    for r in rows or []:
        if not isinstance(r, dict):
            raise ListStopped("a statement is not an object", docs)
        acct = str(r.get("accountNum") or "")
        m = _ACCOUNT_NUM_RE.fullmatch(acct)
        if not m or (known is not None and acct not in known):
            raise ListStopped("a statement's account is not one the page asked for", docs)
        sid = str(r.get("statementId") or "")
        if not STATEMENT_ID_RE.fullmatch(sid):
            raise ListStopped("a statement's id is not one this can read", docs)
        iso = statement_date(r.get("statementDateFormated"))
        if not iso:
            raise ListStopped("a statement's date is not a calendar date", docs)
        doc_id = f"statement-{m.group(1)}-{iso.replace('-', '')}"
        if doc_id in ids:
            raise ListStopped("two statements carry one account and date", docs)
        ids.add(doc_id)
        name = re.sub(r"\s+", " ", str(r.get("statementName") or "")).strip()
        name = name if _NAME_RE.fullmatch(name) else "Statement"
        title = f"Cetera {name} {iso}"
        docs.append(RawDoc(title=title, account=acct, date_text=iso, href=DOWNLOAD_PATH, text=title,
                           row_index=len(docs), kind="statement", document_id=doc_id,
                           statement_id=sid))
    if len(docs) != total:
        raise ListStopped(f"the statement list read {len(docs)} of the {total} it holds", docs)
    return docs


def reports_of(rows, total: int) -> List[RawDoc]:
    """RawDocs from the quarterly performance report rows, known by their
    report id and dated by their date. The household name in a report's
    name is never kept; the title says only its year and quarter."""
    docs: List[RawDoc] = []
    ids = set()
    for r in rows or []:
        if not isinstance(r, dict):
            raise ListStopped("a report is not an object", docs)
        sid = str(r.get("statementId") or "")
        if not QPR_ID_RE.fullmatch(sid):
            raise ListStopped("a report's id is not one this can read", docs)
        acct_id = str(r.get("accountId") or "")
        if not _ACCOUNT_ID_RE.fullmatch(acct_id):
            raise ListStopped("a report's account is not one this can read", docs)
        iso = statement_date(r.get("statementDateFormated"))
        if not iso:
            raise ListStopped("a report's date is not a calendar date", docs)
        if sid in ids:
            raise ListStopped("two reports carry one id", docs)
        ids.add(sid)
        m = _QPR_NAME_RE.fullmatch(re.sub(r"\s+", " ", str(r.get("statementName") or "")).strip())
        quarter = f" {m.group(1)} Q{m.group(2)}" if m else ""
        title = f"Cetera Quarterly Performance Report{quarter} {iso}"
        docs.append(RawDoc(title=title, date_text=iso, href=QPR_DOWNLOAD_PATH, text=title,
                           row_index=len(docs), kind="report", document_id=f"qpr-{sid}",
                           statement_id=sid, account_id=acct_id, is_ria=r.get("isRia") is True))
    if len(docs) != total:
        raise ListStopped(f"the report list read {len(docs)} of the {total} it holds", docs)
    return docs


def goto_documents(page) -> bool:
    """Open Statements & Notices and take its account list. False when it
    showed the sign-in page, settled elsewhere, or never asked."""
    try:
        _open(page)
        return True
    except (SessionExpired, ListStopped) as e:
        log.info("Statements & Notices did not open: %s", e)
        return False


def bill_list_opens(page) -> bool:
    """Whether the document list could be read whole, which only a
    signed-in page allows."""
    try:
        collect_download_docs(page)
        return True
    except (SessionExpired, ListStopped) as e:
        log.info("the document list could not be read: %s", e)
        return False


def scroll_full_page(page, rounds: int = 8, delay_ms: int = 600) -> None:
    try:
        for _ in range(rounds):
            page.mouse.wheel(0, 3000)
            page.wait_for_timeout(delay_ms)
    except Exception:
        pass


def expand_all(page) -> None:
    """Nothing to press: both lists are asked for whole."""
    return None


def table_header(page) -> dict:
    """For Diagnose. The lists are read from the API, not a table."""
    return {"cells": [], "statement_date_column": None}


def collect_download_docs(page) -> List[RawDoc]:
    """Every statement and quarterly performance report the portal lists.
    Nothing is pressed. A list that cannot be read whole raises ListStopped
    holding what was read, and a signed-out session raises SessionExpired."""
    session = _open(page)
    rows, total = _ask_statements(page, session)
    docs = statements_of(rows, total, session.accounts)
    try:
        rows, total = _ask_reports(page, session)
        return docs + reports_of(rows, total)
    except ListStopped as stop:
        raise ListStopped(str(stop), docs + stop.docs)


_PDF_JS = r"""async ([url, headers, limit]) => {
  let r;
  try { r = await fetch(url, {credentials: 'include', redirect: 'manual', headers: headers}); }
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


def pdf_request(doc: RawDoc, headers: dict) -> Tuple[str, dict]:
    """The address and headers the page's own download sends for `doc`, or
    ("", {}) when it is neither kind."""
    if doc.href == DOWNLOAD_PATH:
        return statement_url(doc.statement_id), dict(headers)
    if doc.href == QPR_DOWNLOAD_PATH and _ACCOUNT_ID_RE.fullmatch(doc.account_id or ""):
        return qpr_url(doc.statement_id, doc.is_ria), dict(headers, accountId=doc.account_id)
    return "", {}


def _fetch(page, doc: RawDoc, session: _Session, out_path: Path, trace: Optional[list]) -> bool:
    """GET the document's PDF address from inside the signed-in page, the
    way its own download does, and keep the body only when it is a PDF."""
    url, headers = pdf_request(doc, session.headers)
    if not url:
        return False
    try:
        got = intake.evaluate(page, _PDF_JS, [url, headers, MAX_PDF_BYTES], limit=MAX_PDF_BYTES) or {}
    except intake.TooLarge:
        return False
    except Exception as e:
        log.info("fetching the document failed (%s)", type(e).__name__)
        if trace is not None:
            trace.append({"note": "fetch failed", "error": type(e).__name__})
        return False
    ctype = str(got.get("type") or "").split(";", 1)[0].strip().lower()
    if trace is not None:
        trace.append({"note": "fetched", "host": HOST, "status": got.get("status"), "type": ctype[:30]})
    if got.get("redirected") or got.get("status") in (401, 403):
        raise SessionExpired("the portal refused the document")
    if got.get("status") != 200 or not got.get("b64"):
        return False
    try:
        data = intake.decode(got["b64"], validate=True, limit=MAX_PDF_BYTES)
    except Exception:
        return False
    if data[:5] != b"%PDF-":
        if data.lstrip()[:1] in (b"<", b"{", b"["):
            raise SessionExpired("the portal answered a document with a sign-in page")
        return False
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(data)
    return True


def download_bill(page, dl_dir, iso_date: str, out_path, title: str = "",
                  trace: Optional[list] = None, href: str = "",
                  document_id: str = "") -> bool:
    """Save the document discovery recorded as `document_id`, dated
    `iso_date`. Both lists are asked again and the document is fetched only
    when exactly one row there carries that id, address and date. `dl_dir`
    is unused. Nothing is pressed. SessionExpired propagates to the run."""
    out_path = Path(out_path)
    doc_id = (document_id or "").strip()
    if href not in (DOWNLOAD_PATH, QPR_DOWNLOAD_PATH) or not _DOC_ID_RE.fullmatch(doc_id):
        log.info("no document was recorded for this entry")
        if trace is not None:
            trace.append({"note": "no recorded document"})
        return False
    try:
        session = _open(page)
        if href == DOWNLOAD_PATH:
            rows, total = _ask_statements(page, session)
            listed = statements_of(rows, total, session.accounts)
        else:
            rows, total = _ask_reports(page, session)
            listed = reports_of(rows, total)
    except ListStopped as stop:
        log.info("the document list stopped while looking for the one dated %s: %s", iso_date, stop)
        return False
    found = [d for d in listed if d.document_id == doc_id and d.href == href and d.date_text == (iso_date or "")]
    if len(found) != 1:
        log.info("%d documents match the recorded id and date %s, none taken", len(found), iso_date)
        if trace is not None:
            trace.append({"note": "no single document matches the record", "matches": len(found)})
        return False
    return _fetch(page, found[0], session, out_path, trace)


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

SURVEY_LINK_RE = re.compile(r"^\s*(my\s+documents|statements)\s*$", re.I)


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
