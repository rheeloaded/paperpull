"""ALL www.spectrum.net selectors, URLs, and page behavior live here.

When Spectrum changes its billing pages, repair this file only.

STATUS. Built from the account owner's read-only survey of 2026-10-12
(signed in, one press of View Printable Statement). An early live run of
2026-10-12/13 saved the newest statement and refused the rest (see below),
which is why an older statement is chosen in page. Run that way on the
owner's account, Discover listed 13 statements of two accounts, Pilot
saved the newest, and Run All saved 10 more, each printing its own date.
It refused the two statements that shared a date, and choosing those by
pressing each row (below) has not been run live yet. Mobile is run live
only as far as MOBILE says.

  * The site is an Angular app on https://www.spectrum.net. All billing data
    comes from the page's own POSTs to https://apis.spectrum.net/selfservice/graph
    (GraphQL), sent with a bearer token the page keeps for itself. This app
    sends no request of its own to that host: it only watches the responses
    the page's own requests get, and from each it reads the exact address,
    the method, the operationName and variables.statementId of the request
    body, the status, and the few response fields it needs. Never a header,
    a cookie, localStorage, the storage state or a whole body.
  * /billing/statements: the page asks fetchAccountStatementList, whose
    answer is data.viewer.account.statementList with statements[{id, date}]
    for the current account and accountTransfers[{accountNumber,
    serviceAddress, statements[{id, date}]}] for an older account the
    service was transferred from. Each id is base64 of
    "Account=<n>|StatementDate=<YYYY-MM-DD>|StatementCode=<n>|PDF_DOCUMENT".
    It carries the account number, so it is a private word, lives only in
    memory, and is decoded only to check that its date is the row's date.
    The rows the page draws (a.kite-list-item__action, "Statement Month D,
    YYYY") must show the same dates, as a check on the answer, never as the
    source of a document.
  * A statement is known by its family and date, "current:2026-09-26" or
    "prior:2026-02-26". Two statements of one date in one family stop the
    list. Before a statement is taken the list is read afresh and exactly one
    entry must carry that family and date.
  * The current account's newest statement is opened by its own address,
    /billing/bill-details?pdfStatementId=<id>&isNextBill=false&
    isAccountTransfer=<bool>, after an exact check of that address. Opened
    that way, an older statement's page also asks for the newest (it draws
    a comparison) and its printable control prints the NEWEST, which the
    live run of 2026-10-12/13 saw for 12 of 13 statements. So every other
    statement is chosen in page, the way a person does: its own row on
    Statements is pressed, after the row guard (is_safe_row) reads its
    words, and the page must move to that statement's own page, its id in
    the page's own spelling (a DIGITAL_DOCUMENT id, unpadded) naming the
    same account and date, isAccountTransfer true for a prior account. Two
    statements of one date, one for each account, have rows nothing tells
    apart before a press, so the first is pressed, and when the page it
    opens is the other statement's own, Statements is read again and the
    second is pressed, which must open this one. The page's own
    AccountDigitalStatementV2 requests
    must name this statement once and otherwise only statements the list
    holds, and every answer must be an answer. Anything unexpected after
    the row press stops the run.
  * "View Printable Statement" makes the page ask FetchStatementPDFEncodedString
    for the same id, whose answer, data.viewer.account.statementPdf, is the
    PDF as base64, and the page turns it into a Blob and opens it in a new tab.
    A hook armed before the one press keeps every Blob the page makes and
    replaces window.open with a recorder that opens nothing. The statement
    is kept only when exactly one such answer came for that id and decodes
    to a PDF, exactly one application/pdf Blob of this origin holds the same
    bytes, no tab opened, no download began, and the tab is still on the
    statement's page. Then the bytes are bound to the statement (bind). The
    PDF's text has to print the statement's date, may not print more of a
    rival's facts than of this one's, and may not be the same file as a
    statement kept earlier in this process or a PDF already in the folder.
    Anything else stops the run.

MOBILE. Built from the survey of 2026-10-13. Spectrum Mobile is a separate
bill, and its site has no PDF of a Mobile statement. The live run of
2026-10-13 listed all 12 Mobile statements and every row press landed on
its statement's page, and the section check was then changed to the page
as it was seen live. A whole Mobile run since that change has not been
reported.
  * Billing (/billing, opened by its address) draws, under Statements, one
    link "Mobile Account Number: <n>" (an anchor with role=link, href
    "javascript:void(0)", non-breaking spaces between its words). Pressing
    it moves the page to /billing/mobile-statements. Whether that address
    opened directly holds the session was not seen, so the link is pressed.
  * The Mobile list draws the statement under way ("Statement October 13
    Auto Pay: ..." with no year), "Your Total So Far ...", the finished
    statements "Statement <Month> <D>, <YYYY>" and an "Order <n> <date>"
    row. Only the finished statements are listed (mobile_days). A Mobile
    statement is known as "mobile:YYYY-MM-DD". Rows that do not draw and
    hold still, and a run whose download folder the browser did not take,
    stop the list, which is then never called whole.
  * Pressing a finished statement's row moves the page to
    /mobile-billing/statement-history?statementId=<id>&newStatementVersion=..
    The page reads "Statement Details", the date ("AUGUST 13, 2026") and
    "Mobile", has collapsed sections, one "Expand All" button and a "Print"
    button that opens the browser's print dialog, which is never pressed.
    The page's own GraphQL answer for the list (fetchMobileDigitalStatements
    ForBillPresentment) was not read, so no statement is opened by its id.
  * A statement is taken by pressing its own row, checking the address is a
    Mobile statement's own and the page reads that date alone and Mobile,
    pressing Expand All, waiting until it reads Collapse All and each of
    the six section buttons (accord-N-button-0) reads aria-expanded="true"
    (seen live 2026-10-13), checking again, and printing the page with
    receipt_pdf.print_page_to_pdf (Page.printToPDF), the way the Venmo app
    prints a month. The PDF's text must print the date, and its bytes may
    not be another statement's. A failed answer to the Mobile list's own
    statements or the statement's own data stops it (MobileWatch); other
    operations' failures, such as the next-bill estimate whose tile then
    reads "This info is currently not available. Please try again later."
    (BENIGN_MESSAGES), are only logged. The statementId values are private words
    the moment the page lands, and no two dates may land on one id.

SESSION: a 401 from the graph, a GraphQL answer with errors to an
operation an Internet statement is read from (Mobile: see MobileWatch,
where another operation's errors are only logged), the sign-in
page (/login, id.spectrum.net), a validateSession answer saying the session
is not valid, or the idle-timeout dialog raise SessionExpired. A one-time
passcode prompt raises OtpRequired. The run stops for the account holder at
either. Nothing is filled in, nothing is recorded against the document.

SAFETY (an account that can pay, enroll in Auto Pay and paperless, change
service and buy equipment):
  Strictly READ-ONLY. Five controls are ever pressed, each through
  paperpull_core.pressing.click under its own predicate. For Mobile: the
  Billing page's "Mobile Account Number" link (is_mobile_account_link,
  that label with only a number after it), a Mobile statement's own row
  (is_safe_mobile_row, "Statement Month D, YYYY" of its date and nothing
  else), and that statement's "Expand All" (is_expand_all, exactly). For
  Internet: A statement's own
  row on Statements, once, after is_safe_row (a row whose words name
  paying, Auto Pay, paperless, equipment, settings, signing out and the
  rest is refused, and only "Statement Month D, YYYY" of that statement's
  date is allowed). The statement page's "View Printable Statement", once
  per statement, after is_safe_control, which allows that label exactly.
  The href of every anchor pressed is read first. A statement row's must
  lead nowhere or to a www.spectrum.net address with no refused word in
  it (is_safe_href), and the Mobile link's and a Mobile row's must lead
  nowhere, as the survey saw them (is_void_href).
  Nothing here fills, selects, types or scrolls. No host but
  www.spectrum.net is ever opened.

PRIVACY: the Mobile account number (from its link's words) and a Mobile
statement page's statementId and newStatementVersion are private words
before anything is logged, and no row or heading words are kept. Both
Internet account numbers, the service address (each part of four
letters or more, or with a digit), and every statement id are registered as
private words as soon as the list answer is read, before anything is
logged. Records keep the family label, the date and a fixed title only.

KNOWN CEILINGS
  * Mobile statements are printed from the page, since the site has none
    as a PDF. A Mobile list that draws a statement row in a shape not
    seen, two rows of one date or two Mobile accounts stops the list.
  * A one-time passcode, when Spectrum asks for one, stops the run.
  * Two statements of one date (one for each account after a transfer)
    are left for a manual save.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import logging
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import date as _date
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import unquote, urlencode, urlsplit

from paperpull_core import pdf_reader
from paperpull_core import intake
from paperpull_core import pressing, receipt_pdf
from paperpull_core.controls import SETTINGS_CONTROL_RE, AUTH_CONTROL_RE
from paperpull_core.redact import private_words, redact, set_private_words  # noqa: F401  (re-exported)
from paperpull_core.urls import is_safe_url as _host_allows
from paperpull_core.identity import (REFUSED, UNREADABLE, VERIFIED, Identity, distinguish,
                                     verify)
from paperpull_core.dates import last_day as _last_day
from paperpull_core.dates import checked as _checked_date
from paperpull_core.dates import full_year as _full_year
# re-exported: the docs module calls it as site.set_download_dir
from paperpull_core.capture import set_download_dir  # noqa: F401
from paperpull_core.words import words_for as _words_for
from paperpull_core.characters import whole_characters, whole_json

log = logging.getLogger("spectrum_docs.site")


def _words():
    """This app's own words for paperpull_core.words."""
    return _words_for("Spectrum", sys.modules[__name__])


# ---------------------------------------------------------------------------
# Addresses
# ---------------------------------------------------------------------------
HOST = "www.spectrum.net"
BASE = f"https://{HOST}"
STATEMENTS_PATH = "/billing/statements"
DETAIL_PATH = "/billing/bill-details"
STATEMENTS_URL = BASE + STATEMENTS_PATH
BILLING_URL = STATEMENTS_URL
DOCUMENTS_URL = STATEMENTS_URL
URLS = {
    "home": f"{BASE}/",
    "login": f"{BASE}/login",
    "documents": STATEMENTS_URL,
    "statements": STATEMENTS_URL,
}

# The page's own API. Watched, never asked.
GRAPH_URL = "https://apis.spectrum.net/selfservice/graph"
SESSION_CHECK_PATH = "/auth/oauth/v2/validateSession"
API_HOST = "apis.spectrum.net"

LIST_OPERATION = "fetchAccountStatementList"
DETAIL_OPERATION = "AccountDigitalStatementV2"
PDF_OPERATION = "FetchStatementPDFEncodedString"

LOGIN_URL_MARKERS = ["/login", "/logout", "id.spectrum.net", "/signin", "/error/session-expired"]

# ---------------------------------------------------------------------------
# HARD SAFETY GUARD
# ---------------------------------------------------------------------------
FORBIDDEN_CONTROL_RE = re.compile(
    r"(\bpay\b|\bpaying\b|\bpayments?\b|\bautopay\b|\bauto\s*-?\s*pay\b|\bpaperless\b|\benroll|"
    r"\bsettings?\b|\bequipment\b|\bupgrades?\b|\badd\b|\bchang(e|es|ed|ing)\b|\bcancel|"
    r"\bservices?\b|\bappointments?\b|\bchat\b|\bsign\s*(out|off)\b|\blog\s*(out|off)\b|\blogout\b|"
    r"\bone\s*-?\s*time\b|\bverify\b|\bcodes?\b|\bmobile\b|\border\b|\bshop\b|\bdeals?\b|\bcall\b|"
    r"\bsubmit\b|\bconfirm\b|\bcontinue\b|\bdelete\b|\bremove\b|\bupdate\b|\bedit\b|\bmanage\b|"
    r"\bpreferences?\b|\bprofile\b|\bagree\b|\baccept\b|\bauthori[sz]e\b|\bpassword\b|\busername\b)", re.I)

# The one control this app presses, whole and nothing else.
SAFE_LABEL = "view printable statement"
PRINTABLE_RE = re.compile(r"^\s*view\s+printable\s+statement\s*$", re.I)

SECURITY_CHALLENGE_MARKERS = ["are you a robot", "captcha", "access denied", "unusual activity"]
RATE_LIMIT_MARKERS = ["too many requests", "rate limit", "try again later",
                      "temporarily unavailable", "http error 429"]
# What the page shows when it wants a one-time passcode, and when its idle
# timer is about to sign the session out (or has).
OTP_MARKERS = ["one-time passcode", "one time passcode", "one-time code", "verification code",
               "enter the code", "we sent a code"]
IDLE_MARKERS = ["your session is about to expire", "session is about to time out",
                "are you still there", "your session has expired", "session timed out",
                "you have been signed out"]

STATEMENT_ROW = "a.kite-list-item__action"
PRINTABLE_BUTTON = "button:has-text('View Printable Statement')"

