"""ALL PG&E (pge.com) selectors, URLs, and page behavior live here.

When PG&E changes its site, repair this file only.

SAFETY (this is a utility billing account):
  This module is strictly READ-ONLY. It navigates to the billing-history
  area, reads the list of bills, and downloads the PDFs PG&E already
  generated. It must NEVER activate any control that pays a bill, sets up
  AutoPay or a payment plan, adds or changes a bank account or card, starts,
  stops or transfers service, or changes any setting. FORBIDDEN_CONTROL_RE is
  the guard; a control must ALSO look like a document action
  (SAFE_DOC_CONTROL_RE) before it may be clicked. There is no code here that
  submits a form or confirms a dialog.

ROUND EIGHT (#33, 2026-09-26). His 0.37.0 failure file was the first to
carry a journal, and it put 140 ms between taking the first bill and
giving up, with no wait for a bill viewer anywhere in it. A press that
brings nothing back waits seconds and then ends in that wait, so this
was a run that never pressed. The reason was the label reader. It asked
every ElementHandle for its text with a timeout, which a handle does not
take, the TypeError was swallowed, and every control read as unlabeled
and was refused. That alone produces the "controls []" of rounds two and
three and the "no option for page N in the picker" lines, whatever the
page holds, so the press and capture work of rounds five to seven never
ran on his account. Labels are now read the way the core reads them, and
the guard judges the text a person sees, as it was written to.

Reading labels switched on code that had never run for him, and a
review before release found four things in it. The press was forced,
which sends the mouse to whatever sits on top of the link, so a dialog
left over the row would have taken the click. It is an ordinary click
now, and when something covers the link the link's own click is used,
which reaches the approved element and nothing else. The guard judged
the first label it found and never the aria-label behind visible text,
so it judges every label now. The page picker clicked its option first
with no limit on the wait, and a click that could not land skipped the
by-value jump, the only jump proven on his history. That jump goes
first now, and the option is looked for inside the picker only. And a
bill opened in a new tab at a blob address was refused by the host
check, because the check moved to the core in 0.33.0 and the core does
not take blob addresses. The code that waits for that tab came from the
contributor who first built this against a real account, so it is read
again, by the page that made it and only when its origin is PG&E's.

A second review of that repair found the guard could still be walked
around. The row hands over the link and the cell it sits in, and when
the link was refused for a hidden label the cell was approved and the
click on the cell landed on the link. So a control is now judged with
everything around it and inside it, and is pressed only when all of it
passes. The same review found the page's own fetch of a blob refused by
the policy Salesforce sites run by default, which is why the contributor
had saved the blob as a download from the page that made it. That is the
fallback now, for a new tab and for a viewer in the page. And a press
that arrived and then raised while a page began to load is not pressed
a second time, the picker's proven sequence is kept as its last resort,
a bill slower than the press window is still heard while its own bill is
open, and the row outline is built from word lists.

A third review found what that still left out. A plain box around the
link whose label said Pay was judged only when its own words were exactly
View Bill PDF, and the page wide look judged a link alone and pressed one
its row had refused. A label hands its click to its control wherever that
sits, and words slotted into a shadow root go up through the slot. So
labeled boxes are judged up to the row, labels' controls are judged, the
walk goes the way a click travels, and the page wide look judges the row
it reaches as the usual look would and never looks again at a row that
refused. The same review found four ways a bill could be saved from
something its press did not bring. A viewer an earlier bill left open,
whose frame had moved on, was read again. A late download of an earlier
bill's blob was heard. A PDF any tab loaded, on any host, was heard. And a
download link made on the history for a PDF on another PG&E origin moved
the history tab instead. Each is closed, and the tab showing a blob is
asked only after the page that made it.

A safety review of that repair found one more way to save something
that is not the bill. The page wide look ran when the bill's row was
found and handed over nothing, and it held the row it reached to the
date alone. A payment made on the bill's day carries the bill's date,
and a link to its receipt passes the guard, so the receipt was saved as
the bill. The look runs only when no row was found now, it takes a row
only when the row reads View Bill PDF as well as carrying the date, and
it refuses when more than one row does. It refuses a row that reads View
Bill PDF more than once as well, since a list item holding several bills
is the row of every link in it, and a press there saved one bill under
another's date in a real browser while this was repaired. The same
review had the View Bill PDF control chosen ahead of any other that
passes, a tab that was open before the press never counted as the
press's, the tabs a press opened closed however the bill ends, and the
host a tab moved to said only as pge or elsewhere.

ROUND FOUR (#33, 2026-09-22). Round three's outline showed the control
plainly: a.pdf-link = "View Bill PDF", inside td > div.align-right, in
the light DOM. And still the row handed over nothing, which means the
selector queries on the row answer empty on this history. The page is a
Salesforce Lightning app, whose synthetic shadow DOM replaces
querySelectorAll on every element with one that hides a component's
children from anything outside the component. A walk over each node's
own children is not patched, which is how the outline saw the link. The
row's controls are now gathered by that walk, anchors and buttons and
anything whose own text reads View Bill PDF, and the rows are waited
for before they are read, since one discovery ran before the table had
drawn and found nothing.

ROUND THREE (#33, 2026-09-22). The tester's third pilot reported two
things. Every bill row read as a date, "Bill Charges View Bill PDF" and
an amount, and handed over no control, so "View Bill PDF" is not an anchor,
a button or a lightning-button on his history, and whatever element
carries the words was not in the list the app looked through. The row's
controls are now found by their own text, innermost element first,
whatever kind it is, and when a row still hands over nothing the log
prints the row's outline (tags, classes, roles, open shadow roots) so
the next round sees it. And the Jump to picker opened without listing its
options, "no option for page 2 in the picker", so after the click the
picker is asked through its own value and change event, the way a
Lightning parent hears it, before giving up.
"""
from __future__ import annotations

import base64
import html as _html
import itertools
import logging
import re
import tempfile
import time
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import urlsplit

from paperpull_core.dates import checked as _checked_date
from paperpull_core.capture import fetch_with_status as _fetch_with_status
from paperpull_core.failure import SAFE_TAGS as _CORE_TAGS
from paperpull_core.failure import SIGNAL_CLASSES as _CORE_CLASSES
from paperpull_core.controls import control_labels as _control_labels
from paperpull_core.controls import is_next_control as _core_is_next
from paperpull_core.ready import (count_reaches, count_settles, network_idle,
                                  new_source, ready, sources_of)

log = logging.getLogger("pge_docs.site")

# The run's journal, handed over by the orchestrator. None when nobody
# set one, and ready() is happy with None, so a journal is never the
# reason a working run stops.
_journal = None


def set_journal(journal) -> None:
    global _journal
    _journal = journal


def _trace(outcome: str, **facts) -> None:
    """How a bill's capture went, into the journal, as a phrase from this
    file and yes or no facts. The failure file carries it, and it is the
    one thing he attaches. Round eight had to be read off a 140 ms gap
    because nothing before the press wrote anything down (#33)."""
    if _journal is not None:
        _journal.result(outcome, **facts)


BASE = "https://myaccount.pge.com"
URLS = {
    "home": f"{BASE}/myaccount/s/",
    "login": f"{BASE}/myaccount/s/",
    "documents": f"{BASE}/myaccount/s/bill-and-payment-history",
    "statements": f"{BASE}/myaccount/s/bill-and-payment-history",
    "documents_alt": f"{BASE}/myaccount/s/",
}
# Only the history itself. The home page was on this list once, and landing
# there counted as success, so a run could report zero bills from a page that
# never had any.
DOCUMENT_URL_CANDIDATES = [URLS["documents"]]

LOGIN_URL_MARKERS = [
    "/login", "/signin", "/sign-in", "/site-signin", "/auth", "/mfa",
    "/verification", "/challenge", "sso.pge.com",
]

ALLOWED_HOSTS = [
    "www.pge.com", "pge.com", "myaccount.pge.com", "m.pge.com",
]

# ---------------------------------------------------------------------------
# HARD SAFETY GUARD - never click anything matching this. Tuned for a utility
# billing portal: never pay a bill, change service, or modify the account.
# ---------------------------------------------------------------------------
FORBIDDEN_CONTROL_RE = re.compile(
    r"(pay\b|payment|pay\s+bill|autopay|auto\s*pay|schedule\s+payment|"
    r"one[-\s]?time\s+payment|payment\s+plan|budget\s+billing|paperless|"
    r"bank\b|routing|account\s+number|debit|credit\s+card|\bcard\b|wallet|"
    r"enroll|unenroll|sign\s+up|start\s+service|stop\s+service|"
    r"transfer\s+service|disconnect|reconnect|new\s+service|move\s+service|"
    r"donate|contribution|round\s*up|"
    # Word boundaries on both sides of the verb stems. "edit" with only a
    # trailing boundary matches the end of "Credit", and a bill row that
    # carries a credit is exactly the sort of label this must let through.
    r"enable|disable|activate|deactivate|\bchang(e|es|ed|ing)\b|"
    r"\bedit(s|ed|ing)?\b|\bupdat(e|es|ed|ing)\b|modify|"
    r"set\s+up|delete|remove|cancel|close\s+account|"
    r"password|profile\b|settings|preferences|"
    r"confirm|submit|agree|accept|authorize|enroll|"
    r"save\s+changes|save\s+settings|update\s+settings|change\s+address|"
    r"edit\s+preferences|document\s+removal|loss\s+mitigation|"
    r"manage\s+autopay|turn\s+off|opt\s+out|update\s+beneficiary|"
    r"place\s+order|rebalance|liquidate|buy|sell)", re.I)

SAFE_DOC_CONTROL_RE = re.compile(
    r"(download|view|open|print|pdf|statement|document|bill|invoice|"
    r"report|history)", re.I)


def is_safe_control(label: str) -> bool:
    """Returns True ONLY if label names a document action and no forbidden verb."""
    if not label or not isinstance(label, str):
        return False
    text = label.strip()
    if not text:
        return False
    if FORBIDDEN_CONTROL_RE.search(text):
        return False
    # The settings and sign-in vocabulary every provider shares lives in core,
    # so a phrasing this list never thought of is still refused.
    from paperpull_core.controls import SETTINGS_CONTROL_RE, AUTH_CONTROL_RE
    if SETTINGS_CONTROL_RE.search(text) or AUTH_CONTROL_RE.search(text):
        return False
    return bool(SAFE_DOC_CONTROL_RE.search(text))


def _inner_text(el) -> str:
    """The text a person reads on an element, from a Locator or a handle.

    A Locator's inner_text takes a timeout and an ElementHandle's takes no
    arguments at all. Both label readers below passed the timeout to every
    element, and every element they were ever given here is a handle, so
    each call raised TypeError, the reader swallowed it, and the label came
    back empty. An empty label is refused, so every View Bill PDF this was
    handed was refused, in every version since this reader arrived in
    0.19.0 (#33). The core's control_labels already asks both ways."""
    try:
        return el.inner_text(timeout=1500)
    except TypeError:
        return el.inner_text()


