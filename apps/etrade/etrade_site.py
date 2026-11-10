"""ALL etrade.com selectors, URLs, and page behavior live here.

When E*TRADE changes its site, repair this file only.

STATUS: CONFIRMED on the tester's account (#36). A Pilot and then a full
run saved every statement, since 0.39.0 reads each PDF out of the site's
own JSON answer. Written without an E*TRADE account and repaired from the
surveys, failure files and download attempts one tester sent. No tax form
has been seen, since his account has none. On a first run it is
deliberately cautious.

  * --login opens a real Edge or Chrome, since etrade.com runs bot protection that is happiest in a real browser.
  * --diagnose surveys whatever the documents page turns out to be,
    records its headings, its controls with the guard's verdict on each,
    and the shape of every JSON response, with digit runs masked, and
    takes no screenshot. That file is what a tester attaches to the
    GitHub issue.
  * --discover reads dates from any control that looks like a
    statement, trade confirmation or tax form, wherever it sits on the page.
  * --pilot tries to save the newest few, by fetching a PDF link the row
    carries from inside the page, or by clicking the row's own control
    and catching a download event, a PDF response or a new tab.

The guesses that most need confirming from a survey are marked GUESS.
The routes are the biggest one.

Round four, from the third survey. Discovery found nothing although the
page listed one statement in its default ninety days, so the searchItems
answer was caught and its documentDate was not read. The date is now read
in every form E*TRADE could send it, an ISO date, an ISO date-time, or an
epoch in seconds or milliseconds, and the survey records the exact shape
of the dates it saw, digits masked. The period picker offers the years
back to 2019 and nothing wider, the tester's screenshot showed, so when
no "all" or "last N years" period exists the app chooses each year in
turn, applies it, and gathers every list. One filter click per year, the
only clicks outside a document row.

Round five, from the fourth survey and its download trace. The dates are
ISO date-times and read fine now, discovery found the statement, and the
download wrote an empty trace, which means the document's row was never
found, the list's rows are not role=row elements with a link in them.
The row is now found by walking the page for the element whose own text
is the document's date, taking the row around it, and its outline goes
in the trace. Then every way a row can hand over a PDF is tried in turn,
the title's own element, any anchor or button in the row, and the row's
checkbox with the page's Download button, each through the catch that
watches for a download, a PDF answer or a new tab, and every request the
click causes is written to the trace so the next look sees the address
the page uses.

From the tester's recording on 0.33.0. The picker is a button named
"Timeframe ,  Last 90 Days", and the app looked for one named exactly
"Last 90 Days", so no period was ever chosen and discovery always read
the default ninety days. Apply runs the search inside the page, no
navigation, and a fresh searchItems answer arrives. The picker is now
found by its label and its period, "Year To Date" and every year are
applied in turn, and Discover writes discovery-trace.json saying what
the picker offered, what was chosen, whether Apply navigated, the rows
before and after and the dates each period brought.

From the tester's 0.37.0 Pilot. Discovery found thirteen documents and
none downloaded. Each Apply replaces the list, so after discovery walked
every year the page showed only the oldest, which was empty, and the
download walked every period again before its first document and ended
on an empty year once more. Every row lookup ran against an empty list.
The download now chooses the one period that lists its document, the
year of its date or "Year To Date" for a newer one.

That puts the download on lists of two to six documents for the first
time, and his thirteen documents sit on eleven dates, so two dates carry
two documents each. The row lookup took the first row with the date, and
review showed it saving the other document's PDF under this one's name.
Every way of finding the row now looks at every row with the date and
takes the one that names the document. A name is an element's whole
words or its label, the title, the title then PDF, or the title then PDF
for an account, the way his recording named the link, and never its own
text nodes with a child adding more. When none names it, a row is taken by its date alone
only if the lists the page loaded held one document on that date, and
that document is this one. Otherwise it refuses and says why, in counts.
Of what a row offers, its box aside, no step presses an element for the
document when something else pressable sits inside it, since a cell
around this document's link can also hold the other document's link or
an insert, and a press on its middle lands on whatever is there. And
anything inside a link or a button is judged as that link or button,
since a press on it presses them too. A control whose words mark it as an
insert is never tried. Inside the chosen row, only this document's own
name is pressed unless the row holds this document and no other, since a
View or a box in a row that also holds the other document of the date
could be that one's. Even then, a control that does not name the
document and says something other than View or Download is pressed only
in a row whose words nowhere carry the title and that holds no View or
Download, when it is the only one, since otherwise it names a notice or
some other thing. Every control in the row counts for that, buttons,
input buttons, pointers and elements made clickable as well as links.
Every step follows that rule, the steps that take a row's link and the
only control of a date included, and a control found before the row walk
has to sit in one row. Every word an element carries passes the guard
before it is pressed, and what is pressed has to look like a document
action. Each element is held from the check to the press. The page's
Download button is pressed only through the row's box, never as a
document's own control, only when it sits outside every document row,
this row's own box reads ticked and it is the only box ticked on the
page, and a box the app ticked is cleared again. A PDF the site sends as
an answer is taken only when its request, or the request a redirect came
from, was made during this document's attempt. A download event or a
file landing in the download folder is not yet tied to the click that
way. What the download writes for a tester to attach is built from fixed
words, counts, dates and words from fixed lists, never the page's own
text.

Review of that repair found four more ways, each reproduced in a real
browser. The only control of a date was taken on the lists' count alone,
before the row walk looked, and a "Privacy Notice PDF" link beside the
statement was saved as the statement. The row walk read the title as
printed only when an element's whole words were the title, so a row
printing it inside longer words had its lone notice pressed. A container
whose cursor says it is clickable was pressed on its middle over an
insert's View. A filter chip printing the date counted as a row of that
date, so a row carrying both documents passed for one holding this
document alone. Testing the repair found one more, a span inside a link
labeled as an insert pressed on the span's own words. Each is closed by
the rules above, and only rows that look like a document's own now
count.

A second review found three more. The row link step judged a row by its
links alone, so beside a View drawn as a button a lone notice link passed
for the document's own. A link whose own text was the title, with
"Privacy Notice" in a span inside it, counted as the name. The page's
bulk Download was taken as the one control of the date, the whole page
being the nearest element around it that printed a date. And smaller
ones, another row's Download taken for the page's, a control found again
by its place when pressed, a redirect of an earlier request taken for
this one's answer, nothing refusing a control that signs out, and page
digits and parameter names leaving in the traces by their shape. The
rules above close them.

From a tester's live page after 0.56.2 (#96), read for labels and shapes
only. displayMultipleAccounts is empty on every document, so no account
was ever read. Each document carries keyAccountNo, and the page's account
list, usermetadata, gives each key the label its Account column shows, so
discovery catches that answer as it catches searchItems and gives each
document its label (_note_accounts). The list's pagination holds a Next
page button, turned off on the last page, which the download presses to
reach a document listed past the first page (_page_with).

SAFETY (this is a brokerage account that can trade and move money):
  This module is strictly READ-ONLY. It opens the documents area, reads
  the list, and saves the PDFs E*TRADE already generated. It must NEVER
  activate any control that trades, buys, sells, places or cancels an
  order, exercises an option, transfers, wires, deposits, withdraws,
  takes a distribution, or edits any setting.
  FORBIDDEN_CONTROL_RE is the guard, with the core's settings and sign-in
  words and SESSION_CONTROL_RE beside it. A control must ALSO look like a
  document action (SAFE_DOC_CONTROL_RE) before it may be clicked, the
  row's box aside. There is no code here that submits a form or confirms
  a dialog.
"""
from __future__ import annotations

import json
import logging
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import urlsplit

from paperpull_core import intake
from paperpull_core.controls import SETTINGS_CONTROL_RE, AUTH_CONTROL_RE
from paperpull_core.controls import dismiss_overlays as _dismiss_overlays

# Everything on its way into a diagnostic file goes through here. It
# lives in core because seventeen apps each had their own copy and
# they drifted into three different versions.
from paperpull_core.redact import redact, set_private_words  # noqa: F401
from paperpull_core.urls import is_safe_url as _host_allows
from paperpull_core.api_census import shape_of as _shape
from paperpull_core.api_census import kind_of as _kind_of
from paperpull_core.dates import last_day as _last_day
from paperpull_core.dates import human_date as _human_date
# re-exported: this app's docs module calls it as site.set_download_dir
from paperpull_core.capture import set_download_dir  # noqa: F401
from paperpull_core.capture import snapshot as _snapshot
from paperpull_core.capture import take_download as _take_download
from paperpull_core.capture import is_document as _is_document
from paperpull_core.capture import clear_copies as _clear_copies
from paperpull_core.capture import ask_again as _ask_again
from paperpull_core.capture import RequestsSince as _RequestsSince
from paperpull_core.capture import take_new_pdf as _take_new_pdf
from paperpull_core.capture import fetch_pdf as _core_fetch_pdf
from paperpull_core.capture import take_new_tab as _core_take_new_tab
from paperpull_core.capture import take_same_tab as _core_take_same_tab
from paperpull_core.controls import control_texts as _control_texts
from paperpull_core.controls import place_of as _place_of
from paperpull_core.controls import second_step as _core_second_step
from paperpull_core.controls import controls_named as _controls_named
from paperpull_core.controls import escape_for_locator
from paperpull_core.dates import checked as _checked_date
from paperpull_core.dates import full_year as _full_year
from paperpull_core import pressing
from paperpull_core.words import Fixed
from paperpull_core.words import words_for as _words_for
from paperpull_core.characters import whole_json

log = logging.getLogger("etrade_docs.site")


def _words():
    """This app's own words for paperpull_core.words, from what its source
    calls it, for saying what covered a control."""
    return _words_for("ETRADE", sys.modules[__name__])


BASE = "https://us.etrade.com"
# From the first survey (#36, 2026-09-20). The Documents page is
# /etx/pxy/accountdocs, a list with a type filter (Statements and three
# more), a date filter that defaults to the last 90 days, a Download
# button and pagination. It is fed by an API on ext-web.etrade.com,
# usermetadata (the accounts and the filter vocabulary) and
# v2/searchItems (the documents, each with a guid, an id, a type, a
# title, a date and its account). The Tax Center is /etx/pxy/tax-center.
# Discovery reads the searchItems answer as the page loads it.
BILLING_CANDIDATES = [
    f"{BASE}/etx/pxy/accountdocs",
    f"{BASE}/etx/pxy/tax-center",
    f"{BASE}/etx/hw/v2/accountshome",
]
DOCS_API_RE = re.compile(r"/etaz/api/adsal/accountdocs/v2/searchItems", re.I)
# The usermetadata answer carries the account list, each with a keyAccount
# that matches keyAccountNo in searchItems and an accountDisplayValue that
# is the human-readable label shown in the Account column (#96).
METADATA_API_RE = re.compile(r"/etaz/api/adsal/accountdocs/usermetadata", re.I)
DOCS_URL = f"{BASE}/etx/pxy/accountdocs#/documents"
# The date filter (second survey, #36) is a button reading its current
# choice, "Last 90 Days", that opens a list of periods. These and the
# list's own Next page button (_next_page) are the only controls outside a
# document row the app touches, and each of these has to read as a period
# and nothing else. The widest period wins. A period is a
# word from this list, and its numbers are a year 19xx or 20xx or a count
# of at most three digits. Any four digits used to pass, so an account's
# last four printed alone on the page read as a period and left in
# discovery-trace.json (#36, review).
DATE_FILTER_RE = re.compile(r"^\s*(last\s+\d{1,3}\s+(days|months|years?)|year\s+to\s+date|ytd|"
                            r"all(\s+(time|documents|dates))?|custom(\s+range)?|(19|20)\d{2})\s*$", re.I)
# Periods wider than a single year, then the narrow ones kept for a picker
# that offers neither those nor years. Years sit between the two, because
# "Year To Date" plus every year reaches further back than any of the
# narrow ones. The old order took "Year To Date" over the years it sat
# beside, and would have stopped discovery at January (#36).
_WIDE_FIRST = [r"^all", r"last\s+(5|7|10)\s+years", r"last\s+\d+\s+years?", r"last\s+(24|36)\s+months"]
_NARROW_LAST = [r"last\s+12\s+months", r"year\s+to\s+date|ytd", r"last\s+\d+\s+months"]
_WIDEST = _WIDE_FIRST + _NARROW_LAST
# The picker's accessible name carries its own label as well as the
# period. The tester's recording named it "Timeframe ,  Last 90 Days"
# (#36), and the finder looked for a button named exactly "Last 90 Days",
# found none, and so no period was ever chosen in any round. The label
# words and their commas are taken off before the period is judged.
_PICKER_LABEL_RE = re.compile(r"\btime\s*frame\b|\bdate\s+range\b|\bperiod\b|[,:]", re.I)
PICKER_NAME_RE = re.compile(r"time\s*frame|last\s+\d+\s+(days|months|years?)|year\s+to\s+date|"
                            r"\b(19|20)\d{2}\b", re.I)
# Apply is on the guard's list, since on most pages it commits something.
# Here it is pressed only when its whole label is Apply, only right after
# a period was chosen, and it only runs the search the period asks for.
PERIOD_APPLY_RE = re.compile(r"^\s*apply(\s+filters?)?\s*$", re.I)
BILLING_URL = BILLING_CANDIDATES[0]
URLS = {
    "home": f"{BASE}/etx/pxy/dashboard",
    "login": BILLING_URL,
    "documents": BILLING_URL,
    "statements": BILLING_URL,
}

LOGIN_URL_MARKERS = ["/login", "/signin", "/sign-in", "/auth/", "/mfa",
                     "/verification", "/challenge", "/authenticate"]

# ---------------------------------------------------------------------------
# HARD SAFETY GUARD. Tuned for brokerage, on top of the bank words. Never move
# money, never change service or coverage, never change a setting.
# ---------------------------------------------------------------------------
FORBIDDEN_CONTROL_RE = re.compile(
    r"(transfer|zelle|\bwire\b|\bpay\b|payment|bill\s*pay|autopay|auto\s*pay|"
    r"deposit|withdraw|send\s+money|request\s+money|move\s+money|"
    r"\bapply\b|open\s+(an?\s+)?account|close\s+account|\bloan\b|\bborrow|"
    r"\bcard\b|\bcards\b|replace|activate|lock|unlock|\bpin\b|limit|"
    r"overdraft|alerts?\b|\bbudget|\bgoal|\brewards?\b|\boffers?\b|"
    r"enroll|unenroll|sign\s+up|paperless|delivery\s+preference|"
    r"enable|disable|change\b|edit\b|update\b|modify|manage\b|"
    r"set\s+up|delete|remove|cancel|dispute|"
    r"password|passcode|username|profile\b|settings|preferences|contact\s+info|\baddress\b|"
    r"confirm\b|submit|agree|accept|authorize|\bchat\b|contact\s+us|"
    r"beneficiar|nickname|order\s+checks|stop\s+payment|"
    r"\btrade\b(?!\s+confirm)|trading|\bbuy\b|\bsell\b|\border\b|\boptions?\b|margin|exercise|rollover|roll\s+over|distribution|contribut|\bwire\b|link\s+(a\s+)?bank|move\s+money|convert|exchange\b|\bfund\b|invest\b)", re.I)

# Controls that end the session. The core's sign-in words cover signing in,
# on and up, and nothing covered signing out, so a row control reading
# "Sign out" or "Log off" could pass for a document's own link under
# another name (#36, review). Every press is judged against these too.
SESSION_CONTROL_RE = re.compile(r"\b(sign|log)[\s_-]?(out|off)\b", re.I)

SAFE_DOC_CONTROL_RE = re.compile(
    r"(download|view|open|print|\bpdf\b|statement|document|\bletter\b|notice|"
    r"1099|1098|5498|tax\s+(form|document)|history|"
    r"trade\s+confirmations?|confirmations?\b|tax\s+center|see\s+(more|all|older)|show\s+(more|all|older)|load\s+more)", re.I)

# A control that fetches one document. GUESS at the wording, wide on
# purpose. "View", "Download", "View PDF", "Statement", "1099-INT".
BILL_CONTROL_RE = re.compile(
    r"((download|view|print|open|get)\s*(my\s+|the\s+|this\s+|your\s+)?(statement|document|pdf|tax|letter|notice|1099|1098)|"
    r"(statement|document|tax\s+form|1099|1098|5498)\s*\(?\s*pdf\s*\)?|\bpdf\b|"
    r"^\s*(view|download|open)\s*$)", re.I)

# A link that points straight at a PDF, from a row's href.
PDF_HREF_RE = re.compile(r"\.pdf(\?|$)|/pdf\b|format=pdf|statement.*download|download.*statement|docId|documentId", re.I)

