"""ALL bestbuy.com addresses, selectors and page behavior live here.

When Best Buy changes its website, repair this file only.

How Best Buy works, mapped against a signed-in account on 2026-09-25:

* The purchase history is ``https://www.bestbuy.com/purchasehistory/purchases``.
  It shows a few purchases and draws only the ones on screen, a list that
  changes as it scrolls, and it opens on "Past 3 Years", which showed three
  purchases of the twenty nine the account holds. So it is not read from
  the page. What it draws from is one GraphQL request per year,
  ``consolidatedQuery`` at ``/gateway/graphql``, with ``year``,
  ``orderOffset``, ``purchaseOffset``, ``orderLimit`` and ``purchaseLimit``.
  One year is chosen in the range menu (test id ``YearDate-Filter-TestID``)
  so the page makes that request, and it is kept and asked again from inside
  the page for each year back from this one, until three years in a row are
  empty. It reached 2020, a year the menu does not even offer. A page size
  of ten is answered and twenty is refused, so it pages by ten, online
  orders and store purchases each with its own offset.
* Each entry has ``id``, ``orderType`` ("online" or "store"), ``created``,
  ``orderTotal`` (negative for a return) and ``orderStatusTitle``. An online
  order is ``BBY01-807187119385``, an order placed in a store
  ``1122359250430``, and a store purchase ``273 1 2546 122222``, which is
  the store, register, transaction and date.
* The details address is built from the label and the number, so the
  button is never pressed. Online and store orders are
  ``/profile/ss/orders/order-details/<number>/view``. A store purchase is
  ``/purchasehistory/purchase-details?purchaseKey=<number>``.
* The details page is the receipt, the date, the order number, the payment,
  the total, sales tax and each item with its model, SKU and quantity. Its
  "Print Receipt" or "View Receipt" is never pressed, one calls
  window.print and the other only spins. The smallest visible block that
  holds the number, a total and a SKU is kept and printed.
* A feedback survey ("confirmIt") can cover the page and take the clicks.
  It is hidden, a display change in the local page, and never answered.

SAFETY (this is a shopping account with a card on file):
  This module is strictly READ-ONLY. Nothing is clicked but the range menu
  and a year in it. FORBIDDEN_CONTROL_RE refuses Buy Again, returns,
  cancellations, reviews, credit card and payment controls.

Site layer verified working against the live site: 2026-09-25
"""
from __future__ import annotations

import html as _html
import json
import logging
import re
from typing import List, Optional
from urllib.parse import quote, urlsplit

# Everything on its way into a diagnostic file goes through here.
from paperpull_core.redact import redact, set_private_words  # noqa: F401

from paperpull_core.models import IN_STORE, ONLINE, Item, Purchase
from paperpull_core.urls import is_safe_url as _host_allows
from paperpull_core.dates import checked as _checked_date
from storage import now_iso

log = logging.getLogger("bestbuy_receipts.site")

BASE = "https://www.bestbuy.com"
ORDERS_URL = f"{BASE}/purchasehistory/purchases"
URLS = {
    "home": ORDERS_URL,
    "orders": ORDERS_URL,
    "account": f"{BASE}/customer/myaccount",
}

LOGIN_URL_MARKERS = ["/identity/signin", "/identity/global/signin", "/signin", "/sign-in",
                     "/login", "/identity/verify", "/mfa"]

YEAR_MENU = "[data-testid^='YearDate-Filter-TestID']"
DETAILS_BUTTON = "View order details"

FORBIDDEN_CONTROL_RE = re.compile(
    r"(buy\s+(it\s+)?again|add\s+to\s+cart|checkout|reorder|subscribe|"
    r"start\s+a\s+return|\breturn\b|cancel|write\s+a\s+review|\breview\b|"
    r"protection\s+plan|trade.in|credit\s+card|pay\s+(your|now|bill)|\bpay\b|payment|"
    r"apply\s+now|print\s+receipt|view\s+receipt|survey|feedback|chat|"
    r"delete|remove|sign\s+out|log\s+out)", re.I)

