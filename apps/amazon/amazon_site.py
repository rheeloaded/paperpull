"""ALL Amazon.com selectors, URL patterns, and page behavior live here.

When Amazon changes its website, repair this file only.

Key advantage over the other merchants: Amazon exposes a dedicated
**printable order summary** at

    https://www.amazon.com/gp/css/summary/print.html?orderID=<ORDER-ID>

which is a clean, self-contained invoice page (order date, order number,
items, quantities, prices, shipping, tax, grand total, payment). Rendering
that page with CDP printToPDF gives a proper receipt with no site chrome and
without ever touching a print dialog.

Amazon purchases are all treated as "Online" (there is no in-store section).

INITIAL SELECTORS written 2026-07-23 from Amazon's long-stable order-history
markup; run `python amazon_receipts.py --diagnose` after signing in and
repair the FALLBACK entries below against the Diagnostics/ output.
"""
# Site layer verified working against the live site: 2026-08
from __future__ import annotations

import html as _html
import logging
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

from paperpull_core.models import ONLINE, Item, Purchase
from storage import now_iso

log = logging.getLogger("amazon_receipts.site")

# ---------------------------------------------------------------------------
# URLs
# ---------------------------------------------------------------------------

BASE = "https://www.amazon.com"
URLS = {
    "home": f"{BASE}/",
    "orders": f"{BASE}/gp/css/order-history",
    "orders_alt": f"{BASE}/your-orders/orders",
    "account": f"{BASE}/gp/css/homepage.html",
}

LOGIN_URL_MARKERS = ["/ap/signin", "/ap/challenge", "signin", "/ap/mfa",
                     "authportal", "/ap/cvf"]


def orders_url(year: Optional[int] = None, start_index: int = 0) -> str:
    """Order history filtered by year, with pagination offset.
    Amazon shows 10 orders per page."""
    parts = []
    if year:
        parts.append(f"timeFilter=year-{year}")
    if start_index:
        parts.append(f"startIndex={start_index}")
    q = ("?" + "&".join(parts)) if parts else ""
    return f"{URLS['orders']}{q}"


def print_invoice_url(order_id: str) -> str:
    """Amazon's printable order summary (the receipt we save)."""
    return f"{BASE}/gp/css/summary/print.html?orderID={order_id}"


def order_details_url(order_id: str) -> str:
    return f"{BASE}/gp/your-account/order-details?orderID={order_id}"


# Amazon order ids: 111-2223333-4445555 (retail) or D01-... (digital)
ORDER_ID_RE = re.compile(r"\b((?:D)?\d{2,3}-\d{7}-\d{7})\b")
ORDER_ID_IN_URL_RE = re.compile(r"orderID=((?:D)?\d{2,3}-\d{7}-\d{7})", re.I)

# ---------------------------------------------------------------------------
# Accessible names / labels
# ---------------------------------------------------------------------------

TAB_NAME = {
    ONLINE: re.compile(r"^\s*orders\s*$", re.I),
}

LOAD_MORE_RE = re.compile(r"(next|load more|show more|view more)", re.I)
RECEIPT_SECTION_RE = re.compile(r"(invoice|receipt|order\s+summary)", re.I)
PRINT_RECEIPT_RE = re.compile(r"(printable\s+order\s+summary|print\s+invoice|"
                              r"view\s+invoice|invoice)", re.I)
GIFT_RECEIPT_RE = re.compile(r"gift\s+receipt", re.I)
INVOICE_RE = re.compile(r"(view|print|download)?\s*invoice", re.I)
SIGN_IN_RE = re.compile(r"^\s*sign\s*in\s*$", re.I)

# Controls that must NEVER be activated.
FORBIDDEN_CONTROL_RE = re.compile(
    r"(buy\s+it\s+again|buy\s+again|return\s+or\s+replace|return\s+items?|"
    r"cancel\s+(items?|order)|write\s+a\s+(product\s+)?review|leave\s+seller\s+feedback|"
    r"archive\s+order|add\s+to\s+cart|proceed\s+to\s+checkout|place\s+your\s+order|"
    r"track\s+package|problem\s+with\s+order|get\s+product\s+support|"
    r"change\s+(payment|shipping|address)|subscribe|share\s+gift\s+receipt)", re.I)