SECURITY_CHALLENGE_MARKERS = [
    "enter the code", "verification code", "6-digit", "two-factor",
    "two-step", "authenticator", "confirm your identity", "verify your identity",
    "we sent a code", "device approval", "approve this login", "unusual",
    "are you a robot", "captcha", "let's verify", "check your email",
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
    "doc_row": ("table tbody tr, [role='row'], [class*='statement'], [class*='Statement'], "
                "li[class*='document'], [class*='document']"),
    "doc_link": "a[href*='.pdf'], a[download], button[class*='download']",
    "download_control": "a[download], a[href$='.pdf'], button:has-text('Download')",
    "page_ready": "table, [role='row'], [class*='statement'], main, [role='main']",
    "next_page":("a[aria-label*='Next' i], button[aria-label*='Next' i], "
                  "[class*='next']"),
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
    """"STATEMENT", "LAST_90_DAYS", not an id, a token or a number."""
    return bool(_WORD_VALUE_RE.match(v)) and sum(ch.isdigit() for ch in v) <= 3


def _safe_query(url: str) -> str:
    """A URL's query parameters, names always, values only when they are
    plain words ("docType=STATEMENT", "range=LAST_90_DAYS"). A value with
    a digit, a token, an id, anything long, is "...". This is what a
    repair needs to make the same call with a wider filter, and nothing
    else."""
    from urllib.parse import urlsplit, parse_qsl
    try:
        pairs = parse_qsl(urlsplit(url).query, keep_blank_values=True)
    except ValueError:
        return ""
    out = []
    for k, v in pairs[:20]:
        out.append("%s=%s" % (k[:30], v if _plain_word(v) else "..."))
    return "&".join(out)

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
    if FORBIDDEN_CONTROL_RE.search(name) or SESSION_CONTROL_RE.search(name):
        return False
    if SETTINGS_CONTROL_RE.search(name) or AUTH_CONTROL_RE.search(name):
        return False
    return bool(SAFE_DOC_CONTROL_RE.search(name))


# ---------------------------------------------------------------------------
# Downloads from a real Edge or Chrome attached over CDP. The browser saves
# the file itself, into its own Downloads folder, and Playwright's download
# event never fires. So the browser is pointed at a folder of ours and that
# folder is watched after every click. The Verizon app found this first.
# AT&T's fourth round found it again, with a trace that showed a clean
# click and nothing arriving.
# ---------------------------------------------------------------------------


def _take_new_tab(page, new_pages, out_path: Path) -> bool:
    """A PDF a click opened in a new tab. The core does the reading, this
    app's guard decides which addresses it may read."""
    return _core_take_new_tab(page, new_pages, out_path, is_safe_url)


# ---------------------------------------------------------------------------
# Billing page
# ---------------------------------------------------------------------------

def dismiss_overlay(page) -> None:
    """Put away a cookie banner, a survey prompt or a notice overlay, the
    things that sit over signed-in pages and intercept clicks. Escape
    first, then only a button whose every label says close, dismiss, no
    thanks or not now and nothing else, never accept, and never what
    closes an account or signs out (controls.dismiss_overlays)."""
    _dismiss_overlays(page, FORBIDDEN_CONTROL_RE)


def _bill_controls(page):
    """Every control on the page whose name says it fetches a document.
    The words are this provider's, the rest is the core's."""
    return _controls_named(page, BILL_CONTROL_RE)


def _looks_like_billing(page) -> bool:
    try:
        if _bill_controls(page).count() > 0:
            return True
    except Exception:
        pass
    try:
        body = page.locator("body").inner_text(timeout=5000)
    except Exception:
        return False
    return bool(re.search(r"statements?\s+(and|&)\s+documents|statement\s+(period|date)|tax\s+(documents|forms|center)|trade\s+confirmations?",
                          body, re.I))


def goto_documents(page) -> bool:
    """Open Statements & Documents. The first candidate that is not a
    sign-in page and shows something statement-shaped wins, and the URL it
    lands on is remembered so a later call does not walk the list again."""
    global BILLING_URL
    dismiss_overlay(page)
    if is_safe_url(page.url or "") and not looks_signed_out(page) and _looks_like_billing(page):
        return True
    for url in [BILLING_URL] + [u for u in BILLING_CANDIDATES if u != BILLING_URL]:
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(5000)
        except Exception as e:
            log.info("goto %s failed: %s", url, e)
            continue
        dismiss_overlay(page)
        if looks_signed_out(page):
            return False
        if _looks_like_billing(page):
            BILLING_URL = url
            return True
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
    pat = re.compile(r"^\s*(show|load|view|see)\s+(more|all|older)(\s+(bills?|statements?|documents?))?\s*$|"
                     r"^\s*(older|previous)\s+(bills?|statements?)\s*$", re.I)
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
    # The account the list's Account column shows for the document, kept
    # whole, since it is what tells one account's statement from another's
    # (#96). It never goes into a trace or a log.
    account: str = ""
    date_text: str = ""
    href: str = ""
    text: str = ""
    row_index: int = -1
    kind: str = "doc"
    # The list's own ids for the document, "<documentGuid>|<documentId>".
    # They change every time the list loads, so they never key anything.
    guid: str = ""
    # What tells a document from another of the same date, title and
    # account, the list giving it none or the same one, the entry's place
    # among them, "#1", "#2", and "" for every other document, so their keys
    # stay what they were (#96).
    entry: str = ""
    # The document carries a key for its account that the page's account
    # list gave no label, so its account is not known (_account_of).
    unnamed: bool = False


# The date a bill control belongs to. The control's own name first, then
# the nearest enclosing row or card whose text carries a date, up to six
# levels up. Returned with the container's text so a repair can see what
# the row looked like.
_ROW_OF_JS = r"""el => {
  const dateRe = /(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}|\d{1,2}\/\d{1,2}\/\d{2,4}|\d{4}-\d{2}-\d{2}/i;
  let node = el, depth = 0;
  while (node && depth < 6) {
    const txt = (node.innerText || '').trim();
    if (dateRe.test(txt)) return txt.slice(0, 300);
    node = node.parentElement; depth++;
  }
  return '';
}"""

# Where the row around a control sits, as the path of child positions from
# the page's root, with that row's text. Found the way _ROW_OF_JS finds it.
# Two controls in one row share a path, and two rows never do, even when
# they print the same words.
_ROW_KEY_JS = r"""el => {
  const dateRe = /(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}|\d{1,2}\/\d{1,2}\/\d{2,4}|\d{4}-\d{2}-\d{2}/i;
  let node = el, depth = 0;
  while (node && depth < 6 && !dateRe.test((node.innerText || '').trim())) { node = node.parentElement; depth++; }
  if (!node) node = el;
  const path = [];
  for (let n = node; n && n.parentElement; n = n.parentElement) {
    path.push(Array.prototype.indexOf.call(n.parentElement.children, n));
  }
  return [path.reverse().join('.'), (node.innerText || '').trim().slice(0, 300)];
}"""


def parse_api_date(value) -> Optional[str]:
    """A date as an API might send it, an ISO date or date-time, an epoch
    in seconds or milliseconds (as a number or a string), or the words a
    page prints. None when it is none of those."""
    if value is None:
        return None
    if isinstance(value, (int, float)) or (isinstance(value, str) and re.fullmatch(r"\d{10,13}", value.strip())):
        try:
            n = float(value)
            if n > 1e11:
                n = n / 1000.0
            from datetime import datetime, timezone
            return datetime.fromtimestamp(n, tz=timezone.utc).strftime("%Y-%m-%d")
        except (ValueError, OverflowError, OSError):
            return None
    return parse_date(str(value))


def date_shape(value) -> str:
    """What a date looked like, digits masked, for the survey."""
    return re.sub(r"\d", "#", str(value))[:40]


# keyAccountNo -> accountDisplayValue, populated from the usermetadata
# answer when the page loads (#96). Cleared at the start of each Discover.
_ACCOUNT_MAP: dict = {}


def _accounts_from_metadata(body: dict) -> dict:
    """The account map from a usermetadata answer, as {keyAccount:
    accountDisplayValue}. keyAccount is the stable opaque key each
    document carries as keyAccountNo; accountDisplayValue is the
    human-readable label the Account column shows, "Name - 1234". When
    the answer gives no useful list, an empty dict is returned."""
    return dict(_labels_of(body))


def _docs_from_api(body: dict) -> List[dict]:
    """The documents in one searchItems answer, as {date, title, kind,
    hint, guid, account, unnamed}. The guid rides as the hint and as the
    guid. It names a document, not a person.

    The account is resolved in this order (_account_of):
    1. keyAccountNo looked up in _ACCOUNT_MAP (built from usermetadata).
       This is the primary path: every document carries a keyAccountNo
       that is stable across renames, and usermetadata maps it to the
       human-readable label (#96).
    2. displayMultipleAccounts, what the list's Account column shows
       directly. This is always empty on the tester's account but kept
       as a fallback.
    The label is kept whole for the record and the file name and never
    written to a trace or a log. `unnamed` says the document carries an
    account key the account list gave no label it could use, so it has
    none here, counted for the trace and never guessed."""
    out = []
    for e in (body or {}).get("defaultDocumentList") or (body or {}).get("resultList") or []:
        if not isinstance(e, dict):
            continue
        iso = parse_api_date(e.get("documentDate")) or parse_api_date(e.get("documentLoadDate"))
        if not iso:
            continue
        title = str(e.get("documentTitle") or e.get("documentDisplayName") or e.get("documentTypeName") or "Document").strip()
        kind = str(e.get("documentTypeName") or "")
        hint = "|".join(str(e.get(k) or "") for k in ("documentGuid", "documentId"))
        # Prefer the usermetadata lookup (keyAccountNo) over displayMultipleAccounts,
        # since displayMultipleAccounts is empty when a sign-in holds multiple
        # accounts (#96). Fall back to displayMultipleAccounts for resilience.
        account = _account_of(e)
        out.append({"date": iso, "title": title, "kind": kind, "hint": hint, "guid": hint,
                    "account": account, "unnamed": not account and bool(_key_account(e))})
    return out


# --- the account each document is for ---------------------------------------------
#
# A tester's live page (#96) showed displayMultipleAccounts empty on every
# document, so no account was ever read. Each document carries keyAccountNo
# instead, one value per account, which is no account number and does not
# change when the account is renamed, and the page's account list
# (METADATA_API_RE) gives each one the label its Account column shows. The
# label is what a record, a file name and the download read, as before. The
# key a record is kept under is still the label's masked digits
# (Document.key), which a rename leaves alone too, so keyAccountNo only
# finds the label, and it is never kept, logged or written anywhere.

# The keys of _ACCOUNT_MAP a label cannot be trusted for, one two answers
# or two entries label two ways, or every key of a label two keys share, so
# a document of theirs has no label from the map.
_ACCOUNTS_UNSURE: set = set()


def _key_account(entry) -> str:
    """The keyAccountNo of a searchItems document, or "" when it has none
    that reads as one."""
    key = entry.get("keyAccountNo") if isinstance(entry, dict) else None
    return key.strip() if isinstance(key, str) else ""


def _account_of(entry) -> str:
    """The account the list's Account column shows for one searchItems
    document. The label the page's account list gives its keyAccountNo,
    else displayMultipleAccounts, else "". A key the list gives no label,
    or two, gives none from the map, since a label is never guessed and a
    document with none is refused wherever another document shares its date
    and title (#96)."""
    key = _key_account(entry)
    mapped = _ACCOUNT_MAP.get(key, "") if key and key not in _ACCOUNTS_UNSURE else ""
    return mapped or re.sub(r"\s+", " ", str(entry.get("displayMultipleAccounts") or "")).strip()


def _labels_of(body) -> List[Tuple[str, str]]:
    """(keyAccount, accountDisplayValue) for each account in one
    usermetadata answer whose two are both words, spacing tidied. Anything
    else in the answer is passed over unread."""
    accounts = body.get("accountList") if isinstance(body, dict) else None
    out = []
    for a in accounts if isinstance(accounts, list) else []:
        if not isinstance(a, dict):
            continue
        key, label = a.get("keyAccount"), a.get("accountDisplayValue")
        if not isinstance(key, str) or not isinstance(label, str):
            continue
        key, label = key.strip(), re.sub(r"\s+", " ", label).strip()
        if key and label:
            out.append((key, label))
    return out


def _note_accounts(body) -> int:
    """Keep the labels one usermetadata answer gives, and how many it gave.
    A key labeled two ways, by two answers or by two entries of one, and
    every key of a label two keys share, account_form telling them apart no
    better than the Account column does, keep no label, so a document of
    theirs reads as one with no account rather than as either one."""
    pairs = _labels_of(body)
    for key, label in pairs:
        held = _ACCOUNT_MAP.get(key)
        if held is not None and account_form(held) != account_form(label):
            _ACCOUNTS_UNSURE.add(key)
        _ACCOUNT_MAP[key] = label
    by_form: dict = {}
    for key, label in _ACCOUNT_MAP.items():
        by_form.setdefault(account_form(label), set()).add(key)
    for keys in by_form.values():
        if len(keys) > 1:
            _ACCOUNTS_UNSURE.update(keys)
    return len(pairs)


def accounts_named() -> int:
    """How many accounts the page's account list gave a label this
    discovery could use, for the log and the trace."""
    return sum(1 for key in _ACCOUNT_MAP if key not in _ACCOUNTS_UNSURE)


# The masked tail of an account as a list shows it, "-1234", "- 1234",
# "...1234", "(...1234)", "****1234" or "xx1234", at the end of the label or
# of one account in a label that names several, before a comma or a
# semicolon, optionally followed by a "(Closed)" or "[inactive]" note. Digits
# printed any other way, a year in a nickname, are not one.
_ACCOUNT_TAIL_RE = re.compile(
    r"(?:-|\.{2,}|\*{2,}|[xX•]{2,})\s*(\d{3,6})\)?(?:\s*[\(\[]?(?:closed|inactive)[\)\]]?)?\s*(?=[,;]|$)",
    re.I)


def account_tails(label: str) -> List[str]:
    """The masked tails a list's account label carries, in order, or none.
    The words before a tail are the account's name, which a person can
    change on E*TRADE as a nickname, so the tail is what says which
    account it is (#96)."""
    return [m.group(1) for m in _ACCOUNT_TAIL_RE.finditer(re.sub(r"\s+", " ", label or "").strip())]


def account_form(label: str) -> str:
    """An account's label in one form whatever its spacing, capitals or way
    of masking, "invented brokerage -1111" for "Invented Brokerage - 1111"
    or "INVENTED BROKERAGE ...1111", to compare two labels whole."""
    text = re.sub(r"\s+", " ", label or "").strip().lower()
    return _ACCOUNT_TAIL_RE.sub(lambda m: "-" + m.group(1), text)


def twin_labels(labels) -> set:
    """The labels, each in account_form, that show the same masked tails as
    another label naming a different account, "Invented Brokerage -1111"
    beside "Invented Roth IRA -1111". Their tails cannot tell them apart, so
    each is known by its whole label. Over every label the lists named, this
    is what a download reads, where it can only add refusals (_for_this)."""
    by_tails: dict = {}
    for label in labels or []:
        tails = tuple(account_tails(label))
        if tails:
            by_tails.setdefault(tails, set()).add(account_form(label))
    return {form for forms in by_tails.values() if len(forms) > 1 for form in forms}


def _listed_fields(d) -> Tuple[str, str, str]:
    """(date, title, account) of a listed document, a RawDoc or a dict from
    _docs_from_api."""
    if isinstance(d, dict):
        date, title, account = d.get("date") or d.get("date_text"), d.get("title"), d.get("account")
    else:
        date, title, account = getattr(d, "date_text", ""), getattr(d, "title", ""), getattr(d, "account", "")
    return str(date or ""), str(title or ""), re.sub(r"\s+", " ", str(account or "")).strip()


def twins_on_one_day(docs) -> set:
    """The labels, in account_form, that show the same masked tails as
    another label the lists give a document of the same date and title.
    Only there can the tails not keep two documents' keys apart, so only
    those are keyed by their whole label and counted as accounts of their
    own. One account the lists word two ways, an older nickname on older
    documents or a tax form's own wording, never shares a date and title
    with itself, and was taken for two accounts, so its history was not
    moved and every statement was taken again (second review of #96)."""
    by_day: dict = {}
    for d in docs or []:
        date, title, account = _listed_fields(d)
        if account:
            by_day.setdefault((date, _norm(title)), []).append(account)
    return {form for labels in by_day.values() for form in twin_labels(labels)}


def accounts_in(docs) -> set:
    """The accounts a list's documents belong to. When any label shows a
    masked tail, each account is its tail, or its whole label when another
    label shows the same tail on a document of the same date and title
    (twins_on_one_day), and a label showing none, "Multiple Accounts" on a
    tax form, adds no account. Only when no label shows a tail is each
    account its whole label. A label naming several accounts counts each of
    them. A label with no digits beside an account's own made a sign-in of
    one account count as two (second review of #96)."""
    labels = [_listed_fields(d)[2] for d in docs or []]
    twins = twins_on_one_day(docs)
    tailed = any(account_tails(label) for label in labels)
    found = set()
    for label in labels:
        if not label:
            continue
        tails = account_tails(label)
        if tails:
            found.update([account_form(label)] if account_form(label) in twins else tails)
        elif not tailed:
            found.add(account_form(label))
    return found


# --- an account's digits in a statement saved before #96 ---------------------
#
# How a saved statement may print the account it is for, read to move a
# record kept before #96 to its account on a sign-in of several accounts.
# No E*TRADE PDF has been seen yet, so each of these is a guess, and each is
# a shape an account number takes, never a number on its own. The last
# digits after masking marks, "XXXX-1111", "XXXX1111", "**** 1111",
# "####1111", "...1111", "(...1111)" or "--1111", after an account's
# "ending in", after an "Account Number", "Account No.", "Acct #" or
# "Account:" label, as the end of a number written "6789-1111", or after
# the words of the account's own label as the list shows it, "Invented
# Brokerage -1111". A year, an amount, a date, a time or a Social Security
# or tax id number is none of them (tails_printed).

_MARKS = "Xx*#•●∗"
_MARK = "[" + _MARKS + "]"
# The digits end the number. Not followed by another digit, or by a
# decimal point, comma, slash, colon or dash and a digit, as an amount, a
# date, a time or the first part of a longer number is.
_DIGITS_END = r"(?![0-9])(?![.,/:\-][0-9])"
# A Social Security, tax id or employer id number masked to its last four,
# "XXX-XX-1111" or "XX-XXX1111", by the marks before the digits.
_TAX_ID_MASK_RE = re.compile(r"%s{3}-%s{2}|%s{2}-%s{3}" % ((_MARK,) * 4))
# Words that say a number nearby is a tax id, not an account.
_TAX_ID_WORDS_RE = re.compile(
    r"\b(?:ssn|tin|ein|social security|taxpayer|tax id|identification)\b", re.I)
_YEAR_RE = re.compile(r"(?:19|20)[0-9]{2}")


# Any account number's last digits, for account_numbers_printed, in place
# of one tail. Up to twelve, so a number printed whole still ends them.
_ANY_DIGITS = r"(?P<digits>[0-9]{3,12})"


def _printed_shapes(tail: str) -> List["re.Pattern"]:
    """The shapes of an account number ending in `tail` that
    tails_printed accepts, beside the account's own label. `tail` is the
    digits, or _ANY_DIGITS for any account number at all."""
    t = tail + _DIGITS_END
    return [re.compile(p, re.I) for p in (
        # masking marks, "XXXX-1111", "XXXX1111", "XX-XXXX-1111"
        r"(?<![0-9A-Za-z])(?P<mask>%s{2,}(?:-%s+)*)-?%s" % (_MARK, _MARK, t),
        # four or more marks and a space, "**** 1111", "XXXX XXXX 1111"
        r"(?<![0-9A-Za-z])(?P<mask>%s{4,}(?: %s{4,})*) %s" % (_MARK, _MARK, t),
        # a short run of dots or an ellipsis, "...1111", "(...1111)", never a
        # dot leader's long run before a page number or a year
        r"(?<![0-9.])\.{2,4}%s" % t,
        r"… ?%s" % t,
        # a run of dashes, "--1111"
        r"(?<![0-9\-])-{2,4}%s" % t,
        # "Account ending in 1111", "card number ends with 1111", the words
        # of an account before it, since "the year ending 2024" is a year
        r"\b(?:account|acct|card|number)\b[^0-9]{0,30}?\bend(?:ing|s) (?:in|with) ?[:#]? ?"
        r"(?:[%s.…\-]+ ?)?%s" % (_MARKS, t),
        # a label, "Account Number: 6789-1111", "Account No. XXXX1111",
        # "Acct #1111", "Account: ****1111", the digits ending the number
        # that follows it
        r"\b(?:account|acct)\b\.? ?(?:(?:number|no\b\.?|num\b\.?) ?(?:\(s\) ?)?[:#.]?|[:#]{1,2})"
        r" ?(?:[0-9%s]+-)*[0-9%s]*?%s" % (_MARKS, _MARKS, t),
        # a number written in E*TRADE's own shape, "6789-1111"
        r"(?<![0-9\-])(?P<head>[0-9]{4})-%s" % t,
    )]


def _label_shape(label: str) -> Optional["re.Pattern"]:
    """The account's own label as the list shows it, its words and its
    masked tail, in any spacing, capitals or masking, or None for a label
    without the one tail."""
    found = list(_ACCOUNT_TAIL_RE.finditer(re.sub(r"\s+", " ", label or "").strip()))
    if len(found) != 1:
        return None
    m = found[0]
    words = re.sub(r"\s+", " ", label or "").strip()[:m.start()].strip()
    if not re.search(r"[A-Za-z]", words):
        return None
    name = r" ?".join(re.escape(w) for w in words.split(" "))
    return re.compile(r"%s ?(?:-|\.{2,}|\*{2,}|[xX•]{2,}) ?\(?%s%s"
                      % (name, m.group(1), _DIGITS_END), re.I)


def _a_tax_id(text: str, m) -> bool:
    """Whether a match is a tax id's last digits, by its masking marks or
    by words just before it."""
    mask = m.groupdict().get("mask")
    if mask and _TAX_ID_MASK_RE.fullmatch(mask):
        return True
    return bool(_TAX_ID_WORDS_RE.search(text[max(0, m.start() - 40):m.end()]))


def _a_year_range(m) -> bool:
    """Whether "2024-2025" was taken for a number ending in 2025."""
    head = m.groupdict().get("head")
    last = m.groupdict().get("digits") or m.group(0)[-4:]
    return bool(head and _YEAR_RE.fullmatch(head) and _YEAR_RE.fullmatch(last))


def tails_printed(text: str, labels) -> set:
    """The masked tails of the listed accounts, `labels` as the list shows
    them, that a statement's text prints as the end of an account number
    (the shapes above). A tail printed only as a number of its own, a year
    or an amount, is not printed here. Only the tails the labels carry are
    looked for, and nothing of the text is kept or written anywhere."""
    text = re.sub(r"\s+", " ", text or "")
    shapes: dict = {}
    for label in sorted(set(labels or [])):
        for tail in account_tails(label):
            shapes.setdefault(tail, _printed_shapes(tail))
        own = _label_shape(label)
        if own is not None:
            shapes.setdefault(account_tails(label)[0], []).append(own)
    found = set()
    for tail, patterns in shapes.items():
        for pattern in patterns:
            if any(not _a_tax_id(text, m) and not _a_year_range(m)
                   for m in pattern.finditer(text)):
                found.add(tail)
                break
    return found


def tails_seen(text: str, tails) -> set:
    """The tails that end any run of digits in the text however it is
    printed, a year, an amount or another account's number in a line about
    a transfer included. Looser than tails_printed on purpose, since a
    statement is moved to one account only when no other listed account's
    digits show in it at all."""
    text = text or ""
    return {t for t in tails or [] if re.fullmatch(r"[0-9]+", t)
            and re.search(t + r"(?![0-9])", text)}


# An account's label as E*TRADE writes it, words, a space and a dash before
# the digits, "Individual Brokerage -2222", whichever account it is.
_LABEL_DIGITS_RE = re.compile(r"(?<![0-9A-Za-z])[A-Za-z]{2,} -(?P<digits>[0-9]{3,12})" + _DIGITS_END)
# Words of an account, which between a tax word and a number say the number
# is the account's.
_ACCOUNT_WORDS_RE = re.compile(r"\b(?:account|acct|card)\b", re.I)


def _a_tax_id_alone(text: str, m) -> bool:
    """Whether a match is a tax id's last digits, by its masking marks, or
    by a tax word before it with no word of an account between, so a
    number labeled as an account's just after a masked tax id is still an
    account's."""
    mask = m.groupdict().get("mask")
    if mask and _TAX_ID_MASK_RE.fullmatch(mask):
        return True
    start = max(0, m.start() - 40)
    words = list(_TAX_ID_WORDS_RE.finditer(text[start:m.start()]))
    if not words:
        return False
    return not _ACCOUNT_WORDS_RE.search(text[start + words[-1].end():m.end()])


def account_numbers_printed(text: str) -> set:
    """The last digits of every account number the text prints in one of
    the shapes above, or in a label's shape, whichever account it is,
    listed or not. A statement of an account the lists no longer name, a
    closed one, printing its own number and another account's in a
    transfer, shows only that other account among the listed ones, and was
    moved to it (review of the relabel). Every number found only refuses a
    move, so a tax word does not hide a number labeled as an account's, and
    a closed account's label counts as much as a listed one's (the second
    review). Nothing of the text is kept or written anywhere."""
    text = re.sub(r"\s+", " ", text or "")
    found = set()
    for pattern in _printed_shapes(_ANY_DIGITS) + [_LABEL_DIGITS_RE]:
        for m in pattern.finditer(text):
            if not _a_tax_id_alone(text, m) and not _a_year_range(m):
                found.add(m.group("digits"))
    return found


def one_account(digits: str, tail: str) -> bool:
    """Whether a number printed ending in `digits` may be the account whose
    masked tail is `tail`, one of the two ending the other."""
    return bool(digits and tail) and (digits.endswith(tail) or tail.endswith(digits))


def goto_docs_capturing(page, capture: list) -> bool:
    """Open the Documents page while catching the searchItems answer that
    fills it, so discovery never has to know how the page asks, and every
    later page of it (_read_every_page). Also catches the usermetadata
    answer, which maps keyAccountNo to a human-readable account label,
    and stores it in _ACCOUNT_MAP for _docs_from_api to use (#96), only
    from E*TRADE's own hosts and only as its answer is read, nothing asked
    of it here (_note_accounts)."""
    start, asked, accounts = len(capture), [], []

    def on_response(res):
        try:
            url = res.url or ""
            if not is_safe_url(url):
                return
            if DOCS_API_RE.search(url):
                body = whole_json(res.json())
                asked.append(_asked_of(res))
                capture.append(body)
            elif METADATA_API_RE.search(url):
                body = whole_json(res.json())
                accounts.append(_note_accounts(body))
        except Exception:
            pass
    page.on("response", on_response)
    try:
        # The page is a single-page app. Landing on it a second time
        # changes nothing and calls nothing, so it is reloaded.
        already = "accountdocs" in (page.url or "")
        page.goto(DOCS_URL, wait_until="domcontentloaded", timeout=60000)
        if already:
            page.reload(wait_until="domcontentloaded", timeout=60000)
        for _ in range(30):
            page.wait_for_timeout(500)
            if capture:
                break
        page.wait_for_timeout(1500)
        # The account list may come a moment after the documents.
        for _ in range(6):
            if accounts:
                break
            page.wait_for_timeout(500)
    except Exception as e:
        log.info("goto documents failed: %s", e)
    finally:
        try:
            page.remove_listener("response", on_response)
        except Exception:
            pass
    # Once nothing listens, so a later page asked here is never caught as a
    # list of its own.
    _read_every_page(page, capture, asked, start)
    dismiss_overlay(page)
    return is_safe_url(page.url or "") and not looks_signed_out(page)


# --- every page of a list ---------------------------------------------------------
#
# The page asks searchItems for one page of a period's list, with a pageNum
# in the body, and the answer says how many documents the list holds,
# numFound. Discovery read the first page alone, so on a list of several
# pages every document past the first was never listed, and the run
# finished clean (#96). Each later page is now asked the way the page asked
# for the first, from inside the page, at the same address with the same
# body and headers and the next pageNum, until the count is reached, and
# its documents go after the first page's in that one list. A list that
# cannot be read to its end says why, in these words, and only a listing
# whose every list was read whole lets a run finish clean or move a record
# kept before to another key.

NO_COUNT = "the list gave no count"
NO_REQUEST = "the request for the list could not be asked again"
PAGE_REFUSED = "a later page was refused"
PAGE_UNREAD = "a later page could not be read"
PAGE_EMPTY = "a later page came back empty"
PAGE_REPEATED = "a later page repeated an earlier one"
TOO_MANY = "more documents came than the list counted"
TOO_MANY_PAGES = "the list has more pages than are read"
# The documents carry keys for their accounts and no account list gave any
# of them a label, so every account is missing from what was read (review).
# Read as a list missing its accounts, every statement saved before came
# out as a new document of no account, taken again.
ACCOUNTS_UNREAD = "the account list was not read"
# An account a record holds has no label now, on a document of its date and
# title, the docs side's own check (App._accounts_lost).
ACCOUNT_LOST = "an account the lists named before has no label now"
_UNREAD_WORDS = (NO_COUNT, NO_REQUEST, PAGE_REFUSED, PAGE_UNREAD, PAGE_EMPTY, PAGE_REPEATED,
                 TOO_MANY, TOO_MANY_PAGES, ACCOUNTS_UNREAD, ACCOUNT_LOST)

# The most pages of one period's list that are read, and the pause before
# each later page.
MAX_PAGES = 40
PAGE_PAUSE_MS = 500

# Each list the last discovery read, as (pages read, why it was not read to
# its end or ""), for Listing and the trace.
_PAGED: list = []

# Headers of the page's own request that are not sent again, the ones the
# browser sets itself and will not take from a page, and the cookie, which
# the browser sends of itself when the page's own request carried one.
_NOT_RESENT_RE = re.compile(
    r"^(?:cookie|host|origin|referer|user-agent|content-length|connection|keep-alive|"
    r"accept-encoding|accept-language|priority|te|trailer|upgrade|via|expect|dnt|"
    r"sec-.*|proxy-.*)$", re.I)
# A header's name as a page may send it. Playwright also gives the
# protocol's own, ":authority" and the like, which fetch refuses.
_HEADER_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,63}$")


def _asked_of(res) -> dict:
    """How the page asked for a list, its address, its body, the headers
    worth sending again and whether it sent a cookie, so a later page is
    asked the same way. Empty when any of it cannot be read. Never raises,
    since it runs in a listener."""
    try:
        req = res.request
        if (req.method or "").upper() != "POST":
            return {}
        sent = whole_json(json.loads(req.post_data or "null"))
        if not isinstance(sent, dict):
            return {}
        # What the page's own script sent, never what the network added on
        # the way, which as a page's own would ask the server's leave first.
        kept = {str(k): str(v) for k, v in dict(req.headers or {}).items()
                if _HEADER_NAME_RE.match(str(k)) and not _NOT_RESENT_RE.match(str(k))}
        try:
            cookie = any(str(k).lower() == "cookie" for k in (req.all_headers() or {}))
        except Exception:
            cookie = False
        return {"url": req.url or "", "body": sent, "headers": kept, "cookie": cookie}
    except Exception:
        return {}


def _count_of(body) -> Optional[int]:
    """How many documents a list says it holds, its numFound, or None when
    it gives no count that reads as one."""
    found = body.get("numFound") if isinstance(body, dict) else None
    if isinstance(found, bool):
        return None
    if isinstance(found, int):
        return found if found >= 0 else None
    if isinstance(found, float) and found.is_integer() and 0 <= found < 1e7:
        return int(found)
    if isinstance(found, str) and re.fullmatch(r"\s*\d{1,7}\s*", found):
        return int(found)
    return None