def control_label(el) -> str:
    """What a person would read on this control. Inner text first, then the
    accessible name, then the title, so a bare icon still has a label to be
    judged by and an unlabeled one is refused."""
    for getter in (lambda: _inner_text(el),
                   lambda: el.get_attribute("aria-label"),
                   lambda: el.get_attribute("title")):
        try:
            text = (getter() or "").strip()
        except Exception:
            text = ""
        if text:
            return re.sub(r"\s+", " ", text)
    return ""


def all_labels(el) -> str:
    """Every label a control carries, joined. The page picker's own text is
    the current page number and its purpose is in the aria-label, so a guard
    that reads only one of them cannot judge it."""
    parts = []
    for getter in (lambda: _inner_text(el),
                   lambda: el.get_attribute("aria-label"),
                   lambda: el.get_attribute("title"),
                   lambda: el.get_attribute("label")):
        try:
            text = (getter() or "").strip()
        except Exception:
            text = ""
        if text:
            parts.append(re.sub(r"\s+", " ", text))
    return " | ".join(parts)


def is_page_picker(label: str) -> bool:
    """The history's page selector, and nothing that commits anything."""
    label = (label or "").strip()
    return bool(re.search(r"jump\s+to|page", label, re.I)) and not (
        FORBIDDEN_CONTROL_RE.search(label))


def is_page_option(label: str, target_page: int) -> bool:
    return (label or "").strip() == str(target_page)


def is_safe_url(url: str) -> bool:
    """True only for an https URL on one of this provider's own hosts.

    The check itself lives in the core, so all of them answer the same way.
    This app keeps the hosts, which is the part that really is its own."""
    from paperpull_core.urls import is_safe_url as _host_allows
    return _host_allows(url, ALLOWED_HOSTS)


SECURITY_CHALLENGE_MARKERS = [
    "enter the code", "verification code", "6-digit", "two-factor",
    "two-step", "authenticator", "confirm your identity", "verify your identity",
    # "unusual" on its own is not a marker. A utility tells you your usage
    # is unusually high on the same page as the bills.
    "we sent a code", "device approval", "approve this login", "unusual activity",
    "are you a robot", "captcha", "let's verify", "check your email",
    "check your phone", "your session has expired", "log back in",
]

RATE_LIMIT_MARKERS = [
    "too many requests", "rate limit", "try again later",
    "temporarily unavailable", "http error 429", "unusual traffic",
]

FALLBACK = {
    "doc_row": ("table tbody tr, [role='row'], [class*='documentRow'], "
                "[class*='DocumentRow'], [class*='row'][class*='document'], "
                "[data-testid*='document'], li[class*='document']"),
    "doc_link": ("a[href*='.pdf'], a[href*='document'], a[href*='statement'], "
                 "a[download], button[class*='download']"),
    "download_control": ("a:has-text('View Bill PDF'), a:has-text('View PDF'), "
                        "button:has-text('View Bill PDF'), a[href$='.pdf'], a[download]"),
    "page_ready": ("table, [role='row'], [class*='document'], [class*='statement'], "
                   "main, [role='main']"),
    "next_page": ("a[aria-label*='Next' i], button[aria-label*='Next' i], "
                  "[class*='next']"),
}

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
YEAR_RE = re.compile(r"\b(19|20)(\d{2})\b")


def _parse_date_from_page(raw: str) -> str:
    """Parse date text into ISO YYYY-MM-DD or empty string if unparseable."""
    if not raw:
        return ""
    text = _html.unescape(raw).strip()
    for pat, fmt in DATE_PATTERNS:
        m = pat.search(text)
        if m:
            if fmt == "mdY":
                mon_str, day_str, yr_str = m.group(1).lower()[:3], m.group(2), m.group(3)
                mon = _MONTHS.get(mon_str, 0)
                if mon:
                    return f"{int(yr_str):04d}-{mon:02d}-{int(day_str):02d}"
            elif fmt == "mdy_slash":
                mon, day, yr = int(m.group(1)), int(m.group(2)), int(m.group(3))
                return f"{yr:04d}-{mon:02d}-{day:02d}"
            elif fmt == "iso":
                return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return ""


def parse_date(text):
    """The date this provider's page is showing, as YYYY-MM-DD.

    The reading is below, unchanged. This only refuses to believe a result
    that names a day which does not exist, because a reference number is
    shaped like a date and used to be taken for one."""
    return _checked_date(_parse_date_from_page(text), "")


def parse_period_date(raw: str) -> Tuple[str, str]:
    """Parse period string returning (iso_date, confidence)."""
    exact = parse_date(raw)
    if exact:
        return exact, "HIGH"
    m_my = MONTH_YEAR_RE.search(raw)
    if m_my:
        mon_str, yr_str = m_my.group(1).lower()[:3], m_my.group(2)
        mon = _MONTHS.get(mon_str, 0)
        yr = int(yr_str)
        if mon:
            import calendar
            _, last_day = calendar.monthrange(yr, mon)
            return f"{yr:04d}-{mon:02d}-{last_day:02d}", "HIGH"
    m_yr = YEAR_RE.search(raw)
    if m_yr:
        yr = int(m_yr.group(0))
        return f"{yr:04d}-12-31", "MEDIUM"
    return "", "LOW"


def looks_signed_out(page) -> bool:
    """Return True if current page indicates session is logged out."""
    url = page.url.lower()
    return any(marker in url for marker in LOGIN_URL_MARKERS)


def detect_security_challenge(page) -> Optional[str]:
    """Name the 2FA, CAPTCHA or throttling prompt on screen, or None.

    Reads the visible text rather than the page source. The source of a
    Salesforce portal carries every string its scripts might ever show, so
    "verification code" is in there on a perfectly normal day."""
    try:
        title = (page.title() or "").lower()
    except Exception:
        title = ""
    try:
        body = page.locator("body").inner_text(timeout=5000).lower()
    except Exception:
        body = ""
    hay = title + "\n" + body[:2000]
    for m in SECURITY_CHALLENGE_MARKERS:
        if m in hay:
            return f"Security challenge detected: '{m}'"
    for m in RATE_LIMIT_MARKERS:
        if m in hay:
            return f"Possible rate limiting detected: '{m}'"
    return None


def on_documents_page(page) -> bool:
    """On the bill history itself, signed in, and not a 404."""
    try:
        url = (page.url or "").lower()
        title = (page.title() or "").lower()
    except Exception:
        return False
    return ("bill-and-payment-history" in url and is_safe_url(url)
            and not looks_signed_out(page)
            and "page not found" not in title and "404" not in title)


def goto_documents(page) -> bool:
    """Land on the bill history.

    The tab the user signed in on is reused. If it already shows the history
    nothing moves. Otherwise the history URL is tried, and if the portal
    answers that with its own 404 page (it has), the tab is left where it was
    so the user can open the history by hand, as login.bat asks them to."""
    if on_documents_page(page):
        return True
    start_url = page.url or ""
    for url in DOCUMENT_URL_CANDIDATES:
        if not is_safe_url(url):
            continue
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=15000)
            for _ in range(10):
                if on_documents_page(page):
                    return True
                page.wait_for_timeout(500)
        except Exception as e:
            log.info("documents URL %s failed: %s", url, e)
    if is_safe_url(start_url) and not looks_signed_out(page) and start_url != page.url:
        try:
            page.goto(start_url, wait_until="domcontentloaded", timeout=15000)
        except Exception:
            pass
    return on_documents_page(page)


def get_pagination_pages(page) -> List[int]:
    """Get list of available page numbers from Jump to combobox."""
    try:
        cb = page.query_selector("lightning-combobox[aria-label='Jump to'], .pagination-block lightning-combobox")
        if cb:
            opts = cb.evaluate("el => (el.options || []).map(o => o.value)")
            if opts:
                return sorted([int(v) for v in opts if str(v).isdigit()])
    except Exception as e:
        log.debug(f"Error getting pagination pages: {e}")
    return [1]


def _rows_signature(page) -> tuple:
    """The dates of the rows on the page, in order, so a page that did not
    change can be told from one that did."""
    try:
        rows = page.query_selector_all(FALLBACK["doc_row"])
        return tuple(parse_date(r.inner_text() or "") for r in rows[:12])
    except Exception:
        return ()


def _current_page(page) -> Optional[int]:
    try:
        cb = page.query_selector("lightning-combobox[aria-label='Jump to'], .pagination-block lightning-combobox")
        if cb:
            v = cb.evaluate("el => el.value")
            return int(v) if str(v).isdigit() else None
    except Exception:
        pass
    return None


def goto_page_number(page, target_page: int) -> bool:
    """Navigate the table to `target_page` through the Jump to combobox,
    and say so only once the table shows it. The picker's value has to
    read the target, and the rows have to have changed from what they
    were, before this returns True. Version one clicked the option,
    slept a second and a half, and answered True while the table still
    showed the page before (#33). Discovery then read page 1 seven times
    and filed every bill under page 7.

    The by-value jump goes first. It is the one jump proven on his
    history (round three found a bill on page 2 with it, and round five
    walked all seven pages), and it clicks nothing. Until round eight
    every label read empty, so the option click after it never ran. Once
    labels read, it ran first with no limit on its wait, and an option it
    could not click took the default thirty seconds, raised, and skipped
    the jump that works. A review before release showed that in a real
    browser. So the option is the fallback now, looked for inside this
    picker only, and every click on it is bounded. When neither moves the
    rows, the picker is closed and asked by value once more, which is the
    order the jump ran in when it walked his seven pages."""
    try:
        cb = page.query_selector("lightning-combobox[aria-label='Jump to'], .pagination-block lightning-combobox")
        if not cb:
            return False
        curr_val = cb.evaluate("el => el.value")
        if curr_val == target_page or str(curr_val) == str(target_page):
            return True
        before = _rows_signature(page)
        # The only two clicks outside a bill row. The picker must call itself
        # a page jump, and the option must be nothing but a page number, so a
        # combobox that turned into something else is left alone.
        if not is_page_picker(all_labels(cb)):
            log.info("the pagination control does not read as a page picker, left alone")
            return False
        # The picker as its parent hears it. A Lightning combobox tells the
        # page about a choice through a change event carrying the value,
        # and the parent's own handler reads event.detail.value. That is
        # the same message a click on the option sends, without needing
        # the option list to have rendered.
        if _jump_by_value(page, cb, target_page) and _wait_for_page_change(page, before, target_page, 8):
            return True
        log.info("page %d did not show when the picker was asked by value, "
                 "so its option is tried", target_page)
        try:
            cb.click(timeout=5000)
        except Exception as e:
            log.info("the page picker would not open (%s)", type(e).__name__)
            return False
        page.wait_for_timeout(400)
        opt = _page_option(cb, target_page)
        if opt is None:
            log.info("no option for page %d in the picker", target_page)
        else:
            clicked = True
            try:
                opt.click(timeout=3000)
            except Exception as e:
                clicked = False
                log.info("the option for page %d would not take a click (%s)",
                         target_page, type(e).__name__)
            if clicked and _wait_for_page_change(page, before, target_page, 8):
                return True
            # A Lightning option can swallow a plain click, and one that is
            # hidden or covered cannot take one at all. Once more through
            # the option's own click, which reaches that element and no
            # other, then the picker is given up on.
            try:
                opt.evaluate("el => el.click()")
            except Exception:
                pass
            if _wait_for_page_change(page, before, target_page, 8):
                return True
            log.info("page %d did not show after the jump (picker reads %s, rows %s)",
                     target_page, _current_page(page),
                     "unchanged" if _rows_signature(page) == before else "changed")
        # Nothing is left open over the rows.
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        # And last, the exact sequence that walked his whole history in
        # rounds three and five. The picker was opened, closed with Escape
        # and then asked by value. Asking by value first has not run on his
        # site with the picker never opened, so that sequence is kept as the
        # last thing tried (second review of round eight).
        if _jump_by_value(page, cb, target_page) and _wait_for_page_change(page, before, target_page, 8):
            log.info("page %d showed when the picker was asked by value once it had been opened",
                     target_page)
            return True
    except Exception as e:
        log.debug("goto_page_number %d failed: %s", target_page, type(e).__name__)
    return False


