"""ALL Marcus by Goldman Sachs selectors, URLs, and page behavior live here.
When the site changes, repair this file only.

SAFETY (this is a savings account):
  This module is strictly READ-ONLY. It opens the Documents page, reads the
  list of account statements, and downloads the statement PDFs Marcus already
  generated. It must NEVER activate any control that moves money, links a
  bank, opens or closes an account, or changes any setting.
  FORBIDDEN_CONTROL_RE is the guard; a control must ALSO look like a document
  action (SAFE_DOC_CONTROL_RE) before it may be clicked. There is no code
  here that submits a form or confirms a dialog.

Mechanism (verified 2026-11 against the live signed-in site):
  Documents live at BASE/us/en/documents under two tabs, "Account
  Statements" and "Tax Forms". This app reads the first. Its panel holds one
  table (role=grid), a row a statement: the masked account, the product
  ("Online Savings") and the statement's date (MM/DD/YYYY) as a link. A year
  picker above the table reloads it for that year. The link is the PDF's own
  address on www.marcus.com and pressing it fires a real browser download
  event. The session is a server-side cookie and survives page.goto, so
  navigation is by URL.
"""
# Site layer verified working against the live site: 2026-11
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

from paperpull_core.delivery import DOWNLOAD, DocumentRequest
from paperpull_core.identity import Identity
from paperpull_core.dates import last_day as _last_day
from paperpull_core.dates import human_date as _human_date
from paperpull_core.dates import checked as _checked_date

log = logging.getLogger("marcus_docs.site")

BASE = "https://www.marcus.com"
DOCUMENTS_URL = f"{BASE}/us/en/documents"
URLS = {
    "home": f"{BASE}/us/en/dashboard",
    "login": f"{BASE}/us/en/login",
    "dashboard": f"{BASE}/us/en/dashboard",
    "statements": DOCUMENTS_URL,
    "documents": DOCUMENTS_URL,
}

LOGIN_URL_MARKERS = ["/login", "/logon", "/signin", "/sign-in",
                     "/mfa", "/verification", "/challenge"]

# ---------------------------------------------------------------------------
# HARD SAFETY GUARD - never click anything matching this. Tuned for a savings
# bank: never move money, link a bank, open or close an account, or change
# the account. (The year picker is pressed by its own selectors and a 4-digit
# label, not routed through this guard.)
# ---------------------------------------------------------------------------
FORBIDDEN_CONTROL_RE = re.compile(
    r"(pay\b|payment|autopay|auto\s*pay|"
    r"transfer|withdraw|deposit|move\s+money|add\s+money|add\s+funds|"
    r"\bsend\b|\bwire\b|\bfund(s|ed|ing)?\b|"
    r"redeem|reward|bonus|refer\b|referral|renew|roll\s*over|"
    r"routing|account\s+number|link\s+(a\s+|an\s+)?(bank|account)|"
    r"external\s+account|beneficiar|joint\s+owner|"
    r"\bapply\b|enroll|unenroll|sign\s+up|paperless|delivery\s+options|"
    r"upgrade|get\s+started|new\s+account|dispute|freeze|"
    # A verb reaching the noun, rather than the noun on its own. "Account"
    # by itself is what the DOCUMENT is called here ("Account Statements"),
    # and the verb is what makes it dangerous.
    r"(add|manage|open|close|link|unlink|remove|delete|rename|lock|unlock|"
    r"set\s*up|break|withdraw\s+from)\b[\w'\s-]{0,24}\b(account|bank|cd)s?\b|"
    r"(account|bank)s?\b[\w'\s]{0,12}\b(settings?|services?|preferences?|details)\b|"
    r"enable|disable|activate|deactivate|"
    # Anchored on both sides. "edit" unanchored matches the end of "Credit".
    r"\bchang(e|es|ed|ing)\b|\bedit(s|ed|ing)?\b|\bupdat(e|es|ed|ing)\b|"
    r"modify|set\s+up|delete|remove|cancel|"
    r"password|profile\b|settings|preferences|\bmanage\b|"
    r"confirm|continue|submit|agree|accept|authorize)", re.I)

# A statement's download link carries no word at all on this site, only the
# statement's date, so a label that is a date and nothing else is a document
# control here. The row it is in and the link's own address are checked as
# well before it is pressed (statement_request).
DATE_LABEL_RE = re.compile(r"^\s*\d{1,2}/\d{1,2}/\d{4}\s*$")

