"""ALL Poppins Payroll addresses, page shapes and page behavior live here.

When Poppins changes its portal, repair this file only.

WHO THIS IS FOR
---------------
Poppins Payroll runs payroll for HOUSEHOLD employers: a family paying a
nanny or another household employee. The person signing in is the
employer. Every document here is the employer's copy: the employee's pay
stubs, the employee's W-2, and the employer's own W-3, Schedule H and
setup forms.

HOW THE PORTAL IS BUILT (surveyed 2026-11-27 on a signed-in employer account)
-----------------------------------------------------------------------------
* One host, https://app.poppinspayroll.com. The pages under /v2/ are drawn
  on the server and the session is an ordinary cookie, so a page can be
  asked for by its address. Every table is a <table> of
  <tr class="pp-table__row">, each cell carrying its column name in
  data-label.
* Pay stubs. /v2/payroll?year=YYYY lists a year's payrolls, newest first,
  about twenty a page, the next page linked rel="next" (?year=YYYY&page=N).
  The year menu links ?year=YYYY for every year the account has. A row has
  "Employee and pay period" (the employee's name, then the period, e.g.
  "November 14-20, 2026"), "Pay day" ("Nov 27, 2026"), amounts, "Status"
  and "Actions". A Complete row's action is Download,
  /v2/payroll/<payroll id>/paystub, which answers the PDF itself
  (pay-stub-<first name>-ending-<YYYY-MM-DD>.pdf). The payroll still open
  for editing has no stub, only "Edit payroll".
* Tax forms. /v2/documents?tab=employer and ?tab=employee list every year
  at once: "Document" (the form, and for an employee's form the employee's
  name beside it), "Year", "Category", "Description", "Status" ("Created
  Jan 21, 2026") and Download. /v2/documents/<id> answers a 302 to the
  stored PDF on the same host, /accounts/storage/<account>/<name>.pdf, the
  name saying the form and its period (er<n>.schedule_h.20251231.pdf,
  ee<n>.w2.20251231.pdf). The overtime premium report is
  /v2/documents/overtime-report/<employee id>/<year>, which answers the PDF
  itself.
* Tax payments. Poppins files Schedule H yearly and keeps NO document for
  the quarterly withdrawals it makes for federal, Illinois income and
  Illinois unemployment tax. /v2/taxes/federal and /v2/taxes/state each end
  in a "Payment History" table (id="payment-history"): "Period / Year",
  "Type", "Date", "Amount", "Status". This app saves those rows as a PDF
  of its own, headed as transcribed from Poppins on the day it was made,
  one per set of payments: a new one is made only when a new payment
  appears.

SAFETY (a site that can run payroll, move money and change bank accounts)
-------------------------------------------------------------------------
Strictly READ-ONLY. Nothing is ever pressed, typed or submitted. The app
opens the payroll list in the person's tab to see that they are signed
in, and everything else is a GET with the session's cookie, each address
checked by is_safe_url first and each redirect checked by it again
(paperpull_core.redirects). is_safe_url allows ONLY the list pages and
the three kinds of document address above, so:

  * /v2/payroll/<id>, a payroll's own page, is refused. It is the form
    that edits hours and pay, even for a payroll already paid.
  * Settings, Employees, Generate FSA receipt (a form that makes a
    document), Refer & Earn and sign-out are refused.

A row is taken only when its own link has the exact shape of a document
address, and a pay stub only when its row says Complete.
FORBIDDEN_CONTROL_RE refuses every control that runs, edits, approves or
pays, although nothing here presses one.
"""
from __future__ import annotations

import html as _html
import logging
import re
from dataclasses import dataclass, field
from datetime import date as _date, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlsplit, parse_qs

from paperpull_core import intake
from paperpull_core import redirects
from paperpull_core import shared_folder
from paperpull_core.urls import is_safe_url as _host_allows
from paperpull_core.urls import join as _join

log = logging.getLogger("poppins_docs.site")

HOST = "app.poppinspayroll.com"
BASE = f"https://{HOST}"

URLS = {
    "home": f"{BASE}/v2/home",
    "documents": f"{BASE}/v2/payroll",
    "payroll": f"{BASE}/v2/payroll",
    "employer_documents": f"{BASE}/v2/documents?tab=employer",
    "employee_documents": f"{BASE}/v2/documents?tab=employee",
    "federal_taxes": f"{BASE}/v2/taxes/federal",
    "state_taxes": f"{BASE}/v2/taxes/state",
    "login": f"{BASE}/login",
}

