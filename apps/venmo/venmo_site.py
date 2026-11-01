"""ALL account.venmo.com selectors, URLs, and page behavior live here.

When Venmo changes its web account pages, repair this file only.

STATUS: built 2026-10-13 from a read-only, masked survey of a signed-in
account, then run on that one personal account: 24 monthly statements,
October 2024 to September 2026, two of them busy months expanded with
"Show more" (12 and 11 rows), every PDF holding the whole statement. What
the survey and the run established is stated plainly below; what they
did not is marked UNCONFIRMED, and the app stops rather than guesses at
each of those points.

WHAT THE SURVEY ESTABLISHED
  * Statements is https://account.venmo.com/statement, a Next.js page. A
    visit with no query settles on
    /statement?accountType=…&month=…&profileId=…&year=… (keys as listed;
    the profile id is PRIVATE, the account type is a word).
  * The page is an HTML "Account Statement" for ONE month: beginning and
    ending balance, transaction fees, a crypto summary (USD and Crypto
    tabs), and "Completed transactions". Its data comes from a POST to
    https://api.venmo.com/graphql, operationName TransactionsHistory, which
    the page itself makes. This app never requests that host; it only
    hears the page's own answer.
  * A month picker is a text input showing "October 2026". Its id is
    React-generated and unstable, so it is found by its value.
  * The page offers two buttons, "Download CSV" and "Send to email". There
    is NO PDF statement on the web. "Download CSV" builds the file in the
    page (a blob: download named VenmoStatement_<Month>_<Year>.csv).
  * "Log out" is the link /account/logout.
  * Seen live on 2026-10-13, read only: changing month= and year= in the
    address shows that month (picker and rows change). The completed
    transactions are one [class*=completedTransactionList] whose children
    are <a class*=transactionItem> rows, each with a [data-testid=money]
    amount. While loading the page draws [data-testid=shimmer]
    placeholders. A month with no transactions draws no list and says "No
    transactions yet for this month, but as soon as they start rolling in,
    we'll list them here."; that is also what a month before the account
    opened shows. Venmo does NOT ask TransactionsHistory for every month
    (its client cache answers some), and over CDP that answer's body is
    often gone before it can be read.
  * A busy month draws ten rows at a time: the list's last child is then
    not a row but a block holding one "Show more" button (2025-08 and
    2025-07, seen live).

THE SHAPE THIS APP TAKES
  The statement page itself is printed to PDF through the core's
  receipt_pdf.print_page_to_pdf (CDP Page.printToPDF on the live page, the
  route Nelnet, Kroger, Costco and Apple already take in the account
  holder's own browser). Each month is reached by its own address and
  bound by the page's own state (settled): the address still names it,
  the picker shows it, the heading is drawn, nothing is loading, and
  either its rows (with at most the list's own "Show more" pager after
  them) or its no-transactions words are drawn, holding still across two
  reads, or for the no-transactions words across EMPTY_HOLD_MS. A month
  with no transactions is not listed. Before printing, the
  one press this app ever makes, the list's own "Show more", is pressed
  until every row is drawn (show_all, each press required to draw more,
  at most SHOW_MORE_PRESSES). Only then is the page printed and filed as
  "<month end> Venmo Statement.pdf". The CSV is never pressed for and never
  kept: no PaperPull app keeps a CSV, and the core's capture, naming,
  validation and rename all take a PDF. Keeping it would be a core change
  first.

UNCONFIRMED (the app stops at each until a run shows it)
  * The account type's value. Only "personal" is accepted (a business
    profile is not listed).
  * How far back the months go. A month before the account opened shows
    the same no-transactions words as an empty month, so it is skipped.
    The walk goes back to the run's start date, and with none set it reads
    MAX_MONTHS months and stops the list (CapReached) when the oldest of
    them has transactions, since older months may have them too. A month
    the page will not show as asked stops the list.
  * That pressing "Show more" until it is gone draws every transaction,
    and that the printed page holds them all. A Show more press that draws
    nothing more, a pager still shown after SHOW_MORE_PRESSES presses, any
    other load-more control, or a TransactionsHistory answer that, when
    heard and readable, says more is to come (more_to_come) and is the
    newest one read when the month is printed, stops that month. The
    number of rows printed is kept in the month's record.
  * What a signed-out visit or a signed-out GraphQL answer looks like. A
    sign-in address, a password field, or a 401 or 403 from the page's
    own GraphQL answer raises SessionExpired.
  * Tax documents (/settings/tax-document, GraphQL getTaxCryptoDocuments)
    are not listed: the surveyed account had no form, so the shape of one
    is unknown and its stop could not be tested.

Sign-in (password, and the SMS or email code) is the account holder's own,
in the browser. No other host is ever opened: not venmo.com, not
id.venmo.com where the sign-in is, not paypal.com. api.venmo.com is only
heard, never asked.

SAFETY (an account that moves money):
  This module is strictly READ-ONLY. It presses exactly one kind of
  control, the completed list's own pager labelled exactly "Show more"
  (is_show_more, through pressing.click, which stops the run if anything
  covers it), changes no input, and fills nothing. It must NEVER activate
  any control that pays,
  requests, sends, splits or transfers money ("Transfer balance", "Pay or
  Request"), cashes out, adds money, links a bank or card, buys or sells
  crypto, tips, donates, switches to or creates a business profile, emails
  a statement ("Send to email"), downloads the CSV, goes paperless,
  changes privacy, notifications or any setting, or signs out.
  FORBIDDEN_CONTROL_RE is kept for the survey's verdicts and for any future
  repair that reaches for a control; a control must ALSO match one of the
  anchored document actions (SAFE_DOC_CONTROL_RES), and the shared core
  guards are consulted every time.

PRIVATE
  The profile id, username (@handle), display name, phone, email, and every
  transaction's counterparty, note and amount are private. The month is
  not. The profile id and what names the account holder are registered as
  private words before anything is printed (_guard_profile), and
  diagnostics go through the core's shaping. The printed PDF is the
  account holder's own statement and holds what the statement holds; none
  of it is logged or put in a file name.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import sys
from dataclasses import dataclass
from datetime import date as _date, timedelta
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import parse_qs, urlencode, urlsplit

from paperpull_core import pressing
from paperpull_core import receipt_pdf
from paperpull_core.controls import SETTINGS_CONTROL_RE, AUTH_CONTROL_RE
from paperpull_core.redact import private_words, redact, set_private_words  # noqa: F401  (re-exported)
from paperpull_core.urls import is_safe_url as _host_allows
from paperpull_core.dates import last_day as _last_day
from paperpull_core.dates import checked as _checked_date
from paperpull_core.dates import full_year as _full_year
from paperpull_core.words import words_for as _words_for
from paperpull_core.characters import whole_json

log = logging.getLogger("venmo_docs.site")


def _words():
    """This app's own words for paperpull_core.words."""
    return _words_for("Venmo", sys.modules[__name__])


