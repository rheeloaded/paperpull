"""ALL paypal.com selectors, URLs, and page behavior live here.

When PayPal changes its site, repair this file only.

STATUS: mapped 2026-09-25 against a signed-in personal account and
verified end to end (list, PDF).

HOW THE SITE WORKS
  Statements & Taxes is a React app under /myaccount/statements. Its
  "All transactions" tab (/myaccount/statements/monthly) lists a monthly
  statement for each of the past three years. The page gets that list from
  its own JSON endpoint and each Download asks another for the PDF. This
  app makes the same two requests from inside the signed-in page, so the
  session never leaves the browser and nothing on the page is clicked.

    list      GET /myaccount/statements/api/statements
              -> data.statements[] of {year, details[] of {month "August",
                 date "20260801", title, monthNumber, year}}
    pdf       GET /myaccount/statements/api/statements/download
                  ?monthList=20260801&reportType=standard
              -> application/pdf, attachment, the statement itself.

  The page's own code builds exactly that address (monthList is the
  month's date, reportType "standard"). IDENTITY is the month.

NOT COVERED
  Tax forms (1099-K, 1099-INT, 1099-MISC, crypto) sit on the Tax documents
  tab, fed by /myaccount/statements/api/tax-documents. The account this was
  built on had none, so their download was never seen and is not built.
  Custom date-range statements are a request PayPal prepares, and are
  never submitted. Statements older than three years are not online.

  Landing on any other PayPal page that is not a sign-in page or a
  security check raises SentElsewhere, and the run stops once and names the
  page. It used to call the page a sign-in page and load the statements
  address four times.

BUSINESS ACCOUNTS
  Asked for the statements address, PayPal sends a business account to its
  settings page, /businessmanage/account/accountAccess (#61). Its
  statements are under Activity, All Reports and then Statements, at
  /reports/accountStatements, which this app loads by its address. See the
  business section below for what one tester's recording showed of that
  page and what it did not.

SAFETY (this account moves money):
  Strictly READ-ONLY. For a personal account this module makes the two
  requests above and nothing else, and it clicks nothing. For a business
  account it loads the statements page, reads the answer the page itself
  gets for its list, and presses only a statement row's own Download
  control, read twice and passed by is_safe_control, and the list's own
  next-page control. It never asks for the list itself, never requests,
  creates or schedules a report or a statement, and a CSV or any other
  kind of file is never pressed for. It never sends or requests money,
  transfers a balance, applies for credit, saves an offer, donates, or
  edits any setting. FORBIDDEN_CONTROL_RE and SAFE_DOC_CONTROL_RE are kept
  so the repo-wide guard tests cover this app the same as every other, and
  --diagnose uses them to grade the page's controls.
"""
from __future__ import annotations

import base64
import calendar
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import unquote, urlparse

from paperpull_core import blob_capture
from paperpull_core import capture
from paperpull_core.controls import SETTINGS_CONTROL_RE, AUTH_CONTROL_RE
from paperpull_core.controls import click_next_page, control_labels, is_next_control
from paperpull_core.delivery import DOWNLOAD, DocumentRequest
from paperpull_core.identity import Identity, date_variants, on_its_own, period_variants
from paperpull_core.identity import month_on_its_own

# Everything on its way into a diagnostic file goes through here. It
# lives in core because seventeen apps each had their own copy and
# they drifted into three different versions.
from paperpull_core.redact import redact, set_private_words  # noqa: F401
from paperpull_core.urls import is_safe_url as _host_allows
from paperpull_core.api_census import shape_of as _shape
from paperpull_core.dates import last_day as _last_day
from paperpull_core.dates import checked as _checked_date

log = logging.getLogger("paypal_docs.site")

# Every host this app will read from. Anything else is refused.
ALLOWED_HOSTS = {"paypal.com"}

BASE = "https://www.paypal.com"
STATEMENTS_PAGE = BASE + "/myaccount/statements/monthly"
LIST_API = BASE + "/myaccount/statements/api/statements"
DOWNLOAD_PATH = "/myaccount/statements/api/statements/download"
REPORT_TYPE = "standard"
BILLING_URL = STATEMENTS_PAGE  # the orchestrator records it as each document's source
URLS = {
    "home": BASE + "/myaccount/summary",
    "login": BASE + "/signin",
    "documents": STATEMENTS_PAGE,
    "statements": STATEMENTS_PAGE,
}

LOGIN_URL_MARKERS = ["/signin", "/signout", "/login", "/authflow", "/checkpoint",
                     "/stepup", "/challenge"]

# Where PayPal keeps a business account's settings. A business account asked
# for the statements address is sent here (#61). It is not a sign-in page,
# and there is nothing on it for this app to read.
BUSINESS_PATHS = ("/businessmanage/",)

# ---------------------------------------------------------------------------
# HARD SAFETY GUARD. Tuned for a wallet that moves money. For a personal
# account this app clicks nothing, and for a business account it presses a
# statement row's Download control and the list's next-page control, each
# only once this guard has passed it.
#
# The reports page that holds a business account's statements is also
# where a report is asked for. A statement or report a control would
# create, generate, prepare, schedule, request, get or run is never pressed
# for, and neither is a file in any kind other than a PDF. "Statement" alone
# used to let "Create statement" through.
# ---------------------------------------------------------------------------
FORBIDDEN_CONTROL_RE = re.compile(
    r"(\bsend\b|request\s+money|\brequest|transfer|withdraw|deposit|add\s+money|"
    r"\bpay\b|payment|pay\s+in\s+4|checkout|\bbuy\b|\bsell\b|crypto|"
    r"donate|charit|fundrais|reload\s+phone|xoom|"
    r"\bapply\b|credit\s+card|cashback|\bcards?\b|\bbanks?\b|link\s+a|"
    r"save\s+offer|\boffers?\b|rewards?\b|redeem|start\s+saving|savings|"
    r"enable|disable|change\b|edit\b|update\b|modify|manage\b|set\s+up|"
    r"delete|remove|cancel|close\s+account|dispute|report\s+a\s+problem|"
    r"custom\s+statement|file\s+taxes|"
    r"\bcreat|\bgenerat|\bprepar|\bschedul|\bget\b|\brun\b|\bnew\b|\bexport|"
    r"\bcustom|\bretry|\bresend|\bregenerat|"
    r"\bcsv\b|\bxlsx?\b|\bexcel\b|\btxt\b|\btext\s+file|tab[\s-]*delimited|"
    r"\bqif\b|\bqbo\b|\bofx\b|\biif\b|quicken|quickbooks|\bxml\b|\bjson\b|"
    r"password|passkey|\bpin\b|profile\b|settings|preferences|security|"
    r"notifications?\b|log\s*out|sign\s*out|"
    r"confirm|submit|save\b|agree|accept|authorize|\bchat\b|contact\s+us|"
    r"learn\s+more|dismiss)", re.I)

SAFE_DOC_CONTROL_RE = re.compile(
    r"(download|view|open|print|\bpdf\b|statement|document|all\s+transactions|"
    r"tax\s+(form|document)|1099|history|"
    r"see\s+(more|all|older)|show\s+(more|all|older)|load\s+more)", re.I)

SECURITY_CHALLENGE_MARKERS = [
    "enter the code", "verification code", "6-digit", "two-step",
    "two-factor", "authenticator", "confirm your identity", "verify your identity",
    "confirm it's you", "we sent a code", "are you a robot", "captcha",
    "security challenge", "check your email", "check your phone",
    "your session has expired", "log in again", "access denied",
]

RATE_LIMIT_MARKERS = [
    "too many requests", "rate limit", "try again later",
    "temporarily unavailable", "http error 429", "unusual traffic",
]

# What the statements page looks like, for --diagnose only.
FALLBACK = {
    "doc_row": ".statements-row",
    "doc_link": "[data-testid^='download-icon-']",
    "download_control": "[data-testid^='download-icon-']",
    "page_ready": "main, #root",
    "next_page": "[aria-label*='Next' i]",
}

# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------
_MONTH_NAMES = list(calendar.month_name)[1:]
_MONTHS = {m[:3].lower(): i + 1 for i, m in enumerate(_MONTH_NAMES)}
MONTH_YEAR_RE = re.compile(
    r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
    r"Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    r"\s+(\d{4})", re.I)
ISO_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})(?!\d)")
YEAR_RE = re.compile(r"\b(19|20)(\d{2})\b")
MONTH_KEY_RE = re.compile(r"^(\d{4})(\d{2})01$")


def parse_date(text):
    """An exact YYYY-MM-DD in the text, or None."""
    m = ISO_RE.search(text or "")
    if not m:
        return None
    return _checked_date(f"{m.group(1)}-{m.group(2)}-{m.group(3)}", None)


def parse_period_date(text: str) -> Tuple[Optional[str], str]:
    """A statement title's month as its last day. "Monthly Statement -
    August 2026" -> 2026-08-31."""
    text = text or ""
    exact = parse_date(text)
    if exact:
        return exact, ""
    m = MONTH_YEAR_RE.search(text)
    if m:
        month = _MONTHS[m.group(1)[:3].lower()]
        year = int(m.group(2))
        return f"{year:04d}-{month:02d}-{_last_day(year, month):02d}", m.group(0)
    m = YEAR_RE.search(text)
    if m:
        year = int(m.group(1) + m.group(2))
        return f"{year:04d}-12-31", str(year)
    return None, ""


def month_of(key: str) -> Optional[Tuple[int, int]]:
    """(year, month) from the list's "20260801", or None for anything else."""
    m = MONTH_KEY_RE.match(key or "")
    if not m:
        return None
    year, month = int(m.group(1)), int(m.group(2))
    if not (2000 <= year <= 2100 and 1 <= month <= 12):
        return None
    return year, month


def month_end(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}-{_last_day(year, month):02d}"


def download_href(key: str) -> str:
    return f"{DOWNLOAD_PATH}?monthList={key}&reportType={REPORT_TYPE}"


def key_for(title: str) -> str:
    """The list's month key back from a title, for a record without a link."""
    m = MONTH_YEAR_RE.search(title or "")
    if not m:
        return ""
    return f"{int(m.group(2)):04d}{_MONTHS[m.group(1)[:3].lower()]:02d}01"


# ---------------------------------------------------------------------------
# Session / safety
# ---------------------------------------------------------------------------

def is_safe_url(url: str) -> bool:
    """True only for an https URL on one of this provider's own hosts.

    The check itself lives in the core, so all of them answer the same way.
    This app keeps the hosts, which is the part that really is its own."""
    return _host_allows(url, ALLOWED_HOSTS)


def looks_signed_out(page) -> bool:
    url = (page.url or "").lower()
    if any(m in urlparse(url).path for m in LOGIN_URL_MARKERS):
        return True
    try:
        if page.locator("input[type='password']").count() > 0:
            return True
    except Exception:
        pass
    return False


def on_myaccount(page) -> bool:
    u = urlparse(page.url or "")
    return (is_safe_url(page.url or "") and u.hostname == "www.paypal.com"
            and u.path.startswith("/myaccount") and not looks_signed_out(page))


def detect_security_challenge(page) -> Optional[str]:
    """Names the passcode, CAPTCHA or throttling prompt on screen, or None.
    Visible text only. A page's source can carry every string its scripts
    could ever show, "verification code" included, on a normal day."""
    try:
        title = (page.title() or "").lower()
    except Exception:
        title = ""
    try:
        body = page.locator("body").inner_text(timeout=5000).lower()
    except Exception:
        body = ""
    hay = title + "\n" + body[:1500]
    for m in SECURITY_CHALLENGE_MARKERS:
        if m in hay:
            return f"Security challenge detected: '{m}'"
    for m in RATE_LIMIT_MARKERS:
        if m in hay:
            return f"Possible rate limiting detected: '{m}'"
    return None


def is_safe_control(name: str) -> bool:
    name = (name or "").strip()
    if not name:
        return False
    if FORBIDDEN_CONTROL_RE.search(name):
        return False
    if SETTINGS_CONTROL_RE.search(name) or AUTH_CONTROL_RE.search(name):
        return False
    return bool(SAFE_DOC_CONTROL_RE.search(name))


class SessionExpired(RuntimeError):
    """PayPal answered with a sign-in page instead of the thing asked for."""


class SentElsewhere(RuntimeError):
    """PayPal sent the tab to one of its own pages that is neither the
    statements nor a sign-in page nor a security check. A business
    account's settings is the one seen (#61). Loading the statements
    address again lands there again, and signing in changes nothing, so
    the run stops and names the page. `where` is its address as
    page_named() gives it, and `business` says it is a business account's.
    `reports` says the business statements page was tried as well and did
    not open."""

    def __init__(self, where: str, business: bool = False, reports: bool = False):
        super().__init__("PayPal opened %s instead of the statements page" % where)
        self.where = where
        self.business = business
        self.reports = reports


# One part of an address that is a plain word, "businessmanage" or
# "accountAccess". Anything else, a part with a digit in it above all, is
# where a site puts an account or a transaction, and is not repeated.
# The words of PayPal's own addresses a message may repeat. A check of each
# part's shape let any word through, a name in a vanity path among them, so
# only these are said and every other part is "..." (review of #61).
_SAYABLE_PARTS = frozenset({
    "myaccount", "businessmanage", "account", "accountaccess", "summary", "settings",
    "statements", "monthly", "custom", "reports", "accountstatements", "activity",
    "transactions", "details", "signin", "authflow", "checkpoint", "stepup",
    "challenge", "home", "business", "money", "wallet", "profile", "security",
    "notifications", "dashboard", "taxes", "tax", "webapps", "mep", "smarthelp", "help",
})


def page_named(url: str) -> str:
    """A page's address as a message may say it. The path only, and of that
    only the parts that are words of PayPal's own addresses, each other part
    as "...". The
    query is left off. A person may paste the message into a public issue,
    so it is built from what may be said rather than cleaned afterwards.
    The host is named only when it is not www.paypal.com."""
    try:
        u = urlparse(url or "")
        host = u.hostname or ""
    except ValueError:
        return "..."
    parts = [p if p.lower() in _SAYABLE_PARTS else "..." for p in u.path.split("/") if p]
    path = "/" + "/".join(parts)
    return path if host == "www.paypal.com" else "%s%s" % (host if is_safe_url(url) else "...", path)


def is_business_page(url: str) -> bool:
    """One of the pages where PayPal keeps a business account's settings."""
    try:
        path = urlparse(url or "").path.lower()
    except ValueError:
        return False
    return is_safe_url(url) and path.startswith(BUSINESS_PATHS)


def landed_elsewhere(page) -> str:
    """Where the tab is, as page_named() says it, when that is a PayPal page
    other than the statements and it is not a sign-in page or a security
    check. "" for anything else, so a sign-in or a check still goes to the
    person and a page off paypal.com is never named as PayPal's.

    Every page that was not the statements used to be called a sign-in
    page. A business account's settings was one, and the run went round the
    sign-in check and the statements address four times before it stopped
    with a traceback (#61)."""
    url = page.url or ""
    if not is_safe_url(url) or on_myaccount(page) or looks_signed_out(page):
        return ""
    if detect_security_challenge(page):
        return ""
    return page_named(url)


# ---------------------------------------------------------------------------
# Requests, made from inside the signed-in page
# ---------------------------------------------------------------------------
_FETCH_JS = r"""async (url) => {
  const r = await fetch(url, {credentials: "include", headers: {accept: "application/json, application/pdf"}});
  const ct = r.headers.get("content-type") || "";
  if (ct.includes("json")) {
    let j = null;
    try { j = await r.json(); } catch (e) { j = null; }
    return {status: r.status, ct, url: r.url, json: j};
  }
  if (!ct.includes("pdf")) return {status: r.status, ct, url: r.url};
  const buf = new Uint8Array(await r.arrayBuffer());
  let s = "";
  for (let i = 0; i < buf.length; i += 0x8000) s += String.fromCharCode.apply(null, buf.subarray(i, i + 0x8000));
  return {status: r.status, ct, url: r.url, b64: btoa(s)};
}"""