SAFE_DOC_CONTROL_RE = re.compile(
    r"(download|view|open|print|pdf|statement|document|tax\s+form|"
    r"^\s*\d{1,2}/\d{1,2}/\d{4}\s*$)", re.I)

SECURITY_CHALLENGE_MARKERS = [
    "enter the code", "verification code", "6-digit", "one-time passcode",
    "one time passcode", "two-factor", "two-step", "authenticator",
    "confirm your identity", "verify your identity", "we sent a code",
    "security code", "unusual", "are you a robot", "captcha", "let's verify",
    "check your email", "check your phone", "your session has expired",
    "session has timed out", "log back in", "sign back in",
]

RATE_LIMIT_MARKERS = [
    "too many requests", "rate limit", "try again later",
    "temporarily unavailable", "http error 429", "unusual traffic",
]

# ---------------------------------------------------------------------------
# Selectors
# ---------------------------------------------------------------------------
STATEMENTS_TAB_SEL = "[data-testid='statements_statements']"
# The Account Statements panel and no other, so a Tax Forms panel left in
# the page is never read as statements.
PANEL_SEL = "[role='tabpanel'][data-testid='statements_statements_tab']"
ROW_SEL = f"{PANEL_SEL} table[role='grid'] tr[role='row']"
DOWNLOAD_LINK_SEL = "a[data-testid^='download_']"

# Fallback selectors (used by --diagnose only)
FALLBACK = {
    "doc_row": ROW_SEL,
    "doc_link": DOWNLOAD_LINK_SEL,
    "download_control": DOWNLOAD_LINK_SEL,
    "page_ready": f"{STATEMENTS_TAB_SEL}, {PANEL_SEL}",
    "next_page": ("a[aria-label*='Next' i], button[aria-label*='Next' i]"),
}

