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
ALLOWED_HOSTS = {"onlinebanking.mtb.com", "m.mtb.com", "www.mtb.com", "mtb.com"}

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
    """Deliberately does NOT navigate.

    M&T's statement list only appears after you select the account and click
    View, and this app never submits that form (see SECURITY.md). An earlier
    version navigated here and clicked a "Statements" nav link, which reloaded
    the page and WIPED the very list the user had created, so discovery always
    read zero. So this only confirms you are still signed in. The actual
    reading is collect_statement_rows, which scans every open tab and frame for
    the statements you listed and the tax page it can open itself.
    """
    return not looks_signed_out(page)


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
# M&T document collection. CONFIRMED against a live account 2026-08-22.
#
# Two server-rendered pages, both with real download URLs (no SPA, no blob):
#   Statements: onlinebanking.mtb.com/Statements/StatementsAndNotices
#     rows are <a href="/Statements/FetchStatementandNotices?t=<TYPE>&a=..&
#     dt=MM/DD/YYYY&stmtId=..">. t=MTGSTMT is a mortgage statement, t=YESTMT a
#     year-end statement.
#   Tax:        m.mtb.com/TaxDocuments/TaxDocumentCenter
#     rows are <a href="/TaxDocuments/FetchTaxDocument?documentkey=..">, the
#     1098 mortgage-interest statements.
#
# A document is identified by its own href. Downloading is a plain GET of that
# href with the session cookie, host-checked first. Nothing is clicked.
# ===========================================================================
STATEMENTS_URL = f"{BASE}/Statements/StatementsAndNotices"
TAX_URL = "https://m.mtb.com/TaxDocuments/TaxDocumentCenter"

_STMT_TYPE = {"MTGSTMT": "Mortgage Statement", "YESTMT": "Year-End Statement"}

_COLLECT_JS = r"""() => [...document.querySelectorAll('a')]
    .map(a => ({label:(a.innerText||'').replace(/\s+/g,' ').trim(),
                href:a.getAttribute('href')||''}))
    .filter(x => /FetchStatementandNotices|FetchTaxDocument/i.test(x.href))"""


def _abs(href: str) -> str:
    if href.startswith("http"):
        return href
    # tax links are relative to m.mtb.com, statement links to onlinebanking
    base = "https://m.mtb.com" if "/TaxDocument" in href else BASE
    return base + href


def _date_from_stmt_href(href: str, label: str) -> str:
    m = re.search(r"[?&]dt=(\d{1,2})/(\d{1,2})/(\d{4})", href)
    if m:
        mo, dy, yr = (int(x) for x in m.groups())
        if 1 <= mo <= 12 and 1 <= dy <= 31:
            return f"{yr:04d}-{mo:02d}-{dy:02d}"
    d = parse_date(label) or ""
    if d:
        return d
    dd, _ = parse_period_date(label)
    return dd or ""


def _doc_id(href: str) -> str:
    """A stable identity from the href: the stmtId or documentkey token. Two
    statements in one month, or two 1098s, differ here even when their titles
    and dates match, so neither collapses into one record."""
    m = re.search(r"[?&](?:stmtId|documentkey)=([^&]+)", href, re.I)
    return m.group(1)[:60] if m else href[-60:]


_TAX_ROWS_JS = r"""() => {
  const out = [];
  for (const tr of document.querySelectorAll('tr')) {
    const a = tr.querySelector('a[href*="FetchTaxDocument"]');
    if (!a) continue;
    const text = (tr.innerText || '').replace(/\s+/g, ' ').trim();
    const ym = text.match(/(20\d{2})/);
    out.push({href: a.getAttribute('href') || '', text: text.slice(0, 80),
              year: ym ? ym[1] : ''});
  }
  return out;
}"""


