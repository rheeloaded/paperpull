"""ALL verizon.com selectors, URLs, and page behavior live here, for the
WIRELESS side of My Verizon. The Fios side has its own app, apps/verizon.

When Verizon changes its site, repair this file only.

STATUS: CONFIRMED 2026-10-29 on a real account (24 bills, issue #31), with
nothing pressed by the app. A signed-in survey showed:

  * Bill & payment history, /digital/nsa/secure/ui/bill/history/, asks
    GET /digital/nsa/secure/gw/bill/billpaymenthistory/bill_history with
    headers of its own (channelId, session_id and others). The answer's
    body.billingHistory.billCycle lists every cycle My Verizon keeps (24),
    each with billEndDate (MM/DD/YYYY), though the page draws nine until
    Show more. Each cycle offers "Review bill" and "Review bill PDF".
  * "Review bill PDF" opens GET
    /digital/nsa/secure/gw/bill/billpaymenthistory/bill_pdfdoc?
    startMonthDate=<billEndDate>&channelId=<the page's channelId header>
    in a new tab: application/pdf, a body starting %PDF, the session's
    cookies and nothing else.
  * So a run opens the history page by its address, takes the page's own
    bill_history answer and channelId, and asks each cycle's bill_pdfdoc
    from inside the page. Nothing is clicked; Diagnose follows nothing.
  * --login opens a real Edge or Chrome, since verizon.com runs bot
    protection that walls the Playwright build of Chromium.

SAFETY (this is a phone account with a card on file):
  This module is strictly READ-ONLY. It opens the bill history, reads the
  list of past bills, and saves the PDFs Verizon already generated. It
  must NEVER activate any control that pays a bill, enrolls in autopay or
  paperless, changes a plan, adds a line, upgrades or trades in a device,
  suspends or restores service, moves a number, or edits any setting.
  FORBIDDEN_CONTROL_RE is the guard. A control must ALSO look like a
  document action (SAFE_DOC_CONTROL_RE) before it may be clicked. There is
  no code here that submits a form or confirms a dialog.
"""
from __future__ import annotations

import logging
from datetime import date as _date
from urllib.parse import parse_qs, urlencode, urlsplit
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from paperpull_core import intake
from paperpull_core.controls import SETTINGS_CONTROL_RE, AUTH_CONTROL_RE
from paperpull_core.controls import dismiss_overlays as _dismiss_overlays

# Everything on its way into a diagnostic file goes through here. It
# lives in core because seventeen apps each had their own copy and
# they drifted into three different versions.
from paperpull_core.redact import redact, set_private_words  # noqa: F401
from paperpull_core.redact import private_words as _private_words
from paperpull_core.urls import is_safe_url as _host_allows
from paperpull_core.api_census import shape_of as _shape
from paperpull_core.dates import last_day as _last_day
from paperpull_core.dates import human_date as _human_date
# re-exported: this app's docs module calls it as site.set_download_dir
from paperpull_core.capture import set_download_dir  # noqa: F401
from paperpull_core.capture import snapshot as _snapshot
from paperpull_core.capture import take_download as _take_download
from paperpull_core.capture import is_document as _is_document
from paperpull_core.capture import clear_copies as _clear_copies
from paperpull_core.capture import ask_again as _ask_again
from paperpull_core.capture import RequestsSince as _RequestsSince
from paperpull_core.capture import take_new_pdf as _take_new_pdf
from paperpull_core.capture import fetch_pdf as _core_fetch_pdf
from paperpull_core.capture import take_new_tab as _core_take_new_tab
from paperpull_core.capture import take_same_tab as _core_take_same_tab
from paperpull_core.controls import control_texts as _control_texts
from paperpull_core.controls import place_of as _place_of
from paperpull_core.controls import second_step as _core_second_step
from paperpull_core.controls import controls_named as _controls_named
from paperpull_core.controls import escape_for_locator
from paperpull_core.dates import checked as _checked_date
from paperpull_core.dates import full_year as _full_year
from paperpull_core import pressing
from paperpull_core.words import words_for as _words_for
from paperpull_core.characters import whole_json

log = logging.getLogger("verizonmobile_docs.site")


def _words():
    """This app's own words for paperpull_core.words, from what its source
    calls it, for saying what covered a control."""
    return _words_for("Verizon Mobile", sys.modules[__name__])


