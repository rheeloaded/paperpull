"""ALL digital.firsthorizon.com selectors, URLs and page behavior live here.

When First Horizon changes its digital banking, repair this file only.

STATUS: built from the account owner's survey of a signed-in account on
2026-10-12 and one live probe, then run in full on that account the same
day, one checking account with 24 statements: Pilot saved one and Run All
the other 23. More than one account on one sign-in has not been seen.

WHAT THE SURVEY AND THE PROBE ESTABLISHED
  * Everything is on one host, https://digital.firsthorizon.com, an NCR D3
    single-page app. The statements page is the route #accounts/documents:
    heading "View Statements", one tab button "STATEMENTS"
    (button.edocs-estatements-tab), and one accordion panel per account,
    div.accordion-panel[role=button][aria-expanded], titled
    "NICKNAME (Product) (*1234) $balance".
  * A panel's statements load only when it is expanded: the page itself then
    GETs /d3rest/v4/edocs/accounts/<userAccountId>/links and draws the
    answer's accountDocumentLinks.STATEMENT entries as cards,
    div.card.edocs-item-card[aria-label="Monthly statement for MM/DD/YYYY"],
    each with a "Download PDF" button (button.edocs-download-btn, aria-label
    "Open New Tab to Download PDF for MM/DD/YYYY statement"). The button
    opens a popup that GETs /d3rest + endpoints.file, which the browser turns
    into a download, and the popup closes itself.
  * The bank's API refuses a request that does not carry the headers the
    page computes for itself (403 "Invalid CSRF Token"), and this app will
    not compute or copy them. So the list is read from the page's OWN answers,
    heard on the browser context (_Watch), and the PDF is taken from the
    download the page's own button makes. The one request this app asks
    itself is the session probe, GET /d3rest/v3/auth/session, whose body
    (the holder's profiles) is checked for its shape and dropped at once.

THE TWO PRESSES. Nothing else is ever pressed, and each goes through one
place, _press, which reads every label the control carries, asks this
module's own predicate, and only then hands the press to the core
(pressing.click):
  1. an account's panel, only while it reads aria-expanded="false"
     (is_account_panel): it expands, never collapses
  2. one bound card's "Download PDF" button, for that card's date only
     (is_download_button)
"View Online", "Manage Statement Delivery", the STATEMENTS tab, Enroll, the
session-timeout dialog, Log Out and everything else are refused.
A control the page has turned off is never pressed. A turned-off panel
stops the list in Discover and stops the run while a statement is sought,
and a turned-off Download PDF leaves that one statement for the next run,
with no record against it, while the run goes on.

SAFETY (a bank account that can pay, transfer and send money):
  READ-ONLY. FORBIDDEN_CONTROL_RE and the core's settings and sign-in guards
  refuse any label that could pay, transfer, send, enroll, manage delivery,
  link, export or edit accounts, or sign out. Nothing is POSTed, and the
  SPA's keepalive /d3rest/v3/login/ping is never called.

PRIVACY: every panel title, whole and part by part (nickname, masked
number, balance), is registered as a private word before any press, and
every account id and document id as soon as an answer is read. None of
them, nor an answer, nor an address that carries an id, is logged or said.
An account is written down only as the product noun in its title, "Express
Checking".

SIGNED OUT: the session-timeout dialog's words on the page, a sign-in
address, a password field, a links or PDF answer that is a redirect, a 401
or 403, HTML, or not JSON, or a session probe that is not the signed-in
shape, checked before and after every wait and press, raises
SessionExpired. The run saves, says so and stops; nothing is recorded for
review.

KNOWN CEILINGS (left until a live run shows otherwise)
  * A panel's cards are read inside the element its aria-controls names.
    A panel without one, or with an id that is not a plain CSS name, stops
    the list.
  * A panel the page hides, or draws only after the list is read, stops
    the list, so a hidden account is never listed.
  * A panel drawn late is seen only until shortly after the walk ends. The
    page then settles twice, 1.5 seconds each, and is read after each, so
    a panel drawn more than 3 seconds after the walk ends is not seen.
  * A panel expanded when the page loads is bound to its answer only when
    the dates make the pairing unique; otherwise the list stops. A panel is
    never collapsed to recover.
  * Two statements of one account on one date, or under one id, stop the
    list, and so does an id a later listing shows under another date than
    its record holds (firsthorizon_docs).
  * Only statements. Tax forms are online only once the holder enrolls in
    online tax statements, which this app never does.
  * The bank ends an idle session after ten minutes; a run stops itself
    eight minutes after its session probe (Run).
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import date as _date
from pathlib import Path
from typing import Callable, List, Optional, Tuple
from urllib.parse import quote, unquote, urlsplit

from paperpull_core import intake
from paperpull_core import pressing
from paperpull_core import redirects
from paperpull_core.controls import SETTINGS_CONTROL_RE, AUTH_CONTROL_RE
from paperpull_core.redact import private_words, redact, set_private_words  # noqa: F401  (re-exported)
from paperpull_core.urls import is_safe_url as _host_allows
from paperpull_core.dates import last_day as _last_day
from paperpull_core.dates import checked as _checked_date
from paperpull_core.dates import full_year as _full_year
# re-exported: the docs module calls it as site.set_download_dir
from paperpull_core.capture import set_download_dir  # noqa: F401
from paperpull_core.capture import snapshot as _snapshot
from paperpull_core.capture import take_download as _take_download
from paperpull_core.capture import clear_copies as _clear_copies
from paperpull_core.words import words_for as _words_for
from paperpull_core.characters import whole_json

log = logging.getLogger("firsthorizon_docs.site")


def _words():
    """This app's own words for paperpull_core.words."""
    return _words_for("First Horizon", sys.modules[__name__])


# ---------------------------------------------------------------------------
# Addresses
# ---------------------------------------------------------------------------
BASE = "https://digital.firsthorizon.com"
API = f"{BASE}/d3rest"
DOCUMENTS_ROUTE = "accounts/documents"
# The statements page. The hash is a route inside the single-page app.
DOCUMENTS_URL = f"{BASE}/#{DOCUMENTS_ROUTE}"
STATEMENTS_URL = DOCUMENTS_URL
BILLING_URL = DOCUMENTS_URL
SESSION_URL = f"{API}/v3/auth/session"
URLS = {
    "home": f"{BASE}/",
    # A signed-out visit is sent on to security.firsthorizon.com, where the
    # account holder signs in.
    "login": f"{BASE}/",
    "documents": DOCUMENTS_URL,
    "statements": DOCUMENTS_URL,
}

LOGIN_URL_MARKERS = ["security.firsthorizon.com", "/fhnsso/", "/sso/logout", "www.firsthorizon.com"]

# The bank's own words for a session about to end or ended. Read, never
# answered: its buttons are never pressed.
TIMEOUT_WORDS = ("session timeout warning", "your session has expired", "your session will expire")