try:
    from paperpull_core.controls import SETTINGS_CONTROL_RE as _SHARED_SETTINGS
    FORBIDDEN_CONTROL_RE = re.compile(
        "(?:%s)|(?:%s)" % (FORBIDDEN_CONTROL_RE.pattern, _SHARED_SETTINGS.pattern),
        re.I)
except Exception:  # the shared core is optional at import time
    pass

SAFE_DOC_CONTROL_RE = re.compile(r"(view\s+order\s+details|purchases|past\s+\d+\s+years|^20\d\d$)", re.I)

SECURITY_CHALLENGE_MARKERS = [
    "press and hold", "verify you are a human", "verify you are human",
    "are you a robot", "access denied", "enter the verification code",
    "enter the code we sent", "checking your browser before accessing",
]
RATE_LIMIT_MARKERS = ["too many requests", "rate limit", "temporarily blocked", "http error 429"]

FALLBACK = {
    "year_menu": YEAR_MENU,
    "survey": ".confirmIt, #confirmIt-backdrop",
    "page_ready": YEAR_MENU,
    "print_page_body": "body",
}

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
DATE_RE = re.compile(r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
                     r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|"
                     r"Dec(?:ember)?)\.?\s+(\d{1,2}),?\s+(\d{4})", re.I)
MONEY_LINE_RE = re.compile(r"^-?\$[\d,]+\.\d{2}$")
# A store purchase is store, register, transaction and date, "269 47 6353 111925",
# the last group six digits. Five per group dropped every one of them.
NUMBER_RE = re.compile(r"^(BBY\d{2}-\d{9,15}|\d{9,16}|\d{1,6}(?: \d{1,6}){3})$")


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
        if page.locator(YEAR_MENU).count() > 0:
            return None
        body = page.locator("body").inner_text(timeout=5000)
        if "Order Number:" in body:
            return None
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


def hide_survey(page) -> None:
    """The feedback survey takes the page's clicks when it appears. It is
    hidden in the local page and never answered."""
    try:
        page.evaluate("() => document.querySelectorAll('.confirmIt, #confirmIt-backdrop, [id^=confirmIt]')"
                      ".forEach(e => e.style.setProperty('display', 'none', 'important'))")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# The history, one year at a time
# ---------------------------------------------------------------------------

def goto_orders(page, wait_ms: int = 30000) -> bool:
    """Open the purchase history and wait for its range menu. True when it
    is there."""
    page.goto(ORDERS_URL, wait_until="domcontentloaded", timeout=60000)
    try:
        page.wait_for_selector(YEAR_MENU, timeout=wait_ms)
    except Exception:
        return False
    page.wait_for_timeout(1500)
    hide_survey(page)
    return True


def year_choices(page) -> List[str]:
    """The years the range menu offers, newest first. Opening the menu is
    the only thing done, and it is closed again."""
    hide_survey(page)
    try:
        page.locator(YEAR_MENU).first.click()
        page.wait_for_timeout(1000)
        texts = page.evaluate(
            "() => [...document.querySelectorAll('body *')]"
            ".filter(e => e.children.length === 0 && e.getClientRects().length)"
            ".map(e => (e.innerText || '').trim()).filter(t => /^20\\d\\d$/.test(t))")
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)
    except Exception as e:
        log.warning("Could not read the range menu: %s", e)
        return []
    return sorted(set(texts), reverse=True)


_CARDS_JS = r"""() => {
  const t = document.body.innerText || '';
  return {parts: t.split(/\n\s*View order details\s*(?=\n)/),
          buttons: [...document.querySelectorAll('button')].filter(b => b.getClientRects().length &&
                    /^\s*View order details\s*$/.test(b.innerText || '')).length};
}"""


def _snapshot(page):
    try:
        got = page.evaluate(_CARDS_JS) or {}
    except Exception:
        return None
    return got


