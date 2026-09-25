"""ALL card.apple.com selectors, URLs, and page behavior live here.

When Apple changes card.apple.com, repair this file only.

STATUS: UNVERIFIED. This app was written without an Apple Card or a
Savings account, from the sign-in address the requester named (#52) and
what Apple says in public about card.apple.com, so that someone who holds
one can test it without writing code. Nothing below has run against the
live signed-in site, and nobody here has seen a signed-in page. On a first
run it is deliberately cautious:

  * --login opens a real Edge or Chrome at card.apple.com, whose sign-in
    (an Apple Account with a code sent to a trusted device) is the user's
    to complete.
  * --record writes down the path the tester takes to one document of
    each kind, which is what this file is waiting on.
  * --diagnose surveys whatever the card, Savings and tax pages turn out
    to be, records their headings, their controls with the guard's
    verdict on each, and the shape of every JSON response, with digit
    runs masked, and takes no screenshot.
  * --discover visits the three sections in turn and reads a date from
    every control that looks like it fetches one document.
  * --pilot tries to save the newest few, by fetching a PDF link the row
    carries from inside the page, or by pressing the row's own control
    once and catching a download event, a PDF response or a new tab.

The guesses that most need confirming are marked GUESS. The biggest are
the addresses of the three sections, how a month is labelled, and where
the 1099-INT lives.

What is public and believed true, still to be confirmed by a Record.
Apple Card statements run for a calendar month, so a statement named by
its month closes on that month's last day. Apple's help pages say a
statement can be downloaded as a PDF from card.apple.com, and that
transactions can also be exported as CSV or OFX, which this app never
wants. Savings is managed from the same Apple Card account and has its
own monthly statements, and a Savings account that earned interest gets a
1099-INT.

SAFETY (this is a credit card and a bank account, both able to move money):
  This module is strictly READ-ONLY. It opens the statement and document
  pages, reads the lists, and saves the PDFs Apple already generated. It
  must NEVER activate any control that pays, schedules a payment,
  transfers, adds money to or withdraws from Savings, moves money between
  the card and Savings, changes where Daily Cash goes, sends Apple Cash,
  disputes a charge, reports a card lost, shows a card number, requests a
  new card or a higher limit, shares the card with family, links a bank
  account, opens or closes anything, or edits any setting.
  FORBIDDEN_CONTROL_RE is the guard. A control must ALSO look like a
  document action (SAFE_DOC_CONTROL_RE) or be one of the few section
  names (SECTION_NAV_RE) before it may be pressed. There is no code here
  that submits a form or confirms a dialog.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import urlsplit

from paperpull_core.controls import SETTINGS_CONTROL_RE, AUTH_CONTROL_RE

# Everything on its way into a diagnostic file goes through here. It
# lives in core because seventeen apps each had their own copy and
# they drifted into three different versions.
from paperpull_core.redact import redact, set_private_words  # noqa: F401
from paperpull_core.urls import is_safe_url as _host_allows
from paperpull_core.api_census import shape_of as _shape
from paperpull_core.dates import last_day as _last_day
# re-exported, since this app's docs module calls it as site.set_download_dir
from paperpull_core.capture import set_download_dir  # noqa: F401
from paperpull_core.capture import snapshot as _snapshot
from paperpull_core.capture import take_new_pdf as _take_new_pdf
from paperpull_core.capture import fetch_pdf as _core_fetch_pdf
from paperpull_core.capture import take_new_tab as _core_take_new_tab
from paperpull_core.capture import take_same_tab as _core_take_same_tab
from paperpull_core.controls import control_texts as _control_texts
from paperpull_core.controls import second_step as _core_second_step
from paperpull_core.controls import controls_named as _controls_named
from paperpull_core.dates import checked as _checked_date
from paperpull_core.dates import full_year as _full_year

log = logging.getLogger("applecard_docs.site")

BASE = "https://card.apple.com"

# The three kinds of document, each with the words its title starts with.
# The title is how the orchestrator hands a document back to be fetched,
# so it is also how download_bill knows which section to open.
CARD, SAVINGS, TAX = "card", "savings", "tax"
KINDS = (CARD, SAVINGS, TAX)
KIND_TITLE = {CARD: "Apple Card Statement", SAVINGS: "Savings Statement",
              TAX: "Tax Document"}

# GUESS, all of them. card.apple.com is a single-page app and nobody here
# has seen its routes signed in. These are the addresses such an app would
# plausibly use. A route that does not exist lands on the overview, which
# is harmless, and then the section is reached through its own menu
# (SECTION_PATH below), which is how a person would get there anyway.
SECTION_URLS = {
    CARD: [f"{BASE}/statements"],
    SAVINGS: [f"{BASE}/savings/statements", f"{BASE}/savings"],
    TAX: [f"{BASE}/savings/documents", f"{BASE}/savings/statements", f"{BASE}/documents"],
}

# GUESS. The menu words a person would press to reach each section from
# the overview, one press per step, each checked against the guard. Apple
# says Savings is reached from the Apple Card account, so the Savings
# steps start there.
SECTION_PATH = {
    CARD: [r"^\s*statements?\s*$"],
    SAVINGS: [r"^\s*savings(\s+account)?\s*$", r"^\s*statements?\s*$"],
    TAX: [r"^\s*savings(\s+account)?\s*$", r"^\s*(tax\s+(documents?|forms?)|documents?|statements?)\s*$"],
}

BILLING_CANDIDATES = [SECTION_URLS[CARD][0], SECTION_URLS[SAVINGS][0], f"{BASE}/"]
BILLING_URL = BILLING_CANDIDATES[0]
URLS = {
    "home": f"{BASE}/",
    # The sign-in is on the front page itself (#52).
    "login": f"{BASE}/",
    "documents": BILLING_URL,
    "statements": BILLING_URL,
}

LOGIN_URL_MARKERS = ["/login", "/signin", "/sign-in", "/auth/", "/mfa",
                     "/verification", "/challenge", "/authenticate"]

# Apple's own sign-in hosts. Public, and not in ALLOWED_HOSTS, because
# nothing this app wants is ever served from them. A tab on one of these,
# or a sign-in frame from one, means the person is not signed in yet.
SIGN_IN_HOSTS = ("idmsa.apple.com", "appleid.apple.com", "account.apple.com")

# ---------------------------------------------------------------------------
# HARD SAFETY GUARD. Tuned for a credit card with a savings account behind
# it. Never move money in either direction, never touch Daily Cash or Apple
# Cash, never dispute, never show or replace a card, never change a
# setting. The bank words are the same as every other bank app's, except
# that "card" alone is allowed, because every statement here is an Apple
# Card statement, and the card words that matter are listed one by one.
# ---------------------------------------------------------------------------
FORBIDDEN_CONTROL_RE = re.compile(
    r"(transfer|zelle|\bwire\b|\bpay\b|payments?|pay\s*later|bill\s*pay|autopay|auto\s*pay|"
    r"schedul|recurring|deposit|withdraw|send\s+money|request\s+money|move\s+money|add\s+money|"
    r"\bapply\b|open\s+(an?\s+)?(account|savings)|close\s+(the\s+|my\s+)?(account|savings|card)|"
    r"\bloan\b|\bborrow|"
    r"daily\s+cash|apple\s+cash|\bcash\b|"
    r"card\s+(number|details?|info(rmation)?)|security\s+code|\bcvv\b|virtual\s+card|"
    r"physical\s+card|titanium|new\s+card|request\s+(a\s+)?card|"
    r"replace|activate|\block\b|unlock|freeze|\bpin\b|limit|\blost\b|stolen|\bfraud|"
    r"dispute|report\s+(an?\s+)?(issue|problem|charge|transaction)|"
    r"\bfamily\b|\bshare\b|sharing|invite|participant|co-?owner|"
    r"bank\s+accounts?|linked\s+accounts?|add\s+(a\s+)?bank|"
    r"overdraft|alerts?\b|notifications?|\bbudget|\bgoal|\brewards?\b|\boffers?\b|"
    r"enroll|unenroll|sign\s+up|paperless|delivery\s+preference|"
    r"enable|disable|change\b|edit\b|update\b|modify|manage\b|"
    r"set\s+up|delete|remove|cancel|"
    r"password|passcode|username|profile\b|settings|preferences|contact\s+info|\baddress\b|"
    r"confirm\b|submit|agree|accept|authorize|\bchat\b|contact\s+us|message|"
    r"beneficiar|nickname|sign\s*out|log\s*out|"
    # Not dangerous, but not a PDF either. Apple offers a transaction
    # export as CSV or OFX next to the statements, and refusing it here
    # means it can never be mistaken for the statement it sits beside.
    r"export|\bcsv\b|\bofx\b|\bqfx\b|\bqbo\b|quicken|spreadsheet)", re.I)

SAFE_DOC_CONTROL_RE = re.compile(
    r"(download|view|open|print|\bpdf\b|statement|document|\bletter\b|notice|"
    r"1099|tax\s+(form|document)|history|"
    r"see\s+(more|all|older)|show\s+(more|all|older)|load\s+more)", re.I)

# The few section names that are safe to press although they fetch no
# document themselves. Exact labels only, so "Savings" is a menu entry and
# "Savings transfer" never is.
SECTION_NAV_RE = re.compile(
    r"^\s*(savings(\s+account)?|statements?|documents?|tax\s+(documents?|forms?))\s*$", re.I)

# A control that fetches one document. GUESS at the wording, wide on
# purpose. "Download PDF", "Download Statement", "View", "1099-INT".
BILL_CONTROL_RE = re.compile(
    r"((download|view|print|open|get)\s*(my\s+|the\s+|this\s+|your\s+)?(statement|document|pdf|tax|letter|notice|1099)|"
    r"(statement|document|tax\s+form|1099(-?int)?)\s*\(?\s*pdf\s*\)?|\bpdf\b|\b1099-?int\b|"
    r"^\s*(view|download|open)\s*$)", re.I)

# A link that points straight at a PDF, from a row's href.
PDF_HREF_RE = re.compile(r"\.pdf(\?|$)|/pdf\b|format=pdf|statement.*download|download.*statement|docId|documentId", re.I)

SECURITY_CHALLENGE_MARKERS = [
    "enter the code", "verification code", "6-digit", "two-factor",
    "two-step", "authenticator", "confirm your identity", "verify your identity",
    "we sent a code", "trusted device", "trusted phone number", "unusual",
    "are you a robot", "captcha", "check your email",
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
    "doc_row": ("table tbody tr, [role='row'], [role='listitem'], [class*='statement' i], "
                "li[class*='document' i], [class*='document' i]"),
    "doc_link": "a[href*='.pdf'], a[download], button[class*='download' i]",
    "download_control": "a[download], a[href$='.pdf'], button:has-text('Download')",
    "page_ready": "table, [role='row'], [role='list'], main, [role='main']",
    "sign_in_frame": "iframe[src*='idmsa.apple.com'], iframe[src*='appleid.apple.com']",
}

# ---------------------------------------------------------------------------
# Date parsing
# ---------------------------------------------------------------------------
_MONTH = (r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
          r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|"
          r"Dec(?:ember)?)")
DATE_PATTERNS = [
    (re.compile(_MONTH + r"\.?\s+(\d{1,2}),?\s+(\d{4})", re.I), "mdY"),
    (re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b"), "mdy_slash"),
    (re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{2})\b"), "mdy_slash2"),
    (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})(?!\d)"), "iso"),
]
_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
MONTH_YEAR_RE = re.compile(r"\b" + _MONTH + r",?\s+(\d{4})\b", re.I)
YEAR_RE = re.compile(r"\b(19|20)(\d{2})\b")
TAX_YEAR_RE = re.compile(r"tax\s+year\s*:?\s*((?:19|20)\d{2})\b|\b((?:19|20)\d{2})\s+(?:form\s+)?1099|"
                         r"1099(?:-?int)?\s*(?:for\s+)?((?:19|20)\d{2})\b", re.I)
TAX_WORDS_RE = re.compile(r"1099|\btax\b", re.I)


def _one_exact(m, kind) -> Optional[str]:
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
        return None
    return None


def _parse_date_from_page(text: str) -> Optional[str]:
    if not text:
        return None
    for pattern, kind in DATE_PATTERNS:
        m = pattern.search(text)
        if m:
            got = _one_exact(m, kind)
            if got:
                return got
    return None


def parse_date(text):
    """The date this provider's page is showing, as YYYY-MM-DD.

    Refuses a result that names a day which does not exist, because a
    reference number is shaped like a date and used to be taken for one."""
    return _checked_date(_parse_date_from_page(text), None)


def _exact_dates(text: str) -> List[str]:
    """Every real day the text names, in order, each once."""
    out: List[str] = []
    for pattern, kind in DATE_PATTERNS:
        for m in pattern.finditer(text or ""):
            got = _checked_date(_one_exact(m, kind), None)
            if got and got not in out:
                out.append(got)
    return sorted(out)


def _month_ends(text: str) -> List[str]:
    """Every "August 2026" the text names, as that month's last day."""
    out: List[str] = []
    for m in MONTH_YEAR_RE.finditer(text or ""):
        month, year = _MONTHS[m.group(1)[:3].lower()], int(m.group(2))
        iso = f"{year:04d}-{month:02d}-{_last_day(year, month):02d}"
        if iso not in out:
            out.append(iso)
    return out