# ---------------------------------------------------------------------------
# HARD SAFETY GUARD. Every stem anchored.
# ---------------------------------------------------------------------------
FORBIDDEN_CONTROL_RE = re.compile(
    r"(\benroll|\benrollment\b|\bmanage\s+statement\s+delivery\b|\bstatement\s+delivery\b|"
    r"\baccount\s+options\b|\blink\s+an?\s+account\b|\bedit\s+accounts?\s+list\b|\bexport|"
    r"\bzelle\b|\bquick\s+payment\b|\bquick\s+transfer\b|\bpay\b|\bpaying\b|\bpayments?\b|"
    r"\bpayees?\b|\btransfers?\b|\btransferring\b|\bmanage\s+your\s+cards\b|"
    r"\bopen\s+a\s+new\s+account\b|\bstay\s+logged\s+in\b|\bskip\s+this\s+step\b|\ball\s+done\b|"
    r"\bgo\s+paperless\b|\bpaperless\b|\bfeedback\b|\blogout\b|\blog\s*(out|off)\b|"
    r"\bsign\s*(out|off)\b|\bmessages?\b|\balerts?\b|\bview\s+online\b|\bsend\s+money\b|"
    r"\bsettings?\b|\bpreferences?\b|\bsave\b|\bsubmit\b|\bconfirm\b|\bcontinue\b|"
    r"\bdelet(e|es|ed|ing)\b|\bremov(e|es|ed|ing|al)\b|\bcancel\b|\bedit(s|ed|ing)?\b|"
    r"\bupdat(e|es|ed|ing)\b|\bchang(e|es|ed|ing)\b|\bmanage\b|\bopt\s*-?\s*(in|out)\b|"
    r"\bclose\b|\bupload\b|\bemail\b|\bshare\b|\bchat\b|\bcontact\b|\brequest(s|ed|ing)?\b|"
    r"\bdeposit|\bwithdraw|\bagree\b|\baccept\b|\bauthori[sz]e\b|\bverify\b|\bpassword\b|"
    r"\busername\b|\bdetails\b|\bcollapse\b|\bhide\b)", re.I)

# The two shapes this app presses, matched whole on every label.
_MDY = r"(\d{2})/(\d{2})/(\d{4})"
PANEL_TITLE_RE = re.compile(
    r"(?P<nick>.+) \((?P<product>[^()]+)\) \(\*(?P<mask>\d{4})\) (?P<balance>-?\$-?[\d,]+(?:\.\d{2})?)")
DOWNLOAD_PDF_RE = re.compile(r"download pdf", re.I)
DOWNLOAD_ARIA_RE = re.compile(r"open new tab to download pdf for " + _MDY + r" statement", re.I)
CARD_LABEL_RE = re.compile(r"monthly statement for " + _MDY, re.I)

# is_safe_control is what the core's own tests and the survey ask about; the
# presses themselves use the two predicates below.
SAFE_DOC_CONTROL_RES = (
    re.compile(r"(view|download)\s+(pdf|statement|bank\s+statement)", re.I),
    DOWNLOAD_ARIA_RE,
)

# A control that fetches one statement, for the survey.
STATEMENT_CONTROL_RE = re.compile(r"^\s*download\s+pdf\s*$", re.I)

SECURITY_CHALLENGE_MARKERS = [
    "enter the code", "verification code", "6-digit", "two-factor",
    "two-step", "authenticator", "confirm your identity", "verify your identity",
    "we sent a code", "one-time passcode", "device approval",
    "are you a robot", "captcha", "check your email", "check your phone",
    "your session has expired", "session timeout warning", "access denied",
]

RATE_LIMIT_MARKERS = [
    "too many requests", "rate limit", "try again later",
    "temporarily unavailable", "http error 429", "unusual traffic",
]

PANEL = 'div.accordion-panel[role="button"][aria-expanded]'
CARD = 'div.card.edocs-item-card[aria-label^="Monthly statement for "]'
DOWNLOAD_BUTTON = "button.edocs-download-btn"
TAB_BUTTON = "button.edocs-estatements-tab"
FALLBACK = {
    "doc_row": "div.card.edocs-item-card",
    "doc_link": DOWNLOAD_BUTTON,
    "download_control": DOWNLOAD_BUTTON,
    "page_ready": "div.accordion-panel",
}

READY_WAIT_MS = 30000
LIST_WAIT_MS = 20000
SETTLE_MS = 1500
DOWNLOAD_WAIT_MS = 60000
SECOND_DOWNLOAD_WAIT_MS = 3000
POLL_MS = 250
# The bank ends a session idle for ten minutes. A run stops itself this
# long after its session probe, before the next navigation, press or wait.
DEADLINE_S = 8 * 60

# ---------------------------------------------------------------------------
# Date parsing, the same general reader the other apps carry. The
# statements themselves use statement_date below, which reads one shape only.
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


_ISO_RE = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})")


def statement_date(text) -> Optional[str]:
    """A statement's documentDate as YYYY-MM-DD, or None. The whole value
    must be the date, written YYYY-MM-DD, and the day must exist."""
    if not isinstance(text, str):
        return None
    m = _ISO_RE.fullmatch(text)
    if not m:
        return None
    try:
        return _date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
    except ValueError:
        return None



def _card_date(label) -> Optional[str]:
    """A card's "Monthly statement for MM/DD/YYYY" as YYYY-MM-DD, or None."""
    m = CARD_LABEL_RE.fullmatch(_tidy(label))
    if not m:
        return None
    try:
        return _date(int(m.group(3)), int(m.group(1)), int(m.group(2))).isoformat()
    except ValueError:
        return None


def _mdy(iso: str) -> str:
    """YYYY-MM-DD as the page writes it, MM/DD/YYYY."""
    return f"{iso[5:7]}/{iso[8:10]}/{iso[:4]}"


# ---------------------------------------------------------------------------
# Session / safety
# ---------------------------------------------------------------------------

class SessionExpired(Exception):
    """First Horizon answered as a signed-out session: its timeout words on
    the page, its sign-in page, a password field, or an answer that is a
    redirect, a 401 or 403, HTML, or not the signed-in JSON. The run stops
    for the account holder."""


class ListStopped(Exception):
    """The list has a part this could not read, so what was read is not all
    of it. `docs` holds what was read before it stopped. Its words are this
    module's own, never the page's."""

    def __init__(self, why: str, docs=None):
        super().__init__(why)
        self.docs = list(docs or [])


class DeadlineReached(Exception):
    """The run has been at First Horizon for DEADLINE_S since its session
    probe, so it stops before the next navigation, press or wait."""


def _tidy(name) -> str:
    return re.sub(r"\s+", " ", str(name or "")).strip()


def looks_signed_out(page) -> bool:
    """The sign-in or signed-out page by its address, or a password field.
    A page whose address cannot be read raises, and is never called signed
    in."""
    url = (page.url or "").lower()
    if any(m in url for m in LOGIN_URL_MARKERS):
        return True
    try:
        if page.locator("input[type='password']").count() > 0:
            return True
    except Exception:
        pass
    return False


_TIMEOUT_JS = r"""words => {
  const body = ((document.body && document.body.innerText) || '').toLowerCase();
  return words.some(w => body.includes(w));
}"""


def _timeout_shown(page) -> bool:
    """The bank's session-timeout warning, or its "session has expired",
    on the page. Its buttons are never pressed."""
    try:
        return bool(page.evaluate(_TIMEOUT_JS, list(TIMEOUT_WORDS)))
    except Exception:
        return False


def check_signed_in(page) -> None:
    """Raise SessionExpired when the page shows the bank signing the session
    out. Asked before and after every wait and every press."""
    if looks_signed_out(page):
        raise SessionExpired("First Horizon showed its sign-in page")
    if _timeout_shown(page):
        raise SessionExpired("First Horizon is showing its session timeout")


def detect_security_challenge(page) -> Optional[str]:
    """Names the passcode, CAPTCHA, timeout or throttling prompt on screen,
    or None. A page that shows a statement card is not a challenge."""
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


def _refused(name: str) -> bool:
    return bool(FORBIDDEN_CONTROL_RE.search(name) or SETTINGS_CONTROL_RE.search(name)
                or AUTH_CONTROL_RE.search(name))


