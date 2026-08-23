"""ALL M&T Bank selectors, URLs, and page behavior live here.

When M&T changes its site, repair this file only.

STATUS, read before trusting anything below.

  CONFIRMED from the public site, 2026-08-22:
    * the mortgage is serviced inside M&T's own online banking at
      onlinebanking.mtb.com, not a third-party subservicer. Sign-in starts
      at www.mtb.com/log-in and lands there.

  NOT YET CONFIRMED, and deliberately not guessed:
    * where mortgage statements and documents live once signed in
    * how a statement PDF is delivered (download event, blob tab, or a
      generated-report flow)

  There are NO guessed document URLs here. The AAFMAA app lost a day to four
  invented .aspx names and the Discover app once ended a live session on a
  logoff page the same way. goto_documents works from the page the user left
  open, and --diagnose records where every link points so the real routes get
  written in from evidence.

SAFETY (this is a BANK, and a mortgage can move real money):
  Strictly READ-ONLY. It opens the document/statement area, reads the list,
  and downloads PDFs M&T already generated. It must NEVER activate a control
  that pays the mortgage, sets up or edits autopay, moves money, transfers,
  sends a wire or Zelle, changes escrow, applies for anything, or changes a
  setting. A control must clear FORBIDDEN_CONTROL_RE *and* match
  SAFE_DOC_CONTROL_RE, and every URL requested must be on an M&T host. There
  is deliberately no code here that submits a form or confirms a dialog.

Documents are genuine PDF downloads, captured via the Playwright download
event -> download.save_as(), until diagnose shows otherwise.
"""
from __future__ import annotations

import base64
import html as _html
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

log = logging.getLogger("mtb_docs.site")

# Sign-in starts here and lands on onlinebanking.mtb.com. Both are M&T hosts.
BASE = "https://onlinebanking.mtb.com"
LOGIN_START = "https://www.mtb.com/log-in"
# Every host this app will talk to, and no others. is_safe_url() checks this
# exact set, parsed, so a request can only ever go to M&T.
ALLOWED_HOSTS = {"onlinebanking.mtb.com", "www.mtb.com", "mtb.com"}

URLS = {
    "home": f"{BASE}/",
    "login": LOGIN_START,
}
# Empty on purpose: routes are written from diagnose evidence, not invented.
DOCUMENT_URL_CANDIDATES: list = []

LOGIN_URL_MARKERS = ["/logon", "/login", "/signin", "/auth", "/idp", "/mfa",
                     "/verify", "logon.mtb"]

# ---------------------------------------------------------------------------
# HARD SAFETY GUARD - never click anything matching this. Tuned for a bank.
# ---------------------------------------------------------------------------
FORBIDDEN_CONTROL_RE = re.compile(
    r"(transfer|deposit|withdraw|wire\b|move\s+money|send\s+money|zelle|"
    r"pay\b|payment|pay\s+bills?|bill\s*pay|autopay|auto-?pay|schedule\s+payment|"
    r"buy|sell|trade|place\s+order|rebalance|reallocate|"
    r"apply|open\s+\w*\s*account|get\s+(a\s+)?(quote|started|loan)|add\s+funds|"
    r"cash\s+a\s+check|mobile\s+deposit|external\s+account|link\s+(bank|account)|"
    r"dispute|report\s+(a\s+)?(problem|fraud|lost|stolen)|lock\s+card|unlock\s+card|"
    r"activate|replace\s+card|order\s+checks|stop\s+payment|"
    r"\bchange\b|\bedit\b|\bupdate\b|set\s+up|enable|disable|delete|remove|"
    r"beneficiar|payee|contact\s+info|password|username|"
    r"file\s+a\s+claim|start\s+a\s+claim|renew|cancel|"
    r"escrow\s+(analysis\s+)?(change|adjust)|make\s+(a\s+)?payment|"
    r"pay\s+(my\s+)?(mortgage|loan|bill)|principal[\s-]*(only)?\s*payment|"
    r"recast|refinanc|forbearance|modif|payoff\s+(request|quote)|"
    r"send\b|submit|confirm|continue|next|agree|accept|sign\b|authorize)", re.I)

