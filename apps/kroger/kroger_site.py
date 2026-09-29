"""ALL Kroger selectors, URL patterns, and page behavior live here.

When Kroger changes its website, repair this file only.

How Kroger works, mapped on 2026-09-21 against a signed-in account that
has NO purchases yet, plus the page's own JavaScript bundle, which names
every route and API the purchase history uses. The parts that need a
purchase to verify are marked GUESS below and are what the first tester's
Diagnose file confirms or corrects.

* The purchase history is ``https://www.kroger.com/mypurchases`` (the
  same page serves every Kroger banner, Pick 'n Save, Metro Market, Fred
  Meyer, Ralphs, King Soopers and the rest, because one account spans
  them). On open, the page asks its own API,

      GET /atlas/v1/post-order/v1/purchase-history-search?pageNo=1&pageSize=10

  which answers ``{"data": {"postOrderSearch": {"data": [...records],
  "pageNo", "pageSize", "pageTotal", "isLastPage"}}}``. The call works
  from inside the signed-in page with the session cookies and the header
  ``X-Kroger-Channel: WEB``, and ``pageSize=50`` is accepted. VERIFIED
  with an empty account (``data: []``, ``isLastPage: true``).
* Each record (GUESS, from the bundle's list component) carries
  ``purchaseType`` (IN_STORE, FUEL, SELF_SERVE_PICKUP, INSTACART_DELIVERY,
  ...), ``createdDateTime.value``, ``total``, ``status`` (CANCELLED among
  them), ``lineItems`` (upc, quantity) and either ``receiptKey``
  (a finished purchase, ``division~store~date~terminal~transaction``) or
  ``orderNumber`` (an order still pending). The bundle's own rule: a
  record with a receiptKey, or a cancelled one, links to
  ``/mypurchases/detail/<key>``, a pending order to
  ``/mypurchases/pending/<orderNumber>``.
* The **receipt page is** ``/mypurchases/image/<receiptKey>``, titled
  "Receipt", rendered by the page from the purchase details into
  ``#receipt-print-area`` (``data-testid="POT-original-receipt"``) inside
  ``.max-receipt-content``, 635px wide, with a Print button of its own
  (``#receipt-print-button``) that this app never presses. VERIFIED that
  the route exists and how it fails ("There was a problem loading the
  receipt. Please try again." for a key that is not yours). What a real
  receipt's lines look like is a GUESS until a tester's Diagnose file.
* The site sits behind Akamai Bot Manager (``window.bmak``), so this app
  drives a real Edge or Chrome, and every API call is made from inside
  the page the way the page itself makes it. Nothing is clicked.

RECORDED (#41), from a tester's Diagnose file of 2026-09-22 and his Pilot
of 2026-09-23, which saved receipts that read properly. A record carries
createdDateTime.value, handoffStoreId, total ("USD 21.48"), purchaseType,
receiptKey, lineItems holding a upc and nothing else, and status
("COMPLETED"), and never the store's name. The receipt page reads, from the
top, the order's labelled lines (Order Type, Order Date, Order Number,
Loyalty Card), the store, its street and its town, then Rewards, Order
Summary, Item Details with each item's name, price, a "3 x $2.33 each"
line and its UPC, and Payment Details. The header is
[data-testid=PO-invoice-header].

Site layer verified against the live site (empty account): 2026-09-21,
and on a tester's account with purchases: 2026-09-23
"""
from __future__ import annotations

import html as _html
import json
import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional

from paperpull_core.models import IN_STORE, ONLINE, Item, Purchase
from storage import now_iso

from paperpull_core.redact import private_words, set_private_words  # noqa: F401
from paperpull_core.urls import is_safe_url as _host_allows

log = logging.getLogger("kroger_receipts.site")

# ---------------------------------------------------------------------------
# URLs
# ---------------------------------------------------------------------------

BASE = "https://www.kroger.com"
ORDERS_URL = f"{BASE}/mypurchases"
URLS = {
    "home": ORDERS_URL,
    "orders": ORDERS_URL,
    "account": f"{BASE}/account/update",
}

SEARCH_API = "/atlas/v1/post-order/v1/purchase-history-search"
PAGE_SIZE = 50
RECEIPT_PATH = "/mypurchases/image/"
DETAIL_PATH = "/mypurchases/detail/"
PENDING_PATH = "/mypurchases/pending/"

LOGIN_URL_MARKERS = ["/signin", "/sign-in", "/login", "login.kroger", "/account/create",
                     "/authenticate", "/mfa", "/verification", "/register"]