def _page_option(cb, target_page: int):
    """The option for `target_page`, from inside this picker and nowhere
    else. It was looked for across the whole page, so any open list with
    an option reading the same number could have been the one clicked.
    Its text must be the number and nothing else, and no label it carries
    may be a forbidden word."""
    try:
        options = cb.query_selector_all("lightning-base-combobox-item, [role='option']")
    except Exception:
        return None
    for opt in options or []:
        if not is_page_option(control_label(opt), target_page):
            continue
        if FORBIDDEN_CONTROL_RE.search(all_labels(opt)):
            continue
        return opt
    return None


def _jump_by_value(page, cb, target_page: int) -> bool:
    """Set the page picker's value and tell its parent, the way the
    component itself does after an option is chosen. Only ever the page
    picker, which has already passed is_page_picker."""
    try:
        cb.evaluate("""(el, v) => {
          el.value = v;
          el.dispatchEvent(new CustomEvent('change', {detail: {value: v}, bubbles: true, composed: true}));
        }""", str(target_page))
        return True
    except Exception as e:
        log.info("the picker would not take a value (%s)", type(e).__name__)
        return False


def _wait_for_page_change(page, before: tuple, target_page: int, seconds: int) -> bool:
    """True once the table shows different rows. The picker reading the
    target is the ideal, but a picker whose value never updates is not
    proof the page did not move, the rows are."""
    for _ in range(seconds * 2):
        page.wait_for_timeout(500)
        sig = _rows_signature(page)
        if sig and sig != before:
            page.wait_for_timeout(500)
            return True
    return False


def is_next_control(label: str) -> bool:
    """The history's Next page control, and nothing else.

    The allowlist lives in the core now, because eight other apps needed
    one and had been handing this question to their commit blocklist, which
    refuses the word "next" and so refused every Next control they had.
    """
    return _core_is_next(label)


def next_page(page) -> bool:
    """One page forward through the history's Next control, for a picker
    that will not jump. True once the rows changed."""
    before = _rows_signature(page)
    try:
        for cand in page.query_selector_all(FALLBACK["next_page"]):
            # Each label on its own. all_labels joins them for a log line,
            # and a control whose text is "Next" and whose aria-label is
            # "Next page" reads "Next | Next page" joined, which is not
            # what either of them says and matched nothing.
            if not any(is_next_control(part) for part in _control_labels(cand)):
                continue
            try:
                if cand.get_attribute("disabled") is not None or (cand.get_attribute("aria-disabled") or "") == "true":
                    return False
            except Exception:
                pass
            cand.click()
            return _wait_for_page_change(page, before, 0, 8)
    except Exception as e:
        log.debug(f"next_page failed: {e}")
    return False


def collect_download_docs(page) -> List[dict]:
    """Every bill across every page of the history, each with the page and
    row it was seen on. A bill seen twice keeps its first sighting, and a
    page that shows the same rows as the page before it means the jump did
    not take, so the walk stops there and says so rather than reading the
    same page again under a new number."""
    results: List[dict] = []
    seen_dates = set()
    try:
        wait_for_rows(page)
        pages = get_pagination_pages(page)
        last_sig = None
        for p_num in pages:
            if len(pages) > 1 and p_num != pages[0]:
                if not goto_page_number(page, p_num) and not next_page(page):
                    log.info("could not reach page %d of the history, stopping at %d bill(s)",
                             p_num, len(results))
                    break
            sig = _rows_signature(page)
            if sig and sig == last_sig:
                log.info("page %d shows the same rows as the page before, stopping", p_num)
                break
            last_sig = sig
            rows = page.query_selector_all(FALLBACK["doc_row"])
            for idx, row in enumerate(rows):
                text = row.inner_text() or ""
                if "View Bill PDF" in text:
                    date_str = parse_date(text)
                    if date_str and date_str not in seen_dates:
                        seen_dates.add(date_str)
                        results.append({
                            "date_text": date_str,
                            "title": f"Energy Statement - {date_str}",
                            "page_number": p_num,
                            "row_index": idx,
                            "summary": "Energy Statement",
                        })
        if len(pages) > 1:
            goto_page_number(page, pages[0])
    except Exception as e:
        log.debug(f"Error collecting docs: {e}")
    return results


def wait_for_rows(page, seconds: int = 20) -> int:
    """How many bill rows the page shows, once it shows any. The table
    draws a moment after the page, and one discovery ran before it had,
    read nothing, and said so as if the history were empty."""
    for _ in range(seconds * 2):
        try:
            rows = page.query_selector_all(FALLBACK["doc_row"])
            n = sum(1 for r in rows if "View Bill PDF" in (r.inner_text() or ""))
            if n:
                return n
        except Exception:
            pass
        page.wait_for_timeout(500)
    return 0


def _row_for_date(page, want_date: str, idx: int):
    """The bill row dated `want_date` on the page that is open. The row at
    `idx` first, then every row, since rows move as bills post.

    A bill row, the kind discovery counted, one that reads View Bill PDF.
    The history is of bills and payments, and a payment made on the day
    another bill is dated shares its date. Its row was taken for the bill,
    and since a refused row is not second guessed by the page wide look
    any more, a payment row with a link in it would have stopped the bill
    (third review of round eight).

    It has to read View Bill PDF exactly once. An element that holds
    several bills also reads View Bill PDF and can start with this bill's
    date, and pressing inside it saved another bill's PDF under this one
    (final review of #33)."""
    if not want_date:
        return None
    wait_for_rows(page)
    rows = page.query_selector_all(FALLBACK["doc_row"])
    order = ([rows[idx]] if 0 <= idx < len(rows) else []) + list(rows)
    for row in order:
        try:
            text = row.inner_text() or ""
            if text.count("View Bill PDF") == 1 and parse_date(text) == want_date:
                return row
        except Exception:
            continue
    return None


def pick_document_control(candidates, tally: Optional[dict] = None,
                          row=None) -> Optional[object]:
    """The first control in a bill row that reads as a document action and
    nothing else. A bill row also holds Pay, and a plain "first link in the
    row" once pointed at it. Every click on a row goes through here.

    Every label the control carries is judged, its text, aria-label, title
    and label together, so a forbidden word in any one of them refuses it.
    It judged the first label it found, and visible text reading View bill
    hid an aria-label reading Pay this bill (#33, review of round eight).

    And a control is judged by what is around it and inside it as well. A
    click on an element is a click on everything it sits in, and it lands
    on whatever sits under the mouse inside it. The row hands over the link
    and the cell around it as separate candidates, so when the link was
    refused its cell was approved, and the click on the cell landed on the
    refused link. The same went for a span reading View Bill PDF inside a
    button whose aria-label read Pay this bill. A second review of round
    eight did both in a real browser. So every candidate is judged first,
    and one is pressed only when nothing a press on it could reach fails
    the guard. _refused_nearby says what that covers.

    `row` is the bill row the candidates came from. Labels on the plain
    boxes around a control are judged up to that row and no further, so
    a heading above the table that reads Bill and Payment History is not
    taken for something the press could set off.

    Of the controls that pass, one that reads View Bill PDF goes first,
    and the rest follow in the order they came. The first that passed was
    the one pressed, so another document action ahead of the bill's link
    in the row, one whose words pass the guard too, was pressed instead
    (review of round eight's repair). This only orders what already
    passed, and a row whose one approved control says something else
    still hands it over.

    `tally`, when given, counts what was looked at, refused and unlabeled,
    and how many of the refused were refused for what was around them,
    numbers only, for the journal."""
    cands = list(candidates or [])
    labels = [all_labels(el) for el in cands]
    safe = [is_safe_control(label) for label in labels]
    refused = [el for el, ok in zip(cands, safe) if not ok]
    if tally is not None:
        tally["seen"] = tally.get("seen", 0) + len(cands)
        for label, ok in zip(labels, safe):
            if not ok:
                key = "refused" if label else "unlabeled"
                tally[key] = tally.get(key, 0) + 1
    passed = [el for el, ok in zip(cands, safe) if ok]

    def rank(el) -> int:
        # View Bill PDF exactly, then a plain View PDF, which an insert can
        # read too, then the rest in the order they came (final review).
        label = control_label(el)
        if _VIEW_BILL_PDF_RE.match(label):
            return 0
        return 1 if _VIEW_PDF_RE.match(label) else 2

    for el in sorted(passed, key=rank):
        if _refused_nearby(el, refused, row):
            if tally is not None:
                tally["refused"] = tally.get("refused", 0) + 1
                tally["nearby"] = tally.get("nearby", 0) + 1
            continue
        return el
    return None


# The next node up the path a click travels, which is the path of a
# composed event. Content slotted into a shadow root goes up through its
# slot and the shadow root's own elements before it reaches the host, and
# a click on it bubbles through them. Going straight to the host skipped
# a Pay button that wrapped the slot (third review of round eight). A
# closed shadow root hides its slot from the page, and nothing here can
# see inside one. _AROUND_JS refuses a control next to a component the
# page defined whose inside it cannot read, which is how a closed root on
# such a component looks from outside. A closed root on an ordinary
# element, or on a tag the page never defined, looks like no root at all
# and is not caught.
_UP_JS = ("const up = n => n.assignedSlot || n.parentElement"
          " || (n.parentNode && n.parentNode.host) || null;")

# Which of `others` sit around the element or inside it, along that path.
_NEAR_JS = r"""(el, others) => {
  %s
  const inside = (x, y) => { for (let n = x; n; n = up(n)) { if (n === y) return true; } return false; };
  const out = [];
  others.forEach((o, i) => { if (o && o !== el && (inside(el, o) || inside(o, el))) out.push(i); });
  return out;
}""" % _UP_JS

