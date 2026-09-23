"""ALL Costco selectors, URL patterns, and page behavior live here.

When Costco changes its website, repair this file only.

WRITTEN FROM A RECORDING, 2026-09-22. The first version of this file was
guesswork off the public site. A member then signed in, pressed Record and
clicked their way to two warehouse receipts and one online invoice, and
everything below marked SEEN comes from that. See issue #47.

THE TWO HALVES

Orders & Purchases is one page with two tabs, and they are two different
things behind one heading.

    Warehouse   what was bought at a warehouse, including the gas station
                and the car wash. This is the half nobody else can get at,
                because Costco keeps it for a matter of months and the
                paper fades.
    Online      costco.com orders.

SEEN. Both are ``role=tab``, named "Warehouse" and "Online". Switching
tabs does not navigate, it asks the API and redraws.

HOW FAR BACK

A ``role=combobox`` labelled "Showing", holding quarters rather than
years, "2026 April - June" and so on, opening on "Last 3 Months". SEEN.
So a run that does not touch it sees a quarter at most, and reaching a
year means walking the options.

A WAREHOUSE RECEIPT IS A DIALOG

SEEN. "View Receipt" on a row opens a dialog **on the same page**, with
no navigation and no URL of its own, and the dialog carries a "Print
Receipt" link and a "Close" button. So a receipt here has no address to
go to, and the only way back to one is to find its row again. Its
identity is therefore made from what the row shows, the date and the
total, and not from any number Costco gives out.

The app never presses Print Receipt. That link calls ``window.print()``,
SEEN, which opens a dialog no program can answer or dismiss. The dialog's
own contents are rendered with CDP printToPDF instead.

AN ONLINE ORDER IS TWO NAVIGATIONS

SEEN. "View Order Details" is a link to
``/myaccount/#/app/<client id>/orderdetails/<order number>``, and that
page carries a "Print Invoice" link to ``/OrderDetailPrintView``, which
is a plain printable page. Both are links with real addresses, so this
app reads the address and goes there. It clicks neither, because the
second press of Print Invoice, on the print view itself, calls
``window.print()``. SEEN, in the recording, twice.

THE API, AND WHY THIS APP DOES NOT USE IT

SEEN. Everything is one GraphQL endpoint,
``https://ecom-api.costco.com/ebusiness/order/v1/orders/graphql``, POSTed
with ``query`` and ``variables``.

    Warehouse tab    data.receiptsWithCounts, carrying inWarehouse,
                     gasStation, carWash and gasAndCarWash counts and a
                     receipts list
    View Receipt     the same shape with one receipt in it
    Online tab       data.getOnlineOrders, with pageNumber, pageSize,
                     totalNumberOfRecords and bcOrders
    Order details    data.getOrderDetails

That is the shape of the answers, which is all a recording keeps. The
query text is a value and was deliberately not captured, so this app
cannot make those calls and does not try. It drives the page the way the
person did. If a later recording brings the queries back, discovery is
the only part that changes.

Costco also runs Akamai Bot Manager, whose script wraps window.fetch and
refused a call made from an automated page, and a queue-it waiting room.
Both verified. So this app drives a real Edge or Chrome.

Signing in is Azure AD B2C on signin.costco.com, returning to
/OAuthLogonCmd. A URL on that host is the signed-out signal. Verified.

Site layer written from a member's recording: 2026-09-22
"""
from __future__ import annotations

import html as _html
import json
import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional

from paperpull_core.models import IN_STORE, ONLINE, Item, Purchase
from storage import now_iso

from paperpull_core.redact import private_words, set_private_words  # noqa: F401
from paperpull_core.urls import is_safe_url as _host_allows

log = logging.getLogger("costco_receipts.site")

# The run's journal, handed over by the orchestrator. None when nobody
# set one, and every use below is guarded, because a journal must never
# be the reason a working provider stops working.
_journal = None


def set_journal(journal) -> None:
    global _journal
    _journal = journal


def _note(method, *a, **kw):
    """Write to the journal if there is one, and never fail."""
    try:
        if _journal is not None:
            getattr(_journal, method)(*a, **kw)
    except Exception:
        pass

# ---------------------------------------------------------------------------
# URLs
# ---------------------------------------------------------------------------

BASE = "https://www.costco.com"

# The OAuth client id, which is also the myaccount app id. The same for
# every member, so this URL is a constant and not something to discover.
MYACCOUNT_APP_ID = "4900eb1f-0c10-4bd9-99c3-c59e6c1ecebf"
ORDERS_URL = f"{BASE}/myaccount/#/app/{MYACCOUNT_APP_ID}/ordersandpurchases"
DETAILS_PATH = f"/myaccount/#/app/{MYACCOUNT_APP_ID}/orderdetails/"

# The printable version of an online order. SEEN as the target of the
# Print Invoice link.
PRINT_VIEW_PATH = "/OrderDetailPrintView"

# The one GraphQL endpoint everything goes through. Not called by this
# app, and listed so a reader of a diagnostics file knows what it is.
ORDER_API = "https://ecom-api.costco.com/ebusiness/order/v1/orders/graphql"

LEGACY_QS = "storeId=10301&catalogId=10701&langId=-1"
LEGACY_ORDERS_URL = f"{BASE}/OrderStatusCmd?{LEGACY_QS}&URL=OrderStatusSummaryView"

URLS = {
    "home": f"{BASE}/",
    "orders": ORDERS_URL,
    "orders_legacy": LEGACY_ORDERS_URL,
    "account": f"{BASE}/myaccount/",
}

ORDER_ROUTES = [ORDERS_URL, f"{BASE}/myaccount/", LEGACY_ORDERS_URL]

# Kept for the shared orchestrator, which asks for these by name.
RECEIPT_PATH = DETAILS_PATH
DETAIL_PATH = DETAILS_PATH
PENDING_PATH = DETAILS_PATH

LOGIN_URL_MARKERS = ["signin.costco.com", "/logonform", "/oauthlogoncmd",
                     "/oauth2/", "/b2c_1a_", "/login", "/sign-in", "/signin",
                     "/registration", "/join"]

# An online order number, or the identity this app makes for a warehouse
# receipt, which has none of its own.
PURCHASE_KEY_RE = re.compile(r"^[0-9A-Za-z]+(?:[~_-][0-9A-Za-z]+)*$")

# The two tabs. SEEN.
TAB_WAREHOUSE = "Warehouse"
TAB_ONLINE = "Online"


def details_url(key: str) -> str:
    return f"{BASE}{DETAILS_PATH}{key}"


def receipt_url(key: str) -> str:
    return details_url(key)


def orders_url(page_no: int = 1) -> str:
    return ORDERS_URL


def warehouse_key(date: str, total: str, where: str = "") -> str:
    """The identity of a warehouse receipt, made from what its row shows.

    Costco gives a warehouse receipt no number on the list and no address
    of its own, so there is nothing to key it by except what a person
    reads on the row. Date, total and the warehouse, which together are
    what tells two rows apart on screen. Two receipts from the same
    warehouse on the same day for the same amount would collide, and a
    run would fetch one of them. That is the cost of a list that carries
    no identifier, and it is recorded here rather than papered over."""
    money = re.sub(r"[^0-9]", "", total or "")
    day = re.sub(r"[^0-9]", "", date or "")
    where = re.sub(r"[^A-Za-z0-9]", "", (where or ""))[:12]
    return "-".join(p for p in ("wh", day, money, where) if p)


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------
FORBIDDEN_CONTROL_RE = re.compile(
    r"(add\s+(all\s+)?to\s+(cart|list)|add\s+all|buy\s+(it\s+)?again|reorder|checkout|"
    r"start\s+(your\s+)?order|modify\s+order|cancel\s+(order|membership|auto)|"
    r"request\s+a\s+refund|refund|return\s+item|start\s+a\s+return|report\s+(a\s+)?problem|"
    r"renew|auto\s*renew|upgrade\s+membership|membership\s+renewal|"
    r"pay\s+now|\bpay\b|payment|contact\s+us|customer\s+(service|support)|"
    r"share\s+feedback|survey|chat|delete|remove|subscribe|redeem|apply\s+now|"
    r"sign\s+out|log\s+out|print\b)", re.I)

