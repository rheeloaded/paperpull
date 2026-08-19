"""ALL U.S. Bank selectors, URLs, and page behavior live here.

When U.S. Bank changes its site, repair this file only.

SCOPE: U.S. Bank **credit cards** only. Checking, savings, money market, CDs,
mortgages, auto loans and U.S. Bancorp Investments accounts are out of scope
for this app.

SAFETY (this is a credit-card account):
  This module is strictly READ-ONLY. It opens the E-statements area, reads the
  list of statements, and downloads the PDFs U.S. Bank already generated. It
  must NEVER activate any control that pays a bill, sets up autopay, moves
  money, transfers a balance, takes a cash advance, orders a convenience
  check, starts an ExtendPay plan or a Simple Loan, redeems rewards or
  FlexPoints, books travel, requests a credit-line increase, disputes a
  charge, locks or replaces a card, applies for a product, or changes any
  setting. The guard is FORBIDDEN_CONTROL_RE; every click path checks it, and
  a control must ALSO look like a document action (SAFE_DOC_CONTROL_RE)
  before it may be clicked. Dropdowns are controls too - see
  MONEY_CONTROL_RE - and there is deliberately no code here that submits a
  form or confirms a dialog.

A REAL BROWSER, ALWAYS: `cmd_open_browser` asks for an installed Edge or
Chrome (prefer_real=True), like the Chase, Walmart and Verizon apps. Chase was
observed to fingerprint and block the Playwright Chromium build; whether
U.S. Bank does is untested, and this app does not intend to find out. A
tripped bot check on a bank can mean a step-up verification loop or a
temporary lock on a real account.

WHAT THE LIVE RUN ESTABLISHED (2026-08-19):
  * www.usbank.com redirects to onlinebanking.usbank.com/auth/login/ when
    signed out. Signed in, the whole portal is ONE hash-routed SPA under
    /digital/servicing/shellapp/.
  * The documents area is reached by clicking the app's own "Statements" nav,
    landing on #/highvolume/edocs/statements, titled "E-statements".
  * The page is a data-testid component tree with NO <table>, NO [role=row]
    and NO <select> anywhere - which is why a generic row scraper reads
    nothing here. See the SEL map below for the real containers.
  * Statements are grouped by an ACCOUNT SELECTOR, not by per-card
    accordions. On a single-account login it is static text, not a dropdown.
  * History comes from the "Document year" filter - a styled dropdown whose
    options are button[role=option], offering 2019-2026.
  * Each row carries TWO controls naming the SAME statement: a link ("View
    <date> statement in a new window.") and a button ("Download <date>
    statement."). Reading both counts every statement twice; the Download
    button alone is authoritative.
  * The list renders a SECOND section, "E-statement disclosures", with
    identical row markup, holding the Electronic document agreement. Its
    controls carry no aria-label and no date. Only sections whose heading
    ends in "statements" are read.
  * Downloads fire a real browser download event from the row's Download
    button.
  * An empty year is normal and renders "You have no statements for the
    selected year." - a working page, not a failure. Both on_documents_page()
    and select_period() are written so that case cannot abort a run.

WHY THE ACCOUNT LABEL IS VETTED SEPARATELY (CARD_ACTION_RE)
  U.S. Bank NAMES its cards after rewards: "Cash+ Visa Signature", "Shopper
  Cash Rewards", "Triple Cash Rewards", "Altitude Reserve", "FlexPerks Gold".
  The blocklist forbids `rewards` because "Redeem rewards" is a rewards
  action - so vetting an account label with the blocklist would refuse the
  card's own name. A label is a NOUN PHRASE; what makes a look-alike
  dangerous is a VERB. So labels are checked against CARD_ACTION_RE instead,
  and must still look like a masked card number. is_safe_row_control() applies
  the same reasoning to a row control that names its card. The Discover app
  hit this first, with "Discover it Miles".

OUT OF SCOPE: tax documents and the "Letters & notices" area, which has its
own nav entry. `document_types` in config lists Statement alone, so a stray
one is skipped rather than half-filed.
"""
# Site layer verified working against the live site: 2026-08-19 (statements:
# discovery across 2019-2026, download, and each filename checked against the
# closing date and account number printed inside the PDF).
from __future__ import annotations

import base64
import html as _html
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

log = logging.getLogger("usbank_docs.site")

BASE = "https://onlinebanking.usbank.com"
PUBLIC = "https://www.usbank.com"
URLS = {
    "home": f"{BASE}/",
    # www.usbank.com redirects here when signed out (confirmed 2026-08-19).
    "login": f"{PUBLIC}/",
    # The E-statements route, confirmed live 2026-08-19. The whole portal is
    # ONE hash-routed SPA under /digital/servicing/shellapp/, so this is a
    # fragment, not a page - which is exactly why goto_documents clicks the
    # app's own "Statements" nav FIRST and only falls back to the URL.
    "documents": f"{BASE}/digital/servicing/shellapp/#/highvolume/edocs/statements",
    "letters": f"{BASE}/digital/servicing/shellapp/#/highvolume/edocs/letters",
    "dashboard": f"{BASE}/digital/servicing/shellapp/#/customer-dashboard",
}
DOCUMENT_URL_CANDIDATES = [URLS["documents"], URLS["dashboard"]]

# Kept narrow on purpose: "/auth/" alone appears in the SIGNED-IN URLs above,
# so matching it would report every working page as signed out.
LOGIN_URL_MARKERS = ["/auth/login", "/logon", "/login.html", "/signin",
                     "/sign-in", "/idp", "/mfa", "/verify-identity",
                     "/authentication", "usbank.com/index.html"]

