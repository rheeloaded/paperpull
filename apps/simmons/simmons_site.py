"""ALL login.simmonsbank.com selectors, URLs and page behavior live here.

When Simmons Bank changes its online banking, repair this file only.

STATUS: built from the account owner's read-only survey of a signed-in
account on 2026-10-15, then run live on it the same day: Discover listed
the 27 documents, Pilot and Run All saved them all as the browser's own
downloads, Verify found no problem. What the survey saw is below. The run
settled what KNOWN CEILINGS listed as unseen, except where it says so, and
showed the PDFs date themselves a day or three after the list does (see
pdf_names_document and nearby_date_offset).

WHAT THE SURVEY ESTABLISHED
  * Simmons Bank's online banking is Banno, Jack Henry's web app, at
    https://login.simmonsbank.com. Every control on it is drawn inside open
    shadow roots of its web components (bannoweb-*, jha-*). The page's own
    document.body.innerText sees none of it, while Playwright's locators
    reach into open shadow roots, so every read here is a locator.
  * The account surveyed has one account at the bank, a paid-off mortgage
    ("RE ARM <number>"), and the bank keeps a paid-off loan's documents for
    a while after it closes: its accounts answer names that date as
    closedAccountAvailableUntil.
  * The documents page is https://login.simmonsbank.com/documents, opened by
    its address. Loading it makes the page ask
    GET /a/consumer/api/v0/users/<userId>/documents/all?startDate=YYYY-MM-DD,
    answered {"documents": [{"documentId", "documentType" (statement,
    notice or tax), "documentTitle", "description", "date", "documentFilename",
    "accountIds": [<the account>]}, ...]}. startDate is the bank's own
    documentStartDate (GET .../documents/settings/institution), and asking
    the same address from that date gave the same 27 documents, so the
    answer is the whole list the bank offers.
  * The page draws one <jha-list-item role=listitem> per document holding a
    <button> whose text is "<documentTitle> <Type>, RE ARM <number>
    (x<last4>)", the Type Statement, Notice or Tax. 27 rows live, newest
    first. Above them sit an enrollment card (Go paperless, Notify at,
    Enroll all accounts, Enroll, Accept, OK) and a filter menu (Type, Year,
    Accounts, Clear all, Apply). None of those is ever pressed.
  * Pressing a row's button makes the page GET
    /a/consumer/api/users/<userId>/documents/<documentId>, a PDF sent as an
    attachment named the document's documentFilename, which the page turns
    into a Blob, and the browser then raises a download at
    blob:https://login.simmonsbank.com/<uuid> with that same suggested file
    name. No tab opens and the page stays on /documents.

HOW A DOCUMENT IS TAKEN
  The documents page is loaded afresh by its address before every press,
  with a listener on the browser context already hearing the page's own
  answers, and the list is read whole again (read_listing). The record is
  bound to exactly one document of that answer by a hash of its documentId
  and its date, and that document to exactly one row by the row's whole
  text, its title, its type word and the one account. That row's button
  alone is pressed, once, through the core's press_once. The download is
  taken only when it is the one download the press brought, its address is
  a Blob of login.simmonsbank.com, and its suggested file name is the
  document's own documentFilename. When no download comes, the exact
  address the page itself asked for that documentId is asked once more with
  the browser's cookies and no redirect followed. Which way the PDF came is
  said in the trace. The bytes must then be a PDF whose text names the
  document (pdf_names_document), or the file is put aside for review.

THE ONE PRESS. A document row's own button, chosen by is_document_row: the
  whole row text must be the row heard for the bound document, title from
  the bank's own answer, type word and the one account, and the part that is
  not the bank's title must pass this module's blocklist and the core's
  settings and sign-in guards. Accept, Enroll, OK, Notify, the filter menu,
  Apply, Clear all, every navigation link, Sign out, Transfers, Zelle, Bill
  pay, the links that open another service and everything else are refused
  (FORBIDDEN_CONTROL_RE, is_safe_control).

THE LIST IS KEPT WHOLE. One answer (two that differ stop), holding nothing
  but its documents, each with a documentId of the expected shape, a known
  type, a title, a calendar date, a PDF file name and exactly one account,
  no documentId twice, one account across the whole list, every document on
  or after the startDate the page asked from, that startDate the bank's own
  when its settings answer was heard, and the rows drawn naming exactly the
  answer's titles and types, as many as the answer holds, all of one
  account, read twice alike. Anything else stops the list.

PRIVACY. The userId, every documentId and accountId, every documentFilename,
  the account's name and number and last four, the owner's name in the user
  menu and every Blob address are private words the moment they are read.
  None of them is logged, said, written to a record or a file name. A record
  keeps a hash of the documentId (record_hash), never the id.

SIGNED OUT. A sign-in address (LOGIN_PATHS), a password field, or a 401,
  403, redirect or HTML answer to the page's own list call raises
  SessionExpired. The run saves, says so and stops.

KNOWN CEILINGS (what the first run was to confirm, and did unless noted)
  * One account. A list naming two accountIds, rows naming two accounts, or
    an accounts answer holding more than the one stops the list.
  * Every row is drawn on /documents (27 live). A page that drew only some
    of them would show as rows not matching the answer, and stops.
  * The press inside shadow roots relies on the core reading what is on top
    of a control through shadow hosts (pressing.look).
  * The PDF text each family prints is unseen (pdf_names_document).
  * The download landing under its suggested name on the attached Chrome
    was seen through the survey's probe, not through this app.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import date as _date
from datetime import timedelta as _timedelta
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import parse_qsl, urlsplit

from paperpull_core import pdf_reader
from paperpull_core import intake
from paperpull_core import pressing
from paperpull_core import redirects
from paperpull_core.controls import SETTINGS_CONTROL_RE, AUTH_CONTROL_RE
from paperpull_core.redact import private_words, redact, set_private_words  # noqa: F401  (re-exported)
from paperpull_core.urls import is_safe_url as _host_allows
from paperpull_core.dates import last_day as _last_day
from paperpull_core.dates import checked as _checked_date
from paperpull_core.dates import full_year as _full_year
from paperpull_core.identity import VERIFIED, Identity, date_variants, on_its_own, verify
# re-exported: the docs module calls it as site.set_download_dir
from paperpull_core.capture import set_download_dir  # noqa: F401
from paperpull_core.capture import snapshot as _snapshot
from paperpull_core.capture import take_download as _take_download
from paperpull_core.capture import clear_copies as _clear_copies
from paperpull_core.capture import arrived as _arrived
from paperpull_core.words import words_for as _words_for
from paperpull_core.characters import whole_characters, whole_json

log = logging.getLogger("simmons_docs.site")

PROVIDER = "Simmons Bank"


def _words():
    """This app's own words for paperpull_core.words."""
    return _words_for(PROVIDER, sys.modules[__name__])


# ---------------------------------------------------------------------------
# Addresses
# ---------------------------------------------------------------------------
HOST = "login.simmonsbank.com"
BASE = f"https://{HOST}"
DOCUMENTS_PATH = "/documents"
DOCUMENTS_URL = BASE + DOCUMENTS_PATH
STATEMENTS_URL = DOCUMENTS_URL
BILLING_URL = DOCUMENTS_URL
URLS = {
    "home": f"{BASE}/",
    # A signed-out visit shows the bank's sign-in, where the account holder
    # signs in.
    "login": f"{BASE}/",
    "documents": DOCUMENTS_URL,
    "statements": DOCUMENTS_URL,
}

# The first part of a sign-in or signed-out address on the host. An address
# is read by its first path part, never by a substring.
LOGIN_PATHS = {"login", "auth", "logout", "sign-in", "signin"}
LOGIN_URL_MARKERS = sorted("/" + part for part in LOGIN_PATHS)

_UUID = r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}"
UUID_RE = re.compile(_UUID)
_LIST_PATH_RE = re.compile(r"/a/consumer/api/v0/users/(" + _UUID + r")/documents/all")
_ACCOUNTS_PATH_RE = re.compile(r"/a/consumer/api/users/(" + _UUID + r")/accounts")
_INSTITUTION_PATH_RE = re.compile(r"/a/consumer/api/users/(" + _UUID
                                  + r")/documents/settings/institution")