# ---------------------------------------------------------------------------
# Addresses (surveyed 2026-10-13)
# ---------------------------------------------------------------------------
BASE = "https://account.venmo.com"
DOCUMENTS_PATH = "/statement"
DOCUMENTS_URL = BASE + DOCUMENTS_PATH
STATEMENTS_URL = DOCUMENTS_URL
BILLING_URL = DOCUMENTS_URL
URLS = {
    "home": f"{BASE}/",
    # A signed-out visit is sent on to Venmo's sign-in, where the account
    # holder signs in.
    "login": DOCUMENTS_URL,
    "documents": DOCUMENTS_URL,
    "statements": DOCUMENTS_URL,
}
# The page's own data request, heard and never made.
API_HOST = "api.venmo.com"
GRAPHQL_PATH = "/graphql"
STATEMENT_OP = "TransactionsHistory"
# The statement address's query, exactly these keys, one value each.
QUERY_KEYS = {"accountType", "month", "year", "profileId"}

# ===========================================================================
# UNCONFIRMED. Each value below is a choice made without a run behind it;
# survey() prints what the page has, so each can be checked.
# ===========================================================================
# The only account type listed. The survey masked its value.
ACCOUNT_TYPE = "personal"
# How many finished months the walk goes back when the run sets no start
# date. How far Venmo goes back is not known, so when the oldest of them
# has transactions the list is not called whole (CapReached). With a start
# date the walk goes back to it.
MAX_MONTHS = 24
# The first month a statement address can name, since its year is 20xx.
FIRST_MONTH = "2000-01"
# A month counts as finished only this many whole days after its last
# day. The computer's date can be a day ahead of Venmo's own, and a
# payment of the month's last evening can post after midnight here.
SETTLE_DAYS = 1
# Venmo's sign-in, matched in the lowered address.
LOGIN_URL_MARKERS = ["id.venmo.com", "/signin", "/sign-in", "/login", "/account/logout"]
# The completed transaction list and its rows, as drawn on 2026-10-13: one
# list per statement, each row an <a> holding a [data-testid=money] amount.
TX_LIST = "[class*='completedTransactionList']"
TX_ROW = ":scope > a[class*='transactionItem']"
# What a month with no transactions says instead of drawing the list, seen
# on 2026-10-13: "No transactions yet for this month, but as soon as they
# start rolling in, we'll list them here."
EMPTY_MONTH_RE = re.compile(r"No transactions yet for this month")
# The one control this app ever presses: the completed list's own pager,
# labelled exactly "Show more", seen live 2026-10-13 under a busy month's
# first ten rows. Pressed only by show_all, before a month is printed, at
# most SHOW_MORE_PRESSES times, and only when each press draws more rows.
SHOW_MORE_LABEL_RE = re.compile(r"show more", re.I)
SHOW_MORE_CSS = "[class*='completedTransactionList'] > div:last-child button, " \
                "[class*='completedTransactionList'] > div:last-child [role='button']"
SHOW_MORE_PRESSES = 60
# A control that would draw more of a month's transactions. Seen, the month
# stops: what is drawn is not all of it.
LOAD_MORE_RE = re.compile(r"^\s*(load|show|see)\s+more\b", re.I)
# What would identify the account holder: the profile's links and labels.
PROFILE_SELECTORS = ("a[href^='/u/'], a[href*='venmo.com/u/'], [data-testid*='profile' i], "
                     "[data-testid='avatar'], img[alt]")
# How long a month's page is given to show its month and its answer.
SETTLE_MS = 20000
POLL_MS = 250
# How long a month's "No transactions yet" must hold before the month is
# skipped, since a page can say it for a moment before its rows draw.
EMPTY_HOLD_MS = 2000
# ===========================================================================
# End of UNCONFIRMED.
# ===========================================================================

# ---------------------------------------------------------------------------
# HARD SAFETY GUARD. Tuned for a payments app. Every stem anchored so
# "Statement" is not "settlement" and "Download" is not "load".
# ---------------------------------------------------------------------------
FORBIDDEN_CONTROL_RE = re.compile(
    r"(\bpay\b|\bpaying\b|\bpayments?\b|\bpay\s*now\b|\bautopay\b|\brequest(s|ed|ing)?\b|\bsend\b|"
    r"\bsplit\b|\btransfer|\bcash\s*out\b|\badd\s+money\b|\binstant\b|\bbank|\bcards?\b|\bdebit\b|"
    r"\bcredit\b|\bcrypto\b|\bbitcoin\b|\bbuy\b|\bsell\b|\btips?\b|\bcharit|\bdonat|\bgroups?\b|"
    r"\bbusiness\b|\bswitch\b|\bprofiles?\b|\bprivacy\b|\bfriends?\b|\bnotifications?\b|"
    r"\bsign\s*(out|off|up)\b|\blog\s*(out|off)\b|\blogout\b|\bcsv\b|\bexport\b|\bhistory\b|\bexcel\b|"
    r"\bpaperless\b|\be-?delivery\b|\bsecurity\b|\baddress(es)?\b|\bbackup\b|\bconnected\b|"
    r"\bsettings?\b|\bpreferences?\b|\bsave\b|\bsubmit\b|\bconfirm\b|\bcontinue\b|"
    r"\bdelet(e|es|ed|ing)\b|\bremov(e|es|ed|ing|al)\b|\bcancel\b|\bedit(s|ed|ing)?\b|"
    r"\bupdat(e|es|ed|ing)\b|\bchang(e|es|ed|ing)\b|\bmanage\b|\bturn\s+(on|off)\b|\bopt\s*-?\s*(in|out)\b|"
    r"\bclose\b|\bupload\b|\bemail\b|\bshare\b|\bchat\b|\bcontact\b|\bsupport\b|\benroll|\bregist(er|ration)\b|"
    r"\bverify\b|\bagree\b|\baccept\b|\bauthori[sz]e\b|\bpassword\b|\busername\b|\brefund\b|"
    r"\blike\b|\bcomment\b|\bdispute\b|\breport\b|\bdetails\b|\bdeposit|\bwithdraw)", re.I)