def _entries_of(body) -> Tuple[str, list]:
    """The name a list keeps its documents under and its documents, read
    the way _docs_from_api reads them."""
    if not isinstance(body, dict):
        return "defaultDocumentList", []
    for name in ("defaultDocumentList", "resultList"):
        if body.get(name):
            return name, list(body[name]) if isinstance(body[name], list) else []
    return "defaultDocumentList", []


def _page_number(value) -> Optional[int]:
    """The page a request asks for, a number or a number written as words
    of digits, or None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and re.fullmatch(r"\d{1,4}", value.strip()):
        return int(value)
    return None


def _same_entry(entry) -> tuple:
    """What a list's entry is whichever load brought it, without the ids
    that change every time the list loads."""
    if not isinstance(entry, dict):
        return (repr(type(entry)),)
    return tuple(str(entry.get(k) or "") for k in (
        "documentDate", "documentLoadDate", "documentTitle", "documentDisplayName",
        "documentTypeName", "displayMultipleAccounts", "keyAccountNo"))


_PAGE_JS = r"""async ([url, headers, body, credentials]) => {
  let r = null;
  try {
    r = await fetch(url, {method: "POST", credentials, redirect: "error", headers,
                          body: JSON.stringify(body)});
  } catch (e) {
    return {status: 0, url: "", data: null};
  }
  let data = null;
  try { data = await ppJson(r); } catch (e) { if (ppRefused(e)) throw e; }
  return {status: r.status, url: r.url, data};
}"""


def _later_pages(page, asked: dict, body) -> Tuple[object, int, str]:
    """One list, `body` its first page, with every later page's documents
    added after the first page's, how many pages that is, and why it was
    not read to its end, "" when it was.

    A list with no documents, or a count no larger than what its first
    page holds, is whole as it is. One with documents and no count may
    have more pages, and is not. Pages are asked by number after the first
    one's, until the count is reached. A page that is refused, does not
    read as a list, comes back empty, or holds exactly what an earlier page
    held (a request whose page number is not heard), ends the reading
    there, keeping what came before it. More documents than the count ends
    it keeping the first page alone, since which page brought the extra
    cannot be told. Nothing is asked of any address but the list's own on
    E*TRADE's hosts, only from a tab on E*TRADE's site, and no redirect is
    followed."""
    name, first = _entries_of(body)
    count = _count_of(body)
    if count is None:
        return body, 1, NO_COUNT if first else ""
    if count <= len(first):
        return body, 1, ""
    asked = asked if isinstance(asked, dict) else {}
    url, sent = asked.get("url") or "", asked.get("body")
    start = _page_number(sent.get("pageNum")) if isinstance(sent, dict) else None
    if start is None or not (is_safe_url(url) and DOCS_API_RE.search(url)):
        return body, 1, NO_REQUEST
    credentials = "include" if asked.get("cookie") else "same-origin"
    entries, read = list(first), [[_same_entry(e) for e in first]]

    def whole(why: str = "") -> Tuple[object, int, str]:
        return dict(body, **{name: entries}), len(read), why

    while len(entries) < count:
        if len(read) >= MAX_PAGES:
            return whole(TOO_MANY_PAGES)
        number = start + len(read)
        ask = dict(sent, pageNum=str(number) if isinstance(sent["pageNum"], str) else number)
        try:
            # A moment between pages, as a person paging would take. The
            # page's own headers go only from a tab on E*TRADE's site, since
            # a tab that went elsewhere could hand them to that site.
            page.wait_for_timeout(PAGE_PAUSE_MS)
            if not is_safe_url(page.url or ""):
                log.info("the tab left E*TRADE's site before page %d of a list", number)
                return whole(PAGE_UNREAD)
            got = intake.evaluate(page, _PAGE_JS, [url, asked.get("headers") or {}, ask,
                                                   credentials]) or {}
        except Exception as e:
            log.info("page %d of a list could not be asked for: %s", number, type(e).__name__)
            return whole(PAGE_UNREAD)
        status = got.get("status") if isinstance(got, dict) else None
        if status != 200:
            log.info("page %d of a list was answered %s", number, status)
            return whole(PAGE_UNREAD if not status else PAGE_REFUSED)
        landed = str(got.get("url") or "")
        data = whole_json(got.get("data"))
        if not (is_safe_url(landed) and DOCS_API_RE.search(landed)) or not isinstance(data, dict) \
                or not any(k in data for k in ("defaultDocumentList", "resultList")):
            return whole(PAGE_UNREAD)
        _name, more = _entries_of(data)
        if not more:
            return whole(PAGE_EMPTY)
        shape = [_same_entry(e) for e in more]
        if shape in read:
            return whole(PAGE_REPEATED)
        read.append(shape)
        entries.extend(more)
    if len(entries) > count:
        return body, 1, TOO_MANY
    return whole()


def _read_every_page(page, capture: list, asked: list, start: int) -> List[Tuple[int, str]]:
    """Read every later page of each list caught into capture[start:],
    `asked` holding how the page asked for each, in the same order. Each
    list's pages become that one list, so a document's place among those of
    its date and title is its place in the whole period. Returns (pages
    read, why not read to the end or "") for each, and keeps them for the
    trace and Listing."""
    out = []
    for i in range(start, len(capture)):
        how = asked[i - start] if 0 <= i - start < len(asked) else {}
        capture[i], pages, why = _later_pages(page, how, capture[i])
        if why:
            log.info("a list was not read to its end, %d page(s) read: %s", pages, why)
        out.append((pages, why))
    _PAGED.extend(out)
    return out


def is_date_filter(label: str) -> bool:
    """The documents page's period picker or one of its periods, and
    nothing that commits anything."""
    label = (label or "").strip()
    return bool(DATE_FILTER_RE.match(label)) and not FORBIDDEN_CONTROL_RE.search(label)


def picker_period(label: str) -> Optional[str]:
    """The period a picker's name shows, "Last 90 Days" out of
    "Timeframe ,  Last 90 Days", or None when the name holds anything
    but the picker's own label and one period."""
    label = label or ""
    if FORBIDDEN_CONTROL_RE.search(label):
        return None
    text = re.sub(r"\s+", " ", _PICKER_LABEL_RE.sub(" ", label)).strip()
    return text if is_date_filter(text) else None


def is_period_apply(label: str) -> bool:
    """The filter's own Apply, and nothing that merely starts with it."""
    return bool(PERIOD_APPLY_RE.match(label or ""))


def plan_periods(options) -> List[str]:
    """The periods to apply, in order, from what the picker offered. One
    period wider than a year when there is one. Otherwise "Year To Date"
    and every year, newest first, since together they reach furthest
    back. Otherwise the widest narrow one."""
    opts: List[str] = []
    for t in options or []:
        t = re.sub(r"\s+", " ", t or "").strip()
        if is_date_filter(t) and t not in opts:
            opts.append(t)
    for pat in _WIDE_FIRST:
        for t in opts:
            if re.search(pat, t, re.I):
                return [t]
    years = sorted({t for t in opts if re.fullmatch(r"(19|20)\d{2}", t)}, reverse=True)
    if years:
        ytd = [t for t in opts if re.fullmatch(r"year\s+to\s+date|ytd", t, re.I)][:1]
        return ytd + years
    for pat in _NARROW_LAST:
        for t in opts:
            if re.search(pat, t, re.I):
                return [t]
    return []


def _find_picker(page):
    """The period picker and the period it shows, or (None, ""). A button
    whose name carries the picker's own label is preferred, so a year in
    an open list is never taken for the picker. A button that could not be
    read may have been the picker's own, so then only a button carrying
    the label is taken. A year in the open list would be taken for the
    picker when the picker's own button did not answer in time (found
    beside CI run 36792330947)."""
    found = []
    unread = 0
    try:
        loc = page.get_by_role("button", name=PICKER_NAME_RE)
        for i in range(min(loc.count(), 8)):
            el = loc.nth(i)
            try:
                label = el.get_attribute("aria-label") or el.inner_text(timeout=800) or ""
                period = picker_period(label)
                if period and el.is_visible():
                    found.append((not re.search(r"time\s*frame", label, re.I), i, el, period))
            except Exception:
                unread += 1
                continue
    except Exception:
        pass
    if not found:
        return None, ""
    found.sort(key=lambda f: (f[0], f[1]))
    if found[0][0] and unread:
        log.info("a period button could not be read, so no button without the picker's label is taken")
        return None, ""
    return found[0][2], found[0][3]


def _option_texts(page) -> set:
    """The visible options of an open list, by role."""
    out = set()
    try:
        loc = page.get_by_role("option")
        for i in range(min(loc.count(), 40)):
            el = loc.nth(i)
            try:
                if el.is_visible():
                    out.add(re.sub(r"\s+", " ", el.inner_text(timeout=500) or "").strip())
            except Exception:
                continue
    except Exception:
        pass
    return out


# The periods the picker offered when it was last opened, so a download
# whose period is already showing does not open it again.
_OFFERED: List[str] = []
# How much longer an opened list may take to show its periods.
PERIODS_WAIT_S = 4


def _periods_offered(page, picker, current: str = "") -> Tuple[List[str], int]:
    """Open the picker and read the periods its list offers, with how many
    other texts appeared beside them, for the trace.

    The period the picker shows counts as offered. What appeared is read as
    what is new since the list opened, and the picker's own text was there
    before, so a list of plain elements lost the period it was showing. A
    year that was showing then looked unoffered, and a document of that
    year was sent to "Year To Date" (#36, review). A list drawing late is
    read again for a few seconds. Reading the controls one at a time used
    to give it a second or so more before the visible texts were read, and
    the core reads them in one call now (the census after CI run
    36792330947). A read that still finds no period returns nothing and
    leaves the periods remembered from the last read as they were.

    Short texts already showing before the list opened are left out as
    well as controls. Only controls used to be, so every short text on the
    page counted as having appeared, an account's last four or a year
    printed beside it among them (review)."""
    before = _control_texts(page) | _short_visible_texts(page)
    try:
        is_open = (picker.get_attribute("aria-expanded", timeout=1000) or "").lower() == "true"
    except Exception:
        is_open = False
    if not is_open:
        picker.click(timeout=5000)
        page.wait_for_timeout(1500)
    until = time.monotonic() + PERIODS_WAIT_S
    while True:
        offered = _option_texts(page) | ((_control_texts(page) | _short_visible_texts(page)) - before)
        periods = {re.sub(r"\s+", " ", t).strip() for t in offered if is_date_filter(t)}
        if periods or time.monotonic() >= until:
            break
        page.wait_for_timeout(500)
    others = len(offered) - len(periods)
    if not periods:
        return [], others
    if current and is_date_filter(current):
        periods.add(re.sub(r"\s+", " ", current).strip())
    _OFFERED[:] = sorted(periods)
    return sorted(periods), others


def _is_year(period: str) -> bool:
    return bool(re.fullmatch(r"(19|20)\d{2}", period or ""))


def period_for(iso_date: str, offered) -> Optional[str]:
    """The one period that lists the document dated `iso_date`, chosen from
    the same plan discovery applied. The year of the date when the picker
    offers it, "Year To Date" for a date newer than every year it offers,
    the single period discovery used when the picker offers no years, and
    None when no period lists the date."""
    plan = plan_periods(offered)
    years = [p for p in plan if _is_year(p)]
    if not years:
        return plan[0] if plan else None
    year = (iso_date or "")[:4]
    if year in years:
        return year
    rest = [p for p in plan if not _is_year(p)]
    if rest and year > max(years):
        return rest[0]
    return None


def _same_period(a: str, b: str) -> bool:
    """One period whatever its spacing and capitals. The picker offered
    "Last 30 Days" and "Last 30 days" side by side (#36)."""
    a = re.sub(r"\s+", " ", a or "").strip().lower()
    b = re.sub(r"\s+", " ", b or "").strip().lower()
    return bool(a) and a == b


def show_period_for(page, iso_date: str, trace: Optional[list] = None) -> bool:
    """Set the period picker to the one period that lists the document
    dated `iso_date`, unless it already shows it. True when it does.

    Each Apply replaces the list rather than adding to it. Discovery walks
    "Year To Date" and every year back, so it ends showing the oldest year.
    On the tester's 0.37.0 run that year was empty, and the download looked
    for each document's row on an empty list (#36). The trace entry holds
    period words and booleans only."""
    note: dict = {"note": "period for this document"}
    if trace is not None:
        trace.append(note)
    try:
        picker, current = _find_picker(page)
        note["found"] = picker is not None
        note["showing"] = current
        if picker is None:
            return False
        remembered = period_for(iso_date, _OFFERED)
        if remembered and _same_period(remembered, current):
            note["period"] = remembered
            return True
        periods, _others = _periods_offered(page, picker, current)
        # A read that found no period keeps the answer the remembered
        # periods give, rather than leaving the list on whatever it showed,
        # which straight after discovery is the empty oldest year.
        want = period_for(iso_date, periods) if periods else remembered
        note["period"] = want or ""
        if not want or _same_period(want, current):
            _close_list(page)
            return bool(want)
        lists: list = []
        chosen = _choose_period(page, want, lists, trace, already_open=True)
        _note_listed(lists)
        return chosen
    except Exception as e:
        note["error"] = type(e).__name__
        log.info("could not set the period for %s: %s", iso_date, e)
        return False


def _list_shut(picker) -> bool:
    """Whether the period picker says its list is shut, aria-expanded
    "false". One that says nothing, or cannot be read, is not taken as shut."""
    try:
        return (picker.get_attribute("aria-expanded", timeout=1000) or "").strip().lower() == "false"
    except Exception:
        return False


def _address_of(page) -> str:
    """The tab's address without its query or fragment, "" when it cannot be
    read, to tell whether a press took the tab to another page."""
    url = getattr(page, "url", "")
    if not isinstance(url, str):
        return ""
    parts = urlsplit(url)
    return "%s://%s%s" % (parts.scheme, parts.netloc, parts.path)


def _close_list(page) -> None:
    """Close the picker's open list. Escape first. If the picker still says
    its list is open, the picker itself is pressed once more, found again
    and judged the same way as when it was opened. Nobody has seen Escape
    close E*TRADE's list, and a list left open over the rows could take
    the click meant for a document."""
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        picker, _current = _find_picker(page)
        if picker is not None and (picker.get_attribute("aria-expanded", timeout=1000) or "").lower() == "true":
            picker.click(timeout=5000)
            page.wait_for_timeout(300)
    except Exception as e:
        log.info("could not close the period list: %s", e)


def widen_date_filter(page, capture: list, trace: Optional[list] = None) -> bool:
    """Open the period picker, choose the periods plan_periods picks, and
    apply each, catching the list the page then loads. The trace says
    whether the picker was found, what it offered and what was chosen,
    in period words only."""
    note: dict = {"note": "period picker"}
    if trace is not None:
        trace.append(note)
    try:
        picker, current = _find_picker(page)
        note["found"] = picker is not None
        note["showing"] = current
        if picker is None:
            try:
                note["buttons_named_like_a_period"] = page.get_by_role("button", name=PICKER_NAME_RE).count()
            except Exception:
                pass
            return False
        periods, others = _periods_offered(page, picker, current)
        note["offered"] = periods[:30]
        note["other_texts_that_appeared"] = others
        plan = plan_periods(periods)
        note["plan"] = plan
        if not plan:
            page.keyboard.press("Escape")
            return False
        got_any = False
        for i, period in enumerate(plan):
            # The list is still open for the first period. Each later one
            # opens the picker again, once.
            got_any = _choose_period(page, period, capture, trace, already_open=(i == 0)) or got_any
        return got_any
    except Exception as e:
        note["error"] = type(e).__name__
        log.info("could not widen the date filter: %s", e)
        return False


def _row_count(page) -> int:
    """How many document rows the page is showing, for when applying a
    period brings no list the app could catch."""
    try:
        return int(page.evaluate(
            "sel => document.querySelectorAll(sel).length", FALLBACK["doc_row"]) or 0)
    except Exception:
        return 0


def _choose_period(page, choice: str, capture: list, trace: Optional[list] = None,
                   already_open: bool = False) -> bool:
    """Open the period picker unless it is open, choose `choice`, apply it,
    and catch the list the page then loads. True when a list arrived or
    rows are showing. The trace entry says what each step saw, so a
    report explains itself."""
    entry: dict = {"note": "period chosen", "period": choice}
    if trace is not None:
        trace.append(entry)
    try:
        if not already_open:
            picker, current = _find_picker(page)
            entry["picker_showed"] = current
            if picker is None:
                entry["outcome"] = "picker not found"
                return False
            picker.click(timeout=5000)
            page.wait_for_timeout(1200)
        entry["rows_before"] = _row_count(page)
        before = len(capture)
        navigations = [0]
        asked: list = []

        def on_response(res):
            try:
                if is_safe_url(res.url or "") and DOCS_API_RE.search(res.url or ""):
                    body = whole_json(res.json())
                    asked.append(_asked_of(res))
                    capture.append(body)
            except Exception:
                pass

        def on_navigated(frame):
            try:
                if frame == page.main_frame:
                    navigations[0] += 1
            except Exception:
                pass
        page.on("response", on_response)
        page.on("framenavigated", on_navigated)
        try:
            unsure: list = []
            start = _address_of(page)
            clicked = _click_text(page, choice, unsure)
            # Opened again only when nothing was pressed, a press that raised
            # having perhaps chosen the period already, and only when the
            # picker says its list is shut. Pressed while its list was open,
            # it shut the list, and the page was searched again for the
            # period's words outside it (review of #119).
            if not clicked and already_open and not unsure:
                picker, _ = _find_picker(page)
                if picker is not None and _list_shut(picker):
                    picker.click(timeout=5000)
                    page.wait_for_timeout(1200)
                    clicked = _click_text(page, choice, unsure)
            entry["option_clicked"] = clicked
            if not clicked:
                entry["outcome"] = "a press that raised" if unsure else "option not found"
                page.keyboard.press("Escape")
                return False
            page.wait_for_timeout(1500)
            entry["apply_clicked"] = False
            # Apply only on the page the period was chosen on. A press that
            # took the tab to another page met that page's own Apply (review
            # of #119).
            apply = page.get_by_role("button", name=PERIOD_APPLY_RE)
            if _address_of(page) != start:
                entry["outcome"] = "the tab left the page"
            elif apply.count() and apply.first.is_visible():
                label = apply.first.get_attribute("aria-label") or apply.first.inner_text(timeout=800) or ""
                if is_period_apply(label):
                    apply.first.click(timeout=5000)
                    entry["apply_clicked"] = True
            for _ in range(30):
                page.wait_for_timeout(500)
                if len(capture) > before:
                    break
            page.wait_for_timeout(1500)
        finally:
            for event, fn in (("response", on_response), ("framenavigated", on_navigated)):
                try:
                    page.remove_listener(event, fn)
                except Exception:
                    pass
        # Every later page of each list that came, once nothing listens.
        paged = _read_every_page(page, capture, asked, before)
        entry["pages"] = [pages for pages, _why in paged]
        entry["not_read_to_the_end"] = [Fixed(why if why in _UNREAD_WORDS else PAGE_UNREAD)
                                        for _pages, why in paged if why]
        # The recording showed Apply submitting a form that the page
        # handles itself, no navigation, and a fresh searchItems answer.
        # Whether this run matched that is written down, and so is the
        # period the picker shows afterwards, which says whether the
        # choice held or was reset.
        got_list = len(capture) > before
        rows_now = _row_count(page)
        entry["navigated"] = navigations[0] > 0
        entry["lists"] = len(capture) - before
        entry["rows_after"] = rows_now
        entry["picker_shows"] = _find_picker(page)[1]
        entry["dates"] = sorted({d["date"] for body in capture[before:] for d in _docs_from_api(body)},
                                reverse=True)[:40]
        if not got_list and rows_now:
            log.info("date filter %r brought no list, but the page shows %d row(s)",
                     choice, rows_now)
        log.info("date filter set to %r, %d list(s)", choice, len(capture) - before)
        return got_list or bool(rows_now)
    except Exception as e:
        entry["error"] = type(e).__name__
        log.info("could not choose the period %r: %s", choice, e)
        return False


# What the last discovery saw, for the file Discover and Diagnose write.
# Period words, counts and dates only.
DISCOVERY_TRACE: list = []

# How many documents each date carried in the lists the page loaded, the
# most any one list held. A download takes the row that names its
# document. When no row names it, a row is taken by its date alone only
# when this says the date held one document, because his thirteen
# documents sat on eleven dates (#36).
_LISTED: dict = {}

# The titles each date carried in those lists. A row can hold more than one
# document's control, and a control that names another document of the
# same date is never tried for this one.
_LISTED_TITLES: dict = {}

# The accounts each date and title carried in those lists, by (date, the
# title as _norm writes it), each account as _norm writes its label. Two
# accounts can each have a statement of one title on one day, and then
# only a link naming this document's own account is its own (#96).
_LISTED_ACCOUNTS: dict = {}

# How many documents each date and title carried in those lists, by (date,
# the title as _norm writes it), the most any one list held. The accounts
# alone cannot say it, since the list can give several accounts' statements
# no account at all, and then their labels are one empty label (#96).
_LISTED_DOCS: dict = {}

# How many documents each date, title and account carried in those lists,
# by (date, title, account) as _norm writes them, an account of "" for none,
# the most any one list held. Only where this is more than one is a
# document told apart from another by its place (#96).
_LISTED_SAME: dict = {}


def _note_listed(bodies) -> None:
    """Count the documents per date, and per date and title, in searchItems
    answers, and keep their titles and the accounts of each title."""
    for body in bodies or []:
        counts: dict = {}
        per_title: dict = {}
        same: dict = {}
        for d in _docs_from_api(body):
            counts[d["date"]] = counts.get(d["date"], 0) + 1
            day_title = (d["date"], _norm(d["title"]))
            per_title[day_title] = per_title.get(day_title, 0) + 1
            one = day_title + (_norm(d["account"]),)
            same[one] = same.get(one, 0) + 1
            _LISTED_TITLES.setdefault(d["date"], set()).add(d["title"])
            _LISTED_ACCOUNTS.setdefault(day_title, set()).add(_norm(d["account"]))
        for day, n in counts.items():
            _LISTED[day] = max(_LISTED.get(day, 0), n)
        for day_title, n in per_title.items():
            _LISTED_DOCS[day_title] = max(_LISTED_DOCS.get(day_title, 0), n)
        for one, n in same.items():
            _LISTED_SAME[one] = max(_LISTED_SAME.get(one, 0), n)


def _listed_docs(iso_date: str, title: str) -> int:
    """How many documents the lists gave this date and title, 0 when they
    gave none or were not read."""
    return int(_LISTED_DOCS.get((iso_date, _norm(title)), 0))


def _places_still_listed(iso_date: str, title: str, account: str = "") -> bool:
    """Whether the lists still gave this date and title more than one
    document of this account, or of no account when `account` is "", the
    only lists where such a document is told apart by its place. Once they
    give that day's documents accounts of their own, a record kept by its
    place is one of another listing (#96)."""
    return int(_LISTED_SAME.get((iso_date, _norm(title), _norm(account)), 0)) > 1


def _shared_with_no_account(iso_date: str, title: str) -> bool:
    """Whether a document the lists gave no account may be any one of
    several, the lists having given its date and title more than one
    document, or to more than one label. Which of them a row is cannot be
    told without an account, so such a document is never taken (#96)."""
    if not title:
        return False
    return _listed_docs(iso_date, title) > 1 or len(_LISTED_ACCOUNTS.get((iso_date, _norm(title)), ())) > 1