def document_date(kind: str, text: str) -> Optional[str]:
    """The one date a document's control or row gives it, or None.

    None whenever the text could mean two documents, because a statement
    saved under the wrong month is worse than one that is not saved. The
    same function reads discovery and the later download, so the control
    that is pressed is always the one that was listed.

    A statement is named by its month, which ends on the month's last day
    because Apple Card and Savings statements run for a calendar month. If
    no month is named, one printed day is taken, or two that are the ends
    of one statement period, the later being the close. A tax form is filed
    at the end of its tax year, the way every other app here files one.
    """
    text = text or ""
    if kind == TAX:
        m = TAX_YEAR_RE.search(text)
        if m:
            year = next(g for g in m.groups() if g)
            return f"{year}-12-31"
        # Without the words "tax year", a lone year is believed only when
        # nothing else on the row is a date. "Issued January 31, 2026" is
        # the 2025 form, and its year is the wrong one.
        if _exact_dates(text) or _month_ends(text):
            return None
        years = sorted({a + b for a, b in YEAR_RE.findall(text)})
        return f"{years[0]}-12-31" if len(years) == 1 else None
    months = _month_ends(text)
    if len(months) == 1:
        return months[0]
    if months:
        return None
    days = _exact_dates(text)
    if len(days) == 1:
        return days[0]
    if len(days) == 2:
        from datetime import date
        a, b = (date.fromisoformat(d) for d in days)
        if 0 < (b - a).days <= 45:
            return days[1]
    return None


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