# A finished purchase's key, division~store~date~terminal~transaction, or an
# order number. Letters, digits, tildes and dashes only.
PURCHASE_KEY_RE = re.compile(r"^[0-9A-Za-z]+(?:[~-][0-9A-Za-z]+)*$")


def receipt_url(key: str) -> str:
    return f"{BASE}{RECEIPT_PATH}{key}"


def detail_url(key: str) -> str:
    return f"{BASE}{DETAIL_PATH}{key}"


def orders_url(page_no: int = 1) -> str:
    return f"{ORDERS_URL}?tab=purchases&page={page_no}" if page_no > 1 else ORDERS_URL


# ---------------------------------------------------------------------------
# Guards. Nothing here is clicked, but the diagnostics grade every control
# and the repo-wide tests hold every app to the same standard.
# ---------------------------------------------------------------------------
FORBIDDEN_CONTROL_RE = re.compile(
    r"(add\s+(all\s+)?to\s+(cart|list)|add\s+all|buy\s+(it\s+)?again|reorder|checkout|"
    r"start\s+(your\s+)?order|modify\s+order|cancel\s+order|request\s+a\s+refund|refund|"
    r"return\s+item|report\s+(a\s+)?problem|update\s+tip|\btip\b|clip|coupon|"
    r"pay\s+now|\bpay\b|payment|contact\s+us|customer\s+support|share\s+feedback|survey|"
    r"delete|remove|subscribe|redeem|apply\s+now|sign\s+out|log\s+out|print\b)", re.I)

try:
    from paperpull_core.controls import SETTINGS_CONTROL_RE as _SHARED_SETTINGS
    FORBIDDEN_CONTROL_RE = re.compile(
        "(?:%s)|(?:%s)" % (FORBIDDEN_CONTROL_RE.pattern, _SHARED_SETTINGS.pattern),
        re.I)
except Exception:  # the shared core is optional at import time
    pass

SAFE_DOC_CONTROL_RE = re.compile(
    r"(view\s+(receipt|invoice|details|order)|receipt|purchase\s+details|purchase\s+history|"
    r"order\s+receipt|load\s+more|show\s+more|next\s+page|page\s+\d+)", re.I)

SECURITY_CHALLENGE_MARKERS = [
    "enter the characters you see", "type the characters you see",
    "are you a robot", "robot check", "press & hold", "press and hold",
    "verify you are a human", "verify you are human",
    "checking your browser before accessing",
    "access to this page has been denied", "access denied",
    "two-step verification", "enter the one time password",
    "enter the one-time password", "enter the otp",
    "enter the verification code", "confirm it's you",
    "pardon our interruption",
]

RATE_LIMIT_MARKERS = [
    "too many requests", "rate limit", "try again later",
    "temporarily blocked", "http error 429", "request was throttled",
]

FALLBACK = {
    "order_card": "[data-testid='PO-NonPendingPurchase']",
    "order_link": "a[href*='/mypurchases/detail/'], a[href*='/mypurchases/pending/']",
    "page_ready": "[data-testid='PO-NonPendingPurchase'], main",
    "receipt_area": "#receipt-print-area, [data-testid='POT-original-receipt']",
    "receipt_shell": ".max-receipt-content",
    "print_button": "#receipt-print-button, [data-testid='POT-receipt-print-button']",
    "item_row": "[data-testid='POT-original-receipt'] li, [data-testid='POT-original-receipt'] [class*='Product']",
    "print_page_body": "body",
}

# The page's own words for an empty history and for the two ways a receipt
# page fails. Verified on the live site.
NO_ORDERS_RE = re.compile(r"no\s+orders\s+yet|aren't\s+any\s+orders\s+to\s+show", re.I)
MISSING_LOYALTY_RE = re.compile(r"missing\s+loyalty\s+id", re.I)
RECEIPT_FAILED_RE = re.compile(r"problem\s+loading\s+the\s+receipt|unable\s+to\s+retrieve\s+your\s+orders", re.I)

MONEY_RE = re.compile(r"\$\s*(-?[\d,]+\.\d{2})")

# Kroger's purchase types, as the API spells them, to the folder they
# belong in and the words a person uses for them.
PURCHASE_TYPE_LABELS = {
    "IN_STORE": ("In-Store", IN_STORE),
    "FUEL": ("Fuel Center", IN_STORE),
    "SELF_SERVE_PICKUP": ("Pickup", ONLINE),
    "PICKUP": ("Pickup", ONLINE),
    "CURBSIDE": ("Pickup", ONLINE),
    "DELIVERY": ("Delivery", ONLINE),
    "INSTACART_DELIVERY": ("Delivery", ONLINE),
    "HOME_DELIVERY": ("Delivery", ONLINE),
    "SHIP": ("Ship to Home", ONLINE),
    "SHIP_TO_HOME": ("Ship to Home", ONLINE),
}