# ---------------------------------------------------------------------------
# Session / safety
# ---------------------------------------------------------------------------

LOGIN_URL_MARKERS = ["/login", "/signin", "/sign-in", "/sign_in", "/users/sign",
                     "/password", "/auth"]

SECURITY_CHALLENGE_MARKERS = [
    "verify your identity", "enter the code", "verification code",
    "one-time passcode", "two-factor", "multi-factor", "check your phone",
]

RATE_LIMIT_MARKERS = [
    "too many requests", "rate limit", "try again later",
    "temporarily unavailable", "http error 429", "unusual traffic",
]

# Controls that must NEVER be activated. Verb stems are anchored on both
# sides, so "Credit" never reads as "edit" (docs/adding-a-provider.md).
FORBIDDEN_CONTROL_RE = re.compile(
    r"\bedit(s|ed|ing)?\b|\bchang(e|es|ed|ing)\b|\bupdat(e|es|ed|ing)\b|"
    r"\brun\s+payroll\b|\bsubmit\b|\bapprov(e|es|ed|al|ing)\b|\bconfirm\b|"
    r"\bpay\s+(now|employee|bonus)\b|\bsave\b|\bdelete\b|\bremove\b|\bcancel\b|"
    r"\bgenerate\b|\bcreate\b|\badd\b|\binvite\b|\brefer\b|"
    r"direct\s+deposit|bank\s+account|routing\s+number|"
    r"\bwithhold|\bw-?4\b|\bi-?9\b|time\s+tracking|\bhours\b|"
    r"sign\s*out|log\s*out", re.I)

SAFE_DOC_CONTROL_RE = re.compile(
    r"\bdownload\b|pay\s*stub|paystub|\bw-?2\b|\bw-?3\b|schedule\s+h|"
    r"tax\s+form|payment\s+history", re.I)


def is_safe_control(name: str) -> bool:
    """Deny by default: clear the blocklist AND match the document allowlist."""
    name = (name or "").strip()
    if not name:
        return False
    if FORBIDDEN_CONTROL_RE.search(name):
        return False
    try:
        from paperpull_core.controls import SETTINGS_CONTROL_RE, AUTH_CONTROL_RE
        if SETTINGS_CONTROL_RE.search(name) or AUTH_CONTROL_RE.search(name):
            return False
    except Exception:
        pass
    return bool(SAFE_DOC_CONTROL_RE.search(name))


# The only paths this app may ask for. Everything else on the host,
# a payroll's own (editing) page above all, is refused.
_SAFE_PATHS = (
    re.compile(r"/"),                        # the root, which opens Home
    re.compile(r"/v2/(home|payroll|documents)"),
    re.compile(r"/v2/taxes/(federal|state)"),
    re.compile(r"/v2/payroll/\d+/paystub"),
    re.compile(r"/v2/documents/\d+"),
    re.compile(r"/v2/documents/overtime-report/\d+/\d{4}"),
    re.compile(r"/accounts/storage/\d+/[A-Za-z0-9_.-]+\.pdf"),
)

# Query keys a list page may carry. Anything else is refused, so a link
# that looks like a list but asks for something more is never followed.
_SAFE_QUERY_KEYS = {"year", "page", "tab", "employee_id",
                    "paymentsYear", "paymentsQuarter"}


def is_safe_url(url: str) -> bool:
    """Is this an address this app may ask for, or a tab it may work in?

    On https://app.poppinspayroll.com only (compared by parsed host, never
    by prefix), with a path that is exactly one of _SAFE_PATHS and a query
    of list keys only."""
    if not _host_allows(url or "", {HOST}, subdomains=False):
        return False
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    path = parts.path.rstrip("/") or "/"
    if not any(p.fullmatch(path) for p in _SAFE_PATHS):
        return False
    if parts.query:
        keys = set(parse_qs(parts.query, keep_blank_values=True))
        if not keys <= _SAFE_QUERY_KEYS:
            return False
    return True


def looks_like_login_url(url: str) -> bool:
    low = (url or "").lower()
    try:
        path = urlsplit(low).path
    except ValueError:
        path = low
    return any(m in path for m in LOGIN_URL_MARKERS)


def looks_signed_out(page) -> bool:
    if looks_like_login_url(page.url or ""):
        return True
    try:
        return page.locator("input[type='password']").count() > 0
    except Exception:
        return False