# ---------------------------------------------------------------------------
# HARD SAFETY GUARD - never click anything matching this. Tuned for a U.S. Bank
# credit card.
# ---------------------------------------------------------------------------
FORBIDDEN_CONTROL_RE = re.compile(
    # money movement
    r"(transfer|deposit|withdraw|wire\b|move\s+money|send\s+money|zelle|"
    r"pay\b|payment|pay\s+bills?|bill\s*pay|autopay|auto-?pay|schedule\s+payment|"
    r"pay\s+card|make\s+a\s+payment|stop\s+payment|"
    # card-specific products and borrowing
    r"balance\s+transfer|cash\s+advance|convenience\s+check|"
    r"credit\s+line|credit\s+limit|extend\s*pay|simple\s+loan|"
    r"overdraft|"
    # rewards. A card NAMED "Shopper Cash Rewards" is a noun phrase and is
    # vetted by CARD_ACTION_RE instead - see is_card_control().
    r"redeem|rewards?\b|points\b|miles\b|flexpoints?|real.?time\s+rewards|"
    r"cash\s*back\s+redeem|offers?\b|deals?\b|"
    r"book\s+travel|travel\s+cent(er|re)|shop\s+and\s+earn|"
    # applications and account changes
    r"apply|open\s+(a|an|another|new)\b[\w\s]{0,24}\baccount\b|"
    r"open\s+\w{0,12}\s*account\b|get\s+(a\s+)?(quote|started|loan|card)|"
    r"add\s+(funds|card|authorized)|authorized\s+user|"
    r"dispute|report\s+(a\s+)?(problem|fraud|lost|stolen)|"
    r"lock\s+card|unlock\s+card|freeze|activate|replace\s+card|close\s+account|"
    r"travel\s+notification|request\b|increase\b|"
    # settings
    r"change\s+|edit\s+|update\s+|set\s+up|enroll|enable|disable|delete|remove|"
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
    "for your security, we signed you out", "for your security we've signed",
]

# Throttling, as REGEXES with a subject. These were bare substrings, and
# "temporarily unavailable" halted a live run on a perfectly healthy
# dashboard: U.S. Bank routinely posts scheduled-maintenance notices, and
# this one read "some features may be temporarily unavailable" about
# transfers and bill pay. A notice about OTHER features being down is not
# this app being rate limited, so each pattern now has to say that the site,
# service or page itself is the thing that is unavailable.
RATE_LIMIT_MARKERS = [
    re.compile(r"too many requests", re.I),
    re.compile(r"rate limit(ed|ing)?\b", re.I),
    re.compile(r"unusual traffic", re.I),
    re.compile(r"\b(http\s*)?(error\s*)?429\b", re.I),
    re.compile(r"(site|service|page|system|application)\s+(is\s+)?"
               r"(currently\s+|temporarily\s+)*unavailable", re.I),
    re.compile(r"we'?re\s+(currently\s+)?(experiencing|having)\s+"
               r"(technical\s+)?(difficulties|issues)", re.I),
]

# ---------------------------------------------------------------------------
# Selectors. Repair these from Diagnostics/ after a --diagnose run - which for
# this app means "fill them in for the first time".
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

# A row control that opens/downloads one statement. Broad on purpose: Chase's
# turned out to be a plain <button> with no aria-label and no href, whose text
# was just the statement's name, so keying on the word "Download" found
# nothing there. The specific selectors are tried first;
# ROW_CONTROL_FALLBACK_SEL then considers any button/link in the row. Either
# way the element's own accessible name must clear is_safe_control(), so
# widening the net does not widen what may be clicked.
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
    for rx in RATE_LIMIT_MARKERS:
        m = rx.search(hay)
        if m:
            return f"Possible rate limiting detected: '{m.group(0)}'"
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
    """Bank portals show an inactivity modal with a keep-alive button.
    Clicking it only extends the session - it moves no money and changes no
    setting. Anything else in that modal (including 'Log out') is left alone.
    """
    for pattern in (r"i'?m still here", r"stay (signed|logged) in",
                    r"continue session", r"keep me (signed|logged) in",
                    r"extend (my )?session", r"still (there|here)\?"):
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

DOCUMENTS_NAV_RE = re.compile(
    r"^\s*(documents?|statements?\s*(&|and)\s*documents?|"
    r"statements?|e-?statements?|tax\s+forms?)\s*$", re.I)


def on_documents_page(page) -> bool:
    """Are we looking at the documents area?

    Keyed on the page's own container, NOT on "did we read any rows". A year
    with no statements in it renders a perfectly good documents page with an
    empty list; treating that as "not the page" made ensure_statements
    navigate away mid-run and lost the rest of the year.
    """
    try:
        if page.locator(SEL["doc_view"]).count() > 0:
            return True
        if page.locator(SEL["list"]).count() > 0:
            return True
    except Exception:
        pass
    try:
        return len(collect_documents(page)) > 0
    except Exception:
        return False


