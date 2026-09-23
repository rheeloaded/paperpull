"""ALL Verizon.com selectors, URLs, and page behavior live here.

When Verizon changes its site, repair this file only.

SAFETY (this is a phone and internet account with a card on file):
  This module is strictly READ-ONLY. It opens the Download Your Bill page,
  picks a bill period from its dropdowns, and saves the PDF Verizon already
  generated. It must NEVER activate any control that pays a bill, sets up
  autopay, changes a plan, orders a device, or changes any setting.
  FORBIDDEN_CONTROL_RE is the guard. A control must ALSO look like a
  document action (SAFE_DOC_CONTROL_RE) before it may be clicked. There is
  no code here that submits a form or confirms a dialog.

Bills are genuine PDF downloads (not rendered pages). Verizon blocks the
Playwright Chromium, so the browser is launched as real Edge or Chrome and
the download directory is set over CDP. The selectors are verified against
the live signed-in pages (see the date recorded under this docstring). When
the provider redesigns, run `diagnose.bat` and repair the FALLBACK entries
and goto_documents against Diagnostics/.
"""
# Site layer verified working against the live site: 2026-08
from __future__ import annotations

import html as _html
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

log = logging.getLogger("verizon_docs.site")

BASE = "https://www.verizon.com"
URLS = {
    "home": f"{BASE}/",
    # The user signs in here manually.
    "login": f"{BASE}/",
    "documents": f"{BASE}/my/bill-history",
    "statements": f"{BASE}/my/bill-history",
    "documents_alt": f"{BASE}/my/billing",
}

LOGIN_URL_MARKERS = ["/login", "/signin", "/sign-in", "/auth", "/mfa",
                     "/verification", "/challenge"]

# ---------------------------------------------------------------------------
# HARD SAFETY GUARD - never click anything matching this. Tuned for a utility
# billing portal: never pay a bill, change service, or modify the account.
# (Pagination is clicked directly by aria-label, not routed through this.)
# ---------------------------------------------------------------------------
FORBIDDEN_CONTROL_RE = re.compile(
    r"(pay\b|payment|pay\s+bill|autopay|auto\s*pay|schedule\s+payment|"
    r"one[-\s]?time\s+payment|payment\s+plan|budget\s+billing|paperless|"
    r"bank\b|routing|account\s+number|debit|credit\s+card|\bcard\b|wallet|"
    r"enroll|unenroll|sign\s+up|start\s+service|stop\s+service|"
    r"transfer\s+service|disconnect|reconnect|new\s+service|move\s+service|"
    r"donate|contribution|round\s*up|"
    r"enable|disable|activate|deactivate|change\b|edit\b|update\b|modify|"
    r"set\s+up|delete|remove|cancel|close\s+account|"
    r"password|profile\b|settings|preferences|"
    r"confirm|submit|agree|accept|authorize|enroll)", re.I)