def is_safe_control(name: str) -> bool:
    """Deny by default: an unreadable label is refused, then this app's
    blocklist, then the shared core guards, and only then the anchored
    document actions, whole."""
    name = _tidy(name)
    if not name or _refused(name):
        return False
    return any(rx.fullmatch(name) for rx in SAFE_DOC_CONTROL_RES)


# -- the two predicates, one for each control this app presses ---------------

def is_account_panel(label: str) -> bool:
    """An account's statements panel, "NICKNAME (Product) (*1234) $12.34",
    exactly that shape, after the blocklist and the core guards."""
    label = _tidy(label)
    return bool(label) and not _refused(label) and bool(PANEL_TITLE_RE.fullmatch(label))


def is_download_button(label: str, iso_date: str = "") -> bool:
    """A card's "Download PDF", or its "Open New Tab to Download PDF for
    MM/DD/YYYY statement" for `iso_date` only when one is given."""
    label = _tidy(label)
    if not label or _refused(label):
        return False
    if DOWNLOAD_PDF_RE.fullmatch(label):
        return True
    m = DOWNLOAD_ARIA_RE.fullmatch(label)
    if not m:
        return False
    try:
        said = _date(int(m.group(3)), int(m.group(1)), int(m.group(2))).isoformat()
    except ValueError:
        return False
    return not iso_date or said == iso_date


PRESS_GUARDS = (is_account_panel, is_download_button)


# ---------------------------------------------------------------------------
# Hosts. Exact, parsed, no subdomain wildcard.
# ---------------------------------------------------------------------------
ALLOWED_HOSTS = {"digital.firsthorizon.com"}
_DOC_ID_RE = r"[A-Za-z0-9._-]+"
_LINKS_PATH_RE = re.compile(r"/d3rest/v4/edocs/accounts/([^/]+)/links")
_DOWNLOAD_PATH_RE = re.compile(
    r"/d3rest/v4/edocs/accounts/[^/]+/statement/[0-9]{4}-[0-9]{2}-[0-9]{2}/" + _DOC_ID_RE)


def is_safe_url(url: str) -> bool:
    """True only for an https URL on exactly digital.firsthorizon.com."""
    return _host_allows(url, ALLOWED_HOSTS, subdomains=False)


def _plain(url):
    """The parsed address when it is on the host and carries no query or
    fragment, else None."""
    if not isinstance(url, str) or not is_safe_url(url) or "?" in url or "#" in url:
        return None
    try:
        return urlsplit(url)
    except ValueError:
        return None


def _no_dots(doc_id: str) -> bool:
    return bool(doc_id) and set(doc_id) != {"."}


def is_documents_url(url: str) -> bool:
    """The statements page: the host's root with the documents route."""
    if not is_safe_url(url):
        return False
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    return parts.path in ("", "/") and not parts.query and parts.fragment == DOCUMENTS_ROUTE


def is_links_url(url: str) -> bool:
    """One account's documents answer, exactly that path."""
    parts = _plain(url)
    return parts is not None and bool(_LINKS_PATH_RE.fullmatch(parts.path))


def links_account_id(url: str) -> str:
    """The account id a links address names, decoded, or ""."""
    parts = _plain(url)
    m = _LINKS_PATH_RE.fullmatch(parts.path) if parts else None
    return unquote(m.group(1)) if m else ""


def is_download_url(url: str) -> bool:
    """A statement PDF's own address: exactly this host, the statement path
    with a dated document, no query."""
    parts = _plain(url)
    if parts is None or not _DOWNLOAD_PATH_RE.fullmatch(parts.path):
        return False
    return _no_dots(parts.path.rsplit("/", 1)[-1])


def file_matches(file, account_id: str, iso: str) -> bool:
    """Whether a statement's endpoints.file is a relative, queryless path to
    a statement of this account on this date."""
    if not isinstance(file, str) or not account_id or not iso:
        return False
    rx = re.compile(r"/v4/edocs/accounts/" + re.escape(quote(account_id, safe="")) + r"/statement/"
                    + re.escape(iso) + r"/" + _DOC_ID_RE)
    return bool(rx.fullmatch(file)) and _no_dots(file.rsplit("/", 1)[-1])


def download_url(file) -> str:
    """The one PDF address a statement's endpoints.file names, or "". It is
    held in memory only, since it carries the account id."""
    if not isinstance(file, str) or not file.startswith("/v4/"):
        return ""
    url = API + file
    return url if is_download_url(url) else ""


# ---------------------------------------------------------------------------
# Private words
# ---------------------------------------------------------------------------

def _guard_words(values) -> None:
    """Register each value as a private word, whole when it is one word of
    four characters or more, and part by part (four letters or more, or any
    part with a digit), as redact applies them anywhere in a string."""
    parts = set()
    for v in values:
        if not isinstance(v, str):
            continue
        whole = v.strip()
        if len(whole) >= 4 and not re.search(r"[\s,]", whole):
            parts.add(whole)
        parts.update(p for p in re.split(r"[^A-Za-z0-9]+", v)
                     if len(p) >= 4 or re.search(r"[0-9]", p))
    new = sorted(parts - set(private_words()))
    if new:
        set_private_words(private_words() + new)


def product_of(title: str) -> str:
    """The product noun of a panel's title, "Express Checking", or "" when
    the title is not exactly "NICKNAME (Product) (*1234) $balance"."""
    m = PANEL_TITLE_RE.fullmatch(_tidy(title))
    return m.group("product").strip() if m else ""


def _guard_titles(state: dict) -> None:
    """Every panel's nickname, masked number and balance, whole and in
    parts, are private before anything is pressed."""
    values = []
    for p in state.get("panels") or []:
        for t in [p.get("title")] + list(p.get("labels") or []):
            t = _tidy(t)
            m = PANEL_TITLE_RE.fullmatch(t)
            # The product noun is not personal and is what records say, so
            # a title of the surveyed shape gives every part but that. One
            # that is not gives every part, product words included.
            values += [m.group("nick"), m.group("mask"), m.group("balance")] if m else [t]
    _guard_words(values)


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------

def _origin(response):
    """The page whose frame asked for `response`, or None when it cannot be
    told. An answer from no known page is never this run's."""
    try:
        return response.frame.page
    except Exception:
        return None


class _Watch:
    """The page's own links answers, heard on the browser context from the
    moment it is attached, before any page is taken or loaded, each kept
    with the page that asked for it. Only answers from the run's own page
    are ever read; another First Horizon tab's are heard and left alone.
    Nothing is read from an answer here but its address, status and page."""

    def __init__(self):
        self.links: list = []          # (page, response)
        self.signed_out: list = []     # pages a signed-out answer came to

    def on_response(self, response) -> None:
        try:
            if not is_links_url(response.url):
                return
            origin = _origin(response)
            if _signed_out_status(response):
                self.signed_out.append(origin)
            else:
                self.links.append((origin, response))
        except Exception:
            pass

    def mark(self) -> int:
        return len(self.links)

    def links_since(self, mark: int, page) -> list:
        return [r for origin, r in self.links[mark:] if origin is page]

    def raise_if_signed_out(self, page) -> None:
        if any(origin is page for origin in self.signed_out):
            raise SessionExpired("the bank answered the page's own request as signed out")