def click_documents_nav(page) -> bool:
    """Reach the documents area the way the app expects: its own navigation.

    Tried BEFORE any URL because on Chase a pasted route was observed to leave
    you on the dashboard silently. The label must clear the read-only guard
    first.
    """
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
                # the nav may open a submenu (Statements / Tax forms)
                for sub in ("statements", "e-statements", "tax forms"):
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

    Order matters. The app's own nav is tried FIRST because on Chase a pasted
    hash route silently left us on the dashboard - where the account dropdown
    belongs to a transfer widget, not to a statements list. Only then are the
    candidate URLs tried, and failing everything we keep whatever page is open
    so you can navigate there by hand and the tool still reads it.
    """
    dismiss_timeout(page)
    if on_documents_page(page):
        return True
    if click_documents_nav(page):
        log.info("documents area reached at %s", page.url)
        return True
    for url in DOCUMENT_URL_CANDIDATES:
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3500)
            dismiss_timeout(page)
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

    Try the CURRENT page first and only navigate when nothing statement-like
    is rendered: if the session is held in memory (as Amex's is) a hard goto
    can bounce you out.
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
# Row scraping (the generic fallback)
#
# Any row carrying a date AND a control that looks like "view / download /
# PDF" is a statement row. Once --diagnose shows the real markup, tighten
# _ROW_JS to U.S. Bank's actual testids/classes so unrelated rows can never be
# picked up.
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
    fallback inside usbank_collect)."""
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
        # De-duplicating on (title, date) alone silently threw away real rows
        # on Chase, where several statements on one date are described
        # identically - 24 rows collapsed to 16. Position is part of the
        # identity here.
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
# SAFETY: a dropdown is a control too. On Ally, the dashboard carried a
# money-TRANSFER widget whose first <select> was an account list (allytmfn
# "fromAccount") - indistinguishable from a statements account picker by its
# options alone, and the first live probe tried to set it. A card dashboard
# has the same hazard in its "pay from" picker. Selecting an option in a
# transfer form is not read-only behaviour even when nothing is submitted, so
# every <select> is identity-checked before it is read OR written.
# ---------------------------------------------------------------------------
_ACCOUNT_HINT_RE = re.compile(
    r"(visa|mastercard|american\s+express|amex|card\b|credit|"
    r"checking|savings|money\s*market|\bcd\b|certificate|"
    r"account|x{2,}\d|\*{2,}\d|\.{3}\d{3,}|\d{4}\s*$)", re.I)

# A control belonging to a money-movement widget. Matched against the
# element's own identity (id/name/aria-label/placeholder/data-testid) AND its
# enclosing form/section, so a picker inside a payment card is refused even
# when its own attributes look innocent.
MONEY_CONTROL_RE = re.compile(
    r"(from|to|source|destination|target)\s*_?-?account|"
    r"transfer|payment|pay\b|bill|deposit|withdraw|zelle|wire|remit|"
    r"send\s*money|move\s*money|recipient|payee|amount|frequency|schedule|"
    r"extend\s*pay|redeem|rewards?\b", re.I)

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
        if is_money_control(identity):
            log.info("refusing dropdown (money control): %s", identity[:120])
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
        out.append({"identity": identity[:200],
                    "refused_as_money_control": is_money_control(identity),
                    "option_count": len(opts),
                    # option labels can carry balances - keep only their shape
                    "option_sample": [re.sub(r"\$[\d,.]+", "$…", o)[:60] for o in opts[:6]]})
    return out


def account_select(page):
    """Return (locator, [labels]) for a <select> that lists accounts, or
    (None, []). Money-movement pickers are refused outright."""
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
    that writes to a <select>, so it must be safe on its own terms no matter
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


