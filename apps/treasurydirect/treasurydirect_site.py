"""ALL treasurydirect.gov selectors, URLs, and page behavior live here.

When TreasuryDirect changes its site, repair this file only.

STATUS: surveyed read-only on 2026-10-13 by clicking the pages' own links,
and run live on that one account (Discover 3, Pilot 1, Run All 2, every PDF
opened). That account had no taxable transactions, so the tax pages were
never seen: a taxable year is listed but its link is never pressed (SURVEY
NEEDED, below).

What TreasuryDirect is, as surveyed:

  * Every signed-in page is one address, /RS/RSGatewayRW on
    www.treasurydirect.gov, with the page named by its query:
    UIHandler=<handler>&primary=true&processID=<n>&uiFrom=<handler>. The
    processID is a per-session token. Opening one of these addresses
    directly (page.goto) ended the session ("TreasuryDirect is
    unavailable.") during the survey, and the site itself says the browser's
    Back, Forward and Refresh end it. So this app NEVER opens an address and
    never asks for one with the session's cookies. It moves only by pressing
    the page's own links, in the person's own tab, one at a time, through
    paperpull_core.pressing.
  * There are no PDFs. Every document is a server-drawn HTML page, taken
    from the tab (page.content()) and rendered to a PDF inertly through
    paperpull_core.receipt_pdf.print_html_inert_to_pdf: scripts, forms and
    frames stripped, drawn in a fresh context with JavaScript off, no
    cookies and no network.
  * Sign-in is TreasuryDirect's own (and ID.me, through caia.treasury.gov).
    The app never sees it: a sign-in page, the caia.treasury.gov address,
    or "TreasuryDirect is unavailable." is SessionExpired; a passcode or
    security question is OtpRequired; a tab that is not a signed-in page
    with the top tabs is NotLive. Each stops the run for the account holder.

What is saved:

  * Current Holdings (ch.DisplayCurrentHoldings), the summary page only.
    Its per-type detail is behind a radio button and Submit, a form post,
    which is never made.
  * Security History (sechist.DisplaySecurityHistory) and Payment History
    (payhist.DisplayPaymentHistorySummary), reached from History
    (hist.DisplayHistory), as they first show. Their own forms are never
    submitted.
  * Not saved, but listed: each taxable year's 1099, from ManageDirect's
    Manage My Taxes list. A year with nothing taxable is plain text, "Year
    2025 (No taxable transactions)", and has nothing to save (CONFIRMED). A
    taxable year is assumed to be a link "Year 2025"; it is recorded for
    manual review and never pressed, since its page is unsurveyed.

The three account pages are snapshots, dated the day they are taken, one per
day. A 1099 is dated its tax year's December 31. A saved
PDF counts only when its own text names the document (pdf_names_document).

SAFETY (an account that can buy, redeem, transfer and approve transfers):
  This module is strictly READ-ONLY. It never opens an address, never
  submits a form, fills nothing, and presses only links whose visible label
  AND exact handler are on the allowlists below (TAB_LINKS, HISTORY_LINKS),
  that lead to the signed-in address on www.treasurydirect.gov, each checked
  against FORBIDDEN_CONTROL_RE, the shared core guards and
  FORBIDDEN_HANDLER_RE first. BuyDirect, Gift
  Box, Logoff, Return To Account Listing, every ManageDirect link that
  changes the account (password, security questions, bank, registration,
  personal information, reinvestments, transfers, redemptions, rights,
  linked accounts), the transfer to myTreasury approval ("here"), the
  Investor InBox (opening a message marks it read) and every Submit,
  Cancel and Delete are refused by name.

KNOWN CEILINGS
  * One account at a time, the one the tab is on. One sign-in can hold
    several (Return To Account Listing), so each document is bound to the
    account it was listed on, by a digest of the number its pages show
    (account_of), and saved only while the tab shows that account. A
    sign-in of several accounts whose pages name none stops the list.
    Linked accounts are never opened.
  * The Investor InBox is not read.
  * Security History and Payment History are saved as they first show; a
    date range or a type chosen in their forms is never submitted.
"""
from __future__ import annotations

import functools
import hashlib
import logging
import re
import sys
from dataclasses import dataclass, field
from datetime import date as _date
from html.parser import HTMLParser
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import parse_qs, urlsplit
from paperpull_core.urls import join as join_url

from paperpull_core import pressing
from paperpull_core import receipt_pdf
from paperpull_core.controls import SETTINGS_CONTROL_RE, AUTH_CONTROL_RE, escape_for_locator
from paperpull_core.redact import private_words, redact, set_private_words  # noqa: F401  (re-exported)
from paperpull_core.urls import is_safe_url as _host_allows
from paperpull_core.words import words_for as _words_for

log = logging.getLogger("treasurydirect_docs.site")


def _words():
    """This app's own words for paperpull_core.words."""
    return _words_for("TreasuryDirect", sys.modules[__name__])


# ===========================================================================
# What the survey saw (CONFIRMED 2026-10-13) and what it could not
# (UNCONFIRMED). A later survey with a taxable year repairs only this block.
# ===========================================================================
SURVEYED = "2026-10-13"

# CONFIRMED. The signed-in pages are on www; the public site and its help
# pages are on the same host but under other paths, and only GATEWAY_PATH
# is a signed-in page.
ALLOWED_HOSTS = {"www.treasurydirect.gov", "treasurydirect.gov"}
BASE = "https://www.treasurydirect.gov"
GATEWAY_PATH = "/RS/RSGatewayRW"
LOGIN_URL = "https://www.treasurydirect.gov/RS/UN-Display.do"

# CONFIRMED. Where a session that has ended lands.
SIGNED_OUT_HOSTS = {"caia.treasury.gov", "api.id.me", "id.me"}
LOGIN_URL_MARKERS = ["/log-in", "authorization.oauth2", "/rs/un-display", "/rs/pw-display"]
SIGNED_OUT_MARKERS = [
    "treasurydirect is unavailable", "you have been logged out", "you have been signed out",
    "session has expired", "session has timed out", "your session timed out",
]