BASE = "https://www.verizon.com"
# GUESS. My Verizon's wireless pages live under /digital/nsa/secure/ui/.
# The bill page is where the current and past bills are, with a Download
# PDF control per bill. The Download Your Bill page is the one the Fios app
# drives and may serve wireless accounts too, so it is the fallback.
BILLING_CANDIDATES = [
    f"{BASE}/digital/nsa/secure/ui/bill/",
    f"{BASE}/digital/nsa/secure/ui/bill/history/",
    f"{BASE}/downloadbill/#/download",
]
BILLING_URL = BILLING_CANDIDATES[0]
URLS = {
    "home": f"{BASE}/digital/nsa/secure/ui/",
    # Signing in to the billing page sends an unauthenticated user through
    # Verizon Mobile's sign-in and back.
    "login": BILLING_URL,
    "documents": BILLING_URL,
    "statements": BILLING_URL,
}

# Sign-in is on secure.verizon.com, a subdomain, so it is inside the
# allowlist. A page whose path says sign-in is still treated as signed out.
LOGIN_URL_MARKERS = ["/login", "/signin", "/sign-in", "/auth", "/mfa",
                     "/verification", "/challenge", "/idp/", "/account/login"]

# ---------------------------------------------------------------------------
# HARD SAFETY GUARD. Tuned for a wireless carrier. Never pay, never change
# service, never touch a device or a number, never edit the account.
# ---------------------------------------------------------------------------
FORBIDDEN_CONTROL_RE = re.compile(
    r"(pay\b|payment|pay\s+bill|autopay|auto\s*pay|schedule\s+payment|"
    r"one[-\s]?time\s+payment|payment\s+(plan|arrangement)|make\s+a\s+payment|"
    r"bank\b|routing|account\s+number|debit|credit\s+card|\bcard\b|wallet|"
    r"enroll|unenroll|sign\s+up|start\s+service|stop\s+service|"
    r"add\s+(a\s+)?line|add[-\s]?on|change\s+plan|\bplans?\b|upgrade|trade[-\s]?in|"
    r"\bbuy\b|\bshop\b|\border\b|\bcart\b|checkout|\bdeals?\b|\boffers?\b|"
    r"transfer\s+(service|number)|port\b|\bsim\b|esim|suspend|restore|"
    r"disconnect|reconnect|new\s+service|move\b|international|roaming|"
    r"enable|disable|activate|deactivate|change\b|edit\b|update\b|modify|manage\b|"
    r"set\s+up|delete|remove|cancel|close\s+account|"
    r"password|passcode|profile\b|settings|preferences|paperless|"
    r"confirm|submit|agree|accept|authorize|\bchat\b|contact\s+us)", re.I)

SAFE_DOC_CONTROL_RE = re.compile(
    r"(download|view|open|print|\bpdf\b|statement|document|\bbill\b|bills\b|"
    r"invoice|history|see\s+(more|all|older)|show\s+(more|all|older)|load\s+more)", re.I)

# A control that fetches one bill. GUESS at the wording, wide on purpose.
# "Download bill (PDF)", "View bill", "Print bill", "See bill", "Bill PDF".
BILL_CONTROL_RE = re.compile(
    r"((download|view|print|see|open|get)\s+(my\s+|the\s+|this\s+|your\s+|full\s+|"
    r"detailed\s+|past\s+)?(bill|statement|invoice)|"
    r"(bill|statement|invoice)\s*\(?\s*pdf\s*\)?|\bpdf\b)", re.I)

# A link that points straight at a bill PDF, from a row's href.
PDF_HREF_RE = re.compile(r"\.pdf(\?|$)|/pdf\b|format=pdf|bill.*download|download.*bill", re.I)

SECURITY_CHALLENGE_MARKERS = [
    "enter the code", "verification code", "6-digit", "two-factor",
    "two-step", "authenticator", "confirm your identity", "verify your identity",
    "we sent a code", "device approval", "approve this login", "unusual",
    "are you a robot", "captcha", "let's verify", "check your email",
    "check your phone", "your session has expired", "log back in",
    "access denied", "reference #",   # the bot wall, when it fires
]

RATE_LIMIT_MARKERS = [
    "too many requests", "rate limit", "try again later",
    "temporarily unavailable", "http error 429", "unusual traffic",
]

