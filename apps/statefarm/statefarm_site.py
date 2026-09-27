"""ALL statefarm.com selectors, URLs, and page behavior live here.

When State Farm changes its site, repair this file only.

STATUS: UNVERIFIED, round three, repaired from two surveys (#37). Written
without a State Farm account, so that someone who holds one can
test it without writing code. Nothing below has run against the live
signed-in site. On a first run it is deliberately cautious:

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
from paperpull_core.capture import take_new_pdf as _take_new_pdf
from paperpull_core.capture import fetch_pdf as _core_fetch_pdf
from paperpull_core.capture import take_new_tab as _core_take_new_tab
from paperpull_core.capture import take_same_tab as _core_take_same_tab
from paperpull_core.capture import fetch_with_status as _fetch_with_status
from paperpull_core.capture import UNFINISHED as _UNFINISHED
from paperpull_core.controls import control_texts as _control_texts
from paperpull_core.controls import second_step as _core_second_step
from paperpull_core.controls import controls_named as _controls_named
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
# fills itself from DocumentCenterProxyV1/customerMetadata?year=NNNN,
# whose answer is data.attributes[] of {availableDate, category, type,
# description, documentId, filePathUrl, policyId, ...}. Discovery reads
# that answer as the page loads it, then asks the same address for each
# earlier year. A document's PDF is its filePathUrl, fetched from inside
# the page, with the row's own control as the fallback.
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


def is_revealed_document(label: str) -> bool:
    """A document link a row revealed, once the guard has had its say.
    The forbidden words are checked first, so "Pay Now - Payment Receipt"
    is refused however well it is shaped."""
    label = (label or "").strip()
    if not label:
        return False
    if FORBIDDEN_CONTROL_RE.search(label):
        return False
    if SETTINGS_CONTROL_RE.search(label) or AUTH_CONTROL_RE.search(label):
        return False
    if VIEW_DOCUMENTS_RE.match(label):
        return False
    return bool(REVEALED_DOC_RE.match(label))


def _refused_document(label: str) -> bool:
    """Shaped like a revealed document and refused by the guard.

    The guard reads the whole name, the description included, so a vehicle
    whose description holds one of its words ("Limited" holds "limit") is
    refused like a control that pays. That is the safe way round and stays.
    The trace used to call such a document "another control", which cannot
    be told from something that is not a document at all (#37)."""
    label = " ".join((label or "").split())
    if not label or VIEW_DOCUMENTS_RE.match(label) or not REVEALED_DOC_RE.match(label):
        return False
    return not is_revealed_document(label)


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


def _label_mask(label: str) -> str:
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
    if is_revealed_document(text):
        return "%s - ..." % _type_word(text)
    if _refused_document(text):
        return "%s - ..., refused by the guard" % _type_word(text)
    if _SECOND_STEP_RE.match(text):
        return text.lower()[:30]
    return "another control"


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


def _visible_named(page, text: str, whole: bool = False) -> list:
    """The visible controls named `text`, as nodes, at most five.

    A name as long as the core cuts one is matched by how it starts, since
    the control's own name is longer. A revealed document of seventy
    characters, "Renewal Notice - " and a long vehicle, was looked for by
    its first sixty and never found (#37). `whole` matches the whole name
    and nothing else, for a name read off the node itself."""
    tail = "$" if whole or len(text) < _CUT_AT else ""
    pattern = re.compile("^" + re.escape(text) + tail, re.I)
    for loc in (page.get_by_role("link", name=pattern), page.get_by_role("button", name=pattern),
                page.locator("a, button, [role=button], [role=link]").filter(has_text=pattern)):
        found = []
        try:
            for h in loc.element_handles()[:5]:
                try:
                    if h.is_visible():
                        found.append(h)
                except Exception:
                    continue
        except Exception:
            found = []
        if found:
            return found
    return []


_DOC_NAME_JS = "el => [el.innerText || '', el.getAttribute('aria-label') || '', el.isConnected]"


def _doc_name(el) -> Optional[dict]:
    """A revealed document's whole name, its aria-label and whether it is on
    the page, read off the node in one call, or None."""
    try:
        got = el.evaluate(_DOC_NAME_JS)
    except Exception:
        return None
    if not isinstance(got, list) or len(got) != 3:
        return None
    text, aria, connected = got
    return {"name": " ".join(str(text or "").split()), "aria": " ".join(str(aria or "").split()),
            "connected": bool(connected)}


def _guard_refuses_words(text: str) -> bool:
    """True when the guard's words refuse `text`, whatever its shape."""
    return bool(FORBIDDEN_CONTROL_RE.search(text) or SETTINGS_CONTROL_RE.search(text)
                or AUTH_CONTROL_RE.search(text))


def _revealed_document(page, appeared: set, title: str):
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
    want = _type_key(title)
    candidates = sorted(t for t in appeared if is_revealed_document(t))
    if not candidates:
        if any(_refused_document(t) for t in appeared):
            return None, "", "what the row revealed looks like a document and the guard refuses it"
        return None, "", "nothing the row revealed looks like a document"
    if not want or want == "document":
        return None, "", "this document has no type to match against"
    same = [t for t in candidates if _type_key(t) == want]
    if len(same) != 1:
        return None, "", ("%d revealed documents are this type, and one is needed" % len(same))
    text = same[0]
    found = _visible_named(page, text)
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
    if not is_revealed_document(name) or (read["aria"] and _guard_refuses_words(read["aria"])):
        return None, "", "the guard refuses the document's whole name"
    return el, name, ""


def _still_the_document(page, el, name: str, row, iso: str, facts: Optional[dict] = None) -> str:
    """Why the revealed document about to be pressed is no longer the one
    that was checked, or can no longer be tied to the row that was pressed,
    as a fixed phrase, or "" when it is still both.

    Its own name and count are read again first, the same check the row's
    own control gets before its press (#37). Then _still_in_its_row ties it
    to `row`, the control that was pressed, and `facts` gets what that says
    about where the document sat when it was not inside the row."""
    read = _doc_name(el)
    if read is None:
        return "it could not be read again"
    if not read["connected"]:
        return "it left the page"
    if read["name"] != name:
        return "its name changed"
    n = len(_visible_named(page, name, whole=True))
    if n != 1:
        return "%d visible controls carry its name now" % n
    return _still_in_its_row(page, row, el, name, iso, facts)


def _still_in_its_row(page, row, doc, name: str, iso: str, facts: Optional[dict] = None) -> str:
    """Why the revealed document `doc` cannot be tied to the row whose
    control `row` was pressed, as a fixed phrase, or "" when it can.

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
        counted. Another row's View Documents is, since a date printed as
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
    dated row, rather than inside it, is refused here, and those say so."""
    if not iso:
        return "there is no date to tie the document to its row"
    dated = _controls_for(page, iso)
    handles = [h for h, _ in dated]
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
    if not isinstance(got, list) or len(got) != 10:
        return "the row's control could not be read again"
    (row_on, row_name, row_text, doc_on, doc_text, inside, outside, openers_inside,
     in_parent, in_next) = got
    if not row_on:
        return "the row's control left the page"
    if _date_of({"name": str(row_name or "").strip(), "row": str(row_text or "")}) != iso:
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
    if not doc_on:
        return "it left the page"
    if " ".join(str(doc_text or "").split()) != name:
        return "its name changed"
    if not row_text:
        return "the row's control is in no row that carries a date"
    if not inside:
        if facts is not None:
            facts.update({"in_the_row": False, "in_the_element_after_the_row": bool(in_next),
                          "in_the_rows_parent": bool(in_parent)})
        return "the document is not inside the row that was pressed"
    return ""


def _open_row_then_document(page, el, label: str, title: str, out_path: Path,
                            trace: Optional[list], dl_dir, census=None, check=None,
                            iso: str = "") -> bool:
    """Press the row's View Documents once, then the document it revealed.

    A Pilot pressed View Documents, saw "Payment Receipt - Payment Receipt"
    appear and stopped there, because nothing pressed the document itself
    (#37). The row's button is pressed exactly once. Pressing it again
    would fold the row away, so a row that is already open is left alone
    and the trace says so.

    `check` says, right before the press, why the control is no longer the
    one that was checked, or nothing when it still is. The revealed
    document gets the same check before its own press, and is also tied to
    this row then, by `iso`, the document's date (_still_in_its_row). Once
    the pressed control has left the page nothing that appeared can be tied
    to it, so nothing more is pressed. `census` is the run's request census,
    which is not listening while the document is pressed and caught."""
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
    try:
        el.click(timeout=8000)
        note({"note": "clicked", "control": _label_mask(label)})
    except Exception as e:
        note({"note": "click failed", "control": _label_mask(label), "why": _click_failure(e)})
        return False
    appeared: set = set()
    for _ in range(8):
        page.wait_for_timeout(500)
        appeared = _control_texts(page) - before
        if any(is_revealed_document(t) for t in appeared):
            break
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
          "appeared": [_label_mask(t) for t in sorted(appeared)[:15]],
          "look_like_documents": sum(1 for t in appeared if is_revealed_document(t)),
          "of_the_wanted_type": sum(1 for t in appeared
                                    if is_revealed_document(t) and _type_key(t) == want),
          "refused_by_the_guard": sum(1 for t in appeared if _refused_document(t)),
          "expanded_before": _attr_word(expanded), "expanded_after": _attr_word(expanded_after),
          "control_after_the_press": after})
    # What appeared is this row's only while the node that was pressed is
    # still there to hold it. A list drawn again after the press, keeping its
    # open row by its place, put new nodes everywhere and opened the row
    # above, and that row's receipt was pressed and saved as this one (#37).
    if after == "left the page":
        note({"note": "no revealed document was pressed",
              "why": "the row's control left the page after its press, "
                     "so nothing ties what appeared to its row"})
        return False
    if after != "still on the page":
        note({"note": "no revealed document was pressed",
              "why": "the row's control could not be read after its press, "
                     "so nothing ties what appeared to its row"})
        return False
    doc_el, doc_name, why = _revealed_document(page, appeared, title)
    if doc_el is None:
        note({"note": "no revealed document was pressed", "why": why})
        return False

    def check_document() -> str:
        where: dict = {}
        why_now = _still_the_document(page, doc_el, doc_name, el, iso, where)
        if where:
            note(dict({"note": "where the document sat against the row that was pressed"}, **where))
        return why_now

    # Whatever the page asks for once the document is pressed is the
    # document's own, and the census would keep any part of its path that is
    # not a number. What arrives is in the trace as facts instead (#37).
    return _press_unheard(page, census, trace, lambda: _catch_pdf(
        page, doc_el, doc_name, out_path, trace, dl_dir, check=check_document))