def kind_of_title(title: str) -> str:
    """Which section a document came from, from the title discovery gave
    it. A title this app did not write is read the same careful way."""
    t = (title or "").lower()
    if t.startswith(KIND_TITLE[TAX].lower()) or TAX_WORDS_RE.search(t):
        return TAX
    if "savings" in t:
        return SAVINGS
    return CARD


def title_for(kind: str, iso: str, label: str = "") -> str:
    """"Apple Card Statement - August 2026", "Savings Statement - August
    2026", "1099-INT - 2025". The month and year only, since a statement is
    a month, and the form's own name when the control carries it."""
    from datetime import date
    d = date.fromisoformat(iso)
    if kind == TAX:
        name = "1099-INT" if re.search(r"1099[\s-]*int", label or "", re.I) else KIND_TITLE[TAX]
        return f"{name} - {d.year}"
    return f"{KIND_TITLE[kind]} - {d.strftime('%B')} {d.year}"


_WORD_VALUE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_ -]{0,23}$")


def _plain_word(v: str) -> bool:
    """"STATEMENT", "LAST_90_DAYS", not an id, a token or a number."""
    return bool(_WORD_VALUE_RE.match(v)) and sum(ch.isdigit() for ch in v) <= 3


def _safe_query(url: str) -> str:
    """A URL's query parameters, names always, values only when they are
    plain words. A value with a digit, a token, an id, anything long, is
    "...". This is what a repair needs to make the same call, and nothing
    else."""
    from urllib.parse import parse_qsl
    try:
        pairs = parse_qsl(urlsplit(url).query, keep_blank_values=True)
    except ValueError:
        return ""
    out = []
    for k, v in pairs[:20]:
        out.append("%s=%s" % (k[:30], v if _plain_word(v) else "..."))
    return "&".join(out)