# Everything a press on the element could reach, as labels for the guard
# to judge. Only words go back to Python, to be matched and dropped. None
# of it is ever printed or journaled.
#
#   c true   a control. Anything that acts when a click reaches it or
#            passes through it. Every one around the element up to the
#            page's body, every one inside it, and the control of any
#            label among them, because a click on a label is handed to its
#            control wherever that sits on the page. A control must pass
#            the whole guard, a document action and no forbidden word.
#   c false  a plain box that carries a label of its own. Every one inside
#            the element, and every one around it up to its bill row. A
#            box with a click handler shows no sign of it, and its label
#            is the one clue to what it does, so no forbidden word may be
#            in it. It need not name a document, since a cell reading
#            Amount says nothing about a bill and does nothing either.
#
#   blind    a component the page defined whose inside cannot be read, the
#            element itself, one around it up to its row or one inside it.
#            A closed shadow root on such a component looks exactly like
#            that, and a Pay button in one took the click on words slotted
#            into it (third review of round eight). A guard that cannot
#            look has not approved anything, so it counts as a control that
#            says nothing, which is refused. Salesforce's lightning
#            components are not counted. A closed root on an ordinary
#            element looks like no root at all to this check, so it is not
#            counted either.
#
# The row is where plain boxes stop. Above it a region can read Bill and
# Payment History, and judging that would refuse every bill for a label
# no press of one could change. With no row given, the nearest row up
# the path is the stop, and with none at all, the body is. The same goes
# for components that cannot be read, since the whole page sits in them.
#
# Controls stop below the body. A handler there hears every click on the
# page, and its text is the whole history, Payment rows included, so
# judging it would refuse every bill in the same way.
#
# `l` is aria-label, title and the label attribute. `x` is the text an
# aria-labelledby points at, and alt. Those were never read before, so
# they only ever refuse and never make something pass.
_AROUND_JS = r"""(el, row) => {
  const tags = new Set(['a', 'button', 'summary', 'select', 'input', 'textarea', 'label',
    'option', 'lightning-button', 'lightning-button-icon', 'lightning-button-menu',
    'lightning-button-stateful', 'lightning-formatted-url', 'lightning-input']);
  const roles = new Set(['button', 'link', 'menuitem', 'menuitemcheckbox', 'menuitemradio',
    'option', 'tab', 'checkbox', 'radio', 'switch']);
  const acts = n => {
    if (!n || n.nodeType !== 1) return false;
    const role = (n.getAttribute('role') || '').toLowerCase().split(/\s+/);
    return tags.has(n.tagName.toLowerCase()) || role.some(r => roles.has(r))
      || n.hasAttribute('onclick');
  };
  %s
  const top = new Set([document.body, document.documentElement]);
  const norm = s => (s || '').replace(/\s+/g, ' ').trim();
  const own = n => ['aria-label', 'title', 'label'].map(a => norm(n.getAttribute(a))).filter(Boolean);
  const refs = n => {
    const ids = norm(n.getAttribute('aria-labelledby')).split(' ').filter(Boolean);
    const root = n.getRootNode && n.getRootNode().getElementById ? n.getRootNode() : document;
    const said = ids.map(id => {
      const t = root.getElementById(id) || document.getElementById(id);
      return t ? norm(t.innerText || t.textContent) : '';
    });
    return said.concat([norm(n.getAttribute('alt'))]).filter(Boolean);
  };
  // A component the page defined whose inside the page cannot read, which
  // is what a closed shadow root looks like from outside. What a click
  // does in there cannot be judged. Salesforce's own base components are
  // left out, since their insides are a button or an icon and their own
  // label is judged.
  const sealed = n => {
    const t = (n.localName || '');
    return t.includes('-') && !t.startsWith('lightning-') && !n.shadowRoot
      && !!(window.customElements && window.customElements.get(t));
  };
  const blind = () => ({c: true, t: '', l: [], x: []});
  const out = [];
  const seen = new Set([el]);
  const control = n => {
    if (!n || n.nodeType !== 1 || seen.has(n) || out.length > 300) return;
    seen.add(n);
    out.push({c: true, t: norm(n.innerText), l: own(n), x: refs(n)});
    if (n.tagName.toLowerCase() === 'label' && n.control) control(n.control);
  };
  const box = n => {
    if (!n || n.nodeType !== 1 || seen.has(n) || out.length > 300) return;
    const l = own(n), x = refs(n);
    if (l.length || x.length) { seen.add(n); out.push({c: false, l: l, x: x}); }
  };
  out.push({c: false, l: [], x: refs(el)});
  if (sealed(el)) out.push(blind());
  if (el.tagName.toLowerCase() === 'label' && el.control) control(el.control);
  const isRow = n => row ? n === row : !!(n.matches && n.matches('tr, [role=row], li'));
  let inRow = true;
  for (let n = up(el); n && !top.has(n); n = up(n)) {
    if (inRow && isRow(n)) inRow = false;
    if (acts(n)) control(n); else if (inRow) box(n);
    if (inRow && sealed(n)) out.push(blind());
  }
  const walk = n => {
    const kids = n.shadowRoot ? [...n.shadowRoot.children, ...n.children] : [...n.children];
    for (const c of kids) {
      if (out.length > 300) return;
      if (acts(c)) control(c); else box(c);
      if (sealed(c)) out.push(blind());
      walk(c);
    }
  };
  walk(el);
  // More than this was not all judged, so it counts as a control that
  // says nothing, which the guard refuses.
  if (out.length > 300) out.push(blind());
  return out;
}""" % _UP_JS


def _forbidden(text: str) -> bool:
    """A word no press may be near. The guard's own list and the core's
    settings and sign-in words, without the document-action half of
    is_safe_control."""
    if not text:
        return False
    from paperpull_core.controls import SETTINGS_CONTROL_RE, AUTH_CONTROL_RE
    return bool(FORBIDDEN_CONTROL_RE.search(text) or SETTINGS_CONTROL_RE.search(text)
                or AUTH_CONTROL_RE.search(text))


def _reach_refused(part) -> bool:
    """One thing a press could reach, as _AROUND_JS described it, judged.
    Anything shaped otherwise is refused, since it cannot be judged."""
    if not isinstance(part, dict):
        return True

    def words(key):
        return [str(s) for s in (part.get(key) or []) if isinstance(s, str) and s]

    if _forbidden(" | ".join(words("x"))):
        return True
    if part.get("c") is True:
        text = part.get("t") if isinstance(part.get("t"), str) else ""
        label = " | ".join([t for t in [text] + words("l") if t])
        return not is_safe_control(label)
    return _forbidden(" | ".join(words("l")))


def _refused_nearby(el, refused: list, row=None) -> bool:
    """True when a press on `el` could set off something the guard did not
    approve. That is a refused or unlabeled candidate around it or inside
    it, a control around it, inside it or tied to it by a label that does
    not pass, or a labeled box around it in its row or inside it whose
    label carries a forbidden word. When the page cannot be asked, the
    answer is True, because a guard that cannot look has not approved
    anything."""
    try:
        if refused and el.evaluate(_NEAR_JS, refused):
            return True
        reach = el.evaluate(_AROUND_JS, row)
    except Exception as e:
        log.info("what sits around a control could not be read (%s), so it is refused",
                 type(e).__name__)
        return True
    if not isinstance(reach, list):
        return True
    return any(_reach_refused(part) for part in reach)


# The bill row a control sits in, found up the same path a click travels.
_ROW_OF_JS = r"""el => {
  %s
  for (let n = up(el); n; n = up(n)) { if (n.matches && n.matches('tr, [role=row], li')) return n; }
  return null;
}""" % _UP_JS


def _row_of(el):
    """The row a control sits in, or None."""
    try:
        return el.evaluate_handle(_ROW_OF_JS).as_element()
    except Exception:
        return None


def _same_node(a, b) -> bool:
    """Two handles on one element. When the page cannot say, they are taken
    to be two, which can only make the page wide look refuse."""
    try:
        return bool(a.evaluate("(x, y) => x === y", b))
    except Exception:
        return False


def _bill_rows_page_wide(page, want_date: str) -> Tuple[list, int]:
    """Every bill row dated `want_date` that a control on the page sits in,
    each row once, and how many of them read View Bill PDF more than once.

    The controls are the ones that could be a bill's PDF, a link or button
    reading View Bill PDF, a link to a PDF and a link marked as a download.
    A row is kept only when it reads View Bill PDF and carries the date,
    the same test _row_for_date and discovery use. A link to a PDF can sit
    in a payment's row, and a payment made on the day a bill is dated
    carries the bill's date, so the date alone let a receipt be saved as
    the bill (safety review of round eight's repair).

    A row that reads View Bill PDF more than once holds more than one
    bill. The row is the nearest list item or table row above a control,
    and when the bills are plain boxes inside one list item, that item is
    the row of every control in it. Its first date can be this bill's
    while the only link in it is another bill's, and a press inside it
    saved one bill under another's date. download_bill refuses such a row,
    and the count says it was there."""
    rows, crowded = [], 0
    try:
        cands = page.query_selector_all(FALLBACK["download_control"])
    except Exception as e:
        log.info("the page wide look could not ask the page (%s)", type(e).__name__)
        return rows, crowded
    for cand in cands:
        own = _row_of(cand)
        if own is None:
            continue
        try:
            text = own.inner_text() or ""
        except Exception:
            continue
        if "View Bill PDF" not in text or parse_date(text) != want_date:
            continue
        if any(_same_node(own, seen) for seen in rows):
            continue
        rows.append(own)
        if text.count("View Bill PDF") > 1:
            crowded += 1
    return rows, crowded


_VIEW_PDF_RE = re.compile(r"^\s*view\s+(bill\s+)?pdf\s*$", re.I)
_VIEW_BILL_PDF_RE = re.compile(r"^\s*view\s+bill\s+pdf\s*$", re.I)

# Every control in the row, gathered by walking each node's own children
# rather than querySelectorAll, which Lightning's synthetic shadow DOM
# patches to hide a component's children from anything outside it (round
# three's outline saw a.pdf-link that way while every query saw nothing).
# Anchors, buttons and anything whose own text reads View Bill PDF,
# innermost first, so the thing a person clicks comes before its cell.
_ROW_TEXT_CONTROLS_JS = r"""row => {
  const rx = /^\s*view\s+(bill\s+)?pdf\s*$/i;
  const out = [];
  const walk = (el) => {
    const kids = el.shadowRoot ? [...el.shadowRoot.children, ...el.children] : [...el.children];
    for (const c of kids) {
      const tag = c.tagName ? c.tagName.toLowerCase() : '';
      const t = (c.innerText || c.textContent || '').trim();
      const role = c.getAttribute ? (c.getAttribute('role') || '') : '';
      if (tag === 'a' || tag === 'button' || role === 'button' || tag === 'lightning-button' || rx.test(t)) out.push(c);
      walk(c);
    }
  };
  walk(row);
  // innermost first: an element none of the others is inside of
  out.sort((a, b) => (a.contains(b) ? 1 : b.contains(a) ? -1 : 0));
  return out;
}"""


