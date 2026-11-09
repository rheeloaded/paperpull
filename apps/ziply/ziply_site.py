"""ALL ziplyfiber.com selectors, URLs, and page behavior live here.

When Ziply Fiber changes its site, repair this file only.

STATUS: built 2026-10-30 from a signed-in survey of a real account, with
nothing pressed by the app.

SEEN SIGNED IN, 2026-10-30 (shapes only, no values kept):

  * My Account's Billing page, https://ziplyfiber.com/myaccount/billing,
    asks POST /myapi, a GraphQL endpoint, with an `authorization` header
    (and a `requestid`) the page adds. On load it asks billingDetails with
    the account number among its variables.
  * Past bills asks billStatements(isCurrentBill: false, accountNumber,
    billsRequired: 5); its answer lists statements of {status, date
    (YYYY-MM-DD), amount_due, id, url}. Asked with billsRequired 100 it
    lists the whole history (17 seen, 2025 to 2026).
  * A statement's url is /api/myacc/billinginvoice?invoiceId=<id>, which
    answers a plain GET with the bill: application/pdf, a body starting
    %PDF, the session's cookies and nothing else. The page's View PDF link
    adds a token the GET does not need.
  * So a run opens Billing by its address, takes the account number and
    the two headers off the page's own billingDetails request, asks
    billStatements (the page's own query, more bills) from inside the page,
    and fetches each statement's PDF the same way. Nothing is clicked. The
    header values stay in memory and are never written. The list is read
    once a run and kept in memory, and read again only for a bill not in
    it.

KNOWN CEILINGS (left as they are until a run shows otherwise)
  * One account. Every account the page asks billingDetails about on load
    is heard, and more than one stops the list. A bill is known by its
    account's last four digits and its invoice id, so a bill listed under
    another account than the one the page asks about stops the run once,
    naming the account to choose. How My Account switches between accounts
    has not been seen.
  * The empty list has not been seen. A list with no bills stops, until a
    real empty history has been seen.
  * 100 bills are asked for and 17 were seen. A list as long as was asked
    for stops, since there may be more. A server that gives fewer than
    were asked for and no more would be read as whole.
  * The answer's APIStatus has been seen as 200 with no message. Any other
    status, an error, or a message that does not say success stops the
    list, and a 401 or 403 there, or words that say the session ended,
    stop the run as signed out.

Sign-in, with any verification code, is the account holder's own, in the
browser.

SAFETY (an account that can pay, enroll and change service):
  This module is strictly READ-ONLY. It presses nothing, fills nothing and
  submits nothing, and the only query it asks is the page's own bill list.
  It must NEVER activate any control that pays, sets up or cancels autopay,
  turns paperless on or off, changes a plan, schedules a visit, returns
  equipment, or signs out. FORBIDDEN_CONTROL_RE is the guard; a control
  must ALSO match one of the anchored document actions
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
from urllib.parse import parse_qs, urlsplit

from paperpull_core import intake
from paperpull_core.characters import whole_json
from paperpull_core.controls import SETTINGS_CONTROL_RE, AUTH_CONTROL_RE
from paperpull_core.redact import private_words, redact, set_private_words  # noqa: F401  (re-exported)
from paperpull_core.urls import is_safe_url as _host_allows
from paperpull_core.dates import last_day as _last_day
from paperpull_core.dates import checked as _checked_date
from paperpull_core.dates import full_year as _full_year
from paperpull_core.words import words_for as _words_for

log = logging.getLogger("ziply_docs.site")


def _words():
    """This app's own words for paperpull_core.words."""
    return _words_for("Ziply Fiber", sys.modules[__name__])


# ---------------------------------------------------------------------------
# Addresses
# ---------------------------------------------------------------------------
BASE = "https://ziplyfiber.com"
API_URL = BASE + "/myapi"
DOCUMENTS_PATH = "/myaccount/billing"
DOCUMENTS_URL = BASE + DOCUMENTS_PATH
# What discovery records as every bill's href; the invoice id is the
# record's document_id and the PDF address is built from it, checked.
DOWNLOAD_PATH = "/api/myacc/billinginvoice"
# Where discovery records a bill's list as, its source_url.
BILLING_URL = DOCUMENTS_URL
URLS = {
    "home": f"{BASE}/myaccount",
    "login": f"{BASE}/myaccount",
    "documents": DOCUMENTS_URL,
    "statements": DOCUMENTS_URL,
}

LOGIN_URL_MARKERS = ["/login", "/signin", "/sign-in", "/logout", "/auth/"]

