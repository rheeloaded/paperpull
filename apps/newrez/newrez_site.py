"""ALL newrez.com selectors, URLs, and page behavior live here.

When Newrez changes its site, repair this file only.

STATUS: CONFIRMED on the tester's account (#38). Written without a Newrez
account and repaired from two surveys, failure files and a recording one
tester sent. Discover reads each year the statements page's year picker
offers, and on his account it walked three years and every document
downloaded, named for the dates printed on them. On a first run it is
deliberately cautious.

  * --login opens a real Edge or Chrome, since Newrez's portal is happiest in a real browser.
  * --diagnose surveys whatever the documents page turns out to be,
    records its headings, its controls with the guard's verdict on each,
    and the shape of every JSON response, with digit runs masked, and
    takes no screenshot. That file is what a tester attaches to the
    GitHub issue.
  * --discover reads dates from any control that looks like a
    monthly statement, escrow analysis or 1098, wherever it sits on the page,
    and then chooses each year the statements page's year picker offers
    and reads that year's list once it is on screen (RECORDED, #38).
  * --pilot tries to save the newest few, by fetching a PDF link the row
    carries from inside the page, or by clicking the row's own control
    and catching a download event, a PDF response or a new tab.

What a tester's files showed is marked RECORDED, and the guesses that are
left are marked GUESS.

SAFETY (this is a mortgage account with a bank account on file):
  This module is strictly READ-ONLY. It opens the documents area, reads
  the list, and saves the PDFs Newrez already generated. It must NEVER
  activate any control that pays, schedules or sets up autopay, requests
  a payoff, an escrow change, hardship help, forbearance or a
  modification, uploads anything, or edits any setting.
  FORBIDDEN_CONTROL_RE is the guard. A control must ALSO look like a
  document action (SAFE_DOC_CONTROL_RE) before it may be clicked. There
  is no code here that submits a form or confirms a dialog.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

from paperpull_core.controls import SETTINGS_CONTROL_RE, AUTH_CONTROL_RE, MONEY_CONTROL_RE
from paperpull_core.controls import IDENTITY_JS as _CORE_IDENTITY_JS
from paperpull_core.controls import is_forbidden_context

# Everything on its way into a diagnostic file goes through here. It
# lives in core because seventeen apps each had their own copy and
# they drifted into three different versions.
from paperpull_core.redact import redact, set_private_words  # noqa: F401
from paperpull_core.urls import is_safe_url as _host_allows
from paperpull_core.api_census import shape_of as _shape
from paperpull_core.dates import last_day as _last_day
from paperpull_core.dates import human_date as _human_date
# re-exported: this app's docs module calls it as site.set_download_dir
from paperpull_core.capture import set_download_dir  # noqa: F401
from paperpull_core.capture import snapshot as _snapshot
from paperpull_core.capture import take_download as _take_download
from paperpull_core.capture import clear_copies as _clear_copies
from paperpull_core.capture import arrived as _arrived
from paperpull_core.capture import UNFINISHED as _UNFINISHED
from paperpull_core.capture import fetch_pdf as _core_fetch_pdf
from paperpull_core.capture import take_new_tab as _core_take_new_tab
from paperpull_core.capture import take_same_tab as _core_take_same_tab
from paperpull_core.controls import control_texts as _control_texts
from paperpull_core.controls import second_step as _core_second_step
from paperpull_core.controls import controls_named as _controls_named
from paperpull_core.controls import escape_for_locator
from paperpull_core.dates import checked as _checked_date
from paperpull_core.dates import full_year as _full_year

log = logging.getLogger("newrez_docs.site")

BASE = "https://myaccount.newrez.com"
# From the first survey (#38, 2026-09-20). Sign-in lands on /dashboard,
# a landing page with "Access My Loan" and "Account Details" controls and
# no statements on it. The /documents and /statements guesses went back
# to the dashboard. The loan itself, and its statements, sit behind those
# two controls, which the survey follows this round. The route guesses
# stay first in case one of them is where "Access My Loan" goes.
BILLING_CANDIDATES = [
    f"{BASE}/dashboard",
]
# From the second survey (#38). "Account Details" on the dashboard goes to
# the servicing app at servicing.newrez.com/servicing/<loan number>/
# dashboard, and the tester found the statements at
# /servicing/<loan number>/statements/monthly and the 1098 at
# /servicing/<loan number>/statements/yearly. The loan number is read off
# the servicing address at run time and never stored in the code. Both
# pages answered with an API error on Newrez's side the day the survey
# was taken, which this app can only report, not fix.
SERVICING = "https://servicing.newrez.com"
LOAN_IN_URL_RE = re.compile(r"/servicing/(\d{6,})/")
ACCOUNT_DETAILS_RE = re.compile(r"^\s*account\s+details\s*$", re.I)
STATEMENT_PAGES = ("/statements/monthly", "/statements/yearly")
BILLING_URL = BILLING_CANDIDATES[0]
URLS = {
    "home": f"{BASE}/dashboard",
    "login": BILLING_URL,
    "documents": BILLING_URL,
    "statements": BILLING_URL,
}

LOGIN_URL_MARKERS = ["/login", "/signin", "/sign-in", "/auth/", "/mfa",
                     "/verification", "/challenge", "/authenticate"]

# ---------------------------------------------------------------------------
# HARD SAFETY GUARD. Tuned for mortgage servicer, on top of the bank words. Never move
# money, never change service or coverage, never change a setting.
# ---------------------------------------------------------------------------
FORBIDDEN_CONTROL_RE = re.compile(
    r"(transfer|zelle|\bwire\b|\bpay\b|payment|bill\s*pay|autopay|auto\s*pay|"
    r"deposit|withdraw|send\s+money|request\s+money|move\s+money|"
    r"\bapply\b|open\s+(an?\s+)?account|close\s+account|(apply\s+for|get|new|take\s+out)\s+(a\s+)?loan|\bborrow|"
    r"\bcard\b|\bcards\b|replace|activate|lock|unlock|\bpin\b|limit|"
    r"overdraft|alerts?\b|\bbudget|\bgoal|\brewards?\b|\boffers?\b|"
    r"enroll|unenroll|sign\s+up|paperless|delivery\s+preference|"
    r"enable|disable|change\b|edit\b|update\b|modify|manage\b|"
    r"set\s+up|delete|remove|cancel|dispute|"
    r"password|passcode|username|profile\b|settings|preferences|contact\s+info|\baddress\b|"
    r"confirm\b|submit|agree|accept|authorize|\bchat\b|contact\s+us|"
    r"beneficiar|nickname|order\s+checks|stop\s+payment|"
    r"payoff|pay\s*off|escrow\s+(change|analysis\s+request)|hardship|forbearance|deferment|modification|refinanc|\bapply\b|request\b|upload|assistance|insurance\s+(change|update)|recast)", re.I)

SAFE_DOC_CONTROL_RE = re.compile(
    r"(download|view|open|print|\bpdf\b|statement|document|\bletter\b|notice|"
    r"1099|1098|5498|tax\s+(form|document)|history|"
    r"escrow\s+(analysis|statement)|access\s+my\s+loan|account\s+details|loan\s+details|my\s+loan|see\s+(more|all|older)|show\s+(more|all|older)|load\s+more)", re.I)

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
# "09/2026", a month and a year without a day. Without this a page that
# dates its statements that way collapses every one of them onto the last
# day of the year and all but one is dropped as a duplicate (#38).
MONTH_SLASH_YEAR_RE = re.compile(r"\b(0?[1-9]|1[0-2])/((?:19|20)\d{2})\b")


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
    m = MONTH_SLASH_YEAR_RE.search(text)
    if m:
        month, year = int(m.group(1)), int(m.group(2))
        return f"{year:04d}-{month:02d}-{_last_day(year, month):02d}", m.group(0)
    m = YEAR_RE.search(text)
    if m:
        year = int(m.group(1) + m.group(2))
        return f"{year:04d}-12-31", str(year)
    return None, ""


# The statements list dates a row by its month and year and nothing finer,
# so a statement is first filed under the last day of that month. The
# statement itself prints its own date beside this label, as the model form
# for a mortgage statement does. The day differs from account to account,
# so it is read off each statement rather than assumed (#38).
STATEMENT_DATE_RE = re.compile(r"statement\s*date\s*:?", re.I)
# How far past the label the date may sit. A header printed as a row of
# labels over a row of values puts the first value more than forty
# characters past the label. A date that far away names a file only when
# it falls in the row's own month, and statement_verdict says when one
# may refuse a file.
STATEMENT_DATE_REACH = 80


def statement_dates(text: str) -> List[str]:
    """The first date after each "Statement Date" label, in the order the
    labels appear, as YYYY-MM-DD."""
    out: List[str] = []
    text = text or ""
    for m in STATEMENT_DATE_RE.finditer(text):
        window = text[m.end():m.end() + STATEMENT_DATE_REACH]
        # The earliest date in any of the forms the reader knows, rather
        # than the first form found, which could skip past the real one.
        hits = [h for h in (p.search(window) for p, _kind in DATE_PATTERNS) if h]
        if not hits:
            continue
        first = min(hits, key=lambda h: h.start())
        found = parse_date(first.group(0))
        if found:
            out.append(found)
    return out


def _dates_in(window: str) -> List[str]:
    """Every date in `window` the reader knows, as YYYY-MM-DD."""
    out = []
    for pattern, _kind in DATE_PATTERNS:
        for m in pattern.finditer(window):
            found = parse_date(m.group(0))
            if found:
                out.append(found)
    return out


def _dates_near_statement_label(text: str) -> set:
    """Every date within reach after any "Statement Date" label."""
    text = text or ""
    near = set()
    for m in STATEMENT_DATE_RE.finditer(text):
        near.update(_dates_in(text[m.end():m.end() + STATEMENT_DATE_REACH]))
    return near


# Spaces and tabs only, so the label never reaches onto the next line.
DUE_DATE_RE = re.compile(r"due[ \t]*date[ \t]*:?", re.I)


def _due_dates(text: str) -> set:
    """The dates a "Due Date" label names on its own line, the label then
    only spaces or a colon and then the date. A date on the line below
    could belong to any label in a row of them, so it is not one."""
    text = text or ""
    out = set()
    for m in DUE_DATE_RE.finditer(text):
        window = text[m.end():m.end() + 40]
        hits = [h for h in (p.search(window) for p, _kind in DATE_PATTERNS) if h]
        if not hits:
            continue
        first = min(hits, key=lambda h: h.start())
        if window[:first.start()].strip(" \t:"):
            continue
        found = parse_date(first.group(0))
        if found:
            out.add(found)
    return out


def printed_statement_date(text: str, row_iso: str) -> str:
    """The date a statement prints beside "Statement Date", as YYYY-MM-DD,
    or "".

    Only the first date after the first label that has one is read, and
    it is believed only when it falls in the month the statement's row
    names. A due date on the first of the next month, or a label with no
    date after it, leaves the file under the month's own date, as it was."""
    month = (row_iso or "")[:7]
    if not re.fullmatch(r"\d{4}-\d{2}", month):
        return ""
    dates = statement_dates(text)
    return dates[0] if dates and dates[0][:7] == month else ""


