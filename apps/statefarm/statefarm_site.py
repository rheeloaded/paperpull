"""ALL statefarm.com selectors, URLs, and page behavior live here.

When State Farm changes its site, repair this file only.

STATUS: CONFIRMED on the tester's account (#37). Written without a State
Farm account and repaired from surveys, failure files and a recording one
tester sent. Discovery reads State Farm's own list of documents, and on his
account a full run saved every document that list holds for his policies.
On a first run it is deliberately cautious.

  * --login opens a real Edge or Chrome, since statefarm.com's sign-in is happiest in a real browser.
  * --diagnose surveys whatever the documents page turns out to be,
    records its headings, its controls with the guard's verdict on each,
    and the shape of every JSON response, with digit runs masked, and
    takes no screenshot. That file is what a tester attaches to the
    GitHub issue.
  * --discover reads dates from any control that looks like a
    bill, renewal notice, ID card, receipt or policy document, wherever it sits on the page.
  * --pilot tries to save the newest few, by fetching a PDF link the row
    carries from inside the page, or by clicking the row's own control
    and catching a download event, a PDF response or a new tab.

The guesses that most need confirming from a survey are marked GUESS.
The routes are the biggest one.

SAFETY (this is an insurance account with a payment method on file):
  This module is strictly READ-ONLY. It opens the documents and billing
  pages, reads the lists, and saves the PDFs State Farm already
  generated. It must NEVER activate any control that pays, sets up
  autopay, files or reports a claim, changes coverage, adds or removes a
  vehicle, driver or policy, starts a quote, cancels or renews a policy,
  or edits any setting.
  FORBIDDEN_CONTROL_RE is the guard. A control must ALSO look like a
  document action (SAFE_DOC_CONTROL_RE) before it may be clicked. There
  is no code here that submits a form or confirms a dialog.
"""
from __future__ import annotations

import base64
import logging
import re
import time
import unicodedata
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

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
from paperpull_core.capture import fetch_with_status as _fetch_with_status
from paperpull_core.capture import UNFINISHED as _UNFINISHED
from paperpull_core.controls import control_texts as _control_texts
from paperpull_core.controls import second_step as _core_second_step
from paperpull_core.controls import controls_named as _controls_named
from paperpull_core.controls import escape_for_locator
from paperpull_core.dates import checked as _checked_date
from paperpull_core.dates import full_year as _full_year

log = logging.getLogger("statefarm_docs.site")

BASE = "https://my.statefarm.com"
# Read off the first survey (#37, 2026-09-20). Sign-in lands on My
# Accounts at my.statefarm.com. Documents live in the Document Center on
# edocuments.statefarm.com ("View documents & PDFs"), bills and payment
# history in the Payment Center on financials.statefarm.com, ID cards on
# get-id-card.statefarm.com, and each policy's own page behind
# tc-ui.statefarm.com. All are statefarm.com hosts. The Document Center
# is the first route, since it is where the PDFs are expected, and the
# survey has not seen inside it yet.
BILLING_CANDIDATES = [
    "https://edocuments.statefarm.com/DocumentCenterUI/",
    "https://financials.statefarm.com/digital-pay/billHistory",
    f"{BASE}/accounts/",
]
# The Document Center (second survey, #37). edocuments.statefarm.com
# lands on a DocumentCenterUI app that lists documents by category (Auto,
# Billing/Payments, Homeowners) with a Time Period filter, and a "View
# Documents" control per row that opens the PDFs in a new tab. The app
# fills itself from DocumentCenterProxyV1/customerMetadata, whose answer
# is data.attributes[] of {availableDate, category, type, description,
# documentId, filePathUrl, policyId, ...}. Discovery reads that answer as
# the page loads it, then asks the same address for each earlier year. A
# document's PDF is its filePathUrl, fetched from inside the page, with the
# row's own control as the fallback.
#
# RECORDED. The page's own list call carries a query parameter named year,
# and in his 0.37.1 file its value was not four digits. The census keeps
# only the parameter's name and the recording masked its value as not a
# plain word, so all that is known is that it is not a four digit year,
# most likely empty or a short number. The walk looked for four digits
# only, and never asked for an earlier year (#37).
# GUESS. The Time Period menu offers years back to 2023, so the same call
# with the year set to four digits answers for that year. The year walk and
# the download of an older document both rest on this, and Discover prints
# what each year answered, so a wrong guess shows there.
DOCS_API_RE = re.compile(r"/DocumentCenterProxyV1/customerMetadata", re.I)
YEARS_BACK = 7
BILLING_URL = BILLING_CANDIDATES[0]
URLS = {
    "home": f"{BASE}/accounts/",
    # A signed-out visit to My Accounts goes through State Farm's sign-in
    # and back. The customer-care route the first round used landed on a
    # contact page instead.
    "login": f"{BASE}/",
    "documents": BILLING_URL,
    "statements": BILLING_URL,
}

LOGIN_URL_MARKERS = ["/login", "/signin", "/sign-in", "/auth/", "/mfa",
                     "/verification", "/challenge", "/authenticate"]

# ---------------------------------------------------------------------------
# HARD SAFETY GUARD. Tuned for insurer, on top of the bank words. Never move
# money, never change service or coverage, never change a setting.
# ---------------------------------------------------------------------------
FORBIDDEN_CONTROL_RE = re.compile(
    r"(transfer|zelle|\bwire\b|\bpay\b|payment(?!\s+(receipts?|history))|bill\s*pay|autopay|auto\s*pay|"
    r"deposit|withdraw|send\s+money|request\s+money|move\s+money|"
    r"\bapply\b|open\s+(an?\s+)?account|close\s+account|\bloan\b|\bborrow|"
    r"(?<!id )\bcards?\b|replace|activate|lock|unlock|\bpin\b|limit|"
    r"overdraft|alerts?\b|\bbudget|\bgoal|\brewards?\b|\boffers?\b|"
    r"enroll|unenroll|sign\s+up|paperless|delivery\s+preference|"
    r"enable|disable|change\b|edit\b|update\b|modify|manage\b|"
    r"set\s+up|delete|remove|cancel|dispute|"
    r"password|passcode|username|profile\b|settings|preferences|contact\s+info|\baddress\b|"
    r"confirm\b|submit|agree|accept|authorize|\bchat\b|contact\s+us|"
    r"beneficiar|nickname|order\s+checks|stop\s+payment|"
    r"(?<!excludes )\bclaims?\b|file\s+a\s+claim|report\s+(a\s+)?claim|coverage|\bquote\b|add\s+(a\s+)?(vehicle|driver|car|home|policy)|change\s+(my\s+)?policy|cancel\s+policy|renew\s+now|drive\s+safe|start\s+(a\s+)?quote|roadside|\bagent\b|contact\s+(my\s+)?agent|policy\s+change)", re.I)

SAFE_DOC_CONTROL_RE = re.compile(
    r"(download|view|open|print|\bpdf\b|statement|document|\bletter\b|notice|"
    r"1099|1098|5498|tax\s+(form|document)|history|"
    r"id\s+cards?|renewal\s+(notice|bill)|receipts?\b|\bbills?\b|billing\b|policy\s+documents?|declarations?|see\s+(more|all|older)|show\s+(more|all|older)|load\s+more)", re.I)