def _get(page, url: str) -> dict:
    """One GET from inside the page. A sign-in answer raises SessionExpired."""
    if not is_safe_url(url):
        raise ValueError("refusing to fetch off paypal.com: %r" % redact(url))
    if not on_myaccount(page):
        raise SessionExpired("the PayPal tab is not on a signed-in paypal.com page")
    r = page.evaluate(_FETCH_JS, url)
    landed = urlparse(r.get("url") or url).path.lower()
    if (r.get("status") in (401, 403) or not is_safe_url(r.get("url") or url)
            or any(m in landed for m in LOGIN_URL_MARKERS)):
        raise SessionExpired("PayPal answered %s, which means the session has ended"
                             % r.get("status"))
    return r


def goto_documents(page, fresh: bool = False) -> bool:
    """Be on the statements page. The requests are same-origin, so any
    signed-in page would serve them, and this is the one they come from.
    `fresh` loads it again even when the tab already shows it, because a
    tab left there still looks signed in after the session has timed out.
    A reload lands on the sign-in page, which the run can name."""
    try:
        if not fresh and on_myaccount(page) and "/myaccount/statements" in (page.url or ""):
            return True
        page.goto(STATEMENTS_PAGE, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)
    except Exception as e:
        log.info("goto statements failed: %s", e)
    return on_myaccount(page)


def statements_in(answer: dict) -> List[dict]:
    """Every month the list answer holds, newest first, as {key, year,
    month, title, date, href}. A month whose key does not parse is
    dropped, one listed twice is kept once."""
    seen, out = set(), []
    years = ((answer or {}).get("data") or {}).get("statements") or []
    for y in years:
        for m in (y or {}).get("details") or []:
            got = month_of(str((m or {}).get("date") or ""))
            if not got or got in seen:
                continue
            seen.add(got)
            year, month = got
            key = f"{year:04d}{month:02d}01"
            out.append({"key": key, "year": year, "month": month,
                        "title": f"Monthly Statement - {_MONTH_NAMES[month - 1]} {year}",
                        "date": month_end(year, month), "href": download_href(key)})
    out.sort(key=lambda s: s["key"], reverse=True)
    return out


def list_statements(page) -> List[dict]:
    r = _get(page, LIST_API)
    answer = r.get("json")
    if not isinstance(answer, dict) or "data" not in answer:
        raise SessionExpired("PayPal answered the statements list with another page")
    return statements_in(answer)


@dataclass
class RawDoc:
    title: str
    account: str = ""
    date_text: str = ""
    href: str = ""
    text: str = ""
    row_index: int = -1
    kind: str = "statement"
    # The days a business statement covers, as the CSV's Period column
    # shows them. Empty for a personal account's month.
    period: str = ""


def _listed(page) -> List[RawDoc]:
    return [RawDoc(title=s["title"], date_text=s["date"], href=s["href"],
                   text=f"PayPal {s['title']}")
            for s in list_statements(page)]


def collect_download_docs(page) -> List[RawDoc]:
    """Every monthly statement the site lists. `href` is the download
    address, built back from the month so nothing else rides along.

    The statements page is loaded once here. When it lands on a business
    account's settings page, the business statements page is loaded by its
    address instead and its own list is read (business_statements). Another
    PayPal page that is not a sign-in page or a security check raises
    SentElsewhere. A sign-in page, a check, or a page off paypal.com raises
    SessionExpired."""
    if not goto_documents(page, fresh=True):
        if is_business_page(page.url or ""):
            return business_statements(page, landed=page.url or "")
        where = landed_elsewhere(page)
        if where:
            raise SentElsewhere(where, business=is_business_page(page.url or ""))
        raise SessionExpired("PayPal showed a sign-in page" if looks_signed_out(page)
                             else "the PayPal statements page did not open")
    return _listed(page)


def parse_href(href: str) -> str:
    """The month key from a download address, or "" when it is not exactly
    one of this site's statement downloads."""
    u = urlparse(href or "")
    if u.scheme or u.netloc or u.path != DOWNLOAD_PATH:
        return ""
    m = re.fullmatch(r"monthList=(\d{8})&reportType=" + REPORT_TYPE, u.query or "")
    return m.group(1) if m and month_of(m.group(1)) else ""


