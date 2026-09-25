"""ALL lowes.com selectors, URL patterns, and page behavior live here.

When Lowe's changes its website, repair this file only.

How Lowe's works, mapped against a signed-in account on 2026-09-25:

* The purchase history is ``https://www.lowes.com/mylowes/orders``, titled
  "Purchase History". It holds online orders and store purchases in one
  list, five to a page. A range menu ("Most Recent", "Last 30 days",
  "Last 6 months", a year each back to 2023, "All") writes itself into
  the address as ``?show=all``, and a page is ``&page=N``, so the whole
  history is read by address and nothing on it is pressed. The list is
  drawn by the page, not fetched as JSON, and a page read too soon is
  empty, so each one is waited on until its cards are there.
* A card reads ``Order Date: Jul 2, 2026``, the total, points earned,
  ``Transaction #308519729`` for a store purchase or
  ``Order #300901198261316402`` for an online one, then its items and a
  status (Completed, Delivered, Canceled, Returned). Its "View Details"
  link is ``/mylowes/orders/details?t=<id>&s=<session token>``. The
  token changes with every load and a stale one sends you back to the
  list, while ``?t=<id>`` alone opens the purchase, so that is what is
  kept.
* The **details page is the receipt**. Its heading is the number, then
  "Placed July 2, 2026" and the total, the store's name and address (or
  the delivery address), each item with its item and model numbers, unit
  price, quantity and any discount, the payment method's last four
  digits, and an Order Summary ending in "Total Billed". A hidden
  ``orderdetails-print-container`` is what "Print Details" prints, and it
  leaves out the card, so the visible block is isolated and printed
  instead. "Print Details" is never pressed.

SAFETY (this is a shopping account with a card on file):
  This module is strictly READ-ONLY. It opens the history and details
  pages and saves what Lowe's already rendered. Nothing is clicked. The
  details page carries Start a Return, Buy it Again, Track Package, Write
  a Review and, on an open order, controls that cancel or change it, and
  FORBIDDEN_CONTROL_RE refuses every one of them for the diagnostics and
  the repo-wide guard tests.

Site layer verified working against the live site: 2026-09-25
"""
from __future__ import annotations

import base64
import html as _html
import logging
import re
from dataclasses import dataclass
from typing import List, Optional
from urllib.parse import parse_qs, urlsplit

# Everything on its way into a diagnostic file goes through here.
from paperpull_core.redact import redact, set_private_words  # noqa: F401

from paperpull_core.models import IN_STORE, ONLINE, Item, Purchase
from paperpull_core.urls import is_safe_url as _host_allows
from paperpull_core.dates import checked as _checked_date
from storage import now_iso

log = logging.getLogger("lowes_receipts.site")

# ---------------------------------------------------------------------------
# URLs
# ---------------------------------------------------------------------------

BASE = "https://www.lowes.com"
ORDERS_URL = f"{BASE}/mylowes/orders"
DETAILS_URL = f"{BASE}/mylowes/orders/details"
URLS = {
    "home": ORDERS_URL,
    "orders": ORDERS_URL,
    "account": f"{BASE}/mylowes",
}

LOGIN_URL_MARKERS = ["/login", "/signin", "/sign-in", "/u/login", "/authenticate",
                     "/mfa", "/verification", "identity.lowes.com"]


def orders_url(page_no: int = 1) -> str:
    """The whole history, one page of it. "All" is a value of the range
    menu, and the menu writes it into the address."""
    return f"{ORDERS_URL}?page={page_no}&show=all" if page_no > 1 else f"{ORDERS_URL}?show=all"


def details_url(t: str) -> str:
    return f"{DETAILS_URL}?t={t}"


def details_id(href: str) -> str:
    """The ``t`` of a View Details link, the purchase's own id, which opens
    its page without the session token that goes stale."""
    try:
        t = (parse_qs(urlsplit(href or "").query).get("t") or [""])[0]
    except ValueError:
        return ""
    if not t or len(t) > 80 or not re.fullmatch(r"[A-Za-z0-9+/=_-]+", t):
        return ""
    try:
        base64.b64decode(t + "=" * (-len(t) % 4), validate=False)
    except Exception:
        return ""
    return t