# The document actions this app would ever accept, anchored whole. Venmo
# offers none it presses; these are kept so the shared guard tests hold
# this app to the same rules as every other.
SAFE_DOC_CONTROL_RES = (
    re.compile(r"^(view|download)(\s+the)?(\s+monthly)?\s+(statement|pdf)(\s+pdf)?$", re.I),
    re.compile(r"^download$", re.I),
)

SECURITY_CHALLENGE_MARKERS = [
    "enter the code", "verification code", "6-digit", "two-factor",
    "two-step", "authenticator", "confirm your identity", "verify your identity",
    "we sent a code", "we texted", "device approval", "approve this login",
    "are you a robot", "captcha", "let's verify", "check your email",
    "check your phone", "your session has expired", "log back in",
    "access denied", "confirm it's you",
]

RATE_LIMIT_MARKERS = [
    "too many requests", "rate limit", "try again later",
    "temporarily unavailable", "http error 429", "unusual traffic",
]

# Fallback selectors (used by --diagnose and the journal).
FALLBACK = {
    "doc_row": "input[type='text']",
    "page_ready": "h1, h2, h3",
    "download_control": "button",
    "profile": PROFILE_SELECTORS,
}

# ---------------------------------------------------------------------------
# Date parsing (verbatim from the Nelnet app; the month picker uses
# month_of below, which reads one shape only)
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


# The month picker's value exactly as the survey saw it: "October 2026".
_MONTH_VALUE_RE = re.compile(
    r"(January|February|March|April|May|June|July|August|September|October|November|December)"
    r" ([0-9]{4})")
_FULL_MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august",
                "september", "october", "november", "december"]
_MONTH_ID_RE = re.compile(r"([0-9]{4})-(0[1-9]|1[0-2])")


def month_of(text) -> Optional[str]:
    """The month picker's value as YYYY-MM, or None. The whole value must be
    the month and its year; nothing is found inside other text."""
    m = _MONTH_VALUE_RE.fullmatch(re.sub(r"\s+", " ", str(text or "")).strip())
    if not m:
        return None
    year = int(m.group(2))
    if not 2000 <= year <= 2099:
        return None
    return f"{year:04d}-{_FULL_MONTHS.index(m.group(1).lower()) + 1:02d}"


def month_end(month_id) -> str:
    """The last day of a YYYY-MM month as YYYY-MM-DD, or "" when it is not
    one. This is the date a statement is filed under."""
    m = _MONTH_ID_RE.fullmatch(str(month_id or ""))
    if not m:
        return ""
    year, month = int(m.group(1)), int(m.group(2))
    return f"{year:04d}-{month:02d}-{_last_day(year, month):02d}"


def months_to_walk(today: _date, floor: str = "", limit: Optional[int] = None) -> List[str]:
    """The finished months, newest first, from the one before `today`'s
    back to `floor` (YYYY-MM-DD, the run's start date) when one is set, and
    otherwise MAX_MONTHS of them. A `limit` given ends the walk sooner when
    it comes first. No walk goes back past FIRST_MONTH, the first month a
    statement address can name (statement_query). The month under way is
    never one, since its statement is not final, and a saved statement is
    never fetched again. Neither is the month before it until SETTLE_DAYS
    have passed since that month's last day."""
    today = today - timedelta(days=SETTLE_DAYS)
    if limit is None:
        limit = -1 if floor else MAX_MONTHS
    y, m = today.year, today.month
    out: List[str] = []
    while limit < 0 or len(out) < limit:
        m -= 1
        if m == 0:
            y, m = y - 1, 12
        month = f"{y:04d}-{m:02d}"
        if month < FIRST_MONTH or (floor and month_end(month) < floor):
            break
        out.append(month)
    return out


# ---------------------------------------------------------------------------
# Session / safety
# ---------------------------------------------------------------------------

class ProfileChanged(Exception):
    """The browser is signed in to another Venmo profile than the one the
    statements were listed on. The run stops: printing this profile's
    month would file it as the other's, done for good."""


class SessionExpired(Exception):
    """Venmo answered as a signed-out session: its sign-in page, a password
    field, or a 401 or 403 to the page's own data request. The run stops
    for the account holder."""


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
    """Names the code, CAPTCHA or throttling prompt on screen, or None.
    Visible text only. A page that shows a month in its picker is not a
    challenge, whatever its text says further down."""
    try:
        if any(month_of(v) for v in (_state(page).get("months") or [])):
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
# Hosts and the statement address. Exact, parsed, no subdomain wildcard.
# ---------------------------------------------------------------------------
ALLOWED_HOSTS = {"account.venmo.com"}
_PROFILE_ID_RE = re.compile(r"[A-Za-z0-9_-]{4,64}")


def is_safe_url(url: str) -> bool:
    """True only for an https URL on exactly account.venmo.com."""
    return _host_allows(url, ALLOWED_HOSTS, subdomains=False)


