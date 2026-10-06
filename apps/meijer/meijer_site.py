"""ALL meijer.com selectors, URL patterns, and page behavior live here.

When Meijer changes its website, repair this file only.

STATUS: round two (#42), repaired from a tester's survey and screenshots.
Written without a Meijer account, so what follows is what his own pages
showed.

* ``https://www.meijer.com/shopping/orders.html`` is titled "Your Orders"
  and shows "Orders and Receipts" with TWO TABS, "Online Orders" and
  "In-Store Receipts". It opens on Online Orders, which for a person who
  only shops in the store reads "You haven't placed any orders yet", and
  every purchase sits behind the second tab. Round one read the first tab
  only and reported nothing. Both tabs are read now, and a receipt from
  the store is filed under In-Store.
* An in-store row reads "In-Store: 09/19/2026", the store's address, then
  "$31.23 - 15 items", with a PDF icon at the right end of the row. That
  icon is the receipt, and the page warns that a pop-up blocker will get
  in its way, so it opens a window rather than a link.
* The page fills the online tab from ``/bin/meijer/order``. What the
  in-store tab calls has not been seen, so the rows are read from the
  page, and the survey records every answer either tab loads.

* The orders page is ``https://www.meijer.com/shopping/orders.html``
  (#42), pickup and delivery orders. In-store purchases show up as
  digital receipts under mPerks when the loyalty account is linked, and
  the route for those is a GUESS the survey will settle.
* Each order row (GUESS at the markup, a card or a list item) carries a
  date, a total and a link to the order's details or receipt. The
  details page, or a receipt link on it, is the document.
* Capture (GUESS at which applies): a link that points at a PDF is
  fetched from inside the signed-in page and saved. A details page is
  opened and its receipt block printed to PDF. Nothing is clicked.
* meijer.com sits behind bot protection, so the app drives the browser
  already on the machine.

The guesses that most need confirming from a survey are marked GUESS.

SAFETY (this is a shopping account with a card on file):
  This module is strictly READ-ONLY. It opens the orders and receipts
  pages, reads the lists, and saves what Meijer already rendered. It must
  NEVER add to a cart, reorder, clip a coupon, redeem mPerks rewards,
  refill a prescription, cancel or modify an order, or edit any setting.
  FORBIDDEN_CONTROL_RE is the guard, and nothing is clicked at all.
"""
from __future__ import annotations

import base64
import hashlib
import html as _html
import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional
from urllib.parse import urljoin, urlsplit

from paperpull_core import page_check as _page_check
from paperpull_core.models import IN_STORE, ONLINE, Item, Purchase
from storage import now_iso

from paperpull_core.redact import private_words, set_private_words  # noqa: F401
from paperpull_core.urls import is_safe_url as _host_allows
from paperpull_core.capture import fetch_with_status as _fetch_with_status
from paperpull_core.dates import checked as _checked_date

log = logging.getLogger("meijer_receipts.site")

# ---------------------------------------------------------------------------
# URLs
# ---------------------------------------------------------------------------

BASE = "https://www.meijer.com"
ORDERS_URL = f"{BASE}/shopping/orders.html"
# GUESS at everything but the first. The orders page the requester named,
# then the places in-store digital receipts are likely to live, then the
# account page whose own links name the real ones.
ORDER_CANDIDATES = [
    ORDERS_URL,
    f"{BASE}/shopping/mperks/receipts.html",
    f"{BASE}/shopping/receipts.html",
    f"{BASE}/shopping/account.html",
]
URLS = {
    "home": ORDERS_URL,
    "orders": ORDERS_URL,
    "account": f"{BASE}/shopping/account.html",
}

LOGIN_URL_MARKERS = ["/login", "/signin", "/sign-in", "/register", "/authenticate", "/mfa",
                     "/verification", "login.meijer"]

# Where the rows live. GUESS. The main content, and within it anything
# list-like holding a money amount and a date.
FRAME = "main, [role=main], #main, body"
FALLBACK = {
    "frame": FRAME,
    "row": "main table tbody tr, main [role=row], main ul li, main [class*='order'], main [class*='Order'], "
           "main [class*='receipt'], main [class*='Receipt'], main [class*='card'], main [class*='Card'], "
           "main [data-testid*='order'], main [data-testid*='receipt']",
    "receipt_link": "a[href*='receipt'], a[href*='order'], a[aria-label*='eceipt'], a[aria-label*='rder'], a[download]",
    "receipt_area": "main, [role=main], body",
    "page_ready": "main, [role=main]",
    "print_page_body": "body",
}

EMPTY_RE = re.compile(r"(no|don't\s+have\s+any|haven't\s+placed\s+any)\s+(orders?|purchases?|receipts?)|"
                      r"you\s+have\s+no\s+(orders|receipts)|nothing\s+to\s+show", re.I)
MONEY_RE = re.compile(r"\$\s*(-?[\d,]+\.\d{2})")
_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
DATE_PATTERNS = [
    (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})(?!\d)"), "iso"),
    (re.compile(r"\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
                r"Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?\s+(\d{1,2}),?\s+(\d{4})\b", re.I), "mdy"),
    (re.compile(r"\b(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(\d{4})\b", re.I), "dmy"),
    (re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b"), "us"),
]

# ---------------------------------------------------------------------------
# Guards. This is a settings area with a card on file. Nothing here is
# clicked but a receipt's own link, and the guard grades everything.
# ---------------------------------------------------------------------------
FORBIDDEN_CONTROL_RE = re.compile(
    r"(add\s+(all\s+)?to\s+(cart|list)|add\s+all|buy\s+(it\s+)?again|reorder|checkout|"
    r"start\s+(your\s+)?order|modify\s+order|edit\s+order|cancel\s+order|cancel|"
    r"request\s+(a\s+)?refund|refund|return\s+item|report\s+(a\s+)?problem|"
    r"clip|coupon|\bmperks?\s+(rewards?|redeem)|redeem|rewards?\b|points|"
    r"refill|prescription|pharmacy|transfer|"
    r"pay\s+now|\bpay\b|payment|\bcard\b|\bcards\b|wallet|"
    r"contact\s+us|customer\s+(care|support|service)|\bchat\b|feedback|survey|"
    r"delete|remove|subscribe|unsubscribe|apply\s+now|sign\s+out|log\s+out|"
    r"edit|save|update|change|manage|settings|preferences|profile|\baddress\b|password|"
    r"tip|substitut|rate\b|review)", re.I)

try:
    from paperpull_core.controls import SETTINGS_CONTROL_RE as _SHARED_SETTINGS
    FORBIDDEN_CONTROL_RE = re.compile(
        "(?:%s)|(?:%s)" % (FORBIDDEN_CONTROL_RE.pattern, _SHARED_SETTINGS.pattern),
        re.I)
except Exception:  # the shared core is optional at import time
    pass

SAFE_DOC_CONTROL_RE = re.compile(
    r"(receipt|invoice|view\s+(receipt|order|details|order\s+details)|order\s+details|"
    r"order\s+history|purchase\s+history|my\s+orders|see\s+(more|all|older)|show\s+(more|all|older)|"
    r"load\s+more|next|previous|older|newer|page\s+\d+)", re.I)

SECURITY_CHALLENGE_MARKERS = [
    "verify your identity", "enter the code", "verification code", "one-time",
    "are you a robot", "verify you are human", "checking your browser",
    "access denied", "pardon our interruption", "press & hold", "press and hold",
]

RATE_LIMIT_MARKERS = [
    "too many requests", "rate limit", "try again later",
    "temporarily blocked", "http error 429",
]


def _parse_date_from_page(text: str) -> Optional[str]:
    for rx, kind in DATE_PATTERNS:
        m = rx.search(text or "")
        if not m:
            continue
        try:
            if kind == "iso":
                y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            elif kind == "mdy":
                mo, d, y = _MONTHS[m.group(1)[:3].lower()], int(m.group(2)), int(m.group(3))
            elif kind == "dmy":
                d, mo, y = int(m.group(1)), _MONTHS[m.group(2)[:3].lower()], int(m.group(3))
            else:
                mo, d, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if 1 <= mo <= 12 and 1 <= d <= 31:
                return f"{y:04d}-{mo:02d}-{d:02d}"
        except (ValueError, KeyError):
            continue
    return None


def parse_date(text):
    """The date this provider's page is showing, as YYYY-MM-DD.

    The reading is below, unchanged. This only refuses to believe a result
    that names a day which does not exist, because a reference number is
    shaped like a date and used to be taken for one."""
    return _checked_date(_parse_date_from_page(text), None)


def parse_money(text: str) -> str:
    m = MONEY_RE.search(text or "")
    return f"${m.group(1)}" if m else ""


