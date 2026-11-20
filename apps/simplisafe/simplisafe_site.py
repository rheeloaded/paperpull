"""Archive the monitoring invoice views in SimpliSafe's signed-in web app."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import re
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from playwright.sync_api import Error as BrowserError
from paperpull_core import identity, intake, pdf_reader, receipt_pdf, shared_folder
from paperpull_core.controls import AUTH_CONTROL_RE, SETTINGS_CONTROL_RE

HOST = "webapp.simplisafe.com"
AUTH_HOST = "auth.simplisafe.com"
API_HOST = "api.simplisafe.com"
BASE = f"https://{HOST}"
ACCOUNT_FRAGMENT = "/account"
DOCUMENTS_URL = BASE + "/#" + ACCOUNT_FRAGMENT
URLS = {"home": DOCUMENTS_URL, "login": DOCUMENTS_URL, "documents": DOCUMENTS_URL}
ALLOWED_HOSTS = {HOST}
LOGIN_URL_MARKERS = (AUTH_HOST,)
RATE_LIMIT_MARKERS = re.compile(r"too many requests|rate limit", re.I)
FORBIDDEN_CONTROL_RE = re.compile(r"\b(?:pay|payment|arm|disarm|cancel|delete|edit|save|change|submit)\b", re.I)
SAFE_DOC_CONTROL_RE = re.compile(
    r"^(?:[0-9a-f]{32}|Close|Download PDF|(?:(?:View|Download) )?Monitoring Bill)$", re.I
)
FALLBACK = {"doc_row": "ss-monitoring-payments table tbody tr"}

_HISTORY_PATH = re.compile(r"/v1/users/[0-9]{1,20}/paymentHistory")
_HISTORY_ROUTE = re.compile(r"^https://api\.simplisafe\.com/v1/users/[0-9]{1,20}/paymentHistory(?:\?.*)?$")
_INVOICE_ID = re.compile(r"[0-9a-f]{32}", re.I)
_INVOICE_TITLE = re.compile(r"Invoice\s*:\s*(?:[A-Za-z0-9]{2})?([0-9a-f]{32})", re.I)
_PAGER = re.compile(r"(?:[0-9]+\s*[–-]\s*[0-9]+\s+of\s+)?([0-9]+)")
_MAX_INVOICES = 500

_MONITORING = "ss-monitoring-payments:visible"
_INVOICE_LINKS = _MONITORING + " table:visible tbody td:nth-child(2) a"
_DIALOG = "mat-dialog-container:visible"
_INVOICE = "ss-payment-details-display .invoice-container"

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
    return _origin(page.url) == ("https", AUTH_HOST) or (
        is_safe_url(page.url) and bool(page.locator("input[type=password]:visible").count())
    )


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


def _parse_view(view):
    range_label = view["range"] if view else ""
    total = _PAGER.fullmatch("0" if range_label == "0 of 0" else range_label)
    if not total:
        raise ListStopped("The Monitoring Payments table or its bill count was unavailable.")
    bills = {}
    for row in view["rows"]:
        invoice_id = row.get("id") or ""
        if not _INVOICE_ID.fullmatch(invoice_id):
            raise ListStopped("A monitoring bill is missing its invoice number.")
        date = _date(row.get("date"))
        if not date:
            raise ListStopped("A monitoring bill has an unreadable date.")
        bill = Bill(invoice_id, date)
        if bill.key in bills:
            raise ListStopped("SimpliSafe listed the same invoice more than once.")
        bills[bill.key] = bill
    count = int(total[1])
    if len(bills) > count:
        raise ListStopped("The monitoring table disagrees with the invoice count.")
    return count, bills


def _view(page):
    if looks_signed_out(page):
        raise SessionExpired()
    if not is_history_page_url(page.url):
        raise ListStopped("Open Manage Account → Monitoring Payments in SimpliSafe.")
    try:
        page.locator(_MONITORING + " table:visible").first.wait_for(state="visible", timeout=12000)
        return _parse_view(page.evaluate(_TABLE_VIEW))
    except BrowserError:
        if looks_signed_out(page):
            raise SessionExpired() from None
        raise ListStopped("The visible Monitoring Payments table did not load.") from None


def _history_request(url):
    if _origin(url) != ("https", API_HOST):
        return None
    address = urlsplit(url)
    try:
        query = parse_qs(address.query, keep_blank_values=True, strict_parsing=True)
    except ValueError:
        return None
    if not _HISTORY_PATH.fullmatch(address.path) or address.fragment:
        return None
    if set(query) != {"numInvoices", "fromInvoice"} or query["fromInvoice"] != ["0"]:
        return None
    size = query["numInvoices"]
    return address if len(size) == 1 and re.fullmatch(r"[1-9][0-9]{0,2}", size[0]) else None


def _reply_ids(data, expected):
    if not isinstance(data, dict) or data.get("totalNumInvoices") != expected:
        raise ListStopped("The monitoring invoice count changed. Run discovery again.")
    rows = data.get("invoices")
    if not isinstance(rows, list) or len(rows) != expected:
        raise ListStopped("SimpliSafe returned only part of the requested monitoring history.")
    ids = [item.get("invoiceId") for item in rows if isinstance(item, dict)]
    if (len(ids) != expected
            or not all(isinstance(value, str) and _INVOICE_ID.fullmatch(value) for value in ids)
            or len({value.lower() for value in ids}) != expected):
        raise ListStopped("The monitoring history has invalid or repeated invoice numbers.")
    return {value.lower() for value in ids}


def _load_full_history(page, expected):
    """Widen the app's own one billing GET, without reading auth headers."""
    if not 1 <= expected <= _MAX_INVOICES:
        raise ListStopped("The monitoring history exceeds the supported invoice count.")
    received = set()
    errors = []
    attempted = False

    def intercept(route):
        nonlocal attempted
        request = route.request
        address = _history_request(request.url)
        if (attempted or request.method != "GET" or address is None
                or request.frame != page.main_frame or request.resource_type not in ("xhr", "fetch")):
            route.fallback()
            return
        attempted = True
        response = None
        try:
            query = urlencode({"numInvoices": expected, "fromInvoice": 0})
            url = urlunsplit((address.scheme, address.netloc, address.path, query, ""))
            response = route.fetch(url=url, max_redirects=0, timeout=18000)
            if response.status in (401, 403):
                raise SessionExpired()
            if response.status == 429:
                raise ListStopped("SimpliSafe is limiting monitoring-history requests.")
            mime = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if response.status != 200 or mime != "application/json":
                raise ListStopped("The full monitoring-history request did not complete.")
            received.update(_reply_ids(json.loads(intake.text_of(response, limit=3_000_000)), expected))
            route.fulfill(response=response)
        except (SessionExpired, ListStopped) as error:
            errors.append(error)
            route.abort()
        except (BrowserError, intake.TooLarge, ValueError):
            errors.append(ListStopped("The monitoring-history response could not be read."))
            route.abort()
        finally:
            if response is not None:
                response.dispose()

    page.route(_HISTORY_ROUTE, intercept)
    try:
        page.reload(wait_until="domcontentloaded", timeout=22000)
        page.wait_for_function(
            "(n) => { const read = " + _TABLE_VIEW + "; return read()?.rows.length === n; }",
            arg=expected, timeout=14000,
        )
    except BrowserError:
        if errors:
            raise errors[0] from None
        if looks_signed_out(page):
            raise SessionExpired() from None
        raise ListStopped("SimpliSafe did not display the full monitoring history.") from None
    finally:
        page.unroute(_HISTORY_ROUTE, intercept)

    if errors:
        raise errors[0]
    total, bills = _view(page)
    if total != expected or {bill.invoice_id.lower() for bill in bills.values()} != received:
        raise ListStopped("The rendered invoices do not match the full monitoring history.")
    return bills


