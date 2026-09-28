"""ALL Apple addresses, page shapes and page behavior live here.

When Apple changes a page, repair this file only.

Apple sells in two places, and they are two different sites behind two
different sign-ins, even in one browser profile. What follows was
RECORDED on the owner's own account, 2026-09-27, through a real Edge.

THE APP STORE AND OTHER MEDIA, reportaproblem.apple.com

* A one page app. Signed in, it lists purchases newest first, for every
  member of the family, thirty at first and more as the list scrolls.
* Its API is same-origin under /api. Every call the page makes sends
  x-apple-xsrf-token, which the page's own script keeps in
  sessionStorage, and x-apple-rap2-api 3.0.0, with credentials. This app
  makes the same calls from inside the page, the way the page makes them.
* GET /api/family names the members, each with a dsid, a given name and
  whether they are the organizer.
* POST /api/purchase/search with every member's dsid answers fifteen
  purchases and a nextBatchId, and the next batch is the same body with
  batchId added. Without a dsid it answers 400. Each purchase has a
  weborder, the purchaser's dsid, a purchaseDate in UTC, invoiceAmount,
  which is null when nothing was paid, and its line items.
* Most purchases are free downloads with no receipt, 117 of 150 on the
  account this was built on. Only purchases where money was spent are
  kept.
* GET /api/order/<weborder>/invoice.html, with a dsid header naming the
  purchaser, answers JSON whose invoice is the whole emailed receipt as
  HTML. It is rendered to PDF in a blank tab of the same browser.
* A 400, 401 or 403, or a redirect toward idmsa.apple.com, means the
  session is gone. Except that Apple can refuse one receipt with a 400 and
  its own error while the session lives, so a refused receipt counts as a
  sign-in only when the family list is refused too.

THE APPLE STORE, www.apple.com/shop and secureN.store.apple.com

* https://www.apple.com/shop/order/list embeds its orders in
  <script id="init_data">. Signed out it sends you to
  https://secureN.store.apple.com/shop/signIn/orders, and the number in
  secureN is not always the same one.
* Each order has a details page on secureN.store.apple.com, which embeds
  init_data too, with the date it was placed, the items and their status,
  the price summary and invoiceUrl.
* invoiceUrl is a printable invoice page drawn by the page's own script,
  with a Print button at the top, which is hidden in the local page before
  it is printed. A canceled order has no invoiceUrl.

SAFETY

This module is strictly READ-ONLY and presses nothing on either site. It
reads three endpoints and loads the store's list, details and invoice
pages, and nothing else. The report, refund, concern and trust and safety
endpoints the page's own script can reach are refused by an allowlist of
the three paths, and FORBIDDEN_CONTROL_RE refuses every cancel, return,
edit, buy and report control, although nothing here presses one.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple
from urllib.parse import urlsplit

# Everything on its way into a diagnostic file goes through here.
from paperpull_core.redact import redact, set_private_words  # noqa: F401

from paperpull_core.dates import checked as _checked_date
from paperpull_core.identity import Identity
from paperpull_core.models import Item, Purchase
from paperpull_core.urls import is_safe_url as _host_allows
# Only what every app's storage has. The core's census tests import each
# site module with whichever app's storage was loaded last.
from storage import now_iso

log = logging.getLogger("apple_receipts.site")

# The two kinds of purchase, the same words storage.py routes on, and a test
# holds the two to each other.
APP_STORE = "App Store"
APPLE_STORE = "Apple Store"

REPORT_HOST = "reportaproblem.apple.com"
REPORT_URL = "https://reportaproblem.apple.com/"
STORE_LIST_URL = "https://www.apple.com/shop/order/list"
URLS = {
    "home": REPORT_URL,
    "login": REPORT_URL,
    "orders": REPORT_URL,
    "store_orders": STORE_LIST_URL,
}

# RECORDED. The version header the page's own calls carry.
RAP_API_VERSION = "3.0.0"
# RECORDED. The session token the page's own script keeps for its calls.
TOKEN_KEY = "x-apple-xsrf-token"

# The three endpoints this app reads, and nothing else. The page's script can
# also reach /api/problem, /api/concern, /api/trustAndSafety,
# /api/purchase/applicableConcerns and the refund and report flows, and a
# path that is not one of these three is refused before any call is made.
FAMILY_PATH = "/api/family"
SEARCH_PATH = "/api/purchase/search"
_ALLOWED_API_RE = re.compile(
    r"^/api/(?:family|purchase/search|order/[A-Za-z0-9]{6,20}/invoice\.html)\Z")

# RECORDED shapes. A paid purchase's weborder is ten letters and digits and a
# free one's fourteen. A dsid is digits. A store order is W and ten digits.
WEBORDER_RE = re.compile(r"^[A-Za-z0-9]{6,20}\Z")
DSID_RE = re.compile(r"^\d{4,20}\Z")
STORE_ORDER_RE = re.compile(r"^W\d{6,15}\Z")

# At least this long between two searches, whatever a caller asks for.
SEARCH_PAUSE_MS = 2000
# A safety net against a cursor that never ends. Fifteen purchases a batch,
# so this is six thousand purchases.
MAX_BATCHES = 400
# Between two store details pages.
STORE_PAUSE_MS = 2000

# How an answer from Report a Problem turned out, and why a walk stopped.
# Words, because they go into the survey a tester may attach.
ANSWERED = "answered"
SIGNED_OUT = "signed out"
REFUSED = "refused"
FAILED = "failed"
END = "end"
DATE_LIMIT = "date limit"
BATCH_CAP = "batch cap"

# How a store page turned out.
READY = "ready"
NO_DATA = "no data"
CHALLENGE = "challenge"

CANCELED = "Canceled"

# Keys this app keeps in its discovery record beside the Purchase fields.
EXTRA_KEYS = ("dsid", "purchaser", "lines")

LOGIN_URL_MARKERS = ["/shop/signin", "/signin", "/sign-in", "/auth/signin",
                     "idmsa.apple.com", "appleid.apple.com/sign-in"]

FORBIDDEN_CONTROL_RE = re.compile(
    r"(report\s+a\s+problem|\breport\b|\bproblem\b|refund|\brequest\b|concern|"
    r"dispute|trust\s+and\s+safety|cancel|\breturn\b|exchange|\bedit\b|"
    r"subscribe|upgrade|renew|trade.?in|\bbuy\b|add\s+to\s+bag|\bbag\b|"
    r"check\s*out|place\s+order|\bpay\b|payment|apple\s+pay|apple\s+card|"
    r"financ|installment|gift\s+card|redeem|family\s+sharing|ask\s+to\s+buy|"
    r"\bshare\b|\bchat\b|contact|\bprint\b|sign\s+out|log\s+out)", re.I)

try:
    from paperpull_core.controls import SETTINGS_CONTROL_RE as _SHARED_SETTINGS
    FORBIDDEN_CONTROL_RE = re.compile(
        "(?:%s)|(?:%s)" % (FORBIDDEN_CONTROL_RE.pattern, _SHARED_SETTINGS.pattern),
        re.I)
except Exception:  # the shared core is optional at import time
    pass

SAFE_DOC_CONTROL_RE = re.compile(
    r"(receipt|invoice|order\s+details|view\s+order|your\s+orders|"
    r"order\s+history|purchase\s+history)", re.I)

SECURITY_CHALLENGE_MARKERS = [
    "verify you are a human", "verify you are human", "are you a robot",
    "unusual activity", "access denied",
]
RATE_LIMIT_MARKERS = ["too many requests", "rate limit", "temporarily blocked",
                      "http error 429"]

FALLBACK = {
    "store_data": "script#init_data",
    "password_field": "input[type='password']",
    "sign_in_frame": "iframe[src*='idmsa.apple.com']",
    "page_ready": "body",
}

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
_NAMED_DATE_RE = re.compile(
    r"\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|"
    r"Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    r"\.?\s+(\d{1,2}),?\s+(\d{4})(?!\d)", re.I)
_ISO_DATE_RE = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")
_US_DATE_RE = re.compile(r"(?<!\d)(\d{1,2})/(\d{1,2})/(\d{4})(?!\d)")
_STAMP_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?)?"
    r"(Z|[+-]\d{2}:?\d{2})?$")


# ---------------------------------------------------------------------------
# Text and dates
# ---------------------------------------------------------------------------

_INVISIBLE = dict.fromkeys(map(ord, "​‎‏﻿"), None)


def clean(value) -> str:
    """Apple's text as a person would type it. Product names come with
    non-breaking spaces and hyphens in them, "MacBook\\u00a0Air", which
    would otherwise reach a file name as they are."""
    text = "" if value is None else str(value)
    text = text.translate(_INVISIBLE).replace(" ", " ").replace("‑", "-")
    return re.sub(r"\s+", " ", text).strip()


def parse_date(text) -> Optional[str]:
    """The date a page shows, as YYYY-MM-DD, or None.

    Apple writes "March 4, 2026" on an order and "June 27, 2026" on a
    receipt. An ISO date is read too, with any time after it ignored, and
    a numeric date only with a four digit year, since a two digit one
    could be either century. A day that does not exist is refused."""
    text = str(text or "")
    m = _NAMED_DATE_RE.search(text)
    if m:
        try:
            iso = "%04d-%02d-%02d" % (int(m.group(3)), MONTHS[m.group(1)[:3].lower()],
                                      int(m.group(2)))
        except (KeyError, ValueError):
            iso = ""
        return _checked_date(iso, None)
    m = _ISO_DATE_RE.search(text)
    if m:
        return _checked_date("%s-%s-%s" % m.group(1, 2, 3), None)
    m = _US_DATE_RE.search(text)
    if m:
        return _checked_date("%s-%02d-%02d" % (m.group(3), int(m.group(1)),
                                               int(m.group(2))), None)
    return None


def local_date(stamp, tz=None) -> str:
    """The day a purchase was made where this computer is, or "".

    purchaseDate is written in UTC, "2026-06-27T17:42:18.074Z", RECORDED,
    so an evening purchase in America reads as the next day until it is
    moved. `tz` is for tests, and left out it is this computer's own."""
    m = _STAMP_RE.match(str(stamp or "").strip())
    if not m:
        return ""
    day = "%s-%s-%s" % m.group(1, 2, 3)
    if not _checked_date(day, None):
        return ""
    if m.group(4) is None or m.group(7) is None:
        # A bare date, or a time with no zone, is already somebody's local day.
        return day
    zone = m.group(7)
    if zone == "Z":
        offset = timezone.utc
    else:
        sign = -1 if zone[0] == "-" else 1
        digits = zone[1:].replace(":", "")
        offset = timezone(sign * timedelta(hours=int(digits[:2]), minutes=int(digits[2:])))
    try:
        moment = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                          int(m.group(4)), int(m.group(5)), int(m.group(6) or 0),
                          tzinfo=offset)
        return moment.astimezone(tz).date().isoformat()
    except (ValueError, OverflowError):
        return day