def row_controls(row) -> list:
    """Everything in a bill row that could be its PDF control. Anchors and
    buttons first, then every element whose own text reads View Bill PDF,
    innermost first, whatever it is, shadow roots included, since on the
    tester's history the control was none of the usual kinds (#33)."""
    out = []
    try:
        handles = row.evaluate_handle(_ROW_TEXT_CONTROLS_JS)
        props = handles.get_properties()
        for h in props.values():
            el = h.as_element()
            if el is not None:
                out.append(el)
    except Exception as e:
        log.debug("text controls in row: %s", e)
    # The selector queries too, for a history where they do answer.
    for sel in ("a, button, [role='button']", "lightning-button, lightning-formatted-url"):
        try:
            for el in row.query_selector_all(sel):
                out.append(el)
        except Exception:
            continue
    return out


# The row's structure, handed back as parts rather than as lines, so the
# line he pastes is built here from what may leave and not from the page.
# It follows open shadow roots only. A closed one reads as no root at all
# from the page, so it never shows here.
_ROW_OUTLINE_JS = r"""row => {
  const out = [];
  const walk = (el, d, inShadow) => {
    if (d > 6 || out.length > 60) return;
    const tag = el.tagName ? el.tagName.toLowerCase() : '#';
    out.push({
      depth: d, shadow: inShadow, tag: tag,
      cls: (el.className || '').toString().split(/\s+/).filter(Boolean).slice(0, 8),
      role: el.getAttribute ? (el.getAttribute('role') || '') : '',
      own: Array.from(el.childNodes || []).filter(n => n.nodeType === 3).map(n => n.textContent.trim()).filter(Boolean).join(' '),
      href: (tag === 'a' && el.getAttribute) ? (el.getAttribute('href') || '') : '',
      labeled: !!(el.getAttribute && ['aria-label', 'title', 'label', 'aria-labelledby', 'alt']
        .some(a => (el.getAttribute(a) || '').trim())),
      root: !!el.shadowRoot});
    if (el.shadowRoot) for (const c of el.shadowRoot.children) walk(c, d + 1, true);
    for (const c of (el.children || [])) walk(c, d + 1, inShadow);
  };
  walk(row, 0, false);
  return out;
}"""

# Words a bill row may be quoted saying, as this file spells them. Any
# other text is named by its shape.
_ROW_WORDS = {w.lower(): w for w in (
    "View Bill PDF", "View PDF", "View Bill", "View", "Bill Charges", "Bill",
    "PDF", "Download", "Print", "Details", "Pay", "Pay Bill", "Pay Now",
    "Payment", "Amount Due", "Due Date")}
_AMOUNT_RE = re.compile(r"[-+(]?\s*\$\s*[\d,]*\.?\d*\)?|[-+]?[\d,]+\.\d{2}")

# The outline's words come from lists, never from the page. Tags and layout
# classes the core already allows, the Lightning tags this history is built
# from, the classes round three's outline showed on his rows, and ARIA's own
# roles. A class or a tag the page made up is named by its kind and nothing
# more, since he pastes this into a public issue (second review of round
# eight, where a shape filter let any class without digits through).
_LIGHTNING_TAGS = frozenset("""
lightning-button lightning-button-icon lightning-button-menu lightning-formatted-url
lightning-formatted-text lightning-formatted-number lightning-formatted-date-time
lightning-icon lightning-primitive-icon lightning-combobox lightning-base-combobox
lightning-base-combobox-item lightning-layout lightning-layout-item lightning-card
lightning-spinner lightning-datatable lightning-input
""".split())
_ROW_CLASSES = frozenset("""
rowbox row-box row-box-td align-right pdf-link no-padding-right payoffamount-div
payoffamount-divpara slds-col slds-grid slds-table slds-truncate slds-button
slds-text-link slds-hide slds-show slds-hint-parent slds-cell-wrap slds-modal
slds-backdrop slds-is-open slds-dropdown slds-listbox
""".split())
_ARIA_ROLES = frozenset("""
button link menuitem option tab checkbox radio switch dialog alertdialog row cell
gridcell rowheader columnheader grid table rowgroup list listitem listbox combobox
img presentation none region group navigation main heading status alert tooltip
document article tabpanel tablist menu menubar
""".split())


def _outline_tag(tag) -> str:
    t = str(tag or "").lower()
    if t in _CORE_TAGS or t in _LIGHTNING_TAGS:
        return t
    return "custom" if "-" in t else "other"


def _shape(text: str) -> str:
    """Page text as it may leave. A word this file knows is printed the
    way this file spells it, and anything else only by its shape."""
    t = re.sub(r"\s+", " ", text or "").strip()
    if not t:
        return ""
    known = _ROW_WORDS.get(t.lower())
    if known:
        return known
    if parse_date(t):
        return "<date>"
    if _AMOUNT_RE.fullmatch(t):
        return "<amount>"
    if re.fullmatch(r"[\d\s#*.,/()-]+", t):
        return "<number>"
    words = min(len(t.split()), 99)
    return "<%d word%s>" % (words, "" if words == 1 else "s")


def _href_kind(href: str) -> str:
    """What kind of address a link holds, in words from this file."""
    h = (href or "").strip()
    if not h:
        return ""
    low = h.lower()
    if low.startswith("#"):
        return "hash"
    if low.startswith("javascript:"):
        return "script"
    if low.startswith("blob:"):
        return "blob"
    try:
        pdf = urlsplit(h).path.lower().endswith(".pdf")
    except ValueError:
        return "unreadable"
    if low.startswith("https://") or low.startswith("http://"):
        kind = "pge" if is_safe_url(h) else "elsewhere"
    else:
        kind = "relative"
    return kind + (" pdf" if pdf else "")


def _outline_line(part: dict) -> str:
    """One node of the row, in words from the lists above. Whether it
    carries a label the guard reads (aria-label, title, label, an
    aria-labelledby or alt) is said as a yes, never what it says, because
    the guard refuses a control for what is around it, and the next round
    needs to see which node could have been the reason."""
    tag = _outline_tag(part.get("tag"))
    cls = [c for c in (part.get("cls") or []) if isinstance(c, str)
           and (c.lower() in _ROW_CLASSES or c.lower() in _CORE_CLASSES)][:2]
    role = str(part.get("role") or "").lower().strip()
    own = _shape(str(part.get("own") or ""))
    href = _href_kind(str(part.get("href") or ""))
    try:
        depth = max(0, min(int(part.get("depth") or 0), 8))
    except (TypeError, ValueError):
        depth = 0
    return ("  " * depth + ("~" if part.get("shadow") else "") + tag
            + ("." + ".".join(c.lower() for c in cls) if cls else "")
            + (" [%s]" % role if role in _ARIA_ROLES else "")
            + (" (labeled)" if part.get("labeled") is True else "")
            + (" = " + own if own else "")
            + (" href=" + href if href else "")
            + (" {shadow}" if part.get("root") else ""))


def _describe_row(row) -> str:
    """What a row holds, for the log line that says no control was found
    in it, built only from what may leave, since he pastes this into a
    public issue. Tags, classes and roles from the lists above, the words
    above, and the shape of anything else. It used to print the row's own
    text with long digit runs masked, and an amount or a short run of an
    account number went straight through (#33, review of round eight)."""
    try:
        text = row.inner_text() or ""
    except Exception:
        text = ""
    facts = "date %s, View Bill PDF %s" % (
        "yes" if parse_date(text) else "no",
        "yes" if "View Bill PDF" in text else "no")
    labels = []
    try:
        for el in row.query_selector_all("a, button, [role='button'], lightning-button, span, div"):
            label = _shape(control_label(el))
            if label and label not in labels:
                labels.append(label)
            if len(labels) >= 8:
                break
    except Exception:
        pass
    try:
        parts = row.evaluate(_ROW_OUTLINE_JS) or []
    except Exception:
        parts = []
    outline = [_outline_line(p) for p in parts if isinstance(p, dict)]
    return "row holds %s, controls %s\n  [site] row outline:\n    %s" % (
        facts, labels, "\n    ".join(outline))


def _url_shape(url: str) -> str:
    """Enough of an address to say what kind of page it is, and no more.
    This goes in the output a tester copies into an issue.

    The host is said as pge or elsewhere, the way _href_kind says a link's.
    It was printed as written, and a tab can move to an address nobody
    chose (review of round eight's repair)."""
    url = url or ""
    if url.startswith("blob:"):
        return "a blob on pge" if _blob_on_pge(url) else "a blob elsewhere"
    try:
        tail = (urlsplit(url).path or "/").rsplit("/", 1)[-1]
    except ValueError:
        return "a page"
    kind = "a PDF" if tail.lower().endswith(".pdf") else "a page"
    return "%s %s" % (kind, "on pge" if is_safe_url(url) else "elsewhere")


def _pdf_from_here(page, before=()) -> Optional[bytes]:
    """The PDF the tab is standing on, or the one inside it.

    PG&E can answer View Bill PDF by moving the tab to its own viewer,
    which is an iframe around the file. Rendering that gives one blank
    sheet, because a viewer is a program and not a document. The file
    itself is fetched through the signed-in session instead, first at the
    address the tab is on and then at whatever its frames hold.

    A bill that opened in a dialog is the same question asked of a page
    that never went anywhere, and a viewer in a dialog often points at a
    blob the page made rather than at an address on the site. A blob
    belongs to the page, so only the page can fetch it, which is what the
    in-page fetch is for. A page whose policy refuses that fetch can still
    save its own blob as a download, so that is tried when the fetch
    brought nothing.

    `before` is every address this reads, as it stood before the press,
    and none of it is ever fetched. Putting it last was not enough. When a
    press brought nothing new, the fetch fell through to the viewer an
    earlier bill had left open and saved that bill under this one's date,
    and a review before release reproduced exactly that. Nothing new means
    nothing, which fails and says so.

    Every address, and not only where the viewers point. This reads the
    tab's own address and every frame's address as well, and a frame
    that followed a redirect is somewhere other than its viewer says. An
    earlier bill's viewer that had moved on like that was fetched again
    and saved under the next bill's date, which the third review of round
    eight did in a real browser. _addresses_before takes them all."""
    seen, blobs = _viewer_sources(page)
    old = set(before or ())
    seen = [s for s in seen if s not in old]
    blobs = [s for s in blobs if s not in old]

    for candidate in seen[:6]:
        try:
            res = page.request.get(candidate, timeout=60000)
            body = res.body() if res.ok else b""
        except Exception as e:
            log.info("fetch %s: %s", _url_shape(candidate), type(e).__name__)
            continue
        if body[:5] == b"%PDF-":
            return body

    for candidate in blobs[:4]:
        body = b""
        try:
            got = _fetch_with_status(page, candidate)
            body = base64.b64decode(got["b64"]) if got.get("b64") else b""
        except Exception as e:
            log.info("fetch a blob: %s", type(e).__name__)
        if body[:5] == b"%PDF-":
            _remember_blob(candidate)
            return body
        # A page whose policy keeps fetch off blobs still lets it save one.
        # Only when the fetch brought nothing, since a blob that was read
        # and is not a bill will not become one by being saved.
        if not body:
            body = _blob_by_download((page,), candidate) or b""
            if body[:5] == b"%PDF-":
                return body
    return None


