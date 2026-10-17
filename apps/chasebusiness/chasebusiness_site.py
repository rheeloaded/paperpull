"""ALL Chase business document-center selectors, URLs and page behavior live
here.

When Chase changes its business document center, repair this file only.

STATUS: built from the account owner's survey of a signed-in business
profile on 2026-10-12 and run live on it on 2026-10-13 (10 statements,
Discover, Pilot and Run All, every PDF opened). The business card's row
shape was surveyed live on 2026-10-17, when its first statement came.

WHAT THE SURVEY ESTABLISHED
  * Everything is on one host, https://secure.chase.com. The document center
    is the dashboard's route #/dashboard/documents/myDocs/index, opened here
    by its address and proven ready by what it draws (_open).
  * The page is an ACCOUNT MENU plus ONE ACCORDION PER DOCUMENT TYPE for the
    account the menu has selected. A menu entry is `a[id^="bottom-"]`, its
    id `bottom-<accountId>`, its label "<NAME> (...1234)", and the selected
    one also reads ", current selection". Statements are the accordion
    `#button-accountsAccordian-STATEMENTS` (sic).
  * Choosing an account, opening the accordion and choosing a year in the
    "View:" picker each make the page itself POST
        /svc/rr/documents/secure/idal/v2/docref/list
        accountFilter=<accountId>&dateFilter.idalDateFilterType=CURRENT_YEAR[_MINUS_n]
    and draw the answer's idaldocRefs as rows of #accountsTable-STATEMENTS,
    "Sep 30, 2026 | Statement | 2 pages". An empty year leaves idaldocRefs
    out. Rows do NOT name the account, so a statement's account is the menu
    entry proven current before its list was read.
  * A row saves its statement one of two ways. A checking row carries a
    two-step menu: "<date> Opens menu to save document" opens it, and "Save
    as PDF" makes the browser download the PDF from secure.chase.com. A
    business card row carries no menu. Its third cell holds two links,
    a#accountsTable-STATEMENTS-row<N>-cell3-requestThisDocumentAnchor-pdf
    "<date> , opens document" and the same id ending -download, "<date>
    Saves document", and the second makes the browser download the PDF
    from the same path, with no new tab. The address carries a per-click
    key and a csrf token, so it is never built here. The press is made and
    the download taken. A row with both shapes or neither stops the list.

THE SEVEN PRESSES. Nothing else is ever pressed. Each is proven by _guarded,
which reads every label the control carries and asks this module's own
predicate for that kind of control, and only then handed to the core
(pressing.click), which presses nothing that something covers and stops the
run instead. The first four go through _press, and a turned off one stops
the run, since every statement after it is reached through it. The last
three are a statement's own and go through _press_row, which leaves that
statement for review when the site has turned its control off:
  1. an account menu entry (is_account_entry)
  2. the STATEMENTS accordion, only while it is closed (is_statements_accordion)
  3. the "View:" year picker (is_year_picker)
  4. one year's option in it, never the year already selected (is_year_option)
  5. the bound row's save menu (is_save_menu)
  6. its "Save as PDF", never the accessible variant (is_save_as_pdf)
  7. a card row's "<date> Saves document", never its "opens document"
     (is_saves_document)
Every press that changes the list is made while the page's own answer is
awaited (page.expect_response) and counted (_Heard): exactly one answer for
that account and that year, or the list stops. Nothing here closes a dialog,
presses "Stay signed in", types, scrolls, or selects.

SAFETY (a business bank account that can pay, wire, collect and approve):
  This module is strictly READ-ONLY. FORBIDDEN_CONTROL_RE and the core's
  settings and sign-in guards refuse any label that could pay, transfer,
  wire, send, collect, deposit, approve, order, enroll, change a setting or
  sign out. A control must also match one of the seven anchored shapes above,
  whole, on every label it carries.

PRIVACY: every menu label, element id and account id is registered as a
private word as soon as the menu is read, before any press, and every
documentId as soon as an answer is read. None of them, nor a request body,
an answer, or an address with its query, is ever logged or said. A
statement's account is written down only as its class, "Business Checking",
"Business Card" or "Business Debit", read from the product noun in its
label. An entry with no such noun is passed over only when it reads as a
cardholder, "J. SURNAME (...1234)", beside a Business Card, and choosing it
shows no Statements. Any other stops the list (_menu_of, _pass_over).

SIGNED OUT: the session-timeout dialog drawn open, a sign-in address, a
password field, or a 401, 403 or redirect answering the list call, checked
before and after every wait and press, raises SessionExpired. The run saves,
says so and stops, and nothing is recorded for review.

KNOWN CEILINGS (ponytail: left until a live run shows otherwise)
  * The document center must open with its account menu and at least one
    document accordion drawn. Statements itself is asked of each account in
    turn (a debit account showed only ATM receipts live).
  * An empty year read before any non-empty one is held until a non-empty
    answer in the same run shows the success code, and a listing in which
    every year was empty stops.
  * The account id in bottom-<accountId> changes with each sign-in (seen
    live), so a record is known by its account's class and last four
    (account_digest), and two accounts of one class with one last four
    stop the list.
  * Two statements of one account on one date stop the list, on every run,
    since nothing on a row tells them apart.
  * Rows do not name their account, so a saved PDF is kept only when the
    account number after its "Account Number" label, or with no label the
    first account number its text prints, ends in the account's last four
    (names_tail). No real statement has been read by this rule yet, so a
    live run that leaves every statement for review should look here
    first.
  * Tax documents, notices, ATM receipts, check images and branch documents
    are never opened. The business card is listed like any account, and its
    rows are saved by their Saves document link. A card statement is kept
    only when its text also prints the row's date as its statement date,
    the closing date of its "Opening/Closing Date" or the date after a
    "Statement Date" label (names_date). No card statement had been saved
    by that path when it was written, so a live run that leaves the card's
    statement for review should look here first.
  * Only rows typed "Statement" are read, and any other type stops the list.
"""
from __future__ import annotations

import hashlib
import logging
import re
import sys
import time
from dataclasses import dataclass
from datetime import date as _date
from pathlib import Path
from typing import Callable, List, Optional, Tuple
from urllib.parse import parse_qs, urlsplit

from paperpull_core import pressing
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
from paperpull_core.receipt_pdf import pdf_text as _pdf_text

log = logging.getLogger("chasebusiness_docs.site")


def _words():
    """This app's own words for paperpull_core.words."""
    return _words_for("Chase Business", sys.modules[__name__])


# ---------------------------------------------------------------------------
# Addresses
# ---------------------------------------------------------------------------
BASE = "https://secure.chase.com"
PUBLIC = "https://www.chase.com"
DOCUMENTS_ROUTE = "#/dashboard/documents/myDocs/index"
DOCUMENTS_URL = f"{BASE}/web/auth/dashboard{DOCUMENTS_ROUTE}"
DOCREF_PATH = "/svc/rr/documents/secure/idal/v2/docref/list"
STATEMENTS_URL = DOCUMENTS_URL
BILLING_URL = DOCUMENTS_URL
URLS = {
    "home": f"{BASE}/",
    # The account holder signs in on www.chase.com, which lands on the
    # dashboard at secure.chase.com. www.chase.com is never a document host.
    "login": f"{PUBLIC}/",
    "documents": DOCUMENTS_URL,
    "statements": DOCUMENTS_URL,
}

LOGIN_URL_MARKERS = ["/logon", "/login", "/signin"]

# ---------------------------------------------------------------------------
# HARD SAFETY GUARD. The personal Chase app's list, and the business words
# the survey saw on this profile's menus.
# ---------------------------------------------------------------------------
FORBIDDEN_CONTROL_RE = re.compile(
    # money movement
    r"(transfer|deposit|withdraw|wire\b|wires\b|move\s+money|send\s+money|zelle|"
    r"\bpay\b|payment|pay\s+bills?|bill\s*pay|autopay|auto-?pay|schedule\s+payment|"
    r"pay\s+card|make\s+a\s+payment|pay\s+vendors?|payroll|invoice|"
    r"\bach\b|collections?\b|chase\s+collect|quick\s*accept|quick\s*deposit|"
    r"merchant\s+services|accept\s+card\s+payments|payment\s+center|positive\s+pay|"
    r"stop\s+payment|order\s+checks|deposit\s+checks|"
    # card and account products and offers
    r"balance\s+transfer|cash\s+advance|credit\s+line|credit\s+limit|"
    r"redeem|rewards?\b|points\b|miles\b|offers?\b|chase\s+offers|"
    r"employee\s+card|\bcatalog\b|"
    # applications, approvals and account changes
    r"apply|open\s+(a|an|another|new)\b[\w\s]{0,24}\baccount\b|"
    r"open\s+\w{0,12}\s*account\b|get\s+(a\s+)?(quote|started|loan|card)|"
    r"add\s+(funds|card|authorized|user|employee)|authorized\s+user|"
    r"pending\s+approvals?|\bapprov|"
    r"dispute|report\s+(a\s+)?(problem|fraud|lost|stolen)|"
    r"lock\s+card|unlock\s+card|freeze|activate|replace\s+card|close\s+account|"
    r"request\b|increase\b|"
    # administration and settings
    r"access\s*(&|and)\s*security|\busers?\b|sub-?users?|entitlements?|"
    r"link\s+relationship|linked\s+accounts|account\s+management|account\s+analysis|"
    r"show\s+or\s+hide|stay\s+signed\s+in|profile\s*(&|and)\s*settings|"
    r"\bchang(e|es|ed|ing)\b|\bedit(s|ed|ing)?\b|\bupdat(e|es|ed|ing)\b|"
    r"\bset\s+up\b|\benabl|\bdisabl|\bdelet|\bremov(e|es|ed|ing|al)\b|"
    r"^\s*save\s*$|\bsave\s+(changes?|settings?|preferences?|profile)\b|"
    r"appl(y|ies|ied|ication)|\boptions?\b|\bsettings?\b|"
    r"\bpreferences?\b|manage|turn\s+(on|off)|opt\s*(in|out)|"
    r"beneficiar|payee|contact\s+info|password|username|"
    r"paperless|delivery\s+preference|alerts?\s+settings|"
    # the variants of a document control this app never presses
    r"accessible|opens\s+document\s+menu|\bprint\b|"
    # anything that commits or leaves
    r"send\b|submit|confirm|continue|next|agree|accept|sign\b|sign\s*out|"
    r"log\s*(out|off)|authorize)", re.I)

# A verb an account menu entry must never carry. A menu entry is a product
# name, which can hold "REWARDS" or "POINTS", so it is judged on actions as
# the personal app judges a card header, plus this profile's business words.
ACCOUNT_ACTION_RE = re.compile(
    r"\bpay\b|\bpayment|transfer|redeem|activat|\block\b|unlock|replace|"
    r"dispute|\bclose\b|appl(y|ies|ied|ication)\b|request|increase|advance|"
    r"authorized\s+user|set\s+up|\bchang(e|es|ed|ing)\b|\bupdat(e|es|ed|ing)\b|"
    r"\bmanage\b|autopay|auto-?pay|zelle|\bwires?\b|deposit|withdraw|\bsend\b|"
    r"enroll|\bopen\b|\bcancel\b|\bsettings?\b|\bpreferences?\b|"
    r"\bach\b|collect|quick\s*accept|merchant|approv|\busers?\b|catalog|"
    r"employee|offers?\b|paperless|sign\s*out|stay\s+signed|continue|show\s+or\s+hide",
    re.I)

