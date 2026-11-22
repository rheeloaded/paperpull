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
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple

from paperpull_core import shared_folder
from paperpull_core import intake
from paperpull_core import page_check as _page_check
from paperpull_core import redirects
from paperpull_core.models import ONLINE, Item, Purchase
from paperpull_core.urls import is_safe_url as _host_allows
from paperpull_core.dates import checked as _checked_date
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


# Amazon order ids: 111-2223333-4445555 (retail) or D01-... (digital).
# A page can print the hyphens as one of Unicode's own (a non-breaking
# hyphen keeps the number on one line), so those are read too, and every id
# the app keeps is written with ASCII hyphens and ASCII digits (order_id_of),
# the way the order's addresses and the saved records write it (#207).
_DASHES = "‐‑‒–—―−﹣－"
_DASH = "[-" + _DASHES + "]"
ORDER_ID_RE = re.compile(r"\b((?:D)?[0-9]{2,3}%s[0-9]{7}%s[0-9]{7})\b" % (_DASH, _DASH))
ORDER_ID_IN_URL_RE = re.compile(r"orderID=((?:D)?[0-9]{2,3}-[0-9]{7}-[0-9]{7})", re.I)
_ORDER_ID_WHOLE_RE = re.compile(r"D?[0-9]{2,3}-[0-9]{7}-[0-9]{7}")
_TO_ASCII = str.maketrans({c: "-" for c in _DASHES})


def order_id_of(text: str) -> str:
    """An order id as the app keeps it, its hyphens ASCII."""
    return (text or "").translate(_TO_ASCII)


def order_ids_in(text: str) -> List[str]:
    """Every order id the text prints, in its order, as the app keeps them."""
    return [order_id_of(m) for m in ORDER_ID_RE.findall(text or "")]

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

# The SECURITY_CHALLENGE_MARKERS that are a sign-in asking for a code, not a
# check that this is a person. Meeting one is a sign-in, so it rests nothing
# (App._rest_after_a_check, #229).
SIGN_IN_MARKERS = ("authentication required", "two-step verification",
                   "enter the one time password", "enter the otp")


def is_robot_check(said: str) -> bool:
    """Whether what detect_security_challenge said is a robot check or a
    rate limit page, rather than a sign-in asking for a code."""
    return bool(said) and not any(m in said.lower() for m in SIGN_IN_MARKERS)

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
    # Amazon's own count of the orders a period holds, "0 orders" for a
    # year with none. It is in span.num-orders, or on some pages in bold in
    # the period menu's label. It is what tells a year with no orders apart
    # from a page that never drew its list.
    "order_count": "span.num-orders, label.time-filter__label b",
    "page_ready": ".order-card, .js-order-card, [data-component='orderCard'], "
                  "span.num-orders, label.time-filter__label b, "
                  "#ordersContainer, .your-orders-content",
    # An order's invoice menu and its order-details link, which name the
    # order on a list drawn without cards (#207). Read by
    # invoice_menu_orders from their data, and counted here so a failure
    # file says whether a list had them.
    "invoice_menu": "[data-a-popover*='invoice/popover']",
    "details_link": "a[href*='order-details']",
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
    (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})(?!\d)"), "iso"),
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


def _parse_date_from_page(text: str) -> Optional[str]:
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


def parse_date(text):
    """The date this provider's page is showing, as YYYY-MM-DD.

    The reading is below, unchanged. This only refuses to believe a result
    that names a day which does not exist, because a reference number is
    shaped like a date and used to be taken for one."""
    return _checked_date(_parse_date_from_page(text), None)


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
# Canceled orders (#114)
# ---------------------------------------------------------------------------

# A canceled order's printable summary names the order and prints no total.
# On amazon.de it is in German whatever ?language= asks for, "Storniert" over
# "Deine Bestellung wurde storniert", or "... wurde vom Verkäufer storniert"
# when the seller canceled (#114, 2026-10). A summary that never filled in
# prints no total either, so no total alone says nothing, and a wrong
# Canceled is final, the receipt never asked for again. So an order is taken
# as canceled only when its own summary says so, in the language of one of
# the stores in MARKETPLACES, and only where nothing on it says otherwise.