def detect_security_challenge(page) -> Optional[str]:
    """Names the passcode prompt or the throttling notice on screen, or None."""
    try:
        title = (page.title() or "").lower()
    except Exception:
        title = ""
    try:
        body = page.locator("body").inner_text(timeout=5000).lower()
    except Exception:
        body = ""
    hay = title + "\n" + body
    for marker in SECURITY_CHALLENGE_MARKERS:
        if marker in hay:
            return f"Sign-in verification step detected: '{marker}'"
    for marker in RATE_LIMIT_MARKERS:
        if marker in hay:
            return f"Possible rate limiting detected: '{marker}'"
    return None


class SessionExpired(Exception):
    """Poppins answered with its sign-in page, or refused the session."""


class Superseded(Exception):
    """A payment history no longer shows the payments it was listed with."""


# ---------------------------------------------------------------------------
# Reading the tables
# ---------------------------------------------------------------------------

@dataclass
class Cell:
    label: str
    # Each run of text in the cell with the class of the element it sits
    # in, so the employee's name and the period can be told apart.
    parts: List[Tuple[str, str]] = field(default_factory=list)

    @property
    def text(self) -> str:
        return " ".join(t for _, t in self.parts).strip()

    def part(self, cls: str) -> str:
        for c, t in self.parts:
            if cls in c.split():
                return t
        return ""


@dataclass
class Row:
    cells: Dict[str, Cell] = field(default_factory=dict)
    links: List[str] = field(default_factory=list)
    in_payment_history: bool = False

    def cell(self, label: str) -> Cell:
        return self.cells.get(label) or Cell(label)


@dataclass
class Read:
    rows: List[Row] = field(default_factory=list)
    links: List[Tuple[str, str]] = field(default_factory=list)  # (href, rel)
    has_password_field: bool = False


class _Reader(HTMLParser):
    """Rows of every pp-table, links, and whether a password field shows.
    Scripts, styles and svg are skipped whole."""

    _SKIP = {"script", "style", "svg", "noscript", "template"}
    _VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input",
             "link", "meta", "source", "track", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = Read()
        self._skip = 0
        self._classes: List[str] = []
        self._row: Optional[Row] = None
        self._cell: Optional[Cell] = None
        self._history_depth: Optional[int] = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in self._SKIP:
            self._skip += 1
            return
        if self._skip:
            return
        if tag == "input" and (a.get("type") or "").lower() == "password":
            self.out.has_password_field = True
        if tag in self._VOID:
            return
        self._classes.append(a.get("class") or "")
        if a.get("id") == "payment-history" and self._history_depth is None:
            self._history_depth = len(self._classes)
        cls = a.get("class") or ""
        if tag == "tr" and "pp-table__row" in cls.split():
            self._row = Row(in_payment_history=self._history_depth is not None)
        elif tag == "td" and self._row is not None and a.get("data-label"):
            self._cell = Cell(a["data-label"].strip())
            self._row.cells[self._cell.label] = self._cell
        elif tag == "a" and a.get("href"):
            href = a["href"]
            self.out.links.append((href, a.get("rel") or ""))
            if self._row is not None:
                self._row.links.append(href)

    def handle_endtag(self, tag):
        if tag in self._SKIP:
            self._skip = max(0, self._skip - 1)
            return
        if self._skip or tag in self._VOID:
            return
        if tag == "td":
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row.cells:
                self.out.rows.append(self._row)
            self._row = None
        if self._classes:
            if self._history_depth is not None and len(self._classes) == self._history_depth:
                self._history_depth = None
            self._classes.pop()

    def handle_data(self, data):
        if self._skip or self._cell is None:
            return
        text = re.sub(r"\s+", " ", data).strip()
        if text:
            self._cell.parts.append((self._classes[-1] if self._classes else "", text))


def read_html(html: str) -> Read:
    r = _Reader()
    r.feed(html or "")
    r.close()
    return r.out


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def parse_day(text: str) -> str:
    """'Nov 27, 2026', 'September 22, 2026' or 'Created Jan 21, 2026'
    -> '2026-11-27'. Anything else -> ''."""
    m = re.search(r"\b([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2}),\s*(\d{4})\b", text or "")
    if not m:
        return ""
    month = _MONTHS.get(m.group(1).lower())
    if not month:
        return ""
    try:
        return _date(int(m.group(3)), month, int(m.group(2))).isoformat()
    except ValueError:
        return ""


