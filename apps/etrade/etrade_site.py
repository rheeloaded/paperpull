"""ALL etrade.com selectors, URLs, and page behavior live here.

When E*TRADE changes its site, repair this file only.

STATUS: UNVERIFIED, round four, repaired from three surveys (#36). Written
without an E*TRADE account, so that someone who holds one can
test it without writing code. Nothing below has run against the live
signed-in site. On a first run it is deliberately cautious:

  * --login opens a real Edge or Chrome, since etrade.com runs bot protection that is happiest in a real browser.
  * --diagnose surveys whatever the documents page turns out to be,
    records its headings, its controls with the guard's verdict on each,
    and the shape of every JSON response, with digit runs masked, and
    takes no screenshot. That file is what a tester attaches to the
    GitHub issue.
  * --discover reads dates from any control that looks like a
    statement, trade confirmation or tax form, wherever it sits on the page.
  * --pilot tries to save the newest few, by fetching a PDF link the row
    carries from inside the page, or by clicking the row's own control
    and catching a download event, a PDF response or a new tab.

The guesses that most need confirming from a survey are marked GUESS.
The routes are the biggest one.

Round four, from the third survey. Discovery found nothing although the
page listed one statement in its default ninety days, so the searchItems
answer was caught and its documentDate was not read. The date is now read
in every form E*TRADE could send it, an ISO date, an ISO date-time, or an
epoch in seconds or milliseconds, and the survey records the exact shape
of the dates it saw, digits masked. The period picker offers the years
back to 2019 and nothing wider, the tester's screenshot showed, so when
no "all" or "last N years" period exists the app chooses each year in
turn, applies it, and gathers every list. One filter click per year, the
only clicks outside a document row.

SAFETY (this is a brokerage account that can trade and move money):
  This module is strictly READ-ONLY. It opens the documents area, reads
  the list, and saves the PDFs E*TRADE already generated. It must NEVER
  activate any control that trades, buys, sells, places or cancels an
  order, exercises an option, transfers, wires, deposits, withdraws,
  takes a distribution, or edits any setting.
  FORBIDDEN_CONTROL_RE is the guard. A control must ALSO look like a
  document action (SAFE_DOC_CONTROL_RE) before it may be clicked. There
  is no code here that submits a form or confirms a dialog.
"""
from __future__ import annotations

import base64
import logging
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from paperpull_core.controls import SETTINGS_CONTROL_RE, AUTH_CONTROL_RE

log = logging.getLogger("etrade_docs.site")

BASE = "https://us.etrade.com"
# From the first survey (#36, 2026-09-20). The Documents page is
# /etx/pxy/accountdocs, a list with a type filter (Statements and three
# more), a date filter that defaults to the last 90 days, a Download
# button and pagination. It is fed by an API on ext-web.etrade.com,
# usermetadata (the accounts and the filter vocabulary) and
# v2/searchItems (the documents, each with a guid, an id, a type, a
# title, a date and its account). The Tax Center is /etx/pxy/tax-center.
# Discovery reads the searchItems answer as the page loads it.
BILLING_CANDIDATES = [
    f"{BASE}/etx/pxy/accountdocs",
    f"{BASE}/etx/pxy/tax-center",
    f"{BASE}/etx/hw/v2/accountshome",
]
DOCS_API_RE = re.compile(r"/etaz/api/adsal/accountdocs/v2/searchItems", re.I)
DOCS_URL = f"{BASE}/etx/pxy/accountdocs#/documents"
# The date filter (second survey, #36) is a button reading its current
# choice, "Last 90 Days", that opens a list of periods. These are the
# only controls outside a document row the app touches, and each has to
# read as a period and nothing else. The widest period wins.
DATE_FILTER_RE = re.compile(r"^\s*(last\s+\d+\s+(days|months|years?)|year\s+to\s+date|ytd|"
                            r"all(\s+(time|documents|dates))?|custom(\s+range)?|\d{4})\s*$", re.I)
_WIDEST = [r"^all", r"last\s+(5|7|10)\s+years", r"last\s+\d+\s+years?", r"last\s+(24|36)\s+months",
           r"last\s+12\s+months", r"year\s+to\s+date|ytd", r"last\s+\d+\s+months"]
BILLING_URL = BILLING_CANDIDATES[0]
URLS = {
    "home": f"{BASE}/etx/pxy/dashboard",
    "login": BILLING_URL,
    "documents": BILLING_URL,
    "statements": BILLING_URL,
}

LOGIN_URL_MARKERS = ["/login", "/signin", "/sign-in", "/auth/", "/mfa",
                     "/verification", "/challenge", "/authenticate"]

# ---------------------------------------------------------------------------
# HARD SAFETY GUARD. Tuned for brokerage, on top of the bank words. Never move
# money, never change service or coverage, never change a setting.
# ---------------------------------------------------------------------------
FORBIDDEN_CONTROL_RE = re.compile(
    r"(transfer|zelle|\bwire\b|\bpay\b|payment|bill\s*pay|autopay|auto\s*pay|"
    r"deposit|withdraw|send\s+money|request\s+money|move\s+money|"
    r"\bapply\b|open\s+(an?\s+)?account|close\s+account|\bloan\b|\bborrow|"
    r"\bcard\b|\bcards\b|replace|activate|lock|unlock|\bpin\b|limit|"
    r"overdraft|alerts?\b|\bbudget|\bgoal|\brewards?\b|\boffers?\b|"
    r"enroll|unenroll|sign\s+up|paperless|delivery\s+preference|"
    r"enable|disable|change\b|edit\b|update\b|modify|manage\b|"
    r"set\s+up|delete|remove|cancel|dispute|"
    r"password|passcode|username|profile\b|settings|preferences|contact\s+info|\baddress\b|"
    r"confirm\b|submit|agree|accept|authorize|\bchat\b|contact\s+us|"
    r"beneficiar|nickname|order\s+checks|stop\s+payment|"
    r"\btrade\b(?!\s+confirm)|trading|\bbuy\b|\bsell\b|\border\b|\boptions?\b|margin|exercise|rollover|roll\s+over|distribution|contribut|\bwire\b|link\s+(a\s+)?bank|move\s+money|convert|exchange\b|\bfund\b|invest\b)", re.I)