def _on_sign_in_host(url: str) -> bool:
    try:
        host = (urlsplit(url or "").hostname or "").lower().rstrip(".")
    except ValueError:
        return False
    return any(host == h or host.endswith("." + h) for h in SIGN_IN_HOSTS)


def looks_signed_out(page) -> bool:
    # page.url is read outside any try on purpose. A page that cannot say
    # where it is must not be called signed in.
    url = (page.url or "").lower()
    if any(m in url for m in LOGIN_URL_MARKERS) or _on_sign_in_host(url):
        return True
    try:
        if page.locator("input[type='password']").count() > 0:
            return True
    except Exception:
        pass
    # GUESS. Apple's sign-in is a frame from its own sign-in host, laid
    # over card.apple.com, so the password field is not on the page
    # itself. A frame that is there and carries a field to type an Apple
    # Account or a password into is a sign-in in progress. A frame alone
    # is not, since a signed-in page may keep one around.
    try:
        for frame in page.frames:
            if not _on_sign_in_host(frame.url or ""):
                continue
            fields = frame.locator("input[type='password'], #account_name_text_field")
            for i in range(min(fields.count(), 4)):
                if fields.nth(i).is_visible():
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
    return bool(SAFE_DOC_CONTROL_RE.search(name) or SECTION_NAV_RE.match(name))