# ---------------------------------------------------------------------------
# HARD SAFETY GUARD. Tuned for an internet provider's account pages. Every
# stem anchored so "Bill" is not "billing plan" and "Download" is not "load".
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
    r"\bturn\s+off\b|\bupgrade\b|\breturn\s+equipment\b|\bvoice\b|\btrouble\s+ticket\b|"
    r"\brebalance\b|\bliquidate\b|\bdetails\b)", re.I)

# The links that lead to a bill, anchored whole, Billing's own "View PDF"
# and a "View Bill", "Download Bill" or "View Internet Bill", the name its
# rules give a bill, with nothing more. This app presses none of them. They
# are named here for the survey's verdicts.
SAFE_DOC_CONTROL_RES = (
    re.compile(r"^view\s+pdf$", re.I),
    re.compile(r"^(view|download)\s+(your\s+)?(detailed\s+)?(internet\s+)?bill(\s+\(?pdf\)?)?$", re.I),
)

BILL_CONTROL_RE = re.compile(r"^\s*view\s+pdf\s*$", re.I)

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

# For Diagnose's counts only: the View PDF links the page draws.
BILL_ROW = "a[href*='/api/myacc/billinginvoice']"

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


# ---------------------------------------------------------------------------
# Session / safety
# ---------------------------------------------------------------------------

class SessionExpired(Exception):
    """ziplyfiber.com answered as a signed-out session, with its sign-in
    page, a redirect where a bill or the list was asked for, a 401 or 403,
    an answer from the account API that says the session ended, or a page
    where a bill's PDF was expected. The run stops for the account
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
# PDF address. The site and the account API its signed-in pages fetch from
# are one host (seen 2026-10-29). Analytics and cookie hosts are not allowed.
# ---------------------------------------------------------------------------
ALLOWED_HOSTS = {"ziplyfiber.com"}
BILLS_ASKED = 100
INVOICE_ID_RE = re.compile(r"[0-9]{4,12}")
# A bill's document_id, its account's last four digits and its invoice id.
BILL_ID_RE = re.compile(r"bill-([0-9]{4})-([0-9]{4,12})")
_ISO_DAY_RE = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})")
_ACCOUNT_RE = re.compile(r"[0-9]{6,20}")
# How long Billing is given, once it has asked about one account, to ask
# about another, so a page showing two is heard as one that does.
ACCOUNTS_WAIT_MS = 2000
# What an answer of the account API says when the session has ended.
_SIGNED_OUT_WORDS = ("unauthori", "unauthenticat", "not authenticated", "expired", "forbidden",
                     "invalid token", "jwt")
# A message beside a list that answered, which says it did.
_SUCCESS_RE = re.compile(r"(?:success(?:ful)?|ok)", re.I)
MAX_LIST_BYTES = 5 * 1024 * 1024
MAX_PDF_BYTES = 25 * 1024 * 1024
# The only request headers taken from the page's own call. The values live
# in memory for one run and are never written, logged or printed.
_CARRIED_HEADERS = ("authorization", "requestid")
# The page's own Past bills query, word for word, asked with more bills.
BILL_STATEMENTS_QUERY = (
    "query billStatements($isCurrentBill: Boolean, $accountNumber: String!, $billsRequired: Float) "
    "{ billStatements( isCurrentBill: $isCurrentBill accountNumber: $accountNumber "
    "billsRequired: $billsRequired ) { error APIStatus message billStatements "
    "{ status date amount_due id url __typename } __typename } }")


def is_safe_url(url: str) -> bool:
    """True only for an https URL on exactly ziplyfiber.com."""
    return _host_allows(url, ALLOWED_HOSTS, subdomains=False)


def invoice_url(invoice_id: str) -> str:
    """A bill's own PDF address, or "" when the id is not one."""
    if not INVOICE_ID_RE.fullmatch(invoice_id or ""):
        return ""
    url = f"{BASE}{DOWNLOAD_PATH}?invoiceId={invoice_id}"
    return url if is_download_url(url) else ""


def is_download_url(url: str) -> bool:
    """True only for a bill's PDF address: this host, the invoice path, and
    a query that is exactly one invoiceId of the right shape."""
    if not is_safe_url(url):
        return False
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    q = parse_qs(parts.query, keep_blank_values=True)
    return (parts.netloc == "ziplyfiber.com" and parts.path == DOWNLOAD_PATH and not parts.fragment
            and set(q) == {"invoiceId"} and len(q["invoiceId"]) == 1
            and bool(INVOICE_ID_RE.fullmatch(q["invoiceId"][0])))


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


class SeveralAccounts(ListStopped):
    """Billing asked about more than one account, and this app reads one."""

    def __init__(self, count: int):
        super().__init__(f"Billing asked about {count} accounts, and this app reads one")
        self.count = count