SAFE_DOC_CONTROL_RE = re.compile(
    r"(download|view|open|print|\bpdf\b|statement|document|\bletter\b|notice|"
    r"1099|1098|5498|tax\s+(form|document)|history|"
    r"trade\s+confirmations?|confirmations?\b|tax\s+center|see\s+(more|all|older)|show\s+(more|all|older)|load\s+more)", re.I)

# A control that fetches one document. GUESS at the wording, wide on
# purpose. "View", "Download", "View PDF", "Statement", "1099-INT".
BILL_CONTROL_RE = re.compile(
    r"((download|view|print|open|get)\s*(my\s+|the\s+|this\s+|your\s+)?(statement|document|pdf|tax|letter|notice|1099|1098)|"
    r"(statement|document|tax\s+form|1099|1098|5498)\s*\(?\s*pdf\s*\)?|\bpdf\b|"
    r"^\s*(view|download|open)\s*$)", re.I)

# A link that points straight at a PDF, from a row's href.
PDF_HREF_RE = re.compile(r"\.pdf(\?|$)|/pdf\b|format=pdf|statement.*download|download.*statement|docId|documentId", re.I)

SECURITY_CHALLENGE_MARKERS = [
    "enter the code", "verification code", "6-digit", "two-factor",
    "two-step", "authenticator", "confirm your identity", "verify your identity",
    "we sent a code", "device approval", "approve this login", "unusual",
    "are you a robot", "captcha", "let's verify", "check your email",
    "check your phone", "your session has expired", "log back in",
    "access denied", "reference #",
]

RATE_LIMIT_MARKERS = [
    "too many requests", "rate limit", "try again later",
    "temporarily unavailable", "http error 429", "unusual traffic",
]

# ---------------------------------------------------------------------------
# Fallback selectors (used by --diagnose only)
# ---------------------------------------------------------------------------
FALLBACK = {
    "doc_row": ("table tbody tr, [role='row'], [class*='statement'], [class*='Statement'], "
                "li[class*='document'], [class*='document']"),
    "doc_link": "a[href*='.pdf'], a[download], button[class*='download']",
    "download_control": "a[download], a[href$='.pdf'], button:has-text('Download')",
    "page_ready": "table, [role='row'], [class*='statement'], main, [role='main']",
    "next_page": ("a[aria-label*='Next' i], button[aria-label*='Next' i], "
                  "[class*='next']"),
}

# ---------------------------------------------------------------------------
# Date parsing
# ---------------------------------------------------------------------------
DATE_PATTERNS = [
    (re.compile(r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
                r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|"
                r"Dec(?:ember)?)\.?\s+(\d{1,2}),?\s+(\d{4})", re.I), "mdY"),
    (re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b"), "mdy_slash"),
    (re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{2})\b"), "mdy_slash2"),
    (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})(?!\d)"), "iso"),
]
_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
MONTH_YEAR_RE = re.compile(
    r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
    r"Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    r"\s+(\d{4})", re.I)
YEAR_RE = re.compile(r"\b(19|20)(\d{2})\b")
_LAST_DAY = {1: 31, 2: 28, 3: 31, 4: 30, 5: 31, 6: 30,
             7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31}
_MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July",
                "August", "September", "October", "November", "December"]
_ID_RE = re.compile(r"\d{6,}")
# A path segment shaped like an id or a key, "/accounts/d11-Kz9Rc.../",
# ten or more characters with a letter and a digit in it.
_PATH_TOKEN_RE = re.compile(r"(?<=/)(?=[A-Za-z0-9_-]*\d)(?=[A-Za-z0-9_-]*[A-Za-z])[A-Za-z0-9_-]{10,}(?=[/?#]|$)")
# "Welcome, ALEX", "Hi Jane", "Good evening, Sam": a greeting names the
# person, and a survey has no use for the name.
_GREETING_RE = re.compile(r"\b((?:welcome(?:\s+back)?|hello|hi|hey|good\s+(?:morning|afternoon|evening)),?)"
                          r"\s+(?!back\b)[A-Za-z][A-Za-z'.-]*(?:\s+[A-Z][A-Za-z'.-]*)?", re.I)


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
            if kind == "mdy_slash2":
                return f"{2000 + int(m.group(3)):04d}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
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


_QUERY_RE = re.compile(r"(https?://[^\s\"'?#]+)\?[^\s\"'#]*")


_WORD_VALUE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_ -]{0,23}$")


def _plain_word(v: str) -> bool:
    """"STATEMENT", "LAST_90_DAYS", not an id, a token or a number."""
    return bool(_WORD_VALUE_RE.match(v)) and sum(ch.isdigit() for ch in v) <= 3


def _safe_query(url: str) -> str:
    """A URL's query parameters, names always, values only when they are
    plain words ("docType=STATEMENT", "range=LAST_90_DAYS"). A value with
    a digit, a token, an id, anything long, is "...". This is what a
    repair needs to make the same call with a wider filter, and nothing
    else."""
    from urllib.parse import urlsplit, parse_qsl
    try:
        pairs = parse_qsl(urlsplit(url).query, keep_blank_values=True)
    except ValueError:
        return ""
    out = []
    for k, v in pairs[:20]:
        out.append("%s=%s" % (k[:30], v if _plain_word(v) else "..."))
    return "&".join(out)