# ---------------------------------------------------------------------------
# Downloads from a real Edge or Chrome attached over CDP. The browser saves
# the file itself, into its own Downloads folder, and Playwright's download
# event never fires. So the browser is pointed at a folder of ours and that
# folder is watched after every click.
# ---------------------------------------------------------------------------


def _take_new_tab(page, new_pages, out_path: Path) -> bool:
    """A PDF a click opened in a new tab. The core does the reading, this
    app's guard decides which addresses it may read."""
    return _core_take_new_tab(page, new_pages, out_path, is_safe_url)


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------

def dismiss_overlay(page) -> None:
    """Close a cookie banner, a survey prompt or a promo overlay, the things
    that sit over signed-in pages and intercept clicks. Escape first, then
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


def _headings(page) -> str:
    try:
        return " ".join(page.locator("h1, h2").all_inner_texts()[:6])
    except Exception:
        return ""


def _looks_like(page, kind: str) -> bool:
    """GUESS. Whether the page on screen is this section. A document
    control must be there. Savings is told from the card by the word
    Savings in the address or the top headings, and the card page must
    not say it, because a Savings statement filed as a card statement is
    the mistake this app is most likely to make."""
    try:
        if _bill_controls(page).count() == 0:
            return False
    except Exception:
        return False
    try:
        path = (urlsplit(page.url or "").path or "").lower()
    except ValueError:
        path = ""
    savingsy = "savings" in path or bool(re.search(r"\bsavings\b", _headings(page), re.I))
    try:
        body = page.locator("body").inner_text(timeout=5000)
    except Exception:
        return False
    if kind == TAX:
        return bool(re.search(r"1099|tax\s+(documents?|forms?)", body, re.I))
    # A page of tax forms alone is not a statements page, or a run that
    # starts on one would never go looking for the card's statements.
    if not re.search(r"\bstatements?\b", body, re.I):
        return False
    return savingsy if kind == SAVINGS else not savingsy


def _press_step(page, pattern: str, trace: Optional[list] = None) -> bool:
    """Press the one visible menu entry whose whole label matches, once,
    after the guard has passed it. False when there is none."""
    rx = re.compile(pattern, re.I)
    for role in ("link", "tab", "button", "menuitem"):
        try:
            loc = page.get_by_role(role, name=rx)
            for i in range(min(loc.count(), 6)):
                el = loc.nth(i)
                if not el.is_visible():
                    continue
                label = (el.inner_text(timeout=800) or el.get_attribute("aria-label") or "").strip()
                if not is_safe_control(label):
                    continue
                el.click(timeout=5000)
                page.wait_for_timeout(3000)
                if trace is not None:
                    trace.append({"note": "pressed a section menu entry", "role": role,
                                  "control": redact(label)[:60]})
                return True
        except Exception:
            continue
    return False


_SECTION_URL: dict = {}


def goto_section(page, kind: str, trace: Optional[list] = None) -> bool:
    """Open the card's statements, the Savings statements, or wherever the
    tax forms are. The page already on screen first, then the address
    that worked last time, then the guessed addresses, then the overview
    and its menu one step at a time. The address that works is kept, so
    the list is walked once per run."""
    dismiss_overlay(page)
    if is_safe_url(page.url or "") and not looks_signed_out(page) and _looks_like(page, kind):
        return True
    tried = []
    for url in ([_SECTION_URL[kind]] if kind in _SECTION_URL else []) + SECTION_URLS[kind]:
        if url in tried:
            continue
        tried.append(url)
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(4000)
        except Exception as e:
            log.info("goto %s failed: %s", url, e)
            continue
        dismiss_overlay(page)
        if looks_signed_out(page):
            return False
        if _looks_like(page, kind):
            _SECTION_URL[kind] = page.url or url
            return True
    try:
        page.goto(URLS["home"], wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(4000)
    except Exception as e:
        log.info("goto the overview failed: %s", e)
        return False
    if looks_signed_out(page):
        return False
    dismiss_overlay(page)
    for step in SECTION_PATH[kind]:
        if _looks_like(page, kind):
            break
        if not _press_step(page, step, trace):
            break
    if _looks_like(page, kind):
        if is_safe_url(page.url or ""):
            _SECTION_URL[kind] = page.url
        return True
    if trace is not None:
        trace.append({"note": "the section was not found", "kind": kind,
                      "document_controls": _count(_bill_controls(page))})
    return False


def _count(loc) -> int:
    try:
        return loc.count()
    except Exception:
        return -1


def goto_documents(page) -> bool:
    """A signed-in card.apple.com page that lists documents of any kind.
    The card's statements first, since every account has those."""
    global BILLING_URL
    for kind in KINDS:
        if goto_section(page, kind):
            BILLING_URL = page.url or BILLING_URL
            return True
        if looks_signed_out(page):
            return False
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
    pat = re.compile(r"^\s*(show|load|view|see)\s+(more|all|older)(\s+(statements?|documents?))?\s*$|"
                     r"^\s*(older|previous)\s+statements?\s*$", re.I)
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


