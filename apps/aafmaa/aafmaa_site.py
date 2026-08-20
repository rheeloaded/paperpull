"""ALL AAFMAA (Armed Forces Mutual) selectors, URLs, and page behaviour live here.

When AAFMAA changes its site, repair this file only.

STATUS: the URLs and selectors below are NOT yet verified against a signed-in
        Member Center - they are starting guesses. Run `login.bat`, then
        `diagnose.bat`, and repair DOCUMENT_URL_CANDIDATES and the FALLBACK
        entries against what Diagnostics/ captures. Replace this paragraph
        with the verification date once that has actually happened. The safety
        guard below does not depend on any of that and applies from the start.

SAFETY (this portal can move money):
  The Member Center's own front page advertises Pay Premiums, Check Loan
  Balances, Make a Payment, Update Family Information and Update Contact
  Information. A member can take a policy loan and pay a premium from here.
  So this module is strictly READ-ONLY: it opens the document areas, reads a
  list, and downloads PDFs AAFMAA has already generated. It must NEVER
  activate a control that pays a premium, requests or repays a loan,
  surrenders or withdraws value, changes a beneficiary, edits contact or
  family details, applies for or cancels coverage, or changes any setting.
  A control must clear FORBIDDEN_CONTROL_RE *and* match SAFE_DOC_CONTROL_RE.
  There is deliberately no code here that submits a form or confirms a dialog.

HOW THIS SITE IS BUILT
  connect.aafmaa.com is classic ASP.NET WebForms - __VIEWSTATE, __EVENTTARGET,
  and control names like ctl00$cphForm$ucLogOn$txtUsername. Two consequences
  shape everything below:

  * The session is a server-side ASP.NET cookie, so `page.goto` to a deep page
    stays signed in. (Contrast the Amex app, whose token lives only in memory
    and dies on navigation.) Navigating by URL is safe here.
  * Many "links" are not links. They are javascript:__doPostBack(...) on an
    <a>, so the href tells you nothing and the control has to be clicked.
    Where a real handler URL with a document id exists, prefer it - that is
    what download_by_id() is for. Clicking the row is the fallback.
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

log = logging.getLogger("aafmaa_docs.site")

BASE = "https://connect.aafmaa.com"
URLS = {
    "home": f"{BASE}/",
    # The logon control sits on the root page, so "/" is both the front door
    # and the sign-in page. That means a URL alone cannot tell you whether you
    # are signed in - looks_signed_out() checks for the password field instead.
    "login": f"{BASE}/",
    # GUESSES until diagnose runs. The public site calls the document area the
    # "Digital Vault"; WebForms apps of this vintage use .aspx page names.
    "documents": f"{BASE}/DigitalVault.aspx",
    "documents_alt": f"{BASE}/Documents.aspx",
    "documents_alt2": f"{BASE}/MyDocuments.aspx",
    "statements": f"{BASE}/Statements.aspx",
}
DOCUMENT_URL_CANDIDATES = [URLS["documents"], URLS["documents_alt"],
                           URLS["documents_alt2"], URLS["statements"]]

LOGIN_URL_MARKERS = ["/login", "/logon", "/signin", "/auth",
                     "returnurl=", "sessionexpired", "timeout.aspx"]

# ---------------------------------------------------------------------------
# HARD SAFETY GUARD - never click anything matching this.
# ---------------------------------------------------------------------------
# Tuned to what this portal can actually do. Note the deliberately NARROW
# patterns: "schedule" alone would refuse a Schedule of Benefits, and bare
# "application" would refuse an insurance application PDF - both are documents
# a member wants. The dangerous verb is matched instead.
#
# If a document's own link text ever trips this guard, the fix is to reach it
# through the row's explicit Download control, NOT to loosen the guard.
FORBIDDEN_CONTROL_RE = re.compile(
    r"(\bpay(ments?)?\b|make\s+a\s+payment|pay\s+(now|premium|bill|balance)|"
    r"autopay|auto-?pay|schedule\s+(a\s+)?payment|recurring\s+payment|"
    r"payment\s+(method|profile)|billing\s+information|"
    # "loan balance" is refused, but NOT a bare \bloan\b - "Loan Statement" is
    # a document worth having, and blocking the word would make it unreachable.
    r"loan\s+(request|repay|payoff|application|balances?)|request\s+a\s+loan|borrow|"
    r"surrender|withdraw|cash\s+(value|out)|redeem|disburse|"
    r"beneficiar|designat|"
    r"change\s+(address|name|phone|email|password|coverage|plan)|"
    r"update\s+(profile|address|contact|family|payment|information)|"
    r"add\s+(dependent|family|bank|card)|link\s+(bank|account)|"
    r"apply\s+now|start\s+(an?\s+)?application|submit\s+(an?\s+)?application|"
    r"enroll|unenroll|increase\s+coverage|decrease\s+coverage|"
    r"cancel|terminate|reinstate|surrender|"
    r"\btransfer\b|\bsubmit\b|\bconfirm\b|authorize|\bagree\b|\baccept\b|"
    r"\bedit\b|delete|remove)", re.I)

SAFE_DOC_CONTROL_RE = re.compile(
    r"(download|view|open|save|print|pdf|"
    r"statement|document|certificate|policy|vault|correspondence|"
    r"1099|1098|tax\s+(form|document)|annual|year.?end|e-?statement|"
    r"premium\s+(statement|notice))", re.I)

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


# Armed Forces Mutual "My Documents" is a table: Document title | Date delivered | Account |
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
    """Collect Armed Forces Mutual document rows currently rendered in the table."""
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


def collect_document_index(page) -> List[dict]:
    """Enumerate EVERY document by capturing the Armed Forces Mutual documents JSON API as the
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

    Armed Forces Mutual shows the PDF as a blob: iframe (no download event, no direct link).
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