# The PDF the press makes the page ask for. No /v0/ here, and the last part
# is a documentId, so documents/all, settings and disclosures are never
# taken for one.
_PDF_PATH_RE = re.compile(r"/a/consumer/api/users/(" + _UUID + r")/documents/(" + _UUID + r")")
_BLOB_RE = re.compile(r"blob:https://login\.simmonsbank\.com/(" + _UUID + r")")

# ---------------------------------------------------------------------------
# HARD SAFETY GUARD. Every stem anchored. The words of a document row ("Loan",
# "Statement", "Notice", "Tax", "Reporting", "RE ARM") are not on it.
# ---------------------------------------------------------------------------
FORBIDDEN_CONTROL_RE = re.compile(
    r"(\baccept(s|ed|ing)?\b|\benroll|\bunenroll|\bnotify\b|\bnotifications?\b|\bok\b|"
    r"\bapply\b|\bclear\b|\bfilters?\b|\bsign\s*(out|off|in|up)\b|\blog\s*(out|off|in|on)\b|"
    r"\blogout\b|\blogin\b|\btransfers?\b|\btransferring\b|\bzelle\b|\bbill\s*pay\b|\bpay\b|"
    r"\bpays\b|\bpaying\b|\bpayments?\b|\bdeposits?\b|\bremote\b|\bmessages?\b|\bdashboard\b|"
    r"\baccounts\b|\bsupport\b|\bhelp\b|\bsettings?\b|\bpreferences?\b|\brefer\b|\bfriends?\b|"
    r"\bopen\s+a\s+new\b|\bnew\s+account\b|\bdirect\s+deposit\b|\bswitch\b|\bskip\b|\bback\b|"
    r"\bmenu\b|\bprivacy\b|\breorder|\bchecks?\b|\bstop\b|\bsubmit\b|\bconfirm\b|\bcontinue\b|"
    r"\bagree\b|\bauthori[sz]e\b|\bpaperless\b|\bdelivery\b|\bemail\b|\bdisclosures?\b|"
    r"\bterms\b|\bsend\b|\bmoney\b|\bprofile\b|\bcall\b|\bphone\b|\bchat\b|\bclose\b|"
    r"\bcancel\b|\bsave\b|\bdelet(e|es|ed|ing)\b|\bremov(e|es|ed|ing|al)\b|\bedit(s|ed|ing)?\b|"
    r"\bupdat(e|es|ed|ing)\b|\bmanage\b|\bloss\s+mitigation\b|\bapplication\b|\bdispute\b|"
    r"\bverify\b|\bpassword\b|\bpasscode\b|\buser\b)", re.I)

# What is_safe_control takes, whole: a document row's own text, or a plain
# document action ("View statement", "Download PDF", "Loan Statement").
_TYPE_WORDS = {"statement": "Statement", "notice": "Notice", "tax": "Tax"}
ROW_RE = re.compile(r"(?P<title>.+) (?P<type>Statement|Notice|Tax), "
                    r"(?P<acct>(?P<name>[^,()]+?) \(x(?P<last4>[0-9]{4})\))")
# A button whose text ends like a row's, read to tell a row this cannot read
# from a control that is no row at all.
ROW_TAIL_RE = re.compile(r"\(x[0-9]{4}\)\s*$")
SAFE_DOC_CONTROL_RE = re.compile(
    r"(?:(?:view|download|open)\s+)?(?:loan\s+)?(?:statements?|notices?|tax\s+reporting|"
    r"tax\s+forms?|tax\s+documents?|documents?|pdf)", re.I)

SECURITY_CHALLENGE_MARKERS = [
    "enter the code", "verification code", "6-digit", "two-factor",
    "two-step", "authenticator", "confirm your identity", "verify your identity",
    "we sent a code", "one-time passcode", "are you a robot", "captcha",
    "check your email", "check your phone", "access denied",
]

RATE_LIMIT_MARKERS = [
    "too many requests", "rate limit", "try again later",
    "temporarily unavailable", "http error 429", "unusual traffic",
]

ROW_HOST = "jha-list-item"
FALLBACK = {
    "doc_row": ROW_HOST,
    "doc_link": ROW_HOST + " button",
    "download_control": ROW_HOST + " button",
    "page_ready": "bannoweb-documents",
}

LIST_WAIT_MS = 30000
SETTLE_MS = 1500
POLL_MS = 250
DOWNLOAD_WAIT_MS = 60000
# How long a capture waits, once a download has come, for a second one. One
# press of one row hands over one PDF, so a second download means one of the
# two is not this press's, and neither is taken.
SECOND_DOWNLOAD_WAIT_MS = 3000

# ---------------------------------------------------------------------------
# Date parsing, the same general reader the other apps carry. The documents
# themselves are dated by their answer's own date (answer_date).
# ---------------------------------------------------------------------------
DATE_PATTERNS = [
    (re.compile(r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
                r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|"
                r"Dec(?:ember)?)\.?\s+(\d{1,2}),?\s+(\d{4})", re.I), "mdY"),
    (re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b"), "mdy_slash"),
    (re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{2})\b"), "mdy_slash2"),
    (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})(?!\d)"), "iso"),
]
_MONTH_NAMES = ("January", "February", "March", "April", "May", "June", "July", "August",
                "September", "October", "November", "December")
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
    """The date this provider's page is showing, as YYYY-MM-DD. A result
    naming a day that does not exist is refused."""
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


_ISO_RE = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})")


def answer_date(text) -> Optional[str]:
    """An answer's date as YYYY-MM-DD, or None. The whole value must be the
    date, written YYYY-MM-DD, and the day must exist."""
    if not isinstance(text, str):
        return None
    m = _ISO_RE.fullmatch(text)
    if not m:
        return None
    try:
        return _date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# The three families, and what each file is called
# ---------------------------------------------------------------------------
_MONTH_RE = "(%s)" % "|".join(_MONTH_NAMES)
# A title's own month and year at its end, "Prime Rate Notice August 2026".
_TITLE_MONTH_RE = re.compile(r"^(?P<words>.+?) " + _MONTH_RE + r" (?P<year>(?:19|20)[0-9]{2})$")
STATEMENT_TITLE_RE = re.compile(r"^Loan Periodic Statement " + _MONTH_RE + r" ((?:19|20)[0-9]{2})$")
# Live the title begins with the form, "1098 Tax Reporting January 2026". A
# title may also begin with the tax year itself.
TAX_TITLE_RE = re.compile(r"^(1098|(?:19|20)[0-9]{2}) Tax Reporting " + _MONTH_RE + r" ((?:19|20)[0-9]{2})$")


def tax_year(title: str) -> str:
    """The calendar year a tax form reports: the year its title begins
    with, or, when it begins with the form number instead, the year before
    the one it was issued in (a January 1098 reports the year just ended).
    "" for a title of another shape."""
    m = TAX_TITLE_RE.match(_tidy(title))
    if not m:
        return ""
    if m.group(1) == "1098":
        return str(int(m.group(3)) - 1)
    return m.group(1)

KINDS = ("statement", "notice", "tax")
STATEMENT_SUMMARY = "Loan Statement"
TAX_SUMMARY = "Tax Reporting"
NOTICE_SUMMARY = "Notice"


def _tidy(text) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def summary_for(kind: str, title: str) -> str:
    """What the file of a document of `kind` titled `title` is called after
    its date and "Simmons Bank": "Loan Statement" for a statement, "Notice -
    <its title without its month and year>" for a notice, "Tax Reporting
    <the year the title begins with>" for a tax form. A title that does not
    have its family's shape keeps the family's plain name, or for a notice
    its whole title."""
    title = _tidy(title)
    if kind == "statement":
        return STATEMENT_SUMMARY
    if kind == "tax":
        year = tax_year(title)
        return "%s %s" % (TAX_SUMMARY, year) if year else TAX_SUMMARY
    m = _TITLE_MONTH_RE.match(title)
    words = m.group("words") if m else title
    words = re.sub(r"[.!?]+$", "", words).strip()
    if len(words) > 60:
        words = words[:60].rsplit(" ", 1)[0]
    return "%s - %s" % (NOTICE_SUMMARY, words) if words else NOTICE_SUMMARY


def title_period(title: str) -> str:
    """The month a title names at its end, YYYY-MM, or ""."""
    m = _TITLE_MONTH_RE.match(_tidy(title))
    if not m:
        return ""
    return "%s-%02d" % (m.group("year"), _MONTH_NAMES.index(m.group(2)) + 1)


