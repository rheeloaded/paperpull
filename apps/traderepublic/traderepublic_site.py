"""Trade Republic (app.traderepublic.com) addresses, the statement route and
how each answer is read. When the web app changes, repair this file only.

STATUS, UNTESTED. Nobody who built this has a Trade Republic account, so no
page and no PDF of theirs has been seen here. Every fact below was first
seen in the Habeas sources definition for Trade Republic
(github.com/habeas-dev/sources, sources/traderepublic.json, CC0, marked
first-party and verified, version 2026-09-02). No code from it or from
anywhere else was read or copied.

  READY   the web app is ready when https://app.traderepublic.com/boards is
          reached. Requests made before that fail.
  ROUTE   GET https://api.traderepublic.com/api/v1/banking/consumer/
          accountstatement/statement with fromDate and toDate set to one
          month. The answer is the statement as a native PDF. About 1100
          days are kept.
  AUTH    the page's cookie session. The person signs in with their phone
          number, PIN and a code from the app or a text message, always
          themselves.
  NOT HERE  trade confirmations and other per-trade documents are reached
          through the web app's WebSocket, which this app never opens.

There is no list. The months are worked out from today's date, and each
month is one document keyed by its period. A session is proven only by one
of those statements answering as a PDF, never by the absence of a sign-in
page.

What the first tester's run settles is kept in named constants,
DATE_PARAM_FORM (how the two dates are written in the request) and
PERIOD_DAY_FORM (how the statement prints its first and last day), so a
correction is one line.

SAFETY. Strictly read-only. Nothing is clicked, typed or loaded. Each month
is one GET from inside the signed-in tab, to the API host only, with
redirects refused. Trade Republic is a broker. Never a trade, a transfer, a
setting or a WebSocket.
"""
from __future__ import annotations

import calendar
import logging
import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import List, Optional, Sequence, Tuple
from urllib.parse import urlencode, urlsplit

from paperpull_core import intake, pdf_reader
from paperpull_core.characters import whole_characters
from paperpull_core.controls import AUTH_CONTROL_RE, SETTINGS_CONTROL_RE
from paperpull_core.identity import MIN_TEXT, Identity, on_its_own
from paperpull_core.redact import redact, set_private_words  # noqa: F401
from paperpull_core.urls import is_safe_url as _host_allows
from paperpull_core.words import Fixed

log = logging.getLogger("traderepublic_site")

APP_HOST = "app.traderepublic.com"
API_HOST = "api.traderepublic.com"
ALLOWED_HOSTS = {APP_HOST, API_HOST}
HOME_URL = f"https://{APP_HOST}/"
READY_PATH = "/boards"
READY_URL = f"https://{APP_HOST}{READY_PATH}"
STATEMENT_URL = (f"https://{API_HOST}/api/v1/banking/consumer/"
                 "accountstatement/statement")
URLS = {"home": HOME_URL, "login": HOME_URL, "documents": READY_URL}
# UNCONFIRMED. Where the web app is taken to ask for a sign-in. Only a
# statement answering proves a session, so this only ever stops a run.
LOGIN_URL_MARKERS = ("/login",)

# How far back the statement route reaches, in days.
LOOKBACK_DAYS = 1100
# How many of the newest months Login and Discover ask before they say a
# session could not be confirmed. A month with no statement (an account
# opened last month, a statement not made yet) does not hide a session.
PROBE_MONTHS = 3

# UNCONFIRMED until a tester's first run. fromDate is the month's first day
# and toDate its last day, both written like this.
DATE_PARAM_FORM = "%Y-%m-%d"
# UNCONFIRMED until a tester's first run. How the statement is expected to
# print the first and the last day of its month, the German way, 01.03.2026
# and 31.03.2026. A PDF that does not show both, each as a date of its own,
# is refused rather than guessed at, and Diagnose counts the date shapes
# the PDF does hold so the first run says which form is right.
PERIOD_DAY_FORM = "%d.%m.%Y"

FORBIDDEN_CONTROL_RE = re.compile(
    r"\b(?:buy|sell|kaufen|verkaufen|order|trade|transfer|send|withdraw|"
    r"deposit|pay|payment|sparplan|savings plan|delete|edit|change|confirm|"
    r"update|cancel|create|submit)\b", re.I)
SAFE_DOC_CONTROL_RE = re.compile(r"\b(?:statement|kontoauszug|download|pdf)\b", re.I)
RATE_LIMIT_MARKERS = re.compile(r"too many requests|rate limit", re.I)
# The app reads no page elements. Named for the journal and the failure file.
FALLBACK = {"password_field": "input[type='password']"}

