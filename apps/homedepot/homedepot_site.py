"""ALL homedepot.com addresses, requests and page behavior live here.

When Home Depot changes its website, repair this file only.

How Home Depot works, mapped against a signed-in account on 2026-09-25:

* The purchase history is ``https://www.homedepot.com/myaccount/purchase-history``.
  The page fills it from one request, a POST to
  ``/oms/customer/order/v1/user/<user id>/orderhistory`` with
  ``{"orderHistoryRequest": {"pageSize", "pageNumber", "startDate",
  "endDate", "timezone"}}``, answering ``orderCount`` and ``orders``, each
  with ``orderNumbers``, ``orderOrigin`` ("online"), ``salesDate``,
  ``type`` ("COM"), ``totalAmount`` and ``transactionKey``. The user id is
  in the address and is taken from the page's own request, never typed.
  The same request made from inside the signed-in page answers the same.
* **Two years is all Home Depot keeps.** A start date further back than
  about two years is refused with ``B2B_ORDER_HISTORY_ERR_8013``, "Start
  date and end date not in the range", however short the window. So the
  page's own date range and page size are used as they are, and the
  history is walked by ``pageNumber`` until ``orderCount`` is reached. Run
  this every few months and nothing is lost.
* The details page is
  ``/myaccount/order-details?orderNumber=<n>&salesDate=<iso>&orderOrigin=<origin>``.
  **Its receipt is already on it**, a block styled ``sui-hidden
  print:sui-block``, hidden on screen and shown only in print. "View
  Receipt" just calls ``window.print()``, which opens the browser's print
  dialog and blocks the window, so it is never pressed. The page is
  switched to print media instead, that block alone is kept, and it is
  printed to PDF, one page with the logo, the date, the order number, each
  item with its model and store SKU, the billing address, the card's last
  four and the payment breakdown.
* A canceled order's receipt reads "Canceled Items" and $0.00. It is
  recorded and not saved.
* Store purchases were not in the account this was built on. An order
  whose origin is not "online" is filed under In-Store and read the same
  way, which is a guess until somebody's history holds one.

SAFETY (this is a shopping account with a card on file):
  This module is strictly READ-ONLY. It reads the history through the
  page's own query, opens details pages and prints what Home Depot
  rendered. Nothing is clicked. FORBIDDEN_CONTROL_RE refuses Buy Again,
  Add to Cart, returns, cancellations, credit card and payment controls
  for the diagnostics and the repo-wide guard tests.

Site layer verified working against the live site: 2026-09-25
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import List, Optional
from urllib.parse import quote, urlsplit

# Everything on its way into a diagnostic file goes through here.
from paperpull_core.redact import redact, set_private_words  # noqa: F401

from paperpull_core.models import IN_STORE, ONLINE, Item, Purchase
from paperpull_core.urls import is_safe_url as _host_allows
from paperpull_core.dates import checked as _checked_date
from storage import now_iso

log = logging.getLogger("homedepot_receipts.site")

BASE = "https://www.homedepot.com"
ORDERS_URL = f"{BASE}/myaccount/purchase-history"
DETAILS_URL = f"{BASE}/myaccount/order-details"
URLS = {
    "home": ORDERS_URL,
    "orders": ORDERS_URL,
    "account": f"{BASE}/myaccount/dashboard",
}

LOGIN_URL_MARKERS = ["/auth/view/signin", "/signin", "/sign-in", "/login", "identity.homedepot.com",
                     "/verify", "/mfa"]

HISTORY_PATH_RE = re.compile(r"^/oms/customer/order/v1/user/([A-Za-z0-9]{6,40})/orderhistory$")
ORDER_NUMBER_RE = re.compile(r"^[A-Z0-9]{6,20}$")

FORBIDDEN_CONTROL_RE = re.compile(
    r"(buy\s+(it\s+)?again|add\s+to\s+cart|checkout|reorder|subscribe|"
    r"start\s+a\s+return|\breturn\b|cancel|change\s+(delivery|pickup|store)|reschedule|"
    r"track\s+(delivery|package)|write\s+a\s+review|\breview\b|protection\s+plan|"
    r"credit\s+card|pay\s+(your|now)|\bpay\b|payment|instant\s+checkout|apply\s+now|"
    r"view\s+receipt|print|magic\s+apron|survey|"
    r"delete|remove|sign\s+out|log\s+out|chat|feedback)", re.I)

try:
    from paperpull_core.controls import SETTINGS_CONTROL_RE as _SHARED_SETTINGS
    FORBIDDEN_CONTROL_RE = re.compile(
        "(?:%s)|(?:%s)" % (FORBIDDEN_CONTROL_RE.pattern, _SHARED_SETTINGS.pattern),
        re.I)
except Exception:  # the shared core is optional at import time
    pass

SAFE_DOC_CONTROL_RE = re.compile(
    r"(purchase\s+history|order\s+details|order\s+#|skip\s+to\s+(next|previous|first|last)\s+page|^\d{1,3}$)",
    re.I)

SECURITY_CHALLENGE_MARKERS = [
    "press & hold", "press and hold", "verify you are a human", "verify you are human",
    "are you a robot", "access denied", "enter the verification code",
    "enter the code we sent", "checking your browser before accessing",
]
RATE_LIMIT_MARKERS = ["too many requests", "rate limit", "temporarily blocked", "http error 429"]

FALLBACK = {
    "order_link": "a[href*='/myaccount/order-details']",
    "receipt_block": "div[class*='print:sui-block']",
    "page_ready": "a[href*='/myaccount/order-details'], div[class*='print:sui-block']",
    "print_page_body": "body",
}

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
DATE_RE = re.compile(r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
                     r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|"
                     r"Dec(?:ember)?)\.?\s+(\d{1,2}),?\s+(\d{4})", re.I)
MONEY_RE = re.compile(r"-?\$\s*([\d,]+\.\d{2})")


def parse_date(text) -> Optional[str]:
    """The date a page is showing, as YYYY-MM-DD, refused when it names a
    day that does not exist."""
    m = DATE_RE.search(text or "")
    if not m:
        return None
    try:
        iso = f"{int(m.group(3)):04d}-{MONTHS[m.group(1)[:3].lower()]:02d}-{int(m.group(2)):02d}"
    except (KeyError, ValueError):
        return None
    return _checked_date(iso, None)


def parse_money(text: str) -> str:
    m = MONEY_RE.search(text or "")
    return f"${m.group(1)}" if m else ""


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
    try:
        if page.locator(FALLBACK["page_ready"]).count() > 0:
            return None
        body = page.locator("body").inner_text(timeout=5000)
    except Exception:
        body = ""
    try:
        title = (page.title() or "").lower()
    except Exception:
        title = ""
    hay = title + "\n" + (body or "").lower()[:2000]
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
# The history, through the page's own request
# ---------------------------------------------------------------------------

def history_request_ok(url: str) -> bool:
    """The page's own history request, on Home Depot's host and at the one
    path it uses. Nothing else is ever replayed."""
    if not is_safe_url(url or ""):
        return False
    return bool(HISTORY_PATH_RE.match(urlsplit(url).path))


# How long the purchase history gets to ask for its orders, how long the
# page is left to settle after that, and how long a page that never asked is
# watched for a bot check. A check can hold the page blank while it decides
# and only then show itself, so a request running late is not the same as a
# page that is fine.
ORDERS_WAIT_MS = 20000
SETTLE_MS = 1000
CHALLENGE_WAIT_MS = 15000


def goto_orders(page, wait_ms: Optional[int] = None) -> Optional[dict]:
    """Open the purchase history and keep the page's own history request,
    its address and its body. None when the page made none.

    The request is what shows a signed-in history, since the page asks for
    its orders whether or not there are any. None is not an empty history
    and not a signed-in session."""
    wait_ms = ORDERS_WAIT_MS if wait_ms is None else wait_ms
    seen = {}

    def on_request(req):
        if "request" not in seen and history_request_ok(req.url or "") and req.method == "POST":
            try:
                body = json.loads(req.post_data or "{}")
            except ValueError:
                body = {}
            if isinstance(body.get("orderHistoryRequest"), dict):
                seen["request"] = {"url": req.url, "body": body}

    page.on("request", on_request)
    try:
        page.goto(ORDERS_URL, wait_until="domcontentloaded", timeout=60000)
        waited = 0
        while waited < wait_ms and "request" not in seen:
            page.wait_for_timeout(500)
            waited += 500
        page.wait_for_timeout(SETTLE_MS)
    finally:
        try:
            page.remove_listener("request", on_request)
        except Exception:
            pass
    return seen.get("request")


def challenge_after_a_moment(page, wait_ms: Optional[int] = None) -> Optional[str]:
    """A security challenge on a purchase history that never asked for its
    orders, looked for several times over a little while rather than once.
    None when there is still none when the time is up."""
    wait_ms = CHALLENGE_WAIT_MS if wait_ms is None else wait_ms
    deadline = time.monotonic() + wait_ms / 1000.0
    while True:
        found = detect_security_challenge(page)
        if found or time.monotonic() >= deadline:
            return found
        try:
            page.wait_for_timeout(500)
        except Exception:
            return found


_FETCH_HISTORY_JS = r"""
async ([url, body]) => {
  const r = await fetch(url, {method: 'POST', credentials: 'include',
    headers: {'content-type': 'application/json', 'accept': 'application/json'},
    body: JSON.stringify(body)});
  let data = null;
  try { data = await r.json(); } catch (e) {}
  return {status: r.status, data};
}
"""


# When the page's own request names no page size.
PAGE_SIZE = 20
# The most orders one reading asks for, two years of a busy account's.
MAX_ORDERS = 1000


def page_size_of(base: dict) -> int:
    """The page size the page's own request asks for, or PAGE_SIZE."""
    size = (base or {}).get("pageSize")
    if isinstance(size, int) and not isinstance(size, bool) and 0 < size <= 200:
        return size
    return PAGE_SIZE


