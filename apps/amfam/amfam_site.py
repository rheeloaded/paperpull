"""ALL amfam.com selectors, URLs, and page behavior live here.

When American Family changes its site, repair this file only.

STATUS: UNVERIFIED. This app was written without an American Family
policy, from the sign-in page the requester named (#45) and what is
publicly known about the My Account site, so that someone who holds one
can test it without writing code. Nothing below has run against the live
signed-in site. On a first run it is deliberately cautious:

  * --login opens a real Edge or Chrome at myaccount.amfam.com, whose
    sign-in is the user's to complete.
  * --diagnose surveys whatever the documents and billing pages turn out
    to be, records their headings, their controls with the guard's verdict
    on each, and the shape of every JSON response, with digit runs
    masked, and takes no screenshot. That file is what a tester attaches
    to the GitHub issue.
  * --discover reads dates from any control that looks like a bill,
    statement, policy document, declarations page or ID card, wherever it
    sits on the page.
  * --pilot tries to save the newest few, by fetching a PDF link the row
    carries from inside the page, or by clicking the row's own control and
    catching a download event, a PDF response or a new tab.

The guesses that most need confirming from a survey are marked GUESS. The
routes are the biggest one. My Account is a single-page app, and its
documents and billing views may sit under paths the first survey has to
find from the page's own links.

SAFETY (this is an insurance account with a payment method on file):
  This module is strictly READ-ONLY. It opens the documents and billing
  pages, reads the lists, and saves the PDFs American Family already
  generated. It must NEVER activate any control that pays, sets up
  autopay, files or reports a claim, changes coverage, adds or removes a
  vehicle, driver or policy, starts a quote, cancels or renews a policy,
  or edits any setting. FORBIDDEN_CONTROL_RE is the guard. A control must
  ALSO look like a document action (SAFE_DOC_CONTROL_RE) before it may be
  clicked. There is no code here that submits a form or confirms a dialog.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import unquote, urlsplit

from paperpull_core.controls import SETTINGS_CONTROL_RE, AUTH_CONTROL_RE

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
from paperpull_core.capture import take_new_pdf as _take_new_pdf
from paperpull_core.capture import fetch_pdf as _core_fetch_pdf
from paperpull_core.capture import is_document as _is_document
from paperpull_core.capture import take_new_tab as _core_take_new_tab
from paperpull_core.capture import take_same_tab as _core_take_same_tab
from paperpull_core import blob_capture
from paperpull_core.controls import control_texts as _control_texts
from paperpull_core.controls import second_step as _core_second_step
from paperpull_core.controls import controls_named as _controls_named
from paperpull_core.controls import escape_for_locator
from paperpull_core.dates import checked as _checked_date
from paperpull_core.dates import full_year as _full_year

log = logging.getLogger("amfam_docs.site")

BASE = "https://myaccount.amfam.com"
# RECORDED (#45). My Account's sign-in is at /login, and Billing & Payments
# is /billing, in the same tab, where the tester opens his statements. The
# app started at /documents until 0.41.0, a guess, which is the wrong place.
# Only the first of these is where statements are looked for. The others
# are where 0.40.0 looked, and the overview's links name the real ones.
BILLING_CANDIDATES = [
    f"{BASE}/billing",
    f"{BASE}/documents",
    f"{BASE}/policies",
    f"{BASE}/overview",
    f"{BASE}/",
]
BILLING_URL = BILLING_CANDIDATES[0]
URLS = {
    "home": f"{BASE}/",
    "login": f"{BASE}/login",
    "documents": BILLING_URL,
    "statements": BILLING_URL,
}

LOGIN_URL_MARKERS = ["/login", "/signin", "/sign-in", "/auth/", "/mfa",
                     "/verification", "/challenge", "/authenticate"]

# ---------------------------------------------------------------------------
# HARD SAFETY GUARD. Tuned for an insurer, on top of the bank words. Never
# move money, never change coverage or a policy, never change a setting.
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
    r"close\s+(my\s+|this\s+|your\s+|the\s+)?(account|policy)|"
    # How a bill or a document is delivered, and what a person is sent. None
    # of these is a document, and each changes a setting or asks for
    # something (review of 0.41.0).
    r"e-?mail|\btext\s+me\b|\bby\s+text\b|\bby\s+mail\b|\bmail\s+me\b|remind|notif|"
    r"\breceive\b|\bswitch\b|stop\s+mailing|combine|reinstate|\brenew\b|\brequest\b|\bsend\b|"
    r"online|electronic|\bpaper\b|postal|\bmail(ed|ing)?\b|u\.?s\.?\s+mail|deliver|\btexted\b|"
    r"via\s+text|quarterly|spanish|\blanguage|frequency|different\s+date|"
    r"beneficiar|nickname|"
    r"(?<!excludes )\bclaims?\b|file\s+a\s+claim|report\s+(a\s+)?claim|coverage|\bquote\b|"
    r"add\s+(a\s+)?(vehicle|driver|car|home|policy)|change\s+(my\s+)?policy|cancel\s+policy|renew\s+now|"
    r"start\s+(a\s+)?quote|roadside|\bagent\b|contact\s+(my\s+)?agent|policy\s+change|knowyourdrive|"
    r"know\s+your\s+drive|drive\s+safe|discount)", re.I)

SAFE_DOC_CONTROL_RE = re.compile(
    r"(download|view|open|print|\bpdf\b|statement|document|\bletter\b|notice|"
    r"1099|1098|5498|tax\s+(form|document)|history|"
    r"id\s+cards?|insurance\s+cards?|renewal\s+(notice|bill)|receipts?\b|\bbills?\b|billing\b|"
    r"policy\s+documents?|declarations?|dec\s+page|see\s+(more|all|older)|show\s+(more|all|older)|load\s+more)", re.I)

# A control that fetches one document, as the whole of its words. A read
# verb and a statement's name, "View bill", "Download statement (PDF)",
# "View bill for September 12, 2026", "View billing statement for policy
# ending 1234", or a statement's name and date, "Billing statement
# 09/12/2026", or a bare "View" or "Download PDF", whose row must then name
# a bill or statement. Never "Get ...", and nothing after the name but a
# date, a policy's last digits or "opens in a new tab". A word anywhere in a
# label matched "Get your statements online", and the guard's refusals, a
# list of phrasings, knew none of them (reviews of 0.41.0).
_DATE_TEXT = (r"(?:(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}"
              r"|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{4}"
              r"|\d{1,2}\/\d{1,2}\/\d{2,4}|\d{4}-\d{2}-\d{2})")
# Escaped, since Playwright writes the pattern into a selector between
# slashes, and a bare one ends it there.
_READ = r"(?:view|download|open)"
_THE = (r"(?:(?:my|the|this|your)\s+)?"
        r"(?:(?:current|latest|last|previous|recent|past|paid|full|printable)\s+)?")
_DOC = (r"(?:bill|billing\s+statement|statement|document|tax\s+(?:form|document)"
        r"|1099(?:-[a-z]{1,4})?|1098|5498)")
_AS_PDF = r"(?:\s*\(?\s*pdf\s*\)?)?"
_WHEN = r"(?:\s*[,-]?\s*(?:(?:for|from|dated|of)\s+)?" + _DATE_TEXT + r")?"
_WHOSE = r"(?:\s*,?\s*for\s+policy\s+(?:number\s+)?ending\s+(?:in\s+)?\d{2,6})?"
_NEW_TAB = r"(?:\s*[,-]?\s*\(?\s*opens\s+in\s+(?:a\s+)?new\s+(?:tab|window)\s*\)?)?"
BILL_CONTROL_RE = re.compile(
    r"^\s*(?:" + _READ + r"\s+" + _THE + _DOC + _AS_PDF + _WHEN + _WHOSE + _NEW_TAB
    + r"|" + _DOC + _AS_PDF + r"\s*[,-]?\s*(?:(?:for|from|dated|of)\s+)?" + _DATE_TEXT + _WHOSE + _NEW_TAB
    + r"|" + _DOC + r"\s*\(?\s*pdf\s*\)?"
    + r"|" + _READ + r"(?:\s+" + _THE + r"pdf)?" + _NEW_TAB
    + r")\s*\.?\s*$", re.I)

# Words that name a statement or a tax form. A control whose own words name
# none, a bare View or Download PDF, is taken only from a row that does, and
# never from one that names another kind of document. A payment plan
# agreement and an ID card were each listed as an Account Statement, and the
# first control carrying a date was the one pressed (review of 0.41.0).
_STATEMENT_WORDS_RE = re.compile(
    r"\b(bills?|billing\s+statements?|statements?|1099|1098|5498|tax\s+(forms?|documents?))\b", re.I)
_OTHER_DOCUMENT_RE = re.compile(
    r"\b(id\s+cards?|insurance\s+cards?|proof\s+of\s+insurance|declarations?|dec\s+page|"
    r"agreements?|contracts?|applications?|endorsements?|"
    r"policy\s+(documents?|packets?|booklets?|changes?)|cancell?ations?|non-?renewals?|"
    r"claims?|letters?|notices?|confirmations?|schedules?)\b", re.I)

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
# RECORDED (#45, on 0.41.0). The tester's recording of opening a statement
# pressed <a data-cy="statementPDF">, a link with no address, so it has no
# link role and no words of a statement's own, and every search by role and
# words found nothing on his billing page. The site's own test id names it.
STATEMENT_PDF_SELECTOR = 'a[data-cy="statementPDF"]'
# Only a mark the page shows. A list the page keeps mounted but hidden, under
# a sign-in prompt or behind another tab, counted as a list showing, and a
# hidden copy ahead of the shown one was the one pressed (review of #45).
_SHOWN_MARKED = STATEMENT_PDF_SELECTOR + ':not([aria-hidden="true"]):not([aria-hidden="true"] *)'

# RECORDED (#45, on 0.43.0). Billing & Payments, headed "My bills", shows
# each bill with an Edit autopay and a Bill details button and no statement
# link of its own, and the tester's recording began on a list of
# statementPDF links under a routed view's heading, after whatever opened
# it. So each bill's statements are taken to be behind its Bill details,
# and a control is one only when the whole of its words is that. GUESS
# where the press leads, a list in place, another route, or either after a
# wait, which the next Diagnose file says.
BILL_DETAILS_RE = re.compile(r"^\s*bill\s+details\s*$", re.I)

FALLBACK = {
    "statement_pdf": STATEMENT_PDF_SELECTOR,
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
# A date is bounded by what is not a digit, not by a word boundary. A row
# built from spans with nothing between them reads "09/12/2026Amount due",
# the way JSX leaves adjacent tags, and a word boundary after the year
# refused it while the page's own row finder had found the date (#45).
DATE_PATTERNS = [
    (re.compile(r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
                r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|"
                r"Dec(?:ember)?)\.?\s+(\d{1,2}),?\s+(\d{4})(?!\d)", re.I), "mdY"),
    (re.compile(r"(?<!\d)(\d{1,2})/(\d{1,2})/(\d{4})(?!\d)"), "mdy_slash"),
    (re.compile(r"(?<!\d)(\d{1,2})/(\d{1,2})/(\d{2})(?!\d)"), "mdy_slash2"),
    (re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)"), "iso"),
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

# What closes an overlay, as the whole of a control's words. Anything that
# began with Close was pressed, "Close my account" and "Close policy" among
# it (review of 0.41.0).
_DISMISS_RE = re.compile(
    r"^\s*(close|dismiss|no\s+thanks|not\s+now)"
    r"(\s+(this\s+)?(dialog|banner|window|message|pop-?up|survey|notice|alert|panel|menu))?\s*[×✕x]?\s*$",
    re.I)


# A close button that shows only its glyph, the way Bootstrap draws one.
_CLOSE_GLYPH_RE = re.compile(r"^\s*[×✕✖xX]\s*$")


def _refused(words: str) -> bool:
    """Whether any of `words` is something the guard refuses."""
    return bool(words and (FORBIDDEN_CONTROL_RE.search(words) or SETTINGS_CONTROL_RE.search(words)
                           or AUTH_CONTROL_RE.search(words)))


def dismiss_overlay(page) -> None:
    """Close a cookie banner, a survey prompt or a promo overlay, the things
    that sit over signed-in pages and intercept clicks. Escape first, then
    only a control that says close or dismiss, never accept."""
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(250)
    except Exception:
        pass
    try:
        cl = page.get_by_role("button", name=_DISMISS_RE)
        for i in range(min(cl.count(), 6)):
            el = cl.nth(i)
            try:
                if el.is_visible():
                    label = (el.inner_text(timeout=500) or "").strip()
                    if label and not (_DISMISS_RE.search(label) or _CLOSE_GLYPH_RE.search(label)):
                        continue
                    if (_refused(label) or _refused(el.get_attribute("aria-label") or "")
                            or _refused(el.get_attribute("title") or "")):
                        continue
                    el.click(timeout=1000)
                    page.wait_for_timeout(250)
            except Exception:
                continue
    except Exception:
        pass


def _bill_controls(page):
    """Every control on the page whose name says it fetches a document, and
    every one the site marks as a statement's PDF. The words are this
    provider's, the rest is the core's."""
    return _controls_named(page, BILL_CONTROL_RE).or_(
        page.locator(_SHOWN_MARKED).filter(visible=True))


def _marked(el) -> bool:
    """Whether the site marks this control as a statement's PDF."""
    try:
        return bool(el.evaluate("(e, s) => e.matches(s)", STATEMENT_PDF_SELECTOR))
    except Exception:
        return False


