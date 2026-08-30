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

  There are NO guessed document URLs here. DOCUMENT_PATHS below is EMPTY, and
  download refuses everything while it is empty, so this app cannot fetch an
  arbitrary URL before its real endpoints are written in from evidence
  gathered by --diagnose.

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
# Empty on purpose: routes are written from diagnose evidence, not invented.
DOCUMENT_URL_CANDIDATES: list = []

# The real document endpoints, filled in from evidence once diagnose has run.
# While this is empty, download_document refuses every URL. That is the point:
# an unmapped app should fetch nothing rather than guess.
DOCUMENT_PATHS: dict = {}

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

# Generic fallback selectors, repaired from diagnose evidence.
FALLBACK = {
    "doc_row": ("table tbody tr, [role='row'], [class*='statement'], "
                "[class*='document'], li[class*='doc']"),
    "doc_link": "a[href*='.pdf'], a[download], button[class*='download']",
    "page_ready": "main, [role='main'], table, [class*='statement']",
}

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


def _abs(href: str) -> str:
    href = (href or "").strip()
    if not href:
        return ""
    if href.startswith("http"):
        return href
    if href.startswith("//"):
        return "https:" + href
    return BASE + ("" if href.startswith("/") else "/") + href


def _endpoint_of(url: str) -> Optional[str]:
    """The document kind this URL is, or None.

    Matched on the URL PATH against DOCUMENT_PATHS, never as a substring of the
    whole URL: a substring test would accept an on-host settings route that
    merely carried the endpoint name in a query string. While DOCUMENT_PATHS is
    empty (this app is not mapped yet) every URL returns None and is refused.
    """
    if not DOCUMENT_PATHS or not is_safe_url(url):
        return None
    from urllib.parse import urlparse
    try:
        path = (urlparse(url).path or "").lower().rstrip("/")
    except ValueError:
        return None
    return DOCUMENT_PATHS.get(path)


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


def _doc_id(href: str) -> str:
    """A stable identity from the href, so two documents that share a title and
    date do not collapse into one record."""
    m = re.search(r"[?&](?:id|docid|documentid|key|documentkey)=([^&]+)", href, re.I)
    return m.group(1)[:60] if m else (href or "")[-60:]


# ---------------------------------------------------------------------------
# Evidence gathering. Until the real endpoints are known, this reports what is
# on the page rather than pretending to know how to collect documents.
# ---------------------------------------------------------------------------
_LINK_EVIDENCE_JS = r"""() => [...document.querySelectorAll('a,button')]
    .map(e => ({
      label: (e.innerText || e.getAttribute('aria-label') || '').replace(/\s+/g,' ').trim().slice(0, 60),
      href: e.getAttribute('href') || '',
      onclick: (e.getAttribute('onclick') || '').slice(0, 60),
      testid: e.getAttribute('data-testid') || e.getAttribute('id') || ''
    }))
    .filter(x => /statement|document|eras|crsc|1099|1042|tax|download|pdf|archive/i.test(
       x.label + ' ' + x.href + ' ' + x.testid))
    .slice(0, 60)"""


def collect_link_evidence(page) -> List[dict]:
    """Read document-looking controls from myPay frames only. Read-only."""
    out: List[dict] = []
    seen = set()
    try:
        pages = [p for p in page.context.pages if not p.is_closed()]
    except Exception:
        pages = [page]
    for pg in pages:
        try:
            frames = [fr for fr in pg.frames if is_mypay_frame(fr)]
        except Exception:
            continue
        for fr in frames:
            try:
                for e in (fr.evaluate(_LINK_EVIDENCE_JS) or []):
                    key = (e.get("label", ""), e.get("href", ""), e.get("testid", ""))
                    if key in seen:
                        continue
                    seen.add(key)
                    e["frame_url"] = (fr.url or "")[:120]
                    out.append(e)
            except Exception:
                continue
    return out


def collect_documents(page) -> List[dict]:
    """Collect real documents.

    Not implemented yet, and deliberately not faked. DOCUMENT_PATHS is empty,
    so there is nothing to collect from. Run --diagnose, which records what is
    actually on the page, and this is written from that evidence.
    """
    if not DOCUMENT_PATHS:
        log.warning("myPay's document endpoints are not mapped yet. Run "
                    "diagnose.bat with your documents page open; it records "
                    "what is there and downloads nothing.")
        return []
    return []


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


def download_document(page, href: str, out_path) -> bool:
    """Save one document's PDF by a host-and-path-checked GET of its own href.

    Refuses everything while DOCUMENT_PATHS is empty, so an unmapped app cannot
    be pointed at an arbitrary URL. Raises SessionExpired when myPay hands back
    a sign-in page instead of a document.
    """
    url = _abs(href)
    if _endpoint_of(url) is None:
        log.error("refusing a URL that is not a known myPay document endpoint")
        return False
    try:
        resp = page.context.request.get(url, max_redirects=3)
    except Exception as e:
        if "redirect" in str(e).lower():
            raise SessionExpired(
                "myPay redirected the document request, which means the "
                "signed-in session is no longer valid") from None
        log.warning("fetch failed: %s", str(e).splitlines()[0][:100])
        return False
    final = getattr(resp, "url", url) or url
    if not is_safe_url(final):
        log.error("refusing a redirect that left myPay's host")
        return False
    if not resp.ok:
        log.warning("fetch returned %s", resp.status)
        return False
    body = resp.body()
    if not body.startswith(b"%PDF"):
        if _looks_like_login_html(body):
            raise SessionExpired(
                "myPay returned a sign-in page instead of a document")
        log.warning("response was not a PDF (%d bytes)", len(body))
        return False
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(body)
    return True