class Run:
    """What one command carries between presses: the clock its deadline is
    counted on, from the session probe, and the watch on the browser
    context. The App owns one per command."""

    def __init__(self, clock: Callable[[], float] = time.monotonic, limit_s: float = DEADLINE_S):
        self.clock = clock
        self.limit_s = limit_s
        self.started: Optional[float] = None
        self.watch = _Watch()
        self._context = None

    def attach(self, context) -> None:
        """Listen on `context`, once. Done by the App as soon as the browser
        context exists, before any page is acquired."""
        if context is None or context is self._context:
            return
        if self._context is not None:
            try:
                self._context.remove_listener("response", self.watch.on_response)
            except Exception:
                pass
        context.on("response", self.watch.on_response)
        self._context = context

    def start(self) -> None:
        if self.started is None:
            self.started = self.clock()

    def past_deadline(self) -> bool:
        return self.started is not None and self.clock() - self.started >= self.limit_s

    def remaining_ms(self, want_ms: float) -> float:
        """`want_ms`, or less when the deadline comes sooner."""
        if self.started is None:
            return want_ms
        left = (self.limit_s - (self.clock() - self.started)) * 1000
        return max(0.0, min(want_ms, left))

    def cap(self, want_ms: float) -> int:
        """A timeout for one blocking call: `want_ms`, or the time left when
        that is less. Raises DeadlineReached when none is left."""
        self.in_time()
        left = int(self.remaining_ms(want_ms))
        if left <= 0:
            raise DeadlineReached("the run has used most of the bank's session")
        return left

    def in_time(self) -> None:
        if self.past_deadline():
            raise DeadlineReached("the run has used most of the bank's session")


def _signed_out_status(response) -> bool:
    try:
        status = int(response.status)
    except Exception:
        return False
    return status in (401, 403) or status in redirects.REDIRECTS or 300 <= status < 400


