"""ALL Uber addresses, page shapes and page behavior live here.

When Uber changes a page, repair this file only.

Uber keeps its two kinds of receipt on two different sites behind two
different sign-ins, even in one browser profile. What follows was
RECORDED on the owner's own account, 2026-09-28, through a real Edge.

RIDES, riders.uber.com

* The trips page, https://riders.uber.com/trips, reads everything from
  POST /graphql, same-origin, with credentials and two headers the
  page's own calls carry, x-csrf-token "x" and x-uber-rv-session-type
  "desktop_session". This app makes the same calls from inside the page.
* Activities lists past trips newest first, five a page on the page and
  twenty when asked, with a nextPageToken that is an ISO time in base64.
  A trip has a uuid, a title that is where it went, a subtitle with the
  month, day and time but NO YEAR, and a description, "$18.64" or
  "$0.00 • Canceled".
* The account this was built on listed ten trips, the oldest from
  November 2025, and any earlier stretch answered empty. The page itself
  offers All and the last twelve months only.
* GetTrip gives the trip's start in UTC, written the way JavaScript
  prints a date, "Mon Jun 15 2026 18:05:10 GMT+0000 (Coordinated
  Universal Time)", and its fare and status.
* GetReceipt answers the receipt as HTML, the receipts the trip has had,
  newest first, and what can be done with them. A canceled trip with
  nothing charged answers no receipt at all.
* The receipt's Download PDF is a GET of
  /trips/<uuid>/receipt?contentType=PDF&timestamp=<the newest receipt's>,
  Uber's own PDF, which prints "Receipt ID # <the trip's uuid>".

UBER EATS, www.ubereats.com

* https://www.ubereats.com/orders reads POST /_p/api/getPastOrdersV1,
  same-origin, x-csrf-token "x". Ten orders a call, newest first, and the
  next ten are asked for with the last one's uuid as lastWorkflowUUID,
  until meta.hasMore is false. Each order has its completion time in UTC,
  the store, the items and the total in cents.
* The account this was built on had 21 orders from December 2024. Four
  cost nothing, a canceled order and three where the store found nothing,
  and Uber keeps no receipt for them.
* POST /_p/api/getReceiptByWorkflowUuidV1 answers the receipt as HTML and
  the timestamp of the newest one, and the receipt's Download PDF is a
  GET of /orders/<uuid>/download-receipt?contentType=PDF&timestamp=<it>.
* Receipts from December 2025 on print "Receipt ID # <an id>", which the
  HTML carries too. Older ones are an older layout that prints no id, so
  those are checked for their own date and total.

SAFETY

This module is strictly READ-ONLY and presses nothing on either site. It
makes three GraphQL queries and two Eats calls, each named in an
allowlist, and fetches the two kinds of receipt PDF, and nothing else. A
GraphQL mutation is refused before it is sent, so the page's Resend
Receipt, which emails the receipt, can never be made, and neither can a
rating, a tip, a report or a reorder. FORBIDDEN_CONTROL_RE refuses every
such control too, although nothing here presses one.
"""
from __future__ import annotations

import base64
import binascii
import html as _html
import logging
import re
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional
from urllib.parse import urlsplit

# Everything on its way into a diagnostic file goes through here.
from paperpull_core.redact import redact, set_private_words  # noqa: F401

from paperpull_core.dates import checked as _checked_date
from paperpull_core.identity import Identity
from paperpull_core.models import Item, Purchase
from paperpull_core.urls import is_safe_url as _host_allows
# Only what every app's storage has. The core's census tests import each
# site module with whichever app's storage was loaded last.
from storage import now_iso  # noqa: F401

log = logging.getLogger("uber_receipts.site")

# The two kinds of purchase, the same words storage.py routes on, and a test
# holds the two to each other.
RIDES = "Rides"
EATS = "Uber Eats"

RIDERS_HOST = "riders.uber.com"
EATS_HOST = "www.ubereats.com"
TRIPS_URL = "https://riders.uber.com/trips"
EATS_ORDERS_URL = "https://www.ubereats.com/orders"
URLS = {
    "home": TRIPS_URL,
    "login": TRIPS_URL,
    "orders": TRIPS_URL,
    "eats_orders": EATS_ORDERS_URL,
}

# RECORDED. The headers the trips page's own GraphQL calls carry. The token
# is the letter x on every call, the page never sends another.
GRAPHQL_PATH = "/graphql"
GRAPHQL_HEADERS = {"x-csrf-token": "x", "x-uber-rv-session-type": "desktop_session"}
# RECORDED. The Eats page's calls carry the same token.
EATS_HEADERS = {"x-csrf-token": "x"}

# The page's own Activities query, word for word, RECORDED.
ACTIVITIES_QUERY = """query Activities($cityID: Int, $endTimeMs: Float, $includePast: Boolean = true, $includeUpcoming: Boolean = true, $limit: Int = 5, $nextPageToken: String, $orderTypes: [RVWebCommonActivityOrderType!] = [RIDES, TRAVEL], $profileType: RVWebCommonActivityProfileType = PERSONAL, $startTimeMs: Float) {
  activities(cityID: $cityID) {
    cityID
    past(
      endTimeMs: $endTimeMs
      limit: $limit
      nextPageToken: $nextPageToken
      orderTypes: $orderTypes
      profileType: $profileType
      startTimeMs: $startTimeMs
    ) @include(if: $includePast) {
      activities {
        ...RVWebCommonActivityFragment
        __typename
      }
      nextPageToken
      __typename
    }
    upcoming @include(if: $includeUpcoming) {
      activities {
        ...RVWebCommonActivityFragment
        __typename
      }
      __typename
    }
    __typename
  }
}

fragment RVWebCommonActivityFragment on RVWebCommonActivity {
  buttons {
    isDefault
    startEnhancerIcon
    text
    url
    __typename
  }
  cardURL
  description
  imageURL {
    light
    dark
    __typename
  }
  subtitle
  title
  uuid
  __typename
}
"""

