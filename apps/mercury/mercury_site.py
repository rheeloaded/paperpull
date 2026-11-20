"""Read monthly deposit statements from Mercury's Documents & Data page."""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime
from hashlib import sha256
from pathlib import Path
import re
from urllib.parse import urlsplit

from playwright.sync_api import Error as BrowserError
from paperpull_core import intake, pdf_reader, refused, shared_folder
from paperpull_core.controls import AUTH_CONTROL_RE, SETTINGS_CONTROL_RE, control_label

HOST = "app.mercury.com"
DOWNLOAD_HOST = "backend.mercury.com"
DOCUMENTS_PATH = "/settings/documents"
DOCUMENTS_URL = f"https://{HOST}{DOCUMENTS_PATH}"
URLS = {"home": f"https://{HOST}/", "login": f"https://{HOST}/login", "documents": DOCUMENTS_URL}
ALLOWED_HOSTS = {HOST, DOWNLOAD_HOST}
LOGIN_URL_MARKERS = ("/login", "/authenticate")
FALLBACK = {"doc_row": "table tbody tr"}

_UUID = r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}"
STATEMENT_ID = re.compile(_UUID, re.I)
DOWNLOAD_PATH = re.compile(rf"/organizations/{_UUID}/statements/({_UUID})", re.I)
MONTHS = {name.lower(): n for n, name in enumerate(calendar.month_abbr) if n}
MONTHS.update({name.lower(): n for n, name in enumerate(calendar.month_name) if n})
ROW_MONTH = re.compile(r"([A-Za-z]+) (\d{4})")
MASKED_ACCOUNT = re.compile(r"(?:[•*xX][ \t]*){2,}(\d{4})$")
DEPOSIT_LABEL = re.compile(r"(?:(?:mercury|business|personal) )?(checking|savings)", re.I)
PERIOD_DATE = r"[A-Za-z]+ \d{1,2}, \d{4}"
PDF_PERIOD = re.compile(rf"({PERIOD_DATE})\s*[-–—]\s*({PERIOD_DATE})(?:\s*\(\d+ days?\))?", re.I)
PDF_ACCOUNT = re.compile(r"Account Number\s*[: ]?\s*(\d{4,24})", re.I)
SAFE_DOC_CONTROL_RE = re.compile(r"^(?:Select statement|Deselect statement|Download)$", re.I)
FORBIDDEN_CONTROL_RE = re.compile(r"\b(?:share|transfer|send|pay|create|generate|edit|delete|settings)\b", re.I)
RATE_LIMIT_MARKERS = re.compile(r"too many requests|rate limit", re.I)

# The first row names both columns, even when the table uses td for headings.
# Read the account suffix only to verify the PDF. It never leaves the site layer.
_SNAPSHOT = r"""() => {
    const tables = [...document.querySelectorAll('table')].filter(t => {
        const cells = t.rows[0]?.cells;
        return t.getClientRects().length && cells?.[1]?.innerText.trim() === 'Statement period'
            && cells?.[2]?.innerText.trim() === 'Account';
    });
    if (tables.length !== 1) return null;
    return [...tables[0].rows].slice(1).filter(r => r.getClientRects().length).map(r => {
        const box = r.querySelector('input[type=checkbox]');
        return {
            period: r.cells[1]?.innerText.trim() ?? '',
            account: r.cells[2]?.innerText.trim() ?? '',
            id: box?.value ?? '',
            selected: box?.checked ?? false,
            available: !!box && !box.disabled,
        };
    });
}"""


class SessionExpired(RuntimeError):
    """Mercury asked the account holder to sign in again."""


class ListStopped(RuntimeError):
    """The statement table could not be read safely."""


@dataclass(frozen=True)
class RawDoc:
    title: str
    date_text: str
    account: str
    document_id: str


@dataclass(frozen=True)
class Statement:
    row_id: str
    account_suffix: str
    kind: str
    month_end: date

    @property
    def document_id(self):
        return sha256(self.row_id.lower().encode()).hexdigest()

    @property
    def doc(self):
        return RawDoc(f"Mercury {self.kind} Statement", self.month_end.isoformat(),
                      self.kind, self.document_id)


def is_safe_url(url: str) -> bool:
    try:
        value = urlsplit(url or "")
    except ValueError:
        return False
    return (value.scheme, value.netloc) == ("https", HOST)


def is_safe_control(name: str) -> bool:
    return bool(SAFE_DOC_CONTROL_RE.fullmatch(name.strip()) and not any(
        guard.search(name) for guard in (FORBIDDEN_CONTROL_RE, AUTH_CONTROL_RE, SETTINGS_CONTROL_RE)
    ))