def download_bill(page, dl_dir, iso_date: str, out_path, href: str = "",
                  title: str = "") -> bool:
    """Fetch one statement's PDF from inside the page and write it. A
    record with no link gets it back from its title. `dl_dir` is unused,
    kept for the orchestrator."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    key = parse_href(href) if href else ""
    key = key or key_for(title)
    got = month_of(key)
    if not got:
        log.info("no download link for %s", iso_date)
        return False
    if month_end(*got) != iso_date:
        log.info("link %s does not match the record's date %s", key, iso_date)
        return False
    if not goto_documents(page):
        return False
    r = _get(page, BASE + download_href(key))
    if "pdf" not in (r.get("ct") or "") or not r.get("b64"):
        log.info("no PDF for %s: status %s, %s", iso_date, r.get("status"), r.get("ct"))
        return False
    body = base64.b64decode(r["b64"])
    if body[:5] != b"%PDF-":
        return False
    out_path.write_bytes(body)
    return True


# ---------------------------------------------------------------------------
# Business accounts
#
# RECORDED on one tester's business account (Record, 0.43.0). Asked for the
# statements address, PayPal sends a business account to its settings
# page. Its statements are under Activity, All Reports and then the
# Statements card, at /reports/accountStatements. As that page loads it
# asks for its own list, a POST to /reports/apis/rux/reports/list, and the
# answer is a list of one object holding "reports" and "hasMore". Each
# report carries id, createdOn, duration, fileFormat, action, type and
# reportStatus, and the page drew a table row of six cells for each, the
# last holding a Download button. Pressed, the
# page's own script added a hidden link with a download mark and clicked
# it a fifth of a second later, and the browser downloaded the statement
# under a name holding what looks like the account's id and two stamps of
# fourteen digits. Nothing of PayPal's was asked for or waited on between.
#
# NOT KNOWN. A recording keeps no values, so what a status, a kind of file
# or a period looks like is not known, nor whether the link's address was
# the file's own or a blob the page built, nor whether the list's request
# carries a header the page adds. So the answer the page gets for its list
# is read as the page loads and this app never asks for the list itself. A
# row is taken only when its fileFormat reads as PDF, its reportStatus as
# ready and its duration as days this app can name, and anything it cannot
# read is refused and written down. The statement comes from the press a
# person would make, taken by the core's delivery and checked for its
# period in its own text. The downloaded file's own name is never kept,
# since it holds the account's id, and a report's id is never read.
# ---------------------------------------------------------------------------
REPORTS_PATH = "/reports/accountStatements"
REPORTS_PAGE = BASE + REPORTS_PATH
# Where on www.paypal.com a statement the page saved through a link of its
# own may be asked for again from, when no download arrived.
REPORTS_ROOT = "/reports/"
REPORTS_LIST_PATH = "/reports/apis/rux/reports/list"
# How long the business statements page has to hand over its list, and the
# moment more it is given once the list came, for the table to be drawn.
REPORTS_WAIT_MS = 30000
REPORTS_SETTLE_MS = 1500
# Pages of the list read at most, one press on its next-page control each.
REPORTS_MAX_PAGES = 20
# How long a press has for its statement to arrive. The tester's came in a
# fifth of a second.
BUSINESS_SETTLE_MS = 30000

# A row of the drawn list.
ROW_SELECTOR = "table tbody tr"

# What the business statements page looks like, for the journal and a
# failure file on a business account's run, in place of FALLBACK, which
# describes the personal statements page. Judged against this page those
# said the rows matched nothing and the selector was wrong. A next-page
# control is left out, since a list of one page has none.
BUSINESS_FALLBACK = {
    "doc_row": ROW_SELECTOR,
    "download_control": "table tbody tr button",
    "page_ready": "table",
}
# Where the list's own next-page control would be, in the table's footer or
# a region marked as pagination. Whether one of these pages forward at all
# is decided by its label alone (controls.is_next_control).
NEXT_PAGE_SELECTOR = ("table tfoot button, table tfoot a, table tfoot [role='button'], "
                      "[aria-label*='pagination' i] button, [aria-label*='pagination' i] a")

# A control that downloads one statement, matched whole. The tester's said
# Download.
DOWNLOAD_LABEL_RE = re.compile(r"^download(?:\s+(?:pdf|statement|report|file))?$", re.I)

# The words a row's status is read by. A status naming any word of the
# second set is not ready, whatever else it says, so NOT_READY is never
# read as ready. A status naming neither is one this app cannot read.
READY_WORDS = frozenset((
    "ready", "available", "complete", "completed", "success", "successful", "succeeded",
    "done", "generated", "finished", "downloadable"))
NOT_READY_WORDS = frozenset((
    "not", "pending", "progress", "processing", "queued", "requested", "request",
    "submitted", "scheduled", "generating", "preparing", "waiting", "running", "initiated",
    "failed", "failure", "fail", "error", "errors", "expired", "cancelled", "canceled",
    "unavailable", "rejected", "deleted", "incomplete"))
# A kind of file other than a PDF, named in a row or a report's fileFormat.
OTHER_KIND_RE = re.compile(r"\b(csv|xlsx?|excel|txt|tab[\s-]*delimited|qif|qbo|ofx|iif|"
                           r"quicken|quickbooks|xml|json)\b", re.I)

# What a report of the list is read as.
READY = "ready"
NOT_READY = "not ready"
OTHER_TYPE = "other type"
UNREAD_TYPE = "unread type"
UNREAD_STATUS = "unread status"
UNREAD_PERIOD = "unread period"
# A second ready statement known only by the day it was made, the same day
# as one already taken, so which is which cannot be told.
UNREAD_SAME_DAY = "unread same day"

# Why a statement was not pressed for, in words of this app's own.
NOT_LISTED = "the list does not hold it as ready"
NO_ROWS = "no rows were shown"
NO_ROW = "no row names its period"
MANY_ROWS = "more than one row names its period"
NO_CONTROL = "its row has no download control"
MANY_CONTROLS = "its row has more than one download control"

# The keys a duration may name its first and last day by.
_START_KEYS = frozenset(("start", "startdate", "startdatetime", "starttime", "from",
                         "fromdate", "begin", "begindate", "periodstart"))
_END_KEYS = frozenset(("end", "enddate", "enddatetime", "endtime", "to", "todate",
                       "until", "periodend"))

_MON = (r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|"
        r"aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)")
# A day, written any of the ways a list or a table might write one. ISO with
# or without a time after it, eight digits or a fourteen digit stamp,
# month/day/year, "Aug 31, 2031" and "31 Aug 2031".
_DAY_RE = re.compile(
    r"(?<!\d)(?P<iy>\d{4})-(?P<im>\d{2})-(?P<id>\d{2})(?!\d)"
    r"|(?<!\d)(?P<sy>\d{4})(?P<sm>\d{2})(?P<sd>\d{2})(?:\d{6})?(?!\d)"
    r"|(?<![\d/])(?P<um>\d{1,2})/(?P<ud>\d{1,2})/(?P<uy>\d{4})(?![\d/])"
    r"|(?<![a-z])(?P<nm>" + _MON + r")\.?\s+(?P<nd>\d{1,2}),?\s+(?P<ny>\d{4})(?!\d)"
    r"|(?<!\d)(?P<dd>\d{1,2})\s+(?P<dm>" + _MON + r")\.?,?\s+(?P<dy>\d{4})(?!\d)",
    re.I)
# A month with its year and no day, "August 2031", "2031-08" or "08/2031".
_MONTH_ONLY_RE = re.compile(
    r"(?<![a-z])(?P<nm>" + _MON + r")\.?,?\s+(?P<ny>\d{4})(?!\d)"
    r"|(?<![\d-])(?P<iy>\d{4})-(?P<im>\d{2})(?![\d-])"
    r"|(?<![\d/])(?P<um>\d{1,2})/(?P<uy>\d{4})(?![\d/])",
    re.I)


def _day(year, month, day) -> Optional[str]:
    """YYYY-MM-DD for a day that exists in this century, or None."""
    try:
        y, m, d = int(year), int(month), int(day)
    except (TypeError, ValueError):
        return None
    if not 2000 <= y <= 2100:
        return None
    return _checked_date("%04d-%02d-%02d" % (y, m, d), None)


def days_in(text) -> List[str]:
    """Every day a string names, as YYYY-MM-DD, in the order it names them.
    Empty when any of them is a day that does not exist, since a value
    holding one is not read past."""
    out = []
    for m in _DAY_RE.finditer(str(text or "")):
        g = m.groupdict()
        if g["iy"]:
            day = _day(g["iy"], g["im"], g["id"])
        elif g["sy"]:
            day = _day(g["sy"], g["sm"], g["sd"])
        elif g["uy"]:
            day = _day(g["uy"], g["um"], g["ud"])
        elif g["ny"]:
            day = _day(g["ny"], _MONTHS[g["nm"][:3].lower()], g["nd"])
        else:
            day = _day(g["dy"], _MONTHS[g["dm"][:3].lower()], g["dd"])
        if day is None:
            return []
        out.append(day)
    return out


def month_in(text) -> Optional[Tuple[int, int]]:
    """(year, month) when a string names one month with its year and no
    day, and None for anything else."""
    found = set()
    for m in _MONTH_ONLY_RE.finditer(str(text or "")):
        g = m.groupdict()
        if g["ny"]:
            year, month = int(g["ny"]), _MONTHS[g["nm"][:3].lower()]
        elif g["iy"]:
            year, month = int(g["iy"]), int(g["im"])
        else:
            year, month = int(g["uy"]), int(g["um"])
        if not (2000 <= year <= 2100 and 1 <= month <= 12):
            return None
        found.add((year, month))
    return found.pop() if len(found) == 1 else None


def _holds_digits(value) -> bool:
    """Whether a value has a digit in it anywhere, which is what a date or a
    count has and a word like Monthly does not."""
    if value is None or isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, str):
        return any(c.isdigit() for c in value)
    if isinstance(value, dict):
        return any(_holds_digits(v) for v in list(value.values())[:20])
    if isinstance(value, (list, tuple)):
        return any(_holds_digits(v) for v in list(value)[:20])
    return True


def _days_of(value, depth: int = 0) -> List[str]:
    """The days a value of the list's answer names. A string is read for its
    dates. An object is read for one start and one end, by their keys, and
    a list of two for one day each. A number names none, since a count of
    milliseconds says a day only in a time zone the answer does not give."""
    if isinstance(value, str):
        return days_in(value)
    pair = []
    if depth == 0 and isinstance(value, dict):
        starts = [v for k, v in value.items() if str(k).lower() in _START_KEYS]
        ends = [v for k, v in value.items() if str(k).lower() in _END_KEYS]
        if len(starts) == 1 and len(ends) == 1:
            pair = [starts[0], ends[0]]
    elif depth == 0 and isinstance(value, (list, tuple)) and len(value) == 2:
        pair = list(value)
    if pair:
        first, last = _days_of(pair[0], 1), _days_of(pair[1], 1)
        if len(first) == 1 and len(last) == 1:
            return [first[0], last[0]]
    return []


@dataclass(frozen=True)
class Period:
    """The days one business statement covers, its first and its last, or
    only the day PayPal made it when the list names no period for it."""
    start: str = ""
    end: str = ""
    created: str = ""

    @property
    def date(self) -> str:
        """The day the statement is filed under, its last."""
        return self.end or self.created

    def month(self) -> Optional[Tuple[int, int]]:
        """(year, month) when the days are one whole calendar month."""
        if not (self.start and self.end) or self.start[8:] != "01":
            return None
        year, month = int(self.start[:4]), int(self.start[5:7])
        return (year, month) if self.end == month_end(year, month) else None

    def title(self) -> str:
        got = self.month()
        if got:
            return f"Monthly Statement - {_MONTH_NAMES[got[1] - 1]} {got[0]}"
        if self.start:
            return f"Statement - {self.start} to {self.end}"
        return f"Statement - created {self.created}"

    def covers(self) -> str:
        """The days, as the CSV's Period column shows them."""
        return f"{self.start} to {self.end}" if self.start else f"created {self.created}"

    def href(self) -> str:
        """What a record keeps to find this statement again. The page and the
        days, never the report's id, which can carry the account's."""
        if self.start:
            return f"{REPORTS_PATH}#period={self.start}..{self.end}"
        return f"{REPORTS_PATH}#created={self.created}"

    def identity(self) -> Optional[Identity]:
        """What the statement's own text is checked against, its first day
        and its last, the same two kinds of fact for every statement
        whatever days it covers. A month for a monthly one and nothing for a
        custom one meant a monthly ending on the same day kept its month
        once the shared day stopped counting, and a custom statement that
        mentioned that month was taken for the monthly. None for a statement
        known only by the day it was made, since nothing says a statement
        prints that."""
        if not self.start:
            return None
        return Identity(date=self.end, start=self.start, kind="statement")

    def named_in(self, text: str) -> int:
        """How plainly a row's words name these days. 2 for the month or
        for the first day and the last, 1 for the last day alone, 0 for
        neither. Each is found only as a date of its own, so the 1st is not
        found inside the 11th. A month is looked for only by its name,
        August 2026 or Aug 2026, never as digits, since July written 07/2031
        is found inside the September day 09/07/2031 and the ISO 2031-07
        begins every ISO day of July."""
        low = (text or "").lower()

        def has(variants):
            return any(on_its_own(v, low) for v in variants)

        if not self.start:
            return 2 if has(date_variants(self.created)) else 0
        got = self.month()
        named = [v for v in period_variants("%04d-%02d" % got) if any(c.isalpha() for c in v)] \
            if got else []
        if any(month_on_its_own(v, low) for v in named):
            return 2
        last = has(date_variants(self.end))
        if last and has(date_variants(self.start)):
            return 2
        return 1 if last else 0