# What one month's answer was.
PDF = "pdf"
SIGNED_OUT = "signed out"
LIMITED = "limited"
NO_STATEMENT = "no statement"
TOO_LARGE = "too large"


class SessionExpired(RuntimeError):
    """Trade Republic answered a statement with 401 or 403."""


class ListStopped(RuntimeError):
    """The run cannot go on asking for months, Trade Republic is limiting
    requests or the tab is gone."""


@dataclass(frozen=True)
class Month:
    period: str   # YYYY-MM
    first: date
    last: date

    @property
    def date(self) -> str:
        """A statement is dated by the last day of its month."""
        return self.last.isoformat()


@dataclass(frozen=True)
class Answer:
    kind: str
    status: int = 0
    data: bytes = b""


@dataclass(frozen=True)
class Check:
    """How a statement PDF compared with its month. Names and counts only."""
    outcome: str            # verified, refused, unchecked or unreadable
    days_found: int = 0     # of this month's two days
    rival_days_found: int = 0
    text_chars: int = 0

    @property
    def ok(self) -> bool:
        return self.outcome == "verified"

    def report(self) -> dict:
        return {"outcome": self.outcome, "days_found": self.days_found,
                "days_expected": 2, "other_month_days_found": self.rival_days_found,
                "text_chars": min(int(self.text_chars), 1_000_000)}


# -- addresses -------------------------------------------------------------

def is_safe_url(url: str) -> bool:
    return _host_allows(url, ALLOWED_HOSTS, subdomains=False)


def is_safe_control(name: str) -> bool:
    """Nothing is pressed during a run. Diagnose and the guard census read this."""
    return bool(SAFE_DOC_CONTROL_RE.search(name or "") and not any(
        p.search(name or "") for p in (FORBIDDEN_CONTROL_RE, AUTH_CONTROL_RE,
                                       SETTINGS_CONTROL_RE)))


def _parts(url: str):
    try:
        u = urlsplit(url or "")
        u.port  # raises on a port that is not a number
        return u
    except ValueError:
        return None


def is_app_url(url: str) -> bool:
    """A page of the web app itself, never the public site or the API."""
    u = _parts(url)
    return bool(u and u.scheme == "https" and u.hostname == APP_HOST
                and is_safe_url(url))


def is_ready_url(url: str) -> bool:
    """The web app on /boards or a page under it, where requests answer."""
    if not is_app_url(url):
        return False
    path = _parts(url).path
    return path == READY_PATH or path.startswith(READY_PATH + "/")


def _url_of(page) -> str:
    try:
        return page.url or ""
    except Exception:
        return ""


def looks_signed_out(page) -> bool:
    """The web app showing a page that asks for the PIN, off /boards. A page
    with no such field is not taken for signed in either, which only a
    statement answering as a PDF proves."""
    # A page that cannot say where it is raises here, never answers that
    # it is signed in (test_no_app_assumes_it_is_signed_in).
    url = page.url or ""
    if not is_safe_url(url):
        return False
    path = _parts(url).path.rstrip("/")
    if path in LOGIN_URL_MARKERS:
        return True
    if not is_app_url(url) or is_ready_url(url):
        return False
    try:
        return bool(page.locator("input[type='password']").count())
    except Exception:
        return False


def detect_security_challenge(page):
    if not is_app_url(_url_of(page)):
        return None
    try:
        if RATE_LIMIT_MARKERS.search(page.title() or ""):
            return "Trade Republic is limiting requests. Try again later."
    except Exception:
        pass
    return None


# -- months ----------------------------------------------------------------

def today() -> date:
    """Today, one place a test can set."""
    return date.today()


def _month(year: int, month: int) -> Month:
    last = calendar.monthrange(year, month)[1]
    return Month("%04d-%02d" % (year, month), date(year, month, 1),
                 date(year, month, last))


def _before(m: Month) -> Month:
    prev = m.first - timedelta(days=1)
    return _month(prev.year, prev.month)


def _after(m: Month) -> Month:
    nxt = m.last + timedelta(days=1)
    return _month(nxt.year, nxt.month)


def month_of(period: str) -> Optional[Month]:
    m = re.fullmatch(r"(\d{4})-(\d{2})", period or "")
    if not m or not 1 <= int(m[2]) <= 12:
        return None
    return _month(int(m[1]), int(m[2]))