SAFE_DOC_CONTROL_RE = re.compile(
    r"(download|view|open|save|print|pdf|statement|document|1099|1098|"
    r"declaration|policy|tax|e-?statement)", re.I)

SECURITY_CHALLENGE_MARKERS = [
    "enter the code we sent", "enter your verification code", "verification code",
    "one-time", "one time pin", "security code", "we sent a code",
    "two-factor", "two-step", "authenticator", "confirm your identity",
    "verify your identity", "we need to verify", "unusual activity",
    "are you a robot", "captcha", "unable to verify", "trouble verifying",
    "your session has expired", "please log on again",
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
                "[class*='DocumentRow'], [class*='statement-row'], "
                "[data-testid*='document'], li[class*='document']"),
    "doc_link": ("a[href*='.pdf'], a[href*='document'], a[href*='statement'], "
                 "a[download], button[class*='download']"),
    "download_control": "a[download], a[href$='.pdf'], button:has-text('Download')",
    "page_ready": ("table, [role='row'], [class*='document'], [class*='statement'], "
                   "main, [role='main']"),
    "account_select": "select, [role='combobox']",
    "next_page": ("a[aria-label*='Next' i], button[aria-label*='Next' i], "
                  ".pagination-next, [class*='next']"),
    "show_more": "button, a",
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
    """Date to file a document under, plus a human period label. Statements
    titled by period ("December 2025", "Q4 2025", "2025") file on the last
    day of that period."""
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
    """Conservative: if a document list rendered, it is a normal page."""
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
    """A control may be clicked only if it looks like a document action AND
    matches nothing in the forbidden list."""
    name = (name or "").strip()
    if not name:
        return False
    if FORBIDDEN_CONTROL_RE.search(name):
        return False
    return bool(SAFE_DOC_CONTROL_RE.search(name))


# ---------------------------------------------------------------------------
# Documents page
# ---------------------------------------------------------------------------

def is_safe_url(url: str) -> bool:
    """On an M&T host, by parsed comparison, never a string prefix.

    A mortgage servicer can move money, so every URL this app fetches must be
    on M&T's own host. Parsed and allowlisted, so a suffix host
    (onlinebanking.mtb.com.evil.test) or a userinfo host
    (onlinebanking.mtb.com@evil.test) cannot walk through.
    """
    from urllib.parse import urlparse
    try:
        got = urlparse(url or "")
    except ValueError:
        return False
    if got.scheme != "https" or not got.hostname:
        return False
    if (got.hostname or "").lower() not in ALLOWED_HOSTS:
        return False
    if got.username or got.password:
        return False
    return True


def goto_documents(page) -> bool:
    """Navigate to a document area. Tries known URLs; if none render a
    document list, keeps whatever page is currently open (so you can navigate
    to the right place manually and the tool reads it)."""
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
    # in-page nav link
    try:
        link = page.get_by_role("link", name=re.compile(
            r"(documents?|statements?|tax\s+forms?)", re.I))
        if link.count() > 0:
            label = link.first.inner_text(timeout=1500) or ""
            if not FORBIDDEN_CONTROL_RE.search(label):
                link.first.click()
                page.wait_for_timeout(3000)
                return page.locator(FALLBACK["doc_row"]).count() > 1
    except Exception:
        pass
    # fall back to the current page
    return page.locator(FALLBACK["doc_row"]).count() > 1


def scroll_full_page(page, rounds: int = 6, delay_ms: int = 700) -> None:
    try:
        for _ in range(rounds):
            page.mouse.wheel(0, 2500)
            page.wait_for_timeout(delay_ms)
        page.keyboard.press("End")
        page.wait_for_timeout(delay_ms)
    except Exception:
        pass


