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

import html as _html
import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import urljoin, urlsplit

from paperpull_core import intake
from paperpull_core import controls as _controls
from paperpull_core.controls import (
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

    By its address on Discover Bank's own host. The account menu discovery
    reads is the one on this page, and any page of the site holds a button
    of the menu's kind, a dashboard's transfer widget among them, so one
    on the page is no sign of the statements page.
    """
    try:
        if looks_public_or_error(page) or looks_signed_out(page):
            return False
        parts = urlsplit(page.url or "")
        return (parts.scheme == "https" and parts.hostname == "bank.discover.com"
                and parts.path.lower().startswith("/web/deposits/documents"))
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


# Where a statement's list and its PDF live, for one account. The account
# is the id the statements page's own account menu holds for it, and each
# PDF the list names sits under that same account's path.
STATEMENTS_PATH = "/bank/deposits/servicing/documents/v1/accounts/%s/statements"
# What an account id may be made of. One that holds anything else is not
# put into a path, since a slash or a question mark in it would ask another
# address on the site than this account's list.
ACCOUNT_ID_RE = re.compile(r"[A-Za-z0-9~._-]{1,128}")
# A statement's PDF, as the list names it, and the account it belongs to.
BINARY_PATH_RE = re.compile(
    r"/bank/deposits/servicing/documents/v1/accounts/([A-Za-z0-9~._-]{1,128})"
    r"/statements/[A-Za-z0-9~._-]{1,256}")

# The kind of account a statement is, from the account's own name on the
# menu. Each word stands alone, so "Discover" or "card" never reads as one.
_LABEL_KINDS = (
    ("Checking", re.compile(r"\bchecking\b", re.I)),
    ("Savings", re.compile(r"\bsavings\b", re.I)),
    ("Money Market", re.compile(r"\bmoney\s*market\b", re.I)),
    ("CD", re.compile(r"\bcd\b|\bcertificates?\s+of\s+deposit\b", re.I)),
)
# The product code inside an account id, measured on a live account. ~OC~
# is a checking account and ~OSA~ an online savings account. Nothing else
# has been seen, so nothing else is read from an id.
_ID_KINDS = (("Checking", "~oc~"), ("Savings", "~osa~"))


def kind_of_label(label: str) -> str:
    """Checking, Savings, Money Market or CD, from an account's name, or ""
    when it names none or more than one."""
    found = {kind for kind, rx in _LABEL_KINDS if rx.search(label or "")}
    return found.pop() if len(found) == 1 else ""


def kind_of_id(account_id: str) -> str:
    """Checking or Savings, from the product code in an account id, or ""
    when it holds none or both."""
    low = (account_id or "").lower()
    found = {kind for kind, marker in _ID_KINDS if marker in low}
    return found.pop() if len(found) == 1 else ""


def statements_url(account_id: str) -> Optional[str]:
    """The address of one account's statement list, or None for an id that
    is not shaped like one."""
    if not ACCOUNT_ID_RE.fullmatch(account_id or ""):
        return None
    return BASE + STATEMENTS_PATH % account_id


def account_of_href(href: str) -> str:
    """The account id a statement's PDF address sits under, or "" for an
    address that is not a statement PDF on Discover Bank's own host."""
    if not is_safe_url(href or "") or urlsplit(href).hostname != "bank.discover.com":
        return ""
    m = BINARY_PATH_RE.fullmatch(urlsplit(href).path or "")
    return m.group(1) if m else ""


def parse_statements_api(json_data, account_label: str, account_id: str = "") -> "Listed":
    """The statements one account's list names, each with its PDF's own
    address, its date and its kind.

    A statement is kept only when its PDF sits under the account it was
    listed for, its date is a real day, and the account's name and the
    product code in its id agree on its kind. Any other is refused and the
    list it came in is not whole (passed_over), so it is never filed under
    another account, a made up date or the wrong kind, and the run says so.
    """
    refused = 0
    docs: List[RawDoc] = []
    if not isinstance(json_data, list):
        return _listed(docs, ("statement list",))
    label = re.sub(r"\s+", " ", account_label or "").strip()
    for i, item in enumerate(json_data):
        if not isinstance(item, dict):
            refused += 1
            continue
        raw_date = str(item.get("statementDate") or "")
        stmt_date = raw_date[:10] if re.match(r"\d{4}-\d{2}-\d{2}(?!\d)", raw_date) else ""
        stmt_date = _checked_date(stmt_date, "")
        name = item.get("name", "")
        name = name if isinstance(name, str) else ""
        binary_href = ""
        links = item.get("links")
        for link in links if isinstance(links, list) else ():
            if isinstance(link, dict) and link.get("rel") == "binary":
                binary_href = link.get("href") or ""
                break
        if not isinstance(binary_href, str):
            binary_href = ""
        if binary_href.startswith("/"):
            binary_href = urljoin(BASE, binary_href)
        owner = account_of_href(binary_href)
        if not owner or not stmt_date or (account_id and owner != account_id):
            log.warning("refusing a statement on the list (%s), since its PDF is not "
                        "this account's or it has no date", name[:40] or i)
            refused += 1
            continue
        by_label, by_id = kind_of_label(label), kind_of_id(owner)
        if by_label and by_id and by_label != by_id:
            log.warning("refusing a statement on the list (%s), since the account is "
                        "named %s and its id says %s", name[:40] or i, by_label, by_id)
            refused += 1
            continue
        kind = by_label or by_id
        docs.append(
            RawDoc(
                title=f"{kind} Statement" if kind else "Statement",
                date_text=stmt_date,
                href=binary_href,
                text=name,
                account=label or kind,
                row_index=i,
            )
        )
    return _listed(docs, ("statement list",) if refused else ())


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
    """Rows currently rendered. Used by --diagnose only, to show a layout
    change. Discovery never files a document from them."""
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


_STATEMENTS_FETCH_JS = """async (url) => {
  const ppTarget = new URL(url, location.href);
  if (ppTarget.protocol !== "https:" || ppTarget.hostname !== "bank.discover.com" || ppTarget.username || ppTarget.password || (ppTarget.port && ppTarget.port !== "443")) throw new Error("Refusing an off-host document request");
  const res = await fetch(url, { credentials: 'include' });
  if (!res.ok) return { ok: false, status: res.status, data: null };
  return { ok: true, status: res.status, data: await res.json() };
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


# The account menu on the statements page is a React button whose props
# hold every account, each with its name and the id its statement list is
# asked by. Read from the page's own state, nothing is pressed. Every such
# button on the page is read, and the menu is the one whose options are
# deposit accounts.
_ACCOUNT_MENUS_JS = """() => {
  const menus = [];
  for (const btn of document.querySelectorAll("button[class*='_dropdown_']")) {
    const key = Object.keys(btn).find(k => k.startsWith("__reactFiber"));
    if (!key) continue;
    let curr = btn[key];
    for (let i = 0; curr && i < 40; i++, curr = curr.return) {
      const props = curr.memoizedProps;
      if (props && Array.isArray(props.options)) {
        menus.push(props.options.map(o => ({
          label: String((o && o.label) || ''),
          id: String((o && (o.id || o.value)) || '')
        })));
        break;
      }
    }
  }
  return menus;
}"""

# The list calls the statements page made itself, read from the browser's
# own record of them. Nothing is pressed and nothing is guessed.
_LIST_CALLS_JS = """() => Array.from(new Set(
  performance.getEntriesByType('resource').map(r => r.name)
    .filter(u => u.startsWith('https://bank.discover.com/bank/deposits/servicing/documents/v1/accounts/'))
))"""


ACCOUNT, OTHER, REFUSED = "account", "other", "refused"


def option_is(opt: dict) -> str:
    """What a menu option is. ACCOUNT, a deposit account to read. OTHER, no
    account of this app's, a card or a loan, or an entry with no id that
    names no kind of account ("All accounts") or names an action ("Open an
    account"). REFUSED, one that may be an account and is not read, an
    account with no id or one whose name says an action, so the list is not
    whole without it. A certificate of deposit is not an action for the
    word deposit."""
    label, has_id = opt.get("label", ""), bool(opt.get("id"))
    if PRODUCT_PICKER_RE.search(label):
        return OTHER
    action = FORBIDDEN_CONTROL_RE.search(
        re.sub(r"\bcertificates?\s+of\s+deposit\b", " ", label, flags=re.I))
    if not has_id:
        return REFUSED if kind_of_label(label) and not action else OTHER
    return REFUSED if action else ACCOUNT


def read_account_menu(page) -> Optional[List[dict]]:
    """[{label, id, refused}] for every account on the statements page's
    account menu, or None when no menu of accounts can be read. An option
    that is no account of this app's is left out, and one that may be an
    account and is not read comes with refused True (option_is).

    Read from the page's state and never by opening the menu. Choosing an
    account on it is a press nobody has shown to be read-only, so it is
    never done. Options that are no deposit account are left out. A menu
    is the one whose options name a kind of deposit account, and when two
    menus on the page do and hold different accounts, which is the list is
    not known, so None.
    """
    try:
        menus = page.evaluate(_ACCOUNT_MENUS_JS)
    except Exception as e:
        log.warning("Could not read the account menu (%s)", e)
        return None
    found = []
    for menu in menus if isinstance(menus, list) else ():
        opts = [{"label": re.sub(r"\s+", " ", str(o.get("label") or "")).strip(),
                 "id": str(o.get("id") or "").strip()}
                for o in menu if isinstance(o, dict)] if isinstance(menu, list) else []
        if any(kind_of_label(o["label"]) for o in opts):
            accounts = [dict(o, refused=option_is(o) == REFUSED) for o in opts
                        if option_is(o) != OTHER]
            if accounts and accounts not in found:
                found.append(accounts)
    if len(found) != 1:
        if found:
            log.warning("Two account menus on the page hold different accounts")
        return None
    return found[0]


def list_deposit_accounts(page) -> List[dict]:
    """[{index, text, id}] for every account the menu holds, read from the
    page's state, or [] when none can be read. Nothing is pressed."""
    accounts = [a for a in read_account_menu(page) or () if not a["refused"]]
    return [{"index": i, "text": a["label"], "id": a["id"]}
            for i, a in enumerate(accounts)]


def _read_list(page, url: str):
    """One account's statement list as the site answers it, or None when it
    did not answer one."""
    try:
        got = intake.evaluate(page, _STATEMENTS_FETCH_JS, url)
    except Exception as e:
        log.warning("The statement list call failed (%s)", str(e).splitlines()[0][:120])
        return None
    if not isinstance(got, dict) or not got.get("ok"):
        log.warning("The statement list call answered %s",
                    got.get("status") if isinstance(got, dict) else "nothing")
        return None
    data = got.get("data")
    return data if isinstance(data, list) else None


def discoverbank_collect(page) -> Optional[Listed]:
    """Every statement Discover Bank lists, for every account the statements
    page's account menu holds, or None when there is no list to read.

    Each account's list is the page's own call, asked from inside the page
    with the account's id from the menu. An account whose list did not
    answer, whose id is not shaped like one, or that is named the same as
    another, and a statement the list names that cannot be told apart
    (parse_statements_api), make the list not whole (passed_over). What was
    read is kept, and the run stops at its end rather than finish.

    With no menu to read, the calls the page made for itself are read, one
    account at most and never as the whole list, since how many accounts
    there are is then not known. Nothing on the page is pressed either way.
    """
    accounts = read_account_menu(page)
    docs: List[RawDoc] = []
    passed_over = set()
    seen = set()

    def take(listed):
        passed_over.update(getattr(listed, "passed_over", ()))
        for d in listed:
            if d.href not in seen:
                seen.add(d.href)
                docs.append(d)

    if accounts:
        log.info("Discovered %d account(s) on the account menu", len(accounts))
        labels = [a["label"] for a in accounts]
        for acct in accounts:
            url = statements_url(acct["id"])
            if (acct["refused"] or not url or not acct["label"]
                    or labels.count(acct["label"]) > 1):
                log.warning("passing over an account on the menu that has no usable "
                            "id, a name that says an action, or a name another "
                            "account has")
                passed_over.add("account menu")
                continue
            data = _read_list(page, url)
            if data is None:
                passed_over.add("statement list")
                continue
            take(parse_statements_api(data, acct["label"], acct["id"]))
        return _listed(docs, passed_over)

    # No menu could be read. The page's own calls, when it made exactly one.
    try:
        calls = page.evaluate(_LIST_CALLS_JS)
    except Exception as e:
        log.warning("Could not read the page's own calls (%s)", e)
        calls = []
    lists = sorted({u.split("?")[0] for u in calls if isinstance(u, str)
                    and re.fullmatch(r"https://bank\.discover\.com" + STATEMENTS_PATH
                                     % r"[A-Za-z0-9~._-]{1,128}", u.split("?")[0])})
    if len(lists) != 1:
        if lists:
            log.warning("The page asked %d statement lists and holds no account menu "
                        "to name them by", len(lists))
        return None
    account_id = lists[0].rsplit("/", 2)[-2]
    data = _read_list(page, lists[0])
    if data is None:
        return None
    take(parse_statements_api(data, "", account_id))
    passed_over.add("account menu")
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

    if not is_safe_url(href) or not account_of_href(href):
        log.warning("Refusing to download from a URL that is no statement PDF: %s", href)
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


_DIGITS_RE = re.compile(r"\d{4,}")


def _redact(value):
    """Mask long digit runs (account/document numbers) but keep the shape."""
    if isinstance(value, str):
        return _DIGITS_RE.sub(lambda m: m.group(0)[:2] + "…" + m.group(0)[-2:], value)
    return value


def probe_statements_api(page) -> dict:
    """Report the statement lists exactly as discovery reads them.

    How many accounts the account menu holds and of what kind, how many
    statements each list names, their date range, the shape of a PDF's
    address, and what was passed over. Discovery reads the same lists and
    nothing more, so this is the thing to compare after a redesign.

    Read-only, and it neither clicks nor navigates past the statements page.
    """
    try:
        ensure_statements(page)
        page.wait_for_timeout(1200)
    except Exception as e:
        log.info("probe_statements_api: %s", e)
    accounts = read_account_menu(page)
    listed = discoverbank_collect(page)
    dates = sorted(d.date_text for d in listed or () if d.date_text)
    per_account = {}
    for d in listed or ():
        per_account[d.title] = per_account.get(d.title, 0) + 1
    return {
        "account_menu_read": accounts is not None,
        "accounts": len(accounts or ()),
        "account_kinds": sorted({kind_of_label(a["label"]) or kind_of_id(a["id"]) or "?"
                                 for a in accounts or ()}),
        "accounts_passed_over": len([a for a in accounts or () if a["refused"]]),
        "statements": len(listed) if listed is not None else 0,
        "statements_by_kind": per_account,
        "oldest": dates[0] if dates else "",
        "newest": dates[-1] if dates else "",
        "passed_over": list(getattr(listed, "passed_over", ())) if listed is not None
                       else ["the whole list"],
        "href_shape": _redact(listed[0].href) if listed else "",
    }


def probe_api(page, seconds: int = 25) -> List[dict]:
    """Watch the SPA's JSON traffic while the statements area loads, and
    report endpoints whose payload looks like a document list. Listen only,
    nothing on the page is chosen or pressed."""
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
        scroll_full_page(page, rounds=4)
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
