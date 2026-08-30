"""ALL Robinhood.com selectors, URLs, and page behavior live here.

When Robinhood changes its site, repair this file only.

SAFETY (this is a brokerage / crypto account):
  This module is strictly READ-ONLY. It navigates to the reports/statements
  and tax areas, reads a list of documents, and downloads the PDFs Robinhood
  already generated. It must NEVER activate any control that buys, sells,
  trades, places or cancels an order, transfers/withdraws/deposits money,
  moves or converts crypto, exercises options, closes a position, stakes, or
  changes any setting. FORBIDDEN_CONTROL_RE is the guard; a control must ALSO
  look like a document action (SAFE_DOC_CONTROL_RE) before it may be clicked.
  There is no code here that submits a form or confirms a dialog.

Documents are genuine PDF downloads (not rendered pages). Robinhood is a
heavy React SPA backed by a JSON API, so - like the USAA project - discovery
prefers capturing the documents API response, with table scraping as a
fallback. The selectors are verified against the live signed-in pages (see
the date recorded under this docstring). When the provider redesigns, run
`diagnose.bat` and repair the FALLBACK entries + goto_documents URLs +
collect_documents_via_api matcher against Diagnostics/.
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

log = logging.getLogger("robinhood_docs.site")

BASE = "https://robinhood.com"
URLS = {
    "home": f"{BASE}/",
    "login": f"{BASE}/login",
    # Document-area candidates (Robinhood moves these around). goto_documents
    # tries each; if none render a list, it uses whatever page is open.
    "documents": f"{BASE}/account/reports-and-statements/documents",
    "statements": f"{BASE}/account/reports-and-statements/statements",
    "documents_alt": f"{BASE}/documents",
    "tax_center": f"{BASE}/account/reports-and-statements/tax-center",
}
DOCUMENT_URL_CANDIDATES = [URLS["documents"], URLS["statements"],
                           URLS["documents_alt"], URLS["tax_center"]]

LOGIN_URL_MARKERS = ["/login", "/signin", "/sign-in", "/auth", "/mfa",
                     "/verification", "/challenge"]

# ---------------------------------------------------------------------------
# HARD SAFETY GUARD - never click anything matching this. Tuned for a
# brokerage / crypto account.
# ---------------------------------------------------------------------------
FORBIDDEN_CONTROL_RE = re.compile(
    r"(buy\b|sell\b|trade\b|place\s+order|review\s+order|submit\s+order|"
    r"cancel\s+order|market\s+order|limit\s+order|stop\s+order|"
    r"transfer|withdraw|deposit|wire\b|move\s+money|send\b|receive\b|"
    r"convert|swap\b|exchange\b|stake\b|unstake\b|earn\b|lend\b|"
    r"exercise|close\s+position|sell\s+all|liquidate|"
    r"options?\b|margin\b|borrow\b|gold\b|subscribe|"
    r"apply|open\s+\w*\s*account|fund\b|add\s+money|link\s+(bank|account)|"
    r"enable|disable|activate|\bchange\s+|\bedit\s+|\bupdate\s+|set\s+up|"
    r"delete|remove|close\s+account|beneficiar|password|"
    r"generate\s+report|create\s+report|generate\b|"
    r"confirm|continue|next\b|agree|accept|authorize)", re.I)

SAFE_DOC_CONTROL_RE = re.compile(
    r"(download|view|open|print|pdf|statement|document|1099|1042|"
    r"tax|report|export)", re.I)

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

def goto_documents(page) -> bool:
    for url in DOCUMENT_URL_CANDIDATES:
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3500)
            if looks_signed_out(page):
                return False
            try:
                page.wait_for_selector(FALLBACK["page_ready"], timeout=12000)
            except Exception:
                pass
            if page.locator(FALLBACK["doc_row"]).count() > 1:
                return True
        except Exception as e:
            log.info("documents URL %s failed: %s", url, e)
    try:
        link = page.get_by_role("link", name=re.compile(
            r"(documents?|statements?|reports?|tax)", re.I))
        if link.count() > 0:
            label = link.first.inner_text(timeout=1500) or ""
            if not FORBIDDEN_CONTROL_RE.search(label):
                link.first.click()
                page.wait_for_timeout(3000)
                return page.locator(FALLBACK["doc_row"]).count() > 1
    except Exception:
        pass
    return page.locator(FALLBACK["doc_row"]).count() > 1


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
    Robinhood's 'View More' is an <a> link (not a button), so both roles are
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
    """Capture Robinhood's documents JSON API as the page loads/pages. Repair
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
            # Robinhood list endpoints usually return {"results":[...]} or a
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
    # A stored record must not be able to steer this anywhere but the
    # provider's own site. Before this check the value went straight to
    # page.goto in the signed-in tab.
    if not is_safe_url(full):
        log.error("refusing a URL that is not on this provider's host")
        return False
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
# Robinhood document pages (verified 2026-07). Each document is an
# <a download href="#"> whose own text is the title (statements) or whose
# ancestor holds the title (tax "Download PDF"). Clicking it fires a real
# download event. Statements live on per-account pages; tax docs on the tax
# center. Trade confirmations are intentionally not listed here (out of scope).
# ---------------------------------------------------------------------------
# Crypto statements are intentionally excluded (the account holder does not
# trade crypto). Re-add f"{BASE}/account/reports-statements/crypto" to collect
# them again.
STATEMENT_URLS = [
    f"{BASE}/account/reports-statements/individual",
]
TAX_URL = f"{BASE}/account/reports-statements/tax"


