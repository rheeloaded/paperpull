"""ALL att.com selectors, URLs, and page behavior live here.

When AT&T changes its site, repair this file only.

STATUS: round nine, the first round with bills on disk. Written without an AT&T account and
repaired from two surveys a tester sent (#26). What the surveys showed:

  * Sign-in lands on /acctmgmt/overview, a shop page. The nav's Billing
    link goes to /acctmgmt/billing/mybillingcenter, which shows the
    current bill with "View/print PDF" and "Download PDF" buttons, an
    account picker (the tester holds wireless and fiber), and a "See bill
    history" link to /acctmgmt/billing/billandpaymenthistory?filter=bill.
  * The history page lists past bills as buttons reading "Bill / Jul 23 -
    Aug 22 / $amount", and while it loads the page calls its own API,
    /msapi/webbillexpms/v1/billandpaymenthistory, whose answer is
    content.historyList[] of {type, displayDate, cycleStartDate,
    cycleEndDate, statementId, invoiceIndex, ...}, sixteen entries.
  * Round two's pilot recognized only the current bill and clicked "See
    bill history" instead of "Download PDF" beside it.
  * Round three read all sixteen bills from the API but matched the
    history buttons by accessible name, found none, and then looked for
    "Download PDF" on the history page instead of the billing center.
  * Rounds four and five reached "Download PDF" and clicked it, and
    nothing arrived, no download, no response, no tab, nothing in the
    browser's own download list. Round five had every capture in place.
    So the click either needs a second step, puts the PDF in a viewer,
    or is not landing, and the trace could not tell those apart because
    a click failure was swallowed. Round six records the click's own
    outcome, compares the page before and after, takes a control the
    click revealed as the second step, reads an embedded viewer, and
    tries "View/print PDF" when "Download PDF" gave nothing.
  * Round seven learned from the tester's screenshot that "Download PDF"
    opens a menu of "Regular PDF" and "View/print PDF", and took the
    first as the second step. Round seven's trace then showed the click
    landing and NOTHING appearing, because the menu's entries are not
    buttons, links or menuitems, so the before-and-after comparison of
    those roles could not see them. Round eight finds the entries by
    their text, whatever element they are, waits for one to be visible,
    clicks "Regular PDF", and records every element on the page whose
    text says PDF, with its tag, role and visibility, for the next look.
  * Round eight WORKED. The tester's pilot saved five bills. Two things
    came back with it. The current bill was saved twice, once dated by
    its issue date from the history API and once dated by its due date,
    a record left in discovery.json by round two, which read the date
    off the billing center's current-balance box. And the filename said
    nothing about which account (the tester holds wireless and fiber).
    Round nine reads the account's kind off the account switcher and
    puts it in the summary, drops discovery records the history API no
    longer lists when nothing was downloaded for them, and never takes a
    date that follows the word "due" as a bill date.

  So discovery now reads the history API as the page loads it, passively,
  and falls back to the bill buttons. A download opens the history page,
  clicks the bill's own button, then the "Download PDF" it reveals, and
  catches what arrives. The current bill is downloaded from the billing
  center's own button. Only the account in focus is read this round.

  What it does on a first run is deliberately cautious:

  * --login opens a real Edge or Chrome, since att.com runs Akamai bot
    protection that walls the Playwright build of Chromium.
  * --diagnose surveys whatever the billing page turns out to be, records
    its headings, its controls with the guard's verdict on each, and the
    shape of every JSON response, with digit runs masked, and takes no
    screenshot. That file is what a tester attaches to the GitHub issue.
  * --discover reads bill dates from any control that looks like a bill
    download, wherever it sits on the page.
  * --pilot tries to save the newest few, first by fetching a PDF link the
    row carries from inside the page, then by clicking the row's own
    download control and catching either the download event or a PDF
    response, whichever the site produces.

The guesses that most need confirming from a survey are marked GUESS.

SAFETY (this is a phone account with a card on file):
  This module is strictly READ-ONLY. It opens the bill history, reads the
  list of past bills, and saves the PDFs AT&T already generated. It must
  NEVER activate any control that pays a bill, enrolls in autopay or
  paperless, changes a plan, adds a line, upgrades or trades in a device,
  suspends or restores service, moves a number, or edits any setting.
  FORBIDDEN_CONTROL_RE is the guard. A control must ALSO look like a
  document action (SAFE_DOC_CONTROL_RE) before it may be clicked. There is
  no code here that submits a form or confirms a dialog.
"""
from __future__ import annotations

import base64
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from paperpull_core.controls import SETTINGS_CONTROL_RE, AUTH_CONTROL_RE
from paperpull_core.controls import safe_selects as _safe_selects

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
from paperpull_core.capture import take_new_pdf as _take_new_pdf
from paperpull_core.capture import fetch_pdf as _core_fetch_pdf
from paperpull_core.capture import take_new_tab as _core_take_new_tab
from paperpull_core.capture import fetch_as_b64 as _fetch_as_b64
from paperpull_core.controls import control_texts as _control_texts
from paperpull_core.controls import second_step as _core_second_step
from paperpull_core.controls import controls_named as _controls_named
from paperpull_core.dates import checked as _checked_date
from paperpull_core.dates import full_year as _full_year

log = logging.getLogger("att_docs.site")

BASE = "https://www.att.com"
# Read off the signed-in site's own navigation in the first survey
# (#26, 2026-09-20). The Billing link in myAT&T's nav goes to the billing
# center. The overview is where sign-in lands and is the fallback, since
# its nav carries the Billing link, which goto_documents follows. The
# routes guessed before the survey all redirected to the overview.
BILLING_CANDIDATES = [
    f"{BASE}/acctmgmt/billing/mybillingcenter",
    f"{BASE}/acctmgmt/overview",
]
# The bill history, read off the billing center's "See bill history" link
# in the second survey, and the API the page calls to fill it.
HISTORY_URL = f"{BASE}/acctmgmt/billing/billandpaymenthistory?filter=bill"
HISTORY_API_RE = re.compile(r"/msapi/webbillexpms/v1/billandpaymenthistory\b", re.I)
# The two buttons that fetch a bill's PDF, exact text from the survey.
PDF_BUTTON_RE = re.compile(r"^\s*(download\s+pdf|view\s*/\s*print\s+pdf)\s*$", re.I)
# A past bill on the history page, "Bill\nJul 23 - Aug 22\n$xx.xx".
BILL_BUTTON_RE = re.compile(r"^\s*bill\s", re.I)
_PERIOD_RE = re.compile(
    r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2})\s*[-\u2013]\s*"
    r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2})", re.I)