def fetch_orders(page, request: dict, page_size: Optional[int] = None,
                 max_pages: Optional[int] = None) -> dict:
    """Every order the history request reaches, a page at a time, with the
    page's own date range and page size. Returns {"orders": [...], "count":
    n, "status": s, "pages": n, "last": bool, "stop": word}.

    Pages are asked for at the page's own size, which is the one Home Depot
    is seen answering, and by number until the count Home Depot gave is
    reached. Twenty were asked for whatever the page asks, and a page with
    fewer than twenty was taken for the last, so wherever Home Depot gives
    no more than its own page size, every order past the first page was
    missed while the run finished clean. A page that brings nothing new, an
    empty one or one already read, is the end too, so a count larger than
    what comes is not asked after page by page. Without a count, a page
    shorter than the size asked for is the last.

    "last" is what shows the history was read whole. "pages" counts the
    pages that answered with the history, so 0 is a history that did not
    come and never an empty one, which comes as one page with nothing on
    it. "stop" says why it ended short of its last page, "refused" for an
    HTTP error ("status" says which), "no answer" when the call itself
    failed and "no list" for an answer that was not JSON, or that carried
    errors and no order history, and is empty when it did not."""
    if not request or not history_request_ok(request.get("url") or ""):
        return {"orders": [], "count": 0, "status": "no history request", "pages": 0,
                "last": False, "stop": "no request"}
    base = dict(request["body"]["orderHistoryRequest"])
    size = page_size or page_size_of(base)
    max_pages = max_pages or -(-MAX_ORDERS // size)
    orders, count, status, pages, last, stop, seen = [], None, "", 0, False, "", set()
    for n in range(1, max_pages + 1):
        body = {"orderHistoryRequest": dict(base, pageSize=size, pageNumber=n)}
        try:
            got = page.evaluate(_FETCH_HISTORY_JS, [request["url"], body]) or {}
        except Exception as e:
            status, stop = "fetch failed: %s" % type(e).__name__, "no answer"
            break
        status = got.get("status")
        # Only an answer that says it succeeded is believed.
        if status != 200:
            stop = "refused"
            break
        data = got.get("data")
        if not isinstance(data, dict) or ("orders" not in data and "orderCount" not in data
                                          and data.get("errors")):
            # A page where the answer should be, or an answer carrying errors
            # and no order history. Read as an empty page, either ended the
            # history as though there were nothing more in it. An answer
            # without the history and without errors is still read as an
            # empty page, since what an account with no orders is answered
            # was never seen.
            stop = "no list"
            break
        pages += 1
        batch = [o for o in (data.get("orders") or []) if isinstance(o, dict)]
        if count is None and isinstance(data.get("orderCount"), int):
            count = data["orderCount"]
        fresh = []
        for o in batch:
            key = json.dumps(o, sort_keys=True, default=str)
            if key not in seen:
                seen.add(key)
                fresh.append(o)
        orders += fresh
        if not fresh or (count is not None and len(orders) >= count) \
                or (count is None and len(batch) < size):
            last = True
            break
    else:
        # As many pages as are read. Taken as the end, as it always was.
        last = True
    if last and count is not None and len(orders) < count:
        log.info("Home Depot counted %d order(s) and %d came", count, len(orders))
    return {"orders": orders, "count": count if count is not None else len(orders),
            "status": status, "pages": pages, "last": last, "stop": stop}


def why_it_stopped(hist: dict) -> str:
    """Why the history request ended short of its last page, in words for a
    message. Its status, never anything from its body."""
    stop = hist.get("stop")
    if stop == "refused":
        return "Home Depot answered HTTP %s" % hist.get("status")
    if stop == "no list":
        return "Home Depot's answer held no order list"
    if stop == "no request":
        return "the page's own request for its orders could not be asked again"
    return "no answer came back from Home Depot"


def details_url(number: str, sales_date: str, origin: str = "online") -> str:
    return "%s?orderNumber=%s&salesDate=%s&orderOrigin=%s" % (
        DETAILS_URL, quote(number, safe=""), quote(sales_date or "", safe=":"), quote(origin or "online", safe=""))


def order_to_purchase(order: dict) -> Optional[Purchase]:
    """A Purchase from one order in the history answer."""
    numbers = [str(x) for x in (order.get("orderNumbers") or []) if x]
    number = numbers[0].strip().upper() if numbers else ""
    if not ORDER_NUMBER_RE.match(number):
        return None
    sales = str(order.get("salesDate") or "")
    date = _checked_date(sales[:10], None) if re.match(r"\d{4}-\d{2}-\d{2}", sales) else None
    origin = str(order.get("orderOrigin") or "online").lower()
    total = order.get("totalAmount")
    url = details_url(number, sales, origin)
    return Purchase(
        purchase_type=ONLINE if origin == "online" else IN_STORE,
        purchase_date=date or "",
        order_number=number,
        total=("$%.2f" % total) if isinstance(total, (int, float)) else "",
        status="",
        store_info="Home Depot",
        details_url=url,
        receipt_url=url,
        discovered_at=now_iso(),
    )


def history_survey(page, request: Optional[dict] = None) -> dict:
    """What the history page and its request hold. Counts and shapes."""
    out = {"url": redact(page.url or ""), "history_request_seen": bool(request)}
    try:
        out["order_links_on_page"] = page.locator(FALLBACK["order_link"]).count()
    except Exception:
        out["order_links_on_page"] = None
    if request:
        body = request["body"].get("orderHistoryRequest") or {}
        out["request_keys"] = sorted(body.keys())
        got = fetch_orders(page, request)
        out["answer_status"] = got["status"]
        out["orders"] = len(got["orders"])
        out["order_count"] = got["count"]
        kinds = {}
        for o in got["orders"]:
            k = "%s/%s" % (o.get("orderOrigin"), o.get("type"))
            kinds[k] = kinds.get(k, 0) + 1
        out["origins"] = kinds
    return out


# ---------------------------------------------------------------------------
# The details page and its print-only receipt
# ---------------------------------------------------------------------------

_BLOCK_JS = r"""() => {
  const el = [...document.querySelectorAll("div[class*='print:sui-block']")]
    .find(e => /Order Number:/.test(e.textContent || ''));
  return el ? (el.innerText || el.textContent || '') : '';
}"""


def on_details_page(page) -> bool:
    return "/myaccount/order-details" in (page.url or "")


def wait_for_details(page, timeout_ms: int = 30000) -> bool:
    try:
        page.wait_for_function(
            "() => [...document.querySelectorAll(\"div[class*='print:sui-block']\")]"
            ".some(e => /Order Number:/.test(e.textContent || ''))", timeout=timeout_ms)
        page.wait_for_timeout(1000)
        return True
    except Exception:
        log.warning("The receipt did not appear on the details page within %dms", timeout_ms)
        return False


def goto_details(page, purchase: Purchase) -> None:
    """Open the details page, from the stored address when it is Home
    Depot's details page, else rebuilt from the order number."""
    url = purchase.details_url if is_safe_url(purchase.details_url or "") else ""
    if not url or "/myaccount/order-details" not in url:
        if not ORDER_NUMBER_RE.match(purchase.order_number or ""):
            raise ValueError("no order number to open")
        url = details_url(purchase.order_number, purchase.purchase_date or "",
                          "online" if purchase.purchase_type == ONLINE else "store")
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    wait_for_details(page)


def receipt_text(page, print_media: bool = True) -> str:
    """The print-only receipt's text, laid out as it prints."""
    try:
        if print_media:
            page.emulate_media(media="print")
        return page.evaluate(_BLOCK_JS) or ""
    except Exception:
        return ""
    finally:
        if print_media:
            try:
                page.emulate_media(media="screen")
            except Exception:
                pass


def receipt_is_present(page) -> bool:
    text = receipt_text(page)
    return bool(re.search(r"Order Number:", text) and re.search(r"Order Total", text))


def details_number(page) -> str:
    m = re.search(r"Order Number:\s*([A-Z0-9]{6,20})\b", receipt_text(page))
    return m.group(1) if m else ""


def extract_items(text: str) -> List[Item]:
    """Each item is its name, its quantity, its price, then "Model #..." and
    "Store SKU #...". Read backward from each Model line."""
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    items: List[Item] = []
    for i, ln in enumerate(lines):
        if not ln.startswith("Model #") or i < 3:
            continue
        price, qty = lines[i - 1], lines[i - 2]
        if not MONEY_RE.fullmatch(price.replace(" ", "")) or not re.fullmatch(r"\d{1,4}", qty):
            continue
        name_lines = []
        for back in range(i - 3, -1, -1):
            prev = lines[back]
            if prev in ("Price", "Qty", "Item") or prev.startswith("Store SKU #"):
                break
            name_lines.insert(0, prev)
        if not name_lines:
            continue
        items.append(Item(name=" ".join(name_lines)[:300], quantity=qty, line_total=price))
    return items


def extract_details(page, purchase: Purchase) -> Purchase:
    """Date, total, status and items off the receipt block."""
    text = receipt_text(page)
    m = re.search(r"Date Ordered:\s*(.+)", text)
    date = parse_date(m.group(1)) if m else None
    if date:
        purchase.purchase_date = date
    m = re.search(r"Order Total:\s*(\$[\d,]+\.\d{2})", text)
    if m:
        purchase.total = m.group(1)
    # "Delivery" is both how an order came and a line of its payment, so a
    # canceled order is the one whose receipt says so and bills nothing.
    if re.search(r"^Canceled Items$", text, re.M) and purchase.total in ("$0.00", ""):
        purchase.status = "Canceled"
    elif re.search(r"^(Return Completed|Refund Total)$", text, re.M):
        # A returned order keeps its receipt, which now carries the refund.
        purchase.status = "Returned"
    m = re.search(r"^Order Total:.*\n+\s*(Delivery|Pick Up|Ship to Home|Ship to Store|Canceled Items)\s*$",
                  text, re.M)
    if m and m.group(1) != "Canceled Items":
        purchase.fulfillment = m.group(1)
    items = extract_items(text)
    if items:
        purchase.items = items
    purchase.receipt_url = page.url
    return purchase


def scroll_full_page(page, rounds: int = 2, delay_ms: int = 400) -> None:
    try:
        for _ in range(rounds):
            page.mouse.wheel(0, 2500)
            page.wait_for_timeout(delay_ms)
        page.evaluate("() => window.scrollTo(0, 0)")
    except Exception:
        pass


# Under print media the receipt block shows. Everything outside its ancestor
# path is hidden, a display change in the local page only.
_ISOLATE_RECEIPT_JS = r"""() => {
  const el = [...document.querySelectorAll("div[class*='print:sui-block']")]
    .find(e => /Order Number:/.test(e.textContent || ''));
  if (!el || !el.getClientRects().length) return false;
  let node = el;
  while (node && node.parentElement && node !== document.body) {
    for (const s of Array.from(node.parentElement.children)) {
      if (s !== node) s.style.setProperty('display', 'none', 'important');
    }
    node = node.parentElement;
  }
  window.scrollTo(0, 0);
  return true;
}"""


def isolate_receipt(page) -> bool:
    """Switch to print media and leave only the receipt. The caller prints
    and then puts the page back to screen media."""
    try:
        page.emulate_media(media="print")
        ok = bool(page.evaluate(_ISOLATE_RECEIPT_JS))
    except Exception as e:
        log.warning("Receipt isolation failed: %s", e)
        return False
    if not ok:
        log.warning("Could not find the receipt block to isolate")
    return ok


def restore_screen(page) -> None:
    try:
        page.emulate_media(media="screen")
    except Exception:
        pass


def open_receipt_section(page) -> bool:
    return receipt_is_present(page)


def find_print_receipt_controls(page) -> list:
    """View Receipt only calls window.print() and is never pressed."""
    return []


def find_invoice_controls(page) -> list:
    return []


def find_printing_frame(page, wait_ms: int = 2000):
    return None


def find_receipt_iframe(page):
    return None


# ---------------------------------------------------------------------------
# Host allowlist. Parsed, never a string prefix.
# ---------------------------------------------------------------------------
ALLOWED_HOSTS = {"homedepot.com"}


def is_safe_url(url: str) -> bool:
    """True only for an https URL on one of this provider's own hosts.

    The check itself lives in the core, so all of them answer the same way.
    This app keeps the hosts, which is the part that really is its own."""
    return _host_allows(url, ALLOWED_HOSTS)
