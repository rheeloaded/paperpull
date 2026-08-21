"""ALL Chase selectors, URLs, and page behavior live here.

When Chase changes its site, repair this file only.

SCOPE: Chase **credit cards** only. Deposit accounts, mortgages, auto loans
and J.P. Morgan investment accounts are out of scope for this app.

SAFETY (this is a credit-card account):
  This module is strictly READ-ONLY. It opens the statements/documents area,
  reads the list of documents, and downloads the PDFs Chase already generated.
  It must NEVER activate any control that pays a bill, sets up autopay, moves
  money, transfers a balance, takes a cash advance, redeems rewards or points,
  books travel, requests a credit-line increase, disputes a charge, locks or
  replaces a card, applies for a product, or changes any setting. The guard is
  FORBIDDEN_CONTROL_RE; every click path checks it, and a control must ALSO
  look like a document action (SAFE_DOC_CONTROL_RE) before it may be clicked.
  Dropdowns are controls too - see MONEY_CONTROL_RE - and there is deliberately
  no code here that submits a form or confirms a dialog.

A REAL BROWSER, ALWAYS: Chase runs bot protection that fingerprints the
Playwright Chromium build. `cmd_open_browser` asks for an installed Edge or
Chrome (prefer_real=True), like the Walmart and Verizon apps. This is not only
about whether a page loads: a tripped bot check on a bank can mean a step-up
verification loop or a temporary lock on a real account, so nothing here ever
touches Chase from an obviously-automated browser.

WHAT THE LIVE PROBE ESTABLISHED (2026-08-18):
  * The document centre is
      secure.chase.com/web/auth/dashboard#/dashboard/documents/myDocs/index
    reached by clicking the app's own nav; document types are URL segments
    (documentType=STATEMENTS / TAX_DOCUMENTS / YEAR_END_STATEMENTS).
  * The page is ONE ACCORDION PER CARD. Opening one makes the SPA call
      POST /svc/rr/documents/secure/idal/v2/docref/list
           accountFilter=<card>&dateFilter.idalDateFilterType=CURRENT_YEAR[_MINUS_n]
    answering {"idaldocRefs":[{documentId, documentDate (YYYYMMDD),
    documentTypeDesc, idaldocType, pageCount}]}.
  * History comes from the page's "View:" year picker (2019..2026 here). It is
    NOT a <select> but a styled <input id*="filterstyledselect">, which is why
    a select-based lookup finds nothing. Driving it is what makes Chase send
    CURRENT_YEAR_MINUS_n; this app never synthesises a filter value the UI
    would not have sent.
  * Documents are attributed from the ROW, not from the API reply. Every row
    names itself in full - "Aug 09, 2026 Statement SAPPHIRE RESERVE (...1234)
    Saves document" - so a document can only be filed under the card printed
    on it. Correlating async replies instead put one card's statements under
    another: collapsing, expanding and changing the year all hit the same
    endpoint, so "the next reply" is not the reply to this click.
  * A card that is ALREADY expanded never re-fetches, so it must be collapsed
    before being opened, or its documents are silently missed entirely.
  * Downloads fire a real browser download event from the row's "Saves
    document" link.

OUT OF SCOPE: tax documents and year-end summaries. Chase gives both their own
nav entries, and this app deliberately collects neither - `document_types` in
config lists only Statement, so a stray one is skipped rather than half-filed.
Removing them beats shipping a collector that has never worked: the tax code
inherited from the Ally app expected a <select> year picker and could not have
run against Chase's accordions.
"""
# Site layer verified working against the live site: 2026-08-18 (statements:
# discovery across 6 cards x 2019-2026, download, filenames checked against
# the account number printed inside each PDF).
from __future__ import annotations

import base64
import html as _html
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

log = logging.getLogger("chase_docs.site")

BASE = "https://secure.chase.com"
PUBLIC = "https://www.chase.com"
URLS = {
    "home": f"{BASE}/",
    "login": f"{PUBLIC}/",
    # CANDIDATES ONLY - not yet confirmed. goto_documents clicks the app's own
    # navigation first (Ally taught us a pasted hash route can silently leave
    # you on the dashboard, where the account dropdown belongs to a TRANSFER
    # widget), and falls back to these.
    "documents": f"{BASE}/web/auth/dashboard#/dashboard/documents/index",
    "documents_alt": f"{BASE}/web/auth/dashboard#/dashboard/statements/index",
    "documents_alt2": f"{BASE}/web/auth/dashboard#/dashboard/documentCenter/index",
    "statements": f"{BASE}/web/auth/dashboard#/dashboard/statements",
}
DOCUMENT_URL_CANDIDATES = [URLS["documents"], URLS["documents_alt"],
                           URLS["documents_alt2"], URLS["statements"]]

