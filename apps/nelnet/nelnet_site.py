"""ALL nelnet.studentaid.gov selectors, URLs, and page behavior live here.

When Nelnet changes its servicing site, repair this file only.

STATUS: mapped and run against a signed-in account on 2026-10-07. The
two ways a document arrives:

  * A statement or notice: pressing the row's Download button makes the
    page fetch the PDF from mmaapi.nelnet.studentaid.gov
    (/api/1/statements/pdf/<id>) and the browser then fires an ordinary
    download event, `statement_YYYYMMDD.pdf`. `_catch_pdf` takes it.
  * The 1098-E is not a file. Its button calls window.print(), which would
    open the browser's print dialog and wait for a person, so
    `_print_tax_form` holds the page's print back for the press and
    prints the live page to PDF itself. The button pressed is the one for
    the form's own tax year (`_tax_forms`), or none.

Nelnet services federal student loans for the Department of Education at
nelnet.studentaid.gov. The site is an Angular app on a cookie session, so
`page.goto` by address keeps you signed in. Its data comes from a second
host, mmaapi.nelnet.studentaid.gov, which the host allowlist covers as a
subdomain. A call to that host from inside the page with nothing but the
page's cookies fails, so nothing here asks it directly: the rows are read
from the page and each document is taken by pressing its own control.

  * Inbox & Statements (/documents/inbox-statements) is one list of
    billing statements and eCorrespondence, ten rows a page, paged inside
    the browser. Each row has a "View document in new tab" link and a
    "Download document to your device" button, both carrying the
    document's id in `data-cy`. Only the download button is pressed. A
    page of the list that cannot be reached stops the listing
    (ListStopped) rather than end it.
  * Tax Info (/documents/tax-info) shows the 1098-E.
  * Loan Summary and Payment Schedule are rendered pages with a Print
    button and no file. Forms only links out to studentaid.gov. None of
    those three is read.

SAFETY (this is a loan account that can take a payment):
  This module is strictly READ-ONLY. It opens the statements area, reads
  the list, pages through it, and saves the PDFs the site already
  generated. It must NEVER activate any control that makes or schedules a
  payment, enrolls in auto debit, asks for a deferment, forbearance or a
  new repayment plan, applies for anything, or edits any setting.
  FORBIDDEN_CONTROL_RE is the guard. A control must ALSO look like a
  document action (SAFE_DOC_CONTROL_RE) before it may be clicked. The guard
  reads the control's own wording and never the title of the document it
  belongs to, because a document called "Repayment Plan Confirmation" is
  not a button that confirms one. There is no code here that submits a
  form or confirms a dialog.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from paperpull_core import receipt_pdf
from paperpull_core.controls import SETTINGS_CONTROL_RE, AUTH_CONTROL_RE

# Everything on its way into a diagnostic file goes through here. It
# lives in core because seventeen apps each had their own copy and
# they drifted into three different versions.
from paperpull_core.redact import redact, set_private_words  # noqa: F401
from paperpull_core.urls import is_safe_url as _host_allows
from paperpull_core.api_census import shape_of as _shape
from paperpull_core.dates import last_day as _last_day
# re-exported: this app's docs module calls it as site.set_download_dir
from paperpull_core.capture import set_download_dir  # noqa: F401
from paperpull_core.capture import snapshot as _snapshot
from paperpull_core.capture import take_download as _take_download
from paperpull_core.capture import is_document as _is_document
from paperpull_core.capture import clear_copies as _clear_copies
from paperpull_core.capture import ask_again as _ask_again
from paperpull_core.capture import RequestsSince as _RequestsSince
from paperpull_core.capture import take_new_pdf as _take_new_pdf
from paperpull_core.capture import take_new_tab as _core_take_new_tab
from paperpull_core.capture import take_same_tab as _core_take_same_tab
from paperpull_core.controls import control_texts as _control_texts
from paperpull_core.controls import second_step as _core_second_step
from paperpull_core.controls import controls_named as _controls_named
from paperpull_core.controls import escape_for_locator
from paperpull_core.dates import checked as _checked_date
from paperpull_core.dates import full_year as _full_year

log = logging.getLogger("nelnet_docs.site")

BASE = "https://nelnet.studentaid.gov"
INBOX_URL = f"{BASE}/documents/inbox-statements"
TAX_URL = f"{BASE}/documents/tax-info"
BILLING_CANDIDATES = [INBOX_URL]
BILLING_URL = INBOX_URL
URLS = {
    "home": f"{BASE}/",
    "login": f"{BASE}/",
    "documents": INBOX_URL,
    "statements": INBOX_URL,
    "tax": TAX_URL,
}

# Words in the address of a sign-in or verification page. Nelnet signs in
# on its own host, auth.nelnet.studentaid.gov. The pages also keep a
# hidden session-check frame there, which is why the marker is matched
# against the tab's own address and not against its frames.
LOGIN_URL_MARKERS = ["/login", "/signin", "/sign-in", "/mfa",
                     "/verification", "/challenge", "/oauth", "/sso",
                     "//auth.nelnet.studentaid.gov"]

# ---------------------------------------------------------------------------
# HARD SAFETY GUARD. Tuned for a loan servicer. Never pay, never apply,
# never ask for anything, never change a setting. Every verb stem is
# anchored on both sides: "Repayment" is not "payment" and "Credit" is not
# "edit".
# ---------------------------------------------------------------------------
FORBIDDEN_CONTROL_RE = re.compile(
    r"(\bpay\b|\bpaying\b|\bpayments?\b|make\s+a\s+payment|\bschedul(e|es|ed|ing)\b|"
    r"auto\s*-?\s*(pay|debit)|recurring|one[-\s]?time|\bbank\b|routing|"
    r"account\s+number|\bdebit\b|\bcard\b|"
    r"\bhardship\b|\bdeferment\b|\bdeferral\b|\bforbearance\b|modification|forgiveness|"
    r"\bapply\b|\bapplication\b|\brequest(s|ed|ing)?\b|\bsubmit|\bupload|"
    r"\benroll|\bunenroll|sign\s+up|paperless|"
    r"\benable\b|\bdisable\b|\bchang(e|es|ed|ing)\b|\bedit(s|ed|ing)?\b|"
    r"\bupdat(e|es|ed|ing)\b|\bmodify\b|\bmanage\b|"
    r"set\s+up|\bdelete\b|\bremove\b|\bcancel|\bwithdraw|"
    r"password|passcode|username|\bprofile\b|\bsettings?\b|preferences|"
    r"contact\s+info|\baddress\b|"
    r"\bconfirm\b|\bagree\b|\baccept\b|\bauthori[sz]e|\bcertif|\brecertif|"
    r"\bchat\b|contact\s+us|consolidat|"
    r"payoff|pay\s+off|dispute|appeal)", re.I)

SAFE_DOC_CONTROL_RE = re.compile(
    r"(download|view|open|print|\bpdf\b|statement|document|\bletter\b|notice|"
    r"1098|1099|tax\s+(form|document|info)|history|"
    r"see\s+(more|all|older)|show\s+(more|all|older)|load\s+more|"
    r"(next|previous|first|last)\s+page|go\s+to\s+(first|last)\s+page)", re.I)

# A control that fetches one document. On the inbox list that is the row's
# "Download document with subject ..." button. On the tax page it is the
# form's own control, whose name carries the form number.
BILL_CONTROL_RE = re.compile(r"(^\s*download\s+document\b|\b1098(-?e)?\b)", re.I)

# Where the rows' wording ends and the document's own subject begins.
_SUBJECT_SPLIT_RE = re.compile(r"\s+with\s+subject\s+", re.I)

SECURITY_CHALLENGE_MARKERS = [
    "enter the code", "verification code", "6-digit", "two-factor",
    "two-step", "authenticator", "confirm your identity", "verify your identity",
    "we sent a code", "device approval", "approve this login", "unusual",
    "are you a robot", "captcha", "let's verify", "check your email",
    "check your phone", "your session has expired", "log back in",
    "access denied",
]

RATE_LIMIT_MARKERS = [
    "too many requests", "rate limit", "try again later",
    "temporarily unavailable", "http error 429", "unusual traffic",
]

# ---------------------------------------------------------------------------
# Fallback selectors (used by --diagnose only)
# ---------------------------------------------------------------------------
FALLBACK = {
    "doc_row": "main table tr",
    "doc_link": "a[data-cy^='document-view-']",
    "download_control": "button[data-cy^='document-download-']",
    "page_ready": "main table, main",
    "next_page": "button[aria-label='Next Page']",
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


def _action_of(name: str) -> str:
    """A control's own wording with the title of the document it belongs
    to taken off. "Download document with subject Repayment Plan
    Confirmation" is a download button, and the guard reads the part that
    says what pressing it does."""
    return _SUBJECT_SPLIT_RE.split(name or "", maxsplit=1)[0].strip()


def is_safe_control(name: str) -> bool:
    name = _action_of(name)
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
    """Close a cookie banner, a survey prompt or a notice overlay, the
    things that sit over portal pages and intercept clicks. Escape first, then
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