# The nav link that leads to the billing center, followed when the
# candidates land somewhere else. GUESS at nothing, this is its exact text.
BILLING_NAV_RE = re.compile(r"^\s*(billing|bill\s*&\s*payments?|bill\s+history)\s*$", re.I)
BILLING_URL = BILLING_CANDIDATES[0]
URLS = {
    "home": f"{BASE}/acctmgmt/overview",
    # Signing in to the billing page sends an unauthenticated user through
    # AT&T's sign-in and back.
    "login": BILLING_URL,
    "documents": BILLING_URL,
    "statements": BILLING_URL,
}

# att.com's own sign-in is on signin.att.com, a subdomain, so it is inside
# the allowlist. A page whose path says sign-in is still treated as signed
# out.
LOGIN_URL_MARKERS = ["/login", "/signin", "/sign-in", "/olam/", "/auth",
                     "/mfa", "/verification", "/challenge", "/idp/"]

# ---------------------------------------------------------------------------
# HARD SAFETY GUARD. Tuned for a wireless carrier. Never pay, never change
# service, never touch a device or a number, never edit the account.
# ---------------------------------------------------------------------------
FORBIDDEN_CONTROL_RE = re.compile(
    r"(pay\b|payment|pay\s+bill|autopay|auto\s*pay|schedule\s+payment|"
    r"one[-\s]?time\s+payment|payment\s+(plan|arrangement)|make\s+a\s+payment|"
    r"bank\b|routing|account\s+number|debit|credit\s+card|\bcard\b|wallet|"
    r"enroll|unenroll|sign\s+up|start\s+service|stop\s+service|"
    r"add\s+(a\s+)?line|add[-\s]?on|change\s+plan|\bplans?\b|upgrade|trade[-\s]?in|"
    r"\bbuy\b|\bshop\b|\border\b|\bcart\b|checkout|\bdeals?\b|\boffers?\b|"
    r"transfer\s+(service|number)|port\b|\bsim\b|esim|suspend|restore|"
    r"disconnect|reconnect|new\s+service|move\b|international|roaming|"
    r"enable|disable|activate|deactivate|change\b|edit\b|update\b|modify|manage\b|"
    r"set\s+up|delete|remove|cancel|close\s+account|"
    r"password|passcode|profile\b|settings|preferences|paperless|"
    r"confirm|submit|agree|accept|authorize|\bchat\b|contact\s+us)", re.I)

SAFE_DOC_CONTROL_RE = re.compile(
    r"(download|view|open|print|\bpdf\b|statement|document|\bbill\b|bills\b|billing\b|"
    r"invoice|history|see\s+(more|all|older)|show\s+(more|all|older)|load\s+more)", re.I)

# A control that fetches one bill. GUESS at the wording, wide on purpose.
# "Download bill (PDF)", "View bill", "Print bill", "See bill", "Bill PDF".
BILL_CONTROL_RE = re.compile(
    r"^(?!.*\bhistory\b).*?"
    r"((download|view|print|see|open|get)\s+(my\s+|the\s+|this\s+|your\s+|full\s+|"
    r"detailed\s+|past\s+)?(bill|statement|invoice)|"
    r"(bill|statement|invoice)\s*\(?\s*pdf\s*\)?|\bpdf\b)", re.I)

# A link that points straight at a bill PDF, from a row's href.
PDF_HREF_RE = re.compile(r"\.pdf(\?|$)|/pdf\b|format=pdf|bill.*download|download.*bill", re.I)

SECURITY_CHALLENGE_MARKERS = [
    "enter the code", "verification code", "6-digit", "two-factor",
    "two-step", "authenticator", "confirm your identity", "verify your identity",
    "we sent a code", "device approval", "approve this login", "unusual",
    "are you a robot", "captcha", "let's verify", "check your email",
    "check your phone", "your session has expired", "log back in",
    "access denied", "reference #",   # Akamai's wall, when it fires
]

RATE_LIMIT_MARKERS = [
    "too many requests", "rate limit", "try again later",
    "temporarily unavailable", "http error 429", "unusual traffic",
]

# ---------------------------------------------------------------------------
# Fallback selectors (used by --diagnose only)
# ---------------------------------------------------------------------------
FALLBACK = {
    "doc_row": ("table tbody tr, [role='row'], [class*='bill'], [class*='Bill'], "
                "li[class*='history'], [class*='statement']"),
    "doc_link": "a[href*='.pdf'], a[download], button[class*='download']",
    "download_control": "a[download], a[href$='.pdf'], button:has-text('Download')",
    "page_ready": "table, [role='row'], [class*='bill'], main, [role='main']",
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
_MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July",
                "August", "September", "October", "November", "December"]


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
    that sit over att.com pages and intercept clicks. Escape first, then
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


ACCOUNT_KIND_RE = re.compile(
    r"\b(wireless|mobility|mobile|fiber|internet|home\s+phone|phone|tv|u-?verse|directv|prepaid|business)\b", re.I)


def _kind_from_line(line: str) -> str:
    """"Wireless" from a line of the switcher, or "" if it names no kind."""
    m = ACCOUNT_KIND_RE.search(line or "")
    if not m or re.fullmatch(r"account", (line or "").strip(), re.I):
        return ""
    kind = m.group(1).lower()
    return {"mobility": "Wireless", "mobile": "Wireless",
            "u-verse": "TV", "uverse": "TV"}.get(kind, kind.title())


# The switcher, whatever the page calls it. Round nine asked for a button
# whose accessible name begins with "account", and on the fiber account
# the filename came out with no kind in it at all, so that name is not
# what this page gives it. These are tried in turn and the first that
# names a kind wins (#26).
_SWITCHER_JS = r"""() => {
  const want = /\b(wireless|mobility|mobile|fiber|internet|home\s+phone|tv|u-?verse|directv|prepaid|business)\b/i;
  const out = [];
  const nodes = document.querySelectorAll(
    '[class*="switch" i],[id*="switch" i],[class*="account" i],[id*="account" i],' +
    '[aria-label*="account" i],button,[role="button"],[role="tab"],[role="menuitem"]');
  for (const el of nodes) {
    const t = (el.innerText || '').trim();
    if (!t || t.length > 300 || !want.test(t)) continue;
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height) continue;
    out.push({text: t, tag: el.tagName.toLowerCase(),
              label: (el.getAttribute('aria-label') || '').slice(0, 80),
              selected: (el.getAttribute('aria-selected') === 'true' ||
                         el.getAttribute('aria-current') !== null ||
                         /(^|\s)(active|selected|current)(\s|$)/i.test(el.className || '')),
              top: Math.round(r.top), left: Math.round(r.left)});
  }
  out.sort((a, b) => (b.selected - a.selected) || (a.top - b.top) || (a.left - b.left));
  return out.slice(0, 8);
}"""