# The status alone on its line, the way a shipment's heading prints it.
_CANCELED_STATUS = (
    r"(?:order\s+)?cancell?ed"                                  # English
    r"|(?:bestellung\s+)?storniert"                             # German
    r"|(?:commande\s+)?annulée?"                                # French
    r"|(?:pedido\s+)?cancelad[oa]"                              # Spanish
    r"|(?:ordine\s+)?annullat[oa]"                              # Italian
    r"|(?:bestelling\s+)?geannuleerd"                           # Dutch
    r"|(?:beställning(?:en)?\s+)?(?:avbruten|annullerad)"       # Swedish
    r"|(?:zamówienie\s+)?anulowane")                            # Polish
CANCELED_STATUS_RE = re.compile(_CANCELED_STATUS, re.I)

# The sentence under that heading, at the start of its line or after the
# heading and a dash when the two run together on one line. At the start,
# because "One item in your order was cancelled" and "Ein Artikel deiner
# Bestellung wurde storniert" hold the words of the whole order's sentence
# and say only part of it was canceled.
CANCELED_SENTENCE_RE = re.compile(
    r"^(?:(?:%s)\s*[-\u2013\u2014:]\s*)?(?:" % _CANCELED_STATUS +
    r"(?:your\s+|this\s+)?order\s+(?:was\s+|has\s+been\s+)?cancell?ed\b"
    r"|(?:deine\s+|ihre\s+|diese\s+)?bestellung\s+(?:wurde|ist)\s+(?:leider\s+)?"
    r"(?:vo[mn]\s+[\w.]+\s+)?storniert\b"
    r"|(?:votre\s+|cette\s+)?commande\s+(?:a\s+été|est)\s+annulée?\b"
    r"|(?:tu\s+|su\s+|este\s+)?pedido\s+(?:ha\s+sido|se\s+ha|fue)\s+cancelad[oa]\b"
    r"|(?:il\s+tuo\s+|questo\s+)?ordine\s+(?:è|e)\s+stato\s+annullat[oa]\b"
    r"|(?:je\s+|uw\s+|deze\s+)?bestelling\s+(?:is|werd)\s+geannuleerd\b"
    r"|(?:din\s+)?beställning(?:en)?\s+(?:har\s+)?"
    r"(?:avbrutits|annullerats|avbruten|annullerad)\b"
    r"|(?:twoje\s+)?zamówienie\s+(?:zostało\s+)?anulowane\b)",
    re.I)

# The line under an item's title names its seller, and the classic layout
# starts the title with "1 of:". A line like that is an item, never the
# order's status, so a product called "Cancelled" is not read as one.
SELLER_LINE_RE = re.compile(
    r"^(?:sold\s+by|supplied\s+by|verkauf\s+durch|vendu\s+par|vendido\s+por|"
    r"venduto\s+da|verkocht\s+door|säljs\s+av|sprzedawane\s+przez|sprzedawca)\b",
    re.I)
ITEM_LINE_RE = re.compile(r"^\d+\s+of:", re.I)