def money_value(text) -> Optional[float]:
    """An amount as a number, negative when it is written as one, or None.

    Read by shape rather than by currency, "$9.99", "9,99 €" and
    "¥1,200" all work, and exactly two digits after the last separator
    is the decimal."""
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


# ---------------------------------------------------------------------------
# Session / safety
# ---------------------------------------------------------------------------

def looks_signed_out(page) -> bool:
    """A sign-in page by its address, or a password field on the page.

    Reading the address is allowed to raise. A page that cannot say where
    it is must never be called signed in."""
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


# ---------------------------------------------------------------------------
# Report a Problem, from inside the page
# ---------------------------------------------------------------------------

def on_report_page(page) -> bool:
    try:
        host = (urlsplit(page.url or "").hostname or "").lower()
    except Exception:
        return False
    return host == REPORT_HOST and is_safe_url(page.url or "")


_TOKEN_JS = "(key) => !!window.sessionStorage.getItem(key)"


def has_session_token(page) -> bool:
    try:
        return bool(page.evaluate(_TOKEN_JS, TOKEN_KEY))
    except Exception:
        return False


def open_report_page(page, wait_ms: int = 30000) -> bool:
    """Open Report a Problem unless this tab is on it already, and wait for
    the page's own script to hold its session token. True when it does.

    The tab somebody signed in with holds the token already. A new tab is
    given it by the page as it loads, GUESS, from how the page behaves
    signed in, never seen happen in a fresh tab."""
    if not on_report_page(page):
        page.goto(REPORT_URL, wait_until="domcontentloaded", timeout=60000)
    waited = 0
    while True:
        if has_session_token(page):
            return True
        if waited >= wait_ms or looks_signed_out(page):
            return False
        page.wait_for_timeout(1000)
        waited += 1000


