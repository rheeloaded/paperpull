"""ALL card.apple.com selectors, URLs, and page behavior live here.

When Apple changes card.apple.com, repair this file only.

STATUS: CONFIRMED on the tester's account (#52). A Pilot and then a full
run saved the card's statements, the Savings statements and the 1099-INT
forms, since 0.39.0 takes each PDF where the page builds it. This app was
written without an Apple Card or a Savings account, from the sign-in
address the requester named and what Apple says in public about
card.apple.com, and rebuilt from the Record and Diagnose files he sent.
Those facts are marked RECORDED, and what nobody has seen is still marked
GUESS. On a run it is deliberately cautious.

  * --login opens a real Edge or Chrome at card.apple.com, whose sign-in
    (an Apple Account with a code sent to a trusted device) is the user's
    to complete.
  * --record writes down the path the tester takes to one document of
    each kind, which is what this file is waiting on.
  * --diagnose surveys whatever the card, Savings and tax pages turn out
    to be, records their headings, their controls with the guard's
    verdict on each, and the shape of every JSON response, with digit
    runs masked, and takes no screenshot.
  * --discover visits the three sections in turn and reads a date from
    every control that looks like it fetches one document.
  * --pilot tries to save the newest few, by fetching a PDF link the row
    carries from inside the page, or by pressing the row's own control
    once and catching a download event, a PDF response or a new tab.

The guesses still open are marked GUESS. The biggest one was the year a
tax form's button names, read as the form's own tax year, and the tester
has since confirmed it against the year printed on the form itself.

What is public and believed true, still to be confirmed by a Record.
Apple Card statements run for a calendar month, so a statement named by
its month closes on that month's last day. Apple's help pages say a
statement can be downloaded as a PDF from card.apple.com, and that
transactions can also be exported as CSV or OFX, which this app never
wants. Savings is managed from the same Apple Card account and has its
own monthly statements, and a Savings account that earned interest gets a
1099-INT.

RECORDED in round one. card.apple.com is one page that draws each
section itself when its menu link is pressed, and an address typed in
for a section answers 404. The card's statements are the menu's
Statements. Savings statements and tax forms are under the menu's
Savings, then Documents, then "Statements" or "Tax Documents", each with
its count. On all three lists every document is one button labeled
"Download statement of <month> <year> (PDF)", and pressing it downloads
the PDF straight away, with no new tab and no second step, under a name
Apple gives it, "Apple Card Statement - <month> <year>.pdf", "Savings
Statement - <month> <year>.pdf" or "1099-INT <year> - Tax Form.pdf".
Only a button named that exact way is ever read as a document, since the
Savings page also carries a control that a wider pattern took for a
document's and that is not one. Because the three lists look alike, a
list is read only once the one it replaced is gone and its own content
agrees (goto_section, _list_checks), and a file whose name Apple wrote
for another document is never saved (_catch_pdf).

SAFETY (this is a credit card and a bank account, both able to move money):
  This module is strictly READ-ONLY. It opens the statement and document
  pages, reads the lists, and saves the PDFs Apple already generated. It
  must NEVER activate any control that pays, schedules a payment,
  transfers, adds money to or withdraws from Savings, moves money between
  the card and Savings, changes where Daily Cash goes, sends Apple Cash,
  disputes a charge, reports a card lost, shows a card number, requests a
  new card or a higher limit, shares the card with family, links a bank
  account, opens or closes anything, or edits any setting.
  FORBIDDEN_CONTROL_RE is the guard. A control must ALSO look like a
  document action (SAFE_DOC_CONTROL_RE) or be one of the few section
  names (SECTION_NAV_RE) before it may be pressed. There is no code here
  that submits a form or confirms a dialog.
"""

from __future__ import annotations

import logging
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import urlsplit

from paperpull_core.controls import SETTINGS_CONTROL_RE, AUTH_CONTROL_RE

# Everything on its way into a diagnostic file goes through here. It
# lives in core because seventeen apps each had their own copy and
# they drifted into three different versions.
from paperpull_core.redact import redact, set_private_words  # noqa: F401
from paperpull_core.urls import is_safe_url as _host_allows
from paperpull_core.api_census import shape_of as _shape
from paperpull_core.dates import last_day as _last_day
# re-exported, since this app's docs module calls it as site.set_download_dir
from paperpull_core.capture import set_download_dir  # noqa: F401
from paperpull_core.capture import snapshot as _snapshot
from paperpull_core.capture import take_download as _take_download
from paperpull_core.capture import is_document as _is_document
from paperpull_core.capture import clear_copies as _clear_copies
from paperpull_core.capture import ask_again as _ask_again
from paperpull_core.capture import RequestsSince as _RequestsSince
from paperpull_core.capture import arrived as _folder_arrived
from paperpull_core.capture import take_new_pdf as _take_new_pdf
from paperpull_core.capture import fetch_pdf as _core_fetch_pdf
from paperpull_core.capture import take_new_tab as _core_take_new_tab
from paperpull_core.capture import take_same_tab as _core_take_same_tab
from paperpull_core.controls import control_texts as _control_texts
from paperpull_core.controls import second_step as _core_second_step
from paperpull_core.controls import controls_named as _controls_named
from paperpull_core.controls import escape_for_locator
from paperpull_core.dates import checked as _checked_date
from paperpull_core.dates import full_year as _full_year
from paperpull_core import pressing
from paperpull_core.words import words_for as _words_for

log = logging.getLogger("applecard_docs.site")


def _words():
    """This app's own words for paperpull_core.words, from what its source
    calls it, for saying what covered a control."""
    return _words_for("Apple Card", sys.modules[__name__])


BASE = "https://card.apple.com"

# The three kinds of document, each with the words its title starts with.
# The title is how the orchestrator hands a document back to be fetched,
# so it is also how download_bill knows which section to open.
CARD, SAVINGS, TAX = "card", "savings", "tax"
KINDS = (CARD, SAVINGS, TAX)
KIND_TITLE = {CARD: "Apple Card Statement", SAVINGS: "Savings Statement",
              TAX: "Tax Document"}

# RECORDED. The front page is the only address this app loads. Loaded
# directly, card.apple.com answered only its front page and /savings.
# /statements, /documents, /savings/statements and /savings/documents
# each came back 404 in the tester's Diagnose, although the menu's own
# links point at two of them, because the page draws each section itself
# when its link is pressed. So every list is reached through the menu,
# the way the tester reached it, and never by its address.
URLS = {
    "home": f"{BASE}/",
    # The sign-in is on the front page itself (#52).
    "login": f"{BASE}/",
    "documents": f"{BASE}/",
    "statements": f"{BASE}/",
}
BILLING_URL = URLS["home"]

# RECORDED. The links the tester pressed to reach each list, as (where,
# words), and every one of them was a link. "nav" is the menu along the
# top of every signed-in page and "main" is the page's own content. The
# card's statements are the menu's Statements. Savings statements and tax
# forms are both under the menu's Savings, then Documents, then a link
# that carries its count, like "Statements 12" or "Tax Documents 3". The
# menu's own Statements link is still on screen there and it is the
# card's, which is why the last two presses look only inside main, and
# why they need the count. Both links the tester pressed carried one, and
# the menu's Statements never does, so the card's link cannot be taken
# for the Savings statements even if a narrow window ever draws the menu
# inside the page's content.
SECTION_PATH = {
    CARD: [("nav", r"^\s*statements?\s*$")],
    SAVINGS: [("nav", r"^\s*savings\s*$"), ("main", r"^\s*documents?\s*$"),
              ("main", r"^\s*statements?\s*\d+\s*$")],
    TAX: [("nav", r"^\s*savings\s*$"), ("main", r"^\s*documents?\s*$"),
          ("main", r"^\s*tax\s+documents?\s*\d+\s*$")],
}

# RECORDED. The page has been drawn once one of the menu's section links
# is on screen. After a direct load of the front page the tester's
# Diagnose found no text, no link and no button about five seconds in,
# where the old fixed wait gave up, and the whole menu a few seconds
# later. So the wait is for the menu, with this long to draw it.
MENU_DRAWN_RE = re.compile(r"^\s*(statements?|savings)\s*$", re.I)
APP_DRAW_SECONDS = 30

# How long a press is given to redraw the page before it is read. The
# tester's next click came two to six seconds after each press, and a
# link or a list that is slower than this is waited for on its own.
STEP_SETTLE_MS = 3000

# How long a list is given, after the last press, to be the list that
# press asked for. Every document button on all three lists has the same
# kind of name and their months overlap, so a list left on screen from
# before the press would be read as the new one. What the list must show
# before it is taken is in _list_checks.
ARRIVE_SECONDS = 10

# How long a press on a document's button is given to produce the PDF
# before anything else is tried, how long a second press is given when the
# first produced nothing at all (_catch_pdf), and how long the last wait
# lasts. RECORDED, a press that works downloads at once (#52).
PRESS_WAIT_SECONDS = 10
AGAIN_WAIT_SECONDS = 15
LAST_WAIT_SECONDS = 15

# RECORDED. The link at the top of the Savings statements list, marked
# aria-current, that leads back to Savings' Documents. The card's
# statements have no link of that name anywhere on the page.
SAVINGS_BACK_RE = re.compile(r"^\s*documents?\s*$", re.I)

LOGIN_URL_MARKERS = ["/login", "/signin", "/sign-in", "/auth/", "/mfa",
                     "/verification", "/challenge", "/authenticate"]

# Apple's own sign-in hosts. Public, and not in ALLOWED_HOSTS, because
# nothing this app wants is ever served from them. A tab on one of these,
# or a sign-in frame from one, means the person is not signed in yet.
SIGN_IN_HOSTS = ("idmsa.apple.com", "appleid.apple.com", "account.apple.com")