_RUN: dict = {}


def collect_download_docs(page) -> list[RawDoc]:
    _RUN.clear()
    _open_account(page)
    total, bills = _view(page)
    if len(bills) != total:
        bills = _load_full_history(page, total)
    _RUN.update(page=page, bills=bills)
    return [bill.record for bill in bills.values()]


def bill_list_ready(page) -> bool:
    try:
        _open_account(page)
        _view(page)
    except (SessionExpired, ListStopped):
        return False
    return True


def _invoice_number(text):
    match = _INVOICE_TITLE.fullmatch(text or "")
    return match[1].lower() if match else ""


def _close_invoice(dialog):
    close = dialog.locator("button.close")
    if (close.count() != 1 or not is_safe_control(close.inner_text(timeout=2000)) or not close.evaluate(
        "e=>!e.form && e.innerText.trim().toLowerCase() === 'close'"
    )):
        raise ListStopped("SimpliSafe's invoice close control changed.")
    close.click(timeout=4000)
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
    link = None
    try:
        link = links.nth(matching[0]).element_handle(timeout=3000)
        if (link is None or not is_safe_control(link.inner_text()) or not link.evaluate(
            """(el, id) => el.innerText.trim() === id && !el.hasAttribute('href') &&
                          !el.hasAttribute('target') && !el.closest('form')""",
            bill.invoice_id,
        )):
            raise ListStopped("The selected invoice's view control changed.")
        link.click(timeout=5000)
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
        if link is not None:
            link.dispose()
        if opened:
            try:
                _close_invoice(dialog.filter(has=page.locator(_INVOICE)))
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
    _, visible = _view(page)
    if visible.get(document_id) != bill:
        collect_download_docs(page)
        if _RUN["bills"].get(document_id) != bill:
            raise ListStopped("The requested invoice disappeared from the monitoring history.")
    html = _invoice_html(page, bill)
    if not html:
        return False
    data = receipt_pdf.inert_pdf_bytes(page, html)
    if not _pdf_matches(data, bill):
        return False
    shared_folder.write_bytes(out_path, data)
    return True