_API_JS = r"""async ([path, method, body, dsid, version, key]) => {
  const headers = {'accept': 'application/json, text/plain, */*',
                   'x-apple-rap2-api': version};
  const token = window.sessionStorage.getItem(key);
  if (token) headers[key] = token;
  if (dsid) headers['dsid'] = dsid;
  const init = {method, credentials: 'include', headers, redirect: 'manual'};
  if (body !== null) {
    headers['content-type'] = 'application/json';
    init.body = JSON.stringify(body);
  }
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


def api_call(page, path: str, body=None, dsid: str = "") -> dict:
    """One call to Report a Problem's API, made from inside the page with the
    headers the page's own calls carry. Asked once and never again, a
    failure is answered, not retried.

    Refused before anything is sent when the path is not one of the three
    this app reads, or when the tab is not on Report a Problem, since the
    path is relative and would go wherever the tab happens to be."""
    if not _ALLOWED_API_RE.match(path or ""):
        raise ValueError("refusing an endpoint this app does not read")
    if dsid and not DSID_RE.match(str(dsid)):
        raise ValueError("refusing a dsid that is not a number")
    if not on_report_page(page):
        return {"status": 0, "redirected": False, "failed": True, "data": None}
    method = "GET" if body is None else "POST"
    try:
        got = page.evaluate(_API_JS, [path, method, body, str(dsid or ""),
                                      RAP_API_VERSION, TOKEN_KEY])
    except Exception as e:
        log.info("A call to Report a Problem did not come back (%s)", type(e).__name__)
        return {"status": 0, "redirected": False, "failed": True, "data": None}
    return got if isinstance(got, dict) else {"status": 0, "failed": True, "data": None}


def answer_kind(got: dict) -> str:
    """What an answer means. A redirect, 400, 401 and 403 all mean the
    session is gone, RECORDED."""
    got = got or {}
    status = got.get("status") or 0
    if got.get("redirected") or status in (400, 401, 403):
        return SIGNED_OUT
    if got.get("failed") or not status:
        return FAILED
    if status != 200:
        return REFUSED
    return ANSWERED


@dataclass
class Member:
    dsid: str
    given_name: str
    organizer: bool


def members_from(data) -> List[Member]:
    """The family's members out of GET /api/family."""
    out, seen = [], set()
    listed = data.get("members") if isinstance(data, dict) else None
    for m in listed if isinstance(listed, list) else []:
        if not isinstance(m, dict):
            continue
        dsid = str(m.get("dsid") or "").strip()
        if not DSID_RE.match(dsid) or dsid in seen:
            continue
        seen.add(dsid)
        out.append(Member(dsid=dsid, given_name=clean(m.get("givenName"))[:40],
                          organizer=bool(m.get("isHeadOfHousehold"))))
    return out