# ---------------------------------------------------------------------------
# HARD SAFETY GUARD. Tuned for a credit card with a savings account behind
# it. Never move money in either direction, never touch Daily Cash or Apple
# Cash, never dispute, never show or replace a card, never change a
# setting. The bank words are the same as every other bank app's, except
# that "card" alone is allowed, because every statement here is an Apple
# Card statement, and the card words that matter are listed one by one.
# ---------------------------------------------------------------------------
FORBIDDEN_CONTROL_RE = re.compile(
    r"(transfer|zelle|\bwire\b|\bpay\b|payments?|pay\s*later|bill\s*pay|autopay|auto\s*pay|"
    r"schedul|recurring|deposit|withdraw|send\s+money|request\s+money|move\s+money|add\s+money|"
    # "Close Apple Card" and "Close Apple Card Account" too, with up to
    # three words between the verb and what it closes. Everything the
    # narrower form refused is still refused.
    r"\bapply\b|open\s+(an?\s+)?(account|savings)|close\s+(\w+\s+){0,3}(account|savings|card)|"
    r"\bloan\b|\bborrow|"
    r"daily\s+cash|apple\s+cash|\bcash\b|"
    r"card\s+(number|details?|info(rmation)?)|security\s+code|\bcvv\b|virtual\s+card|"
    r"physical\s+card|titanium|new\s+card|request\s+(a\s+)?card|"
    r"replace|activate|\block\b|unlock|freeze|\bpin\b|limit|\blost\b|stolen|\bfraud|"
    r"dispute|report\s+(an?\s+)?(issue|problem|charge|transaction)|"
    r"\bfamily\b|\bshare\b|sharing|invite|participant|co-?owner|"
    r"bank\s+accounts?|linked\s+accounts?|add\s+(a\s+)?bank|"
    r"overdraft|alerts?\b|notifications?|\bbudget|\bgoal|\brewards?\b|\boffers?\b|"
    r"enroll|unenroll|sign\s+up|paperless|delivery\s+preference|"
    r"enable|disable|change\b|edit\b|update\b|modify|manage\b|"
    r"set\s+up|delete|remove|cancel|"
    r"password|passcode|username|profile\b|settings|preferences|contact\s+info|\baddress\b|"
    r"confirm\b|submit|agree|accept|authorize|\bchat\b|contact\s+us|message|"
    r"beneficiar|nickname|sign\s*out|log\s*out|"
    # Not dangerous, but not a PDF either. Apple offers a transaction
    # export as CSV or OFX next to the statements, and refusing it here
    # means it can never be mistaken for the statement it sits beside.
    r"export|\bcsv\b|\bofx\b|\bqfx\b|\bqbo\b|quicken|spreadsheet)", re.I)

SAFE_DOC_CONTROL_RE = re.compile(
    r"(download|view|open|print|\bpdf\b|statement|document|\bletter\b|notice|"
    r"1099|tax\s+(form|document)|history|"
    r"see\s+(more|all|older)|show\s+(more|all|older)|load\s+more)", re.I)

# The few section names that are safe to press although they fetch no
# document themselves. Exact labels only, so "Savings" is a menu entry and
# "Savings transfer" never is.
SECTION_NAV_RE = re.compile(
    r"^\s*(savings(\s+account)?|statements?|documents?|tax\s+(documents?|forms?))\s*$", re.I)

# A control whose name says it fetches a document, wide on purpose. It is
# what the survey counts, and what tells a list the app reads from a
# challenge page. It is never what a document is read from. That is
# DOC_BUTTON_RE, the one shape recorded on all three lists, because the
# tester's own Diagnose (#52) found a control this matches on the Savings
# page that holds no document at all, and on the Tax Documents list any
# year printed near such a control would have been read as a tax form's.
BILL_CONTROL_RE = re.compile(
    r"((download|view|print|open|get)\s*(my\s+|the\s+|this\s+|your\s+)?(statement|document|pdf|tax|letter|notice|1099)|"
    r"(statement|document|tax\s+form|1099(-?int)?)\s*\(?\s*pdf\s*\)?|\bpdf\b|\b1099-?int\b|"
    r"^\s*(view|download|open)\s*$)", re.I)

# A link that points straight at a PDF, from a row's href.
PDF_HREF_RE = re.compile(r"\.pdf(\?|$)|/pdf\b|format=pdf|statement.*download|download.*statement|docId|documentId", re.I)

SECURITY_CHALLENGE_MARKERS = [
    "enter the code", "verification code", "6-digit", "two-factor",
    "two-step", "authenticator", "confirm your identity", "verify your identity",
    "we sent a code", "trusted device", "trusted phone number", "unusual",
    "are you a robot", "captcha", "check your email",
    "check your phone", "your session has expired", "log back in",
    "access denied", "reference #",
]

RATE_LIMIT_MARKERS = [
    "too many requests", "rate limit", "try again later",
    "temporarily unavailable", "http error 429", "unusual traffic",
]

# ---------------------------------------------------------------------------
# Fallback selectors (used by --diagnose only)
# ---------------------------------------------------------------------------
FALLBACK = {
    "doc_row": ("table tbody tr, [role='row'], [role='listitem'], [class*='statement' i], "
                "li[class*='document' i], [class*='document' i]"),
    "doc_link": "a[href*='.pdf'], a[download], button[class*='download' i]",
    # RECORDED. Each document's control is an element of Apple's own with
    # role=button and the name in aria-label, holding only an icon, so it
    # is counted by those two attributes. Plain CSS, so the failure file's
    # census can count it inside the page.
    "download_control": ("a[download], a[href$='.pdf'], [role='button'][aria-label*='download' i], "
                         "button[aria-label*='download' i]"),
    "page_ready": "table, [role='row'], [role='list'], main, [role='main']",
    "sign_in_frame": "iframe[src*='idmsa.apple.com'], iframe[src*='appleid.apple.com']",
}

# ---------------------------------------------------------------------------
# Date parsing
# ---------------------------------------------------------------------------
_MONTH = (r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
          r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|"
          r"Dec(?:ember)?)")
DATE_PATTERNS = [
    (re.compile(_MONTH + r"\.?\s+(\d{1,2}),?\s+(\d{4})", re.I), "mdY"),
    (re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b"), "mdy_slash"),
    (re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{2})\b"), "mdy_slash2"),
    (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})(?!\d)"), "iso"),
]
_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
MONTH_YEAR_RE = re.compile(r"\b" + _MONTH + r",?\s+(\d{4})\b", re.I)
YEAR_RE = re.compile(r"\b(19|20)(\d{2})\b")
TAX_YEAR_RE = re.compile(r"tax\s+year\s*:?\s*((?:19|20)\d{2})\b|\b((?:19|20)\d{2})\s+(?:form\s+)?1099|"
                         r"1099(?:-?int)?\s*(?:for\s+)?((?:19|20)\d{2})\b", re.I)
TAX_WORDS_RE = re.compile(r"1099|\btax\b", re.I)


def _one_exact(m, kind) -> Optional[str]:
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
        return None
    return None


def _parse_date_from_page(text: str) -> Optional[str]:
    if not text:
        return None
    for pattern, kind in DATE_PATTERNS:
        m = pattern.search(text)
        if m:
            got = _one_exact(m, kind)
            if got:
                return got
    return None


def parse_date(text):
    """The date this provider's page is showing, as YYYY-MM-DD.

    Refuses a result that names a day which does not exist, because a
    reference number is shaped like a date and used to be taken for one."""
    return _checked_date(_parse_date_from_page(text), None)


def _exact_dates(text: str) -> List[str]:
    """Every real day the text names, in order, each once."""
    out: List[str] = []
    for pattern, kind in DATE_PATTERNS:
        for m in pattern.finditer(text or ""):
            got = _checked_date(_one_exact(m, kind), None)
            if got and got not in out:
                out.append(got)
    return sorted(out)


def _month_ends(text: str) -> List[str]:
    """Every "August 2026" the text names, as that month's last day."""
    out: List[str] = []
    for m in MONTH_YEAR_RE.finditer(text or ""):
        month, year = _MONTHS[m.group(1)[:3].lower()], int(m.group(2))
        iso = f"{year:04d}-{month:02d}-{_last_day(year, month):02d}"
        if iso not in out:
            out.append(iso)
    return out


def document_date(kind: str, text: str) -> Optional[str]:
    """The one date a document's control or row gives it, or None.

    None whenever the text could mean two documents, because a statement
    saved under the wrong month is worse than one that is not saved. The
    same function reads discovery and the later download, so the control
    that is pressed is always the one that was listed.

    A statement is named by its month, which ends on the month's last day
    because Apple Card and Savings statements run for a calendar month. If
    no month is named, one printed day is taken, or two that are the ends
    of one statement period, the later being the close. A tax form is filed
    at the end of its tax year, the way every other app here files one.
    """
    text = text or ""
    if kind == TAX:
        m = TAX_YEAR_RE.search(text)
        if m:
            year = next(g for g in m.groups() if g)
            return f"{year}-12-31"
        # Without the words "tax year", a lone year is believed only when
        # nothing else on the row is a date. "Issued January 31, 2026" is
        # the 2025 form, and its year is the wrong one.
        if _exact_dates(text) or _month_ends(text):
            return None
        years = sorted({a + b for a, b in YEAR_RE.findall(text)})
        return f"{years[0]}-12-31" if len(years) == 1 else None
    months = _month_ends(text)
    if len(months) == 1:
        return months[0]
    if months:
        return None
    days = _exact_dates(text)
    if len(days) == 1:
        return days[0]
    if len(days) == 2:
        from datetime import date
        a, b = (date.fromisoformat(d) for d in days)
        if 0 < (b - a).days <= 45:
            return days[1]
    return None