def _norm(text) -> str:
    """Words compared whatever their spacing and capitals."""
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def _alone_that_day(iso_date: str, title: str = "") -> bool:
    """Whether the lists the page loaded held one document on this date and
    it is this one. When the lists named that document, its title has to be
    the one asked for. Counting alone took a single row of the date for
    this document when the one listed that day was a different document,
    which a list read later on a page with other filters could give (#36,
    review). A title this file made up, for a document found without a
    list, names nothing, so there the count decides.

    For a document of one account, the lists also have to have given that
    date and title to this account alone (_FOR), so the only row of a date
    is never taken for it when it may be another account's (#96)."""
    if _LISTED.get(iso_date) != 1:
        return False
    held = _for_this(title)
    if held is not None and held["shared"]:
        return False
    titles = {_norm(t) for t in _LISTED_TITLES.get(iso_date, ())}
    if not titles or not title:
        return True
    return titles == {_norm(title)}


def _mentions(text: str, other: str, mine: str = "") -> bool:
    """Whether `text` carries the title `other` anywhere, as whole words,
    other than as a piece of this document's own title `mine`."""
    t, o, m = _norm(text), _norm(other), _norm(mine)
    if not t or not o:
        return False
    edge = r"(?<![a-z0-9])%s(?![a-z0-9])"
    own = [(x.start(), x.end()) for x in re.finditer(edge % re.escape(m), t)] if m else []
    for x in re.finditer(edge % re.escape(o), t):
        if not any(a <= x.start() and x.end() <= b for a, b in own):
            return True
    return False


def _names_another(texts, title: str, iso_date: str) -> bool:
    """Whether a control's text or label, or a row's words, carry a
    different document that the lists gave the same date. Anywhere in the
    words counts, not only at their start, since what says a row may hold
    another document has to catch it however the page words it. Naming
    the document the link is for is stricter, see names_title (#36,
    review)."""
    mine = _norm(title)
    for other in _LISTED_TITLES.get(iso_date, ()):
        if _norm(other) == mine:
            continue
        if any(_mentions(t, other, title) for t in texts if t):
            return True
    return False


def _entries_only_where_shared(docs) -> None:
    """Keep the entry, what tells one document from the next of the same
    date, title and account, the list giving them none or the same one,
    only where another document shares all three. Every other one keeps the
    key it always had, so nothing a sign-in of one account saved is taken
    again (#96)."""
    shared: dict = {}
    for d in docs:
        one = (d.date_text, d.title, _norm(d.account))
        shared[one] = shared.get(one, 0) + 1
    for d in docs:
        if shared.get((d.date_text, d.title, _norm(d.account)), 0) < 2:
            d.entry = ""


class Listing(list):
    """The documents discovery found, and why a period's list was not read
    to its end, in fixed words (_UNREAD_WORDS), none when every list was.
    Only a listing read whole may move a record kept before to another key,
    or let a run finish clean. `unnamed_accounts` counts the accounts whose
    key the account list gave no label, each one an account the sign-in
    has, so it is counted with the rest, never named."""
    unread: tuple = ()
    unnamed_accounts: int = 0


def _listing(docs, paged, more=(), unnamed_accounts: int = 0) -> Listing:
    out = Listing(docs)
    out.unread = tuple(sorted({why if why in _UNREAD_WORDS else PAGE_UNREAD
                               for _pages, why in paged if why} | set(more)))
    out.unnamed_accounts = unnamed_accounts
    return out


def collect_download_docs(page) -> Listing:
    """Every document the Documents page lists, from the API answers the
    page loads for its default period and for every period the picker is
    set to, every page of each, else the rows."""
    docs: List[RawDoc] = []
    seen = set()
    bodies: list = []
    trace = DISCOVERY_TRACE
    del trace[:]
    _LISTED.clear()
    _LISTED_TITLES.clear()
    _LISTED_ACCOUNTS.clear()
    _LISTED_DOCS.clear()
    _LISTED_SAME.clear()
    _ACCOUNT_MAP.clear()
    _ACCOUNTS_UNSURE.clear()
    del _PAGED[:]
    # The page is loaded again here, so it shows a list's first page.
    _MOVED_ON[0] = False
    if goto_docs_capturing(page, bodies):
        trace.append({"note": "default list", "lists": len(bodies),
                      "dates": sorted({d["date"] for b in bodies for d in _docs_from_api(b)},
                                      reverse=True)[:40]})
        wider: list = []
        widen_date_filter(page, wider, trace)
        # The default period's list is kept alongside the wider ones. A
        # period that applied without a list the app caught used to leave
        # nothing at all to read.
        bodies = bodies + wider
        _note_listed(bodies)
        for body in bodies:
            places: dict = {}
            for d in _docs_from_api(body):
                # Two accounts can each have a statement of one title on one
                # day. Kept by date and title alone, the second account's
                # was dropped here and never listed (#96).
                key = (d["date"], d["title"], _norm(d["account"]))
                # And by its place among this list's entries of that date,
                # title and account, a list being every page of one period.
                # Five accounts' statements the list gave no account were
                # one record here, and four were never listed (#96). They
                # were then told apart by the list's own ids, which change
                # every time the list loads, so every list and every
                # Discover added each such statement again, and Run All
                # saved the copies (0.56.0, #96). One account's two
                # documents of a title and day, two trade confirmations,
                # were one record once the account was read, and the second
                # was never listed (review).
                places[key] = places.get(key, 0) + 1
                entry = "#%d" % places[key]
                key += (entry,)
                if key in seen:
                    continue
                seen.add(key)
                tax = bool(re.search(r"1099|1098|5498|tax", d["title"] + " " + d["kind"], re.I))
                docs.append(RawDoc(title=d["title"], account=d["account"], date_text=d["date"],
                                   href=d["hint"], text=f"E*TRADE {d['title']} {_human_date(d['date'])}",
                                   kind="tax" if tax else "statement", guid=d["guid"], entry=entry,
                                   unnamed=d["unnamed"]))
        _entries_only_where_shared(docs)
        # Counts only, never a label or a key (#96). By date and title, since
        # every list gives the same document under new ids. The keys of the
        # accounts with no label are counted here and go no further.
        unnamed = {(d["date"], _norm(d["title"])) for b in bodies for d in _docs_from_api(b)
                   if d["unnamed"]}
        unnamed_accounts = len({_key_account(e) for b in bodies for e in _entries_of(b)[1]
                                if isinstance(e, dict) and _key_account(e) and not _account_of(e)})
        # Keys and not one label means the account list was missed, and every
        # document would read as one of no account (review).
        missed = (ACCOUNTS_UNREAD,) if unnamed_accounts and not accounts_named() else ()
        trace.append({"note": "discovery result", "documents": len(docs),
                      "dates": sorted({d.date_text for d in docs}, reverse=True)[:60],
                      "accounts_named": accounts_named(),
                      "accounts_not_named": unnamed_accounts,
                      "documents_of_an_account_not_named": len(unnamed),
                      "pages": sum(pages for pages, _why in _PAGED),
                      "lists_of_more_than_one_page": sum(1 for pages, _why in _PAGED if pages > 1),
                      "not_read_to_the_end": [Fixed(w) for w in _listing((), _PAGED, missed).unread]})
        if docs:
            return _listing(docs, _PAGED, missed, unnamed_accounts)
    expand_all(page)
    scroll_full_page(page)
    ctrls = _bill_controls(page)
    # Without a list to read, the rows the page shows say how many documents
    # each date holds. A document found here has a title made up by this
    # file, which no row prints, so its download finds its row by date and
    # takes it only when this says the date held one row.
    rows_by_date: dict = {}
    for i in range(ctrls.count()):
        el = ctrls.nth(i)
        try:
            name = (el.get_attribute("aria-label") or el.inner_text(timeout=800) or "").strip()
        except Exception:
            name = ""
        if not is_safe_control(name):
            continue
        try:
            href = el.get_attribute("href") or ""
        except Exception:
            href = ""
        row_text = ""
        iso = parse_date(name)
        if not iso:
            try:
                row_text = el.evaluate(_ROW_OF_JS) or ""
            except Exception:
                row_text = ""
            iso = parse_date(row_text)
        if iso:
            try:
                where, around = el.evaluate(_ROW_KEY_JS) or ["", ""]
            except Exception:
                where, around = "", ""
            keys = rows_by_date.setdefault(iso, set())
            keys.add(where or "control %d" % i)
            # A container that prints more than one date is a list, not a
            # row, so it says nothing about how many documents a date holds.
            if len(_dates_in(around)) > 1:
                keys.add("crowded %d" % i)
            _LISTED[iso] = max(_LISTED.get(iso, 0), len(keys))
        if not iso or iso in seen:
            continue
        seen.add(iso)
        disp = _human_date(iso)
        tax = bool(re.search(r"1099|1098|5498|tax", name + " " + row_text, re.I))
        kind_title = "Tax Document" if tax else "Account Statement"
        docs.append(RawDoc(title=f"{kind_title} - {disp}", date_text=iso,
                           href=href if PDF_HREF_RE.search(href or "") else "",
                           text=f"E*TRADE {kind_title} {disp}", row_index=i,
                           kind="tax" if tax else "statement"))
    return _listing(docs, _PAGED)


# ---------------------------------------------------------------------------
# Which row is the document's. A date is not enough, since two documents can
# share one (#36, thirteen documents on eleven dates). A row, link or control
# is the document's when it names the document, its whole text the title, or
# the title then "PDF", the way the tester's recording named the link,
# "<title> PDF for <account>". When none names it, a row is taken by its date
# alone only when it is the only one and the lists said that date held one
# document. Anything else is refused and written down in counts.
# ---------------------------------------------------------------------------
# A row's other links hand over a different document, the inserts beside a
# statement (second survey).
_INSERT_RE = re.compile(r"insert|client\s+re", re.I)

# A document the lists gave no account, on a day they gave its title more
# than once, which download_bill refuses before anything is pressed, and
# which the docs side sends to Manual Review saying so (#96).
SHARED_WITH_NO_ACCOUNT = "the document names no account and the lists gave its title more than once that day"

# One account's documents of one title and day, two trade confirmations,
# which no row or link tells apart, so nothing is pressed for either
# (review).
TWICE_FOR_ONE_ACCOUNT = "the lists gave this account the title more than once that day"

# Fewer rows of the date naming the document, for any account, than the
# lists gave documents of its date and title. The others are on another
# page of the list, behind a filter, not drawn yet, or worded some other
# way, and the one row shown may be any of them (#96).
FEWER_NAMED = "not as many rows name this document as the lists gave"

# Why a lookup refused, in the only words that may say so.
_REFUSALS = (
    SHARED_WITH_NO_ACCOUNT,
    TWICE_FOR_ONE_ACCOUNT,
    FEWER_NAMED,
    "more than one row of this date names this document",
    "no row of this date names this document",
    "more than one row carries this date",
    "no row around this date",
    "more than one control of this date names this document",
    "no control of this date names this document",
    "more than one control carries this date",
    "the row prints another date",
    "the one control of this date may be for something else",
    "the control holds something else that could be pressed",
    "the control sits outside any one row",
    "a control on the page could not be read",
    "a row of this date could not be read",
    "the row may be another account's",
)

# Why a row may hold more than this document, in the only words that may
# say so. Any of them means only this document's own name is pressed.
_CROWDED = (
    "the row prints another date",
    "the row names another document of this date",
    "the row holds more than one box",
    "the row repeats a control",
    "the lists did not say this row holds this document alone",
    "fewer rows carry this date than the lists held documents",
)

# The account a document link names after "PDF for", the way his recording
# named the link, "<title> PDF for <account>".
_FOR_ACCOUNT_RE = re.compile(r"\s+pdf\s+for\s+.*$", re.I)


def _is_insert_text(texts, title: str = "", labels=()) -> bool:
    """Whether a control's words name an insert, once the document's own
    title is taken out. A link named "<title> PDF insert" is an insert and
    used to pass for the document's own, since it starts with the title
    (#36, review). A document whose own title is an insert's name is still
    that document.

    `texts` are what an element shows, `labels` its own aria-label or title
    attribute. Only a label has the account after "PDF for" taken off,
    since a label is one string the page gave that one element and the
    account says nothing about what it hands over. What an element shows
    can be a whole cell, the document's link and an insert link beside it,
    and taking off everything after "PDF for" there took the insert's word
    with it (review)."""
    mine = _norm(title)
    parts = []
    for word, is_label in [(w, False) for w in texts] + [(w, True) for w in labels]:
        text = _norm(word)
        if not text:
            continue
        if is_label and _names_any(text, title):
            text = _FOR_ACCOUNT_RE.sub(" pdf", text)
        if mine:
            text = text.replace(mine, " ")
        parts.append(text)
    return bool(_INSERT_RE.search(" ".join(parts)))


def _outer_of(cand: dict) -> List[dict]:
    """The links and buttons around a row walk candidate inside its row,
    each as its words, since a press on the candidate presses them too."""
    return [o for o in (cand.get("outer") or []) if isinstance(o, dict)]


def _is_insert(cand: dict, title: str = "") -> bool:
    """A row control that hands over an insert rather than the document,
    judged with the words of any link or button around it, since a press
    on it is a press on that control as well. A span reading View inside a
    link labeled as an insert passed for a bare View (review)."""
    outer = _outer_of(cand)
    return _is_insert_text([cand.get("text")] + [o.get("text") for o in outer], title,
                           [cand.get("aria")] + [o.get("aria") for o in outer])


def _names_any(name: str, title: str) -> bool:
    """Whether a control's name or text names the document `title`, for any
    account. The whole of it is the title, the title then PDF, or the title
    then PDF for an account, the way his recording named the link. It used
    to accept the title then PDF then any words at all, so a cell holding
    the document's link beside the other document's, or an insert, passed
    for the document's own name, and the words after PDF never reached the
    guard (#36, review)."""
    return _for_part(name, title) is not None


def _for_part(name: str, title: str) -> Optional[str]:
    """The account a name gives the document `title` after "PDF for", "" when
    it names the document with no account, and None when it does not name
    the document at all."""
    if not title:
        return None
    name = re.sub(r"\s+", " ", name or "").strip()
    found = re.match(r"^\s*" + escape_for_locator(title.strip()) + r"(?:\s+pdf(?:\s+for\s+(\S.*?))?)?\s*$",
                     name, re.I)
    if not found:
        return None
    return (found.group(1) or "").strip()


# The document download_bill is taking, while it takes it, as {date, title,
# account}, the title and the account as _norm writes them. Empty when it
# takes a document of no known account, and then every name is read the
# way it always was. A module's state like _LISTED, since every step that
# chooses what to press reads the name through names_title (#96).
_FOR: dict = {}


def _for_this(title: str) -> Optional[dict]:
    """{account, shared, by_label, others} when `title` is the title of the
    document of one account being taken, else None. shared says the lists
    did not give its date and title to this account alone, so another
    account may have a document of the same title that day, or the lists
    were not read. by_label says another account the lists named shows the
    same masked tail, so only the whole label tells them apart. others are
    the other accounts the lists named, each in account_form."""
    if not _FOR.get("account") or _norm(title) != _FOR.get("title"):
        return None
    mine = _FOR["account"]
    listed = _LISTED_ACCOUNTS.get((_FOR.get("date"), _FOR.get("title")), set())
    shared = {account_form(a) for a in listed} != {account_form(mine)}
    everyone = {a for accounts in _LISTED_ACCOUNTS.values() for a in accounts if a} | {mine}
    return {"account": mine, "shared": shared,
            "by_label": account_form(mine) in twin_labels(everyone),
            "others": {account_form(a) for a in everyone} - {account_form(mine)}}


def _same_account(named: str, held: dict) -> bool:
    """Whether the account a name gives after "PDF for" is the account of
    the document being taken. By the masked tails the two show, since a
    link can write the account another way than the list does, "Invented
    Brokerage - 1111" or in capitals beside the list's "Invented Brokerage
    -1111", and by the whole label, in account_form, when neither shows a
    tail or another account the lists named shows the same tail. One
    showing a tail and the other none is not the same (review of #96)."""
    if held["by_label"]:
        return account_form(named) == account_form(held["account"])
    mine, theirs = account_tails(held["account"]), account_tails(named)
    if mine or theirs:
        return mine == theirs
    return account_form(named) == account_form(held["account"])


def _row_is_this_accounts(words, row_texts, title: str) -> bool:
    """Whether a control whose words are `words`, in a row that says
    `row_texts`, may be this account's document. A control naming the
    document for this account may. Any other, one naming the document with
    no account, a View or a box, may only when nothing the row says shows
    another account, neither a masked tail other than this account's nor
    the label of another account the lists named. The lists can leave out
    another account's statement of the day, and its row, its link naming
    no account, was taken for this one's (review of #96). A row whose words
    could not be read may be anyone's, and so may one when another account
    shows this account's tail. Outside a download of one account, every
    control may."""
    held = _for_this(title)
    if held is None:
        return True
    for word in words or ():
        found = _for_part(word, title)
        if found and _same_account(found, held):
            return True
    if row_texts is None or held["by_label"]:
        return False
    pieces = [p for t in row_texts if isinstance(t, str) for p in re.split(r"[\n\t|]+", t) if p.strip()]
    if any(account_form(p) in held["others"] for p in pieces):
        return False
    shown = {tail for p in pieces for tail in account_tails(p)}
    return shown <= set(account_tails(held["account"]))


def names_title(name: str, title: str) -> bool:
    """Whether a control's name or text names the document `title` (see
    _names_any). While download_bill takes a document of one account, a
    name that gives another account after "PDF for" is not its name, and
    when another account may have a document of the same title and day, a
    name is the document's only when it gives this account, exactly, as
    "<title> PDF for <account>". Two accounts' statements of one day used to
    be one document here, and of two rows naming it the download refused
    both, or took whichever one the page showed (#96)."""
    found = _for_part(name, title)
    if found is None:
        return False
    held = _for_this(title)
    if held is None:
        return True
    if not found:
        return not held["shared"]
    return _same_account(found, held)


def _account_ok(words, title: str) -> bool:
    """Whether a control may be this document's by every word it carries,
    what it shows and its labels together, while download_bill takes a
    document of one account. No word may name the document for another
    account, and when another account may have a document of the same title
    and day, one word has to name it for this account exactly. A link
    showing the title with a label for another account showed the title
    alone, which reads as this document's name (#96). Outside a download of
    one account, every control may."""
    held = _for_this(title)
    if held is None:
        return True
    exact = False
    for word in words:
        found = _for_part(word, title)
        if not found:
            continue
        if not _same_account(found, held):
            return False
        exact = True
    return exact or not held["shared"]


def _js_title(title: str) -> list:
    """The title as the page scripts take it, with the account, whether it
    is shared and whether only its whole label tells it apart, while
    download_bill takes a document of one account, so a script reads a
    name the way names_title does."""
    held = _for_this(title)
    return [title or "", held["account"] if held else "", bool(held and held["shared"]),
            bool(held and held["by_label"])]


def _title_name_re(title: str):
    """_names_any as a pattern, for a locator's accessible name."""
    return re.compile(r"^\s*" + escape_for_locator(title.strip()) + r"(\s+pdf(\s+for\s+\S.*)?)?\s*$", re.I)


def _guard_word(word: str, title: str = "") -> str:
    """One of an element's words as the guard reads it. A word that names
    the document loses the account after "PDF for", which is the account's
    name and not what the link does, whichever account it is. Every other
    word is read whole."""
    w = re.sub(r"\s+", " ", word or "").strip()
    if w and _names_any(w, title):
        w = _FOR_ACCOUNT_RE.sub(" PDF", w)
    return w


def _guard_allows(words, title: str = "") -> bool:
    """Whether the guard lets an element be pressed, judged on every word it
    carries, what it shows and its label alike. The download used to judge
    a named link by the document's title alone, so the link's own words
    never reached the guard (#36, review). With no words, the title is
    judged. Every press path runs through this or is_safe_control, and
    both refuse the forbidden words, the core's settings and sign-in words,
    and the words that sign out."""
    seen = [w for w in (_guard_word(w, title) for w in words) if w]
    for w in seen or [title or ""]:
        if FORBIDDEN_CONTROL_RE.search(w) or SETTINGS_CONTROL_RE.search(w) or AUTH_CONTROL_RE.search(w) \
                or SESSION_CONTROL_RE.search(w):
            return False
    return True


# The words a control may say when it does not name the document and is
# still pressed for it, View, Download, Open, Print or PDF, with statement
# or document after them. Anything else names some other thing, a notice or
# another document.
_ACTION_WORDS = {"view", "download", "open", "print", "pdf"}
_PLAIN_WORDS = _ACTION_WORDS | {"statement", "document", "file", "the", "this", "as", "or", "and", "/", "&", ","}


def _says_only_an_action(cand: dict) -> bool:
    """Whether a row control's words are a bare action, View, Download PDF,
    Open statement, and nothing that names what it opens."""
    words = [w for w in (cand.get("text"), cand.get("aria")) if _norm(w)]
    if not words:
        return False
    for w in words:
        toks = re.findall(r"[a-z0-9]+|[^\sa-z0-9]", _norm(w))
        if not toks or toks[0] not in _ACTION_WORDS or any(t not in _PLAIN_WORDS for t in toks):
            return False
    return True


def _date_text_re(iso_date: str):
    """The date the way a row prints it, 07/31/26 or 07/31/2026, and not as
    a piece of a longer number or date."""
    y, m, d = iso_date.split("-")
    forms = [f"{m}/{d}/{y[2:]}", f"{m}/{d}/{y}"]
    return re.compile(r"(^|[^\d/])(" + "|".join(escape_for_locator(f) for f in forms) + r")($|[^\d/])")


def _dates_in(text: str) -> set:
    """Every date a piece of text carries, as YYYY-MM-DD."""
    out = set()
    for pattern, _kind in DATE_PATTERNS:
        for m in pattern.finditer(text or ""):
            iso = parse_date(m.group(0))
            if iso:
                out.add(iso)
    return out


def _refuse(trace: Optional[list], way: str, why: str, iso_date: str,
            carries: int, naming: int) -> None:
    """Write down that a lookup would have had to guess, in fixed words and
    counts."""
    log.info("not sure which %s is the document of %s: %s", way, iso_date, why)
    if trace is not None:
        trace.append({"note": "not sure which is this document, so nothing was pressed",
                      "way": way, "why": why if why in _REFUSALS else "unrecognized",
                      "carrying_the_date": int(carries), "naming_the_document": int(naming),
                      "listed_that_day": int(_LISTED.get(iso_date, 0))})