_REF_RE = re.compile(r"^" + re.escape(REPORTS_PATH) + r"#(?:period=(\d{4}-\d{2}-\d{2})\.\."
                     r"(\d{4}-\d{2}-\d{2})|created=(\d{4}-\d{2}-\d{2}))$")


def business_ref(href: str) -> Optional[Period]:
    """The days a record's link names when it is one of this app's business
    statements (Period.href), and None for anything else, a personal
    account's download address included."""
    m = _REF_RE.match(href or "")
    if not m:
        return None
    if m.group(3):
        made = _checked_date(m.group(3), None)
        return Period(created=made) if made else None
    first, last = _checked_date(m.group(1), None), _checked_date(m.group(2), None)
    return Period(start=first, end=last) if first and last and first <= last else None


def _words_of(value, depth: int = 0) -> str:
    """A value of the list's answer as lowercase words of letters, or ""
    when it holds none. A word joined to the next by a capital is two.
    An object or a list is read for its strings, one level down."""
    if isinstance(value, str):
        spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", value)
        return " ".join(re.findall(r"[a-z]+", spaced.lower()))
    if depth == 0 and isinstance(value, dict):
        parts = [_words_of(v, 1) for v in list(value.values())[:10]]
    elif depth == 0 and isinstance(value, (list, tuple)):
        parts = [_words_of(v, 1) for v in list(value)[:10]]
    else:
        return ""
    return " ".join(p for p in parts if p)


def type_of(row: dict) -> str:
    """"pdf" when a report's fileFormat says PDF and no other kind of file,
    "other" when it says anything else, and "" when it says nothing."""
    words = _words_of(row.get("fileFormat"))
    if not words:
        return ""
    return "pdf" if "pdf" in words.split() and not OTHER_KIND_RE.search(words) else "other"


def status_of(row: dict) -> str:
    """READY or NOT_READY by a report's reportStatus, or "" when it names
    neither, a status this app cannot read."""
    words = set(_words_of(row.get("reportStatus")).split())
    if words & NOT_READY_WORDS:
        return NOT_READY
    if words & READY_WORDS:
        return READY
    return ""


def period_of(row: dict) -> Optional[Period]:
    """The days a report covers, by its duration. When the duration names no
    day at all, the day PayPal made it, by its createdOn. None when either
    holds something this app cannot read, which is refused rather than
    guessed past."""
    duration = row.get("duration")
    if _holds_digits(duration):
        days = _days_of(duration)
        if len(days) == 2 and days[0] <= days[1]:
            return Period(start=days[0], end=days[1])
        if not days and isinstance(duration, str):
            got = month_in(duration)
            if got:
                return Period(start="%04d-%02d-01" % got, end=month_end(*got))
        return None
    made = _days_of(row.get("createdOn"))
    return Period(created=made[0]) if len(made) == 1 else None


def read_row(row) -> Tuple[str, Optional[Period]]:
    """What a report of the list is, and its days when it is a ready PDF
    statement. Its kind of file is read first, so a CSV is left alone
    whatever its status, then its status, then its days."""
    if not isinstance(row, dict):
        return UNREAD_TYPE, None
    kind = type_of(row)
    if not kind:
        return UNREAD_TYPE, None
    if kind != "pdf":
        return OTHER_TYPE, None
    status = status_of(row)
    if not status:
        return UNREAD_STATUS, None
    if status != READY:
        return NOT_READY, None
    period = period_of(row)
    if period is None:
        return UNREAD_PERIOD, None
    return READY, period


def row_facts(row: dict, verdict: str) -> dict:
    """What a refused report may say in a failure file. What it was read as,
    its status and its kind of file as lowercase words, and whether its
    duration held a date. Never its id and never its days."""
    return {"reads_as": verdict,
            "status": _words_of(row.get("reportStatus"))[:40],
            "type": _words_of(row.get("fileFormat"))[:40],
            "period": "named" if _holds_digits(row.get("duration")) else "none"}


class ReportsUnread(RuntimeError):
    """The business statements page opened, and the list its page gets as it
    loads never came, or came in a shape this app does not read. `where` is
    the page as page_named() gives it and `seen` how many answers came."""

    def __init__(self, where: str, seen: int = 0):
        super().__init__("PayPal's business statements page did not hand over its list")
        self.where = where
        self.seen = seen


def is_list_answer(url: str, method: str = "") -> bool:
    """Whether an answer is the business statements page's own list, a POST
    to that one address on www.paypal.com."""
    try:
        u = urlparse(url or "")
    except ValueError:
        return False
    return (is_safe_url(url) and u.hostname == "www.paypal.com"
            and u.path == REPORTS_LIST_PATH and str(method or "").upper() == "POST")


def reports_in(answer) -> Optional[Tuple[list, Optional[bool]]]:
    """The reports one list answer holds and whether PayPal says more
    follow, or None for an answer of another shape. The tester's answer was
    a list of one object holding both. hasMore is None when it is not a
    plain yes or no."""
    if isinstance(answer, list) and len(answer) == 1:
        answer = answer[0]
    if not isinstance(answer, dict):
        return None
    reports = answer.get("reports")
    if not isinstance(reports, list) or not all(isinstance(r, dict) for r in reports):
        return None
    more = answer.get("hasMore")
    return reports, (more if isinstance(more, bool) else None)


