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
from paperpull_core.urls import is_safe_url as _host_allows
from storage import now_iso

log = logging.getLogger("amazon_receipts.site")

# ---------------------------------------------------------------------------
# URLs
# ---------------------------------------------------------------------------

# Amazon is one company with a separate store per country, and an order
# placed on one store is only on that store. `marketplace` in config.json
# names the store this install reads. The order-history and printable-summary
# paths are the same everywhere. What differs is the currency, the date
# order, and the language of the labels the parser reads. For a store whose
# pages are not in English, every URL asks for English, which Amazon honors
# and remembers in a cookie, so the labels stay the ones the parser knows.
# Each entry: currency symbol, whether dates come day first, and the
# language code to ask for, or None when the store is already English.
MARKETPLACES = {
    "amazon.com":    ("$", False, None),
    "amazon.ca":     ("$", False, None),
    "amazon.co.uk":  ("£", True, None),
    "amazon.ie":     ("€", True, None),
    "amazon.com.au": ("$", True, None),
    "amazon.de":     ("€", True, "en_GB"),
    "amazon.fr":     ("€", True, "en_GB"),
    "amazon.it":     ("€", True, "en_GB"),
    "amazon.es":     ("€", True, "en_GB"),
    "amazon.nl":     ("€", True, "en_GB"),
    "amazon.com.be": ("€", True, "en_GB"),
    "amazon.se":     ("kr", True, "en_GB"),
    "amazon.pl":     ("zł", True, "en_GB"),
    "amazon.com.mx": ("$", True, "en_US"),
}
DEFAULT_MARKETPLACE = "amazon.com"

MARKETPLACE = DEFAULT_MARKETPLACE
CURRENCY = "$"
DAY_FIRST = False
ENGLISH = None
BASE = "https://www.amazon.com"
URLS: dict = {}
ALLOWED_HOSTS: set = set()


def set_marketplace(domain: Optional[str]) -> str:
    """Point this module at one Amazon store. Anything not in MARKETPLACES
    is refused rather than guessed, because the host allowlist below is the
    thing that stops a stored URL from steering the browser somewhere else,
    and a config value must not be able to widen it to an arbitrary host."""
    global MARKETPLACE, CURRENCY, DAY_FIRST, ENGLISH, BASE, URLS, ALLOWED_HOSTS
    domain = (domain or DEFAULT_MARKETPLACE).strip().lower()
    domain = re.sub(r"^(https?://)?(www\.)?", "", domain).rstrip("/")
    if domain not in MARKETPLACES:
        raise ValueError(
            f"marketplace {domain!r} is not one this app knows. Use one of: "
            + ", ".join(sorted(MARKETPLACES)))
    MARKETPLACE = domain
    CURRENCY, DAY_FIRST, ENGLISH = MARKETPLACES[domain]
    BASE = f"https://www.{domain}"
    URLS = {
        "home": _with_language(f"{BASE}/"),
        "orders": _with_language(f"{BASE}/gp/css/order-history"),
        "orders_alt": _with_language(f"{BASE}/your-orders/orders"),
        "account": _with_language(f"{BASE}/gp/css/homepage.html"),
    }
    ALLOWED_HOSTS = {domain}
    return domain


def _with_language(url: str) -> str:
    """The same URL asking for English, on a store that is not in English."""
    if not ENGLISH:
        return url
    return url + ("&" if "?" in url else "?") + "language=" + ENGLISH

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
    base = f"{BASE}/gp/css/order-history"
    q = ("?" + "&".join(parts)) if parts else ""
    return _with_language(f"{base}{q}")


def print_invoice_url(order_id: str) -> str:
    """Amazon's printable order summary (the receipt we save)."""
    return _with_language(f"{BASE}/gp/css/summary/print.html?orderID={order_id}")


def invoice_popover_url(order_id: str) -> str:
    """The fragment behind an order's Invoice / Rechnung menu. It links the
    printable summary and, where Amazon issued one, the invoice PDF(s)."""
    return _with_language(f"{BASE}/your-orders/invoice/popover?orderId={order_id}")


def order_details_url(order_id: str) -> str:
    return _with_language(f"{BASE}/gp/your-account/order-details?orderID={order_id}")


# Amazon order ids: 111-2223333-4445555 (retail) or D01-... (digital)
ORDER_ID_RE = re.compile(r"\b((?:D)?\d{2,3}-\d{7}-\d{7})\b")
ORDER_ID_IN_URL_RE = re.compile(r"orderID=((?:D)?\d{2,3}-\d{7}-\d{7})", re.I)