FALLBACK = {
    "doc_row": STATEMENT_ROW,
    "doc_link": STATEMENT_ROW,
    "download_control": PRINTABLE_BUTTON,
    "page_ready": STATEMENT_ROW,
}

# ---------------------------------------------------------------------------
# Date parsing (verbatim from the Optum app; the list answer uses
# iso_day below, which reads one shape only)
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
    """The date this provider's page is showing, as YYYY-MM-DD, or None for
    a day that does not exist."""
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


def valid_iso(text) -> bool:
    """Whether `text` is exactly a calendar day as YYYY-MM-DD."""
    t = str(text or "")
    if not re.fullmatch(r"(?:19|20)\d{2}-\d{2}-\d{2}", t):
        return False
    try:
        return _date.fromisoformat(t).isoformat() == t
    except ValueError:
        return False


def iso_day(value) -> Optional[str]:
    """The day of a list answer's date, "2026-09-26T00:00:00-05:00" or
    "2026-09-26", as YYYY-MM-DD, or None. The day is read as written, never
    moved between time zones."""
    m = re.fullmatch(r"(\d{4}-\d{2}-\d{2})(?:T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?",
                     str(value or "").strip())
    if not m or not valid_iso(m.group(1)):
        return None
    return m.group(1)


_ROW_DATE_RE = re.compile(
    r"^Statement (January|February|March|April|May|June|July|August|September|October|November|December) "
    r"(\d{1,2}), (\d{4})\b")


def row_day(text) -> Optional[str]:
    """The date a drawn statement row starts with, "Statement September 26,
    2026 ...", as YYYY-MM-DD, or None."""
    m = _ROW_DATE_RE.match(re.sub(r"\s+", " ", str(text or "")).strip())
    if not m:
        return None
    try:
        return _date(int(m.group(3)), _MONTHS[m.group(1)[:3].lower()], int(m.group(2))).isoformat()
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Session / safety
# ---------------------------------------------------------------------------

class SessionExpired(Exception):
    """Spectrum answered as a signed-out session: its sign-in page, a 401 or
    an answer with errors from its own API, a session check saying the
    session is not valid, or its idle-timeout dialog. The run stops for the
    account holder."""


class OtpRequired(Exception):
    """Spectrum asks for a one-time passcode. Nothing is filled in, and the
    run stops for the account holder."""


class ListStopped(Exception):
    """The list has a part this could not read, so what was read is not all
    of it. `docs` holds what was read before it stopped."""

    def __init__(self, why: str, docs=None):
        super().__init__(why)
        self.docs = list(docs or [])


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


def _body_text(page, limit: int = 4000) -> str:
    """The page's visible words, lowercase. Never logged."""
    try:
        return (page.locator("body").inner_text(timeout=5000) or "")[:limit].lower()
    except Exception:
        return ""


def otp_prompt(page) -> bool:
    """Whether the page shows a one-time passcode prompt."""
    hay = _body_text(page)
    return any(m in hay for m in OTP_MARKERS)


def idle_dialog(page) -> bool:
    """Whether the page shows its idle-timeout dialog."""
    hay = _body_text(page)
    return any(m in hay for m in IDLE_MARKERS)


# Page messages that carry a rate-limit phrase and are not one. The Mobile
# list's estimated-next-bill tile, when its own answer fails, reads (live,
# 2026-10-13): "Looking for your next bill? This info is currently not
# available. Please try again later." That sentence, whole, is taken out
# before the rate-limit phrases are looked for, so the same phrase anywhere
# else on the page still counts.
BENIGN_MESSAGES = [
    re.compile(r"this info is currently not available\. please try again later\."),
]


def detect_security_challenge(page) -> Optional[str]:
    """Names a robot check or throttling notice on screen, or None. Visible
    text only. A one-time passcode prompt is not this: it raises
    OtpRequired where it is met. A page message known to be benign
    (BENIGN_MESSAGES) is not read as throttling; a robot check is looked
    for on the whole text."""
    hay = re.sub(r"\s+", " ", _body_text(page, 2500))
    for m in SECURITY_CHALLENGE_MARKERS:
        if m in hay:
            return f"Security challenge detected: '{m}'"
    for benign in BENIGN_MESSAGES:
        hay = benign.sub(" ", hay)
    for m in RATE_LIMIT_MARKERS:
        if m in hay:
            return f"Possible rate limiting detected: '{m}'"
    return None


def check_page(page) -> None:
    """Raise SessionExpired for the sign-in page or the idle dialog, and
    OtpRequired for a passcode prompt. Reads only."""
    if looks_signed_out(page) or idle_dialog(page):
        raise SessionExpired("Spectrum showed a signed-out page")
    if otp_prompt(page):
        raise OtpRequired("Spectrum asks for a one-time passcode")


def normalized(label) -> str:
    return re.sub(r"\s+", " ", str(label or "")).strip().lower()


def is_safe_control(name: str) -> bool:
    """Deny by default: an unreadable label is refused, then this app's
    blocklist, then the shared core guards, and only then the one label
    this app presses, "View Printable Statement", whole."""
    label = normalized(name)
    if not label:
        return False
    if FORBIDDEN_CONTROL_RE.search(label):
        return False
    if SETTINGS_CONTROL_RE.search(label) or AUTH_CONTROL_RE.search(label):
        return False
    return label == SAFE_LABEL


# ---------------------------------------------------------------------------
# Hosts. One exact host for pages; the same origin, exactly, for the blob a
# press makes.
# ---------------------------------------------------------------------------
ALLOWED_HOSTS = {HOST}
BLOB_ORIGIN = BASE


def is_safe_url(url: str) -> bool:
    """True only for an https URL on exactly www.spectrum.net."""
    return _host_allows(url, ALLOWED_HOSTS, subdomains=False)


def is_download_url(url: str) -> bool:
    """True only for a blob: URL whose origin is exactly www.spectrum.net."""
    u = str(url or "")
    if not u.startswith("blob:"):
        return False
    try:
        parts = urlsplit(u[len("blob:"):])
        port = parts.port
    except ValueError:
        return False
    return (parts.scheme == "https" and (parts.hostname or "").lower() == HOST
            and port is None and not parts.username and not parts.password)


_DETAIL_FIELDS = {"pdfStatementId", "isNextBill", "isAccountTransfer"}


def _query_pairs(query: str) -> List[Tuple[str, str]]:
    """The name and value pairs of an address's query, each value
    percent-decoded as written. A "+" stays a "+", since a statement id is
    base64 and base64 has "+" in it, where parse_qsl would make it a space.
    ValueError for a part with no "=" or an empty name."""
    pairs = []
    for part in (query or "").split("&"):
        if "=" not in part:
            raise ValueError("a query part has no value")
        name, value = part.split("=", 1)
        if not name:
            raise ValueError("a query part has no name")
        pairs.append((unquote(name), unquote(value)))
    return pairs


def _detail_query(url: str) -> Optional[dict]:
    """The query of a statement's own page, or None for any other address.
    https, exactly www.spectrum.net, no port, credentials or fragment,
    exactly the path /billing/bill-details, and a query of pdfStatementId,
    isNextBill=false and isAccountTransfer=true or false, each once and
    nothing more."""
    if not is_safe_url(url):
        return None
    try:
        parts = urlsplit(url)
        if parts.port is not None or parts.fragment or parts.path != DETAIL_PATH:
            return None
        pairs = _query_pairs(parts.query)
    except ValueError:
        return None
    keys = [k for k, _ in pairs]
    if set(keys) != _DETAIL_FIELDS or len(keys) != len(_DETAIL_FIELDS):
        return None
    q = dict(pairs)
    if q["isNextBill"] != "false" or q["isAccountTransfer"] not in ("true", "false"):
        return None
    return q


def is_detail_url(url: str, statement_id: str = "") -> bool:
    """A statement's own page as this app opens it by address and nothing
    else (see _detail_query), its pdfStatementId one statement's PDF id.
    With `statement_id`, the id must be that one."""
    q = _detail_query(url)
    if q is None:
        return False
    if statement_id and q["pdfStatementId"] != statement_id:
        return False
    try:
        decode_statement_id(q["pdfStatementId"])
    except ListStopped:
        return False
    return True


def lands_on(url: str, entry: "Entry") -> bool:
    """Whether the page a press of the entry's row moved to is that
    statement's own page. The address has the shape _detail_query reads,
    its pdfStatementId names the same account and date as the entry, in
    the page's PDF or digital spelling with or without its padding, and its
    isAccountTransfer is true for a prior account's statement and false for
    the current account's."""
    q = _detail_query(url)
    if q is None:
        return False
    if q["isAccountTransfer"] != ("true" if entry.family == PRIOR else "false"):
        return False
    return same_statement(q["pdfStatementId"], entry.statement_id)


def detail_url(statement_id: str, transfer: bool) -> str:
    """The address of the statement with this id, or "" when it would not
    pass is_detail_url."""
    query = urlencode([("pdfStatementId", statement_id or ""), ("isNextBill", "false"),
                       ("isAccountTransfer", "true" if transfer else "false")])
    url = f"{BASE}{DETAIL_PATH}?{query}"
    return url if is_detail_url(url, statement_id) else ""


# ---------------------------------------------------------------------------
# Statement ids and the list answer
# ---------------------------------------------------------------------------
_B64_RE = re.compile(r"[A-Za-z0-9+/]+={0,2}")
_ID_TEXT_RE = re.compile(
    r"Account=([0-9]{4,32})\|StatementDate=(\d{4}-\d{2}-\d{2})\|StatementCode=([0-9]{1,6})\|PDF_DOCUMENT")
# The list names a statement by a PDF_DOCUMENT id, the statement's own page
# asks for it by a DIGITAL_DOCUMENT id of the same account, date and code.
_ANY_ID_TEXT_RE = re.compile(
    r"Account=([0-9]{4,32})\|StatementDate=(\d{4}-\d{2}-\d{2})\|StatementCode=([0-9]{1,6})\|(PDF|DIGITAL)_DOCUMENT")

CURRENT, PRIOR, MOBILE = "current", "prior", "mobile"
FAMILY_LABEL = {CURRENT: "Internet", PRIOR: "Internet (prior account)", MOBILE: "Mobile"}
TITLE = "Spectrum Internet Statement"
MOBILE_TITLE = "Spectrum Mobile Statement"
DOCUMENT_ID_RE = re.compile(r"(current|prior|mobile):((?:19|20)\d{2}-\d{2}-\d{2})")


def decode_statement_id(statement_id) -> Tuple[str, str]:
    """(account number, statement date) inside a statement id, or
    ListStopped. The reason never carries the id or what it decodes to."""
    sid = str(statement_id or "")
    if not _B64_RE.fullmatch(sid) or len(sid) % 4:
        raise ListStopped("a statement id is not base64")
    try:
        text = base64.b64decode(sid, validate=True).decode("ascii")
    except (binascii.Error, ValueError):
        raise ListStopped("a statement id does not decode")
    m = _ID_TEXT_RE.fullmatch(text)
    if not m:
        raise ListStopped("a statement id is not a PDF statement's")
    if not valid_iso(m.group(2)):
        raise ListStopped("a statement id's date is not a calendar date")
    return m.group(1), m.group(2)


def same_statement(a, b) -> bool:
    """Whether two statement ids name one statement: the same account and
    statement date, whether the page spells it as a PDF_DOCUMENT or a
    DIGITAL_DOCUMENT. The code inside the id is the document's, not the
    statement's: the list's PDF id and the page's digital id for one month
    carry different codes, so it is not compared. One account has one
    statement a date (the list stops otherwise), so account and date name
    it. False for an id that does not decode."""
    def pair(sid):
        # The page's own id for a statement comes without its base64 padding.
        raw = str(sid or "")
        raw += "=" * (-len(raw) % 4)
        text = base64.b64decode(raw, validate=True).decode("ascii")
        m = _ANY_ID_TEXT_RE.fullmatch(text)
        return (m.group(1), m.group(2)) if m else None
    try:
        pa, pb = pair(a), pair(b)
    except (binascii.Error, ValueError):
        return False
    return pa is not None and pa == pb


@dataclass
class Entry:
    """One statement as the list answer gives it. The id is kept in memory
    only and never printed (repr=False)."""
    family: str
    date: str
    statement_id: str = field(default="", repr=False)

    @property
    def document_id(self) -> str:
        return f"{self.family}:{self.date}"


def _parts(value) -> List[str]:
    """The parts of a value that are private words: each part of four
    letters or more, or with a digit, as redact applies them anywhere in a
    string. "CA" or "St" would turn "CAPTCHA" and "Statement" into "[name]"."""
    out = []
    text = str(value or "").strip()
    if not text:
        return out
    if len(text) >= 4 and not re.search(r"\s", text):
        out.append(text)
    for part in re.split(r"[\s,.#/|=-]+", text):
        if len(part) >= 4 or re.search(r"[0-9]", part):
            out.append(part)
    return out


def _strings(node) -> List[str]:
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        return [s for v in node.values() for s in _strings(v)]
    if isinstance(node, list):
        return [s for v in node for s in _strings(v)]
    return []