# ---------------------------------------------------------------------------
# Date parsing (shared with the other projects)
# ---------------------------------------------------------------------------
DATE_PATTERNS = [
    (re.compile(r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
                r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|"
                r"Dec(?:ember)?)\.?\s+(\d{1,2}),?\s+(\d{4})", re.I), "mdY"),
    (re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b"), "mdy_slash"),
    (re.compile(r"\b(\d{1,2})-(\d{1,2})-(\d{4})\b"), "mdy_dash"),
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
YEAR_ONLY_RE = re.compile(r"^20\d\d$")
_MDY_SLASH_RE = re.compile(r"^\s*(\d{1,2})/(\d{1,2})/(\d{4})\s*$")
_LAST_DIGITS_RE = re.compile(r"(\d{2,6})\s*$")


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
            if kind in ("mdy_dash", "mdy_slash"):
                return f"{int(m.group(3)):04d}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
            if kind == "iso":
                return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        except (KeyError, ValueError):
            continue
    return None


def parse_date(text):
    """The date this provider's page is showing, as YYYY-MM-DD, and nothing
    for a day that does not exist."""
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


def _iso_from_label(text: str) -> Optional[str]:
    """'MM/DD/YYYY', all a statement's link says, as 'YYYY-MM-DD'. Nothing
    for a label that says anything more, or a day that does not exist."""
    m = _MDY_SLASH_RE.match(text or "")
    if not m:
        return None
    return _checked_date(
        f"{int(m.group(3)):04d}-{int(m.group(1)):02d}-{int(m.group(2)):02d}", None)


def account_label(cell: str) -> str:
    """'****1234', the way the page masks an account, as 'x1234'. An
    asterisk cannot be in a file name, and the digits are what tell two
    accounts apart."""
    m = _LAST_DIGITS_RE.search(cell or "")
    return f"x{m.group(1)}" if m else ""


def _account_digits(account: str) -> str:
    m = _LAST_DIGITS_RE.search(account or "")
    return m.group(1) if m else ""


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


def _list_shows(page) -> bool:
    """Whether the Account Statements tab is the one open, with its panel.
    Only a signed-in Documents page draws either. A year with no statement
    has no row, so rows are not what this asks for."""
    try:
        tab = page.locator(STATEMENTS_TAB_SEL)
        if tab.count() != 1:
            return False
        if (tab.first.get_attribute("aria-selected") or "").lower() != "true":
            return False
        return page.locator(PANEL_SEL).count() > 0
    except Exception:
        return False


def detect_security_challenge(page) -> Optional[str]:
    if _list_shows(page):
        return None
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
    # The shared core guard is consulted as well as this app's own blocklist.
    try:
        from paperpull_core.controls import SETTINGS_CONTROL_RE, AUTH_CONTROL_RE
        if SETTINGS_CONTROL_RE.search(name) or AUTH_CONTROL_RE.search(name):
            return False
    except Exception:
        pass
    return bool(SAFE_DOC_CONTROL_RE.search(name))


# ---------------------------------------------------------------------------
# Documents page
# ---------------------------------------------------------------------------

def _on_documents(page) -> bool:
    return (page.url or "").split("?")[0].rstrip("/").endswith("/documents")


def goto_documents(page) -> bool:
    """Open the Documents page and confirm the Account Statements tab is
    the one showing. The session survives a hard navigation, so page.goto is
    safe here, and it is also how the page is put back on that tab when the
    person left it on Tax Forms."""
    try:
        if not _on_documents(page) or not _list_shows(page):
            page.goto(DOCUMENTS_URL, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(2500)
        if looks_signed_out(page):
            return False
        try:
            page.wait_for_selector(STATEMENTS_TAB_SEL, timeout=15000)
        except Exception:
            pass
        _wait_for_rows(page)
        return _list_shows(page)
    except Exception as e:
        log.info("goto_documents failed: %s", type(e).__name__)
        return _list_shows(page)


def _wait_for_rows(page, ms: int = 6000) -> None:
    """Give the table the time it takes to draw. A year with no statement
    never draws a row, so this waits and does not insist."""
    try:
        page.wait_for_selector(ROW_SEL, timeout=ms)
    except Exception:
        pass
    try:
        page.wait_for_timeout(400)
    except Exception:
        pass


def scroll_full_page(page, rounds: int = 6, delay_ms: int = 500) -> None:
    try:
        for _ in range(rounds):
            page.mouse.wheel(0, 3000)
            page.wait_for_timeout(delay_ms)
        page.keyboard.press("End")
        page.wait_for_timeout(delay_ms)
    except Exception:
        pass


def expand_all(page) -> None:
    """No lazy 'show more' on this table (it is split by year, handled in
    collect_download_docs). Kept for the shared --diagnose path."""
    return None


@dataclass
class Row:
    """One row of the statements table, as the page draws it."""
    index: int
    account: str      # 'x1234'
    product: str      # 'Online Savings'
    date: str         # ISO, or '' for a row whose link is not a date
    label: str        # the link's own words
    href: str
    links: int        # download links in the row


_ROWS_JS = """(sel) => [...document.querySelectorAll(sel.row)].map(tr => {
    const flat = (el) => (el.innerText || '').replace(/\\s+/g, ' ').trim();
    const links = [...tr.querySelectorAll(sel.link)];
    return {cells: [...tr.querySelectorAll('td')].map(flat),
            links: links.length,
            label: links.length ? flat(links[0]) : '',
            href: links.length ? (links[0].href || '') : ''};
})"""


def _rows(page) -> List[Row]:
    """The statements table currently shown (one year)."""
    try:
        raw = page.evaluate(_ROWS_JS, {"row": ROW_SEL, "link": DOWNLOAD_LINK_SEL})
    except Exception:
        raw = []
    out = []
    for i, r in enumerate(raw or []):
        cells = list(r.get("cells") or [])
        if len(cells) < 3:
            continue
        label = (r.get("label") or "").strip()
        out.append(Row(index=i, account=account_label(cells[0]),
                       product=cells[1].strip(),
                       date=_iso_from_label(label) or "", label=label,
                       href=r.get("href") or "", links=int(r.get("links") or 0)))
    return out


def _row_dates(page) -> List[str]:
    return [r.date for r in _rows(page) if r.date]


# -- the year picker ---------------------------------------------------------
#
# "Date Range", a widget of the site's own and not a <select> a script can
# set. Its input shows the year the table is for, pressing it opens a
# listbox of the years there are, and pressing one reloads the table. The
# <select> inside it is a helper that holds the chosen year and no other.
YEAR_PICKER_SEL = "[data-testid='statements_selectStatementDate_drop_down']"
YEAR_OPENER_SEL = f"{YEAR_PICKER_SEL} input[aria-controls='selectStatementDate-listbox']"
YEAR_OPTION_SEL = "#selectStatementDate-listbox [role='option']"
YEAR_SHOWN_SEL = f"{YEAR_OPTION_SEL}[aria-selected='true']"


# What the panel says in place of the table for a year with no statement.
EMPTY_NOTICE_RE = re.compile(r"no documents found", re.I)


def _says_empty(page) -> bool:
    """Whether the panel says the year on show has no documents. A table
    still loading draws no row either, and says nothing."""
    try:
        text = page.locator(PANEL_SEL).first.inner_text(timeout=1500)
    except Exception:
        return False
    return bool(EMPTY_NOTICE_RE.search(text or ""))


def _shown_year(page) -> str:
    """The year the picker says the table is for."""
    try:
        text = page.evaluate(
            "(sel) => { const el = document.querySelectorAll(sel);"
            " return el.length === 1 ? (el[0].textContent || '') : ''; }",
            YEAR_SHOWN_SEL)
    except Exception:
        text = ""
    m = re.search(r"\b20\d\d\b", text or "")
    return m.group(0) if m else ""


def _year_options(page) -> List[str]:
    """Every year the picker offers, newest first."""
    try:
        texts = page.evaluate(
            "(sel) => [...document.querySelectorAll(sel)]"
            ".map(el => (el.textContent || '').trim())", YEAR_OPTION_SEL)
    except Exception:
        texts = []
    return sorted({t for t in texts or [] if YEAR_ONLY_RE.match(t)}, reverse=True)


def _select_year(page, year: str) -> bool:
    """Show `year` in the table. True once the picker says that year and
    the table holds rows all dated in it, or the panel says the year has
    no documents. A table with no row and no such notice is still loading.

    The picker says the new year as soon as it is pressed, while the panel
    still holds what the year before it showed. So a notice of no documents
    counts only once what the panel held before the press has gone, or the
    notice has stayed for three seconds, which is one empty year after
    another when the site keeps the notice it already drew."""
    if not YEAR_ONLY_RE.match(year or ""):
        return False
    if _shown_year(page) == year:
        return True
    try:
        opener = page.locator(YEAR_OPENER_SEL).first
        opener.scroll_into_view_if_needed(timeout=3000)
        opener.click(timeout=8000)
        option = page.locator(YEAR_OPTION_SEL).filter(
            has_text=re.compile(rf"^\s*{year}\s*$"))
        if option.count() != 1:
            log.info("the year picker does not offer %s once", year)
            page.keyboard.press("Escape")
            return False
        before = page.query_selector(f"{PANEL_SEL} > *")
        option.first.click(timeout=8000)
        stayed = 0
        for _ in range(48):                    # up to ~12s for the table to swap
            page.wait_for_timeout(250)
            if _shown_year(page) != year:
                continue
            dates = _row_dates(page)
            if dates and all(d.startswith(year) for d in dates):
                return True
            if dates or not _says_empty(page):
                stayed = 0
                continue
            stayed += 1
            if _gone(before) or stayed >= 12:
                return True
        return False
    except Exception as e:
        log.info("year %s could not be selected: %s", year, type(e).__name__)
        return False


def _gone(handle) -> bool:
    """Whether what the panel held before a press is no longer in the page."""
    if handle is None:
        return True
    try:
        return not handle.evaluate("e => e.isConnected")
    except Exception:
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


def _raw(row: Row) -> RawDoc:
    disp = _human_date(row.date)
    product = row.product or "Account"
    # The link's address is not kept. It carries the account's own
    # identifier, and the row is found again by its account and date.
    return RawDoc(title=f"{product} Statement", account=row.account,
                  date_text=row.date, href="",
                  text=f"Marcus {product} statement {disp}",
                  row_index=row.index, kind="statement")


class ListStopped(Exception):
    """The list has a part this could not read, a year the picker offers
    and the table would not show, so what was read is not all of it. `docs`
    holds what was read before it stopped. Its words are this module's own,
    never the page's."""

    def __init__(self, why: str, docs=None):
        super().__init__(why)
        self.docs = list(docs or [])


def collect_download_docs(page, keep=None) -> List[RawDoc]:
    """Read every account statement across all available years. The table
    shows one year at a time; harvest the year on show, then select each
    other year and harvest again."""
    if not _on_documents(page) or not _list_shows(page):
        goto_documents(page)
    docs: List[RawDoc] = []
    seen = set()

    def harvest():
        for row in _rows(page):
            if not row.date:
                continue
            if not row.account:
                # Two accounts' statements of one day differ by nothing else.
                raise ListStopped("a statement's row names no account", docs)
            if (row.date, row.account) in seen:
                continue
            seen.add((row.date, row.account))
            docs.append(_raw(row))

    harvest()                                  # the year on show costs nothing
    shown = _shown_year(page)
    offered = _year_options(page)
    if not shown or shown not in offered:
        # With no picker read, only the year on show would be listed, and
        # that is not the whole list.
        raise ListStopped("the year picker could not be read", docs)
    years = [y for y in offered if y != shown]
    if keep is not None:
        wanted = [y for y in years if keep(y)]
        if len(wanted) < len(years):
            log.info("Marcus: skipping %d year(s) outside the run's scope",
                     len(years) - len(wanted))
        years = wanted
    for year in years:
        if not _select_year(page, year):
            raise ListStopped("the statements of a year the picker offers "
                              "did not show", docs)
        harvest()
    return docs


def identity_for(doc) -> Identity:
    """What a statement's row carries that its file can be checked
    against, which is nothing. The row is dated the day after the period
    the statement prints (a row of 11/01 holds "Statement Period 10/01 to
    10/31"), so its date is nowhere in its own file and is in the next
    month's, as that one's first day. Checking against it would refuse
    every statement. An Identity with no fact says so and reads as
    unchecked."""
    return Identity()


def statement_request(page, iso_date: str, account: str = "") -> Optional[DocumentRequest]:
    """Everything up to the click, for the statement of `account` dated
    `iso_date`.

    Reach the Documents page, pick that statement's year, find its one row
    and check the row's link. Then stop, and hand the click to
    delivery.deliver.

    None when the page cannot be reached, the row is not there or is there
    twice, or the link is one this app will not press. The caller tells
    those apart by asking looks_signed_out."""
    if not _on_documents(page) or not _list_shows(page):
        if not goto_documents(page):
            return None
    if looks_signed_out(page):
        return None

    year = (iso_date or "")[:4]
    if year and not any(d.startswith(year) for d in _row_dates(page)):
        if not _select_year(page, year):
            log.info("could not select year %s for %s", year, iso_date)
            return None

    want = _account_digits(account)
    found = [r for r in _rows(page) if r.date == iso_date
             and (not want or _account_digits(r.account) == want)]
    if len(found) != 1:
        log.info("%d rows for the statement of %s, where one was wanted",
                 len(found), iso_date)
        return None
    row = found[0]

    # Safety. The link's own words, read off the page, are what the guard
    # judges, and they are a date and nothing else. The row must hold that
    # one link and no other, and the address it leads to must be Marcus's.
    if row.links != 1:
        log.error("refusing a row that holds %d download links", row.links)
        return None
    if not DATE_LABEL_RE.match(row.label) or not is_safe_control(row.label):
        log.error("refusing a control labeled %r", row.label[:60])
        return None
    if not is_safe_url(row.href):
        log.error("refusing a statement link that leaves Marcus")
        return None

    tr = page.locator(ROW_SEL).nth(row.index)
    link = tr.locator(DOWNLOAD_LINK_SEL)

    def press():
        # Read again at the press. A table drawn again since the row was
        # chosen can hold another statement in the same place, and two
        # accounts' statements of one day carry the same label, so the
        # account and the link's own address are read again as well.
        now = (link.inner_text(timeout=1500) or "").strip()
        account = account_label(tr.locator("td").first.inner_text(timeout=1500))
        href = link.evaluate("e => e.href")
        if (now, account, href) != (row.label, row.account, row.href):
            raise RuntimeError("the row no longer holds this statement's link")
        link.click(timeout=8000)

    try:
        link.scroll_into_view_if_needed(timeout=4000)
    except Exception:
        pass
    return DocumentRequest(trigger=press,
                           expect=Identity(),
                           close_new_tabs=True,
                           hints=(DOWNLOAD,))


# ---------------------------------------------------------------------------
# Diagnose-only helper (the rows on show; no year is selected, no downloads)
# ---------------------------------------------------------------------------
def collect_documents(page) -> List[RawDoc]:
    return [_raw(r) for r in _rows(page) if r.date]


# ---------------------------------------------------------------------------
# Host allowlist. Parsed, never a string prefix, so a lookalike host cannot
# walk through.
# ---------------------------------------------------------------------------
ALLOWED_HOSTS = {'marcus.com'}


def is_safe_url(url: str) -> bool:
    """True only for an https URL on one of this provider's own hosts.

    The check itself lives in the core, so all of them answer the same way.
    This app keeps the hosts, which is the part that really is its own."""
    from paperpull_core.urls import is_safe_url as _host_allows
    return _host_allows(url, ALLOWED_HOSTS)