def record_hash(document_id: str) -> str:
    """A stable, non-reversible name for a documentId, which a record keeps
    in its place. The id itself is never written anywhere."""
    return hashlib.sha256(("simmons\0%s" % (document_id or "")).encode("utf-8")).hexdigest()


RECORD_HASH_RE = re.compile(r"[0-9a-f]{64}")

# ---------------------------------------------------------------------------
# Session / safety
# ---------------------------------------------------------------------------


class SessionExpired(Exception):
    """Simmons Bank answered as a signed-out session: its sign-in page, a
    password field, or a 401, 403, redirect or HTML answer to the page's own
    list call. The run stops for the account holder."""


class ListStopped(Exception):
    """The list has a part this could not read, so what was read is not all
    of it. `docs` holds what was read before it stopped. Its words are this
    module's own, never the page's."""

    def __init__(self, why: str, docs=None):
        super().__init__(why)
        self.docs = list(docs or [])


def _first_part(url: str) -> str:
    try:
        path = urlsplit(url or "").path
    except ValueError:
        return ""
    return (path.strip("/").split("/", 1)[0] or "").lower()


def looks_signed_out(page) -> bool:
    """A sign-in or signed-out address on the bank's host (LOGIN_PATHS), or
    a password field."""
    url = page.url or ""
    if _host_of(url) == HOST and _first_part(url) in LOGIN_PATHS:
        return True
    try:
        if page.locator("input[type='password']").count() > 0:
            return True
    except Exception:
        pass
    return False


def check_signed_in(page) -> None:
    """Raise SessionExpired when the page shows the bank's sign-in. Asked
    before and after every wait and the press."""
    if looks_signed_out(page):
        raise SessionExpired("Simmons Bank showed its sign-in page")


def detect_security_challenge(page) -> Optional[str]:
    """Names the passcode, CAPTCHA or throttling prompt on screen, or None.
    A page that shows a document row is not a challenge. The page's text is
    mostly inside shadow roots, so this reads what the body shows and is a
    hint only. The sign-in itself is the account holder's, in the window."""
    try:
        if page.locator(FALLBACK["doc_row"]).count() > 0:
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


def _refused(name: str) -> bool:
    return bool(FORBIDDEN_CONTROL_RE.search(name) or SETTINGS_CONTROL_RE.search(name)
                or AUTH_CONTROL_RE.search(name))


def _parts(name) -> List[str]:
    """Each label a control carries, as press_once joins them with " | "."""
    return [_tidy(p) for p in str(name or "").split(" | ")]


def is_safe_control(name: str) -> bool:
    """Deny by default: every label the control carries must be readable,
    pass this app's blocklist and the shared core guards, and then be, whole,
    a document row's text or a plain document action. What the core's tests
    and the survey ask about. The press itself asks is_document_row."""
    parts = _parts(name)
    if not parts or any(not p for p in parts):
        return False
    for p in parts:
        if _refused(p):
            return False
        if not (ROW_RE.fullmatch(p) or SAFE_DOC_CONTROL_RE.fullmatch(p)):
            return False
    return True


def is_document_row(name, want: str) -> bool:
    """The press's own guard: every label the control carries is exactly
    `want`, the row text heard for the bound document, which is the bank's
    own title of it, its type word and the one account. The title is the
    bank's name for one of its documents, which can carry a word the
    blocklist holds ("Notice of Address Change"), so the blocklist and the
    core guards are asked about the rest of the row, the type word and the
    account, which must pass them. Refused with no `want`."""
    want = _tidy(want)
    m = ROW_RE.fullmatch(want)
    if not want or not m:
        return False
    rest = "%s, %s" % (m.group("type"), m.group("acct"))
    if _refused(rest):
        return False
    parts = _parts(name)
    return bool(parts) and all(p == want for p in parts)


# ---------------------------------------------------------------------------
# Hosts. Exact, parsed, no subdomain wildcard.
# ---------------------------------------------------------------------------
ALLOWED_HOSTS = {HOST}


def is_safe_url(url: str) -> bool:
    """True only for an https URL on exactly login.simmonsbank.com."""
    return _host_allows(url, ALLOWED_HOSTS, subdomains=False)


def _host_of(url) -> str:
    try:
        return (urlsplit(url or "").hostname or "").lower()
    except ValueError:
        return ""


def _on(url, query: bool = False):
    """The parsed address when it is https on exactly the bank's host with no
    fragment, and no query unless `query`, else None."""
    if not isinstance(url, str) or not is_safe_url(url) or "#" in url:
        return None
    if not query and "?" in url:
        return None
    try:
        return urlsplit(url)
    except ValueError:
        return None


def is_documents_url(url) -> bool:
    """The documents page itself, with nothing after it."""
    parts = _on(url)
    return parts is not None and parts.path in (DOCUMENTS_PATH, DOCUMENTS_PATH + "/")


def list_address(url) -> Tuple[str, str]:
    """(userId, startDate) of the page's own list call,
    /a/consumer/api/v0/users/<userId>/documents/all?startDate=YYYY-MM-DD with
    that one query key once, or ("", "")."""
    parts = _on(url, query=True)
    m = _LIST_PATH_RE.fullmatch(parts.path) if parts else None
    if not m:
        return "", ""
    try:
        pairs = parse_qsl(parts.query, keep_blank_values=True, strict_parsing=True)
    except ValueError:
        return "", ""
    if len(pairs) != 1 or pairs[0][0] != "startDate" or not answer_date(pairs[0][1]):
        return "", ""
    return m.group(1), pairs[0][1]


def accounts_user(url) -> str:
    parts = _on(url)
    m = _ACCOUNTS_PATH_RE.fullmatch(parts.path) if parts else None
    return m.group(1) if m else ""


def institution_user(url) -> str:
    parts = _on(url)
    m = _INSTITUTION_PATH_RE.fullmatch(parts.path) if parts else None
    return m.group(1) if m else ""


def pdf_ids(url) -> Tuple[str, str]:
    """(userId, documentId) of a document's own PDF address, or ("", "")."""
    parts = _on(url)
    m = _PDF_PATH_RE.fullmatch(parts.path) if parts else None
    return (m.group(1), m.group(2)) if m else ("", "")


def is_census_url(url) -> bool:
    """What the run's request census may describe: the documents page and
    the two answers this app reads whole itself, the list and the bank's
    documents settings. The accounts answer, which carries balances, and
    every other answer of the bank, emails and transactions among them, are
    never read by the census and are counted with other hosts' answers
    (api_census.Requests)."""
    return is_documents_url(url) or bool(list_address(url)[0]) or bool(institution_user(url))


def is_download_url(url) -> bool:
    """True only for a Blob the bank's own page made,
    blob:https://login.simmonsbank.com/<uuid>, nothing else."""
    return isinstance(url, str) and bool(_BLOB_RE.fullmatch(url))


# ---------------------------------------------------------------------------
# Private words
# ---------------------------------------------------------------------------

def _guard_words(values) -> None:
    """Register each value as a private word, whole when it is one word of
    four characters or more, and part by part, as redact applies them
    anywhere in a string: every part of four letters or more, every part
    mixing letters and digits, and every run of five digits or more. A
    shorter run of digits alone, a day, a month or a year in a file name, is
    left alone, since masking it would mask every date the run writes. The
    last four of the account is registered on its own (_guard_last4)."""
    parts = set()
    for v in values:
        if not isinstance(v, str):
            continue
        whole = v.strip()
        if len(whole) >= 4 and not re.search(r"[\s,]", whole):
            parts.add(whole)
        for p in re.split(r"[^A-Za-z0-9]+", v):
            if p.isdigit():
                if len(p) >= 5:
                    parts.add(p)
            elif len(p) >= 4 or re.search(r"[0-9]", p):
                parts.add(p)
    # The words every row and file name shares and the bank's own name stay
    # readable.
    parts -= {"Simmons", "Bank", "simmonsbank", "login", "blob", "https", "documents", "STATEMENT",
              "NOTICE", "Statement", "Notice"}
    _add_private(parts)


