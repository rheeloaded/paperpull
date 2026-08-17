"""ALL Walmart.com selectors, URL patterns, and page behavior live here.

When Walmart changes its website, repair this file only. Nothing elsewhere
in the project should contain a Walmart selector.

INITIAL SELECTORS: written 2026-07-23 from Walmart's known URL scheme; run
`python walmart_receipts.py --diagnose` and `probe_orders.py` after signing
in, then repair the FALLBACK selectors below against Diagnostics/ output —
the same repair workflow used for the Target project.

Walmart's purchase history at walmart.com/orders mixes Online orders and
In-store purchases in one list; cards are classified by their text/URL
rather than by page tabs. Walmart also uses aggressive bot detection
("Press & Hold" / "Robot or human?" challenges). This module only detects
those and reports them — the tool stops and asks the user to take over;
it NEVER attempts a bypass.

Navigation strategy priority:
  1. Accessible roles and names
  2. Visible labels and button text
  3. Stable URL patterns
  4. Semantic page structure
  5. Centralized fallback selectors below
"""
# Site layer verified working against the live site: 2026-08
from __future__ import annotations

import html as _html
import logging
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

from paperpull_core.models import IN_STORE, ONLINE, Item, Purchase
from storage import now_iso

log = logging.getLogger("walmart_receipts.site")

# ---------------------------------------------------------------------------
# URLs
# ---------------------------------------------------------------------------

URLS = {
    "home": "https://www.walmart.com/",
    "orders": "https://www.walmart.com/orders",
    "account": "https://www.walmart.com/account",
}

LOGIN_URL_MARKERS = ["/account/login", "login.walmart", "identity.walmart",
                     "/authentication", "signin"]

# Verified 2026-07-23 (Diagnostics/probe-orders.json, probe-detail.json):
# order id = the 20-digit suffix of data-automation-id
#   "view-order-details-link-00000000000000000000".
# Detail URL: /orders/<id>?groupId=0&storePurchase=true  (store purchases).
ORDER_LINK_RE = re.compile(r"/orders/([0-9]{10,})")
DETAIL_LINK_AUTO_RE = re.compile(r"view-order-details-link-([0-9]{10,})")
STORE_MARKER_RE = re.compile(
    r"(store\s+purchase|storePurchase=true|in[\s\-]?store|walmart\s+pay|"
    r"purchased\s+at|store\s+trip)", re.I)

# ---------------------------------------------------------------------------
# Accessible names / labels
# ---------------------------------------------------------------------------

TAB_NAME = {
    ONLINE: re.compile(r"^\s*online\s*$", re.I),
    IN_STORE: re.compile(r"^\s*in[\s\-]?store\s*$", re.I),
}

LOAD_MORE_RE = re.compile(
    r"(load more|show more|view more|more orders|more purchases|next page)", re.I)
# A section EXPANDER only (rare). The actual print trigger "View receipt
# details" is handled by PRINT_RECEIPT_RE, so open_receipt_section never
# clicks it prematurely (that would fire window.print before we are ready).
RECEIPT_SECTION_RE = re.compile(
    r"(receipts?\s*&?\s*(and)?\s*invoices?)", re.I)
# Receipt controls (in-store). Invoices are handled separately so an online
# "Print invoice" is never mislabeled as a receipt.
PRINT_RECEIPT_RE = re.compile(
    r"(view\s+receipt\s+details|print\s+receipt|view\s+receipt)", re.I)
GIFT_RECEIPT_RE = re.compile(r"gift\s+receipt", re.I)
INVOICE_RE = re.compile(r"(view|print|download)\s+(detailed\s+)?invoices?", re.I)
SIGN_IN_RE = re.compile(r"^\s*sign\s*in\s*$", re.I)

# Controls that must NEVER be activated.
FORBIDDEN_CONTROL_RE = re.compile(
    r"(start\s+a\s+return|return\s+or\s+replace|buy\s+(it\s+)?again|add\s+to\s+cart|"
    r"reorder|write\s+a\s+review|rate\s*(and|&)?\s*review|track\s+(package|shipment)|"
    r"cancel\s+order|payment\s+method|delivery\s+(information|address)|"
    r"check\s*out|place\s+order|substitutions|tip\s+your|edit\s+order|"
    r"gift\s+receipt|chat\s+with|start\s+a\s+chat)", re.I)