def document_source_urls() -> List[Tuple[str, str]]:
    """(url, source_label) pairs to scan for downloadable documents."""
    pairs = [(u, "statements") for u in STATEMENT_URLS]
    pairs.append((TAX_URL, "tax"))
    return pairs


_COLLECT_JS = r"""() => {
  const out = [];
  const seen = new Set();
  const titleRe = /([A-Z][a-z]+ \d{4}[^\n]*Statement|[^\n]*Consolidated[^\n]*1099[^\n]*|[^\n]*Form 1099[^\n]*|[^\n]*\b1099\b[^\n]*|[^\n]*\b1042-?S\b[^\n]*|[^\n]*\b5498\b[^\n]*)/;
  for (const el of document.querySelectorAll("a[download], a, button, [role=button]")) {
    const own = ((el.innerText||'') + ' ' + (el.getAttribute('aria-label')||'')).trim();
    const hasDlAttr = el.hasAttribute('download');
    const isPdfBtn = /download\s*pdf/i.test(own);
    const isCsvBtn = /download\s*csv/i.test(own);
    let title = '', is_pdf = false;
    if (hasDlAttr && !isCsvBtn && titleRe.test(own)) {
      // statement link: <a download> whose own text IS the title
      title = own; is_pdf = true;
    } else if (isPdfBtn) {
      // tax 'Download PDF' button: the title lives in an ancestor
      let node = el;
      for (let i = 0; i < 12 && node; i++) {
        node = node.parentElement;
        const m = ((node && node.innerText) || '').match(titleRe);
        if (m) { title = m[1]; break; }
      }
      is_pdf = true;
    } else {
      continue;  // CSV buttons, plain title links, nav, etc.
    }
    title = title.replace(/\s+/g, ' ').replace(/\s*Download (PDF|CSV)\s*/gi, ' ').trim();
    if (!title || title.length < 4) continue;
    const key = title.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({title: title.slice(0, 160), is_pdf});
  }
  return out;
}"""


def collect_download_docs(page) -> List[RawDoc]:
    """Every downloadable PDF document on the current page (skips CSV-only
    items like the tax transactions export)."""
    docs: List[RawDoc] = []
    try:
        items = page.evaluate(_COLLECT_JS)
    except Exception:
        items = []
    for it in items:
        if not it.get("is_pdf"):
            continue
        title = _html.unescape(it.get("title", "")).strip()
        if not title:
            continue
        date_text, _ = parse_period_date(title)
        docs.append(RawDoc(title=title[:200], date_text=date_text or "",
                           href="", text=title, kind="doc"))
    return docs


def download_named(page, title: str, out_path) -> bool:
    """Click the download control for the document whose title matches, and
    capture the resulting download event to out_path."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    needle = re.sub(r"\s+", " ", title).strip()[:30]

    # find the matching download control (its own text or an ancestor's holds
    # the title). Only follow controls that pass the safety guard for their
    # visible label (download/view) - never a forbidden one.
    control = None
    try:
        loc = page.locator("a[download], a, button, [role='button']")
        for i in range(min(loc.count(), 400)):
            el = loc.nth(i)
            try:
                own = (el.inner_text(timeout=400) or "") + " " + \
                    (el.get_attribute("aria-label") or "")
            except Exception:
                continue
            has_dl_attr = el.get_attribute("download") is not None
            if not (has_dl_attr or re.search(r"download", own, re.I)):
                continue
            if re.search(r"csv", own, re.I):
                continue
            if FORBIDDEN_CONTROL_RE.search(own) and not has_dl_attr:
                continue
            # match by own text or ancestor text containing the title
            hay = own
            if needle.lower() not in hay.lower():
                try:
                    hay = el.evaluate(
                        "el => { let n = el; for (let i=0;i<6 && n;i++){ n=n.parentElement;"
                        " if(n && (n.innerText||'').length>10) return n.innerText; } return ''; }")
                except Exception:
                    hay = ""
            if needle.lower() in (hay or "").lower():
                control = el
                break
    except Exception:
        pass
    if control is None:
        log.info("download control not found for %r", title)
        return False

    from receipt_pdf import save_download
    try:
        with page.expect_download(timeout=45000) as dl:
            control.click()
        save_download(dl.value, out_path)
        return True
    except Exception as e:
        log.info("download click failed for %r: %s", title, e)
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


# ---------------------------------------------------------------------------
# Host allowlist. Added repo-wide after a review found this app would fetch or
# navigate to whatever URL a stored record or a page attribute contained, using
# the live signed-in session. Parsed, never a string prefix, so a lookalike
# host cannot walk through.
# ---------------------------------------------------------------------------
ALLOWED_HOSTS = {'robinhood.com'}


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
