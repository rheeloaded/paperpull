"""ALL coinbase.com selectors, URLs, and page behavior live here.

When Coinbase changes its site, repair this file only.

STATUS: mapped against a signed-in retail account on 2026-10-09. The two
ways a document arrives:

  * A monthly statement. accounts.coinbase.com/statements lists one row per
    complete month back to the account's first month, behind a "Load more"
    button, each row with HTML / PDF / CSV buttons. Pressing the row's PDF
    button makes the page itself ask Coinbase to build that month's PDF
    (a POST the page makes, not this app), poll for it, and then the browser
    downloads it from statements-report-persistent-production.s3.amazonaws.com.
    The statements page is loaded afresh before every press, so a month
    asked for before cannot hand its download to this one's. Then
    `_catch_statement` presses the one button, through the core's
    press_once, and takes the download event only when it is the one
    download the press brought and its address is on that exact host. The
    saved PDF has to name its own month more plainly than the months on
    either side (statement_identity) before it is filed under that month.
    The "Last 30 days" row is a moving window, not a statement, and is
    skipped.
  * A tax form. The page's own list call, GET /v2/tax/forms?...&year=YYYY,
    returns each form with a short-lived link to its PDF on
    tax-center-forms-production.s3.amazonaws.com. `_collect_tax` reads the
    list for every year since the account's first transaction, and
    `_fetch_tax_pdf` asks the list again at download time and fetches the
    PDF from that exact host. Nothing is pressed, so the page's own
    mark-read / mark-downloaded calls, which its Download button makes, are
    never made. Pregenerated gain/loss reports (/v2/tax/tax-reports) are
    listed the same way, PDFs only.
  * A Coinbase One Card statement. The Statements page's "Credit Card"
    tab (data-testid subpage-navigation-item, text "Credit Card", no href
    on the survey) is pressed through the core on the statements page
    loaded by its address. It is pressed rather than opened by its address,
    /statements/credit-card, because the press is what the survey saw
    work, twice, and a load of that address was never tried. Opening it,
    the page itself POSTs graphql-direct/query and answers its list,
    viewer.creditCard.statements.edges, each with statementId and
    statementDate (the closing day). That answer is heard, never asked for,
    and its count and months have to match the rows the page draws, one
    "<Month YYYY>" row with one PDF button each. `_take_card_statement`
    then presses that row's PDF button, through press_once, hears the
    page's own CreditCardStatementRowQuery answer, whose request names the
    statementId the list gave that month, takes its statementUrl only on
    exactly statements.cardless.com with that closing date in its path
    (is_card_statement_url), waits for the tab to arrive there itself,
    fetches that exact address with the session and no redirect followed,
    and keeps it only as a PDF that says "Coinbase One Card" and prints the
    closing date. The tab then goes back to the list, and the list has to
    show again. The tab's own responses at that address are Chrome's PDF
    viewer, not the PDF, and are never read. A popup, a download, the tab
    arriving anywhere else, or an answer that names another statement or
    another date stops the run.

Session: www.coinbase.com and accounts.coinbase.com share a sign-in through
login.coinbase.com; `page.goto` to accounts.coinbase.com stays signed in.

SAFETY (this is a crypto exchange account that can move money):
  This module is strictly READ-ONLY. It must NEVER activate any control
  that buys, sells, trades, converts, swaps, sends, receives, withdraws,
  deposits, transfers, stakes, borrows, pays, creates an order, API key,
  address or custom statement, or edits any setting. The only controls
  this app presses are a statement row's own PDF button, the list's
  "Load more", the Statements page's "Credit Card" tab (is_card_tab) and a
  card statement row's own PDF button (is_card_pdf_label), each through
  its own guard first and then through the
  core (pressing.press_once and pressing.click), which presses nothing
  that something covers and stops the run instead. FORBIDDEN_CONTROL_RE is
  the guard; a control must ALSO look like a document action
  (SAFE_DOC_CONTROL_RE), and the shared core guards are consulted every
  time. A control whose label cannot be read is never clicked. The custom
  statement generator ("Generate") and the tax "Generate" report button are
  never touched. There is no code here that closes a banner, submits a form
  or confirms a dialog.

HOSTS: exact, no subdomain wildcard, and on accounts.coinbase.com only the
paths this app reads (ALLOWED_PATH_RE). A document is accepted from exactly
the two S3 hosts above (DOWNLOAD_HOSTS) and from nowhere else, and a card
statement from exactly statements.cardless.com and only at the address the
page itself was handed for it (is_card_statement_url), which is on neither
list. A presigned link is used once and never written anywhere. Discovery
keeps the form's opaque id and the API path only, and for a card statement
its title and closing date only. The card's account id, the statement's
id, its signed address and anything in it are never logged or kept.

KNOWN CEILINGS (ponytail: left as they are until a run shows otherwise)
  * The tax list's page cursor is sent as `cursor=`; next_cursor was empty on
    the account this was built on, so a non-empty one is untested.
  * A form is filed under the year it was asked for (year=). A form whose
    own year field names another year stops the listing.
  * The tax reports list is read as one page of up to 200. An answer that
    says there is another page, or fills the page, stops the listing.
  * The card list is the one answer the page asks for when its Credit Card
    tab opens. When that answer carries a pageInfo it has to say there is
    no next page, and when it carries none its months have to follow one
    another with no month missing. Whether the answer carries a pageInfo
    was not seen on the survey. Only one card account is read, and an
    answer naming more than one is a card list this cannot read.
  * An account whose Statements page shows no Credit Card tab lists no card
    statement. One whose tab answers no card (creditCard null, or no card
    account) lists none too. That reading of an account without a card is
    not surveyed.
  * A card list this cannot read whole leaves only the card statements,
    none of them listed (CardListUnread). The monthly statements and tax
    documents are listed and taken as usual, and the run ends as one that
    did not finish, so the card statements are asked for again next time.
  * "Last 30 days" is skipped by design, it is not a statement. A list
    showing it twice is a list this cannot read.
  * The statements list is called whole only when its oldest month is the
    month of the account's first transaction (owner-info's
    first_transaction_date) or an earlier one. A list that stops short of
    it, or an account whose owner-info names no first transaction, stops
    the listing.
"""
from __future__ import annotations

import json
import logging
import re
import sys
from dataclasses import dataclass
from datetime import date as _date
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import parse_qsl, urlsplit

from paperpull_core import pdf_reader
from paperpull_core import intake
from paperpull_core import pressing
from paperpull_core import redirects
from paperpull_core.controls import SETTINGS_CONTROL_RE, AUTH_CONTROL_RE
from paperpull_core.redact import redact, set_private_words  # noqa: F401  (re-exported)
from paperpull_core.urls import is_safe_url as _host_allows
from paperpull_core.api_census import shape_of as _shape
from paperpull_core.dates import last_day as _last_day
from paperpull_core.dates import checked as _checked_date
from paperpull_core.dates import full_year as _full_year
from paperpull_core.identity import Identity
# re-exported: the docs module calls it as site.set_download_dir
from paperpull_core.capture import set_download_dir  # noqa: F401
from paperpull_core.capture import snapshot as _snapshot
from paperpull_core.capture import take_download as _take_download
from paperpull_core.capture import clear_copies as _clear_copies
from paperpull_core.words import words_for as _words_for
from paperpull_core.characters import whole_characters, whole_json

log = logging.getLogger("coinbase_docs.site")


def _words():
    """This app's own words for paperpull_core.words."""
    return _words_for("Coinbase", sys.modules[__name__])


# ---------------------------------------------------------------------------
# Addresses
# ---------------------------------------------------------------------------
HOME = "https://www.coinbase.com"
BASE = "https://accounts.coinbase.com"
STATEMENTS_URL = f"{BASE}/statements"
TAX_URL = f"{BASE}/taxes/documents"
TAX_FORMS_API = f"{BASE}/v2/tax/forms"
TAX_REPORTS_API = f"{BASE}/v2/tax/tax-reports"
TAX_OWNER_API = f"{BASE}/v2/tax/owner-info"
# The Coinbase One Card's own statements, the Statements page's "Credit Card"
# tab. The app reaches it by pressing that tab, never by its address.
CARD_LIST_URL = f"{BASE}/statements/credit-card"
# Where the page asks for its card list and for a statement's address. The
# app only listens to the page's own answers here and never asks it itself.
GRAPHQL_URL = f"{BASE}/graphql-direct/query"
BILLING_URL = STATEMENTS_URL
URLS = {
    "home": f"{HOME}/",
    "login": f"{HOME}/",
    "documents": STATEMENTS_URL,
    "statements": STATEMENTS_URL,
    "tax": TAX_URL,
}

# The form types the page itself asks for.
TAX_FORM_TYPES = ("1042-S", "1099-K", "1099-B", "1099-MISC", "1099-DA")

LOGIN_URL_MARKERS = ["/signin", "/sign-in", "/login", "/oauth", "/2fa", "/mfa",
                     "/verify", "/verification", "/challenge", "/sso",
                     "//login.coinbase.com"]