def looks_signed_out(page) -> bool:
    url = (page.url or "").lower()
    if any(m in url for m in LOGIN_URL_MARKERS):
        return True
    try:
        body = page.locator("body").inner_text(timeout=5000).lower()
    except Exception:
        return False
    return ("sign in" in body[:3000] and "password" in body[:3000]) and "order" not in body[:3000]


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


ALLOWED_HOSTS = {"meijer.com"}


def is_safe_url(url: str) -> bool:
    """True only for an https URL on one of this provider's own hosts.

    The check itself lives in the core, so all of them answer the same way.
    This app keeps the hosts, which is the part that really is its own."""
    return _host_allows(url, ALLOWED_HOSTS)


# ---------------------------------------------------------------------------
# The payment history
# ---------------------------------------------------------------------------

def orders_url(page_no: int = 1) -> str:
    return f"{ORDERS_URL}?page={page_no}" if page_no > 1 else ORDERS_URL


# The two tabs, and the folder a purchase from each belongs in.
TAB_IN_STORE_RE = re.compile(r"^\s*in-?store\s+receipts?\s*$", re.I)
# A row's receipt control, as a recording found it. It is a LINK reading
# "view receipt pdf", and pressing it opens a tab rather than downloading
# anything, which is what the page's own pop-up blocker warning is about.
# Round two guessed a PDF icon carrying no text at all (#42).
RECEIPT_LINK_RE = re.compile(r"^\s*view\s+receipt(\s+pdf)?\s*$", re.I)
TAB_ONLINE_RE = re.compile(r"^\s*online\s+orders?\s*$", re.I)
IN_STORE_ROW_RE = re.compile(r"\bin-?store\b\s*:", re.I)


# How long a tab is given to start drawing once it is pressed.
TAB_PAUSE_MS = 2500


def open_tab(page, pattern) -> bool:
    """Show one of the two tabs. A tab is not a control that buys or
    changes anything, and its name has to read as one of the two."""
    try:
        for role in ("tab", "button", "link"):
            loc = page.get_by_role(role, name=pattern)
            for i in range(min(loc.count(), 4)):
                el = loc.nth(i)
                if not el.is_visible():
                    continue
                label = (el.inner_text(timeout=800) or "").strip()
                if not pattern.match(label) or FORBIDDEN_CONTROL_RE.search(label):
                    continue
                el.click(timeout=5000)
                page.wait_for_timeout(TAB_PAUSE_MS)
                return True
        # Not a role the page declares, so by its text.
        loc = page.get_by_text(pattern)
        for i in range(min(loc.count(), 4)):
            el = loc.nth(i)
            if el.is_visible():
                el.click(timeout=5000)
                page.wait_for_timeout(TAB_PAUSE_MS)
                return True
    except Exception as e:
        log.info("could not open the tab: %s", e)
    return False


def _looks_like_orders(page) -> bool:
    try:
        text = page.locator(FRAME).first.inner_text(timeout=5000)
    except Exception:
        return False
    return bool(EMPTY_RE.search(text) or (MONEY_RE.search(text) and re.search(r"order|receipt|purchase", text, re.I)))


# How long each try at the orders page gets to draw its main content, and how
# long it is left to settle after that. The list can come a moment after the
# page, and a bot check can hold the page blank while it decides and only
# then show itself, so a page the list never came to is watched for
# CHALLENGE_WAIT_MS more, for the list or a check, whichever comes.
ORDERS_WAIT_MS = 15000
SETTLE_MS = 2500
CHALLENGE_WAIT_MS = 30000