# A shipment delivered, on its way or still to be sent, at the start of its
# status line. An order with one is not canceled whatever else it says, so
# an order canceled in part is saved like any other, a free one too, whose
# total is zero. Broad on purpose, like the total words below.
SHIPPED_STATUS_RE = re.compile(
    r"^(?:delivered|shipped|dispatched|arriv\w*|out\s+for\s+delivery|on\s+the\s+way|"
    r"not\s+yet\s+(?:shipped|dispatched)|preparing\s+for\s+(?:shipment|dispatch)|"
    # German
    r"zugestellt|geliefert|versandt|verschickt|unterwegs|noch\s+nicht\s+versandt|"
    r"versandbereit|in\s+zustellung|ankunft|voraussichtliche\s+lieferung|"
    r"lieferung\s+(?:heute|morgen|am|bis|voraussichtlich)|"
    r"wird\s+(?:heute\s+|morgen\s+)?(?:geliefert|zugestellt|versandt|vorbereitet)|"
    # French
    r"livrée?|expédiée?|pas\s+encore\s+expédiée?|en\s+cours\s+de\s+(?:livraison|préparation)|"
    r"livraison\s+(?:prévue|estimée|aujourd|demain|le)|"
    # Spanish
    r"entregad[oa]|enviad[oa]|(?:aún|todavía)\s+no\s+(?:se\s+ha\s+)?enviad[oa]|llega\w*|"
    r"en\s+reparto|en\s+preparación|entrega\s+(?:prevista|estimada)|"
    # Italian
    r"consegnat[oa]|spedit[oa]|non\s+ancora\s+spedit[oa]|in\s+consegna|"
    r"in\s+preparazione|consegna\s+(?:prevista|stimata)|"
    # Dutch
    r"bezorgd|geleverd|verzonden|onderweg|nog\s+niet\s+verzonden|"
    r"verwachte\s+bezorging|wordt\s+(?:vandaag\s+|morgen\s+)?bezorgd|"
    # Swedish
    r"levererad|levererat|levererades|skickad|ännu\s+inte\s+skickad|"
    r"inte\s+skickad\s+än|beräknad\s+leverans|anländer|på\s+väg|"
    # Polish
    r"dostarczon[oea]|wysłan[oea]|jeszcze\s+nie\s+wysłan[oea]|w\s+drodze|"
    r"w\s+przygotowaniu|przewidywana\s+dostawa|dostawa\s+(?:dzisiaj|jutro))\b",
    re.I)

# Words that say an order was canceled only in part, anywhere on the page,
# "Tu pedido ha sido cancelado parcialmente" among them. A page with one is
# never read as the whole order canceled.
IN_PART_RE = re.compile(
    r"\b(?:partially|partly|in\s+part|teilweise|partiellement|en\s+partie|"
    r"parcialmente|parzialmente|gedeeltelijk|delvis|częściowo)\b",
    re.I)

# What a summary prints its totals under, in the stores' languages (Total,
# Sous-total, Totale, Totaal, Totalt, Zwischensumme, Gesamtsumme, Summa,
# Suma, Razem, Łącznie). Broad on purpose. A page this finds a total above
# zero on is never taken as canceled, so a word it should not have caught
# only leaves the order to be asked for again, as before.
TOTAL_WORDS_RE = re.compile(
    r"tota+l|summe|summa\b|\bsuma\b|\brazem\b|\błącznie\b|\bgesamt", re.I)


def total_above_zero(text: str) -> bool:
    """Whether an amount above zero follows a total label, in any of the
    stores' languages. An order canceled in part still owes for the rest."""
    text = text or ""
    for m in TOTAL_WORDS_RE.finditer(text):
        if any(v > 0 for v in find_amounts(text[m.end(): m.end() + 40])):
            return True
    return False


def reads_canceled(text: str, status: str = "") -> bool:
    """Whether an order's printable summary says the order was canceled.

    It has to say so. A line that is the status alone, "Storniert" or
    "Cancelled", or the sentence under it, "Deine Bestellung wurde
    storniert", in a store's language, or `status`, what the order list or
    the summary was read as before (parse_status, the only way an English
    order was recognized up to now). A line that is an item's title is not
    read. Nothing on the page may say otherwise, no total above zero, no
    shipment delivered, on its way or still to be sent, and no word saying
    the order was canceled in part, since those are an order canceled in
    part, or a product named for the word, and their receipt is saved."""
    lines = [line.strip() for line in (text or "").splitlines()]
    lines = [line for line in lines if line]
    if total_above_zero(text) or IN_PART_RE.search(text or "") \
            or any(SHIPPED_STATUS_RE.match(line) for line in lines):
        return False
    if re.search(r"cancell?ed", status or "", re.I):
        return True
    for i, line in enumerate(lines):
        after = lines[i + 1] if i + 1 < len(lines) else ""
        if ITEM_LINE_RE.match(line) or SELLER_LINE_RE.match(after):
            continue
        if CANCELED_STATUS_RE.fullmatch(line.rstrip(".!").strip()) \
                or CANCELED_SENTENCE_RE.match(line):
            return True
    return False