# A marked link that holds another control, whose press could land on that
# control and do anything (review of #45).
_HOLDS_A_CONTROL_JS = r"""e => !!e.querySelector(
  'a, button, input, select, textarea, [role=button], [role=link], [role=menuitem], [role=checkbox], [role=switch]')"""


def _marked_row_refuses(row_text: str, row_flat: str) -> bool:
    """Whether a marked link's row names another kind of document, or a
    payment without naming a statement. The mark says a statement's PDF, and
    a site that marks every document's link the same way had another
    document's link, above the statement with its date, saved as the
    statement, and the statement itself never fetched (review of #45)."""
    texts = [t for t in (row_text, row_flat) if t]
    if any(_OTHER_DOCUMENT_RE.search(t) for t in texts):
        return True
    return (any(_PAYMENT_WORDS_RE.search(t) for t in texts)
            and not _A_STATEMENT_RE.search(row_flat or row_text))


def _safe_to_press(el, name: str) -> bool:
    """The guard's answer for a control about to be pressed. One the site
    marks as a statement's PDF has no statement words of its own, so every
    word it shows or announces is checked instead."""
    if _marked(el):
        try:
            words = el.evaluate(_WORDS_OF_JS) or []
            holds = el.evaluate(_HOLDS_A_CONTROL_JS)
        except Exception:
            return False
        return not holds and not any(_refused(w) for w in words)
    return is_safe_control(name)


def _looks_like_billing(page) -> bool:
    try:
        if _bill_controls(page).count() > 0 or _details_controls(page).count() > 0:
            return True
    except Exception:
        pass
    try:
        body = page.locator("body").inner_text(timeout=5000)
    except Exception:
        return False
    return bool(re.search(r"statements?\s+(and|&)\s+documents|statement\s+(period|date)|tax\s+documents",
                          body, re.I))


def _on_billing(page) -> bool:
    """The tab is at Billing & Payments, or a page under it, on this
    provider's host."""
    try:
        here, there = urlsplit(page.url or ""), urlsplit(BILLING_URL)
    except ValueError:
        return False
    # The page itself. A page under it, /billing/autopay, was taken for it
    # and read (review of 0.41.0).
    path, home = here.path.rstrip("/"), there.path.rstrip("/")
    return is_safe_url(page.url or "") and here.netloc == there.netloc and path == home