_MONTH = (r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)")
_ROW_DATE = rf"{_MONTH}\s+\d{{1,2}},\s+\d{{4}}"

# The seven controls this app presses, each anchored whole.
ACCOUNT_ENTRY_RE = re.compile(
    r"[A-Za-z0-9 .&'-]+ \(\.\.\.\d{4}\)(\s*,\s*current selection)?", re.I)
STATEMENTS_ACCORDION_RE = re.compile(r"statements", re.I)
# The picker's aria-label reads " View:: 2026" live, two colons and a space.
YEAR_PICKER_RE = re.compile(r"(view:{0,2}\s*)?(\d{4})?", re.I)
# The last year reads "2019 , you've reached the end of the menu" live: a
# space before the comma, and "menu" where the survey had seen "list".
YEAR_OPTION_RE = re.compile(r"(\d{4})(\s*,\s*you[’']ve reached the end of the (?:list|menu))?", re.I)
SAVE_MENU_RE = re.compile(rf"({_ROW_DATE}) opens menu to save document", re.I)
# Live, the option reads "Save as PDF 1 of 2 items": the menu adds the
# item's place to its name. That tail alone is allowed.
SAVE_AS_PDF_RE = re.compile(r"save as pdf(\s*\d{1,2} of \d{1,2} items?)?", re.I)
# A business card's row carries no save menu. Its own link reads "Oct 13,
# 2026 Saves document" live, beside "Oct 13, 2026 , opens document", which
# is never pressed.
SAVES_DOCUMENT_RE = re.compile(rf"({_ROW_DATE}) saves document", re.I)

# What the general guard takes, for the survey and the repo-wide tests: the
# seven shapes, and the rules' own summary under a document verb. Nothing on
# the document center reads like the last one.
SAFE_DOC_CONTROL_RES = (
    ACCOUNT_ENTRY_RE, STATEMENTS_ACCORDION_RE, YEAR_OPTION_RE, SAVE_MENU_RE,
    SAVE_AS_PDF_RE, SAVES_DOCUMENT_RE,
    re.compile(r"view:?(\s*\d{4})?", re.I),
    re.compile(r"((view|download)\s+)?(bank\s+)?statements?", re.I),
)

SECURITY_CHALLENGE_MARKERS = [
    "enter the code we sent", "enter your verification code", "verification code",
    "one-time", "one time passcode", "security code", "we sent a code",
    "two-factor", "two-step", "authenticator", "confirm your identity",
    "verify your identity", "we need to verify", "unusual activity",
    "are you a robot", "captcha", "unable to verify", "trouble verifying",
    "your session has expired", "please log in again", "you've been logged out",
    "for your security, we signed you out",
]

RATE_LIMIT_MARKERS = [
    "too many requests", "rate limit", "try again later",
    "temporarily unavailable", "http error 429", "unusual traffic",
]

# Selectors, also what --diagnose counts.
MENU_ENTRY = 'a[id^="bottom-"]'
ACCORDION = 'button[id^="button-accountsAccordian-"]'
STATEMENTS_ACCORDION_ID = "button-accountsAccordian-STATEMENTS"
YEAR_PICKER_ID = "header-filterstyledselect-0"
YEAR_OPTION = '[id^="container-"][id$="-filterstyledselect-0"]'
STATEMENT_ROW = 'tr[id^="accountsTable-STATEMENTS-row"]'
TIMEOUT_DIALOG = "mds-dialog#octagonSessionTimeoutDialogue"
# The dialog is in the page all the time, hidden, with no open attribute and
# a box of nothing. It is drawn open only when it carries open (not "false")
# and has a box on screen, its own or that of something in its shadow root,
# that is neither hidden nor transparent. Its words are never read: they are
# in the hidden DOM all the time.
_DIALOG_OPEN_JS = r"""() => Array.from(document.querySelectorAll('mds-dialog#octagonSessionTimeoutDialogue'))
  .some(d => {
    if (!d.hasAttribute('open') || /^false$/i.test(d.getAttribute('open') || '')) return false;
    const st = getComputedStyle(d);
    if (st.visibility === 'hidden' || st.display === 'none' || parseFloat(st.opacity) === 0) return false;
    const drawn = el => {
      const r = el.getBoundingClientRect(), s = getComputedStyle(el);
      return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'
             && parseFloat(s.opacity) > 0;
    };
    if (drawn(d)) return true;
    return !!d.shadowRoot && Array.from(d.shadowRoot.querySelectorAll('*')).some(drawn);
  })"""
FALLBACK = {
    "doc_row": STATEMENT_ROW,
    "doc_link": '[id$="-downloadPDFOption"]',
    "download_control": 'a[id^="header-"][id$="-cell3-downloadDocumentDropdown"]',
    # A business card row's own Saves document link, which it has in place
    # of the save menu.
    "card_download": 'a[id^="accountsTable-STATEMENTS-row"][id$="-cell3-requestThisDocumentAnchor-download"]',
    # Live, a wrapper div carries the same id without the header- prefix, and the
    # anchor is the control.
    "page_ready": f"{MENU_ENTRY}, #{STATEMENTS_ACCORDION_ID}",
    "account_select": MENU_ENTRY,
}

# How long each wait is given.
READY_WAIT_MS = 30000
ACCOUNT_WAIT_MS = 15000
LIST_WAIT_MS = 20000
ROWS_WAIT_MS = 10000
MENU_WAIT_MS = 5000
SETTLE_MS = 1500
DOWNLOAD_WAIT_MS = 60000
SECOND_DOWNLOAD_WAIT_MS = 2000
POLL_MS = 250
# A run stops taking documents this long after its first press. Chase signs
# an idle session out after a few minutes, with a one-minute warning.
DEADLINE_S = 6 * 60

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


_ROW_DATE_RE = re.compile(r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2}),\s+(\d{4})")


def row_date(text) -> Optional[str]:
    """A statement row's date cell, "Sep 30, 2026", as YYYY-MM-DD, or None.
    The whole cell must be the date and the day must exist."""
    m = _ROW_DATE_RE.fullmatch(re.sub(r"\s+", " ", str(text or "")).strip())
    if not m:
        return None
    try:
        return _date(int(m.group(3)), _MONTHS[m.group(1).lower()], int(m.group(2))).isoformat()
    except ValueError:
        return None


def answer_date(value) -> Optional[str]:
    """An answer's documentDate, YYYYMMDD or YYYY-MM-DD, as YYYY-MM-DD, or
    None. Nothing else is read as a date."""
    text = str(value or "").strip() if isinstance(value, (str, int)) else ""
    m = re.fullmatch(r"(\d{4})-?(\d{2})-?(\d{2})", text)
    if not m:
        return None
    try:
        return _date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
    except ValueError:
        return None


def _row_label_date(iso: str) -> str:
    """How a row's save menu writes a date, "Sep 30, 2026"."""
    d = _date.fromisoformat(iso)
    return "%s %02d, %d" % (("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep",
                             "Oct", "Nov", "Dec")[d.month - 1], d.day, d.year)


# ---------------------------------------------------------------------------
# Session / safety
# ---------------------------------------------------------------------------

class SessionExpired(Exception):
    """Chase answered as a signed-out session: its timeout dialog drawn
    open, its sign-in page, a password field, or a 401, 403 or redirect
    answering the list call. The run stops for the account holder."""


class ListStopped(Exception):
    """The list has a part this could not read, so what was read is not all
    of it. `docs` holds what was read before it stopped. Its words are this
    module's own, never the page's."""

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


def _timeout_dialog_open(page) -> bool:
    """Chase's "Your session is about to end" dialog, drawn open. It is in
    the page all the time and shows when its open attribute is set. Its
    buttons are never pressed."""
    try:
        return page.evaluate(_DIALOG_OPEN_JS) is True
    except Exception:
        return False


def check_signed_in(page) -> None:
    """Raise SessionExpired when the page shows Chase signing the session
    out. Asked before and after every wait and every press."""
    if _timeout_dialog_open(page):
        raise SessionExpired("Chase is showing its session timeout dialog")
    if looks_signed_out(page):
        raise SessionExpired("Chase showed its sign-in page")


def detect_security_challenge(page) -> Optional[str]:
    """Names the passcode, CAPTCHA or throttling prompt on screen, or None.
    A page that shows a statement row is not a challenge."""
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
    blocklist, then the shared core guards, and only then the anchored
    shapes, whole."""
    name = _tidy(name)
    if not name or _refused(name):
        return False
    return any(rx.fullmatch(name) for rx in SAFE_DOC_CONTROL_RES)


# -- the seven predicates, one for each control this app presses -------------

def is_account_entry(label: str) -> bool:
    """An account menu entry, "BUS COMPLETE CHK (...1234)", with or without
    ", current selection". Judged on action verbs, not product words."""
    label = _tidy(label)
    if not label or ACCOUNT_ACTION_RE.search(label) or SETTINGS_CONTROL_RE.search(label) \
            or AUTH_CONTROL_RE.search(label):
        return False
    return bool(ACCOUNT_ENTRY_RE.fullmatch(label))


def is_statements_accordion(label: str) -> bool:
    """The Statements accordion's header."""
    label = _tidy(label)
    return bool(label) and not _refused(label) and bool(STATEMENTS_ACCORDION_RE.fullmatch(label))


def is_year_picker(label: str) -> bool:
    """The "View:" year picker, by its label or the year it shows."""
    label = _tidy(label)
    return bool(label) and not _refused(label) and bool(YEAR_PICKER_RE.fullmatch(label))


def is_year_option(label: str) -> bool:
    """One year in the picker's list. The year already selected reads ",
    current selection" (a space may come before the comma) and is never
    pressed, so it is refused here."""
    label = _tidy(label)
    return bool(label) and not _refused(label) and bool(YEAR_OPTION_RE.fullmatch(label))


def is_save_menu(label: str, row_date_label: str = "") -> bool:
    """The bound row's "<date> Opens menu to save document", for that date
    only when one is given."""
    label = _tidy(label)
    if not label or _refused(label):
        return False
    m = SAVE_MENU_RE.fullmatch(label)
    if not m:
        return False
    return not row_date_label or row_date(m.group(1)) == row_date(row_date_label)


def is_save_as_pdf(label: str) -> bool:
    """"Save as PDF", with or without the menu's "1 of 2 items" place hint,
    and nothing else. The accessible variant is refused."""
    label = _tidy(label)
    return bool(label) and not _refused(label) and bool(SAVE_AS_PDF_RE.fullmatch(label))