# RECORDED. The name Apple gives every document's button, on the card's
# statements, the Savings statements and the tax forms alike.
DOC_BUTTON_RE = re.compile(r"^\s*download\s+statement\s+of\s+" + _MONTH +
                           r"\s+((?:19|20)\d{2})\s*\(\s*pdf\s*\)\s*$", re.I)


def tax_list_date(label: str) -> Optional[str]:
    """A form on the Tax Documents list, filed at the end of the year its
    button names, or None for a button named any other way.

    Apple names a tax form's button with a month and a year, the same way
    it names a statement's, so the words never say tax. In the first
    recording (#52) that button on the Tax Documents list saved a file
    Apple itself called "1099-INT <year> - Tax Form.pdf", with the same
    year the button gave, so that year is read as the form's own. RECORDED,
    the tester then checked the tax year printed on that form, and it is
    the year in the file's name. Only this exact shape is read, and only
    on that list, so a statement's month can never be taken for a tax
    year."""
    m = DOC_BUTTON_RE.match(label or "")
    return f"{m.group(2)}-12-31" if m else None


# RECORDED. The name Apple gave each file the tester's three presses
# downloaded, "Apple Card Statement - <month> <year>.pdf", "Savings
# Statement - <month> <year>.pdf" and "1099-INT <year> - Tax Form.pdf". A
# browser that already holds one may add " (1)" at the end.
APPLE_STATEMENT_FILE_RE = re.compile(r"^\s*(apple\s+card|savings)\s+statement\s*-\s*" + _MONTH +
                                     r"\s+((?:19|20)\d{2})\b", re.I)
APPLE_TAX_FILE_RE = re.compile(r"^\s*1099(?:-?[a-z]{1,4})?\s+((?:19|20)\d{2})\s*-\s*tax\s+form\b", re.I)


def apple_file_verdict(kind: str, iso: str, filename: str) -> Optional[dict]:
    """What the name Apple gave a downloaded file says about it, against
    the `kind` document dated `iso` that was asked for. None when the name
    is not one of the shapes Apple was recorded using, since a name that
    says nothing is no evidence either way. Otherwise which kind it names
    and whether its kind and its month, or a tax form's year, agree.

    A tax form's year here is the one Apple wrote into the file name, and
    the app files a form at the year its button names. The two agreed in
    the recording. If they ever disagree the form is not saved, and a
    repair is told which reading was wrong."""
    name = re.split(r"[\\/]", filename or "")[-1]
    m = APPLE_TAX_FILE_RE.match(name)
    if m:
        named, period, want = TAX, m.group(1), (iso or "")[:4]
    else:
        m = APPLE_STATEMENT_FILE_RE.match(name)
        if not m:
            return None
        named = SAVINGS if m.group(1).lower().startswith("savings") else CARD
        period = "%s-%02d" % (m.group(3), _MONTHS[m.group(2)[:3].lower()])
        want = (iso or "")[:7]
    return {"named_kind": named, "same_kind": named == kind, "same_period": period == want}


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


def kind_of_title(title: str) -> str:
    """Which section a document came from, from the title discovery gave
    it. A title this app did not write is read the same careful way."""
    t = (title or "").lower()
    if t.startswith(KIND_TITLE[TAX].lower()) or TAX_WORDS_RE.search(t):
        return TAX
    if "savings" in t:
        return SAVINGS
    return CARD


def title_for(kind: str, iso: str, label: str = "") -> str:
    """"Apple Card Statement - August 2026", "Savings Statement - August
    2026", "1099-INT - 2025". The month and year only, since a statement is
    a month, and the form's own name when the control carries it."""
    from datetime import date
    d = date.fromisoformat(iso)
    if kind == TAX:
        name = "1099-INT" if re.search(r"1099[\s-]*int", label or "", re.I) else KIND_TITLE[TAX]
        return f"{name} - {d.year}"
    return f"{KIND_TITLE[kind]} - {d.strftime('%B')} {d.year}"


_WORD_VALUE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_ -]{0,23}$")


def _plain_word(v: str) -> bool:
    """"STATEMENT", "LAST_90_DAYS", not an id, a token or a number."""
    return bool(_WORD_VALUE_RE.match(v)) and sum(ch.isdigit() for ch in v) <= 3


def _safe_query(url: str) -> str:
    """A URL's query parameters, names always, values only when they are
    plain words. A value with a digit, a token, an id, anything long, is
    "...". This is what a repair needs to make the same call, and nothing
    else."""
    from urllib.parse import parse_qsl
    try:
        pairs = parse_qsl(urlsplit(url).query, keep_blank_values=True)
    except ValueError:
        return ""
    out = []
    for k, v in pairs[:20]:
        out.append("%s=%s" % (k[:30], v if _plain_word(v) else "..."))
    return "&".join(out)


def _on_sign_in_host(url: str) -> bool:
    try:
        host = (urlsplit(url or "").hostname or "").lower().rstrip(".")
    except ValueError:
        return False
    return any(host == h or host.endswith("." + h) for h in SIGN_IN_HOSTS)


def looks_signed_out(page) -> bool:
    # page.url is read outside any try on purpose. A page that cannot say
    # where it is must not be called signed in.
    url = (page.url or "").lower()
    if any(m in url for m in LOGIN_URL_MARKERS) or _on_sign_in_host(url):
        return True
    try:
        if page.locator("input[type='password']").count() > 0:
            return True
    except Exception:
        pass
    # GUESS. Apple's sign-in is a frame from its own sign-in host, laid
    # over card.apple.com, so the password field is not on the page
    # itself. A frame that is there and carries a field to type an Apple
    # Account or a password into is a sign-in in progress. A frame alone
    # is not, since a signed-in page may keep one around.
    try:
        for frame in page.frames:
            if not _on_sign_in_host(frame.url or ""):
                continue
            fields = frame.locator("input[type='password'], #account_name_text_field")
            for i in range(min(fields.count(), 4)):
                if fields.nth(i).is_visible():
                    return True
    except Exception:
        pass
    return False


def detect_security_challenge(page) -> Optional[str]:
    """Names the passcode, CAPTCHA or throttling prompt on screen, or None.
    Visible text only. A page's source can carry every string its scripts
    could ever show, "verification code" included, on a normal day."""
    try:
        if _bill_controls(page).count() > 0:
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
    name = (name or "").strip()
    if not name:
        return False
    if FORBIDDEN_CONTROL_RE.search(name):
        return False
    if SETTINGS_CONTROL_RE.search(name) or AUTH_CONTROL_RE.search(name):
        return False
    return bool(SAFE_DOC_CONTROL_RE.search(name) or SECTION_NAV_RE.match(name))


# ---------------------------------------------------------------------------
# Downloads from a real Edge or Chrome attached over CDP. The browser saves
# the file itself, into its own Downloads folder, and Playwright's download
# event never fires. So the browser is pointed at a folder of ours and that
# folder is watched after every click.
# ---------------------------------------------------------------------------


def _take_new_tab(page, new_pages, out_path: Path) -> bool:
    """A PDF a click opened in a new tab. The core does the reading, this
    app's guard decides which addresses it may read."""
    return _core_take_new_tab(page, new_pages, out_path, is_safe_url)


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------

# The whole name of a button that dismisses something and does nothing
# else. Only the whole name, because "Close Apple Card Account" also
# starts with close, and an icon button carries its name in aria-label
# with no text of its own to check.
DISMISS_RE = re.compile(r"^\s*(close|dismiss|no,?\s*thanks|not\s+now)\s*$", re.I)


def dismiss_overlay(page) -> None:
    """Close a cookie banner, a survey prompt or a promo overlay, the things
    that sit over signed-in pages and intercept clicks. Escape first, then
    only a button whose whole name is close, dismiss, no thanks or not now,
    never accept. Its aria-label and its text are both put to the guard."""
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(250)
    except Exception:
        pass
    try:
        cl = page.get_by_role("button", name=DISMISS_RE)
        for i in range(min(cl.count(), 6)):
            el = cl.nth(i)
            try:
                if not el.is_visible():
                    continue
                words = [el.get_attribute("aria-label") or "", el.inner_text(timeout=500) or ""]
                if any(FORBIDDEN_CONTROL_RE.search(w) for w in words):
                    continue
                el.click(timeout=1000)
                page.wait_for_timeout(250)
            except Exception:
                continue
    except Exception:
        pass


def _bill_controls(page):
    """Every control on the page whose name says it fetches a document.
    The words are this provider's, the rest is the core's. Wide, for the
    survey and the counts. Documents are read from _doc_buttons."""
    return _controls_named(page, BILL_CONTROL_RE)


def _doc_buttons(page):
    """Every document button on the page, named the one way Apple names
    them on all three lists (DOC_BUTTON_RE). Nothing else on a list is
    ever read, dated, waited for or pressed as a document."""
    return _controls_named(page, DOC_BUTTON_RE)


def _headings(page) -> str:
    try:
        return " ".join(page.locator("h1, h2").all_inner_texts()[:6])
    except Exception:
        return ""


def _savingsy(page) -> bool:
    """Whether the page on screen is one of Savings'. RECORDED. Savings
    kept the address /savings on every page the tester opened under it,
    its Documents list and both lists below that included, and the card's
    statements were at the front page's address."""
    try:
        path = (urlsplit(page.url or "").path or "").lower()
    except ValueError:
        path = ""
    return "savings" in path or bool(re.search(r"\bsavings\b", _headings(page), re.I))


