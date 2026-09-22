"""ALL eBay selectors, URL patterns, and page behavior live here.

When eBay changes its website, repair this file only.

How eBay works, mapped against a signed-in account on 2026-09-21:

* The purchase history is ``https://www.ebay.com/mye/myebay/purchase``,
  a list of order cards. Each card holds one line item's title, the
  order's status ("Delivered", "Shipped", "Canceled"), a line reading
  ``Order date:Sep 13, 2026 Order total:US $314.00 Order number:
  25-12345-67890``, the seller ("Sold by: name"), and a "View order
  details" link to ``https://order.ebay.com/ord/show?orderId=...&
  purchaseOrderId=...``. An order with several items has several cards
  sharing one order number.
* The list is filtered by year through a menu ("All", "Last 60 Days",
  then one entry per year). "All" is not all, it is this year and the
  three before it. The filter is a URL parameter with a vocabulary of
  words, ``filter=year_filter:THIS_YEAR``, ``LAST_YEAR``,
  ``TWO_YEARS_AGO`` and so on, which is how discovery walks every year
  back to the first one that is empty. A page's list lazy-loads a little
  on scroll, so each year is scrolled until the count settles. The
  ``page=`` parameter does nothing.
* The **order-details page IS the receipt**. It shows Order info (time
  placed, order number, total, seller), Delivery info, Item info (each
  item's title, unit price, item number, condition), the shipping address
  and Payment info (the payment method with the email masked, item
  total, shipping, tax, order total). There is a "Printer friendly page"
  button that did nothing under automation, and no print stylesheet, so
  ``isolate_receipt`` hides everything outside the details block (the
  ``div.main-regions`` holding Order info through Payment info) and the
  page is printed to PDF as it stands, scaled to the printable width
  because the layout is a fixed 1220px wide whatever the viewport.
* Some orders from 2019 and before get eBay's own "Order not found" page
  every time. Their history card is isolated and printed instead.
* Opening a few hundred details pages in one day trips a daily limit,
  after which every details URL lands on ``pages.ebay.com/limitexceeded``
  until the next day. ``hit_daily_limit`` sees that, the run stops with
  its progress saved, and ``--resume`` picks up the next day. The
  purchase history is not limited the same way.

eBay also lists purchases through the buyer's own Payments area, which
this app does not touch. Nothing here clicks an action control. Capture is
navigation plus printToPDF, so ``FORBIDDEN_CONTROL_RE`` exists as a guard
for the diagnostics helpers and the repo-wide guard tests.

Round two (#44, 2026-09-22). A tester's pilot found two of the nine
orders he made this year. Two things could hide an order, and both are
now covered: a card whose "View order details" link is missing or points
somewhere else (a card is now taken from the "Order number" line, and
the details address is built from the id), and a list that had not
finished lazy-loading when it was read (the scroll is more patient, it
waits for the page to stop growing as well as for the count to settle,
and it presses any "Show more" control it finds).

Site layer verified working against the live site: 2026-09-21
"""
from __future__ import annotations

import html as _html
import logging
import re
from dataclasses import dataclass
from datetime import date as _date
from typing import List, Optional
from urllib.parse import parse_qs, urlsplit

from paperpull_core.models import ONLINE, Item, Purchase
from storage import now_iso

log = logging.getLogger("ebay_receipts.site")

# ---------------------------------------------------------------------------
# URLs
# ---------------------------------------------------------------------------

BASE = "https://www.ebay.com"
ORDERS_URL = f"{BASE}/mye/myebay/purchase"
DETAILS_BASE = "https://order.ebay.com/ord/show"
URLS = {
    "home": ORDERS_URL,
    "orders": ORDERS_URL,
    "account": f"{BASE}/mye/myebay/summary",
}

LOGIN_URL_MARKERS = ["/signin", "/sign-in", "/login", "signin.ebay", "/ws/ebayisapi.dll?signin",
                     "/authenticate", "/mfa", "/verification"]