def usbank_collect(page) -> List[dict]:
    """The GENERIC fallback: every statement reachable by walking whatever
    <select>s the page offers, reading the rows it renders.

    usbank_collect_structured is tried first; this runs only when that
    answered nothing - a page shape neither it nor this app has seen.
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


# ===========================================================================
# Accounts, periods and rows - CONFIRMED LIVE 2026-08-19
#
# The E-statements page is a data-testid component tree, not a table:
#
#   [data-testid="document-view"]
#     [data-testid="account-date-selector"]
#       [data-testid="account-dropdown"]   "Account / Credit Card ...4321"
#       [data-testid="year-filter"]        button#exp_button_year-filter-select
#     [data-testid="list-of-statements"]
#       div.document-list                  <- ONE PER SECTION
#         h3 "Credit Card ...4321 statements"
#         ul > li.download-items           <- the row
#             a       aria "View <date> statement in a new window."
#             button  aria "Download <date> statement."
#       div.document-list
#         h3 "E-statement disclosures"     <- NOT statements; must be skipped
#         ul > li.download-items           "Electronic document agreement"
#
# There is no <table>, no [role=row] and no <select> anywhere on this page,
# which is why the generic scraper found nothing here.
# ===========================================================================

SEL = {
    "doc_view": "[data-testid='document-view']",
    "account": "[data-testid='account-dropdown']",
    "year_filter": "[data-testid='year-filter']",
    "year_button": "#exp_button_year-filter-select",
    "year_selection": "#year-filter-select .dropdown__btn-selection",
    "list": "[data-testid='list-of-statements']",
    "section": ".document-list",
    "row": "li.download-items",
}

# The section whose documents are statements. The page also renders an
# "E-statement disclosures" section with the same row markup, holding the
# Electronic document agreement - paperwork, not a statement.
STATEMENT_SECTION_RE = re.compile(r"statements\s*$", re.I)

# "Download March 15, 2026 statement." / "View March 15, 2026 statement in a
# new window." - the row's two controls, each naming its own date. The
# disclosure row's controls carry NO aria-label and no date, so they cannot
# match either pattern.
ROW_DOWNLOAD_ARIA_RE = re.compile(r"^\s*Download\s+(.+?)\s+statement\b", re.I)
ROW_VIEW_ARIA_RE = re.compile(r"^\s*View\s+(.+?)\s+statement\b", re.I)

# A masked card number, in the shapes providers actually print. U.S. Bank
# prints "Credit Card ...4321"; the others are kept for Chase's "(...1234)"
# and for layouts this app has not seen.
CARD_RE = re.compile(
    r"\(\s*\.{2,}\s*\d{4}\s*\)"        # (...1234)
    r"|\.{3,}\s*\d{4}"                   # ...1234   <- U.S. Bank
    r"|[*x\u00b7\u2022]{2,}\s*\d{4}"     # ****1234 / xxxx1234
    r"|ending\s+(?:in\s+)?\d{4}",         # ending in 1234
    re.I)

# The VERBS that make a card-shaped label dangerous. A header is a NOUN
# PHRASE; "Credit Card ...4321" is an account, "Pay Credit Card ...4321" is a
# payment. The blocklist cannot be used here: U.S. Bank names cards "Shopper
# Cash Rewards" and "Altitude Reserve", and the blocklist forbids `rewards`.
CARD_ACTION_RE = re.compile(
    r"\b(pay|paid|paying|redeem\w*|transfer\w*|activat\w*|lock|unlock|"
    r"freeze|unfreeze|replac\w*|clos\w*|open|apply|applying|add|remov\w*|"
    r"delet\w*|chang\w*|edit|updat\w*|manag\w*|enroll\w*|dispute\w*|"
    r"report\w*|request\w*|increas\w*|book|shop|send|deposit|withdraw|"
    r"convert|link|set\s*up|schedul\w*|order)\b", re.I)


def is_card_control(label: str) -> bool:
    """An account label may be read, though it is not a document control.

    A deliberate, narrow exception to SAFE_DOC_CONTROL_RE: the label reads
    "Credit Card ...4321", which names no document action, so the document
    allowlist would refuse it and the app could never name the account its
    statements belong to. It must still LOOK like a card (CARD_RE) and carry
    no action verb (CARD_ACTION_RE), so "Pay Credit Card ...4321" stays
    refused.
    """
    label = " ".join((label or "").split())
    if not label or not CARD_RE.search(label):
        return False
    return not CARD_ACTION_RE.search(label)


def account_name(page) -> str:
    """The account these statements belong to, as the page names it.

    Read from the account selector, which on a single-account login is static
    text ("Account / Credit Card ...4321") rather than a dropdown.
    """
    try:
        el = page.locator(SEL["account"]).first
        if el.count() == 0:
            return ""
        text = " ".join((el.inner_text(timeout=3000) or "").split())
    except Exception:
        return ""
    # strip the field's own label
    text = re.sub(r"^\s*Account\s*", "", text, flags=re.I).strip()
    if not text:
        return ""
    if not is_card_control(text):
        log.info("account label %r did not clear the card guard", text[:60])
        return ""
    return text


def account_options(page) -> List[str]:
    """Every account the selector offers, newest layout first.

    ONLY THE SINGLE-ACCOUNT CASE HAS BEEN SEEN (2026-08-19): the selector was
    static text with no button. If a multi-account login turns it into a real
    dropdown, this opens it and reads the options; otherwise it reports the
    one account. It never guesses at a list it cannot see.
    """
    try:
        holder = page.locator(SEL["account"]).first
        if holder.count() == 0:
            return []
        btn = holder.locator("button[aria-expanded], [role='combobox']")
        if btn.count() == 0:
            one = account_name(page)
            return [one] if one else []
    except Exception:
        return []
    try:
        identity = control_identity(btn.first)
        if is_money_control(identity):
            log.info("refusing account picker (money control): %s", identity[:120])
            return []
        btn.first.click()
        page.wait_for_timeout(1200)
        labels = [" ".join(t.split())
                  for t in page.get_by_role("option").all_inner_texts()]
        page.keyboard.press("Escape")
        page.wait_for_timeout(400)
        out = [x for x in labels if is_card_control(x)]
        for x in labels:
            if x and x not in out:
                log.info("refusing account option %r", x[:60])
        return out
    except Exception as e:
        log.info("account options failed: %s", e)
        one = account_name(page)
        return [one] if one else []


def select_account(page, label: str) -> bool:
    """Show one account's documents. True when there is nothing to set -
    a single-account login is a working page, not a failure."""
    if not label or label == account_name(page):
        return True
    try:
        holder = page.locator(SEL["account"]).first
        btn = holder.locator("button[aria-expanded], [role='combobox']")
        if btn.count() == 0:
            return True
        if is_money_control(control_identity(btn.first)):
            log.warning("REFUSED to set the account picker (money control)")
            return False
        if not is_card_control(label):
            log.warning("REFUSED account option %r - not a card label", label[:60])
            return False
        btn.first.click()
        page.wait_for_timeout(1000)
        opt = page.get_by_role("option", name=re.compile(re.escape(label)))
        if opt.count() == 0:
            page.keyboard.press("Escape")
            log.info("account %r not offered", label[:40])
            return False
        opt.first.click()
        page.wait_for_timeout(3000)
        dismiss_timeout(page)
        return True
    except Exception as e:
        log.info("could not select account %r: %s", label[:40], e)
        return False


def _year_button(page):
    """The Document year filter's button, or None. It is a styled dropdown -
    not a <select>, and it carries no combobox role."""
    try:
        btn = page.locator(SEL["year_button"])
        if btn.count() == 0:
            return None
    except Exception:
        return None
    try:
        name = " ".join((btn.first.inner_text(timeout=1500) or "").split())
    except Exception:
        name = ""
    # "Document year 2026" - a view filter, and it must say so.
    if not is_safe_control(name):
        log.info("year filter %r did not clear the guard", name[:60])
        return None
    if is_money_control(control_identity(btn.first)):
        log.info("refusing year filter (money control)")
        return None
    return btn.first


def reset_to_newest_period(page) -> str:
    """Put the year filter back on the newest period, and say which.

    The filter is browser state: it survives a run, so a later one can open
    on a year that simply has no statements in it. Anything that REPORTS what
    the page holds (--diagnose, the probes) must reset first, or it reports
    "0 rows" for a working reader on an empty year.
    """
    newest = (period_options(page) or [""])[0]
    if newest and select_period(page, newest):
        return newest
    return current_period(page)


def current_period(page) -> str:
    try:
        el = page.locator(SEL["year_selection"]).first
        if el.count() == 0:
            return ""
        return " ".join((el.inner_text(timeout=1500) or "").split())
    except Exception:
        return ""


def period_options(page) -> List[str]:
    """The document years the page offers, newest first.

    Confirmed live: 2019-2026, as button[role=option] inside the year filter.
    Falls back to a <select> for a layout this app has not seen; [] means
    "no picker", not "no history".
    """
    btn = _year_button(page)
    if btn is None:
        sel, years = year_select(page)
        return sorted(set(years), reverse=True) if years else []
    try:
        btn.click()
        page.wait_for_timeout(1200)
        years = sorted({t.strip() for t in page.get_by_role("option").all_inner_texts()
                        if re.fullmatch(r"20\d{2}", t.strip())}, reverse=True)
        page.keyboard.press("Escape")
        page.wait_for_timeout(400)
        return years
    except Exception as e:
        log.info("period options failed: %s", e)
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        return []


def select_period(page, year: str) -> bool:
    """Show `year` in the Document year filter.

    Returns True when there is nothing to set: a statement list with no
    period picker is a working page, not a failure, and returning False
    would fail every download before it was attempted.
    """
    year = str(year)
    btn = _year_button(page)
    if btn is None:
        sel, years = year_select(page)
        if sel is not None and years:
            return year in years and _select_option(page, sel, year)
        return True
    if current_period(page) == year:
        return True
    try:
        btn.click()
        page.wait_for_timeout(1000)
        # Anchor the START of the option name only. On Chase the last option
        # read "2019, you've reached the end of the list" and matching the
        # whole name reported the oldest year as "not offered", losing 36
        # statements with no error.
        opt = page.get_by_role("option", name=re.compile(rf"^\s*{year}\b"))
        if opt.count() == 0:
            page.keyboard.press("Escape")
            log.info("year %s not offered by the picker", year)
            return False
        opt.first.click()
        page.wait_for_timeout(3500)
        dismiss_timeout(page)
        if current_period(page) != year:
            log.info("year picker still shows %r after selecting %s",
                     current_period(page), year)
        return True
    except Exception as e:
        log.info("could not select year %s: %s", year, e)
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        return False


# ---------------------------------------------------------------------------
# Reading rows
#
# A statement row names itself on its own controls, so a document is filed
# under the account and date PRINTED ON IT. Only the section headed
# "<account> statements" is read; the "E-statement disclosures" section uses
# identical row markup and holds the Electronic document agreement.
# ---------------------------------------------------------------------------

_CARD_MASK_RE = re.compile(
    r"(\(\s*\.{2,}\s*\d{4}\s*\)|\.{3,}\s*\d{4}"
    r"|[*x\u00b7\u2022]{2,}\s*\d{4}|ending\s+(?:in\s+)?\d{4})", re.I)

# A word that cannot be part of a card's name, so walking backwards stops
# here. The one-regex version reached back greedily and captured "Statement
# Cash+ Visa Signature (...1234)" - the document type became part of the name.
_NOT_CARD_WORD_RE = re.compile(
    r"^(statements?|documents?|e-?statements?|pdf|file|link|download|view|open|"
    r"save|saves|print|opens|tax|form|summary|billing|monthly|annual|year|"
    r"year-end|account|for|the|of|and|on|dated|20\d{2}|\d{1,2}|"
    r"jan\w*|feb\w*|mar\w*|apr\w*|may|jun\w*|jul\w*|aug\w*|sep\w*|oct\w*|"
    r"nov\w*|dec\w*)[,:;.]?$", re.I)

_ROW_NOISE_RE = re.compile(
    r"\b(saves?\s+document|opens?\s+document|download(s|ing)?|view(s|ing)?|"
    r"open(s|ing)?|save(s|ing)?|print(s|ing)?|pdf|link|in\s+a\s+new\s+"
    r"(tab|window)|file)\b", re.I)

_MONTHS_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def card_in_row(name: str) -> str:
    """The card a label names, or "" if it names none.

    Found by locating the masked number and walking BACKWARDS over the words
    before it, stopping at anything that cannot be part of a card's name.
    """
    text = " ".join((name or "").split())
    m = _CARD_MASK_RE.search(text)
    if not m:
        return ""
    mask = " ".join(m.group(1).split())
    kept: List[str] = []
    for word in reversed(text[:m.start()].split()):
        if _NOT_CARD_WORD_RE.match(word) or len(kept) >= 8:
            break
        kept.insert(0, word)
    return " ".join(kept + [mask])


def doc_title_in_row(name: str, card: str = "") -> str:
    """What a label calls its document, with the date, the card and the
    control's own verbs taken out. Falls back to "Statement"."""
    text = " ".join((name or "").split())
    for pattern, _kind in DATE_PATTERNS:
        text = pattern.sub(" ", text)
    text = MONTH_YEAR_RE.sub(" ", text)
    if card:
        text = text.replace(card, " ")
    text = _CARD_MASK_RE.sub(" ", text)
    text = _ROW_NOISE_RE.sub(" ", text)
    text = re.sub(r"[\-\u2013\u2014,:;|.]+", " ", text)
    text = " ".join(text.split()).strip()
    return text[:120] or "Statement"


