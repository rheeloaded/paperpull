"""ALL IRS Online Account selectors, URLs, and page behavior live here.

When the IRS changes its Online Account, repair this file only.

STATUS. Built from a read-only survey of a signed-in account on 2026-10-13,
with no control pressed, and corrected from a live run the same day (the
content area is div#main[role=main], not <main>, and the four transcript
types and the tax period's shape). On that account Discover then listed
26 transcripts, and a Pilot and a Run All saved all 26, every one a valid
PDF, by the plain fetch below. The transcript routes below were seen. What
was not seen is marked SURVEY NEEDED and is checked before anything is
read, so a page or answer that differs stops the list (ListStopped).
Nothing is guessed past it.
`survey(page)` prints the real structure, masked, for the run that
confirms the rest.

The Online Account is a single-page app on one host, sa.www4.irs.gov,
under /ola/. NOTHING IS EVER CLICKED HERE:

  * Transcripts. The page /ola/tax_records/transcripts draws its lists from
    GET /ola/api/shared/accounts/taxrecords/1.0/taxpayers/transcripts, a
    JSON array with one item per transcript: transcriptType (account,
    return, wageAndIncome, recordOfAccount), taxPeriod (YYYYMM), mft,
    taxForm and availableLanguages. The page's own
    "EN" link (href="#", "<year> Account Transcript PDF will open in a new
    window") makes the page GET
    /ola/api/shared/accounts/taxrecords/1.0/taxpayers/transcripts/
    {transcriptType}/{taxPeriod}/{mft}, which answered 200 application/pdf,
    and then shows that PDF as a blob in a new tab, with no download event.
    This app opens the page by its address, reads the same JSON list with
    the session's cookies, and GETs each transcript's own address built
    from that item's own fields, no redirect followed, keeping it only when
    it is a PDF. The EN link is never pressed.
  * Notices and letters. /ola/notices_and_letters said "There are no
    notices at this time." on the surveyed account, which is read as an
    empty list. Anything else there stops the list until a notice has been
    seen (SURVEY NEEDED N1-N2).
  * Information returns (/ola/information_return: W-2 rows as href="#"
    links in a per-year accordion) are not read; how they deliver a PDF
    was not seen.

Sign-in is ID.me (or Login.gov), with a one-time code, entirely the account
holder's own, in the browser. The app never opens, reads or answers a
sign-in page: a tab on one raises OtpRequired or SessionExpired, and the
run stops for the account holder. No identity host is ever an allowed host.

SAFETY (an account that can pay, set up payment plans, change an address
and request an IP PIN):
  This module is strictly READ-ONLY. It presses nothing, changes no select,
  and fills nothing. It must NEVER activate any control that pays, schedules
  or cancels a payment, sets up or revises a payment plan, adds or saves a
  bank account, requests or retrieves an IP PIN, requests a transcript by
  mail, changes an address, language or notification preference, opts into
  or out of paper or email notices, authorizes or approves a representative
  (Form 2848 / 8821), signs a form, or signs out ("Logout" is an href="#"
  link, refused by name). FORBIDDEN_CONTROL_RE is kept for the survey's
  verdicts and for any future repair that reaches for a control; a control
  must ALSO match one of the anchored document actions
  (SAFE_DOC_CONTROL_RES), and the shared core guards are consulted every
  time. A plain GET of a transcript's address is what the live run used
  (T4). Were it ever refused while the page's own EN link works, the
  fallback is a guarded press of that one EN link and taking the PDF the
  page made, which is NOT built here and would need its own review.

PRIVATE WORDS. The taxpayer's name, as the page shows it in the elements
IDENTITY_SELECTORS names, and anything on the page shaped like an SSN or
ITIN, masked or whole, with its last four digits, are registered as
private words as soon as a page that shows them is read (_guard_identity).
Nothing else is, an address or a notice's reference numbers included. No
page text goes into a log, a record or a file name, and Diagnose writes
any word that is not on PaperPull's fixed list as its shape. A
transcript's type, tax period, MFT and form are not personal and are used.

KNOWN CEILINGS (left as they are until a run shows otherwise)
  * A transcript is taken once per type, tax period and MFT. The IRS
    updates an account transcript as the account changes, so a later copy
    is not taken again (--redownload takes it).
  * Information returns (W-2, 1099) are not read.
  * Only the taxpayer signed in. Nothing here acts for anyone the account
    holder is authorized for.
"""
from __future__ import annotations

import json
import logging
import re
import sys
from dataclasses import dataclass
from datetime import date as _date
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlsplit

from paperpull_core import intake
from paperpull_core.urls import host_matches, host_of
from paperpull_core import redirects
from paperpull_core.controls import SETTINGS_CONTROL_RE, AUTH_CONTROL_RE
from paperpull_core.redact import private_words, redact, set_private_words  # noqa: F401  (re-exported)
from paperpull_core.urls import is_safe_url as _host_allows
from paperpull_core.dates import last_day as _last_day
from paperpull_core.dates import checked as _checked_date
from paperpull_core.dates import full_year as _full_year
from paperpull_core.words import words_for as _words_for
from paperpull_core.characters import whole_json

log = logging.getLogger("irs_docs.site")


def _words():
    """This app's own words for paperpull_core.words."""
    return _words_for("IRS", sys.modules[__name__])


