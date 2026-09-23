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
from dataclasses import dataclass, field
from typing import List, Optional
from urllib.parse import urljoin, urlsplit

from paperpull_core.models import IN_STORE, ONLINE, Item, Purchase
from storage import now_iso

from paperpull_core.redact import private_words, set_private_words  # noqa: F401
from paperpull_core.urls import is_safe_url as _host_allows

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
    "access denied", "pardon our interruption", "press and hold",
]

RATE_LIMIT_MARKERS = [
    "too many requests", "rate limit", "try again later",
    "temporarily blocked", "http error 429",
]


def parse_date(text: str) -> Optional[str]:
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
TAB_ONLINE_RE = re.compile(r"^\s*online\s+orders?\s*$", re.I)
IN_STORE_ROW_RE = re.compile(r"\bin-?store\b\s*:", re.I)


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
                page.wait_for_timeout(2500)
                return True
        # Not a role the page declares, so by its text.
        loc = page.get_by_text(pattern)
        for i in range(min(loc.count(), 4)):
            el = loc.nth(i)
            if el.is_visible():
                el.click(timeout=5000)
                page.wait_for_timeout(2500)
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


def goto_orders(page, page_no: int = 1) -> None:
    """Open the orders page. On the first page, try each candidate route
    in turn and stay on the first that is signed in and looks like a list
    of orders or says there are none."""
    if page_no > 1:
        page.goto(orders_url(page_no), wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(2500)
        return
    for url in ORDER_CANDIDATES:
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        try:
            page.wait_for_selector(FALLBACK["page_ready"], timeout=15000)
        except Exception:
            pass
        page.wait_for_timeout(2500)
        if looks_signed_out(page):
            return
        if _looks_like_orders(page):
            return
    page.goto(ORDERS_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(2500)


def history_state(page) -> str:
    """"empty" when the page says there are no orders, else ""."""
    try:
        text = page.locator(FRAME).first.inner_text(timeout=5000)
    except Exception:
        return ""
    return "empty" if EMPTY_RE.search(text) else ""


@dataclass
class RawCard:
    text: str
    links: List[dict] = field(default_factory=list)   # {text, href, label, download}
    kind: str = ONLINE


# Every row inside the frame that holds a money amount, with its links.
# GUESS at what a row is, so anything list-like is tried, smallest first,
# and a row that contains another matching row is dropped.
_COLLECT_ROWS_JS = r"""
(rowSel) => {
  const cands = Array.from(document.querySelectorAll(rowSel));
  const money = /\$\s*-?[\d,]+\.\d{2}/;
  const rows = cands.filter(e => money.test(e.innerText || ''));
  const out = [];
  for (const r of rows) {
    if (rows.some(o => o !== r && r.contains(o))) continue;   // keep the innermost
    const links = Array.from(r.querySelectorAll('a')).map(a => ({
      text: (a.innerText || '').trim().replace(/\s+/g, ' ').slice(0, 80),
      href: a.getAttribute('href') || '',
      label: a.getAttribute('aria-label') || a.getAttribute('title') || '',
      download: a.hasAttribute('download'),
    }));
    out.push({text: (r.innerText || '').trim().slice(0, 600), links});
    if (out.length >= 400) break;
  }
  return out;
}
"""


def collect_both_tabs(page) -> List[RawCard]:
    """Every row on both tabs. The page opens on Online Orders, and a
    person who only shops in the store has everything on the other one
    (#42)."""
    cards: List[RawCard] = []
    seen = set()
    for pattern, label in ((TAB_IN_STORE_RE, "In-Store Receipts"), (TAB_ONLINE_RE, "Online Orders")):
        if not open_tab(page, pattern):
            log.info("no %s tab on this page", label)
            continue
        found = collect_cards(page)
        log.info("%s: %d row(s)", label, len(found))
        for c in found:
            if c.text in seen:
                continue
            seen.add(c.text)
            cards.append(c)
    if not cards:
        cards = collect_cards(page)
    return cards


def collect_cards(page, purchase_type: str = "") -> List[RawCard]:
    try:
        raw = page.evaluate(_COLLECT_ROWS_JS, FALLBACK["row"]) or []
    except Exception as e:
        log.warning("Row collection failed: %s", e)
        raw = []
    return [RawCard(text=r.get("text") or "", links=r.get("links") or []) for r in raw]


# A row's own controls, including an icon with no text, so the PDF icon
# at the end of an in-store row can be pressed (#42).
_ROW_CONTROLS_JS = r"""([text, money]) => {
  const rows = [];
  const walk = (el) => {
    for (const c of el.children) {
      const t = (c.innerText || '').trim();
      if (t.includes(money) && t.includes(text.slice(0, 12))) rows.push(c);
      walk(c);
    }
  };
  walk(document.body);
  if (!rows.length) return {found: false};
  rows.sort((a, b) => (a.contains(b) ? 1 : b.contains(a) ? -1 : 0));
  const row = rows[0];
  const out = [];
  const collect = (el) => {
    for (const c of el.children) {
      const tag = c.tagName.toLowerCase();
      const role = c.getAttribute('role') || '';
      const label = c.getAttribute('aria-label') || c.getAttribute('title') || '';
      const cls = (c.className || '').toString();
      const clickable = tag === 'a' || tag === 'button' || role === 'button' || role === 'link' ||
                        getComputedStyle(c).cursor === 'pointer';
      const looksPdf = /pdf|receipt|download/i.test(label + ' ' + cls + ' ' + (c.getAttribute('href') || ''));
      if (clickable || looksPdf) {
        out.push({el: c, text: (c.innerText || '').trim().slice(0, 40), label: label.slice(0, 40),
                  href: c.getAttribute('href') || '', pdf: looksPdf});
      }
      collect(c);
    }
  };
  collect(row);
  out.sort((a, b) => (b.pdf ? 1 : 0) - (a.pdf ? 1 : 0));
  return {found: true, cands: out.map(c => ({text: c.text, label: c.label, href: c.href, pdf: c.pdf})),
          els: out.map(c => c.el), outline: (row.innerText || '').slice(0, 200)};
}"""


def row_controls(page, purchase):
    """(candidates, handles) for the row this purchase came from, the PDF
    icon first. None when the row is not on the page."""
    money = purchase.total or ""
    text = (purchase.items[0].name if purchase.items else "") or purchase.purchase_date or ""
    try:
        h = page.evaluate_handle(_ROW_CONTROLS_JS, [text, money])
        props = h.get_properties()
        if "els" not in props:
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
        if not is_safe_url(href):
            continue
        name = ln.get("text") or ln.get("label") or "Receipt"
        if FORBIDDEN_CONTROL_RE.search(name):
            continue
        out.append({**ln, "href": href, "name": name})
    out.sort(key=lambda ln: (0 if (ln.get("download") or re.search(r"\.pdf(\?|$)|download", ln["href"], re.I)) else 1))
    return out


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

_FETCH_AS_B64 = r"""
async (url) => {
  const res = await fetch(url, {credentials: 'include', redirect: 'follow'});
  if (!res.ok) return {status: res.status, type: res.headers.get('content-type') || '', b64: ''};
  const buf = await res.arrayBuffer();
  let bin = ''; const bytes = new Uint8Array(buf);
  for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  return {status: res.status, type: res.headers.get('content-type') || '', url: res.url, b64: btoa(bin)};
}
"""


def fetch_receipt_bytes(page, url: str) -> Optional[bytes]:
    """The receipt link fetched from inside the signed-in page. Bytes when
    the answer is a PDF, None when it is a page (to be printed) or an
    error."""
    if not is_safe_url(url):
        return None
    try:
        out = page.evaluate(_FETCH_AS_B64, url) or {}
    except Exception as e:
        log.info("fetch of %s failed: %s", url[:80], e)
        return None
    if not out.get("b64"):
        return None
    data = base64.b64decode(out["b64"])
    if data[:5] == b"%PDF-":
        return data
    return None


def press_row_receipt(page, purchase, trace=None):
    """Press the row's own receipt control, the PDF icon at its end, and
    take whatever the page produces: a download, a PDF answer, or the
    window it opens (the page warns a pop-up blocker will stop it, so it
    opens one). Bytes, or None."""
    found = row_controls(page, purchase)
    if not found:
        if trace is not None:
            trace.append({"note": "the row for this purchase is not on the page"})
        return None
    cands, els = found
    if trace is not None:
        trace.append({"note": "the row's controls",
                      "candidates": [{**c, "text": mask_text(c["text"]), "label": mask_text(c["label"]),
                                      "href": mask_href(c["href"])} for c in cands[:12]]})
    ctx = page.context
    for c, el in list(zip(cands, els))[:6]:
        if el is None:
            continue
        label = c["label"] or c["text"] or "receipt"
        if FORBIDDEN_CONTROL_RE.search(label):
            continue
        href = urljoin(BASE, c["href"] or "")
        if c["href"] and is_safe_url(href):
            body = fetch_receipt_bytes(page, href)
            if body:
                return body
        got = {}

        def on_response(res):
            try:
                if got or "pdf" not in (res.headers.get("content-type") or "").lower():
                    return
                if not is_safe_url(res.url or ""):
                    return
                body = res.body()
                if body[:5] == b"%PDF-":
                    got["body"] = body
            except Exception:
                pass
        downloads = []
        ctx.on("response", on_response)
        page.on("download", downloads.append)
        before = set(ctx.pages)
        try:
            el.click(timeout=5000)
        except Exception as e:
            if trace is not None:
                trace.append({"note": "click failed", "control": mask_text(label)[:40], "error": str(e)[:100]})
        try:
            for _ in range(20):
                page.wait_for_timeout(500)
                if got or downloads:
                    break
                for extra in [x for x in ctx.pages if x not in before]:
                    try:
                        extra.wait_for_load_state("domcontentloaded", timeout=5000)
                    except Exception:
                        pass
                    u = extra.url or ""
                    if u.startswith("blob:") or is_safe_url(u):
                        body = fetch_receipt_bytes(extra, u) if not u.startswith("blob:") else None
                        if not body:
                            try:
                                body = extra.evaluate(_FETCH_AS_B64, u)
                                body = base64.b64decode(body["b64"]) if body.get("b64") else None
                            except Exception:
                                body = None
                        if body and body[:5] == b"%PDF-":
                            got["body"] = body
                    if u and not got:
                        if trace is not None:
                            trace.append({"note": "the control opened a window", "url": mask_href(u)})
                    try:
                        extra.close()
                    except Exception:
                        pass
                if got:
                    break
        finally:
            try:
                ctx.remove_listener("response", on_response)
            except Exception:
                pass
            try:
                page.remove_listener("download", downloads.append)
            except Exception:
                pass
        if downloads and not got:
            # A download the browser saved for itself. Its own file is read
            # rather than moved, so nothing is left in the browser's folder
            # half-taken.
            try:
                import pathlib
                saved = downloads[0].path()
                if saved:
                    body = pathlib.Path(saved).read_bytes()
                    if body[:5] == b"%PDF-":
                        got["body"] = body
            except Exception as e:
                if trace is not None:
                    trace.append({"note": "download save failed", "error": str(e)[:100]})
        if got.get("body"):
            if trace is not None:
                trace.append({"note": "the receipt came from the row's control", "control": mask_text(label)[:40]})
            return got["body"]
    return None


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
    return (page.url or "").split("#")[0].rstrip("/") == url.split("#")[0].rstrip("/")


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
        res = page.evaluate(_FETCH_AS_B64, url) or {}
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
