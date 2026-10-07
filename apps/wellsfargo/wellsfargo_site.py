"""ALL wellsfargo.com selectors, URLs, and page behavior live here.

When Wells Fargo changes its site, repair this file only.

STATUS: UNVERIFIED. This app was written without a Wells Fargo account,
from what is publicly known about Wells Fargo Online, so that someone who
holds an account can test it without writing code. Nothing below has run
against the live signed-in site. On a first run it is deliberately
cautious:

  * --login opens a real Edge or Chrome, since wellsfargo.com runs bot
    protection that walls the Playwright build of Chromium.
  * --diagnose surveys whatever the Statements & Documents page turns out
    to be, records its headings, its controls with the guard's verdict on
    each, and the shape of every JSON response, with digit runs masked,
    and takes no screenshot. That file is what a tester attaches to the
    GitHub issue.
  * --discover reads statement dates from any control that looks like a
    statement or tax document, wherever it sits on the page.
  * --pilot tries to save the newest few, by fetching a PDF link the row
    carries from inside the page, or by clicking the row's own control
    and catching a download event, a PDF response or a new tab.

The guesses that most need confirming from a survey are marked GUESS. The
one most likely to matter: Wells Fargo lists statements one account at a
time behind an account picker. The first survey shows what that picker
looks like, and the second round drives it.

SAFETY (this is a bank account that can move money):
  This module is strictly READ-ONLY. It opens Statements & Documents,
  reads the list, and saves the PDFs Wells Fargo already generated. It
  must NEVER activate any control that transfers, pays, sends money by
  Zelle, wires, deposits, opens or closes an account, changes a limit or
  an address, or edits any setting. FORBIDDEN_CONTROL_RE is the guard. A
  control must ALSO look like a document action (SAFE_DOC_CONTROL_RE)
  before it may be clicked. There is no code here that submits a form or
  confirms a dialog.
"""
from __future__ import annotations

import logging
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from paperpull_core.controls import SETTINGS_CONTROL_RE, AUTH_CONTROL_RE

# Everything on its way into a diagnostic file goes through here. It
# lives in core because seventeen apps each had their own copy and
# they drifted into three different versions.
from paperpull_core.redact import redact, set_private_words  # noqa: F401
from paperpull_core.urls import is_safe_url as _host_allows
from paperpull_core.api_census import shape_of as _shape
from paperpull_core.dates import last_day as _last_day
from paperpull_core.dates import human_date as _human_date
# re-exported: this app's docs module calls it as site.set_download_dir
from paperpull_core.capture import set_download_dir  # noqa: F401
from paperpull_core.capture import snapshot as _snapshot
from paperpull_core.capture import take_download as _take_download
from paperpull_core.capture import is_document as _is_document
from paperpull_core.capture import clear_copies as _clear_copies
from paperpull_core.capture import ask_again as _ask_again
from paperpull_core.capture import RequestsSince as _RequestsSince
from paperpull_core.capture import take_new_pdf as _take_new_pdf
from paperpull_core.capture import fetch_pdf as _core_fetch_pdf
from paperpull_core.capture import take_new_tab as _core_take_new_tab
from paperpull_core.capture import take_same_tab as _core_take_same_tab
from paperpull_core.controls import control_texts as _control_texts
from paperpull_core.controls import second_step as _core_second_step
from paperpull_core.controls import controls_named as _controls_named
from paperpull_core.controls import escape_for_locator
from paperpull_core.dates import checked as _checked_date
from paperpull_core.dates import full_year as _full_year
from paperpull_core import pressing
from paperpull_core.words import words_for as _words_for

log = logging.getLogger("wellsfargo_docs.site")


def _words():
    """This app's own words for paperpull_core.words, from what its source
    calls it, for saying what covered a control."""
    return _words_for("Wells Fargo", sys.modules[__name__])


BASE = "https://connect.secure.wellsfargo.com"
# GUESS. Wells Fargo Online's signed-in pages live on connect.secure. The
# Statements & Documents area is under /edocs/. The accounts summary is
# the fallback, since it links to the documents area from a control the
# survey will name.
BILLING_CANDIDATES = [
    f"{BASE}/edocs/statements",
    f"{BASE}/edocs/documents",
    f"{BASE}/accounts/start",
]
BILLING_URL = BILLING_CANDIDATES[0]
URLS = {
    "home": f"{BASE}/accounts/start",
    "login": BILLING_URL,
    "documents": BILLING_URL,
    "statements": BILLING_URL,
}

LOGIN_URL_MARKERS = ["/login", "/signin", "/sign-in", "/auth/", "/mfa",
                     "/verification", "/challenge", "/authenticate"]

# ---------------------------------------------------------------------------
# HARD SAFETY GUARD. Tuned for a bank. Never move money, never open or
# close anything, never change a setting.
# ---------------------------------------------------------------------------
FORBIDDEN_CONTROL_RE = re.compile(
    r"(transfer|zelle|\bwire\b|\bpay\b|payment|bill\s*pay|autopay|auto\s*pay|"
    r"deposit|withdraw|send\s+money|request\s+money|move\s+money|"
    r"\bapply\b|open\s+(an?\s+)?account|close\s+account|\bloan\b|\bborrow|"
    r"\bcard\b|\bcards\b|replace|activate|lock|unlock|\bpin\b|limit|"
    r"overdraft|alerts?\b|\bbudget|\bgoal|\brewards?\b|\boffers?\b|"
    r"enroll|unenroll|sign\s+up|paperless|delivery\s+preference|"
    r"enable|disable|change\b|edit\b|update\b|modify|manage\b|"
    r"set\s+up|delete|remove|cancel|dispute|"
    r"password|passcode|username|profile\b|settings|preferences|contact\s+info|\baddress\b|"
    r"confirm|submit|agree|accept|authorize|\bchat\b|contact\s+us|"
    r"beneficiar|nickname|order\s+checks|stop\s+payment)", re.I)