def is_saves_document(label: str, row_date_label: str = "") -> bool:
    """A business card row's own "<date> Saves document" link, for that
    date only when one is given. The row's "<date> , opens document" beside
    it is refused, and so is any other words."""
    label = _tidy(label)
    if not label or _refused(label):
        return False
    m = SAVES_DOCUMENT_RE.fullmatch(label)
    if not m:
        return False
    return not row_date_label or row_date(m.group(1)) == row_date(row_date_label)


PRESS_GUARDS = (is_account_entry, is_statements_accordion, is_year_picker,
                is_year_option, is_save_menu, is_save_as_pdf, is_saves_document)


# ---------------------------------------------------------------------------
# Hosts. Exact, parsed, no subdomain wildcard.
# ---------------------------------------------------------------------------
ALLOWED_HOSTS = {"secure.chase.com"}
_PDF_PATH_RE = re.compile(r"/svc/rr/documents/secure/idal/v[0-9]+/pdfdoc/star/list")


def is_safe_url(url: str) -> bool:
    """True only for an https URL on exactly secure.chase.com."""
    return _host_allows(url, ALLOWED_HOSTS, subdomains=False)


def is_documents_url(url: str) -> bool:
    """The document center itself: secure.chase.com's dashboard with the
    documents route, as the address or with an account chosen in it."""
    if not is_safe_url(url):
        return False
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    return parts.path == "/web/auth/dashboard" and \
        (parts.fragment or "").startswith(DOCUMENTS_ROUTE[1:])


def is_docref_url(url: str) -> bool:
    """The statements list call, exactly: secure.chase.com and its path."""
    if not is_safe_url(url):
        return False
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    return parts.path == DOCREF_PATH and not parts.fragment


def is_download_url(url: str) -> bool:
    """Where a statement's PDF comes from: secure.chase.com's PDF path."""
    if not is_safe_url(url):
        return False
    try:
        return bool(_PDF_PATH_RE.fullmatch(urlsplit(url).path))
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------

class Run:
    """What one run carries between presses: when its first press was made,
    for the deadline, the code the first non-empty list answered with,
    which is what an empty year is checked against, and the codes of the
    empty years read before any list showed that code. The App owns one."""

    def __init__(self, clock: Callable[[], float] = time.monotonic,
                 limit_s: float = DEADLINE_S, today: Callable[[], _date] = _date.today):
        self.clock = clock
        self.limit_s = limit_s
        self.today = today
        self.first_press: Optional[float] = None
        self.success_code = None
        # The codes of empty years answered before any non-empty list did.
        # Each is checked against the success code once one is known, and a
        # listing that ends with some held and no code known stops.
        self.held: list = []
        # Every download any watched tab raises for the whole run, and how
        # many of them a Save as PDF took. One more than were taken is a
        # download no press of this run is known to have made, and nothing
        # more is pressed while one is there.
        self.downloads: list = []
        self.taken = 0
        self._watched: list = []
        # Every new tab a watched tab opens from a card's first Saves
        # document on. One is never what a press should bring, so nothing
        # more is pressed once one has come.
        self.popups: list = []
        self._popup_watched: list = []

    def watch(self, page) -> None:
        """Listen for downloads on this tab for the rest of the run."""
        if any(p is page for p in self._watched):
            return
        page.on("download", self._on_download)
        self._watched.append(page)

    def _on_download(self, dl) -> None:
        self.downloads.append(dl)

    def watch_popups(self, page) -> None:
        """Listen for new tabs this tab opens for the rest of the run."""
        if any(p is page for p in self._popup_watched):
            return
        page.on("popup", self._on_popup)
        self._popup_watched.append(page)

    def _on_popup(self, tab) -> None:
        self.popups.append(tab)

    def untied(self) -> int:
        """Downloads that came and that no Save as PDF of this run took."""
        return len(self.downloads) - self.taken

    def pressed(self) -> None:
        if self.first_press is None:
            self.first_press = self.clock()

    def unproven(self) -> bool:
        """Whether an empty year was read and no list of this run has shown
        what success looks like, so that year cannot yet be read as empty."""
        return bool(self.held) and self.success_code is None

    def past_deadline(self) -> bool:
        return self.first_press is not None and self.clock() - self.first_press >= self.limit_s


@dataclass
class RawDoc:
    title: str
    account: str = ""
    date_text: str = ""
    href: str = ""
    text: str = ""
    row_index: int = -1
    kind: str = "doc"
    # documentId from the list answer. Private: never logged or in a name.
    document_id: str = ""
    # The menu entry's element id, bottom-<accountId>. Private. Chase mints
    # it anew each sign-in, so it names the account for this session only
    # and is never what a record is known by.
    account_ref: str = ""
    doc_type: str = ""
    page_count: int = 0
    # The account's class and last four, digested (account_digest). What a
    # record is known by and what finds its account again on a later
    # sign-in.
    account_digest: str = ""


@dataclass(frozen=True)
class Item:
    """One statement as the list answer gives it."""
    document_id: str
    date: str
    doc_type: str
    pages: int

    @property
    def shape(self) -> tuple:
        return (self.date, self.doc_type, self.pages)


@dataclass(frozen=True)
class Account:
    ref: str          # bottom-<accountId>
    account_id: str
    klass: str
    # The last four digits the menu label shows, "(...1234)". Private. With
    # the class it is what names the account across sign-ins (digest), and
    # what a saved statement's text is checked for.
    tail: str = ""

    @property
    def digest(self) -> str:
        return account_digest(self.klass, self.tail)


def account_digest(klass: str, tail: str) -> str:
    """Twelve hex letters of an unsalted SHA-256 of an account's class and
    last four, "Business Checking:1234", or "" without both. Chase mints an
    account's id anew each sign-in, so the class and last four are what
    name the account from one sign-in to the next, as the chase app keys
    its cards. The digest keeps the four digits out of a file name, but it
    is no secret, since there are only ten thousand last fours to try."""
    if not klass or not re.fullmatch(r"\d{4}", tail or ""):
        return ""
    return hashlib.sha256(("%s:%s" % (klass, tail)).encode("utf-8")).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Reading the page. Read only; nothing on the page is changed.
# ---------------------------------------------------------------------------
_STATE_JS = r"""() => {
  const tidy = s => (s || '').replace(/\s+/g, ' ').trim();
  const shown = el => !!el && !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length)
                      && getComputedStyle(el).visibility !== 'hidden';
  const labels = el => [tidy(el.innerText), tidy(el.getAttribute('aria-label')),
                        tidy(el.getAttribute('title'))].filter(Boolean);
  const out = {menu: [], accordions: [], picker: null, options: [], rows: [],
               dialog: (__DIALOG__)(),
               password: !!document.querySelector("input[type='password']")};
  for (const a of document.querySelectorAll('a[id^="bottom-"]'))
    out.menu.push({id: a.id, labels: labels(a), all: tidy(a.textContent), shown: shown(a)});
  for (const b of document.querySelectorAll('button[id^="button-accountsAccordian-"]'))
    out.accordions.push({id: b.id, expanded: b.getAttribute('aria-expanded') || '',
                         labels: labels(b), shown: shown(b)});
  const p = document.getElementById('header-filterstyledselect-0');
  if (p) out.picker = {labels: labels(p), value: tidy(p.value || p.getAttribute('value')), shown: shown(p)};
  for (const o of document.querySelectorAll('[id^="container-"][id$="-filterstyledselect-0"]'))
    out.options.push({id: o.id, labels: labels(o), shown: shown(o)});
  for (const tr of document.querySelectorAll('tr[id^="accountsTable-STATEMENTS-row"]')) {
    if (!/^accountsTable-STATEMENTS-row[0-9]+$/.test(tr.id)) continue;
    out.rows.push({id: tr.id, shown: shown(tr),
                   cells: Array.from(tr.querySelectorAll('th, td')).map(c => tidy(c.innerText))});
  }
  return out;
}"""

# One reading of the timeout dialog for both places that ask.
_STATE_JS = _STATE_JS.replace("__DIALOG__", _DIALOG_OPEN_JS)

_LABELS_JS = r"""el => [el.innerText, el.getAttribute('aria-label'), el.getAttribute('title')]
  .map(s => (s || '').replace(/\s+/g, ' ').trim()).filter(Boolean)"""


def _read(page) -> dict:
    """What the document center shows now. A page that cannot be read
    stops the list."""
    try:
        state = page.evaluate(_STATE_JS)
    except Exception as e:
        raise ListStopped("the document center could not be read (%s)" % type(e).__name__)
    if not isinstance(state, dict):
        raise ListStopped("the document center could not be read")
    if state.get("dialog"):
        raise SessionExpired("Chase is showing its session timeout dialog")
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


_ACCOUNT_REF_RE = re.compile(r"bottom-([A-Za-z0-9_-]{1,80})")
_CLASSES = ((re.compile(r"\b(CHK|CHECKING)\b", re.I), "Business Checking"),
            (re.compile(r"\bCARD\b", re.I), "Business Card"),
            (re.compile(r"\bDEBIT\b", re.I), "Business Debit"))
_TAIL_RE = re.compile(r"\s*\(\.\.\.\d{4}\)(\s*,\s*current selection)?\s*$", re.I)
_FOUR_RE = re.compile(r"\(\.\.\.(\d{4})\)")
# A cardholder's menu entry, as the live menu draws it: one initial with a
# period, then a surname of one or more words of capital letters, an
# apostrophe or hyphen only inside a word, then the masked last four.
_SURNAME_WORD = r"[A-Z]+(?:['-][A-Z]+)*"
CARDHOLDER_RE = re.compile(r"[A-Z]\. %s(?: %s)* \(\.\.\.\d{4}\)(\s*,\s*current selection)?"
                           % (_SURNAME_WORD, _SURNAME_WORD))


def label_tail(label: str) -> str:
    """The last four digits a menu label shows as "(...1234)", or "" for a
    label with none or more than one."""
    found = _FOUR_RE.findall(_tidy(label))
    return found[0] if len(found) == 1 else ""


def account_class(label: str) -> str:
    """The class of account a menu label names, from its product noun
    alone: "Business Checking" (CHK, CHECKING), "Business Card" (CARD) or
    "Business Debit" (DEBIT). "" for a label with none of them, or more than
    one, which is a cardholder's name or a label this cannot read."""
    name = _TAIL_RE.sub("", _tidy(label))
    found = {klass for rx, klass in _CLASSES if rx.search(name)}
    return found.pop() if len(found) == 1 else ""


def _is_current(entry: dict) -> bool:
    return any(re.search(r",\s*current selection\s*$", t or "", re.I)
               for t in list(entry.get("labels") or []) + [entry.get("all") or ""])