def _control_for(page, iso: str, title: str = "", trace: Optional[list] = None):
    """The control for the document dated `iso` and titled `title`, or
    None. Every visible control of that date is looked at, inserts left
    out, and the one that names the document is taken, once every word it
    carries has passed the guard. The name it comes back with is the one
    the guard read, the account after "PDF for" taken off. A control whose
    row text carries more than one date sits in a list rather than a row,
    so its date says nothing.

    Only visible controls count, so a hidden copy of the list cannot make
    one document look like two. The first eighty are read, and a document
    whose control lies past them goes on to the row walk, which chooses the
    same way.

    When no control names the document, the one control of the date is
    taken only when the lists held this document alone that day and it is
    a bare action, View, Download, Open, Print or PDF, or its row does not
    print the title and holds no bare action and no other control that
    says something else (_may_press_unnamed, the rule the other steps
    follow). It used to be taken on the lists' count alone, before the row
    walk ever looked, so a "Privacy Notice PDF" link beside the statement's
    own link, or beside its title printed as text, was saved as the
    statement (#36, review). Whatever this takes has to press only itself,
    every pressable element inside it naming the document too, and has to
    sit in one row, the nearest element above it that prints a date
    holding one element that prints a date. Otherwise it refuses in fixed
    words and the row walk decides.

    The page's own Download is never taken here. It hands over every
    ticked document, and it was taken as "the one control of the date",
    the whole page being the nearest element around it that printed a
    date, and pressed with none of the checks the box path makes (review).
    It is pressed only through _tick_and_download. Each control is held as
    the element itself from the check to the press. It was found again by
    its place among the page's controls when pressed, so a list that
    changed in between moved the press onto another document (review).

    A control that could not be read, one that did not answer in time or
    whose words or row could not be had, stops the choosing, and the row
    walk decides. It used to be passed over as if it were not on the page,
    so with none answering nothing was written down (CI run 36792330947),
    and of two controls naming the document the one that answered would be
    pressed as the only one."""
    ctrls = _bill_controls(page)
    matches = []
    unread = 0
    for i in range(min(ctrls.count(), 80)):
        try:
            el = ctrls.nth(i).element_handle(timeout=2000)
        except Exception:
            unread += 1
            continue
        if el is None:
            unread += 1
            continue
        try:
            if not el.is_visible():
                continue
            aria = el.get_attribute("aria-label") or ""
            text = el.evaluate(_WORDS_JS) or ""
        except Exception:
            unread += 1
            continue
        name = (aria or text).strip()
        if _DOWNLOAD_BUTTON_RE.match(name) or _DOWNLOAD_BUTTON_RE.match(text):
            continue
        found = parse_date(name)
        if not found:
            try:
                row_text = el.evaluate(_ROW_OF_JS) or ""
            except Exception:
                unread += 1
                continue
            if len(_dates_in(row_text)) > 1:
                continue
            found = parse_date(row_text)
        if found == iso and not _is_insert_text((text,), title, (aria,)):
            matches.append((el, name, (aria, text)))
    if unread:
        _refuse(trace, "control", "a control on the page could not be read", iso, len(matches),
                sum(1 for m in matches if any(names_title(w, title) for w in m[2])))
        return None, ""
    if not matches:
        return None, ""
    if title:
        # A control naming this title for another account is that account's
        # document, whatever else it shows (#96).
        named = [m for m in matches if any(names_title(w, title) for w in m[2])
                 and _account_ok(m[2], title) and _guard_allows(m[2], title)]
        if len(named) == 1:
            # Every document the lists gave its date and title has to have a
            # row here with a control naming it, whatever its account, or
            # the one naming this account's may be another's (#96).
            listed = _listed_docs(iso, title)
            if listed > 1:
                rows, rows_unread = _rows_naming_any(matches, title)
                if rows_unread:
                    _refuse(trace, "control", "a control on the page could not be read", iso, len(matches), 1)
                    return None, ""
                if rows < listed:
                    _refuse(trace, "control", FEWER_NAMED, iso, len(matches), rows)
                    return None, ""
            around = _around(named[0][0], title)
            if not around:
                _refuse(trace, "control", "a control on the page could not be read", iso, len(matches), 1)
                return None, ""
            if not around.get("clean"):
                _refuse(trace, "control", "the control holds something else that could be pressed",
                        iso, len(matches), 1)
                return None, ""
            if not _in_one_row(around):
                _refuse(trace, "control", "the control sits outside any one row", iso, len(matches), 1)
                return None, ""
            if not _row_is_this_accounts(named[0][2], around.get("texts"), title):
                _refuse(trace, "control", "the row may be another account's", iso, len(matches), 1)
                return None, ""
            return named[0][0], _guard_word(named[0][1], title)
        if len(named) > 1:
            _refuse(trace, "control", "more than one control of this date names this document",
                    iso, len(matches), len(named))
            return None, ""
    if len(matches) == 1 and _alone_that_day(iso, title) and _account_ok(matches[0][2], title) \
            and not _names_another(matches[0][2], title, iso) and _guard_allows(matches[0][2], title):
        el, name, (aria, text) = matches[0]
        mine = {"text": (text or "").strip(), "aria": (aria or "").strip()}
        around = _around(el, title)
        if not around:
            _refuse(trace, "control", "a control on the page could not be read", iso, 1, 0)
            return None, ""
        if not around.get("clean"):
            _refuse(trace, "control", "the control holds something else that could be pressed", iso, 1, 0)
            return None, ""
        if not _in_one_row(around):
            _refuse(trace, "control", "the control sits outside any one row", iso, 1, 0)
            return None, ""
        if not _row_is_this_accounts(matches[0][2], around.get("texts"), title):
            _refuse(trace, "control", "the row may be another account's", iso, 1, 0)
            return None, ""
        if _says_only_an_action(mine) or _lone_control_may_be_pressed(around, iso, title, mine):
            return el, name
        _refuse(trace, "control", "the one control of this date may be for something else", iso, 1, 0)
        return None, ""
    _refuse(trace, "control", "no control of this date names this document" if title
            else "more than one control carries this date", iso, len(matches), 0)
    return None, ""


def _rows_naming_any(matches, title: str) -> Tuple[int, int]:
    """How many rows hold a control of `matches` naming the document, for
    any account, each row counted once however many such controls it
    holds, and how many of those controls' rows could not be read. A row
    that could not be read may have been one of them, so the caller takes
    nothing then."""
    rows, unread = set(), 0
    for el, _name, words in matches:
        if not any(_names_any(w, title) for w in words):
            continue
        try:
            where = (el.evaluate(_ROW_KEY_JS) or [""])[0]
        except Exception:
            unread += 1
            continue
        rows.add(where or "control %d" % len(rows))
    return len(rows), unread


def _around(el, title: str) -> dict:
    """What _AROUND_CONTROL_JS says of one control, whether it presses only
    itself and what the row around it says, or {} when that could not be
    read, which every caller takes as a reason not to press it."""
    try:
        got = el.evaluate(_AROUND_CONTROL_JS, _js_title(title))
    except Exception as e:
        log.info("could not read around a control: %s", type(e).__name__)
        return {}
    return got if isinstance(got, dict) else {}


def _in_one_row(around: dict) -> bool:
    """Whether a control sits in one row, the nearest element above it that
    prints a date holding exactly one element that prints a date."""
    return bool(around.get("row")) and around.get("dated") == 1


# What a control says, its visible text, or for a button drawn as an input
# its value, since an input has no text of its own.
_WORDS_JS = r"""el => {
  const tag = el.tagName.toLowerCase();
  if (tag === 'input') {
    const type = (el.getAttribute('type') || '').toLowerCase();
    if (type === 'image') return el.getAttribute('alt') || '';
    return ['button', 'submit', 'reset'].includes(type) ? (el.getAttribute('value') || '') : '';
  }
  return el.innerText || '';
}"""


def _lone_control_may_be_pressed(around: dict, iso: str, title: str, mine: dict) -> bool:
    """Whether the one control of a date, which neither names the document
    nor is a bare action, may be pressed for it, by the rule every step
    follows (_may_press_unnamed). Its row, the nearest element above it
    that prints a date, has to print this date and no other, and then it
    may only when the row's words do not carry the title anywhere and it
    is the only control there that says something other than a bare
    action. An insert is not counted, since it is never pressed and says
    what it is, and neither is a control with no words at all."""
    if not around.get("row"):
        return False
    texts = [t for t in (around.get("texts") or []) if isinstance(t, str)]
    if _dates_in(" | ".join(texts)) != {iso}:
        return False
    others = []
    for c in around.get("controls") or []:
        if not isinstance(c, dict):
            continue
        c = {"text": str(c.get("text") or "").strip(), "aria": str(c.get("aria") or "").strip()}
        if not (c["text"] or c["aria"]) or _is_insert(c, title):
            continue
        others.append(c)
    names_it = any(_mentions(t, title) for t in texts)
    return _may_press_unnamed([mine] + others, names_it)[0]


def _fetch_pdf(page, href: str, zip_ok: bool = False) -> Optional[bytes]:
    """A PDF link fetched from inside the signed-in page, cookies and all.
    The fetching is the core's, the hosts are this app's."""
    return _core_fetch_pdf(page, href, is_safe_url, zip_ok=zip_ok)


def _take_same_tab(page, start_url: str, out_path: Path, trace) -> bool:
    """A PDF the click opened in this very tab. The core does the reading,
    this app's guard decides which addresses it may read. What the core
    says goes into a list of its own, and only its shape reaches the
    trace, since the trace is a file a tester attaches."""
    moved_to = page.url or ""
    said: list = []
    ok = _core_take_same_tab(page, start_url, out_path, said, is_safe_url)
    if trace is not None and said:
        trace.append({"note": "the tab moved", "url": mask_href(moved_to),
                      "type": _kind_of(str(said[0].get("content_type") or ""))})
    return ok


_SHORT_TEXTS_JS = r"""() => {
  const out = new Set();
  const walk = (el) => {
    for (const c of el.children) {
      if (c.shadowRoot) walk(c.shadowRoot);
      const t = (c.innerText || '').trim().replace(/\s+/g, ' ');
      if (t && t.length <= 30 && c.children.length <= 2) {
        const r = c.getBoundingClientRect();
        if (r.width > 0 && r.height > 0) out.add(t);
      }
      walk(c);
    }
  };
  walk(document.body);
  return Array.from(out).slice(0, 400);
}"""


def _short_visible_texts(page) -> set:
    """Every short visible text on the page, whatever element carries it.
    A period picker's years were not buttons or menu items (#36)."""
    try:
        return set(page.evaluate(_SHORT_TEXTS_JS) or [])
    except Exception:
        return set()


def _click_text(page, text: str, unsure: Optional[list] = None) -> bool:
    """Click the visible element whose whole text is `text`, by role
    first, then by text alone. The text has passed is_date_filter.

    A candidate that is hidden, or will not scroll into view, is passed
    over for the next one (#119). A click that raised is the last one
    tried, since it may have reached the page, and `unsure` then gets the
    text, so nothing else is pressed for it, another element of the same
    words included (review of #119, the rule of pressing.press_once)."""
    pat = re.compile("^\\s*" + escape_for_locator(text) + "\\s*$", re.I)

    def candidates():
        for role in ("menuitem", "option", "radio", "menuitemradio", "button", "link", "tab"):
            try:
                opt = page.get_by_role(role, name=pat)
                many = min(opt.count(), 10)
            except Exception:
                continue
            for i in range(many):
                yield opt.nth(i)
        try:
            loc = page.get_by_text(pat)
            many = min(loc.count(), 20)
        except Exception:
            return
        for i in range(many):
            yield loc.nth(i)

    for el in candidates():
        try:
            if not el.is_visible():
                continue
            el.scroll_into_view_if_needed(timeout=1000)
        except Exception:
            continue
        try:
            el.click(timeout=5000)
        except Exception:
            if unsure is not None:
                unsure.append(text)
            return False
        return True
    return False


_SECOND_STEP_RE = re.compile(
    r"^\s*(download|download\s+(pdf|now|file|statement|document)|save|save\s+(as\s+)?pdf|"
    r"(regular|standard|full|detailed)\s+pdf|pdf|view\s*/\s*print\s+pdf|print|open\s+pdf)\s*$", re.I)


# ---------------------------------------------------------------------------
# What the download may write down. download-attempt.json goes on a public
# issue, so it is built from what may leave, fixed words, counts, the kind of
# an address and the shape of a text, and never from the page's text with
# parts scrubbed out. The row outline used to carry each element's own text,
# the account column among it (#36, review).
# ---------------------------------------------------------------------------
_TAG_RE = re.compile(r"[a-z][a-z0-9-]{0,40}")
_CLASS_RE = re.compile(r"[A-Za-z][A-Za-z_-]{0,40}\d?")
_WORD_RE = re.compile(r"[a-z][a-z-]{0,30}")
_METHODS = {"GET", "POST", "PUT", "HEAD", "OPTIONS"}
_CANDIDATE_KINDS = {"title", "control", "checkbox", "pointer"}
# Words a document row may be quoted saying. Any other text is named by
# its shape.
_ROW_WORDS = {w.lower(): w for w in (
    "View", "Download", "PDF", "Print", "Open", "Insert", "Inserts",
    "Statement", "Statements", "Document", "Documents", "Tax Documents",
    "Trade Confirmations", "Confirmations", "Select", "Account", "Date",
    "Document type", "Actions", "More")}


# The only parameter names, of an address or of a request's body, that may
# leave, the ones E*TRADE was seen to use. RequestID and SeqID ride on every
# API call and n on the sign-in check, in the tester's failure file (#36),
# and TimeFrame and pageNum are the keys of the searchItems body as the
# app's own tests model it. A name was judged by its shape, so "JohnSmith"
# left as written (review). Every other name is written as one #, so how
# many there were still shows.
_PARAM_NAMES = {n.lower(): n for n in ("RequestID", "SeqID", "n", "TimeFrame", "pageNum")}


def _param_names(names) -> List[str]:
    """Parameter names as they may leave, sorted, each one on the list as
    E*TRADE spells it and each other one as #."""
    return sorted(_PARAM_NAMES.get(str(n).lower(), "#") for n in names)


# The only words of an address path or route that may leave, the ones
# E*TRADE's own pages were seen to use (#36). Judging a piece by its shape
# let a plain word through whatever it said, so a file named for its owner
# would have left as written. Anything not on this list is #.
_ADDRESS_WORDS = frozenset((
    "etx", "pxy", "accountdocs", "documents", "etaz", "api", "adsal",
    "v1", "v2", "v3", "searchitems", "login", "sar", "docs", "view",
    "download", "neologger.json",
))
# A file keeps the kind its name ends in and nothing else.
_ADDRESS_EXTENSIONS = (".pdf", ".json", ".js", ".html", ".htm")


def _address_word(part: str) -> str:
    """One piece of an address path or route as it may leave, a word from
    _ADDRESS_WORDS, # and a file's ending, or #."""
    low = (part or "").lower()
    if low in _ADDRESS_WORDS:
        return part
    for ext in _ADDRESS_EXTENSIONS:
        if low.endswith(ext):
            return "#" + ext
    return "#"


def mask_href(url: str) -> str:
    """An address as it may leave. Whether it is E*TRADE's, the words of its
    path and of its route after # that are on the list E*TRADE was seen to
    use, a file's ending, and the names of its parameters that are on
    _PARAM_NAMES, never their values. Anything else in it is #."""
    from urllib.parse import urlsplit, parse_qsl
    u = (url or "").strip()
    if not u:
        return ""
    low = u.lower()
    for scheme in ("javascript:", "blob:", "data:", "about:"):
        if low.startswith(scheme):
            return scheme[:-1]
    try:
        parts = urlsplit(u)
        keys = _param_names(k for k, _v in parse_qsl(parts.query, keep_blank_values=True))
    except ValueError:
        return "unreadable"
    if parts.scheme or parts.netloc:
        if not is_safe_url(u):
            return "elsewhere"
        where = "etrade"
    else:
        where = "relative"

    def words(path: str) -> str:
        return "/".join(_address_word(p) for p in path.split("/") if p)[:160]

    out = where + ":/" + words(parts.path)
    if keys:
        out += "?" + "&".join(keys[:12])
    if parts.fragment:
        out += "#/" + words(parts.fragment.split("?")[0])
    return out


def _text_shape(text: str, title: str = "") -> str:
    """Page text as it may leave. The document's title and the words this
    file knows are named, a date or a number by its shape, and anything
    else by how many words it has."""
    t = re.sub(r"\s+", " ", text or "").strip()
    if not t:
        return ""
    if _names_any(t, title):
        return "<the title>"
    known = _ROW_WORDS.get(t.lower())
    if known:
        return known
    if parse_date(t):
        return "<date>"
    if re.fullmatch(r"[\d\s#*.,/()$+-]+", t):
        return "<number>"
    return "<text of %d words>" % min(len(t.split()), 99)


def _href_kind(href: str) -> str:
    """What kind of address a link holds, in words from this file."""
    h = (href or "").strip()
    if not h:
        return ""
    low = h.lower()
    if low.startswith("#"):
        return "hash"
    if low.startswith("javascript:"):
        return "script"
    if low.startswith("blob:"):
        return "blob"
    from urllib.parse import urlsplit
    try:
        pdf = urlsplit(h).path.lower().endswith(".pdf")
    except ValueError:
        return "unreadable"
    if low.startswith("https://") or low.startswith("http://"):
        kind = "etrade" if is_safe_url(h) else "elsewhere"
    else:
        kind = "relative"
    return kind + (" pdf" if pdf else "")


def _outline_line(part: dict, title: str = "") -> str:
    """One element of the document's row, as it may leave. Its tag, classes
    without long numbers, role and type when they are plain words, and the
    shape of its text, its label and its address."""
    tag = str(part.get("tag") or "")
    tag = tag if _TAG_RE.fullmatch(tag) else "?"
    cls = [c for c in (part.get("cls") or [])[:2] if isinstance(c, str) and _CLASS_RE.fullmatch(c)]
    role = str(part.get("role") or "")
    kind = str(part.get("type") or "").lower()
    aria = _text_shape(str(part.get("aria") or ""), title)
    own = _text_shape(str(part.get("own") or ""), title)
    href = _href_kind(str(part.get("href") or ""))
    try:
        depth = max(0, min(int(part.get("depth") or 0), 8))
    except (TypeError, ValueError):
        depth = 0
    return ("  " * depth + ("~" if part.get("shadow") else "") + tag
            + ("." + ".".join(cls) if cls else "")
            + (" [%s]" % role if _WORD_RE.fullmatch(role) else "")
            + (" type=" + kind if _WORD_RE.fullmatch(kind) else "")
            + (" aria=" + aria if aria else "")
            + (" = " + own if own else "")
            + (" href=" + href if href else "")
            + (" {pointer}" if part.get("pointer") else "")
            + (" {shadow}" if part.get("root") else ""))


def _fixed_word(text: str) -> str:
    """A control's words when they are one of the finishing words this file
    knows, "Download" or "Save as PDF", else nothing."""
    t = re.sub(r"\s+", " ", text or "").strip()
    return t.lower() if _SECOND_STEP_RE.fullmatch(t) else ""


def _second_step(page, appeared: set, place, trace: Optional[list] = None):
    """A control the click revealed whose text says it finishes a download,
    once it has passed the guard and sits where the press at `place` put
    it, or None. The choosing is the core's, the words this provider uses
    and the guard are this app's."""
    return _core_second_step(page, appeared, _SECOND_STEP_RE, is_safe_control, place, trace)


# RECORDED (#36, 0.38.0). Pressing a document's link makes the page POST to
# /etaz/api/adsal/accountdocs/<...>/<n>.pdf, and the answer is JSON, 200, with
# the PDF inside it as base64 text, which the page then hands to the browser
# as a download. Two of four statements reached the app that way and two did
# not. So the PDF is also read straight out of that JSON answer, which ties
# it to the very request this attempt's press made.
_DOC_ANSWER_RE = re.compile(r"/accountdocs/.*\.pdf$", re.I)
# How a file begins once written as base64, "%PDF-" for a PDF. Only a PDF is
# ever saved. The other two just name what an answer held when it held none.
_ENCODED_STARTS = (("JVBERi0", "pdf"), ("UEsDB", "zip"), ("H4sI", "gzip"))
# A data address can wrap the base64, "data:application/pdf;base64,".
_DATA_ADDRESS_RE = re.compile(r"^data:[a-z]+/[a-z0-9.+-]+;base64,", re.I)
_BASE64_RE = re.compile(r"[A-Za-z0-9+/]+={0,2}")


def _json_texts(value, depth: int = 0):
    """Every text in a JSON answer, six levels down and two hundred wide."""
    if depth > 6:
        return
    if isinstance(value, str):
        yield value
        return
    if isinstance(value, dict):
        items = list(value.values())
    elif isinstance(value, list):
        items = value
    else:
        return
    for item in items[:200]:
        yield from _json_texts(item, depth + 1)


def _bare(text: str) -> str:
    """A text without its whitespace or a data address around it."""
    return _DATA_ADDRESS_RE.sub("", re.sub(r"\s+", "", text))


def _pdf_in_json(value) -> Optional[bytes]:
    """The PDF carried inside a JSON answer as base64 text, found by what it
    starts with rather than by the field's name, or None."""
    for text in _json_texts(value):
        text = _bare(text)
        if not text.startswith("JVBERi0") or len(text) > 60_000_000:
            continue
        try:
            # Strict, so text that only starts like a PDF is not decoded
            # into something that also only starts like one.
            data = intake.decode(text, validate=True)
        except Exception:
            continue
        if data[:5] == b"%PDF-" and b"%%EOF" in data[-2048:]:
            return data
    return None


def _json_answer_shape(value) -> dict:
    """What a JSON answer that held no PDF did hold, for the attempt file,
    in counts and fixed words. Its longest text is given by its length,
    whether it is base64, and which kind of file its start would encode,
    never by what it says."""
    texts = [_bare(t) for t in _json_texts(value)]
    longest = max(texts, key=len, default="")
    begins = next((word for start, word in _ENCODED_STARTS if longest.startswith(start)),
                  "other" if longest else "nothing")
    return {"texts": len(texts), "longest": len(longest),
            "base64": bool(_BASE64_RE.fullmatch(longest)), "begins": begins}


# What _catch_pdf adds to the list of controls pressed for a document when
# the page had its control turned off, so nothing was pressed
# (pressing.TurnedOff). A page's own words never hold a NUL.
_TURNED_OFF = "\x00turned off"


