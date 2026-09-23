"""ALL sba.gov selectors, URLs, and page behavior live here.

When the SBA changes its portal, repair this file only.

STATUS: UNVERIFIED. This app was written without an SBA loan, from what is
publicly known about the MySBA Loan Portal (lending.sba.gov), where EIDL
and other SBA-serviced borrowers see their loans, monthly statements and
year-end tax forms. Nothing below has run against the live signed-in
site. On a first run it is deliberately cautious:

  * --login opens the sign-in page. The portal signs in through login.gov
    or an SBA account, both of which are the user's to complete.
  * --diagnose surveys whatever the loan and statements pages turn out to
    be, records their headings, their controls with the guard's verdict on
    each, and the shape of every JSON response, with digit runs masked,
    and takes no screenshot. That file is what a tester attaches to the
    GitHub issue.
  * --discover reads statement dates from any control that looks like a
    statement or tax document, wherever it sits on the page.
  * --pilot tries to save the newest few, by fetching a PDF link the row
    carries from inside the page, or by clicking the row's own control
    and catching a download event, a PDF response or a new tab.

The guesses that most need confirming from a survey are marked GUESS. The
portal's routes are the biggest one. A borrower with several loans will
see them one at a time, and the first survey shows how.

SAFETY (this is a loan account that can take a payment):
  This module is strictly READ-ONLY. It opens the statements area, reads
  the list, and saves the PDFs the portal already generated. It must
  NEVER activate any control that makes or schedules a payment, enrolls in
  autopay, requests a hardship plan or a deferment, applies for anything,
  or edits any setting. FORBIDDEN_CONTROL_RE is the guard. A control must
  ALSO look like a document action (SAFE_DOC_CONTROL_RE) before it may be
  clicked. There is no code here that submits a form or confirms a dialog.
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

# Everything on its way into a diagnostic file goes through here. It
# lives in core because seventeen apps each had their own copy and
# they drifted into three different versions.
from paperpull_core.redact import redact, set_private_words  # noqa: F401
from paperpull_core.urls import is_safe_url as _host_allows
from paperpull_core.api_census import shape_of as _shape
from paperpull_core.dates import last_day as _last_day
from paperpull_core.dates import human_date as _human_date

log = logging.getLogger("sba_docs.site")

BASE = "https://lending.sba.gov"
# GUESS. The MySBA Loan Portal. Statements and tax forms hang off a loan,
# and the portal's routes are not documented anywhere public, so the list
# starts at the places the survey is most likely to find a way in from.
BILLING_CANDIDATES = [
    f"{BASE}/statements",
    f"{BASE}/documents",
    f"{BASE}/loans",
    f"{BASE}/",
]
BILLING_URL = BILLING_CANDIDATES[0]
URLS = {
    "home": f"{BASE}/",
    "login": f"{BASE}/",
    "documents": BILLING_URL,
    "statements": BILLING_URL,
}

# The portal signs in through login.gov or an SBA account on its own host.
LOGIN_URL_MARKERS = ["/login", "/signin", "/sign-in", "/auth", "/mfa",
                     "/verification", "/challenge", "login.gov", "/oauth", "/sso"]

# ---------------------------------------------------------------------------
# HARD SAFETY GUARD. Tuned for a loan servicer. Never pay, never apply,
# never ask for anything, never change a setting.
# ---------------------------------------------------------------------------
FORBIDDEN_CONTROL_RE = re.compile(
    r"(\bpay\b|payment|make\s+a\s+payment|schedule|autopay|auto\s*pay|recurring|"
    r"one[-\s]?time|\bbank\b|routing|account\s+number|debit|\bcard\b|"
    r"hardship|deferment|deferral|forbearance|modification|forgiveness|"
    r"\bapply\b|application|request|\bsubmit|upload|"
    r"enroll|unenroll|sign\s+up|paperless|"
    r"enable|disable|change\b|edit\b|update\b|modify|manage\b|"
    r"set\s+up|delete|remove|cancel|withdraw|"
    r"password|passcode|username|profile\b|settings|preferences|contact\s+info|\baddress\b|"
    r"confirm|agree|accept|authorize|certif|\bchat\b|contact\s+us|"
    r"payoff|pay\s+off|dispute|appeal)", re.I)

SAFE_DOC_CONTROL_RE = re.compile(
    r"(download|view|open|print|\bpdf\b|statement|document|\bletter\b|notice|"
    r"1098|1099|tax\s+(form|document)|history|"
    r"see\s+(more|all|older)|show\s+(more|all|older)|load\s+more)", re.I)

# A control that fetches one document. GUESS at the wording, wide on
# purpose. "View statement", "Download", "Statement PDF", "1098".
BILL_CONTROL_RE = re.compile(
    r"((download|view|print|open|get)\s*(my\s+|the\s+|this\s+|your\s+)?(statement|document|pdf|tax|letter|notice|1098|1099)|"
    r"(statement|document|tax\s+form|1098|1099)\s*\(?\s*pdf\s*\)?|\bpdf\b|"
    r"^\s*(view|download|open)\s*$)", re.I)

# A link that points straight at a PDF, from a row's href.
PDF_HREF_RE = re.compile(r"\.pdf(\?|$)|/pdf\b|format=pdf|statement.*download|download.*statement|documentId", re.I)

SECURITY_CHALLENGE_MARKERS = [
    "enter the code", "verification code", "6-digit", "two-factor",
    "two-step", "authenticator", "confirm your identity", "verify your identity",
    "we sent a code", "device approval", "approve this login", "unusual",
    "are you a robot", "captcha", "let's verify", "check your email",
    "check your phone", "your session has expired", "log back in",
    "access denied",
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
                "li[class*='document'], [class*='document'], [class*='loan']"),
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
    """Close a cookie banner, a survey prompt or a notice overlay, the
    things that sit over portal pages and intercept clicks. Escape first, then
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
    return bool(re.search(r"statements?|statement\s+(period|date)|tax\s+(form|document)|loan\s+(number|balance|details)",
                          body, re.I))


def goto_documents(page) -> bool:
    """Open the statements area. The first candidate that is not a
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
        tax = bool(re.search(r"1098|1099|tax", name + " " + row_text, re.I))
        kind_title = "Tax Document" if tax else "Loan Statement"
        docs.append(RawDoc(title=f"{kind_title} - {disp}", date_text=iso,
                           href=href if PDF_HREF_RE.search(href or "") else "",
                           text=f"SBA {kind_title} {disp}", row_index=i,
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
    only on sba.gov. None unless the answer is a PDF."""
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
        log.info("could not open the statements page for %s", iso_date)
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
# loan page shows names, numbers and balances. Digit runs are masked and
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
    r"^\s*((see|view|show)\s+)?(statements?|documents|tax\s+(forms|documents)|"
    r"statement\s+history|my\s+loans?|loan\s+details)\s*$", re.I)


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
    """What the signed-in loan portal looks like, without downloading
    anything. Records each page, its headings and controls with the
    guard's verdict on each, and every JSON or PDF response sba.gov sends
    while the page settles. Then follows, one at a time and back again,
    the few links whose text is a statements or loans word. No screenshot."""
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
ALLOWED_HOSTS = {"sba.gov"}


def is_safe_url(url: str) -> bool:
    """True only for an https URL on one of this provider's own hosts.

    The check itself lives in the core, so all of them answer the same way.
    This app keeps the hosts, which is the part that really is its own."""
    return _host_allows(url, ALLOWED_HOSTS)
