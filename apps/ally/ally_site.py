"""ALL Ally Bank selectors, URLs, and page behavior live here.

When Ally changes its site, repair this file only.

SAFETY (this is a BANK):
  This module is strictly READ-ONLY. It navigates to the document/statement
  areas, reads a list of documents, and downloads the PDFs Ally already
  generated. It must NEVER activate any control that moves money, pays a
  bill, sends Zelle/wire/transfer, deposits, withdraws, opens or closes an
  account, renews or rolls over a CD, or changes any setting. The guard is
  FORBIDDEN_CONTROL_RE; every click path checks it, and a control must ALSO
  look like a document action (SAFE_DOC_CONTROL_RE) before it may be clicked.
  There is deliberately no code here that submits a form or confirms a dialog.

SCOPE: Ally **Bank** only (checking / savings / money market / CDs). Ally
Invest and Ally Auto are separate portals and are not covered here.

WHAT THE LIVE PROBE ESTABLISHED (2026-08-18):
  * The documents area is https://secure.ally.com/bank/statements-and-forms,
    reached by clicking the SPA's own "Documents" nav control. The dashboard
    is hash-routed and IGNORES a pasted #/statements fragment - a goto leaves
    you on Snapshot, where the only account dropdown belongs to a money
    TRANSFER widget. Hence nav-first navigation, and the dropdown guard.
  * Statements come from
        GET /acs/v1/bank-statements?docType=STATEMENTS&year=YYYY
    answering {"statements":[{iraType, documentId, trustName, documentName,
    uploadDate}]}. That is the discovery path; row scraping is the fallback.
    Driving the year picker 2020..2026 returned 198 statements over 7 years.
  * SEVERAL statements share a date (3/month on this account), and the record
    carries NOTHING that separates them except documentId:
      - trustName is present on only some records, and it really is a TRUST
        name - the page renders those rows as "<name> Trust Statement".
      - documentName is always "Statement"; iraType is always false.
      - the remaining records are described identically in the API AND on the
        page ("Download statement for: Statement"), several per date.
    So a trust statement can be identified exactly, and the rest can only be
    told apart by POSITION within their date. Discovery numbers them
    (`occurrence`) and flags them (`ambiguous`); the downloader aims at the
    Nth such row and returns False rather than guessing. Which real account
    each belongs to is not knowable from the site - only from the PDF.
  * The page has a year picker (select#statementYear) covering 2020..2026.

DOWNLOAD: clicking the row's control opens the PDF in a new tab, whose bytes
are captured. Fetching /acs/v1/bank-statements/<documentId> directly does NOT
work - it needs the Authorization header the SPA adds in JS. That endpoint is
still useful as PROOF: the id in the request says which statement was really
served, so a download is verified rather than trusted (see ally_download).

TAX FORMS (confirmed live 2026-08-18): a "Tax Forms" tab at
/bank/statements-and-forms/tax, served by the SAME endpoint with
    GET /acs/v1/bank-statements?docType=TAXFORMS      (no year parameter)
answering {"taxForms":[{corrected, documentId, documentName, iraType, taxYear,
trustName, uploadDate}]}. Notes that cost real debugging:
  * File by taxYear, NOT uploadDate: the 2025 form is posted 2026-01-10.
  * The row names the form "1099-INT" while the API titles it "Form 1099-INT",
    so rows are matched on the form CODE (FORM_CODE_RE).
  * One form per registration per year, ALL titled identically - matching on
    the name alone served the same PDF twice (the served-id check caught it:
    "wanted 022499, Ally served 022500"). Registration first, then position.
  * The tax year picker starts at 2020, but the API returns a 2019 form. That
    document cannot be reached from the page at all; the app says so and stops
    rather than downloading a different year.
"""
# Site layer verified working against the live site: 2026-08-18 (discovery,
# download, per-document verification, tax forms, content-based naming).
from __future__ import annotations

import base64
import html as _html
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

log = logging.getLogger("ally_docs.site")

BASE = "https://secure.ally.com"
PUBLIC = "https://www.ally.com"
URLS = {
    "home": f"{BASE}/",
    "login": f"{PUBLIC}/",
    # The real documents page, confirmed live 2026-08-18. These are only the
    # fallback: goto_documents clicks the SPA's own nav first, because a
    # hash-route goto lands on the dashboard instead (see the docstring).
    "documents": f"{BASE}/bank/statements-and-forms",
    "documents_alt": f"{BASE}/statements",
    "documents_alt2": f"{BASE}/dashboard/#/statements",
    "statements": f"{BASE}/bank/statements",
}
DOCUMENT_URL_CANDIDATES = [URLS["documents"], URLS["documents_alt"],
                           URLS["documents_alt2"], URLS["statements"]]

LOGIN_URL_MARKERS = ["/logon", "/login", "/signin", "/sign-in", "/auth",
                     "/idp", "/mfa", "/verify", "www.ally.com/login"]