def months(on: Optional[date] = None) -> List[Month]:
    """Every complete month the route reaches, newest first. The month
    today is in is left out, since its statement is not made yet, and the
    oldest is the month holding the day LOOKBACK_DAYS before today."""
    on = on or today()
    oldest = on - timedelta(days=LOOKBACK_DAYS)
    out = []
    m = _before(_month(on.year, on.month))
    while m.last >= date(oldest.year, oldest.month, 1):
        out.append(m)
        m = _before(m)
    return out


def statement_url(m: Month) -> str:
    return STATEMENT_URL + "?" + urlencode({
        "fromDate": m.first.strftime(DATE_PARAM_FORM),
        "toDate": m.last.strftime(DATE_PARAM_FORM)})


# -- the request -----------------------------------------------------------

# Runs inside the signed-in tab. One GET, with the page's own cookies, to
# the API host only, a redirect refused rather than followed. Hands back the
# status, the content type and, for a 200, the body as base64. Nothing of the
# answer's headers, and never a cookie.
_FETCH_JS = """async ({url}) => {
  const t = new URL(url);
  if (t.protocol !== 'https:' || t.hostname !== 'api.traderepublic.com'
      || t.username || t.password || (t.port && t.port !== '443')) {
    throw new Error('Refusing an off-host request');
  }
  let r;
  try {
    r = await fetch(t.href, {credentials: 'include', redirect: 'error', cache: 'no-store'});
  } catch (e) {
    return {status: 0, ct: '', b64: ''};
  }
  const ct = (r.headers.get('content-type') || '').split(';')[0].trim().toLowerCase();
  if (r.status !== 200) {
    try { if (r.body) await r.body.cancel(); } catch (e) {}
    return {status: r.status, ct, b64: ''};
  }
  const bytes = await ppRead(r);
  let s = '';
  for (let i = 0; i < bytes.length; i += 0x8000)
    s += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  return {status: 200, ct, b64: btoa(s)};
}"""


def tab_gone(page) -> bool:
    """Whether the tab has closed, which is the browser and never a month."""
    return _closed(page)


def _closed(page) -> bool:
    try:
        return bool(page.is_closed())
    except Exception:
        return True


def fetch_month(page, m: Month) -> Answer:
    """One month's statement, asked for from inside the tab.

    401 and 403 are a sign-out, 429 is Trade Republic limiting requests, a
    body that starts %PDF- is a statement, and anything else, another
    status, an empty body, a page, an error in JSON, a redirect or a fetch
    that failed, is a month with no statement PDF. Raises ListStopped when
    the tab is gone, since that is the browser and not the month."""
    url = statement_url(m)
    if not is_safe_url(url) or urlsplit(url).hostname != API_HOST:
        log.info("refused to ask a statement of another host")
        return Answer(NO_STATEMENT)
    try:
        res = intake.evaluate(page, _FETCH_JS, {"url": url}) or {}
    except intake.TooLarge:
        return Answer(TOO_LARGE, 200)
    except Exception as e:
        if _closed(page):
            raise ListStopped("The Trade Republic tab closed.") from None
        log.info("the statement request did not complete (%s)", type(e).__name__)
        return Answer(NO_STATEMENT)
    try:
        status = int(res.get("status") or 0)
    except (TypeError, ValueError):
        status = 0
    if status in (401, 403):
        return Answer(SIGNED_OUT, status)
    if status == 429:
        return Answer(LIMITED, status)
    if status != 200:
        return Answer(NO_STATEMENT, status)
    try:
        data = intake.decode(res.get("b64") or "")
    except intake.TooLarge:
        return Answer(TOO_LARGE, status)
    except Exception:
        return Answer(NO_STATEMENT, status)
    if not data.startswith(b"%PDF-"):
        return Answer(NO_STATEMENT, status)
    return Answer(PDF, status, data)


def proven(kind: str) -> bool:
    """Whether what prove_session found is a statement, the one proof."""
    return kind == PDF


def prove_session(page, recent: Sequence[Month]) -> Tuple[str, Optional[Month]]:
    """Whether the tab is signed in, by a statement answering as a PDF.

    The newest PROBE_MONTHS months are asked, newest first, until one
    answers. Gives PDF and that month, SIGNED_OUT, LIMITED, or NO_STATEMENT
    when none answered with a PDF, which proves nothing either way."""
    if not is_ready_url(_url_of(page)):
        return NO_STATEMENT, None
    for m in list(recent)[:PROBE_MONTHS]:
        try:
            got = fetch_month(page, m)
        except ListStopped:
            return NO_STATEMENT, None
        if got.kind in (PDF, SIGNED_OUT, LIMITED):
            return got.kind, m
    return NO_STATEMENT, None


