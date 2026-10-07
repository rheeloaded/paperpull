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
from paperpull_core.controls import second_step as _core_second_step
from paperpull_core.controls import controls_named as _controls_named
from paperpull_core.controls import escape_for_locator
from paperpull_core.dates import checked as _checked_date
from paperpull_core.dates import full_year as _full_year
from paperpull_core import pressing
from paperpull_core.words import words_for as _words_for

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
DOCS_URL = f"{BASE}/etx/pxy/accountdocs#/documents"
# The date filter (second survey, #36) is a button reading its current
# choice, "Last 90 Days", that opens a list of periods. These are the
# only controls outside a document row the app touches, and each has to
# read as a period and nothing else. The widest period wins. A period is a
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
    "next_page": ("a[aria-label*='Next' i], button[aria-label*='Next' i], "
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
    """Close a cookie banner, a survey prompt or a promo overlay, the things
    that sit over bank pages and intercept clicks. Escape first, then
    only a control that says close or dismiss, never accept."""
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(250)
    except Exception:
        pass
    try:
        cl = page.get_by_role("button", name=re.compile(r"^(close|dismiss|no thanks|not now)\b", re.I))
        for i in range(min(cl.count(), 6)):
            el = cl.nth(i)
            try:
                if el.is_visible():
                    label = el.inner_text(timeout=500) or ""
                    if FORBIDDEN_CONTROL_RE.search(label) or SESSION_CONTROL_RE.search(label):
                        continue
                    el.click(timeout=1000)
                    page.wait_for_timeout(250)
            except Exception:
                continue
    except Exception:
        pass


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
    account: str = ""
    date_text: str = ""
    href: str = ""
    text: str = ""
    row_index: int = -1
    kind: str = "doc"


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


def _docs_from_api(body: dict) -> List[dict]:
    """The documents in one searchItems answer, as {date, title, kind,
    hint, account}. The guid rides as the hint. It names a document, not
    a person, and the download will need it."""
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
        out.append({"date": iso, "title": title, "kind": kind, "hint": hint,
                    "account": redact(str(e.get("displayMultipleAccounts") or ""))[:40]})
    return out


def goto_docs_capturing(page, capture: list) -> bool:
    """Open the Documents page while catching the searchItems answer that
    fills it, so discovery never has to know how the page asks."""
    def on_response(res):
        try:
            url = res.url or ""
            if is_safe_url(url) and DOCS_API_RE.search(url):
                capture.append(res.json())
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
    except Exception as e:
        log.info("goto documents failed: %s", e)
    finally:
        try:
            page.remove_listener("response", on_response)
        except Exception:
            pass
    dismiss_overlay(page)
    return is_safe_url(page.url or "") and not looks_signed_out(page)


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

        def on_response(res):
            try:
                if is_safe_url(res.url or "") and DOCS_API_RE.search(res.url or ""):
                    capture.append(res.json())
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
            clicked = _click_text(page, choice)
            entry["option_clicked"] = clicked
            if not clicked:
                entry["outcome"] = "option not found"
                page.keyboard.press("Escape")
                return False
            page.wait_for_timeout(1500)
            entry["apply_clicked"] = False
            apply = page.get_by_role("button", name=PERIOD_APPLY_RE)
            if apply.count() and apply.first.is_visible():
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


def _note_listed(bodies) -> None:
    """Count the documents per date in searchItems answers, and keep their
    titles."""
    for body in bodies or []:
        counts: dict = {}
        for d in _docs_from_api(body):
            counts[d["date"]] = counts.get(d["date"], 0) + 1
            _LISTED_TITLES.setdefault(d["date"], set()).add(d["title"])
        for day, n in counts.items():
            _LISTED[day] = max(_LISTED.get(day, 0), n)


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
    list, names nothing, so there the count decides."""
    if _LISTED.get(iso_date) != 1:
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


def collect_download_docs(page) -> List[RawDoc]:
    """Every document the Documents page lists, from the API answers the
    page loads for its default period and for every period the picker is
    set to, else the rows."""
    docs: List[RawDoc] = []
    seen = set()
    bodies: list = []
    trace = DISCOVERY_TRACE
    del trace[:]
    _LISTED.clear()
    _LISTED_TITLES.clear()
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
            for d in _docs_from_api(body):
                key = (d["date"], d["title"])
                if key in seen:
                    continue
                seen.add(key)
                tax = bool(re.search(r"1099|1098|5498|tax", d["title"] + " " + d["kind"], re.I))
                docs.append(RawDoc(title=d["title"], account=d["account"], date_text=d["date"],
                                   href=d["hint"], text=f"E*TRADE {d['title']} {_human_date(d['date'])}",
                                   kind="tax" if tax else "statement"))
        trace.append({"note": "discovery result", "documents": len(docs),
                      "dates": sorted({d.date_text for d in docs}, reverse=True)[:60]})
        if docs:
            return docs
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
    return docs


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

# Why a lookup refused, in the only words that may say so.
_REFUSALS = (
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
        if is_label and names_title(text, title):
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


def names_title(name: str, title: str) -> bool:
    """Whether a control's name or text names the document `title`. The
    whole of it is the title, the title then PDF, or the title then PDF for
    an account, the way his recording named the link. It used to accept the
    title then PDF then any words at all, so a cell holding the document's
    link beside the other document's, or an insert, passed for the
    document's own name, and the words after PDF never reached the guard
    (#36, review)."""
    if not title:
        return False
    name = re.sub(r"\s+", " ", name or "").strip()
    return bool(_title_name_re(title).match(name))


def _title_name_re(title: str):
    """names_title as a pattern, for a locator's accessible name."""
    return re.compile(r"^\s*" + escape_for_locator(title.strip()) + r"(\s+pdf(\s+for\s+\S.*)?)?\s*$", re.I)


def _guard_word(word: str, title: str = "") -> str:
    """One of an element's words as the guard reads it. A word that names
    the document loses the account after "PDF for", which is the account's
    name and not what the link does. Every other word is read whole."""
    w = re.sub(r"\s+", " ", word or "").strip()
    if w and names_title(w, title):
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
        named = [m for m in matches if any(names_title(w, title) for w in m[2])
                 and _guard_allows(m[2], title)]
        if len(named) == 1:
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
            return named[0][0], _guard_word(named[0][1], title)
        if len(named) > 1:
            _refuse(trace, "control", "more than one control of this date names this document",
                    iso, len(matches), len(named))
            return None, ""
    if len(matches) == 1 and _alone_that_day(iso, title) \
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
        if _says_only_an_action(mine) or _lone_control_may_be_pressed(around, iso, title, mine):
            return el, name
        _refuse(trace, "control", "the one control of this date may be for something else", iso, 1, 0)
        return None, ""
    _refuse(trace, "control", "no control of this date names this document" if title
            else "more than one control carries this date", iso, len(matches), 0)
    return None, ""


def _around(el, title: str) -> dict:
    """What _AROUND_CONTROL_JS says of one control, whether it presses only
    itself and what the row around it says, or {} when that could not be
    read, which every caller takes as a reason not to press it."""
    try:
        got = el.evaluate(_AROUND_CONTROL_JS, title or "")
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


def _click_text(page, text: str) -> bool:
    """Click the visible element whose whole text is `text`, by role
    first, then by text alone. The text has passed is_date_filter."""
    pat = re.compile("^\\s*" + escape_for_locator(text) + "\\s*$", re.I)
    for role in ("menuitem", "option", "radio", "menuitemradio", "button", "link", "tab"):
        try:
            opt = page.get_by_role(role, name=pat)
            if opt.count() and opt.first.is_visible():
                opt.first.click(timeout=5000)
                return True
        except Exception:
            continue
    try:
        loc = page.get_by_text(pat)
        for i in range(min(loc.count(), 6)):
            if loc.nth(i).is_visible():
                loc.nth(i).click(timeout=5000)
                return True
    except Exception:
        pass
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
    if names_title(t, title):
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


def _second_step(page, appeared: set):
    """A control the click revealed whose text says it finishes a download,
    once it has passed the guard, or None. The choosing is the core's, the
    words this provider uses and the guard are this app's."""
    return _core_second_step(page, appeared, _SECOND_STEP_RE, is_safe_control)


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
    import base64
    for text in _json_texts(value):
        text = _bare(text)
        if not text.startswith("JVBERi0") or len(text) > 60_000_000:
            continue
        try:
            # Strict, so text that only starts like a PDF is not decoded
            # into something that also only starts like one.
            data = base64.b64decode(text, validate=True)
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


def _catch_pdf(page, el, label: str, out_path: Path, trace: Optional[list] = None,
               dl_dir=None) -> bool:
    """Click `el` and save whatever PDF the site produces, a file landing
    in `dl_dir`, a download event, a PDF response, a new tab, this tab
    moving to the document, or a second control the click revealed. A PDF
    answer, or a JSON answer carrying one, is taken only when its request
    was made during this attempt, and for a redirect, the request it came
    from. A download event or a file landing in `dl_dir` is not tied to the
    click that way yet, so such an answer wins over them.
    `trace` collects what happened, the click's own outcome included."""
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
                        answer = res.json()
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
                body = resp.body() if resp.ok else b""
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
        # Playwright's own press, and through the page only when nothing
        # covered the control, its press never reached the page and nothing
        # it should bring came. What cannot be told stops the run, and the
        # control is never pressed twice (pressing.press_once).
        outcome = pressing.press_once(
            page, el, what="the control for this document", words=_words(),
            guard=is_safe_control, dl_dir=dl_dir,
            brought=lambda: bool(downloads or got or (_control_texts(page) - controls_before)))
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
        if wait_for_pdf(10):
            return True
        if _take_same_tab(page, start_url, out_path, trace):
            return True
        if _take_new_tab(page, [p for p in ctx.pages if p not in before], out_path):
            return True
        appeared = _control_texts(page) - controls_before
        if trace is not None:
            trace.append({"note": "after the click", "url": mask_href(page.url or ""),
                          "appeared": len(appeared),
                          "finishing_words": sorted({_fixed_word(t) for t in appeared} - {""})[:10],
                          "new_tabs": len([p for p in ctx.pages if p not in before])})
        step, step_label = _second_step(page, appeared)
        if step is not None:
            try:
                step.click(timeout=8000)
                if trace is not None:
                    trace.append({"note": "second step clicked", "words": _fixed_word(step_label) or "other"})
            except Exception as e:
                if trace is not None:
                    trace.append({"note": "second step click failed", "words": _fixed_word(step_label) or "other",
                                  "error": type(e).__name__})
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
    36792330947)."""
    looks = (row.get_by_role("link", name=_title_name_re(title)),
             row.get_by_role("link").filter(has_text=re.compile(
                 "^\\s*" + escape_for_locator(title.strip()) + "\\s*$", re.I)))
    unread, unmade = False, 0
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
            return el, False
    return None, unread or unmade == len(looks)


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
        named = []
        if title:
            for row in shown:
                link, missed = _named_link(row, title, trace)
                if missed:
                    unread += 1
                if link is not None:
                    named.append(link)
        if unread:
            _refuse(trace, "row link", unread_why, iso_date, len(shown), len(named))
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
                words += [w for w in (row.evaluate(_ROW_WORDS_JS, title or "") or []) if isinstance(w, str)]
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
# this in has the document's title, or "", in scope as `title`.
_PRESS_JS = r"""
  const own = (el) => Array.from(el.childNodes).filter(n => n.nodeType === 3).map(n => n.textContent.trim()).filter(Boolean).join(' ');
  const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const titleRe = title ? new RegExp('^\\s*' + esc(title.trim()) + '(\\s+pdf(\\s+for\\s+\\S.*)?)?\\s*$', 'i') : null;
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
  // pressed as the document's name (review). This decides every press.
  const namesTitle = (el) => {
    if (!titleRe || !el.getAttribute) return false;
    const t = wordsIn(el);
    const aria = (el.getAttribute('aria-label') || '').replace(/\s+/g, ' ').trim();
    return (t.length < 200 && titleRe.test(t)) || titleRe.test(aria);
  };
  // For choosing which row is the document's, an element whose own text
  // nodes are the title counts as well, a title printed beside smaller
  // words. It never decides what is pressed.
  const printsTitle = (el) => namesTitle(el) || (!!titleRe && !!el.getAttribute && titleRe.test(own(el)));
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
_ROW_BY_DATE_JS = r"""([dates, title, alone]) => {""" + _PRESS_JS + r"""
  const forms = dates.filter(Boolean);
  const dateRes = forms.map(d => new RegExp('(^|[^0-9/])' + esc(d) + '($|[^0-9/])'));
  const anyDate = /(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}|\b\d{1,2}\/\d{1,2}\/\d{2,4}\b|\b\d{4}-\d{2}-\d{2}\b/gi;
  // The innermost visible elements under `root` that print the title, to
  // choose the row by. What is pressed in it is decided by namesTitle.
  const titled = (root) => {
    const found = new Set();
    const go = (el, d) => {
      if (d > 20) return;
      for (const c of inside(el)) {
        if (!c.getAttribute) continue;
        if (printsTitle(c) && shown(c)) found.add(c);
        go(c, d + 1);
      }
    };
    go(root, 0);
    const list = Array.from(found);
    return list.filter(a => !list.some(b => b !== a && a.contains(b)));
  };
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
  let row = null, why = '';
  if (!titleRe) {
    if (rows.length === 1) row = rows[0];
    else why = rows.length ? 'more than one row carries this date' : 'no row around this date';
  } else if (named.length === 1) row = named[0];
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
_AROUND_CONTROL_JS = r"""(el, title) => {""" + _PRESS_JS + r"""
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
_ROW_WORDS_JS = r"""(row, title) => {""" + _PRESS_JS + r"""
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
    y, m, d = iso_date.split("-")
    dates = [f"{m}/{d}/{y}", f"{m}/{d}/{y[2:]}", _human_date(iso_date),
             f"{int(m)}/{int(d)}/{y}", f"{int(m)}/{int(d)}/{y[2:]}"]
    try:
        h = page.evaluate_handle(_ROW_BY_DATE_JS, [dates, title or "", _alone_that_day(iso_date, title)])
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
            own = next((t for t in sorted(titles) if any(names_title(w, t) for w in words)), title)
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


def _tick_and_download(page, box, dl_dir, out_path: Path, trace: Optional[list]) -> bool:
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
        return _catch_pdf(page, shown[0], "Download", out_path, trace, dl_dir)
    finally:
        if ticked_here and _box_state(box) == "ticked":
            try:
                box.click(timeout=4000)
                note({"note": "this document's box was cleared again"})
            except Exception as e:
                note({"note": "this document's box could not be cleared", "error": type(e).__name__})


def _try_every_way(page, dl_dir, iso_date: str, out_path: Path, title: str, trace: Optional[list]) -> bool:
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
    Download button goes through _tick_and_download."""
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
                    parsed = _json.loads(body)
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
        for i in order[:6]:
            c, el = cands[i], els[i]
            if el is None:
                continue
            label = _guard_word(c["text"] or c["aria"], title) or title or "document"
            if trace is not None:
                trace.append({"note": "trying", "kind": c["kind"]})
            tried += 1
            if _catch_pdf(page, el, label, out_path, trace, dl_dir):
                return True
            if trace is not None and requests:
                trace.append({"note": "requests after that click", "requests": requests[-12:]})
                requests.clear()
        # The row's box and the page's own Download button, only in a row
        # that holds this document alone, which means one box at most.
        boxes = [i for i, c in enumerate(cands) if c["kind"] == "checkbox" and not left_out(i)]
        if boxes and els[boxes[0]] is not None:
            if trace is not None:
                trace.append({"note": "trying", "kind": "checkbox then Download"})
            if _tick_and_download(page, els[boxes[0]], dl_dir, out_path, trace):
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


def download_bill(page, dl_dir, iso_date: str, out_path, title: str = "",
                  trace: Optional[list] = None) -> bool:
    """Save the document dated `iso_date` and titled `title`. The period
    picker is first set to the period that lists it. A PDF link on the row
    is fetched from inside the page. Otherwise the row's own control is
    clicked, once it has passed the guard, and whichever the site produces
    is caught, a download event or a PDF response, in this tab or one it
    opens. Each way of finding the row takes the one that names the
    document, and when it cannot tell which that is it presses nothing.

    `dl_dir` is where the attached browser saves a download, watched
    after every click."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if not goto_documents(page):
        log.info("could not open the documents page for %s", iso_date)
        return False
    # The list shows one period at a time, whichever was applied last. That
    # used to be the oldest year, since this walked every period the way
    # discovery does, so the period that lists this document is chosen.
    if "accountdocs" in (page.url or ""):
        show_period_for(page, iso_date, trace)
    el, label = _row_link_for(page, iso_date, title, trace)
    if el is not None and is_safe_control(label):
        if _catch_pdf(page, el, label, out_path, trace, dl_dir):
            return True
    expand_all(page)

    el, label = _control_for(page, iso_date, title, trace)
    if el is None:
        log.info("no document control by name for %s, looking for its row by date", iso_date)
        return _try_every_way(page, dl_dir, iso_date, out_path, title, trace)
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
    return _catch_pdf(page, el, label, out_path, trace, dl_dir)


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
                    body = res.json()
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