SAFE_DOC_CONTROL_RE = re.compile(
    r"(download|view|open|print|\bpdf\b|statement|document|\bletter\b|notice|"
    r"1099|1098|5498|tax\s+(form|document)|history|"
    r"see\s+(more|all|older)|show\s+(more|all|older)|load\s+more)", re.I)

# A control that fetches one document. GUESS at the wording, wide on
# purpose. "View", "Download", "View PDF", "Statement", "1099-INT".
BILL_CONTROL_RE = re.compile(
    r"((download|view|print|open|get)\s*(my\s+|the\s+|this\s+|your\s+)?(statement|document|pdf|tax|letter|notice|1099|1098)|"
    r"(statement|document|tax\s+form|1099|1098|5498)\s*\(?\s*pdf\s*\)?|\bpdf\b|"
    r"^\s*(view|download|open)\s*$)", re.I)

# A link that points straight at a PDF, from a row's href.
PDF_HREF_RE = re.compile(r"\.pdf(\?|$)|/pdf\b|format=pdf|statement.*download|download.*statement|docId|documentId", re.I)

SECURITY_CHALLENGE_MARKERS = [
    "enter the code", "verification code", "6-digit", "two-factor",
    "two-step", "authenticator", "confirm your identity", "verify your identity",
    "we sent a code", "device approval", "approve this login", "unusual",
    "are you a robot", "captcha", "let's verify", "check your email",
    "check your phone", "your session has expired", "log back in",
    "access denied", "reference #",
]

RATE_LIMIT_MARKERS = [
    "too many requests", "rate limit", "try again later",
    "temporarily unavailable", "http error 429", "unusual traffic",
]

# ---------------------------------------------------------------------------
# Fallback selectors (used by --diagnose only)
# ---------------------------------------------------------------------------
FALLBACK = {
    "doc_row": ("table tbody tr, [role='row'], [class*='statement'], [class*='Statement'], "
                "li[class*='document'], [class*='document']"),
    "doc_link": "a[href*='.pdf'], a[download], button[class*='download']",
    "download_control": "a[download], a[href$='.pdf'], button:has-text('Download')",
    "page_ready": "table, [role='row'], [class*='statement'], main, [role='main']",
    "next_page": ("a[aria-label*='Next' i], button[aria-label*='Next' i], "
                  "[class*='next']"),
}

# ---------------------------------------------------------------------------
# Date parsing
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
    """The date this provider's page is showing, as YYYY-MM-DD.

    The reading is below, unchanged. This only refuses to believe a result
    that names a day which does not exist, because a reference number is
    shaped like a date and used to be taken for one."""
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


_WORD_VALUE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_ -]{0,23}$")


def _plain_word(v: str) -> bool:
    """"STATEMENT", "LAST_90_DAYS", not an id, a token or a number."""
    return bool(_WORD_VALUE_RE.match(v)) and sum(ch.isdigit() for ch in v) <= 3


def _safe_query(url: str) -> str:
    """A URL's query parameters, names always, values only when they are
    plain words ("docType=STATEMENT", "range=LAST_90_DAYS"). A value with
    a digit, a token, an id, anything long, is "...". This is what a
    repair needs to make the same call with a wider filter, and nothing
    else."""
    from urllib.parse import urlsplit, parse_qsl
    try:
        pairs = parse_qsl(urlsplit(url).query, keep_blank_values=True)
    except ValueError:
        return ""
    out = []
    for k, v in pairs[:20]:
        out.append("%s=%s" % (k[:30], v if _plain_word(v) else "..."))
    return "&".join(out)

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
    """Names the passcode, CAPTCHA or throttling prompt on screen, or None.
    Visible text only. A page's source can carry every string its scripts
    could ever show, "verification code" included, on a normal day."""
    try:
        if _bill_controls(page).count() > 0:
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
    name = (name or "").strip()
    if not name:
        return False
    if FORBIDDEN_CONTROL_RE.search(name):
        return False
    if SETTINGS_CONTROL_RE.search(name) or AUTH_CONTROL_RE.search(name):
        return False
    return bool(SAFE_DOC_CONTROL_RE.search(name))


# ---------------------------------------------------------------------------
# Downloads from a real Edge or Chrome attached over CDP. The browser saves
# the file itself, into its own Downloads folder, and Playwright's download
# event never fires. So the browser is pointed at a folder of ours and that
# folder is watched after every click. The Verizon app found this first.
# AT&T's fourth round found it again, with a trace that showed a clean
# click and nothing arriving.
# ---------------------------------------------------------------------------


def _take_new_tab(page, new_pages, out_path: Path) -> bool:
    """A PDF a click opened in a new tab. The core does the reading, this
    app's guard decides which addresses it may read."""
    return _core_take_new_tab(page, new_pages, out_path, is_safe_url)


# ---------------------------------------------------------------------------
# Billing page
# ---------------------------------------------------------------------------

def dismiss_overlay(page) -> None:
    """Close a cookie banner, a survey prompt or a promo overlay, the things
    that sit over bank pages and intercept clicks. Escape first, then
    only a control that says close or dismiss, never accept."""
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(250)
    except Exception:
        pass
    try:
        cl = page.get_by_role("button", name=re.compile(r"^(close|dismiss|no thanks|not now)\b", re.I))
        for i in range(min(cl.count(), 6)):
            el = cl.nth(i)
            try:
                if el.is_visible():
                    label = el.inner_text(timeout=500) or ""
                    if FORBIDDEN_CONTROL_RE.search(label):
                        continue
                    el.click(timeout=1000)
                    page.wait_for_timeout(250)
            except Exception:
                continue
    except Exception:
        pass