# CONFIRMED. The top tabs every signed-in page draws, by label and handler.
# Only these four are ever pressed; the others are listed to be refused.
TAB_LINKS = {
    "My Account": "misc.DisplayWelcome",
    "Current Holdings": "ch.DisplayCurrentHoldings",
    "ManageDirect®": "md.DisplayManageDirect",
    "History": "hist.DisplayHistory",
}
# CONFIRMED. The History page's links to the two histories saved.
HISTORY_LINKS = {
    "Security History": "sechist.DisplaySecurityHistory",
    "Payment History": "payhist.DisplayPaymentHistorySummary",
}
# Each page's own heading (its h1), so a press is known to have landed where
# it was meant to. CONFIRMED as h1 for History, the two histories and My
# Account; read from the page text, not yet as h1, for Current Holdings and
# ManageDirect.
PAGE_HEADINGS = {
    "ch.DisplayCurrentHoldings": re.compile(r"^current\s+holdings$", re.I),
    "md.DisplayManageDirect": re.compile(r"^managedirect®?$", re.I),
    "hist.DisplayHistory": re.compile(r"^history$", re.I),
    "sechist.DisplaySecurityHistory": re.compile(r"^history\s*»\s*security\s+history$", re.I),
    "payhist.DisplayPaymentHistorySummary": re.compile(r"^history\s*»\s*payment\s+history$", re.I),
    "misc.DisplayWelcome": re.compile(r"^welcome\s+to\s+your\s+account\s+summary\b", re.I),
}

# CONFIRMED. ManageDirect's tax list: an h4 "Manage My Taxes" over a list of
# "Year 2025 (No taxable transactions)" items, plain text.
TAXES_SECTION_RE = re.compile(r"^\s*manage\s+my\s+taxes\s*$", re.I)
NO_TAX_YEAR_RE = re.compile(r"^year\s+((?:19|20)[0-9]{2})\s*\(\s*no\s+taxable\s+transactions\s*\)$", re.I)
# SURVEY NEEDED. A taxable year's item, assumed to be a link "Year 2025".
# What it opens, and the handler of that link, have never been seen: the
# surveyed account had no taxable year. So a taxable year is LISTED but its
# link is NEVER PRESSED. Its 1099 is recorded for manual review, so the
# account holder sees it exists and saves it by hand. A later survey must
# observe the exact handler of the year link, of any "View your 1099 for tax
# year 2025" link (TreasuryDirect's public help) and of the way back, and
# only then add them to the press allowlist (is_safe_handler) with a page
# contract (is_1099_page) for what they open.
TAX_YEAR_LINK_RE = re.compile(r"^year\s+((?:19|20)[0-9]{2})$", re.I)
# Read only, for the survey: the label public help gives the 1099 link.
FORM_1099_LINK_RE = re.compile(r"^view\s+your\s+(?:form\s+)?1099\s+for\s+tax\s+year\s+((?:19|20)[0-9]{2})$", re.I)
# The tax pages are never pressed to, so a 1099 is never taken by this app.
TAX_PAGES_SURVEYED = False
# The 1099 page's own heading must name the form; a page that calls itself
# the Taxable Transaction Summary is never taken for it.
FORM_1099_HEADING_RE = re.compile(r"^(?:form\s+)?1099(?:-(?:int|b|oid))?\b", re.I)
FORM_1099_PAGE_RE = re.compile(r"\bform\s+1099", re.I)
SUMMARY_PAGE_RE = re.compile(r"taxable\s+transaction\s+summary", re.I)
# The names this app files its documents under, as a link may carry them,
# and a plain "View statement" or "Download PDF".
# A label alone is never enough to be pressed: its handler must also be on
# an allowlist (is_safe_handler).
DOC_NAME_RE = re.compile(r"^(?:(?:view|download)\s+)?(?:1099\s+tax\s+form|current\s+holdings|"
                         r"security\s+history|payment\s+history)$|^(?:view|download)\s+(?:statement|pdf)$", re.I)

# CONFIRMED words on a passcode or security-question page, counted only
# where there is somewhere to type an answer.
OTP_MARKERS = ["one-time passcode", "one time passcode", "security question",
               "verification code", "enter the code", "we sent a code"]

# CONFIRMED. What names the account holder: "<Name>'s account: <number>" on
# every page, the account number "A-123-456-789", the session's processID,
# an InBox message's upd_ts, and confirmation numbers and serials (letters
# and digits together).
ACCOUNT_OWNER_RE = re.compile(r"([A-Z][\w.-]{1,40}(?:[ \t]+[A-Z][\w.-]{1,40}){0,3})'s[ \t]+account\b")
ACCOUNT_NUMBER_RE = re.compile(r"\b[A-Z]-?[0-9]{3}-?[0-9]{3}-?[0-9]{3}\b")
# The account the page is on, the number after "<Name>'s account" in the
# line every signed-in page draws. Only a number there names it.
ACCOUNT_LINE_RE = re.compile(r"['’]s[ \t]+account\s*:?\s*(%s)" % ACCOUNT_NUMBER_RE.pattern)
# One sign-in can hold several accounts. Its pages then link back to the
# list of them, "Return To Account Listing" (as the survey's pages drew it).
ACCOUNT_LISTING_RE = re.compile(r"^return\s+to\s+account\s+listing$", re.I)
ACCOUNT_LISTING_HANDLER_RE = re.compile(r"multiaccount", re.I)
MIXED_ID_RE = re.compile(r"\b(?=[A-Z0-9]*[0-9])(?=[A-Z0-9]*[A-Z])[A-Z0-9]{6,}\b")
TAX_ID_RE = re.compile(r"(?<![0-9])(?:[0-9Xx*]{3}-[0-9Xx*]{2}-[0-9]{4}|[0-9]{9})(?![0-9])")
PRIVATE_QUERY_KEYS = ("processID", "upd_ts", "count")
# ===========================================================================
# end of the surveyed block
# ===========================================================================

URLS = {
    "home": f"{BASE}/",
    "login": LOGIN_URL,
}