def pick_year(page, year: str, reads: int = 3, gap_ms: int = 1200, limit: int = 25) -> bool:
    """Choose one year in the range menu and wait for the list to hold still
    for `reads` looks in a row. A list read mid-redraw once mixed a purchase
    from the year before into it."""
    hide_survey(page)
    try:
        page.locator(YEAR_MENU).first.click()
        page.wait_for_timeout(1000)
        page.get_by_text(year, exact=True).last.click()
    except Exception as e:
        log.warning("Could not choose %s: %s", year, e)
        return False
    last, same = None, 0
    for _ in range(limit):
        page.wait_for_timeout(gap_ms)
        now = _snapshot(page)
        same = same + 1 if (now is not None and now == last) else 0
        last = now
        if same >= reads - 1:
            return True
    log.warning("The %s list did not settle", year)
    return False


def capture_history_query(page, year: str) -> Optional[dict]:
    """Pick one year in the range menu and keep the request the page makes
    for it, the consolidatedQuery, its address, the headers the app itself
    sends and its body. None when the page made none."""
    seen = {}

    def on_request(req):
        if "q" in seen or req.method != "POST" or not is_safe_url(req.url or ""):
            return
        if urlsplit(req.url).path != "/gateway/graphql":
            return
        try:
            body = json.loads(req.post_data or "{}")
        except ValueError:
            return
        if isinstance(body, dict) and body.get("operationName") == "consolidatedQuery" \
                and isinstance(body.get("variables"), dict):
            headers = {k: v for k, v in (req.headers or {}).items()
                       if k.lower() in ("content-type", "accept") or k.lower().startswith("x-")}
            seen["q"] = {"url": req.url, "headers": headers, "body": body}

    page.on("request", on_request)
    try:
        pick_year(page, year)
    finally:
        try:
            page.remove_listener("request", on_request)
        except Exception:
            pass
    return seen.get("q")


_FETCH_JS = r"""async ([url, headers, body]) => {
  const r = await fetch(url, {method: 'POST', credentials: 'include', headers, body: JSON.stringify(body)});
  let data = null;
  try { data = await r.json(); } catch (e) {}
  return {status: r.status, data};
}"""

# Best Buy answers a page size of ten and refuses twenty.
PAGE_SIZE = 10


def fetch_year(page, query: dict, year: int, max_pages: int = 30) -> dict:
    """Every entry the history holds for one year, ten at a time. Online
    orders and store purchases page separately, so each keeps its own
    offset. Returns {"entries": [...], "status": s, "complete": bool}."""
    if not query or not is_safe_url(query.get("url") or ""):
        return {"entries": [], "status": "no query", "complete": False}
    entries, seen = [], set()
    order_offset = purchase_offset = 0
    status, complete = "", False
    for _ in range(max_pages):
        body = json.loads(json.dumps(query["body"]))
        body["variables"].update(year=int(year), orderLimit=PAGE_SIZE, purchaseLimit=PAGE_SIZE,
                                 orderOffset=order_offset, purchaseOffset=purchase_offset)
        # The page can reload under a request, which destroys the context it
        # ran in, so a failed call is waited out and tried again.
        got, error = None, None
        for attempt in range(3):
            try:
                got = page.evaluate(_FETCH_JS, [query["url"], query["headers"], body]) or {}
                break
            except Exception as e:
                error = e
                log.info("History request for %s failed (%s), trying again", year, str(e).splitlines()[0][:120])
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=15000)
                except Exception:
                    pass
                page.wait_for_timeout(2000 * (attempt + 1))
        if got is None:
            status = "fetch failed: %s" % type(error).__name__
            break
        status = got.get("status")
        data = got.get("data") if isinstance(got.get("data"), dict) else {}
        if status != 200 or data.get("errors"):
            status = status if status != 200 else "errors"
            break
        exp = (((data.get("data") or {}).get("customer") or {})
               .get("purchaseHistoryOrdersExperience") or {})
        closed = exp.get("closedOrdersAndTransactions") or {}
        opened = exp.get("openOrders") or {}
        batch = [e for e in (closed.get("entries") or []) + (opened.get("entries") or [])
                 if isinstance(e, dict)]
        fresh = [e for e in batch if str(e.get("id")) not in seen]
        for e in fresh:
            seen.add(str(e.get("id")))
        entries += fresh
        more = bool((closed.get("pageInfo") or {}).get("hasNext") or (opened.get("pageInfo") or {}).get("hasNext"))
        if not more:
            complete = True
            break
        if not fresh:
            break           # asked for more and got nothing new, so stop rather than loop
        order_offset += sum(1 for e in fresh if str(e.get("orderType")).lower() != "store")
        purchase_offset += sum(1 for e in fresh if str(e.get("orderType")).lower() == "store")
        # Paced like a person paging. Best Buy's bot protection reset every
        # request, the page's own included, after a burst of these.
        page.wait_for_timeout(2500)
    return {"entries": entries, "status": status, "complete": complete}