def _addresses_before(page) -> list:
    """Every address _pdf_from_here could fetch, before the press. The
    viewers' sources, and the tab's and its frames' own addresses."""
    seen, blobs = _viewer_sources(page)
    return list(sources_of(page, VIEWER_ELEMENTS)) + list(seen) + list(blobs)


def _blob_on_pge(url: str) -> bool:
    """A blob address minted by a PG&E page. A blob carries the origin of
    the page that made it, blob:https://myaccount.pge.com/..., and that
    origin is held to the same host check as any other address."""
    url = url or ""
    return url.startswith("blob:") and is_safe_url(url[len("blob:"):])


def _pdf_from_blob_tab(page, tab, blob_url: str) -> Optional[bytes]:
    """The bill in a new tab that opened at a blob address, or None.

    The contributor who first built this against a real account wrote the
    wait for exactly this tab, and the host check then took blob:https
    addresses on PG&E's hosts. The check moved to the core in 0.33.0, the
    core takes https alone, and from then on this tab was waited for and
    thrown away. The blob belongs to the page that made it, so the page
    fetches it, and the tab is asked second in case the page let it go.
    The fetch checks the origin again inside the page (#33, review of
    round eight)."""
    if not _blob_on_pge(blob_url):
        return None
    for holder in (page, tab):
        if holder is None:
            continue
        try:
            got = _fetch_with_status(holder, blob_url, ALLOWED_HOSTS)
            body = base64.b64decode(got["b64"]) if got.get("b64") else b""
        except Exception as e:
            log.info("the blob tab could not be read here (%s)", type(e).__name__)
            continue
        if body[:5] == b"%PDF-":
            return body
    return None


# Whether a blob address was made by this very page's origin. Saving one
# through a link only works on its own origin, and a link to anything else
# would move the tab instead, so nothing is clicked unless this says yes.
_SAME_ORIGIN_BLOB_JS = r"""(url) => {
  try { return url.startsWith('blob:') && new URL(url.slice(5)).origin === location.origin; }
  catch (e) { return false; }
}"""

# The contributor's way, from the commit that made the capture work on a
# live account. A link this code makes, never one of the page's controls,
# pointing at the page's own blob and marked as a download.
_SAVE_BLOB_JS = r"""(url) => {
  const a = document.createElement('a');
  a.href = url;
  a.download = 'bill.pdf';
  a.style.display = 'none';
  (document.body || document.documentElement).appendChild(a);
  a.click();
  a.remove();
}"""


def _blob_by_download(holders, blob_url: str) -> Optional[bytes]:
    """A PG&E blob saved as a download from a page on its own origin, or
    None.

    The in-page fetch is refused by a page whose policy keeps fetch off
    blob addresses, and a Salesforce site's policy does exactly that by
    default. His history is one (its answers carry Salesforce's CSP
    setting). The contributor met this in his own pilot. His first blob
    capture fetched it in the page, and the commit that made the capture
    work replaced that with this, a download from the page that made the
    blob. A second review of round eight showed the fetch failing and
    this still working under that policy in a real browser (#33)."""
    if not _blob_on_pge(blob_url):
        return None
    for holder in holders:
        if holder is None:
            continue
        try:
            if not holder.evaluate(_SAME_ORIGIN_BLOB_JS, blob_url):
                continue
            # Before the click, since a download the browser holds back
            # (asking whether the site may save several files) can be let
            # go after this gives up, while a later bill is listening.
            _remember_blob(blob_url)
            # Only the download of this address. A download an earlier
            # bill's save started, held back and let go now, is another
            # bill's (final review of #33).
            with holder.expect_download(predicate=lambda d: d.url == blob_url,
                                        timeout=10000) as info:
                holder.evaluate(_SAVE_BLOB_JS, blob_url)
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "bill.pdf"
                info.value.save_as(str(path))
                body = path.read_bytes()
        except Exception as e:
            log.info("the blob could not be saved from here (%s)", type(e).__name__)
            continue
        if body[:5] == b"%PDF-":
            return body
    return None


# Addresses an earlier bill in this run already had, and a download of one
# of them that turns up later is never saved under the bill being taken
# now. The case is a save the browser held back to ask about several
# downloads, let go after the bill it was for had given up, while a later
# bill was listening (third review of round eight).
#
# Every blob address a bill was read or saved from, since a blob address
# is made new each time and names one file. And every PG&E address this
# code itself made a download link for. An address PG&E's own download
# came from is not kept, because one address could serve every bill in
# turn, and keeping it would refuse each bill after the first.
_ADDRESSES_TAKEN: set = set()


def _remember_blob(url: str) -> None:
    if url and url.startswith("blob:"):
        _ADDRESSES_TAKEN.add(url)


def _pdf_at(page, url: str) -> Optional[bytes]:
    """A PDF at a PG&E address, asked for through the signed-in session.
    Nothing is clicked and no tab moves. None unless it is a PDF."""
    if not is_safe_url(url):
        return None
    try:
        res = page.request.get(url, timeout=60000)
        body = res.body() if res.ok else b""
    except Exception as e:
        log.info("fetch %s: %s", _url_shape(url), type(e).__name__)
        return None
    return body if body[:5] == b"%PDF-" else None


def _same_origin(a: str, b: str) -> bool:
    """Two https addresses with one scheme, host and port."""
    try:
        pa, pb = urlsplit(a or ""), urlsplit(b or "")
    except ValueError:
        return False
    return bool(pa.netloc) and pa.scheme == "https" and (
        (pa.scheme, pa.netloc.lower()) == (pb.scheme, pb.netloc.lower()))


# The contributor's download link for an address on the page's own origin.
# A link this code makes, never one of the page's controls.
_SAVE_URL_JS = r"""(url) => {
  if (new URL(url, location.href).origin !== location.origin) return false;
  const a = document.createElement('a');
  a.href = url;
  a.download = 'statement.pdf';
  a.style.display = 'none';
  (document.body || document.documentElement).appendChild(a);
  a.click();
  a.remove();
  return true;
}"""


def _https_by_download(page, url: str) -> Optional[bytes]:
    """A PDF on the history's own origin, saved as a download from the
    history. The page checks the origin once more before it clicks."""
    if not is_safe_url(url) or not _same_origin(page.url, url):
        return None
    # Before the click, for the same reason as a blob's.
    _ADDRESSES_TAKEN.add(url)
    try:
        # Only the download of this address, for the same reason as a
        # blob's. A redirected download then fails rather than guessing.
        with page.expect_download(predicate=lambda d: d.url == url,
                                  timeout=10000) as info:
            if not page.evaluate(_SAVE_URL_JS, url):
                raise RuntimeError("not this page's origin")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bill.pdf"
            info.value.save_as(str(path))
            body = path.read_bytes()
    except Exception as e:
        log.info("the new tab's address could not be saved from here (%s)", type(e).__name__)
        return None
    return body if body[:5] == b"%PDF-" else None


def _whose_answer(res, page, before=()) -> str:
    """Whose an answer heard on the browser is, for the bill being taken.

    "ours" is an answer on PG&E's hosts, heard in the history tab or in a
    tab the history opened during this press. "first" is on PG&E's hosts
    and is the first answer of a tab that is only now opening, which
    cannot be named yet (Playwright gives a request made before its frame
    no frame at all). It is held and taken only once the tab this press
    opened stands at its address. Everything else is "elsewhere" and never
    saved.

    The listener is on the whole browser, so the answer a new tab loads
    is heard, and it took any PDF from any tab on any host. A PDF another
    tab loaded while a bill was open was saved as that bill (third review
    of round eight).

    `before` is every tab that was open before the press, and none of
    them but the history is this press's. A tab the history had opened
    earlier, for an earlier bill or by hand, counted as the history's, so
    a PDF it loaded while this bill was open was saved as this bill
    (review of round eight's repair)."""
    try:
        if not is_safe_url(res.url or ""):
            return "elsewhere"
    except Exception:
        return "elsewhere"
    try:
        owner = res.frame.page
    except Exception:
        try:
            return "first" if res.request.is_navigation_request() else "elsewhere"
        except Exception:
            return "elsewhere"
    try:
        if owner is page:
            return "ours"
        if any(owner is tab for tab in before):
            return "elsewhere"
        if owner.opener() is page:
            return "ours"
    except Exception:
        pass
    return "elsewhere"


def _take_blob(holders, blob_url: str) -> Tuple[Optional[bytes], bool]:
    """A PG&E blob, from the first holder that can give it, and whether it
    came as a download.

    Each holder is asked both ways before the next is asked at all, the
    page's fetch and then a download from it. The opener comes first. A
    new tab showing a PDF is the browser's own viewer, and a script asked
    to run inside one has no time limit here, so it is asked only when the
    page that made the blob could not give it up (third review of round
    eight)."""
    if not _blob_on_pge(blob_url):
        return None, False
    for holder in holders:
        if holder is None:
            continue
        body = _pdf_from_blob_tab(holder, None, blob_url)
        if body:
            return body, False
        body = _blob_by_download((holder,), blob_url)
        if body:
            return body, True
    return None, False


# What a viewer sits in. CSS and not Playwright's dialect, because ready()
# counts these inside the page.
VIEWER_ELEMENTS = "iframe, embed, object"


def _viewer_sources(page) -> Tuple[list, list]:
    """Every address the tab and its viewers point at, on PG&E or a blob.

    Split out of _pdf_from_here so the same reading can say, before a
    click and after it, whether anything new arrived."""
    seen, blobs = [], []
    url = page.url or ""
    if url.startswith("blob:"):
        blobs.append(url)
    elif url and is_safe_url(url):
        seen.append(url)
    try:
        for frame in page.frames:
            f_url = frame.url or ""
            if not f_url or f_url.startswith("about:"):
                continue
            if f_url.startswith("blob:") and f_url not in blobs:
                blobs.append(f_url)
            elif f_url not in seen and is_safe_url(f_url):
                seen.append(f_url)
    except Exception as e:
        log.info("frames: %s", type(e).__name__)
    try:
        for src in page.eval_on_selector_all(
                VIEWER_ELEMENTS,
                "els => els.map(e => e.src || e.data || '').filter(Boolean)") or []:
            if src.startswith("blob:") and src not in blobs:
                blobs.append(src)
            elif src not in seen and is_safe_url(src):
                seen.append(src)
    except Exception as e:
        log.info("embedded sources: %s", type(e).__name__)
    return seen, blobs


def _viewers_now(page) -> list:
    """What the page's viewers point at, kept to compare with later."""
    return sources_of(page, VIEWER_ELEMENTS)