def redact(text: str) -> str:
    """Runs of six or more digits become #, so an account or phone number
    in a URL, a heading or a link never reaches the survey file, and a URL
    loses its query string, which is where a site keeps session details
    the survey has no use for."""
    text = _QUERY_RE.sub(lambda m: m.group(1) + "?...", text or "")
    text = _GREETING_RE.sub(lambda m: m.group(1) + " [name]", text)
    text = _PATH_TOKEN_RE.sub("...", text)
    return _ID_RE.sub(lambda m: "#" * len(m.group(0)), text)


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
    """Names the passcode, CAPTCHA or throttling prompt on screen, or None.
    Visible text only. A page's source can carry every string its scripts
    could ever show, "verification code" included, on a normal day."""
    try:
        if _bill_controls(page).count() > 0:
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
    if SETTINGS_CONTROL_RE.search(name) or AUTH_CONTROL_RE.search(name):
        return False
    return bool(SAFE_DOC_CONTROL_RE.search(name))


# ---------------------------------------------------------------------------
# Downloads from a real Edge or Chrome attached over CDP. The browser saves
# the file itself, into its own Downloads folder, and Playwright's download
# event never fires. So the browser is pointed at a folder of ours and that
# folder is watched after every click. The Verizon app found this first.
# AT&T's fourth round found it again, with a trace that showed a clean
# click and nothing arriving.
# ---------------------------------------------------------------------------

def set_download_dir(page, dirpath) -> None:
    """Point the attached browser's downloads at `dirpath`, via CDP."""
    try:
        Path(dirpath).mkdir(parents=True, exist_ok=True)
        cdp = page.context.new_cdp_session(page)
        cdp.send("Browser.setDownloadBehavior",
                 {"behavior": "allow", "downloadPath": str(dirpath), "eventsEnabled": True})
    except Exception as e:
        log.info("set_download_dir failed: %s", e)


def _snapshot(dl_dir) -> set:
    try:
        return set(os.listdir(dl_dir)) if dl_dir else set()
    except OSError:
        return set()


def _take_new_pdf(dl_dir, before: set, out_path: Path) -> bool:
    """A finished PDF that appeared in `dl_dir` since `before`, moved to
    `out_path`. A file still downloading (.crdownload, .partial) is not
    finished."""
    if not dl_dir:
        return False
    try:
        names = [f for f in os.listdir(dl_dir) if f not in before
                 and not f.lower().endswith((".crdownload", ".partial", ".tmp"))]
    except OSError:
        return False
    for name in names:
        src = Path(dl_dir) / name
        try:
            if src.stat().st_size == 0 or src.read_bytes()[:5] != b"%PDF-":
                continue
            if out_path.exists():
                out_path.unlink()
            shutil.move(str(src), str(out_path))
            return True
        except OSError:
            continue
    return False


_FETCH_AS_B64 = r"""async (u) => {
    const r = await fetch(u, {credentials: 'include'});
    if (!r.ok) return null;
    const buf = new Uint8Array(await r.arrayBuffer());
    let s = ''; for (let i = 0; i < buf.length; i += 0x8000) s += String.fromCharCode.apply(null, buf.subarray(i, i + 0x8000));
    return btoa(s);
}"""


def _take_new_tab(page, new_pages, out_path: Path) -> bool:
    """A PDF that a click opened in a new tab, read out of that tab and
    written to `out_path`. A blob: tab was minted by the page itself and
    is read through the page that made it. Any other address is host
    checked before its bytes are fetched with the session."""
    for extra in new_pages:
        try:
            extra.wait_for_load_state("domcontentloaded", timeout=15000)
            url = extra.url or ""
            if url.startswith("blob:"):
                b64 = page.evaluate(_FETCH_AS_B64, url)
            elif is_safe_url(url):
                b64 = extra.evaluate(_FETCH_AS_B64, url)
            else:
                continue
            if not b64:
                continue
            data = base64.b64decode(b64)
            if data[:5] == b"%PDF-":
                out_path.write_bytes(data)
                return True
        except Exception as e:
            log.info("tab capture failed: %s", e)
    return False


# ---------------------------------------------------------------------------
# Billing page
# ---------------------------------------------------------------------------

def dismiss_overlay(page) -> None:
    """Close a cookie banner, a survey prompt or a promo overlay, the things
    that sit over bank pages and intercept clicks. Escape first, then
    only a control that says close or dismiss, never accept."""
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(250)
    except Exception:
        pass
    try:
        cl = page.get_by_role("button", name=re.compile(r"^(close|dismiss|no thanks|not now)\b", re.I))
        for i in range(min(cl.count(), 6)):
            el = cl.nth(i)
            try:
                if el.is_visible():
                    label = el.inner_text(timeout=500) or ""
                    if FORBIDDEN_CONTROL_RE.search(label):
                        continue
                    el.click(timeout=1000)
                    page.wait_for_timeout(250)
            except Exception:
                continue
    except Exception:
        pass


def _bill_controls(page):
    """Every control on the page whose name says it fetches a document, as
    a button or a link. The row it sits in supplies the date."""
    return page.get_by_role("button", name=BILL_CONTROL_RE).or_(
        page.get_by_role("link", name=BILL_CONTROL_RE))


def _looks_like_billing(page) -> bool:
    try:
        if _bill_controls(page).count() > 0:
            return True
    except Exception:
        pass
    try:
        body = page.locator("body").inner_text(timeout=5000)
    except Exception:
        return False
    return bool(re.search(r"statements?\s+(and|&)\s+documents|statement\s+(period|date)|tax\s+(documents|forms|center)|trade\s+confirmations?",
                          body, re.I))