def is_statement_page_url(url: str) -> bool:
    return is_safe_url(url) and urlsplit(url).path.rstrip("/") == DOCUMENTS_PATH


def looks_signed_out(page) -> bool:
    if not is_safe_url(page.url):
        return False
    return (urlsplit(page.url).path.rstrip("/") in LOGIN_URL_MARKERS
            or bool(page.locator("input[type=password]:visible").count()))


def detect_security_challenge(page):
    if not is_safe_url(page.url):
        return None
    title = page.title()
    if RATE_LIMIT_MARKERS.search(title):
        return "Mercury is limiting requests. Try again later."
    if re.search(r"just a moment|security check|verify (?:that )?you are human", title, re.I):
        return "Mercury is asking for verification in the browser."
    return None


def open_statements(page) -> None:
    if not is_safe_url(page.url) or looks_signed_out(page):
        return
    if not is_statement_page_url(page.url):
        try:
            page.goto(DOCUMENTS_URL, wait_until="domcontentloaded", timeout=15000)
        except BrowserError:
            raise ListStopped("Documents & Data did not open") from None


def _read_rows(page):
    if looks_signed_out(page):
        raise SessionExpired()
    if not is_statement_page_url(page.url):
        raise ListStopped("Open Documents & Data → Statements in the Mercury window.")
    try:
        page.locator("table").filter(has_text="Statement period").first.wait_for(
            state="visible", timeout=8000
        )
        rows = page.evaluate(_SNAPSHOT)
    except BrowserError:
        if looks_signed_out(page):
            raise SessionExpired() from None
        raise ListStopped("The Mercury statement table did not appear.") from None
    if rows is None:
        raise ListStopped("The Mercury statement table could not be identified.")
    return rows


def _parse_rows(rows) -> dict[str, Statement]:
    statements = {}
    for row in rows:
        account_match = MASKED_ACCOUNT.search(row["account"])
        account_label = (row["account"][:account_match.start()] if account_match else row["account"]).strip()
        deposit = DEPOSIT_LABEL.fullmatch(account_label)
        if not deposit:
            continue
        if not account_match:
            raise ListStopped("A Mercury deposit row no longer shows its account suffix.")
        period = ROW_MONTH.fullmatch(row["period"])
        if not period or not isinstance(row["id"], str) or not STATEMENT_ID.fullmatch(row["id"]):
            raise ListStopped("A Mercury deposit statement row could not be identified.")
        month = MONTHS.get(period[1].lower())
        year = int(period[2])
        if not month or not 2000 <= year <= 2199:
            raise ListStopped("Mercury returned an unreadable statement month.")
        if not row["available"]:
            raise ListStopped("A Mercury deposit statement is unavailable.")
        end = date(year, month, calendar.monthrange(year, month)[1])
        statement = Statement(row["id"], account_match[1], deposit[1].title(), end)
        if statement.document_id in statements:
            raise ListStopped("Mercury returned the same statement more than once.")
        statements[statement.document_id] = statement
    return statements


def collect_download_docs(page):
    return [statement.doc for statement in _parse_rows(_read_rows(page)).values()]


def statement_list_ready(page) -> bool:
    try:
        collect_download_docs(page)
    except (ListStopped, SessionExpired):
        return False
    return True


def _download_address(href, row_id):
    try:
        url = urlsplit(href or "")
    except ValueError:
        return ""
    if (url.scheme, url.netloc) != ("https", DOWNLOAD_HOST) or url.query or url.fragment:
        return ""
    match = DOWNLOAD_PATH.fullmatch(url.path)
    return href if match and match[1] == row_id else ""


def _matches_pdf(data, statement: Statement):
    if not data.startswith(b"%PDF-"):
        return False
    try:
        pages = pdf_reader.page_texts(data, pages=1)
    except Exception:
        return False
    if not pages:
        return False
    lines = [" ".join(line.split()) for line in pages[0].splitlines()[:40]]
    month = statement.month_end
    title = f"{calendar.month_name[month.month]} {month.year} statement"
    for idx, line in enumerate(lines[:-1]):
        if line.casefold() == title.casefold():
            period = PDF_PERIOD.fullmatch(lines[idx + 1])
            break
    else:
        return False
    if period is None:
        return False
    try:
        start, end = (datetime.strptime(value, "%B %d, %Y").date() for value in period.groups())
    except ValueError:
        return False
    if not (date(month.year, month.month, 1) <= start <= end <= month):
        return False
    numbers = [match[1] for line in lines if (match := PDF_ACCOUNT.fullmatch(line))]
    return len(numbers) == 1 and numbers[0].endswith(statement.account_suffix)