def _ctype(response) -> str:
    try:
        return (response.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
    except Exception:
        return ""


def _exactly(want: str):
    def guard(url) -> bool:
        return isinstance(url, str) and url == want and _plain(url) is not None
    return guard


def session_alive(page, run: Run) -> bool:
    """The one request this app asks itself: GET /d3rest/v3/auth/session,
    no redirect followed. Signed in only for a 200 whose JSON is an object
    with a "profiles" list. The body holds the holder's own details, so it
    is checked for that shape and dropped; nothing of it is kept or logged.
    The run's deadline starts here."""
    run.start()
    try:
        resp = redirects.get(page.context.request, SESSION_URL, _exactly(SESSION_URL), hops=0,
                             timeout=run.cap(60000))
    except redirects.TooManyRedirects:
        raise SessionExpired("the session probe was sent on")
    except DeadlineReached:
        raise
    except Exception as e:
        run.in_time()
        log.info("the session probe failed (%s)", type(e).__name__)
        raise ListStopped("the session probe failed")
    run.in_time()
    if _signed_out_status(resp):
        raise SessionExpired("the session probe answered as signed out")
    try:
        body = intake.body(resp)
    except Exception:
        raise ListStopped("the session probe could not be read")
    if _ctype(resp).startswith("text/html") or body.lstrip()[:1] == b"<":
        raise SessionExpired("the session probe answered with a page")
    if resp.status != 200:
        raise ListStopped("the session probe was answered %d" % resp.status)
    try:
        got = whole_json(json.loads(body.decode("utf-8")))
    except (ValueError, UnicodeDecodeError):
        raise SessionExpired("the session probe was not JSON")
    ok = isinstance(got, dict) and isinstance(got.get("profiles"), list)
    del got, body
    if not ok:
        raise SessionExpired("the session probe is not the signed-in shape")
    return True


def signed_in(page, run: Optional[Run] = None) -> bool:
    try:
        return session_alive(page, run or Run())
    except (SessionExpired, ListStopped) as e:
        log.info("the session probe says not signed in: %s", e)
        return False


# ---------------------------------------------------------------------------
# The page's own answers
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
    # The bank's document id, the last part of the statement's address.
    # Private: never logged or in a name.
    document_id: str = ""
    # The bank's own id of the account. Private: kept in the run's own
    # records only, to find the account's panel again.
    account_id: str = ""


@dataclass(frozen=True)
class Statement:
    date: str
    doc_id: str
    file: str


def statements_of(got, account_id: str) -> List[Statement]:
    """One account's statements from its links answer. Not the signed-in
    shape raises SessionExpired. An entry this cannot read, one for another
    account, or two of one date or of one id stop the list. A record's key
    is the account and the id alone, so two statements under one id would
    be one record."""
    if not isinstance(got, dict) or not isinstance(got.get("accountDocumentLinks"), dict):
        raise SessionExpired("the documents answer is not the signed-in one")
    entries = got["accountDocumentLinks"].get("STATEMENT", [])
    if entries is None:
        entries = []
    if not isinstance(entries, list):
        raise ListStopped("an account's statements could not be read")
    files = [(e.get("endpoints") or {}).get("file") for e in entries
             if isinstance(e, dict) and isinstance(e.get("endpoints"), dict)]
    _guard_words([f.rsplit("/", 1)[-1] for f in files if isinstance(f, str)])
    out: List[Statement] = []
    for e in entries:
        if not isinstance(e, dict):
            raise ListStopped("a statement could not be read")
        iso = statement_date(e.get("documentDate"))
        if not iso:
            raise ListStopped("a statement's date is not a calendar date")
        if e.get("type", "STATEMENT") != "STATEMENT":
            raise ListStopped("a statement is not marked as one")
        # The JSON carries the id as a number where the address spells it as
        # text; the same digits are the same account.
        uid = e.get("userAccountId")
        if isinstance(uid, bool) or not isinstance(uid, (str, int)) or str(uid) != str(account_id):
            raise ListStopped("a statement names another account")
        endpoints = e.get("endpoints")
        file = endpoints.get("file") if isinstance(endpoints, dict) else None
        if not file_matches(file, account_id, iso) or not download_url(file):
            raise ListStopped("a statement's address is not one this can read")
        if any(s.date == iso for s in out):
            raise ListStopped("two statements of one account carry one date")
        doc_id = file.rsplit("/", 1)[-1]
        if any(s.doc_id == doc_id for s in out):
            raise ListStopped("two statements of one account carry one id")
        out.append(Statement(iso, doc_id, file))
    return out


def read_links(response) -> Tuple[str, List[Statement]]:
    """The account id and statements of one links answer the page got. An
    answer that is a redirect, 401 or 403, HTML, or not JSON is the bank
    saying the session has ended."""
    if _signed_out_status(response):
        raise SessionExpired("the documents answer was signed out")
    account_id = links_account_id(response.url)
    if not account_id:
        raise ListStopped("a documents answer came from another address")
    _guard_words([account_id])
    try:
        body = intake.body(response)
    except Exception as e:
        raise ListStopped("a documents answer could not be read (%s)" % type(e).__name__)
    if _ctype(response).startswith("text/html") or body.lstrip()[:1] == b"<":
        raise SessionExpired("the documents answer was a page")
    if int(response.status) != 200:
        raise ListStopped("a documents answer was not 200")
    try:
        got = whole_json(json.loads(body.decode("utf-8")))
    except (ValueError, UnicodeDecodeError):
        raise SessionExpired("the documents answer was not JSON")
    return account_id, statements_of(got, account_id)


def _dates(statements: List[Statement]) -> List[str]:
    return sorted(s.date for s in statements)


# ---------------------------------------------------------------------------
# Reading the page. Read only; nothing on the page is changed.
# ---------------------------------------------------------------------------
_STATE_JS = r"""() => {
  const tidy = s => (s || '').replace(/\s+/g, ' ').trim();
  const shown = el => !!el && !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length)
                      && getComputedStyle(el).visibility !== 'hidden';
  const labels = el => [tidy(el.innerText), tidy(el.getAttribute('aria-label')),
                        tidy(el.getAttribute('title'))].filter(Boolean);
  const out = {heading: false, tab: !!document.querySelector('button.edocs-estatements-tab'),
               panels: [], password: !!document.querySelector("input[type='password']")};
  for (const h of document.querySelectorAll('h1, h2, h3'))
    if (/^view statements$/i.test(tidy(h.innerText))) out.heading = true;
  const panels = document.querySelectorAll('div.accordion-panel[role="button"][aria-expanded]');
  panels.forEach((p, i) => {
    const region = p.getAttribute('aria-controls') || '';
    const box = region ? document.getElementById(region) : null;
    const cards = [];
    if (box) for (const c of box.querySelectorAll('div.card.edocs-item-card[aria-label^="Monthly statement for "]'))
      cards.push({label: tidy(c.getAttribute('aria-label')), shown: shown(c),
                  buttons: c.querySelectorAll('button.edocs-download-btn').length});
    out.panels.push({index: i, title: tidy(p.innerText), labels: labels(p),
                     expanded: p.getAttribute('aria-expanded') || '', region: region,
                     cards: cards, shown: shown(p)});
  });
  return out;
}"""

_LABELS_JS = r"""el => [el.innerText, el.getAttribute('aria-label'), el.getAttribute('title')]
  .map(s => (s || '').replace(/\s+/g, ' ').trim()).filter(Boolean)"""


def _read(page) -> dict:
    """What the statements page shows now. A page that cannot be read stops
    the list."""
    try:
        state = page.evaluate(_STATE_JS)
    except Exception as e:
        raise ListStopped("the statements page could not be read (%s)" % type(e).__name__)
    if not isinstance(state, dict):
        raise ListStopped("the statements page could not be read")
    return state


def _pause(page, run: Run, ms: float) -> None:
    """Wait `ms`, never past the run's deadline, asking the deadline before
    and after. A wait the deadline cut short raises DeadlineReached."""
    run.in_time()
    page.wait_for_timeout(run.remaining_ms(ms))
    run.in_time()


def _wait_for(page, run: Run, ready: Callable[[dict], bool], timeout_ms: int) -> Optional[dict]:
    """Read the page until `ready` holds, or None once `timeout_ms` has
    gone. The deadline is asked before the wait, and the session before and
    after every poll."""
    run.in_time()
    waited = 0
    while True:
        check_signed_in(page)
        run.watch.raise_if_signed_out(page)
        state = _read(page)
        if ready(state):
            return state
        if waited >= timeout_ms:
            return None
        _pause(page, run, POLL_MS)
        waited += POLL_MS
        check_signed_in(page)


def _settle(page, run: Run) -> None:
    _pause(page, run, SETTLE_MS)
    check_signed_in(page)
    run.watch.raise_if_signed_out(page)


def _panel(state: dict, i: int) -> dict:
    panels = state.get("panels") or []
    if i >= len(panels):
        raise ListStopped("an account's panel is gone from the page")
    return panels[i]


def _card_dates(panel: dict) -> Optional[List[str]]:
    """The panel's card dates, sorted, or None when a card's label is not a
    date or a card has no single Download PDF."""
    out = []
    for c in panel.get("cards") or []:
        iso = _card_date(c.get("label"))
        if not iso or c.get("buttons") != 1:
            return None
        out.append(iso)
    return sorted(out)


def _ready(state: dict) -> bool:
    return bool(state.get("heading")) and bool(state.get("tab")) and bool(state.get("panels"))


# ---------------------------------------------------------------------------
# Pressing. Every press goes through _press, with one of the two predicates.
# ---------------------------------------------------------------------------

def _labels_of(locator) -> List[str]:
    try:
        labels = locator.evaluate(_LABELS_JS)
    except Exception:
        return []
    return [str(x) for x in labels or [] if str(x or "").strip()]


def _press(page, locator, *, css: str, what: str, guard, step: str, run: Run,
           expect: Optional[str] = None, leave_if_off: bool = False) -> bool:
    """Press one control, once, through the core, after every label it
    carries has passed `guard`, one of PRESS_GUARDS. A control that is not
    exactly one shown element, or a label refused, stops the list and
    nothing is pressed. True once pressed.

    A control the page has turned off is not pressed (pressing.TurnedOff).
    For an account's panel that stops the list, since every statement of
    the account sits behind it. With `leave_if_off`, for a statement's own
    Download PDF, it returns False instead: nothing was pressed, and that
    one statement is left for the next run while the run goes on. Anything
    else the core raises (covered, unreadable) still stops the run."""
    if guard not in PRESS_GUARDS:
        raise ListStopped("a press was asked for with no guard of this app's own")
    run.in_time()
    check_signed_in(page)
    try:
        if locator.count() != 1 or not locator.is_visible():
            raise ListStopped("%s is not one control on the page" % what)
    except ListStopped:
        raise
    except Exception as e:
        raise ListStopped("%s could not be read (%s)" % (what, type(e).__name__))
    labels = _labels_of(locator)
    ok = bool(labels) and all(guard(t) if expect is None else guard(t, expect) for t in labels)
    if not ok:
        raise ListStopped("the guard refused %s" % what)
    try:
        pressing.click(page, locator, css=css, what=what, words=_words(), step=step,
                       timeout=run.cap(pressing.PRESS_MS))
    except pressing.TurnedOff:
        # The press waited out its time for the control to turn on; a run
        # whose budget that wait used up stops here, not at a later step.
        run.in_time()
        if not leave_if_off:
            raise ListStopped("%s is turned off on the page" % what)
        log.info("%s is turned off on the page; nothing was pressed", what)
        return False
    run.in_time()
    check_signed_in(page)
    return True


# ---------------------------------------------------------------------------
# The statements page
# ---------------------------------------------------------------------------

@dataclass
class Opened:
    state: dict
    mark: int


@dataclass
class Bound:
    index: int
    product: str
    account_id: str
    statements: List[Statement]
    region: str


def _open(page, run: Run) -> Opened:
    """Load the statements page afresh, with the context's watch already
    listening, ask the bank whether the session is signed in, and wait for
    the page to be ready: the "View Statements" heading, the STATEMENTS
    tab and at least one account panel. Every panel title is private from
    here on. Nothing is pressed."""
    run.attach(page.context)
    run.in_time()
    mark = run.watch.mark()
    try:
        resp = page.goto(DOCUMENTS_URL, wait_until="domcontentloaded", timeout=run.cap(60000))
        run.in_time()
        if resp is None:
            # A route change inside the app loads nothing, and a panel left
            # open would draw without an answer heard in this load.
            page.reload(wait_until="domcontentloaded", timeout=run.cap(60000))
            run.in_time()
    except DeadlineReached:
        raise
    except Exception as e:
        run.in_time()
        log.info("opening the statements page failed (%s)", type(e).__name__)
        check_signed_in(page)
        raise ListStopped("the statements page did not open")
    check_signed_in(page)
    if not is_documents_url(page.url or ""):
        raise ListStopped("the statements page settled off its own address")
    session_alive(page, run)
    state = _wait_for(page, run, _ready, READY_WAIT_MS)
    if state is None:
        _guard_titles(_read(page))
        raise ListStopped("the statements page did not show its heading, tab and accounts")
    _guard_titles(state)
    return Opened(state, mark)


def _pairing(panels: List[dict], answers: list) -> Optional[dict]:
    """Panel index -> (account id, statements) when each panel opened on
    load matches exactly one answer by its card dates and each answer
    exactly one panel; None otherwise."""
    if len(panels) != len(answers):
        return None
    read = [read_links(r) for r in answers]
    out = {}
    used = set()
    for p in panels:
        dates = _card_dates(p)
        if dates is None:
            return None
        hits = [n for n, (_a, st) in enumerate(read) if _dates(st) == dates]
        if len(hits) != 1:
            return None
        out[p["index"]] = read[hits[0]]
        used.add(hits[0])
    return out if len(used) == len(read) else None


def _bind_loaded(page, run: Run, opened: Opened) -> dict:
    """The panels the page opened by itself, each bound to the one answer
    heard in this load whose dates its cards show. Raises ListStopped when
    the pairing is not unique, or an answer is left unclaimed."""
    expanded = [p for p in opened.state.get("panels") or [] if p.get("expanded") == "true"]
    found = {}

    def ready(state: dict) -> bool:
        now = [p for p in state.get("panels") or [] if p.get("expanded") == "true"]
        if [p["index"] for p in now] != [p["index"] for p in expanded]:
            raise ListStopped("a panel opened or closed by itself")
        pairing = _pairing(now, run.watch.links_since(opened.mark, page))
        if pairing is None:
            return False
        found.update(pairing)
        return True

    if _wait_for(page, run, ready, LIST_WAIT_MS) is None:
        raise ListStopped("the panels open on load could not be told apart by their answers")
    _settle(page, run)
    found.clear()
    if not ready(_read(page)):
        raise ListStopped("another documents answer came after the page settled")
    # No product yet: the title read on load may not have drawn its balance,
    # so the product is taken from the settled title (_from_load).
    return {i: Bound(i, "", acct, st, _panel(opened.state, i).get("region") or "")
            for i, (acct, st) in found.items()}


def _from_load(b: Bound, panel: dict) -> Bound:
    """A panel the page opened by itself, bound in _bind_loaded, given the
    product of its settled title. The settled panel must sit in the region
    it was bound in, or the list stops."""
    if (panel.get("region") or "") != b.region:
        raise ListStopped("an account's panel moved while its title drew")
    return Bound(b.index, product_of(panel.get("title")), b.account_id, b.statements, b.region)


def _expand(page, run: Run, i: int, region: str) -> Bound:
    """Press panel `i` open, once, while it reads aria-expanded="false",
    and bind it to the one answer that press brought. Anything else stops
    the list; a panel is never closed.

    `region` is the region the panel had when the panels were read. A panel
    the page draws late, ahead of this one, moves it one place on, and the
    panel then at `i` is another one. So the panel at `i` must still have
    that region, or the list stops and nothing is pressed. Every title on
    the page is made private before that, a late one among them."""
    now = _read(page)
    _guard_titles(now)
    before = _panel(now, i)
    if not region or (before.get("region") or "") != region:
        raise ListStopped("an account's panel moved before it was pressed")
    if before.get("expanded") != "false":
        raise ListStopped("an account's panel is not closed")
    mark = run.watch.mark()
    _press(page, page.locator(PANEL).nth(i), css=PANEL, what="an account's statements panel",
           guard=is_account_panel, step="open an account's statements", run=run)
    if _wait_for(page, run, lambda s: _panel(s, i).get("expanded") == "true"
                 and len(run.watch.links_since(mark, page)) >= 1, LIST_WAIT_MS) is None:
        raise ListStopped("an account's panel did not open with its documents answer")
    _settle(page, run)
    answers = run.watch.links_since(mark, page)
    if len(answers) != 1:
        raise ListStopped("an account's panel brought %d documents answers" % len(answers))
    account_id, statements = read_links(answers[0])
    want = _dates(statements)
    state = _wait_for(page, run, lambda s: _card_dates(_panel(s, i)) == want, LIST_WAIT_MS)
    if state is None:
        raise ListStopped("an account's cards do not match its documents answer")
    after = _panel(state, i)
    if after.get("title") != before.get("title") or after.get("region") != before.get("region"):
        raise ListStopped("an account's panel changed while it opened")
    if len(run.watch.links_since(mark, page)) != 1:
        raise ListStopped("another documents answer came after the panel opened")
    return Bound(i, product_of(after.get("title")), account_id, statements, after.get("region") or "")


def _rawdocs(b: Bound) -> List[RawDoc]:
    return [RawDoc(title="Bank Statement", account=b.product, date_text=s.date, href="",
                   text="Bank Statement", kind="statement", document_id=s.doc_id,
                   account_id=b.account_id) for s in b.statements]


def _settled_panels(page, run: Run, opened: Opened) -> list:
    """The page's account panels once their titles have finished drawing. A
    title comes in two steps, the balance last, so each is given its time to
    reach the surveyed shape before any is judged, and one still not of that
    shape after the wait is left to the caller, which skips it. Every title
    read here is private before it is returned, a panel drawn late among
    them, and a panel the page hides stops the list."""
    settled = _wait_for(page, run, lambda s: bool(s.get("panels")) and all(
        product_of(p.get("title")) for p in s.get("panels") or []), LIST_WAIT_MS)
    if settled is None:
        # One title never reached the shape: the panels are read once more
        # as they are now, so the ones that did finish drawing are kept.
        settled = _read(page)
    _guard_titles(settled)
    panels = settled.get("panels") or []
    if not all(p.get("shown") for p in panels):
        raise ListStopped("an account's panel is hidden on the page")
    return panels


def _shape(panels: list) -> list:
    return [(p.get("index"), p.get("region") or "", product_of(p.get("title")), bool(p.get("shown")))
            for p in panels]


def _held_still(page, run: Run, panels: list, why: str) -> None:
    """The page settles twice once the panels are walked, and is read after
    each. Both reads must show the panels walked, so they agree with each
    other too, or the list stops with `why`. The wait is two SETTLE_MS in
    all, never past the deadline. A panel the page draws in that time, late
    ones among them, is private before the list stops."""
    for _ in range(2):
        _settle(page, run)
        now = _read(page)
        _guard_titles(now)
        if _shape(now.get("panels") or []) != _shape(panels):
            raise ListStopped(why)


def collect_download_docs(page, run: Optional[Run] = None) -> List[RawDoc]:
    """Every statement of every account panel. Panels the page opened by
    itself are read from the answers heard as it loaded, and each closed one
    is pressed open once. A title not of the surveyed shape is skipped and
    the list is then not called whole. Once the walk is done the page
    settles twice and is read after each (_held_still), and a panel that is
    not one of the panels walked, as one the page drew late, stops the
    list. Raises ListStopped holding what was read, SessionExpired for a
    signed-out session and DeadlineReached."""
    run = run or Run()
    opened = _open(page, run)
    docs: List[RawDoc] = []
    try:
        loaded = _bind_loaded(page, run, opened)
        panels = _settled_panels(page, run, opened)
        skipped = 0
        seen = set()
        for p in panels:
            i = p["index"]
            if not product_of(p.get("title")):
                skipped += 1
                log.info("an account's panel title is not one this app reads; it is skipped")
                continue
            b = _from_load(loaded[i], p) if i in loaded else _expand(page, run, i, p.get("region") or "")
            if b.account_id in seen:
                raise ListStopped("two panels carry one account")
            seen.add(b.account_id)
            docs.extend(_rawdocs(b))
            log.info("%s: %d statement(s)", b.product, len(b.statements))
        _held_still(page, run, panels, "the account panels changed while the list was read")
    except ListStopped as stop:
        raise ListStopped(str(stop), docs)
    if skipped:
        raise ListStopped("an account's panel title could not be read", docs)
    return docs


def goto_documents(page, run: Optional[Run] = None) -> bool:
    """Open the statements page and prove it ready. False when it showed
    the sign-in page or did not open. Nothing is pressed."""
    try:
        _open(page, run or Run())
        return True
    except (SessionExpired, ListStopped, DeadlineReached) as e:
        log.info("the statements page did not open: %s", type(e).__name__)
        return False


def scroll_full_page(page, rounds: int = 0, delay_ms: int = 0) -> None:
    """Nothing to scroll: every statement of an account is one list."""
    return None


def expand_all(page) -> None:
    """Nothing is pressed beyond the two controls in the module docstring."""
    return None


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

@dataclass
class Target:
    region: str
    card: int
    expected: str = field(repr=False)


_REGION_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]*")