# ---------------------------------------------------------------------------
# Guards. Nothing here is clicked, but the diagnostics grade every control
# and the repo-wide tests hold every app to the same standard.
# ---------------------------------------------------------------------------
FORBIDDEN_CONTROL_RE = re.compile(
    r"(buy\s+(it\s+)?again|add\s+to\s+(cart|list)|checkout|reorder|subscribe|"
    r"start\s+a\s+return|\breturn\b|cancel|edit\s+(quantity|order)|add\s+(new\s+)?item|"
    r"change\s+(store|delivery|pickup)|reschedule|haul\s*away|track\s+package|"
    r"write\s+a\s+review|\breview\b|\brat(e|ing)\b|protection\s+plan|"
    r"pay\s+now|\bpay\b|payment|apply\s+now|credit\s+center|redeem|rewards?\b|"
    r"add\s+existing\s+receipt|search\s+store\s+purchase|"
    r"delete|remove|sign\s+out|log\s+out|chat|feedback)", re.I)

try:
    from paperpull_core.controls import SETTINGS_CONTROL_RE as _SHARED_SETTINGS
    FORBIDDEN_CONTROL_RE = re.compile(
        "(?:%s)|(?:%s)" % (FORBIDDEN_CONTROL_RE.pattern, _SHARED_SETTINGS.pattern),
        re.I)
except Exception:  # the shared core is optional at import time
    pass

SAFE_DOC_CONTROL_RE = re.compile(
    r"(view\s+details|order\s+details|purchase\s+history|orders\s+&\s+purchases|"
    r"go\s+to\s+(next|previous)\s+page|^\d{1,3}$)", re.I)

SECURITY_CHALLENGE_MARKERS = [
    "press and hold", "verify you are a human", "verify you are human",
    "are you a robot", "access denied", "access to this page has been denied",
    "enter the verification code", "enter the code we sent",
    "checking your browser before accessing",
]

RATE_LIMIT_MARKERS = [
    "too many requests", "rate limit", "temporarily blocked", "http error 429",
]

FALLBACK = {
    "details_link": "a[href*='/mylowes/orders/details']",
    "page_ready": "a[href*='/mylowes/orders/details']",
    "print_page_body": "body",
}

CARD_NUMBER_RE = re.compile(r"\b(Order|Transaction)\s*#\s*(\d{5,24})\b")
MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
DATE_RE = re.compile(r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
                     r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|"
                     r"Dec(?:ember)?)\.?\s+(\d{1,2}),?\s+(\d{4})", re.I)
MONEY_RE = re.compile(r"\$\s*([\d,]+\.\d{2})")
STATUS_RE = re.compile(r"^(Completed|Delivered|Shipped|Canceled|Cancelled|Returned|"
                       r"In Progress|Processing|Ready for Pickup|Picked Up|Partially Returned)$",
                       re.I | re.M)


def _read_date(text: str) -> Optional[str]:
    m = DATE_RE.search(text or "")
    if not m:
        return None
    try:
        return f"{int(m.group(3)):04d}-{MONTHS[m.group(1)[:3].lower()]:02d}-{int(m.group(2)):02d}"
    except (KeyError, ValueError):
        return None


def parse_date(text):
    """The date this provider's page is showing, as YYYY-MM-DD, refused when
    it names a day that does not exist."""
    return _checked_date(_read_date(text), None)


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
    """Names the check, code or throttling page on screen, or None. Only
    when no purchase is showing, since a page's scripts can carry any of
    these words on a normal day."""
    try:
        if page.locator(FALLBACK["details_link"]).count() > 0:
            return None
        body = page.locator("body").inner_text(timeout=5000)
        if "Total Billed" in body:
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


# ---------------------------------------------------------------------------
# Purchase history
# ---------------------------------------------------------------------------

EMPTY_RE = re.compile(r"(no|don.t\s+have\s+any|haven.t\s+(placed|made)\s+any)\s+(orders|purchases)", re.I)


