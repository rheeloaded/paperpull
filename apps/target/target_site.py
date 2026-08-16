"""ALL Target.com selectors, URL patterns, and page behavior live here.

When Target changes its website, repair this file only. Nothing elsewhere
in the project should contain a Target selector.

Navigation strategy priority (spec section 8):
  1. Accessible roles and names
  2. Visible labels and button text
  3. Stable URL patterns
  4. Semantic page structure
  5. Centralized fallback selectors below
"""
# Site layer verified working against the live site: 2026-08
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from models import IN_STORE, ONLINE, Item, Purchase
from storage import now_iso

log = logging.getLogger("target_receipts.site")

# ---------------------------------------------------------------------------
# URLs
# ---------------------------------------------------------------------------

URLS = {
    "home": "https://www.target.com/",
    "orders": "https://www.target.com/orders",
    "account": "https://www.target.com/account",
}

# URL substrings that indicate Target bounced us to a sign-in page.
LOGIN_URL_MARKERS = ["/login", "gsp.target.com", "/co-login", "auth"]

# URL patterns for order/transaction details links (verified 2026-07 via
# Diagnostics/probe-orders.json + probe-instore.json):
#   Online:   /orders/900000000000000
#   In-store: /orders/stores/6203-1005-0171-6207
ORDER_LINK_STORE_RE = re.compile(r"/orders/stores/([A-Za-z0-9\-]+)")
ORDER_LINK_ONLINE_RE = re.compile(r"/orders/(\d{6,})(?:[/?#]|$)")


def parse_order_link(href: str):
    """Classify an /orders/... href. Returns (purchase_type, id) or (None, None)."""
    m = ORDER_LINK_STORE_RE.search(href or "")
    if m:
        return IN_STORE, m.group(1)
    m = ORDER_LINK_ONLINE_RE.search(href or "")
    if m:
        return ONLINE, m.group(1)
    return None, None

# ---------------------------------------------------------------------------
# Accessible names / labels (regex, case-insensitive)
# ---------------------------------------------------------------------------

TAB_NAME = {
    ONLINE: re.compile(r"^\s*online\s*$", re.I),
    IN_STORE: re.compile(r"^\s*in[\s\-]?store\s*$", re.I),
}

LOAD_MORE_RE = re.compile(r"(load more|show more|view more|more orders|more purchases)", re.I)
# Online details: "Receipts & invoices" link. In-store details: "View your
# receipt" button ("View and save your store receipt"). Verified 2026-07.
RECEIPT_SECTION_RE = re.compile(
    r"(receipts?\s*&?\s*(and)?\s*invoices?|view (your |and save )?receipt)", re.I)
PRINT_RECEIPT_RE = re.compile(r"print\s+receipts?", re.I)
GIFT_RECEIPT_RE = re.compile(r"gift\s+receipt", re.I)
INVOICE_RE = re.compile(r"(view|print|download)\s+(detailed\s+)?invoices?", re.I)
SIGN_IN_RE = re.compile(r"^\s*sign\s*in\s*$", re.I)

# Controls that must NEVER be activated (spec sections 9, 25).
FORBIDDEN_CONTROL_RE = re.compile(
    r"(start\s+a\s+return|fix\s+an\s+issue|buy\s+it\s+again|rate\s*(and|&)?\s*review|"
    r"track\s+package|photo\s+confirmation|gift\s+receipt|cancel\s+order|"
    r"payment\s+method|delivery\s+information|add\s+to\s+cart|check\s*out|"
    r"place\s+order|write\s+a\s+review|return\s+or\s+replace)", re.I)

SECURITY_CHALLENGE_MARKERS = [
    "verify your identity", "unusual activity", "suspicious activity",
    "are you a robot", "captcha", "recaptcha", "access denied",
    "verification code", "let's make sure", "prove you're human",
    "security check", "we need to verify",
]

RATE_LIMIT_MARKERS = [
    "too many requests", "rate limit", "try again later",
    "temporarily blocked", "http error 429",
]

# Fallback CSS selectors (lowest priority; keep short and repairable).
# data-test attributes verified 2026-07 (see Diagnostics/probe-*.json).
FALLBACK = {
    "order_card_link": "a[href*='/orders/']",
    "item_link": "a[href*='/p/']",
    "receipt_iframe": "iframe",
    "card_container_online": "[data-test='order-details-link']",
    "card_container_instore": "[data-test='store-order-details-link']",
    "item_row": "[data-test='package-card-item-row']",
    "store_receipt_container": "[data-test='store-pos-order-receipt-container']",
    "receipt_modal_heading": "[data-test='modal-drawer-heading']",
    "tab_online": "[data-test='tabOnline']",
    "tab_instore": "[data-test='tabInstore']",
    "page_ready": ("[data-test='tabOnline'], [data-test='order-details-link'], "
                   "[data-test='store-order-details-link']"),
}