def _guard_last4(last4) -> None:
    """The account's last four, private on its own, four digits exactly."""
    if isinstance(last4, str) and re.fullmatch(r"[0-9]{4}", last4):
        _add_private({last4})


def _guard_name(name) -> None:
    """A person's name, every part of it of two letters or more, as the
    owner's own name is registered."""
    if isinstance(name, str) and name.strip():
        _add_private({p for p in re.split(r"[\s,]+", name.strip()) if len(p) >= 2})


def _add_private(parts) -> None:
    new = sorted(set(parts) - set(private_words()))
    if new:
        set_private_words(private_words() + new)


def _guard_address(url) -> None:
    """Register an address's private parts: every UUID it carries and the
    whole address. The words every address of the bank shares, "consumer",
    "users", "documents", stay readable."""
    if not isinstance(url, str) or not url.strip():
        return
    _add_private(set(UUID_RE.findall(url)) | {url.strip()})


# ---------------------------------------------------------------------------
# The page's own answers, heard on the browser context
# ---------------------------------------------------------------------------

def _origin(response):
    """The page whose frame asked for `response`, or None when it cannot be
    told. An answer from no known page is never this run's."""
    try:
        return response.frame.page
    except Exception:
        return None


def _status(response) -> int:
    try:
        return int(response.status)
    except Exception:
        return 0


def _signed_out_status(response) -> bool:
    """The bank saying the session has ended, a 401 or 403, or a redirect
    (301, 302, 303, 307 or 308), since the documents API answers a signed-in
    page with its JSON and never sends it elsewhere. Where a redirect points
    is read by the core's redirects alone, so any redirect here is one. Any
    other 3xx, a 304 from a cache among them, is an answer this cannot read
    (_unread_status), never a sign-out."""
    status = _status(response)
    return status in (401, 403) or status in redirects.REDIRECTS


def _unread_status(response) -> bool:
    """A 3xx that is no redirect, a 304 from a cache revalidation say. It
    carries no answer this can read, so the list stops."""
    return 300 <= _status(response) < 400 and not _signed_out_status(response)


