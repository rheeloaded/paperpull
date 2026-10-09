"""ALL coinbase.com selectors, URLs, and page behavior live here.

When Coinbase changes its site, repair this file only.

STATUS: mapped against a signed-in retail account on 2026-10-09. The two
ways a document arrives:

  * A monthly statement. accounts.coinbase.com/statements lists one row per
    complete month back to the account's first month, behind a "Load more"
    button, each row with HTML / PDF / CSV buttons. Pressing the row's PDF
    button makes the page itself ask Coinbase to build that month's PDF
    (a POST the page makes, not this app), poll for it, and then the browser
    downloads it from statements-report-persistent-production.s3.amazonaws.com.
    `_catch_statement` presses the one button and takes the download event
    only when its address is on that exact host. The "Last 30 days" row is
    a moving window, not a statement, and is skipped.
  * A tax form. The page's own list call, GET /v2/tax/forms?...&year=YYYY,
    returns each form with a short-lived link to its PDF on
    tax-center-forms-production.s3.amazonaws.com. `_collect_tax` reads the
    list for every year since the account's first transaction, and
    `_fetch_tax_pdf` asks the list again at download time and fetches the
    PDF from that exact host. Nothing is pressed, so the page's own
    mark-read / mark-downloaded calls, which its Download button makes, are
    never made. Pregenerated gain/loss reports (/v2/tax/tax-reports) are
    listed the same way, PDFs only.

Session: www.coinbase.com and accounts.coinbase.com share a sign-in through
login.coinbase.com; `page.goto` to accounts.coinbase.com stays signed in.

SAFETY (this is a crypto exchange account that can move money):
  This module is strictly READ-ONLY. It must NEVER activate any control
  that buys, sells, trades, converts, swaps, sends, receives, withdraws,
  deposits, transfers, stakes, borrows, pays, creates an order, API key,
  address or custom statement, or edits any setting. The only controls
  this app presses are a statement row's own PDF button and the list's
  "Load more", each through is_safe_control first. FORBIDDEN_CONTROL_RE is
  the guard; a control must ALSO look like a document action
  (SAFE_DOC_CONTROL_RE), and the shared core guards are consulted every
  time. A control whose label cannot be read is never clicked. The custom
  statement generator ("Generate") and the tax "Generate" report button are
  never touched. There is no code here that closes a banner, submits a form
  or confirms a dialog.

HOSTS: exact, no subdomain wildcard, and on accounts.coinbase.com only the
paths this app reads (ALLOWED_PATH_RE). A document is accepted from exactly
the two S3 hosts above (DOWNLOAD_HOSTS) and from nowhere else. A presigned
link is used once and never written anywhere; discovery keeps the form's
opaque id and the API path only.

KNOWN CEILINGS (ponytail: left as they are until a run shows otherwise)
  * The tax list's page cursor is sent as `cursor=`; next_cursor was empty on
    the account this was built on, so a non-empty one is untested.
  * The statements page's "Credit Card" tab is not read; the account this
    was built on has no Coinbase Card.
  * "Last 30 days" is skipped by design, it is not a statement.
"""
from __future__ import annotations

import logging
import re
import sys
from dataclasses import dataclass
from datetime import date as _date
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import urlsplit

from paperpull_core import redirects
from paperpull_core.controls import SETTINGS_CONTROL_RE, AUTH_CONTROL_RE
from paperpull_core.redact import redact, set_private_words  # noqa: F401  (re-exported)
from paperpull_core.urls import is_safe_url as _host_allows
from paperpull_core.api_census import shape_of as _shape
from paperpull_core.dates import last_day as _last_day
from paperpull_core.dates import checked as _checked_date
from paperpull_core.dates import full_year as _full_year
# re-exported: the docs module calls it as site.set_download_dir
from paperpull_core.capture import set_download_dir  # noqa: F401
from paperpull_core.capture import snapshot as _snapshot
from paperpull_core.capture import clear_copies as _clear_copies
from paperpull_core.controls import escape_for_locator
from paperpull_core.words import words_for as _words_for

log = logging.getLogger("coinbase_docs.site")


def _words():
    """This app's own words for paperpull_core.words."""
    return _words_for("Coinbase", sys.modules[__name__])