# The year filter's vocabulary, as the site's own menu writes it into the
# URL. Index 0 is this year.
YEAR_FILTER_WORDS = ["THIS_YEAR", "LAST_YEAR", "TWO_YEARS_AGO", "THREE_YEARS_AGO", "FOUR_YEARS_AGO",
                     "FIVE_YEARS_AGO", "SIX_YEARS_AGO", "SEVEN_YEARS_AGO", "EIGHT_YEARS_AGO",
                     "NINE_YEARS_AGO", "TEN_YEARS_AGO"]


def year_filter_word(year: int, today: Optional[_date] = None) -> Optional[str]:
    """The filter word for a calendar year, or None when it is further back
    than the vocabulary reaches."""
    back = (today or _date.today()).year - year
    if 0 <= back < len(YEAR_FILTER_WORDS):
        return YEAR_FILTER_WORDS[back]
    return None


def orders_url(year: Optional[int] = None) -> str:
    word = year_filter_word(year) if year else None
    return f"{ORDERS_URL}?filter=year_filter:{word}" if word else ORDERS_URL


# An order id is "25-12345-67890" today. Orders from 2018 and before carry
# the older "123456789012-1234567890123!1234" form, an item and transaction
# pair, and their cards show "Order number:12345-67890". The link's
# orderId is the identity in both cases.
ORDER_ID_RE = re.compile(r"\b(\d{2}-\d{5}-\d{5}|\d{5,}-\d{5,})\b")
ORDER_ID_TOKEN_RE = re.compile(r"^[0-9A-Za-z]+(?:-[0-9A-Za-z]+)*(?:![0-9A-Za-z]+)?$")
ORDER_ID_IN_URL_RE = re.compile(r"[?&]orderId=([0-9A-Za-z!-]+)", re.I)


def order_details_url(order_id: str, purchase_order_id: str = "") -> str:
    url = f"{DETAILS_BASE}?orderId={order_id}"
    if purchase_order_id:
        url += f"&purchaseOrderId={purchase_order_id}"
    return url


def parse_order_link(href: str):
    """(ONLINE, orderId, purchaseOrderId) from a View order details link."""
    try:
        q = parse_qs(urlsplit(href or "").query)
    except ValueError:
        return None, None, None
    oid = (q.get("orderId") or [""])[0]
    if not oid or len(oid) > 60 or not ORDER_ID_TOKEN_RE.match(oid):
        return None, None, None
    return ONLINE, oid, (q.get("purchaseOrderId") or [""])[0]


# ---------------------------------------------------------------------------
# Guards. Nothing here is clicked, but the diagnostics grade every control
# and the repo-wide tests hold every app to the same standard.
# ---------------------------------------------------------------------------
FORBIDDEN_CONTROL_RE = re.compile(
    r"(buy\s+(it\s+)?again|buy\s+now|add\s+to\s+(cart|watchlist)|checkout|place\s+(bid|order)|"
    r"\bbid\b|make\s+(an\s+)?offer|pay\s+now|\bpay\b|payment|resell|sell\s+(one|it)|"
    r"leave\s+feedback|return\s+(this\s+)?item|start\s+a\s+return|report\s+(item|seller|a\s+problem)|"
    r"contact\s+seller|cancel\s+(order|item)|hide\s+order|unhide|"
    r"delete|remove|subscribe|redeem|apply\s+now|\bsell\b|list\s+(an\s+)?item)", re.I)

try:
    from paperpull_core.controls import SETTINGS_CONTROL_RE as _SHARED_SETTINGS
    FORBIDDEN_CONTROL_RE = re.compile(
        "(?:%s)|(?:%s)" % (FORBIDDEN_CONTROL_RE.pattern, _SHARED_SETTINGS.pattern),
        re.I)
except Exception:  # the shared core is optional at import time
    pass

SAFE_DOC_CONTROL_RE = re.compile(
    r"(print|printer\s+friendly|view\s+(receipt|invoice|order\s+details)|order\s+details|"
    r"purchase\s+history|load\s+more|show\s+more|view\s+more)", re.I)