SECURITY_CHALLENGE_MARKERS = [
    "robot or human", "press & hold", "press and hold", "are you a robot",
    "verify your identity", "unusual activity", "suspicious activity",
    "captcha", "recaptcha", "access denied", "verification code",
    "security check", "we need to verify", "prove you're human",
]

RATE_LIMIT_MARKERS = [
    "too many requests", "rate limit", "try again later",
    "temporarily blocked", "http error 429",
]

# CSS selectors verified 2026-07-23 against the signed-in account.
FALLBACK = {
    "order_card": "[data-testid^='order-']",         # order-0, order-1, ...
    "detail_link": "[data-automation-id^='view-order-details-link-']",
    "item_tile": "[data-testid='itemtile-stack']",
    "item_name": "[data-testid='productName'], [data-testid='productDescription']",
    "item_price": "[data-testid='line-price']",
    "show_all_items": "[data-automation-id='show-all-items'], "
                      "[data-automation-id='items-toggle-link']",
    "order_type_filter": "button:has-text('Order type')",
    "receipt_iframe": "iframe",
    "page_ready": "[data-testid^='order-'], [data-automation-id^='view-order-details-link-']",
    # both types share the same card container; type is read from card text
    "card_container_online": "[data-testid^='order-']",
    "card_container_instore": "[data-testid^='order-']",
    "store_receipt_container": "[data-testid*='receipt'], [data-automation-id*='receipt']",
}

CARD_CONTAINER = {
    ONLINE: FALLBACK["order_card"],
    IN_STORE: FALLBACK["order_card"],
}

# Card is a purchase card, not the status-tracker element that also matches.
def _is_order_card_testid(testid: str) -> bool:
    return bool(re.fullmatch(r"order-\d+", testid or ""))

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
    r"\b(delivered|shipped|arriving|cancell?ed|return\s+complete|returned|refunded|"
    r"picked\s*up|ready\s+for\s+pickup|processing|preparing|completed|"
    r"return\s+started|purchased|in\s+progress|out\s+for\s+delivery)\b", re.I)
STORE_TRIP_RE = re.compile(
    r"(?:store\s+purchase|purchased)\s+at\s+([^\n]+)|store\s+trip\s+at\s+([^\n]+)", re.I)


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
    """Extract the order id from a details href/URL. Type is decided from
    card text or the storePurchase flag, not the path."""
    m = ORDER_LINK_RE.search(href or "")
    if not m:
        return None, None
    kind = IN_STORE if "storepurchase=true" in (href or "").lower() else None
    return kind, m.group(1)


# ---------------------------------------------------------------------------
# Session / safety checks
# ---------------------------------------------------------------------------

def looks_signed_out(page) -> bool:
    url = (page.url or "").lower()
    if any(marker in url for marker in LOGIN_URL_MARKERS):
        return True
    try:
        if page.locator("input[type='password']").count() > 0:
            return True
    except Exception:
        pass
    try:
        heading = page.get_by_role("heading", name=SIGN_IN_RE)
        if heading.count() > 0 and heading.first.is_visible():
            return True
    except Exception:
        pass
    return False


def detect_security_challenge(page) -> Optional[str]:
    try:
        title = (page.title() or "").lower()
    except Exception:
        title = ""
    try:
        body = page.locator("body").inner_text(timeout=5000).lower()
    except Exception:
        body = ""
    haystack = title + "\n" + body[:5000]
    for marker in SECURITY_CHALLENGE_MARKERS:
        if marker in haystack:
            return f"Security challenge detected: '{marker}'"
    for marker in RATE_LIMIT_MARKERS:
        if marker in haystack:
            return f"Possible rate limiting detected: '{marker}'"
    return None


# ---------------------------------------------------------------------------
# Purchase history navigation
# ---------------------------------------------------------------------------