def read_family(page) -> dict:
    """{"kind", "status", "members"}"""
    got = api_call(page, FAMILY_PATH)
    kind = answer_kind(got)
    members = members_from(got.get("data")) if kind == ANSWERED else []
    return {"kind": kind, "status": got.get("status") or 0, "members": members}


def purchase_date_of(raw: dict) -> str:
    return local_date((raw or {}).get("purchaseDate"))


def walk_purchases(page, dsids, limit_date: str = "", pause_ms: int = SEARCH_PAUSE_MS,
                   max_batches: int = MAX_BATCHES) -> dict:
    """Every purchase the family's search holds, a batch at a time.

    The first body names every member's dsid and each one after adds the
    batchId the last answer gave as nextBatchId, RECORDED. It stops at the
    end, when a whole batch is older than `limit_date`, since the list is
    newest first and everything after it is older still, or at the first
    answer that is not a 200, which is never asked again. A cursor seen
    twice is the end too, rather than a loop.

    Returns {"purchases": [...], "stop": word, "status": n, "batches": n}."""
    dsids = [str(d) for d in dsids if DSID_RE.match(str(d))]
    purchases, seen = [], set()
    body = {"dsids": dsids}
    batches, stop, status = 0, END, 0
    while True:
        if batches >= max_batches:
            stop = BATCH_CAP
            break
        if batches:
            # Paced like a person scrolling, and never faster than this.
            page.wait_for_timeout(max(SEARCH_PAUSE_MS, int(pause_ms)))
        got = api_call(page, SEARCH_PATH, body=body)
        batches += 1
        status = got.get("status") or 0
        kind = answer_kind(got)
        if kind != ANSWERED:
            stop = kind
            break
        data = got.get("data") if isinstance(got.get("data"), dict) else {}
        batch = [p for p in (data.get("purchases") or []) if isinstance(p, dict)]
        purchases += batch
        nxt = data.get("nextBatchId")
        if not batch or not nxt or nxt in seen:
            stop = END
            break
        if limit_date and all((purchase_date_of(p) or "9999") < limit_date for p in batch):
            stop = DATE_LIMIT
            break
        seen.add(nxt)
        body = {"batchId": nxt, "dsids": dsids}
    return {"purchases": purchases, "stop": stop, "status": status, "batches": batches}


def is_pending(raw: dict) -> bool:
    return bool((raw or {}).get("isPendingPurchase"))


def is_paid(raw: dict) -> bool:
    """Whether money was spent, which is the only kind kept.

    An invoiceAmount says so, and Apple leaves it null for a free download.
    One that is written as zero is taken at its word and skipped, GUESS,
    since none was seen. Failing that, a line item that is not free and
    had more than nothing paid for it."""
    amount = (raw or {}).get("invoiceAmount")
    if amount not in (None, ""):
        value = money_value(amount)
        if value is None or value > 0:
            return True
    for pli in (raw or {}).get("plis") or []:
        if isinstance(pli, dict) and not pli.get("isFreePurchase"):
            value = money_value(pli.get("amountPaid"))
            if value is not None and value > 0:
                return True
    return False


def line_of(pli: dict) -> dict:
    """One line item, as the fields this app keeps."""
    content = pli.get("localizedContent") if isinstance(pli.get("localizedContent"), dict) else {}
    quantity = pli.get("quantity")
    return {
        "name": clean(content.get("nameForDisplay") or pli.get("title"))[:200],
        "detail": clean(content.get("detailForDisplay"))[:200],
        "media_type": clean(content.get("mediaType"))[:60],
        "line_item_type": clean(pli.get("lineItemType"))[:60],
        "amount_paid": clean(pli.get("amountPaid"))[:20],
        "unit_price": clean(pli.get("unitStorePrice"))[:20],
        "quantity": quantity if isinstance(quantity, int) and not isinstance(quantity, bool) else None,
        "free": bool(pli.get("isFreePurchase")),
    }


def purchaser_name(dsid: str, members: List[Member], owner: str = "") -> str:
    """Whose purchase it was. The organizer is the config's owner, and
    anybody else in the family is their given name, so a child's in-app
    purchase says whose it was."""
    for m in members or []:
        if m.dsid == dsid:
            if m.organizer and (owner or "").strip():
                return owner.strip()
            return m.given_name
    return ""