# ---------------------------------------------------------------------------
# Accessible names / labels
# ---------------------------------------------------------------------------
PRINT_RECEIPT_RE = re.compile(r"(printable\s+order\s+summary|print\s+invoice|"
                              r"view\s+invoice|invoice)", re.I)
GIFT_RECEIPT_RE = re.compile(r"gift\s+receipt", re.I)
# A signed-in amazon.de account set to German gets German pages whatever
# ?language= asks for (seen 2026-09),
# so the labels the parser reads are matched in German as well.
TOTAL_LABEL_RE = r"(grand\s+total|order\s+total|item\s+subtotal|gesamtsumme|zwischensumme)"
ORDER_PLACED_RE = r"(order\s+placed|bestellung\s+aufgegeben)"
SOLD_BY_RE = r"^(sold\s+by|verkauf\s+durch)\s*:"
SIGN_IN_RE = re.compile(r"^\s*sign\s*in\s*$", re.I)

# Controls that must NEVER be activated.
FORBIDDEN_CONTROL_RE = re.compile(
    r"(buy\s+it\s+again|buy\s+again|return\s+or\s+replace|return\s+items?|"
    r"cancel\s+(items?|order)|write\s+a\s+(product\s+)?review|leave\s+seller\s+feedback|"
    r"archive\s+order|add\s+to\s+cart|proceed\s+to\s+checkout|place\s+your\s+order|"
    r"track\s+package|problem\s+with\s+order|get\s+product\s+support|"
    r"change\s+(payment|shipping|address)|subscribe|share\s+gift\s+receipt)", re.I)


# Fold in the shared settings vocabulary. These apps guard with this pattern
# used inline rather than through an allowlist, which is correct for them:
# they click pagination controls like "Load more", and a document-word
# allowlist would refuse those and break the run. Composing the pattern keeps
# every existing call site working and means the next improvement to the
# shared list reaches this app without another edit.
try:
    from paperpull_core.controls import SETTINGS_CONTROL_RE as _SHARED_SETTINGS
    FORBIDDEN_CONTROL_RE = re.compile(
        "(?:%s)|(?:%s)" % (FORBIDDEN_CONTROL_RE.pattern, _SHARED_SETTINGS.pattern),
        re.I)
except Exception:  # the shared core is optional at import time
    pass

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

_MONTH_WORDS = (r"Jan(?:uary|uar)?|Feb(?:ruary|ruar)?|M(?:ar(?:ch)?|ärz)|Apr(?:il)?|"
                r"Ma[iy]|Jun[ei]?|Jul[iy]?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|O[ck]t(?:ober)?|"
                r"Nov(?:ember)?|De[cz](?:ember)?")