def guard_menu(state: dict) -> None:
    """Register every menu label, element id and account id as private
    words, in every part, before anything is pressed, logged or raised."""
    new = []
    for e in state.get("menu") or []:
        ident = str(e.get("id") or "")
        new.append(ident)
        m = _ACCOUNT_REF_RE.fullmatch(ident)
        if m:
            new.append(m.group(1))
        for text in list(e.get("labels") or []) + [e.get("all") or ""]:
            text = str(text or "")
            new.append(text)
            new.extend(re.findall(r"\d{4,}", text))
    have = set(private_words())
    add = [w for w in new if w and w not in have]
    if add:
        set_private_words(private_words() + add)


def _guard_ids(ids) -> None:
    have = set(private_words())
    add = [i for i in ids if i not in have]
    if add:
        set_private_words(private_words() + add)


def accounts_of(state: dict) -> List[Account]:
    """The menu entries this app lists, in menu order, each with a
    well-formed element id, one last four, and a class every label it
    carries agrees on (_menu_of)."""
    return _menu_of(state)[0]


def _menu_of(state: dict) -> Tuple[List[Account], List[Account]]:
    """The accounts this app lists and the cardholders' entries, each with
    a well-formed element id and one last four.

    An entry with no class may be a cardholder's only when its label reads
    as a person, one initial with a period and then a surname,
    "J. SURNAME (...1234)" (CARDHOLDER_RE), and the menu also lists a
    Business Card. Live, the cardholder shows a last four of its own, not
    the card's, and only notices. Such an entry is passed over only once
    choosing it shows no Statements (_pass_over), since a second card or
    an account nicknamed like a person reads the same way. Any other entry
    without a class stops the list, since it may be an account whose name
    carries no product word (a card named "INK BUSINESS CASH", say) and
    skipping it would call the list whole without it. One element id twice
    stops the list too, and so do two accounts of one class with one last
    four, which nothing would tell apart."""
    seen, read = set(), []
    for e in state.get("menu") or []:
        ref = str(e.get("id") or "")
        m = _ACCOUNT_REF_RE.fullmatch(ref)
        if not m:
            raise ListStopped("an account menu entry has an id this cannot read")
        if ref in seen:
            raise ListStopped("two account menu entries carry one id")
        seen.add(ref)
        if not e.get("shown"):
            raise ListStopped("an account menu entry is drawn but not shown")
        labels = list(e.get("labels") or [])
        if not labels:
            raise ListStopped("an account menu entry has no label")
        klass = account_class(labels[0])
        # An entry that is listed is pressed, so its every label must be one
        # the press would take. A cardholder's is pressed too, to show it
        # has no Statements, and is held to the same below once its shape
        # is known, since an entry with neither stops the list anyway.
        if klass and not all(is_account_entry(t) for t in labels):
            raise ListStopped("an account menu entry reads in a way this cannot read")
        if any(account_class(t) != klass for t in labels):
            raise ListStopped("an account menu entry's labels name different accounts")
        tails = {label_tail(t) for t in labels}
        if len(tails) != 1 or "" in tails:
            raise ListStopped("an account menu entry shows no single last four")
        read.append((ref, m.group(1), klass, tails.pop(), labels))
    has_card = any(klass == "Business Card" for _r, _i, klass, _t, _l in read)
    out, holders = [], []
    for ref, account_id, klass, tail, labels in read:
        if klass:
            out.append(Account(ref=ref, account_id=account_id, klass=klass, tail=tail))
        elif has_card and all(CARDHOLDER_RE.fullmatch(_tidy(t)) for t in labels):
            if not all(is_account_entry(t) for t in labels):
                raise ListStopped("a cardholder's menu entry reads in a way the press would not take")
            holders.append(Account(ref=ref, account_id=account_id, klass="", tail=tail))
        else:
            raise ListStopped("an account menu entry names no class of business account this reads")
    if len({a.digest for a in out}) != len(out):
        raise ListStopped("two accounts of one class show one last four")
    return out, holders


def _menu_reading(state: dict) -> list:
    """The account menu as one reading saw it: each entry's id, labels,
    whole text and whether it shows, in order."""
    return [(str(e.get("id") or ""), tuple(_tidy(t) for t in e.get("labels") or []),
             _tidy(e.get("all")), bool(e.get("shown"))) for e in state.get("menu") or []]


# ---------------------------------------------------------------------------
# The page's own list answers
# ---------------------------------------------------------------------------

def _form(request) -> Optional[dict]:
    try:
        body = request.post_data or ""
    except Exception:
        return None
    try:
        return parse_qs(body, keep_blank_values=True, strict_parsing=bool(body))
    except ValueError:
        return None


def is_docref_post(response) -> bool:
    """A POST to exactly the statements list call."""
    try:
        return response.request.method == "POST" and is_docref_url(response.url)
    except Exception:
        return False


def answers(response, account_id: str, filter_type: str) -> bool:
    """Whether this response is the statements list for this account and
    this year: a POST to exactly the list call whose form body names the
    account and the year's filter, each once."""
    if not is_docref_post(response):
        return False
    form = _form(response.request)
    return bool(form) and form.get("accountFilter") == [account_id] \
        and form.get("dateFilter.idalDateFilterType") == [filter_type]


def filter_for(current_year: int, year: int) -> str:
    """The filter the page sends for `year` while `current_year` is the
    picker's current year."""
    n = current_year - year
    if n < 0:
        raise ListStopped("a year after the current one was asked for")
    return "CURRENT_YEAR" if n == 0 else "CURRENT_YEAR_MINUS_%d" % n


def _signed_out_answer(response) -> bool:
    try:
        status = int(response.status)
    except Exception:
        return False
    return status in (401, 403) or 300 <= status < 400


class _Heard:
    """The page's own statements-list answers while armed: those for one
    account and one year, and whether any list answer said signed out."""

    def __init__(self, page, account_id: Optional[str] = None, filter_type: Optional[str] = None):
        self.page = page
        self.account_id, self.filter_type = account_id, filter_type
        self.all: list = []
        self.signed_out = False

    def _on(self, response):
        try:
            if not is_docref_post(response):
                return
            if _signed_out_answer(response):
                self.signed_out = True
                return
            self.all.append(response)
        except Exception:
            pass

    def matching(self, account_id: str, filter_type: str) -> list:
        return [r for r in self.all if answers(r, account_id, filter_type)]

    def raise_if_signed_out(self) -> None:
        if self.signed_out:
            raise SessionExpired("the statements list answered as signed out")

    def __enter__(self):
        self.page.on("response", self._on)
        return self

    def __exit__(self, *exc):
        try:
            self.page.remove_listener("response", self._on)
        except Exception:
            pass
        return False


def _await_answers(page, account_id: str, filter_type: str, press: Callable[[], None],
                   timeout_ms: int) -> list:
    """Make `press` while the page's answer for this account and year is
    awaited, then let the page settle and say every such answer that came.
    None coming in `timeout_ms` is not an error here, and the caller decides."""
    with _Heard(page) as heard:
        try:
            with page.expect_response(lambda r: answers(r, account_id, filter_type),
                                      timeout=timeout_ms):
                press()
        except (SessionExpired, ListStopped):
            raise
        except Exception as e:
            log.info("no list answer came within the wait (%s)", type(e).__name__)
        check_signed_in(page)
        heard.raise_if_signed_out()
        page.wait_for_timeout(SETTLE_MS)
        check_signed_in(page)
        heard.raise_if_signed_out()
        return heard.matching(account_id, filter_type)


_DOCUMENT_ID_RE = re.compile(r"[A-Za-z0-9_.:+/=-]{4,200}")


def read_answer(response, run: Run, year: int) -> List[Item]:
    """The statements of one list answer, every one dated in `year`.

    An answer must be 200 JSON with a code. idaldocRefs present must be a
    non-empty list of well-formed statements, and the first such answer in
    the run sets the success code. idaldocRefs absent is an empty year when
    it carries that code. Before any code is known an empty year is held
    (Run.held), since in January every account's current year is empty and
    is the first list read. The first non-empty answer then checks every
    held code, and a listing that ends with none known stops
    (collect_download_docs). An empty year with another code stops the
    list. Nothing of the answer is logged."""
    try:
        status = int(response.status)
    except Exception:
        raise ListStopped("the list answer could not be read")
    if _signed_out_answer(response):
        raise SessionExpired("the statements list answered as signed out")
    if status != 200:
        raise ListStopped("the list answered with status %d" % status)
    try:
        data = response.json()
    except Exception:
        raise ListStopped("the list answer is not JSON")
    if not isinstance(data, dict):
        raise ListStopped("the list answer is not the shape this reads")
    code = data.get("code")
    if code is None or isinstance(code, (bool, dict, list)) or str(code).strip() == "":
        raise ListStopped("the list answer carries no code")
    if "idaldocRefs" not in data:
        if run.success_code is None:
            run.held.append(code)
            return []
        if code != run.success_code:
            raise ListStopped("an empty year came with another code than the lists before it")
        return []
    refs = data.get("idaldocRefs")
    if not isinstance(refs, list) or not refs:
        raise ListStopped("the list answer's statements are not the shape this reads")
    ids = []
    for ref in refs:
        if not isinstance(ref, dict):
            raise ListStopped("a statement in the list answer is not the shape this reads")
        doc_id = ref.get("documentId")
        if not isinstance(doc_id, str) or not _DOCUMENT_ID_RE.fullmatch(doc_id):
            raise ListStopped("a statement's id is not one this can read")
        ids.append(doc_id)
    # Private before anything below can say anything.
    _guard_ids(ids)
    out = []
    for ref in refs:
        iso = answer_date(ref.get("documentDate"))
        if not iso:
            raise ListStopped("a statement's date is not a calendar date")
        if int(iso[:4]) != year:
            raise ListStopped("a statement is dated outside the year asked for")
        kind = _tidy(ref.get("documentTypeDesc")) if isinstance(ref.get("documentTypeDesc"), str) else ""
        if kind.lower() != "statement":
            raise ListStopped("a document of a type other than Statement is in the list")
        pages = ref.get("pageCount")
        if isinstance(pages, str) and pages.strip().isdigit():
            pages = int(pages.strip())
        if isinstance(pages, bool) or not isinstance(pages, int) or pages <= 0:
            raise ListStopped("a statement's page count is not one this can read")
        out.append(Item(document_id=ref["documentId"], date=iso, doc_type="Statement", pages=pages))
    if len({i.document_id for i in out}) != len(out):
        raise ListStopped("two statements in one answer carry one id")
    if run.success_code is None:
        if any(h != code for h in run.held):
            raise ListStopped("an empty year came with another code than the first list")
        run.success_code = code
    elif code != run.success_code:
        raise ListStopped("a list came with another code than the lists before it")
    return out


# ---------------------------------------------------------------------------
# The rows the page draws, checked against the answer
# ---------------------------------------------------------------------------

def row_shape(cells) -> Optional[tuple]:
    """(date, type, pages) of a row's Date, Type and Size cells, or None
    when any of them cannot be read."""
    cells = list(cells or [])
    if len(cells) < 3:
        return None
    iso = row_date(cells[0])
    kind = _tidy(cells[1])
    m = re.fullmatch(r"(\d+) pages?", _tidy(cells[2]), re.I)
    if not iso or not kind or not m or int(m.group(1)) <= 0:
        return None
    return (iso, "Statement" if kind.lower() == "statement" else kind, int(m.group(1)))


