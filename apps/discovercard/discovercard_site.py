"""ALL Discover selectors, URLs, and page behavior live here.

When Discover changes its site, repair this file only.

SCOPE: Discover **credit cards** only (Discover it, Discover it Miles/Chrome/
Student, Discover More). Discover Bank deposit accounts, personal loans,
student loans and home loans are separate portals and are out of scope.

SAFETY (this is a credit-card account):
  This module is strictly READ-ONLY. It opens the statements/documents area,
  reads the list of documents, and downloads the PDFs Discover already
  generated. It must NEVER activate any control that pays a bill, sets up
  autopay, moves money, transfers a balance, takes a cash advance, redeems
  Cashback Bonus or rewards, freezes or replaces a card, requests a
  credit-line increase, disputes a charge, applies for a product, or changes
  any setting. The guard is FORBIDDEN_CONTROL_RE; every click path checks it,
  and a control must ALSO look like a document action (SAFE_DOC_CONTROL_RE)
  before it may be clicked. Dropdowns are controls too - see
  MONEY_CONTROL_RE - and there is deliberately no code here that submits a
  form or confirms a dialog.

A REAL BROWSER, ALWAYS: this app asks for an installed Edge or Chrome
(prefer_real=True), like the Walmart, Verizon and Chase apps. Discover's
bot-detection posture has not been measured, and that is precisely the reason:
a tripped check on a card account can mean a step-up verification loop or a
temporary lock, so the first contact is never from an obviously-automated
browser. Do not "just try" the bundled Chromium to find out.

WHAT THE LIVE PROBE ESTABLISHED (2026-08-19):
  * The page is "Activity & Statements" at
      card.discover.com/cardmembersvcs/statements/app/activity
    hash-routed: #/recent, #/current, #/stmt_YYYYMMDD. page.goto WORKS and
    keeps the session, so this app pastes the URL first - the opposite of the
    Ally and Chase apps, where only clicking the app's own nav worked.
  * There is NO <select> anywhere. The "Show me" period chooser is a
    link-based dropdown, which is why a select-based lookup finds nothing.
  * It does not need to be opened. Every period's row, each with its own PDF
    link, is already in the DOM on plain page load (24 links before any
    interaction, the same 24 after opening the chooser). Discovery is
    therefore ONE READ with nothing clicked and nothing swept - no accordions
    and no per-year sweep, which is all the Chase app's machinery existed for.
  * A statement is served directly:
        GET /cardmembersvcs/statements/app/stmtPDF?view=true&date=YYYYMMDD
          -> 200 application/pdf
             content-disposition: inline;
               filename=Discover-Statement-20250115-1234.pdf
    where date is the statement's CLOSING date. The bytes are fetched with the
    context's own cookies, using the href READ FROM THE PAGE - not a URL built
    from a template, so a change to the query string cannot silently fetch the
    wrong period. The served filename also carries the card's last four, which
    is the only place a single-card login states them.
  * The neighbouring "Download" control opens a MODAL DIALOG (a transactions
    export, not the statement PDF), and "Print" opens a popup. Neither is used:
    answering a dialog is exactly what this project never does.
  * History observed: 24 statements, the oldest .. the newest - about two
    years. Older statements are not reachable from this page and are not
    guessed at.
  * Discover shows an inactivity "stay logged in?" modal; only its keep-alive
    control is ever clicked (dismiss_timeout).

STILL UNVERIFIED:
  * A login with MORE THAN ONE Discover card. This account has one, so no card
    chooser was observed and none is coded for. If one exists, the last four in
    each served filename is the handle to tell statements apart - do not infer
    a card from row position. Attributing by position rather than by what the
    document itself says filed one card's statements under another during the
    Chase build, and the output looked entirely plausible.
  * Whether Discover blocks the bundled Chromium. This app uses a real browser
    regardless; see above.

OUT OF SCOPE: tax documents. Discover Bank issues 1099-INT for deposit
accounts, which this app does not cover; a card account's only tax-ish
document is an occasional 1099-C or 1099-MISC. `document_types` in config
lists Statement only, so a stray one is classified and then skipped rather
than half-filed.
"""
# Site layer verified working against the live site: 2026-08-19
# (discovery of 24 statements spanning about two years, and one PDF
# fetched and checked: 4 pages, card ...1234, %PDF-1.7).
from __future__ import annotations

import html as _html
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

log = logging.getLogger("discovercard_docs.site")

BASE = "https://card.discover.com"
PUBLIC = "https://www.discover.com"
URLS = {
    "home": f"{BASE}/cardmembersvcs/achome/homepage",
    "login": f"{PUBLIC}/",
    # CONFIRMED 2026-08-19. "Activity & Statements", hash-routed within one
    # page: #/recent (transactions to date), #/current, #/stmt_YYYYMMDD.
    # page.goto works and keeps the session - Discover does NOT need the
    # click-only navigation Ally and Chase did.
    #
    # #/recent is the right landing route: the statement index is present on
    # any of them, and #/recent is the page's own default.
    "documents": f"{BASE}/cardmembersvcs/statements/app/activity#/recent",
    "documents_alt": f"{BASE}/cardmembersvcs/statements/app/activity",
    # kept only as a last resort if the route above is ever retired
    "documents_alt2": f"{BASE}/cardmembersvcs/statements/app/statement",
    "statements": f"{BASE}/cardmembersvcs/statements",
}
# Only the two CONFIRMED routes. The speculative ones were removed after a
# live run ended on Discover's logoff page: a bad path under /cardmembersvcs/
# may end the session, and even if that run was really an inactivity timeout
# (it could not be told apart afterwards), guessing paths on a bank while
# signed in is not worth the doubt. If both of these stop working, click the
# app's own nav - that is the fallback below, not more guesses.
DOCUMENT_URL_CANDIDATES = [URLS["documents"], URLS["documents_alt"]]

# Confirmed live: a signed-out session lands on
#   portal.discover.com/customersvcs/universalLogin/logoff_confirmed
# which matched NONE of the original markers - "universalLogin" does not
# contain "/login". The app therefore kept trying instead of telling the user
# to sign in again, which is the worst of both: no documents and no
# explanation. Substring matching on a URL is brittle; these are deliberately
# generous.
LOGIN_URL_MARKERS = ["/logon", "/login", "/signin", "/sign-in", "/auth/logon",
                     "/idp", "/mfa", "/verify", "/cardmembersvcs/authentication",
                     "universallogin", "logoff", "logout", "loggedout",
                     "signed-out", "signedout", "sessionend", "session-expired",
                     "timeout"]