def is_safe_row_control(name: str) -> bool:
    """The guard, applied to a control that may NAME ITS CARD.

    U.S. Bank's cards are named after rewards, so running the blocklist over
    a whole row label would refuse the row on the word "Rewards" and the
    statement would be lost SILENTLY, with the run reporting a plausible
    smaller total. It is the account-label problem one level down, and it
    costs data rather than access.

    So the card name is removed first, and only if it is a genuine
    noun-phrase label (is_card_control). What REMAINS must still look like a
    document action and clear the blocklist - so "Redeem rewards for Cash+
    (...1234)" is refused on "Redeem", and "Pay Shopper Cash Rewards
    (...5678)" is refused because a label carrying a verb is not a card name.
    """
    text = " ".join((name or "").split())
    if not text:
        return False
    card = card_in_row(text)
    if card:
        if not is_card_control(card):
            return False
        text = text.replace(card, " ")
    return is_safe_control(text)


def _row_controls(page, limit: int = 400):
    """(locator, accessible name) for every control that could open a
    document. The GENERIC fallback, used when the real containers are gone."""
    for role in ("link", "button"):
        try:
            loc = page.get_by_role(role, name=SAFE_DOC_CONTROL_RE)
            n = min(loc.count(), limit)
        except Exception:
            continue
        for i in range(n):
            c = loc.nth(i)
            try:
                name = " ".join((c.get_attribute("aria-label") or "").split())
            except Exception:
                name = ""
            if not name:
                try:
                    name = " ".join((c.inner_text(timeout=800) or "").split())
                except Exception:
                    continue
            if name:
                yield c, name