CARD_CONTAINER = {
    ONLINE: FALLBACK["card_container_online"],
    IN_STORE: FALLBACK["card_container_instore"],
}
TAB_FALLBACK = {
    ONLINE: FALLBACK["tab_online"],
    IN_STORE: FALLBACK["tab_instore"],
}

DATE_PATTERNS = [
    # "June 5, 2026" / "Jun 5, 2026"
    (re.compile(r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
                r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|"
                r"Dec(?:ember)?)\.?\s+(\d{1,2}),?\s+(\d{4})", re.I), "mdY"),
    # "06/05/2026"
    (re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b"), "mdy_slash"),
    # "2026-06-05"
    (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"), "iso"),
]

_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}

MONEY_RE = re.compile(r"\$\s*([\d,]+\.\d{2})")
QTY_RE = re.compile(r"\b(?:qty|quantity)\s*:?\s*(\d+)", re.I)
STATUS_WORDS_RE = re.compile(
    r"\b(delivered|shipped|arriving|cancell?ed|return\s+complete|returned|refunded|"
    r"picked\s*up|ready\s+for\s+pickup|processing|preparing|completed|"
    r"return\s+started|purchased)\b", re.I)
STORE_TRIP_RE = re.compile(r"store\s+trip\s+at\s+([^\n]+)", re.I)


def parse_date(text: str) -> Optional[str]:
    """Extract the first date in *text* as YYYY-MM-DD."""
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


# ---------------------------------------------------------------------------
# Session / safety checks
# ---------------------------------------------------------------------------

def looks_signed_out(page) -> bool:
    """Heuristic: bounced to a login URL, or a prominent Sign in prompt."""
    url = (page.url or "").lower()
    if any(marker in url for marker in LOGIN_URL_MARKERS):
        return True
    try:
        # A password field on screen is a strong signal.
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
    """Return a description if a CAPTCHA / verification / block page appears."""
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
    # The purchase history is client-side rendered; wait for real content.
    try:
        page.wait_for_selector(FALLBACK["page_ready"], timeout=30000)
    except Exception:
        log.warning("Purchase-history content did not appear within 30s")
    page.wait_for_timeout(2500)


def select_history_tab(page, purchase_type: str) -> bool:
    """Switch to the Online or In-store purchase-history tab.
    Returns True if a tab control was found and selected."""
    name_re = TAB_NAME[purchase_type]
    clicked = False
    # 1. proper tab roles
    for role in ("tab", "button", "link", "radio"):
        try:
            loc = page.get_by_role(role, name=name_re)
            if loc.count() > 0 and loc.first.is_visible():
                loc.first.click()
                clicked = True
                break
        except Exception:
            continue
    # 2. stable data-test fallback
    if not clicked:
        try:
            loc = page.locator(TAB_FALLBACK[purchase_type])
            if loc.count() > 0 and loc.first.is_visible():
                loc.first.click()
                clicked = True
        except Exception:
            pass
    # 3. visible text fallback
    if not clicked:
        try:
            loc = page.get_by_text(name_re)
            if loc.count() > 0 and loc.first.is_visible():
                loc.first.click()
                clicked = True
        except Exception:
            pass
    if not clicked:
        log.warning("Could not find %s tab on purchase history page", purchase_type)
        return False
    # wait for this tab's cards to render
    try:
        page.wait_for_selector(CARD_CONTAINER[purchase_type], timeout=20000)
    except Exception:
        log.warning("%s cards did not appear within 20s of selecting the tab",
                    purchase_type)
    page.wait_for_timeout(2000)
    return True


# A real year/date-range filter option, and nothing else. Must fullmatch so
# header buttons like "Ship to 12345" can never be mistaken for a filter
# (that exact bug happened 2026-07-23).
YEAR_OPTION_RE = re.compile(
    r"(20\d{2}|(past|last)\s+\d+\s+(months?|years?)|all(\s+time)?)", re.I)


def get_year_options(page) -> List[str]:
    """Return the year / date-range options of a real <select> filter, if one
    exists. Target's current history page uses 'Load more purchases' instead,
    so this usually returns [] — that's fine and handled by the caller."""
    try:
        for select in page.locator("select").all():
            options = [o.strip() for o in select.locator("option").all_inner_texts()]
            candidate = [o for o in options if YEAR_OPTION_RE.fullmatch(o)]
            # only trust selects where most options look like years/ranges
            if candidate and len(candidate) >= max(1, len([o for o in options if o]) - 1):
                return candidate
    except Exception:
        pass
    return []


def select_year_option(page, option_text: str) -> bool:
    """Choose a year / date-range option in the <select> filter that
    get_year_options() found. Select elements only — never clicks buttons."""
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


def load_all_cards(page, purchase_type: str = ONLINE,
                   delay_ms: int = 1500, max_rounds: int = 200) -> int:
    """Scroll / click Load More until the purchase list stops growing.
    Returns the final card count."""
    last_count = -1
    stable_rounds = 0
    for _ in range(max_rounds):
        count = _card_count(page, purchase_type)
        if count == last_count:
            stable_rounds += 1
        else:
            stable_rounds = 0
        last_count = count

        clicked = False
        try:
            btn = page.get_by_role("button", name=LOAD_MORE_RE)
            if btn.count() > 0 and btn.first.is_visible():
                btn.first.scroll_into_view_if_needed()
                btn.first.click()
                clicked = True
        except Exception:
            pass
        if not clicked:
            try:
                page.mouse.wheel(0, 4000)
            except Exception:
                page.keyboard.press("End")
        page.wait_for_timeout(delay_ms)

        if stable_rounds >= 3 and not clicked:
            break
    return _card_count(page, purchase_type)


def _card_count(page, purchase_type: str = ONLINE) -> int:
    try:
        n = page.locator(CARD_CONTAINER[purchase_type]).count()
        if n:
            return n
    except Exception:
        pass
    try:
        return page.locator(FALLBACK["order_card_link"]).count()
    except Exception:
        return 0


@dataclass
class RawCard:
    href: str
    text: str


def collect_cards(page, purchase_type: str = ONLINE) -> List[RawCard]:
    """Collect raw purchase cards: details href + full card text.

    Primary: the per-type card containers (data-test attributes), reading the
    details link inside each. Fallback: scan all /orders/ links and climb to
    the surrounding card for its text.
    """
    cards: List[RawCard] = []
    seen = set()
    try:
        containers = page.locator(CARD_CONTAINER[purchase_type]).all()
    except Exception:
        containers = []
    for c in containers:
        try:
            text = (c.inner_text(timeout=3000) or "").strip()
            href = c.get_attribute("href") or ""
            if not href:
                link = c.locator(FALLBACK["order_card_link"])
                if link.count() > 0:
                    href = link.first.get_attribute("href") or ""
            if not href or href in seen:
                continue
            seen.add(href)
            cards.append(RawCard(href=href, text=text))
        except Exception:
            continue
    if cards:
        return cards

    # fallback: raw link scan
    try:
        links = page.locator(FALLBACK["order_card_link"]).all()
    except Exception:
        links = []
    for link in links:
        try:
            href = link.get_attribute("href") or ""
            kind, _ = parse_order_link(href)
            if kind != purchase_type or href in seen:
                continue
            seen.add(href)
            text = ""
            try:
                text = link.evaluate(
                    """el => {
                        let node = el;
                        for (let i = 0; i < 6 && node.parentElement; i++) {
                            node = node.parentElement;
                            const t = node.innerText || '';
                            if (t.length > 40) return t.slice(0, 2000);
                        }
                        return (node.innerText || '').slice(0, 2000);
                    }""")
            except Exception:
                try:
                    text = link.inner_text(timeout=2000)
                except Exception:
                    text = ""
            cards.append(RawCard(href=href, text=text or ""))
        except Exception:
            continue
    return cards


def card_to_purchase(card: RawCard, purchase_type: str,
                     base_url: str = "https://www.target.com") -> Optional[Purchase]:
    kind, order_number = parse_order_link(card.href)
    if kind != purchase_type or not order_number:
        return None
    # Online cards also print the order number as "#900000000000000";
    # prefer that when it matches, since it's what receipts display.
    m = re.search(r"#\s*([0-9]{6,})", card.text or "")
    if purchase_type == ONLINE and m:
        order_number = m.group(1)
    url = card.href if card.href.startswith("http") else base_url + card.href
    store = ""
    sm = STORE_TRIP_RE.search(card.text or "")
    if sm:
        store = sm.group(1).strip()
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
    """Extract order/transaction details from the open details page.
    Works for both Online orders and In-store transactions; both render as
    /orders/... detail pages with item listings."""
    try:
        body_text = page.locator("body").inner_text(timeout=10000)
    except Exception:
        body_text = ""
    # Drop the site footer ("Order Pickup", "Same Day Delivery"... links would
    # pollute status/fulfillment parsing). The page renders a literal
    # "Footer" landmark line before it.
    body_text = re.split(r"\n\s*Footer\s*\n", body_text, maxsplit=1)[0]

    # Purchase date: prefer an explicit "placed"/"purchased" line.
    placed = None
    for line in body_text.splitlines():
        if re.search(r"(placed|purchased|order date|transaction date)", line, re.I):
            placed = parse_date(line)
            if placed:
                break
    date = placed or parse_date(body_text)
    if date:
        purchase.purchase_date = date

    # Order number: explicit label beats URL slug.
    m = re.search(r"(?:order|receipt|transaction)\s*(?:number|#)\s*:?\s*([A-Za-z0-9\-]{6,})",
                  body_text, re.I)
    if m:
        purchase.order_number = m.group(1)

    # Total: prefer a labeled total line, else the largest money value.
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

    if re.search(r"cancell?ed", body_text, re.I) and re.search(
            r"(order|this purchase)\s+(was\s+)?cancell?ed", body_text, re.I):
        purchase.status = purchase.status or "Canceled"

    if purchase.purchase_type == IN_STORE:
        m = (STORE_TRIP_RE.search(body_text)
             or re.search(r"(store\s*#?\s*\d{3,5}|target\s+[A-Za-z .]+,\s*[A-Z]{2})",
                          body_text, re.I))
        if m and not purchase.store_info:
            purchase.store_info = m.group(1).strip()

    if purchase.purchase_type == ONLINE:
        fm = re.search(r"\b(shipping|delivery|drive\s*up|order\s*pickup|pickup|shipt|same\s*day)\b",
                       body_text, re.I)
        if fm:
            purchase.fulfillment = fm.group(1).title()

    purchase.items = extract_items(page)
    purchase.details_url = page.url
    return purchase


_NON_ITEM_NAME_RE = re.compile(
    r"^(barcode\b|target:|qty\b|\$|unit price|logo\b|at\s|track package|"
    r"view photo|delivered to|package delivered|gift receipt|digital receipt|"
    r"start a return|buy it again|rate & review|get help|view your receipt|"
    r"purchased on|placed at)", re.I)
_LOCATION_LINE_RE = re.compile(r"^[A-Z][A-Za-z .'-]+,\s*[A-Z]{2}(\s+\d{5})?$")
# "Jul 22, 4:48 PM" / "Tue, Jul 21" — date-ish lines with no year
_MONTH_DAY_RE = re.compile(
    r"^((Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*,?\s+)?"
    r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2}\b", re.I)
PRICE_LINE_RE = re.compile(r"^\$\s*[\d,]+(?:\.\d{1,2})?(\s*(unit price|each|/\s*\S+))?$", re.I)


def _clean_item_name(name: str) -> str:
    import html as _html
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
    """Parse item blocks out of an item-row's inner text. Handles both one
    row per item and one row per whole store trip:
        <item name> / $14.89 [unit price] / Qty 1 / <next item> / ...
    """
    items: List[Item] = []
    cur: Optional[Item] = None
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if PRICE_LINE_RE.match(line):
            if cur is not None:
                price = "$" + MONEY_RE.search(line).group(1) if MONEY_RE.search(line) \
                    else "$" + re.sub(r"[^\d.,]", "", line)
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


def extract_items(page) -> List[Item]:
    """Extract line items.

    Primary: data-test='package-card-item-row' rows (both Online and In-store
    details pages use these; verified 2026-07). Each row holds the item image
    (alt = item name), '$X[.XX] [unit price]', and 'Qty N'.
    Fallbacks: /p/ product links, then descriptive image alts.
    """
    items: List[Item] = []
    seen_names = set()

    try:
        rows = page.locator(FALLBACK["item_row"]).all()
    except Exception:
        rows = []
    for row in rows:
        try:
            text = row.inner_text(timeout=3000) or ""
        except Exception:
            continue
        for item in _parse_items_from_text(text):
            if item.name.lower() in seen_names:
                continue
            seen_names.add(item.name.lower())
            items.append(item)
    if items:
        return items

    # fallback 1: /p/ product links
    try:
        links = page.locator(FALLBACK["item_link"]).all()
    except Exception:
        links = []
    for link in links:
        try:
            name = (link.inner_text(timeout=1500) or "").strip()
            if not name:
                # image-only link: use the image alt
                try:
                    name = (link.locator("img").first.get_attribute("alt") or "").strip()
                except Exception:
                    name = ""
            name = _clean_item_name(name)
            if not name or name.lower() in seen_names:
                continue
            context_text = ""
            try:
                context_text = link.evaluate(
                    """el => {
                        let node = el;
                        for (let i = 0; i < 5 && node.parentElement; i++) {
                            node = node.parentElement;
                            const t = node.innerText || '';
                            if (t.length > 20) return t.slice(0, 800);
                        }
                        return '';
                    }""")
            except Exception:
                pass
            qty = ""
            qm = QTY_RE.search(context_text)
            if qm:
                qty = qm.group(1)
            prices = MONEY_RE.findall(context_text)
            unit_price = f"${prices[0]}" if prices else ""
            line_total = f"${prices[-1]}" if len(prices) > 1 else unit_price
            ret = ""
            if re.search(r"\b(returned|refunded|return\s+started)\b", context_text, re.I):
                ret = "Returned"
            status = parse_status(context_text)
            seen_names.add(name.lower())
            items.append(Item(name=name, quantity=qty, unit_price=unit_price,
                              line_total=line_total, status=status, return_status=ret))
        except Exception:
            continue

    if not items:
        # fallback: product images with descriptive alt text
        try:
            for img in page.locator("img[alt]").all():
                alt = (img.get_attribute("alt") or "").strip()
                if len(alt) > 12 and not re.search(r"(logo|icon|target)", alt, re.I) \
                        and alt.lower() not in seen_names:
                    seen_names.add(alt.lower())
                    items.append(Item(name=re.sub(r"\s+", " ", alt)))
        except Exception:
            pass
    return items


# ---------------------------------------------------------------------------
# Receipt access
# ---------------------------------------------------------------------------

def open_receipt_section(page) -> bool:
    """Open 'Receipts & invoices' / 'View receipt' on the details page.
    Returns True if something receipt-related was opened or is present."""
    for role in ("button", "link", "tab"):
        try:
            loc = page.get_by_role(role, name=RECEIPT_SECTION_RE)
            for i in range(min(loc.count(), 5)):
                el = loc.nth(i)
                name = (el.inner_text(timeout=1500) or "")
                if GIFT_RECEIPT_RE.search(name) or FORBIDDEN_CONTROL_RE.search(name):
                    continue
                if el.is_visible():
                    el.click()
                    page.wait_for_timeout(2500)
                    return True
        except Exception:
            continue
    # already-visible receipt content?
    try:
        if page.get_by_text(re.compile(r"store receipt|ereceipt|e-receipt", re.I)).count() > 0:
            return True
    except Exception:
        pass
    return False


def find_print_receipt_controls(page) -> list:
    """All 'Print receipts' controls on the page/popup, excluding gift
    receipts and any forbidden control."""
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
    """Find the hidden iframe from which Target called print() (suppressed by
    our init script — the flag is set on the iframe's own window). Falls back
    to any iframe holding substantial receipt content."""
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
    """If the printable receipt is rendered inside an iframe, return that
    frame, else None."""
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
    """Click a Print receipts control and detect what happened.

    Returns (kind, obj):
      ("download", Download)  - a file download started
      ("popup", Page)         - a new tab/popup opened
      ("print_called", Page)  - the page invoked window.print() (suppressed)
      ("navigated", Page)     - same tab navigated to a printable page
      ("inline", Page)        - nothing external; receipt likely inline/iframe
    """
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
        # reset any stale print snapshot from a previous click on this page
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
    """After opening the receipt view, wait until real receipt content is
    present. Returns 'store-receipt', 'print-controls', or '' (unknown)."""
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
    """How many Store Receipt documents this order has. The receipts page
    labels them 'Store Receipt 1 of N'."""
    try:
        body = page.locator("body").inner_text(timeout=5000)
        m = re.search(r"store receipt\s*\d+\s*of\s*(\d+)", body, re.I)
        if m:
            return max(1, int(m.group(1)))
    except Exception:
        pass
    return 1