# ---------------------------------------------------------------------------
# HARD SAFETY GUARD - never click anything matching this. Tuned for a bank.
# ---------------------------------------------------------------------------
FORBIDDEN_CONTROL_RE = re.compile(
    # money movement
    r"(transfer|deposit|withdraw|wire\b|move\s+money|send\s+money|zelle|"
    r"pay\b|payment|pay\s+bills?|bill\s*pay|autopay|auto-?pay|schedule\s+payment|"
    r"pay\s+card|make\s+a\s+payment|"
    # card-specific products and offers. Discover's own names matter here:
    # its rewards currency is "Cashback Bonus" (and "Miles" on Discover it
    # Miles), its card-lock feature is "Freeze It", and its shopping portal is
    # "Discover Deals" - none of which the Chase vocabulary would have caught.
    r"balance\s+transfer|cash\s+advance|credit\s+line|credit\s+limit|"
    r"redeem|rewards?\b|points\b|miles\b|cash\s*back|cashback|"
    r"offers?\b|deals?\b|refer\s+a\s+friend|"
    r"discover\s+deals|shop\s+(with|through)|book\s+travel|"
    r"credit\s+scorecard|fico|spend\s+analyzer|"
    # applications and account changes
    r"apply|open\s+(a|an|another|new)\b[\w\s]{0,24}\baccount\b|"
    r"open\s+\w{0,12}\s*account\b|get\s+(a\s+)?(quote|started|loan|card)|"
    r"add\s+(funds|card|authorized)|authorized\s+user|"
    r"dispute|report\s+(a\s+)?(problem|fraud|lost|stolen)|"
    r"lock\s+card|unlock\s+card|freeze|freeze\s*it|activate|replace\s+card|"
    r"close\s+account|report\s+lost|report\s+stolen|"
    r"request\b|increase\b|"
    # settings
    r"change\s+|edit\s+|update\s+|set\s+up|enable|disable|delete|remove|"
    r"beneficiar|payee|contact\s+info|password|username|"
    r"paperless|delivery\s+preference|alerts?\s+settings|"
    # anything that commits
    r"send\b|submit|confirm|continue|next|agree|accept|sign\b|authorize)", re.I)

SAFE_DOC_CONTROL_RE = re.compile(
    r"(download|view|open|save|print|pdf|statement|document|1099|1098|5498|"
    r"tax|e-?statement|year.?end)", re.I)

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

# ---------------------------------------------------------------------------
# Selectors. Repair these from Diagnostics/ after a --diagnose run.
# ---------------------------------------------------------------------------
FALLBACK = {
    "doc_row": ("table tbody tr, [role='row'], [class*='statement-row'], "
                "[class*='StatementRow'], [class*='documentRow'], "
                "[data-testid*='statement'], [data-testid*='document'], "
                "li[class*='statement'], li[class*='document']"),
    "doc_link": ("a[href*='.pdf'], a[href*='statement'], a[href*='document'], "
                 "a[download], button[class*='download']"),
    "download_control": ("a[download], a[href$='.pdf'], "
                         "button:has-text('Download'), button:has-text('View')"),
    "page_ready": ("table, [role='row'], [class*='statement'], [class*='document'], "
                   "main, [role='main']"),
    "account_select": "select, [role='combobox'], [role='listbox']",
    "next_page": ("a[aria-label*='Next' i], button[aria-label*='Next' i], "
                  ".pagination-next, [class*='next']"),
    "show_more": "button, a",
}

# A row control that opens/downloads one statement. Discover's form is UNKNOWN.
#
# The specific selectors below are tried first, then ROW_CONTROL_FALLBACK_SEL
# considers any button/link in the row. That two-stage shape is not padding:
# on ALLY the control turned out to be a plain <button> with no aria-label and
# no href, whose text was just "Statement" - the words "Download statement
# for:" lived in a separate visually-hidden element - so keying on aria-label
# or on the word "Download" found nothing at all. Expect Discover to be
# similarly unhelpful in its own way.
#
# Either way the element's own accessible name must clear is_safe_control(),
# so widening the net does not widen what may be clicked.
ROW_CONTROL_SEL = ("a[href$='.pdf'], a[download], "
                   "a[aria-label*='statement' i], a[aria-label*='download' i], "
                   "button[aria-label*='statement' i], button[aria-label*='download' i], "
                   "button[aria-label*='view' i], "
                   "a:has-text('Download'), a:has-text('View'), "
                   "button:has-text('Download'), button:has-text('View'), "
                   "button:has-text('PDF'), a:has-text('PDF')")
ROW_CONTROL_FALLBACK_SEL = "button, a"