def goto_documents(page) -> bool:
    """Open Statements & Documents. The first candidate that is not a
    sign-in page and shows something statement-shaped wins, and the URL it
    lands on is remembered so a later call does not walk the list again."""
    global BILLING_URL
    dismiss_overlay(page)
    if is_safe_url(page.url or "") and not looks_signed_out(page) and _looks_like_billing(page):
        return True
    for url in [BILLING_URL] + [u for u in BILLING_CANDIDATES if u != BILLING_URL]:
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(5000)
        except Exception as e:
            log.info("goto %s failed: %s", url, e)
            continue
        dismiss_overlay(page)
        if looks_signed_out(page):
            return False
        if _looks_like_billing(page):
            BILLING_URL = url
            return True
    return False


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
    """Click 'See more' / 'Show more' / 'View older statements' repeatedly
    to surface anything the page loads on demand. The label is
    checked against the guard before every click."""
    pat = re.compile(r"^\s*(show|load|view|see)\s+(more|all|older)(\s+(bills?|statements?|documents?))?\s*$|"
                     r"^\s*(older|previous)\s+(bills?|statements?)\s*$", re.I)
    for _ in range(30):
        clicked = False
        for role in ("button", "link"):
            try:
                loc = page.get_by_role(role, name=pat)
                if loc.count() > 0 and loc.first.is_visible():
                    label = loc.first.inner_text(timeout=1000) or ""
                    if is_safe_control(label):
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


# The date a bill control belongs to. The control's own name first, then
# the nearest enclosing row or card whose text carries a date, up to six
# levels up. Returned with the container's text so a repair can see what
# the row looked like.
_ROW_OF_JS = r"""el => {
  const dateRe = /(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}|\d{1,2}\/\d{1,2}\/\d{2,4}|\d{4}-\d{2}-\d{2}/i;
  let node = el, depth = 0;
  while (node && depth < 6) {
    const txt = (node.innerText || '').trim();
    if (dateRe.test(txt)) return txt.slice(0, 300);
    node = node.parentElement; depth++;
  }
  return '';
}"""


def parse_api_date(value) -> Optional[str]:
    """A date as an API might send it, an ISO date or date-time, an epoch
    in seconds or milliseconds (as a number or a string), or the words a
    page prints. None when it is none of those."""
    if value is None:
        return None
    if isinstance(value, (int, float)) or (isinstance(value, str) and re.fullmatch(r"\d{10,13}", value.strip())):
        try:
            n = float(value)
            if n > 1e11:
                n = n / 1000.0
            from datetime import datetime, timezone
            return datetime.fromtimestamp(n, tz=timezone.utc).strftime("%Y-%m-%d")
        except (ValueError, OverflowError, OSError):
            return None
    return parse_date(str(value))


def date_shape(value) -> str:
    """What a date looked like, digits masked, for the survey."""
    return re.sub(r"\d", "#", str(value))[:40]


def _docs_from_api(body: dict) -> List[dict]:
    """The documents in one searchItems answer, as {date, title, kind,
    hint, account}. The guid rides as the hint. It names a document, not
    a person, and the download will need it."""
    out = []
    for e in (body or {}).get("defaultDocumentList") or (body or {}).get("resultList") or []:
        if not isinstance(e, dict):
            continue
        iso = parse_api_date(e.get("documentDate")) or parse_api_date(e.get("documentLoadDate"))
        if not iso:
            continue
        title = str(e.get("documentTitle") or e.get("documentDisplayName") or e.get("documentTypeName") or "Document").strip()
        kind = str(e.get("documentTypeName") or "")
        hint = "|".join(str(e.get(k) or "") for k in ("documentGuid", "documentId"))
        out.append({"date": iso, "title": title, "kind": kind, "hint": hint,
                    "account": redact(str(e.get("displayMultipleAccounts") or ""))[:40]})
    return out


def goto_docs_capturing(page, capture: list) -> bool:
    """Open the Documents page while catching the searchItems answer that
    fills it, so discovery never has to know how the page asks."""
    def on_response(res):
        try:
            url = res.url or ""
            if is_safe_url(url) and DOCS_API_RE.search(url):
                capture.append(res.json())
        except Exception:
            pass
    page.on("response", on_response)
    try:
        # The page is a single-page app. Landing on it a second time
        # changes nothing and calls nothing, so it is reloaded.
        already = "accountdocs" in (page.url or "")
        page.goto(DOCS_URL, wait_until="domcontentloaded", timeout=60000)
        if already:
            page.reload(wait_until="domcontentloaded", timeout=60000)
        for _ in range(30):
            page.wait_for_timeout(500)
            if capture:
                break
        page.wait_for_timeout(1500)
    except Exception as e:
        log.info("goto documents failed: %s", e)
    finally:
        try:
            page.remove_listener("response", on_response)
        except Exception:
            pass
    dismiss_overlay(page)
    return is_safe_url(page.url or "") and not looks_signed_out(page)


def is_date_filter(label: str) -> bool:
    """The documents page's period picker or one of its periods, and
    nothing that commits anything."""
    label = (label or "").strip()
    return bool(DATE_FILTER_RE.match(label)) and not FORBIDDEN_CONTROL_RE.search(label)


def widen_date_filter(page, capture: list, trace: Optional[list] = None) -> bool:
    """Open the period picker, choose the widest period it offers, and
    apply it, catching the list the page then loads. The picker is the
    button whose text is the current period. Every option seen is
    recorded so the next round knows the vocabulary."""
    try:
        loc = page.get_by_role("button", name=re.compile(r"^\s*last\s+\d+\s+days\s*$", re.I))
        if loc.count() == 0:
            return False
        picker = loc.first
        current = (picker.inner_text(timeout=1000) or "").strip()
        if not is_date_filter(current):
            return False
        before = _control_texts(page)
        picker.click(timeout=5000)
        page.wait_for_timeout(1500)
        appeared = sorted(_control_texts(page) - before)
        if trace is not None:
            trace.append({"note": "period picker options", "options": [redact(t) for t in appeared[:20]]})
        options = [t for t in appeared if is_date_filter(t)]
        choice = None
        for pat in _WIDEST:
            for t in options:
                if re.search(pat, t, re.I):
                    choice = t
                    break
            if choice:
                break
        if not choice:
            years = sorted({t.strip() for t in options if re.fullmatch(r"\s*(19|20)\d{2}\s*", t)}, reverse=True)
            if not years:
                page.keyboard.press("Escape")
                return False
            # No period wider than a year is offered (the third survey's
            # picker ran from this year back to 2019). Each year in turn,
            # then, gathering every list the page loads.
            page.keyboard.press("Escape")
            page.wait_for_timeout(500)
            got_any = False
            for year in years:
                got_any = _choose_period(page, year, capture, trace) or got_any
            return got_any
        return _choose_period(page, choice, capture, trace)
    except Exception as e:
        log.info("could not widen the date filter: %s", e)
        return False


