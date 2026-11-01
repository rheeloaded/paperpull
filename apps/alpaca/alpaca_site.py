"""ALL Alpaca documents-page selectors, URLs and page behavior live here.

When Alpaca changes its documents page, repair this file only.

STATUS: built from the account owner's survey of a signed-in Live account
on 2026-10-12 (one Download pressed by hand), then run whole on that
account the same day: Discover listed 42 documents and kept 22, and Pilot
and Run All saved all 22.

WHAT THE SURVEY ESTABLISHED
  * The page is https://app.alpaca.markets/account/documents, a route of the
    dashboard SPA, opened here by its address. On a Paper account it
    silently redirects to /dashboard/overview, so a Paper account never shows
    it. One sign-in holds a Paper and a Live account and the app opens on
    whichever was chosen last. The account switcher's button,
    [data-testid=account-switcher-button], reads "<name> Paper - <id>" on
    Paper.
  * The SPA authorizes its API with a bearer token it holds in memory, not a
    cookie, so nothing here can ask the API itself. Opening the page makes
    the page GET
        /api/v1/accounts/<account uuid>/documents?start=YYYY-MM-DD&end=YYYY-MM-DD
    whose answer is the whole list for that window, a JSON array of {id,
    name, type, sub_type, date}. That answer is listened for, never asked
    for. The page picks the window itself (the survey's started three years
    back), so the list is called whole only when it reaches far enough
    back (reaches_back).
  * The table draws that list ten rows a page, "Date | Document Type |
    Download", the type cell being the list's own type enum verbatim, with
    Previous / page numbers / Next buttons under it. A day can hold a
    trade_confirmation and its trade_confirmation_json twin.
  * The row's last cell is a <p> reading "Download", no link. Pressing it
    makes the page GET .../documents/<document uuid>/url, whose JSON {id,
    url} is a presigned link on s3.amazonaws.com under /prod.alpaca.markets/
    (the account number is in its path), and the browser downloads the PDF
    under the account number as its name.

THE TWO PRESSES. Nothing else is ever pressed, and both go through one
place, _press, which checks the session, the deadline and the Live account,
reads every label the control carries, asks this module's own predicate,
and only then hands the press to the core (pressing.click):
  1. the list's "Next" button (is_next_control), to read or reach a page
  2. a bound row's "Download" (is_download_control), once, under
     expect_download and expect_response for that document's own link
A control the page has turned off is not pressed (pressing.TurnedOff), and
each call says what that means: a turned off Next stops the list
(ListStopped), and a turned off Download leaves that one document for the
next run (DocumentTurnedOff), recorded nowhere, while the run goes on.
Nothing here opens the account switcher, the "Filters" button, a menu or a
dialog, types, scrolls or selects.

SAFETY (a brokerage account that can trade, transfer and deposit): this
module is strictly READ-ONLY. is_safe_control denies by default: the
blocklist and the core's settings and sign-in guards refuse first, and then
only the whole labels "Download", "Next", "Previous" and a page number pass.

LIVE ONLY: before navigating, after it, and before every press, the switcher
must be one readable, shown button whose text holds no "Paper", the Paper
banner must be absent, and the page must be exactly /account/documents with
its one table. Otherwise the run stops (NotLive) and nothing is pressed.

PRIVACY: the switcher's text (the account's name and number), the account
uuid in the list's address, every document uuid, the account number in a
link's path and the download's suggested name are registered as private
words as soon as they are read. None of them, the link, a response body or
an address with its query is ever logged, said or written. Only the list and
link calls are ever listened to. /details, /owners, /billing, authx, cognito,
unleash and sentry answers are never read.

SIGNED OUT: a sign-in address, authx, a password field, a 401 or 403 on the
list or link call, or an answer to either that is not the JSON it should be
raises SessionExpired, checked before and after every wait and press. The
run saves, says so and stops. Nothing is recorded for review.

KNOWN CEILINGS (ponytail: left until a live run shows otherwise)
  * Tax forms are deferred: no tax_* or 1099 type has been seen, so they are
    counted and skipped, never pressed.
  * Two documents of one kept type on one date are counted and not saved:
    a row shows only its date and type, so it could not be bound to one of
    them. The rest of the list goes on.
  * An account older than the page's window, with no start date of the
    run's own inside it, stops the list (reaches_back). Whether the page's
    Filters reach further back has not been seen.
  * An application reissued inside the window, on an account with nothing
    listed before the reissue, passes for the account's first application,
    so documents older than the window would go unnoticed. No list can tell
    the two apart, and a reissue has not been seen.
  * The table's markup beyond what the survey saw (one table, rows in one
    tbody, three cells) is assumed, and anything else stops the list.
"""
from __future__ import annotations

import logging
import re
import shutil
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import date as _date, timedelta
from pathlib import Path
from typing import Callable, List, Optional, Tuple
from urllib.parse import parse_qs, urlsplit

from paperpull_core import intake, pressing
from paperpull_core.controls import SETTINGS_CONTROL_RE, AUTH_CONTROL_RE
from paperpull_core.redact import private_words, redact, set_private_words  # noqa: F401  (re-exported)
from paperpull_core.urls import is_safe_url as _host_allows
from paperpull_core.dates import last_day as _last_day
from paperpull_core.dates import checked as _checked_date
# re-exported: the docs module calls it as site.set_download_dir
from paperpull_core.capture import set_download_dir  # noqa: F401
from paperpull_core.capture import snapshot as _snapshot
from paperpull_core.capture import take_download as _take_download
from paperpull_core.capture import clear_copies as _clear_copies
from paperpull_core.words import words_for as _words_for
from paperpull_core.characters import whole_json

log = logging.getLogger("alpaca_docs.site")


def _words():
    """This app's own words for paperpull_core.words."""
    return _words_for("Alpaca", sys.modules[__name__])


# ---------------------------------------------------------------------------
# Addresses
# ---------------------------------------------------------------------------
HOST = "app.alpaca.markets"
BASE = "https://" + HOST
DOCUMENTS_PATH = "/account/documents"
DOCUMENTS_URL = BASE + DOCUMENTS_PATH
LOGIN_URL = BASE + "/account/login"
URLS = {
    "home": BASE + "/",
    "login": LOGIN_URL,
    "documents": DOCUMENTS_URL,
    "statements": DOCUMENTS_URL,
}

LOGIN_URL_MARKERS = ["/account/login", "/login", "authx.alpaca.markets", "/logout"]

# The one host a document comes from, and the bucket's folder on it.
DOWNLOAD_HOST = "s3.amazonaws.com"
DOWNLOAD_PREFIX = "/prod.alpaca.markets/"
AMZ_FIELDS = ("X-Amz-Algorithm", "X-Amz-Credential", "X-Amz-Date", "X-Amz-Expires",
              "X-Amz-Signature", "X-Amz-SignedHeaders")

_UUID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
UUID_RE = re.compile(_UUID)
LIST_PATH_RE = re.compile(r"/api/v1/accounts/(%s)/documents" % _UUID)
URL_PATH_RE = re.compile(r"/api/v1/accounts/(%s)/documents/(%s)/url" % (_UUID, _UUID))