SAFE_DOC_CONTROL_RE = re.compile(
    r"(download|view|open|print|pdf|statement|document|bill|invoice|"
    r"report|history)", re.I)

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
# Fallback selectors (repair after diagnose)
# ---------------------------------------------------------------------------
FALLBACK = {
    "doc_row": ("table tbody tr, [role='row'], [class*='documentRow'], "
                "[class*='DocumentRow'], [class*='row'][class*='document'], "
                "[data-testid*='document'], li[class*='document']"),
    "doc_link": ("a[href*='.pdf'], a[href*='document'], a[href*='statement'], "
                 "a[download], button[class*='download']"),
    "download_control": "a[download], a[href$='.pdf'], button:has-text('Download')",
    "page_ready": ("table, [role='row'], [class*='document'], [class*='statement'], "
                   "main, [role='main']"),
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
# Documents page
# ---------------------------------------------------------------------------

# My Verizon "Download Your Bill" page. Pick a bill date + "Download PDF" +
# "Get My Bill" -> a PDF downloads (up to 24 months of bills). Verizon blocks
# the Playwright Chromium, so the browser is launched as real Edge/Chrome and
# the download directory is set over CDP (downloads bypass Playwright's own
# capture when attached to a user-launched browser).
DOWNLOAD_URL = "https://www.verizon.com/downloadbill/#/download"
BILLING_URL = DOWNLOAD_URL


def dismiss_overlay(page) -> None:
    """Close Verizon's full-screen mega-menu overlay (Mobile/Home/Account menus)
    which otherwise covers the page and intercepts clicks."""
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
    except Exception:
        pass
    try:
        cl = page.get_by_role("button", name=re.compile(r"^close .*(menu|sign in)", re.I))
        for i in range(min(cl.count(), 6)):
            el = cl.nth(i)
            try:
                if el.is_visible():
                    el.click(timeout=1200)
                    page.wait_for_timeout(300)
            except Exception:
                continue
    except Exception:
        pass


def set_download_dir(page, dirpath) -> None:
    """Point the attached browser's downloads at `dirpath` (via CDP)."""
    try:
        Path(dirpath).mkdir(parents=True, exist_ok=True)
        cdp = page.context.new_cdp_session(page)
        cdp.send("Browser.setDownloadBehavior",
                 {"behavior": "allow", "downloadPath": str(dirpath), "eventsEnabled": True})
    except Exception as e:
        log.info("set_download_dir failed: %s", e)


def goto_documents(page) -> bool:
    """Open the 'Download Your Bill' page and confirm its dropdowns are present."""
    dismiss_overlay(page)
    try:
        if "downloadbill" not in (page.url or ""):
            page.goto(DOWNLOAD_URL, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(5000)
        dismiss_overlay(page)
        if looks_signed_out(page):
            return False
        try:
            page.wait_for_selector("[role='combobox']", timeout=15000)
        except Exception:
            pass
        return page.get_by_role("combobox").count() >= 2
    except Exception as e:
        log.info("goto_documents (downloadbill) failed: %s", e)
        return page.get_by_role("combobox").count() >= 2


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
    """Click 'View More' / 'Show more' repeatedly until the full list loads.
    Verizon's 'View More' is an <a> link (not a button), so both roles are
    tried."""
    pat = re.compile(r"^\s*(show|load|view|see)\s+more\s*$|^\s*view\s+all\s*$|^\s*older\s*$", re.I)
    for _ in range(60):
        clicked = False
        for role in ("button", "link"):
            try:
                loc = page.get_by_role(role, name=pat)
                if loc.count() > 0 and loc.first.is_visible():
                    label = loc.first.inner_text(timeout=1000) or ""
                    if not FORBIDDEN_CONTROL_RE.search(label):
                        loc.first.click()
                        page.wait_for_timeout(1600)
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
    """Scrape document rows from the visible table/list (fallback path)."""
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


def _open_combobox(page, which: int):
    """Open the date (0) or delivery (1) dropdown and return its options locator."""
    combos = page.get_by_role("combobox")
    if combos.count() <= which:
        return None
    try:
        combos.nth(which).click()
        page.wait_for_timeout(900)
    except Exception:
        return None
    return page.get_by_role("option")


def collect_download_docs(page) -> List[RawDoc]:
    """Read every available bill date from the Bill Date dropdown (up to 24
    months). Titles carry the display date; the PDF is fetched by download_bill."""
    docs: List[RawDoc] = []
    seen = set()
    opts = _open_combobox(page, 0)
    if opts is None:
        return docs
    n = opts.count()
    for i in range(n):
        try:
            t = (opts.nth(i).inner_text(timeout=500) or "").strip()
        except Exception:
            continue
        iso = parse_date(t)
        if not iso or iso in seen:
            continue
        seen.add(iso)
        docs.append(RawDoc(title=f"Monthly Statement - {t}", date_text=iso, href="",
                           text=f"Verizon Bill Statement {t}", kind="statement"))
    try:
        page.keyboard.press("Escape")
    except Exception:
        pass
    return docs


def download_bill(page, dl_dir, iso_date: str, out_path) -> bool:
    """Select the bill dated `iso_date`, choose 'Download PDF', click 'Get My
    Bill', and move the resulting PDF from the browser download dir to out_path."""
    import os
    import shutil
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    dl_dir = Path(dl_dir)
    dl_dir.mkdir(parents=True, exist_ok=True)
    display = _human_date(iso_date)   # 2026-07-24 -> "July 24, 2026"

    dismiss_overlay(page)
    # 1) pick the bill date
    opts = _open_combobox(page, 0)
    if opts is None:
        log.info("bill-date dropdown not found for %s", iso_date)
        return False
    try:
        page.get_by_role("option", name=re.compile(re.escape(display), re.I)).first.click()
        page.wait_for_timeout(800)
    except Exception as e:
        log.info("could not pick date %s: %s", display, e)
        return False
    # 2) delivery = Download PDF
    opts = _open_combobox(page, 1)
    if opts is None:
        log.info("delivery dropdown not found for %s", iso_date)
        return False
    try:
        page.get_by_role("option", name=re.compile(r"download\s*pdf", re.I)).first.click()
        page.wait_for_timeout(800)
    except Exception as e:
        log.info("could not pick 'Download PDF' for %s: %s", iso_date, e)
        return False
    # 3) Get My Bill -> file lands in dl_dir
    before = set(os.listdir(dl_dir))
    try:
        page.locator("#getmybill").click(timeout=8000)
    except Exception as e:
        log.info("Get My Bill click failed for %s: %s", iso_date, e)
        return False
    for _ in range(40):                        # up to ~20s
        page.wait_for_timeout(500)
        new = [f for f in os.listdir(dl_dir)
               if f not in before and not f.endswith(".crdownload")
               and f.lower().endswith(".pdf")]
        if new:
            src = dl_dir / new[0]
            try:
                if out_path.exists():
                    out_path.unlink()
                shutil.move(str(src), str(out_path))
                return True
            except Exception as e:
                log.info("move failed for %s: %s", iso_date, e)
                return False
    log.info("no PDF appeared for %s", iso_date)
    return False


_MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July",
                "August", "September", "October", "November", "December"]


def _human_date(iso: str) -> str:
    try:
        y, m, d = iso.split("-")
        return f"{_MONTH_NAMES[int(m) - 1]} {int(d)}, {y}"
    except Exception:
        return iso


# ---------------------------------------------------------------------------
# Host allowlist. Added repo-wide after a review found this app would fetch or
# navigate to whatever URL a stored record or a page attribute contained, using
# the live signed-in session. Parsed, never a string prefix, so a lookalike
# host cannot walk through.
# ---------------------------------------------------------------------------
ALLOWED_HOSTS = {'verizon.com'}


def is_safe_url(url: str) -> bool:
    """True only for an https URL on one of this provider's own hosts.

    The check itself lives in the core, so all of them answer the same way.
    This app keeps the hosts, which is the part that really is its own."""
    from paperpull_core.urls import is_safe_url as _host_allows
    return _host_allows(url, ALLOWED_HOSTS)