def _choose_period(page, choice: str, capture: list, trace: Optional[list] = None) -> bool:
    """Open the period picker if it is closed, choose `choice`, apply it,
    and catch the list the page then loads. True when a list arrived."""
    try:
        opened = False
        for role in ("menuitem", "option", "button", "link"):
            opt = page.get_by_role(role, name=re.compile("^\\s*" + re.escape(choice) + "\\s*$", re.I))
            if opt.count() and opt.first.is_visible():
                opened = True
                break
        if not opened:
            picker = page.get_by_role("button", name=DATE_FILTER_RE)
            if picker.count() == 0:
                return False
            picker.first.click(timeout=5000)
            page.wait_for_timeout(1200)
        before = len(capture)

        def on_response(res):
            try:
                if is_safe_url(res.url or "") and DOCS_API_RE.search(res.url or ""):
                    capture.append(res.json())
            except Exception:
                pass
        page.on("response", on_response)
        try:
            for role in ("menuitem", "option", "button", "link"):
                opt = page.get_by_role(role, name=re.compile("^\\s*" + re.escape(choice) + "\\s*$", re.I))
                if opt.count():
                    opt.first.click(timeout=5000)
                    break
            page.wait_for_timeout(1500)
            apply = page.get_by_role("button", name=re.compile(r"^\s*apply\s*$", re.I))
            if apply.count() and apply.first.is_visible():
                apply.first.click(timeout=5000)
            for _ in range(30):
                page.wait_for_timeout(500)
                if len(capture) > before:
                    break
            page.wait_for_timeout(1500)
        finally:
            try:
                page.remove_listener("response", on_response)
            except Exception:
                pass
        if trace is not None:
            trace.append({"note": "period chosen", "period": choice, "lists": len(capture) - before})
        log.info("date filter set to %r, %d list(s)", choice, len(capture) - before)
        return len(capture) > before
    except Exception as e:
        log.info("could not choose the period %r: %s", choice, e)
        return False


def collect_download_docs(page) -> List[RawDoc]:
    """Every document the Documents page lists, from the API answer the
    page loads with the widest period its picker offers, else the page's
    own default period, else the rows."""
    docs: List[RawDoc] = []
    seen = set()
    bodies: list = []
    if goto_docs_capturing(page, bodies):
        wider: list = []
        if widen_date_filter(page, wider):
            bodies = wider
        for body in bodies:
            for d in _docs_from_api(body):
                key = (d["date"], d["title"])
                if key in seen:
                    continue
                seen.add(key)
                tax = bool(re.search(r"1099|1098|5498|tax", d["title"] + " " + d["kind"], re.I))
                docs.append(RawDoc(title=d["title"], account=d["account"], date_text=d["date"],
                                   href=d["hint"], text=f"E*TRADE {d['title']} {_human_date(d['date'])}",
                                   kind="tax" if tax else "statement"))
        if docs:
            return docs
    expand_all(page)
    scroll_full_page(page)
    ctrls = _bill_controls(page)
    for i in range(ctrls.count()):
        el = ctrls.nth(i)
        try:
            name = (el.get_attribute("aria-label") or el.inner_text(timeout=800) or "").strip()
        except Exception:
            name = ""
        if not is_safe_control(name):
            continue
        try:
            href = el.get_attribute("href") or ""
        except Exception:
            href = ""
        row_text = ""
        iso = parse_date(name)
        if not iso:
            try:
                row_text = el.evaluate(_ROW_OF_JS) or ""
            except Exception:
                row_text = ""
            iso = parse_date(row_text)
        if not iso or iso in seen:
            continue
        seen.add(iso)
        disp = _human_date(iso)
        tax = bool(re.search(r"1099|1098|5498|tax", name + " " + row_text, re.I))
        kind_title = "Tax Document" if tax else "Account Statement"
        docs.append(RawDoc(title=f"{kind_title} - {disp}", date_text=iso,
                           href=href if PDF_HREF_RE.search(href or "") else "",
                           text=f"E*TRADE {kind_title} {disp}", row_index=i,
                           kind="tax" if tax else "statement"))
    return docs


def _control_for(page, iso: str):
    """The control for the document dated `iso`, matched the same way
    discovery found it, or None."""
    ctrls = _bill_controls(page)
    for i in range(ctrls.count()):
        el = ctrls.nth(i)
        try:
            name = (el.get_attribute("aria-label") or el.inner_text(timeout=800) or "").strip()
        except Exception:
            name = ""
        found = parse_date(name)
        if not found:
            try:
                found = parse_date(el.evaluate(_ROW_OF_JS) or "")
            except Exception:
                found = None
        if found == iso:
            return el, name
    return None, ""


def _fetch_pdf(page, href: str) -> Optional[bytes]:
    """A PDF link fetched from inside the signed-in page, cookies and all,
    only on etrade.com. None unless the answer is a PDF."""
    if not is_safe_url(href):
        return None
    try:
        resp = page.context.request.get(href, timeout=60000)
        body = resp.body() if resp.ok else b""
    except Exception as e:
        log.info("fetch %s failed: %s", redact(href)[:80], e)
        return None
    return body if body[:5] == b"%PDF-" else None