def switcher_candidates(page) -> list:
    """What the page says about which account is in focus. For the survey,
    so a round that gets the kind wrong can be read rather than guessed at."""
    try:
        return page.evaluate(_SWITCHER_JS) or []
    except Exception as e:
        log.info("account switcher: %s", e)
        return []


def current_account_label(page) -> str:
    """The kind of account in focus, "Wireless" or "Internet", read off
    the account switcher's own text. Nothing is clicked. "" when the page
    has no switcher, a person with one account."""
    try:
        loc = page.get_by_role("button", name=re.compile(r"switch\s+account|^\s*account\b", re.I))
        for i in range(min(loc.count(), 6)):
            text = (loc.nth(i).inner_text(timeout=800) or "")
            # The switcher lists every account, and the tester's note is
            # that the one in focus is listed first, the order changing as
            # he switches. Round nine read the lines backwards and so took
            # the kind of the account he was not looking at (#26).
            for line in [ln.strip() for ln in text.splitlines() if ln.strip()]:
                kind = _kind_from_line(line)
                if kind:
                    return kind
    except Exception as e:
        log.info("account switcher: %s", e)
    # The button was not there under that name. Ask the page itself, the
    # one it marks as selected first.
    for cand in switcher_candidates(page):
        for line in [ln.strip() for ln in (cand.get("text") or "").splitlines() if ln.strip()]:
            kind = _kind_from_line(line)
            if kind:
                return kind
    return ""


# "Due Sep 30" is not a bill date. The billing center's current-balance
# box prints the due date beside the "Download PDF" button, and round two
# took it for the bill's own date.
_DUE_BEFORE_DATE_RE = re.compile(r"\bdue\b[^\n]{0,40}$", re.I)


def _date_not_due(text: str) -> Optional[str]:
    """The first date in `text` that is not a due date."""
    for m in re.finditer(r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}|\d{1,2}/\d{1,2}/\d{2,4}|\d{4}-\d{2}-\d{2}", text or "", re.I):
        before = (text or "")[max(0, m.start() - 40):m.start()]
        if _DUE_BEFORE_DATE_RE.search(before):
            continue
        iso = parse_date(m.group(0))
        if iso:
            return iso
    return None


def _bill_controls(page):
    """Every control on the page whose name says it fetches a document.
    The words are this provider's, the rest is the core's."""
    return _controls_named(page, BILL_CONTROL_RE)


def _looks_like_billing(page) -> bool:
    """The billing center, not the overview. The overview carries one
    "View bill" button, which was enough to pass the first version of this
    check and left discovery reading a shop page (#26). The URL decides
    first, then the page has to show more than one bill control or the
    words of a bill history."""
    url = (page.url or "").lower()
    if "/billing/" in url or "billhistory" in url or "/bill/" in url or "billandpaymenthistory" in url:
        return True
    if "/overview" in url:
        return False
    try:
        if _bill_controls(page).count() > 1:
            return True
    except Exception:
        pass
    try:
        body = page.locator("body").inner_text(timeout=5000)
    except Exception:
        return False
    return bool(re.search(r"bill(ing)?\s+(history|period|date)|past\s+bills|previous\s+bills",
                          body, re.I))


def _follow_billing_nav(page) -> bool:
    """From wherever sign-in landed, click the nav's Billing link, once it
    has passed the guard, and say whether that reached the billing center."""
    for role in ("link", "button"):
        try:
            loc = page.get_by_role(role, name=BILLING_NAV_RE)
            if loc.count() == 0:
                continue
            label = (loc.first.inner_text(timeout=1000) or "").strip()
            if not is_safe_control(label):
                continue
            loc.first.click(timeout=5000)
            page.wait_for_timeout(4000)
            dismiss_overlay(page)
            return is_safe_url(page.url or "") and not looks_signed_out(page) and _looks_like_billing(page)
        except Exception as e:
            log.info("billing nav %s failed: %s", role, e)
    return False


def goto_documents(page) -> bool:
    """Open the bill history. The first candidate that is not a sign-in
    page and shows something bill-shaped wins, and the URL it lands on is
    remembered so a later call does not walk the list again."""
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
        if _follow_billing_nav(page):
            BILLING_URL = page.url.split("?")[0]
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
    """Click 'See more' / 'Show more' / 'View more bills' repeatedly to
    surface any older bills the history page loads on demand. The label is
    checked against the guard before every click."""
    pat = re.compile(r"^\s*(show|load|view|see)\s+(more|all|older)(\s+bills?)?\s*$|"
                     r"^\s*(older|previous)\s+bills?\s*$", re.I)
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


# The date a bill control belongs to. The control's own name first, then
# the nearest enclosing row or card whose text carries a date, up to six
# levels up. Returned with the container's text so a repair can see what
# the row looked like.
_ROW_OF_JS = r"""el => {
  const dateRe = /(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}|\d{1,2}\/\d{1,2}\/\d{2,4}|\d{4}-\d{2}-\d{2}/i;
  let node = el, depth = 0;
  while (node && depth < 6) {
    const txt = (node.innerText || '').trim();
    if (dateRe.test(txt)) return txt.slice(0, 300);
    node = node.parentElement; depth++;
  }
  return '';
}"""


def _history_from_api(body: dict) -> List[dict]:
    """The bills in one billandpaymenthistory answer, as {date, hint,
    period}. A payment row, if the filter ever lets one through, is left
    out. The statement id and invoice index ride along as the download
    hint. They name a bill, not a person."""
    out = []
    content = (body or {}).get("content") or {}
    for e in content.get("historyList") or []:
        if not isinstance(e, dict):
            continue
        kind = str(e.get("type") or "")
        if re.search(r"pay", kind, re.I) and not re.search(r"bill", kind, re.I):
            continue
        iso = parse_date(str(e.get("cycleEndDate") or "")) or parse_date(str(e.get("displayDate") or ""))
        if not iso:
            continue
        hint = "|".join(str(e.get(k) or "") for k in ("statementId", "invoiceIndex"))
        start = parse_date(str(e.get("cycleStartDate") or ""))
        out.append({"date": iso, "hint": hint, "start": start or ""})
    return out


def _period_end(text: str, newest_year: int, prev_month: Optional[int]) -> Tuple[Optional[str], Optional[int]]:
    """The end date of "Jul 23 - Aug 22" as ISO. The buttons carry no year,
    so the newest bill takes this year, or last year when its month has
    not come yet, and each older one steps the year back whenever its
    month is later than the one before it."""
    m = _PERIOD_RE.search(text or "")
    if not m:
        return None, prev_month
    month = _MONTHS[m.group(3)[:3].lower()]
    day = int(m.group(4))
    year = newest_year
    if prev_month is not None and month > prev_month:
        year -= 1
    return f"{year:04d}-{month:02d}-{day:02d}", month


