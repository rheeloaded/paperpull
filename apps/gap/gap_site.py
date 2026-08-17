"""ALL Gap.com selectors, URL patterns, and page behavior live here.

When Gap changes its website, repair this file only.

How Gap differs from the other merchants:

* The signed-in account site is **secure-www.gap.com**, not www.gap.com.
  One Gap Inc. login covers Gap, Old Navy, Banana Republic, Athleta and
  Gap Factory, so a single order history holds orders from every brand.
* Order history at ``/my-account/order-history`` **lazy-loads on scroll**:
  the first render shows only a handful of orders and more appear as you
  scroll. There is no year filter and no ``startIndex`` pagination, so one
  fully scrolled page holds the entire (~13 month) history.
* The **order-details page IS the receipt**. It hydrates from a GraphQL
  call a few seconds after load; once "Total cost:" appears it shows the
  purchase summary, payment method, items and delivery information.
* Gap ships **no print stylesheet**, so a plain printToPDF captures the
  whole site (nav, promo banners, footer). ``isolate_receipt`` first hides
  everything outside the receipt block - the purchase header, line items and
  charge summary - so the PDF holds the receipt and nothing else.

Gap purchases are all treated as "Online" (there is no in-store section).

This file is READ-ONLY by design: nothing here clicks an action control.
Capture is pure navigation + printToPDF, so ``FORBIDDEN_CONTROL_RE`` exists
only as a belt-and-braces guard for the diagnostics helpers.

Site layer verified working against the live site: 2026-08
"""
from __future__ import annotations

import html as _html
import logging
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

from models import ONLINE, Item, Purchase
from storage import now_iso

log = logging.getLogger("gap_receipts.site")

# ---------------------------------------------------------------------------
# URLs
# ---------------------------------------------------------------------------

# The signed-in account experience lives on secure-www, NOT www.
BASE = "https://secure-www.gap.com"
URLS = {
    "home": f"{BASE}/my-account/order-history",
    "orders": f"{BASE}/my-account/order-history",
    "account": f"{BASE}/my-account",
}

LOGIN_URL_MARKERS = ["/sign-in", "/signin", "/login", "/my-account/sign",
                     "/authenticate", "loginredirect", "/account/sign-in"]


def orders_url(year: Optional[int] = None, start_index: int = 0) -> str:
    """Gap's order history takes no year/offset parameters - everything lazy
    loads onto one page - so the arguments are accepted and ignored."""
    return URLS["orders"]


def order_details_url(order_id: str) -> str:
    """The order-details page. This is both the details page AND the receipt."""
    return f"{BASE}/my-account/order-details/{order_id}"


def print_invoice_url(order_id: str) -> str:
    """Gap has no separate printable invoice: the order-details page is it."""
    return order_details_url(order_id)


# Gap order ids are short alphanumeric tokens (e.g. "K4M9XQ2") that appear in
# the order-details URL and, on the details page, after "Purchase #:".
ORDER_ID_IN_URL_RE = re.compile(r"order-details/([A-Za-z0-9][A-Za-z0-9_-]{3,23})", re.I)
ORDER_ID_RE = re.compile(r"(?:purchase|order)\s*#\s*:?\s*([A-Za-z0-9-]{4,24})", re.I)

# Brand is not printed on the order card; the card's Narvar tracking link
# carries it in the URL path (narvar.com/gap/..., narvar.com/oldnavy/...).
NARVAR_BRAND_RE = re.compile(r"narvar\.com/([a-z0-9]+)/", re.I)
BRANDS = {
    "gap": "Gap",
    "gapfactory": "Gap Factory",
    "gapcanada": "Gap",
    "oldnavy": "Old Navy",
    "bananarepublic": "Banana Republic",
    "brfactory": "Banana Republic Factory",
    "athleta": "Athleta",
}
DEFAULT_BRAND = "Gap"

