"""ALL statefarm.com selectors, URLs, and page behavior live here.

When State Farm changes its site, repair this file only.

STATUS: UNVERIFIED, round two, repaired from the first survey (#37). Written
without a State Farm account, so that someone who holds one can
test it without writing code. Nothing below has run against the live
signed-in site. On a first run it is deliberately cautious:

  * --login opens a real Edge or Chrome, since statefarm.com's sign-in is happiest in a real browser.
  * --diagnose surveys whatever the documents page turns out to be,
    records its headings, its controls with the guard's verdict on each,
    and the shape of every JSON response, with digit runs masked, and
    takes no screenshot. That file is what a tester attaches to the
    GitHub issue.
  * --discover reads dates from any control that looks like a
    bill, renewal notice, ID card, receipt or policy document, wherever it sits on the page.
  * --pilot tries to save the newest few, by fetching a PDF link the row
    carries from inside the page, or by clicking the row's own control
    and catching a download event, a PDF response or a new tab.

The guesses that most need confirming from a survey are marked GUESS.
The routes are the biggest one.

SAFETY (this is an insurance account with a payment method on file):
  This module is strictly READ-ONLY. It opens the documents and billing
  pages, reads the lists, and saves the PDFs State Farm already
  generated. It must NEVER activate any control that pays, sets up
  autopay, files or reports a claim, changes coverage, adds or removes a
  vehicle, driver or policy, starts a quote, cancels or renews a policy,
  or edits any setting.
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

log = logging.getLogger("statefarm_docs.site")

BASE = "https://my.statefarm.com"
# Read off the first survey (#37, 2026-09-20). Sign-in lands on My
# Accounts at my.statefarm.com. Documents live in the Document Center on
# edocuments.statefarm.com ("View documents & PDFs"), bills and payment
# history in the Payment Center on financials.statefarm.com, ID cards on
# get-id-card.statefarm.com, and each policy's own page behind
# tc-ui.statefarm.com. All are statefarm.com hosts. The Document Center
# is the first route, since it is where the PDFs are expected, and the
# survey has not seen inside it yet.
BILLING_CANDIDATES = [
    "https://edocuments.statefarm.com/DocumentCenterUI/",
    "https://financials.statefarm.com/digital-pay/billHistory",
    f"{BASE}/accounts/",
]
BILLING_URL = BILLING_CANDIDATES[0]
URLS = {
    "home": f"{BASE}/accounts/",
    # A signed-out visit to My Accounts goes through State Farm's sign-in
    # and back. The customer-care route the first round used landed on a
    # contact page instead.
    "login": f"{BASE}/",
    "documents": BILLING_URL,
    "statements": BILLING_URL,
}

LOGIN_URL_MARKERS = ["/login", "/signin", "/sign-in", "/auth/", "/mfa",
                     "/verification", "/challenge", "/authenticate"]

# ---------------------------------------------------------------------------
# HARD SAFETY GUARD. Tuned for insurer, on top of the bank words. Never move
# money, never change service or coverage, never change a setting.
# ---------------------------------------------------------------------------
FORBIDDEN_CONTROL_RE = re.compile(
    r"(transfer|zelle|\bwire\b|\bpay\b|payment(?!\s+(receipts?|history))|bill\s*pay|autopay|auto\s*pay|"
    r"deposit|withdraw|send\s+money|request\s+money|move\s+money|"
    r"\bapply\b|open\s+(an?\s+)?account|close\s+account|\bloan\b|\bborrow|"
    r"(?<!id )\bcards?\b|replace|activate|lock|unlock|\bpin\b|limit|"
    r"overdraft|alerts?\b|\bbudget|\bgoal|\brewards?\b|\boffers?\b|"
    r"enroll|unenroll|sign\s+up|paperless|delivery\s+preference|"
    r"enable|disable|change\b|edit\b|update\b|modify|manage\b|"
    r"set\s+up|delete|remove|cancel|dispute|"
    r"password|passcode|username|profile\b|settings|preferences|contact\s+info|\baddress\b|"
    r"confirm\b|submit|agree|accept|authorize|\bchat\b|contact\s+us|"
    r"beneficiar|nickname|order\s+checks|stop\s+payment|"
    r"(?<!excludes )\bclaims?\b|file\s+a\s+claim|report\s+(a\s+)?claim|coverage|\bquote\b|add\s+(a\s+)?(vehicle|driver|car|home|policy)|change\s+(my\s+)?policy|cancel\s+policy|renew\s+now|drive\s+safe|start\s+(a\s+)?quote|roadside|\bagent\b|contact\s+(my\s+)?agent|policy\s+change)", re.I)

SAFE_DOC_CONTROL_RE = re.compile(
    r"(download|view|open|print|\bpdf\b|statement|document|\bletter\b|notice|"
    r"1099|1098|5498|tax\s+(form|document)|history|"
    r"id\s+cards?|renewal\s+(notice|bill)|receipts?\b|\bbills?\b|billing\b|policy\s+documents?|declarations?|see\s+(more|all|older)|show\s+(more|all|older)|load\s+more)", re.I)

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
    (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"), "iso"),
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
    return bool(re.search(r"bill(ing)?\s+(history|period|date)|past\s+bills|renewal\s+notice|id\s+cards?|policy\s+documents|payment\s+receipts?|document\s+center|documents\s*&\s*pdfs",
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


def collect_download_docs(page) -> List[RawDoc]:
    """Read every statement and tax document the page offers. Each
    control's own name, or the row it sits in, carries the date."""
    docs: List[RawDoc] = []
    seen = set()
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
                           text=f"State Farm {kind_title} {disp}", row_index=i,
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
    only on statefarm.com. None unless the answer is a PDF."""
    if not is_safe_url(href):
        return None
    try:
        resp = page.context.request.get(href, timeout=60000)
        body = resp.body() if resp.ok else b""
    except Exception as e:
        log.info("fetch %s failed: %s", redact(href)[:80], e)
        return None
    return body if body[:5] == b"%PDF-" else None


def download_bill(page, dl_dir, iso_date: str, out_path) -> bool:
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
    if href and PDF_HREF_RE.search(href):
        from urllib.parse import urljoin
        body = _fetch_pdf(page, urljoin(page.url, href))
        if body:
            out_path.write_bytes(body)
            return True

    # The click. A PDF can arrive as a download event, as a response in
    # this tab, or in a new tab the control opens. All three are watched,
    # at the context level so a new tab is covered too.
    ctx = page.context
    got: dict = {}

    def on_response(res):
        try:
            if got or not is_safe_url(res.url or ""):
                return
            if "pdf" in (res.headers.get("content-type") or "").lower():
                body = res.body()
                if body[:5] == b"%PDF-":
                    got["body"] = body
        except Exception:
            pass

    ctx.on("response", on_response)
    before = set(ctx.pages)
    seen = _snapshot(dl_dir)
    try:
        try:
            el.scroll_into_view_if_needed(timeout=4000)
        except Exception:
            pass
        try:
            with page.expect_download(timeout=20000) as dl:
                el.click()
            from paperpull_core.receipt_pdf import save_download
            save_download(dl.value, out_path)
            if out_path.stat().st_size > 0 and out_path.read_bytes()[:5] == b"%PDF-":
                return True
        except Exception:
            pass
        deadline = 45
        while not got and deadline > 0:
            if _take_new_pdf(dl_dir, seen, out_path):
                return True
            page.wait_for_timeout(1000)
            deadline -= 1
        if got:
            out_path.write_bytes(got["body"])
            return True
        if _take_new_pdf(dl_dir, seen, out_path):
            return True
        if _take_new_tab(page, [p for p in ctx.pages if p not in before], out_path):
            return True
        log.info("click on %r produced no PDF for %s", label, iso_date)
        return False
    finally:
        try:
            ctx.remove_listener("response", on_response)
        except Exception:
            pass
        for extra in [p for p in ctx.pages if p not in before]:
            try:
                extra.close()
            except Exception:
                pass


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
    r"^\s*((see|view|show|get)\s+)?(bills?|billing|bill(ing)?\s+history|documents(\s*\(excludes\s+claims\))?|"
    r"documents\s*&\s*pdfs|policy\s+documents|(insurance\s+)?id\s+cards?|receipts?|payment\s+history|"
    r"(insurance\s+)?billing\s+and\s+payment\s+history|statements?)\s*$", re.I)


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
    guard's verdict on each, and every JSON or PDF response statefarm.com sends
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
            q = _safe_query(url)
            if q:
                entry["query"] = q[:240]
            if "json" in ct:
                try:
                    entry["shape"] = _shape(res.json())
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
                link.click(timeout=5000)
                page.wait_for_timeout(dwell_ms)
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
ALLOWED_HOSTS = {"statefarm.com"}


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