# The row a document control sits in. The control's own name first, then
# the nearest enclosing element whose text carries a date or a month,
# up to six levels up. The text is handed back so document_date can refuse
# a container that names more than one.
_ROW_OF_JS = r"""el => {
  const dateRe = /(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2},?\s+)?\d{4}|\d{1,2}\/\d{1,2}\/\d{2,4}|\d{4}-\d{2}-\d{2}|\b(19|20)\d{2}\b/i;
  let node = el, depth = 0;
  while (node && depth < 6) {
    const txt = (node.innerText || '').trim();
    if (dateRe.test(txt)) return txt.slice(0, 300);
    node = node.parentElement; depth++;
  }
  return '';
}"""


def _label_of(el) -> str:
    try:
        return (el.get_attribute("aria-label") or el.inner_text(timeout=800) or "").strip()
    except Exception:
        return ""


def _read_control(el, kind: str) -> Tuple[str, str, Optional[str], str]:
    """A control's label, the kind it belongs to, its date, and its row's
    text. A control on a statements page whose words say tax is a tax
    form, since Savings may list its 1099-INT beside its statements."""
    name = _label_of(el)
    row_text = ""
    try:
        row_text = el.evaluate(_ROW_OF_JS) or ""
    except Exception:
        row_text = ""
    own = TAX if TAX_WORDS_RE.search(name + " " + row_text) else (SAVINGS if kind == SAVINGS else CARD)
    if kind == TAX and own != TAX:
        return name, own, None, row_text
    iso = document_date(own, name) or document_date(own, row_text)
    return name, own, iso, row_text