# How long a fresh Document Center may take to draw its rows. It draws none
# until its own list call has answered (#37).
ROWS_WAIT_MS = 30000
# How long the wanted row's control has to stay the same node before it is
# pressed. A page that draws its rows and then draws them again a moment
# later leaves the first press on a node that is no longer there (#37).
SETTLE_MS = 1500


def _all_on_page(handles) -> bool:
    for h in handles:
        try:
            if not h.evaluate("el => el.isConnected"):
                return False
        except Exception:
            return False
    return True


def _fresh_list(page, want: str = "") -> dict:
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

    Returns what the wait saw, as counts and yes or no, for the trace."""
    answered: list = []

    def on_response(res):
        try:
            url = res.url or ""
            if is_safe_url(url) and DOCS_API_RE.search(url):
                answered.append(1)
        except Exception:
            pass

    facts = {"waited_ms": 0, "list_answered": False, "dated_controls": 0,
             "wanted_date_seen": False, "rows_redrawn": 0}
    page.on("response", on_response)
    try:
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
        facts["list_answered"] = bool(answered)
    dismiss_overlay(page)
    return facts


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
_ROW_BOX_JS = r"""el => {
  const dateRe = /(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}|\d{1,2}\/\d{1,2}\/\d{2,4}|\d{4}-\d{2}-\d{2}/i;
  let node = el, depth = 0;
  while (node && depth < 6) {
    if (dateRe.test((node.innerText || '').trim())) return node;
    node = node.parentElement; depth++;
  }
  return null;
}"""
_ROW_OF_JS = ("el => { const box = (" + _ROW_BOX_JS + ")(el); "
              "return box ? (box.innerText || '').trim().slice(0, 300) : ''; }")


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


def _capture_docs(page) -> Tuple[list, list]:
    """Open the Document Center while catching the customerMetadata answer
    and the address it was asked at, so discovery can ask for other years
    the same way."""
    bodies: list = []
    urls: list = []

    def on_response(res):
        try:
            url = res.url or ""
            if is_safe_url(url) and DOCS_API_RE.search(url):
                urls.append(url)
                bodies.append(res.json())
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
    return bodies, urls


# The answer's status and content type come back with it, so a year that
# was refused can be told from a year with nothing in it.
_FETCH_JSON = r"""async (u) => {
    const r = await fetch(u, {credentials: 'include', headers: {accept: 'application/json'}});
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
})