SECURITY_CHALLENGE_MARKERS = [
    "enter the characters you see", "type the characters you see",
    "are you a robot", "robot check", "press and hold",
    "verify you are a human", "verify you are human",
    "checking your browser before accessing",
    "access to this page has been denied",
    "two-step verification", "enter the one time password",
    "enter the one-time password", "enter the otp",
    "enter the verification code", "confirm it's you",
]

RATE_LIMIT_MARKERS = [
    "too many requests", "rate limit", "try again later",
    "temporarily blocked", "http error 429", "request was throttled",
]

# eBay caps how many order-details pages one account may open in a day
# (a few hundred). Past the cap every details URL lands on
# pages.ebay.com/limitexceeded.html with this sentence, until the next
# day. The purchase history itself keeps working.
DAILY_LIMIT_URL_MARKER = "limitexceeded"
DAILY_LIMIT_MARKERS = [
    "exceeded the number of requests allowed in one day",
    "daily limit exceeded",
]


def hit_daily_limit(page) -> bool:
    """True when eBay has answered with its daily request limit page."""
    try:
        if DAILY_LIMIT_URL_MARKER in (page.url or "").lower():
            return True
        hay = (page.title() or "").lower() + "\n" + page.locator("body").inner_text(timeout=5000).lower()[:3000]
    except Exception:
        return False
    return any(m in hay for m in DAILY_LIMIT_MARKERS)

FALLBACK = {
    "order_link": "a[href*='order.ebay.com/ord/show']",
    "order_card": "a[href*='order.ebay.com/ord/show']",
    "page_ready": "a[href*='order.ebay.com/ord/show'], main, [class*='m-ph-card']",
    "invoice_link": "a[href*='order.ebay.com/ord/show']",
    "item_row": "[class*='m-item-card'], [class*='item-card']",
    "item_title": ".main-regions a[href*='/itm/'], .main-regions h3.clipped",
    "next_page": "",  # a year filter and a scroll, no pager
    "print_page_body": "body",
}