# ---------------------------------------------------------------------------
# HARD SAFETY GUARD. Tuned for a Treasury securities account. Every label
# pressed must also be on an allowlist, so this is the second wall.
# ---------------------------------------------------------------------------
FORBIDDEN_CONTROL_RE = re.compile(
    r"(\bbuy|\bpurchas|\bredeem|\bredemption|\bcash\s+(in|out)\b|\bconvert|\bconversion\b|"
    r"\btransfer|\bgift|\bdeliver|\breinvest|\bschedul|\bpayroll\b|\bc\s+of\s+i\b|"
    r"\bcertificate\s+of\s+indebtedness\b|\bbank|\bwithdraw|\bdeposit|\bfunding\b|\bregistration\b|"
    r"\bbeneficiar|\bsign\s*(out|off)\b|\blog\s*(out|off)\b|\blogoff\b|\blogout\b|\bsettings?\b|"
    r"\bprofile\b|\bpreferences?\b|\bpassword\b|\bsecurity\s+questions?\b|\bpersonal\s+information\b|"
    r"\bsave\b|\bsubmit\b|\bconfirm\b|\bcontinue\b|\bdelet|\bde-?link|\bremov|\bcancel\b|\bedit|"
    r"\bupdat|\bchang|\bmanage\b|\blinked\b|\bcustom\b|\bminor\b|\bestablish|\bopen\s+(an?\s+)?account\b|"
    r"\bclose\b|\bupload\b|\bemail\b|\bshare|\bagree\b|\baccept\b|\bapprove|\bauthori[sz]e\b|\bverify\b|"
    r"\bsell\b|\border\b|\bwithholding\b|\bw-?9\b|\binbox\b|\brights\b|\baccount\s+listing\b|"
    r"\baccount\s+info|\bpending\b|\bhere\b|\bcontact\b|\bmytreasury\b)", re.I)

# What a pressed link's handler must never be.
FORBIDDEN_HANDLER_RE = re.compile(
    r"^(bd|gb|bank|al|la|ac|tr|trfrmyt|pt|ai|cofihist|psphist)\.|"
    r"(exit|logoff|logout|multiaccount|buy|redeem|redemption|transfer|gift|bank|edit|change|delete|"
    r"delink|create|register|registration|reinvest|schedule|rights|funding|inbox|contactus|cancel|"
    r"submit|confirm|approve|accept|agree|process|send|request|update|remove|withhold)", re.I)

SECURITY_CHALLENGE_MARKERS = ["captcha", "are you a robot", "verify your identity",
                              "confirm your identity", "access denied"]
RATE_LIMIT_MARKERS = ["too many requests", "rate limit", "try again later",
                      "temporarily unavailable", "http error 429", "unusual traffic"]

# Fallback selectors (used by --diagnose and the journal).
FALLBACK = {
    "doc_row": "a[href*='UIHandler=']",
    "doc_link": "a[href*='UIHandler=']",
    "tab_link": "a[href*='fromTabLink=true']",
    "page_ready": "h1",
    "password_field": "input[type='password']",
}


# ---------------------------------------------------------------------------
# Boundaries
# ---------------------------------------------------------------------------

class SessionExpired(Exception):
    """TreasuryDirect answered as a signed-out session: its sign-in page,
    the caia.treasury.gov sign-in, or "TreasuryDirect is unavailable." The
    run stops for the account holder."""


class OtpRequired(Exception):
    """TreasuryDirect asked for a one-time passcode or a security answer.
    The app never answers one; the run stops for the account holder."""


class NotLive(Exception):
    """The tab is not a signed-in TreasuryDirect page with its top tabs, so
    there is nothing this app may press. The run stops and says where to
    go."""


class ListStopped(Exception):
    """The list has a part this could not read, so what was read is not all
    of it. `docs` holds what was read before it stopped."""

    def __init__(self, why: str, docs=None):
        super().__init__(why)
        self.docs = list(docs or [])


class OtherAccount(Exception):
    """The tab is on an account other than the one the document was listed
    on. Nothing is saved, and the run sends the document to review."""


# ---------------------------------------------------------------------------
# Reading a page, in Python, from the HTML the tab holds. Nothing is run.
# ---------------------------------------------------------------------------

# Headings, read for the survey and to know a page. Only a real heading names
# the section a link sits in, so a table's column head ("Tax Year") or the
# page title does not, and bold text is not read as one at all.
_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6", "th", "legend", "caption", "title"}
_SECTION_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6", "legend", "caption"}
_SKIP_TAGS = {"script", "style", "noscript", "template"}
_ANSWER_TYPES = {"text", "password", "tel", "number", "email"}


@dataclass
class Link:
    text: str
    href: str
    section: str = ""

    @property
    def handler(self) -> str:
        return handler_of(self.href)


@dataclass
class Item:
    """A list item: its whole text, the section it is in, and its links."""
    text: str
    section: str = ""
    links: List[Link] = field(default_factory=list)


@dataclass
class _Form:
    method: str
    inputs: List[Tuple[str, str, str]] = field(default_factory=list)
    section: str = ""