# ---------------------------------------------------------------------------
# Accessible names / labels
# ---------------------------------------------------------------------------

TAB_NAME = {
    ONLINE: re.compile(r"^\s*order\s+history\s*$", re.I),
}

LOAD_MORE_RE = re.compile(r"(load more|show more|view more|see more)", re.I)
RECEIPT_SECTION_RE = re.compile(r"(purchase\s+summary|order\s+summary|receipt)", re.I)
PRINT_RECEIPT_RE = re.compile(r"(print\s+receipt|print\s+invoice|view\s+invoice)", re.I)
GIFT_RECEIPT_RE = re.compile(r"gift\s+receipt", re.I)
INVOICE_RE = re.compile(r"(view|print|download)?\s*invoice", re.I)
SIGN_IN_RE = re.compile(r"^\s*sign\s*in\s*$", re.I)

# The block that holds the receipt on a hydrated order-details page.
PURCHASE_SUMMARY_LABEL = "PURCHASE SUMMARY"
HYDRATED_RE = re.compile(r"total\s+cost\s*:", re.I)

# Controls that must NEVER be activated. Nothing in this file clicks a
# control during a normal run; this guard protects the diagnostics helpers.
FORBIDDEN_CONTROL_RE = re.compile(
    r"(buy\s+it\s+again|buy\s+again|shop\s+again|start\s+a\s+return|"
    r"return\s+or\s+exchange|return\s+items?|exchange\s+items?|"
    r"cancel\s+(items?|order)|write\s+a\s+review|rate\s+(this\s+)?(item|product)|"
    r"add\s+to\s+(bag|cart)|checkout|place\s+(your\s+)?order|track\s+(package|order)|"
    r"change\s+(payment|shipping|address)|subscribe|apply\s+now|pay\s+(bill|now)|"
    r"redeem|share\s+gift\s+receipt|delete|remove)", re.I)

# Controls that are safe to read/activate (none are needed, but a repair could
# legitimately reach for one of these).
SAFE_DOC_CONTROL_RE = re.compile(
    r"(print|view\s+(receipt|invoice|details)|order\s+details|"
    r"purchase\s+summary|load\s+more|show\s+more|view\s+more)", re.I)

# Keep these SPECIFIC. Gap pages are full of product titles, so generic
# words would false-positive on a product name and needlessly halt a run.
# Detection also only scans the page title and the top of the body, and is
# skipped entirely when order cards / a hydrated receipt render.
SECURITY_CHALLENGE_MARKERS = [
    "enter the characters you see", "type the characters you see",
    "are you a robot", "robot check", "press and hold",
    "verify you are a human", "verify you are human",
    "checking your browser before accessing",
    "access to this page has been denied",
    "two-step verification", "enter the one time password",
    "enter the one-time password", "enter the otp",
    "enter the verification code",
]

RATE_LIMIT_MARKERS = [
    "too many requests", "rate limit", "try again later",
    "temporarily blocked", "http error 429", "request was throttled",
]

# ---------------------------------------------------------------------------
# Fallback CSS selectors (repair here after --diagnose)
# ---------------------------------------------------------------------------

FALLBACK = {
    # Every order on the history page links to its own details page; that link
    # is the most stable handle on a card.
    "order_link": "a[href*='order-details/']",
    "order_card": "a[href*='order-details/']",
    "page_ready": "a[href*='order-details/'], main, [data-testid*='order']",
    "invoice_link": "a[href*='order-details/']",
    "item_row": "[data-testid*='item'], [class*='lineItem'], [class*='line-item']",
    "item_title": "a[href*='/browse/product.do'], a[href*='/product/'], "
                  "[data-testid*='productName'], [class*='productName']",
    "next_page": "",  # Gap lazy-loads instead of paginating
    "print_page_body": "body",
}

CARD_CONTAINER = {ONLINE: FALLBACK["order_card"]}