def goto_orders(page) -> None:
    page.goto(URLS["orders"], wait_until="domcontentloaded", timeout=60000)
    try:
        page.wait_for_selector(FALLBACK["page_ready"], timeout=30000)
    except Exception:
        log.warning("Purchase-history content did not appear within 30s")
    page.wait_for_timeout(2500)


# Selecting the Order-type filter sets a URL parameter; navigating straight
# to it is more robust than operating the bottomsheet. Verified 2026-07-23.
FILTER_URL = {
    ONLINE: "https://www.walmart.com/orders?filterIds=online",
    IN_STORE: "https://www.walmart.com/orders?filterIds=in-store",
}


def select_history_tab(page, purchase_type: str) -> bool:
    """Show only Online or In-store purchases by navigating to the filtered
    order-list URL."""
    page.goto(FILTER_URL[purchase_type], wait_until="domcontentloaded", timeout=60000)
    try:
        page.wait_for_selector(FALLBACK["page_ready"], timeout=30000)
    except Exception:
        log.warning("%s filtered order list did not render within 30s", purchase_type)
    page.wait_for_timeout(2500)
    return True


YEAR_OPTION_RE = re.compile(
    r"(20\d{2}|(past|last)\s+\d+\s+(months?|years?)|all(\s+time)?)", re.I)


def get_year_options(page) -> List[str]:
    """Walmart's order list has a time-range <select> filter (e.g. 'Last 3
    months', '2025'). Only trust real selects whose options look like
    years/ranges — never header buttons."""
    try:
        for select in page.locator("select").all():
            options = [o.strip() for o in select.locator("option").all_inner_texts()]
            candidate = [o for o in options if YEAR_OPTION_RE.fullmatch(o)]
            if candidate and len(candidate) >= max(1, len([o for o in options if o]) - 1):
                return candidate
    except Exception:
        pass
    return []


def select_year_option(page, option_text: str) -> bool:
    try:
        for select in page.locator("select").all():
            options = select.locator("option").all_inner_texts()
            if any(option_text.strip() == o.strip() for o in options):
                select.select_option(label=option_text.strip())
                page.wait_for_timeout(3000)
                return True
    except Exception:
        pass
    return False


def _go_next_page(page) -> bool:
    """Advance to the next page of the paginated order list. Returns False
    when there is no next page."""
    for getter in (
        lambda: page.get_by_role("link", name=re.compile(r"^\s*next\s*$", re.I)),
        lambda: page.get_by_role("button", name=re.compile(r"^\s*next\s*$", re.I)),
        lambda: page.locator("[aria-label*='Next' i]"),
    ):
        try:
            loc = getter()
            if loc.count() > 0 and loc.first.is_visible() and loc.first.is_enabled():
                loc.first.scroll_into_view_if_needed()
                loc.first.click()
                page.wait_for_timeout(2500)
                return True
        except Exception:
            continue
    return False


def load_all_cards(page, purchase_type: str = ONLINE,
                   delay_ms: int = 1500, max_rounds: int = 200) -> int:
    """Walmart paginates the order list. collect_cards() is called per page
    by the caller via iter_all_cards(); here we just ensure the first page's
    cards are present and return the visible count."""
    try:
        page.wait_for_selector(FALLBACK["order_card"], timeout=15000)
    except Exception:
        pass
    for _ in range(3):
        page.mouse.wheel(0, 2000)
        page.wait_for_timeout(delay_ms)
    return _card_count(page, purchase_type)


def iter_all_cards(page, purchase_type: str, delay_ms: int = 1500,
                   max_pages: int = 100) -> List["RawCard"]:
    """Collect cards of the requested type across every paginated page."""
    all_cards: List[RawCard] = []
    seen = set()
    for _ in range(max_pages):
        load_all_cards(page, purchase_type, delay_ms)
        for card in collect_cards(page, purchase_type):
            key = card.href or card.text[:60]
            if key in seen:
                continue
            seen.add(key)
            all_cards.append(card)
        if not _go_next_page(page):
            break
    return all_cards