# A control that fetches one document. GUESS at the wording, wide on
# purpose. "View", "Download", "View PDF", "Statement", "1099-INT".
BILL_CONTROL_RE = re.compile(
    r"((download|view|print|open|get)\s*(my\s+|the\s+|this\s+|your\s+)?(statement|document|pdf|tax|letter|notice|1099|1098)|"
    r"(statement|document|tax\s+form|1099|1098|5498)\s*\(?\s*pdf\s*\)?|\bpdf\b|"
    # A document here is named after what it is rather than after what
    # pressing it does. A recording showed the member opening one called
    # "Renewal Notice - <year make model>", which none of the wording
    # above matches, so once the row was open there was still nothing the
    # app would recognize as a document (#37).
    r"^\s*(renewal\s+(notice|bill)|declarations?(\s+page)?|policy\s+documents?|"
    r"id\s+cards?|insurance\s+cards?|premium\s+notice|billing\s+statement)\b|"
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


def _iso_of(m, kind: str) -> str:
    """One match of DATE_PATTERNS as YYYY-MM-DD. KeyError or ValueError
    when it names no month or year."""
    if kind == "mdY":
        return f"{int(m.group(3)):04d}-{_MONTHS[m.group(1)[:3].lower()]:02d}-{int(m.group(2)):02d}"
    if kind == "mdy_slash":
        return f"{int(m.group(3)):04d}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
    if kind == "mdy_slash2":
        return f"{_full_year(m.group(3)):04d}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
    if kind == "iso":
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    raise ValueError(kind)


def _parse_date_from_page(text: str) -> Optional[str]:
    if not text:
        return None
    for pattern, kind in DATE_PATTERNS:
        m = pattern.search(text)
        if not m:
            continue
        try:
            return _iso_of(m, kind)
        except (KeyError, ValueError):
            continue
    return None


def parse_date(text):
    """The date this provider's page is showing, as YYYY-MM-DD.

    The reading is below, unchanged. This only refuses to believe a result
    that names a day which does not exist, because a reference number is
    shaped like a date and used to be taken for one."""
    return _checked_date(_parse_date_from_page(text), None)


def _date_not_ahead(text) -> Optional[str]:
    """The date `text` names, read the way parse_date reads it, passing
    over any day after tomorrow.

    A document that stays online for two years says until when, and once
    its row is open that line is part of the row. His 0.39.1 Pilot found
    the row, pressed its View Documents, saw the Payment Receipt it
    revealed, and then found no row carrying the date, since the row that
    was drawn again read as the day two years on (#37). No document is
    dated ahead, the list's own dates are never taken past tomorrow either
    (is_future), so a day ahead is never a row's. A day that does not exist
    still reads as no date, as it does in parse_date."""
    if not text:
        return None
    for pattern, kind in DATE_PATTERNS:
        for m in pattern.finditer(text):
            try:
                iso = _iso_of(m, kind)
            except (KeyError, ValueError):
                break
            checked = _checked_date(iso, None)
            if checked and is_future(checked):
                continue
            return checked
    return None


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
    return bool(re.search(r"bill(ing)?\s+(history|period|date)|past\s+bills|renewal\s+notice|id\s+cards?|policy\s+documents|payment\s+receipts?|document\s+center|documents\s*&\s*pdfs",
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


# A row on the Document Center keeps its documents folded away behind a
# button of its own, and a recording showed the member pressing one
# before any document link existed to press (#37). "View Documents2" is
# how the second row's button names itself, so the number at the end is
# part of the name and not part of the question.
VIEW_DOCUMENTS_RE = re.compile(r"^\s*view\s+documents?\s*\d*\s*$", re.I)


def reveal_documents(page, limit: int = 20) -> int:
    """Press each row's own View Documents, so the document links exist.

    Returns how many were pressed. Without this the page holds no link to
    any document, `expand_all` does not press it because its name is not
    "view more" or "view all", and a run reported finding four documents
    and no control on the page for any of them."""
    pressed = 0
    try:
        for role in ("button", "link"):
            loc = page.get_by_role(role, name=VIEW_DOCUMENTS_RE)
            count = min(loc.count(), limit)
            for i in range(count):
                el = loc.nth(i)
                try:
                    if not el.is_visible():
                        continue
                    label = (el.get_attribute("aria-label")
                             or el.inner_text(timeout=800) or "").strip()
                except Exception:
                    continue
                if not VIEW_DOCUMENTS_RE.match(label) or not is_safe_control(label):
                    continue
                try:
                    el.click(timeout=5000)
                    pressed += 1
                    page.wait_for_timeout(1200)
                except Exception as e:
                    log.info("view documents: %s", e)
    except Exception as e:
        log.info("reveal documents: %s", e)
    if pressed:
        log.info("opened %d row(s) of documents", pressed)
    return pressed


# What a row's View Documents reveals. The recording showed "Renewal Notice
# - <year make model>" and a Pilot showed "Payment Receipt - Payment
# Receipt", so a document is named "<type> - <description>" and opens in a
# new tab (#37). Its own allowlist, narrow on purpose, and only ever pressed
# when it appeared after this row was opened and still sits inside that
# row, which _still_in_its_row reads right before every press. Appearing
# after the press used to be enough, and a list drawn again after the press
# opened another row and had its document pressed (#37).
REVEALED_DOC_RE = re.compile(r"^\s*[A-Za-z][A-Za-z0-9&/'(). ]{1,60}?\s+-\s+\S.{0,80}$")


# A revealed document's description, after the dash, names what the
# document is about, a vehicle, a policy, how a payment was made. The whole
# guard read a money noun there as a control that pays, "Payments" in the
# list's own "Payment Receipt - Billing/Payments", and his Payment Receipt of
# 2025-03-11 was never fetched (#37). A description is read three ways. It is
# refused when it tells someone to do something, a verb at its start or one
# of a few commands anywhere in it, and when it asks to sign in.
_DESCRIPTION_ACTION_RE = re.compile(
    r"^\s*(pay|transfer|send|request|move|apply|activate|replace|lock|unlock|enroll|unenroll|"
    r"enable|disable|change|edit|update|modify|manage|set\s+up|delete|remove|cancel|dispute|"
    r"confirm|submit|agree|accept|authorize|consent|certify|add|renew|stop|schedule|close|"
    r"open|withdraw|deposit|buy|sell|place\s+(an\s+)?order|rebalance|reallocate|liquidate|"
    r"turn\s+(on|off)|opt\s*(in|out)|save\s+(changes?|settings?|preferences?)|"
    r"sign\s+(up|in|on)|log\s*in|chat|contact|call)\b"
    r"|\bpay\s+(now|online|today|(your|my|the)\s+(bill|premium|balance))\b|"
    r"\bmake\s+(a\s+)?payment|\bsign\s+up\b|\bfile\s+a\s+claim|\breport\s+(a\s+)?claim|"
    r"\brenew\s+now|\bstart\s+(a\s+)?quote|\b(send|move|request)\s+money", re.I)

# And the description faces the whole guard too, less the few nouns a
# document is known to be named by, and only in the shape they take. A money
# noun is let off only when it is the whole description, the category a
# receipt is listed under or how it was paid, and Limited only in a vehicle's
# name, a model year and the plain words of a make and model. A word nobody
# has seen on a document is still refused, and the trace says which. Reviews
# before release found a list of verbs alone letting through every way of
# saying pay, switch or file that it did not name, "Switch to autopay" and
# "Go paperless", and a noun let off wherever it sat carrying a verb in,
# "Use this card ending 4321", "Switch to Limited Tort", a coverage election.
_WHOLE_NOUN_RE = re.compile(
    r"billing\s*/\s*payments?"
    r"|\b((credit|debit)\s+)?card\s+ending(\s+in)?\s+[\dxX*\u2022.]{2,}"
    r"|auto\s*pay|payments?|wire|bill\s*pay", re.I)
# A vehicle's name, a model year and words that each start with a letter or
# a digit, so a lone dash or slash cannot join a second clause to it. Its
# Limited is the trim only at the end, or before Edition, a drive or a
# powertrain word, since "2025 Switch to Limited Tort" is shaped like a
# vehicle too (a third review before release).
_VEHICLE_RE = re.compile(r"(19|20)\d\d(\s+[A-Za-z0-9][A-Za-z0-9&'./-]*)+")
_LIMITED_TRIM_RE = re.compile(
    r"\blimited(?=(\s+(edition|awd|fwd|rwd|4wd|4x4|platinum|hybrid))*$)", re.I)


def _description_left(description: str) -> str:
    """What of a description faces the whole guard. Nothing when the whole
    of it is one of the known nouns, a vehicle's name less its trim Limited,
    else all of it."""
    text = " ".join((description or "").split())
    if _WHOLE_NOUN_RE.fullmatch(text):
        return ""
    if _VEHICLE_RE.fullmatch(text):
        return _LIMITED_TRIM_RE.sub(" ", text)
    return text


def _plain(text: str) -> str:
    """Text as it is compared with the list's, its case, spacing and
    compatibility forms aside, so a ligature reads as its letters."""
    return " ".join(unicodedata.normalize("NFKC", text or "").split()).lower()


def _said_by_the_list(description: str, label: str, own, cut: bool = False) -> bool:
    """Whether a revealed document's description, or its whole name, is
    one of `own`, what State Farm's list calls this document.

    `cut` says the name was read cut short, the way the page's controls
    are listed, at _CUT_AT characters, and then it only has to be the start
    of one of them. A receipt named past sixty characters was never matched
    otherwise. The name read whole off the node before the press is held to
    all of it (_revealed_document)."""
    if not own:
        return False
    d, n = _plain(description), _plain(label)
    if d in own or (n and n in own):
        return True
    if cut:
        return any(w.startswith(d) or (n and w.startswith(n)) for w in own)
    return False


def _description_rules(description: str):
    """The (text, rule) pairs a description is read by, in order."""
    left = _description_left(description)
    return [(description, _DESCRIPTION_ACTION_RE), (description, AUTH_CONTROL_RE),
            (left, FORBIDDEN_CONTROL_RE), (left, SETTINGS_CONTROL_RE)]


# The money words a receipt is described by, and nothing else. His Payment
# Receipt of 2025-03-11 was refused twice for one of them in its
# description, the second time on 0.41.1, in a shape no list of whole
# descriptions here had guessed (#37).
_LIST_MONEY_RE = re.compile(
    r"\b(payments?|paid|billing|receipts?)\b"
    r"|\b((credit|debit)\s+)?card\s+ending(\s+in)?\s+[\dxX*\u2022.]{2,}", re.I)


def _own_rules(description: str):
    """The rules a description is read by when it is what State Farm's own
    list calls this document. The same rules, read in its compatibility
    form, with the money words of _LIST_MONEY_RE taken out before the whole
    guard reads it, so a word that acts or a setting is refused as ever."""
    text = unicodedata.normalize("NFKC", description)
    left = _LIST_MONEY_RE.sub(" ", _description_left(text))
    return [(text, _DESCRIPTION_ACTION_RE), (text, AUTH_CONTROL_RE),
            (left, FORBIDDEN_CONTROL_RE), (left, SETTINGS_CONTROL_RE)]


def _rules_for(description: str, label: str, own=(), cut: bool = False):
    """The rules a revealed document's description is read by.

    `own` is what State Farm's own list calls this document, its
    description and its category, from the list the page fetched for the
    load the row is found on (_own_words). A description the rules of
    _description_rules refuse gets a second reading by _own_rules when it,
    or the whole name, is one of those, and never a stricter one."""
    rules = _description_rules(description)
    if any(rule.search(text) for text, rule in rules) and \
            _said_by_the_list(description, label, own, cut):
        return _own_rules(description)
    return rules


_DOCUMENT_PARTS_RE = re.compile(r"^\s*(.+?)\s+-\s+(.*?)\s*$")


def _document_parts(label: str):
    """(type, description) of a name shaped like a revealed document, split
    at the first dash, or None."""
    m = _DOCUMENT_PARTS_RE.match(" ".join((label or "").split()))
    return (m.group(1), m.group(2)) if m else None


def is_revealed_document(label: str, own=(), cut: bool = False) -> bool:
    """A document link a row revealed, once the guard has had its say.

    The type, before the dash, faces the whole guard, so "Pay Now - Payment
    Receipt" is refused however well it is shaped. The description, after
    it, faces the words that act, and the whole guard too once the nouns a
    document is known to be named by are taken out of it (#37). One that is
    what the list calls this document, `own`, is read again by _own_rules,
    and `cut` says the label was read cut short (_rules_for)."""
    cut = cut and len(label or "") >= _CUT_AT
    label = " ".join((label or "").split())
    if not label or VIEW_DOCUMENTS_RE.match(label) or not REVEALED_DOC_RE.match(label):
        return False
    parts = _document_parts(label)
    if parts is None:
        return False
    kind, description = parts
    if _guard_refuses_words(kind):
        return False
    return not any(rule.search(text)
                   for text, rule in _rules_for(description, label, own, cut))


def _guard_refuses_name(text: str, want=None, own=()) -> bool:
    """The guard on a whole name, the name a control gives a screen reader
    say. A name shaped like a revealed document, and of the wanted type
    when `want` is given, is read the way a document's own words are.
    Anything else faces the whole guard, since "Make a - payment" is shaped
    like a document and its type is nobody's."""
    text = " ".join((text or "").split())
    if not text:
        return False
    if REVEALED_DOC_RE.match(text) and not VIEW_DOCUMENTS_RE.match(text) and \
            (want is None or _type_key(text) == want):
        return not is_revealed_document(text, own)
    return _guard_refuses_words(text)


def _refused_document(label: str, own=(), cut: bool = False) -> bool:
    """Shaped like a revealed document and refused by the guard.

    The trace used to call such a document "another control", which cannot
    be told from something that is not a document at all (#37). The label
    goes on as it came, since whether it was cut is read off its raw
    length."""
    text = " ".join((label or "").split())
    if not text or VIEW_DOCUMENTS_RE.match(text) or not REVEALED_DOC_RE.match(text):
        return False
    return not is_revealed_document(label, own, cut)


# The words a trace may give for why the guard refused a document, the
# guard's own and nothing the page printed. A match not listed here is
# "another word".
_GUARD_WORDS = frozenset([
    "transfer", "zelle", "wire", "pay", "payment", "bill pay", "billpay", "autopay", "auto pay",
    "deposit", "withdraw", "send money", "request money", "move money", "apply", "loan",
    "borrow", "card", "cards", "replace", "activate", "lock", "unlock", "pin", "limit",
    "overdraft", "alert", "alerts", "budget", "goal", "reward", "rewards", "offer", "offers",
    "enroll", "unenroll", "sign up", "paperless", "delivery preference", "enable", "disable",
    "change", "edit", "update", "modify", "manage", "set up", "delete", "remove", "cancel",
    "dispute", "password", "passcode", "username", "profile", "settings", "preferences",
    "contact info", "address", "confirm", "submit", "agree", "accept", "authorize", "chat",
    "contact us", "beneficiar", "nickname", "order checks", "stop payment", "claim", "claims",
    "file a claim", "coverage", "quote", "roadside", "agent", "contact agent", "policy change",
    "renew now", "drive safe", "send", "request", "move", "stop", "schedule", "close", "open",
    "add", "sign in", "sign on", "login", "log in", "call", "contact", "make a payment",
    "make payment", "pay now", "pay online", "pay today", "report a claim", "report claim",
    "start a quote", "start quote", "consent", "certify", "buy", "sell", "place order",
    "place an order", "rebalance", "reallocate", "liquidate", "turn on", "turn off", "opt in",
    "opt out", "optin", "optout", "save changes", "save change", "save settings",
    "save setting", "save preferences", "save preference", "withholding", "authorization",
    "application", "beneficiary", "beneficiaries", "set up"])


def _refusing_word(label: str, own=(), cut: bool = False) -> str:
    """The guard's own word for why it refused a revealed document, from
    _GUARD_WORDS, else "another word". Nothing the page printed leaves."""
    cut = cut and len(label or "") >= _CUT_AT
    parts = _document_parts(label)
    if parts is None:
        return "another word"
    kind, description = parts
    checks = [(kind, FORBIDDEN_CONTROL_RE), (kind, SETTINGS_CONTROL_RE), (kind, AUTH_CONTROL_RE)]
    for text, rule in checks + _rules_for(description, label, own, cut):
        m = rule.search(text)
        if m:
            word = " ".join(m.group(0).lower().split())
            return word if word in _GUARD_WORDS else "another word"
    return "another word"


def _type_key(text: str) -> str:
    """The document type, the part before " - ", as bare letters and
    digits. "Payment Receipt - Billing/Payments" from the list and
    "Payment Receipt - Payment Receipt" on the page both give
    "paymentreceipt"."""
    return re.sub(r"[^a-z0-9]", "", (text or "").split(" - ")[0].lower())


# -- what a trace may say about a control ---------------------------------------
#
# download-attempt.json is a file testers are asked to post on a public
# issue, so everything in it comes from a list of what may leave. A control
# is named by a fixed word, a document by its type when the type is one of
# these, and nothing a page printed goes in as it stands. A revealed
# document is named "<type> - <description>" and the description can be a
# vehicle or a policy (the member took his out of the recording himself), so
# the description never leaves (#37).
_KNOWN_TYPES = {
    "renewalnotice": "Renewal Notice", "renewalbill": "Renewal Bill",
    "paymentreceipt": "Payment Receipt", "premiumnotice": "Premium Notice",
    "billingstatement": "Billing Statement", "bill": "Bill",
    "declarations": "Declarations", "declarationspage": "Declarations Page",
    "idcard": "ID Card", "idcards": "ID Cards", "autoidcard": "Auto ID Card",
    "insurancecard": "Insurance Card", "insurancecards": "Insurance Cards",
    "policydocument": "Policy Document", "policydocuments": "Policy Documents",
}
_VIEW_N_RE = re.compile(r"^\s*view\s+documents?\s*(\d{1,3})?\s*$", re.I)


def _type_word(text: str) -> str:
    """The document type of a label or a title, when it is one State Farm
    uses for everybody, else a fixed phrase."""
    return _KNOWN_TYPES.get(_type_key(text), "another type")


# A known type named anywhere in a control's words, the longest name first
# so "Declarations Page" is not read as "Declarations".
_TYPE_NAME_RE = re.compile(
    r"\b(" + "|".join(re.escape(v).replace(r"\ ", r"\s+")
                      for v in sorted(_KNOWN_TYPES.values(), key=len, reverse=True)) + r")\b",
    re.I)


def _named_type(label: str) -> str:
    """The document type a control's own words name, as a type key, or ""
    when they name none ("View PDF", "Download", "View Documents2")."""
    text = " ".join((label or "").split())
    if not text or VIEW_DOCUMENTS_RE.match(text):
        return ""
    if REVEALED_DOC_RE.match(text):
        return _type_key(text)
    m = _TYPE_NAME_RE.search(text)
    return _type_key(m.group(0)) if m else ""


def _same_type(a: str, b: str) -> bool:
    """Two type keys that name one type, "ID Cards" and "ID Card" alike."""
    return bool(a) and a.rstrip("s") == (b or "").rstrip("s")


def _other_type_named(text: str, want: str) -> str:
    """The first known document type `text` names that is not `want`, as a
    type key, or "" when it names no other.

    For the words of a row whose one control names no type ("View PDF"). A
    row that names the wanted type and another one too cannot say which of
    them that control is, so any other one is enough to refuse it (#37)."""
    text = " ".join((text or "").split())
    for m in _TYPE_NAME_RE.finditer(text):
        key = _type_key(m.group(0))
        if not _same_type(key, want):
            return key
    return ""


def _names_type(text: str, want: str) -> bool:
    """Whether `text` names the wanted type key. A row whose one control
    names no type has to say what it is, since a row naming no type or one
    this file does not know, such as Proof of Insurance, was saved as the
    Renewal Notice asked for on its date (final review of #37)."""
    text = " ".join((text or "").split())
    return any(_same_type(_type_key(m.group(0)), want) for m in _TYPE_NAME_RE.finditer(text))


def _label_mask(label: str, own=(), cut: bool = False) -> str:
    """A control's name as a trace may carry it, from a list and never the
    page's own words. Named a mask so the repo-wide check on trace entries
    knows it for a cleaner, and stricter than one, since nothing it returns
    was printed by the page except a row number and fixed words."""
    text = " ".join((label or "").split())
    if not text:
        return "nothing"
    m = _VIEW_N_RE.match(text)
    if m:
        return "View Documents" + (m.group(1) or "")
    if is_revealed_document(label, own, cut):
        return "%s - ..." % _type_word(text)
    if _refused_document(label, own, cut):
        return "%s - ..., refused by the guard for %s" % (_type_word(text),
                                                          _refusing_word(label, own, cut))
    if _SECOND_STEP_RE.match(text):
        return text.lower()[:30]
    return "another control"


# The words a refused description may be told by in a trace, the ordinary
# words a document's description is made of and nothing that names anybody.
# Any other word is "*", a run of digits "#", and a mark not listed "?". His
# receipt was refused twice and the trace could only say for which word of
# the guard's, so the second repair rested on a guess (#37). Left out, a word
# that is also a first name, Bill, a card's brand, the kind of bank account,
# and a payment that was declined, returned, reversed or canceled, since the
# file is posted in public (review).
_DESCRIPTION_WORDS = frozenset("""
a an the and or of for to on in by with from at your you thank thanks
payment payments paid pay receipt receipts billing billed statement statements
invoice confirmation confirmed received processed posted applied accepted submitted
completed pending online web mobile app phone mail agent office automatic auto autopay
recurring scheduled one time onetime monthly quarterly annual installment installments
plan premium premiums policy policies account accounts card ending credit debit
bank eft electronic funds transfer check draft drafts ach wire sfpp state farm
insurance home homeowners renters condo life fire health umbrella vehicle notice
renewal document documents letter refund refunds change update amount balance due
date method number no id limited new past final partial full initial down first
last current summary copy details detail
""".split())
_DESCRIPTION_MARKS = frozenset("-/&,.:()#'")
_DESCRIPTION_TOKEN_RE = re.compile(r"[^\W\d_]+|\d+|\S")


def _description_mask(label: str, cut: bool = False) -> str:
    """A revealed document's description as a trace may carry it, each word
    one of _DESCRIPTION_WORDS or a placeholder, at most sixteen. Built from
    that list, so nothing the page printed leaves as it stands. `cut` says
    the label was read cut short, and one as long as the cut ends "...",
    since its last word may be a part of one."""
    parts = _document_parts(label)
    if parts is None:
        return ""
    out = []
    for tok in _DESCRIPTION_TOKEN_RE.findall(parts[1]):
        low = tok.lower()
        if low in _DESCRIPTION_WORDS:
            out.append(low)
        elif tok.isdigit():
            out.append("#")
        elif tok in _DESCRIPTION_MARKS:
            out.append(tok)
        elif tok.isalpha():
            out.append("*")
        else:
            out.append("?")
    more = len(out) > 16 or (cut and len(label or "") >= _CUT_AT)
    return " ".join(out[:16]) + (" ..." if more else "")


def _list_says(appeared, want: str, own) -> str:
    """Whether a revealed document of the wanted type is named as the list
    names this document, as a fixed phrase. A name read cut short that only
    starts as the list's says so."""
    if not own:
        return "the list gave no words for it"
    said = "no"
    for t in appeared:
        parts = _document_parts(t)
        if not parts or _type_key(t) != want:
            continue
        if _said_by_the_list(parts[1], t, own):
            return "yes"
        if len(t or "") >= _CUT_AT and _said_by_the_list(parts[1], t, own, cut=True):
            said = "its first sixty characters"
    return said


def _own_words(answers, hint: str) -> tuple:
    """What State Farm's list calls the document `hint` names, its
    description and its category as _plain text, read from the list
    answers of the load its row is found on. Nothing when there is no hint,
    or when no entry, or more than one document, carries it.

    `hint` is what discovery kept, the document's file address when the list
    gave one and its id when it did not, and it is matched against both.
    Every entry carrying it has to be the same document, its type, date,
    category and description too, since two that share an id would pool
    their words (review). The words are compared in memory and never
    written anywhere."""
    if not hint:
        return ()
    found = []
    for body in answers or []:
        data = body.get("data") if isinstance(body, dict) else None
        entries = data.get("attributes") if isinstance(data, dict) else None
        for e in entries if isinstance(entries, list) else []:
            if isinstance(e, dict) and hint in (str(e.get("filePathUrl") or ""),
                                                str(e.get("documentId") or "")):
                found.append(e)
    whose = {tuple(str(e.get(k) or "") for k in ("documentId", "filePathUrl", "type",
                                                 "creationDate", "category", "description"))
             for e in found}
    if len(whose) != 1:
        return ()
    words = {_plain(str(e.get(k) or "")) for e in found for k in ("description", "category")}
    return tuple(sorted(w for w in words if w))


def _attr_word(value) -> str:
    """aria-expanded as one of four words."""
    if value is None:
        return "absent"
    v = str(value).strip().lower()
    return v if v in ("true", "false") else "other"


def _click_failure(e: Exception) -> str:
    """Why a press failed, as a fixed phrase. Playwright's own message
    quotes the locator, and the locator quotes the control's name."""
    msg = str(e).lower()
    if "intercepts pointer events" in msg:
        return "something else on the page was in the way"
    if "not visible" in msg:
        return "it was not visible"
    if "detached" in msg or "not attached" in msg:
        return "it left the page"
    if "timeout" in msg:
        return "timed out"
    return "some other error"


# The core's control_texts cuts every name to this many characters, so a
# name that long in what a press revealed can be longer on the page.
_CUT_AT = 60


class _Found(list):
    """What a look for controls found, and how many it could not read. One
    that could not be read may be one of them, so a count of the rest is
    not a count of them all, and every count of these refuses then (the
    census after CI run 36792330947)."""
    unread = 0


def _visible_named(page, text: str, whole: bool = False) -> list:
    """The visible controls named `text`, as nodes, at most five.

    A name as long as the core cuts one is matched by how it starts, since
    the control's own name is longer. A revealed document of seventy
    characters, "Renewal Notice - " and a long vehicle, was looked for by
    its first sixty and never found (#37). `whole` matches the whole name
    and nothing else, for a name read off the node itself."""
    tail = "$" if whole or len(text) < _CUT_AT else ""
    pattern = re.compile("^" + escape_for_locator(text) + tail, re.I)
    for loc in (page.get_by_role("link", name=pattern), page.get_by_role("button", name=pattern),
                page.locator("a, button, [role=button], [role=link]").filter(has_text=pattern)):
        found = _Found()
        try:
            for h in loc.element_handles()[:5]:
                try:
                    if h.is_visible():
                        found.append(h)
                except Exception:
                    found.unread += 1
        except Exception:
            # The look itself could not be made, as when a name with a
            # slash in it reaches a role's pattern, and the next look is
            # made instead. Only a control it found and could not read
            # counts as unread.
            found = _Found()
        if found or found.unread:
            return found
    return _Found()


# Every name a screen reader may give the node, aria-label, the text of the
# elements aria-labelledby points at, and title, each asked of the guard. The
# node is found by any of them, so reading aria-label alone let a control
# labelled elsewhere as one that pays through (#37).
_DOC_NAME_JS = r"""el => {
  const by = (el.getAttribute('aria-labelledby') || '').split(/\s+/).filter(Boolean)
    .map(id => { const n = document.getElementById(id); return n ? (n.textContent || '') : ''; })
    .join(' ');
  return [el.innerText || '', el.getAttribute('aria-label') || '', by,
          el.getAttribute('title') || '', el.isConnected];
}"""


def _doc_name(el) -> Optional[dict]:
    """A revealed document's whole name, the names it gives a screen reader
    and whether it is on the page, read off the node in one call, or None."""
    try:
        got = el.evaluate(_DOC_NAME_JS)
    except Exception:
        return None
    if not isinstance(got, list) or len(got) != 5:
        return None
    text, aria, labelled_by, title, connected = got
    names = [" ".join(str(n or "").split()) for n in (aria, labelled_by, title)]
    return {"name": " ".join(str(text or "").split()), "aria": names[0],
            "names": [n for n in names if n], "connected": bool(connected)}


def _guard_refuses_words(text: str) -> bool:
    """True when the guard's words refuse `text`, whatever its shape."""
    return bool(FORBIDDEN_CONTROL_RE.search(text) or SETTINGS_CONTROL_RE.search(text)
                or AUTH_CONTROL_RE.search(text))


def _revealed_document(page, appeared: set, title: str, own=()):
    """The one document link that appeared after this row's press and is
    the wanted type, as (node, whole name, why). None when there is not
    exactly one, because a row can hold several and the wrong one would be
    saved under this document's name. Appearing after the press does not
    make it this row's, so it is tied to the row right before it is
    pressed, by _still_in_its_row (#37).

    What appeared is names cut to sixty characters, so the node found is
    read again whole and the guard is asked about the whole name, and about
    the name it gives a screen reader when it has one. A word the guard
    refuses past the sixtieth character is still refused (#37)."""
    if not getattr(appeared, "complete", True):
        return None, "", "the controls on the page could not all be read, so what the row revealed is not known"
    want = _type_key(title)
    candidates = sorted(t for t in appeared if is_revealed_document(t, own, cut=True))
    if not candidates:
        if any(_refused_document(t, own, cut=True) for t in appeared):
            return None, "", "what the row revealed looks like a document and the guard refuses it"
        return None, "", "nothing the row revealed looks like a document"
    if not want or want == "document":
        return None, "", "this document has no type to match against"
    same = [t for t in candidates if _type_key(t) == want]
    if len(same) != 1:
        return None, "", ("%d revealed documents are this type, and one is needed" % len(same))
    text = same[0]
    found = _visible_named(page, text)
    if found.unread:
        return None, "", "a control carrying that name could not be read"
    if len(found) != 1:
        return None, "", ("%d visible controls carry that name, and one is needed" % len(found))
    el = found[0]
    read = _doc_name(el)
    if read is None or not read["connected"]:
        return None, "", "the document left the page before it could be read whole"
    name = read["name"]
    # What appeared is each control's own words, and the node is found by its
    # accessible name, which is the name it gives a screen reader when it has
    # one. So its own words have to start with the name it was found by and
    # carry the wanted type, or it is some other control whose screen reader
    # name happens to be that document's (#37).
    if not name.startswith(text) or _type_key(name) != want:
        return None, "", "the control found by that name does not read as that document"
    # Its own words start with the type and the start of the description it
    # was found by, so only the guard is asked again, about the whole name.
    if not is_revealed_document(name, own) or \
            any(_guard_refuses_name(n, want, own) for n in read["names"]):
        return None, "", "the guard refuses the document's whole name"
    return el, name, ""


def _still_the_document(page, el, name: str, row, iso: str, facts: Optional[dict] = None,
                        row_is: str = "the row that was pressed") -> str:
    """Why the revealed document about to be pressed is no longer the one
    that was checked, or can no longer be tied to its row, as a fixed
    phrase, or "" when it is still both.

    Its own name and count are read again first, the same check the row's
    own control gets before its press (#37). Then _still_in_its_row ties it
    to `row`, the control that was pressed, or the one found again in its
    place when the press drew the row anew, which `row_is` names. `facts`
    gets what that says about where the document sat when it was not inside
    the row."""
    read = _doc_name(el)
    if read is None:
        return "it could not be read again"
    if not read["connected"]:
        return "it left the page"
    if read["name"] != name:
        return "its name changed"
    named = _visible_named(page, name, whole=True)
    if named.unread:
        return "a control carrying its name could not be read"
    n = len(named)
    if n != 1:
        return "%d visible controls carry its name now" % n
    return _still_in_its_row(page, row, el, name, iso, facts, row_is)


def _still_in_its_row(page, row, doc, name: str, iso: str, facts: Optional[dict] = None,
                      row_is: str = "the row that was pressed") -> str:
    """Why the revealed document `doc` cannot be tied to the row whose
    control `row` was pressed, as a fixed phrase, or "" when it can.

    `row` is the control found again by the date when the press drew the
    row anew and the one pressed left the page (_row_found_again), and
    everything below is asked of that one instead. `row_is` names which of
    the two it is, one of those two fixed phrases.

    After the press nothing tied the document to the row. Any new document
    of the wanted type anywhere on the page was taken, so a list drawn again
    after the press, keeping its open row by its place in the list, opened
    the row above and had its receipt saved under this one's name. A list
    patched in place did the same with the pressed node still on the page
    (#37). So all of these have to hold, right before every press of the
    document, the one made through the page included.

      * The pressed control is still on the page.
      * It still carries this date, read the way discovery reads one.
      * It is still the only row that does. No other control outside its
        row carries the date, and no other View Documents inside it does.
        The documents the row revealed carry its date too and are not
        counted, and neither is the document about to be pressed wherever
        it sits, since the last check below refuses it outside the row and
        says where it sat. Another row's View Documents is, since a date printed as
        a heading over several rows makes that whole block the row, and a
        row added to it after the press was opened in the pressed row's
        place and had its notice taken as this one.
      * The document sits inside its row, the ancestor _ROW_OF_JS stops at.

    Those and the document's own name and place on the page are read in one
    call, so what they say holds for one moment. The pressed control is
    never compared by its name. A tester's file showed "View Documents 1"
    after a press where the button had said "View Documents1", so an opened
    row can rename its button (#37).

    `facts` gets where the document sat instead, as yes or no, when it was
    not inside the row. A page whose documents open in the element after the
    dated row, or in a dialog, rather than inside it, is refused here, and
    those say so."""
    if not iso:
        return "there is no date to tie the document to its row"
    dated = _controls_for(page, iso)
    handles = [h for h, _ in dated]
    if dated.unread:
        for h in handles:
            try:
                h.dispose()
            except Exception:
                pass
        return "a control on the page could not be read"
    openers = [bool(VIEW_DOCUMENTS_RE.match(" ".join((n or "").split()))) for _, n in dated]
    try:
        got = row.evaluate(_TIE_JS, [doc, handles, openers])
    except Exception:
        got = None
    finally:
        for h in handles:
            try:
                h.dispose()
            except Exception:
                pass
    if not isinstance(got, list) or len(got) != 13:
        return "the row's control could not be read again"
    (row_on, row_name, row_text, doc_on, doc_text, inside, outside, openers_inside,
     in_parent, in_next, in_dialog, openers_anywhere, in_row) = got
    if not row_on:
        return "the row's control left the page"
    if _date_of({"name": str(row_name or "").strip(), "row": str(row_text or ""),
                 "in_row": in_row is True}) != iso:
        return "the row's control no longer carries this date"
    if not isinstance(outside, int) or outside < 0 or \
            not isinstance(openers_inside, int) or openers_inside < 0:
        return "the row's control could not be read again"
    if outside == 1:
        return "another control outside the row carries this date now"
    if outside > 1:
        return "%d other controls outside the row carry this date now" % outside
    if openers_inside == 1:
        return "another View Documents inside the row carries this date now"
    if openers_inside > 1:
        return "%d other View Documents inside the row carry this date now" % openers_inside
    # Another row's View Documents inside the box, whatever date it reads.
    # One whose opened row says only until when its document stays online
    # reads no date at all, so counting only those that read this date let
    # a row opened in place under a date heading pass as this one (#37).
    if not isinstance(openers_anywhere, int) or openers_anywhere < 0:
        return "the row's control could not be read again"
    if openers_anywhere:
        return "another View Documents sits inside the row"
    if not doc_on:
        return "it left the page"
    if " ".join(str(doc_text or "").split()) != name:
        return "its name changed"
    if not row_text:
        return "the row's control is in no row that carries a date"
    if not inside:
        if facts is not None:
            facts.update({"in_the_row": False, "in_the_element_after_the_row": bool(in_next),
                          "in_the_rows_parent": bool(in_parent), "in_a_dialog": bool(in_dialog)})
        return "the document is not inside %s" % row_is
    return ""


def _row_found_again(page, iso: str):
    """The one row on the page that carries `iso`, found again by its View
    Documents after a press drew the row anew, as (node, rows, unread).
    `node` is None unless exactly one View Documents carries the date and
    every control could be read, `rows` is how many do, and `unread` how
    many controls could not be read.

    A row is known by its View Documents and the date it reads, the same
    way download_bill found it before its press. The documents a row
    revealed carry its date too, and are not rows. Two rows carrying one
    date cannot be told apart, and no row with it means the press took the
    page somewhere else, so neither gives a row to tie a document to (#37).
    """
    if not iso:
        return None, 0, 0
    openers, others = [], []
    dated = _controls_for(page, iso)
    for h, name in dated:
        (openers if VIEW_DOCUMENTS_RE.match(" ".join((name or "").split())) else others).append(h)
    for h in others + (openers if len(openers) != 1 or dated.unread else []):
        try:
            h.dispose()
        except Exception:
            pass
    if len(openers) != 1 or dated.unread:
        return None, len(openers), dated.unread
    return openers[0], 1, 0


def _openers_read(page, iso: str) -> dict:
    """How each View Documents on the page reads its date now, as counts,
    for the trace when the pressed row is not the one row carrying its date
    after the press. A row whose every date is after tomorrow is counted
    apart, so the next file says whether reading the dates is still what
    stands in the way (#37)."""
    counts = {"openers": 0, "with_this_date": 0, "with_another_date": 0,
              "only_days_ahead": 0, "with_no_date": 0}
    try:
        handles = _bill_controls(page).element_handles()
    except Exception:
        return counts
    for n, h in enumerate(handles):
        got = _read_control(h) if n < 40 else None
        try:
            h.dispose()
        except Exception:
            pass
        if got is None or not VIEW_DOCUMENTS_RE.match(" ".join(got["name"].split())):
            continue
        counts["openers"] += 1
        day = _date_of(got)
        if day == iso:
            counts["with_this_date"] += 1
        elif day:
            counts["with_another_date"] += 1
        else:
            any_day = parse_date(got["name"]) or parse_date(got["row"])
            counts["only_days_ahead" if any_day and is_future(any_day) else "with_no_date"] += 1
    return counts


def _open_row_then_document(page, el, label: str, title: str, out_path: Path,
                            trace: Optional[list], dl_dir, census=None, check=None,
                            iso: str = "", own=()) -> bool:
    """Press the row's View Documents once, then the document it revealed.

    A Pilot pressed View Documents, saw "Payment Receipt - Payment Receipt"
    appear and stopped there, because nothing pressed the document itself
    (#37). The row's button is pressed exactly once. Pressing it again
    would fold the row away, so a row that is already open is left alone
    and the trace says so.

    `check` says, right before the press, why the control is no longer the
    one that was checked, or nothing when it still is. The revealed
    document gets the same check before its own press, and is also tied to
    this row then, by `iso`, the document's date (_still_in_its_row). When
    the press draws the row anew, the control pressed leaves the page and
    the row is found again by `iso` (_row_found_again). Only the one row on
    the page that carries the date can hold the document then, and two rows
    with it, or none, press nothing more. `census` is the run's request
    census, which is not listening while the document is pressed and
    caught. `own` is what State Farm's list calls the document
    (_own_words)."""
    def note(entry):
        if trace is not None:
            trace.append(entry)

    try:
        expanded = el.get_attribute("aria-expanded")
    except Exception:
        expanded = None
    if expanded == "true":
        note({"note": "the row was already open, so its View Documents was not pressed again",
              "control": _label_mask(label)})
        return False
    before = _control_texts(page)
    try:
        el.scroll_into_view_if_needed(timeout=4000)
    except Exception:
        pass
    why = check() if check is not None else ""
    if why:
        note({"note": "the row's control changed before it was pressed, so nothing was pressed",
              "why": why})
        return False
    # Whether the page asked for its list again after the press, counted.
    # A list asked for again with the page's own period would drop a row
    # from an earlier year, and his 0.39.1 file could not say (#37).
    list_calls: list = []

    def on_list(res):
        try:
            if is_safe_url(res.url or "") and DOCS_API_RE.search(res.url or ""):
                list_calls.append(1)
        except Exception:
            pass
    try:
        page.on("response", on_list)
    except Exception:
        pass
    try:
        try:
            el.click(timeout=8000)
            note({"note": "clicked", "control": _label_mask(label)})
        except Exception as e:
            note({"note": "click failed", "control": _label_mask(label), "why": _click_failure(e)})
            return False
        appeared: set = set()
        # Looked at against the clock. Each look used to read every control
        # one at a time, which on a real page added a second or so, so eight
        # looks waited well past four seconds. The core reads them in one
        # call now (the census after CI run 36792330947).
        until = time.monotonic() + REVEAL_WAIT_S
        while True:
            page.wait_for_timeout(500)
            appeared = _control_texts(page) - before
            if any(is_revealed_document(t, own, cut=True) for t in appeared) or \
                    time.monotonic() >= until:
                break
    finally:
        try:
            page.remove_listener("response", on_list)
        except Exception:
            pass
    try:
        expanded_after = el.get_attribute("aria-expanded")
    except Exception:
        expanded_after = None
    # A page that draws its rows again after the press folds the row away
    # with a node the press never touched. The old node still says it is
    # open, so without this the trace read like a row that revealed
    # nothing (#37).
    try:
        after = "still on the page" if el.evaluate("el => el.isConnected") else "left the page"
    except Exception:
        after = "could not be read"
    want = _type_key(title)
    note({"note": "the row's documents", "wanted_type": _type_word(title),
          "appeared": [_label_mask(t, own, cut=True) for t in sorted(appeared)[:15]],
          "look_like_documents": sum(1 for t in appeared
                                     if is_revealed_document(t, own, cut=True)),
          "of_the_wanted_type": sum(1 for t in appeared
                                    if is_revealed_document(t, own, cut=True)
                                    and _type_key(t) == want),
          "refused_by_the_guard": sum(1 for t in appeared if _refused_document(t, own, cut=True)),
          "named_as_the_list_names_it": _list_says(appeared, want, own),
          "refused_words": [_description_mask(t, cut=True) for t in sorted(appeared)
                            if _refused_document(t, own, cut=True) and _type_key(t) == want][:3],
          "expanded_before": _attr_word(expanded), "expanded_after": _attr_word(expanded_after),
          "control_after_the_press": after,
          "list_calls_after_the_press": len(list_calls)})
    # What appeared is this row's only while it can be tied to the row. A
    # list drawn again after the press, keeping its open row by its place,
    # put new nodes everywhere and opened the row above, and that row's
    # receipt was pressed and saved as this one (#37).
    #
    # RECORDED. His 0.37.1 file showed the Document Center drawing the
    # pressed row anew. The node pressed left the page, and a Renewal Notice
    # and a View Documents of the same number appeared among the page's own
    # controls, so the document is in the page and not in a frame. The page
    # held the same four dialogs and two frames every earlier file counted
    # before anything was pressed, and the press added elements to the page
    # rather than showing ones already there, so nothing says it opened a
    # dialog. What kept the document from its row was that the node held
    # here was the old one. A row whose control left the page is found again
    # by this date, and it has to be the one row on the page carrying it.
    # Every check the pressed row gets before the document is pressed is then
    # made against that row, so the list drawn again by place above is still
    # refused, since its document is not inside the row with this date, and a
    # document outside its row, in a dialog or anywhere else, is refused and
    # the trace says where it sat.
    row, row_is = el, "the row that was pressed"
    if after == "left the page":
        row, rows, unread = _row_found_again(page, iso)
        found = {"note": "the row's control left the page after its press, so its row was "
                         "looked for again by this date", "rows_with_this_date": rows}
        if rows != 1:
            found.update(_openers_read(page, iso))
        note(found)
        if row is None:
            note({"note": "no revealed document was pressed",
                  "why": ("a control on the page could not be read, so which row carries this "
                          "date is not known" if unread else
                          "no row carries this date after the press" if rows == 0 else
                          "%d rows carry this date after the press, so which one is this "
                          "document's is not known" % rows)})
            return False
        row_is = "the row found again by this date"
    elif after != "still on the page":
        note({"note": "no revealed document was pressed",
              "why": "the row's control could not be read after its press, "
                     "so nothing ties what appeared to its row"})
        return False
    doc_el, doc_name, why = _revealed_document(page, appeared, title, own)
    if doc_el is None:
        note({"note": "no revealed document was pressed", "why": why})
        return False

    def check_document() -> str:
        where: dict = {}
        why_now = _still_the_document(page, doc_el, doc_name, row, iso, where, row_is)
        if where:
            note(dict({"note": "where the document sat against " + row_is}, **where))
        return why_now

    # Whatever the page asks for once the document is pressed is the
    # document's own, and the census would keep any part of its path that is
    # not a number. What arrives is in the trace as facts instead (#37).
    return _press_unheard(page, census, trace, lambda: _catch_pdf(
        page, doc_el, doc_name, out_path, trace, dl_dir, check=check_document, own=own))


# How long a fresh Document Center may take to draw its rows. It draws none
# until its own list call has answered (#37).
ROWS_WAIT_MS = 30000
# How long the wanted row's control has to stay the same node before it is
# pressed. A page that draws its rows and then draws them again a moment
# later leaves the first press on a node that is no longer there (#37).
SETTLE_MS = 1500
# How long a pressed row may take to show its documents.
REVEAL_WAIT_S = 12


def _all_on_page(handles) -> bool:
    for h in handles:
        try:
            if not h.evaluate("el => el.isConnected"):
                return False
        except Exception:
            return False
    return True


def _fresh_list(page, want: str = "", year: Optional[int] = None,
                answers: Optional[list] = None) -> dict:
    """Load the documents page again so every row starts folded, then wait
    for the rows.

    Rows opened by an earlier document in the same run stay open, and
    pressing an open row's View Documents folds it away. A fresh page is
    the one state where one press opens exactly the row wanted (#37).

    The wait is for a control that carries a date, the wanted one when it
    is given. 0.34.2 stopped waiting at the first document control of any
    kind, and the page shows one with no date on it before its rows exist.
    A Pilot on 0.37.0 then looked for its row within three seconds of
    starting on the document, saw that one control and "no date", and gave
    up while the page's list call had not answered yet (#37).

    Without the wanted date it stops two seconds after the page's own list
    has answered and some control carries a date. Dated controls alone are
    not enough, because a control reads its date from up to six levels of
    the page around it and could find one before any row exists. It stops
    at once on a sign-in page or a page off statefarm.com, since no row is
    coming there. The time is the clock's, so reading the controls on each
    pass cannot stretch the wait past ROWS_WAIT_MS by much.

    Once the wanted date shows, the controls carrying it have to stay the
    same nodes for SETTLE_MS. A page that draws its rows and draws them
    again a moment later took the press on the first node, and the second
    drawing folded the row away (#37). rows_redrawn counts how often that
    happened. When the wanted date shows and is gone again on the next pass,
    the two second grace starts over, so the passes counted before the date
    first showed cannot end the wait while the page draws its rows again.

    `year`, when given, is the year the page's own list call asks for while
    the page loads. The page draws the rows of one period, and a document
    from an earlier year has no row until the list is asked for its year.
    So the year in the call's query is set to `year` and nothing else in it
    changes, the same change the year walk makes, and the page draws that
    year's rows itself. Nothing on the page is pressed for it, since the
    page's own Time Period menu is a control this app does not press. Only
    a GET on statefarm.com whose address carries one year is changed, the
    change ends with the wait, and the facts count the page's list calls
    that were changed and those that were not (#37).

    `answers`, when given, gets each list answer the page received, so the
    caller can read what the list calls a document. Nothing of them goes
    in the facts.

    Returns what the wait saw, as counts and yes or no, for the trace."""
    answered: list = []
    changed: list = []
    unchanged: list = []

    def on_response(res):
        try:
            url = res.url or ""
            if is_safe_url(url) and DOCS_API_RE.search(url):
                answered.append(1)
                if answers is not None:
                    try:
                        answers.append(res.json())
                    except Exception:
                        pass
        except Exception:
            pass

    def ask_for_year(route):
        # A route left unanswered holds the page's request until the page
        # closes, so a call that cannot be changed goes on as it was.
        try:
            target = _list_call_for_year(route.request.method, route.request.url, year)
        except Exception:
            target = None
        if target is not None:
            try:
                route.fallback(url=target)
                changed.append(1)
                return
            except Exception as e:
                log.info("the list call could not be asked for another year: %s", e)
        unchanged.append(1)
        try:
            route.fallback()
        except Exception:
            pass

    facts = {"waited_ms": 0, "list_answered": False, "dated_controls": 0,
             "wanted_date_seen": False, "rows_redrawn": 0}
    if year is not None:
        facts["year_asked"] = int(year)
    page.on("response", on_response)
    try:
        if year is not None:
            try:
                page.route(DOCS_API_RE, ask_for_year)
            except Exception as e:
                log.info("the list call could not be asked for %s: %s", year, e)
        try:
            page.goto(BILLING_URL, wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            log.info("reloading the documents page failed: %s", e)
            facts["reloaded"] = False
            return facts
        started = time.monotonic()
        deadline = started + ROWS_WAIT_MS / 1000.0
        settled = 0
        held: Optional[list] = None
        since = 0.0
        while True:
            page.wait_for_timeout(500)
            if looks_signed_out(page) or not is_safe_url(page.url or ""):
                facts["stopped_early"] = "a sign-in page or a page off statefarm.com"
                break
            dates = [d for d in _control_dates(page) if d != "no date"]
            facts["dated_controls"] = len(dates)
            if want and want in dates:
                facts["wanted_date_seen"] = True
                now = [h for h, _ in _controls_for(page, want)]
                if held is not None and _all_on_page(held) and len(now) == len(held):
                    if time.monotonic() - since >= SETTLE_MS / 1000.0:
                        break
                else:
                    if held is not None:
                        facts["rows_redrawn"] += 1
                    held, since = now, time.monotonic()
            else:
                if held is not None:
                    facts["rows_redrawn"] += 1
                    # The wanted date showed and is gone this pass, so the
                    # page is drawing its rows again. The grace below starts
                    # over, or passes counted before the date first showed
                    # would end the wait here with nothing held still (#37).
                    settled = 0
                held = None
                # The rows come from the list's one answer, so once it is in
                # and some carry a date the rest are there too. A short
                # grace, and then the search below says which dates it did
                # find.
                if answered and dates:
                    settled += 1
                    if settled >= 4:
                        break
            if time.monotonic() >= deadline:
                break
        facts["waited_ms"] = int((time.monotonic() - started) * 1000)
    finally:
        try:
            page.remove_listener("response", on_response)
        except Exception:
            pass
        # The page's later calls are its own again, so a page loaded after
        # this one, the next document's included, shows its own period. It is
        # taken off whenever it was asked for, since page.route can add it
        # and still raise.
        if year is not None:
            try:
                page.unroute(DOCS_API_RE, ask_for_year)
            except Exception as e:
                log.info("the change to the list call could not be removed: %s", e)
        facts["list_answered"] = bool(answered)
        if year is not None:
            facts["list_calls_changed"] = len(changed)
            facts["list_calls_unchanged"] = len(unchanged)
    dismiss_overlay(page)
    return facts


def _list_call_for_year(method: str, url: str, year: int) -> Optional[str]:
    """Where the page's own list call is sent instead, asking for `year`, or
    None when it is left as it is. Only a GET is changed, since the list is
    only ever read, and only an address that carries one year parameter and
    is still on statefarm.com once the year is set (#37)."""
    if (method or "").upper() != "GET":
        return None
    target = _with_year(url or "", year)
    return target if target is not None and is_safe_url(target) else None


def _years_to_show(iso: str) -> list:
    """The years to ask the list for, in turn, while looking for the row of
    the document dated `iso`. None is the page's own period.

    Every document found so far has been in the page's own period, so a
    document from this year looks there first and asks for its year only
    when its row is not there. One from an earlier year is where the year
    walk finds it, in the list of its own year, so that is asked first, and
    the page's own period after it in case that period reaches back past
    New Year (#37)."""
    from datetime import date as _date
    m = re.match(r"(\d{4})-\d{2}-\d{2}$", iso or "")
    if not m:
        return [None]
    year = int(m.group(1))
    return [year, None] if year < _date.today().year else [None, year]


@dataclass
class RawDoc:
    title: str
    account: str = ""
    date_text: str = ""
    href: str = ""
    text: str = ""
    row_index: int = -1
    kind: str = "doc"
    # What tells this entry of the list from another, its document id, else
    # its file address. Discovery compares this and not the address, so one
    # document whose address differs between two reads is still one (#37).
    ident: str = ""


# The date a bill control belongs to. The control's own name first, then
# the nearest enclosing row or card whose text carries a date, up to six
# levels up. _ROW_BOX_JS finds that container, the control itself when its
# own words carry a date, and _ROW_OF_JS returns its text so a repair can
# see what the row looked like. The tie between a revealed document and the
# row that was pressed (_TIE_JS) walks the same way, so the row it holds the
# document to is the one discovery read the date from (#37).
#
# A container whose every date is after tomorrow is walked past, since no
# document is dated ahead and that date is a document's "available until".
# His 0.39.1 Pilot pressed a row's View Documents, the row was drawn again
# open, and no row carried its date after that, which is what a button
# whose nearest dated container is the revealed document's own line would
# give. Only a View Documents walks past such a container, only while the
# container shows a document the row revealed, which is the opened row his
# file describes, and never out of its own row, the nearest ancestor that
# is a row, a table row or a list item. A row's date can sit in an element
# with no control of its own, a document sent by mail or a date heading, so
# stopping at another control alone let the walk take a neighbor's date,
# which a review showed saving one document under another's (#37). Inside
# its row it still never steps into a container that holds a control other
# than this one and the documents it revealed. A container it cannot get
# past is still the box, and its date is then read as none
# (_date_not_ahead), where it used to read as the day ahead.
_ROW_BOX_JS = r"""el => {
  const dateRe = /(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}|\d{1,2}\/\d{1,2}\/\d{2,4}|\d{4}-\d{2}-\d{2}/ig;
  const months = {jan: 0, feb: 1, mar: 2, apr: 3, may: 4, jun: 5, jul: 6, aug: 7,
                  sep: 8, oct: 9, nov: 10, dec: 11};
  const today = new Date();
  const limit = new Date(today.getFullYear(), today.getMonth(), today.getDate() + 2);
  // A day as a Date, or null for one that does not exist or is not named by
  // a month's own name. A two digit year is read as full_year reads it, up
  // to next year this century.
  const day = s => {
    let g, y, m, d;
    if ((g = s.match(/^(\d{4})-(\d{2})-(\d{2})$/))) {
      y = +g[1]; m = +g[2] - 1; d = +g[3];
    } else if ((g = s.match(/^(\d{1,2})\/(\d{1,2})\/(\d{2,4})$/))) {
      m = +g[1] - 1; d = +g[2]; y = +g[3];
      if (g[3].length === 2) { y += 2000; if (y > today.getFullYear() + 1) y -= 100; }
    } else if ((g = s.match(/^(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?\s+(\d{1,2}),?\s+(\d{4})$/i))) {
      m = months[g[1].slice(0, 3).toLowerCase()]; d = +g[2]; y = +g[3];
    } else {
      return null;
    }
    if (m === undefined) return null;
    const t = new Date(y, m, d);
    if (t.getFullYear() !== y || t.getMonth() !== m || t.getDate() !== d) return null;
    return t;
  };
  // A day that does not exist is not ahead, so it ends the walk as before.
  const ahead = s => { const t = day(s); return !!t && t >= limit; };
  const words = c => ((c.getAttribute('aria-label') || c.innerText || '') + '').replace(/\s+/g, ' ').trim();
  const opener = /^\s*view\s+documents?\s*\d*\s*$/i.test(words(el));
  const near = el.closest('[role=row], tr, li');
  const own = near && near.matches('[role=row]') ? near : null;
  const controls = n => [...n.querySelectorAll('a, button, [role=button], [role=link]')];
  let node = el, depth = 0, aheadOnly = null;
  const docShaped = c => /^[A-Za-z][A-Za-z0-9&\/'(). ]{1,60}?\s+-\s+\S/.test(words(c))
    && !/^\s*view\s+documents?\s*\d*\s*$/i.test(words(c));
  const revealed = n => controls(n).some(c => c !== el && c.getClientRects().length > 0 && docShaped(c));
  const holdsOthers = n => controls(n).some(c => c !== el && !aheadOnly.contains(c));
  while (node && depth < 6) {
    const days = (node.innerText || '').trim().match(dateRe) || [];
    if (days.length) {
      if (days.some(s => !ahead(s))) return node;
      if (!aheadOnly) aheadOnly = node;
      const up = node.parentElement;
      if (!up || !opener || !own || !own.contains(up) || !revealed(aheadOnly) || holdsOthers(up)) {
        return aheadOnly;
      }
    }
    node = node.parentElement; depth++;
  }
  return aheadOnly;
}"""
_ROW_OF_JS = ("el => { const box = (" + _ROW_BOX_JS + ")(el); "
              "return box ? (box.innerText || '').trim().slice(0, 300) : ''; }")
# Whether the box a control reads its date from lies inside the control's
# own row. A day ahead is passed over only there. Outside it the box is a
# heading or a list that holds other rows, and a date is read there as
# v0.39.1 read it (review of 1662ac2).
_IN_ROW_JS = ("el => { const box = (" + _ROW_BOX_JS + ")(el); "
              "const own = el.closest('[role=row], tr, li'); "
              "return !!box && !!own && own.matches('[role=row]') && own.contains(box); }")


def _docs_from_api(body: dict) -> List[dict]:
    """The documents in one customerMetadata answer, as {date, title,
    kind, hint, url}. The description can carry a policy or vehicle, so
    the title is the type and the category, and the description only
    rides along with its digits masked."""
    out = []
    undated = future = 0
    data = (body or {}).get("data") or {}
    for e in data.get("attributes") or []:
        if not isinstance(e, dict):
            continue
        # creationDate is when the document was made. availableDate is how
        # long it stays on the site, which a tester spotted as the source of
        # a document filed under 2028, from the line under its title that
        # says how long it stays online, two years on. The page's own
        # controls carried 2026 dates for the same documents (#37).
        #
        # availableDate used to stand in when creationDate was missing. That
        # is the 2028 date again, so a document without its own date is left
        # out and counted rather than filed under the wrong one.
        iso = parse_date(str(e.get("creationDate") or ""))
        if not iso:
            undated += 1
            continue
        if is_future(iso):
            future += 1
            continue
        kind = str(e.get("type") or "").strip()
        cat = str(e.get("category") or "").strip()
        desc = redact(str(e.get("description") or ""))[:60]
        title = " - ".join(x for x in (kind or "Document", cat) if x)
        out.append({"date": iso, "title": title, "kind": kind, "category": cat, "desc": desc,
                    "hint": str(e.get("documentId") or ""), "url": str(e.get("filePathUrl") or "")})
    if undated or future:
        log.info("left out %d document(s) with no creation date and %d dated in the future",
                 undated, future)
    return out


def is_future(iso: str) -> bool:
    """True for a date after tomorrow. No document is issued in the future,
    so a date like that was read from the wrong field. Tomorrow is allowed
    because the site's clock and this machine's can sit a day apart (#37)."""
    from datetime import date as _date, timedelta as _td
    try:
        return _date.fromisoformat(iso) > _date.today() + _td(days=1)
    except (TypeError, ValueError):
        return False


_YEAR_ONLY_RE = re.compile(r"^\d{4}$")


def title_detail(title: str) -> str:
    """What a document's title says it is for, the part after the dash, or "".

    RECORDED (#37). The Document Center titles a document by its kind, a
    dash and the policy it belongs to, "Renewal Notice - Auto", "Renewal
    Notice - Homeowners", or the vehicle on an auto policy, "Renewal
    Notice - <year make model>". A receipt repeats its kind after the dash,
    "Payment Receipt - Payment Receipt", which says nothing more, and a year
    alone says nothing the date does not."""
    head, sep, tail = (title or "").partition(" - ")
    tail = re.sub(r"\s+", " ", tail).strip()
    if not sep or not tail:
        return ""
    if tail.lower() == re.sub(r"\s+", " ", head).strip().lower():
        return ""
    if _YEAR_ONLY_RE.match(tail):
        return ""
    return tail


# Headers a fetch from inside the page may not set, or that the browser
# adds on its own. Everything else the page's own list call sent is sent
# again with each year, since that call answered and the year walk, which
# sent cookies and an accept header alone, was refused 401 for every year,
# the current one included (#37, his 0.38.0 Discover).
_UNSENDABLE_HEADER_RE = re.compile(
    r"^(cookie2?|host|connection|keep-alive|content-length|content-type|origin|referer|"
    r"user-agent|accept-encoding|accept-charset|date|dnt|expect|te|trailer|"
    r"transfer-encoding|upgrade|via|priority|sec-.*|proxy-.*|:.*)$", re.I)


def _resendable_headers(headers) -> dict:
    """The headers a page set on a request that a fetch from the same page
    may set again, never a cookie, which the browser adds itself."""
    return {k: v for k, v in (headers or {}).items()
            if k and not _UNSENDABLE_HEADER_RE.match(k)}


def _capture_docs(page) -> Tuple[list, list, list]:
    """Open the Document Center while catching the customerMetadata answer,
    the address it was asked at and the headers it was asked with, so
    discovery can ask for other years the same way."""
    bodies: list = []
    urls: list = []
    heads: list = []

    def on_response(res):
        try:
            url = res.url or ""
            if is_safe_url(url) and DOCS_API_RE.search(url):
                try:
                    sent = _resendable_headers(res.request.all_headers())
                except Exception:
                    sent = {}
                body = res.json()
                urls.append(url)
                bodies.append(body)
                heads.append(sent)
        except Exception:
            pass
    page.on("response", on_response)
    try:
        page.goto(BILLING_CANDIDATES[0], wait_until="domcontentloaded", timeout=60000)
        for _ in range(40):
            page.wait_for_timeout(500)
            if bodies:
                break
        page.wait_for_timeout(1500)
    except Exception as e:
        log.info("goto document center failed: %s", e)
    finally:
        try:
            page.remove_listener("response", on_response)
        except Exception:
            pass
    dismiss_overlay(page)
    return bodies, urls, heads


# The answer's status and content type come back with it, so a year that
# was refused can be told from a year with nothing in it.
_FETCH_JSON = r"""async (arg) => {
    const [u, h] = Array.isArray(arg) ? arg : [arg, {}];
    const headers = Object.assign({accept: 'application/json'}, h || {});
    const r = await fetch(u, {credentials: 'include', headers});
    const out = {status: r.status, type: r.headers.get('content-type') || ''};
    if (!r.ok) return out;
    try { out.body = await r.json(); } catch (e) { out.unreadable = true; }
    return out;
}"""


def _status_of(value) -> int:
    """An HTTP status as a number, or 0 when it is not one."""
    return value if isinstance(value, int) and 100 <= value <= 599 else 0


def _listed(body) -> int:
    """How many entries a customerMetadata answer lists, before any is
    left out for a missing or future date."""
    data = body.get("data") if isinstance(body, dict) else None
    entries = data.get("attributes") if isinstance(data, dict) else None
    return len(entries) if isinstance(entries, list) else 0


# Every word and phrase the list read and the year walk put in their facts.
# What prints those facts shows one of these or a fixed phrase in its place,
# so a line a tester pastes is built from this list and nothing else (#37).
FACT_WORDS = frozenset({
    # a content type as the core's kind_of names it, or no answer at all
    "json", "pdf", "html", "xml", "text", "image", "stream", "other", "nothing",
    "not readable as json",
    # why a fetch failed, from _fetch_failure
    "the address is off statefarm.com", "the browser could not fetch it", "some other error",
    # why the year walk stopped
    "asked every year back to the limit", "the list's address carries no year to change",
    "the changed address is not on statefarm.com", "two years running with nothing in them",
    # what the year in the page's own list address held, from _year_word
    "not there", "there more than once", "left empty", "a four digit year",
    "a number that is not a four digit year", "some other value",
})


# The year in the list's address, as the page's own call carries it, a query
# parameter named year. Its value is whatever the page put there, so the
# whole value is matched and nothing after it.
_YEAR_PARAM_RE = re.compile(r"([?&]year=)([^&#]*)")


def _year_values(url: str) -> list:
    """The values of every year parameter in `url`'s query, as they stand."""
    query = (url or "").split("#", 1)[0]
    return [m.group(2) for m in _YEAR_PARAM_RE.finditer(query)]


def _with_year(url: str, year: int) -> Optional[str]:
    """`url` with its year parameter set to `year` and nothing else in it
    changed, or None when it carries no year parameter or more than one.

    The walk used to change four digits after "year=" and nothing else. The
    page's own call carries something other than four digits there (his
    0.37.1 file), so the walk changed nothing and stopped before its first
    year. Whatever the value is, it is replaced whole now (#37)."""
    head, mark, fragment = (url or "").partition("#")
    if len(_year_values(head)) != 1:
        return None
    return (_YEAR_PARAM_RE.sub(lambda m: m.group(1) + "%04d" % int(year), head, count=1)
            + mark + fragment)


def _four_digit_year(url: str) -> int:
    """The year the list's address asks for, when its one year parameter
    holds four digits, else -1."""
    values = _year_values(url)
    return int(values[0]) if len(values) == 1 and re.fullmatch(r"\d{4}", values[0]) else -1


def _year_word(url: str) -> str:
    """What the year in the list's address held, as a fixed phrase from
    FACT_WORDS and none of the value. The census kept only the parameter's
    name and the recording masked its value, so this is the one way a
    tester's file can say which kind of value the page sends (#37)."""
    values = _year_values(url)
    if not values:
        return "not there"
    if len(values) > 1:
        return "there more than once"
    value = values[0]
    if not value:
        return "left empty"
    if re.fullmatch(r"\d{4}", value):
        return "a four digit year"
    if re.fullmatch(r"-?\d{1,12}", value):
        return "a number that is not a four digit year"
    return "some other value"


def _years_from(page, url: str, first_year: int, facts: Optional[dict] = None,
                headers: Optional[dict] = None) -> List[dict]:
    """The same customerMetadata call for each earlier year, made from
    inside the page. The year is the only thing changed in the address.

    Discovery has found the current year only in every round since 0.33.0,
    and the census in his failure file shows no answer for any earlier
    year, while this walk wrote its failures to the log and nowhere else
    (#37). `facts` gets each year's status, a word for its content type
    and how many documents it listed and kept, or a fixed phrase for why
    it failed, and why the walk stopped.

    `first_year` is the year the page's own call asked for, or -1 when its
    address did not hold one. Then this year is asked for too, since the
    page's own period may not be the whole of it, and a document read
    twice is read once by collect_download_docs."""
    from datetime import date as _date
    out = []
    asked: list = []
    stopped = "asked every year back to the limit"
    empty = 0
    this_year = _date.today().year
    for year in range(this_year, this_year - YEARS_BACK - 1, -1):
        if year == first_year:
            continue
        target = _with_year(url, year)
        if target is None:
            stopped = "the list's address carries no year to change"
            break
        if not is_safe_url(target):
            stopped = "the changed address is not on statefarm.com"
            break
        entry: dict = {"year": year}
        asked.append(entry)
        try:
            got_raw = page.evaluate(_FETCH_JSON, [target, headers] if headers else target)
        except Exception as e:
            log.info("year %d: %s", year, e)
            entry["failed"] = _fetch_failure(e)
            continue
        got_raw = got_raw if isinstance(got_raw, dict) else {}
        body = got_raw.get("body") if isinstance(got_raw.get("body"), dict) else None
        entry["status"] = _status_of(got_raw.get("status"))
        entry["type"] = _kind_of(str(got_raw.get("type") or ""))
        if got_raw.get("unreadable"):
            entry["answer"] = "not readable as json"
        got = _docs_from_api(body) if body else []
        entry["listed"] = _listed(body)
        entry["kept"] = len(got)
        out.extend(got)
        # The tester's menu only offers back to 2023 and State Farm only
        # keeps two years, so asking for seven is seven calls for nothing.
        # Two empty years in a row is the end of what is kept (#37).
        empty = 0 if got else empty + 1
        if empty >= 2:
            log.info("two years running with nothing in them, so that is the end of the history")
            stopped = "two years running with nothing in them"
            break
    if facts is not None:
        facts["years"] = asked
        facts["stopped"] = stopped
    return out


def _address_kind(url: str) -> str:
    """Which count a document's file address from the list goes under. A
    path is the one kind download_bill asks for."""
    if not url:
        return "with_no_file_address"
    return "with_a_file_address" if "/" in url else "with_a_file_address_that_is_not_a_path"


def collect_download_docs(page, facts: Optional[dict] = None) -> List[RawDoc]:
    """Every document the Document Center's API lists, this year as the
    page loads it and each earlier year by the same call, else the rows.

    `facts` gets counts and fixed words about how the list was read, for
    download-attempt.json (#37)."""
    docs: List[RawDoc] = []
    seen = set()
    bodies, urls, heads = _capture_docs(page)
    found = []
    for body in bodies:
        found.extend(_docs_from_api(body))
    if facts is not None:
        facts["page_list_answers"] = len(bodies)
        facts["page_list_listed"] = sum(_listed(b) for b in bodies)
        facts["page_list_kept"] = len(found)
    if urls:
        # RECORDED. The address checked is the page's own first list call,
        # which carries a year parameter whose value was not four digits in
        # his 0.37.1 file. Only four digits used to count as a year there,
        # so the walk stopped before its first year and said the address
        # carried none. What the value held is in the facts as a fixed
        # phrase, since the census kept only the parameter's name (#37).
        first = _four_digit_year(urls[0])
        sent = heads[0] if heads else {}
        if facts is not None:
            facts["year_in_address"] = first != -1
            facts["year_value"] = _year_word(urls[0])
            # How many headers the page's own call carried and whether one
            # was an authorization, never their names or values (#37).
            facts["page_call_headers"] = len(sent)
            facts["page_call_authorization"] = any(k.lower() == "authorization" for k in sent)
        found.extend(_years_from(page, urls[0], first, facts, headers=sent))
    # What the list gave as each document's file address, counted. The one
    # document tried in his 0.37.1 file had "an id and no address", which
    # an empty filePathUrl and one with no slash in it both give, so these
    # say which it was without saying what it held (#37).
    addresses = {"with_a_file_address": 0, "with_a_file_address_that_is_not_a_path": 0,
                 "with_no_file_address": 0}
    for d in found:
        # One entry is one document, told from another by its document id,
        # else by its file address when the list gave no id. Two entries
        # with one date and title and no id used to fold into the first
        # here, so discovery never saw that they were two. Folding on the
        # address as well as the id split one document in two whenever its
        # address differed between two reads, and a record split that way
        # is refused for good. The same entry read twice is read once (#37).
        ident = d["hint"] or d["url"]
        key = (d["date"], d["title"], ident)
        if key in seen:
            continue
        seen.add(key)
        addresses[_address_kind(d["url"])] += 1
        insurance = bool(re.search(r"id\s*card|declaration|policy", d["kind"] + " " + d["title"], re.I))
        docs.append(RawDoc(title=d["title"], account=d["category"], date_text=d["date"],
                           href=d["url"] or d["hint"], text=f"State Farm {d['title']} {d['desc']}",
                           kind="insurance" if insurance else "statement", ident=ident))
    if docs:
        if facts is not None:
            facts.update(addresses)
        return docs
    reveal_documents(page)
    expand_all(page)
    scroll_full_page(page)
    ctrls = _bill_controls(page)
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
        iso = _date_not_ahead(name)
        if not iso:
            got = _read_control(el)
            row_text = got["row"] if got is not None else ""
            iso = _date_of(got) if got is not None else None
        if not iso or iso in seen:
            continue
        seen.add(iso)
        disp = _human_date(iso)
        tax = bool(re.search(r"1099|1098|5498|tax", name + " " + row_text, re.I))
        kind_title = "Tax Document" if tax else "Account Statement"
        docs.append(RawDoc(title=f"{kind_title} - {disp}", date_text=iso,
                           href=href if PDF_HREF_RE.search(href or "") else "",
                           text=f"State Farm {kind_title} {disp}", row_index=i,
                           kind="tax" if tax else "statement"))
    return docs


# A control's name, the text around it that carries a date, whether it is
# still on the page and its own link, read in one call so they describe one
# moment.
_NAME_AND_ROW_JS = ("el => [(el.getAttribute('aria-label') || el.innerText || '').trim(), ("
                    + _ROW_OF_JS + ")(el), el.isConnected, el.getAttribute('href') || '', ("
                    + _IN_ROW_JS + ")(el)]")

# The pressed row's control, the document it revealed and every control that
# carries the wanted date, read in one call so what it says holds for one
# moment. `openers` says which of the dated controls is another row's View
# Documents. The control's name and its row's text are read as
# _NAME_AND_ROW_JS reads them, and the row is the container _ROW_BOX_JS
# finds. Returns whether the control is on the page, its name, its row's
# text, whether the document is on the page, the document's own words,
# whether the row holds the document, how many dated controls sit outside
# the row besides the control itself and the document, how many other View
# Documents carrying the date sit inside it, and whether the document sits
# in the row's parent, in the element right after the row or in a dialog,
# for the trace when the row does not hold it (#37). A dialog is asked about
# because every failure file counts four on the page, hidden ones included,
# so a dialog filled in by the press would not change the count. The
# document is left out of the controls outside the row because, outside it,
# it reads its date from the page around it like any control, and was then
# refused as another control before the trace could say where it sat. It is
# still refused, by the check that the row holds it.
_TIE_JS = ("(row, [doc, dated, openers]) => { const box = (" + _ROW_BOX_JS + ")(row); "
           "const inside = h => !!box && box.contains(h); return ["
           "row.isConnected, (row.getAttribute('aria-label') || row.innerText || '').trim(), "
           "box ? (box.innerText || '').trim().slice(0, 300) : '', "
           "doc.isConnected, doc.innerText || '', "
           "!!box && box !== doc && box.contains(doc), "
           "dated.filter(h => h !== row && h !== doc && !inside(h)).length, "
           "dated.filter((h, i) => h !== row && inside(h) && openers[i]).length, "
           "!!box && !!box.parentElement && box.parentElement.contains(doc), "
           "!!box && !!box.nextElementSibling && box.nextElementSibling.contains(doc), "
           "!!doc.closest('dialog, [role=dialog], [aria-modal=true]'), "
           "box ? [...box.querySelectorAll('a, button, [role=button], [role=link]')].filter(c => "
           "c !== row && c !== doc && c.getClientRects().length > 0 && (c.hasAttribute('aria-expanded') || "
           "/^\\s*(view|hide|show|close)\\s+documents?\\s*\\d*\\s*$/i.test("
           "((c.getAttribute('aria-label') || c.innerText || '') + '').replace(/\\s+/g, ' ')))).length : 0, "
           "(" + _IN_ROW_JS + ")(row)]; }")


def _read_control(el) -> Optional[dict]:
    """A control's name, the text that dates it, whether it is on the page
    and its link, from one read of the node itself, or None."""
    try:
        got = el.evaluate(_NAME_AND_ROW_JS)
    except Exception:
        return None
    if not isinstance(got, list) or len(got) != 5:
        return None
    name, row, connected, href, in_row = got
    return {"name": str(name or "").strip(), "row": str(row or ""),
            "connected": bool(connected), "href": str(href or ""), "in_row": in_row is True}


def _date_of(read: dict) -> Optional[str]:
    """The date a control belongs to, from its own name first and then from
    the text around it, the way discovery reads it. A day after tomorrow is
    passed over only in text from inside the control's own row. Anywhere
    else the text holds other rows, and it is read as v0.39.1 read it."""
    row_date = _date_not_ahead if read.get("in_row") else parse_date
    return _date_not_ahead(read["name"]) or row_date(read["row"])


def _controls_for(page, iso: str) -> list:
    """Every control on the page for the document dated `iso`, matched the
    same way discovery found it, as (node, name) pairs.

    All of them and not only the first. Two rows can carry one date, and
    pressing the first opened the other document's row, whose document of
    the same type was then saved under this one's name (#37).

    Each is the node itself, taken before its name and date are read and
    read through that same node. A locator for "the nth control" is looked
    up again every time it is used, so once a row was drawn above the
    wanted one the name read belonged to one row and the link fetched to
    the next (#37).

    A control that could not be read is counted in `unread`, since it may
    carry the date. It was left out, so of two rows carrying one date the
    other one would be pressed as the only one."""
    out = _Found()
    try:
        handles = _bill_controls(page).element_handles()
    except Exception:
        out.unread = 1
        return out
    for h in handles:
        got = _read_control(h)
        if got is None:
            out.unread += 1
        elif _date_of(got) == iso:
            out.append((h, got["name"]))
            continue
        try:
            h.dispose()
        except Exception:
            pass
    return out


def _recheck(page, el, iso: str, label: str) -> Tuple[str, str, str]:
    """(why, link, row). Why the control is no longer the one that was
    checked, as a fixed phrase, or "" when it still is, and its own link and
    its row's words as that same read found them.

    The control is found, then every control on the page is read so that
    what the press reveals can be told apart, and only then is it pressed
    or its link fetched. A page still settling can move a control or reuse
    it for another row in between. So right before, its name and its date
    are read again, and it has to be the only control carrying this date
    still (#37)."""
    got = _read_control(el)
    if got is None:
        return "it could not be read again", "", ""
    if not got["connected"]:
        return "it left the page", "", ""
    if got["name"] != label:
        return "its name changed", "", ""
    if _date_of(got) != iso:
        return "it no longer carries this date", "", ""
    dated = _controls_for(page, iso)
    if dated.unread:
        return "a control on the page could not be read", "", ""
    n = len(dated)
    if n != 1:
        return "%d controls carry this date now" % n, "", ""
    return "", got["href"], got["row"]


def _still_the_one(page, el, iso: str, label: str) -> str:
    """Why the control about to be pressed is no longer the one that was
    checked, as a fixed phrase, or "" when it still is."""
    return _recheck(page, el, iso, label)[0]


def _control_dates(page) -> list:
    """The dates the page's own controls carry, for the trace when the one
    that was wanted is not among them. Dates and nothing else (#37)."""
    out = []
    try:
        ctrls = _bill_controls(page)
        for i in range(min(ctrls.count(), 30)):
            el = ctrls.nth(i)
            try:
                name = (el.get_attribute("aria-label") or el.inner_text(timeout=500) or "").strip()
            except Exception:
                name = ""
            # Read the way _controls_for reads it, so the wait and the search
            # never disagree about which date a control carries.
            found = _date_not_ahead(name)
            if not found:
                got = _read_control(el)
                found = _date_of(got) if got is not None else None
            out.append(found or "no date")
    except Exception as e:
        log.info("control dates: %s", e)
    return out[:30]


# A download still being written was touched this recently. One left behind
# by a browser that closed mid-download is older, and is not waited on.
UNFINISHED_RECENT_S = 600


def _unfinished_downloads(dl_dir) -> int:
    """How many downloads in the folder are still being written, counting
    only those written to lately."""
    if not dl_dir:
        return 0
    import os
    try:
        names = os.listdir(dl_dir)
    except OSError:
        return 0
    now = time.time()
    n = 0
    for name in names:
        if not name.lower().endswith(_UNFINISHED):
            continue
        try:
            if now - os.path.getmtime(os.path.join(str(dl_dir), name)) <= UNFINISHED_RECENT_S:
                n += 1
        except OSError:
            continue
    return n


def _fetch_pdf(page, href: str, zip_ok: bool = False) -> Optional[bytes]:
    """A PDF link fetched from inside the signed-in page, cookies and all.
    The fetching is the core's, the hosts are this app's."""
    return _core_fetch_pdf(page, href, is_safe_url, zip_ok=zip_ok)


def _take_same_tab(page, start_url: str, out_path: Path, trace) -> bool:
    """A PDF the click opened in this very tab. The core does the reading,
    this app's guard decides which addresses it may read.

    The core's own trace entry carries the address the tab moved to, which
    here would be a document's own address, so it gets no trace and this
    writes the entry from facts instead (#37)."""
    url = page.url or ""
    if trace is not None and url and url != start_url and is_safe_url(url):
        kind = ""
        try:
            kind = page.evaluate("() => document.contentType || ''") or ""
        except Exception:
            pass
        trace.append({"note": "the tab moved", "address": url_mask(url, start_url),
                      "content_type": _kind_of(str(kind))})
    return _core_take_same_tab(page, start_url, out_path, None, is_safe_url)


_SECOND_STEP_RE = re.compile(
    r"^\s*(download|download\s+(pdf|now|file|statement|document)|save|save\s+(as\s+)?pdf|"
    r"(regular|standard|full|detailed)\s+pdf|pdf|view\s*/\s*print\s+pdf|print|open\s+pdf)\s*$", re.I)


def _second_step(page, appeared: set):
    """A control the click revealed whose text says it finishes a download,
    once it has passed the guard, or None. The choosing is the core's, the
    words this provider uses and the guard are this app's."""
    return _core_second_step(page, appeared, _SECOND_STEP_RE, is_safe_control)


def _catch_pdf(page, el, label: str, out_path: Path, trace: Optional[list] = None,
               dl_dir=None, check=None, own=()) -> bool:
    """Click `el` and save whatever PDF the site produces, a file landing
    in `dl_dir`, a download event, a PDF response, a new tab, this tab
    moving to the document, or a second control the click revealed.
    `trace` collects what happened, the click's own outcome included.
    `check`, when given, says right before the click why `el` is no longer
    the control that was checked, and then nothing is clicked. `own` is
    what the list calls the document, for the trace's name of `el`."""
    ctx = page.context
    got: dict = {}
    downloads: list = []
    # Answers to a request this press made, from its tab or one it opened,
    # that called themselves a PDF and read empty. Asked for once more only
    # when nothing else brings the document (capture.ask_again).
    empty_answers: list = []
    made_here = _RequestsSince(page, ctx.pages)
    start_url = page.url or ""
    # Taken before the listener starts, so it can tell a tab this press
    # opened from one that was already open.
    before = set(ctx.pages)

    def on_download(dl):
        downloads.append(dl)

    def on_response(res):
        try:
            url = res.url or ""
            if not is_safe_url(url):
                return
            ct = (res.headers.get("content-type") or "").lower()
            # Pressing a revealed document is what first reaches these, and
            # their addresses are the document's own, so facts only (#37).
            if trace is not None and ("json" in ct or "pdf" in ct or "octet" in ct or "zip" in ct):
                trace.append({"status": _status_of(res.status), "type": _kind_of(ct),
                              "address": url_mask(url, start_url)})
            if got:
                return
            # Only a PDF on this tab or on a tab this press opened, and only
            # a whole answer. The listener hears the whole browser, and a
            # State Farm PDF loading in a tab that was already open was
            # saved under this document's name (final review of #37). An
            # answer whose tab cannot be named is not taken either.
            try:
                owner = res.frame.page
            except Exception:
                owner = None
            if owner is None or (owner is not page and owner in before):
                return
            if res.status != 200:
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
    seen = _snapshot(dl_dir)
    # A PDF that lands in the folder during this press is taken as this
    # press's own. One that an earlier press started and that finishes now
    # would be taken the same way and saved under this document's name, so
    # while one is still being written the folder is not read at all.
    unfinished = _unfinished_downloads(dl_dir)
    if unfinished and trace is not None:
        trace.append({"note": "a download from an earlier press had not finished, "
                              "so the download folder was not read for this press",
                      "unfinished": unfinished})
    controls_before = _control_texts(page)

    def landed() -> bool:
        # Pointed at a folder, the browser can save the only copy there and
        # leave the event's own file empty, so that file is taken rather than
        # the document asked for a second time (capture.take_download).
        # Not while an earlier press's download is still arriving, when
        # the folder is not read at all.
        if downloads and _take_download(downloads[0], None if unfinished else dl_dir,
                                        seen, out_path, zip_ok=True):
            return True
        if got.get("body"):
            out_path.write_bytes(got["body"])
            return True
        if got.get("refetch"):
            try:
                resp = page.context.request.get(got.pop("refetch"), timeout=60000)
                body = resp.body() if resp.ok else b""
                if _is_document(body, zip_ok=True):
                    out_path.write_bytes(body)
                    return True
            except Exception:
                pass
        if unfinished:
            return False
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
        why = check() if check is not None else ""
        if why:
            if trace is not None:
                trace.append({"note": "the control changed before it was pressed, so nothing was pressed",
                              "why": why})
            return False
        try:
            el.click(timeout=8000)
            if trace is not None:
                trace.append({"note": "clicked", "control": _label_mask(label, own)})
        except Exception as e:
            if trace is not None:
                trace.append({"note": "click failed", "control": _label_mask(label, own),
                              "why": _click_failure(e)})
            # A press can wait eight seconds before it fails, and the page
            # can move in that time, so the control is checked again before
            # it is pressed through the page instead (#37).
            why = check() if check is not None else ""
            if why:
                if trace is not None:
                    trace.append({"note": "the control changed while the press waited, "
                                          "so it was not pressed through the page",
                                  "why": why})
                return False
            try:
                el.evaluate("el => el.click()")
                if trace is not None:
                    trace.append({"note": "clicked through the DOM instead",
                                  "control": _label_mask(label, own)})
            except Exception as e2:
                if trace is not None:
                    trace.append({"note": "DOM click failed too", "why": _click_failure(e2)})
        if wait_for_pdf(10):
            return True
        if _take_same_tab(page, start_url, out_path, trace):
            return True
        if _take_new_tab(page, [p for p in ctx.pages if p not in before], out_path):
            return True
        appeared = _control_texts(page) - controls_before
        if trace is not None:
            trace.append({"note": "after the click", "address": url_mask(page.url or "", start_url),
                          "appeared": [_label_mask(t) for t in sorted(appeared)[:15]],
                          "new_tabs": len([p for p in ctx.pages if p not in before]),
                          "tabs_opened": _describe_tabs([p for p in ctx.pages if p not in before])})
        step, step_label = _second_step(page, appeared)
        if step is not None:
            try:
                step.click(timeout=8000)
                if trace is not None:
                    trace.append({"note": "second step clicked", "control": _label_mask(step_label)})
            except Exception as e:
                if trace is not None:
                    trace.append({"note": "second step click failed", "control": _label_mask(step_label),
                                  "why": _click_failure(e)})
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


def _describe_tabs(pages) -> list:
    """What each tab a click opened turned out to be, for the trace. The
    recording showed a document opening in a new tab (#37), and when that
    tab gives no PDF the next repair needs to know whether it was a viewer
    page, a blob or somewhere off State Farm. Facts about its address from
    url_mask and a word for its content type, nothing from the page and
    no part of the address that could be somebody's."""
    out = []
    for p in pages[:3]:
        try:
            url = p.url or ""
        except Exception:
            url = ""
        kind = ""
        try:
            kind = p.evaluate("() => document.contentType || ''") or ""
        except Exception:
            pass
        out.append({"address": url_mask(url),
                    "on_statefarm": bool(is_safe_url(url)), "content_type": _kind_of(str(kind))})
    return out


# The hosts and first path segments a trace may name, from the requests
# State Farm's own pages made in the testers' files (#37). They are the
# same for every customer. Any other host or segment is a fixed word.
_KNOWN_HOSTS = {
    "edocuments.statefarm.com", "my.statefarm.com", "www.statefarm.com",
    "financials.statefarm.com", "get-id-card.statefarm.com",
    "documentcenterui-prod-custdocmgmtweb.apps.gdrosa.redk8s.statefarm.com",
    "documentcenterproxyv1-prod-custdocmgmtweb.apps.gdrosa.redk8s.statefarm.com",
}
_KNOWN_ROOTS = {"DocumentCenterProxyV1", "DocumentCenterUI", "DocumentInformationUI"}


def url_mask(url: str, page_url: str = "") -> dict:
    """What a trace may say about an address, as facts from a list.

    A document's address, a file address from the list and the tab a
    document opens in are made for one customer, and redact() keeps a path
    segment that holds a name (#37). So no part of an address leaves except
    a host and a first path segment that are State Farm's own, a count of
    segments, and yes or no for a query, a .pdf ending and the page's host.
    Named a mask so the repo-wide check on trace entries knows it for a
    cleaner, and stricter than one."""
    from urllib.parse import urlsplit
    url = url or ""
    if not url:
        return {"host": "none"}
    if url.startswith("blob:"):
        return {"host": "blob", "on_statefarm": bool(is_safe_url(url[5:]))}
    try:
        parts = urlsplit(url)
        scheme = (parts.scheme or "").lower()
        host = (parts.hostname or "").lower()
        segs = [p for p in parts.path.split("/") if p]
        has_query = bool(parts.query)
        page_host = (urlsplit(page_url).hostname or "").lower() if page_url else ""
    except ValueError:
        return {"host": "unreadable"}
    if host in _KNOWN_HOSTS:
        host_word = host
    elif is_safe_url(url):
        host_word = "another statefarm.com host"
    else:
        host_word = "off statefarm.com"
    out = {"host": host_word,
           "starts_with": (segs[0] if segs[0] in _KNOWN_ROOTS else "other") if segs else "nothing",
           "segments": len(segs),
           "ends_in_pdf": bool(segs) and segs[-1].lower().endswith(".pdf"),
           "has_query": has_query}
    # Only an https address is ever asked for, so one that is not says so,
    # rather than reading like an address on a State Farm host that was.
    if scheme != "https":
        out["scheme"] = scheme if scheme == "http" else ("none" if not scheme else "other")
    if page_url:
        out["same_host_as_page"] = bool(host) and host == page_host
    return out


@contextmanager
def _unheard(page, census):
    """The run's request census stops listening for the length of the block.

    The census writes each request's path into the failure file with only
    number-shaped segments masked, and a file address from the list can
    hold a name, and so can whatever the page asks for once a document is
    pressed, in this tab or by moving this tab to the document. The census
    listens on the work tab only, so a tab the press opens is never heard.
    So it is paused for the file address fetch, for the control's own link
    and for every press of a document, and what arrives then is in the
    trace as facts instead. A short pause before listening again lets the
    last answer's event arrive while nobody is listening. Requests outside
    these blocks, the reload and the row's View Documents among them, are
    still heard (#37).

    Only a census that is listening is paused and started again. One that
    was not listening is left alone, since starting it at the end of the
    block would have it hear what nobody asked it to.

    Whether it is listening is read off the core's Requests, which keeps
    it in `_started`. If that ever stops being there, the census is stopped
    and not started again, which hears nothing it should not and never
    starts one that was not listening. The app's tests read the core's
    attribute, so a rename there fails here first (#37)."""
    paused = False
    if census is not None:
        listening = getattr(census, "_started", None)
        if listening is None:
            log.info("cannot tell whether the request census is listening, so it is stopped for good")
            try:
                census.stop()
            except Exception:
                pass
        elif listening:
            try:
                census.stop()
                paused = True
            except Exception:
                pass
    try:
        yield
    finally:
        if paused:
            try:
                page.wait_for_timeout(300)
            except Exception:
                pass
            try:
                census.start()
            except Exception:
                pass


def _back_to_the_list(page, start_url: str, trace: Optional[list]) -> None:
    """After a press that left the tab somewhere else, load the documents
    page again.

    A press can move this tab to the document's own page, a viewer that is
    not a PDF, and the core leaves it there when no PDF comes. The census
    listens again as soon as the press is over, and it would then hear what
    that page asks for, with any name in its path kept (#37). So the tab
    leaves the document first, and if even that fails it goes to a blank
    page, which asks for nothing."""
    url = page.url or ""
    if not url or url == start_url:
        return
    if trace is not None:
        trace.append({"note": "the press left this tab at another address, so it went back to "
                              "the documents page before the census listened again",
                      "address": url_mask(url, start_url)})
    try:
        page.goto(BILLING_URL, wait_until="domcontentloaded", timeout=60000)
        return
    except Exception as e:
        log.info("going back to the documents page failed: %s", e)
    try:
        page.goto("about:blank", timeout=15000)
    except Exception:
        pass


def _press_unheard(page, census, trace: Optional[list], press) -> bool:
    """Run `press` with the census not listening, and leave a page the press
    moved to before it listens again, whether or not a PDF came."""
    with _unheard(page, census):
        start_url = page.url or ""
        try:
            return press()
        finally:
            _back_to_the_list(page, start_url, trace)


def _answer_kind(data: bytes) -> str:
    """What an answer was, as one word and none of its content."""
    if not data:
        return "nothing"
    head = data.lstrip()[:1]
    if head == b"<":
        return "html"
    if head in (b"{", b"["):
        return "json"
    return "other"


def _fetch_failure(e: Exception) -> str:
    """Why an in-page fetch failed, as one of a few fixed phrases. The
    error's own text can carry the address, so it never goes in a trace."""
    msg = str(e)
    if "Refusing an off-host" in msg:
        return "the address is off statefarm.com"
    if "Failed to fetch" in msg:
        return "the browser could not fetch it"
    return "some other error"


_ID_SHAPED_RE = re.compile(r"^[A-Za-z0-9_:-]{1,120}$")
_FILE_NAME_RE = re.compile(r"\.[A-Za-z]{2,4}$")


def _hint_word(hint: str) -> str:
    """What the list gave for a document that is not an address with a
    slash in it, as a fixed phrase and none of the value.

    The download is handed the file address, else the document id, and
    anything without a slash used to read as "an id" whatever it was. A
    path written with backslashes or a bare file name is not an id, and
    the next repair needs to know which it was (#37)."""
    hint = hint or ""
    if not hint:
        return "neither an id nor an address"
    if "\\" in hint:
        return "a path written with backslashes, which this app does not ask for"
    if _FILE_NAME_RE.search(hint):
        return "a file name with no path, which this app does not ask for"
    if _ID_SHAPED_RE.match(hint):
        return "an id and no address"
    return "a value that is neither an id nor an address"


def download_bill(page, dl_dir, iso_date: str, out_path, title: str = "",
                  trace: Optional[list] = None, hint: str = "", census=None,
                  shared: bool = False, twins: int = 0) -> bool:
    """Save the document dated `iso_date`. A PDF link on the row is fetched
    from inside the page. Otherwise the row's own control is clicked, once
    it has passed the guard, and whichever the site produces is caught, a
    download event or a PDF response, in this tab or one it opens.

    `dl_dir` is where the attached browser saves a download, watched
    after every click. `census` is the run's request census, which is not
    listening while the file address is fetched or a document is pressed.
    `shared` says two documents in the list share this one's date, type
    and category, so this one record stands for both of them. `twins` is
    how many other documents in the list have this one's date and type in
    another category, which the page's rows cannot tell apart from it.

    When it is not certain which row is this document's, nothing is
    pressed and the trace says why. A document saved from another row
    would be filed under this one's name and marked done for good."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # One record cannot stand for two documents. Its file address could be
    # either one's, and the row route either finds two of the type in one
    # row and refuses, or two rows on the date and cannot tell them apart.
    # A save under it would also mark it done, and the other document would
    # never be fetched (#37).
    if shared:
        if trace is not None:
            trace.append({"note": "two documents in the list share this date, type and category",
                          "so": "one record cannot stand for both, so nothing was fetched or pressed"})
        return False
    if not goto_documents(page):
        log.info("could not open the documents page for %s", iso_date)
        return False
    # The document's own address from the API, fetched from inside the
    # page. Only on statefarm.com, and only a PDF counts, or a ZIP the docs
    # module opens.
    #
    # A run that had no address and then found no control on the page
    # wrote a trace with nothing in it at all, which is what a tester
    # sent, and an empty trace cannot be told apart from a run that never
    # started. Both of those now say so in a sentence (#37).
    if trace is not None and not (hint and "/" in hint):
        trace.append({"note": "the document list gave no file address for this document",
                      "have": _hint_word(hint),
                      "so": "the row's own control on the page is the only way left"})
    if hint and "/" in hint:
        from urllib.parse import urljoin
        target = urljoin(page.url, hint)
        # Discovery used to drop this address before it reached here, so
        # it had never been asked for. What goes in the trace is a status, a
        # word for the content type and for what came back, a size, and
        # facts about the address, never the address itself (#37).
        if is_safe_url(target):
            facts = {"absolute": hint.lower().startswith(("http:", "https:", "//")),
                     "address": url_mask(target, page.url or "")}
            try:
                with _unheard(page, census):
                    got = _fetch_with_status(page, target, tuple(ALLOWED_HOSTS))
                b64 = got.get("b64") or ""
                data = base64.b64decode(b64) if b64 else b""
                if _is_document(data, zip_ok=True):
                    out_path.write_bytes(data)
                    return True
                if trace is not None:
                    trace.append(dict({"note": "filePathUrl did not answer with a PDF",
                                       "status": _status_of(got.get("status")),
                                       "type": _kind_of(str(got.get("type") or "")),
                                       "answered": _answer_kind(data), "bytes": len(data)},
                                      **facts))
            except Exception as e:
                if trace is not None:
                    trace.append(dict({"note": "filePathUrl fetch failed", "why": _fetch_failure(e)},
                                      **facts))
        elif trace is not None:
            trace.append({"note": "filePathUrl is not on statefarm.com, so it was not asked for"})
    # Another document in the list has this one's date and type, in another
    # category. A row is found by its date and its document by its type, so
    # the page cannot say which of the two a row holds, and when only one of
    # them is drawn its document would be saved under this one's name. Its
    # own file address above is the one way to tell them apart (#37).
    if twins:
        log.info("%d other document(s) share %s and this type, so no row was pressed",
                 twins, iso_date)
        if trace is not None:
            trace.append({"note": "another document in the list has this date and type",
                          "others": twins,
                          "so": "the page does not say which row is whose, so none was pressed"})
        return False
    # The rows are NOT all opened here any more. Opening every row and then
    # pressing the wanted row's View Documents again pressed the same button
    # twice, which folds the row away when it was the one left open. The
    # rows' own buttons carry the dates, so the wanted row is found folded
    # and opened once (#37).
    #
    # The page draws the rows of one period, so a document from an earlier
    # year has a row only once the list is asked for its year. It is asked
    # for that first, and a document from this year asks for its year only
    # when the page's own period does not hold its row (_years_to_show).
    #
    # Whether a load holds the row is read from every control once the page
    # is expanded, the way the row is found below. The wait's own look at the
    # dates reads the first thirty controls only, so a row past them would
    # send a this-year document to a second load that rests on a guess. A
    # load that does not load ends the search. One that ends on a sign-in
    # page ends it only for the page's own period, so an older document whose
    # own year ended early is still looked for in the page's own period.
    answers: list = []
    for year in _years_to_show(iso_date):
        answers = []
        loaded = _fresh_list(page, iso_date, year=year, answers=answers)
        if trace is not None:
            said = ("loaded the documents page again and waited for its rows" if year is None else
                    "loaded the documents page again with its list asked for this document's "
                    "year, and waited for its rows")
            trace.append(dict({"note": said}, **loaded))
        expand_all(page)
        here = _controls_for(page, iso_date)
        for h, _ in here:
            try:
                h.dispose()
            except Exception:
                pass
        if here or loaded.get("reloaded") is False or (year is None and loaded.get("stopped_early")):
            break

    found = _controls_for(page, iso_date)
    if found.unread:
        log.info("a control could not be read, so none was pressed for %s", iso_date)
        if trace is not None:
            trace.append({"note": "a control on the page could not be read", "unread": found.unread,
                          "so": "which row is this document's is not known, so none was pressed"})
        return False
    if not found:
        log.info("no document control found for %s", iso_date)
        if trace is not None:
            trace.append({"note": "no control on the page carries this date",
                          "date": iso_date, "page": url_mask(page.url or ""),
                          "controls_seen": _control_dates(page)})
        return False
    # Two rows on one date cannot be told apart by the date, and the first
    # one used to be pressed. Its document of the same type was then saved
    # under this one's name (#37).
    if len(found) > 1:
        log.info("%d controls carry %s, so none was pressed", len(found), iso_date)
        if trace is not None:
            trace.append({"note": "more than one control on the page carries this date",
                          "controls": len(found),
                          "so": "which row is this document's is not known, so none was pressed"})
        return False
    # The control is the node _controls_for read its name and date from, so
    # a row drawn above it later cannot turn it into another row's control.
    # Its name, date and link are read again right before it is used.
    el, label = found[0]
    if not is_safe_control(label):
        log.info("refusing unsafe control %r for %s", label, iso_date)
        if trace is not None:
            trace.append({"note": "the control for this date is one the guard refuses",
                          "control": _label_mask(label)})
        return False

    def check() -> str:
        return _still_the_one(page, el, iso_date, label)

    if VIEW_DOCUMENTS_RE.match(label):
        # What the list the page just fetched calls this document, so a
        # description that is the list's own words is not refused for a
        # noun (#37).
        return _open_row_then_document(page, el, label, title, out_path, trace, dl_dir,
                                       census=census, check=check, iso=iso_date,
                                       own=_own_words(answers, hint))

    # Here the control is the document itself, so what it says it is has to
    # be what is wanted. A row whose one control was a Declarations Page was
    # saved as the Renewal Notice asked for on that date (#37).
    want = _type_key(title)
    named = _named_type(label)
    if named and not _same_type(named, want):
        if trace is not None:
            trace.append({"note": "the control for this date names another type of document",
                          "names": _KNOWN_TYPES.get(named, "another type"),
                          "wanted_type": _type_word(title),
                          "so": "it was not fetched or pressed"})
        return False
    # Its link is read in the same read that checks its name and date. A link
    # read after the check could be another row's by then, and it is fetched
    # and saved with no press for a check to stop (#37).
    why, href, row = _recheck(page, el, iso_date, label)
    if why:
        if trace is not None:
            trace.append({"note": "the control changed before its link was read, "
                                  "so nothing was fetched or pressed", "why": why})
        return False
    # A control whose own words name no type ("View PDF") is what its row
    # says it is. One in a Declarations Page row was saved as the Renewal
    # Notice asked for on that date, since nothing it said was against it.
    # The row's words come from the same read as its name, date and link,
    # and a row that names any other known type refuses it, even when the
    # wanted type is named there too, since the row cannot say which of the
    # two the control is (#37).
    other = "" if named else _other_type_named(row, want)
    if other:
        if trace is not None:
            trace.append({"note": "the control for this date names no type and its row names "
                                  "another type of document",
                          "names": _KNOWN_TYPES.get(other, "another type"),
                          "wanted_type": _type_word(title),
                          "so": "it was not fetched or pressed"})
        return False
    if not named and not _names_type(row, want):
        if trace is not None:
            trace.append({"note": "the control for this date names no type and its row does not "
                                  "name the type asked for",
                          "wanted_type": _type_word(title),
                          "so": "it was not fetched or pressed"})
        return False

    def check_direct() -> str:
        """Why the control is no longer the one that was checked, right
        before a press, with its row's words read again in the same read."""
        why_now, _link, row_now = _recheck(page, el, iso_date, label)
        if why_now:
            return why_now
        if not named and _other_type_named(row_now, want):
            return "its row names another type of document now"
        if not named and not _names_type(row_now, want):
            return "its row no longer names the type asked for"
        return ""

    def fetch_then_press() -> bool:
        if href and not href.lower().startswith(("javascript", "#")):
            from urllib.parse import urljoin
            target = urljoin(page.url, href)
            # A link on the provider's own hosts is fetched through the
            # session first. A PDF answer is the document. Anything else
            # means the link is a page or a handoff, and the click below
            # follows it.
            if is_safe_url(target):
                body = _fetch_pdf(page, target, zip_ok=True)
                if body:
                    out_path.write_bytes(body)
                    return True
                if trace is not None:
                    trace.append({"note": "the control's own link did not answer with a PDF",
                                  "address": url_mask(target, page.url or "")})
        return _catch_pdf(page, el, label, out_path, trace, dl_dir, check=check_direct)

    return _press_unheard(page, census, trace, fetch_then_press)


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
    r"^\s*((see|view|show|get)\s+)?(bills?|billing|bill(ing)?\s+history|documents(\s*\(excludes\s+claims\))?|"
    r"documents\s*&\s*pdfs|policy\s+documents|(insurance\s+)?id\s+cards?|receipts?|payment\s+history|"
    r"(insurance\s+)?billing\s+and\s+payment\s+history|statements?)\s*$", re.I)


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
    guard's verdict on each, and every JSON or PDF response statefarm.com sends
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
ALLOWED_HOSTS = {"statefarm.com"}


def is_safe_url(url: str) -> bool:
    """True only for an https URL on one of this provider's own hosts.

    The check itself lives in the core, so all of them answer the same way.
    This app keeps the hosts, which is the part that really is its own."""
    return _host_allows(url, ALLOWED_HOSTS)