def _take_same_tab(page, start_url: str, out_path: Path, trace: Optional[list]) -> bool:
    """A PDF the click opened in this very tab, the way SMUD's vendor does
    it. The tab's address moved to a document, its bytes are fetched
    through the session, and the tab is sent back where it was."""
    url = page.url or ""
    if not url or url == start_url or not is_safe_url(url):
        return False
    kind = ""
    try:
        kind = (page.evaluate("() => document.contentType || ''") or "").lower()
    except Exception:
        pass
    if trace is not None:
        trace.append({"note": "the tab moved", "url": redact(url)[:160], "content_type": kind[:40]})
    if "pdf" not in kind and not url.lower().split("?")[0].endswith(".pdf"):
        return False
    body = b""
    try:
        resp = page.context.request.get(url, timeout=60000)
        body = resp.body() if resp.ok else b""
    except Exception as e:
        log.info("same-tab fetch failed: %s", e)
    if body[:5] != b"%PDF-":
        try:
            b64 = page.evaluate(_FETCH_AS_B64, url)
            body = base64.b64decode(b64) if b64 else b""
        except Exception:
            body = b""
    try:
        page.go_back(wait_until="domcontentloaded", timeout=15000)
        page.wait_for_timeout(1500)
    except Exception:
        pass
    if body[:5] == b"%PDF-":
        out_path.write_bytes(body)
        return True
    return False


def _control_texts(page) -> set:
    out = set()
    for role in ("button", "link", "menuitem"):
        try:
            loc = page.get_by_role(role)
            for i in range(min(loc.count(), 120)):
                try:
                    t = (loc.nth(i).inner_text(timeout=200) or "").strip()
                except Exception:
                    continue
                if t:
                    out.add(re.sub(r"\s+", " ", t)[:60])
        except Exception:
            pass
    return out


_SECOND_STEP_RE = re.compile(
    r"^\s*(download|download\s+(pdf|now|file|statement|document)|save|save\s+(as\s+)?pdf|"
    r"(regular|standard|full|detailed)\s+pdf|pdf|view\s*/\s*print\s+pdf|print|open\s+pdf)\s*$", re.I)


def _second_step(page, appeared: set):
    """A control the click revealed whose text says it finishes a
    download, once it has passed the guard, or None."""
    ranked = sorted(appeared, key=lambda t: (0 if re.search(r"regular|standard|full|^download", t, re.I) else 1, t))
    for text in ranked:
        if _SECOND_STEP_RE.match(text) and is_safe_control(text):
            for role in ("button", "link", "menuitem"):
                try:
                    loc = page.get_by_role(role, name=re.compile("^" + re.escape(text) + "$", re.I))
                    if loc.count() and loc.first.is_visible():
                        return loc.first, text
                except Exception:
                    continue
    return None, ""


def _catch_pdf(page, el, label: str, out_path: Path, trace: Optional[list] = None,
               dl_dir=None) -> bool:
    """Click `el` and save whatever PDF the site produces, a file landing
    in `dl_dir`, a download event, a PDF response, a new tab, this tab
    moving to the document, or a second control the click revealed.
    `trace` collects what happened, the click's own outcome included."""
    ctx = page.context
    got: dict = {}
    downloads: list = []
    start_url = page.url or ""

    def on_download(dl):
        downloads.append(dl)

    def on_response(res):
        try:
            url = res.url or ""
            if not is_safe_url(url):
                return
            ct = (res.headers.get("content-type") or "").lower()
            if trace is not None and ("json" in ct or "pdf" in ct or "octet" in ct):
                trace.append({"status": res.status, "type": ct[:40], "url": redact(url)[:160]})
            if got:
                return
            if "pdf" in ct or "octet" in ct:
                try:
                    body = res.body()
                except Exception:
                    body = b""
                    got["refetch"] = url
                if body[:5] == b"%PDF-":
                    got["body"] = body
        except Exception:
            pass

    ctx.on("response", on_response)
    page.on("download", on_download)
    before = set(ctx.pages)
    seen = _snapshot(dl_dir)
    controls_before = _control_texts(page)

    def landed() -> bool:
        if downloads:
            try:
                from paperpull_core.receipt_pdf import save_download
                save_download(downloads[0], out_path)
                if out_path.exists() and out_path.read_bytes()[:5] == b"%PDF-":
                    return True
            except Exception as e:
                log.info("download event save failed: %s", e)
        if got.get("body"):
            out_path.write_bytes(got["body"])
            return True
        if got.get("refetch"):
            try:
                resp = page.context.request.get(got.pop("refetch"), timeout=60000)
                body = resp.body() if resp.ok else b""
                if body[:5] == b"%PDF-":
                    out_path.write_bytes(body)
                    return True
            except Exception:
                pass
        return _take_new_pdf(dl_dir, seen, out_path)

    def wait_for_pdf(seconds: int) -> bool:
        for _ in range(seconds):
            if landed():
                return True
            page.wait_for_timeout(1000)
        return landed()

    try:
        try:
            el.scroll_into_view_if_needed(timeout=4000)
        except Exception:
            pass
        try:
            el.click(timeout=8000)
            if trace is not None:
                trace.append({"note": "clicked", "control": label[:60]})
        except Exception as e:
            if trace is not None:
                trace.append({"note": "click failed", "control": label[:60], "error": str(e)[:160]})
            try:
                el.evaluate("el => el.click()")
                if trace is not None:
                    trace.append({"note": "clicked through the DOM instead", "control": label[:60]})
            except Exception as e2:
                if trace is not None:
                    trace.append({"note": "DOM click failed too", "error": str(e2)[:160]})
        if wait_for_pdf(10):
            return True
        if _take_same_tab(page, start_url, out_path, trace):
            return True
        if _take_new_tab(page, [p for p in ctx.pages if p not in before], out_path):
            return True
        appeared = _control_texts(page) - controls_before
        if trace is not None:
            trace.append({"note": "after the click", "url": redact(page.url or "")[:160],
                          "appeared": [redact(t) for t in sorted(appeared)[:15]],
                          "new_tabs": len([p for p in ctx.pages if p not in before])})
        step, step_label = _second_step(page, appeared)
        if step is not None:
            try:
                step.click(timeout=8000)
                if trace is not None:
                    trace.append({"note": "second step clicked", "control": step_label[:60]})
            except Exception as e:
                if trace is not None:
                    trace.append({"note": "second step click failed", "control": step_label[:60],
                                  "error": str(e)[:160]})
            if wait_for_pdf(20):
                return True
            if _take_same_tab(page, start_url, out_path, trace) or \
                    _take_new_tab(page, [p for p in ctx.pages if p not in before], out_path):
                return True
        if wait_for_pdf(15):
            return True
        if _take_new_tab(page, [p for p in ctx.pages if p not in before], out_path):
            return True
        log.info("click on %r produced no PDF", label)
        return False
    finally:
        try:
            ctx.remove_listener("response", on_response)
        except Exception:
            pass
        try:
            page.remove_listener("download", on_download)
        except Exception:
            pass
        for extra in [p for p in ctx.pages if p not in before]:
            try:
                extra.close()
            except Exception:
                pass


