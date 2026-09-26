"""ALL billing.ups.com selectors, URLs, and page behavior live here.

When UPS changes its Billing Center, repair this file only.

STATUS: mapped 2026-09-25 against a signed-in Billing Center account and
verified end to end (list, PDF).

HOW THE SITE WORKS
  Shipping invoices live in the UPS Billing Center, billing.ups.com, a
  React app (run for UPS by Paymentus) under /ups/billing/. My Invoices
  (/ups/billing/invoice) fills its table from the app's own JSON API. Every
  call carries session headers the page holds (x-csrf-token, x-sub-token,
  instance-id), so this app opens My Invoices, keeps the list answer and
  the headers the page itself sent, and asks for each PDF the same way.
  Nothing on the page is clicked.

    list      POST /api/v1/bc/invoice/list   body {}
              -> [ {id, accountNumber, invoiceNumber, invoiceDate ISO,
                    invoiceAmount, invoiceType "100", businessUnit "EBS",
                    countryCode, recordType "ACCOUNT", planNumber,
                    planInvoiceNumber, ...} ]  every invoice it keeps
    pdf       POST /api/v1/bc/invoice/download?fileType=pdf
              body {locale, invoices: [{countryCode, languageCode,
                    invoiceDate "DD/MM/YY", invoiceAmount, businessUnit,
                    recordType, accountNumber, planNumber, invoiceType,
                    invoiceNumber}]}
              -> application/pdf, attachment

  The PDF body is built exactly as the app's own code builds it. The one
  surprise is invoiceType, which the list gives as a code and the download
  wants as a word. The table is UPS's, read from its code (TYPE_WORDS
  below). Sending the code answers "Invoice not found".

  IDENTITY is the row's id, which UPS made up and which names no account.
  The invoice number carries the account number inside it, so it never
  goes into a filename.

NOT COVERED
  Supporting documents (freight bills, brokerage and import forms) and
  the CSV and XML versions of an invoice. Shipping History receipts on
  www.ups.com belong to shipments made from that login and are a
  different system.

SAFETY (the Billing Center takes payments):
  Strictly READ-ONLY. This module opens My Invoices, keeps what the page
  receives, and asks for invoice PDFs. It never pays, sets up automatic
  payments, disputes a charge, changes a plan, emails an invoice, or edits
  any setting, and it clicks nothing at all. FORBIDDEN_CONTROL_RE and
  SAFE_DOC_CONTROL_RE are kept so the repo-wide guard tests cover this app
  the same as every other, and --diagnose uses them to grade the page.
"""
from __future__ import annotations

import base64
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import urlparse

from paperpull_core.controls import SETTINGS_CONTROL_RE, AUTH_CONTROL_RE

# Everything on its way into a diagnostic file goes through here. It
# lives in core because seventeen apps each had their own copy and
# they drifted into three different versions.
from paperpull_core.redact import redact, set_private_words  # noqa: F401
from paperpull_core.urls import is_safe_url as _host_allows
from paperpull_core.api_census import shape_of as _shape
from paperpull_core.dates import checked as _checked_date

log = logging.getLogger("ups_docs.site")

# Every host this app will read from. Anything else is refused.
ALLOWED_HOSTS = {"ups.com"}

BASE = "https://billing.ups.com"
INVOICES_PAGE = BASE + "/ups/billing/invoice"
LIST_API = BASE + "/api/v1/bc/invoice/list"
DOWNLOAD_API = BASE + "/api/v1/bc/invoice/download?fileType=pdf"
BILLING_URL = INVOICES_PAGE  # the orchestrator records it as each document's source
URLS = {
    "home": BASE + "/home",
    "login": "https://www.ups.com/lasso/login",
    "documents": INVOICES_PAGE,
    "statements": INVOICES_PAGE,
}

LOGIN_URL_MARKERS = ["/lasso/", "/login", "/logout", "/signin", "/sign-in"]

# How long a captured list and its headers are trusted before looking again.
_FRESH_SECONDS = 300

# The download wants a word where the list gives a code. UPS's own table,
# from its code: small package (EBS) in the US and Canada says IMPORT or
# EXPORT, Supply Chain (SCS) names the mode, anything else is sent as is.
_EBS_IMPORT = {"200", "210", "211"}
_EBS_EXPORT = {"100", "110", "111", "120", "121"}
_SCS_WORDS = {"700": "Air", "750": "Air", "800": "Ocean", "850": "Ocean",
              "900": "Brokerage", "950": "Brokerage",
              "400": "Mail Innovations", "450": "Mail Innovations"}