def order_canceled(page, status: str = "") -> bool:
    """reads_canceled() of the summary on the page, read as the screen lays
    it out, since printing leaves the tab in print media for the rest of
    the run. False when the page cannot be read, which says nothing."""
    return reads_canceled(_page_check.page_text(page, "screen"), status)


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

# How long the order list gets to appear, and one year's page of it, how
# long each is left to settle after that, and how long a page the list
# never came to is watched for a check. A bot check can hold a page blank
# while it decides and only then show itself, so a list running late is not
# the same as a year with no orders.
ORDERS_WAIT_MS = 30000
YEAR_WAIT_MS = 20000
SETTLE_MS = 2000
YEAR_SETTLE_MS = 1500
CHALLENGE_WAIT_MS = 15000


class ListStopped(Exception):
    """The order list did not come to its end, a year that still showed a
    next page at the most Discover reads of one year. A run downloads what
    it did read first, then leaves with this as the cause (App
    _stop_if_cut_short). The core knows a stop by this name and reports the
    run as stopped at a page that was not what it expected
    (paperpull_core.run_reporting.stop_reason). The panel then offers a
    support report and no sign-in, beside Continue after a run that
    downloads and Check again after Check what's there. Either reads the
    list again first, so for a year past the limit it stops at the same
    place, which the app's own words say when it stops."""


def goto_orders(page) -> bool:
    """Open the order list. True when it appeared, its orders or Amazon's
    own count saying the period has none.

    False is not an empty history and not a signed-in session. A page can
    sit blank while a bot check decides and only then turn into the check,
    so one look at it finds nothing to name."""
    page.goto(URLS["orders"], wait_until="domcontentloaded", timeout=60000)
    return _wait_for_list(page, ORDERS_WAIT_MS, SETTLE_MS)


def goto_year_page(page, year: int, start_index: int = 0) -> bool:
    """One year's page of the order list. True when it appeared, the same
    way, with the count read against where this page starts."""
    page.goto(orders_url(year, start_index), wait_until="domcontentloaded", timeout=60000)
    return _wait_for_list(page, YEAR_WAIT_MS, YEAR_SETTLE_MS, start_index)


def _wait_for_list(page, wait_ms: int, settle_ms: int, start_index: int = 0) -> bool:
    try:
        page.wait_for_selector(FALLBACK["page_ready"], timeout=wait_ms)
    except Exception:
        log.warning("Order-history content did not appear within %gs", wait_ms / 1000)
    page.wait_for_timeout(settle_ms)
    return orders_listed(page, start_index)


def order_count(page) -> Optional[int]:
    """Amazon's own count of the orders the period holds, or None when the
    page shows no count."""
    try:
        loc = page.locator(FALLBACK["order_count"])
        if loc.count() == 0:
            return None
        text = loc.first.text_content(timeout=2000) or ""
    except Exception:
        return None
    m = re.match(r"\s*(\d[\d,.\u00a0 ]*)", text)
    digits = re.sub(r"\D", "", m.group(1)) if m else ""
    return int(digits) if digits else None