def goto_documents(page) -> bool:
    """Open Billing & Payments, where the tester's statements are (#45), and
    only that page. Another page that looked statement-shaped, the overview
    or the documents page, carries ID cards and other documents, and one was
    saved as a statement (reviews of 0.41.0)."""
    dismiss_overlay(page)
    if _on_billing(page) and not looks_signed_out(page) and _looks_like_billing(page):
        return True
    return _load_billing(page)


# How long Billing & Payments is given to draw its bills or its statements,
# in looks half a second apart. It was a fixed five seconds.
_BILLING_LOOKS = 20


def _settle_billing(page) -> None:
    """Wait until Billing & Payments shows its bills or its statements and
    shows as many on two looks in a row, so a second bill drawn a moment
    after the first is there too. Ends at once when the tab is not at
    Billing & Payments or is signed out, and after about ten seconds
    otherwise."""
    last = -1
    for _ in range(_BILLING_LOOKS):
        try:
            if not _on_billing(page) or looks_signed_out(page):
                return
            now = _details_controls(page).count() + _bill_controls(page).count()
        except Exception:
            now = -1
        if now > 0 and now == last:
            return
        last = now
        page.wait_for_timeout(500)


def _load_billing(page) -> bool:
    """Load Billing & Payments by its address, afresh, and wait for its
    bills or its statements. True only when the tab is there, signed in,
    and the page looks like billing."""
    try:
        page.goto(BILLING_URL, wait_until="domcontentloaded", timeout=60000)
    except Exception as e:
        log.info("goto %s failed: %s", BILLING_URL, e)
        return False
    _settle_billing(page)
    dismiss_overlay(page)
    if looks_signed_out(page):
        return False
    # Where the address went is checked too. A billing page that sent the tab
    # on to the overview was read as billing (review of 0.41.0).
    return _on_billing(page) and _looks_like_billing(page)


def scroll_full_page(page, rounds: int = 8, delay_ms: int = 600) -> None:
    try:
        for _ in range(rounds):
            page.mouse.wheel(0, 3000)
            page.wait_for_timeout(delay_ms)
        page.keyboard.press("End")
        page.wait_for_timeout(delay_ms)
    except Exception:
        pass


def expand_all(page, view: Optional[str] = None) -> bool:
    """Click 'See more' / 'Show more' / 'View older statements' repeatedly
    to surface anything the page loads on demand. The label is
    checked against the guard before every click, and so is every other
    word the control shows or announces, on the element that is pressed.

    `view` is the path a bill's statements showed at after its Bill
    details, Billing & Payments itself or the route the press led to, and a
    press that takes the tab off it has left the page. Without one the page
    is Billing & Payments. False when a press left the page, which is then
    loaded again at Billing & Payments."""
    # Bills and statements only. "View all documents" took the app to the
    # documents page, where an ID card was saved as a statement (review of
    # 0.41.0).
    pat = re.compile(r"^\s*(show|load|view|see)\s+(more|all|older)(\s+(bills?|statements?))?\s*$|"
                     r"^\s*(older|previous)\s+(bills?|statements?)\s*$", re.I)
    for _ in range(30):
        clicked = False
        for role in ("button", "link"):
            try:
                loc = page.get_by_role(role, name=pat)
                if loc.count() > 0 and loc.first.is_visible():
                    el = loc.first.element_handle(timeout=1000)
                    label = el.inner_text() or ""
                    # A show-more whose other words refuse, a title or a
                    # described "and turn on autopay", is never pressed
                    # (review of the Bill details change).
                    if is_safe_control(label) and _words_pass(el):
                        el.click()
                        page.wait_for_timeout(1500)
                        clicked = True
                        break
            except Exception:
                continue
        if clicked and not (_on_view(page, view) if view is not None else _on_billing(page)):
            log.info("a show-more control left %s, going back",
                     "the bill's statements" if view is not None else "Billing & Payments")
            try:
                page.goto(BILLING_URL, wait_until="domcontentloaded", timeout=60000)
            except Exception:
                pass
            return False
        if not clicked:
            break
    return True


@dataclass
class RawDoc:
    title: str
    account: str = ""
    date_text: str = ""
    href: str = ""
    text: str = ""
    row_index: int = -1
    kind: str = "doc"


# The row a bill control sits in, the nearest enclosing element whose
# text carries a date, up to six levels up, read whole. None when that
# element holds another row, another bill control whose own dated row is
# inside it. A document in a row with no date of its own climbed to the
# whole list, whose summary said "billing statement was issued 09/12/2026",
# and a payment plan agreement was saved as that statement (review of
# 0.41.0).
_ROW_OF_JS = r"""(el, arg) => {
  const dateRe = /(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}|\d{1,2}\/\d{1,2}\/\d{2,4}|\d{4}-\d{2}-\d{2}/i;
  const bill = new RegExp(arg.pattern, 'i');
  const marked = (c) => c.matches(arg.marked);
  const wordsOf = (c) => ((c.getAttribute('aria-label') || c.innerText || '')).replace(/\s+/g, ' ').trim();
  const rowOf = (c) => {
    let node = c, depth = 0;
    while (node && depth < 6) {
      if (dateRe.test(node.innerText || '')) return node;
      node = node.parentElement; depth++;
    }
    return null;
  };
  const mine = rowOf(el);
  if (!mine) return '';
  for (const c of mine.querySelectorAll('a, button, [role=button], [role=link]')) {
    if (c === el || el.contains(c) || c.contains(el)) continue;
    if (!bill.test(wordsOf(c)) && !marked(c)) continue;
    const theirs = rowOf(c);
    if (theirs && theirs !== mine && mine.contains(theirs)) return '';
    // Two statement PDFs the site marks in one row, and which statement
    // each one opens cannot be told (review of #45).
    if (theirs === mine && marked(c) && marked(el)) return '';
  }
  // Each visible piece of text with a space between, since spans that
  // touch run their words together in innerText, "10/01/2026Next bill
  // date", where no word boundary falls, and innerText as well (review of
  // 0.41.0).
  const parts = [];
  const walker = document.createTreeWalker(mine, NodeFilter.SHOW_TEXT);
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    const host = n.parentElement;
    if (!host || !host.getClientRects().length) continue;
    const t = (n.textContent || '').replace(/\s+/g, ' ').trim();
    if (t) parts.push(t);
  }
  const text = parts.join(' ');
  const flat = (mine.innerText || '').trim();
  // A row is short. Read whole, a section whose words said "statement"
  // far from a document of another kind was taken for its row (review of
  // 0.41.0).
  if (text.length > 300 || flat.length > 300) return '';
  return {text, flat};
}"""

# Every word a control shows or announces, its label, what its labelledby
# names, its title, an image's alt, its visible text, and text a style puts
# before or after it. Each has to pass the guard. A button labelled "View
# bill" that showed "Go paperless", and one announced as "Enroll in
# paperless billing" that showed "View bill", were pressed (review of
# 0.41.0).
_WORDS_OF_JS = r"""el => {
  const out = [];
  const add = (t) => { t = (t || '').replace(/\s+/g, ' ').trim(); if (t) out.push(t.slice(0, 300)); };
  add(el.getAttribute('aria-label'));
  const by = el.getAttribute('aria-labelledby');
  if (by) for (const id of by.split(/\s+/)) { const n = document.getElementById(id); if (n) add(n.textContent); }
  add(el.getAttribute('title'));
  add(el.innerText);
  // What an input shows, what an SVG's title and aria-describedby announce,
  // none of which innerText holds (review of #45).
  for (const n of [el, ...el.querySelectorAll('input')]) {
    if (n.tagName === 'INPUT') { add(n.value); add(n.getAttribute('value')); }
  }
  for (const t of el.querySelectorAll('svg title, title')) add(t.textContent);
  for (const n of [el, ...el.querySelectorAll('[aria-describedby]')]) {
    const d = n.getAttribute('aria-describedby');
    if (d) for (const id of d.split(/\s+/)) { const m = document.getElementById(id); if (m) add(m.textContent); }
  }
  // And each visible piece of its text alone, since spans that touch run
  // together in innerText, "View billPay now", where "pay" has no word
  // boundary to be refused by (review of 0.41.0).
  const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
  let pieces = 0;
  for (let n = walker.nextNode(); n && pieces < 60; n = walker.nextNode()) {
    const host = n.parentElement;
    if (host && host.getClientRects().length) { add(n.textContent); pieces++; }
  }
  const parts = [el, ...Array.from(el.querySelectorAll('*')).slice(0, 60)];
  for (const n of parts) {
    if (n !== el) { add(n.getAttribute('aria-label')); add(n.getAttribute('alt')); add(n.getAttribute('title')); }
    for (const where of ['::before', '::after']) {
      const c = getComputedStyle(n, where).content;
      if (c && c !== 'none' && c !== 'normal') add(c.replace(/^["']|["']$/g, ''));
    }
  }
  return out;
}"""