# ---------------------------------------------------------------------------
# Addresses
# ---------------------------------------------------------------------------
HOME = "https://www.coinbase.com"
BASE = "https://accounts.coinbase.com"
STATEMENTS_URL = f"{BASE}/statements"
TAX_URL = f"{BASE}/taxes/documents"
TAX_FORMS_API = f"{BASE}/v2/tax/forms"
TAX_REPORTS_API = f"{BASE}/v2/tax/tax-reports"
TAX_OWNER_API = f"{BASE}/v2/tax/owner-info"
BILLING_URL = STATEMENTS_URL
URLS = {
    "home": f"{HOME}/",
    "login": f"{HOME}/",
    "documents": STATEMENTS_URL,
    "statements": STATEMENTS_URL,
    "tax": TAX_URL,
}

# The form types the page itself asks for.
TAX_FORM_TYPES = ("1042-S", "1099-K", "1099-B", "1099-MISC", "1099-DA")

LOGIN_URL_MARKERS = ["/signin", "/sign-in", "/login", "/oauth", "/2fa", "/mfa",
                     "/verify", "/verification", "/challenge", "/sso",
                     "//login.coinbase.com"]

# ---------------------------------------------------------------------------
# HARD SAFETY GUARD. Tuned for an exchange. Every verb stem anchored on both
# sides so "Statements" is not "state" and "Downloads" is not "load".
# ---------------------------------------------------------------------------
FORBIDDEN_CONTROL_RE = re.compile(
    r"(\bbuy\b|\bsell\b|\btrad(e|es|ed|ing)\b|\bconvert(s|ed|ing)?\b|\bswap(s|ped|ping)?\b|"
    r"\bsend\b|\breceive\b|\bwithdraw(al|als|s)?\b|\bdeposit(s|ed)?\b|\btransfer(s|red|ring)?\b|"
    r"\bstak(e|es|ed|ing)\b|\bunstak(e|es|ed|ing)\b|\bearn\b|\bborrow\b|\blend(ing)?\b|\bloan\b|"
    r"\bcard\b|\bpay\b|\bpayment(s)?\b|\brecurring\b|\border(s)?\b|\badvanced\b|\bwallet\b|"
    r"\baddress(es)?\b|\bwhitelist\b|\ballowlist\b|\bapi\b|\bkey(s)?\b|"
    r"\bgenerat(e|es|ed|ing)\b|\bcreat(e|es|ed|ing)\b|\bcustom\b|\brequest(s|ed|ing)?\b|"
    r"\bapprov(e|es|ed|ing|al)\b|\bcontinue\b|\bsubmit\b|\bconfirm\b|\bagree\b|\baccept\b|"
    r"\bauthori[sz]e\b|\bverify\b|\bidentity\b|\bpassword\b|\bpasskey\b|\b2fa\b|\bsecurity\b|"
    r"\bsettings?\b|\bprofile\b|\benabl(e|es|ed|ing)\b|\bdisabl(e|es|ed|ing)\b|"
    r"\bchang(e|es|ed|ing)\b|\bedit(s|ed|ing)?\b|\bupdat(e|es|ed|ing)\b|\bdelet(e|es|ed|ing)\b|"
    r"\bremov(e|es|ed|ing)\b|\bcancel\b|\bclose\b|\bexport\b|\bemail\b|\bshare\b|"
    r"\bsign\s*up\b|\bupgrade\b|\bsubscribe\b|\bone\b|\bchat\b|\bcontact\b|\bmark\b)", re.I)

SAFE_DOC_CONTROL_RE = re.compile(
    r"(\bdownload\b|\bview\b|\bopen\b|\bprint\b|\bpdf\b|\bstatements?\b|\bdocuments?\b|"
    r"\btax\b|\b1099\b|\bgain\b|\bloss\b|\breport\b|\bhistory\b|"
    r"see\s+(more|all|older)|show\s+(more|all|older)|load\s+more|"
    r"(next|previous|first|last)\s+page|go\s+to\s+(first|last)\s+page)", re.I)

# A control that fetches one document, for the survey.
BILL_CONTROL_RE = re.compile(r"(^\s*download\b|^\s*pdf\b|\b1099\b|gain.{0,6}loss)", re.I)

SECURITY_CHALLENGE_MARKERS = [
    "enter the code", "verification code", "6-digit", "7-digit", "two-factor",
    "two-step", "authenticator", "confirm your identity", "verify your identity",
    "we sent a code", "device approval", "approve this login",
    "are you a robot", "captcha", "let's verify", "check your email",
    "check your phone", "your session has expired", "log back in",
    "access denied",
]