def _row_number(row_id: str) -> int:
    m = re.fullmatch(r"accountsTable-STATEMENTS-row([0-9]+)", row_id or "")
    return int(m.group(1)) if m else -1


def rows_match(items: List[Item], rows: list) -> bool:
    """Whether the rows drawn are exactly the statements answered, as
    multisets of (date, type, pages). An unreadable row never matches."""
    from collections import Counter
    shapes = []
    for r in rows:
        shape = row_shape(r.get("cells"))
        if shape is None:
            return False
        shapes.append(shape)
    return Counter(shapes) == Counter(i.shape for i in items)


def _cross_check(page, items: List[Item]) -> dict:
    """Wait for the rows to be the answer's statements, or stop the list."""
    state = _wait_for(page, lambda s: rows_match(items, s.get("rows") or []), ROWS_WAIT_MS)
    if state is None:
        raise ListStopped("the rows on the page are not the statements the page was sent")
    return state


# ---------------------------------------------------------------------------
# Pressing. Every press goes through _press or _press_row, with one of the
# seven predicates.
# ---------------------------------------------------------------------------

def _labels_of(locator) -> List[str]:
    try:
        labels = locator.evaluate(_LABELS_JS)
    except Exception:
        return []
    return [str(x) for x in labels or [] if str(x or "").strip()]


def _guarded(page, locator, *, what: str, guard, expect: Optional[str]) -> None:
    """Prove a control may be pressed: exactly one shown element, every
    label it carries passing `guard`, one of PRESS_GUARDS. Anything else
    stops the list with nothing pressed."""
    if guard not in PRESS_GUARDS:
        raise ListStopped("a press was asked for with no guard of this app's own")
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


def _press(page, locator, *, css: str, what: str, guard, step: str, run: Run,
           expect: Optional[str] = None) -> None:
    """Press one of the four controls that reach a list, an account in the
    menu, the Statements accordion, the year picker or a year in it, once,
    through the core, once _guarded has passed it. Every statement after
    such a control is reached through it, so one the site has turned off
    stops the run (pressing.TurnedOff) rather than leave each statement."""
    _guarded(page, locator, what=what, guard=guard, expect=expect)
    run.pressed()
    pressing.click(page, locator, css=css, what=what, words=_words(), step=step)
    check_signed_in(page)


def _press_row(page, locator, *, css: str, what: str, guard, step: str, run: Run,
               expect: Optional[str] = None) -> bool:
    """Press one statement's own control, its save menu or the Save as PDF
    in it, once, through the core, once _guarded has passed it. True when
    pressed. False when the site has turned that control off, which the
    core says only once nothing was pressed and nothing came
    (pressing.TurnedOff). Its statement is then left for review and the
    next run, and the run goes on to the next statement."""
    _guarded(page, locator, what=what, guard=guard, expect=expect)
    run.pressed()
    try:
        pressing.click(page, locator, css=css, what=what, words=_words(), step=step)
    except pressing.TurnedOff:
        log.info("%s is turned off, so its statement is left for review", what)
        return False
    check_signed_in(page)
    return True


# ---------------------------------------------------------------------------
# The document center
# ---------------------------------------------------------------------------

class Opened:
    """The document center as it opened, and the list answers its own load
    made, which hold the current year of the account it opened on."""

    def __init__(self, state: dict, heard: list):
        self.state = state
        self.heard = heard


def _statements(state: dict):
    """The Statements accordion: None when the page draws none, the one
    node when exactly one shows, and "" for a hidden or a doubled node,
    which this cannot read."""
    nodes = [a for a in state.get("accordions") or [] if a.get("id") == STATEMENTS_ACCORDION_ID]
    if not nodes:
        return None
    if len(nodes) != 1 or not nodes[0].get("shown"):
        return ""
    return nodes[0]


def _ready(state: dict) -> bool:
    """The document center drawn: its account menu and at least one document
    accordion. Statements itself is asked of each account in turn, since an
    account the page opens on may be one that has none (a debit card shows
    only ATM receipts)."""
    return any(e.get("shown") for e in state.get("menu") or []) and \
        any(a.get("shown") for a in state.get("accordions") or [])