# ---------------------------------------------------------------------------
# HARD SAFETY GUARD. Tuned for an exchange. Every verb stem anchored on both
# sides so "Statements" is not "state" and "Downloads" is not "load".
# ---------------------------------------------------------------------------
FORBIDDEN_CONTROL_RE = re.compile(
    r"(\bbuy\b|\bsell\b|\btrad(e|es|ed|ing)\b|\bconvert(s|ed|ing)?\b|\bswap(s|ped|ping)?\b|"
    r"\bsend\b|\breceive\b|\bwithdraw(al|als|s)?\b|\bdeposit(s|ed)?\b|\btransfer(s|red|ring)?\b|"
    r"\bstak(e|es|ed|ing)\b|\bunstak(e|es|ed|ing)\b|\bearn\b|\bborrow\b|\blend(ing)?\b|\bloan\b|"
    r"\bcard\b|\bpay\b|\bpayment(s)?\b|\brecurring\b|\border(s)?\b|\badvanced\b|\bwallet\b|"
    r"\baddress(es)?\b|\bwhitelist\b|\ballowlist\b|\bapi\b|\bkey(s)?\b|"
    r"\bgenerat(e|es|ed|ing)\b|\bcreat(e|es|ed|ing)\b|\bcustom\b|\brequest(s|ed|ing)?\b|"
    r"\bapprov(e|es|ed|ing|al)\b|\bcontinue\b|\bsubmit\b|\bconfirm\b|\bagree\b|\baccept\b|"
    r"\bauthori[sz]e\b|\bverify\b|\bidentity\b|\bpassword\b|\bpasskey\b|\b2fa\b|\bsecurity\b|"
    r"\bsettings?\b|\bprofile\b|\benabl(e|es|ed|ing)\b|\bdisabl(e|es|ed|ing)\b|"
    r"\bchang(e|es|ed|ing)\b|\bedit(s|ed|ing)?\b|\bupdat(e|es|ed|ing)\b|\bdelet(e|es|ed|ing)\b|"
    r"\bremov(e|es|ed|ing)\b|\bcancel\b|\bclose\b|\bexport\b|\bemail\b|\bshare\b|"
    r"\bsign\s*up\b|\bupgrade\b|\bsubscribe\b|\bone\b|\bchat\b|\bcontact\b|\bmark\b)", re.I)

SAFE_DOC_CONTROL_RE = re.compile(
    r"(\bdownload\b|\bview\b|\bopen\b|\bprint\b|\bpdf\b|\bstatements?\b|\bdocuments?\b|"
    r"\btax\b|\b1099\b|\bgain\b|\bloss\b|\breport\b|\bhistory\b|"
    r"see\s+(more|all|older)|show\s+(more|all|older)|load\s+more|"
    r"(next|previous|first|last)\s+page|go\s+to\s+(first|last)\s+page)", re.I)

# A control that fetches one document, for the survey.
BILL_CONTROL_RE = re.compile(r"(^\s*download\b|^\s*pdf\b|\b1099\b|gain.{0,6}loss)", re.I)

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

# Fallback selectors (used by --diagnose only).
FALLBACK = {
    "doc_row": "button[data-testid='statements-pdf-v2']",
    "doc_link": "a[data-testid='statements-taxform-link']",
    "download_control": "button[data-testid='statements-pdf-v2']",
    "page_ready": "button[data-testid='statements-pdf-v2'], main",
    "next_page": "button[data-testid='load-more']",
}

# ---------------------------------------------------------------------------
# Date parsing
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



_WORD_VALUE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_ -]{0,23}$")


def _plain_word(v: str) -> bool:
    return bool(_WORD_VALUE_RE.match(v or ""))


def _safe_query(url: str) -> str:
    """A URL's query parameters, names always, values only when they are
    plain words. A value with a digit, a token, an id, anything long, is
    "..."."""
    from urllib.parse import parse_qsl
    try:
        pairs = parse_qsl(urlsplit(url).query, keep_blank_values=True)
    except ValueError:
        return ""
    out = []
    for k, v in pairs[:20]:
        out.append("%s=%s" % (k[:30], v if _plain_word(v) else "..."))
    return "&".join(out)


# ---------------------------------------------------------------------------
# Session / safety
# ---------------------------------------------------------------------------

def looks_signed_out(page) -> bool:
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
    Visible text only. A page that shows a statement row is not a
    challenge, whatever its text says further down. A prompt drawn over the
    list is not missed for that, since every press goes through the core,
    which reads what is on top of the control and stops the run when
    something covers it (pressing.click, pressing.press_once)."""
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
    blocklist, then the shared core guards, and only then the document
    allowlist."""
    name = re.sub(r"\s+", " ", name or "").strip()
    if not name:
        return False
    if FORBIDDEN_CONTROL_RE.search(name):
        return False
    if SETTINGS_CONTROL_RE.search(name) or AUTH_CONTROL_RE.search(name):
        return False
    return bool(SAFE_DOC_CONTROL_RE.search(name))


# ---------------------------------------------------------------------------
# Hosts. Exact, parsed, no subdomain wildcard, and on the accounts host only
# the paths this app reads itself. Each is a fixed path with no part left
# open, so a path that climbs with ".." never matches one.
# ---------------------------------------------------------------------------
ALLOWED_HOSTS = {"accounts.coinbase.com", "www.coinbase.com"}
DOWNLOAD_HOSTS = {"statements-report-persistent-production.s3.amazonaws.com",
                  "tax-center-forms-production.s3.amazonaws.com"}
ALLOWED_PATH_RE = re.compile(
    r"^/(statements|taxes|taxes/documents|v2/tax/forms|v2/tax/tax-reports|"
    r"v2/tax/owner-info)/?$")


def is_safe_url(url: str) -> bool:
    """True only for an https URL on exactly one of this provider's hosts.
    Where this app itself asks for something, is_list_url holds the path to
    the list calls as well."""
    return _host_allows(url, ALLOWED_HOSTS, subdomains=False)


def is_list_url(url: str) -> bool:
    """is_safe_url, and on accounts.coinbase.com only a path this app reads
    itself: the two document pages and the tax list calls. Every GET this
    app makes goes through it, and redirects.get asks it about each hop."""
    if not is_safe_url(url):
        return False
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    if (parts.hostname or "").lower() == "accounts.coinbase.com":
        return bool(ALLOWED_PATH_RE.match(parts.path or ""))
    return (parts.path or "/").rstrip("/") in ("", "/home")


def is_download_url(url: str) -> bool:
    """True only for an https address on exactly one of the two hosts the
    site was seen handing documents from. Checked before any document is
    taken, whether the browser downloaded it or this app asked for it."""
    return _host_allows(url, DOWNLOAD_HOSTS, subdomains=False)


# ---------------------------------------------------------------------------
# Documents
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
    # The tax form's or report's own id, which a record is kept under, so a
    # second form of one year never changes the first's key.
    document_id: str = ""


class ListStopped(Exception):
    """The list has a part this could not read, so what was read is not all
    of it. `docs` holds what was read before it stopped."""

    def __init__(self, why: str, docs=None):
        super().__init__(why)
        self.docs = list(docs or [])


class CardListUnread(Exception):
    """The Coinbase One Card statements could not be read whole, so none of
    them is listed and they are left for the next run. Only that family is
    left. `docs` holds the monthly statements and tax documents the listing
    read, which a run still takes, and the listing is then not called
    whole."""

    def __init__(self, why: str, docs=None):
        super().__init__(why)
        self.docs = list(docs or [])


class SessionExpired(Exception):
    """Coinbase showed its sign-in page, by its address or a password field,
    where a page of its own was expected. The run stops for the account
    holder to sign in again."""


_PDF_BTN = "button[data-testid='statements-pdf-v2']"
# How long a statement's capture waits, once a download has come, for a
# second one. One press of one PDF button hands over one PDF, so a second
# download means one of the two is not this press's, and neither is taken.
SECOND_DOWNLOAD_WAIT_MS = 3000
_LOAD_MORE = "button[data-testid='load-more']"
_MAX_LOAD_MORE = 60
# How long the list is given before a Load more that is not there, or is
# turned off, is taken for the end of the list. It is looked for once, and
# once more after this, since a list still drawing a page can hide it for a
# moment.
LOAD_MORE_LOOK_AGAIN_MS = 1500
# How long the statements page is given to draw its month rows, once its
# first PDF button shows, when the account has months to show.
MONTH_ROWS_WAIT_MS = 10000
_MONTH_ROW_RE = re.compile(r"^(January|February|March|April|May|June|July|August|September|"
                           r"October|November|December) ((?:19|20)\d{2})$")
_STATEMENT_TITLE_RE = re.compile(r"^Monthly Statement ((?:January|February|March|April|May|June|"
                                 r"July|August|September|October|November|December) (?:19|20)\d{2})$")
_TAX_TITLE_RE = re.compile(r"^(.+?) Tax Year ((?:19|20)\d{2})(?: \(#([A-Za-z0-9]{1,40})\))?$")

# The label of the row one PDF button sits in, "September 2026" or "Last 30
# days", read from the page without pressing anything. The row is the
# nearest ancestor whose text starts with such a label. An ancestor holding
# a second PDF button is the list around the rows, not a row, and the label
# is "" there. A row whose own text did not start with its month used to
# climb to the list, which starts with "Last 30 days", and was skipped as
# that row.
_LABEL_OF_JS = r"""(b) => {
  let el = b;
  for (let k = 0; k < 8 && el; k++, el = el.parentElement) {
    if (el.querySelectorAll("button[data-testid='statements-pdf-v2']").length > 1) return '';
    const t = (el.innerText || '').trim();
    const m = t.match(/^(Last 30 days|[A-Z][a-z]+ (?:19|20)\d{2})(?!\S)/);
    if (m) return m[1];
  }
  return '';
}"""

# Each PDF button with the label of its row (_LABEL_OF_JS) and its own words.
_ROWS_JS = r"""() => {
  const labelOf = %s;
  return [...document.querySelectorAll("button[data-testid='statements-pdf-v2']")].map((b, i) => (
    {label: labelOf(b), button: (b.innerText || b.getAttribute('aria-label') || '').trim(), i: i}));
}""" % _LABEL_OF_JS


def month_to_iso(label: str) -> str:
    """"September 2026" -> "2026-09-30", the statement's own last day, or ""."""
    m = _MONTH_ROW_RE.match((label or "").strip())
    if not m:
        return ""
    year, month = int(m.group(2)), _MONTHS[m.group(1)[:3].lower()]
    return f"{year:04d}-{month:02d}-{_last_day(year, month):02d}"


def statement_identity(title: str):
    """What a monthly statement's own text is checked against, and the
    statements it could be taken for, as (mine, rivals) for
    identity.distinguish. Its month, its first day and its last day, the
    same three kinds of fact for every month, and as rivals the month
    before and the month after, the two a statement most often names beside
    its own, in an opening balance or the day it was made. None for a title
    that is not a monthly statement's."""
    m = _STATEMENT_TITLE_RE.match((title or "").strip())
    if not m:
        return None
    iso = month_to_iso(m.group(1))
    year, month = int(iso[:4]), int(iso[5:7])

    def of(y: int, mo: int) -> Identity:
        return Identity(period="%04d-%02d" % (y, mo), start="%04d-%02d-01" % (y, mo),
                        date="%04d-%02d-%02d" % (y, mo, _last_day(y, mo)), kind="statement")

    before = (year - 1, 12) if month == 1 else (year, month - 1)
    after = (year + 1, 1) if month == 12 else (year, month + 1)
    return of(year, month), (of(*before), of(*after))