# ---------------------------------------------------------------------------
# Addresses, as surveyed on 2026-10-13.
# ---------------------------------------------------------------------------
HOST = "sa.www4.irs.gov"
BASE = f"https://{HOST}"
HOME_PATH = "/ola/"
TRANSCRIPTS_PATH = "/ola/tax_records/transcripts"
NOTICES_PATH = "/ola/notices_and_letters"
# The transcript list the page itself asks for, and the prefix of each
# transcript's own address.
TRANSCRIPT_LIST_PATH = "/ola/api/shared/accounts/taxrecords/1.0/taxpayers/transcripts"
TRANSCRIPT_LIST_URL = BASE + TRANSCRIPT_LIST_PATH

# ===========================================================================
# SURVEY NEEDED. Seen on the surveyed account, or not, as each line says.
#
#   T1. transcriptType values: CONFIRMED live (2026-10-13), in camel case:
#       account, return, wageAndIncome, recordOfAccount. Any other value
#       stops the list.
#   T2. taxPeriod: CONFIRMED live, always six digits, YYYYMM. Any other
#       shape stops the list.
#   T3. mft: CONFIRMED live, digits ("30", "00", "29" seen).
#   T4. CONFIRMED live (2026-10-13). A plain GET of each transcript's
#       address with the session's cookies, no header added, answered the
#       PDF for all 26 transcripts, one by a Pilot and 25 by a Run All.
#   T5. CONFIRMED live: the list JSON is a plain array holding every
#       transcript (26 on the surveyed account). Anything but a list stops.
#   N1. What a notice looks like on /ola/notices_and_letters. The page also
#       asks /ola/tdc/notifications, the likely list; not read until seen.
#   N2. The wording of the empty notices page beyond the one sentence seen.
#   I1. Where the page shows the taxpayer's name (IDENTITY_SELECTORS), so it
#       is registered as a private word.
# ===========================================================================
TRANSCRIPT_TYPES: Dict[str, str] = {
    # Live (2026-10-13): the four types the listing names, in camel case.
    "account": "Account",
    "return": "Return",
    "wageAndIncome": "Wage and Income",
    "recordOfAccount": "Record of Account",
}
NO_NOTICES_RE = re.compile(r"there\s+are\s+no\s+notices\s+at\s+this\s+time\.?", re.I)
IDENTITY_SELECTORS = ["header [class*='name' i]", "[data-testid*='name' i]", "[class*='taxpayer' i]",
                      "[class*='user-name' i]"]
# ===========================================================================
# end of SURVEY NEEDED
# ===========================================================================

DOCUMENTS_URL = BASE + TRANSCRIPTS_PATH
STATEMENTS_URL = DOCUMENTS_URL
BILLING_URL = DOCUMENTS_URL
TAX_URL = DOCUMENTS_URL
NOTICES_URL = BASE + NOTICES_PATH
URLS = {
    "home": BASE + HOME_PATH,
    # A signed-out visit is sent on to the IRS sign-in, where the account
    # holder chooses ID.me and signs in.
    "login": BASE + HOME_PATH,
    "documents": DOCUMENTS_URL,
    "statements": DOCUMENTS_URL,
    "tax": DOCUMENTS_URL,
    "notices": NOTICES_URL,
}
LIST_PATHS: Dict[str, str] = {"transcript": TRANSCRIPTS_PATH, "notice": NOTICES_PATH}

# The identity hosts and the sign-in paths. A tab on any of them is signed
# out, and an ID.me page is the one-time code the account holder answers.
IDENTITY_HOSTS = ("id.me", "login.gov")
LOGIN_URL_MARKERS = ["/secureaccess/", "/login", "/signin", "/sign-in", "/oauth", "/authorize",
                     "/logout", "/sessiontimeout", "/session-expired"]

# ---------------------------------------------------------------------------
# HARD SAFETY GUARD. Tuned for the IRS account. Every stem anchored so
# "Transcript" is not "script" and "Download" is not "load".
# ---------------------------------------------------------------------------
FORBIDDEN_CONTROL_RE = re.compile(
    r"(\bpay\b|\bpaying\b|\bpayments?\b|\bpay\s*now\b|\bdirect\s+pay\b|\bpayment\s+plans?\b|"
    r"\binstallment|\bschedul(e|es|ed|ing)\b|\bbank|\bdebit\b|\bcredit\s+card\b|\bip\s*pin\b|\bpin\b|"
    r"\bauthori[sz](e|es|ed|ing|ation|ations)\b|\bapprov(e|es|ed|al)\b|\breject\b|\bpowers?\s+of\s+attorney\b|"
    r"\b2848\b|\b8821\b|\b4506|\bsign\b|\bsignature\b|\bsign\s*(in|out|off)\b|\blog\s*(in|out|off)\b|\blogout\b|"
    r"\baddress\b|\bprofile\b|\bsettings?\b|\bpreferences?\b|\blanguage\b|\bpaperless\b|\bpaper\b|"
    r"\bopt\s*-?\s*(in|out)\b|\bnotifications?\b|\balerts?\b|\bemail\b|\btext\s+message|\bmail\b|"
    r"\bby\s+mail\b|\brequest(s|ed|ing)?\b|\border\b|\bsubmit\b|\bsave\b|\bconfirm\b|\bcontinue\b|"
    r"\bnext\b|\bagree\b|\baccept\b|\bverify\b|\bpassword\b|\busername\b|\bdelet(e|es|ed|ing)\b|"
    r"\bremov(e|es|ed|ing|al)\b|\bcancel\b|\bedit(s|ed|ing)?\b|\bupdat(e|es|ed|ing)\b|\bchang(e|es|ed|ing)\b|"
    r"\bmanage\b|\brevise\b|\bupload\b|\brespond\b|\breply\b|\bshare\b|\bchat\b|\bcontact\b|\bprint\b|"
    r"\bamend\b|\bfile\b|\bfiling\b|\bextension\b|\bbalance\b|\bactivity\b|\bdetails\b|\bwallet\b)", re.I)

