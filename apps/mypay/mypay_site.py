"""ALL DFAS myPay selectors, URLs, and page behavior live here.

When myPay changes, repair this file only.

STATUS, read before trusting anything below.

  CONFIRMED from the public site, 2026-08-23:
    * one host, mypay.dfas.mil, an Angular SPA using #/ fragment routes
    * sign-in is a Login ID + password form (CAC is offered separately)
    * the sign-in page also carries an SSN field (name="socialField") used for
      account recovery, and an "AgreeToTerms" checkbox

  NOT YET CONFIRMED, and deliberately not guessed:
    * where the eRAS, CRSC and tax documents live once signed in
    * how a statement PDF is delivered

  There are NO guessed URLs here. A document is fetched by its (type, id)
  pair, both validated as integers against the type map below, so the request
  path is built from numbers this app recognises rather than from any stored
  string.

SAFETY (this is a US government pay system):
  Strictly READ-ONLY. myPay can change where retirement pay is deposited, tax
  withholding, allotments, SBP elections and correspondence details. This app
  must NEVER activate a control that does any of those, never submits a form,
  never confirms a dialog, and never accepts terms on the user's behalf. It
  also must never read from or type into the SSN field.

  Two further rules specific to a DoD system:
    * the user signs in themselves and accepts the DoD consent banner
      themselves. This app does not click through a government consent banner.
    * sessions are short by design. An expired session raises SessionExpired
      so a run stops loudly rather than reporting an empty success.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import List, Optional, Tuple

log = logging.getLogger("mypay_docs.site")

BASE = "https://mypay.dfas.mil"
# One host. Everything this app touches is on it, checked parsed, never by
# prefix, so a lookalike like mypay.dfas.mil.example cannot walk through.
ALLOWED_HOSTS = {"mypay.dfas.mil"}

URLS = {
    "home": f"{BASE}/",
    "login": f"{BASE}/",
}


# Markers of a genuine sign-in / challenge redirect. The signed-in app lives at
# the bare host with #/ routes, so none of these collide with a normal page.
LOGIN_URL_MARKERS = ["/signin", "/logon", "/sso", "samlsso", "returnurl=",
                     "sessiontimeout", "/logout", "/loggedout"]

# ---------------------------------------------------------------------------
# HARD SAFETY GUARD - never click anything matching this.
# Tuned for a military pay account. Verb families include their endings: a
# review of the sibling bank app found "Save Changes", "Document Removal" and
# "Loss Mitigation Application" walking through a guard that matched only the
# bare stems, so the same mistake is not repeated here.
# ---------------------------------------------------------------------------
FORBIDDEN_CONTROL_RE = re.compile(
    # where the money goes
    r"(direct\s*deposit|net\s*pay|electronic\s+funds|\beft\b|routing|"
    r"bank\s*(account|info)|account\s*number|financial\s+institution|"
    r"allotment|discretionary|transfer|deposit|withdraw|wire\b|payment|"
    # tax and entitlements
    r"withholding|\bw-?4\b|\bw-?2\b|fitw|sitw|state\s+tax|federal\s+tax|"
    r"exemption|dependent|survivor|\bsbp\b|\bsgli\b|\bfegli\b|beneficiar|"
    r"annuit|\btsp\b|thrift\s+savings|combat\s+related\s+election|"
    r"waiver|\bvsi\b|\bssb\b|garnish|debt|overpayment|"
    # identity and account settings
    r"social\s*security|\bssn\b|social\s*field|date\s+of\s+birth|"
    r"address|phone|e-?mail|password|login\s*id|\bpin\b|security\s+question|"
    r"correspondence|mailing|contact\s+info|"
    # verb families, endings included
    r"chang(e|es|ed|ing)|edit(s|ed|ing)?\b|updat(e|es|ed|ing)|"
    r"set\s+up|enabl|disabl|delet|remov(e|es|ed|ing|al)|start|stop|restart|"
    r"\boptions?\b|\bsettings?\b|\bpreferences?\b|\bsave\b|manage|"
    r"enroll|consent|agree|accept|opt\s*(in|out)|turn\s+(on|off)|"
    r"elect(ion)?\b|authoriz|certif|"
    # generic commit verbs
    r"submit|confirm|continue|\bnext\b|sign\b|appl(y|ies|ied|ication)|"
    r"request|cancel|renew|activat)", re.I)

# A control must ALSO look like a document action before it may be clicked.
SAFE_DOC_CONTROL_RE = re.compile(
    r"(download|view|open|print|pdf|statement|document|1099|1042|"
    r"\beras\b|crsc|retiree\s+account|tax\s+statement|archive)", re.I)

SECURITY_CHALLENGE_MARKERS = [
    "enter the code we sent", "verification code", "one-time", "one time pin",
    "security code", "we sent a code", "two-factor", "two-step",
    "authenticator", "confirm your identity", "verify your identity",
    "unusual activity", "are you a robot", "captcha",
    "your session has expired", "session timeout", "please log in again",
]

RATE_LIMIT_MARKERS = [
    "too many requests", "rate limit", "try again later",
    "temporarily unavailable", "http error 429", "unusual traffic",
]


# ---------------------------------------------------------------------------
# Date parsing
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
    """Date to file a document under, plus a human period label. A monthly
    statement titled by period files on the last day of that period."""
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
        # The sign-in page carries a Login ID, a password and an SSN recovery
        # field. The SSN field is only ever DETECTED here, never read from and
        # never typed into.
        if page.locator("input[name='socialField' i], input[name='socialfield' i]").count() > 0:
            return True
        return page.locator("input[type='password']").count() > 0
    except Exception:
        return False


def detect_security_challenge(page) -> Optional[str]:
    try:
        title = (page.title() or "").lower()
    except Exception:
        title = ""
    try:
        body = page.locator("body").inner_text(timeout=5000).lower()
    except Exception:
        body = ""
    hay = title + "\n" + body[:2000]
    for m in SECURITY_CHALLENGE_MARKERS:
        if m in hay:
            return f"Security challenge detected: '{m}'"
    for m in RATE_LIMIT_MARKERS:
        if m in hay:
            return f"Possible rate limiting detected: '{m}'"
    return None


def is_safe_control(name: str) -> bool:
    """A control may be clicked only if it looks like a document action AND
    matches nothing in the forbidden list. Empty or unknown means no."""
    name = (name or "").strip()
    if not name:
        return False
    if FORBIDDEN_CONTROL_RE.search(name):
        return False
    return bool(SAFE_DOC_CONTROL_RE.search(name))


def is_safe_url(url: str) -> bool:
    """On myPay's host, by parsed comparison, never a string prefix."""
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


