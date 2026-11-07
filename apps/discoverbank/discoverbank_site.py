"""ALL Discover Bank selectors, URLs, and page behavior live here.

When Discover changes its site, repair this file only.

SCOPE: Discover **Bank** deposit accounts (Checking, Savings, Money Market, CD).
Discover credit cards, personal loans, student loans and home loans are separate
portals and are out of scope. card.discover.com and cards.discover.com are strictly rejected.

SAFETY (this is a banking deposit account):
  This module is strictly READ-ONLY. It opens the statements/documents area,
  reads the list of documents, and downloads the PDFs Discover already
  generated. It must NEVER activate any control that pays a bill, sets up
  autopay, moves money, transfers funds, deposits checks, orders checks,
  freezes or replaces a debit card, closes an account, or changes any setting.
  The guard is FORBIDDEN_CONTROL_RE; every click path checks it, and a control
  must ALSO look like a document action (SAFE_DOC_CONTROL_RE) before it may be
  clicked. Dropdowns are controls too - see MONEY_CONTROL_RE and
  is_forbidden_control_context - allowing Checking/Savings account options in
  dropdown context while refusing payment/transfer widgets.
"""
from __future__ import annotations

import base64
import html as _html
import json
import logging
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import urljoin, urlparse, urlsplit

from paperpull_core import intake
from paperpull_core import controls as _controls
from paperpull_core import redirects
from paperpull_core.controls import (
    AUTH_CONTROL_RE,
    SETTINGS_CONTROL_RE,
    click_next_page as _click_next_page,
)
from paperpull_core.dates import last_day as _last_day
from paperpull_core.dates import checked as _checked_date
from paperpull_core.characters import whole_json

log = logging.getLogger("discoverbank_docs.site")

BASE = "https://bank.discover.com"
PUBLIC = "https://www.discover.com"

ALLOWED_HOSTS = ("bank.discover.com", "www.discover.com")
FORBIDDEN_HOSTS = ("card.discover.com", "cards.discover.com")

URLS = {
    "login": f"{PUBLIC}/",
    "documents": f"{BASE}/web/deposits/documents/statements",
}
DOCUMENT_URL_CANDIDATES = [URLS["documents"]]

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
    r"\b(transfer|withdraw|wire|zelle|send\s+money|move\s+money|deposit|"
    r"pay\s+bills?|bill\s*pay|make\s+a?\s*payment|autopay|order\s+checks?|"
    r"open\b|apply\b|close\s+account|freeze|lock\s+card|replace\s+card|overdraft|"
    r"dispute\b|delete\b|manage\b|profile|link\s+account|"
    r"settings?\b|edit\s+profile|manage\s+alerts?|change\s+password)\b",
    re.I,
)

SAFE_DOC_CONTROL_RE = re.compile(
    r"\b(statements?|tax\s+forms?|documents?|year\s+\d{4}|accordion|"
    r"pdf|download|expand|(?:checking|savings|money\s*market|\bcd\b)\s*(?:\([^\)]*\)|\bstatement\b))",
    re.I,
)


def is_safe_url(url: str) -> bool:
    if not url:
        return False
    try:
        parsed = urlsplit(url)
    except ValueError:
        return False
    if parsed.scheme != "https":
        return False
    if parsed.username or parsed.password:
        return False
    try:
        port = parsed.port
    except ValueError:
        return False
    if port not in (None, 443):
        return False
    host = (parsed.hostname or "").lower()
    if host in FORBIDDEN_HOSTS or "card.discover.com" in host or "cards.discover.com" in host:
        return False
    return host in ALLOWED_HOSTS


def is_safe_control(name: str) -> bool:
    if not name:
        return False
    cleaned = name.strip()
    if FORBIDDEN_CONTROL_RE.search(cleaned):
        return False
    if SETTINGS_CONTROL_RE.search(cleaned) or AUTH_CONTROL_RE.search(cleaned):
        return False
    return bool(SAFE_DOC_CONTROL_RE.search(cleaned))

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