# The document actions this app would ever accept, anchored whole: a
# transcript's or notice's "View", "Download" or "View PDF", a bare tax year
# (a transcript link's own text), or a notice's IRS code. Nothing looser.
SAFE_DOC_CONTROL_RES = (
    re.compile(r"^(view|download)(\s+pdf)?$", re.I),
    re.compile(r"^(view|download)\s+(the\s+)?(transcript|notice|letter)(\s+pdf)?$", re.I),
    re.compile(r"^(view\s+|download\s+)?((tax\s+)?(account|return)|wage\s+(and|&)\s+income|record\s+of\s+account)"
               r"\s+transcript(\s+pdf)?$",
               re.I),
    re.compile(r"^(19|20)[0-9]{2}$"),
    re.compile(r"^(view\s+)?(cp|ltr|letter)\s?-?[0-9]{1,5}[a-z]{0,2}$", re.I),
    # The transcript list's own EN link, by its text and by its aria-label.
    re.compile(r"^en$", re.I),
    re.compile(r"^(19|20)[0-9]{2}\s+(account|return|wage\s+(and|&)\s+income|record\s+of\s+account)\s+transcript\s+pdf"
               r"\s+will\s+open\s+in\s+a\s+new\s+window$", re.I),
)

# A control that looks like it fetches a document, for the survey.
DOC_CONTROL_RE = re.compile(r"(\bpdf\b|\btranscript\b|\bnotice\b|\bletter\b|^\s*(view|download)\s*$)", re.I)

SECURITY_CHALLENGE_MARKERS = [
    "enter the code", "verification code", "two-factor", "two-step", "authenticator",
    "confirm your identity", "verify your identity", "we sent a code",
    "are you a robot", "captcha", "your session has expired", "session timed out",
    "access denied", "service unavailable", "system unavailable", "not available at this time",
]

RATE_LIMIT_MARKERS = [
    "too many requests", "rate limit", "try again later",
    "temporarily unavailable", "http error 429", "unusual traffic",
]

# Fallback selectors (used by --diagnose and the journal).
FALLBACK = {
    # Live, the account's pages have no <main>: the content area is
    # <div id="main" role="main">, so both are accepted.
    "doc_row": "[role=main] a[aria-label*='Transcript' i], main a[aria-label*='Transcript' i]",
    "doc_link": "[role=main] a[aria-label*='Transcript' i], main a[aria-label*='Transcript' i]",
    "download_control": "[role=main] a[aria-label*='Transcript' i], main a[aria-label*='Transcript' i]",
    "page_ready": "[role=main], main",
}

# ---------------------------------------------------------------------------
# Date parsing (verbatim from the SDG&E app, for --diagnose; a transcript's
# date is read by period_date below, which reads fixed shapes only)
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
    """The date this provider's page is showing, as YYYY-MM-DD, or None for
    a day that does not exist."""
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


# ---------------------------------------------------------------------------
# Session / safety
# ---------------------------------------------------------------------------

class SessionExpired(Exception):
    """The Online Account answered as a signed-out session: a sign-in page,
    an identity host, a redirect where a document was asked for, a 401 or
    403, or an HTML or JSON body where a PDF was expected. The run stops for
    the account holder."""


class OtpRequired(SessionExpired):
    """The tab is on ID.me (or Login.gov) asking for a one-time code or an
    identity check. The account holder answers it; this app never does."""


class NotLive(SessionExpired):
    """The tab this run was using is gone or cannot be read, so whether the
    session is signed in cannot be known."""


def _host(url: str) -> str:
    return host_of(url)


def on_identity_host(url: str) -> bool:
    """True for a page on ID.me or Login.gov, or any subdomain of them."""
    h = _host(url)
    return host_matches(h, IDENTITY_HOSTS)


def address_signed_out(url: str) -> bool:
    """Whether an address alone says the tab is not on a signed-in IRS page:
    an identity host, a sign-in path, or any host but the Online Account's.
    Needs nothing from the page itself."""
    u = (url or "").lower()
    return on_identity_host(u) or not is_safe_url(url or "") or any(m in u for m in LOGIN_URL_MARKERS)


def looks_signed_out(page) -> bool:
    """A sign-in page by its host or address, or a password field. A page
    whose address cannot be read raises, and is never called signed in."""
    url = (page.url or "").lower()
    if on_identity_host(url):
        return True
    if any(m in url for m in LOGIN_URL_MARKERS):
        return True
    try:
        if page.locator("input[type='password']").count() > 0:
            return True
    except Exception:
        pass
    return False


def _page_url(page) -> str:
    try:
        return page.url or ""
    except Exception as e:
        raise NotLive(f"the tab could not be read ({type(e).__name__})")


def _raise_if_signed_out(page) -> None:
    """OtpRequired on an identity host, SessionExpired on any other sign-in
    page. Nothing on either is read past its address, or touched, and
    neither is a page of another site: only a page on the Online Account's
    own host is asked whether it shows a password field."""
    url = _page_url(page)
    if on_identity_host(url):
        raise OtpRequired("the IRS sign-in (ID.me) is waiting for the account holder")
    if any(m in url.lower() for m in LOGIN_URL_MARKERS):
        raise SessionExpired("the IRS Online Account showed its sign-in page")
    if is_safe_url(url) and looks_signed_out(page):
        raise SessionExpired("the IRS Online Account showed its sign-in page")