def collect_download_docs(page, kind: str = CARD, trace: Optional[list] = None) -> List[RawDoc]:
    """Read every document the section on screen offers. Each control's
    own name, or the row it sits in, carries the date. One document per
    kind and date, since a row often has a View and a Download for the
    same statement."""
    docs: List[RawDoc] = []
    seen = set()
    undated = 0
    expand_all(page)
    scroll_full_page(page)
    ctrls = _bill_controls(page)
    for i in range(ctrls.count()):
        el = ctrls.nth(i)
        name, own, iso, _row = _read_control(el, kind)
        if not is_safe_control(name):
            continue
        if kind == TAX and own != TAX:
            continue
        if not iso:
            undated += 1
            continue
        if (own, iso) in seen:
            continue
        seen.add((own, iso))
        try:
            href = el.get_attribute("href") or ""
        except Exception:
            href = ""
        title = title_for(own, iso, name + " " + _row)
        docs.append(RawDoc(title=title, date_text=iso,
                           href=href if PDF_HREF_RE.search(href or "") else "",
                           text=f"Apple Card {title}", row_index=i, kind=own))
    if trace is not None:
        trace.append({"note": "read a section", "kind": kind, "documents": len(docs),
                      "controls_without_one_date": undated})
    if undated:
        log.info("%d document control(s) in the %s section carried no single date, left alone",
                 undated, kind)
    return docs


def _control_for(page, kind: str, iso: str):
    """The control for the `kind` document dated `iso`, matched the same
    way discovery found it, or None. A Download is preferred to a View
    when a row has both."""
    ctrls = _bill_controls(page)
    found = []
    for i in range(ctrls.count()):
        el = ctrls.nth(i)
        name, own, got, _row = _read_control(el, kind)
        if own == kind and got == iso and is_safe_control(name):
            found.append((el, name))
    if not found:
        return None, ""
    found.sort(key=lambda p: 0 if re.search(r"download|pdf", p[1], re.I) else 1)
    return found[0]


def _fetch_pdf(page, href: str) -> Optional[bytes]:
    """A PDF link fetched from inside the signed-in page, cookies and all.
    The fetching is the core's, the hosts are this app's."""
    return _core_fetch_pdf(page, href, is_safe_url)


def _take_same_tab(page, start_url: str, out_path: Path, trace) -> bool:
    """A PDF the click opened in this very tab. The core does the reading,
    this app's guard decides which addresses it may read."""
    return _core_take_same_tab(page, start_url, out_path, trace, is_safe_url)


# GUESS. If Download asks which format, PDF is the one. CSV and OFX never
# match, and the guard refuses them besides.
_SECOND_STEP_RE = re.compile(
    r"^\s*(download|download\s+(pdf|now|file|statement|document)|save|save\s+(as\s+)?pdf|"
    r"pdf|view\s*/\s*print\s+pdf|print|open\s+pdf)\s*$", re.I)


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
    start_url = page.url or ""

    def on_download(dl):
        downloads.append(dl)

    def on_response(res):
        try:
            url = res.url or ""
            if not is_safe_url(url):
                return
            ct = (res.headers.get("content-type") or "").lower()
            if trace is not None and ("json" in ct or "pdf" in ct or "octet" in ct):
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
        except Exception:
            pass

    ctx.on("response", on_response)
    page.on("download", on_download)
    before = set(ctx.pages)
    seen = _snapshot(dl_dir)
    controls_before = _control_texts(page)

    def landed() -> bool:
        if downloads:
            try:
                from paperpull_core.receipt_pdf import save_download
                save_download(downloads[0], out_path)
                if out_path.exists() and out_path.read_bytes()[:5] == b"%PDF-":
                    return True
            except Exception as e:
                log.info("download event save failed: %s", e)
        if got.get("body"):
            out_path.write_bytes(got["body"])
            return True
        if got.get("refetch"):
            try:
                resp = page.context.request.get(got.pop("refetch"), timeout=60000)
                body = resp.body() if resp.ok else b""
                if body[:5] == b"%PDF-":
                    out_path.write_bytes(body)
                    return True
            except Exception:
                pass
        return _take_new_pdf(dl_dir, seen, out_path)

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
        log.info("click on %r produced no PDF", label)
        return False
    finally:
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