def _looks_like(page, kind: str) -> bool:
    """GUESS. Whether the page on screen is this section, from its words.
    Only the survey asks this now, to say what it thinks each page is.
    Opening a section goes by which link was pressed (goto_section),
    because the Savings statements and the tax forms share one address
    and one shape. A document control must be there. Savings is told from
    the card by the word Savings in the address or the top headings, and
    the card page must not say it, because a Savings statement filed as a
    card statement is the mistake this app is most likely to make."""
    try:
        if _bill_controls(page).count() == 0:
            return False
    except Exception:
        return False
    savingsy = _savingsy(page)
    try:
        body = page.locator("body").inner_text(timeout=5000)
    except Exception:
        return False
    if kind == TAX:
        return bool(re.search(r"1099|tax\s+(documents?|forms?)", body, re.I))
    # A page of tax forms alone is not a statements page, or a run that
    # starts on one would never go looking for the card's statements.
    if not re.search(r"\bstatements?\b", body, re.I):
        return False
    return savingsy if kind == SAVINGS else not savingsy


def _pause(page, ms: int) -> bool:
    """Wait on the page. False when the page can no longer be waited on."""
    try:
        page.wait_for_timeout(ms)
        return True
    except Exception:
        return False


def _app_drawn(page, seconds: int) -> bool:
    """Whether the menu has been drawn, asked once a second for up to
    `seconds`. A signed-out page stops the wait, since it never will be."""
    for waited in range(seconds + 1):
        try:
            links = page.locator("nav").get_by_role("link", name=MENU_DRAWN_RE)
            for i in range(min(links.count(), 4)):
                if links.nth(i).is_visible():
                    return True
        except Exception:
            pass
        if waited == seconds or looks_signed_out(page) or not _pause(page, 1000):
            return False
    return False


def _drawn_controls(page):
    """Handles to the document buttons on screen now, or None when they
    cannot be read. Taken before a walk, so that the list the walk opens
    can be told from one that was already there. Only the document buttons,
    so a control of another kind that stays on every Savings page, if
    there is one, does not make each new Savings list look like the one
    before it."""
    try:
        return _doc_buttons(page).element_handles()
    except Exception:
        return None


def _let_go(handles) -> None:
    for h in handles or []:
        try:
            h.dispose()
        except Exception:
            pass


_STILL_DRAWN_JS = "els => els.filter(e => e && e.isConnected && e.getClientRects().length > 0).length"


def _left_over(page, old) -> int:
    """How many of the controls in `old` are still drawn. When that cannot
    be asked, all of them are taken to be, since a list that cannot be
    shown to be new is not read as new."""
    if not old:
        return 0
    try:
        return int(page.evaluate(_STILL_DRAWN_JS, old))
    except Exception:
        return len(old)


def _savings_back_link(page) -> bool:
    """Whether the page's content holds the Savings lists' link back to
    Documents. When that cannot be asked, it is taken to be there, so
    the card's list is never taken on a page that could not be read."""
    try:
        links = page.locator("main").get_by_role("link", name=SAVINGS_BACK_RE)
        for i in range(min(links.count(), 4)):
            if links.nth(i).is_visible():
                return True
    except Exception:
        return True
    return False


def _count_in(label: Optional[str]) -> Optional[int]:
    """The count a link carries after its words, "Statements 12" or
    "Tax Documents 3", or None for a link without one."""
    m = re.search(r"(\d+)\s*$", label or "")
    return int(m.group(1)) if m else None


def _list_checks(page, kind: str, old, count: Optional[int]) -> dict:
    """What the list on screen must show before it is read as `kind`'s,
    each as True or False.

    Its document buttons, of the recorded shape, are drawn. None of the
    buttons that were on screen before the walk is still drawn, since a
    list left over from before the press looks exactly like the new one.
    The address agrees, a Savings address for the Savings statements and
    the tax forms and any other for the card's. The card's list has no
    link back to Savings' Documents, which the Savings statements list
    carries (RECORDED). A list reached through a link that carries a count
    holds no more documents than that count, which is what tells the tax
    forms from the Savings statements by what is on screen and not only
    by the link that was pressed (RECORDED, the tax link's count was the
    number of rows on the list it opened). Buttons that cannot be counted
    pass neither check."""
    shown = _count(_doc_buttons(page))
    within = shown >= 0 and (count is None or shown <= count)
    return {
        "documents_drawn": shown > 0,
        "earlier_list_gone": _left_over(page, old) == 0,
        "address_agrees": _savingsy(page) == (kind in (SAVINGS, TAX)),
        "no_savings_back_link": kind != CARD or not _savings_back_link(page),
        "within_its_count": within,
    }


def _arrived(page, kind: str, seconds: Optional[int] = None, old=None,
             count: Optional[int] = None, trace: Optional[list] = None) -> bool:
    """Whether the list on screen is `kind`'s, asked once a second for up
    to `seconds` until every one of _list_checks holds. Which of the two
    Savings lists it is comes first from the link that was pressed, since
    they share one address and one shape. A list that never passes is not
    read, and the trace says which check it failed, as True or False."""
    seconds = ARRIVE_SECONDS if seconds is None else seconds
    checks: dict = {}
    for waited in range(seconds + 1):
        checks = _list_checks(page, kind, old, count)
        if all(checks.values()):
            return True
        if waited == seconds or not _pause(page, 1000):
            break
    if trace is not None:
        entry = {"note": "the list on screen was not taken", "kind": kind}
        entry.update(checks)
        trace.append(entry)
    return False


def _step_control(page, step) -> Tuple[object, str]:
    """The visible link a path step names, inside its part of the page,
    once the guard has passed it, as (locator, label), or (None, "")."""
    where, pattern = step
    rx = re.compile(pattern, re.I)
    try:
        loc = page.locator(where).get_by_role("link", name=rx)
        for i in range(min(loc.count(), 6)):
            el = loc.nth(i)
            if not el.is_visible():
                continue
            label = (el.inner_text(timeout=800) or el.get_attribute("aria-label") or "").strip()
            if is_safe_control(label):
                return el, label
    except Exception:
        pass
    return None, ""


def _press_step(page, step, trace: Optional[list] = None, kind: str = "",
                index: int = 0, of: int = 0) -> Optional[str]:
    """Press the link a path step names, once, after the guard has passed
    it, and give back its label. None when there is none or the press
    failed. The trace says which step of which path it was and the count
    the link carried, never the link's own words."""
    el, label = _step_control(page, step)
    if el is None:
        return None
    try:
        el.click(timeout=5000)
    except Exception as e:
        log.info("pressing %r failed: %s", redact(label)[:60], e)
        return None
    _pause(page, STEP_SETTLE_MS)
    if trace is not None:
        trace.append({"note": "pressed a section menu entry", "kind": kind,
                      "step": index + 1, "of": of, "where": step[0],
                      "count": _count_in(label)})
    return label


def _furthest_step(page, path, start: int, seconds: int = 8) -> Optional[int]:
    """The furthest step along `path`, from `start` on, whose link is on
    screen, asked once a second for up to `seconds`. None when none of
    them appears."""
    for waited in range(seconds + 1):
        for j in range(len(path) - 1, start - 1, -1):
            if _step_control(page, path[j])[0] is not None:
                return j
        if waited == seconds or not _pause(page, 1000):
            return None
    return None


def _walk(page, kind: str, trace: Optional[list] = None) -> Optional[str]:
    """Press along `kind`'s path until its last link has been pressed, and
    give back that link's label, or None when the walk stopped short. The
    furthest link on screen is pressed each time, so a walk that starts
    partway along, on the Savings Documents list or on one of the two
    lists under it, carries on from there. That is also how the tester
    went from the Savings statements to the tax forms, back through
    Documents (#52)."""
    path = SECTION_PATH[kind]
    start = 0
    while start < len(path):
        j = _furthest_step(page, path, start)
        if j is None:
            return None
        label = _press_step(page, path[j], trace, kind, j, len(path))
        if label is None:
            return None
        if j == len(path) - 1:
            return label
        start = j + 1
    return None


# Which list this app last opened, at what address, the count its link
# carried, and when it was taken. Nothing but this app moves the page
# during a run, so the list on screen is kept only when it was opened here
# for the same kind and the address has not moved since. Anything else is
# opened again through the menu.
_ARRIVED: dict = {}


def goto_section(page, kind: str, trace: Optional[list] = None) -> bool:
    """Open the card's statements, the Savings statements or the Savings
    tax forms, by pressing through the menu the way the tester did (#52).

    The list already on screen is kept when this app opened it for the
    same kind. Otherwise the walk starts from the page on screen when the
    menu is drawn there, or from the front page loaded fresh, and a walk
    that does not arrive is tried once more from the front page. That
    covers a Savings page that keeps its address when the menu's
    Statements is pressed, which nobody has seen either way yet.

    The document buttons on screen before the walk are held on to, and
    the list the walk opens is not read while any of them is still drawn
    (_list_checks). Going from a Savings list to the card's is one press
    of the menu's Statements, and a page that moved its address before it
    redrew would otherwise hand over a Savings statement for the card's
    of the same month. A page that keeps those very buttons and relabels
    them is never shown to be new, so it is left for the fresh front page,
    which holds nothing from before."""
    dismiss_overlay(page)
    here = page.url or ""
    if (_ARRIVED.get("kind") == kind and _ARRIVED.get("url") == here and is_safe_url(here)
            and not looks_signed_out(page)
            and _arrived(page, kind, 0, count=_ARRIVED.get("count"))):
        return True
    _ARRIVED.clear()
    old = _drawn_controls(page)
    try:
        for attempt in range(2):
            if attempt or old is None or not (is_safe_url(page.url or "") and _app_drawn(page, 2)):
                try:
                    page.goto(URLS["home"], wait_until="domcontentloaded", timeout=60000)
                except Exception as e:
                    log.info("goto the front page failed: %s", e)
                    return False
                # A page loaded fresh holds nothing from before.
                _let_go(old)
                old = []
                if not _app_drawn(page, APP_DRAW_SECONDS):
                    if trace is not None and not looks_signed_out(page):
                        trace.append({"note": "the menu was never drawn", "kind": kind,
                                      "seconds": APP_DRAW_SECONDS})
                    return False
            if looks_signed_out(page):
                return False
            dismiss_overlay(page)
            label = _walk(page, kind, trace)
            count = _count_in(label)
            if label is not None and count == 0:
                # The link says the list is empty, so there is nothing to
                # wait for and nothing to refuse. A Savings account with no
                # tax forms yet is not a failure.
                if trace is not None:
                    trace.append({"note": "the list's link counted none", "kind": kind})
                return False
            if label is not None and _arrived(page, kind, None, old, count, trace):
                _ARRIVED.update(kind=kind, url=page.url or "", count=count, at=time.monotonic())
                return True
    finally:
        _let_go(old)
    if trace is not None:
        trace.append({"note": "the section was not found", "kind": kind,
                      "document_controls": _count(_doc_buttons(page))})
    return False