class _Page(HTMLParser):
    """Every link with its visible text and the heading it sits under, every
    list item, every form's method and input names, types and button labels
    (never a value typed), whether there is a field to type an answer into,
    the h1, the headings and the visible text nodes."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: List[Link] = []
        self.items: List[Item] = []
        self.forms: List[_Form] = []
        self.headings: List[str] = []
        self.h1: List[str] = []
        self.words: List[str] = []
        self.answer_field = False
        self.password_field = False
        self._section = ""
        self._skip = 0
        self._heading: Optional[List[str]] = None
        self._heading_depth = 0
        self._link: Optional[Link] = None
        self._link_text: List[str] = []
        self._items: List[Tuple[Item, List[str]]] = []

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag in _SKIP_TAGS:
            self._skip += 1
            return
        if tag in _HEADING_TAGS:
            if self._heading is None:
                self._heading = []
            self._heading_depth += 1
        if tag == "li":
            self._items.append((Item(text="", section=self._section), []))
        if tag == "a":
            self._link = Link(text="", href=a.get("href", ""), section=self._section)
            self._link_text = []
        elif tag == "form":
            self.forms.append(_Form(method=(a.get("method") or "get").lower(), section=self._section))
        if tag in ("input", "select", "textarea", "button"):
            kind = (a.get("type") or ("text" if tag == "input" else tag)).lower()
            if kind == "password":
                self.password_field = True
            if kind in _ANSWER_TYPES or tag == "textarea":
                self.answer_field = True
            if self.forms:
                label = a.get("value", "") if kind in ("submit", "button", "reset") else ""
                self.forms[-1].inputs.append((a.get("name", ""), kind, label))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag in _HEADING_TAGS or tag in ("a", "li") or tag in _SKIP_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag in _SKIP_TAGS:
            self._skip = max(0, self._skip - 1)
            return
        if tag in _HEADING_TAGS and self._heading is not None:
            self._heading_depth -= 1
            if self._heading_depth <= 0:
                text = _squash("".join(self._heading))
                if text:
                    self.headings.append(text)
                    if tag == "h1":
                        self.h1.append(text)
                    if tag in _SECTION_TAGS:
                        self._section = text
                self._heading = None
                self._heading_depth = 0
        if tag == "a" and self._link is not None:
            self._link.text = _squash("".join(self._link_text))
            self.links.append(self._link)
            if self._items:
                self._items[-1][0].links.append(self._link)
            self._link = None
        if tag == "li" and self._items:
            item, parts = self._items.pop()
            item.text = _squash("".join(parts))
            self.items.append(item)

    def handle_data(self, data):
        if self._skip:
            return
        self.words.append(data)
        if self._heading is not None:
            self._heading.append(data)
        if self._link is not None:
            self._link_text.append(data)
        for _item, parts in self._items:
            parts.append(data)


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def read_page(html: str) -> _Page:
    """The links, list items, forms, headings and text of a page's HTML."""
    p = _Page()
    try:
        p.feed(html or "")
        p.close()
    except Exception as e:
        log.info("a page's HTML could not be read whole (%s)", type(e).__name__)
    return p


def _text_of(page: _Page) -> str:
    return _squash(" ".join(page.words)).lower()


def handler_of(url: str) -> str:
    """The UIHandler a TreasuryDirect address names, or ""."""
    try:
        q = parse_qs(urlsplit(url or "").query)
    except ValueError:
        return ""
    vals = q.get("UIHandler") or []
    return vals[0] if len(vals) == 1 and re.fullmatch(r"[A-Za-z]+\.[A-Za-z0-9]+", vals[0]) else ""


def _url(page) -> str:
    try:
        return page.url or ""
    except Exception:
        return ""


def _content(page) -> str:
    try:
        return page.content() or ""
    except Exception as e:
        log.info("the tab's page could not be read (%s)", type(e).__name__)
        return ""


# ---------------------------------------------------------------------------
# Hosts and session
# ---------------------------------------------------------------------------

def looks_like_login_url(url: str) -> bool:
    """Whether an address is one of the site's sign-in pages (the log-in
    page, the ID.me hand-off, the name and password steps), by its path."""
    low = str(url or "").lower()
    return any(m in low for m in LOGIN_URL_MARKERS)


def is_safe_url(url: str) -> bool:
    """True only for an https URL on exactly TreasuryDirect's own hosts."""
    return _host_allows(url, ALLOWED_HOSTS, subdomains=False)


# CONFIRMED. The one host the signed-in pages are on, and the only one a
# press may lead to. The bare host serves the public site and the log-in page.
SIGNED_IN_HOST = "www.treasurydirect.gov"


def is_signed_in_url(url: str) -> bool:
    """True only for a signed-in page's address: the gateway path on exactly
    www.treasurydirect.gov, over https."""
    if not is_safe_url(url):
        return False
    try:
        parts = urlsplit(url)
        return (parts.hostname or "").lower() == SIGNED_IN_HOST and parts.path == GATEWAY_PATH
    except ValueError:
        return False


def _signed_out_url(url: str) -> bool:
    try:
        host = (urlsplit(url or "").hostname or "").lower()
    except ValueError:
        host = ""
    low = (url or "").lower()
    return host in SIGNED_OUT_HOSTS or any(m in low for m in LOGIN_URL_MARKERS)


def html_says_signed_out(html: str, url: str = "") -> bool:
    """A sign-in address, a password field, or a page saying the session
    has ended ("TreasuryDirect is unavailable.")."""
    if _signed_out_url(url):
        return True
    page = read_page(html)
    if page.password_field:
        return True
    text = _text_of(page)
    return any(m in text for m in SIGNED_OUT_MARKERS)


def html_asks_for_code(html: str) -> bool:
    """A one-time passcode or security question: its wording on a page with
    somewhere to type the answer. ManageDirect's link "View/Change my
    security questions", on a page with no answer field, is not one."""
    page = read_page(html)
    # A signed-in page draws the top tabs, and every one carries a text
    # field of the site's own ("iesinglesubmithack") under a notice that
    # "security questions will be retired" (CONFIRMED). A passcode page is
    # not a signed-in page, so a page with the tabs is never one.
    if not page.answer_field or _has_tabs(page):
        return False
    text = _text_of(page)
    return any(m in text for m in OTP_MARKERS)


def looks_signed_out(page) -> bool:
    """A sign-in or ended-session page. A tab whose address cannot be read
    is never called signed in."""
    try:
        url = page.url or ""
    except Exception:
        return True
    return html_says_signed_out(_content(page), url)


def detect_security_challenge(page) -> Optional[str]:
    """Names the passcode, CAPTCHA or throttling prompt on screen, or None."""
    html = _content(page)
    if html_asks_for_code(html):
        return "Security challenge detected: a passcode or security question"
    text = _text_of(read_page(html))[:3000]
    for m in SECURITY_CHALLENGE_MARKERS:
        if m in text:
            return f"Security challenge detected: '{m}'"
    for m in RATE_LIMIT_MARKERS:
        if m in text:
            return f"Possible rate limiting detected: '{m}'"
    return None


def _has_tabs(page: _Page) -> bool:
    """Whether the page draws the signed-in top tabs: each of TAB_LINKS by
    its label and handler."""
    have = {(lk.text, lk.handler) for lk in page.links}
    return all((label, h) in have for label, h in TAB_LINKS.items())


