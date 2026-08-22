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


def on_documents_page(page) -> bool:
    """Actually on /Documents/, not merely on some page that has a table.

    The generic more-rows-than-one test once accepted a post-login landing
    page, and the collector then walked a pager on it. The URL for this
    tenant is confirmed, so it is the positive check everywhere below.
    """
    return "/documents/" in (page.url or "").lower()


def goto_documents(page) -> bool:
    """Find the document area, without losing a good page you already have.

    The page in front of us is checked first, then the one confirmed URL,
    then the site's own nav link. Every success path requires BOTH a document
    list and the /Documents/ URL, because right after a re-login the site
    redirects on its own schedule and a table on the landing page is not the
    documents table.
    """
    started_at = page.url
    if on_documents_page(page) and page.locator(FALLBACK["doc_row"]).count() > 1:
        log.info("using the page already open: %s", started_at)
        return True

    for url in DOCUMENT_URL_CANDIDATES:
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3500)
        except Exception as e:
            # "interrupted by another navigation" is not a failure, it is a
            # race: the page was already on its way somewhere, usually the
            # site's own redirect just after a re-login. Let it land, then
            # judge where it ended up like any other outcome.
            log.info("navigation raced (%s); letting the page settle",
                     str(e).splitlines()[0][:90])
            try:
                page.wait_for_load_state("domcontentloaded", timeout=15000)
            except Exception:
                pass
            page.wait_for_timeout(2500)
        if looks_signed_out(page):
            return False
        if looks_like_missing_page(page):
            log.info("no such page: %s", url)
            continue
        try:
            page.wait_for_selector(FALLBACK["page_ready"], timeout=12000)
        except Exception:
            pass
        if on_documents_page(page) and page.locator(FALLBACK["doc_row"]).count() > 1:
            return True

    # the site's own nav link
    try:
        link = page.get_by_role("link", name=re.compile(
            r"(documents?|statements?|tax\s+forms?)", re.I))
        if link.count() > 0:
            label = link.first.inner_text(timeout=1500) or ""
            if not FORBIDDEN_CONTROL_RE.search(label):
                link.first.click()
                page.wait_for_timeout(3000)
                if on_documents_page(page) and                         page.locator(FALLBACK["doc_row"]).count() > 1:
                    return True
    except Exception:
        pass

    # Nothing worked. Go back to whatever was open rather than stranding the
    # user on an error page, but do NOT call that page a success.
    try:
        if page.url != started_at:
            page.goto(started_at, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(2500)
    except Exception:
        pass
    found = on_documents_page(page) and page.locator(FALLBACK["doc_row"]).count() > 1
    if not found:
        log.warning(
            "No document list found. Open %s in the signed-in browser, leave "
            "it there, and run --diagnose.", URLS["documents"])
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


def goto_table_page(page, number: int) -> bool:
    """Click the pager link for a page number, and only for a page number.

    The pager is two rows of postback links reading "1 2 3". A link is clicked
    only if its entire text is the number asked for, so nothing else on the
    page can be mistaken for it. Numbers are the one control class on this
    page that is safe by construction, but the forbidden check runs anyway.
    """
    label = str(number)
    try:
        loc = page.get_by_role("link", name=label, exact=True)
        if loc.count() == 0:
            return False
        el = loc.first
        text = " ".join((el.inner_text(timeout=800) or "").split())
        if text != label or FORBIDDEN_CONTROL_RE.search(text):
            return False
        el.click()
        page.wait_for_timeout(2500)
        return True
    except Exception:
        return False


def collect_all_pages(page, max_pages: int = 20) -> List[dict]:
    """Walk the pager and collect every page's rows.

    Page 1 is read as it stands. Then numbered pager links are clicked in
    order until one is missing. Identity comes from title, policy and date
    rather than the postback name, because WebForms regenerates control ids
    per page, so the same document could carry a different postback target on
    a different visit. max_pages is a hard stop against a pager that loops.
    """
    if not on_documents_page(page):
        log.warning("refusing to collect: this is not the documents page (%s)",
                    (page.url or "")[:80])
        return []
    # Normalise to page 1 before reading anything. Discovery reads whatever
    # page the table was left showing, and a previous walk leaves it on the
    # LAST page - a run then read page 3 twice, never saw page 1, and five
    # documents quietly went missing. If "1" is not a link, this is already
    # page 1 and the click is a no-op by construction.
    goto_table_page(page, 1)

    seen_keys = set()
    out: List[dict] = []

    def take(rows):
        added = 0
        for r in rows:
            key = (r["title"], r["accountName"], r["documentDate"])
            if key in seen_keys:
                continue
            seen_keys.add(key)
            out.append(r)
            added += 1
        return added

    take(collect_document_index(page))
    for number in range(2, max_pages + 1):
        if not goto_table_page(page, number):
            break
        added = take(collect_document_index(page))
        log.info("table page %d: %d new document(s)", number, added)
        if added == 0:
            break
    log.info("documents table: %d document(s) across the pager", len(out))
    return out


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


_TABLE_JS = """() => [...document.querySelectorAll('tr')].map(tr => {
  const own = [...tr.children].filter(c => c.tagName === 'TD');
  const links = [...tr.querySelectorAll('a')].map(a => {
    const h = a.getAttribute('href') || '';
    let pb = '';
    const i1 = h.indexOf('PostBackOptions("');
    if (i1 >= 0) {
      const rest = h.slice(i1 + 17);
      pb = rest.slice(0, rest.indexOf('"'));
    } else {
      const i2 = h.indexOf("__doPostBack('");
      if (i2 >= 0) {
        const rest = h.slice(i2 + 14);
        pb = rest.slice(0, rest.indexOf("'"));
      }
    }
    return {label: a.innerText || '', href: pb ? '' : h, postback: pb};
  });
  return {cells: own.map(c => c.innerText || ''), links: links};
})"""


def _clean(text: str) -> str:
    return " ".join((text or "").split())

def collect_document_index(page) -> List[dict]:
    """Every document row on the current page of the table.

    Read in ONE page.evaluate rather than by walking cells with Playwright.
    The first attempt made four locator calls per row and every real row threw,
    so twenty documents vanished and only a pagination cell survived. One
    round trip has no per-cell timeout to lose, and returns the row's links
    with their postback targets in the same pass.

    Confirmed layout, 2026-08-22. A document row owns SEVEN cells:

        Date | Document | Policy | Name of Insured | View | Download | (spacer)

    Boilerplate rows own three and are dropped by their link living under
    /Resources/PDFFiles/. The pager owns one or three and has no date.
    """
    try:
        rows = page.evaluate(_TABLE_JS) or []
    except Exception as e:
        log.info("could not read the documents table: %s", e)
        return []

    docs: List[dict] = []
    skipped_no_date = skipped_no_view = 0
    sample_cells = None
    for row in rows:
        cells = [_clean(c) for c in (row.get("cells") or [])]
        if len(cells) < 4:
            continue
        # The header claims six columns and a document row owns seven cells,
        # so positions are NOT trusted. The date column is found by looking
        # for the date, and the three cells after it are Document, Policy and
        # Name of Insured, matching the header's own order.
        date_idx = next((i for i, c in enumerate(cells)
                         if _iso_from_us_date(c)), None)
        if date_idx is None or date_idx + 3 >= len(cells):
            if any(cells):
                skipped_no_date += 1
                if sample_cells is None:
                    sample_cells = cells
            continue
        date_text = cells[date_idx]
        title, policy, insured = cells[date_idx + 1:date_idx + 4]
        if not title:
            continue

        view_target, static_href = "", ""
        for link in row.get("links") or []:
            label = _clean(link.get("label"))
            if not label or "view" not in label.lower():
                continue
            if FORBIDDEN_CONTROL_RE.search(label) or not SAFE_DOC_CONTROL_RE.search(label):
                continue
            # "Download a Copy" posts back to a confirmation panel, and this
            # project answers no confirmations anywhere. "View in Browser"
            # renders the document, so that is the control taken.
            view_target = link.get("postback") or ""
            static_href = link.get("href") or ""
            break

        if static_href and RESOURCE_PDF_RE.search(static_href):
            continue
        if not view_target:
            skipped_no_view += 1
            log.info("no usable View control on row %r", title[:60])
            continue

        docs.append({
            "title": title,
            "documentDate": _iso_from_us_date(date_text),
            "displayDate": date_text,
            # A member can hold several policies, and several people can be
            # insured under one login, so both are needed to tell two
            # identically titled statements apart.
            "accountName": _clean(f"{policy} {insured}"),
            "documentId": view_target,
            "category": "",
        })
    # Silence here cost a whole debugging round: every row was filtered by a
    # positional assumption and nothing said so. If rows existed and none
    # survived, say what one looked like.
    if not docs and (skipped_no_date or skipped_no_view):
        log.warning("table had %d row(s) with no recognisable date and %d "
                    "with no View control; first unmatched row's cells: %r",
                    skipped_no_date, skipped_no_view,
                    [c[:30] for c in (sample_cells or [])])
    return docs

def document_deeplink(document_id: str, document_date: str) -> str:
    return f"{BASE}/my/documents?documentId={document_id}&documentDate={document_date}"


def _row_matches(row_doc: dict, title: str, date_text: str, account: str) -> bool:
    if _clean(row_doc.get("title")) != _clean(title):
        return False
    if _clean(row_doc.get("displayDate")) != _clean(date_text):
        return False
    # account is "policy insured" joined at discovery time
    return _clean(row_doc.get("accountName")) == _clean(account)


def _fresh_view_target(page, title: str, date_text: str, account: str) -> str:
    """Walk the pager and return TODAY'S postback target for this document.

    Never the stored one. WebForms names repeater controls by row position,
    so ctl02$lnkViewDocument means "row 2 of whichever page is showing", and
    the same name exists on every pager page. A stored target clicked on the
    wrong page would view a different member document under this one's
    filename, which is the worst quiet failure this app could have.
    """
    goto_table_page(page, 1)
    for number in range(1, 21):
        if number > 1 and not goto_table_page(page, number):
            break
        for row_doc in collect_document_index(page):
            if _row_matches(row_doc, title, date_text, account):
                return row_doc.get("documentId") or ""
    return ""


def download_document_row(page, title: str, date_text: str, account: str,
                          out_path) -> bool:
    """Click the row's View control and capture the PDF it produces.

    How the PDF arrives after the postback is not knowable in advance, so
    three channels are watched at once: a download event, a popup whose
    response is a PDF, and a PDF response in the page itself. Whichever
    happens first wins. Bytes are written only if they begin %PDF.
    """
    target = _fresh_view_target(page, title, date_text, account)
    if not target:
        log.info("could not re-find the row for %r %s", title[:50], date_text)
        return False

    link = page.locator(f'a[href*="{target}"]')
    try:
        if link.count() != 1:
            log.info("expected exactly one link for %s, found %d",
                     target[-40:], link.count())
            return False
        label = _clean(link.first.inner_text(timeout=1500))
    except Exception as e:
        log.info("could not read the View link: %s", e)
        return False
    if FORBIDDEN_CONTROL_RE.search(label) or not SAFE_DOC_CONTROL_RE.search(label):
        log.warning("refusing control %r", label[:60])
        return False

    state = {"download": None, "popup": None, "pdf": None}

    def on_download(d):
        state["download"] = d

    def on_response(r):
        try:
            if state["pdf"] is None and                     "pdf" in (r.headers.get("content-type") or "").lower():
                state["pdf"] = r
        except Exception:
            pass

    def on_popup(pop):
        state["popup"] = pop
        try:
            pop.on("response", on_response)
        except Exception:
            pass

    page.on("download", on_download)
    page.on("popup", on_popup)
    page.on("response", on_response)
    saved = False
    try:
        link.first.click()
        deadline = 30.0
        while deadline > 0 and not saved:
            if state["download"] is not None:
                try:
                    state["download"].save_as(str(out_path))
                    data = Path(out_path).read_bytes()
                    if data.startswith(b"%PDF"):
                        saved = True
                    else:
                        Path(out_path).unlink(missing_ok=True)
                        log.warning("download event delivered a non-PDF")
                        break
                except Exception as e:
                    log.info("saving the download failed: %s", e)
                    break
            elif state["pdf"] is not None:
                try:
                    data = state["pdf"].body()
                except Exception as e:
                    log.info("could not read the PDF response body: %s", e)
                    state["pdf"] = None
                    continue
                if data.startswith(b"%PDF"):
                    out = Path(out_path)
                    out.parent.mkdir(parents=True, exist_ok=True)
                    out.write_bytes(data)
                    saved = True
                else:
                    log.warning("response called itself a PDF and was not")
                    break
            else:
                page.wait_for_timeout(500)
                deadline -= 0.5
        if not saved and deadline <= 0:
            log.info("no PDF arrived within 30s for %r", title[:50])
    finally:
        for event, fn in (("download", on_download), ("popup", on_popup),
                          ("response", on_response)):
            try:
                page.remove_listener(event, fn)
            except Exception:
                pass
        # a popup is the app's own doing, never the user's tab
        if state["popup"] is not None:
            try:
                state["popup"].close()
            except Exception:
                pass
        # a full postback can leave the main frame on the rendered document,
        # so put the table back before the next row is looked for
        try:
            if not on_documents_page(page):
                page.goto(URLS["documents"], wait_until="domcontentloaded",
                          timeout=60000)
                page.wait_for_timeout(2500)
        except Exception:
            pass
    return saved