# Keep these SPECIFIC. Amazon pages are full of product titles, so generic
# words ("puzzle", "robot") would false-positive on a jigsaw puzzle or a toy
# robot and needlessly halt a run. Detection also only scans the page title
# and the top of the body, and is skipped entirely when order cards render.
SECURITY_CHALLENGE_MARKERS = [
    "enter the characters you see", "type the characters you see",
    "solve this puzzle to", "are you a robot", "robot check",
    "sorry, we just need to make sure you're not a robot",
    "authentication required", "two-step verification",
    "enter the one time password", "enter the otp",
]

RATE_LIMIT_MARKERS = [
    "too many requests", "rate limit", "try again later",
    "temporarily blocked", "http error 429", "request was throttled",
]

# ---------------------------------------------------------------------------
# Fallback CSS selectors (repair here after --diagnose)
# ---------------------------------------------------------------------------

FALLBACK = {
    # Amazon has used .order-card / .js-order-card for years; newer pages add
    # [data-component='orderCard'].
    "order_card": ".order-card, .js-order-card, [data-component='orderCard'], "
                  ".a-box-group.order",
    "order_link": "a[href*='orderID=']",
    "invoice_link": "a[href*='summary/print.html'], a[href*='invoice']",
    "item_row": ".yohtmlc-item, .a-fixed-left-grid.item-box, "
                "[data-component='purchasedItems'] .a-fixed-left-grid",
    "item_title": ".yohtmlc-product-title, a[href*='/dp/'], a[href*='/gp/product/']",
    "next_page": ".a-pagination .a-last a, a.s-pagination-next",
    "page_ready": ".order-card, .js-order-card, [data-component='orderCard'], "
                  "#ordersContainer, .your-orders-content",
    # printable summary page
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
    r"\b(delivered|shipped|arriving|cancell?ed|returned|refunded|"
    r"out\s+for\s+delivery|preparing\s+for\s+shipment|not\s+yet\s+shipped|"
    r"return\s+complete)\b", re.I)


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


# ---------------------------------------------------------------------------
# Session / safety
# ---------------------------------------------------------------------------

def looks_signed_out(page) -> bool:
    url = (page.url or "").lower()
    if any(marker in url for marker in LOGIN_URL_MARKERS):
        return True
    try:
        if page.locator("input[type='password']#ap_password, input#ap_email").count() > 0:
            return True
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
    """Detect a real CAPTCHA / OTP wall.

    Deliberately conservative: if the page rendered order cards or a real
    order summary, it is a normal page no matter what words appear in the
    product titles below. Only the title and the TOP of the body are scanned,
    because challenge pages put their message there and carry no content.
    """
    try:
        if page.locator(FALLBACK["order_card"]).count() > 0:
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
    if ORDER_ID_RE.search(body or ""):
        return None  # a real order page, not a challenge
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

def goto_orders(page) -> None:
    page.goto(URLS["orders"], wait_until="domcontentloaded", timeout=60000)
    try:
        page.wait_for_selector(FALLBACK["page_ready"], timeout=30000)
    except Exception:
        log.warning("Order-history content did not appear within 30s")
    page.wait_for_timeout(2000)


def select_history_tab(page, purchase_type: str) -> bool:
    """Amazon has no in-store section; everything is Online."""
    return purchase_type == ONLINE


def goto_year_page(page, year: int, start_index: int = 0) -> bool:
    page.goto(orders_url(year, start_index), wait_until="domcontentloaded", timeout=60000)
    try:
        page.wait_for_selector(FALLBACK["page_ready"], timeout=20000)
    except Exception:
        pass
    page.wait_for_timeout(1500)
    return True


def get_year_options(page) -> List[str]:
    """Years available in the time-filter dropdown."""
    years: List[str] = []
    try:
        for sel in page.locator("select#time-filter, select[name='timeFilter']").all():
            for opt in sel.locator("option").all():
                val = (opt.get_attribute("value") or "")
                m = re.search(r"year-(\d{4})", val)
                if m:
                    years.append(m.group(1))
            if years:
                break
    except Exception:
        pass
    return years