RATE_LIMIT_MARKERS = [
    "too many requests", "rate limit", "try again later",
    "temporarily unavailable", "http error 429", "unusual traffic",
]

# Fallback selectors (used by --diagnose only).
FALLBACK = {
    "doc_row": "button[data-testid='statements-pdf-v2']",
    "doc_link": "a[data-testid='statements-taxform-link']",
    "download_control": "button[data-testid='statements-pdf-v2']",
    "page_ready": "button[data-testid='statements-pdf-v2'], main",
    "next_page": "button[data-testid='load-more']",
}

# ---------------------------------------------------------------------------
# Date parsing (verbatim from the Nelnet app)
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


def _parse_date_from_page(text: str) -> Optional[str]:
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
                return f"{_full_year(m.group(3)):04d}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
            if kind == "iso":
                return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        except (KeyError, ValueError):
            continue
    return None


def parse_date(text):
    """The date this provider's page is showing, as YYYY-MM-DD.

    The reading is below, unchanged. This only refuses to believe a result
    that names a day which does not exist, because a reference number is
    shaped like a date and used to be taken for one."""
    return _checked_date(_parse_date_from_page(text), None)


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
    return bool(_WORD_VALUE_RE.match(v or ""))


def _safe_query(url: str) -> str:
    """A URL's query parameters, names always, values only when they are
    plain words. A value with a digit, a token, an id, anything long, is
    "..."."""
    from urllib.parse import parse_qsl
    try:
        pairs = parse_qsl(urlsplit(url).query, keep_blank_values=True)
    except ValueError:
        return ""
    out = []
    for k, v in pairs[:20]:
        out.append("%s=%s" % (k[:30], v if _plain_word(v) else "..."))
    return "&".join(out)


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
    Visible text only. A page that shows a statement row is not a
    challenge, whatever its text says further down."""
    try:
        if page.locator(FALLBACK["doc_row"]).count() > 0:
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
    """Deny by default: an unreadable label is refused, then this app's
    blocklist, then the shared core guards, and only then the document
    allowlist."""
    name = re.sub(r"\s+", " ", name or "").strip()
    if not name:
        return False
    if FORBIDDEN_CONTROL_RE.search(name):
        return False
    if SETTINGS_CONTROL_RE.search(name) or AUTH_CONTROL_RE.search(name):
        return False
    return bool(SAFE_DOC_CONTROL_RE.search(name))


# ---------------------------------------------------------------------------
# Hosts. Exact, parsed, no subdomain wildcard, and on the accounts host only
# the paths this app reads or the page itself calls while it is open.
# ---------------------------------------------------------------------------
ALLOWED_HOSTS = {"accounts.coinbase.com", "www.coinbase.com"}
DOWNLOAD_HOSTS = {"statements-report-persistent-production.s3.amazonaws.com",
                  "tax-center-forms-production.s3.amazonaws.com"}
ALLOWED_PATH_RE = re.compile(
    r"^/(statements|taxes|taxes/documents|v2/tax/forms|v2/tax/tax-reports|"
    r"v2/tax/owner-info|v1/statements(/[A-Za-z0-9._-]+){0,3})/?$")


def is_safe_url(url: str) -> bool:
    """True only for an https URL on exactly one of this provider's hosts,
    and only for a path this app has business with: on accounts.coinbase.com
    the two document pages and the list calls, on www.coinbase.com the
    sign-in landing alone. Nothing on www is ever fetched."""
    if not _host_allows(url, ALLOWED_HOSTS, subdomains=False):
        return False
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    host = (parts.hostname or "").lower()
    if host == "accounts.coinbase.com":
        return bool(ALLOWED_PATH_RE.match(parts.path or ""))
    # www.coinbase.com is where the sign-in window opens and lands. Any
    # other page there, the markets, a trade screen, is not this app's and
    # is never chosen as its tab.
    return (parts.path or "/").rstrip("/") in ("", "/home")


def is_download_url(url: str) -> bool:
    """True only for an https address on exactly one of the two hosts the
    site was seen handing documents from. Checked before any document is
    taken, whether the browser downloaded it or this app asked for it."""
    return _host_allows(url, DOWNLOAD_HOSTS, subdomains=False)


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------

@dataclass
class RawDoc:
    title: str
    account: str = ""
    date_text: str = ""
    href: str = ""
    text: str = ""
    row_index: int = -1
    kind: str = "doc"


class ListStopped(Exception):
    """The list has a part this could not read, so what was read is not all
    of it. `docs` holds what was read before it stopped."""

    def __init__(self, why: str, docs=None):
        super().__init__(why)
        self.docs = list(docs or [])


_PDF_BTN = "button[data-testid='statements-pdf-v2']"
_LOAD_MORE = "button[data-testid='load-more']"
_MAX_LOAD_MORE = 60
_MONTH_ROW_RE = re.compile(r"^(January|February|March|April|May|June|July|August|September|"
                           r"October|November|December) ((?:19|20)\d{2})$")
_STATEMENT_TITLE_RE = re.compile(r"^Monthly Statement ((?:January|February|March|April|May|June|"
                                 r"July|August|September|October|November|December) (?:19|20)\d{2})$")
_TAX_TITLE_RE = re.compile(r"^(.+?) Tax Year ((?:19|20)\d{2})(?: \(#([A-Za-z0-9]{1,40})\))?$")

# Each PDF button with the label of the row it sits in, "September 2026" or
# "Last 30 days", read from the page without pressing anything. The row is
# the nearest ancestor whose text starts with such a label.
_ROWS_JS = r"""() => [...document.querySelectorAll("button[data-testid='statements-pdf-v2']")].map((b, i) => {
  let el = b;
  for (let k = 0; k < 8 && el; k++, el = el.parentElement) {
    const t = (el.innerText || '').trim();
    const m = t.match(/^(Last 30 days|[A-Z][a-z]+ (?:19|20)\d{2})(?!\S)/);
    if (m) return {label: m[1], button: (b.innerText || b.getAttribute('aria-label') || '').trim(), i: i};
  }
  return {label: '', button: (b.innerText || b.getAttribute('aria-label') || '').trim(), i: i};
})"""


def month_to_iso(label: str) -> str:
    """"September 2026" -> "2026-09-30", the statement's own last day, or ""."""
    m = _MONTH_ROW_RE.match((label or "").strip())
    if not m:
        return ""
    year, month = int(m.group(2)), _MONTHS[m.group(1)[:3].lower()]
    return f"{year:04d}-{month:02d}-{_last_day(year, month):02d}"