DATE_PATTERNS = [
    (re.compile(r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
                r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|"
                r"Dec(?:ember)?)\.?\s+(\d{1,2}),?\s+(\d{4})", re.I), "mdY"),
    (re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b"), "mdy_slash"),
    (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"), "iso"),
]
_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}

MONEY_RE = re.compile(r"(?:US\s*)?\$\s*([\d,]+\.\d{2})")
STATUS_WORDS_RE = re.compile(
    r"\b(delivered|shipped|in\s+transit|out\s+for\s+delivery|arriving|"
    r"cancell?ed|returned|refunded|return\s+started|refund\s+issued|"
    r"processing|paid|awaiting\s+shipment|order\s+placed|unpaid|payment\s+failed)\b", re.I)


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
    """Names the CAPTCHA, passcode or throttling prompt on screen, or None.
    Visible text only, and only when the purchase list is not there, since
    a page's scripts can carry every one of these strings on a normal
    day."""
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
# Purchase history
# ---------------------------------------------------------------------------

_ORDER_LINK_COUNT_JS = "() => document.querySelectorAll(\"a[href*='order.ebay.com/ord/show']\").length"


def _order_link_count(page) -> int:
    try:
        return int(page.evaluate(_ORDER_LINK_COUNT_JS) or 0)
    except Exception:
        return 0


_SHOW_MORE_RE = re.compile(r"^\s*(show|see|load)\s+(more|older)( orders| purchases)?\s*$", re.I)


def _press_show_more(page) -> bool:
    """A "Show more" the list offers instead of loading on scroll."""
    try:
        loc = page.get_by_role("button", name=_SHOW_MORE_RE).or_(page.get_by_role("link", name=_SHOW_MORE_RE))
        if loc.count() and loc.first.is_visible():
            label = (loc.first.inner_text(timeout=800) or "").strip()
            if is_safe_control(label):
                loc.first.click(timeout=5000)
                return True
    except Exception:
        pass
    return False


def _order_count(page) -> int:
    """Orders on the page, by link and by order number, since a card
    without a link is still an order (#44)."""
    try:
        return int(page.evaluate(
            r"""() => { const s = new Set();
               for (const a of document.querySelectorAll("a[href*='order.ebay.com/ord/show']")) {
                 const m = (a.getAttribute('href')||'').match(/[?&]orderId=([0-9A-Za-z!-]+)/); if (m) s.add(m[1]); }
               const t = document.body.innerText || ''; const rx = /order\s*number\s*:?\s*([0-9A-Za-z][0-9A-Za-z!-]{4,})/gi;
               let m; while ((m = rx.exec(t))) s.add(m[1]);
               return s.size; }"""))
    except Exception:
        return _order_link_count(page)


def scroll_all_orders(page, max_rounds: int = 25, delay_ms: int = 2000,
                      stable_rounds: int = 3) -> int:
    """Scroll until the list stops growing, in orders and in page height,
    pressing any "Show more" it offers. Returns the order count."""
    last = _order_count(page)
    last_height = 0
    stable = 0
    for _ in range(max_rounds):
        try:
            page.mouse.wheel(0, 4000)
            page.wait_for_timeout(delay_ms)
            page.keyboard.press("End")
            page.wait_for_timeout(delay_ms)
            if _press_show_more(page):
                page.wait_for_timeout(delay_ms)
        except Exception:
            break
        now = _order_count(page)
        try:
            height = int(page.evaluate("() => document.body.scrollHeight") or 0)
        except Exception:
            height = last_height
        if now == last and height == last_height:
            stable += 1
            if stable >= stable_rounds:
                break
        else:
            stable = 0
            last = now
            last_height = height
    try:
        page.evaluate("() => window.scrollTo(0, 0)")
    except Exception:
        pass
    return last


def goto_orders(page, year: Optional[int] = None) -> None:
    """Open the purchase history, for one calendar year when given, and
    scroll it until the list settles."""
    page.goto(orders_url(year), wait_until="domcontentloaded", timeout=60000)
    # The list renders a moment after the shell. Wait for an order link
    # itself, since "main" is there at once, and give an empty year the
    # full wait before believing it is empty.
    try:
        page.wait_for_selector(FALLBACK["order_link"], timeout=20000)
    except Exception:
        pass
    page.wait_for_timeout(2500)
    scroll_all_orders(page)


@dataclass
class RawCard:
    href: str
    text: str
    order_id: str
    purchase_order_id: str = ""
    kind: str = ONLINE
    title: str = ""
    seller: str = ""


# A card is the smallest ancestor of a "View order details" link that still
# belongs to ONE order id. The moment a second order's id appears we have
# left the card. An order with several items renders several cards that
# share an id, and the first one seen keeps it.
_COLLECT_CARDS_JS = r"""
() => {
  const LINK = "a[href*='order.ebay.com/ord/show']";
  const NUM = /order\s*number\s*:?\s*([0-9A-Za-z][0-9A-Za-z!-]{4,})/i;
  const idOf = (l) => { const m = (l.getAttribute('href') || '').match(/[?&]orderId=([0-9A-Za-z!-]+)/); return m ? m[1] : null; };
  const idsIn = (el) => {
    const s = new Set();
    for (const l of el.querySelectorAll(LINK)) { const id = idOf(l); if (id) s.add(id); }
    const t = el.innerText || '';
    let m; const rx = new RegExp(NUM.source, 'gi');
    while ((m = rx.exec(t))) s.add(m[1]);
    return s;
  };
  // Every anchor that names an order, and every element whose own text
  // carries an order number. A card with no details link is still an
  // order, and the details address is built from the number (#44).
  const starts = [];
  for (const a of document.querySelectorAll(LINK)) starts.push({el: a, id: idOf(a), href: a.getAttribute('href') || ''});
  const walk = (el) => {
    for (const c of el.children) {
      const own = Array.from(c.childNodes).filter(n => n.nodeType === 3).map(n => n.textContent).join(' ');
      const m = own.match(NUM);
      if (m) starts.push({el: c, id: m[1], href: ''});
      walk(c);
    }
  };
  walk(document.body);
  const out = [];
  const seen = new Set();
  for (const start of starts) {
    const id = start.id;
    if (!id || seen.has(id)) continue;
    seen.add(id);
    let best = start.el, el = start.el.parentElement;
    while (el && el !== document.body) {
      if (idsIn(el).size > 1) break;
      best = el;
      el = el.parentElement;
    }
    let href = start.href;
    if (!href) {
      const a = best.querySelector(LINK);
      if (a) href = a.getAttribute('href') || '';
    }
    const h3 = best.querySelector('h3');
    const seller = best.querySelector("a[href*='/usr/']");
    out.push({id: id, href: href, text: (best.innerText || '').trim(),
              title: h3 ? h3.innerText.trim() : '', seller: seller ? seller.innerText.trim().split('\n')[0] : ''});
  }
  return out;
}
"""


def collect_cards(page, purchase_type: str = "") -> List[RawCard]:
    """Every order card rendered on the history page, one per order."""
    try:
        raw = page.evaluate(_COLLECT_CARDS_JS) or []
    except Exception as e:
        log.warning("Card collection failed: %s", e)
        raw = []
    cards: List[RawCard] = []
    for r in raw:
        kind, oid, poid = parse_order_link(r.get("href") or "")
        if not oid:
            # No usable link on the card. The order number in its own text
            # is enough, the details page takes it as orderId (#44).
            oid = str(r.get("id") or "").strip()
            poid = ""
            if not oid or len(oid) > 60 or not ORDER_ID_TOKEN_RE.match(oid):
                continue
        cards.append(RawCard(href=order_details_url(oid, poid), text=r.get("text") or "",
                             order_id=oid, purchase_order_id=poid or "", kind=ONLINE,
                             title=(r.get("title") or "").strip(), seller=(r.get("seller") or "").strip()))
    if purchase_type and purchase_type != ONLINE:
        return []
    return cards


def card_to_purchase(card: RawCard, purchase_type: str = "",
                     base_url: str = BASE) -> Optional[Purchase]:
    """A Purchase from a card. The card's own line "Order date:Sep 13,
    2026 Order total:US $314.00 Order number:25-..." carries the date and
    the total, its first line the status."""
    if not card.order_id:
        return None
    text = card.text or ""
    date = ""
    m = re.search(r"order\s+date\s*:?\s*([A-Za-z]{3,9}\.?\s+\d{1,2},?\s+\d{4})", text, re.I)
    if m:
        date = parse_date(m.group(1)) or ""
    if not date:
        date = parse_date(text) or ""
    total = ""
    m = re.search(r"order\s+total\s*:?\s*(?:US\s*)?(\$[\d,]+\.\d{2})", text, re.I)
    total = m.group(1) if m else parse_money(text)
    status = parse_status(text.split("\n", 2)[1] if "\n" in text else text) or parse_status(text)
    return Purchase(
        purchase_type=ONLINE,
        purchase_date=date,
        order_number=card.order_id,
        total=total,
        status=status,
        store_info=card.seller or "eBay",
        details_url=card.href,
        receipt_url=card.href,
        items=[Item(name=card.title[:300], quantity="1")] if card.title else [],
        discovered_at=now_iso(),
    )


# ---------------------------------------------------------------------------
# Details page = the receipt
# ---------------------------------------------------------------------------

HYDRATED_RE = re.compile(r"order\s+number", re.I)


def on_details_page(page) -> bool:
    return "order.ebay.com/ord/show" in (page.url or "")


def wait_for_hydration(page, timeout_ms: int = 45000) -> bool:
    """The details page renders its shell first and fills in the order a
    moment later. "Order number" and "Order total" are the markers."""
    try:
        page.wait_for_function(
            "() => /Order number/i.test(document.body.innerText) && /Order total/i.test(document.body.innerText)",
            timeout=timeout_ms)
        page.wait_for_timeout(800)
        return True
    except Exception:
        log.warning("Order-details page did not hydrate within %dms", timeout_ms)
        return False


def goto_details(page, purchase: Purchase) -> None:
    """Open the order-details page and wait for it to fill in. That page is
    both where the order data is read and what gets saved as the receipt."""
    url = purchase.details_url if is_safe_url(purchase.details_url or "") else ""
    if not url or "orderId=" not in url:
        url = order_details_url(purchase.order_number)
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    wait_for_hydration(page)


# Lines that are labels, not titles. The condition words stand alone on
# their line, so they must match the whole line, else "New UJ-272 ..." and
# "Used Canon lens" would be thrown away with them.
_NON_ITEM_NAME_RE = re.compile(
    r"^(?:order\s+(info|details|number|total)|time\s+placed|total\b|sold\s+by|delivery\s+info|"
    r"tracking|track\s+package|number\b|item\s+info|unit\s+price|item\s+number|quantity|qty|"
    r"no\s+cancellations|buy\s+again|more\s+actions|other\s+actions|"
    r"contact\s+seller|shipping\s+address|payment\s+info|paypal|shipping\b|tax\b|learn\s+more|"
    r"delivered|shipped|paid|arriving|returned|refunded|cancell?ed|printer\s+friendly|"
    r"we\s+automatically|\d+\s+items?$|step\s+completed|-)|"
    r"^(?:used|new|pre-owned|refurbished|open\s+box|for\s+parts)\.?$", re.I)


def _clean_item_name(name: str) -> str:
    name = _html.unescape(re.sub(r"\s+", " ", name or "")).strip()
    if len(name) < 5 or MONEY_RE.search(name) or _NON_ITEM_NAME_RE.search(name):
        return ""
    return name


def extract_items(page) -> List[Item]:
    """Line items on the details page, from the Item info section. Each
    item's title is a line on its own, followed by its price, a unit price
    and an item number. A quantity line, when there is one, reads
    "Quantity 2" or "Qty 2"."""
    try:
        body = page.locator("body").inner_text(timeout=8000)
    except Exception:
        body = ""
    lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
    items: List[Item] = []
    inside = False
    current: Optional[Item] = None
    for i, ln in enumerate(lines):
        if re.match(r"^item\s+info$", ln, re.I):
            inside = True
            continue
        if inside and re.match(r"^(other\s+actions|shipping\s+address|payment\s+info)$", ln, re.I):
            break
        if not inside:
            continue
        qm = re.match(r"^(?:quantity|qty)\s*:?\s*(\d{1,3})$", ln, re.I)
        if qm and current is not None:
            current.quantity = qm.group(1)
            continue
        um = re.match(r"^unit\s+price\s+(\$[\d,]+\.\d{2})$", ln, re.I)
        if um and current is not None:
            current.unit_price = um.group(1)
            continue
        pm = re.match(r"^(?:US\s*)?(\$[\d,]+\.\d{2})$", ln)
        if pm and current is not None:
            if not current.line_total:
                current.line_total = pm.group(1)
            continue
        # A title is the line right before an item's price. The condition,
        # the return policy and the action labels that follow an item are
        # not items, and none of them is followed by a price.
        priced = any(re.match(r"^(?:US\s*)?\$[\d,]+\.\d{2}$", nxt) for nxt in lines[i + 1:i + 3])
        name = _clean_item_name(ln) if priced else ""
        if name and (current is None or name.lower() != (current.name or "").lower()):
            current = Item(name=name[:300], quantity="1")
            items.append(current)
    if items:
        return items
    seen = set()
    try:
        for el in page.locator(FALLBACK["item_title"]).all():
            name = _clean_item_name(el.inner_text(timeout=1200) or "")
            if name and name.lower() not in seen:
                seen.add(name.lower())
                items.append(Item(name=name[:300], quantity="1"))
    except Exception:
        pass
    return items


def extract_details(page, purchase: Purchase) -> Purchase:
    """Read the filled-in details page. It reads, label and value on one
    line separated by a tab:

        Order info
        Time placed    Sep 13, 2026 at 1:00 PM
        Order number   25-12345-67890
        Total          $314.00 (1 item)
        Sold by        seller
        ...
        Payment info
        ...
        Order total    $314.00
    """
    try:
        body = page.locator("body").inner_text(timeout=10000)
    except Exception:
        body = ""
    m = ORDER_ID_RE.search(body)
    if m and not purchase.order_number:
        purchase.order_number = m.group(1)
    m = re.search(r"time\s+placed\s*[\t:]?\s*([A-Za-z]{3,9}\.?\s+\d{1,2},?\s+\d{4})", body, re.I)
    date = parse_date(m.group(1)) if m else None
    if date:
        purchase.purchase_date = date
    total = ""
    for label in (r"order\s+total", r"^total"):
        mm = re.search(label + r"\s*[\t:]?\s*(?:US\s*)?(\$[\d,]+\.\d{2})", body, re.I | re.M)
        if mm:
            total = mm.group(1)
            break
    if total:
        purchase.total = total
    sm = re.search(r"sold\s+by\s*[\t:]?\s*(\S+)", body, re.I)
    if sm:
        purchase.store_info = sm.group(1)
    status = parse_status(body)
    if status:
        purchase.status = status
    if re.search(r"order\s+(was\s+)?cancell?ed|cancell?ed\s+order|this\s+order\s+was\s+cancell?ed", body, re.I):
        purchase.status = "Canceled"
    items = extract_items(page)
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
        page.wait_for_timeout(300)
    except Exception:
        pass


def receipt_is_present(page) -> bool:
    """True when the current page is a filled-in order-details receipt."""
    try:
        body = page.locator("body").inner_text(timeout=8000)
    except Exception:
        return False
    return bool(body and HYDRATED_RE.search(body) and re.search(r"order\s+total", body, re.I))


# The details block is the smallest element holding both "Order info" and
# "Payment info". Everything not on its ancestor path is hidden, a live
# DOM display change only, discarded on the next navigation.
_ISOLATE_RECEIPT_JS = r"""
() => {
  const smallest = (test) => {
    let best = null, bestLen = Infinity;
    for (const el of document.querySelectorAll('div,section,main,article')) {
      const t = el.innerText || '';
      if (t.length < bestLen && test(t)) { best = el; bestLen = t.length; }
    }
    return best;
  };
  let n = smallest(t => /Order info/i.test(t) && /Payment info/i.test(t));
  if (!n) n = smallest(t => /Order number/i.test(t) && /Order total/i.test(t));
  if (!n) return false;
  let el = n;
  while (el && el.parentElement && el !== document.body) {
    for (const s of Array.from(el.parentElement.children)) {
      if (s !== el) s.style.display = 'none';
    }
    el = el.parentElement;
  }
  // The shipment card holds the Item info (title, unit price, item
  // number) at a fixed height with the rest clipped away. Let it grow.
  const st = document.createElement('style');
  st.textContent = '.shipment-info, .shipment-containers, .shipment-container, .shipment-card, ' +
    '.shipment-card-row, .shipment-card-content, .item-container ' +
    '{ height: auto !important; max-height: none !important; overflow: visible !important; }';
  document.head.appendChild(st);
  // Buttons (Buy again, Track package, More actions) are not part of a
  // receipt. Hiding them is a display change in the local page only.
  for (const x of n.querySelectorAll('button')) x.style.display = 'none';
  // The page is a fixed 1220px desktop layout that ignores the viewport,
  // so the right column (the amounts) falls off an 8.5in page. Scale the
  // whole thing to the printable width instead.
  const w = Math.max(n.scrollWidth, n.getBoundingClientRect().width);
  const zoom = Math.min(1, Math.max(0.45, 736 / (w + 16)));
  document.body.style.zoom = String(zoom);
  return true;
}
"""


NOT_FOUND_RE = re.compile(r"order\s+not\s+found|error\s+retrieving\s+your\s+order", re.I)


def order_not_found(page) -> bool:
    """True when eBay answers the details URL with its own "Order not
    found" page. Some orders from 2019 and before do this every time. The
    purchase history still lists them, so their card is the record."""
    try:
        body = page.locator("body").inner_text(timeout=8000)
    except Exception:
        return False
    return bool(body and NOT_FOUND_RE.search(body) and not HYDRATED_RE.search(body))


# The card for one order id on the purchase history page, everything else
# hidden, the same way the details block is isolated.
_ISOLATE_CARD_JS = r"""
(oid) => {
  const LINK = "a[href*='order.ebay.com/ord/show']";
  const idOf = (l) => { const m = (l.getAttribute('href') || '').match(/[?&]orderId=([0-9A-Za-z!-]+)/); return m ? m[1] : null; };
  const idsIn = (el) => { const s = new Set(); for (const l of el.querySelectorAll(LINK)) { const id = idOf(l); if (id) s.add(id); } return s; };
  const a = Array.from(document.querySelectorAll(LINK)).find(l => idOf(l) === oid);
  if (!a) return false;
  let n = a, el = a.parentElement;
  while (el && el !== document.body) {
    if (idsIn(el).size > 1) break;
    n = el;
    el = el.parentElement;
  }
  el = n;
  while (el && el.parentElement && el !== document.body) {
    for (const s of Array.from(el.parentElement.children)) {
      if (s !== el) s.style.display = 'none';
    }
    el = el.parentElement;
  }
  for (const x of n.querySelectorAll('button')) x.style.display = 'none';
  const w = Math.max(n.scrollWidth, n.getBoundingClientRect().width);
  const zoom = Math.min(1, Math.max(0.45, 736 / (w + 16)));
  document.body.style.zoom = String(zoom);
  window.scrollTo(0, 0);
  return true;
}
"""


def show_order_card(page, purchase: Purchase) -> bool:
    """Open the purchase history for the order's year and leave only this
    order's card on the page, for printing when the details page is gone.
    The card carries the date, the item, the total, the seller, the status
    and the order number, which is the whole record eBay still holds."""
    year = None
    m = re.match(r"(\d{4})-", purchase.purchase_date or "")
    if m:
        year = int(m.group(1))
    try:
        goto_orders(page, year)
        ok = bool(page.evaluate(_ISOLATE_CARD_JS, purchase.order_number))
    except Exception as e:
        log.warning("Could not show the history card for %s: %s", purchase.order_number, e)
        return False
    if ok:
        page.wait_for_timeout(300)
    else:
        log.warning("No history card for %s in %s", purchase.order_number, year or "the history")
    return ok


def isolate_receipt(page) -> bool:
    """Strip the site chrome so printToPDF renders only the receipt, and
    scale the fixed-width layout to the page."""
    try:
        ok = bool(page.evaluate(_ISOLATE_RECEIPT_JS))
    except Exception as e:
        log.warning("Receipt isolation failed: %s", e)
        return False
    if ok:
        page.wait_for_timeout(300)
    else:
        log.warning("Could not find the order details block to isolate")
    return ok


def open_receipt_section(page) -> bool:
    """Nothing to expand on eBay, the receipt is the page."""
    if not receipt_is_present(page):
        wait_for_hydration(page, timeout_ms=15000)
    return receipt_is_present(page)


# --- receipt-access hooks eBay does not need -------------------------------

def find_print_receipt_controls(page) -> list:
    """eBay's "Printer friendly page" button did nothing under automation
    and is not needed. Capture is navigation plus printToPDF."""
    return []


def find_invoice_controls(page) -> list:
    """eBay has no separate invoice document for a buyer."""
    return []


def find_printing_frame(page, wait_ms: int = 2000):
    return None


def find_receipt_iframe(page):
    return None


# ---------------------------------------------------------------------------
# Host allowlist. Parsed, never a string prefix.
# ---------------------------------------------------------------------------
ALLOWED_HOSTS = {"ebay.com"}


def is_safe_url(url: str) -> bool:
    """True only for an https URL on one of this provider's own hosts."""
    from urllib.parse import urlparse
    try:
        got = urlparse(url or "")
    except ValueError:
        return False
    if got.scheme != "https" or not got.hostname:
        return False
    if got.username or got.password:
        return False
    host = got.hostname.lower().rstrip(".")
    return any(host == h or host.endswith("." + h) for h in ALLOWED_HOSTS)