def _history_from_buttons(page) -> List[dict]:
    """The history page's own bill buttons, when the API was not seen."""
    from datetime import date as _date
    out = []
    today = _date.today()
    year = today.year
    prev = None
    try:
        loc = page.get_by_role("button", name=BILL_BUTTON_RE)
        for i in range(min(loc.count(), 60)):
            text = (loc.nth(i).inner_text(timeout=800) or "").strip()
            if not _PERIOD_RE.search(text):
                continue
            if prev is None:
                first = _MONTHS[_PERIOD_RE.search(text).group(3)[:3].lower()]
                if first > today.month:
                    year -= 1
            iso, prev = _period_end(text, year, prev)
            if iso:
                year = int(iso[:4])
                out.append({"date": iso, "hint": "", "start": ""})
    except Exception as e:
        log.info("history buttons: %s", e)
    return out


def goto_history(page, capture: Optional[list] = None) -> bool:
    """Open the bill history page. While it loads, the API answer that
    fills it is caught and appended to `capture`, so discovery never has
    to know how the page asks for it."""
    def on_response(res):
        try:
            url = res.url or ""
            if capture is not None and is_safe_url(url) and HISTORY_API_RE.search(url):
                capture.append(res.json())
        except Exception:
            pass
    page.on("response", on_response)
    try:
        page.goto(HISTORY_URL, wait_until="domcontentloaded", timeout=60000)
        # Until the API answered, or the bill buttons are on the page,
        # whichever the caller is after, up to fifteen seconds.
        for _ in range(30):
            page.wait_for_timeout(500)
            if capture:
                break
            if capture is None and _period_buttons(page).count() > 0:
                break
        page.wait_for_timeout(1500)
    except Exception as e:
        log.info("goto history failed: %s", e)
    finally:
        try:
            page.remove_listener("response", on_response)
        except Exception:
            pass
    dismiss_overlay(page)
    return is_safe_url(page.url or "") and not looks_signed_out(page) \
        and "billandpaymenthistory" in (page.url or "")


def collect_download_docs(page) -> List[RawDoc]:
    """Every bill the account in focus has. The history API as the page
    loads it, else the history page's bill buttons, else the bill
    controls wherever they sit on the page, the way round two read them."""
    docs: List[RawDoc] = []
    seen = set()
    bodies: list = []
    if goto_history(page, bodies):
        account = current_account_label(page)
        bills = []
        for body in bodies:
            bills.extend(_history_from_api(body))
        if not bills:
            bills = _history_from_buttons(page)
        for b in bills:
            if b["date"] in seen:
                continue
            seen.add(b["date"])
            disp = _human_date(b["date"])
            docs.append(RawDoc(title=f"Monthly Statement - {disp}", date_text=b["date"], account=account,
                               href=b["hint"], text=f"AT&T Bill {disp}", kind="statement"))
        if docs:
            return docs
    account = current_account_label(page)
    expand_all(page)
    scroll_full_page(page)
    ctrls = _bill_controls(page)
    for i in range(ctrls.count()):
        el = ctrls.nth(i)
        try:
            name = (el.get_attribute("aria-label") or el.inner_text(timeout=800) or "").strip()
        except Exception:
            name = ""
        if not is_safe_control(name):
            continue
        try:
            href = el.get_attribute("href") or ""
        except Exception:
            href = ""
        row_text = ""
        iso = _date_not_due(name)
        if not iso:
            try:
                row_text = el.evaluate(_ROW_OF_JS) or ""
            except Exception:
                row_text = ""
            iso = _date_not_due(row_text)
        if not iso or iso in seen:
            continue
        seen.add(iso)
        disp = _human_date(iso)
        docs.append(RawDoc(title=f"Monthly Statement - {disp}", date_text=iso, account=account,
                           href=href if PDF_HREF_RE.search(href or "") else "",
                           text=f"AT&T Bill {disp}", row_index=i, kind="statement"))
    return docs


def _control_for(page, iso: str):
    """The bill control for the bill dated `iso`, matched the same way
    discovery found it, or None."""
    ctrls = _bill_controls(page)
    for i in range(ctrls.count()):
        el = ctrls.nth(i)
        try:
            name = (el.get_attribute("aria-label") or el.inner_text(timeout=800) or "").strip()
        except Exception:
            name = ""
        found = parse_date(name)
        if not found:
            try:
                found = parse_date(el.evaluate(_ROW_OF_JS) or "")
            except Exception:
                found = None
        if found == iso:
            return el, name
    return None, ""


def _fetch_pdf(page, href: str) -> Optional[bytes]:
    """A PDF link fetched from inside the signed-in page, cookies and all.
    The fetching is the core's, the hosts are this app's."""
    return _core_fetch_pdf(page, href, is_safe_url)


def _period_buttons(page):
    """The history page's bill buttons, every button whose visible text
    carries a "Jul 23 - Aug 22" period. Matched on the text a person
    sees, not the accessible name: round three matched the name, which
    a button can carry as an aria-label that reads nothing like its
    face, and found none of them."""
    return page.get_by_role("button").filter(has_text=_PERIOD_RE)


def _bill_button_for(page, iso_date: str, anchor_year: Optional[int] = None,
                     today=None):
    """The history page's button for the bill whose period ends on
    `iso_date`, or None.

    The buttons carry no year, so each one's year is worked out from its
    place in the list, the way discovery reads them. The newest takes
    this year, or last year when its month has not come yet, or
    `anchor_year` when a date range naming a year is showing, and each
    older one steps back a year across January. Only the exact date
    matches.

    It used to match "Aug 22" alone and take the first, so a bill from
    August 2025 asked for while only 2026's were showing would have
    pressed 2026's and saved it under the 2025 date (#26)."""
    from datetime import date as _date
    today = today or _date.today()
    dated = []
    try:
        loc = _period_buttons(page)
        year, prev = None, None
        for i in range(min(loc.count(), 60)):
            el = loc.nth(i)
            text = (el.inner_text(timeout=800) or "").strip()
            pm = _PERIOD_RE.search(text)
            if not pm:
                continue
            if year is None:
                month = _MONTHS[pm.group(3)[:3].lower()]
                if anchor_year is not None:
                    year = anchor_year
                else:
                    year = today.year - (1 if month > today.month else 0)
            iso, prev = _period_end(text, year, prev)
            if not iso:
                continue
            year = int(iso[:4])
            dated.append((el, text, iso))
    except Exception as e:
        log.info("bill button lookup failed: %s", e)
        return None, ""
    # Under a named year every button has to work out to that year. One
    # that does not means the list crossed January and the years above
    # are off by one, so nothing is matched rather than the wrong bill.
    if anchor_year is not None and any(iso[:4] != str(anchor_year)
                                       for _, _, iso in dated):
        log.info("the %s list crosses a year, so no bill is matched on it",
                 anchor_year)
        return None, ""
    for el, text, iso in dated:
        if iso == iso_date:
            return el, text
    return None, ""