def parse_period_date(title: str):
    """(ISO date, period) from a title, for anything recorded without a
    date. Engine fallback only: every row here carries its own date."""
    day = parse_day(title)
    if day:
        return day, ""
    m = re.search(r"\b(20\d{2})\b", title or "")
    if m:
        return f"{m.group(1)}-12-31", f"Tax Year {m.group(1)}"
    return "", ""


# ---------------------------------------------------------------------------
# What a list holds
# ---------------------------------------------------------------------------

PAYSTUB = "paystub"
FORM = "form"
PAYMENTS = "payments"

PAYSTUB_HREF_RE = re.compile(r"/v2/payroll/(\d+)/paystub")
FORM_HREF_RE = re.compile(r"/v2/documents/(\d+)")
OVERTIME_HREF_RE = re.compile(r"/v2/documents/overtime-report/(\d+)/(\d{4})")

# Forms filed for the year they name, and so dated at its last day.
# Every other form (setup and authorization forms) is dated the day
# Poppins made it.
YEAR_END_FORM_RE = re.compile(r"\bw-?2c?\b|\bw-?3\b|schedule\s+h|overtime\s+premium|\b1099", re.I)

PAYMENT_KINDS = {
    "federal": ("Federal Tax Payment History", "federal_taxes"),
    "state": ("State Tax Payment History", "state_taxes"),
}


@dataclass
class RawDoc:
    """One document, in the shape the orchestrator records."""
    title: str
    date_text: str          # ISO date
    href: str               # the path it is fetched from
    kind: str
    document_id: str
    account: str = ""       # the employee a document is of, when it is one's
    period: str = ""
    text: str = ""


class ListStopped(Exception):
    """A list could not be read whole. Holds what was read before it."""

    def __init__(self, why: str, docs=None):
        super().__init__(why)
        self.docs = list(docs or [])


def paystubs_of(read: Read) -> List[RawDoc]:
    """The pay stubs one payroll list page offers: a Complete row whose own
    link is a paystub address. The open payroll has none and is passed by."""
    docs = []
    for row in read.rows:
        if "Pay day" not in row.cells:
            continue
        stub = next((h for h in row.links if PAYSTUB_HREF_RE.fullmatch(h)), "")
        if not stub:
            continue
        if row.cell("Status").text.strip().lower() != "complete":
            continue
        pay_day = parse_day(row.cell("Pay day").text)
        if not pay_day:
            raise ListStopped("a pay stub row has no pay day this app can read")
        who = row.cell("Employee and pay period")
        employee = who.part("pp-table__cell--title")
        period = who.part("pp-table__cell--description")
        payroll_id = PAYSTUB_HREF_RE.fullmatch(stub).group(1)
        docs.append(RawDoc(
            title=f"Pay Stub {period}".strip(),
            date_text=pay_day, href=stub, kind=PAYSTUB,
            document_id=f"paystub-{payroll_id}", account=employee,
            period=period))
    return docs


def years_of(read: Read) -> List[str]:
    """The years the payroll menu offers, newest first."""
    years = set()
    for href, _ in read.links:
        m = re.fullmatch(r"\?year=(\d{4})", _html.unescape(href))
        if m:
            years.add(m.group(1))
    return sorted(years, reverse=True)


def older_page_link(read: Read) -> str:
    """The rel="next" link of a list page, or ''."""
    for href, rel in read.links:
        if "next" in (rel or "").split():
            return _html.unescape(href)
    return ""


def forms_of(read: Read) -> List[RawDoc]:
    """The forms one Documents tab lists."""
    docs = []
    for row in read.rows:
        if "Document" not in row.cells or "Year" not in row.cells:
            continue
        link = next((h for h in row.links
                     if FORM_HREF_RE.fullmatch(h) or OVERTIME_HREF_RE.fullmatch(h)), "")
        if not link:
            continue
        cell = row.cell("Document")
        name = cell.part("pp-avatar-label__primary") or cell.text
        employee = cell.part("pp-avatar-label__secondary")
        year = row.cell("Year").text.strip()
        if not re.fullmatch(r"20\d{2}", year):
            raise ListStopped("a document row has no year this app can read")
        made = parse_day(row.cell("Status").text)
        day = f"{year}-12-31" if YEAR_END_FORM_RE.search(name) or not made else made
        m = FORM_HREF_RE.fullmatch(link)
        doc_id = f"form-{m.group(1)}" if m else \
            "overtime-%s-%s" % OVERTIME_HREF_RE.fullmatch(link).groups()
        docs.append(RawDoc(
            title=f"{name} {year}", date_text=day, href=link, kind=FORM,
            document_id=doc_id, account=employee, period=f"Tax Year {year}"))
    return docs


