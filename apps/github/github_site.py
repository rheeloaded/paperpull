"""ALL GitHub selectors, URL patterns, and page behavior live here.

When GitHub changes its website, repair this file only.

How GitHub's payment history works, mapped on 2026-09-21 against a
signed-in personal account that has NEVER paid GitHub anything, plus
GitHub's own documentation. The parts that need a payment to verify are
marked GUESS and are what the first tester's Diagnose file confirms.

* The page is ``https://github.com/account/billing/history``, titled
  "Payment history", the "Payment history" entry under Billing and
  licensing in Settings. It is a server-rendered page inside
  ``turbo-frame#settings-frame``. With no payments it shows a blank
  slate reading "You have not made any payments." VERIFIED.
  ``?page=N`` is accepted. VERIFIED that it answers, GUESS that it pages.
* GitHub's documentation says the page lists each payment with its date,
  amount and payment method, that an eye icon views the receipt, and
  that a download icon under "Receipt" or "Invoice" downloads it. So
  each row (GUESS at the markup, a table row or a list item) carries a
  date, an amount, a description and one or more links whose text or
  label says receipt, invoice, view or download.
* Capture (GUESS at which applies): a link that points at a PDF, or that
  carries a ``download`` attribute, is fetched from inside the signed-in
  page and saved. A link that opens a receipt page is followed and the
  receipt block printed to PDF. Both are read-only, and neither presses
  anything but the receipt's own link.
* GitHub has no bot wall. The app still opens the browser already on the
  machine so passkeys and password managers work as they do elsewhere.

Round two (#43, 2026-09-22), from a tester whose pilot captured five
receipts. His payment history is a table with the columns Date, ID,
Payment Method, Amount, Status, Receipt and Invoice, and the Receipt
column's link is ``/account/receipt/<id>``, which answers with a PDF.
There is no description of what was bought anywhere on the row, so two
payments on one day used to write the same filename and the second got
" (2)". The ID column is the one thing that tells them apart, and it is
GitHub's own short payment id, so it goes in the filename.

Site layer verified against the live site (empty account): 2026-09-21
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

from paperpull_core.models import ONLINE, Item, Purchase
from storage import now_iso

from paperpull_core.redact import private_words, set_private_words  # noqa: F401
from paperpull_core.urls import is_safe_url as _host_allows
from paperpull_core.capture import fetch_with_status as _fetch_with_status
from paperpull_core.dates import checked as _checked_date

log = logging.getLogger("github_receipts.site")

# ---------------------------------------------------------------------------
# URLs
# ---------------------------------------------------------------------------

BASE = "https://github.com"
ORDERS_URL = f"{BASE}/account/billing/history"
URLS = {
    "home": ORDERS_URL,
    "orders": ORDERS_URL,
    "account": f"{BASE}/settings/billing",
}

LOGIN_URL_MARKERS = ["/login", "/session", "/sessions/two-factor", "/sessions/verified-device",
                     "/password_reset", "/signup"]

# What the page's frame is called, and where its rows live. GUESS at the
# rows. A table row or a list item holding a money amount and a date.
FRAME = "turbo-frame#settings-frame"
FALLBACK = {
    "frame": FRAME,
    "row": f"{FRAME} table tbody tr, {FRAME} [role=row], {FRAME} ul li, {FRAME} .Box-row, {FRAME} [class*='Row'], {FRAME} [data-testid*='row'], {FRAME} [data-testid*='payment']",
    "receipt_link": f"{FRAME} a[href*='receipt'], {FRAME} a[href*='invoice'], {FRAME} a[aria-label*='eceipt'], {FRAME} a[aria-label*='nvoice'], {FRAME} a[download]",
    "receipt_area": "main, [role=main], body",
    "page_ready": FRAME,
    "print_page_body": "body",
}

EMPTY_RE = re.compile(r"you\s+have\s+not\s+made\s+any\s+payments", re.I)
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
    r"(pay\s+now|\bpay\b|make\s+(a\s+)?payment|payment\s+(method|information)|add\s+(a\s+)?card|"
    r"update\s+(card|payment)|remove|delete|cancel|downgrade|upgrade|change\s+plan|"
    r"edit|save|apply|redeem|coupon|budget|alert|spending\s+limit|sponsor\b|sponsorship|"
    r"sign\s+out|log\s+out|password|two-factor|ssh|token|email|verify|"
    r"start\s+(a\s+)?trial|buy|purchase|subscribe|billing\s+contact|add\s+seats?|manage)", re.I)

try:
    from paperpull_core.controls import SETTINGS_CONTROL_RE as _SHARED_SETTINGS
    FORBIDDEN_CONTROL_RE = re.compile(
        "(?:%s)|(?:%s)" % (FORBIDDEN_CONTROL_RE.pattern, _SHARED_SETTINGS.pattern),
        re.I)
except Exception:  # the shared core is optional at import time
    pass

SAFE_DOC_CONTROL_RE = re.compile(
    r"(receipt|invoice|view\s+receipt|download\s+(receipt|invoice)|payment\s+history|"
    r"next|previous|older|newer|page\s+\d+)", re.I)

SECURITY_CHALLENGE_MARKERS = [
    "verify your identity", "device verification", "two-factor authentication",
    "authentication code", "confirm access", "enter the code", "use your passkey",
    "are you a robot", "verify you are human", "checking your browser",
]

RATE_LIMIT_MARKERS = [
    "too many requests", "rate limit", "try again later", "abuse detection",
    "temporarily blocked", "http error 429", "whoa there",
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
    return "sign in to github" in body[:4000] and "payment history" not in body


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


ALLOWED_HOSTS = {"github.com", "githubusercontent.com"}


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


def goto_orders(page, page_no: int = 1) -> None:
    page.goto(orders_url(page_no), wait_until="domcontentloaded", timeout=60000)
    try:
        page.wait_for_selector(FRAME, timeout=20000)
    except Exception:
        pass
    page.wait_for_timeout(1500)


def history_state(page) -> str:
    """"empty" when GitHub says there have been no payments, else ""."""
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


def collect_cards(page, purchase_type: str = "") -> List[RawCard]:
    try:
        raw = page.evaluate(_COLLECT_ROWS_JS, FALLBACK["row"]) or []
    except Exception as e:
        log.warning("Row collection failed: %s", e)
        raw = []
    return [RawCard(text=r.get("text") or "", links=r.get("links") or []) for r in raw]


def receipt_links(card: RawCard) -> List[dict]:
    """The row's links that say receipt, invoice, view or download, host
    checked and guard checked, download links first."""
    out = []
    for ln in card.links:
        words = f"{ln.get('text', '')} {ln.get('label', '')} {ln.get('href', '')}"
        if not re.search(r"receipt|invoice|download|view", words, re.I):
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
    its identity across runs without an id GitHub would have to show."""
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


