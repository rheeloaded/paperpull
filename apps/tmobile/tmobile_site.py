"""ALL T-Mobile.com selectors, URLs, and page behavior live here.

When T-Mobile changes its site, repair this file only.

SAFETY (this is a telecom account):
  This module is strictly READ-ONLY. It navigates to the bill-history area,
  reads the list of past bills, and downloads the detailed-bill PDFs T-Mobile
  already generated. It must NEVER activate any control that pays a bill,
  enrolls in autopay/paperless, changes a plan or service, or edits any
  account setting. FORBIDDEN_CONTROL_RE is the guard; a control must ALSO
  look like a document action (SAFE_DOC_CONTROL_RE) before it may be clicked.
  There is no code here that submits a form or confirms a dialog.

Mechanism (verified 2026-08 against the live signed-in site):
  Bill history lives at t-mobile.com/bill/historical. Each past bill exposes a
  "Download detailed bill" button whose accessible name carries the bill date
  (e.g. "Aug 12, 2026 Download detailed bill PDF"). Clicking it fires a real
  browser download event, captured by Playwright's expect_download - no CDP
  download-directory plumbing needed (unlike Verizon). T-Mobile does NOT block
  the Playwright Chromium, so the browser is launched as a plain Chromium.
"""
# Site layer verified working against the live site: 2026-08
from __future__ import annotations

import html as _html
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

log = logging.getLogger("tmobile_docs.site")

BASE = "https://www.t-mobile.com"
# Bill history: every downloadable bill (current + past) is listed here, each
# with its own "Download detailed bill" button.
HISTORICAL_URL = f"{BASE}/bill/historical"
BILLING_URL = HISTORICAL_URL
URLS = {
    "home": f"{BASE}/",
    # The user signs in manually; landing on the bill-history page sends them
    # through T-Mobile's sign-in and back if they aren't authenticated yet.
    "login": HISTORICAL_URL,
    "documents": HISTORICAL_URL,
    "statements": HISTORICAL_URL,
}
DOCUMENT_URL_CANDIDATES = [HISTORICAL_URL]

LOGIN_URL_MARKERS = ["/login", "/signin", "/sign-in", "/auth", "/mfa",
                     "/verification", "/challenge"]

# ---------------------------------------------------------------------------
# HARD SAFETY GUARD - never click anything matching this. Tuned for a telecom
# billing portal: never pay a bill, change service, or modify the account.
# ---------------------------------------------------------------------------
FORBIDDEN_CONTROL_RE = re.compile(
    r"(pay\b|payment|pay\s+bill|autopay|auto\s*pay|schedule\s+payment|"
    r"one[-\s]?time\s+payment|payment\s+plan|budget\s+billing|"
    r"bank\b|routing|account\s+number|debit|credit\s+card|\bcard\b|wallet|"
    r"enroll|unenroll|sign\s+up|start\s+service|stop\s+service|"
    r"add\s+a\s+line|change\s+plan|upgrade|trade[-\s]?in|"
    r"transfer\s+service|disconnect|reconnect|new\s+service|"
    r"enable|disable|activate|deactivate|change\b|edit\b|update\b|modify|"
    r"set\s+up|delete|remove|cancel|close\s+account|"
    r"password|profile\b|settings|preferences|paperless|"
    r"confirm|submit|agree|accept|authorize)", re.I)

SAFE_DOC_CONTROL_RE = re.compile(
    r"(download|view|open|print|pdf|statement|document|bill|invoice|"
    r"report|history)", re.I)

# The "Download detailed bill" control on each bill row. Its accessible name is
# "<Mon> <day>, <year> Download detailed bill PDF" (there is also a "summary
# bill" variant, which we skip in favor of the full detailed bill).
DETAILED_BTN_RE = re.compile(r"download\s+detailed\s+bill", re.I)

SECURITY_CHALLENGE_MARKERS = [
    "enter the code", "verification code", "6-digit", "two-factor",
    "two-step", "authenticator", "confirm your identity", "verify your identity",
    "we sent a code", "device approval", "approve this login", "unusual",
    "are you a robot", "captcha", "let's verify", "check your email",
    "check your phone", "your session has expired", "log back in",
]