def _card_count(page, purchase_type: str = ONLINE) -> int:
    try:
        return len([t for t in page.locator(FALLBACK["order_card"])
                    .evaluate_all("els => els.map(e => e.getAttribute('data-testid'))")
                    if _is_order_card_testid(t)])
    except Exception:
        try:
            return page.locator(FALLBACK["order_card"]).count()
        except Exception:
            return 0


@dataclass
class RawCard:
    href: str
    text: str
    order_id: str = ""
    kind: str = ""


def collect_cards(page, purchase_type: str = ONLINE) -> List[RawCard]:
    """Collect purchase cards of the requested type on the CURRENT page.
    Order id comes from the view-order-details automation-id; type from the
    'Store purchase' marker in the card text."""
    cards: List[RawCard] = []
    try:
        containers = page.locator(FALLBACK["order_card"]).all()
    except Exception:
        containers = []
    for c in containers:
        try:
            testid = c.get_attribute("data-testid") or ""
            if not _is_order_card_testid(testid):
                continue
            text = (c.inner_text(timeout=3000) or "").strip()
            order_id = ""
            try:
                auto = c.locator(FALLBACK["detail_link"]).first.get_attribute(
                    "data-automation-id", timeout=1500) or ""
                mm = DETAIL_LINK_AUTO_RE.search(auto)
                if mm:
                    order_id = mm.group(1)
            except Exception:
                pass
            if not order_id:
                continue
            kind = IN_STORE if STORE_MARKER_RE.search(text) else ONLINE
            if kind != purchase_type:
                continue
            cards.append(RawCard(href="", text=text, order_id=order_id, kind=kind))
        except Exception:
            continue
    return cards


def card_to_purchase(card: RawCard, purchase_type: str,
                     base_url: str = "https://www.walmart.com") -> Optional[Purchase]:
    order_number = card.order_id or (parse_order_link(card.href)[1] or "")
    if not order_number:
        return None
    if purchase_type == IN_STORE:
        # groupId=0 is required for the details page to render the receipt
        # controls ("View receipt details"); without it the button is absent.
        url = f"{base_url}/orders/{order_number}?groupId=0&storePurchase=true"
    else:
        url = f"{base_url}/orders/{order_number}"
    store = ""
    sm = STORE_TRIP_RE.search(card.text or "")
    if sm:
        store = (sm.group(1) or sm.group(2) or "").strip()
    return Purchase(
        purchase_type=purchase_type,
        purchase_date=parse_date(card.text) or "",
        order_number=order_number,
        total=parse_money(card.text),
        status=parse_status(card.text),
        details_url=url,
        store_info=store,
        discovered_at=now_iso(),
    )


# ---------------------------------------------------------------------------
# Purchase details extraction
# ---------------------------------------------------------------------------