def _read_rows(page) -> list:
    try:
        return page.evaluate(_ROWS_JS) or []
    except Exception:
        return []


def row_index_for(rows: list, label: str) -> Tuple[int, str]:
    """(index, button label) of the one PDF button whose row reads exactly
    `label`, or (-1, ""). Two rows with one label is a page this cannot
    read, and nothing is chosen."""
    hits = [r for r in rows if (r.get("label") or "") == label]
    if len(hits) != 1:
        return -1, ""
    return int(hits[0].get("i", -1)), hits[0].get("button") or ""


def _wait_for_list(page, timeout_ms: int = 30000) -> bool:
    try:
        page.wait_for_selector(_PDF_BTN, timeout=timeout_ms)
        return True
    except Exception:
        return False


def goto_documents(page) -> bool:
    """Open the statements page by its address. No click, no banner
    handling: a banner is for the account holder to close in the window."""
    here = page.url or ""
    if here.split("?")[0].rstrip("/") == STATEMENTS_URL and is_safe_url(here) \
            and not looks_signed_out(page) and _wait_for_list(page, 5000):
        return True
    return reload_statements(page)


def reload_statements(page) -> bool:
    """Load the statements page afresh by its address, whatever the tab
    shows already, and wait for its list. Done before every press of a
    statement's PDF button. A month pressed before may still be building
    and polling for its PDF in the page, and its download could then come
    during the next month's press and be taken for that month. The load
    ends that page and its polling."""
    try:
        page.goto(STATEMENTS_URL, wait_until="domcontentloaded", timeout=60000)
    except Exception as e:
        log.info("goto %s failed: %s", STATEMENTS_URL, e)
        return False
    if looks_signed_out(page):
        return False
    return _wait_for_list(page)


def scroll_full_page(page, rounds: int = 8, delay_ms: int = 600) -> None:
    try:
        for _ in range(rounds):
            page.mouse.wheel(0, 3000)
            page.wait_for_timeout(delay_ms)
        page.keyboard.press("End")
        page.wait_for_timeout(delay_ms)
    except Exception:
        pass


def _load_more_button(page):
    """The list's Load more when it shows and is turned on, or None once it
    has been looked for twice, LOAD_MORE_LOOK_AGAIN_MS apart, so a button
    the page hides or turns off for a moment while it draws is not taken for
    the end of the list. A button that could not be read raises
    ListStopped. Whether the list then reaches back far enough is
    _reaches_first_month's to say."""
    for look in (1, 2):
        try:
            btn = page.locator(_LOAD_MORE).first
            if btn.count() and btn.is_visible() and btn.is_enabled(timeout=1000):
                return btn
        except Exception as e:
            raise ListStopped("its Load more could not be read (%s)" % type(e).__name__)
        if look == 1:
            page.wait_for_timeout(LOAD_MORE_LOOK_AGAIN_MS)
    return None


def _press_load_more(page) -> bool:
    """Press the list's Load more once. False when there is none left,
    looked for twice (_load_more_button). Its own label goes through the
    guard first, and the press goes through the core, which presses
    nothing that something covers and stops the run instead
    (pressing.click). Pressed with the rows still the same after about ten
    seconds, or refused, raises ListStopped, since both used to read as the
    end of the list."""
    btn = _load_more_button(page)
    if btn is None:
        return False
    try:
        label = (btn.inner_text(timeout=1000) or btn.get_attribute("aria-label") or "")
    except Exception as e:
        raise ListStopped("its Load more could not be read (%s)" % type(e).__name__)
    if not is_safe_control(label):
        raise ListStopped("the guard refused its Load more button")
    before = page.locator(_PDF_BTN).count()
    pressing.click(page, btn, css=_LOAD_MORE, what="the Load more button of the statements list",
                   words=_words(), step="load more of the list")
    for _ in range(34):
        page.wait_for_timeout(300)
        if page.locator(_PDF_BTN).count() > before:
            return True
    raise ListStopped("the rows stayed the same after Load more was pressed")


def expand_all(page) -> None:
    """Load the whole list. The row count only ever grows."""
    for _ in range(_MAX_LOAD_MORE):
        if not _press_load_more(page):
            return
    raise ListStopped("it runs past %d presses of Load more" % _MAX_LOAD_MORE)


def _month_of(iso: str) -> Tuple[int, int]:
    return int(iso[:4]), int(iso[5:7])


def _has_months(first: str, today: _date) -> bool:
    """Whether an account whose first transaction was on `first` has a
    complete month by `today`, and so a statement to list."""
    return bool(first) and _month_of(first) < (today.year, today.month)


def _wait_for_months(page, timeout_ms: int = MONTH_ROWS_WAIT_MS) -> None:
    """Wait as long as `timeout_ms` for a row labeled with a month, since
    the list can show its "Last 30 days" row first. Whether the months
    then read reach back far enough is _reaches_first_month's to say."""
    waited = 0
    while waited < timeout_ms:
        if any(month_to_iso(r.get("label") or "") for r in _read_rows(page)):
            return
        page.wait_for_timeout(500)
        waited += 500


def _reaches_first_month(docs: List[RawDoc], first: str, today: _date) -> None:
    """Raise ListStopped unless the oldest month listed is the month of the
    account's first transaction, `first` (YYYY-MM-DD), or an earlier one.
    Every complete month since then has its statement, so a list that stops
    short of that month has lost every month past where it stopped, and one
    that lists no month at all has lost them all."""
    if not first:
        raise ListStopped("Coinbase did not say when the account's first transaction was, so "
                          "the statements list cannot be checked whole")
    if not _has_months(first, today):
        return
    if not docs:
        raise ListStopped("it lists no month, though the account's first transaction was "
                          "before this month")
    oldest = min(d.date_text for d in docs)
    if _month_of(oldest) > _month_of(first):
        raise ListStopped("its oldest month is %s, after the month of the account's first "
                          "transaction" % oldest[:7])


def _collect_statements(page, first: str, today: Optional[_date] = None) -> List[RawDoc]:
    """One RawDoc per complete month on the statements page, newest first.
    "Last 30 days" is a moving window and is skipped, once. The list has to
    reach back to the month of the account's first transaction, `first`
    (YYYY-MM-DD, from owner-info), or it is a list cut short
    (_reaches_first_month)."""
    today = today or _date.today()
    docs: List[RawDoc] = []
    seen = set()
    windows = 0
    try:
        if _has_months(first, today):
            _wait_for_months(page)
        expand_all(page)
        rows = _read_rows(page)
        if not rows:
            raise ListStopped("no statement rows could be read")
        for r in rows:
            label = r.get("label") or ""
            if not label:
                raise ListStopped("a statement row has no month label this can read")
            iso = month_to_iso(label)
            if not iso:
                if label == "Last 30 days":
                    windows += 1
                    if windows > 1:
                        raise ListStopped("two statement rows read Last 30 days")
                    continue
                raise ListStopped("a statement row reads %r, not a month" % label[:30])
            if iso in seen:
                raise ListStopped("two statement rows read %s" % label)
            seen.add(iso)
            docs.append(RawDoc(title=f"Monthly Statement {label}", date_text=iso,
                               text=f"Coinbase Monthly Statement {label}",
                               row_index=len(docs), kind="statement"))
        _reaches_first_month(docs, first, today)
    except ListStopped as stop:
        stop.docs = docs
        raise
    return docs


# -- tax forms, read from the list call the page itself makes ---------------

def _get_json(page, url: str):
    """GET an allowed address with the signed-in session, every redirect hop
    checked. The JSON, or None when the answer was not ok or not JSON."""
    if not is_list_url(url):
        raise RuntimeError("refusing to ask an address off the app's own list calls")
    resp = redirects.get(page.context.request, url, is_list_url, timeout=60000)
    if not resp.ok:
        log.warning("%s answered %s", redact(url.split("?")[0]), resp.status)
        return None
    try:
        # Never copied into the run past the limit (intake.json_of).
        return intake.json_of(resp)
    except Exception:
        return None


def _first_transaction(page) -> str:
    """The day of the account's first transaction, from owner-info, as
    YYYY-MM-DD, or "" when it names none."""
    data = _get_json(page, TAX_OWNER_API)
    first = str((data.get("first_transaction_date") if isinstance(data, dict) else "") or "")
    m = re.match(r"(?:19|20)\d{2}-(?:0[1-9]|1[0-2])-\d{2}", first)
    return m.group(0) if m else ""


def _first_tax_year(first: str) -> int:
    """The year of the account's first transaction, `first`, or 2012,
    Coinbase's own first year."""
    return int(first[:4]) if first else 2012


def _year_said(item: dict) -> str:
    """The year a listed form names for itself, or "" when it names none."""
    for name in ("tax_year", "year"):
        value = item.get(name)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def _tax_forms_for(page, year: int) -> list:
    """The forms the list call returns for `year`, every page of it. A form
    is filed under the year asked for, so one whose own year field names
    another year, or an answer that is not a list of forms, stops the
    listing."""
    types = "&".join("types=%s" % t for t in TAX_FORM_TYPES)
    url = f"{TAX_FORMS_API}?{types}&sort_direction=DESC&year={year}&is_hidden=false"
    items: list = []
    cursor = ""
    for _ in range(20):
        data = _get_json(page, url + ("&cursor=%s" % cursor if cursor else ""))
        if not isinstance(data, dict) or not isinstance(data.get("data"), list) \
                or not all(isinstance(it, dict) for it in data["data"]):
            raise ListStopped("the tax forms list for %d could not be read" % year)
        for it in data["data"]:
            said = _year_said(it)
            if said and said != str(year):
                raise ListStopped("the tax forms list for %d holds a form of another year" % year)
        items.extend(data["data"])
        nxt = str(data.get("next_cursor") or "")
        if not nxt:
            return items
        if nxt == cursor:
            raise ListStopped("the tax forms list for %d repeats a page cursor" % year)
        cursor = nxt
    raise ListStopped("the tax forms list for %d runs past 20 pages" % year)


