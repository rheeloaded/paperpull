"""Read Sonic Member Tools bill history and verified invoice PDFs."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from html.parser import HTMLParser
from pathlib import Path
import re
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import Error as BrowserError
from paperpull_core import identity, intake, pdf_reader, refused, shared_folder
from paperpull_core.controls import AUTH_CONTROL_RE, SETTINGS_CONTROL_RE

HOST = "members.sonic.net"
BASE = f"https://{HOST}"
BILLING_PATH = "/account/billing/"
HISTORY_PATH = BILLING_PATH + "history/"
INVOICE_PATH = BILLING_PATH + "invoice/view.php"
DOCUMENTS_URL = BASE + HISTORY_PATH
URLS = {"home": BASE + "/", "login": BASE + BILLING_PATH, "documents": DOCUMENTS_URL}
ALLOWED_HOSTS = {HOST}
RATE_LIMIT_MARKERS = re.compile(r"too many requests|rate limit", re.I)
FORBIDDEN_CONTROL_RE = re.compile(r"\b(?:pay|payment|transfer|change|delete|add|edit|submit|send)\b", re.I)
SAFE_DOC_CONTROL_RE = re.compile(r"^(?:(?:view|download) )?(?:(?:internet )?bill|invoice|pdf)$", re.I)
FALLBACK = {"doc_row": "ul.list-group > li.list-group-item"}

_ID = re.compile(r"[0-9]{1,18}")
_HISTORY_DATE = re.compile(r"^([A-Za-z]+ \d{1,2}, \d{4})(?!\d)")
_PDF_NUMBER = re.compile(r"\bInvoice Number\s*:\s*([0-9]{1,18})(?![0-9A-Za-z])", re.I)
_DATE_TEXT = (r"(?:[0-9]{1,2}/[0-9]{1,2}/(?:[0-9]{4}|[0-9]{2})"
              r"|[A-Za-z]+ [0-9]{1,2}, [0-9]{4}|[0-9]{4}-[0-9]{2}-[0-9]{2})")
_PDF_DATE = re.compile(
    rf"\b(?:Payment Due(?:\s+(?:On|By|Date))?|Invoice Date)\s*:\s*({_DATE_TEXT})(?![0-9A-Za-z])",
    re.I,
)
_PERIOD = re.compile(rf"^\s*({_DATE_TEXT})\s*[-–—]\s*{_DATE_TEXT}\s*$")
_HISTORY_LIMIT = 3_000_000


class SessionExpired(RuntimeError):
    """Member Tools asked for sign-in again."""


class ListStopped(RuntimeError):
    """The Sonic bill history could not be read safely."""


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
        return sha256(("sonic:" + self.invoice_id).encode()).hexdigest()

    @property
    def record(self) -> RawDoc:
        return RawDoc("Sonic Internet Bill", self.date, "", self.key)


class _HistoryHTML(HTMLParser):
    """Read the rows of Sonic's server-rendered list without loading its resources."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.groups = []
        self.signed_out = False
        self._list_depth = 0
        self._group = None
        self._row = None

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        classes = (attrs.get("class") or "").split()
        if tag == "input" and (attrs.get("type") or "").lower() == "password":
            self.signed_out = True
        if tag == "ul":
            if self._list_depth or "list-group" in classes:
                if not self._list_depth:
                    self._group = []
                self._list_depth += 1
        if self._list_depth != 1:
            return
        if tag == "li":
            if self._row is not None or "list-group-item" not in classes:
                raise ListStopped("A Sonic history row was not in the expected format.")
            self._row = ([], [])
        elif self._row is not None and tag == "a":
            href = attrs.get("href") or ""
            title = (attrs.get("title") or "").strip().casefold()
            if title == "download pdf" or INVOICE_PATH in href:
                self._row[1].append(href)

    def handle_endtag(self, tag):
        if self._list_depth == 1 and tag == "li" and self._row is not None:
            self._group.append(self._row)
            self._row = None
        if tag == "ul" and self._list_depth:
            self._list_depth -= 1
            if not self._list_depth:
                if self._row is not None:
                    raise ListStopped("Sonic's bill history ended mid-row.")
                self.groups.append(self._group)
                self._group = None

    def handle_data(self, data):
        if self._row is not None and self._list_depth == 1:
            self._row[0].append(data)


def is_safe_url(url: str) -> bool:
    try:
        parsed = urlsplit(url or "")
    except ValueError:
        return False
    return (parsed.scheme, parsed.netloc) == ("https", HOST)


def is_history_page_url(url: str) -> bool:
    return is_safe_url(url) and urlsplit(url).path.rstrip("/") == HISTORY_PATH.rstrip("/")


def is_safe_control(name: str) -> bool:
    """Describe invoice controls to diagnostics. Runs fetch by address."""
    return bool(SAFE_DOC_CONTROL_RE.fullmatch(name.strip())) and not any(
        pattern.search(name) for pattern in (FORBIDDEN_CONTROL_RE, AUTH_CONTROL_RE, SETTINGS_CONTROL_RE)
    )


def looks_signed_out(page) -> bool:
    return is_safe_url(page.url) and bool(page.locator("input[type=password]:visible").count())


def detect_security_challenge(page):
    if not is_safe_url(page.url):
        return None
    title = page.title()
    if RATE_LIMIT_MARKERS.search(title):
        return "Sonic is limiting requests. Try again later."
    if re.search(r"just a moment|security check|verify (?:that )?you are human", title, re.I):
        return "Sonic is asking for verification in the browser."
    return None