def purchase_kind(purchase_type: str) -> str:
    """Which folder a Kroger purchase type belongs in. Anything unknown is
    treated as an online order, the receipt page is the same either way."""
    return PURCHASE_TYPE_LABELS.get((purchase_type or "").upper(), ("", ONLINE))[1]


def purchase_label(purchase_type: str) -> str:
    label = PURCHASE_TYPE_LABELS.get((purchase_type or "").upper(), ("", ONLINE))[0]
    return label or (purchase_type or "").replace("_", " ").title()


def money_from_api(value) -> str:
    """The API writes money as "USD 12.34" or a number. Filenames and the
    spreadsheet want "$12.34"."""
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        return f"${value:,.2f}"
    s = str(value).strip()
    m = re.search(r"(-?[\d,]+(?:\.\d{1,2})?)", s.replace("USD", ""))
    if not m:
        return ""
    try:
        return f"${float(m.group(1).replace(',', '')):,.2f}"
    except ValueError:
        return ""


def parse_status(text: str) -> str:
    t = (text or "").strip().upper()
    if not t:
        return ""
    if t in ("CANCELLED", "CANCELED"):
        return "Canceled"
    if t in ("REFUNDED",):
        return "Refunded"
    if t in ("COMPLETED", "COMPLETE", "DELIVERED", "PICKED_UP"):
        return "Completed"
    return t.replace("_", " ").title()


def looks_signed_out(page) -> bool:
    url = (page.url or "").lower()
    if any(m in url for m in LOGIN_URL_MARKERS):
        return True
    try:
        body = page.locator("body").inner_text(timeout=5000).lower()
    except Exception:
        return False
    return ("sign in to your account" in body or "create an account" in body[:3000]) and "purchase history" not in body


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
    name = (name or "").strip()
    if not name or FORBIDDEN_CONTROL_RE.search(name):
        return False
    return bool(SAFE_DOC_CONTROL_RE.search(name))


# ---------------------------------------------------------------------------
# The purchase history, read through the page's own API
# ---------------------------------------------------------------------------

def goto_orders(page, page_no: int = 1) -> None:
    """Open the purchase history. The page itself is only the place the API
    is called from, and where a person sees what the app sees."""
    page.goto(orders_url(page_no), wait_until="domcontentloaded", timeout=60000)
    try:
        page.wait_for_selector("main", timeout=20000)
    except Exception:
        pass
    page.wait_for_timeout(2500)


def history_state(page) -> str:
    """"empty" when the page says there are no orders, "no-loyalty" when
    the account has no loyalty card to look purchases up by, else ""."""
    try:
        body = page.locator("body").inner_text(timeout=5000)
    except Exception:
        return ""
    if MISSING_LOYALTY_RE.search(body):
        return "no-loyalty"
    if NO_ORDERS_RE.search(body):
        return "empty"
    return ""


# Runs inside the signed-in page. Same URL, same header the page's own code
# sends, same cookies. Pages until the API says it is the last one.
_FETCH_HISTORY_JS = r"""
async ([api, pageSize, maxPages]) => {
  const headers = {'X-Kroger-Channel': 'WEB', 'Accept': 'application/json'};
  try { if (window.bmak && bmak.get_telemetry) headers['Akamai-BM-Telemetry'] = bmak.get_telemetry(); } catch (e) {}
  const records = [];
  let pageNo = 1, pages = 0, status = 0, last = false;
  while (pageNo <= maxPages) {
    const res = await fetch(`${api}?pageNo=${pageNo}&pageSize=${pageSize}`, {credentials: 'include', headers});
    status = res.status;
    if (!res.ok) break;
    const body = await res.json();
    const search = body && body.data && body.data.postOrderSearch;
    if (!search) break;
    pages += 1;
    for (const r of (search.data || [])) records.push(r);
    last = !!search.isLastPage || !(search.data || []).length;
    if (last) break;
    pageNo += 1;
  }
  return {status, pages, last, records};
}
"""


def fetch_history(page, max_pages: int = 200) -> dict:
    """Every purchase record the API lists, newest first as the site
    orders them. Returns {"status", "pages", "last", "records"}."""
    try:
        out = page.evaluate(_FETCH_HISTORY_JS, [SEARCH_API, PAGE_SIZE, max_pages]) or {}
    except Exception as e:
        log.warning("Purchase history API call failed: %s", e)
        return {"status": 0, "pages": 0, "last": False, "records": []}
    if out.get("status") and out["status"] != 200:
        log.warning("Purchase history API answered HTTP %s", out["status"])
    return out