def _rows_generic(page, account: str) -> List[dict]:
    """Rows read from accessible names alone, for a page whose containers
    this app no longer recognises."""
    out: List[dict] = []
    for _c, name in _row_controls(page):
        if not is_safe_row_control(name):
            continue
        date, _period = parse_period_date(name)
        if not date:
            continue
        card = card_in_row(name) or account
        out.append({"documentId": "", "date": date,
                    "title": doc_title_in_row(name, card),
                    "account": card, "kind": "statement",
                    "occurrence": 0, "ambiguous": False})
    return out


def read_rows(page, account: str = "") -> List[dict]:
    """The statements the page is currently showing.

    Read from each row's own Download control, which names its date. The View
    link names the SAME date, so reading both would count every statement
    twice - the Download button alone is authoritative.
    """
    account = account or account_name(page)
    try:
        have_list = page.locator(f"{SEL['list']} {SEL['section']}").count() > 0
    except Exception:
        have_list = False
    if not have_list:
        log.info("statement list container not found - reading names instead")
        return _rows_generic(page, account)

    out: List[dict] = []
    for row, heading in _statement_rows(page):
        _button, aria = _row_download_button(row)
        if not aria:
            continue            # a disclosure row: no aria-label, no date
        if not is_safe_row_control(aria):
            log.info("row control %r did not clear the guard", aria[:70])
            continue
        m = ROW_DOWNLOAD_ARIA_RE.match(aria)
        date, _period = parse_period_date(m.group(1))
        if not date:
            log.info("no date in row control %r", aria[:70])
            continue
        out.append({"documentId": "", "date": date, "title": "Statement",
                    # the section it is printed in, not the selector's state
                    "account": account_in_heading(heading) or account,
                    "kind": "statement", "occurrence": 0, "ambiguous": False})
    return out


def read_card_rows(page, label: str) -> List[dict]:
    """The statements shown for one account, selecting it first."""
    if not select_account(page, label):
        return []
    return read_rows(page, label)


def card_groups(page) -> List[Tuple[object, str]]:
    """Kept for --diagnose, which reports how documents are grouped.

    U.S. Bank groups by an account SELECTOR, not by per-card accordions, so
    this reports the accounts the selector offers with no element to click.
    """
    return [(None, label) for label in account_options(page)]


def usbank_collect_structured(page) -> List[dict]:
    """Every statement U.S. Bank still shows: each account, each year offered.

    Driven through the page's own account selector and Document year filter;
    this app issues no request of its own.
    """
    if not ensure_statements(page):
        log.info("documents page not reachable")
        return []

    accounts = account_options(page) or [account_name(page)]
    periods = period_options(page) or [""]
    log.info("U.S. Bank: %d account(s) x %d year(s)", len(accounts), len(periods))

    found: List[dict] = []
    for acct in accounts:
        if len(accounts) > 1 and not select_account(page, acct):
            continue
        for period in periods:
            if period and not select_period(page, period):
                continue
            rows = read_rows(page, acct)
            log.info("  %s %s: %d statement(s)",
                     (acct or "(account)")[:34], period or "(current)", len(rows))
            found.extend(rows)

    out, seen = [], set()
    for rec in found:
        key = (rec["account"], rec["date"], rec["title"])
        if key in seen:
            continue
        seen.add(key)
        out.append(rec)
    out.sort(key=lambda r: (r["date"], r["account"]), reverse=True)
    return out


# ---------------------------------------------------------------------------
# Download
#
# The row's Download button fires a real browser download event. The View
# link opens the same PDF in a new window (its href is "#", so there is no
# direct URL to fetch); it is the fallback if the event never arrives.
# ---------------------------------------------------------------------------
_FETCH_AS_B64 = r"""async (u) => {
    const r = await fetch(u, {credentials: 'include'});
    if (!r.ok) return null;
    const buf = new Uint8Array(await r.arrayBuffer());
    let s = ''; for (let i = 0; i < buf.length; i++) s += String.fromCharCode(buf[i]);
    return btoa(s);
}"""