def private_words_of(statement_list) -> List[str]:
    """Every value of a list answer that names the account: the transfer
    accounts' numbers and service addresses, each statement id and the
    account number inside it. Read defensively, before anything is
    checked, so they are private before any reason is said."""
    words: List[str] = []
    if not isinstance(statement_list, dict):
        return words
    groups = [statement_list.get("statements")]
    for t in statement_list.get("accountTransfers") or []:
        if isinstance(t, dict):
            words += _parts(t.get("accountNumber"))
            for s in _strings(t.get("serviceAddress")):
                words += _parts(s)
            groups.append(t.get("statements"))
    for group in groups:
        for s in group if isinstance(group, list) else []:
            sid = s.get("id") if isinstance(s, dict) else None
            if isinstance(sid, str) and sid:
                words.append(sid)
                try:
                    words.append(base64.b64decode(sid + "=" * (-len(sid) % 4)).decode("ascii", "replace"))
                except (binascii.Error, ValueError):
                    pass
                m = re.search(r"Account=([0-9A-Za-z]+)", words[-1])
                if m:
                    words.append(m.group(1))
    return [w for w in words if w]


def register_private(words) -> None:
    """Add words to the private words, each once."""
    have = list(private_words())
    new = [w for w in dict.fromkeys(words) if w and w not in have]
    if new:
        set_private_words(have + new)


def statement_list_of(answer) -> dict:
    """data.viewer.account.statementList of a fetchAccountStatementList
    answer. An answer with errors is a signed-out session, and any other
    shape stops the list."""
    if not isinstance(answer, dict):
        raise ListStopped("the statement list answer is not an object")
    if answer.get("errors"):
        raise SessionExpired("the statement list answer carries errors")
    try:
        found = answer["data"]["viewer"]["account"]["statementList"]
    except (KeyError, TypeError):
        raise ListStopped("the statement list answer has no statementList")
    if not isinstance(found, dict):
        raise ListStopped("the statementList is not an object")
    return found


def entries_of(statement_list: dict) -> List[Entry]:
    """Every statement of the current account and of the accounts transferred
    from, as Entries. The private words are registered first. A statement
    whose id is not a PDF statement's, whose id's date is not its date, two
    statements of one date in one family, or a family whose statements name
    two accounts stop the list."""
    register_private(private_words_of(statement_list))
    current = statement_list.get("statements")
    transfers = statement_list.get("accountTransfers")
    if not isinstance(current, list):
        raise ListStopped("the statement list has no statements")
    if transfers is None:
        transfers = []
    if not isinstance(transfers, list):
        raise ListStopped("the account transfers are not a list")
    out: List[Entry] = []

    def read(group, family: str, account: Optional[str]) -> None:
        seen = set()
        accounts = set()
        for s in group:
            if not isinstance(s, dict):
                raise ListStopped("a statement is not an object")
            day = iso_day(s.get("date"))
            if not day:
                raise ListStopped("a statement's date is not a calendar date")
            inside_account, inside_day = decode_statement_id(s.get("id"))
            if inside_day != day:
                raise ListStopped("a statement id's date is not its row's date")
            if account is not None and inside_account != account:
                raise ListStopped("a transferred account's statement names another account")
            accounts.add(inside_account)
            if day in seen:
                raise ListStopped("two %s statements carry one date" % family)
            seen.add(day)
            out.append(Entry(family, day, s["id"]))
        if len(accounts) > 1:
            raise ListStopped("the %s statements name more than one account" % family)

    read(current, CURRENT, None)
    prior_days: set = set()
    for t in transfers:
        if not isinstance(t, dict):
            raise ListStopped("an account transfer is not an object")
        number = str(t.get("accountNumber") or "").strip()
        group = t.get("statements")
        if not number or not isinstance(group, list):
            raise ListStopped("an account transfer has no account number or statements")
        before = len(out)
        read(group, PRIOR, number)
        for e in out[before:]:
            if e.date in prior_days:
                raise ListStopped("two prior statements carry one date")
            prior_days.add(e.date)
    return out


@dataclass
class RawDoc:
    title: str
    account: str = ""
    date_text: str = ""
    href: str = ""
    text: str = ""
    row_index: int = -1
    kind: str = "doc"
    # "current:YYYY-MM-DD" or "prior:YYYY-MM-DD", never a statement id.
    document_id: str = ""


def raw_docs(entries: List[Entry]) -> List[RawDoc]:
    out = []
    for i, e in enumerate(entries):
        title = MOBILE_TITLE if e.family == MOBILE else TITLE
        out.append(RawDoc(title=title, account=FAMILY_LABEL[e.family], date_text=e.date, href="",
                          text=title, row_index=i, kind="statement", document_id=e.document_id))
    return out


# ---------------------------------------------------------------------------
# Watching the page's own API
# ---------------------------------------------------------------------------

class Watch:
    """The answers the page's own requests get, while armed.

    Kept: each answer to a POST of exactly GRAPH_URL whose request body's
    operationName is `operation` (with whether its variables.statementId is
    `statement_id`), the status of every answer to a POST of GRAPH_URL, and
    each answer to the session check. A response object is kept to be read
    after the wait, never inside the listener, and only the fields named in
    read_* are read from it. Nothing else of a request or a response is
    looked at, and nothing of one is logged."""

    def __init__(self, page, operation: str, statement_id: str = ""):
        self.page = page
        self.operation = operation
        self.statement_id = statement_id
        # [(response, its statementId names `statement_id`, that statementId)].
        # The id is a private word, kept in memory to be compared only.
        self.hits: list = []
        self.statuses: list = []    # every graph answer's status
        self.sessions: list = []    # session-check responses
        self._listener = None

    def start(self) -> "Watch":
        watch = self

        def on_response(response):
            watch.heard(response)
        self._listener = on_response
        self.page.on("response", on_response)
        return self

    def stop(self) -> None:
        if self._listener is not None:
            try:
                self.page.remove_listener("response", self._listener)
            except Exception:
                pass
            self._listener = None

    def heard(self, response) -> None:
        try:
            request = response.request
            url = request.url
            method = request.method
        except Exception:
            return
        try:
            parts = urlsplit(url)
        except ValueError:
            return
        if method == "GET" and parts.scheme == "https" and parts.hostname == API_HOST \
                and parts.path == SESSION_CHECK_PATH:
            self.sessions.append(response)
            return
        if url != GRAPH_URL or method != "POST":
            return
        try:
            self.statuses.append(int(response.status))
        except Exception:
            self.statuses.append(0)
        try:
            body = whole_json(json.loads(request.post_data or ""))
        except (TypeError, ValueError):
            return
        if not isinstance(body, dict) or body.get("operationName") != self.operation:
            return
        variables = body.get("variables") if isinstance(body.get("variables"), dict) else {}
        asked = variables.get("statementId")
        asked = asked if isinstance(asked, str) else ""
        self.hits.append((response, bool(self.statement_id) and same_statement(asked, self.statement_id),
                          asked))

    def check_session(self) -> None:
        """SessionExpired for a 401 from the graph or a session check that
        says the session is not valid."""
        if 401 in self.statuses:
            raise SessionExpired("Spectrum's API answered 401")
        for response in list(self.sessions):
            try:
                status = int(response.status)
            except Exception:
                continue
            if status == 401:
                raise SessionExpired("Spectrum's session check answered 401")
            try:
                answer = whole_json(response.json())
            except Exception:
                continue
            if isinstance(answer, dict) and answer.get("isValidSession") is False:
                raise SessionExpired("Spectrum's session check says the session is not valid")

    def wait(self, polls: int = 60, delay_ms: int = 500, also=None) -> None:
        """Wait for the first answer, then until the count has held still
        for three polls, so a second answer lands in the count rather than
        after it. `also` adds a count of its own to what has to hold still."""
        seen, still = None, 0
        for _ in range(polls):
            self.page.wait_for_timeout(delay_ms)
            now = (len(self.hits), also() if also else 0)
            if now[0] and now == seen:
                still += 1
                if still >= 3:
                    return
            else:
                still = 0
            seen = now


def answer_of(response) -> dict:
    """A graph answer's JSON, SessionExpired for a 401 or an answer with
    errors, ListStopped for anything that is not an answer."""
    try:
        status = int(response.status)
    except Exception:
        status = 0
    if status == 401:
        raise SessionExpired("Spectrum's API answered 401")
    if status != 200:
        raise ListStopped("Spectrum's API answered %d" % status)
    try:
        answer = whole_json(response.json())
    except Exception:
        raise ListStopped("Spectrum's API answer is not JSON")
    if not isinstance(answer, dict):
        raise ListStopped("Spectrum's API answer is not an object")
    if answer.get("errors"):
        raise SessionExpired("Spectrum's API answer carries errors")
    return answer


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

def tabs_now(page) -> list:
    """The tabs open before a navigation or a press, so a tab that opened
    can be told from one that was already there."""
    try:
        return list(page.context.pages)
    except Exception:
        return []


def _opened_since(page, before: list) -> list:
    """Tabs that opened since `before`, by identity, closed again here since
    this app opens none. When the tabs cannot be read, that counts as a tab
    that opened, so nothing is taken on a guess."""
    try:
        extra = [p for p in page.context.pages
                 if p is not page and not any(p is q for q in before)]
    except Exception:
        return [None]
    for p in extra:
        try:
            p.close()
        except Exception:
            pass
    return extra


def _on_path(page, path: str) -> bool:
    url = page.url or ""
    try:
        return is_safe_url(url) and urlsplit(url).path.rstrip("/") == path
    except ValueError:
        return False


_ROWS_JS = r"""() => Array.from(document.querySelectorAll('a.kite-list-item__action'))
  .map(a => (a.innerText || '').replace(/\s+/g, ' ').trim())"""


def _row_days(page) -> Optional[list]:
    """The dates the drawn statement rows start with. None when a row that
    reads "Statement ..." has no date this can read. Row text is never kept
    or logged."""
    try:
        texts = page.evaluate(_ROWS_JS) or []
    except Exception:
        return None
    days = []
    for t in texts:
        if not re.match(r"^\s*statement\b", str(t or ""), re.I):
            continue
        d = row_day(t)
        if not d:
            return None
        days.append(d)
    return days


def corroborate(entries: List[Entry], days: Optional[list]) -> None:
    """The drawn rows show the dates the list answer gives, as many times
    each, or ListStopped. The rows are a check on the answer only."""
    if days is None:
        raise ListStopped("a drawn statement row has no date this can read")
    if Counter(days) != Counter(e.date for e in entries):
        raise ListStopped("the drawn rows do not show the statements the list answer gives")