def detect_security_challenge(page) -> Optional[str]:
    """Names the passcode, CAPTCHA, outage or throttling prompt on screen, or
    None. Visible text only. An identity host is always a challenge and its
    text is never read."""
    try:
        if on_identity_host(page.url or ""):
            return "Security challenge detected: 'ID.me sign-in'"
    except Exception:
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
    """Deny by default: an unreadable label is refused, then this app's
    blocklist, then the shared core guards, and only then the anchored
    document actions."""
    name = re.sub(r"\s+", " ", name or "").strip()
    if not name:
        return False
    if FORBIDDEN_CONTROL_RE.search(name):
        return False
    if SETTINGS_CONTROL_RE.search(name) or AUTH_CONTROL_RE.search(name):
        return False
    return any(rx.match(name) for rx in SAFE_DOC_CONTROL_RES)




# ---------------------------------------------------------------------------
# Hosts. Exact, parsed, no subdomain wildcard, and a transcript only from its
# own address.
# ---------------------------------------------------------------------------
ALLOWED_HOSTS = {HOST}

TYPE_RE = re.compile(r"[a-z][A-Za-z]{0,39}")  # live: account, return, wageAndIncome, recordOfAccount
PERIOD_RE = re.compile(r"[0-9]{6}")  # live: always YYYYMM
MFT_RE = re.compile(r"[0-9]{1,3}")
_TRANSCRIPT_PATH_RE = re.compile(
    re.escape(TRANSCRIPT_LIST_PATH) + r"/(?P<type>[A-Za-z]{1,40})/(?P<period>[0-9]{6})/(?P<mft>[0-9]{1,3})")


def is_safe_url(url: str) -> bool:
    """True only for an https URL on exactly the Online Account host."""
    return _host_allows(url, ALLOWED_HOSTS, subdomains=False)


def is_list_url(url: str) -> bool:
    """True only for the transcript list's own address, written plainly."""
    if not is_safe_url(url):
        return False
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    return parts.path == TRANSCRIPT_LIST_PATH and not parts.query and not parts.fragment


def is_download_url(url: str) -> bool:
    """True only for a transcript's own address: exactly this host, the
    list's path followed by a type, period and MFT of the right shapes, no
    query, no fragment. Also the only redirect target paperpull_core.
    redirects may follow, and it is called with no hops, so a redirect is
    handed back, never followed."""
    if not is_safe_url(url):
        return False
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    m = _TRANSCRIPT_PATH_RE.fullmatch(parts.path or "")
    return bool(m and not parts.query and not parts.fragment
                and TYPE_RE.fullmatch(m.group("type")) and PERIOD_RE.fullmatch(m.group("period"))
                and MFT_RE.fullmatch(m.group("mft")))


def download_url(transcript_type: str, period: str, mft: str) -> str:
    """A transcript's own address from its list item's fields, or "" when
    any field is not of its shape."""
    t, p, f = str(transcript_type or ""), str(period or ""), str(mft or "")
    if not (TYPE_RE.fullmatch(t) and PERIOD_RE.fullmatch(p) and MFT_RE.fullmatch(f)):
        return ""
    url = f"{TRANSCRIPT_LIST_URL}/{t}/{p}/{f}"
    return url if is_download_url(url) else ""


def period_date(period) -> Optional[str]:
    """A tax period, YYYYMM as the listing writes it, as the last day of
    that month. None for any other shape or a month that does not exist."""
    p = str(period or "")
    if not re.fullmatch(r"(19|20)[0-9]{2}(0[1-9]|1[0-2])", p):
        return None
    y, m = int(p[:4]), int(p[4:])
    return _date(y, m, _last_day(y, m)).isoformat()


# ---------------------------------------------------------------------------
# Documents. Read from the list the transcript page itself asks for;
# nothing is pressed.
# ---------------------------------------------------------------------------

@dataclass
class RawDoc:
    title: str
    account: str = ""
    date_text: str = ""
    # The transcript's own address, which carries nothing personal: its
    # type, tax period and MFT.
    href: str = ""
    text: str = ""
    row_index: int = -1
    kind: str = "doc"
    # "transcript-<transcriptType>-<taxPeriod>-<mft>", what tells two
    # transcripts apart.
    document_id: str = ""
    # What sets this transcript apart in its file name when another of the
    # same type and period is listed: its form ("1040") or its MFT ("MFT
    # 29"). Empty when it is the only one (transcripts_of).
    variant: str = ""


class ListStopped(Exception):
    """The list has a part this could not read, so what was read is not all
    of it. `docs` holds what was read before it stopped."""

    def __init__(self, why: str, docs=None):
        super().__init__(why)
        self.docs = list(docs or [])


# What would identify the taxpayer on a page: the text of the identity
# elements, and anything shaped like an SSN or ITIN. Read only to be
# registered as private words; never logged or returned past redact's word
# list.
_IDENTITY_JS = r"""(sels) => {
  const out = [];
  for (const sel of sels) {
    try { for (const el of document.querySelectorAll(sel)) out.push(el.textContent || ''); } catch (e) {}
  }
  const body = (document.body && document.body.innerText) || '';
  for (const m of body.matchAll(/\b(?:[0-9X*•]{3}-[0-9X*•]{2}-[0-9]{4}|[0-9]{9})\b/g)) out.push(m[0]);
  return out;
}"""

_SSN_RE = re.compile(r"[0-9X*•]{3}-[0-9X*•]{2}-([0-9]{4})")


def _register(words) -> None:
    """Add these words to the private words. Each is handed to the core
    whole, which keeps every part of two letters or more, as it does for
    the owner's name, so a short name part is guarded too. An SSN or ITIN,
    masked or whole, adds its last four digits as well."""
    found = []
    for w in words or []:
        w = re.sub(r"\s+", " ", str(w or "")).strip()
        for m in _SSN_RE.finditer(w):
            found += [m.group(0), m.group(1)]
        if w:
            found.append(w)
    if not found:
        return
    before = private_words()
    set_private_words(before + found)
    merged = private_words()
    # The core re-splits every word; keep each part once.
    set_private_words(list(dict.fromkeys(merged)))