# The mediaType words that already name an Apple service, RECORDED.
FIRST_PARTY_MEDIA = {
    "icloud+": "iCloud+",
    "apple one subscription": "Apple One",
    "applecare subscription": "AppleCare",
    "apple tv subscription": "Apple TV",
}
# GUESS for the rest of Apple's own, Apple Music Subscription and the like.
_APPLE_SERVICE_RE = re.compile(r"^(Apple [A-Za-z+ ]{2,30}?) Subscription$")
# Where the purchase is the app itself and nameForDisplay is its name.
_APP_KINDS = {"iosapp", "macapp"}
_APP_MEDIA = {"ios app", "app", "mac app"}
# A store listing's tagline after the app's name, "Journal: Notes and Moods".
_TAGLINE_RE = re.compile(r"\s*(?::|\s[-–—•|]\s).*$")


def short_name(text) -> str:
    """An app's name without the tagline its store listing adds."""
    return _TAGLINE_RE.sub("", clean(text)).strip()[:60]


def service_name(line: dict) -> str:
    """What was bought, the app or the service, for one line item.

    RECORDED on the owner's account. A subscription or an in-app purchase
    names the item in nameForDisplay and its app in detailForDisplay, an
    app bought outright is named in nameForDisplay, Apple One's tier is
    the name and Apple One the detail, and Roblox writes "Roblox | 80
    Robux" in the name with no detail at all."""
    media = line.get("media_type") or ""
    name, detail = line.get("name") or "", line.get("detail") or ""
    first_party = FIRST_PARTY_MEDIA.get(media.lower())
    if first_party:
        return first_party
    m = _APPLE_SERVICE_RE.match(media)
    if m:
        return m.group(1)
    if "|" in name:
        return short_name(name.split("|")[0])
    if (line.get("line_item_type") or "").lower() in _APP_KINDS or media.lower() in _APP_MEDIA:
        return short_name(name)
    return short_name(detail) or short_name(name)


HIGH, LOW = "High", "Low"
FALLBACK_SUMMARY = "App Store Purchase"


def app_store_summary(lines) -> Tuple[str, str]:
    """The name an App Store receipt is filed under, and how sure it is.

    Apple has already said what was bought, so this is not guessed from
    keywords the way a grocery receipt is. The paid lines speak first, and
    two things bought together are named together."""
    ordered = sorted((ln for ln in lines or [] if isinstance(ln, dict)),
                     key=lambda ln: bool(ln.get("free")))
    names = []
    for line in ordered:
        name = service_name(line)
        if name and name.lower() not in (n.lower() for n in names):
            names.append(name)
    if not names:
        return FALLBACK_SUMMARY, LOW
    if len(names) == 1:
        return names[0], HIGH
    if len(names) == 2:
        return "%s and %s" % (names[0], names[1]), HIGH
    return "%s and %d More" % (names[0], len(names) - 1), HIGH


def _line_label(line: dict) -> str:
    name, detail = line.get("name") or "", line.get("detail") or ""
    if detail and detail.lower() not in name.lower():
        return "%s (%s)" % (name, detail) if name else detail
    return name


def app_store_purchase(raw: dict, members: List[Member], owner: str = ""):
    """(Purchase, extras) for one paid purchase, or None.

    The extras are kept in the discovery record beside the Purchase, the
    dsid the receipt has to be asked for with, the purchaser, and the line
    items as Apple named them."""
    weborder = str((raw or {}).get("weborder") or "").strip()
    if not WEBORDER_RE.match(weborder):
        return None
    dsid = str(raw.get("dsid") or "").strip()
    lines = [line_of(p) for p in raw.get("plis") or [] if isinstance(p, dict)]
    purchaser = purchaser_name(dsid, members, owner)
    summary, confidence = app_store_summary(lines)
    items = [Item(name=_line_label(ln)[:300],
                  quantity="" if ln["quantity"] is None else str(ln["quantity"]),
                  unit_price=ln["unit_price"], line_total=ln["amount_paid"],
                  fulfillment=ln["media_type"] or ln["line_item_type"])
             for ln in lines]
    purchase = Purchase(
        purchase_type=APP_STORE,
        purchase_date=purchase_date_of(raw),
        order_number=weborder,
        total=clean(raw.get("invoiceAmount") or raw.get("estimatedTotalAmount")),
        details_url=REPORT_URL,
        receipt_url=REPORT_URL,
        store_info=APP_STORE,
        items=items,
        discovered_at=now_iso(),
        summary=summary,
        confidence=confidence,
        notes=("Purchased by %s" % purchaser) if purchaser else "",
    )
    return purchase, {"dsid": dsid if DSID_RE.match(dsid) else "",
                      "purchaser": purchaser, "lines": lines}


def merge_purchase(into, other) -> None:
    """Add a second purchase's line items to the first one with the same
    weborder, and name it again from all of them.

    GUESS that it can happen at all. Every purchase on the account this was
    built on had a weborder of its own, 165 of 165, and ten of them carried
    several line items in one purchase instead."""
    first, first_extras = into
    second, second_extras = other
    first.items = list(first.items) + list(second.items)
    first_extras["lines"] = list(first_extras.get("lines") or []) + list(second_extras.get("lines") or [])
    first.summary, first.confidence = app_store_summary(first_extras["lines"])