def read_statement_list(page) -> List[Entry]:
    """Open Statements by its address with the list watch armed first, take
    the one fetchAccountStatementList answer the page's own request got, and
    check it against the drawn rows. SessionExpired, OtpRequired or
    ListStopped otherwise."""
    watch = Watch(page, LIST_OPERATION).start()
    try:
        before = tabs_now(page)
        try:
            page.goto(STATEMENTS_URL, wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            log.info("opening Statements failed (%s)", type(e).__name__)
            check_page(page)
            raise ListStopped("Statements did not open")
        if _opened_since(page, before):
            raise ListStopped("opening Statements opened another tab, which was closed")
        check_page(page)
        if not _on_path(page, STATEMENTS_PATH):
            raise ListStopped("Statements settled off its own address")
        watch.wait()
        watch.check_session()
        check_page(page)
        if len(watch.hits) != 1:
            raise ListStopped("%d statement list answers came, not one" % len(watch.hits))
        entries = entries_of(statement_list_of(answer_of(watch.hits[0][0])))
    finally:
        watch.stop()
    days = _row_days(page)
    for _ in range(20):
        if days is not None and len(days) >= len(entries):
            break
        page.wait_for_timeout(500)
        days = _row_days(page)
    corroborate(entries, days)
    return entries


def goto_documents(page) -> bool:
    """Open Statements by its address and read its list. False when it
    showed a signed-out page, asked for a passcode, settled elsewhere, or
    could not be read. No click."""
    try:
        read_statement_list(page)
        return True
    except (SessionExpired, OtpRequired, ListStopped) as e:
        log.info("Statements did not open: %s", e)
        return False


def statement_list_opens(page) -> bool:
    """What the login check asks: Statements opened and its list was read
    whole, which only a signed-in page allows."""
    return goto_documents(page)


def scroll_full_page(page, rounds: int = 0, delay_ms: int = 0) -> None:
    """Nothing to scroll: the list comes whole from the page's own answer."""
    return None


def expand_all(page) -> None:
    """Nothing to press: every statement is in the one list answer."""
    return None


def collect_download_docs(page, dl_dir=None, mobile: bool = True) -> List[RawDoc]:
    """Every Internet statement Spectrum lists, current and prior account,
    then, with `mobile`, every finished Mobile statement. The Internet list
    presses nothing. The Mobile list is reached by pressing Billing's
    "Mobile Account Number" link (open_mobile_list), which needs the run's
    confirmed download folder `dl_dir`. Without it, Mobile is left unread,
    so the list raises ListStopped holding the Internet statements, as a
    Mobile list that stops does. They are kept and the list is never
    called whole while a part of it was not read."""
    internet = read_statement_list(page)
    if not mobile:
        return raw_docs(internet)
    if not dl_dir:
        # No press is made without the folder, so the Mobile list is not
        # read, and a list with a part unread is not the whole list.
        log.info("the download folder was not confirmed, so the Mobile statements were not opened")
        raise ListStopped("the browser did not take this run's download folder, so the Mobile "
                          "statements were not read", raw_docs(internet))
    try:
        found = mobile_entries(page, dl_dir)
    except ListStopped as stop:
        raise ListStopped("the Mobile list stopped, %s" % stop, raw_docs(internet))
    return raw_docs(internet + found)


# ---------------------------------------------------------------------------
# The press and what it makes
# ---------------------------------------------------------------------------
# The hook keeps the page's own window.open and URL.createObjectURL, and
# _RESTORE_JS puts both back once the press is done with, on every path, so
# the person's tab works as Spectrum made it after the run.
_ARM_JS = r"""() => {
  if (!window.__ppNative) window.__ppNative = {open: window.open, create: URL.createObjectURL};
  window.__pp = {blobs: [], opened: []};
  const oc = window.__ppNative.create.bind(URL);
  URL.createObjectURL = function (b) { const u = oc(b); window.__pp.blobs.push({blob: b, type: (b && b.type) || '', size: (b && b.size) || 0, url: String(u)}); return u; };
  window.open = function (u, t, f) { window.__pp.opened.push(String(u)); return null; };
}"""
_RESTORE_JS = r"""() => {
  const n = window.__ppNative;
  if (!n) return false;
  window.open = n.open; URL.createObjectURL = n.create;
  delete window.__ppNative; delete window.__pp;
  return true;
}"""
_COUNT_JS = r"""() => (window.__pp && window.__pp.blobs.length) || 0"""
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


def pdf_of(answer) -> bytes:
    """The PDF a FetchStatementPDFEncodedString answer carries, or b"" when
    it carries none: data.viewer.account.statementPdf, base64, decoding to
    bytes that start %PDF-."""
    try:
        text = answer["data"]["viewer"]["account"]["statementPdf"]
    except (KeyError, TypeError):
        return b""
    if not isinstance(text, str) or not text:
        return b""
    try:
        data = intake.decode(text, validate=True)
    except (binascii.Error, ValueError, intake.TooLarge):
        return b""
    return data if data[:5] == b"%PDF-" else b""


def accept(pdfs: list, blob_result: dict, *, new_pages: int, popups: int, downloads: int,
           on_route: bool) -> Tuple[bytes, str]:
    """(bytes, "") only when the press brought exactly the one statement and
    nothing else: exactly one answer for the statement's id, `pdfs` being
    [(id matches, decoded bytes)], whose bytes are a PDF, exactly one Blob,
    of type application/pdf, on this origin, holding the same bytes, and no
    address opened but that Blob's, no new tab, popup or download, and the
    tab still on the statement's page. Otherwise (b"", why), our own words."""
    if new_pages or popups:
        return b"", "a tab opened"
    if downloads:
        return b"", "a download began"
    if not on_route:
        return b"", "the tab left the statement's page"
    if len(pdfs) != 1:
        return b"", "%d statement answers came, not one" % len(pdfs)
    matches, data = pdfs[0]
    if not matches:
        return b"", "the statement answer was for another statement"
    if not data:
        return b"", "the statement answer holds no PDF"
    blobs = list((blob_result or {}).get("blobs") or [])
    if len(blobs) != 1:
        return b"", "%d blobs were made, not one" % len(blobs)
    b = blobs[0]
    if str(b.get("type") or "").split(";", 1)[0].strip().lower() != "application/pdf":
        return b"", "the blob is not application/pdf"
    if not is_download_url(str(b.get("url") or "")):
        return b"", "the blob is not on this site's origin"
    opened = list((blob_result or {}).get("opened") or [])
    if any(u != b.get("url") for u in opened) or len(opened) > 1:
        return b"", "the page asked to open something other than the blob"
    try:
        held = intake.decode((blob_result or {}).get("b64") or "", validate=True)
    except (binascii.Error, ValueError, intake.TooLarge):
        return b"", "the blob's bytes could not be read"
    if held != data:
        return b"", "the blob does not hold the statement answer's bytes"
    return data, ""


def _entries(dl_dir) -> Optional[dict]:
    """Each entry of the run's download folder with its size and time, or
    None when the folder cannot be read. Nothing in it is opened.

    The browser deletes or renames a download in its own time, so an entry
    can be listed and gone before its size is read. It is still an entry,
    with None for its size and time (_changed_entries says what that means).
    Until 2026-10-18 one such entry made the whole folder unreadable, and a
    press that brought exactly its statement stopped the run as a download."""
    if not dl_dir:
        return {}
    out = {}
    try:
        for p in Path(dl_dir).iterdir():
            try:
                st = p.stat()
            except FileNotFoundError:
                out[p.name] = None
                continue
            out[p.name] = (st.st_size, st.st_mtime_ns)
    except OSError:
        return None
    return out


def _changed_entries(dl_dir, before: Optional[dict]) -> int:
    """How many entries of the folder are new or rewritten since `before`,
    each removed, since this app keeps nothing a download left. A folder
    that cannot be read counts as one, so nothing is taken on a guess.

    An entry that went as it was read before the press is not in the folder
    after it unless something wrote it again. One that goes as it is read
    after the press counts as changed, whatever it was before, since the
    browser was moving a file there while the folder was read."""
    now = _entries(dl_dir)
    if before is None or now is None:
        return 1
    changed = [name for name, stamp in now.items()
               if stamp is None or name not in before or before[name] != stamp]
    for name in changed:
        try:
            (Path(dl_dir) / name).unlink()
        except OSError:
            pass
    return len(changed)


def _note(trace, **what) -> None:
    if trace is not None:
        trace.append(what)


def refused(why: str):
    """The press was made and did not bring exactly one statement: the run
    stops, since pressing again could do something else."""
    return pressing.no_answer(
        "take a statement", "the press made something other than one statement",
        "View Printable Statement was pressed and did not bring exactly one statement "
        "(%s), so the run stops." % why)


CHOOSE_STEP = "choose a statement"


def chose_wrong(entry: Entry, why: str):
    """The statement's row was pressed and the page did not become exactly
    that statement's own page. The run stops, since the next statement's
    row could do the same."""
    return pressing.no_answer(
        CHOOSE_STEP, "the statement row opened something other than its statement",
        "The statement row dated %s was pressed and did not open exactly that statement "
        "(%s), so the run stops." % (entry.date, why))


def no_folder():
    """The run's download folder was not confirmed, so a download a press
    began could land anywhere. Nothing is pressed and the run stops."""
    return pressing.NotPressed(
        "take a statement", "the browser did not take the download folder",
        ["The browser did not take this run's download folder, so no statement "
         "was pressed and the run stops.",
         "Close the browser, open Spectrum with login.bat again, then run Resume."])


def newest(entries: List[Entry]) -> Optional[Entry]:
    """The current account's newest statement, or None when the current
    account lists none. Its own page, opened by its address, asks for it
    alone and prints it, which the live run of 2026-10-12 saw. Every other
    statement's page opened that way prints this one instead."""
    current = [e for e in entries if e.family == CURRENT]
    return max(current, key=lambda e: e.date) if current else None


def is_safe_row(text, day: str) -> bool:
    """Whether a drawn statement row may be pressed to choose the statement
    dated `day`. Deny by default. Unreadable words are refused, then any
    word of this app's blocklist (pay, payment, Auto Pay, paperless,
    equipment, settings, sign out and the rest), then the shared core
    guards, and only then a row whose words start "Statement Month D, YYYY"
    with exactly that date. The row's own address is read just before the
    press and must pass is_safe_href, so a row whose address holds a refused
    word, or leads off the site, is never pressed and its statement is left
    for a manual save."""
    label = normalized(text)
    if not label or not valid_iso(day):
        return False
    if FORBIDDEN_CONTROL_RE.search(label):
        return False
    if SETTINGS_CONTROL_RE.search(label) or AUTH_CONTROL_RE.search(label):
        return False
    return row_day(text) == day


# What a row or link that only runs the page's own script carries as its
# href, as the survey saw it, with or without the closing semicolon. Since
# November 2026 Spectrum's page writes it with Angular's "unsafe:" in front,
# the mark Angular puts on a script address it will not run as a link, so
# it still leads nowhere. Nothing else after "unsafe:" passes.
_VOID_HREF_RE = re.compile(r"(?:unsafe:)?javascript:void\(0\);?", re.I)


def is_void_href(href) -> bool:
    """Whether an anchor's own href leads nowhere. No href, an empty one and
    "javascript:void(0)" do, and anything else does not."""
    if href is None:
        return True
    if not isinstance(href, str):
        return False
    h = href.strip()
    return not h or bool(_VOID_HREF_RE.fullmatch(h))


def _address_words(part: str) -> str:
    """A path or a query name as words, so the blocklist reads it as it
    reads a label. "/billing/makePayment" reads "billing make Payment"."""
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", part)
    return re.sub(r"[^A-Za-z0-9]+", " ", text).strip()


def _refuses(words: str) -> bool:
    return bool(FORBIDDEN_CONTROL_RE.search(words) or SETTINGS_CONTROL_RE.search(words)
                or AUTH_CONTROL_RE.search(words))


def is_safe_href(href) -> bool:
    """Whether a statement row's own href may stand behind its press. Deny
    by default. One that leads nowhere (is_void_href) passes. Otherwise it
    must be an address on exactly www.spectrum.net, written whole or from
    the site's root, with no port, credentials, fragment, backslash or
    white space, and no word of this app's blocklist or the shared core
    guards in its path, its query's names or its query's values. Anything
    else, another host or scheme, a relative path or a fragment, is
    refused."""
    if is_void_href(href):
        return True
    if not isinstance(href, str):
        return False
    h = href.strip()
    if "\\" in h or "#" in h or re.search(r"[\s\x00-\x1f\x7f]", h):
        return False
    if h.startswith("/") and not h.startswith("//"):
        h = BASE + h
    if not is_safe_url(h):
        return False
    try:
        parts = urlsplit(h)
        if parts.port is not None or parts.username or parts.password:
            return False
        pairs = _query_pairs(parts.query) if parts.query else []
    except ValueError:
        return False
    words = [_address_words(unquote(parts.path))] + [_address_words(k) for k, _ in pairs] + [v for _, v in pairs]
    return not any(_refuses(w) for w in words)


def _flat(text) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def row_for(page, entry: Entry, entries: List[Entry], past: int = -1) -> Tuple[int, str, str]:
    """(index among the drawn rows, its words, "") for the row to press to
    choose `entry`, or (-1, "", why) when there is none. The rows of its date
    must be as many as the statements of its date. Two statements of one
    date, one for each account, draw two rows nothing the survey saw tells
    apart before a press, so the first after the row at `past` is given,
    and the page it opens says whose it is (choose_in_page)."""
    same = sum(1 for e in entries if e.date == entry.date)
    try:
        texts = page.evaluate(_ROWS_JS) or []
    except Exception:
        return -1, "", "the rows could not be read"
    found = [(i, _flat(t)) for i, t in enumerate(texts)
             if re.match(r"^\s*statement\b", str(t or ""), re.I) and row_day(t) == entry.date]
    if len(found) != same:
        return -1, "", "%d rows carry the statement's date, not %d" % (len(found), same)
    found = [f for f in found if f[0] > past]
    if not found:
        return -1, "", "no other row carries the statement's date"
    i, text = found[0]
    if not is_safe_row(text, entry.date):
        return -1, "", "the guard refused the statement's row"
    return i, text, ""


def details_answered(watch: "Watch", entry: Entry, entries: List[Entry]) -> str:
    """An empty string when every AccountDigitalStatementV2 answer the
    statement's page got is an answer, the page asked for this statement
    exactly once, and every other such request named a statement the list
    holds (the page compares against one). Otherwise our own words for what
    was wrong. Every answer is read first, so a 401 or an answer with
    errors raises SessionExpired whatever else is wrong."""
    failed = ""
    for response, _, _ in watch.hits:
        try:
            answer_of(response)
        except ListStopped as stop:
            failed = failed or str(stop)
    if failed:
        return failed
    mine = [h for h in watch.hits if h[1]]
    if len(mine) != 1:
        return "the page asked for this statement %d times, not once" % len(mine)
    for _, matches, asked in watch.hits:
        if not matches and not any(same_statement(asked, e.statement_id) for e in entries):
            return "the page asked for a statement the list does not hold"
    return ""


def open_by_address(page, entry: Entry, entries: List[Entry], trace) -> bool:
    """Open the newest statement's own page by its address and check the
    page asked for it. False, nothing pressed, otherwise."""
    url = detail_url(entry.statement_id, entry.family == PRIOR)
    if not url:
        _note(trace, note="statement address refused")
        return False
    detail = Watch(page, DETAIL_OPERATION, entry.statement_id)
    try:
        detail.start()
        before = tabs_now(page)
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            log.info("opening the statement's page failed (%s)", type(e).__name__)
            check_page(page)
            _note(trace, note="statement page did not open", error=type(e).__name__)
            return False
        if _opened_since(page, before):
            _note(trace, note="a tab opened with the statement's page")
            return False
        check_page(page)
        if not is_detail_url(page.url or "", entry.statement_id):
            _note(trace, note="statement page settled off its address")
            return False
        detail.wait(polls=40)
        detail.check_session()
        check_page(page)
        why = details_answered(detail, entry, entries)
    finally:
        detail.stop()
    if why:
        _note(trace, note="statement page answer refused", why=why, answers=len(detail.hits))
        return False
    return True


def is_its_twin(url: str, entry: Entry, entries: List[Entry]) -> bool:
    """Whether the page a press of the entry's row moved to is the own page of
    the other account's statement of the same date, as lands_on reads it."""
    return any(e.date == entry.date and e.family != entry.family and lands_on(url, e)
               for e in entries)


def choose_in_page(page, entry: Entry, entries: List[Entry], dl_dir, trace, past: int = -1) -> bool:
    """Choose the statement by pressing its own row on Statements, the page
    the list was just read from, so the statement page the app moves to is
    the one chosen and not the newest. False, nothing pressed, when there
    is no row the guard allows for it (row_for), when the row's words
    changed before the press, when its address is refused (is_safe_href),
    or when Spectrum kept it turned off. Once the row is pressed, a tab, a
    popup or a download, a page that is not this statement's own, or a page
    that asked for anything but this statement and one the list holds stops
    the run (chose_wrong). The one exception is the first press of two rows
    of one date landing on the other account's statement of that date:
    Statements is read again and the row after it, `past`, is pressed, once,
    under all of the same checks. SessionExpired and OtpRequired propagate."""
    index, text, why = row_for(page, entry, entries, *([past] if past >= 0 else []))
    if why:
        log.info("the statement dated %s was not chosen: %s", entry.date, why)
        _note(trace, note="no row to choose", why=why)
        return False
    row = page.locator(STATEMENT_ROW).nth(index)
    try:
        now = _flat(row.inner_text(timeout=2000))
        href = row.get_attribute("href", timeout=2000)
    except Exception as e:
        _note(trace, note="the row could not be read", error=type(e).__name__)
        return False
    if now != text or not is_safe_row(now, entry.date):
        _note(trace, note="the row changed before the press")
        return False
    if not is_safe_href(href):
        # The address itself is never logged, since it may carry the statement id.
        log.info("the statement dated %s was not chosen, since the guard refused its row's address", entry.date)
        _note(trace, note="the guard refused the row's address")
        return False
    if not dl_dir:
        raise no_folder()
    detail = Watch(page, DETAIL_OPERATION, entry.statement_id)
    popups: list = []
    downloads: list = []

    def on_popup(popup):
        popups.append(1)

    # Observation only: a download the press began is counted and
    # canceled, and its file, if the browser had already written one,
    # deleted. Nothing of it is read or saved.
    def on_download(download):
        downloads.append(1)
        intake.discard(download)
    pressed = False
    try:
        detail.start()
        page.on("popup", on_popup)
        page.on("download", on_download)
        before = tabs_now(page)
        folder_before = _entries(dl_dir)
        try:
            pressing.click(page, row, css=pressing.LINKS, what="the statement row dated %s" % entry.date,
                           words=_words(), step=CHOOSE_STEP)
        except pressing.TurnedOff:
            log.info("the statement row stayed turned off, so nothing was pressed")
            _note(trace, note="the row is turned off")
            return False
        pressed = True
        detail.wait(polls=40)
        new_pages = len(_opened_since(page, before))
    except (SessionExpired, OtpRequired):
        raise
    except Exception as e:
        if not pressed:
            raise
        raise chose_wrong(entry, "the page could not be read after the press, %s" % type(e).__name__) from None
    finally:
        detail.stop()
        _unlisten(page, (("popup", on_popup), ("download", on_download)))
    try:
        stray = len(downloads) + _changed_entries(dl_dir, folder_before)
        _note(trace, note="row pressed", answers=len(detail.hits), tabs=new_pages, downloads=stray)
        if new_pages or popups:
            raise chose_wrong(entry, "a tab opened")
        if stray:
            raise chose_wrong(entry, "a download began")
        detail.check_session()
        check_page(page)
        twin = past < 0 and is_its_twin(page.url or "", entry, entries)
        if not twin and not lands_on(page.url or "", entry):
            raise chose_wrong(entry, "the page it opened is not that statement's own")
        why = "" if twin else details_answered(detail, entry, entries)
    except (SessionExpired, OtpRequired):
        raise
    except Exception as e:
        raise chose_wrong(entry, "the page could not be read after the press, %s" % type(e).__name__) from None
    if why:
        raise chose_wrong(entry, why)
    if twin:
        _note(trace, note="the row opened the other account's statement of this date")
        read_statement_list(page)
        return choose_in_page(page, entry, entries, dl_dir, trace, past=index)
    return True


def take_statement(page, entry: Entry, out_path: Path, dl_dir=None,
                   trace: Optional[list] = None, entries: Optional[List[Entry]] = None,
                   own_files=()) -> bool:
    """Bring up the statement's own page and press View Printable Statement
    once under the hook. The newest statement's page is opened by its
    address. Every other statement is chosen in page by pressing its row
    (choose_in_page). False, with nothing pressed, when the page or the
    button is not as expected before any press. Once a row was pressed, a
    printable button that is not the one expected stops the run. After the
    printable press anything but exactly one statement, bound to this one,
    stops the run (refused). SessionExpired and OtpRequired propagate.
    `own_files` are this statement's own copies saved before, which a
    Download again may meet with the same bytes (bind)."""
    entries = list(entries) if entries else [entry]
    top = newest(entries)
    by_address = top is not None and top.document_id == entry.document_id
    if by_address:
        if not open_by_address(page, entry, entries, trace):
            return False

        def on_page(url):
            return is_detail_url(url, entry.statement_id)
    else:
        if not choose_in_page(page, entry, entries, dl_dir, trace):
            return False

        def on_page(url):
            return lands_on(url, entry)

    def wrong(why: str) -> bool:
        _note(trace, note=why)
        if by_address:
            return False
        raise chose_wrong(entry, why)
    try:
        button = page.get_by_role("button", name=PRINTABLE_RE)
        count = button.count()
    except Exception:
        count = -1
    if count != 1:
        return wrong("not one printable statement button")
    el = button.first
    try:
        label = el.inner_text(timeout=2000) or ""
        enabled = el.is_enabled()
    except Exception:
        return wrong("the button could not be read")
    if not is_safe_control(label):
        return wrong("the guard refused the button")
    if not enabled:
        _note(trace, note="the button is turned off")
        return False
    return _press_for_statement(page, el, entry, entries, out_path, dl_dir, trace, on_page,
                                own_files=own_files)


def _unlisten(page, pairs) -> None:
    for event, handler in pairs:
        try:
            page.remove_listener(event, handler)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Binding the bytes to the statement
# ---------------------------------------------------------------------------
# sha256 of each statement this process kept, with its document id. Bytes
# one statement already gave are never kept for another.
_KEPT: dict = {}


def pdf_text(data: bytes, pages: int = 5) -> str:
    """The text of the first pages of a PDF held in memory, or "". Never
    logged, never written."""
    try:
        return whole_characters("\n".join(pdf_reader.page_texts(data, max(1, pages))))
    except Exception:
        return ""


def rivals_of(entry: Entry, entries: List[Entry]) -> list:
    """The statements this one could be mistaken for, as Identity: the
    current account's newest (the copy the page printed in its place on
    2026-10-12) and the statements beside it in the list."""
    out: List[Entry] = []
    top = newest(entries)
    if top is not None:
        out.append(top)
    ids = [e.document_id for e in entries]
    if entry.document_id in ids:
        i = ids.index(entry.document_id)
        out += entries[max(0, i - 1):i] + entries[i + 1:i + 2]
    seen, rivals = set(), []
    for e in out:
        if e.document_id != entry.document_id and e.document_id not in seen:
            seen.add(e.document_id)
            rivals.append(Identity(date=e.date))
    return rivals


def _same_file_in(folder: Path, data: bytes, skip) -> Optional[bool]:
    """Whether a PDF already in `folder`, other than those in `skip`, holds
    exactly these bytes, None when the folder cannot be read. A folder not
    made yet holds none."""
    if not folder.exists():
        return False
    try:
        skipped = {Path(x).resolve() for x in skip if x}
        for p in folder.iterdir():
            if p.resolve() in skipped or p.suffix.lower() != ".pdf" or not p.is_file():
                continue
            if p.stat().st_size == len(data) and p.read_bytes() == data:
                return True
    except OSError:
        return None
    return False


def bind(data: bytes, entry: Entry, entries: List[Entry], out_path: Path,
         trace: Optional[list] = None, own_files=()) -> str:
    """An empty string when the bytes the press brought are this statement's, beyond
    the page's own request having named it. The PDF's text prints the
    statement's date, it does not print more of a rival statement's own
    facts than of this one's, and it is not the same file as a statement
    kept earlier in this process or a PDF already in the folder it is saved
    to (where earlier runs kept the newest), this statement's own copies
    from before (`own_files`, for a Download again) apart. Otherwise our
    own words for what was wrong. Only names and yes or no go into the
    trace."""
    text = pdf_text(data)
    own = Identity(date=entry.date)
    verdict = verify(None, own, text=text)
    _note(trace, note="date check", verdict=verdict.report())
    if verdict.outcome == UNREADABLE:
        return "the PDF holds no text to check its date against"
    if verdict.outcome != VERIFIED:
        return "the PDF does not print the statement's date"
    told = distinguish(None, own, rivals_of(entry, entries), text=text)
    _note(trace, note="rival check", verdict=told.report())
    if told.outcome == REFUSED:
        return "the PDF prints another statement's date more than this one's"
    digest = hashlib.sha256(data).hexdigest()
    other = _KEPT.get(digest)
    if other is not None and other != entry.document_id:
        return "the PDF is the same file as another statement kept in this run"
    same = _same_file_in(out_path.parent, data, [out_path, *own_files])
    if same is None:
        return "the folder could not be read to compare the PDF with those saved"
    if same:
        return "the PDF is the same file as one already saved"
    return ""


def _press_for_statement(page, el, entry: Entry, entries: List[Entry], out_path: Path, dl_dir,
                         trace, on_page, own_files=()) -> bool:
    if not dl_dir:
        raise no_folder()
    pdf = Watch(page, PDF_OPERATION, entry.statement_id)
    popups: list = []
    downloads: list = []

    def on_popup(popup):
        popups.append(1)

    # Observation only: a download the press began is counted and
    # canceled, and its file, if the browser had already written one,
    # deleted. Nothing of it is read or saved.
    def on_download(download):
        downloads.append(1)
        intake.discard(download)
    result: dict = {}
    pressed = False
    try:
        pdf.start()
        page.on("popup", on_popup)
        page.on("download", on_download)
        page.evaluate(_ARM_JS)
        pages_before = tabs_now(page)
        folder_before = _entries(dl_dir)
        try:
            pressing.click(page, el, css=pressing.BUTTONS, what="the View Printable Statement button",
                           words=_words(), step="take a statement")
        except pressing.TurnedOff:
            # Spectrum kept the button turned off the whole time Playwright
            # waited, with nothing over it, so nothing was pressed. The
            # statement is left for the next run, as the core leaves any
            # document whose own control is turned off. The hook comes off
            # in finally.
            log.info("View Printable Statement stayed turned off, so nothing was pressed")
            _note(trace, note="the button is turned off")
            return False
        pressed = True

        def blobs() -> int:
            try:
                return int(page.evaluate(_COUNT_JS) or 0)
            except Exception:
                return 0
        pdf.wait(polls=60, also=blobs)
        new_pages = len(_opened_since(page, pages_before))
        pdf.check_session()
        check_page(page)
        on_route = on_page(page.url or "")
        decoded = []
        for response, matches, _ in pdf.hits:
            try:
                decoded.append((matches, pdf_of(answer_of(response))))
            except ListStopped:
                decoded.append((matches, b""))
        try:
            result = intake.evaluate(page, _RESULT_JS) or {}
        except Exception:
            result = {}
    except (SessionExpired, OtpRequired):
        raise
    except Exception as e:
        if not pressed:
            raise
        raise refused("the page could not be read after the press, %s" % type(e).__name__) from None
    finally:
        pdf.stop()
        _unlisten(page, (("popup", on_popup), ("download", on_download)))
        try:
            page.evaluate(_RESTORE_JS)
        except Exception:
            pass
    try:
        stray = len(downloads) + _changed_entries(dl_dir, folder_before)
        data, why = accept(decoded, result, new_pages=new_pages, popups=len(popups),
                           downloads=stray, on_route=on_route)
        made = list(result.get("blobs") or [])
        _note(trace, note="statement accepted" if data else "statement refused", why=why,
              answers=len(decoded), blobs=len(made), tabs=new_pages, downloads=stray)
        if data:
            why = bind(data, entry, entries, out_path, trace, own_files)
            if why:
                log.info("the PDF the press brought is not bound to the statement dated %s: %s", entry.date, why)
        else:
            log.info("the press did not bring exactly one statement: %s", why)
        if not why:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(data)
            _KEPT[hashlib.sha256(data).hexdigest()] = entry.document_id
    except Exception as e:
        raise refused("what it brought could not be checked or kept, %s" % type(e).__name__) from None
    if why:
        raise refused(why)
    return True


def download_bill(page, dl_dir, iso_date: str, out_path, title: str = "",
                  trace: Optional[list] = None, href: str = "",
                  document_id: str = "", own_files=()) -> bool:
    """Save the statement discovery recorded as `document_id`
    ("current:YYYY-MM-DD", "prior:YYYY-MM-DD" or "mobile:YYYY-MM-DD"), dated
    `iso_date`. A Mobile statement is taken by take_mobile. For an Internet
    one Statements is read again and exactly one entry there must carry that
    family and date. The newest statement's page is then opened by its
    address, any other statement is chosen by pressing its row there.
    False, nothing pressed, when it is not found. SessionExpired and
    OtpRequired propagate to the run, and a press that brought anything but
    the statement stops it. So does ListStopped when Statements cannot be
    read again, since every statement after this one reads the same list.
    `own_files` are the statement's own copies saved before, as
    take_statement says."""
    out_path = Path(out_path)
    m = DOCUMENT_ID_RE.fullmatch((document_id or "").strip())
    if not m or m.group(2) != (iso_date or "") or not valid_iso(iso_date):
        log.info("no statement was recorded for this document")
        _note(trace, note="no recorded statement")
        return False
    if m.group(1) == MOBILE:
        return take_mobile(page, iso_date, out_path, dl_dir, trace, own_files=own_files)
    try:
        entries = read_statement_list(page)
    except ListStopped as stop:
        log.info("the statement list stopped while looking for the statement dated %s: %s", iso_date, stop)
        raise
    found = [e for e in entries if e.family == m.group(1) and e.date == iso_date]
    if len(found) != 1:
        log.info("%d entries match the recorded statement dated %s, none taken", len(found), iso_date)
        _note(trace, note="no single entry matches the record", matches=len(found))
        return False
    return take_statement(page, found[0], out_path, dl_dir, trace, entries, own_files=own_files)


# ---------------------------------------------------------------------------
# Mobile statements, a second family. See MOBILE in the module docstring.
# ---------------------------------------------------------------------------
BILLING_HOME_PATH = "/billing"
BILLING_HOME_URL = BASE + BILLING_HOME_PATH
MOBILE_LIST_PATH = "/billing/mobile-statements"
MOBILE_DETAIL_PATH = "/mobile-billing/statement-history"
# The Billing page's "Mobile Account Number" link and the Mobile list's rows
# are anchors with role=link and href "javascript:void(0)" (survey of
# 2026-10-13). The rows' class was not seen, so they are found by role and
# told apart by their words.
MOBILE_LINK = "a[role=link]"
MOBILE_ROW = "a[role=link]"
OPEN_MOBILE_STEP = "open the Mobile statements"
CHOOSE_MOBILE_STEP = "choose a Mobile statement"
EXPAND_STEP = "expand the Mobile statement"
_MONTH_WORDS = ("January|February|March|April|May|June|July|August|September|October|"
                "November|December")
# "Mobile Account Number: <n>" with non-breaking spaces between the
# words, read after normalized(), so any run of white space is one space.
# The number may be shown whole or masked.
_MOBILE_LINK_RE = re.compile(r"mobile account number ?:? ?([0-9*#\u2022xX. -]{0,40})")
# The number part must hold at least one digit or masking character.
_ACCOUNT_TOKEN_RE = re.compile(r"[0-9*#\u2022xX]")
_INTERNET_LINK_RE = re.compile(r"^internet account number\b")
# A finished statement's row, "Statement August 13, 2026", whole, with at most
# one amount after it (an amount is private and never kept).
_MOBILE_ROW_RE = re.compile(r"Statement (%s) (\d{1,2}), (\d{4})(?: -?\$[0-9,]+\.\d{2})?" % _MONTH_WORDS)
# The statement under way, "Statement October 13 Auto Pay: Oct 30 $...", has
# no year after its day.
_UNFINISHED_ROW_RE = re.compile(r"^Statement (%s) \d{1,2}(?!\d|, \d{4})" % _MONTH_WORDS)
_FULL_DATE_RE = re.compile(r"(%s) (\d{1,2}), (\d{4})" % _MONTH_WORDS, re.I)
EXPAND_ALL_RE = re.compile(r"^\s*expand\s+all\s*$", re.I)

_LINKS_JS = r"""(sel) => Array.from(document.querySelectorAll(sel))
  .map(a => (a.innerText || '').replace(/\s+/g, ' ').trim())"""

# Read only. The distinct texts of drawn elements whose whole text is a full
# date ("AUGUST 13, 2026"), whether an element reads exactly "Statement
# Details", and whether a line reading exactly "Mobile" sits within four
# ancestors of such a date. An element that is not drawn (no box, or hidden)
# is skipped, since innerText gives a hidden element's whole text.
_DETAIL_JS = r"""() => {
  const full = /^(january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2},\s+\d{4}$/i;
  const flat = s => (s || '').replace(/\s+/g, ' ').trim();
  const drawn = el => el.getClientRects().length > 0 && getComputedStyle(el).visibility !== 'hidden';
  const out = {dates: [], details: false, mobile: false};
  for (const el of document.querySelectorAll('body *')) {
    const raw = el.textContent || '';
    if (!raw.trim() || raw.length > 120 || !drawn(el)) continue;
    const t = flat(el.innerText);
    if (t === 'Statement Details') out.details = true;
    if (!full.test(t)) continue;
    if (!out.dates.includes(t)) out.dates.push(t);
    let a = el;
    for (let i = 0; i < 5 && a; i++, a = a.parentElement) {
      if ((a.innerText || '').split('\n').some(line => flat(line) === 'Mobile')) { out.mobile = true; break; }
    }
  }
  return out;
}"""

# The statementId each Mobile statement's page carried in this process, so
# two dates never share one page. In memory only, never written or logged.
_MOBILE_IDS: dict = {}


def full_date(text) -> Optional[str]:
    """A whole "Month D, YYYY" date, in any case, as YYYY-MM-DD, or None."""
    m = _FULL_DATE_RE.fullmatch(_flat(text))
    if not m:
        return None
    try:
        return _date(int(m.group(3)), _MONTHS[m.group(1)[:3].lower()], int(m.group(2))).isoformat()
    except ValueError:
        return None


def mobile_row_day(text) -> Optional[str]:
    """The date of a finished Mobile statement's row, "Statement August 13,
    2026" whole (an amount after it allowed), as YYYY-MM-DD, or None."""
    m = _MOBILE_ROW_RE.fullmatch(_flat(text))
    if not m:
        return None
    try:
        return _date(int(m.group(3)), _MONTHS[m.group(1)[:3].lower()], int(m.group(2))).isoformat()
    except ValueError:
        return None


def mobile_account_number(label) -> Optional[str]:
    """The number part of a "Mobile Account Number: <n>" link label, or None
    when the label is not that link's, a number or its mask included."""
    m = _MOBILE_LINK_RE.fullmatch(normalized(label))
    if not m or not _ACCOUNT_TOKEN_RE.search(m.group(1)):
        return None
    return m.group(1).strip()


def is_mobile_account_link(label) -> bool:
    """The guard for the Billing page's "Mobile Account Number" link. Deny by
    default. The label must be exactly that, with only an account number
    after it, and pass the shared core guards. The app's blocklist refuses
    "mobile", so this exact shape takes its place for this one label."""
    if mobile_account_number(label) is None:
        return False
    text = normalized(label)
    return not (SETTINGS_CONTROL_RE.search(text) or AUTH_CONTROL_RE.search(text))


def is_safe_mobile_row(text, day: str) -> bool:
    """Whether a Mobile list row may be pressed to choose the statement dated
    `day`. Deny by default. Unreadable words are refused, then this app's
    blocklist (pay, Auto Pay, order, settings and the rest), then the shared
    core guards, and only then a row that is exactly "Statement Month D,
    YYYY" of that date. The statement under way (Auto Pay, no year), "Your
    Total So Far" and an "Order" row never pass."""
    label = normalized(text)
    if not label or not valid_iso(day):
        return False
    if FORBIDDEN_CONTROL_RE.search(label):
        return False
    if SETTINGS_CONTROL_RE.search(label) or AUTH_CONTROL_RE.search(label):
        return False
    return mobile_row_day(text) == day


def is_expand_all(label) -> bool:
    """The guard for the Mobile statement's "Expand All". Deny by default,
    exactly that label, and nothing the blocklist or the core guards
    refuse."""
    text = normalized(label)
    if not EXPAND_ALL_RE.fullmatch(text):
        return False
    return not (FORBIDDEN_CONTROL_RE.search(text) or SETTINGS_CONTROL_RE.search(text)
                or AUTH_CONTROL_RE.search(text))


def mobile_days(texts) -> List[str]:
    """The dates of the finished statements a Mobile list shows, in its
    order. The statement under way (no year after its day) is skipped, and
    so is every row that does not start "Statement" ("Your Total So Far",
    "Order ..."). Any other row starting "Statement" is a shape not seen, and
    two rows of one date leave nothing to tell them apart: both stop the
    list. Row words are never kept or logged."""
    days: List[str] = []
    for t in texts or []:
        flat = _flat(t)
        if not flat.startswith("Statement"):
            continue
        day = mobile_row_day(flat)
        if day:
            if day in days:
                raise ListStopped("two Mobile statements carry one date")
            days.append(day)
        elif not _UNFINISHED_ROW_RE.match(flat):
            raise ListStopped("a Mobile statement row has a shape this app does not know")
    return days


def _link_texts(page, sel: str) -> Optional[list]:
    try:
        return [str(t or "") for t in (page.evaluate(_LINKS_JS, sel) or [])]
    except Exception:
        return None


def _mobile_detail_query(url: str) -> Optional[dict]:
    """The query of a Mobile statement's own page, or None for any other
    address: https, exactly www.spectrum.net, no port, credentials or
    fragment, exactly the path /mobile-billing/statement-history, and a
    query of a non-empty statementId with at most newStatementVersion
    beside it, each once."""
    if not is_safe_url(url):
        return None
    try:
        parts = urlsplit(url)
        if parts.port is not None or parts.fragment or parts.path != MOBILE_DETAIL_PATH:
            return None
        pairs = _query_pairs(parts.query)
    except ValueError:
        return None
    keys = [k for k, _ in pairs]
    if len(set(keys)) != len(keys) or "statementId" not in keys \
            or not set(keys) <= {"statementId", "newStatementVersion"}:
        return None
    q = dict(pairs)
    return q if q["statementId"] else None


def detail_state(page) -> dict:
    """What the Mobile statement page draws (_DETAIL_JS), {} when it cannot
    be read. Never logged."""
    try:
        got = page.evaluate(_DETAIL_JS) or {}
    except Exception:
        return {}
    return got if isinstance(got, dict) else {}


def heading_says(state: dict, day: str, only: bool) -> str:
    """"" when the page's state shows the Mobile statement dated `day`: an
    element reading "Statement Details", a date element reading `day`
    ("AUGUST 13, 2026"), with "Mobile" beside it. With `only`, as the page
    first draws, no other date may be drawn on its own, since the expanded
    sections, which may hold other dates, are closed then. Otherwise our own
    words for what is wrong."""
    days = [full_date(t) for t in state.get("dates") or []]
    if not state.get("details"):
        return "the page does not read Statement Details"
    if day not in days:
        return "the page does not show the statement's date"
    if only and set(days) != {day}:
        return "the page shows another date beside the statement's"
    if not state.get("mobile"):
        return "the page does not say Mobile beside its date"
    return ""


# The page's own GraphQL operations a Mobile statement depends on: the
# Mobile list's statements and the statement's own data (heard live
# 2026-10-13). A failed answer to one of these fails the press or the print.
# Any other operation's failed answer (the next-bill estimate, alerts,
# insurance) is only logged by name and counted, since the live list page
# draws a "not available" tile when the estimate fails, and the statement
# does not come from it. A 401 from any graph answer is a signed-out
# session, as for every Watch.
MOBILE_STATEMENT_OPERATIONS = {"fetchMobileDigitalStatementsForBillPresentment",
                               "fetchMobileHistoricalStatement"}


class MobileWatch(Watch):
    """The page's own GraphQL answers while a Mobile press or the print is
    under way. Kept, as Watch keeps them: every graph answer's status and
    the session check, and every graph answer with its operationName, of
    which only the status and whether the JSON has an "errors" member are
    read, after the wait. Nothing else of a request or response is looked
    at."""

    def __init__(self, page):
        super().__init__(page, "")
        self.mine: list = []
        self.others_failed: list = []

    def heard(self, response) -> None:
        super().heard(response)
        try:
            request = response.request
            if request.url != GRAPH_URL or request.method != "POST":
                return
            body = whole_json(json.loads(request.post_data or ""))
        except Exception:
            body = None
        op = body.get("operationName") if isinstance(body, dict) else None
        self.mine.append((op if isinstance(op, str) else "", response))

    @staticmethod
    def _fault(response) -> str:
        try:
            status = int(response.status)
        except Exception:
            status = 0
        if status != 200:
            return "came back %d" % status
        try:
            answer = whole_json(response.json())
        except Exception:
            return "is not JSON"
        if not isinstance(answer, dict) or answer.get("errors"):
            return "carries errors"
        return ""

    def failed(self) -> str:
        """SessionExpired for a 401 or a session check that says the session
        is not valid. "" when every answer to a MOBILE_STATEMENT_OPERATIONS
        operation was a 200 JSON object without errors, else our own words.
        Other operations' failed answers are logged by name only."""
        self.check_session()
        why = ""
        for op, response in list(self.mine):
            fault = self._fault(response)
            if not fault:
                continue
            if op in MOBILE_STATEMENT_OPERATIONS:
                why = why or "the statement's own answer %s" % fault
            else:
                # An operation's name is the page's own code word, never
                # the account's. Anything else is not repeated.
                name = redact(op) if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,79}", op or "") else "unnamed"
                self.others_failed.append(name)
                log.info("another graph answer %s (%s), not one the statement depends on", fault, name)
        return why