def _read_rows(page) -> list:
    try:
        return page.evaluate(_ROWS_JS) or []
    except Exception:
        return []


def row_index_for(rows: list, label: str) -> Tuple[int, str]:
    """(index, button label) of the one PDF button whose row reads exactly
    `label`, or (-1, ""). Two rows with one label is a page this cannot
    read, and nothing is chosen."""
    hits = [r for r in rows if (r.get("label") or "") == label]
    if len(hits) != 1:
        return -1, ""
    return int(hits[0].get("i", -1)), hits[0].get("button") or ""


def _wait_for_list(page, timeout_ms: int = 30000) -> bool:
    try:
        page.wait_for_selector(_PDF_BTN, timeout=timeout_ms)
        return True
    except Exception:
        return False


def goto_documents(page) -> bool:
    """Open the statements page by its address. No click, no banner
    handling: a banner is for the account holder to close in the window."""
    here = page.url or ""
    if here.split("?")[0].rstrip("/") == STATEMENTS_URL and is_safe_url(here) \
            and not looks_signed_out(page) and _wait_for_list(page, 5000):
        return True
    try:
        page.goto(STATEMENTS_URL, wait_until="domcontentloaded", timeout=60000)
    except Exception as e:
        log.info("goto %s failed: %s", STATEMENTS_URL, e)
        return False
    if looks_signed_out(page):
        return False
    return _wait_for_list(page)


def scroll_full_page(page, rounds: int = 8, delay_ms: int = 600) -> None:
    try:
        for _ in range(rounds):
            page.mouse.wheel(0, 3000)
            page.wait_for_timeout(delay_ms)
        page.keyboard.press("End")
        page.wait_for_timeout(delay_ms)
    except Exception:
        pass