# Where a press would land, which has to be the control itself. A card
# labelled "View bill for September 12, 2026" with a "Set up autopay"
# button at its center pressed the button (review of 0.41.0).
_CENTER_JS = r"""el => {
  const r = el.getBoundingClientRect();
  if (!r.width || !r.height) return true;
  const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
  if (!hit || !el.contains(hit)) return true;
  const ctl = hit.closest('a[href], button, input, select, textarea, [role=button], [role=link], [role=menuitem], [role=checkbox], [role=switch]');
  if (!ctl || ctl === el || !el.contains(ctl)) return true;
  // One control wrapped in another, a link around a button with the same
  // words, is the same control, and was refused (review of 0.41.0).
  const words = (n) => (n.innerText || '').replace(/\s+/g, ' ').trim();
  return words(ctl) !== '' && words(ctl) === words(el);
}"""

# Any word of a payment. A bare View in a row that mentions one can be a
# payment's own record, worded any number of ways, "Bill payment
# 09/20/2026", "Bill paid", "Payment applied to statement 09/12/2026", and
# every list of its phrasings missed some (reviews of 0.41.0). Such a row is
# left alone. A control whose own words name the statement, View bill, is
# found whatever its row says.
_PAYMENT_WORDS_RE = re.compile(r"\b(payments?|paid|receipts?)\b", re.I)
# The tax form numbers only as numbers of their own. Inside a reference or
# policy number, "Ref 44109921", a payment's receipt was saved as a tax
# document (review of 0.41.0).
_A_STATEMENT_RE = re.compile(
    r"\b(billing\s+)?statements?\b|(?<![$\d.,])\b(1099|1098|5498)\b(?![.,]\d)|\btax\s+(forms?|documents?)\b", re.I)
_A_BILL_RE = re.compile(r"\bbills?\b", re.I)
_A_TAX_FORM_RE = re.compile(
    r"(?<![$\d.,])\b(1099|1098|5498)\b(?![.,]\d)|\btax\s+(forms?|documents?|statements?)\b", re.I)


def _row_names_a_statement(row_text: str, row_flat: str = "") -> bool:
    """Whether a row says it is a statement or a bill and nothing else. A
    row that also names another kind of document, or a payment, read either
    way, is left alone. `row_flat` is the row's innerText, and naming a
    statement is read from it, `row_text` its pieces with spaces between."""
    flat = row_flat or row_text
    if not flat:
        return False
    for text in (row_text, flat):
        if _OTHER_DOCUMENT_RE.search(text) or _PAYMENT_WORDS_RE.search(text):
            return False
    return bool(_A_STATEMENT_RE.search(flat) or _A_BILL_RE.search(flat))


# The words just before a date that make it the statement's own date.
_STATEMENT_DATE_RE = re.compile(
    r"(statement(\s+date)?|issued(\s+on)?|bill(ing)?\s+date|billed(\s+on)?)\s*:?\s*(on\s+)?$", re.I)
# A row that writes another statement's date anywhere, the next one or an
# earlier one. "Next bill date 10/12/2026" is the next statement's own date,
# and a statement filed under it made the real one count as saved already,
# for good. Anywhere in the row, since a card's header row, "Statement date
# | Next bill date", sits apart from the dates it names (reviews of 0.41.0).
_ANOTHER_STATEMENT_RE = re.compile(
    r"(?<![a-z])(next|upcoming|future|following|previous|prior|last)\s+(bill|billing|statement)", re.I)


def _dates_in(text: str) -> list:
    """Each full date in `text`, as (where it starts, where it ends,
    YYYY-MM-DD), in order."""
    found = set()
    for pattern, _kind in DATE_PATTERNS:
        for m in pattern.finditer(text or ""):
            iso = parse_date(m.group(0))
            if iso:
                found.add((m.start(), m.end(), iso))
    return sorted(found)


def _labelled_dates(text: str) -> list:
    """Each full date in `text` with the words just before it, back to the
    date before it, as (words, YYYY-MM-DD)."""
    out, last = [], 0
    for start, end, iso in _dates_in(text):
        out.append((text[max(last, start - 40):start], iso))
        last = end
    return out


def _statement_date(name: str, row_text: str, row_flat: str = "") -> Optional[str]:
    """The date of the statement a control fetches, only where the page
    leaves no doubt. Its own words first. None when the row writes another
    statement's date anywhere, the next or a previous one. Then a month its
    words name, as the one date of that month in its row. Then the row's
    one date. Of a row's several dates, only the one written right before as
    the statement's own, "Statement date", "issued", and none when none or
    two are written. Choosing among several dates by where they sit or by
    what they were not filed statements under a due date, a payment's date
    and the next statement's own date, which would have made the real one
    count as saved (reviews of 0.41.0)."""
    own = parse_date(name)
    if own:
        return own
    # The dates are read as the page shows them, from innerText. The pieces
    # with spaces between also hold text the page hides, a collapsed panel's
    # "Bill date 08/12/2026", and split a date React writes in five pieces,
    # so they are read only for what refuses a row (review of 0.41.0).
    dates = _labelled_dates(row_flat or row_text)
    distinct = sorted({iso for _words, iso in dates})
    if not distinct:
        return None
    if _ANOTHER_STATEMENT_RE.search(row_text) or _ANOTHER_STATEMENT_RE.search(row_flat):
        return None
    month = MONTH_YEAR_RE.search(name or "")
    if month:
        want = "%s-%02d" % (month.group(2), _MONTHS[month.group(1)[:3].lower()])
        inside = [iso for iso in distinct if iso.startswith(want)]
        return inside[0] if len(inside) == 1 else None
    if len(distinct) == 1:
        return distinct[0]
    written = {iso for words, iso in dates if _STATEMENT_DATE_RE.search(words)}
    return next(iter(written)) if len(written) == 1 else None


def _statement_controls(page, new_only: bool = False):
    """Each control on the page that fetches one statement or tax form, as
    (position, element, its words, its date, its row's words). Discovery
    and the download find a control the same way, through this.

    With `new_only`, only a control that shows and was not showing before
    a bill's Bill details was pressed (_mark_shown), so a list already on
    the page is never read as that bill's."""
    ctrls = _bill_controls(page)
    for i in range(ctrls.count()):
        el = ctrls.nth(i)
        if new_only:
            try:
                if not el.is_visible() or not el.evaluate(_IS_NEW_JS):
                    continue
            except Exception:
                continue
        marked = _marked(el)
        try:
            name = (el.get_attribute("aria-label") or el.inner_text(timeout=800) or "").strip()
            if marked and not name:
                name = (el.get_attribute("title") or "").strip()
        except Exception:
            continue
        name = re.sub(r"\s+", " ", name)
        # A control the site marks as a statement's PDF is one by the site's
        # own word, and has none of its own to match, so only the guard's
        # check of every word below applies to it.
        if not marked and (not is_safe_control(name) or not BILL_CONTROL_RE.search(name)):
            continue
        try:
            words = el.evaluate(_WORDS_OF_JS) or []
        except Exception:
            continue
        if any(_refused(w) for w in words):
            continue
        if marked:
            try:
                if el.evaluate(_HOLDS_A_CONTROL_JS):
                    continue
            except Exception:
                continue
        try:
            row = el.evaluate(_ROW_OF_JS, {"pattern": BILL_CONTROL_RE.pattern,
                                           "marked": STATEMENT_PDF_SELECTOR}) or {}
        except Exception:
            row = {}
        row_text = str(row.get("text") or "") if isinstance(row, dict) else ""
        row_flat = str(row.get("flat") or "") if isinstance(row, dict) else ""
        if marked and _marked_row_refuses(row_text, row_flat):
            continue
        if (not marked and not _STATEMENT_WORDS_RE.search(name)
                and not _row_names_a_statement(row_text, row_flat)):
            continue
        iso = _statement_date(name, row_text, row_flat)
        if iso:
            yield i, el, name, iso, row_text