# ---------------------------------------------------------------------------
# HARD SAFETY GUARD
# ---------------------------------------------------------------------------
FORBIDDEN_CONTROL_RE = re.compile(
    r"\b(buy|sell|cancel\w*|orders?|trades?|trading|transfers?|deposits?|withdraw\w*|"
    r"add\s+funds|wallets?|funds?|configure|regenerate|delete\w*|api\s*keys?|keys?|"
    r"connect\w*|plans?|upgrade\w*|subscri\w*|switch\w*|paper|profile|settings?|"
    r"save|edit\w*|accept\w*|agree\w*|enable\w*|disable\w*|sign\s*out|log\s*out|logout|"
    r"chat|intercom|liquidate|close)\b", re.I)

# The whole labels a control may carry, and nothing else.
SAFE_LABEL_RE = re.compile(r"download|next|previous|\d{1,3}", re.I)

SECURITY_CHALLENGE_MARKERS = [
    "enter the code we sent", "enter your verification code", "verification code",
    "one-time", "one time passcode", "security code", "we sent a code",
    "two-factor", "two-step", "authenticator", "confirm your identity",
    "verify your identity", "are you a robot", "captcha",
    "your session has expired", "please log in again",
]

RATE_LIMIT_MARKERS = [
    "too many requests", "rate limit", "try again later",
    "temporarily unavailable", "http error 429",
]

# Selectors, also what --diagnose counts.
SWITCHER = '[data-testid="account-switcher-button"]'
TABLE = "table"
ROW = "table tbody tr"
ROW_CONTROL = "table tbody tr td:last-child p"
PAGER_BUTTON = "button"
FALLBACK = {
    "doc_row": ROW,
    "doc_link": ROW_CONTROL,
    "download_control": ROW_CONTROL,
    "page_ready": SWITCHER + ", " + TABLE,
    "account_select": SWITCHER,
}

# The switcher reads "<name> Paper - <id>" on Paper. Any "paper" in it at
# all is refused, as a word or inside one ("PaperTrading", "paper_account"):
# a Live account whose name holds the letters is refused too, which is the
# safe way to be wrong.
def reads_paper(text) -> bool:
    """Whether `text` holds "paper" anywhere, in any case."""
    return "paper" in str(text or "").casefold()
PAPER_BANNER = "you are on paper trading"

# How long each wait is given.
READY_WAIT_MS = 30000
LIST_WAIT_MS = 30000
ROWS_WAIT_MS = 10000
SETTLE_MS = 1500
URL_WAIT_MS = 30000
DOWNLOAD_WAIT_MS = 60000
SECOND_DOWNLOAD_WAIT_MS = 2000
# How long a run's end waits for a download its capture stopped waiting for.
LATE_DOWNLOAD_WAIT_MS = 10000
POLL_MS = 250
PAGE_SIZE = 10
# A run stops pressing this long after it first opened the documents page.
# No sign-out was seen in the survey, so this is a conservative bound.
DEADLINE_S = 20 * 60

# What each kept type is called, and the types read but never taken.
TITLES = {
    "account_statement": "Brokerage Statement",
    "crypto_account_statement": "Crypto Statement",
    "trade_confirmation": "Trade Confirmation",
}
SKIPPED_TYPES = {"trade_confirmation_json": "twins", "account_application": "applications"}
# What read_list counts and does not keep, by kind.
COUNTED = ("twins", "applications", "tax", "other", "alike")