def orders_listed(page, start_index: int = 0) -> bool:
    """Whether the order list is on the page now. Nothing is waited for.

    Its orders are there, or Amazon's own count says the period holds no
    more orders than come before this page, the way a year with none reads
    "0 orders". A page with neither never drew its list, however signed in
    it looks."""
    try:
        if page.locator(FALLBACK["order_card"]).count() > 0:
            return True
    except Exception:
        pass
    count = order_count(page)
    if count is not None and count <= start_index:
        return True
    # Orders drawn without a card the app knows, each found by its own
    # invoice menu or order-details link (#207).
    if invoice_menu_orders(page):
        return True
    # The orders read off the page's text, the way collect_cards falls back
    # to doing when the cards are drawn some other way.
    try:
        body = page.locator("body").inner_text(timeout=3000)
    except Exception:
        body = ""
    return bool(ORDER_ID_RE.search(body or ""))


def challenge_after_a_moment(page, wait_ms: Optional[int] = None,
                             start_index: int = 0) -> Optional[str]:
    """A security challenge on a page the order list never came to, looked
    for several times over a little while rather than once.

    None when there is still none when the time is up, and also when the
    list turns up after all, which the caller asks orders_listed about."""
    wait_ms = CHALLENGE_WAIT_MS if wait_ms is None else wait_ms
    deadline = time.monotonic() + wait_ms / 1000.0
    while True:
        found = detect_security_challenge(page)
        if found or orders_listed(page, start_index) or time.monotonic() >= deadline:
            return found
        try:
            page.wait_for_timeout(500)
        except Exception:
            return found


PAGE_SIZE = 10


def fewer_than_counted(page, start_index: int, read: int) -> bool:
    """Whether a list drawn without cards, whose orders print no order
    number in its text, showed fewer orders than Amazon's own count says
    this page holds (#207). Such a list is read from each order's invoice
    menu or order-details link, and an order drawn with neither would go
    missing with nothing said. False on a page with cards, a page whose
    text prints the numbers, and a page with no count, which read as they
    always did."""
    try:
        if page.locator(FALLBACK["order_card"]).count() > 0:
            return False
        body = page.locator("body").inner_text(timeout=3000)
    except Exception:
        return False
    if ORDER_ID_RE.search(body or ""):
        return False
    count = order_count(page)
    if count is None:
        return False
    return read < min(PAGE_SIZE, count - start_index)


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
                order_id = order_id_of(m.group(1))
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
    # Orders drawn without a card the app knows, each read from its own
    # invoice menu or order-details link and the block that holds it (#207).
    # Not on a page whose own count says it holds no orders, where whatever
    # names one is not in the list.
    if order_count(page) != 0:
        for oid, text in invoice_menu_orders(page):
            if oid in seen:
                continue
            seen.add(oid)
            cards.append(RawCard(href=order_details_url(oid), text=text, order_id=oid))
    # Then the whole page for order ids + their surrounding block, the block
    # found where the id is printed, whichever hyphens it has. Any the menus
    # did not name are read this way as they always were.
    try:
        body = page.locator("body").inner_text(timeout=8000)
    except Exception:
        body = ""
    for m in ORDER_ID_RE.finditer(body or ""):
        oid = order_id_of(m.group(1))
        if oid in seen:
            continue
        seen.add(oid)
        idx = m.start(1)
        chunk = body[max(0, idx - 400): idx + 400]
        cards.append(RawCard(href=order_details_url(oid), text=chunk, order_id=oid))
    return cards


# ---------------------------------------------------------------------------
# Orders drawn without a card the app knows (#207)
# ---------------------------------------------------------------------------
#
# A tester's amazon.de list (2026-11) draws each order as a plain block with
# no card class, no orderID= link the old selector finds and no order number
# its text gives the reader. Each order's header still carries the order's
# own invoice menu, Amazon's popover trigger whose data-a-popover names
# /your-orders/invoice/popover?orderId=<id>, and an order-details link. The
# ship-to name beside it is a popover trigger of the same shape, so a trigger
# is never taken by its place or its words, only by the address its data
# names. Nothing here is pressed or hovered, the attributes are read.

_INVOICE_MENU_PATH_RE = re.compile(
    r"(?:/-/[a-z]{2}(?:[_-][A-Za-z]{2})?)?/your-orders/invoice/popover")