def _count(loc) -> int:
    try:
        return loc.count()
    except Exception:
        return -1


def goto_documents(page) -> bool:
    """A signed-in card.apple.com page that lists documents of any kind.
    The card's statements first, since every account has those."""
    global BILLING_URL
    for kind in KINDS:
        if goto_section(page, kind):
            BILLING_URL = page.url or BILLING_URL
            return True
        if looks_signed_out(page):
            return False
    return False


def scroll_full_page(page, rounds: int = 8, delay_ms: int = 600) -> None:
    try:
        for _ in range(rounds):
            page.mouse.wheel(0, 3000)
            page.wait_for_timeout(delay_ms)
        page.keyboard.press("End")
        page.wait_for_timeout(delay_ms)
    except Exception:
        pass


def expand_all(page) -> None:
    """Click 'See more' / 'Show more' / 'View older statements' repeatedly
    to surface anything the page loads on demand. The label is
    checked against the guard before every click."""
    pat = re.compile(r"^\s*(show|load|view|see)\s+(more|all|older)(\s+(statements?|documents?))?\s*$|"
                     r"^\s*(older|previous)\s+statements?\s*$", re.I)
    for _ in range(30):
        clicked = False
        for role in ("button", "link"):
            try:
                loc = page.get_by_role(role, name=pat)
                if loc.count() > 0 and loc.first.is_visible():
                    label = loc.first.inner_text(timeout=1000) or ""
                    if is_safe_control(label):
                        loc.first.click()
                        page.wait_for_timeout(1500)
                        clicked = True
                        break
            except Exception:
                continue
        if not clicked:
            break


@dataclass
class RawDoc:
    title: str
    account: str = ""
    date_text: str = ""
    href: str = ""
    text: str = ""
    row_index: int = -1
    kind: str = "doc"


# The row a document control sits in, the nearest enclosing element whose
# text carries a date, a month or a year, up to six levels up. A document
# is dated by its button's own name and never by this. The row only says
# whether a tax form is a 1099-INT, and whether a statement row speaks of
# tax, which leaves that button unread.
_ROW_OF_JS = r"""el => {
  const dateRe = /(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2},?\s+)?\d{4}|\d{1,2}\/\d{1,2}\/\d{2,4}|\d{4}-\d{2}-\d{2}|\b(19|20)\d{2}\b/i;
  let node = el, depth = 0;
  while (node && depth < 6) {
    const txt = (node.innerText || '').trim();
    if (dateRe.test(txt)) return txt.slice(0, 300);
    node = node.parentElement; depth++;
  }
  return '';
}"""


def _label_of(el) -> Optional[str]:
    """A control's label, or None when it could not be read. It used to be
    "" then, which read as no document at all (the census after CI run
    36792330947)."""
    try:
        return (el.get_attribute("aria-label") or el.inner_text(timeout=800) or "").strip()
    except Exception:
        return None


def _read_control(el, kind: str) -> Tuple[Optional[str], str, Optional[str], str]:
    """A control's label, the kind it belongs to, its date, and its row's
    text. Only a button of the recorded shape (DOC_BUTTON_RE) is given a
    date, and only from its own name, so nothing else on a list, a PDF
    link beside it or a year printed near it, can ever be read as a
    document (#52).

    Every such button on the Tax Documents list is a tax form, since Apple
    names its button the way it names a statement's, filed at the year the
    button names (tax_list_date). On a statements list it is that list's
    statement, filed at the end of the month it names. A statement row
    whose own text says tax is left undated, since it is neither. A label
    that could not be read is None, and so is the date."""
    name = _label_of(el)
    if name is None:
        return None, kind, None, ""
    row_text = ""
    try:
        row_text = el.evaluate(_ROW_OF_JS) or ""
    except Exception:
        row_text = ""
    if not DOC_BUTTON_RE.match(name):
        return name, kind, None, row_text
    if kind == TAX:
        return name, TAX, tax_list_date(name), row_text
    if TAX_WORDS_RE.search(row_text):
        return name, kind, None, row_text
    return name, kind, document_date(kind, name), row_text


def collect_download_docs(page, kind: str = CARD, trace: Optional[list] = None) -> List[RawDoc]:
    """Read every document the list on screen offers, one per recorded
    button, dated by the button's own name. One document per kind and
    date. Controls that only look like a document's are counted for the
    trace and never read."""
    docs: List[RawDoc] = []
    seen = set()
    undated = 0
    expand_all(page)
    scroll_full_page(page)
    ctrls = _doc_buttons(page)
    total = _count(ctrls)
    for i in range(max(total, 0)):
        el = ctrls.nth(i)
        name, own, iso, _row = _read_control(el, kind)
        if not is_safe_control(name):
            continue
        if not iso:
            undated += 1
            continue
        if (own, iso) in seen:
            continue
        seen.add((own, iso))
        try:
            href = el.get_attribute("href") or ""
        except Exception:
            href = ""
        title = title_for(own, iso, name + " " + _row)
        docs.append(RawDoc(title=title, date_text=iso,
                           href=href if PDF_HREF_RE.search(href or "") else "",
                           text=f"Apple Card {title}", row_index=i, kind=own))
    other = max(_count(_bill_controls(page)) - max(total, 0), 0)
    if trace is not None:
        trace.append({"note": "read a section", "kind": kind, "documents": len(docs),
                      "controls_without_one_date": undated,
                      "controls_of_another_shape": other})
    if undated:
        log.info("%d document button(s) in the %s section carried no single date, left alone",
                 undated, kind)
    if other:
        log.info("%d control(s) in the %s section only looked like a document's, left alone",
                 other, kind)
    return docs


def _dated(page, kind: str, iso: str) -> Optional[List[str]]:
    """The name of every document button on the list on screen that reads
    as the `kind` document dated `iso`, the same way discovery read it, or
    None when a button's name could not be read, since it may read as that
    document too."""
    ctrls = _doc_buttons(page)
    names = []
    unread = 0
    for i in range(max(_count(ctrls), 0)):
        name, own, got, _row = _read_control(ctrls.nth(i), kind)
        if name is None:
            unread += 1
            continue
        if own == kind and got == iso and is_safe_control(name):
            names.append(name)
    if unread:
        return None
    return names


def _exactly_named(page, name: str):
    """The control whose whole name is `name`, found by that name every
    time it is used. A click therefore lands on the button that names this
    document, even when the list gains or loses a row between reading it
    and pressing it, and fails when two controls carry that name."""
    words = (name or "").split()
    rx = re.compile(r"^\s*" + r"\s+".join(escape_for_locator(w) for w in words) + r"\s*$", re.I)
    return _controls_named(page, rx)


def _control_for(page, kind: str, iso: str):
    """The button for the `kind` document dated `iso`, matched the same way
    discovery found it, as (control, name), or (None, "") when no button or
    more than one reads as that document, since pressing one of two would
    be a guess. A button whose name could not be read could be the second,
    so then nothing is chosen either."""
    names = _dated(page, kind, iso)
    if names is None or len(names) != 1:
        return None, ""
    return _exactly_named(page, names[0]), names[0]


def _fetch_pdf(page, href: str, zip_ok: bool = False) -> Optional[bytes]:
    """A PDF link fetched from inside the signed-in page, cookies and all.
    The fetching is the core's, the hosts are this app's."""
    return _core_fetch_pdf(page, href, is_safe_url, zip_ok=zip_ok)


def _take_same_tab(page, start_url: str, out_path: Path, trace) -> bool:
    """A PDF the click opened in this very tab. The core does the reading,
    this app's guard decides which addresses it may read."""
    return _core_take_same_tab(page, start_url, out_path, trace, is_safe_url)


# GUESS. If Download asks which format, PDF is the one. CSV and OFX never
# match, and the guard refuses them besides.
_SECOND_STEP_RE = re.compile(
    r"^\s*(download|download\s+(pdf|now|file|statement|document)|save|save\s+(as\s+)?pdf|"
    r"pdf|view\s*/\s*print\s+pdf|print|open\s+pdf)\s*$", re.I)


def _second_step(page, appeared: set):
    """A control the click revealed whose text says it finishes a download,
    once it has passed the guard, or None. The choosing is the core's, the
    words this provider uses and the guard are this app's."""
    return _core_second_step(page, appeared, _SECOND_STEP_RE, is_safe_control)