# How many reports the list is asked for at once.
_REPORTS_LIMIT = 200


def _more_pages(data: dict) -> bool:
    """Whether a list's answer says it has another page, by a cursor of its
    own or one under pagination."""
    if str(data.get("next_cursor") or ""):
        return True
    more = data.get("pagination")
    return isinstance(more, dict) and any(
        str(more.get(name) or "") for name in ("next_cursor", "next_uri", "next_starting_after"))


def _tax_reports(page) -> list:
    """The pregenerated reports, PDFs only. One page of up to
    _REPORTS_LIMIT is read, so an answer that says there is another page,
    or fills this one, stops the listing rather than miss the rest."""
    url = (f"{TAX_REPORTS_API}?from_date=2012-01-01T00:00:00Z"
           f"&to_date={_date.today().year}-12-31T23:59:59Z&limit={_REPORTS_LIMIT}")
    data = _get_json(page, url)
    if not isinstance(data, dict) or not isinstance(data.get("data"), list) \
            or not all(isinstance(r, dict) for r in data["data"]):
        raise ListStopped("the tax reports list could not be read")
    if _more_pages(data) or len(data["data"]) >= _REPORTS_LIMIT:
        raise ListStopped("the tax reports list has more than the one page this reads")
    return [r for r in data["data"]
            if str((r.get("file") or {}).get("file_type") or "").lower() == "pdf"]


def _short(doc_id: str) -> str:
    """The id as a title suffix: its whole self, letters and digits only, so
    two ids never share a suffix."""
    return re.sub(r"[^A-Za-z0-9]", "", str(doc_id or ""))[:40]


# What a form the list names no form_type for is called, in its title and
# when the list is asked for it again.
_NO_FORM_TYPE = "Tax Form"


def _form_type(item: dict) -> str:
    return str(item.get("form_type") or "").strip() or _NO_FORM_TYPE


def _report_summary(name: str) -> str:
    """"PregeneratedGainLossPDF" -> "Gain Loss Report"."""
    n = re.sub(r"^Pregenerated", "", str(name or ""))
    n = re.sub(r"(PDF|CSV)$", "", n)
    n = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", n).strip()
    return (n + " Report") if n else "Tax Report"


def tax_rawdocs(forms_by_year: dict, reports: list) -> List[RawDoc]:
    """RawDocs for the forms and PDF reports, titled "<form> Tax Year YYYY",
    with a short id suffix only where one year has two of the same form,
    so a corrected form is not lost under the original's title. Each keeps
    its own id as document_id, which its record is kept under, so a second
    form of a year never changes the first's. href holds the API path and
    the opaque id only, never a link."""
    out: List[RawDoc] = []
    # A form or a report without an id of its own, or two sharing one, is a
    # list this cannot tell apart, and a report without a year one it cannot
    # date. Either stops the listing rather than being skipped or merged,
    # since a document skipped here would be called complete.
    ids: set = set()

    def _id_of(item, what: str) -> str:
        did = str(item.get("id") or "").strip()
        if not did:
            raise ListStopped("a tax %s lists no id" % what)
        if did in ids:
            raise ListStopped("two tax documents share one id")
        ids.add(did)
        return did

    counts: dict = {}
    for year, items in forms_by_year.items():
        for it in items:
            ft = _form_type(it)
            counts[(ft, year)] = counts.get((ft, year), 0) + 1
    for year, items in sorted(forms_by_year.items(), reverse=True):
        for it in items:
            ft = _form_type(it)
            did = _id_of(it, "form")
            title = f"{ft} Tax Year {year}"
            if counts[(ft, year)] > 1:
                title += f" (#{_short(did)})"
            out.append(RawDoc(title=title, date_text=f"{year}-12-31",
                              href=f"/v2/tax/forms/{did}",
                              text=f"Coinbase {title}", kind="tax", document_id=did))
    rcounts: dict = {}
    for r in reports:
        year = r.get("year") or r.get("timeframe_year")
        if not year:
            raise ListStopped("a tax report names no year")
        key = (_report_summary(r.get("name")), year)
        rcounts[key] = rcounts.get(key, 0) + 1
    for r in reports:
        year = r.get("year") or r.get("timeframe_year")
        did = _id_of(r, "report")
        summary = _report_summary(r.get("name"))
        title = f"{summary} Tax Year {year}"
        if rcounts[(summary, year)] > 1:
            title += f" (#{_short(did)})"
        out.append(RawDoc(title=title, date_text=f"{year}-12-31",
                          href=f"/v2/tax/tax-reports/{did}",
                          text=f"Coinbase {title}", kind="tax", document_id=did))
    return out


def _collect_tax(page, first: str) -> List[RawDoc]:
    """Every tax form and pregenerated PDF report, from the list calls, for
    every year since the first transaction, `first`. A year that cannot be
    read raises ListStopped, never an empty year."""
    this_year = _date.today().year
    forms = {}
    for year in range(_first_tax_year(first), this_year + 1):
        forms[year] = _tax_forms_for(page, year)
    return tax_rawdocs(forms, _tax_reports(page))


def shown_documents(page) -> List[RawDoc]:
    """What Diagnose recognizes, with nothing pressed. Every statement row
    the page shows as it stands, Load more left alone, so only the rows
    already shown, and every tax document the Taxes page's own list calls
    name. A tax list that stops partway gives what was read before it."""
    docs: List[RawDoc] = []
    for r in _read_rows(page):
        label = r.get("label") or ""
        iso = month_to_iso(label)
        if iso:
            docs.append(RawDoc(title=f"Monthly Statement {label}", date_text=iso,
                               row_index=len(docs), kind="statement"))
    try:
        docs.extend(_collect_tax(page, _first_transaction(page)))
    except ListStopped as stop:
        docs.extend(stop.docs)
    return docs


def collect_download_docs(page) -> List[RawDoc]:
    """Every monthly statement, every tax document and every Coinbase One
    Card statement. Nothing is pressed except Load more and the Credit Card
    tab. A statements list that stopped partway still has the others read,
    and then raises ListStopped holding everything. A card list that cannot
    be read whole leaves only the card statements, none of them listed, and
    raises CardListUnread holding the monthly statements and tax documents,
    which a run still takes."""
    docs: List[RawDoc] = []
    stopped = None
    unread = None
    if not goto_documents(page):
        raise ListStopped("the statements page did not open")
    first = _first_transaction(page)
    try:
        docs.extend(_collect_statements(page, first))
    except ListStopped as stop:
        docs.extend(stop.docs)
        stopped = stop
    try:
        docs.extend(_collect_tax(page, first))
    except ListStopped as stop:
        stop.docs = docs
        raise
    try:
        docs.extend(_collect_card(page))
    except CardListUnread as card:
        unread = card
    if stopped is not None:
        stopped.docs = docs
        raise stopped
    if unread is not None:
        unread.docs = docs
        raise unread
    return docs


# -- downloads --------------------------------------------------------------

def _pdf_url_of(item: dict) -> str:
    files = item.get("files")
    if isinstance(files, list):
        for f in files:
            if str((f or {}).get("file_type") or "").lower() == "pdf":
                return str(f.get("url") or "")
    f = item.get("file")
    if isinstance(f, dict) and str(f.get("file_type") or "").lower() == "pdf":
        return str(f.get("url") or "")
    return ""


def _fetch_tax_pdf(page, title: str, out_path: Path, trace: Optional[list],
                   document_id: str = "") -> bool:
    """Ask the list again for the document titled `title`, with the id
    `document_id` when its record keeps one, then fetch its PDF from its
    short-lived link, only when that link is on an exact download host. The
    link is used once and written nowhere. A list that cannot be read again
    raises ListStopped, since every tax document after this one asks the
    same list."""
    m = _TAX_TITLE_RE.match((title or "").strip())
    if not m:
        return False
    summary, year, short = m.group(1), int(m.group(2)), m.group(3) or ""
    try:
        if summary.endswith(" Report"):
            items = [r for r in _tax_reports(page) if int(r.get("year") or r.get("timeframe_year") or 0) == year
                     and _report_summary(r.get("name")) == summary]
        else:
            items = [it for it in _tax_forms_for(page, year) if _form_type(it) == summary]
        # The id the record keeps names the one document, and failing that
        # the suffix, when the title carries one. Without either the title
        # has to name exactly one by itself.
        if document_id:
            items = [it for it in items if str(it.get("id") or "").strip() == document_id]
        elif short:
            items = [it for it in items if _short(it.get("id")) == short]
        elif len(items) > 1:
            items = []
    except ListStopped as stop:
        log.info("could not read the list for %s: %s", title, stop)
        raise
    if len(items) != 1:
        log.info("no single listed document matches %r (%d)", title, len(items))
        if trace is not None:
            trace.append({"note": "the list did not name this document once", "matches": len(items)})
        return False
    url = _pdf_url_of(items[0])
    host = urlsplit(url).hostname or ""
    if not is_download_url(url):
        log.info("refusing a document link on host %r", host)
        if trace is not None:
            trace.append({"note": "document link refused", "host": host})
        return False
    try:
        resp = page.context.request.get(url, max_redirects=0, timeout=60000)
    except Exception as e:
        if trace is not None:
            trace.append({"note": "fetch failed", "host": host, "error": str(e)[:160]})
        return False
    if trace is not None:
        trace.append({"note": "fetched", "host": host, "status": resp.status})
    try:
        body = intake.body(resp) if resp.ok else b""
    except intake.TooLarge:
        return False
    if body[:5] != b"%PDF-":
        return False
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(body)
    return True


def _cancel_all(downloads: list) -> None:
    for dl in downloads:
        try:
            dl.cancel()
        except Exception:
            pass