def _wait_for_viewer(page, before: list):
    """Wait for the bill to arrive in a viewer the page can be asked for.

    His second failure file showed a dialog and an iframe, and the page
    was read once, straight after the popup gave up, with no wait of its
    own. Whether a viewer in a dialog has its source by then is a guess,
    so this makes three of them and the run says which one it took (#33).

    Ready means a viewer pointing somewhere it did not point before the
    press. The page's own address is not counted, because a hash change
    straight after the press read as the bill arriving seconds before it
    did, which would have taught the next round that no wait was needed.
    A frame the history always carried is not counted either."""
    try:
        viewers = int(page.evaluate(
            "(s) => document.querySelectorAll(s).length", VIEWER_ELEMENTS) or 0)
    except Exception:
        viewers = 0
    return ready(page,
                 [count_reaches(VIEWER_ELEMENTS, viewers + 1, within_ms=6000),
                  network_idle(within_ms=8000),
                  count_settles(VIEWER_ELEMENTS, quiet_ms=1500)],
                 invariant=new_source(VIEWER_ELEMENTS, before),
                 budget_ms=15000, journal=_journal, name="bill viewer")


# A PDF written out as base64 starts with these characters, "%PDF-".
_B64_PDF = "JVBERi0"
_AURA_PATH = "/sfsites/aura"


def _pdf_from_value(value, depth: int = 0) -> Optional[bytes]:
    """A PDF carried as base64 text anywhere in a decoded answer, or None.

    Bounded in depth and only ever decodes a string that already starts
    the way a base64 PDF starts, so a large answer costs a walk and not a
    decode of everything in it.

    An Apex method on PG&E answers with a string, and a string can be
    JSON written out, a file name and the base64 inside it. That string
    does not start the way a PDF does, so it was passed over. One that
    opens like JSON is read as JSON and walked like the rest (#33, review
    of round eight)."""
    if depth > 8:
        return None
    if isinstance(value, str):
        text = value.strip()
        if text[:1] in ("{", "[") and len(text) > 200:
            try:
                import json as _json
                inner = _json.loads(text)
            except Exception:
                return None
            return _pdf_from_value(inner, depth + 1)
        if text.startswith("data:application/pdf;base64,"):
            text = text.split(",", 1)[1]
        if text.startswith(_B64_PDF) and len(text) > 200:
            try:
                data = base64.b64decode(text, validate=False)
            except Exception:
                return None
            return data if data[:5] == b"%PDF-" else None
        return None
    if isinstance(value, dict):
        items = value.values()
    elif isinstance(value, list):
        items = value
    else:
        return None
    for item in items:
        found = _pdf_from_value(item, depth + 1)
        if found:
            return found
    return None


def _pdf_in_aura(res) -> Optional[bytes]:
    """The bill, if it came back inside Salesforce's own answer.

    PG&E's history is a Salesforce Lightning site, and pressing View Bill
    PDF runs a server action whose answer comes back through /sfsites/aura
    as JSON. His two failure files showed no request for a PDF anywhere,
    and Apex actions answering with a text value of seven to fourteen
    thousand characters, which is the size of a small PDF written out as
    base64. A Lightning page often hands a generated file back exactly
    that way and builds the viewer from it, which is why nothing that
    looked for a PDF by its content type ever saw one (#33). Read only on
    PG&E's own host, and only a string that decodes to a PDF counts.

    That reading of his files was wrong. Round eight showed nothing had
    ever been pressed, and those answers arrive in the same order while
    the history loads, so they are the page's own data and not a bill.
    The listener stays, since it costs a walk of an answer and is one of
    the ways a Lightning page hands a file back, but nothing yet shows
    PG&E uses it."""
    try:
        url = res.url or ""
        if _AURA_PATH not in url or not is_safe_url(url):
            return None
        if "json" not in (res.headers.get("content-type") or "").lower():
            return None
        # An aura answer can open with a guard like while(1); ahead of
        # the JSON, so it is read from the first brace.
        text = res.text() or ""
        start = text.find("{")
        if start < 0:
            return None
        import json as _json
        body = _json.loads(text[start:])
    except Exception:
        return None
    actions = body.get("actions") if isinstance(body, dict) else None
    for action in actions or ():
        if isinstance(action, dict) and action.get("state") == "SUCCESS":
            found = _pdf_from_value(action.get("returnValue"))
            if found:
                return found
    return None


def _press_once(page, link, arrived, seconds: float = 6.0, said: Optional[dict] = None):
    """Press View Bill PDF once, and wait for a tab or anything else.

    It used to press, wait six seconds for a tab, and on no tab press
    again. No tab is not a failed click. A bill that opens in a dialog,
    or a site that is slow, opens no tab, and the second press opened a
    second dialog, which is what his failure file showed (#33). A press
    on somebody's account is not something to repeat on a guess.

    So the tab is listened for before the press, which catches a late
    one as well as a prompt one, and the element's own click is tried
    only when the first press raised, which is the one case where it
    did not happen. arrived() says whether a download or a response
    came instead, so the wait ends as soon as anything does.

    The press is never forced. A forced click goes to whatever sits on
    top at the link's position, and a review before release showed a
    dialog over the row taking it, a button reading Enroll that no guard
    had looked at. An ordinary click lands only on the link, and when
    something covers it the link's own click is used, which reaches the
    approved element and no other (#33, round eight).

    Playwright's click can also raise after the click arrived, when the
    press starts a slow page load and the click waits on it. The link's
    own click after that would be a second press. So the link is asked,
    before the press, to note a click reaching it, and the own click runs
    only when the link says for certain that none did. When the link
    cannot be asked at all, nothing is pressed again (second review of
    round eight).

    `said`, when given, records whether the press landed, whether the
    link's own click was the one that did it, and whether the click
    raised after it had landed, for the journal."""
    popups = []
    heard = []
    if said is None:
        said = {}
    said.update(landed=False, own_click=False, late_error=False)
    word = "paperpull heard press %d" % next(_PRESS_COUNT)

    # Functions of their own, since Playwright cannot wrap a list's
    # append as a listener.
    def heard_tab(tab):
        popups.append(tab)

    def heard_word(msg):
        try:
            if msg.text == word:
                heard.append(True)
        except Exception:
            pass

    page.on("popup", heard_tab)
    page.on("console", heard_word)
    try:
        try:
            listening = bool(link.evaluate(_HEAR_PRESS_JS, word))
        except Exception:
            listening = False
        try:
            link.click(timeout=4000)
            said["landed"] = True
        except Exception as e:
            # The error names whatever covered the link, and that is page
            # text, so only its kind is said.
            reached = _press_reached(link, heard) if listening else None
            if reached:
                said["landed"] = said["late_error"] = True
                log.info("the press reached the link and then raised (%s), "
                         "so it is not pressed again", type(e).__name__)
            elif reached is False:
                log.info("the press did not land on the link (%s), so the link's own click",
                         type(e).__name__)
                try:
                    link.evaluate("el => el.click()")
                    said["landed"] = said["own_click"] = True
                except Exception as e2:
                    log.info("the link's own click did not land either (%s)", type(e2).__name__)
                    return None
            else:
                log.info("the press raised (%s) and the link could not say whether it "
                         "arrived, so it is not pressed again", type(e).__name__)
                return None
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            try:
                if popups or arrived():
                    break
            except Exception:
                pass
            page.wait_for_timeout(300)
        return popups[0] if popups else None
    finally:
        for event, fn in (("popup", heard_tab), ("console", heard_word)):
            try:
                page.remove_listener(event, fn)
            except Exception:
                pass


_PRESS_COUNT = itertools.count(1)

# Set on the link before the press. The flag is read back when the click
# raises, and the console line is heard even when the page has already
# started to leave, which is when the flag can no longer be read.
_HEAR_PRESS_JS = r"""(el, word) => {
  el.__paperpullPressed = false;
  el.addEventListener('click', () => {
    el.__paperpullPressed = true;
    try { console.debug(word); } catch (e) {}
  }, {capture: true, once: true});
  return true;
}"""


def _press_reached(link, heard) -> Optional[bool]:
    """Whether the press reached the link. True or False when the link can
    say, None when it cannot be asked."""
    if heard:
        return True
    try:
        return bool(link.evaluate("el => el.__paperpullPressed === true"))
    except Exception:
        return None