_DETAILS_PATH_RE = re.compile(
    r"(?:/-/[a-z]{2}(?:[_-][A-Za-z]{2})?)?/(?:gp/your-account|your-orders)/order-details"
    r"(?:/ref=[^/]*)?")

# Each element whose data names a popover, and each link whose address has
# an orderID, with the address its data or href holds, and its ancestors by
# their place in the document, the element itself first, up to and not
# counting the body. A block that holds the page's own controls (the period
# menu's select, the header or the navigation) is never an order's, whatever
# it holds. A form is not one of them, since an order's Buy it again button
# can sit in a form of its own.
_INVOICE_MENUS_JS = r"""() => {
  const all = document.getElementsByTagName('*');
  const place = new Map();
  for (let i = 0; i < all.length; i++) place.set(all[i], i);
  const wide = new Map();
  const isWide = (el) => {
    if (!wide.has(el)) wide.set(el, !!(el.matches('header, nav, select') ||
        el.querySelector('header, nav, select')));
    return wide.get(el);
  };
  // Whether a sibling has the same tag and the same attribute names, the
  // mark of one block in a list of blocks drawn alike, an order among orders.
  const shapeOf = (el) => el.tagName + '|' + el.getAttributeNames().sort().join(',');
  const twin = new Map();
  const hasTwin = (el) => {
    if (!twin.has(el)) {
      const p = el.parentElement, mine = shapeOf(el);
      twin.set(el, !!p && Array.from(p.children).some(s => s !== el && shapeOf(s) === mine));
    }
    return twin.get(el);
  };
  const out = [];
  const found = Array.from(document.querySelectorAll('[data-a-popover], a[href]'));
  for (const el of found) {
    let kind, raw;
    if (el.hasAttribute('data-a-popover')) {
      kind = 'menu'; raw = el.getAttribute('data-a-popover') || '';
    } else {
      raw = el.getAttribute('href') || '';
      if (!/orderid=/i.test(raw)) continue;
      kind = 'link';
    }
    if (raw.length > 4000) continue;
    const chain = [], alike = [];
    let top = null;
    for (let up = el; up && up !== document.body && up !== document.documentElement;
         up = up.parentElement) {
      if (isWide(up)) { top = place.get(up); break; }
      chain.push(place.get(up));
      alike.push(hasTwin(up));
    }
    if (top === null && chain.length) top = -1;
    out.push({kind: kind, raw: raw, chain: chain, alike: alike, top: top});
    if (out.length >= 2000) break;
  }
  return out;
}"""

# The texts of each order's blocks, by their places, once each still holds
# the element that was read there and that still names what it named, else
# null.
_BLOCK_TEXT_JS = r"""(asks) => {
  const all = document.getElementsByTagName('*');
  return asks.map(([blocks, member, raw, kind]) => {
    const m = all[member];
    if (!m) return null;
    const now = kind === 'menu' ? m.getAttribute('data-a-popover') : m.getAttribute('href');
    if (now !== raw) return null;
    const said = [];
    for (const block of blocks) {
      const b = all[block];
      if (!b || !b.contains(m)) return null;
      said.push((b.innerText || '').slice(0, 6000));
    }
    return said;
  });
}"""


def _own_store(url: str) -> Optional[str]:
    """The path of an address on this store, relative or on its own host
    over https, else None."""
    from urllib.parse import urlsplit
    if not isinstance(url, str) or "\\" in url:
        return None
    if url.startswith("/") and not url.startswith("//"):
        return urlsplit(url).path
    if not is_safe_url(url):
        return None
    return urlsplit(url).path


def _the_one_order_id(url: str) -> Optional[str]:
    """The order id the address's own orderID parameter names, its name read
    in any case, when it names exactly one well-formed id, else None."""
    from urllib.parse import parse_qsl, urlsplit
    query = urlsplit(url).query
    named = [v for k, v in parse_qsl(query, keep_blank_values=True)
             if k.lower() == "orderid"]
    if len(set(named)) != 1:
        return None
    oid = order_id_of(named[0].strip())
    return oid if _ORDER_ID_WHOLE_RE.fullmatch(oid) else None