def check_signed_in(html: str, url: str) -> _Page:
    """The page, read, when it is a signed-in TreasuryDirect page. Raises
    SessionExpired for any sign-in or ended-session page, OtpRequired for a
    passcode or security question, NotLive for anything else."""
    if html_says_signed_out(html, url):
        raise SessionExpired("TreasuryDirect answered as signed out")
    if not is_safe_url(url):
        raise NotLive("the tab is not on TreasuryDirect")
    if html_asks_for_code(html):
        raise OtpRequired("TreasuryDirect is asking for a passcode or security answer")
    page = read_page(html)
    if not is_signed_in_url(url) or not _has_tabs(page):
        raise NotLive("the tab is not a signed-in TreasuryDirect page")
    return page


def is_safe_control(name: str) -> bool:
    """Deny by default: an unreadable label is refused, then this app's
    blocklist, then the shared core guards, and only then the labels this
    app presses."""
    name = _squash(name or "")
    if not name:
        return False
    if FORBIDDEN_CONTROL_RE.search(name):
        return False
    if SETTINGS_CONTROL_RE.search(name) or AUTH_CONTROL_RE.search(name):
        return False
    return name in TAB_LINKS or name in HISTORY_LINKS or bool(DOC_NAME_RE.match(name))


def is_safe_handler(handler: str) -> bool:
    """A handler this app may press a link to: exactly one it names, and
    never one FORBIDDEN_HANDLER_RE refuses. No tax handler is on the list
    until one has been surveyed."""
    if not handler or FORBIDDEN_HANDLER_RE.search(handler):
        return False
    return handler in TAB_LINKS.values() or handler in HISTORY_LINKS.values()


# ---------------------------------------------------------------------------
# Private words. Registered from every page read, before anything is logged.
# ---------------------------------------------------------------------------

_COMMON = {"account", "number", "name", "treasury", "treasurydirect", "direct", "your", "welcome",
           "summary", "primary", "individual", "history", "current", "holdings", "security",
           "payment", "series", "savings", "bond", "bonds", "type", "amount", "date", "none",
           "confirm", "transaction", "managedirect", "manage", "year", "form"}


def private_values(html: str, url: str = "") -> set:
    """What names the account holder on this page: the name before "'s
    account", the account number, a taxpayer id, confirmation numbers and
    serials, and the session's processID and other private query values.
    In the parts redact matches anywhere (four letters or more, or any with
    a digit), plus each whole value with a digit. Words of the page's own
    are left out."""
    text = "\n".join(read_page(html).words) if html else ""
    found = set(ACCOUNT_NUMBER_RE.findall(text)) | set(TAX_ID_RE.findall(text)) | set(MIXED_ID_RE.findall(text))
    for m in ACCOUNT_OWNER_RE.finditer(text):
        found.add(m.group(1).strip())
    for addr in [url] + [lk.href for lk in read_page(html).links] if html or url else []:
        try:
            q = parse_qs(urlsplit(addr or "").query)
        except ValueError:
            continue
        for key in PRIVATE_QUERY_KEYS:
            found.update(v for v in q.get(key, []) if v)
    parts = {part for w in found for part in re.split(r"[\s,.#/:;()'-]+", str(w or ""))
             if (len(part) >= 4 or re.search(r"[0-9]", part)) and part.lower() not in _COMMON}
    return parts | {w for w in found if re.search(r"[0-9]", w)}


def guard_private(html: str, url: str = "") -> int:
    """Register this page's private values beside the owner's name the run
    already set. Returns how many were new. Never logs a value."""
    new = private_values(html, url) - set(private_words())
    if new:
        set_private_words(private_words() + sorted(new))
    return len(new)


# ---------------------------------------------------------------------------
# The account a page is on, known by a digest of its number and never by
# the number itself.
# ---------------------------------------------------------------------------

_DIGEST_SALT = b"paperpull treasurydirect account"


@functools.lru_cache(maxsize=16)
def account_digest(number: str) -> str:
    """Twelve hex letters naming the account numbered `number`, or "" for
    anything that is not an account number. One letter and nine digits are
    few enough to try every one against a plain digest, so this is a slow
    one (PBKDF2 over SHA-256, 200,000 rounds). The number itself is in no
    record, key or file name."""
    norm = re.sub(r"[\s-]", "", str(number or "")).upper()
    if not re.fullmatch(r"[A-Z][0-9]{9}", norm):
        return ""
    return hashlib.pbkdf2_hmac("sha256", norm.encode("ascii"), _DIGEST_SALT, 200_000).hex()[:12]


def account_numbers_of(page_read: _Page) -> List[str]:
    """The account numbers the page's account line names, each as one
    letter and nine digits. Each is registered as a private word, as the
    page shows it and as it is written here, before anything is logged."""
    found = []
    for m in ACCOUNT_LINE_RE.finditer(_squash(" ".join(page_read.words))):
        norm = m.group(1).replace("-", "").upper()
        new = [w for w in dict.fromkeys((m.group(1), norm)) if w not in private_words()]
        if new:
            set_private_words(private_words() + new)
        if norm not in found:
            found.append(norm)
    return found


def lists_several_accounts(page_read: _Page) -> bool:
    """Whether the page links back to the list of the accounts its sign-in
    holds, Return To Account Listing."""
    return any(ACCOUNT_LISTING_RE.match(lk.text) or ACCOUNT_LISTING_HANDLER_RE.search(lk.handler)
               for lk in page_read.links)


def account_of(page_read: _Page) -> str:
    """The digest of the account the page is on (account_digest), or ""
    when the page names no account and links to no list of several. A page
    naming two accounts, or naming none while its sign-in holds several,
    stops the list, since which account it shows cannot be told."""
    numbers = account_numbers_of(page_read)
    if len(numbers) > 1:
        raise ListStopped("the page names more than one account")
    if numbers:
        return account_digest(numbers[0])
    if lists_several_accounts(page_read):
        raise ListStopped("the sign-in holds several accounts and the page names none of them")
    return ""


# ---------------------------------------------------------------------------
# Pressing. Only a page's own link, in the tab, through the core guard.
# ---------------------------------------------------------------------------