def collect_download_docs(page, refused: Optional[list] = None) -> List[RawDoc]:
    """Read every statement and tax document the page offers. Each
    control's own name, or the row it sits in, carries the date.

    Where Billing & Payments lists its bills, each bill's statements are
    behind its Bill details (#45). So each bill that passes the guard and
    can be told from the others is opened in turn, from the page loaded
    afresh, and what is read there carries the account part its own card
    shows, since two bills can each have a statement of the same date. A
    page with no Bill details is read as it shows.

    `refused`, when given, is told in words of ours why a bill's
    statements were left alone, so the run can write it down."""
    bills = _bills(page)
    if not bills:
        return _documents_shown(page, "", set())
    # A statement list already showing beside the bills, before any Bill
    # details is pressed, is never read, since which bill it belongs to
    # cannot be told. A safe miss (review of the Bill details change).
    if refused is not None and any(b.safe and b.account is None for b in bills):
        refused.append("a bill had no account of its own")
    seen: set = set()
    found: list = []
    for account in [b.account for b in bills if b.safe and b.account is not None]:
        said: dict = {}
        view = _open_bill(page, account, said)
        if said.get("refused") and refused is not None:
            refused.append(said["refused"])
        if view is None:
            continue
        listed: list = []
        docs = _documents_shown(page, account, seen, view, listed)
        found.append((account, tuple(listed), docs))
    # Two bills that showed one list, the same statements in the same
    # order, each showed what could be either bill's or both, so neither is
    # kept and a later run tries again (review of the Bill details change).
    lists = [listed for _account, listed, _docs in found]
    out: List[RawDoc] = []
    for _account, listed, docs in found:
        if listed and lists.count(listed) > 1:
            if refused is not None:
                refused.append(SAME_LIST_REASON)
            continue
        out.extend(docs)
    return out


# What the failure file says when two bills showed one list, in words on
# the word list, so a tester's file says plainly which way the page works.
SAME_LIST_REASON = "two bills showed the same statement list"


def _documents_shown(page, account: str, seen: set, view: Optional[str] = None,
                     listed: Optional[list] = None) -> List[RawDoc]:
    """The statements and tax documents the page shows now, each carrying
    `account`, the bill's account part, and none whose account part and
    date are in `seen` already. With `view`, the path a bill's Bill details
    led to, only what that press brought is read, and nothing once the tab
    has left it, after a show-more press or by itself. `listed`, when
    given, is told each statement shown, its date, words, row and link, in
    the page's order, so two bills' lists can be compared."""
    docs: List[RawDoc] = []
    stayed = expand_all(page, view)
    scroll_full_page(page)
    if view is not None and not (stayed and _on_view(page, view)):
        return docs
    for i, el, name, iso, row_text in _statement_controls(page, new_only=view is not None):
        try:
            href = el.get_attribute("href") or ""
        except Exception:
            href = ""
        if listed is not None:
            listed.append((iso, name, row_text, href))
        if (account, iso) in seen:
            continue
        seen.add((account, iso))
        disp = _human_date(iso)
        # A tax form's number only as a number of its own, and tax only as a
        # tax form. Anywhere in a row, a reference number or "Premium tax"
        # made a statement a Tax Document (review of 0.41.0).
        tax = bool(_A_TAX_FORM_RE.search(name + " " + row_text))
        kind_title = "Tax Document" if tax else "Account Statement"
        docs.append(RawDoc(title=f"{kind_title} - {disp}", account=account, date_text=iso,
                           href=href if PDF_HREF_RE.search(href or "") else "",
                           text=f"American Family {kind_title} {disp}", row_index=i,
                           kind="tax" if tax else "statement"))
    return docs


def _control_for(page, iso: str, new_only: bool = False):
    """The control for the document dated `iso`, matched the same way
    discovery found it, or None. With `new_only`, only among what a bill's
    Bill details brought."""
    for _i, el, name, found, _row in _statement_controls(page, new_only=new_only):
        if found == iso:
            return el, name
    return None, ""


# ---------------------------------------------------------------------------
# Bills, each behind its Bill details (#45)
# ---------------------------------------------------------------------------

@dataclass
class Bill:
    """One bill on Billing & Payments. Its Bill details control, held as
    the element itself, so a page that draws another control before it
    between the listing and the press cannot have that one pressed in its
    place. The guard's verdict on it, the account part its own card shows
    and whether the card labels it an account or a policy, and the card's
    words. `part` is None when the card shows two such numbers. `account`
    is the part when the bill can be told from the others, None when it
    cannot, and empty for the one bill of a page whose card shows none."""
    el: object
    safe: bool
    part: Optional[str]
    kind: str
    account: Optional[str]
    card: str = ""


# The words of each element around a Bill details control, the control
# first and then each one around it, out to the widest that holds no other
# Bill details control, no heading of the page and no more than 600
# characters, up to eight levels up. Lines stay apart, since a label and
# its number can each sit on a line of their own.
_CARD_LEVELS_JS = r"""(el, pattern) => {
  const details = new RegExp(pattern, 'i');
  const wordsOf = (c) => (c.getAttribute('aria-label') || c.innerText || '').replace(/\s+/g, ' ').trim();
  const linesOf = (n) => (n.innerText || '').replace(/[^\S\n]+/g, ' ').replace(/ *\n[\n ]*/g, '\n').trim();
  const levels = [linesOf(el)];
  for (let node = el.parentElement, depth = 0; node && depth < 8; node = node.parentElement, depth++) {
    if (node === document.body || node.matches('main, [role=main]') || node.querySelector('h1')) break;
    const another = Array.from(node.querySelectorAll('a, button, [role=button], [role=link]')).some(
      (c) => c !== el && !el.contains(c) && !c.contains(el) && details.test(wordsOf(c)));
    if (another || (node.innerText || '').length > 600) break;
    levels.push(linesOf(node));
  }
  return levels;
}"""

# What a bill's press brought, read around the statement controls that
# were not showing before it. Their nearest common element, and from there
# out to the widest element below the page's main part that holds no other
# bill's Bill details, as its lines, or beside true when the statements
# themselves sit around another bill's Bill details. The control pressed is
# kept in the page as it is pressed (_press_details).
_VIEW_OF_JS = r"""(els, pattern) => {
  const isNew = (e) => !(window.__paperpullShownBefore && window.__paperpullShownBefore.has(e));
  const shown = els.filter(isNew);
  if (!shown.length) return null;
  const details = new RegExp(pattern, 'i');
  const pressed = window.__paperpullPressed;
  const wordsOf = (c) => (c.getAttribute('aria-label') || c.innerText || '').replace(/\s+/g, ' ').trim();
  const another = (n) => Array.from(n.querySelectorAll('a, button, [role=button], [role=link]')).some(
    (c) => !(pressed && (c === pressed || c.contains(pressed) || pressed.contains(c))) && details.test(wordsOf(c)));
  let common = shown[0];
  while (common && !shown.every((e) => common.contains(e))) common = common.parentElement;
  if (!common) return null;
  if (another(common)) return {beside: true, text: ''};
  let region = common;
  for (let node = common.parentElement; node && node !== document.body && !node.matches('main, [role=main]');
       node = node.parentElement) {
    if (another(node)) break;
    region = node;
  }
  const text = (region.innerText || '').replace(/[^\S\n]+/g, ' ').replace(/ *\n[\n ]*/g, '\n').trim();
  return {beside: false, text: text.slice(0, 4000)};
}"""