# ---------------------------------------------------------------------------
# What a download may write down. download-attempt.json is a file a tester
# is asked to attach to a public issue, so what goes in it comes from a
# list of what may leave, fixed words, counts, states, the kind of an
# address and the plain words of its path, and never from the page's text
# or an address with parts scrubbed out. A clicked button's name carries a
# statement's month, and a revealed control could carry anything.
# ---------------------------------------------------------------------------
_PATH_PART_RE = re.compile(r"[a-z][a-z0-9._-]{0,40}")
_PARAM_NAME_RE = re.compile(r"[A-Za-z][A-Za-z0-9._-]{0,40}")


def _plain(part: str, rx) -> str:
    """One piece of an address or one parameter name when it is a plain
    word with at most three digits, else #."""
    ok = rx.fullmatch(part or "") and sum(ch.isdigit() for ch in part) <= 3
    return part if ok else "#"


def mask_href(url: str) -> str:
    """An address as it may leave. Whether it is card.apple.com's, the
    plain lowercase words of its path and the names of its parameters,
    never their values. Anything else in it is #, and an address on any
    other host is only "elsewhere"."""
    from urllib.parse import parse_qsl
    u = (url or "").strip()
    if not u:
        return ""
    low = u.lower()
    for scheme in ("javascript:", "blob:", "data:", "about:"):
        if low.startswith(scheme):
            return scheme[:-1]
    try:
        parts = urlsplit(u)
        keys = sorted({_plain(k, _PARAM_NAME_RE) for k, _v in parse_qsl(parts.query, keep_blank_values=True)})
    except ValueError:
        return "unreadable"
    if parts.scheme or parts.netloc:
        if not is_safe_url(u):
            return "elsewhere"
        where = "card"
    else:
        where = "relative"
    out = where + ":/" + "/".join(_plain(p, _PATH_PART_RE) for p in parts.path.split("/") if p)[:160]
    if keys:
        out += "?" + "&".join(keys[:12])
    return out


_MASKED_HREF_RE = re.compile(r"(card|relative|elsewhere|unreadable|javascript|blob|data|about)"
                             r"(:/[a-z0-9._#/-]*)?(\?[A-Za-z0-9._#&-]*)?")


def _type_word(content_type: str) -> str:
    """A response's content type as one word."""
    ct = (content_type or "").lower()
    for word in ("pdf", "json", "octet", "html"):
        if word in ct:
            return word
    return "other" if ct.strip() else ""


def _label_mask(label: str) -> str:
    """A control's name as a trace may carry it, a fixed phrase and never
    the page's own words. A document button's name is a statement's
    month, so it is only called a document button."""
    text = " ".join((label or "").split())
    if not text:
        return "nothing"
    if DOC_BUTTON_RE.match(text):
        return "a document button"
    if _SECOND_STEP_RE.match(text):
        return "a download or save control"
    return "another control"


def _click_failure(e: Exception) -> str:
    """Why a press failed, as a fixed phrase. Playwright's own message
    quotes the locator, and the locator quotes the control's name."""
    msg = str(e).lower()
    if "intercepts pointer events" in msg:
        return "something else on the page was in the way"
    if "strict mode violation" in msg:
        return "more than one control matched"
    if "not visible" in msg:
        return "it was not visible"
    if "detached" in msg or "not attached" in msg:
        return "it was no longer on the page"
    if "timeout" in msg:
        return "it timed out"
    return "another error"


# Every fixed word a trace entry here may carry as it stands. A string
# that is not one of these leaves as null, so a new note that was not
# added here loses its words rather than widening the file.
_TRACE_WORDS = frozenset(KINDS) | frozenset({
    "nav", "main",
    # notes written in this module
    "pressed a section menu entry", "the menu was never drawn", "the section was not found",
    "the list on screen was not taken", "the list's link counted none", "read a section",
    "no control carried this document's date", "more than one control carried this document's date",
    "a control's name could not be read",
    "clicked", "click failed", "clicked through the DOM instead", "DOM click failed too",
    "the press reached the page although it raised, so it was not made again",
    "after the click", "second step clicked", "second step click failed",
    "pressed again", "the second press failed",
    "the page made the document itself", "another apple host",
    "the list was opened for this document", "the list was already open",
    "the control's own link did not answer with a PDF",
    "apple named the file for another document",
    # notes the core's capture writes into the same trace
    "the tab moved",
    # _label_mask
    "nothing", "a document button", "a download or save control", "another control",
    # _click_failure
    "something else on the page was in the way", "more than one control matched",
    "it was not visible", "it was no longer on the page", "it timed out", "another error",
})


def _trace_value(key: str, value, depth: int = 0):
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int):
        return max(min(value, 10 ** 6), -1)
    if isinstance(value, float):
        return round(value, 3)
    if isinstance(value, str):
        if key == "url":
            return value if _MASKED_HREF_RE.fullmatch(value) else mask_href(value)
        if key in ("type", "content_type"):
            return _type_word(value)
        return value if value in _TRACE_WORDS else None
    if isinstance(value, (list, tuple)) and depth == 0:
        return [_trace_value(key, v, 1) for v in list(value)[:20]]
    return None


def attempt_record(trace) -> list:
    """A download's trace as download-attempt.json may carry it. Field
    names, numbers and flags as they are, an address through mask_href, a
    content type as one word, and a string only when it is one of this
    module's fixed words. The core's own entries in the same trace go
    through the same list."""
    out = []
    for entry in list(trace or [])[:80]:
        if not isinstance(entry, dict):
            continue
        rec = {}
        for key, value in list(entry.items())[:20]:
            k = re.sub(r"[^a-z0-9_]+", "_", str(key).lower())[:40]
            rec[k] = _trace_value(k, value)
        out.append(rec)
    return out


def _press_again(el, label: str, trace: Optional[list] = None) -> bool:
    """Press a document's button a second time, found again by its whole
    name, once the guard has passed that name again. False when it could
    not be pressed, and when two controls now carry the name, since
    pressing one of two would be a guess."""
    if not is_safe_control(label):
        return False
    try:
        el.scroll_into_view_if_needed(timeout=4000)
    except Exception:
        pass
    try:
        el.click(timeout=8000)
    except Exception as e:
        if trace is not None:
            trace.append({"note": "the second press failed", "control": _label_mask(label),
                          "error": _click_failure(e)})
        return False
    if trace is not None:
        trace.append({"note": "pressed again", "control": _label_mask(label)})
    return True


# RECORDED (#52). The recording saw each download arrive under Apple's file
# name with no request for it on card.apple.com, so the page builds the PDF
# itself. On 0.38.0 the tester's Chrome downloaded both August statements
# twice, its own download menu open in the address bar, while nothing
# reached the folder this app watches or its download event. So the file is
# also taken where the page hands it to the browser. URL.createObjectURL is
# wrapped to keep every PDF blob the page makes, and an anchor's click to
# keep the name Apple gives the file, and both are passed on unchanged, so
# the page and the browser do exactly what they did before. Nothing is
# pressed, blocked or suppressed. Arming it again clears what it kept, so a
# document is only ever taken from a blob made after its own press began.
_BLOB_HOOK_JS = r"""() => {
  window.__paperpullBlobs = [];
  window.__paperpullNames = [];
  if (window.__paperpullBlobHook) return true;
  window.__paperpullBlobHook = true;
  const made = URL.createObjectURL.bind(URL);
  URL.createObjectURL = function (obj) {
    const url = made(obj);
    try {
      if (obj instanceof Blob && ['application/pdf', 'application/octet-stream', ''].includes(obj.type)) {
        window.__paperpullBlobs.push({url, blob: obj});
      }
    } catch (e) {}
    return url;
  };
  const clicked = HTMLAnchorElement.prototype.click;
  HTMLAnchorElement.prototype.click = function () {
    try {
      if (this.download) window.__paperpullNames.push({href: this.href, name: String(this.download)});
    } catch (e) {}
    return clicked.apply(this, arguments);
  };
  return true;
}"""

# The newest PDF blob the page made since the hook was armed, as base64, with
# the name its anchor gave it, or empty. Anything that does not begin with
# the PDF marker, or is implausibly small or large, is passed over.
_TAKE_BLOB_JS = r"""async () => {
  const blobs = window.__paperpullBlobs || [];
  const names = window.__paperpullNames || [];
  for (let i = blobs.length - 1; i >= 0; i--) {
    const {url, blob} = blobs[i];
    if (!blob || blob.size < 100 || blob.size > 30000000) continue;
    const head = new Uint8Array(await blob.slice(0, 5).arrayBuffer());
    if (String.fromCharCode(...head) !== '%PDF-') continue;
    const buf = new Uint8Array(await blob.arrayBuffer());
    let s = '';
    for (let j = 0; j < buf.length; j += 0x8000) s += String.fromCharCode.apply(null, buf.subarray(j, j + 0x8000));
    const named = names.filter(n => n.href === url).map(n => n.name);
    return {b64: btoa(s), name: named.length ? named[named.length - 1] : '', count: blobs.length};
  }
  return {b64: '', name: '', count: blobs.length};
}"""


def _arm_blob_hook(page) -> bool:
    """Start keeping the PDF blobs the page makes, and forget any kept for
    an earlier document. False when the page could not be asked."""
    try:
        return bool(page.evaluate(_BLOB_HOOK_JS))
    except Exception:
        return False


def _take_blob(page) -> Optional[Tuple[bytes, str]]:
    """The newest PDF the page made since the hook was armed, and the name
    Apple gave it, or None."""
    try:
        got = page.evaluate(_TAKE_BLOB_JS)
    except Exception:
        return None
    if not isinstance(got, dict) or not got.get("b64"):
        return None
    import base64
    try:
        data = base64.b64decode(got["b64"])
    except Exception:
        return None
    if data[:5] != b"%PDF-":
        return None
    return data, str(got.get("name") or "")