def _years_from(page, url: str, first_year: int, facts: Optional[dict] = None) -> List[dict]:
    """The same customerMetadata call for each earlier year, made from
    inside the page. The year is the only thing changed in the address.

    Discovery has found the current year only in every round since 0.33.0,
    and the census in his failure file shows no answer for any earlier
    year, while this walk wrote its failures to the log and nowhere else
    (#37). `facts` gets each year's status, a word for its content type
    and how many documents it listed and kept, or a fixed phrase for why
    it failed, and why the walk stopped."""
    from datetime import date as _date
    out = []
    asked: list = []
    stopped = "asked every year back to the limit"
    empty = 0
    this_year = _date.today().year
    for year in range(this_year, this_year - YEARS_BACK - 1, -1):
        if year == first_year:
            continue
        target = re.sub(r"([?&]year=)\d{4}", lambda m: m.group(1) + str(year), url)
        if target == url:
            stopped = "the list's address carries no year to change"
            break
        if not is_safe_url(target):
            stopped = "the changed address is not on statefarm.com"
            break
        entry: dict = {"year": year}
        asked.append(entry)
        try:
            got_raw = page.evaluate(_FETCH_JSON, target)
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


def collect_download_docs(page, facts: Optional[dict] = None) -> List[RawDoc]:
    """Every document the Document Center's API lists, this year as the
    page loads it and each earlier year by the same call, else the rows.

    `facts` gets counts and fixed words about how the list was read, for
    download-attempt.json (#37)."""
    docs: List[RawDoc] = []
    seen = set()
    bodies, urls = _capture_docs(page)
    found = []
    for body in bodies:
        found.extend(_docs_from_api(body))
    if facts is not None:
        facts["page_list_answers"] = len(bodies)
        facts["page_list_listed"] = sum(_listed(b) for b in bodies)
        facts["page_list_kept"] = len(found)
    if urls:
        m = re.search(r"[?&]year=(\d{4})", urls[0])
        if facts is not None:
            facts["year_in_address"] = bool(m)
        found.extend(_years_from(page, urls[0], int(m.group(1)) if m else -1, facts))
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
        insurance = bool(re.search(r"id\s*card|declaration|policy", d["kind"] + " " + d["title"], re.I))
        docs.append(RawDoc(title=d["title"], account=d["category"], date_text=d["date"],
                           href=d["url"] or d["hint"], text=f"State Farm {d['title']} {d['desc']}",
                           kind="insurance" if insurance else "statement", ident=ident))
    if docs:
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
        iso = parse_date(name)
        if not iso:
            try:
                row_text = el.evaluate(_ROW_OF_JS) or ""
            except Exception:
                row_text = ""
            iso = parse_date(row_text)
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
                    + _ROW_OF_JS + ")(el), el.isConnected, el.getAttribute('href') || '']")