# What the date inside a saved statement says about which row it belongs
# to. Fixed words, because the verdict goes into the failure file.
STATEMENT_VERDICTS = ("this month", "no date", "unclear", "another row", "another month",
                      "a tax form")
# A 1098 prints no Statement Date, so one whose download arrived late,
# during a statement's capture, read as "no date" and was kept as that
# statement.
FORM_1098_RE = re.compile(r"\bform\s*1098\b", re.I)


def statement_verdict(text: str, row_iso: str, other_months) -> str:
    """Whether a saved statement is the one its row asked for, read from
    the dates after "Statement Date" inside it.

    "another row" refuses a file, as "a tax form" below does. The first
    date after the label is in the month of another statement on the list,
    no date within reach after any such label is in the row's own month,
    and the date is not one a "Due Date" label names on its own line. That
    is what a statement taken by the wrong capture looks like, a download
    the capture before gave up on arriving during this one (#38).

    Captures run newest first, so a late download is always a newer
    statement landing in an older row's capture, and none of its dates is
    in the older row's month. A date in the row's own month anywhere near
    the label therefore means the reading is out of order, the due date
    read first say, and the verdict is "unclear" rather than a refusal,
    since a refused statement is fetched again on every run. The row's own
    due date read first is "another month" for the same reason, and so is
    a date in a month the list does not show. `other_months` holds YYYY-MM
    for every other statement on the list.

    "a tax form" refuses a file too. It says Form 1098 and prints no
    Statement Date, which a statement always does, so it is a 1098 whose
    download arrived during a statement's capture."""
    month = (row_iso or "")[:7]
    dates = statement_dates(text)
    if not dates and FORM_1098_RE.search(text or ""):
        return "a tax form"
    if not dates or not re.fullmatch(r"\d{4}-\d{2}", month):
        return "no date"
    first = dates[0]
    if first[:7] == month:
        return "this month"
    if any(d[:7] == month for d in _dates_near_statement_label(text)):
        return "unclear"
    if first[:7] in set(other_months or ()) - {month} and first not in _due_dates(text):
        return "another row"
    return "another month"


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
    if FORBIDDEN_CONTROL_RE.search(name):
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
                    if FORBIDDEN_CONTROL_RE.search(label):
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
    return bool(re.search(r"statements?\s+(and|&)\s+documents|statement\s+(period|date)|tax\s+(documents|forms)|escrow\s+analysis|\b1098\b",
                          body, re.I))


def loan_number(page) -> str:
    """The loan number in the servicing app's address, or ""."""
    m = LOAN_IN_URL_RE.search(page.url or "")
    return m.group(1) if m else ""


