"""Archive the monitoring invoice views in SimpliSafe's signed-in web app."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from pathlib import Path
import re
import sys
import time
from urllib.parse import urlsplit

from playwright.sync_api import Error as BrowserError
from paperpull_core import identity, pdf_reader, pressing, receipt_pdf, shared_folder
from paperpull_core.controls import AUTH_CONTROL_RE, SETTINGS_CONTROL_RE
from paperpull_core.words import words_for as _words_for

HOST = "webapp.simplisafe.com"
AUTH_HOST = "auth.simplisafe.com"
BASE = f"https://{HOST}"
ACCOUNT_FRAGMENT = "/account"
DOCUMENTS_URL = BASE + "/#" + ACCOUNT_FRAGMENT
URLS = {"home": DOCUMENTS_URL, "login": DOCUMENTS_URL, "documents": DOCUMENTS_URL}
ALLOWED_HOSTS = {HOST}
LOGIN_URL_MARKERS = (AUTH_HOST,)
RATE_LIMIT_MARKERS = re.compile(r"too many requests|rate limit", re.I)
FORBIDDEN_CONTROL_RE = re.compile(r"\b(?:pay|payment|arm|disarm|cancel|delete|edit|save|change|submit)\b", re.I)
SAFE_DOC_CONTROL_RE = re.compile(
    r"^(?:[0-9a-f]{32}|Close|Download PDF|(?:(?:View|Download) )?Monitoring Bill"
    r"|Next page|Previous page)$", re.I
)
FALLBACK = {"doc_row": "ss-monitoring-payments table tbody tr",
            "next_page": "ss-monitoring-payments button.mat-mdc-paginator-navigation-next",
            "previous_page": "ss-monitoring-payments button.mat-mdc-paginator-navigation-previous"}

_INVOICE_ID = re.compile(r"[0-9a-f]{32}", re.I)
_INVOICE_TITLE = re.compile(r"Invoice\s*:\s*(?:[A-Za-z0-9]{2})?([0-9a-f]{32})", re.I)
_RANGE = re.compile(r"([0-9]{1,6})\s*[–-]\s*([0-9]{1,6})\s+of\s+([0-9]{1,6})")
_MAX_PAGES = 100

_MONITORING = "ss-monitoring-payments:visible"
_INVOICE_CSS = "ss-monitoring-payments table tbody td:nth-child(2) a"
_INVOICE_LINKS = _MONITORING + " table:visible tbody td:nth-child(2) a"
_DIALOG = "mat-dialog-container:visible"
_INVOICE = "ss-payment-details-display .invoice-container"
_CLOSE_CSS = "mat-dialog-container button.close"

# The paginator's own two buttons, each found by its Angular Material class
# and pressed only when its whole label is the one named here.
_TURNS = {1: ("button.mat-mdc-paginator-navigation-next", "Next page"),
          -1: ("button.mat-mdc-paginator-navigation-previous", "Previous page")}
_TURN_WAIT_S = 15.0
_TURN_PAUSE_MS = 800
_SETTLE_S = 15.0
_EMPTY_SETTLE_S = 6.0
_SETTLE_EVERY_MS = 500
_LIST_STEP = "read the monitoring history"
_OPEN_STEP = "open a monitoring invoice"


def _words():
    """The app's own words for what a press says (paperpull_core.words)."""
    return _words_for("SimpliSafe", sys.modules[__name__])