def _catch_statement(page, dl_dir, label: str, out_path: Path, trace: Optional[list]) -> bool:
    """Press the PDF button of the row that reads `label`, once, and take
    the download the browser then makes, only when it is the one download
    that came, none came before the press, and it comes from an exact
    download host. A file that lands with no event, or from any other
    host, is not taken. A list that cannot be read, or stops while it loads
    more, raises ListStopped, since every statement after this one reads
    the same list."""
    rows = _read_rows(page)
    idx, btn_label = row_index_for(rows, label)
    try:
        # Load more only while the month is not on the page yet; the list
        # is newest first, so an older month needs more presses, a recent
        # one none.
        for _ in range(_MAX_LOAD_MORE):
            if idx >= 0 or not _press_load_more(page):
                break
            rows = _read_rows(page)
            idx, btn_label = row_index_for(rows, label)
    except ListStopped as stop:
        log.info("the list stopped while looking for %s: %s", label, stop)
        raise
    if idx < 0:
        if trace is not None:
            trace.append({"note": "no single row reads this label", "rows": len(rows)})
        return False
    if not is_safe_control(btn_label):
        log.info("refusing unsafe control %r for %s", btn_label, label)
        return False
    # The one button, held as an element from here on, so every read and the
    # press reach that button and no other, even should the list be drawn
    # anew in between (pressing.press_once).
    try:
        el = page.locator(_PDF_BTN).nth(idx).element_handle(timeout=3000)
    except Exception:
        el = None
    if el is None:
        if trace is not None:
            trace.append({"note": "the PDF button could not be read"})
        return False

    def row_changed() -> str:
        """press_once's own check, "" while the button's row still reads
        `label`, and otherwise why it is not the button that was chosen."""
        try:
            now = el.evaluate(_LABEL_OF_JS)
        except Exception:
            return "its row could not be read"
        return "" if now == label else "its row reads another month"

    downloads: list = []
    def on_download(dl):
        # A plain function: Playwright tags the handler it is given, which a
        # bound builtin cannot carry, and one object so remove_listener finds it.
        downloads.append(dl)
    page.on("download", on_download)
    before = _snapshot(dl_dir)
    try:
        # The row is read again at the press, not only when the button was
        # found.
        if row_changed():
            if trace is not None:
                trace.append({"note": "the PDF button's row reads another month now"})
            return False
        # A download that came before the press is not this press's, and
        # with one on its way nothing is pressed.
        if downloads:
            _cancel_all(downloads)
            if trace is not None:
                trace.append({"note": "a download came before the press, so nothing was pressed",
                              "downloads": len(downloads)})
            return False
        # Playwright's own press, and through the page only when nothing
        # covered the button, its press never reached the page, nothing it
        # should bring came and its row still reads this month. Something
        # over the button stops the run, and the button is never pressed
        # twice (pressing.press_once).
        try:
            outcome = pressing.press_once(
                page, el, what="the PDF button of this month's statement", words=_words(),
                guard=is_safe_control, check=row_changed, dl_dir=dl_dir,
                brought=lambda: bool(downloads))
        except pressing.TurnedOff:
            # The page has turned the button off, so nothing was pressed and
            # nothing this statement brings can come. It is left for review
            # and the next run while the run goes on (pressing.TurnedOff).
            if trace is not None:
                trace.append({"note": "the PDF button is turned off on the page, so nothing was pressed"})
            return False
        if trace is not None:
            if outcome.error is None:
                trace.append({"note": "clicked", "control": redact(btn_label)[:40]})
            else:
                trace.append({"note": "click failed", "control": redact(btn_label)[:40],
                              "error": str(outcome.error)[:160]})
            if outcome.how == pressing.MADE:
                trace.append({"note": "the press reached the page although it raised, "
                                      "so it was not made again"})
            elif outcome.how == pressing.THROUGH_THE_PAGE and outcome.page_error is None:
                trace.append({"note": "clicked through the DOM instead"})
            elif outcome.how == pressing.THROUGH_THE_PAGE:
                trace.append({"note": "DOM click failed too", "error": str(outcome.page_error)[:160]})
        if outcome.how == pressing.GONE:
            # Nothing was pressed, so nothing this statement brings can come.
            if trace is not None:
                trace.append({"note": "the PDF button left the page before it was pressed"})
            return False
        # The page asks Coinbase to build the month's PDF and polls for it;
        # measured at well under a minute.
        for _ in range(120):
            if downloads:
                break
            page.wait_for_timeout(1000)
        if not downloads:
            if trace is not None:
                trace.append({"note": "no download in two minutes"})
            return False
        # One press brings one PDF. A second download means one of them
        # belongs to an earlier press, and which cannot be told, so neither
        # is taken and the statement is left for review and the next run.
        page.wait_for_timeout(SECOND_DOWNLOAD_WAIT_MS)
        if len(downloads) > 1:
            _cancel_all(downloads)
            if trace is not None:
                trace.append({"note": "more than one download came after one press, so none was taken",
                              "downloads": len(downloads)})
            return False
        dl = downloads[0]
        host = urlsplit(dl.url or "").hostname or ""
        if not is_download_url(dl.url or ""):
            log.info("refusing a download from host %r", host)
            if trace is not None:
                trace.append({"note": "download refused", "host": host})
            try:
                dl.cancel()
            except Exception:
                pass
            return False
        how = _take_event(dl, dl_dir, before, out_path)
        if trace is not None:
            trace.append({"note": "download taken" if how else "download not taken", "host": host, "how": how})
        return bool(how)
    finally:
        try:
            page.remove_listener("download", on_download)
        except Exception:
            pass
        try:
            _clear_copies(dl_dir, before, out_path)
        except Exception:
            pass
        try:
            el.dispose()
        except Exception:
            pass


def _take_event(dl, dl_dir, before, out_path: Path) -> str:
    """The download whose address passed is_download_url, saved through the
    core: the event's own file when the browser gives one, else the file
    the browser wrote into the folder it was pointed at, taken only when the
    folder can say it is this download's (capture.take_download). Says
    "event" or "folder", or "" when neither held a PDF. The document is
    never asked for a second time. Whatever copy the browser left in the
    folder, an exact one of what was saved, goes (capture.clear_copies)."""
    how = _take_download(dl, dl_dir, before, out_path)
    try:
        _clear_copies(dl_dir, before, out_path)
    except Exception:
        pass
    return how


def download_bill(page, dl_dir, iso_date: str, out_path, title: str = "",
                  trace: Optional[list] = None, document_id: str = "") -> bool:
    """Save the document titled `title`, dated `iso_date`. A tax document is
    fetched from its listed link, nothing pressed. A monthly statement is
    taken by loading the statements page afresh, pressing its row's own PDF
    button once and catching the download, which is how the site hands one
    over. Whether the PDF names its own month is the caller's to check
    (statement_identity). A Coinbase One Card statement is taken on the
    statements page loaded afresh, through its Credit Card tab and its row's
    own PDF button (_take_card_statement), which checks the PDF itself.
    A statements page that will not open, or a list that cannot be read
    again, raises ListStopped, since every document after this one reads
    the same page."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    t = (title or "").strip()
    if _TAX_TITLE_RE.match(t):
        return _fetch_tax_pdf(page, t, out_path, trace, document_id)
    c = _CARD_TITLE_RE.match(t)
    if c:
        if _checked_date(iso_date, None) != iso_date or _card_label(iso_date) != c.group(1):
            log.info("title %r and date %s disagree", t, iso_date)
            return False
        # Afresh, as for a monthly statement, and the card list heard anew.
        if not load_statements_for_card(page):
            if looks_signed_out(page):
                raise SessionExpired("the statements page answered as signed out")
            raise ListStopped("the statements page did not open")
        return _take_card_statement(page, c.group(1), iso_date, out_path, trace)
    m = _STATEMENT_TITLE_RE.match(t)
    if not m:
        log.info("not a title this app knows how to fetch: %r", t)
        return False
    if month_to_iso(m.group(1)) != iso_date:
        log.info("title %r and date %s disagree", t, iso_date)
        return False
    # Afresh before every press, so no earlier month's page is still
    # polling for its PDF (reload_statements).
    if not reload_statements(page):
        if looks_signed_out(page):
            raise SessionExpired("the statements page answered as signed out")
        raise ListStopped("the statements page did not open")
    return _catch_statement(page, dl_dir, m.group(1), out_path, trace)


# ---------------------------------------------------------------------------
# Coinbase One Card statements
# ---------------------------------------------------------------------------

CARD_STATEMENT_HOST = "statements.cardless.com"
# The signing keys the statement's address carries, each once (a CloudFront signed URL).
CARD_SIGNED_KEYS = ("Expires", "Signature", "Key-Pair-Id")
# The Statements page's two sub-navigation links are "Transactions" and
# "Credit Card". Only the second is ever pressed (is_card_tab).
CARD_LINK_CSS = "a[data-testid='subpage-navigation-item']"
CARD_LINK_TEXT = "Credit Card"
CARD_ROW_QUERY = "CreditCardStatementRowQuery"
# How long the card list is given to be heard and drawn once its tab is
# pressed, and how long an account whose tab answers no card is watched
# before that is believed.
CARD_LIST_WAIT_MS = 20000
CARD_NONE_WAIT_MS = 3000
# How long a press of a card row's PDF button is given for the page's
# answer and for the tab to arrive at the address it names.
CARD_LAND_WAIT_MS = 30000
# How long the list is given to show again once the tab has gone back.
CARD_BACK_WAIT_MS = 10000
_CARD_TITLE_RE = re.compile(r"^Coinbase One Card Statement ((?:January|February|March|April|May|"
                            r"June|July|August|September|October|November|December) (?:19|20)\d{2})$")
_CARD_PDF_PATH_RE = re.compile(r"/[A-Za-z0-9._~-]+_(\d{4}-\d{2}-\d{2})_Coinbase\.pdf")
_MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August",
                "September", "October", "November", "December"]
# The icon glyphs Coinbase draws in a button, from Unicode's private use
# areas, which a label is read without.
_GLYPHS_RE = re.compile("[\\s-\U000f0000-\U000ffffd\U00100000-\U0010fffd]")

# Whether a button is a card row's PDF button, a BUTTON that is not the
# Transactions tab's own PDF button, whose text is an icon and "PDF". The
# same reading as is_card_pdf_label.
_IS_CARD_PDF_JS = r"""(x) => x && x.tagName === 'BUTTON'
    && x.getAttribute('data-testid') !== 'statements-pdf-v2'
    && (x.innerText || '').replace(/[\s\u{E000}-\u{F8FF}\u{F0000}-\u{FFFFD}\u{100000}-\u{10FFFD}]/gu, '') === 'PDF'"""

# The month a card row's PDF button sits in, "September 2026", read upward
# from the button like _LABEL_OF_JS. An ancestor holding a second card PDF
# button is the list around the rows, and the label is "" there, so a row
# whose own text does not start with its month never reads as the first
# row's.
_CARD_LABEL_OF_JS = r"""(b) => {
  const isCard = %s;
  let el = b;
  for (let k = 0; k < 8 && el; k++, el = el.parentElement) {
    if ([...el.querySelectorAll('button')].filter(isCard).length > 1) return '';
    const t = (el.innerText || '').trim();
    const m = t.match(/^([A-Z][a-z]+ (?:19|20)\d{2})(?!\S)/);
    if (m) return m[1];
  }
  return '';
}""" % _IS_CARD_PDF_JS

# Each card PDF button with its row's month, its own words and its place
# among the page's buttons, which is how it is found again to be pressed.
_CARD_ROWS_JS = r"""() => {
  const isCard = %s;
  const labelOf = %s;
  return [...document.querySelectorAll('button')].map((b, i) => [b, i])
    .filter(([b]) => isCard(b))
    .map(([b, i]) => ({label: labelOf(b), button: (b.innerText || '').trim(), i: i}));
}""" % (_IS_CARD_PDF_JS, _CARD_LABEL_OF_JS)


def _no_fragment(url) -> str:
    return str(url or "").split("#", 1)[0]


def is_card_tab(text: str, href) -> bool:
    """The Statements page's own Credit Card tab, its text exactly "Credit
    Card" and no address or exactly the card list's. A "Credit Card" link
    with any other address, the product page's /creditcard say, is not it.
    Its words are never put to is_safe_control, which refuses "card" for
    every other control and goes on doing so."""
    if re.sub(r"\s+", " ", text or "").strip() != CARD_LINK_TEXT:
        return False
    if href in (None, ""):
        return True
    return str(href).strip() in ("/statements/credit-card", CARD_LIST_URL)


def is_card_pdf_label(name: str) -> bool:
    """A card statement row's PDF button, read by its words, an icon and
    "PDF" and nothing else, with the guard's own verdict on them too."""
    if not name or not is_safe_control(name):
        return False
    return _GLYPHS_RE.sub("", name) == "PDF"