def _first(d: dict, *names, default=None):
    for n in names:
        if isinstance(d, dict) and d.get(n) not in (None, ""):
            return d[n]
    return default


def _datetime_value(v) -> str:
    """The API wraps dates as {"value": "2026-09-13T15:04:05Z", ...}."""
    if isinstance(v, dict):
        v = v.get("value") or v.get("date") or ""
    s = str(v or "")
    m = re.match(r"(\d{4}-\d{2}-\d{2})", s)
    return m.group(1) if m else ""


def record_key(rec: dict) -> str:
    """The receipt key when the purchase is finished, else the order number.
    The bundle's own rule for which page a record links to."""
    key = _first(rec, "receiptKey", "receiptId", "orderNumber", "orderId", default="")
    key = str(key).strip()
    return key if PURCHASE_KEY_RE.match(key) and len(key) <= 80 else ""


def record_is_pending(rec: dict) -> bool:
    """An order with no receipt yet. Its receipt page does not exist until
    the order is fulfilled, so it is recorded and revisited next run."""
    has_receipt = bool(_first(rec, "receiptKey", "receiptId"))
    status = str(_first(rec, "status", default="")).upper()
    return not has_receipt and status not in ("CANCELLED", "CANCELED")


def record_to_purchase(rec: dict) -> Optional[Purchase]:
    """A Purchase from one API record. Field names are the bundle's, and
    each one is read with a fallback so a renamed field degrades to an
    empty column instead of a crash."""
    key = record_key(rec)
    if not key:
        return None
    ptype = str(_first(rec, "purchaseType", "fulfillmentType", "modality", default=""))
    items: List[Item] = []
    for li in rec.get("lineItems") or rec.get("items") or []:
        if not isinstance(li, dict):
            continue
        info = li.get("displayInfo") or (li.get("purchasedData") or {}).get("displayInfo") or {}
        name = _first(info, "description", "name", default="") or _first(li, "description", "name", default="")
        upc = str(_first(li, "upc", "gtin", default="") or "")
        qty = str(_first(li, "quantity", "qty", default="1") or "1")
        items.append(Item(name=(str(name) or f"UPC {upc}")[:300], quantity=qty,
                          unit_price=money_from_api(_first(li, "unitPrice", "price")),
                          line_total=money_from_api(_first(li, "total", "extendedPrice"))))
    kind = purchase_kind(ptype)
    date = _datetime_value(_first(rec, "createdDateTime", "receiptCreateDateTime", "orderCreateDateTime", "purchaseDate"))
    p = Purchase(
        purchase_type=kind,
        purchase_date=date,
        order_number=key,
        total=money_from_api(_first(rec, "total", "orderTotal", "grandTotal")),
        status=parse_status(str(_first(rec, "status", default=""))),
        # The record names no store (#41, his Diagnose). The receipt page
        # does, and extract_details reads it into store_info. The purchase
        # type was here until 0.41.0, which is what a {store} name part then
        # said, "In-Store", and it is where it belongs now, the fulfillment.
        store_info="",
        fulfillment=purchase_label(ptype),
        details_url=detail_url(key),
        receipt_url=receipt_url(key),
        items=items,
        discovered_at=now_iso(),
    )
    if record_is_pending(rec):
        p.status = p.status or "Pending"
        p.notes = "Pending order, no receipt yet"
    return p


# ---------------------------------------------------------------------------
# The receipt page = the receipt
# ---------------------------------------------------------------------------

def on_receipt_page(page) -> bool:
    return RECEIPT_PATH in (page.url or "")


def goto_receipt(page, purchase: Purchase) -> None:
    url = purchase.receipt_url if is_safe_url(purchase.receipt_url or "") else receipt_url(purchase.order_number)
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    wait_for_receipt(page)


def wait_for_receipt(page, timeout_ms: int = 30000) -> bool:
    """The receipt renders a moment after the shell, or the page says it
    could not load it. Either ends the wait."""
    try:
        page.wait_for_function(
            """([area, failed]) => !!document.querySelector(area) || new RegExp(failed, 'i').test(document.body.innerText)""",
            arg=[FALLBACK["receipt_area"], RECEIPT_FAILED_RE.pattern], timeout=timeout_ms)
    except Exception:
        log.warning("Receipt page did not render within %dms", timeout_ms)
        return False
    page.wait_for_timeout(800)
    return True


def receipt_is_present(page) -> bool:
    try:
        if page.locator(FALLBACK["receipt_area"]).count() == 0:
            return False
        text = page.locator(FALLBACK["receipt_area"]).first.inner_text(timeout=5000)
    except Exception:
        return False
    return bool(text and MONEY_RE.search(text))