def _read(page, tabs: bool = True) -> _Page:
    """The tab's page, its private values registered, checked as signed in:
    with the top tabs, or (tabs=False, for the 1099 page, which is said to
    draw none) at least on the signed-in address and neither signed out nor
    asking for a code."""
    url, html = _url(page), _content(page)
    guard_private(html, url)
    if tabs:
        return check_signed_in(html, url)
    if html_says_signed_out(html, url):
        raise SessionExpired("TreasuryDirect answered as signed out")
    if html_asks_for_code(html):
        raise OtpRequired("TreasuryDirect is asking for a passcode or security answer")
    if not is_signed_in_url(url):
        raise NotLive("the tab is not a signed-in TreasuryDirect page")
    return read_page(html)


def _one_link(page_read: _Page, label_re, handler_ok) -> Link:
    """The one link on the page whose label matches and whose handler passes.
    None, or more than one, stops the list."""
    found = [lk for lk in page_read.links if label_re(lk.text) and handler_ok(lk.handler)]
    if len(found) != 1:
        raise ListStopped("%d links on the page match the one this app presses" % len(found))
    return found[0]


def _press_link(page, link: Link, what: str, step: str, landed, tabs: bool = True) -> _Page:
    """Press `link` in the tab, once, and wait for its page. The label and
    handler are checked again first; the locator must find exactly that one
    link; the press goes through paperpull_core.pressing.click, which
    refuses a control anything covers. `landed(handler, page)` says the
    page that came is the one meant. Returns the new page, read and
    checked as signed in (with its top tabs unless `tabs` is False)."""
    if not is_safe_control(link.text) or not is_safe_handler(link.handler):
        raise ListStopped("a link this app does not press")
    # Where the link leads, read against the page it is on: only the
    # signed-in address on TreasuryDirect's own host is ever pressed toward.
    href = (link.href or "").strip()
    if not href or href.lower().startswith(("javascript:", "data:", "#")) \
            or not is_signed_in_url(join_url(_url(page), href)):
        raise ListStopped("a link that leads off the signed-in pages")
    loc = page.locator('a[href*="UIHandler=%s"]' % link.handler).filter(
        has_text=re.compile(r"^\s*%s\s*$" % escape_for_locator(link.text)))
    try:
        n = loc.count()
    except Exception:
        n = -1
    if n != 1:
        raise ListStopped("the link to press is not one on the page")
    before = _url(page)
    pressing.click(page, loc.first, css=pressing.LINKS, what=what, words=_words(), step=step)
    try:
        page.wait_for_url(lambda u: u != before, timeout=30000)
        page.wait_for_load_state("domcontentloaded", timeout=30000)
    except Exception as e:
        log.info("the page did not change after a press (%s)", type(e).__name__)
        _read(page, tabs)
        raise ListStopped("the page did not change after a press")
    after = _read(page, tabs)
    if not landed(handler_of(_url(page)), after):
        raise ListStopped("a press landed somewhere other than the page meant")
    return after


def _heading_is(handler: str, page_read: _Page) -> bool:
    rx = PAGE_HEADINGS.get(handler)
    return bool(rx) and any(rx.match(h) for h in page_read.h1)


def _open_tab(page, label: str) -> _Page:
    """Press one of the top tabs and land on its page."""
    handler = TAB_LINKS[label]
    here = _read(page)
    if handler_of(_url(page)) == handler and _heading_is(handler, here):
        # Already there. Pressing a tab to the page it is on may change
        # nothing a wait could see, so it is not pressed.
        return here
    link = _one_link(here, lambda t: t == label, lambda h: h == handler)
    return _press_link(page, link, "the %s tab" % label.rstrip("®"), "open a tab",
                       lambda h, p: h == handler and _heading_is(handler, p))


def _open_history(page, label: str) -> _Page:
    """Press History, then one of its histories."""
    handler = HISTORY_LINKS[label]
    hist = _open_tab(page, "History")
    link = _one_link(hist, lambda t: t == label, lambda h: h == handler)
    return _press_link(page, link, "the %s link" % label, "open a history",
                       lambda h, p: h == handler and _heading_is(handler, p))


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------

HOLDINGS = "holdings"
SECURITY_HISTORY = "security-history"
PAYMENT_HISTORY = "payment-history"
FORM_1099 = "1099"
SNAPSHOTS = {
    HOLDINGS: "Current Holdings",
    SECURITY_HISTORY: "Security History",
    PAYMENT_HISTORY: "Payment History",
}
DOC_ID_RE = re.compile(r"(?:(holdings|security-history|payment-history)-([0-9]{4}-[0-9]{2}-[0-9]{2})"
                       r"|((?:19|20)[0-9]{2})-1099)")


@dataclass
class RawDoc:
    title: str
    # The digest of the account it was listed on (account_digest), or ""
    # for a sign-in of one account whose pages name none.
    account: str = ""
    date_text: str = ""
    href: str = ""
    text: str = ""
    row_index: int = -1
    kind: str = "doc"
    # "<kind>-<date>" for a snapshot, "<tax year>-1099" for a 1099.
    document_id: str = ""


def _snapshot(kind: str, day: str, account: str = "") -> RawDoc:
    title = "TreasuryDirect %s %s" % (SNAPSHOTS[kind], day)
    return RawDoc(title=title, account=account, date_text=day, href=GATEWAY_PATH, text=title,
                  kind=kind, document_id="%s-%s" % (kind, day))


def _tax(year: str, account: str = "") -> RawDoc:
    title = "TreasuryDirect Form 1099 %s" % year
    return RawDoc(title=title, account=account, date_text="%s-12-31" % year, href=GATEWAY_PATH,
                  text=title, kind=FORM_1099, document_id="%s-1099" % year)


def tax_years_of(page_read: _Page) -> List[str]:
    """The tax years ManageDirect's Manage My Taxes list offers a 1099 for,
    newest first. A year listed "(No taxable transactions)" has none. An
    item that reads as neither, a section that is missing, or a list with
    no year stops the list."""
    if not any(TAXES_SECTION_RE.match(h) for h in page_read.headings):
        raise ListStopped("ManageDirect shows no Manage My Taxes section")
    items = [it for it in page_read.items if TAXES_SECTION_RE.match(it.section or "")]
    if not items:
        raise ListStopped("Manage My Taxes lists no tax year")
    years = []
    for it in items:
        if NO_TAX_YEAR_RE.match(it.text) and not it.links:
            continue
        m = TAX_YEAR_LINK_RE.match(it.text)
        if not m or len(it.links) != 1 or it.links[0].text != it.text:
            raise ListStopped("a Manage My Taxes item does not read as a tax year")
        if not it.links[0].handler or FORBIDDEN_HANDLER_RE.search(it.links[0].handler):
            raise ListStopped("a tax year link opens a page this app does not know")
        years.append(m.group(1))
    if len(set(years)) != len(years):
        raise ListStopped("one tax year is listed twice")
    return sorted(years, reverse=True)