try:
    from paperpull_core.controls import SETTINGS_CONTROL_RE as _SHARED_SETTINGS
    FORBIDDEN_CONTROL_RE = re.compile(
        "(?:%s)|(?:%s)" % (FORBIDDEN_CONTROL_RE.pattern, _SHARED_SETTINGS.pattern),
        re.I)
except Exception:  # the shared core is optional at import time
    pass

# Everything here is a control SEEN in the recording, except the few kept
# from the first version because a near miss should still be allowed.
# "Print Receipt" and "Print Invoice" stay refused on purpose. They are
# the right controls and this app must not press them, because they call
# window.print() and open a dialog no program can dismiss.
SAFE_DOC_CONTROL_RE = re.compile(
    r"(view\s+(receipt|invoice|details|order)|receipt|invoice|order\s+details|"
    r"purchase\s+details|order\s+history|purchase\s+history|"
    r"orders?\s*(and|&|&amp;)\s*(purchases|returns)|"
    r"in.?warehouse|warehouse|online\s+orders?|\bonline\b|"
    r"view\s+more|load\s+more|show\s+more|next\s+page|page\s+\d+|"
    r"last\s+\d+\s+months?|all\s+dates|date\s+range|showing)", re.I)

SECURITY_CHALLENGE_MARKERS = [
    "enter the characters you see", "type the characters you see",
    "are you a robot", "robot check", "press and hold",
    "verify you are a human", "verify you are human",
    "checking your browser before accessing",
    "access to this page has been denied", "access denied",
    "two-step verification", "enter the one time password",
    "enter the one-time password", "enter the otp",
    "enter the verification code", "confirm it's you",
    "pardon our interruption",
    "reference #", "you are now in line", "your estimated wait time",
    "waiting room", "queue-it",
]

RATE_LIMIT_MARKERS = [
    "too many requests", "rate limit", "try again later",
    "temporarily blocked", "http error 429", "request was throttled",
]

# SEEN, every one of them, with a looser spelling beside each in case
# Costco changes the wording before somebody changes this file.
# What a control says, for code that runs INSIDE the page. Everything in
# FALLBACK below is a Playwright selector, and Playwright's own additions
# to CSS, :has-text() among them, are understood by page.locator() and
# rejected by the browser's querySelectorAll. Discovery runs in the page,
# so it matches on these instead. A live run against a real account is
# what found that out.
RECEIPT_CONTROL_TEXT = r"view\s+receipt"
DETAILS_CONTROL_TEXT = r"view\s+order\s+details|order\s+details"
PRINT_CONTROL_TEXT = r"print\s*(receipt|invoice)?"

FALLBACK = {
    "tab": "[role=tab]",
    "receipt_button": "button:has-text('View Receipt')",
    "details_link": "a:has-text('View Order Details')",
    "range_select": "select",
    # Costco's receipt is a Bootstrap modal, and Bootstrap leaves the
    # empty one in the markup with role=dialog on it, nought by nought,
    # from the moment the page loads. Matching on the selector alone
    # found that one every time, so everything below picks by what is on
    # screen instead. See _VISIBLE_JS.
    "dialog": "[role=dialog], [aria-modal=true], .modal.show, .modal.in",
    "dialog_close": "[role=dialog] button:has-text('Close')",
    "print_invoice": "a:has-text('Print Invoice')",
    # The receipt itself, inside the dialog. The dialog is the block worth
    # rendering, so the shell and the block are the same thing here.
    "receipt_area": "[role=dialog], [aria-modal=true], .modal.show, .modal.in",
    "receipt_shell": "[role=dialog], [aria-modal=true], main, body",
    "print_button": "[role=dialog] a:has-text('Print Receipt'), "
                    "[role=dialog] button:has-text('Print Receipt')",
    "order_card": "[role=dialog], li, tr, [class*='card' i]",
    "order_link": "a[href*='orderdetails' i]",
    "page_ready": "[role=tab], main, [role=main], body",
    "item_row": "[role=dialog] tr, [role=dialog] li",
    "print_page_body": "body",
}

NO_ORDERS_RE = re.compile(
    r"no\s+orders|don't\s+have\s+any\s+orders|aren't\s+any\s+orders|"
    r"no\s+purchases|no\s+receipts|nothing\s+to\s+show", re.I)
MISSING_LOYALTY_RE = re.compile(
    r"membership\s+(number\s+)?not\s+found|add\s+your\s+membership|"
    r"link\s+your\s+membership", re.I)
RECEIPT_FAILED_RE = re.compile(
    r"problem\s+loading|unable\s+to\s+(retrieve|load|display)|"
    r"something\s+went\s+wrong|couldn't\s+load", re.I)

MONEY_RE = re.compile(r"\$\s*(-?[\d,]+\.\d{2})")

# Costco's own words, with the API's spellings beside them because a
# later round may read the list from getOnlineOrders instead of the page.
PURCHASE_TYPE_LABELS = {
    "WAREHOUSE": ("In-Warehouse", IN_STORE),
    "IN_WAREHOUSE": ("In-Warehouse", IN_STORE),
    "INWAREHOUSE": ("In-Warehouse", IN_STORE),
    "IN_STORE": ("In-Warehouse", IN_STORE),
    "GAS": ("Gas Station", IN_STORE),
    "GASSTATION": ("Gas Station", IN_STORE),
    "GAS_STATION": ("Gas Station", IN_STORE),
    "FUEL": ("Gas Station", IN_STORE),
    "CARWASH": ("Car Wash", IN_STORE),
    "CAR_WASH": ("Car Wash", IN_STORE),
    "GASANDCARWASH": ("Gas and Car Wash", IN_STORE),
    "PHARMACY": ("Pharmacy", IN_STORE),
    "OPTICAL": ("Optical", IN_STORE),
    "ONLINE": ("Online", ONLINE),
    "DOTCOM": ("Online", ONLINE),
    "SHIP": ("Online", ONLINE),
    "SHIP_TO_HOME": ("Online", ONLINE),
    "DELIVERY": ("Delivery", ONLINE),
    "SAME_DAY": ("Same-Day Delivery", ONLINE),
    "GROCERY": ("Grocery", ONLINE),
    "TRAVEL": ("Travel", ONLINE),
    "PHOTO": ("Photo", ONLINE),
}


def purchase_kind(purchase_type: str) -> str:
    """Which folder a Costco purchase belongs in. Anything unrecognised is
    filed as an online order, because that is the one a person can always
    get at themselves if this guessed wrong."""
    return PURCHASE_TYPE_LABELS.get((purchase_type or "").upper(), ("", ONLINE))[1]


def purchase_label(purchase_type: str) -> str:
    label = PURCHASE_TYPE_LABELS.get((purchase_type or "").upper(), ("", ONLINE))[0]
    return label or (purchase_type or "").replace("_", " ").title()


def money_from_api(value) -> str:
    """The API writes money as "USD 12.34" or a number. Filenames and the
    spreadsheet want "$12.34"."""
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        return f"${value:,.2f}"
    s = str(value).strip()
    m = re.search(r"(-?[\d,]+(?:\.\d{1,2})?)", s.replace("USD", ""))
    if not m:
        return ""
    try:
        return f"${float(m.group(1).replace(',', '')):,.2f}"
    except ValueError:
        return ""