def _fetch_pdf(page, href):
    response = None
    try:
        response = page.context.request.get(href, headers={"Accept": "application/pdf"},
                                            max_redirects=0, timeout=20000)
        if response.status in (401, 403):
            raise SessionExpired()
        if response.status == 429:
            raise ListStopped("Mercury is limiting statement downloads. Try again later.")
        content_type = response.headers.get("content-type", "").split(";")[0].lower().strip()
        if response.status != 200 or content_type != "application/pdf":
            raise SessionExpired()
        data = intake.body(response)
        if not data.startswith(b"%PDF-"):
            raise SessionExpired()
        return data
    except BrowserError:
        raise SessionExpired() from None
    finally:
        if response is not None:
            response.dispose()


def _statement_label_is_safe(label, row_id, checked):
    # Mercury uses a native label with no text. Verify which input it
    # actually controls, including when a new label points elsewhere.
    labels = label.evaluate("""(label, [rowId, checked]) => {
        const box = label.control;
        if (!box || !label.contains(box) || box.type !== 'checkbox' ||
            box.value !== rowId || box.disabled || box.checked !== checked ||
            label.querySelector('a, button, input:not([type=checkbox])')) return null;
        return [label.innerText, label.getAttribute('aria-label'), label.title,
                box.getAttribute('aria-label'), box.title];
    }""", [row_id, checked], timeout=1500)
    return labels is not None and all(is_safe_control(text) for text in labels if text and text.strip())


def _take_pdf(page, statement):
    box_selector = f'input[type="checkbox"][value="{statement.row_id}"]'
    box = page.locator(f"table {box_selector}")
    label = page.locator(f"table label:has({box_selector})")
    if (box.count() != 1 or label.count() != 1
            or not _statement_label_is_safe(label, statement.row_id, False)):
        raise ListStopped("The statement selection control changed.")
    selected_here = False
    try:
        label.click(timeout=5000)
        selected_here = True
        after = _read_rows(page)
        if [row["id"] for row in after if row["selected"]] != [statement.row_id]:
            raise ListStopped("Mercury selected a different set of statements.")
        if _parse_rows(after).get(statement.document_id) != statement:
            raise ListStopped("The selected Mercury statement changed.")
        link = page.get_by_role("link", name="Download", exact=True)
        link.wait_for(state="visible", timeout=8000)
        if link.count() != 1 or not is_safe_control(control_label(link)):
            raise ListStopped("The statement download link changed.")
        href = _download_address(link.get_attribute("href", timeout=5000), statement.row_id)
        if not href:
            raise ListStopped("The download link did not identify the selected statement.")
        return _fetch_pdf(page, href)
    except BrowserError:
        if looks_signed_out(page):
            raise SessionExpired() from None
        raise ListStopped("Mercury did not expose the selected statement for download.") from None
    finally:
        if selected_here and is_statement_page_url(page.url):
            try:
                if box.count() == label.count() == 1 and _statement_label_is_safe(
                    label, statement.row_id, True
                ):
                    label.click(timeout=1200)
            except BrowserError:
                pass


def _read_after_refusal(page):
    if looks_signed_out(page):
        raise SessionExpired()
    if not is_statement_page_url(page.url):
        raise ListStopped("The Mercury Statements page is no longer open.")
    page.reload(wait_until="domcontentloaded", timeout=15000)
    return collect_download_docs(page)


def download_bill(page, date: str, out_path: Path, *, account: str, document_id: str) -> bool:
    rows = _read_rows(page)
    statement = _parse_rows(rows).get(document_id)
    if not statement or (statement.kind, statement.month_end.isoformat()) != (account, date):
        raise ListStopped("The statement no longer matches the listed account and month.")
    if any(row["selected"] for row in rows):
        raise ListStopped("Clear the selected rows on Mercury's Statements page and try again.")
    try:
        data = _take_pdf(page, statement)
    except SessionExpired:
        refreshed = refused.list_again(lambda: _read_after_refusal(page), SessionExpired, ListStopped)
        if statement.doc not in refreshed:
            raise ListStopped("The selected statement was missing after Mercury reloaded the list.")
        return False
    if not _matches_pdf(data, statement):
        return False
    shared_folder.write_bytes(out_path, data)
    return True