# ---------------------------------------------------------------------------
# Date parsing (shared with the other projects)
# ---------------------------------------------------------------------------
DATE_PATTERNS = [
    (re.compile(r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
                r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|"
                r"Dec(?:ember)?)\.?\s+(\d{1,2}),?\s+(\d{4})", re.I), "mdY"),
    (re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b"), "mdy_slash"),
    (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"), "iso"),
]
_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
MONTH_YEAR_RE = re.compile(
    r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
    r"Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    r"\s+(\d{4})", re.I)
QUARTER_RE = re.compile(r"\bQ([1-4])\s*[' ]?\s*(\d{4})\b", re.I)
YEAR_RE = re.compile(r"\b(19|20)(\d{2})\b")
_LAST_DAY = {1: 31, 2: 28, 3: 31, 4: 30, 5: 31, 6: 30,
             7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31}


def _last_day(year: int, month: int) -> int:
    if month == 2 and (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)):
        return 29
    return _LAST_DAY[month]


def parse_date(text: str) -> Optional[str]:
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


def parse_period_date(text: str) -> Tuple[Optional[str], str]:
    """Date to file a document under, plus a human period label. Statements
    titled by period ("December 2025", "Q4 2025", "2025") file on the last
    day of that period."""
    text = text or ""
    exact = parse_date(text)
    if exact:
        return exact, ""
    m = MONTH_YEAR_RE.search(text)
    if m:
        month = _MONTHS[m.group(1)[:3].lower()]
        year = int(m.group(2))
        return f"{year:04d}-{month:02d}-{_last_day(year, month):02d}", m.group(0)
    m = QUARTER_RE.search(text)
    if m:
        q, year = int(m.group(1)), int(m.group(2))
        month = q * 3
        return f"{year:04d}-{month:02d}-{_last_day(year, month):02d}", f"Q{q} {year}"
    m = YEAR_RE.search(text)
    if m:
        year = int(m.group(1) + m.group(2))
        return f"{year:04d}-12-31", str(year)
    return None, ""


# ---------------------------------------------------------------------------
# Session / safety
# ---------------------------------------------------------------------------

# A page that is not part of the signed-in application at all: a 404, or the
# public marketing site. Reached by a wrong guessed URL, and the reason the
# first live probe ended up poking Discover's public login form.
PUBLIC_OR_ERROR_MARKERS = [
    "error404", "/404", "page-not-found", "pagenotfound", "error.shtml",
    "www.discover.com/discover/data/misc",
]


def looks_public_or_error(page) -> bool:
    """True when the current page is a 404 or the public site.

    Checked before ANY control on the page is read or written. A wrong URL
    guess is expected during a first probe; treating whatever it lands on as
    if it were the application is what turns that into a safety problem.
    """
    url = (page.url or "").lower()
    if any(m in url for m in PUBLIC_OR_ERROR_MARKERS):
        return True
    # the public site is a different host from the signed-in card portal
    if url.startswith("https://www.discover.com/") and "/cardmembersvcs" not in url:
        return True
    return False


def looks_signed_out(page) -> bool:
    url = (page.url or "").lower()
    if any(m in url for m in LOGIN_URL_MARKERS):
        return True
    if looks_public_or_error(page):
        return True
    try:
        if page.locator("input[type='password']").count() > 0:
            return True
    except Exception:
        pass
    return False


def detect_security_challenge(page) -> Optional[str]:
    """Conservative: if a document list rendered, it is a normal page."""
    try:
        if page.locator(FALLBACK["doc_row"]).count() > 2:
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
    """A control may be clicked only if it looks like a document action AND
    matches nothing in the forbidden list."""
    name = (name or "").strip()
    if not name:
        return False
    if FORBIDDEN_CONTROL_RE.search(name):
        return False
    return bool(SAFE_DOC_CONTROL_RE.search(name))


def dismiss_timeout(page) -> None:
    """Discover shows an inactivity modal with a keep-alive button. Clicking it
    only extends the session - it moves no money and changes no setting.
    Anything else in that modal (including 'Log out') is left alone."""
    for pattern in (r"i'?m still here", r"stay (signed|logged) in",
                    r"continue session", r"keep me (signed|logged) in"):
        try:
            c = page.get_by_role("button", name=re.compile(pattern, re.I))
            if c.count() and c.first.is_visible():
                c.first.click()
                page.wait_for_timeout(1000)
                return
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Documents page
# ---------------------------------------------------------------------------

# Discover's top nav is "Activity" (a menu), and the page itself is titled
# "Activity & Statements". Clicking nav is only the fallback here, since
# page.goto works.
DOCUMENTS_NAV_RE = re.compile(
    r"^\s*(activity(\s*(&|and)\s*statements?)?|documents?|"
    r"statements?\s*(&|and)\s*documents?|statements?)\s*(menu)?\s*$", re.I)


def on_documents_page(page) -> bool:
    """Are we on the statements page?

    The test is whether the page publishes statement PDF links - not whether
    it says "Statements" anywhere. A page that merely has the word on it, or a
    public 404 that happens to render a nav, does not count.
    """
    try:
        if looks_public_or_error(page):
            return False
        return page.locator(STMT_PDF_SEL).count() > 0
    except Exception:
        return False


def click_documents_nav(page) -> bool:
    """Reach the documents area by clicking the app's own nav control.

    Tried BEFORE any URL in DOCUMENT_URL_CANDIDATES. Whether Discover needs
    this is unknown - its portal may well accept a pasted URL. The ordering is
    kept because on ALLY a pasted hash fragment silently left you on the
    dashboard (where the account dropdown belongs to a transfer widget), and on
    CHASE every guessed URL was wrong while the nav click worked. Clicking
    first costs one click and removes a whole class of silent failure.

    The label must clear the read-only guard first."""
    for role in ("button", "link"):
        try:
            loc = page.get_by_role(role, name=DOCUMENTS_NAV_RE)
            if loc.count() == 0:
                continue
            for i in range(min(loc.count(), 4)):
                c = loc.nth(i)
                try:
                    if not c.is_visible():
                        continue
                    label = (c.inner_text(timeout=1000) or "").strip()
                except Exception:
                    continue
                if not is_safe_control(label):
                    continue
                c.click()
                page.wait_for_timeout(3500)
                dismiss_timeout(page)
                log.info("clicked %s %r -> %s", role, label, page.url)
                if on_documents_page(page):
                    return True
                # the nav may open a submenu (Statements / Tax Forms)
                for sub in ("statements", "tax forms"):
                    try:
                        s = page.get_by_role("link", name=re.compile(rf"^\s*{sub}\s*$", re.I))
                        if s.count() and s.first.is_visible():
                            s.first.click()
                            page.wait_for_timeout(3000)
                            dismiss_timeout(page)
                            log.info("clicked submenu %r -> %s", sub, page.url)
                            if on_documents_page(page):
                                return True
                    except Exception:
                        pass
        except Exception as e:
            log.info("documents nav (%s) failed: %s", role, e)
    return False


def goto_documents(page) -> bool:
    """Navigate to a document area.

    Order matters. The SPA's own nav is tried FIRST because a hash-route goto
    silently leaves you on the dashboard - where the account dropdown belongs
    to a transfer widget, not to a statements list. Only then are the known
    URLs tried, and failing everything we keep whatever page is open so you
    can navigate there by hand and the tool still reads it.
    """
    dismiss_timeout(page)
    if on_documents_page(page):
        return True
    # Discover accepts a pasted URL, so try that first here - the reverse of
    # the Ally/Chase ordering, and confirmed to work.
    for url in DOCUMENT_URL_CANDIDATES[:2]:
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(4000)
            dismiss_timeout(page)
            if looks_public_or_error(page) or looks_signed_out(page):
                break
            if on_documents_page(page):
                log.info("statements page reached at %s", page.url)
                return True
        except Exception as e:
            log.info("documents URL %s failed: %s", url, str(e).splitlines()[0][:70])
    if click_documents_nav(page):
        log.info("documents area reached at %s", page.url)
        return True
    # Signed out already? Say so instead of navigating around a dead session.
    if looks_signed_out(page):
        log.info("session is signed out (%s) - not navigating", page.url[:70])
        return False
    started_at = page.url
    for url in DOCUMENT_URL_CANDIDATES:
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3500)
            dismiss_timeout(page)
            if looks_public_or_error(page):
                # A wrong guess. Go back to where the user left us rather than
                # leaving them stranded on a 404 with the public site's login
                # form on screen, and stop guessing.
                log.info("URL %s landed on a public/error page - reverting", url)
                try:
                    page.goto(started_at, wait_until="domcontentloaded", timeout=45000)
                except Exception:
                    pass
                return False
            if looks_signed_out(page):
                return False
            try:
                page.wait_for_selector(FALLBACK["page_ready"], timeout=12000)
            except Exception:
                pass
            if on_documents_page(page):
                log.info("documents area reached at %s", page.url)
                return True
        except Exception as e:
            log.info("documents URL %s failed: %s", url, e)
    return on_documents_page(page)


def ensure_statements(page) -> bool:
    """Reuse the signed-in tab and make sure a statements list is showing.

    Discover's portal is a single-page app; if the session is held in memory a
    hard goto can bounce you out, so try the current page FIRST and only
    navigate when nothing statement-like is rendered.
    """
    dismiss_timeout(page)
    if on_documents_page(page):
        return True
    return goto_documents(page)


def scroll_full_page(page, rounds: int = 6, delay_ms: int = 700) -> None:
    try:
        for _ in range(rounds):
            page.mouse.wheel(0, 2500)
            page.wait_for_timeout(delay_ms)
        page.keyboard.press("End")
        page.wait_for_timeout(delay_ms)
    except Exception:
        pass


def expand_all(page) -> None:
    """Click only SAFE 'show more / load more / view all' controls."""
    for _ in range(25):
        clicked = False
        try:
            btn = page.get_by_role("button", name=re.compile(
                r"(show more|load more|view more|see more|view all|older|"
                r"more\s+statements|previous\s+statements)", re.I))
            if btn.count() > 0 and btn.first.is_visible():
                label = btn.first.inner_text(timeout=1000) or ""
                if not FORBIDDEN_CONTROL_RE.search(label):
                    btn.first.click()
                    page.wait_for_timeout(1500)
                    clicked = True
        except Exception:
            pass
        if not clicked:
            break


def next_page(page) -> bool:
    try:
        loc = page.locator(FALLBACK["next_page"])
        if loc.count() > 0 and loc.first.is_visible() and loc.first.is_enabled():
            label = (loc.first.inner_text(timeout=800) or "") + \
                (loc.first.get_attribute("aria-label") or "")
            if FORBIDDEN_CONTROL_RE.search(label):
                return False
            loc.first.click()
            page.wait_for_timeout(2500)
            return True
    except Exception:
        pass
    return False


@dataclass
class RawDoc:
    title: str
    account: str = ""
    date_text: str = ""
    href: str = ""
    text: str = ""
    row_index: int = -1
    kind: str = "doc"


# ---------------------------------------------------------------------------
# Row scraping
#
# Generic on purpose until the live DOM is probed: any row carrying a date AND
# a control that looks like "view / download / PDF" is a statement row. Once
# --diagnose shows the real markup, tighten _ROW_JS to Discover's actual
# testids/classes so unrelated rows can never be picked up.
# ---------------------------------------------------------------------------
_ROW_JS = r"""() => {
  const DATE_RE = /(\d{1,2}\/\d{1,2}\/\d{4})|((Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4})|((Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4})/i;
  const CTRL = "a[href$='.pdf'], a[download], a[aria-label], button[aria-label], a, button";
  const SAFE = /(download|view|open|save|print|pdf|statement|document|1099|1098|5498|tax)/i;
  const rows = new Set();
  for (const sel of ['table tr', "[role='row']", "li", "[class*='statement']", "[class*='document']"]) {
    for (const el of document.querySelectorAll(sel)) rows.add(el);
  }
  const out = [];
  for (const el of rows) {
    // skip containers that hold other candidate rows (keep the innermost)
    if (el.querySelector("table tr, [role='row']")) continue;
    const text = (el.innerText || '').replace(/\s+/g, ' ').trim();
    if (!text || text.length > 400) continue;
    const m = text.match(DATE_RE);
    if (!m) continue;
    let ctrl = null;
    for (const c of el.querySelectorAll(CTRL)) {
      const label = ((c.innerText || '') + ' ' + (c.getAttribute('aria-label') || '') +
                     ' ' + (c.getAttribute('href') || '')).trim();
      if (SAFE.test(label)) { ctrl = { label: label.slice(0, 80),
                                       href: c.getAttribute('href') || '',
                                       tag: c.tagName.toLowerCase() }; break; }
    }
    if (!ctrl) continue;
    out.push({ date_text: m[0], text: text.slice(0, 300),
               title: text.replace(m[0], '').replace(/\s+/g, ' ').trim().slice(0, 120),
               ctrl_label: ctrl.label, href: ctrl.href, tag: ctrl.tag });
  }
  return out;
}"""


def collect_documents(page) -> List[RawDoc]:
    """Rows currently rendered. Used by --diagnose (and as the generic
    fallback inside discovercard_collect)."""
    docs: List[RawDoc] = []
    seen = set()
    try:
        rows = page.evaluate(_ROW_JS)
    except Exception as e:
        log.info("row scrape failed: %s", e)
        rows = []
    for i, r in enumerate(rows):
        title = _html.unescape(r.get("title", "")).strip() or "Statement"
        date_text = r.get("date_text", "")
        # Two of the three statements on a date are described IDENTICALLY, so
        # de-duplicating on (title, date) silently threw one away - 24 real
        # rows collapsed to 16. Position is part of the identity here.
        key = (title, date_text, i)
        if key in seen:
            continue
        seen.add(key)
        docs.append(RawDoc(title=title[:200], date_text=date_text,
                           href=r.get("href", ""), text=r.get("text", ""),
                           row_index=i))
    return docs


# ---------------------------------------------------------------------------
# Account + period selectors
#
# SAFETY: a dropdown is a control too.
#
# On ALLY, the dashboard carried a money-TRANSFER widget whose first <select>
# was an account list (id "fromAccount"), indistinguishable from a statements
# account picker by its options alone - and the first live probe found exactly
# that and tried to set it. Selecting an option in a transfer form is not
# read-only behaviour even when nothing is submitted.
#
# A card dashboard has the same hazard in its "pay from" picker, so every
# <select> is identity-checked before it is read OR written, and the check
# FAILS CLOSED when an identity cannot be read.
# ---------------------------------------------------------------------------
_ACCOUNT_HINT_RE = re.compile(
    r"(checking|savings|money\s*market|\bcd\b|certificate|spending|"
    r"interest|account|x{2,}\d|\*{2,}\d|\.{3}\d{3,}|\d{4}\s*$)", re.I)

# A control belonging to a money-movement widget. Matched against the element's
# own identity (id/name/aria-label/placeholder/data-testid/allytmfn) AND its
# enclosing form/section, so a picker inside a transfer card is refused even
# when its own attributes look innocent.
MONEY_CONTROL_RE = re.compile(
    r"(from|to|source|destination|target)\s*_?-?account|"
    r"transfer|payment|pay\b|bill|deposit|withdraw|zelle|wire|remit|"
    r"send\s*money|move\s*money|recipient|payee|amount|frequency|schedule", re.I)

# A control that belongs to a SIGN-IN / registration form is off-limits, full
# stop. Non-negotiable #2 is that this tool never touches authentication.
#
# This is not hypothetical: the first live Discover probe walked its guessed
# URLs onto a public 404 page, found the marketing site's "what do you want to
# log into" dropdown (identity "choose-card | login-form | loginForm", options
# "Credit Card / Bank Account / Student Loans / ...") and tried to SET it. The
# money-control test did not match - correctly, it is not a transfer widget -
# so nothing refused it. The enclosing form's id was already in the identity
# string; nothing was asking about it.
AUTH_CONTROL_RE = re.compile(
    r"log[\s_-]?(in|on)|sign[\s_-]?(in|on|up)|signin|logon|"
    r"authenticat|credential|register|enroll(ment)?\b|"
    r"username|user[\s_-]?id|password|passcode|remember\s*me", re.I)

# A PRODUCT chooser ("which Discover product?") is not a document picker, and
# options alone give it away wherever it appears.
PRODUCT_PICKER_RE = re.compile(
    r"bank\s+account|student\s+loans?|personal\s+loans?|home\s+loans?|"
    r"mortgage|auto\s+loans?|certificate\s+of\s+deposit|"
    r"select\s+an?\s+account", re.I)

# What the element identity JS returns for a control inside a money widget.
_IDENTITY_JS = r"""el => {
  const attrs = ['id','name','aria-label','placeholder','data-testid',
                 'allytmfn','data-allytmfn','data-track-name'];
  const bits = attrs.map(a => el.getAttribute(a) || '');
  const form = el.closest('form');
  if (form) bits.push(form.id || '', form.getAttribute('name') || '',
                      form.getAttribute('aria-label') || '');
  // the nearest labelled section/card this control lives in
  const sect = el.closest("section, [role='region'], [class*='card'], [class*='Card'], " +
                          "[class*='widget'], [class*='Widget'], [class*='module']");
  if (sect) {
    bits.push(sect.getAttribute('aria-label') || '', sect.className || '');
    const h = sect.querySelector('h1,h2,h3,h4,legend');
    if (h) bits.push((h.innerText || '').slice(0, 60));
  }
  const lbl = el.id ? document.querySelector(`label[for="${CSS.escape(el.id)}"]`) : null;
  if (lbl) bits.push((lbl.innerText || '').slice(0, 60));
  return bits.filter(Boolean).join(' | ');
}"""


def control_identity(loc) -> str:
    """Every name this control answers to: its own attributes, its label, its
    form, and the card it sits in."""
    try:
        return loc.evaluate(_IDENTITY_JS) or ""
    except Exception:
        return ""


def is_forbidden_control_context(identity: str, options: Optional[List[str]] = None) -> bool:
    """True when this control must not be read OR written, for any reason.

    Fails CLOSED: an identity we could not read at all is treated as unsafe.
    Three independent reasons, any one of which is disqualifying:
      * it is part of a money-movement widget      (MONEY_CONTROL_RE)
      * it is part of a sign-in / registration form (AUTH_CONTROL_RE)
      * its OPTIONS describe Discover products rather than documents
        (PRODUCT_PICKER_RE) - context-free, so it holds on any page
    """
    if not identity:
        return True
    if (MONEY_CONTROL_RE.search(identity) or AUTH_CONTROL_RE.search(identity)
            or FORBIDDEN_CONTROL_RE.search(identity)
            or PRODUCT_PICKER_RE.search(identity)):
        return True
    for opt in options or []:
        if PRODUCT_PICKER_RE.search(opt or ""):
            return True
    return False


def is_money_control(identity: str) -> bool:
    """True if this control belongs to anything that moves money. Fails
    CLOSED: an identity we could not read at all is treated as unsafe."""
    if not identity:
        return True
    return bool(MONEY_CONTROL_RE.search(identity)
                or FORBIDDEN_CONTROL_RE.search(identity))


def _safe_selects(page, limit: int = 12):
    """Yield (locator, identity) for the <select> elements that are NOT part of
    a money-movement widget."""
    try:
        loc = page.locator("select")
        n = min(loc.count(), limit)
    except Exception:
        return
    for i in range(n):
        s = loc.nth(i)
        identity = control_identity(s)
        # Options are read (harmless) before any decision, because a product
        # picker is identifiable from its options alone even when its identity
        # looks innocent.
        try:
            options = s.locator("option").all_text_contents()
        except Exception:
            options = []
        if is_forbidden_control_context(identity, options):
            log.info("refusing dropdown: %s", (identity or "<unreadable>")[:120])
            continue
        yield s, identity


def describe_selects(page, limit: int = 12) -> List[dict]:
    """Every <select> on the page with its identity and the guard's verdict.
    Diagnostic only - it reads, and never sets, anything. If a real statements
    picker is ever refused, this is where you will see why."""
    out: List[dict] = []
    try:
        loc = page.locator("select")
        n = min(loc.count(), limit)
    except Exception:
        return out
    for i in range(n):
        s = loc.nth(i)
        identity = control_identity(s)
        try:
            opts = [o.strip() for o in s.locator("option").all_inner_texts()][:12]
        except Exception:
            opts = []
        reasons = []
        if not identity:
            reasons.append("unreadable identity (fails closed)")
        else:
            if MONEY_CONTROL_RE.search(identity):
                reasons.append("money widget")
            if AUTH_CONTROL_RE.search(identity):
                reasons.append("sign-in form")
            if FORBIDDEN_CONTROL_RE.search(identity):
                reasons.append("forbidden control")
            if PRODUCT_PICKER_RE.search(identity):
                reasons.append("product picker (identity)")
        if any(PRODUCT_PICKER_RE.search(o or "") for o in opts):
            reasons.append("product picker (options)")
        out.append({"identity": identity[:200],
                    "refused": bool(reasons),
                    "refused_because": reasons,
                    # kept under the old key so existing notes/tools still read
                    "refused_as_money_control": is_forbidden_control_context(identity, opts),
                    "option_count": len(opts),
                    # option labels can carry balances - keep only their shape
                    "option_sample": [re.sub(r"\$[\d,.]+", "$…", o)[:60] for o in opts[:6]]})
    return out


def account_select(page):
    """Return (locator, [labels]) for a <select> that lists accounts, or
    (None, []).

    Money-movement widgets, sign-in forms and product pickers are refused
    outright by _safe_selects before this ever sees them.
    """
    for s, _identity in _safe_selects(page):
        try:
            opts = [o.strip() for o in s.locator("option").all_inner_texts()]
        except Exception:
            continue
        accts = [o for o in opts if o and _ACCOUNT_HINT_RE.search(o)
                 and not re.fullmatch(r"20\d{2}", o)]
        if accts:
            return s, accts
    return None, []


def year_select(page):
    """A <select> whose options are years (statement archives are usually
    split by year). Returns (locator, [years]) or (None, [])."""
    for s, _identity in _safe_selects(page):
        try:
            opts = [o.strip() for o in s.locator("option").all_inner_texts()]
        except Exception:
            continue
        years = [o for o in opts if re.fullmatch(r"20\d{2}", o)]
        if years:
            return s, years
    return None, []


def _select_option(page, sel, label: str) -> bool:
    """Set a dropdown - but never one attached to a money-movement widget.

    Re-checked here as well as in _safe_selects: this is the only function
    that writes to a control, so it must be safe on its own terms no matter
    which caller reached it.
    """
    identity = control_identity(sel)
    if is_money_control(identity):
        log.warning("REFUSED to set a money-movement control: %s", identity[:160])
        return False
    if FORBIDDEN_CONTROL_RE.search(label or ""):
        log.warning("REFUSED option %r - matches the forbidden list", label)
        return False
    try:
        sel.select_option(label=label, timeout=8000)
        page.wait_for_timeout(2500)
        dismiss_timeout(page)
        return True
    except Exception as e:
        log.info("could not select %r: %s", label, str(e).split("\n")[0])
        return False


def discovercard_collect(page) -> List[dict]:
    """Every statement Discover still has: a list of {account, date, title}.

    Walks the account dropdown (if there is one) and, within each account,
    every year in the period dropdown - so the full history is captured, not
    just the default view.

    This is the DOM fallback. discovercard_collect_via_api is tried first; this runs
    only if the API answered nothing (a redesign, or a locked-down session).
    """
    docs: List[dict] = []
    seen = set()

    def grab(acct: str):
        expand_all(page)
        scroll_full_page(page, rounds=3)
        for r in collect_documents(page):
            date, _ = parse_period_date(r.date_text or r.text)
            if not date:
                continue
            key = (acct, date, r.title)
            if key in seen:
                continue
            seen.add(key)
            docs.append({"account": acct, "date": date,
                         "title": r.title or "Statement"})

    def walk_years(acct: str):
        sel, years = year_select(page)
        if sel is not None and years:
            for y in years:
                if _select_option(page, sel, y):
                    grab(acct)
        else:
            grab(acct)
            # no year dropdown: try pagination instead
            for _ in range(30):
                if not next_page(page):
                    break
                grab(acct)

    acct_sel, accounts = account_select(page)
    if acct_sel is not None and accounts:
        for a in accounts:
            if not _select_option(page, acct_sel, a):
                continue
            walk_years(re.sub(r"\s+", " ", a).strip())
    else:
        walk_years("")
    return docs


# ---------------------------------------------------------------------------
# Download
#
# Three mechanisms are tried in order, because which one Discover uses is the key
# unknown until the live probe: a real browser download event, a blob/PDF tab,
# and a direct PDF href fetched from the page context (which carries the
# session cookies). Whichever wins, the bytes are checked for %PDF- before the
# file is written.
# ---------------------------------------------------------------------------
def _write_if_pdf(data: bytes, out_path: Path) -> bool:
    if not data or b"%PDF-" not in data[:1024]:
        return False
    out_path.write_bytes(data)
    return True


def _row_download_control(row):
    """The row's own download control, or None.

    Tries the explicit selectors first, then any button/link in the row -
    Discover's control announces itself only through its text. In BOTH passes the
    control's own accessible name must pass is_safe_control(), so a money
    control in a row could never be picked up by the wider pass.
    """
    for sel in (ROW_CONTROL_SEL, ROW_CONTROL_FALLBACK_SEL):
        try:
            ctrl = row.locator(sel)
            n = min(ctrl.count(), 8)
        except Exception:
            continue
        for j in range(n):
            c = ctrl.nth(j)
            try:
                label = ((c.inner_text(timeout=500) or "") + " " +
                         (c.get_attribute("aria-label") or "") + " " +
                         (c.get_attribute("href") or ""))
            except Exception:
                continue
            if is_safe_control(label):
                return c
    return None


# ===========================================================================
# Downloading a statement. CONFIRMED LIVE 2026-08-19.
#
# Discover serves each statement at its own URL, which the page itself puts in
# an <a href> - one per period, all present on load:
#
#     GET /cardmembersvcs/statements/app/stmtPDF?view=true&date=YYYYMMDD
#       -> 200 application/pdf
#          content-disposition: inline;
#            filename=Discover-Statement-20250115-1234.pdf
#
# So there is nothing to click. The bytes are fetched with the browser
# context's own authenticated request (cookie session, same origin, plain GET
# of a URL the page published). This is NOT the "synthesise an endpoint" move
# that failed on Ally: that guessed a URL and needed an Authorization header
# the SPA added in JavaScript. Here the href is read from the DOM and used
# verbatim.
#
# Not clicking is also what keeps this read-only in the strongest sense: the
# "Download" control next to it opens a MODAL DIALOG (a transactions export,
# not the statement), and answering a dialog is exactly what this project
# never does.
#
# The server's filename carries the card's last four digits, which is the only
# place a single-card login states them.
# ===========================================================================
CD_FILENAME_RE = re.compile(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)", re.I)
CD_LAST4_RE = re.compile(r"-(\d{4})\.pdf$", re.I)


def served_last4(disposition: str) -> str:
    """The card's last 4 from the served filename, or ""."""
    m = CD_FILENAME_RE.search(disposition or "")
    if not m:
        return ""
    m2 = CD_LAST4_RE.search(m.group(1).strip())
    return m2.group(1) if m2 else ""


def discovercard_download(page, ctx, account: str, date: str, out_path,
                   occurrence: int = 0, document_id: str = "",
                   title: str = "") -> bool:
    """Download one statement PDF.

    `document_id` is the statement's own URL as discovery read it from the
    page. Nothing is clicked and nothing is navigated: the file is fetched
    with the signed-in context's cookies and written only if it really is a
    PDF and really is the statement that was asked for.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    href = document_id or ""
    if not href:
        # Re-find it on the page by its date, rather than rebuilding the URL
        # from a template - if Discover changes the query string, guessing it
        # would download the wrong period under a confident filename.
        href = statement_href_for(page, date)
    if not href:
        log.info("no statement URL for %s", date)
        return False

    # The URL must still be one of Discover's own statement URLs, and must
    # still name the date we want. A stored href from an earlier run cannot
    # send this anywhere else.
    if not STMT_PDF_RE.search(href):
        log.warning("refusing a non-statement URL for %s: %s", date, href[:80])
        return False
    want = date.replace("-", "")
    if want and want not in href:
        log.warning("MISMATCH: %s does not name %s - refusing", href[:80], want)
        return False

    url = href if href.startswith("http") else BASE + href
    try:
        resp = ctx.request.get(url, timeout=90000)
    except Exception as e:
        log.info("fetch failed for %s: %s", date, str(e).splitlines()[0][:80])
        return False
    if resp.status != 200:
        log.info("statement %s returned HTTP %s", date, resp.status)
        return False
    ctype = (resp.headers.get("content-type") or "").lower()
    if "pdf" not in ctype:
        # An HTML body here usually means the session lapsed and Discover
        # answered with a sign-in page. Do not write it.
        log.info("statement %s came back as %r, not a PDF", date, ctype[:40])
        return False
    try:
        data = resp.body()
    except Exception as e:
        log.info("could not read body for %s: %s", date, e)
        return False
    if not _write_if_pdf(data, out_path):
        return False
    last4 = served_last4(resp.headers.get("content-disposition", ""))
    log.info("saved %s (%d bytes%s)", date, len(data),
             f", card ...{last4}" if last4 else "")
    return True


_DIGITS_RE = re.compile(r"\d{4,}")


def _redact(value):
    """Mask long digit runs (account/document numbers) but keep the shape."""
    if isinstance(value, str):
        return _DIGITS_RE.sub(lambda m: m.group(0)[:2] + "…" + m.group(0)[-2:], value)
    return value


# NOT a known Discover endpoint - a candidate shape only, so that IF Discover
# turns out to answer a document list as JSON, probe_statements_api reports its
# records. probe_api (below) is the one that finds endpoints without guessing.
DOCREF_API_RE = re.compile(r"/(documents?|statements?|docref)[a-z/]*/(list|search)|"
                           r"/statements?\?|/documents?\?", re.I)


def probe_statements_api(page) -> dict:
    """Report the statement index exactly as the page publishes it.

    Discover needs no API call for discovery - the whole index is static
    markup - so this reports what a read of that markup yields: how many PDF
    links there are, their date range, a sample of the period labels, and
    whether any link was refused by the read-only guard. That is the thing to
    compare against after a redesign.

    Read-only, and it neither clicks nor navigates.
    """
    try:
        ensure_statements(page)
        page.wait_for_timeout(1200)
    except Exception as e:
        log.info("probe_statements_api: %s", e)
    try:
        raw_links = page.locator(STMT_PDF_SEL).count()
    except Exception:
        raw_links = 0
    recs = statement_links(page)
    dates = [r["date"] for r in recs]
    return {
        "pdf_links_in_dom": raw_links,
        "statements": len(recs),
        "oldest": dates[-1] if dates else "",
        "newest": dates[0] if dates else "",
        "period_labels_sample": [r["period"] for r in recs[:4] if r["period"]],
        "href_shape": _redact(recs[0]["href"]) if recs else "",
        "note": "pdf_links_in_dom may exceed statements: the period chooser's "
                "markup repeats a link. Discovery de-duplicates by date.",
    }


def probe_api(page, seconds: int = 25) -> List[dict]:
    """Watch the SPA's JSON traffic while the statements area loads, and
    report endpoints whose payload looks like a document list."""
    hits: List[dict] = []

    def on_resp(r):
        try:
            ct = (r.headers.get("content-type", "") or "").lower()
            if "json" not in ct:
                return
            body = r.text()
            if len(body) > 400000:
                body = body[:400000]
            low = body.lower()
            if not any(k in low for k in ("statement", "document", "pdf", "taxform")):
                return
            data = json.loads(body)
            keys = list(data.keys())[:20] if isinstance(data, dict) else ["<list>"]
            hits.append({"url": r.url.split("?")[0], "status": r.status,
                         "top_keys": keys, "sample": body[:600]})
        except Exception:
            pass

    page.on("response", on_resp)
    try:
        ensure_statements(page)
        page.wait_for_timeout(3000)
        expand_all(page)
        scroll_full_page(page, rounds=4)
        acct_sel, accounts = account_select(page)
        if acct_sel is not None:
            for a in accounts[:3]:
                _select_option(page, acct_sel, a)
        sel, years = year_select(page)
        if sel is not None:
            for y in years[:3]:
                _select_option(page, sel, y)
        page.wait_for_timeout(int(seconds * 100))
    except Exception as e:
        log.info("probe_api: %s", e)
    finally:
        try:
            page.remove_listener("response", on_resp)
        except Exception:
            pass

    # de-duplicate by endpoint, keep the first sample of each
    out, seen = [], set()
    for h in hits:
        if h["url"] in seen:
            continue
        seen.add(h["url"])
        out.append(h)
    return out


# ===========================================================================
# Discovery. CONFIRMED LIVE 2026-08-19.
#
# The statements page is
#     card.discover.com/cardmembersvcs/statements/app/activity
# with hash routes #/recent, #/current and #/stmt_YYYYMMDD. page.goto works
# and keeps the session (unlike Ally and Chase, where it did not).
#
# The page's "Show me" period chooser is a link-based dropdown, NOT a <select>
# - which is why a select-based lookup finds nothing here. It does not need to
# be opened: every period's row, each with its own PDF link, is already in the
# DOM on plain page load. Verified: 24 links before any interaction, the same
# 24 after opening the chooser.
#
# So discovery is one read of
#     a[href*="stmtPDF"]   ->  ...stmtPDF?view=true&date=YYYYMMDD
# where the date is the statement's CLOSING date, and the enclosing <li> gives
# the human period label ("Mar 16 - Apr 15, 2025", or "Current (...)").
#
# Nothing is clicked, no accordion is expanded, no period is swept. The Chase
# app needed all of that because its rows only existed while one card's
# accordion was open on one year; here the whole index is static markup.
#
# History observed: 24 statements, the oldest .. the newest - Discover keeps
# about two years online. Older ones are not reachable from this page and are
# not guessed at.
# ===========================================================================
STMT_PDF_RE = re.compile(r"/statements/app/stmtPDF\b[^\"\']*?date=(\d{8})", re.I)
STMT_PDF_SEL = "a[href*='stmtPDF']"
# "Mar 16 - Apr 15, 2025" / "Dec 16, 2024 - Jan 15, 2025" / "Current (...)"
PERIOD_LABEL_RE = re.compile(
    r"((?:Current\s*\()?[A-Z][a-z]{2}\s+\d{1,2}(?:,\s*\d{4})?\s*[-\u2013]\s*"
    r"[A-Z][a-z]{2}\s+\d{1,2},\s*\d{4}\)?)")


def _iso_from_yyyymmdd(raw: str) -> str:
    return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}" if re.fullmatch(r"\d{8}", raw or "") else ""


def statement_links(page) -> List[dict]:
    """Every statement Discover is offering, read from its own PDF links.

    One plain read of the DOM - no clicking, no expanding, no navigation.
    Returns {date, href, period, occurrence, ambiguous, documentId} per
    statement, de-duplicated by date (the markup repeats a link when the
    chooser is open).
    """
    out: List[dict] = []
    seen = set()
    try:
        loc = page.locator(STMT_PDF_SEL)
        n = min(loc.count(), 400)
    except Exception as e:
        log.info("could not read statement links: %s", e)
        return []
    for i in range(n):
        el = loc.nth(i)
        try:
            href = el.get_attribute("href") or ""
        except Exception:
            continue
        m = STMT_PDF_RE.search(href)
        if not m:
            continue
        date = _iso_from_yyyymmdd(m.group(1))
        if not date or date in seen:
            continue
        # The control must still clear the read-only guard, even though it is
        # only ever fetched and never clicked.
        try:
            label = " ".join((el.inner_text(timeout=600) or "").split())
        except Exception:
            label = ""
        if label and not is_safe_control(label):
            log.info("refusing statement control %r", label[:60])
            continue
        # The human period label lives on an ANCESTOR of the link, but not a
        # predictable one: closest('div') matches a bare wrapper holding only
        # the word "PDF". So walk up until the text actually looks like a
        # period, a few levels at most.
        period = ""
        try:
            texts = el.evaluate("""e => {
                const out = []; let n = e.parentElement;
                for (let i = 0; i < 5 && n; i++, n = n.parentElement) {
                    out.push(n.innerText || '');
                }
                return out;
            }""") or []
            for raw in texts:
                pm = PERIOD_LABEL_RE.search(" ".join(raw.split()))
                if pm:
                    period = pm.group(1).strip()
                    break
        except Exception:
            pass
        seen.add(date)
        out.append({"date": date, "href": href, "period": period,
                    # identity IS the URL: durable, and it re-finds the file
                    # without depending on row order.
                    "documentId": href,
                    "title": "Statement", "account": "",
                    "kind": "statement", "occurrence": 0, "ambiguous": False})
    out.sort(key=lambda r: r["date"], reverse=True)
    return out


def statement_href_for(page, date: str) -> str:
    """Re-find one statement's URL on the page by its closing date."""
    want = (date or "").replace("-", "")
    for rec in statement_links(page):
        if rec["date"].replace("-", "") == want:
            return rec["href"]
    return ""


def discovercard_collect_via_api(page) -> List[dict]:
    """Every statement Discover still offers.

    Named for the shared orchestrator's call site. There is no API call here
    and none is needed - the page publishes its whole statement index as
    links, so this is a single read with nothing clicked.
    """
    if not ensure_statements(page):
        log.info("statements page not reachable")
        return []
    scroll_full_page(page, rounds=2)
    recs = statement_links(page)
    if not recs:
        log.info("no statement PDF links found - the page layout may have changed; "
                 "run --diagnose and check STMT_PDF_SEL")
        return []
    log.info("Discover: %d statement(s), %s .. %s",
             len(recs), recs[-1]["date"], recs[0]["date"])
    return recs