# The web app contains a second, hidden table for narrow screens. Only
# read the visible desktop table with the two explicitly named columns.
_TABLE_VIEW = r"""() => {
    const shown = e => !!e.getClientRects().length;
    const roots = [...document.querySelectorAll('ss-monitoring-payments')].filter(shown);
    if (roots.length !== 1) return null;
    const root = roots[0];
    const tables = [...root.querySelectorAll('table')].filter(table => {
        const heads = table.tHead?.rows[0]?.cells;
        return shown(table) && heads?.[0]?.innerText.trim() === 'Date'
            && heads?.[1]?.innerText.trim() === 'Invoice';
    });
    if (tables.length !== 1 || tables[0].tBodies.length !== 1) return null;
    const pager = root.querySelector('.mat-mdc-paginator-range-label');
    if (!pager || !shown(pager)) return null;
    return {
        range: pager.innerText.trim(),
        rows: [...tables[0].tBodies[0].rows].filter(shown).map(row => {
            const links = row.cells[1]?.querySelectorAll('a');
            return {
                date: row.cells[0]?.innerText.trim(),
                id: links?.length === 1 ? links[0].innerText.trim() : null
            };
        })
    };
}"""

_INVOICE_VIEW = r"""el => {
    const children = [...el.children];
    const heading = children.find(e => e.tagName === 'H2');
    const labels = children.filter(e => e.tagName === 'H3' && /^Date\s*:?$/i.test(e.innerText.trim()));
    const value = labels.length === 1 ? labels[0].nextElementSibling : null;
    const clone = el.cloneNode(true);
    clone.querySelectorAll('img,svg,link,style,button,input,form').forEach(e => e.remove());
    return {number: heading?.innerText.trim(), date: value?.tagName === 'P' ? value.innerText.trim() : null,
            body: clone.outerHTML};
}"""

_PRINT_HEAD = """<!doctype html><html><head><meta charset="utf-8">
<style>
body { color: #182534; font: 13px/1.5 Arial, sans-serif; margin: 28px; }
h1 { color: #174367; font-size: 24px; margin: 0 0 20px; }
h2 { font-size: 17px; overflow-wrap: anywhere; }
h3 { font-size: 13px; margin-bottom: 3px; }
h3 + p { margin-top: 0; }
hr { border: 0; border-top: 1px solid #c9d4df; margin: 14px 0; }
table { border-collapse: collapse; margin: 10px 0; width: 100%; }
th, td { border-bottom: 1px solid #d7e1e8; padding: 6px 5px; text-align: left; }
th { color: #174367; }
tr { break-inside: avoid; }
.invoice-breakdown { margin-left: auto; width: 48%; }
.total { font-weight: bold; }
</style></head><body><h1>SimpliSafe</h1>"""


class SessionExpired(RuntimeError):
    """The account holder needs to sign in again."""


class ListStopped(RuntimeError):
    """The monitoring invoice list could not be verified."""


class NoBills(ListStopped):
    """The table settled with no bills, which cannot be told from a history
    that has not arrived, so the list stops and says so in its own words."""


@dataclass(frozen=True)
class RawDoc:
    title: str
    date_text: str
    account: str
    document_id: str


@dataclass(frozen=True)
class Bill:
    invoice_id: str
    date: str

    @property
    def key(self) -> str:
        return sha256(("simplisafe:" + self.invoice_id.lower()).encode()).hexdigest()

    @property
    def record(self) -> RawDoc:
        return RawDoc("SimpliSafe Monitoring Bill", self.date, "", self.key)


def _origin(url: str):
    try:
        parsed = urlsplit(url or "")
    except ValueError:
        return "", ""
    return parsed.scheme, parsed.netloc


def is_safe_url(url: str) -> bool:
    return _origin(url) == ("https", HOST)


def is_session_url(url: str) -> bool:
    return is_safe_url(url) or _origin(url) == ("https", AUTH_HOST)


def is_safe_control(label: str) -> bool:
    return bool(SAFE_DOC_CONTROL_RE.fullmatch(label.strip())) and not any(
        pattern.search(label) for pattern in (FORBIDDEN_CONTROL_RE, AUTH_CONTROL_RE, SETTINGS_CONTROL_RE)
    )


def is_history_page_url(url: str) -> bool:
    if not is_safe_url(url):
        return False
    parsed = urlsplit(url)
    return parsed.path in ("", "/") and parsed.fragment.rstrip("/") == ACCOUNT_FRAGMENT