def receipt_failed(page) -> bool:
    try:
        body = page.locator("body").inner_text(timeout=5000)
    except Exception:
        return False
    return bool(RECEIPT_FAILED_RE.search(body))


# GUESS. Lines on the rendered receipt, read from its text. A line that
# ends in a price and is not one of the summary labels is an item.
_SUMMARY_LINE_RE = re.compile(
    r"^(sub\s*total|subtotal|total|tax|sales\s+tax|savings|total\s+savings|coupons?|discounts?|"
    r"original\s+item\s+total|order\s+total|order\s+summary|item\s+coupons?|item\s+details|"
    r"tip|gratuity|fees?|delivery\s+fee|service\s+fee|bag\s+fee|bottle\s+deposit|"
    r"balance|change|payment|paid|amount\s+(due|paid)|ebt|snap|gift\s+card|visa|mastercard|"
    r"master\s*card|discover|amex|american\s+express|debit|credit|cash|refund|items?\s+purchased|"
    r"\d+\s+items?)\b", re.I)
_ITEM_LINE_RE = re.compile(
    r"^(?P<name>.+?)(?:\s+(?P<qty>\d+)\s*(?:x|@)\s*\$?\s*[\d,]+\.\d{2})?\s+\$\s*(?P<price>-?[\d,]+\.\d{2})\s*$")


# RECORDED (#41). The receipt page's header names the store the purchase was
# made at, the banner and not Kroger, on the line after the order's labelled
# lines and before its street and town. A tester's Metro Market receipt read
# "Order Type: In Store", "Order Date", "Order Number", "Loyalty Card (last
# 4)", then "Metro Market", then the address. The banners are the ones the
# tester listed, which are Kroger's own.
KROGER_BANNERS = (
    "Kroger", "Ralphs", "Dillons", "Smith's", "King Soopers", "Fry's", "QFC",
    "City Market", "Owen's", "Jay C", "Pay Less", "Baker's", "Gerbes",
    "Fred Meyer", "Harris Teeter", "Pick 'n Save", "Metro Market", "Mariano's",
    "Food 4 Less", "Foods Co", "Ruler Foods", "Copps",
)
# Longer names a banner's receipts can print, to the banner.
_BANNER_ALIASES = {
    "Smith's Food & Drug": "Smith's", "Fry's Food Stores": "Fry's",
    "Fry's Food & Drug": "Fry's", "Jay C Food Stores": "Jay C",
    "Pay Less Super Markets": "Pay Less", "Kroger Marketplace": "Kroger",
    "Kroger Fuel Center": "Kroger", "Baker's Supermarkets": "Baker's",
    "Fred Meyer Stores": "Fred Meyer", "King Soopers Marketplace": "King Soopers",
}


def _squash(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


_BANNER_BY_SQUASH = {_squash(b): b for b in KROGER_BANNERS}
_BANNER_BY_SQUASH.update({_squash(k): v for k, v in _BANNER_ALIASES.items()})
# Where the header ends, the first heading after it.
_HEADER_END_RE = re.compile(r"^(rewards|order\s+summary|item\s+details|total\s+savings|payment\s+details)\b",
                            re.I)
# The order's own labelled lines in the header, "Order Date: ..." and the like.
_LABELLED_RE = re.compile(r"^[A-Za-z][A-Za-z ()0-9]{0,40}:", re.I)
# What a store's name looks like, words and nothing a street or a town has.
_NAME_LINE_RE = re.compile(r"^[A-Za-z][A-Za-z'\u2019&.\- ]{1,38}[A-Za-z.]$")


def _spaced(s: str) -> str:
    return " %s " % " ".join(re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).split())


# Longest first, so a longer name a banner prints is found before the banner
# inside it.
_BANNER_WORDS = sorted(((_spaced(k), v) for k, v in
                        list(_BANNER_ALIASES.items()) + [(b, b) for b in KROGER_BANNERS]),
                       key=lambda kv: -len(kv[0]))


def banner_of(line: str) -> str:
    """The banner a line names, spelled the banner's way, or empty. A store
    number after it, "Kroger #123", is not part of it."""
    core = re.sub(r"\s*(?:#\s*)?\d+\s*$", "", (line or "").strip())
    return _BANNER_BY_SQUASH.get(_squash(core), "")