def is_card_statement_url(url, iso: str) -> bool:
    """The one address a card statement is taken from, https on exactly
    statements.cardless.com, no port and no user, a path of one token, the
    statement's own closing date `iso` and "_Coinbase.pdf". It is applied
    to the address the page itself was handed for the statement it pressed,
    so this host is on none of the app's own host lists."""
    if not url or not iso or not _host_allows(url, {CARD_STATEMENT_HOST}, subdomains=False):
        return False
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return False
    if port is not None or parts.username or parts.password or "@" in parts.netloc:
        return False
    if parts.netloc.lower() != CARD_STATEMENT_HOST or parts.fragment or ("?" in url and not parts.query):
        return False
    # The address is signed, so its query is exactly the three signing
    # keys, each once with a value, or (for a bare address) nothing at all.
    try:
        pairs = parse_qsl(parts.query, keep_blank_values=True, strict_parsing=bool(parts.query))
    except ValueError:
        return False
    if pairs and (sorted(k for k, _v in pairs) != sorted(CARD_SIGNED_KEYS) or any(not v for _k, v in pairs)):
        return False
    m = _CARD_PDF_PATH_RE.fullmatch(parts.path or "")
    return bool(m) and m.group(1) == iso


def closing_date_re(iso: str):
    """How a card statement prints its closing day `iso`, "Sep 4, 2031",
    and the same with the month written out or as "Sept"."""
    year, month, day = int(iso[:4]), int(iso[5:7]), int(iso[8:10])
    full = _MONTH_NAMES[month - 1]
    names = {full, full[:3]} | ({"Sept"} if month == 9 else set())
    return re.compile(r"\b(?:%s)\.?\s+0?%d,?\s+%d\b"
                      % ("|".join(sorted(names, key=len, reverse=True)), day, year))


def _card_label(iso: str) -> str:
    """"2031-09-04" -> "September 2031", the month its row reads."""
    return "%s %s" % (_MONTH_NAMES[int(iso[5:7]) - 1], iso[:4])


def _is_graphql(url) -> bool:
    try:
        parts = urlsplit(url or "")
        return (parts.scheme == "https" and (parts.hostname or "") == "accounts.coinbase.com"
                and parts.port is None and parts.path == "/graphql-direct/query")
    except ValueError:
        return False


def _listen(page) -> Tuple[list, object]:
    """A response listener for the page's own graphql-direct answers, GET
    persisted queries and POSTs alike, and what it hears. Each answer is
    read as it comes, inside the listener,
    because the press of a card PDF button sends the tab on at once and a
    navigation takes the bodies with it. Kept for each are the operation
    the request names, the statementId its variables name, the status and
    the answer, None when it could not be read. Nothing of it is logged."""
    heard: list = []

    def on_response(res):
        try:
            method = res.request.method
            if not _is_graphql(res.url) or method not in ("POST", "GET"):
                return
        except Exception:
            return
        entry = {"op": "", "statement_id": "", "status": 0, "body": None}
        try:
            entry["status"] = int(res.status or 0)
        except Exception:
            pass
        try:
            # The page sends each query first as a GET persisted query (its
            # name and variables in the address) and again as a POST with
            # the full query when the server does not know the hash. Live,
            # a repeat visit is answered by the GET alone, so both are heard.
            sent = whole_json(res.request.post_data_json) if method == "POST" else _sent_in_address(res.url)
            if isinstance(sent, dict):
                entry["op"] = str(sent.get("operationName") or "")
                variables = sent.get("variables")
                if isinstance(variables, dict):
                    entry["statement_id"] = str(variables.get("statementId") or "")
        except Exception:
            pass
        try:
            entry["body"] = whole_json(res.json())
        except Exception:
            entry["body"] = None
        if method == "GET" and entry["status"] == 200 and _is_hash_miss(entry["body"]):
            # Not an answer. The server did not know the hash (said with a
            # 200, as live), and the page asks again by POST. Hearing it as
            # an error would stop a list the POST then answers whole. The
            # same words on any other status are heard as the error they are.
            return
        heard.append(entry)
    return heard, on_response


def _no_duplicate_keys(pairs):
    """json.loads hook that refuses an object naming a key twice, so a
    second statementId cannot hide behind the first."""
    out: dict = {}
    for k, v in pairs:
        if k in out:
            raise ValueError("duplicate key")
        out[k] = v
    return out


def _sent_in_address(url) -> Optional[dict]:
    """What a GET persisted query names in its address, operationName and
    variables (a JSON object), or None when the address cannot be read, or
    names operationName or variables more than once, or its JSON names a
    key twice. An ambiguous address is no answer at all."""
    try:
        pairs = parse_qsl(urlsplit(url or "").query, keep_blank_values=True)
    except ValueError:
        return None
    keys = [k for k, _v in pairs]
    if keys.count("operationName") > 1 or keys.count("variables") > 1:
        return None
    query = dict(pairs)
    sent: dict = {"operationName": query.get("operationName") or ""}
    if "variables" in query:
        try:
            variables = whole_json(json.loads(query["variables"], object_pairs_hook=_no_duplicate_keys))
        except ValueError:
            return None
        sent["variables"] = variables if isinstance(variables, dict) else {}
    return sent


def _is_hash_miss(body) -> bool:
    """True for the answer that only says the persisted query's hash is
    unknown, every error coded PERSISTED_QUERY_NOT_FOUND and no data."""
    if not isinstance(body, dict) or body.get("data") is not None:
        return False
    errors = body.get("errors")
    if not isinstance(errors, list) or not errors:
        return False
    return all(isinstance(e, dict) and isinstance(e.get("extensions"), dict)
               and e["extensions"].get("code") == "PERSISTED_QUERY_NOT_FOUND" for e in errors)


def _clean(entry: dict) -> bool:
    """An answer heard whole, status 200, a JSON object and no errors."""
    body = entry.get("body")
    return entry.get("status") == 200 and isinstance(body, dict) and not body.get("errors")


def _card_of(body):
    """viewer.creditCard of an answer, or None when the answer has none."""
    try:
        return body["data"]["viewer"]["creditCard"]
    except (KeyError, TypeError):
        return None


def _has_no_card(body) -> bool:
    """An answer that says this account has no card, creditCard null or a
    list of card accounts that is empty."""
    try:
        viewer = body["data"]["viewer"]
    except (KeyError, TypeError):
        return False
    if not isinstance(viewer, dict) or "creditCard" not in viewer:
        return False
    card = viewer["creditCard"]
    return card is None or (isinstance(card, dict) and card.get("accounts") == [])


def _card_accounts(body) -> int:
    """How many card accounts an answer names, 0 when it names no list of
    them."""
    card = _card_of(body)
    accounts = card.get("accounts") if isinstance(card, dict) else None
    return len(accounts) if isinstance(accounts, list) else 0


def _statements_of(body):
    """The `statements` object of a card list answer, or None for an answer
    that is not one."""
    card = _card_of(body)
    if isinstance(card, dict) and isinstance(card.get("statements"), dict) \
            and "edges" in card["statements"]:
        return card["statements"]
    return None


def _months_follow(dates: List[str]) -> bool:
    months = sorted({(int(d[:4]), int(d[5:7])) for d in dates})
    for (y1, m1), (y2, m2) in zip(months, months[1:]):
        if (y2 * 12 + m2) - (y1 * 12 + m1) != 1:
            return False
    return True