def invoice_menu_order_id(raw: str) -> Optional[str]:
    """The order an invoice menu belongs to, from its data-a-popover, when
    that names this store's /your-orders/invoice/popover for exactly one
    order. None for any other popover, the ship-to name's among them, and
    for anything that does not read cleanly."""
    import json
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None
    url = data.get("url") if isinstance(data, dict) else None
    path = _own_store(url) if isinstance(url, str) else None
    if path is None or not _INVOICE_MENU_PATH_RE.fullmatch(path):
        return None
    return _the_one_order_id(url)


def details_link_order_id(href: str) -> Optional[str]:
    """The order an order-details link on this store names, else None. A
    product link that happens to carry an orderID is not one."""
    path = _own_store(href)
    if path is None or not _DETAILS_PATH_RE.fullmatch(path):
        return None
    return _the_one_order_id(href)


def _order_of(found: dict) -> Optional[str]:
    if found.get("kind") == "menu":
        return invoice_menu_order_id(found.get("raw"))
    if found.get("kind") == "link":
        return details_link_order_id(found.get("raw"))
    return None


def invoice_menu_orders(page) -> List[Tuple[str, str]]:
    """(order id, its block's text) for each order on the page found by its
    invoice menu or order-details link, in the page's order.

    An order's block is found going up from what named it, never past a
    block that names another order or holds the page's own controls, and it
    stops at the first block drawn like one of its siblings, an order in a
    list of orders, so an unnamed neighbor's date is not taken. Its text
    gives the order's date and total. Where no block is wider than what
    named it the order is kept with that alone, no date or total rather
    than a neighbor's.

    The list is the place holding the most orders' blocks, counted by their
    invoice menus where any order has one, and an order whose block sits
    outside it (a banner naming an order) is not read. An order named only
    by its order-details link is read when its block is in the list. Empty when nothing names an
    order, or the page cannot be read."""
    try:
        found = page.evaluate(_INVOICE_MENUS_JS) or []
    except Exception:
        return []
    named = []
    for f in found:
        if not isinstance(f, dict) or not isinstance(f.get("chain"), list) or not f["chain"]:
            continue
        alike = f.get("alike")
        if not isinstance(alike, list) or len(alike) != len(f["chain"]):
            continue
        oid = _order_of(f)
        if oid:
            named.append((oid, f))
    if not named:
        return []
    # Each place to the orders named under it.
    under: dict = {}
    for oid, f in named:
        for p in f["chain"]:
            under.setdefault(p, set()).add(oid)
    # Each naming's blocks to choose from, lowest first, the ones drawn like
    # a sibling and the largest that names no other order, and the place
    # that holds that largest one.
    placed = []
    for oid, f in named:
        chain, at = f["chain"], 0
        for i, p in enumerate(chain):
            if under.get(p) != {oid}:
                break
            at = i
        blocks = [chain[i] for i in range(at) if f["alike"][i]] + [chain[at]]
        holder = chain[at + 1] if at + 1 < len(chain) else f.get("top")
        placed.append((oid, f, blocks, holder))
    # The list, the holder of the most orders' blocks, counted by their
    # invoice menus where any order has one. An order whose block is
    # elsewhere is not read from there, and an order named only by its
    # order-details link (a canceled one, say) is read when its block sits
    # in that list. Where nothing settles which holder is the list (one
    # order on the page, say), the orders named by a menu are read and a
    # link alone names none. An order missed that way is said, since the
    # page then shows fewer orders than its count (fewer_than_counted).
    menus = [x for x in placed if x[1]["kind"] == "menu"]
    votes = menus or placed
    held: dict = {}
    for oid, _f, _block, holder in votes:
        held.setdefault(holder, set()).add(oid)
    most = max(len(v) for v in held.values())
    lists = [h for h, v in held.items() if len(v) == most]
    if len(lists) == 1 and most >= 2:
        placed = [x for x in placed if x[3] == lists[0]]
    elif most >= 2:
        return []
    elif menus:
        placed = menus
    asks, order = [], []
    for oid, f, blocks, _holder in placed:
        if oid in order:
            continue
        order.append(oid)
        asks.append([blocks, f["chain"][0], f["raw"], f["kind"]])
    try:
        texts = page.evaluate(_BLOCK_TEXT_JS, asks) or []
    except Exception:
        return []
    if len(texts) != len(order):
        return []
    out = []
    for oid, said in zip(order, texts):
        if not isinstance(said, list) or not said or any(not isinstance(t, str) for t in said):
            # The page moved between the two looks, so nothing it says now
            # is taken for this order.
            return []
        # The lowest block that gives a date is the order's own, else the
        # largest that names it alone.
        text = next((t for t in said if parse_date(t)), said[-1])
        out.append((oid, text.strip()))
    log.info("orders read from their invoice menus: %d", len(out))
    return out


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
        purchase.order_number = order_id_of(m.group(1))

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

           Invented 10mm Axle Kit, 8 Pack, ...
           Sold by: Example Parts Co
           Return window closed on December 19, 2025
           $27.43

    2. Classic layout, "<qty> of: <Product Title>" then the price.

    3. Whole Foods and Amazon Fresh (verified 2026-09), no "Sold by" and no
       quantity anywhere. After "Purchased at Whole Foods Market" every item
       is a title line followed by a line holding only its price, and an
       item bought twice is simply listed twice:

           Invented Wild Salmon Fillets, Skin-On, 1 lb, Frozen
           $23.87
           Invented Wild Salmon Fillets, Skin-On, 1 lb, Frozen
           $23.87

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