def _bill_controls(page):
    """Every control on the page whose name says it fetches a document.
    The words are this provider's, the rest is the core's."""
    return _controls_named(page, BILL_CONTROL_RE)


def _looks_like_billing(page) -> bool:
    try:
        if _bill_controls(page).count() > 0:
            return True
    except Exception:
        pass
    try:
        body = page.locator("body").inner_text(timeout=5000)
    except Exception:
        return False
    return bool(re.search(r"statements?\s+(and|&)\s+documents|statement\s+(period|date)|tax\s+documents",
                          body, re.I))


def goto_documents(page) -> bool:
    """Open Statements & Documents. The first candidate that is not a
    sign-in page and shows something statement-shaped wins, and the URL it
    lands on is remembered so a later call does not walk the list again."""
    global BILLING_URL
    dismiss_overlay(page)
    if is_safe_url(page.url or "") and not looks_signed_out(page) and _looks_like_billing(page):
        return True
    for url in [BILLING_URL] + [u for u in BILLING_CANDIDATES if u != BILLING_URL]:
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(5000)
        except Exception as e:
            log.info("goto %s failed: %s", url, e)
            continue
        dismiss_overlay(page)
        if looks_signed_out(page):
            return False
        if _looks_like_billing(page):
            BILLING_URL = url
            return True
    return False


def scroll_full_page(page, rounds: int = 8, delay_ms: int = 600) -> None:
    try:
        for _ in range(rounds):
            page.mouse.wheel(0, 3000)
            page.wait_for_timeout(delay_ms)
        page.keyboard.press("End")
        page.wait_for_timeout(delay_ms)
    except Exception:
        pass


def expand_all(page) -> None:
    """Click 'See more' / 'Show more' / 'View older statements' repeatedly
    to surface anything the page loads on demand. The label is
    checked against the guard before every click."""
    pat = re.compile(r"^\s*(show|load|view|see)\s+(more|all|older)(\s+(bills?|statements?|documents?))?\s*$|"
                     r"^\s*(older|previous)\s+(bills?|statements?)\s*$", re.I)
    for _ in range(30):
        clicked = False
        for role in ("button", "link"):
            try:
                loc = page.get_by_role(role, name=pat)
                if loc.count() > 0 and loc.first.is_visible():
                    label = loc.first.inner_text(timeout=1000) or ""
                    if is_safe_control(label):
                        loc.first.click()
                        page.wait_for_timeout(1500)
                        clicked = True
                        break
            except Exception:
                continue
        if not clicked:
            break


@dataclass
class RawDoc:
    title: str
    account: str = ""
    date_text: str = ""
    href: str = ""
    text: str = ""
    row_index: int = -1
    kind: str = "doc"
    # How many rows of the page hold a document of this date and kind. Rows
    # past the first cannot be told apart from it, so the download refuses
    # the document rather than guess which one it is.
    rows: int = 1


class _Found(list):
    """The documents discovery found, with counts of the document controls
    that would not answer and of those whose two readings disagree."""
    unread = 0
    unsure = 0


# What a document is, read from the control that fetches it. Discovery
# names a document by its date and kind, and the download finds its control
# again by the same reading, so the two cannot disagree about which document
# a control fetches. A statement and a 1099 of one day are two documents.
#
# Each control is read twice. Once the way this app always read it, its date
# from its name or else from the first date printed around it, and its kind
# from any tax word in its name or around it. And once with care, never
# taking a date printed in another control or in a list of rows, and taking
# its kind from its own words and then the nearest words around it that
# are not another control's (see _kind_of). A control is a document only
# where both readings agree on its date and its kind. Where they disagree,
# the page is one this app does not understand, and the control is counted
# and left alone, so nothing is filed under a kind or a date the old reading
# would not have given it either.
#
# A tax form, read with care, is 1099, 1098 or 5498 as a number of its own,
# 1099INT as much as 1099-INT, or the word tax on its own. Read the old way,
# it is any of them anywhere.
_TAX_RE = re.compile(r"(?<![$\d.,])\b(1099|1098|5498)(?![.,]?\d)|\btax\b", re.I)
_TAX_AS_BEFORE_RE = re.compile(r"1099|1098|5498|tax", re.I)
_STATEMENT_RE = re.compile(r"\bstatements?\b", re.I)

# The words a document's title starts with, by its kind. Discovery writes
# the title from these, and the download reads the kind back out of it.
KIND_TITLES = {"tax": "Tax Document", "statement": "Account Statement"}

# How long a control has to answer a read, in milliseconds.
_READ_MS = 2000


def kind_of_title(title: str) -> Optional[str]:
    """The kind of document a title written by collect_download_docs names,
    or None for a title it did not write."""
    for kind, words in KIND_TITLES.items():
        if (title or "").startswith(words + " - "):
            return kind
    return None


def _kind_of(own: str, chain) -> str:
    """Which kind of document a control fetches, read with care. What its
    own words name, a tax form or a statement. Otherwise the nearest words
    around it that name a kind, so an entry printing "Account statement" is
    a statement under a heading that says tax. `chain` is what each element
    around the control prints of its own, nearest first, with every other
    document control's part left out, so a 1099's link beside a statement's
    says nothing of the statement. With no such words it is a statement, as
    it always was."""
    if _TAX_RE.search(own):
        return "tax"
    if _STATEMENT_RE.search(own):
        return "statement"
    for words in chain:
        if _TAX_RE.search(words):
            return "tax"
        if _STATEMENT_RE.search(words):
            return "statement"
    return "statement"


