"""ALL AAFMAA (Armed Forces Mutual) selectors, URLs, and page behaviour live here.

When AAFMAA changes its site, repair this file only.

STATUS, and read this before trusting anything below.

  CONFIRMED against a signed-in account on 2026-08-22:
    * the documents area is /Documents/default.aspx
    * the app is organised as /<Area>/default.aspx
    * the session survives page.goto, being an ordinary ASP.NET cookie

  STILL UNVERIFIED:
    * every selector in FALLBACK, which has never been matched against a
      real document list
    * every rule in document_rules.json, which was written from what AAFMAA
      is known to issue rather than from titles anyone has seen
    * whether the list paginates, or splits by policy, or by year

  So discovery and download are not finished. Run `diagnose.bat` on the
  documents page and repair FALLBACK against what lands in Diagnostics/.
  Update these two lists as things move from one to the other, rather than
  deleting the block wholesale, because a file that claims more than it has
  earned is worse than one that admits what it does not know.

  The safety guard does not depend on any of this and applies from the start.

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
    Confirmed for this page: every View and Download control is a postback,
    and no handler URL with a document id exists anywhere. The postback
    target name is therefore the document's identity.

THE TABLE, confirmed 2026-08-22
  Date | Document | Policy | Name of Insured | View in Browser | Download a Copy

  Two controls per row, and the choice between them matters. "Download a
  Copy" posts back to lnkShowDownloadConfirmation, which opens a confirmation
  panel, and answering one is a thing this project does not do anywhere. "View
  in Browser" renders the document directly, so that is the control used.

  Above the member's own rows sit three static PDFs that every member sees, a
  president's letter, a benefits brochure and the privacy policy. They are
  dropped by WHERE they live, under /Resources/PDFFiles/, not by their titles.
  Only one of the three matches any skip rule, so title matching would have
  quietly archived the other two as though they were somebody's records.
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
    # CONFIRMED against a signed-in account, 2026-08-22. The app is organised
    # as /<Area>/default.aspx, so the documents area is /Documents/default.aspx
    # and the landing page is /Home/default.aspx.
    "home_app": f"{BASE}/Home/default.aspx",
    "documents": f"{BASE}/Documents/default.aspx",
}

# Deliberately ONE confirmed URL rather than a list of guesses.
#
# The first probe here tried four invented .aspx names, every one of them
# missed, and the app sat on a styled 404 that still returns HTTP 200. On the
# Discover app the same habit ended a live session on a logoff page, and it
# could not afterwards be established whether a bad path or an inactivity
# timeout did it. Guessing paths on a financial site while signed in is not
# worth that doubt. If this URL ever stops working, the in-page nav link is
# the fallback, and diagnose records where every link points.
DOCUMENT_URL_CANDIDATES = [URLS["documents"]]

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

def looks_like_missing_page(page) -> bool:
    """AAFMAA answers an unknown .aspx with a styled 'does not exist' page and
    an HTTP 200, so nothing about the response says it failed."""
    try:
        body = page.locator("body").inner_text(timeout=4000).lower()
    except Exception:
        return False
    return any(m in body for m in (
        "page you are trying to access does not exist",
        "does not exist. to access the member center",
        "page cannot be found", "page not found"))


def goto_documents(page) -> bool:
    """Find the document area, without losing a good page you already have.

    Order matters. The URLs below are guesses, and a wrong guess on AAFMAA
    lands on a 'does not exist' page that still returns HTTP 200. If we
    navigated first and only then looked around, we would throw away the very
    page you had opened for us. So the page in front of us is checked first,
    and if nothing works we navigate back to it.
    """
    started_at = page.url
    if page.locator(FALLBACK["doc_row"]).count() > 1:
        log.info("using the page already open: %s", started_at)
        return True

    for url in DOCUMENT_URL_CANDIDATES:
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3500)
            if looks_signed_out(page):
                return False
            if looks_like_missing_page(page):
                log.info("no such page: %s", url)
                continue
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
    # Nothing worked. Go back to whatever you had open, rather than leaving
    # you stranded on a guessed URL's error page, and read that instead.
    try:
        if page.url != started_at:
            page.goto(started_at, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(2500)
    except Exception:
        pass
    found = page.locator(FALLBACK["doc_row"]).count() > 1
    if not found:
        log.warning(
            "No document list found. None of the guessed URLs exist on this "
            "tenant. Open your documents page in the signed-in browser, leave "
            "it there, and run --diagnose so the real URL can be recorded.")
    return found


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


# NOTE: the data-testid selectors this app was cloned with belong to USAA and
# match nothing here. AAFMAA is WebForms and has no test ids at all. The real
# structure is the table described in the module docstring above.
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


# The membership boilerplate AAFMAA shows every member, above their own
# documents: a president's letter, a benefits brochure, the privacy policy.
# Recognised by WHERE they live rather than by what they are called, so a
# rename cannot start them being archived as somebody's insurance records.
RESOURCE_PDF_RE = re.compile(r"/Resources/PDFFiles/", re.I)

# Each row's links, as (label, href, postback target). WebForms writes the
# target inside a WebForm_PostBackOptions(...) call or a plain __doPostBack,
# so the href is javascript and the name inside it is the real handle.
_ROW_LINKS_JS = r"""e => [...e.querySelectorAll('a')].map(a => {
  const href = a.getAttribute('href') || '';
  const m = href.match(/PostBackOptions\("([^"]+)"/) ||
            href.match(/__doPostBack\('([^']+)'/);
  return [(a.innerText || '').trim(), m ? '' : href, m ? m[1] : ''];
}).slice(0, 8)"""


def _iso_from_us_date(text: str) -> str:
    """AAFMAA prints M/D/YYYY. Returns an ISO date, or an empty string."""
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", text or "")
    if not m:
        return ""
    month, day, year = (int(x) for x in m.groups())
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return ""
    return f"{year:04d}-{month:02d}-{day:02d}"


def collect_document_index(page) -> List[dict]:
    """Every document row in the table, read structurally.

    The table is confirmed 2026-08-22 and its header reads:

        Date | Document | Policy | Name of Insured | View in Browser | Download a Copy

    So the columns are positional and there is no need to guess at labels.
    A row without that many cells is not a document row.

    Two kinds of row are deliberately dropped:

    * The membership boilerplate at the top (a president's letter, a benefits
      brochure, the privacy policy). Those are recognised by their link being
      a REAL href under /Resources/PDFFiles/, which is structural. Matching
      their titles instead would break the first time AAFMAA renames one, and
      would quietly start archiving marketing material.
    * The header row itself.

    Each real row's View control is a __doPostBack target rather than a URL,
    so the postback name is the document's identity. It is stable across a
    reload in a way a row index is not.
    """
    docs: List[dict] = []
    try:
        rows = page.locator("table tr")
        n = min(rows.count(), 400)
    except Exception as e:
        log.info("could not read the documents table: %s", e)
        return docs

    for i in range(n):
        row = rows.nth(i)
        try:
            cells = row.locator("td")
            if cells.count() < 4:
                continue
            values = [" ".join((cells.nth(c).inner_text(timeout=800) or "").split())
                      for c in range(4)]
        except Exception:
            continue
        date_text, title, policy, insured = values
        if not title or not date_text:
            continue
        # the header row names its own columns
        if date_text.lower() == "date" and title.lower() == "document":
            continue

        view_target, static_href = "", ""
        try:
            found = row.evaluate(_ROW_LINKS_JS) or []
        except Exception:
            found = []
        for label, href, postback in found:
            if not SAFE_DOC_CONTROL_RE.search(label or ""):
                continue
            if FORBIDDEN_CONTROL_RE.search(label or ""):
                continue
            # "Download a Copy" opens a confirmation panel, and answering one
            # is a thing this project never does. "View in Browser" renders
            # the PDF directly, so that is the control used.
            if "view" in (label or "").lower():
                if postback:
                    view_target = postback
                elif href:
                    static_href = href
                break

        if static_href and RESOURCE_PDF_RE.search(static_href):
            log.info("skipping membership boilerplate: %s", title[:60])
            continue
        if not view_target:
            log.info("no usable View control on row %r", title[:60])
            continue

        docs.append({
            "title": title,
            "documentDate": _iso_from_us_date(date_text),
            "displayDate": date_text,
            # The policy this document belongs to. Kept because a member can
            # hold several and the filename has to tell them apart.
            "accountName": policy,
            "documentId": view_target,
            "category": "",
            "insured": insured,
        })
    log.info("documents table: %d row(s)", len(docs))
    return docs

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