def download_bill(page, dl_dir, iso_date: str, out_path, title: str = "",
                  trace: Optional[list] = None) -> bool:
    """Save the document dated `iso_date` of the kind its title names. The
    section is opened, and a PDF link on the row is fetched from inside
    the page. Otherwise the row's own control is pressed once, after the
    guard has passed it, and whichever the site produces is caught, a
    download event or a PDF response, in this tab or one it opens.

    `dl_dir` is where the attached browser saves a download, watched
    after every click."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    kind = kind_of_title(title)
    if not goto_section(page, kind, trace):
        log.info("could not open the %s section for %s", kind, iso_date)
        return False
    expand_all(page)

    el, label = _control_for(page, kind, iso_date)
    if el is None:
        log.info("no %s document control found for %s", kind, iso_date)
        if trace is not None:
            trace.append({"note": "no control carried this document's date", "kind": kind,
                          "document_controls": _count(_bill_controls(page))})
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
            body = _fetch_pdf(page, target)
            if body:
                out_path.write_bytes(body)
                return True
            if trace is not None:
                trace.append({"note": "the control's own link did not answer with a PDF",
                              "url": redact(target)[:160]})
    return _catch_pdf(page, el, label, out_path, trace, dl_dir)


# ---------------------------------------------------------------------------
# Diagnose. A survey a tester can attach to an issue. No screenshot, since a
# signed-in page shows names, numbers and amounts. Digit runs are masked and
# JSON bodies are recorded as shape only.
# ---------------------------------------------------------------------------
_ROW_JS = r"""() => {
  const out = [];
  for (const tr of document.querySelectorAll('table tr, [role=row], [role=listitem], li')) {
    const txt = (tr.innerText || '').trim();
    if (!txt) continue;
    const link = tr.querySelector("a[href]");
    out.push({text: txt.slice(0, 200), href: link ? link.getAttribute('href') : ''});
  }
  return out.slice(0, 200);
}"""

SURVEY_LINK_RE = re.compile(
    r"^\s*((see|view|show)\s+)?(statements?|savings(\s+account)?|documents?|"
    r"tax\s+(documents?|forms?)|savings\s+statements?)\s*$", re.I)


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
    out["sections"] = {k: _looks_like(page, k) for k in KINDS}
    return out


def survey(page, dwell_ms: int = 4000, max_follow: int = 6) -> dict:
    """What the signed-in card, Savings and tax pages look like, without
    downloading anything. Records each page, its headings and controls with
    the guard's verdict on each, which section each page was taken for, and
    every JSON or PDF response card.apple.com sends while the page settles.
    Then follows, one at a time and back again, the few links whose text is
    a section name. No screenshot."""
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
            if followed >= max_follow or c["role"] not in ("link", "button", "tab") or not c["survey"]:
                continue
            if not is_safe_control(c["text"]):
                continue
            try:
                link = page.get_by_role(c["role"], name=re.compile(
                    "^" + re.escape(c["text"].replace("#", "")) + "$", re.I)).first
                if link.count() == 0:
                    continue
                before = page.url
                tabs_before = set(page.context.pages)
                link.click(timeout=5000)
                page.wait_for_timeout(dwell_ms)
                # A control that opened a new tab is surveyed there, then the
                # tab is closed. Off Apple Card's host it is still recorded,
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
#
# card.apple.com is known, the requester signs in there (#52). It is the
# only host here, and deliberately not apple.com as a whole, since that
# would take in the Apple Store, where a control can buy something.
# Whether a statement PDF is served from card.apple.com itself or from a
# separate file host is not known. None is guessed at. If the recording
# shows the PDF arriving from another Apple host, that one host is added
# here and nothing wider.
# ---------------------------------------------------------------------------
ALLOWED_HOSTS = {"card.apple.com"}


def is_safe_url(url: str) -> bool:
    """True only for an https URL on one of this provider's own hosts.

    The check itself lives in the core, so all of them answer the same way.
    This app keeps the hosts, which is the part that really is its own."""
    return _host_allows(url, ALLOWED_HOSTS)