class OtherAccountShown(Exception):
    """Billing asks about another account than the one a bill was listed
    under. Every bill of that account would meet the same, so the run stops
    once, naming the last four digits of the account it wants."""

    def __init__(self, wanted: str, shown: str):
        super().__init__(f"Billing shows the account ending {shown}, and the bill is of the one ending {wanted}")
        self.wanted, self.shown = wanted, shown


@dataclass
class _Session:
    account: str
    headers: dict


def _account_request(method: str, url: str, post_data: Optional[str]) -> str:
    """The account number a request of the page's own carries, when it is
    the billingDetails query to /myapi, else ""."""
    if (method or "").upper() != "POST" or url != API_URL:
        return ""
    try:
        body = whole_json(json.loads(post_data or ""))
    except (TypeError, ValueError):
        return ""
    if not isinstance(body, dict) or body.get("operationName") != "billingDetails":
        return ""
    account = str(((body.get("variables") or {}) if isinstance(body.get("variables"), dict) else {}).get("accountNumber") or "")
    return account if _ACCOUNT_RE.fullmatch(account) else ""


def _settled_here(page) -> bool:
    url = page.url or ""
    try:
        return is_safe_url(url) and urlsplit(url).path.rstrip("/") == DOCUMENTS_PATH
    except ValueError:
        return False