# The history's own date filter. It shows the most recent bills until
# someone chooses a wider range, and an older bill has no button until
# then (#26). None of its words are document words, so the guard refuses
# them all, and each gets an allowlist of its own instead of the guard
# being loosened. The opener, an option that names nothing but a span of
# time, and the button that applies it. The forbidden words are still
# checked first.
RANGE_OPENER_RE = re.compile(
    r"^\s*((select|choose|filter\s+by)\s+)?(a\s+)?date(\s+range)?\s*$", re.I)
# "6 months" and "Past 2 years" are guesses from the round that found the
# menu and no option in it (#26), both still nothing but a span of time.
RANGE_OPTION_RE = re.compile(
    r"^\s*(?:(?:(?:last|past|previous)\s+)?(\d{1,2})\s+months?|"
    r"(?:last|past|previous)\s+([1-9])\s+years?|"
    r"((?:19|20)\d\d)|"
    r"(all)(?:\s+(?:bills|dates|time|history))?|"
    r"(?:this|current|last|previous|past)\s+year)"
    r"\s*$", re.I)
RANGE_APPLY_RE = re.compile(
    r"^\s*(apply|apply\s+filters?|done|show\s+results|view\s+results)\s*$", re.I)


def is_range_control(label: str, pat) -> bool:
    text = re.sub(r"\s+", " ", label or "").strip()
    return bool(text) and not FORBIDDEN_CONTROL_RE.search(text) \
        and bool(pat.match(text))


def _range_choice(labels, iso_date: str, today=None):
    """The option that reaches `iso_date`, and the year it names if any.

    A span counted back from today first, the shortest "last N months"
    that reaches the bill, then "all", because the history's newest bill
    is then this year's and every button's year can be worked out from
    today. A named year only when nothing else reaches, since a year's
    list can hold a bill that ends in January of the next. "Last year" is
    never chosen, because it can mean the calendar year or the last
    twelve months and a wrong guess would shift every date by a year.
    None when nothing on offer covers it, which the trace says."""
    from datetime import date as _date
    today = today or _date.today()
    y, m = int(iso_date[:4]), int(iso_date[5:7])
    back = (today.year - y) * 12 + (today.month - m)
    best = None
    for label in labels:
        mm = RANGE_OPTION_RE.match(label or "")
        if not mm:
            continue
        if mm.group(1) or mm.group(2):
            months = int(mm.group(1)) if mm.group(1) else 12 * int(mm.group(2))
            key, year = ((0, months), None) if back < months else (None, None)
        elif mm.group(4):
            key, year = (1, 0), None
        elif mm.group(3) and int(mm.group(3)) == y:
            key, year = (2, 0), y
        else:
            key, year = None, None
        if key is not None and (best is None or key < best[0]):
            best = (key, label, year)
    return (best[1], best[2]) if best else (None, None)


def _range_options(page) -> list:
    """Every visible element that reads as a range option, with its text."""
    found, seen = [], set()
    for role in ("option", "menuitemradio", "radio", "menuitem",
                 "menuitemcheckbox", "checkbox", "tab", "button", "link"):
        try:
            loc = page.get_by_role(role, name=RANGE_OPTION_RE)
            for i in range(min(loc.count(), 20)):
                el = loc.nth(i)
                text = re.sub(r"\s+", " ", el.inner_text(timeout=500) or
                              el.get_attribute("aria-label") or "").strip()
                if text and text not in seen and el.is_visible():
                    seen.add(text)
                    found.append((el, text))
        except Exception:
            continue
    return found


def _range_texts(page, appeared_texts: set) -> list:
    """Range options that are not controls at all, a list of plain divs,
    found by their words. Only words that appeared when the opener was
    pressed count, so a year printed as a heading on the history is never
    taken for an option."""
    found, seen = [], set()
    try:
        loc = page.get_by_text(RANGE_OPTION_RE)
        for i in range(min(loc.count(), 20)):
            el = loc.nth(i)
            try:
                text = re.sub(r"\s+", " ", el.inner_text(timeout=500) or "").strip()
            except Exception:
                continue
            if (text and text not in seen and text in appeared_texts
                    and is_range_control(text, RANGE_OPTION_RE) and el.is_visible()):
                seen.add(text)
                found.append((el, text))
    except Exception:
        pass
    return found


# What is showing, as the kind of each small visible element and its words,
# so what pressing the opener brought up can be told apart from what was
# there before. The words are cut short and masked before they leave, and
# an input gives its type and whether it asks for a date, never its value.
_SHAPE_JS = r"""() => {
  const items = [];
  const counts = {selects: 0, date_inputs: 0, other_inputs: 0, listboxes: 0,
                  options: 0, comboboxes: 0, checkboxes: 0, radios: 0, dialogs: 0, menus: 0};
  const shown = (e) => {
    const r = e.getBoundingClientRect();
    const cs = getComputedStyle(e);
    return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none';
  };
  for (const e of document.querySelectorAll('body *')) {
    if (!shown(e)) continue;
    const tag = e.tagName.toLowerCase();
    const role = e.getAttribute('role') || '';
    const type = tag === 'input' ? (e.getAttribute('type') || 'text').toLowerCase() : '';
    if (tag === 'select') counts.selects++;
    if (role === 'combobox') counts.comboboxes++;
    if (tag === 'input') {
      const hint = [e.getAttribute('placeholder'), e.getAttribute('aria-label'),
                    e.getAttribute('name')].join(' ');
      if (type === 'date' || /date|mm.?dd|dd.?mm|start|end|from/i.test(hint)) counts.date_inputs++;
      else if (type === 'checkbox') counts.checkboxes++;
      else if (type === 'radio') counts.radios++;
      else counts.other_inputs++;
    }
    if (role === 'listbox') counts.listboxes++;
    if (role === 'option' || tag === 'option') counts.options++;
    if (role === 'checkbox' || role === 'menuitemcheckbox') counts.checkboxes++;
    if (role === 'radio' || role === 'menuitemradio') counts.radios++;
    if (role === 'dialog' || tag === 'dialog') counts.dialogs++;
    if (role === 'menu') counts.menus++;
    if (e.children.length > 3) continue;
    const text = tag === 'input' ? '' : (e.innerText || '').trim().replace(/\s+/g, ' ');
    if (tag !== 'input' && tag !== 'select' && !role && (!text || text.length > 40)) continue;
    if (text.length > 40) continue;
    items.push({tag, role, type, text});
    if (items.length >= 600) break;
  }
  return {items, counts};
}"""


def _page_shape(page) -> dict:
    try:
        return page.evaluate(_SHAPE_JS) or {"items": [], "counts": {}}
    except Exception:
        return {"items": [], "counts": {}}