DATE_PATTERNS = [
    # January 5, 2025
    (re.compile(r"(" + _MONTH_WORDS + r")\.?\s+(\d{1,2}),?\s+(\d{4})", re.I), "mdY"),
    # 5 January 2025, 5. Januar 2025
    (re.compile(r"\b(\d{1,2})\.?\s+(" + _MONTH_WORDS + r")\.?\s+(\d{4})", re.I), "dMY"),
    # 01/05/2025, which is month first or day first by store, and 05.01.2025
    (re.compile(r"\b(\d{1,2})[/.](\d{1,2})[/.](\d{4})\b"), "slash"),
    (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"), "iso"),
]
_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
_MONTHS.update({"mär": 3, "mai": 5, "okt": 10, "dez": 12})   # German, where it differs


def _month_number(word: str) -> int:
    return _MONTHS[word[:3].lower()]


# Money. Every store prints two decimals. Which side the symbol sits on and
# which mark is the decimal vary, so amounts are found by shape and turned
# into a float, then written back in one canonical form, the store's symbol
# in front and a dot for the decimal, so every consumer downstream reads one
# format whatever the store prints.
_NUM = r"\d{1,3}(?:[.,\u00a0 ]\d{3})*[.,]\d{2}|\d+[.,]\d{2}"
_SYMBOLS = r"(?:\$|£|€|kr|zł|USD|GBP|EUR|CAD|AUD|MXN|SEK|PLN)"
MONEY_RE = re.compile(
    r"(-)?\s*" + _SYMBOLS + r"\s?(-)?(" + _NUM + r")(?!\d)"
    r"|(-)?(" + _NUM + r")\s?" + _SYMBOLS + r"(?![A-Za-z])")


def parse_amount(text: str) -> Optional[float]:
    """'1,234.56' -> 1234.56 and '1.234,56' -> 1234.56. The mark followed by
    exactly two digits at the end is the decimal, whichever it is."""
    s = re.sub(r"[\s\u00a0]", "", text or "")
    if not re.fullmatch(r"-?[\d.,]*\d", s):
        return None
    neg = s.startswith("-")
    s = s.lstrip("-")
    if re.search(r"[.,]\d{2}$", s):
        s = s[:-3].replace(".", "").replace(",", "") + "." + s[-2:]
    else:
        s = s.replace(".", "").replace(",", "")
    try:
        v = float(s)
    except ValueError:
        return None
    return -v if neg else v


def _amount_of(m) -> Optional[float]:
    neg = bool(m.group(1) or m.group(2) or m.group(4))
    v = parse_amount(m.group(3) or m.group(5) or "")
    return None if v is None else (-v if neg else v)


def find_amounts(text: str) -> List[float]:
    """Every amount in the text, in order."""
    out = []
    for m in MONEY_RE.finditer(text or ""):
        v = _amount_of(m)
        if v is not None:
            out.append(v)
    return out


def first_amount(text: str) -> Optional[float]:
    amounts = find_amounts(text)
    return amounts[0] if amounts else None


def fmt_money(value: float) -> str:
    """The one canonical form everything downstream reads."""
    sign = "-" if value < 0 else ""
    return f"{sign}{CURRENCY}{abs(value):,.2f}"


def amount_after(label: str, text: str, window: int = 40) -> str:
    """The first amount within `window` characters after a label such as
    'grand total', as canonical money, or '' when there is none."""
    for m in re.finditer(label, text or "", re.I):
        v = first_amount(text[m.end(): m.end() + window])
        if v is not None:
            return fmt_money(v)
    return ""
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
                month = _month_number(m.group(1))
                return f"{int(m.group(3)):04d}-{month:02d}-{int(m.group(2)):02d}"
            if kind == "dMY":
                month = _month_number(m.group(2))
                return f"{int(m.group(3)):04d}-{month:02d}-{int(m.group(1)):02d}"
            if kind == "slash":
                a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
                day, month = (a, b) if DAY_FIRST else (b, a)
                if not (1 <= month <= 12 and 1 <= day <= 31):
                    continue
                return f"{y:04d}-{month:02d}-{day:02d}"
            if kind == "iso":
                return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        except (KeyError, ValueError):
            continue
    return None


def money_value(text: str) -> float:
    """'$1,234.56' -> 1234.56, anything else -> 0.0."""
    v = first_amount(text)
    return v if v is not None else 0.0


def parse_subtotal(text: str) -> Optional[float]:
    """The item subtotal a summary prints, so a parse can be checked against
    it. None when the page does not print one."""
    s = amount_after(r"item\(?s?\)?\s+subtotal\s*:?", text, 20)
    return money_value(s) if s else None


def parse_money(text: str) -> str:
    v = first_amount(text)
    return fmt_money(v) if v is not None else ""


def parse_status(text: str) -> str:
    m = STATUS_WORDS_RE.search(text or "")
    return m.group(1).title() if m else ""


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


def goto_year_page(page, year: int, start_index: int = 0) -> bool:
    page.goto(orders_url(year, start_index), wait_until="domcontentloaded", timeout=60000)
    try:
        page.wait_for_selector(FALLBACK["page_ready"], timeout=20000)
    except Exception:
        pass
    page.wait_for_timeout(1500)
    return True


def has_next_page(page) -> bool:
    try:
        loc = page.locator(FALLBACK["next_page"])
        return loc.count() > 0 and loc.first.is_visible()
    except Exception:
        return False


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
    total = amount_after(r"total", text, 20) or parse_money(text)
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
    r"qty\b|[$£€]|-[$£€]|item\(s\)\s+subtotal|item\s+subtotal|subtotal|shipping|tax\b|"
    r"grand\s+total|order\s+total|total\s+before\s+tax|sold\s+by|supplied\s+by|"
    r"condition\b|payment\s+method|billing|shipping\s+address|credit\s+card|"
    r"gift\s+card|estimated|of\s+items?|order\s+placed|items?\s+ordered|"
    r"order\s+summary|ship\s+to|back\s+to\s+top|print$|view\s+related|"
    r"return\s+window|united\s+states|united\s+kingdom|deutschland|germany|"
    r"english\b|order\s*#|"
    # the same boilerplate on a German summary
    r"verkauf\s+durch|zwischensumme|verpackung\s+&|gesamt|geschätzte\s+ust|"
    r"summe\s*:|versandadresse|zahlungsart|bestellung\s+aufgegeben|"
    r"bestellübersicht|zugestellt|widerruf|zurück\s+zum)", re.I)