def _card_edges(entry: dict) -> List[Tuple[str, str]]:
    """(statementId, closing day) of every statement a card list answer
    names, or ListStopped when any of it cannot be read whole. The ids stay
    in memory, never in a record or a log."""
    if entry.get("status") != 200 or not isinstance(entry.get("body"), dict) \
            or entry["body"].get("errors"):
        raise ListStopped("the page's own list of card statements came back with an error")
    statements = _statements_of(entry["body"])
    edges = statements.get("edges") if statements else None
    if not isinstance(edges, list):
        raise ListStopped("the page's own list of card statements could not be read")
    out: List[Tuple[str, str]] = []
    for e in edges:
        node = e.get("node") if isinstance(e, dict) else None
        sid = node.get("statementId") if isinstance(node, dict) else None
        when = node.get("statementDate") if isinstance(node, dict) else None
        m = re.match(r"((?:19|20)\d{2}-\d{2}-\d{2})T", when) if isinstance(when, str) else None
        if not isinstance(sid, str) or not sid.strip() or not m \
                or _checked_date(m.group(1), None) != m.group(1):
            raise ListStopped("a card statement in the page's own list could not be read")
        out.append((sid, m.group(1)))
    if len({d for _s, d in out}) != len(out) or len({_card_label(d) for _s, d in out}) != len(out):
        raise ListStopped("two card statements in the page's own list share a month")
    if len({s for s, _d in out}) != len(out):
        raise ListStopped("two card statements in the page's own list share an id")
    more = statements.get("pageInfo")
    if more is not None:
        if not isinstance(more, dict) or more.get("hasNextPage") is not False:
            raise ListStopped("the page's own list of card statements has a page this does not read")
    elif not _months_follow([d for _s, d in out]):
        raise ListStopped("the page's own list of card statements skips a month and says "
                          "nothing of another page")
    return out


@dataclass
class CardList:
    """The card list the page answered and drew, matched row for row."""
    edges: List[Tuple[str, str]]
    rows: list


def _card_rows(page) -> list:
    try:
        return page.evaluate(_CARD_ROWS_JS) or []
    except Exception:
        return []


_CARD_TAB_TEXT_RE = re.compile(r"^\s*Credit\s+Card\s*$")


def _card_tab(page):
    """The Statements page's own Credit Card tab, as (locator, selector),
    or None when the page shows none. Looked for only on the statements
    page itself. Found by its text and its address (is_card_tab), then
    found again for the press by a selector only a link with that address
    fits and by its exact text, which Playwright holds it to at the press
    itself, so a link drawn anew in between is never the one pressed. Two
    that are, or one that cannot be read, stops the list."""
    if _no_fragment(page.url).rstrip("/") != STATEMENTS_URL:
        raise ListStopped("the statements page is not open, so its Credit Card tab is not looked for")
    try:
        links = page.locator(CARD_LINK_CSS)
        found = []
        for i in range(links.count()):
            link = links.nth(i)
            href = link.get_attribute("href")
            if is_card_tab(link.inner_text(timeout=2000), href):
                found.append(href)
        if len(found) > 1:
            raise ListStopped("the statements page shows two Credit Card tabs")
        if not found:
            return None
        href = found[0]
        css = CARD_LINK_CSS + (":not([href])" if href is None else "[href='%s']" % href)
        tab = page.locator(css).filter(has_text=_CARD_TAB_TEXT_RE)
        if tab.count() != 1 or not is_card_tab(tab.inner_text(timeout=2000),
                                               tab.get_attribute("href")):
            raise ListStopped("the statements page's Credit Card tab could not be found alone")
    except ListStopped:
        raise
    except Exception as e:
        raise ListStopped("the statements page's sub-navigation could not be read (%s)"
                          % type(e).__name__)
    return tab, css


def _left_the_list(step: str, why: str) -> pressing.Stop:
    """The run's stop for a press that took the tab somewhere it should
    not have gone or brought something it should not have."""
    return pressing.Stop(step, why, [
        "Coinbase answered a press of a card statement control in a way this app does "
        "not expect (%s), so the run stops here." % why,
        "Nothing more is pressed. Look at the browser window, then run this again."],
        after_a_press=True)


def _list_changed(step: str, why: str) -> pressing.Stop:
    """The run's stop for a card list that, read again for one statement,
    is not the list discovery read whole. Nothing was pressed for it. It
    leaves the list unread, so the panel offers a run that reads it afresh
    rather than Continue, which would read the same list again (#124)."""
    return pressing.Stop(step, why, [
        "The list of card statements changed since it was read (%s), so the run stops "
        "here rather than leave this statement and go on to the next." % why,
        "Nothing was pressed for it."], list_unread=True)


def open_card_list(page) -> Optional[CardList]:
    """Press the Statements page's Credit Card tab, hear the page's own
    list of card statements, and match it to the rows it draws. None when
    the page shows no Credit Card tab, or its answer says the account has
    no card. A list that cannot be read whole, or that names more than one
    card account, raises ListStopped. A tab that took the page to the
    sign-in page raises SessionExpired, and one that took it anywhere else
    but the card list stops the run."""
    found_tab = _card_tab(page)
    if found_tab is None:
        return None
    tab, css = found_tab
    heard, on_response = _listen(page)
    page.on("response", on_response)
    rows: list = []
    try:
        pressing.click(page, tab, css=css, what="the Credit Card tab of the statements page",
                       words=_words(), step="open the credit card statements")
        waited = 0
        while True:
            here = _no_fragment(page.url)
            if here != CARD_LIST_URL and not here.startswith(STATEMENTS_URL):
                break
            lists = [h for h in heard if _statements_of(h["body"]) is not None]
            rows = _card_rows(page) if here == CARD_LIST_URL else []
            if here == CARD_LIST_URL and lists:
                try:
                    want = len(_statements_of(lists[0]["body"]).get("edges") or [])
                except Exception:
                    want = -1
                if len(rows) == want and all(month_to_iso(r.get("label") or "") for r in rows):
                    break
            if here == CARD_LIST_URL and not lists and not rows and waited >= CARD_NONE_WAIT_MS \
                    and any(_has_no_card(h["body"]) for h in heard):
                break
            if waited >= CARD_LIST_WAIT_MS:
                break
            page.wait_for_timeout(500)
            waited += 500
    finally:
        try:
            page.remove_listener("response", on_response)
        except Exception:
            pass
    if _no_fragment(page.url) != CARD_LIST_URL:
        # A tab that went to the sign-in page was signed out, and that is the
        # account holder's to answer by signing in again.
        if looks_signed_out(page):
            raise SessionExpired("the credit card tab opened the sign-in page")
        raise _left_the_list("open the credit card statements",
                             "the credit card tab did not open the card statements page")
    if any(not _clean(h) for h in heard):
        raise ListStopped("an answer the page had for its card statements could not be read, "
                          "or came back with an error")
    # The statements of one card account are read. An answer naming more
    # than one is a list this cannot tell apart, never one account's alone.
    if any(_card_accounts(h["body"]) > 1 for h in heard):
        raise ListStopped("the page names more than one card account")
    lists = [h for h in heard if _statements_of(h["body"]) is not None]
    if not lists:
        if any(_has_no_card(h["body"]) for h in heard) and not rows:
            log.info("the Credit Card tab answers that this account has no card")
            return None
        raise ListStopped("the page's own list of card statements was not heard")
    if len(lists) > 1:
        raise ListStopped("the page answered its list of card statements more than once")
    edges = _card_edges(lists[0])
    try:
        if page.locator(_LOAD_MORE).count():
            raise ListStopped("the card statements page shows a Load more this does not read")
    except ListStopped:
        raise
    except Exception as e:
        raise ListStopped("the card statements page could not be read (%s)" % type(e).__name__)
    rows = _card_rows(page)
    if len(rows) != len(edges):
        raise ListStopped("the page shows %d card statements and its own list names %d"
                          % (len(rows), len(edges)))
    labels = [r.get("label") or "" for r in rows]
    if not all(month_to_iso(lab) for lab in labels) or len(set(labels)) != len(labels):
        raise ListStopped("a card statement row has no month this can read, or shares one")
    if set(labels) != {_card_label(d) for _s, d in edges}:
        raise ListStopped("the card statement rows and the page's own list name different months")
    return CardList(edges=edges, rows=rows)


def _collect_card(page) -> List[RawDoc]:
    """One RawDoc per Coinbase One Card statement, newest first, titled by
    its row's month and dated by its closing day. Nothing about it that is
    the account's own, its id or the statement's, is kept. A list that
    cannot be read whole raises CardListUnread, which leaves the card
    statements alone and never the other families."""
    try:
        found = open_card_list(page)
    except ListStopped as stop:
        raise CardListUnread(str(stop))
    if found is None:
        log.info("no card statements are listed, since the page shows no card")
        return []
    docs = []
    for _sid, iso in sorted(found.edges, key=lambda e: e[1], reverse=True):
        label = _card_label(iso)
        docs.append(RawDoc(title=f"Coinbase One Card Statement {label}", date_text=iso,
                           text=f"Coinbase One Card Statement {label}",
                           row_index=len(docs), kind="card"))
    log.info("card statements listed: %d", len(docs))
    return docs


def _card_pdf_ok(body: bytes, iso: str) -> str:
    """"" for a PDF that is this card statement, and otherwise why not. It
    has to be a PDF, say "Coinbase One Card" and print the closing day."""
    if not body or body[:5] != b"%PDF-":
        return "the answer is not a PDF"
    try:
        text = whole_characters("\n".join(pdf_reader.page_texts(body)))
    except Exception:
        text = ""
    flat = re.sub(r"\s+", " ", text)
    if not flat.strip():
        return "the PDF's text could not be read"
    if not re.search(r"\bCoinbase One Card\b", flat):
        return "the PDF does not say Coinbase One Card"
    if not closing_date_re(iso).search(flat):
        return "the PDF does not print the statement's closing day"
    return ""