def is_mypay_frame(frame) -> bool:
    """True only for a frame actually loaded from myPay.

    The collector walks every frame of every tab in the attached browser, which
    is the user's ordinary Chrome. Without this it would read from, and could
    click inside, unrelated sites.
    """
    try:
        url = frame.url or ""
    except Exception:
        return False
    if not url.startswith("https://"):
        return False
    from urllib.parse import urlparse
    try:
        return (urlparse(url).hostname or "").lower() in ALLOWED_HOSTS
    except ValueError:
        return False






def goto_documents(page) -> bool:
    """Deliberately does NOT navigate.

    myPay is a single-page app behind a short session, and the document area is
    reached by the user. Navigating would risk dropping their place or their
    session. This only confirms they are still signed in.
    """
    return not looks_signed_out(page)


def ensure_statements(page) -> bool:
    """Only confirms the session is still live, and never navigates."""
    return not looks_signed_out(page)




# ---------------------------------------------------------------------------
# The document API. CONFIRMED against a live account, 2026-08-23.
#
#   GET /api/document/history/{DocumentTypeId}  -> the list for that type
#   GET /api/document/pdf/{DocumentTypeId}/{Id} -> that document as a PDF
#
# Both are plain GETs. Nothing on the page is clicked, no form is submitted and
# nothing is navigated, which on a system that can redirect retirement pay is
# the strongest guarantee available.
#
# HOW THE REQUEST IS AUTHENTICATED, and why it is done this way.
# The Angular app sends a bearer token plus three identifying headers. Rather
# than lift that token out of the browser and carry it around in this process,
# every call below runs INSIDE the page and reads the token in the same
# expression that uses it. The token is a government session credential: it
# never enters this program, is never logged, and never touches disk.
# ---------------------------------------------------------------------------

# DocumentTypeId -> (title, whether to collect by default). Taken from the
# app's own DocumentTypeEnum, so these are its numbers, not invented ones.
DOCUMENT_TYPES = {
    # Retiree and annuitant accounts (verified live against a retiree account)
    21: "Retiree Account Statement",
    19: "Annual Retiree Account Statement",
    20: "CRSC Pay Statement",
    18: "1099-R Tax Form",
    22: "1042-S Tax Form",
    23: "Annuitant Account Statement",
    27: "Travel 1099-INT Statement",
    9: "Travel Misc W-2 Statement",
    5: "IRS Form 1095-B",
    6: "IRS Form 1095-C",
    # Active-duty accounts. NOT YET VERIFIED against a live active-duty
    # account: the numbers are myPay's own DocumentTypeEnum values and the API
    # is the same one the retiree types are proven on, but nobody has run this
    # against an active-duty member's account. A type that does not apply to an
    # account simply returns nothing and is skipped, so listing these here is
    # harmless for a retiree and is what makes one app serve both.
    2: "Leave and Earnings Statement",
    3: "W-2 Tax Form",
    4: "W-2C Corrected Tax Form",
}