# Address-ish lines that appear in the Ship-to block.
_ADDRESS_LINE_RE = re.compile(
    r"^(\d+\s+[A-Z0-9 .'-]+|[A-Z][A-Za-z .'-]+,\s*[A-Z]{2}\s*\d{5}(-\d{4})?)$")


def _clean_item_name(name: str, min_len: int = 5) -> str:
    name = _html.unescape(re.sub(r"\s+", " ", name or "")).strip()
    if len(name) < min_len or _NON_ITEM_NAME_RE.search(name):
        return ""
    return name


def _is_pair_title(line: str) -> bool:
    """A title in the title-then-price layout. The bare price on the next
    line is the evidence, so a short name like "Banana" is allowed here
    where _is_title_line would want ten characters."""
    line = (line or "").strip()
    if len(line) < 3 or first_amount(line) is not None:
        return False
    if line.endswith(":"):      # a label ("collected:" above the tax amount), not a product
        return False
    return not (_NON_ITEM_NAME_RE.search(line) or _ADDRESS_LINE_RE.match(line))


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
        if re.search(ORDER_PLACED_RE, line, re.I):
            placed = parse_date(line)
            if placed:
                break
    date = placed or parse_date(body)
    if date:
        purchase.purchase_date = date

    # Grand Total. NOTE: when a gift card covers the order, Amazon's invoice
    # shows "Grand Total: $0.00", keep the order-history total in that case
    # so the receipt index still reflects what the order was worth.
    total = ""
    for label in (r"grand\s+total", r"order\s+total", r"gesamtsumme"):
        total = amount_after(label, body, 40)
        if total:
            break
    if not total:
        amounts = find_amounts(body)
        if amounts:
            total = fmt_money(max(amounts))
    if total:
        is_zero = money_value(total) == 0
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
    if len(line) < 10 or first_amount(line) is not None:
        return False
    if _NON_ITEM_NAME_RE.search(line) or _ADDRESS_LINE_RE.match(line):
        return False
    return True