def _invoice_id(href: str) -> str:
    try:
        parsed = urlsplit(href)
        params = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=True)
    except ValueError:
        return ""
    if (parsed.scheme, parsed.netloc) not in {("", ""), ("https", HOST)}:
        return ""
    if parsed.path != INVOICE_PATH or parsed.fragment or set(params) != {"id", "pdf"}:
        return ""
    ids = params["id"]
    return ids[0] if len(ids) == 1 and _ID.fullmatch(ids[0]) and params["pdf"] == ["1"] else ""


def _listed_date(parts) -> str:
    normalized = " ".join(" ".join(parts).split())
    found = _HISTORY_DATE.match(normalized)
    if found:
        for fmt in ("%B %d, %Y", "%b %d, %Y"):
            try:
                return datetime.strptime(found[1], fmt).date().isoformat()
            except ValueError:
                pass
    raise ListStopped("A Sonic bill is missing its history date.")


def _parse_history(html: str) -> dict[str, Bill]:
    parser = _HistoryHTML()
    parser.feed(html)
    parser.close()
    if parser.signed_out:
        raise SessionExpired()
    if parser._list_depth:
        raise ListStopped("Sonic's bill history ended before the list closed.")
    groups = [rows for rows in parser.groups if any(links for _, links in rows)]
    if len(groups) != 1:
        raise ListStopped("Sonic did not return one recognizable bill history list.")
    bills = {}
    for parts, links in groups[0]:
        invoice_id = _invoice_id(links[0]) if len(links) == 1 else ""
        if not invoice_id:
            raise ListStopped("A Sonic bill lacks one recognizable PDF link.")
        bill = Bill(invoice_id, _listed_date(parts))
        if bill.key in bills:
            raise ListStopped("Sonic returned the same invoice more than once.")
        bills[bill.key] = bill
    return bills


def _read_history(page) -> dict[str, Bill]:
    if not is_safe_url(page.url):
        raise ListStopped("Open Sonic Member Tools in its sign-in window.")
    response = None
    try:
        response = page.context.request.get(
            DOCUMENTS_URL, headers={"Accept": "text/html"}, max_redirects=0, timeout=18000
        )
        if response.status in (401, 403):
            raise SessionExpired()
        if response.status == 429:
            raise ListStopped("Sonic is limiting bill-history requests. Try again later.")
        if response.status != 200:
            if 300 <= response.status < 400 and looks_signed_out(page):
                raise SessionExpired()
            raise ListStopped("The Sonic bill history request did not complete.")
        mime = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if mime != "text/html":
            raise ListStopped("Sonic returned an unexpected bill history format.")
        return _parse_history(intake.text_of(response, limit=_HISTORY_LIMIT))
    except (BrowserError, intake.TooLarge):
        raise ListStopped("Sonic's bill history could not be read.") from None
    finally:
        if response is not None:
            response.dispose()


_RUN: dict = {}


def collect_download_docs(page) -> list[RawDoc]:
    _RUN.clear()
    bills = _read_history(page)
    _RUN.update(page=page, bills=bills)
    return [bill.record for bill in bills.values()]


def bill_list_ready(page) -> bool:
    try:
        collect_download_docs(page)
    except (SessionExpired, ListStopped):
        return False
    return True


def _fetch_pdf(page, invoice_id: str) -> bytes:
    if not is_safe_url(page.url) or not _ID.fullmatch(invoice_id):
        raise ListStopped("The selected Sonic bill is no longer available in this window.")
    response = None
    try:
        url = f"{BASE}{INVOICE_PATH}?id={invoice_id}&pdf=1"
        response = page.context.request.get(
            url, headers={"Accept": "application/pdf"}, max_redirects=0, timeout=20000
        )
        if response.status in (401, 403):
            raise SessionExpired()
        if response.status == 429:
            raise ListStopped("Sonic is limiting invoice downloads. Try again later.")
        mime = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if response.status != 200 or mime != "application/pdf":
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


def _pdf_matches(data: bytes, bill: Bill) -> bool:
    try:
        pages = pdf_reader.page_texts(data, pages=1, layout=True)
    except Exception:
        return False
    if not pages:
        return False
    invoice_numbers = _PDF_NUMBER.findall(pages[0])
    if set(invoice_numbers) != {bill.invoice_id}:
        return False
    # Sonic labels the date in bill history by the payment or service period.
    # The separately printed Invoice Date can precede it.
    variants = identity.date_variants(bill.date)
    for line in pages[0].splitlines()[:60]:
        dates = _PDF_DATE.findall(line)
        if period := _PERIOD.fullmatch(line):
            dates.append(period[1])
        if any(identity.contains(value, variants, "date") for value in dates):
            return True
    return False


def download_bill(page, date: str, out_path: Path, *, document_id: str) -> bool:
    if _RUN.get("page") is not page:
        collect_download_docs(page)
    bill = _RUN["bills"].get(document_id)
    if not bill or bill.date != date:
        raise ListStopped("The selected bill no longer matches Sonic's history.")
    try:
        data = _fetch_pdf(page, bill.invoice_id)
    except SessionExpired:
        refreshed = refused.list_again(lambda: collect_download_docs(page), SessionExpired, ListStopped)
        if bill.record not in refreshed:
            raise ListStopped("The selected bill was missing after Sonic reloaded the history.")
        return False
    if not _pdf_matches(data, bill):
        return False
    shared_folder.write_bytes(out_path, data)
    return True