def banner_from_lines(lines) -> str:
    """The store a receipt's header names, from its lines, or empty. Only
    the header is read, since the items below it include Kroger's own brand,
    "Kroger White Corn Tortilla Chips", which is not where it was bought. A
    banner this app does not list is taken from where the store's name sits,
    the first plain line after the order's labelled ones."""
    head = []
    for ln in lines or []:
        ln = (ln or "").strip()
        if not ln:
            continue
        if _HEADER_END_RE.match(ln):
            break
        head.append(ln)
    for ln in head:
        found = banner_of(ln)
        if found:
            return found
    # A printed receipt lays the order's lines and the store side by side,
    # and a PDF's text can run them together, "Order Type: In Store Metro
    # Market", so a banner is also looked for as whole words inside a line.
    for ln in head:
        spaced = _spaced(ln)
        for words, banner in _BANNER_WORDS:
            if words in spaced:
                return banner
    seen_label = False
    for ln in head:
        if _LABELLED_RE.match(ln):
            seen_label = True
            continue
        if seen_label and _NAME_LINE_RE.match(ln):
            return ln
    return ""


def read_banner(page) -> str:
    """The store the open receipt page names in its header, or empty."""
    for sel in ("[data-testid='PO-invoice-header']", FALLBACK["receipt_area"]):
        try:
            text = page.locator(sel).first.inner_text(timeout=5000)
        except Exception:
            continue
        found = banner_from_lines(text.splitlines())
        if found:
            return found
    return ""


# RECORDED (#41). The items are the Item Details section, between its heading
# and Payment Details. The Order Summary above it prints "Original Item Total"
# and "Order Total" the way an item prints its price, a label and its amount
# on the next line, and both were read as items until 0.41.0.
_ITEMS_START_RE = re.compile(r"^item\s+details\b", re.I)
_ITEMS_END_RE = re.compile(r"^(payment\s+details|alcoholic\s+beverages\s+fulfilled|order\s+summary)\b", re.I)
# The line under an item's price, "3 x $2.49 each", or for something weighed
# "0.62 lbs x $8.99 each (approx.)", which is one item, not 0.62 of one.
_QTY_LINE_RE = re.compile(r"^(?P<n>\d+(?:\.\d+)?)\s*(?P<unit>lbs?|oz|kg|g)?\s*x\s*\$\s*(?P<each>[\d,]+\.\d{2})",
                          re.I)


def _item_lines(lines: List[str]):
    """The Item Details section's lines, and whether the receipt has one."""
    start = next((i for i, ln in enumerate(lines) if _ITEMS_START_RE.match(ln)), None)
    if start is None:
        return lines, False
    end = next((i for i in range(start + 1, len(lines)) if _ITEMS_END_RE.match(lines[i])), len(lines))
    return lines[start + 1:end], True


# Inside Item Details only a line that is nothing but a summary label is not
# an item. The start-of-name filter below would drop a real product whose
# name begins with Total, Tax, Cash or Balance, the cereal among them.
_SUMMARY_LABEL_RE = re.compile(
    r"^(original\s+item\s+total|order\s+total|sub\s*total|subtotal|total|tax|sales\s+tax|"
    r"total\s+savings|item\s+coupons?(/sales)?|item\s+coupon/sale|\d+\s+items?)$", re.I)


def _clean_item_name(name: str, in_items: bool = False) -> str:
    name = _html.unescape(re.sub(r"\s+", " ", name or "")).strip(" -:*")
    if len(name) < 3:
        return ""
    if (_SUMMARY_LABEL_RE if in_items else _SUMMARY_LINE_RE).match(name):
        return ""
    return name


def extract_items(page) -> List[Item]:
    """Line items from the rendered receipt. GUESS at the line shape, and
    an empty answer only means the spreadsheet's item rows come from the
    API record instead."""
    try:
        text = page.locator(FALLBACK["receipt_area"]).first.inner_text(timeout=8000)
    except Exception:
        return []
    return items_from_lines([ln.strip() for ln in text.splitlines() if ln.strip()])


def items_from_lines(lines: List[str]) -> List[Item]:
    """Line items from a receipt's lines, read only from its Item Details
    section when it has one."""
    items: List[Item] = []
    lines, in_items = _item_lines(lines)
    for i, ln in enumerate(lines):
        m = _ITEM_LINE_RE.match(ln)
        if m:
            name = _clean_item_name(m.group("name"), in_items)
            if name:
                items.append(Item(name=name[:300], quantity=m.group("qty") or "1",
                                  line_total=f"${m.group('price')}"))
            continue
        # A name on one line and its price on the next, and then how many.
        if i + 1 < len(lines) and re.fullmatch(r"\$\s*-?[\d,]+\.\d{2}", lines[i + 1]):
            name = _clean_item_name(ln, in_items)
            if name and not MONEY_RE.search(ln):
                qty, each = "1", ""
                q = _QTY_LINE_RE.match(lines[i + 2]) if i + 2 < len(lines) else None
                if q:
                    each = "$" + q.group("each")
                    if not q.group("unit"):
                        qty = str(int(float(q.group("n")))) if float(q.group("n")) >= 1 else "1"
                items.append(Item(name=name[:300], quantity=qty, unit_price=each,
                                  line_total="$" + re.sub(r"[^\d.,-]", "", lines[i + 1])))
    return items