# ---------------------------------------------------------------------------
# Date parsing (shared with the other projects)
# ---------------------------------------------------------------------------
DATE_PATTERNS = [
    (re.compile(r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
                r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|"
                r"Dec(?:ember)?)\.?\s+(\d{1,2}),?\s+(\d{4})", re.I), "mdY"),
    (re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b"), "mdy_slash"),
    (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})(?!\d)"), "iso"),
]
_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
MONTH_YEAR_RE = re.compile(
    r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
    r"Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    r"\s+(\d{4})", re.I)
QUARTER_RE = re.compile(r"\bQ([1-4])\s*[' ]?\s*(\d{4})\b", re.I)
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
    # The public marketing site is on www.discover.com without a login marker
    if url.startswith("https://www.discover.com/") and not any(m in url for m in LOGIN_URL_MARKERS):
        return True
    return False


# Capital One acquired Discover, and card servicing is being moved onto
# Capital One's own site account by account. Once an account has moved, nothing
# this app knows how to read still exists, and the honest answer is to say so
# and point to the capitalone app, which reads a moved card on capitalone.com.
# Without this the run reported "could not open your Discover statements, sign
# in and try again", which sends someone to fix a sign-in that is not broken.
MOVED_HOSTS = ("capitalone.com", "capitalone360.com")


def looks_moved_to_capital_one(page) -> bool:
    """True when the open tab has landed on Capital One.

    Host equality on the parsed hostname, not a substring, for the same reason
    every other host check here works that way.
    """
    from urllib.parse import urlparse
    try:
        host = (urlparse(page.url or "").hostname or "").lower()
    except ValueError:
        return False
    return any(host == h or host.endswith("." + h) for h in MOVED_HOSTS)


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
    """Are we on the deposit statements page?

    Checks for deposit document URL paths and key deposit statements page elements.
    """
    try:
        if looks_public_or_error(page) or looks_signed_out(page):
            return False
        url = (page.url or "").lower()
        if "/web/deposits/documents" in url:
            return True
        if page.locator('button[class*="_dropdown_"], [data-testid*="document"], button[class*="card-item-btn"]').count() > 0:
            return True
        return False
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
    """One page forward, through a control that says it pages forward.

    Judged by an allowlist in the core rather than by FORBIDDEN_CONTROL_RE,
    because that blocklist refuses the word "next". Correctly, since "Next"
    is also what a wizard's commit button says, and fatally here, because it
    meant this could never page forward at all and the run reported success
    having seen only the first page.
    """
    return _click_next_page(page, FALLBACK["next_page"])


@dataclass
class RawDoc:
    title: str
    date_text: str = ""
    href: str = ""
    text: str = ""
    account: str = ""
    row_index: int = 0
    kind: str = "doc"

    def get(self, key: str, default=None):
        if key == "date":
            return self.date_text or default
        if key == "documentId":
            return self.href or default
        return getattr(self, key, default)

    def __getitem__(self, key: str):
        val = self.get(key)
        if val is None:
            raise KeyError(key)
        return val


def parse_statements_api(json_data: list, account_label: str) -> List[RawDoc]:
    docs: List[RawDoc] = []
    if not isinstance(json_data, list):
        return docs
    acc_lower = (account_label or "").lower()

    for i, item in enumerate(json_data):
        if not isinstance(item, dict):
            continue
        stmt_date = (item.get("statementDate") or "")[:10]  # YYYY-MM-DD
        name = item.get("name", "")
        binary_href = ""
        for link in item.get("links", []):
            if isinstance(link, dict) and link.get("rel") == "binary":
                binary_href = link.get("href", "")
                break
        if binary_href and binary_href.startswith("/"):
            binary_href = urljoin(BASE, binary_href)
        if not binary_href or not is_safe_url(binary_href):
            continue

        href_lower = binary_href.lower()
        if "~osa~" in href_lower or "-osa" in href_lower:
            account_clean = "Savings"
            account_name = account_label if (account_label and "savings" in acc_lower) else (account_label or "Savings")
        elif "~oc~" in href_lower or "-oc" in href_lower:
            account_clean = "Checking"
            account_name = account_label if (account_label and "checking" in acc_lower) else (account_label or "Checking")
        elif "money market" in acc_lower or "~mm~" in href_lower:
            account_clean = "Money Market"
            account_name = account_label or "Money Market"
        elif "cd" in acc_lower or "certificate" in acc_lower or "~cd~" in href_lower:
            account_clean = "CD"
            account_name = account_label or "CD"
        elif "savings" in acc_lower:
            account_clean = "Savings"
            account_name = account_label or "Savings"
        else:
            account_clean = "Checking"
            account_name = account_label or "Checking"

        docs.append(
            RawDoc(
                title=f"{account_clean} Statement",
                date_text=stmt_date,
                href=binary_href,
                text=name,
                account=account_name,
                row_index=i,
            )
        )
    return docs


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
# read-only behavior even when nothing is submitted.
#
# A card dashboard has the same hazard in its "pay from" picker, so every
# <select> is identity-checked before it is read OR written, and the check
# FAILS CLOSED when an identity cannot be read.
# ---------------------------------------------------------------------------
_ACCOUNT_HINT_RE = re.compile(
    r"(checking|savings|money\s*market|\bcd\b|certificate|spending|"
    r"interest|account|x{2,}\d|\*{2,}\d|\.{3}\d{3,}|\d{4}\s*$)", re.I)

# The guard that decides whether a control may be touched now lives in
# paperpull_core.controls - this app's copy was the third one written, the
# first to consider that a control might belong to a sign-in form, and the
# version the core module was built from. Deleting it here means the next
# lesson lands in one place instead of three.
#
# What stays in this file is this provider's own vocabulary:
# FORBIDDEN_CONTROL_RE above, and PRODUCT_PICKER_RE below, passed to the core
# as an extra rule. A PRODUCT chooser ("which Discover product?") is not a
# document picker, and its OPTIONS alone give it away wherever it appears, so
# they are checked against the same pattern.
PRODUCT_PICKER_RE = re.compile(
    r"credit\s+cards?|student\s+loans?|personal\s+loans?|home\s+loans?|"
    r"mortgage|auto\s+loans?", re.I)

# Re-exported because the tests and the rest of this module refer to them.
MONEY_CONTROL_RE = _controls.MONEY_CONTROL_RE
AUTH_CONTROL_RE = _controls.AUTH_CONTROL_RE
control_identity = _controls.control_identity

_EXTRA_RES = (PRODUCT_PICKER_RE,)


def is_forbidden_control_context(identity: Optional[str],
                                 options: Optional[List[str]] = None) -> bool:
    """This provider's controls, judged by the shared rules. Fails CLOSED on
    an unreadable identity, exactly as the core does."""
    if not identity:
        return True
    opts = options or []
    for opt in opts:
        if PRODUCT_PICKER_RE.search(opt or ""):
            return True
    return _controls.is_forbidden_context(identity, FORBIDDEN_CONTROL_RE,
                                          extra_res=_EXTRA_RES,
                                          options=opts)


def is_money_control(identity: str) -> bool:
    """Kept for callers that only ask the narrower question. Still fails
    closed, and still refuses anything the full check would refuse."""
    return is_forbidden_control_context(identity)


def _safe_selects(page, limit: int = 12):
    """Yield (locator, identity) for the <select> elements safe to touch.

    The core refuses by identity; the option labels are then read (harmless)
    and checked too, because a product picker is identifiable from its
    options alone even when its identity looks innocent.
    """
    for s, identity in _controls.safe_selects(page, FORBIDDEN_CONTROL_RE,
                                              signed_out=looks_signed_out,
                                              extra_res=_EXTRA_RES,
                                              limit=limit):
        try:
            options = s.locator("option").all_text_contents()
        except Exception:
            options = []
        if is_forbidden_control_context(identity, options):
            log.info("refusing dropdown by its options: %s", identity[:120])
            continue
        yield s, identity


def describe_selects(page, limit: int = 12) -> List[dict]:
    return _controls.describe_selects(page, FORBIDDEN_CONTROL_RE,
                                      extra_res=_EXTRA_RES, limit=limit)


# The options of a dropdown that can be chosen. A turned off one cannot be,
# and choosing it waited out its time and was taken for an account or a
# year that would not take.
_ENABLED_OPTION = "option:not([disabled])"


class Listed(list):
    """The documents a walk of the list read. passed_over names each part
    of the list a dropdown offered and the walk could not read through,
    "account picker" or "year picker", so the list is not whole however
    much was read."""
    passed_over: tuple = ()


def _listed(items, passed_over=()) -> Listed:
    out = Listed(items)
    out.passed_over = tuple(sorted(set(passed_over)))
    return out


def account_select(page):
    """Return (locator, [labels]) for a <select> that lists accounts, or
    (None, []).

    Money-movement widgets, sign-in forms and product pickers are refused
    outright by _safe_selects before this ever sees them.
    """
    for s, _identity in _safe_selects(page):
        try:
            opts = [o.strip() for o in s.locator(_ENABLED_OPTION).all_inner_texts()]
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
            opts = [o.strip() for o in s.locator(_ENABLED_OPTION).all_inner_texts()]
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


_STATEMENTS_FETCH_JS = """async (url) => {
  const ppTarget = new URL(url, location.href);
  if (ppTarget.protocol !== "https:" || ppTarget.hostname !== "bank.discover.com" || ppTarget.username || ppTarget.password || (ppTarget.port && ppTarget.port !== "443")) throw new Error("Refusing an off-host document request");
  const res = await fetch(url, { credentials: 'include' });
  if (!res.ok) return [];
  return await res.json();
}"""

_DOWNLOAD_BYTES_JS = """async (url) => {
  const ppTarget = new URL(url, location.href);
  if (ppTarget.protocol !== "https:" || ppTarget.hostname !== "bank.discover.com" || ppTarget.username || ppTarget.password || (ppTarget.port && ppTarget.port !== "443")) throw new Error("Refusing an off-host document request");
  const r = await fetch(url, { credentials: 'include', headers: { 'Accept': 'application/pdf' } });
  if (r.status !== 200) {
    const text = await r.text();
    return { ok: false, status: r.status, b64: '', text: text.slice(0, 300) };
  }
  let s = '';
  const bytes = await ppRead(r);
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk)
    s += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
  return { ok: true, status: r.status, b64: btoa(s), text: '' };
}"""


def list_deposit_accounts(page) -> List[dict]:
    """Inspects account dropdown to return all deposit accounts."""
    try:
        # Check React fiber first for instant, non-invasive option discovery
        fiber_options = page.evaluate("""() => {
            const btn = document.querySelector("button[class*='_dropdown_']");
            if (!btn) return null;
            const key = Object.keys(btn).find(k => k.startsWith("__reactFiber"));
            if (!key) return null;
            let curr = btn[key];
            while (curr) {
                if (curr.memoizedProps && Array.isArray(curr.memoizedProps.options)) {
                    return curr.memoizedProps.options.map((o, i) => ({
                        index: i,
                        text: o.label || '',
                        id: o.id || o.value || ''
                    }));
                }
                curr = curr.return;
            }
            return null;
        }""")
        if fiber_options:
            results = []
            for opt in fiber_options:
                txt = opt.get("text", "")
                if txt and not FORBIDDEN_CONTROL_RE.search(txt) and is_safe_control(txt):
                    results.append(opt)
            if results:
                return results

        btn = page.locator('button[class*="_dropdown_"]').first
        if btn.count() == 0:
            return []
        txt = (btn.inner_text() or "").strip()
        aria = btn.get_attribute("aria-label") or ""
        combined = f"{txt} {aria}".strip()
        if FORBIDDEN_CONTROL_RE.search(combined):
            log.warning("Dropdown button matches forbidden words: %r", combined)
            return []
        if btn.get_attribute("aria-expanded") != "true":
            btn.click()
            page.wait_for_timeout(300)
        options = page.locator('[role="option"], ul[role="listbox"] li')
        results = []
        for i in range(options.count()):
            opt_text = options.nth(i).inner_text().strip()
            if not FORBIDDEN_CONTROL_RE.search(opt_text) and is_safe_control(opt_text):
                results.append({"index": i, "text": opt_text})
        if btn.get_attribute("aria-expanded") == "true":
            btn.click()
        return results
    except Exception as e:
        log.warning("list_deposit_accounts failed: %s", e)
        return []


def discoverbank_collect(page) -> Listed:
    """Collects statements across all available deposit accounts."""
    all_docs: List[RawDoc] = []
    seen_hrefs = set()

    # 1. First, check if accounts and their IDs can be extracted directly from React fiber
    try:
        acct_options = page.evaluate("""() => {
            const btn = document.querySelector("button[class*='_dropdown_']");
            if (!btn) return [];
            const key = Object.keys(btn).find(k => k.startsWith("__reactFiber"));
            if (!key) return [];
            let curr = btn[key];
            while (curr) {
                if (curr.memoizedProps && Array.isArray(curr.memoizedProps.options)) {
                    return curr.memoizedProps.options.map(o => ({
                        label: o.label || '',
                        id: o.id || o.value || ''
                    }));
                }
                curr = curr.return;
            }
            return [];
        }""")
    except Exception as e:
        log.warning("Could not read React fiber account options: %s", e)
        acct_options = []

    # If accounts were found in React fiber, fetch statements directly for each account
    if acct_options:
        log.info("Discovered %d account(s) from React state: %s",
                 len(acct_options), [a.get("label") for a in acct_options])
        for acct in acct_options:
            acct_id = acct.get("id")
            acct_label = acct.get("label", "")
            if not acct_id:
                continue
            if not is_safe_control(acct_label) or FORBIDDEN_CONTROL_RE.search(acct_label):
                log.warning("Skipping unsafe account option %r", acct_label)
                continue
            url = f"https://bank.discover.com/bank/deposits/servicing/documents/v1/accounts/{acct_id}/statements"
            try:
                raw_json = intake.evaluate(page, _STATEMENTS_FETCH_JS, url)
                if isinstance(raw_json, list):
                    docs = parse_statements_api(raw_json, acct_label)
                    for d in docs:
                        if d.href not in seen_hrefs:
                            seen_hrefs.add(d.href)
                            all_docs.append(d)
            except Exception as e:
                log.warning("Direct fetch failed for account %s (%s): %s", acct_label, acct_id, e)

        if all_docs:
            return _listed(all_docs)

    # 2. Fallback: discover endpoints from performance entries and cycle dropdown if needed
    accounts = list_deposit_accounts(page)

    # First discover any statement endpoints already present in browser performance entries
    try:
        endpoints = page.evaluate("""() => {
            return Array.from(new Set(
                performance.getEntriesByType('resource')
                    .map(r => r.name)
                    .filter(url => 
                        url.startsWith('https://bank.discover.com/bank/deposits/') &&
                        url.includes('/statements') && 
                        !url.includes('bankprod2')
                    )
            ));
        }""")
    except Exception as e:
        log.warning("Could not read performance entries: %s", e)
        endpoints = []

    # If performance entries do not cover all accounts, cycle the dropdown to load them
    if accounts and len(endpoints) < len(accounts):
        for acc in accounts:
            idx = acc["index"]
            label = acc["text"]
            if not is_safe_control(label) or FORBIDDEN_CONTROL_RE.search(label):
                log.warning("Refusing to switch to unsafe account control: %r", label)
                continue
            try:
                btn = page.locator('button[class*="_dropdown_"]').first
                if btn.count() > 0:
                    if btn.get_attribute("aria-expanded") != "true":
                        btn.click()
                        page.wait_for_timeout(300)
                    options = page.locator('[role="option"], ul[role="listbox"] li')
                    if options.count() > idx:
                        options.nth(idx).click()
                        page.wait_for_timeout(1000)
            except Exception as e:
                log.warning("Could not switch to account %s (idx %d): %s", label, idx, e)

        try:
            endpoints = page.evaluate("""() => {
                return Array.from(new Set(
                    performance.getEntriesByType('resource')
                        .map(r => r.name)
                        .filter(url => 
                            url.startsWith('https://bank.discover.com/bank/deposits/') &&
                            url.includes('/statements') && 
                            !url.includes('bankprod2')
                        )
                ));
            }""")
        except Exception:
            pass

    for ep in endpoints:
        try:
            raw_json = intake.evaluate(page, _STATEMENTS_FETCH_JS, ep)
            if isinstance(raw_json, list):
                label = ""
                for a in accounts:
                    txt = a.get("text", "")
                    if ("~osa~" in ep.lower() or "-osa" in ep.lower()) and "savings" in txt.lower():
                        label = txt
                        break
                    elif ("~oc~" in ep.lower() or "-oc" in ep.lower()) and "checking" in txt.lower():
                        label = txt
                        break
                docs = parse_statements_api(raw_json, label)
                for d in docs:
                    if d.href not in seen_hrefs:
                        seen_hrefs.add(d.href)
                        all_docs.append(d)
        except Exception as e:
            log.warning("API statement collection failed for %s: %s", ep, e)

    return _listed(all_docs)


def discovercard_collect(page) -> Listed:
    """Every statement Discover still has: a list of {account, date, title}.

    Walks the account dropdown (if there is one) and, within each account,
    every year in the period dropdown - so the full history is captured, not
    just the default view.

    This is the DOM fallback. discovercard_collect_via_api is tried first; this runs
    only if the API answered nothing (a redesign, or a locked-down session).

    A year or an account whose choice did not take was not read, and is
    named in passed_over, where it used to be passed over and the list
    noted whole without it. One the guard refuses is never chosen.
    """
    docs: List[dict] = []
    seen = set()
    passed_over = set()

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
                    passed_over.add("year picker")
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
            if FORBIDDEN_CONTROL_RE.search(a):
                # Never chosen (_select_option), and no account whose
                # statements are listed.
                log.info("refusing account option %r", a[:60])
                continue
            if not _select_option(page, acct_sel, a):
                passed_over.add("account picker")
                continue
            walk_years(re.sub(r"\s+", " ", a).strip())
    else:
        walk_years("")
    return _listed(docs, passed_over)


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
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = out_path.with_suffix(f".tmp.{os.getpid()}")
    try:
        tmp_path.write_bytes(data)
        os.replace(tmp_path, out_path)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink()
        raise
    return True


def discoverbank_download(
    page, ctx, account: str, date: str, out_path: Path, href: str = "", **kw
) -> bool:
    """Downloads statement PDF via authenticated fetch, verifying %PDF- signature."""
    href = href or kw.get("document_id", "")
    if href and href.startswith("/"):
        href = urljoin(BASE, href)
    if not href:
        log.warning("No download URL provided for %s %s", account, date)
        return False

    if not is_safe_url(href):
        log.warning("Refusing to download from unsafe URL: %s", href)
        return False

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    result = intake.evaluate(page, _DOWNLOAD_BYTES_JS, href)

    if not isinstance(result, dict) or not result.get("ok") or not result.get("b64"):
        err = result.get("text") if isinstance(result, dict) else "unknown error"
        log.error("Failed to fetch statement bytes from %s: %s", href, err)
        return False

    pdf_bytes = intake.decode(result["b64"])
    return _write_if_pdf(pdf_bytes, out_path)


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
# of a URL the page published). This is NOT the "synthesize an endpoint" move
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


def resolve_statement_url(href: str) -> Optional[str]:
    """The absolute URL to fetch, or None if the href leaves Discover's host.

    The fetch below carries the signed-in session's cookies, so an absolute
    href must be on BASE's own scheme and host before it may be followed - a
    hostile absolute href sitting in the DOM must not be able to send those
    cookies anywhere else. Parsed and compared, never a string prefix: a
    prefix check passes both a suffix host (card.discover.com.evil.test) and
    a userinfo host (card.discover.com@evil.test), which is exactly how the
    UKG app's tenant guard was once walked through.
    """
    parts = urlsplit(href)
    if not parts.scheme and not parts.netloc:
        return BASE + href
    base = urlsplit(BASE)
    if (parts.scheme, parts.hostname) == (base.scheme, base.hostname):
        return href
    return None


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

    # The URL must still be one of Discover's own statement URLs, on
    # Discover's own host, and must still name the date we want. A stored
    # href from an earlier run cannot send this anywhere else.
    if not STMT_PDF_RE.search(href):
        log.warning("refusing a non-statement URL for %s: %s", date, href[:80])
        return False
    want = date.replace("-", "")
    if want and want not in href:
        log.warning("MISMATCH: %s does not name %s - refusing", href[:80], want)
        return False

    url = resolve_statement_url(href)
    if not url:
        log.warning("refusing an off-host statement URL for %s: %s",
                    date, href[:80])
        return False
    # Every redirect on the way has to stay on Discover's hosts as well.
    # Playwright alone would follow one wherever it led, carrying the
    # session's cookies, so each hop is checked before it is asked.
    try:
        resp = redirects.get(ctx.request, url, is_safe_url, timeout=90000)
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
        data = intake.body(resp)
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
            data = whole_json(json.loads(body))
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


