"""ALL Target Circle Card (RedCard credit) selectors, URLs, and page behavior
live here. When the portal changes, repair this file only.

SAFETY (this is a credit-card account serviced by TD Bank USA):
  This module is strictly READ-ONLY. It opens the Statements area, reads the
  list of billing statements, and downloads the statement PDFs TD already
  generated. It must NEVER activate any control that makes a payment, sets up
  autopay/paperless, transfers a balance, redeems rewards, or changes any
  account setting. FORBIDDEN_CONTROL_RE is the guard; a control must ALSO look
  like a document action (SAFE_DOC_CONTROL_RE) before it may be clicked. There
  is no code here that submits a form or confirms a dialog.

Mechanism (verified 2026-08 against the live signed-in portal):
  The RedCard credit account is serviced by TD Bank through the "Manage my
  Target Circle Card" portal (rcam.target.com -> mytargetcirclecard.target.com,
  TD's "eCustomer Service" platform). Statements live at BASE/statements as a
  single <table>: columns Date (MM-DD-YYYY) | Document type | balances |
  Payment due date | "Download pdf" | "View". A year switcher (role=button
  "2025", "2024", ...) reloads the table for that year. Each row's "Download
  pdf" link fires a real browser download event (filename YYYYMMDD.pdf) that
  Playwright's expect_download captures directly - no CDP download plumbing.
  The portal's session survives page.goto (a server-side cookie session, unlike
  the Amex SPA it was cloned from), so navigation is by URL.
"""
# Site layer verified working against the live site: 2026-08
from __future__ import annotations

import html as _html
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

log = logging.getLogger("redcard_docs.site")

BASE = "https://mytargetcirclecard.target.com"
STATEMENTS_URL = f"{BASE}/statements"
URLS = {
    "home": f"{BASE}/home",
    # rcam.target.com is Target's friendly entry; it 302s to the login page.
    "login": "https://rcam.target.com/",
    "dashboard": f"{BASE}/home",
    "statements": STATEMENTS_URL,
    "documents": STATEMENTS_URL,
}
DOCUMENT_URL_CANDIDATES = [STATEMENTS_URL]

LOGIN_URL_MARKERS = ["/login", "/logon", "/signin", "/sign-in", "/auth",
                     "/mfa", "/verification", "/challenge"]

# ---------------------------------------------------------------------------
# HARD SAFETY GUARD - never click anything matching this. Tuned for a credit
# card servicing portal: never pay, autopay, transfer a balance, or change the
# account. (Year switching is clicked directly by its 4-digit label, not routed
# through this guard.)
# ---------------------------------------------------------------------------
FORBIDDEN_CONTROL_RE = re.compile(
    r"(pay\b|payment|make\s+a\s+payment|pay\s+bill|autopay|auto\s*pay|"
    r"schedule\s+payment|one[-\s]?time\s+payment|payment\s+plan|"
    r"transfer\b|balance\s+transfer|cash\s+advance|cash\s*back|"
    r"withdraw|deposit|move\s+money|\bsend\b|\bwire\b|"
    r"redeem|reward|redemption|\bpoints\b|"
    r"bank\b|routing|account\s+number|debit|add\s+card|link\s+bank|wallet|"
    r"\bapply\b|enroll|unenroll|sign\s+up|paperless|delivery\s+options|upgrade|"
    r"book\s+travel|\btravel\b|dispute|report\s+lost|lost\s+card|lock\s+card|"
    r"freeze|\bcard\b|\baccount\b|"
    r"enable|disable|activate|deactivate|change\b|edit\b|update\b|modify|"
    r"set\s+up|delete|remove|cancel|close\s+account|"
    r"password|profile\b|settings|preferences|\bmanage\b|"
    r"confirm|continue|submit|agree|accept|authorize)", re.I)

SAFE_DOC_CONTROL_RE = re.compile(
    r"(download|view|open|print|pdf|statement|document|e?statement|"
    r"summary|year.?end)", re.I)

SECURITY_CHALLENGE_MARKERS = [
    "enter the code", "verification code", "6-digit", "one-time passcode",
    "one time passcode", "two-factor", "two-step", "authenticator",
    "confirm your identity", "verify your identity", "we sent a code",
    "security code", "unusual", "are you a robot", "captcha", "let's verify",
    "check your email", "check your phone", "your session has expired",
    "session has timed out", "log back in", "sign back in",
]