# The shared header block. Built inside the page from the values the app itself
# uses, so a request is indistinguishable from the one the page would make.
_HEADERS_JS = """
  const H = {
    'Authorization': 'Bearer ' + (sessionStorage.getItem('id_token') || ''),
    'Content-Type': 'application/json',
    'myPayVersion': sessionStorage.getItem('myPayVersion') || '',
    'browserSessionId': sessionStorage.getItem('browserSessionId') || '',
    'deviceId': localStorage.getItem('deviceId') || ''
  };
"""

_HISTORY_JS = """async (t) => {
""" + _HEADERS_JS + """
  H['Accept'] = 'application/json';
  const r = await fetch('/api/document/history/' + t, {headers: H, credentials: 'include'});
  const ct = r.headers.get('content-type') || '';
  if (!/json/i.test(ct)) return {status: r.status, html: true};
  return {status: r.status, body: await r.json()};
}"""

_PDF_JS = """async (a) => {
""" + _HEADERS_JS + """
  H['Accept'] = 'application/pdf';
  const r = await fetch('/api/document/pdf/' + a.t + '/' + a.id, {headers: H, credentials: 'include'});
  const ct = r.headers.get('content-type') || '';
  const buf = new Uint8Array(await r.arrayBuffer());
  let s = '';
  for (let i = 0; i < buf.length; i++) s += String.fromCharCode(buf[i]);
  return {status: r.status, ct: ct, b64: btoa(s)};
}"""


def _iso_from_discriminator(value: str) -> str:
    """2025-05-20T00:00:00 -> 2025-05-20, read as a calendar date.

    Taken as written rather than parsed through a timezone, so a statement
    never shifts a day and file itself under the wrong month.
    """
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(value or ""))
    return m.group(0) if m else ""


def _documents_from(payload) -> List[dict]:
    """Pull the document list out of the API envelope, whatever it wraps it in."""
    import json as _json
    body = payload if isinstance(payload, dict) else {}
    if body.get("Succeeded") is False:
        return []
    jr = body.get("JsonResult")
    if isinstance(jr, str):
        try:
            jr = _json.loads(jr)
        except Exception:
            return []
    if isinstance(jr, list):
        return [d for d in jr if isinstance(d, dict)]
    if isinstance(jr, dict):
        for v in jr.values():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                return v
    return []


def collect_documents(page) -> List[dict]:
    """Every document myPay holds, across every type, newest first.

    Returns dicts {title, date, account, href, doc_id}. The identity is
    "typeId|documentId", not a URL, so a changed query string cannot cause the
    wrong file to be fetched.
    """
    rows: List[dict] = []
    seen = set()
    if not is_mypay_frame_page(page):
        log.warning("The open tab is not myPay. Sign in at mypay.dfas.mil and "
                    "leave that tab open.")
        return rows

    for type_id, title in DOCUMENT_TYPES.items():
        try:
            res = page.evaluate(_HISTORY_JS, type_id) or {}
        except Exception as e:
            log.info("history for type %s failed: %s", type_id,
                     str(e).splitlines()[0][:80])
            continue
        if res.get("html"):
            raise SessionExpired(
                "myPay answered a document listing with a page instead of "
                "data, which means the signed-in session is no longer valid")
        docs = _documents_from(res.get("body"))
        if not docs:
            continue
        kept = 0
        per_date = {}
        for d in docs:
            if not d.get("DataFound", True) or d.get("Id") is None:
                continue
            date = _iso_from_discriminator(d.get("DateDiscriminator"))
            if not date:
                continue
            # Identity is type + date, NOT myPay's numeric Id: that Id is a
            # transient handle for generated documents and goes stale between
            # sessions, which once caused every statement to be recorded twice.
            n = per_date.get(date, 0)
            per_date[date] = n + 1
            key = "%d|%s" % (type_id, date) if n == 0 else "%d|%s|%d" % (type_id, date, n)
            if key in seen:
                continue
            seen.add(key)
            suffix = re.sub(r"\s+", " ", str(d.get("DocumentNameSuffix") or "")).strip()
            rows.append({
                "title": ("%s %s" % (title, suffix)).strip() if suffix else title,
                "date": date,
                "account": "",
                "href": "",          # deliberately empty: never a URL
                "doc_id": key,
            })
            kept += 1
        if kept:
            log.info("%-34s %d document(s)", title, kept)

    rows.sort(key=lambda r: r["date"] or "", reverse=True)
    log.info("myPay: %d document(s) collected", len(rows))
    return rows