def not_this_purchase(page, order_id: str) -> str:
    """"" when the page in front of the app is this order's printable
    summary, else why it is not, in fixed words.

    Its address names the order in orderID, and every order id on the page
    as it prints is this one (both measured on saved summaries,
    2026-09-29). The order list names several orders and no orderID, a
    sign-in page names the order only in its return address, and another
    order's summary prints its own id. See paperpull_core.page_check."""
    if not _page_check.address_names(page.url, order_id, query="orderID"):
        return _page_check.NOT_ITS_ADDRESS
    shown = order_ids_in(_page_check.page_text(page, "print"))
    return _page_check.names_only(shown, order_id)


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
        resp = redirects.get(page.context.request, invoice_popover_url(order_id),
                             is_safe_url, hops=3, timeout=30000)
    except Exception as e:
        log.warning("invoice popover fetch failed: %s", str(e).splitlines()[0][:100])
        return []
    if not resp.ok or not is_safe_url(resp.url):
        return []
    try:
        # Never copied into the run past the limit (intake.text_of).
        popover = intake.text_of(resp)
    except intake.TooLarge:
        return []
    out, seen = [], set()
    for m in INVOICE_PDF_HREF_RE.finditer(popover):
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
        # A redirect is followed only to the store's own hosts, each
        # checked before it is asked, since Playwright alone would carry
        # the browser's cookies wherever one led.
        resp = redirects.get(page.context.request, url, is_safe_url, hops=3, timeout=90000)
    except Exception as e:
        log.warning("invoice download failed: %s", str(e).splitlines()[0][:100])
        return False
    if not resp.ok or not is_safe_url(resp.url):
        log.warning("invoice download returned %s", resp.status)
        return False
    try:
        body = intake.body(resp)
    except intake.TooLarge:
        return False
    if not body.startswith(b"%PDF"):
        log.warning("invoice download was not a PDF (%d bytes)", len(body))
        return False
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    shared_folder.write_bytes(out, body)
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


def find_receipt_iframe(page):
    """Amazon's invoice is a page of its own, never an iframe. The other
    seven receipt apps carry this same stub and Amazon did not, so its
    Diagnose stopped here and wrote nothing after it."""
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