def expand_all(page) -> None:
    """Click only SAFE 'show more / load more / view all' controls."""
    for _ in range(25):
        clicked = False
        try:
            btn = page.get_by_role("button", name=re.compile(
                r"(show more|load more|view more|see more|view all|older|more\s+statements)", re.I))
            if btn.count() > 0 and btn.first.is_visible():
                label = btn.first.inner_text(timeout=1000) or ""
                if not FORBIDDEN_CONTROL_RE.search(label):
                    btn.first.click()
                    page.wait_for_timeout(1500)
                    clicked = True
        except Exception:
            pass
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


# M&T Bank "My Documents" is a table: Document title | Date delivered | Account |
# Options. Each document row has a title <button data-testid="readDocument-N">
# (clicking it renders the PDF inline in a blob: iframe) and an Options
# <button data-testid="actions-N">. Verified 2026-07-23.
_ROW_JS = r"""() => {
  const out = [];
  for (const tr of document.querySelectorAll('table tr')) {
    const rd = tr.querySelector("[data-testid^='readDocument-']");
    if (!rd) continue;                       // header / non-document row
    const tds = [...tr.querySelectorAll('td')].map(c => (c.innerText || '').trim());
    out.push({
      title: (tds[0] || '').replace(/\s+/g, ' ').trim(),
      date: tds[1] || '',
      account: (tds[2] || '').replace(/\s+/g, ' ').trim(),
      testid: rd.getAttribute('data-testid') || ''
    });
  }
  return out;
}"""


def collect_documents(page) -> List[RawDoc]:
    """Collect M&T Bank document rows currently rendered in the table."""
    docs: List[RawDoc] = []
    seen = set()
    try:
        rows = page.evaluate(_ROW_JS)
    except Exception:
        rows = []
    for r in rows:
        title = _html.unescape(r.get("title", "")).strip()
        if not title:
            continue
        date_text = r.get("date", "")
        account = _html.unescape(r.get("account", "")).strip()
        key = (title, date_text, account)
        if key in seen:
            continue
        seen.add(key)
        docs.append(RawDoc(title=title[:200], account=account, date_text=date_text,
                           href="", row_index=-1,
                           text=f"{title} | {date_text} | {account}"))
    return docs


_BLOB_FETCH_JS = r"""async () => {
    const f = document.querySelector("iframe[src^='blob:']");
    if (!f || !f.src) return null;
    const r = await fetch(f.src);
    const buf = new Uint8Array(await r.arrayBuffer());
    let s = ''; for (let i = 0; i < buf.length; i++) s += String.fromCharCode(buf[i]);
    return btoa(s);
}"""


def collect_documents_via_api(page) -> List[dict]:
    """Enumerate EVERY document by capturing the M&T Bank documents JSON API as the
    page loads/pages, rather than scraping the visible table.

    The SPA calls
      GET .../my-documents/experience/individuals/<id>/documents?limit=100
    returning {"documents":[{title, displayDate, accountName, category,
    subCategory, documentId, documentDate, ...}]} newest-first, in pages. We
    capture every such response while scrolling + clicking through the pager,
    then de-duplicate by documentId. Returns the raw document dicts.
    """
    batches: List[list] = []

    def on_resp(r):
        try:
            u = r.url
            if "/documents" not in u or "?" not in u:
                return
            if "json" not in (r.headers.get("content-type", "") or "").lower():
                return
            data = json.loads(r.text())
            if isinstance(data, dict) and isinstance(data.get("documents"), list):
                batches.append(data["documents"])
        except Exception:
            pass

    page.on("response", on_resp)
    try:
        goto_documents(page)
        page.wait_for_timeout(3500)
        last_total = -1
        stagnant = 0
        for _ in range(150):  # generous cap
            for _ in range(3):
                page.mouse.wheel(0, 5000)
                page.wait_for_timeout(700)
            advanced = False
            try:
                nxt = page.get_by_role("button", name=re.compile(r"^\s*next page\s*$", re.I))
                if nxt.count() == 0:
                    nxt = page.get_by_role("link", name=re.compile(r"^\s*next page\s*$", re.I))
                if nxt.count() and nxt.first.is_visible() and nxt.first.is_enabled():
                    nxt.first.click()
                    page.wait_for_timeout(1800)
                    advanced = True
            except Exception:
                pass
            total = sum(len(b) for b in batches)
            if total == last_total and not advanced:
                stagnant += 1
                if stagnant >= 3:
                    break
            else:
                stagnant = 0
                last_total = total
    finally:
        try:
            page.remove_listener("response", on_resp)
        except Exception:
            pass

    docs: dict = {}
    for batch in batches:
        for d in batch:
            did = d.get("documentId")
            if did and did not in docs:
                docs[did] = d
    return list(docs.values())