def _press_load_more(page) -> bool:
    """Press the list's Load more once. False when there is none left. Its
    own label goes through the guard first. Pressed with the rows still the
    same after about ten seconds, or refused, raises ListStopped: both used
    to read as the end of the list."""
    try:
        btn = page.locator(_LOAD_MORE).first
        if btn.count() == 0 or not btn.is_visible():
            return False
        label = (btn.inner_text(timeout=1000) or btn.get_attribute("aria-label") or "")
    except Exception as e:
        raise ListStopped("its Load more could not be read (%s)" % type(e).__name__)
    if not is_safe_control(label):
        raise ListStopped("the guard refused its Load more button")
    before = page.locator(_PDF_BTN).count()
    try:
        btn.click(timeout=5000)
    except Exception as e:
        raise ListStopped("its Load more could not be pressed (%s)" % type(e).__name__)
    for _ in range(34):
        page.wait_for_timeout(300)
        if page.locator(_PDF_BTN).count() > before:
            return True
    raise ListStopped("the rows stayed the same after Load more was pressed")


def expand_all(page) -> None:
    """Load the whole list. The row count only ever grows."""
    for _ in range(_MAX_LOAD_MORE):
        if not _press_load_more(page):
            return
    raise ListStopped("it runs past %d presses of Load more" % _MAX_LOAD_MORE)


def _collect_statements(page) -> List[RawDoc]:
    """One RawDoc per complete month on the statements page, newest first.
    "Last 30 days" is a moving window and is skipped."""
    docs: List[RawDoc] = []
    seen = set()
    try:
        expand_all(page)
        rows = _read_rows(page)
        if not rows:
            raise ListStopped("no statement rows could be read")
        for r in rows:
            label = r.get("label") or ""
            if not label:
                raise ListStopped("a statement row has no month label this can read")
            iso = month_to_iso(label)
            if not iso:
                if label == "Last 30 days":
                    continue
                raise ListStopped("a statement row reads %r, not a month" % label[:30])
            if iso in seen:
                raise ListStopped("two statement rows read %s" % label)
            seen.add(iso)
            docs.append(RawDoc(title=f"Monthly Statement {label}", date_text=iso,
                               text=f"Coinbase Monthly Statement {label}",
                               row_index=len(docs), kind="statement"))
    except ListStopped as stop:
        stop.docs = docs
        raise
    return docs


# -- tax forms, read from the list call the page itself makes ---------------

def _get_json(page, url: str):
    """GET an allowed address with the signed-in session, every redirect hop
    checked. The JSON, or None when the answer was not ok or not JSON."""
    if not is_safe_url(url):
        raise RuntimeError("refusing to ask an address off the app's own hosts")
    resp = redirects.get(page.context.request, url, is_safe_url, timeout=60000)
    if not resp.ok:
        log.warning("%s answered %s", redact(url.split("?")[0]), resp.status)
        return None
    try:
        return resp.json()
    except Exception:
        return None


def _first_tax_year(page) -> int:
    """The year of the account's first transaction, from owner-info, or
    2012, Coinbase's own first year."""
    data = _get_json(page, TAX_OWNER_API) or {}
    first = str(data.get("first_transaction_date") or "")
    m = re.match(r"((?:19|20)\d{2})-", first)
    return int(m.group(1)) if m else 2012


def _tax_forms_for(page, year: int) -> list:
    """The forms the list call returns for `year`, every page of it."""
    types = "&".join("types=%s" % t for t in TAX_FORM_TYPES)
    url = f"{TAX_FORMS_API}?{types}&sort_direction=DESC&year={year}&is_hidden=false"
    items: list = []
    cursor = ""
    for _ in range(20):
        data = _get_json(page, url + ("&cursor=%s" % cursor if cursor else ""))
        if data is None or not isinstance(data.get("data"), list):
            raise ListStopped("the tax forms list for %d could not be read" % year)
        items.extend(data["data"])
        nxt = str(data.get("next_cursor") or "")
        if not nxt:
            return items
        if nxt == cursor:
            raise ListStopped("the tax forms list for %d repeats a page cursor" % year)
        cursor = nxt
    raise ListStopped("the tax forms list for %d runs past 20 pages" % year)


def _tax_reports(page) -> list:
    """The pregenerated reports, PDFs only."""
    url = (f"{TAX_REPORTS_API}?from_date=2012-01-01T00:00:00Z"
           f"&to_date={_date.today().year}-12-31T23:59:59Z&limit=200")
    data = _get_json(page, url)
    if data is None or not isinstance(data.get("data"), list):
        raise ListStopped("the tax reports list could not be read")
    return [r for r in data["data"]
            if str((r.get("file") or {}).get("file_type") or "").lower() == "pdf"]