# GitHub's own payment id, the ID column: eight or so characters of
# capitals and digits, no spaces. It names a payment, not a person.
PAYMENT_ID_RE = re.compile(r"^[0-9A-Z]{6,16}$")


def payment_id(purchase) -> str:
    """The payment's own id, from the row's ID column, or ""."""
    for item in getattr(purchase, "items", None) or []:
        name = (item.name or "").strip()
        if PAYMENT_ID_RE.match(name):
            return name
    return ""


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
    return Purchase(
        purchase_type=ONLINE,
        purchase_date=date,
        order_number=key,
        total=total,
        status="Paid",
        store_info="GitHub",
        details_url=links[0]["href"] if links else ORDERS_URL,
        receipt_url=links[0]["href"] if links else "",
        items=[Item(name=description or "GitHub payment", quantity="1", line_total=total)],
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
    return bool(MONEY_RE.search(text) and re.search(r"receipt|invoice|paid|payment|total", text, re.I))


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
  const words = /receipt|invoice|paid|payment/i;
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


def survey_history_page(page) -> dict:
    """The payment-history frame as this browser shows it, masked: its
    words line by line, every link inside it with its kind, the rows the
    app would take and what it makes of them, and the frame's outline."""
    out = {"url": mask_text(page.url or ""), "title": "", "state": history_state(page),
           "lines": [], "links": [], "rows": 0, "parsed": [], "outline": []}
    try:
        out["title"] = page.title() or ""
    except Exception:
        pass
    try:
        text = page.locator(FRAME).first.inner_text(timeout=5000)
        out["lines"] = [mask_text(ln.strip()) for ln in text.splitlines() if ln.strip()][:150]
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
        out["outline"] = page.evaluate(_OUTLINE_JS, FRAME) or []
    except Exception:
        pass
    return out


def survey_receipt(page, url: str) -> dict:
    """What one receipt link gives: a PDF, or a page, described masked."""
    out = {"href": mask_href(url), "kind": "", "status": None, "lines": [], "outline": []}
    if not is_safe_url(url):
        out["kind"] = "refused, not a GitHub host"
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