# Where a control sits, read in the page.
#
# "rowText" is the text of the nearest element around the control that
# prints a date, the control itself first, up to six levels up, the way
# this app always read it. "date" is the same element read with care, never
# a list and never another control's words. An element holding another
# document control whose own date is printed nearer to it is a list or a
# section, and a date printed there belongs to something else. A control
# that prints its own date has its date printed in its row. A heading over
# entries that print no date of their own is their date.
#
# "row" numbers the entry the control belongs to, the same number for every
# control of one entry and a different one for any other, so two entries
# printing the same words are still two. An entry is the control's table or
# grid row. Without one it is the outermost part, inside the element that
# printed the date, that prints words of its own outside any part holding a
# document control, so a menu of View and Download is never an entry but
# each of two accounts under one date is. Without that it is the element
# that printed the date, and without a date around it the control's list
# item, or the control alone. "up" numbers what holds the entry, so a part
# of an entry is known to be inside it.
#
# "own" is the control's visible text. "chain" is what each element around
# it prints of its own, nearest first, up to the element that printed the
# date, leaving out any part that holds another document control and every
# date. They say what kind of document the control fetches. The numbers are
# kept in a map on the page's window and nothing is written into the page.
_WHERE_JS = r"""(el, pattern) => {
  const dateRe = /(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}|\d{1,2}\/\d{1,2}\/\d{2,4}|\d{4}-\d{2}-\d{2}/i;
  const everyDate = new RegExp(dateRe.source, 'gi');
  const bill = new RegExp(pattern, 'i');
  const key = Symbol.for('paperpull.rows');
  const store = window[key] || (window[key] = {ids: new WeakMap(), next: 1});
  const idOf = (n) => {
    if (!store.ids.has(n)) store.ids.set(n, store.next++);
    return store.ids.get(n);
  };
  const ROWS = 'tr, [role=row], li';
  const CONTROLS = 'a, button, [role=button], [role=link]';
  const isDoc = (c) => bill.test((c.getAttribute('aria-label') || c.innerText || '').replace(/\s+/g, ' ').trim());
  const docsIn = (n) => Array.from(n.querySelectorAll(CONTROLS)).filter(isDoc);
  const holding = new Map();
  const holdsDoc = (n) => {
    if (!holding.has(n)) holding.set(n, (n.matches(CONTROLS) && isDoc(n)) || docsIn(n).length > 0);
    return holding.get(n);
  };
  const datedAround = (c) => {
    for (let node = c, depth = 0; node && depth < 6; node = node.parentElement, depth++)
      if (dateRe.test(node.innerText || '')) return node;
    return null;
  };
  const datedRowOf = (c) => {
    const d = datedAround(c);
    return d === c ? (c.closest(ROWS) || c) : d;
  };
  const asBefore = datedAround(el);
  const rowText = asBefore ? (asBefore.innerText || '').trim().slice(0, 300) : '';
  let dated = asBefore;
  if (dated && docsIn(dated).some(c => {
    if (c === el || c.contains(el) || el.contains(c)) return false;
    const theirs = datedRowOf(c);
    return theirs !== null && theirs !== dated && dated.contains(theirs);
  })) dated = null;
  // The text an element shows outside every document control but this one.
  const outsideOthers = (a) => {
    const out = [];
    const walker = document.createTreeWalker(a, NodeFilter.SHOW_TEXT);
    for (let t = walker.nextNode(); t; t = walker.nextNode()) {
      const host = t.parentElement;
      if (!host || !host.getClientRects().length || getComputedStyle(host).visibility !== 'visible') continue;
      const control = host.closest(CONTROLS);
      if (control && control !== el && !control.contains(el) && a.contains(control) && isDoc(control)) continue;
      const s = (t.textContent || '').trim();
      if (s) out.push(s);
    }
    return out.join(' ');
  };
  const date = dated ? outsideOthers(dated).slice(0, 300) : '';
  const bound = dated && dated !== el ? dated : (el.closest(ROWS) || el);
  const wordsOf = (a) => {
    const out = [];
    const walker = document.createTreeWalker(a, NodeFilter.SHOW_TEXT);
    for (let t = walker.nextNode(); t; t = walker.nextNode()) {
      const host = t.parentElement;
      if (!host || !host.getClientRects().length || getComputedStyle(host).visibility !== 'visible') continue;
      let held = false;
      for (let n = host; n && n !== a; n = n.parentElement) if (holdsDoc(n)) { held = true; break; }
      if (held) continue;
      const s = (t.textContent || '').replace(everyDate, ' ').replace(/\s+/g, ' ').trim();
      if (/[A-Za-z0-9]/.test(s)) out.push(s);
    }
    return out.join(' ');
  };
  const chain = [];
  let worded = null;
  for (let n = el.parentElement; n && bound.contains(n); n = n.parentElement) {
    const w = wordsOf(n);
    chain.push(w.slice(0, 300));
    if (w) worded = n;
  }
  const table = el.closest('tr, [role=row]');
  const row = table && bound.contains(table) ? table : (worded || bound);
  const up = [];
  for (let n = row.parentElement; n; n = n.parentElement) up.push(idOf(n));
  return {rowText, date, own: (el.innerText || '').trim().slice(0, 300), chain, row: idOf(row), up};
}"""


@dataclass
class _Seen:
    """One document control, as a look at the page read it."""
    index: int      # its place among the page's document controls
    name: str       # its own words, the ones the guard passed
    href: str
    iso: str        # the date of the document it fetches
    kind: str       # "tax" or "statement"
    row: int        # the entry it belongs to, alike for every control of it
    up: tuple = ()  # what holds that entry, nearest first
    doubt: str = ""  # "date" or "kind" when its two readings disagree on it


class _Survey(list):
    """Every document control a look at the page could read and file, with
    counts of the controls that would not answer and of those whose two
    readings disagree."""
    unread = 0
    unsure = 0