def _catch_pdf(page, el, label: str, out_path: Path, trace: Optional[list] = None,
               dl_dir=None, pressed: Optional[list] = None,
               unsure: Optional[list] = None) -> bool:
    """Click `el` and save whatever PDF the site produces, a file landing
    in `dl_dir`, a download event, a PDF response, a new tab, this tab
    moving to the document, or a second control the click revealed. A PDF
    answer, or a JSON answer carrying one, is taken only when its request
    was made during this attempt, and for a redirect, the request it came
    from. A download event or a file landing in `dl_dir` is not tied to the
    click that way yet, so such an answer wins over them.
    `trace` collects what happened, the click's own outcome included.
    `pressed`, when given, is one list for the whole document and gets the
    words of each control pressed. A control the page has turned off leaves
    the document only when nothing was pressed for it before, since what an
    earlier press began may still bring its PDF, and then the run stops as
    it did. `unsure` is given the label when the press may have been made
    and nothing came, so nothing more is pressed for this document."""
    ctx = page.context
    got: dict = {}
    downloads: list = []
    # Answers to a request this press made, from its tab or one it opened,
    # that called themselves a PDF and read empty. Asked for once more only
    # when nothing else brings the document (capture.ask_again).
    empty_answers: list = []
    made_here = _RequestsSince(page, ctx.pages)
    asked: list = []
    start_url = page.url or ""

    def on_download(dl):
        downloads.append(dl)

    def on_request(req):
        asked.append(req)

    def on_response(res):
        try:
            url = res.url or ""
            if not is_safe_url(url):
                return
            ct = (res.headers.get("content-type") or "").lower()
            if trace is not None and ("json" in ct or "pdf" in ct or "octet" in ct or "zip" in ct):
                trace.append({"status": int(res.status), "type": _kind_of(ct), "url": mask_href(url)})
            if got:
                return
            carried = "json" in ct and bool(_DOC_ANSWER_RE.search(urlsplit(url).path or ""))
            if "pdf" in ct or "octet" in ct or carried:
                # Only an answer to a request made during this attempt is
                # this document. Runs now take several documents in turn,
                # and a late answer to the last document's click used to
                # be saved under this one's name (#36, review). A redirect
                # is a new request, so an earlier request redirected during
                # this attempt passed too. The request it came from is the
                # one that has to be this attempt's (review).
                req = res.request
                for _hop in range(20):
                    before_hop = getattr(req, "redirected_from", None)
                    if before_hop is None:
                        break
                    req = before_hop
                if not any(r is req for r in asked):
                    if trace is not None:
                        trace.append({"note": "a PDF answering an earlier request was left alone",
                                      "type": _kind_of(ct)})
                    return
                if carried:
                    try:
                        answer = whole_json(res.json())
                    except Exception:
                        if trace is not None:
                            trace.append({"note": "its JSON answer could not be read"})
                        return
                    inside = _pdf_in_json(answer)
                    if inside:
                        got["body"] = inside
                        if trace is not None:
                            trace.append({"note": "the PDF came inside its JSON answer"})
                    elif trace is not None:
                        trace.append(dict({"note": "its JSON answer held no PDF"},
                                          **_json_answer_shape(answer)))
                    return
                try:
                    body = intake.body(res)
                except intake.TooLarge:
                    # Larger than a document may be, and never asked again.
                    body = b""
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

    ctx.on("request", on_request)
    ctx.on("response", on_response)
    page.on("download", on_download)
    before = set(ctx.pages)
    seen = _snapshot(dl_dir)
    controls_before = _control_texts(page)

    def landed() -> bool:
        # An answer to this attempt's own request comes first. A download
        # event is not tied to the click, so an earlier press's late
        # download must not win over it.
        if got.get("body"):
            out_path.write_bytes(got["body"])
            return True
        # Pointed at a folder, the browser can save the only copy there and
        # leave the event's own file empty, so that file is taken rather than
        # the document asked for a second time (capture.take_download).
        # The event is not tied to the click, so its file is taken only
        # when it is the one document that arrived, and otherwise this
        # attempt's own answer below decides.
        if downloads and _take_download(downloads[0], dl_dir, seen, out_path, zip_ok=True):
            return True
        if got.get("refetch"):
            try:
                # This address answered the press directly, so asking it
                # again needs no redirect, and one would take the
                # browser's cookies wherever it led.
                resp = page.context.request.get(got.pop("refetch"), max_redirects=0,
                                                timeout=60000)
                body = intake.body(resp) if resp.ok else b""
                if _is_document(body, zip_ok=True):
                    out_path.write_bytes(body)
                    return True
            except Exception:
                pass
        return _take_new_pdf(dl_dir, seen, out_path, zip_ok=True)

    def wait_for_pdf(seconds: int) -> bool:
        for _ in range(seconds):
            if landed():
                return True
            page.wait_for_timeout(1000)
        return landed()

    try:
        try:
            el.scroll_into_view_if_needed(timeout=4000)
        except Exception:
            pass
        # Where the press is made, read just before it, so a control the
        # press reveals is taken only where the press put it
        # (controls.second_step).
        place = _place_of(page, el)
        # Playwright's own press, and through the page only when nothing
        # covered the control, its press never reached the page and nothing
        # it should bring came. What cannot be told stops the run, and the
        # control is never pressed twice (pressing.press_once).
        try:
            outcome = pressing.press_once(
                page, el, what="the control for this document", words=_words(),
                guard=is_safe_control, dl_dir=dl_dir,
                brought=lambda: bool(downloads or got or (_control_texts(page) - controls_before)))
        except pressing.TurnedOff:
            # Something was pressed for this document already, and what it
            # began may still bring a PDF, so the run stops there as it did.
            if pressed and any(not p.startswith("\x00") for p in pressed):
                raise
            # The page has turned the control off, so nothing was pressed and
            # nothing this document brings can come. No second step is looked
            # for, and the document is left for review and the next run while
            # the run goes on (pressing.TurnedOff).
            if trace is not None:
                trace.append({"note": "the control is turned off on the page, so nothing was pressed"})
            if pressed is not None:
                pressed.append(_TURNED_OFF)
            return False
        if trace is not None:
            if outcome.error is None:
                trace.append({"note": "clicked"})
            else:
                trace.append({"note": "click failed",
                              "error": type(outcome.error).__name__})
            if outcome.how == pressing.MADE:
                trace.append({"note": "the press reached the page although it raised, "
                                      "so it was not made again"})
            elif outcome.how == pressing.THROUGH_THE_PAGE and outcome.page_error is None:
                trace.append({"note": "clicked through the DOM instead"})
            elif outcome.how == pressing.THROUGH_THE_PAGE:
                trace.append({"note": "DOM click failed too", "error": type(outcome.page_error).__name__})
        if pressed is not None and outcome.how != pressing.GONE:
            pressed.append(label)
        if outcome.how == pressing.GONE:
            # Nothing was pressed, so nothing this document brings can come,
            # and whatever the page shows now is not this press's. No second
            # step is looked for, and the document is left for another run.
            if trace is not None:
                trace.append({"note": "the control left the page before it was pressed"})
            return False
        if wait_for_pdf(10):
            return True
        if _take_same_tab(page, start_url, out_path, trace):
            return True
        if _take_new_tab(page, [p for p in ctx.pages if p not in before], out_path):
            return True
        # The press through the page raised, so it may have been made, and
        # nothing more is pressed (pressing.Pressed). No second step is
        # looked for, and what the press brought is still waited for.
        unsure_press = outcome.page_error is not None
        if unsure_press and trace is not None:
            trace.append({"note": "the press through the page raised, so nothing more is pressed"})
        if unsure_press and unsure is not None:
            unsure.append(label)
        appeared = _control_texts(page) - controls_before
        if trace is not None:
            trace.append({"note": "after the click", "url": mask_href(page.url or ""),
                          "appeared": len(appeared),
                          "finishing_words": sorted({_fixed_word(t) for t in appeared} - {""})[:10],
                          "new_tabs": len([p for p in ctx.pages if p not in before])})
        step, step_label = (None, "") if unsure_press else _second_step(page, appeared, place, trace)
        if step is not None:
            try:
                step.click(timeout=8000)
                if trace is not None:
                    trace.append({"note": "second step clicked", "words": _fixed_word(step_label) or "other"})
            except Exception as e:
                if trace is not None:
                    trace.append({"note": "second step click failed", "words": _fixed_word(step_label) or "other",
                                  "error": type(e).__name__})
                # A click that raised may have been made, so nothing more is
                # pressed for this document (review of 0.45.0's fixes).
                if unsure is not None:
                    unsure.append(step_label)
            if wait_for_pdf(20):
                return True
            if _take_same_tab(page, start_url, out_path, trace) or \
                    _take_new_tab(page, [p for p in ctx.pages if p not in before], out_path):
                return True
        if wait_for_pdf(15):
            return True
        if _take_new_tab(page, [p for p in ctx.pages if p not in before], out_path):
            return True
        # Nothing else brought it, so the one answer that read empty is asked
        # for once more (capture.ask_again).
        if _ask_again(page, empty_answers, out_path, is_safe_url, zip_ok=True):
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
            ctx.remove_listener("request", on_request)
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


def _named_link(row, title: str, trace: Optional[list] = None):
    """The link in `row` that names the document, by its accessible name
    or its whole text, or None. A link whose words, the title taken out,
    name an insert is not the document's, and every word the link carries,
    what it shows, its label and its title, has to pass the guard. The
    guard used to read the document's title in place of the link's own
    words (#36, review). A link with something else pressable inside it,
    a role=link element wrapping a notice's link, is passed over, since a
    press lands on its middle, and the trace says so in fixed words
    (review). The link comes back as the element itself, the one that was
    checked, never found again by its place when it is pressed (review).

    The answer is the link or None, and whether a link could not be read.
    A link that could not be read may have been the one naming the
    document, so the caller does not count this row as naming nothing. It
    used to be passed over, and of two rows naming the document the other
    one's link would be pressed as the only one (found beside CI run
    36792330947).

    Third, whether a visible link in the row names the document for any
    account, insert aside, so the caller can count the rows holding one of
    the documents the lists gave its date and title (#96)."""
    looks = (row.get_by_role("link", name=_title_name_re(title)),
             row.get_by_role("link").filter(has_text=re.compile(
                 "^\\s*" + escape_for_locator(title.strip()) + "\\s*$", re.I)))
    unread, unmade, names_any = False, 0, False
    for loc in looks:
        # A look that cannot be made at all gives way to the next one. Only
        # when no look could be made is the row unread.
        try:
            many = min(loc.count(), 4)
        except Exception:
            unmade += 1
            continue
        for j in range(many):
            try:
                el = loc.nth(j).element_handle(timeout=2000)
                if el is None:
                    unread = True
                    continue
                if not el.is_visible():
                    continue
                shows = el.inner_text()
                labels = (el.get_attribute("aria-label"), el.get_attribute("title"))
            except Exception:
                unread = True
                continue
            if _is_insert_text((shows,), title, labels):
                continue
            names_any = True
            # The link has to be this account's by every word it carries, its
            # label as well as what it shows (#96).
            if not _account_ok((shows,) + labels, title):
                continue
            if not _guard_allows((shows,) + labels, title):
                continue
            around = _around(el, title)
            if not around:
                unread = True
                continue
            if not around.get("clean"):
                if trace is not None:
                    trace.append({"note": "a link naming this document holds something else that "
                                          "could be pressed, so it was passed over"})
                continue
            # A link naming no account, in a row showing another account,
            # is that account's (review of #96).
            if not _row_is_this_accounts((shows,) + labels, around.get("texts") if around.get("row") else None,
                                         title):
                if trace is not None:
                    trace.append({"note": "a link naming this document sits in a row that may be "
                                          "another account's, so it was passed over"})
                continue
            return el, False, True
    return None, unread or unmade == len(looks), names_any


def _may_press_unnamed(cands, row_names_it: bool) -> List[bool]:
    """For each of a row's controls that do not name the document, whether
    it may be pressed for the document, in a row already known to hold this
    document and no other. A bare action, View, Download, Open, Print or
    PDF, may. One that says something else names some other thing, a
    notice or the document printed under another name. It may only when
    the row names nothing, holds no bare action, and it is the only such
    control, since then it is the document's own link under another name.
    Only an insert's own words said it was one, so a "Privacy Notice" link
    was pressed as the document's once its own link or its View brought
    nothing (#36, review)."""
    plain = [_says_only_an_action(c) for c in cands]
    other = {_norm(c.get("text") or c.get("aria")) for c, p in zip(cands, plain) if not p}
    alone = not row_names_it and not any(plain) and len(other) == 1
    return [p or alone for p in plain]


def _row_link_for(page, iso_date: str, title: str, trace: Optional[list] = None):
    """The document's own link in its row, the one a person clicks to get
    the PDF (second survey), or (None, "").

    Every row that prints the date is looked at, and the link that names
    the document is taken. Only when no row names it, exactly one row
    prints the date, and the lists said that date held one document and
    it is this one, is one of that row's links taken, never an insert or
    another document's, and then only when the row prints no other date.
    Of the rest, a bare View or Download may be taken, and a link that
    says something else only when the row does not print the document's
    title, holds no View or Download, and it is the only such control
    (_lone_control_may_be_pressed, which counts every control in the row,
    buttons, input buttons, pointers and elements made clickable, not only
    links). A View drawn as a button went unseen here, and a lone notice
    link was taken as the document's own link under another name, ahead
    of every other step (review). What the row prints is read through
    shadow roots and slots as well, since a row's own text leaves out what
    a web component draws there. A link with something else pressable
    inside it is never taken. It used to
    take the first row with the date, and on a date with two documents
    that saved the other one's PDF under this one's name (#36, review). A
    row that merely prints the title beside some other link is not
    enough, since that link could be the other document's (review).

    When the rows of the date hold no link this step can see, as when a
    table in a shadow root shows links slotted in from outside it, it says
    so and leaves the choice to the row walk, rather than writing a
    refusal ahead of a download that then succeeds (review).

    A row of the date that could not be told visible or not, or a link in
    one that could not be read, stops the choosing, and the steps after
    this one decide. Either used to be passed over as if it were not on
    the page, so of two rows naming the document the one that could be
    read would be taken as the only one (found beside CI run 36792330947). The
    one row's words read through shadow roots are still only logged when
    they cannot be had, since its own text is read either way."""
    unread_why = "a row of this date could not be read"
    try:
        rows = page.get_by_role("row").filter(has_text=_date_text_re(iso_date))
        shown, unread = [], 0
        for i in range(min(rows.count(), 40)):
            try:
                if rows.nth(i).is_visible():
                    shown.append(rows.nth(i))
            except Exception:
                unread += 1
        named, named_any = [], 0
        if title:
            for row in shown:
                link, missed, any_account = _named_link(row, title, trace)
                if missed:
                    unread += 1
                if link is not None:
                    named.append(link)
                named_any += bool(any_account)
        if unread:
            _refuse(trace, "row link", unread_why, iso_date, len(shown), len(named))
            return None, ""
        # Every document the lists gave its date and title has to have its
        # row here, whatever its account, or the one naming it may be
        # another's, the rest on another page of the list (#96).
        listed = _listed_docs(iso_date, title)
        if len(named) == 1 and listed > 1 and named_any < listed:
            _refuse(trace, "row link", FEWER_NAMED, iso_date, len(shown), named_any)
            return None, ""
        if len(named) == 1:
            return named[0], title
        if len(named) > 1:
            _refuse(trace, "row link", "more than one row of this date names this document",
                    iso_date, len(shown), len(named))
            return None, ""
        if not shown:
            return None, ""
        if not any(row.get_by_role("link").count() for row in shown):
            if trace is not None:
                trace.append({"note": "the rows of this date show this step no link, so the row walk decides",
                              "rows": len(shown)})
            return None, ""
        if len(shown) == 1 and _alone_that_day(iso_date, title):
            row = shown[0]
            words = [row.inner_text(timeout=2000) or ""]
            try:
                words += [w for w in (row.evaluate(_ROW_WORDS_JS, _js_title(title)) or []) if isinstance(w, str)]
            except Exception as e:
                log.info("could not read the row's words: %s", type(e).__name__)
            if _dates_in(" | ".join(words)) - {iso_date}:
                _refuse(trace, "row link", "the row prints another date", iso_date, 1, 0)
                return None, ""
            links = row.get_by_role("link")
            usable = []
            for j in range(min(links.count(), 8)):
                try:
                    el = links.nth(j).element_handle(timeout=2000)
                    if el is None:
                        unread += 1
                        continue
                    if not el.is_visible():
                        continue
                    text = (el.inner_text() or "").strip()
                    aria = (el.get_attribute("aria-label") or "").strip()
                except Exception:
                    unread += 1
                    continue
                if not (text or aria) or _is_insert_text((text,), title, (aria,)) \
                        or _names_another((text, aria), title, iso_date) \
                        or not _account_ok((text, aria), title) \
                        or not _row_is_this_accounts((text, aria), words, title) \
                        or not _guard_allows((text, aria), title):
                    continue
                usable.append((el, {"text": text, "aria": aria}))
            if unread:
                _refuse(trace, "row link", unread_why, iso_date, 1, 0)
                return None, ""
            may = _may_press_unnamed([c for _el, c in usable], any(_mentions(w, title) for w in words))
            why = "no row of this date names this document"
            for (el, c), ok in zip(usable, may):
                if not ok:
                    continue
                around = _around(el, title)
                if not around:
                    _refuse(trace, "row link", unread_why, iso_date, 1, 0)
                    return None, ""
                if not around.get("clean"):
                    why = "the control holds something else that could be pressed"
                    continue
                if not _says_only_an_action(c) and not _lone_control_may_be_pressed(around, iso_date, title, c):
                    why = "the one control of this date may be for something else"
                    continue
                return el, _guard_word(c["text"] or c["aria"], title)
            _refuse(trace, "row link", why, iso_date, 1, 0)
            return None, ""
        _refuse(trace, "row link", "no row of this date names this document" if title
                else "more than one row carries this date", iso_date, len(shown), 0)
    except Exception as e:
        log.info("row link lookup failed: %s", e)
    return None, ""


# What a press could land on, whether an element names the document, and
# what a row says, for every script below that decides what may be
# pressed, so each of them judges it the same way. A script that splices
# this in has the document's title in scope as `docName`, either the title or
# "", or what _js_title gives, the title with the account of the document
# being taken and whether another account may have a document of the same
# title and day (#96).
_PRESS_JS = r"""
  const [title, account, shared, byLabel] = Array.isArray(docName)
    ? [String(docName[0] || ''), String(docName[1] || ''), !!docName[2], !!docName[3]]
    : [String(docName || ''), '', false, false];
  const own = (el) => Array.from(el.childNodes).filter(n => n.nodeType === 3).map(n => n.textContent.trim()).filter(Boolean).join(' ');
  const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const titleRe = title ? new RegExp('^\\s*' + esc(title.trim()) + '(\\s+pdf(\\s+for\\s+(\\S.*?))?)?\\s*$', 'i') : null;
  const norm = (s) => (s || '').replace(/\s+/g, ' ').trim().toLowerCase();
  // The account words give the title after "PDF for", '' when they name it
  // with no account, null when they do not name it (_for_part).
  const forOf = (s) => {
    if (!titleRe) return null;
    const m = titleRe.exec((s || '').replace(/\s+/g, ' ').trim());
    return m ? (m[3] || '').trim() : null;
  };
  // An account's masked tails and its label in one form (account_tails,
  // account_form), and whether the account a name gives is this one, by
  // its tails, or by its whole label when neither shows a tail or another
  // account shows the same tail (_same_account).
  const TAIL = /(?:-|\.{2,}|\*{2,}|[xX•]{2,})\s*(\d{3,6})\)?(?:\s*[\(\[]?(?:closed|inactive)[\)\]]?)?\s*(?=[,;]|$)/gi;
  const tailsOf = (s) => Array.from(norm(s).matchAll(TAIL)).map(m => m[1]);
  const form = (s) => norm(s).replace(TAIL, (m, d) => '-' + d);
  const sameAccount = (f) => {
    if (byLabel) return form(f) === form(account);
    const mine = tailsOf(account), theirs = tailsOf(f);
    if (mine.length || theirs.length) return mine.join('+') === theirs.join('+');
    return form(f) === form(account);
  };
  // The words of one element may be this account's document. None of them
  // names the title for another account, and when another account may have
  // a document of the same title and day, one names it for this account
  // (_account_ok).
  const accountOk = (words) => {
    if (!account) return true;
    let exact = false;
    for (const w of words) {
      const f = forOf(w);
      if (!f) continue;
      if (!sameAccount(f)) return false;
      exact = true;
    }
    return exact || !shared;
  };
  const shown = (el) => {
    try { if (el.checkVisibility) return el.checkVisibility(); } catch (e) { /* an older engine */ }
    return !!(el.getClientRects && el.getClientRects().length);
  };
  // A row's own children are not all of it. E*TRADE's table is built
  // from web components, so the cell that holds the document's link is a
  // <slot>, and what the slot shows lives somewhere else entirely. A walk
  // over children alone reached the slot and stopped, and the trace came
  // back saying the row holds nothing clickable while the row plainly
  // held a document (#36). This goes through a shadow root and through a
  // slot to whatever it is showing.
  const inside = (el) => {
    const out = [];
    try {
      if (el.tagName && el.tagName.toLowerCase() === 'slot' && el.assignedElements) {
        for (const a of el.assignedElements({flatten: true})) out.push(a);
      }
    } catch (e) { /* an older slot, or none */ }
    if (el.shadowRoot) {
      for (const c of el.shadowRoot.children) out.push(c);
    }
    for (const c of el.children) out.push(c);
    return out;
  };
  // What an element says, its visible text, or for a button drawn as an
  // input its value, since an input has no text of its own. An input
  // button reading Download went unseen as a word (review).
  const BUTTON_INPUTS = ['button', 'submit', 'reset', 'image'];
  const wordsIn = (el) => {
    const tag = el.tagName ? el.tagName.toLowerCase() : '';
    if (tag === 'input') {
      const type = (el.getAttribute('type') || '').toLowerCase();
      const said = type === 'image' ? el.getAttribute('alt') : BUTTON_INPUTS.includes(type) ? el.getAttribute('value') : '';
      return (said || '').replace(/\s+/g, ' ').trim();
    }
    return (el.innerText || '').replace(/\s+/g, ' ').trim();
  };
  // An element names the document when its whole words or its label are
  // the title, the title then PDF, or "<title> PDF for <account>". Its own
  // text nodes alone used to count too, whatever its children added, so a
  // link reading the title with "Privacy Notice" in a span inside it was
  // pressed as the document's name (review). This decides every press. For
  // a document of one account, the element has to be that account's by
  // all its words, its label as well as what it shows (#96).
  const namesTitle = (el) => {
    if (!titleRe || !el.getAttribute) return false;
    const t = wordsIn(el);
    const aria = (el.getAttribute('aria-label') || '').replace(/\s+/g, ' ').trim();
    const shows = t.length < 200 ? t : '';
    return (titleRe.test(shows) || titleRe.test(aria)) && accountOk([shows, aria]);
  };
  // For choosing which row is the document's, an element whose own text
  // nodes are the title counts as well, a title printed beside smaller
  // words. It never decides what is pressed. Printed bare, the title says
  // nothing of the account, so it counts only when no other account may
  // have a document of the same title and day.
  const printsTitle = (el) => namesTitle(el) || (!!titleRe && !!el.getAttribute && titleRe.test(own(el))
    && accountOk([own(el), (el.getAttribute('aria-label') || '').replace(/\s+/g, ' ').trim()]));
  // Something a press could land on and set off, whatever it says.
  const PRESS_TAGS = ['a', 'button', 'input', 'select', 'textarea', 'summary', 'label'];
  const PRESS_ROLES = ['button', 'link', 'checkbox', 'menuitem', 'menuitemradio', 'menuitemcheckbox',
                       'option', 'tab', 'switch', 'radio'];
  const pointerAt = (el) => { try { return getComputedStyle(el).cursor === 'pointer'; } catch (e) { return false; } };
  const pressable = (el, parent) => {
    const tag = el.tagName.toLowerCase();
    if (PRESS_TAGS.includes(tag)) return true;
    if (PRESS_ROLES.includes((el.getAttribute('role') || '').toLowerCase())) return true;
    if (el.hasAttribute('onclick')) return true;
    const ti = el.getAttribute('tabindex');
    if (ti !== null && parseInt(ti, 10) >= 0) return true;
    // A pointer cursor inherits, so only one that starts here counts.
    return pointerAt(el) && !(parent && parent.getAttribute && pointerAt(parent));
  };
  // A box, which the row's box path handles, and a field or a label, which
  // nothing presses for a document.
  const isBox = (el) => {
    const tag = el.tagName.toLowerCase();
    const type = (el.getAttribute('type') || '').toLowerCase();
    const role = (el.getAttribute('role') || '').toLowerCase();
    return (tag === 'input' && (type === 'checkbox' || type === 'radio')) ||
           ['checkbox', 'radio', 'switch', 'menuitemcheckbox', 'menuitemradio'].includes(role);
  };
  const isField = (el) => {
    const tag = el.tagName.toLowerCase();
    const type = (el.getAttribute('type') || '').toLowerCase();
    return tag === 'select' || tag === 'textarea' || tag === 'label' ||
           (tag === 'input' && !BUTTON_INPUTS.includes(type) && type !== 'checkbox' && type !== 'radio');
  };
  // Everything pressable() counts that is not a box or a field, a link, a
  // button, an input button, an element the page made clickable with an
  // action role, onclick or a tab stop, and one whose pointer cursor
  // starts there. The row link step and the one control rule counted
  // links and buttons only, so a View drawn any other way went unseen and
  // a lone notice passed for the document's own link (review).
  const actionable = (el, parent) => pressable(el, parent) && !isBox(el) && !isField(el);
  // The ones that are a control whatever their cursor, everything above
  // but a bare pointer.
  const actsAsControl = (el) => {
    if (isBox(el) || isField(el)) return false;
    const tag = el.tagName.toLowerCase();
    const type = (el.getAttribute('type') || '').toLowerCase();
    const role = (el.getAttribute('role') || '').toLowerCase();
    if (tag === 'a' || tag === 'button' || tag === 'summary') return true;
    if (tag === 'input' && BUTTON_INPUTS.includes(type)) return true;
    if (PRESS_ROLES.includes(role) || el.hasAttribute('onclick')) return true;
    const ti = el.getAttribute('tabindex');
    return ti !== null && parseInt(ti, 10) >= 0;
  };
  // A control a press on something inside it sets off as well, a link, a
  // button, an input button, an action role or an onclick. A tab stop
  // alone only takes the focus.
  const captures = (el) => {
    if (isBox(el) || isField(el)) return false;
    const tag = el.tagName.toLowerCase();
    const type = (el.getAttribute('type') || '').toLowerCase();
    const role = (el.getAttribute('role') || '').toLowerCase();
    return tag === 'a' || tag === 'button' || tag === 'summary' || (tag === 'input' && BUTTON_INPUTS.includes(type)) ||
           PRESS_ROLES.includes(role) || el.hasAttribute('onclick');
  };
  // An element is pressed for the document only when nothing else
  // pressable sits inside it. A cell or a wrapper whose words start with
  // the title can also hold the other document's link or an insert, and a
  // press on its middle lands on whatever is there, which saved the other
  // document's PDF under this name (#36, review). A container whose
  // cursor says it is clickable did the same with an insert's View
  // (review). Anything pressable inside has to name the document too.
  const clean = (el, d) => {
    if (d > 20) return false;
    for (const c of inside(el)) {
      if (!c.getAttribute) continue;
      if (pressable(c, el) && !namesTitle(c)) return false;
      if (!clean(c, d + 1)) return false;
    }
    return true;
  };
  const up = (el) => {
    if (el.parentElement) return el.parentElement;
    const r = el.getRootNode ? el.getRootNode() : null;
    return r && r.host ? r.host : null;
  };
  // What an element says, element by element, through shadow roots and
  // slots, since innerText leaves out whatever a web component draws in
  // its shadow root. It is compared in Python and never written down.
  const sayInto = (el, d, out) => {
    if (d > 20 || out.length > 300 || !el.getAttribute) return;
    const t = wordsIn(el);
    if (t && t.length < 200) out.push(t);
    const o = own(el);
    if (o) out.push(o);
    const a = el.getAttribute('aria-label');
    if (a) out.push(a);
    for (const c of inside(el)) sayInto(c, d + 1, out);
  };
  // The controls under `root`, everything actionable() counts, with the
  // words each carries, less any that `skip` names. Compared in Python and
  // never written down.
  const controlsIn = (root, skip) => {
    const out = [];
    const go = (el, d) => {
      if (d > 20 || out.length > 40) return;
      for (const c of inside(el)) {
        if (!c.getAttribute) continue;
        if (!(skip && skip(c)) && actionable(c, el)) {
          out.push({text: wordsIn(c).slice(0, 80), aria: c.getAttribute('aria-label') || ''});
        }
        go(c, d + 1);
      }
    };
    go(root, 0);
    return out;
  };
"""