def _short(doc_id: str) -> str:
    """The id as a title suffix: its whole self, letters and digits only, so
    two ids never share a suffix."""
    return re.sub(r"[^A-Za-z0-9]", "", str(doc_id or ""))[:40]


def _report_summary(name: str) -> str:
    """"PregeneratedGainLossPDF" -> "Gain Loss Report"."""
    n = re.sub(r"^Pregenerated", "", str(name or ""))
    n = re.sub(r"(PDF|CSV)$", "", n)
    n = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", n).strip()
    return (n + " Report") if n else "Tax Report"


def tax_rawdocs(forms_by_year: dict, reports: list) -> List[RawDoc]:
    """RawDocs for the forms and PDF reports, titled "<form> Tax Year YYYY",
    with a short id suffix only where one year has two of the same form,
    so a corrected form is not lost under the original's title. href holds
    the API path and the opaque id only, never a link."""
    out: List[RawDoc] = []
    counts: dict = {}
    for year, items in forms_by_year.items():
        for it in items:
            ft = str(it.get("form_type") or "Tax Form").strip()
            counts[(ft, year)] = counts.get((ft, year), 0) + 1
    for year, items in sorted(forms_by_year.items(), reverse=True):
        for it in items:
            ft = str(it.get("form_type") or "Tax Form").strip()
            did = str(it.get("id") or "")
            title = f"{ft} Tax Year {year}"
            if counts[(ft, year)] > 1 and did:
                title += f" (#{_short(did)})"
            out.append(RawDoc(title=title, date_text=f"{year}-12-31",
                              href=f"/v2/tax/forms/{did}" if did else "/v2/tax/forms",
                              text=f"Coinbase {title}", kind="tax"))
    rcounts: dict = {}
    for r in reports:
        year = r.get("year") or r.get("timeframe_year")
        key = (_report_summary(r.get("name")), year)
        rcounts[key] = rcounts.get(key, 0) + 1
    for r in reports:
        year = r.get("year") or r.get("timeframe_year")
        if not year:
            continue
        did = str(r.get("id") or "")
        summary = _report_summary(r.get("name"))
        title = f"{summary} Tax Year {year}"
        if rcounts[(summary, year)] > 1 and did:
            title += f" (#{_short(did)})"
        out.append(RawDoc(title=title, date_text=f"{year}-12-31",
                          href=f"/v2/tax/tax-reports/{did}" if did else "/v2/tax/tax-reports",
                          text=f"Coinbase {title}", kind="tax"))
    return out


def _collect_tax(page) -> List[RawDoc]:
    """Every tax form and pregenerated PDF report, from the list calls, for
    every year since the first transaction. A year that cannot be read
    raises ListStopped, never an empty year."""
    this_year = _date.today().year
    forms = {}
    for year in range(_first_tax_year(page), this_year + 1):
        forms[year] = _tax_forms_for(page, year)
    return tax_rawdocs(forms, _tax_reports(page))


def collect_download_docs(page) -> List[RawDoc]:
    """Every monthly statement and every tax document. Nothing is pressed
    except Load more. A statements list that stopped partway still has the
    tax documents read, and then raises ListStopped holding everything."""
    docs: List[RawDoc] = []
    stopped = None
    if not goto_documents(page):
        raise ListStopped("the statements page did not open")
    try:
        docs.extend(_collect_statements(page))
    except ListStopped as stop:
        docs.extend(stop.docs)
        stopped = stop
    try:
        docs.extend(_collect_tax(page))
    except ListStopped as stop:
        stop.docs = docs
        raise
    if stopped is not None:
        stopped.docs = docs
        raise stopped
    return docs


# -- downloads --------------------------------------------------------------

def _pdf_url_of(item: dict) -> str:
    files = item.get("files")
    if isinstance(files, list):
        for f in files:
            if str((f or {}).get("file_type") or "").lower() == "pdf":
                return str(f.get("url") or "")
    f = item.get("file")
    if isinstance(f, dict) and str(f.get("file_type") or "").lower() == "pdf":
        return str(f.get("url") or "")
    return ""