def goto_orders(page, page_no: int = 1, wait_ms: int = 15000) -> int:
    """Open one page of the whole history and wait until its cards are
    drawn. The page arrives before its list does, and read too soon it
    looks empty, which once made a nine-page history look like five.
    Returns how many cards are showing."""
    page.goto(orders_url(page_no), wait_until="domcontentloaded", timeout=60000)
    waited = 0
    while waited < wait_ms:
        page.wait_for_timeout(500)
        waited += 500
        try:
            n = page.locator(FALLBACK["details_link"]).count()
        except Exception:
            n = 0
        if n:
            page.wait_for_timeout(800)   # the rest of the five arrive together
            return page.locator(FALLBACK["details_link"]).count()
        if waited >= 4000 and history_state(page) == "empty":
            return 0
    return 0


def history_state(page) -> str:
    """"empty" when the page says there are no purchases, else ""."""
    try:
        text = page.locator("body").inner_text(timeout=5000)
    except Exception:
        return ""
    return "empty" if EMPTY_RE.search(text or "") else ""


def page_count(page) -> int:
    """The highest page number the pager shows, or 1."""
    try:
        nums = page.evaluate(
            "() => [...document.querySelectorAll('button,a')]"
            ".map(b => (b.innerText || '').trim()).filter(t => /^\\d{1,3}$/.test(t)).map(Number)")
    except Exception:
        nums = []
    return max(nums or [1])


@dataclass
class RawCard:
    href: str
    text: str
    number: str
    kind: str
    t: str = ""
    label: str = "Order Date"


# A card is not one element. The list is a flat run of rows, a header row
# (the date, the total, the number and View Details) and then the item and
# status rows, one purchase after another in one shared container, and a
# header's rows are not always nested alike. Climbing from each link found
# four purchases on a page of five. So the list is read the way a person
# reads it, as text split at each header, "Order Date: Jul 2, 2026 $76.28"
# for a purchase and "Return Initiated: Jun 13, 2025 $39.10" for a return,
# and the View Details links are paired with the headers in order.
# The amount follows the date on the same line on the live page, and on the
# next one when the date is drawn as a block of its own, so either is read.
_CARD_HEAD = r"^[ \t]*[A-Z][A-Za-z ]{2,30}:[ \t]*[A-Z][a-z]{2,8}\.?[ \t]+\d{1,2},[ \t]*\d{4}\s*\$"
_COLLECT_CARDS_JS = r"""
(headSource) => {
  const HEAD = new RegExp(headSource, 'm');
  const body = document.body.innerText || '';
  const start = body.search(HEAD);
  let end = body.search(/Your online order history can.t be used/i);
  if (end < 0 || end < start) end = body.length;
  const region = start < 0 ? '' : body.slice(start, end);
  const segs = [];
  let rest = region;
  while (rest) {
    const next = rest.slice(1).search(HEAD);
    const cut = next < 0 ? rest.length : next + 1;
    segs.push(rest.slice(0, cut));
    rest = rest.slice(cut);
  }
  const links = [...document.querySelectorAll("a[href*='/mylowes/orders/details']")]
    .filter(a => a.getClientRects().length).map(a => a.href || a.getAttribute('href') || '');
  return {segs: segs.map(s => s.trim().slice(0, 2000)), links};
}
"""
_CARD_HEAD_RE = re.compile(r"^\s*([A-Z][A-Za-z ]{2,30}):\s*([A-Z][a-z]{2,8}\.?\s+\d{1,2},\s*\d{4})\s*(\$[\d,]+\.\d{2})")


def pair_cards(segs: List[str], links: List[str]) -> List[RawCard]:
    """Headers and links, paired in order, and only when they agree.

    A page whose headers and links do not come out the same in number is
    not guessed at, since pairing the wrong link with a purchase would
    save one purchase's receipt under another's name. An online order's
    link carries its own number, base64 in ``t``, and must match it."""
    if len(segs) != len(links):
        log.warning("History page has %d purchase headers and %d details links; "
                    "not pairing them", len(segs), len(links))
        return []
    cards = []
    for seg, href in zip(segs, links):
        m = CARD_NUMBER_RE.search(seg)
        head = _CARD_HEAD_RE.match(seg)
        t = details_id(href)
        if not m or not head or not t:
            continue
        kind, number = m.group(1), m.group(2)
        if kind == "Order":
            try:
                decoded = base64.b64decode(t + "=" * (-len(t) % 4)).decode("ascii", "replace")
            except Exception:
                decoded = ""
            if decoded != number:
                log.warning("A details link does not carry order %s; skipped", number)
                continue
        cards.append(RawCard(href=details_url(t), text=seg, number=number,
                             kind=IN_STORE if kind == "Transaction" else ONLINE,
                             t=t, label=head.group(1).strip()))
    return cards