class _Strays:
    """Tabs, popups and downloads a press brings. A download is only counted,
    canceled and deleted, and a file it left in the run's folder removed.
    Nothing of either is read or kept."""

    def __init__(self, page, dl_dir):
        self.page, self.dl_dir = page, dl_dir
        self.popups: list = []
        self.downloads: list = []
        self._pairs: tuple = ()
        self.before: list = []
        self.folder_before: Optional[dict] = {}

    def start(self) -> "_Strays":
        popups, downloads = self.popups, self.downloads

        def on_popup(popup):
            popups.append(1)

        def on_download(download):
            downloads.append(1)
            intake.discard(download)
        self._pairs = (("popup", on_popup), ("download", on_download))
        self.before = tabs_now(self.page)
        self.folder_before = _entries(self.dl_dir)
        self.page.on("popup", on_popup)
        self.page.on("download", on_download)
        return self

    def stop(self) -> None:
        _unlisten(self.page, self._pairs)

    def found(self) -> str:
        """"" when the press brought no tab, popup or download, else which."""
        if _opened_since(self.page, self.before) or self.popups:
            return "a tab opened"
        if len(self.downloads) + _changed_entries(self.dl_dir, self.folder_before):
            return "a download began"
        return ""


def mobile_stopped(step: str, why: str):
    """A Mobile press was made and the page did not do what it does. The run
    stops, since the next press could do the same."""
    return pressing.no_answer(
        step, "the press opened something other than what it opens",
        "A press to %s did not bring what it brings (%s), so the run stops." % (step, why))