_LIST_BUTTON = 'main table button[data-cy^="document-download-"]'


def _wait_for_list(page, timeout_ms: int = 30000) -> bool:
    """The inbox list is filled in after the page loads, so its first
    download button is what says it is ready."""
    try:
        page.wait_for_selector(_LIST_BUTTON, timeout=timeout_ms)
        return True
    except Exception:
        return False


def goto_documents(page) -> bool:
    """Open Inbox & Statements by its address. The session is a cookie, so
    the address works, and a tab already there is left as it is."""
    dismiss_overlay(page)
    here = page.url or ""
    if here.startswith(INBOX_URL) and is_safe_url(here) and not looks_signed_out(page) \
            and _wait_for_list(page, 5000):
        return True
    try:
        page.goto(INBOX_URL, wait_until="domcontentloaded", timeout=60000)
    except Exception as e:
        log.info("goto %s failed: %s", INBOX_URL, e)
        return False
    dismiss_overlay(page)
    if looks_signed_out(page):
        return False
    return _wait_for_list(page)


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


# One entry per row of the inbox list that has a download button, read
# from the page without pressing anything. `subject` is the document's own
# name as the View link shows it, with the screen-reader words and the icon
# taken off. `label` is the download button's aria-label, "Download
# document with subject ...". `cy` is the button's own `data-cy`, the only
# thing that tells two rows with one subject apart.
_LIST_ROWS_JS = r"""() => {
  const out = [];
  for (const tr of document.querySelectorAll('main table tr')) {
    const btn = tr.querySelector('button[data-cy^="document-download-"]');
    if (!btn) continue;
    const link = tr.querySelector('a[data-cy^="document-view-"]');
    let subject = '';
    if (link) {
      const c = link.cloneNode(true);
      c.querySelectorAll('.sr-only, u-icon, svg').forEach(n => n.remove());
      subject = (c.textContent || '').replace(/\s+/g, ' ').trim();
    }
    const tds = tr.querySelectorAll('td');
    out.push({
      date: ((tds[0] && tds[0].textContent) || '').replace(/\s+/g, ' ').trim(),
      subject: subject,
      label: btn.getAttribute('aria-label') || '',
      cy: btn.getAttribute('data-cy') || ''
    });
  }
  return out;
}"""