def collect_statement_rows(page) -> List[dict]:
    """Every statement and tax document, from both pages, newest first.

    Returns dicts {title, date, account, href}. The orchestrator records the
    href as the document's identity and downloads it with a host-checked GET.
    """
    rows: List[dict] = []
    seen = set()

    def harvest_statement_links(links):
        added = 0
        for a in links:
            href = a.get("href") or ""
            if not href or "FetchStatementandNotices" not in href or href in seen:
                continue
            label = re.sub(r"\s+", " ", a.get("label") or "").strip()
            m = re.search(r"[?&]t=([A-Z]+)", href)
            title = _STMT_TYPE.get(m.group(1) if m else "", "Mortgage Statement")
            seen.add(href)
            full = _abs(href)
            rows.append({"title": title, "date": _date_from_stmt_href(href, label),
                         "account": "", "href": full, "doc_id": _doc_id(full)})
            added += 1
        return added

    # STATEMENTS. The list only renders after you pick the account and click
    # View, and this app does not submit that form (see SECURITY.md). So you
    # list it and the app reads it - but the listed view is transient and the
    # tab it lives in is not predictable, so scan EVERY open tab and every
    # frame rather than assuming one. Whichever tab holds the listed statements
    # is found.
    found_statements = 0
    try:
        pages = [p for p in page.context.pages if not p.is_closed()]
    except Exception:
        pages = [page]
    for pg in pages:
        for fr in pg.frames:
            # The statements page shows one collapsed section PER YEAR, and only
            # the current year is open by default. Each collapsed year is a
            # <span class="open-table"> whose click fires a FetchYearlyStatements
            # GET that lists that year - read-only, no form submit. Expand them
            # all before reading, or five-plus years of statements are silently
            # missed (they were, until this was found). Expanding is bounded and
            # idempotent: once open the span becomes "close-table".
            try:
                if fr.evaluate(r"""()=>document.querySelectorAll('span.open-table').length"""):
                    for _ in range(15):  # at most 15 year sections
                        opened = fr.evaluate(r"""()=>{
                            const s=document.querySelector('span.open-table');
                            if(!s) return false; s.click(); return true;}""")
                        if not opened:
                            break
                        fr.wait_for_timeout(1200)
            except Exception:
                pass
            try:
                found_statements += harvest_statement_links(fr.evaluate(_COLLECT_JS) or [])
            except Exception:
                continue
    if found_statements == 0:
        log.warning("No statements found in any open tab. On the Statements and "
                    "Notices page, pick your account and click View so they "
                    "show, LEAVE that tab open, then re-run.")

    # TAX documents auto-list on their own page (a plain GET). Read them by
    # table ROW, not by bare anchor: the tax YEAR sits in a separate cell from
    # the link, and a row can carry more than one link, so anchor-only
    # collection loses the year and double-counts. One record per row.
    # Read the tax page the same way as statements: from an open tab, not by
    # navigating (which would hijack the statements tab). If the Tax Documents
    # page is open in any tab, its 1098s are collected; if not, they are simply
    # skipped with a hint, and statements still come through.
    found_tax = 0
    for pg in pages:
        for fr in pg.frames:
            try:
                tax_rows = fr.evaluate(_TAX_ROWS_JS) or []
            except Exception:
                continue
            for r in tax_rows:
                href = r.get("href") or ""
                if not href or href in seen:
                    continue
                seen.add(href)
                year = r.get("year") or ""
                title = "1098 Mortgage Interest Statement"
                rows.append({
                    "title": f"{year} {title}".strip() if year else title,
                    "date": f"{year}-12-31" if year else "",
                    "account": "", "href": _abs(href),
                    "doc_id": _doc_id(_abs(href))})
                found_tax += 1
    if found_tax == 0:
        log.info("No tax documents found in an open tab. To include 1098s, open "
                 "the Tax Documents page (Statements > View Tax Documents) and "
                 "re-run.")

    rows.sort(key=lambda r: r["date"] or "", reverse=True)
    log.info("M&T: %d document(s) collected", len(rows))
    return rows


def ensure_statements(page) -> bool:
    """Only confirms you are still signed in, and never navigates.

    Download does not need the statements page at all: it GETs each document's
    own href (host-checked). Navigating here would reload and wipe the listed
    statements, so this leaves the page exactly as you left it.
    """
    return not looks_signed_out(page)


def download_statement(page, href: str, out_path) -> bool:
    """Save one document's PDF by a host-checked GET of its own href.

    href is the identity captured at discovery. It is re-checked against M&T's
    hosts here, so a stored value can never send the session cookie elsewhere.
    """
    from pathlib import Path
    url = _abs(href)
    if not is_safe_url(url):
        log.error("refusing a non-M&T URL")
        return False
    resp = page.context.request.get(url)
    if not resp.ok:
        log.warning("fetch returned %s", resp.status)
        return False
    body = resp.body()
    if not body.startswith(b"%PDF"):
        log.warning("response was not a PDF")
        return False
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(body)
    return True
