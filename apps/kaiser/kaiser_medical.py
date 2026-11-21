"""Read original medical statements from Kaiser’s billing details."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from time import monotonic
import re
from urllib.parse import parse_qsl, urlsplit

from playwright.sync_api import Error as BrowserError

from paperpull_core import capture, intake, pdf_reader, shared_folder

HOST = "healthy.kaiserpermanente.org"
DETAILS_PATH = "/mychartcn/Billing/Details"
BASE = "https://" + HOST
SOURCE_URL = BASE + "/mychartcn/Billing/Summary"
TITLE = "Medical Bill"

_MONTH = (r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
          r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)")
_LONG_DATE = rf"{_MONTH}\s+\d{{1,2}},?\s+\d{{4}}"
_NUMERIC_DATE = r"\d{1,2}/\d{1,2}/\d{4}"
_DATE = rf"(?<!\w)(?:{_LONG_DATE}|{_NUMERIC_DATE})(?!\w)"
_ROW_DATE = re.compile(rf"(?<!\w){_LONG_DATE}(?!\w)", re.I)
_PRINT_LABEL = r"\b(?:statement date|date of statement)\b"
_PRINT_DATE = re.compile(rf"{_PRINT_LABEL}\s*:?\s*({_DATE})", re.I)
_ANY_DATE = re.compile(_DATE, re.I)

_HEADING = re.compile(r"^Statements\s*(?:&|and)\s*Billing$", re.I)
_ACCOUNT_KEYS = {"id", "accountid", "billingaccountid", "guarantorid"}
_VIEWER_DOWNLOAD = re.compile(rf"{DETAILS_PATH}/Download[A-Za-z]{{1,48}}/?")
_DIALOG = '[role=dialog].Popup:visible'
_DIALOG_HEADING = re.compile(r"^(?:Statement(?: PDF)?|Billing Statement|View Statement(?: \(PDF\))?|View PDF|PDF Viewer)$", re.I)
_OPEN_LIST = "In Medical Billing, open View billing and payment details, then Statements."
_READ_LIST = r"""heading => {
    const region = heading.parentElement?.parentElement?.parentElement;
    if (!region) return null;
    const visible = e => Boolean(e.getClientRects().length) &&
                         getComputedStyle(e).visibility === 'visible';
    const label = e => e.innerText.trim().replace(/\s+/g, ' ');
    const documents = [];
    for (const control of region.querySelectorAll('a')) {
        if (!visible(control) || !/^View statement\s*\(?PDF\)?$/i.test(label(control))) continue;
        const row = control.closest('li');
        const dates = row?.querySelectorAll('.ba_details_statement_date');
        const href = control.getAttribute('href');
        const index = control.getAttribute('data-index');
        const safe = row && dates.length === 1 && href?.startsWith('#') && /^\d+$/.test(index || '') &&
            !control.hasAttribute('target') && !control.hasAttribute('download') &&
            !control.closest('form');
        documents.push(safe ? [index, row.innerText, dates[0].innerText] : null);
    }
    return {
        rows: documents,
        empty: /\bno (?:[a-z-]+ )?statements are available for this account\b/i.test(region.innerText),
        more: [...region.querySelectorAll('button,a')].some(e =>
            visible(e) && !e.disabled && e.getAttribute('aria-disabled') !== 'true' &&
                /^(?:load more|next(?: page)?|(?:show|view) more(?: statements)?)$/i.test(label(e)))
    };
}"""


class MedicalListError(RuntimeError):
    """Medical billing did not show a complete, unambiguous statement list."""


@dataclass(frozen=True)
class MedicalBill:
    date_text: str
    document_id: str
    row_digest: str
    title: str = TITLE
    account: str = ""


def is_details_url(url: str) -> bool:
    try:
        address = urlsplit(url)
    except ValueError:
        return False
    return (address.scheme == "https" and address.netloc == HOST
            and address.path.rstrip("/") == DETAILS_PATH)


def is_statement_tab(page) -> bool:
    if not is_details_url(page.url):
        return False
    try:
        heading = page.get_by_role("heading", level=2, name=_HEADING)
        return heading.count() == 1 and heading.is_visible()
    except BrowserError:
        return False


def _account_scope(url: str) -> str:
    if not is_details_url(url):
        return ""
    values = [value for key, value in parse_qsl(urlsplit(url).query)
              if key.casefold() in _ACCOUNT_KEYS and value]
    return sha256(values[0].encode()).hexdigest() if len(values) == 1 else ""


def _read_rows(page) -> dict[MedicalBill, str]:
    if not is_statement_tab(page):
        raise MedicalListError(_OPEN_LIST)
    heading = page.get_by_role("heading", level=2, name=_HEADING)
    source_url = page.url
    deadline = monotonic() + 8
    while True:
        view = heading.evaluate(_READ_LIST)
        if not view or view["more"] or page.url != source_url:
            raise MedicalListError("The visible medical statements list is incomplete.")
        if view["rows"] or view["empty"]:
            break
        if monotonic() >= deadline:
            raise MedicalListError("Kaiser did not finish showing the medical statements list.")
        page.wait_for_timeout(150)
    if not view["rows"]:
        return {}
    account = _account_scope(source_url)
    selected = {}
    indexes = set()
    for entry in view["rows"]:
        if not entry:
            raise MedicalListError("Kaiser showed a medical statement control PaperPull could not identify.")
        index, row_text, date_text = entry
        bill = _bill_from_row(row_text, date_text, account)
        if bill in selected or index in indexes:
            raise MedicalListError("Kaiser showed indistinguishable medical statement rows.")
        selected[bill] = index
        indexes.add(index)
    return selected


def _iso_date(raw: str) -> str:
    value = " ".join(raw.replace(",", "").split())
    if "/" in value:
        fmt = "%m/%d/%Y"
    else:
        fmt = "%b %d %Y" if len(value.split()[0]) == 3 else "%B %d %Y"
    return datetime.strptime(value, fmt).date().isoformat()


def _bill_from_row(row_text: str, date_text: str, account_scope: str) -> MedicalBill:
    normalized = " ".join(row_text.split())
    # Kaiser repeats this date in its visual and screen-reader labels.
    try:
        dates = {_iso_date(value) for value in _ROW_DATE.findall(date_text)}
    except ValueError:
        raise MedicalListError("A medical statement row showed an invalid date.") from None
    if len(dates) != 1 or not account_scope:
        raise MedicalListError("A medical statement row did not identify its date and billing account.")
    date = dates.pop()
    row = sha256(normalized.encode()).hexdigest()
    key = sha256(f"kaiser:medical:{account_scope}:{row}".encode()).hexdigest()
    return MedicalBill(date, key, row)


def _dates_in(text: str, pattern: re.Pattern) -> set[str]:
    dates = set()
    for value in pattern.findall(text):
        try:
            dates.add(_iso_date(value))
        except ValueError:
            continue
    return dates


def _matches_pdf(data: bytes, bill: MedicalBill) -> bool:
    if not capture.is_document(data):
        return False
    read = pdf_reader.read(data, text_pages=3)
    if not read.opened or not read.pages or read.text_error:
        return False
    text = " ".join(" ".join(read.texts).split())
    if not re.search(r"\bstatement\b", text, re.I):
        return False
    # A printed statement date takes precedence over visit and due dates.
    if re.search(_PRINT_LABEL, text, re.I):
        return _dates_in(text, _PRINT_DATE) == {bill.date_text}
    return bill.date_text in _dates_in(text, _ANY_DATE)


def collect_download_docs(page) -> list[MedicalBill]:
    return list(_read_rows(page))


def _medical_download_url(url: str) -> bool:
    try:
        address = urlsplit(url)
    except ValueError:
        return False
    return (address.scheme == "https" and address.netloc == HOST
            and bool(_VIEWER_DOWNLOAD.fullmatch(address.path)))


def _close_viewer(page, press) -> bool:
    dialog = page.locator(_DIALOG)
    if not dialog.count():
        return True
    if dialog.count() != 1 or dialog.get_by_role("heading", name=_DIALOG_HEADING).count() != 1:
        return False
    controls = dialog.locator("button[type=button]:visible").element_handles()
    safe = [control for control in controls if control.evaluate(r"""e => !e.form &&
        /^Close this popup[.!]?$/i.test(
            (e.getAttribute('aria-label') || e.getAttribute('title') || e.innerText).trim())""")]
    if len(safe) != 1:
        return False
    press(page, safe[0], "button[type=button]")
    dialog.wait_for(state="hidden", timeout=4500)
    return True


def _capture_inline_pdf(page, control, press) -> bytes | None:
    """Read the browser's inline PDF response before Chromium opens its viewer."""
    session = page.context.new_cdp_session(page)
    answers = []
    refused = False

    def observe(event):
        nonlocal refused
        request_id = event["requestId"]
        try:
            request = event["request"]
            if (event.get("responseStatusCode") != 200 or request["method"] != "GET"
                    or not _medical_download_url(request["url"])):
                return
            headers = {item["name"].casefold(): item["value"] for item in event["responseHeaders"]}
            if headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/pdf":
                return
            if not 0 <= int(headers.get("content-length") or 0) <= intake.DOCUMENT_BYTES:
                refused = True
                return
            answer = session.send("Fetch.getResponseBody", {"requestId": request_id})
            data = intake.decode(answer["body"]) if answer["base64Encoded"] else b""
            if capture.is_document(data):
                answers.append(data)
        except (BrowserError, TypeError, ValueError, KeyError, intake.TooLarge):
            refused = True
        finally:
            try:
                session.send("Fetch.continueResponse", {"requestId": request_id})
            except BrowserError:
                pass

    session.on("Fetch.requestPaused", observe)
    try:
        session.send("Fetch.enable", {"patterns": [{
            "urlPattern": BASE + DETAILS_PATH + "/Download*",
            "requestStage": "Response",
        }]})
        press(page, control, "a[data-index]")
        deadline = monotonic() + 12
        while not answers and not refused and monotonic() < deadline:
            page.wait_for_timeout(100)
        return answers[0] if len(answers) == 1 and not refused else None
    finally:
        try:
            session.send("Fetch.disable")
        finally:
            session.detach()