def _wait_for(page, ready, polls: int = 40) -> bool:
    for _ in range(polls):
        if ready():
            return True
        page.wait_for_timeout(500)
    return ready()


def open_mobile_list(page, dl_dir, trace=None) -> Optional[List[str]]:
    """Open Billing by its address and press its "Mobile Account Number"
    link once, under is_mobile_account_link, to reach the Mobile statement
    list, and return the dates of its finished statements (mobile_days).
    None, nothing pressed, when Billing draws no such link, as for an
    Internet-only customer. ListStopped, nothing pressed, for a Billing page
    whose account links did not settle, that did not draw its statements or
    draws two Mobile links, for a link whose href leads anywhere
    (is_void_href), and after the press for a list whose statement rows did
    not draw and hold still, since what it shows then is not all of it. A
    tab, popup or download the press brought stops the run. SessionExpired
    and OtpRequired propagate."""
    if not dl_dir:
        raise no_folder()
    before = tabs_now(page)
    try:
        page.goto(BILLING_HOME_URL, wait_until="domcontentloaded", timeout=60000)
    except Exception as e:
        log.info("opening Billing failed (%s)", type(e).__name__)
        check_page(page)
        raise ListStopped("Billing did not open")
    if _opened_since(page, before):
        raise ListStopped("opening Billing opened another tab, which was closed")
    check_page(page)
    if not _on_path(page, BILLING_HOME_PATH):
        raise ListStopped("Billing settled off its own address")
    seen: dict = {"links": None, "still": 0}

    def drawn() -> bool:
        texts = _link_texts(page, MOBILE_LINK) or []
        mobile = [i for i, t in enumerate(texts) if mobile_account_number(t) is not None]
        internet = any(_INTERNET_LINK_RE.match(normalized(t)) for t in texts)
        now = (tuple(mobile), internet)
        seen["still"] = seen["still"] + 1 if now == seen["links"] else 0
        seen["links"] = now
        return (bool(mobile) or internet) and seen["still"] >= 3
    settled = _wait_for(page, drawn)
    check_page(page)
    if not settled:
        raise ListStopped("Billing's account links did not settle")
    texts = _link_texts(page, MOBILE_LINK) or []
    mobile = [i for i, t in enumerate(texts) if mobile_account_number(t) is not None]
    for i in mobile:
        register_private(_parts(mobile_account_number(texts[i])))
    if any(normalized(t).startswith("mobile account number") and mobile_account_number(t) is None
           for t in texts):
        raise ListStopped("Billing draws a Mobile account link this app does not know")
    if not mobile:
        if not any(_INTERNET_LINK_RE.match(normalized(t)) for t in texts):
            raise ListStopped("Billing did not draw its statement links")
        log.info("Billing lists no Mobile account")
        _note(trace, note="no Mobile account")
        return None
    if len(mobile) != 1:
        raise ListStopped("Billing draws %d Mobile account links, not one" % len(mobile))
    link = page.locator(MOBILE_LINK).nth(mobile[0])
    try:
        label = link.inner_text(timeout=2000)
        href = link.get_attribute("href", timeout=2000)
    except Exception as e:
        raise ListStopped("the Mobile link could not be read, %s" % type(e).__name__)
    if _flat(label) != _flat(texts[mobile[0]]) or not is_mobile_account_link(label):
        raise ListStopped("the guard refused the Mobile link")
    if not is_void_href(href):
        raise ListStopped("the Mobile link leads somewhere of its own, which the survey never saw")
    session = MobileWatch(page)
    strays = _Strays(page, dl_dir)
    pressed = False
    settled = False
    try:
        session.start()
        strays.start()
        pressing.click(page, link, css=pressing.LINKS, what="the Mobile Account Number link",
                       words=_words(), step="open the Mobile statements")
        pressed = True
        rows: dict = {"days": None, "n": -1, "still": 0}

        def listed() -> bool:
            if not _on_path(page, MOBILE_LIST_PATH):
                return False
            texts = _link_texts(page, MOBILE_ROW) or []
            n = sum(1 for t in texts if _flat(t).startswith("Statement"))
            rows["still"] = rows["still"] + 1 if n == rows["n"] else 0
            rows["n"] = n
            return n > 0 and rows["still"] >= 3
        settled = _wait_for(page, listed)
        why = strays.found()
    except (SessionExpired, OtpRequired, pressing.Stop):
        raise
    except Exception as e:
        if not pressed:
            raise
        raise mobile_stopped(OPEN_MOBILE_STEP, "the page could not be read after the press, %s"
                             % type(e).__name__) from None
    finally:
        session.stop()
        strays.stop()
    _note(trace, note="Mobile link pressed", strays=bool(why))
    if why:
        raise mobile_stopped(OPEN_MOBILE_STEP, why)
    why = session.failed()
    check_page(page)
    if why:
        raise ListStopped(why)
    if not _on_path(page, MOBILE_LIST_PATH):
        raise ListStopped("the Mobile link did not open the Mobile statements")
    if not settled:
        raise ListStopped("the Mobile statement rows did not draw and hold still")
    texts = _link_texts(page, MOBILE_ROW)
    if texts is None:
        raise ListStopped("the Mobile statement rows could not be read")
    if sum(1 for t in texts if _flat(t).startswith("Statement")) != rows["n"]:
        raise ListStopped("the Mobile statement rows changed as they were read")
    return mobile_days(texts)