def _reach_card(page, run: Run, account_id: str, product: str, document_id: str,
                iso_date: str, trace: Optional[list]) -> Optional[Target]:
    """Open the statements page afresh and find the record's statement: the
    panel of the record's product whose answer names the record's account,
    exactly one statement there with the record's date and document id, and
    exactly one card of that date in that panel. The panels the page opened
    by itself are looked at first, then each closed panel of the product is
    pressed open in turn until the account is found, and no further, so on
    an accordion that keeps one panel open the account's own panel is the
    last one opened. None, with nothing pressed past the panels, when the
    statement is not there. ListStopped when the page does not hold still
    while it is read."""
    opened = _open(page, run)
    loaded = _bind_loaded(page, run, opened)
    panels = _settled_panels(page, run, opened)
    mine = [p for p in panels if product_of(p.get("title")) == product]
    b = None
    for p in [p for p in mine if p["index"] in loaded] + [p for p in mine if p["index"] not in loaded]:
        got = _from_load(loaded[p["index"]], p) if p["index"] in loaded \
            else _expand(page, run, p["index"], p.get("region") or "")
        if got.account_id == account_id:
            b = got
            break
    if b is None:
        # The account is called not on the page only when the panels held
        # still while they were walked. A panel drawn late may be the
        # account's own, so the run stops rather than send it to review.
        _held_still(page, run, panels, "the account panels changed while the account was sought")
        if trace is not None:
            trace.append({"note": "the account is not on the page"})
        return None
    st = [s for s in b.statements if s.date == iso_date and s.doc_id == document_id]
    if len(st) != 1:
        if trace is not None:
            trace.append({"note": "no single statement matches the record", "matches": len(st)})
        return None
    # Every title drawn now is private before the card's Download PDF is
    # pressed, a panel drawn late among them.
    now = _read(page)
    _guard_titles(now)
    panel = _panel(now, b.index)
    if panel.get("expanded") != "true" or (panel.get("region") or "") != b.region:
        raise ListStopped("the account's panel closed or moved before its card was read")
    cards = [n for n, c in enumerate(panel.get("cards") or [])
             if _card_date(c.get("label")) == iso_date]
    if len(cards) != 1 or not _REGION_RE.fullmatch(b.region or ""):
        if trace is not None:
            trace.append({"note": "no single card matches the record", "matches": len(cards)})
        return None
    expected = download_url(st[0].file)
    if not expected:
        return None
    return Target(b.region, cards[0], expected)