def _read_control(el, index: int, wait: Optional[int] = _READ_MS) -> Optional[_Seen]:
    """What one control fetches, or None when it is not a dated document
    control the guard lets through. Raises when the control would not
    answer, because a control that could not be read is not a control that
    is absent. `el` is a locator, read with a `wait`, or an element handle
    already found, read with none. The answer's `doubt` names what the two
    readings of it disagree on, and such a control is filed as nothing."""
    wait_for = {"timeout": wait} if wait else {}
    name = (el.get_attribute("aria-label", **wait_for)
            or el.inner_text(**wait_for) or "").strip()
    if not is_safe_control(name):
        return None
    where = el.evaluate(_WHERE_JS, BILL_CONTROL_RE.pattern, **wait_for) or {}
    row_text = str(where.get("rowText") or "")
    named = parse_date(name)
    iso = named or parse_date(str(where.get("date") or ""))
    iso_as_before = named or parse_date(row_text)
    if not iso and not iso_as_before:
        return None
    try:
        href = el.get_attribute("href", **wait_for) or ""
    except Exception:
        href = ""      # shown in a survey, never what decides anything
    kind = _kind_of(name + " " + str(where.get("own") or ""), [str(w) for w in where.get("chain") or ()])
    kind_as_before = "tax" if _TAX_AS_BEFORE_RE.search(name + " " + ("" if named else row_text)) else "statement"
    doubt = "date" if iso != iso_as_before else ("kind" if kind != kind_as_before else "")
    return _Seen(index, name, href, iso or iso_as_before, kind, int(where.get("row") or 0),
                 tuple(where.get("up") or ()), doubt)


def _rows_of(controls) -> set:
    """The entries a document's controls sit in that hold no other of them.
    A control in an entry and another in a part of it fetch one document,
    and two entries apart from each other hold two."""
    rows = {c.row for c in controls}
    return {r for r in rows if not any(r in c.up for c in controls)}


def _survey(page) -> _Survey:
    """Every document control on the page, read one at a time. Discovery
    names documents from this and the download finds its control again
    from it, so the two read a control the same way."""
    out = _Survey()
    ctrls = _bill_controls(page)
    try:
        count = ctrls.count()
    except Exception:
        out.unread += 1
        return out
    for i in range(count):
        try:
            seen = _read_control(ctrls.nth(i), i)
        except Exception:
            out.unread += 1
            continue
        if seen is None:
            continue
        if seen.doubt:
            out.unsure += 1
            continue
        out.append(seen)
    return out


def collect_download_docs(page) -> List[RawDoc]:
    """Read every statement and tax document the page offers, one for each
    date and kind, so a statement and a 1099 of one day are both found.

    Two rows of one day holding the same kind cannot be told apart. That
    document is recorded once, with the number of its rows, and the
    download refuses it rather than guess. A control that would not answer
    is counted and left for the next run, and lends no other control its
    date or its kind. So is a control whose two readings disagree on its
    date or its kind, which is left for a person."""
    expand_all(page)
    scroll_full_page(page)
    survey = _survey(page)
    by_document: dict = {}
    for seen in survey:
        by_document.setdefault((seen.iso, seen.kind), []).append(seen)
    docs = _Found()
    docs.unread, docs.unsure = survey.unread, survey.unsure
    for (iso, kind), controls in by_document.items():
        first = controls[0]
        disp = _human_date(iso)
        kind_title = KIND_TITLES[kind]
        docs.append(RawDoc(title=f"{kind_title} - {disp}", date_text=iso,
                           href=first.href if PDF_HREF_RE.search(first.href or "") else "",
                           text=f"Wells Fargo {kind_title} {disp}", row_index=first.index,
                           kind=kind, rows=len(_rows_of(controls))))
    if survey.unread:
        log.info("%d document controls would not answer, what they hold waits for the next run",
                 survey.unread)
    if survey.unsure:
        log.info("%d document controls read two ways disagree on their date or kind, and are left for a person",
                 survey.unsure)
    shared = sum(1 for d in docs if d.rows > 1)
    if shared:
        log.info("%d documents share their date and kind with another row, none of them is guessed at",
                 shared)
    return docs


# Why the download pressed nothing, in the only words that may say so.
_REFUSALS = (
    "the title does not say which kind of document it is",
    "discovery found more than one row of this date holding this kind of document",
    "a document control on the page could not be read",
    "no control of this date is this kind of document",
    "more than one row of this date holds this kind of document",
    "the control was not the same when read again",
)


def _refuse(trace: Optional[list], why: str, iso: str, survey=(), mine=()) -> None:
    """Write down why nothing was pressed, in fixed words and counts."""
    log.info("pressed nothing for the document of %s, %s", iso, why)
    if trace is not None:
        trace.append({"note": "nothing was pressed",
                      "why": why if why in _REFUSALS else "unrecognized",
                      "controls_read": len(survey),
                      "unread": int(getattr(survey, "unread", 0)),
                      "unsure": int(getattr(survey, "unsure", 0)),
                      "rows_of_this_date_and_kind": len(_rows_of(mine))})


def _control_for(page, iso: str, kind: Optional[str], trace: Optional[list] = None,
                 rows_found: int = 1):
    """The control for the document of date `iso` and kind `kind`, read the
    way discovery read it, or (None, "") with the reason written down.

    `rows_found` is how many rows of this date and kind discovery saw. More
    than one is refused at once, since a twin discovery scrolled into view
    may not be drawn when the download looks. Then the whole page is read.
    A control that would not answer could be this document's twin, and a
    second row of this date holding this kind is another document, so
    either means nothing is pressed. Of the one row's controls the first is
    taken, as it always was. It is found once more as an element, read
    again through that element, and that element is what is handed back,
    so the control pressed is the one that was read."""
    if kind not in KIND_TITLES:
        _refuse(trace, "the title does not say which kind of document it is", iso)
        return None, ""
    if rows_found > 1:
        _refuse(trace, "discovery found more than one row of this date holding this kind of document", iso)
        return None, ""
    survey = _survey(page)
    mine = [c for c in survey if c.iso == iso and c.kind == kind]
    rows = _rows_of(mine)
    if survey.unread:
        _refuse(trace, "a document control on the page could not be read", iso, survey, mine)
        return None, ""
    if not mine:
        _refuse(trace, "no control of this date is this kind of document", iso, survey, mine)
        return None, ""
    if len(rows) > 1:
        _refuse(trace, "more than one row of this date holds this kind of document", iso, survey, mine)
        return None, ""
    chosen = mine[0]
    try:
        el = _bill_controls(page).nth(chosen.index).element_handle(timeout=_READ_MS)
        again = _read_control(el, chosen.index, wait=None)
    except Exception:
        el, again = None, None
    if again is None or (again.name, again.iso, again.kind, again.row, again.doubt) != \
            (chosen.name, chosen.iso, chosen.kind, chosen.row, ""):
        _refuse(trace, "the control was not the same when read again", iso, survey, mine)
        return None, ""
    return el, chosen.name