DATE_PATTERNS = [
    (re.compile(r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
                r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|"
                r"Dec(?:ember)?)\.?\s+(\d{1,2}),?\s+(\d{4})", re.I), "mdY"),
    (re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b"), "mdy_slash"),
    (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"), "iso"),
]
_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}

MONEY_RE = re.compile(r"\$\s*([\d,]+\.\d{2})")
QTY_RE = re.compile(r"\b(?:qty|quantity)\s*:?\s*(\d+)", re.I)
STATUS_WORDS_RE = re.compile(
    r"\b(delivered|shipped|in\s+transit|out\s+for\s+delivery|arriving|"
    r"ready\s+for\s+pickup|picked\s+up|cancell?ed|returned|refunded|"
    r"processing|preparing|order\s+placed)\b", re.I)


def parse_date(text: str) -> Optional[str]:
    if not text:
        return None
    for pattern, kind in DATE_PATTERNS:
        m = pattern.search(text)
        if not m:
            continue
        try:
            if kind == "mdY":
                month = _MONTHS[m.group(1)[:3].lower()]
                return f"{int(m.group(3)):04d}-{month:02d}-{int(m.group(2)):02d}"
            if kind == "mdy_slash":
                return f"{int(m.group(3)):04d}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
            if kind == "iso":
                return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        except (KeyError, ValueError):
            continue
    return None


def parse_money(text: str) -> str:
    m = MONEY_RE.search(text or "")
    return f"${m.group(1)}" if m else ""


def parse_status(text: str) -> str:
    m = STATUS_WORDS_RE.search(text or "")
    return m.group(1).title() if m else ""


def parse_order_link(href: str):
    m = ORDER_ID_IN_URL_RE.search(href or "")
    if m:
        return ONLINE, m.group(1)
    return None, None


def brand_from_text(text: str) -> str:
    """Best-effort brand for an order, from a Narvar tracking link."""
    m = NARVAR_BRAND_RE.search(text or "")
    if m:
        return BRANDS.get(m.group(1).lower(), m.group(1).title())
    return ""


# ---------------------------------------------------------------------------
# Session / safety
# ---------------------------------------------------------------------------

def looks_signed_out(page) -> bool:
    url = (page.url or "").lower()
    if any(marker in url for marker in LOGIN_URL_MARKERS):
        return True
    try:
        # A real signed-in order page never renders a password box.
        if page.locator("input[type='password']").count() > 0:
            return True
    except Exception:
        pass
    try:
        if page.locator(FALLBACK["order_link"]).count() > 0:
            return False
    except Exception:
        pass
    try:
        h = page.get_by_role("heading", name=SIGN_IN_RE)
        if h.count() > 0 and h.first.is_visible():
            return True
    except Exception:
        pass
    return False


def detect_security_challenge(page) -> Optional[str]:
    """Detect a real bot-wall / OTP page.

    Deliberately conservative: if the page rendered order links or a
    hydrated purchase summary, it is a normal page no matter what words
    appear in the product titles below. Only the title and the TOP of the
    body are scanned, because challenge pages put their message there and
    carry no real content.
    """
    try:
        if page.locator(FALLBACK["order_link"]).count() > 0:
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
    if HYDRATED_RE.search(body or ""):
        return None  # a real, hydrated order page
    hay = title + "\n" + body[:1200]
    for m in SECURITY_CHALLENGE_MARKERS:
        if m in hay:
            return f"Security challenge detected: '{m}'"
    for m in RATE_LIMIT_MARKERS:
        if m in hay:
            return f"Possible rate limiting detected: '{m}'"
    return None


# ---------------------------------------------------------------------------
# Order history navigation
# ---------------------------------------------------------------------------

# Gap's SPA keeps long-poll/analytics requests open forever, so `networkidle`
# never fires. Everything here uses domcontentloaded + explicit waits.
_ORDER_LINK_COUNT_JS = (
    "() => document.querySelectorAll(\"a[href*='order-details/']\").length"
)


def _order_link_count(page) -> int:
    try:
        return int(page.evaluate(_ORDER_LINK_COUNT_JS) or 0)
    except Exception:
        return 0


def scroll_all_orders(page, max_rounds: int = 20, delay_ms: int = 1200,
                      stable_rounds: int = 3) -> int:
    """Scroll the order-history page until it stops adding orders.

    Gap renders ~5 orders and appends more as you scroll. Returns the final
    number of order links found."""
    last = _order_link_count(page)
    stable = 0
    for _ in range(max_rounds):
        try:
            page.mouse.wheel(0, 3000)
        except Exception:
            try:
                page.evaluate("() => window.scrollBy(0, 3000)")
            except Exception:
                break
        page.wait_for_timeout(delay_ms)
        count = _order_link_count(page)
        if count > last:
            last = count
            stable = 0
            continue
        stable += 1
        if stable >= stable_rounds:
            break
    log.info("Order history settled at %d order(s)", last)
    return last


def goto_orders(page) -> None:
    page.goto(URLS["orders"], wait_until="domcontentloaded", timeout=60000)
    try:
        page.wait_for_selector(FALLBACK["order_link"], timeout=30000)
    except Exception:
        log.warning("No order links appeared on the order-history page within 30s")
    page.wait_for_timeout(1500)
    scroll_all_orders(page)


def select_history_tab(page, purchase_type: str) -> bool:
    """Gap has no in-store section; everything is Online."""
    return purchase_type == ONLINE


def goto_year_page(page, year: int, start_index: int = 0) -> bool:
    """Gap has no per-year pages: one scrolled order-history page holds the
    whole available history. The first call loads it; any later call (a
    different year, or a pagination offset) reports 'nothing more here'."""
    if start_index:
        return False
    goto_orders(page)
    return True


def get_year_options(page) -> List[str]:
    """Gap exposes no year filter."""
    return []


def has_next_page(page) -> bool:
    """Gap lazy-loads instead of paginating; goto_orders already scrolled
    everything in."""
    return False


def load_all_cards(page, purchase_type: str = ONLINE,
                   delay_ms: int = 1200, max_rounds: int = 20) -> int:
    return scroll_all_orders(page, max_rounds=max_rounds, delay_ms=delay_ms)


def _card_count(page, purchase_type: str = ONLINE) -> int:
    return _order_link_count(page)


@dataclass
class RawCard:
    href: str
    text: str
    order_id: str = ""
    kind: str = ONLINE
    brand: str = ""


# Collect one record per order card: the id from the details link, plus the
# text of the smallest ancestor that actually reads like a card (so the date
# and any total come along) and the raw hrefs inside it (for the brand).
_COLLECT_CARDS_JS = r"""
() => {
  const out = [];
  const seen = new Set();
  for (const a of document.querySelectorAll("a[href*='order-details/']")) {
    const m = (a.getAttribute('href') || '').match(/order-details\/([A-Za-z0-9][A-Za-z0-9_-]{3,23})/);
    if (!m) continue;
    const id = m[1];
    if (seen.has(id)) continue;
    seen.add(id);
    let best = a, el = a.parentElement;
    while (el && el !== document.body) {
      const t = (el.innerText || '').trim();
      if (t.length > 700) break;
      if (t.length > 25) best = el;
      el = el.parentElement;
    }
    const hrefs = Array.from(best.querySelectorAll('a[href]'))
      .map(l => l.getAttribute('href') || '').join(' ');
    out.push({id: id, text: (best.innerText || '').trim(), hrefs: hrefs});
  }
  return out;
}
"""


def collect_cards(page, purchase_type: str = ONLINE) -> List[RawCard]:
    """Collect every order card currently rendered on the history page."""
    if purchase_type != ONLINE:
        return []
    try:
        raw = page.evaluate(_COLLECT_CARDS_JS) or []
    except Exception as e:
        log.warning("Card collection failed: %s", e)
        raw = []
    cards: List[RawCard] = []
    for r in raw:
        oid = (r.get("id") or "").strip()
        if not oid:
            continue
        text = r.get("text") or ""
        cards.append(RawCard(
            href=order_details_url(oid), text=text, order_id=oid,
            brand=brand_from_text(r.get("hrefs", "")) or brand_from_text(text)))
    return cards


def card_to_purchase(card: RawCard, purchase_type: str,
                     base_url: str = BASE) -> Optional[Purchase]:
    if not card.order_id:
        return None
    text = card.text or ""
    # Prefer a date on an "order placed / purchased" line; the delivery
    # estimates on a card ("Arriving Tue, Aug 20") carry no year, so the
    # year-requiring patterns skip them anyway.
    date = ""
    for line in text.splitlines():
        if re.search(r"(order\s+placed|purchased|ordered\s+on)", line, re.I):
            date = parse_date(line) or ""
            if date:
                break
    if not date:
        date = parse_date(text) or ""
    total = ""
    m = re.search(r"total[^$]{0,20}(\$[\d,]+\.\d{2})", text, re.I)
    total = m.group(1) if m else parse_money(text)
    return Purchase(
        purchase_type=ONLINE,
        purchase_date=date,
        order_number=card.order_id,
        total=total,
        status=parse_status(text),
        store_info=card.brand or DEFAULT_BRAND,
        details_url=order_details_url(card.order_id),
        receipt_url=order_details_url(card.order_id),
        discovered_at=now_iso(),
    )


# ---------------------------------------------------------------------------
# Details page = the receipt
# ---------------------------------------------------------------------------

def wait_for_hydration(page, timeout_ms: int = 45000) -> bool:
    """The order-details page renders its shell immediately and fills in the
    receipt from api.gap.com a few seconds later. Wait for the filled-in
    version ("Total cost:" is the marker)."""
    try:
        page.wait_for_function(
            "() => /Total cost:/i.test(document.body.innerText)",
            timeout=timeout_ms)
        page.wait_for_timeout(800)
        return True
    except Exception:
        log.warning("Order-details page did not hydrate within %dms", timeout_ms)
        return False


def goto_details(page, purchase: Purchase) -> None:
    """Open the order-details page and wait for it to hydrate. That page is
    both where the order data is read AND what gets saved as the receipt."""
    page.goto(order_details_url(purchase.order_number),
              wait_until="domcontentloaded", timeout=60000)
    wait_for_hydration(page)


# Boilerplate lines that are never product titles.
_NON_ITEM_NAME_RE = re.compile(
    r"^(gap\.com\b|gap\s+inc\b|gap\s+good\s+rewards\b|gap\s+card\b|"
    r"purchase\s+summary|purchased\s*:|purchase\s*#|total\s+cost|payment\s*:|"
    r"delivery\b|shipped\b|pickup\b|order\s+placed|track(ing)?\b|"
    r"qty\b|quantity\b|size\b|color\b|colour\b|item\s+total|"
    r"\$|-\$|subtotal|shipping|tax\b|grand\s+total|order\s+total|"
    r"estimated|ship\s+to|shipping\s+address|billing|payment\s+method|"
    r"credit\s+card|gift\s+card|return|exchange|need\s+help|contact\s+us|"
    r"back\s+to\s+top|view\s+details|print$|english\b|united\s+states)", re.I)

# Address-ish lines that appear in the ship-to block.
_ADDRESS_LINE_RE = re.compile(
    r"^(\d+\s+[A-Z0-9 .'-]+|[A-Z][A-Za-z .'-]+,\s*[A-Z]{2}\s*\d{5}(-\d{4})?)$")


def _clean_item_name(name: str) -> str:
    name = _html.unescape(re.sub(r"\s+", " ", name or "")).strip()
    if len(name) < 5 or _NON_ITEM_NAME_RE.search(name):
        return ""
    return name


def _value_after_label(lines: List[str], index: int, look_ahead: int = 2) -> str:
    """Gap puts each summary label on its own line and the value on the next
    one ("Purchased:" / "June 24, 2026 (10:06PM EDT)"), so read forward."""
    for k in range(index, min(len(lines), index + look_ahead + 1)):
        if k > index and lines[k]:
            return lines[k]
    return ""


def extract_details(page, purchase: Purchase) -> Purchase:
    """Read the hydrated order-details page.

    A hydrated page reads roughly (label and value on SEPARATE lines):

        PURCHASE SUMMARY
        Purchased:
        June 24, 2026 (10:06PM EDT)
        Purchase #:
        K4M9XQ2
        Total cost:
        $53.51 (4 items)
        Payment:
        Apple Pay
        DELIVERY
        ...items...
        SUMMARY OF CHARGES
        ...subtotal / savings / shipping / tax / total...
    """
    try:
        body = page.locator("body").inner_text(timeout=10000)
    except Exception:
        body = ""

    m = ORDER_ID_RE.search(body)
    if m and not purchase.order_number:
        purchase.order_number = m.group(1)

    # "Purchased:" followed by "June 24, 2026 (10:06PM EDT)" on the next line.
    lines = [l.strip() for l in body.splitlines()]
    placed = None
    for i, line in enumerate(lines):
        if re.search(r"^(purchased|order\s+placed)\b", line, re.I):
            placed = parse_date(line) or parse_date(_value_after_label(lines, i))
            if placed:
                break
    date = placed or parse_date(body)
    if date:
        purchase.purchase_date = date

    # "Total cost: $84.31 (4 items)"
    total = ""
    for label in (r"total\s+cost", r"order\s+total", r"grand\s+total"):
        mm = re.search(label + r"[^$]{0,40}(\$[\d,]+\.\d{2})", body, re.I)
        if mm:
            total = mm.group(1)
            break
    if total:
        # A gift-card-covered order can show $0.00; keep the history total then.
        is_zero = total.replace("$", "").replace(",", "") in ("0.00", "0")
        if not (is_zero and purchase.total):
            purchase.total = total

    status = parse_status(body)
    if status:
        purchase.status = status
    if re.search(r"order\s+(was\s+)?cancell?ed|purchase\s+cancell?ed", body, re.I):
        purchase.status = "Canceled"

    fm = re.search(r"\b(free\s+shipping|standard\s+shipping|express\s+shipping|"
                   r"rush\s+shipping|store\s+pickup|curbside\s+pickup|"
                   r"pick\s+up\s+in\s+store|delivery)\b", body, re.I)
    if fm:
        purchase.fulfillment = fm.group(1).title()

    brand = brand_from_text(body)
    if brand:
        purchase.store_info = brand
    elif not purchase.store_info:
        purchase.store_info = DEFAULT_BRAND

    purchase.items = extract_items(page)
    purchase.receipt_url = page.url
    return purchase


def _is_title_line(line: str) -> bool:
    line = (line or "").strip()
    if len(line) < 8 or MONEY_RE.search(line):
        return False
    if _NON_ITEM_NAME_RE.search(line) or _ADDRESS_LINE_RE.match(line):
        return False
    if re.match(r"^(qty|quantity|size|color|colour)\b", line, re.I):
        return False
    return True


# An item's "size | color" attribute row - the one reliably-shaped line in an
# item block, and the anchor the parser hangs everything else off.
_ATTR_LINE_RE = re.compile(r"^[^|$\n]{1,60}\|[^|$\n]{1,60}$")
# A trailing "(2)" on a product title is the quantity ("... (3-Pack) (2)").
_QTY_SUFFIX_RE = re.compile(r"\s*\((\d{1,3})\)\s*$")
# All-caps section headers (DELIVERY, SUMMARY OF CHARGES) end an item block.
_SECTION_HEADER_RE = re.compile(r"^[A-Z][A-Z &'/-]{4,}$")


def _parse_items_from_summary_text(body: str) -> List[Item]:
    """Parse item lines out of a hydrated Gap order-details page.

    Each item block reads:

        Short-Sleeve Rashguard Swim Top for Boys      <- title
        XL | Chrysolite                               <- size | color
        Promo: PWP - Single Points - US               <- optional
        $22.99                                        <- original price
        $11.05                                        <- price paid
        Savings $11.50                                <- optional

    So the parser anchors on the "size | color" row, takes the product title
    from the line above it, and reads the price paid (the SECOND money value,
    when the item was discounted) from the lines below. A quantity above one
    shows up as a trailing "(2)" on the title, with the price marked "each".
    """
    body = body or ""
    items: List[Item] = []
    seen = set()
    lines = [l.strip() for l in body.splitlines()]

    for i, line in enumerate(lines):
        if not _ATTR_LINE_RE.match(line):
            continue
        raw_title = ""
        for j in range(i - 1, max(-1, i - 4), -1):
            if _is_title_line(lines[j]):
                raw_title = lines[j]
                break
        if not raw_title:
            continue
        qty = "1"
        qm = _QTY_SUFFIX_RE.search(raw_title)
        if qm:
            qty = qm.group(1)
            raw_title = _QTY_SUFFIX_RE.sub("", raw_title)
        title = _clean_item_name(raw_title)
        if not title or title.lower() in seen:
            continue

        prices: List[str] = []
        for k in range(i + 1, min(len(lines), i + 9)):
            nxt = lines[k]
            if _ATTR_LINE_RE.match(nxt) or _SECTION_HEADER_RE.match(nxt):
                break
            if re.match(r"^savings\b", nxt, re.I):
                continue  # a discount amount, not a price
            mm = MONEY_RE.search(nxt)
            if mm and not nxt.startswith("-"):
                prices.append(f"${mm.group(1)}")
                if len(prices) >= 2:
                    break
                continue
            if prices and _is_title_line(nxt):
                break  # ran into the next item
        # Discounted items list the original price first, the price paid
        # second; undiscounted items list one price.
        unit = prices[1] if len(prices) > 1 else (prices[0] if prices else "")
        seen.add(title.lower())
        items.append(Item(name=title[:300], quantity=qty, unit_price=unit,
                          line_total=unit if qty == "1" else ""))
    return items


def extract_items(page) -> List[Item]:
    """Line items on the hydrated order-details page."""
    try:
        body = page.locator("body").inner_text(timeout=8000)
    except Exception:
        body = ""

    items = _parse_items_from_summary_text(body)
    if items:
        return items

    # Fallback: product links / titles in the DOM.
    seen = set()
    try:
        for link in page.locator(FALLBACK["item_title"]).all():
            name = _clean_item_name(link.inner_text(timeout=1200) or "")
            if not name or name.lower() in seen:
                continue
            seen.add(name.lower())
            items.append(Item(name=name[:300], quantity="1"))
    except Exception:
        pass
    return items


# ---------------------------------------------------------------------------
# Receipt access - the hydrated details page IS the receipt
# ---------------------------------------------------------------------------

def scroll_full_page(page, rounds: int = 3, delay_ms: int = 500) -> None:
    try:
        for _ in range(rounds):
            page.mouse.wheel(0, 2500)
            page.wait_for_timeout(delay_ms)
        page.evaluate("() => window.scrollTo(0, 0)")
        page.wait_for_timeout(300)
    except Exception:
        pass


def receipt_is_present(page) -> bool:
    """True when the current page is a hydrated Gap order-details receipt."""
    try:
        body = page.locator("body").inner_text(timeout=8000)
    except Exception:
        return False
    if not body:
        return False
    if HYDRATED_RE.search(body) and re.search(r"purchase\s*#", body, re.I):
        return True
    return bool(HYDRATED_RE.search(body)
                and PURCHASE_SUMMARY_LABEL.lower() in body.lower())


# Gap ships no print stylesheet, so printToPDF would otherwise capture the
# entire site (nav, promo banners, footer). Find the receipt block and hide
# everything that is not on its ancestor path, leaving a clean one-page
# receipt. Display changes are made in the live DOM only; nothing is
# submitted and the next navigation discards them.
#
# The block to keep is the SMALLEST element holding both "PURCHASE SUMMARY"
# and "SUMMARY OF CHARGES" - i.e. the whole receipt, from the purchase
# header through the line items to the charge breakdown. Anchoring on
# "PURCHASE SUMMARY" alone finds only the header block and silently drops
# the items and totals from the PDF.
_ISOLATE_RECEIPT_JS = r"""
() => {
  const MARK = 'PURCHASE SUMMARY';
  const smallest = (test) => {
    let best = null, bestLen = Infinity;
    for (const el of document.querySelectorAll('div,section,main,article')) {
      const t = el.innerText || '';
      if (t.length < bestLen && test(t)) { best = el; bestLen = t.length; }
    }
    return best;
  };
  let n = smallest(t => t.includes(MARK) && t.includes('SUMMARY OF CHARGES'));
  if (!n) n = smallest(t => t.includes(MARK) && /Total cost:/i.test(t));
  if (!n) n = smallest(t => t.trim().startsWith(MARK));
  if (!n) return false;
  let el = n;
  while (el && el.parentElement && el !== document.body) {
    for (const s of Array.from(el.parentElement.children)) {
      if (s !== el) s.style.display = 'none';
    }
    el = el.parentElement;
  }
  return true;
}
"""


def isolate_receipt(page) -> bool:
    """Strip the site chrome so printToPDF renders only the receipt.

    Returns True when the purchase-summary block was found and isolated.
    A False result is not fatal: the capture still runs, it just includes
    the surrounding page."""
    try:
        ok = bool(page.evaluate(_ISOLATE_RECEIPT_JS))
    except Exception as e:
        log.warning("Receipt isolation failed: %s", e)
        return False
    if ok:
        page.wait_for_timeout(300)
    else:
        log.warning("Could not find the PURCHASE SUMMARY block to isolate")
    return ok


def open_receipt_section(page) -> bool:
    """Nothing to expand on Gap: the receipt is the page. Just confirm it
    rendered."""
    if not receipt_is_present(page):
        wait_for_hydration(page, timeout_ms=15000)
    return receipt_is_present(page)


def wait_for_receipt_content(page, timeout_ms: int = 15000) -> str:
    rounds = max(1, timeout_ms // 500)
    for _ in range(rounds):
        if receipt_is_present(page):
            return "order-details"
        page.wait_for_timeout(500)
    return ""


def count_store_receipts(page) -> int:
    return 1


# --- receipt-access hooks Gap does not need --------------------------------
# The orchestrator calls these when a merchant hides its receipt behind a
# button, a print popup or an iframe. Gap does none of that (navigate ->
# wait for the page's data -> printToPDF), so they intentionally report
# "nothing here" rather than being deleted: they are where a future repair
# would hook in if Gap ever moves the receipt behind a control.

def find_print_receipt_controls(page) -> list:
    """Gap has no print-receipt control; capture is pure navigation."""
    return []


def find_invoice_controls(page) -> list:
    """Gap has no separate invoice document."""
    return []


def find_printing_frame(page, wait_ms: int = 2000):
    """Gap never renders the receipt into a print iframe."""
    return None


def find_receipt_iframe(page):
    """Gap never renders the receipt into an iframe."""
    return None


def trigger_print_receipt(page, control, timeout_ms: int = 15000) -> Tuple[str, object]:
    """Unused for Gap (capture is inline on the details page). Kept for API
    parity with the other site layers."""
    return "inline", page