# ---------------------------------------------------------------------------
# HARD SAFETY GUARD - never click anything matching this. Tuned for a bank.
# ---------------------------------------------------------------------------
FORBIDDEN_CONTROL_RE = re.compile(
    r"(transfer|deposit|withdraw|wire\b|move\s+money|send\s+money|zelle|"
    r"pay\b|payment|pay\s+bills?|bill\s*pay|autopay|auto-?pay|schedule\s+payment|"
    r"buy|sell|trade|place\s+order|rebalance|reallocate|invest\b|"
    # "Open ... account" with any words in between ("Open a new savings
    # account"), plus the bare two-word form. A document control that merely
    # names an account ("Open statement for account 1234") is left safe.
    r"apply|open\s+(a|an|another|new)\b[\w\s]{0,24}\baccount\b|open\s+\w{0,12}\s*account\b|"
    r"get\s+(a\s+)?(quote|started|loan)|add\s+funds|"
    r"remote\s+deposit|mobile\s+deposit|external\s+account|link\s+(bank|account)|"
    r"dispute|report\s+(a\s+)?(problem|fraud|lost|stolen)|lock\s+card|unlock\s+card|"
    r"activate|replace\s+card|order\s+checks|stop\s+payment|"
    # Ally-specific money/product controls
    r"renew|roll\s*over|rollover|mature|early\s+withdrawal|close\s+account|"
    r"create\s+bucket|bucket|boost|surprise\s+savings|round\s*ups?|"
    r"recurring\s+transfer|allocate|goal\b|"
    r"change\s+|edit\s+|update\s+|set\s+up|enable|disable|delete|remove|"
    r"beneficiar|payee|contact\s+info|password|username|"
    r"paperless|delivery\s+preference|"
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
# Ally's is a plain <button> with NO aria-label and NO href, whose text is just
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
    """Ally shows an inactivity modal with a keep-alive button. Clicking it
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
    control. Ally's dashboard is a hash-routed SPA that ignores a pasted
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

    Ally's portal is a single-page app; if the session is held in memory a
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
# --diagnose shows the real markup, tighten _ROW_JS to Ally's actual
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
    fallback inside ally_collect)."""
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
# SAFETY: a dropdown is a control too. Ally's dashboard carries a money-TRANSFER
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


# ---------------------------------------------------------------------------
# Discovery via Ally's own JSON API (preferred)
#
# The statements page is driven by
#     GET https://secure.ally.com/acs/v1/bank-statements
# which answers {"statements":[{documentId, trustName, documentName,
# uploadDate, iraType}, ...]}. Reading that is far more reliable than scraping
# rows, and documentId is a durable per-document identity, so the delete-safe
# state survives any redesign of the table. Confirmed live 2026-08-18.
#
# Ally issues ONE combined statement per ownership group (individual / joint /
# IRA), not one per account - so two statements can share a date and are told
# apart only by trustName + iraType.
# ---------------------------------------------------------------------------
STATEMENTS_API_RE = re.compile(r"/acs/v\d+/(bank-)?statements", re.I)


def account_label(trust_name: str, ira_type: bool = False,
                  labels: Optional[dict] = None) -> str:
    """A short, stable label for the ownership group a statement belongs to,
    used to tell same-dated statements apart in filenames.

    This deliberately does NOT infer a category from the registration name.
    An earlier version guessed "Joint" when the name contained "and" and
    "Individual" otherwise, which quietly mislabels a trust registration
    ("Sample Family Trust" has no "and" in it) - and a wrong label is worse
    than a long one, because it is not obviously wrong on the shelf.

    So the label is, in order:
      1. whatever you mapped this registration to in config.json
         ("account_labels": {"<registration name>": "Trust"}),
      2. "IRA" when Ally's own iraType flag says so and nothing is mapped,
      3. otherwise the registration name exactly as Ally reports it.
    """
    name = (trust_name or "").strip()
    if labels:
        mapped = labels.get(name)
        if mapped:
            return str(mapped).strip()
    if ira_type:
        return "IRA"
    return name


def _normalize_api_statement(s: dict, labels: Optional[dict] = None) -> Optional[dict]:
    """One API record -> the dict the orchestrator records."""
    doc_id = (s.get("documentId") or "").strip()
    raw_date = (s.get("uploadDate") or "").strip()
    date = raw_date[:10] if re.match(r"\d{4}-\d{2}-\d{2}", raw_date) else None
    if not date:
        date, _ = parse_period_date(raw_date)
    if not date:
        return None
    # trustName is present ONLY on trust-registered statements - Ally omits the
    # key entirely otherwise. The page confirms the reading: those rows render
    # as "<name> Trust Statement". So its presence is a fact, not an inference.
    trust = re.sub(r"\s+", " ", (s.get("trustName") or "")).strip()
    ira = bool(s.get("iraType"))
    return {"documentId": doc_id,
            "date": date,
            "title": (s.get("documentName") or "Statement").strip() or "Statement",
            # the registration name exactly as Ally reports it: how a row is
            # re-found on the page, and the key you map in account_labels
            "account": trust,
            "ira": ira,
            # what goes in the filename (your mapping, else the name itself)
            "label": account_label(trust, ira, labels),
            # set by ally_collect_via_api once the whole date is known
            "occurrence": 0,
            "ambiguous": False}


def ally_collect_via_api(page, labels: Optional[dict] = None) -> List[dict]:
    """Every statement Ally still has, read from its own JSON API.

    The year picker is walked so that whichever way Ally filters - server-side
    per year, or client-side over one payload - the full history is seen. All
    responses are merged and de-duplicated by documentId, so re-fetching the
    same year costs nothing.
    """
    captured: List[dict] = []

    def on_resp(r):
        try:
            if not STATEMENTS_API_RE.search(r.url):
                return
            if "json" not in (r.headers.get("content-type", "") or "").lower():
                return
            data = json.loads(r.text())
            items = data.get("statements") if isinstance(data, dict) else None
            if isinstance(items, list):
                captured.extend(items)
                log.info("captured %d statements from %s", len(items), r.url)
        except Exception as e:
            log.info("could not read statements response: %s", e)

    page.on("response", on_resp)
    try:
        if not ensure_statements(page):
            log.info("statements page not reachable for the API read")
        page.wait_for_timeout(2500)

        sel, years = year_select(page)
        if sel is not None and years:
            # Start from the far end so the first pick always changes the
            # value (selecting the year already shown fires no request).
            ordered = sorted(years, reverse=False)          # oldest .. newest
            for y in ordered:
                if _select_option(page, sel, y):
                    page.wait_for_timeout(1200)
        else:
            log.info("no year picker found; reading the default view only")
    finally:
        try:
            page.remove_listener("response", on_resp)
        except Exception:
            pass

    out, seen = [], set()
    for s in captured:
        rec = _normalize_api_statement(s, labels)
        if not rec:
            continue
        key = rec["documentId"] or f"{rec['date']}|{rec['account']}|{rec['title']}"
        if key in seen:
            continue
        seen.add(key)
        out.append(rec)

    # Ally posts several statements per date and describes the non-trust ones
    # identically - same documentName, no registration, same row label. They
    # differ ONLY by documentId. So each one is numbered within its date (in
    # the API's own order) to give the downloader something to aim at, and
    # flagged so the filename can carry a disambiguator instead of two files
    # silently claiming to be the same statement.
    by_date: dict = {}
    for rec in out:
        if not rec["account"]:                       # non-trust: ambiguous set
            by_date.setdefault(rec["date"], []).append(rec)
    for date, sibs in by_date.items():
        for i, rec in enumerate(sibs):
            rec["occurrence"] = i
            rec["ambiguous"] = len(sibs) > 1
        if len(sibs) > 1:
            log.info("%s: %d statements Ally does not distinguish", date, len(sibs))

    out.sort(key=lambda r: (r["date"], r.get("occurrence", 0)), reverse=True)
    return out


def ally_collect(page) -> List[dict]:
    """Every statement Ally still has: a list of {account, date, title}.

    Walks the account dropdown (if there is one) and, within each account,
    every year in the period dropdown - so the full history is captured, not
    just the default view.

    This is the DOM fallback. ally_collect_via_api is tried first; this runs
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
# Three mechanisms are tried in order, because which one Ally uses is the key
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


def _date_needles(date: str) -> List[str]:
    """The ways this ISO date can appear in a row."""
    y, m, d = date[:4], date[5:7], date[8:10]
    month = ["January", "February", "March", "April", "May", "June", "July",
             "August", "September", "October", "November", "December"][int(m) - 1]
    return [f"{int(m)}/{int(d)}/{y}", f"{m}/{d}/{y}",
            f"{month} {int(d)}, {y}", f"{month[:3]} {int(d)}, {y}", date]


def _row_download_control(row):
    """The row's own download control, or None.

    Tries the explicit selectors first, then any button/link in the row -
    Ally's control announces itself only through its text. In BOTH passes the
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


def _rows_for_date(page, date: str):
    """Every statement row shown for this date, in page order, as
    (row, text) pairs."""
    for needle in _date_needles(date):
        try:
            rows = page.locator("tr, [role='row'], li").filter(has_text=needle)
            n = min(rows.count(), 40)
        except Exception:
            continue
        found = []
        for i in range(n):
            row = rows.nth(i)
            try:
                text = re.sub(r"\s+", " ", row.inner_text(timeout=800) or "")
            except Exception:
                continue
            if _row_download_control(row) is not None:
                found.append((row, text))
        if found:
            return found
    return []


def _find_row_control(page, date: str, account: str = "", occurrence: int = 0):
    """Re-find the download control for ONE statement.

    Matched by visible content, never by a global index - indexes shift
    whenever the year changes.

    Two cases, because Ally describes its statements two different ways:

    * A TRUST statement carries the registration in its row label
      ("Download statement for: <name> Trust Statement"), so `account` picks
      it out exactly.
    * Everything else is labelled identically ("Download statement for:
      Statement"), several per date, differing only by documentId. Nothing on
      the page distinguishes them, so the only handle available is position:
      the Nth such row for that date. `occurrence` selects it, and the trust
      rows are excluded first so the count lines up with the API's order.

    Returns None rather than guessing when the row it wants is not there -
    downloading the wrong statement under a confident filename is far worse
    than downloading nothing.
    """
    rows = _rows_for_date(page, date)
    if not rows:
        return None

    if account:
        needle = account[:24].strip().lower()
        for row, text in rows:
            if needle and needle in text.lower():
                return _row_download_control(row)
        log.info("no row for registration %r on %s", account[:40], date)
        return None

    # Ambiguous set: drop the registration-labelled rows, then take the Nth.
    plain = [(row, text) for row, text in rows
             if not re.search(r"\btrust\b", text, re.I)]
    if occurrence < len(plain):
        return _row_download_control(plain[occurrence][0])
    log.info("wanted statement #%d of %d on %s - not present",
             occurrence + 1, len(plain), date)
    return None


# Clicking a row makes the SPA call GET /acs/v1/bank-statements/<documentId>,
# and that response is the PDF. Fetching it ourselves does NOT work: the
# endpoint needs the Authorization header the SPA attaches in JS, and a
# cookie-only fetch comes back non-2xx (tried live 2026-08-18 - every id
# returned no body). So the row still has to be clicked.
#
# What the endpoint DOES give us is proof. The id in that request says which
# statement the site actually served, so a download can be checked against the
# statement we meant to fetch instead of trusting that row N is record N.
STATEMENT_BY_ID_RE = re.compile(r"/acs/v\d+/bank-statements/(\w+)", re.I)
# Any /acs/ endpoint that serves ONE document by id - statements today,
# tax forms on whatever path Ally uses for them.
SERVED_DOC_ID_RE = re.compile(r"/acs/v\d+/[a-z-]+/(\w{6,})", re.I)


def ally_download(page, ctx, account: str, date: str, out_path,
                  occurrence: int = 0, document_id: str = "",
                  kind: str = "statement", title: str = "") -> bool:
    """Download the statement dated `date` for `account` into out_path.

    Returns True only when a real PDF was written.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    dismiss_timeout(page)
    if not ensure_statements(page):
        log.info("statements page not available for %r %s", account, date)
        return False

    # Tax forms live in their own tab and are identified by their form name
    # ("1099-INT"), not by a statement date.
    if kind == "tax":
        if not click_tax_tab(page):
            log.info("could not open the tax area for %r", title or date)
            return False

    # Put the list in the state that shows this row: the statement's own year.
    sel, years = year_select(page)
    if sel is not None and years:
        if date[:4] in years:
            _select_option(page, sel, date[:4])
        else:
            # Ally lists documents in its API that its own year picker cannot
            # reach (the tax picker starts at 2020, but the API returns a 2019
            # form). Clicking whatever row is on screen would download some
            # other year's document, so stop here and say why.
            log.warning("%s is not in Ally's year picker (%s..%s) - this "
                        "document cannot be reached from the page",
                        date[:4], min(years), max(years))
            return False
    expand_all(page)

    # Watch which statement the SITE actually serves while we click, so the
    # bytes can be checked against the one we meant to download.
    served_ids: List[str] = []

    def _note_pdf(r):
        try:
            m = SERVED_DOC_ID_RE.search(r.url)
            if m and r.status == 200:
                served_ids.append(m.group(1))
        except Exception:
            pass

    page.on("response", _note_pdf)
    try:
        ok = _download_via_row(page, ctx, account, date, out_path,
                               occurrence, kind, title)
    finally:
        try:
            page.remove_listener("response", _note_pdf)
        except Exception:
            pass

    if not ok:
        return False

    # The whole reason this check exists: several statements per date look
    # identical, so the row we clicked is an inference. The served id is not.
    # If they disagree, the PDF on disk is some OTHER statement - delete it
    # rather than file it under this one's name.
    if document_id and served_ids:
        if document_id not in served_ids:
            log.warning("MISMATCH: wanted %s, Ally served %s - discarding",
                        document_id[-6:], ", ".join(s[-6:] for s in served_ids[:3]))
            try:
                Path(out_path).unlink(missing_ok=True)
            except Exception:
                pass
            return False
        log.info("verified: Ally served the requested statement %s", document_id[-6:])
    elif document_id:
        log.info("could not verify which statement was served for %s", document_id[-6:])
    return True


def _download_via_row(page, ctx, account: str, date: str, out_path: Path,
                      occurrence: int = 0, kind: str = "statement",
                      title: str = "") -> bool:
    """Find this statement's row control and capture the PDF behind it."""
    ctrl = (_find_tax_row_control(page, title, account, occurrence)
            if kind == "tax"
            else _find_row_control(page, date, account, occurrence))
    if ctrl is None:
        log.info("statement row not found for %r %s", account, date)
        return False

    # 1. A direct PDF href needs no click at all - fetch it in the page
    #    context so the session cookies come along.
    try:
        href = ctrl.get_attribute("href") or ""
    except Exception:
        href = ""
    if href and not href.startswith("javascript:") and (".pdf" in href.lower()
                                                        or "statement" in href.lower()):
        url = href if href.startswith("http") else f"{BASE}{href if href.startswith('/') else '/' + href}"
        try:
            b64 = page.evaluate(_FETCH_AS_B64, url)
            if b64 and _write_if_pdf(base64.b64decode(b64), out_path):
                log.info("captured via direct href")
                return True
        except Exception as e:
            log.info("direct fetch failed for %s: %s", url, e)

    # 2. A real download event (the most common mechanism).
    before = {id(p) for p in ctx.pages}
    try:
        with page.expect_download(timeout=20000) as dl:
            ctrl.click()
        dl.value.save_as(str(out_path))
        if out_path.exists() and out_path.read_bytes()[:5] == b"%PDF-":
            log.info("captured via download event")
            return True
    except Exception as e:
        log.info("no download event for %r %s (%s); trying tab capture",
                 account, date, str(e).split("\n")[0])

    # 3. The PDF opened in a new tab (blob: or a URL) - fetch its bytes.
    new_page = None
    for _ in range(24):                                   # up to ~12s
        page.wait_for_timeout(500)
        dismiss_timeout(page)
        for p in ctx.pages:
            if id(p) not in before and not p.is_closed():
                new_page = p
                break
        if new_page:
            break
    if new_page is None:
        log.info("nothing opened for %r %s", account, date)
        return False

    ok = False
    try:
        new_page.wait_for_load_state("domcontentloaded", timeout=15000)
        url = new_page.url or ""
        b64 = page.evaluate(_FETCH_AS_B64, url) if url.startswith("blob:") else \
            new_page.evaluate(_FETCH_AS_B64, url)
        if b64:
            ok = _write_if_pdf(base64.b64decode(b64), out_path)
            if ok:
                log.info("captured via new tab (%s)", url[:80])
    except Exception as e:
        log.info("tab capture failed for %r %s: %s", account, date, e)
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
# see whether Ally offers one. It only listens; it issues no requests.
# ---------------------------------------------------------------------------

_DIGITS_RE = re.compile(r"\d{4,}")


def _redact(value):
    """Mask long digit runs (account/document numbers) but keep the shape."""
    if isinstance(value, str):
        return _DIGITS_RE.sub(lambda m: m.group(0)[:2] + "…" + m.group(0)[-2:], value)
    return value


def probe_statements_api(page) -> dict:
    """Capture the RAW statement records across every year and report what
    fields they actually carry.

    Why this exists: the first probe's 600-character sample happened to show
    only records with a populated trustName. In reality most records leave it
    EMPTY, and several statements share a date - so there must be some other
    field that tells them apart, or a download matched on date alone would
    fetch the wrong statement. This finds that field. Read-only: it listens to
    the page's own traffic and drives only the year picker.
    """
    raw: List[dict] = []

    def on_resp(r):
        try:
            if not STATEMENTS_API_RE.search(r.url):
                return
            if "json" not in (r.headers.get("content-type", "") or "").lower():
                return
            data = json.loads(r.text())
            if isinstance(data, dict) and isinstance(data.get("statements"), list):
                raw.extend(data["statements"])
        except Exception:
            pass

    page.on("response", on_resp)
    try:
        ensure_statements(page)
        page.wait_for_timeout(2000)
        sel, years = year_select(page)
        for y in sorted(years or []):
            if _select_option(page, sel, y):
                page.wait_for_timeout(900)
    except Exception as e:
        log.info("probe_statements_api: %s", e)
    finally:
        try:
            page.remove_listener("response", on_resp)
        except Exception:
            pass

    keys: dict = {}
    for rec in raw:
        if not isinstance(rec, dict):
            continue
        for k, v in rec.items():
            info = keys.setdefault(k, {"present": 0, "empty": 0, "distinct": set()})
            info["present"] += 1
            if v in ("", None, [], {}):
                info["empty"] += 1
            elif len(info["distinct"]) < 12:
                info["distinct"].add(str(_redact(v))[:60])

    # Same-date clusters are the ones that must be told apart.
    by_date: dict = {}
    for rec in raw:
        if isinstance(rec, dict):
            by_date.setdefault((rec.get("uploadDate") or "")[:10], []).append(rec)
    clashes = {d: recs for d, recs in by_date.items() if len(recs) > 1}
    worst = sorted(clashes.items(), key=lambda kv: -len(kv[1]))[:2]

    return {
        "total_records": len(raw),
        "fields": {k: {"present": v["present"], "empty": v["empty"],
                       "distinct_sample": sorted(v["distinct"])[:12]}
                   for k, v in sorted(keys.items())},
        "dates_with_more_than_one_statement": len(clashes),
        "example_clusters": [
            {"date": d, "records": [{k: _redact(v) for k, v in r.items()} for r in recs]}
            for d, recs in worst],
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
# Reading a saved statement PDF
#
# Ally's API describes several statements per date identically, so the only
# authoritative statement of what a PDF covers is the PDF itself. Its first
# page carries an account-summary table and the addressee block:
#
#     Account Name                    Account Number    Beginning ...
#     <nickname>                          xxxxxx1234
#     <nickname>                          xxxxxx5678
#     Total Account Balances:
#
# These are parsed STRUCTURALLY - by Ally's own template text and the masked
# account-number column - never by a list of expected account names. Account
# nicknames are chosen by each customer, so any such list would only ever fit
# the person who wrote it. A customer with one account yields one row.
#
# Everything here is plain string matching: deterministic, offline, and it
# returns nothing rather than a guess when the layout is not recognised.
# ===========================================================================
STMT_TABLE_START_RE = re.compile(r"account\s+name\s+account\s+number", re.I)
STMT_TABLE_END_RE = re.compile(r"^\s*total\s+account\s+balances", re.I)
# "<nickname><gap>xxxxxx1234" - the masked column is what marks a real row.
STMT_ACCOUNT_ROW_RE = re.compile(r"^\s*(?P<name>\S.*?)\s{2,}x+(?P<last4>\d{4})\b")
STMT_STREET_RE = re.compile(r"^\s*\d+\s+\w")
STMT_NAME_LINE_RE = re.compile(r"^\s*([A-Z][A-Z0-9 .,'&/-]{3,60})\s*$")


@dataclass
class StatementFacts:
    """What a statement PDF says about itself."""
    accounts: List[Tuple[str, str]]      # [(nickname, last4), ...] in page order
    addressee: str = ""                  # the name this copy was addressed to

    @property
    def ok(self) -> bool:
        return bool(self.accounts)

    def account_summary(self, max_len: int = 90) -> str:
        """The accounts this statement covers, for a filename."""
        names = [n for n, _ in self.accounts]
        joined = " + ".join(names)
        if len(joined) <= max_len:
            return joined
        # too many accounts to name: keep the first and count the rest
        return f"{names[0]} +{len(names) - 1} more"[:max_len]


def read_statement_facts(pdf_path) -> StatementFacts:
    """Parse an Ally statement PDF's first page. Never raises."""
    try:
        from pypdf import PdfReader
    except Exception:
        return StatementFacts([])
    try:
        page = PdfReader(str(pdf_path)).pages[0]
        try:
            # layout mode keeps the table's columns apart; without it the
            # header and the first nickname run together
            text = page.extract_text(extraction_mode="layout") or ""
        except Exception:
            text = page.extract_text() or ""
    except Exception as e:
        log.info("could not read %s: %s", pdf_path, e)
        return StatementFacts([])

    return parse_statement_text(text)


def parse_statement_text(text: str) -> StatementFacts:
    """The parsing half of read_statement_facts, over already-extracted text.

    Split out so it can be tested without shipping a real bank statement as a
    fixture - the regexes are the part that breaks when Ally restyles.
    """
    lines = (text or "").splitlines()
    accounts: List[Tuple[str, str]] = []
    in_table = False
    for ln in lines:
        if not in_table:
            if STMT_TABLE_START_RE.search(ln):
                in_table = True
            continue
        if STMT_TABLE_END_RE.search(ln):
            break
        m = STMT_ACCOUNT_ROW_RE.match(ln)
        if m:
            accounts.append((" ".join(m.group("name").split()), m.group("last4")))

    addressee = ""
    for i, ln in enumerate(lines[:40]):
        if i and STMT_STREET_RE.match(ln):
            m = STMT_NAME_LINE_RE.match(lines[i - 1])
            if m:
                addressee = " ".join(m.group(1).split())
                break
    return StatementFacts(accounts, addressee)


_NAME_MINOR = {"and", "of", "the", "for", "de", "la", "van", "von"}


def normalize_name(name: str) -> str:
    """Ally prints the addressee in block capitals ("PAT Q SAMPLE AND ALEX
    EXAMPLE"). Filenames read better in title case. A name that is not
    all-caps is left exactly as it is - it may already be cased deliberately
    ("McTavish", "O'Neil-Smith")."""
    name = " ".join((name or "").split())
    if not name or not name.isupper():
        return name
    out = []
    for i, word in enumerate(name.split(" ")):
        low = word.lower()
        out.append(low if (i and low in _NAME_MINOR) else
                   "-".join(p[:1].upper() + p[1:] for p in low.split("-")))
    return " ".join(out)


# ===========================================================================
# Tax forms
#
# The documents page is "statements-and-forms", and the statements API takes a
# docType parameter (docType=STATEMENTS), which all but names a sibling value
# for forms. Rather than hardcode a guess at that value, this opens the page's
# own tax tab and captures whatever request the SPA makes - so it keeps working
# if Ally renames the parameter, and it never invents a URL.
#
# The payload shape is read tolerantly for the same reason: the list is found
# by looking for the array in the response, and each record's id/name/date by
# trying the key names Ally is known to use. Anything unrecognised is skipped
# and logged rather than guessed at.
# ===========================================================================
# The form designation as it appears in a tax row: "1099-INT", "1098-E",
# "5498-SA", "W-2". Ally's API titles these "Form 1099-INT"; the page does not.
FORM_CODE_RE = re.compile(r"\b(?:1099|1098|5498|1042|W)-?[A-Z0-9]{0,4}\b")
TAX_TAB_RE = re.compile(r"^\s*tax\s*(forms?|documents?|center|info\w*)?\s*$", re.I)
ACS_API_RE = re.compile(r"/acs/v\d+/", re.I)

# Where a document list hides in a response, in order of preference.
DOC_LIST_KEYS = ("taxForms", "taxDocuments", "forms", "documents", "statements")
# Candidate field names on one record.
ID_KEYS = ("documentId", "id", "formId", "documentID")
NAME_KEYS = ("documentName", "formName", "formType", "documentType", "name", "title")
DATE_KEYS = ("uploadDate", "documentDate", "postedDate", "createdDate", "date")
YEAR_KEYS = ("taxYear", "year")


def click_tax_tab(page) -> bool:
    """Open the tax area of the documents page. The control must clear the
    read-only guard like any other."""
    for role in ("tab", "link", "button"):
        try:
            loc = page.get_by_role(role, name=TAX_TAB_RE)
            n = min(loc.count(), 4)
        except Exception:
            continue
        for i in range(n):
            c = loc.nth(i)
            try:
                if not c.is_visible():
                    continue
                label = (c.inner_text(timeout=1000) or "").strip()
            except Exception:
                continue
            if not is_safe_control(label):
                continue
            try:
                c.click()
                page.wait_for_timeout(3000)
                dismiss_timeout(page)
                log.info("opened tax area via %s %r -> %s", role, label, page.url)
                return True
            except Exception as e:
                log.info("tax tab click failed: %s", e)
    log.info("no tax tab found on the documents page")
    return False


def _find_doc_list(data):
    """(key, items) for the document array in a response, or (None, [])."""
    if not isinstance(data, dict):
        return None, []
    for key in DOC_LIST_KEYS:
        items = data.get(key)
        if isinstance(items, list) and items and isinstance(items[0], dict):
            return key, items
    # any other array of objects, so a renamed key still works
    for key, items in data.items():
        if isinstance(items, list) and items and isinstance(items[0], dict):
            return key, items
    return None, []


def _first_key(rec: dict, keys) -> str:
    for k in keys:
        v = rec.get(k)
        if v not in (None, "", []):
            return str(v).strip()
    return ""


def _normalize_tax_record(rec: dict) -> Optional[dict]:
    """One tax-form record -> the dict the orchestrator records, or None.

    Filed by TAX YEAR, not by the date Ally posted it. The 1099-INT for 2025
    is issued in January 2026, and an archive where the 2025 form sits under
    2026 is wrong in the only way that matters at tax time. taxYear is used
    when present (confirmed live: {"taxYear": 2025, "uploadDate":
    "2026-01-10"}); the posting date is only a fallback.
    """
    doc_id = _first_key(rec, ID_KEYS)
    title = _first_key(rec, NAME_KEYS) or "Tax Document"
    date, _ = parse_period_date(_first_key(rec, YEAR_KEYS))
    if not date:
        raw_date = _first_key(rec, DATE_KEYS)
        if re.match(r"\d{4}-\d{2}-\d{2}", raw_date or ""):
            date = raw_date[:10]
        else:
            date, _ = parse_period_date(raw_date or title)
    if not date:
        log.info("tax record with no usable date, skipped: keys=%s",
                 ",".join(sorted(rec.keys()))[:120])
        return None
    trust = re.sub(r"\s+", " ", (rec.get("trustName") or "")).strip()
    return {"documentId": doc_id, "date": date, "title": title,
            "account": trust, "ira": bool(rec.get("iraType")),
            # a corrected form supersedes the original and must not overwrite
            # it or be mistaken for it
            "corrected": bool(rec.get("corrected")),
            "label": "", "occurrence": 0, "ambiguous": False, "kind": "tax"}


def ally_collect_tax_via_api(page) -> List[dict]:
    """Tax forms, read the same way statements are: open the tax area, walk
    the year picker, and capture the SPA's own JSON."""
    captured: List[dict] = []
    seen_shapes: List[str] = []

    def on_resp(r):
        try:
            if not ACS_API_RE.search(r.url):
                return
            if "json" not in (r.headers.get("content-type", "") or "").lower():
                return
            if STATEMENTS_API_RE.search(r.url) and "statements" in r.url.lower() \
                    and "tax" not in r.url.lower():
                return                     # that is the statements list
            key, items = _find_doc_list(json.loads(r.text()))
            if items:
                captured.extend(items)
                shape = f"{r.url.split('?')[0]} key={key} fields={','.join(sorted(items[0].keys()))}"
                if shape not in seen_shapes:
                    seen_shapes.append(shape)
                    log.info("tax payload: %s", shape[:220])
        except Exception:
            pass

    page.on("response", on_resp)
    try:
        if not ensure_statements(page):
            return []
        if not click_tax_tab(page):
            return []
        page.wait_for_timeout(2500)
        sel, years = year_select(page)
        if sel is not None and years:
            for y in sorted(years):
                if _select_option(page, sel, y):
                    page.wait_for_timeout(1200)
    finally:
        try:
            page.remove_listener("response", on_resp)
        except Exception:
            pass

    out, seen = [], set()
    for rec in captured:
        norm = _normalize_tax_record(rec)
        if not norm:
            continue
        key = norm["documentId"] or f"{norm['date']}|{norm['title']}"
        if key in seen:
            continue
        seen.add(key)
        out.append(norm)

    # Same guard as statements: if two forms would land on the same name,
    # number them so neither silently overwrites the other.
    groups: dict = {}
    for rec in out:
        groups.setdefault((rec["date"], rec["title"], rec["account"],
                           rec["corrected"]), []).append(rec)
    for sibs in groups.values():
        for i, rec in enumerate(sibs):
            rec["occurrence"] = i
            rec["ambiguous"] = len(sibs) > 1

    out.sort(key=lambda r: r["date"], reverse=True)
    log.info("tax forms found: %d", len(out))
    return out


def _find_tax_row_control(page, title: str, account: str = "",
                          occurrence: int = 0):
    """The download control on the tax row for this form.

    The form name alone is NOT enough. Ally issues one 1099-INT per
    registration per tax year, and every one of them is titled "Form
    1099-INT" - so matching on the name found the first row every time and
    served the same PDF for both. (The served-id check caught exactly this on
    2026-08-18: "wanted 022499, Ally served 022500".)

    So the registration is matched first, exactly as statement rows are, and
    position within the year is the fallback for rows that carry no name.
    """
    needle = (title or "").strip()
    if not needle:
        return None
    # The row names the form as bare "1099-INT" while the API calls it "Form
    # 1099-INT", so matching on the API's title finds only the rows whose
    # registration text happens to contain the word "Form". Match on the form
    # CODE first - that is what actually appears in the row.
    code = FORM_CODE_RE.search(needle)
    short = re.sub(r"^\s*form\s+", "", needle, flags=re.I)
    short = re.sub(r"\s*(tax\s*)?(form|document)s?\s*$", "", short, flags=re.I).strip()

    matches = []
    for candidate in [code.group(0) if code else "", short, needle]:
        if not candidate:
            continue
        try:
            rows = page.locator("tr, [role='row'], li").filter(has_text=candidate)
            n = min(rows.count(), 20)
        except Exception:
            continue
        for i in range(n):
            row = rows.nth(i)
            if _row_download_control(row) is None:
                continue
            try:
                text = re.sub(r"\s+", " ", row.inner_text(timeout=800) or "")
            except Exception:
                text = ""
            matches.append((row, text))
        if matches:
            break
    if not matches:
        log.info("no tax row found for %r", title)
        return None

    if account:
        name = account[:24].strip().lower()
        for row, text in matches:
            if name and name in text.lower():
                return _row_download_control(row)
        log.info("no tax row for registration %r (%s)", account[:40], title)
        return None

    # No registration on this record: take the Nth row that names none either,
    # so it can never collide with a registration-labelled form.
    plain = [(row, text) for row, text in matches
             if not re.search(r"\btrust\b", text, re.I)]
    if occurrence < len(plain):
        return _row_download_control(plain[occurrence][0])
    log.info("wanted tax form #%d of %d for %s - not present",
             occurrence + 1, len(plain), title)
    return None