# -- identity --------------------------------------------------------------

def days_of(m: Month) -> Tuple[str, str]:
    """The month's first and last day as the statement is expected to print them."""
    return m.first.strftime(PERIOD_DAY_FORM), m.last.strftime(PERIOD_DAY_FORM)


def neighbors(m: Month) -> Tuple[Month, Month]:
    """The months a statement could be confused with, either side."""
    return _before(m), _after(m)


def identity_for(m: Month) -> Identity:
    """What delivery checks the PDF against again as it places it."""
    return Identity(kind="Account Statement", extra=days_of(m))


def rivals_for(m: Month) -> tuple:
    return tuple(identity_for(n) for n in neighbors(m))


def _text(data: bytes) -> Optional[str]:
    try:
        return whole_characters("\n".join(pdf_reader.page_texts(data, 5)))
    except Exception:
        return None


def check_period(data: bytes, m: Month) -> Check:
    """Whether the PDF is this month's statement.

    Verified only when both of this month's days are printed, each as a date
    of its own, and no neighboring month has both of its own printed. One
    day found, or none, is unchecked, a neighbor's two days are refused,
    and a PDF with too little text to read is unreadable. Only verified is
    saved."""
    text = _text(data)
    if text is None or len(text.strip()) < MIN_TEXT:
        return Check("unreadable", text_chars=len(text or ""))
    low = text.lower()

    def found(month: Month) -> int:
        return sum(1 for day in days_of(month) if on_its_own(day, low))

    mine = found(m)
    rivals = [found(n) for n in neighbors(m)]
    best = max(rivals)
    if best == 2:
        return Check("refused", mine, best, len(text))
    if mine == 2:
        return Check("verified", mine, best, len(text))
    if best > mine:
        return Check("refused", mine, best, len(text))
    return Check("unchecked", mine, best, len(text))


# -- Diagnose --------------------------------------------------------------

# Each key is made of words on PaperPull's fixed list, so the file a tester
# sends keeps them. day_month_year is 31.03.2026, day_month_two_year is
# 31.03.26, year_month_day is 2026-03-31, month_day_year is anything with
# slashes, month_names counts English month names and month_names_other
# German ones.
_SHAPES = {
    "dates_day_month_year": re.compile(r"(?<![0-9.])\d{1,2}\.\d{1,2}\.\d{4}(?![0-9])"),
    "dates_day_month_two_year": re.compile(r"(?<![0-9.])\d{1,2}\.\d{1,2}\.\d{2}(?![0-9.])"),
    "dates_year_month_day": re.compile(r"(?<![0-9])\d{4}-\d{2}-\d{2}(?![0-9])"),
    "dates_month_day_year": re.compile(r"(?<![0-9])\d{1,2}/\d{1,2}/\d{2,4}(?![0-9])"),
    "month_names_other": re.compile(
        r"\b(?:januar|februar|m(?:\u00e4|ae)rz|april|mai|juni|juli|august|september|"
        r"oktober|november|dezember)\b", re.I),
    "month_names": re.compile(
        r"\b(?:january|february|march|april|may|june|july|august|september|"
        r"october|november|december)\b", re.I),
}


def survey_pdf(data: bytes, m: Month) -> dict:
    """What a statement PDF holds, as counts and yes or no, never a value.
    For a tester's Diagnose, which says which date form the PDF prints."""
    out = {"pages": 0, "text_chars": 0, "first_day_found": False,
           "last_day_found": False}
    try:
        out["pages"] = len(pdf_reader.page_texts(data))
    except Exception:
        out["pages"] = 0
    text = _text(data) or ""
    low = text.lower()
    first, last = days_of(m)
    out["text_chars"] = min(len(text), 1_000_000)
    out["first_day_found"] = on_its_own(first, low)
    out["last_day_found"] = on_its_own(last, low)
    for name, pattern in _SHAPES.items():
        out[name] = len(pattern.findall(text))
    out["identity"] = Fixed(check_period(data, m).outcome)
    return out


def status_class(status: int) -> str:
    """A status as its class, 2xx, 4xx, so no answer's detail leaves."""
    return Fixed("%dxx" % (status // 100) if status else "none")
