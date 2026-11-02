"""ALL American Express selectors, URLs, and page behavior live here.

When Amex changes its site, repair THIS file only.

SAFETY (this is a credit-card account):
  This module is strictly READ-ONLY. It navigates to the statements / documents
  / year-end-summary / tax areas, reads a list of documents, and downloads the
  PDFs Amex already generated. It must NEVER activate any control that pays a
  bill, transfers a balance, moves money, redeems rewards/points, applies for a
  card or product, disputes a charge, books travel, cancels a card, or changes
  any setting. FORBIDDEN_CONTROL_RE is the guard; a control must ALSO look like
  a document action (SAFE_DOC_CONTROL_RE) before it may be clicked. There is no
  code here that submits a form or confirms a dialog.

  Every press a run makes goes through paperpull_core.pressing, never
  forced. A control is brought to the middle of the window and pressed only
  when it is the thing on top there, and otherwise nothing is pressed and
  the run stops. A forced press once landed on a chat bubble over the last
  Download button, and the presses after it on the chat's suggested
  replies. next_page alone still presses through controls.click_next_page,
  unforced, and nothing calls it.

Amex is a heavy React SPA behind Akamai. The signed-in browser session (opened
by login.bat and attached over CDP) carries the auth, so this module only reads
and clicks document/download controls. Statement PDFs may be plain <a> download
links, may sit behind a period selector, or may be produced by a JSON/PDF
endpoint - collect_download_docs + download_named handle the link case and are
refined against the real DOM via paperpull amex diagnose.
"""
# Site layer verified working against the live site: 2026-08
from __future__ import annotations

import html as _html
import logging
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from paperpull_core import intake
from paperpull_core import pressing
from paperpull_core.dates import last_day as _last_day
from paperpull_core.dates import human_date as _human_date
from paperpull_core.dates import checked as _checked_date
from paperpull_core.controls import click_next_page as _click_next_page
from paperpull_core.failure import error_kind as _error_kind
from paperpull_core.words import words_for as _words_for

log = logging.getLogger("amex_docs.site")


def _words():
    """This app's own words for paperpull_core.words, from what its source
    calls it, for saying what covered a control."""
    return _words_for("American Express", sys.modules[__name__])

BASE = "https://global.americanexpress.com"
URLS = {
    "home": "https://www.americanexpress.com/",
    "login": "https://www.americanexpress.com/en-us/account/login/",
    "dashboard": f"{BASE}/dashboard",
    # Document-area candidates (Amex moves these around). goto_documents tries
    # each; if none render a list, it uses whatever page is open.
    "statements": f"{BASE}/activity/statements",
    "documents": f"{BASE}/activity/document-center",
    "year_end": f"{BASE}/spending-report",
    "tax": f"{BASE}/activity/statements",
}

LOGIN_URL_MARKERS = ["/login", "/logon", "/signin", "/sign-in", "/auth",
                     "/mfa", "/verification", "/challenge", "myca/logon"]

# ---------------------------------------------------------------------------
# HARD SAFETY GUARD - never click anything matching this. Tuned for a
# credit-card account.
# ---------------------------------------------------------------------------
FORBIDDEN_CONTROL_RE = re.compile(
    r"(pay\b|pay\s+bill|make\s+a?\s*payment|autopay|auto\s*pay|"
    r"balance\s+transfer|transfer|withdraw|deposit|wire\b|move\s+money|"
    r"send\b|redeem|reward|points\b|membership\s+rewards|cash\s*back\b|"
    r"apply|apply\s+now|add\s+card|add\s+account|link\s+(bank|account)|"
    r"dispute|report\s+(fraud|lost|stolen)|book\b|travel\b|reservation|"
    r"cancel|close\s+account|activate|replace\s+card|lock\b|freeze\b|"
    r"enable|disable|\bchange\s+|\bedit\s+|\bupdate\s+|set\s+up|manage\b|"
    r"delete|remove|beneficiar|password|username|"
    r"enroll|subscribe|upgrade|offer\b|refer\b|"
    r"confirm|continue|next\b|agree|accept|authorize|submit)", re.I)

SAFE_DOC_CONTROL_RE = re.compile(
    r"(download|view|open|print|pdf|statement|document|summary|"
    r"year.?end|1099|1098|tax|export)", re.I)

SECURITY_CHALLENGE_MARKERS = [
    "enter the code", "verification code", "6-digit", "one-time code",
    "two-factor", "two-step", "authenticator", "confirm your identity",
    "verify your identity", "we sent a code", "we'll send", "check your email",
    "check your phone", "your session has expired", "log back in",
    "are you a robot", "captcha", "let's confirm it's you", "unusual activity",
]

RATE_LIMIT_MARKERS = [
    "too many requests", "rate limit", "try again later",
    "temporarily unavailable", "http error 429", "unusual traffic",
    "access denied", "reference #",
]