def _open(page, timeout_ms: int = 45000) -> _Session:
    """Open Billing by its address and take the account number and the
    authorization the page's own billingDetails query carries. Every
    account the page asks about is heard, and more than one raises
    SeveralAccounts. Raises SessionExpired when the site shows its sign-in
    page and ListStopped when the page never asks. Nothing is pressed."""
    got = []

    def seen(req):
        try:
            if len(got) < 20 and _account_request(req.method, req.url, req.post_data):
                got.append(req)
        except Exception:
            pass

    page.on("request", seen)
    try:
        try:
            page.goto(DOCUMENTS_URL, wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            log.info("opening Billing failed (%s)", type(e).__name__)
        waited = 0
        while not got and waited < timeout_ms:
            page.wait_for_timeout(250)
            waited += 250
        # A page that shows a second account asks about it soon after the
        # first, so it is given a moment more to be heard.
        waited = 0
        while got and waited < ACCOUNTS_WAIT_MS:
            page.wait_for_timeout(250)
            waited += 250
    finally:
        try:
            page.remove_listener("request", seen)
        except Exception:
            pass
    if looks_signed_out(page):
        raise SessionExpired("ziplyfiber.com showed its sign-in page")
    if not got:
        raise ListStopped("Billing did not ask for its account")
    if not _settled_here(page):
        raise ListStopped("Billing settled off its own address")
    accounts = sorted({_account_request(r.method, r.url, r.post_data) for r in got})
    _keep_private(accounts)
    if len(accounts) != 1:
        raise SeveralAccounts(len(accounts))
    req = got[0]
    try:
        headers = {k: v for k, v in req.all_headers().items() if k.lower() in _CARRIED_HEADERS and v}
    except Exception as e:
        raise ListStopped(f"the page's own request could not be read ({type(e).__name__})")
    if not headers.get("authorization"):
        raise ListStopped("the page's own account request carried no authorization")
    return _Session(account=accounts[0], headers=headers)


def _keep_private(words) -> None:
    parts = {str(w) for w in words or [] if w and len(str(w)) >= 4}
    if parts - set(private_words()):
        set_private_words(private_words() + sorted(parts - set(private_words())))


_ASK_JS = r"""async ([url, headers, body]) => {
  let r;
  try {
    r = await fetch(url, {method: 'POST', credentials: 'include', redirect: 'manual',
                          headers: Object.assign({'content-type': 'application/json'}, headers),
                          body: JSON.stringify(body)});
  } catch (e) { return {status: 0, failed: true}; }
  if (r.type === 'opaqueredirect' || r.redirected) return {status: r.status, redirected: true};
  let data = null;
  try { data = await ppJson(r); } catch (e) { if (ppRefused(e)) throw e; data = null; }
  return {status: r.status, data: data};
}"""


def _ask_statements(page, session: _Session) -> dict:
    body = {"operationName": "billStatements", "query": BILL_STATEMENTS_QUERY,
            "variables": {"billsRequired": BILLS_ASKED, "isCurrentBill": False,
                          "accountNumber": session.account}}
    try:
        got = intake.evaluate(page, _ASK_JS, [API_URL, session.headers, body], limit=MAX_LIST_BYTES) or {}
    except intake.TooLarge:
        raise ListStopped("the bill list is larger than any history")
    except Exception as e:
        # The page went away under the script, a sign-out among the ways.
        if looks_signed_out(page):
            raise SessionExpired("ziplyfiber.com showed its sign-in page")
        raise ListStopped(f"the bill list could not be asked ({type(e).__name__})")
    if got.get("redirected") or got.get("status") in (401, 403):
        raise SessionExpired("the account API refused the session")
    if got.get("status") != 200 or not isinstance(got.get("data"), dict):
        raise ListStopped(f"the bill list was answered with {got.get('status')}")
    return got["data"]


def bill_day(text) -> Optional[str]:
    m = _ISO_DAY_RE.fullmatch(str(text or "").strip())
    if not m:
        return None
    try:
        return _date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
    except ValueError:
        return None


def _says_signed_out(value) -> bool:
    text = (value if isinstance(value, str) else json.dumps(value, default=str)).lower()
    return any(w in text for w in _SIGNED_OUT_WORDS)


def bills_of(answer, account: str) -> List[RawDoc]:
    """RawDocs from a billStatements answer for `account`, one per
    statement, known by the account's last four digits and its invoice id
    and dated by its date. An answer with errors, an error or a status
    other than 200 or a message that does not say success in its block, a
    list with no bills, a statement whose id is not one, whose URL is not
    that id's PDF, whose date is not a calendar date, one id twice, or a
    list as long as was asked for (there may be more) stops the list,
    carrying what was read before it. A 401 or 403 in the block, or words
    that say the session ended, raise SessionExpired."""
    if not _ACCOUNT_RE.fullmatch(account or ""):
        raise ListStopped("the bill list names no account number")
    last4 = account[-4:]
    if not isinstance(answer, dict):
        raise ListStopped("the bill list answer is not an object")
    if answer.get("errors"):
        if _says_signed_out(answer.get("errors")):
            raise SessionExpired("the account API said the session has ended")
        raise ListStopped("the account API answered the bill list with errors")
    data = answer.get("data")
    block = data.get("billStatements") if isinstance(data, dict) else None
    if not isinstance(block, dict):
        raise ListStopped("the account API answered with no bill list")
    status, said = block.get("APIStatus"), block.get("message")
    if str(status) in ("401", "403") or (block.get("error") and _says_signed_out(said)):
        raise SessionExpired("the account API said the session has ended")
    if block.get("error"):
        raise ListStopped("the account API answered the bill list with an error")
    if str(status) != "200":
        shown = status if isinstance(status, int) and not isinstance(status, bool) else "that is not one"
        raise ListStopped(f"the account API answered the bill list with status {shown}")
    if said not in (None, "") and not (isinstance(said, str) and _SUCCESS_RE.fullmatch(said.strip())):
        raise ListStopped("the account API answered the bill list with a message")
    rows = block.get("billStatements")
    if not isinstance(rows, list):
        raise ListStopped("the bill list holds no statements")
    if not rows:
        raise ListStopped("the bill list holds no bills, and a history with none has not been seen")
    docs: List[RawDoc] = []
    ids = set()
    for r in rows:
        if not isinstance(r, dict):
            raise ListStopped("a statement is not an object", docs)
        inv = str(r.get("id") or "")
        if not INVOICE_ID_RE.fullmatch(inv):
            raise ListStopped("a statement's id is not one this can read", docs)
        if str(r.get("url") or "") != invoice_url(inv):
            raise ListStopped("a statement's address is not its own PDF", docs)
        iso = bill_day(r.get("date"))
        if not iso:
            raise ListStopped("a statement's date is not a calendar date", docs)
        if inv in ids:
            raise ListStopped("two statements carry one id", docs)
        ids.add(inv)
        title = f"Ziply Fiber Bill {iso}"
        docs.append(RawDoc(title=title, account=f"XXXX-{last4}", date_text=iso, href=DOWNLOAD_PATH,
                           text=title, row_index=len(docs), kind="statement",
                           document_id=f"bill-{last4}-{inv}"))
    if len(rows) >= BILLS_ASKED:
        raise ListStopped(f"the bill list holds all {BILLS_ASKED} asked for, so there may be more", docs)
    return docs


def goto_documents(page) -> bool:
    """Open Billing and take its account. False when it showed the sign-in
    page, settled elsewhere, or never asked."""
    try:
        _open(page)
        return True
    except (SessionExpired, ListStopped) as e:
        log.info("Billing did not open: %s", e)
        return False


def bill_list_opens(page) -> bool:
    """Whether the bill list could be read whole, which only a signed-in
    page allows."""
    try:
        collect_download_docs(page)
        return True
    except (SessionExpired, ListStopped) as e:
        log.info("the bill list could not be read: %s", e)
        return False


def scroll_full_page(page, rounds: int = 8, delay_ms: int = 600) -> None:
    try:
        for _ in range(rounds):
            page.mouse.wheel(0, 3000)
            page.wait_for_timeout(delay_ms)
    except Exception:
        pass


def expand_all(page) -> None:
    """Nothing to press: the bill list is asked for whole."""
    return None


# The list as this run last read it, with the session it was read with, so
# each bill is not a fresh reading of the whole list. In memory for the run
# only.
_RUN: dict = {}


def _read(page) -> List[RawDoc]:
    _RUN.clear()
    session = _open(page)
    bills = bills_of(_ask_statements(page, session), session.account)
    _RUN.update(session=session, bills=bills)
    return bills


def collect_download_docs(page) -> List[RawDoc]:
    """Every bill Ziply lists, kept for this run's downloads. Nothing is
    pressed. A list that cannot be read whole raises ListStopped holding
    what was read, and a signed-out session raises SessionExpired."""
    return _read(page)


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


def _fetch(page, invoice_id: str, out_path: Path, trace: Optional[list]) -> bool:
    """GET the bill's PDF address from inside the signed-in page, the way
    its View PDF link opens it, and keep the body only when it is a PDF."""
    url = invoice_url(invoice_id)
    if not url:
        return False
    try:
        got = intake.evaluate(page, _PDF_JS, [url, MAX_PDF_BYTES], limit=MAX_PDF_BYTES) or {}
    except intake.TooLarge:
        return False
    except Exception as e:
        log.info("fetching the bill failed (%s)", type(e).__name__)
        if trace is not None:
            trace.append({"note": "fetch failed", "error": type(e).__name__})
        return False
    ctype = str(got.get("type") or "").split(";", 1)[0].strip().lower()
    if trace is not None:
        trace.append({"note": "fetched", "host": "ziplyfiber.com", "status": got.get("status"), "type": ctype[:30]})
    if got.get("redirected") or got.get("status") in (401, 403):
        raise SessionExpired("ziplyfiber.com refused the bill")
    if got.get("status") != 200 or not got.get("b64"):
        return False
    try:
        data = intake.decode(got["b64"], validate=True, limit=MAX_PDF_BYTES)
    except Exception:
        return False
    if data[:5] != b"%PDF-":
        # The PDF is asked with the session's cookies alone, so a page in
        # its place is the sign-in page. A JSON answer is about this one
        # bill, which fails alone and is tried again on the next run.
        if data.lstrip()[:1] == b"<":
            raise SessionExpired("ziplyfiber.com answered a bill with a sign-in page")
        if trace is not None:
            trace.append({"note": "the answer is not a PDF"})
        return False
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(data)
    return True


def download_bill(page, dl_dir, iso_date: str, out_path, title: str = "",
                  trace: Optional[list] = None, href: str = "",
                  document_id: str = "") -> bool:
    """Save the bill discovery recorded as `document_id`, its account's last
    four digits and its invoice id, dated `iso_date`. The list this run read
    is used when there is one, and it is read again when there is none or
    the bill is not in it. The bill is fetched only when exactly one
    statement there carries that id and date. A list for another account
    than the one the bill was recorded under raises OtherAccountShown, with
    no reread, since the account shown is the person's choice on the site.
    `dl_dir` is unused. Nothing is pressed. SessionExpired propagates to the
    run, and so does ListStopped when the list cannot be read again, since
    every bill after this one would read the same list."""
    out_path = Path(out_path)
    m = BILL_ID_RE.fullmatch((document_id or "").strip())
    if href != DOWNLOAD_PATH or not m:
        log.info("no bill was recorded for this document")
        if trace is not None:
            trace.append({"note": "no recorded bill"})
        return False
    last4, inv = m.group(1), m.group(2)
    found: List[RawDoc] = []
    for fresh in ((False, True) if _RUN else (True,)):
        if fresh:
            _read(page)
        session, bills = _RUN["session"], _RUN["bills"]
        if session.account[-4:] != last4:
            raise OtherAccountShown(last4, session.account[-4:])
        found = [d for d in bills if d.document_id == m.group(0) and d.date_text == (iso_date or "")]
        if len(found) == 1:
            return _fetch(page, inv, out_path, trace)
    log.info("%d statements match the recorded id and date %s, none taken", len(found), iso_date)
    if trace is not None:
        trace.append({"note": "no single statement matches the record", "matches": len(found)})
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