@dataclass
class Payment:
    period: str
    type: str
    day: str
    amount: str
    status: str


def payments_of(read: Read) -> List[Payment]:
    """The Payment History rows of a tax page, newest first as shown.

    The page draws the table three times, for wide, middle and narrow
    screens, the narrower ones folding Type and Date into the first cell.
    Only the wide one, the row with all five cells, is read, and a row
    drawn twice is kept once."""
    out, seen = [], set()
    for row in read.rows:
        if not row.in_payment_history:
            continue
        if not all(k in row.cells for k in ("Period / Year", "Type", "Date", "Amount")):
            continue
        day = parse_day(row.cell("Date").text)
        if not day:
            raise ListStopped("a tax payment row has no date this app can read")
        p = Payment(period=row.cell("Period / Year").text,
                    type=row.cell("Type").text, day=day,
                    amount=row.cell("Amount").text,
                    status=row.cell("Status").text)
        key = (p.period, p.type, p.day, p.amount)
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out


def payments_doc(kind: str, payments: List[Payment]) -> Optional[RawDoc]:
    """The payment history document for these rows: dated by the newest
    payment and known by it and the count, so the same rows make the same
    document and a new payment makes a new one."""
    if not payments:
        return None
    newest = max(p.day for p in payments)
    title, url_key = PAYMENT_KINDS[kind]
    return RawDoc(title=f"{title} {newest}", date_text=newest,
                  href=urlsplit(URLS[url_key]).path, kind=PAYMENTS,
                  document_id=f"{kind}-payments-{newest}-{len(payments)}",
                  period=f"Payments through {newest}")


# ---------------------------------------------------------------------------
# Asking Poppins
# ---------------------------------------------------------------------------

def _absolute(href: str, base: str = BASE + "/v2/payroll") -> str:
    # The core's join, which gives "" for a link a browser could read as
    # another place; is_safe_url then refuses it.
    return _join(base, _html.unescape(href or ""))


def _get(page, url: str):
    """GET an allowed address with the session, each redirect checked."""
    if not is_safe_url(url):
        raise RuntimeError(f"refusing to request an address this app does not read: {url}")
    resp = redirects.get(page.context.request, url, is_safe_url)
    return resp


def fetch_page(page, url: str) -> Read:
    """One list page, read. Raises SessionExpired when Poppins answers with its
    sign-in page or refuses the session."""
    resp = _get(page, url)
    if resp.status in redirects.REDIRECTS or resp.status in (401, 403):
        # A redirect is_safe_url refused is the sign-in page.
        raise SessionExpired(f"Poppins sent {url} elsewhere ({resp.status})")
    if not resp.ok:
        raise ListStopped(f"Poppins answered {resp.status} for a list page")
    read = read_html(intake.text_of(resp))
    if read.has_password_field:
        raise SessionExpired("Poppins answered with a sign-in page")
    return read


def goto_documents(page) -> bool:
    """Open the payroll list in the tab, True only once its history table
    is on the page (a row with a Pay day)."""
    page.goto(URLS["payroll"], wait_until="domcontentloaded", timeout=60000)
    try:
        # "attached", not visible: the page draws the table once per screen
        # width, and the first copy is the one hidden on a wide window.
        page.locator("td[data-label='Pay day']").first.wait_for(state="attached", timeout=15000)
    except Exception:
        return False
    return not looks_signed_out(page)


def collect_paystubs(page) -> List[RawDoc]:
    first = fetch_page(page, URLS["payroll"])
    years = years_of(first)
    if not years:
        raise ListStopped("the payroll list offers no year")
    docs: List[RawDoc] = []
    for year in years:
        url = f"{URLS['payroll']}?year={year}"
        for _ in range(60):  # no account has sixty pages of one year
            read = fetch_page(page, url)
            docs += paystubs_of(read)
            nxt = older_page_link(read)
            if not nxt:
                break
            url = _absolute(nxt, url)
        else:
            raise ListStopped(f"the {year} payroll list did not end", docs)
    return docs


def collect_forms(page) -> List[RawDoc]:
    docs: List[RawDoc] = []
    for key in ("employer_documents", "employee_documents"):
        docs += forms_of(fetch_page(page, URLS[key]))
    return docs