# ---------------------------------------------------------------------------
# HARD SAFETY GUARD. Tuned for a billing center. This app clicks nothing,
# so the guard grades controls for --diagnose and satisfies the repo-wide
# guard tests.
# ---------------------------------------------------------------------------
FORBIDDEN_CONTROL_RE = re.compile(
    r"(\bpay\b|payment|pay\s+now|pay\s+bill|autopay|automatic\s+payments?|"
    r"dispute|refund|credit\s+request|"
    r"\bplans?\b|enroll|unenroll|sign\s+up|"
    r"email\s+invoice|email|share|"
    r"\bbank\b|\bcards?\b|wallet|"
    r"enable|disable|change\b|edit\b|update\b|modify|manage\b|set\s+up|"
    r"delete|remove|cancel|add\b|"
    r"password|profile\b|settings|preferences|administration|users?\b|"
    r"log\s*out|sign\s*out|"
    r"confirm|submit|save\b|agree|accept|authorize|\bchat\b|contact\s+us|"
    r"more\s+actions)", re.I)

SAFE_DOC_CONTROL_RE = re.compile(
    r"(download|view|open|print|\bpdf\b|statement|document|invoices?\b|"
    r"history|see\s+(more|all|older)|show\s+(more|all|older)|load\s+more)", re.I)

SECURITY_CHALLENGE_MARKERS = [
    "enter the code", "verification code", "6-digit", "two-step",
    "two-factor", "authenticator", "confirm your identity", "verify your identity",
    "we sent a code", "are you a robot", "captcha", "check your email",
    "check your phone", "your session has expired", "session timed out",
    "access denied",
]

RATE_LIMIT_MARKERS = [
    "too many requests", "rate limit", "try again later",
    "temporarily unavailable", "http error 429", "unusual traffic",
]

# What My Invoices looks like, for --diagnose only.
FALLBACK = {
    "doc_row": "table tbody tr",
    "doc_link": "table tbody tr svg",
    "download_control": "table tbody tr svg",
    "page_ready": "main, #root",
    "next_page": "[aria-label*='Next' i]",
}

# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------
ISO_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})(?!\d)")
YEAR_RE = re.compile(r"\b(19|20)(\d{2})\b")


def parse_date(text):
    """An exact YYYY-MM-DD in the text, or None."""
    m = ISO_RE.search(text or "")
    if not m:
        return None
    return _checked_date(f"{m.group(1)}-{m.group(2)}-{m.group(3)}", None)


def parse_period_date(text: str) -> Tuple[Optional[str], str]:
    text = text or ""
    exact = parse_date(text)
    if exact:
        return exact, ""
    m = YEAR_RE.search(text)
    if m:
        year = int(m.group(1) + m.group(2))
        return f"{year:04d}-12-31", str(year)
    return None, ""


def ups_date(iso: str) -> str:
    """2026-02-14 -> 14/02/26, the form the download takes."""
    y, m, d = iso.split("-")
    return f"{d}/{m}/{y[2:]}"


def js_number(value) -> str:
    """A number the way the page's own code writes it into the body,
    String(2.73) is "2.73" and String(27.0) is "27"."""
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return repr(value)
    return "" if value is None else str(value)


def type_word(row: dict) -> str:
    """The invoiceType the download wants, from the code the list gives."""
    code = str(row.get("invoiceType") or "")
    unit = row.get("businessUnit")
    if unit == "EBS" and row.get("countryCode") in ("US", "CA"):
        if code in _EBS_IMPORT:
            return "IMPORT"
        if code in _EBS_EXPORT:
            return "EXPORT"
    if unit == "SCS" and code in _SCS_WORDS:
        return _SCS_WORDS[code]
    return code


def download_body(row: dict, locale: str = "en-US") -> dict:
    """The download request for one list row, as the page builds it."""
    inv = {"countryCode": row.get("countryCode"),
           "languageCode": locale.split("-")[0].upper(),
           "invoiceDate": ups_date(row_date(row)),
           "invoiceAmount": js_number(row.get("invoiceAmount")),
           "businessUnit": row.get("businessUnit"),
           "recordType": row.get("recordType"),
           "accountNumber": row.get("accountNumber"),
           "planNumber": row.get("planNumber"),
           "invoiceType": type_word(row),
           "invoiceNumber": row.get("invoiceNumber")}
    if row.get("planInvoiceNumber"):
        inv["planInvoiceNumber"] = row["planInvoiceNumber"]
    return {"locale": locale, "invoices": [inv]}