def _open(page) -> Opened:
    """Open the document center by its address and wait for it to be ready:
    the account menu and the Statements accordion drawn, on its own route.
    Every menu label and id is private from here on. The menu is read again
    once the page has settled, and the two readings must agree, so a menu
    still being drawn is never taken for the whole of it. Raises
    SessionExpired for a signed-out page and ListStopped for one that did
    not open or whose menu changed between readings. The list answers the
    load itself makes are kept. Nothing is pressed."""
    with _Heard(page) as heard:
        try:
            page.goto(DOCUMENTS_URL, wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            log.info("opening the document center failed (%s)", type(e).__name__)
            check_signed_in(page)
            heard.raise_if_signed_out()
            raise ListStopped("the document center did not open")
        check_signed_in(page)
        if not is_documents_url(page.url or ""):
            raise ListStopped("the document center settled off its own address")
        state = _wait_for(page, _ready, READY_WAIT_MS)
        heard.raise_if_signed_out()
        if state is None:
            seen = _read(page)
            guard_menu(seen)
            raise ListStopped("the document center did not show its account menu and Statements")
        guard_menu(state)
        if not is_documents_url(page.url or ""):
            raise ListStopped("the document center settled off its own address")
        page.wait_for_timeout(SETTLE_MS)
        check_signed_in(page)
        heard.raise_if_signed_out()
        again = _read(page)
        guard_menu(again)
        if _menu_reading(again) != _menu_reading(state):
            raise ListStopped("the account menu read differently twice over")
        return Opened(state, list(heard.all))


def _entry(state: dict, ref: str) -> Optional[dict]:
    """The one shown menu entry with this id, or None for none, a hidden
    one, or the id on two nodes."""
    hits = [e for e in state.get("menu") or [] if e.get("id") == ref]
    return hits[0] if len(hits) == 1 and hits[0].get("shown") else None


def _picker_year(state: dict) -> Optional[int]:
    p = state.get("picker") or {}
    for text in [p.get("value") or ""] + list(p.get("labels") or []):
        m = YEAR_PICKER_RE.fullmatch(_tidy(text))
        if m and m.group(2):
            return int(m.group(2))
    return None


def _arrive(page, run: Run, opened: Opened, acct: Account):
    """Make `acct` the current account and read its current year's list.

    Returns (items, current_year), or None for an account that shows no
    Statements accordion once it is proven current. The account's entry is
    pressed only when it is not the current selection already, and the load's
    own answers hold its list then. The accordion is pressed only while
    closed. Exactly one answer for this account's current year, from these
    transitions together, or the list stops."""
    entry = _entry(opened.state, acct.ref)
    if entry is None:
        raise ListStopped("the account is not in the menu once")
    cur_filter = "CURRENT_YEAR"
    matches: list = []
    if _is_current(entry):
        matches = [r for r in opened.heard if answers(r, acct.account_id, cur_filter)]
    else:
        css = "#" + acct.ref
        matches = _await_answers(
            page, acct.account_id, cur_filter,
            lambda: _press(page, page.locator(css), css=css, what="an account in the menu",
                           guard=is_account_entry, step="choose an account", run=run),
            ACCOUNT_WAIT_MS)
    state = _wait_for(page, lambda s: _entry(s, acct.ref) is not None
                      and _is_current(_entry(s, acct.ref))
                      and bool(s.get("accordions")), LIST_WAIT_MS)
    if state is None:
        raise ListStopped("the account chosen does not show as the current selection")
    stmt = _statements(state)
    if stmt == "":
        raise ListStopped("the Statements accordion is hidden or drawn twice")
    if stmt is None:
        if matches:
            raise ListStopped("a statements list came for an account with no Statements")
        return None
    if (stmt.get("expanded") or "").lower() != "true":
        css = "#" + STATEMENTS_ACCORDION_ID
        matches = matches + _await_answers(
            page, acct.account_id, cur_filter,
            lambda: _press(page, page.locator(css), css=css, what="the Statements accordion",
                           guard=is_statements_accordion, step="open the statements", run=run),
            LIST_WAIT_MS)
    if not matches and _is_current(entry) and (stmt.get("expanded") or "").lower() == "true":
        # The page opened on this account with its statements already drawn,
        # so nothing this run pressed fetched the current year's list and the
        # load's own answer came before this run was listening. Choosing
        # another year and then the current one again, two presses the
        # picker allows, brings the current year's answer in this run's
        # hearing. Re-choosing the current year straight off fetches nothing.
        state = _read(page)
        shown = _picker_year(state)
        if shown is None:
            raise ListStopped("the year picker shows no year")
        year_now = run.today().year
        if shown != year_now:
            # A run before this one left the picker on another year. Choosing
            # this year brings its answer, which is what is wanted here.
            options = _open_picker(page, run)
            items = _choose_year(page, run, acct, year_now, year_now, options)
            return items, year_now
        options = _open_picker(page, run)
        others = sorted((y for y, _css, _cur in options if y != year_now), reverse=True)
        if not others:
            raise ListStopped("the picker offers no other year to come back from")
        _choose_year(page, run, acct, year_now, others[0], options)
        options = _open_picker(page, run)
        items = _choose_year(page, run, acct, year_now, year_now, options)
        return items, year_now
    if len(matches) != 1:
        raise ListStopped("%d list answers came for the account's current year" % len(matches))
    state = _read(page)
    year = _picker_year(state)
    if year is None:
        raise ListStopped("the year picker shows no year")
    if year != run.today().year:
        raise ListStopped("the year picker's current year is not this year")
    items = read_answer(matches[0], run, year)
    _cross_check(page, items)
    return items, year


_END_WORDS_RE = re.compile(r"you[’']ve reached the end of the (?:list|menu)", re.I)


def _options(state: dict) -> List[Tuple[int, str, bool]]:
    """(year, css, current) for each shown year option. An option that
    cannot be read stops the list, and so does a list whose oldest year
    does not carry the picker's end of the menu words, or whose words are
    on another year, since the list may then be cut short."""
    out, ends = [], []
    for o in state.get("options") or []:
        # Live, each year is drawn as container-<n>-... with inner
        # container-primary-<n>-... and container-secondary-<n>-... parts, the
        # last with no words. Only the year's own node is read.
        if not re.fullmatch(r"container-[0-9]+-filterstyledselect-0", o.get("id") or ""):
            continue
        if not o.get("shown"):
            continue
        labels = [_tidy(t) for t in o.get("labels") or []]
        years = set()
        current = False
        for t in labels:
            if re.fullmatch(r"\d{4}\s*,\s*current selection(\s*,\s*you[’']ve reached the end of the "
                            r"(?:list|menu))?", t, re.I):
                current = True
                years.add(int(t[:4]))
                continue
            m = YEAR_OPTION_RE.fullmatch(t)
            if not m:
                raise ListStopped("a year in the picker reads in a way this cannot read")
            years.add(int(m.group(1)))
        if len(years) != 1 or not re.fullmatch(r"container-[0-9]+-filterstyledselect-0", o.get("id") or ""):
            raise ListStopped("a year in the picker reads in a way this cannot read")
        year = years.pop()
        out.append((year, "#" + o["id"], current))
        if any(_END_WORDS_RE.search(t) for t in labels):
            ends.append(year)
    if len({y for y, _c, _cur in out}) != len(out):
        raise ListStopped("the picker offers one year twice")
    if out and ends != [min(y for y, _c, _cur in out)]:
        raise ListStopped("the picker's oldest year does not say it ends the menu")
    return out


def _open_picker(page, run: Run) -> List[Tuple[int, str, bool]]:
    """Open the "View:" picker, unless its years show already, and read
    them."""
    state = _read(page)
    if not any(o.get("shown") for o in state.get("options") or []):
        css = "#" + YEAR_PICKER_ID
        _press(page, page.locator(css), css=css, what="the year picker",
               guard=is_year_picker, step="open the year picker", run=run)
        state = _wait_for(page, lambda s: any(o.get("shown") for o in s.get("options") or []),
                          MENU_WAIT_MS)
        if state is None:
            raise ListStopped("the year picker showed no years")
    return _options(state)


def _choose_year(page, run: Run, acct: Account, current_year: int, year: int,
                 options: List[Tuple[int, str, bool]]) -> List[Item]:
    """Choose `year` in the picker and read its list: exactly one answer for
    this account and that year's filter, rows checked against it."""
    hits = [(css, cur) for y, css, cur in options if y == year]
    if len(hits) != 1:
        raise ListStopped("the picker does not offer the year once")
    css, cur = hits[0]
    if cur:
        raise ListStopped("the year is the current selection already")
    filt = filter_for(current_year, year)
    matches = _await_answers(
        page, acct.account_id, filt,
        lambda: _press(page, page.locator(css), css=css, what="a year in the picker",
                       guard=is_year_option, step="choose a year", run=run),
        LIST_WAIT_MS)
    if len(matches) != 1:
        raise ListStopped("%d list answers came for the year chosen" % len(matches))
    if _picker_year(_read(page)) != year:
        raise ListStopped("the picker does not show the year chosen")
    items = read_answer(matches[0], run, year)
    _cross_check(page, items)
    return items


def _rawdocs(acct: Account, items: List[Item]) -> List[RawDoc]:
    title = "%s Statement" % acct.klass
    return [RawDoc(title=title, account=acct.klass, date_text=i.date, href="", text=title,
                   kind="statement", document_id="", account_ref=acct.ref,
                   doc_type=i.doc_type, page_count=i.pages, account_digest=acct.digest)
            for i in items]


def _account_docs(page, run: Run, acct: Account, accounts: List[Account]) -> List[RawDoc]:
    """Every statement of one account, each year the picker offers. The
    menu the document center opens with must list the same accounts as
    the one the listing began from."""
    opened = _open(page)
    if accounts_of(opened.state) != accounts:
        raise ListStopped("the account menu changed during the listing")
    arrived = _arrive(page, run, opened, acct)
    if arrived is None:
        log.info("a %s account shows no Statements", acct.klass)
        return []
    items, current_year = arrived
    docs = _rawdocs(acct, items)
    log.info("%s %d: %d statement(s)", acct.klass, current_year, len(items))
    years = [y for y, _css, _cur in _open_picker(page, run)]
    if current_year not in years:
        raise ListStopped("the picker does not offer the current year", docs)
    for year in sorted((y for y in years if y != current_year), reverse=True):
        try:
            options = _open_picker(page, run)
            if sorted(y for y, _c, _cur in options) != sorted(years):
                raise ListStopped("the picker offers other years than before")
            items = _choose_year(page, run, acct, current_year, year, options)
        except ListStopped as stop:
            raise ListStopped(str(stop), docs)
        docs.extend(_rawdocs(acct, items))
        log.info("%s %d: %d statement(s)", acct.klass, year, len(items))
    return docs


def _pass_over(page, run: Run, holder: Account, accounts: List[Account],
               holders: List[Account]) -> None:
    """Choose a cardholder's menu entry with the account press and pass it
    over only when it shows no Statements accordion (_arrive gives None).
    Live, the cardholder shows only notices. An entry of that shape that
    shows Statements may be a second card or an account nicknamed like a
    person, so it stops the list rather than be left out of a list called
    whole."""
    opened = _open(page)
    if _menu_of(opened.state) != (accounts, holders):
        raise ListStopped("the account menu changed during the listing")
    if _arrive(page, run, opened, holder) is not None:
        raise ListStopped("a menu entry that reads as a cardholder shows Statements")
    log.info("a cardholder's menu entry shows no Statements and is passed over")


def collect_download_docs(page, run: Optional[Run] = None) -> List[RawDoc]:
    """Every statement of every business account in the menu. Raises
    ListStopped holding what was read when any part cannot be read, and
    SessionExpired for a signed-out session."""
    run = run or Run()
    opened = _open(page)
    accounts, holders = _menu_of(opened.state)
    if not accounts:
        raise ListStopped("the account menu names no business account this app reads")
    docs: List[RawDoc] = []
    for acct in accounts:
        try:
            docs.extend(_account_docs(page, run, acct, accounts))
        except ListStopped as stop:
            raise ListStopped(str(stop), docs + stop.docs)
    for holder in holders:
        try:
            _pass_over(page, run, holder, accounts, holders)
        except ListStopped as stop:
            raise ListStopped(str(stop), docs + stop.docs)
    if run.unproven():
        raise ListStopped("every year read was empty, so none showed what success looks like", docs)
    # A statement is its account, date and type (Chase mints its documentId
    # anew each session), so two listed alike would share one record and no
    # download could tell them apart. Two statements of one account on one
    # date stop the list here on every run (README, Validation status).
    seen = set()
    for d in docs:
        ident = (d.account_digest, d.date_text, d.doc_type)
        if ident in seen:
            raise ListStopped("one account has two statements on one date", docs)
        seen.add(ident)
    return docs


def goto_documents(page) -> bool:
    """Open the document center by its address and prove it ready. False
    when it showed the sign-in page or did not open. Nothing is pressed."""
    try:
        _open(page)
        return True
    except (SessionExpired, ListStopped) as e:
        log.info("the document center did not open: %s", e)
        return False


def scroll_full_page(page, rounds: int = 0, delay_ms: int = 0) -> None:
    """Nothing to scroll: every statement of a year is one table."""
    return None


def expand_all(page) -> None:
    """Nothing to press beyond the seven controls in the module docstring."""
    return None


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def bind(items: List[Item], rows: list, document_id: str, iso_date: str, doc_type: str,
         pages: int) -> int:
    """The row number of the one statement to save, or -1.

    Exactly one answered statement must have the record's date, type and
    page count, and exactly one shown row must read that same date, type and
    page count. The documentId is not compared (see below)."""
    # Chase mints a statement's documentId anew each session, so it names
    # nothing across runs: the record is its account, date, type and page
    # count, and exactly one answered statement must carry that shape.
    want = (iso_date, doc_type, int(pages or 0))
    api = [i for i in items if i.shape == want]
    if len(api) != 1:
        return -1
    hits = [r for r in rows if r.get("shown") and row_shape(r.get("cells")) == want]
    if len(hits) != 1:
        return -1
    return _row_number(hits[0].get("id") or "")


def _reach_row(page, run: Run, digest: str, document_id: str, iso_date: str,
               doc_type: str, pages: int, trace: Optional[list]) -> Tuple[int, str]:
    """Open the document center afresh, choose the record's account, open
    Statements, choose the record's year and bind the record to one row.
    The row's number and the account's last four, or -1 with nothing
    pressed past the list."""
    opened = _open(page)
    accts = [a for a in accounts_of(opened.state) if a.digest == digest]
    if len(accts) != 1:
        if trace is not None:
            trace.append({"note": "the account is not in the menu once"})
        return -1, ""
    acct = accts[0]
    arrived = _arrive(page, run, opened, acct)
    if arrived is None:
        if trace is not None:
            trace.append({"note": "the account shows no statements"})
        return -1, ""
    items, current_year = arrived
    year = int(iso_date[:4])
    if year != current_year:
        items = _choose_year(page, run, acct, current_year, year, _open_picker(page, run))
    n = bind(items, _read(page).get("rows") or [], document_id, iso_date, doc_type, pages)
    if n < 0 and trace is not None:
        trace.append({"note": "no single statement and row match the record"})
    return n, acct.tail


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


# Which "Save as PDF" the bound row's save menu shows, read only. The option
# must be inside the bound row itself, or inside the menu its save control
# names as its own (aria-controls or aria-owns), and it must be the only
# shown "Save as PDF" anywhere on the page, so no detached or other row's
# option can stand in for it.
_MENU_JS = r"""(args) => {
  // Every row's save menu is in the DOM, closed ones included, and a closed
  // one's Save as PDF has a box but no words; only an option drawn with its
  // words, in an open menu, is shown.
  const shown = el => {
    if (!el) return false;
    const r = el.getBoundingClientRect(), s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'
           && parseFloat(s.opacity || '1') > 0 && (el.innerText || '').trim().length > 0;
  };
  const out = {controls: 0, option: false, shownOptions: 0, inRow: false, menuId: '',
               triggerId: '', expandedSelf: false, expandedOthers: 0};
  const row = document.getElementById(args.row);
  if (!row) return out;
  const controls = Array.from(row.querySelectorAll(args.control));
  out.controls = controls.length;
  // The option is an anchor, item-0-<N>-…; the span inside it, itemLink-0-<N>-…,
  // ends the same way and is not a second option.
  out.shownOptions = Array.from(document.querySelectorAll('a[id^="item-"][id$="-downloadPDFOption"]')).filter(shown).length;
  const opt = document.getElementById(args.option);
  out.option = shown(opt);
  if (!opt || controls.length !== 1) return out;
  out.inRow = row.contains(opt);
  const trigger = controls[0];
  out.triggerId = trigger.id || '';
  out.expandedSelf = (trigger.getAttribute('aria-expanded') || '').toLowerCase() === 'true';
  out.expandedOthers = Array.from(document.querySelectorAll('a[id^="header-"][id$="-cell3-downloadDocumentDropdown"]'))
    .filter(t => t !== trigger && (t.getAttribute('aria-expanded') || '').toLowerCase() === 'true').length;
  const ids = ((controls[0].getAttribute('aria-controls') || '') + ' ' +
               (controls[0].getAttribute('aria-owns') || '')).split(/\s+/).filter(Boolean);
  const menus = ids.map(i => document.getElementById(i)).filter(m => m && m.contains(opt));
  if (menus.length === 1) out.menuId = menus[0].id || '';
  return out;
}"""

_MENU_ID_RE = re.compile(r"[A-Za-z0-9_:.-]{1,100}")


def _own_pdf_option(page, n: int) -> str:
    """The selector of the bound row's own "Save as PDF", or "" while it is
    not proven to be that.

    The row's save control must be exactly
    header-accountsTable-STATEMENTS-row<N>-cell3-downloadDocumentDropdown and
    the option item-0-<N>-downloadPDFOption, the same N, as the survey found
    them, no other row's save control may be expanded, and the option must
    be the only shown Save as PDF on the page. It is then taken inside the
    row itself, or inside the one menu the control names (aria-controls or
    aria-owns) only while this control is the one expanded, since such a
    popup can be shared by every row."""
    row = "accountsTable-STATEMENTS-row%d" % n
    option = "item-0-%d-downloadPDFOption" % n
    try:
        seen = page.evaluate(_MENU_JS, {"row": row, "option": option,
                                        "control": 'a[id^="header-"][id$="-row%d-cell3-downloadDocumentDropdown"]' % n})
    except Exception:
        return ""
    if not isinstance(seen, dict) or seen.get("controls") != 1 or not seen.get("option") \
            or seen.get("shownOptions") != 1 or seen.get("expandedOthers") != 0 \
            or seen.get("triggerId") != "header-%s-cell3-downloadDocumentDropdown" % row:
        return ""
    # Either way the bound control itself must read expanded: an option drawn
    # inside a row whose menu is closed is stale, not this press's.
    if seen.get("expandedSelf") is not True:
        return ""
    if seen.get("inRow"):
        return "#%s #%s" % (row, option)
    menu = str(seen.get("menuId") or "")
    if _MENU_ID_RE.fullmatch(menu):
        return '[id="%s"] #%s' % (menu, option)
    return ""


class _LeftTurnedOff(Exception):
    """The row's last control was turned off and not pressed (_press_row)."""


def _row_shape_of(page, menu_css: str, anchor_css: str) -> str:
    """Which way the bound row saves its statement: "menu" for a checking
    row's save menu, "anchor" for a business card row's own Saves document
    link. Read only. A row that shows both, or neither, stops the list,
    since this cannot tell which of them is the statement's own."""
    try:
        has_menu = page.locator(menu_css).count() > 0
        has_anchor = page.locator(anchor_css).count() > 0
    except Exception as e:
        raise ListStopped("the statement's row could not be read (%s)" % type(e).__name__)
    if has_menu and has_anchor:
        raise ListStopped("the statement's row shows both a save menu and a Saves document link")
    if not has_menu and not has_anchor:
        raise ListStopped("the statement's row shows neither a save menu nor a Saves document link")
    return "menu" if has_menu else "anchor"


def _take_arrived(page, run: Run, dl, start: int, dl_dir, before, out_path: Path,
                  trace: Optional[list], name: str, popups_from: Optional[int] = None) -> bool:
    """Take the one download the last press, `name`, brought, once the page
    has had a moment to raise a second one. More than one download, a new
    tab since `popups_from` when new tabs are watched (Run.watch_popups), a
    download from anywhere but Chase's PDF path, or one that is not a PDF
    stops the run with nothing taken."""
    check_signed_in(page)
    page.wait_for_timeout(SECOND_DOWNLOAD_WAIT_MS)
    check_signed_in(page)
    came = run.downloads[start:]
    if len(came) != 1:
        _cancel_all(came)
        raise _stop("More than one download came after one %s, so none was taken." % name,
                    "more than one download came")
    run.taken = len(run.downloads)
    if popups_from is not None and len(run.popups) > popups_from:
        _cancel_all([dl])
        raise _stop("A new tab opened after %s was pressed, so nothing was taken." % name,
                    "a new tab opened")
    if not is_download_url(getattr(dl, "url", "") or ""):
        _cancel_all([dl])
        raise _stop("The download did not come from Chase's statement address, so it was "
                    "not taken.", "the download came from elsewhere")
    try:
        how = _take_download(dl, dl_dir, before, out_path)
        if trace is not None:
            trace.append({"note": "download taken" if how else "download not taken", "how": how})
        if not how or not out_path.exists() or out_path.read_bytes()[:5] != b"%PDF-":
            try:
                out_path.unlink()
            except OSError:
                pass
            raise _stop("The download was not a PDF, so it was not kept.", "the download was not a pdf")
        return True
    finally:
        # The browser's own copy, whichever way the take went.
        try:
            _clear_copies(dl_dir, before, out_path)
        except Exception:
            pass


def _catch_statement(page, run: Run, dl_dir, n: int, iso_date: str, out_path: Path,
                     trace: Optional[list]) -> bool:
    """Save row `n`'s statement, the one way the row offers, and take the
    one download that brings, through the core.

    A checking row carries a save menu: it is pressed, and then its own Save
    as PDF, once each. A business card row carries no menu, only "<date> ,
    opens document" and "<date> Saves document" links, and its Saves
    document is pressed once (_catch_by_anchor). A row with both or neither
    stops the list with nothing pressed (_row_shape_of).

    A download already on its way or one no press of this run took, a Save
    as PDF that is not the bound menu's own, none in time, a second
    download, one from anywhere but Chase's PDF path, one that is not a
    PDF, or a new tab once a card's press has made the run watch for them
    (Run.watch_popups) stops the run: nothing more is pressed for this or
    any later statement. The run listens for downloads from its first save to its
    end (Run.watch), so a second download that comes late still stops the
    next statement before anything is pressed for it."""
    out_path = Path(out_path)
    row_css = "#accountsTable-STATEMENTS-row%d" % n
    # The one exact anchor of each shape the surveys found, named before the
    # press: a lookalike with the same words and a longer id is never
    # pressed.
    menu_css = "%s a#header-accountsTable-STATEMENTS-row%d-cell3-downloadDocumentDropdown" % (row_css, n)
    anchor_css = "%s a#accountsTable-STATEMENTS-row%d-cell3-requestThisDocumentAnchor-download" % (row_css, n)
    run.watch(page)
    before = _snapshot(dl_dir)
    try:
        if _unfinished(dl_dir):
            raise _stop("A download was still arriving before this statement was saved, "
                        "so nothing was pressed.", "a download was pending")
        if run.untied():
            raise _stop("A download came that no Save as PDF of this run took, so nothing "
                        "more is pressed.", "a download came that no press took")
        if run.popups:
            raise _stop("A new tab opened after a statement was saved, so nothing more is "
                        "pressed.", "a new tab opened")
        # New tabs are watched only once a card's Saves document has been
        # pressed in this run (Run.watch_popups), so a checking-only run
        # never has one, and a checking row after a card is held to it too.
        popups_from = len(run.popups)
        if _row_shape_of(page, menu_css, anchor_css) == "anchor":
            return _catch_by_anchor(page, run, dl_dir, before, anchor_css, iso_date, out_path, trace)
        if not _press_row(page, page.locator(menu_css), css=menu_css,
                          what="the statement's save menu", guard=is_save_menu,
                          expect=_row_label_date(iso_date), step="open the save menu", run=run):
            if trace is not None:
                trace.append({"note": "the save menu is turned off"})
            return False
        waited = 0
        while True:
            check_signed_in(page)
            pdf_css = _own_pdf_option(page, n)
            if pdf_css:
                break
            if waited >= MENU_WAIT_MS:
                raise _stop("The statement's save menu did not show its own Save as PDF, "
                            "alone, so nothing more was pressed.",
                            "the save menu showed no save as pdf of its own")
            page.wait_for_timeout(POLL_MS)
            waited += POLL_MS
        if run.untied() or _unfinished(dl_dir):
            _cancel_all(run.downloads[run.taken:])
            raise _stop("A download came before Save as PDF was pressed, so it was not pressed.",
                        "a download came before the press")
        if len(run.popups) > popups_from:
            raise _stop("A new tab opened after the save menu was pressed, so Save as PDF was "
                        "not pressed.", "a new tab opened")
        start = len(run.downloads)
        try:
            with page.expect_download(timeout=DOWNLOAD_WAIT_MS) as info:
                if not _press_row(page, page.locator(pdf_css), css=pdf_css,
                                  what="Save as PDF in the statement's save menu",
                                  guard=is_save_as_pdf, step="save the statement", run=run):
                    # Raised to leave the wait at once: a wait left by an
                    # exception is called off rather than waited out.
                    raise _LeftTurnedOff()
            dl = info.value
        except _LeftTurnedOff:
            if trace is not None:
                trace.append({"note": "save as pdf is turned off"})
            return False
        except (SessionExpired, ListStopped):
            raise
        except Exception as e:
            check_signed_in(page)
            if trace is not None:
                trace.append({"note": "no download came", "error": type(e).__name__})
            raise _stop("Save as PDF was pressed and no download came.", "no download came")
        return _take_arrived(page, run, dl, start, dl_dir, before, out_path, trace, "Save as PDF",
                             popups_from=popups_from)
    finally:
        try:
            _clear_copies(dl_dir, before, out_path)
        except Exception:
            pass


def _catch_by_anchor(page, run: Run, dl_dir, before, anchor_css: str, iso_date: str,
                     out_path: Path, trace: Optional[list]) -> bool:
    """Press a business card row's own "<date> Saves document" link once,
    its label proven to be that row's date and those words alone, and take
    the one download it brings. Live, the press makes the page fetch the PDF
    from Chase's PDF path and the browser download it, with no new tab and
    no new address. A new tab, a second download, one from elsewhere, none,
    or one that is not a PDF stops the run as the save menu's do. A PDF
    that does not print the row's date as its statement date is not kept,
    and the statement is left for review (names_date)."""
    # Watched from here to the run's end, so a tab that opens late still
    # stops the next statement before anything is pressed for it.
    run.watch_popups(page)
    popups_from = len(run.popups)
    start = len(run.downloads)
    try:
        with page.expect_download(timeout=DOWNLOAD_WAIT_MS) as info:
            if not _press_row(page, page.locator(anchor_css), css=anchor_css,
                              what="the statement's Saves document link",
                              guard=is_saves_document, expect=_row_label_date(iso_date),
                              step="save the statement", run=run):
                raise _LeftTurnedOff()
        dl = info.value
    except _LeftTurnedOff:
        if trace is not None:
            trace.append({"note": "saves document is turned off"})
        return False
    except (SessionExpired, ListStopped):
        raise
    except Exception as e:
        check_signed_in(page)
        if trace is not None:
            trace.append({"note": "no download came", "error": type(e).__name__})
        raise _stop("Saves document was pressed and no download came.", "no download came")
    _take_arrived(page, run, dl, start, dl_dir, before, out_path, trace, "Saves document",
                  popups_from=popups_from)
    if not names_date(_pdf_text(out_path), iso_date):
        log.info("the statement dated %s does not print that date as its statement date, so "
                 "it is not kept", iso_date)
        if trace is not None:
            trace.append({"note": "the pdf does not print the statement's date"})
        try:
            out_path.unlink()
        except OSError:
            pass
        return False
    return True


# A date as a statement prints one: "10/13/26", "10/13/2026", "Oct 13, 2026",
# "October 13, 2026" or "2026-10-13".
_DATE_TOKEN = (r"(?:\d{1,2}/\d{1,2}/(?:\d{4}|\d{2})(?![\d/])|[A-Za-z]{3,9}\.?\s+\d{1,2},?\s+\d{4}(?!\d)"
               r"|\d{4}-\d{2}-\d{2}(?!\d))")
# A card statement's period, "Opening/Closing Date 09/14/26 - 10/13/26",
# whose second date is the statement's.
_PERIOD_RE = re.compile(r"Opening\s*/\s*Closing\s+Date\s*:?\s*(%s)\s*(?:-|–|to|through)\s*(%s)"
                        % (_DATE_TOKEN, _DATE_TOKEN), re.I)
# "Statement Date: 10/13/26" or "Closing Date 10/13/26", not the "Closing
# Date" inside "Opening/Closing Date", which the opening date follows.
_STATEMENT_DATE_RE = re.compile(r"(?<![/\w])(?<!/ )(?:Statement|Closing)\s+Date\s*:?\s*(%s)"
                                % _DATE_TOKEN, re.I)


def _token_iso(token: str) -> Optional[str]:
    """A _DATE_TOKEN as YYYY-MM-DD, or None for a day that does not exist.
    A two-digit year is in this century."""
    token = _tidy(token)
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4}|\d{2})", token)
    try:
        if m:
            year = int(m.group(3)) + (2000 if len(m.group(3)) == 2 else 0)
            return _date(year, int(m.group(1)), int(m.group(2))).isoformat()
        m = re.fullmatch(r"([A-Za-z]{3,9})\.?\s+(\d{1,2}),?\s+(\d{4})", token)
        if m:
            name = m.group(1).lower()
            month = _MONTHS.get(name[:3])
            full = ("january", "february", "march", "april", "may", "june", "july", "august",
                    "september", "october", "november", "december")
            # The month's three letters, its whole name, or "Sept", and no
            # other spelling.
            if month is None or name not in (name[:3], full[month - 1], "sept") \
                    or (name == "sept" and month != 9):
                return None
            return _date(int(m.group(3)), month, int(m.group(2))).isoformat()
        return answer_date(token)
    except ValueError:
        return None