def _is_apple_file_host(url: str) -> bool:
    """An https address on apple.com or one of its own subdomains, the only
    other place a statement's PDF may be read from as it goes past. Only
    read, never opened or asked for by this app except to fetch the very
    answer the page received."""
    try:
        parts = urlsplit(url or "")
    except ValueError:
        return False
    host = (parts.hostname or "").lower().rstrip(".")
    if parts.scheme != "https" or parts.username or parts.password:
        return False
    if parts.port not in (None, 443):
        return False
    return host == "apple.com" or host.endswith(".apple.com")


def _new_names(dl_dir, before: set) -> List[str]:
    """The finished files that appeared in the download folder since
    `before`, or were written again in place since, by name. The same files
    take_new_pdf may take, so none of them is taken before Apple's name for
    it is read (review of the download folder fix)."""
    return _folder_arrived(dl_dir, before)


def _catch_pdf(page, el, label: str, out_path: Path, trace: Optional[list] = None,
               dl_dir=None, expect: Optional[Tuple[str, str]] = None) -> bool:
    """Click `el` and save whatever PDF the site produces, a file landing
    in `dl_dir`, a download event, a PDF response, a new tab, this tab
    moving to the document, or a second control the click revealed.
    `trace` collects what happened, the click's own outcome included, in
    fixed words and counts.

    `expect` is the (kind, date) of the document asked for. When the file
    arrives with a name Apple wrote for another document, a download
    event's name or the name it was saved under in `dl_dir`, nothing is
    saved and nothing else is tried (apple_file_verdict).

    RECORDED in the first Pilot (#52, 0.37.1). The first press on a list
    the app had just opened produced nothing at all, no download, no file,
    no tab and no new control, on the card's statements and on the Savings
    statements alike, and every later press on the same list downloaded at
    once. Not a slow download either, or its file would have landed during
    a later press and been refused there for its name, and no later press
    in that run saw one. Why the page let that first press go is not
    known. So a press that produced nothing at all, on a page that
    has not moved, is made once more on the same button, found again by
    its whole name (_press_again). A file that arrives is checked against
    the document asked for the same way whichever press sent it. A second
    copy, which the browser names with " (1)", is removed from the
    download folder once the document is saved, when it is the same bytes
    (capture.clear_copies), and otherwise left there."""
    ctx = page.context
    got: dict = {}
    downloads: list = []
    # Answers to a request this press made, from its tab or one it opened,
    # that called themselves a PDF and read empty. Asked for once more only
    # when nothing else brings the document (capture.ask_again).
    empty_answers: list = []
    made_here = _RequestsSince(page, ctx.pages)
    refused: list = []
    start_url = page.url or ""

    def named_right(name: str) -> bool:
        """False once Apple's own name for the file names another document."""
        if refused:
            return False
        if expect is None:
            return True
        verdict = apple_file_verdict(expect[0], expect[1], name)
        if verdict is None or (verdict["same_kind"] and verdict["same_period"]):
            return True
        refused.append(verdict)
        if trace is not None:
            trace.append({"note": "apple named the file for another document", "kind": expect[0],
                          "named_kind": verdict["named_kind"], "same_kind": verdict["same_kind"],
                          "same_period": verdict["same_period"]})
        log.info("the file for a %s document arrived named for another document, not saved", expect[0])
        return False

    def on_download(dl):
        downloads.append(dl)

    def on_response(res):
        try:
            url = res.url or ""
            ours = is_safe_url(url)
            if not ours and not _is_apple_file_host(url):
                return
            ct = (res.headers.get("content-type") or "").lower()
            if trace is not None and ("json" in ct or "pdf" in ct or "octet" in ct or "zip" in ct):
                entry = {"status": res.status, "type": _type_word(ct), "url": mask_href(url)}
                if not ours:
                    entry["from"] = "another apple host"
                trace.append(entry)
            if not ours and "pdf" not in ct and "octet" not in ct:
                return
            if got:
                return
            if "pdf" in ct or "octet" in ct:
                try:
                    body = res.body()
                except Exception:
                    body = b""
                    got["refetch"] = url
                if body[:5] == b"%PDF-":
                    got["body"] = body
                elif not body and not got and made_here.made(res.request) \
                        and (res.request.method, url) not in empty_answers:
                    # A PDF the page reads into a blob leaves its answer
                    # empty under Playwright 1.63 (capture.ask_again).
                    empty_answers.append((res.request.method, url))
        except Exception:
            pass

    ctx.on("response", on_response)
    page.on("download", on_download)
    before = set(ctx.pages)
    seen = _snapshot(dl_dir)
    controls_before = _control_texts(page)
    hooked = _arm_blob_hook(page)

    def landed() -> bool:
        if refused:
            return False
        if downloads:
            try:
                suggested = downloads[0].suggested_filename or ""
            except Exception:
                suggested = ""
            if not named_right(suggested):
                return False
            # Pointed at a folder, the browser can save the only copy there
            # and leave the event's own file empty, so that file is taken
            # rather than the document asked for a second time.
            if _take_download(downloads[0], dl_dir, seen, out_path, zip_ok=True):
                return True
        if got.get("body"):
            out_path.write_bytes(got["body"])
            return True
        if got.get("refetch"):
            try:
                # This address answered the press directly, so asking it
                # again needs no redirect, and one would take the
                # browser's cookies wherever it led.
                resp = page.context.request.get(got.pop("refetch"), max_redirects=0,
                                                timeout=60000)
                body = resp.body() if resp.ok else b""
                if _is_document(body, zip_ok=True):
                    out_path.write_bytes(body)
                    return True
            except Exception:
                pass
        # The PDF the page built itself, whatever the browser then did with
        # its download (_BLOB_HOOK_JS). Checked against Apple's name for it
        # the same way as every other arrival.
        made = _take_blob(page) if hooked else None
        if made:
            data, name = made
            if name and not named_right(name):
                return False
            out_path.write_bytes(data)
            if trace is not None:
                trace.append({"note": "the page made the document itself", "named": bool(name)})
            return True
        # A real Edge or Chrome saves the file itself, under Apple's name.
        for name in _new_names(dl_dir, seen):
            if not named_right(name):
                return False
        return _take_new_pdf(dl_dir, seen, out_path, zip_ok=True)

    def wait_for_pdf(seconds: int) -> bool:
        for _ in range(seconds):
            if landed():
                return True
            if refused:
                return False
            page.wait_for_timeout(1000)
        return landed()

    try:
        try:
            el.scroll_into_view_if_needed(timeout=4000)
        except Exception:
            pass
        # Playwright's own press, and through the page only when nothing
        # covered the control, its press never reached the page and nothing
        # it should bring came. What cannot be told stops the run, and the
        # control is never pressed twice (pressing.press_once).
        outcome = pressing.press_once(
            page, el, what="the control for this statement", words=_words(),
            guard=is_safe_control, dl_dir=dl_dir,
            brought=lambda: bool(downloads or got or refused or (_control_texts(page) - controls_before)))
        if trace is not None:
            if outcome.error is None:
                trace.append({"note": "clicked", "control": _label_mask(label)})
            else:
                trace.append({"note": "click failed", "control": _label_mask(label),
                              "error": _click_failure(outcome.error)})
            if outcome.how == pressing.MADE:
                trace.append({"note": "the press reached the page although it raised, "
                                      "so it was not made again", "control": _label_mask(label)})
            elif outcome.how == pressing.THROUGH_THE_PAGE and outcome.page_error is None:
                trace.append({"note": "clicked through the DOM instead", "control": _label_mask(label)})
            elif outcome.how == pressing.THROUGH_THE_PAGE:
                trace.append({"note": "DOM click failed too", "error": _click_failure(outcome.page_error)})
        if wait_for_pdf(PRESS_WAIT_SECONDS):
            return True
        if refused:
            return False
        if _take_same_tab(page, start_url, out_path, trace):
            return True
        if _take_new_tab(page, [p for p in ctx.pages if p not in before], out_path):
            return True
        appeared = _control_texts(page) - controls_before
        if trace is not None:
            trace.append({"note": "after the click", "url": mask_href(page.url or ""),
                          "appeared": [_label_mask(t) for t in sorted(appeared)[:15]],
                          "new_tabs": len([p for p in ctx.pages if p not in before])})
        step, step_label = _second_step(page, appeared)
        if step is not None:
            try:
                step.click(timeout=8000)
                if trace is not None:
                    trace.append({"note": "second step clicked", "control": _label_mask(step_label)})
            except Exception as e:
                if trace is not None:
                    trace.append({"note": "second step click failed", "control": _label_mask(step_label),
                                  "error": _click_failure(e)})
            if wait_for_pdf(20):
                return True
            if refused:
                return False
            if _take_same_tab(page, start_url, out_path, trace) or \
                    _take_new_tab(page, [p for p in ctx.pages if p not in before], out_path):
                return True
        elif not appeared and (page.url or "") == start_url and outcome.how == pressing.PRESSED \
                and _press_again(el, label, trace):
            if wait_for_pdf(AGAIN_WAIT_SECONDS):
                return True
            if refused:
                return False
            if _take_new_tab(page, [p for p in ctx.pages if p not in before], out_path):
                return True
        if wait_for_pdf(LAST_WAIT_SECONDS):
            return True
        if refused:
            return False
        if _take_new_tab(page, [p for p in ctx.pages if p not in before], out_path):
            return True
        # Looked at once more, so a file that arrived meanwhile is checked by
        # the name Apple gave it first. Then, when nothing else brought it and
        # nothing was refused, the one answer that read empty is asked for
        # once more, on the hosts an answer is read from (capture.ask_again).
        if landed():
            return True
        if refused:
            return False
        if _ask_again(page, empty_answers, out_path,
                      lambda u: is_safe_url(u) or _is_apple_file_host(u), zip_ok=True):
            return True
        log.info("click on %r produced no PDF", label)
        return False
    finally:
        made_here.stop()
        try:
            ctx.remove_listener("response", on_response)
        except Exception:
            pass
        try:
            page.remove_listener("download", on_download)
        except Exception:
            pass
        for extra in [p for p in ctx.pages if p not in before]:
            try:
                extra.close()
            except Exception:
                pass
        # What the browser saved into the folder while the document came
        # some other way, read off the answer or asked for again, goes when
        # it is an exact copy of the one saved (capture.clear_copies).
        try:
            _clear_copies(dl_dir, seen, out_path)
        except Exception:
            pass