def has_next_page(page) -> bool:
    try:
        loc = page.locator(FALLBACK["next_page"])
        return loc.count() > 0 and loc.first.is_visible()
    except Exception:
        return False


def load_all_cards(page, purchase_type: str = ONLINE,
                   delay_ms: int = 1200, max_rounds: int = 3) -> int:
    """Amazon paginates via startIndex; nothing lazy-loads on a page, so we
    just settle the page and count."""
    for _ in range(2):
        page.mouse.wheel(0, 2500)
        page.wait_for_timeout(delay_ms)
    return _card_count(page, purchase_type)


def _card_count(page, purchase_type: str = ONLINE) -> int:
    try:
        return page.locator(FALLBACK["order_card"]).count()
    except Exception:
        return 0


@dataclass
class RawCard:
    href: str
    text: str
    order_id: str = ""
    kind: str = ONLINE


def collect_cards(page, purchase_type: str = ONLINE) -> List[RawCard]:
    """Collect order cards on the current page."""
    if purchase_type != ONLINE:
        return []
    cards: List[RawCard] = []
    seen = set()
    try:
        containers = page.locator(FALLBACK["order_card"]).all()
    except Exception:
        containers = []
    for c in containers:
        try:
            text = (c.inner_text(timeout=3000) or "").strip()
            order_id = ""
            m = ORDER_ID_RE.search(text)
            if m:
                order_id = m.group(1)
            if not order_id:
                try:
                    href = c.locator(FALLBACK["order_link"]).first.get_attribute(
                        "href", timeout=1500) or ""
                    mm = ORDER_ID_IN_URL_RE.search(href)
                    if mm:
                        order_id = mm.group(1)
                except Exception:
                    pass
            if not order_id or order_id in seen:
                continue
            seen.add(order_id)
            cards.append(RawCard(href=order_details_url(order_id), text=text,
                                 order_id=order_id))
        except Exception:
            continue
    if cards:
        return cards
    # Fallback: scan the whole page for order ids + their surrounding block.
    try:
        body = page.locator("body").inner_text(timeout=8000)
    except Exception:
        body = ""
    for oid in dict.fromkeys(ORDER_ID_RE.findall(body)):
        if oid in seen:
            continue
        seen.add(oid)
        idx = body.find(oid)
        chunk = body[max(0, idx - 400): idx + 400]
        cards.append(RawCard(href=order_details_url(oid), text=chunk, order_id=oid))
    return cards


def card_to_purchase(card: RawCard, purchase_type: str,
                     base_url: str = BASE) -> Optional[Purchase]:
    if not card.order_id:
        return None
    text = card.text or ""
    # "ORDER PLACED" column holds the purchase date; take the first date.
    date = parse_date(text) or ""
    # total: prefer the amount right after a TOTAL label
    total = ""
    m = re.search(r"total[^$]{0,20}(\$[\d,]+\.\d{2})", text, re.I)
    if m:
        total = m.group(1)
    else:
        total = parse_money(text)
    return Purchase(
        purchase_type=ONLINE,
        purchase_date=date,
        order_number=card.order_id,
        total=total,
        status=parse_status(text),
        details_url=order_details_url(card.order_id),
        receipt_url=print_invoice_url(card.order_id),
        discovered_at=now_iso(),
    )


# ---------------------------------------------------------------------------
# Details / printable invoice
# ---------------------------------------------------------------------------

