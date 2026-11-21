"""Read and archive the documents listed in Kaiser Permanente’s My Documents."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from html import escape
from pathlib import Path
import re
import sys
from tempfile import TemporaryDirectory
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import Error as BrowserError
from playwright.sync_api import TimeoutError as BrowserTimeout

from paperpull_core import blob_capture, capture, intake, pdf_reader, pressing, receipt_pdf, shared_folder
from paperpull_core.controls import AUTH_CONTROL_RE, SETTINGS_CONTROL_RE
from paperpull_core.words import words_for

import kaiser_medical as medical

HOST = "healthy.kaiserpermanente.org"
ALLOWED_HOSTS = {HOST}
AUTH_HOST = "identityauth.kaiserpermanente.org"
BASE = f"https://{HOST}"
REGION = r"[a-z]+(?:-[a-z]+)*"
_LIST_PATH = re.compile(rf"/{REGION}/secure/my-documents-myc")
_DIRECT_PATH = re.compile(rf"/{REGION}/secure/my-documents(?:-myc)?")
_WRAPPER_PATH = "/mychartcn/Extensibility/Redirection/FdiRedirection"
DOCUMENTS_URL = BASE + "/northern-california/secure/my-documents"
MY_DOCUMENTS_ENTRY = BASE + _WRAPPER_PATH + "?option=my-documents-myc"
# Kaiser returns to the URL the browser opened at after sign-in. Tell the
# panel this is also an account page, so it can recognize that return.
URLS = {"login": MY_DOCUMENTS_ENTRY, "documents": DOCUMENTS_URL,
        "mychart_documents": MY_DOCUMENTS_ENTRY, "medical_billing": BASE + "/secure/billing"}
LOGIN_URL_MARKERS = ("/sign-on", "/sign-in", AUTH_HOST)
RATE_LIMIT_MARKERS = ("too many requests", "rate limit", "try again later")
_VIEWER_CONTENT = "main #documentcontent"
_ROW = "._datafeed_row:visible"
_STATEMENT_DATE = re.compile(r"\bStatement\s*Date\s*:?\s*(\d{1,2}/\d{1,2}/\d{4})(?!\d)", re.I)
_ROW_ID = re.compile(r"getdoc_[0-9]+")
_TITLE = "Premium Bills"
OPEN_BILL_LIST = ("Open Kaiser Permanente's My Documents page or Medical Billing → Statements, "
                  "then leave that tab open.")
BILL_PAGE_WAIT_SECONDS = 30
_LIST_WAIT_SECONDS = 75
_BILLING_ENTRY = re.compile(rf"/(?:{REGION}/)?secure/billing/?")

_FEEDBACK_CLOSE = '.QSIWebResponsive-creative-container-fade button[aria-label="Close"]'
_EXTRA_RESULTS = re.compile(r"^(?:(?:go to )?next(?: page| results)?|load more|(?:show|view) more (?:documents|bills))$", re.I)
_RANGE = re.compile(r"^(\d+)\s*[-–]\s*(\d+)\s+of\s+(\d+)\s+items?$", re.I)
_EMPTY_RANGE = re.compile(r"^0(?:\s*[-–]\s*0\s+of\s+0)?\s+items?$", re.I)
_PAGER = ".ds-pagination:visible"
_NAV = ".ds-pagination nav.ds-pagination__nav"
_PAGE_CHANGE_MS = 15000
_DOWNLOAD_WAIT_MS = 30000
_DEFAULT_PAGE_SIZE = 10

FORBIDDEN_CONTROL_RE = re.compile(
    r"\b(?:pay|payments?|autopay|submit|confirm|transfer|delete|edit|update|manage|enroll)\b",
    re.I,
)
SAFE_DOC_CONTROL_RE = re.compile(
    r"^(?:Premium Bills|View statement(?: \(PDF\))?|Download PDF|Next results|Previous results|Close(?: this popup[.!]?)?)$", re.I,
)


def is_safe_control(label: str) -> bool:
    label = " ".join(label.split())
    return bool(SAFE_DOC_CONTROL_RE.fullmatch(label)) and not any(
        pattern.search(label) for pattern in (FORBIDDEN_CONTROL_RE, AUTH_CONTROL_RE, SETTINGS_CONTROL_RE)
    )


def press_named(page, control, selector: str, *, frame=None, statement_date="") -> None:
    labels = control.evaluate(
        "e => [e.innerText, e.getAttribute('aria-label'), e.getAttribute('title')]"
    )
    words = words_for("Kaiser Permanente", sys.modules[__name__])
    visible, accessibility, title = labels
    # Kaiser can put "Go to next page" on the Previous results anchor.
    # Pagination binds the label to its direction before it calls this guard.
    pager_title = (visible in ("Next results", "Previous results")
                   and title in ("Go to next page", "Go to previous page"))
    if (not is_safe_control(visible or accessibility or title or "")
            or (title and not pager_title and not is_safe_control(title))
            or (accessibility and not is_safe_control(accessibility)
                and not medical.matches_accessible_label(accessibility, statement_date))):
        raise pressing.Changed("check the document control", "unexpected control label",
                               ["Kaiser Permanente changed a bill control."])
    try:
        pressing.click(page, control, css=selector, what="the Kaiser document control",
                       words=words, frame=frame)
        return
    except pressing.Stop:
        if not looks_signed_out(page):
            raise
    raise SessionExpired()


_ROW_META = r"""row => {
    const visible = e => e.getClientRects().length && getComputedStyle(e).visibility === 'visible';
    const normalized = e => (e?.innerText || '').trim().replace(/\s+/g, ' ');
    const viewer = [...row.querySelectorAll('a._document_name')].filter(visible);
    const pdf = [...row.querySelectorAll('a.download-pdf-link')].filter(visible);
    const safe = e => e.getAttribute('href') === '#' && !e.hasAttribute('target') &&
        !e.hasAttribute('download') && !e.hasAttribute('onclick') && !e.closest('form');
    if (viewer.length !== 1 || !safe(viewer[0]) || pdf.length > 1) return null;
    const id = viewer[0].id;
    const title = normalized(viewer[0]);
    const date = normalized(row.querySelector('._document_date'));
    if (!/^getdoc_[0-9]+$/.test(id) || !title || !date) return null;
    if (pdf.length && (!safe(pdf[0]) || !/^Download PDF$/i.test(normalized(pdf[0])) ||
        id !== 'getdoc_' + pdf[0].getAttribute('data-docid'))) return null;
    return [id, date, title, Boolean(pdf.length)];
}"""

_READ_PAGE = r"""() => {
    const rowMeta = ROW_META;
    const visible = e => Boolean(e.getClientRects().length) &&
        getComputedStyle(e).visibility === 'visible';
    const rows = [...document.querySelectorAll('._datafeed_row')].filter(visible);
    const pagers = [...document.querySelectorAll('.ds-pagination')].filter(visible);
    if (pagers.length === 0) return {range: null, rows: rows.map(rowMeta)};
    if (pagers.length !== 1) return null;
    const pager = pagers[0];
    const container = pager.closest('.feed-container');
    if (!container || rows.some(row => !container.contains(row))) return null;
    const counts = pager.querySelectorAll('.ds-pagination__count > p');
    const nav = pager.querySelectorAll('nav.ds-pagination__nav');
    if (counts.length !== 1 || nav.length !== 1) return null;
    const enabled = direction => {
        const items = nav[0].querySelectorAll('li.-' + direction + ' > a.ds-pagination__link');
        if (items.length !== 1) return null;
        const a = items[0];
        return !a.parentElement.classList.contains('-disabled') &&
            a.getAttribute('aria-disabled') !== 'true';
    };
    return {range: counts[0].innerText.trim(), rows: rows.map(rowMeta),
        previous: enabled('prev'), next: enabled('next')};
}""".replace("ROW_META", _ROW_META)

_WAIT_FOR_PAGE = r"""({direction, first, last, total, old, rangePattern}) => {
    const read = READ_PAGE;
    const current = read();
    if (!current?.range) return false;
    const values = new RegExp(rangePattern, 'i').exec(current.range)?.slice(1).map(Number);
    if (!values || values[2] !== total) return false;
    const [start, end] = values;
    if (start < 1 || end < start || end > total) return false;
    const adjacent = direction === 'next' ? start === last + 1 : end === first - 1;
    if (!adjacent || current.rows.length !== end - start + 1 ||
        current.previous !== (start > 1) || current.next !== (end < total)) return false;
    const occupied = new Set(old);
    return current.rows.every(row => row && !occupied.has(row[0])) ? current : false;
}""".replace("READ_PAGE", _READ_PAGE)

_READ_VIEWER = r"""root => {
    const copy = root.cloneNode(true);
    copy.querySelectorAll('script,style,link,iframe,object,embed,button,input,select,textarea,form,img')
        .forEach(node => node.remove());
    return [root.innerText, copy.innerHTML];
}"""


class SessionExpired(RuntimeError):
    """Kaiser needs the account holder to sign in again."""


class ListStopped(RuntimeError):
    """The current bill list could not be read safely."""


class BillMismatch(RuntimeError):
    """A listed row did not reopen the expected bill."""


@dataclass(frozen=True)
class BillRow:
    control_id: str
    list_date: str
    title: str = _TITLE
    native_pdf: bool = False
    page_start: int = 1
    list_total: int = 0


@dataclass(frozen=True)
class DocumentsPage:
    first: int
    last: int
    total: int
    rows: tuple[BillRow, ...]


@dataclass(frozen=True)
class Bill:
    row: BillRow
    date_text: str
    fingerprint: str
    title: str = _TITLE
    account: str = ""

    @property
    def document_id(self) -> str:
        return sha256(f"kaiser:{self.row.control_id}:{self.fingerprint}".encode()).hexdigest()


@dataclass(frozen=True)
class NativeDocument:
    row: BillRow
    account: str = ""

    @property
    def title(self) -> str:
        return self.row.title

    @property
    def date_text(self) -> str:
        return self.row.list_date

    @property
    def document_id(self) -> str:
        key = f"kaiser:pdf:{self.row.control_id}:{self.date_text}"
        return sha256(key.encode()).hexdigest()


def _address(url: str):
    try:
        value = urlsplit(url or "")
    except ValueError:
        return None
    return value if value.scheme == "https" and value.netloc in {HOST, AUTH_HOST} else None


def is_safe_url(url: str) -> bool:
    address = _address(url)
    return address is not None and address.netloc == HOST


def is_session_url(url: str) -> bool:
    return _address(url) is not None


def is_history_page_url(url: str) -> bool:
    if not is_safe_url(url):
        return False
    address = urlsplit(url)
    if address.path == _WRAPPER_PATH:
        option = parse_qs(address.query).get("option")
        return option in (None, ["my-documents-myc"])
    return bool(_DIRECT_PATH.fullmatch(address.path)) or address.path == "/secure/my-documents"


def can_lead_to_bill_list(url: str) -> bool:
    """Only wait on Kaiser routes that can lead to a supported bill list."""
    return medical.is_details_url(url) or is_history_page_url(url) or (is_safe_url(url) and bool(
        _BILLING_ENTRY.fullmatch(urlsplit(url).path)
        or (urlsplit(url).path == _WRAPPER_PATH
            and parse_qs(urlsplit(url).query).get("option") == ["billing"])
    ))


def _history_frame(page):
    if not is_history_page_url(page.url):
        return None
    frames = [frame for frame in page.frames if is_safe_url(frame.url)
              and _LIST_PATH.fullmatch(urlsplit(frame.url).path)]
    return frames[0] if len(frames) == 1 else None


def is_history_tab(page) -> bool:
    return medical.is_statement_tab(page) or _history_frame(page) is not None


def list_source_url(page) -> str | None:
    if medical.is_details_url(page.url):
        return medical.SOURCE_URL
    return DOCUMENTS_URL if is_history_page_url(page.url) else None


def looks_signed_out(page) -> bool:
    for frame in getattr(page, "frames", ()) or (page,):
        address = _address(frame.url)
        if address is None:
            continue
        if address.netloc == AUTH_HOST or any(
                marker in address.path.casefold() for marker in LOGIN_URL_MARKERS):
            return True
        try:
            if frame.locator('input[type="password"]').count():
                return True
        except BrowserError:
            # Kaiser may replace the frame while returning to sign-in.
            continue
    return False


def _require_history_frame(page):
    frame = _history_frame(page)
    if frame is None:
        if looks_signed_out(page):
            raise SessionExpired()
        raise ListStopped(OPEN_BILL_LIST)
    return frame


def detect_security_challenge(page):
    if not is_session_url(page.url):
        return None
    title = page.title().casefold()
    if any(marker in title for marker in RATE_LIMIT_MARKERS):
        return "Kaiser Permanente is limiting requests. Try again later."
    if re.search(r"just a moment|security check|verify (?:that )?you are human", title):
        return "Kaiser Permanente is asking for verification in the browser."
    return None


def _iso_date(value: str, fmt: str) -> str:
    return datetime.strptime(" ".join(value.split()), fmt).date().isoformat()


def _statement_date(text: str) -> str:
    dates = {_iso_date(value, "%m/%d/%Y") for value in _STATEMENT_DATE.findall(text)}
    if len(dates) != 1:
        raise BillMismatch("Kaiser’s bill did not show a unique statement date.")
    return dates.pop()


def _parse_page(raw) -> DocumentsPage:
    if not raw:
        raise ListStopped("My Documents displayed an unrecognized pager.")
    if (not raw["rows"] and _EMPTY_RANGE.fullmatch(raw["range"] or "")
            and raw.get("previous") is False and raw.get("next") is False):
        return DocumentsPage(1, 0, 0, ())
    if not raw["rows"] or any(item is None for item in raw["rows"]):
        raise ListStopped("A My Documents row has an unrecognized document action.")
    if raw["range"] is not None:
        match = _RANGE.fullmatch(raw["range"])
        if not match:
            raise ListStopped("My Documents did not show a valid result range.")
        first, last, total = map(int, match.groups())
        if (not 1 <= first <= last <= total
                or len(raw["rows"]) != last - first + 1
                or raw["previous"] is not (first > 1)
                or raw["next"] is not (last < total)):
            raise ListStopped("My Documents did not show a consistent result range.")
    else:
        first, last, total = 1, len(raw["rows"]), len(raw["rows"])
        if total >= _DEFAULT_PAGE_SIZE:
            raise ListStopped("My Documents showed a full page without a verifiable total.")
    try:
        rows = tuple(BillRow(key, _iso_date(date, "%b %d, %Y"), title, native, first, total)
                     for key, date, title, native in raw["rows"])
    except ValueError:
        raise ListStopped("A My Documents row has an unreadable list date.") from None
    if len({row.control_id for row in rows}) != len(rows):
        raise ListStopped("My Documents contains duplicate row identifiers.")
    if any(not row.native_pdf and row.title != _TITLE for row in rows):
        raise ListStopped("A My Documents item has an unrecognized viewer.")
    return DocumentsPage(first, last, total, rows)


def _visible_page(frame) -> DocumentsPage:
    first_row = frame.locator(_ROW).first
    if not first_row.is_visible():
        print("Waiting for Kaiser Permanente's My Documents list to load.", flush=True)
    empty = frame.locator(_PAGER + " .ds-pagination__count > p").filter(has_text=_EMPTY_RANGE)
    try:
        first_row.or_(empty).first.wait_for(timeout=_LIST_WAIT_SECONDS * 1000)
    except BrowserTimeout:
        if looks_signed_out(frame.page):
            raise SessionExpired() from None
        raise ListStopped("Kaiser did not finish showing the My Documents list.") from None
    # A full-sized list may appear just before its pager mounts.
    if frame.locator(_ROW).count() >= _DEFAULT_PAGE_SIZE:
        frame.locator(_PAGER).first.wait_for(timeout=_PAGE_CHANGE_MS)
    if not frame.locator(_PAGER).count():
        for role in ("button", "link"):
            if any(item.is_visible() and item.is_enabled()
                   for item in frame.get_by_role(role, name=_EXTRA_RESULTS).all()):
                raise ListStopped("My Documents shows more rows than PaperPull can read.")
    return _parse_page(frame.evaluate(_READ_PAGE))


def _turn_page(frame, current: DocumentsPage, direction: str) -> DocumentsPage:
    if (direction == "next" and current.last == current.total
            or direction == "prev" and current.first == 1):
        raise ListStopped("My Documents reached the edge of the list unexpectedly.")
    _dismiss_feedback(frame.page, frame)
    selector = f"{_NAV} li.-{direction} > a.ds-pagination__link"
    controls = frame.locator(selector + ":visible").element_handles()
    label = "Next results" if direction == "next" else "Previous results"
    if len(controls) != 1 or not controls[0].evaluate(r"""(e, label) =>
            e.isConnected && e.innerText.trim().replace(/\s+/g, ' ') === label &&
            e.getAttribute('href') === '#' && e.getAttribute('aria-disabled') !== 'true' &&
            !e.parentElement.classList.contains('-disabled') && !e.closest('form') &&
            !e.hasAttribute('target') && !e.hasAttribute('download') && !e.hasAttribute('onclick')
        """, label):
        raise ListStopped("The My Documents paging control could not be verified.")
    press_named(frame.page, controls[0], selector, frame=frame)
    try:
        changed = frame.wait_for_function(_WAIT_FOR_PAGE, arg={
            "direction": direction, "first": current.first, "last": current.last,
            "total": current.total, "old": [row.control_id for row in current.rows],
            "rangePattern": _RANGE.pattern,
        }, timeout=_PAGE_CHANGE_MS)
        try:
            return _parse_page(changed.json_value())
        finally:
            changed.dispose()
    except BrowserError:
        if looks_signed_out(frame.page):
            raise SessionExpired() from None
        raise ListStopped("Kaiser did not load the adjacent My Documents page.") from None


def _seek_page(frame, first: int, total: int | None = None) -> DocumentsPage:
    current = _visible_page(frame)
    if total is not None and current.total != total:
        raise ListStopped("The My Documents result count changed during the run.")
    while current.first != first:
        direction = "next" if current.first < first else "prev"
        current = _turn_page(frame, current, direction)
        if (direction == "next" and current.first > first
                or direction == "prev" and current.first < first):
            raise ListStopped("The My Documents page boundaries changed during the run.")
    return current


def bill_list_ready(page) -> bool:
    if medical.is_statement_tab(page):
        try:
            medical.collect_download_docs(page)
            return True
        except (BrowserError, medical.MedicalListError):
            return False
    frame = _history_frame(page)
    if frame is None:
        return False
    try:
        _visible_page(frame)
        return True
    except (BrowserError, ListStopped, SessionExpired):
        return False


def _dismiss_feedback(page, frame):
    close = frame.locator(_FEEDBACK_CLOSE + ":visible")
    if close.count() == 1 and close.evaluate("e => !e.form && e.className.includes('close-btn')"):
        press_named(page, close, _FEEDBACK_CLOSE, frame=frame)


def _read_bill(page, frame, row: BillRow) -> tuple[Bill, str]:
    if _history_frame(page) is not frame or row not in _seek_page(frame, row.page_start, row.list_total).rows:
        raise ListStopped("The selected Premium Bills row is no longer on My Documents.")
    list_path = urlsplit(frame.url).path
    view_path = list_path + "/viewer"
    _dismiss_feedback(frame.page, frame)
    controls = frame.locator(f"a._document_name#{row.control_id}").element_handles()
    if len(controls) != 1:
        raise BillMismatch("The Premium Bills control could not be identified uniquely.")
    control = controls[0]
    current_date = control.evaluate(r"""e => {
        if (!e.isConnected || e.innerText.trim() !== 'Premium Bills' ||
            e.getAttribute('href') !== '#' || e.hasAttribute('target') ||
            e.hasAttribute('download') || e.closest('form')) return null;
        return e.closest('._datafeed_row')?.querySelector('._document_date')?.innerText.trim();
    }""")
    if not current_date or _iso_date(current_date, "%b %d, %Y") != row.list_date:
        raise BillMismatch("The Premium Bills control changed before it could be opened.")

    def expected_viewer(navigated):
        return (navigated is frame and is_safe_url(navigated.url)
                and urlsplit(navigated.url).path == view_path)

    try:
        with page.expect_event("framenavigated", predicate=expected_viewer, timeout=12000):
            press_named(page, control, f"a._document_name#{row.control_id}", frame=frame)
        frame.wait_for_function(r"""selector => /\bStatement\s*Date\s*:?\s*\d{1,2}\/\d{1,2}\/\d{4}/i
                               .test(document.querySelector(selector)?.innerText || '')""",
                                arg=_VIEWER_CONTENT, timeout=12000)
        if not expected_viewer(frame):
            raise BillMismatch("Kaiser left the selected bill viewer before it answered.")
        text, html = frame.locator(_VIEWER_CONTENT).evaluate(_READ_VIEWER)
        date = _statement_date(text)
        if not html or not re.search(r"\bpremium\b", text, re.I):
            raise BillMismatch("The viewer did not show a premium bill.")
        # The list date can differ from the printed statement date. Bind the
        # viewer to the selected row and use the printed date for filing.
        # Persist only a digest of the bill text.
        fingerprint = sha256(" ".join(text.split()).encode()).hexdigest()
        return Bill(row, date, fingerprint), html
    finally:
        if expected_viewer(frame):
            frame.goto(BASE + list_path, wait_until="domcontentloaded", timeout=12000)


def collect_download_docs(page) -> list[Bill | NativeDocument | medical.MedicalBill]:
    if medical.is_details_url(page.url):
        try:
            return medical.collect_download_docs(page)
        except medical.MedicalListError as error:
            raise ListStopped(str(error)) from None
        except BrowserError:
            if looks_signed_out(page):
                raise SessionExpired() from None
            raise ListStopped(OPEN_BILL_LIST) from None
    frame = _require_history_frame(page)
    try:
        current = _seek_page(frame, 1)
        total = current.total
        if not total:
            return []
        rows = []
        seen = set()
        while True:
            ids = {row.control_id for row in current.rows}
            if seen.intersection(ids):
                raise ListStopped("My Documents repeated rows on another page.")
            seen.update(ids)
            rows.extend(current.rows)
            print(f"Read My Documents rows {current.first}–{current.last} of {total}.", flush=True)
            if current.last == total:
                break
            current = _turn_page(frame, current, "next")
        if len(seen) != total:
            raise ListStopped("The My Documents row count did not match the portal total.")
        bills = [NativeDocument(row) if row.native_pdf else _read_bill(page, frame, row)[0]
                 for row in rows]
        _seek_page(frame, 1, total)
        return bills
    except (BrowserError, BillMismatch, ValueError) as error:
        if looks_signed_out(page):
            raise SessionExpired() from None
        if isinstance(error, BrowserTimeout) and _history_frame(page) is not None:
            raise
        raise ListStopped("Kaiser did not finish reading My Documents. " + OPEN_BILL_LIST) from None


def _validated_pdf(page, bill: Bill, content_html: str) -> bytes | None:
    html = f"""<!doctype html><html lang="en"><meta charset="utf-8">
    <title>{escape(bill.title)}</title><body>{content_html}</body></html>"""
    data = receipt_pdf.inert_pdf_bytes(page, html)
    pdf = pdf_reader.read(data, text_pages=pdf_reader.ALL)
    if not pdf.opened or not pdf.pages or pdf.text_error:
        return None
    text = "\n".join(pdf.texts)
    try:
        date = _statement_date(text)
    except (BillMismatch, ValueError):
        return None
    return data if date == bill.date_text and re.search(r"\bpremium\b", text, re.I) else None


def bill_source_url(bill: Bill | NativeDocument | medical.MedicalBill) -> str:
    return medical.SOURCE_URL if isinstance(bill, medical.MedicalBill) else DOCUMENTS_URL


def _native_pdf(page, frame, row: BillRow, output_folder: Path) -> bytes | None:
    if _history_frame(page) is not frame or row not in _seek_page(frame, row.page_start, row.list_total).rows:
        raise ListStopped("The selected item is no longer on My Documents.")
    _dismiss_feedback(frame.page, frame)
    doc_id = row.control_id.removeprefix("getdoc_")
    selector = f'a.download-pdf-link[data-docid="{doc_id}"]'
    controls = frame.locator(selector + ":visible").element_handles()
    if len(controls) != 1:
        return None
    control = controls[0]
    observed = control.evaluate(r"""e => {
        const rowMeta = ROW_META;
        const row = e.closest('._datafeed_row');
        return e.isConnected && row ? rowMeta(row) : null;
    }""".replace("ROW_META", _ROW_META))
    if not observed:
        return None
    key, date, title, native = observed
    if BillRow(key, _iso_date(date, "%b %d, %Y"), title, native, row.page_start, row.list_total) != row:
        return None
    if shared_folder.on_server() and shared_folder.leads_out(output_folder):
        return None
    # Isolate the browser's disposable copy from the archive and from earlier
    # downloads. Only bytes tied to this press's own blob link are archived.
    with TemporaryDirectory(prefix=".kaiser-download-", dir=output_folder, ignore_cleanup_errors=True) as scratch:
        if not capture.set_download_dir(page, scratch):
            raise ListStopped("The browser could not prepare a private Kaiser download folder.")
        return _capture_native_pdf(page, frame, control, selector)


def _capture_native_pdf(page, frame, control, selector: str) -> bytes | None:
    if not blob_capture.arm(frame):
        return None
    downloads = []

    def record_download(download):
        downloads.append(download)

    page.on("download", record_download)
    try:
        press_named(page, control, selector, frame=frame)
        observed = frame.wait_for_function(
            f"() => ({blob_capture.SAVED_JS})()?.length > 0", timeout=_DOWNLOAD_WAIT_MS)
        observed.dispose()
        links = blob_capture.saved_links(frame) or []
        if (len(links) != 1 or not links[0].startswith(f"blob:{BASE}/")
                or len(downloads) > 1 or (downloads and downloads[0].url != links[0])):
            raise ListStopped("Kaiser’s PDF could not be tied to the selected My Documents row.")
        payload = blob_capture.take(frame, urls=links)
        if not payload:
            return None
        data, _ = payload
        pdf = pdf_reader.read(data)
        return data if pdf.opened and pdf.pages else None
    except BrowserError:
        if looks_signed_out(page):
            raise SessionExpired() from None
        # A late PDF from this action could otherwise be mistaken for the next row.
        raise ListStopped("Kaiser did not finish the selected PDF download. Run Continue to try it again.") from None
    finally:
        page.remove_listener("download", record_download)
        if len(downloads) == 1 and downloads[0].url in (blob_capture.saved_links(frame) or []):
            intake.discard(downloads[0], page)
        blob_capture.arm(frame)

def download_bill(page, bill: Bill | NativeDocument | medical.MedicalBill, out_path: Path,
                  *, existing_pdfs: dict[str, Path] | None = None) -> Path | None:
    if isinstance(bill, medical.MedicalBill):
        try:
            return out_path if medical.download_bill(page, bill, out_path, press=press_named) else None
        except medical.MedicalListError as error:
            raise ListStopped(str(error)) from None
        except BrowserError:
            if looks_signed_out(page):
                raise SessionExpired() from None
            collect_download_docs(page)
            return None
    frame = _require_history_frame(page)
    try:
        if isinstance(bill, NativeDocument):
            data = _native_pdf(page, frame, bill.row, out_path.parent)
        else:
            selected, html = _read_bill(page, frame, bill.row)
            if selected != bill:
                return None
            data = _validated_pdf(page, bill, html)
        if not data:
            return None
        if isinstance(bill, NativeDocument) and existing_pdfs:
            fingerprint = sha256(data).hexdigest()
            existing = existing_pdfs.get(fingerprint)
            if existing is not None and intake.plain_sha256(existing) == fingerprint:
                return existing
        shared_folder.write_whole(out_path, data)
        return out_path
    except (BillMismatch, ValueError):
        return None
    except BrowserError:
        if looks_signed_out(page):
            raise SessionExpired() from None
        current = _require_history_frame(page)
        try:
            _visible_page(current)
        except BrowserError:
            raise ListStopped(OPEN_BILL_LIST) from None
        return None