def _row_link_for(page, iso_date: str, title: str):
    """The document's own link in its row, the one a person clicks to get
    the PDF (second survey): the row whose date reads this date, and in
    it the link whose text is the title, else the row's first link that
    is not in the Inserts column."""
    try:
        y, m, d = iso_date.split("-")
        short = f"{m}/{d}/{y[2:]}"
        long = f"{m}/{d}/{y}"
        rows = page.get_by_role("row").filter(has_text=re.compile(re.escape(short) + "|" + re.escape(long)))
        for i in range(min(rows.count(), 40)):
            row = rows.nth(i)
            links = row.get_by_role("link")
            if title:
                named = links.filter(has_text=re.compile("^\\s*" + re.escape(title) + "\\s*$", re.I))
                if named.count():
                    return named.first, title
            for j in range(min(links.count(), 4)):
                text = (links.nth(j).inner_text(timeout=500) or "").strip()
                if text and not re.search(r"insert|client\s+re", text, re.I):
                    return links.nth(j), text
    except Exception as e:
        log.info("row link lookup failed: %s", e)
    return None, ""


def download_bill(page, dl_dir, iso_date: str, out_path, title: str = "",
                  trace: Optional[list] = None) -> bool:
    """Save the document dated `iso_date`. A PDF link on the row is fetched
    from inside the page. Otherwise the row's own control is clicked, once
    it has passed the guard, and whichever the site produces is caught, a
    download event or a PDF response, in this tab or one it opens.

    `dl_dir` is where the attached browser saves a download, watched
    after every click."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if not goto_documents(page):
        log.info("could not open the documents page for %s", iso_date)
        return False
    # The list shows the page's default period. It is widened the same
    # way discovery widened it, so an older document's row is on the page.
    if "accountdocs" in (page.url or "") and not getattr(page, "_pp_widened", False):
        widen_date_filter(page, [], trace)
        try:
            page._pp_widened = True
        except Exception:
            pass
    row_link = _row_link_for(page, iso_date, title)
    if row_link is not None:
        el, label = row_link
        if is_safe_control(label):
            return _catch_pdf(page, el, label, out_path, trace, dl_dir)
    expand_all(page)

    el, label = _control_for(page, iso_date)
    if el is None:
        log.info("no document control found for %s", iso_date)
        return False
    if not is_safe_control(label):
        log.info("refusing unsafe control %r for %s", label, iso_date)
        return False

    try:
        href = el.get_attribute("href") or ""
    except Exception:
        href = ""
    if href and not href.lower().startswith(("javascript", "#")):
        from urllib.parse import urljoin
        target = urljoin(page.url, href)
        # A link on the provider's own hosts is fetched through the session
        # first. A PDF answer is the document. Anything else means the link
        # is a page or a handoff, and the click below follows it.
        if is_safe_url(target):
            body = _fetch_pdf(page, target)
            if body:
                out_path.write_bytes(body)
                return True
            if trace is not None:
                trace.append({"note": "the control's own link did not answer with a PDF",
                              "url": redact(target)[:160]})
    return _catch_pdf(page, el, label, out_path, trace, dl_dir)


# ---------------------------------------------------------------------------
# Diagnose. A survey a tester can attach to an issue. No screenshot, since a
# bank page shows names, numbers and balances. Digit runs are masked and
# JSON bodies are recorded as shape only.
# ---------------------------------------------------------------------------
_ROW_JS = r"""() => {
  const out = [];
  for (const tr of document.querySelectorAll('table tr, [role=row], li, [class*="bill" i]')) {
    const txt = (tr.innerText || '').trim();
    if (!txt) continue;
    const link = tr.querySelector("a[href]");
    out.push({text: txt.slice(0, 200), href: link ? link.getAttribute('href') : ''});
  }
  return out.slice(0, 200);
}"""

SURVEY_LINK_RE = re.compile(
    r"^\s*((see|view|show)\s+)?(statements?(\s+(and|&)\s+documents)?|documents|tax\s+(documents|forms|center)|statement\s+history|trade\s+confirmations?|confirmations?)\s*$", re.I)


def collect_documents(page) -> List[RawDoc]:
    """Loose row scrape used only by --diagnose. Every row that carries a
    date, a link or the word download, with digits masked."""
    docs: List[RawDoc] = []
    seen = set()
    try:
        rows = page.evaluate(_ROW_JS)
    except Exception:
        rows = []
    for i, r in enumerate(rows):
        text = redact((r.get("text") or "").strip())
        if not text:
            continue
        has_date = parse_date(text) or MONTH_YEAR_RE.search(text)
        href = redact(r.get("href", "") or "")
        if not (has_date or href or "download" in text.lower()):
            continue
        title = text.splitlines()[0][:200]
        date_text = next((ln for ln in text.splitlines()
                          if parse_date(ln) or MONTH_YEAR_RE.search(ln)), "")
        key = (title, date_text, href, text[:60])
        if key in seen:
            continue
        seen.add(key)
        docs.append(RawDoc(title=re.sub(r"\s+", " ", title), date_text=date_text,
                           href=href, text=text[:400], row_index=i))
    # A row with a date is a document row, and those are what a repair
    # wants to see first, ahead of a nav full of links.
    docs.sort(key=lambda d: 0 if d.date_text else 1)
    return docs


def _shape(obj, depth=0):
    """The shape of a JSON body, never its values."""
    if depth > 3:
        return "..."
    if isinstance(obj, dict):
        return {k: _shape(v, depth + 1) for k, v in list(obj.items())[:25]}
    if isinstance(obj, list):
        return ["list of %d" % len(obj), _shape(obj[0], depth + 1) if obj else None]
    return type(obj).__name__


def _page_summary(page) -> dict:
    out = {"url": redact(page.url or ""), "title": ""}
    try:
        out["title"] = redact(page.title() or "")
    except Exception:
        pass
    try:
        heads = page.locator("h1, h2, h3").all_inner_texts()
        out["headings"] = [redact(h.strip())[:80] for h in heads if h.strip()][:30]
    except Exception:
        out["headings"] = []
    controls = []
    for role in ("link", "button", "tab", "menuitem"):
        try:
            loc = page.get_by_role(role)
            for i in range(min(loc.count(), 100)):
                el = loc.nth(i)
                try:
                    text = (el.inner_text(timeout=300) or "").strip()
                except Exception:
                    text = ""
                if not text:
                    try:
                        text = (el.get_attribute("aria-label") or "").strip()
                    except Exception:
                        text = ""
                if not text:
                    continue
                href = ""
                if role == "link":
                    try:
                        href = el.get_attribute("href") or ""
                    except Exception:
                        pass
                controls.append({"role": role, "text": redact(text)[:60],
                                 "href": redact(href)[:120],
                                 "safe": is_safe_control(text),
                                 "bill": bool(BILL_CONTROL_RE.search(text)),
                                 "survey": bool(SURVEY_LINK_RE.match(text.strip()))})
        except Exception:
            pass
    out["controls"] = controls
    out["bill_controls"] = sum(1 for c in controls if c["bill"])
    return out


def survey(page, dwell_ms: int = 4000, max_follow: int = 6) -> dict:
    """What the signed-in documents area looks like, without downloading
    anything. Records each page, its headings and controls with the
    guard's verdict on each, and every JSON or PDF response etrade.com sends
    while the page settles. Then follows, one at a time and back again,
    the few links whose text is a documents word. No screenshot."""
    seen: list = []

    def on_response(res):
        try:
            url = res.url or ""
            if not is_safe_url(url):
                return
            ct = (res.headers.get("content-type") or "").lower()
            if "json" not in ct and "pdf" not in ct:
                return
            entry = {"url": redact(url)[:200], "status": res.status, "type": ct[:40]}
            try:
                entry["method"] = res.request.method
                body = res.request.post_data or ""
                if body.lstrip().startswith("{"):
                    import json as _json
                    parsed = _json.loads(body)
                    if isinstance(parsed, dict):
                        entry["post_keys"] = sorted(str(k) for k in parsed)[:30]
            except Exception:
                pass
            q = _safe_query(url)
            if q:
                entry["query"] = q[:240]
            if "json" in ct:
                try:
                    body = res.json()
                    entry["shape"] = _shape(body)
                    if DOCS_API_RE.search(url):
                        items = (body or {}).get("defaultDocumentList") or (body or {}).get("resultList") or []
                        entry["date_shapes"] = sorted({date_shape(e.get("documentDate")) for e in items if isinstance(e, dict)})[:5]
                        entry["read_as"] = sorted({str(parse_api_date(e.get("documentDate"))) for e in items if isinstance(e, dict)})[:5]
                except Exception:
                    entry["shape"] = "unreadable"
            seen.append(entry)
        except Exception:
            pass

    page.on("response", on_response)
    report = {"pages": [], "responses": seen}
    try:
        page.wait_for_timeout(dwell_ms)
        start = _page_summary(page)
        report["pages"].append(start)
        followed = 0
        for c in start["controls"]:
            if followed >= max_follow or c["role"] not in ("link", "button") or not c["survey"]:
                continue
            if not is_safe_control(c["text"]):
                continue
            try:
                link = page.get_by_role(c["role"], name=re.compile(
                    "^" + re.escape(c["text"].replace("#", "")) + "$", re.I)).first
                if link.count() == 0:
                    continue
                before = page.url
                tabs_before = set(page.context.pages)
                link.click(timeout=5000)
                page.wait_for_timeout(dwell_ms)
                # A control that opened a new tab (a document vendor behind
                # a single sign-on, a PDF) is surveyed there, then the tab
                # is closed. Off the provider's hosts it is still recorded,
                # marked, and nothing on it is followed.
                for extra in [p for p in page.context.pages if p not in tabs_before]:
                    try:
                        extra.wait_for_load_state("domcontentloaded", timeout=15000)
                        tab = _page_summary(extra)
                        tab["opened_tab_from"] = c["text"]
                        tab["off_host"] = not is_safe_url(extra.url or "")
                        report["pages"].append(tab)
                    except Exception as e:
                        report.setdefault("notes", []).append(
                            "could not read the tab %r opened: %s" % (c["text"], str(e)[:120]))
                    try:
                        extra.close()
                    except Exception:
                        pass
                if not is_safe_url(page.url or ""):
                    page.go_back()
                    continue
                summary = _page_summary(page)
                summary["followed_from"] = c["text"]
                report["pages"].append(summary)
                followed += 1
                if page.url != before:
                    page.go_back(wait_until="domcontentloaded", timeout=15000)
                    page.wait_for_timeout(1500)
            except Exception as e:
                report.setdefault("notes", []).append(
                    "could not follow %r: %s" % (c["text"], str(e)[:120]))
    finally:
        try:
            page.remove_listener("response", on_response)
        except Exception:
            pass
    return report


# ---------------------------------------------------------------------------
# Host allowlist. Parsed, never a string prefix, so a lookalike host cannot
# walk through.
# ---------------------------------------------------------------------------
ALLOWED_HOSTS = {"etrade.com"}


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
