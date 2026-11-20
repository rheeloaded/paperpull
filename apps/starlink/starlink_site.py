"""Read invoices and their PDFs from Starlink's signed-in billing page."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from pathlib import Path
import re
from urllib.parse import urlsplit

from playwright.sync_api import Error as BrowserError

from paperpull_core import intake, pdf_reader, refused, shared_folder
from paperpull_core.controls import AUTH_CONTROL_RE, SETTINGS_CONTROL_RE, control_label

HOSTS = {"starlink.com", "www.starlink.com"}
ALLOWED_HOSTS = HOSTS
BASE = "https://starlink.com"
DOCUMENTS_URL = BASE + "/account/billing"
URLS = {"home": BASE + "/account", "login": DOCUMENTS_URL, "documents": DOCUMENTS_URL}
LOGIN_URL_MARKERS = ("/auth/", "/login", "/sign-in")
RATE_LIMIT_MARKERS = re.compile(r"too many requests|rate limit", re.I)
FORBIDDEN_CONTROL_RE = re.compile(r"\b(?:pay|payment|submit|confirm|save|edit|cancel|delete|order)\b", re.I)
SAFE_DOC_CONTROL_RE = re.compile(r"^(?:Invoice PDF|Download (?:Invoice|PDF)|Go to (?:next|previous) page)$", re.I)
FALLBACK = {"doc_row": ".MuiDataGrid-row"}

_INVOICE = re.compile(r"INV-[A-Z0-9]+(?:-[A-Z0-9]+)*", re.I | re.ASCII)
_RANGE = re.compile(r"([0-9]+)\s*[-–]\s*([0-9]+)(?:\s+of\s+([0-9]+))?")
_PATH = re.compile(r"/(?:[a-z]{2}(?:-[a-z]{2})?/)?account/billing/?", re.I)
_MAX_PAGES = 100
_REFERENCE = '[data-field="payableEntityReferenceId"]'
_PAGER = ".MuiTablePagination-root"
_PREVIOUS = "Go to previous page"
_NEXT = "Go to next page"

# The Payments grid also says Invoice Number, but has different field names.
# Read both the rows and the footer from the same uniquely matched grid.
_READ_PAGE = r"""() => {
    const visible = el => el && el.getClientRects().length > 0;
    const roots = [...document.querySelectorAll('.MuiDataGrid-root')].filter(root =>
        visible(root) && root.querySelector('[role=columnheader][data-field=payableEntityReferenceId]')
        && root.querySelector('[role=columnheader][data-field=payableEntityCreatedDate]'));
    if (roots.length !== 1) return null;
    const root = roots[0];
    if ([...root.querySelectorAll('[role=progressbar], .MuiDataGrid-loadingOverlay')].some(visible)) return null;
    const footer = root.querySelector('.MuiTablePagination-root');
    if (!visible(footer)) return null;
    const range = footer.querySelector('.MuiTablePagination-displayedRows')?.innerText.trim();
    const enabled = label => {
        const buttons = [...footer.querySelectorAll('button[type=button]')]
            .filter(e => visible(e) && e.getAttribute('aria-label') === label && !e.form
                && !e.hasAttribute('formaction'));
        if (buttons.length !== 1) return null;
        return !buttons[0].disabled && buttons[0].getAttribute('aria-disabled') !== 'true';
    };
    const rows = [...root.querySelectorAll('.MuiDataGrid-row[role=row]')].filter(visible).map(row => [
        row.querySelector('[role=gridcell][data-field=payableEntityReferenceId]')?.innerText.trim(),
        row.querySelector('[role=gridcell][data-field=payableEntityCreatedDate]')?.innerText.trim()
    ]);
    return {range, rows, previous: enabled('Go to previous page'), next: enabled('Go to next page')};
}"""

_WAIT_PAGE = r"""before => {
    const read = READ_PAGE_PLACEHOLDER;
    const current = read();
    if (!current || current.next === null || current.previous === null) return false;
    const bounds = /^(\d+)\s*[-–]\s*(\d+)(?:\s+of\s+\d+)?$/.exec(current.range || '');
    if (!bounds) return false;
    const first = Number(bounds[1]);
    const last = Number(bounds[2]);
    if (current.rows.length !== (first === 0 ? 0 : last - first + 1)
        || current.rows.some(([id,date]) => !id || !date)) return false;
    if (!before) return current;
    const previousIds = new Set(before.ids);
    return current.range !== before.range && current.rows.length > 0
        && current.rows.every(([id]) => !previousIds.has(id)) ? current : false;
}""".replace("READ_PAGE_PLACEHOLDER", _READ_PAGE)


class SessionExpired(RuntimeError):
    """Starlink needs the account holder to sign in again."""


class ListStopped(RuntimeError):
    """The current invoice list could not be read safely."""


@dataclass(frozen=True)
class RawDoc:
    title: str
    date_text: str
    account: str
    document_id: str


@dataclass(frozen=True)
class Bill:
    number: str
    date: str

    @property
    def key(self) -> str:
        return sha256(f"starlink:{self.number.upper()}".encode()).hexdigest()

    @property
    def record(self) -> RawDoc:
        return RawDoc("Starlink Invoice", self.date, "", self.key)


@dataclass(frozen=True)
class InvoicePage:
    first: int
    last: int
    total: int | None
    previous: bool
    next: bool
    label: str
    bills: tuple[Bill, ...]


def is_safe_url(url: str) -> bool:
    try:
        address = urlsplit(url or "")
    except ValueError:
        return False
    return address.scheme == "https" and address.netloc in HOSTS


def is_session_url(url: str) -> bool:
    return is_safe_url(url)


def is_history_page_url(url: str) -> bool:
    return is_safe_url(url) and bool(_PATH.fullmatch(urlsplit(url).path))


def looks_signed_out(page) -> bool:
    if not is_session_url(page.url):
        return False
    path = urlsplit(page.url).path.rstrip("/") + "/"
    return any(marker.rstrip("/") + "/" in path for marker in LOGIN_URL_MARKERS) or bool(
        page.locator('input[type="password"]:visible').count()
    )


def detect_security_challenge(page):
    if not is_session_url(page.url):
        return None
    title = page.title()
    if RATE_LIMIT_MARKERS.search(title):
        return "Starlink is limiting requests. Try again later."
    if re.search(r"just a moment|security check|verify (?:that )?you are human", title, re.I):
        return "Starlink is asking for verification in the browser."
    return None


def is_safe_control(label: str) -> bool:
    return bool(SAFE_DOC_CONTROL_RE.fullmatch(label.strip())) and not any(
        rule.search(label) for rule in (FORBIDDEN_CONTROL_RE, AUTH_CONTROL_RE, SETTINGS_CONTROL_RE)
    )


def _date(text: str) -> str:
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%B %d, %Y", "%b %d, %Y", "%A, %B %d, %Y", "%a, %b %d, %Y"):
        try:
            return datetime.strptime(text.strip(), fmt).date().isoformat()
        except ValueError:
            pass
    return ""


def _number_ok(value: str) -> bool:
    return 8 <= len(value) <= 64 and bool(_INVOICE.fullmatch(value))


def _parse_view(raw) -> InvoicePage:
    match = _RANGE.fullmatch(raw.get("range") or "") if raw else None
    if not match or raw["next"] is None or raw["previous"] is None:
        raise ListStopped("Starlink's Invoices table or pagination was unavailable.")
    first, last = int(match[1]), int(match[2])
    total = int(match[3]) if match[3] is not None else None
    if first == 0:
        if last or raw["rows"] or total not in (None, 0) or raw["previous"] or raw["next"]:
            raise ListStopped("Starlink's empty invoice list could not be verified.")
    elif (last < first or len(raw["rows"]) != last - first + 1
          or raw["previous"] != (first > 1)
          or (total is not None and (last > total or raw["next"] != (last < total)))):
        raise ListStopped("Starlink's invoice rows disagree with its pagination.")
    bills = []
    for number, displayed_date in raw["rows"]:
        date = _date(displayed_date or "")
        if not date or not _number_ok(number or ""):
            raise ListStopped("A Starlink invoice number or issue date could not be read.")
        bills.append(Bill(number, date))
    if len({bill.key for bill in bills}) != len(bills):
        raise ListStopped("Starlink repeated an invoice in its history.")
    return InvoicePage(first, last, total, raw["previous"], raw["next"], raw["range"], tuple(bills))


def _require_billing(page) -> None:
    if looks_signed_out(page):
        raise SessionExpired()
    if not is_history_page_url(page.url):
        raise ListStopped("Open Billing → Invoices in the Starlink sign-in window.")


def _open_billing(page) -> None:
    if looks_signed_out(page):
        raise SessionExpired()
    if not is_safe_url(page.url):
        raise ListStopped("Open Billing → Invoices in the Starlink sign-in window.")
    if not is_history_page_url(page.url):
        try:
            page.goto(DOCUMENTS_URL, wait_until="domcontentloaded", timeout=18000)
        except BrowserError:
            raise ListStopped("Starlink's Billing page did not open.") from None
    _require_billing(page)


def _view(page, before: InvoicePage | None = None) -> InvoicePage:
    _require_billing(page)
    prior = {"range": before.label, "ids": [bill.number for bill in before.bills]} if before else None
    try:
        handle = page.wait_for_function(_WAIT_PAGE, arg=prior, timeout=12000)
        try:
            raw = handle.json_value()
        finally:
            handle.dispose()
    except BrowserError:
        _require_billing(page)
        raise ListStopped("Starlink did not show a complete invoice page.") from None
    _require_billing(page)
    return _parse_view(raw)


def _turn_page(page, current: InvoicePage, *, forward: bool) -> InvoicePage:
    _require_billing(page)
    label = _NEXT if forward else _PREVIOUS
    columns = page.locator('[role="columnheader"]' + _REFERENCE)
    root = page.locator('.MuiDataGrid-root:visible').filter(has=columns)
    buttons = root.locator(f'{_PAGER} button[type="button"][aria-label="{label}"]:visible')
    try:
        if root.count() != 1 or buttons.count() != 1:
            raise ListStopped("The Starlink invoice pager changed.")
        button = buttons.element_handle(timeout=3000)
        if button is None:
            raise ListStopped("The Starlink invoice pager changed.")
        try:
            observed = control_label(button)
            if observed != label or not is_safe_control(observed):
                raise ListStopped("The Starlink invoice pager changed.")
            if not button.evaluate(r'''(e, name) => e.matches('button[type=button]') &&
                e.getAttribute('aria-label') === name && !e.form && !e.hasAttribute('formaction') &&
                !e.disabled && e.getAttribute('aria-disabled') !== 'true' ''', label):
                raise ListStopped("The Starlink invoice pager changed.")
            button.click(timeout=5000)
        finally:
            button.dispose()
    except BrowserError:
        _require_billing(page)
        raise ListStopped("The Starlink invoice pager did not respond.") from None
    updated = _view(page, current)
    adjacent = updated.first == current.last + 1 if forward else updated.last == current.first - 1
    if not adjacent or updated.total != current.total:
        raise ListStopped("Starlink's invoice pagination skipped or changed pages.")
    return updated


def _first(page, current: InvoicePage) -> InvoicePage:
    for _ in range(_MAX_PAGES):
        if not current.previous:
            return current
        current = _turn_page(page, current, forward=False)
    raise ListStopped("Starlink's invoice history exceeded the supported number of pages.")


_RUN: dict = {}


def collect_download_docs(page) -> list[RawDoc]:
    _RUN.clear()
    _open_billing(page)
    current = first = _first(page, _view(page))
    bills = {}
    for _ in range(_MAX_PAGES):
        for bill in current.bills:
            if bill.key in bills:
                raise ListStopped("Starlink repeated an invoice across pages.")
            bills[bill.key] = bill
        if not current.next:
            if _first(page, current) != first:
                raise ListStopped("Starlink's first invoice page changed during discovery.")
            _RUN.update(page=page, first=first, bills=bills)
            return [bill.record for bill in bills.values()]
        current = _turn_page(page, current, forward=True)
    raise ListStopped("Starlink's invoice history exceeded the supported number of pages.")


def bill_list_ready(page) -> bool:
    try:
        _open_billing(page)
        _view(page)
    except (SessionExpired, ListStopped):
        return False
    return True


def _pdf_matches(data: bytes, bill: Bill) -> bool:
    if not data.startswith(b"%PDF-"):
        return False
    try:
        pages = pdf_reader.page_texts(data, pages=1)
    except Exception:
        return False
    if not pages:
        return False
    lines = [" ".join(line.split()) for line in pages[0].splitlines() if line.strip()]
    numbers = [value for label, value in zip(lines, lines[1:]) if label.casefold() == "invoice"]
    dates = [line.split(":", 1)[1].strip() for line in lines if line.casefold().startswith("invoice date:")]
    return numbers == [bill.number] and len(dates) == 1 and _date(dates[0]) == bill.date


def _fetch_pdf(page, bill: Bill) -> bytes:
    _require_billing(page)
    if not _number_ok(bill.number):
        raise ListStopped("The selected Starlink invoice number could not be verified.")
    host = urlsplit(page.url).netloc
    # Exact same-origin GET exposed by Starlink's Invoice PDF menu link.
    url = f"https://{host}/api/webagg/v1/public/invoice/{bill.number}/download"
    response = None
    try:
        response = page.request.get(url, max_redirects=0, timeout=20000)
        status = response.status
        mime = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if status in (301, 302, 303, 307, 308, 401, 403) or (
            status == 200 and mime in ("text/html", "application/xhtml+xml")
        ):
            raise SessionExpired()
        if status == 429:
            raise ListStopped("Starlink is limiting invoice downloads. Try again later.")
        if status != 200 or mime != "application/pdf":
            return b""
        return intake.body(response)
    except (BrowserError, intake.TooLarge):
        return b""
    finally:
        if response is not None:
            response.dispose()


def _refresh_invoices(page) -> list[RawDoc]:
    _require_billing(page)
    page.reload(wait_until="domcontentloaded", timeout=18000)
    return collect_download_docs(page)


def download_bill(page, date: str, out_path: Path, *, document_id: str) -> bool:
    if _RUN.get("page") is not page or _view(page) != _RUN["first"]:
        collect_download_docs(page)
    bill = _RUN["bills"].get(document_id)
    if not bill or bill.date != date:
        raise ListStopped("The selected invoice no longer matches Starlink's history.")
    try:
        data = _fetch_pdf(page, bill)
    except SessionExpired:
        # A refusal for one PDF can be specific to that invoice. Only the
        # refreshed history can tell if the whole session or list is gone.
        refused.list_again(lambda: _refresh_invoices(page), SessionExpired, ListStopped)
        return False
    if not _pdf_matches(data, bill):
        return False
    shared_folder.write_bytes(out_path, data)
    return True