# The words a date filter is made of, which are the only words about a
# new element that may reach the file. Anything else is reported by its
# length. The file is attached to a public issue, and masking let a name,
# a street and a phone number through when a review tried it before
# 0.34.2, because masking removes what it recognizes and this keeps only
# what it recognizes.
RANGE_WORDS_RE = re.compile(
    r"^\s*(from|to|start(\s+date)?|end(\s+date)?|date(\s+range)?|cancel|close|"
    r"reset|clear|custom(\s+range)?|select(\s+a)?\s+(date|range|period)|"
    r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*)\s*$", re.I)


def _range_words(text: str) -> dict:
    """An element's text for the trace, only when it is a date filter's
    own word, and its length otherwise."""
    text = re.sub(r"\s+", " ", text or "").strip()
    if text and any(p.match(text) for p in (RANGE_OPTION_RE, RANGE_APPLY_RE,
                                            RANGE_OPENER_RE, RANGE_WORDS_RE)):
        return {"text": text[:40]}
    return {"text_len": min(len(text), 999)}


def _appeared(before: dict, after: dict) -> list:
    """The elements in `after` that `before` did not have."""
    def key(x):
        return (x.get("tag", ""), x.get("role", ""), x.get("type", ""), x.get("text", ""))
    had = {key(x) for x in before.get("items", [])}
    return [x for x in after.get("items", []) if key(x) not in had]


def _opener_state(el) -> dict:
    """What the opener says about itself, never its text beyond the label
    the allowlist already matched."""
    try:
        return el.evaluate(
            "e => ({tag: e.tagName.toLowerCase(), role: e.getAttribute('role') || '',"
            " expanded: e.getAttribute('aria-expanded') || '',"
            " haspopup: e.getAttribute('aria-haspopup') || '',"
            " controls: !!e.getAttribute('aria-controls')})") or {}
    except Exception:
        return {}


def _try_range_selects(page, iso_date: str, today, note: dict):
    """Choose the span in a plain select, through the shared filter.
    (True, year) when one was set, None otherwise."""
    try:
        # Through the shared filter, which refuses every dropdown on a page
        # that is not signed in and any whose surroundings name a payment
        # or a transfer. A dropdown whose options look like spans of time
        # is not reason enough to set it on a page nobody has confirmed.
        for sel, _identity in _safe_selects(page, FORBIDDEN_CONTROL_RE,
                                            signed_out=looks_signed_out,
                                            limit=6):
            labels = [re.sub(r"\s+", " ", t).strip() for t in
                      (sel.evaluate("s => Array.from(s.options).map(o => o.text)")
                       or [])]
            if not any(RANGE_OPTION_RE.match(t) for t in labels):
                continue
            label, year = _range_choice(labels, iso_date, today)
            note.update(kind="select", options=[redact(t)[:40] for t in labels][:12],
                        chose=redact(label or "")[:40])
            if label and is_range_control(label, RANGE_OPTION_RE):
                sel.select_option(label=label)
                page.wait_for_timeout(2500)
                return True, year
    except Exception as e:
        log.info("date range select: %s", e)
    return None


def widen_range(page, iso_date: str, trace: Optional[list] = None,
                today=None):
    """Open the history's date filter and choose a span that reaches
    `iso_date`. Returns (chose, anchor_year). chose is False when there
    was no filter or no option covering it, and the trace says which,
    with the options it saw, so a wrong guess costs one report and not
    a round of guessing."""
    note = {"note": "date range", "wanted": iso_date}

    def done(result):
        if trace is not None:
            trace.append(note)
        return result

    # A plain select first, since choosing in one clicks nothing.
    got = _try_range_selects(page, iso_date, today, note)
    if got:
        return done(got)

    opener = None
    for getter in (lambda: page.get_by_role("button", name=RANGE_OPENER_RE),
                   lambda: page.get_by_role("combobox", name=RANGE_OPENER_RE),
                   lambda: page.get_by_text(RANGE_OPENER_RE)):
        try:
            loc = getter()
            for i in range(min(loc.count(), 4)):
                el = loc.nth(i)
                text = (el.inner_text(timeout=500) or
                        el.get_attribute("aria-label") or "").strip()
                if is_range_control(text, RANGE_OPENER_RE) and el.is_visible():
                    opener = el
                    break
        except Exception:
            continue
        if opener is not None:
            break
    if opener is None:
        note["kind"] = "none found"
        return done((False, None))

    # The 0.34.1 file found the opener and then no option at all, with the
    # page's buttons unchanged (#26). Whether the menu opened, and what it
    # is made of, is written down this time.
    before = _page_shape(page)
    note["opener"] = _opener_state(opener)
    try:
        opener.click(timeout=4000)
        note["opener_click"] = "ok"
    except Exception as e:
        # A timed-out click may still have landed, so it is not pressed again.
        note["opener_click"] = type(e).__name__
        log.info("date range opener: %s", e)

    # The menu can open a moment after the click, so it is looked for a
    # few times, and the opener is never pressed again.
    options, kind, after = [], "menu", before
    for _ in range(6):
        page.wait_for_timeout(600)
        options = _range_options(page)
        if options:
            break
    after = _page_shape(page)
    appeared = _appeared(before, after)
    note["opener_after"] = _opener_state(opener).get("expanded", "")
    note["appeared_count"] = len(appeared)
    if not options:
        # A select that only exists once the opener is pressed.
        got = _try_range_selects(page, iso_date, today, note)
        if got:
            note["kind"] = "select after opener"
            return done(got)
    if not options:
        options = _range_texts(page, {x.get("text", "") for x in appeared})
        kind = "text"
    labels = [t for _, t in options]
    label, year = _range_choice(labels, iso_date, today)
    note.update(kind=kind, options=[redact(t)[:40] for t in labels][:12],
                chose=redact(label or "")[:40])
    if not label:
        note["appeared"] = [
            {"tag": x.get("tag", ""), "role": x.get("role", ""),
             "type": x.get("type", ""), **_range_words(x.get("text", ""))}
            for x in appeared[:20]]
        note["counts_before"] = before.get("counts", {})
        note["counts_after"] = after.get("counts", {})
        note["buttons"] = _buttons_seen(page)
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        return done((False, None))
    el = next(e for e, t in options if t == label)
    try:
        el.click(timeout=4000)
        page.wait_for_timeout(1200)
        for role in ("button", "link"):
            loc = page.get_by_role(role, name=RANGE_APPLY_RE)
            if loc.count() and loc.first.is_visible():
                text = (loc.first.inner_text(timeout=500) or "").strip()
                if is_range_control(text, RANGE_APPLY_RE):
                    loc.first.click(timeout=4000)
                    note["applied"] = True
                    break
        page.wait_for_timeout(2500)
    except Exception as e:
        log.info("date range option: %s", e)
    return done((True, year))