def is_stale(doc_id: str, today: Optional[str] = None) -> bool:
    """Whether a recorded snapshot is of a day other than today. A snapshot
    shows the account as it is when taken, so one recorded on an earlier
    day (a run that stopped) is never taken under that day's name."""
    m = DOC_ID_RE.fullmatch(doc_id or "")
    return bool(m and m.group(1) and m.group(2) != (today or _date.today().isoformat()))


def collect_download_docs(page, today: Optional[str] = None) -> List[RawDoc]:
    """Every document of the account the tab is on: today's snapshots of
    Current Holdings, Security History and Payment History, and a 1099 for
    each taxable year Manage My Taxes lists, each bound to the account the
    tab is on (account_of). ManageDirect is opened by pressing its tab, and
    must be of the same account. A list that cannot be read whole raises
    ListStopped holding what was read, and nothing at all when which
    account the tab is on cannot be told. SessionExpired, OtpRequired and
    NotLive propagate."""
    day = today or _date.today().isoformat()
    account = account_of(_read(page))
    docs = [_snapshot(k, day, account) for k in (HOLDINGS, SECURITY_HISTORY, PAYMENT_HISTORY)]
    try:
        md = _open_tab(page, "ManageDirect®")
        if account_of(md) != account:
            raise ListStopped("ManageDirect is of another account than the page the list began on")
        docs += [_tax(y, account) for y in tax_years_of(md)]
    except ListStopped as stop:
        raise ListStopped(str(stop), docs)
    for i, d in enumerate(docs):
        d.row_index = i
    return docs


def goto_documents(page) -> bool:
    """Whether the tab is a signed-in TreasuryDirect page with its top tabs.
    Nothing is opened or pressed."""
    try:
        _read(page)
        return True
    except (SessionExpired, OtpRequired, NotLive) as e:
        log.info("no signed-in TreasuryDirect page: %s", e)
        return False


def documents_list_opens(page) -> bool:
    """Whether the documents can be listed whole, which presses ManageDirect."""
    try:
        collect_download_docs(page)
        return True
    except (SessionExpired, OtpRequired, NotLive, ListStopped) as e:
        log.info("TreasuryDirect could not be read: %s", e)
        return False


def expand_all(page) -> None:
    """Nothing to expand: every page is drawn whole by the server."""
    return None


_FORM_TAG_RE = re.compile(r"<\s*(/?)\s*form\b[^>]*>", re.I)
_CONTROL_RE = re.compile(r"<\s*(input|button|select|textarea)\b[^>]*>(?:.*?<\s*/\s*\1\s*>)?", re.I | re.S)


def unwrap_forms(html: str) -> str:
    """The page with its form tags turned into plain blocks and its form
    controls taken out. Every TreasuryDirect page wraps its content in one
    form (CONFIRMED), and the inert render removes a form whole, content
    and all, which would leave the PDF blank. The words inside stay; the
    radio buttons, Submit, Cancel and Delete do not."""
    out = _CONTROL_RE.sub("", html or "")
    return _FORM_TAG_RE.sub(lambda m: "</div>" if m.group(1) else "<div>", out)


# One whole tag, a quoted value read as one piece so a ">" inside quotes
# does not end it. Possessive, and a tag with no ">" runs to the end of the
# page, so a page of broken tags is read in linear time.
_TAG_RE = re.compile(r"<[a-zA-Z](?:\"[^\"]*+\"|'[^']*+'|[^'\">]++)*+>?")
# A link's address inside one tag. Quoted values are passed over first, so
# an address is found only where it stands as an attribute.
_HREF_RE = re.compile(r"(\"[^\"]*+\"|'[^']*+')|(?<=[\s/\"'])(?:xlink:)?href\s*=\s*"
                      r"(?:\"[^\"]*+\"|'[^']*+'|[^\s>]*+)", re.I)


def drop_links(html: str) -> str:
    """The page with every link's address taken out of its tags, the words
    of each link kept. A link drawn into a PDF keeps its address there, and
    every TreasuryDirect address carries the session's processID."""
    return _TAG_RE.sub(lambda m: _HREF_RE.sub(lambda a: a.group(1) or "", m.group(0)), html or "")


def render(page, html: str, out_path: Path) -> None:
    """The tab's page as a PDF, rendered inertly. Form controls are removed
    and forms unwrapped (unwrap_forms), every link's address is taken out
    (drop_links), then scripts and frames are stripped, in a fresh context
    with JavaScript off, no cookies and no network. The account holder's
    own words stay in the PDF, which is the document, and never reach a
    log."""
    receipt_pdf.print_html_inert_to_pdf(page, drop_links(unwrap_forms(html)), Path(out_path),
                                        base=BASE + "/")


# What a saved snapshot's own text must name: its page's heading.
_SNAPSHOT_TEXT_RE = {
    HOLDINGS: re.compile(r"current\s+holdings", re.I),
    SECURITY_HISTORY: re.compile(r"security\s+history", re.I),
    PAYMENT_HISTORY: re.compile(r"payment\s+history", re.I),
}


def pdf_names_document(doc_id: str, text: str) -> bool:
    """Whether a saved PDF's extracted text names the document recorded as
    `doc_id`: the snapshot's own heading, or for a 1099 the form and its
    year. A blank or wrong page does not, and is left for review."""
    m = DOC_ID_RE.fullmatch(doc_id or "")
    text = re.sub(r"\s+", " ", text or "")
    if not m or not text.strip():
        return False
    if m.group(1):
        return bool(_SNAPSHOT_TEXT_RE[m.group(1)].search(text))
    return bool(FORM_1099_PAGE_RE.search(text)) and bool(re.search(r"\b%s\b" % m.group(3), text))