def document_deeplink(document_id: str, document_date: str) -> str:
    return f"{BASE}/my/documents?documentId={document_id}&documentDate={document_date}"


def download_by_id(page, document_id: str, document_date: str, out_path) -> bool:
    """Download a document by navigating straight to its deep link, which
    renders the PDF inline as a blob iframe, then fetching the blob bytes.
    Stateless - needs no filter/pagination state."""
    if not document_id:
        return False
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        page.goto(document_deeplink(document_id, document_date),
                  wait_until="domcontentloaded", timeout=60000)
        page.wait_for_selector("iframe[src^='blob:']", timeout=30000)
        page.wait_for_timeout(1500)
        b64 = page.evaluate(_BLOB_FETCH_JS)
        if b64:
            data = base64.b64decode(b64)
            if b"%PDF-" in data[:1024]:
                out_path.write_bytes(data)
                return True
            log.info("deep-link blob for %s not a PDF (%d bytes)", document_id, len(data))
    except Exception as e:
        log.info("download_by_id failed for %s: %s", document_id, e)
    return False


def _find_doc_row(page, title: str, date_text: str, account: str):
    """Return the readDocument (title) button for the row matching this
    document, or None. Matched by content because row indexes are unstable."""
    try:
        rows = page.locator("table tr")
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
            if account and account[:18] and account[:18] not in text:
                continue
            rd = row.locator("[data-testid^='readDocument-']")
            if rd.count() > 0:
                return rd.first
    except Exception:
        pass
    return None