def _guard_identity(page) -> None:
    """Register what names the taxpayer on this page as private words,
    beside the owner's name already there."""
    try:
        seen = page.evaluate(_IDENTITY_JS, IDENTITY_SELECTORS) or []
    except Exception as e:
        log.info("the taxpayer's details could not be read (%s)", type(e).__name__)
        return
    _register(seen if isinstance(seen, list) else [])


def _settled_on(page, kind: str) -> bool:
    url = page.url or ""
    try:
        return is_safe_url(url) and urlsplit(url).path.rstrip("/") == LIST_PATHS[kind].rstrip("/")
    except ValueError:
        return False


def _open(page, kind: str, timeout_ms: int = 30000) -> None:
    """Open one list page by its address. Raises OtpRequired or
    SessionExpired when it is a sign-in page or lands off the Online
    Account, and ListStopped when it settles elsewhere on the Online
    Account or does not draw. Registers what names the taxpayer there.
    Nothing is pressed."""
    try:
        page.goto(BASE + LIST_PATHS[kind], wait_until="domcontentloaded", timeout=60000)
    except Exception as e:
        log.info("opening the %s page failed (%s)", kind, type(e).__name__)
        _raise_if_signed_out(page)
        raise ListStopped(f"the {kind} page did not open")
    _raise_if_signed_out(page)
    if address_signed_out(_page_url(page)):
        # A signed-out visit is sent off the Online Account, to another IRS
        # host among others, so the account holder is asked to sign in again
        # rather than told the list stopped.
        raise SessionExpired(f"the {kind} page was sent off the IRS Online Account")
    if not _settled_on(page, kind):
        raise ListStopped(f"the {kind} page settled off its own address")
    try:
        page.wait_for_selector(FALLBACK["page_ready"], timeout=timeout_ms)
    except Exception:
        _raise_if_signed_out(page)
        raise ListStopped(f"the {kind} page did not finish loading")
    _guard_identity(page)