_NEXT_PAGE = 'button[aria-label="Next Page"]'
_FIRST_PAGE = 'button[aria-label="Go to first page"]'
_MAX_LIST_PAGES = 60
# How long a pressed pager button has to change the rows. The list is paged
# inside the browser, so it changes at once when it changes at all.
_PAGER_WAITS = 34      # times 300 ms, about ten seconds
_CY_RE = re.compile(r"^document-download-[A-Za-z0-9-]+$")


class ListStopped(Exception):
    """The list has a page this could not reach, so what was read is not all
    of it. `docs` holds what was read before it stopped. A reader that took
    such a page for the last one ended the listing with rows still unread,
    and discovery then called the list whole (paperpull_core.listing)."""

    def __init__(self, why: str, docs=None):
        super().__init__(why)
        self.docs = list(docs or [])


def _read_rows(page) -> list:
    try:
        return page.evaluate(_LIST_ROWS_JS) or []
    except Exception:
        return []


def _subject_of(row: dict) -> str:
    subject = re.sub(r"\s+", " ", row.get("subject") or "").strip()
    if subject:
        return subject
    parts = _SUBJECT_SPLIT_RE.split(row.get("label") or "", maxsplit=1)
    return parts[1].strip() if len(parts) == 2 else ""


def _press_pager(page, selector: str) -> bool:
    """Press one of the list's pager buttons once. False when there is no
    page to go to, the button gone or disabled. Its own label goes through
    the guard first. The list is paged inside the browser, so this asks the
    site for nothing new.

    A page that is there and could not be reached raises ListStopped, the
    button refused by the guard, or pressed with the rows still the same
    after about ten seconds. Both used to read as the last page, so a slow
    page ended the listing with pages unread."""
    try:
        btn = page.locator(selector).first
        if btn.count() == 0 or btn.get_attribute("aria-disabled") == "true" \
                or btn.get_attribute("disabled") is not None:
            return False
        label = btn.get_attribute("aria-label") or ""
    except Exception as e:
        raise ListStopped("its pager could not be read (%s)" % type(e).__name__)
    if not is_safe_control(label):
        raise ListStopped("the guard refused its pager button")
    before = _read_rows(page)
    try:
        btn.click(timeout=5000)
    except Exception as e:
        raise ListStopped("its pager button could not be pressed (%s)" % type(e).__name__)
    for _ in range(_PAGER_WAITS):
        page.wait_for_timeout(300)
        if _read_rows(page) != before:
            return True
    raise ListStopped("the rows stayed the same after its pager button was pressed")