def _fingerprint(value) -> str:
    try:
        return json.dumps(value, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return repr(value)


class _ListAnswers:
    """The page's own answers to its list request while this is attached,
    each as (status, body), the body None when it could not be read as
    JSON. Nothing is asked for here. Guarded whole, since it runs inside
    Playwright's event loop."""

    def __init__(self, page):
        self.page = page
        self.got: list = []
        try:
            page.on("response", self._answered)
        except Exception:
            pass

    def _answered(self, response):
        try:
            if not is_list_answer(response.url, response.request.method):
                return
            body = None
            kind = ((response.headers or {}).get("content-type") or "").lower()
            if response.status == 200 and "json" in kind:
                try:
                    body = response.json()
                except Exception:
                    body = None
            self.got.append((response.status, body))
        except Exception:
            pass

    def stop(self) -> None:
        try:
            self.page.remove_listener("response", self._answered)
        except Exception:
            pass


class Reports:
    """What the business statements page answered for its list while this
    app watched, in one tab. `pages` holds each answer it could read as
    (reports, has_more), the last being the list the tab draws now. `seen`
    counts every answer and `unread` those it could not read. `forward`
    counts the presses on the list's next-page control."""

    def __init__(self, tab):
        self.tab = tab
        self.pages: list = []
        self.first = None
        self.seen = 0
        self.unread = 0
        self.forward = 0

    @property
    def listed(self) -> bool:
        return bool(self.pages)

    @property
    def drawn(self) -> list:
        return self.pages[-1][0] if self.pages else []

    @property
    def more(self) -> Optional[bool]:
        return self.pages[-1][1] if self.pages else None

    @property
    def whole(self) -> bool:
        """Every page of the list was read, the last saying no more follow."""
        return bool(self.pages) and self.more is False

    def take(self, got) -> int:
        """Add the answers a listener kept, and say how many were new pages.
        An answer the same as the one before it is the page asking again,
        not another page."""
        added = 0
        for status, body in got:
            self.seen += 1
            read = reports_in(body) if status == 200 else None
            if read is None:
                self.unread += 1
                continue
            if self.first is None:
                self.first = body
            if self.pages and _fingerprint(self.pages[-1][0]) == _fingerprint(read[0]):
                self.pages[-1] = read
                continue
            self.pages.append(read)
            added += 1
        return added


def on_reports(page) -> bool:
    """Whether the tab shows the business statements page, signed in."""
    url = page.url or ""
    try:
        u = urlparse(url)
    except ValueError:
        return False
    return (is_safe_url(url) and u.hostname == "www.paypal.com"
            and u.path.rstrip("/") == REPORTS_PATH and not looks_signed_out(page))


def _pause(page, ms: int) -> bool:
    """A wait inside Playwright, so the answers it is listening for are
    heard. False when the tab will not wait, a closed one."""
    try:
        page.wait_for_timeout(ms)
        return True
    except Exception:
        return False


def _wait_for_list(page, listening, wait_ms: int) -> bool:
    """Wait until the page's own list answer has come, then a moment more
    for the table. False at a sign-in page, a security check, a page other
    than the business statements page, or the time limit."""
    waited, step = 0, 500
    while waited < wait_ms:
        if listening.got:
            _pause(page, REPORTS_SETTLE_MS)
            return True
        if waited % 2000 == 0 and (not on_reports(page) or detect_security_challenge(page)):
            return bool(listening.got)
        if not _pause(page, step):
            break
        waited += step
    return bool(listening.got)


def open_reports(page, wait_ms: Optional[int] = None) -> Reports:
    """Load the business statements page by its address, never through its
    menus, and keep the answer the page itself gets for its list. The list
    is never asked for here. A session is proven by that list, so this
    waits for it, and stops waiting at a sign-in page or a security check."""
    view = Reports(page)
    listening = _ListAnswers(page)
    try:
        try:
            page.goto(REPORTS_PAGE, wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            log.info("goto business statements failed: %s", e)
        _wait_for_list(page, listening, REPORTS_WAIT_MS if wait_ms is None else wait_ms)
    finally:
        listening.stop()
    view.take(listening.got)
    return view


def next_reports_page(page) -> bool:
    """Page the business statements list forward once, by the control whose
    label says it pages forward and nothing else (controls.click_next_page).
    False when there is none, and nothing else is ever pressed for it."""
    return click_next_page(page, NEXT_PAGE_SELECTOR, settle_ms=500)


def more_reports(page, view: Reports) -> bool:
    """The list's next page, by its own next-page control, added to `view`.
    False when there is no such control or no new page came."""
    listening = _ListAnswers(page)
    try:
        if not next_reports_page(page):
            return False
        view.forward += 1
        _wait_for_list(page, listening, REPORTS_WAIT_MS)
    finally:
        listening.stop()
    return view.take(listening.got) > 0


class Listing(list):
    """A business account's statements, each a RawDoc, and what was left
    out. `whole` says every page of the list was read, `counts` how many
    reports were read as each kind (read_row), and `unread` the facts of
    each report refused because this app could not read it (row_facts).
    `view` is the list as the tab was left showing it."""

    def __init__(self, docs=(), whole=True, counts=None, unread=(), view=None):
        super().__init__(docs)
        self.whole = whole
        self.counts = dict(counts or {})
        self.unread = list(unread)
        self.view = view


def listing_of(view: Reports) -> Listing:
    """The statements every page of the list read holds, newest first, each
    once. A statement is kept by its days (Period.href), so one record
    stands for every report naming the same first and last day, which hold
    the same statement. Two reports known only by the day each was made
    are not known to be one, and the one after the first is refused as
    one this app could not tell apart, counted and written down with the
    rest it could not read, never let go of in silence."""
    rows, taken, docs, unread = set(), set(), [], []
    counts = {k: 0 for k in (READY, NOT_READY, OTHER_TYPE, UNREAD_TYPE, UNREAD_STATUS,
                             UNREAD_PERIOD, UNREAD_SAME_DAY)}
    for reports, _more in view.pages:
        for row in reports:
            mark = _fingerprint(row)
            if mark in rows:
                continue
            rows.add(mark)
            verdict, period = read_row(row)
            if verdict == READY and period.href() in taken and not period.start:
                verdict = UNREAD_SAME_DAY
            counts[verdict] += 1
            if verdict == READY:
                if period.href() in taken:
                    continue
                taken.add(period.href())
                docs.append(RawDoc(title=period.title(), date_text=period.date,
                                   href=period.href(), text="PayPal " + period.title(),
                                   period=period.covers()))
            elif verdict.startswith("unread"):
                unread.append(row_facts(row, verdict))
    docs.sort(key=lambda d: d.date_text, reverse=True)
    return Listing(docs, whole=view.whole, counts=counts, unread=unread, view=view)


def why_unlisted(page, view: Reports, landed: str = "") -> Exception:
    """Why the business statements list did not come, as the exception a run
    stops on. `landed` is the address the statements address landed on
    before, said when the business statements page did not open at all."""
    if looks_signed_out(page):
        return SessionExpired("PayPal showed a sign-in page")
    if detect_security_challenge(page):
        return SessionExpired("PayPal showed a security check")
    if on_reports(page):
        return ReportsUnread(page_named(page.url or ""), seen=view.seen)
    url = page.url or ""
    if not is_safe_url(url) and landed:
        # The page did not open at all, and the tab shows the browser's
        # own error. Where PayPal had sent it is what can be said.
        url = landed
    if is_safe_url(url):
        return SentElsewhere(page_named(url), business=is_business_page(url), reports=True)
    return SessionExpired("the PayPal business statements page did not open")


def business_statements(page, landed: str = "") -> Listing:
    """A business account's statements, from the answer its statements page
    gets for its list, every page of it, each later page by the list's own
    next-page control. Raises why_unlisted's exception when no list came."""
    view = open_reports(page)
    if not view.listed:
        raise why_unlisted(page, view, landed)
    while view.more is True and len(view.pages) < REPORTS_MAX_PAGES:
        if not more_reports(page, view):
            break
    return listing_of(view)


def _index_in(reports, ref: Period) -> int:
    """Where the ready statement `ref` names is in one page of the list, or
    -1 when it is not there as a ready PDF."""
    for i, row in enumerate(reports):
        verdict, period = read_row(row)
        if verdict == READY and period == ref:
            return i
    return -1


# The words of each row of the drawn list in order, read the way a person
# sees them.
ROWS_JS = r"""(sel) => [...document.querySelectorAll(sel)].map(
  (tr) => (tr.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 600))"""

# A control read with care. What it shows, its words as a person sees them,
# and every name it answers to, its own and those of anything inside it.
CAREFUL_JS = r"""(el) => {
  const tidy = (v) => String(v || '').replace(/\s+/g, ' ').trim();
  const named = [];
  const add = (v) => { v = tidy(v); if (v) named.push(v); };
  add(el.getAttribute('aria-label'));
  add(el.getAttribute('title'));
  const by = el.getAttribute('aria-labelledby');
  if (by) for (const id of by.split(/\s+/)) {
    const n = document.getElementById(id);
    if (n) add(n.innerText || n.textContent);
  }
  for (const inner of el.querySelectorAll('[aria-label], [title], img[alt]')) {
    add(inner.getAttribute('aria-label'));
    add(inner.getAttribute('title'));
    add(inner.getAttribute('alt'));
  }
  return {shows: tidy(el.innerText), named};
}"""


def _forbidden(label: str) -> bool:
    return bool(FORBIDDEN_CONTROL_RE.search(label) or SETTINGS_CONTROL_RE.search(label)
                or AUTH_CONTROL_RE.search(label))


def read_twice(el) -> Tuple[list, Optional[dict]]:
    """A control's labels read the old way, each label it carries
    (controls.control_labels), and read with care (CAREFUL_JS), None when it
    would not answer."""
    old = control_labels(el)
    try:
        careful = el.evaluate(CAREFUL_JS)
    except Exception:
        careful = None
    return old, careful if isinstance(careful, dict) else None


def is_download_control(old, careful) -> bool:
    """Whether a control is a statement's Download control by both of its
    readings. Read the old way, every label it carries passes the guard and
    one says Download. Read with care, what it shows says Download and
    passes the guard, and no name it answers to, its own or an icon's
    inside it, is one the guard forbids. A control that will not answer
    either way is not one."""
    if not old or careful is None:
        return False
    if not all(is_safe_control(label) for label in old):
        return False
    if not any(DOWNLOAD_LABEL_RE.match(label) for label in old):
        return False
    shows = str(careful.get("shows") or "")
    if not (DOWNLOAD_LABEL_RE.match(shows) and is_safe_control(shows)):
        return False
    return not any(_forbidden(str(name)) for name in careful.get("named") or [])


def _drawn_rows(page) -> List[str]:
    try:
        rows = page.evaluate(ROWS_JS, ROW_SELECTOR)
    except Exception:
        return []
    return [str(r or "") for r in rows] if isinstance(rows, list) else []


def _table_drawn(page, wait_ms: int = 10000) -> bool:
    try:
        page.locator(ROW_SELECTOR).first.wait_for(state="attached", timeout=wait_ms)
        return True
    except Exception:
        return False


def choose_row(rows, ref: Period) -> Tuple[int, int, str]:
    """Which drawn row is the statement's, as (its place among the rows, how
    plainly it names the days, why none is), found by the days the rows'
    words name and never by a position. A row naming a kind of file other
    than a PDF is never it. When more than one row names the days, the one
    naming them plainly, by its month's name or its first and last day, is
    it only when no other names them as plainly, and otherwise none is. The
    place a statement has in the list's answer decided between them once,
    and a table drawn in another order sent July's press to August's row."""
    named = [(i, ref.named_in(words)) for i, words in enumerate(rows)
             if not OTHER_KIND_RE.search(words)]
    named = [(i, level) for i, level in named if level]
    if len(named) > 1:
        plain = [(i, level) for i, level in named if level >= 2]
        if len(plain) != 1:
            return -1, 0, MANY_ROWS
        named = plain
    if not named:
        return -1, 0, NO_ROW
    return named[0][0], named[0][1], ""


def statement_request(page, ref: Period, view: Reports,
                      rivals=()) -> Tuple[Optional[DocumentRequest], str]:
    """Everything up to the press, for the business statement `ref` names,
    or None and why not, in words of this app's own.

    The statement is found in the list's answer, a later page of it pressed
    for when it is not on this one. Then its row in the drawn table, by the
    days its words name and never by a position (choose_row). In that row,
    the one control whose two readings both call it Download
    (is_download_control, which holds every label to is_safe_control) is
    the one pressed. At the moment of the press the rows are read again and
    the whole choice made again, and it has to come to the same row naming
    the days as plainly, and the control has to read the same."""
    while _index_in(view.drawn, ref) < 0:
        if view.more is not True or len(view.pages) >= REPORTS_MAX_PAGES \
                or not more_reports(page, view):
            return None, NOT_LISTED
    if not _table_drawn(page):
        return None, NO_ROWS
    chosen, level, why = choose_row(_drawn_rows(page), ref)
    if chosen < 0:
        return None, why
    row = page.locator("table tbody tr").nth(chosen)
    controls = row.locator("button, a[href], [role='button'], [role='link']")
    try:
        count = min(controls.count(), 12)
    except Exception:
        count = 0
    found = [controls.nth(j) for j in range(count)
             if is_download_control(*read_twice(controls.nth(j)))]
    if len(found) != 1:
        return None, (NO_CONTROL if not found else MANY_CONTROLS)
    control = found[0]

    def press():
        # Armed first, so a PDF the page builds for this press is kept.
        blob_capture.arm(page)
        # The choice made again on the rows as they are drawn now. A row
        # drawn again since it was chosen can hold another statement in the
        # same place, one that ends on the same day included, and a control
        # can be given another label.
        if choose_row(_drawn_rows(page), ref)[:2] != (chosen, level):
            raise RuntimeError("the rows no longer choose this statement's row")
        if not is_download_control(*read_twice(control)):
            raise RuntimeError("the control no longer reads as its Download")
        control.click(timeout=8000)

    return DocumentRequest(trigger=press, expect=ref.identity(), rivals=tuple(rivals),
                           close_new_tabs=True, hints=(DOWNLOAD,)), ""


def is_reports_file(href: str) -> bool:
    """Whether an address is one the business statements page may have
    saved a statement from, a path under /reports/ on www.paypal.com, with
    no step back out of it. Anything else the page's link pointed at is
    never asked for, whatever the host."""
    try:
        u = urlparse(href or "")
    except ValueError:
        return False
    if not (is_safe_url(href) and u.hostname == "www.paypal.com"
            and u.path.startswith(REPORTS_ROOT)):
        return False
    return not any(unquote(part) in (".", "..") for part in u.path.split("/"))


def taken_from_the_page(page, out_path) -> Optional[bytes]:
    """The statement a press handed over, read from the page, for when no
    download arrived. Only when the page clicked exactly one link with a
    download mark since the press was armed. A blob it made is read from
    the page's own memory (blob_capture), and an address under /reports/ on
    www.paypal.com (is_reports_file) is asked for once more from inside the
    page, a GET that follows no redirect (capture.ask_again). Nothing else
    is asked for. Only a PDF is kept, and never the name the page gave it,
    which holds the account's id."""
    links = blob_capture.saved_links(page) or []
    if len(set(links)) != 1:
        return None
    href = links[0]
    if href.startswith("blob:"):
        kept = blob_capture.take(page, urls=[href])
        return kept[0] if kept else None
    if not is_reports_file(href):
        return None
    held = Path(out_path).parent / (Path(out_path).name + ".asking")
    try:
        if capture.ask_again(page, [("GET", href)], held, is_safe_url):
            data = held.read_bytes()
            return data if data[:5] == b"%PDF-" else None
    except OSError as e:
        log.info("could not read what was asked for again: %s", e)
    finally:
        try:
            held.unlink(missing_ok=True)
        except OSError:
            pass
    return None


# ---------------------------------------------------------------------------
# Diagnose. What the list answers, as counts and shapes, and the page's own
# controls with the guard's verdict on each. No screenshot, digits masked,
# nothing clicked and nothing downloaded.
# ---------------------------------------------------------------------------

def _page_summary(page) -> dict:
    out = {"url": redact(page.url or ""), "title": ""}
    try:
        out["title"] = redact(page.title() or "")
    except Exception:
        pass
    try:
        heads = page.locator("h1, h2, h3").all_inner_texts()
        out["headings"] = [redact(h.strip())[:80] for h in heads if h.strip()][:30]
    except Exception:
        out["headings"] = []
    controls = []
    for role in ("link", "button", "tab"):
        try:
            loc = page.get_by_role(role)
            for i in range(min(loc.count(), 80)):
                el = loc.nth(i)
                try:
                    text = (el.inner_text(timeout=300) or "").strip() or \
                        (el.get_attribute("aria-label") or "").strip()
                except Exception:
                    text = ""
                if text:
                    controls.append({"role": role, "text": redact(text)[:60],
                                     "safe": is_safe_control(text)})
        except Exception:
            pass
    out["controls"] = controls
    return out


def survey(page, dwell_ms: int = 2000, max_follow: int = 0) -> dict:
    """The statements page and what the list answers, without downloading
    anything. Nothing is clicked."""
    report = {"page": _page_summary(page), "accounts": [], "api": {}}
    try:
        r = _get(page, LIST_API)
        answer = r.get("json") if isinstance(r.get("json"), dict) else {}
        items = statements_in(answer)
        report["api"]["statements"] = {
            "status": r.get("status"), "months": len(items),
            "newest": items[0]["date"] if items else "",
            "oldest": items[-1]["date"] if items else "",
            "shape": _shape(answer.get("data") or {})}
    except Exception as e:
        report["error"] = str(e)[:200]
    return report


def _value_shape(value):
    """A value of the list's answer the way Diagnose keeps it, a string as
    it is and an object's strings by key, so the file it is written to
    shapes every word off the list and every digit. A number is said to be
    one and nothing more."""
    if value is None:
        return "none"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return value[:80]
    if isinstance(value, dict):
        return {str(k)[:40]: _value_shape(v) if not isinstance(v, (dict, list)) else "nested"
                for k, v in list(value.items())[:10]}
    if isinstance(value, list):
        return [_value_shape(v) if not isinstance(v, (dict, list)) else "nested"
                for v in value[:4]]
    return type(value).__name__


def _row_survey(row) -> dict:
    """One report of the list as Diagnose keeps it. What it reads as, its
    status, kind of file, type and action as words, and its duration and
    createdOn as they are written. Never its id."""
    verdict, _period = read_row(row)
    row = row if isinstance(row, dict) else {}
    return {"reads_as": verdict,
            "status": _words_of(row.get("reportStatus")),
            "type": _words_of(row.get("fileFormat")),
            "kind": _words_of(row.get("type")),
            "action": _words_of(row.get("action")),
            "period": _value_shape(row.get("duration")),
            "created": _value_shape(row.get("createdOn"))}


# The drawn list's shape, and every link with a download mark on the page,
# by its address alone.
TABLE_JS = r"""(sel) => {
  const rows = [...document.querySelectorAll(sel)];
  return {tables: document.querySelectorAll('table').length,
          rows: rows.length,
          cells: rows.slice(0, 5).map((tr) => tr.children.length),
          links: [...document.querySelectorAll('a[download]')].slice(0, 5)
                   .map((a) => a.getAttribute('href') || '')};
}"""


def link_kind(href: str) -> dict:
    """What a link's address is, a blob of the page's own, a data address,
    an address of a site or one relative to the page, and its path when it
    has one. Never its query and never the name the link gives its file."""
    href = str(href or "")
    if not href:
        return {"kind": "none"}
    for kind in ("blob", "data"):
        if href.startswith(kind + ":"):
            return {"kind": kind}
    try:
        u = urlparse(href)
    except ValueError:
        return {"kind": "other"}
    if u.scheme in ("http", "https"):
        return {"kind": u.scheme, "on_paypal": is_safe_url(href), "path": u.path[:120]}
    if href.startswith("/"):
        return {"kind": "relative", "path": u.path[:120]}
    return {"kind": "other"}


def _control_survey(el) -> dict:
    old, careful = read_twice(el)
    return {"labels": old[:3],
            "shows": (careful or {}).get("shows", "")[:60] if careful else None,
            "named": ((careful or {}).get("named") or [])[:4] if careful else None,
            "safe": [is_safe_control(label) for label in old[:3]],
            "download": is_download_control(old, careful)}


def _ready_row_survey(page, view: Reports) -> dict:
    """For the first statement the list holds as ready, how many drawn rows
    name its days, what the first of those rows says, and what each control
    in it reads as, both ways. Nothing is pressed."""
    ref = None
    for row in view.drawn:
        verdict, period = read_row(row)
        if verdict == READY:
            ref = period
            break
    if ref is None:
        return {"found": False}
    rows = _drawn_rows(page)
    named = [i for i, words in enumerate(rows) if ref.named_in(words)]
    out = {"found": True, "monthly": ref.month() is not None, "rows_naming_it": len(named),
           "position": _index_in(view.drawn, ref)}
    if not named:
        return out
    out["row"] = rows[named[0]][:300]
    controls = page.locator(ROW_SELECTOR).nth(named[0]).locator(
        "button, a[href], [role='button'], [role='link']")
    try:
        count = min(controls.count(), 12)
    except Exception:
        count = 0
    out["controls"] = [_control_survey(controls.nth(j)) for j in range(count)]
    return out


def survey_business(page) -> dict:
    """The business statements page and what its list answers, for Diagnose,
    without pressing anything. The page is loaded by its address and its own
    list answer read as it loads. Kept are the answer's keys and types, how
    many reports came and whether more follow, each report's status, kind
    of file and days as written, how the drawn table is laid out, whether
    the page holds a link with a download mark and what kind of address it
    has, and for one ready statement what its Download control reads as,
    both ways. Never a report's id, and never a file's name. The file this
    goes into shapes every word off PaperPull's list and every digit."""
    view = open_reports(page)
    out = {"landed": page_named(page.url or ""), "on_statements_page": on_reports(page),
           "signed_out": looks_signed_out(page),
           "challenge": bool(detect_security_challenge(page)),
           "answers": view.seen, "answers_unread": view.unread, "listed": view.listed}
    if view.listed:
        out["answer"] = _shape(view.first)
        out["has_more"] = "unknown" if view.more is None else view.more
        out["rows"] = len(view.drawn)
        out["row_keys"] = sorted({str(k)[:40] for r in view.drawn for k in r})[:30]
        out["rows_read"] = [_row_survey(r) for r in view.drawn[:60]]
        out["counts"] = listing_of(view).counts
    try:
        table = page.evaluate(TABLE_JS, ROW_SELECTOR)
    except Exception:
        table = {}
    table = table if isinstance(table, dict) else {}
    out["table"] = {"tables": table.get("tables", 0), "rows": table.get("rows", 0),
                    "cells": table.get("cells", []),
                    "links": [link_kind(h) for h in table.get("links", [])]}
    try:
        nexts = page.locator(NEXT_PAGE_SELECTOR)
        out["table"]["next_controls"] = [
            {"labels": control_labels(nexts.nth(i))[:2],
             "pages_forward": any(is_next_control(x) for x in control_labels(nexts.nth(i)))}
            for i in range(min(nexts.count(), 6))]
    except Exception:
        out["table"]["next_controls"] = []
    out["ready_row"] = _ready_row_survey(page, view)
    return out


def collect_documents(page) -> List[RawDoc]:
    """Used only by --diagnose, which has opened the statements page
    already. The same list discovery reads, asked for from the page the tab
    is on. It used to load the statements address again first, one more
    trip to a business account's settings page (#61)."""
    try:
        return _listed(page)
    except Exception:
        return []


def expand_all(page) -> None:
    """Nothing to expand. The list comes from the page's own endpoint."""


def scroll_full_page(page, rounds: int = 0, delay_ms: int = 0) -> None:
    """Nothing to scroll. The list comes from the page's own endpoint."""