def collect_cards(page) -> List[RawCard]:
    """Every purchase on the page showing, one per purchase."""
    try:
        raw = page.evaluate(_COLLECT_CARDS_JS, _CARD_HEAD) or {}
    except Exception as e:
        log.warning("Card collection failed: %s", e)
        raw = {}
    return pair_cards(list(raw.get("segs") or []), list(raw.get("links") or []))


# Lines of a card that are not an item's name.
_NOT_A_TITLE_RE = re.compile(
    r"^(view details|write a review|\d stars?|buy it again|track package|subscribe & save|"
    r"\d{1,3}|note:.*|[+-]\s*\d+\s+points|.*%\s+off\b.*|round up donation|"
    r"(order|transaction)\s*#.*|delivered\b.*|return\b.*|we.re working on your refund.*)$", re.I)


def card_to_purchase(card: RawCard) -> Optional[Purchase]:
    """A Purchase from a card. The header's date and amount are the date
    and the total, and a header that names a return makes it one."""
    if not card.number:
        return None
    text = card.text or ""
    head = _CARD_HEAD_RE.match(text)
    date = parse_date(head.group(2)) if head else parse_date(text)
    total = head.group(3) if head else parse_money(text)
    status = ""
    sm = STATUS_RE.search(text)
    if sm:
        status = sm.group(1).title()
    title = ""
    for ln in text.splitlines()[1:]:
        ln = ln.strip()
        if len(ln) >= 6 and re.search(r"[A-Za-z]{3}", ln) and not _NOT_A_TITLE_RE.match(ln) \
                and not STATUS_RE.match(ln) and not MONEY_RE.search(ln):
            title = _html.unescape(ln)
            break
    returned = card.label.lower().startswith("return")
    return Purchase(
        purchase_type=card.kind,
        purchase_date=date or "",
        order_number=card.number,
        total=total,
        status="Returned" if returned and not status else status,
        store_info="Lowe's",
        details_url=card.href,
        receipt_url=card.href,
        items=[Item(name=title[:300], quantity="1")] if title else [],
        document_type="Return" if returned else "Receipt",
        discovered_at=now_iso(),
    )


_HISTORY_SURVEY_JS = r"""
() => {
  const NUM = /\b(Order|Transaction)\s*#\s*\d{5,24}\b/g;
  const text = document.body.innerText || '';
  const kinds = {Order: 0, Transaction: 0};
  for (const m of text.matchAll(NUM)) kinds[m[1]] += 1;
  const pager = [...document.querySelectorAll('button,a')]
    .map(b => (b.innerText || '').trim()).filter(t => /^\d{1,3}$/.test(t)).map(Number);
  return {
    details_links: document.querySelectorAll("a[href*='/mylowes/orders/details']").length,
    order_numbers: kinds.Order, transaction_numbers: kinds.Transaction,
    order_date_lines: (text.match(/Order Date/gi) || []).length,
    pager_numbers: pager, range_menus: document.querySelectorAll('select').length,
  };
}
"""


def history_survey(page) -> dict:
    """What the history page holds and what this app makes of it. Counts
    and shapes only, and a purchase number, which the filenames carry."""
    out = {"url": redact(page.url or "")}
    try:
        out["page"] = page.evaluate(_HISTORY_SURVEY_JS)
    except Exception as e:
        out["page"] = {"error": str(e)[:120]}
    cards = collect_cards(page)
    out["cards_collected"] = len(cards)
    became = []
    for c in cards:
        p = card_to_purchase(c)
        if p is None:
            continue
        became.append({"id": p.order_number, "kind": p.purchase_type,
                       "date": p.purchase_date or "no date", "total": "yes" if p.total else "no",
                       "status": p.status or "none"})
    out["purchases"] = became[:25]
    return out