def _to_first_page(page) -> None:
    for _ in range(_MAX_LIST_PAGES):
        if not _press_pager(page, _FIRST_PAGE):
            return


def _row_is_tax(subject: str) -> bool:
    return bool(re.search(r"\b1098\b|\btax\b", subject, re.I))


def _collect_inbox(page) -> List[RawDoc]:
    """Every row of the inbox list, from its first page to its last. Raises
    ListStopped, holding the rows read so far, when a page could not be
    reached or the list runs past _MAX_LIST_PAGES."""
    docs: List[RawDoc] = []
    seen = set()
    try:
        _to_first_page(page)
        for _ in range(_MAX_LIST_PAGES):
            for r in _read_rows(page):
                subject = _subject_of(r)
                iso = parse_date(r.get("date") or "")
                if not iso or not subject or not is_safe_control(r.get("label") or ""):
                    continue
                key = (iso, subject.lower())
                if key in seen:
                    continue
                seen.add(key)
                docs.append(RawDoc(title=subject, date_text=iso,
                                   text=f"Nelnet {subject}", row_index=len(docs),
                                   kind=("tax" if _row_is_tax(subject)
                                         else "statement" if re.search(r"\bstatement\b", subject, re.I)
                                         else "letter")))
            if not _press_pager(page, _NEXT_PAGE):
                break
        else:
            raise ListStopped("it runs past %d pages" % _MAX_LIST_PAGES)
    except ListStopped as stop:
        stop.docs = docs
        raise
    return docs


_TAX_YEAR_RE = re.compile(r"tax\s+year\s+((?:19|20)\d{2})", re.I)


def _goto_tax(page) -> bool:
    try:
        page.goto(TAX_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)
    except Exception as e:
        log.info("goto %s failed: %s", TAX_URL, e)
        return False
    dismiss_overlay(page)
    return not looks_signed_out(page)