def _entry_date(created: str) -> str:
    """The purchase's date. An online order carries its own offset. A store
    purchase is written in UTC, so an evening purchase reads as the next
    day, and it is moved back to US time. The details page's own date
    replaces this before anything is named."""
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):", created or "")
    if not m:
        return ""
    iso = "%s-%s-%s" % m.group(1, 2, 3)
    if created.endswith("Z") and int(m.group(4)) < 6:
        from datetime import date, timedelta
        iso = (date.fromisoformat(iso) - timedelta(days=1)).isoformat()
    return _checked_date(iso, None) or ""


def is_reference(entry: dict) -> bool:
    """An old online order Best Buy keeps only as a pointer, an id and an
    item count with no date, total or status. Its details page no longer
    exists, it sends you back to the list, so there is no receipt to save."""
    return str(entry.get("orderType") or "").lower() == "reference"


def _store_key_date(number: str) -> str:
    """A store purchase's number ends in its date, "147 41 6953 100815" is
    October 8, 2015. Old ones carry a created time from when Best Buy moved
    its records, years later, so the number is the better witness."""
    m = re.fullmatch(r"\d{1,6} \d{1,6} \d{1,6} (\d{2})(\d{2})(\d{2})", number or "")
    if not m:
        return ""
    return _checked_date("20%s-%s-%s" % (m.group(3), m.group(1), m.group(2)), None) or ""


def entry_to_purchase(entry: dict) -> Optional[Purchase]:
    number = str(entry.get("id") or "").strip()
    if not NUMBER_RE.match(number) or is_reference(entry):
        return None
    kind = str(entry.get("orderType") or "").lower()
    total = entry.get("orderTotal")
    try:
        amount = float(total)
    except (TypeError, ValueError):
        amount = None
    shown = "" if amount is None else ("-$%.2f" % -amount if amount < 0 else "$%.2f" % amount)
    status = str(entry.get("orderStatusTitle") or "").strip()
    url = details_url("in store" if kind == "store" else "online order", number)
    return Purchase(
        purchase_type=IN_STORE if kind == "store" or not number.startswith("BBY") else ONLINE,
        purchase_date=_store_key_date(number) or _entry_date(str(entry.get("created") or "")),
        order_number=number,
        total=shown,
        status=status,
        store_info="Best Buy",
        details_url=url,
        receipt_url=url,
        document_type="Return" if amount is not None and amount < 0 else "Receipt",
        discovered_at=now_iso(),
    )


def details_url(label: str, number: str) -> str:
    if label.lower() == "in store":
        return f"{BASE}/purchasehistory/purchase-details?purchaseKey={quote(number, safe='')}"
    return f"{BASE}/profile/ss/orders/order-details/{quote(number, safe='')}/view"


def history_survey(page, query: Optional[dict] = None, years=()) -> dict:
    """What the history holds, per year, as counts."""
    out = {"url": redact(page.url or ""), "query_seen": bool(query)}
    if query:
        out["variables"] = sorted((query["body"].get("variables") or {}).keys())
        for y in years:
            got = fetch_year(page, query, int(y))
            kinds = {}
            for e in got["entries"]:
                kinds[str(e.get("orderType"))] = kinds.get(str(e.get("orderType")), 0) + 1
            out[str(y)] = {"status": got["status"], "complete": got["complete"],
                           "entries": len(got["entries"]), "types": kinds}
    return out


# ---------------------------------------------------------------------------
# The details page is the receipt
# ---------------------------------------------------------------------------

def on_details_page(page) -> bool:
    url = page.url or ""
    return "/profile/ss/orders/order-details/" in url or "/purchasehistory/purchase-details" in url