# The pressed row's control, the document it revealed and every control that
# carries the wanted date, read in one call so what it says holds for one
# moment. `openers` says which of the dated controls is another row's View
# Documents. The control's name and its row's text are read as
# _NAME_AND_ROW_JS reads them, and the row is the container _ROW_BOX_JS
# finds. Returns whether the control is on the page, its name, its row's
# text, whether the document is on the page, the document's own words,
# whether the row holds the document, how many dated controls sit outside
# the row besides the control itself, how many other View Documents carrying
# the date sit inside it, and whether the document sits in the row's parent
# or in the element right after the row, for the trace when the row does
# not hold it (#37).
_TIE_JS = ("(row, [doc, dated, openers]) => { const box = (" + _ROW_BOX_JS + ")(row); "
           "const inside = h => !!box && box.contains(h); return ["
           "row.isConnected, (row.getAttribute('aria-label') || row.innerText || '').trim(), "
           "box ? (box.innerText || '').trim().slice(0, 300) : '', "
           "doc.isConnected, doc.innerText || '', "
           "!!box && box !== doc && box.contains(doc), "
           "dated.filter(h => h !== row && !inside(h)).length, "
           "dated.filter((h, i) => h !== row && inside(h) && openers[i]).length, "
           "!!box && !!box.parentElement && box.parentElement.contains(doc), "
           "!!box && !!box.nextElementSibling && box.nextElementSibling.contains(doc)]; }")


