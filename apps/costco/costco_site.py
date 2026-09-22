"""ALL Costco selectors, URL patterns, and page behavior live here.

When Costco changes its website, repair this file only.

BUILT WITHOUT AN ACCOUNT, 2026-09-22. Everything below marked VERIFIED was
read off the live public site. Everything marked GUESS is what a signed-in
page is expected to look like and is exactly what the first tester's
recording settles. This app exists to be corrected, not to be right.

* **Orders and purchases** is
  ``https://www.costco.com/myaccount/#/app/4900eb1f-0c10-4bd9-99c3-c59e6c1ecebf/ordersandpurchases``
  VERIFIED, and that UUID is the same for everybody. It is the OAuth
  client id, not an account id, which the sign-in redirect proves by
  carrying it as ``client_id``. The page is a hash-routed single page
  app, so the part after the ``#`` never reaches the server and the shell
  has to settle before anything is on screen.
* **Signing in** is Azure AD B2C on ``signin.costco.com``, policy
  ``B2C_1A_SSO_WCS_signup_signin_209``, which returns to
  ``https://www.costco.com/OAuthLogonCmd``. VERIFIED. Password, emailed
  passcode and passkey are all offered, so the person signs in themselves
  and this app only ever finds the session already there. A URL on
  signin.costco.com is the signed-out signal.
* **Costco is behind Akamai Bot Manager**, whose sensor script sits at
  ``/149e9513-01fa-4fb0-aad4-566afd725d1b/.../p.js``. VERIFIED, and
  verified the hard way, because that script wraps ``window.fetch`` and
  refused a fetch issued from an automated page. So this app drives a
  real Edge or Chrome, and it reads the page rather than calling an API
  behind the page's back. If the recording shows the site's own JSON
  calls, a later round can use them the way the page itself does.
* **A virtual waiting room** (queue-it) is wired into the site. VERIFIED
  that the script loads. A run can land in a queue at a busy hour, which
  looks like a page that never arrives, so it is called out by name.
* **The legacy storefront is still there**, ``LogonForm``,
  ``OrderStatusCmd`` and ``OrderStatusSummaryView`` with
  ``storeId=10301&catalogId=10701&langId=-1``. VERIFIED as links on the
  home page. Kept as a second route to try when the SPA gives nothing.
* **What a purchase looks like** is a GUESS. Costco shows online orders
  and in-warehouse receipts in the same list, usually behind two tabs,
  and the warehouse receipt is the one nobody else can get at. The card
  shape, the link to a receipt, and whether a receipt is a page or a PDF
  are all unknown until somebody records themselves opening one.

Site layer verified against the live public site (signed out): 2026-09-22
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

log = logging.getLogger("costco_receipts.site")

# ---------------------------------------------------------------------------
# URLs
# ---------------------------------------------------------------------------

BASE = "https://www.costco.com"

# The OAuth client id, which is also the myaccount app id. The same for
# every member, so this URL is a constant and not something to discover.
MYACCOUNT_APP_ID = "4900eb1f-0c10-4bd9-99c3-c59e6c1ecebf"
ORDERS_URL = f"{BASE}/myaccount/#/app/{MYACCOUNT_APP_ID}/ordersandpurchases"

# The old storefront, still mounted. Tried only when the SPA gives nothing.
LEGACY_QS = "storeId=10301&catalogId=10701&langId=-1"
LEGACY_ORDERS_URL = f"{BASE}/OrderStatusCmd?{LEGACY_QS}&URL=OrderStatusSummaryView"

URLS = {
    "home": f"{BASE}/",
    "orders": ORDERS_URL,
    "orders_legacy": LEGACY_ORDERS_URL,
    "account": f"{BASE}/myaccount/",
}

# Every route worth trying for a list of purchases, best first. Discovery
# takes the first that is not a sign-in page and has something on it. The
# recording replaces this list with the one route that is right.
ORDER_ROUTES = [ORDERS_URL, f"{BASE}/myaccount/", LEGACY_ORDERS_URL]

# GUESS. A receipt or an order detail lives under one of these. Written as
# path fragments rather than a formatted URL because which one Costco uses,
# and what it puts after it, is the main thing the recording answers.
RECEIPT_PATH = "/myaccount/#/app/%s/ordersandpurchases/" % MYACCOUNT_APP_ID
DETAIL_PATH = RECEIPT_PATH
PENDING_PATH = RECEIPT_PATH

LOGIN_URL_MARKERS = ["signin.costco.com", "/logonform", "/oauthlogoncmd",
                     "/oauth2/", "/b2c_1a_", "/login", "/sign-in", "/signin",
                     "/registration", "/join"]

# An order number or a receipt key, whatever shape Costco uses. Letters,
# digits, dashes and tildes, which covers every shape seen on comparable
# sites, and nothing that could turn a key into a path of its own.
PURCHASE_KEY_RE = re.compile(r"^[0-9A-Za-z]+(?:[~_-][0-9A-Za-z]+)*$")


def receipt_url(key: str) -> str:
    return f"{BASE}{RECEIPT_PATH}{key}"


def detail_url(key: str) -> str:
    return f"{BASE}{DETAIL_PATH}{key}"


def orders_url(page_no: int = 1) -> str:
    """The list. It is one hash route with no page in it as far as anyone
    outside an account can see, so the page number is ignored until a
    recording shows otherwise."""
    return ORDERS_URL


# ---------------------------------------------------------------------------
# Guards. This app reads the page rather than clicking through it, but the
# diagnostics grade every control and the repo-wide tests hold every app to
# the same standard.
# ---------------------------------------------------------------------------
FORBIDDEN_CONTROL_RE = re.compile(
    r"(add\s+(all\s+)?to\s+(cart|list)|add\s+all|buy\s+(it\s+)?again|reorder|checkout|"
    r"start\s+(your\s+)?order|modify\s+order|cancel\s+(order|membership|auto)|"
    r"request\s+a\s+refund|refund|return\s+item|start\s+a\s+return|report\s+(a\s+)?problem|"
    r"renew|auto\s*renew|upgrade\s+membership|membership\s+renewal|"
    r"pay\s+now|\bpay\b|payment|contact\s+us|customer\s+(service|support)|"
    r"share\s+feedback|survey|chat|delete|remove|subscribe|redeem|apply\s+now|"
    r"sign\s+out|log\s+out|print\b)", re.I)

try:
    from paperpull_core.controls import SETTINGS_CONTROL_RE as _SHARED_SETTINGS
    FORBIDDEN_CONTROL_RE = re.compile(
        "(?:%s)|(?:%s)" % (FORBIDDEN_CONTROL_RE.pattern, _SHARED_SETTINGS.pattern),
        re.I)
except Exception:  # the shared core is optional at import time
    pass

SAFE_DOC_CONTROL_RE = re.compile(
    r"(view\s+(receipt|invoice|details|order)|receipt|invoice|order\s+details|"
    r"purchase\s+details|order\s+history|purchase\s+history|orders?\s+(and|&)\s+purchases|"
    r"in.?warehouse|warehouse|online\s+orders?|view\s+more|load\s+more|show\s+more|"
    r"next\s+page|page\s+\d+)", re.I)

SECURITY_CHALLENGE_MARKERS = [
    "enter the characters you see", "type the characters you see",
    "are you a robot", "robot check", "press and hold",
    "verify you are a human", "verify you are human",
    "checking your browser before accessing",
    "access to this page has been denied", "access denied",
    "two-step verification", "enter the one time password",
    "enter the one-time password", "enter the otp",
    "enter the verification code", "confirm it's you",
    "pardon our interruption",
    # Akamai and the waiting room, both of which this site actually runs.
    "reference #", "you are now in line", "your estimated wait time",
    "waiting room", "queue-it",
]

RATE_LIMIT_MARKERS = [
    "too many requests", "rate limit", "try again later",
    "temporarily blocked", "http error 429", "request was throttled",
]

# GUESS, every one of them. Written wide on purpose, because a scaffold
# that finds too much tells a tester more than one that finds nothing.
FALLBACK = {
    "order_card": ("[data-testid*='order' i], [class*='order-card' i], "
                   "[class*='OrderCard' i], [class*='purchase' i] li, "
                   "[data-automation-id*='order' i]"),
    "order_link": ("a[href*='order' i], a[href*='receipt' i], "
                   "a[href*='invoice' i], a[href*='purchase' i]"),
    "page_ready": "#main, main, [role=main], .myaccount, body",
    "receipt_area": ("[data-testid*='receipt' i], [class*='receipt' i], "
                     "[id*='receipt' i], [class*='invoice' i]"),
    "receipt_shell": "main, [role=main], body",
    "print_button": "button[aria-label*='print' i], [data-testid*='print' i]",
    "item_row": "[class*='item' i], [data-testid*='item' i], tbody tr",
    "print_page_body": "body",
}

# The page's own words for an empty list. GUESS, in the wording these
# sites usually choose.
NO_ORDERS_RE = re.compile(
    r"no\s+orders|don't\s+have\s+any\s+orders|aren't\s+any\s+orders|"
    r"no\s+purchases|nothing\s+to\s+show\s+here", re.I)
MISSING_LOYALTY_RE = re.compile(
    r"membership\s+(number\s+)?not\s+found|add\s+your\s+membership|"
    r"link\s+your\s+membership", re.I)
RECEIPT_FAILED_RE = re.compile(
    r"problem\s+loading|unable\s+to\s+(retrieve|load|display)|"
    r"something\s+went\s+wrong|couldn't\s+load", re.I)

MONEY_RE = re.compile(r"\$\s*(-?[\d,]+\.\d{2})")

# Costco's own words for the kinds of purchase, to the folder each belongs
# in. GUESS at the exact spelling, generous on purpose so a near miss
# still files correctly.
PURCHASE_TYPE_LABELS = {
    "WAREHOUSE": ("In-Warehouse", IN_STORE),
    "IN_WAREHOUSE": ("In-Warehouse", IN_STORE),
    "IN_STORE": ("In-Warehouse", IN_STORE),
    "INSTORE": ("In-Warehouse", IN_STORE),
    "GAS": ("Gas Station", IN_STORE),
    "GAS_STATION": ("Gas Station", IN_STORE),
    "FUEL": ("Gas Station", IN_STORE),
    "PHARMACY": ("Pharmacy", IN_STORE),
    "OPTICAL": ("Optical", IN_STORE),
    "ONLINE": ("Online", ONLINE),
    "DOTCOM": ("Online", ONLINE),
    "SHIP": ("Online", ONLINE),
    "SHIP_TO_HOME": ("Online", ONLINE),
    "DELIVERY": ("Delivery", ONLINE),
    "SAME_DAY": ("Same-Day Delivery", ONLINE),
    "INSTACART": ("Same-Day Delivery", ONLINE),
    "GROCERY": ("Grocery", ONLINE),
    "TRAVEL": ("Travel", ONLINE),
    "PHOTO": ("Photo", ONLINE),
}


def purchase_kind(purchase_type: str) -> str:
    """Which folder a Costco purchase belongs in. Anything unrecognised is
    filed as an online order, because that is the one a person can always
    get at themselves if this guessed wrong."""
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
    """Costco sends a signed-out visitor to signin.costco.com, so the URL
    answers this on its own almost every time. VERIFIED by opening the
    orders route signed out and landing on the B2C authorize endpoint."""
    url = (page.url or "").lower()
    if any(m in url for m in LOGIN_URL_MARKERS):
        return True
    try:
        if page.locator("input[type='password']").count() > 0:
            return True
    except Exception:
        pass
    try:
        body = page.locator("body").inner_text(timeout=5000).lower()
    except Exception:
        return False
    signed_out = ("sign in" in body[:1500] and "email address" in body[:1500])
    return signed_out and "orders" not in body[:1500]


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
    """Open orders and purchases and wait for the app to settle.

    The route is a hash, so the server sees only /myaccount/ and the list
    is drawn afterwards. Navigating from one hash to another does not
    reload, which is why this checks where it ended up rather than
    assuming."""
    page.goto(ORDERS_URL, wait_until="domcontentloaded", timeout=60000)
    try:
        page.wait_for_selector(FALLBACK["page_ready"], timeout=20000)
    except Exception:
        pass
    # The shell arrives first and the list a moment later. There is no
    # marker to wait on that is known to be right, so this waits for the
    # page to stop changing instead.
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        page.wait_for_timeout(3000)


def goto_orders_route(page, url: str) -> None:
    """One candidate route, for discovery to try in turn."""
    if not is_safe_url(url):
        raise ValueError("refusing to open a URL that is not on costco.com")
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        page.wait_for_timeout(3000)


def history_state(page) -> str:
    '''"empty" when the page says there is nothing to show, "no-membership"
    when it wants a membership number linked first, else "".'''
    try:
        body = page.locator("body").inner_text(timeout=5000)
    except Exception:
        return ""
    if MISSING_LOYALTY_RE.search(body):
        return "no-membership"
    if NO_ORDERS_RE.search(body):
        return "empty"
    return ""


# Runs inside the signed-in page and reads what is on screen. GUESS, all
# of it. Costco's own JSON calls would be better and this app does not
# know them, which is the whole reason a recording is worth more than
# another round of guessing. Every value comes back as a string and every
# one of them is shaped like the API record record_to_purchase expects, so
# when the real call is known only this function changes.
_READ_HISTORY_JS = r"""
(sel) => {
  const seen = new Set(), out = [];
  const money = (s) => { const m = (s || '').match(/\$\s*-?[\d,]+\.\d{2}/); return m ? m[0] : ''; };
  const when = (s) => {
    let m = (s || '').match(/(\d{1,2})\/(\d{1,2})\/(\d{2,4})/);
    if (m) { const y = m[3].length === 4 ? m[3] : '20' + m[3];
             return y + '-' + String(+m[1]).padStart(2,'0') + '-' + String(+m[2]).padStart(2,'0'); }
    m = (s || '').match(/(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{1,2}),?\s+(\d{4})/i);
    if (!m) return '';
    const mo = ['jan','feb','mar','apr','may','jun','jul','aug','sep','oct','nov','dec']
                 .indexOf(m[1].slice(0,3).toLowerCase()) + 1;
    return m[3] + '-' + String(mo).padStart(2,'0') + '-' + String(+m[2]).padStart(2,'0');
  };
  // A link to something that reads like one order, and the card it sits in.
  for (const a of document.querySelectorAll(sel)) {
    const href = a.getAttribute('href') || '';
    if (!href || href === '#') continue;
    let card = a;
    for (let i = 0; i < 6 && card.parentElement; i++) {
      card = card.parentElement;
      if ((card.innerText || '').length > 60) break;
    }
    const text = (card.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 600);
    const key = (href.split(/[?#]/)[0].split('/').filter(Boolean).pop() || '').slice(0, 80);
    if (!key || seen.has(key)) continue;
    seen.add(key);
    out.push({orderNumber: key, href: a.href,
              createdDateTime: when(text), total: money(text),
              status: /cancell?ed/i.test(text) ? 'CANCELLED' : '',
              purchaseType: /warehouse|in.?store|gas|fuel|pharmacy/i.test(text)
                              ? 'WAREHOUSE' : 'ONLINE',
              cardText: text});
  }
  return out;
}
"""


def fetch_history(page, max_pages: int = 200) -> dict:
    """Every purchase the page is showing, read from the page itself.

    Named for what the orchestrator calls, not for how it works. The
    answer has the same shape a JSON API would give, so when a recording
    shows Costco's real call this is the only function that changes."""
    try:
        records = page.evaluate(_READ_HISTORY_JS, FALLBACK["order_link"]) or []
    except Exception as e:
        log.warning("Could not read the purchase list from the page: %s", e)
        return {"status": 0, "pages": 0, "last": True, "records": []}
    if not records:
        log.warning("No purchases found on the page. This app was built "
                    "without a Costco account, so the selectors are a guess. "
                    "Run `record` and send the file, and the guess becomes "
                    "the answer.")
    return {"status": 200 if records else 0, "pages": 1, "last": True,
            "records": records}


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
    href = str(_first(rec, "href", "url", default="") or "")
    if not is_safe_url(href):
        href = ""
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
        store_info=purchase_label(ptype) or "Costco",
        summary=str(_first(rec, "cardText", default="") or "")[:300],
        # The href the page itself drew, when there is one and it is on
        # Costco. A link the site made is worth more than a URL this app
        # assembled from a guess at the path.
        details_url=href or detail_url(key),
        receipt_url=href or receipt_url(key),
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
    """GUESS. Any page that is not the list and has a receipt-shaped block
    on it, since the address of a Costco receipt is unknown until a
    recording shows one being opened."""
    try:
        return page.locator(FALLBACK["receipt_area"]).count() > 0
    except Exception:
        return False


def goto_receipt(page, purchase: Purchase) -> None:
    """Open one purchase. The href read off the card is used when there is
    one, because a link the page itself drew is worth more than a URL this
    app assembled from a guess at the path."""
    url = purchase.receipt_url or ""
    if not is_safe_url(url):
        url = detail_url(purchase.order_number)
    if not is_safe_url(url):
        raise ValueError("refusing to open a URL that is not on costco.com")
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
    r"tip|gratuity|fees?|delivery\s+fee|service\s+fee|bag\s+fee|bottle\s+deposit|"
    r"balance|change|payment|paid|amount\s+(due|paid)|ebt|snap|gift\s+card|visa|mastercard|"
    r"master\s*card|discover|amex|american\s+express|debit|credit|cash|refund|items?\s+purchased|"
    r"\d+\s+items?)\b", re.I)
_ITEM_LINE_RE = re.compile(
    r"^(?P<name>.+?)(?:\s+(?P<qty>\d+)\s*(?:x|@)\s*\$?\s*[\d,]+\.\d{2})?\s+\$\s*(?P<price>-?[\d,]+\.\d{2})\s*$")


def _clean_item_name(name: str) -> str:
    name = _html.unescape(re.sub(r"\s+", " ", name or "")).strip(" -:*")
    if len(name) < 3 or _SUMMARY_LINE_RE.match(name):
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
    items: List[Item] = []
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for i, ln in enumerate(lines):
        m = _ITEM_LINE_RE.match(ln)
        if m:
            name = _clean_item_name(m.group("name"))
            if name:
                items.append(Item(name=name[:300], quantity=m.group("qty") or "1",
                                  line_total=f"${m.group('price')}"))
            continue
        # A name on one line and its price on the next.
        if i + 1 < len(lines) and re.fullmatch(r"\$\s*-?[\d,]+\.\d{2}", lines[i + 1]):
            name = _clean_item_name(ln)
            if name and not MONEY_RE.search(ln):
                items.append(Item(name=name[:300], quantity="1",
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
                       "total": p.total, "status": p.status, "label": p.store_info,
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


ALLOWED_HOSTS = {"costco.com"}


def is_safe_url(url: str) -> bool:
    """Only https URLs on costco.com or a subdomain of it."""
    from urllib.parse import urlsplit
    try:
        u = urlsplit(url or "")
    except ValueError:
        return False
    if u.scheme != "https" or not u.hostname or u.username or u.password:
        return False
    host = u.hostname.lower()
    return any(host == h or host.endswith("." + h) for h in ALLOWED_HOSTS)


def to_json(obj) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False, default=str)