def _fetch_pdf(page, href: str, zip_ok: bool = False) -> Optional[bytes]:
    """A PDF link fetched from inside the signed-in page, cookies and all.
    The fetching is the core's, the hosts are this app's."""
    return _core_fetch_pdf(page, href, is_safe_url, zip_ok=zip_ok)


def _take_same_tab(page, start_url: str, out_path: Path, trace) -> bool:
    """A PDF the click opened in this very tab. The core does the reading,
    this app's guard decides which addresses it may read."""
    return _core_take_same_tab(page, start_url, out_path, trace, is_safe_url)


_SECOND_STEP_RE = re.compile(
    r"^\s*(download|download\s+(pdf|now|file|statement|document)|save|save\s+(as\s+)?pdf|"
    r"(regular|standard|full|detailed)\s+pdf|pdf|view\s*/\s*print\s+pdf|print|open\s+pdf)\s*$", re.I)


def _second_step(page, appeared: set):
    """A control the click revealed whose text says it finishes a download,
    once it has passed the guard, or None. The choosing is the core's, the
    words this provider uses and the guard are this app's."""
    return _core_second_step(page, appeared, _SECOND_STEP_RE, is_safe_control)


def _catch_pdf(page, el, label: str, out_path: Path, trace: Optional[list] = None,
               dl_dir=None) -> bool:
    """Click `el` and save whatever PDF the site produces, a file landing
    in `dl_dir`, a download event, a PDF response, a new tab, this tab
    moving to the document, or a second control the click revealed.
    `trace` collects what happened, the click's own outcome included."""
    ctx = page.context
    got: dict = {}
    downloads: list = []
    # Answers to a request this press made, from its tab or one it opened,
    # that called themselves a PDF and read empty. Asked for once more only
    # when nothing else brings the document (capture.ask_again).
    empty_answers: list = []
    made_here = _RequestsSince(page, ctx.pages)
    start_url = page.url or ""

    def on_download(dl):
        downloads.append(dl)

    def on_response(res):
        try:
            url = res.url or ""
            if not is_safe_url(url):
                return
            ct = (res.headers.get("content-type") or "").lower()
            if trace is not None and ("json" in ct or "pdf" in ct or "octet" in ct or "zip" in ct):
                trace.append({"status": res.status, "type": ct[:40], "url": redact(url)[:160]})
            if got:
                return
            if "pdf" in ct or "octet" in ct:
                try:
                    body = res.body()
                except Exception:
                    body = b""
                    got["refetch"] = url
                if body[:5] == b"%PDF-":
                    got["body"] = body
                elif not body and not got and made_here.made(res.request) \
                        and (res.request.method, url) not in empty_answers:
                    # A PDF the page reads into a blob leaves its answer
                    # empty under Playwright 1.63 (capture.ask_again).
                    empty_answers.append((res.request.method, url))
        except Exception:
            pass

    ctx.on("response", on_response)
    page.on("download", on_download)
    before = set(ctx.pages)
    seen = _snapshot(dl_dir)
    controls_before = _control_texts(page)

    def landed() -> bool:
        # Pointed at a folder, the browser can save the only copy there and
        # leave the event's own file empty, so that file is taken rather than
        # the document asked for a second time (capture.take_download).
        if downloads and _take_download(downloads[0], dl_dir, seen, out_path, zip_ok=True):
            return True
        if got.get("body"):
            out_path.write_bytes(got["body"])
            return True
        if got.get("refetch"):
            try:
                # This address answered the press directly, so asking it
                # again needs no redirect, and one would take the
                # browser's cookies wherever it led.
                resp = page.context.request.get(got.pop("refetch"), max_redirects=0,
                                                timeout=60000)
                body = resp.body() if resp.ok else b""
                if _is_document(body, zip_ok=True):
                    out_path.write_bytes(body)
                    return True
            except Exception:
                pass
        return _take_new_pdf(dl_dir, seen, out_path, zip_ok=True)

    def wait_for_pdf(seconds: int) -> bool:
        for _ in range(seconds):
            if landed():
                return True
            page.wait_for_timeout(1000)
        return landed()

    try:
        try:
            el.scroll_into_view_if_needed(timeout=4000)
        except Exception:
            pass
        # Playwright's own press, and through the page only when nothing
        # covered the control, its press never reached the page and nothing
        # it should bring came. What cannot be told stops the run, and the
        # control is never pressed twice (pressing.press_once).
        outcome = pressing.press_once(
            page, el, what="the control for this document", words=_words(),
            guard=is_safe_control, dl_dir=dl_dir,
            brought=lambda: bool(downloads or got or (_control_texts(page) - controls_before)))
        if trace is not None:
            if outcome.error is None:
                trace.append({"note": "clicked", "control": redact(label)[:60]})
            else:
                trace.append({"note": "click failed", "control": redact(label)[:60],
                              "error": str(outcome.error)[:160]})
            if outcome.how == pressing.MADE:
                trace.append({"note": "the press reached the page although it raised, "
                                      "so it was not made again", "control": redact(label)[:60]})
            elif outcome.how == pressing.THROUGH_THE_PAGE and outcome.page_error is None:
                trace.append({"note": "clicked through the DOM instead", "control": redact(label)[:60]})
            elif outcome.how == pressing.THROUGH_THE_PAGE:
                trace.append({"note": "DOM click failed too", "error": str(outcome.page_error)[:160]})
        if wait_for_pdf(10):
            return True
        if _take_same_tab(page, start_url, out_path, trace):
            return True
        if _take_new_tab(page, [p for p in ctx.pages if p not in before], out_path):
            return True
        appeared = _control_texts(page) - controls_before
        if trace is not None:
            trace.append({"note": "after the click", "url": redact(page.url or "")[:160],
                          "appeared": [redact(t) for t in sorted(appeared)[:15]],
                          "new_tabs": len([p for p in ctx.pages if p not in before])})
        step, step_label = _second_step(page, appeared)
        if step is not None:
            try:
                step.click(timeout=8000)
                if trace is not None:
                    trace.append({"note": "second step clicked", "control": redact(step_label)[:60]})
            except Exception as e:
                if trace is not None:
                    trace.append({"note": "second step click failed", "control": redact(step_label)[:60],
                                  "error": str(e)[:160]})
            if wait_for_pdf(20):
                return True
            if _take_same_tab(page, start_url, out_path, trace) or \
                    _take_new_tab(page, [p for p in ctx.pages if p not in before], out_path):
                return True
        if wait_for_pdf(15):
            return True
        if _take_new_tab(page, [p for p in ctx.pages if p not in before], out_path):
            return True
        # Nothing else brought it, so the one answer that read empty is asked
        # for once more (capture.ask_again).
        if _ask_again(page, empty_answers, out_path, is_safe_url, zip_ok=True):
            return True
        log.info("click on %r produced no PDF", label)
        return False
    finally:
        made_here.stop()
        try:
            ctx.remove_listener("response", on_response)
        except Exception:
            pass
        try:
            page.remove_listener("download", on_download)
        except Exception:
            pass
        for extra in [p for p in ctx.pages if p not in before]:
            try:
                extra.close()
            except Exception:
                pass
        # What the browser saved into the folder while the document came
        # some other way, read off the answer or asked for again, goes when
        # it is an exact copy of the one saved (capture.clear_copies).
        try:
            _clear_copies(dl_dir, seen, out_path)
        except Exception:
            pass