# The rows around every element whose own text is the document's date, by a
# walk over children (never querySelectorAll, which some frameworks patch),
# and of those the one that names the document, with an outline of what it
# holds for the trace. It used to take the first element on the page with
# the date and ignore the title, and on a date with two documents that
# clicked the other one's control (#36, review). When it cannot tell which
# row is the document's it says so in counts and chooses nothing.
_ROW_BY_DATE_JS = r"""([dates, docName, alone, expected]) => {""" + _PRESS_JS + r"""
  const forms = dates.filter(Boolean);
  const dateRes = forms.map(d => new RegExp('(^|[^0-9/])' + esc(d) + '($|[^0-9/])'));
  const anyDate = /(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}|\b\d{1,2}\/\d{1,2}\/\d{2,4}\b|\b\d{4}-\d{2}-\d{2}\b/gi;
  // The innermost visible elements under `root` that print the title, to
  // choose the row by. What is pressed in it is decided by namesTitle.
  const titledBy = (root, prints) => {
    const found = new Set();
    const go = (el, d) => {
      if (d > 20) return;
      for (const c of inside(el)) {
        if (!c.getAttribute) continue;
        if (prints(c) && shown(c)) found.add(c);
        go(c, d + 1);
      }
    };
    go(root, 0);
    const list = Array.from(found);
    return list.filter(a => !list.some(b => b !== a && a.contains(b)));
  };
  const titled = (root) => titledBy(root, printsTitle);
  // An element printing the title for any account, its whole words, its
  // label or its own text nodes, to count the rows of the date that hold
  // one of the documents the lists gave its date and title (#96).
  const printsAnyAccounts = (el) => !!titleRe && !!el.getAttribute && (titleRe.test(wordsIn(el).length < 200 ? wordsIn(el) : '')
    || titleRe.test((el.getAttribute('aria-label') || '').replace(/\s+/g, ' ').trim()) || titleRe.test(own(el)));
  // A container that prints some other date holds more than one row.
  const otherDates = (el) => ((el.innerText || '').match(anyDate) || []).some(m => !forms.includes(m.replace(/\s+/g, ' ')));
  // The row around a date. A table row, a list item or a role=row element,
  // else the nearest element that holds exactly one element naming the
  // document and no other date. None when there is neither, since a
  // container of many rows is not a row.
  const rowOf = (hit) => {
    let node = hit;
    for (let i = 0; i < 10 && node && node !== document.body && node !== document.documentElement; i++) {
      const tag = node.tagName.toLowerCase();
      const role = node.getAttribute('role') || '';
      if (tag === 'tr' || tag === 'li' || role === 'row') return node;
      if (titleRe && node !== hit && node.children.length > 1 && titled(node).length === 1 && !otherDates(node)) return node;
      node = up(node);
    }
    return null;
  };
  const all = [];
  const walk = (el) => { for (const c of el.children) { all.push(c); if (c.shadowRoot) for (const s of c.shadowRoot.children) { all.push(s); walk(s); } walk(c); } };
  walk(document.body);
  const hits = all.filter(el => (dateRes.some(r => r.test(own(el))) || forms.some(d => (el.innerText || '').trim() === d)) && shown(el));
  if (!hits.length) return null;
  const found = [];
  for (const h of hits) { const r = rowOf(h); if (r && !found.includes(r)) found.push(r); }
  const rows = found.filter(r => !found.some(o => o !== r && r.contains(o)));
  const named = rows.filter(r => titled(r).length > 0);
  // When the lists gave its date and title more than one document, every
  // one of them has to have a row here naming it, whatever its account.
  // The one row naming it among fewer may be another document's, on a page
  // that shows only some of them (#96).
  const namedAny = titleRe ? rows.filter(r => titledBy(r, printsAnyAccounts).length > 0).length : 0;
  let row = null, why = '';
  if (!titleRe) {
    if (rows.length === 1) row = rows[0];
    else why = rows.length ? 'more than one row carries this date' : 'no row around this date';
  } else if (named.length === 1 && expected > 1 && namedAny < expected) why = '""" + FEWER_NAMED + r"""';
  else if (named.length === 1) row = named[0];
  else if (named.length > 1) why = 'more than one row of this date names this document';
  else if (rows.length === 1 && alone) row = rows[0];
  else why = rows.length ? 'no row of this date names this document' : 'no row around this date';
  if (!row) return {refused: why, rows: rows.length, named: named.length};
  // The outline is data. What of it may leave is decided in Python.
  const outline = [];
  const desc = (el, d) => {
    if (d > 6 || outline.length > 80) return;
    const tag = el.tagName.toLowerCase();
    if (['svg', 'path', 'script', 'style'].includes(tag)) return;
    const home = el.getRootNode ? el.getRootNode() : document;
    outline.push({depth: d, tag, shadow: home !== document, root: !!el.shadowRoot,
                  cls: (el.className || '').toString().split(' ').filter(Boolean).slice(0, 2),
                  role: el.getAttribute('role') || '', type: el.getAttribute('type') || '',
                  aria: el.getAttribute('aria-label') || '', own: own(el),
                  href: tag === 'a' ? (el.getAttribute('href') || '') : '',
                  pointer: getComputedStyle(el).cursor === 'pointer'});
    for (const c of inside(el)) desc(c, d + 1);
  };
  desc(row, 0);
  // candidates, innermost first: the element that names the document,
  // anchors, buttons, anything the cursor says is clickable, and a checkbox
  const cands = [];
  const seen = new Set();
  // A press on anything inside a control is a press on that control as
  // well. A span reading View inside a link labeled as an insert was
  // pressed on its own words and handed over the insert (review). So each
  // candidate carries the words of every control around it inside the row
  // that a press sets off (captures), and Python judges it by those too.
  const wordsOf = (el) => ({text: wordsIn(el).slice(0, 200), aria: el.getAttribute('aria-label') || ''});
  const collect = (el, d, outer) => {
    if (d > 20) return;
    for (const c of inside(el)) {
      if (!c.getAttribute || seen.has(c)) continue;
      seen.add(c);
      const role = (c.getAttribute('role') || '').toLowerCase();
      const t = wordsIn(c);
      const type = (c.getAttribute('type') || '').toLowerCase();
      // The kinds, in the order Python tries them. A control is anything
      // actsAsControl names, input buttons and elements made clickable
      // with an action role, onclick or a tab stop among them, which went
      // unseen here, so a notice beside a Download drawn that way was the
      // row's only control (review).
      let kind = '';
      if (namesTitle(c) && clean(c, 0)) kind = 'title';
      else if ((c.tagName.toLowerCase() === 'input' && type === 'checkbox') || role === 'checkbox') kind = 'checkbox';
      else if (actsAsControl(c)) kind = 'control';
      else if (!isBox(c) && !isField(c) && getComputedStyle(c).cursor === 'pointer' && t && t.length < 80) kind = 'pointer';
      // A control or a pointer with something else pressable inside it is
      // never pressed, the rule a title already had. A pointer container
      // holding this document's View and an insert's read as a bare View,
      // and a press on its middle landed on the insert (review). It stays
      // a candidate, marked, so it still counts among the row's controls
      // when Python decides what else in the row may be pressed.
      const holds = (kind === 'control' || kind === 'pointer') && !clean(c, 0);
      // A box's own words are its label, which the guard reads too.
      let label = '';
      try { if (c.labels) label = Array.from(c.labels).map(l => (l.innerText || '').trim()).join(' '); } catch (e) { label = ''; }
      if (kind) cands.push({el: c, kind, text: t.slice(0, 200), aria: c.getAttribute('aria-label') || '',
                            label: label.slice(0, 80), holds, outer: outer.map(wordsOf)});
      collect(c, d + 1, captures(c) ? outer.concat([c]) : outer);
    }
  };
  collect(row, 0, []);
  cands.sort((a, b) => (a.el.contains(b.el) ? 1 : b.el.contains(a.el) ? -1 : 0));
  // What the row says, so Python can tell whether it prints the title or
  // holds another document too.
  const texts = [];
  sayInto(row, 0, texts);
  // What every row of the date says and which controls it holds, so
  // Python counts only the rows that look like a document's own. Any
  // element printing the date used to count as a row, a filter chip among
  // them (review).
  const rowWords = rows.map(r => { const said = []; sayInto(r, 0, said); return {texts: said, controls: controlsIn(r, null)}; });
  return {outline, cands: cands.map(c => ({kind: c.kind, text: c.text, aria: c.aria, label: c.label,
                                           holds: c.holds, outer: c.outer})),
          els: cands.map(c => c.el), rows: rows.length, named: named.length, texts, row_words: rowWords};
}"""


# One control found before the row walk, and the row around it. Whether it
# presses only itself, every pressable element inside it naming the
# document too, and the row around it, the nearest element above it that
# prints a date, with what that row says, the words of every other control
# in it, and how many of its elements print a date as their own text. More
# than one means the "row" is several rows or the whole page, which is
# where the page's bulk Download sits (review). What the lone control step
# and the row link step judge it by. It is compared in Python and never
# written down.
_AROUND_CONTROL_JS = r"""(el, docName) => {""" + _PRESS_JS + r"""
  const dateRe = /(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}|\d{1,2}\/\d{1,2}\/\d{2,4}|\d{4}-\d{2}-\d{2}/i;
  const above = (a, b) => { for (let n = up(b); n; n = up(n)) { if (n === a) return true; } return false; };
  const out = {clean: clean(el, 0), row: false, texts: [], controls: [], dated: 0};
  let row = up(el);
  for (let i = 0; i < 8 && row && row !== document.body && !dateRe.test(row.innerText || ''); i++) row = up(row);
  if (!row || row === document.body || row === document.documentElement || !dateRe.test(row.innerText || '')) return out;
  out.row = true;
  sayInto(row, 0, out.texts);
  out.controls = controlsIn(row, c => c === el || above(c, el) || above(el, c));
  const count = (n, d) => {
    if (d > 20 || !n.getAttribute) return;
    if (dateRe.test(own(n))) out.dated++;
    for (const c of inside(n)) count(c, d + 1);
  };
  count(row, 0);
  return out;
}"""


# Everything a row says, element by element, through shadow roots and
# slots. A row's innerText leaves out what a web component draws in its
# shadow root, so a title printed there went unseen. Compared in Python and
# never written down.
_ROW_WORDS_JS = r"""(row, docName) => {""" + _PRESS_JS + r"""
  const out = [];
  sayInto(row, 0, out);
  return out;
}"""


def _row_by_date(page, iso_date: str, title: str):
    """The document's row, chosen among every row that prints its date, as
    a dict. With "refused" and the counts when it cannot tell which row is
    the document's, with "outline", "cands", "els", "texts", "row_words"
    and the counts when it can, and None when no element on the page
    carries the date. "texts" is what the chosen row says and "row_words"
    what every row of the date says and which controls it holds, for
    _row_holds_only_this and _document_rows. Neither is ever written
    down."""
    dates = _row_date_forms(iso_date)
    try:
        h = page.evaluate_handle(_ROW_BY_DATE_JS, [dates, _js_title(title), _alone_that_day(iso_date, title),
                                                   _listed_docs(iso_date, title)])
        props = h.get_properties()
        if not props:
            return None
        counts = {k: int(props[k].json_value() or 0) for k in ("rows", "named") if k in props}
        if "refused" in props:
            return {"refused": str(props["refused"].json_value() or ""), **counts}
        if "els" not in props:
            return None
        texts = props["texts"].json_value() if "texts" in props else []
        row_words = props["row_words"].json_value() if "row_words" in props else []
        return {"outline": props["outline"].json_value(), "cands": props["cands"].json_value(),
                "els": [v.as_element() for v in props["els"].get_properties().values()],
                "texts": [t for t in texts if isinstance(t, str)],
                "row_words": [r for r in row_words if isinstance(r, dict)] if isinstance(row_words, list) else [],
                **counts}
    except Exception as e:
        log.info("row by date: %s", e)
        return None


def _row_words(found: dict) -> List[str]:
    """What the chosen row says, element by element, with every candidate's
    words and its box's label. Compared, never written down."""
    cands = found.get("cands") or []
    texts = [t for t in (found.get("texts") or []) if isinstance(t, str)]
    return texts + [str(c.get(k) or "") for c in cands for k in ("text", "aria", "label")]


def _document_rows(iso_date: str, title: str, found: dict) -> int:
    """How many of the rows that print the date look like a document's own
    row. Such a row prints a title the lists gave that date and no other
    date, and holds a control that could hand a document over, a bare
    action or a control whose words carry such a title, once inserts and
    whatever the guard refuses are left out. A control is judged against
    the title it names, so another document's link keeps its own title out
    of the insert check and the account it names after "PDF for" out of the
    guard. Every element that printed the date used to count, so a filter
    chip made a row carrying both documents of the date pass for one
    holding this document alone, and the other one's Download was pressed
    (#36, review). A row that prints none of the listed titles, a notice
    with a View of its own, is not one of those documents either."""
    titles = {t for t in _LISTED_TITLES.get(iso_date, ()) if _norm(t)}
    if _norm(title):
        titles.add(title)
    count = 0
    for row in found.get("row_words") or []:
        if not isinstance(row, dict):
            continue
        texts = [t for t in (row.get("texts") or []) if isinstance(t, str)]
        if _dates_in(" | ".join(texts)) - {iso_date}:
            continue
        if not any(_mentions(t, x) for t in texts for x in titles):
            continue
        for c in row.get("controls") or []:
            if not isinstance(c, dict):
                continue
            c = {"text": str(c.get("text") or ""), "aria": str(c.get("aria") or "")}
            words = [w for w in (c["text"], c["aria"]) if _norm(w)]
            if not words:
                continue
            own = next((t for t in sorted(titles) if any(_names_any(w, t) for w in words)), title)
            if _is_insert(c, own) or not _guard_allows(words, own):
                continue
            if _says_only_an_action(c) or any(_mentions(w, t) for w in words for t in titles):
                count += 1
                break
    return count


def _row_holds_only_this(iso_date: str, title: str, found: dict) -> Tuple[bool, str]:
    """Whether the chosen row holds this document and no other, and when
    not, why, in words from _CROWDED. Only then may a control in it that
    does not name the document, a View, a pointer or the row's box, be
    pressed for it. One row can hold both documents of a date, and a View
    or a box in it could be the other one's (#36, review).

    The row holds only this document when it prints no other date, names
    no other document the lists gave its date, and holds at most one box,
    and then either the lists held this one document alone on that date,
    or the row names this document, the lists named that date's documents
    so another one would have been seen, no control label repeats, and
    the page shows at least as many document rows of the date as the lists
    held documents (_document_rows). Fewer rows than documents means one
    row carries two of them, however the page words the other one
    (review)."""
    cands = found.get("cands") or []
    texts = _row_words(found)
    if _dates_in(" | ".join(texts)) - {iso_date}:
        return False, _CROWDED[0]
    if _names_another(texts, title, iso_date):
        return False, _CROWDED[1]
    if sum(1 for c in cands if c.get("kind") == "checkbox") > 1:
        return False, _CROWDED[2]
    if _alone_that_day(iso_date, title):
        return True, ""
    if not (title and found.get("named") and _LISTED_TITLES.get(iso_date)):
        return False, _CROWDED[4]
    labels = [_norm(c.get("text") or c.get("aria")) for c in cands
              if c.get("kind") == "control" and not _is_insert(c, title)]
    if len(labels) != len(set(labels)):
        return False, _CROWDED[3]
    if _document_rows(iso_date, title, found) < _LISTED.get(iso_date, 0):
        return False, _CROWDED[5]
    return True, ""


# How many boxes are ticked on the page, through shadow roots, a native
# checkbox by its state and any other by aria-checked. A role=checkbox
# element with a native box inside it, in its own children or its shadow
# root, is that one box, counted once by the native box's state. The
# shadow root's box used to be counted beside its host, which made one
# ticked box read as two (review).
_TICKED_JS = r"""() => {
  let n = 0;
  const walk = (root) => {
    for (const el of root.children) {
      const tag = el.tagName.toLowerCase();
      if (tag === 'input' && (el.type || '').toLowerCase() === 'checkbox') { if (el.checked) n++; }
      else if (el.getAttribute('role') === 'checkbox' && el.getAttribute('aria-checked') === 'true') {
        if (!el.querySelector('input[type=checkbox]') &&
            !(el.shadowRoot && el.shadowRoot.querySelector('input[type=checkbox]'))) n++;
      }
      if (el.shadowRoot) walk(el.shadowRoot);
      walk(el);
    }
  };
  walk(document.body);
  return n;
}"""


def _ticked(page) -> int:
    """How many boxes the page shows ticked, or -1 when they could not be
    counted, which the caller takes as a reason not to press Download."""
    try:
        return int(page.evaluate(_TICKED_JS) or 0)
    except Exception:
        return -1


# Whether one box reads ticked, a native checkbox by its state, one inside
# it or inside its shadow root the same way, any other by aria-checked.
# Empty when it says neither.
_BOX_STATE_JS = r"""el => {
  let input = null;
  if (el.tagName.toLowerCase() === 'input' && (el.type || '').toLowerCase() === 'checkbox') input = el;
  else input = el.querySelector('input[type=checkbox]') ||
               (el.shadowRoot ? el.shadowRoot.querySelector('input[type=checkbox]') : null);
  if (input) return input.checked ? 'ticked' : 'clear';
  const a = (el.getAttribute('aria-checked') || '').toLowerCase();
  return a === 'true' ? 'ticked' : a === 'false' ? 'clear' : '';
}"""


def _box_state(el) -> str:
    """"ticked", "clear", or "" when the box could not be read."""
    try:
        state = el.evaluate(_BOX_STATE_JS)
    except Exception:
        return ""
    return state if state in ("ticked", "clear") else ""


_DOWNLOAD_BUTTON_RE = re.compile(r"^\s*download\s*$", re.I)

# Whether a button sits inside a document's row, a table row, a list item
# or a role=row element around it that prints a date, through shadow
# roots. The page's own Download sits outside every one of them. The only
# visible button named Download was another row's own and it was pressed
# after this row's box was ticked (review). A toolbar's list item prints no
# date, so a Download kept in one is still the page's.
_IN_A_ROW_JS = r"""el => {
  const dateRe = /(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}|\d{1,2}\/\d{1,2}\/\d{2,4}|\d{4}-\d{2}-\d{2}/i;
  for (let n = el, i = 0; n && i < 60; i++) {
    const tag = n.tagName ? n.tagName.toLowerCase() : '';
    const role = n.getAttribute ? (n.getAttribute('role') || '').toLowerCase() : '';
    if ((tag === 'tr' || tag === 'li' || role === 'row') && dateRe.test(n.innerText || '')) return true;
    if (n.parentElement) { n = n.parentElement; continue; }
    const r = n.getRootNode ? n.getRootNode() : null;
    n = r && r.host ? r.host : null;
  }
  return false;
}"""


def _tick_and_download(page, box, dl_dir, out_path: Path, trace: Optional[list],
                       pressed: Optional[list] = None) -> bool:
    """Tick this row's own box and press the page's Download button, which
    hands over every ticked document.

    Download is pressed only when the page shows exactly one Download
    button, the tick raised nothing, this row's box then reads ticked, and
    it is the only box ticked on the page. The guard used to count only
    whether more than one box was ticked, so a box another attempt left
    ticked, beside this row's box that would not tick, made Download hand
    over that other document under this one's name (#36, review). A box
    this ticked is cleared again whatever happens, so it cannot do the same
    to the next document. The Download pressed is the page's own, outside
    every document row (_IN_A_ROW_JS), held as the element that was
    checked. Every refusal is written in fixed words.

    A Download button that could not be read stops the press. It was
    passed over, so of two the one that could be read would be pressed as
    the only one (found beside CI run 36792330947)."""
    def note(entry: dict) -> None:
        if trace is not None:
            trace.append(entry)
    shown, in_rows, unread = [], 0, 0
    try:
        buttons = page.get_by_role("button", name=_DOWNLOAD_BUTTON_RE)
        many = min(buttons.count(), 10)
    except Exception:
        many = 0
    for i in range(many):
        try:
            button = buttons.nth(i).element_handle(timeout=2000)
            if button is None:
                unread += 1
                continue
            if not button.is_visible():
                continue
        except Exception:
            unread += 1
            continue
        try:
            inside_a_row = bool(button.evaluate(_IN_A_ROW_JS))
        except Exception:
            # Could not tell. It used to count as one inside a row, which
            # is never pressed, and that left the other button outside
            # every row as the only one.
            unread += 1
            continue
        if inside_a_row:
            in_rows += 1
        else:
            shown.append(button)
    if unread:
        note({"note": "a Download button could not be read, so none was pressed", "unread": unread})
        return False
    if not shown and in_rows:
        note({"note": "the only Download buttons sit inside rows, so none was pressed", "in_rows": in_rows})
        return False
    if len(shown) != 1:
        note({"note": "no single Download button on the page, so none was pressed", "buttons": len(shown)})
        return False
    before = _box_state(box)
    if not before:
        note({"note": "this document's box could not be read, so Download was not pressed"})
        return False
    ticked_here = False
    try:
        if before == "clear":
            try:
                box.click(timeout=4000)
            except Exception as e:
                note({"note": "checkbox click failed, so Download was not pressed", "error": type(e).__name__})
                ticked_here = _box_state(box) == "ticked"
                return False
            ticked_here = True
            page.wait_for_timeout(800)
        if _box_state(box) != "ticked":
            note({"note": "this document's box does not read ticked, so Download was not pressed"})
            return False
        count = _ticked(page)
        if count > 1:
            note({"note": "another box is ticked too, so Download was not pressed", "ticked": count})
            return False
        if count != 1:
            note({"note": "the ticked boxes could not be counted, so Download was not pressed",
                  "ticked": count})
            return False
        return _catch_pdf(page, shown[0], "Download", out_path, trace, dl_dir, pressed)
    finally:
        if ticked_here and _box_state(box) == "ticked":
            try:
                box.click(timeout=4000)
                note({"note": "this document's box was cleared again"})
            except Exception as e:
                note({"note": "this document's box could not be cleared", "error": type(e).__name__})