def _read_transcript_list(page) -> list:
    """The transcript list JSON, asked for by its own address with the
    session's cookies, no redirect followed. A redirect, a 401 or 403, or an
    HTML body is a signed-out session; anything else that is not a JSON
    array stops the list (T5, confirmed live)."""
    try:
        resp = redirects.get(page.context.request, TRANSCRIPT_LIST_URL, is_list_url, hops=0, timeout=60000)
    except redirects.TooManyRedirects:
        raise SessionExpired("the transcript list sent the request on")
    except Exception as e:
        log.info("asking for the transcript list failed (%s)", type(e).__name__)
        raise ListStopped("the transcript list could not be asked for")
    ctype = (resp.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
    if resp.status in redirects.REDIRECTS or resp.status in (401, 403) \
            or (resp.status == 200 and ctype.startswith("text/html")):
        _let_go(resp)
        raise SessionExpired("the IRS Online Account answered the transcript list as signed out")
    if resp.status != 200 or "json" not in ctype:
        _let_go(resp)
        raise ListStopped("the transcript list did not answer as a list")
    try:
        data = whole_json(json.loads(intake.body(resp).decode("utf-8")))
    except (ValueError, UnicodeDecodeError, intake.TooLarge):
        raise ListStopped("the transcript list did not answer as a list")
    if not isinstance(data, list):
        raise ListStopped("the transcript list is not the plain list this app was built for")
    return data


def transcripts_of(items: list) -> List[RawDoc]:
    """RawDocs from the transcript list's items. Each item's type, tax
    period and MFT must be of their shapes, its type one of the four this
    app names, its period a month, and English among its languages; one that is not, or one type,
    period and MFT twice, stops the list, carrying what was read before it.
    Nothing but those fields is read, and taxForm only to tell apart two
    transcripts of one type and period (_set_variants)."""
    docs: List[RawDoc] = []
    forms: List[str] = []
    seen = set()
    for item in items or []:
        if not isinstance(item, dict):
            raise ListStopped("a transcript list item is not one this app can read", docs)
        t, p, f = (str(item.get(k) if item.get(k) is not None else "") for k in ("transcriptType", "taxPeriod", "mft"))
        url = download_url(t, p, f)
        if not url:
            raise ListStopped("a transcript's type, tax period or MFT is not of its shape", docs)
        if t not in TRANSCRIPT_TYPES:
            raise ListStopped("a transcript of a type this app has not seen is listed", docs)
        name = TRANSCRIPT_TYPES[t]
        iso = period_date(p)
        if not iso:
            raise ListStopped("a transcript's tax period is not one this app can read", docs)
        langs = item.get("availableLanguages")
        if not isinstance(langs, list) or "en" not in [str(x).lower() for x in langs]:
            raise ListStopped("a transcript is not offered in English", docs)
        doc_id = f"transcript-{t}-{p}-{f}"
        if doc_id in seen:
            raise ListStopped("one transcript is listed twice", docs)
        seen.add(doc_id)
        title = f"IRS {name} Transcript {p}"
        docs.append(RawDoc(title=title, date_text=iso, href=urlsplit(url).path, text=title,
                           row_index=len(docs), kind="transcript", document_id=doc_id))
        forms.append(str(item.get("taxForm") or "").strip())
    _set_variants(docs, forms)
    return docs


# A listing's form as it may go into a file name, and nothing else: an IRS
# form number ("1040", "5329", "941X"), optionally " Series", or "All Forms".
# Anything else, a name or an address included, never reaches a title.
_FORM_RE = re.compile(r"[0-9]{3,4}[A-Z]{0,2}( Series)?|All Forms")


def _set_variants(docs: List[RawDoc], forms: List[str]) -> None:
    """Give each transcript that shares its type and tax period with
    another a variant for its title and file name, so two account
    transcripts of one period (one per MFT, seen live) are named apart by
    the listing's own fields rather than by a suffix added to a taken name.
    The group's forms are used when each is an IRS form name (_FORM_RE) and
    they all differ; otherwise each one's MFT. Nothing personal is in
    either."""
    groups: dict = {}
    for d, form in zip(docs, forms):
        type_period = d.document_id.rsplit("-", 1)[0]
        groups.setdefault(type_period, []).append((d, form))
    for members in groups.values():
        if len(members) < 2:
            continue
        names = [f for _, f in members]
        by_form = all(_FORM_RE.fullmatch(f) for f in names) and len({f.lower() for f in names}) == len(names)
        for d, form in members:
            d.variant = form if by_form else f"MFT {d.document_id.rsplit('-', 1)[1]}"
            d.title = d.text = f"{d.title} {d.variant}"


# Read only: the visible text of the main area and a count of the links and
# buttons in it that look like documents.
NOTICES_SETTLE_MS = 15000

_NOTICES_JS = r"""() => {
  const main = document.querySelector('[role=main]') || document.querySelector('main');
  if (!main) return null;
  let docs = 0;
  for (const el of main.querySelectorAll('a, button, [role=button]')) {
    const t = ((el.textContent || '') + ' ' + (el.getAttribute('aria-label') || '')).replace(/\s+/g, ' ');
    // Live, the empty page's one link is "View your profile" (paperless
    // settings), which is not a document.
    if (/\bview your profile\b/i.test(t)) continue;
    if (/\b(pdf|view|download|notice|letter|cp ?[0-9]|ltr ?[0-9])\b/i.test(t)) docs += 1;
  }
  return {text: (main.innerText || '').replace(/\s+/g, ' ').slice(0, 4000), docs: docs};
}"""


# What a notice would put on the page in any markup: its IRS code or a date.
# Either beside the empty sentence means the page is not the empty one seen.
_NOTICE_CODE_RE = re.compile(r"\b(CP|LTR|Letter)\s?-?[0-9]{1,5}[A-Z]{0,2}\b", re.I)
_A_DATE_RE = re.compile(r"\b[0-9]{1,2}/[0-9]{1,2}/[0-9]{2,4}\b|"
                        r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+[0-9]{1,2},\s+[0-9]{4}\b", re.I)


def notices_of(seen) -> List[RawDoc]:
    """The notices page as read. Only the empty page has been seen: its one
    sentence, no document-looking link or button, and no notice code or
    date anywhere in its main text. Anything else stops
    the list until a notice has been seen (SURVEY NEEDED N1-N2); the page's
    words are never said."""
    if not isinstance(seen, dict):
        raise ListStopped("the notices page has no main area")
    text = str(seen.get("text") or "")
    if NO_NOTICES_RE.search(text) and not seen.get("docs") \
            and not _NOTICE_CODE_RE.search(text) and not _A_DATE_RE.search(text):
        return []
    raise ListStopped("the notices page lists something this app has not seen yet")


def _transcripts(page) -> List[RawDoc]:
    _open(page, "transcript")
    return transcripts_of(_read_transcript_list(page))


def _notices(page) -> List[RawDoc]:
    """The notices page, given time to draw: the page is a script that
    fills its main area after the frame is up, so it is read again, up to
    NOTICES_SETTLE_MS, until the empty sentence or a document shows."""
    _open(page, "notice")
    seen = None
    waited = 0
    while True:
        try:
            seen = page.evaluate(_NOTICES_JS)
        except Exception as e:
            log.info("reading the notices page failed (%s)", type(e).__name__)
            seen = None
        if isinstance(seen, dict) and (seen.get("docs") or NO_NOTICES_RE.search(str(seen.get("text") or ""))):
            break
        if waited >= NOTICES_SETTLE_MS:
            break
        page.wait_for_timeout(500)
        waited += 500
    return notices_of(seen)


def goto_documents(page) -> bool:
    """Open the transcript page by its address. False when it showed a
    sign-in page, settled elsewhere, or did not draw."""
    try:
        _open(page, "transcript")
        return True
    except (SessionExpired, ListStopped) as e:
        log.info("the transcript page did not open: %s", e)
        return False


def bill_list_opens(page, notices: bool = True) -> bool:
    """Whether the lists opened and could be read whole, which only a
    signed-in page allows. The notices page is one of them only when
    `notices` is true, as for collect_download_docs."""
    try:
        collect_download_docs(page, notices=notices)
        return True
    except (SessionExpired, ListStopped) as e:
        log.info("the IRS lists could not be read: %s", e)
        return False


def scroll_full_page(page, rounds: int = 8, delay_ms: int = 600) -> None:
    try:
        for _ in range(rounds):
            page.mouse.wheel(0, 3000)
            page.wait_for_timeout(delay_ms)
    except Exception:
        pass


def expand_all(page) -> None:
    """Nothing to press: the transcript list is read whole from its JSON,
    so "Show more transcripts" is never needed."""
    return None


def collect_download_docs(page, notices: bool = True) -> List[RawDoc]:
    """Every transcript, then the notices. Nothing is pressed. A list that
    will not open or cannot be read raises ListStopped holding everything
    read before it, and a signed-out account raises SessionExpired (or
    OtpRequired).

    The notices page is opened only when `notices` is true, which the app
    asks only when notices are in scope ("Other Document" in its
    document_types). Any notice there stops the list until one has been
    seen, so a person who keeps notices out of scope is never stopped by
    one."""
    docs = _transcripts(page)
    if not notices:
        return docs
    try:
        docs += _notices(page)
    except ListStopped as stop:
        raise ListStopped(str(stop), docs + stop.docs)
    return docs


def _fetch(page, url: str, out_path: Path, trace: Optional[list]) -> bool:
    """GET the document's own address with the session's cookies, no
    redirect followed, and keep it only when it is a PDF (application/pdf
    and a body starting %PDF). A redirect, a 401 or 403, or an HTML or JSON
    body is the account saying the session has ended."""
    if not is_download_url(url):
        if trace is not None:
            trace.append({"note": "document address refused"})
        return False
    try:
        resp = redirects.get(page.context.request, url, is_download_url, hops=0, timeout=60000)
    except redirects.TooManyRedirects:
        raise SessionExpired("the document's address sent the request on")
    except Exception as e:
        log.info("fetching the document failed (%s)", type(e).__name__)
        if trace is not None:
            trace.append({"note": "fetch failed", "error": type(e).__name__})
        return False
    ctype = (resp.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
    if trace is not None:
        trace.append({"note": "fetched", "host": HOST, "status": resp.status, "type": ctype[:30]})
    if resp.status in redirects.REDIRECTS or resp.status in (401, 403) \
            or (resp.status == 200 and (ctype.startswith("text/") or "json" in ctype)):
        _let_go(resp)
        raise SessionExpired("the IRS Online Account answered a document with a sign-in response")
    if resp.status != 200 or ctype != "application/pdf":
        _let_go(resp)
        return False
    try:
        body = intake.body(resp)
    except intake.TooLarge:
        return False
    if body[:5] != b"%PDF-":
        if body.lstrip()[:1] in (b"<", b"{", b"["):
            raise SessionExpired("the IRS Online Account answered a document with a sign-in body")
        return False
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(body)
    return True


def _let_go(resp) -> None:
    try:
        resp.dispose()
    except Exception:
        pass




_DOC_ID_RE = re.compile(r"transcript-([a-z][A-Za-z]{0,39})-([0-9]{6})-([0-9]{1,3})")


def download_bill(page, dl_dir, iso_date: str, out_path, title: str = "",
                  trace: Optional[list] = None, href: str = "",
                  document_id: str = "") -> bool:
    """Save the transcript discovery recorded with id `document_id`, dated
    `iso_date`, at address path `href`. The list is asked for again and the
    transcript is fetched only when exactly one item there still carries
    that same id, date and address. `dl_dir` is unused, since nothing here
    goes through the browser's downloads. Nothing is pressed.

    A list that no longer holds the record answers False, so the record
    goes to review and the run goes on. The IRS keeps each kind of
    transcript online for a window of years that moves forward every year,
    so a transcript discovery recorded and no run has saved yet can drop
    off the list, and that is this record's matter alone. SessionExpired
    propagates to the run, and so does ListStopped when the list cannot be
    read again or holds the record more than once."""
    out_path = Path(out_path)
    doc_id = (document_id or "").strip()
    if not _DOC_ID_RE.fullmatch(doc_id) or not is_download_url(BASE + (href or "")):
        log.info("no transcript address was recorded for this document")
        if trace is not None:
            trace.append({"note": "no recorded document"})
        return False
    try:
        found = [d for d in _transcripts(page)
                 if d.document_id == doc_id and d.date_text == (iso_date or "") and d.href == href]
    except ListStopped as stop:
        log.info("the transcript list stopped while looking for the one dated %s: %s", iso_date, stop)
        raise
    if not found:
        log.info("the transcript list no longer holds the recorded transcript dated %s", iso_date)
        if trace is not None:
            trace.append({"note": "the record is gone from the list", "matches": 0})
        return False
    if len(found) != 1:
        log.info("%d items match the recorded transcript dated %s, none taken", len(found), iso_date)
        if trace is not None:
            trace.append({"note": "no single item matches the record", "matches": len(found)})
        # One record listed twice is a list this app cannot read, so the run
        # stops rather than choose between them.
        raise ListStopped("the transcript list holds the record more than once")
    return _fetch(page, BASE + found[0].href, out_path, trace)


# ---------------------------------------------------------------------------
# Diagnose and survey. Loose, redacted, and pressing nothing. No screenshot.
# ---------------------------------------------------------------------------
_ROW_JS = r"""() => {
  const out = [];
  for (const tr of document.querySelectorAll('table tr, [role=row], [role=main] li, main li')) {
    const txt = (tr.innerText || '').trim();
    if (!txt) continue;
    const link = tr.querySelector("a[href]");
    out.push({text: txt.slice(0, 200), href: link ? link.getAttribute('href') : ''});
  }
  return out.slice(0, 200);
}"""

SURVEY_LINK_RE = re.compile(r"^\s*(records\s+(and|&)\s+status|tax\s+records|transcripts?|"
                            r"notices\s+(and|&)\s+letters|get\s+transcript)\s*$", re.I)


def collect_documents(page) -> List[RawDoc]:
    """Loose row scrape used only by --diagnose, redacted."""
    docs: List[RawDoc] = []
    seen = set()
    try:
        rows = page.evaluate(_ROW_JS)
    except Exception:
        rows = []
    for i, r in enumerate(rows or []):
        text = redact((r.get("text") or "").strip())
        if not text:
            continue
        has_date = parse_date(text) or MONTH_YEAR_RE.search(text)
        href = redact((r.get("href", "") or "").split("?", 1)[0])
        if not (has_date or href or "download" in text.lower()):
            continue
        title = text.splitlines()[0][:200]
        key = (title, href, text[:60])
        if key in seen:
            continue
        seen.add(key)
        docs.append(RawDoc(title=re.sub(r"\s+", " ", title), href=href, text=text[:400], row_index=i))
    return docs


def _path_shape(url: str) -> str:
    """An address as its host and path with every digit run and every long
    token written as its shape, and the query as its parameter names only,
    so the survey can name the real document addresses without carrying a
    taxpayer's reference."""
    try:
        parts = urlsplit(url or "")
    except ValueError:
        return ""
    path = re.sub(r"[0-9]+", lambda m: "9" * len(m.group(0)), parts.path or "")
    path = re.sub(r"[A-Za-z0-9_-]{24,}", "<token>", path)
    names = sorted({kv.split("=", 1)[0] for kv in (parts.query or "").split("&") if kv})
    return f"{parts.hostname or ''}{path}" + (f"?{'&'.join(n + '=' for n in names)}" if names else "")


def _page_summary(page) -> dict:
    out = {"url": _path_shape(page.url or ""), "title": ""}
    try:
        out["title"] = redact(page.title() or "")
    except Exception:
        pass
    try:
        heads = page.locator("h1, h2, h3, h4").all_inner_texts()
        out["headings"] = [redact(h.strip())[:80] for h in heads if h.strip()][:40]
    except Exception:
        out["headings"] = []
    controls = []
    for role in ("link", "button", "tab", "menuitem"):
        try:
            loc = page.get_by_role(role)
            for i in range(min(loc.count(), 150)):
                el = loc.nth(i)
                try:
                    text = (el.inner_text(timeout=300) or "").strip()
                except Exception:
                    text = ""
                aria = ""
                try:
                    aria = (el.get_attribute("aria-label") or "").strip()
                except Exception:
                    pass
                if not (text or aria):
                    continue
                href = ""
                if role == "link":
                    try:
                        href = el.get_attribute("href") or ""
                    except Exception:
                        pass
                    if href and not href.startswith("http"):
                        href = BASE + href if href.startswith("/") else href
                label = text or aria
                controls.append({"role": role, "text": redact(label)[:60],
                                 "aria": redact(aria)[:60],
                                 "href_shape": _path_shape(href)[:160] if href else "",
                                 "transcript_address": is_download_url(href) if href else False,
                                 "safe": is_safe_control(label),
                                 "looks_like_document": bool(DOC_CONTROL_RE.search(label)),
                                 "survey": bool(SURVEY_LINK_RE.match(label))})
        except Exception:
            pass
    out["controls"] = controls
    out["document_controls"] = sum(1 for c in controls if c["looks_like_document"])
    out["document_links_of_the_expected_shape"] = sum(1 for c in controls if c["transcript_address"])
    return out


def survey(page, dwell_ms: int = 4000, max_follow: int = 0) -> dict:
    """What the signed-in Online Account shows, without downloading or
    pressing anything: for the transcript page, the list's items by their
    non-personal fields (type, the shape of the period, MFT, form,
    languages) and what this app reads of them; for the notices page,
    whether it shows the empty sentence and how many document-looking
    controls it has; and for each, every control with the guard's verdict
    and the shape of its address. A sign-in page or an ID.me page is
    reported as such and not read. This is what the run that settles the
    SURVEY NEEDED block runs. No screenshot."""
    report = {"pages": [], "assumptions": "irs_site.py SURVEY NEEDED N1-N2, I1"}
    for kind in ("transcript", "notice"):
        entry = {"list": kind, "expected": HOST + LIST_PATHS[kind]}
        try:
            _open(page, kind)
            entry["opened"] = True
            if kind == "transcript":
                items = _read_transcript_list(page)
                entry["items"] = len(items)
                entry["item_fields"] = sorted({k for i in items if isinstance(i, dict) for k in i})[:20]
                entry["types"] = sorted({str(i.get("transcriptType"))[:30] for i in items if isinstance(i, dict)})
                entry["period_shapes"] = sorted({re.sub(r"[0-9]", "9", str(i.get("taxPeriod")))[:12]
                                                 for i in items if isinstance(i, dict)})
                entry["mfts"] = sorted({str(i.get("mft"))[:4] for i in items if isinstance(i, dict)
                                        if MFT_RE.fullmatch(str(i.get("mft")))})
                entry["forms"] = sorted({str(i.get("taxForm"))[:12] for i in items if isinstance(i, dict)
                                         if re.fullmatch(r"[0-9A-Z-]{1,12}", str(i.get("taxForm")))})
                try:
                    entry["documents_read"] = len(transcripts_of(items))
                except ListStopped as stop:
                    entry["documents_read"] = len(stop.docs)
                    entry["stopped"] = str(stop)
            else:
                seen = page.evaluate(_NOTICES_JS)
                entry["says_no_notices"] = bool(isinstance(seen, dict) and NO_NOTICES_RE.search(str(seen.get("text") or "")))
                entry["document_controls"] = (seen or {}).get("docs") if isinstance(seen, dict) else None
        except OtpRequired:
            entry["opened"] = False
            entry["stopped"] = "ID.me sign-in is waiting"
            report["pages"].append(entry)
            return report
        except (SessionExpired, ListStopped) as e:
            entry["opened"] = entry.get("opened", False)
            entry["stopped"] = str(e)
        page.wait_for_timeout(dwell_ms)
        try:
            if not on_identity_host(page.url or ""):
                entry["page"] = _page_summary(page)
        except Exception:
            pass
        report["pages"].append(entry)
    return report