def download_document_row(page, title: str, date_text: str, account: str,
                          out_path) -> bool:
    """Reload a fresh document list, click this document's title, and capture
    the PDF it renders inline.

    M&T Bank shows the PDF as a blob: iframe (no download event, no direct link).
    We ALWAYS reload the list first so no previous document's iframe lingers -
    that stale iframe was the cause of every capture returning the same file.
    After the click we wait for a fresh blob iframe, then fetch its bytes in
    the page context.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # fresh list -> guarantees no leftover PDF iframe from the previous doc
    goto_documents(page)
    scroll_full_page(page, rounds=2)
    rd = _find_doc_row(page, title, date_text, account)
    if rd is None:
        log.info("row not found for %r %r %r", title, date_text, account)
        return False

    try:
        rd.click()
        # the inline PDF renders into a blob: iframe once the click resolves
        page.wait_for_selector("iframe[src^='blob:']", timeout=30000)
        page.wait_for_timeout(1800)
        b64 = page.evaluate(r"""async () => {
            const f = document.querySelector("iframe[src^='blob:']");
            if (!f || !f.src) return null;
            const r = await fetch(f.src);
            const buf = new Uint8Array(await r.arrayBuffer());
            let s = ''; for (let i = 0; i < buf.length; i++) s += String.fromCharCode(buf[i]);
            return btoa(s);
        }""")
        if b64:
            data = base64.b64decode(b64)
            if b"%PDF-" in data[:1024]:
                out_path.write_bytes(data)
                return True
            log.info("blob for %r was not a PDF (%d bytes)", title, len(data))
    except Exception as e:
        log.info("capture failed for %r: %s", title, e)
    return False


# ===========================================================================
# M&T Bank document center - NOT YET MAPPED. The functions below are the
# Navy Federal scaffolding this app was cloned from (accordion groups, blob
# View buttons). They are kept as a plausible starting shape for another
# bank SPA, but every selector and the statements URL must be confirmed with
# diagnose before use. No guessed URL is navigated to automatically.
# ===========================================================================
STATEMENTS_URL = ""  # filled in from diagnose evidence
GROUP_SEL = "[class*='product-kind-description-row']"

_BLOB_FETCH = r"""async (u) => {
    const r = await fetch(u);
    const buf = new Uint8Array(await r.arrayBuffer());
    let s = ''; for (let i = 0; i < buf.length; i++) s += String.fromCharCode(buf[i]);
    return btoa(s);
}"""


def dismiss_timeout(page) -> None:
    """Click the 'Continue Session' keep-alive if the inactivity modal is up."""
    try:
        c = page.get_by_role("button", name=re.compile(r"continue session", re.I))
        if c.count() and c.first.is_visible():
            c.first.click()
            page.wait_for_timeout(1000)
    except Exception:
        pass


def ensure_statements(page) -> bool:
    """Reuse the signed-in tab and make sure the Statements page is showing."""
    dismiss_timeout(page)
    try:
        if "statement" not in (page.url or "").lower():
            lk = page.get_by_role("link", name=re.compile(r"^\s*statements\s*$", re.I))
            if lk.count() and lk.first.is_visible():
                lk.first.click()
                page.wait_for_timeout(3000)
        try:
            page.wait_for_selector(GROUP_SEL, timeout=15000)
        except Exception:
            pass
        dismiss_timeout(page)
    except Exception as e:
        log.info("ensure_statements failed: %s", e)
    return page.locator(GROUP_SEL).count() > 0


def group_names(page) -> List[str]:
    out = []
    loc = page.locator(GROUP_SEL)
    for i in range(loc.count()):
        try:
            t = re.sub(r"\s+", " ", loc.nth(i).inner_text(timeout=800) or "").strip()
        except Exception:
            t = ""
        if t:
            out.append(t)
    return out


def expand_only(page, name_needle: str) -> bool:
    """Expand the group whose header contains name_needle; collapse the others
    so the visible rows belong to only that group."""
    dismiss_timeout(page)
    loc = page.locator(GROUP_SEL)
    n = loc.count()
    opened = False
    for i in range(n):
        g = loc.nth(i)
        try:
            txt = g.inner_text(timeout=800) or ""
            exp = (g.get_attribute("aria-expanded") or "").lower()
        except Exception:
            continue
        want = name_needle.lower() in txt.lower()
        if want:
            if exp != "true":
                try:
                    g.click(); page.wait_for_timeout(1800)
                except Exception:
                    pass
            opened = True
        elif exp == "true":
            try:
                g.click(); page.wait_for_timeout(700)
            except Exception:
                pass
    dismiss_timeout(page)
    return opened


_STATEMENT_ROW_JS = r"""() => {
    const out = [];
    for (const tr of document.querySelectorAll('tr')) {
        const t = (tr.innerText || '').replace(/\s+/g, ' ').trim();
        const m = t.match(/(\d{1,2})\/(\d{1,2})\/(\d{4})/);
        if (!m) continue;
        const btn = tr.querySelector("button[id*='statement-link'], button[aria-label*='View'], a[aria-label*='View']");
        if (!btn) continue;
        const title = t.replace(m[0], '').replace(/\s+/g, ' ').trim();
        out.push({date: `${m[3]}-${String(m[1]).padStart(2,'0')}-${String(m[2]).padStart(2,'0')}`,
                  title: title.slice(0, 80)});
    }
    return out;
}"""


def collect_group_rows(page):
    try:
        return page.main_frame.evaluate(_STATEMENT_ROW_JS)
    except Exception:
        return []


def year_select(page):
    """The 'Previous Statements' archive has a year dropdown (2021..2026).
    Return (locator, [years]) if such a <select> is present, else (None, [])."""
    loc = page.locator("select")
    for i in range(min(loc.count(), 12)):
        s = loc.nth(i)
        try:
            opts = [o.strip() for o in s.locator("option").all_inner_texts()]
        except Exception:
            opts = []
        years = [o for o in opts if re.fullmatch(r"20\d{2}", o)]
        if years:
            return s, years
    return None, []


def collect_statement_rows(page):
    """Every document across all account groups: list of {account,date,title}.
    For the 'Previous Statements' archive, iterate its year dropdown so the full
    history (not just the default year) is captured."""
    docs, seen = [], set()

    def grab(acct):
        for r in collect_group_rows(page):
            key = (acct, r["date"], r["title"])
            if key in seen:
                continue
            seen.add(key)
            docs.append({"account": acct, "date": r["date"], "title": r["title"] or "Statement"})

    for name in group_names(page):
        acct = re.sub(r"\s+", " ", name).strip()
        if not expand_only(page, name):
            continue
        sel, years = year_select(page)
        if sel is not None and years:
            for y in years:
                try:
                    sel.select_option(label=y)
                    page.wait_for_timeout(2500)
                    dismiss_timeout(page)
                except Exception:
                    continue
                grab(acct)
        else:
            grab(acct)
    return docs


def download_statement(page, ctx, account: str, date: str, out_path) -> bool:
    """Expand the account group, click the View button on the row dated `date`,
    capture the blob PDF that opens in a new tab, and save it."""
    import base64
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if not expand_only(page, account):
        expand_only(page, account.split()[0] if account else account)
    dismiss_timeout(page)

    # In the 'Previous Statements' archive, the rows for a given year only show
    # once that year is picked, so select the target year first.
    sel, years = year_select(page)
    if sel is not None and date[:4] in years:
        try:
            sel.select_option(label=date[:4])
            page.wait_for_timeout(2500)
            dismiss_timeout(page)
        except Exception:
            pass

    us_date = f"{date[5:7]}/{date[8:10]}/{date[:4]}"   # 2026-07-24 -> 07/24/2026
    btn = None
    try:
        rows = page.locator("tr").filter(has_text=us_date)
        for i in range(rows.count()):
            b = rows.nth(i).locator("button[id*='statement-link'], button[aria-label*='View']")
            if b.count():
                btn = b.first
                break
    except Exception:
        pass
    if btn is None:
        log.info("statement row not found for %s %s", account, date)
        return False

    # close any stale blob tab so we capture THIS statement's blob, not a prior one
    for p in list(ctx.pages):
        if (p.url or "").startswith("blob:"):
            try:
                p.close()
            except Exception:
                pass

    try:
        btn.click()
    except Exception as e:
        log.info("view click failed for %s %s: %s", account, date, e)
        return False

    # the PDF opens as a blob in a new tab; poll for it (dismissing the
    # inactivity modal while we wait, which can otherwise delay the open)
    blob_page = None
    for _ in range(24):                 # up to ~12s
        page.wait_for_timeout(500)
        dismiss_timeout(page)
        for p in ctx.pages:
            if (p.url or "").startswith("blob:"):
                blob_page = p
                break
        if blob_page:
            break
    if blob_page is None:
        log.info("no blob tab opened for %s %s", account, date)
        return False

    ok = False
    try:
        data = base64.b64decode(page.evaluate(_BLOB_FETCH, blob_page.url))
        ok = data[:5] == b"%PDF-"
        if ok:
            out_path.write_bytes(data)
    except Exception as e:
        log.info("blob fetch failed for %s %s: %s", account, date, e)
    try:
        blob_page.close()
    except Exception:
        pass
    return ok