# The page's GetTrip, asked for only the fields this app keeps. The page's
# own also asks for the driver, the rating and the addresses, which nothing
# here needs.
GET_TRIP_QUERY = """query GetTrip($tripUUID: String!) {
  getTrip(tripUUID: $tripUUID) {
    trip {
      beginTripTime
      fare
      status
      uuid
      __typename
    }
    receipt {
      distance
      distanceLabel
      duration
      vehicleType
      __typename
    }
    __typename
  }
}
"""

# The page's GetReceipt, word for word apart from the layout, RECORDED.
GET_RECEIPT_QUERY = """query GetReceipt($tripUUID: String!, $timestamp: String) {
  getReceipt(tripUUID: $tripUUID, timestamp: $timestamp) {
    actionList {
      type
      helpNodeUUID
    }
    receiptData
    receiptsForJob {
      timestamp
      type
      eventUUID
    }
  }
}
"""

# The three queries this app makes, and nothing else. The page's script can
# also resend a receipt by email, rate a trip, tip and report, and none of
# those is a query here.
QUERIES = {
    "Activities": ACTIVITIES_QUERY,
    "GetTrip": GET_TRIP_QUERY,
    "GetReceipt": GET_RECEIPT_QUERY,
}
# The two Eats calls this app makes, and nothing else.
EATS_CALLS = ("getPastOrdersV1", "getReceiptByWorkflowUuidV1")
_EATS_CALL_RE = re.compile(r"^/_p/api/(?:getPastOrdersV1|getReceiptByWorkflowUuidV1)\Z")
_MUTATION_RE = re.compile(r"^\s*(?:mutation|subscription)\b", re.I)

# RECORDED shapes. A trip and an order are both known by a uuid.
UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z")
# A ride receipt's timestamp is milliseconds, an Eats one an ISO time in UTC.
RIDE_STAMP_RE = re.compile(r"^\d{10,14}\Z")
EATS_STAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z\Z")
_RECEIPT_ID_RE = re.compile(
    r"Receipt\s+ID\s*#?\s*([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
    re.I)

# At least this long between two list calls, whatever a caller asks for.
LIST_PAUSE_MS = 2000
# Twenty trips a call, RECORDED to be answered, where the page asks five.
RIDES_PER_CALL = 20
# Safety nets against a cursor that never ends. Twenty trips and ten orders
# a call, so these are eight thousand trips and four thousand orders.
MAX_RIDE_PAGES = 400
MAX_EATS_PAGES = 400
# The profiles whose trips are read. Family and delegate profiles are other
# people's trips, and personal and business are the two a person pays for.
PROFILES = ("PERSONAL", "BUSINESS")
# How long a page opened for this app is given to come back to its site,
# through auth.uber.com when a session lapsed, before it counts as signed out.
SETTLE_MS = 20000
# The largest receipt this app will take, well above the ~200 KB Uber sends.
MAX_PDF_BYTES = 25 * 1024 * 1024

# How an answer turned out, and why a walk stopped. Words, because they go
# into the survey a tester may attach.
ANSWERED = "answered"
SIGNED_OUT = "signed out"
REFUSED = "refused"
FAILED = "failed"
END = "end"
DATE_LIMIT = "date limit"
PAGE_CAP = "page cap"

# How a page opened for this app came to rest.
READY = "ready"
CHALLENGE = "challenge"

CANCELED = "Canceled"
COMPLETED = "Completed"

# Keys this app keeps in its discovery record beside the Purchase fields.
EXTRA_KEYS = ("vehicle", "subtitle")

LOGIN_HOSTS = ("auth.uber.com", "login.uber.com")
LOGIN_URL_MARKERS = ["/login", "/signin", "/sign-in", "login-redirect"]

FORBIDDEN_CONTROL_RE = re.compile(
    r"(resend|e-?mail|\brate\b|rating|\btip\b|\bhelp\b|report|\bissue\b|"
    r"problem|refund|dispute|cancel|reorder|order\s+again|re-?order|"
    r"add\s+to\s+(?:cart|order)|\bcart\b|check\s*out|place\s+order|\bpay\b|"
    r"payment|wallet|uber\s+cash|gift\s+card|redeem|promo|membership|"
    r"uber\s+one|subscribe|expense|business\s+profile|\bshare\b|\bchat\b|"
    r"contact|message|call|delete|remove|\bedit\b|schedule|reserve|"
    r"request\s+a?\s*ride|book|\bprint\b|sign\s+out|log\s+out)", re.I)

try:
    from paperpull_core.controls import SETTINGS_CONTROL_RE as _SHARED_SETTINGS
    FORBIDDEN_CONTROL_RE = re.compile(
        "(?:%s)|(?:%s)" % (FORBIDDEN_CONTROL_RE.pattern, _SHARED_SETTINGS.pattern),
        re.I)
except Exception:  # the shared core is optional at import time
    pass

SAFE_DOC_CONTROL_RE = re.compile(
    r"(receipt|invoice|download\s+pdf|trip\s+details|\bdetails\b|past\s+orders|"
    r"your\s+orders|my\s+trips|\btrips\b|\borders\b|activity)", re.I)

SECURITY_CHALLENGE_MARKERS = [
    "verify you are a human", "verify you are human", "are you a robot",
    "unusual activity", "access denied", "press and hold", "press & hold",
]
RATE_LIMIT_MARKERS = ["too many requests", "rate limit", "temporarily blocked",
                      "http error 429"]

FALLBACK = {
    "page_ready": "body",
    "sign_in_field": "input[type='password'], input[type='tel'], input[type='email']",
    "eats_orders": "a[href*='mod=orderReceipt']",
}

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
_ISO_STAMP_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?)?"
    r"(Z|[+-]\d{2}:?\d{2})?$")