# ---------------------------------------------------------------------------
# Date parsing (the orchestrator's period reading, unchanged in shape)
# ---------------------------------------------------------------------------
DATE_PATTERNS = [
    (re.compile(r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
                r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|"
                r"Dec(?:ember)?)\.?\s+(\d{1,2}),?\s+(\d{4})", re.I), "mdY"),
    (re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b"), "mdy_slash"),
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


def calendar_date(value) -> Optional[str]:
    """A YYYY-MM-DD string naming a day that exists, as it is, or None.
    Nothing else is read as a date."""
    if not isinstance(value, str):
        return None
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", value.strip())
    if not m:
        return None
    try:
        return _date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Session / safety
# ---------------------------------------------------------------------------

class SessionExpired(Exception):
    """Alpaca answered as a signed-out session: its sign-in page, a password
    field, a 401 or 403 on the list or link call, or an answer to either
    that is not the JSON it should be. The run stops for the account
    holder."""


class NotLive(Exception):
    """The page is not the Live account's documents page: the switcher reads
    Paper or cannot be read, the Paper banner shows, or the page settled
    anywhere but /account/documents with its table. Nothing is pressed and
    the run stops for the account holder to choose Live themselves."""


class DeadlineReached(Exception):
    """The run has been at Alpaca for DEADLINE_S since it first opened the
    documents page, so it presses nothing more."""


class DocumentTurnedOff(Exception):
    """The document's own Download is turned off on the page, so nothing was
    pressed for it and nothing it brings can come. The document is left for
    the next run, with nothing recorded against it, and the run goes on."""


class ListStopped(Exception):
    """The list has a part this could not read, so what was read is not all
    of it. `docs` holds what was read before it stopped. Its words are this
    module's own, never the page's."""

    def __init__(self, why: str, docs=None):
        super().__init__(why)
        self.docs = list(docs or [])


class WindowNotWhole(ListStopped):
    """The window the page asked the list for starts after it ends, ended
    before yesterday, or is not two calendar dates (window_whole)."""

    def __init__(self):
        super().__init__("the window the list was asked for does not run from its start to yesterday or later")


class ListTooShort(ListStopped):
    """The list does not reach back far enough to be called whole
    (reaches_back). `start` is where its window begins, an ISO date, or ""
    when the list's address did not say."""

    def __init__(self, start: str):
        super().__init__("the list starts at %s and holds no account application"
                         % (start or "a date it did not give"))
        self.start = start


def looks_signed_out(page) -> bool:
    """The sign-in page by its address or a password field."""
    url = (page.url or "").lower()
    if any(m in url for m in LOGIN_URL_MARKERS):
        return True
    try:
        if page.locator("input[type='password']").count() > 0:
            return True
    except Exception:
        pass
    return False


def check_signed_in(page) -> None:
    """Raise SessionExpired when the page shows Alpaca signing the session
    out. Asked before and after every wait and every press."""
    if looks_signed_out(page):
        raise SessionExpired("Alpaca showed its sign-in page")


def detect_security_challenge(page) -> Optional[str]:
    """Names the passcode, CAPTCHA or throttling prompt on screen, or None.
    A page that shows a document row is not a challenge."""
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


def _tidy(name) -> str:
    return re.sub(r"\s+", " ", str(name or "")).strip()


def _refused(name: str) -> bool:
    return bool(FORBIDDEN_CONTROL_RE.search(name) or SETTINGS_CONTROL_RE.search(name)
                or AUTH_CONTROL_RE.search(name))


def is_safe_control(name: str) -> bool:
    """Deny by default: an unreadable label is refused, then this app's
    blocklist, then the shared core guards, and only then the whole labels
    "Download", "Next", "Previous" and a page number."""
    name = _tidy(name)
    if not name or _refused(name):
        return False
    return bool(SAFE_LABEL_RE.fullmatch(name))


def is_download_control(label: str) -> bool:
    """A row's "Download" and nothing else."""
    label = _tidy(label)
    return is_safe_control(label) and label.lower() == "download"


def is_next_control(label: str) -> bool:
    """The list's "Next" and nothing else."""
    label = _tidy(label)
    return is_safe_control(label) and label.lower() == "next"


PRESS_GUARDS = (is_download_control, is_next_control)


# ---------------------------------------------------------------------------
# Hosts and calls. Exact, parsed, no subdomain wildcard.
# ---------------------------------------------------------------------------
ALLOWED_HOSTS = {HOST}


def is_safe_url(url: str) -> bool:
    """True only for an https URL on exactly app.alpaca.markets."""
    return _host_allows(url, ALLOWED_HOSTS, subdomains=False)


def _parts(url: str):
    try:
        return urlsplit(url or "")
    except ValueError:
        return None


def is_documents_url(url: str) -> bool:
    """The documents page itself: app.alpaca.markets/account/documents,
    exactly, with no query and no fragment."""
    parts = _parts(url)
    return bool(parts) and is_safe_url(url) and parts.path == DOCUMENTS_PATH \
        and not parts.query and not parts.fragment


def is_list_url(url: str) -> bool:
    """The documents list call, exactly: its path, and a query of start and
    end, once each, each a calendar date, and nothing else."""
    parts = _parts(url)
    if not parts or not is_safe_url(url) or parts.fragment or not LIST_PATH_RE.fullmatch(parts.path):
        return False
    try:
        query = parse_qs(parts.query, keep_blank_values=True, strict_parsing=True)
    except ValueError:
        return False
    return set(query) == {"start", "end"} and all(
        len(query[k]) == 1 and calendar_date(query[k][0]) == query[k][0] for k in ("start", "end"))


def is_link_url(url: str, document_id: Optional[str] = None) -> bool:
    """A document's link call, exactly: its path with no query, for
    `document_id` when one is given."""
    parts = _parts(url)
    if not parts or not is_safe_url(url) or parts.query or parts.fragment:
        return False
    m = URL_PATH_RE.fullmatch(parts.path)
    if not m:
        return False
    return document_id is None or m.group(2).lower() == str(document_id).lower()


def is_census_url(url: str) -> bool:
    """What the run's census of calls may describe: the list and link calls
    only. Every other answer on the host, the account's details, owners and
    billing among them, is never read."""
    return is_list_url(url) or is_link_url(url)


def _method(response) -> str:
    try:
        return str(response.request.method or "").upper()
    except Exception:
        return ""


def is_list_response(response) -> bool:
    try:
        return _method(response) == "GET" and is_list_url(response.url)
    except Exception:
        return False


def is_link_response(response, document_id: Optional[str] = None) -> bool:
    try:
        return _method(response) == "GET" and is_link_url(response.url, document_id)
    except Exception:
        return False


def is_download_url(url: str) -> bool:
    """A presigned link to a document in Alpaca's bucket: https, exactly
    s3.amazonaws.com with no user, password or port, no fragment, a path
    under /prod.alpaca.markets/, and each X-Amz field of the signature once.
    Never logged, stored or said."""
    if not isinstance(url, str) or "#" in url or "\\" in url:
        return False
    parts = _parts(url)
    if not parts or parts.scheme != "https" or parts.netloc.lower() != DOWNLOAD_HOST:
        return False
    try:
        if parts.username or parts.password or parts.port is not None:
            return False
    except ValueError:
        return False
    path = parts.path
    if not path.startswith(DOWNLOAD_PREFIX) or len(path) <= len(DOWNLOAD_PREFIX) \
            or "/../" in path or "/./" in path or "//" in path[1:]:
        return False
    try:
        query = parse_qs(parts.query, keep_blank_values=True, strict_parsing=True)
    except ValueError:
        return False
    return all(len(query.get(f, [])) == 1 and query[f][0] for f in AMZ_FIELDS)


# ---------------------------------------------------------------------------
# Private words
# ---------------------------------------------------------------------------

def _guard(words) -> None:
    """Register `words` as private before anything can log or raise them."""
    have = set(private_words())
    add = [str(w) for w in words if w and str(w) not in have]
    if add:
        set_private_words(private_words() + add)


def guard_switcher(text: str) -> None:
    """The switcher's text names the account and its number: the whole of
    it, each part either side of its dash, and every run of letters and
    digits holding a digit."""
    text = _tidy(text)
    if not text:
        return
    words = [text] + [p.strip() for p in re.split(r"\s+[-‐-―]\s+", text)]
    words += re.findall(r"[A-Za-z0-9]*\d[A-Za-z0-9]*", text)
    _guard(w for w in words if len(w) >= 3)


def guard_link(url: str) -> None:
    """A link's path carries the account number. Each of its parts that
    holds a digit is private."""
    parts = _parts(url)
    if not parts:
        return
    _guard(seg for seg in re.split(r"[/.]", parts.path) if re.search(r"\d", seg) and len(seg) >= 3)


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------

class Run:
    """What one run carries between documents: when it first opened the
    documents page, for the deadline, how many listed documents were
    skipped, by kind, and the downloads the run's tab raised. The App owns
    one, and closes it as it lets go of the tab (close).

    The browser saves into one folder of the app's own, .alpaca-downloads,
    which is kept and never emptied, and nothing in it is removed by its
    name or a pattern. The run listens to its tab's downloads until it
    closes, and a download is the run's only when it is bound to one of its
    own presses:
      * it came inside that press's window, from just before the Download
        was pressed to the end of the settle after it, once a press may
        have reached the page, it was the only download that came there,
        and it came from exactly the link Alpaca handed that press (one
        from anywhere else is not the press's: it is left as it is and the
        run stops), or
      * the press got no download in its window, the link Alpaca handed it
        is known, and it came by the run's end from exactly that link.
    A bound download that was not taken (refused) is canceled, the file it
    wrote is discarded only where the core can tell it is that download's
    (capture.take_download, then capture.clear_copies, which removes only
    files arrived since that press's snapshot and byte for byte the same as
    what was discarded), and its own copy deleted (Download.delete).

    Any other download is not the run's: one that came outside every
    press's window is counted (unbound) and left as it is, never canceled,
    discarded or deleted, and two that came in one window stop the run as
    one it cannot tell apart, with nothing taken and none touched.

    The limits, which every app here that takes downloads shares: a file a
    refused or late download left that no press can be bound to (two in a
    window, a late one from no known link, or one that began after the run
    stopped listening) stays in the folder for the person to remove."""

    def __init__(self, clock: Callable[[], float] = time.monotonic, limit_s: float = DEADLINE_S):
        self.clock = clock
        self.limit_s = limit_s
        self.first_navigation: Optional[float] = None
        self.counts: dict = {}
        # The run's own start date (--start-date or default_start_date), as
        # an ISO date, or None. The list must reach back to it (reaches_back).
        self.floor: Optional[str] = None
        self._watched: list = []
        self.dl_dir: Optional[Path] = None
        # What was in the folder as the last press was made.
        self.before = None
        # The downloads of the press window open now, or None between them.
        self.window: Optional[list] = None
        # Downloads that came outside every press's window, never touched.
        self.unbound = 0
        # A press whose download had not come when its capture stopped
        # waiting, and the link Alpaca handed it: a download from exactly
        # that link, by the run's end, is that press's.
        self.owed_link: Optional[str] = None
        self.late: list = []

    def watch(self, page, dl_dir) -> None:
        """Hear this tab's downloads until the run closes."""
        self.dl_dir = Path(dl_dir)
        if any(p is page for p in self._watched):
            return
        page.on("download", self._on_download)
        self._watched.append(page)

    def _on_download(self, dl) -> None:
        if self.window is not None:
            self.window.append(dl)
            return
        if self.owed_link is not None:
            try:
                url = str(dl.url or "")
            except Exception:
                url = ""
            if url == self.owed_link:
                self.owed_link = None
                self.late.append(dl)
                return
        self.unbound += 1
        log.info("a download the run did not press for came on its tab, and is left as it is")

    def open_window(self) -> None:
        self.window = []

    def close_window(self) -> list:
        came, self.window = list(self.window or []), None
        return came

    def discard(self, dl) -> int:
        """A download bound to a press of the run's and not taken: cancel
        it, discard the file the core can tell is its own, and delete its
        own copy. Says how many files went from the folder."""
        try:
            name = str(dl.suggested_filename or "")
        except Exception:
            name = ""
        _guard([name, Path(name).stem])
        try:
            dl.cancel()
        except Exception:
            pass
        gone = 0
        if self.dl_dir is not None and self.before is not None:
            gone = _discard(dl, self.dl_dir, self.before)
        # Deleting waits until the download has finished, so it waits only
        # for the cancel to land (intake.discard).
        intake.discard(dl)
        if gone:
            log.info("discarded %d file(s) of a download that was not taken", gone)
        return gone

    def close(self) -> int:
        """As the app lets go of the tab: when a press is owed its download,
        wait the bounded time for it and discard it if it comes from that
        press's link, then stop listening. Nothing else is touched. Says
        how many files went from the folder."""
        if self.owed_link is not None:
            for page in self._watched:
                try:
                    if not page.is_closed():
                        page.wait_for_timeout(LATE_DOWNLOAD_WAIT_MS)
                        break
                except Exception:
                    continue
        gone = 0
        for dl in self.late:
            gone += self.discard(dl)
        self.late = []
        self.owed_link = None
        for page in self._watched:
            try:
                page.remove_listener("download", self._on_download)
            except Exception:
                pass
        self._watched = []
        return gone

    def navigated(self) -> None:
        if self.first_navigation is None:
            self.first_navigation = self.clock()

    def past_deadline(self) -> bool:
        return self.first_navigation is not None \
            and self.clock() - self.first_navigation >= self.limit_s


@dataclass
class RawDoc:
    title: str
    account: str = ""
    date_text: str = ""
    href: str = ""
    text: str = ""
    row_index: int = -1
    kind: str = "doc"
    # The document's uuid from the list. Private: never logged or in a name.
    document_id: str = ""
    doc_type: str = ""


@dataclass(frozen=True)
class Item:
    """One document as the list answers it."""
    document_id: str
    date: str
    doc_type: str

    @property
    def shape(self) -> tuple:
        return (self.date, self.doc_type)


@dataclass
class Listed:
    items: List[Item]
    kept: List[Item]
    counts: dict = field(default_factory=dict)
    # The window the page asked the list for, from the list call's address.
    start: str = ""
    end: str = ""


# The type of the account's application, dated when the account was opened.
APPLICATION_TYPE = "account_application"


def _today() -> _date:
    """The day the run reads the list on."""
    return _date.today()


def window_whole(listed: Listed, today: _date) -> bool:
    """Whether the window the page asked the list for can hold every
    document up to now. Both ends are calendar dates, the start on or
    before the end, and the end no earlier than yesterday, since a list
    that ended before then may be missing what came since."""
    start, end = listed.start, listed.end
    if calendar_date(start) != start or calendar_date(end) != end:
        return False
    return start <= end and end >= (today - timedelta(days=1)).isoformat()


def reaches_back(listed: Listed, floor: Optional[str], today: _date) -> bool:
    """Whether the list reaches back far enough to be called whole. The
    page asks for documents from a start date of its own, so an account
    older than that has documents the list never holds. Its window must be
    whole first (window_whole). It is whole when the earliest application
    it holds is inside its window and nothing listed is dated before it,
    since nothing comes before the account was opened and a reissued
    application must not let older documents pass. It is whole as well
    when its window starts on or before the run's own start date, since
    nothing earlier is wanted. A floor that is not a calendar date counts
    as no floor."""
    if not window_whole(listed, today):
        return False
    start, end = listed.start, listed.end
    applied = [i.date for i in listed.items if i.doc_type == APPLICATION_TYPE]
    if applied:
        first = min(applied)
        if start <= first <= end and all(i.date >= first for i in listed.items):
            return True
    return bool(floor) and calendar_date(floor) == floor and start <= floor


# ---------------------------------------------------------------------------
# Reading the page. Read only, nothing on the page is changed.
# ---------------------------------------------------------------------------
_STATE_JS = r"""() => {
  const tidy = s => (s || '').replace(/\s+/g, ' ').trim();
  const shown = el => !!el && !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length)
                      && getComputedStyle(el).visibility !== 'hidden';
  const labels = el => [tidy(el.innerText), tidy(el.getAttribute('aria-label')),
                        tidy(el.getAttribute('title'))].filter(Boolean);
  const out = {switcher: [], banner: false, tables: document.querySelectorAll('table').length,
               bodies: 0, rows: [], buttons: [],
               password: !!document.querySelector("input[type='password']")};
  for (const s of document.querySelectorAll('[data-testid="account-switcher-button"]'))
    out.switcher.push({text: tidy(s.innerText), shown: shown(s)});
  out.banner = /you are on paper trading/i.test(document.body ? document.body.innerText : '');
  const t = document.querySelector('table');
  if (t) {
    out.bodies = t.querySelectorAll('tbody').length;
    const body = t.querySelector('tbody');
    let n = 0;
    for (const tr of (body ? body.children : [])) {
      if (tr.tagName !== 'TR') continue;
      n += 1;
      const cells = Array.from(tr.children).filter(c => c.tagName === 'TD');
      const last = cells.length ? cells[cells.length - 1] : null;
      const ps = last ? Array.from(last.querySelectorAll('p')) : [];
      out.rows.push({n: n, shown: shown(tr), cells: cells.map(c => tidy(c.innerText)),
                     controls: ps.length, control: ps.length === 1 ? labels(ps[0]) : []});
    }
  }
  const all = Array.from(document.querySelectorAll('button'));
  all.forEach((b, i) => {
    const l = labels(b);
    if (l.some(x => /^(next|previous|[0-9]{1,3})$/i.test(x)))
      out.buttons.push({i: i, labels: l, shown: shown(b),
                        disabled: !!b.disabled || b.getAttribute('aria-disabled') === 'true'});
  });
  return out;
}"""

_LABELS_JS = r"""el => [el.innerText, el.getAttribute('aria-label'), el.getAttribute('title')]
  .map(s => (s || '').replace(/\s+/g, ' ').trim()).filter(Boolean)"""


def _read(page) -> dict:
    """What the documents page shows now. A page that cannot be read stops
    the list. The switcher's text is private as soon as it is read."""
    try:
        state = page.evaluate(_STATE_JS)
    except Exception as e:
        raise ListStopped("the documents page could not be read (%s)" % type(e).__name__)
    if not isinstance(state, dict):
        raise ListStopped("the documents page could not be read")
    for s in state.get("switcher") or []:
        guard_switcher((s or {}).get("text") or "")
    if state.get("password"):
        raise SessionExpired("Alpaca showed a password field")
    return state


def _wait_for(page, ready: Callable[[dict], bool], timeout_ms: int) -> Optional[dict]:
    """Read the page until `ready` holds, or None once `timeout_ms` has
    gone. The session is asked before and after every wait."""
    waited = 0
    while True:
        check_signed_in(page)
        state = _read(page)
        if ready(state):
            return state
        if waited >= timeout_ms:
            return None
        page.wait_for_timeout(POLL_MS)
        waited += POLL_MS
        check_signed_in(page)


def check_account(state: dict) -> None:
    """The account the page shows is Live: one shown, readable switcher
    whose text holds no "Paper", and no Paper banner. NotLive otherwise."""
    sw = state.get("switcher") or []
    if len(sw) != 1 or not sw[0].get("shown") or not _tidy(sw[0].get("text")):
        raise NotLive("the account switcher could not be read")
    if reads_paper(sw[0].get("text")):
        raise NotLive("the account switcher shows a Paper account")
    if state.get("banner"):
        raise NotLive("the page shows the Paper trading banner")


def check_live(page, state: dict) -> None:
    """check_account, and the page is exactly the documents page with its
    one table. Asked after navigation and before every press."""
    check_account(state)
    if not is_documents_url(page.url or ""):
        raise NotLive("the page is not the documents page")
    if state.get("tables") != 1 or state.get("bodies") != 1:
        raise NotLive("the documents table is not on the page once")


def _ready(page) -> Callable[[dict], bool]:
    return lambda s: is_documents_url(page.url or "") and len(s.get("switcher") or []) == 1 \
        and s.get("tables") == 1 and s.get("bodies") == 1


# ---------------------------------------------------------------------------
# The page's own answers
# ---------------------------------------------------------------------------

def _status(response) -> Optional[int]:
    try:
        return int(response.status)
    except Exception:
        return None


class _Watch:
    """The page's own answers to one kind of call while armed, and whether
    any of them said signed out. Only answers `want` takes are looked at,
    and only their status here."""

    def __init__(self, page, want: Callable):
        self.page, self.want = page, want
        self.got: list = []
        self.signed_out = False

    def _on(self, response):
        try:
            if not self.want(response):
                return
            if _status(response) in (401, 403):
                self.signed_out = True
                return
            self.got.append(response)
        except Exception:
            pass

    def raise_if_signed_out(self) -> None:
        if self.signed_out:
            raise SessionExpired("Alpaca answered as signed out")

    def __enter__(self):
        self.page.on("response", self._on)
        return self

    def __exit__(self, *exc):
        try:
            self.page.remove_listener("response", self._on)
        except Exception:
            pass
        return False


def read_list(response) -> Listed:
    """Every document of one list answer, and those this app takes.

    The answer must be 200 JSON, a list of {id, name, type, sub_type, date}:
    each id a uuid, no id twice, each type a lowercase enum, each date a
    calendar date. Kept are the three statement and confirmation types. The
    JSON twins, the application, tax forms (deferred) and any other type are
    counted and skipped. Kept documents that share one type and one date
    with another are counted (alike) and not kept, since a row could not be
    told from the other, and the rest are kept. They stay in the list's
    items, so the rows are still checked against them. The window the list
    was asked for is read off its address. A 401 or 403, or an answer that
    is not a JSON list, is a signed-out session. Nothing of the answer is
    logged."""
    status = _status(response)
    if status in (401, 403):
        raise SessionExpired("the documents list answered as signed out")
    try:
        m = LIST_PATH_RE.fullmatch(urlsplit(response.url).path)
    except Exception:
        m = None
    if m:
        _guard([m.group(1)])
    if status != 200:
        raise ListStopped("the documents list answered with status %s" % status)
    try:
        data = whole_json(response.json())
    except Exception:
        raise SessionExpired("the documents list did not answer with JSON")
    if not isinstance(data, list):
        raise SessionExpired("the documents list did not answer with a list")
    _guard(d.get("id") for d in data if isinstance(d, dict) and isinstance(d.get("id"), str))
    items = []
    for d in data:
        if not isinstance(d, dict):
            raise ListStopped("a document in the list is not the shape this reads")
        doc_id, kind, day = d.get("id"), d.get("type"), d.get("date")
        if not isinstance(doc_id, str) or not UUID_RE.fullmatch(doc_id):
            raise ListStopped("a document's id is not one this can read")
        if not isinstance(kind, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", kind):
            raise ListStopped("a document's type is not one this can read")
        if calendar_date(day) != day:
            raise ListStopped("a document's date is not a calendar date")
        for extra in ("name", "sub_type"):
            if d.get(extra) is not None and not isinstance(d.get(extra), str):
                raise ListStopped("a document in the list is not the shape this reads")
        items.append(Item(document_id=doc_id.lower(), date=day, doc_type=kind))
    if len({i.document_id for i in items}) != len(items):
        raise ListStopped("two documents in the list carry one id")
    kept, counts = [], {k: 0 for k in COUNTED}
    for i in items:
        if i.doc_type in TITLES:
            kept.append(i)
        elif i.doc_type in SKIPPED_TYPES:
            counts[SKIPPED_TYPES[i.doc_type]] += 1
        elif i.doc_type.startswith("tax") or "1099" in i.doc_type:
            counts["tax"] += 1
        else:
            counts["other"] += 1
    shapes = Counter(i.shape for i in kept)
    counts["alike"] = sum(n for n in shapes.values() if n > 1)
    kept = [i for i in kept if shapes[i.shape] == 1]
    try:
        query = parse_qs(urlsplit(response.url).query)
        start, end = query.get("start", [""])[0], query.get("end", [""])[0]
    except Exception:
        start = end = ""
    return Listed(items=items, kept=kept, counts=counts, start=start, end=end)


# ---------------------------------------------------------------------------
# The rows the page draws
# ---------------------------------------------------------------------------

def row_shape(row) -> Optional[tuple]:
    """(date, type) of a row reading "<date> | <type> | Download" with one
    Download in its last cell, or None when it reads any other way."""
    cells = list((row or {}).get("cells") or [])
    if len(cells) != 3 or _tidy(cells[2]).lower() != "download" or (row or {}).get("controls") != 1:
        return None
    day, kind = _tidy(cells[0]), _tidy(cells[1])
    if calendar_date(day) != day or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", kind):
        return None
    return (day, kind)


def _shown_rows(state: dict) -> list:
    return [r for r in state.get("rows") or [] if r.get("shown")]


def _rows_readable(state: dict) -> bool:
    rows = _shown_rows(state)
    return bool(rows) and all(row_shape(r) for r in rows)


def _signature(state: dict) -> tuple:
    return tuple(row_shape(r) for r in _shown_rows(state))


def _next_button(state: dict) -> Optional[dict]:
    """The one shown "Next" button that is not turned off, or None."""
    hits = [b for b in state.get("buttons") or []
            if any(_tidy(t).lower() == "next" for t in b.get("labels") or [])]
    if len(hits) != 1 or not hits[0].get("shown") or hits[0].get("disabled"):
        return None
    return hits[0]


# ---------------------------------------------------------------------------
# Pressing. Every press goes through _press, with one of the two predicates.
# ---------------------------------------------------------------------------

def _labels_of(locator) -> List[str]:
    try:
        labels = locator.evaluate(_LABELS_JS)
    except Exception:
        return []
    return [str(x) for x in labels or [] if str(x or "").strip()]


# What a turned off control means where it is pressed (_press's `off`).
STOPS_THE_LIST = "stops the list"
LEAVES_THE_DOCUMENT = "leaves the document"
OFF_MEANS = (STOPS_THE_LIST, LEAVES_THE_DOCUMENT)


class Attempt:
    """Whether a press may have reached the page: set just before the
    core's press and cleared when the core says it made none."""

    def __init__(self):
        self.may_have_pressed = False


def _press(page, run: Run, locator, *, css: str, what: str, guard, step: str, off: str,
           attempt: Optional[Attempt] = None) -> None:
    """Press one control, once, through the core, after the session, the
    deadline and the Live account have been checked and every label it
    carries has passed `guard`, one of PRESS_GUARDS. A control that is not
    exactly one shown element, or a label refused, stops the list and
    nothing is pressed.

    A control the page has turned off is not pressed (pressing.TurnedOff),
    and `off` says what that means here: STOPS_THE_LIST raises ListStopped,
    for the list's Next, and LEAVES_THE_DOCUMENT raises DocumentTurnedOff,
    for a document's own Download, which nothing was pressed for. A turned
    off control that something covers or that cannot be read still stops
    the run (pressing.Covered, pressing.Unread)."""
    if off not in OFF_MEANS:
        raise ListStopped("a press was asked for with no word on a turned off control")
    if guard not in PRESS_GUARDS:
        raise ListStopped("a press was asked for with no guard of this app's own")
    check_signed_in(page)
    if run.past_deadline():
        raise DeadlineReached("the run's time at Alpaca is up")
    check_live(page, _read(page))
    try:
        if locator.count() != 1 or not locator.is_visible():
            raise ListStopped("%s is not one control on the page" % what)
    except ListStopped:
        raise
    except Exception as e:
        raise ListStopped("%s could not be read (%s)" % (what, type(e).__name__))
    labels = _labels_of(locator)
    if not labels or not all(guard(t) for t in labels):
        raise ListStopped("the guard refused %s" % what)
    if attempt is not None:
        attempt.may_have_pressed = True
    try:
        pressing.click(page, locator, css=css, what=what, words=_words(), step=step)
    except pressing.TurnedOff:
        # The core read it turned off and pressed nothing.
        if attempt is not None:
            attempt.may_have_pressed = False
        check_signed_in(page)
        if off == LEAVES_THE_DOCUMENT:
            raise DocumentTurnedOff("%s is turned off on the page" % what)
        raise ListStopped("%s is turned off on the page" % what)
    except pressing.Stop as stop:
        # Covered, Unread and the like come before any press was tried.
        if attempt is not None and not stop.after_a_press:
            attempt.may_have_pressed = False
        raise
    check_signed_in(page)


def _turn_page(page, run: Run, state: dict) -> dict:
    """Press the list's Next once and wait for other rows to show."""
    button = _next_button(state)
    if button is None:
        raise ListStopped("the list has no Next to press")
    before = _signature(state)
    _press(page, run, page.locator(PAGER_BUTTON).nth(int(button["i"])), css=PAGER_BUTTON,
           what="the list's Next button", guard=is_next_control, step="turn the list's page",
           off=STOPS_THE_LIST)
    turned = _wait_for(page, lambda s: _rows_readable(s) and _signature(s) != before, ROWS_WAIT_MS)
    if turned is None:
        raise ListStopped("the list did not show other rows after Next")
    return turned


def _max_pages(items) -> int:
    return len(items) // PAGE_SIZE + 2


# ---------------------------------------------------------------------------
# The documents page
# ---------------------------------------------------------------------------

class Opened:
    """The documents page as it opened: what it shows, and its list, with
    the list's listener still armed. It stays armed while the rows are
    read against the list, so a list answer that comes late, after the
    settle, is still counted (one_list_answer). close() takes it off."""

    def __init__(self, state: dict, listed: Listed, heard: Optional["_Watch"] = None):
        self.state = state
        self.listed = listed
        self.heard = heard

    def one_list_answer(self) -> None:
        """The page has still answered its list exactly once, and never as
        signed out. ListStopped or SessionExpired otherwise."""
        if self.heard is None:
            return
        self.heard.raise_if_signed_out()
        if len(self.heard.got) != 1:
            raise ListStopped("%d list answers came for one opening of the page"
                              % len(self.heard.got))

    def close(self) -> None:
        if self.heard is not None:
            self.heard.__exit__(None, None, None)
            self.heard = None


def _open(page, run: Run) -> Opened:
    """Open the documents page by its address, with its list answer awaited,
    and prove it the Live account's: the account is checked before leaving
    a page of the site and again once the page is ready. Exactly one list
    answer, read whole. Raises SessionExpired, NotLive or ListStopped.
    Nothing is pressed.

    The list answer is heard by a listener armed before the navigation,
    for exactly the list call, and waited for by counting, not by
    page.expect_response: the address is the first thing asked of a tab
    this run opened (core/tests/test_no_app_acts_on_another_sites_tab.py),
    and the listener hears every answer expect_response would. It is left
    armed on the Opened it returns, so the rows can be read against the list
    with a late second answer still counted. The caller closes it."""
    check_signed_in(page)
    if is_safe_url(page.url or ""):
        check_account(_read(page))
    run.navigated()
    heard = _Watch(page, is_list_response).__enter__()
    try:
        try:
            page.goto(DOCUMENTS_URL, wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            log.info("opening the documents page failed (%s)", type(e).__name__)
            check_signed_in(page)
            heard.raise_if_signed_out()
            raise ListStopped("the documents page did not open")
        check_signed_in(page)
        waited = 0
        while not heard.got and not heard.signed_out and waited < LIST_WAIT_MS:
            page.wait_for_timeout(POLL_MS)
            waited += POLL_MS
            check_signed_in(page)
        heard.raise_if_signed_out()
        if not heard.got:
            if not is_documents_url(page.url or ""):
                raise NotLive("the documents page did not stay open, as on a Paper account")
            raise ListStopped("the documents list did not come")
        state = _wait_for(page, _ready(page), READY_WAIT_MS)
        if state is None:
            state = _read(page)
        check_live(page, state)
        page.wait_for_timeout(SETTLE_MS)
        check_signed_in(page)
        opened = Opened(state, None, heard)
        opened.one_list_answer()
        opened.listed = read_list(heard.got[0])
    except BaseException:
        heard.__exit__(None, None, None)
        raise
    return opened


def _first_rows(page, items, state: dict) -> dict:
    """The first page of rows, once they read whole."""
    if not items:
        return state
    ready = _wait_for(page, _rows_readable, ROWS_WAIT_MS)
    if ready is None:
        raise ListStopped("the list's rows did not show in a shape this reads")
    return ready


def cross_check(page, run: Run, items: List[Item], state: dict) -> int:
    """Read every page of rows, to the last one, until they are exactly the
    list's documents as a multiset of (date, type) and the list has no Next
    left to press (missing or turned off). Rows matching the list while Next
    is still on are not the end: the next page is read, so rows the list
    does not hold are never missed. A page whose rows do not change after
    Next, a page seen twice, a Next missing or turned off while rows are
    missing, more rows of a kind than the list holds, or more pages than the
    list can fill stops the list. Says how many pages were read."""
    want = Counter(i.shape for i in items)
    if not items:
        if any(row_shape(r) for r in _shown_rows(state)):
            raise ListStopped("the page shows rows the list does not hold")
        if _next_button(state) is not None:
            raise ListStopped("an empty list shows a Next to press")
        return 0
    state = _first_rows(page, items, state)
    seen: Counter = Counter()
    visited = set()
    pages = 0
    while True:
        sig = _signature(state)
        if None in sig:
            raise ListStopped("a row of the list reads in a way this cannot read")
        if sig in visited:
            raise ListStopped("a page of the list came twice")
        visited.add(sig)
        seen.update(sig)
        pages += 1
        if seen == want and _next_button(state) is None:
            return pages
        if any(seen[k] > want[k] for k in seen):
            raise ListStopped("the rows on the page are not the documents the list holds")
        if pages >= _max_pages(items):
            raise ListStopped("the list ran to more pages than its documents fill")
        if _next_button(state) is None:
            raise ListStopped("the list ended before all its documents showed")
        state = _turn_page(page, run, state)


def _rawdocs(items: List[Item]) -> List[RawDoc]:
    return [RawDoc(title=TITLES[i.doc_type], date_text=i.date, href="", text=TITLES[i.doc_type],
                   kind="statement", document_id=i.document_id, doc_type=i.doc_type)
            for i in items]


def collect_download_docs(page, run: Optional[Run] = None) -> List[RawDoc]:
    """Every statement and trade confirmation the Live account's list holds,
    once its window is whole (window_whole), it reaches back far enough
    (reaches_back) and every row the page draws has been checked against
    it. Raises ListStopped, SessionExpired, NotLive or DeadlineReached."""
    run = run or Run()
    opened = _open(page, run)
    try:
        run.counts = dict(opened.listed.counts)
        today = _today()
        if not window_whole(opened.listed, today):
            raise WindowNotWhole()
        if not reaches_back(opened.listed, run.floor, today):
            raise ListTooShort(opened.listed.start)
        pages = cross_check(page, run, opened.listed.items, opened.state)
        # A second list answer that came while the rows were read means the
        # rows may be another list's.
        opened.one_list_answer()
    finally:
        opened.close()
    log.info("documents list: %d listed, %d kept, read over %d page(s)",
             len(opened.listed.items), len(opened.listed.kept), pages)
    return _rawdocs(opened.listed.kept)


def goto_documents(page, run: Optional[Run] = None) -> bool:
    """Open the documents page by its address and prove it the Live
    account's. False when it did not. Nothing is pressed."""
    try:
        _open(page, run or Run()).close()
        return True
    except (SessionExpired, ListStopped, NotLive) as e:
        log.info("the documents page did not open: %s", e)
        return False


def scroll_full_page(page, rounds: int = 0, delay_ms: int = 0) -> None:
    """Nothing to scroll: the list is paged with Next."""
    return None


def expand_all(page) -> None:
    """Nothing to press beyond the two controls in the module docstring."""
    return None


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def bind(items: List[Item], document_id: str, iso: str, doc_type: str) -> bool:
    """Whether exactly one listed document has the record's date and type,
    and it is the record's own id."""
    same = [i for i in items if i.shape == (iso, doc_type)]
    return len(same) == 1 and same[0].document_id == str(document_id).lower()


def _find_row(page, run: Run, opened: Opened, document_id: str, iso: str, doc_type: str,
              trace: Optional[list]) -> int:
    """Bind the record to exactly one listed document, and page with Next
    to the one row reading its date and type, the list's listener armed
    throughout: the row is given only while the page has answered its list
    exactly once. The row's number on the page shown, or -1 with nothing
    pressed on a row."""
    items = opened.listed.items
    if not bind(items, document_id, iso, doc_type):
        if trace is not None:
            trace.append({"note": "no single listed document matches the record"})
        return -1
    state = _first_rows(page, items, opened.state)
    want = (iso, doc_type)
    visited = set()
    while True:
        sig = _signature(state)
        if None in sig:
            raise ListStopped("a row of the list reads in a way this cannot read")
        if sig in visited:
            raise ListStopped("a page of the list came twice")
        visited.add(sig)
        hits = [r for r in _shown_rows(state) if row_shape(r) == want]
        if len(hits) > 1:
            if trace is not None:
                trace.append({"note": "two rows read the record's date and type"})
            return -1
        if hits:
            opened.one_list_answer()
            return int(hits[0]["n"])
        if len(visited) >= _max_pages(items) or _next_button(state) is None:
            if trace is not None:
                trace.append({"note": "no row reads the record's date and type"})
            return -1
        state = _turn_page(page, run, state)


def _discard(dl, dl_dir, before) -> int:
    """Discard what a download that was not taken left: the core takes the
    file the browser wrote for it only when the folder can say that file
    is this download's (capture.take_download, the way an accepted capture
    takes one), into a scratch file that is then removed with any exact copy
    of it that arrived since `before` (capture.clear_copies). Nothing is
    matched by its name alone. Says how many files went from the folder."""
    import tempfile
    scratch = Path(tempfile.mkdtemp(prefix="alpaca-discard-"))
    try:
        held = scratch / "discarded.pdf"
        how = _take_download(dl, dl_dir, before, held)
        if not how:
            return 0
        copies = _clear_copies(dl_dir, before, held)
        return (1 if how == "folder" else 0) + copies
    except Exception as e:
        log.info("a download that was not taken could not be discarded (%s)", type(e).__name__)
        return 0
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def _unfinished(dl_dir) -> bool:
    try:
        return any(p.name.lower().endswith((".crdownload", ".part", ".download", ".tmp"))
                   for p in Path(dl_dir).iterdir())
    except OSError:
        return False


def _stop(said: str, reason: str):
    return pressing.no_answer("download the document", reason, said)


def row_css(n: int) -> str:
    return "%s:nth-of-type(%d)" % (ROW, int(n))


def download_css(n: int) -> str:
    return "%s > td:last-child p" % row_css(n)


def _link_of(answered: list, document_id: str) -> str:
    """The presigned link of the one link answer for this document, checked
    whole, or the run stops. Never logged."""
    if len(answered) != 1:
        raise _stop("The page asked Alpaca for %s document link after one Download, so "
                     "nothing was taken." % ("no" if not answered else "more than one"),
                     "not one document link was asked for")
    resp = answered[0]
    if not is_link_response(resp, document_id):
        raise _stop("The page asked for another document's link, so nothing was taken.",
                    "the link was for another document")
    if _status(resp) != 200:
        raise _stop("Alpaca did not hand over the document's link, so nothing was taken.",
                    "the link was not handed over")
    try:
        data = whole_json(resp.json())
    except Exception:
        raise SessionExpired("the document link did not answer with JSON")
    if not isinstance(data, dict):
        raise SessionExpired("the document link did not answer with an object")
    link = data.get("url")
    if isinstance(link, str):
        guard_link(link)
    if str(data.get("id") or "").lower() != str(document_id).lower():
        raise _stop("Alpaca's link answer named another document, so nothing was taken.",
                    "the link answer named another document")
    if not isinstance(link, str) or not is_download_url(link):
        raise _stop("The document's link was not in Alpaca's document bucket, so nothing "
                    "was taken.", "the link was not alpaca's bucket")
    return link


def _from_link(download, link: str) -> bool:
    """Whether the download came from exactly the link Alpaca handed over.
    A blob the page made, or any other address, is not bound to the link
    and is never taken."""
    try:
        url = download.url or ""
    except Exception:
        return False
    return url == link


def _catch_document(page, run: Run, dl_dir, n: int, document_id: str, iso: str, doc_type: str,
                    out_path: Path, trace: Optional[list], opened: Optional[Opened] = None) -> bool:
    """Press row `n`'s Download once and take the one download that brings,
    through the core.

    `opened` is the documents page as download_document opened it, its
    list's listener still armed: just before the press the page must still
    have answered its list exactly once, or nothing is pressed.

    A download already on its way, none in time, two in the press's window,
    a link that is not this document's or not in Alpaca's bucket, or a file
    that is not a PDF stops the run: nothing more is pressed for this or any
    later document. A Download the page has turned off is not pressed and
    raises DocumentTurnedOff. A download bound to this press and not taken
    is discarded (Run.discard). Nothing else in the folder is touched."""
    out_path = Path(out_path)
    css = download_css(n)
    want = (iso, doc_type)
    run.watch(page, dl_dir)
    attempt = Attempt()
    bound = None
    kept = False
    before = _snapshot(dl_dir)
    run.before = before
    try:
        if _unfinished(dl_dir):
            raise _stop("A download was still arriving before this document was saved, "
                        "so nothing was pressed.", "a download was pending")
        rows = [r for r in _shown_rows(_read(page)) if r.get("n") == n]
        if len(rows) != 1 or row_shape(rows[0]) != want:
            raise ListStopped("the row changed before its Download was pressed")
        if opened is not None:
            # A list answer that came since the row was found may make the
            # row another document's.
            opened.one_list_answer()
        with _Watch(page, is_link_response) as heard:
            run.open_window()
            came: list = []
            try:
                try:
                    with page.expect_download(timeout=DOWNLOAD_WAIT_MS) as info:
                        with page.expect_response(lambda r: is_link_response(r, document_id),
                                                  timeout=URL_WAIT_MS):
                            _press(page, run, page.locator(css), css=css,
                                   what="the document's Download", guard=is_download_control,
                                   step="download the document", off=LEAVES_THE_DOCUMENT,
                                   attempt=attempt)
                    dl = info.value
                except DocumentTurnedOff:
                    if trace is not None:
                        trace.append({"note": "the Download is turned off on the page, so "
                                              "nothing was pressed and the document is left "
                                              "for the next run"})
                    raise
                except (SessionExpired, ListStopped, NotLive, DeadlineReached):
                    raise
                except Exception as e:
                    check_signed_in(page)
                    heard.raise_if_signed_out()
                    if attempt.may_have_pressed and not run.window:
                        # The press may still bring its download. Only one
                        # from exactly the link Alpaca handed it is its own.
                        try:
                            run.owed_link = _link_of(list(heard.got), document_id)
                        except (pressing.Stop, SessionExpired):
                            run.owed_link = None
                    if trace is not None:
                        trace.append({"note": "no download came", "error": type(e).__name__})
                    raise _stop("Download was pressed and no download came.", "no download came")
                check_signed_in(page)
                heard.raise_if_signed_out()
                page.wait_for_timeout(SECOND_DOWNLOAD_WAIT_MS)
                heard.raise_if_signed_out()
                answered = list(heard.got)
            finally:
                came = run.close_window()
                if not attempt.may_have_pressed:
                    # Nothing was pressed, so nothing that came is this run's.
                    run.unbound += len(came)
                    came = []
        if len(came) != 1 or came[0] is not dl:
            raise _stop("More than one download came after one Download, so none was taken "
                        "and none was touched.", "more than one download came")
        try:
            suggested = str(dl.suggested_filename or "")
        except Exception:
            suggested = ""
        _guard([suggested, Path(suggested).stem])
        link = _link_of(answered, document_id)
        if not _from_link(dl, link):
            # Not from the link Alpaca handed this press, so it is not this
            # press's download, and the press's own did not come. It is
            # left as it is, and the run stops, since which download is
            # whose cannot be told.
            run.unbound += 1
            log.info("a download that did not come from the document's link came on the "
                     "tab, and is left as it is")
            raise _stop("The only download that came was not from the document's link, so "
                        "nothing was taken and it was left as it is.",
                        "the download came from elsewhere")
        # Proved this press's own: from exactly the link handed over.
        bound = dl
        how = _take_download(dl, dl_dir, before, out_path)
        if trace is not None:
            trace.append({"note": "download taken" if how else "download not taken", "how": how})
        if not how or not out_path.exists() or out_path.read_bytes()[:5] != b"%PDF-":
            try:
                out_path.unlink()
            except OSError:
                pass
            raise _stop("The download was not a PDF, so it was not kept.", "the download was not a pdf")
        kept = True
        return True
    finally:
        try:
            if kept:
                _clear_copies(dl_dir, before, out_path)
            elif bound is not None:
                # The one download this press brought, refused.
                run.discard(bound)
        except Exception:
            pass


def download_document(page, run: Run, dl_dir, out_path, *, document_id: str, iso_date: str,
                      doc_type: str, trace: Optional[list] = None) -> bool:
    """Save the document discovery recorded. The documents page is opened
    afresh, its list read again, the record bound to exactly one listed
    document and one row, and only then is that row's Download pressed, the
    list's listener armed from the opening to the press. False, with
    nothing pressed on a row, when the list does not hold the record once.
    DocumentTurnedOff, when the row's Download is turned off on the page,
    SessionExpired, NotLive, DeadlineReached and a stop of the run
    propagate, and so does ListStopped when the documents page will not
    open, its list cannot be read again, the row's Download is refused or
    the row or the list's answer changes before the press, since every
    document after this one meets the same page, as Bilt's and First
    Horizon's do."""
    out_path = Path(out_path)
    day = iso_date
    if not (isinstance(document_id, str) and UUID_RE.fullmatch(document_id)
            and calendar_date(day) == day and doc_type in TITLES):
        if trace is not None:
            trace.append({"note": "the record does not name one document"})
        return False
    try:
        opened = _open(page, run)
    except ListStopped as stop:
        log.info("the list stopped while looking for the document dated %s: %s", day, stop)
        raise
    try:
        try:
            n = _find_row(page, run, opened, document_id, day, doc_type, trace)
        except ListStopped as stop:
            log.info("the list stopped while looking for the document dated %s: %s", day, stop)
            raise
        if n < 1:
            return False
        try:
            return _catch_document(page, run, dl_dir, n, document_id, day, doc_type, out_path,
                                   trace, opened=opened)
        except ListStopped as stop:
            log.info("the document dated %s was not saved: %s", day, stop)
            raise
    finally:
        opened.close()


# ---------------------------------------------------------------------------
# Diagnose. Reads only, presses nothing. No screenshot.
# ---------------------------------------------------------------------------

def collect_documents(page) -> List[RawDoc]:
    """The rows drawn now, by shape only (date, type)."""
    try:
        state = _read(page)
    except (ListStopped, SessionExpired):
        return []
    out = []
    for r in _shown_rows(state):
        shape = row_shape(r)
        if shape:
            out.append(RawDoc(title=TITLES.get(shape[1], "Document"), date_text=shape[0],
                              text=shape[1], row_index=int(r.get("n") or -1), kind="statement"))
    return out


def survey(page, dwell_ms: int = 4000, max_follow: int = 0) -> dict:
    """What the signed-in documents page shows, by counts and the guard's
    verdicts, without a label of the page's. Presses nothing."""
    page.wait_for_timeout(dwell_ms)
    try:
        state = _read(page)
    except (ListStopped, SessionExpired) as e:
        return {"pages": [], "error": type(e).__name__}
    sw = state.get("switcher") or []
    return {"pages": [{
        "url": redact(page.url or ""),
        "documents_route": is_documents_url(page.url or ""),
        "switchers": len(sw),
        "switcher_shown": bool(sw) and bool(sw[0].get("shown")),
        "switcher_reads_paper": any(reads_paper(s.get("text")) for s in sw),
        "paper_banner": bool(state.get("banner")),
        "tables": state.get("tables"),
        "rows": len(state.get("rows") or []),
        "rows_readable": sum(1 for r in state.get("rows") or [] if row_shape(r)),
        "pager_buttons": len(state.get("buttons") or []),
        "pager_buttons_the_guard_takes": sum(
            1 for b in state.get("buttons") or []
            if b.get("labels") and all(is_safe_control(t) for t in b.get("labels"))),
        "next_enabled": _next_button(state) is not None,
    }]}
