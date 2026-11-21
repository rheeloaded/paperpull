"""Read Kaiser Permanente's premium and medical billing documents."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from html import escape
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

from playwright.sync_api import Error as BrowserError

from paperpull_core import pressing, receipt_pdf, pdf_reader, shared_folder
from paperpull_core.controls import AUTH_CONTROL_RE, SETTINGS_CONTROL_RE
from paperpull_core.words import words_for

import kaiser_medical as medical

HOST = "healthy.kaiserpermanente.org"
ALLOWED_HOSTS = {HOST}
LOGIN_URL_MARKERS = ("/sign-on", "/sign-in")
RATE_LIMIT_MARKERS = ("too many requests", "rate limit", "try again later")
AUTH_HOST = "identityauth.kaiserpermanente.org"
BASE = f"https://{HOST}"
REGION = r"[a-z]+(?:-[a-z]+)*"
_LIST_PATH = re.compile(rf"/{REGION}/secure/my-documents-myc")
_DIRECT_PATH = re.compile(rf"/{REGION}/secure/my-documents(?:-myc)?")
_WRAPPER_PATH = "/mychartcn/Extensibility/Redirection/FdiRedirection"
DOCUMENTS_URL = BASE + "/northern-california/secure/my-documents"
URLS = {"login": BASE + "/secure/billing", "documents": DOCUMENTS_URL}
_VIEWER_CONTENT = "main #documentcontent"
_ROW = "._datafeed_row:visible"
_STATEMENT_DATE = re.compile(r"\bStatement\s*Date\s*:?\s*(\d{1,2}/\d{1,2}/\d{4})(?!\d)", re.I)
_ROW_ID = re.compile(r"getdoc_[0-9]+")
_TITLE = "Premium Bills"
_OPEN_LIST = ("Open View past bills → My Documents or Medical Billing → Statements, "
              "then leave that tab open.")
_FEEDBACK_CLOSE = '.QSIWebResponsive-creative-container-fade:visible button[aria-label="Close"]:visible'
_NEXT = re.compile(r"^(?:next(?: page)?|load more|(?:show|view) more (?:documents|bills))$", re.I)
FORBIDDEN_CONTROL_RE = re.compile(
    r"\b(?:pay|payments?|autopay|submit|confirm|transfer|delete|edit|update|manage|enroll)\b",
    re.I,
)
SAFE_DOC_CONTROL_RE = re.compile(
    r"^(?:Premium Bills|View statement(?: \(PDF\))?|Close(?: this popup[.!]?)?)$", re.I,
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
    if (not is_safe_control(visible or accessibility or title or "") or (title and not is_safe_control(title))
            or (accessibility and not is_safe_control(accessibility)
                and not medical.matches_accessible_label(accessibility, statement_date))):
        raise pressing.Changed("check the document control", "unexpected control label",
                               ["Kaiser Permanente changed a bill control."])
    pressing.click(page, control, css=selector, what="the Kaiser bill control",
                   words=words, frame=frame)


_READ_ROWS = r"""rows => rows.flatMap(row => {
    const title = row.querySelector('.feed-title');
    const control = row.querySelector('a._document_name');
    if (title?.innerText.trim() !== 'Premium Bills' &&
        control?.innerText.trim() !== 'Premium Bills') return [];
    const date = row.querySelector('._document_date')?.innerText.trim();
    const safe = control && control.innerText.trim() === 'Premium Bills' &&
        control.getAttribute('href') === '#' && !control.hasAttribute('target') &&
        !control.hasAttribute('download') && !control.closest('form');
    return [[safe ? control.id : null, date]];
})"""

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
    path = urlsplit(url).path
    return path == _WRAPPER_PATH or bool(_DIRECT_PATH.fullmatch(path))


def _history_frame(page):
    if not is_history_page_url(page.url):
        return None
    frames = [frame for frame in page.frames if is_safe_url(frame.url)
              and _LIST_PATH.fullmatch(urlsplit(frame.url).path)]
    return frames[0] if len(frames) == 1 else None


def is_history_tab(page) -> bool:
    return medical.is_statement_tab(page) or _history_frame(page) is not None


def looks_signed_out(page) -> bool:
    for frame in getattr(page, "frames", ()) or (page,):
        address = _address(frame.url)
        if address is None:
            continue
        if address.netloc == AUTH_HOST or any(
                marker in address.path.casefold() for marker in LOGIN_URL_MARKERS):
            return True
        if frame.locator('input[type="password"]').count():
            return True
    return False


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


def _visible_rows(frame) -> tuple[BillRow, ...]:
    frame.locator(_ROW).first.wait_for(timeout=12000)
    for role in ("button", "link"):
        if any(item.is_visible() and item.is_enabled()
               for item in frame.get_by_role(role, name=_NEXT).all()):
            # A control that loads further rows must be understood before marking
            # the visible portion of the feed as the complete list.
            raise ListStopped("My Documents shows more rows than PaperPull can read.")
    raw = frame.locator(_ROW).evaluate_all(_READ_ROWS)
    try:
        rows = tuple(BillRow(key, _iso_date(date, "%b %d, %Y"))
                     for key, date in raw
                     if _ROW_ID.fullmatch(key or "") and isinstance(date, str))
    except ValueError:
        raise ListStopped("A Premium Bills row has an unreadable list date.") from None
    if len(rows) != len(raw) or len({row.control_id for row in rows}) != len(rows):
        raise ListStopped("A Premium Bills row could not be identified uniquely.")
    return rows


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
        return bool(_visible_rows(frame))
    except (BrowserError, ListStopped):
        return False


def _dismiss_feedback(page, frame):
    close = frame.locator(_FEEDBACK_CLOSE)
    if close.count() == 1 and close.evaluate("e => !e.form && e.className.includes('close-btn')"):
        press_named(page, close, '.QSIWebResponsive-creative-container-fade button[aria-label="Close"]',
                    frame=frame)


def _read_bill(page, frame, row: BillRow) -> tuple[Bill, str]:
    if _history_frame(page) is not frame or row not in _visible_rows(frame):
        raise ListStopped("The selected Premium Bills row is no longer on My Documents.")
    list_path = urlsplit(frame.url).path
    view_path = list_path + "/viewer"
    _dismiss_feedback(page, frame)
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


def collect_download_docs(page) -> list[Bill | medical.MedicalBill]:
    if medical.is_details_url(page.url):
        try:
            return medical.collect_download_docs(page)
        except medical.MedicalListError as error:
            raise ListStopped(str(error)) from None
        except BrowserError:
            if looks_signed_out(page):
                raise SessionExpired() from None
            raise ListStopped(_OPEN_LIST) from None
    frame = _history_frame(page)
    if frame is None:
        raise ListStopped(_OPEN_LIST)
    try:
        rows = _visible_rows(frame)
        bills = [_read_bill(page, frame, row)[0] for row in rows]
        if set(rows) != set(_visible_rows(frame)):
            raise ListStopped("The feed changed while it was being read. Try Discover again.")
        return bills
    except (BrowserError, BillMismatch, ValueError):
        if looks_signed_out(page):
            raise SessionExpired() from None
        raise ListStopped("Kaiser did not open a listed Premium Bills document. " + _OPEN_LIST) from None


def _validated_pdf(page, bill: Bill, content_html: str) -> bytes | None:
    html = f"""<!doctype html><html lang="en"><meta charset="utf-8">
    <title>{escape(bill.title)}</title><body>{content_html}</body></html>"""
    data = receipt_pdf.inert_pdf_bytes(page, html)
    read = pdf_reader.read(data, text_pages=pdf_reader.ALL)
    if not read.opened or not read.pages or read.text_error:
        return None
    text = "\n".join(read.texts)
    try:
        date = _statement_date(text)
    except (BillMismatch, ValueError):
        return None
    return data if date == bill.date_text and re.search(r"\bpremium\b", text, re.I) else None


def bill_source_url(bill: Bill | medical.MedicalBill) -> str:
    return medical.SOURCE_URL if isinstance(bill, medical.MedicalBill) else DOCUMENTS_URL


def download_bill(page, bill: Bill | medical.MedicalBill, out_path: Path) -> bool:
    if isinstance(bill, medical.MedicalBill):
        try:
            return medical.download_bill(page, bill, out_path, press=press_named)
        except medical.MedicalListError as error:
            raise ListStopped(str(error)) from None
        except BrowserError:
            if looks_signed_out(page):
                raise SessionExpired() from None
            collect_download_docs(page)
            return False
    frame = _history_frame(page)
    if frame is None:
        raise ListStopped(_OPEN_LIST)
    try:
        selected, html = _read_bill(page, frame, bill.row)
        if selected != bill:
            return False
        data = _validated_pdf(page, bill, html)
        if not data:
            return False
        shared_folder.write_whole(out_path, data)
        return True
    except (BillMismatch, ValueError):
        return False
    except BrowserError:
        if looks_signed_out(page):
            raise SessionExpired() from None
        current = _history_frame(page)
        if current is None:
            raise ListStopped(_OPEN_LIST) from None
        try:
            _visible_rows(current)
        except BrowserError:
            raise ListStopped(_OPEN_LIST) from None
        return False
