"""United Airlines (united.com) purchase receipt discovery and PDF capture.

How united.com's receipts work, mapped on 2026-11-26 against a signed-in
MileagePlus account with thirteen flight reservations and seven seat
purchases, the oldest bought in September 2024:

* The receipts page is ``https://www.united.com/en/us/receipts``. Signed
  in, it goes on to ``/en/us/receipts/search`` and lists the member's
  receipts in two tables, "Travel Reservations" (a flight booking, keyed
  by its six-character confirmation number) and "Travel options and
  inflight purchases" (a seat, a bag, an upgrade, keyed by a thirteen-digit
  receipt number). VERIFIED.
* The page reads the list from ``POST /api/CustomerCare/CustomerReceipts``,
  asked by the member's MileagePlus number (``QueryByFqtv``) with
  ``QueryArchive: "N"``. The answer holds every receipt at once, under
  ``Data.Reservations`` and ``Data.TravelOptions``, each with a
  ``RcptData`` block: the receipt's id, its type (``T`` a flight, ``D`` a
  travel option) and its tickets, documents and travelers. The page shows
  the first eight rows of a table and a "Load more results" button for
  the rest. The page never asks for the archive, so neither does the app,
  and how far back the list goes is up to United.
* "View receipt" sends that ``RcptData`` to
  ``POST /api/CustomerCare/GetHTMLReceipt`` and writes the answer's HTML
  into a new blank tab. The answer is a list of HTML receipts
  (``Data.GetRcptHTMLResp.Rcpt[].Html``). For some flights booked for four
  it holds four, one per traveler, and the tab shows only the first. For
  others it holds one that covers all four, and a travel option's receipt
  is always one for everyone on it. So the app prints every receipt in the
  answer and files them as one PDF, in United's order, and the printed
  receipts together must show every traveler's eTicket number. There is no
  PDF anywhere. VERIFIED.
* For one exchanged reservation the answer was a single empty receipt,
  ``[{}]``, on every try, and United's own page said "We're having trouble
  displaying your receipt". The app says so and leaves it for the next run.
* Both routes refuse a request made from outside the page, even with the
  browser's cookies: Akamai answers 428 "Access Denied". So the app reads
  the list the page itself asks for when it loads, and gets each receipt
  by pressing that row's "View receipt", reading the answer the page gets,
  and closing the tab it opened. It never reads or sends the page's
  sign-in token. "Email receipt", beside it in every row, sends an email
  and is refused by the guard.
* The receipt prints its confirmation number (or, for a travel option, the
  reference number of each item) and "Date of purchase", the day the
  tickets were issued. A ticket that was exchanged prints the day of the
  exchange. Each printed receipt must show its number and one of the
  listed purchase days before it is filed.

Pressing "View receipt" (and "Load more results") is the only thing this
app does on the page. It never presses Email receipt, never changes a
search, a date range or a filter, and never opens a trip, a check-in, a
change, a cancellation, a refund or a payment.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlsplit

from paperpull_core import identity, intake, pdf_reader, pressing, receipt_pdf, refused, shared_folder, tabs
from paperpull_core.characters import whole_json
from paperpull_core.controls import AUTH_CONTROL_RE, SETTINGS_CONTROL_RE
from paperpull_core.urls import is_safe_url as _host_allows
from paperpull_core.words import words_for


HOST = "www.united.com"
BASE = f"https://{HOST}/en/us"
RECEIPTS_URL = f"{BASE}/receipts"
SEARCH_PATH = "/en/us/receipts/search"
ORDERS_URL = RECEIPTS_URL
LIST_PATH = "/api/CustomerCare/CustomerReceipts"
RECEIPT_PATH = "/api/CustomerCare/GetHTMLReceipt"
URLS = {"home": RECEIPTS_URL, "login": RECEIPTS_URL, "documents": RECEIPTS_URL}
ALLOWED_HOSTS = {HOST}
LOGIN_URL_MARKERS = ("/login", "/sign-in", "/signin")

CONFIRMATION = re.compile(r"^[A-Z0-9]{6}$")
RECEIPT_NUMBER = re.compile(r"^\d{13}$")
TICKET = re.compile(r"^\d{13}$")
FQTV = re.compile(r"^[A-Z0-9]{6,12}$")
RCPT_ID = re.compile(r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$", re.I)
AIRPORT = re.compile(r"^[A-Z]{3}$")
# The page's own types: T a flight reservation, D a travel option.
TRAVEL, OPTION = "T", "D"
LIST_BYTES = 8_000_000
RECEIPT_BYTES = 8_000_000
LIST_WAIT_MS = 30000
RECEIPT_WAIT_MS = 30000
POLL_MS = 250
POPUP_WAIT_MS = 5000
MAX_LOAD_MORE = 40
MAX_TRAVELERS = 12

# The two tables, each by the label of the cell that holds its key.
KEY_LABEL = {TRAVEL: "Confirmation number", OPTION: "Receipt number"}
TABLE_NAME = {TRAVEL: "Travel Reservations", OPTION: "Travel options and inflight purchases"}
VIEW_LABEL = "View receipt, opens in a new tab"
VIEW_CSS = f"button[aria-label='{VIEW_LABEL}']"
LOAD_MORE_CSS = "button"
LOAD_MORE_TEXT = "Load more results"

FORBIDDEN_CONTROL_RE = re.compile(
    r"\b(?:e-?mail(?:s|ed|ing)?|send|share|print\s+boarding|boarding\s+pass|check[\s-]?in|"
    r"pay(?:s|ment|ments)?|refund(?:s|ed)?|cancel(?:s|led|lation)?|"
    r"chang(?:e|es|ed|ing)|edit(?:s|ed|ing)?|updat(?:e|es|ed|ing)|modify|"
    r"upgrade|buy|purchase\s+(?:now|seat|bag|miles)|book(?:ing)?\s+now|"
    r"add(?:\s+bags?)?|redeem|transfer|delete|remove|submit|confirm|continue|"
    r"select\s+seats?|seat\s+map|request|claim|dispute|"
    r"find\s+receipt|search\s+another)\b", re.I)
SAFE_DOC_CONTROL_RE = re.compile(
    r"\b(?:view\s+(?:(?:flight|purchase)\s+)?receipt|load\s+more\s+results)\b", re.I)
RATE_LIMIT_MARKERS = re.compile(r"too many requests|rate limit|access denied", re.I)
FALLBACK = {"doc_row": "main table tbody tr"}


class SessionExpired(RuntimeError):
    """united.com answered as no one signed in."""


class ListStopped(RuntimeError):
    """The receipt list could not be read, or a receipt not fetched, as
    it should be."""


@dataclass(frozen=True)
class RawDoc:
    title: str
    date_text: str
    account: str
    document_id: str
    number: str = ""


@dataclass(frozen=True)
class Receipt:
    kind: str              # TRAVEL or OPTION
    number: str            # confirmation number, or receipt number
    receipt_id: str
    date: str              # the day the app files it under
    dates: tuple           # every day the receipt may print as its purchase day
    references: tuple      # numbers one of which each printed receipt must show
    tickets: tuple         # eTicket numbers the receipts together must show


_RUN: dict = {}
_WORDS: dict = {}


def words():
    if "w" not in _WORDS:
        import sys
        _WORDS["w"] = words_for("United", sys.modules[__name__])
    return _WORDS["w"]


def is_safe_url(url: str) -> bool:
    return _host_allows(url, ALLOWED_HOSTS, subdomains=False)


def is_safe_control(name: str) -> bool:
    return bool(SAFE_DOC_CONTROL_RE.search(name or "") and not any(
        pattern.search(name or "") for pattern in (FORBIDDEN_CONTROL_RE, AUTH_CONTROL_RE, SETTINGS_CONTROL_RE)))


def is_invoice_page_url(url: str) -> bool:
    """Any page of united.com. The receipts page is opened by its address
    in the tab, with the session every united.com page shares."""
    u = urlsplit(url or "")
    return (u.scheme, u.hostname) == ("https", HOST)


def _on_search(url: str) -> bool:
    u = urlsplit(url or "")
    return (u.scheme, u.hostname) == ("https", HOST) and u.path.rstrip("/") == SEARCH_PATH


def _is_route(response, path: str) -> bool:
    try:
        u = urlsplit(response.url or "")
        return ((u.scheme, u.hostname, u.path) == ("https", HOST, path)
                and response.request.method == "POST")
    except Exception:
        return False


def _tag(value: str) -> str:
    return sha256(value.encode()).hexdigest()


def looks_signed_out(page) -> bool:
    u = urlsplit(getattr(page, "url", "") or "")
    if (u.scheme, u.hostname) != ("https", HOST):
        return False
    path = u.path.lower()
    return any(m in path for m in LOGIN_URL_MARKERS)


def detect_security_challenge(page):
    if not is_safe_url(getattr(page, "url", "") or ""):
        return None
    try:
        title = page.title()
        if RATE_LIMIT_MARKERS.search(title):
            return "united.com is refusing requests from this browser for now. Try again later."
        if re.search(r"just a moment|verify you are human|security check|are you a robot", title, re.I):
            return "united.com is asking for verification in the browser."
    except Exception:
        pass
    return None


# -- the list ------------------------------------------------------------

class _Heard:
    """The answers of one route the page receives while armed."""

    def __init__(self, page, path: str):
        self.page, self.path, self.got = page, path, []

    def _on(self, response):
        if _is_route(response, self.path):
            self.got.append(response)

    def __enter__(self):
        self.page.on("response", self._on)
        return self

    def __exit__(self, *exc):
        try:
            self.page.remove_listener("response", self._on)
        except Exception:
            pass
        return False


def _asked_by(response) -> dict:
    """The JSON the page sent with a request, {} when it cannot be read."""
    try:
        sent = whole_json(json.loads(response.request.post_data or ""))
    except Exception:
        return {}
    return sent if isinstance(sent, dict) else {}


def _member_of(sent: dict) -> str:
    """The MileagePlus number a list request asked by, or ""."""
    try:
        if sent.get("QueryArchive") != "N":
            return ""
        query = sent["QueryParam"]
        if any(query.get(k) for k in ("QueryByPnr", "QueryByCC", "QueryByTkt", "QueryByDoc")):
            return ""
        number = query["QueryByFqtv"]["FqtvNbr"]
    except Exception:
        return ""
    return number if isinstance(number, str) and FQTV.fullmatch(number) else ""


def _json_of(response, limit: int):
    status = response.status
    if status in (428, 429):
        raise ListStopped("united.com is refusing requests from this browser for now. "
                          "Wait a while, then Resume.")
    if status in (401, 403):
        raise SessionExpired()
    if status != 200:
        raise ListStopped("united.com did not answer the receipt request")
    try:
        data = whole_json(json.loads(intake.text_of(response, limit=limit)))
    except Exception:
        raise ListStopped("united.com did not return a readable answer") from None
    if not isinstance(data, dict):
        raise ListStopped("united.com did not return a readable answer")
    return data


def open_receipts_page(page) -> None:
    """Open the receipts page in a tab, reading the list it asks for on the
    way, so a run that opens the page and then lists loads it once. A list
    that could not be read is left for account_tag and the listing, which
    say why."""
    try:
        _tag_now, _found, docs = _receipts(page)
    except (SessionExpired, ListStopped):
        return
    _RUN["unread_docs"] = (page, docs)


def _open_list(page) -> tuple[str, dict]:
    """Open the receipts page by its address and read the list the page
    asks for. (member tag, the list's Data block). Nothing is pressed."""
    if not is_invoice_page_url(getattr(page, "url", "")) and not tabs.is_own(page):
        raise ListStopped("Open united.com in the PaperPull browser.")
    with _Heard(page, LIST_PATH) as heard:
        try:
            page.goto(RECEIPTS_URL, wait_until="domcontentloaded", timeout=60000)
        except Exception:
            if looks_signed_out(page):
                raise SessionExpired() from None
            raise ListStopped("The united.com receipts page did not open") from None
        waited = 0
        while not heard.got and waited < LIST_WAIT_MS:
            if looks_signed_out(page):
                raise SessionExpired()
            page.wait_for_timeout(POLL_MS)
            waited += POLL_MS
        if not heard.got:
            if looks_signed_out(page) or not _on_search(page.url):
                # Signed out, the receipts page shows its search form and
                # asks for nothing.
                raise SessionExpired()
            raise ListStopped("united.com did not send the receipt list")
        page.wait_for_timeout(POLL_MS * 4)
        answers = list(heard.got)
    if len(answers) != 1:
        raise ListStopped("united.com sent the receipt list more than once")
    response = answers[0]
    member = _member_of(_asked_by(response))
    if not member:
        raise ListStopped("The receipts page did not ask by the signed-in MileagePlus number")
    data = _json_of(response, LIST_BYTES)
    block = data.get("Data")
    if not isinstance(block, dict):
        raise SessionExpired() if data.get("Errors") else ListStopped(
            "united.com did not return a readable receipt list")
    return _tag(member), block


def _iso(value) -> str:
    """An ISO day from "YYYY-MM-DD..." or "MM/DD/YYYY", else ""."""
    if not isinstance(value, str):
        return ""
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", value)
    if m:
        return "-".join(m.groups())
    m = re.match(r"^(\d{2})/(\d{2})/(\d{4})$", value)
    if m:
        return f"{m.group(3)}-{m.group(1)}-{m.group(2)}"
    return ""


def _strings(items, key):
    return [i.get(key) for i in items or [] if isinstance(i, dict) and isinstance(i.get(key), str)]


def _route_of(segments) -> str:
    legs = []
    for s in segments or []:
        if not isinstance(s, dict):
            continue
        a, b = s.get("OriginIATACode"), s.get("DestinationIATACode")
        if isinstance(a, str) and isinstance(b, str) and AIRPORT.fullmatch(a) and AIRPORT.fullmatch(b):
            legs.append(f"{a}-{b}")
    return ", ".join(legs[:4])


def _reservation(row) -> tuple[Receipt, str]:
    rd = row.get("RcptData") if isinstance(row, dict) else None
    if not isinstance(rd, dict):
        raise ListStopped("united.com returned an unrecognized reservation")
    number, rid = row.get("RecordLocator"), rd.get("RcptId")
    if (not isinstance(number, str) or not CONFIRMATION.fullmatch(number) or rd.get("RecLoc") != number
            or rd.get("RcptType") != TRAVEL or not isinstance(rid, str) or not RCPT_ID.fullmatch(rid)):
        raise ListStopped("united.com returned an unrecognized reservation")
    tickets = [t for t in rd.get("Tkt") or [] if isinstance(t, dict)]
    issued = sorted({_iso(t.get("IssLclDtTm")) for t in tickets} - {""})
    created = _iso(rd.get("PnrCreateDt"))
    emds = sorted({_iso(e.get("DocCreateDt")) for e in rd.get("Emd") or [] if isinstance(e, dict)} - {""})
    date = issued[0] if issued else created
    travelers = [t for t in rd.get("Tvlr") or [] if isinstance(t, dict)]
    owned = [n for t in travelers for n in t.get("TktNbr") or [] if isinstance(n, str)]
    if not date or not 1 <= len(travelers) <= MAX_TRAVELERS:
        raise ListStopped("united.com returned a reservation without a purchase date")
    if not owned or not all(TICKET.fullmatch(n) for n in owned):
        raise ListStopped("united.com returned a reservation without its tickets")
    dates = tuple(dict.fromkeys(d for d in [date, *issued, created, *emds] if d))
    receipt = Receipt(TRAVEL, number, rid.lower(), date, dates, (number,), tuple(dict.fromkeys(owned)))
    return receipt, _route_of(row.get("Segments"))


def _option(row) -> tuple[Receipt, str]:
    rd = row.get("RcptData") if isinstance(row, dict) else None
    if not isinstance(rd, dict):
        raise ListStopped("united.com returned an unrecognized purchase")
    number, rid = row.get("ReceiptNumber"), rd.get("RcptId")
    if (not isinstance(number, str) or not RECEIPT_NUMBER.fullmatch(number)
            or rd.get("RcptType") != OPTION or not isinstance(rid, str) or not RCPT_ID.fullmatch(rid)):
        raise ListStopped("united.com returned an unrecognized purchase")
    docs = [d for d in _strings(rd.get("Emd"), "DocId") if RECEIPT_NUMBER.fullmatch(d)]
    if number not in docs:
        raise ListStopped("united.com returned a purchase whose receipt number it does not hold")
    date = _iso(row.get("PurchaseDate")) or _iso(row.get("DocCreateDt"))
    if not date:
        raise ListStopped("united.com returned a purchase without a date")
    dates = tuple(dict.fromkeys(d for d in [date, _iso(row.get("DocCreateDt")),
                  *(_iso(e.get("DocCreateDt")) for e in rd.get("Emd") or [] if isinstance(e, dict))] if d))
    detail = row.get("PurchaseDetail") if isinstance(row.get("PurchaseDetail"), str) else ""
    receipt = Receipt(OPTION, number, rid.lower(), date, dates, tuple(dict.fromkeys(docs)), ())
    return receipt, " ".join(detail.split()).title()[:60]


def _receipts(page) -> tuple[str, dict, list]:
    tag, block = _open_list(page)
    _RUN["tag_for"] = (page, tag)
    for stale in ("page", "account", "receipts", "rows"):
        _RUN.pop(stale, None)
    reservations, options = block.get("Reservations"), block.get("TravelOptions")
    if not isinstance(reservations, list) or not isinstance(options, list):
        raise ListStopped("united.com did not return a readable receipt list")
    found: dict[str, Receipt] = {}
    rows: dict[str, dict] = {}
    docs: list = []
    for kind, items, read in ((TRAVEL, reservations, _reservation), (OPTION, options, _option)):
        for row in items:
            receipt, about = read(row)
            key = _tag(f"{tag}:{receipt.receipt_id}")
            if key in found:
                if found[key].number != receipt.number:
                    raise ListStopped("united.com returned conflicting records for a receipt")
                continue
            found[key] = receipt
            rows[key] = row["RcptData"]
            if kind == TRAVEL:
                title = f"United Airlines Flight Receipt {receipt.number}"
            else:
                title = f"United Airlines Purchase Receipt {receipt.number}"
            docs.append(RawDoc(title + (f": {about}" if about else ""), receipt.date, tag, key,
                               receipt.number))
    _RUN.update(page=page, account=tag, receipts=found, rows=rows)
    return tag, found, docs


def collect_download_docs(page) -> list[RawDoc]:
    """The receipts of the list. The list account_tag has just read for
    this page is taken once rather than opened again, and every other call
    opens the receipts page and reads it anew."""
    held = _RUN.pop("unread_docs", None)
    if held and held[0] is page:
        return held[1]
    return _receipts(page)[2]


def account_tag(page, fresh: bool = False) -> str:
    """A hash of the signed-in member's MileagePlus number, as the receipts
    page asked for the list by it, or "" when no list could be read. Kept
    for the page it was read on."""
    if not is_invoice_page_url(getattr(page, "url", "")):
        return ""
    cached = _RUN.get("tag_for")
    if cached and cached[0] is page and not fresh:
        return cached[1]
    try:
        tag, _found, docs = _receipts(page)
    except (SessionExpired, ListStopped):
        return ""
    _RUN["unread_docs"] = (page, docs)
    return tag


def invoice_list_look(page) -> tuple[bool, str]:
    """(True, "ready") when the receipt list was read, (False, "signed out")
    when the page shows no one signed in, else (False, "stopped")."""
    if not is_invoice_page_url(getattr(page, "url", "")):
        return False, "stopped"
    try:
        _receipts(page)
    except SessionExpired:
        return False, "signed out"
    except ListStopped:
        return False, "stopped"
    return True, "ready"


def invoice_list_ready(page) -> bool:
    return invoice_list_look(page)[0]


def unpaid_counts() -> dict:
    """united.com lists no receipt without a payment."""
    return {}


def legacy_count() -> int:
    return 0


# -- one receipt -----------------------------------------------------------

def _section(page, kind: str):
    """The section of the page that holds a table's rows."""
    return page.locator("main section").filter(
        has=page.locator(f"td[data-label='{KEY_LABEL[kind]}']"))


def _row(page, receipt: Receipt):
    """The table row of a receipt, pressing "Load more results" in its
    section until it shows. None when it never shows."""
    section = _section(page, receipt.kind)
    waited = 0
    while section.count() == 0 and waited < LIST_WAIT_MS:
        # The list has arrived, and its tables are still being drawn.
        page.wait_for_timeout(POLL_MS)
        waited += POLL_MS
    key_cell = f"td[data-label='{KEY_LABEL[receipt.kind]}']"
    for _ in range(MAX_LOAD_MORE):
        if section.count() != 1:
            return None
        rows = section.locator("tbody tr")
        hits = []
        for i in range(rows.count()):
            cell = rows.nth(i).locator(key_cell)
            if cell.count() == 1 and " ".join((cell.inner_text() or "").split()) == receipt.number:
                hits.append(i)
        if len(hits) > 1:
            raise ListStopped("The receipts page shows a receipt number twice")
        if hits:
            return rows.nth(hits[0])
        more = section.locator(LOAD_MORE_CSS).filter(has_text=LOAD_MORE_TEXT)
        if more.count() != 1:
            return None
        label = " ".join((more.inner_text() or "").split())
        if not is_safe_control(label):
            raise ListStopped("The receipts page's Load more control is not the one expected")
        pressing.click(page, more, css=LOAD_MORE_CSS, words=words(), step="show more receipts",
                       what=f"the Load more results button of {TABLE_NAME[receipt.kind]}")
        page.wait_for_timeout(POLL_MS * 2)
    return None


def _view_button(row):
    button = row.locator(VIEW_CSS)
    if button.count() != 1:
        return None
    label = " ".join(((button.get_attribute("aria-label") or "") + " " + (button.inner_text() or "")).split())
    return button if is_safe_control(label) else None


def press_view(page, button, css: str, what: str) -> None:
    """Press one receipt row's own View receipt. A button United has turned
    off is not pressed, and only that receipt is left (ReceiptLeft), for
    review and the next run."""
    try:
        pressing.click(page, button, css=css, words=words(), what=what,
                       step="view the receipt")
    except pressing.TurnedOff:
        raise ReceiptLeft("United turned off this receipt's View receipt button.") from None


def _take_receipt(page, receipt: Receipt, what: str) -> list[str]:
    """Press the row's View receipt and read the receipt the page gets.
    Every traveler's HTML, in United's order. Closes the tab it opened."""
    row = _row(page, receipt)
    if row is None or row.count() != 1:
        raise _Gone()
    button = _view_button(row)
    if button is None:
        raise _Gone()
    context = page.context
    before = set(context.pages)
    popups: list = []

    def opened(tab):
        popups.append(tab)

    page.on("popup", opened)
    try:
        with _Heard(page, RECEIPT_PATH) as heard:
            press_view(page, button, VIEW_CSS, what)
            waited = 0
            while not heard.got and waited < RECEIPT_WAIT_MS:
                page.wait_for_timeout(POLL_MS)
                waited += POLL_MS
            # The receipt's tab opens once its answer is in. It is waited
            # for, so it is closed here rather than left behind.
            waited = 0
            while heard.got and not popups and waited < POPUP_WAIT_MS:
                page.wait_for_timeout(POLL_MS)
                waited += POLL_MS
            page.wait_for_timeout(POLL_MS * 2)
            answers = list(heard.got)
    finally:
        try:
            page.remove_listener("popup", opened)
        except Exception:
            pass
        for tab in popups + [t for t in context.pages if t not in before]:
            if tab is not page:
                try:
                    if not tab.is_closed():
                        tab.close()
                except Exception:
                    pass
    if not answers:
        raise ListStopped("View receipt was pressed and united.com sent no receipt")
    if len(answers) != 1:
        raise ListStopped("View receipt was pressed and united.com sent more than one receipt")
    response = answers[0]
    sent = (_asked_by(response).get("RcptData") or {})
    if not isinstance(sent, dict) or str(sent.get("RcptId", "")).lower() != receipt.receipt_id:
        raise ListStopped("The receipt united.com sent was not the one pressed")
    status = response.status
    if status != 200:
        # A 401 or 403 here may be this receipt's own, so download_bill
        # weighs it against the list (refused.list_again), which stops the
        # run as signed out only when the list is refused too.
        if status in (428, 429):
            raise ListStopped("united.com is refusing receipt requests from this browser for now. "
                              "Wait a while, then Resume.")
        raise _Refused()
    data = _json_of(response, RECEIPT_BYTES)
    try:
        items = data["Data"]["GetRcptHTMLResp"]["Rcpt"]
    except Exception:
        raise _Refused() from None
    if isinstance(items, list) and items and all(i == {} for i in items):
        # United's own page then says "We're having trouble displaying
        # your receipt" and opens no tab. Seen for one reservation whose
        # tickets were exchanged, on every try.
        raise _Unavailable()
    if not isinstance(items, list) or not items or len(items) > MAX_TRAVELERS:
        raise _Refused()
    pages = [i.get("Html") for i in items if isinstance(i, dict)]
    if len(pages) != len(items) or not all(isinstance(h, str) and "<" in h for h in pages):
        raise _Refused()
    return pages


class _Gone(Exception):
    pass


class ReceiptLeft(Exception):
    """A receipt's own View receipt button was turned off and was not pressed."""


class _Refused(Exception):
    pass


class _Unavailable(Exception):
    pass


def background_tab(context):
    """A blank tab of the run's own, opened behind the person's tab so the
    browser does not come to the front of their screen. Chromium makes one
    over the DevTools protocol (Target.createTarget, background); Playwright's
    new_page always brings it forward. Falls back to tabs.new_tab when the
    browser will not."""
    browser = getattr(context, "browser", None)
    try:
        if browser is None or len(browser.contexts) != 1 or browser.contexts[0] is not context:
            raise LookupError()
        session = browser.new_browser_cdp_session()
        try:
            made = session.send("Target.createTarget", {"url": "about:blank", "background": True})
            target = made.get("targetId")
            tab = None
            for _ in range(40):
                tab = next((t for t in context.pages if _target_of(t) == target), None)
                if tab is not None:
                    break
                time.sleep(0.1)
            if tab is None:
                try:
                    session.send("Target.closeTarget", {"targetId": target})
                except Exception:
                    pass
                raise LookupError()
        finally:
            try:
                session.detach()
            except Exception:
                pass
        # Known from then on as a tab of the run's own, as tabs.new_tab's
        # are, which may be loaded anywhere the run needs it.
        tabs._OWN.add(tab)
        return tab
    except Exception:
        return tabs.new_tab(context)


def _target_of(tab) -> str:
    """The DevTools target id of a tab, "" when it cannot be read."""
    session = None
    try:
        session = tab.context.new_cdp_session(tab)
        return session.send("Target.getTargetInfo")["targetInfo"]["targetId"]
    except Exception:
        return ""
    finally:
        if session is not None:
            try:
                session.detach()
            except Exception:
                pass


def _printed(page, html: str) -> bytes:
    """United's HTML receipt as a PDF, drawn by the core with its scripts,
    frames and requests taken out (receipt_pdf.inert_pdf_bytes)."""
    return receipt_pdf.inert_pdf_bytes(page, html)


# Between two travelers' receipts printed as one document.
PAGE_BREAK = '<div style="break-after: page; page-break-after: always"></div>'


def _part(html: str, tag: str) -> str | None:
    found = re.search(rf"<{tag}\b[^>]*>(.*)</{tag}\s*>", html or "", re.I | re.S)
    return found.group(1) if found else None


def _together(pages: list[str]) -> str:
    """Every traveler's receipt HTML as one document, each from a new page,
    so one print holds them all. The receipts share United's template, so
    the first one's head styles them all."""
    if len(pages) == 1:
        return pages[0]
    head = _part(pages[0], "head") or ""
    bodies = [_part(html, "body") if _part(html, "body") is not None else html for html in pages]
    return ("<!DOCTYPE html><html><head>" + head + "</head><body>"
            + PAGE_BREAK.join("<div>" + body + "</div>" for body in bodies)
            + "</body></html>")


_LIGATURES = str.maketrans({"ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl"})


def _printed_number(text: str, number: str) -> bool:
    return bool(re.search(rf"(?<![A-Z0-9]){re.escape(number)}(?![A-Z0-9])", text, re.I))


def _printed_date(text: str, dates) -> bool:
    low = " ".join((text or "").translate(_LIGATURES).split()).lower()
    return any(identity.on_its_own(v.lower(), low) for d in dates if d for v in identity.date_variants(d))


def checks_out(text: str, receipt: Receipt) -> bool:
    """Whether one traveler's printed receipt names this receipt."""
    text = (text or "").translate(_LIGATURES)
    return (bool(re.search(r"thank you for choosing united", text, re.I))
            and bool(re.search(r"date\s+of\s+purchase", text, re.I))
            and any(_printed_number(text, n) for n in receipt.references)
            and _printed_date(text, receipt.dates))


def names_every_ticket(text: str, receipt: Receipt) -> bool:
    """Whether the printed receipts together show every traveler's ticket.
    United answers one receipt per traveler for some reservations and one
    for everyone for others."""
    return all(_printed_number(text, n) for n in receipt.tickets)


# Why the last download_bill saved nothing, one of REFUSALS.
REFUSALS = ("gone", "refused", "turned off", "unavailable", "unreadable", "wrong")
_REFUSAL = {"why": ""}


def last_refusal() -> str:
    return _REFUSAL["why"]


def _refuse(why: str) -> bool:
    _REFUSAL["why"] = why
    return False


def download_bill(page, date: str, out_path: Path, *, account: str, document_id: str) -> bool:
    _REFUSAL["why"] = ""
    if not account:
        raise ListStopped("Sign in to the MileagePlus account these receipts belong to.")
    if (_RUN.get("page") is not page or _RUN.get("account") != account
            or not _on_search(getattr(page, "url", ""))):
        _receipts(page)
    if _RUN.get("account") != account:
        raise ListStopped("Sign in to the MileagePlus account these receipts belong to.")
    receipt = _RUN["receipts"].get(document_id)
    if receipt is None or receipt.date != date:
        return _refuse("gone")
    noun = "flight reservation" if receipt.kind == TRAVEL else "purchase"
    what = f"the View receipt button of the {noun} of {receipt.date}"
    try:
        pages = _take_receipt(page, receipt, what)
    except _Gone:
        return _refuse("gone")
    except _Unavailable:
        return _refuse("unavailable")
    except ReceiptLeft:
        return _refuse("turned off")
    except _Refused:
        refused.list_again(lambda: collect_download_docs(page), SessionExpired, ListStopped)
        return _refuse("refused")
    for html in pages:
        data = _printed(page, html)
        try:
            text = " ".join(pdf_reader.page_texts(data))
        except Exception:
            return _refuse("unreadable")
        if not checks_out(text, receipt):
            return _refuse("wrong")
    if len(pages) > 1:
        data = _printed(page, _together(pages))
        try:
            text = " ".join(pdf_reader.page_texts(data))
        except Exception:
            return _refuse("unreadable")
    if not names_every_ticket(text, receipt):
        return _refuse("wrong")
    shared_folder.write_bytes(out_path, data)
    return True
