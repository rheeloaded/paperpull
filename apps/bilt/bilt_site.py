"""ALL www.bilt.com selectors, URLs and page behavior live here.

When Bilt changes its wallet, repair this file only.

STATUS: built from the account owner's read-only survey of a signed-in
account on 2026-10-15 (the Bilt Card 2.0, serviced by Cardless, one card
with eight statements, October 06, 2026 back to March 06, 2026), then run
live on that account the same day: Discover listed the eight, Pilot and
Run All saved them all, Verify found no problem. What the survey saw is
marked SURVEYED below, and what the run then settled or left open is
marked under WHAT THE RUN SETTLED.

WHAT THE SURVEY ESTABLISHED (SURVEYED)
  * The account holder signs in at https://www.bilt.com, a Next.js app. The
    wallet is /wallet, and its session holds across page.goto within
    www.bilt.com. The wallet shows a carousel of wallet items ("Card 2 of
    11"), the Bilt Card among them ("Bilt Blue Card •••• 1234"), and under
    the card a button whose only label is aria-label="View balance summary",
    with "Pay card", "Pay with points", "Authorized users", "Manage card",
    "Lock card", "Transfer a balance", "Make payment", "Refer a friend" and a
    "Recent activity ... View all" link to
    /wallet/transactions?cardId=<card id, a UUID>.
  * The data comes from https://api.biltrewards.com, asked by the page with
    headers of its own. A plain request without them fails, so this app
    asks that host nothing and only hears the answers the page's own
    requests get (_Watch).
  * The three presses, all read-only:
      1. "View balance summary" opens a sheet holding a
         <div role="button"> reading exactly "View statements".
      2. "View statements" opens a second sheet that lists the statements
         as <button aria-label="Download statement for October 06, 2026">
         reading "October 06, 2026", newest first. Opening it makes the
         page GET /bilt-card/cards/<card id>/account/statements, answered
         {"statements": [{"statementId", "date": "YYYY-MM-DD",
         "downloadUrl": null}, ...], "count": N}.
      3. A statement's button makes the page GET
         .../account/statements/<statementId>/details, answered
         {"statementId", "date", "downloadUrl": <a signed address>}, and then
         opens a new tab at
         https://statements.cardless.com/<token>_<YYYY-MM-DD>_Bilt.pdf,
         the PDF itself. No browser download began, and the tab stays open.

WHAT THE RUN SETTLED (2026-10-15, eight statements saved)
  * The popup's address is signed: the statement's own date in its path
    and exactly the query keys Expires, Signature and Key-Pair-Id, each
    once (SIGNED_KEYS). Every query value is a private word.
  * The card's label on the wallet is split across elements, the name, the
    masked number and the card's own "View" button in one row, so the
    label pattern (CARD_LABEL_RE) allows that one word after the last four.
  * The "View statements" control's accessible name is "View statements
    action-right", an icon button's name nested in it, so it is found by
    its own exact text among the shown buttons (_view_statements).
  * The PDF is taken from the popup, read whole from its own answer or,
    when Chromium's PDF viewer keeps that, asked once more at the exact
    address with the browser's own cookies (_pdf_bytes). Which way it came
    is said in the trace. The PDF prints its statement date and the card's
    last four, and every one of the eight passed those checks.
  * A statementId held across the three loads of one session (Discover,
    Pilot, Run All), and the list was heard anew on each load.
  Still open: how long an idle session lasts, whether ids hold across a
  fresh sign-in, and a wallet with more than one Bilt Card (only one was
  seen, and two stop).

WHAT A SIGNED-OUT DISCOVER SHOWED (2026-10-15)
  * A signed-out visit to /wallet stays on that exact address, with no
    redirect, query or fragment, and the page draws its sign-in in place.
    The nav shows a "Sign up / Log in" control and the body reads "Complete
    login to continue" and "Welcome to Bilt. Log in or sign up.", over a
    phone or email field, "Continue" and "Sign in with passkey". It has no
    password field and no card. Those words or that control, with no
    balance summary button shown, are read as signed out (shows_sign_in).
    LOGIN_PATHS stays for an address Bilt may yet send a sign-out to.

THE THREE PRESSES. Nothing else is ever pressed, and each goes through one
place, _press, which reads every label the control carries, asks this
module's own predicate, and only then hands the press to the core
(pressing.click):
  1. "View balance summary" (is_balance_summary, that label exactly)
  2. "View statements" (is_view_statements, that label exactly)
  3. one statement's "Download statement for <Month DD, YYYY>", for that
     statement's date only (is_statement_button)
Pay card, Pay with points, Make payment, Transfer a balance, Lock card,
Manage card, Authorized users, Add, Refer a friend, Rewards, Neighborhood,
the concierge chat, the profile, the carousel's Previous and Next card and
everything else are refused. A control the page has turned off is never
pressed. A turned-off opener stops the list, and a turned-off statement
button leaves that one statement for the next run while the run goes on.

THE LIST IS KEPT WHOLE. The statements answer the page got must be one
answer, for the card the wallet shows, holding nothing but its list and
its count (the live answer held only those, so a pager's key, a cursor or
a total stops it), its count equal to its list, with no statement id or
date twice, and the sheet's buttons must show exactly the answer's dates,
one button each, read twice alike. A sheet that shows a control for more,
older or earlier statements, or a next page, stops the list too, since the
answer and the sheet would then agree on a part (PAGER_RE). Anything else
stops the list, which is then never called whole.

ONE STATEMENT. The wallet is loaded again and the list read again, whole,
and exactly one entry must carry the record's statementId and date. Then
that one button is pressed, and the run takes the statement only when
exactly one tab opened, it is on statements.cardless.com at a PDF address
of that date, the page's own details answer named that statementId and
date, no browser download began and no second tab opened. The tab is
closed before anything is kept, and the bytes must be a PDF whose text
prints the date and, where it prints a masked card number, the card's
last four (bind). Anything else stops the run.

SAFETY (a card account that can pay, transfer balances and lock the card):
  READ-ONLY. FORBIDDEN_CONTROL_RE and the core's settings and sign-in guards
  refuse any label that could pay, transfer, lock, manage, add a user,
  refer, redeem or sign out. Nothing is POSTed, and no host is opened but
  www.bilt.com. The one request this app asks itself is the popup's own PDF
  address, once, when its answer could not be read (_pdf_bytes).

PRIVACY: the card id, every statementId, the card's last four, the profile
name, the popup's token and whole address and the details downloadUrl are
private words the moment they are read, before anything is logged. None of
them, nor an answer, nor an address that carries one, is logged or said.
Records keep the date, a fixed title and the private ids in the app's own
discovery and progress files only.

SIGNED OUT: a sign-in address, a password field, the sign-in drawn on the
wallet itself, or a 401, 403, redirect or HTML answer to the page's own
statements requests raises SessionExpired. The run saves, says so and
stops, and asks for a sign-in again. A wallet that shows neither the
sign-in nor one Bilt Card still stops the list.

KNOWN CEILINGS
  * One Bilt Card. A wallet that shows none, or more than one, stops the
    list. The carousel is never moved, so the wallet has to be left showing
    the Bilt Card.
  * Statements of the Wells Fargo issued Bilt card (before February 2026)
    are not here. They are Wells Fargo's (apps/wellsfargo).
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import sys
from dataclasses import dataclass, field
from datetime import date as _date
from pathlib import Path
from typing import Callable, List, Optional, Tuple
from urllib.parse import parse_qsl, urlsplit

from paperpull_core import pdf_reader
from paperpull_core import intake
from paperpull_core import pressing
from paperpull_core import redirects
from paperpull_core.controls import SETTINGS_CONTROL_RE, AUTH_CONTROL_RE
from paperpull_core.redact import private_words, redact, set_private_words  # noqa: F401  (re-exported)
from paperpull_core.urls import is_safe_url as _host_allows
from paperpull_core.dates import last_day as _last_day
from paperpull_core.dates import checked as _checked_date
from paperpull_core.dates import full_year as _full_year
from paperpull_core.identity import REFUSED, VERIFIED, Identity, distinguish, verify
# re-exported: the docs module calls it as site.set_download_dir
from paperpull_core.capture import set_download_dir  # noqa: F401
from paperpull_core.words import words_for as _words_for
from paperpull_core.characters import whole_characters, whole_json

log = logging.getLogger("bilt_docs.site")


def _words():
    """This app's own words for paperpull_core.words."""
    return _words_for("Bilt", sys.modules[__name__])