_YEAR_IN_LABEL_RE = re.compile(r"\b((?:19|20)\d{2})\b")
# The title a 1098-E from Tax Info is listed under. A document whose title is
# not exactly this came from the inbox, and is taken from its own row there,
# whatever its subject says.
_TAX_TITLE_RE = re.compile(r"^1098-E Tax Year ((?:19|20)\d{2})$")


def _tax_forms(page) -> dict:
    """Each 1098-E control on Tax Info by the tax year it is for, as
    {year: (control, label)}, the first for each year as the page lists
    them. A control's year is the one its own label names ("2024 1098-E
    Form"), which has to be a tax year the page shows, or, when its label
    names none, the one tax year the page shows. A control whose year
    cannot be told that way is left out. The control pressed for a year is
    then always one for that year. It used to be the first 1098-E control
    whatever year was asked for, so a form for an older year, asked for
    again, was the page's current form saved under the older year."""
    try:
        body = page.locator("main").inner_text(timeout=8000)
    except Exception:
        return {}
    shown = set(_TAX_YEAR_RE.findall(body))
    if not shown:
        return {}
    found = {}
    ctrls = _bill_controls(page)
    for i in range(ctrls.count()):
        el = ctrls.nth(i)
        try:
            label = (el.get_attribute("aria-label") or el.inner_text(timeout=800) or "").strip()
        except Exception:
            continue
        if not (is_safe_control(label) and re.search(r"\b1098\b", label, re.I)):
            continue
        named = set(_YEAR_IN_LABEL_RE.findall(label))
        if len(named) > 1:
            continue
        year = named.pop() if named else (next(iter(shown)) if len(shown) == 1 else None)
        if year is None or year not in shown:
            continue
        found.setdefault(year, (el, label))
    return found


def _collect_tax(page) -> List[RawDoc]:
    """The 1098-E on Tax Info for each tax year it can be told for, filed at
    the end of that year."""
    if not _goto_tax(page):
        return []
    return [RawDoc(title=f"1098-E Tax Year {year}", date_text=f"{year}-12-31",
                   text=f"Nelnet 1098-E Tax Year {year}", kind="tax")
            for year in sorted(_tax_forms(page), reverse=True)]


def collect_download_docs(page) -> List[RawDoc]:
    """Every statement and notice on Inbox & Statements, paged through,
    and the 1098-E on Tax Info. Nothing is pressed except the pager. An
    inbox list that stopped partway still has Tax Info read, and then
    raises ListStopped holding everything read."""
    docs: List[RawDoc] = []
    stopped = None
    if goto_documents(page):
        try:
            docs.extend(_collect_inbox(page))
        except ListStopped as stop:
            docs.extend(stop.docs)
            stopped = stop
    docs.extend(_collect_tax(page))
    if stopped is not None:
        stopped.docs = docs
        raise stopped
    return docs


def _print_tax_form(page, el, label: str, out_path: Path,
                    trace: Optional[list] = None) -> bool:
    """Save the 1098-E. The form is not a file: its button calls
    window.print() on the page, and the browser's print dialog would wait
    for a person. So the page's print is held back for the press, which is
    what makes the page lay out the form, and then the live page itself is
    printed to PDF, the way the print dialog would have."""
    receipt_pdf.install_print_suppression(page)
    receipt_pdf.clear_print_snapshot(page)
    try:
        try:
            el.click(timeout=8000)
        except Exception as e:
            if trace is not None:
                trace.append({"note": "click failed", "control": redact(label)[:60],
                              "error": str(e)[:160]})
            return False
        for _ in range(10):
            if receipt_pdf.was_print_called(page):
                break
            page.wait_for_timeout(500)
        else:
            if trace is not None:
                trace.append({"note": "the click did not call print",
                              "control": redact(label)[:60]})
            return False
        if trace is not None:
            trace.append({"note": "printed the page after the press",
                          "control": redact(label)[:60]})
        try:
            receipt_pdf.print_page_to_pdf(page, out_path)
        except Exception as e:
            if trace is not None:
                trace.append({"note": "print to PDF failed", "error": str(e)[:160]})
            return False
        return True
    finally:
        receipt_pdf.restore_print(page)