def download_bill(page, dl_dir, iso_date: str, out_path, title: str = "",
                  trace: Optional[list] = None, rows: int = 1) -> bool:
    """Save the document dated `iso_date` of the kind its `title` names,
    the title discovery wrote. A PDF link on the row is fetched from inside
    the page. Otherwise the row's own control is clicked, once it has
    passed the guard, and whichever the site produces is caught, a
    download event or a PDF response, in this tab or one it opens.

    `dl_dir` is where the attached browser saves a download, watched
    after every click. `rows` is how many rows of the page discovery found
    holding a document of this date and kind."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if not goto_documents(page):
        log.info("could not open the documents page for %s", iso_date)
        return False
    expand_all(page)

    el, label = _control_for(page, iso_date, kind_of_title(title), trace, rows)
    if el is None:
        return False
    if not is_safe_control(label):
        log.info("refusing unsafe control %r for %s", label, iso_date)
        return False

    try:
        href = el.get_attribute("href") or ""
    except Exception:
        href = ""
    if href and not href.lower().startswith(("javascript", "#")):
        from urllib.parse import urljoin
        target = urljoin(page.url, href)
        # A link on the provider's own hosts is fetched through the session
        # first. A PDF answer is the document. Anything else means the link
        # is a page or a handoff, and the click below follows it.
        if is_safe_url(target):
            body = _fetch_pdf(page, target, zip_ok=True)
            if body:
                out_path.write_bytes(body)
                return True
            if trace is not None:
                trace.append({"note": "the control's own link did not answer with a PDF",
                              "url": redact(target)[:160]})
    return _catch_pdf(page, el, label, out_path, trace, dl_dir)


# ---------------------------------------------------------------------------
# Diagnose. A survey a tester can attach to an issue. No screenshot, since a
# bank page shows names, numbers and balances. Digit runs are masked and
# JSON bodies are recorded as shape only.
# ---------------------------------------------------------------------------
_ROW_JS = r"""() => {
  const out = [];
  for (const tr of document.querySelectorAll('table tr, [role=row], li, [class*="bill" i]')) {
    const txt = (tr.innerText || '').trim();
    if (!txt) continue;
    const link = tr.querySelector("a[href]");
    out.push({text: txt.slice(0, 200), href: link ? link.getAttribute('href') : ''});
  }
  return out.slice(0, 200);
}"""

SURVEY_LINK_RE = re.compile(
    r"^\s*((see|view|show)\s+)?(statements?(\s+(and|&)\s+documents)?|documents|"
    r"tax\s+documents|statement\s+history)\s*$", re.I)


def collect_documents(page) -> List[RawDoc]:
    """Loose row scrape used only by --diagnose. Every row that carries a
    date, a link or the word download, with digits masked."""
    docs: List[RawDoc] = []
    seen = set()
    try:
        rows = page.evaluate(_ROW_JS)
    except Exception:
        rows = []
    for i, r in enumerate(rows):
        text = redact((r.get("text") or "").strip())
        if not text:
            continue
        has_date = parse_date(text) or MONTH_YEAR_RE.search(text)
        href = redact(r.get("href", "") or "")
        if not (has_date or href or "download" in text.lower()):
            continue
        title = text.splitlines()[0][:200]
        date_text = next((ln for ln in text.splitlines()
                          if parse_date(ln) or MONTH_YEAR_RE.search(ln)), "")
        key = (title, date_text, href, text[:60])
        if key in seen:
            continue
        seen.add(key)
        docs.append(RawDoc(title=re.sub(r"\s+", " ", title), date_text=date_text,
                           href=href, text=text[:400], row_index=i))
    # A row with a date is a document row, and those are what a repair
    # wants to see first, ahead of a nav full of links.
    docs.sort(key=lambda d: 0 if d.date_text else 1)
    return docs


def _page_summary(page) -> dict:
    out = {"url": redact(page.url or ""), "title": ""}
    try:
        out["title"] = redact(page.title() or "")
    except Exception:
        pass
    try:
        heads = page.locator("h1, h2, h3").all_inner_texts()
        out["headings"] = [redact(h.strip())[:80] for h in heads if h.strip()][:30]
    except Exception:
        out["headings"] = []
    controls = []
    for role in ("link", "button", "tab", "menuitem"):
        try:
            loc = page.get_by_role(role)
            for i in range(min(loc.count(), 100)):
                el = loc.nth(i)
                try:
                    text = (el.inner_text(timeout=300) or "").strip()
                except Exception:
                    text = ""
                if not text:
                    try:
                        text = (el.get_attribute("aria-label") or "").strip()
                    except Exception:
                        text = ""
                if not text:
                    continue
                href = ""
                if role == "link":
                    try:
                        href = el.get_attribute("href") or ""
                    except Exception:
                        pass
                controls.append({"role": role, "text": redact(text)[:60],
                                 "href": redact(href)[:120],
                                 "safe": is_safe_control(text),
                                 "bill": bool(BILL_CONTROL_RE.search(text)),
                                 "survey": bool(SURVEY_LINK_RE.match(text.strip()))})
        except Exception:
            pass
    out["controls"] = controls
    out["bill_controls"] = sum(1 for c in controls if c["bill"])
    return out


def survey(page, dwell_ms: int = 4000, max_follow: int = 6) -> dict:
    """What the signed-in documents area looks like, without downloading
    anything. Records each page, its headings and controls with the
    guard's verdict on each, and every JSON or PDF response wellsfargo.com sends
    while the page settles. Then follows, one at a time and back again,
    the few links whose text is a documents word. No screenshot."""
    seen: list = []

    def on_response(res):
        try:
            url = res.url or ""
            if not is_safe_url(url):
                return
            ct = (res.headers.get("content-type") or "").lower()
            if "json" not in ct and "pdf" not in ct:
                return
            entry = {"url": redact(url)[:200], "status": res.status, "type": ct[:40]}
            try:
                entry["method"] = res.request.method
                body = res.request.post_data or ""
                if body.lstrip().startswith("{"):
                    import json as _json
                    parsed = _json.loads(body)
                    if isinstance(parsed, dict):
                        entry["post_keys"] = sorted(str(k) for k in parsed)[:30]
            except Exception:
                pass
            q = _safe_query(url)
            if q:
                entry["query"] = q[:240]
            if "json" in ct:
                try:
                    entry["shape"] = _shape(res.json())
                except Exception:
                    entry["shape"] = "unreadable"
            seen.append(entry)
        except Exception:
            pass

    page.on("response", on_response)
    report = {"pages": [], "responses": seen}
    try:
        page.wait_for_timeout(dwell_ms)
        start = _page_summary(page)
        report["pages"].append(start)
        followed = 0
        for c in start["controls"]:
            if followed >= max_follow or c["role"] not in ("link", "button") or not c["survey"]:
                continue
            if not is_safe_control(c["text"]):
                continue
            try:
                link = page.get_by_role(c["role"], name=re.compile(
                    "^" + escape_for_locator(c["text"].replace("#", "")) + "$", re.I)).first
                if link.count() == 0:
                    continue
                before = page.url
                tabs_before = set(page.context.pages)
                link.click(timeout=5000)
                page.wait_for_timeout(dwell_ms)
                # A control that opened a new tab (a document vendor behind
                # a single sign-on, a PDF) is surveyed there, then the tab
                # is closed. Off the provider's hosts it is still recorded,
                # marked, and nothing on it is followed.
                for extra in [p for p in page.context.pages if p not in tabs_before]:
                    try:
                        extra.wait_for_load_state("domcontentloaded", timeout=15000)
                        tab = _page_summary(extra)
                        tab["opened_tab_from"] = c["text"]
                        tab["off_host"] = not is_safe_url(extra.url or "")
                        report["pages"].append(tab)
                    except Exception as e:
                        report.setdefault("notes", []).append(
                            "could not read the tab %r opened: %s" % (c["text"], str(e)[:120]))
                    try:
                        extra.close()
                    except Exception:
                        pass
                if not is_safe_url(page.url or ""):
                    page.go_back()
                    continue
                summary = _page_summary(page)
                summary["followed_from"] = c["text"]
                report["pages"].append(summary)
                followed += 1
                if page.url != before:
                    page.go_back(wait_until="domcontentloaded", timeout=15000)
                    page.wait_for_timeout(1500)
            except Exception as e:
                report.setdefault("notes", []).append(
                    "could not follow %r: %s" % (c["text"], str(e)[:120]))
    finally:
        try:
            page.remove_listener("response", on_response)
        except Exception:
            pass
    return report


# ---------------------------------------------------------------------------
# Host allowlist. Parsed, never a string prefix, so a lookalike host cannot
# walk through.
# ---------------------------------------------------------------------------
ALLOWED_HOSTS = {"wellsfargo.com"}


def is_safe_url(url: str) -> bool:
    """True only for an https URL on one of this provider's own hosts.

    The check itself lives in the core, so all of them answer the same way.
    This app keeps the hosts, which is the part that really is its own."""
    return _host_allows(url, ALLOWED_HOSTS)