def names_date(text: str, iso: str) -> bool:
    """Whether the text prints `iso` as its statement's own date: the
    closing date of an "Opening/Closing Date" period, as a card statement
    prints it, or the date after a "Statement Date" or "Closing Date"
    label. Only one date is judged, the first period's when the text
    prints one, else the first labeled date, as names_tail judges one
    number. A date printed anywhere else, a transaction's say, is not read,
    so another statement of the same card that lists a purchase on this
    date is not taken for this one."""
    if answer_date(iso) != iso:
        return False
    text = text or ""
    m = _PERIOD_RE.search(text)
    if m:
        return _token_iso(m.group(2)) == iso
    m = _STATEMENT_DATE_RE.search(text)
    return bool(m) and _token_iso(m.group(1)) == iso


def download_statement(page, run: Run, dl_dir, out_path, *, account_digest: str, document_id: str,
                       iso_date: str, doc_type: str, page_count: int,
                       trace: Optional[list] = None) -> bool:
    """Save the statement discovery recorded. The document center is opened
    afresh, the record's account found by its class and last four
    (account_digest) and chosen and proven current, Statements
    opened, its year chosen, and the record bound to exactly one answered
    statement and one shown row before anything is pressed on the row.
    False, with nothing pressed on the row, when any of that does not hold.
    False too when a control on the row is turned off, and when the PDF that
    came does not print the account's last four, since rows do not name
    their account. Such a PDF is not kept. SessionExpired and a stop of the
    run propagate."""
    out_path = Path(out_path)
    # The documentId is not required: Chase mints it anew each session, so
    # a record keeps none (see bind).
    if not (re.fullmatch(r"[0-9a-f]{12}", account_digest or "")
            and answer_date(iso_date) == iso_date and doc_type == "Statement" and int(page_count or 0) > 0):
        if trace is not None:
            trace.append({"note": "the record does not name one statement"})
        return False
    try:
        n, tail = _reach_row(page, run, account_digest, document_id, iso_date, doc_type,
                             int(page_count), trace)
    except ListStopped as stop:
        log.info("the list stopped while looking for the statement dated %s: %s", iso_date, stop)
        if trace is not None:
            trace.append({"note": "the list stopped", "why": str(stop)})
        return False
    if n < 0:
        return False
    try:
        if not _catch_statement(page, run, dl_dir, n, iso_date, out_path, trace):
            return False
    except ListStopped as stop:
        # A control on the row the guard refused, or not one control: it
        # was not pressed, and the statement is left for review.
        log.info("the statement dated %s was not saved: %s", iso_date, stop)
        if trace is not None:
            trace.append({"note": "the row's control was not pressed", "why": str(stop)})
        return False
    if not names_tail(_pdf_text(out_path), tail):
        log.info("the statement dated %s does not print its account's last four, so it is "
                 "not kept", iso_date)
        if trace is not None:
            trace.append({"note": "the pdf does not print the account's last four"})
        try:
            out_path.unlink()
        except OSError:
            pass
        return False
    return True