def is_mypay_frame_page(page) -> bool:
    """The page itself is on myPay (the frame check, applied to a page)."""
    try:
        return is_safe_url(page.url or "")
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

class SessionExpired(Exception):
    """The server answered a document request with a sign-in page."""


def _looks_like_login_html(body: bytes) -> bool:
    """A sign-in page returned where a PDF was expected.

    A short government session expires often, and an expired session answers
    with HTML and an HTTP 200 rather than an error. Without this the caller
    files every remaining document as "manual review" and the run ends looking
    successful while having saved nothing.
    """
    head = body[:4000].lower()
    if b"<html" not in head and b"<!doctype" not in head:
        return False
    return any(m in head for m in (
        b"type=\"password\"", b"type='password'", b"sign in", b"log in",
        b"login id", b"session has expired", b"session timeout"))


def parse_doc_id(doc_id: str):
    """"21|2025-05-20" -> (21, "2025-05-20", 0), or None if malformed.

    The identity is the document TYPE and its statement DATE, never myPay's
    numeric Id. A live run proved why: for the on-demand documents (eRAS,
    1099-R) that Id is a transient generation handle. It goes stale between
    sessions, so a stored one returns 404 and the same statement gets recorded
    again under a new Id. Type plus date is what actually identifies a monthly
    statement, and the numeric Id is looked up fresh at download time.

    An optional third part disambiguates two documents of one type sharing a
    date, so neither is silently dropped.
    """
    m = re.fullmatch(r"(\d{1,6})\|(\d{4}-\d{2}-\d{2})(?:\|(\d{1,3}))?",
                     str(doc_id or "").strip())
    if not m:
        return None
    type_id = int(m.group(1))
    if type_id not in DOCUMENT_TYPES:
        return None
    return type_id, m.group(2), int(m.group(3) or 0)


def _history_docs(page, type_id: int) -> List[dict]:
    """The current session's list for one document type. Raises SessionExpired
    if myPay answers with a page instead of data."""
    res = page.evaluate(_HISTORY_JS, type_id) or {}
    if res.get("html"):
        raise SessionExpired(
            "myPay answered a document listing with a page instead of data, "
            "which means the signed-in session is no longer valid")
    return _documents_from(res.get("body"))


def resolve_document_id(page, type_id: int, date: str, ordinal: int = 0):
    """The CURRENT numeric Id for a (type, date) document, or None.

    Looked up fresh every time rather than trusted from storage, because the
    Id myPay hands out for a generated document does not survive the session.
    """
    matches = [d for d in _history_docs(page, type_id)
               if _iso_from_discriminator(d.get("DateDiscriminator")) == date
               and d.get("Id") is not None]
    if ordinal >= len(matches):
        return None
    try:
        return int(matches[ordinal]["Id"])
    except (TypeError, ValueError):
        return None


def download_document(page, doc_id: str, out_path) -> bool:
    """Save one document by its (type, id) identity, never by a URL.

    The identity is validated to two integers and the type must be one this app
    knows, so the request cannot be pointed anywhere else. Raises SessionExpired
    when myPay answers with a page instead of a document.
    """
    import base64
    parsed = parse_doc_id(doc_id)
    if not parsed:
        log.error("refusing a document identity that is not a known type and date")
        return False
    type_id, date, ordinal = parsed
    if not is_mypay_frame_page(page):
        raise SessionExpired("the myPay tab is no longer open on myPay")
    # Look the numeric Id up fresh. A stored one goes stale between sessions.
    ident = resolve_document_id(page, type_id, date, ordinal)
    if ident is None:
        log.warning("myPay no longer lists a %s dated %s",
                    DOCUMENT_TYPES.get(type_id, type_id), date)
        return False
    try:
        res = page.evaluate(_PDF_JS, {"t": type_id, "id": ident}) or {}
    except Exception as e:
        log.warning("fetch failed: %s", str(e).splitlines()[0][:100])
        return False
    status = res.get("status")
    if status in (401, 403):
        raise SessionExpired("myPay refused the document request (%s), which "
                             "means the session has expired" % status)
    if status != 200:
        log.warning("fetch returned %s", status)
        return False
    try:
        body = base64.b64decode(res.get("b64") or "")
    except Exception:
        log.warning("could not decode the response")
        return False
    if not body.startswith(b"%PDF"):
        if _looks_like_login_html(body):
            raise SessionExpired(
                "myPay returned a sign-in page instead of a document")
        log.warning("response was not a PDF (%d bytes, %s)",
                    len(body), str(res.get("ct"))[:30])
        return False
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(body)
    return True