def purchase_counts(raws, members: List[Member]) -> dict:
    """What a walk found, in counts."""
    organizers = {m.dsid for m in members or [] if m.organizer}
    counts = {"purchases": 0, "paid": 0, "free": 0, "pending": 0, "paid_by_others": 0}
    for raw in raws or []:
        counts["purchases"] += 1
        if is_pending(raw):
            counts["pending"] += 1
        elif is_paid(raw):
            counts["paid"] += 1
            if str(raw.get("dsid") or "") not in organizers:
                counts["paid_by_others"] += 1
        else:
            counts["free"] += 1
    return counts


def invoice_path(weborder: str) -> str:
    if not WEBORDER_RE.match(weborder or ""):
        raise ValueError("not an order id this app asks for")
    return "/api/order/%s/invoice.html" % weborder


_SCRIPT_RE = re.compile(r"<script\b.*?</script\s*>", re.I | re.S)


def invoice_html_from(data) -> str:
    """The receipt out of the invoice answer, {email, invoice, refund, vat},
    RECORDED, with any script taken out before it is drawn in a tab of the
    person's own browser. Apple's receipt carries none."""
    if not isinstance(data, dict):
        return ""
    html = data.get("invoice")
    if not isinstance(html, str) or "<" not in html:
        return ""
    return _SCRIPT_RE.sub("", html)


def fetch_invoice(page, weborder: str, dsid: str) -> dict:
    """The receipt for one purchase, asked for as the page's View Receipt
    asks, with the purchaser's dsid in the header. {"kind", "status",
    "html"}."""
    if not WEBORDER_RE.match(weborder or "") or not DSID_RE.match(dsid or ""):
        return {"kind": REFUSED, "status": 0, "html": ""}
    got = api_call(page, invoice_path(weborder), dsid=dsid)
    kind = answer_kind(got)
    if kind == SIGNED_OUT and not got.get("redirected") and session_alive(page):
        # RECORDED 2026-09-27. One paid purchase's receipt answered 400 with
        # Apple's own error, actionCode DISPLAY_ERROR and the message key
        # RAP2.Error.INTERNAL_ERROR.Body, while the family list answered 200
        # beside it. Read as a sign-in, that one receipt stopped every run at
        # the same purchase. So a refused receipt is a sign-in only when the
        # family list is refused too.
        kind = REFUSED
    html = invoice_html_from(got.get("data")) if kind == ANSWERED else ""
    return {"kind": kind, "status": got.get("status") or 0, "html": html}


def session_alive(page) -> bool:
    """Whether Report a Problem still answers its family list, the cheapest
    call the page makes, so that one receipt Apple refuses is told from a
    session that is gone."""
    return answer_kind(api_call(page, FAMILY_PATH)) == ANSWERED


def identity_for(purchase) -> Identity:
    """What a receipt must carry to be filed under this purchase, its own
    order number and nothing else.

    A date or a total would let the wrong receipt through, because the
    check passes on any one fact it finds and two purchases share a day
    and a price all the time. Both of Apple's receipts print the number,
    the App Store's as "Order ID" and the Apple Store's as "Order Number",
    so a receipt without its own is refused."""
    return Identity(number=getattr(purchase, "order_number", "") or "",
                    kind=getattr(purchase, "document_type", "") or "")


# ---------------------------------------------------------------------------
# The Apple Store
# ---------------------------------------------------------------------------

_INIT_DATA_JS = ("() => { const s = document.getElementById('init_data');"
                 " return s ? s.textContent : null; }")
_HAS_INIT_DATA_JS = "() => !!document.getElementById('init_data')"