RATE_LIMIT_MARKERS = [
    "too many requests", "rate limit", "try again later",
    "temporarily unavailable", "http error 429", "unusual traffic",
]

# ---------------------------------------------------------------------------
# Fallback selectors (used by --diagnose only)
# ---------------------------------------------------------------------------
FALLBACK = {
    "doc_row": ("table tbody tr, [role='row'], [class*='documentRow'], "
                "[class*='DocumentRow'], [class*='bill'], li[class*='bill']"),
    "doc_link": ("a[href*='.pdf'], a[download], button[class*='download']"),
    "download_control": "a[download], a[href$='.pdf'], button:has-text('Download')",
    "page_ready": ("table, [role='row'], [class*='bill'], main, [role='main']"),
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
_LAST_DAY = {1: 31, 2: 28, 3: 31, 4: 30, 5: 31, 6: 30,
             7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31}

_MON_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
             "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
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
            if kind == "mdy_slash":
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
    try:
        if page.locator("input[type='password']").count() > 0:
            return True
    except Exception:
        pass
    return False


def detect_security_challenge(page) -> Optional[str]:
    try:
        if _detailed_buttons(page).count() > 0:
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
# Bill-history page
# ---------------------------------------------------------------------------

def dismiss_overlay(page) -> None:
    """Close T-Mobile's full-screen mega-menu / bill-download menu overlay,
    which otherwise covers the page and intercepts clicks."""
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(250)
    except Exception:
        pass
    try:
        cl = page.get_by_role("button", name=re.compile(r"^close\b", re.I))
        for i in range(min(cl.count(), 6)):
            el = cl.nth(i)
            try:
                if el.is_visible():
                    el.click(timeout=1000)
                    page.wait_for_timeout(250)
            except Exception:
                continue
    except Exception:
        pass


def _detailed_buttons(page):
    """Every visible 'Download detailed bill' control on the history page."""
    return page.get_by_role("button", name=DETAILED_BTN_RE)


def goto_documents(page) -> bool:
    """Open the bill-history page and confirm its detailed-bill buttons load."""
    dismiss_overlay(page)
    try:
        if "/bill/historical" not in (page.url or ""):
            page.goto(HISTORICAL_URL, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(4000)
        dismiss_overlay(page)
        if looks_signed_out(page):
            return False
        try:
            page.get_by_role("button", name=DETAILED_BTN_RE).first.wait_for(
                state="attached", timeout=15000)
        except Exception:
            pass
        page.wait_for_timeout(1000)
        return _detailed_buttons(page).count() > 0
    except Exception as e:
        log.info("goto_documents failed: %s", e)
        return _detailed_buttons(page).count() > 0


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
    """Click 'View more' / 'Show more' / 'Load more' repeatedly to surface any
    older bills the history page loads on demand."""
    pat = re.compile(r"^\s*(show|load|view|see)\s+more\s*$|^\s*view\s+all\s*$|"
                     r"^\s*older\s*$", re.I)
    for _ in range(30):
        clicked = False
        for role in ("button", "link"):
            try:
                loc = page.get_by_role(role, name=pat)
                if loc.count() > 0 and loc.first.is_visible():
                    label = loc.first.inner_text(timeout=1000) or ""
                    if not FORBIDDEN_CONTROL_RE.search(label):
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


def collect_download_docs(page) -> List[RawDoc]:
    """Read every downloadable bill from the history page. Each 'Download
    detailed bill' button carries the bill date in its accessible name."""
    docs: List[RawDoc] = []
    seen = set()
    expand_all(page)
    btns = _detailed_buttons(page)
    for i in range(btns.count()):
        el = btns.nth(i)
        try:
            name = (el.get_attribute("aria-label")
                    or el.inner_text(timeout=800) or "").strip()
        except Exception:
            name = ""
        iso = parse_date(name)
        if not iso or iso in seen:
            continue
        seen.add(iso)
        disp = _human_date(iso)
        docs.append(RawDoc(title=f"Monthly Statement - {disp}", date_text=iso,
                           href="", text=f"T-Mobile Bill {disp}", kind="statement"))
    return docs


def _btn_re_for(iso: str) -> Optional[re.Pattern]:
    """A regex matching the detailed-bill button for the bill dated `iso`. The
    button's name is like 'Aug 12, 2026 Download detailed bill PDF'."""
    try:
        y, m, d = iso.split("-")
    except Exception:
        return None
    mon = _MON_ABBR[int(m) - 1]
    return re.compile(
        rf"{mon}\w*\.?\s+0*{int(d)},?\s+{y}\b.*detailed\s+bill",
        re.I | re.S)


def download_bill(page, dl_dir, iso_date: str, out_path) -> bool:
    """Find the bill dated `iso_date` on the history page and click its
    'Download detailed bill' button, capturing the real download event.

    `dl_dir` is unused - T-Mobile fires an ordinary download that Playwright's
    expect_download captures directly (kept in the signature for parity with
    the shared orchestrator)."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if "/bill/historical" not in (page.url or ""):
        if not goto_documents(page):
            log.info("could not open bill history for %s", iso_date)
            return False
    dismiss_overlay(page)

    pat = _btn_re_for(iso_date)
    if pat is None:
        log.info("bad iso date %r", iso_date)
        return False
    btn = page.get_by_role("button", name=pat)
    if btn.count() == 0:
        log.info("detailed-bill button not found for %s", iso_date)
        return False

    # safety: the control must be a document action, never a forbidden one
    try:
        label = (btn.first.get_attribute("aria-label")
                 or btn.first.inner_text(timeout=1000) or "")
    except Exception:
        label = ""
    if label and not is_safe_control(label):
        log.info("refusing unsafe control %r for %s", label, iso_date)
        return False

    from receipt_pdf import save_download
    try:
        btn.first.scroll_into_view_if_needed(timeout=4000)
    except Exception:
        pass
    try:
        with page.expect_download(timeout=60000) as dl:
            btn.first.click()
        save_download(dl.value, out_path)
        return True
    except Exception as e:
        log.info("download click failed for %s: %s", iso_date, e)
        return False


# ---------------------------------------------------------------------------
# Diagnose-only helpers (structure dump; no downloads)
# ---------------------------------------------------------------------------
_ROW_JS = r"""() => {
  const out = [];
  for (const tr of document.querySelectorAll('table tr, [role=row], li')) {
    const txt = (tr.innerText || '').trim();
    if (!txt) continue;
    const link = tr.querySelector("a[href]");
    out.push({text: txt.slice(0, 200), href: link ? link.getAttribute('href') : ''});
  }
  return out;
}"""


def collect_documents(page) -> List[RawDoc]:
    """Loose row scrape used only by --diagnose."""
    docs: List[RawDoc] = []
    seen = set()
    try:
        rows = page.evaluate(_ROW_JS)
    except Exception:
        rows = []
    for i, r in enumerate(rows):
        text = (r.get("text") or "").strip()
        if not text:
            continue
        has_date = parse_date(text) or MONTH_YEAR_RE.search(text) or YEAR_RE.search(text)
        href = r.get("href", "")
        if not (has_date or href or "download" in text.lower()):
            continue
        title = _html.unescape(text.splitlines()[0])[:200]
        date_text = next((ln for ln in text.splitlines()
                          if parse_date(ln) or MONTH_YEAR_RE.search(ln)), "")
        key = (title, date_text, href, text[:60])
        if key in seen:
            continue
        seen.add(key)
        docs.append(RawDoc(title=re.sub(r"\s+", " ", title), date_text=date_text,
                           href=href, text=text[:400], row_index=i))
    return docs


# ---------------------------------------------------------------------------
# Host allowlist. Added repo-wide after a review found this app would fetch or
# navigate to whatever URL a stored record or a page attribute contained, using
# the live signed-in session. Parsed, never a string prefix, so a lookalike
# host cannot walk through.
# ---------------------------------------------------------------------------
ALLOWED_HOSTS = {'t-mobile.com'}


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