def names_tail(text: str, tail: str) -> bool:
    """Whether the statement's own account number, the one in its header,
    ends in these four digits. An account number is printed in full or
    masked, eight or more digits or masking marks in groups of four or
    more that a space or a dash may part, ending in four digits, as in
    "000000123451234" or "XXXX XXXX XXXX 1234" (_account_number).

    When the text has an "Account Number" label, the first account number
    printed after it is judged, on the label's line or a later one, since
    the owner's saved statement printed its number on a line of its own
    apart from the label. Only when there is no label is the first account
    number in the whole text judged. Either way only one number is judged,
    so another account's statement that names this account in a transfer
    line, or a long transaction number ending in the same four, is not
    kept. A ZIP+4, a mail sort number, a run of zeros, a phone number, a
    check number or a date printed before the number is no account number
    and is passed over (_account_number). Four digits are needed.

    Each run of digits and marks is found once, whole, and its groups are
    judged here, so a long run is read in one pass rather than tried every
    way a pattern could split it."""
    if not re.fullmatch(r"\d{4}", tail or ""):
        return False
    text = text or ""
    label = _ACCOUNT_LABEL_RE.search(text)
    for run in _NUMBER_RUN_RE.finditer(text, label.end() if label else 0):
        last = _account_number(run.group(0))
        if last:
            return last.endswith(tail)
    return False


def _account_number(run: str) -> str:
    """The last group of the account number a run of digits and marks holds,
    or "" for none. The number is the run's longest stretch of groups four
    or more long, the first of the longest on a tie, so a short group
    beside it on the same line, a page number or a date, is not part of
    it. The stretch must hold eight or more digits or marks and end in four
    digits. A stretch of digits alone is no account number when it holds
    eight digits or fewer, as a mail sort number, a page code or a date
    does, when every digit is a zero, or when it is a ZIP+4, five digits, a
    dash and four digits. One pass over the groups."""
    # Groups at the even places, the space or dash before each at the odd.
    parts = re.split(r"([ -])", run) + [" ", ""]
    first = last = start = -1
    best_len = cur_len = 0
    for i in range(0, len(parts), 2):
        if len(parts[i]) >= 4:
            if not cur_len:
                start = i
            cur_len += len(parts[i])
            continue
        if cur_len > best_len:
            first, last, best_len = start, i - 2, cur_len
        cur_len = 0
    if best_len < 8 or not parts[last][-4:].isdigit():
        return ""
    groups = parts[first:last + 1:2]
    digits = "".join(groups)
    if digits.isdigit():
        zip_plus_four = [len(g) for g in groups] == [5, 4] and parts[first + 1] == "-"
        if len(digits) <= 8 or not digits.strip("0") or zip_plus_four:
            return ""
    return parts[last]


# The label Chase prints before a statement's account number, "Account
# Number" in title case or capitals with any spacing between its words. A
# colon after it, if any, is passed over with the other text before the
# number. Lower case is prose, as in "tell us your name and account
# number", not the label.
_ACCOUNT_LABEL_RE = re.compile(r"\b(?:Account\s+Number|ACCOUNT\s+NUMBER)\b")


# A run of digits and masking marks, in groups a single space or dash
# parts. A separator must come between groups, so the run is matched in one
# pass whatever its length.
_NUMBER_RUN_RE = re.compile(r"(?<![0-9A-Za-z])[0-9Xx*\u2022]+(?:[ -][0-9Xx*\u2022]+)*")


# ---------------------------------------------------------------------------
# Diagnose. Reads only, presses nothing. No screenshot.
# ---------------------------------------------------------------------------

def collect_documents(page) -> List[RawDoc]:
    """The statement rows drawn now, by shape only (date, type, pages),
    nothing that names an account."""
    try:
        state = _read(page)
    except (ListStopped, SessionExpired):
        return []
    out = []
    for r in state.get("rows") or []:
        shape = row_shape(r.get("cells"))
        if shape:
            out.append(RawDoc(title="Statement", date_text=shape[0], text="%s %d pages" % (shape[1], shape[2]),
                              row_index=_row_number(r.get("id") or ""), kind="statement"))
    return out


def survey(page, dwell_ms: int = 4000, max_follow: int = 0) -> dict:
    """What the signed-in document center shows, by counts and the guard's
    verdicts, without a label of the page's. Presses nothing."""
    page.wait_for_timeout(dwell_ms)
    try:
        state = _read(page)
    except (ListStopped, SessionExpired) as e:
        return {"pages": [], "error": type(e).__name__}
    guard_menu(state)
    menu = state.get("menu") or []
    return {"pages": [{
        "url": redact(page.url or ""),
        "documents_route": is_documents_url(page.url or ""),
        "menu_entries": len(menu),
        "menu_entries_the_guard_takes": sum(1 for e in menu
                                            if (e.get("labels") or [""])
                                            and all(is_account_entry(t) for t in e.get("labels") or [""])),
        "menu_entries_by_class": {k: sum(1 for e in menu
                                         if account_class((e.get("labels") or [""])[0]) == k)
                                  for k in ("Business Checking", "Business Card", "Business Debit", "")},
        "current_entries": sum(1 for e in menu if _is_current(e)),
        "accordions": [re.sub(r"^button-accountsAccordian-", "", a.get("id") or "")[:30]
                       for a in state.get("accordions") or []
                       if re.fullmatch(r"button-accountsAccordian-[A-Z_]{1,30}", a.get("id") or "")],
        "statements_open": any(a.get("id") == STATEMENTS_ACCORDION_ID
                               and (a.get("expanded") or "").lower() == "true"
                               for a in state.get("accordions") or []),
        "picker_year": _picker_year(state),
        "rows": len(state.get("rows") or []),
        "rows_readable": sum(1 for r in state.get("rows") or [] if row_shape(r.get("cells"))),
        "timeout_dialog_open": bool(state.get("dialog")),
    }]}