def _write_if_pdf(data: bytes, out_path: Path) -> bool:
    if not data or b"%PDF-" not in data[:1024]:
        return False
    out_path.write_bytes(data)
    return True


def row_label_re(date: str, account: str = "", action: str = ""):
    """Match one row's control by its accessible name.

    The DATE is required, in any of the forms a statement row prints -
    U.S. Bank writes "Download March 15, 2026 statement." The account and
    action word are OPTIONAL, since this row prints neither, but whatever is
    passed must be present.
    """
    year = date[:4]
    month = int(date[5:7])
    day = int(date[8:10])
    mon = _MONTHS_ABBR[month - 1]
    forms = [
        rf"{mon}\w*\.?\s+0?{day}(?!\d),?\s*{year}",   # March 15, 2026
        rf"0?{month}/0?{day}(?!\d)/{year}",             # 08/14/2026
        rf"{year}-{month:02d}-{day:02d}",               # 2026-03-15
    ]
    pattern = "(?:" + "|".join(forms) + ")"
    if account:
        pattern += rf".*{re.escape(account)}"
    if action:
        pattern += rf".*{re.escape(action)}"
    return re.compile(pattern, re.I | re.S)


def usbank_download(page, ctx, account: str, date: str, out_path,
                    occurrence: int = 0, document_id: str = "",
                    title: str = "") -> bool:
    """Download one statement: right account, right year, right row."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    dismiss_timeout(page)
    if not ensure_statements(page):
        log.info("documents page not available for %r %s", account, date)
        return False
    if account and not select_account(page, account):
        log.info("could not select the account %r", account[:40])
        return False
    if not select_period(page, date[:4]):
        log.info("year %s not offered - cannot reach %s %s", date[:4], account, date)
        return False
    return _click_row_and_capture(page, ctx, account, date, out_path)


def _statement_rows(page):
    """Yield (row, section heading) for each li.download-items in a STATEMENTS
    section (not the disclosures one).

    The heading is yielded because it is where the account is printed -
    "Credit Card ...4321 statements". The rows themselves name only a date, so
    the heading is the app's attribution: a statement is filed under the
    account whose section it is rendered in, never under whichever account
    happened to be selected when an async reply arrived.

    Shared by discovery and download so the two cannot disagree about which
    rows exist.
    """
    try:
        sections = page.locator(f"{SEL['list']} {SEL['section']}")
        n = sections.count()
    except Exception:
        return
    for i in range(n):
        sec = sections.nth(i)
        try:
            heading = " ".join((sec.locator("h3").first.inner_text(timeout=2000) or "").split())
        except Exception:
            heading = ""
        if not STATEMENT_SECTION_RE.search(heading):
            continue
        try:
            rows = sec.locator(SEL["row"])
            rn = min(rows.count(), 400)
        except Exception:
            continue
        for j in range(rn):
            yield rows.nth(j), heading


def account_in_heading(heading: str) -> str:
    """The account a section heading names: "Credit Card ...4321 statements"
    -> "Credit Card ...4321"."""
    text = re.sub(r"\s*statements\s*$", "", " ".join((heading or "").split()),
                  flags=re.I).strip()
    return text if is_card_control(text) else ""


def _row_download_button(row):
    """(button, aria-label) for a row's Download control, or (None, "")."""
    try:
        btns = row.locator("button")
        n = min(btns.count(), 4)
    except Exception:
        return None, ""
    for k in range(n):
        b = btns.nth(k)
        try:
            aria = " ".join((b.get_attribute("aria-label") or "").split())
        except Exception:
            continue
        if ROW_DOWNLOAD_ARIA_RE.match(aria):
            return b, aria
    return None, ""


def find_row_control(page, date: str, account: str = ""):
    """The Download button for one statement, matched on its own aria-label.

    Matching is done HERE rather than with get_by_role(name=<regex>): a
    Playwright role selector serialises the pattern into its own selector
    syntax, and row_label_re contains "/" for the MM/DD/YYYY form, which ends
    the regex literal early and raises InvalidSelectorError. Reading the
    labels and matching them in Python has no such quoting problem - and it
    reuses the same rows discovery reads, so the two cannot disagree.
    """
    # The row names ONLY its date - "Download March 15, 2026 statement." -
    # so the account is matched against the section heading instead. Passing
    # it to row_label_re looked right and matched nothing.
    rx = row_label_re(date)
    for row, heading in _statement_rows(page):
        if account and account_in_heading(heading) not in ("", account):
            continue
        button, aria = _row_download_button(row)
        if button is None or not rx.search(aria):
            continue
        if not is_safe_row_control(aria):
            log.info("row control %r did not clear the guard", aria[:70])
            continue
        return button, aria
    return None, ""