def _buttons_seen(page, limit: int = 12) -> list:
    """The visible text of the page's buttons, digits masked, for a trace
    that has to explain why nothing matched."""
    out = []
    try:
        loc = page.get_by_role("button")
        for i in range(min(loc.count(), 80)):
            try:
                text = (loc.nth(i).inner_text(timeout=300) or "").strip()
            except Exception:
                continue
            if text:
                out.append(redact(text).replace("\n", " / ")[:60])
            if len(out) >= limit:
                break
    except Exception:
        pass
    return out


def _pdf_button(page):
    """The "Download PDF" or "View/print PDF" button on the page, once it
    has passed the guard, or None."""
    for pat in (re.compile(r"^\s*download\s+pdf\s*$", re.I), PDF_BUTTON_RE):
        try:
            loc = page.get_by_role("button", name=pat).or_(page.get_by_role("link", name=pat))
            for i in range(min(loc.count(), 6)):
                el = loc.nth(i)
                label = (el.inner_text(timeout=800) or el.get_attribute("aria-label") or "").strip()
                if is_safe_control(label) and el.is_visible():
                    return el, label
        except Exception:
            continue
    return None, ""


_SECOND_STEP_RE = re.compile(
    r"^\s*(download|download\s+(pdf|bill|now)|save|save\s+(as\s+)?pdf|pdf|full\s+bill|"
    r"(regular|standard|full|detailed|accessibility)\s+pdf|"
    r"bill\s+pdf|view\s*/\s*print\s+pdf|print|ok|continue|get\s+(my\s+)?bill)\s*$", re.I)

_VIEWER_JS = r"""() => {
  const out = [];
  for (const e of document.querySelectorAll("iframe, embed, object")) {
    const src = e.getAttribute("src") || e.getAttribute("data") || "";
    if (src) out.push(src.slice(0, 300));
  }
  return out;
}"""


_REGULAR_PDF_RE = re.compile(r"^\s*regular\s+pdf\s*$", re.I)
_VIEW_PRINT_RE = re.compile(r"^\s*view\s*/\s*print\s+pdf\s*$", re.I)

# Every element whose own text says PDF, with what it is and whether it
# can be seen. The menu under "Download PDF" is made of elements that are
# not buttons, links or menuitems, which is why round seven saw nothing.
_PDF_TEXTS_JS = r"""() => {
  const out = [];
  const seen = new Set();
  for (const e of document.querySelectorAll('body *')) {
    if (e.children.length > 3) continue;
    const t = (e.innerText || '').trim().replace(/\s+/g, ' ');
    if (!t || t.length > 60 || !/pdf/i.test(t)) continue;
    const key = e.tagName + '|' + t;
    if (seen.has(key)) continue;
    seen.add(key);
    const r = e.getBoundingClientRect();
    const cs = getComputedStyle(e);
    const visible = r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none';
    out.push({text: t, tag: e.tagName.toLowerCase(), role: e.getAttribute('role') || '',
              cls: (e.className || '').toString().slice(0, 40), visible});
    if (out.length >= 25) break;
  }
  return out;
}"""


def _pdf_texts(page) -> list:
    try:
        return page.evaluate(_PDF_TEXTS_JS) or []
    except Exception:
        return []


def _menu_entry(page, pat, wait_ms: int = 4000):
    """A visible element whose whole text matches `pat`, found by text so
    the element's kind does not matter, waited for up to `wait_ms` since a
    menu opens a moment after the click. Guard checked. None if absent."""
    deadline = wait_ms
    while True:
        try:
            loc = page.get_by_text(pat)
            for i in range(min(loc.count(), 6)):
                el = loc.nth(i)
                try:
                    text = re.sub(r"\s+", " ", (el.inner_text(timeout=500) or "")).strip()
                except Exception:
                    continue
                if pat.match(text) and is_safe_control(text) and el.is_visible():
                    return el, text
        except Exception:
            pass
        if deadline <= 0:
            return None, ""
        page.wait_for_timeout(500)
        deadline -= 500


def _second_step(page, appeared: set):
    """A control the click revealed whose text says it finishes a download,
    once it has passed the guard, or None. The choosing is the core's, the
    words this provider uses and the guard are this app's."""
    return _core_second_step(page, appeared, _SECOND_STEP_RE, is_safe_control)


def _take_viewer(page, out_path: Path, trace: Optional[list]) -> bool:
    """A PDF the click put into an embedded viewer on the page, read from
    the viewer's source. A blob: source is read through the page, any
    other is host checked first."""
    try:
        srcs = page.evaluate(_VIEWER_JS) or []
    except Exception:
        srcs = []
    if trace is not None and srcs:
        trace.append({"note": "embedded viewers after the click", "sources": [redact(x)[:120] for x in srcs[:5]]})
    for src in srcs:
        try:
            if src.startswith("blob:") or is_safe_url(src):
                b64 = _fetch_as_b64(page, src)
                if b64:
                    data = base64.b64decode(b64)
                    if data[:5] == b"%PDF-":
                        out_path.write_bytes(data)
                        return True
        except Exception as e:
            log.info("viewer read failed: %s", e)
    return False


def _view_print_button(page):
    """The "View/print PDF" button, once it has passed the guard, or None."""
    pat = re.compile(r"^\s*view\s*/\s*print\s+pdf\s*$", re.I)
    try:
        loc = page.get_by_role("button", name=pat).or_(page.get_by_role("link", name=pat))
        for i in range(min(loc.count(), 4)):
            el = loc.nth(i)
            label = (el.inner_text(timeout=800) or el.get_attribute("aria-label") or "").strip()
            if is_safe_control(label) and el.is_visible():
                return el, label
    except Exception:
        pass
    return None, ""