def _try_every_way(page, dl_dir, iso_date: str, out_path: Path, title: str, trace: Optional[list],
                   pressed: Optional[list] = None) -> bool:
    """The document's row, chosen by the title it names among every row that
    prints its date, and every way it could hand over its PDF tried in
    turn. Each attempt goes through the catch.

    A candidate of kind "title" names the document and holds nothing else
    pressable (the clean check in _ROW_BY_DATE_JS), so a cell holding the
    other document's link or an insert beside this one's is never pressed
    as this document's name. A control or a pointer with anything else
    pressable inside it is never pressed either, and still counts among
    the row's controls when deciding what else may be. A candidate inside
    a link or a button is judged with that control's words, since a press
    on it presses the control too, and it is pressed only as the
    document's name inside controls that name the document. A control whose
    words mark it as an insert is never tried, even one whose label starts
    with the title, since its PDF is a different document. Every word a
    candidate carries has to pass the guard, what it says has to look like
    a document action (is_safe_control) as on every other step, and a
    title's words are read again, its whole words or its label naming the
    document and never its own text nodes alone. A control that does not name
    the document, a View, a pointer or the row's box, is tried only when
    the row holds this document and no other (_row_holds_only_this), and
    of those a control that says something other than View or Download
    only as _may_press_unnamed allows. Whether the row prints the title is
    read the way the row link step reads it, the title anywhere in the
    row's words. It used to need an element whose whole words were the
    title, so a row printing "<title> - October" beside a lone notice was
    taken to print nothing and the notice was pressed (#36, review).
    Otherwise only this document's own name is pressed, and when that
    brings nothing the row is refused in counted, fixed words. The page's
    Download button goes through _tick_and_download. `pressed` is the
    document's list of controls pressed (_catch_pdf), and once a control
    the page has turned off leaves the document, nothing more is tried."""
    pressed = [] if pressed is None else pressed
    found = _row_by_date(page, iso_date, title)
    if not found:
        if trace is not None:
            trace.append({"note": "no element on the page carries this document's date", "date": iso_date})
        return False
    if "refused" in found:
        _refuse(trace, "row by date", found["refused"], iso_date,
                found.get("rows", 0), found.get("named", 0))
        return False
    outline, cands, els = found["outline"], found["cands"], found["els"]
    only_this, why = _row_holds_only_this(iso_date, title, found)
    # A candidate inside a link or a button is part of that control, which
    # is a candidate of its own and is judged on its own words.
    unnamed = [i for i, c in enumerate(cands)
               if c.get("kind") in ("control", "pointer") and not _is_insert(c, title) and not _outer_of(c)]
    row_names_it = int(found.get("named", 0)) > 0 or any(_mentions(w, title) for w in _row_words(found))
    may = dict(zip(unnamed, _may_press_unnamed([cands[i] for i in unnamed], row_names_it)))

    def left_out(i: int) -> bool:
        c = cands[i]
        outer = _outer_of(c)
        words = [c.get("text"), c.get("aria"), c.get("label")] + [o.get(k) for o in outer for k in ("text", "aria")]
        if _is_insert(c, title) or not _guard_allows(words, title):
            return True
        # Never anything that names this title for another account, nor a
        # name that does not give this account when another account may
        # have a document of the same title and day (#96).
        if not _account_ok(words, title):
            return True
        # Nor, in a row showing another account, anything that does not
        # name this one (review of #96).
        if not _row_is_this_accounts(words, found.get("texts"), title):
            return True
        # What is pressed has to look like a document action, the rule
        # is_safe_control holds every other step to. The row walk asked only
        # that a candidate pass the guard, so a row's one control pressed as
        # the document's own link could say anything short of the guard's
        # words (review). The box is a selection, not an action, and is
        # judged by the box path.
        if c.get("kind") != "checkbox" and not is_safe_control(
                _guard_word(c.get("text") or c.get("aria"), title) or title):
            return True
        if c.get("holds"):
            return True
        # A title's words are read again here. A name is an element's whole
        # words or its label. Its own text nodes counted too, whatever its
        # children added, so a link reading the title with "Privacy Notice"
        # in a span inside it was pressed as the name (review).
        if c.get("kind") == "title" and not (names_title(c.get("text"), title) or names_title(c.get("aria"), title)):
            return True
        if outer:
            # A press on it presses the links and buttons around it, so it
            # is pressed only as the document's name inside controls that
            # name the document too. The title in a span inside a link that
            # runs on past it, "<title> PDF Privacy Notice", is that link.
            return not (c.get("kind") == "title" and all(
                names_title(o.get("text"), title) or names_title(o.get("aria"), title) for o in outer))
        if c.get("kind") == "title":
            return False
        return not only_this or not may.get(i, True)
    if trace is not None:
        entry = {"note": "the document's row",
                 "outline": [_outline_line(p, title) for p in outline[:80] if isinstance(p, dict)],
                 "candidates": [{"kind": c.get("kind") if c.get("kind") in _CANDIDATE_KINDS else "other",
                                 "insert": _is_insert(c, title), "left_out": left_out(i),
                                 "holds_another": bool(c.get("holds")),
                                 "inside_another": bool(_outer_of(c))}
                                for i, c in enumerate(cands[:20])],
                 "carrying_the_date": int(found.get("rows", 0)),
                 "rows_with_a_document_control": _document_rows(iso_date, title, found),
                 "naming_the_document": int(found.get("named", 0)),
                 "holds_only_this_document": only_this}
        if why:
            entry["why_not"] = why if why in _CROWDED else "unrecognized"
        trace.append(entry)
    ctx = page.context
    requests: list = []

    def on_request(req):
        try:
            url = req.url or ""
            if not is_safe_url(url) or re.search(r"neologger|analytics|beacon|\.(js|css|png|gif|svg|woff)", url, re.I):
                return
            method = str(req.method or "").upper()
            entry = {"method": method if method in _METHODS else "other", "url": mask_href(url)}
            body = req.post_data or ""
            if body.lstrip().startswith("{"):
                import json as _json
                try:
                    parsed = whole_json(_json.loads(body))
                    if isinstance(parsed, dict):
                        entry["post_keys"] = _param_names(parsed)[:30]
                except Exception:
                    pass
            requests.append(entry)
        except Exception:
            pass
    ctx.on("request", on_request)
    try:
        order = [i for kind in ("title", "control", "pointer")
                 for i, c in enumerate(cands) if c["kind"] == kind and not left_out(i)]
        tried = 0
        unsure: list = []
        for i in order[:6]:
            c, el = cands[i], els[i]
            if el is None:
                continue
            label = _guard_word(c["text"] or c["aria"], title) or title or "document"
            if trace is not None:
                trace.append({"note": "trying", "kind": c["kind"]})
            tried += 1
            if _catch_pdf(page, el, label, out_path, trace, dl_dir, pressed, unsure=unsure):
                return True
            # Turned off on the page, so nothing was pressed for the
            # document, or a press that may have been made, which ends this
            # document, so no other control of its row is pressed (review of
            # 0.45.0).
            if _TURNED_OFF in pressed or unsure:
                return False
            if trace is not None and requests:
                trace.append({"note": "requests after that click", "requests": requests[-12:]})
                requests.clear()
        # The row's box and the page's own Download button, only in a row
        # that holds this document alone, which means one box at most.
        boxes = [i for i, c in enumerate(cands) if c["kind"] == "checkbox" and not left_out(i)]
        if boxes and els[boxes[0]] is not None:
            if trace is not None:
                trace.append({"note": "trying", "kind": "checkbox then Download"})
            if _tick_and_download(page, els[boxes[0]], dl_dir, out_path, trace, pressed):
                return True
            if trace is not None and requests:
                trace.append({"note": "requests after Download", "requests": requests[-12:]})
        if trace is not None and not only_this:
            trace.append({"note": "only this document's own name was pressed, since the row may hold another document",
                          "why": why if why in _CROWDED else "unrecognized", "names_pressed": tried,
                          "left_alone": sum(1 for i, c in enumerate(cands)
                                            if left_out(i) and not _is_insert(c, title))})
        elif trace is not None and not tried and not boxes:
            left = sum(1 for i, c in enumerate(cands) if left_out(i) and not _is_insert(c, title))
            if left:
                trace.append({"note": "nothing in the row may be pressed for this document", "left_alone": left})
            else:
                trace.append({"note": "the row holds nothing that looks clickable"})
    finally:
        try:
            ctx.remove_listener("request", on_request)
        except Exception:
            pass
    return False


# --- a document listed on a later page --------------------------------------------
#
# The list shows one page of a period at a time. Discovery reads every page
# through the page's own request, but the download looks for a document's
# row on the page shown, so a document listed on a later page went to
# Manual Review (#96). On a tester's live page the list's next-page control
# is a button whose aria-label is "Next page" inside <ms-pagination
# role="navigation" aria-label="Table pagination">, turned off on the last
# page. Only that button is pressed, only while it is on, and only while the
# page shown holds no row of the document's date naming its title. A press
# that does not move the list ends it, and the next download opens the
# documents page again first, so it starts from a list's first page.

NEXT_PAGE_LABEL = "Next page"
PAGINATION_LABEL = "Table pagination"
PAGE_MOVE_WAIT_S = 15

# Whether a download moved a list past its first page since the documents
# page was last opened.
_MOVED_ON = [False]

# Playwright's CSS reads through open shadow roots, and an attribute's value
# in brackets matches it exactly, capitals and spaces as written.
_NEXT_CSS = 'button[aria-label="%s"]' % NEXT_PAGE_LABEL
_PAGINATION_CSS = '[role="navigation"][aria-label="%s"]' % PAGINATION_LABEL
_NEXT_IN_PAGINATION_CSS = "%s %s" % (_PAGINATION_CSS, _NEXT_CSS)

# The pagination's words through its shadow root, which say the page shown
# ("Page 1 of 3"), compared before and after a press and never written down.
_PAGINATION_WORDS_JS = r"""nav => {
  const textOf = (el, d) => {
    if (d > 12) return '';
    let s = '';
    for (const n of el.childNodes) {
      if (n.nodeType === 3) s += ' ' + n.textContent;
      else if (n.nodeType === 1) s += ' ' + textOf(n, d + 1);
    }
    if (el.shadowRoot) s += ' ' + textOf(el.shadowRoot, d + 1);
    return s;
  };
  return textOf(nav, 0).replace(/\s+/g, ' ').trim().slice(0, 120);
}"""

# The rows the page shows of the titles `titles`, for any account, as
# [which title, what its row says], and whether any element prints the date
# `dates` gives in its forms, the way the row walk finds a date. An element
# printing a title, its whole words, its label or its own text nodes, is in
# the row of the nearest element above it that prints a date. A list's
# container prints every row's date, and a title in a row printing none
# reaches it. What a row says is compared in Python and never written down.
_SHOWS_JS = r"""([titles, dates, docName]) => {""" + _PRESS_JS + r"""
  const forms = dates.filter(Boolean);
  const dateRes = forms.map(d => new RegExp('(^|[^0-9/])' + esc(d) + '($|[^0-9/])'));
  const anyDate = /(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}|\b\d{1,2}\/\d{1,2}\/\d{2,4}\b|\b\d{4}-\d{2}-\d{2}\b/i;
  const res = titles.map(t => new RegExp('^\\s*' + esc(String(t).trim()) + '(\\s+pdf(\\s+for\\s+\\S.*)?)?\\s*$', 'i'));
  const which = (el) => {
    if (!el.getAttribute) return -1;
    const w = wordsIn(el);
    const shows = w.length < 200 ? w : '';
    const aria = (el.getAttribute('aria-label') || '').replace(/\s+/g, ' ').trim();
    const o = own(el);
    return res.findIndex(r => r.test(shows) || r.test(aria) || r.test(o));
  };
  const all = [];
  const walk = (el) => { for (const c of el.children) { all.push(c); if (c.shadowRoot) for (const s of c.shadowRoot.children) { all.push(s); walk(s); } walk(c); } };
  walk(document.body);
  const rows = [];
  for (const el of all) {
    if (rows.length >= 200) break;
    const i = which(el);
    if (i < 0 || !shown(el)) continue;
    for (let node = up(el), d = 0; node && node !== document.body && node !== document.documentElement && d < 12; node = up(node), d++) {
      const said = [];
      sayInto(node, 0, said);
      const text = said.join(' | ');
      if (anyDate.test(text)) { rows.push([i, text.slice(0, 4000)]); break; }
    }
  }
  const dated = all.some(el => (dateRes.some(r => r.test(own(el))) || forms.some(d => (el.innerText || '').trim() === d)) && shown(el));
  return {rows, dated};
}"""


def _row_date_forms(iso_date: str) -> List[str]:
    """The ways a row may print a date, as the row walk looks for it."""
    y, m, d = iso_date.split("-")
    return [f"{m}/{d}/{y}", f"{m}/{d}/{y[2:]}", _human_date(iso_date),
            f"{int(m)}/{int(d)}/{y}", f"{int(m)}/{int(d)}/{y[2:]}"]


def _shows_document(page, iso_date: str, title: str) -> Optional[bool]:
    """Whether the page may show the document, a row of this date naming
    this title for any account, or this date printed anywhere at all. False
    only when the page shows rows of the titles the lists gave, none of
    them is this one, and nothing prints its date, and None when it shows
    no such row it can read, or could not be read, since then the document
    may be there in a shape these rows do not take."""
    titles = [title] + sorted({t for ts in _LISTED_TITLES.values() for t in ts
                               if _norm(t) and _norm(t) != _norm(title)})[:40]
    forms = _row_date_forms(iso_date) + [iso_date]
    try:
        got = page.evaluate(_SHOWS_JS, [titles, forms, [title or "", "", False, False]])
    except Exception as e:
        log.info("could not read whether the page shows the document: %s", type(e).__name__)
        return None
    got = got if isinstance(got, dict) else {}
    rows = [r for r in got.get("rows") or [] if isinstance(r, list) and len(r) == 2]
    if not rows:
        return None
    return bool(got.get("dated")) or any(r[0] == 0 and iso_date in _dates_in(str(r[1])) for r in rows)


def _pagination_words(page) -> str:
    """What the list's pagination says, "" when it cannot be read."""
    try:
        return str(page.locator(_PAGINATION_CSS).first.evaluate(_PAGINATION_WORDS_JS) or "")
    except Exception:
        return ""


def _next_page(page, trace: Optional[list] = None) -> bool:
    """Press the list's Next page button once, and whether the list then
    moved. Pressed only when the page holds exactly one button whose
    aria-label is exactly NEXT_PAGE_LABEL, it sits inside the navigation
    labeled PAGINATION_LABEL, it is shown and on, turned off neither itself
    nor by aria-disabled, its words are clear of the guard, and the tab is
    on E*TRADE's site. Moved means a searchItems answer came, or the
    pagination's words changed. The trace says what was seen in counts and
    booleans."""
    note: dict = {"note": "next page"}
    if trace is not None:
        trace.append(note)
    try:
        everywhere = page.locator(_NEXT_CSS).count()
        inside = page.locator(_NEXT_IN_PAGINATION_CSS)
        here = inside.count()
        note.update(buttons=int(everywhere), in_the_pagination=int(here))
        if everywhere != 1 or here != 1:
            return False
        button = inside.first
        label = button.get_attribute("aria-label")
        off = str(button.get_attribute("aria-disabled") or "").strip().lower() == "true"
        on = bool(button.is_enabled()) and not off
        shown = bool(button.is_visible())
        words = str(button.inner_text(timeout=2000) or "")
    except Exception as e:
        note["error"] = type(e).__name__
        return False
    note.update(turned_on=on, shown=shown)
    if label != NEXT_PAGE_LABEL or not on or not shown:
        return False
    url = page.url if isinstance(page.url, str) else ""
    if not _guard_allows([words, label]) or not is_safe_url(url):
        note["refused"] = True
        return False
    before = _pagination_words(page)
    lists = [0]

    def on_response(res):
        try:
            if is_safe_url(res.url or "") and DOCS_API_RE.search(res.url or ""):
                lists[0] += 1
        except Exception:
            pass
    page.on("response", on_response)
    moved = False
    try:
        # From here the list may show another page, whatever comes of it.
        _MOVED_ON[0] = True
        button.click(timeout=5000)
        note["pressed"] = True
        for _ in range(PAGE_MOVE_WAIT_S * 2):
            page.wait_for_timeout(500)
            if lists[0] or _pagination_words(page) != before:
                moved = True
                break
        page.wait_for_timeout(1500)
    except Exception as e:
        note["error"] = type(e).__name__
        return False
    finally:
        try:
            page.remove_listener("response", on_response)
        except Exception:
            pass
    note["moved"] = moved
    return moved


def _page_with(page, iso_date: str, title: str, trace: Optional[list] = None) -> int:
    """Move the list on, by its Next page button, to the page that shows
    the document, and how many presses that took. Only for a document the
    lists gave, only while the page shown holds no row of its date naming
    its title (_shows_document), and at most MAX_PAGES - 1 times. A page
    that cannot be read stops it, and so does a press that did not move the
    list, and so does a page whose rows of the listed titles cannot be
    read. Whatever page it stops on, the steps after look for the document
    there and refuse as they always did when they cannot tell which row is
    its own."""
    if not title or _listed_docs(iso_date, title) < 1:
        return 0
    moved = 0
    while moved < MAX_PAGES - 1 and _shows_document(page, iso_date, title) is False:
        if not _next_page(page, trace):
            break
        moved += 1
    if trace is not None and moved:
        trace.append({"note": "the list was moved on to a later page", "pages": moved})
    return moved


def _first_page_again(page) -> bool:
    """Open the documents page again after a download moved its list past
    its first page, so this download looks from a list's first page, and
    whether it did. The page's own reload shows the first page of its
    default period, and show_period_for then chooses this document's. A tab
    that left the documents page is opened afresh by goto_documents. When
    the reload fails, the list may still show a later page, so the next
    download tries again (review)."""
    url = page.url or ""
    try:
        if is_safe_url(url) and "accountdocs" in url:
            page.reload(wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3000)
    except Exception as e:
        log.info("could not open the documents page again: %s", type(e).__name__)
        return False
    _MOVED_ON[0] = False
    return True


def download_bill(page, dl_dir, iso_date: str, out_path, title: str = "",
                  trace: Optional[list] = None, account: str = "") -> bool:
    """Save the document dated `iso_date` and titled `title`. The period
    picker is first set to the period that lists it. A PDF link on the row
    is fetched from inside the page. Otherwise the row's own control is
    clicked, once it has passed the guard, and whichever the site produces
    is caught, a download event or a PDF response, in this tab or one it
    opens. Each way of finding the row takes the one that names the
    document, and when it cannot tell which that is it presses nothing.

    `dl_dir` is where the attached browser saves a download, watched
    after every click.

    `account` is the account the list gave the document, what its Account
    column shows. While it is taken, a name that gives another account
    after "PDF for" is never its name, and when the lists did not give its
    date and title to this account alone, only a name giving this account
    exactly is, "<title> PDF for <account>" (names_title, _account_ok). Two
    accounts' statements of one day were one document, and of two rows
    naming it the download refused both, or took whichever one the page
    showed (#96).

    With no account, on a day the lists gave its title more than once or
    to more than one label, nothing is pressed (SHARED_WITH_NO_ACCOUNT).
    Every guard that reads the account passes a document of none, so of
    several accounts' statements of one title and day, the one row the page
    showed was taken for it, whichever account's it was (#96). Nor is it
    for one account's documents of one title and day, which no link tells
    apart (TWICE_FOR_ONE_ACCOUNT).

    A document the period's list holds on a later page is looked for on
    that page, the list moved on by its own Next page button while the page
    shown holds no row of its date naming its title (_page_with). It went to
    Manual Review (#96)."""
    _FOR.clear()
    if account and title:
        _FOR.update(date=iso_date, title=_norm(title), account=_norm(account))
    try:
        if not account and _shared_with_no_account(iso_date, title):
            _refuse(trace, "listed document", SHARED_WITH_NO_ACCOUNT, iso_date, 0, 0)
            return False
        if account and _places_still_listed(iso_date, title, account):
            _refuse(trace, "listed document", TWICE_FOR_ONE_ACCOUNT, iso_date, 0, 0)
            return False
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        # Every control pressed for this document, through every attempt below.
        tried: list = []
        if _MOVED_ON[0] and not _first_page_again(page):
            return False
        if not goto_documents(page):
            log.info("could not open the documents page for %s", iso_date)
            return False
        # The list shows one period at a time, whichever was applied last. That
        # used to be the oldest year, since this walked every period the way
        # discovery does, so the period that lists this document is chosen.
        if "accountdocs" in (page.url or ""):
            show_period_for(page, iso_date, trace)
            _page_with(page, iso_date, title, trace)
        el, label = _row_link_for(page, iso_date, title, trace)
        if el is not None and is_safe_control(label):
            unsure: list = []
            if _catch_pdf(page, el, label, out_path, trace, dl_dir, tried, unsure=unsure):
                return True
            # Turned off on the page, so nothing was pressed for the document,
            # and nothing else is pressed for it either. A press that may have
            # been made ends this document too, so its own control is not
            # pressed again (review of 0.45.0).
            if _TURNED_OFF in tried or unsure:
                return False
        expand_all(page)

        el, label = _control_for(page, iso_date, title, trace)
        if el is None:
            log.info("no document control by name for %s, looking for its row by date", iso_date)
            return _try_every_way(page, dl_dir, iso_date, out_path, title, trace, tried)
        if not is_safe_control(label):
            # By its date alone. A link's label can say "PDF for" an account.
            log.info("refusing an unsafe control for %s", iso_date)
            return False

        try:
            href = el.get_attribute("href") or ""
        except Exception:
            href = ""
        if href and not href.lower().startswith(("javascript", "#")):
            from paperpull_core.urls import join as join_url
            target = join_url(page.url, href)
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
        return _catch_pdf(page, el, label, out_path, trace, dl_dir, tried)
    finally:
        _FOR.clear()


# ---------------------------------------------------------------------------
# Diagnose. A survey a tester can attach to an issue. No screenshot, since a
# bank page shows names, numbers and balances. Digit runs are masked and
# JSON bodies are recorded as shape only.
# ---------------------------------------------------------------------------
_ROW_JS = r"""() => {
  const out = [];
  for (const tr of document.querySelectorAll('table tr, [role=row], li, [class*="bill" i]')) {
    const txt = (tr.innerText || '').trim();
    if (!txt) continue;
    const link = tr.querySelector("a[href]");
    out.push({text: txt.slice(0, 200), href: link ? link.getAttribute('href') : ''});
  }
  return out.slice(0, 200);
}"""

SURVEY_LINK_RE = re.compile(
    r"^\s*((see|view|show)\s+)?(statements?(\s+(and|&)\s+documents)?|documents|tax\s+(documents|forms|center)|statement\s+history|trade\s+confirmations?|confirmations?)\s*$", re.I)


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
    return out


def survey(page, dwell_ms: int = 4000, max_follow: int = 6) -> dict:
    """What the signed-in documents area looks like, without downloading
    anything. Records each page, its headings and controls with the
    guard's verdict on each, and every JSON or PDF response etrade.com sends
    while the page settles. Then follows, one at a time and back again,
    the few links whose text is a documents word. No screenshot."""
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
                    parsed = whole_json(_json.loads(body))
                    if isinstance(parsed, dict):
                        entry["post_keys"] = sorted(str(k) for k in parsed)[:30]
            except Exception:
                pass
            q = _safe_query(url)
            if q:
                entry["query"] = q[:240]
            if "json" in ct:
                try:
                    body = whole_json(res.json())
                    entry["shape"] = _shape(body)
                    if DOCS_API_RE.search(url):
                        items = (body or {}).get("defaultDocumentList") or (body or {}).get("resultList") or []
                        entry["date_shapes"] = sorted({date_shape(e.get("documentDate")) for e in items if isinstance(e, dict)})[:5]
                        entry["read_as"] = sorted({str(parse_api_date(e.get("documentDate"))) for e in items if isinstance(e, dict)})[:5]
                except Exception:
                    entry["shape"] = "unreadable"
            seen.append(entry)
        except Exception:
            pass

    page.on("response", on_response)
    report = {"pages": [], "responses": seen}
    try:
        page.wait_for_timeout(dwell_ms)
        start = _page_summary(page)
        report["pages"].append(start)
        followed = 0
        for c in start["controls"]:
            if followed >= max_follow or c["role"] not in ("link", "button") or not c["survey"]:
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
                # A control that opened a new tab (a document vendor behind
                # a single sign-on, a PDF) is surveyed there, then the tab
                # is closed. Off the provider's hosts it is still recorded,
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
                    page.go_back()
                    continue
                summary = _page_summary(page)
                summary["followed_from"] = c["text"]
                report["pages"].append(summary)
                followed += 1
                if page.url != before:
                    page.go_back(wait_until="domcontentloaded", timeout=15000)
                    page.wait_for_timeout(1500)
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
# ---------------------------------------------------------------------------
ALLOWED_HOSTS = {"etrade.com"}


def is_safe_url(url: str) -> bool:
    """True only for an https URL on one of this provider's own hosts.

    The check itself lives in the core, so all of them answer the same way.
    This app keeps the hosts, which is the part that really is its own."""
    return _host_allows(url, ALLOWED_HOSTS)