def _click_row_and_capture(page, ctx, account: str, date: str,
                           out_path: Path) -> bool:
    """Click this row's Download button and keep the PDF it produces."""
    link, label = find_row_control(page, date, account)
    if link is None:
        log.info("no Download control for %s on %s",
                 account[:40] or "(account)", date)
        return False

    before = {id(p) for p in ctx.pages}
    try:
        with page.expect_download(timeout=30000) as dl:
            link.click()
        dl.value.save_as(str(out_path))
        if out_path.exists() and out_path.read_bytes()[:5] == b"%PDF-":
            log.info("captured via download event (%s)", label[:60])
            return True
    except Exception as e:
        log.info("no download event for %s (%s); trying the View window",
                 date, str(e).splitlines()[0][:60])

    # Fallback: the View link opens the same PDF in a new window.
    new_page = None
    for _ in range(30):
        page.wait_for_timeout(500)
        dismiss_timeout(page)
        for p in ctx.pages:
            if id(p) not in before and not p.is_closed():
                new_page = p
                break
        if new_page:
            break
    if new_page is None:
        log.info("nothing opened for %s", date)
        return False

    ok = False
    try:
        new_page.wait_for_load_state("domcontentloaded", timeout=20000)
        url = new_page.url or ""
        b64 = page.evaluate(_FETCH_AS_B64, url) if url.startswith("blob:") \
            else new_page.evaluate(_FETCH_AS_B64, url)
        if b64:
            ok = _write_if_pdf(base64.b64decode(b64), out_path)
            if ok:
                log.info("captured via new window (%s)", url[:70])
    except Exception as e:
        log.info("window capture failed for %s: %s", date, e)
    try:
        new_page.close()
    except Exception:
        pass
    return ok


# ---------------------------------------------------------------------------
# Probes: what does the page actually do?
#
# Several PaperPull apps (USAA, Navy Federal's document center) turned out to
# be far more reliable read through the provider's own JSON API than scraped
# from the DOM. These record candidate endpoints during --diagnose so we can
# see whether U.S. Bank offers one. They only LISTEN; they issue no requests.
# ---------------------------------------------------------------------------

_DIGITS_RE = re.compile(r"\d{4,}")

# Endpoints whose path looks like a document list. Chase's was
# /svc/rr/documents/.../docref/list; U.S. Bank's is unknown, so this matches
# the shape rather than one vendor's route.
DOCLIST_API_RE = re.compile(
    r"/(document|statement|edocument|estatement|docref)[\w-]*"
    r"(/[\w-]+)*/(list|search|history|index|documents|statements)\b", re.I)


def _redact(value):
    """Mask long digit runs (account/document numbers) but keep the shape."""
    if isinstance(value, str):
        return _DIGITS_RE.sub(lambda m: m.group(0)[:2] + "…" + m.group(0)[-2:], value)
    return value


def _doc_records(payload) -> List[dict]:
    """Any list-of-dicts inside a JSON payload that could be a document list.
    Shape-based, because the key name is unknown."""
    out: List[dict] = []
    if isinstance(payload, list):
        out.extend(x for x in payload if isinstance(x, dict))
    elif isinstance(payload, dict):
        for value in payload.values():
            if isinstance(value, list) and any(isinstance(x, dict) for x in value):
                out.extend(x for x in value if isinstance(x, dict))
    return out


def probe_statements_api(page) -> dict:
    """Capture the RAW document records U.S. Bank sends and report their
    fields.

    Why this exists: a truncated sample of one response is not enough to
    design against. This drives the page's own card groups and captures every
    document-list reply the page makes FOR ITSELF, dumps the field names with
    a redacted sample of each, and reports the rows the page shows for the
    same cards - so a change in either can be seen before any code depends on
    it.

    Read-only: it listens to the page's own traffic and drives only the card
    groups.
    """
    raw: List[dict] = []
    rows: List[dict] = []

    def on_resp(r):
        try:
            if not DOCLIST_API_RE.search(r.url):
                return
            if "json" not in (r.headers.get("content-type", "") or "").lower():
                return
            raw.extend(_doc_records(r.json()))
        except Exception:
            pass

    page.on("response", on_resp)
    try:
        ensure_statements(page)
        page.wait_for_timeout(1500)
        # Reset to the newest period. probe_api walks the year filter and
        # leaves it wherever it stopped, so without this the probe reports
        # "0 rows" for a year that simply has no statements in it - which
        # reads as a broken reader rather than an empty year.
        newest = (period_options(page) or [""])[0]
        if newest:
            select_period(page, newest)
        accounts = account_options(page)
        if len(accounts) > 1:
            for label in accounts:
                rows.extend(read_card_rows(page, label))
        else:
            rows.extend(read_rows(page))
    except Exception as e:
        log.info("probe_statements_api: %s", e)
    finally:
        try:
            page.remove_listener("response", on_resp)
        except Exception:
            pass

    keys: dict = {}
    for rec in raw:
        for k, v in rec.items():
            info = keys.setdefault(k, {"present": 0, "empty": 0, "distinct": set()})
            info["present"] += 1
            if v in ("", None, [], {}):
                info["empty"] += 1
            elif len(info["distinct"]) < 12:
                info["distinct"].add(str(_redact(v))[:60])

    by_card: dict = {}
    for r in rows:
        by_card[r["account"] or "(no card printed)"] = \
            by_card.get(r["account"] or "(no card printed)", 0) + 1

    return {
        "api_records": len(raw),
        "fields": {k: {"present": v["present"], "empty": v["empty"],
                       "distinct_sample": sorted(v["distinct"])[:12]}
                   for k, v in sorted(keys.items())},
        "rows_shown": len(rows),
        "rows_per_card": {_redact(k): v for k, v in sorted(by_card.items())},
        "note": "UNVERIFIED app: 0 api_records may simply mean U.S. Bank uses "
                "no such endpoint, or that DOCLIST_API_RE does not match its "
                "route - check api_candidates for what it actually called. "
                "Discovery files documents by ROW either way.",
    }


def probe_api(page, seconds: int = 25) -> List[dict]:
    """Watch the page's JSON traffic while the statements area loads, and
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
                         "top_keys": keys, "sample": _redact(body[:600])})
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
        for p in (period_options(page) or [])[:3]:
            select_period(page, p)
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