def goto_details(page, purchase: Purchase) -> None:
    """Go straight to the printable order summary: it contains everything we
    need (date, order id, items, quantities, prices, totals) AND is what we
    save as the receipt. Avoids a second page load."""
    page.goto(print_invoice_url(purchase.order_number),
              wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(2500)


# Boilerplate lines that are never product titles. NOTE: must not reject
# genuine Amazon-brand products ("Amazon Basics ...", "Amazon Essentials ..."),
# so only match Amazon.com/order boilerplate, never a bare leading "Amazon".
_NON_ITEM_NAME_RE = re.compile(
    r"^(amazon\.com\b|amazon\s+order\b|amazon\s+visa\b|amazon\s+gift\s+card\b|"
    r"qty\b|\$|-\$|item\(s\)\s+subtotal|item\s+subtotal|subtotal|shipping|tax\b|"
    r"grand\s+total|order\s+total|total\s+before\s+tax|sold\s+by|supplied\s+by|"
    r"condition\b|payment\s+method|billing|shipping\s+address|credit\s+card|"
    r"gift\s+card|estimated|of\s+items?|order\s+placed|items?\s+ordered|"
    r"order\s+summary|ship\s+to|back\s+to\s+top|print$|view\s+related|"
    r"return\s+window|united\s+states|english\b|order\s*#)", re.I)

# Address-ish lines that appear in the Ship-to block.
_ADDRESS_LINE_RE = re.compile(
    r"^(\d+\s+[A-Z0-9 .'-]+|[A-Z][A-Za-z .'-]+,\s*[A-Z]{2}\s*\d{5}(-\d{4})?)$")


def _clean_item_name(name: str) -> str:
    name = _html.unescape(re.sub(r"\s+", " ", name or "")).strip()
    if len(name) < 5 or _NON_ITEM_NAME_RE.search(name):
        return ""
    return name


def extract_details(page, purchase: Purchase) -> Purchase:
    """Extract order data from the printable order summary page."""
    try:
        body = page.locator("body").inner_text(timeout=10000)
    except Exception:
        body = ""

    # Order id
    m = ORDER_ID_RE.search(body)
    if m and not purchase.order_number:
        purchase.order_number = m.group(1)

    # "Order Placed: January 5, 2025"
    placed = None
    for line in body.splitlines():
        if re.search(r"order\s+placed", line, re.I):
            placed = parse_date(line)
            if placed:
                break
    date = placed or parse_date(body)
    if date:
        purchase.purchase_date = date

    # Grand Total. NOTE: when a gift card covers the order, Amazon's invoice
    # shows "Grand Total: $0.00" — keep the order-history total in that case
    # so the receipt index still reflects what the order was worth.
    total = ""
    for label in (r"grand\s+total", r"order\s+total"):
        mm = re.search(label + r"[^$]{0,40}(\$[\d,]+\.\d{2})", body, re.I)
        if mm:
            total = mm.group(1)
            break
    if not total:
        amounts = MONEY_RE.findall(body)
        if amounts:
            total = "$" + max(amounts, key=lambda a: float(a.replace(",", "")))
    if total:
        is_zero = total.replace("$", "").replace(",", "") in ("0.00", "0")
        if not (is_zero and purchase.total):
            purchase.total = total

    status = parse_status(body)
    if status:
        purchase.status = status
    if re.search(r"order\s+(was\s+)?cancell?ed", body, re.I):
        purchase.status = purchase.status or "Canceled"

    fm = re.search(r"\b(digital order|prime|standard shipping|free shipping|"
                   r"same[- ]day|amazon fresh|whole foods)\b", body, re.I)
    if fm:
        purchase.fulfillment = fm.group(1).title()

    purchase.items = extract_items(page)
    purchase.receipt_url = page.url
    return purchase


def _is_title_line(line: str) -> bool:
    line = (line or "").strip()
    if len(line) < 10 or MONEY_RE.search(line):
        return False
    if _NON_ITEM_NAME_RE.search(line) or _ADDRESS_LINE_RE.match(line):
        return False
    return True


def _parse_items_from_summary_text(body: str) -> List[Item]:
    """Parse item lines from Amazon's printable order summary.

    Two layouts are supported:

    1. Current layout (verified 2026-07) — each item is a title line followed
       by a "Sold by: <seller>" line, then its price(s):

           AXL 10mm Stem, IKEA Office Chair Wheels, ...
           Sold by: AXL Global
           Return window closed on February 2, 2026
           $30.99

    2. Classic layout — "<qty> of: <Product Title>" then the price.
    """
    body = body or ""
    items: List[Item] = []
    seen = set()

    # --- layout 2 (classic) ------------------------------------------------
    for mm in re.finditer(r"(\d+)\s+of:\s*(.+)", body):
        qty, title = mm.group(1), _clean_item_name(mm.group(2))
        if not title or title.lower() in seen:
            continue
        seen.add(title.lower())
        price = parse_money(body[mm.end(): mm.end() + 300])
        items.append(Item(name=title[:300], quantity=qty,
                          unit_price=price, line_total=price))
    if items:
        return items

    # --- layout 1 (current) ------------------------------------------------
    lines = [l.strip() for l in body.splitlines()]
    for i, line in enumerate(lines):
        if not re.match(r"^sold\s+by\s*:", line, re.I):
            continue
        # title = nearest preceding plausible product line
        title = ""
        for j in range(i - 1, max(-1, i - 6), -1):
            if _is_title_line(lines[j]):
                title = _clean_item_name(lines[j])
                if title:
                    break
        if not title or title.lower() in seen:
            continue
        # price = first money value in the following few lines
        price = ""
        qty = ""
        for k in range(i + 1, min(len(lines), i + 7)):
            nxt = lines[k]
            if not price:
                m = MONEY_RE.search(nxt)
                if m and not nxt.startswith("-"):
                    price = f"${m.group(1)}"
            qm = re.match(r"^(?:qty|quantity)\s*:?\s*(\d+)$", nxt, re.I)
            if qm:
                qty = qm.group(1)
        seen.add(title.lower())
        items.append(Item(name=title[:300], quantity=qty or "1",
                          unit_price=price, line_total=price))
    return items


def extract_items(page) -> List[Item]:
    """Item lines on the printable summary: '<qty> of: <title> ... $price'."""
    seen = set()
    try:
        body = page.locator("body").inner_text(timeout=8000)
    except Exception:
        body = ""

    items = _parse_items_from_summary_text(body)
    if items:
        return items
    seen = {i.name.lower() for i in items}

    # Fallback: product links on a details page
    try:
        for link in page.locator(FALLBACK["item_title"]).all():
            name = _clean_item_name(link.inner_text(timeout=1200) or "")
            if not name or name.lower() in seen:
                continue
            seen.add(name.lower())
            items.append(Item(name=name[:300]))
    except Exception:
        pass
    return items


# ---------------------------------------------------------------------------
# Receipt access — the printable summary IS the receipt
# ---------------------------------------------------------------------------

def scroll_full_page(page, rounds: int = 3, delay_ms: int = 600) -> None:
    try:
        for _ in range(rounds):
            page.mouse.wheel(0, 2500)
            page.wait_for_timeout(delay_ms)
    except Exception:
        pass


def receipt_is_present(page) -> bool:
    """True when the current page looks like a real Amazon order summary."""
    try:
        body = page.locator("body").inner_text(timeout=8000)
    except Exception:
        return False
    if ORDER_ID_RE.search(body) and re.search(
            r"(grand\s+total|order\s+total|item\s+subtotal)", body, re.I):
        return True
    return False


def open_receipt_section(page) -> bool:
    scroll_full_page(page)
    return receipt_is_present(page)


def find_print_receipt_controls(page) -> list:
    """Not used for capture (we navigate straight to the print URL) but kept
    for diagnostics."""
    out = []
    for role in ("link", "button"):
        try:
            loc = page.get_by_role(role, name=PRINT_RECEIPT_RE)
            for i in range(loc.count()):
                el = loc.nth(i)
                try:
                    name = el.inner_text(timeout=1000) or ""
                except Exception:
                    name = ""
                if GIFT_RECEIPT_RE.search(name) or FORBIDDEN_CONTROL_RE.search(name):
                    continue
                out.append(el)
        except Exception:
            continue
    return out


def find_invoice_controls(page) -> list:
    return find_print_receipt_controls(page)


def find_printing_frame(page, wait_ms: int = 2000):
    return None


def wait_for_receipt_content(page, timeout_ms: int = 15000) -> str:
    rounds = max(1, timeout_ms // 500)
    for _ in range(rounds):
        if receipt_is_present(page):
            return "order-summary"
        page.wait_for_timeout(500)
    return ""


def count_store_receipts(page) -> int:
    return 1


def trigger_print_receipt(page, control, timeout_ms: int = 15000) -> Tuple[str, object]:
    """Unused for Amazon (capture is via the print URL). Kept for API parity."""
    return "inline", page
