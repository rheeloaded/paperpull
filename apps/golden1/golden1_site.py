"""ALL golden1.com selectors, URLs, and page behavior live here.

When Golden 1 changes its site, repair this file only.

STATUS: CONFIRMED on the tester's account (#35). Written without a Golden
1 account and repaired from the surveys, failure files and a recording one
tester sent. Discover reads every page of every account's statement
history, a card's included, and on his two accounts every statement
downloaded, the card's named Credit Card Statement. On a first run it is
deliberately cautious.

  * --login opens a real Edge or Chrome, since a credit union's sign-in is happiest in a real browser.
  * --diagnose surveys whatever the documents page turns out to be,
    records its headings, its controls with the guard's verdict on each,
    and the shape of every JSON response, with digit runs masked, and
    takes no screenshot. That file is what a tester attaches to the
    GitHub issue.
  * --discover reads dates from any control that looks like a
    statement or tax form, wherever it sits on the page.
  * --pilot tries to save the newest few, by fetching a PDF link the row
    carries from inside the page, or by clicking the row's own control
    and catching a download event, a PDF response or a new tab.

The guesses that most need confirming from a survey are marked GUESS.
The routes are the biggest one.

SAFETY (this is a bank account that can move money):
  This module is strictly READ-ONLY. It opens eStatements, reads the
  list, and saves the PDFs Golden 1 already generated. It must NEVER
  activate any control that transfers, pays, sends money by Zelle,
  wires, deposits, opens or closes an account, changes a limit or an
  address, or edits any setting.
  FORBIDDEN_CONTROL_RE is the guard. A control must ALSO look like a
  document action (SAFE_DOC_CONTROL_RE) before it may be clicked. There
  is no code here that submits a form or confirms a dialog.
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

log = logging.getLogger("golden1_docs.site")


def _words():
    """This app's own words for paperpull_core.words, from what its source
    calls it, for saying what covered a control."""
    return _words_for("Golden 1", sys.modules[__name__])


BASE = "https://digitalbanking.golden1.com"
# From the first survey (#35, 2026-09-21). Sign-in is at
# login.golden1.com/login/?realm=/alpha and lands on digitalbanking
# .golden1.com/accounts/overview. The documents page is
# /accounts/documents, whose "View Documents" button signs the person on
# to the credit union's document vendor, ebank.hepsiian.com, in a new
# tab. The statements themselves are listed there, which is why that
# host is in the allowlist and why discovery and download work in that
# tab once it is open. Documents are kept for seven years.
BILLING_CANDIDATES = [
    f"{BASE}/accounts/documents",
    f"{BASE}/accounts/overview",
]
VENDOR_HOSTS = ("hepsiian.com",)
# The bank's own site. It lists no statements, only the button that
# signs on to the vendor, which every survey and the recording agree on.
BANK_DOMAIN = "golden1.com"
# Round four (#35). The third survey pressed "View documents", the
# sidebar LINK, because the button and the link share a name and the
# link came first, so it landed on the documents page again and the
# vendor was never opened. The button is taken first now. And since the
# vendor's real host has still not been seen, a tab the bank's own
# button opens is read as the vendor's tab whatever host it is on, its
# host is recorded, and that host is allowed for that run's fetches.
# Every click on that tab still goes through the guard.
_VENDOR_HOSTS_SEEN: set = set()
# The button's text, with room for an icon's word after it. The second
# survey listed the button as "View Documents" and yet did not match it
# on the exact form, so the match is on the start of the text.
VENDOR_BUTTON_RE = re.compile(r"^\s*view\s+documents\b", re.I)
BILLING_URL = BILLING_CANDIDATES[0]
URLS = {
    "home": f"{BASE}/accounts/overview",
    "login": "https://login.golden1.com/login/?realm=/alpha#/",
    "documents": BILLING_URL,
    "statements": BILLING_URL,
}

LOGIN_URL_MARKERS = ["/login", "/signin", "/sign-in", "/auth/", "/mfa",
                     "/verification", "/challenge", "/authenticate"]

# ---------------------------------------------------------------------------
# HARD SAFETY GUARD. Tuned for credit union, on top of the bank words. Never move
# money, never change service or coverage, never change a setting.
# ---------------------------------------------------------------------------
FORBIDDEN_CONTROL_RE = re.compile(
    r"(transfer|zelle|\bwire\b|\bpay\b|payment|bill\s*pay|autopay|auto\s*pay|"
    r"deposit|withdraw|send\s+money|request\s+money|move\s+money|"
    r"\bapply\b|open\s+(an?\s+)?account|close\s+account|\bloan\b|\bborrow|"
    # A card statement is a document, round six saves the card's, and every
    # other card control, lock, replace, activate and the rest, is still
    # refused by its own verb or by the bare noun.
    r"\bcards?\b(?!\s+statements?\b)|replace|activate|lock|unlock|\bpin\b|limit|"
    r"overdraft|alerts?\b|\bbudget|\bgoal|\brewards?\b|\boffers?\b|"
    r"enroll|unenroll|sign\s+up|paperless|delivery\s+preference|"
    r"enable|disable|change\b|\bedit\b|update\b|modify|manage\b|"
    r"set\s+up|delete|remove|cancel|dispute|"
    r"password|passcode|username|profile\b|settings|preferences|contact\s+info|\baddress\b|"
    r"confirm\b|submit|agree|accept|authorize|\bchat\b|contact\s+us|"
    r"beneficiar|nickname|order\s+checks|stop\s+payment)", re.I)

SAFE_DOC_CONTROL_RE = re.compile(
    r"(download|view|open|print|\bpdf\b|statement|document|\bletter\b|notice|"
    r"1099|1098|5498|tax\s+(form|document)|history|"
    r"e-?statements?|see\s+(more|all|older)|show\s+(more|all|older)|load\s+more)", re.I)

# A control whose whole label is a date. On the vendor's Statement
# History that is what a statement is called, and nothing else.
#
# A recording caught this. The member pressed a link whose whole label was
# the statement's date, and the step came back guard_allows false, so the
# app would have refused to press the one control that fetches the
# document. Nothing destructive can be labeled with only a date, and
# the forbidden words are still checked first (#35).
DATE_ONLY_CONTROL_RE = re.compile(
    r"^\s*(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2}|"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4})\s*$",
    re.I)

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
    from urllib.parse import parse_qsl
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
    if DATE_ONLY_CONTROL_RE.match(name):
        return True
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
    """Every control that fetches a document, including one whose whole
    label is a date, which is what the vendor's Statement History calls a
    statement (#35)."""
    named = _controls_named(page, BILL_CONTROL_RE)
    dated = _controls_named(page, DATE_ONLY_CONTROL_RE)
    try:
        if dated.count():
            return named.or_(dated)
    except Exception:
        pass
    return named


def _bill_controls_by_name_only(page):
    """Every control on the page whose name says it fetches a document.
    The words are this provider's, the rest is the core's."""
    return _controls_named(page, BILL_CONTROL_RE)


def _dated_count(page) -> int:
    """How many controls on the page are named by nothing but a date."""
    try:
        return _controls_named(page, DATE_ONLY_CONTROL_RE).count()
    except Exception:
        return 0


def _all_dates(text: str) -> set:
    """Every distinct day the text names, in any form parse_date reads."""
    out = set()
    for pattern, kind in DATE_PATTERNS:
        for m in pattern.finditer(text or ""):
            got = parse_date(m.group(0))
            if got:
                out.add(got)
    return out


def _date_of_control(el, name: str, list_shown: bool) -> Tuple[Optional[str], str]:
    """The one date a document control belongs to, and where it came from.

    The label comes first, and on the vendor's list the label is the
    statement date itself. A control with no date of its own, such as
    View PDF, is not read at all while the page lists dated statements,
    since that list already names every statement once. Only on a page
    with no such list is the date taken from the row, and then only when
    the row names exactly one day.

    A pilot on 0.34.1 wanted a statement dated by a day that was not a
    month end while the vendor's list ran back by month ends. That date
    came from the text around a dateless control, where the first date
    found is whatever the page prints near it, and it named no statement
    the vendor offers (#35). The request census of the next pilot showed
    discovery never reached the vendor, so that control was almost
    certainly on the bank's own documents page. Only a tab this run
    opened through the bank's button is read for statements now (see
    collect_download_docs)."""
    iso = parse_date(name)
    if iso:
        return iso, "label"
    if list_shown:
        return None, "no date of its own beside a dated list"
    try:
        row_text = el.evaluate(_ROW_OF_JS) or ""
    except Exception:
        row_text = ""
    days = _all_dates(row_text)
    if len(days) == 1:
        return next(iter(days)), "row"
    return None, ("no date near it" if not days else "more than one date near it")


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
    return bool(re.search(r"statements?\s+(and|&)\s+documents|e-?statements|statement\s+(period|date)|tax\s+(documents|forms)",
                          body, re.I))


# How long a page loaded by address is given before it is looked at.
GOTO_WAIT_MS = 5000


def goto_documents(page) -> bool:
    """Open Statements & Documents. The first candidate that is not a
    sign-in page and shows something statement-shaped wins, and the URL it
    lands on is remembered so a later call does not walk the list again.

    Only a page on the bank's own site is taken as it is. The vendor's
    tab is on an allowed host too and lists statements, but the bank's
    documents page is where the run starts from, and a vendor tab an
    earlier run left open would otherwise pass for it (#35).

    A page loaded here is noted as just arrived, so its View Documents
    button waits for the member's accounts to answer (see
    _press_when_ready)."""
    global BILLING_URL
    dismiss_overlay(page)
    if on_bank_host(page.url or "") and not looks_signed_out(page) and _looks_like_billing(page):
        return True
    for url in [BILLING_URL] + [u for u in BILLING_CANDIDATES if u != BILLING_URL]:
        try:
            _arriving(page)
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(GOTO_WAIT_MS)
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
    # "label" when the control's own name is the date, "row" when it was
    # read from the one date around it. The orchestrator trusts a list
    # read from labels enough to retire what is no longer on it (#35).
    dated_by: str = ""
    # The title and account this statement was saved under before its panel
    # was read as the other kind, when that happened, so its record is
    # carried to the new ones rather than the statement listed again (#35).
    legacy_title: str = ""
    legacy_account: str = ""


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


def _on_vendor_host(url: str) -> bool:
    """True for an address on a known vendor host or on the host the
    bank's button opened this run."""
    hosts = set(VENDOR_HOSTS) | _VENDOR_HOSTS_SEEN
    try:
        host = (urlsplit(url or "").hostname or "").lower()
    except ValueError:
        return False
    return bool(host) and any(host == h or host.endswith("." + h) for h in hosts)


def _vendor_tab(page):
    """The document vendor's tab, if one is open, on a known vendor host
    or on the host the bank's button opened this run."""
    for p in page.context.pages:
        try:
            if p is page or p.is_closed():
                continue
            if _on_vendor_host(p.url or ""):
                return p
        except Exception:
            continue
    return None


# The vendor tabs this run opened itself, newest last. A vendor tab an
# earlier run left open still shows the list it was given, long after
# the vendor's session behind it has ended, so reading it would queue
# statements that every capture then fails to fetch. Only a tab opened
# by this run's own press of the bank's button is read (#35).
_ADOPTED_TABS: list = []


def _vendor_tab_this_run(page):
    """The newest vendor tab this run opened that is still open and still
    on the vendor, or None."""
    for p in reversed(_ADOPTED_TABS):
        try:
            if p is page or p.is_closed():
                continue
            if _on_vendor_host(p.url or ""):
                return p
        except Exception:
            continue
    return None


def on_bank_host(url: str) -> bool:
    """True only for an https address on the bank's own site. is_safe_url
    admits the vendor's host as well, and the vendor is not the bank."""
    try:
        parts = urlsplit(url or "")
        host = (parts.hostname or "").lower()
    except ValueError:
        return False
    return parts.scheme == "https" and (host == BANK_DOMAIN or host.endswith("." + BANK_DOMAIN))


def _still_at_the_bank(page) -> bool:
    """The tab is on an https page of the bank's own site and not signed
    out. Checked right before the documents page's button is pressed,
    since the sidebar link, or the page itself while it loads, may have
    taken the tab anywhere.

    Those two are what this relies on. detect_security_challenge is asked
    as well, but it answers None on any page still showing a document
    control, and the sidebar link is one, so it catches only a challenge
    that replaces the whole page. One drawn over the page is left to the
    click, which is never forced and so does not go through a dialog
    covering the button."""
    try:
        return (on_bank_host(page.url or "") and not looks_signed_out(page)
                and detect_security_challenge(page) is None)
    except Exception:
        return False


def _vendor_button(page):
    """The "View Documents" BUTTON on the documents page, and only when
    there is no button, the link of the same name."""
    btn = page.get_by_role("button", name=VENDOR_BUTTON_RE)
    if btn.count():
        return btn
    return page.get_by_role("link", name=VENDOR_BUTTON_RE)


def _adopt_new_tab(page, tabs_before: set):
    """A tab the bank's own button opened, adopted as the vendor's tab.
    Its host is remembered for this run so the app can read and fetch
    there. Anything that is not https is closed unread.

    A tab that never leaves the bank's own site is not the vendor's. Once
    taken for it, a bank host joined the vendor's hosts for the run, so
    the bank's own tab could pass for the vendor's, and a trace said the
    vendor's tab had not opened when one had. It is closed, and the trace
    says it stayed at the bank (#35).

    A tab that closes before it is looked at leaves nothing to adopt, and
    the trace says so rather than keeping the reason an earlier try gave.

    Only one tab is adopted. Any other the press opened is closed unread.
    The look stopped at the tab it adopted, so another tab from the same
    press was never looked at and stayed open in the member's browser."""
    _said(TAB_GONE)
    adopted = None
    try:
        for extra in [p for p in page.context.pages if p not in tabs_before]:
            try:
                extra.wait_for_load_state("domcontentloaded", timeout=20000)
            except Exception:
                pass
            for _ in range(ADOPT_WAIT_POLLS):
                u = extra.url or ""
                if u and u != "about:blank" and not on_bank_host(u):
                    break
                extra.wait_for_timeout(500)
            u = extra.url or ""
            host = (urlsplit(u).hostname or "").lower()
            if on_bank_host(u):
                log.info("a tab opened and stayed on the bank's own site, so it is not the vendor's")
                _said(STAYED_AT_THE_BANK)
            elif u.startswith("https://") and host:
                _VENDOR_HOSTS_SEEN.add(host)
                ALLOWED_HOSTS.add(host)
                _ADOPTED_TABS.append(extra)
                log.info("the vendor's tab is on %s", redact(host))
                _said(OPENED)
                adopted = extra
                break
            else:
                _said(NOT_HTTPS)
            try:
                extra.close()
            except Exception:
                pass
    finally:
        # However the look ended, also when a tab that closed itself while
        # it was waited for made the look raise.
        try:
            others = [p for p in page.context.pages
                      if p not in tabs_before and p is not adopted]
        except Exception:
            others = []
        for extra in others:
            try:
                extra.close()
            except Exception:
                pass
    return adopted


def _close_old_vendor_tabs(page) -> int:
    """Close the statements tabs still open that this run will not read,
    just before the button is pressed for a fresh one, and say how many.

    A tab an earlier run left open still shows its list after the session
    behind it has ended, so it is never read (see _vendor_tab_this_run).
    Leaving it open is not harmless either. A bank that opens its vendor
    into a NAMED window sends the new sign-on into an open tab of that
    name instead of a new one, so the press opens no tab and discovery
    finds nothing. With the old tab closed first, the press has to open a
    new one, and only a new one is ever adopted (#35).

    Only a tab on the vendor's site, or one this run opened, is closed.
    Never the tab the run works in and never a page of the bank's."""
    closed = 0
    for p in list(page.context.pages):
        if p is page:
            continue
        try:
            if p.is_closed() or on_bank_host(p.url or ""):
                continue
            if _on_vendor_host(p.url or "") or any(p is a for a in _ADOPTED_TABS):
                p.close()
                closed += 1
        except Exception:
            continue
    if closed:
        log.info("closed %d statements tab(s) this run will not read", closed)
    return closed


# How long a press waits for the tab it opens, in half seconds.
TAB_WAIT_POLLS = 30
# How long a tab the button opened gets to leave the bank's own site for
# the vendor's, in half seconds. The member's recording has him pressing
# on the vendor's list about thirteen seconds after the button.
ADOPT_WAIT_POLLS = 30
# How long the documents page gets, once this run has brought the tab
# there, to show its button and hear back about the member's accounts,
# in half seconds. If the accounts never answer, the button is pressed
# when this is over, as a person would press it.
LINK_WAIT_POLLS = 30
# And how long it is left to settle after the accounts answer, before the
# button is pressed. The member pressed it almost three seconds after the
# link.
VENDOR_SETTLE_MS = 2000
# The documents page asks for the member's accounts when it arrives, and
# the button signs on to the vendor with one of them. The recording shows
# this call answering at the link step and the button's sign-on sending
# an account id, and both pilots' request lists show it too (#35).
_ACCOUNTS_PATH_RE = re.compile(r"/edocs-sso/members/?$", re.I)

# When this run last brought each bank tab to a page, by an address or by
# the sidebar link, and when that tab last heard back about the member's
# accounts, both on the monotonic clock. A tab the run found already on
# the documents page has no arrival, since its page loaded long before,
# and its button is pressed at once, as it always was (#35).
_ARRIVALS: dict = {}


def _watch(page) -> dict:
    """This tab's arrival record. The first call starts listening for the
    accounts call, so it hears one that answers after any later goto or
    link press."""
    rec = _ARRIVALS.get(page)
    if rec is not None:
        return rec
    rec = {"arrived": None, "accounts": None}

    def on_response(res):
        try:
            url = res.url or ""
            if (on_bank_host(url) and res.status < 400
                    and _ACCOUNTS_PATH_RE.search(urlsplit(url).path or "")):
                rec["accounts"] = time.monotonic()
        except Exception:
            pass

    try:
        page.on("response", on_response)
    except Exception:
        pass
    _ARRIVALS[page] = rec
    return rec


def _arriving(page) -> None:
    """Note that this run is about to bring the tab to a new page, so the
    button there waits for the accounts to answer again."""
    _watch(page)["arrived"] = time.monotonic()


def _ready_to_press(rec) -> bool:
    """Whether the documents page has had what it needs from the bank
    before its button is pressed. A page reached before the run looked
    has. One this run brought the tab to has once the accounts answered
    after it arrived and the page then settled, or once the whole wait is
    over with no answer at all."""
    arrived = rec.get("arrived")
    if arrived is None:
        return True
    now = time.monotonic()
    heard = rec.get("accounts")
    if heard is not None and heard >= arrived:
        return now - heard >= VENDOR_SETTLE_MS / 1000.0
    return now - arrived >= LINK_WAIT_POLLS * 0.5


def _waited(rec) -> str:
    """How long the button was held back, in fixed words for a trace."""
    arrived = rec.get("arrived")
    if arrived is None:
        return "not at all, the page was already open"
    heard = rec.get("accounts")
    if heard is not None and heard >= arrived:
        return "until the accounts answered"
    return "the whole wait, the accounts never answered"


# Why open_vendor came back with what it did, in fixed words for a trace
# a tester attaches, so a failed pilot says which step failed (#35).
OPENED = "the button opened a new tab"
REUSED = "the tab this run opened was still open"
NO_DOCUMENTS_PAGE = "the documents page did not open"
OFF_THE_BANK = "the tab was not on the bank's own site, so nothing was pressed"
NO_CONTROL = "no View Documents button or link on the page"
REFUSED = "the View Documents control did not pass the guard"
LEFT_THE_BANK = ("the tab was not on the bank's signed-in pages when the button was due, "
                 "so it was not pressed")
NO_BUTTON = "no View Documents button on the documents page when it was due"
NO_TAB = "the button was pressed and no tab opened"
STAYED_AT_THE_BANK = "a tab opened but stayed on the bank's own site"
NOT_HTTPS = "a tab opened on an address that is not https, so it was closed"
TAB_GONE = "a tab opened and closed before it could be read"
FAILED = "pressing it raised an error"
_LAST_OPEN: dict = {}


def _said(why: str, **more) -> None:
    """Record why the vendor's tab did or did not open, one of the words
    above, for the trace."""
    _LAST_OPEN.clear()
    _LAST_OPEN["why"] = why
    _LAST_OPEN.update(more)


def _open_said() -> dict:
    """What the last try at the vendor's tab came to, fixed words and a
    count only."""
    return {k: _LAST_OPEN[k] for k in ("why", "waited", "error", "old_tabs_closed")
            if _LAST_OPEN.get(k)}


def _press_for_vendor_tab(page, loc):
    """Press `loc`, once it has passed the guard, and adopt the tab it
    opens, or None.

    Statements tabs this run will not read are closed first (see
    _close_old_vendor_tabs), and only a tab that did not exist before the
    press is ever taken for the one it opened. An old tab that reloads
    itself during the wait is not mistaken for it (#35)."""
    label = (loc.first.inner_text(timeout=1000) or "").strip()
    if not is_safe_control(label):
        _said(REFUSED)
        return None
    closed = _close_old_vendor_tabs(page)
    ctx = page.context
    before = set(ctx.pages)
    loc.first.click(timeout=5000)
    for _ in range(TAB_WAIT_POLLS):
        page.wait_for_timeout(500)
        if [p for p in ctx.pages if p not in before]:
            break
    tab = None
    if [p for p in ctx.pages if p not in before]:
        tab = _adopt_new_tab(page, before)
    else:
        _said(NO_TAB)
    if closed:
        _LAST_OPEN["old_tabs_closed"] = closed
    if tab is not None:
        tab.wait_for_timeout(3000)
    return tab


def _press_when_ready(page, button, tabs_before=None):
    """Press the documents page's button once the page is ready for it,
    and adopt the tab it opens, or None.

    When this run has just brought the tab to the page, by an address or
    by the sidebar link, the button waits until the page has heard back
    about the member's accounts and settled, since the button signs on
    with one of them. Pressed sooner it may open nothing, and discovery
    then has no list. A goto_documents that loaded the page by address
    before open_vendor was called counts as bringing it there, which is
    what discovery does when a run starts away from the documents page.

    The wait ends early if the tab leaves the bank's site or is signed
    out, and the button is pressed only while the tab is still at the
    bank. `tabs_before`, given after the link, also takes a tab the link
    itself opened."""
    rec = _watch(page)
    for _ in range(LINK_WAIT_POLLS + VENDOR_SETTLE_MS // 500 + 2):
        if tabs_before is not None and [p for p in page.context.pages if p not in tabs_before]:
            tab = _adopt_new_tab(page, tabs_before)
            if tab is not None:
                tab.wait_for_timeout(3000)
            return tab
        if not on_bank_host(page.url or "") or looks_signed_out(page):
            break
        if button.count() and _ready_to_press(rec):
            break
        page.wait_for_timeout(500)
    if not _still_at_the_bank(page):
        log.info("the tab is not on the bank's own signed-in page, so the button is not pressed")
        _said(LEFT_THE_BANK)
        return None
    if not button.count():
        _said(NO_BUTTON)
        return None
    waited = _waited(rec)
    log.info("pressing View Documents, having waited %s", waited)
    tab = _press_for_vendor_tab(page, button)
    _LAST_OPEN["waited"] = waited
    return tab


def _follow_link_to_button(page, link, button):
    """Press the sidebar link, which only brings this tab to the documents
    page, then the button there that opens the vendor, once the page is
    ready for it, or None."""
    label = (link.first.inner_text(timeout=1000) or "").strip()
    if not is_safe_control(label):
        _said(REFUSED)
        return None
    before = set(page.context.pages)
    _arriving(page)
    link.first.click(timeout=5000)
    return _press_when_ready(page, button, tabs_before=before)


def open_vendor(page):
    """The vendor tab, opened through the documents page's "View
    Documents" button when this run has not opened it yet, or None. The
    button has passed the guard, and the tab it opens has to be on an
    https host, anything else is closed unread.

    The LINK of the same name sits in online banking's sidebar and only
    brings this tab to the documents page. goto_documents takes
    any page carrying that link for the documents page, so a run started
    on the overview pressed the link, saw no tab open and gave up, and
    discovery read the bank's own page. Two pilots did exactly that, each
    request census showing the documents page loading and then a single
    press of the button, which came from the capture after it (#35). So
    a link that opens no tab is followed by the button it leads to.

    Why it came back as it did is left in fixed words for the trace (see
    _open_said)."""
    tab = _vendor_tab_this_run(page)
    if tab is not None:
        _said(REUSED)
        return tab
    _watch(page)
    if not goto_documents(page):
        _said(NO_DOCUMENTS_PAGE)
        return None
    # The button that opens the vendor is the bank's own, so nothing is
    # pressed for it on any other site.
    if not on_bank_host(page.url or ""):
        log.info("not on the bank's own site, so the vendor's button is not looked for")
        _said(OFF_THE_BANK)
        return None
    try:
        button = page.get_by_role("button", name=VENDOR_BUTTON_RE)
        loc = _vendor_button(page)
        if loc.count() == 0:
            _said(NO_CONTROL)
            return None
        if button.count():
            tab = _press_when_ready(page, button)
        else:
            tab = _follow_link_to_button(page, loc, button)
        if tab is None:
            log.info("View Documents opened no tab")
        return tab
    except Exception as e:
        log.info("could not open the document vendor: %s", e)
        _said(FAILED, error=_error_word(e))
    return None


STATEMENT_HISTORY_RE = re.compile(r"^\s*(statement|document|e-?statement)s?\s+history\s*$", re.I)


def open_statement_history(page) -> bool:
    """Press the vendor's own Statement History, so the older statements
    exist on the page. It changes nothing and fetches nothing."""
    try:
        for role in ("link", "button", "tab"):
            loc = page.get_by_role(role, name=STATEMENT_HISTORY_RE)
            for i in range(min(loc.count(), 3)):
                el = loc.nth(i)
                if not el.is_visible():
                    continue
                label = (el.get_attribute("aria-label") or el.inner_text(timeout=800) or "").strip()
                if not STATEMENT_HISTORY_RE.match(label) or not is_safe_control(label):
                    continue
                el.click(timeout=5000)
                page.wait_for_timeout(2000)
                log.info("opened the vendor's statement history")
                return True
    except Exception as e:
        log.info("statement history: %s", e)
    return False


# ---------------------------------------------------------------------------
# Accounts and pages (#35, round six)
# ---------------------------------------------------------------------------
# RECORDED, from the member's recording of 2026-09-27. The vendor's page
# holds one panel per account, headed by an element carrying aria-expanded,
# and each panel has its own Statement History link. The card was the
# second panel, and the member opened it before pressing its Statement
# History. Statement History opens a dialog of twelve statements a page,
# under year headings, with NEXT under the list and Close beside it. The
# app read the first panel's first page and nothing else, so older
# statements were never listed and the card was never seen.
NEXT_PAGE_RE = re.compile(r"^\s*next\s*$", re.I)
CLOSE_RE = re.compile(r"^\s*close\s*$", re.I)
# Seven years at twelve a page is seven pages. This only stops a list
# that never ends.
MAX_HISTORY_PAGES = 20
# A panel whose heading says card holds the card's statements. The guard
# refuses the word card on a control, so a panel heading has a guard of
# its own, the money-moving words without it.
# The plural counts only as "credit cards" or "mastercards". The member's
# card sits under the vendor's heading "Credit Cards / Home Equity Lines of
# Credit", which the singular missed, so its statements were saved as an
# account's (#35). A bare "Cards" can head debit or gift cards, which hold no
# card's statements. The heading names a home equity line as well, and the
# only member we know of with it holds a card, so it is read as a card's.
CARD_PANEL_RE = re.compile(r"\b(visa|master\s*cards?|credit\s+cards?|card)\b", re.I)
# The rule before plurals. Every panel it reads keeps the kind and key it
# gave, and only a panel the plural alone reads as a card changes, in
# _assign_kinds.
_CARD_PANEL_RE_SINGULAR = re.compile(r"\b(visa|master\s*card|credit\s+card|card)\b", re.I)
PANEL_HEADING_FORBIDDEN_RE = re.compile(
    r"(transfer|zelle|\bwire\b|\bpay\b|payment|deposit|withdraw|send\s+money|"
    r"close\s+account|\bcancel|\bdelete|\bremove|\block\b|activate|replace|dispute)", re.I)

CARD_TITLE = "Credit Card Statement"
ACCOUNT_TITLE = "Account Statement"

# RECORDED, from the member's 0.39.1 Pilot of 2026-09-28. The card's twelve
# statements came back with the checking account's twelve dates, while the
# card's own list runs on the 20th of each month, so every card statement
# was looked for on a day the card never had. The history is one dialog for
# every account, and the list read for the card was the one the dialog
# still showed from the account read before it. Each account also read one
# page and no more, where the member counts seven years behind NEXT (#35).
#
# So right before Statement History or NEXT is pressed, every control on
# the page is marked with its own label, and a list counts once its dated
# controls are unmarked, drawn after the press, or carry a label other than
# the one they were marked with, drawn again in place. The vendor answers
# each press with a round trip of its own, so the wait is longer than the
# six seconds it was, and why a history stopped paging goes in the trace.
HISTORY_WAIT_MS = 20000
_POLL_MS = 300
_SEEN_ATTR = "data-paperpull-seen"
# The list read last, kept on the page itself, so a page loaded again
# forgets it along with the list it described.
_LAST_LIST_ATTR = "data-paperpull-last-list"

# How a press's list came, fixed phrases for the trace.
DRAWN = "drawn after the press"
DRAWN_SAME = "drawn again the same"
SHOWN = "shown without being drawn again"
BEFORE = "the list read before"
NO_LIST = "no list"

_MARK_JS = r"""(attr) => {
  const label = el => (el.getAttribute('aria-label') || el.textContent || '').trim();
  for (const el of document.querySelectorAll('a, button, [role=link], [role=button]')) {
    el.setAttribute(attr, label(el));
  }
}"""

# A marked control whose label is no longer the one it was marked with was
# drawn again in place, so it counts as new.
_UNMARK_CHANGED_JS = r"""(attr) => {
  const label = el => (el.getAttribute('aria-label') || el.textContent || '').trim();
  for (const el of document.querySelectorAll('[' + attr + ']')) {
    if (el.getAttribute(attr) !== label(el)) el.removeAttribute(attr);
  }
}"""


def _mark_seen(page) -> None:
    """Mark every control on the page with its label, so the list the next
    press brings can be told from the one the page holds now."""
    try:
        page.evaluate(_MARK_JS, _SEEN_ATTR)
    except Exception as e:
        log.info("could not mark the controls on the page: %s", e)


def _fresh(page):
    """The controls drawn since the page was last marked, as a locator to
    narrow another one with."""
    try:
        page.evaluate(_UNMARK_CHANGED_JS, _SEEN_ATTR)
    except Exception:
        pass
    return page.locator(":not([%s])" % _SEEN_ATTR)


def _labels_of(loc) -> Optional[List[str]]:
    """Each control's label, its aria-label or else its words, in order,
    or None when one could not be read. A read can run out of time on a
    loaded machine, which says nothing of what the page holds, so it is
    never taken for a page with no list."""
    out = []
    try:
        for i in range(loc.count()):
            el = loc.nth(i)
            out.append((el.get_attribute("aria-label", timeout=500)
                        or el.inner_text(timeout=500) or "").strip())
    except Exception:
        return None
    return out


def _listed_labels(page, fresh_only: bool = False) -> Optional[List[str]]:
    """The labels of the dated statements showing, only those drawn since
    the last mark when `fresh_only`, or None when they could not be read.

    Only a control that shows is counted. controls_named falls back to
    every control whose words match when none matches by its accessible
    name, and that takes in the links of a history dialog that was closed.
    Right after the card's Statement History was pressed and before its
    dialog showed, those were the checking account's links, which is the
    likeliest way the card got the checking account's dates (#35)."""
    try:
        loc = _controls_named(page, DATE_ONLY_CONTROL_RE).filter(visible=True)
        if fresh_only:
            loc = loc.and_(_fresh(page))
    except Exception:
        return None
    return _labels_of(loc)


def _remember_list(page, panel, labels: List[str]) -> None:
    """Keep the list just read, and whose panel it was, on the page."""
    try:
        page.evaluate("([attr, value]) => document.documentElement.setAttribute(attr, "
                      "JSON.stringify(value))",
                      [_LAST_LIST_ATTR, {"panel": panel, "labels": list(labels)}])
    except Exception:
        pass


def _last_read(page) -> Optional[dict]:
    """The list this run read last on this page and whose panel it was, as
    {"panel", "labels"}, or None when it has read none since the page
    loaded."""
    import json
    try:
        got = json.loads(page.evaluate(
            "(attr) => document.documentElement.getAttribute(attr) || 'null'", _LAST_LIST_ATTR))
    except Exception:
        return None
    if not isinstance(got, dict) or not isinstance(got.get("labels"), list):
        return None
    return {"panel": got.get("panel"), "labels": [x for x in got["labels"] if isinstance(x, str)]}


def _wait_for_new_list(page, panel, not_like: Optional[List[str]], stale: Optional[List[str]],
                       shown_at_once: bool = False) -> Tuple[str, List[str]]:
    """Wait for the dated list a press brought. Returns how it came, one of
    the fixed phrases above, and its labels.

    A list drawn after the press is taken, unless its labels are
    `not_like`, the page NEXT was pressed on or the last list read from
    another account. That one is waited past, since the old list can be
    drawn before the new one arrives, and taken only when nothing else
    comes. A list showing that was not drawn after the press is taken at
    once only when `shown_at_once`, which is when nothing has been read on
    this page yet, so it cannot be left over from this run, and taken that
    way as it always was. Otherwise it is taken at the end of the wait, and
    only when it is not `stale`, the page NEXT was pressed on or the list
    last read from another account, which is what a dialog opened again
    shows before its new list arrives (#35). `panel` is kept with whatever
    list is taken.

    A list showing is taken at once only when a look for a list drawn after
    the press, taken after the look at what shows, finds none. The page can
    draw its list between two looks. A list drawn after the look for a
    drawn list and before the look at what shows was said to show without
    being drawn again, in the trace and in what Discover prints, and its
    first page was read with every dated control showing, not only those
    the press drew. Full test runs under load did that to the first account
    twice on 2026-10-06. A look in the wait that could not be read says
    nothing either way, and the next look decides."""
    not_like = list(not_like or [])
    same: List[str] = []
    for _ in range(max(1, HISTORY_WAIT_MS // _POLL_MS)):
        page.wait_for_timeout(_POLL_MS)
        fresh = _listed_labels(page, fresh_only=True)
        if fresh:
            if not_like and fresh == not_like:
                same = fresh
                continue
            # One more look, so a list still being drawn is read whole.
            page.wait_for_timeout(_POLL_MS)
            fresh = _listed_labels(page, fresh_only=True) or fresh
            _remember_list(page, panel, fresh)
            return DRAWN, fresh
        if shown_at_once:
            shown = _listed_labels(page)
            if shown:
                page.wait_for_timeout(_POLL_MS)
                shown = _listed_labels(page) or shown
                # Drawn after the press since, or not read, so not taken yet.
                if _listed_labels(page, fresh_only=True) != []:
                    continue
                _remember_list(page, panel, shown)
                return SHOWN, shown
    if same:
        _remember_list(page, panel, same)
        return DRAWN_SAME, same
    shown = _listed_labels(page)
    if not shown:
        return NO_LIST, []
    if stale and shown == list(stale):
        return BEFORE, shown
    _remember_list(page, panel, shown)
    return SHOWN, shown


# Words a trace may say a panel's heading carries, and nothing else from it.
# A heading holds the account's own name and number, and these are enough to
# learn how the vendor names a card. The member's card panel matched none of
# card, Visa or Mastercard, so its statements were read as an account's (#35).
_HEADING_WORDS = (
    "account", "auto", "business", "card", "cash", "certificate", "checking", "classic",
    "credit", "debit", "equity", "gold", "ira", "line", "loan", "mastercard",
    "member", "membership", "money", "market", "mortgage", "platinum", "premier",
    "premium", "rewards", "savings", "secured", "share", "signature", "statement",
    "statements", "travel", "visa")
# A plural counts as its word, "Cards" as card and "Lines" as line (#35).
# Longest first, so a word the list holds in the plural, statements, is
# still given as it is written.
_HEADING_WORD_RE = re.compile(
    r"\b(%s)s?\b" % "|".join(sorted(_HEADING_WORDS, key=len, reverse=True)), re.I)

# A masked account number in a heading, "****4321", "x4321", "...4321" or
# "ending in 4321", with the suffix a credit union writes after a member
# number when there is one, "XXXXXX1111-20". A balance or a date is not one.
_MASKED_FOUR_RE = re.compile(
    r"(?:(?<![A-Za-z0-9])[*x\u2022#]+|\.{2,}|\u2026|\bending\s+in|\bends\s+in)\s*(\d{4})"
    r"(-\d{1,3})?(?!\d)",
    re.I)
# A month's whole name or its short form, and not a word that merely starts
# like one, "Market" or "Decade".
_MONTH_WORD_RE = re.compile(
    r"^(jan(uary)?|feb(ruary)?|mar(ch)?|apr(il)?|may|june?|july?|aug(ust)?|sept?(ember)?|"
    r"oct(ober)?|nov(ember)?|dec(ember)?)$", re.I)


_HEADING_WORD_OF = {w.casefold(): w for w in _HEADING_WORDS}


def _heading_words(text: str) -> List[str]:
    """The words from the list above that `text` carries, each given as the
    list writes it. A letter the match folds, a long s say, never reaches a
    trace as the page wrote it."""
    found = (_HEADING_WORD_OF.get(m.group(1).casefold())
             for m in _HEADING_WORD_RE.finditer(text or ""))
    return sorted({w for w in found if w})


def _panel_facts(panel: dict) -> dict:
    """What a trace may say about a panel's heading, words from the list
    above and whether it shows a masked number, never the heading."""
    return {"words": _heading_words(panel.get("heading") or ""),
            "words_under_it": _heading_words(" ".join(panel.get("sub") or [])),
            "masked_number": bool(_MASKED_FOUR_RE.search(panel.get("heading") or ""))}


def panel_heading_is_safe(text: str) -> bool:
    """A panel's heading may be pressed to open the panel when it names no
    money moving. It only shows or hides the account's own links."""
    return bool((text or "").strip()) and not PANEL_HEADING_FORBIDDEN_RE.search(text)


# Every Statement History link, the hidden ones in a closed panel too, and
# for each the heading of the panel it sits in, the nearest element above
# it with a child that carries aria-expanded. Each is marked so it can be
# pressed by that mark and not by a position that may shift.
_PANELS_JS = r"""(pattern) => {
  const re = new RegExp(pattern, 'i');
  const out = [];
  const named = (el) => (el.getAttribute('aria-label') || el.textContent || '').trim();
  const links = [...document.querySelectorAll('a, button, [role=link], [role=button], [role=tab]')]
    .filter(el => re.test(named(el)));
  links.forEach((el, i) => {
    let header = null, box = null;
    for (let node = el.parentElement; node && node !== document.body; node = node.parentElement) {
      header = [...node.children].find(c => c.hasAttribute('aria-expanded') && !c.contains(el));
      if (header) { box = node; break; }
    }
    el.setAttribute('data-paperpull-history', String(i));
    if (header) header.setAttribute('data-paperpull-panel', String(i));
    const shown = !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
    const inner = header ? [...header.querySelectorAll('a, button, input, select, [role=button], [role=link]')] : [];
    // The panel's own headings under its header, which may name the
    // account's kind when the header does not.
    const sub = box ? [...box.querySelectorAll('h3, h4')].filter(h => !header.contains(h))
      .slice(0, 3).map(h => (h.innerText || h.textContent || '').trim()) : [];
    out.push({i, heading: header ? (header.innerText || header.textContent || '').trim() : '',
              expanded: header ? header.getAttribute('aria-expanded') : '',
              header: !!header,
              header_controls: inner.map(c => (c.getAttribute('aria-label') || c.textContent || '').trim()),
              sub, shown});
  });
  return out;
}"""


def history_panels(page) -> List[dict]:
    """Each account panel's Statement History, in page order, with the
    panel's heading, whether it is open, and whether it is a card's."""
    try:
        got = page.evaluate(_PANELS_JS, STATEMENT_HISTORY_RE.pattern) or []
    except Exception as e:
        log.info("could not read the account panels: %s", e)
        return []
    _assign_kinds(got)
    return got


def _own_key(panel: dict) -> str:
    """The key a panel's own heading gives it, its masked number or its
    words, or ""."""
    return _masked_key(panel) or _words_key(panel)


def _assign_kinds(panels: List[dict]) -> None:
    """Each panel's kind, account key and what its statements were saved
    under, set in place as "card", "account_key" and "legacy".

    Every panel keeps the kind and the key 0.41.0 gave it, so nothing it
    saved is listed again, except a panel only the plural reads as a card
    (#35). That one becomes a card's and takes the key its own heading
    gives it, never the empty key or a place, which the saved statements of
    another panel may hold. When its heading's key is not its alone, it
    stays what it was, since two panels sharing a key would pass one
    account's statements to the other. A member with a card and a home
    equity line under the same heading keeps both as they were.

    `legacy` is the (kind, account) its statements were saved under, and
    only when that too came from its own heading. A place or the empty key
    it held before may since belong to another panel's statements, if the
    page changed, so those are left where they are (review before release)."""
    for p in panels:
        p["card"] = bool(_CARD_PANEL_RE_SINGULAR.search(p.get("heading") or ""))
    for p in panels:
        p["account_key"] = _account_by_place(panels, p)
        p["legacy"] = None
    taken = {p["account_key"] for p in panels if p["card"]}
    for p in panels:
        if p["card"] or not CARD_PANEL_RE.search(p.get("heading") or ""):
            continue
        mine = _own_key(p)
        if not mine or mine in taken or sum(1 for q in panels if _own_key(q) == mine) != 1:
            continue
        old = p["account_key"]
        p["card"], p["account_key"] = True, mine
        taken.add(mine)
        if old and not re.fullmatch(r"account \d+", old):
            p["legacy"] = (ACCOUNT_TITLE, old)


def _panel_account(panels: List[dict], panel: dict) -> str:
    """The panel's account key, as _assign_kinds gave it, or as a panel's
    place among those of its kind gives it for a panel read elsewhere."""
    if "account_key" in panel:
        return panel["account_key"]
    return _account_by_place(panels, panel)


def _account_by_place(panels: List[dict], panel: dict) -> str:
    """What tells this panel's statements from another panel's of the same
    kind. The first panel of a kind keeps an empty account, which is what
    every statement saved before round six was keyed by, so nothing is
    fetched twice. A later one is told apart by the masked number in its
    heading, else by the heading's own words, and by its place among the
    panels of its kind only when neither tells it from the rest.

    0.39.1 kept the whole heading. A heading can hold more than the
    account's name, a balance or a date beside it, and a key that changed
    with either would list every statement of that account again as new on
    the next run (#35). A key has to be the panel's own as well. Two
    panels given one key share one record for each date, and a place moves
    to the next panel when one before it closes, which would pass its
    downloaded dates to another account's statements."""
    same = [p for p in panels if p["card"] == panel["card"]]
    if not same or same[0]["i"] == panel["i"]:
        return ""
    for key in (_masked_key, _words_key):
        mine = key(panel)
        if mine and sum(1 for p in same[1:] if key(p) == mine) == 1:
            return mine
    place = next((n for n, p in enumerate(same, 1) if p["i"] == panel["i"]), 0)
    return "account %d" % place


def _masked_key(panel: dict) -> str:
    """The panel by the masked number in its heading, or ""."""
    m = _MASKED_FOUR_RE.search(panel.get("heading") or "")
    return "account ending %s%s" % (m.group(1), m.group(2) or "") if m else ""


def _words_key(panel: dict) -> str:
    """The panel by its heading's words alone, with every number, amount and
    month name left out, so a balance or a date that changes does not
    change it. Short enough that the key keeps it whole, or ""."""
    words = [w.lower() for w in re.findall(r"[A-Za-z]+", panel.get("heading") or "")
             if not _MONTH_WORD_RE.match(w)]
    return ("account " + " ".join(words))[:40].rstrip() if words else ""


def _panel_opens_safely(panel: dict) -> bool:
    """A closed panel is opened only through a heading that names no money
    moving, and whose own controls, a toggle say, name none either."""
    inner = panel.get("header_controls") or []
    return panel_heading_is_safe(panel.get("heading")) and all(
        not (x or "").strip() or panel_heading_is_safe(x) for x in inner)


def open_panel_history(page, panel: dict, trace: Optional[list] = None,
                       facts: Optional[dict] = None) -> bool:
    """Open this panel if it is closed, through its own heading, then press
    its Statement History. True when a list shows that the press brought.

    Every control is marked right before the press, and when the list read
    last on this page was another account's, the new one must not be it, so
    a list left over from the account before is never read as this one's
    (#35). `facts` gets how the list came, as _wait_for_new_list says it."""
    i = panel["i"]
    try:
        if panel.get("expanded") == "false":
            if not _panel_opens_safely(panel):
                if trace is not None:
                    trace.append({"note": "a panel's heading was not pressed", "panel": i,
                                  "why": "it names a word the guard refuses"})
                return False
            head = page.locator('[data-paperpull-panel="%d"]' % i).first
            head.click(timeout=5000)
            page.wait_for_timeout(800)
            # A heading that opens through a small toggle of its own, and
            # did not open from a press on the heading, gets the toggle,
            # when it is the heading's only control.
            if head.get_attribute("aria-expanded") == "false" and len(panel.get("header_controls") or []) == 1:
                head.locator("a, button, [role=button], [role=link]").first.click(timeout=5000)
                page.wait_for_timeout(800)
        link = page.locator('[data-paperpull-history="%d"]' % i).first
        link.wait_for(state="visible", timeout=4000)
        label = (link.get_attribute("aria-label") or link.inner_text(timeout=1500) or "").strip()
        if not STATEMENT_HISTORY_RE.match(label) or not is_safe_control(label):
            return False
        last = _last_read(page)
        _mark_seen(page)
        link.click(timeout=5000)
    except Exception as e:
        log.info("could not open a panel's statement history: %s", e)
        if trace is not None:
            trace.append({"note": "a panel's statement history would not open", "panel": i,
                          "error": _error_word(e)})
        return False
    # Only another account's list is one this account's must not be. The
    # same account's, opened again, is waited on to be drawn again, since it
    # can be showing a later page, and taken as it is when it never is.
    other = last["labels"] if last is not None and last["panel"] != i else []
    how, _labels = _wait_for_new_list(page, i, other, other, shown_at_once=last is None)
    if facts is not None:
        facts["list"] = how
    return how in (DRAWN, DRAWN_SAME, SHOWN)


# The history dialog's own controls. The dialog is in the selector itself,
# so a Next or a Close anywhere else on the vendor's page is never taken.
_DIALOG_CONTROLS = ("[role=dialog] button, [role=dialog] a, [role=dialog] [role=button], "
                    "[aria-modal=true] button, [aria-modal=true] [role=button]")


def _pager(page, name_re, why: Optional[dict] = None):
    """The history dialog's own control whose whole label, its aria-label
    or else what it shows, matches `name_re`, showing and enabled, or None.
    A control whose label cannot be read is never taken, and neither is
    one the guard refuses. `why` gets "hidden", "disabled" or "none" when
    nothing is taken."""
    hidden = disabled = 0
    try:
        loc = page.locator(_DIALOG_CONTROLS)
        count = int(loc.count())
    except Exception:
        count = 0
    for i in range(min(count, 40)):
        el = loc.nth(i)
        try:
            label = (el.get_attribute("aria-label") or el.inner_text(timeout=500) or "").strip()
            if not label or not name_re.match(label) or FORBIDDEN_CONTROL_RE.search(label):
                continue
            if not el.is_visible():
                hidden += 1
                continue
            if not el.is_enabled() or _looks_disabled(el):
                disabled += 1
                continue
            return el
        except Exception:
            continue
    if why is not None:
        why["pager"] = "disabled" if disabled else "hidden" if hidden else "none"
    return None


def _looks_disabled(el) -> bool:
    """A control that says it is disabled without the disabled property. A
    WebForms link button that is off is drawn as a link with the class
    aspNetDisabled, and a browser reports that link as enabled, so a last
    page's NEXT would be pressed and waited on."""
    try:
        if (el.get_attribute("aria-disabled") or "").strip().lower() == "true":
            return True
        return "aspnetdisabled" in (el.get_attribute("class") or "").lower()
    except Exception:
        return False


# Why a history stopped paging, fixed phrases for the trace, each one a
# clause that reads after "paging stopped because".
_STOPPED = {
    "none": "there is no NEXT in the history",
    "hidden": "NEXT is hidden",
    "disabled": "NEXT is disabled",
    DRAWN_SAME: "NEXT drew the same page again",
    BEFORE: "NEXT brought no new page",
    NO_LIST: "the list went away after NEXT",
}
PAGE_LIMIT = "it reached the page limit"


def next_history_page(page, facts: Optional[dict] = None) -> bool:
    """Press NEXT under the history, and wait for the next page of dates,
    drawn after the press. False on the last page, where NEXT is gone or
    disabled or no new page comes, and `facts` gets why as a fixed phrase,
    how long the wait was, and how the new page came when it did (#35)."""
    facts = facts if facts is not None else {}
    why: dict = {}
    btn = _pager(page, NEXT_PAGE_RE, why)
    if btn is None:
        facts["stopped"] = _STOPPED.get(why.get("pager"), _STOPPED["none"])
        return False
    before = _listed_labels(page)
    last = _last_read(page)
    _mark_seen(page)
    try:
        btn.click(timeout=5000)
    except Exception as e:
        log.info("NEXT did not press: %s", e)
        facts["stopped"] = "NEXT would not press (%s)" % _error_word(e)
        return False
    started = time.monotonic()
    how, _labels = _wait_for_new_list(page, last["panel"] if last else None, before, before)
    facts["list"] = how
    facts["waited_s"] = round(time.monotonic() - started, 1)
    if how in (DRAWN, SHOWN):
        return True
    facts["stopped"] = _STOPPED.get(how, how)
    return False


def close_history(page) -> None:
    """Close the history dialog with its own Close, or Escape."""
    btn = _pager(page, CLOSE_RE)
    try:
        if btn is not None:
            btn.click(timeout=3000)
        else:
            page.keyboard.press("Escape")
        page.wait_for_timeout(500)
    except Exception:
        pass


def _panel_for(panels: List[dict], title: str, account: str) -> Optional[dict]:
    """The panel a statement was listed in, by its kind and account. A card
    statement is in a card's panel and every other one in another panel,
    and the first panel of the kind when no account was kept."""
    card = (title or "").startswith(CARD_TITLE)
    same = [p for p in panels if p["card"] == card]
    # The empty key is looked up like any other. The first panel of a kind
    # in page order held it until a card only the plural reads could come
    # first, and then a Visa's statements were looked for in the other
    # card's history, where a statement of the same day was saved as the
    # Visa's (review before release).
    return next((p for p in same if _panel_account(panels, p) == account), None)


def _read_dated_list(page, kind: str, account: str, seen: set,
                     fresh_only: bool = False, legacy=None) -> List[RawDoc]:
    """The statements on the history page showing, each named by nothing
    but its date, as this panel's kind of statement. Only statements that
    show are read, and only those drawn after the last press when
    `fresh_only`, so a list left over from another account is not (#35).
    `legacy` is the (kind, account) they were saved under before, if any."""
    docs: List[RawDoc] = []
    try:
        loc = _controls_named(page, DATE_ONLY_CONTROL_RE).filter(visible=True)
        if fresh_only:
            loc = loc.and_(_fresh(page))
        count = loc.count()
    except Exception:
        return docs
    for i in range(count):
        el = loc.nth(i)
        try:
            name = (el.get_attribute("aria-label", timeout=800) or el.inner_text(timeout=800) or "").strip()
        except Exception:
            continue
        iso = parse_date(name) if is_safe_control(name) else None
        if not iso or (kind, account, iso) in seen:
            continue
        seen.add((kind, account, iso))
        try:
            href = el.get_attribute("href") or ""
        except Exception:
            href = ""
        disp = _human_date(iso)
        docs.append(RawDoc(title=f"{kind} - {disp}", account=account, date_text=iso,
                           href=href if PDF_HREF_RE.search(href or "") else "",
                           text=f"Golden 1 {kind} {disp}", row_index=i,
                           kind="statement", dated_by="label",
                           legacy_title=f"{legacy[0]} - {disp}" if legacy else "",
                           legacy_account=legacy[1] if legacy else ""))
    return docs


def _read_every_panel(page, panels: List[dict], trace: Optional[list]) -> List[RawDoc]:
    """Every panel's history, every page of it, closed again after.

    The trace says, for each panel, how its first list came, how many pages
    were read and why the paging stopped, and which words from a fixed list
    its heading carries, so the next file says what NEXT did and what the
    vendor calls a card (#35)."""
    if trace is not None:
        trace.append({"note": "discovery found the account panels", "panels": len(panels),
                      "cards": sum(1 for p in panels if p["card"]),
                      "closed": sum(1 for p in panels if p.get("expanded") == "false"),
                      "headings": [_panel_facts(p) for p in panels[:6]]})
    docs: List[RawDoc] = []
    seen: set = set()
    for first in panels:
        now = history_panels(page)
        panel = next((p for p in now if p["i"] == first["i"]), None)
        if panel is None:
            continue
        if _pager(page, CLOSE_RE) is not None:
            close_history(page)
        opened: dict = {}
        if not open_panel_history(page, panel, trace, facts=opened):
            if trace is not None:
                trace.append({"note": "a panel's statement history did not show",
                              "panel": panel["i"], "card": panel["card"],
                              "list": opened.get("list", "")})
            continue
        expand_all(page)
        kind = CARD_TITLE if panel["card"] else ACCOUNT_TITLE
        account = _panel_account(now, panel)
        legacy = panel.get("legacy")
        fresh_only = opened.get("list") != SHOWN
        pages = found = 0
        stopped, waits = "", []
        while True:
            pages += 1
            got = _read_dated_list(page, kind, account, seen, fresh_only=fresh_only,
                                   legacy=legacy)
            docs += got
            found += len(got)
            if pages >= MAX_HISTORY_PAGES:
                stopped = PAGE_LIMIT
                break
            paged: dict = {}
            if not next_history_page(page, paged):
                stopped = paged.get("stopped", "")
                break
            waits.append(paged.get("waited_s", 0))
            fresh_only = paged.get("list") != SHOWN
        close_history(page)
        if trace is not None:
            trace.append({"note": "a panel's statement history was read", "panel": panel["i"],
                          "card": panel["card"], "pages": pages, "dated": found,
                          "list": opened.get("list", ""), "paging_stopped": stopped,
                          "longest_wait_s": max(waits) if waits else 0})
    return docs


def _find_in_panels(page, panels: List[dict], iso_date: str, title: str, account: str,
                    trace: Optional[list]):
    """This statement's control, in its own panel's history, paged to. Only
    a list the presses drew is searched, never one left from another
    account (#35)."""
    panel = _panel_for(panels, title, account)
    if panel is None:
        if trace is not None:
            trace.append({"note": "no panel holds this kind of statement",
                          "card": (title or "").startswith(CARD_TITLE), "panels": len(panels)})
        return None, ""
    if _pager(page, CLOSE_RE) is not None:
        close_history(page)
    opened: dict = {}
    if not open_panel_history(page, panel, trace, facts=opened):
        if trace is not None:
            trace.append({"note": "a panel's statement history did not show",
                          "panel": panel["i"], "card": panel["card"],
                          "list": opened.get("list", "")})
        return None, ""
    expand_all(page)
    fresh_only = opened.get("list") != SHOWN
    pages = 1
    stopped = ""
    el, label = _control_for(page, iso_date, fresh_only=fresh_only, visible_only=True)
    while el is None:
        if pages >= MAX_HISTORY_PAGES:
            stopped = PAGE_LIMIT
            break
        paged: dict = {}
        if not next_history_page(page, paged):
            stopped = paged.get("stopped", "")
            break
        pages += 1
        fresh_only = paged.get("list") != SHOWN
        el, label = _control_for(page, iso_date, fresh_only=fresh_only, visible_only=True)
    if trace is not None:
        trace.append({"note": "the panel's statement history was searched", "panel": panel["i"],
                      "card": panel["card"], "pages": pages, "found": el is not None,
                      "list": opened.get("list", ""), "paging_stopped": stopped})
    return el, label


_HOW_SAID = {
    DRAWN: "Its list was drawn after the press.",
    DRAWN_SAME: "Its list was drawn with the same dates as the account read before it.",
    SHOWN: "Its list showed without being drawn again.",
    BEFORE: "Only the list read before it showed.",
    NO_LIST: "No list came.",
}


def discovery_lines(trace) -> List[str]:
    """What discovery saw of each account's history, as sentences of fixed
    words and counts, for Discover to print so a tester can paste them.
    The member's paste of the summary alone could not say which account
    was read how, or why each stopped at one page (#35)."""
    entries = [t for t in (trace or []) if isinstance(t, dict)]
    found = next((t for t in entries if t.get("note") == "discovery found the account panels"), None)
    if found is None:
        return []
    out = ["The statements page shows %d account(s), %d taken for a card."
           % (found.get("panels", 0), found.get("cards", 0))]
    for k, h in enumerate(found.get("headings") or []):
        words = h.get("words") or []
        said = ("Account %d heading carries the words %s" % (k + 1, ", ".join(words)) if words
                else "Account %d heading carries no word from the app's list" % (k + 1))
        if h.get("masked_number"):
            said += ", and a masked number"
        under = h.get("words_under_it") or []
        if under:
            said += ". The headings under it carry %s" % ", ".join(under)
        out.append(said + ".")
    for t in entries:
        if t.get("note") == "a panel's statement history was read":
            said = "Account %d history, %d statements on %d page(s). %s" % (
                t.get("panel", 0) + 1, t.get("dated", 0), t.get("pages", 0),
                _HOW_SAID.get(t.get("list"), ""))
            if t.get("paging_stopped"):
                said += " Paging stopped because %s." % t["paging_stopped"]
            out.append(said.strip())
        elif t.get("note") == "a panel's statement history did not show":
            out.append("Account %d history did not show. %s"
                       % (t.get("panel", 0) + 1, _HOW_SAID.get(t.get("list"), "Its link would not open.")))
    return out


def collect_download_docs(page, trace: Optional[list] = None) -> List[RawDoc]:
    """Read every statement and tax document the vendor's page offers.
    Each control's own name, or the row it sits in, carries the date.

    `trace` collects where discovery read and how many dates it found
    there, counts and fixed wording only. What discovery saw had to be
    worked out from the order of a request census, because no file a
    tester sends said it (#35).

    Only a vendor tab this run opened through the bank's button is read.
    The bank's own pages list no statements, and a control there with no
    date of its own took whatever date was printed near it, which is how
    a statement dated by a day the vendor never offered came to be tried
    first on every pilot. Any other tab, such as a vendor tab an earlier
    run left open, may show a list from a session that has ended. When
    the vendor's tab does not open, discovery finds nothing and says why."""
    vendor = open_vendor(page)
    if vendor is None:
        log.info("the vendor's tab did not open, so there is no list to read")
        if trace is not None:
            trace.append({"note": "discovery, the vendor's tab did not open, so no list was read",
                          "on": _where(page.url), **_open_said()})
        return []
    page = vendor
    if trace is not None:
        trace.append({"note": "discovery, the vendor's tab opened",
                      "on": _where(page.url), **_open_said()})
    # One panel per account, each with its own history of twelve a page,
    # read to its last page (round six). A vendor page that shows no
    # Statement History at all is read the way it always was, below.
    panels = history_panels(page)
    if panels:
        return _read_every_panel(page, panels, trace)
    docs: List[RawDoc] = []
    seen = set()
    # The vendor opens on the current statement, and the rest are behind
    # its own Statement History, which the recording shows the member
    # pressing before any dated link existed to press (#35).
    opened = open_statement_history(page)
    expand_all(page)
    scroll_full_page(page)
    list_shown = _dated_count(page) > 0
    log.info("statement history %s, %d dated statements listed",
             "opened" if opened else "control not found", _dated_count(page))
    ctrls = _bill_controls(page)
    skipped = 0
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
        iso, how = _date_of_control(el, name, list_shown)
        if not iso:
            skipped += 1
            continue
        if iso in seen:
            continue
        seen.add(iso)
        disp = _human_date(iso)
        row_text = ""
        if how == "row":
            try:
                row_text = el.evaluate(_ROW_OF_JS) or ""
            except Exception:
                row_text = ""
        tax = bool(re.search(r"1099|1098|5498|tax", name + " " + row_text, re.I))
        kind_title = "Tax Document" if tax else "Account Statement"
        docs.append(RawDoc(title=f"{kind_title} - {disp}", date_text=iso,
                           href=href if PDF_HREF_RE.search(href or "") else "",
                           text=f"Golden 1 {kind_title} {disp}", row_index=i,
                           kind="tax" if tax else "statement", dated_by=how))
    if skipped:
        log.info("%d document controls left out, none named one date of its own", skipped)
    if trace is not None:
        trace.append({"note": "discovery read the page",
                      "statement_history": "opened" if opened else "not found",
                      "dated_statements": _dated_count(page),
                      "by_label": sum(1 for d in docs if d.dated_by == "label"),
                      "by_row": sum(1 for d in docs if d.dated_by == "row"),
                      "left_out": skipped})
    return docs


_PICKED_ATTR = "data-paperpull-picked"


def _control_for(page, iso: str, fresh_only: bool = False, visible_only: bool = False):
    """The control for the document dated `iso`, matched the same way
    discovery found it, or None. Both read a control's date through
    _date_of_control, so the two cannot disagree about which day a
    statement is (#35). With `visible_only`, as in an account's history,
    only a control that shows is taken, and with `fresh_only` only one
    drawn after the last press.

    The control found is marked and handed back by that mark, so the one
    pressed is the one whose date was read, even when the list is drawn
    again in between and the same place holds another."""
    list_shown = _dated_count(page) > 0
    ctrls = _bill_controls(page)
    if visible_only or fresh_only:
        ctrls = ctrls.filter(visible=True)
    if fresh_only:
        ctrls = ctrls.and_(_fresh(page))
    for i in range(ctrls.count()):
        el = ctrls.nth(i)
        try:
            name = (el.get_attribute("aria-label", timeout=800)
                    or el.inner_text(timeout=800) or "").strip()
        except Exception:
            name = ""
        found, _ = _date_of_control(el, name, list_shown)
        if found == iso:
            try:
                el.evaluate("(e, a) => { document.querySelectorAll('[' + a + ']')"
                            ".forEach(x => x.removeAttribute(a)); e.setAttribute(a, '1'); }",
                            _PICKED_ATTR)
                return page.locator("[%s]" % _PICKED_ATTR).first, name
            except Exception:
                return el, name
    return None, ""


def _fetch_pdf(page, href: str, zip_ok: bool = False) -> Optional[bytes]:
    """A PDF link fetched from inside the signed-in page, cookies and all.
    The fetching is the core's, the hosts are this app's."""
    return _core_fetch_pdf(page, href, is_safe_url, zip_ok=zip_ok)


def _take_same_tab(page, start_url: str, out_path: Path, trace) -> bool:
    """A PDF the click opened in this very tab. The core does the reading,
    this app's guard decides which addresses it may read.

    The core notes the address the tab moved to. What reaches this app's
    trace is only which site that was and what kind of answer it gave."""
    moved_to = page.url or ""
    noted: list = []
    ok = _core_take_same_tab(page, start_url, out_path, noted, is_safe_url)
    if trace is not None:
        for entry in noted:
            trace.append({"note": "the tab moved", "on": _where(moved_to),
                          "type": _type_word(str(entry.get("content_type") or ""))})
    return ok


# How long a click is given to produce the document, in seconds, before
# the next way of catching it is tried, after a second step, and at last.
CLICK_WAIT_S = 10
SECOND_STEP_WAIT_S = 20
LAST_WAIT_S = 15


def _type_word(content_type: str) -> str:
    """A content type as one of a few fixed words, for a trace."""
    ct = (content_type or "").lower()
    for word in ("pdf", "json", "octet", "html", "javascript", "text"):
        if word in ct:
            return word
    return "other" if ct else "none"


def _control_kind(label: str) -> str:
    """What sort of control was pressed, in fixed words, for a trace. Its
    own words stay out of the file."""
    if DATE_ONLY_CONTROL_RE.match(label or ""):
        return "a link named by its date"
    if _SECOND_STEP_RE.match(label or ""):
        return "a download step"
    return "another document control"


def _error_word(e: BaseException) -> str:
    """An error by its kind alone. Playwright's message can quote the
    element it was waiting for, address and all."""
    return type(e).__name__[:40]


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
    `trace` collects what happened, the click's own outcome included.

    Everything the trace says is built from fixed words, counts and
    statuses. It goes into download-attempt.json, which a tester is asked
    to attach to a public issue, and until this pilot no Golden 1 run had
    got this far, so it had never held an address or a label (#35)."""
    ctx = page.context
    got: dict = {}
    downloads: list = []
    # Answers to a request this press made, from its tab or one it opened,
    # that called themselves a PDF and read empty. Asked for once more only
    # when nothing else brings the document (capture.ask_again).
    empty_answers: list = []
    made_here = _RequestsSince(page, ctx.pages)
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
                trace.append({"status": res.status, "type": _type_word(ct), "on": _where(url)})
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
            page, el, what="the control for this statement", words=_words(),
            guard=is_safe_control, dl_dir=dl_dir,
            brought=lambda: bool(downloads or got or (_control_texts(page) - controls_before)))
        if trace is not None:
            if outcome.error is None:
                trace.append({"note": "clicked", "control_kind": _control_kind(label)})
            else:
                trace.append({"note": "click failed", "control_kind": _control_kind(label),
                              "error": _error_word(outcome.error)})
            if outcome.how == pressing.MADE:
                trace.append({"note": "the press reached the page although it raised, "
                                      "so it was not made again", "control_kind": _control_kind(label)})
            elif outcome.how == pressing.THROUGH_THE_PAGE and outcome.page_error is None:
                trace.append({"note": "clicked through the DOM instead", "control_kind": _control_kind(label)})
            elif outcome.how == pressing.THROUGH_THE_PAGE:
                trace.append({"note": "DOM click failed too", "error": _error_word(outcome.page_error)})
        if wait_for_pdf(CLICK_WAIT_S):
            return True
        if _take_same_tab(page, start_url, out_path, trace):
            return True
        if _take_new_tab(page, [p for p in ctx.pages if p not in before], out_path):
            return True
        appeared = _control_texts(page) - controls_before
        if trace is not None:
            trace.append({"note": "after the click", "on": _where(page.url or ""),
                          "appeared": len(appeared),
                          "new_tabs": len([p for p in ctx.pages if p not in before])})
        step, step_label = _second_step(page, appeared)
        if step is not None:
            try:
                step.click(timeout=8000)
                if trace is not None:
                    trace.append({"note": "second step clicked",
                                  "control_kind": _control_kind(step_label)})
            except Exception as e:
                if trace is not None:
                    trace.append({"note": "second step click failed",
                                  "control_kind": _control_kind(step_label),
                                  "error": _error_word(e)})
            if wait_for_pdf(SECOND_STEP_WAIT_S):
                return True
            if _take_same_tab(page, start_url, out_path, trace) or \
                    _take_new_tab(page, [p for p in ctx.pages if p not in before], out_path):
                return True
        if wait_for_pdf(LAST_WAIT_S):
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


# The hosts a trace may name. Anything else is "another site", so what
# goes into a file a tester attaches is always one of these words.
_KNOWN_HOSTS = ("digitalbanking.golden1.com", "login.golden1.com", "ebank.hepsiian.com")
_KNOWN_DOMAINS = (BANK_DOMAIN,) + VENDOR_HOSTS


def _where(url: str) -> str:
    """Which site a page is on, for a file a tester attaches. Always a word
    from the lists above, a known host of the bank's or the vendor's, the
    domain for any other page of theirs, "another site", or "nowhere".
    Never the address itself, its port or anything before its host."""
    try:
        host = (urlsplit(url or "").hostname or "").lower()
    except ValueError:
        return "nowhere"
    if not host:
        return "nowhere"
    if host in _KNOWN_HOSTS:
        return host
    for domain in _KNOWN_DOMAINS:
        if host == domain or host.endswith("." + domain):
            return domain
    return "another site"


# The orchestrator says where the bank's tab stood in the same words.
where = _where


def _control_dates(page, limit: int = 30) -> list:
    """The dates this page's own document controls carry, for the trace
    when the one that was wanted is not among them. Dates only (#35)."""
    out = []
    try:
        list_shown = _dated_count(page) > 0
        ctrls = _bill_controls(page)
        for i in range(min(ctrls.count(), limit)):
            el = ctrls.nth(i)
            try:
                name = (el.get_attribute("aria-label") or el.inner_text(timeout=500) or "").strip()
            except Exception:
                name = ""
            found, how = _date_of_control(el, name, list_shown)
            # Why a control has no date is fixed wording from this file,
            # never the page's own text.
            out.append(found or "no date, " + how)
    except Exception as e:
        log.info("control dates: %s", e)
    return out[:limit]


def download_bill(page, dl_dir, iso_date: str, out_path, title: str = "",
                  trace: Optional[list] = None, account: str = "") -> bool:
    """Save the document dated `iso_date`. A PDF link on the row is fetched
    from inside the page. Otherwise the row's own control is clicked, once
    it has passed the guard, and whichever the site produces is caught, a
    download event or a PDF response, in this tab or one it opens.

    `dl_dir` is where the attached browser saves a download, watched
    after every click."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if not goto_documents(page):
        log.info("could not open the documents page for %s", iso_date)
        if trace is not None:
            trace.append({"note": "the documents page would not open"})
        return False
    # The documents themselves are on the bank's vendor, behind a button
    # on this page. A run that never got there and then found no control
    # wrote a trace with nothing in it at all, which is what a tester
    # sent, and an empty trace cannot be told from a run that never
    # started (#35).
    vendor = open_vendor(page)
    if vendor is None:
        # Only a vendor tab this run opened lists statements it can fetch.
        # The bank's own pages list none, their only document controls are
        # the two that lead to the vendor, and any other tab may be an old
        # one whose session has ended. So nothing is pressed anywhere else.
        log.info("the vendor's tab did not open, so nothing is pressed for %s", iso_date)
        if trace is not None:
            trace.append({"note": "the vendor's tab did not open, so no statement was pressed",
                          "on": _where(page.url), **_open_said()})
        return False
    page = vendor
    if trace is not None:
        trace.append({"note": "the vendor's tab opened", "on": _where(page.url), **_open_said()})
    # The statement's own panel, by its kind and account, and its history
    # paged until its date shows (round six). A vendor page that shows no
    # Statement History at all is searched the way it always was.
    panels = history_panels(page)
    if panels:
        el, label = _find_in_panels(page, panels, iso_date, title, account, trace)
    else:
        # The same step discovery takes. The vendor opens on the current
        # statement and the rest are behind its own Statement History, so a
        # capture that skipped it would find nothing for any date but the
        # newest (#35).
        opened_history = open_statement_history(page)
        expand_all(page)
        # The 0.34.1 pilot found no Statement History control and yet twelve
        # dated statements on the page, so the vendor can open straight on
        # its list. A missing control is only a problem when no dated
        # statement is listed either, and the trace now says which (#35).
        listed = _dated_count(page)
        if trace is not None:
            if opened_history:
                note = "the vendor's statement history opened"
            elif listed:
                note = "no statement history control, the vendor's page already lists dated statements"
            else:
                note = "no statement history control and no dated statement on the vendor's page"
            trace.append({"note": note, "dated_statements": listed})

        el, label = _control_for(page, iso_date)
    if el is None:
        log.info("no document control found for %s", iso_date)
        if trace is not None:
            trace.append({"note": "no control on this page carries that date",
                          "date": iso_date,
                          "dates_here": _control_dates(page)})
        return False
    if not is_safe_control(label):
        log.info("refusing unsafe control %r for %s", label, iso_date)
        if trace is not None:
            trace.append({"note": "the control for that date is one the guard refuses",
                          "control_kind": _control_kind(label)})
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
                              "on": _where(target)})
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
    r"^\s*((see|view|show)\s+)?(statements?(\s+(and|&)\s+documents)?|e-?statements|documents|tax\s+(documents|forms)|statement\s+history)\s*$", re.I)


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
    guard's verdict on each, and every JSON or PDF response golden1.com sends
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

    ctx = page.context
    ctx.on("response", on_response)
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
        # The second survey never saw inside the vendor's tab, because the
        # "View Documents" control is a button the follow loop above did
        # not take. Press it here, on purpose, and record whatever opens,
        # on whatever host, marked. Nothing on that tab is followed.
        _survey_vendor_button(page, report, dwell_ms)
    finally:
        try:
            ctx.remove_listener("response", on_response)
        except Exception:
            pass
    return report


def _survey_vendor_button(page, report: dict, dwell_ms: int) -> None:
    """Press "View Documents" on the documents page and describe the tab
    it opens, or the page it changes, for the report."""
    # The tabs that were open before the press, set just before it.
    tabs_before = None
    try:
        if not goto_documents(page):
            report.setdefault("notes", []).append("documents page not reached, vendor button not tried")
            return
        loc = _vendor_button(page)
        if loc.count() == 0:
            report.setdefault("notes", []).append("no View Documents button on the documents page")
            return
        label = (loc.first.inner_text(timeout=1000) or "").strip()
        if not is_safe_control(label):
            report.setdefault("notes", []).append("View Documents did not pass the guard: %r" % redact(label)[:60])
            return
        tabs_before = set(page.context.pages)
        url_before = page.url
        controls_before = {c["text"] for c in _page_summary(page)["controls"]}
        loc.first.click(timeout=5000)
        new_tabs = []
        for _ in range(40):
            page.wait_for_timeout(500)
            new_tabs = [p for p in page.context.pages if p not in tabs_before]
            if new_tabs:
                break
        if not new_tabs:
            page.wait_for_timeout(dwell_ms)
            after = _page_summary(page)
            appeared = [c["text"] for c in after["controls"] if c["text"] not in controls_before]
            report.setdefault("notes", []).append("View Documents opened no tab")
            report["vendor_button"] = {"pressed": redact(label)[:60], "url_after": redact(page.url or "")[:160],
                                       "url_changed": page.url != url_before, "appeared": appeared[:20]}
            if page.url != url_before and is_safe_url(page.url or ""):
                after["followed_from"] = label
                report["pages"].append(after)
            return
        for extra in new_tabs:
            try:
                extra.wait_for_load_state("domcontentloaded", timeout=20000)
            except Exception:
                pass
            # The vendor signs the person on through a redirect or two.
            # Give it time, then read where it ended up.
            for _ in range(20):
                extra.wait_for_timeout(500)
                if _vendor_tab(page) is not None:
                    break
            extra.wait_for_timeout(dwell_ms)
            try:
                host = urlsplit(extra.url or "").hostname or ""
                tab = _page_summary(extra)
                tab["opened_tab_from"] = label
                tab["host"] = redact(host)
                tab["off_host"] = not is_safe_url(extra.url or "")
                tab["row_counts"] = {}
                for name, sel in (("doc_row", FALLBACK["doc_row"]), ("table rows", "table tbody tr"),
                                  ("pdf links", "a[href*='.pdf']"), ("download attrs", "a[download]"),
                                  ("frames", "iframe")):
                    try:
                        tab["row_counts"][name] = extra.locator(sel).count()
                    except Exception:
                        tab["row_counts"][name] = "ERR"
                try:
                    tab["frames"] = [redact(f.url or "")[:120] for f in extra.frames if f != extra.main_frame][:8]
                except Exception:
                    pass
                report["pages"].append(tab)
            except Exception as e:
                report.setdefault("notes", []).append("could not read the vendor tab: %s" % str(e)[:120])
            try:
                extra.close()
            except Exception:
                pass
    except Exception as e:
        report.setdefault("notes", []).append("vendor button survey failed: %s" % str(e)[:120])
    finally:
        # Every tab the press opened is closed however the survey ended. It
        # took the new tabs as they stood when the first one came, so a tab
        # the same press opened a moment later stayed open, and so did the
        # ones after a tab whose reading raised.
        if tabs_before is not None:
            try:
                opened = [p for p in page.context.pages if p not in tabs_before]
            except Exception:
                opened = []
            for extra in opened:
                try:
                    extra.close()
                except Exception:
                    pass


# ---------------------------------------------------------------------------
# Host allowlist. Parsed, never a string prefix, so a lookalike host cannot
# walk through.
# ---------------------------------------------------------------------------
# hepsiian.com is the document vendor the "View Documents" button signs
# on to, seen in the first survey. The statements are listed there.
ALLOWED_HOSTS = {"golden1.com", "hepsiian.com"}  # the vendor's host is added when its tab opens


def is_safe_url(url: str) -> bool:
    """True only for an https URL on one of this provider's own hosts.

    The check itself lives in the core, so all of them answer the same way.
    This app keeps the hosts, which is the part that really is its own."""
    return _host_allows(url, ALLOWED_HOSTS)