def mobile_entries(page, dl_dir, trace=None) -> List[Entry]:
    """Every finished Mobile statement the Mobile list shows, as Entries of
    the mobile family, [] when Billing has no Mobile account."""
    days = open_mobile_list(page, dl_dir, trace)
    return [Entry(MOBILE, d) for d in days or []]


def choose_mobile(page, index: int, text: str, day: str, dl_dir, trace=None) -> bool:
    """Press the Mobile list row `index`, read as `text`, to open the
    statement dated `day`. False, nothing pressed, when the row's words
    changed or the guard refuses them, its href leads anywhere
    (is_void_href), or Spectrum kept it turned off.
    After the press, a tab, popup or download, a page that is not exactly a
    Mobile statement's own address, a statementId another date's page
    already carried, or a page that does not read this statement's date and
    Mobile on its own stops the run. SessionExpired and OtpRequired
    propagate."""
    if not dl_dir:
        raise no_folder()
    row = page.locator(MOBILE_ROW).nth(index)
    try:
        now = _flat(row.inner_text(timeout=2000))
        href = row.get_attribute("href", timeout=2000)
    except Exception as e:
        _note(trace, note="the Mobile row could not be read", error=type(e).__name__)
        return False
    if now != _flat(text) or not is_safe_mobile_row(now, day):
        _note(trace, note="the Mobile row changed or was refused before the press")
        return False
    if not is_void_href(href):
        _note(trace, note="the Mobile row leads somewhere of its own, which the survey never saw")
        return False
    session = MobileWatch(page)
    strays = _Strays(page, dl_dir)
    pressed = False
    state: dict = {}
    try:
        session.start()
        strays.start()
        try:
            pressing.click(page, row, css=pressing.LINKS, what="the Mobile statement row dated %s" % day,
                           words=_words(), step="choose a Mobile statement")
        except pressing.TurnedOff:
            log.info("the Mobile statement row stayed turned off, so nothing was pressed")
            _note(trace, note="the Mobile row is turned off")
            return False
        pressed = True

        def landed() -> bool:
            if _mobile_detail_query(page.url or "") is None:
                return False
            state.clear()
            state.update(detail_state(page))
            return bool(state.get("dates")) and bool(state.get("details"))
        _wait_for(page, landed)
        why = strays.found()
    except (SessionExpired, OtpRequired, pressing.Stop):
        raise
    except Exception as e:
        if not pressed:
            raise
        raise mobile_stopped(CHOOSE_MOBILE_STEP, "the page could not be read after the press, %s"
                             % type(e).__name__) from None
    finally:
        session.stop()
        strays.stop()
    _note(trace, note="Mobile row pressed", strays=bool(why))
    if why:
        raise mobile_stopped(CHOOSE_MOBILE_STEP, why)
    why = session.failed()
    check_page(page)
    if why:
        raise mobile_stopped(CHOOSE_MOBILE_STEP, why)
    q = _mobile_detail_query(page.url or "")
    if q is None:
        raise mobile_stopped(CHOOSE_MOBILE_STEP, "the page it opened is not a Mobile statement's own")
    register_private([v for v in q.values() if v])
    other = _MOBILE_IDS.get(q["statementId"])
    if other is not None and other != day:
        raise mobile_stopped(CHOOSE_MOBILE_STEP, "the page is the one another date's row opened")
    why = heading_says(state, day, only=True)
    if why:
        raise mobile_stopped(CHOOSE_MOBILE_STEP, why)
    _MOBILE_IDS[q["statementId"]] = day
    return True


# Read only. The statement's sections and its one Expand All / Collapse All
# toggle, as seen live on 2026-10-13: each section is a
# <button id="accord-N-button-0" class="kite-accordion-row__button"
# aria-expanded="..."> (six of them, Account Holder Information first, none
# with aria-controls), and the toggle is a kite-button reading "Expand All"
# that reads "Collapse All" once every section is open. Other buttons on the
# page carry aria-expanded too (the navigation's), so only the sections'
# own buttons are counted. Counts and the toggle's word only.
_SECTIONS_JS = r"""() => {
  const flat = s => (s || '').replace(/\s+/g, ' ').trim();
  const toggles = Array.from(document.querySelectorAll('button'))
    .map(b => flat(b.innerText)).filter(t => /^(expand|collapse) all$/i.test(t));
  const rows = Array.from(document.querySelectorAll('button')).filter(b =>
    /^accord-\d+-button-0$/.test(b.id || '') && b.classList.contains('kite-accordion-row__button'));
  return {toggles: toggles.length,
          toggle: toggles.length === 1 ? toggles[0].split(' ')[0].toLowerCase() : '',
          sections: rows.length,
          open: rows.filter(b => b.getAttribute('aria-expanded') === 'true').length};
}"""


