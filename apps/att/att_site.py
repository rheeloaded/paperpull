"""ALL att.com selectors, URLs, and page behavior live here.

When AT&T changes its site, repair this file only.

STATUS: UNVERIFIED, round three. Written without an AT&T account and
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

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from paperpull_core.controls import SETTINGS_CONTROL_RE, AUTH_CONTROL_RE

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
    (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"), "iso"),
]
_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
MONTH_YEAR_RE = re.compile(
    r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
    r"Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    r"\s+(\d{4})", re.I)
YEAR_RE = re.compile(r"\b(19|20)(\d{2})\b")
_LAST_DAY = {1: 31, 2: 28, 3: 31, 4: 30, 5: 31, 6: 30,
             7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31}
_MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July",
                "August", "September", "October", "November", "December"]
_ID_RE = re.compile(r"\d{6,}")


def _last_day(year: int, month: int) -> int:
    if month == 2 and (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)):
        return 29
    return _LAST_DAY[month]


def parse_date(text: str) -> Optional[str]:
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
                return f"{2000 + int(m.group(3)):04d}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
            if kind == "iso":
                return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        except (KeyError, ValueError):
            continue
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


def _human_date(iso: str) -> str:
    try:
        y, m, d = iso.split("-")
        return f"{_MONTH_NAMES[int(m) - 1]} {int(d)}, {y}"
    except Exception:
        return iso


_QUERY_RE = re.compile(r"(https?://[^\s\"'?#]+)\?[^\s\"'#]*")


def redact(text: str) -> str:
    """Runs of six or more digits become #, so an account or phone number
    in a URL, a heading or a link never reaches the survey file, and a URL
    loses its query string, which is where a site keeps session details
    the survey has no use for."""
    text = _QUERY_RE.sub(lambda m: m.group(1) + "?...", text or "")
    return _ID_RE.sub(lambda m: "#" * len(m.group(0)), text)


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


def _bill_controls(page):
    """Every control on the page whose name says it fetches a bill, as a
    button or a link. The row it sits in supplies the date."""
    return page.get_by_role("button", name=BILL_CONTROL_RE).or_(
        page.get_by_role("link", name=BILL_CONTROL_RE))


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
        for _ in range(20):
            page.wait_for_timeout(500)
            if capture:
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
            docs.append(RawDoc(title=f"Monthly Statement - {disp}", date_text=b["date"],
                               href=b["hint"], text=f"AT&T Bill {disp}", kind="statement"))
        if docs:
            return docs
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
        iso = parse_date(name)
        if not iso:
            try:
                row_text = el.evaluate(_ROW_OF_JS) or ""
            except Exception:
                row_text = ""
            iso = parse_date(row_text)
        if not iso or iso in seen:
            continue
        seen.add(iso)
        disp = _human_date(iso)
        docs.append(RawDoc(title=f"Monthly Statement - {disp}", date_text=iso,
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
    """A PDF link fetched from inside the signed-in page, cookies and all,
    only on att.com. None unless the answer is a PDF."""
    if not is_safe_url(href):
        return None
    try:
        resp = page.context.request.get(href, timeout=60000)
        body = resp.body() if resp.ok else b""
    except Exception as e:
        log.info("fetch %s failed: %s", redact(href)[:80], e)
        return None
    return body if body[:5] == b"%PDF-" else None


def _bill_button_for(page, iso_date: str):
    """The history page's button for the bill whose period ends on
    `iso_date`, matched on "Mon d" since the buttons carry no year, or
    None. Two bills a year apart share the text, so the first match
    walking newest to oldest is taken for the newer date."""
    try:
        y, m, d = iso_date.split("-")
        want = f"{_MONTH_NAMES[int(m) - 1][:3]} {int(d)}"
        loc = page.get_by_role("button", name=BILL_BUTTON_RE)
        for i in range(min(loc.count(), 60)):
            el = loc.nth(i)
            text = (el.inner_text(timeout=800) or "").strip()
            pm = _PERIOD_RE.search(text)
            if pm and f"{pm.group(3)[:3].title()} {int(pm.group(4))}" == want:
                return el, text
    except Exception as e:
        log.info("bill button lookup failed: %s", e)
    return None, ""


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


def _catch_pdf(page, el, label: str, out_path: Path, trace: Optional[list] = None) -> bool:
    """Click `el` and save whatever PDF the site produces, a download
    event, a PDF response in this tab, or a new tab. `trace` collects the
    att.com JSON and PDF responses seen meanwhile, URL cut at the query,
    so a failed attempt tells the next round what the button called."""
    ctx = page.context
    got: dict = {}

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
    before = set(ctx.pages)
    try:
        try:
            el.scroll_into_view_if_needed(timeout=4000)
        except Exception:
            pass
        try:
            with page.expect_download(timeout=20000) as dl:
                el.click()
            from paperpull_core.receipt_pdf import save_download
            save_download(dl.value, out_path)
            if out_path.stat().st_size > 0 and out_path.read_bytes()[:5] == b"%PDF-":
                return True
        except Exception:
            pass
        deadline = 30
        while not got and deadline > 0:
            page.wait_for_timeout(1000)
            deadline -= 1
        if got:
            out_path.write_bytes(got["body"])
            return True
        log.info("click on %r produced no PDF", label)
        return False
    finally:
        try:
            ctx.remove_listener("response", on_response)
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

    `dl_dir` is unused, kept for parity with the shared orchestrator."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if goto_history(page):
        el, label = _bill_button_for(page, iso_date)
        if el is not None and is_safe_control(label):
            try:
                el.scroll_into_view_if_needed(timeout=4000)
                el.click(timeout=5000)
                page.wait_for_timeout(3000)
                dismiss_overlay(page)
            except Exception as e:
                log.info("bill button click failed for %s: %s", iso_date, e)
            btn, blabel = _pdf_button(page)
            if btn is not None:
                if _catch_pdf(page, btn, blabel, out_path, trace):
                    return True
            else:
                log.info("no Download PDF after opening the bill for %s", iso_date)
                if trace is not None:
                    trace.append({"note": "no Download PDF button after the bill button",
                                  "url": redact(page.url or "")[:160]})

    # The current bill, on the billing center.
    if not goto_documents(page):
        log.info("could not open the billing center for %s", iso_date)
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
        return False
    if shown and iso_date not in shown:
        log.info("the billing center shows %s, not %s, so its PDF is not this bill",
                 sorted(shown)[-1], iso_date)
        if trace is not None:
            trace.append({"note": "billing center shows other dates", "dates": sorted(shown)[-3:]})
        return False
    return _catch_pdf(page, btn, blabel, out_path, trace)


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
    return docs


def _shape(obj, depth=0):
    """The shape of a JSON body, never its values."""
    if depth > 3:
        return "..."
    if isinstance(obj, dict):
        return {k: _shape(v, depth + 1) for k, v in list(obj.items())[:25]}
    if isinstance(obj, list):
        return ["list of %d" % len(obj), _shape(obj[0], depth + 1) if obj else None]
    return type(obj).__name__


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
                link.click(timeout=5000)
                page.wait_for_timeout(dwell_ms)
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
    """True only for an https URL on one of this provider's own hosts."""
    from urllib.parse import urlparse
    try:
        got = urlparse(url or "")
    except ValueError:
        return False
    if got.scheme != "https" or not got.hostname:
        return False
    if got.username or got.password:
        return False
    host = got.hostname.lower().rstrip(".")
    return any(host == h or host.endswith("." + h) for h in ALLOWED_HOSTS)
