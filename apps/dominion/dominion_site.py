"""ALL Dominion.com selectors, URLs, and page behavior live here.

When Dominion changes its site, repair this file only.

SAFETY (this is a utility billing account):
  This module is strictly READ-ONLY. It navigates to the billing-history
  area, reads the list of bills, and downloads the PDFs Dominion already
  generated. It must NEVER activate any control that pays a bill, sets up
  AutoPay or a payment plan, adds or changes a bank account or card, starts,
  stops or transfers service, or changes any setting. FORBIDDEN_CONTROL_RE is
  the guard; a control must ALSO look like a document action
  (SAFE_DOC_CONTROL_RE) before it may be clicked. There is no code here that
  submits a form or confirms a dialog.

Documents are genuine PDF downloads (not rendered pages). Dominion is a
heavy React SPA backed by a JSON API, so - like the USAA project - discovery
prefers capturing the documents API response, with table scraping as a
fallback.

Dominion posts monthly bills and no tax forms, so what this returns is always
a billing statement. It also serves a placeholder PDF for bills older than
about 18 months - see is_unavailable_bill().
"""
# Site layer verified working against the live site: 2026-08
from __future__ import annotations

import base64
import html as _html
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

log = logging.getLogger("dominion_docs.site")

BASE = "https://www.dominionenergy.com"
URLS = {
    "home": f"{BASE}/virginia",
    # The user signs in here manually.
    "login": f"{BASE}/virginia",
    "documents": f"{BASE}/account/billing-and-payments",
    "statements": f"{BASE}/account/billing-and-payments",
    "documents_alt": f"{BASE}/account",
}
DOCUMENT_URL_CANDIDATES = [URLS["documents"], URLS["statements"],
                           URLS["documents_alt"]]

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
    r"(download|view|open|save|print|pdf|statement|document|bill|invoice|"
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
    return bool(SAFE_DOC_CONTROL_RE.search(name))


# ---------------------------------------------------------------------------
# Documents page
# ---------------------------------------------------------------------------

# The billing portal is a separate hash-routed Material-UI SPA. Its session is
# cookie-based, so a fresh page.goto stays signed in. Bills are a paginated
# accordion; each bill's statement date is in its panel header.
PORTAL = "https://myaccount.dominionenergy.com/portal"
BILLING_URL = f"{PORTAL}/#/Billinghistory"
PANEL_HEADER = ".MuiExpansionPanelSummary-root"
DL_BTN_RE = re.compile(r"download your detailed bill pdf", re.I)
_DATE_RE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")


def goto_documents(page) -> bool:
    """Open the billing-history page (cookie session survives a hard nav)."""
    try:
        if "Billinghistory" not in (page.url or ""):
            page.goto(BILLING_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)
        if looks_signed_out(page):
            return False
        try:
            page.wait_for_selector(PANEL_HEADER, timeout=15000)
        except Exception:
            pass
        return page.locator(PANEL_HEADER).count() > 0
    except Exception as e:
        log.info("goto_documents (billing) failed: %s", e)
        return page.locator(PANEL_HEADER).count() > 0


def _panel_dates(page) -> List[str]:
    """ISO dates of the bills on the current page (from panel headers)."""
    out = []
    loc = page.locator(PANEL_HEADER)
    for i in range(loc.count()):
        try:
            t = loc.nth(i).inner_text(timeout=800) or ""
        except Exception:
            continue
        m = _DATE_RE.search(t)
        if m:
            out.append(f"{int(m.group(3)):04d}-{int(m.group(1)):02d}-{int(m.group(2)):02d}")
    return out


def _next_page(page) -> bool:
    """Click 'next page' if it exists and is enabled; return whether it advanced."""
    try:
        btn = page.get_by_role("button", name=re.compile(r"^\s*next page\s*$", re.I))
        if btn.count() == 0 or not btn.first.is_visible():
            return False
        if btn.first.is_disabled():
            return False
        btn.first.click()
        page.wait_for_timeout(1800)
        return True
    except Exception:
        return False


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
    Dominion's 'View More' is an <a> link (not a button), so both roles are
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


def next_page(page) -> bool:
    try:
        loc = page.locator(FALLBACK["next_page"])
        if loc.count() > 0 and loc.first.is_visible() and loc.first.is_enabled():
            label = (loc.first.inner_text(timeout=800) or "") + \
                (loc.first.get_attribute("aria-label") or "")
            if FORBIDDEN_CONTROL_RE.search(label):
                return False
            loc.first.click()
            page.wait_for_timeout(2500)
            return True
    except Exception:
        pass
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