# ---------------------------------------------------------------------------
# Addresses
# ---------------------------------------------------------------------------
HOST = "www.bilt.com"
BASE = f"https://{HOST}"
WALLET_PATH = "/wallet"
WALLET_URL = BASE + WALLET_PATH
DOCUMENTS_URL = WALLET_URL
STATEMENTS_URL = WALLET_URL
BILLING_URL = WALLET_URL
URLS = {
    "home": f"{BASE}/",
    # A signed-out visit to the wallet draws Bilt's sign-in at the wallet's
    # own address, where the account holder signs in.
    "login": WALLET_URL,
    "documents": WALLET_URL,
    "statements": WALLET_URL,
}
API_HOST = "api.biltrewards.com"
PDF_HOST = "statements.cardless.com"

# ASSUMED: the first part of a sign-in or signed-out address. Never seen,
# since a signed-out wallet draws its sign-in in place (shows_sign_in).
LOGIN_PATHS = {"login", "signin", "sign-in", "signup", "sign-up", "logout", "auth"}
# The same, as the addresses the core's tests ask about. An address is read
# by its first path part, never by a substring, so /wallet/authorized-users
# is not taken for /auth.
LOGIN_URL_MARKERS = sorted("/" + part for part in LOGIN_PATHS)

# ---------------------------------------------------------------------------
# HARD SAFETY GUARD. Every stem anchored.
# ---------------------------------------------------------------------------
FORBIDDEN_CONTROL_RE = re.compile(
    r"(\bpay\b|\bpays\b|\bpaying\b|\bpayments?\b|\bautopay\b|\bauto\s*-?\s*pay\b|\bpoints?\b|"
    r"\btransfers?\b|\btransferring\b|\block\b|\bunlock\b|\bfreeze\b|\bmanage\b|\bmanaging\b|"
    r"\bauthori[sz]ed\b|\busers?\b|\badd\b|\badding\b|\brefer|\breferral|\brewards?\b|"
    r"\bneighborhood\b|\bconcierge\b|\bchat\b|\bconversation\b|\bsuggestion\b|\bprofile\b|"
    r"\baccount\b|\bsettings?\b|\bpreferences?\b|\bsign\s*(out|off|in|up)\b|\blog\s*(out|off|in)\b|"
    r"\blogout\b|\blogin\b|\bdispute|\breplace|\breport\b|\bactivat|\bredeem|\bsubmit\b|"
    r"\bconfirm\b|\bcontinue\b|\bsave\b|\bdelet(e|es|ed|ing)\b|\bremov(e|es|ed|ing|al)\b|"
    r"\bclose\b|\bedit(s|ed|ing)?\b|\bupdat(e|es|ed|ing)\b|\bchang(e|es|ed|ing)\b|\blink|"
    r"\boffers?\b|\bbenefits?\b|\bapply\b|\bupgrade\b|\bscheduled\b|\bcancel\b|\bsend\b|"
    r"\brequest(s|ed|ing)?\b|\bshare\b|\bemail\b|\bupload\b|\battachment\b|\bvoice\b|"
    r"\bmap\b|\bprevious\b|\bnext\b|\bwallet\b|\bactivity\b|\btransactions?\b|\bview\s+all\b|"
    r"\bmembership\b|\bdefault\b|\bverify\b|\bpassword\b|\baccept\b|\bagree\b|\bauthori[sz]e\b|"
    r"\bmortgage\b|\bpartners?\b|\bsupport\b|\bhelp\b|\bmore\b|\bfullscreen\b|\bvisits?\b|"
    r"\bcash\b|\bcredit\s+limit\b|\bdeposit|\bwithdraw)", re.I)

# The three labels this app presses.
SUMMARY_LABEL = "View balance summary"
STATEMENTS_LABEL = "View statements"
_MONTH_NAMES = ("January", "February", "March", "April", "May", "June", "July", "August",
                "September", "October", "November", "December")
_MONTH_RE = "(%s)" % "|".join(_MONTH_NAMES)
_DAY_RE = _MONTH_RE + r" (\d{1,2}), (\d{4})"
STATEMENT_ARIA_RE = re.compile(r"Download statement for " + _DAY_RE)
STATEMENT_TEXT_RE = re.compile(_DAY_RE)

# is_safe_control is what the core's own tests and the survey ask about. The
# presses themselves use the three predicates below.
SAFE_DOC_CONTROL_RES = (
    re.compile(r"(view|download)\s+(card\s+)?statements?", re.I),
    re.compile(r"view\s+balance\s+summary", re.I),
    STATEMENT_ARIA_RE,
)

# A control that fetches one statement, for the survey.
STATEMENT_CONTROL_RE = STATEMENT_ARIA_RE

SECURITY_CHALLENGE_MARKERS = [
    "enter the code", "verification code", "6-digit", "two-factor",
    "two-step", "authenticator", "confirm your identity", "verify your identity",
    "we sent a code", "one-time passcode", "are you a robot", "captcha",
    "check your email", "check your phone", "access denied",
]

RATE_LIMIT_MARKERS = [
    "too many requests", "rate limit", "try again later",
    "temporarily unavailable", "http error 429", "unusual traffic",
]

STATEMENT_BUTTON = '[aria-label^="Download statement for "]'
TRANSACTIONS_LINK = 'a[href^="/wallet/transactions?cardId="]'
FALLBACK = {
    "doc_row": STATEMENT_BUTTON,
    "doc_link": STATEMENT_BUTTON,
    "download_control": STATEMENT_BUTTON,
    "page_ready": '[aria-label="View balance summary"]',
}

READY_WAIT_MS = 30000
LIST_WAIT_MS = 20000
SETTLE_MS = 1500
POPUP_WAIT_MS = 30000
SECOND_WAIT_MS = 3000
POLL_MS = 250

# ---------------------------------------------------------------------------
# Date parsing, the same general reader the other apps carry. The
# statements themselves use statement_date and button_date below, which
# read one shape each.
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
    """The date this provider's page is showing, as YYYY-MM-DD. A result
    naming a day that does not exist is refused."""
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
    """An answer's date as YYYY-MM-DD, or None. The whole value must be the
    date, written YYYY-MM-DD, and the day must exist."""
    if not isinstance(text, str):
        return None
    m = _ISO_RE.fullmatch(text)
    if not m:
        return None
    try:
        return _date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
    except ValueError:
        return None


def _from_words(m) -> Optional[str]:
    try:
        return _date(int(m.group(3)), _MONTH_NAMES.index(m.group(1)) + 1, int(m.group(2))).isoformat()
    except ValueError:
        return None


def button_date(label) -> Optional[str]:
    """A statement button's date as YYYY-MM-DD from its aria-label,
    "Download statement for October 06, 2026", or its text, "October 06,
    2026", the whole label exactly one of those. None otherwise."""
    label = _tidy(label)
    m = STATEMENT_ARIA_RE.fullmatch(label) or STATEMENT_TEXT_RE.fullmatch(label)
    return _from_words(m) if m else None


def words_date(iso: str) -> str:
    """YYYY-MM-DD as the sheet writes it, "October 06, 2026"."""
    d = _date.fromisoformat(iso)
    return "%s %02d, %04d" % (_MONTH_NAMES[d.month - 1], d.day, d.year)


def statement_label(iso: str) -> str:
    """The aria-label of the statement button of this date."""
    return "Download statement for " + words_date(iso)


# ---------------------------------------------------------------------------
# Session / safety
# ---------------------------------------------------------------------------

class SessionExpired(Exception):
    """Bilt answered as a signed-out session: its sign-in page, a password
    field, its sign-in drawn on the wallet, or a 401, 403, redirect or HTML
    answer to the page's own statements requests. The run stops for the
    account holder."""


class ListStopped(Exception):
    """The list has a part this could not read, so what was read is not all
    of it. `docs` holds what was read before it stopped. Its words are this
    module's own, never the page's."""

    def __init__(self, why: str, docs=None):
        super().__init__(why)
        self.docs = list(docs or [])


def _tidy(name) -> str:
    return re.sub(r"\s+", " ", str(name or "")).strip()


def _first_part(url: str) -> str:
    try:
        path = urlsplit(url or "").path
    except ValueError:
        return ""
    return (path.strip("/").split("/", 1)[0] or "").lower()


def shows_sign_in(state: dict) -> bool:
    """The page draws Bilt's sign-in (SIGN_IN_SENTENCES, SIGN_IN_CONTROL) and
    shows no balance summary button, as a signed-out visit to the wallet
    did. The words beside a shown balance summary button are the wallet's
    own content and are not read as signed out. The label on anything but a
    button does not count."""
    buttons = [x for x in _shown(state.get("summary")) if x.get("tag") == "BUTTON"]
    return bool(state.get("signin")) and not buttons


# How long the drawn sign-in has to stay, with no balance summary button,
# before it is read as signed out. The signed-out wallet draws its sign-in
# in place, and a page that does that can draw it for a moment while a
# signed-in wallet is still finding its session, so one look never says a
# run is signed out (#105).
SIGN_IN_HOLD_MS = 4000