def download_bill(page, dl_dir, iso_date: str, out_path, title: str = "",
                  trace: Optional[list] = None) -> bool:
    """Save the document dated `iso_date` of the kind its title names. The
    section is opened, and a PDF link on the row is fetched from inside
    the page. Otherwise the row's own control is pressed, after the guard
    has passed it, once more only when the first press produced nothing at
    all (_catch_pdf), and whichever the site produces is caught, a
    download event or a PDF response, in this tab or one it opens.

    `dl_dir` is where the attached browser saves a download, watched
    after every click."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    kind = kind_of_title(title)
    was_taken = _ARRIVED.get("at")
    if not goto_section(page, kind, trace):
        log.info("could not open the %s section for %s", kind, iso_date)
        return False
    taken = _ARRIVED.get("at")
    expand_all(page)

    el, label = _control_for(page, kind, iso_date)
    if el is None:
        dated = _dated(page, kind, iso_date)
        same = len(dated or [])
        log.info("%d %s document buttons read as %s, none pressed", same, kind, iso_date)
        if trace is not None:
            trace.append({"note": ("a control's name could not be read" if dated is None else
                                   "more than one control carried this document's date" if same
                                   else "no control carried this document's date"),
                          "kind": kind, "document_controls": _count(_doc_buttons(page)),
                          "with_this_date": same})
        return False
    if not is_safe_control(label):
        log.info("refusing unsafe control %r for %s", label, iso_date)
        return False

    try:
        href = el.get_attribute("href") or ""
    except Exception:
        href = ""
    if href and not href.lower().startswith(("javascript", "#")):
        from urllib.parse import urljoin
        target = urljoin(page.url, href)
        # A link on the provider's own hosts is fetched through the session
        # first. A PDF answer is the document. Anything else means the link
        # is a page or a handoff, and the click below follows it.
        if is_safe_url(target):
            body = _fetch_pdf(page, target, zip_ok=True)
            if body:
                out_path.write_bytes(body)
                return True
            if trace is not None:
                trace.append({"note": "the control's own link did not answer with a PDF",
                              "url": mask_href(target)})
    # Whether this press is the first on a list just opened, and how long
    # the list has been on screen, the two things that set apart the
    # presses that failed in the first Pilot (#52).
    if trace is not None and taken is not None:
        trace.append({"note": ("the list was already open" if taken == was_taken
                               else "the list was opened for this document"),
                      "kind": kind, "seconds_open": int(time.monotonic() - taken)})
    return _catch_pdf(page, el, label, out_path, trace, dl_dir, expect=(kind, iso_date))


# ---------------------------------------------------------------------------
# Diagnose. A survey a tester can attach to an issue. No screenshot, since a
# signed-in page shows names, numbers and amounts. Digit runs are masked and
# JSON bodies are recorded as shape only.
# ---------------------------------------------------------------------------
_ROW_JS = r"""() => {
  const out = [];
  for (const tr of document.querySelectorAll('table tr, [role=row], [role=listitem], li')) {
    const txt = (tr.innerText || '').trim();
    if (!txt) continue;
    const link = tr.querySelector("a[href]");
    out.push({text: txt.slice(0, 200), href: link ? link.getAttribute('href') : ''});
  }
  return out.slice(0, 200);
}"""

SURVEY_LINK_RE = re.compile(
    r"^\s*((see|view|show)\s+)?(statements?|savings(\s+account)?|documents?|"
    r"tax\s+(documents?|forms?)|savings\s+statements?)\s*$", re.I)


def collect_documents(page) -> List[RawDoc]:
    """Loose row scrape used only by --diagnose. Every row that carries a
    date, a link or the word download, with digits masked."""
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
    # A row with a date is a document row, and those are what a repair
    # wants to see first, ahead of a nav full of links.
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
    out["sections"] = {k: _looks_like(page, k) for k in KINDS}
    return out


def _front_page_again(page) -> bool:
    """The front page, loaded fresh, with its menu waited for. This is the
    survey's way back after following a link. Going back in the tab's
    history does not work here, because the page replaces its own history
    entry when a section is opened, so going back leaves card.apple.com
    for whatever the tab held before it. In the first Diagnose (#52) that
    was a section address that answers 404, and the rows read after the
    survey were read off that 404 page."""
    try:
        page.goto(URLS["home"], wait_until="domcontentloaded", timeout=60000)
    except Exception as e:
        log.info("goto the front page failed: %s", e)
        return False
    return _app_drawn(page, APP_DRAW_SECONDS)


def survey(page, dwell_ms: int = 4000, max_follow: int = 6) -> dict:
    """What the signed-in card, Savings and tax pages look like, without
    downloading anything. Records each page, its headings and controls with
    the guard's verdict on each, which section each page was taken for, and
    every JSON or PDF response card.apple.com sends while the page settles.
    Then follows, one at a time, the few links whose text is a section
    name, and after one that moved the page loads the front page again
    rather than going back (_front_page_again). No screenshot."""
    seen: list = []

    def on_response(res):
        try:
            url = res.url or ""
            if not is_safe_url(url):
                return
            ct = (res.headers.get("content-type") or "").lower()
            if "json" not in ct and "pdf" not in ct:
                return
            entry = {"url": redact(url)[:200], "status": res.status, "type": ct[:40]}
            try:
                entry["method"] = res.request.method
                body = res.request.post_data or ""
                if body.lstrip().startswith("{"):
                    import json as _json
                    parsed = _json.loads(body)
                    if isinstance(parsed, dict):
                        entry["post_keys"] = sorted(str(k) for k in parsed)[:30]
            except Exception:
                pass
            q = _safe_query(url)
            if q:
                entry["query"] = q[:240]
            if "json" in ct:
                try:
                    entry["shape"] = _shape(res.json())
                except Exception:
                    entry["shape"] = "unreadable"
            seen.append(entry)
        except Exception:
            pass

    # The survey presses menu links of its own, so whichever list this app
    # last opened is no longer known to be the one on screen.
    _ARRIVED.clear()
    page.on("response", on_response)
    report = {"pages": [], "responses": seen}
    try:
        page.wait_for_timeout(dwell_ms)
        start = _page_summary(page)
        report["pages"].append(start)
        followed = 0
        for c in start["controls"]:
            if followed >= max_follow or c["role"] not in ("link", "button", "tab") or not c["survey"]:
                continue
            if not is_safe_control(c["text"]):
                continue
            try:
                link = page.get_by_role(c["role"], name=re.compile(
                    "^" + escape_for_locator(c["text"].replace("#", "")) + "$", re.I)).first
                if link.count() == 0:
                    continue
                before = page.url
                tabs_before = set(page.context.pages)
                link.click(timeout=5000)
                page.wait_for_timeout(dwell_ms)
                # A control that opened a new tab is surveyed there, then the
                # tab is closed. Off Apple Card's host it is still recorded,
                # marked, and nothing on it is followed.
                for extra in [p for p in page.context.pages if p not in tabs_before]:
                    try:
                        extra.wait_for_load_state("domcontentloaded", timeout=15000)
                        tab = _page_summary(extra)
                        tab["opened_tab_from"] = c["text"]
                        tab["off_host"] = not is_safe_url(extra.url or "")
                        report["pages"].append(tab)
                    except Exception as e:
                        report.setdefault("notes", []).append(
                            "could not read the tab %r opened: %s" % (c["text"], str(e)[:120]))
                    try:
                        extra.close()
                    except Exception:
                        pass
                if not is_safe_url(page.url or ""):
                    _front_page_again(page)
                    continue
                summary = _page_summary(page)
                summary["followed_from"] = c["text"]
                report["pages"].append(summary)
                followed += 1
                if page.url != before:
                    _front_page_again(page)
            except Exception as e:
                report.setdefault("notes", []).append(
                    "could not follow %r: %s" % (c["text"], str(e)[:120]))
    finally:
        try:
            page.remove_listener("response", on_response)
        except Exception:
            pass
    return report


# ---------------------------------------------------------------------------
# Host allowlist. Parsed, never a string prefix, so a lookalike host cannot
# walk through.
#
# card.apple.com is known, the requester signs in there (#52). It is the
# only host here, and deliberately not apple.com as a whole, since that
# would take in the Apple Store, where a control can buy something.
# Whether a statement PDF is served from card.apple.com itself or from a
# separate file host is not known. None is guessed at. If the recording
# shows the PDF arriving from another Apple host, that one host is added
# here and nothing wider.
# ---------------------------------------------------------------------------
ALLOWED_HOSTS = {"card.apple.com"}


def is_safe_url(url: str) -> bool:
    """True only for an https URL on one of this provider's own hosts.

    The check itself lives in the core, so all of them answer the same way.
    This app keeps the hosts, which is the part that really is its own."""
    return _host_allows(url, ALLOWED_HOSTS)