def collect_documents_via_api(page) -> List[dict]:
    """Capture Dominion's documents JSON API as the page loads/pages. Repair
    the URL/response matcher after diagnose. Returns raw document dicts."""
    batches: List[list] = []

    def on_resp(r):
        try:
            u = r.url
            if not re.search(r"document|statement|report", u, re.I):
                return
            if "json" not in (r.headers.get("content-type", "") or "").lower():
                return
            data = json.loads(r.text())
            # Dominion list endpoints usually return {"results":[...]} or a
            # bare list. Accept either.
            items = None
            if isinstance(data, dict):
                for k in ("results", "documents", "data", "items"):
                    if isinstance(data.get(k), list):
                        items = data[k]
                        break
            elif isinstance(data, list):
                items = data
            if items:
                batches.append(items)
        except Exception:
            pass

    page.on("response", on_resp)
    try:
        goto_documents(page)
        page.wait_for_timeout(3500)
        last = -1
        stagnant = 0
        for _ in range(150):
            for _ in range(3):
                page.mouse.wheel(0, 5000)
                page.wait_for_timeout(700)
            advanced = next_page(page)
            total = sum(len(b) for b in batches)
            if total == last and not advanced:
                stagnant += 1
                if stagnant >= 3:
                    break
            else:
                stagnant = 0
                last = total
    finally:
        try:
            page.remove_listener("response", on_resp)
        except Exception:
            pass

    docs: dict = {}
    for batch in batches:
        for d in batch:
            if not isinstance(d, dict):
                continue
            did = d.get("id") or d.get("documentId") or d.get("url")
            if did and did not in docs:
                docs[did] = d
    return list(docs.values())