_CONTACT_RE = re.compile(r"@|\b[A-Z]{2}\s+\d{5}(?:-\d{4})?\b|^(Ready to Redeem|Digital Delivery|"
                         r"Shipping Address|Delivered on .*|Store Pickup.*)$", re.I)


def _looks_like_contact(line: str) -> bool:
    return bool(_CONTACT_RE.search((line or "").replace("\xa0", " ")))


def wait_for_details(page, timeout_ms: int = 30000, names_ms: int = 10000) -> bool:
    """The order number and SKUs first, then every item's name, which draws
    a moment later. One order was read before its names had drawn and its
    items came out as the shipping address and a delivery email."""
    try:
        page.wait_for_function("() => /Order Number:/.test(document.body.innerText) && /SKU/.test(document.body.innerText)",
                               timeout=timeout_ms)
        page.wait_for_timeout(1500)
        hide_survey(page)
    except Exception:
        log.warning("The details page did not fill in within %dms", timeout_ms)
        return False
    waited = 0
    while waited < names_ms:
        try:
            items = extract_items(page.locator("body").inner_text(timeout=5000))
        except Exception:
            items = []
        if items and all(i.name for i in items):
            break
        page.wait_for_timeout(1000)
        waited += 1000
    else:
        log.warning("Some item names had not drawn after %dms", names_ms)
    return True


def goto_details(page, purchase: Purchase) -> None:
    """Open the details page from the stored address when it is Best Buy's
    own details page, else rebuilt from the number."""
    url = purchase.details_url if is_safe_url(purchase.details_url or "") else ""
    if not url or not ("/profile/ss/orders/order-details/" in url or "/purchasehistory/purchase-details" in url):
        if not NUMBER_RE.match(purchase.order_number or ""):
            raise ValueError("no order number to open")
        url = details_url("in store" if purchase.purchase_type == IN_STORE and " " in purchase.order_number
                          else "online order", purchase.order_number)
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    wait_for_details(page)


def details_number(page) -> str:
    try:
        body = page.locator("body").inner_text(timeout=8000)
    except Exception:
        return ""
    m = re.search(r"Order Number:\s*(BBY\d{2}-\d{9,15}|\d{1,6}(?: \d{1,6}){3}|\d{9,16})", body or "")
    return m.group(1) if m else ""


def receipt_is_present(page) -> bool:
    try:
        body = page.locator("body").inner_text(timeout=8000)
    except Exception:
        return False
    return bool(re.search(r"Order Number:", body) and re.search(r"SKU", body) and re.search(r"Total", body))


_ITEM_LABELS = ("Serial:", "Model:", "SKU:", "Quantity:", "Item Total:", "Product Price:",
                "Sales Tax, Fees & Surcharges:")


def _joined(body: str) -> List[str]:
    """Lines with each label and its value on one line. An order's page puts
    the value on the line after its label, a store purchase's page puts it
    after the colon."""
    lines = [ln.strip() for ln in (body or "").splitlines() if ln.strip()]
    out, i = [], 0
    while i < len(lines):
        if lines[i] in _ITEM_LABELS and i + 1 < len(lines):
            out.append(lines[i] + " " + lines[i + 1])
            i += 2
            continue
        out.append(lines[i])
        i += 1
    return out


def extract_items(body: str) -> List[Item]:
    """Each item is its name, then "Model:", "SKU:", "Quantity:" and "Item
    Total:". The name is the line before Model, passing over a "Serial:"
    line, which the page puts between them for a device."""
    lines = _joined(body)
    items: List[Item] = []
    for i, ln in enumerate(lines):
        if not ln.startswith("Model:") or i == 0:
            continue
        k = i - 1
        while k >= 0 and lines[k].startswith("Serial:"):
            k -= 1
        if k < 0:
            continue
        name = _html.unescape(lines[k])
        if name.startswith(_ITEM_LABELS) or MONEY_LINE_RE.match(name):
            continue
        # Product names draw a moment after the rest, and until they do the
        # line before "Model:" is the shipping address or a delivery email.
        # That is not a name, and an empty one tells the wait to keep going.
        if _looks_like_contact(name):
            name = ""
        item = Item(name=name[:300], quantity="1")
        for nxt in lines[i + 1:i + 8]:
            if nxt.startswith("Model:"):
                break
            m = re.match(r"^Quantity:\s*(\d{1,4})", nxt)
            if m:
                item.quantity = m.group(1)
            m = re.match(r"^Item Total:\s*(-?\$[\d,]+\.\d{2})", nxt)
            if m:
                item.line_total = m.group(1)
            m = re.match(r"^Product Price:\s*(\$[\d,]+\.\d{2})", nxt)
            if m:
                item.unit_price = m.group(1)
        items.append(item)
    return items