def extract_details(page, purchase: Purchase) -> Purchase:
    """Fill in what the rendered receipt says. The API record already gave
    the date, total and type, so this only fills gaps and reads items."""
    try:
        text = page.locator(FALLBACK["receipt_area"]).first.inner_text(timeout=8000)
    except Exception:
        text = ""
    if text:
        m = re.search(r"^\s*total\s*:?\s*\$\s*([\d,]+\.\d{2})\s*$", text, re.I | re.M)
        if m and not purchase.total:
            purchase.total = f"${m.group(1)}"
        m = re.search(r"(\d{1,2}/\d{1,2}/\d{2,4})", text)
        if m and not purchase.purchase_date:
            mm, dd, yy = m.group(1).split("/")
            yy = yy if len(yy) == 4 else "20" + yy
            purchase.purchase_date = f"{yy}-{int(mm):02d}-{int(dd):02d}"
    items = extract_items(page)
    if items:
        purchase.items = items
    banner = read_banner(page)
    if banner:
        purchase.store_info = banner
    return purchase


def scroll_full_page(page, rounds: int = 2, delay_ms: int = 400) -> None:
    for _ in range(rounds):
        try:
            page.mouse.wheel(0, 3000)
            page.wait_for_timeout(delay_ms)
        except Exception:
            break
    try:
        page.evaluate("() => window.scrollTo(0, 0)")
    except Exception:
        pass


# Everything outside the receipt block is hidden, a live DOM display change
# only, discarded on the next navigation. The block's own Print button is
# hidden too, never pressed.
_ISOLATE_RECEIPT_JS = r"""
([area, printBtn]) => {
  const n = document.querySelector(area);
  if (!n) return false;
  let el = n;
  while (el && el.parentElement && el !== document.body) {
    for (const s of Array.from(el.parentElement.children)) {
      if (s !== el) s.style.display = 'none';
    }
    el = el.parentElement;
  }
  for (const x of n.querySelectorAll(printBtn + ', button')) x.style.display = 'none';
  const w = Math.max(n.scrollWidth, n.getBoundingClientRect().width);
  const zoom = Math.min(1, Math.max(0.5, 736 / (w + 16)));
  document.body.style.zoom = String(zoom);
  window.scrollTo(0, 0);
  return true;
}
"""


def isolate_receipt(page) -> bool:
    try:
        ok = bool(page.evaluate(_ISOLATE_RECEIPT_JS, [FALLBACK["receipt_area"], FALLBACK["print_button"]]))
    except Exception as e:
        log.warning("Receipt isolation failed: %s", e)
        return False
    if ok:
        page.wait_for_timeout(300)
    else:
        log.warning("Could not find the receipt block to isolate")
    return ok


# ---------------------------------------------------------------------------
# Diagnostics. What a tester sends back, with nothing personal in it.
# ---------------------------------------------------------------------------

# Two digits or more, so prices, dates, keys and card numbers all go, and
# a quantity of 2 or a page number 1 stays readable.
_DIGITS_RE = re.compile(r"\d{2,}")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")

# API fields whose values are safe to keep as they are (type names, status
# words, counts). Everything else that is a string is masked.
_KEEP_VALUES = {"purchaseType", "status", "fulfillmentType", "modality", "quantity", "pageNo",
                "pageSize", "pageTotal", "isLastPage", "itemType", "unitOfMeasure"}


# The owner's name and the rest of the redaction live in core. These apps
# had a fourth version of it, without the title and suffix exclusion, so
# every "Jr" and "II" on a page became [name].


def mask_text(s: str) -> str:
    for word in private_words():
        s = re.sub(re.escape(word), "[name]", s or "", flags=re.I)
    s = _EMAIL_RE.sub("<email>", s or "")
    return _DIGITS_RE.sub(lambda m: "#" * len(m.group(0)), s)


def mask_json(obj, key: str = "", depth: int = 0):
    """The SHAPE of an API answer: every key kept, string values masked
    except type and status words, lists cut to three entries."""
    if depth > 8:
        return "..."
    if isinstance(obj, dict):
        return {k: mask_json(v, k, depth + 1) for k, v in list(obj.items())[:60]}
    if isinstance(obj, list):
        return [mask_json(v, key, depth + 1) for v in obj[:3]] + (["... %d more" % (len(obj) - 3)] if len(obj) > 3 else [])
    if isinstance(obj, bool) or obj is None:
        return obj
    if isinstance(obj, (int, float)):
        return obj if key in _KEEP_VALUES else "<number>"
    s = str(obj)
    if key in _KEEP_VALUES and len(s) < 40:
        return s
    return mask_text(s)[:80]