# ---------------------------------------------------------------------------
# Details page = the receipt
# ---------------------------------------------------------------------------

def on_details_page(page) -> bool:
    return "/mylowes/orders/details" in (page.url or "")


def wait_for_details(page, timeout_ms: int = 30000) -> bool:
    """The details page draws its shell first. "Total Billed" is the last
    line of the receipt, so its arrival is the mark."""
    try:
        page.wait_for_function("() => /Total Billed/i.test(document.body.innerText)",
                               timeout=timeout_ms)
        page.wait_for_timeout(1000)
        return True
    except Exception:
        log.warning("Details page did not fill in within %dms", timeout_ms)
        return False


def goto_details(page, purchase: Purchase) -> None:
    """Open the purchase's details page from its stored address.

    A stored address that is not a Lowe's details page is never followed.
    An online order's id is its order number in base64, so its page can be
    rebuilt from the number. A store purchase's id cannot, so the history
    is opened instead, and the heading check before anything is saved
    refuses it rather than filing the wrong page."""
    url = purchase.details_url if is_safe_url(purchase.details_url or "") else ""
    if not url or "/mylowes/orders/details" not in url or not details_id(url):
        if purchase.purchase_type == ONLINE and re.fullmatch(r"\d{5,24}", purchase.order_number or ""):
            url = details_url(base64.b64encode(purchase.order_number.encode()).decode())
        else:
            log.warning("No usable details address for %s", purchase.order_number)
            url = ORDERS_URL
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    wait_for_details(page)


# The details page's heading. A purchase reads "Transaction # 308519729" or
# "Order #300901198261316402", and a return reads "Order Details
# 203274163250910134", with no "#" at all.
DETAILS_HEADING_RE = re.compile(r"\b(?:(?:Order|Transaction)\s*#|Order Details)\s*(\d{5,24})\b")


def details_number(page) -> str:
    """The number in the details page's own heading."""
    try:
        body = page.locator("body").inner_text(timeout=8000)
    except Exception:
        return ""
    m = DETAILS_HEADING_RE.search(body or "")
    return m.group(1) if m else ""


def receipt_is_present(page) -> bool:
    try:
        body = page.locator("body").inner_text(timeout=8000)
    except Exception:
        return False
    return bool(body and DETAILS_HEADING_RE.search(body) and re.search(r"Total Billed", body, re.I))


ITEM_NUMBER_RE = re.compile(r"^Item\s*#\s*(\S+)(?:\s+Model\s*#\s*(\S.*))?$", re.I)
QTY_RE = re.compile(r"^QTY\s*(\d{1,4})$", re.I)
UNIT_RE = re.compile(r"^\$([\d,]+\.\d{2})\s*/\s*ea\.?", re.I)


def extract_items(body: str) -> List[Item]:
    """Each item is its name on one line, then "Item #146675 Model #140",
    "$17.98 /ea.", "QTY 1", then its line total and any saving."""
    lines = [ln.strip() for ln in (body or "").splitlines() if ln.strip()]
    items: List[Item] = []
    for i, ln in enumerate(lines):
        if not ITEM_NUMBER_RE.match(ln) or i == 0:
            continue
        name = _html.unescape(lines[i - 1])
        if ITEM_NUMBER_RE.match(name) or MONEY_RE.search(name):
            continue
        item = Item(name=name[:300], quantity="1")
        # The five star lines of "Write a Review" sit between the quantity
        # and the amounts, so they are passed over rather than counted.
        after = [x for x in lines[i + 1:i + 20] if not re.fullmatch(r"\d Stars?", x, re.I)]
        for k, nxt in enumerate(after[:9]):
            # The item ends where the summary or the payment starts, or
            # where the next item's name does, and not a line later, or
            # the last item's total is the tax (a test caught exactly that).
            if re.match(r"^(order summary|subtotal|tax|total billed|payment method)\b", nxt, re.I):
                break
            if k + 1 < len(after) and ITEM_NUMBER_RE.match(after[k + 1]):
                break
            um = UNIT_RE.match(nxt)
            if um and not item.unit_price:
                item.unit_price = "$" + um.group(1)
                continue
            qm = QTY_RE.match(nxt)
            if qm:
                item.quantity = qm.group(1)
                continue
            if re.fullmatch(r"\$[\d,]+\.\d{2}", nxt):
                item.line_total = nxt       # the last amount before the next item wins
            if ITEM_NUMBER_RE.match(nxt):
                break
        items.append(item)
    return items