def goto_servicing(page) -> bool:
    """Be in the servicing app. From the dashboard, "Account Details" is
    the way in, once it has passed the guard."""
    if "servicing.newrez.com" in (page.url or "") and loan_number(page):
        return True
    try:
        page.goto(f"{BASE}/dashboard", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(4000)
        dismiss_overlay(page)
        loc = page.get_by_role("button", name=ACCOUNT_DETAILS_RE).or_(page.get_by_role("link", name=ACCOUNT_DETAILS_RE))
        if loc.count() == 0:
            return False
        label = (loc.first.inner_text(timeout=1000) or "").strip()
        if not is_safe_control(label):
            return False
        loc.first.click(timeout=5000)
        for _ in range(40):
            page.wait_for_timeout(500)
            if loan_number(page):
                page.wait_for_timeout(2000)
                return True
    except Exception as e:
        log.info("could not reach the servicing app: %s", e)
    return False


def goto_documents(page) -> bool:
    """Open the monthly statements page of the servicing app. The loan
    number comes off the address once "Account Details" has led there."""
    global BILLING_URL
    dismiss_overlay(page)
    if goto_servicing(page):
        loan = loan_number(page)
        url = f"{SERVICING}/servicing/{loan}{STATEMENT_PAGES[0]}"
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(5000)
            dismiss_overlay(page)
            if not looks_signed_out(page) and is_safe_url(page.url or ""):
                BILLING_URL = url
                return True
        except Exception as e:
            log.info("goto statements failed: %s", e)
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
# The row a control sits in, found by walking up until the text carries
# something that dates it.
#
# Round three asked for a full date and a mortgage statement list does
# not print one. The tester's page is nine statements, each a View and a
# Download whose address is `javascript:void(0)`, and discovery reported
# nothing at all because no ancestor of any of them held a day of a
# month. A month and a year dates a monthly statement, and a year alone
# dates a 1098, so both count now (#38).
_ROW_OF_JS = r"""el => {
  const dateRe = /(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}|\d{1,2}\/\d{1,2}\/\d{2,4}|\d{4}-\d{2}-\d{2}|(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4}|\d{1,2}\/(19|20)\d{2}\b|\b(19|20)\d{2}\b/i;
  let node = el, depth = 0, widest = '';
  while (node && depth < 8) {
    const txt = (node.innerText || '').trim();
    if (dateRe.test(txt)) { widest = txt.slice(0, 300); break; }
    node = node.parentElement; depth++;
  }
  return widest;
}"""


def collect_download_docs(page, walk: Optional[dict] = None) -> List[RawDoc]:
    """Every statement on the monthly page, then every 1098 on the yearly
    page. Each control's own name, or the row it sits in, carries the
    date. A page that shows an error instead of a list is said so.

    What a page shows first is read as it always was, and then the list
    for every year its year picker offers, since the monthly page shows
    one year at a time (#38). `walk` collects what each page's picker
    gave, in counts and fixed words, for the discovery line."""
    docs: List[RawDoc] = []
    seen: set = set()
    loan = loan_number(page)
    for path in STATEMENT_PAGES:
        if loan:
            try:
                page.goto(f"{SERVICING}/servicing/{loan}{path}", wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(5000)
                dismiss_overlay(page)
            except Exception as e:
                log.info("goto %s failed: %s", path, e)
                continue
        try:
            body = page.locator("body").inner_text(timeout=5000)
            if re.search(r"api\s+error|something\s+went\s+wrong|unable\s+to\s+(load|retrieve)|try\s+again\s+later", body, re.I):
                log.info("%s shows an error instead of a list, which is on Newrez's side", path)
        except Exception:
            pass
        _read_rows(page, docs, seen)
        facts = _walk_years(page, docs, seen)
        if walk is not None:
            walk[path.rsplit("/", 1)[-1]] = facts
        if not loan:
            break
    return docs


# Every document control's name, its link and the row around it, read in
# one call. Read one control at a time, a list drawn again with fewer rows
# after the count was taken left each control that had gone to wait out
# Playwright's thirty second default.
_CONTROL_ROWS_JS = ("els => els.map(el => [(el.getAttribute('aria-label') || el.innerText || '')"
                    ".trim(), el.getAttribute('href') || '', (" + _ROW_OF_JS + ")(el)])")


def _read_rows(page, docs: List[RawDoc], seen: set) -> None:
    expand_all(page)
    scroll_full_page(page)
    try:
        every = _bill_controls(page).evaluate_all(_CONTROL_ROWS_JS)
    except Exception:
        every = []
    for i, got in enumerate(every if isinstance(every, list) else []):
        if not isinstance(got, list) or len(got) != 3:
            continue
        name, href, row = (str(v or "") for v in got)
        if not is_safe_control(name):
            continue
        row_text = ""
        # A month and a year is a date for a monthly statement, and a year
        # alone is one for a 1098, so the period reader is used rather than
        # the one that insists on a day (#38).
        iso, _period = parse_period_date(name)
        if not iso:
            row_text = row
            iso, _period = parse_period_date(row_text)
        if not iso:
            continue
        tax = bool(re.search(r"1099|1098|5498|tax|yearly", name + " " + row_text + " " + (page.url or ""), re.I))
        # A December statement and that year's 1098 are both dated the
        # last day of the year. Kept by the date alone, the 1098, read
        # second, would be dropped as a copy of the statement now that
        # every year's statements are read (#38). A row's View and
        # Download, and a hidden copy of the list, are still one document.
        if (tax, iso) in seen:
            continue
        seen.add((tax, iso))
        disp = _human_date(iso)
        kind_title = "Tax Document" if tax else "Mortgage Statement"
        docs.append(RawDoc(title=f"{kind_title} - {disp}", date_text=iso,
                           href=href if PDF_HREF_RE.search(href or "") else "",
                           text=f"Newrez {kind_title} {disp}", row_index=i,
                           kind="tax" if tax else "statement"))


def _control_for(page, iso: str, info: Optional[dict] = None):
    """The control for the document dated `iso`, matched the same way
    discovery found it, or None.

    A control on screen wins over a hidden copy of the same row. When the
    accessible names match nothing the controls are found by their words,
    and that finds a hidden twin of the list too (a phone layout kept in
    the page, say), which cannot be clicked like a person would (#38).
    `info` collects what was seen, for the trace."""
    ctrls = _bill_controls(page)
    try:
        n = ctrls.count()
    except Exception:
        n = 0
    dates: list = []
    visible = 0
    shown_match = hidden_match = None
    same_date = 0
    for i in range(n):
        el = ctrls.nth(i)
        try:
            name = (el.get_attribute("aria-label") or el.inner_text(timeout=800) or "").strip()
        except Exception:
            name = ""
        found, _period = parse_period_date(name)
        if not found:
            try:
                found, _period = parse_period_date(el.evaluate(_ROW_OF_JS) or "")
            except Exception:
                found = None
        try:
            shown = bool(el.is_visible())
        except Exception:
            shown = False
        visible += shown
        dates.append(found or "none")
        if found != iso:
            continue
        same_date += 1
        if shown and shown_match is None:
            shown_match = (el, name)
        elif not shown and hidden_match is None:
            hidden_match = (el, name)
    chosen = shown_match or hidden_match
    if info is not None:
        info.update({"controls": n, "visible": visible,
                     "dates_read": [redact(d) for d in dates[:30]],
                     "same_date": same_date})
        if chosen:
            info["chosen"] = redact(chosen[1])[:60]
            info["chosen_visible"] = chosen is shown_match
    return chosen if chosen else (None, "")


# ---------------------------------------------------------------------------
# The year picker on the statements page
# ---------------------------------------------------------------------------
# RECORDED (#38, 2026-09-27). The monthly page shows one year's statements
# at a time, and a year picker above the list shows another. His 0.37.1
# runs found only this year's statements, and his recording chose 2025,
# then 2024, and pressed Download on December 2024. The picker is a select
# with no id, no name and no label tied to it, inside a form that holds
# nothing else, beside a label that is not linked to it. So it is known by
# what it offers, every option a year.
#
# It has four options, and what the first says was not recorded. The
# first has no id and the other three have one, and his 2024 list held
# seven statements, which fits a loan whose first statement came in the
# middle of 2024. So the years with statements are 2024, 2025 and 2026,
# the three he named, and the first option is taken to be a placeholder
# such as Select Year (GUESS). One leading option that is not a year is
# allowed when every other option is one. It is never chosen and never
# counted as a year. A first option that is a year works as well, and a
# select with two options that are not years, or one anywhere but first,
# is not a picker, which the discovery line says with its counts.
#
# His recording saw no call to newrez.com while he chose the years, and
# seven calls to other hosts over the whole recording, so the list is
# drawn again from an answer that comes back a moment after the choice.
# Until it does, the list on screen is still the last year's, and every
# row looks alike. A year's list is read only once every dated row on
# screen is in that year and two readings a second apart agree.
YEAR_OPTION_RE = re.compile(r"^(19|20)\d{2}$")
# How long a year's list may take to replace the last one. The recording
# pressed Download about two seconds after choosing 2024. A year with no
# statement never shows one, so this is also what an empty year costs.
YEAR_WAIT_S = 20
# How long a page with a dropdown that offers something other than years
# is given for its options to become years, in case they arrive after the
# list (GUESS).
PICKER_WAIT_S = 5
# How long capture lets the picker sit with no list drawn before choosing
# anyway, for a year with no statement yet, early in January say. Never
# for the newest year offered, whose list is the one the page draws first.
PICKER_IDLE_S = 8
# How long Playwright may take to choose the year.
YEAR_CHOICE_TIMEOUT_MS = 8000

# What the look for a picker found and why one was not used, and what
# became of each year of a walk. Fixed words, since they go into the
# discovery line, the journal and the failure file.
_PICKER_STATES = ("found", "none", "refused", "more than one", "hidden",
                  "not on a statements page")
_PICKER_REFUSALS = ("the shared filter refused it", "it could not be read",
                    "it takes more than one choice", "it is disabled", "it is not in a form",
                    "its form has more to fill in", "its words name an action")
_WALK_OUTCOMES = ("shown", "never showed", "could not be chosen", "changed before the choice",
                  "not offered", "no picker")

# A select's options, the one chosen, whether it is in a form and whether
# anything else in that form can be filled in or pressed, and its words,
# read in one call. Its words are its own names, its form's, the label
# nearest it and the nearest heading above it, and never a class name. A
# class says how a thing looks. The core's identity check
# reads class names, and this app's forbidden words refuse "card" and
# "lock", so a picker inside a styling class of "card" or "d-block" would
# be refused, and a refused picker looks like an account with one year.
# It only reads.
_SELECT_FACTS_JS = r"""el => {
  const texts = Array.from(el.options || []).map(o => (o.text || '').replace(/\s+/g, ' ').trim());
  const form = el.form || el.closest('form');
  let others = 0;
  if (form) {
    for (const c of Array.from(form.elements || [])) {
      const tag = (c.tagName || '').toLowerCase();
      if (c === el || tag === 'fieldset' || tag === 'output' || tag === 'object') continue;
      if (tag === 'input' && (c.type || '').toLowerCase() === 'hidden') continue;
      others += 1;
    }
    others += form.querySelectorAll('[role=button], [role=textbox], [role=checkbox], '
                                    + '[role=radio], [role=switch], [contenteditable]').length;
  }
  const words = ['id', 'name', 'aria-label', 'title', 'placeholder', 'data-testid']
    .map(a => el.getAttribute(a) || '');
  for (const id of (el.getAttribute('aria-labelledby') || '').split(/\s+/)) {
    const t = id ? document.getElementById(id) : null;
    if (t) words.push((t.innerText || t.textContent || '').trim().slice(0, 80));
  }
  for (const l of Array.from(el.labels || [])) words.push((l.innerText || '').trim().slice(0, 80));
  if (form) for (const a of ['id', 'name', 'aria-label', 'action']) words.push(form.getAttribute(a) || '');
  let node = el, near = '';
  for (let i = 0; i < 5 && node && !near; i++) {
    node = node.parentElement;
    const l = node ? node.querySelector('label, legend') : null;
    if (l) near = (l.innerText || l.textContent || '').trim().slice(0, 80);
  }
  words.push(near);
  let heading = '';
  node = el;
  for (let i = 0; i < 12 && node && !heading; i++) {
    node = node.parentElement;
    if (!node) break;
    const above = Array.from(node.querySelectorAll('h1, h2, h3, h4, h5, h6')).filter(h =>
      (h.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING)
      && (h.innerText || h.textContent || '').trim());
    if (above.length) {
      const h = above[above.length - 1];
      heading = (h.innerText || h.textContent || '').trim().slice(0, 80);
    }
  }
  words.push(heading);
  const box = el.getBoundingClientRect();
  const style = getComputedStyle(el);
  return {options: texts.slice(0, 40),
          chosen: el.selectedIndex >= 0 ? (texts[el.selectedIndex] || '') : '',
          others: others, in_form: !!form, words: words.filter(Boolean).join(' | ').slice(0, 400),
          visible: box.width >= 1 && box.height >= 1 && style.display !== 'none'
                   && style.visibility !== 'hidden',
          enabled: !el.matches(':disabled'), multiple: !!el.multiple, connected: el.isConnected};
}"""

# A select's facts beside the core's reading of what it is, the identity
# every app's dropdowns are filtered by, read together so they describe
# one element at one moment. And the same for every select on the page.
_ONE_SELECT_JS = "el => [(" + _SELECT_FACTS_JS + ")(el), (" + _CORE_IDENTITY_JS + ")(el)]"
_ALL_SELECTS_JS = "els => els.slice(0, 12).map(" + _ONE_SELECT_JS + ")"
# The core's filter is asked with its own rules, money and sign-in words
# and a control that will not say what it is. This app's forbidden words
# were written for the words on a button, "card" and "lock" among them,
# and the core's identity carries class names, where "mat-card" or
# "d-block" says how a thing looks. Asked with them, the filter would
# refuse the picker inside most styled pages. _picker_refusal applies
# those words to the words that name the control.
_SHARED_FILTER = "the shared filter refused it"

# Every document control's name, the text around it that carries a date,
# and whether it is on screen, all read in one call. A list that is being
# drawn again can lose rows between two calls, and asking Playwright for
# the nth control once there are fewer than n waits out its whole timeout,
# thirty seconds for each row that went, which is what a list whose old
# rows animate out did to the first version of this.
_DATED_CONTROLS_JS = ("els => els.slice(0, 80).map(el => { const b = el.getBoundingClientRect(),"
                      " s = getComputedStyle(el); return [(el.getAttribute('aria-label')"
                      " || el.innerText || '').trim(), (" + _ROW_OF_JS + ")(el), b.width >= 1"
                      " && b.height >= 1 && s.display !== 'none' && s.visibility !== 'hidden']; })")


@dataclass
class _Picker:
    """The year picker on a page, or why there is none, in counts and
    fixed words, with the select itself when there is one."""
    state: str = "none"
    handle: object = None
    years: List[str] = field(default_factory=list)
    chosen: str = ""
    refused: str = ""
    reasons: set = field(default_factory=set)
    selects: int = 0
    year_selects: int = 0
    most_years: int = 0
    most_options: int = 0

    def facts(self) -> dict:
        """What the discovery line and the journal are told."""
        out = {"picker": self.state, "selects": self.selects, "year_selects": self.year_selects}
        if self.state == "found":
            out["years"] = len(self.years)
        else:
            out.update(most_years=self.most_years, most_options=self.most_options)
        if self.state == "refused":
            out["why"] = self.refused
        return out


def _on_statements_page(page) -> bool:
    """Whether this is one of the servicing app's statements pages, signed
    in. Nothing on any other page is chosen in, whatever it offers."""
    from urllib.parse import urlsplit
    url = page.url or ""
    try:
        path = urlsplit(url).path.rstrip("/")
    except ValueError:
        return False
    if not (is_safe_url(url) and loan_number(page) and path.endswith(STATEMENT_PAGES)):
        return False
    return not looks_signed_out(page)


def _options(facts) -> List[str]:
    return [str(o or "").strip() for o in (facts or {}).get("options") or []]


def _placeholder(facts) -> str:
    """The words of a select's first option when it is not a year, the
    placeholder such as Select Year, or ""."""
    opts = _options(facts)
    return opts[0] if opts and not YEAR_OPTION_RE.match(opts[0]) else ""


def _years_of(facts) -> List[str]:
    """The years a select offers, when every option is a year but for at
    most one leading placeholder. The placeholder is never a year here, so
    it is never chosen and never counted. A second option that is not a
    year, or one anywhere but first, means the select is not a picker."""
    opts = _options(facts)
    if opts and not YEAR_OPTION_RE.match(opts[0]):
        opts = opts[1:]
    return opts if opts and all(YEAR_OPTION_RE.match(o) for o in opts) else []


def _picker_refusal(facts: dict) -> str:
    """Why a select that offers only years may still not be chosen in, as
    fixed words, or "" when it may.

    Choosing a year is reading, but a select that offers years can also
    be a card's expiry year in a payment form or a year in a request
    form. The recorded picker is alone in its own form and named by
    nothing, so a select outside a form, one whose form has anything else
    to fill in or press, and one with a word near it, above it or in its
    placeholder that names an action, is left alone. Outside a form there
    is no telling which fields beside it belong with it."""
    if not facts.get("connected"):
        return "it could not be read"
    if facts.get("multiple"):
        return "it takes more than one choice"
    if not facts.get("enabled"):
        return "it is disabled"
    if not facts.get("in_form"):
        return "it is not in a form"
    if facts.get("others"):
        return "its form has more to fill in"
    # A placeholder says what the select is for as plainly as a label does.
    words = " | ".join(w for w in (str(facts.get("words") or ""), _placeholder(facts)) if w)
    if words and (FORBIDDEN_CONTROL_RE.search(words) or MONEY_CONTROL_RE.search(words)
                  or AUTH_CONTROL_RE.search(words)):
        return "its words name an action"
    return ""


def _year_picker(page) -> _Picker:
    """The statements page's year picker. A select that offers only years
    after at most one leading placeholder, on a signed-in statements page,
    that the core's filter lets through, on screen, alone in its form, with
    no word near it that names an action, and the only one of its kind.
    Anything else is left alone, and what was seen is kept in counts and
    fixed words."""
    out = _Picker()
    if not _on_statements_page(page):
        out.state = "not on a statements page"
        return out
    try:
        loc = page.locator("select")
        every = loc.evaluate_all(_ALL_SELECTS_JS)
    except Exception:
        return out
    if not isinstance(every, list):
        return out
    out.selects = len(every)
    usable, hidden, on_screen = [], 0, 0
    for i, pair in enumerate(every):
        if not (isinstance(pair, list) and len(pair) == 2 and isinstance(pair[0], dict)):
            continue
        facts, identity = pair
        # The select closest to being a picker, for the discovery line. Two
        # options that are not years, or one anywhere but first, show up
        # here as a count of years short of the count of options.
        opts = _options(facts)
        n_years = sum(1 for o in opts if YEAR_OPTION_RE.match(o))
        if n_years > out.most_years or not (out.most_years or out.most_options):
            out.most_years, out.most_options = n_years, len(opts)
        years = _years_of(facts)
        if not years:
            continue
        out.year_selects += 1
        # Every one on screen counts toward more than one, refused or not,
        # so a real picker that is disabled for now beside a second select
        # of years never hands the choice to the second.
        on_screen += bool(facts.get("visible"))
        # The core's filter first, the gate every app's sweep of a page's
        # dropdowns goes through, and then this app's stricter checks.
        why = _SHARED_FILTER if is_forbidden_context(str(identity or "")) else _picker_refusal(facts)
        if why:
            out.refused = out.refused or why
            out.reasons.add(why)
        elif not facts.get("visible"):
            hidden += 1
        else:
            usable.append((i, facts, years))
    if on_screen > 1:
        out.state = "more than one"
    elif usable:
        i, facts, years = usable[0]
        # Held as the element itself, and read again through it right
        # before a year is chosen, so a select drawn in between cannot
        # take the choice.
        try:
            out.handle = loc.nth(i).element_handle(timeout=2000)
        except Exception:
            out.state, out.refused = "refused", "it could not be read"
            return out
        out.state, out.years = "found", years
        out.chosen = str(facts.get("chosen") or "").strip()
    elif out.refused:
        out.state = "refused"
    elif hidden:
        out.state = "hidden"
    return out


def _find_year_picker(page, wait_s: Optional[int] = None) -> _Picker:
    """The year picker, given PICKER_WAIT_S when the page has a dropdown
    that does not offer only years yet, or a picker whose only fault is
    that it is disabled, as one can be while its page loads."""
    budget = PICKER_WAIT_S if wait_s is None else wait_s
    waited = 0
    while True:
        picker = _year_picker(page)
        loading = ((picker.state == "none" and picker.selects)
                   or (picker.state == "refused" and picker.reasons == {"it is disabled"}))
        if not loading or waited >= budget:
            return picker
        page.wait_for_timeout(1000)
        waited += 1


def _choose_year(page, year: str, picker: Optional[_Picker] = None):
    """Choose `year` in the year picker, and nothing else. Answers what
    became of it in fixed words, with the picker as it was found.

    The select is read again through the element itself right before the
    choice, so one drawn again as something else in between is not chosen
    in. The choice is Playwright's select_option, which sets the option and
    tells the page it changed. Nothing is clicked or pressed, and the form
    is never submitted."""
    picker = picker if picker is not None else _year_picker(page)
    if picker.state != "found":
        return "no picker", picker
    if year not in picker.years:
        return "not offered", picker
    if picker.chosen == year:
        return "already chosen", picker
    try:
        facts, identity = picker.handle.evaluate(_ONE_SELECT_JS)
    except Exception:
        return "changed before the choice", picker
    if (not isinstance(facts, dict) or _years_of(facts) != picker.years
            or is_forbidden_context(str(identity or "")) or _picker_refusal(facts)
            or not facts.get("visible")):
        return "changed before the choice", picker
    try:
        picker.handle.select_option(label=year, timeout=YEAR_CHOICE_TIMEOUT_MS)
        now = picker.handle.evaluate(_SELECT_FACTS_JS)
    except Exception as e:
        log.info("could not choose a year in the year picker: %s", str(e).split("\n")[0][:160])
        return "could not be chosen", picker
    if not isinstance(now, dict) or str(now.get("chosen") or "").strip() != year:
        return "could not be chosen", picker
    picker.chosen = year
    return "chose", picker


def _list_dates(page) -> List[str]:
    """The date every document control on the list carries, read the way
    discovery reads a row, its name first and then the row around it. The
    controls on screen answer, and hidden ones only when none is on
    screen."""
    try:
        every = _bill_controls(page).evaluate_all(_DATED_CONTROLS_JS)
    except Exception:
        return []
    shown, hidden = [], []
    for got in every if isinstance(every, list) else []:
        if not isinstance(got, list) or len(got) != 3:
            continue
        name, row, on_screen = got
        found = parse_period_date(str(name or ""))[0] or parse_period_date(str(row or ""))[0]
        if found:
            (shown if on_screen else hidden).append(found)
    return shown or hidden


def _wait_for_year(page, year: str, budget_s: Optional[int] = None) -> Tuple[bool, int, int]:
    """Whether the list on screen became `year`'s, the seconds that took,
    and how many statements it shows.

    Every dated row on screen must be in that year, so a list left over
    from the year before is never taken for the new one, not even while
    its rows are still leaving. Two readings a second apart must also
    agree, so a list drawn in pieces less than a second apart is not read
    half done. A year with no statement never shows one."""
    budget = YEAR_WAIT_S if budget_s is None else budget_s
    waited = 0
    last = None
    while True:
        dates = _list_dates(page)
        now = None
        if dates and all(d[:4] == year for d in dates):
            now = tuple(sorted(set(dates)))
        if now is not None and now == last:
            return True, waited, len(now)
        last = now
        if waited >= budget:
            return False, waited, 0
        page.wait_for_timeout(1000)
        waited += 1


def _walk_years(page, docs: List[RawDoc], seen: set) -> dict:
    """Read the list for every year the page's year picker offers, in the
    order it offers them, each once its own list is on screen. What each
    year gave comes back in counts and fixed words for the discovery line.
    A page without a picker is left as it was."""
    picker = _find_year_picker(page)
    facts = picker.facts()
    if picker.state != "found":
        return facts
    walked = []
    for year in list(picker.years):
        how, _found = _choose_year(page, year, picker)
        rows = 0
        if how in ("chose", "already chosen"):
            shown, _waited, rows = _wait_for_year(page, year)
            how = "shown" if shown else "never showed"
            if shown:
                _read_rows(page, docs, seen)
        walked.append([int(year), rows, how])
        # Looked for afresh before the next year, since the page may have
        # drawn the picker again along with the list.
        picker = None
    facts["walked"] = walked
    return facts


def _plural(n: int, word: str) -> str:
    return "%d %s%s" % (n, word, "" if n == 1 else "s")


def _whole(facts: dict, key: str) -> int:
    """A count from the walk's facts, or 0 for anything that is not one."""
    value = facts.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def year_walk_facts(walk) -> dict:
    """What each statements page's picker gave, for the journal and so for
    the failure file, which a tester attaches in public.

    No year is written. How many statements each year holds says when the
    loan began, seven in the year it came to Newrez say, so each year is
    its place in the picker instead, 1 for the first year it offers. The
    console line may name the years, since a tester reads it before
    pasting it. Only the counts and fixed words above are copied."""
    out: dict = {}
    if not isinstance(walk, dict):
        return out
    for name in (p.rsplit("/", 1)[-1] for p in STATEMENT_PAGES):
        facts = walk.get(name)
        if not isinstance(facts, dict):
            continue
        page = {k: _whole(facts, k) for k in ("selects", "year_selects", "years",
                                              "most_years", "most_options") if k in facts}
        if facts.get("picker") in _PICKER_STATES:
            page["picker"] = facts["picker"]
        if facts.get("why") in _PICKER_REFUSALS:
            page["why"] = facts["why"]
        walked = []
        for place, entry in enumerate(facts.get("walked") or [], 1):
            try:
                rows, how = int(entry[1]), entry[2]
            except (TypeError, ValueError, IndexError):
                continue
            if how in _WALK_OUTCOMES:
                walked.append([place, rows, how])
        if walked:
            page["walked"] = walked
        out[name] = page
    return out


def year_walk_lines(walk) -> List[str]:
    """The discovery lines a tester copies into the issue, one for each
    statements page, which years its picker offered and how many documents
    each gave. Built from numbers and the fixed words above only, so
    nothing off the page can reach them (#38). They name the years, so
    they go to the console and never to the journal, which carries
    year_walk_facts instead."""
    lines: List[str] = []
    if not isinstance(walk, dict):
        return lines
    for name in (p.rsplit("/", 1)[-1] for p in STATEMENT_PAGES):
        facts = walk.get(name)
        if not isinstance(facts, dict):
            continue
        state = facts.get("picker")
        if state == "found":
            parts = []
            for entry in facts.get("walked") or []:
                try:
                    year, rows, how = int(entry[0]), int(entry[1]), entry[2]
                except (TypeError, ValueError, IndexError):
                    continue
                if not 1900 <= year <= 2099 or how not in _WALK_OUTCOMES:
                    continue
                parts.append("%d gave %d" % (year, rows) if how == "shown" else "%d %s" % (year, how))
            lines.append("Year picker on the %s page walked %s, %s"
                         % (name, _plural(len(parts), "year"), ", ".join(parts) or "none was read"))
        elif state == "none" and not _whole(facts, "selects"):
            lines.append("No year picker on the %s page, it has no dropdown" % name)
        elif state == "none":
            lines.append("No year picker on the %s page, it has %s and the one with the most years "
                         "offers %d among %s" % (name, _plural(_whole(facts, "selects"), "dropdown"),
                                                 _whole(facts, "most_years"),
                                                 _plural(_whole(facts, "most_options"), "option")))
        elif state == "refused" and facts.get("why") in _PICKER_REFUSALS:
            lines.append("The year picker on the %s page was not used, %s" % (name, facts["why"]))
        elif state == "more than one":
            lines.append("The %s page has %d dropdowns that offer only years, so none was used"
                         % (name, _whole(facts, "year_selects")))
        elif state == "hidden":
            lines.append("The year picker on the %s page is not on screen, so it was not used" % name)
        elif state == "not on a statements page":
            lines.append("The %s page was not a signed-in statements page, so no year picker "
                         "was looked for" % name)
    return lines


# How long capture waits for the rows once a statements page is open.
# Every page.goto reloads the servicing app, which signs in again through
# Okta before it asks for the list. His failure file (#38) ends on exactly
# that sign-in with no list requested yet, and capture looked for the row
# five seconds after the load, where discovery reads the page ten seconds
# or more after it. Four of his five were looked for too early.
LIST_WAIT_S = 30


def _note(trace: Optional[list], note: str, **fields) -> None:
    if trace is not None:
        trace.append(dict({"note": note}, **fields))


# What a capture may say in the failure file, the one file a tester
# reliably attaches, and in the journal line for a saved document. His
# 0.37.0 file showed the second statement failing on the list after a 33
# second capture and could not say what the click did, because that is
# only in download-attempt.json (#38). Each step the trace names maps to
# fixed words written here, and only the counts, yes-or-no fields and
# words listed below are copied, so no label, address or date off the
# page can reach the file.
_CAPTURE_STEPS = {
    "already on the statements page": "stayed on the list",
    "opened the statements page": "opened the list",
    "could not open the statements page": "could not open the list",
    "no loan number in the address, so the yearly page cannot be opened": "no loan number in the address",
    "could not open the yearly page": "could not open the yearly page",
    "found the row": "found the row",
    "no row on the page has this date": "no row has this date",
    "refused the control, the guard said no": "guard refused the control",
    "the control's own link did not answer with a PDF": "own link was not a pdf",
    "clicked": "clicked",
    "click failed": "click failed",
    "clicked through the DOM instead": "clicked through the page",
    "DOM click failed too": "page click failed too",
    "the tab moved": "the tab moved",
    "after the click": "looked after the click",
    "second step clicked": "second step clicked",
    "second step click failed": "second step click failed",
    "no PDF arrived": "no pdf arrived",
    "the control's own link answered with a PDF": "own link was a pdf",
    "waited for an earlier download to finish": "waited for an earlier download",
    "an earlier download was still being written, so nothing was clicked":
        "earlier download still being written",
    "the row left the page before it could be pressed": "row left the page",
    "the row changed before it was pressed, so nothing was pressed": "row changed before the press",
    "the row changed, so it was not pressed through the DOM": "row changed before the page click",
    "the download folder could not say which download is this one":
        "folder could not tell which download",
    "waited on a document still on its way": "waited on a document on its way",
    "the PDF landed": "the pdf landed",
    # The statement's year, for a row the list as drawn did not have (#38).
    "chose the statement's year": "chose the year",
    "the year picker already shows the statement's year": "year already chosen",
    "the year picker does not offer the statement's year": "year not offered",
    "the year picker changed before the choice, so nothing was chosen":
        "picker changed before the choice",
    "the statement's year could not be chosen, so nothing was pressed": "year could not be chosen",
    "the list never showed the statement's year, so nothing was pressed":
        "list never showed the year",
}
# Which counts, yes-or-no fields and words may be copied, and the part of
# the capture each one describes. Grouped so the failure file stays under
# the twenty fields a section may hold, and so a count keeps its meaning,
# the list's wait and the wait for an earlier download being two numbers.
_CAPTURE_COUNTS = {
    "waited_s": "list", "controls": "list", "visible": "list", "same_date": "list",
    "after_click_s": "click", "in_flight_s": "click", "new_tabs": "click",
    # Playwright's own download event. It does not fire for an attached
    # Edge or Chrome, so a zero here says nothing about whether a download
    # began. The download folder and the network counts do.
    "download_events": "click",
    "arrived_unfinished": "download_folder", "arrived_not_pdf": "download_folder",
    "left_unfinished": "download_folder", "earlier_download_s": "download_folder",
    # A download that was still being written when the click was made and
    # was gone when a PDF landed, and how many new PDFs there were then.
    "earlier_finished": "download_folder", "new_pdfs": "download_folder",
    # How long the list took to show the statement's year once it was
    # chosen, how many statements that year's list showed, and how many
    # years the picker offered. Never the year itself.
    "year_wait_s": "year", "year_rows": "year", "years_offered": "year",
}
_CAPTURE_FLAGS = {"scrolled": "list", "chosen_visible": "list", "signed_out": "list"}
# The wait a PDF landed in, and the way it arrived.
_CAPTURE_WINDOWS = ("first wait", "second step wait", "last wait", "in flight wait", "no click")
_CAPTURE_HOWS = ("download folder", "download event", "pdf response", "refetched response",
                 "same tab", "new tab", "own link")
# Why the control about to be pressed was no longer the one the guard
# approved.
_CHECK_WHYS = ("it left the page", "its name changed", "it no longer carries this date",
               "it could not be read again")
_CAPTURE_WORDS = {"window": _CAPTURE_WINDOWS, "how": _CAPTURE_HOWS, "why": _CHECK_WHYS,
                  "picker": _PICKER_STATES}
# The part of the capture a word describes, the click unless named here.
_CAPTURE_WORD_PARTS = {"picker": "year"}


def capture_facts(trace: Optional[list]) -> dict:
    """A capture's trace as steps, counts and fixed words, for the failure
    file and the journal. Nothing is copied that is not named above, and
    the network counts are integers under fixed names."""
    out: dict = {"steps": []}
    for entry in trace or []:
        if not isinstance(entry, dict):
            continue
        note = entry.get("note")
        step = _CAPTURE_STEPS.get(note) if isinstance(note, str) else None
        if not step:
            continue
        out["steps"].append(step)
        for name, part in _CAPTURE_COUNTS.items():
            value = entry.get(name)
            if isinstance(value, int) and not isinstance(value, bool):
                out.setdefault(part, {})[name] = value
        for name, part in _CAPTURE_FLAGS.items():
            if isinstance(entry.get(name), bool):
                out.setdefault(part, {})[name] = entry[name]
        for name, allowed in _CAPTURE_WORDS.items():
            if entry.get(name) in allowed:
                out.setdefault(_CAPTURE_WORD_PARTS.get(name, "click"), {})[name] = entry[name]
        if isinstance(entry.get("appeared"), list):
            out.setdefault("click", {})["controls_appeared"] = len(entry["appeared"])
        if isinstance(entry.get("network"), dict):
            out["network"] = _network_facts(entry["network"])
    return out


def landing_facts(trace: Optional[list]) -> dict:
    """How a saved document arrived, for the journal line written when it
    is saved. How long after the click, in which wait, which way, how long
    the list took, and the network counts, so a run that saves some and
    not others shows how close the good ones came to giving up (#38)."""
    facts = capture_facts(trace)
    if "the pdf landed" not in facts.get("steps", []):
        return {}
    out = dict(facts.get("click") or {})
    out.pop("controls_appeared", None)
    if "waited_s" in (facts.get("list") or {}):
        out["list_waited_s"] = facts["list"]["waited_s"]
    if facts.get("year"):
        out["year"] = facts["year"]
    if facts.get("network"):
        out["network"] = facts["network"]
    return out


# ---------------------------------------------------------------------------
# What the browser sent and got back while one capture waited, as counts.
# ---------------------------------------------------------------------------
# His 0.37.0 failure file listed no newrez.com answer to the statements tab
# after the page loaded, for the statement that saved as much as for the
# one that did not (#38). Only the provider's own answers are ever listed,
# so the document comes some other way, from another address, from data
# the page already held, or in a tab the list never watched. These counts
# cover the statements tab and any tab the click opens, at every address,
# and say whether a request that could be the document was still waiting,
# was answered with an error, came back as an attachment, or never went
# out, without writing down an address, a header or a byte of what came
# back. "aborted" is a request the browser cut off, which is what a request
# turned into a download ends as, and also what a page cancelling its own
# call ends as, so "attachments" is the firmer sign of a download. The
# other tabs of his browser are not counted, since a call one of them keeps
# open would keep every capture waiting for nothing.
_TRAFFIC_WHERE = ("provider", "elsewhere")
_TRAFFIC_COUNTS = (
    "requests", "document_requests", "fetch_requests",
    "responses_pdf", "responses_octet", "responses_json", "responses_html", "responses_other",
    "attachments", "status_2xx", "status_3xx", "status_4xx", "status_5xx",
    "finished", "failed", "aborted", "pending", "pending_answered",
)


def _network_facts(raw) -> dict:
    """Only the fixed names above, and only whole numbers."""
    out = {}
    for where in _TRAFFIC_WHERE:
        part = raw.get(where) if isinstance(raw, dict) else None
        if not isinstance(part, dict):
            continue
        out[where] = {k: part[k] for k in _TRAFFIC_COUNTS
                      if isinstance(part.get(k), int) and not isinstance(part.get(k), bool)}
    return out


class _Traffic:
    """Every request the browser made while one capture waited, counted
    by whether it went to Newrez or elsewhere, and never described.

    Listened for on the whole browser context, so a tab the click opens is
    counted too. A request from a tab in `ignore`, the tabs that were open
    before the click other than the statements tab, is not counted, and
    neither is one no tab can be named for, a service worker's say. Only
    the requests counted here are answered, finished or failed here.
    Nothing here may raise, it runs inside Playwright's events."""

    def __init__(self, ignore=()):
        self.counts = {w: dict.fromkeys(_TRAFFIC_COUNTS, 0) for w in _TRAFFIC_WHERE}
        self._open: dict = {}
        self._tracked: set = set()
        self._ignore = set(ignore or ())

    @staticmethod
    def _where(url) -> str:
        try:
            return "provider" if is_safe_url(url or "") else "elsewhere"
        except Exception:
            return "elsewhere"

    def _counted(self, req) -> bool:
        """Whether a new request comes from a tab this capture watches."""
        try:
            return req.frame.page not in self._ignore
        except Exception:
            return False

    def tracks(self, req) -> bool:
        """Whether `req` was made while this capture watched, from a tab
        it watches."""
        try:
            return req in self._tracked
        except Exception:
            return False

    def on_request(self, req) -> None:
        try:
            if not self._counted(req):
                return
            where = self._where(req.url)
            kind = str(req.resource_type or "")
            part = self.counts[where]
            part["requests"] += 1
            if kind == "document":
                part["document_requests"] += 1
            elif kind in ("fetch", "xhr"):
                part["fetch_requests"] += 1
            self._open[req] = {"where": where, "kind": kind, "answered": False, "file": False}
            self._tracked.add(req)
        except Exception:
            pass

    def on_response(self, res) -> None:
        try:
            if not self.tracks(res.request):
                return
            where = self._where(res.url)
            part = self.counts[where]
            headers = res.headers or {}
            ct = str(headers.get("content-type") or "").lower()
            kind = ("pdf" if "pdf" in ct else "octet" if "octet-stream" in ct
                    else "json" if "json" in ct else "html" if "html" in ct else "other")
            part["responses_" + kind] += 1
            attached = str(headers.get("content-disposition") or "").lower().startswith("attachment")
            if attached:
                part["attachments"] += 1
            status = int(res.status or 0)
            if 200 <= status < 600:
                part["status_%dxx" % (status // 100)] += 1
            entry = self._open.get(res.request)
            if entry is not None:
                entry["answered"] = True
                entry["file"] = kind in ("pdf", "octet") or attached
        except Exception:
            pass

    def _closed(self, req, how: str) -> None:
        try:
            entry = self._open.pop(req, None)
            if entry is None:
                return
            where = entry["where"]
            self.counts[where][how] += 1
            if how == "failed" and "ERR_ABORTED" in str(req.failure or ""):
                # Cut off by the browser, which a request turned into a
                # download is, and a call the page cancelled is too.
                self.counts[where]["aborted"] += 1
        except Exception:
            pass

    def on_finished(self, req) -> None:
        self._closed(req, "finished")

    def on_failed(self, req) -> None:
        self._closed(req, "failed")

    def in_flight(self) -> bool:
        """A request made since the click, from the statements tab or a
        tab the click opened, that could still be the document. A page
        load or a download started by the browser, a call from the page, or
        anything already answered with a file whose body is still coming.
        Calls to other sites count too, since the failure file shows the
        document does not come from a newrez.com address, and the wait they
        can cause is capped (#38)."""
        for entry in list(self._open.values()):
            if entry["file"] or entry["kind"] in ("document", "fetch", "xhr"):
                return True
        return False

    def facts(self) -> dict:
        out = {w: dict(c) for w, c in self.counts.items()}
        for entry in list(self._open.values()):
            out[entry["where"]]["pending"] += 1
            if entry["answered"]:
                out[entry["where"]]["pending_answered"] += 1
        return out


# How long a capture waits for the PDF after the click, in seconds. The
# first wait, the wait after a second control the click revealed, and the
# last. A statement he saved on 0.37.0 took about eleven seconds from the
# click, past the first wait, which leaves the budget little room (#38).
FIRST_WAIT_S = 10
SECOND_STEP_WAIT_S = 20
LAST_WAIT_S = 15
# How much longer the last wait may run while a document is visibly on
# its way, a file still being written to the download folder or a request
# that could be it still waiting. Nothing is clicked while it waits.
IN_FLIGHT_WAIT_S = 45
# A download an earlier capture gave up on and that is still being written
# is let finish before the row is looked for, for at most this long, and
# taken as abandoned once it has not grown for EARLIER_STILL_S. One still
# growing when the wait ends means nothing is clicked.
EARLIER_WAIT_S = 30
EARLIER_STILL_S = 5
# How long Playwright may take to press the control.
CLICK_TIMEOUT_MS = 8000
# The clock a capture measures itself by, so a test can move it.
_clock = time.monotonic
# Files still being written that a capture in this run has already taken
# as abandoned, by path and size. A browser keeps an interrupted download's
# file so it can resume it, and such a leftover is waited on once, not
# before every capture. One whose size has changed is waited on again.
_ABANDONED: dict = {}


def _unfinished(dl_dir) -> dict:
    """The download folder's files still being written, with their sizes."""
    out = {}
    if not dl_dir:
        return out
    try:
        names = os.listdir(dl_dir)
    except OSError:
        return out
    for name in names:
        if name.lower().endswith(_UNFINISHED):
            try:
                out[name] = os.path.getsize(os.path.join(dl_dir, name))
            except OSError:
                out[name] = -1
    return out


def _earlier_downloads_settled(page, dl_dir, trace: Optional[list]) -> bool:
    """Let a download still being written from an earlier capture finish
    before this capture looks for its row, or say it has not.

    The folder is compared before and after the click. A file an earlier
    capture gave up on that finishes after the click has a new name, the
    finished one, and could be saved under this document's name. One that
    finishes here is part of the picture taken before the click and is
    left alone. One that has not grown for EARLIER_STILL_S is taken as
    abandoned. The capture then watches it, and a PDF that lands after it
    has gone is not taken (#38).

    False when one is still growing after EARLIER_WAIT_S. Nothing is
    clicked then, and the document is left for the next run. This runs
    before the row is looked for, so no wait sits between the guard
    approving a control and the click."""
    if not dl_dir:
        return True

    def live() -> dict:
        return {name: size for name, size in _unfinished(dl_dir).items()
                if _ABANDONED.get(str(Path(dl_dir) / name)) != size}

    waited = still = 0
    last = None
    settled = True
    while True:
        now = live()
        if not now:
            break
        if waited >= EARLIER_WAIT_S:
            settled = False
            break
        still = still + 1 if now == last else 0
        if still >= EARLIER_STILL_S:
            for name, size in now.items():
                _ABANDONED[str(Path(dl_dir) / name)] = size
            break
        last = now
        page.wait_for_timeout(1000)
        waited += 1
    left = len(_unfinished(dl_dir))
    if not settled:
        _note(trace, "an earlier download was still being written, so nothing was clicked",
              earlier_download_s=waited, left_unfinished=left)
        log.info("an earlier download is still being written, so this one is left for the next run")
        return False
    if waited:
        _note(trace, "waited for an earlier download to finish",
              earlier_download_s=waited, left_unfinished=left)
    return True


def _new_pdfs(dl_dir, before: set) -> list:
    """Finished files in the download folder that were not there before,
    or were written again in place since, and start like a PDF, by name.
    The browser writes a finished file of the same name over the old one,
    and compared by name alone that download never arrived."""
    if not dl_dir:
        return []
    out = []
    for name in _arrived(dl_dir, before):
        try:
            with open(os.path.join(dl_dir, name), "rb") as fh:
                if fh.read(5) == b"%PDF-":
                    out.append(name)
        except OSError:
            continue
    return out


# A control's name, the text around it that carries a date, and whether it
# is still on the page, read in one call so they describe one moment.
_NAME_AND_ROW_JS = ("el => [(el.getAttribute('aria-label') || el.innerText || '').trim(), ("
                    + _ROW_OF_JS + ")(el), el.isConnected]")
# The press through the page, made only if the control still has the name
# the guard approved, checked and pressed in one step so nothing can move
# in between.
_DOM_CLICK_IF_SAME_JS = ("(el, want) => { const n = (el.getAttribute('aria-label') || el.innerText"
                         " || '').trim(); if (!el.isConnected || n !== want) return false;"
                         " el.click(); return true; }")


def _still_the_one(el, iso: str, label: str) -> str:
    """Why the control about to be pressed is no longer the one the guard
    approved, as fixed words, or "" when it still is.

    The control is held as the element itself, so a list that redraws in
    another order cannot move the press to another row. A page that reuses
    the element for another row changes its name or its date, and that is
    read again right before the press (#38)."""
    try:
        got = el.evaluate(_NAME_AND_ROW_JS)
    except Exception:
        return "it could not be read again"
    if not isinstance(got, list) or len(got) != 3:
        return "it could not be read again"
    name, row, connected = got
    if not connected:
        return "it left the page"
    name = str(name or "").strip()
    if name != label or not is_safe_control(name):
        return "its name changed"
    found = parse_period_date(name)[0] or parse_period_date(str(row or ""))[0]
    if found != iso:
        return "it no longer carries this date"
    return ""


def _where(page) -> str:
    """The page's path and route with digits masked, never its query."""
    from urllib.parse import urlsplit
    try:
        parts = urlsplit(page.url or "")
    except ValueError:
        return ""
    route = parts.path + ("#" + parts.fragment.split("?")[0] if parts.fragment else "")
    return redact(route)[:120]


def _list_path_for(title: str) -> str:
    """The statements page a document lives on. A 1098 sits on the yearly
    page, and capture used to look for it on the monthly one."""
    return STATEMENT_PAGES[1] if (title or "").startswith("Tax Document") else STATEMENT_PAGES[0]


def _open_list(page, path: str, trace: Optional[list]) -> bool:
    """Be on the statements page `path` of the servicing app. The run has
    just opened the monthly page before calling capture, and loading it
    again straight away starts the app's sign-in over, so a page already
    there is kept."""
    from urllib.parse import urlsplit
    here = page.url or ""
    try:
        here_path = urlsplit(here).path.rstrip("/")
    except ValueError:
        here_path = ""
    if loan_number(page) and is_safe_url(here) and here_path.endswith(path):
        _note(trace, "already on the statements page", page=path, url=_where(page))
        return True
    if not goto_documents(page):
        _note(trace, "could not open the statements page", url=_where(page),
              signed_out=looks_signed_out(page))
        return False
    if path != STATEMENT_PAGES[0]:
        loan = loan_number(page)
        if not loan:
            _note(trace, "no loan number in the address, so the yearly page cannot be opened",
                  url=_where(page))
            return False
        try:
            page.goto(f"{SERVICING}/servicing/{loan}{path}", wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(2000)
            dismiss_overlay(page)
        except Exception as e:
            _note(trace, "could not open the yearly page", error=redact(str(e))[:160])
            return False
    _note(trace, "opened the statements page", page=path, url=_where(page))
    return True


def _year_for_row(page, iso: str, drawn: int, idle: int, trace: Optional[list]):
    """Set the year picker to the statement's year, for a row the list as
    drawn does not have, and wait until the list shows that year.

    Answers what became of it, the seconds that took, and what the look
    for the picker found. What became of it is "" while there is no picker
    or the list has not drawn, since a year chosen while the page is still
    loading its first list can have that list land after the chosen one,
    and the picker's options may still be arriving. A picker that sits
    with nothing drawn for PICKER_IDLE_S is used anyway, for a year with
    no statement yet, but never for the newest year it offers. That year's
    list is the one the page draws first, and choosing it while the page
    still loads drew the list twice and took the row away before the
    press, where 0.37.1 had saved it. "failed" means nothing may be
    pressed."""
    year = (iso or "")[:4]
    found = _year_picker(page)
    if found.state != "found":
        return "", 0, found.state
    if not drawn and (idle < PICKER_IDLE_S or year == max(found.years)):
        return "", 0, found.state
    offered = len(found.years)
    if year not in found.years:
        _note(trace, "the year picker does not offer the statement's year", years_offered=offered)
        return "not offered", 0, found.state
    if found.chosen == year:
        _note(trace, "the year picker already shows the statement's year", years_offered=offered)
        return "already chosen", 0, found.state
    how, found = _choose_year(page, year, found)
    if how == "changed before the choice":
        _note(trace, "the year picker changed before the choice, so nothing was chosen",
              years_offered=offered)
        return "failed", 0, found.state
    if how != "chose":
        _note(trace, "the statement's year could not be chosen, so nothing was pressed",
              years_offered=offered)
        return "failed", 0, found.state
    shown, spent, rows = _wait_for_year(page, year)
    if not shown:
        _note(trace, "the list never showed the statement's year, so nothing was pressed",
              year_wait_s=spent, years_offered=offered)
        return "failed", spent, found.state
    _note(trace, "chose the statement's year", year_wait_s=spent, year_rows=rows,
          years_offered=offered)
    return "shown", spent, found.state


def _wait_for_control(page, iso: str, trace: Optional[list]):
    """The control for `iso`, waiting for the list to render. Once rows
    are there and none is this date, the page is expanded and scrolled
    once, as discovery does, and the wait ends when the count settles.

    A statement is only on its own year's list. While the row is not on
    the list the year picker is looked for, and once the list has drawn
    the picker is set to the statement's year, once, and the list waited
    on until it shows that year, before the row is looked for again. A
    list that never shows it ends the wait with nothing pressed (#38)."""
    counts: list = []
    scrolled = False
    waited = 0
    info: dict = {}
    el, label = None, ""
    # What became of the statement's year, "" while the picker is still
    # looked for, what the look for it last found, and how many looks
    # found it with no list drawn.
    year_step, picker, idle = "", "", 0
    while True:
        info = {}
        el, label = _control_for(page, iso, info)
        if el is not None:
            break
        n = info.get("controls", 0)
        counts.append(n)
        if waited >= LIST_WAIT_S:
            break
        if not year_step:
            year_step, spent, picker = _year_for_row(page, iso, n, idle, trace)
            waited += spent
            idle += picker == "found"
            if year_step == "failed":
                break
            if year_step == "shown":
                counts, scrolled = [], False
                continue
        if n and not scrolled:
            expand_all(page)
            scroll_full_page(page)
            scrolled = True
            waited += 5
            continue
        if n and scrolled and len(counts) >= 3 and len(set(counts[-3:])) == 1:
            break
        page.wait_for_timeout(1000)
        waited += 1
    looked = {"picker": picker} if picker else {}
    _note(trace, "found the row" if el is not None else "no row on the page has this date",
          date=iso, waited_s=waited, scrolled=scrolled, url=_where(page), **looked, **info)
    return el, label


def _fetch_pdf(page, href: str) -> Optional[bytes]:
    """A PDF link fetched from inside the signed-in page, cookies and all.
    The fetching is the core's, the hosts are this app's."""
    return _core_fetch_pdf(page, href, is_safe_url)


def _take_same_tab(page, start_url: str, out_path: Path, trace) -> bool:
    """A PDF the click opened in this very tab. The core does the reading,
    this app's guard decides which addresses it may read."""
    return _core_take_same_tab(page, start_url, out_path, trace, is_safe_url)


_SECOND_STEP_RE = re.compile(
    r"^\s*(download|download\s+(pdf|now|file|statement|document)|save|save\s+(as\s+)?pdf|"
    r"(regular|standard|full|detailed)\s+pdf|pdf|view\s*/\s*print\s+pdf|print|open\s+pdf)\s*$", re.I)


def _second_step(page, appeared: set):
    """A control the click revealed whose text says it finishes a download,
    once it has passed the guard, or None. The choosing is the core's, the
    words this provider uses and the guard are this app's."""
    return _core_second_step(page, appeared, _SECOND_STEP_RE, is_safe_control)


# What landed() answers when a PDF arrived in the download folder but the
# folder cannot say it is this document's.
_AMBIGUOUS = "ambiguous"


def _catch_pdf(page, el, label: str, out_path: Path, trace: Optional[list] = None,
               dl_dir=None, check=None) -> bool:
    """Click `el` and save whatever PDF the site produces, a file landing
    in `dl_dir`, a download event, a PDF response, a new tab, this tab
    moving to the document, or a second control the click revealed.
    `trace` collects what happened, the click's own outcome included, and
    how long after the click the PDF landed, in which wait and which way.

    `check` says why `el` is no longer the control the guard approved, or
    "" when it still is. It is asked right before the press, and nothing
    is pressed when it objects.

    A PDF in the download folder is taken only when the folder can say it
    is this one. It is not when a download that was still being written
    before the click has gone by the time the PDF lands, since that
    download may have finished as this very file, or when more than one
    new PDF is there. The files are left where they are, nothing is saved,
    and the document is asked for again on the next run (#38)."""
    ctx = page.context
    got: dict = {}
    downloads: list = []
    start_url = page.url or ""
    before = set(ctx.pages)
    # The other tabs of the browser are not this capture's business.
    traffic = _Traffic(ignore=before - {page})

    def on_download(dl):
        downloads.append(dl)

    def on_response(res):
        traffic.on_response(res)
        try:
            # Only an answer to a request made while this capture watched,
            # from this tab or one the click opened, can be this document.
            if not traffic.tracks(res.request):
                return
            url = res.url or ""
            if not is_safe_url(url):
                return
            ct = (res.headers.get("content-type") or "").lower()
            if trace is not None and ("json" in ct or "pdf" in ct or "octet" in ct):
                trace.append({"status": res.status, "type": ct[:40], "url": redact(url)[:160]})
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
        except Exception:
            pass

    listeners = [("request", traffic.on_request), ("response", on_response),
                 ("requestfinished", traffic.on_finished), ("requestfailed", traffic.on_failed)]
    for event, fn in listeners:
        try:
            ctx.on(event, fn)
        except Exception:
            pass
    page.on("download", on_download)
    seen = _snapshot(dl_dir)
    # Downloads still being written when the picture was taken, from an
    # earlier capture or left over from before. The browser renames one
    # when it finishes, so a PDF that lands after one of these has gone
    # may be it.
    unfinished_before = {name for name in seen if name.lower().endswith(_UNFINISHED)}
    controls_before = _control_texts(page)
    clicked_at = [_clock()]
    doubt: dict = {}

    def after_click_s() -> int:
        return max(0, int(round(_clock() - clicked_at[0])))

    def earlier_gone() -> int:
        return len(unfinished_before - _snapshot(dl_dir))

    def from_folder() -> str:
        """The download folder's PDF moved to `out_path`, _AMBIGUOUS when
        the folder cannot say which download it is, or "" when none has
        landed."""
        new = _new_pdfs(dl_dir, seen)
        if not new:
            return ""
        # Looked at after the new PDFs were listed, so an earlier download
        # that finishes in between is seen as gone.
        gone = earlier_gone()
        if gone or len(new) > 1:
            doubt.update(earlier_finished=gone, new_pdfs=len(new))
            return _AMBIGUOUS
        try:
            if out_path.exists():
                out_path.unlink()
            shutil.move(os.path.join(dl_dir, new[0]), str(out_path))
        except OSError as e:
            log.info("could not move the downloaded PDF: %s", e)
            return ""
        return "download folder"

    def landed() -> str:
        """The way a PDF arrived, or "" while none has."""
        # Pointed at a folder, the browser can save the only copy there and
        # leave the event's own file empty, so that file is taken rather than
        # the document asked for a second time (capture.take_download).
        # The event is not tied to the press, so its file is taken only
        # when it is the one document that arrived, and otherwise the
        # folder rules below decide, as they did before (#38).
        if downloads:
            how = _take_download(downloads[0], dl_dir, seen, out_path)
            if how == "event":
                return "download event"
            if how:
                return "download folder"
        if got.get("body"):
            out_path.write_bytes(got["body"])
            return "pdf response"
        if got.get("refetch"):
            try:
                resp = page.context.request.get(got.pop("refetch"), timeout=60000)
                body = resp.body() if resp.ok else b""
                if body[:5] == b"%PDF-":
                    out_path.write_bytes(body)
                    return "refetched response"
            except Exception:
                pass
        return from_folder()

    def wait_for_pdf(seconds: int) -> str:
        for _ in range(seconds):
            how = landed()
            if how:
                return how
            page.wait_for_timeout(1000)
        return landed()

    def on_its_way() -> bool:
        """A file this click started still being written, or a request
        that could be the document still waiting."""
        if traffic.in_flight():
            return True
        return any(name not in seen for name in _unfinished(dl_dir))

    def wait_while_on_its_way():
        waited = 0
        while waited < IN_FLIGHT_WAIT_S and on_its_way():
            page.wait_for_timeout(1000)
            waited += 1
            how = landed()
            if how:
                return how, waited
        return (landed() if waited else ""), waited

    def new_tabs() -> list:
        return [p for p in ctx.pages if p not in before]

    def ended(how: str, window: str) -> bool:
        if how == _AMBIGUOUS:
            _note(trace, "the download folder could not say which download is this one",
                  after_click_s=after_click_s(), network=traffic.facts(), **doubt)
            log.info("a PDF landed that may be an earlier download, so it was not taken")
            return False
        if trace is not None:
            trace.append({"note": "the PDF landed", "how": how, "window": window,
                          "after_click_s": after_click_s(), "network": traffic.facts()})
        return True

    try:
        try:
            el.scroll_into_view_if_needed(timeout=4000)
        except Exception:
            pass
        why = check() if check is not None else ""
        if why:
            _note(trace, "the row changed before it was pressed, so nothing was pressed", why=why)
            log.info("the control for %r changed before it was pressed, so nothing was pressed", label)
            return False
        clicked_at[0] = _clock()
        try:
            el.click(timeout=CLICK_TIMEOUT_MS)
            if trace is not None:
                trace.append({"note": "clicked", "control": redact(label)[:60]})
        except Exception as e:
            if trace is not None:
                trace.append({"note": "click failed", "control": redact(label)[:60], "error": str(e)[:160]})
            # The ordinary press can take seconds to give up, so the name and
            # the date are read again before pressing through the page, and
            # the name once more in the same step as the press.
            why = check() if check is not None else ""
            try:
                if why:
                    _note(trace, "the row changed, so it was not pressed through the DOM", why=why)
                elif el.evaluate(_DOM_CLICK_IF_SAME_JS, label) is False:
                    _note(trace, "the row changed, so it was not pressed through the DOM")
                elif trace is not None:
                    trace.append({"note": "clicked through the DOM instead", "control": redact(label)[:60]})
            except Exception as e2:
                if trace is not None:
                    trace.append({"note": "DOM click failed too", "error": str(e2)[:160]})
        how = wait_for_pdf(FIRST_WAIT_S)
        if how:
            return ended(how, "first wait")
        if _take_same_tab(page, start_url, out_path, trace):
            return ended("same tab", "first wait")
        if _take_new_tab(page, new_tabs(), out_path):
            return ended("new tab", "first wait")
        appeared = _control_texts(page) - controls_before
        if trace is not None:
            trace.append({"note": "after the click", "url": redact(page.url or "")[:160],
                          "appeared": [redact(t) for t in sorted(appeared)[:15]],
                          "new_tabs": len(new_tabs())})
        step, step_label = _second_step(page, appeared)
        if step is not None:
            try:
                step.click(timeout=CLICK_TIMEOUT_MS)
                if trace is not None:
                    trace.append({"note": "second step clicked", "control": redact(step_label)[:60]})
            except Exception as e:
                if trace is not None:
                    trace.append({"note": "second step click failed", "control": redact(step_label)[:60],
                                  "error": str(e)[:160]})
            how = wait_for_pdf(SECOND_STEP_WAIT_S)
            if how:
                return ended(how, "second step wait")
            if _take_same_tab(page, start_url, out_path, trace):
                return ended("same tab", "second step wait")
            if _take_new_tab(page, new_tabs(), out_path):
                return ended("new tab", "second step wait")
        how = wait_for_pdf(LAST_WAIT_S)
        if how:
            return ended(how, "last wait")
        if _take_new_tab(page, new_tabs(), out_path):
            return ended("new tab", "last wait")
        # A statement that took about eleven seconds on a good run leaves
        # the budget little room, so one still visibly on its way is
        # waited for rather than given up on (#38).
        how, in_flight_s = wait_while_on_its_way()
        if in_flight_s:
            _note(trace, "waited on a document still on its way", in_flight_s=in_flight_s)
        if how:
            return ended(how, "in flight wait")
        if in_flight_s and _take_new_tab(page, new_tabs(), out_path):
            return ended("new tab", "in flight wait")
        if trace is not None:
            # What reached the download folder and was not taken. A file
            # still being written is a document on its way that the wait
            # gave up on, and a finished one left behind is not a PDF.
            arrived = _snapshot(dl_dir) - seen
            unfinished = sum(1 for f in arrived if f.lower().endswith(_UNFINISHED))
            trace.append({"note": "no PDF arrived", "url": redact(_where(page)),
                          "download_events": len(downloads),
                          "new_tabs": len(new_tabs()),
                          "arrived_unfinished": unfinished,
                          "arrived_not_pdf": len(arrived) - unfinished,
                          "earlier_finished": earlier_gone(),
                          "after_click_s": after_click_s(),
                          "in_flight_s": in_flight_s,
                          "network": traffic.facts()})
        log.info("click on %r produced no PDF", label)
        return False
    finally:
        for event, fn in listeners:
            try:
                ctx.remove_listener(event, fn)
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
    """Save the document dated `iso_date`. A PDF link on the row is fetched
    from inside the page. Otherwise the row's own control is clicked, once
    it has passed the guard, and whichever the site produces is caught, a
    download event or a PDF response, in this tab or one it opens.

    `dl_dir` is where the attached browser saves a download, watched
    after every click."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Every way out of here leaves a line in the trace. His attempt file
    # came back with an empty list because only a click wrote to it, and
    # four of his five never got as far as a click (#38).
    if not _open_list(page, _list_path_for(title), trace):
        log.info("could not open the documents page for %s", iso_date)
        return False
    # Before the row is looked for, so that no wait sits between the guard
    # approving a control and the press.
    if not _earlier_downloads_settled(page, dl_dir, trace):
        return False

    el, label = _wait_for_control(page, iso_date, trace)
    if el is None:
        log.info("no document control found for %s", iso_date)
        return False
    if not is_safe_control(label):
        _note(trace, "refused the control, the guard said no", control=redact(label)[:60])
        log.info("refusing unsafe control %r for %s", label, iso_date)
        return False
    # The control as the element itself rather than as "the nth control",
    # which is found again when it is pressed and lands on another row once
    # the list redraws in another order. Its name and its date are read
    # again through it now and once more right before the press.
    try:
        el = el.element_handle(timeout=2000)
    except Exception:
        _note(trace, "the row left the page before it could be pressed")
        return False
    why = _still_the_one(el, iso_date, label)
    if why:
        _note(trace, "the row changed before it was pressed, so nothing was pressed", why=why)
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
            body = _fetch_pdf(page, target)
            if body:
                out_path.write_bytes(body)
                _note(trace, "the control's own link answered with a PDF")
                _note(trace, "the PDF landed", how="own link", window="no click")
                return True
            if trace is not None:
                trace.append({"note": "the control's own link did not answer with a PDF",
                              "url": redact(target)[:160]})
    return _catch_pdf(page, el, label, out_path, trace, dl_dir,
                      check=lambda: _still_the_one(el, iso_date, label))


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
    r"^\s*((see|view|show)\s+)?(statements?(\s+(and|&)\s+documents)?|documents|tax\s+(documents|forms)|statement\s+history|"
    r"escrow\s+(analysis|documents)|access\s+my\s+loan|account\s+details|loan\s+details|my\s+loan)\s*$", re.I)


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
    # What the row around a bill control says, with its digits masked.
    # Two rounds went by on a page holding nine statements the app never
    # took, because nothing in the survey said how those rows are dated
    # and the app was asking each for a day of a month it does not print.
    # The mask keeps the shape, which is the whole question (#38).
    out["bill_rows"] = _bill_row_shapes(page)
    return out


def _bill_row_shapes(page, limit: int = 6) -> list:
    """The row each bill control sits in, masked, and what the app makes
    of its date. Digits are masked, so "September 2026" comes back as
    "September ####", which says how a row is dated without saying which
    account it belongs to."""
    rows = []
    try:
        ctrls = _bill_controls(page)
        for i in range(min(ctrls.count(), limit)):
            el = ctrls.nth(i)
            try:
                text = (el.evaluate(_ROW_OF_JS) or "").strip()
            except Exception:
                text = ""
            if not text:
                try:
                    text = (el.evaluate(
                        "el => ((el.closest('tr, li, [role=row]') || el.parentElement"
                        " || el).innerText || '')") or "").strip()
                except Exception:
                    text = ""
            iso, period = parse_period_date(text)
            rows.append({"row": redact(text).replace("\n", " / ")[:160],
                         "read_as": iso or "no date the app can read",
                         "from": period})
    except Exception as e:
        log.info("bill row shapes: %s", e)
    return rows


def survey(page, dwell_ms: int = 4000, max_follow: int = 6) -> dict:
    """What the signed-in documents area looks like, without downloading
    anything. Records each page, its headings and controls with the
    guard's verdict on each, and every JSON or PDF response newrez.com sends
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
                    entry["shape"] = _shape(res.json())
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
ALLOWED_HOSTS = {"newrez.com"}


def is_safe_url(url: str) -> bool:
    """True only for an https URL on one of this provider's own hosts.

    The check itself lives in the core, so all of them answer the same way.
    This app keeps the hosts, which is the part that really is its own."""
    return _host_allows(url, ALLOWED_HOSTS)