def _read_control(el) -> Optional[dict]:
    """A control's name, the text that dates it, whether it is on the page
    and its link, from one read of the node itself, or None."""
    try:
        got = el.evaluate(_NAME_AND_ROW_JS)
    except Exception:
        return None
    if not isinstance(got, list) or len(got) != 4:
        return None
    name, row, connected, href = got
    return {"name": str(name or "").strip(), "row": str(row or ""),
            "connected": bool(connected), "href": str(href or "")}


def _date_of(read: dict) -> Optional[str]:
    """The date a control belongs to, from its own name first and then from
    the text around it, the way discovery reads it."""
    return parse_date(read["name"]) or parse_date(read["row"])


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
    the next (#37)."""
    out = []
    try:
        handles = _bill_controls(page).element_handles()
    except Exception:
        return out
    for h in handles:
        got = _read_control(h)
        if got is not None and _date_of(got) == iso:
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
    n = len(_controls_for(page, iso))
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
            found = parse_date(name)
            if not found:
                try:
                    found = parse_date(el.evaluate(_ROW_OF_JS) or "")
                except Exception:
                    found = None
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


def _fetch_pdf(page, href: str) -> Optional[bytes]:
    """A PDF link fetched from inside the signed-in page, cookies and all.
    The fetching is the core's, the hosts are this app's."""
    return _core_fetch_pdf(page, href, is_safe_url)


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
               dl_dir=None, check=None) -> bool:
    """Click `el` and save whatever PDF the site produces, a file landing
    in `dl_dir`, a download event, a PDF response, a new tab, this tab
    moving to the document, or a second control the click revealed.
    `trace` collects what happened, the click's own outcome included.
    `check`, when given, says right before the click why `el` is no longer
    the control that was checked, and then nothing is clicked."""
    ctx = page.context
    got: dict = {}
    downloads: list = []
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
            if trace is not None and ("json" in ct or "pdf" in ct or "octet" in ct):
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
        if downloads:
            try:
                from paperpull_core.receipt_pdf import save_download
                save_download(downloads[0], out_path)
                if out_path.exists() and out_path.read_bytes()[:5] == b"%PDF-":
                    return True
            except Exception as e:
                log.info("download event save failed: %s", e)
        if got.get("body"):
            out_path.write_bytes(got["body"])
            return True
        if got.get("refetch"):
            try:
                resp = page.context.request.get(got.pop("refetch"), timeout=60000)
                body = resp.body() if resp.ok else b""
                if body[:5] == b"%PDF-":
                    out_path.write_bytes(body)
                    return True
            except Exception:
                pass
        if unfinished:
            return False
        return _take_new_pdf(dl_dir, seen, out_path)

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
                trace.append({"note": "clicked", "control": _label_mask(label)})
        except Exception as e:
            if trace is not None:
                trace.append({"note": "click failed", "control": _label_mask(label),
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
                    trace.append({"note": "clicked through the DOM instead", "control": _label_mask(label)})
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
        log.info("click on %r produced no PDF", label)
        return False
    finally:
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
    # page. Only on statefarm.com, and only a PDF counts.
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
                if data[:5] == b"%PDF-":
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
    loaded = _fresh_list(page, iso_date)
    if trace is not None:
        trace.append(dict({"note": "loaded the documents page again and waited for its rows"},
                          **loaded))
    expand_all(page)

    found = _controls_for(page, iso_date)
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
        return _open_row_then_document(page, el, label, title, out_path, trace, dl_dir,
                                       census=census, check=check, iso=iso_date)

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
                body = _fetch_pdf(page, target)
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
                    "^" + re.escape(c["text"].replace("#", "")) + "$", re.I)).first
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