def parse_status(text: str) -> str:
    t = (text or "").strip().upper()
    if not t:
        return ""
    if t in ("CANCELLED", "CANCELED"):
        return "Canceled"
    if t in ("REFUNDED",):
        return "Refunded"
    if t in ("COMPLETED", "COMPLETE", "DELIVERED", "PICKED_UP"):
        return "Completed"
    return t.replace("_", " ").title()


def looks_signed_out(page) -> bool:
    """Costco sends a signed-out visitor to signin.costco.com, so the URL
    answers this on its own almost every time. VERIFIED by opening the
    orders route signed out and landing on the B2C authorize endpoint."""
    url = (page.url or "").lower()
    if any(m in url for m in LOGIN_URL_MARKERS):
        return True
    try:
        if page.locator("input[type='password']").count() > 0:
            return True
    except Exception:
        pass
    try:
        body = page.locator("body").inner_text(timeout=5000).lower()
    except Exception:
        return False
    signed_out = ("sign in" in body[:1500] and "email address" in body[:1500])
    return signed_out and "orders" not in body[:1500]


def detect_security_challenge(page) -> Optional[str]:
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
# The purchase history, read through the page's own API
# ---------------------------------------------------------------------------

def goto_orders(page, page_no: int = 1, fresh: bool = False) -> None:
    """Open Orders & Purchases and wait for the tabs to exist.

    Both routes under /myaccount/ differ only after the "#", so going
    from one order's details back to the list is a same document
    navigation. The browser changes the address and loads nothing, and
    whether the app notices is the app's business. Coming back from an
    order this way left the tabs undrawn and every receipt after the
    first failed with "could not open the Warehouse tab". A live run
    found it.

    So the address is set first and the page is then reloaded for real
    if the tabs do not turn up, which is the one thing a hash cannot
    do on its own."""
    if on_orders_page(page) and has_tabs(page) and not fresh:
        return
    # Going from this page to this page is a hash change and loads
    # nothing at all, so when a fresh one is wanted it is asked for
    # outright. Trying goto first cost twenty five seconds a receipt
    # waiting for tabs that were never going to be redrawn.
    for attempt in (1, 2):
        try:
            if attempt == 1 and not (fresh and on_orders_page(page)):
                page.goto(ORDERS_URL, wait_until="domcontentloaded", timeout=60000)
            else:
                page.reload(wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            log.warning("Could not open Orders & Purchases: %s", e)
        try:
            page.wait_for_selector(FALLBACK["tab"], timeout=25000)
            settle(page)
            return
        except Exception:
            if attempt == 2:
                log.warning("The Orders & Purchases tabs did not appear")
    settle(page)


def has_tabs(page) -> bool:
    try:
        return page.locator(FALLBACK["tab"]).count() > 0
    except Exception:
        return False


def on_orders_page(page) -> bool:
    return "ordersandpurchases" in (page.url or "").lower()


def settle(page, ms: int = 12000) -> None:
    """Wait for the page to stop talking. Every tab and every date range
    is an API call and a redraw, with no navigation to wait on."""
    try:
        page.wait_for_load_state("networkidle", timeout=ms)
    except Exception:
        page.wait_for_timeout(2500)


def goto_orders_route(page, url: str) -> None:
    """One candidate route, for diagnostics to try in turn."""
    if not is_safe_url(url):
        raise ValueError("refusing to open a URL that is not on costco.com")
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    settle(page)


def history_state(page) -> str:
    '''"empty" when the tab says there is nothing to show, "no-membership"
    when it wants a membership number linked first, else "".'''
    try:
        body = page.locator("body").inner_text(timeout=5000)
    except Exception:
        return ""
    if MISSING_LOYALTY_RE.search(body):
        return "no-membership"
    if NO_ORDERS_RE.search(body):
        return "empty"
    return ""


# -- the two tabs --------------------------------------------------------------

def tab_names(page) -> List[str]:
    out = []
    try:
        for tab in page.locator(FALLBACK["tab"]).all()[:12]:
            name = (tab.inner_text(timeout=1000) or "").strip()
            if name:
                out.append(name)
    except Exception:
        pass
    return out


def open_tab(page, name: str) -> bool:
    """Click one of the two tabs. Returns whether it is now the open one.

    Switching does not navigate, it asks the API and redraws, so the only
    thing to wait on is the page going quiet."""
    _note("op", "switch_tab", "open a tab")
    if not is_safe_control(name):
        raise ValueError("refusing to click a control called %r" % name)
    try:
        tab = page.get_by_role("tab", name=name, exact=False).first
        if tab.count() == 0:
            log.warning("No tab called %r on this page", name)
            return False
        if (tab.get_attribute("aria-selected") or "").lower() == "true":
            return True
        tab.click(timeout=15000)
    except Exception as e:
        log.warning("Could not open the %s tab: %s", name, e)
        _note("result", "could not open the tab", error=e)
        return False
    settle(page)
    _note("checkpoint", "the tab is open", page)
    return True


# -- how far back ---------------------------------------------------------------

# "2026 April - June", and "Last 3 Months" for the one it opens on. SEEN.
_QUARTER_RE = re.compile(
    r"(20\d\d)\s*[-,]?\s*(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)",
    re.I)
_MONTHS = ["jan", "feb", "mar", "apr", "may", "jun",
           "jul", "aug", "sep", "oct", "nov", "dec"]


def range_options(page) -> List[str]:
    """Every option in the "Showing" picker, in the order it lists them."""
    try:
        sel = page.get_by_role("combobox", name=re.compile("showing", re.I)).first
        if sel.count() == 0:
            sel = page.locator(FALLBACK["range_select"]).first
        if sel.count() == 0:
            return []
        return [o.strip() for o in
                sel.locator("option").all_inner_texts()[:60] if o.strip()]
    except Exception as e:
        log.warning("Could not read the date range options: %s", e)
        return []


def range_covers(option: str, date: str) -> bool:
    """Does an option like "2026 April - June" contain this date?

    Only the year and the first month are read, because the option names
    a quarter and a quarter is three months from the one it names. An
    option that is not a quarter, "Last 3 Months" say, covers nothing in
    particular and is never chosen on purpose."""
    m = _QUARTER_RE.search(option or "")
    if not m or not date:
        return False
    try:
        year, month, _ = date.split("-")
        start = _MONTHS.index(m.group(2)[:3].lower()) + 1
    except (ValueError, IndexError):
        return False
    return m.group(1) == year and start <= int(month) <= start + 2


def select_range(page, option: str) -> bool:
    """Choose one option in the "Showing" picker and wait for the redraw."""
    try:
        sel = page.get_by_role("combobox", name=re.compile("showing", re.I)).first
        if sel.count() == 0:
            sel = page.locator(FALLBACK["range_select"]).first
        if sel.count() == 0:
            return False
        sel.select_option(label=option, timeout=15000)
    except Exception as e:
        log.warning("Could not choose the range %r: %s", option, e)
        _note("result", "could not choose the range", error=e)
        return False
    settle(page)
    _note("checkpoint", "the range is chosen", page)
    return True


def ranges_for(page, year: str = "") -> List[str]:
    """The options worth walking. A year if one is asked for, otherwise
    every quarter the picker offers, newest first as it lists them."""
    quarters = [o for o in range_options(page) if _QUARTER_RE.search(o)]
    if year:
        quarters = [o for o in quarters if o.strip().startswith(year)]
    return quarters


# -- what is on the tab ---------------------------------------------------------

# Runs inside the signed-in page. One entry per row that carries a control
# for looking at the purchase, with the row's own words beside it. The
# GraphQL answers behind this page would be better and this app cannot
# make those calls, because their query text is a value and a recording
# keeps no values. Shaped like a JSON record all the same, so the day a
# recording brings the queries back, only this function changes.
_READ_ROWS_JS = r"""
([receiptText, linkSel]) => {
  const out = [];
  const money = (s) => { const m = (s || '').match(/\$\s*-?[\d,]+\.\d{2}/); return m ? m[0] : ''; };
  const when = (s) => {
    let m = (s || '').match(/(\d{1,2})\/(\d{1,2})\/(\d{2,4})/);
    if (m) { const y = m[3].length === 4 ? m[3] : '20' + m[3];
             return y + '-' + String(+m[1]).padStart(2,'0') + '-' + String(+m[2]).padStart(2,'0'); }
    m = (s || '').match(/(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{1,2}),?\s+(\d{4})/i);
    if (!m) return '';
    const mo = ['jan','feb','mar','apr','may','jun','jul','aug','sep','oct','nov','dec']
                 .indexOf(m[1].slice(0,3).toLowerCase()) + 1;
    return m[3] + '-' + String(mo).padStart(2,'0') + '-' + String(+m[2]).padStart(2,'0');
  };
  // Up from the control to the block a person would call one purchase.
  const card = (el) => {
    let n = el;
    for (let i = 0; i < 8 && n.parentElement; i++) {
      n = n.parentElement;
      const txt = (n.innerText || '');
      if (txt.length > 40 && /\$\s*[\d,]+\.\d{2}/.test(txt)) return n;
    }
    return el.parentElement || el;
  };
  const rows = [];
  // Plain CSS and a text test, because this runs in the browser and the
  // browser has never heard of :has-text().
  const wants = new RegExp(receiptText, 'i');
  for (const el of document.querySelectorAll('button, [role=button], a')) {
    const label = (el.innerText || el.getAttribute('aria-label') || '').trim();
    if (label && label.length < 40 && wants.test(label)) rows.push(['WAREHOUSE', el]);
  }
  for (const el of document.querySelectorAll(linkSel)) rows.push(['ONLINE', el]);
  const done = new Set();
  for (const [kind, el] of rows) {
    if (done.has(el)) continue;
    done.add(el);
    // Marked so the code that presses it can ask for this element and
    // not for the nth of some other list. Counting by position meant
    // reading `button, [role=button], a` and pressing the nth `button`,
    // and the first receipt on the page worked while the rest did not.
    // A live run found it. The attribute is a DOM change like the
    // isolation, gone on the next navigation.
    el.setAttribute('data-pp-row', String(out.length));
    const block = card(el);
    const text = (block.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 600);
    const href = el.tagName.toLowerCase() === 'a' ? (el.href || '') : '';
    out.push({purchaseType: kind, href: href,
              createdDateTime: when(text), total: money(text),
              status: /cancell?ed/i.test(text) ? 'CANCELLED' : '',
              where: (text.match(/\b([A-Z][A-Z' -]{3,24})\b(?=\s|$)/) || [,''])[1].trim(),
              index: out.length, cardText: text});
  }
  return out;
}
"""


_ROWS_READY_JS = r"""
([linkSel, receiptText, emptyText]) => {
  const wants = new RegExp(receiptText, 'i');
  for (const el of document.querySelectorAll('button, [role=button], a')) {
    const label = (el.innerText || el.getAttribute('aria-label') || '').trim();
    if (label && label.length < 40 && wants.test(label)) return true;
  }
  if (document.querySelector(linkSel)) return true;
  // An account with nothing in this quarter says so, and that is an
  // answer too. Without this the wait would run its full length on
  // every empty quarter, of which there are many.
  return new RegExp(emptyText, 'i').test(document.body.innerText || '');
}
"""


def wait_for_rows(page, timeout_ms: int = 20000) -> bool:
    """Wait until the tab has drawn its rows, or said it has none.

    Switching a tab or a quarter does not navigate, it asks the API and
    redraws, so there is no load to wait on and network quiet comes back
    before the rows are on screen. A live run read an empty list this
    way and then could not find the receipt it had discovered a minute
    earlier."""
    try:
        page.wait_for_function(
            _ROWS_READY_JS,
            arg=[FALLBACK["order_link"], RECEIPT_CONTROL_TEXT,
                 NO_ORDERS_RE.pattern],
            timeout=timeout_ms)
        return True
    except Exception:
        log.debug("The list did not draw within %dms", timeout_ms)
        return False


def read_rows(page, wait_ms: int = 20000) -> List[dict]:
    """The purchases on the tab that is open, as records."""
    if wait_ms:
        wait_for_rows(page, wait_ms)
    try:
        rows = page.evaluate(_READ_ROWS_JS,
                             [RECEIPT_CONTROL_TEXT, FALLBACK["order_link"]]) or []
    except Exception as e:
        log.warning("Could not read the rows on this tab: %s", e)
        return []
    rows = [r for r in rows if isinstance(r, dict)]
    _note("op", "read_rows", "read the rows", rows=len(rows))
    return rows


def fetch_history(page, max_pages: int = 200, year: str = "") -> dict:
    """Every purchase on both tabs, across the quarters the picker offers.

    Named for what the orchestrator calls. The answer has the shape a
    JSON API would give, so the day a recording brings Costco's own
    query text back, this is the only function that changes."""
    records, seen = [], set()
    ranges_walked = 0
    for tab in (TAB_WAREHOUSE, TAB_ONLINE):
        if not open_tab(page, tab):
            continue
        options = ranges_for(page, year)
        # Whatever it opens on first, then each quarter in turn. Without
        # touching the picker a run sees three months and no more.
        for option in [None] + options:
            if option is not None:
                if not select_range(page, option):
                    continue
                ranges_walked += 1
            for rec in read_rows(page):
                rec["tab"] = tab
                rec["range"] = option or ""
                key = record_key(rec)
                if key and key not in seen:
                    seen.add(key)
                    records.append(rec)
            if year and option is None:
                # A scoped run should not keep whatever the page opened on.
                records = [r for r in records if not r.get("createdDateTime")
                           or r["createdDateTime"].startswith(year)]
    if not records:
        log.warning("No purchases were found on either tab. If there are "
                    "purchases on screen, run `record` and send the file.")
    return {"status": 200 if records else 0, "pages": ranges_walked or 1,
            "last": True, "records": records}


def _first(d: dict, *names, default=None):
    for n in names:
        if isinstance(d, dict) and d.get(n) not in (None, ""):
            return d[n]
    return default


def _datetime_value(v) -> str:
    """The API wraps dates as {"value": "2026-09-13T15:04:05Z", ...}."""
    if isinstance(v, dict):
        v = v.get("value") or v.get("date") or ""
    s = str(v or "")
    m = re.match(r"(\d{4}-\d{2}-\d{2})", s)
    return m.group(1) if m else ""


def record_key(rec: dict) -> str:
    """What tells this purchase from the next one, on both tabs.

    An online order has a number, in the address of its details link. A
    warehouse receipt has nothing at all on the list, so one is made from
    what its row shows. See warehouse_key."""
    key = str(_first(rec, "orderNumber", "receiptKey", "orderId", default="")).strip()
    if not key:
        href = str(rec.get("href") or "")
        m = re.search(r"orderdetails/([0-9A-Za-z_-]{4,40})", href, re.I)
        if m:
            key = m.group(1)
    if not key and str(rec.get("purchaseType") or "").upper().startswith("WAREHOUSE"):
        key = warehouse_key(str(rec.get("createdDateTime") or ""),
                            str(rec.get("total") or ""),
                            str(rec.get("where") or ""))
        if key == "wh":
            key = ""
    return key if key and PURCHASE_KEY_RE.match(key) and len(key) <= 80 else ""


def record_is_pending(rec: dict) -> bool:
    """An order still on its way. A warehouse receipt is never pending,
    it is a thing that already happened at a till."""
    if str(rec.get("purchaseType") or "").upper().startswith("WAREHOUSE"):
        return False
    status = str(_first(rec, "status", default="")).upper()
    text = str(rec.get("cardText") or "")
    if status in ("CANCELLED", "CANCELED"):
        return False
    return bool(re.search(r"processing|in\s*transit|shipping\s+soon|"
                          r"on\s+its\s+way|not\s+yet\s+shipped|pending",
                          text, re.I))


def record_to_purchase(rec: dict) -> Optional[Purchase]:
    """A Purchase from one API record. Field names are the bundle's, and
    each one is read with a fallback so a renamed field degrades to an
    empty column instead of a crash."""
    key = record_key(rec)
    if not key:
        return None
    href = str(_first(rec, "href", "url", default="") or "")
    if not is_safe_url(href):
        href = ""
    ptype = str(_first(rec, "purchaseType", "fulfillmentType", "modality", default=""))
    items: List[Item] = []
    for li in rec.get("lineItems") or rec.get("items") or []:
        if not isinstance(li, dict):
            continue
        info = li.get("displayInfo") or (li.get("purchasedData") or {}).get("displayInfo") or {}
        name = _first(info, "description", "name", default="") or _first(li, "description", "name", default="")
        upc = str(_first(li, "upc", "gtin", default="") or "")
        qty = str(_first(li, "quantity", "qty", default="1") or "1")
        items.append(Item(name=(str(name) or f"UPC {upc}")[:300], quantity=qty,
                          unit_price=money_from_api(_first(li, "unitPrice", "price")),
                          line_total=money_from_api(_first(li, "total", "extendedPrice"))))
    kind = purchase_kind(ptype)
    date = _datetime_value(_first(rec, "createdDateTime", "receiptCreateDateTime", "orderCreateDateTime", "purchaseDate"))
    p = Purchase(
        purchase_type=kind,
        purchase_date=date,
        order_number=key,
        total=money_from_api(_first(rec, "total", "orderTotal", "grandTotal")),
        status=parse_status(str(_first(rec, "status", default=""))),
        store_info=purchase_label(ptype) or "Costco",
        # NOT summary. The summary becomes the PDF's filename, and a
        # receipt that fails before it is classified would be saved
        # under the whole row's text, timestamp and all.
        notes=("Row: " + str(_first(rec, "cardText", default="") or ""))[:300],
        # The href the page itself drew, when there is one and it is on
        # Costco. A link the site made is worth more than a URL this app
        # assembled from a guess at the path.
        details_url=href or details_url(key),
        receipt_url=href or details_url(key),
        fulfillment=str(_first(rec, "tab", default="") or ""),
        items=items,
        discovered_at=now_iso(),
    )
    if record_is_pending(rec):
        p.status = p.status or "Pending"
        p.notes = ("Pending order, no receipt yet. " + p.notes)[:300]
    return p


# ---------------------------------------------------------------------------
# The receipt page = the receipt
# ---------------------------------------------------------------------------

# The block a person is actually looking at. Bootstrap keeps a hidden
# copy of the modal in the markup, so a selector is not enough, and the
# biggest visible match is. Shared by every piece of code below that has
# to find the receipt, because they all fell for the hidden one.
_VISIBLE_JS = r"""
  const onScreen = (el) => {
    const r = el.getBoundingClientRect();
    if (r.width < 80 || r.height < 80) return false;
    const s = getComputedStyle(el);
    return s.display !== 'none' && s.visibility !== 'hidden' && s.opacity !== '0';
  };
  const pick = (sel) => {
    let best = null, most = -1;
    for (const el of document.querySelectorAll(sel)) {
      if (!onScreen(el)) continue;
      const n = (el.innerText || '').length;
      if (n > most) { most = n; best = el; }
    }
    return best;
  };
"""

_FIND_RECEIPT_JS = "(area) => {" + _VISIBLE_JS + """
  const n = pick(area);
  if (!n) return null;
  const r = n.getBoundingClientRect();
  return {text: (n.innerText || '').slice(0, 20000),
          width: Math.round(r.width), height: Math.round(n.scrollHeight)};
}"""


def visible_receipt(page) -> Optional[dict]:
    """The receipt on screen, as its text and its size, or None."""
    try:
        got = page.evaluate(_FIND_RECEIPT_JS, FALLBACK["receipt_area"])
    except Exception as e:
        log.debug("Could not look for the receipt: %s", e)
        return None
    return got if isinstance(got, dict) else None


def receipt_text(page) -> str:
    got = visible_receipt(page)
    return (got or {}).get("text") or ""


def on_receipt_page(page) -> bool:
    """Either half counts. A warehouse receipt is a dialog with no
    address of its own, an online one is the print view."""
    if PRINT_VIEW_PATH.lower() in (page.url or "").lower():
        return True
    return dialog_open(page)


def dialog_open(page) -> bool:
    """On screen, not merely present. Bootstrap's hidden copy is always
    present."""
    return visible_receipt(page) is not None


def close_dialog(page) -> None:
    """Dismiss the receipt dialog, Escape first.

    Escape rather than the Close button, because Escape is not a control
    and cannot be the wrong one. A page that ignores it falls back to the
    dialog's own Close, found inside the dialog rather than by name, so
    there is no way to reach a "Close Account" somewhere else on the
    page."""
    if not dialog_open(page):
        return
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(400)
    except Exception:
        pass
    if not dialog_open(page):
        return
    try:
        button = page.locator(FALLBACK["dialog_close"]).first
        if button.count():
            button.click(timeout=5000)
            page.wait_for_timeout(400)
    except Exception as e:
        log.warning("Could not close the receipt dialog: %s", e)


def goto_receipt(page, purchase: Purchase) -> None:
    """Put this purchase's receipt on screen, whichever half it is from."""
    if purchase.purchase_type == IN_STORE:
        open_warehouse_receipt(page, purchase)
    else:
        open_online_invoice(page, purchase)


# -- the warehouse half, which is a dialog --------------------------------------

def open_warehouse_receipt(page, purchase: Purchase) -> None:
    """Find this receipt's row again and press its View Receipt.

    A warehouse receipt has no address, so there is nothing to navigate
    to and the row has to be found the way a person finds it. Back to the
    tab, forward to the quarter the date falls in, then the row whose
    date and total are this purchase's.

    The page is asked for fresh, and no longer has to be. Saving the one
    before it used to hide every element on this page except the dialog
    and leave them that way, so the first receipt of a run worked and
    every one after it failed to open. A capture puts the page back now,
    in a finally, and this reload is belt as well as braces, because a
    quarter that has been paged through is not in the state a lookup
    expects either."""
    _note("op", "open_item", "open a warehouse receipt")
    close_dialog(page)
    goto_orders(page, fresh=True)
    _note("checkpoint", "back on the list", page)
    if not open_tab(page, TAB_WAREHOUSE):
        raise RuntimeError("could not open the Warehouse tab")
    log.debug("Back on the Warehouse tab, looking for %s", purchase.purchase_date)

    # The key discovery gave it, not one rebuilt from the fields here.
    # Rebuilding it needs the warehouse name, and a Purchase carries the
    # kind of place rather than which one, so every lookup asked for
    # wh-<date>-<total>-InWarehouse and no row ever answered. A live run
    # found that on the first receipt it tried to open.
    wanted = purchase.order_number
    # Whatever the picker is showing, then the quarters the date falls
    # in, then the rest. The picker keeps whichever quarter the last
    # receipt needed, so "what it shows now" is not a range this app can
    # reason about, and two receipts a fortnight apart failed to open
    # because only the covering quarters were tried after it had moved.
    every = ranges_for(page)
    covering = [o for o in every if range_covers(o, purchase.purchase_date)]
    order = [None] + covering + [o for o in every if o not in covering]
    for option in order:
        if option is not None and not select_range(page, option):
            continue
        for row in read_rows(page):
            if record_key(row) != wanted:
                continue
            press_view_receipt(page, row.get("index", 0))
            if wait_for_receipt(page):
                return
            close_dialog(page)
    raise RuntimeError("no row on the Warehouse tab matches this receipt")


def press_view_receipt(page, index: int) -> None:
    """Press the control read_rows took as row `index`.

    Asked for by the mark read_rows left on it, so this is the same
    element and not the nth of a list assembled differently. Its name is
    checked against the guard first, because a control in that place
    saying something else is a page this app no longer understands."""
    button = page.locator('[data-pp-row="%d"]' % int(index)).first
    # Both numbers, named. Counting one collection and pressing the nth
    # of another is the bug this records, and it reads from outside
    # exactly like a page that did not load.
    _note("chose", "receipt_button", "rows the reader marked",
          candidates=page.locator("[data-pp-row]").count(),
          ordinal=int(index), precondition="visible")
    if button.count() == 0:
        raise RuntimeError("that row is no longer on the page")
    name = (button.inner_text(timeout=2000) or "").strip()
    if not is_safe_control(name):
        raise RuntimeError("refusing to press a control called %r" % name)
    button.click(timeout=15000)


def wait_for_receipt(page, timeout_ms: int = 30000) -> bool:
    """The dialog, or the print view, or the page saying it could not."""
    try:
        page.wait_for_function(
            "([area, failed, printPath]) => {" + _VISIBLE_JS + """
                 if (pick(area)) return true;
                 if (location.href.toLowerCase().includes(printPath)) return true;
                 return new RegExp(failed, 'i').test(document.body.innerText || '');
               }""",
            arg=[FALLBACK["receipt_area"], RECEIPT_FAILED_RE.pattern,
                 PRINT_VIEW_PATH.lower()],
            timeout=timeout_ms)
    except Exception:
        log.warning("No receipt appeared within %dms", timeout_ms)
        return False
    settle(page, 8000)
    return True


# -- the online half, which is two links ----------------------------------------

def open_online_invoice(page, purchase: Purchase) -> None:
    """The order's own details page, then its printable invoice.

    Both steps are links with real addresses, so this reads the address
    and goes there. Print Invoice is never pressed. Pressing it once
    navigates, and pressing it again on the page it lands on calls
    window.print(), which opens a dialog no program can dismiss."""
    url = purchase.details_url or purchase.receipt_url or ""
    if not is_safe_url(url):
        url = details_url(purchase.order_number)
    if not is_safe_url(url):
        raise ValueError("refusing to open a URL that is not on costco.com")
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    settle(page)

    printable = print_view_url(page, wait_ms=20000)
    if printable:
        page.goto(printable, wait_until="domcontentloaded", timeout=60000)
        settle(page)
    else:
        log.warning("No Print Invoice link on this order, saving the details "
                    "page instead")
    wait_for_receipt(page)


def print_view_url(page, wait_ms: int = 0) -> str:
    """Where Print Invoice points, read rather than pressed.

    Waited for, because the order details page is drawn by the app after
    the shell arrives and a first look finds nothing. A live run decided
    two orders had no invoice at all, and they both did."""
    link = page.locator(FALLBACK["print_invoice"]).first
    if wait_ms:
        try:
            link.wait_for(state="attached", timeout=wait_ms)
        except Exception:
            pass
    try:
        if link.count() == 0:
            return ""
        href = link.get_attribute("href") or ""
    except Exception as e:
        log.warning("Could not read the Print Invoice link: %s", e)
        return ""
    if href.startswith("/"):
        href = BASE + href
    return href if is_safe_url(href) and PRINT_VIEW_PATH.lower() in href.lower() else ""


def receipt_is_present(page) -> bool:
    """Something with money in it, in the dialog or on the print view."""
    text = receipt_text(page)
    if text and MONEY_RE.search(text):
        return True
    if PRINT_VIEW_PATH.lower() in (page.url or "").lower():
        try:
            body = page.locator("body").inner_text(timeout=5000)
        except Exception:
            return False
        return bool(body and MONEY_RE.search(body))
    return False


def receipt_failed(page) -> bool:
    try:
        body = page.locator("body").inner_text(timeout=5000)
    except Exception:
        return False
    return bool(RECEIPT_FAILED_RE.search(body))


# A Costco warehouse receipt line, as one reads on screen.
#
#     E     933402  DORITOS 30Z     7.29 3
#           512599  **KS TOWEL**   20.79 Y
#
# An optional department letter, the item number, the name, the price,
# and a tax code. No currency sign anywhere, which is why the first
# version of this found no items at all and every receipt was filed as
# "Mixed Purchases". The item number is what tells a line from a total,
# since SUBTOTAL and TAX have no number in front of them.
_ITEM_LINE_RE = re.compile(
    r"^(?:(?P<dept>[A-Z])\s+)?(?P<num>\d{5,8})\s+"
    r"(?P<name>\S.*?)\s+"
    r"(?P<price>-?[\d,]+\.\d{2})(?P<sign>-)?"
    r"(?:\s+(?P<code>[A-Z0-9]))?\s*$")

# The online invoice is a table, and a table read as text gives one
# cell per line. An item is six of them.
#
#     Sour Punch Twists, Variety, 180-count     the name
#     Item 12345678                             Costco's item number
#     $12.34                                    unit price
#     1                                         quantity
#     Delivered                                 status
#     $12.34                                    total price
#
# The item number line is the anchor, because it is the only one whose
# shape cannot be anything else.
_ONLINE_ANCHOR_RE = re.compile(r"^item\s+#?\s*(\d{5,12})$", re.I)
_MONEY_ONLY_RE = re.compile(r"^\$\s*(-?[\d,]+\.\d{2})$")
_QTY_ONLY_RE = re.compile(r"^(\d{1,4})$")

# A one line invoice, kept for a layout that is not a table.
_ONLINE_ITEM_QTY_RE = re.compile(
    r"^(?P<name>.+?)\s+(?P<qty>\d+)\s*(?:x|@)\s*"
    r"\$\s*[\d,]+\.\d{2}\s+\$\s*(?P<price>-?[\d,]+\.\d{2})\s*$")
_ONLINE_ITEM_RE = re.compile(
    r"^(?P<name>.+?)\s+\$\s*(?P<price>-?[\d,]+\.\d{2})\s*$")

# Lines that carry a number and a price and are still not a purchase.
_NOT_AN_ITEM_RE = re.compile(
    r"^(sub\s*total|subtotal|total|tax|sales\s+tax|total\s+tax|savings|"
    r"total\s+savings|instant\s+savings|coupons?|discounts?|tip|gratuity|"
    r"fees?|shipping|handling|delivery\s+fee|service\s+fee|surcharge|"
    r"balance|change|payment|paid|amount|amount\s+(due|paid)|"
    r"visa|mastercard|master\s*card|discover|amex|american\s+express|"
    r"debit|credit|cash|ebt|snap|gift\s+card|refund|member|whse|trm|trn|opt|"
    r"items?\s+sold|total\s+number\s+of\s+items?|approved)\b", re.I)


def _clean_item_name(name: str) -> str:
    """A name as a person would write it down. Costco wraps some in
    asterisks, which mean something to Costco and nothing here."""
    name = _html.unescape(re.sub(r"\s+", " ", name or "")).strip()
    name = name.strip("*").strip(" -:")
    if len(name) < 2 or _NOT_AN_ITEM_RE.match(name):
        return ""
    return name


def _online_table_items(lines: List[str]) -> List[Item]:
    """The six line blocks on an online invoice, if that is what this is.

    Anchored on the item number, because the name above it can be
    anything and the four lines below it can each be missing."""
    items: List[Item] = []
    for i, line in enumerate(lines):
        if not _ONLINE_ANCHOR_RE.match(line):
            continue
        name = ""
        for back in range(i - 1, max(-1, i - 4), -1):
            candidate = _clean_item_name(lines[back])
            if candidate and not _MONEY_ONLY_RE.match(lines[back]):
                name = candidate
                break
        if not name:
            continue
        money, qty = [], "1"
        for ahead in range(i + 1, min(len(lines), i + 7)):
            ahead_line = lines[ahead]
            if _ONLINE_ANCHOR_RE.match(ahead_line):
                break
            m = _MONEY_ONLY_RE.match(ahead_line)
            if m:
                money.append(m.group(1))
                continue
            q = _QTY_ONLY_RE.match(ahead_line)
            if q and qty == "1":
                qty = q.group(1)
        total = money[-1] if money else ""
        items.append(Item(name=name[:300], quantity=qty,
                          unit_price="$" + money[0] if money else "",
                          line_total="$" + total if total else ""))
    return items


def extract_items(page) -> List[Item]:
    """Line items from the receipt on screen, warehouse or online."""
    return items_from_text(receipt_text(page) or _page_text(page))


def _page_text(page) -> str:
    try:
        return page.locator("body").inner_text(timeout=8000) or ""
    except Exception:
        return ""


def items_from_text(text: str) -> List[Item]:
    """Kept apart from the page so a real receipt can be tested."""
    lines = [ln.strip() for ln in (text or "").splitlines()]
    items = _online_table_items(lines)
    if items:
        return items
    for raw in lines:
        line = raw.strip()
        if not line or _NOT_AN_ITEM_RE.match(line):
            continue
        m = _ITEM_LINE_RE.match(line)
        if m:
            name = _clean_item_name(m.group("name"))
            if not name:
                continue
            price = m.group("price")
            if m.group("sign"):
                price = "-" + price
            items.append(Item(name=name[:300], quantity="1",
                              line_total="$" + price.lstrip("-").lstrip()
                              if not price.startswith("-") else "-$" + price[1:]))
            continue
        m = _ONLINE_ITEM_QTY_RE.match(line) or _ONLINE_ITEM_RE.match(line)
        if m:
            name = _clean_item_name(m.group("name"))
            if name:
                qty = m.groupdict().get("qty") or "1"
                items.append(Item(name=name[:300], quantity=qty,
                                  line_total="$" + m.group("price")))
    return items


def extract_details(page, purchase: Purchase) -> Purchase:
    """Fill in what the rendered receipt says. The API record already gave
    the date, total and type, so this only fills gaps and reads items."""
    text = receipt_text(page) or _page_text(page)
    if text:
        # "**** TOTAL 50.59", with no currency sign, which is how a till
        # prints it.
        m = re.search(r"^\s*\**\s*total\s*:?\s*\$?\s*([\d,]+\.\d{2})\s*$",
                      text, re.I | re.M)
        if m and not purchase.total:
            purchase.total = f"${m.group(1)}"
        m = re.search(r"(\d{1,2}/\d{1,2}/\d{2,4})", text)
        if m and not purchase.purchase_date:
            mm, dd, yy = m.group(1).split("/")
            yy = yy if len(yy) == 4 else "20" + yy
            purchase.purchase_date = f"{yy}-{int(mm):02d}-{int(dd):02d}"
    items = extract_items(page)
    if items:
        purchase.items = items
    return purchase


def scroll_full_page(page, rounds: int = 2, delay_ms: int = 400) -> None:
    for _ in range(rounds):
        try:
            page.mouse.wheel(0, 3000)
            page.wait_for_timeout(delay_ms)
        except Exception:
            break
    try:
        page.evaluate("() => window.scrollTo(0, 0)")
    except Exception:
        pass


# Everything outside the receipt is hidden, a live DOM display change
# only, discarded on the next navigation. For a warehouse receipt that
# means the dialog and nothing else, including the backdrop the dialog
# sits on, which is what would otherwise print as a grey page. The
# dialog's own Print Receipt link and its Close button are hidden too,
# and never pressed. On the online print view there is nothing to hide,
# because that page is already only the invoice.
_ISOLATE_RECEIPT_JS = "([area, printText]) => {" + _VISIBLE_JS + r"""
  const n = pick(area);
  if (!n) {
    // The online print view. Costco serves it as a page of its own with
    // nothing else on it, so there is nothing to take away.
    document.body.style.zoom = '1';
    window.scrollTo(0, 0);
    return true;
  }
  let el = n;
  while (el && el.parentElement && el !== document.body) {
    for (const s of Array.from(el.parentElement.children)) {
      if (s !== el) s.style.display = 'none';
    }
    el = el.parentElement;
  }
  // The dialog's own controls. A printed receipt with a Print Receipt
  // link and a Close button in it looks like a screenshot of a website.
  // Plain CSS and a text test, because this runs in the browser, which
  // has never heard of :has-text(). The isolation was the second place
  // that got wrong, after discovery.
  const saysPrint = new RegExp(printText, 'i');
  for (const x of n.querySelectorAll('button, [role=button]')) x.style.display = 'none';
  for (const x of n.querySelectorAll('a')) {
    const label = (x.innerText || x.getAttribute('aria-label') || '').trim();
    if (!x.getAttribute('href') || x.getAttribute('href') === '#'
        || (label && saysPrint.test(label))) x.style.display = 'none';
  }
  // The dialog is positioned, so it keeps its own scroll. Let it grow to
  // its full height instead, or printToPDF captures one screen of it.
  for (const el of [n, n.parentElement].filter(Boolean)) {
    el.style.maxHeight = 'none';
    el.style.height = 'auto';
    el.style.overflow = 'visible';
    el.style.position = 'static';
  }
  // A modal locks the page behind it. Left on, printToPDF renders one
  // blank viewport and stops. The grey it dims the page with, and the
  // help tab bolted to the window, both print as well if left alone.
  for (const el of [document.documentElement, document.body]) {
    el.style.overflow = 'visible';
    el.style.height = 'auto';
    el.style.maxHeight = 'none';
    el.style.position = 'static';
    el.style.background = '#fff';
    el.style.backgroundColor = '#fff';
  }
  for (const el of document.querySelectorAll(
      '.modal-backdrop, [class*="backdrop" i], [class*="overlay" i]')) {
    el.style.display = 'none';
  }
  // Anything pinned to the window that is not part of the receipt. A
  // feedback tab, a cookie bar, a chat bubble. They sit outside the
  // block being kept, so hiding its siblings never reached them.
  for (const el of document.querySelectorAll('body *')) {
    if (el === n || n.contains(el) || el.contains(n)) continue;
    const s = getComputedStyle(el);
    if (s.position === 'fixed' || s.position === 'sticky') el.style.display = 'none';
  }
  const w = Math.max(n.scrollWidth, n.getBoundingClientRect().width);
  const zoom = Math.min(1, Math.max(0.5, 736 / (w + 16)));
  document.body.style.zoom = String(zoom);
  window.scrollTo(0, 0);
  return true;
}
"""


def isolate_receipt(page) -> bool:
    try:
        ok = bool(page.evaluate(_ISOLATE_RECEIPT_JS,
                                [FALLBACK["receipt_area"], PRINT_CONTROL_TEXT]))
    except Exception as e:
        log.warning("Receipt isolation failed: %s", e)
        return False
    if ok:
        page.wait_for_timeout(300)
    else:
        log.warning("Could not find the receipt block to isolate")
    return ok


# ---------------------------------------------------------------------------
# Diagnostics. What a tester sends back, with nothing personal in it.
# ---------------------------------------------------------------------------

# Two digits or more, so prices, dates, keys and card numbers all go, and
# a quantity of 2 or a page number 1 stays readable.
_DIGITS_RE = re.compile(r"\d{2,}")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")

# API fields whose values are safe to keep as they are (type names, status
# words, counts). Everything else that is a string is masked.
_KEEP_VALUES = {"purchaseType", "status", "fulfillmentType", "modality", "quantity", "pageNo",
                "pageSize", "pageTotal", "isLastPage", "itemType", "unitOfMeasure"}


# The owner's name and the rest of the redaction live in core. These apps
# had a fourth version of it, without the title and suffix exclusion, so
# every "Jr" and "II" on a page became [name].


# An online invoice prints the member's name and their shipping and
# billing address in full. Digits alone do not cover a street name, and
# the owner's name only covers the parts of it this app was told. SEEN
# on a live invoice, which is why this exists.
_ADDRESS_BLOCK_RE = re.compile(
    r"((?:shipping|billing|delivery|mailing)\s+address)"
    r"(?:(?!\n\s*\n)[\s\S]){0,200}", re.I)
_STREET_LINE_RE = re.compile(
    r"^\s*\d{1,6}\s+[A-Za-z0-9.' -]{2,40}"
    r"\s(?:st|street|ave|avenue|rd|road|dr|drive|ln|lane|ct|court|cir|circle|"
    r"blvd|boulevard|way|pl|place|ter|terrace|pkwy|parkway|hwy|highway)\.?\s*$",
    re.I | re.M)


def mask_text(s: str) -> str:
    s = s or ""
    for word in private_words():
        s = re.sub(re.escape(word), "[name]", s, flags=re.I)
    s = _EMAIL_RE.sub("<email>", s)
    s = _STREET_LINE_RE.sub("[address]", s)
    s = _ADDRESS_BLOCK_RE.sub(lambda m: m.group(1) + " [address]", s)
    return _DIGITS_RE.sub(lambda m: "#" * len(m.group(0)), s)


def mask_json(obj, key: str = "", depth: int = 0):
    """The SHAPE of an API answer: every key kept, string values masked
    except type and status words, lists cut to three entries."""
    if depth > 8:
        return "..."
    if isinstance(obj, dict):
        return {k: mask_json(v, k, depth + 1) for k, v in list(obj.items())[:60]}
    if isinstance(obj, list):
        return [mask_json(v, key, depth + 1) for v in obj[:3]] + (["... %d more" % (len(obj) - 3)] if len(obj) > 3 else [])
    if isinstance(obj, bool) or obj is None:
        return obj
    if isinstance(obj, (int, float)):
        return obj if key in _KEEP_VALUES else "<number>"
    s = str(obj)
    if key in _KEEP_VALUES and len(s) < 40:
        return s
    return mask_text(s)[:80]


@dataclass
class ReceiptSurvey:
    url: str = ""
    title: str = ""
    rendered: bool = False
    failed: bool = False
    lines: List[str] = field(default_factory=list)
    outline: List[str] = field(default_factory=list)
    controls: List[str] = field(default_factory=list)


_OUTLINE_JS = r"""
(area) => {
  const n = document.querySelector(area);
  if (!n) return [];
  const out = [];
  const walk = (el, d) => {
    if (d > 6 || out.length > 200) return;
    const tag = el.tagName.toLowerCase();
    const cls = (el.className || '').toString().split(' ').filter(Boolean).slice(0, 3).join('.');
    const tid = el.getAttribute('data-testid') || el.getAttribute('data-test') || '';
    out.push('  '.repeat(d) + tag + (cls ? '.' + cls : '') + (tid ? ' [' + tid + ']' : '') + (el.children.length ? '' : ' = ' + (el.innerText || '').trim().length + ' chars'));
    for (const c of el.children) walk(c, d + 1);
  };
  walk(n, 0);
  return out;
}
"""


def survey_receipt_page(page) -> ReceiptSurvey:
    """The receipt page as the tester's browser shows it, with every
    number of two digits or more and every email masked."""
    s = ReceiptSurvey(url=mask_text(page.url or ""))
    try:
        s.title = page.title() or ""
    except Exception:
        pass
    s.rendered = receipt_is_present(page)
    s.failed = receipt_failed(page)
    try:
        area = page.locator(FALLBACK["receipt_area"]).first if page.locator(FALLBACK["receipt_area"]).count() else page.locator(FALLBACK["receipt_shell"]).first
        text = area.inner_text(timeout=5000) if area.count() else ""
        s.lines = [mask_text(ln.strip()) for ln in text.splitlines() if ln.strip()][:120]
    except Exception:
        pass
    try:
        s.outline = page.evaluate(_OUTLINE_JS, FALLBACK["receipt_area"]) or []
    except Exception:
        pass
    try:
        for b in page.locator("button, a[role=button], [role=tab]").all()[:60]:
            t = (b.inner_text(timeout=500) or "").strip()
            if t and len(t) < 60:
                s.controls.append(f"{mask_text(t)} -> {'safe' if is_safe_control(t) else 'not clicked'}")
    except Exception:
        pass
    return s


def survey_history_page(page) -> dict:
    """Orders & Purchases as a tester's browser shows it, masked.

    Both tabs, because they are two different lists, and the quarters the
    picker offers, because without touching it a run sees three months."""
    out = {"url": mask_text(page.url or ""), "title": "",
           "state": history_state(page), "tabs": [], "ranges": [],
           "api": {"endpoint": ORDER_API,
                   "note": "not called by this app, see the module docstring"},
           "per_tab": {}}
    try:
        out["title"] = page.title() or ""
    except Exception:
        pass
    out["tabs"] = tab_names(page)
    for tab in (TAB_WAREHOUSE, TAB_ONLINE):
        info = {"opened": False, "rows": 0, "sample": [], "state": ""}
        if open_tab(page, tab):
            info["opened"] = True
            if not out["ranges"]:
                out["ranges"] = range_options(page)
            rows = read_rows(page)
            info["rows"] = len(rows)
            info["state"] = history_state(page)
            info["sample"] = mask_json(rows[:3])
            parsed = []
            for rec in rows[:3]:
                p = record_to_purchase(dict(rec, tab=tab))
                parsed.append({"key_shape": mask_text(p.order_number),
                               "kind": p.purchase_type, "date": p.purchase_date,
                               "total": p.total, "label": p.store_info,
                               "pending": record_is_pending(rec)}
                              if p else "row without anything to key it by")
            info["parsed"] = parsed
        out["per_tab"][tab] = info
    return out


# ---------------------------------------------------------------------------
# Kept for the shared orchestrator's diagnose command
# ---------------------------------------------------------------------------

def open_receipt_section(page) -> bool:
    return receipt_is_present(page)


def find_print_receipt_controls(page) -> list:
    try:
        return page.locator(FALLBACK["print_button"]).all()
    except Exception:
        return []


def find_invoice_controls(page) -> list:
    return []


def find_printing_frame(page, wait_ms: int = 2000):
    return None


def find_receipt_iframe(page):
    return None


ALLOWED_HOSTS = {"costco.com"}


def is_safe_url(url: str) -> bool:
    """True only for an https URL on one of this provider's own hosts.

    The check itself lives in the core, so all of them answer the same way.
    This app keeps the hosts, which is the part that really is its own."""
    return _host_allows(url, ALLOWED_HOSTS)


def to_json(obj) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False, default=str)