def _fetch_tax_pdf(page, title: str, out_path: Path, trace: Optional[list]) -> bool:
    """Ask the list again for the document titled `title`, then fetch its
    PDF from its short-lived link, only when that link is on an exact
    download host. The link is used once and written nowhere."""
    m = _TAX_TITLE_RE.match((title or "").strip())
    if not m:
        return False
    summary, year, short = m.group(1), int(m.group(2)), m.group(3) or ""
    try:
        if summary.endswith(" Report"):
            items = [r for r in _tax_reports(page) if int(r.get("year") or r.get("timeframe_year") or 0) == year
                     and _report_summary(r.get("name")) == summary]
        else:
            items = [it for it in _tax_forms_for(page, year)
                     if str(it.get("form_type") or "").strip() == summary]
        # The suffix, when the title carries one, names the one document;
        # without one the title has to name exactly one by itself.
        if short:
            items = [it for it in items if _short(it.get("id")) == short]
        elif len(items) > 1:
            items = []
    except ListStopped as stop:
        log.info("could not read the list for %s: %s", title, stop)
        return False
    if len(items) != 1:
        log.info("no single listed document matches %r (%d)", title, len(items))
        if trace is not None:
            trace.append({"note": "the list did not name this document once", "matches": len(items)})
        return False
    url = _pdf_url_of(items[0])
    host = urlsplit(url).hostname or ""
    if not is_download_url(url):
        log.info("refusing a document link on host %r", host)
        if trace is not None:
            trace.append({"note": "document link refused", "host": host})
        return False
    try:
        resp = page.context.request.get(url, max_redirects=0, timeout=60000)
    except Exception as e:
        if trace is not None:
            trace.append({"note": "fetch failed", "host": host, "error": str(e)[:160]})
        return False
    if trace is not None:
        trace.append({"note": "fetched", "host": host, "status": resp.status})
    body = resp.body() if resp.ok else b""
    if body[:5] != b"%PDF-":
        return False
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(body)
    return True


def _catch_statement(page, dl_dir, label: str, out_path: Path, trace: Optional[list]) -> bool:
    """Press the PDF button of the row that reads `label`, once, and take
    the download the browser then makes, only when it comes from an exact
    download host. A file that lands with no event, or from any other
    host, is not taken."""
    rows = _read_rows(page)
    idx, btn_label = row_index_for(rows, label)
    try:
        # Load more only while the month is not on the page yet; the list
        # is newest first, so an older month needs more presses, a recent
        # one none.
        for _ in range(_MAX_LOAD_MORE):
            if idx >= 0 or not _press_load_more(page):
                break
            rows = _read_rows(page)
            idx, btn_label = row_index_for(rows, label)
    except ListStopped as stop:
        log.info("the list stopped while looking for %s: %s", label, stop)
    if idx < 0:
        if trace is not None:
            trace.append({"note": "no single row reads this label", "rows": len(rows)})
        return False
    if not is_safe_control(btn_label):
        log.info("refusing unsafe control %r for %s", btn_label, label)
        return False
    el = page.locator(_PDF_BTN).nth(idx)
    downloads: list = []
    def on_download(dl):
        # A plain function: Playwright tags the handler it is given, which a
        # bound builtin cannot carry, and one object so remove_listener finds it.
        downloads.append(dl)
    page.on("download", on_download)
    before = _snapshot(dl_dir)
    try:
        try:
            el.scroll_into_view_if_needed(timeout=4000)
        except Exception:
            pass
        try:
            el.click(timeout=8000)
        except Exception as e:
            if trace is not None:
                trace.append({"note": "click failed", "control": btn_label[:40], "error": str(e)[:160]})
            return False
        if trace is not None:
            trace.append({"note": "clicked", "control": btn_label[:40]})
        # The page asks Coinbase to build the month's PDF and polls for it;
        # measured at well under a minute.
        for _ in range(120):
            if downloads:
                break
            page.wait_for_timeout(1000)
        if not downloads:
            if trace is not None:
                trace.append({"note": "no download event within two minutes"})
            return False
        dl = downloads[0]
        host = urlsplit(dl.url or "").hostname or ""
        if not is_download_url(dl.url or ""):
            log.info("refusing a download from host %r", host)
            if trace is not None:
                trace.append({"note": "download refused", "host": host})
            try:
                dl.cancel()
            except Exception:
                pass
            return False
        how = _take_event(page, dl, out_path)
        if trace is not None:
            trace.append({"note": "download taken" if how else "download not taken", "host": host, "how": how})
        return bool(how)
    finally:
        try:
            page.remove_listener("download", on_download)
        except Exception:
            pass
        try:
            _clear_copies(dl_dir, before, out_path)
        except Exception:
            pass