def collect_payment_histories(page) -> List[RawDoc]:
    docs = []
    for kind, (_, url_key) in PAYMENT_KINDS.items():
        doc = payments_doc(kind, payments_of(fetch_page(page, URLS[url_key])))
        if doc:
            docs.append(doc)
    return docs


def collect_documents(page) -> List[RawDoc]:
    """Every document the account offers, each once, newest first."""
    docs: List[RawDoc] = []
    try:
        docs += collect_paystubs(page)
        docs += collect_forms(page)
        docs += collect_payment_histories(page)
    except ListStopped as stop:
        raise ListStopped(str(stop), docs + stop.docs)
    seen, unique = set(), []
    for d in docs:
        if d.document_id not in seen:
            seen.add(d.document_id)
            unique.append(d)
    unique.sort(key=lambda d: (d.date_text, d.document_id), reverse=True)
    return unique


# ---------------------------------------------------------------------------
# Saving one
# ---------------------------------------------------------------------------

def _save_pdf(body: bytes, out_path) -> bool:
    if not body.startswith(b"%PDF"):
        log.warning("the answer was not a PDF")
        return False
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    shared_folder.write_bytes(out, body)
    return True


def download_pdf(page, href: str, out_path) -> bool:
    """A pay stub or a form: a GET of its own address, following a redirect
    only to the stored PDF on Poppins' own host."""
    url = _absolute(href)
    if not (PAYSTUB_HREF_RE.fullmatch(urlsplit(url).path)
            or FORM_HREF_RE.fullmatch(urlsplit(url).path)
            or OVERTIME_HREF_RE.fullmatch(urlsplit(url).path)):
        log.error("refusing to fetch an address that is not a document's")
        return False
    resp = _get(page, url)
    if not resp.ok:
        log.warning("the document answered %s", resp.status)
        return False
    try:
        body = intake.body(resp)
    except intake.TooLarge:
        return False
    return _save_pdf(body, out_path)


def payments_html(title: str, payments: List[Payment], made_on: str) -> str:
    """The page a payment history PDF is drawn from. Every value escaped."""
    e = _html.escape
    rows = "".join(
        f"<tr><td>{e(p.period)}</td><td>{e(p.type)}</td><td>{e(p.day)}</td>"
        f"<td class=n>{e(p.amount)}</td><td>{e(p.status)}</td></tr>" for p in payments)
    return (
        "<html><head><meta charset='utf-8'><style>"
        "body{font-family:Helvetica,Arial,sans-serif;font-size:11pt;margin:36px}"
        "h1{font-size:16pt;margin:0 0 4px}p{color:#444;margin:0 0 16px}"
        "table{border-collapse:collapse;width:100%}"
        "th,td{border-bottom:1px solid #ccc;padding:6px 8px;text-align:left}"
        "td.n{text-align:right}th{background:#f2f2f2}"
        "</style></head><body>"
        f"<h1>Poppins Payroll: {e(title)}</h1>"
        f"<p>Payment History transcribed from app.poppinspayroll.com on {e(made_on)}. "
        "Poppins keeps no document of these withdrawals.</p>"
        "<table><tr><th>Period / Year</th><th>Type</th><th>Date</th>"
        f"<th>Amount</th><th>Status</th></tr>{rows}</table></body></html>")


def download_payments(page, document_id: str, out_path, today: Optional[str] = None) -> bool:
    """A payment history: its tax page read again now, and drawn only when
    it still holds exactly the payments it was listed with."""
    from paperpull_core import receipt_pdf
    kind = (document_id or "").split("-", 1)[0]
    if kind not in PAYMENT_KINDS:
        return False
    title, url_key = PAYMENT_KINDS[kind]
    payments = payments_of(fetch_page(page, URLS[url_key]))
    now = payments_doc(kind, payments)
    if now is None or now.document_id != document_id:
        # A newer payment has appeared since it was listed. This one will
        # never be drawn as it was listed, and the newer one is its own
        # document, taken once it is listed.
        raise Superseded(document_id)
    html = payments_html(title, payments, today or _date.today().isoformat())
    receipt_pdf.print_html_inert_to_pdf(page, html, Path(out_path), base=BASE + "/")
    return Path(out_path).exists()


def download_document(page, doc, out_path) -> bool:
    if doc.document_id.split("-", 1)[0] in PAYMENT_KINDS:
        return download_payments(page, doc.document_id, out_path)
    return download_pdf(page, doc.href, out_path)