# RECORDED, how GetTrip writes a time, JavaScript's own Date.toString().
_JS_STAMP_RE = re.compile(
    r"^[A-Za-z]{3}\s+([A-Za-z]{3})\s+(\d{1,2})\s+(\d{4})\s+(\d{2}):(\d{2}):(\d{2})\s+"
    r"GMT([+-]\d{4})")
# RECORDED, a trip list subtitle, "Jun 15 • 1:55 PM", with no year.
_SUBTITLE_RE = re.compile(r"^\s*([A-Za-z]{3,9})\.?\s+(\d{1,2})\b")


# ---------------------------------------------------------------------------
# Text, dates and money
# ---------------------------------------------------------------------------

_INVISIBLE = dict.fromkeys(map(ord, "​‎‏﻿"), None)


def clean(value) -> str:
    """Uber's text as a person would type it, one space between words."""
    text = "" if value is None else str(value)
    text = text.translate(_INVISIBLE).replace(" ", " ").replace("‑", "-")
    return re.sub(r"\s+", " ", text).strip()


def _offset(zone: str):
    if zone in ("Z", ""):
        return timezone.utc
    sign = -1 if zone[0] == "-" else 1
    digits = zone[1:].replace(":", "")
    return timezone(sign * timedelta(hours=int(digits[:2]), minutes=int(digits[2:4])))


def local_date(stamp, tz=None) -> str:
    """The day something happened where this computer is, or "".

    Uber writes an order's completion as "2026-04-18T18:11:52.604Z" and a
    trip's start as "Mon Jun 15 2026 18:05:10 GMT+0000 (...)", both UTC,
    RECORDED, so an evening purchase in America reads as the next day until
    it is moved. A receipt's time in milliseconds is read too. `tz` is for
    tests, and left out it is this computer's own."""
    text = str(stamp or "").strip()
    if not text:
        return ""
    moment = None
    try:
        if RIDE_STAMP_RE.match(text):
            moment = datetime.fromtimestamp(int(text) / 1000.0, tz=timezone.utc)
        else:
            m = _JS_STAMP_RE.match(text)
            if m:
                month = MONTHS.get(m.group(1).lower())
                if not month:
                    return ""
                moment = datetime(int(m.group(3)), month, int(m.group(2)),
                                  int(m.group(4)), int(m.group(5)), int(m.group(6)),
                                  tzinfo=_offset(m.group(7)))
            else:
                m = _ISO_STAMP_RE.match(text)
                if not m:
                    return ""
                day = "%s-%s-%s" % m.group(1, 2, 3)
                if not _checked_date(day, None):
                    return ""
                if m.group(4) is None or m.group(7) is None:
                    # A bare date, or a time with no zone, is already local.
                    return day
                moment = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                                  int(m.group(4)), int(m.group(5)), int(m.group(6) or 0),
                                  tzinfo=_offset(m.group(7)))
    except (ValueError, OverflowError, OSError):
        return ""
    try:
        return moment.astimezone(tz).date().isoformat()
    except (ValueError, OverflowError, OSError):
        return ""


def money_value(text) -> Optional[float]:
    """An amount as a number, negative when it is written as one, or None.

    Read by shape rather than by currency, and exactly two digits after the
    last separator is the decimal."""
    s = clean(text)
    m = re.search(r"\d[\d.,]*", s)
    if not m:
        return None
    digits = m.group(0).rstrip(".,")
    if re.search(r"[.,]\d{2}$", digits):
        digits = digits[:-3].replace(".", "").replace(",", "") + "." + digits[-2:]
    else:
        digits = digits.replace(".", "").replace(",", "")
    try:
        value = float(digits)
    except ValueError:
        return None
    return -value if re.match(r"^[^\d]*[-−(]", s) else value