# ---------------------------------------------------------------------------
# Fallback selectors (used by --diagnose only)
# ---------------------------------------------------------------------------
FALLBACK = {
    "doc_row": ("table tbody tr, [role='row'], [class*='bill'], [class*='Bill'], "
                "li[class*='history'], [class*='statement']"),
    "doc_link": "a[href*='.pdf'], a[download], button[class*='download']",
    "download_control": "a[download], a[href$='.pdf'], button:has-text('Download')",
    "page_ready": "table, [role='row'], [class*='bill'], main, [role='main']",
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
    """"STATEMENT", "LAST_90_DAYS", not an id, a token or a number."""
    return bool(_WORD_VALUE_RE.match(v)) and sum(ch.isdigit() for ch in v) <= 3


def _safe_query(url: str) -> str:
    """A URL's query parameters, names always, values only when they are
    plain words ("docType=STATEMENT", "range=LAST_90_DAYS"). A value with
    a digit, a token, an id, anything long, is "...". This is what a
    repair needs to make the same call with a wider filter, and nothing
    else."""
    from urllib.parse import parse_qs, parse_qsl, urlencode, urlsplit
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
        if page.get_by_text(re.compile(r"^Review bill PDF$")).count() > 0:
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


HISTORY_PATH = "/digital/nsa/secure/ui/bill/history/"
HISTORY_URL = BASE + HISTORY_PATH
HISTORY_API_PATH = "/digital/nsa/secure/gw/bill/billpaymenthistory/bill_history"
PDF_PATH = "/digital/nsa/secure/gw/bill/billpaymenthistory/bill_pdfdoc"
BILL_ID_RE = re.compile(r"bill-[0-9]{4}-[0-9]{2}-[0-9]{2}")
_END_DATE_RE = re.compile(r"([0-9]{2})/([0-9]{2})/([0-9]{4})")
_CHANNEL_RE = re.compile(r"[A-Za-z0-9_-]{1,40}")
MAX_LIST_BYTES = 5 * 1024 * 1024
MAX_PDF_BYTES = 25 * 1024 * 1024


@dataclass
class RawDoc:
    title: str
    account: str = ""
    date_text: str = ""
    href: str = ""
    text: str = ""
    row_index: int = -1
    kind: str = "doc"
    document_id: str = ""
    # The cycle's bill end date as the API writes it, MM/DD/YYYY, which is
    # what a bill's PDF is asked for by. Not recorded.
    end_date: str = ""


class ListStopped(Exception):
    """The list has a part this could not read, so what was read is not all
    of it. `docs` holds what was read before it stopped."""

    def __init__(self, why: str, docs=None):
        super().__init__(why)
        self.docs = list(docs or [])


class SessionExpired(Exception):
    """Verizon answered as a signed-out session."""


@dataclass
class _History:
    answer: dict
    channel: str


def _is_history_answer(url: str) -> bool:
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    return parts.netloc == "www.verizon.com" and parts.path == HISTORY_API_PATH


def _open(page, timeout_ms: int = 45000) -> _History:
    """Open Bill & payment history by its address and take the bill history
    the page itself asks for, with the channelId its own request carries.
    Raises SessionExpired when the site shows its sign-in and ListStopped
    when the page never asks. Nothing is pressed."""
    got = []

    def seen(resp):
        try:
            if not got and _is_history_answer(resp.url) and resp.request.method == "GET":
                got.append(resp)
        except Exception:
            pass

    page.on("response", seen)
    try:
        try:
            page.goto(HISTORY_URL, wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            log.info("opening Bill & payment history failed (%s)", type(e).__name__)
        waited = 0
        while not got and waited < timeout_ms:
            page.wait_for_timeout(250)
            waited += 250
    finally:
        try:
            page.remove_listener("response", seen)
        except Exception:
            pass
    if looks_signed_out(page):
        raise SessionExpired("Verizon showed its sign-in page")
    if not got:
        raise ListStopped("Bill & payment history did not ask for its bills")
    resp = got[0]
    if resp.status in (401, 403):
        raise SessionExpired("Verizon refused the bill history")
    if resp.status != 200:
        raise ListStopped(f"the bill history was answered with {resp.status}")
    try:
        answer = intake.json_of(resp, MAX_LIST_BYTES)
        channel = resp.request.all_headers().get("channelid") or ""
    except intake.TooLarge:
        raise ListStopped("the bill history answer is larger than any history")
    except Exception as e:
        raise ListStopped(f"the bill history answer could not be read ({type(e).__name__})")
    if not _CHANNEL_RE.fullmatch(channel):
        raise ListStopped("the page's own bill history request carried no channel")
    _keep_private(answer)
    return _History(answer=answer, channel=channel)


def _keep_private(answer) -> None:
    """Register the account number, name and address in the answer as
    private words, part by part."""
    addr = (((answer or {}).get("body") or {}).get("billingHistory") or {}).get("address") or {}
    found = [str(v) for k, v in addr.items() if isinstance(v, str) and k != "state"]
    # Four characters or more: a house number like "100" would turn every
    # "0100" in a diagnostic into "[name]".
    parts = {part for w in found for part in re.split(r"[\s,.#/-]+", w) if len(part) >= 4}
    if parts - set(_private_words()):
        set_private_words(_private_words() + sorted(parts - set(_private_words())))


def end_day(text) -> Optional[str]:
    """A cycle's billEndDate, "10/21/2026", as YYYY-MM-DD, or None."""
    m = _END_DATE_RE.fullmatch(str(text or "").strip())
    if not m:
        return None
    try:
        return _date(int(m.group(3)), int(m.group(1)), int(m.group(2))).isoformat()
    except ValueError:
        return None


def bills_of(answer) -> List[RawDoc]:
    """RawDocs from the bill history answer, one per billing cycle, dated by
    its bill end date. An answer that is not a bill history, a cycle whose
    end date is not a calendar date, or two cycles of one end date stops
    the list, carrying what was read before it."""
    if not isinstance(answer, dict):
        raise ListStopped("the bill history answer is not an object")
    if (answer.get("responseInfo") or {}).get("responseCode") not in ("00", "0", None):
        raise ListStopped("Verizon answered the bill history with an error code")
    cycles = (((answer.get("body") or {}).get("billingHistory") or {}).get("billCycle"))
    if not isinstance(cycles, list):
        raise ListStopped("the bill history answer holds no billing cycles")
    docs: List[RawDoc] = []
    dates = set()
    for c in cycles:
        end = (c or {}).get("billEndDate") if isinstance(c, dict) else None
        iso = end_day(end)
        if not iso:
            raise ListStopped("a bill's end date is not a calendar date", docs)
        if iso in dates:
            raise ListStopped("two bills carry one end date", docs)
        dates.add(iso)
        title = f"Verizon Mobile Bill {iso}"
        docs.append(RawDoc(title=title, date_text=iso, href=PDF_PATH, text=title,
                           row_index=len(docs), kind="statement",
                           document_id=f"bill-{iso}", end_date=str(end)))
    return docs


def pdf_url(end_date: str, channel: str) -> str:
    """The address a cycle's PDF is asked from, the one the page's own
    Review bill PDF opens, or "" when either part is not one."""
    if not _END_DATE_RE.fullmatch(end_date or "") or not _CHANNEL_RE.fullmatch(channel or ""):
        return ""
    url = f"{BASE}{PDF_PATH}?" + urlencode({"startMonthDate": end_date, "channelId": channel})
    return url if is_pdf_url(url) else ""


def is_pdf_url(url: str) -> bool:
    """True only for the bill PDF address on www.verizon.com with exactly
    its two parameters, each of the right shape."""
    if not is_safe_url(url):
        return False
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    q = parse_qs(parts.query)
    return (parts.netloc == "www.verizon.com" and parts.path == PDF_PATH and not parts.fragment
            and set(q) == {"startMonthDate", "channelId"}
            and bool(_END_DATE_RE.fullmatch(q["startMonthDate"][0]))
            and bool(_CHANNEL_RE.fullmatch(q["channelId"][0])))


def goto_documents(page) -> bool:
    """Open Bill & payment history and take its bill list. False when it
    showed the sign-in page or never asked."""
    try:
        _open(page)
        return True
    except (SessionExpired, ListStopped) as e:
        log.info("Bill & payment history did not open: %s", e)
        return False


def scroll_full_page(page, rounds: int = 8, delay_ms: int = 600) -> None:
    try:
        for _ in range(rounds):
            page.mouse.wheel(0, 3000)
            page.wait_for_timeout(delay_ms)
    except Exception:
        pass


def expand_all(page) -> None:
    """Nothing to press: the API's answer holds every cycle, even those the
    page shows only after Show more."""
    return None


def collect_download_docs(page) -> List[RawDoc]:
    """Every bill in the bill history. Nothing is pressed. A list that
    cannot be read whole, or a signed-out session, gives no list at all,
    said in the log, since this app's engine records whatever it is given
    and a part of the history must never pass for all of it."""
    try:
        return bills_of(_open(page).answer)
    except (SessionExpired, ListStopped) as e:
        log.warning("the bill history could not be read whole: %s", e)
        return []


_PDF_JS = r"""async ([url, limit]) => {
  let r;
  try { r = await fetch(url, {credentials: 'include', redirect: 'manual'}); }
  catch (e) { return {status: 0, failed: true}; }
  if (r.type === 'opaqueredirect' || r.redirected) return {status: r.status, redirected: true};
  const type = r.headers.get('content-type') || '';
  if (r.status !== 200) return {status: r.status, type: type};
  const buf = await ppRead(r);
  if (buf.length > limit) return {status: r.status, type: type, too_big: true};
  let s = '';
  for (let i = 0; i < buf.length; i += 0x8000) {
    s += String.fromCharCode.apply(null, buf.subarray(i, i + 0x8000));
  }
  return {status: r.status, type: type, b64: btoa(s)};
}"""


def _fetch(page, url: str, out_path: Path, trace: Optional[list]) -> bool:
    """GET a bill's PDF address from inside the signed-in page, the way its
    Review bill PDF opens it, and keep the body only when it is a PDF."""
    if not is_pdf_url(url):
        return False
    try:
        got = intake.evaluate(page, _PDF_JS, [url, MAX_PDF_BYTES], limit=MAX_PDF_BYTES) or {}
    except intake.TooLarge:
        return False
    except Exception as e:
        log.info("fetching the bill failed (%s)", type(e).__name__)
        if trace is not None:
            trace.append({"note": "fetch failed", "error": type(e).__name__})
        return False
    ctype = str(got.get("type") or "").split(";", 1)[0].strip().lower()
    if trace is not None:
        trace.append({"note": "fetched", "host": "www.verizon.com", "status": got.get("status"), "type": ctype[:30]})
    if got.get("redirected") or got.get("status") in (401, 403):
        raise SessionExpired("Verizon refused the bill")
    if got.get("status") != 200 or not got.get("b64"):
        return False
    try:
        data = intake.decode(got["b64"], validate=True, limit=MAX_PDF_BYTES)
    except Exception:
        return False
    if data[:5] != b"%PDF-":
        if data.lstrip()[:1] in (b"<", b"{", b"["):
            raise SessionExpired("Verizon answered a bill with a sign-in page")
        return False
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(data)
    return True


def download_bill(page, dl_dir, iso_date: str, out_path, title: str = "",
                  trace: Optional[list] = None) -> bool:
    """Save the bill whose cycle ended on `iso_date`. The bill history is
    taken again from the page, and the bill is fetched only when exactly one
    cycle there ends that day. `dl_dir` is unused: nothing goes through the
    browser's downloads. Nothing is pressed. SessionExpired propagates."""
    out_path = Path(out_path)
    try:
        history = _open(page)
        found = [d for d in bills_of(history.answer) if d.date_text == (iso_date or "")]
    except (SessionExpired, ListStopped) as stop:
        log.info("the bill list stopped while looking for the bill dated %s: %s", iso_date, stop)
        return False
    if len(found) != 1:
        log.info("%d bills match the date %s, none taken", len(found), iso_date)
        if trace is not None:
            trace.append({"note": "no single bill matches the record", "matches": len(found)})
        return False
    try:
        return _fetch(page, pdf_url(found[0].end_date, history.channel), out_path, trace)
    except SessionExpired as e:
        log.info("the bill dated %s was refused: %s", iso_date, e)
        return False


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
    r"^\s*((see|view|show)\s+)?(bill(ing)?\s+)?(history|bills|statements|past\s+bills|"
    r"previous\s+bills|documents|billing)\s*$", re.I)


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


def survey(page, dwell_ms: int = 4000, max_follow: int = 0) -> dict:
    """What the signed-in billing area looks like, without downloading
    anything. Records the page, its headings and controls with the guard's
    verdict on each, and every JSON or PDF response verizon.com sends while
    the page settles. Follows nothing, since this app presses no control at
    all and a survey is not a reason to start. No screenshot."""
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
                    parsed = whole_json(_json.loads(body))
                    if isinstance(parsed, dict):
                        entry["post_keys"] = sorted(str(k) for k in parsed)[:30]
            except Exception:
                pass
            q = _safe_query(url)
            if q:
                entry["query"] = q[:240]
            if "json" in ct:
                try:
                    entry["shape"] = _shape(whole_json(res.json()))
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


# ---------------------------------------------------------------------------
# Host allowlist. Parsed, never a string prefix, so a lookalike host cannot
# walk through.
# ---------------------------------------------------------------------------
ALLOWED_HOSTS = {"verizon.com"}


def is_safe_url(url: str) -> bool:
    """True only for an https URL on one of this provider's own hosts.

    The check itself lives in the core, so all of them answer the same way.
    This app keeps the hosts, which is the part that really is its own."""
    return _host_allows(url, ALLOWED_HOSTS)