# Which statement controls show before a bill's Bill details is pressed,
# kept in the page, so only what the press brought counts as that bill's.
# A page loaded since keeps none, and everything on it came after the press.
_MARK_SHOWN_JS = r"""(els) => { window.__paperpullShownBefore = new WeakSet(els); return true; }"""
_IS_NEW_JS = r"""(e) => !(window.__paperpullShownBefore && window.__paperpullShownBefore.has(e))"""
_COUNT_NEW_JS = r"""(els) => els.filter(
  (e) => !(window.__paperpullShownBefore && window.__paperpullShownBefore.has(e))).length"""

# A number a bill's card shows, its billing account or a policy, read for
# the bill's account part. Four digits at least, letters and hyphens
# between them allowed, and never a date, an amount or a year, which change
# from one bill to the next.
_AMOUNT_RE = re.compile(r"[$]\s?\d[\d,]*(?:\.\d+)?|(?<![\d.,])\d[\d,]*\.\d\d(?!\d)")
_YEAR_ALONE_RE = re.compile(r"(?<![A-Za-z0-9-])(?:19|20)\d\d(?![A-Za-z0-9-])")
_NUMBERISH_RE = re.compile(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*")
# The words before a number that make it an account's or a policy's, and
# the words that make it never a bill's own, the bank or card autopay draws
# on, a payment, a phone, a claim or an agent. An autopay bank's "account
# ending in 6789" was read as the bill's own account (review of the Bill
# details change).
_ACCOUNT_WORD_RE = re.compile(r"\b(account|acct)\b", re.I)
_POLICY_WORD_RE = re.compile(r"\bpolic(y|ies)\b", re.I)
_NOT_THE_BILLS_RE = re.compile(
    r"\b(bank|banking|auto\s*-?\s*pay|autopay|checking|savings|routing|phone|telephone|tel|call|fax|"
    r"claims?|agent|cards?|visa|mastercard|payments?|paid|confirmation|reference|ref|transaction)\b", re.I)


def _label_of(text: str, start: int, after: int) -> str:
    """The words just before the number at `start`, back to the start of its
    line and never past `after`, where the number before it ends. When the
    number begins its line, the line above, where a label of its own sits."""
    line = text.rfind("\n", 0, start) + 1
    label = text[max(line, after, start - 40):start]
    if not label.strip() and line - 1 > after:
        above = text.rfind("\n", 0, line - 1) + 1
        label = text[max(above, after, line - 41):line - 1]
    return label


def _numbers_in(text: str) -> list:
    """Each number of four digits or more the words show, as (what the words
    just before it call it, "account", "policy" or "", its digits). Never a
    date, an amount or a year, and never a number those words tie to a
    bank, autopay, a card, a payment, a phone, a claim or an agent. A date,
    an amount or a year ends the words before it, so "Payment due
    10/01/2026 Billing account 9900123401" labels the account and not a
    payment."""
    for pattern, _kind in DATE_PATTERNS:
        text = pattern.sub("\n", text)
    text = MONTH_YEAR_RE.sub("\n", text)
    text = _AMOUNT_RE.sub("\n", text)
    text = _YEAR_ALONE_RE.sub("\n", text)
    found, after = [], 0
    for m in _NUMBERISH_RE.finditer(text):
        digits = re.sub(r"\D", "", m.group())
        if len(digits) < 4:
            continue
        label = _label_of(text, m.start(), after)
        after = m.end()
        if _NOT_THE_BILLS_RE.search(label):
            continue
        kind = ("account" if _ACCOUNT_WORD_RE.search(label)
                else "policy" if _POLICY_WORD_RE.search(label) else "")
        found.append((kind, digits))
    return found


# Which number a card labels says which bill it is, its billing account
# first, since that is what tells two bills apart, and its policy only
# when it labels no account.
_KINDS_IN_ORDER = ("account", "policy")


def _account_of(levels) -> Tuple[Optional[str], str]:
    """A bill's account part, read from the words its own card shows, and
    what labels it, "account" or "policy". `levels` are the words of each
    element around the Bill details control, narrowest first. The narrowest
    whose words label a number an account or a policy is the card, so a
    paid bill's card drawn beside this one, with no Bill details of its
    own, is never read as this bill's (review of the Bill details change).
    Its one account number gives "..." and the number's last four digits,
    or its one policy number when it labels no account. Two different
    numbers of the kind used give None and that kind, since which is the
    bill's own cannot be told. ("", "") when no element labels one."""
    for text in levels or []:
        found = _numbers_in(str(text or ""))
        for kind in _KINDS_IN_ORDER:
            numbers = {digits for k, digits in found if k == kind}
            if len(numbers) == 1:
                return "..." + numbers.pop()[-4:], kind
            if numbers:
                return None, kind
    return "", ""


def _details_controls(page):
    """Every control on the page that shows and whose whole words are Bill
    details."""
    return _controls_named(page, BILL_DETAILS_RE).filter(visible=True)


# The most Bill details controls read on one page.
_MOST_BILLS = 30


def _read_details(el) -> tuple:
    """What a Bill details control reads as, (whether it is safe, the
    account part its card shows, what labels that part, the card's words).
    Safe when its whole words are Bill details, every word it shows or
    announces passes the guard and it holds no other control. Raises when
    the control cannot be read."""
    name = re.sub(r"\s+", " ", el.get_attribute("aria-label") or el.inner_text() or "").strip()
    words = el.evaluate(_WORDS_OF_JS) or []
    holds = el.evaluate(_HOLDS_A_CONTROL_JS)
    levels = [str(t or "") for t in (el.evaluate(_CARD_LEVELS_JS, BILL_DETAILS_RE.pattern) or [])]
    safe = bool(BILL_DETAILS_RE.match(name)) and not holds and not any(_refused(w) for w in words)
    part, kind = _account_of(levels)
    return safe, part, kind, (levels[-1] if levels else "")


def _bills(page) -> list:
    """Each bill Billing & Payments shows, in the page's order, its control
    held as the element itself. Bills whose cards show the same account
    part, a card that shows two, or a bill of several whose card shows
    none, get None, since which bill a statement belongs to could not be
    told. When any control could not be read, or there are more than are
    read, no bill is told from another."""
    bills: list = []
    try:
        ctrls = _details_controls(page)
        n = ctrls.count()
    except Exception:
        return bills
    unread = n > _MOST_BILLS
    for i in range(min(n, _MOST_BILLS)):
        try:
            el = ctrls.nth(i).element_handle(timeout=2000)
            safe, part, kind, card = _read_details(el)
        except Exception:
            unread = True
            continue
        bills.append(Bill(el=el, safe=safe, part=part, kind=kind, account=part, card=card))
    counted: dict = {}
    for bill in bills:
        counted[bill.part] = counted.get(bill.part, 0) + 1
    for bill in bills:
        if (unread or bill.part is None or counted[bill.part] > 1
                or (not bill.part and len(bills) > 1)):
            bill.account = None
    return bills


def _still_the_bill(bill) -> bool:
    """Whether the element `bill` holds reads as it did when the bills were
    listed, read again just before it is pressed. A page that changed a
    control's words or its card in between has it left alone (review of
    the Bill details change)."""
    try:
        safe, part, kind, _card = _read_details(bill.el)
    except Exception:
        return False
    return safe and bill.safe and (part, kind) == (bill.part, bill.kind)


def _words_pass(el) -> bool:
    """Whether every word a control shows or announces passes the guard and
    it holds no other control. False when it could not be read."""
    try:
        words = el.evaluate(_WORDS_OF_JS) or []
        holds = el.evaluate(_HOLDS_A_CONTROL_JS)
    except Exception:
        return False
    return not holds and not any(_refused(w) for w in words)


def _address_words(url: str) -> str:
    """The words of an address's path, query and fragment, with a word
    written into the next split from it, autoPay as auto Pay, for the
    guard."""
    try:
        parts = urlsplit(url or "")
    except ValueError:
        return ""
    raw = unquote(" ".join((parts.path, parts.query, parts.fragment)))
    raw = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", raw)
    return re.sub(r"[^A-Za-z0-9]+", " ", raw).strip()


def _bill_view_allowed(page) -> bool:
    """Whether the tab may be read for a bill's statements. On My Account's
    own host and signed in, at an address none of whose words the guard
    refuses, so /billing/autopay, and any payment, autopay or settings
    route, is never read."""
    url = page.url or ""
    try:
        here, home = urlsplit(url), urlsplit(BILLING_URL)
    except ValueError:
        return False
    if not is_safe_url(url) or here.netloc != home.netloc or looks_signed_out(page):
        return False
    return not _refused(_address_words(url))


def _on_view(page, view: Optional[str]) -> bool:
    """Whether the tab is still at the path a bill's statements showed at,
    and still allowed there."""
    try:
        here = urlsplit(page.url or "").path.rstrip("/")
    except ValueError:
        return False
    return here == (view or "").rstrip("/") and _bill_view_allowed(page)


def _mark_shown(page) -> bool:
    """Keep in the page which statement controls show now. False when the
    page could not be asked, and nothing is pressed then."""
    try:
        return bool(_bill_controls(page).filter(visible=True).evaluate_all(_MARK_SHOWN_JS))
    except Exception:
        return False


def _new_shown(page) -> int:
    """How many statement controls show that were not showing when
    _mark_shown asked."""
    try:
        return int(_bill_controls(page).filter(visible=True).evaluate_all(_COUNT_NEW_JS) or 0)
    except Exception:
        return 0


# How long a bill's statements are given to show after its Bill details is
# pressed, in seconds by the clock, since the page may ask for them first.
_LIST_SECONDS = 20
# How long the count of a bill's statements has to hold still before they
# are read, in seconds by the clock. A list drawn in two passes 300 ms
# apart was read after the first, and its later statements were not found
# (review of the Bill details change).
_STEADY_SECONDS = 1.0


def _settle_list(page, most: float = 10.0) -> Optional[int]:
    """Wait until as many statement controls that were not showing before
    the press show for a whole _STEADY_SECONDS. Their count, or None when
    it never held still in about `most` seconds."""
    started = time.monotonic()
    last, since = -1, started
    while True:
        shown = _new_shown(page)
        now = time.monotonic()
        if shown != last:
            last, since = shown, now
        if now - since >= _STEADY_SECONDS:
            return shown
        if now - started >= most:
            return None
        page.wait_for_timeout(250)


def _view_refusal(page, bill) -> Optional[str]:
    """Why the statements a bill's press brought are not tied to that bill,
    in words of ours, or None. Statements drawn around another bill's Bill
    details could be that bill's, and a view that labels an account or a
    policy with other last four digits than this bill's card shows is
    another bill's (review of the Bill details change)."""
    try:
        found = _bill_controls(page).filter(visible=True).evaluate_all(
            _VIEW_OF_JS, BILL_DETAILS_RE.pattern)
    except Exception:
        found = None
    if not isinstance(found, dict):
        return "the statements could not be read"
    if found.get("beside"):
        return "the statements showed beside another bill"
    if bill.part and bill.kind:
        for kind, digits in _numbers_in(str(found.get("text") or "")):
            if kind == bill.kind and digits[-4:] != bill.part[-4:]:
                return "a bill showed another account"
    return None


def _press_details(page, bill, report: Optional[dict] = None) -> Optional[str]:
    """Press one bill's Bill details and wait up to about twenty seconds for
    its statements, then until their count holds still. The path of the
    view they show at, Billing & Payments itself or the one route the press
    led to, or None.

    A control the guard refused, one with another control where the press
    would land, or one that no longer reads as it did when the bills were
    listed, is not pressed. A press that leads off My Account or to an
    address whose words the guard refuses, such as /billing/autopay, that
    shows no statement, or whose statements are not tied to this bill
    (_view_refusal), gives None, and the tab is loaded at Billing &
    Payments again. Only statements that were not showing before the press
    count. A tab the press opened is closed. `report`, when given, is told
    where the press led, how many statements showed, how many seconds they
    took and why they were refused, for Diagnose and for the run."""
    if not bill.safe:
        return None
    el = bill.el
    ctx = page.context
    before = set(ctx.pages)
    lands = False
    for attempt in range(2):
        if attempt:
            # A banner drawn over the button, closed the way any overlay is.
            dismiss_overlay(page)
        try:
            el.scroll_into_view_if_needed(timeout=4000)
        except Exception:
            pass
        try:
            lands = bool(el.evaluate(_CENTER_JS))
        except Exception:
            lands = False
        if lands:
            break
    if not lands:
        log.info("another control sits where the Bill details press would land")
        return None
    if not _mark_shown(page):
        return None
    try:
        el.evaluate("(e) => { window.__paperpullPressed = e; return true; }")
    except Exception:
        return None
    # The element itself, read once more as it is about to be pressed.
    if not _still_the_bill(bill):
        log.info("the Bill details control no longer reads as it did, so it is not pressed")
        return None
    blob_capture.arm(page)
    armed_at = set(ctx.pages)
    started = time.monotonic()
    view = None
    try:
        try:
            el.click(timeout=8000)
        except Exception as e:
            log.info("the Bill details press failed with %s", e)
            return None
        if report is not None:
            report["pressed"] = True
        while True:
            allowed = _bill_view_allowed(page)
            shown = _new_shown(page) if allowed else 0
            if not allowed or shown or time.monotonic() - started >= _LIST_SECONDS:
                break
            page.wait_for_timeout(250)
        appeared = time.monotonic() - started
        if allowed and shown:
            shown = _settle_list(page) or 0
        here = urlsplit(page.url or "").path
        refusal = _view_refusal(page, bill) if allowed and shown else None
        # Where the statements were read is where the tab still is, checked
        # once they have been read.
        allowed = allowed and _on_view(page, here)
        if report is not None:
            report["address"] = redact(page.url or "")
            report["statement_links"] = shown
            report["seconds_until_links"] = int(round(appeared)) if shown else None
            if refusal:
                report["refused"] = refusal
        if not allowed:
            log.info("Bill details led somewhere the guard refuses, so nothing there is read")
        elif not shown:
            log.info("no statement showed and held still within %d s of Bill details", _LIST_SECONDS)
        elif refusal:
            log.info("the statements Bill details brought are left alone, %s", refusal)
        else:
            view = here
        return view
    finally:
        blob_capture.close_new_tabs(page, before, armed_at)
        if view is None:
            _leave_the_press(page)


def _open_bill(page, account: str, report: Optional[dict] = None) -> Optional[str]:
    """Open the details of the bill whose own card shows `account`, from
    Billing & Payments loaded afresh, so nothing an earlier press opened is
    still showing. The path its statements show at, or None when the page
    did not load, no single bill shows that account part, its control is
    refused or its statements are not tied to it. `report` as for
    _press_details."""
    if not _load_billing(page):
        return None
    bills = _bills(page)
    mine = [b for b in bills if b.account == account and b.safe]
    if len(mine) != 1:
        log.info("no single bill that passes the guard shows that account part")
        return None
    return _press_details(page, mine[0], report)


def survey_bills(page) -> list:
    """What each bill's Bill details does, for Diagnose. Each one that
    passes the guard is pressed from Billing & Payments loaded afresh, and
    where it led, how many statements showed and how many seconds they
    took are noted, with whether the bill's account part could be read and
    its card's words. Nothing on the statements is pressed and nothing is
    saved."""
    out: list = []
    if not _load_billing(page):
        return out
    listed = _bills(page)
    for n, bill in enumerate(listed):
        entry = {"safe": bill.safe, "identity_read": bool(bill.account), "identity_kind": bill.kind,
                 "pressed": False, "card": " | ".join(bill.card.splitlines())[:200]}
        out.append(entry)
        if not bill.safe:
            continue
        if n and not _load_billing(page):
            continue
        again = _bills(page)
        if len(again) == len(listed) and again[n].safe:
            _press_details(page, again[n], entry)
    return out


def _fetch_pdf(page, href: str, zip_ok: bool = False) -> Optional[bytes]:
    """A PDF link fetched from inside the signed-in page, cookies and all.
    The fetching is the core's, the hosts are this app's."""
    return _core_fetch_pdf(page, href, is_safe_url, zip_ok=zip_ok)


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


def _catch_pdf(page, el, label: str, out_path: Path, trace: Optional[list] = None,
               dl_dir=None) -> bool:
    """Click `el` and save whatever PDF the site produces, a file landing
    in `dl_dir`, a download event, a PDF response, a new tab, this tab
    moving to the document, or a second control the click revealed.
    `trace` collects what happened, the click's own outcome included."""
    ctx = page.context
    got: dict = {}
    downloads: list = []
    start_url = page.url or ""

    def on_download(dl):
        downloads.append(dl)

    def on_response(res):
        try:
            url = res.url or ""
            if not is_safe_url(url):
                return
            ct = (res.headers.get("content-type") or "").lower()
            if trace is not None and ("json" in ct or "pdf" in ct or "octet" in ct or "zip" in ct):
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

    ctx.on("response", on_response)
    page.on("download", on_download)
    before = set(ctx.pages)
    seen = _snapshot(dl_dir)
    controls_before = _control_texts(page)
    # RECORDED (#45). A statement opens in a new tab at a blob: address the
    # page made, and a page can revoke that address as soon as the tab has
    # it, after which it cannot be read back. So every PDF blob the page
    # makes from here on is kept as it is made.
    blob_capture.arm(page)
    armed_at = set(ctx.pages)

    def landed() -> bool:
        # Pointed at a folder, the browser can save the only copy there and
        # leave the event's own file empty, so that file is taken rather than
        # the document asked for a second time (capture.take_download).
        if downloads and _take_download(downloads[0], dl_dir, seen, out_path, zip_ok=True):
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
        if _take_new_pdf(dl_dir, seen, out_path, zip_ok=True):
            return True
        # Only the one PDF blob this press opened in a new tab, by the tab's
        # address or by the page's own asking to open it. The newest PDF the
        # page made could be another document the same press made, or a late
        # one from an earlier press (review of 0.41.0).
        shown = [p.url for p in ctx.pages if p not in before and (p.url or "").startswith("blob:")]
        kept = blob_capture.take(page, urls=shown, opened=True)
        if kept:
            out_path.write_bytes(kept[0])
            if trace is not None:
                trace.append({"note": "the page made the PDF itself, a blob it opened"})
            return True
        return False

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
        try:
            if not el.evaluate(_CENTER_JS):
                if trace is not None:
                    trace.append({"note": "another control sits where the press would land",
                                  "control": redact(label)[:60]})
                return False
        except Exception:
            return False
        try:
            el.click(timeout=8000)
            if trace is not None:
                trace.append({"note": "clicked", "control": redact(label)[:60]})
        except Exception as e:
            if trace is not None:
                trace.append({"note": "click failed", "control": redact(label)[:60], "error": str(e)[:160]})
            try:
                el.evaluate("el => el.click()")
                if trace is not None:
                    trace.append({"note": "clicked through the DOM instead", "control": redact(label)[:60]})
            except Exception as e2:
                if trace is not None:
                    trace.append({"note": "DOM click failed too", "error": str(e2)[:160]})
        if wait_for_pdf(10):
            return True
        if _take_same_tab(page, start_url, out_path, trace):
            return True
        if _take_new_tab(page, [p for p in ctx.pages if p not in before], out_path):
            return True
        appeared = _control_texts(page) - controls_before
        if trace is not None:
            trace.append({"note": "after the click", "url": redact(page.url or "")[:160],
                          "appeared": [redact(t) for t in sorted(appeared)[:15]],
                          "new_tabs": len([p for p in ctx.pages if p not in before])})
        step, step_label = _second_step(page, appeared)
        if step is not None:
            blob_capture.arm(page)
            armed_at = set(ctx.pages)
            try:
                step.click(timeout=8000)
                if trace is not None:
                    trace.append({"note": "second step clicked", "control": redact(step_label)[:60]})
            except Exception as e:
                if trace is not None:
                    trace.append({"note": "second step click failed", "control": redact(step_label)[:60],
                                  "error": str(e)[:160]})
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
        # The statement is taken from the page the moment the page asks for
        # its tab, and on a busy machine Playwright heard of that tab only
        # after this press had closed the ones it knew of, so it stayed
        # open. A tab the page asked for is waited for before closing.
        blob_capture.close_new_tabs(page, before, armed_at)
        # What the browser saved into the folder while the document came
        # some other way, read off the answer or asked for again, goes when
        # it is an exact copy of the one saved (capture.clear_copies).
        try:
            _clear_copies(dl_dir, seen, out_path)
        except Exception:
            pass


def download_bill(page, dl_dir, iso_date: str, out_path, title: str = "",
                  trace: Optional[list] = None, account: str = "") -> bool:
    """Save the document dated `iso_date`. A PDF link on the row is fetched
    from inside the page. Otherwise the row's own control is clicked, once
    it has passed the guard, and whichever the site produces is caught, a
    download event or a PDF response, in this tab or one it opens.

    `account` is the account part of the bill the document was found
    under. Where Billing & Payments lists bills, that bill's Bill details
    is opened first, from the page loaded afresh, and the document is taken
    only from what it brought. A document found under a bill is never taken
    from a page that shows none.

    `dl_dir` is where the attached browser saves a download, watched
    after every click."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if not goto_documents(page):
        log.info("could not open the documents page for %s", iso_date)
        return False
    view = None
    if account or _bills(page):
        view = _open_bill(page, account)
        if view is None:
            log.info("could not open the details of the bill for %s", iso_date)
            return False
    stayed = expand_all(page, view)
    if view is not None:
        # The bill's statements only, where its press showed them, and once
        # their count holds still, the way discovery read them.
        if not (stayed and _on_view(page, view)):
            log.info("the tab left the bill's statements before %s was found", iso_date)
            return False
        if _settle_list(page) is None:
            log.info("the bill's statements never held still")
            return False

    el, label = _control_for(page, iso_date, new_only=view is not None)
    if el is None:
        log.info("no document control found for %s", iso_date)
        return False
    if not _safe_to_press(el, label):
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
                              "url": redact(target)[:160]})
    ok = _catch_pdf(page, el, label, out_path, trace, dl_dir)
    if not ok:
        _leave_the_press(page, view)
    return ok


def _leave_the_press(page, view: Optional[str] = None) -> None:
    """Load Billing & Payments again after a press that brought no PDF. The
    page makes each statement itself, and one that came after the app had
    given up on its press was opened inside the next press's wait and taken
    for the next statement. Loading the page again ends whatever the press
    left running (review of 0.41.0).

    `view` is the path a bill's statements showed at. Billing & Payments is
    loaded whether or not the press took the tab off it, since the next
    document opens its bill again from there, and a press that did is
    noted."""
    if view is not None and not _on_view(page, view):
        log.info("the press took the tab off the bill's statements")
    try:
        page.goto(BILLING_URL, wait_until="domcontentloaded", timeout=60000)
    except Exception as e:
        log.info("loading billing again after a press failed: %s", e)
        try:
            page.goto("about:blank")
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Diagnose. A survey a tester can attach to an issue. No screenshot, since a
# signed-in page shows names, numbers and amounts. Digit runs are masked and
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
    r"^\s*((see|view|show)\s+)?(documents?|policy\s+documents?|my\s+documents|statements?|"
    r"billing(\s+(and|&)\s+payments?)?|bills?|billing\s+history|payment\s+history|"
    r"id\s+cards?|insurance\s+cards?|policies|my\s+policies|declarations?)\s*$", re.I)


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
    guard's verdict on each, and every JSON or PDF response amfam.com sends
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
ALLOWED_HOSTS = {"amfam.com"}


def is_safe_url(url: str) -> bool:
    """True only for an https URL on one of this provider's own hosts.

    The check itself lives in the core, so all of them answer the same way.
    This app keeps the hosts, which is the part that really is its own."""
    return _host_allows(url, ALLOWED_HOSTS)