def dollars(cents) -> str:
    """Cents, as Uber Eats keeps an amount, the way a receipt prints it.

    Uber sends some as floats that miss by a hair, 2045.9999999999998,
    RECORDED, so the cents are rounded before anything is printed."""
    try:
        value = int(round(float(cents)))
    except (TypeError, ValueError):
        return ""
    sign = "-" if value < 0 else ""
    value = abs(value)
    return "%s$%s.%02d" % (sign, "{:,}".format(value // 100), value % 100)


# ---------------------------------------------------------------------------
# Session / safety
# ---------------------------------------------------------------------------

def looks_signed_out(page) -> bool:
    """Uber's sign-in page by its address, or a password field on the page.

    Reading the address is allowed to raise. A page that cannot say where
    it is must never be called signed in."""
    url = (page.url or "").lower()
    try:
        host = (urlsplit(url).hostname or "").lower()
    except (TypeError, ValueError):
        return True
    if host in LOGIN_HOSTS or any(m in url for m in LOGIN_URL_MARKERS):
        return True
    try:
        if page.locator("input[type='password']").count() > 0:
            return True
    except Exception:
        pass
    return False


def detect_security_challenge(page) -> Optional[str]:
    try:
        body = page.locator("body").inner_text(timeout=5000)
    except Exception:
        body = ""
    try:
        title = (page.title() or "").lower()
    except Exception:
        title = ""
    hay = title + "\n" + (body or "").lower()[:3000]
    for m in SECURITY_CHALLENGE_MARKERS:
        if m in hay:
            return f"Security challenge detected: '{m}'"
    for m in RATE_LIMIT_MARKERS:
        if m in hay:
            return f"Possible rate limiting detected: '{m}'"
    return None


def is_safe_control(name: str) -> bool:
    """Whether a control could ever be pressed. Nothing here presses one,
    and the recorder and the census ask this all the same."""
    name = (name or "").strip()
    if not name or FORBIDDEN_CONTROL_RE.search(name):
        return False
    return bool(SAFE_DOC_CONTROL_RE.search(name))


def _host_of(page) -> str:
    try:
        return (urlsplit(page.url or "").hostname or "").lower()
    except Exception:
        return ""


def on_riders_page(page) -> bool:
    return _host_of(page) == RIDERS_HOST and is_safe_url(page.url or "")


def on_eats_page(page) -> bool:
    return _host_of(page) == EATS_HOST and is_safe_url(page.url or "")


def open_trips_page(page, wait_ms: Optional[int] = None, force: bool = False) -> str:
    """Open the trips page unless this tab is on riders.uber.com already,
    or always when `force` asks for a fresh load. READY, SIGNED_OUT or
    CHALLENGE."""
    if force or not on_riders_page(page):
        page.goto(TRIPS_URL, wait_until="domcontentloaded", timeout=60000)
    return _settle(page, on_riders_page, wait_ms)


def open_eats_page(page, wait_ms: Optional[int] = None, force: bool = False) -> str:
    """Open the Uber Eats orders page unless this tab is on Uber Eats
    already, or always when `force` asks for a fresh load. READY,
    SIGNED_OUT or CHALLENGE."""
    if force or not on_eats_page(page):
        page.goto(EATS_ORDERS_URL, wait_until="domcontentloaded", timeout=60000)
    return _settle(page, on_eats_page, wait_ms)


def refreshing(page, side: str, ask, kind_of):
    """Ask once, and when the answer says the session is gone, load the
    side's page again and ask one more time.

    RECORDED 2026-09-28. After an hour or two with nothing asked, the trips
    page's own GraphQL answered a redirect while the Uber sign-in itself was
    still good, and loading the trips page again went through auth.uber.com
    on its own and came back signed in, without anybody signing in. So a
    redirect is a sign-in only when a fresh page load says so too. Uber Eats
    is treated the same way, GUESS, never seen to lapse."""
    got = ask()
    if kind_of(got) != SIGNED_OUT:
        return got
    opener = open_trips_page if side == RIDES else open_eats_page
    try:
        state = opener(page, force=True)
    except Exception as e:
        log.info("Loading the page again did not finish (%s)", type(e).__name__)
        return got
    if state != READY:
        return got
    log.info("The session came back on a fresh page load, asking again")
    return ask()


def _settle(page, on_site, wait_ms: Optional[int] = None) -> str:
    """Where a page opened for this app came to rest. Signed out, Uber
    sends the page to auth.uber.com, RECORDED for Uber Eats. A lapsed
    session passes through auth.uber.com as well and comes back signed in
    on its own, RECORDED for the trips page, so a sign-in page is a sign-out
    only once the tab has stayed away from the site for the whole wait."""
    wait_ms = SETTLE_MS if wait_ms is None else wait_ms
    waited = 0
    while True:
        if detect_security_challenge(page):
            return CHALLENGE
        if on_site(page) and not looks_signed_out(page):
            return READY
        if waited >= wait_ms:
            return SIGNED_OUT
        page.wait_for_timeout(1000)
        waited += 1000


# ---------------------------------------------------------------------------
# Calls from inside the page
# ---------------------------------------------------------------------------

_POST_JS = r"""async ([path, headers, body]) => {
  const init = {method: 'POST', credentials: 'include', redirect: 'manual',
                headers: Object.assign({'content-type': 'application/json',
                                        'accept': 'application/json'}, headers),
                body: JSON.stringify(body)};
  let r;
  try { r = await fetch(path, init); }
  catch (e) { return {status: 0, redirected: false, failed: true, data: null}; }
  if (r.type === 'opaqueredirect' || r.redirected) {
    return {status: r.status, redirected: true, failed: false, data: null};
  }
  let data = null;
  try { data = await r.json(); } catch (e) { data = null; }
  return {status: r.status, redirected: false, failed: false, data};
}"""

_PDF_JS = r"""async ([path, limit]) => {
  let r;
  try { r = await fetch(path, {credentials: 'include', redirect: 'manual'}); }
  catch (e) { return {status: 0, redirected: false, failed: true}; }
  if (r.type === 'opaqueredirect' || r.redirected) {
    return {status: r.status, redirected: true, failed: false};
  }
  const type = r.headers.get('content-type') || '';
  const name = r.headers.get('content-disposition') || '';
  if (r.status !== 200) return {status: r.status, redirected: false, failed: false, type};
  const buf = new Uint8Array(await r.arrayBuffer());
  if (buf.length > limit) return {status: r.status, redirected: false, failed: false, type, too_big: true};
  let s = '';
  for (let i = 0; i < buf.length; i += 0x8000) {
    s += String.fromCharCode.apply(null, buf.subarray(i, i + 0x8000));
  }
  return {status: r.status, redirected: false, failed: false, type, name, b64: btoa(s)};
}"""

_NO_ANSWER = {"status": 0, "redirected": False, "failed": True, "data": None}


def gql(page, operation: str, variables: dict) -> dict:
    """One GraphQL query to riders.uber.com, made from inside the page with
    the headers the page's own calls carry. Asked once, never retried.

    Refused before anything is sent when the operation is not one of the
    three this app makes, when its text is a mutation, or when the tab is
    not on riders.uber.com, since the path is relative."""
    query = QUERIES.get(operation)
    if not query or _MUTATION_RE.match(query):
        raise ValueError("refusing a query this app does not make")
    if not on_riders_page(page):
        return dict(_NO_ANSWER)
    body = {"operationName": operation, "variables": variables or {}, "query": query}
    try:
        got = page.evaluate(_POST_JS, [GRAPHQL_PATH, GRAPHQL_HEADERS, body])
    except Exception as e:
        log.info("A call to Uber did not come back (%s)", type(e).__name__)
        return dict(_NO_ANSWER)
    return got if isinstance(got, dict) else dict(_NO_ANSWER)


def eats_call(page, name: str, body: dict) -> dict:
    """One call to Uber Eats' own API, from inside the page. Refused before
    anything is sent unless it is one of the two this app makes and the tab
    is on Uber Eats."""
    path = "/_p/api/%s" % name
    if name not in EATS_CALLS or not _EATS_CALL_RE.match(path):
        raise ValueError("refusing a call this app does not make")
    if not on_eats_page(page):
        return dict(_NO_ANSWER)
    try:
        got = page.evaluate(_POST_JS, [path, EATS_HEADERS, body or {}])
    except Exception as e:
        log.info("A call to Uber Eats did not come back (%s)", type(e).__name__)
        return dict(_NO_ANSWER)
    return got if isinstance(got, dict) else dict(_NO_ANSWER)


def gql_kind(got: dict) -> str:
    """What a GraphQL answer means.

    A redirect, 401 and 403 mean the session is gone. So does an error
    carrying a redirectUrl, which the page's own code follows to the
    sign-in page, or the code UNAUTHENTICATED, GUESS, from the page's own
    error names, never seen, since the account was never signed out."""
    got = got or {}
    status = got.get("status") or 0
    if got.get("redirected") or status in (401, 403):
        return SIGNED_OUT
    if got.get("failed") or not status:
        return FAILED
    data = got.get("data")
    errors = (data or {}).get("errors") if isinstance(data, dict) else None
    for err in errors or []:
        ext = (err or {}).get("extensions") or {}
        if ext.get("redirectUrl") or str(ext.get("code") or "").upper() == "UNAUTHENTICATED":
            return SIGNED_OUT
    if status != 200 or not isinstance(data, dict) or not data.get("data"):
        return REFUSED
    return ANSWERED


def eats_kind(got: dict) -> str:
    """What an Uber Eats answer means. It answers 200 with a status word,
    "success" or "failure", and a failure names a code, "404" for a receipt
    Uber does not have, RECORDED. A 401 or 403, as the status or as that
    code, is a sign-in, GUESS."""
    got = got or {}
    status = got.get("status") or 0
    if got.get("redirected") or status in (401, 403):
        return SIGNED_OUT
    if got.get("failed") or not status:
        return FAILED
    data = got.get("data")
    if status != 200 or not isinstance(data, dict):
        return REFUSED
    if data.get("status") != "success":
        code = str(((data.get("data") or {}) if isinstance(data.get("data"), dict)
                    else {}).get("code") or "")
        return SIGNED_OUT if code in ("401", "403") else REFUSED
    return ANSWERED


def _payload(got: dict) -> dict:
    """The data an answer carries, for either site."""
    data = (got or {}).get("data")
    inner = data.get("data") if isinstance(data, dict) else None
    return inner if isinstance(inner, dict) else {}


# ---------------------------------------------------------------------------
# Rides
# ---------------------------------------------------------------------------

def activities_of(got: dict):
    """The trips and the next page's token in one Activities answer."""
    past = ((_payload(got).get("activities") or {}).get("past") or {})
    rows = [r for r in past.get("activities") or [] if isinstance(r, dict)]
    token = past.get("nextPageToken") or ""
    return rows, token if isinstance(token, str) else ""


def token_time(token: str) -> str:
    """The ISO time a nextPageToken stands for, RECORDED to be base64 of
    one, or ""."""
    try:
        text = base64.b64decode(str(token or ""), validate=True).decode("ascii")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return ""
    return text if _ISO_STAMP_RE.match(text) else ""


def walk_rides(page, limit_date: str = "", pause_ms: Optional[int] = None,
               max_pages: int = MAX_RIDE_PAGES, profiles=PROFILES) -> dict:
    """Every past trip, newest first, one page at a time with a pause, for
    each profile. A profile stops at its end or at limit_date (a floor,
    YYYY-MM-DD), and the next profile is still read. The walk stops at a
    sign-in, at a call that is not answered, or at the page cap.

    Each trip comes back with the time window its page covered, the time
    the page before it ended and the time its own page ended, because a
    trip's subtitle has no year and the window is what places it."""
    pause_ms = LIST_PAUSE_MS if pause_ms is None else max(int(pause_ms), LIST_PAUSE_MS)
    rows, pages, stop, status, seen = [], 0, END, 0, set()
    for profile in profiles:
        token, upper = "", ""
        while True:
            if pages >= max_pages:
                stop = PAGE_CAP
                break
            if pages:
                page.wait_for_timeout(pause_ms)
            variables = {"includePast": True, "includeUpcoming": False,
                         "limit": RIDES_PER_CALL, "orderTypes": ["RIDES", "TRAVEL"],
                         "profileType": profile}
            if token:
                variables["nextPageToken"] = token
            got = refreshing(page, RIDES, lambda: gql(page, "Activities", variables), gql_kind)
            pages += 1
            kind = gql_kind(got)
            status = got.get("status") or 0
            if kind != ANSWERED:
                stop = SIGNED_OUT if kind == SIGNED_OUT else (
                    REFUSED if kind == REFUSED else FAILED)
                break
            found, token = activities_of(got)
            lower = token_time(token)
            fresh = 0
            for row in found:
                uuid = str(row.get("uuid") or "")
                if not UUID_RE.match(uuid) or uuid in seen:
                    continue
                seen.add(uuid)
                fresh += 1
                rows.append(dict(row, _window=[upper, lower], _profile=profile))
            # A page that brings nothing new is the end too, so a token that
            # repeats is not followed to the page cap.
            if not found or not token or not fresh:
                break
            if limit_date and lower and local_date(lower) and local_date(lower) < limit_date:
                # Only this profile is past the floor. A business trip in
                # scope is still read (review of 0.40.0).
                stop = DATE_LIMIT
                break
            upper = lower
        if stop not in (END, DATE_LIMIT):
            break
    return {"rides": rows, "pages": pages, "stop": stop, "status": status}


def ride_amount(row: dict) -> Optional[float]:
    """What a trip cost, from the list's own description, "$18.64" or
    "$0.00 • Canceled", RECORDED."""
    first = clean(row.get("description")).split("•")[0]
    return money_value(first)


def ride_is_paid(row: dict) -> bool:
    """Whether money was spent. A trip canceled before anything was charged
    says $0.00 and Uber keeps no receipt for it, RECORDED."""
    value = ride_amount(row)
    return value is not None and value > 0


def ride_is_canceled(row: dict) -> bool:
    return "cancel" in clean(row.get("description")).lower()


def subtitle_date(subtitle: str, window) -> str:
    """The day a trip was taken, from its subtitle and the window of time
    its list page covered, or "".

    The subtitle says "Jun 15 • 1:55 PM" with no year, even for a trip
    from the year before, RECORDED. The page before ended at `upper` and
    this one at `lower`, so the trip is the newest day with that month and
    day between the two. Only a trip GetTrip gives no start for is placed
    this way, which is one canceled with a fee."""
    m = _SUBTITLE_RE.match(clean(subtitle))
    if not m:
        return ""
    month = MONTHS.get(m.group(1)[:3].lower())
    if not month:
        return ""
    day = int(m.group(2))
    upper, lower = (list(window or []) + ["", ""])[:2]
    hi = local_date(upper) if upper else date.today().isoformat()
    lo = local_date(lower) if lower else ""
    if not hi:
        return ""
    for year in range(int(hi[:4]), int(hi[:4]) - 3, -1):
        iso = _checked_date("%04d-%02d-%02d" % (year, month, day), None)
        if iso and iso <= hi and (not lo or iso >= lo):
            return iso
    return ""


def trip_of(got: dict) -> dict:
    """GetTrip's trip and receipt facts, the few this app keeps."""
    found = _payload(got).get("getTrip") or {}
    trip = found.get("trip") or {}
    receipt = found.get("receipt") or {}
    return {
        "begin": clean(trip.get("beginTripTime")),
        "fare": clean(trip.get("fare")),
        "status": clean(trip.get("status")),
        "uuid": clean(trip.get("uuid")),
        "vehicle": clean(receipt.get("vehicleType")),
        "distance": clean(receipt.get("distance")),
        "distance_label": clean(receipt.get("distanceLabel")),
        "duration": clean(receipt.get("duration")),
    }


def read_trip(page, uuid: str) -> dict:
    if not UUID_RE.match(str(uuid or "")):
        raise ValueError("refusing a trip id that is not a uuid")
    got = refreshing(page, RIDES, lambda: gql(page, "GetTrip", {"tripUUID": uuid}), gql_kind)
    kind = gql_kind(got)
    return {"kind": kind, "status": got.get("status") or 0,
            "trip": trip_of(got) if kind == ANSWERED else {}}


def ride_summary(row: dict) -> str:
    """A ride is named for where it went, as the trip list says."""
    where = clean(row.get("title"))
    return ("Ride to %s" % where) if where else "Ride"


def ride_purchase(row: dict, trip: dict) -> Optional[Purchase]:
    """A trip as a Purchase, or None when its day cannot be told."""
    uuid = str(row.get("uuid") or "")
    if not UUID_RE.match(uuid):
        return None
    day = local_date(trip.get("begin")) or subtitle_date(row.get("subtitle"), row.get("_window"))
    if not day:
        return None
    amount = ride_amount(row)
    total = clean(trip.get("fare")) or (("$%.2f" % amount) if amount is not None else "")
    what = ", ".join(x for x in (
        trip.get("vehicle") or "Uber ride",
        (" ".join(x for x in (trip.get("distance"), trip.get("distance_label")) if x)),
        trip.get("duration")) if x)
    status = CANCELED if ride_is_canceled(row) else COMPLETED
    url = "https://riders.uber.com/trips/%s" % uuid
    return Purchase(purchase_type=RIDES, purchase_date=day, order_number=uuid,
                    total=total, status=status, details_url=url, receipt_url=url,
                    store_info="Uber", fulfillment="Ride",
                    items=[Item(name=what, quantity="1", unit_price=total,
                                line_total=total, status=status)])


def ride_extras(row: dict, trip: dict) -> dict:
    return {"vehicle": trip.get("vehicle") or "", "subtitle": clean(row.get("subtitle")),
            "summary_hint": ride_summary(row)}


def read_ride_receipt(page, uuid: str) -> dict:
    """GetReceipt for one trip. The newest receipt's timestamp, whether a
    PDF is offered, and the Receipt ID the receipt prints."""
    if not UUID_RE.match(str(uuid or "")):
        raise ValueError("refusing a trip id that is not a uuid")
    got = refreshing(page, RIDES, lambda: gql(page, "GetReceipt", {"tripUUID": uuid}), gql_kind)
    kind = gql_kind(got)
    out = {"kind": kind, "status": got.get("status") or 0, "stamp": "",
           "pdf": False, "receipt_id": "", "count": 0}
    if kind != ANSWERED:
        return out
    found = _payload(got).get("getReceipt") or {}
    receipts = [r for r in found.get("receiptsForJob") or [] if isinstance(r, dict)]
    actions = {str((a or {}).get("type") or "") for a in found.get("actionList") or []}
    stamp = str((receipts[0] if receipts else {}).get("timestamp") or "")
    out.update(stamp=stamp if RIDE_STAMP_RE.match(stamp) else "",
               pdf="DOWNLOAD_PDF" in actions,
               receipt_id=receipt_id_in(found.get("receiptData") or ""),
               count=len(receipts))
    return out


def ride_pdf_path(uuid: str, stamp: str) -> str:
    """The receipt's Download PDF, as the page builds it, RECORDED."""
    if not UUID_RE.match(str(uuid or "")):
        raise ValueError("refusing a trip id that is not a uuid")
    if stamp and not RIDE_STAMP_RE.match(str(stamp)):
        raise ValueError("refusing a receipt time that is not milliseconds")
    return "/trips/%s/receipt?contentType=PDF%s" % (uuid, ("&timestamp=%s" % stamp) if stamp else "")


# ---------------------------------------------------------------------------
# Uber Eats
# ---------------------------------------------------------------------------

def eats_page_of(got: dict):
    """The orders in one getPastOrdersV1 answer, in the order it lists them,
    and whether it says there are more."""
    data = _payload(got)
    uuids = [u for u in data.get("orderUuids") or [] if isinstance(u, str)]
    orders_map = data.get("ordersMap") or {}
    orders = [orders_map[u] for u in uuids if isinstance(orders_map.get(u), dict)]
    more = (data.get("meta") or {}).get("hasMore")
    return orders, uuids, more is not False


def walk_eats(page, limit_date: str = "", pause_ms: Optional[int] = None,
              max_pages: int = MAX_EATS_PAGES) -> dict:
    """Every past Uber Eats order, newest first, the way Show more asks for
    them, the last order's uuid as lastWorkflowUUID, RECORDED from the
    page's own code. Stops at the end, at limit_date, at a sign-in, or at a
    call that is not answered."""
    pause_ms = LIST_PAUSE_MS if pause_ms is None else max(int(pause_ms), LIST_PAUSE_MS)
    orders, pages, stop, status, last, seen = [], 0, END, 0, "", set()
    while True:
        if pages >= max_pages:
            stop = PAGE_CAP
            break
        if pages:
            page.wait_for_timeout(pause_ms)
        body = {"lastWorkflowUUID": last}
        got = refreshing(page, EATS, lambda: eats_call(page, "getPastOrdersV1", body), eats_kind)
        pages += 1
        kind = eats_kind(got)
        status = got.get("status") or 0
        if kind != ANSWERED:
            stop = SIGNED_OUT if kind == SIGNED_OUT else (
                REFUSED if kind == REFUSED else FAILED)
            break
        found, uuids, more = eats_page_of(got)
        fresh = 0
        for order in found:
            uuid = order_uuid(order)
            if not UUID_RE.match(uuid) or uuid in seen:
                continue
            seen.add(uuid)
            fresh += 1
            orders.append(order)
        if not uuids or not more or not fresh:
            break
        oldest = eats_date(found[-1]) if found else ""
        if limit_date and oldest and oldest < limit_date:
            stop = DATE_LIMIT
            break
        last = uuids[-1]
    return {"orders": orders, "pages": pages, "stop": stop, "status": status}


def _base(order: dict) -> dict:
    base = (order or {}).get("baseEaterOrder")
    return base if isinstance(base, dict) else {}


def order_uuid(order: dict) -> str:
    return str(_base(order).get("uuid") or "")


def eats_date(order: dict, tz=None) -> str:
    base = _base(order)
    return local_date(base.get("completedAt") or base.get("lastStateChangeAt"), tz)


def eats_total_cents(order: dict) -> Optional[float]:
    try:
        return float(((order or {}).get("fareInfo") or {}).get("totalPrice"))
    except (TypeError, ValueError):
        return None


def eats_is_paid(order: dict) -> bool:
    """Whether money was spent. Uber keeps no receipt for an order that
    cost nothing, a canceled one or one where the store found nothing,
    RECORDED."""
    cents = eats_total_cents(order)
    return cents is not None and round(cents) > 0


def eats_is_canceled(order: dict) -> bool:
    return bool(_base(order).get("isCancelled"))


def store_name(order: dict) -> str:
    return clean(((order or {}).get("storeInfo") or {}).get("title"))


def eats_summary(order: dict) -> str:
    """An order is named for the store it came from, as Uber names it."""
    store = store_name(order)
    return ("Eats %s" % store) if store else "Eats Order"


def eats_items(order: dict) -> List[Item]:
    cart = (_base(order).get("shoppingCart") or {})
    out = []
    for it in cart.get("items") or []:
        if not isinstance(it, dict):
            continue
        name = clean(it.get("title"))
        if not name:
            continue
        try:
            qty = int(it.get("quantity") or 1)
        except (TypeError, ValueError):
            qty = 1
        unit = dollars(it.get("price")) if it.get("price") is not None else ""
        line = dollars(float(it.get("price")) * qty) if unit else ""
        out.append(Item(name=name, quantity=str(qty), unit_price=unit, line_total=line))
    return out


def eats_receipt_url(uuid: str) -> str:
    return "https://www.ubereats.com/orders?mod=orderReceipt&modctx=%s&ps=1" % uuid


def eats_purchase(order: dict) -> Optional[Purchase]:
    """An Uber Eats order as a Purchase, or None without a uuid or a day."""
    uuid = order_uuid(order)
    day = eats_date(order)
    if not UUID_RE.match(uuid) or not day:
        return None
    base = _base(order)
    status = CANCELED if eats_is_canceled(order) else (
        COMPLETED if base.get("isCompleted") else clean(base.get("orderPhase")) or "")
    kind = clean(base.get("fulfillmentType")).replace("_", " ").title()
    return Purchase(purchase_type=EATS, purchase_date=day, order_number=uuid,
                    total=dollars(eats_total_cents(order)), status=status,
                    details_url=EATS_ORDERS_URL, receipt_url=eats_receipt_url(uuid),
                    store_info=store_name(order), fulfillment=kind,
                    items=eats_items(order))


def eats_extras(order: dict) -> dict:
    return {"summary_hint": eats_summary(order)}


def read_eats_receipt(page, uuid: str) -> dict:
    """The receipt call for one order, as the receipt window makes it. The
    newest receipt's timestamp, whether a PDF is offered, and the Receipt
    ID the receipt prints, which only newer receipts do."""
    if not UUID_RE.match(str(uuid or "")):
        raise ValueError("refusing an order id that is not a uuid")
    body = {"contentType": "WEB_HTML", "workflowUuid": uuid, "timestamp": None}
    got = refreshing(page, EATS, lambda: eats_call(page, "getReceiptByWorkflowUuidV1", body),
                     eats_kind)
    kind = eats_kind(got)
    out = {"kind": kind, "status": got.get("status") or 0, "stamp": "",
           "pdf": False, "receipt_id": "", "count": 0}
    if kind != ANSWERED:
        return out
    data = _payload(got)
    stamp = str(data.get("timestamp") or "")
    receipts = [r for r in data.get("receiptsForJob") or [] if isinstance(r, dict)]
    out.update(stamp=stamp if EATS_STAMP_RE.match(stamp) else "",
               pdf=bool(data.get("isPDFSupported")),
               receipt_id=receipt_id_in(data.get("receiptData") or ""),
               count=len(receipts))
    return out


def eats_pdf_path(uuid: str, stamp: str) -> str:
    """The receipt's Download PDF, as the page builds it, RECORDED."""
    if not UUID_RE.match(str(uuid or "")):
        raise ValueError("refusing an order id that is not a uuid")
    if stamp and not EATS_STAMP_RE.match(str(stamp)):
        raise ValueError("refusing a receipt time that is not an ISO time")
    return "/orders/%s/download-receipt?contentType=PDF&timestamp=%s" % (uuid, stamp or "")


# ---------------------------------------------------------------------------
# The receipt itself
# ---------------------------------------------------------------------------

def receipt_id_in(receipt_html: str) -> str:
    """The Receipt ID a receipt prints, read from the receipt Uber answered,
    or "". Every ride receipt prints one, and so do Eats receipts from
    December 2025 on, RECORDED."""
    text = clean(_html.unescape(re.sub(r"<[^>]+>", " ", str(receipt_html or ""))))
    m = _RECEIPT_ID_RE.search(text)
    return m.group(1).lower() if m else ""


def fetch_pdf(page, path: str, side: str = RIDES) -> dict:
    """The receipt PDF at a path this app built, fetched from inside the
    page, so it carries the page's own session. The bytes, or why not."""
    if not (path.startswith("/trips/") or path.startswith("/orders/")):
        raise ValueError("refusing a path this app did not build")
    return refreshing(page, side, lambda: _fetch_pdf_once(page, path),
                      lambda got: got.get("kind"))


def _fetch_pdf_once(page, path: str) -> dict:
    try:
        got = page.evaluate(_PDF_JS, [path, MAX_PDF_BYTES])
    except Exception as e:
        log.info("The receipt did not come back (%s)", type(e).__name__)
        got = None
    got = got if isinstance(got, dict) else {"status": 0, "failed": True}
    status = got.get("status") or 0
    out = {"kind": ANSWERED, "status": status, "data": b""}
    if got.get("redirected") or status in (401, 403):
        out["kind"] = SIGNED_OUT
    elif got.get("failed") or not status:
        out["kind"] = FAILED
    elif status != 200 or got.get("too_big") or not got.get("b64"):
        out["kind"] = REFUSED
    else:
        try:
            out["data"] = base64.b64decode(got["b64"])
        except (binascii.Error, ValueError, TypeError):
            out["kind"] = FAILED
    return out


def receipt_tokens(purchase) -> list:
    """What an Uber receipt prints of its purchase, for the last check
    before a PDF is filed.

    The core looks for the word Uber, the order number, an ISO date and
    item names. An older Uber Eats receipt paid by card can print none of
    those, RECORDED on the account this was built on, only the store, the
    date written out, short item names such as Plate and Bowl, and the
    total, so the total, the store and the date as a receipt writes it are
    asked for too.

    The total and the dates count only as numbers of their own. Found
    anywhere, a January 19 purchase's 1/19/27 is found in a November 19
    receipt's 11/19/27, and that receipt would be filed as the January
    purchase's."""
    from paperpull_core.identity import date_variants
    from paperpull_core.receipt_pdf import OnItsOwn
    total = str(getattr(purchase, "total", "") or "")
    out = [OnItsOwn((total,) if total else ()),
           getattr(purchase, "store_info", "") or "",
           OnItsOwn(date_variants(getattr(purchase, "purchase_date", "") or ""))]
    return [t for t in out if t]


def identity_for(purchase, receipt_id: str = "") -> Identity:
    """What a receipt must carry to be filed under this purchase.

    Its own Receipt ID when the receipt prints one, and nothing else, since
    a date or a total would let the wrong receipt through when two
    purchases share them. An older Uber Eats receipt prints no id, so its
    date and total are asked for instead, and it is filed when it carries
    either. It is not counted against the orders around it. A review of
    0.40.0 found a correct receipt refused and destroyed that way, when
    one neighbor shared its day, another its total, and the first
    neighbor's total was printed on it as an item's price. The receipt is
    fetched by the order's own id, so what is left to catch is a receipt
    for another day and amount altogether."""
    if receipt_id:
        return Identity(number=receipt_id, kind=getattr(purchase, "document_type", "") or "")
    return Identity(date=getattr(purchase, "purchase_date", "") or "",
                    total=getattr(purchase, "total", "") or "",
                    kind=getattr(purchase, "document_type", "") or "")


# ---------------------------------------------------------------------------
# Host allowlist. Parsed, never a string prefix.
# ---------------------------------------------------------------------------
ALLOWED_HOSTS = {RIDERS_HOST, EATS_HOST}


def is_safe_url(url: str) -> bool:
    """True only for an https URL on riders.uber.com or www.ubereats.com,
    exactly, never a subdomain of one.

    The check itself lives in the core, so all of them answer the same way.
    This app keeps the hosts, which is the part that really is its own."""
    return _host_allows(url, ALLOWED_HOSTS, subdomains=False)