def _sign_in_holds(page) -> bool:
    """Whether the page draws Bilt's sign-in (shows_sign_in) on every look
    for SIGN_IN_HOLD_MS. A look that cannot be made says no."""
    waited = 0
    while True:
        try:
            state = page.evaluate(_SIGNIN_JS)
        except Exception:
            return False
        if not (isinstance(state, dict) and shows_sign_in(state)):
            return False
        if waited >= SIGN_IN_HOLD_MS:
            return True
        _pause(page, POLL_MS)
        waited += POLL_MS


def looks_signed_out(page) -> bool:
    """A sign-in or signed-out address (LOGIN_PATHS), a password field, or
    the sign-in drawn in place on the wallet for SIGN_IN_HOLD_MS
    (shows_sign_in, _sign_in_holds). A page whose
    address cannot be read raises, and is never called signed in. A page
    that cannot be asked about its fields, as one mid-navigation, is not
    called signed out for that alone."""
    if _first_part(page.url or "") in LOGIN_PATHS:
        return True
    try:
        if page.locator("input[type='password']").count() > 0:
            return True
    except Exception:
        pass
    return _sign_in_holds(page)


def check_signed_in(page) -> None:
    """Raise SessionExpired when the page shows Bilt's sign-in. Asked
    before and after every wait and every press."""
    if looks_signed_out(page):
        raise SessionExpired("Bilt showed its sign-in page")


def detect_security_challenge(page) -> Optional[str]:
    """Names the passcode, CAPTCHA or throttling prompt on screen, or None.
    A page that shows a statement button is not a challenge."""
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
    statement actions, whole."""
    name = _tidy(name)
    if not name or _refused(name):
        return False
    return any(rx.fullmatch(name) for rx in SAFE_DOC_CONTROL_RES)


# -- the three predicates, one for each control this app presses -------------

def is_balance_summary(label) -> bool:
    """The card's "View balance summary" button, that label exactly, after
    the blocklist and the core guards."""
    label = _tidy(label)
    return bool(label) and not _refused(label) and label == SUMMARY_LABEL


def is_view_statements(label) -> bool:
    """The balance summary's "View statements", that label exactly."""
    label = _tidy(label)
    return bool(label) and not _refused(label) and label == STATEMENTS_LABEL


def is_statement_button(label, iso_date: str = "") -> bool:
    """A statement's "Download statement for October 06, 2026", or its text
    "October 06, 2026", for `iso_date` only. Refused with no date given."""
    label = _tidy(label)
    if not label or not iso_date or _refused(label):
        return False
    return button_date(label) == iso_date


PRESS_GUARDS = (is_balance_summary, is_view_statements, is_statement_button)


# ---------------------------------------------------------------------------
# Hosts. Exact, parsed, no subdomain wildcard.
# ---------------------------------------------------------------------------
ALLOWED_HOSTS = {HOST}
_UUID_RE = r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}"
CARD_ID_RE = re.compile(_UUID_RE)
STATEMENT_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,128}")
_LIST_PATH_RE = re.compile(r"/bilt-card/cards/(" + _UUID_RE + r")/account/statements")
_DETAILS_PATH_RE = re.compile(r"/bilt-card/cards/(" + _UUID_RE
                              + r")/account/statements/([A-Za-z0-9_-]{1,128})/details")
_PDF_PATH_RE = re.compile(r"/([A-Za-z0-9-]{1,256})_([0-9]{4}-[0-9]{2}-[0-9]{2})_Bilt\.pdf")


def is_safe_url(url: str) -> bool:
    """True only for an https URL on exactly www.bilt.com."""
    return _host_allows(url, ALLOWED_HOSTS, subdomains=False)


def _on(url, host: str):
    """The parsed address when it is https on exactly `host` with no query
    or fragment, else None."""
    if not isinstance(url, str) or not _host_allows(url, {host}, subdomains=False):
        return None
    if "?" in url or "#" in url:
        return None
    try:
        return urlsplit(url)
    except ValueError:
        return None


def is_wallet_url(url: str) -> bool:
    """The wallet itself, www.bilt.com/wallet, with nothing after it."""
    parts = _on(url, HOST)
    return parts is not None and parts.path in (WALLET_PATH, WALLET_PATH + "/")


def list_card_id(url) -> str:
    """The card id a statements answer's address names, or ""."""
    parts = _on(url, API_HOST)
    m = _LIST_PATH_RE.fullmatch(parts.path) if parts else None
    return m.group(1) if m else ""


def details_ids(url) -> Tuple[str, str]:
    """(card id, statementId) a details answer's address names, or ("", "")."""
    parts = _on(url, API_HOST)
    m = _DETAILS_PATH_RE.fullmatch(parts.path) if parts else None
    return (m.group(1), m.group(2)) if m and set(m.group(2)) != {"-"} else ("", "")


# The PDF's address is signed: the live tab opens on it with exactly these
# three query keys (a CloudFront signed URL), each once, and nothing else.
SIGNED_KEYS = ("Expires", "Signature", "Key-Pair-Id")


def _signed_pdf(url):
    """The parsed address when it is https on exactly statements.cardless.com
    with no fragment and a query that is empty or exactly the three signing
    keys, each once with a value, else None."""
    if not isinstance(url, str) or "#" in url or not _host_allows(url, {PDF_HOST}, subdomains=False):
        return None
    try:
        parts = urlsplit(url)
        pairs = parse_qsl(parts.query, keep_blank_values=True, strict_parsing=bool(parts.query))
    except ValueError:
        return None
    if "?" in url and not parts.query:
        return None
    keys = [k for k, _v in pairs]
    if pairs and (sorted(keys) != sorted(SIGNED_KEYS) or any(not v for _k, v in pairs)):
        return None
    return parts


def pdf_url_date(url) -> Optional[str]:
    """The date a statement PDF's own address carries, when it is exactly
    https://statements.cardless.com/<token>_<YYYY-MM-DD>_Bilt.pdf, bare or
    with its signing query (SIGNED_KEYS, each once), and the date exists.
    None for anything else."""
    parts = _signed_pdf(url)
    m = _PDF_PATH_RE.fullmatch(parts.path) if parts else None
    return statement_date(m.group(2)) if m else None


def pdf_token(url) -> str:
    parts = _signed_pdf(url)
    m = _PDF_PATH_RE.fullmatch(parts.path) if parts else None
    return m.group(1) if m else ""


def transactions_card_id(href) -> str:
    """The card id of the wallet's "View all" transactions link,
    /wallet/transactions?cardId=<UUID> exactly, or ""."""
    if not isinstance(href, str) or not href.startswith("/wallet/transactions?"):
        return ""
    try:
        pairs = parse_qsl(urlsplit(href).query, keep_blank_values=True)
    except ValueError:
        return ""
    if len(pairs) != 1 or pairs[0][0] != "cardId" or not CARD_ID_RE.fullmatch(pairs[0][1]):
        return ""
    return pairs[0][1]


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


def _guard_address(url) -> None:
    """Register an address that carries private parts: the whole address,
    the PDF token it names, its last path part and each query value. Only
    those, so the words every address shares, the host's and a year's,
    stay readable in the run's own lines."""
    if not isinstance(url, str) or not url.strip():
        return
    values = [url.strip(), pdf_token(url)]
    try:
        parts = urlsplit(url)
        values.append(parts.path.rsplit("/", 1)[-1])
        values += [v for _k, v in parse_qsl(parts.query, keep_blank_values=True)]
    except ValueError:
        pass
    new = sorted({v for v in values if isinstance(v, str) and len(v) >= 6} - set(private_words()))
    if new:
        set_private_words(private_words() + new)


_PROFILE_RE = re.compile(r"user profile\.?\s*(.*)", re.I | re.S)


def _guard_state(state: dict) -> None:
    """Everything on the wallet that names the holder or the card is private
    before anything is pressed: every card id a transactions link carries,
    every last four, the profile's name and the welcome line's name."""
    values = []
    for href in state.get("links") or []:
        values.append(transactions_card_id(href.get("href")) if isinstance(href, dict) else "")
    for href in state.get("summary_link") or []:
        values.append(transactions_card_id(href))
    values += [str(x) for x in state.get("summary_card") or []]
    for c in state.get("cards") or []:
        if isinstance(c, dict):
            values.append(c.get("last4"))
    for label in state.get("profile") or []:
        m = _PROFILE_RE.match(_tidy(label))
        values.append(m.group(1) if m else _tidy(label))
    for name in state.get("welcome") or []:
        values.append(_tidy(name))
    _guard_words([v for v in values if v])