def looks_signed_out(page) -> bool:
    if _origin(page.url) == ("https", AUTH_HOST):
        return True
    try:
        return is_safe_url(page.url) and bool(page.locator("input[type=password]:visible").count())
    except BrowserError:
        # A page between two documents cannot be read. Nothing is taken
        # from it, and the read of the list that follows decides.
        return False


def detect_security_challenge(page):
    if not is_session_url(page.url):
        return None
    title = page.title()
    if RATE_LIMIT_MARKERS.search(title):
        return "SimpliSafe is limiting requests. Try again later."
    if re.search(r"just a moment|security check|verify (?:that )?you are human", title, re.I):
        return "SimpliSafe is asking for verification in the browser."
    return None


def _open_account(page) -> None:
    if looks_signed_out(page):
        raise SessionExpired()
    if not is_safe_url(page.url):
        raise ListStopped("Open Manage Account in the SimpliSafe sign-in window.")
    if page.locator(_DIALOG).count():
        raise ListStopped("Close the open SimpliSafe dialog before getting bills.")
    if not is_history_page_url(page.url):
        try:
            page.goto(DOCUMENTS_URL, wait_until="domcontentloaded", timeout=18000)
        except BrowserError:
            raise ListStopped("The SimpliSafe account page did not open.") from None