def _take_event(page, dl, out_path: Path) -> str:
    """The bytes of a download whose address passed is_download_url: the
    event's own file when the browser gives one, else a GET of that same
    address with the session's cookies and no redirect. Says "event" or
    "fetch", or "" when neither held a PDF. A file found in the download
    folder is never taken, since nothing ties a file there to this press
    (round-3 review, finding 2)."""
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        dl.save_as(str(out_path))
        if out_path.exists() and out_path.read_bytes()[:5] == b"%PDF-":
            return "event"
    except Exception as e:
        log.info("saving the download event failed: %s", e)
    try:
        if out_path.exists():
            out_path.unlink()
    except OSError:
        pass
    # Asked up to three times: the bucket hung up on two of sixty-six asks
    # in the first full run, right after the browser had taken its own copy.
    # Only the error's kind is logged, since Playwright's message carries
    # the whole presigned address.
    body = b""
    for attempt in range(3):
        try:
            resp = page.context.request.get(dl.url, max_redirects=0, timeout=60000)
            body = resp.body() if resp.ok else b""
            if body[:5] == b"%PDF-":
                break
            log.info("the download's own address answered %s without a PDF", resp.status)
        except Exception as e:
            log.info("fetching the download's own address failed (%s), try %d of 3",
                     type(e).__name__, attempt + 1)
        try:
            page.wait_for_timeout(2000)
        except Exception:
            pass
    if body[:5] != b"%PDF-":
        return ""
    out_path.write_bytes(body)
    return "fetch"


def download_bill(page, dl_dir, iso_date: str, out_path, title: str = "",
                  trace: Optional[list] = None) -> bool:
    """Save the document titled `title`, dated `iso_date`. A tax document is
    fetched from its listed link, nothing pressed. A monthly statement is
    taken by pressing its row's own PDF button once and catching the
    download, which is how the site hands one over."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    t = (title or "").strip()
    if _TAX_TITLE_RE.match(t):
        return _fetch_tax_pdf(page, t, out_path, trace)
    m = _STATEMENT_TITLE_RE.match(t)
    if not m:
        log.info("not a title this app knows how to fetch: %r", t)
        return False
    if month_to_iso(m.group(1)) != iso_date:
        log.info("title %r and date %s disagree", t, iso_date)
        return False
    if not goto_documents(page):
        log.info("could not open the statements page for %s", iso_date)
        return False
    return _catch_statement(page, dl_dir, m.group(1), out_path, trace)


# ---------------------------------------------------------------------------
# Diagnose. Loose, redacted scrape and a survey of the signed-in pages.
# No screenshot.
# ---------------------------------------------------------------------------
_ROW_JS = r"""() => {
  const out = [];
  for (const tr of document.querySelectorAll('table tr, [role=row], li, [class*="statement" i], [class*="document" i]')) {
    const txt = (tr.innerText || '').trim();
    if (!txt) continue;
    const link = tr.querySelector("a[href]");
    out.push({text: txt.slice(0, 200), href: link ? link.getAttribute('href') : ''});
  }
  return out.slice(0, 200);
}"""

SURVEY_LINK_RE = re.compile(r"^\s*(statements?|documents?|view\s+tax\s+forms|tax\s+documents?)\s*$", re.I)
def collect_documents(page) -> List[RawDoc]:
    """Loose row scrape used only by --diagnose, digits masked."""
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


def survey(page, dwell_ms: int = 4000, max_follow: int = 0) -> dict:
    """What the signed-in page looks like, without downloading anything.
    Records the page's headings and controls with the guard's verdict, and
    the path, status and shape of every JSON or PDF response an allowed host
    sends while the page settles. Follows nothing: the only controls this
    app ever presses are a statement row's PDF button and Load more, and a
    survey is not a reason to press a third kind. Query strings are not
    kept, not even as names. No screenshot."""
    seen: list = []

    def on_response(res):
        try:
            url = res.url or ""
            if not is_safe_url(url):
                return
            ct = (res.headers.get("content-type") or "").lower()
            if "json" not in ct and "pdf" not in ct:
                return
            entry = {"path": redact(urlsplit(url).path)[:200], "status": res.status, "type": ct[:40]}
            try:
                entry["method"] = res.request.method
            except Exception:
                pass
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
        report["pages"].append(_page_summary(page))
    finally:
        try:
            page.remove_listener("response", on_response)
        except Exception:
            pass
    return report