def _ctype(response) -> str:
    try:
        return (response.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
    except Exception:
        return ""


def _method(response) -> str:
    try:
        return str(response.request.method or "").upper()
    except Exception:
        return ""


def _kind_of(url) -> str:
    if list_address(url)[0]:
        return "list"
    if accounts_user(url):
        return "accounts"
    if institution_user(url):
        return "institution"
    return ""


class _Watch:
    """The page's own list, accounts and settings answers, heard on the
    browser context from the moment it is attached, each kept with the page
    that asked for it. Only answers from the run's own page are ever read.
    Nothing is read from an answer here but its address, method, status and
    page, and the userId its address carries is made private at once. Its
    body is read after the wait (venmo found a body still arriving cannot be
    read inside the handler), and the page stays on the documents page
    until then."""

    def __init__(self):
        self.heard: list = []          # (kind, page, response)
        self.signed_out: list = []     # pages a signed-out list answer came to

    def on_response(self, response) -> None:
        try:
            url = response.url
            kind = _kind_of(url)
            if not kind or _method(response) not in ("GET", ""):
                return
            _guard_address(url.split("?", 1)[0])
            origin = _origin(response)
            if kind == "list" and _signed_out_status(response):
                self.signed_out.append(origin)
                return
            self.heard.append((kind, origin, response))
        except Exception:
            pass

    def mark(self) -> int:
        return len(self.heard)

    def since(self, mark: int, page, kind: str) -> list:
        return [r for k, origin, r in self.heard[mark:] if k == kind and origin is page]

    def raise_if_signed_out(self, page) -> None:
        if any(origin is page for origin in self.signed_out):
            raise SessionExpired("Simmons Bank answered the page's own list call as signed out")


class Run:
    """What one command carries between loads: the watch on the browser
    context, and the date the bank keeps this loan's documents until, once
    an accounts answer named it. The App owns one per command."""

    def __init__(self):
        self.watch = _Watch()
        self.available_until = ""
        self._context = None

    def attach(self, context) -> None:
        """Listen on `context`, once. Done by the App as soon as the browser
        context exists, before any page is loaded."""
        if context is None or context is self._context:
            return
        if self._context is not None:
            try:
                self._context.remove_listener("response", self.watch.on_response)
            except Exception:
                pass
        context.on("response", self.watch.on_response)
        self._context = context


def _exactly(want: str):
    def guard(url) -> bool:
        return isinstance(url, str) and url == want
    return guard


def _body(response):
    """An answer's bytes, waited for while it is still arriving, or None
    when they cannot be read."""
    try:
        finished = getattr(response, "finished", None)
        if callable(finished):
            finished()
        return intake.body(response)
    except Exception:
        return None


def _json_of(page, response, what: str, ask_again: bool = False):
    """An answer's JSON. A 401, 403, a redirect or HTML is the bank saying
    the session has ended. Any other 3xx, a 304 among them, and
    anything else that is not a 200 JSON answer stops the list. With
    `ask_again`, an answer whose body the browser no longer holds is asked
    once more at its exact address, with the browser's cookies and no
    redirect followed, as the page itself asked it."""
    if _signed_out_status(response):
        raise SessionExpired("the %s answer was signed out" % what)
    if _unread_status(response):
        raise ListStopped("the %s answer was a %d, which carries nothing this can read"
                          % (what, _status(response)))
    body = _body(response)
    if body is None and ask_again:
        url = response.url
        log.info("the %s answer's body was gone, so its address is asked once more", what)
        response = _ask(page, url, what)
        if _signed_out_status(response):
            raise SessionExpired("the %s answer was signed out" % what)
        if _unread_status(response):
            raise ListStopped("the %s answer was a %d, which carries nothing this can read"
                              % (what, _status(response)))
        body = _body(response)
    if body is None:
        raise ListStopped("the %s answer could not be read" % what)
    if _ctype(response).startswith("text/html") or body.lstrip()[:1] == b"<":
        raise SessionExpired("the %s answer was a page" % what)
    if _status(response) != 200:
        raise ListStopped("the %s answer was not 200" % what)
    try:
        return whole_json(json.loads(body.decode("utf-8")))
    except (ValueError, UnicodeDecodeError):
        raise ListStopped("the %s answer was not JSON" % what)


@dataclass(frozen=True)
class Entry:
    """One document of the list answer."""
    document_id: str = field(repr=False)
    kind: str = ""
    title: str = ""
    date: str = ""
    filename: str = field(default="", repr=False)
    account_id: str = field(default="", repr=False)

    @property
    def type_word(self) -> str:
        return _TYPE_WORDS[self.kind]


# What a list answer holds, all of it. The live answer held this one key, and
# a key beyond it (a cursor, a page, a total) may be how the bank says there
# is more.
LIST_KEYS = frozenset({"documents"})
_ENTRY_KEYS = frozenset({"documentId", "documentType", "documentTitle", "description", "date",
                         "documentFilename", "accountIds"})


def entries_of(got, start: str) -> List[Entry]:
    """The documents of one list answer, asked from `start`. The answer holds
    nothing but its list (LIST_KEYS), every entry a document of a known type
    with an id of the expected shape, a title, a calendar date on or after
    `start`, a PDF file name and exactly one account, no id twice, and one
    account across the whole list, or the list stops. Every id, account and
    file name is private before anything else is done with it."""
    if not isinstance(got, dict) or not isinstance(got.get("documents"), list):
        raise ListStopped("the documents answer is not the expected shape")
    raw = got["documents"]
    values = []
    for e in raw:
        if isinstance(e, dict):
            values += [e.get("documentId"), e.get("documentFilename")]
            ids = e.get("accountIds")
            values += list(ids) if isinstance(ids, list) else []
    _guard_words([v for v in values if isinstance(v, str)])
    if set(got) - LIST_KEYS:
        raise ListStopped("the documents answer holds more than its list, which may say there "
                          "are more documents, so it is not read as the whole list")
    out: List[Entry] = []
    for e in raw:
        if not isinstance(e, dict) or set(e) - _ENTRY_KEYS:
            raise ListStopped("a document of the answer could not be read")
        did = e.get("documentId")
        if not isinstance(did, str) or not UUID_RE.fullmatch(did):
            raise ListStopped("a document's id is not one this can read")
        kind = e.get("documentType")
        if kind not in KINDS:
            raise ListStopped("a document is of a type this does not know")
        title = e.get("documentTitle")
        if not isinstance(title, str) or not _tidy(title) or len(title) > 200 \
                or _tidy(title) != title:
            raise ListStopped("a document's title could not be read")
        iso = answer_date(e.get("date"))
        if not iso:
            raise ListStopped("a document's date is not a calendar date")
        if iso < start:
            raise ListStopped("a document is dated before the day the list was asked from")
        name = e.get("documentFilename")
        if not isinstance(name, str) or not name.lower().endswith(".pdf") or "/" in name \
                or "\\" in name:
            raise ListStopped("a document's file name is not a PDF's")
        accounts = e.get("accountIds")
        if not isinstance(accounts, list) or len(accounts) != 1 \
                or not isinstance(accounts[0], str) or not accounts[0].strip():
            raise ListStopped("a document does not name exactly one account")
        if any(x.document_id == did for x in out):
            raise ListStopped("two documents carry one id")
        out.append(Entry(did, kind, title, iso, name, accounts[0]))
    if len({x.account_id for x in out}) > 1:
        raise ListStopped("the documents answer names more than one account, and this app "
                          "reads one")
    return out


@dataclass(frozen=True)
class Row:
    """One document row the page drew, by its button's whole text."""
    index: int
    text: str = field(repr=False)
    title: str = ""
    type_word: str = ""
    account: str = field(default="", repr=False)


# Every button's text, the list item it sits in (climbed through shadow
# hosts, -1 for none, the same number for the same item) and whether it is
# drawn. Run on page.locator("button"), which reaches every open shadow root.
_BUTTONS_JS = r"""els => {
  const items = [];
  return els.map(e => {
    let n = e, item = null;
    while (n) {
      if (n.localName === '%s') { item = n; break; }
      n = n.parentElement || (n.parentNode && n.parentNode.host) || null;
    }
    let k = -1;
    if (item) { k = items.indexOf(item); if (k < 0) { items.push(item); k = items.length - 1; } }
    // Drawn and seen: checkVisibility reads every ancestor through shadow
    // hosts, hidden, visibility hidden and fully transparent alike.
    // A browser without it says nothing, and a row it cannot vouch for
    // stops the list.
    const shown = typeof e.checkVisibility === 'function'
      ? e.checkVisibility({checkOpacity: true, checkVisibilityCSS: true}) : null;
    return {t: (e.innerText || '').replace(/\s+/g, ' ').trim(), item: k, shown: shown};
  });
}""" % ROW_HOST


def _buttons(page) -> List[dict]:
    """Every button on the page, in Playwright's own order, through every
    open shadow root, as {text, item, shown}."""
    try:
        got = page.locator("button").evaluate_all(_BUTTONS_JS)
    except Exception as e:
        raise ListStopped("the page's buttons could not be read (%s)" % type(e).__name__)
    if not isinstance(got, list) or not all(isinstance(b, dict) for b in got):
        raise ListStopped("the page's buttons could not be read")
    return [{"text": _tidy(b.get("t")), "item": b.get("item"), "shown": b.get("shown") is True}
            for b in got]


def _button_texts(page) -> List[str]:
    return [b["text"] for b in _buttons(page)]


def read_rows(page) -> List[Row]:
    """Every document row the page draws, its account registered private as
    soon as it is read. A row is a drawn button inside a list item, the only
    row of that item, whose whole text is a row's. A button with a row's
    text anywhere else, one not drawn, a second row in one item, or a button
    that ends like a row's text and is not one stops the list. Every other
    button, Accept, Enroll, the menus and the links, is no row."""
    rows: List[Row] = []
    items = set()
    for i, b in enumerate(_buttons(page)):
        text = b["text"]
        m = ROW_RE.fullmatch(text)
        if not m:
            if ROW_TAIL_RE.search(text):
                _guard_last4(text.rstrip()[-5:-1])
                raise ListStopped("a document row's text could not be read")
            continue
        _guard_words([m.group("acct"), m.group("name")])
        _guard_last4(m.group("last4"))
        item = b["item"]
        if not isinstance(item, int) or isinstance(item, bool) or item < 0:
            raise ListStopped("a button reads like a document row outside the list")
        if not b["shown"]:
            raise ListStopped("a document row is not drawn")
        if item in items:
            raise ListStopped("a list item holds two document rows")
        items.add(item)
        rows.append(Row(i, text, m.group("title"), m.group("type"), m.group("acct")))
    return rows


def rows_disagree(rows: List[Row], entries: List[Entry]) -> str:
    """Why the rows drawn are not the answer's documents, or "". The rows
    must name exactly the answer's titles and types, as many of each, all of
    one account."""
    if len({r.account for r in rows}) > 1:
        return "the rows name more than one account"
    if len(rows) != len(entries):
        return "the page draws %d rows for %d documents" % (len(rows), len(entries))
    if Counter((r.title, r.type_word) for r in rows) != \
            Counter((e.title, e.type_word) for e in entries):
        return "the rows' titles are not the answer's"
    return ""


_OWNER_JS = r"""els => els.map(e => (e.innerText || '').replace(/\s+/g, ' ').trim())"""


def _guard_owner(page) -> None:
    """The owner's name on the user menu is private once it is drawn."""
    try:
        names = page.locator('button[aria-label="user menu"]').evaluate_all(_OWNER_JS)
    except Exception:
        return
    for n in names or []:
        _guard_name(n)


@dataclass
class Listing:
    entries: List[Entry]
    rows: List[Row]
    account: str = field(default="", repr=False)
    user_id: str = field(default="", repr=False)
    available_until: str = ""


def _pause(page, ms: float) -> None:
    page.wait_for_timeout(ms)


def _open(page, run: Run) -> int:
    """Load the documents page afresh, with the context's watch already
    listening. Nothing is pressed. Returns the watch's mark taken before the
    load."""
    run.attach(page.context)
    mark = run.watch.mark()
    try:
        page.goto(DOCUMENTS_URL, wait_until="domcontentloaded", timeout=60000)
    except Exception as e:
        log.info("opening the documents page failed (%s)", type(e).__name__)
        check_signed_in(page)
        raise ListStopped("the documents page did not open")
    check_signed_in(page)
    if not is_documents_url(page.url or ""):
        raise ListStopped("the documents page settled off its own address")
    return mark


def _one_list(page, answers: list, read: dict) -> Tuple[str, str, List[Entry]]:
    """(userId, startDate, entries) of the list answers heard. Two that say
    different things stop the list. A body the browser no longer holds is
    asked once more at its exact address (_json_of), once for each answer,
    since `read` keeps what each answer was read as."""
    got = None
    for response in answers:
        user, start = list_address(response.url)
        if id(response) not in read:
            read[id(response)] = (response, _json_of(page, response, "documents", ask_again=True))
        entries = entries_of(read[id(response)][1], start)
        if got is not None and (got[0], got[1], got[2]) != (user, start, entries):
            raise ListStopped("the page asked for the documents twice and was answered "
                              "differently")
        got = (user, start, entries)
    return got


def _available_until(page, answers: list, account_id: str) -> str:
    """The date the accounts answer says this loan's documents are kept
    until, or "" when no accounts answer was heard or its body is gone. The
    answer must hold exactly one account, the list's own, or the list stops.
    Its name and numbers are private at once. Nothing else of it is read."""
    for response in answers[-1:]:
        if _signed_out_status(response):
            raise SessionExpired("the accounts answer was signed out")
        body = _body(response)
        if body is None or _status(response) != 200:
            return ""
        try:
            got = whole_json(json.loads(body.decode("utf-8")))
        except (ValueError, UnicodeDecodeError):
            return ""
        accounts = got.get("accounts") if isinstance(got, dict) else None
        if not isinstance(accounts, list):
            return ""
        _guard_words([str(a.get(k) or "") for a in accounts if isinstance(a, dict)
                      for k in ("id", "name", "numbers")])
        if len(accounts) > 1:
            raise ListStopped("the bank's accounts answer holds more than one account, and "
                              "this app reads one")
        if len(accounts) != 1 or not isinstance(accounts[0], dict):
            # A paid-off loan's account leaves the answer once its date has
            # passed. Said as what was seen, never as more than one.
            raise ListStopped("the bank's accounts answer holds no account this can read")
        if account_id and accounts[0].get("id") != account_id:
            raise ListStopped("the documents are of another account than the one the bank lists")
        return answer_date(accounts[0].get("closedAccountAvailableUntil")) or ""
    return ""


def institution_url(user: str) -> str:
    return "%s/a/consumer/api/users/%s/documents/settings/institution" % (BASE, user)


def _start_is_the_banks(page, answers: list, user: str, start: str) -> None:
    """The day the list was asked from must be the bank's own first day of
    documents, its documentStartDate. Read from the settings answer the page
    got on this load for the list's own userId (two that differ stop the
    list), or when none was heard or its body is gone, from that user's
    exact settings address asked once with the browser's cookies and no
    redirect followed. A first day absent, unreadable or another day stops
    the list, since a list asked from a later day would read whole and miss
    every older document."""
    said_by = set()
    got = None
    for response in answers:
        if institution_user(response.url) != user or _status(response) != 200:
            continue
        body = _body(response)
        if body is None:
            continue
        try:
            read = whole_json(json.loads(body.decode("utf-8")))
        except (ValueError, UnicodeDecodeError):
            continue
        said_by.add(json.dumps(read, sort_keys=True))
        got = read
    if len(said_by) > 1:
        raise ListStopped("the bank's documents settings were answered twice, differently")
    if got is None:
        url = institution_url(user)
        log.info("the bank's documents settings were not heard, so their address is asked once")
        got = _json_of(page, _ask(page, url, "settings"), "settings")
    said = ((got or {}).get("settings") or {}).get("documentStartDate") \
        if isinstance(got, dict) and isinstance(got.get("settings"), dict) else None
    if answer_date(said) is None:
        raise ListStopped("the bank's first day of documents could not be read")
    if answer_date(said) != start:
        raise ListStopped("the list was asked from another day than the bank's own first day")


def _ask(page, url: str, what: str):
    """GET one of the bank's own addresses once, with the browser's cookies
    and no redirect followed."""
    try:
        return redirects.get(page.context.request, url, _exactly(url), hops=0, timeout=60000)
    except Exception as e:
        raise ListStopped("the %s address could not be asked (%s)" % (what, type(e).__name__))


def read_listing(page, run: Optional[Run] = None) -> Listing:
    """Open the documents page and read the list whole: the page's own list
    answer, one of them, holding only its documents, of one account, and the
    rows drawn naming exactly its titles and types, read twice alike. Raises
    ListStopped for anything else, SessionExpired for a signed-out session.
    Nothing is pressed."""
    run = run or Run()
    mark = _open(page, run)
    got: dict = {}
    read: dict = {}

    def ready() -> bool:
        lists = run.watch.since(mark, page, "list")
        if not lists:
            return False
        if "list" not in got:
            got["list"] = _one_list(page, lists, read)
        rows = read_rows(page)
        if rows_disagree(rows, got["list"][2]):
            return False
        got["rows"] = rows
        return True

    waited = 0
    while True:
        check_signed_in(page)
        run.watch.raise_if_signed_out(page)
        if ready():
            break
        if waited >= LIST_WAIT_MS:
            if "list" not in got:
                raise ListStopped("no documents answer came")
            raise ListStopped("the rows the page draws are not the answer's documents (%s)"
                              % rows_disagree(read_rows(page), got["list"][2]))
        _pause(page, POLL_MS)
        waited += POLL_MS
    _pause(page, SETTLE_MS)
    check_signed_in(page)
    run.watch.raise_if_signed_out(page)
    user, start, entries = _one_list(page, run.watch.since(mark, page, "list"), read)
    rows = read_rows(page)
    if entries != got["list"][2] or [r.text for r in rows] != [r.text for r in got["rows"]]:
        raise ListStopped("the documents changed while the list was read")
    _guard_owner(page)
    account_id = entries[0].account_id if entries else ""
    _start_is_the_banks(page, run.watch.since(mark, page, "institution"), user, start)
    until = _available_until(page, run.watch.since(mark, page, "accounts"), account_id)
    if until:
        run.available_until = until
    return Listing(entries, rows, rows[0].account if rows else "", user, until)


@dataclass
class RawDoc:
    title: str
    account: str = ""
    date_text: str = ""
    href: str = ""
    text: str = ""
    row_index: int = -1
    kind: str = "doc"
    # record_hash of the bank's documentId. The id itself is never kept.
    document_id: str = ""


def collect_download_docs(page, run: Optional[Run] = None) -> List[RawDoc]:
    """Every document the documents page lists. Raises ListStopped (holding
    nothing, since a list not read whole is not called read) and
    SessionExpired."""
    listing = read_listing(page, run)
    docs = [RawDoc(title=e.title, date_text=e.date, text=e.title, row_index=i, kind=e.kind,
                   document_id=record_hash(e.document_id))
            for i, e in enumerate(listing.entries)]
    log.info("documents: %d listed (%s)", len(docs), ", ".join(
        "%s %d" % (k, sum(1 for e in listing.entries if e.kind == k)) for k in KINDS))
    return docs


def goto_documents(page, run: Optional[Run] = None) -> bool:
    """Open the documents page and read its list whole. False when it showed
    the sign-in page or the list could not be read. Nothing is pressed."""
    try:
        read_listing(page, run)
        return True
    except (SessionExpired, ListStopped) as e:
        log.info("the documents page did not open: %s", type(e).__name__)
        return False


def scroll_full_page(page, rounds: int = 0, delay_ms: int = 0) -> None:
    """Nothing to scroll: the page draws every row."""
    return None


def expand_all(page) -> None:
    """Nothing is pressed but a document row's own button."""
    return None


# ---------------------------------------------------------------------------
# One document
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Target:
    """The document to take and what binds its PDF to it: the row's whole
    text, its documentId, its documentFilename and the userId of the list,
    all held in memory only."""
    label: str = field(repr=False)
    document_id: str = field(repr=False)
    filename: str = field(repr=False)
    user_id: str = field(default="", repr=False)


def row_label(entry: Entry, account: str) -> str:
    return "%s %s, %s" % (entry.title, entry.type_word, account)


def _note(trace, **what) -> None:
    if trace is not None:
        trace.append(what)


def _cancel_all(downloads: list) -> None:
    """End every download handed over and remove any file the browser had
    already written for it. Nothing of it is read or kept."""
    for dl in downloads:
        intake.discard(dl)


def _close_all(pages: list) -> None:
    for p in pages:
        try:
            if not p.is_closed():
                p.close()
        except Exception:
            pass


def _stop(said: str, reason: str):
    return pressing.no_answer("save the document", reason, said)


def _own_request(target: Target, asked: list) -> str:
    """The one PDF address the page asked after the press, when it is this
    document's own, on the bank's host with no query, for the list's userId,
    or "" for none, two, or any other."""
    if len(asked) != 1:
        return ""
    user, did = pdf_ids(asked[0])
    if did != target.document_id or user != target.user_id:
        return ""
    return asked[0]


def _fetch_asked(page, url: str, out_path: Path, trace) -> bool:
    """With no download come, the exact address the page asked for this
    document's PDF after the press (_own_request), asked once more with the
    browser's cookies and no redirect followed. Written only when it answers
    200 with a PDF."""
    try:
        resp = redirects.get(page.context.request, url, _exactly(url), hops=0, timeout=60000)
    except Exception as e:
        _note(trace, note="asking the page's PDF address again failed", error=type(e).__name__)
        return False
    if _signed_out_status(resp):
        raise SessionExpired("the document's address answered as signed out")
    body = _body(resp) if _status(resp) == 200 else None
    if not body or body[:5] != b"%PDF-":
        _note(trace, note="the page's PDF address did not answer a PDF", status=_status(resp))
        return False
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(body)
    _note(trace, note="document taken", how="fetched")
    return True


def _came_since(dl_dir, before) -> list:
    """The names in the download folder that were not there at `before`, or
    have been written again since, finished ones and ones the browser is
    still writing alike."""
    if not dl_dir:
        return []
    try:
        now = set(os.listdir(dl_dir))
    except OSError:
        return []
    return sorted({n for n in now if n not in before} | set(_arrived(dl_dir, before)))


def _new_in_folder(dl_dir, before) -> int:
    """How many files came into the download folder since `before`."""
    return len(_came_since(dl_dir, before))


# The app's own download folder, under the output folder. The browser saves
# each download there under the bank's own documentFilename, which can carry
# the account number, so nothing the app did not keep is left in it. Files
# are only ever removed from directly inside a folder of this name.
DOWNLOAD_FOLDER = ".simmons-downloads"
_UNFINISHED = (".crdownload", ".part", ".partial", ".tmp", ".download")


def _own_folder(dl_dir) -> Optional[Path]:
    """The app's own download folder, resolved, or None for any other
    folder, a link to one or a folder that is not there."""
    if not dl_dir:
        return None
    try:
        folder = Path(dl_dir)
        if folder.name != DOWNLOAD_FOLDER or folder.is_symlink() or not folder.is_dir():
            return None
        real = folder.resolve()
        # A junction or link in its place resolves somewhere else.
        if real.name != DOWNLOAD_FOLDER or real.parent != folder.absolute().parent.resolve():
            return None
        return real
    except (OSError, RuntimeError):
        return None


def _same_file(a: Path, b) -> bool:
    try:
        return os.path.samefile(a, b)
    except (OSError, TypeError, ValueError):
        return False


def _remove(folder: Path, names, keep=None, unfinished: bool = True) -> int:
    """Remove each of `names` that is a plain file directly in `folder`,
    never a link, a folder or the file `keep`, and with `unfinished` False
    never one the browser is still writing. Says how many went."""
    gone = 0
    for name in names:
        if not name or name in (".", "..") or "/" in name or "\\" in name:
            continue
        if not unfinished and name.lower().endswith(_UNFINISHED):
            continue
        path = folder / name
        try:
            if path.is_symlink() or not path.is_file() or path.resolve().parent != folder:
                continue
            if keep is not None and _same_file(path, keep):
                continue
            path.unlink()
            gone += 1
        except OSError:
            continue
    return gone


def clear_what_came(dl_dir, before, keep=None) -> int:
    """Remove from the app's own download folder every file that came, or
    was written again, since `before`, finished or still arriving, except
    `keep`. A capture asks this as it ends, kept or refused, so a download
    it refused or gave up on does not stay under the bank's file name.
    Nothing is removed from any other folder. Says how many went."""
    folder = _own_folder(dl_dir)
    if folder is None:
        return 0
    return _remove(folder, _came_since(folder, before), keep)


def empty_download_folder(dl_dir, unfinished: bool = True) -> int:
    """Remove every plain file directly in the app's own download folder,
    and with `unfinished` False leave one the browser is still writing.
    Everything the app keeps has been moved to the archive by then, so what
    is left there is a download it refused or gave up on, or a copy. Asked
    before each press and as a run starts and ends. Nothing is removed from
    any other folder. Says how many went."""
    folder = _own_folder(dl_dir)
    if folder is None:
        return 0
    try:
        names = os.listdir(folder)
    except OSError:
        return 0
    return _remove(folder, names, unfinished=unfinished)


def _row_button(page, label: str):
    """The one drawn button inside a list item whose whole text is `label`,
    as an element, or None. Buttons that cannot be read raise ListStopped,
    as they do when the list is read."""
    buttons = _buttons(page)
    hits = [i for i, b in enumerate(buttons)
            if b["text"] == label and b["shown"] and isinstance(b["item"], int)
            and not isinstance(b["item"], bool) and b["item"] >= 0]
    if len(hits) != 1:
        return None
    try:
        return page.locator("button").nth(hits[0]).element_handle(timeout=3000)
    except Exception:
        return None


def _catch_document(page, run: Run, dl_dir, target: Target, out_path,
                    trace: Optional[list] = None) -> Optional[bool]:
    """Press the bound row's own button once and take the PDF it brings.

    Heard from just before the press on: every download, every tab the page
    opens and every PDF address of a document the page asks. The press must
    make the page ask exactly one PDF address, this document's own
    (_own_request). The PDF is then taken from the one download the press
    brought, when its address is a Blob of the bank's page and its suggested
    file name is the document's own documentFilename, and failing a
    download, from that address asked once more (_fetch_asked). A tab, a
    second download, no request or another document's, the tab leaving the
    page, a download named for another file, or a file landing in the
    download folder with no download event, and nothing is taken. Every
    download refused is ended and its file removed.

    None when the page has turned the row's button off: nothing was pressed,
    nothing is waited for, and the document is left for the next run."""
    out_path = Path(out_path)
    # press_once asks the guard only before its press through the page, not
    # before Playwright's own first press, so the row's own text is asked
    # here, before anything is found or pressed.
    if not is_document_row(target.label, target.label):
        _note(trace, note="the row's own text is not a document row this presses")
        return False
    el = _row_button(page, target.label)
    if el is None:
        _note(trace, note="not one row reads this document's text")
        return False

    def row_changed() -> str:
        """press_once's own check, "" while the button still reads the
        bound row's whole text."""
        try:
            now = _tidy(el.evaluate("e => e.innerText || ''"))
        except Exception:
            return "its row could not be read"
        return "" if now == target.label else "its row reads another document"

    downloads: list = []
    popups: list = []
    asked: list = []

    def on_download(dl):
        downloads.append(dl)

    def on_popup(p):
        popups.append(p)

    def on_request(request):
        try:
            url = request.url
            if pdf_ids(url)[1] and str(request.method or "GET").upper() == "GET":
                _guard_address(url)
                asked.append(url)
        except Exception:
            pass

    # A download an earlier press gave up on that finished since goes before
    # this press, so it is neither left under the bank's file name nor taken
    # for this one. One the browser is still writing is left to the end.
    empty_download_folder(dl_dir, unfinished=False)
    before = _snapshot(dl_dir)
    where = page.url or ""
    try:
        if row_changed():
            _note(trace, note="the row's button reads another document now")
            return False
        # Armed just before the press, so nothing the page asked or
        # downloaded before it is taken for this press's.
        for event, fn in (("download", on_download), ("popup", on_popup), ("request", on_request)):
            page.on(event, fn)
        try:
            outcome = pressing.press_once(
                page, el, what="the row of this document", words=_words(),
                guard=lambda words: is_document_row(words, target.label), check=row_changed,
                dl_dir=dl_dir, brought=lambda: bool(downloads or asked or popups))
        except pressing.TurnedOff:
            _note(trace, note="the row's button is turned off on the page, so nothing was pressed")
            return None
        _note(trace, note="pressed" if outcome.error is None else "press raised",
              how=outcome.how, error=type(outcome.error).__name__ if outcome.error else "")
        if outcome.how == pressing.GONE:
            _note(trace, note="the row left the page before it was pressed")
            return False
        waited = 0
        while not downloads and waited < DOWNLOAD_WAIT_MS:
            if popups or len(asked) > 1 or (asked and not _own_request(target, asked)) \
                    or (page.url or "") != where:
                break
            _pause(page, POLL_MS)
            waited += POLL_MS
        if downloads:
            _pause(page, SECOND_DOWNLOAD_WAIT_MS)
        if popups:
            _close_all(popups)
            _cancel_all(downloads)
            _note(trace, note="the press opened a tab, so nothing was taken", tabs=len(popups))
            return False
        if (page.url or "") != where:
            _cancel_all(downloads)
            _note(trace, note="the page left the documents list after the press")
            return False
        own = _own_request(target, asked)
        if not own:
            _cancel_all(downloads)
            _note(trace, note="the page did not ask this document's own PDF once, so nothing "
                              "was taken", asked=len(asked))
            return False
        if len(downloads) > 1:
            _cancel_all(downloads)
            _note(trace, note="more than one download came after one press, so none was taken",
                  downloads=len(downloads))
            return False
        if not downloads:
            came = _new_in_folder(dl_dir, before)
            if came:
                # A download Playwright did not hand over, finished or still
                # being written. Whose it is cannot be told, so it is not
                # taken and the document is not asked again, which would make
                # a second copy. It is removed as the capture ends, with
                # everything else this press brought (clear_what_came).
                _note(trace, note="a file came into the download folder with no download event, "
                                  "so nothing was taken or asked again", files=came)
                return False
            return _fetch_asked(page, own, out_path, trace)
        dl = downloads[0]
        try:
            url = dl.url or ""
        except Exception:
            url = ""
        _guard_address(url)
        if not is_download_url(url):
            _cancel_all(downloads)
            _note(trace, note="the download is not the bank's own page's", host=_host_of(url))
            return False
        try:
            name = dl.suggested_filename or ""
        except Exception:
            name = ""
        if name != target.filename:
            _cancel_all(downloads)
            _note(trace, note="the download is named for another file, so it was not taken")
            return False
        how = _take_download(dl, dl_dir, before, out_path)
        _note(trace, note="document taken" if how else "download not taken", how="download",
              where=how)
        return bool(how)
    finally:
        for event, fn in (("download", on_download), ("popup", on_popup), ("request", on_request)):
            try:
                page.remove_listener(event, fn)
            except Exception:
                pass
        try:
            _clear_copies(dl_dir, before, out_path)
        except Exception:
            pass
        # Whatever this press brought into the app's own download folder,
        # refused, given up on or a copy, goes before the run goes on. The
        # kept document is in the archive, never in that folder.
        try:
            clear_what_came(dl_dir, before, keep=out_path)
        except Exception:
            pass
        try:
            el.dispose()
        except Exception:
            pass


def download_document(page, run: Run, dl_dir, out_path, *, record_id: str, iso_date: str,
                      title: str, kind: str, trace: Optional[list] = None) -> Optional[bool]:
    """Save the document discovery recorded. The documents page is loaded
    afresh and the list read whole again, and exactly one document must carry
    the record's hash and date, with the record's title and type, and
    exactly one row its whole text, before that one row's button is pressed.
    False, with nothing pressed, when it is not there. None when its button
    is turned off on the page. A list that stops on the way stops the run
    with pressing.Stop, since the next document would meet the same page.
    SessionExpired propagates. Whether the PDF names its document is
    pdf_names_document's to say, after."""
    out_path = Path(out_path)
    if not (isinstance(record_id, str) and RECORD_HASH_RE.fullmatch(record_id)
            and answer_date(iso_date) == iso_date and kind in KINDS):
        _note(trace, note="the record does not name one document")
        return False
    try:
        listing = read_listing(page, run)
    except ListStopped as stop:
        log.info("the list stopped while looking for the document dated %s: %s", iso_date, stop)
        _note(trace, note="the list stopped")
        raise _page_stopped(stop)
    found = [e for e in listing.entries
             if record_hash(e.document_id) == record_id and e.date == iso_date]
    if len(found) != 1:
        _note(trace, note="no single document matches the record", matches=len(found))
        return False
    entry = found[0]
    if entry.title != title or entry.kind != kind:
        _note(trace, note="the document listed under the record has another title or type")
        return False
    label = row_label(entry, listing.account)
    rows = [r for r in listing.rows if r.text == label]
    if len(rows) != 1:
        _note(trace, note="not one row reads this document's text", rows=len(rows))
        return False
    target = Target(label, entry.document_id, entry.filename, listing.user_id)
    try:
        return _catch_document(page, run, dl_dir, target, out_path, trace)
    except ListStopped as stop:
        log.info("the list stopped before the document dated %s was pressed: %s", iso_date, stop)
        _note(trace, note="the list stopped")
        raise _page_stopped(stop)


def _page_stopped(stop: ListStopped) -> pressing.Stop:
    """A stop of the list while a document was sought, as a stop of the run.
    Its words are this app's own, never the page's."""
    return pressing.Stop("find the document", "the documents list stopped", [
        "The documents list stopped before this document was saved, since %s." % stop,
        "Nothing was pressed, and the run stops here rather than meet the same page "
        "for the next document.",
        pressing.AGAIN])


# ---------------------------------------------------------------------------
# Whether the PDF names its document
# ---------------------------------------------------------------------------

def pdf_text(data: bytes, pages: int = 5) -> str:
    """The text of the first pages of a PDF held in memory, or "". Never
    logged, never written."""
    try:
        return whole_characters("\n".join(pdf_reader.page_texts(data, max(1, pages))))
    except Exception:
        return ""


def pdf_names_document(data: bytes, kind: str, title: str, iso_date: str) -> Tuple[bool, dict]:
    """Whether a PDF's own text names the document it was taken for, and
    what was checked, as names and yes or no only. Its text must print the
    document's date, or the month its title names. A tax form may instead
    print the year its title begins with, as a number of its own, beside
    "1098" or "tax". A PDF with no text to read names nothing."""
    if not data or data[:5] != b"%PDF-":
        return False, {"pdf": False}
    text = pdf_text(data)
    low = (text or "").lower()
    if kind == "tax":
        # A tax form is named by the year it reports, never by its issue
        # date or month: every January's 1098 prints "January <issue year>",
        # so the date would pass a wrong year's form.
        year = tax_year(title)
        found = bool(year) and on_its_own(year, low)
        form = "1098" in low or "tax" in low
        return found and form, {"pdf": True, "tax_year": found, "tax_form": form}
    verdict = verify(None, Identity(date=iso_date, period=title_period(title)), text=text)
    report = {"pdf": True, "verdict": verdict.report()}
    if verdict.outcome == VERIFIED:
        return True, report
    # Live, a statement prints its own "Statement Date" a day or three after
    # the date the list gives it (the posting date), and a notice its
    # effective date a day off, all as numbers (04/13/31, 8/05/31). So a date
    # the PDF prints within a few days of the list's date, in the month the
    # title names, names the document too.
    offset = nearby_date_offset(low, iso_date, title_period(title))
    report.update(nearby_date=offset)
    return offset is not None, report


# How far from the list's date a document's own printed date may fall, a
# little before it and up to ten days after it.
NEARBY_BEFORE_DAYS = 3
NEARBY_AFTER_DAYS = 10


def _more_variants(day) -> list:
    """The forms the core does not try: a month without its zero before a
    day with one, 8/05/31 and 8/05/2031, as Simmons prints a notice."""
    return ["%d/%02d/%02d" % (day.month, day.day, day.year % 100),
            "%d/%02d/%04d" % (day.month, day.day, day.year)]


def nearby_date_offset(text_lower: str, iso_date: str, period: str) -> Optional[int]:
    """The offset in days of a date the text prints as a number of its own,
    within NEARBY_BEFORE_DAYS before and NEARBY_AFTER_DAYS after `iso_date`
    and inside the month `period` (YYYY-MM, or the list date's own month
    when the title names none), nearest first. None when it prints none."""
    base = answer_date(iso_date)
    if not base or not text_lower:
        return None
    start = _date.fromisoformat(base)
    month = period or base[:7]
    for offset in sorted(range(-NEARBY_BEFORE_DAYS, NEARBY_AFTER_DAYS + 1), key=abs):
        day = start + _timedelta(days=offset)
        if day.isoformat()[:7] != month:
            continue
        for v in date_variants(day.isoformat()) + _more_variants(day):
            if on_its_own(v, text_lower):
                return offset
    return None


# ---------------------------------------------------------------------------
# Diagnose. Reads only, presses nothing. No screenshot.
# ---------------------------------------------------------------------------

def collect_documents(page) -> List[RawDoc]:
    """The document rows drawn now, by type only, and nothing that names the
    account or the document."""
    try:
        rows = read_rows(page)
    except ListStopped:
        return []
    return [RawDoc(title="Document row", text=r.type_word, kind=r.type_word.lower(),
                   row_index=n) for n, r in enumerate(rows)]


def survey(page, dwell_ms: int = 4000, max_follow: int = 0, run: Optional[Run] = None) -> dict:
    """What the signed-in documents page looks like, by counts, without
    pressing or downloading anything. No label of the page's own leaves
    here."""
    page.wait_for_timeout(dwell_ms)
    try:
        texts = _button_texts(page)
        rows = read_rows(page)
        readable = True
    except ListStopped:
        texts, rows, readable = [], [], False
    by_type = Counter(r.type_word for r in rows)
    return {"pages": [{
        "on_documents": is_documents_url(page.url or ""),
        "buttons": len(texts),
        "rows_readable": readable,
        "document_rows": len(rows),
        "statement_rows": by_type.get("Statement", 0),
        "notice_rows": by_type.get("Notice", 0),
        "tax_rows": by_type.get("Tax", 0),
        "accounts_in_rows": len({r.account for r in rows}),
        "available_until_heard": bool(run.available_until) if run else False,
    }]}