_BLOB_FETCH_JS = r"""async () => {
    const f = document.querySelector("iframe[src^='blob:']");
    if (!f || !f.src) return null;
    const r = await fetch(f.src);
    const buf = new Uint8Array(await r.arrayBuffer());
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
    # try a genuine download first
    try:
        with page.expect_download(timeout=20000) as dl:
            try:
                page.goto(full)
            except Exception as e:
                if "download is starting" not in str(e).lower():
                    raise
        from receipt_pdf import save_download
        save_download(dl.value, out_path)
        return True
    except Exception:
        pass
    # inline PDF (blob iframe) fallback
    try:
        page.wait_for_selector("iframe[src^='blob:']", timeout=15000)
        page.wait_for_timeout(1200)
        b64 = page.evaluate(_BLOB_FETCH_JS)
        if b64:
            data = base64.b64decode(b64)
            if b"%PDF-" in data[:1024]:
                out_path.write_bytes(data)
                return True
    except Exception as e:
        log.info("download_by_url blob fallback failed for %s: %s", url, e)
    return False


# ---------------------------------------------------------------------------
# Dominion document pages (verified 2026-07). Every bill lives on the one
# paginated billing-history page as an <a download href="#"> whose own text is
# the title; clicking it fires a real download event. There is no tax area -
# a utility issues no tax forms.
def document_source_urls() -> List[Tuple[str, str]]:
    """The single billing-history page holds every statement (paginated)."""
    return [(BILLING_URL, "statements")]


# How many pages of bills to walk at most (10 bills/page) - a safety bound.
_MAX_PAGES = 40


def collect_download_docs(page) -> List[RawDoc]:
    """Every billing statement across all pages of the billing-history table.
    Each bill's statement date comes from its accordion panel header; the PDF
    itself is fetched later by download_statement (expanding that row)."""
    docs: List[RawDoc] = []
    seen = set()
    for _ in range(_MAX_PAGES):
        page_dates = _panel_dates(page)
        added = False
        for iso in page_dates:
            if iso in seen:
                continue
            seen.add(iso)
            added = True
            human = _human_date(iso)
            docs.append(RawDoc(title=f"Statement - {human}", date_text=iso,
                               href="", text=f"Dominion Energy Statement {human}",
                               kind="statement"))
        # advance; stop when next page shows nothing new
        if not _next_page(page):
            break
        if not added:
            break
    return docs


_MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July",
                "August", "September", "October", "November", "December"]


def _human_date(iso: str) -> str:
    try:
        y, m, d = iso.split("-")
        return f"{_MONTH_NAMES[int(m) - 1]} {int(d)}, {y}"
    except Exception:
        return iso


def _find_panel_for(page, iso: str):
    """Return the accordion header for the bill dated `iso` on the current
    page, or None."""
    try:
        y, m, d = iso.split("-")
    except Exception:
        return None
    mmddyyyy = f"{int(m)}/{int(d)}/{y}"
    loc = page.locator(PANEL_HEADER)
    for i in range(loc.count()):
        h = loc.nth(i)
        try:
            if mmddyyyy in (h.inner_text(timeout=800) or ""):
                return h
        except Exception:
            continue
    return None


def download_statement(page, iso_date: str, out_path) -> bool:
    """Expand the bill dated `iso_date` (paginating to find it) and click its
    'Download Your Detailed Bill PDF' button, capturing the download."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # reset the paginated table to the first page (a prior download may have
    # paged forward); reloading the SPA is the reliable reset.
    try:
        page.reload(wait_until="domcontentloaded", timeout=60000)
        page.wait_for_selector(PANEL_HEADER, timeout=15000)
        page.wait_for_timeout(800)
    except Exception:
        pass

    # locate the panel, walking pages until found
    header = None
    for _ in range(_MAX_PAGES):
        header = _find_panel_for(page, iso_date)
        if header is not None:
            break
        if not _next_page(page):
            break
    if header is None:
        log.info("bill panel not found for %s", iso_date)
        return False

    # this bill's own accordion panel (so we never click another bill's button)
    panel = header.locator(
        "xpath=ancestor::*[contains(concat(' ', normalize-space(@class), ' '),"
        " ' MuiExpansionPanel-root ')][1]")

    # expand it (accordion is single-open)
    try:
        if (header.get_attribute("aria-expanded") or "").lower() != "true":
            header.scroll_into_view_if_needed(timeout=4000)
            header.click()
            page.wait_for_timeout(1200)
    except Exception as e:
        log.info("could not expand panel for %s: %s", iso_date, e)
        return False

    # the download button MUST come from this bill's now-expanded panel
    btn = panel.get_by_role("button", name=DL_BTN_RE)
    if btn.count() == 0:
        btn = panel.get_by_text(DL_BTN_RE)
    try:
        btn.first.wait_for(state="visible", timeout=6000)
    except Exception:
        log.info("download button not visible in panel for %s", iso_date)
        return False

    # safety: the label must be a document action, never a forbidden one
    try:
        label = btn.first.inner_text(timeout=1000) or ""
    except Exception:
        label = ""
    if label and not is_safe_control(label):
        log.info("refusing unsafe control %r for %s", label, iso_date)
        return False

    from receipt_pdf import save_download
    try:
        with page.expect_download(timeout=45000) as dl:
            btn.first.click()
        save_download(dl.value, out_path)
        return True
    except Exception as e:
        log.info("download click failed for %s: %s", iso_date, e)
        return False


_UNAVAILABLE_RE = re.compile(r"older than 18 months", re.I)


def is_unavailable_bill(out_path) -> bool:
    """Dominion serves an identical placeholder PDF ('Images for Bills older
    than 18 months are not available.') instead of a real bill beyond ~18
    months. Detect it so those are marked unavailable, not saved as junk."""
    try:
        import pypdf
        text = (pypdf.PdfReader(str(out_path)).pages[0].extract_text() or "")
        return bool(_UNAVAILABLE_RE.search(text))
    except Exception:
        return False


def find_row_download(page, title: str, date_text: str = ""):
    """Re-find a row's safe download control by its text. Repair after
    diagnose once the real row/menu structure is known."""
    try:
        rows = page.locator(FALLBACK["doc_row"])
        for i in range(rows.count()):
            row = rows.nth(i)
            try:
                text = row.inner_text(timeout=800) or ""
            except Exception:
                continue
            if title and title[:40] not in text:
                continue
            if date_text and date_text not in text:
                continue
            link = row.locator("a[download], a[href$='.pdf'], a[href*='.pdf']")
            if link.count() > 0:
                return link.first
            for b in row.locator("button, a").all():
                try:
                    label = (b.inner_text(timeout=600) or "") + \
                        (b.get_attribute("aria-label") or "")
                except Exception:
                    label = ""
                if is_safe_control(label):
                    return b
    except Exception:
        pass
    return None