# ---------------------------------------------------------------------------
# The page's own answers, heard on the browser context
# ---------------------------------------------------------------------------

def _origin(response):
    """The page whose frame asked for `response`, or None when it cannot be
    told. An answer from no known page is never this run's."""
    try:
        return response.frame.page
    except Exception:
        return None


def _status(response) -> int:
    try:
        return int(response.status)
    except Exception:
        return 0


def _signed_out_status(response) -> bool:
    status = _status(response)
    return status in (401, 403) or status in redirects.REDIRECTS or 300 <= status < 400


def _ctype(response) -> str:
    try:
        return (response.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
    except Exception:
        return ""


def _method(response) -> str:
    try:
        return str(response.request.method or "").upper()
    except Exception:
        return ""


class _Watch:
    """The page's own statements answers, heard on the browser context from
    the moment it is attached, each kept with the page that asked for it.
    Only answers from the run's own page are ever read. Nothing is read from
    an answer here but its address, method, status and page. Its body is
    read after the wait, by read_list or read_details."""

    def __init__(self):
        self.lists: list = []          # (page, response)
        self.details: list = []        # (page, response)
        self.signed_out: list = []     # pages a signed-out answer came to

    def on_response(self, response) -> None:
        try:
            url = response.url
            if not (list_card_id(url) or details_ids(url)[0]):
                return
            if _method(response) not in ("GET", ""):
                return
            origin = _origin(response)
            if _signed_out_status(response):
                self.signed_out.append(origin)
            elif list_card_id(url):
                self.lists.append((origin, response))
            else:
                self.details.append((origin, response))
        except Exception:
            pass

    def mark(self) -> Tuple[int, int]:
        return len(self.lists), len(self.details)

    def lists_since(self, mark, page) -> list:
        return [r for origin, r in self.lists[mark[0]:] if origin is page]

    def details_since(self, mark, page) -> list:
        return [r for origin, r in self.details[mark[1]:] if origin is page]

    def raise_if_signed_out(self, page) -> None:
        if any(origin is page for origin in self.signed_out):
            raise SessionExpired("Bilt answered the page's own request as signed out")


class Run:
    """What one command carries between presses: the watch on the browser
    context, and whether the browser's downloads go to the app's own folder
    (`staged`, from capture.set_download_dir). Nothing is pressed unless
    they do, so a download a press began by surprise never lands in the
    person's own Downloads. The App owns one per command."""

    def __init__(self, staged: bool = False):
        self.watch = _Watch()
        self.staged = bool(staged)
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


@dataclass(frozen=True)
class Statement:
    date: str
    statement_id: str = field(repr=False)


def _json_of(response, what: str):
    """A statements answer's JSON. A redirect, 401, 403 or HTML is Bilt
    saying the session has ended. Anything else not a 200 JSON answer stops
    the list."""
    if _signed_out_status(response):
        raise SessionExpired("the %s answer was signed out" % what)
    try:
        body = intake.body(response)
    except Exception as e:
        raise ListStopped("the %s answer could not be read (%s)" % (what, type(e).__name__))
    if _ctype(response).startswith("text/html") or body.lstrip()[:1] == b"<":
        raise SessionExpired("the %s answer was a page" % what)
    if _status(response) != 200:
        raise ListStopped("the %s answer was not 200" % what)
    try:
        return whole_json(json.loads(body.decode("utf-8")))
    except (ValueError, UnicodeDecodeError):
        raise ListStopped("the %s answer was not JSON" % what)


# What a statements answer holds, all of it. The live answer held these two
# keys and nothing else. Its count is the length of its own list, so it
# cannot show a cut list by itself, and a key beyond these two (hasMore, a
# cursor, a page, a total) may be how Bilt says there is more.
LIST_KEYS = frozenset({"statements", "count"})


def statements_of(got) -> List[Statement]:
    """The statements of one list answer. It holds nothing but its list and
    its count (LIST_KEYS), its count must be its list, every entry an object
    with a statementId of the expected shape and a calendar date, and no id
    or date twice, or the list stops."""
    if not isinstance(got, dict) or not isinstance(got.get("statements"), list):
        raise ListStopped("the statements answer is not the expected shape")
    entries = got["statements"]
    _guard_words([e.get("statementId") for e in entries if isinstance(e, dict)])
    if set(got) - LIST_KEYS:
        raise ListStopped("the statements answer holds more than its list and its count, which "
                          "may say there are more statements, so it is not read as the whole list")
    count = got.get("count")
    if isinstance(count, bool) or not isinstance(count, int) or count != len(entries):
        raise ListStopped("the statements answer's count is not its list")
    out: List[Statement] = []
    for e in entries:
        if not isinstance(e, dict):
            raise ListStopped("a statement could not be read")
        sid = e.get("statementId")
        if not isinstance(sid, str) or not STATEMENT_ID_RE.fullmatch(sid) or set(sid) == {"-"}:
            raise ListStopped("a statement's id is not one this can read")
        iso = statement_date(e.get("date"))
        if not iso:
            raise ListStopped("a statement's date is not a calendar date")
        if any(s.date == iso for s in out):
            raise ListStopped("two statements carry one date")
        if any(s.statement_id == sid for s in out):
            raise ListStopped("two statements carry one id")
        out.append(Statement(iso, sid))
    return out


def read_list(response, card_id: str) -> List[Statement]:
    """The statements of the list answer the page got, for `card_id`."""
    got_card = list_card_id(response.url)
    if not got_card or got_card != card_id:
        raise ListStopped("the statements answer is for another card")
    return statements_of(_json_of(response, "statements"))


def read_details(response, card_id: str, statement: Statement) -> str:
    """The downloadUrl of the details answer the page got for `statement`,
    held in memory only. The answer must be for this card and name this
    statement's id and date, or the run stops."""
    got_card, got_sid = details_ids(response.url)
    if got_card != card_id or got_sid != statement.statement_id:
        raise ListStopped("the details answer is for another statement")
    got = _json_of(response, "details")
    if not isinstance(got, dict):
        raise ListStopped("the details answer is not the expected shape")
    url = got.get("downloadUrl")
    _guard_address(url)
    if got.get("statementId") != statement.statement_id \
            or statement_date(got.get("date")) != statement.date:
        raise ListStopped("the details answer names another statement")
    if not isinstance(url, str) or not url.strip():
        raise ListStopped("the details answer holds no address")
    return url


# ---------------------------------------------------------------------------
# Reading the wallet. Read only, and nothing on the page is changed.
# ---------------------------------------------------------------------------
# The one card's label on the wallet, "Bilt Blue Card •••• 1234", read from
# the smallest element holding it. Live that element also holds the card's
# own "View" button, so that one word may follow the last four and nothing
# else may. The same pattern serves the page script and the tests.
CARD_LABEL_RE = re.compile(r"^Bilt [A-Za-z ]*Card\s*[•*]+\s*(\d{4})(?: View)?$")

# A control on the statements sheet that would bring more of the list than
# it shows: "Load more", "Show older statements", "More", "Older", "View all
# statements", "Next page". Read whole, from a control's text, aria-label
# or title, and for one drawn as an <input> of type button, submit, image or
# reset, which Playwright gives a button's role, from its value or an
# image's alt as well. Such an input was no control here, so a Load more
# drawn as one let a part of the list be read as whole, where a button stops
# it. A box to tick or a text field is still none. The live sheet showed
# none. One shown on the sheet stops the
# list (_no_pager), and none is ever pressed (FORBIDDEN_CONTROL_RE). "View
# all" alone is the wallet's own Recent activity link, so "all" counts only
# with "statements".
PAGER_RE = re.compile(
    r"^(?:(?:load|show|see|view)\s+(?:more|older|earlier|previous)(?:\s+statements?)?"
    r"|(?:load|show|see|view)\s+all\s+statements?"
    r"|(?:more|older|earlier|previous)(?:\s+statements?)?"
    r"|next\s+page)$", re.I)

# Bilt's sign-in as a signed-out visit to the wallet drew it on 2026-10-15,
# in place at /wallet with no password field. Either sentence, whole and as
# shown text (a text node may hold it beside others, as "Welcome to Bilt.
# Log in or sign up." did), or a shown control reading exactly "Sign up /
# Log in". Only whether it is drawn is returned, never the page's text, and
# only where no balance summary button shows is it read as signed out
# (shows_sign_in).
SIGN_IN_SENTENCES = ("Complete login to continue", "Log in or sign up")
SIGN_IN_CONTROL = "Sign up / Log in"

_SIGNIN_FN = r"""
  const signinDrawn = () => {
    const sentences = %s, control = %s;
    const root = document.body || document.documentElement;
    if (!root) return false;
    const walk = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    for (let n = walk.nextNode(); n; n = walk.nextNode()) {
      if (!shown(n.parentElement)) continue;
      for (const part of tidy(n.nodeValue).split(/(?<=[.!?])\s+/))
        if (sentences.includes(part.replace(/[.!?]+$/, ''))) return true;
    }
    for (const el of root.querySelectorAll('button, [role="button"], a, [role="link"]'))
      if (shown(el) && tidy(el.innerText) === control) return true;
    return false;
  };""" % (json.dumps(list(SIGN_IN_SENTENCES)), json.dumps(SIGN_IN_CONTROL))

_SHOWN_FN = r"""
  const tidy = s => (s || '').replace(/\s+/g, ' ').trim();
  const shown = el => !!el && !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length)
                      && getComputedStyle(el).visibility !== 'hidden';"""

# The sign-in question alone, for looks_signed_out. It returns whether the
# sign-in is drawn and which balance summary buttons show, and nothing else.
_SIGNIN_JS = r"""() => {%s%s
  return {signin: signinDrawn(),
          summary: Array.from(document.querySelectorAll('[aria-label="View balance summary"]'))
            .map(el => ({shown: shown(el), tag: el.tagName}))};
}""" % (_SHOWN_FN, _SIGNIN_FN)

_STATE_JS = r"""() => {
  const CARD_LABEL_PATTERN = %s;
  const PAGER_PATTERN = %s;%s%s
  const out = {path: location.pathname, password: !!document.querySelector("input[type='password']"),
               signin: signinDrawn(),
               summary: [], openers: [], statements: [], links: [], cards: [], profile: [], welcome: []};
  for (const el of document.querySelectorAll('[aria-label="View balance summary"]'))
    out.summary.push({shown: shown(el), tag: el.tagName});
  for (const el of document.querySelectorAll('[role="button"], button'))
    if (tidy(el.innerText) === 'View statements') out.openers.push({shown: shown(el), tag: el.tagName});
  for (const el of document.querySelectorAll('[aria-label^="Download statement for "]'))
    out.statements.push({aria: tidy(el.getAttribute('aria-label')), text: tidy(el.innerText),
                         title: tidy(el.getAttribute('title')), shown: shown(el), tag: el.tagName});
  for (const a of document.querySelectorAll('a[href^="/wallet/transactions?cardId="]'))
    out.links.push({href: a.getAttribute('href') || '', shown: shown(a)});
  // The label's smallest element on the live wallet holds the name, the
  // masked number and the card's own "View" button, so that one word may
  // follow the last four.
  const card = new RegExp(CARD_LABEL_PATTERN);
  for (const el of document.querySelectorAll('body *')) {
    const t = tidy(el.innerText);
    if (!card.test(t) || !shown(el)) continue;
    if (Array.from(el.children).some(c => card.test(tidy(c.innerText)))) continue;
    out.cards.push({last4: t.match(card)[1]});
  }
  // The card the balance summary button sits under: the nearest enclosing
  // element holding a card label, and from there the nearest holding a
  // transactions link. Both have to be the wallet's one card and link.
  const leafCards = root => {
    const found = [];
    for (const el of root.querySelectorAll('*')) {
      const t = tidy(el.innerText);
      if (!card.test(t) || !shown(el)) continue;
      if (Array.from(el.children).some(c => card.test(tidy(c.innerText)))) continue;
      found.push(t.match(card)[1]);
    }
    return found;
  };
  out.summary_card = []; out.summary_link = [];
  const sums = Array.from(document.querySelectorAll('[aria-label="View balance summary"]')).filter(shown);
  if (sums.length === 1) {
    let el = sums[0].parentElement;
    while (el && el !== document.documentElement) {
      const fours = leafCards(el);
      if (fours.length) { out.summary_card = fours; break; }
      el = el.parentElement;
    }
    while (el && el !== document.documentElement) {
      const links = Array.from(el.querySelectorAll('a[href^="/wallet/transactions?cardId="]'))
        .filter(shown).map(a => a.getAttribute('href') || '');
      if (links.length) { out.summary_link = links; break; }
      el = el.parentElement;
    }
  }
  // The statements sheet: from the smallest element holding every statement
  // button, up to the last element that holds none of the wallet's own
  // controls (the balance summary button, the transactions link). A shown
  // control in it that would bring more statements is counted, never named.
  out.pagers = [];
  const rows = Array.from(document.querySelectorAll('[aria-label^="Download statement for "]'));
  if (rows.length) {
    const pager = new RegExp(PAGER_PATTERN, 'i');
    const walletOwn = el => !!el.querySelector(
      '[aria-label="View balance summary"], a[href^="/wallet/transactions?cardId="]');
    let sheet = rows[0].parentElement;
    while (sheet && !rows.every(b => sheet.contains(b))) sheet = sheet.parentElement;
    while (sheet && sheet.parentElement && sheet.parentElement !== document.body
           && sheet.parentElement !== document.documentElement && !walletOwn(sheet.parentElement))
      sheet = sheet.parentElement;
    const controls = 'button, [role="button"], a, [role="link"], input[type="button"], input[type="submit"], '
      + 'input[type="image"], input[type="reset"]';
    for (const el of (sheet ? sheet.querySelectorAll(controls) : [])) {
      if (!shown(el)) continue;
      const said = [el.innerText, el.getAttribute('aria-label'), el.getAttribute('title'),
                    el.tagName === 'INPUT' ? el.value : '', el.getAttribute('alt')].map(tidy);
      if (said.some(s => s && pager.test(s))) out.pagers.push(1);
    }
  }
  for (const el of document.querySelectorAll('[aria-label^="User profile"]'))
    out.profile.push(tidy(el.getAttribute('aria-label')));
  const body = (document.body && document.body.innerText) || '';
  for (const m of body.matchAll(/Welcome, ([^\n]{1,80})/g)) out.welcome.push(tidy(m[1]));
  return out;
}""" % (json.dumps(CARD_LABEL_RE.pattern), json.dumps(PAGER_RE.pattern), _SHOWN_FN, _SIGNIN_FN)

_LABELS_JS = r"""el => [el.innerText, el.getAttribute('aria-label'), el.getAttribute('title')]
  .map(s => (s || '').replace(/\s+/g, ' ').trim()).filter(Boolean)"""


def _read(page) -> dict:
    """What the wallet shows now. A page that cannot be read stops the
    list. Every private word it carries is registered before it is
    returned."""
    try:
        state = page.evaluate(_STATE_JS)
    except Exception as e:
        raise ListStopped("the wallet could not be read (%s)" % type(e).__name__)
    if not isinstance(state, dict):
        raise ListStopped("the wallet could not be read")
    _guard_state(state)
    return state


def _pause(page, ms: float) -> None:
    page.wait_for_timeout(ms)


def _wait_for(page, run: Run, ready: Callable[[dict], bool], timeout_ms: int) -> Optional[dict]:
    """Read the page until `ready` holds, or None once `timeout_ms` has
    gone. The session is asked before and after every poll."""
    waited = 0
    while True:
        check_signed_in(page)
        run.watch.raise_if_signed_out(page)
        state = _read(page)
        if shows_sign_in(state) and _sign_in_holds(page):
            raise SessionExpired("Bilt drew its sign-in on the wallet")
        if ready(state):
            return state
        if waited >= timeout_ms:
            return None
        _pause(page, POLL_MS)
        waited += POLL_MS
        check_signed_in(page)


def _settle(page, run: Run) -> None:
    _pause(page, SETTLE_MS)
    check_signed_in(page)
    run.watch.raise_if_signed_out(page)


def _shown(items) -> list:
    return [x for x in items or [] if isinstance(x, dict) and x.get("shown")]


def card_of(state: dict) -> Tuple[str, str]:
    """(card id, last four) of the one Bilt Card the wallet shows, or
    ("", "") when it shows none, more than one, or a link this cannot read.
    The card label and the transactions link nearest the balance summary
    button have to be that one card's, so a label and a link of two cards
    are never taken for one."""
    ids = {transactions_card_id(x.get("href")) for x in _shown(state.get("links"))}
    fours = {str(c.get("last4") or "") for c in state.get("cards") or [] if isinstance(c, dict)}
    if len(ids) != 1 or "" in ids or len(fours) != 1 or not re.fullmatch(r"[0-9]{4}", next(iter(fours))):
        return "", ""
    near_fours = [str(x) for x in state.get("summary_card") or []]
    near_ids = {transactions_card_id(h) for h in state.get("summary_link") or []}
    if near_fours != list(fours) or near_ids != ids:
        return "", ""
    return next(iter(ids)), next(iter(fours))


def _wallet_ready(state: dict) -> bool:
    return state.get("path") == WALLET_PATH and len(_shown(state.get("summary"))) == 1 \
        and all(x.get("tag") == "BUTTON" for x in _shown(state.get("summary"))) \
        and bool(card_of(state)[0])


def _no_pager(state: dict) -> None:
    """Stop the list when the statements sheet shows a control that would
    bring more of it (PAGER_RE). The answer and the sheet would then agree
    on a part of the list, and nothing would say so."""
    if state.get("pagers"):
        raise ListStopped("the statements sheet shows a control for more or older statements, "
                          "so what it shows may be only a part of the list")


def sheet_dates(state: dict) -> Optional[List[str]]:
    """The dates of the statement buttons the sheet shows, sorted, or None
    when a button is hidden, is not a button, or does not read exactly one
    date in its aria-label and the same date in its text."""
    out = []
    for b in state.get("statements") or []:
        if not isinstance(b, dict) or not b.get("shown") or b.get("tag") != "BUTTON":
            return None
        aria = STATEMENT_ARIA_RE.fullmatch(_tidy(b.get("aria")))
        iso = _from_words(aria) if aria else None
        if not iso or button_date(b.get("text")) != iso or (b.get("title") and button_date(b.get("title")) != iso):
            return None
        out.append(iso)
    return sorted(out)


# ---------------------------------------------------------------------------
# Pressing. Every press goes through _press, with one of the three guards.
# ---------------------------------------------------------------------------

def _labels_of(locator) -> List[str]:
    try:
        labels = locator.evaluate(_LABELS_JS)
    except Exception:
        return []
    return [str(x) for x in labels or [] if str(x or "").strip()]


def _press(page, locator, *, what: str, guard, step: str, run: Run,
           expect: Optional[str] = None, leave_if_off: bool = False) -> bool:
    """Press one control, once, through the core, after every label it
    carries has passed `guard`, one of PRESS_GUARDS. A control that is not
    exactly one shown element, or a label refused, stops the list and
    nothing is pressed. True once pressed.

    A control the page has turned off is not pressed (pressing.TurnedOff).
    For the two controls that open the list that stops the list, since
    every statement sits behind them. With `leave_if_off`, for a
    statement's own button, it returns False instead: nothing was pressed,
    and that one statement is left for the next run while the run goes on.
    Anything else the core raises (covered, unreadable) still stops the
    run."""
    if guard not in PRESS_GUARDS:
        raise ListStopped("a press was asked for with no guard of this app's own")
    if not run.staged:
        raise ListStopped("the browser's download folder could not be set, so nothing is pressed")
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
        pressing.click(page, locator, css=pressing.BUTTONS, what=what, words=_words(), step=step)
    except pressing.TurnedOff:
        if not leave_if_off:
            raise ListStopped("%s is turned off on the page" % what)
        log.info("%s is turned off on the page, and nothing was pressed", what)
        return False
    check_signed_in(page)
    return True


def _button(page, label: str):
    """The one button whose accessible name is `label`, exactly."""
    return page.get_by_role("button", name=label, exact=True)


# The "View statements" control is a role=button div whose accessible name
# also carries the name of an icon button nested inside it ("View
# statements action-right" on the live sheet), so a role query by its exact
# name misses it. It is found among the shown buttons by its own text.
OPENER_CSS = 'button, [role="button"]'
STATEMENTS_TEXT_RE = re.compile(r"^\s*View statements\s*$")


def _view_statements(page):
    """The one shown button whose text is exactly "View statements"."""
    return page.locator(OPENER_CSS).filter(has_text=STATEMENTS_TEXT_RE).filter(visible=True)


# ---------------------------------------------------------------------------
# The wallet and its statements list
# ---------------------------------------------------------------------------

@dataclass
class Listing:
    card_id: str = field(repr=False)
    last4: str = field(repr=False)
    statements: List[Statement]


def _open(page, run: Run) -> Tuple[str, str, Tuple[int, int]]:
    """Load the wallet afresh, with the context's watch already listening,
    and wait for it to show one Bilt Card with its "View balance summary".
    Every private word on the wallet is registered from here on. Nothing is
    pressed. Returns the card id, its last four and the watch's mark taken
    before the load."""
    run.attach(page.context)
    mark = run.watch.mark()
    try:
        page.goto(WALLET_URL, wait_until="domcontentloaded", timeout=60000)
    except Exception as e:
        log.info("opening the wallet failed (%s)", type(e).__name__)
        check_signed_in(page)
        raise ListStopped("the wallet did not open")
    check_signed_in(page)
    if not is_wallet_url(page.url or ""):
        raise ListStopped("the wallet settled off its own address")
    state = _wait_for(page, run, _wallet_ready, READY_WAIT_MS)
    if state is None:
        raise ListStopped("the wallet does not show one Bilt Card with its balance summary")
    card_id, last4 = card_of(state)
    return card_id, last4, mark


def read_listing(page, run: Optional[Run] = None) -> Listing:
    """Open the wallet, press "View balance summary" and then "View
    statements", and read the list whole: exactly one statements answer
    heard from this page since the load, for the card the wallet shows,
    holding only its list and count, and the sheet showing exactly its
    dates, one button each, and no control for more, read again alike after
    the page settles. Raises ListStopped for anything else, SessionExpired
    for a signed-out session."""
    run = run or Run()
    card_id, last4, mark = _open(page, run)
    _press(page, _button(page, SUMMARY_LABEL), what="the balance summary button",
           guard=is_balance_summary, step="open the balance summary", run=run)
    if _wait_for(page, run, lambda s: len(_shown(s.get("openers"))) == 1, LIST_WAIT_MS) is None:
        raise ListStopped("the balance summary did not show View statements")
    _press(page, _view_statements(page), what="View statements",
           guard=is_view_statements, step="open the statements", run=run)
    got: dict = {}

    def ready(state: dict) -> bool:
        _no_pager(state)
        answers = run.watch.lists_since(mark, page)
        if len(answers) > 1:
            raise ListStopped("the page asked for the statements more than once")
        if not answers:
            return False
        if "statements" not in got:
            got["statements"] = read_list(answers[0], card_id)
        return sheet_dates(state) == sorted(s.date for s in got["statements"])

    if _wait_for(page, run, ready, LIST_WAIT_MS) is None:
        if not run.watch.lists_since(mark, page):
            raise ListStopped("no statements answer came")
        raise ListStopped("the sheet's statements do not match the statements answer")
    _settle(page, run)
    state = _read(page)
    if not ready(state) or card_of(state) != (card_id, last4):
        raise ListStopped("the statements changed while the list was read")
    return Listing(card_id, last4, list(got["statements"]))


@dataclass
class RawDoc:
    title: str
    account: str = ""
    date_text: str = ""
    href: str = ""
    text: str = ""
    row_index: int = -1
    kind: str = "doc"
    # Bilt's statementId. Private: never logged or in a name.
    document_id: str = ""
    # Bilt's card id. Private: kept in the run's own records only, to know
    # the card again.
    card_id: str = ""


TITLE = "Card Statement"
ACCOUNT = "Bilt Card"


def collect_download_docs(page, run: Optional[Run] = None) -> List[RawDoc]:
    """Every statement the wallet lists for its one Bilt Card. Raises
    ListStopped (holding nothing, since a list not read whole is not
    called read) and SessionExpired."""
    listing = read_listing(page, run)
    docs = [RawDoc(title=TITLE, account=ACCOUNT, date_text=s.date, text=TITLE, kind="statement",
                   document_id=s.statement_id, card_id=listing.card_id)
            for s in listing.statements]
    log.info("%s: %d statement(s)", ACCOUNT, len(docs))
    return docs


def goto_documents(page, run: Optional[Run] = None) -> bool:
    """Open the wallet and prove it shows the Bilt Card. False when it
    showed the sign-in page or did not. Nothing is pressed."""
    try:
        _open(page, run or Run())
        return True
    except (SessionExpired, ListStopped) as e:
        log.info("the wallet did not open: %s", type(e).__name__)
        return False


def scroll_full_page(page, rounds: int = 0, delay_ms: int = 0) -> None:
    """Nothing to scroll: the sheet lists every statement."""
    return None


def expand_all(page) -> None:
    """Nothing is pressed beyond the three controls in the module docstring."""
    return None


# ---------------------------------------------------------------------------
# One statement
# ---------------------------------------------------------------------------

@dataclass
class Target:
    """The statement to take and what binds the PDF to it: its date, its
    id, the card's id and last four, and the dates of the statements beside
    it in the list, which its PDF must not be mistaken for."""
    date: str
    statement_id: str = field(repr=False)
    card_id: str = field(repr=False)
    last4: str = field(repr=False)
    rivals: tuple = ()

    @property
    def statement(self) -> Statement:
        return Statement(self.date, self.statement_id)


def _stop(said: str, reason: str):
    return pressing.no_answer("save the statement", reason, said)


def _still_on_bilt(page) -> None:
    """Stop the run when the run's own tab has left www.bilt.com since the
    statement's button was pressed. A tab that opened the PDF while sending
    its opener elsewhere is not the page's own behavior, so nothing is kept.
    Asked through every wait after the press and just before saving."""
    try:
        where = page.url or ""
    except Exception:
        where = ""
    if not is_safe_url(where):
        raise _stop("The wallet's tab left Bilt after the statement's button was pressed, so "
                    "nothing was taken.", "the wallet left bilt")


def _navigation(response) -> bool:
    """A document answer a page went to, not one of its inner frames'. A
    popup's first answer can come before Playwright knows its page, and its
    frame cannot be read then, and that still counts as a navigation."""
    try:
        if not response.request.is_navigation_request():
            return False
    except Exception:
        return False
    try:
        return response.frame.parent_frame is None
    except Exception:
        return True


def _opener(p):
    try:
        return p.opener()
    except Exception:
        return None


def _host_of(url) -> str:
    try:
        return (urlsplit(url or "").hostname or "").lower()
    except ValueError:
        return ""


def _close_all(pages: list) -> bool:
    """Close every page the press opened, and confirm each is closed. False
    when one would not close or cannot be asked."""
    ok = True
    for p in pages:
        try:
            if not p.is_closed():
                p.close()
            if not p.is_closed():
                ok = False
        except Exception:
            ok = False
    return ok


def _exactly(want: str):
    def guard(url) -> bool:
        return isinstance(url, str) and url == want and pdf_url_date(url) is not None
    return guard


def _pdf_bytes(page, url: str, heard: list, trace) -> bytes:
    """The PDF the popup holds: the body of its own navigation answer when
    Playwright can read it, else its exact address asked once more with the
    browser's cookies and no redirect followed. b"" when neither gives a
    PDF. Only the way it came is said in the trace."""
    for r in heard:
        if _status(r) != 200:
            continue
        try:
            body = intake.body(r)
        except Exception:
            body = b""
        if body[:5] == b"%PDF-":
            _note(trace, note="the popup's own answer was read", how="heard")
            return body
    try:
        resp = redirects.get(page.context.request, url, _exactly(url), hops=0, timeout=60000)
    except Exception as e:
        _note(trace, note="asking the popup's address again failed", error=type(e).__name__)
        return b""
    if _status(resp) != 200:
        _note(trace, note="asking the popup's address again was not answered 200")
        return b""
    try:
        body = intake.body(resp)
    except Exception:
        body = b""
    _note(trace, note="the popup's address was asked again", how="asked")
    return body if body[:5] == b"%PDF-" else b""


def _note(trace, **what) -> None:
    if trace is not None:
        trace.append(what)


def _catch_statement(page, run: Run, target: Target, out_path: Path,
                     trace: Optional[list] = None, own_files=()) -> Optional[bool]:
    """Press the bound statement's own button once and take the PDF the tab
    it opens holds.

    Heard from the press on: every tab the run's page opens, every browser
    download on the page or on such a tab (observation only: counted,
    canceled and its file deleted), every navigation answer of such a tab or
    of a page that cannot be told (so another tab can make this stop but
    never makes it take the wrong file), and the page's own details answer.
    The statement is taken only when exactly one tab opened, no download
    began, the details answer named this statement, the tab's address and
    every navigation answer are on statements.cardless.com at a PDF address
    of the statement's date, and a downloadUrl on that host is the tab's own
    address. The tab is closed before anything is kept. Anything else stops
    the run: nothing more is pressed for this or any later statement.

    None when the page has turned the button off: nothing was pressed,
    nothing is waited for, and the statement is left for the next run.
    `own_files` are this statement's own copies saved before (bind)."""
    out_path = Path(out_path)
    run.attach(page.context)
    button = _button(page, statement_label(target.date))
    # Every page the press opened, directly or through a page it opened,
    # in the order heard. Only these are ever closed.
    popups: list = []
    downloads: list = []
    navs: list = []
    armed = [False]

    # Observation only: a download the press began is counted and canceled,
    # and its file, if the browser had already written one, deleted. Nothing
    # of it is read or saved.
    def on_download(download):
        downloads.append(1)
        intake.discard(download)

    def on_page(p):
        if not armed[0]:
            return
        opener = _opener(p)
        if opener is not page and not any(opener is q for q in popups):
            return  # another tab's page: not this run's to hear or close
        popups.append(p)
        try:
            p.on("download", on_download)
        except Exception:
            pass

    def on_nav(response):
        if not armed[0] or not _navigation(response):
            return
        origin = _origin(response)
        if origin is None or any(origin is p for p in popups):
            navs.append(response)

    page.on("download", on_download)
    page.context.on("page", on_page)
    page.context.on("response", on_nav)
    mark = run.watch.mark()
    data = b""
    try:
        armed[0] = True
        if not _press(page, button, what="the statement's button", guard=is_statement_button,
                      expect=target.date, step="save the statement", run=run, leave_if_off=True):
            _note(trace, note="the statement's button was turned off")
            return None
        waited = 0
        while not (popups and run.watch.details_since(mark, page)):
            check_signed_in(page)
            _still_on_bilt(page)
            run.watch.raise_if_signed_out(page)
            if downloads or len(popups) > 1:
                break
            if waited >= POPUP_WAIT_MS:
                _close_all(popups)
                _note(trace, note="no tab or no details answer came", tabs=len(popups))
                raise _stop("The statement's button was pressed and no statement tab came.",
                            "no statement tab came")
            _pause(page, POLL_MS)
            waited += POLL_MS
        waited = 0
        while waited < SECOND_WAIT_MS:
            _pause(page, POLL_MS)
            waited += POLL_MS
            _still_on_bilt(page)
        check_signed_in(page)
        run.watch.raise_if_signed_out(page)
        data = _take(page, run, target, popups, downloads, navs, mark, trace)
        if len(popups) != 1 or downloads:
            # A page or a download that came while the PDF was read.
            raise _stop("Something more came while the statement was taken, so it was not kept.",
                        "more came while the statement was taken")
    finally:
        armed[0] = False
        for source, name, fn in ((page, "download", on_download), (page.context, "page", on_page),
                                 (page.context, "response", on_nav)):
            try:
                source.remove_listener(name, fn)
            except Exception:
                pass
        # Whatever ended the capture, no page the press opened is left open.
        _close_all(popups)
    _still_on_bilt(page)
    why = bind(data, target, out_path, trace, own_files)
    if why:
        log.info("the PDF of the statement dated %s was not kept: %s", target.date, why)
        raise _stop("The statement's PDF was not kept, since %s." % why, "the pdf is not this statement")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(data)
    _KEPT[hashlib.sha256(data).hexdigest()] = target.statement_id
    _note(trace, note="statement kept")
    return True


def _take(page, run: Run, target: Target, popups: list, downloads: list, navs: list,
          mark, trace) -> bytes:
    """What the press brought, checked, its tab closed. Raises a stop of
    the run for anything but one tab holding this statement's PDF."""
    def give_up(said: str, reason: str):
        _close_all(popups)
        _note(trace, note=reason, tabs=len(popups), downloads=len(downloads))
        return _stop(said, reason)

    if downloads:
        raise give_up("The statement's button began a browser download, so nothing was taken.",
                      "a download began")
    if len(popups) != 1 or _opener(popups[0]) is not page:
        raise give_up("The statement's button opened %d tabs, so nothing was taken." % len(popups),
                      "the press did not open one tab")
    popup = popups[0]
    try:
        popup.wait_for_load_state("domcontentloaded", timeout=POPUP_WAIT_MS)
    except Exception:
        pass
    try:
        url = popup.url or ""
    except Exception:
        raise give_up("Where the statement's tab went could not be read, so nothing was taken.",
                      "the tab could not be read")
    _guard_address(url)
    if _first_part(url) in LOGIN_PATHS and _host_of(url) == HOST:
        _close_all(popups)
        raise SessionExpired("the statement's tab landed on the sign-in page")
    if _host_of(url) != PDF_HOST:
        raise give_up("The statement's tab opened on another host, so nothing was taken.",
                      "the tab is on another host")
    if pdf_url_date(url) != target.date:
        raise give_up("The statement's tab is not this statement's PDF address, so nothing "
                      "was taken.", "the tab's address is not this statement's")
    went = []
    for r in navs:
        try:
            went.append(r.url or "")
        except Exception:
            went.append("")
    if any(u != url for u in went):
        raise give_up("The statement's tab went through another address, so nothing was taken.",
                      "the tab went elsewhere")
    if any(_signed_out_status(r) for r in navs):
        _close_all(popups)
        raise SessionExpired("the statement's address answered as signed out")
    answers = run.watch.details_since(mark, page)
    if len(answers) != 1:
        raise give_up("The page asked for %d statement details, so nothing was taken." % len(answers),
                      "not one details answer")
    try:
        download_url = read_details(answers[0], target.card_id, target.statement)
    except ListStopped as e:
        raise give_up("The page's details answer did not name this statement, so nothing was "
                      "taken.", str(e))
    same_host = _host_of(download_url) == PDF_HOST
    _note(trace, note="details answer", same_host=same_host, same_address=download_url == url)
    if same_host and download_url != url:
        raise give_up("The page named another PDF address than the tab opened, so nothing was "
                      "taken.", "the details answer names another address")
    data = _pdf_bytes(page, url, [r for r in navs if (r.url or "") == url], trace)
    if not _close_all(popups):
        raise _stop("The statement's tab could not be closed, so nothing was taken.",
                    "the tab stayed open")
    if not data:
        raise _stop("The statement's tab did not hold a PDF, so nothing was taken.",
                    "the tab held no pdf")
    return data


# ---------------------------------------------------------------------------
# Binding the bytes to the statement
# ---------------------------------------------------------------------------
# sha256 of each statement this process kept, with its statementId. Bytes
# one statement already gave are never kept for another.
_KEPT: dict = {}

# A card number as a statement masks it: "ending in 1234", "•••• 1234",
# "**** 1234", "XXXX XXXX XXXX 1234". The four digits are compared with the
# card's last four and never kept.
MASKED_FOUR_RE = re.compile(
    r"(?:ending\s+in|ends\s+in|[•*xX]{2,}[\s-]*)(?:[•*xX\s-]*)(\d{4})(?!\d)", re.I)


def pdf_text(data: bytes, pages: int = 5) -> str:
    """The text of the first pages of a PDF held in memory, or "". Never
    logged, never written."""
    try:
        return whole_characters("\n".join(pdf_reader.page_texts(data, max(1, pages))))
    except Exception:
        return ""


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


def bind(data: bytes, target: Target, out_path: Path, trace: Optional[list] = None,
         own_files=()) -> str:
    """An empty string when the bytes are this statement's PDF, beyond the
    tab's address having named its date. The bytes are a PDF, its text
    prints the statement's date, it does not print a neighboring
    statement's date in place of this one's, when it prints masked card or
    account numbers the card's last four is among them (a statement may
    also name the account a payment came from), and it is not the same file
    as a statement kept earlier in this process or a PDF already in the
    folder. This statement's own copies from before (`own_files`, the file
    its record names) are left out of that last comparison, so a Download
    again that gets the very bytes of the copy still on disk is no copy of
    another statement. Otherwise our own words for what was wrong. Only
    names and yes or no go into the trace."""
    if not data or data[:5] != b"%PDF-":
        return "it is not a PDF"
    text = pdf_text(data)
    own = Identity(date=target.date)
    verdict = verify(None, own, text=text)
    _note(trace, note="date check", verdict=verdict.report())
    if verdict.outcome != VERIFIED:
        return "the PDF does not print the statement's date"
    told = distinguish(None, own, [Identity(date=d) for d in target.rivals if d != target.date],
                       text=text)
    _note(trace, note="rival check", verdict=told.report())
    if told.outcome == REFUSED:
        return "the PDF prints another statement's date in place of this one's"
    fours = set(MASKED_FOUR_RE.findall(text))
    _note(trace, note="card check", masked=bool(fours), card_among=target.last4 in fours)
    if fours and target.last4 not in fours:
        return "the PDF prints another card's number"
    digest = hashlib.sha256(data).hexdigest()
    other = _KEPT.get(digest)
    if other is not None and other != target.statement_id:
        return "the PDF is the same file as another statement kept in this run"
    same = _same_file_in(Path(out_path).parent, data, [out_path, *own_files])
    if same is None:
        return "the folder could not be read to compare the PDF with those saved"
    if same:
        return "the PDF is the same file as one already saved"
    return ""


def _neighbors(statements: List[Statement], iso: str) -> tuple:
    dates = sorted(s.date for s in statements)
    if iso not in dates:
        return ()
    i = dates.index(iso)
    return tuple(dates[max(0, i - 1):i] + dates[i + 1:i + 2])


def download_statement(page, run: Run, out_path, *, card_id: str, statement_id: str,
                       iso_date: str, trace: Optional[list] = None,
                       own_files=()) -> Optional[bool]:
    """Save the statement discovery recorded. The wallet is loaded afresh
    and the list read whole again, and exactly one entry must carry the
    record's statementId and date, for the record's card, before that one
    statement's button is pressed. False, with nothing pressed on a
    statement, when it is not there. None when its button is turned off on
    the page: nothing was pressed on it, and the statement is left for the
    next run. A list that stops on the way stops the run with pressing.Stop,
    since the next statement would meet the same page. SessionExpired and
    every other stop of the run propagate. `own_files` are the statement's
    own copies saved before, the file its record names, which a Download
    again may get the very bytes of (bind)."""
    out_path = Path(out_path)
    if not (card_id and CARD_ID_RE.fullmatch(card_id) and isinstance(statement_id, str)
            and STATEMENT_ID_RE.fullmatch(statement_id) and statement_date(iso_date) == iso_date):
        _note(trace, note="the record does not name one statement")
        return False
    try:
        listing = read_listing(page, run)
    except ListStopped as stop:
        log.info("the list stopped while looking for the statement dated %s: %s", iso_date, stop)
        _note(trace, note="the list stopped")
        raise _page_stopped(stop)
    if listing.card_id != card_id:
        _note(trace, note="the wallet shows another card")
        return False
    found = [s for s in listing.statements if s.statement_id == statement_id and s.date == iso_date]
    if len(found) != 1:
        _note(trace, note="no single statement matches the record", matches=len(found))
        return False
    target = Target(iso_date, statement_id, card_id, listing.last4,
                    _neighbors(listing.statements, iso_date))
    try:
        return _catch_statement(page, run, target, out_path, trace, own_files=own_files)
    except ListStopped as stop:
        log.info("the statement dated %s was not saved: %s", iso_date, stop)
        _note(trace, note="the statement's button was not pressed")
        raise _page_stopped(stop)


def _page_stopped(stop: ListStopped) -> pressing.Stop:
    """A stop of the wallet while a statement was sought, as a stop of the
    run that leaves the list unread, so the panel offers a run that reads
    it first rather than Continue, which would meet the same list (#124).
    Its words are this app's own, never the page's. An opener may have been
    pressed on the way, so it counts as a stop after a press."""
    return pressing.Stop("find the statement", "the statements list stopped", [
        "The statements list stopped before this statement was saved, since %s." % stop,
        "Nothing more was pressed, and the run stops here rather than meet the same page "
        "for the next statement."], after_a_press=True, list_unread=True)


def record_hash(statement_id: str) -> str:
    """A stable, non-reversible name for a statementId, the record's
    identity, which itself is never output."""
    return hashlib.sha256(("bilt\0%s" % (statement_id or "")).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Diagnose. Reads only, presses nothing. No screenshot.
# ---------------------------------------------------------------------------

def collect_documents(page) -> List[RawDoc]:
    """The statement buttons drawn now, by date only, and nothing that names
    the card."""
    try:
        state = _read(page)
    except (ListStopped, SessionExpired):
        return []
    out = []
    for b in state.get("statements") or []:
        iso = button_date(b.get("aria")) if isinstance(b, dict) else None
        out.append(RawDoc(title="Statement button", date_text=iso or "", text="statement button",
                          row_index=len(out)))
    return out


def survey(page, dwell_ms: int = 4000, max_follow: int = 0) -> dict:
    """What the signed-in wallet looks like, by counts, without pressing or
    downloading anything. No label of the page's own leaves here."""
    page.wait_for_timeout(dwell_ms)
    try:
        state = _read(page)
    except (ListStopped, SessionExpired):
        return {"pages": [{"read": False}]}
    return {"pages": [{
        "read": True, "on_wallet": state.get("path") == WALLET_PATH,
        "balance_summary_buttons": len(_shown(state.get("summary"))),
        "view_statements_controls": len(_shown(state.get("openers"))),
        "transactions_links": len(_shown(state.get("links"))),
        "bilt_cards_shown": len(state.get("cards") or []),
        "one_card_read": bool(card_of(state)[0]),
        "statement_buttons": len(state.get("statements") or []),
        "statement_buttons_readable": sheet_dates(state) is not None,
        "pager_controls": len(state.get("pagers") or []),
    }]}