@dataclass
class ReceiptSurvey:
    url: str = ""
    title: str = ""
    rendered: bool = False
    failed: bool = False
    lines: List[str] = field(default_factory=list)
    outline: List[str] = field(default_factory=list)
    controls: List[str] = field(default_factory=list)


_OUTLINE_JS = r"""
(area) => {
  const n = document.querySelector(area);
  if (!n) return [];
  const out = [];
  const walk = (el, d) => {
    if (d > 6 || out.length > 200) return;
    const tag = el.tagName.toLowerCase();
    const cls = (el.className || '').toString().split(' ').filter(Boolean).slice(0, 3).join('.');
    const tid = el.getAttribute('data-testid') || el.getAttribute('data-test') || '';
    out.push('  '.repeat(d) + tag + (cls ? '.' + cls : '') + (tid ? ' [' + tid + ']' : '') + (el.children.length ? '' : ' = ' + (el.innerText || '').trim().length + ' chars'));
    for (const c of el.children) walk(c, d + 1);
  };
  walk(n, 0);
  return out;
}
"""


def survey_receipt_page(page) -> ReceiptSurvey:
    """The receipt page as the tester's browser shows it, with every
    number of two digits or more and every email masked."""
    s = ReceiptSurvey(url=mask_text(page.url or ""))
    try:
        s.title = page.title() or ""
    except Exception:
        pass
    s.rendered = receipt_is_present(page)
    s.failed = receipt_failed(page)
    try:
        area = page.locator(FALLBACK["receipt_area"]).first if page.locator(FALLBACK["receipt_area"]).count() else page.locator(FALLBACK["receipt_shell"]).first
        text = area.inner_text(timeout=5000) if area.count() else ""
        s.lines = [mask_text(ln.strip()) for ln in text.splitlines() if ln.strip()][:120]
    except Exception:
        pass
    try:
        s.outline = page.evaluate(_OUTLINE_JS, FALLBACK["receipt_area"]) or []
    except Exception:
        pass
    try:
        for b in page.locator("button, a[role=button], [role=tab]").all()[:60]:
            t = (b.inner_text(timeout=500) or "").strip()
            if t and len(t) < 60:
                s.controls.append(f"{mask_text(t)} -> {'safe' if is_safe_control(t) else 'not clicked'}")
    except Exception:
        pass
    return s


def survey_history_page(page) -> dict:
    """The purchase-history page, its API answer's shape, and the page's
    own words, masked."""
    out = {"url": mask_text(page.url or ""), "title": "", "state": history_state(page),
           "api": {}, "cards_on_page": 0, "sample_records": []}
    try:
        out["title"] = page.title() or ""
    except Exception:
        pass
    try:
        out["cards_on_page"] = page.locator(FALLBACK["order_card"]).count()
    except Exception:
        pass
    hist = fetch_history(page, max_pages=1)
    out["api"] = {"status": hist.get("status"), "pages_read": hist.get("pages"),
                  "last_page": hist.get("last"), "records": len(hist.get("records") or [])}
    out["sample_records"] = mask_json(hist.get("records") or [])
    parsed = []
    for rec in (hist.get("records") or [])[:3]:
        p = record_to_purchase(rec)
        parsed.append({"key_shape": mask_text(p.order_number), "kind": p.purchase_type, "date": p.purchase_date,
                       "total": p.total, "status": p.status, "label": p.fulfillment,
                       "items": len(p.items), "pending": record_is_pending(rec)} if p else "record without a key")
    out["parsed"] = parsed
    return out


# ---------------------------------------------------------------------------
# Kept for the shared orchestrator's diagnose command
# ---------------------------------------------------------------------------

def open_receipt_section(page) -> bool:
    return receipt_is_present(page)


def find_print_receipt_controls(page) -> list:
    try:
        return page.locator(FALLBACK["print_button"]).all()
    except Exception:
        return []


def find_invoice_controls(page) -> list:
    return []


def find_printing_frame(page, wait_ms: int = 2000):
    return None


def find_receipt_iframe(page):
    return None


ALLOWED_HOSTS = {"kroger.com"}


def is_safe_url(url: str) -> bool:
    """True only for an https URL on one of this provider's own hosts.

    The check itself lives in the core, so all of them answer the same way.
    This app keeps the hosts, which is the part that really is its own."""
    return _host_allows(url, ALLOWED_HOSTS)


def to_json(obj) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False, default=str)