def sections(page) -> dict:
    """What _SECTIONS_JS reads, {} when it cannot be read. Counts only."""
    try:
        got = page.evaluate(_SECTIONS_JS) or {}
    except Exception:
        return {}
    return got if isinstance(got, dict) else {}


# The sections every Mobile statement seen live had: Account Holder
# Information, Previous Balance, Payments and Credits, Remaining Balance,
# the plan's lines, and Included Taxes, Fees & Charges. Fewer is a page
# still drawing, never a whole statement. A month may have more.
MIN_SECTIONS = 6


def all_open(seen: dict, sections_before: int = 0) -> bool:
    """Whether the statement shows every section: one toggle, reading
    Collapse All, at least MIN_SECTIONS section buttons, as many as before
    the press when that is given, and every one reading expanded."""
    count = int(seen.get("sections") or 0)
    return (seen.get("toggles") == 1 and seen.get("toggle") == "collapse"
            and count >= MIN_SECTIONS and (not sections_before or count == sections_before)
            and seen.get("open") == count)


# How many reads in a row, half a second apart, must show every section
# open, the same each time, before the statement counts as whole. The page
# gives no signal that it has finished drawing, so a section added late is
# caught by this, and by the same read just before and just after the print.
STEADY_READS = 3


def steady_open(page, sections_before: int = 0, polls: int = 10) -> dict:
    """The section counts once STEADY_READS reads in a row show every
    section open (all_open) and the same, else {} after `polls` reads."""
    last, run = None, 0
    for i in range(polls):
        if i:
            page.wait_for_timeout(500)
        seen = sections(page)
        now = _counts(seen)
        if all_open(seen, sections_before):
            run = run + 1 if now == last else 1
            if run >= STEADY_READS:
                return seen
        else:
            run = 0
        last = now
    return {}


def _counts(seen: dict) -> dict:
    return {"toggles": int(seen.get("toggles") or 0), "toggle": str(seen.get("toggle") or "")[:8],
            "sections": int(seen.get("sections") or 0), "open": int(seen.get("open") or 0)}


def expand_statement(page, day: str, dl_dir, trace=None) -> bool:
    """Open every section of the Mobile statement, so all of it shows in the
    print. A statement already showing every section (all_open) is left as
    it is, with nothing pressed. Otherwise its one "Expand All" is pressed
    once, under is_expand_all, and the page is given about five seconds to
    read Collapse All with every section expanded. False, nothing pressed,
    when there is not exactly one Expand All, it is refused or turned off,
    or fewer than MIN_SECTIONS sections can be read. False, nothing
    printed, when the sections, as many as before the press, do not all
    open and hold still after the press. After the press, a tab, popup or download,
    an address that changed, a graph answer that is not an answer, or a
    page that no longer reads this statement's date and Mobile stops the
    run. The trace keeps the counts seen. SessionExpired and OtpRequired
    propagate."""
    if not dl_dir:
        raise no_folder()
    where = page.url or ""
    before = sections(page)
    _note(trace, note="sections before Expand All", **_counts(before))
    if before.get("toggle") == "collapse":
        # Already open: nothing is pressed, and it must hold still as a
        # pressed one must.
        held = steady_open(page)
        _note(trace, note="sections already open", **_counts(held))
        if not held:
            _note(trace, note="not every section expanded")
            return False
        return True
    if before.get("toggles") != 1 or before.get("toggle") != "expand" \
            or int(before.get("sections") or 0) < MIN_SECTIONS:
        _note(trace, note="no section to expand was read")
        return False
    try:
        button = page.get_by_role("button", name=EXPAND_ALL_RE)
        count = button.count()
    except Exception:
        count = -1
    if count != 1:
        _note(trace, note="not one Expand All button")
        return False
    el = button.first
    try:
        label = el.inner_text(timeout=2000) or ""
        enabled = el.is_enabled()
    except Exception:
        _note(trace, note="Expand All could not be read")
        return False
    if not is_expand_all(label) or not enabled:
        _note(trace, note="Expand All refused or turned off")
        return False
    session = MobileWatch(page)
    strays = _Strays(page, dl_dir)
    pressed = False
    after: dict = {}
    try:
        session.start()
        strays.start()
        pressing.click(page, el, css=pressing.BUTTONS, what="the Expand All button",
                       words=_words(), step="expand the Mobile statement")
        pressed = True

        after.update(steady_open(page, int(before.get("sections") or 0), polls=14))
        why = strays.found()
        state = detail_state(page)
    except (SessionExpired, OtpRequired, pressing.Stop):
        raise
    except Exception as e:
        if not pressed:
            raise
        raise mobile_stopped(EXPAND_STEP, "the page could not be read after the press, %s"
                             % type(e).__name__) from None
    finally:
        session.stop()
        strays.stop()
    _note(trace, note="Expand All pressed", strays=bool(why), **_counts(after))
    if why:
        raise mobile_stopped(EXPAND_STEP, why)
    why = session.failed()
    check_page(page)
    if why:
        raise mobile_stopped(EXPAND_STEP, why)
    if (page.url or "") != where:
        raise mobile_stopped(EXPAND_STEP, "the address changed")
    why = heading_says(state, day, only=False)
    if why:
        raise mobile_stopped(EXPAND_STEP, why)
    if not all_open(after, int(before.get("sections") or 0)):
        log.info("the Mobile statement dated %s did not show every section, so it is not printed", day)
        _note(trace, note="not every section expanded")
        return False
    return True


# The printed page's header, as pypdf reads it (live print of 2026-10-13):
# the heading is letter-spaced in print, "S E P T E M B E R 1 3, 2 0 2 6",
# and comes first, followed by the word "Mobile". pypdf separates the
# letter-spaced words with two spaces ("S E P T E M B E R  1 3,  2 0 2 6")
# and puts "Mobile" on the next line. The screen's "Statement Details" bar
# is not printed. So white space is collapsed first, the date is matched
# with any white space between any two of its characters, and the very
# next word must be "Mobile" on its own (never inside a longer word such as
# "Automobile").
def _spaced(word: str) -> str:
    return r"\s*".join(re.escape(c) for c in word)


_PRINTED_DATE_RE = re.compile(
    r"(?<![a-z0-9])(%s)\s*(\d(?:\s*\d)?)\s*,\s*(\d\s*\d\s*\d\s*\d)(?!\s*[0-9])"
    % "|".join(_spaced(m.lower()) for m in _MONTH_WORDS.split("|")), re.I)
# "Mobile" prints as a plain word (live), so only that spelling is taken.
_PRINTED_MOBILE_RE = re.compile(r"\s+mobile(?!\w)", re.I)


def printed_header_day(text) -> Optional[str]:
    """The date the printed Mobile statement's header reads, as YYYY-MM-DD,
    or None: the first "<MONTH> <D>, <YYYY>" in the text, in any case and
    however letter-spaced, whose very next word is "Mobile"."""
    flat = re.sub(r"\s+", " ", str(text or ""))
    m = _PRINTED_DATE_RE.search(flat)
    if not m or not _PRINTED_MOBILE_RE.match(flat, m.end()):
        return None
    month, day, year = (re.sub(r"\s+", "", g).lower() for g in m.groups())
    try:
        return _date(int(year), _MONTHS[month[:3]], int(day)).isoformat()
    except (KeyError, ValueError):
        return None


def bind_mobile(data: bytes, day: str, out_path: Path, trace=None, own_files=()) -> str:
    """"" when a printed Mobile statement is this one's, beyond the page
    having read its date before and after the print: a PDF whose header
    reads this date first, with "Mobile" just after it (printed_header_day),
    whose text prints the date, and not the same file as a statement kept
    earlier in this process or a PDF already in the folder (this
    statement's own copies apart). Otherwise our own words."""
    if data[:5] != b"%PDF-":
        return "the print is not a PDF"
    text = pdf_text(data)
    header = printed_header_day(text)
    _note(trace, note="header check", reads_the_date=header == day)
    if header != day:
        return "the printed page's header does not read the statement's date"
    verdict = verify(None, Identity(date=day), text=text)
    _note(trace, note="date check", verdict=verdict.report())
    if verdict.outcome != VERIFIED:
        return "the printed page does not print the statement's date"
    other = _KEPT.get(hashlib.sha256(data).hexdigest())
    if other is not None and other != "%s:%s" % (MOBILE, day):
        return "the PDF is the same file as another statement kept in this run"
    same = _same_file_in(out_path.parent, data, [out_path, *own_files])
    if same is None:
        return "the folder could not be read to compare the PDF with those saved"
    if same:
        return "the PDF is the same file as one already saved"
    return ""


def _still_the_statement(page, where: str, day: str) -> str:
    """"" when the tab is still at exactly `where` and reads the statement
    dated `day` with Mobile, else our own words."""
    check_page(page)
    if (page.url or "") != where:
        return "the address changed"
    return heading_says(detail_state(page), day, only=False)


def take_mobile(page, day: str, out_path: Path, dl_dir, trace=None, own_files=()) -> bool:
    """Save the Mobile statement dated `day`. Billing's Mobile link opens
    the list afresh, the one finished row of that date is pressed, Expand
    All is pressed, and the page is printed to PDF with
    receipt_pdf.print_page_to_pdf (never the page's own Print). The tab
    must be at the same address and read the statement's date and Mobile
    just before and just after the print, and no Mobile answer heard while
    it printed may fail. False, nothing more pressed, when the row is not
    as expected before a press, Expand All is missing or did not expand
    every section, or the print fails. A Mobile list that cannot be read
    again raises ListStopped, since every Mobile statement after this one
    reads the same list, and a printed page not bound to the statement
    (bind_mobile) stops the run."""
    if not dl_dir:
        raise no_folder()
    try:
        days = open_mobile_list(page, dl_dir, trace)
    except ListStopped as stop:
        log.info("the Mobile list stopped while looking for the statement dated %s: %s", day, stop)
        raise
    if not days or days.count(day) != 1:
        _note(trace, note="no single Mobile row matches the record")
        return False
    texts = _link_texts(page, MOBILE_ROW) or []
    found = [i for i, t in enumerate(texts) if mobile_row_day(t) == day]
    if len(found) != 1:
        _note(trace, note="no single Mobile row matches the record")
        return False
    if not choose_mobile(page, found[0], texts[found[0]], day, dl_dir, trace):
        return False
    if not expand_statement(page, day, dl_dir, trace):
        return False
    where = page.url or ""
    why = _still_the_statement(page, where, day)
    shown = sections(page)
    if not why and not all_open(shown):
        why = "not every section is open just before the print"
    if why:
        raise mobile_stopped("print the Mobile statement", why)
    part = out_path.with_name(out_path.name + ".part")
    session = MobileWatch(page)
    try:
        session.start()
        try:
            receipt_pdf.print_page_to_pdf(page, part)
            data = part.read_bytes()
        except Exception as e:
            log.info("printing the Mobile statement failed (%s)", type(e).__name__)
            _note(trace, note="print to PDF failed", error=type(e).__name__)
            _drop(part)
            return False
        why = session.failed() or _still_the_statement(page, where, day)
        if not why and _counts(sections(page)) != _counts(shown):
            # A section drawn or closed while it printed: the print may
            # not hold the whole statement.
            why = "the sections changed while the page printed"
    finally:
        session.stop()
    try:
        why = why or bind_mobile(data, day, out_path, trace, own_files)
        if not why:
            part.replace(out_path)
            _KEPT[hashlib.sha256(data).hexdigest()] = "%s:%s" % (MOBILE, day)
    except Exception as e:
        why = "the print could not be checked or kept, %s" % type(e).__name__
    finally:
        _drop(part)
    _note(trace, note="Mobile statement kept" if not why else "Mobile statement refused", why=why)
    if why:
        log.info("the printed Mobile statement dated %s was refused: %s", day, why)
        raise mobile_stopped("print the Mobile statement", why)
    return True


def _drop(path: Path) -> None:
    try:
        if path.exists():
            path.unlink()
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Diagnose: a survey with the private words taken out, no screenshot.
# ---------------------------------------------------------------------------

def collect_documents(page) -> List[RawDoc]:
    """The drawn statement rows' dates only, for --diagnose."""
    out: List[RawDoc] = []
    for i, d in enumerate((_row_days(page) or [])[:40]):
        out.append(RawDoc(title="Statement", date_text=d, text="Statement", row_index=i))
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
                    controls.append({"role": role, "text": redact(text)[:50], "safe": is_safe_control(text)})
        except Exception:
            pass
    out["controls"] = controls
    return out


def survey(page, dwell_ms: int = 3000, max_follow: int = 0) -> dict:
    """The page's headings and controls with the guard's verdict. Follows
    nothing, listens to nothing, no screenshot."""
    report = {"pages": []}
    page.wait_for_timeout(dwell_ms)
    report["pages"].append(_page_summary(page))
    return report