RATE_LIMIT_MARKERS = [
    "too many requests", "rate limit", "try again later",
    "temporarily unavailable", "http error 429", "unusual traffic",
]

# ---------------------------------------------------------------------------
# Fallback selectors (used by --diagnose only)
# ---------------------------------------------------------------------------
FALLBACK = {
    "doc_row": "table tr, [role='row']",
    "doc_link": ("a[aria-label*='Download PDF' i], a[aria-label*='download pdf' i], "
                 "a[href$='.pdf']"),
    "download_control": "a[aria-label*='Download PDF' i]",
    "page_ready": "table, [role='table'], main, [role='main']",
    "next_page": ("a[aria-label*='Next' i], button[aria-label*='Next' i], "
                  "[class*='next']"),
}

# ---------------------------------------------------------------------------
# Date parsing (shared with the other projects)
# ---------------------------------------------------------------------------
DATE_PATTERNS = [
    (re.compile(r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
                r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|"
                r"Dec(?:ember)?)\.?\s+(\d{1,2}),?\s+(\d{4})", re.I), "mdY"),
    (re.compile(r"\b(\d{1,2})-(\d{1,2})-(\d{4})\b"), "mdy_dash"),
    (re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b"), "mdy_slash"),
    (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"), "iso"),
]
_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
MONTH_YEAR_RE = re.compile(
    r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
    r"Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    r"\s+(\d{4})", re.I)
QUARTER_RE = re.compile(r"\bQ([1-4])\s*[' ]?\s*(\d{4})\b", re.I)
YEAR_RE = re.compile(r"\b(19|20)(\d{2})\b")
YEAR_ONLY_RE = re.compile(r"^20\d\d$")
_MDY_DASH_RE = re.compile(r"\b(\d{2})-(\d{2})-(\d{4})\b")   # MM-DD-YYYY
_LAST_DAY = {1: 31, 2: 28, 3: 31, 4: 30, 5: 31, 6: 30,
             7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31}

_MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July",
                "August", "September", "October", "November", "December"]


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
            if kind in ("mdy_dash", "mdy_slash"):
                return f"{int(m.group(3)):04d}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
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


def _iso_from_mdy(text: str) -> Optional[str]:
    """'MM-DD-YYYY' (the table's date format) -> 'YYYY-MM-DD'."""
    m = _MDY_DASH_RE.search(text or "")
    if not m:
        return None
    return f"{m.group(3)}-{m.group(1)}-{m.group(2)}"


def _mdy_from_iso(iso: str) -> str:
    """'YYYY-MM-DD' -> 'MM-DD-YYYY' (to match the table cell text)."""
    try:
        y, m, d = iso.split("-")
        return f"{m}-{d}-{y}"
    except Exception:
        return iso


def _human_date(iso: str) -> str:
    try:
        y, m, d = iso.split("-")
        return f"{_MONTH_NAMES[int(m) - 1]} {int(d)}, {y}"
    except Exception:
        return iso


# ---------------------------------------------------------------------------
# Session / safety
# ---------------------------------------------------------------------------

def looks_signed_out(page) -> bool:
    url = (page.url or "").lower()
    if any(m in url for m in LOGIN_URL_MARKERS):
        return True
    if "rcam.target.com" in url:
        return True
    try:
        if page.locator("input[type='password']").count() > 0:
            return True
    except Exception:
        pass
    return False


def detect_security_challenge(page) -> Optional[str]:
    try:
        if page.locator("table tr").count() > 1:
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
    # The shared core guard is consulted as well as this app's own blocklist.
    # A repo-wide review found each app had drifted its own way and every one
    # of them let settings controls through ("Save Changes", "Document
    # Removal", "Turn off"). Centralising it means the next gap is fixed once
    # rather than nineteen times.
    try:
        from paperpull_core.controls import SETTINGS_CONTROL_RE, AUTH_CONTROL_RE
        if SETTINGS_CONTROL_RE.search(name) or AUTH_CONTROL_RE.search(name):
            return False
    except Exception:
        pass
    return bool(SAFE_DOC_CONTROL_RE.search(name))


# ---------------------------------------------------------------------------
# Statements page
# ---------------------------------------------------------------------------

def goto_documents(page) -> bool:
    """Open the Statements page and confirm its table renders. The portal's
    session survives a hard navigation, so page.goto is safe here."""
    try:
        if "/statements" not in (page.url or ""):
            page.goto(STATEMENTS_URL, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3500)
        if looks_signed_out(page):
            return False
        try:
            page.wait_for_selector("table tr", timeout=15000)
        except Exception:
            pass
        page.wait_for_timeout(500)
        return page.locator("table tr").count() > 1
    except Exception as e:
        log.info("goto_documents failed: %s", e)
        return page.locator("table tr").count() > 1


def scroll_full_page(page, rounds: int = 6, delay_ms: int = 500) -> None:
    try:
        for _ in range(rounds):
            page.mouse.wheel(0, 3000)
            page.wait_for_timeout(delay_ms)
        page.keyboard.press("End")
        page.wait_for_timeout(delay_ms)
    except Exception:
        pass


def expand_all(page) -> None:
    """No lazy 'show more' on this table (it paginates by year, handled in
    collect_download_docs). Kept for the shared --diagnose path."""
    return None


def _row_dates(page) -> List[str]:
    """ISO dates of the statements in the table currently shown (one year)."""
    try:
        cells = page.evaluate(
            "() => [...document.querySelectorAll('table tr')]"
            ".map(tr => { const c = tr.querySelector('td,th');"
            " return c ? (c.innerText||'').trim() : ''; })")
    except Exception:
        cells = []
    out = []
    for t in cells:
        iso = _iso_from_mdy(t)
        if iso:
            out.append(iso)
    return out


def _year_buttons(page) -> List[str]:
    """The 4-digit year labels that are clickable buttons (the non-active
    years). The active year has no button - its rows are already shown."""
    years = []
    try:
        loc = page.get_by_role("button", name=YEAR_ONLY_RE)
        for i in range(loc.count()):
            try:
                t = (loc.nth(i).inner_text(timeout=500) or "").strip()
            except Exception:
                t = ""
            if YEAR_ONLY_RE.match(t):
                years.append(t)
    except Exception:
        pass
    # de-dup, newest first
    return sorted(set(years), reverse=True)


def _select_year(page, year: str) -> bool:
    """Click the year switcher for `year`; return whether the table changed to
    show that year."""
    btn = page.get_by_role("button", name=re.compile(rf"^{year}$"))
    if btn.count() == 0:
        # already the active year?
        return any(d.startswith(year) for d in _row_dates(page))
    try:
        btn.first.scroll_into_view_if_needed(timeout=3000)
        btn.first.click()
        for _ in range(20):                    # up to ~5s for the table to swap
            page.wait_for_timeout(250)
            if any(d.startswith(year) for d in _row_dates(page)):
                return True
        return any(d.startswith(year) for d in _row_dates(page))
    except Exception as e:
        log.info("year %s click failed: %s", year, e)
        return False


@dataclass
class RawDoc:
    title: str
    account: str = ""
    date_text: str = ""
    href: str = ""
    text: str = ""
    row_index: int = -1
    kind: str = "doc"


def collect_download_docs(page) -> List[RawDoc]:
    """Read every billing statement across all available years. The table shows
    one year at a time; harvest the current (latest) year, then click each
    past-year button and harvest again."""
    if "/statements" not in (page.url or ""):
        goto_documents(page)
    docs: List[RawDoc] = []
    seen = set()

    def harvest():
        for iso in _row_dates(page):
            if iso in seen:
                continue
            seen.add(iso)
            disp = _human_date(iso)
            docs.append(RawDoc(title=f"Statement - {disp}", date_text=iso,
                               href="", text=f"Target Circle Card statement {disp}",
                               kind="statement"))

    harvest()                                  # current (latest) year
    for year in _year_buttons(page):           # each past year
        if _select_year(page, year):
            harvest()
    return docs


def _row_download_link(page, mdy: str):
    """The 'Download pdf' link in the table row whose date cell == `mdy`
    (MM-DD-YYYY). Returns a Playwright locator or None."""
    rows = page.locator("table tr")
    for i in range(rows.count()):
        row = rows.nth(i)
        try:
            first = (row.locator("td, th").first.inner_text(timeout=600) or "").strip()
        except Exception:
            continue
        if first != mdy:
            continue
        lk = row.get_by_role("link", name=re.compile(r"download\s*pdf", re.I))
        if lk.count() == 0:
            lk = row.locator("a[aria-label*='Download PDF' i], a[aria-label*='download pdf' i]")
        if lk.count() > 0:
            return lk.first
    return None


def _attempt_download(page, iso_date: str, out_path) -> Optional[bool]:
    """One download attempt on the current page. Returns True on success, False
    if the statement row/link can't be found, or None if we can't even reach a
    signed-in Statements page (caller should reload / re-check the session)."""
    if "/statements" not in (page.url or ""):
        if not goto_documents(page):
            return None
    if looks_signed_out(page):
        return None

    year = (iso_date or "")[:4]
    if year and not any(d.startswith(year) for d in _row_dates(page)):
        if not _select_year(page, year):
            log.info("could not select year %s for %s", year, iso_date)
            return False

    mdy = _mdy_from_iso(iso_date)
    link = _row_download_link(page, mdy)
    if link is None:
        log.info("statement row not found for %s (%s)", iso_date, mdy)
        return False

    # Safety. This used to read is_safe_control("Download PDF statement") with
    # that string hardcoded, which always returned True and therefore gated
    # nothing at all. The control's REAL label is checked now.
    #
    # The portal's own aria-label is a buggy un-interpolated template
    # ("{{...}}"), so when that is what comes back there is no label to judge.
    # In that case the element still has to be the row's dedicated download
    # link, which is how _row_download_link found it, and that is stated here
    # rather than hidden behind a constant that looked like a check.
    label = ""
    for how in ("inner_text", "get_attribute"):
        try:
            label = (link.inner_text(timeout=1500) if how == "inner_text"
                     else link.get_attribute("aria-label")) or ""
            label = label.strip()
            if label:
                break
        except Exception:
            label = ""
    templated = ("{{" in label) or ("}}" in label)
    if label and not templated and not is_safe_control(label):
        log.error("refusing a control labelled %r", label[:60])
        return False

    from receipt_pdf import save_download
    try:
        link.scroll_into_view_if_needed(timeout=4000)
    except Exception:
        pass
    with page.expect_download(timeout=45000) as dl:
        link.click()
    save_download(dl.value, out_path)
    return True


def download_document(page, category, iso_date: str, out_path) -> bool:
    """Download the billing statement dated `iso_date`. Selects that statement's
    year in the switcher, finds its table row, and clicks the row's 'Download
    pdf' link, capturing the real download event. `category` is unused (every
    document here is a Statement).

    TD's portal session is short-lived: when it expires the SPA keeps showing a
    cached statements table, but download clicks silently do nothing. So if the
    first attempt fails, hard-navigate to the Statements URL (which redirects to
    the auth page if the session is truly dead, letting looks_signed_out catch
    it) and retry once."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        r = _attempt_download(page, iso_date, out_path)
        if r:
            return True
    except Exception as e:
        log.info("download attempt 1 failed for %s: %s", iso_date, e)

    # Re-sync: a fresh navigation refreshes any stale download token and surfaces
    # an expired session as a redirect to the auth page.
    try:
        page.goto(STATEMENTS_URL, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(3000)
        if looks_signed_out(page):
            log.info("session expired while downloading %s (needs re-login)", iso_date)
            return False
        return bool(_attempt_download(page, iso_date, out_path))
    except Exception as e:
        log.info("download click failed for %s: %s", iso_date, e)
        return False


# ---------------------------------------------------------------------------
# Diagnose-only helper (loose row scrape; no downloads)
# ---------------------------------------------------------------------------
def collect_documents(page) -> List[RawDoc]:
    docs: List[RawDoc] = []
    seen = set()
    try:
        rows = page.evaluate(
            "() => [...document.querySelectorAll('table tr')].map(tr => ({"
            " text: (tr.innerText||'').replace(/\\s+/g,' ').trim() }))")
    except Exception:
        rows = []
    for i, r in enumerate(rows):
        text = (r.get("text") or "").strip()
        iso = _iso_from_mdy(text)
        if not iso:
            continue
        if iso in seen:
            continue
        seen.add(iso)
        disp = _human_date(iso)
        docs.append(RawDoc(title=f"Statement - {disp}", date_text=iso,
                           text=_html.unescape(text)[:200], row_index=i,
                           kind="statement"))
    return docs


# ---------------------------------------------------------------------------
# Host allowlist. Added repo-wide after a review found this app would fetch or
# navigate to whatever URL a stored record or a page attribute contained, using
# the live signed-in session. Parsed, never a string prefix, so a lookalike
# host cannot walk through.
# ---------------------------------------------------------------------------
ALLOWED_HOSTS = {'target.com'}


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