def _press_card_pdf(page, label: str, trace: Optional[list], brought=None):
    """Press the PDF button of the card row that reads `label`, once,
    through press_once. The press as press_once says it went, or None when
    nothing was pressed, a button turned off or gone, or a row that reads
    another month by the press, which leaves the statement for review and
    the next run."""
    def note(what: str) -> None:
        if trace is not None:
            trace.append({"note": what})

    idx, btn_label = row_index_for(_card_rows(page), label)
    if idx < 0:
        note("no single card row reads this month")
        return None
    if not is_card_pdf_label(btn_label):
        note("the card row's button is not its PDF button")
        return None
    try:
        el = page.locator("button").nth(idx).element_handle(timeout=3000)
    except Exception:
        el = None
    if el is None:
        note("the card row's PDF button could not be read")
        return None

    def row_changed() -> str:
        try:
            now = el.evaluate(_CARD_LABEL_OF_JS)
        except Exception:
            return "its row could not be read"
        return "" if now == label else "its row reads another month"

    try:
        if row_changed():
            note("the card PDF button's row reads another month now")
            return None
        try:
            outcome = pressing.press_once(
                page, el, what="the PDF button of this month's card statement", words=_words(),
                guard=is_card_pdf_label, check=row_changed, brought=brought,
                step="press a card statement's PDF button")
        except pressing.TurnedOff:
            note("the card PDF button is turned off on the page, so nothing was pressed")
            return None
        if outcome.how == pressing.GONE:
            note("the card PDF button left the page before it was pressed")
            return None
        note("clicked" if outcome.error is None else "click raised, not made again")
        return outcome
    finally:
        try:
            el.dispose()
        except Exception:
            pass


def _back_to_card_list(page, count: int, trace: Optional[list]) -> bool:
    """Take the tab back to the card list, and require it to show its
    `count` rows again. A list that does not come back has the statements
    page loaded by its address, so the tab is never left at the statement's
    signed address."""
    try:
        if _no_fragment(page.url) != CARD_LIST_URL:
            page.go_back(wait_until="domcontentloaded", timeout=30000)
    except Exception as e:
        if trace is not None:
            trace.append({"note": "going back raised", "error": type(e).__name__})
    waited = 0
    while True:
        if _no_fragment(page.url) == CARD_LIST_URL and len(_card_rows(page)) == count:
            return True
        if waited >= CARD_BACK_WAIT_MS:
            break
        page.wait_for_timeout(500)
        waited += 500
    if trace is not None:
        trace.append({"note": "the card list did not show again, so the statements page was loaded"})
    reload_statements(page)
    return False


def _take_card_statement(page, label: str, iso: str, out_path: Path, trace: Optional[list]) -> bool:
    """Take the card statement of the month `label` closing on `iso`, on
    the statements page as it was just loaded. See the module's docstring
    for the whole path. Anything the press brings that it should not, a
    popup, a download, the tab arriving anywhere but the address the page
    named, or an answer that names another statement or another date,
    stops the run. A statement whose PDF does not prove itself is left for
    review, since by then its address was bound to its row."""
    def note(what: str, **more) -> None:
        if trace is not None:
            trace.append(dict({"note": what}, **more))

    step = "take a card statement"
    # The list was read whole at discovery, and is read again for this
    # statement. One that is not whole now, or no longer names this
    # statement once, stops the run, before anything is pressed for it.
    try:
        found = open_card_list(page)
    except ListStopped as stop:
        note("the card list could not be read", why=str(stop)[:120])
        raise _list_changed(step, "the list of card statements could not be read again")
    if found is None:
        raise _list_changed(step, "the page shows no card statements now")
    sids = [s for s, d in found.edges if d == iso]
    if len(sids) != 1 or _card_label(iso) != label:
        raise _list_changed(step, "the list of card statements does not name this one once now")
    sid = sids[0]
    popups: list = []
    downloads: list = []

    def on_popup(p):
        popups.append(p)

    def on_download(dl):
        downloads.append(dl)
    heard, on_response = _listen(page)
    listeners = (("popup", on_popup), ("download", on_download), ("response", on_response))
    for ev, fn in listeners:
        page.on(ev, fn)

    def answers() -> list:
        return [h for h in heard if h["op"] == CARD_ROW_QUERY]

    pressed = False
    try:
        outcome = _press_card_pdf(page, label, trace,
                                  brought=lambda: bool(answers() or popups or downloads))
        if outcome is None:
            return False
        pressed = True
        waited = 0
        while not popups and not downloads:
            if answers() and _no_fragment(page.url) != CARD_LIST_URL:
                break
            if waited >= CARD_LAND_WAIT_MS:
                break
            page.wait_for_timeout(500)
            waited += 500
        if popups or downloads:
            for dl in downloads:
                try:
                    dl.cancel()
                except Exception:
                    pass
            raise _left_the_list(step, "a popup or a download came" if popups and downloads
                                 else ("a popup came" if popups else "a download came"))
        # From the press on, a statement whose address cannot be bound to
        # its row stops the run, so no second row is pressed after it.
        got = answers()
        if not got:
            raise _left_the_list(step, "the page did not answer with the address of the statement")
        if len(got) != 1:
            raise _left_the_list(step, "the page answered one press more than once")
        answer = got[0]
        if answer["statement_id"] != sid:
            raise _left_the_list(step, "the press asked for another statement than its row")
        card = _card_of(answer["body"]) if _clean(answer) else None
        url = card.get("statementUrl") if isinstance(card, dict) else None
        if url is None and answer["body"] is None and answer.get("status") == 200:
            # On the live page the tab's own move to the statement's address
            # evicts the answer's body before it can be read. The address the
            # page was handed is then where the tab landed, bound to the row's
            # date exactly as a heard one is, and the request that brought it
            # has already been held to the row's statementId above. An answer
            # that was read but names no address still stops the run.
            landed = _no_fragment(page.url)
            if is_card_statement_url(landed, iso):
                note("the statement's address was read from the tab")
                url = landed
        if not isinstance(url, str):
            raise _left_the_list(step, "the page answer naming the statement could not be read")
        if not is_card_statement_url(url, iso):
            host = ""
            try:
                host = urlsplit(url).hostname or ""
            except ValueError:
                pass
            if host != CARD_STATEMENT_HOST:
                note("the statement's address is refused", host=host[:60])
                raise _left_the_list(step, "the address of the statement is on another host")
            raise _left_the_list(step, "the address of the statement names another date")
        if _no_fragment(page.url) != url:
            raise _left_the_list(step, "the tab is not at the address of the statement")
        try:
            resp = page.context.request.get(url, max_redirects=0, timeout=60000)
        except Exception as e:
            note("the statement could not be fetched", error=type(e).__name__)
            return False
        status = getattr(resp, "status", 0)
        if status != 200:
            note("the statement's address answered", status=status)
            return False
        try:
            body = intake.body(resp)
        except Exception as e:
            note("the statement's answer could not be read", error=type(e).__name__)
            return False
        why = _card_pdf_ok(body, iso)
        if why:
            note(why)
            return False
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(body)
        note("card statement taken")
        return True
    finally:
        for ev, fn in listeners:
            try:
                page.remove_listener(ev, fn)
            except Exception:
                pass
        if pressed or _no_fragment(page.url) != CARD_LIST_URL:
            _back_to_card_list(page, len(found.edges), trace)


def load_statements_for_card(page) -> bool:
    """The statements page loaded by its address, waiting for its Credit
    Card tab rather than for the Transactions list, so an account whose
    Transactions list draws late or not at all still reaches its card."""
    try:
        page.goto(STATEMENTS_URL, wait_until="domcontentloaded", timeout=60000)
    except Exception as e:
        log.info("could not load the statements page (%s)", type(e).__name__)
        return False
    if looks_signed_out(page):
        return False
    try:
        page.wait_for_selector(CARD_LINK_CSS, timeout=30000)
        return True
    except Exception:
        return False


def where_landed(page) -> str:
    """Where the tab is, for a file a tester may send, the redacted address
    on Coinbase's own hosts, and only the host anywhere else, since the
    card statement's address is signed."""
    url = getattr(page, "url", "") or ""
    if is_safe_url(url):
        return redact(url)
    try:
        return (urlsplit(url).hostname or "")[:60]
    except ValueError:
        return ""


# ---------------------------------------------------------------------------
# Diagnose. Loose, redacted scrape and a survey of the signed-in pages.
# No screenshot.
# ---------------------------------------------------------------------------
_ROW_JS = r"""() => {
  const out = [];
  for (const tr of document.querySelectorAll('table tr, [role=row], li, [class*="statement" i], [class*="document" i]')) {
    const txt = (tr.innerText || '').trim();
    if (!txt) continue;
    const link = tr.querySelector("a[href]");
    out.push({text: txt.slice(0, 200), href: link ? link.getAttribute('href') : ''});
  }
  return out.slice(0, 200);
}"""

SURVEY_LINK_RE = re.compile(r"^\s*(statements?|documents?|view\s+tax\s+forms|tax\s+documents?)\s*$", re.I)
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
    Records the page's headings and controls with the guard's verdict, and
    the path, status and shape of every JSON or PDF response an allowed host
    sends while the page settles. Follows nothing: the only controls this
    app ever presses are a statement row's PDF button and Load more, and a
    survey is not a reason to press a third kind. Query strings are not
    kept, not even as names. No screenshot."""
    seen: list = []

    def on_response(res):
        try:
            url = res.url or ""
            if not is_safe_url(url):
                return
            ct = (res.headers.get("content-type") or "").lower()
            if "json" not in ct and "pdf" not in ct:
                return
            entry = {"path": redact(urlsplit(url).path)[:200], "status": res.status, "type": ct[:40]}
            try:
                entry["method"] = res.request.method
            except Exception:
                pass
            if "json" in ct:
                try:
                    entry["shape"] = _shape(whole_json(res.json()))
                except Exception:
                    entry["shape"] = "unreadable"
            seen.append(entry)
        except Exception:
            pass

    page.on("response", on_response)
    report = {"pages": [], "responses": seen}
    try:
        page.wait_for_timeout(dwell_ms)
        report["pages"].append(_page_summary(page))
    finally:
        try:
            page.remove_listener("response", on_response)
        except Exception:
            pass
    return report