def init_data_from(text) -> Optional[dict]:
    try:
        data = json.loads(text or "")
    except (TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def read_init_data(page) -> Optional[dict]:
    try:
        return init_data_from(page.evaluate(_INIT_DATA_JS))
    except Exception:
        return None


def _store_page_state(page, wait_ms: int) -> str:
    """Whether a store page is signed out, still loading or carrying its data."""
    waited = 0
    while True:
        if looks_signed_out(page):
            return SIGNED_OUT
        try:
            if page.evaluate(_HAS_INIT_DATA_JS):
                return READY
        except Exception:
            pass
        if waited >= wait_ms:
            break
        page.wait_for_timeout(500)
        waited += 500
    return CHALLENGE if detect_security_challenge(page) else NO_DATA


def goto_store_list(page, wait_ms: int = 20000) -> str:
    """Open the order list. READY, SIGNED_OUT, CHALLENGE or NO_DATA."""
    page.goto(STORE_LIST_URL, wait_until="domcontentloaded", timeout=60000)
    return _store_page_state(page, wait_ms)


def _path_of(url: str) -> str:
    try:
        return urlsplit(url or "").path
    except ValueError:
        return ""


def is_order_detail_url(url: str) -> bool:
    return is_safe_url(url) and _path_of(url).startswith("/shop/order/detail/")


def is_invoice_url(url: str) -> bool:
    return is_safe_url(url) and _path_of(url).startswith("/shop/order/print/invoice/")


def _status_word(tracker: str = "", delivery: str = "") -> str:
    """An item's status as a word. The tracker's code first, DELIVERED,
    PICKED_UP or CANCELED, RECORDED, and the list's own words failing that."""
    code = clean(tracker).upper()
    if code:
        if code in ("CANCELED", "CANCELLED"):
            return CANCELED
        words = code.replace("_", " ").lower().split()
        return " ".join(w if (0 < i < len(words) - 1 and w in ("for", "of", "to"))
                        else w.capitalize() for i, w in enumerate(words))
    text = clean(delivery).lower()
    for prefix, word in (("cancel", CANCELED), ("picked up", "Picked Up"),
                         ("delivered", "Delivered"), ("shipped", "Shipped"),
                         ("ready", "Ready for Pickup")):
        if text.startswith(prefix):
            return word
    return ""


def parse_order_list(init) -> dict:
    """The order list's init_data as orders, RECORDED. {"orders": [...],
    "more": bool}. Each order is its number, its details address and its
    items."""
    root = (init or {}).get("orderList") if isinstance(init, dict) else None
    root = root if isinstance(root, dict) else {}
    more = bool((root.get("d") or {}).get("moreOrdersAvailable"))
    orders, seen = [], set()
    for key in root.get("c") or []:
        node = root.get(key)
        if not isinstance(node, dict):
            continue
        number = clean((node.get("d") or {}).get("webOrderNumber"))
        if not STORE_ORDER_RE.match(number):
            m = re.fullmatch(r"order-(W\d{6,15})", str(key))
            number = m.group(1) if m else ""
        if not number or number in seen:
            continue
        seen.add(number)
        items, detail_url = [], ""
        for item_key in node.get("c") or []:
            item = (node.get(item_key) or {}).get("d") if isinstance(node.get(item_key), dict) else None
            if not isinstance(item, dict):
                continue
            url = str(item.get("orderDetailUrl") or "")
            if not detail_url and is_order_detail_url(url):
                detail_url = url
            items.append({"name": clean(item.get("productShortName"))[:200],
                          "quantity": item.get("quantity"),
                          "status": _status_word("", item.get("deliveryDate"))})
        orders.append({"order_number": number, "detail_url": detail_url, "items": items})
    return {"orders": orders, "more": more}


def parse_order_detail(init) -> dict:
    """An order's details page init_data, RECORDED, as the fields this app
    keeps. invoice_url is empty when there is none, or when it is not an
    invoice address on Apple's own hosts."""
    od = (init or {}).get("orderDetail") if isinstance(init, dict) else None
    od = od if isinstance(od, dict) else {}
    header = ((od.get("orderHeader") or {}).get("d")) or {}
    invoice = str(header.get("invoiceUrl") or "")
    oi = od.get("orderItems") if isinstance(od.get("orderItems"), dict) else {}
    keys = [k for k in (oi.get("c") or []) if str(k).startswith("orderItem-")] \
        or [k for k in oi if str(k).startswith("orderItem-")]
    items = []
    for key in keys:
        node = oi.get(key) if isinstance(oi.get(key), dict) else {}
        details = (node.get("orderItemDetails") or {}).get("d") or {}
        tracker = (node.get("orderItemStatusTracker") or {}).get("d") or {}
        items.append({
            "name": clean(details.get("productName") or details.get("itemShortName"))[:200],
            "quantity": details.get("quantity"),
            "total": clean(details.get("totalPrice")),
            "list_price": clean(details.get("listPrice")),
            "status": _status_word(tracker.get("currentStatus") or tracker.get("statusDescription"),
                                   details.get("deliveryDate")),
        })
    pricing = (od.get("pricingSummary") or {}).get("d") or {}
    return {
        "order_number": clean(header.get("orderNumber")),
        "placed": parse_date(header.get("orderPlacedDate")) or "",
        "invoice_url": invoice if is_invoice_url(invoice) else "",
        "items": items,
        "subtotal": clean(pricing.get("subTotal")),
        "tax": clean(pricing.get("taxAmount")),
        "total": clean(pricing.get("orderTotal")),
    }


def read_order_detail(page, url: str, wait_ms: int = 20000):
    """(state, detail) for one order's details page. Only read, and
    nothing on it is pressed, its Edit and cancel and return controls
    included."""
    if not is_order_detail_url(url):
        return NO_DATA, None
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    state = _store_page_state(page, wait_ms)
    if state != READY:
        return state, None
    return READY, parse_order_detail(read_init_data(page))


def order_status(statuses) -> str:
    """The order's status from its items'. Canceled only when every item is."""
    words = [s for s in statuses if s]
    if words and all(w == CANCELED for w in words):
        return CANCELED
    return ", ".join(dict.fromkeys(w for w in words if w != CANCELED))


def _quantity(value) -> str:
    return str(value) if isinstance(value, int) and not isinstance(value, bool) else ""


def store_purchase(listed: dict, detail: dict) -> Optional[Purchase]:
    """One store order as a Purchase, or None when the details page named a
    different order than the list did."""
    listed, detail = listed or {}, detail or {}
    number = detail.get("order_number") or listed.get("order_number") or ""
    if listed.get("order_number") and detail.get("order_number") \
            and listed["order_number"] != detail["order_number"]:
        return None
    if not STORE_ORDER_RE.match(number):
        return None
    rows = detail.get("items") or listed.get("items") or []
    items = [Item(name=r.get("name") or "", quantity=_quantity(r.get("quantity")),
                  unit_price=r.get("list_price") or "", line_total=r.get("total") or "",
                  status=r.get("status") or "")
             for r in rows if isinstance(r, dict)]
    return Purchase(
        purchase_type=APPLE_STORE,
        purchase_date=detail.get("placed") or "",
        order_number=number,
        total=detail.get("total") or "",
        status=order_status(r.get("status") for r in rows if isinstance(r, dict)),
        details_url=listed.get("detail_url") or "",
        receipt_url=detail.get("invoice_url") or "",
        store_info=APPLE_STORE,
        items=items,
        discovered_at=now_iso(),
    )


def is_canceled(purchase) -> bool:
    """An order with no invoice whose items all read canceled."""
    return (getattr(purchase, "status", "") == CANCELED
            and not getattr(purchase, "receipt_url", ""))


def open_invoice(context, url: str):
    """The order's invoice in a new tab of the store's context. The address
    must be an invoice page on Apple's own hosts, or nothing is opened."""
    if not is_invoice_url(url):
        raise ValueError("not an invoice address this app opens")
    tab = context.new_page()
    try:
        tab.goto(url, wait_until="domcontentloaded", timeout=60000)
    except Exception:
        # A tab nobody will ever look at again is not left behind.
        try:
            tab.close()
        except Exception:
            pass
        raise
    return tab


def wait_for_invoice(page, order_number: str, timeout_ms: int = 30000) -> bool:
    """The invoice is drawn by the page's own script, so this waits until it
    shows this order's number."""
    try:
        page.wait_for_function(
            "(n) => !!(document.body && (document.body.innerText || '').includes(n))",
            arg=order_number, timeout=timeout_ms)
        page.wait_for_timeout(800)
        return True
    except Exception:
        return False


_HIDE_PRINT_JS = r"""() => {
  let hidden = 0;
  const controls = document.querySelectorAll(
      "button, a, [role='button'], input[type='button'], input[type='submit']");
  for (const el of controls) {
    const t = (el.innerText || el.value || el.getAttribute('aria-label') || '').trim();
    if (/^(print|close)$/i.test(t)) {
      el.style.setProperty('display', 'none', 'important');
      hidden++;
    }
  }
  return hidden;
}"""


def drop_blank_last_pages(path) -> int:
    """Remove pages at the end of a printed receipt that hold no text and
    no image, and answer how many went. RECORDED, the owner's first Apple
    Store invoice printed a second page with nothing on it. The first page
    is always kept, and a page with any word or picture on it ends the
    trimming, so nothing that was printed on is ever cut."""
    try:
        from pypdf import PdfReader, PdfWriter
        reader = PdfReader(str(path))
        total = keep = len(reader.pages)
        while keep > 1:
            page = reader.pages[keep - 1]
            if (page.extract_text() or "").strip():
                break
            resources = page.get("/Resources") or {}
            try:
                resources = resources.get_object()
            except Exception:
                pass
            if "/XObject" in resources:
                break
            keep -= 1
        if keep == total:
            return 0
        writer = PdfWriter()
        for page in reader.pages[:keep]:
            writer.add_page(page)
        with open(str(path), "wb") as out:
            writer.write(out)
        return total - keep
    except Exception as e:
        log.info("Could not look for blank pages at the end (%s)", type(e).__name__)
        return 0


def hide_print_controls(page) -> int:
    """Hide the invoice's own Print button, and a Close one if it has one,
    so the PDF does not show them. A display change in the local page, and
    the tab is closed afterwards. Neither is pressed. RECORDED, the page's
    own strings name them Print and Close."""
    try:
        return int(page.evaluate(_HIDE_PRINT_JS) or 0)
    except Exception as e:
        log.warning("Could not hide the invoice's Print button (%s)", type(e).__name__)
        return 0


# ---------------------------------------------------------------------------
# Host allowlist. Parsed, never a string prefix.
# ---------------------------------------------------------------------------
ALLOWED_HOSTS = {"reportaproblem.apple.com", "www.apple.com", "store.apple.com"}

# The store's secure host carries a number that changes, secure7 on one
# visit and another on the next, RECORDED. A digit run and nothing else,
# anchored, so no other name under store.apple.com passes.
SECURE_STORE_HOST_RE = re.compile(r"^secure\d{1,3}\.store\.apple\.com\Z")


def is_safe_url(url: str) -> bool:
    """True only for an https URL on one of Apple's hosts this app reads,
    exactly, never a subdomain of one.

    The check itself lives in the core, so all of them answer the same way.
    This app keeps the hosts, which is the part that really is its own."""
    if _host_allows(url, ALLOWED_HOSTS, subdomains=False):
        return True
    try:
        host = (urlsplit(url or "").hostname or "").lower().rstrip(".")
    except (TypeError, ValueError):
        return False
    return bool(SECURE_STORE_HOST_RE.match(host)) and _host_allows(url, {host}, subdomains=False)