def profile_tag(profile_id: str) -> str:
    """A short, one-way name for a profile id, kept in a statement's record
    so a run can tell it is still on the profile the statement was listed
    on. The id itself is never written down."""
    return hashlib.sha256(("venmo-profile\0%s" % (profile_id or "")).encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class Where:
    """The profile the Statements page settled on: its account type and
    its id, which is private and never written down."""
    account_type: str
    profile_id: str


def statement_query(url) -> Optional[dict]:
    """The statement address's query as {accountType, month, year,
    profileId}, or None unless the URL is exactly this host's Statements
    page with exactly those four keys, one plain value each, a month of 1
    to 12, a four-digit year and a profile id of the right shape."""
    if not is_safe_url(url):
        return None
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.path.rstrip("/") != DOCUMENTS_PATH or parts.fragment:
        return None
    q = parse_qs(parts.query or "", keep_blank_values=True)
    if set(q) != QUERY_KEYS or any(len(v) != 1 for v in q.values()):
        return None
    got = {k: v[0] for k, v in q.items()}
    if not re.fullmatch(r"[1-9]|1[0-2]|0[1-9]", got["month"]) or not re.fullmatch(r"20[0-9]{2}", got["year"]):
        return None
    if not re.fullmatch(r"[A-Za-z]{2,20}", got["accountType"]) or not _PROFILE_ID_RE.fullmatch(got["profileId"]):
        return None
    return got


def month_url(where: Where, month_id: str) -> str:
    """The Statements page's address for this YYYY-MM month on this
    profile, or "" when the month is not one."""
    m = _MONTH_ID_RE.fullmatch(str(month_id or ""))
    if not m or not where or not where.profile_id:
        return ""
    url = DOCUMENTS_URL + "?" + urlencode({"accountType": where.account_type, "month": str(int(m.group(2))),
                                            "profileId": where.profile_id, "year": m.group(1)})
    return url if statement_query(url) else ""


def _month_in(q: dict) -> str:
    return f"{int(q['year']):04d}-{int(q['month']):02d}"


# ---------------------------------------------------------------------------
# Statements. Each month is the Statements page at its own address;
# nothing is pressed.
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
    # The statement's month, YYYY-MM, which is how it is reached and what
    # tells two statements apart.
    document_id: str = ""
    # profile_tag of the profile it was listed on.
    profile: str = ""


class ListStopped(Exception):
    """The list has a part this could not read, so what was read is not all
    of it. `docs` holds what was read before it stopped."""

    def __init__(self, why: str, docs=None):
        super().__init__(why)
        self.docs = list(docs or [])


class CapReached(ListStopped):
    """A walk with no start date read its MAX_MONTHS months and the oldest
    of them has transactions, so older months may have them too and the
    list is not whole. A start date takes the walk back to it."""


class Heard:
    """The page's own GraphQL answers to one navigation, heard on the
    request and response events.

    Bound to the navigation: nothing counts until the page's own document
    request for an address `arms` accepts has been seen, and then only the
    answers to GraphQL requests made after it. An answer still on its way
    from the page before (another month) is never taken for this one. A
    request or response to any host but api.venmo.com, or not to /graphql,
    is not heard. Nothing is ever requested here.

    Of each answer the operation's name and the status are kept. Of the
    TransactionsHistory answer the body is also walked, when it can still
    be read, in memory and never kept or logged, only to see whether it
    says more transactions are to come (partial). The flag is the newest
    readable answer's, and an answer whose body cannot be read leaves it as
    it was, so an earlier answer that said more is to come is only cleared
    by a later one that says the list is whole. Hearing it is an extra
    check, never a requirement: Venmo does not ask for every month (its
    client cache answers some), and over CDP the body is often gone before
    it can be read, which is logged and otherwise ignored."""

    def __init__(self, arms=None):
        self.arms = arms or (lambda url: statement_query(url) is not None)
        self.armed = False
        self.asked: list = []
        self.answers: List[Tuple[str, int]] = []
        self.pending: list = []
        self.partial = False

    @staticmethod
    def _graphql(url) -> bool:
        try:
            parts = urlsplit(url or "")
        except ValueError:
            return False
        return parts.scheme == "https" and parts.hostname == API_HOST and parts.path == GRAPHQL_PATH

    def on_request(self, request) -> None:
        try:
            if request.is_navigation_request():
                if self.arms(request.url or ""):
                    self.armed, self.asked, self.answers = True, [], []
                    self.pending = []
                    self.partial = False
                return
            if self.armed and self._graphql(request.url):
                self.asked.append(request)
        except Exception:
            return

    def on_response(self, response) -> None:
        try:
            if not self._graphql(response.url):
                return
            request = response.request
            if not any(request is r for r in self.asked):
                return
            op = _operation(request.post_data or "")
            status = int(response.status)
            self.answers.append((op, status))
            if op == STATEMENT_OP and status == 200:
                # The body is read later, from statement(): inside the event
                # handler the answer is still on its way and cannot be read.
                self.pending.append(response)
        except Exception:
            return

    def _read_pending(self) -> None:
        """Walk the TransactionsHistory answers heard so far, once each, in
        memory. One whose body cannot be read is skipped."""
        while self.pending:
            response = self.pending.pop(0)
            try:
                # An answer whose body is still arriving is waited for, not
                # called unreadable: finished() returns once it is whole.
                finished = getattr(response, "finished", None)
                if callable(finished):
                    finished()
                body = whole_json(response.json())
            except Exception as e:
                # Over CDP the body is often gone before it can be read
                # (Network.getResponseBody: no resource). The page's own
                # state decides the month, so this check is only skipped.
                log.info("a statement answer's body was not read (%s)", type(e).__name__)
                continue
            if isinstance(body, (dict, list)):
                # The newest answer read says whether more is to come, so
                # the answer to the press that drew the last rows replaces
                # what the first answer said.
                self.partial = more_to_come(body)

    def listen(self, page) -> None:
        page.on("request", self.on_request)
        page.on("response", self.on_response)

    def stop(self, page) -> None:
        for event, fn in (("request", self.on_request), ("response", self.on_response)):
            try:
                page.remove_listener(event, fn)
            except Exception:
                pass

    def signed_out(self) -> bool:
        """Whether any GraphQL answer heard since this navigation, a "Show
        more" press's own among them, was a 401 or 403."""
        self._read_pending()
        return any(s in (401, 403) for _op, s in self.answers)

    def statement(self) -> Optional[int]:
        """The status of the newest TransactionsHistory answer to this
        navigation, or None. The answers' bodies are read here, after the
        event that brought them."""
        self._read_pending()
        found = [s for op, s in self.answers if op == STATEMENT_OP]
        return found[-1] if found else None


_HAS_MORE_KEY = re.compile(r"has_?next(_?page)?|has_?more", re.I)
_NEXT_KEY = re.compile(r"next(_?(cursor|token|id|page(_?token)?))?|cursor|next_?offset", re.I)


def more_to_come(body) -> bool:
    """Whether a GraphQL answer says the list it holds goes on: a
    hasNextPage or hasMore that is true anywhere in it, or, when it has no
    such flag at all, a next cursor, token, id or page that is not empty.
    UNCONFIRMED: the survey did not record the answer's shape, so this
    looks for the shapes paged GraphQL answers take; a month whose answer
    says more is coming is never printed."""
    flags: list = []
    nexts: list = []

    def walk(node, depth=0):
        if depth > 12:
            return
        if isinstance(node, dict):
            for k, v in node.items():
                key = str(k)
                if _HAS_MORE_KEY.fullmatch(key):
                    flags.append(v is True)
                elif _NEXT_KEY.fullmatch(key):
                    nexts.append(v not in (None, "", False, 0, [], {}))
                walk(v, depth + 1)
        elif isinstance(node, list):
            for v in node:
                walk(v, depth + 1)
    walk(body)
    if flags:
        return any(flags)
    return any(nexts)


def _operation(body: str) -> str:
    """The operationName of a GraphQL request body, or "" when it has none
    this can read. Only the name is read; the variables are private."""
    try:
        data = whole_json(json.loads(body))
    except (TypeError, ValueError):
        return ""
    if isinstance(data, list):
        names = {str(d.get("operationName") or "") for d in data if isinstance(d, dict)}
        return STATEMENT_OP if STATEMENT_OP in names else ""
    return str(data.get("operationName") or "") if isinstance(data, dict) else ""


# What the open page shows that this app reads, all of it seen live on
# 2026-10-13: the value of every text input shaped like a month (the month
# picker), whether the "Account Statement" heading is drawn, how many
# transaction rows the completed list holds (each an <a> carrying an
# amount), whether a loading shimmer is drawn inside the statement, whether
# the page says the month has no transactions, and every control's label,
# for the Load more check. Read only; no text of a row is read.
_STATE_JS = r"""([listSel, rowSel, emptyRe]) => {
  const months = Array.from(document.querySelectorAll('input'))
    .map(i => (i.value || '').replace(/\s+/g, ' ').trim())
    .filter(v => /^[A-Z][a-z]+ [0-9]{4}$/.test(v));
  const heading = Array.from(document.querySelectorAll('h1, h2, h3'))
    .some(h => /^\s*account statement\s*$/i.test(h.textContent || ''));
  const lists = document.querySelectorAll(listSel);
  const rows = lists.length === 1 ? lists[0].querySelectorAll(rowSel).length : 0;
  const kids = lists.length === 1 ? lists[0].children.length : 0;
  // The list's own pager: its last child, not a row, holding exactly one
  // control and that control reading exactly "Show more".
  let pager = 0;
  if (lists.length === 1 && kids > rows) {
    const last = lists[0].lastElementChild;
    const isRow = last && last.matches('a[class*="transactionItem"]');
    const ctl = last && !isRow ? last.querySelectorAll('button, [role="button"], a') : [];
    const said = ctl.length === 1 ? (ctl[0].textContent || '').replace(/\s+/g, ' ').trim() : '';
    if (ctl.length === 1 && /^show more$/i.test(said)) pager = 1;
  }
  const main = document.querySelector('main') || document.body;
  const empty = new RegExp(emptyRe, 'i').test((main && main.innerText) || '');
  const loading = main ? main.querySelectorAll('[data-testid="shimmer"]').length : 0;
  const labels = Array.from(document.querySelectorAll('button, [role="button"], a'))
    .map(b => (b.textContent || b.getAttribute('aria-label') || '').replace(/\s+/g, ' ').trim())
    .filter(t => t && t.length < 40);
  return {months: months, heading: heading, lists: lists.length, rows: rows, kids: kids, pager: pager,
          empty: empty, loading: loading, labels: labels};
}"""


def _state(page) -> dict:
    try:
        got = page.evaluate(_STATE_JS, [TX_LIST, TX_ROW, EMPTY_MONTH_RE.pattern])
    except Exception as e:
        log.info("reading the statement page failed (%s)", type(e).__name__)
        return {}
    return got if isinstance(got, dict) else {}


# What would identify the account holder on the page: the profile's links,
# labels and image descriptions, and @handles, email addresses and phone
# numbers in the page's visible text. Read only to be registered as private
# words; never logged or returned past redact's word list.
_PROFILE_JS = r"""(sel) => {
  const out = [];
  for (const el of document.querySelectorAll(sel)) {
    out.push(el.textContent || '');
    for (const a of ['href', 'alt', 'title', 'aria-label']) out.push(el.getAttribute(a) || '');
  }
  const body = (document.body && document.body.innerText) || '';
  for (const m of body.matchAll(/@[A-Za-z0-9_-]{2,}/g)) out.push(m[0]);
  for (const m of body.matchAll(/[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/g)) out.push(m[0]);
  for (const m of body.matchAll(/\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}/g)) out.push(m[0]);
  return out;
}"""

# Words the profile reading would otherwise register that are Venmo's own:
# registering them would turn "Statement" into "[name]" in every
# diagnostic.
_NOT_PRIVATE = {"venmo", "statement", "statements", "profile", "account", "settings",
                "help", "home", "personal", "business", "avatar", "settings/profile"}


def private_parts(seen) -> set:
    """The words to register from what the profile reading returned. Each
    value is kept whole (a handle, an email) and in parts, as redact
    applies words anywhere in a string: a part of four letters or more, or
    one with a digit, and a handle with and without its "@". Venmo's own
    words and addresses are left out, and so is anything with a space,
    whose parts are registered on their own
    (paperpull_core.redact.set_private_words keeps parts only)."""
    parts = set()
    for w in seen or []:
        w = str(w or "").strip()
        for part in [w] + re.split(r"[\s,/#()|:?=&]+", w):
            part = part.strip().strip(".")
            if re.search(r"[\s,]", part):
                continue
            low = part.lower()
            if not part or low in _NOT_PRIVATE or low.startswith(("http", "venmo.com", "account.venmo")):
                continue
            if part.startswith("@") and len(part) >= 3:
                parts.add(part)
                part = part[1:]
            if len(part) >= 4 or re.search(r"[0-9]", part):
                parts.add(part)
    return parts


def _register(words) -> None:
    new = set(words) - set(private_words())
    if new:
        set_private_words(private_words() + sorted(new))


def _guard_profile(page, where: Optional[Where] = None) -> None:
    """Register the profile id and what names the account holder as
    private words, beside the owner's name already there, before anything
    is printed or said."""
    if where is not None:
        _register([where.profile_id])
    try:
        seen = page.evaluate(_PROFILE_JS, PROFILE_SELECTORS)
    except Exception as e:
        log.info("the profile could not be read (%s)", type(e).__name__)
        return
    if isinstance(seen, list):
        _register(private_parts(seen))


def _goto(page, url: str) -> None:
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
    except Exception as e:
        log.info("opening Statements failed (%s)", type(e).__name__)
        if looks_signed_out(page):
            raise SessionExpired("Venmo showed its sign-in page")
        raise ListStopped("the Statements page did not open")
    if looks_signed_out(page):
        raise SessionExpired("Venmo showed its sign-in page")


def _where(page) -> Where:
    """Open Statements by its plain address and read the profile it settles
    on from the address Venmo gives it. The profile id is registered as a
    private word at once. A page that settles anywhere else, or on another
    account type, stops the list."""
    _goto(page, DOCUMENTS_URL)
    q = statement_query(page.url or "")
    if q is not None:
        _register([q["profileId"]])
    if q is None:
        raise ListStopped("the Statements page did not settle on a statement address")
    if q["accountType"] != ACCOUNT_TYPE:
        raise ListStopped("the Statements page settled on a profile this app does not list")
    return Where(q["accountType"], q["profileId"])


def settled(state: dict, month: str) -> str:
    """Whether the page state read by _STATE_JS shows `month` drawn: "" when
    it does, else why not. Exactly one month picker reading that month, the
    "Account Statement" heading, no loading shimmer in the statement, and
    either one completed list whose every child is a transaction row but
    for, at most, its own last "Show more" pager (a busy month draws ten
    rows at a time; show_all draws the rest before printing), or no list
    and the page's own words for a month with no transactions."""
    if not state.get("heading"):
        return "the statement did not finish drawing"
    shown = [month_of(v) for v in state.get("months") or []]
    if shown != [month]:
        return "the month picker does not show the month asked for"
    if state.get("loading"):
        return "the statement is still loading"
    lists, rows = state.get("lists") or 0, state.get("rows") or 0
    if state.get("empty") and lists:
        return "the page draws transactions and says there are none"
    if lists == 1 and rows > 0 and rows + (1 if state.get("pager") else 0) == state.get("kids"):
        return ""
    if lists == 0 and state.get("empty"):
        return ""
    return "the month's transactions did not finish drawing"


def _month_heard(month: str) -> "Heard":
    """A Heard armed by the navigation to this month's own address."""
    return Heard(arms=lambda u: (statement_query(u) or {}).get("month") is not None
                 and _month_in(statement_query(u)) == month)


def _still_here(page, where: Where, month: str, heard: "Heard") -> None:
    """Raise unless the tab is still at exactly this month's statement
    address on this profile and account type, and nothing heard or shown
    says it is signed out."""
    if heard.signed_out():
        raise SessionExpired("Venmo answered the statement as signed out")
    q = statement_query(page.url or "")
    if q is None or _month_in(q) != month or q["profileId"] != where.profile_id \
            or q["accountType"] != where.account_type:
        if looks_signed_out(page):
            raise SessionExpired("Venmo showed its sign-in page")
        raise ListStopped("the Statements page did not stay on the month asked for")
    if looks_signed_out(page):
        raise SessionExpired("Venmo showed its sign-in page")


def _open_month(page, where: Where, month: str, heard: Optional["Heard"] = None) -> int:
    """Open one month's statement by its own address and wait until the
    page shows it whole (settled), twice in a row with the same rows, and
    return how many transaction rows it drew (0 for a month with none). A
    month that says it has none must say so for EMPTY_HOLD_MS before it is
    taken as empty, since a page can say it a moment before its rows draw.

    The month is bound by the page's own state, never by hearing its data:
    Venmo does not ask for every month (its client cache answers some).
    When the page's TransactionsHistory answer to this navigation IS heard,
    it is an extra check: a 401 or 403 raises SessionExpired, and one that
    says more is to come stops the month. A sign-in page or a password
    field raises SessionExpired. An address that no longer names this
    month on this profile, a page that does not settle in SETTLE_MS, or a
    load-more control other than the list's own pager raises ListStopped.
    Nothing is pressed here; show_all presses the pager.

    `heard`, when given, is a _month_heard already listening, which the
    caller keeps listening through show_all and takes off itself."""
    url = month_url(where, month)
    if not url:
        raise ListStopped("a statement address could not be made")
    own = heard is None
    if own:
        heard = _month_heard(month)
        heard.listen(page)
    try:
        _goto(page, url)
        why, last, held = "the statement did not finish drawing", None, 0
        state = {}
        for _ in range(max(2, SETTLE_MS // POLL_MS)):
            _still_here(page, where, month, heard)
            state = _state(page)
            why = settled(state, month)
            seen = (state.get("rows"), state.get("empty"))
            # How many waits the same settled page has held across.
            held = held + 1 if not why and seen == last else 0
            if held and (state.get("rows") or held * POLL_MS >= EMPTY_HOLD_MS):
                break
            last = seen if not why else None
            page.wait_for_timeout(POLL_MS)
        else:
            raise ListStopped(why or "the statement did not hold still")
        if heard.signed_out():
            raise SessionExpired("Venmo answered the statement as signed out")
        if heard.partial and not state.get("pager"):
            # The answer says more is to come while the page shows no "Show
            # more" to bring it: a shape this app does not know. With the
            # pager drawn, show_all brings the rest before anything is printed.
            raise ListStopped("the statement's own answer says more transactions are to come")
        mores = sum(1 for t in state.get("labels") or [] if LOAD_MORE_RE.match(str(t or "")))
        if mores > (1 if state.get("pager") else 0):
            raise ListStopped("the page shows a Load more control this app does not know")
    finally:
        if own:
            heard.stop(page)
    _guard_profile(page, where)
    return int(state.get("rows") or 0)


def is_show_more(label) -> bool:
    """The guard for the one press this app makes: a label that is exactly
    "Show more", and that neither this app's blocklist nor the shared core
    guards refuse. Deny by default; anything more in the label is refused."""
    name = re.sub(r"\s+", " ", str(label or "")).strip()
    if not SHOW_MORE_LABEL_RE.fullmatch(name):
        return False
    if FORBIDDEN_CONTROL_RE.search(name) or SETTINGS_CONTROL_RE.search(name) or AUTH_CONTROL_RE.search(name):
        return False
    return True


def _wait_drawn(page, where: Where, month: str, before: int, heard: "Heard") -> dict:
    """The page state once it shows `month` drawn with more rows than
    `before`, the same on two reads; ListStopped when it does not within
    SETTLE_MS. The address and the answers heard are checked on every
    read (_still_here)."""
    last = None
    for _ in range(max(2, SETTLE_MS // POLL_MS)):
        _still_here(page, where, month, heard)
        state = _state(page)
        seen = (state.get("rows"), state.get("pager"))
        if not settled(state, month) and (state.get("rows") or 0) > before and seen == last:
            return state
        last = seen
        page.wait_for_timeout(POLL_MS)
    raise ListStopped("a Show more press did not draw more transactions")


def show_all(page, where: Where, month: str, heard: "Heard") -> int:
    """Draw every transaction of the open month, pressing the list's own
    "Show more" pager through pressing.click under is_show_more, and return
    how many rows are drawn. Each press must draw more rows, and the pager
    must be gone within SHOW_MORE_PRESSES presses, or else ListStopped,
    and nothing is printed. A pager the page has turned off is not pressed
    and leaves this month for review (ListStopped), while a covered one
    stops the run (pressing). Nothing else is ever pressed. After every
    press the address must still be this month's on this profile and no
    GraphQL answer heard may be a 401 or 403 (SessionExpired)."""
    _still_here(page, where, month, heard)
    state = _state(page)
    if settled(state, month):
        raise ListStopped("the statement did not finish drawing")
    for _ in range(SHOW_MORE_PRESSES):
        if not state.get("pager"):
            return int(state.get("rows") or 0)
        before = int(state.get("rows") or 0)
        loc = page.locator(SHOW_MORE_CSS)
        if loc.count() != 1:
            raise ListStopped("the Show more control is not one this app can read")
        control = loc.first
        try:
            label = control.inner_text(timeout=3000)
        except Exception:
            label = ""
        if not is_show_more(label):
            raise ListStopped("the list's last control is not Show more")
        try:
            pressing.click(page, control, css=SHOW_MORE_CSS,
                           what="the Show more control of the month's transactions",
                           words=_words(), step="show more of the month")
        except pressing.TurnedOff:
            # The page has turned the pager off, so nothing was pressed and
            # the month is not drawn whole. Only this month is left, for
            # review and the next run, and the run goes on to the next one.
            raise ListStopped("the month's Show more is turned off on the page")
        _still_here(page, where, month, heard)
        state = _wait_drawn(page, where, month, before, heard)
    if state.get("pager"):
        raise ListStopped("Show more is still shown after the most presses this app makes")
    return int(state.get("rows") or 0)


def ready_to_print(page, where: Where, month: str, heard: "Heard") -> None:
    """The last check before a month is printed: the exact statement address
    for this month, profile and account type, nothing heard or shown saying
    signed out, the newest statement answer read not saying more is to
    come, the month settled with no pager left, and no load-more control of
    any kind on the page. Raises SessionExpired or ListStopped."""
    _still_here(page, where, month, heard)
    if heard.partial:
        raise ListStopped("the statement's own answer says more transactions are to come")
    state = _state(page)
    why = settled(state, month)
    if why:
        raise ListStopped(why)
    if state.get("pager") or any(LOAD_MORE_RE.match(str(t or "")) for t in state.get("labels") or []):
        raise ListStopped("the page still shows a Load more control")
    if not state.get("rows"):
        raise ListStopped("the month now shows no transactions")


def _rawdoc(month: str, i: int, where: Where) -> RawDoc:
    title = f"Venmo Statement {month}"
    return RawDoc(title=title, date_text=month_end(month), href=DOCUMENTS_PATH, text=title,
                  row_index=i, kind="statement", document_id=month,
                  profile=profile_tag(where.profile_id))


def goto_documents(page) -> bool:
    """Open the Statements page by its address and read the profile it
    settles on. False when it showed the sign-in page or settled elsewhere.
    No click, no banner handling."""
    try:
        _guard_profile(page, _where(page))
        return True
    except (SessionExpired, ListStopped) as e:
        log.info("Statements did not open: %s", e)
        return False


def bill_list_opens(page) -> bool:
    """Whether the Statements page opened and showed the last finished
    month, which only a signed-in page does."""
    try:
        where = _where(page)
        months = months_to_walk(_date.today(), limit=1)
        if months:
            _open_month(page, where, months[0])
        return True
    except (SessionExpired, ListStopped) as e:
        log.info("Statements could not be read: %s", e)
        return False


def scroll_full_page(page, rounds: int = 8, delay_ms: int = 600) -> None:
    try:
        for _ in range(rounds):
            page.mouse.wheel(0, 3000)
            page.wait_for_timeout(delay_ms)
    except Exception:
        pass


def expand_all(page) -> None:
    """Nothing to press: each month is its own address."""
    return None


def collect_download_docs(page, today: Optional[_date] = None, floor: str = "",
                          limit: Optional[int] = None) -> List[RawDoc]:
    """Every finished month's statement, newest first, back to `floor` (the
    run's start date) when one is set, and otherwise MAX_MONTHS months
    (months_to_walk). Each month is opened by its own address and listed
    only when the page shows it (_open_month) with at least one
    transaction. A month with none is skipped, counted only in the log, and
    the walk goes on. The first month the page will not show as asked stops
    the list, holding the months read before it, since what a month before
    the account opened looks like has not been seen, so it is not taken
    for the start of the history. With no start date, a walk whose oldest
    month has transactions stops the list too (CapReached), since older
    months may have them as well. A `limit`, as Diagnose gives, reads that
    many months only and is never the whole list. A signed-out page raises
    SessionExpired. Nothing is pressed."""
    where = _where(page)
    _guard_profile(page, where)
    docs: List[RawDoc] = []
    empty = 0
    walk = months_to_walk(today or _date.today(), floor, limit)
    for month in walk:
        try:
            rows = _open_month(page, where, month)
        except ListStopped as stop:
            raise ListStopped(str(stop), docs)
        if rows == 0:
            # "No transactions yet for this month": nothing to keep, and a
            # month before the account opened shows the same.
            empty += 1
            continue
        docs.append(_rawdoc(month, len(docs), where))
    if empty:
        log.info("%d month(s) with no transactions were not listed", empty)
    if not floor and limit is None and walk and docs and docs[-1].document_id == walk[-1]:
        raise CapReached("the oldest of the %d months read has transactions, so older "
                         "months may have them too" % len(walk), docs)
    return docs


def download_bill(page, dl_dir, iso_date: str, out_path, title: str = "",
                  trace: Optional[list] = None, href: str = "",
                  document_id: str = "", today: Optional[_date] = None, profile: str = "",
                  drawn: Optional[dict] = None) -> bool:
    """Save the statement discovery recorded for month `document_id`
    (YYYY-MM), dated `iso_date`, its last day, on the profile tagged
    `profile`, by printing that month's statement page to PDF once
    _open_month has shown it is that month and show_all has drawn every
    row. `drawn`, when given, is told how many rows were printed. A month
    not yet over, a record with no profile, or a month that now shows no
    transactions is refused. `dl_dir` is unused: nothing here goes through
    the browser's downloads. Nothing but the list's own "Show more" is
    pressed. SessionExpired, and ProfileChanged when the browser is on
    another profile, propagate to the run, and so does a pressing.Stop.
    So does ListStopped when Statements itself does not settle on a
    statement address of this app's account type (_where), since every
    month after this one opens the same page first. A month's own page
    that does not show as asked is that month's matter, False."""
    out_path = Path(out_path)
    month = (document_id or "").strip()
    today = today or _date.today()
    if href != DOCUMENTS_PATH or not month_end(month) or month_end(month) != (iso_date or "") \
            or month_end(month) >= (today - timedelta(days=SETTLE_DAYS)).isoformat() or not profile:
        log.info("no finished statement month was recorded for this document")
        if trace is not None:
            trace.append({"note": "no recorded statement"})
        return False
    heard = _month_heard(month)
    heard.listen(page)
    try:
        where = _where(page)
        if profile_tag(where.profile_id) != profile:
            raise ProfileChanged("the browser is on another Venmo profile than the one listed")
        try:
            if not _open_month(page, where, month, heard=heard):
                raise ListStopped("the month now shows no transactions")
            rows = show_all(page, where, month, heard)
            ready_to_print(page, where, month, heard)
        except ListStopped as stop:
            log.info("the statement for %s could not be shown: %s", month, stop)
            if trace is not None:
                trace.append({"note": "the statement could not be shown", "why": str(stop)[:80]})
            return False
        try:
            receipt_pdf.print_page_to_pdf(page, out_path)
        except Exception as e:
            log.info("printing the statement failed (%s)", type(e).__name__)
            if trace is not None:
                trace.append({"note": "print to PDF failed", "error": type(e).__name__})
            _drop(out_path)
            return False
    finally:
        heard.stop(page)
    if trace is not None:
        trace.append({"note": "printed the statement page", "month": month, "rows": rows})
    if drawn is not None:
        drawn["rows"] = rows
    try:
        if out_path.read_bytes()[:5] != b"%PDF-":
            _drop(out_path)
            return False
    except OSError:
        return False
    return True


def _drop(path: Path) -> None:
    try:
        if path.exists():
            path.unlink()
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Diagnose. Loose, redacted scrape and a survey of the signed-in page.
# No screenshot.
# ---------------------------------------------------------------------------

# What the survey reads of the page's structure: every input shaped like a
# month, every control's label and address with whether it carries a
# download attribute, and the headings. Read only.
_SURVEY_JS = r"""() => {
  const text = el => (el.textContent || el.getAttribute('aria-label') || '').replace(/\s+/g, ' ').trim();
  const inputs = Array.from(document.querySelectorAll('input')).map(i => ({
    type: i.getAttribute('type') || '', role: i.getAttribute('role') || '',
    value: (i.value || '').slice(0, 40)}));
  const controls = [];
  for (const el of document.querySelectorAll('a, button, [role="button"], [role="tab"], [role="menuitem"]')) {
    controls.push({tag: el.tagName.toLowerCase(), text: text(el).slice(0, 60),
                   href: (el.getAttribute('href') || '').slice(0, 300),
                   download: el.hasAttribute('download')});
  }
  return {inputs: inputs.slice(0, 40), controls: controls.slice(0, 120)};
}"""

SURVEY_LINK_RE = re.compile(r"^\s*statements?\s*$", re.I)


def collect_documents(page) -> List[RawDoc]:
    """Loose scrape used only by --diagnose: the month the picker shows,
    private words masked."""
    docs: List[RawDoc] = []
    for i, v in enumerate(_state(page).get("months") or []):
        text = redact(str(v or ""))
        month = month_of(text)
        docs.append(RawDoc(title=text[:60], date_text=month_end(month) if month else "",
                           text=text[:60], row_index=i))
    return docs


def _path_only(href) -> str:
    """An address's host and path, private words masked; never its query."""
    try:
        parts = urlsplit(str(href or ""))
        return redact((parts.hostname or "") + parts.path)[:120]
    except ValueError:
        return ""


def _query_fields(href) -> list:
    """The names of an address's query fields, never their values: a
    profile id is private."""
    try:
        q = urlsplit(str(href or "")).query
    except ValueError:
        return []
    return sorted({redact(kv.split("=", 1)[0])[:30] for kv in (q or "").split("&") if kv})


def _page_summary(page, heard: Optional[Heard] = None) -> dict:
    out = {"path": _path_only(page.url or ""), "query_fields": _query_fields(page.url or ""),
           "title": "", "statement_address": statement_query(page.url or "") is not None}
    try:
        out["title"] = redact(page.title() or "")
    except Exception:
        pass
    try:
        heads = page.locator("h1, h2, h3").all_inner_texts()
        out["headings"] = [redact(h.strip())[:80] for h in heads if h.strip()][:30]
    except Exception:
        out["headings"] = []
    try:
        raw = page.evaluate(_SURVEY_JS) or {}
    except Exception:
        raw = {}
    out["inputs"] = [{"type": i.get("type", ""), "role": i.get("role", ""),
                      "month": month_of(i.get("value", "")) or "",
                      "value_shape": "" if month_of(i.get("value", "")) else redact(i.get("value", ""))[:20]}
                     for i in (raw.get("inputs") or [])]
    out["controls"] = [{"tag": c.get("tag", ""), "text": redact(c.get("text", "")),
                        "href_path": _path_only(c.get("href", "")),
                        "href_query_fields": _query_fields(c.get("href", "")),
                        "download_attribute": bool(c.get("download")),
                        "safe": is_safe_control(c.get("text", "")),
                        "load_more": bool(LOAD_MORE_RE.match(c.get("text", "") or ""))}
                       for c in (raw.get("controls") or [])]
    if heard is not None:
        out["graphql_heard"] = [{"operation": redact(op)[:40], "status": s} for op, s in heard.answers[:40]]
    return out


def survey(page, dwell_ms: int = 4000, max_follow: int = 0) -> dict:
    """What the signed-in Statements page looks like, without saving
    anything: its settled path and the names of its query's fields (never
    their values), its headings, every input with the month it reads, every
    control with its path, query field names and the guard's verdict, and
    the names and statuses of the page's own GraphQL answers heard while it
    reloads at its own address. The profile's words are registered first,
    so they are masked. Presses nothing, follows nothing but the page's
    own address, and takes no screenshot."""
    report = {"pages": []}
    heard = Heard(arms=lambda u: is_safe_url(u) and urlsplit(u).path.rstrip("/") == DOCUMENTS_PATH)
    heard.listen(page)
    try:
        try:
            where = _where(page)
            _guard_profile(page, where)
        except (SessionExpired, ListStopped) as e:
            report["stopped"] = str(e) if isinstance(e, (SessionExpired, ListStopped)) else type(e).__name__
        page.wait_for_timeout(dwell_ms)
        _guard_profile(page)
        report["pages"].append(_page_summary(page, heard))
    finally:
        heard.stop(page)
    return report