def download_bill(page, doc: dict, out_path: Path, config: dict) -> bool:
    """Download a bill PDF for specified doc dictionary handling downloads, popups, fetches, and network responses."""
    # The tabs that were open before the press, set just before it.
    existing_pages = None
    try:
        idx = doc.get("row_index", -1)
        target_page = int(doc.get("page_number", 1))
        link = None
        want_date = doc.get("date_text") or doc.get("date") or ""

        # The row is found on the page discovery saw it on, by its date,
        # and when it is not there (the page number was wrong, a bill
        # posted since and everything moved down a page) every page of the
        # history is walked until the date turns up.
        row = None
        pages = get_pagination_pages(page)
        order = [target_page] + [p for p in pages if p != target_page]
        for p_num in order:
            if p_num != (_current_page(page) or pages[0]):
                if not goto_page_number(page, p_num):
                    continue
            row = _row_for_date(page, want_date, idx if p_num == target_page else -1)
            if row is not None:
                if p_num != target_page:
                    log.info("bill %s is on page %d now, not %d", want_date, p_num, target_page)
                target_page = p_num
                break
        in_row, on_page = {}, {}
        if row is not None:
            link = pick_document_control(row_controls(row), in_row, row=row)
            if not link:
                print("  [site] the row for %s hands over no PDF control: %s" % (want_date, _describe_row(row)))

        # The page wide look, for a bill whose row was not found where the
        # rows are looked for. Every control on the page that could be a
        # bill's PDF leads to the row it sits in, and _bill_rows_page_wide
        # keeps a row only when it is a bill row with this bill's date,
        # one that reads View Bill PDF, the test the usual look and
        # discovery use. When exactly one row is kept and it holds one
        # bill, it is walked and judged exactly as a row found the usual
        # way would be.
        #
        # Only when no row was found. When the bill's row was found, a look
        # across the page can only reach some other row. It used to run
        # when the found row handed over nothing, and it held the row it
        # reached to the date alone, so a payment made on the bill's day,
        # with a link to its receipt that passed the guard, had the receipt
        # saved as the bill. A safety review of round eight's repair did
        # that in a real browser. The look already never ran for a found
        # row that refused something, since it once approved a link its row
        # had refused for a Pay box around it (third review of round eight).
        #
        # Only one row, holding one bill. When more than one row on the
        # page reads View Bill PDF and carries the date, nothing says which
        # is this bill, so neither is pressed. A row that reads View Bill
        # PDF more than once holds other bills too, and a control in it can
        # be another bill's, so it is refused as well. And a bill with no
        # date is never looked for this way, since any bill's link would do
        # for it.
        looked = False
        page_rows = page_crowded = 0
        if not link and want_date and row is None:
            looked = True
            reached, page_crowded = _bill_rows_page_wide(page, want_date)
            page_rows = len(reached)
            if page_rows > 1:
                _trace("refused more than one bill row with the date", rows=page_rows)
            elif page_crowded:
                _trace("refused a row that holds more than one bill")
            elif page_rows == 1:
                link = pick_document_control(row_controls(reached[0]), on_page, row=reached[0])

        if not link:
            # Numbers only, so the next file tells a row with nothing in
            # it from a row whose control was there and refused. A control
            # can be counted twice, once by the walk and once by the query.
            # The nearby counts are the refused ones that were refused for
            # something around them or inside them, not for their own words.
            # page_looked says whether the page wide look ran at all,
            # page_rows how many bill rows with the date it reached,
            # page_crowded how many of those read View Bill PDF more than
            # once, and the page counts are the one row it judged.
            _trace("found no pdf control", row_found=row is not None,
                   row_candidates=in_row.get("seen", 0),
                   row_refused=in_row.get("refused", 0),
                   row_unlabeled=in_row.get("unlabeled", 0),
                   row_nearby=in_row.get("nearby", 0),
                   page_looked=looked,
                   page_rows=page_rows,
                   page_crowded=page_crowded,
                   page_links=on_page.get("seen", 0),
                   page_refused=on_page.get("refused", 0),
                   page_nearby=on_page.get("nearby", 0))
            print(f"  [site] No download link found for doc index {idx} on page {target_page}")
            return False

        # Said in this file's words. The label is page text, and this line
        # is pasted into a public issue.
        named = "View Bill PDF" if _VIEW_PDF_RE.match(control_label(link)) else "a bill control"
        print(f"  [site] Found {named} for index {idx} (page {target_page}). Preparing capture...")

        # Direct href check if present
        try:
            href = link.get_attribute("href") or ""
            if href and ("http" in href or ".pdf" in href):
                target_url = href if href.startswith("http") else (BASE.rstrip("/") + "/" + href.lstrip("/"))
                if is_safe_url(target_url):
                    res = page.request.get(target_url)
                    if res.ok and res.body()[:5] == b"%PDF-":
                        out_path.write_bytes(res.body())
                        print("  [site] Successfully fetched PDF via direct href!")
                        return True
        except Exception as e_href:
            print(f"  [site] Direct href fetch note: {type(e_href).__name__}")

        existing_pages = set(page.context.pages)
        history_url = page.url or ""
        before_click = _viewers_now(page)
        # Every address the page itself could be asked for, as it stands
        # now, so nothing an earlier bill left open is taken for this one.
        before_all = _addresses_before(page)
        captured_download = [None]
        captured_response_bytes = [None]
        # A new tab's first answer comes before the tab can be named, so
        # it waits here, by address, until the tab this press opened is
        # known and is standing at that address.
        first_answers = {}

        def handle_download(dl):
            try:
                if dl.url in _ADDRESSES_TAKEN:
                    log.info("a download an earlier bill already had was left alone")
                    return
            except Exception:
                pass
            captured_download[0] = dl

        def handle_response(res):
            try:
                whose = _whose_answer(res, page, existing_pages)
                if whose == "elsewhere":
                    return
                ct = (res.headers.get("content-type") or "").lower()
                if "application/pdf" in ct or ".pdf" in res.url.lower():
                    b = res.body()
                    if b and b[:5] == b"%PDF-":
                        if whose == "ours":
                            captured_response_bytes[0] = b
                        else:
                            first_answers[res.url] = b
                elif captured_response_bytes[0] is None and whose == "ours":
                    b = _pdf_in_aura(res)
                    if b:
                        captured_response_bytes[0] = b
            except Exception:
                pass

        page.on("download", handle_download)
        # On the context, not on this page. A PDF that loads in the tab
        # PG&E opens never reaches a listener on the tab it was opened
        # from, so the answer that carried the bill went unheard.
        page.context.on("response", handle_response)
        listening = [True]

        def stop_listening():
            if not listening[0]:
                return
            listening[0] = False
            try:
                page.remove_listener("download", handle_download)
            except Exception:
                pass
            try:
                page.context.remove_listener("response", handle_response)
            except Exception:
                pass

        popup = None
        blob_url = None
        press = {}
        tab_moved = moved = False
        from_page = None
        try:
            try:
                link.scroll_into_view_if_needed(timeout=3000)
            except Exception:
                pass
            print("  [site] Clicking 'View Bill PDF' link...")
            popup = _press_once(page, link, lambda: bool(
                captured_download[0] or captured_response_bytes[0]), said=press)

            blob_url = None
            if popup:
                try:
                    popup.wait_for_url(lambda u: u.startswith("blob:") or ("http" in u and ".pdf" in u), timeout=15000)
                    blob_url = popup.url
                except Exception as e_wait:
                    print(f"  [site] Popup wait note: {type(e_wait).__name__}")
                    if popup.url and popup.url != "about:blank":
                        blob_url = popup.url
                # The tab's first answer, held by address until now, is
                # taken once the tab this press opened stands at it.
                if blob_url and not blob_url.startswith("blob:"):
                    t_start = time.monotonic()
                    while (captured_response_bytes[0] is None and blob_url not in first_answers
                           and time.monotonic() - t_start < 3.0):
                        page.wait_for_timeout(300)
                    if captured_response_bytes[0] is None and blob_url in first_answers:
                        captured_response_bytes[0] = first_answers[blob_url]

            # Wait briefly if direct download or response happened instead
            # Waited out through the browser's own timer. The download and
            # the response are both set by listeners, and Playwright only
            # hands a listener its event while this thread is inside a
            # Playwright call, so a time.sleep here could never see either
            # arrive and spun its five seconds for nothing.
            if not blob_url:
                t_start = time.monotonic()
                while time.monotonic() - t_start < 5.0:
                    if captured_download[0] or captured_response_bytes[0]:
                        break
                    page.wait_for_timeout(300)
            tab_moved = (page.url or "") != history_url

            # The control need not open a tab at all. It can move THIS tab
            # to PG&E's viewer, and then there is no popup, no download and
            # no response this tab was listening for (#33). So a tab that
            # moved is read where it stands, through the session. It need
            # not move at all either. A bill can open in a dialog, the shape
            # Costco's receipt has, so the page is asked what it is holding
            # whether or not it went anywhere.
            #
            # The ears stay open while the viewer is waited for. They used
            # to close first, so a bill slower than the press window was
            # lost, and a very late one could be heard in the next bill's
            # window and saved under its name. Now it is heard while its
            # own bill is still open (second review of round eight).
            if not (captured_response_bytes[0] or captured_download[0] or blob_url):
                moved = tab_moved
                if moved:
                    print("  [site] the tab moved to %s rather than opening one" % _url_shape(page.url))
                else:
                    print("  [site] the control opened nothing this was watching, "
                          "so the page itself is asked what it is holding")
                _wait_for_viewer(page, before_click)
                stop_listening()
                if not (captured_response_bytes[0] or captured_download[0]):
                    from_page = _pdf_from_here(page, before_all)
                    if from_page:
                        print("  [site] the bill came from the page itself")
        except Exception as e_click:
            print(f"  [site] Link click warning: {type(e_click).__name__}")
        finally:
            stop_listening()
        _trace("pressed the pdf control", landed=bool(press.get("landed")),
               own_click=bool(press.get("own_click")),
               late_error=bool(press.get("late_error")),
               tab=popup is not None,
               blob_tab=(blob_url or "").startswith("blob:"),
               download=captured_download[0] is not None,
               answer=captured_response_bytes[0] is not None,
               tab_moved=tab_moved,
               from_page=from_page is not None)
        if from_page:
            captured_response_bytes[0] = from_page
        # This bill's blob, whichever way it is taken below, is never a
        # later bill's download.
        _remember_blob(blob_url or "")

        # and put the tab back on the history when it left, or every bill
        # after this is looked for on a page that does not hold it
        if moved:
            try:
                page.goto(history_url, wait_until="domcontentloaded", timeout=45000)
                wait_for_rows(page, seconds=20)
            except Exception as e_back:
                log.info("could not return to the history: %s", type(e_back).__name__)

        if captured_response_bytes[0]:
            print("  [site] Captured PDF from network response!")
            out_path.write_bytes(captured_response_bytes[0])
        elif captured_download[0]:
            print("  [site] Download event captured!")
            try:
                _remember_blob(captured_download[0].url or "")
            except Exception:
                pass
            captured_download[0].save_as(str(out_path))
        elif blob_url and blob_url.startswith("blob:"):
            # The new tab opened at a blob, read by the page that made it,
            # and when the page's policy refuses that read, saved as a
            # download from the page that made it, the contributor's way.
            # The tab itself is asked only after both have failed.
            body, by_download = _take_blob((page, popup), blob_url)
            if body:
                out_path.write_bytes(body)
                print("  [site] the bill came from the new tab")
            else:
                print("  [site] the new tab held no bill this could read")
            _trace("read the new tab", pge_origin=_blob_on_pge(blob_url),
                   bill=bool(body), by_download=by_download)
        elif blob_url and is_safe_url(blob_url):
            # A new tab at a PDF on PG&E. It is asked for through the
            # session first, which clicks nothing and moves no tab. The
            # contributor's download link is kept for an address on the
            # history's own origin only, since on any other origin the
            # browser ignores the download mark and the history tab itself
            # went to the PDF (third review of round eight).
            print(f"  [site] Statement ready at {_url_shape(blob_url)}. Capturing it...")
            body = _pdf_at(page, blob_url)
            by_download = False
            if body is None and _same_origin(history_url, blob_url):
                body = _https_by_download(page, blob_url)
                by_download = body is not None
            if body:
                out_path.write_bytes(body)
                print("  [site] Statement PDF saved!")
            else:
                print("  [site] the new tab held no bill this could read")
            _trace("read the new tab", pge_origin=True, bill=bool(body),
                   by_download=by_download)

        if out_path.exists() and (out_path.stat().st_size == 0 or out_path.read_bytes()[:5] != b"%PDF-"):
            out_path.unlink()
            return False
        return out_path.exists()
    except Exception as e:
        print(f"  [site] Download bill exception: {type(e).__name__}")
        if out_path.exists() and out_path.stat().st_size == 0:
            out_path.unlink()
        return False
    finally:
        # The tabs opened while the bill was taken are closed however it
        # ended. This ran at the end of the capture, so anything that raised
        # on the way skipped it and the tab stayed open into the next bill
        # (review of round eight's repair). Nothing before the press opens
        # a tab, and a bill that stops before it has nothing to close.
        if existing_pages is not None:
            _close_new_tabs(page, existing_pages)


def _close_new_tabs(page, before) -> None:
    """Close every tab that was not open before the press. The history and
    every tab that was already open are left as they were."""
    try:
        tabs = list(page.context.pages)
    except Exception:
        return
    for tab in tabs:
        if tab is page or any(tab is was for was in before):
            continue
        try:
            if not tab.is_closed():
                tab.close()
        except Exception:
            pass