def extract_details(page, purchase: Purchase) -> Purchase:
    """Read the details page. "Placed July 2, 2026" is the date and "Total
    Billed" the total. A store purchase names its store under the status."""
    try:
        body = page.locator("body").inner_text(timeout=10000)
    except Exception:
        body = ""
    m = re.search(r"Placed\s+([A-Za-z]{3,9}\.?\s+\d{1,2},?\s+\d{4})", body)
    date = parse_date(m.group(1)) if m else None
    if date:
        purchase.purchase_date = date
    m = re.search(r"Total Billed\s*(\$[\d,]+\.\d{2})", body)
    if m:
        purchase.total = m.group(1)
    sm = re.search(r"^([A-Z][\w.' -]{1,40} Lowe's)$", body, re.M)
    if sm and purchase.purchase_type == IN_STORE:
        purchase.store_info = sm.group(1)
    st = STATUS_RE.search(body)
    if st:
        purchase.status = st.group(1).title()
    items = extract_items(body)
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


# The smallest VISIBLE block holding both the number and "Total Billed".
# The page also keeps a hidden print copy, the smallest of all, which
# leaves out the card and printed as a blank page when it was taken.
_ISOLATE_RECEIPT_JS = r"""
() => {
  const want = (t) => /((Order|Transaction)\s*#|Order Details)\s*\d{5,}/.test(t) && /Total Billed/i.test(t);
  let best = null, bestLen = Infinity;
  for (const el of document.querySelectorAll('div,section,main,article')) {
    const t = el.innerText || '';
    const r = el.getBoundingClientRect();
    if (r.width > 0 && r.height > 0 && t.length < bestLen && want(t)) { best = el; bestLen = t.length; }
  }
  if (!best) return false;
  let el = best;
  while (el && el.parentElement && el !== document.body) {
    for (const s of Array.from(el.parentElement.children)) if (s !== el) s.style.display = 'none';
    el = el.parentElement;
  }
  // Controls and the reviews are not part of a receipt, nor is the note
  // about reordering, which alone ran onto a second page.
  for (const x of best.querySelectorAll('button, a, [role=button], p, div, span')) {
    const t = (x.innerText || x.getAttribute('aria-label') || '').trim();
    if (x.tagName === 'BUTTON' || x.getAttribute('role') === 'button' ||
        /^(write a review|buy it again|track package|start a return|print details|subscribe & save)$/i.test(t) ||
        (/^Note:/.test(t) && t.length < 200)) {
      x.style.display = 'none';
    }
  }
  const w = Math.max(best.scrollWidth, best.getBoundingClientRect().width);
  document.body.style.zoom = String(Math.min(1, Math.max(0.45, 736 / (w + 16))));
  window.scrollTo(0, 0);
  return true;
}
"""


def isolate_receipt(page) -> bool:
    """Leave only the receipt block on the page for printing. A display
    change in the local page, gone on the next navigation."""
    try:
        ok = bool(page.evaluate(_ISOLATE_RECEIPT_JS))
    except Exception as e:
        log.warning("Receipt isolation failed: %s", e)
        return False
    if ok:
        page.wait_for_timeout(300)
    else:
        log.warning("Could not find the receipt block to isolate")
    return ok


def open_receipt_section(page) -> bool:
    """Nothing to expand, the receipt is the page."""
    if not receipt_is_present(page):
        wait_for_details(page, timeout_ms=15000)
    return receipt_is_present(page)


# --- receipt-access hooks Lowe's does not need ------------------------------

def find_print_receipt_controls(page) -> list:
    """Print Details opens the print dialog and is never pressed."""
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
ALLOWED_HOSTS = {"lowes.com"}


def is_safe_url(url: str) -> bool:
    """True only for an https URL on one of this provider's own hosts.

    The check itself lives in the core, so all of them answer the same way.
    This app keeps the hosts, which is the part that really is its own."""
    return _host_allows(url, ALLOWED_HOSTS)