def _unfinished(dl_dir) -> bool:
    try:
        return any(p.name.lower().endswith((".crdownload", ".part", ".download", ".tmp"))
                   for p in Path(dl_dir).iterdir())
    except OSError:
        return False


def _cancel_all(downloads: list) -> None:
    for dl in downloads:
        try:
            dl.cancel()
        except Exception:
            pass


def _stop(said: str, reason: str):
    return pressing.no_answer("save the statement", reason, said)


def _close(pages: list) -> List[str]:
    """Close each page this press made that is still open, and say where
    each was. Only pages whose opener is the run's own page are ever here."""
    where = []
    for p in pages:
        try:
            if p.is_closed():
                continue
        except Exception:
            pass
        try:
            where.append(p.url or "")
        except Exception:
            where.append("")
        try:
            p.close()
        except Exception:
            pass
    return where


# Where a popup that became a download is left, read as Playwright reads it.
# MEASURED 2026-10-12 in headless Chromium through Playwright 1.6x: the
# popup Download PDF opens stays open, and its url reads "" (its navigation
# became the download and never committed), not "about:blank". Both are a
# page that went nowhere. A url that cannot be read is neither.
BLANK_URLS = ("about:blank", "")


def _closed(made: list) -> bool:
    """Close the press's one popup when it is still open, and confirm it is
    closed. False when it would not close or cannot be asked."""
    for p in made:
        try:
            if not p.is_closed():
                p.close()
            if not p.is_closed():
                return False
        except Exception:
            return False
    return True


def _opener(p):
    try:
        return p.opener()
    except Exception:
        return None


def _navigation(response) -> bool:
    """A document answer a page went to, not one of its inner frames'. A
    popup's first answer can come before Playwright knows its page, and its
    frame cannot be read then; that still counts as a navigation."""
    try:
        if not response.request.is_navigation_request():
            return False
    except Exception:
        return False
    try:
        return response.frame.parent_frame is None
    except Exception:
        return True


def _to_sign_in(url: str) -> bool:
    return any(m in (url or "").lower() for m in LOGIN_URL_MARKERS)