# ---------------------------------------------------------------------------
# Fallback selectors (repair after diagnose)
# ---------------------------------------------------------------------------
FALLBACK = {
    "doc_row": ("table tbody tr, [role='row'], [class*='statement-row'], "
                "[class*='StatementRow'], [class*='document'], "
                "[data-testid*='statement'], [data-testid*='document'], "
                "[data-test-id*='statement'], [data-test-id*='document'], "
                "li[class*='statement'], li[class*='document']"),
    "doc_link": ("a[href*='.pdf'], a[href*='statement'], a[href*='document'], "
                 "a[download], button[class*='download'], "
                 "button[aria-label*='download' i]"),
    "download_control": ("a[download], a[href$='.pdf'], "
                         "button:has-text('Download'), "
                         "[aria-label*='Download' i]"),
    "page_ready": ("table, [role='row'], [class*='statement'], "
                   "[class*='document'], main, [role='main']"),
    "next_page": ("a[aria-label*='Next' i], button[aria-label*='Next' i], "
                  "[class*='next']"),
    "period_select": ("select[name*='statement' i], select[name*='period' i], "
                      "select[aria-label*='statement' i], "
                      "[role='combobox'][aria-label*='statement' i]"),
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
            return f"Possible rate limiting / bot block detected: '{m}'"
    return None


def _forbidden(name: str) -> bool:
    """Whether a control's words say it does what this app never does."""
    if FORBIDDEN_CONTROL_RE.search(name):
        return True
    # The shared core guard is consulted as well as this app's own blocklist.
    # A repo-wide review found each app had drifted its own way and every one
    # of them let settings controls through ("Save Changes", "Document
    # Removal", "Turn off"). Centralizing it means the next gap is fixed once
    # rather than nineteen times.
    try:
        from paperpull_core.controls import SETTINGS_CONTROL_RE, AUTH_CONTROL_RE
        if SETTINGS_CONTROL_RE.search(name) or AUTH_CONTROL_RE.search(name):
            return True
    except Exception:
        pass
    return False


def is_safe_control(name: str) -> bool:
    name = (name or "").strip()
    if not name:
        return False
    if _forbidden(name):
        return False
    return bool(SAFE_DOC_CONTROL_RE.search(name))


# ---------------------------------------------------------------------------
# Documents page navigation
# ---------------------------------------------------------------------------

# Amex writes a control's test id as data-testid on some pages and as
# data-test-id on others, the PDF statements page of a German account among
# them (#107), so every test id is looked for under both names.
TEST_ID_ATTRS = ("data-testid", "data-test-id")


def _by_test_id(op: str, value: str) -> str:
    """A selector for a test id under either of its names, `op` one of
    =, *=, $= or ^=."""
    return ", ".join("[%s%s'%s']" % (attr, op, value) for attr in TEST_ID_ATTRS)


def _test_ids_of(el) -> List[str]:
    """Every test id an element carries, under either name. An element can
    carry both, and only one of them need be the one looked for."""
    return [tid for tid in (el.get_attribute(attr) for attr in TEST_ID_ATTRS) if tid]


_PDF_LINK_SEL = ", ".join(_by_test_id("=", name) for name in ("goToPdfLinkLg", "goToPdfLinkSm"))
_ACTIVITY_WORDS = re.compile(r"statements?\s*&\s*activity", re.I)
_PDF_LINK_WORDS = re.compile(r"go to pdf statements", re.I)
# A page in another language names its links in its own words, "Kontobewegungen
# & Abrechnungen" and "PDF-Abrechnungen" on a German account, and their
# addresses are the same in every language, each with a query of its own
# (#107). They are looked for by address only where the English Statements &
# Activity link does not show, so an English page is reached as it always was,
# and a tile of the page before, still drawn while the next one loads, is not
# taken for the next page's own link.
_ACTIVITY_HREF = "a[href='/activity'], a[href^='/activity?']"
_STATEMENTS_HREF = "a[href^='/activity/statements']"
_DOWNLOAD_BUTTONS = _by_test_id("*=", "download-button")

_SWITCHER_COMBOBOX_SEL = _by_test_id("=", "simple_switcher_combobox")
_SWITCHER_OPTION_SEL = _by_test_id("^=", "simple_switcher_product_option_")
_SWITCHER_NAME_SEL = _by_test_id("=", "simple_switcher_display_name")
_SWITCHER_NUM_SEL = _by_test_id("=", "simple_switcher_display_number")
_SWITCHER_SELECTED_DISPLAY_SEL = _by_test_id("=", "simple_switcher_selected_option_display")

NO_STATEMENTS_RE = re.compile(
    r"(no\s+statements?\s+(available|found|to\s+display)|"
    r"there\s+are\s+no\s+statements?|"
    r"you\s+have\s+no\s+statements?|"
    r"no\s+documents?\s+available|"
    r"no\s+billing\s+statements?|"
    r"keine\s+(abrechnungen|dokumente|kontoausz[üu]ge)|"
    r"es\s+liegen\s+keine\s+(abrechnungen|dokumente|kontoausz[üu]ge)\s+vor)", re.I)


def has_no_statements(page) -> bool:
    """Whether the page explicitly states there are no statements."""
    try:
        # Check statement/content containers first, never the whole body/header/footer
        for sel in ("#statements-list", "[data-testid*='statement']", "section", "main", "[role='main']", "#main-content"):
            loc = page.locator(sel)
            for i in range(min(loc.count(), 5)):
                el = loc.nth(i)
                if el.is_visible() and NO_STATEMENTS_RE.search(el.inner_text() or ""):
                    return True
        # Fallback for bare test pages without section/main: check visible text in non-footer/header elements
        loc = page.locator("p, div[role='alert'], [class*='empty'], [class*='no-statement']")
        for i in range(min(loc.count(), 10)):
            el = loc.nth(i)
            if not el.is_visible():
                continue
            if el.locator("xpath=ancestor::footer | ancestor::header | ancestor::*[@role='contentinfo']").count() > 0:
                continue
            if NO_STATEMENTS_RE.search(el.inner_text() or ""):
                return True
        return False
    except Exception:
        return False

# How long the tab is given to show a press's page after the wait it was
# always given, LINK_WAIT_MS after the first link and PDF_LINK_WAIT_MS after
# Go to PDF Statements. A single page app can take its time, and a press it
# has not answered by then is not pressed again, nor anything after it.
LINK_WAIT_MS = 5000
PDF_LINK_WAIT_MS = 6000
ROUTE_MS = 20000
# How long the statements page is given to show its first Download.
LIST_WAIT_MS = 12000


def _english_link(page):
    """The English Statements & Activity link when it shows, or None."""
    link = page.get_by_role("link", name=_ACTIVITY_WORDS)
    return link.first if link.count() and link.first.is_visible() else None


def _card_of(href: str) -> str:
    """The card a link's address names, its account_key, or ""."""
    from urllib.parse import parse_qs, urlsplit
    return ",".join(sorted(parse_qs(urlsplit(href).query).get("account_key", [])))


def _link_words(el) -> str:
    """What a link says, its text and its label, or "" when it cannot be read."""
    try:
        return " ".join([el.inner_text(timeout=2000) or "",
                         el.get_attribute("aria-label", timeout=2000) or "",
                         el.get_attribute("title", timeout=2000) or ""]).strip()
    except Exception:
        return ""


def _link_by_href(page, css: str):
    """The link of `css` a page in another language is reached by, or None.

    A link found by where it points has no English words to go by, so every
    link of `css` that shows is read. When they name more than one card by
    its account_key, which one this run is for cannot be told, and the run
    stops with nothing pressed. A link that names no card names no other
    one. A hidden copy is never taken, nor a link whose words say it does
    what this app never does, nor one that says nothing. A link that could
    not be read could be another card's, so the run stops then too, with
    nothing pressed."""
    loc = page.locator(css)
    shown = []
    for i in range(min(_safe_count(loc), 12)):
        el = loc.nth(i)
        try:
            if el.is_visible():
                shown.append((el, el.get_attribute("href", timeout=2000) or ""))
        except Exception:
            log.info("a link to the statements could not be read, so none is pressed")
            raise pressing.Stop("open the statements page",
                                "a link to the statements could not be read", [
                "A link to the statements could not be read, and it could be another "
                "card's, so none of them was pressed.",
                "Open the PDF statements of the card you want in the browser window, then "
                "press Resume here, or run this again."])
    cards = {_card_of(href) for _, href in shown} - {""}
    if len(cards) > 1:
        log.info("the page links to the statements of %d cards, so none is pressed", len(cards))
        raise pressing.Stop("open the statements page", "the page links to more than one card", [
            "The page links to the statements of more than one card, and which one this "
            "run is for could not be told, so none of them was pressed.",
            "Open the PDF statements of the card you want in the browser window, then "
            "press Resume here, or run this again."])
    for el, href in shown:
        words = _link_words(el)
        if href and words and not _forbidden(words):
            return el
    return None


def _href_of(el) -> str:
    try:
        return el.get_attribute("href", timeout=2000) or ""
    except Exception:
        return ""


def _arrived(page, part: str, waited_ms: int, shown: str = "") -> bool:
    """Whether the tab's address holds `part`, or an element of `shown` is on
    the page, after `waited_ms` and then for up to ROUTE_MS more. A single
    page app moves the tab without loading a page, so the address is read
    every half second rather than waited on as a load."""
    page.wait_for_timeout(waited_ms)
    for i in range(ROUTE_MS // 500 + 1):
        if part in (page.url or "") or (shown and _safe_count(page.locator(shown))):
            return True
        if i < ROUTE_MS // 500:
            page.wait_for_timeout(500)
    return False


def goto_documents(page) -> bool:
    """Reach the PDF Statements page ('Statements and Year End Summaries') by
    CLICKING within the SPA. Amex holds the session in an in-memory token, so a
    hard page.goto drops the session and bounces to login - we never use it for
    authenticated pages. Ready when statement download-buttons are present.

    Each link on the way is pressed once. A press whose page does not come
    stops the run with nothing more pressed (pressing.no_answer), since every
    caller would otherwise come back here and press it again."""
    if looks_signed_out(page):
        return False
    try:
        url = page.url or ""
        if "/activity/statements" not in url:
            # Multi-card sign-ins frequently land on /overview rather than /dashboard.
            # /overview does not draw the 'Statements & Activity' top-nav link until
            # a specific card product is selected from the switcher.
            if "/overview" in (page.url or ""):
                cb = page.locator(_SWITCHER_COMBOBOX_SEL)
                if cb.count() and cb.first.is_visible():
                    pressing.click(page, cb.first, css=_SWITCHER_COMBOBOX_SEL,
                                   what="the card switcher",
                                   words=_words(), step="open the card switcher")
                    try:
                        page.wait_for_selector(_SWITCHER_OPTION_SEL, timeout=LINK_WAIT_MS)
                    except Exception:
                        pass
                    opts = page.locator(_SWITCHER_OPTION_SEL)
                    if opts.count() and opts.first.is_visible():
                        opt = opts.first
                        tid = opt.get_attribute("data-testid") or opt.get_attribute("data-test-id") or ""
                        opt_css = _by_test_id("=", tid) if tid else _SWITCHER_OPTION_SEL
                        pressing.click(page, opt, css=opt_css,
                                       what="the card option",
                                       words=_words(), step="select card on overview")
                        if not _arrived(page, "/dashboard", LINK_WAIT_MS):
                            log.info("selected card on overview and dashboard did not come")
                            raise pressing.no_answer(
                                "open the dashboard", "the dashboard did not open",
                                "The card was selected on the overview page and the dashboard did not open.")
                    else:
                        raise pressing.no_answer(
                            "open the card switcher", "the card options did not show",
                            "The card switcher on the overview page was opened and its options did not show.")
            pressed = ""
            if "/activity" not in (page.url or ""):
                link, want = _english_link(page), "/activity"
                if link is None:
                    # The PDF statements themselves, which a dashboard in
                    # another language links to, or else the activity page.
                    link, want = _link_by_href(page, _STATEMENTS_HREF), "/activity/statements"
                    if link is None:
                        link, want = _link_by_href(page, _ACTIVITY_HREF), "/activity"
                if link is not None:
                    pressed = _href_of(link)
                    pressing.click(page, link, css=pressing.LINKS,
                                   what="the Statements and Activity link",
                                   words=_words(), step="open the statements page")
                    if not _arrived(page, want, LINK_WAIT_MS):
                        log.info("the first link on the way to the statements was pressed "
                                 "and its page did not come")
                        raise pressing.no_answer(
                            "open the statements page", "the page did not open",
                            "The link on the way to the statements was pressed once and "
                            "the page it leads to did not open.")
            if "/activity/statements" not in (page.url or ""):
                pdf = page.locator(_PDF_LINK_SEL)
                if pdf.count() == 0:
                    pdf = page.get_by_role("link", name=_PDF_LINK_WORDS)
                pdf = pdf.first if pdf.count() and pdf.first.is_visible() else None
                if pdf is None and "/activity" in (page.url or "") and _english_link(page) is None:
                    pdf = _link_by_href(page, _STATEMENTS_HREF)
                if pdf is not None and pressed and _href_of(pdf) == pressed:
                    raise pressing.Stop("open the statements page", "the link was pressed already", [
                        "The link to the PDF statements is the one pressed on the way "
                        "there, which did not lead to them, so it was not pressed again.",
                        pressing.AGAIN])
                if pdf is not None:
                    pressing.click(page, pdf, css="%s, %s" % (_PDF_LINK_SEL, pressing.LINKS),
                                   what="the Go to PDF Statements link",
                                   words=_words(), step="open the statements page")
                    if not _arrived(page, "/activity/statements", PDF_LINK_WAIT_MS,
                                    _DOWNLOAD_BUTTONS):
                        log.info("the link to the PDF statements was pressed and they "
                                 "did not come")
                        raise pressing.no_answer(
                            "open the statements page", "the statements did not open",
                            "The Go to PDF Statements link was pressed once and the "
                            "statements did not open.")
        try:
            page.wait_for_selector(_DOWNLOAD_BUTTONS, timeout=LIST_WAIT_MS)
        except Exception:
            pass
        expand_sections(page)
        return "/activity/statements" in (page.url or "") or page.locator(_DOWNLOAD_BUTTONS).count() > 0
    except Exception as e:
        log.info("goto_documents (click-nav) failed: %s", e)
        return "/activity/statements" in (page.url or "") or page.locator(_DOWNLOAD_BUTTONS).count() > 0


# The collapsible sections, each by its English words and then by the part
# it opens, which is the same in every language ("Vergangene Abrechnungen"
# heads the older statements on a German account, #107). Only the older
# statements' part has been seen by its name.
_SECTIONS = (
    ("Older Statements", r"older\s+statements", "[aria-controls='content-older-statements']"),
    ("Year End Summary", r"year.?end\s+summary", None),
)


def expand_sections(page) -> None:
    """Open the collapsible 'Older Statements' and 'Year End Summary' sections
    so their download buttons become clickable. 'Older Statements' is expanded
    by default; 'Year End Summary' is collapsed - only click a header whose
    aria-expanded is 'false' (clicking an open one would collapse it). A
    section's heading is found by its English words first, as it always was,
    then by the part it opens, whatever kind of element carries that, and
    only the first that shows is pressed or left as it is."""
    for name, label, css in _SECTIONS:
        try:
            found = [(page.get_by_role("button", name=re.compile(label, re.I)), pressing.BUTTONS)]
            if css:
                found.append((page.locator(css), css))
            el = kind = None
            for hdr, sel in found:
                for i in range(min(hdr.count(), 3)):
                    if hdr.nth(i).is_visible():
                        el, kind = hdr.nth(i), sel
                        break
                if el is not None:
                    break
            if el is None:
                continue
            if (el.get_attribute("aria-expanded") or "").lower() == "false":
                pressing.click(page, el, css=kind,
                               what="the heading of the %s section" % name,
                               words=_words(), step="open a section")
                page.wait_for_timeout(1500)
        except Exception:
            continue


def scroll_full_page(page, rounds: int = 8, delay_ms: int = 700) -> None:
    try:
        for _ in range(rounds):
            page.mouse.wheel(0, 3000)
            page.wait_for_timeout(delay_ms)
        page.keyboard.press("End")
        page.wait_for_timeout(delay_ms)
    except Exception:
        pass


def expand_all(page) -> None:
    """Click 'View More' / 'Show more' / 'Load more' repeatedly until the full
    list loads. Amex uses both <button> and <a>, so both roles are tried."""
    pat = re.compile(
        r"^\s*(show|load|view|see)\s+more\s*$|^\s*view\s+all\s*$|"
        r"^\s*(show|see)\s+(all|older)\s*$|^\s*older\s*$", re.I)
    for _ in range(60):
        clicked = False
        for role in ("button", "link"):
            try:
                loc = page.get_by_role(role, name=pat)
                if loc.count() > 0 and loc.first.is_visible():
                    label = loc.first.inner_text(timeout=1000) or ""
                    if not FORBIDDEN_CONTROL_RE.search(label):
                        pressing.click(page, loc.first,
                                       css="%s, %s" % (pressing.BUTTONS, pressing.LINKS),
                                       what="a control that shows more of the list",
                                       words=_words(), step="show more of the list")
                        page.wait_for_timeout(1600)
                        clicked = True
                        break
            except Exception:
                continue
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
    account: str = ""
    date_text: str = ""
    href: str = ""
    text: str = ""
    row_index: int = -1
    kind: str = "doc"


_ROW_JS = r"""() => {
  const out = [];
  for (const tr of document.querySelectorAll('table tr, [role=row]')) {
    const tds = [...tr.querySelectorAll('td, [role=cell]')].map(c => (c.innerText || '').trim());
    if (tds.length < 2) continue;
    const link = tr.querySelector("a[href]");
    out.push({cells: tds.slice(0, 6),
              href: link ? link.getAttribute('href') : ''});
  }
  return out;
}"""


def collect_documents(page) -> List[RawDoc]:
    """Scrape document rows from the visible table/list (diagnose + fallback)."""
    docs: List[RawDoc] = []
    seen = set()
    try:
        rows = page.evaluate(_ROW_JS)
    except Exception:
        rows = []
    for i, r in enumerate(rows):
        cells = [c for c in (r.get("cells") or []) if c]
        if not cells:
            continue
        text = " | ".join(cells)
        has_date = parse_date(text) or MONTH_YEAR_RE.search(text) or YEAR_RE.search(text)
        href = r.get("href", "")
        if not (has_date or href or "download" in text.lower()):
            continue
        title = _html.unescape(cells[0])
        date_text = next((c for c in cells if parse_date(c) or MONTH_YEAR_RE.search(c)), "")
        key = (title, date_text, href, text[:60])
        if key in seen:
            continue
        seen.add(key)
        docs.append(RawDoc(title=re.sub(r"\s+", " ", title)[:200], date_text=date_text,
                           href=href, text=text[:400], row_index=i))
    return docs


# ---------------------------------------------------------------------------
# Downloadable-document collection (verified 2026-07 against the live site).
#
# On the "Statements and Year End Summaries" page every document is a
# <button> whose test id, data-testid or on some pages data-test-id (#107),
# encodes its category AND date, e.g.
#   myca-activity-statements/common/Table/recent-statements/2020-01-15/download-button
#   myca-activity-statements/common/Table/older-statements/2019-01-15/download-button
#   myca-activity-statements/common/Table/year-end-summary/2019/download-button
# (dates above are invented. A real testid carries a real closing date,
#  which would publish the account's billing-cycle day.)
# Each date appears twice (a desktop + a hidden mobile copy of the same
# testid), so results are de-duped by (category, date). page.evaluate is
# blocked by Amex (eval lockdown), so this uses locators only.
# ---------------------------------------------------------------------------
_STMT_TESTID_RE = re.compile(r"/(recent|older)-statements/(\d{4}-\d{2}-\d{2})/download-button")
_YE_TESTID_RE = re.compile(r"/year-end-summary/(\d{4})/download-button")


def clean_account_name(raw: str) -> str:
    """Strip trademark symbols and extra whitespace from account name."""
    s = re.sub(r"[®™]", "", raw or "")
    return re.sub(r"\s+", " ", s).strip()


def list_cards(page) -> List[dict]:
    """List every card/account available in the switcher.

    Amex disables eval on its pages, so locators and attributes are used
    directly instead of page.evaluate(). Each card option in the switcher
    combobox provides a display name and the masked card number (e.g. ••••12345).
    The card label is formatted as '<name> (<last_digits>)' so cards of the
    same product type do not collide.

    Returns list of dicts: [{'index': int, 'tid': str, 'label': str, 'digits': str, 'name': str}]
    """
    try:
        page.wait_for_selector(_SWITCHER_COMBOBOX_SEL, timeout=LINK_WAIT_MS)
    except Exception:
        pass
    cb = page.locator(_SWITCHER_COMBOBOX_SEL)
    if not (cb.count() and cb.first.is_visible()):
        return []
    pressing.click(page, cb.first, css=_SWITCHER_COMBOBOX_SEL,
                   what="the card switcher",
                   words=_words(), step="open the card switcher")
    try:
        page.wait_for_selector(_SWITCHER_OPTION_SEL, timeout=LINK_WAIT_MS)
    except Exception:
        raise pressing.no_answer(
            "open the card switcher", "the card options did not show",
            "The card switcher was opened and its options did not show.")
    opts = page.locator(_SWITCHER_OPTION_SEL)
    if not (opts.count() and opts.first.is_visible()):
        raise pressing.no_answer(
            "open the card switcher", "the card options did not show",
            "The card switcher was opened and its options did not show.")
    cards = []
    for i in range(opts.count()):
        opt = opts.nth(i)
        tid = opt.get_attribute("data-testid") or opt.get_attribute("data-test-id") or ""
        name_el = opt.locator(_SWITCHER_NAME_SEL)
        num_el = opt.locator(_SWITCHER_NUM_SEL)
        name = clean_account_name(name_el.inner_text()) if name_el.count() else ""
        num = (num_el.inner_text() if num_el.count() else "").strip()
        digits = re.sub(r"\D", "", num)
        label = f"{name} ({digits})" if digits else name
        cards.append({"index": i, "tid": tid, "label": label, "digits": digits, "name": name})
    if (cb.first.get_attribute("aria-expanded") or "").lower() == "true":
        pressing.click(page, cb.first, css=_SWITCHER_COMBOBOX_SEL,
                       what="the card switcher",
                       words=_words(), step="close the card switcher")
    if len(cards) > 1 and any(not c["digits"] for c in cards):
        raise pressing.Stop(
            "read the card switcher", "a card has no account number",
            ["More than one card was found in the switcher, but at least one card has no account number to identify it.",
             pressing.AGAIN])
    if len(set(c["label"] for c in cards)) < len(cards):
        raise pressing.Stop(
            "read the card switcher", "two cards share a label",
            ["Two cards in the switcher share the same label, so their statements cannot be told apart.",
             pressing.AGAIN])
    return cards


def _switcher_selected_container(page):
    disp = page.locator(_SWITCHER_SELECTED_DISPLAY_SEL)
    if disp.count() and disp.first.is_visible():
        return disp.first
    cb = page.locator(_SWITCHER_COMBOBOX_SEL)
    if cb.count() and cb.first.is_visible():
        return cb.first
    return None


def _current_card_digits(page) -> str:
    container = _switcher_selected_container(page)
    if not container:
        return ""
    num_el = container.locator(_SWITCHER_NUM_SEL)
    if num_el.count() and num_el.first.is_visible():
        return re.sub(r"\D", "", num_el.first.inner_text())
    txt = container.inner_text()
    m = re.findall(r"\b\d{4,5}\b", txt)
    if m:
        return m[-1]
    digits = re.sub(r"\D", "", txt)
    return digits[-5:] if len(digits) >= 5 else digits


def current_card_label(page) -> str:
    """The label of the currently selected card in the switcher, or ''."""
    container = _switcher_selected_container(page)
    if not container:
        return ""
    try:
        name_el = container.locator(_SWITCHER_NAME_SEL)
        num_el = container.locator(_SWITCHER_NUM_SEL)
        name = clean_account_name(name_el.first.inner_text()) if name_el.count() and name_el.first.is_visible() else ""
        num = num_el.first.inner_text() if num_el.count() and num_el.first.is_visible() else ""
        digits = re.sub(r"\D", "", num)
        if not name:
            txt = container.inner_text().strip()
            lines = [l.strip() for l in txt.splitlines() if l.strip()]
            if lines:
                name = clean_account_name(lines[0])
                num = lines[1] if len(lines) > 1 else ""
                digits = re.sub(r"\D", "", num)
        return f"{name} ({digits})" if digits else name
    except Exception:
        return ""


def select_card(page, card: dict) -> bool:
    """Switch to the card specified by dict.
    Returns True if successfully switched or already on that card."""
    cb = page.locator(_SWITCHER_COMBOBOX_SEL)
    if not (cb.count() and cb.first.is_visible()):
        return False
    digits = card.get("digits", "")
    current_digits = _current_card_digits(page)
    if digits and current_digits == digits:
        return True

    pressing.click(page, cb.first, css=_SWITCHER_COMBOBOX_SEL,
                   what="the card switcher",
                   words=_words(), step="open the card switcher")
    try:
        page.wait_for_selector(_SWITCHER_OPTION_SEL, timeout=LINK_WAIT_MS)
    except Exception:
        raise pressing.no_answer(
            "open the card switcher", "the card options did not show",
            "The card switcher was opened and its options did not show.")

    tid = card.get("tid", "")
    opt = None
    opt_css = _SWITCHER_OPTION_SEL
    if tid:
        opt_loc = page.locator(_by_test_id("=", tid))
        if opt_loc.count() and opt_loc.first.is_visible():
            opt = opt_loc.first
            opt_css = _by_test_id("=", tid)
    if not opt:
        opts = page.locator(_SWITCHER_OPTION_SEL)
        for i in range(opts.count()):
            candidate = opts.nth(i)
            num_el = candidate.locator(_SWITCHER_NUM_SEL)
            opt_digits = re.sub(r"\D", "", num_el.inner_text() if num_el.count() else "")
            if digits and opt_digits == digits:
                opt = candidate
                cand_tid = candidate.get_attribute("data-testid") or candidate.get_attribute("data-test-id") or ""
                opt_css = _by_test_id("=", cand_tid) if cand_tid else _SWITCHER_OPTION_SEL
                break
    if not opt:
        if (cb.first.get_attribute("aria-expanded") or "").lower() == "true":
            pressing.click(page, cb.first, css=_SWITCHER_COMBOBOX_SEL,
                           what="the card switcher",
                           words=_words(), step="close the card switcher")
        return False

    old_buttons = page.locator(_DOWNLOAD_BUTTONS)
    has_old = old_buttons.count() > 0 and old_buttons.first.is_visible()
    old_handle = old_buttons.first.element_handle() if has_old else None
    old_url = page.url or ""

    pressing.click(page, opt, css=opt_css,
                   what="the card option",
                   words=_words(), step="switch card")

    # Wait until the selected card display shows exactly that card's digits
    switched = False
    for _ in range(int(LINK_WAIT_MS / 250)):
        page.wait_for_timeout(250)
        if _current_card_digits(page) == digits:
            switched = True
            break

    if not switched:
        log.info("switched card option but selected card display did not update to digits %s", digits)
        raise pressing.no_answer(
            "switch card", "the card did not switch",
            f"The switcher was set to {card.get('label', 'card')} and the card's statements did not open.")

    # Wait until the previous card's statement buttons are gone / detached
    if old_handle is not None:
        detached = False
        for _ in range(int(LINK_WAIT_MS / 250)):
            page.wait_for_timeout(250)
            try:
                connected = old_handle.evaluate("el => el.isConnected")
                if not connected:
                    detached = True
                    break
            except Exception:
                detached = True
                break
            if page.locator(_DOWNLOAD_BUTTONS).count() == 0 or (_card_of(page.url) and _card_of(page.url) != _card_of(old_url)):
                detached = True
                break
        if not detached:
            log.info("switched card option but old statements list never cleared")
            raise pressing.no_answer(
                "switch card", "the statements did not switch",
                f"The switcher was set to {card.get('label', 'card')} and the card's statements did not open.")

    try:
        page.wait_for_selector(f"{_DOWNLOAD_BUTTONS}, main, [role='main']", timeout=LIST_WAIT_MS)
    except Exception:
        pass
    expand_sections(page)
    return True


def ensure_card(page, account: str) -> bool:
    """Ensure that the page is on the card matching `account`."""
    if not account:
        return True
    m = re.search(r"\((\d+)\)", account)
    digits = m.group(1) if m else re.sub(r"\D", "", account)
    if not digits:
        return False
    current_digits = _current_card_digits(page)
    if current_digits and current_digits == digits:
        return True
    cards = list_cards(page)
    for c in cards:
        if c.get("digits") == digits:
            return select_card(page, c)
    log.info("card %s was not found in the switcher; nothing was pressed", account)
    print(f"Card {account} was not found in the switcher; nothing was pressed.")
    return False


def collect_download_docs(page, account: str = "") -> List[RawDoc]:
    """Every downloadable statement + year-end summary on the statements page,
    read from the download-button testids (deduped by category+date)."""
    docs: List[RawDoc] = []
    seen = set()
    loc = page.locator(_DOWNLOAD_BUTTONS)
    try:
        n = loc.count()
    except Exception:
        n = 0
    for i in range(n):
        try:
            tids = _test_ids_of(loc.nth(i))
        except Exception:
            continue
        # An element may carry both names, and either may be the document's
        # own (#107), so each is read. Two that name different documents
        # leave which one the button downloads untold.
        named = {}
        for tid in tids:
            m = _STMT_TESTID_RE.search(tid)
            if m:
                named.setdefault(("stmt", m.group(2)), tid)
                continue
            m = _YE_TESTID_RE.search(tid)
            if m:
                named.setdefault(("ye", m.group(1)), tid)
        if len(named) > 1:
            log.info("a Download button's two test ids name two documents")
            raise pressing.Stop("read the statements", "a download names two documents", [
                "A Download button on the statements page names two different documents, "
                "so which one it brings could not be told and the list was not read.",
                "Nothing was pressed.", pressing.AGAIN])
        for (kind, when), tid in named.items():
            if (kind, when) in seen:
                continue
            seen.add((kind, when))
            if kind == "stmt":
                human = _human_date(when)
                docs.append(RawDoc(title=f"Monthly Statement - {human}", date_text=when,
                                   href=tid, text=f"Monthly Statement {human}",
                                   kind="statement", account=account))
            else:
                docs.append(RawDoc(title=f"{when} Year-End Summary", date_text=f"{when}-12-31",
                                   href=tid, text=f"{when} Year-End Summary",
                                   kind="year-end", account=account))
    return docs


def _first_visible(loc):
    try:
        n = loc.count()
    except Exception:
        return None
    for i in range(n):
        el = loc.nth(i)
        try:
            if el.is_visible():
                return el
        except Exception:
            continue
    return loc.first if (n and loc.count()) else None


def _shows(el) -> bool:
    try:
        return bool(el.is_visible())
    except Exception:
        return False


def _last_visible(loc):
    """The last element of `loc` that shows, which for dialogs held one
    inside the other is the innermost, or None."""
    n = _safe_count(loc)
    for i in range(min(n, 12) - 1, -1, -1):
        if _shows(loc.nth(i)):
            return loc.nth(i)
    return None


def _pdf_radio(page):
    """The file-type dialog's plain PDF choice, never the one for a screen
    reader, statement_pdf before any other PDF and one that shows before one
    that does not. A radio button that does not show is drawn by its label
    alone, the way a styled one can be, and pressing.check checks it
    through that label. A dialog can draw its choices a moment after its
    Download, so they are looked for again for a few seconds. Only inside the
    file-type dialog's own element, so a PDF choice elsewhere on the page is
    never taken for its own, and with no such element there is none."""
    for _ in range(10):
        dialog = _file_type_dialog(page)
        if dialog is None:
            page.wait_for_timeout(500)
            continue
        for sel in ("input[type='radio'][value='statement_pdf']",
                    "input[type='radio'][value*='pdf' i]"):
            loc = dialog.locator(sel)
            found = []
            for i in range(min(_safe_count(loc), 12)):
                el = loc.nth(i)
                try:
                    v = (el.get_attribute("value", timeout=2000) or "").lower()
                except Exception:
                    continue
                if "accessible" in v or "screen" in v:
                    continue
                found.append(el)
            shown = [el for el in found if _shows(el)]
            if shown or found:
                return (shown or found)[0]
        page.wait_for_timeout(500)
    return None


def _choose_pdf(page, thing: str, words) -> None:
    """Choose the plain PDF in the open file-type dialog, or stop the run.
    The dialog's Download is never pressed with the PDF not chosen, since
    it would bring whichever kind of file was chosen before."""
    radio = _pdf_radio(page)
    if radio is None and _file_type_dialog(page) is None:
        raise pressing.Stop("choose the pdf", "the dialog was not found", [
            "The file type dialog for %s could not be told from the rest of the page, "
            "so nothing in it was pressed." % thing,
            "Nothing more was pressed.", pressing.AGAIN])
    if radio is None:
        raise pressing.Stop("choose the pdf", "the dialog offered no pdf", [
            "The file type dialog for %s opened without its plain PDF choice, "
            "so its Download was not pressed." % thing,
            "Nothing more was pressed.", pressing.AGAIN])
    pressing.check(page, radio, css="input[type='radio']",
                   what="the plain PDF choice in the file type dialog for %s" % thing,
                   words=words, step="choose the pdf")


# The "Select File Type" dialog's confirm button renders its label as an icon
# glyph (its accessible name is unreliable), but it carries a stable test id,
# matched by its own last words under either name (#107).
_DIALOG_CONFIRM_SEL = (
    "[data-test-id$='download-footer-download-confirm-anchor'], "
    "[data-testid$='download-footer-download-confirm-anchor'], "
    "[id*='download-confirm'][id$='-anchor']")
# The dialog's own controls, its PDF radio and its confirm button, looked for
# inside the dialog whenever it is found (_dialog_open).
_DIALOG_OPEN_SEL = "input[type='radio'][value*='pdf' i], " + _DIALOG_CONFIRM_SEL
# The file-type dialog itself, the dialog that holds its confirm button. Only
# its own Cancel or Close is ever pressed to close a dialog. A dialog, frame
# or widget of anything else on the page, a chat window among them, is left
# as it is.
_DIALOGS = "[role='dialog'], [role='alertdialog'], dialog, [aria-modal='true']"
_CLOSE_NAME = re.compile(r"^\s*(cancel|close)\s*$", re.I)


def _file_type_dialog(page):
    """The file-type dialog's own element, known by its own Download, whose
    test id nothing else on the page has, or None. A PDF choice alone does
    not make a dialog this one, since a setting elsewhere can offer a PDF."""
    return _last_visible(page.locator(_DIALOGS).filter(has=page.locator(_DIALOG_CONFIRM_SEL)))


def _dialog_scope(page):
    """Where the file-type dialog's own controls are looked for, inside the
    dialog whenever it is found, and on the page only when it is not."""
    dialog = _file_type_dialog(page)
    return dialog if dialog is not None else page


def _dialog_download_button(page, timeout: int = 8000):
    """The confirm 'Download' button INSIDE the file-type dialog, matched by its
    stable test id (not by accessible name, which is just an icon glyph)."""
    loc = _dialog_scope(page).locator(_DIALOG_CONFIRM_SEL)
    try:
        loc.first.wait_for(state="visible", timeout=timeout)
    except Exception:
        pass
    vb = _first_visible(loc)
    if vb is not None and _shows(vb):
        return vb
    # Last resort, a button named Download inside the file-type dialog itself
    # that is not a row's button. One anywhere else on the page belongs to
    # something else.
    dialog = _file_type_dialog(page)
    if dialog is None:
        return None
    cands = dialog.get_by_role("button", name=re.compile(r"^\s*download\s*$", re.I))
    for i in range(min(_safe_count(cands), 12)):
        el = cands.nth(i)
        try:
            tids = _test_ids_of(el)
            if el.is_visible() and not any(t.endswith("download-button") for t in tids):
                return el
        except Exception:
            continue
    return None


def _safe_count(loc) -> int:
    try:
        return loc.count()
    except Exception:
        return 0


def _dialog_open(page) -> bool:
    """Whether the file-type dialog shows, by its PDF choice or its
    Download inside the dialog whenever it is found, and by its Download
    alone when it is not, so a PDF choice elsewhere on the page never counts.
    A copy left hidden in the page does not count either."""
    dialog = _file_type_dialog(page)
    if dialog is not None:
        loc = dialog.locator(_DIALOG_OPEN_SEL)
    else:
        loc = page.locator(_DIALOG_CONFIRM_SEL)
    return any(_shows(loc.nth(i)) for i in range(min(_safe_count(loc), 12)))


def _wait_for_dialog(page, ms: int) -> bool:
    """Whether the file-type dialog shows within `ms`. Any of its controls
    that shows counts, where page.wait_for_selector looks at the first one
    in the page alone, a radio button that may be drawn by its label."""
    import time
    deadline = time.monotonic() + ms / 1000.0
    while True:
        if _dialog_open(page):
            return True
        if time.monotonic() >= deadline:
            return False
        page.wait_for_timeout(250)


def close_file_type_dialog(page, quiet: bool = False) -> None:
    """Close the file-type dialog when it shows, once, through its own
    Cancel or Close, or with Escape sent to one of its own controls that
    shows when it has neither. Both are looked for only inside the dialog
    itself, so with no dialog element of its own to look in nothing is
    sent at all. Nothing outside that dialog is pressed, so a chat window or
    a dialog of anything else is left as it is.

    The Cancel or Close goes through pressing.click like every press. A
    dialog that is still there afterwards stops the run, since every press
    after it would land on the dialog. Right after a document is saved and
    recorded this is `quiet`. A refusal made before anything was pressed
    then leaves the dialog for the next document, whose own close is the
    first press of its Cancel. A stop that came once the press was tried,
    one that may have gone to something else, stops the run there all the
    same, quiet or not."""
    if not _dialog_open(page):
        return
    try:
        dialog = _file_type_dialog(page)
        closer = own = None
        if dialog is not None:
            closer = _first_visible(dialog.get_by_role("button", name=_CLOSE_NAME))
            if closer is not None and not _shows(closer):
                closer = None
            if closer is None:
                own = _first_visible(dialog.locator(_DIALOG_OPEN_SEL))
                if own is not None and not _shows(own):
                    own = None
        if closer is not None:
            pressing.click(page, closer, css=pressing.BUTTONS,
                           what="the Cancel of the file type dialog", words=_words(),
                           step="close the file type dialog")
        elif own is not None:
            # A key goes to the element that has the focus. It is sent only
            # once one of the dialog's own controls holds the focus, never
            # to whatever else on the page has it.
            own.focus(timeout=3000)
            if _safe_count(dialog.locator(":focus")) == 1:
                own.press("Escape", timeout=3000)
        page.wait_for_timeout(700)
    except pressing.Stop as stop:
        if not quiet or stop.after_a_press:
            raise
        log.info("the file type dialog was left open (%s)", stop.reason)
        return
    except Exception as e:
        log.info("the file type dialog could not be closed (%s)", _error_kind(e))
    if _dialog_open(page) and not quiet:
        raise pressing.Stop("close the file type dialog", "the dialog did not close", [
            "The file type dialog was open and would not close, so nothing was "
            "pressed for this document.",
            "Close it in the browser window, then press Resume here, or run this again."])


# How long the file-type dialog is given to open after its row's Download,
# and the dialog's Download is given to start its download.
DIALOG_WAIT_MS = 10000
DOWNLOAD_WAIT_MS = 45000


def download_document(page, category: str, date: str, out_path) -> bool:
    """Download one statement or year-end summary PDF. Its row's Download
    button is pressed once, the plain PDF is chosen in the Select File Type
    dialog, the dialog's own Download is pressed once, and the download
    event is saved.

    Every press goes through paperpull_core.pressing and none is forced, so
    a control with anything on top of it is never pressed and the run stops
    there. A press that does not bring what it should, the dialog after the
    row's button or a download after the dialog's, is not made again and
    the run stops (pressing.Stop). This used to try a second time and go on
    to the next document, so a press that had opened something else was
    followed by more presses, on whatever it had opened.

    False only when the row's button is not on the page or the page has it
    turned off, and then nothing was pressed for this document, or when the
    download came and could not be saved. A turned off button leaves its
    document for review and the next run, and the run goes on
    (pressing.TurnedOff). The dialog is left open once the statement is
    saved, for the app to close once it has recorded the statement as
    saved, so a stop at the close never loses a saved statement
    (close_file_type_dialog)."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    words = _words()
    if category == "Year-End Summary":
        sel = _by_test_id("$=", f"/year-end-summary/{date[:4]}/download-button")
        thing = "the %s year-end summary" % date[:4]
    else:
        sel = _by_test_id("$=", f"/{date}/download-button")
        thing = "the statement dated %s" % date
    button = "the Download button of %s" % thing

    close_file_type_dialog(page)   # one the document before left open
    expand_sections(page)          # Older Statements / Year End Summary open

    btn = _first_visible(page.locator(sel))
    if btn is None or not _shows(btn):
        log.info("row download button not found for %s %s (sel=%s)", category, date, sel)
        return False
    try:
        pressing.click(page, btn, css=sel, what=button, words=words,
                       step="press a download button")
    except pressing.TurnedOff:
        log.info("%s is turned off on the page, so nothing was pressed and it is left for "
                 "review", button)
        return False

    if not _wait_for_dialog(page, DIALOG_WAIT_MS):
        log.info("file-type dialog did not open for %s %s", category, date)
        raise pressing.no_answer("open the file type dialog", "the dialog did not open",
                                 "%s was pressed once and the file type dialog did not "
                                 "open." % ("T" + button[1:]))

    _choose_pdf(page, thing, words)
    confirm = _dialog_download_button(page)
    if confirm is None:
        raise pressing.Stop("find the dialog download", "the dialog has no download", [
            "The file type dialog for %s showed no Download of its own, so "
            "nothing in it was pressed." % thing,
            "Nothing more was pressed.", pressing.AGAIN])

    from paperpull_core.receipt_pdf import save_download
    try:
        # The press is given as long as the download, since Playwright's
        # wait on what a press starts runs on the press's own time.
        with page.expect_download(timeout=DOWNLOAD_WAIT_MS) as dl:
            pressing.click(page, confirm, css="%s, %s" % (_DIALOG_CONFIRM_SEL, pressing.BUTTONS),
                           what="the Download of the file type dialog for %s" % thing,
                           words=words, step="press the dialog download",
                           timeout=DOWNLOAD_WAIT_MS)
        download = dl.value
    except Exception as e:
        log.info("no download came for %s %s (%s)", category, date, _error_kind(e))
        raise pressing.no_answer("download from the dialog", "no download came",
                                 "The Download of the file type dialog for %s was pressed "
                                 "once and no download came." % thing)
    try:
        save_download(download, out_path)
    except Exception as e:
        log.info("the download for %s %s could not be saved (%s)", category, date,
                 _error_kind(e))
        return False
    return True


_BLOB_FETCH_JS = r"""async () => {
    const f = document.querySelector("iframe[src^='blob:'], embed[src^='blob:']");
    const src = f && f.src;
    if (!src) return null;
    const r = await fetch(src);
    const buf = await ppRead(r);
    let s = ''; for (let i = 0; i < buf.length; i++) s += String.fromCharCode(buf[i]);
    return btoa(s);
}"""


def download_by_url(page, url: str, out_path) -> bool:
    """Download a document PDF from a direct/API URL. Handles both a real file
    download and an inline blob-iframe render."""
    if not url:
        return False
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    full = url if url.startswith("http") else BASE + url
    # A stored record must not be able to steer this anywhere but the
    # provider's own site. Before this check the value went straight to
    # page.goto in the signed-in tab.
    if not is_safe_url(full):
        log.error("refusing a URL that is not on this provider's host")
        return False
    try:
        with page.expect_download(timeout=25000) as dl:
            try:
                page.goto(full)
            except Exception as e:
                if "download is starting" not in str(e).lower():
                    raise
        from paperpull_core.receipt_pdf import save_download
        save_download(dl.value, out_path)
        return True
    except Exception:
        pass
    try:
        page.wait_for_selector("iframe[src^='blob:'], embed[src^='blob:']", timeout=15000)
        page.wait_for_timeout(1200)
        b64 = intake.evaluate(page, _BLOB_FETCH_JS)
        if b64:
            data = intake.decode(b64)
            if b"%PDF-" in data[:1024]:
                out_path.write_bytes(data)
                return True
    except Exception as e:
        log.info("download_by_url blob fallback failed for %s: %s", url, e)
    return False


def download_named(page, title: str, out_path) -> bool:
    """Click the download control for the document whose title/date matches, and
    capture the resulting download event to out_path. Falls back to a direct PDF
    href if clicking does not fire a download event."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    needle = re.sub(r"\s+", " ", title).strip()
    date_hint, _ = parse_period_date(title)

    control = None
    href_hit = ""
    try:
        loc = page.locator("a[download], a[href*='.pdf'], a, button, [role='button']")
        for i in range(min(loc.count(), 500)):
            el = loc.nth(i)
            try:
                own = (el.inner_text(timeout=400) or "") + " " + \
                    (el.get_attribute("aria-label") or "")
            except Exception:
                continue
            href = el.get_attribute("href") or ""
            has_dl_attr = el.get_attribute("download") is not None
            is_pdf_href = bool(re.search(r"\.pdf(\?|$)", href, re.I))
            says_dl = bool(re.search(r"download|\bpdf\b|save\s+pdf|view\s+pdf", own, re.I))
            if not (has_dl_attr or is_pdf_href or says_dl):
                continue
            if re.search(r"\b(csv|excel|xlsx?|ofx|qfx|qbo)\b", own, re.I):
                continue
            if FORBIDDEN_CONTROL_RE.search(own) and not (has_dl_attr or is_pdf_href):
                continue
            hay = own
            if needle.lower()[:30] not in hay.lower():
                try:
                    hay = el.evaluate(
                        "el => { let n = el; for (let i=0;i<8 && n;i++){ n=n.parentElement;"
                        " if(n && (n.innerText||'').length>8) return n.innerText; } return ''; }")
                except Exception:
                    hay = ""
            hay_l = (hay or "").lower()
            matched = needle.lower()[:30] in hay_l
            if not matched and date_hint:
                dm = MONTH_YEAR_RE.search(needle)
                if dm and dm.group(0).lower() in hay_l:
                    matched = True
            if matched:
                control = el
                href_hit = href if (is_pdf_href or has_dl_attr) else ""
                break
    except Exception:
        pass

    if control is None:
        log.info("download control not found for %r", title)
        return False

    from paperpull_core.receipt_pdf import save_download
    try:
        with page.expect_download(timeout=45000) as dl:
            pressing.click(page, control, css="a, button, [role=button]",
                           what="the download control for this document",
                           words=_words(), step="press a download control")
        save_download(dl.value, out_path)
        return True
    except Exception as e:
        log.info("download click did not fire an event for %r: %s", title, e)
    if href_hit:
        return download_by_url(page, href_hit, out_path)
    return False


# ---------------------------------------------------------------------------
# Document source pages. document_source_urls() yields (url, label) pairs that
# cmd_discover scans. Repair the URLs after paperpull amex diagnose confirms the real ones.
# ---------------------------------------------------------------------------
STATEMENT_URLS = [
    URLS["statements"],
]
YEAR_END_URL = URLS["year_end"]
TAX_URL = URLS["tax"]


def document_source_urls() -> List[Tuple[str, str]]:
    """(url, source_label) pairs to scan for downloadable documents."""
    pairs = [(u, "statements") for u in STATEMENT_URLS]
    pairs.append((YEAR_END_URL, "year-end"))
    if TAX_URL not in [u for u, _ in pairs]:
        pairs.append((TAX_URL, "tax"))
    return pairs


# ---------------------------------------------------------------------------
# Host allowlist. Added repo-wide after a review found this app would fetch or
# navigate to whatever URL a stored record or a page attribute contained, using
# the live signed-in session. Parsed, never a string prefix, so a lookalike
# host cannot walk through.
# ---------------------------------------------------------------------------
ALLOWED_HOSTS = {'americanexpress.com'}


def is_safe_url(url: str) -> bool:
    """True only for an https URL on one of this provider's own hosts.

    The check itself lives in the core, so all of them answer the same way.
    This app keeps the hosts, which is the part that really is its own."""
    from paperpull_core.urls import is_safe_url as _host_allows
    return _host_allows(url, ALLOWED_HOSTS)