def goto_orders(page, page_no: int = 1) -> bool:
    """Open the orders page. On the first page, try each candidate route
    in turn and stay on the first that is signed in and looks like a list
    of orders or says there are none. True when the list is on the page,
    which orders_listed says.

    False is not an empty history and not a signed-in session. A page can
    sit blank while a bot check decides and only then turn into the check,
    so one look at it finds nothing to name."""
    if page_no > 1:
        page.goto(orders_url(page_no), wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(SETTLE_MS)
        return orders_listed(page)
    for url in ORDER_CANDIDATES:
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        try:
            page.wait_for_selector(FALLBACK["page_ready"], timeout=ORDERS_WAIT_MS)
        except Exception:
            pass
        page.wait_for_timeout(SETTLE_MS)
        if looks_signed_out(page):
            return False
        if _looks_like_orders(page):
            return orders_listed(page)
    page.goto(ORDERS_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(SETTLE_MS)
    return orders_listed(page)


def history_state(page) -> str:
    """"empty" when the page says there are no orders, else ""."""
    try:
        text = page.locator(FRAME).first.inner_text(timeout=5000)
    except Exception:
        return ""
    return "empty" if EMPTY_RE.search(text) else ""


# Both of the orders page's tabs, drawn in its main content. A label is the
# words an element shows, as open_tab reads it, so the words of anything
# hidden inside it are left out, and the spacing around them does not count.
_TABS_SHOWING_JS = r"""([online, inStore]) => {
  const root = document.querySelector('main, [role=main], #main') || document.body;
  if (!root) return false;
  const named = [new RegExp(online, 'i'), new RegExp(inStore, 'i')];
  const seen = [false, false];
  for (const el of root.querySelectorAll('*')) {
    const words = el.textContent || '';
    if (words.length > 2000 || words.replace(/\s+/g, ' ').trim().length > 80) continue;
    if (!el.getClientRects().length || getComputedStyle(el).visibility === 'hidden') continue;
    const label = (el.innerText || '').replace(/\s+/g, ' ').trim();
    named.forEach((re, i) => { if (!seen[i] && re.test(label)) seen[i] = true; });
    if (seen[0] && seen[1]) return true;
  }
  return false;
}"""

# The words of the page's main content, or of the whole page when it has no
# main content.
_LIST_WORDS_JS = r"""() => {
  const root = document.querySelector('main, [role=main], #main') || document.body;
  return root ? (root.innerText || '') : '';
}"""

# The Online tab's own sentence for an account with no online orders, as a
# tester's page showed it (#42). EMPTY_RE is wider than that, and a line such
# as "No purchase necessary" anywhere on a page would pass for it.
NO_ORDERS_YET_RE = re.compile(r"haven[’']?t\s+placed\s+any\s+orders", re.I)


def orders_listed(page) -> bool:
    """Whether the orders page has drawn its list now, its two tabs, a row
    with a date and an amount on it, or the Online tab's own sentence for no
    orders, in the page's main content. Nothing is waited for.

    An amount anywhere on the page and the word order are enough for
    _looks_like_orders, and the list's own heading gives the word. A
    tester's Run All met a page that drew only that heading and a line
    under it, no tabs and no rows (#42), and a page still blank while a bot
    check decides has none of it either."""
    try:
        if page.evaluate(_TABS_SHOWING_JS, [TAB_ONLINE_RE.pattern, TAB_IN_STORE_RE.pattern]):
            return True
    except Exception:
        pass
    if any(parse_date(c.text) and parse_money(c.text) for c in collect_cards(page)):
        return True
    try:
        return bool(NO_ORDERS_YET_RE.search(page.evaluate(_LIST_WORDS_JS) or ""))
    except Exception:
        return False


def challenge_after_a_moment(page, wait_ms: Optional[int] = None) -> Optional[str]:
    """A security challenge on a page the list never came to, looked for
    several times over a little while rather than once.

    None when there is still none when the time is up, and also when the
    list turns up after all, which the caller asks orders_listed about."""
    wait_ms = CHALLENGE_WAIT_MS if wait_ms is None else wait_ms
    deadline = time.monotonic() + wait_ms / 1000.0
    while True:
        found = detect_security_challenge(page)
        if found or orders_listed(page) or time.monotonic() >= deadline:
            return found
        try:
            page.wait_for_timeout(500)
        except Exception:
            return found


@dataclass
class RawCard:
    text: str
    links: List[dict] = field(default_factory=list)   # {text, href, label, download}
    kind: str = ONLINE


# The most rows _COLLECT_ROWS_JS hands back. A list that reaches it may draw
# rows that were not read, so its oldest row is not known from what was read
# and it is never taken as seen whole (review).
ROWS_CAP = 400

# Every row inside the frame that holds a money amount, with its links.
# GUESS at what a row is, so anything list-like is tried, smallest first,
# and a row that contains another matching row is dropped.
_COLLECT_ROWS_JS = r"""
(rowSel) => {
  const cands = Array.from(document.querySelectorAll(rowSel));
  const money = /\$\s*-?[\d,]+\.\d{2}/;
  const dated = /\d{1,2}\/\d{1,2}\/\d{2,4}|\d{4}-\d{2}-\d{2}|(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}/i;
  const withMoney = cands.filter(e => money.test(e.innerText || ''));
  // Whether the page draws an element. A row on a tab that is hidden
  // rather than removed draws nothing, and its innerText runs its lines
  // together, "In-Store: 06/11/202618 Example Road", where no date can be
  // read. Having a box is also what row_controls asks of a row it presses,
  // so a row read here is one that can be pressed.
  const drawn = (e) => e.getClientRects().length > 0;
  // The innermost element holding an amount, and then up from there
  // until the text also carries a date.
  //
  // His receipts read "In-Store: 09/19/2026" on one line and "$31.23 6
  // items" on the next, as separate elements. Keeping the innermost
  // element with an amount took the second of those, so ninety-six rows
  // were found and every one of them parsed with no date at all, which
  // put every one outside the scope he had set (#42).
  //
  // It stops climbing at an element holding more than one amount, since
  // that is no longer one receipt.
  const rowsAmong = (found) => {
    const rows = [];
    for (const r of found) {
      if (found.some(o => o !== r && r.contains(o))) continue;
      let best = r, el = r;
      for (let up = 0; up < 5 && el && el.parentElement; up += 1) {
        if (dated.test(best.innerText || '')) break;
        el = el.parentElement;
        const t = el.innerText || '';
        if ((t.match(new RegExp(money.source, 'g')) || []).length > 1) break;
        best = el;
      }
      if (!rows.some(o => o === best)) rows.push(best);
    }
    return rows.filter(r => !rows.some(o => o !== r && r.contains(o)));
  };
  // What the page draws and what it does not are looked through apart. A
  // row can carry a copy of itself for a narrower screen, kept out of
  // sight, and taken together that copy was the innermost element with an
  // amount, so the row came back as the copy, undrawn and with no date.
  // The rows it does not draw come back as well, marked, so a caller can
  // say how many it left out.
  const out = [];
  for (const [rows, shown] of [[rowsAmong(withMoney.filter(drawn)), true],
                               [rowsAmong(withMoney.filter(e => !drawn(e))), false]]) {
    for (const r of rows) {
      if (out.length >= ROWS_CAP) break;
      const links = Array.from(r.querySelectorAll('a')).map(a => ({
        text: (a.innerText || '').trim().replace(/\s+/g, ' ').slice(0, 80),
        href: a.getAttribute('href') || '',
        label: a.getAttribute('aria-label') || a.getAttribute('title') || '',
        download: a.hasAttribute('download'),
      }));
      // Whether the row is drawn at all. A row on a hidden tab still hands
      // back its text, and it cannot be pressed.
      out.push({text: (r.innerText || '').trim().slice(0, 600), links,
                shown: shown && drawn(r)});
    }
  }
  return out;
}
""".replace("ROWS_CAP", str(ROWS_CAP))


def collect_both_tabs(page, facts: Optional[dict] = None) -> List[RawCard]:
    """Every row on both tabs. The page opens on Online Orders, and a
    person who only shops in the store has everything on the other one
    (#42).

    Each tab is read once rows of its own kind show on it, and is given
    LIST_WAIT_MS for that, as a purchase's tab is (show_list_for). The
    In-Store rows come only after that tab is pressed, and they used to be
    read at the press's own pause of two and a half seconds, so rows that
    came later were read as none. The Online tab is read as soon as it says
    it has no orders. A page without the tabs is read as it stands, once
    rows show on it.

    A tab whose rows never came is not a tab with nothing on it, and
    `facts`, when given, names each one as "unread". Only rows the page
    draws are read, see collect_cards.

    Rows that have begun to show are read once their count has stopped
    changing (settle_rows). A tab can draw its rows a few at a time, and
    read at its first rows, the ones it had not drawn yet were left for a
    later run to find. `facts` names each kind whose rows were there to
    read as "read"."""
    cards: List[RawCard] = []
    seen = set()
    unread = []
    drew = []
    for kind, label in ((IN_STORE, "In-Store Receipts"), (ONLINE, "Online Orders")):
        shown = show_list_for(page, kind, or_none=True)
        if shown.get("rows") and settle_rows(page, kind)["rows"]:
            drew.append(kind)
        if not (shown.get("rows") or shown.get("none")):
            unread.append(label)
        if not (shown.get("opened") or shown.get("rows")):
            log.info("no %s tab on this page", label)
            continue
        read: dict = {}
        found = collect_cards(page, facts=read)
        log.info("%s: %d row(s)%s", label, len(found),
                 ", %d more not showing, left out" % read["not_showing"] if read.get("not_showing") else "")
        for c in found:
            if c.text in seen:
                continue
            seen.add(c.text)
            cards.append(c)
    if facts is not None:
        facts["unread"] = unread
        facts["read"] = drew
    return cards


def collect_cards(page, purchase_type: str = "", facts: Optional[dict] = None) -> List[RawCard]:
    """Every row the page draws, with its links.

    A row the page does not draw is left out, and `facts`, when given, says
    how many as "not_showing". A tab hidden rather than removed hands back
    its rows with their lines run together and no date to read, and every
    store receipt was read once more that way from behind the Online tab
    and recorded a second time, undated. Such a row cannot be pressed
    either, since row_controls takes only a row that shows."""
    try:
        raw = page.evaluate(_COLLECT_ROWS_JS, FALLBACK["row"]) or []
    except Exception as e:
        log.warning("Row collection failed: %s", e)
        raw = []
    shown = [r for r in raw if r.get("shown")]
    if facts is not None:
        facts["not_showing"] = len(raw) - len(shown)
    return [RawCard(text=r.get("text") or "", links=r.get("links") or []) for r in shown]


# A row's own controls, including an icon with no text, so the PDF icon
# at the end of an in-store row can be pressed (#42).
_ROW_CONTROLS_JS = r"""([text, money, dates]) => {
  const rows = [];
  // A row is also held to its own date when the purchase has one, so two
  // receipts from the same store for the same amount are never mistaken
  // for each other.
  // A date only counts with no digit on either side, since "1/19/2026"
  // is inside "11/19/2026", and a November receipt was pressed for a
  // January purchase of the same store and amount (review).
  const esc = (s) => s.replace(/[.*+?^${}()|[\]\\\/]/g, '\\$&');
  const dateRes = (dates || []).map(d => new RegExp('(^|[^0-9])' + esc(d) + '(?![0-9])'));
  const dated = (t) => !dateRes.length || dateRes.some(r => r.test(t));
  const walk = (el) => {
    for (const c of el.children) {
      const t = (c.innerText || '').trim();
      // Only a row that is showing. A tab that is hidden rather than
      // removed still hands back its text, and a row on it cannot be
      // pressed.
      if (t.includes(money) && t.includes(text.slice(0, 12)) && dated(t) &&
          c.getClientRects().length) rows.push(c);
      walk(c);
    }
  };
  walk(document.body);
  if (!rows.length) return {found: false};
  // Two rows that each hold the words are two receipts, and neither is
  // guessed at.
  const inner = rows.filter(r => !rows.some(o => o !== r && r.contains(o)));
  if (inner.length > 1) return {found: false, ambiguous: inner.length};
  // The words can sit in a block beside the control, so the row is the
  // element above them that holds a control too, never one that holds a
  // second amount, which is another row's (review).
  const CTL = 'a, button, [role=button], [role=link]';
  const amounts = /\$\s*-?[\d,]+\.\d{2}/g;
  let row = inner[0];
  for (let up = 0; up < 4 && !row.querySelector(CTL) && row.parentElement &&
       row.parentElement !== document.body; up += 1) {
    const p = row.parentElement;
    if (((p.innerText || '').match(amounts) || []).length > 1) break;
    row = p;
  }
  const out = [];
  const collect = (el) => {
    for (const c of el.children) {
      const tag = c.tagName.toLowerCase();
      const role = c.getAttribute('role') || '';
      const label = c.getAttribute('aria-label') || c.getAttribute('title') || '';
      const cls = (c.className || '').toString();
      const cs = getComputedStyle(c);
      const interactive = tag === 'a' || tag === 'button' || role === 'button' || role === 'link';
      const clickable = interactive || cs.cursor === 'pointer';
      // Its own words count too. A recording showed the control is a link
      // that reads "view receipt pdf", and round two looked only at the
      // label, the class and the address, so the one control on the row
      // that says what it is did not rank as the one to press (#42).
      const looksPdf = /pdf|receipt|download/i.test(
        label + ' ' + cls + ' ' + (c.getAttribute('href') || '') + ' ' + (c.innerText || '').slice(0, 40));
      if (clickable || looksPdf) {
        out.push({el: c, text: (c.innerText || '').trim().slice(0, 40), label: label.slice(0, 40),
                  href: c.getAttribute('href') || '', pdf: looksPdf, interactive,
                  shown: !!c.getClientRects().length && cs.visibility !== 'hidden',
                  holdsControl: !!c.querySelector(CTL)});
      }
      collect(c);
    }
  };
  collect(row);
  out.sort((a, b) => (b.pdf ? 1 : 0) - (a.pdf ? 1 : 0));
  return {found: true, cands: out.map(c => ({text: c.text, label: c.label, href: c.href, pdf: c.pdf,
                                             interactive: c.interactive, shown: c.shown,
                                             holdsControl: c.holdsControl})),
          els: out.map(c => c.el), outline: (row.innerText || '').slice(0, 200)};
}"""


def row_dates(iso: str) -> List[str]:
    """The ways a row can print this date. His rows read "In-Store:
    09/19/2026", and a date written without leading zeros is allowed for."""
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", iso or "")
    if not m:
        return []
    y, mo, d = m.groups()
    return sorted({f"{mo}/{d}/{y}", f"{int(mo)}/{int(d)}/{y}", iso})


def show_tab_for(page, purchase_type: str) -> bool:
    """The tab a purchase's row lives on. The page opens on Online Orders,
    so an in-store receipt was looked for on a tab that only ever said
    there were no orders, and Pilot pressed nothing ten times (#42)."""
    return open_tab(page, TAB_IN_STORE_RE if purchase_type == IN_STORE else TAB_ONLINE_RE)


def _collected(page) -> list:
    """Every row _COLLECT_ROWS_JS hands back, none when the page could not
    be read."""
    try:
        return page.evaluate(_COLLECT_ROWS_JS, FALLBACK["row"]) or []
    except Exception:
        return []


def _of_kind(raw, purchase_type: str) -> List[str]:
    """The words of each drawn row of a purchase's kind among those the
    collector handed back, In-Store rows for a store receipt and the others
    for an online order."""
    in_store = purchase_type == IN_STORE
    return [r.get("text") or "" for r in raw if r.get("shown")
            and bool(IN_STORE_ROW_RE.search(r.get("text") or "")) == in_store]


def _rows_of_kind(page, purchase_type: str) -> List[str]:
    """The words of each row of a purchase's kind the page is drawing now.
    None drawn, or a page that could not be read, is no rows."""
    return _of_kind(_collected(page), purchase_type)


def rows_showing(page, purchase_type: str) -> int:
    """How many rows of a purchase's kind the page is drawing now, In-Store
    rows for a store receipt and the others for an online order. Nothing is
    waited for."""
    return len(_rows_of_kind(page, purchase_type))


def rows_capped(page) -> bool:
    """Whether the collector stopped at ROWS_CAP, so the page may draw rows
    it did not read. A page that could not be read counts as one that may."""
    try:
        raw = page.evaluate(_COLLECT_ROWS_JS, FALLBACK["row"]) or []
    except Exception:
        return True
    return len(raw) >= ROWS_CAP


def listed_rows(page, purchase_type: str) -> dict:
    """The rows of a purchase's kind the page is drawing now, how many
    ("rows") and the date of the oldest of them ("oldest", as YYYY-MM-DD).
    The oldest is "" unless every one of them shows a date, since a row
    whose date could not be read could be the oldest, and "" when the
    collector stopped at ROWS_CAP, since then the last row read is not the
    list's last. Nothing is waited for."""
    raw = _collected(page)
    texts = _of_kind(raw, purchase_type)
    dates = [parse_date(t) for t in texts]
    whole = len(raw) < ROWS_CAP
    oldest = min(dates) if whole and dates and all(dates) else ""
    return {"rows": len(texts), "oldest": oldest}


def page_visible(page) -> bool:
    """Whether the browser is showing the page, as the page itself says.
    A page it is not showing may not draw what scrolling asks of it, and one
    that could not be asked counts as not showing (review)."""
    try:
        return page.evaluate("() => document.visibilityState") == "visible"
    except Exception:
        return False


# The tab each kind of purchase is listed on, named as the page names it.
TAB_LABELS = {IN_STORE: "In-Store Receipts", ONLINE: "Online Orders"}

# How long the orders page is given to show a purchase's tab and its rows.
LIST_WAIT_MS = 30000

# How long the count of a tab's rows has to stay the same before the list
# is taken as drawn. A list can draw its rows a few at a time, and read
# while it is still filling, a row it has not drawn yet looks like a row it
# does not have.
ROWS_STEADY_MS = 3000


def settle_rows(page, purchase_type: str, wait_ms: Optional[int] = None,
                seen: Optional[tuple] = None, steady_ms: Optional[int] = None) -> dict:
    """Wait until the count of a purchase's rows has stayed the same for
    `steady_ms`, ROWS_STEADY_MS when not given, for up to `wait_ms` in all,
    LIST_WAIT_MS when not given. `seen`, when given, is what reads made
    already found, the count and the time it was first read, and the wait
    goes on from there rather than starting over.

    Returns the count ("rows"), whether it changed from the first count
    ("changed"), and whether it stayed the same long enough before the time
    was up ("settled"). A list still changing when the time is up was not
    seen whole, and is never read as if it had been, and neither is one
    the collector stopped reading at ROWS_CAP (review).

    The count has stayed the same only as long as reads that agree span.
    Time after the last read is never counted, since the page can change in
    it, and a pause in this program right after a read used to end the wait
    on a count nothing had read again (review)."""
    wait_ms = LIST_WAIT_MS if wait_ms is None else wait_ms
    steady_ms = ROWS_STEADY_MS if steady_ms is None else steady_ms
    deadline = time.monotonic() + wait_ms / 1000.0
    if seen is None or seen[0] is None or seen[1] is None:
        rows = rows_showing(page, purchase_type)
        since = time.monotonic()
    else:
        rows, since = seen
    changed = False
    while time.monotonic() < deadline:
        try:
            page.wait_for_timeout(500)
        except Exception:
            break
        began = time.monotonic()
        now = rows_showing(page, purchase_type)
        if now != rows:
            rows, changed, since = now, True, time.monotonic()
        elif began - since >= steady_ms / 1000.0:
            return {"rows": rows, "changed": changed, "settled": not rows_capped(page)}
    return {"rows": rows, "changed": changed, "settled": False}


# A list whose oldest row is younger than this many months is never taken for
# all Meijer holds. It appears to list about two years of store receipts,
# inferred from one account, and a list that goes back less far than that may
# be filtered, paged, or cut short while Meijer slows requests (review).
WHOLE_LIST_MONTHS = 20

# The words of a row's own details link, which with its receipt link is the
# one control a row may show (see allowed_on_the_list).
ROW_DETAILS_RE = re.compile(r"^\s*(view\s+)?(order\s+)?details\s*$", re.I)

# Every control the list's main content shows, its words, the name a screen
# reader hears, and whether it sits in one of the list's rows. A control is
# anything a person can press or choose, a link, a button, a field or a
# dropdown, a summary that opens, an element with a control's role, one a
# keyboard can reach or one that answers a click, and the outermost element
# the pointer shows as clickable. One inside another is part of it.
_MORE_CONTROLS_JS = r"""(rowSel) => {
  const root = document.querySelector('main, [role=main], #main') || document.body;
  const money = /\$\s*-?[\d,]+\.\d{2}/;
  const dated = /\d{1,2}\/\d{1,2}\/\d{2,4}|\d{4}-\d{2}-\d{2}|(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}/i;
  const shows = (el) => el.getClientRects().length > 0 && getComputedStyle(el).visibility !== 'hidden';
  const found = new Set();
  for (const el of root.querySelectorAll(
      'a, button, input:not([type=hidden]), select, textarea, summary, [contenteditable=true], ' +
      '[role=button], [role=link], [role=tab], [role=radio], [role=option], [role=menuitem], ' +
      '[role=menuitemradio], [role=menuitemcheckbox], [role=checkbox], [role=switch], ' +
      '[role=combobox], [role=listbox], [role=slider], [role=spinbutton], [role=treeitem], ' +
      '[onclick], [tabindex]:not([tabindex="-1"])')) {
    if (shows(el)) found.add(el);
  }
  for (const el of root.querySelectorAll('*')) {
    if (found.has(el) || !shows(el) || getComputedStyle(el).cursor !== 'pointer') continue;
    const up = el.parentElement;
    if (up && root.contains(up) && getComputedStyle(up).cursor === 'pointer') continue;
    found.add(el);
  }
  const all = Array.from(found);
  return all.filter(el => !all.some(o => o !== el && o.contains(el))).map(el => {
    const row = el.closest(rowSel);
    const words = row && row !== el ? (row.innerText || '') : '';
    return {text: ((el.tagName === 'INPUT' ? el.value : el.innerText) || '').replace(/\s+/g, ' ').trim().slice(0, 80),
            label: (el.getAttribute('aria-label') || el.getAttribute('title') || '').replace(/\s+/g, ' ').trim().slice(0, 80),
            inRow: money.test(words) && dated.test(words)};
  });
}"""


def allowed_on_the_list(control: dict) -> bool:
    """Whether a control the list's main content shows is one a list that
    Meijer shows whole may show. Only the two tabs, by the words each shows,
    and a row's own receipt or details link are. Every other control may
    show more of the list or a narrower part of it, a Load more button or a
    pager, an arrow, a year or a month, All receipts, a filter or a menu,
    and a list showing one is never taken for all Meijer holds. A list of
    the words such a control says missed every one that says it another way
    (review)."""
    text = " ".join((control.get("text") or "").split())
    label = " ".join((control.get("label") or "").split())
    if any(w and (TAB_ONLINE_RE.match(w) or TAB_IN_STORE_RE.match(w)) for w in (text, label)):
        return True
    if not control.get("inRow"):
        return False
    return is_receipt_control({"text": text, "label": label}) or bool(ROW_DETAILS_RE.match(text or label))


def more_controls(page) -> Optional[int]:
    """How many controls the list's main content shows besides the ones a
    list Meijer shows whole may show (allowed_on_the_list). None when the
    page could not be read, which is never taken for none. Nothing is
    pressed.

    A list behind a Load more button, a pager or a remembered filter draws
    only part of what Meijer holds, and the rest used to be read as
    purchases Meijer no longer lists (review)."""
    try:
        controls = page.evaluate(_MORE_CONTROLS_JS, FALLBACK["row"])
    except Exception as e:
        log.info("could not read the list's controls: %s", e)
        return None
    if not isinstance(controls, list):
        return None
    return sum(1 for c in controls if not (isinstance(c, dict) and allowed_on_the_list(c)))


# The page, and every part of its main content that scrolls, taken to its
# end, the way a person scrolls to the bottom of a list.
_SCROLL_TO_END_JS = r"""() => {
  const root = document.querySelector('main, [role=main], #main') || document.body;
  const page = document.scrollingElement || document.documentElement;
  page.scrollTop = page.scrollHeight;
  for (const el of root.querySelectorAll('*')) {
    if (el.scrollHeight > el.clientHeight + 1 && /(auto|scroll)/.test(getComputedStyle(el).overflowY)) {
      el.scrollTop = el.scrollHeight;
    }
  }
  return true;
}"""


# How long the rows have to hold still once the list is scrolled to its end.
# A list that fetches its older receipts as it is scrolled can take longer
# than ROWS_STEADY_MS to draw them. The list is scrolled only for a purchase
# about to be said to have dropped off it, so the wait is seldom paid
# (review).
SCROLL_STEADY_MS = 10000


def scroll_to_end(page, purchase_type: str) -> dict:
    """Scroll the list to its end and let its rows settle for at least
    SCROLL_STEADY_MS, as settle_rows answers, "changed" meaning they changed
    from the count before the scroll. A list that draws more of itself as it
    is scrolled shows only its first part until then, and the rows it adds
    can come before the first read after the scroll, so the count is read
    before it. A page that could not be scrolled is said to have changed,
    so nothing on it is read as the whole list."""
    before = rows_showing(page, purchase_type)
    since = time.monotonic()
    try:
        page.evaluate(_SCROLL_TO_END_JS)
    except Exception as e:
        log.info("could not scroll the list: %s", e)
        return {"rows": before, "changed": True, "settled": False}
    steady = max(ROWS_STEADY_MS, SCROLL_STEADY_MS)
    return settle_rows(page, purchase_type, seen=(before, since), steady_ms=steady,
                       wait_ms=max(LIST_WAIT_MS, 2 * steady))


def says_it_has_none(page, purchase_type: str) -> bool:
    """Whether the tab a kind of purchase lives on says, in its own words
    and where they show, that it has nothing.

    Only the Online tab has been seen saying so, as NO_ORDERS_YET_RE
    (#42). What the In-Store tab says when there are no receipts has not
    been seen, so it is never taken to say it, and an In-Store tab without
    rows is a list that did not come."""
    if purchase_type == IN_STORE:
        return False
    try:
        return bool(NO_ORDERS_YET_RE.search(page.evaluate(_LIST_WORDS_JS) or ""))
    except Exception:
        return False


def show_list_for(page, purchase_type: str, wait_ms: Optional[int] = None,
                  or_none: bool = False) -> dict:
    """Show the tab a purchase's row lives on, and wait until its rows show.

    The tab is looked for until it is there, and pressed once. Its rows are
    then waited for, up to `wait_ms` in all. His Run All, after most of
    the list had been saved from the same page, met one drawing only the
    list's heading and a line under it, with no tabs and no rows. It looked
    for the tab once, and for the row for ten seconds, and wrote the
    purchase down as a row with no receipt (#42).

    Returns what it found, whether the tab was pressed ("opened") and how
    many rows of the purchase's kind are showing ("rows"). No rows is a list
    that did not come. With `or_none` the wait also ends when the tab says
    it has nothing (says_it_has_none), which is then "none". Discovery asks
    for that. A purchase's own row is looked for without it, as it always
    was, since the purchase was on the list when it was found."""
    wait_ms = LIST_WAIT_MS if wait_ms is None else wait_ms
    deadline = time.monotonic() + wait_ms / 1000.0
    opened, rows, none = False, 0, False
    while True:
        if not opened:
            opened = show_tab_for(page, purchase_type)
        rows = rows_showing(page, purchase_type)
        none = bool(or_none and not rows and says_it_has_none(page, purchase_type))
        if rows or none or time.monotonic() >= deadline:
            return {"opened": opened, "rows": rows, "none": none}
        try:
            page.wait_for_timeout(1000)
        except Exception:
            return {"opened": opened, "rows": rows, "none": none}


def row_controls(page, purchase, facts: Optional[dict] = None):
    """(candidates, handles) for the row this purchase came from, the PDF
    icon first. None when the row is not on the page, or when more than one
    row fits it, which `facts` then says as "ambiguous"."""
    money = purchase.total or ""
    text = (purchase.items[0].name if purchase.items else "") or purchase.purchase_date or ""
    try:
        h = page.evaluate_handle(_ROW_CONTROLS_JS, [text, money, row_dates(purchase.purchase_date)])
        props = h.get_properties()
        if "els" not in props:
            if facts is not None and "ambiguous" in props:
                facts["ambiguous"] = int(h.get_property("ambiguous").json_value() or 0)
            return None
        cands = h.get_property("cands").json_value()
        els = [v.as_element() for v in props["els"].get_properties().values()]
        return cands, els
    except Exception as e:
        log.info("row controls: %s", e)
        return None


def receipt_links(card: RawCard) -> List[dict]:
    """The row's links that say receipt, order details, view or download,
    host checked and guard checked, download links first."""
    out = []
    for ln in card.links:
        words = f"{ln.get('text', '')} {ln.get('label', '')} {ln.get('href', '')}"
        if not re.search(r"receipt|invoice|download|view|details|order", words, re.I):
            continue
        href = urljoin(BASE, ln.get("href") or "")
        if not is_receipt_address(href):
            continue
        name = ln.get("text") or ln.get("label") or "Receipt"
        if FORBIDDEN_CONTROL_RE.search(name):
            continue
        out.append({**ln, "href": href, "name": name})
    out.sort(key=lambda ln: (0 if (ln.get("download") or re.search(r"\.pdf(\?|$)|download", ln["href"], re.I)) else 1))
    return out


def is_receipt_address(url: str) -> bool:
    """A Meijer address that can be a receipt's. An empty link, a "#" or a
    "/" resolves to Meijer's front page, and that page would have been
    printed and filed as the receipt, since a Meijer page passes the check
    on the word Meijer (review)."""
    return is_safe_url(url) and urlsplit(url).path not in ("", "/")


def _stable_key(card: RawCard, date: str, total: str) -> str:
    """A payment id from a receipt link's path when there is one, else a
    short hash of the row's date, amount and words, so a payment keeps
    its identity across runs without an id Meijer would have to show."""
    for ln in receipt_links(card):
        for seg in reversed(urlsplit(ln["href"]).path.split("/")):
            if len(seg) >= 4 and re.search(r"\d", seg) and re.fullmatch(r"[A-Za-z0-9_-]+", seg):
                return seg[:60]
    words = re.sub(r"\s+", " ", card.text)[:200]
    return "p" + hashlib.sha1(f"{date}|{total}|{words}".encode("utf-8")).hexdigest()[:12]


_DESCRIPTION_SKIP_RE = re.compile(
    r"^(receipt|invoice|view|download|paid|payment|date|amount|description|method|"
    r"\$\s*[\d,]+\.\d{2}|visa|mastercard|american\s+express|amex|discover|paypal|"
    r"[•*x]{2,}\s*\d{4}|ending\s+in\s+\d{4}|\d{1,2}/\d{2,4})\b", re.I)


def card_to_purchase(card: RawCard, purchase_type: str = "", base_url: str = BASE) -> Optional[Purchase]:
    """A Purchase from one payment row. The description is the first
    line that is not the date, the amount, the card or a link's text."""
    text = card.text or ""
    date = parse_date(text) or ""
    total = parse_money(text)
    if not total:
        return None
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    description = ""
    for ln in lines:
        if parse_date(ln) and len(ln) < 24:
            continue
        if _DESCRIPTION_SKIP_RE.match(ln) or MONEY_RE.fullmatch(ln.replace(" ", "")):
            continue
        if any(ln == (lk.get("text") or "") for lk in card.links):
            continue
        description = _html.unescape(ln)[:300]
        break
    links = receipt_links(card)
    key = _stable_key(card, date, total)
    in_store = bool(IN_STORE_ROW_RE.search(text))
    return Purchase(
        purchase_type=IN_STORE if in_store else ONLINE,
        purchase_date=date,
        order_number=key,
        total=total,
        status="Paid",
        store_info="Meijer",
        details_url=links[0]["href"] if links else ORDERS_URL,
        receipt_url=links[0]["href"] if links else "",
        items=[Item(name=description or "Meijer order", quantity="1", line_total=total)],
        discovered_at=now_iso(),
    )


# ---------------------------------------------------------------------------
# Capture
# ---------------------------------------------------------------------------


def fetch_receipt_bytes(page, url: str) -> Optional[bytes]:
    """The receipt link fetched from inside the signed-in page. Bytes when
    the answer is a PDF, None when it is a page (to be printed) or an
    error."""
    if not is_safe_url(url):
        return None
    try:
        out = _fetch_with_status(page, url)
    except Exception as e:
        log.info("fetch of %s failed: %s", url[:80], e)
        return None
    if not out.get("b64"):
        return None
    data = base64.b64decode(out["b64"])
    if data[:5] == b"%PDF-":
        return data
    return None


# Why pressing a row's receipt control took nothing, in words of this app's
# own. Each is also the reason a failure file gives and what the file a
# tester attaches says of the attempt, so every word of them is on the
# fixed list in paperpull_core.words.
NOT_ON_THE_PAGE = "its row is not on the page"
MORE_THAN_ONE_ROW = "more than one row fits it"
NO_RECEIPT_CONTROL = "no receipt control on its row"
NO_PDF = "the press gave no pdf"

# How many times, a second apart, a purchase's row is looked for before it
# is called missing.
ROW_LOOKS = 10


def press_row_receipt(page, purchase, trace=None, facts=None):
    """Press the row's own receipt control, the PDF icon at its end, and
    take whatever the page produces: a download, a PDF answer, or the
    window it opens (the page warns a pop-up blocker will stop it, so it
    opens one). Bytes, or None.

    When it is None, `facts`, when given, says why as "outcome", one of
    NOT_ON_THE_PAGE, MORE_THAN_ONE_ROW, NO_RECEIPT_CONTROL and NO_PDF. A run
    used to say of all four that the row carried no receipt link (#42).
    For a row not on the page it also gives how many rows of the purchase's
    kind its last look counted ("rows") and when that count was first read
    ("since"), so a wait for the list to settle goes on from these looks
    (settle_rows) rather than starting over."""
    said = facts if facts is not None else {}
    # The tab's rows arrive after the tab is shown, so the row is given a
    # few seconds to appear before it is called missing. The rows are
    # counted before each look for the row, so every row counted was
    # looked through.
    found = None
    fit: dict = {}
    rows, since = None, None
    for _ in range(ROW_LOOKS):
        count = rows_showing(page, getattr(purchase, "purchase_type", ""))
        if count != rows:
            rows, since = count, time.monotonic()
        found = row_controls(page, purchase, fit)
        if found or fit.get("ambiguous"):
            break
        page.wait_for_timeout(1000)
    if not found:
        said["outcome"] = MORE_THAN_ONE_ROW if fit.get("ambiguous") else NOT_ON_THE_PAGE
        said["rows"], said["since"] = rows, since
        if trace is not None:
            if fit.get("ambiguous"):
                trace.append({"note": "more than one row fits this purchase, so none was pressed",
                              "rows": fit["ambiguous"]})
            else:
                trace.append({"note": "the row for this purchase is not on the page"})
        return None
    cands, els = found
    if trace is not None:
        # What may leave is listed, and the row's own words never do. A
        # store's street reached this file through a control's words
        # (review).
        trace.append({"note": "the row's controls",
                      "candidates": [{"says": control_says(c), "href": _href_kind(c.get("href") or ""),
                                      "pdf": bool(c.get("pdf")), "shown": bool(c.get("shown", True)),
                                      "interactive": bool(c.get("interactive"))}
                                     for c in cands[:12]]})
    # Only the row's own receipt control is pressed, and only its address is
    # fetched. Until 0.39.2 this function raised before its first press, so
    # the loop that pressed up to six of the row's controls in turn had never
    # run on a real account, and it would have pressed an Email Receipt, or
    # a control with no words at all, before the receipt (#42, review).
    # And only a link or a button that is showing and holds no other
    # control, so a wrapper is never pressed at its middle, where another
    # control can sit, and a copy hidden at this width is never the one
    # tried (review).
    picked = next(((c, el) for c, el in zip(cands, els)
                   if el is not None and c.get("interactive") and c.get("shown", True)
                   and not c.get("holdsControl") and is_receipt_control(c)), None)
    if picked is None:
        said["outcome"] = NO_RECEIPT_CONTROL
        if trace is not None:
            trace.append({"note": "no control on the row reads as its receipt", "controls": len(cands)})
        return None
    c, el = picked
    label = c["text"] or c["label"]
    href = urljoin(BASE, c["href"] or "")
    if c["href"] and is_safe_url(href):
        body = fetch_receipt_bytes(page, href)
        if body:
            if trace is not None:
                trace.append({"note": "the receipt came from the row's control",
                              "control": mask_text(label)[:40],
                              "how": "its own address, fetched from the page"})
            return body
    ctx = page.context
    got: dict = {}
    downloads: list = []
    popups: list = []
    finished: dict = {}

    def on_response(res):
        # An answer from this page or a window this press opened. Another
        # tab of the same browser can be on meijer.com as well (review).
        try:
            if got or "pdf" not in (res.headers.get("content-type") or "").lower():
                return
            if not is_safe_url(res.url or "") or res.frame.page not in [page] + popups:
                return
            body = res.body()
            if body[:5] == b"%PDF-":
                got["body"] = body
                got["how"] = ("an answer to the page" if res.frame.page is page
                              else "an answer to the window it opened")
        except Exception:
            pass

    # A function of its own and not downloads.append. Playwright marks the
    # handler it is given, a built-in method cannot be marked, and every
    # receipt on 0.39.1 raised AttributeError right here (#42). It is also
    # the one object the listener is taken off with below, where a second
    # downloads.append would be a different one.
    def on_download(dl):
        # Only a download from a Meijer address, and it is waited for here,
        # in the listener's own fiber, so the press can give up on one that
        # never finishes (review).
        u = dl.url or ""
        if not is_safe_url(u[5:] if u.startswith("blob:") else u):
            return
        downloads.append(dl)
        try:
            finished[id(dl)] = dl.path()
        except Exception:
            finished[id(dl)] = None

    def on_popup(p):
        popups.append(p)
        for event, handler in (("download", on_download), ("popup", on_popup)):
            try:
                p.on(event, handler)
            except Exception:
                pass

    looked: list = []
    try:
        ctx.on("response", on_response)
        page.on("download", on_download)
        page.on("popup", on_popup)
        try:
            el.click(timeout=5000)
        except Exception as e:
            if trace is not None:
                trace.append({"note": "click failed", "control": mask_text(label)[:40],
                              "error": type(e).__name__})
        for _ in range(20):
            page.wait_for_timeout(500)
            if got or downloads:
                break
            for extra in [p for p in popups if p not in looked]:
                u = extra.url or ""
                # A window the page opens blank, to be filled once its own
                # fetch answers, is looked at again on the next tick and never
                # closed while it is still being filled (review).
                if not u or u == "about:blank":
                    continue
                looked.append(extra)
                try:
                    extra.wait_for_load_state("domcontentloaded", timeout=5000)
                except Exception:
                    pass
                if u.startswith("blob:") or is_safe_url(u):
                    # The window's address is fetched once.
                    if u.startswith("blob:"):
                        try:
                            fetched = _fetch_with_status(extra, u)
                            body = base64.b64decode(fetched["b64"]) if fetched.get("b64") else None
                        except Exception:
                            body = None
                    else:
                        body = fetch_receipt_bytes(extra, u)
                    if body and body[:5] == b"%PDF-":
                        got["body"] = body
                        got["how"] = ("the window it opened, a blob" if u.startswith("blob:")
                                      else "the window it opened")
                if not got and trace is not None:
                    trace.append({"note": "the control opened a window", "url": mask_href(u)})
            if got:
                break
        # A download is given twenty seconds to finish, then cancelled, so
        # Download.path() cannot hold the run forever.
        if downloads and not got:
            for _ in range(40):
                if id(downloads[0]) in finished:
                    break
                page.wait_for_timeout(500)
            if id(downloads[0]) not in finished:
                try:
                    downloads[0].cancel()
                except Exception:
                    pass
                if trace is not None:
                    trace.append({"note": "the download did not finish in time"})
    finally:
        for target, event, handler in ((ctx, "response", on_response), (page, "download", on_download),
                                       (page, "popup", on_popup)):
            try:
                target.remove_listener(event, handler)
            except Exception:
                pass
        for extra in popups:
            for event, handler in (("download", on_download), ("popup", on_popup)):
                try:
                    extra.remove_listener(event, handler)
                except Exception:
                    pass
            try:
                extra.close()
            except Exception:
                pass
    if downloads and not got and finished.get(id(downloads[0])):
        # A download the browser saved for itself. Its own file is read
        # rather than moved, so nothing is left in the browser's folder
        # half-taken.
        try:
            import pathlib
            body = pathlib.Path(finished[id(downloads[0])]).read_bytes()
            if body[:5] == b"%PDF-":
                got["body"] = body
                got["how"] = "a download"
        except Exception as e:
            if trace is not None:
                trace.append({"note": "download save failed", "error": type(e).__name__})
    if got.get("body"):
        if trace is not None:
            trace.append({"note": "the receipt came from the row's control", "control": mask_text(label)[:40],
                          "how": got.get("how", "")})
        return got["body"]
    said["outcome"] = NO_PDF
    return None


# Words a receipt carries, from a fixed list. What pdf_facts says of a PDF is
# only which of these it holds, so the file it goes into never carries a
# purchase, a price, a card or a store of the member's own.
RECEIPT_WORDS = ("meijer", "receipt", "subtotal", "total", "tax", "change",
                 "balance", "visa", "mastercard", "debit", "credit", "cash",
                 "mperks", "store", "thank", "items")


def pdf_facts(path) -> dict:
    """What a receipt that failed its check holds, for the file a tester
    attaches: its size, its pages, how much text it has, whether a date or
    an amount is printed, and which RECEIPT_WORDS appear. Never its words."""
    facts: dict = {}
    try:
        p = Path(path)
        facts["bytes"] = p.stat().st_size
        from pypdf import PdfReader
        reader = PdfReader(str(p))
        facts["pages"] = len(reader.pages)
        text = "".join((pg.extract_text() or "") for pg in reader.pages[:5]).lower()
        facts["text_characters"] = len(text)
        facts["prints_a_date"] = bool(re.search(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b", text))
        facts["prints_an_amount"] = bool(re.search(r"\d+\.\d{2}\b", text))
        facts["words"] = [w for w in RECEIPT_WORDS if w in text]
    except Exception as e:
        facts["error"] = type(e).__name__
    return facts


# What the row's own receipt control says. The member's recording showed a
# link that reads "view receipt pdf" (#42). A control with no words of its
# own is taken only when its name for a screen reader says the same.
RECEIPT_PDF_LABEL_RE = re.compile(
    r"^\s*(view|download|open)\s+(the\s+|my\s+|your\s+)?(receipt\s+)?pdf\s*$", re.I)


# Words that send, share or print a receipt, refused in the visible words
# and in the name a screen reader hears alike. A link reading "view receipt
# pdf" whose name says Email receipt is not the one to press (review).
SENDS_CONTROL_RE = re.compile(
    r"\b(e-?mail(ed|s)?|mail|share|send|sms|text|print|message|forward|copy\s+link)\b", re.I)


def is_receipt_control(c: dict) -> bool:
    """Whether a row control is the one that fetches its receipt. Never one
    the guard refuses, and never one that only mentions a receipt, since
    Email Receipt and Share Receipt send it somewhere."""
    text = " ".join((c.get("text") or "").split())
    label = " ".join((c.get("label") or "").split())
    if FORBIDDEN_CONTROL_RE.search(text) or FORBIDDEN_CONTROL_RE.search(label):
        return False
    if SENDS_CONTROL_RE.search(text) or SENDS_CONTROL_RE.search(label):
        return False
    if text:
        return bool(RECEIPT_LINK_RE.match(text))
    return bool(RECEIPT_LINK_RE.match(label) or RECEIPT_PDF_LABEL_RE.match(label))


def control_says(c: dict) -> str:
    """A control's words as one of a few fixed answers, for the trace,
    never the words themselves."""
    words = " ".join(((c.get("text") or "") + " " + (c.get("label") or "")).split())
    if not words:
        return "nothing"
    if is_receipt_control(c):
        return "the receipt"
    if SENDS_CONTROL_RE.search(words):
        return "sends or prints"
    if FORBIDDEN_CONTROL_RE.search(words):
        return "refused by the guard"
    return "something else"


def _href_kind(h: str) -> str:
    if not h:
        return "none"
    if h.startswith("javascript:"):
        return "script"
    if h.startswith("#"):
        return "fragment"
    return "meijer" if is_safe_url(urljoin(BASE, h)) else "elsewhere"


def goto_receipt_page(page, url: str) -> bool:
    if not is_safe_url(url):
        return False
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(1500)
    return True


def receipt_is_present(page) -> bool:
    """A receipt page shows an amount and one of the words a receipt has."""
    try:
        text = page.locator("main").first.inner_text(timeout=5000) if page.locator("main").count() \
            else page.locator("body").inner_text(timeout=5000)
    except Exception:
        return False
    return bool(MONEY_RE.search(text) and re.search(r"receipt|order|total|subtotal|items?", text, re.I))


def on_receipt_page(page, url: str) -> bool:
    """Whether the browser is still at the receipt's own address, as
    Meijer might write it, see paperpull_core.page_check.same_address."""
    return _page_check.same_address(page.url or "", url)


def not_this_purchase(page, url: str) -> str:
    """"" when the page in front of the app is the receipt this order's row
    links to, else why it is not, in fixed words.

    The orders page shows each order's own date and total, which is what
    the check on the saved file looks for, so printed in an order's place
    it passed. Where the page is tells them apart. A receipt link that
    leads anywhere else, the orders page or a sign-in page among them, is
    not the receipt, and neither is a row's link that is one of the order
    lists itself. Nobody has seen an online order's receipt page, so an
    address that only shares a list's path is not taken for the list."""
    for listed in ORDER_CANDIDATES:
        if _page_check.same_address(url, listed) and _page_check.same_address(listed, url):
            return _page_check.IS_THE_LIST
    if not on_receipt_page(page, url):
        return _page_check.NOT_ITS_ADDRESS
    return ""


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


# The receipt block is the smallest element with an amount and a receipt
# word that is not the whole page. Everything on other branches is hidden,
# a live DOM display change only, discarded on the next navigation.
_ISOLATE_JS = r"""
() => {
  const money = /\$\s*-?[\d,]+\.\d{2}/;
  const words = /receipt|order|total|subtotal/i;
  let best = null, bestLen = Infinity;
  for (const el of document.querySelectorAll('main div, main section, main article, main table, turbo-frame div')) {
    const t = el.innerText || '';
    if (t.length < 40 || t.length >= bestLen) continue;
    if (money.test(t) && words.test(t) && el.querySelectorAll('nav, header').length === 0) { best = el; bestLen = t.length; }
  }
  let n = best;
  // climb until the block is at least a few hundred characters, a receipt
  // is more than its total line
  while (n && (n.innerText || '').length < 300 && n.parentElement && n.parentElement.tagName !== 'BODY') n = n.parentElement;
  if (!n) return false;
  let el = n;
  while (el && el.parentElement && el !== document.body) {
    for (const s of Array.from(el.parentElement.children)) if (s !== el) s.style.display = 'none';
    el = el.parentElement;
  }
  for (const x of n.querySelectorAll('button, nav')) x.style.display = 'none';
  const w = Math.max(n.scrollWidth, n.getBoundingClientRect().width);
  document.body.style.zoom = String(Math.min(1, Math.max(0.5, 736 / (w + 16))));
  window.scrollTo(0, 0);
  return true;
}
"""


def isolate_receipt(page) -> bool:
    try:
        ok = bool(page.evaluate(_ISOLATE_JS))
    except Exception as e:
        log.warning("Receipt isolation failed: %s", e)
        return False
    if ok:
        page.wait_for_timeout(300)
    return ok


def extract_items(page) -> List[Item]:
    """Lines of a receipt page that end in an amount, minus the totals."""
    try:
        text = page.locator("main").first.inner_text(timeout=5000) if page.locator("main").count() \
            else page.locator("body").inner_text(timeout=5000)
    except Exception:
        return []
    items: List[Item] = []
    for ln in (x.strip() for x in text.splitlines()):
        m = re.match(r"^(?P<name>.+?)\s+\$\s*(?P<amt>-?[\d,]+\.\d{2})$", ln)
        if not m:
            continue
        name = m.group("name").strip(" :-")
        if len(name) < 3 or re.match(r"^(sub\s*total|total|tax|amount\s+(paid|due)|balance|paid|payment|discount|credit)\b", name, re.I):
            continue
        items.append(Item(name=name[:300], quantity="1", line_total=f"${m.group('amt')}"))
    return items


def extract_details(page, purchase: Purchase) -> Purchase:
    items = extract_items(page)
    if items:
        purchase.items = items
    return purchase


# ---------------------------------------------------------------------------
# Diagnostics, what a tester sends back, with nothing personal in it
# ---------------------------------------------------------------------------

_DIGITS_RE = re.compile(r"\d{2,}")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_HANDLE_RE = re.compile(r"@[A-Za-z0-9-]{2,39}")


# The owner's name and the rest of the redaction live in core. These apps
# had a fourth version of it, without the title and suffix exclusion, so
# every "Jr" and "II" on a page became [name].


def mask_text(s: str) -> str:
    for word in private_words():
        s = re.sub(re.escape(word), "[name]", s or "", flags=re.I)
    s = _EMAIL_RE.sub("<email>", s or "")
    s = _HANDLE_RE.sub("@<user>", s)
    return _DIGITS_RE.sub(lambda m: "#" * len(m.group(0)), s)


def mask_href(h: str) -> str:
    """A link with every path token longer than three characters that has
    a digit in it masked, and the query dropped."""
    u = urlsplit(h or "")
    parts = [("<id>" if (len(seg) > 3 and re.search(r"\d", seg)) else seg) for seg in u.path.split("/")]
    return (u.scheme + "://" + u.netloc if u.netloc else "") + "/".join(parts) + ("?..." if u.query else "")


_OUTLINE_JS = r"""
(sel) => {
  const n = document.querySelector(sel);
  if (!n) return [];
  const out = [];
  const walk = (el, d) => {
    if (d > 7 || out.length > 250) return;
    const tag = el.tagName.toLowerCase();
    if (['script', 'style', 'svg', 'path'].includes(tag)) return;
    const cls = (el.className || '').toString().split(' ').filter(Boolean).slice(0, 3).join('.');
    const tid = el.getAttribute('data-testid') || el.getAttribute('data-test-selector') || el.getAttribute('role') || '';
    out.push('  '.repeat(d) + tag + (cls ? '.' + cls : '') + (tid ? ' [' + tid + ']' : '') + (el.children.length ? '' : ' = ' + (el.innerText || '').trim().length + ' chars'));
    for (const c of el.children) walk(c, d + 1);
  };
  walk(n, 0);
  return out;
}
"""


def json_shape(obj, depth: int = 0):
    """The shape of a JSON answer, keys kept, values replaced by their
    type, lists cut to one entry. Nothing personal survives."""
    if depth > 6:
        return "..."
    if isinstance(obj, dict):
        return {k: json_shape(v, depth + 1) for k, v in list(obj.items())[:40]}
    if isinstance(obj, list):
        return [f"list of {len(obj)}"] + ([json_shape(obj[0], depth + 1)] if obj else [])
    return type(obj).__name__


class JsonSniffer:
    """Records the address and shape of every JSON answer meijer.com
    sends while the survey runs, so the second round can read the list
    the way the page does. Values never leave the browser."""

    def __init__(self, page):
        self.page = page
        self.seen = []

        def on_response(resp):
            try:
                ctype = resp.headers.get("content-type", "")
                url = resp.url
                if "json" not in ctype or not is_safe_url(url) or len(self.seen) >= 40:
                    return
                body = resp.json()
                self.seen.append({"url": mask_href(url), "status": resp.status, "shape": json_shape(body)})
            except Exception:
                pass
        self._fn = on_response
        page.on("response", on_response)

    def stop(self):
        try:
            self.page.remove_listener("response", self._fn)
        except Exception:
            pass
        return self.seen


def survey_history_page(page) -> dict:
    """The payment-history frame as this browser shows it, masked: its
    words line by line, every link inside it with its kind, the rows the
    app would take and what it makes of them, and the frame's outline."""
    out = {"url": mask_href(page.url or ""), "title": "", "state": history_state(page),
           "candidates_tried": [mask_href(u) for u in ORDER_CANDIDATES],
           "lines": [], "links": [], "rows": 0, "parsed": [], "outline": []}
    try:
        out["title"] = page.title() or ""
    except Exception:
        pass
    try:
        text = page.locator(FRAME).first.inner_text(timeout=5000)
        out["lines"] = [mask_text(ln.strip()) for ln in text.splitlines() if ln.strip()][:200]
    except Exception:
        pass
    try:
        links = page.evaluate("""(f) => Array.from(document.querySelectorAll(f + ' a')).map(a => ({
            text: (a.innerText || '').trim().replace(/\\s+/g, ' ').slice(0, 60),
            label: a.getAttribute('aria-label') || a.getAttribute('title') || '',
            href: a.getAttribute('href') || '', download: a.hasAttribute('download'),
            cls: (a.className || '').toString().slice(0, 40)}))""", FRAME) or []
        out["links"] = [{"text": mask_text(x["text"]), "label": mask_text(x["label"]), "href": mask_href(x["href"]),
                         "download": x["download"], "cls": x["cls"],
                         "verdict": "safe" if is_safe_control(x["text"] or x["label"]) else "not clicked"}
                        for x in links[:80]]
    except Exception:
        pass
    cards = collect_cards(page)
    out["rows"] = len(cards)
    for c in cards[:3]:
        p = card_to_purchase(c)
        out["parsed"].append({"date": p.purchase_date, "total": bool(p.total), "key_shape": mask_text(p.order_number),
                              "description": mask_text(p.items[0].name)[:60], "receipt_links": len(receipt_links(c))}
                             if p else "row without an amount")
    try:
        out["outline"] = page.evaluate(_OUTLINE_JS, "main") or []
    except Exception:
        pass
    return out


def survey_receipt(page, url: str) -> dict:
    """What one receipt link gives: a PDF, or a page, described masked."""
    out = {"href": mask_href(url), "kind": "", "status": None, "lines": [], "outline": []}
    if not is_safe_url(url):
        out["kind"] = "refused, not a Meijer host"
        return out
    try:
        res = _fetch_with_status(page, url)
    except Exception as e:
        out["kind"] = "fetch failed " + mask_text(str(e))[:80]
        return out
    out["status"] = res.get("status")
    ctype = (res.get("type") or "")[:40]
    data = base64.b64decode(res["b64"]) if res.get("b64") else b""
    if data[:5] == b"%PDF-":
        out["kind"] = f"pdf, {len(data)} bytes"
        return out
    out["kind"] = f"page, {ctype}"
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(1500)
        text = page.locator("main").first.inner_text(timeout=5000) if page.locator("main").count() \
            else page.locator("body").inner_text(timeout=5000)
        out["lines"] = [mask_text(ln.strip()) for ln in text.splitlines() if ln.strip()][:120]
        out["rendered"] = receipt_is_present(page)
        out["outline"] = page.evaluate(_OUTLINE_JS, "main") or []
    except Exception as e:
        out["error"] = mask_text(str(e))[:120]
    return out


# ---------------------------------------------------------------------------
# Kept for the shared orchestrator's helpers
# ---------------------------------------------------------------------------

def open_receipt_section(page) -> bool:
    return receipt_is_present(page)


def find_print_receipt_controls(page) -> list:
    return []


def find_invoice_controls(page) -> list:
    return []


def find_printing_frame(page, wait_ms: int = 2000):
    return None


def find_receipt_iframe(page):
    return None


def to_json(obj) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False, default=str)