def _catch_pdf(page, el, label: str, out_path: Path, trace: Optional[list] = None,
               dl_dir=None) -> bool:
    """Click `el` and save whatever PDF the site produces, a file landing
    in `dl_dir`, a download event, a PDF response in this tab, a new tab,
    an embedded viewer, or a second control the click revealed. `trace`
    collects what happened, the click's own outcome included, so a failed
    attempt says which of those it was not."""
    ctx = page.context
    got: dict = {}
    downloads: list = []

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
                body = res.body()
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
        if got:
            out_path.write_bytes(got["body"])
            return True
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
            log.info("click on %r failed: %s", label, str(e)[:120])
            if trace is not None:
                trace.append({"note": "click failed", "control": redact(label)[:60], "error": str(e)[:160]})
            try:
                el.evaluate("el => el.click()")
                if trace is not None:
                    trace.append({"note": "clicked through the DOM instead", "control": redact(label)[:60]})
            except Exception as e2:
                if trace is not None:
                    trace.append({"note": "DOM click failed too", "error": str(e2)[:160]})
        if wait_for_pdf(12):
            return True
        # What did the click change? A menu or a dialog with the real
        # download control, a viewer with the PDF in it, or nothing.
        appeared = _control_texts(page) - controls_before
        pdf_texts = _pdf_texts(page)
        if trace is not None:
            trace.append({"note": "after the click", "url": redact(page.url or "")[:160],
                          "appeared": [redact(t) for t in sorted(appeared)[:15]],
                          "pdf_texts": [{**x, "text": redact(x["text"])} for x in pdf_texts],
                          "new_tabs": len([p for p in ctx.pages if p not in before])})
        if _take_viewer(page, out_path, trace):
            return True
        if _take_new_tab(page, [p for p in ctx.pages if p not in before], out_path):
            return True
        # The menu under "Download PDF" holds "Regular PDF", which saves
        # the file, and "View/print PDF", which opens a tab. Found by text.
        step, step_label = _menu_entry(page, _REGULAR_PDF_RE)
        if step is None:
            step, step_label = _second_step(page, appeared)
        if step is None:
            step, step_label = _menu_entry(page, _VIEW_PRINT_RE, wait_ms=1000)
        if step is None and trace is not None:
            trace.append({"note": "no menu entry found after the click",
                          "pdf_texts_now": [{**x, "text": redact(x["text"])} for x in _pdf_texts(page)]})
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
            if _take_viewer(page, out_path, trace) or \
                    _take_new_tab(page, [p for p in ctx.pages if p not in before], out_path):
                return True
        if wait_for_pdf(15):
            return True
        if _take_new_tab(page, [p for p in ctx.pages if p not in before], out_path):
            return True
        log.info("click on %r produced no PDF", label)
        return False
    finally:
        for name, fn in (("response", on_response),):
            try:
                ctx.remove_listener(name, fn)
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


def download_bill(page, dl_dir, iso_date: str, out_path, hint: str = "",
                  trace: Optional[list] = None) -> bool:
    """Save the bill whose period ends on `iso_date`. The history page's
    button for that bill is clicked, which shows the bill, then the
    "Download PDF" it reveals, and whatever arrives is caught. When the
    history has no button for it (the current bill lives on the billing
    center), the billing center's own "Download PDF" is used, provided the
    bill shown there carries this date. Nothing else is ever clicked.

    `dl_dir` is where the attached browser saves a download, watched
    after every click."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if goto_history(page):
        el, label = _bill_button_for(page, iso_date)
        if el is None:
            # Older than the history shows by default. The tester's four
            # failures on each account were all of these (#26).
            chose, anchor = widen_range(page, iso_date, trace)
            if chose:
                el, label = _bill_button_for(page, iso_date, anchor)
        if el is not None and is_safe_control(label):
            try:
                el.scroll_into_view_if_needed(timeout=4000)
                el.click(timeout=5000)
                page.wait_for_timeout(2000)
                dismiss_overlay(page)
            except Exception as e:
                log.info("bill button click failed for %s: %s", iso_date, e)
            # The bill opens in place or on its own page, and its Download
            # PDF may take a moment to appear.
            btn, blabel = None, ""
            for _ in range(10):
                btn, blabel = _pdf_button(page)
                if btn is not None:
                    break
                page.wait_for_timeout(1000)
            if btn is not None:
                if _catch_pdf(page, btn, blabel, out_path, trace, dl_dir):
                    return True
                # Download PDF gave nothing. View/print PDF is the other
                # control the survey saw, and it may open the PDF in a tab.
                alt, alabel = _view_print_button(page)
                if alt is not None and alabel.lower() != blabel.lower():
                    if _catch_pdf(page, alt, alabel, out_path, trace, dl_dir):
                        return True
            else:
                log.info("no Download PDF after opening the bill for %s", iso_date)
                if trace is not None:
                    trace.append({"note": "no Download PDF button after the bill button",
                                  "url": redact(page.url or "")[:160],
                                  "buttons": _buttons_seen(page)})
        else:
            log.info("no bill button for %s on the history page", iso_date)
            if trace is not None:
                trace.append({"note": "no bill button for this date on the history page",
                              "wanted": iso_date, "period_buttons": _period_buttons(page).count(),
                              "buttons": _buttons_seen(page)})

    # The current bill, on the billing center, which is a page of its
    # own and has to be opened as one. The history page passes the
    # billing check too, which is how round three looked for the button
    # there and never here.
    try:
        page.goto(BILLING_CANDIDATES[0], wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(4000)
    except Exception as e:
        log.info("could not open the billing center for %s: %s", iso_date, e)
        return False
    if looks_signed_out(page) or not is_safe_url(page.url or ""):
        return False
    dismiss_overlay(page)
    try:
        body = page.locator("body").inner_text(timeout=5000)
    except Exception:
        body = ""
    shown = set()
    for m in re.finditer(r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}", body, re.I):
        iso = parse_date(m.group(0))
        if iso:
            shown.add(iso)
    btn, blabel = _pdf_button(page)
    if btn is None:
        log.info("no Download PDF on the billing center for %s", iso_date)
        if trace is not None:
            trace.append({"note": "no Download PDF on the billing center",
                          "url": redact(page.url or "")[:160], "buttons": _buttons_seen(page)})
        return False
    if shown and iso_date not in shown:
        log.info("the billing center shows %s, not %s, so its PDF is not this bill",
                 sorted(shown)[-1], iso_date)
        if trace is not None:
            trace.append({"note": "billing center shows other dates", "dates": sorted(shown)[-3:]})
        return False
    return _catch_pdf(page, btn, blabel, out_path, trace, dl_dir)


# ---------------------------------------------------------------------------
# Diagnose. A survey a tester can attach to an issue. No screenshot, since a
# billing page shows names, numbers and amounts. Digit runs are masked and
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
    r"^\s*((see|view|show)\s+)?(bill(ing)?\s+)?(history|bills|statements|past\s+bills|"
    r"previous\s+bills|documents|billing|bill\s*&\s*payments?|view\s+bill)\s*$", re.I)


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
    """What the signed-in billing area looks like, without downloading
    anything. Records each page, its headings and controls with the
    guard's verdict on each, and every JSON or PDF response att.com sends
    while the page settles. Then follows, one at a time and back again,
    the few links whose text is a billing word. No screenshot."""
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
                    "^" + re.escape(c["text"].replace("#", "")) + "$", re.I)).first
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
ALLOWED_HOSTS = {"att.com"}


def is_safe_url(url: str) -> bool:
    """True only for an https URL on one of this provider's own hosts.

    The check itself lives in the core, so all of them answer the same way.
    This app keeps the hosts, which is the part that really is its own."""
    return _host_allows(url, ALLOWED_HOSTS)