def _parse_items_from_summary_text(body: str) -> List[Item]:
    """Parse item lines from Amazon's printable order summary.

    Two layouts are supported:

    1. Current layout (verified 2026-07), each item is a title line followed
       by a "Sold by: <seller>" line, then its price(s):

           AXL 10mm Stem, IKEA Office Chair Wheels, ...
           Sold by: AXL Global
           Return window closed on February 2, 2026
           $30.99

    2. Classic layout, "<qty> of: <Product Title>" then the price.

    3. Whole Foods and Amazon Fresh (verified 2026-09), no "Sold by" and no
       quantity anywhere. After "Purchased at Whole Foods Market" every item
       is a title line followed by a line holding only its price, and an
       item bought twice is simply listed twice:

           Whole Foods Market Sea Scallops 10/20 Count, 12 OZ
           $24.49
           Whole Foods Market Sea Scallops 10/20 Count, 12 OZ
           $24.49

       Repeats collapse into one item with the quantity and a line total.
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
        if not re.match(SOLD_BY_RE, line, re.I):
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
                v = first_amount(nxt)
                if v is not None and v >= 0:
                    price = fmt_money(v)
            qm = re.match(r"^(?:qty|quantity)\s*:?\s*(\d+)$", nxt, re.I)
            if qm:
                qty = qm.group(1)
        seen.add(title.lower())
        items.append(Item(name=title[:300], quantity=qty or "1",
                          unit_price=price, line_total=price))
    if items:
        return items

    # --- layout 3 (Whole Foods, title then a bare price) ---------------------
    return _parse_title_price_pairs(lines)


def _bare_amount(line: str) -> Optional[float]:
    """The amount when the line is nothing but one price, else None."""
    m = MONEY_RE.fullmatch((line or "").strip())
    return _amount_of(m) if m else None


def _parse_title_price_pairs(lines: List[str]) -> List[Item]:
    """Items from a summary that lists each one as a title line followed by a
    line that is only a price. A repeated title-and-price pair is the same
    item bought again, so it becomes a quantity rather than a second row."""
    # A page number sits between a title and its price when the item straddles
    # a page break in the saved PDF, and it is never an item, so drop it.
    lines = [l for l in lines if l and not re.match(r"^\d{1,3}$", l)]
    counted: "dict[tuple, int]" = {}
    order: List[tuple] = []
    for i in range(len(lines) - 1):
        amount = _bare_amount(lines[i + 1])
        if amount is None or not _is_pair_title(lines[i]):
            continue
        title = _clean_item_name(lines[i], min_len=3)
        if not title:
            continue
        key = (title[:300], amount)
        if key not in counted:
            order.append(key)
        counted[key] = counted.get(key, 0) + 1
    items: List[Item] = []
    for title, unit in order:
        qty = counted[(title, unit)]
        items.append(Item(name=title, quantity=str(qty), unit_price=fmt_money(unit),
                          line_total=fmt_money(unit * qty)))
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
# Receipt access, the printable summary IS the receipt
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
    if ORDER_ID_RE.search(body) and re.search(TOTAL_LABEL_RE, body, re.I):
        return True
    return False


# ---------------------------------------------------------------------------
# Invoice PDFs, the legal invoice behind an order's Invoice / Rechnung menu
# ---------------------------------------------------------------------------

# Verified on amazon.de 2026-09: the popover links
#   /documents/download/<uuid>/invoice.pdf   ("Rechnung")
# served from the store's own host as application/pdf. The uuid is minted per
# request, so links are fetched and used right away, never stored. With the
# site switched to another language the same links carry a prefix,
# /-/en/documents/download/..., which is kept as served.
INVOICE_PDF_HREF_RE = re.compile(
    r'href="((?:/-/[a-z]{2}(?:[_-][A-Za-z]{2})?)?/documents/download/[0-9A-Za-z-]+/[^"?#]+\.pdf)"'
    r'[^>]*>(.*?)</a>',
    re.I | re.S)


def find_invoice_pdf_links(page, order_id: str) -> List[Tuple[str, str]]:
    """(label, absolute url) for each invoice PDF Amazon offers for the order.
    A plain GET of the popover fragment with the signed-in session; nothing on
    the page is clicked. Empty when the order has only the printable summary."""
    try:
        resp = page.context.request.get(invoice_popover_url(order_id),
                                        max_redirects=3, timeout=30000)
    except Exception as e:
        log.warning("invoice popover fetch failed: %s", str(e).splitlines()[0][:100])
        return []
    if not resp.ok or not is_safe_url(resp.url):
        return []
    out, seen = [], set()
    for m in INVOICE_PDF_HREF_RE.finditer(resp.text()):
        url = BASE + _html.unescape(m.group(1))
        if url in seen or not is_safe_url(url):
            continue
        seen.add(url)
        label = _html.unescape(re.sub(r"<[^>]+>|\s+", " ", m.group(2))).strip()
        out.append((label, url))
    return out


def download_invoice_pdf(page, url: str, out_path) -> bool:
    """Fetch one invoice PDF with the signed-in session and write it. False,
    with nothing written, unless the answer is a PDF from the store's host."""
    from pathlib import Path
    if not is_safe_url(url):
        return False
    try:
        resp = page.context.request.get(url, max_redirects=3, timeout=90000)
    except Exception as e:
        log.warning("invoice download failed: %s", str(e).splitlines()[0][:100])
        return False
    if not resp.ok or not is_safe_url(resp.url):
        log.warning("invoice download returned %s", resp.status)
        return False
    body = resp.body()
    if not body.startswith(b"%PDF"):
        log.warning("invoice download was not a PDF (%d bytes)", len(body))
        return False
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(body)
    return True


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


# ---------------------------------------------------------------------------
# Host allowlist. Added repo-wide after a review found this app would fetch or
# navigate to whatever URL a stored record or a page attribute contained, using
# the live signed-in session. Parsed, never a string prefix, so a lookalike
# host cannot walk through.
# ---------------------------------------------------------------------------
set_marketplace(DEFAULT_MARKETPLACE)


def is_safe_url(url: str) -> bool:
    """True only for an https URL on one of this provider's own hosts.

    The check itself lives in the core, so all of them answer the same way.
    This app keeps the hosts, which is the part that really is its own."""
    return _host_allows(url, ALLOWED_HOSTS)