def row_date(row: dict) -> str:
    """The invoice date as YYYY-MM-DD, or "". The list gives
    "2026-02-14T00:00:00.000Z", a calendar day at UTC midnight."""
    return parse_date(str(row.get("invoiceDate") or "")[:10]) or ""


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


def on_billing(page) -> bool:
    return (urlparse(page.url or "").hostname == "billing.ups.com"
            and is_safe_url(page.url or "") and not looks_signed_out(page))


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
    """UPS answered with a sign-in page instead of the thing asked for."""


class NeedsPerson(RuntimeError):
    """Kept for the orchestrator, which handles it for every document app
    cloned from this shape. UPS has no step like that seen so far."""


def goto_documents(page) -> bool:
    """Be on a signed-in Billing Center page."""
    try:
        if on_billing(page):
            return True
        page.goto(URLS["home"], wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(5000)
    except Exception as e:
        log.info("goto billing failed: %s", e)
    return on_billing(page)


# ---------------------------------------------------------------------------
# The list, kept from what the page itself receives
# ---------------------------------------------------------------------------

# Headers the page sent that are worth sending again. Browser-managed ones
# (cookie, user-agent, sec-*) are left to the browser.
_KEEP_HEADERS = re.compile(r"^(accept|content-type|x-csrf-token|x-sub-token|x-api-token-sub|"
                           r"instance-id)$", re.I)

_captured = {"at": 0.0, "rows": None, "headers": {}}


def _is_all_invoices(request) -> bool:
    """The call that lists every invoice. The page also asks for a
    filtered list with a status, which is not the whole history."""
    u = urlparse(request.url)
    if u.hostname != "billing.ups.com" or u.path != "/api/v1/bc/invoice/list":
        return False
    return (request.post_data or "").strip() in ("{}", "")


def capture_list(page, wait_ms: int = 25000) -> Tuple[Optional[list], dict]:
    """Open My Invoices and keep the list answer and the headers the page
    sent with it."""
    if not on_billing(page) and not goto_documents(page):
        raise SessionExpired("the UPS tab is not on a signed-in Billing Center page")
    got = {}

    def on_response(r):
        if "rows" in got or not _is_all_invoices(r.request):
            return
        try:
            body = r.json()
        except Exception:
            body = None
        try:
            headers = r.request.all_headers()
        except Exception:
            headers = dict(r.request.headers)
        got["status"] = r.status
        got["headers"] = {k: v for k, v in headers.items() if _KEEP_HEADERS.match(k)}
        got["rows"] = body if isinstance(body, list) else None

    page.on("response", on_response)
    try:
        page.goto(INVOICES_PAGE, wait_until="domcontentloaded", timeout=60000)
        waited = 0
        while "rows" not in got and waited < wait_ms:
            page.wait_for_timeout(500)
            waited += 500
    finally:
        page.remove_listener("response", on_response)
    if looks_signed_out(page) or got.get("status") in (401, 403):
        raise SessionExpired("UPS showed a sign-in page")
    rows = got.get("rows")
    _captured.update(at=time.monotonic(), rows=rows, headers=got.get("headers") or {})
    return rows, got.get("headers") or {}


def invoice_doc(row: dict) -> Optional[dict]:
    doc_id = row.get("id")
    if not isinstance(doc_id, str) or not doc_id or not row.get("invoiceNumber"):
        return None
    date = row_date(row)
    if not date:
        return None
    return {"id": doc_id, "date": date, "title": "Shipping Invoice", "row": row}


def list_invoices(page) -> List[dict]:
    rows, _headers = capture_list(page)
    if rows is None:
        log.info("My Invoices never received its list")
        return []
    docs = [d for d in (invoice_doc(r) for r in rows if isinstance(r, dict)) if d]
    docs.sort(key=lambda d: (d["date"], d["id"]), reverse=True)
    return docs


@dataclass
class RawDoc:
    title: str
    account: str = ""
    date_text: str = ""
    href: str = ""
    text: str = ""
    row_index: int = -1
    kind: str = "statement"
    document_id: str = ""


def collect_download_docs(page) -> List[RawDoc]:
    return [RawDoc(title=d["title"], date_text=d["date"], document_id=d["id"],
                   text=f"UPS {d['title']}")
            for d in list_invoices(page)]


_FETCH_JS = r"""async ([url, headers, body]) => {
  const r = await fetch(url, {method: "POST", credentials: "include", headers, body: JSON.stringify(body)});
  const ct = r.headers.get("content-type") || "";
  if (!ct.includes("pdf")) {
    let j = null;
    try { j = await r.json(); } catch (e) { j = null; }
    return {status: r.status, ct, url: r.url, json: j};
  }
  const buf = new Uint8Array(await r.arrayBuffer());
  let s = "";
  for (let i = 0; i < buf.length; i += 0x8000) s += String.fromCharCode.apply(null, buf.subarray(i, i + 0x8000));
  return {status: r.status, ct, url: r.url, b64: btoa(s)};
}"""


def _post(page, url: str, headers: dict, body: dict) -> dict:
    if not is_safe_url(url):
        raise ValueError("refusing to fetch off ups.com: %r" % redact(url))
    if not on_billing(page):
        raise SessionExpired("the UPS tab is not on a signed-in Billing Center page")
    r = page.evaluate(_FETCH_JS, [url, headers, body])
    if r.get("status") in (401, 403) or not is_safe_url(r.get("url") or url):
        raise SessionExpired("UPS answered %s, which means the session has ended" % r.get("status"))
    return r


def _row_for(page, document_id: str) -> Tuple[Optional[dict], dict]:
    if time.monotonic() - _captured["at"] > _FRESH_SECONDS or _captured["rows"] is None:
        capture_list(page)
    for row in _captured["rows"] or []:
        if isinstance(row, dict) and row.get("id") == document_id:
            return row, _captured["headers"]
    return None, _captured["headers"]


def download_bill(page, dl_dir, iso_date: str, out_path, href: str = "",
                  title: str = "", document_id: str = "") -> bool:
    """Ask for one invoice's PDF from inside the page and write it. The row
    is looked up fresh, with the headers the page sent, so a record needs
    nothing but its id. `dl_dir` and `href` are unused."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if not document_id:
        log.info("no invoice id for %s", iso_date)
        return False
    if not goto_documents(page):
        return False
    row, headers = _row_for(page, document_id)
    if row is None:
        log.info("invoice for %s is no longer listed", iso_date)
        return False
    if row_date(row) != iso_date:
        log.info("the listed invoice's date does not match the record's %s", iso_date)
        return False
    r = _post(page, DOWNLOAD_API, headers, download_body(row))
    if not r.get("b64"):
        log.info("no PDF for %s: status %s, %s", iso_date, r.get("status"), r.get("ct"))
        return False
    data = base64.b64decode(r["b64"])
    if data[:5] != b"%PDF-":
        return False
    out_path.write_bytes(data)
    return True


# ---------------------------------------------------------------------------
# Diagnose. What the list answers, as counts and a shape, and the page's
# own controls with the guard's verdict on each. No screenshot, digits
# masked, nothing clicked and nothing downloaded.
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
    """My Invoices and the shape of the list it received, without
    downloading anything. Nothing is clicked. Values never leave, only
    field names, types and counts."""
    report = {"accounts": [], "api": {}}
    try:
        rows, headers = capture_list(page)
        rows = rows or []
        report["api"]["invoices"] = {
            "received": rows is not None,
            "rows": len(rows),
            "readable": sum(1 for r in rows if isinstance(r, dict) and invoice_doc(r)),
            "type_codes": sorted({str(r.get("invoiceType")) for r in rows if isinstance(r, dict)}),
            "business_units": sorted({str(r.get("businessUnit")) for r in rows if isinstance(r, dict)}),
            "headers_kept": sorted(headers),
            "shape": _shape(rows[:1]),
        }
        report["page"] = _page_summary(page)
    except Exception as e:
        report["error"] = str(e)[:200]
    return report


def collect_documents(page) -> List[RawDoc]:
    """Used only by --diagnose. The same list discovery reads, minus the
    ids, which are opaque but still point into an account."""
    try:
        docs = collect_download_docs(page)
    except Exception:
        return []
    for d in docs:
        d.document_id = ""
    return docs


def expand_all(page) -> None:
    """Nothing to expand. The list comes from the page's own answer."""


def scroll_full_page(page, rounds: int = 0, delay_ms: int = 0) -> None:
    """Nothing to scroll. The list comes from the page's own answer."""