def _inbox_control(page, iso: str, title: str):
    """The download button of the inbox row dated `iso` whose subject is
    `title`, found by paging from the first page, or (None, "")."""
    want = re.sub(r"\s+", " ", title or "").strip().lower()
    try:
        _to_first_page(page)
        for _ in range(_MAX_LIST_PAGES):
            for r in _read_rows(page):
                if parse_date(r.get("date") or "") != iso:
                    continue
                if want and _subject_of(r).lower() != want:
                    continue
                cy = r.get("cy") or ""
                if _CY_RE.match(cy):
                    return page.locator('button[data-cy="%s"]' % cy).first, r.get("label") or ""
            if not _press_pager(page, _NEXT_PAGE):
                break
    except ListStopped as stop:
        log.info("the inbox list stopped while looking for %s, %s", iso, stop)
    return None, ""


def _tax_control(page, year: str):
    """The 1098-E control for tax year `year`, or (None, "") when Tax Info
    shows none that can be told to be for that year."""
    if not _goto_tax(page):
        return None, ""
    return _tax_forms(page).get(year, (None, ""))


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
        try:
            el.click(timeout=8000)
            if trace is not None:
                trace.append({"note": "clicked", "control": redact(label)[:60]})
        except Exception as e:
            if trace is not None:
                trace.append({"note": "click failed", "control": redact(label)[:60], "error": str(e)[:160]})
            try:
                el.evaluate("el => el.click()")
                if trace is not None:
                    trace.append({"note": "clicked through the DOM instead", "control": redact(label)[:60]})
            except Exception as e2:
                if trace is not None:
                    trace.append({"note": "DOM click failed too", "error": str(e2)[:160]})
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
                  trace: Optional[list] = None) -> bool:
    """Save the document dated `iso_date` whose subject is `title`. The
    row's own download button is pressed, once it has passed the guard, and
    whichever way the site hands the file over is caught, a download event,
    a PDF response, a file in `dl_dir` or a new tab.

    `dl_dir` is where the attached browser saves a download, watched
    after every click."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Only a form listed from Tax Info is taken there, for its own year. An
    # inbox notice whose subject names the 1098-E is a letter of its own,
    # and used to be sent to Tax Info and saved as the year's form.
    tax = _TAX_TITLE_RE.match((title or "").strip())
    if tax:
        el, label = _tax_control(page, tax.group(1))
        if el is None or not is_safe_control(label):
            log.info("no safe 1098-E control for tax year %s", tax.group(1))
            return False
        return _print_tax_form(page, el, label, out_path, trace)
    elif goto_documents(page):
        el, label = _inbox_control(page, iso_date, title)
    else:
        log.info("could not open the statements page for %s", iso_date)
        return False
    if el is None:
        log.info("no document control found for %s", iso_date)
        return False
    if not is_safe_control(label):
        log.info("refusing unsafe control %r for %s", label, iso_date)
        return False
    return _catch_pdf(page, el, label, out_path, trace, dl_dir)


# ---------------------------------------------------------------------------
# Diagnose. A survey a tester can attach to an issue. No screenshot, since a
# loan page shows names, numbers and balances. Digit runs are masked and
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
    r"^\s*(inbox\s*&\s*statements|tax\s+info|statements?|documents)\s*$", re.I)


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
    """What the signed-in loan portal looks like, without downloading
    anything. Records each page, its headings and controls with the
    guard's verdict on each, and every JSON or PDF response studentaid.gov sends
    while the page settles. Then follows, one at a time and back again,
    the few links whose text is a statements or loans word. No screenshot."""
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
ALLOWED_HOSTS = {"nelnet.studentaid.gov"}


def is_safe_url(url: str) -> bool:
    """True only for an https URL on one of this provider's own hosts.

    The check itself lives in the core, so all of them answer the same way.
    This app keeps the hosts, which is the part that really is its own."""
    return _host_allows(url, ALLOWED_HOSTS)