LOGIN_URL_MARKERS = ["/logon", "/login", "/signin", "/sign-in", "/auth/logon",
                     "/idp", "/mfa", "/verify", "chase.com/web/auth#/logon"]

# ---------------------------------------------------------------------------
# HARD SAFETY GUARD - never click anything matching this. Tuned for a bank.
# ---------------------------------------------------------------------------
FORBIDDEN_CONTROL_RE = re.compile(
    # money movement
    r"(transfer|deposit|withdraw|wire\b|move\s+money|send\s+money|zelle|"
    r"pay\b|payment|pay\s+bills?|bill\s*pay|autopay|auto-?pay|schedule\s+payment|"
    r"pay\s+card|make\s+a\s+payment|"
    # card-specific products and offers
    r"balance\s+transfer|cash\s+advance|credit\s+line|credit\s+limit|"
    r"redeem|rewards?\b|points\b|miles\b|cash\s*back\s+redeem|offers?\b|"
    r"book\s+travel|shop\s+through|pay\s+yourself\s+back|"
    r"my\s*chase\s*(plan|loan)|"
    # applications and account changes
    r"apply|open\s+(a|an|another|new)\b[\w\s]{0,24}\baccount\b|"
    r"open\s+\w{0,12}\s*account\b|get\s+(a\s+)?(quote|started|loan|card)|"
    r"add\s+(funds|card|authorized)|authorized\s+user|"
    r"dispute|report\s+(a\s+)?(problem|fraud|lost|stolen)|"
    r"lock\s+card|unlock\s+card|freeze|activate|replace\s+card|close\s+account|"
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

# A row control that opens/downloads one statement.
#
# Chase's is a plain <button> with NO aria-label and NO href, whose text is just
# the statement's name ("Statement", or "<name> Trust Statement"). The words
# "Download statement for:" sit in a separate visually-hidden element in the
# row, not on the button - so keying on aria-label or on the word "Download"
# finds nothing (confirmed live 2026-08-18). The specific selectors are kept
# for other layouts and tried first; ROW_CONTROL_FALLBACK_SEL then considers
# any button/link in the row. Either way the element's own accessible name
# must clear is_safe_control(), so widening the net does not widen what may
# be clicked.
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
    """Chase shows an inactivity modal with a keep-alive button. Clicking it
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

DOCUMENTS_NAV_RE = re.compile(
    r"^\s*(documents?|statements?\s*(&|and)\s*documents?|"
    r"statements?|tax\s+forms?)\s*$", re.I)


def on_documents_page(page) -> bool:
    """Are we looking at a document list? Requires rows the scraper can
    actually read - a page that merely says "Documents" does not count."""
    try:
        return len(collect_documents(page)) > 0
    except Exception:
        return False


def click_documents_nav(page) -> bool:
    """Reach the documents area the way the SPA expects: its own top-nav
    control. Chase's dashboard is a hash-routed SPA that ignores a pasted
    #/statements fragment (confirmed 2026-08-18), so clicking is the reliable
    route. The label must clear the read-only guard first."""
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

    Chase's portal is a single-page app; if the session is held in memory a
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
# --diagnose shows the real markup, tighten _ROW_JS to Chase's actual
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
    fallback inside chase_collect)."""
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
# SAFETY: a dropdown is a control too. Chase's dashboard carries a money-TRANSFER
# widget whose first <select> is an account list (id/allytmfn "fromAccount") -
# indistinguishable from a statements account picker by its options alone. The
# 2026-08-18 probe found exactly that and tried to set it. Selecting an option
# in a transfer form is not read-only behaviour even when nothing is submitted,
# so every <select> is identity-checked before it is read OR written.
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

# A control inside a sign-in or registration form. Refused outright, and NOT
# because it moves money - it does not. Selecting inside a login form is
# simply not reading, and this app only reads.
#
# This exists because of a real defect found on the Discover app. A first
# probe missed every guessed URL, landed on that provider's PUBLIC site, and
# the account-picker lookup matched the marketing page's "what do you want to
# log into" dropdown - then set a value on it. Nothing was submitted and no
# credential was touched, but the enclosing form's id was already sitting in
# the identity string the guard reads, and nothing was asking about it.
AUTH_CONTROL_RE = re.compile(
    r"log[\s_-]?(in|on)|sign[\s_-]?(in|on|up)|signin|logon|"
    r"authenticat|credential|register|enroll(ment)?\b|"
    r"username|user[\s_-]?id|password|passcode|remember\s*me", re.I)


def is_forbidden_control_context(identity: str) -> bool:
    """True when a control must not be read OR written, for any reason.

    Fails CLOSED: an identity that could not be read at all is unsafe.
    Two independent reasons, either of which disqualifies:
      * it belongs to a money-movement widget   (MONEY_CONTROL_RE)
      * it belongs to a sign-in or registration form (AUTH_CONTROL_RE)
    """
    if not identity:
        return True
    return bool(MONEY_CONTROL_RE.search(identity)
                or AUTH_CONTROL_RE.search(identity)
                or FORBIDDEN_CONTROL_RE.search(identity))


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
    """Yield (locator, identity) for the <select> elements that are safe to
    touch, meaning part of neither a money widget nor a sign-in form."""
    # Page-level gate first. If a password field is on screen we are not on an
    # application page at all, and no control here should be read or written,
    # whatever it calls itself. A wrong URL guess is expected on a first probe.
    # Treating whatever it lands on as if it were the app is what turns an
    # ordinary miss into a safety problem.
    try:
        if looks_signed_out(page):
            log.info("refusing every control: this is not a signed-in page")
            return
    except Exception:
        return
    try:
        loc = page.locator("select")
        n = min(loc.count(), limit)
    except Exception:
        return
    for i in range(n):
        s = loc.nth(i)
        identity = control_identity(s)
        if is_forbidden_control_context(identity):
            log.info("refusing dropdown: %s", identity[:120])
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


def chase_collect(page) -> List[dict]:
    """Every statement Chase still has: a list of {account, date, title}.

    Walks the account dropdown (if there is one) and, within each account,
    every year in the period dropdown - so the full history is captured, not
    just the default view.

    This is the DOM fallback. chase_collect_via_api is tried first; this runs
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
# Three mechanisms are tried in order, because which one Chase uses is the key
# unknown until the live probe: a real browser download event, a blob/PDF tab,
# and a direct PDF href fetched from the page context (which carries the
# session cookies). Whichever wins, the bytes are checked for %PDF- before the
# file is written.
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


def _row_download_control(row):
    """The row's own download control, or None.

    Tries the explicit selectors first, then any button/link in the row -
    Chase's control announces itself only through its text. In BOTH passes the
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


_MONTHS_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def row_label_re(date: str, account: str, action: str = "Saves document"):
    """Match one row's control by its accessible name.

    Chase names these fully - "Aug 09, 2026 Statement SAPPHIRE RESERVE
    (...1234) Saves document" - so a row is identified by date AND card AND
    action, with nothing left to position or inference. Two rows cannot be
    confused the way Ally's identically-labelled statements could.
    """
    month = _MONTHS_ABBR[int(date[5:7]) - 1]
    day = date[8:10]
    day_pat = f"0?{int(day)}"                      # "Aug 9" or "Aug 09"
    return re.compile(rf"{month}\s+{day_pat},\s*{date[:4]}.*"
                      rf"{re.escape(account)}.*{re.escape(action)}", re.I | re.S)


def chase_download(page, ctx, account: str, date: str, out_path,
                   occurrence: int = 0, document_id: str = "",
                   title: str = "") -> bool:
    """Download one document: right year, right card, right row.

    Chase only renders a card's rows while its accordion is open and the year
    picker is on that document's year, so both are set first - through the
    page's own controls.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    dismiss_timeout(page)
    if not ensure_statements(page):
        log.info("documents page not available for %r %s", account, date)
        return False

    if not select_year(page, date[:4]):
        log.info("year %s not offered by the picker - cannot reach %s %s",
                 date[:4], account, date)
        return False
    if account and not expand_only_card(page, account):
        log.info("could not open the card %r", account[:40])
        return False

    # Which document Chase actually serves, so the file can be checked against
    # the one that was asked for rather than trusted.
    served: List[str] = []

    def _note(r):
        try:
            u = r.url
            if document_id and document_id in u:
                served.append(document_id)
            m = re.search(r"documentId=([\w-]{8,})", u)
            if m:
                served.append(m.group(1))
        except Exception:
            pass

    page.on("response", _note)
    try:
        ok = _click_row_and_capture(page, ctx, account, date, out_path)
    finally:
        try:
            page.remove_listener("response", _note)
        except Exception:
            pass

    if not ok:
        return False
    if document_id and served and document_id not in served:
        log.warning("MISMATCH: wanted %s, Chase served %s - discarding",
                    document_id[-8:], ", ".join(s[-8:] for s in served[:3]))
        try:
            out_path.unlink(missing_ok=True)
        except Exception:
            pass
        return False
    return True


def _click_row_and_capture(page, ctx, account: str, date: str,
                           out_path: Path) -> bool:
    """Click this row's save control and keep whatever PDF it produces."""
    link = None
    for action in ("Saves document", "opens document"):
        try:
            loc = page.get_by_role("link", name=row_label_re(date, account, action))
            if loc.count():
                label = " ".join((loc.first.inner_text(timeout=1500) or "").split())
                if not is_safe_control(label or action):
                    log.info("row control %r did not clear the guard", label[:60])
                    continue
                link = loc.first
                break
        except Exception as e:
            log.info("row lookup failed (%s): %s", action, str(e).splitlines()[0][:70])
    if link is None:
        log.info("no row for %s on %s", account[:40], date)
        return False

    before = {id(p) for p in ctx.pages}
    try:
        with page.expect_download(timeout=25000) as dl:
            link.click()
        dl.value.save_as(str(out_path))
        if out_path.exists() and out_path.read_bytes()[:5] == b"%PDF-":
            log.info("captured via download event")
            return True
    except Exception as e:
        log.info("no download event for %s %s (%s); trying tab capture",
                 account[:30], date, str(e).splitlines()[0][:60])

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
        log.info("nothing opened for %s %s", account[:30], date)
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
                log.info("captured via new tab (%s)", url[:70])
    except Exception as e:
        log.info("tab capture failed for %s %s: %s", account[:30], date, e)
    try:
        new_page.close()
    except Exception:
        pass
    return ok


# ---------------------------------------------------------------------------
# Probe: what JSON does the SPA call?
#
# Several PaperPull apps (USAA, Navy Federal's document center) turned out to
# be far more reliable read through the provider's own JSON API than scraped
# from the DOM. This records candidate endpoints during --diagnose so we can
# see whether Chase offers one. It only listens; it issues no requests.
# ---------------------------------------------------------------------------

_DIGITS_RE = re.compile(r"\d{4,}")


def _redact(value):
    """Mask long digit runs (account/document numbers) but keep the shape."""
    if isinstance(value, str):
        return _DIGITS_RE.sub(lambda m: m.group(0)[:2] + "…" + m.group(0)[-2:], value)
    return value


DOCREF_API_RE = re.compile(r"/svc/rr/documents/.*/docref/list", re.I)


def probe_statements_api(page) -> dict:
    """Capture the RAW document records Chase sends and report their fields.

    Why this exists: a truncated sample of one response is not enough to
    design against. This opens each card once on the year the picker is
    already showing, captures every docref/list reply the page makes for
    itself, dumps the field names with a redacted sample of each, and reports
    the rows the page shows for the same cards - so a change in either can be
    seen before any code depends on it.

    Read-only: it listens to the page's own traffic and drives only the card
    accordions.
    """
    raw: List[dict] = []
    rows: List[dict] = []

    def on_resp(r):
        try:
            if not DOCREF_API_RE.search(r.url):
                return
            refs = (r.json() or {}).get("idaldocRefs")
            if isinstance(refs, list):
                raw.extend(x for x in refs if isinstance(x, dict))
        except Exception:
            pass

    page.on("response", on_resp)
    try:
        ensure_statements(page)
        page.wait_for_timeout(1500)
        for _el, label in card_accordions(page):
            rows.extend(read_card_rows(page, label))
            collapse_all_cards(page)
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
        by_card[r["account"]] = by_card.get(r["account"], 0) + 1

    return {
        "api_records": len(raw),
        "fields": {k: {"present": v["present"], "empty": v["empty"],
                       "distinct_sample": sorted(v["distinct"])[:12]}
                   for k, v in sorted(keys.items())},
        "rows_shown": len(rows),
        "rows_per_card": {_redact(k): v for k, v in sorted(by_card.items())},
        "note": "api_records and rows_shown should agree for the year the "
                "picker is showing; discovery files documents by ROW.",
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
# Discovery: the document centre, driven exactly as a person drives it
#
# Confirmed live 2026-08-18. The page is one accordion per card. Expanding one
# makes the SPA call
#     POST /svc/rr/documents/secure/idal/v2/docref/list
#          accountFilter=<that card's id>&dateFilter.idalDateFilterType=<X>
# The reply carries no account field, and this app does not need it: documents
# are attributed from the ROW (see read_card_rows), never from the reply.
#
# The year comes from the page's "View:" picker. Selecting a year makes the
# SPA send idalDateFilterType=CURRENT_YEAR / CURRENT_YEAR_MINUS_1 / ... We
# drive the picker and let Chase compose that value; this app never
# synthesises a filter the UI would not have sent.
# ===========================================================================
# "FREEDOM (...5678)" - a card accordion header
CARD_RE = re.compile(r"\(\s*\.{2,}\s*\d{4}\s*\)")
YEAR_PICKER_SEL = "input[id*='filterstyledselect']"


def is_card_control(label: str) -> bool:
    """A card accordion header may be expanded, though it is not a document
    control.

    This is a deliberate, narrow exception to SAFE_DOC_CONTROL_RE: the header
    reads "FREEDOM (...5678)", which names no document action, so the document
    allowlist would refuse it and the app could never see past the first card.
    It must still look like a card AND clear the forbidden list, so a control
    that merely mentions a card ("Pay card", "Activate card") stays refused.
    """
    label = (label or "").strip()
    if not label or not CARD_RE.search(label):
        return False
    return not FORBIDDEN_CONTROL_RE.search(label)


def card_accordions(page) -> List[Tuple[object, str]]:
    """(header, label) for each card accordion on the documents page."""
    out: List[Tuple[object, str]] = []
    try:
        loc = page.get_by_role("button", name=CARD_RE)
        n = min(loc.count(), 20)
    except Exception:
        return out
    for i in range(n):
        el = loc.nth(i)
        try:
            label = " ".join((el.inner_text(timeout=1000) or "").split())
        except Exception:
            continue
        if is_card_control(label):
            out.append((el, label))
        elif label:
            log.info("refusing accordion control %r", label[:60])
    return out


def collapse_all_cards(page) -> None:
    """Close every card accordion."""
    for el, name in card_accordions(page):
        try:
            if (el.get_attribute("aria-expanded") or "").lower() == "true":
                el.click()
                page.wait_for_timeout(400)
        except Exception as e:
            log.info("could not collapse %r: %s", name[:40], e)


def expand_only_card(page, label: str) -> bool:
    """Expand this card's accordion, with every other one closed.

    The card is ALWAYS collapsed first if it is already open. Chase fetches a
    card's documents when its accordion opens, so a card that happens to be
    expanded already never fetches anything - and a discovery run that only
    listens would record nothing for it. That is not an empty card, it is a
    missing one: the first live run captured five of six cards this way, and
    the sixth was simply the one the page had open.
    """
    for el, name in card_accordions(page):
        if name != label:
            continue
        try:
            if (el.get_attribute("aria-expanded") or "").lower() == "true":
                el.click()                      # close, so opening re-fetches
                page.wait_for_timeout(600)
            el.click()
            page.wait_for_timeout(2500)
            return True
        except Exception as e:
            log.info("could not expand %r: %s", name[:40], e)
            return False
    return False


def year_options(page) -> List[str]:
    """The years the "View:" picker offers. It is not a <select> but a styled
    input, so the list only exists once it is open."""
    try:
        inp = page.locator(YEAR_PICKER_SEL).first
        if inp.count() == 0:
            return []
        label = inp.get_attribute("aria-label") or "View:"
        if not is_safe_control(label):
            log.info("year picker %r did not clear the guard", label)
            return []
        inp.click()
        page.wait_for_timeout(1200)
        years = page.evaluate("""() => {
            const s = new Set();
            for (const el of document.querySelectorAll('[role="option"], li, span')) {
                const t = (el.innerText || '').trim();
                if (/^20\\d{2}$/.test(t)) s.add(t);
            }
            return [...s];
        }""")
        page.keyboard.press("Escape")
        page.wait_for_timeout(400)
        return sorted(years, reverse=True)
    except Exception as e:
        log.info("year options failed: %s", e)
        return []


def select_year(page, year: str) -> bool:
    """Pick a year in the "View:" picker, the way a person would."""
    try:
        inp = page.locator(YEAR_PICKER_SEL).first
        if (inp.get_attribute("value") or "").strip() == str(year):
            return True
        inp.click()
        page.wait_for_timeout(1000)
        # The accessible name is not just the year: the last option reads
        # "2019, you've reached the end of the list" and the current one
        # "2020, current selection". Anchor the start only, or the oldest
        # year is never selectable and is silently reported as not offered.
        opt = page.get_by_role("option", name=re.compile(rf"^\s*{year}\b"))
        if opt.count() == 0:
            page.keyboard.press("Escape")
            log.info("year %s not offered", year)
            return False
        opt.first.click()
        page.wait_for_timeout(3500)
        dismiss_timeout(page)
        return True
    except Exception as e:
        log.info("could not select year %s: %s", year, e)
        return False


# A row's accessible name, e.g.
#   "Aug 09, 2026 Statement SAPPHIRE RESERVE (...1234) Saves document"
ROW_NAME_RE = re.compile(
    r"(?P<mon>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+"
    r"(?P<day>\d{1,2}),\s*(?P<year>20\d{2})\s+"
    r"(?P<type>.*?)\s+(?P<card>[A-Z0-9][^()]*\(\s*\.{2,}\s*\d{4}\s*\))",
    re.I)


def read_card_rows(page, label: str) -> List[dict]:
    """The documents Chase is showing for one card, read from the rows.

    Attribution comes from the ROW, not from correlating an async API reply.
    Each row names itself completely - date, type and card - so a document can
    only ever be filed under the card printed on it. Correlating responses
    instead put a card's statements under its neighbour: collapsing, expanding
    and changing the year all fire the same endpoint, so "the next reply" is
    not reliably the reply to this click.
    """
    if not expand_only_card(page, label):
        return []
    out: List[dict] = []
    try:
        links = page.get_by_role("link", name=re.compile(r"Saves document", re.I))
        n = min(links.count(), 400)
    except Exception as e:
        log.info("could not read rows for %r: %s", label[:40], e)
        return []
    for i in range(n):
        try:
            name = " ".join((links.nth(i).inner_text(timeout=800) or "").split())
        except Exception:
            continue
        m = ROW_NAME_RE.search(name)
        if not m:
            continue
        card = " ".join(m.group("card").split())
        # Only rows belonging to the card we opened - other accordions may
        # still be rendered even when collapsed.
        if card != label:
            continue
        date, _ = parse_period_date(f"{m.group('mon')} {m.group('day')}, {m.group('year')}")
        if not date:
            continue
        out.append({"documentId": "", "date": date,
                    "title": (m.group("type") or "Statement").strip() or "Statement",
                    "account": card, "kind": "statement",
                    "occurrence": 0, "ambiguous": False})
    return out


def chase_collect_via_api(page) -> List[dict]:
    """Every document Chase still shows: each card, each year in the picker.

    Driven through the page's own accordions and year picker; this app issues
    no request of its own.
    """
    found: List[dict] = []
    if not ensure_statements(page):
        log.info("documents page not reachable")
        return []
    years = year_options(page) or [""]
    cards = [label for _el, label in card_accordions(page)]
    if not cards:
        log.info("no card accordions found")
        return []
    log.info("Chase: %d card(s) x %d year(s)", len(cards), len(years))

    for year in years:
        if year and not select_year(page, year):
            continue
        collapse_all_cards(page)
        for label in cards:
            rows = read_card_rows(page, label)
            log.info("  %s %s: %d document(s)", year or "(current)", label[:34], len(rows))
            found.extend(rows)
            collapse_all_cards(page)

    out, seen = [], set()
    for rec in found:
        key = (rec["account"], rec["date"], rec["title"])
        if key in seen:
            continue
        seen.add(key)
        out.append(rec)
    out.sort(key=lambda r: (r["date"], r["account"]), reverse=True)
    return out