def extract_details(page, purchase: Purchase) -> Purchase:
    try:
        body = page.locator("body").inner_text(timeout=10000)
    except Exception:
        body = ""
    m = re.search(r"Purchase Date:\s*([A-Za-z]{3,9}\.?\s+\d{1,2},?\s+\d{4})", body)
    date = parse_date(m.group(1)) if m else None
    if date:
        purchase.purchase_date = date
    m = re.search(r"(?<!Net )(?<!Item )Total:\s*(-?\$[\d,]+\.\d{2})", body)
    if m:
        purchase.total = m.group(1)
    m = re.search(r"Store Location\s*\n\s*([A-Z][A-Z .'-]{2,40})", body)
    if m and purchase.purchase_type == IN_STORE:
        purchase.store_info = "Best Buy " + m.group(1).strip().title()
    if re.search(r"^Canceled$|^Cancelled$|order (was|has been) canceled", body, re.I | re.M) and not re.search(r"SKU", body):
        purchase.status = "Canceled"
    # An item whose name never drew is left out rather than named for the
    # address above it.
    items = [i for i in extract_items(body) if i.name]
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


_ISOLATE_RECEIPT_JS = r"""(num) => {
  const want = (t) => t.includes(num) && /Total/.test(t) && /SKU/.test(t);
  let best = null, bestLen = Infinity;
  for (const el of document.querySelectorAll('main,section,article,div')) {
    const t = el.innerText || '';
    const r = el.getBoundingClientRect();
    if (r.width > 0 && r.height > 0 && t.length < bestLen && want(t)) { best = el; bestLen = t.length; }
  }
  if (!best) return false;
  let el = best;
  while (el && el.parentElement && el !== document.body) {
    for (const s of Array.from(el.parentElement.children)) if (s !== el) s.style.setProperty('display', 'none', 'important');
    el = el.parentElement;
  }
  for (const x of best.querySelectorAll('a,button,[role=button]')) {
    const t = (x.innerText || x.getAttribute('aria-label') || '').trim();
    if (/write a review|get product support|print receipt|view receipt|buy again|view items|learn more|get help|see all purchases/i.test(t)) {
      x.style.setProperty('display', 'none', 'important');
    }
  }
  const w = Math.max(best.scrollWidth, best.getBoundingClientRect().width);
  document.body.style.zoom = String(Math.min(1, Math.max(0.45, 736 / (w + 16))));
  window.scrollTo(0, 0);
  return true;
}"""


def isolate_receipt(page, number: str = "") -> bool:
    """Leave only the receipt block, the smallest visible one holding this
    purchase's number. A display change in the local page."""
    number = number or details_number(page)
    if not number:
        return False
    try:
        ok = bool(page.evaluate(_ISOLATE_RECEIPT_JS, number))
    except Exception as e:
        log.warning("Receipt isolation failed: %s", e)
        return False
    if ok:
        page.wait_for_timeout(300)
    else:
        log.warning("Could not find the receipt block to isolate")
    return ok


def open_receipt_section(page) -> bool:
    return receipt_is_present(page)


def find_print_receipt_controls(page) -> list:
    """Print Receipt calls window.print and View Receipt only spins, so
    neither is pressed."""
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
ALLOWED_HOSTS = {"bestbuy.com"}


def is_safe_url(url: str) -> bool:
    """True only for an https URL on one of this provider's own hosts.

    The check itself lives in the core, so all of them answer the same way.
    This app keeps the hosts, which is the part that really is its own."""
    return _host_allows(url, ALLOWED_HOSTS)