def download_bill(page, bill: MedicalBill, out_path: Path, *, press) -> bool:
    if not _close_viewer(page, press):
        raise MedicalListError("Close the medical statement viewer and leave Statements open.")
    rows = _read_rows(page)
    if bill not in rows:
        return False
    controls = page.locator(f'a[data-index="{rows[bill]}"]:visible').element_handles()
    eligible = []
    for control in controls:
        row = control.evaluate(r"""e => {
            const href = e.getAttribute('href');
            if (!e.isConnected || !href?.startsWith('#') || e.hasAttribute('target') ||
                e.hasAttribute('download') || e.closest('form') ||
                !/^View statement\s*\(?PDF\)?$/i.test(e.innerText.trim().replace(/\s+/g,' '))) return null;
            const row = e.closest('li');
            const dates = row?.querySelectorAll('.ba_details_statement_date');
            return dates?.length === 1 ? [row.innerText, dates[0].innerText] : null;
        }""")
        if row and _bill_from_row(*row, _account_scope(page.url)) == bill:
            eligible.append(control)
    if len(eligible) != 1:
        return False
    try:
        data = _capture_inline_pdf(page, eligible[0], press)
    finally:
        if not _close_viewer(page, press):
            raise MedicalListError("Close the medical statement viewer and leave Statements open.")
    if not data or not _matches_pdf(data, bill):
        return False
    shared_folder.write_whole(out_path, data)
    return True