def _date(text: str | None) -> str:
    for fmt in ("%m/%d/%y", "%m/%d/%Y", "%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(text or "", fmt).date().isoformat()
        except ValueError:
            pass
    return ""


@dataclass(frozen=True)
class Shown:
    """One page of the Monitoring Payments table as it is drawn: the range
    its paginator prints, first and last row numbers and the whole count,
    and its bills in the order shown."""
    start: int
    end: int
    total: int
    bills: dict

    @property
    def keys(self) -> frozenset:
        return frozenset(self.bills)


def _parsed(view):
    """Read one drawn page. A page has to print its range, "1 – 10 of 37"
    or "0 of 0", and show exactly the rows that range names, each with one
    invoice number and a readable date, no number twice. Gives the page,
    or None and what is wrong with it."""
    range_label = " ".join(str(view.get("range") or "").split()) if isinstance(view, dict) else ""
    rows = view.get("rows") if isinstance(view, dict) else None
    if not isinstance(rows, list):
        return None, "The Monitoring Payments table or its bill count was unavailable."
    if range_label == "0 of 0":
        start = end = total = 0
    else:
        shown = _RANGE.fullmatch(range_label)
        if not shown:
            return None, "The Monitoring Payments table or its bill count was unavailable."
        start, end, total = (int(part) for part in shown.groups())
        if not 1 <= start <= end <= total:
            return None, "The monitoring table prints a range it cannot hold."
    bills = {}
    for row in rows:
        invoice_id = (row.get("id") if isinstance(row, dict) else None) or ""
        if not _INVOICE_ID.fullmatch(invoice_id):
            return None, "A monitoring bill is missing its invoice number."
        date = _date(row.get("date"))
        if not date:
            return None, "A monitoring bill has an unreadable date."
        bill = Bill(invoice_id, date)
        if bill.key in bills:
            return None, "SimpliSafe listed the same invoice more than once."
        bills[bill.key] = bill
    if len(bills) != (end - start + 1 if total else 0):
        return None, "The monitoring table disagrees with the invoice count."
    return Shown(start, end, total, bills), ""


def _parse_view(view) -> Shown:
    shown, wrong = _parsed(view)
    if shown is None:
        raise ListStopped(wrong)
    return shown


def _read(page):
    """The page as drawn right now, or None while it cannot be read."""
    try:
        return _parsed(page.evaluate(_TABLE_VIEW))[0]
    except BrowserError:
        return None


def _view(page) -> Shown:
    if looks_signed_out(page):
        raise SessionExpired()
    if not is_history_page_url(page.url):
        raise ListStopped("Open Manage Account → Monitoring Payments in SimpliSafe.")
    try:
        page.locator(_MONITORING + " table:visible").first.wait_for(state="visible", timeout=12000)
    except BrowserError:
        if looks_signed_out(page):
            raise SessionExpired() from None
        raise ListStopped("The visible Monitoring Payments table did not load.") from None
    return _settled(page)


def _settled(page) -> Shown:
    """The table once two reads in a row agree. Angular Material draws the
    table's header and prints "0 of 0" before the history arrives, so an
    empty history is believed only after it has stayed empty for
    _EMPTY_SETTLE_S, and a read that does not hold together yet (rows under
    a "0 of 0" still being replaced) is read again until _SETTLE_S."""
    deadline = time.monotonic() + _SETTLE_S
    last = None
    empty_since = None
    while True:
        if looks_signed_out(page):
            raise SessionExpired()
        try:
            now, wrong = _parsed(page.evaluate(_TABLE_VIEW))
        except BrowserError:
            now, wrong = None, "The visible Monitoring Payments table did not load."
        if now is not None and now == last:
            if now.total:
                return now
            empty_since = empty_since or time.monotonic()
            if time.monotonic() - empty_since >= _EMPTY_SETTLE_S:
                # A table that still prints "0 of 0" cannot be told from one
                # whose history has not arrived, so it is never a whole list.
                raise NoBills("SimpliSafe shows no monitoring bills yet. Run again once "
                                  "Monitoring Payments lists them.")
        elif now is None or now.total:
            empty_since = None
        last = now
        if time.monotonic() >= deadline:
            raise ListStopped(wrong or "The Monitoring Payments table did not settle.")
        page.wait_for_timeout(_SETTLE_EVERY_MS)


_TURN_GUARD = r"""(el, label) => {
    const root = el.closest('ss-monitoring-payments');
    return el.tagName === 'BUTTON' && !el.closest('form') && !!root
        && !!el.closest('mat-paginator, .mat-mdc-paginator')
        && (el.getAttribute('aria-label') || '').trim() === label
        && (el.getAttribute('type') || 'button').toLowerCase() === 'button'
        && !el.hasAttribute('href') && !!el.getClientRects().length;
}"""

_TURNED_OFF = r"""el => el.disabled || el.getAttribute('aria-disabled') === 'true'"""


def _turn(page, shown: Shown, way: int) -> Shown:
    """Press the paginator's own Next page (way 1) or Previous page (way -1)
    button once, the press a person makes, and answer the page it brings.

    The page is answered only once its range is the one next to `shown`,
    its count is the same, and its rows are bills `shown` did not hold. The
    range label alone is not enough, since SimpliSafe can print the next
    range while the rows of the page before still show. Anything else stops
    the list, nothing is read as the next page."""
    css, label = _TURNS[way]
    button = page.locator(f"{_MONITORING} {css}:visible")
    try:
        named = button.get_attribute("aria-label", timeout=2000) if button.count() == 1 else None
        if named != label or not is_safe_control(named) or not button.evaluate(_TURN_GUARD, label):
            raise ListStopped("SimpliSafe's monitoring history page control changed.")
        if button.evaluate(_TURNED_OFF):
            raise ListStopped("SimpliSafe's monitoring history ended before its count.")
    except BrowserError:
        raise ListStopped("SimpliSafe's monitoring history page control changed.") from None
    page.wait_for_timeout(_TURN_PAUSE_MS)
    # Read as turned on just above, so a button the page turns off during
    # the press stops the run (pressing.TurnedOff).
    pressing.click(page, button, css=css, words=_words(), step=_LIST_STEP,
                   what=f"the monitoring history's {label} button")
    deadline = time.monotonic() + _TURN_WAIT_S
    while True:
        if looks_signed_out(page):
            raise SessionExpired()
        now = _read(page)
        if now is not None and now.total == shown.total and not (now.keys & shown.keys) and (
                (way == 1 and now.start == shown.end + 1)
                or (way == -1 and now.end == shown.start - 1)):
            return now
        if now is not None and now.total != shown.total:
            raise ListStopped("The monitoring invoice count changed. Run discovery again.")
        if time.monotonic() >= deadline:
            raise ListStopped("SimpliSafe did not show the next page of the monitoring history.")
        page.wait_for_timeout(250)


def _first_page(page, shown: Shown) -> Shown:
    """Go back to the history's first page by Previous page, when it shows
    a later one."""
    for _ in range(_MAX_PAGES):
        if shown.start <= 1:
            return shown
        shown = _turn(page, shown, -1)
    raise ListStopped("The monitoring history is longer than PaperPull reads.")


def _walk(page):
    """Every bill of the history, read page by page from the first through
    the paginator's own Next page button, with the page each was shown on.
    A history of one page presses nothing."""
    shown = _first_page(page, _view(page))
    size = shown.end if shown.total else 0
    bills, where = {}, {}
    for number in range(_MAX_PAGES):
        if shown.start != number * size + 1 and shown.total:
            raise ListStopped("The monitoring history pages are not the same size.")
        if shown.keys & set(bills):
            raise ListStopped("SimpliSafe listed the same invoice more than once.")
        for key, bill in shown.bills.items():
            bills[key] = bill
            where[key] = number
        if len(bills) == shown.total:
            return bills, where, size, shown.total
        if shown.end >= shown.total:
            raise ListStopped("The monitoring table disagrees with the invoice count.")
        shown = _turn(page, shown, 1)
    raise ListStopped("The monitoring history is longer than PaperPull reads.")


_RUN: dict = {}


def collect_download_docs(page) -> list[RawDoc]:
    _RUN.clear()
    _open_account(page)
    bills, where, size, total = _walk(page)
    _RUN.update(page=page, bills=bills, where=where, size=size, total=total)
    return [bill.record for bill in bills.values()]


def bill_list_ready(page) -> bool:
    try:
        _open_account(page)
        _view(page)
    except (SessionExpired, ListStopped):
        return False
    return True


def bill_list_problem(page) -> str:
    """What keeps the bill history from being ready, in words a person can
    act on, or "" when it is ready. A table with no bills says that, not
    where to find a page the person already has open."""
    try:
        _open_account(page)
        _view(page)
    except NoBills as stop:
        return str(stop)
    except (SessionExpired, ListStopped):
        return "Open Manage Account → Monitoring Payments in that window."
    return ""


def _show(page, bill: Bill) -> bool:
    """Bring up the page the bill was listed on, through the paginator's own
    buttons, and say whether that page shows it now."""
    target = _RUN["where"][bill.key] * _RUN["size"] + 1
    shown = _view(page)
    went = 0
    for _ in range(_MAX_PAGES):
        if shown.total != _RUN["total"] or target > shown.total:
            return False
        if shown.start == target:
            return shown.bills.get(bill.key) == bill
        way = 1 if shown.start < target else -1
        if went and way != went:
            # Passed over the page, so the pages are not the size they were
            # listed at. The history is listed again.
            return False
        went = way
        shown = _turn(page, shown, way)
    return False


def _invoice_number(text):
    match = _INVOICE_TITLE.fullmatch(text or "")
    return match[1].lower() if match else ""


def _close_invoice(page, dialog):
    """Press the invoice dialog's own Close button, through the guards."""
    close = dialog.locator("button.close")
    if (close.count() != 1 or not is_safe_control(close.inner_text(timeout=2000)) or not close.evaluate(
        "e=>!e.form && e.innerText.trim().toLowerCase() === 'close'"
    )):
        raise ListStopped("SimpliSafe's invoice close control changed.")
    pressing.click(page, close, css=_CLOSE_CSS, words=_words(), step=_OPEN_STEP,
                   what="the monitoring invoice's Close button")
    dialog.wait_for(state="hidden", timeout=5000)


def _invoice_html(page, bill):
    dialog = page.locator(_DIALOG)
    if dialog.count():
        raise ListStopped("Close the open SimpliSafe dialog before getting bills.")
    links = page.locator(_INVOICE_LINKS)
    matching = links.evaluate_all(r"""(els, id) => els.flatMap((el, index) =>
        el.innerText.trim() === id ? [index] : []
    )""", bill.invoice_id)
    if len(matching) != 1:
        raise ListStopped("The selected invoice's view control changed.")
    opened = False
    invoice = dialog.locator(_INVOICE)
    link = links.nth(matching[0])
    try:
        if (not is_safe_control(link.inner_text(timeout=3000)) or not link.evaluate(
            """(el, id) => el.innerText.trim() === id && !el.hasAttribute('href') &&
                          !el.hasAttribute('target') && !el.closest('form')""",
            bill.invoice_id,
        )):
            raise ListStopped("The selected invoice's view control changed.")
        try:
            pressing.click(page, link, css=_INVOICE_CSS, words=_words(), step=_OPEN_STEP,
                           what=f"the monitoring invoice row of {bill.date}")
        except pressing.TurnedOff:
            return ""
        invoice.wait_for(state="visible", timeout=7000)
        if dialog.count() != 1 or invoice.count() != 1:
            raise ListStopped("SimpliSafe opened an unexpected invoice view.")
        opened = True
        data = invoice.evaluate(_INVOICE_VIEW)
        view_date = _date(data["date"])
        if _invoice_number(data["number"]) != bill.invoice_id.lower() or view_date != bill.date:
            return ""
        return _PRINT_HEAD + data["body"] + "</body></html>"
    except BrowserError:
        if looks_signed_out(page):
            raise SessionExpired() from None
        raise ListStopped("SimpliSafe could not open this monitoring invoice.") from None
    finally:
        # A signed-out page has no Close to press, and the sign-in stop in
        # flight is the one the run has to say.
        if opened and not looks_signed_out(page):
            try:
                _close_invoice(page, dialog.filter(has=page.locator(_INVOICE)))
            except BrowserError:
                raise ListStopped("SimpliSafe's invoice viewer did not close.") from None


def _pdf_matches(data, bill):
    if not data.startswith(b"%PDF-"):
        return False
    try:
        pages = pdf_reader.page_texts(data, pages=1)
    except Exception:
        return False
    if not pages:
        return False
    lines = [" ".join(line.split()) for line in pages[0].splitlines() if line.strip()]
    expected = bill.invoice_id.lower()
    if not any(_invoice_number(line) == expected for line in lines):
        return False
    return any(label.casefold().rstrip(":").strip() == "date"
               and identity.contains(value, identity.date_variants(bill.date), "date")
               for label, value in zip(lines, lines[1:]))


def download_bill(page, date: str, out_path: Path, *, document_id: str) -> bool:
    if _RUN.get("page") is not page:
        collect_download_docs(page)
    bill = _RUN["bills"].get(document_id)
    if not bill or bill.date != date:
        raise ListStopped("The requested invoice no longer matches the monitoring history.")
    # The bill's own page is brought up by the paginator's buttons. A
    # history that moved since it was listed is listed again from its first
    # page, and a bill that is not where that listing puts it stops the list.
    if not _show(page, bill):
        collect_download_docs(page)
        if _RUN["bills"].get(document_id) != bill or not _show(page, bill):
            raise ListStopped("The requested invoice disappeared from the monitoring history.")
    html = _invoice_html(page, bill)
    if not html:
        return False
    data = receipt_pdf.inert_pdf_bytes(page, html)
    if not _pdf_matches(data, bill):
        return False
    shared_folder.write_bytes(out_path, data)
    return True