def goto_details(page, purchase: Purchase) -> None:
    page.goto(purchase.details_url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(3000)


def extract_details(page, purchase: Purchase) -> Purchase:
    try:
        body_text = page.locator("body").inner_text(timeout=10000)
    except Exception:
        body_text = ""
    # Trim the site footer if a recognizable boundary exists.
    body_text = re.split(r"\n\s*(Footer|All Departments)\s*\n", body_text, maxsplit=1)[0]

    # Online detail shows "May 31, 2026 order"; in-store shows a "purchased"
    # line. Match either, plus explicit "placed/order date" labels.
    placed = None
    for line in body_text.splitlines():
        if re.search(r"(placed|purchas|order\s+date|transaction\s+date"
                     r"|\d{4}\s+order\b|\border\s+placed)", line, re.I):
            placed = parse_date(line)
            if placed:
                break
    date = placed or parse_date(body_text)
    if date:
        purchase.purchase_date = date

    # Do NOT overwrite the order id discovered from the details-link
    # automation-id (matches the URL, no dashes). Walmart's detail page shows
    # a dashed display form ("Order# 2000144-34385041") that would fork the
    # dedup key. Only fill in when discovery somehow left it blank.
    if not purchase.order_number:
        m = re.search(r"(?:order|receipt|transaction)\s*(?:number|#)\s*:?\s*([0-9][0-9\-]{6,})",
                      body_text, re.I)
        if m:
            purchase.order_number = re.sub(r"\D", "", m.group(1))

    total = None
    for line in body_text.splitlines():
        if re.search(r"\btotal\b", line, re.I) and not re.search(r"subtotal", line, re.I):
            money = MONEY_RE.search(line)
            if money:
                total = f"${money.group(1)}"
                break
    if not total:
        amounts = MONEY_RE.findall(body_text)
        if amounts:
            total = "$" + max(amounts, key=lambda a: float(a.replace(",", "")))
    if total:
        purchase.total = total

    status = parse_status(body_text)
    if status:
        purchase.status = status
    if re.search(r"(order|this purchase)\s+(was\s+)?cancell?ed", body_text, re.I):
        purchase.status = purchase.status or "Canceled"

    if purchase.purchase_type == IN_STORE and not purchase.store_info:
        m = (STORE_TRIP_RE.search(body_text)
             or re.search(r"(walmart\s+(supercenter|neighborhood market)[^\n]{0,60})",
                          body_text, re.I))
        if m:
            purchase.store_info = next(g for g in m.groups() if g).strip()

    if purchase.purchase_type == ONLINE:
        fm = re.search(r"\b(shipping|delivery|curbside|pickup|shipt|same\s*day)\b",
                       body_text, re.I)
        if fm:
            purchase.fulfillment = fm.group(1).title()

    purchase.items = extract_items(page)
    purchase.details_url = page.url
    return purchase


# ---------------------------------------------------------------------------
# Item extraction (same block-parser approach proven on the Target project)
# ---------------------------------------------------------------------------

_NON_ITEM_NAME_RE = re.compile(
    r"^(barcode\b|walmart[:\s]|qty\b|\$|unit price|logo\b|at\s|track |"
    r"view |delivered to|package delivered|gift receipt|digital receipt|"
    r"start a return|buy again|reorder|rate & review|get help|"
    r"purchased on|placed at|order#|order #|shopped|total|subtotal|tax\b)", re.I)
_LOCATION_LINE_RE = re.compile(r"^[A-Z][A-Za-z .'-]+,\s*[A-Z]{2}(\s+\d{5})?$")
_MONTH_DAY_RE = re.compile(
    r"^((Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*,?\s+)?"
    r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2}\b", re.I)
PRICE_LINE_RE = re.compile(
    r"^\$\s*[\d,]+(?:\.\d{1,2})?(\s*(unit price|each|/\s*\S+))?$", re.I)


def _clean_item_name(name: str) -> str:
    name = _html.unescape(re.sub(r"\s+", " ", name or "")).strip()
    if len(name) < 4 or _NON_ITEM_NAME_RE.search(name):
        return ""
    return name


def _looks_like_item_name(line: str) -> bool:
    if len(line) < 6 or MONEY_RE.search(line):
        return False
    if parse_status(line) and len(line) < 45:
        return False
    if parse_date(line) and len(line) < 45:
        return False
    if _MONTH_DAY_RE.match(line) and len(line) < 45:
        return False
    if _LOCATION_LINE_RE.match(line):
        return False
    return bool(_clean_item_name(line))


def _parse_items_from_text(text: str) -> List[Item]:
    items: List[Item] = []
    cur: Optional[Item] = None
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if PRICE_LINE_RE.match(line):
            if cur is not None:
                mm = MONEY_RE.search(line)
                price = "$" + mm.group(1) if mm else ""
                if not cur.unit_price:
                    cur.unit_price = price
                else:
                    cur.line_total = price
            continue
        qm = QTY_RE.match(line)
        if qm:
            if cur is not None:
                cur.quantity = qm.group(1)
            continue
        if re.search(r"\b(returned|refunded|return\s+(started|complete))\b", line, re.I) \
                and len(line) < 45:
            if cur is not None:
                cur.return_status = "Returned"
            continue
        if _looks_like_item_name(line):
            cur = Item(name=_clean_item_name(line))
            items.append(cur)
    for it in items:
        if not it.line_total:
            it.line_total = it.unit_price
    return items


def expand_all_items(page) -> None:
    """Click 'show all items' / 'items toggle' so collapsed line items render
    before extraction."""
    try:
        loc = page.locator(FALLBACK["show_all_items"])
        for i in range(min(loc.count(), 6)):
            el = loc.nth(i)
            if el.is_visible():
                el.click()
                page.wait_for_timeout(800)
    except Exception:
        pass


def extract_items(page) -> List[Item]:
    """Primary: Walmart item tiles (data-testid='itemtile-stack') with
    productName + line-price. Verified 2026-07-23."""
    expand_all_items(page)
    items: List[Item] = []
    seen_names = set()

    try:
        tiles = page.locator(FALLBACK["item_tile"]).all()
    except Exception:
        tiles = []
    for tile in tiles:
        try:
            name = ""
            nl = tile.locator(FALLBACK["item_name"])
            if nl.count() > 0:
                name = _clean_item_name(nl.first.inner_text(timeout=1500) or "")
            if not name:
                try:
                    name = _clean_item_name(
                        tile.locator("img[alt]").first.get_attribute("alt") or "")
                except Exception:
                    name = ""
            if not name or name.lower() in seen_names:
                continue
            text = tile.inner_text(timeout=1500) or ""
            qty = ""
            qm = QTY_RE.search(text)
            if qm:
                qty = qm.group(1)
            price = ""
            try:
                pl = tile.locator(FALLBACK["item_price"])
                if pl.count() > 0:
                    price = parse_money(pl.first.inner_text(timeout=1000) or "")
            except Exception:
                pass
            if not price:
                prices = MONEY_RE.findall(text)
                price = f"${prices[-1]}" if prices else ""
            ret = "Returned" if re.search(
                r"\b(returned|refunded|return\s+(started|complete))\b", text, re.I) else ""
            seen_names.add(name.lower())
            items.append(Item(name=name, quantity=qty, unit_price=price,
                              line_total=price, status=parse_status(text),
                              return_status=ret))
        except Exception:
            continue
    if items:
        return items

    # fallback: /ip/ product links
    try:
        links = page.locator(FALLBACK["item_link"]).all() \
            if "item_link" in FALLBACK else page.locator("a[href*='/ip/']").all()
    except Exception:
        links = []
    for link in links:
        try:
            name = _clean_item_name(link.inner_text(timeout=1500) or "")
            if not name:
                try:
                    name = _clean_item_name(
                        link.locator("img").first.get_attribute("alt") or "")
                except Exception:
                    name = ""
            if not name or name.lower() in seen_names:
                continue
            seen_names.add(name.lower())
            items.append(Item(name=name))
        except Exception:
            continue

    if not items:
        try:
            for img in page.locator("img[alt]").all():
                alt = _clean_item_name(img.get_attribute("alt") or "")
                if len(alt) > 12 and not re.search(r"(logo|icon|walmart)", alt, re.I) \
                        and alt.lower() not in seen_names:
                    seen_names.add(alt.lower())
                    items.append(Item(name=alt))
        except Exception:
            pass
    return items


# ---------------------------------------------------------------------------
# Receipt access
# ---------------------------------------------------------------------------

def scroll_full_page(page, rounds: int = 5, delay_ms: int = 800) -> None:
    """Scroll top-to-bottom so lazily-rendered sections (the receipt/invoice
    controls live near the bottom of the order-details page) are present."""
    try:
        for _ in range(rounds):
            page.mouse.wheel(0, 2500)
            page.wait_for_timeout(delay_ms)
        page.keyboard.press("End")
        page.wait_for_timeout(delay_ms)
    except Exception:
        pass


def open_receipt_section(page) -> bool:
    """Prepare the details page for receipt capture: scroll so the lazy
    receipt/invoice controls render, and click a 'Receipts & invoices'
    expander if one exists (Walmart usually has none). Never clicks the
    'View receipt details' print trigger itself. Returns True if a receipt
    or invoice control is now present."""
    scroll_full_page(page)
    for role in ("button", "link", "tab"):
        try:
            loc = page.get_by_role(role, name=RECEIPT_SECTION_RE)
            for i in range(min(loc.count(), 5)):
                el = loc.nth(i)
                try:
                    name = (el.inner_text(timeout=1500) or "")
                except Exception:
                    name = ""
                if GIFT_RECEIPT_RE.search(name) or FORBIDDEN_CONTROL_RE.search(name):
                    continue
                if el.is_visible():
                    el.click()
                    page.wait_for_timeout(2000)
        except Exception:
            continue
    return bool(find_print_receipt_controls(page) or find_invoice_controls(page))


def find_print_receipt_controls(page) -> list:
    controls = []
    for role in ("button", "link"):
        try:
            loc = page.get_by_role(role, name=PRINT_RECEIPT_RE)
            for i in range(loc.count()):
                el = loc.nth(i)
                try:
                    name = el.inner_text(timeout=1500) or ""
                except Exception:
                    name = ""
                if GIFT_RECEIPT_RE.search(name) or FORBIDDEN_CONTROL_RE.search(name):
                    continue
                controls.append(el)
        except Exception:
            continue
    return controls


def find_invoice_controls(page) -> list:
    controls = []
    for role in ("button", "link"):
        try:
            loc = page.get_by_role(role, name=INVOICE_RE)
            for i in range(loc.count()):
                controls.append(loc.nth(i))
        except Exception:
            continue
    return controls


def find_printing_frame(page, wait_ms: int = 6000):
    rounds = max(1, wait_ms // 500)
    for _ in range(rounds):
        for frame in page.frames:
            if frame == page.main_frame:
                continue
            try:
                if frame.evaluate("() => window.__targetReceiptsPrintCalled === true"):
                    return frame
            except Exception:
                continue
        page.wait_for_timeout(500)
    return find_receipt_iframe(page)


def find_receipt_iframe(page):
    try:
        for frame in page.frames:
            if frame == page.main_frame:
                continue
            try:
                text = frame.locator("body").inner_text(timeout=2000)
            except Exception:
                continue
            if re.search(r"(store receipt|order number|receipt id|subtotal)",
                         text or "", re.I) and len(text or "") > 150:
                return frame
    except Exception:
        pass
    return None


def trigger_print_receipt(page, control, timeout_ms: int = 15000) -> Tuple[str, object]:
    old_url = page.url
    download_info = {}
    popup_info = {}

    def on_download(d):
        download_info["download"] = d

    def on_popup(p):
        popup_info["page"] = p

    page.on("download", on_download)
    page.context.on("page", on_popup)
    try:
        try:
            page.evaluate("() => { window.__targetReceiptsPrintHTML = null; "
                          "window.__targetReceiptsPrintCalled = false; }")
        except Exception:
            pass
        control.scroll_into_view_if_needed()
        control.click()
        page.wait_for_timeout(1500)
        deadline_rounds = max(1, timeout_ms // 500)
        for _ in range(deadline_rounds):
            if download_info.get("download"):
                return "download", download_info["download"]
            if popup_info.get("page"):
                popup = popup_info["page"]
                try:
                    popup.wait_for_load_state("domcontentloaded", timeout=15000)
                except Exception:
                    pass
                return "popup", popup
            try:
                if page.evaluate("() => window.__targetReceiptsPrintCalled === true"):
                    return "print_called", page
            except Exception:
                pass
            if page.url != old_url:
                return "navigated", page
            page.wait_for_timeout(500)
        return "inline", page
    finally:
        try:
            page.remove_listener("download", on_download)
        except Exception:
            pass
        try:
            page.context.remove_listener("page", on_popup)
        except Exception:
            pass


def wait_for_receipt_content(page, timeout_ms: int = 15000) -> str:
    deadline_rounds = max(1, timeout_ms // 500)
    for _ in range(deadline_rounds):
        try:
            if page.locator(FALLBACK["store_receipt_container"]).count() > 0:
                return "store-receipt"
        except Exception:
            pass
        try:
            if find_print_receipt_controls(page):
                return "print-controls"
        except Exception:
            pass
        page.wait_for_timeout(500)
    return ""


def count_store_receipts(page) -> int:
    try:
        body = page.locator("body").inner_text(timeout=5000)
        m = re.search(r"store receipt\s*\d+\s*of\s*(\d+)", body, re.I)
        if m:
            return max(1, int(m.group(1)))
    except Exception:
        pass
    return 1