def _catch_statement(page, run: Run, dl_dir, target: Target, iso_date: str, out_path: Path,
                     trace: Optional[list]) -> Optional[bool]:
    """Press the bound card's Download PDF once and take the one download it
    brings, through the core.

    The bank's button opens a popup that becomes the download and closes
    itself; in Chromium the download is raised on the run's own page and
    the popup's one answer comes before Playwright knows the popup, with a
    frame that cannot be read. So what is heard is: downloads raised on the
    run's page or on a page whose opener is the run's page, and, on the
    context, every navigation answer in the window that is the run's page's,
    such a page's, or one whose page cannot be told. An answer known to
    come from another tab, and that tab's pages, are left alone; an answer
    that cannot be told apart counts, so another tab can make this stop but
    never makes it take the wrong file. Exactly one of them must have gone to the
    record's own statement address, answered with no sign-out, and the one
    download must come from that address too. A download already on its
    way, none in time, a second one, a page that went anywhere else (closed
    by itself or not), a page the press made left open, or a file that is
    not a PDF stops the run: nothing more is pressed for this or any later
    statement. Only pages this press made are ever closed. Every wait is
    capped by the run's deadline.

    None when the page has turned the Download PDF off: nothing was
    pressed, nothing is waited for, and the statement is left for the next
    run (pressing.TurnedOff)."""
    out_path = Path(out_path)
    run.attach(page.context)
    css = "#%s %s" % (target.region, CARD)
    button = page.locator(css).nth(target.card).locator(DOWNLOAD_BUTTON)
    downloads: list = []
    made: list = []
    navs: list = []          # where the run's page and its popups went
    armed = [False]

    def on_download(dl):
        downloads.append(dl)

    def on_nav(response):
        if not armed[0] or not _navigation(response):
            return
        origin = _origin(response)
        if origin is None or origin is page or any(origin is p for p in made):
            navs.append(response)

    def on_page(p):
        if _opener(p) is not page:
            return  # another tab's popup: not this run's to hear or close
        made.append(p)
        try:
            p.on("download", on_download)
        except Exception:
            pass

    def give_up():
        _cancel_all(downloads)
        _close(made)

    page.on("download", on_download)
    page.context.on("response", on_nav)
    page.context.on("page", on_page)
    before = _snapshot(dl_dir)
    try:
        if _unfinished(dl_dir) or downloads:
            raise _stop("A download was still arriving before this statement was saved, "
                        "so nothing was pressed.", "a download was pending")
        armed[0] = True
        if not _press(page, button, css=DOWNLOAD_BUTTON, what="the statement's Download PDF",
                      guard=is_download_button, expect=iso_date, step="save the statement",
                      run=run, leave_if_off=True):
            if trace is not None:
                trace.append({"note": "the statement's control was turned off"})
            return None
        waited = 0
        while not downloads:
            check_signed_in(page)
            run.watch.raise_if_signed_out(page)
            if any(_signed_out_status(r) or _to_sign_in(r.url) for r in navs):
                give_up()
                raise SessionExpired("the statement's address answered as signed out")
            if waited >= DOWNLOAD_WAIT_MS:
                gone = _close(made)
                if any(_to_sign_in(u) for u in gone):
                    raise SessionExpired("the statement's popup landed on the sign-in page")
                if trace is not None:
                    trace.append({"note": "no download came"})
                raise _stop("Download PDF was pressed and no download came.", "no download came")
            _pause(page, run, POLL_MS)
            waited += POLL_MS
        waited = 0
        while waited < SECOND_DOWNLOAD_WAIT_MS:
            _pause(page, run, POLL_MS)
            waited += POLL_MS
        check_signed_in(page)
        went = [r.url or "" for r in navs]
        if any(_signed_out_status(r) or _ctype(r).startswith("text/html") or _to_sign_in(r.url)
               for r in navs):
            give_up()
            raise SessionExpired("the statement's address answered as signed out")
        if len(made) > 1:
            give_up()
            raise _stop("Download PDF opened more than one page, so nothing was taken.",
                        "the press opened more than one page")
        ended = []
        for p in made:
            try:
                ended.append(p.url)
            except Exception:
                give_up()
                raise _stop("Where the page the bank opened went could not be read, so the "
                            "download was not taken.", "a page the press opened could not be read")
        if any(_to_sign_in(u) for u in ended):
            give_up()
            raise SessionExpired("the statement's popup landed on the sign-in page")
        if len(downloads) != 1:
            give_up()
            raise _stop("More than one download came after one Download PDF, so none was taken.",
                        "more than one download came")
        dl = downloads[0]
        if (getattr(dl, "url", "") or "") != target.expected or went != [target.expected] \
                or any(u != target.expected and u not in BLANK_URLS for u in ended):
            give_up()
            raise _stop("The download did not come from this statement's own address alone, "
                        "so it was not taken.", "the download came from elsewhere")
        if not _closed(made):
            _cancel_all(downloads)
            raise _stop("The page the bank opened for the statement could not be closed, so the "
                        "download was not taken.", "a page the press opened stayed open")
        run.in_time()
        how = _take_download(dl, dl_dir, before, out_path)
        if run.past_deadline():
            # Saving ran past the fence: what it wrote is not kept.
            try:
                out_path.unlink()
            except OSError:
                pass
            raise DeadlineReached("saving the statement ran past the run's time")
        if trace is not None:
            trace.append({"note": "download taken" if how else "download not taken", "how": how})
        if not how or not out_path.exists() or out_path.read_bytes()[:5] != b"%PDF-":
            try:
                out_path.unlink()
            except OSError:
                pass
            raise _stop("The download was not a PDF, so it was not kept.", "the download was not a pdf")
        return True
    except DeadlineReached:
        give_up()
        raise
    finally:
        armed[0] = False
        for target_, name, fn in ((page, "download", on_download), (page.context, "response", on_nav),
                                  (page.context, "page", on_page)):
            try:
                target_.remove_listener(name, fn)
            except Exception:
                pass
        try:
            _clear_copies(dl_dir, before, out_path)
        except Exception:
            pass


_DOCUMENT_ID_RE = re.compile(_DOC_ID_RE)


def download_statement(page, run: Run, dl_dir, out_path, *, account_id: str, product: str,
                       document_id: str, iso_date: str,
                       trace: Optional[list] = None) -> Optional[bool]:
    """Save the statement discovery recorded. The statements page is opened
    afresh, the record's account found by its own answer, the statement
    bound to exactly one answer entry and one card, and only then is that
    card's Download PDF pressed. False, with nothing pressed on a card, when
    the statement is not there. None when the card's Download PDF is turned
    off on the page: nothing was pressed on it, and the statement is left
    for the next run. A page that stops the list on the way (it does not
    open, the session probe fails, a panel is turned off, hidden or changes)
    stops the run with pressing.Stop, since the next statement would meet
    the same page. SessionExpired, DeadlineReached and every other stop of
    the run propagate."""
    out_path = Path(out_path)
    if not (account_id and product and _DOCUMENT_ID_RE.fullmatch(document_id or "")
            and _no_dots(document_id) and statement_date(iso_date) == iso_date):
        if trace is not None:
            trace.append({"note": "the record does not name one statement"})
        return False
    try:
        target = _reach_card(page, run, account_id, product, document_id, iso_date, trace)
    except ListStopped as stop:
        log.info("the list stopped while looking for the statement dated %s: %s", iso_date, stop)
        if trace is not None:
            trace.append({"note": "the list stopped"})
        raise _page_stopped(stop)
    if target is None:
        return False
    try:
        return _catch_statement(page, run, dl_dir, target, iso_date, out_path, trace)
    except ListStopped as stop:
        log.info("the statement dated %s was not saved: %s", iso_date, stop)
        if trace is not None:
            trace.append({"note": "the card's control was not pressed"})
        raise _page_stopped(stop)


def _page_stopped(stop: ListStopped) -> pressing.Stop:
    """A stop of the statements page while a statement was sought, as a stop
    of the run that leaves the list unread, so the panel offers a run that
    reads it first rather than Continue, which would meet the same page
    (#124). Its words are this app's own, never the page's. A panel may
    have been pressed on the way, so it counts as a stop after a press."""
    return pressing.Stop("find the statement", "the statements page stopped", [
        "The statements page stopped before this statement was saved, since %s." % stop,
        "Nothing more was pressed, and the run stops here rather than meet the same page "
        "for the next statement."], after_a_press=True, list_unread=True)


def record_hash(account_id: str, document_id: str) -> str:
    """A stable, non-reversible name for (account id, document id), the
    record's identity, which itself is never output."""
    return hashlib.sha256(("%s\0%s" % (account_id or "", document_id or "")).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Diagnose. Reads only, presses nothing. No screenshot.
# ---------------------------------------------------------------------------

def collect_documents(page) -> List[RawDoc]:
    """The statement cards drawn now, by date only; nothing that names an
    account."""
    try:
        state = _read(page)
    except (ListStopped, SessionExpired):
        return []
    out = []
    for p in state.get("panels") or []:
        for c in p.get("cards") or []:
            iso = _card_date(c.get("label")) or ""
            out.append(RawDoc(title="Statement card", date_text=iso, text="statement card",
                              row_index=len(out)))
    return out


def survey(page, dwell_ms: int = 4000, max_follow: int = 0) -> dict:
    """What the signed-in page looks like, by counts, without pressing or
    downloading anything. No label of the page's own leaves here."""
    page.wait_for_timeout(dwell_ms)
    try:
        state = _read(page)
    except (ListStopped, SessionExpired):
        return {"pages": [{"read": False}]}
    panels = state.get("panels") or []
    return {"pages": [{
        "read": True, "heading": bool(state.get("heading")), "tab": bool(state.get("tab")),
        "panels": len(panels),
        "panels_open": sum(1 for p in panels if p.get("expanded") == "true"),
        "panel_titles_readable": sum(1 for p in panels if product_of(p.get("title"))),
        "cards": sum(len(p.get("cards") or []) for p in panels),
    }]}