def is_1099_page(html: str, year: str) -> bool:
    """Whether the page is the year's Form 1099: a heading of its own that
    names the form, the form named in its text with the year, and no
    heading calling it the Taxable Transaction Summary. UNCONFIRMED: no
    1099 has been surveyed, so anything less is left for review."""
    page = read_page(html)
    text = _text_of(page)
    heads = page.h1 + [h for h in page.headings if h not in page.h1]
    return (any(FORM_1099_HEADING_RE.match(h) for h in heads)
            and not any(SUMMARY_PAGE_RE.search(h) for h in heads)
            and bool(FORM_1099_PAGE_RE.search(text)) and bool(re.search(r"\b%s\b" % re.escape(year), text)))


def download_document(page, doc_id: str, iso_date: str, out_path,
                      trace: Optional[list] = None, account: str = "") -> bool:
    """Save the document discovery recorded as `doc_id`, dated `iso_date`,
    of the account recorded as `account` (account_digest, "" for none).
    The tab is moved to it by pressing the page's own links, and its HTML
    rendered. The tab must be on that account before anything is pressed,
    and the page rendered must show it, else OtherAccount is raised and
    nothing is saved. SessionExpired, OtpRequired, NotLive and a press the
    core refuses (pressing.Stop) propagate to the run, and so does
    ListStopped when the page every document starts from cannot tell which
    account it is on, since every document after this one starts there
    too. A document's own page that no longer reads as expected is False,
    for manual review."""
    out_path = Path(out_path)
    m = DOC_ID_RE.fullmatch(doc_id or "")
    if not m or (m.group(1) and m.group(2) != iso_date) or (m.group(3) and iso_date != "%s-12-31" % m.group(3)):
        if trace is not None:
            trace.append({"note": "no recorded document"})
        return False
    if is_stale(doc_id):
        if trace is not None:
            trace.append({"note": "a page recorded on another day"})
        return False
    if not m.group(1):
        # A tax year link is never pressed until its page has been
        # surveyed (TAX_PAGES_SURVEYED), so a 1099 goes to review.
        if trace is not None:
            trace.append({"note": "the tax form page is not surveyed"})
        return False
    account = account or ""
    # The page discovery began on, read the way it read it. One that cannot
    # be read raises ListStopped to the run.
    if account_of(_read(page)) != account:
        raise OtherAccount("the tab is on another account")
    try:
        if m.group(1) == HOLDINGS:
            _open_tab(page, "Current Holdings")
        elif m.group(1) == SECURITY_HISTORY:
            _open_history(page, "Security History")
        else:
            _open_history(page, "Payment History")
        html = _content(page)
        if account_of(read_page(html)) != account:
            raise OtherAccount("the page reached is of another account")
    except ListStopped as stop:
        log.info("the document could not be reached: %s", stop)
        if trace is not None:
            trace.append({"note": "stopped", "why": str(stop)[:80]})
        return False
    if not html:
        return False
    try:
        render(page, html, out_path)
    except Exception as e:
        log.info("rendering the page to a PDF failed (%s)", type(e).__name__)
        if trace is not None:
            trace.append({"note": "render failed", "error": type(e).__name__})
        return False
    return True


# ---------------------------------------------------------------------------
# Diagnose. A survey of the tab as it is, private-word-masked. Nothing is
# pressed and no screenshot is taken.
# ---------------------------------------------------------------------------

def _link_summary(link: Link) -> dict:
    href = (link.href or "").strip()
    return {
        "text": redact(link.text)[:80],
        "section": redact(link.section)[:60],
        "handler": link.handler,
        "href_kind": ("none" if not href else "script" if href.lower().startswith("javascript:")
                      else "anchor" if href.startswith("#") else "address"),
        "safe": is_safe_control(link.text),
        "handler_safe": is_safe_handler(link.handler),
        "year_link": bool(TAX_YEAR_LINK_RE.match(link.text)),
        "tax_form_link": bool(FORM_1099_LINK_RE.match(link.text)),
    }


def _page_summary(html: str, url: str) -> dict:
    page = read_page(html)
    text = _text_of(page)
    return {
        "path": redact(urlsplit(url or "").path)[:120],
        "handler": handler_of(url),
        "h1": [redact(h)[:80] for h in page.h1][:5],
        "headings": [redact(h)[:80] for h in page.headings][:40],
        "links": [_link_summary(lk) for lk in page.links][:150],
        "tax_items": [redact(it.text)[:60] for it in page.items if TAXES_SECTION_RE.match(it.section or "")][:20],
        "forms": [{"method": f.method, "section": redact(f.section)[:60],
                   "inputs": [[redact(n)[:40], t, redact(v)[:20]] for n, t, v in f.inputs][:30]}
                  for f in page.forms][:20],
        "top_tabs": _has_tabs(page),
        "tax_form_page": bool(FORM_1099_PAGE_RE.search(text)),
        "signed_out": html_says_signed_out(html, url),
        "code_page": html_asks_for_code(html),
        "password_field": page.password_field,
    }


def survey(page, dwell_ms: int = 0, max_follow: int = 0) -> dict:
    """What the tab looks like now, without pressing anything: its h1 and
    headings, every link (label masked, handler, the guards' verdicts),
    the Manage My Taxes items when shown, and every form (method, input
    names and types, button labels, never values). Open ManageDirect or a
    1099 in the tab yourself before Diagnose to survey that page.
    `max_follow` is kept for the shared signature and must stay 0: nothing
    is followed. What names the account holder is registered first."""
    if dwell_ms:
        try:
            page.wait_for_timeout(dwell_ms)
        except Exception:
            pass
    url, html = _url(page), _content(page)
    guard_private(html, url)
    return {"surveyed": SURVEYED, "pages": [_page_summary(html, url)]}


def collect_documents(page) -> List[RawDoc]:
    """Loose scrape used only by --diagnose: the tab's links, masked."""
    out = []
    for i, link in enumerate(read_page(_content(page)).links[:200]):
        text = redact(link.text)
        if text:
            out.append(RawDoc(title=text[:200], href=link.handler, text=redact(link.section)[:120], row_index=i))
    return out
