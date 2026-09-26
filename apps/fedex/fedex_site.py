"""ALL fedex.com selectors, URLs, and page behavior live here.

When FedEx changes FedEx Billing Online, repair this file only.

STATUS: UNTESTED. Mapped 2026-09-25 from a signed-in FedEx login whose
shipping account is not connected to FedEx Billing Online, so no invoice
has ever been seen. Opening Billing Online on that login sends the page to
/register/connect-account (a form asking for the account number), which
this app never fills in. What is known comes from the app itself.

  - Billing Online is an Angular app at www.fedex.com/online/billing/,
    invoices at /online/billing/cbs/invoices.
  - Its data comes from api.fedex.com with an OAuth token the page gets
    for itself, and its config (/online/billing/cbs/config/
    CBSProperties.json) names invoiceAPI on api.fedex.com and the document
    download on www.fedex.com and documentapi.prod.fedex.com.
  - The first call it makes is POST /bill/v1/accounts/balancesummaries/
    retrieve, which answered 401 for the unconnected login.

What the invoice list and a PDF download look like is NOT known. So the
app opens the invoices page and keeps every answer the page itself
receives from api.fedex.com under /bill/, reads rows out of them by
looking for their fields, and saves a PDF only from a link a row carries
on a FedEx host. Diagnose records the shape of every answer it saw, field
names and types only, which is what the first tester's file is for.

FedEx runs bot protection that closes connections when asked too much, so
nothing here loops or retries, and the app pauses between documents.

SAFETY (Billing Online takes payments and disputes):
  Strictly READ-ONLY. This module opens the invoices page, keeps what the
  page receives, and fetches a PDF from a row's own link. It never pays,
  disputes, sets up autopay, connects an account, or edits any setting,
  and it clicks nothing at all. FORBIDDEN_CONTROL_RE and
  SAFE_DOC_CONTROL_RE are kept so the repo-wide guard tests cover this app
  the same as every other, and --diagnose uses them to grade the page.
"""
from __future__ import annotations

import base64
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
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

log = logging.getLogger("fedex_docs.site")

# Every host this app will read from. Anything else is refused.
ALLOWED_HOSTS = {"fedex.com"}

BASE = "https://www.fedex.com"
INVOICES_PAGE = BASE + "/online/billing/cbs/invoices"
BILLING_URL = INVOICES_PAGE  # the orchestrator records it as each document's source
URLS = {
    "home": BASE + "/en-us/logged-in-home.html",
    "login": BASE + "/secure-login/en-us/#/login-credentials",
    "documents": INVOICES_PAGE,
    "statements": INVOICES_PAGE,
}
CONNECT_PATH = "/register/connect-account"

LOGIN_URL_MARKERS = ["/secure-login", "/login", "/logout", "/signin"]

# How long captured answers are trusted before a download looks again.
_FRESH_SECONDS = 240

# ---------------------------------------------------------------------------
# HARD SAFETY GUARD. Tuned for a billing center. This app clicks nothing,
# so the guard grades controls for --diagnose and satisfies the repo-wide
# guard tests.
# ---------------------------------------------------------------------------
FORBIDDEN_CONTROL_RE = re.compile(
    r"(\bpay\b|payment|pay\s+now|autopay|auto\s*pay|dispute|refund|credit\s+request|"
    r"connect|link\s+account|add\s+account|\bjoin\b|enroll|register|"
    r"\bship\b|create\s+shipment|schedule|pickup|rate\b|redirect|order\s+supplies|"
    r"\bbank\b|\bcards?\b|wallet|"
    r"enable|disable|change\b|edit\b|update\b|modify|manage\b|set\s+up|"
    r"delete|remove|cancel|"
    r"password|profile\b|settings|preferences|administration|users?\b|"
    r"log\s*out|sign\s*out|"
    r"confirm|submit|continue|save\b|agree|accept|authorize|\bchat\b|contact\s+us)", re.I)

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

# What the invoices page looks like, for --diagnose only.
FALLBACK = {
    "doc_row": "table tbody tr, [role='row']",
    "doc_link": "a[href*='pdf'], a[href*='document']",
    "download_control": "button, a",
    "page_ready": "app-root, main",
    "next_page": "[aria-label*='Next' i]",
}

# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------
ISO_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})(?!\d)")
US_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
YEAR_RE = re.compile(r"\b(19|20)(\d{2})\b")


def parse_date(text):
    """An exact date in "2031-02-14..." or "02/14/2031" form, or None."""
    text = text or ""
    m = ISO_RE.search(text)
    if m:
        return _checked_date(f"{m.group(1)}-{m.group(2)}-{m.group(3)}", None)
    m = US_RE.search(text)
    if m:
        return _checked_date(f"{int(m.group(3)):04d}-{int(m.group(1)):02d}-{int(m.group(2)):02d}", None)
    return None


def parse_period_date(text: str) -> Tuple[Optional[str], str]:
    exact = parse_date(text)
    if exact:
        return exact, ""
    m = YEAR_RE.search(text or "")
    if m:
        year = int(m.group(1) + m.group(2))
        return f"{year:04d}-12-31", str(year)
    return None, ""


def iso_from_unix(value) -> str:
    """Unix seconds or milliseconds as the UTC calendar day, or ""."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return ""
    if value > 10_000_000_000:
        value = value / 1000
    if not 946684800 <= value <= 4102444800:
        return ""
    return datetime.fromtimestamp(value, tz=timezone.utc).strftime("%Y-%m-%d")


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
    if any(m in urlparse(url).path for m in LOGIN_URL_MARKERS) or "#/login" in url:
        return True
    try:
        if page.locator("input[type='password']").count() > 0:
            return True
    except Exception:
        pass
    return False


def not_connected(page) -> bool:
    """Billing Online sent the page to the form that connects a shipping
    account to it. That form is the account holder's to fill in."""
    return CONNECT_PATH in urlparse(page.url or "").path


def on_fedex(page) -> bool:
    return is_safe_url(page.url or "") and not looks_signed_out(page)


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
    """FedEx answered with a sign-in page instead of the thing asked for."""


class NeedsPerson(RuntimeError):
    """FedEx needs something only the account holder may do, such as
    connecting the shipping account to Billing Online. Never done here."""


def goto_documents(page) -> bool:
    """Be on a signed-in fedex.com page."""
    try:
        if on_fedex(page):
            return True
        page.goto(URLS["home"], wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(4000)
    except Exception as e:
        log.info("goto fedex failed: %s", e)
    return on_fedex(page)


# ---------------------------------------------------------------------------
# The answers the invoices page receives
# ---------------------------------------------------------------------------

def is_billing_answer(url: str) -> bool:
    u = urlparse(url or "")
    return u.hostname == "api.fedex.com" and u.path.startswith("/bill/")


_captured = {"at": 0.0, "answers": []}


def capture_answers(page, wait_ms: int = 25000, settle_ms: int = 4000) -> List[dict]:
    """Open the invoices page and keep every Billing Online answer the page
    receives, as {path, status, body}. Raises NeedsPerson when the page
    goes to the connect-account form instead."""
    if not on_fedex(page) and not goto_documents(page):
        raise SessionExpired("the FedEx tab is not on a signed-in fedex.com page")
    got = []

    def on_response(r):
        if not is_billing_answer(r.url):
            return
        try:
            body = r.json()
        except Exception:
            body = None
        got.append({"path": urlparse(r.url).path, "status": r.status, "body": body})

    page.on("response", on_response)
    try:
        page.goto(INVOICES_PAGE, wait_until="domcontentloaded", timeout=60000)
        waited, quiet = 0, 0
        while waited < wait_ms:
            before = len(got)
            page.wait_for_timeout(500)
            waited += 500
            quiet = quiet + 500 if len(got) == before else 0
            if got and quiet >= settle_ms:
                break
            if not_connected(page):
                break
    finally:
        page.remove_listener("response", on_response)
    if looks_signed_out(page):
        raise SessionExpired("FedEx showed a sign-in page")
    if not_connected(page):
        raise NeedsPerson("FedEx Billing Online is not connected to your shipping account")
    _captured.update(at=time.monotonic(), answers=got)
    return got


def _lists_in(body, depth=0):
    """Every list of objects inside an answer, however deep."""
    if depth > 5:
        return
    if isinstance(body, list):
        if body and all(isinstance(x, dict) for x in body):
            yield body
        for x in body[:3]:
            yield from _lists_in(x, depth + 1)
    elif isinstance(body, dict):
        for v in body.values():
            yield from _lists_in(v, depth + 1)


def _first(row: dict, *names):
    for n in names:
        v = row.get(n)
        if v not in (None, "", [], {}):
            return v
    return None


_LINK_KEYS = ("pdfUrl", "pdfURL", "pdf", "documentUrl", "documentURL", "downloadUrl",
              "downloadURL", "download_url", "url", "link", "href", "fileUrl")


def row_link(row: dict) -> str:
    for k in _LINK_KEYS:
        v = row.get(k)
        if isinstance(v, str) and is_safe_url(v):
            return v
        if isinstance(v, dict):
            inner = row_link(v)
            if inner:
                return inner
    return ""


def row_number(row: dict) -> str:
    v = _first(row, "invoiceNumber", "invoiceNo", "invoiceId", "documentNumber", "number", "id")
    return str(v) if isinstance(v, (str, int)) and str(v).strip() else ""


def row_date(row: dict) -> str:
    for k in ("invoiceDate", "invoiceDt", "billDate", "documentDate", "statementDate", "date",
              "createdDate", "created"):
        v = row.get(k)
        got = parse_date(v) if isinstance(v, str) else iso_from_unix(v)
        if got:
            return got
    return ""


def looks_like_invoice(row: dict) -> bool:
    keys = " ".join(row).lower()
    return "invoice" in keys and bool(row_number(row)) and bool(row_date(row))


def invoice_doc(row: dict) -> Optional[dict]:
    if not looks_like_invoice(row):
        return None
    return {"id": row_number(row), "date": row_date(row), "title": "Shipping Invoice",
            "link": row_link(row)}


def invoices_in(answers: List[dict]) -> List[dict]:
    """Every invoice-looking row across the answers, newest first, once
    each by its number."""
    seen, out = set(), []
    for a in answers:
        for rows in _lists_in(a.get("body")):
            for row in rows:
                d = invoice_doc(row)
                if d and d["id"] not in seen:
                    seen.add(d["id"])
                    out.append(d)
    out.sort(key=lambda d: (d["date"], d["id"]), reverse=True)
    return out


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
    return [RawDoc(title=d["title"], date_text=d["date"], href=d["link"],
                   document_id=d["id"], text=f"FedEx {d['title']}")
            for d in invoices_in(capture_answers(page))]


_FETCH_JS = r"""async (url) => {
  const r = await fetch(url, {credentials: "include"});
  const ct = r.headers.get("content-type") || "";
  if (!ct.includes("pdf") && !ct.includes("octet-stream")) return {status: r.status, ct, url: r.url};
  const buf = new Uint8Array(await r.arrayBuffer());
  let s = "";
  for (let i = 0; i < buf.length; i += 0x8000) s += String.fromCharCode.apply(null, buf.subarray(i, i + 0x8000));
  return {status: r.status, ct, url: r.url, b64: btoa(s)};
}"""


def _fetch_file(page, link: str) -> dict:
    """A file from its own link, from inside the page, or through the
    browser's own session when the page may not read that host."""
    if not is_safe_url(link):
        raise ValueError("refusing to fetch off fedex.com: %r" % redact(link))
    try:
        r = page.evaluate(_FETCH_JS, link)
    except Exception as e:
        log.info("in-page fetch refused (%s), asking through the session", str(e)[:80])
        resp = page.context.request.get(link, max_redirects=5)
        body = resp.body()
        r = {"status": resp.status, "ct": (resp.headers.get("content-type") or "").lower(),
             "url": resp.url, "b64": base64.b64encode(body).decode() if body[:5] == b"%PDF-" else ""}
    if r.get("status") in (401, 403) or not is_safe_url(r.get("url") or link):
        raise SessionExpired("FedEx answered %s, which means the session has ended" % r.get("status"))
    return r


def _fresh_link(page, document_id: str) -> str:
    if time.monotonic() - _captured["at"] > _FRESH_SECONDS:
        capture_answers(page)
    for d in invoices_in(_captured["answers"]):
        if d["id"] == document_id:
            return d["link"]
    return ""


def download_bill(page, dl_dir, iso_date: str, out_path, href: str = "",
                  title: str = "", document_id: str = "") -> bool:
    """Fetch one invoice's PDF from its own link and write it. A row with no
    link raises NeedsPerson, so it goes to manual review with a note to
    download it by hand and send a Diagnose file. `dl_dir` is unused."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if not goto_documents(page):
        return False
    link = _fresh_link(page, document_id) if document_id else ""
    link = link or (href if is_safe_url(href) else "")
    if not link:
        raise NeedsPerson("FedEx lists this invoice with no download link the app understands")
    r = _fetch_file(page, link)
    if not r.get("b64"):
        log.info("no PDF for %s: status %s, %s", iso_date, r.get("status"), r.get("ct"))
        return False
    data = base64.b64decode(r["b64"])
    if data[:5] != b"%PDF-":
        return False
    out_path.write_bytes(data)
    return True


# ---------------------------------------------------------------------------
# Diagnose. The shape of every Billing Online answer the page received,
# and the page's own controls with the guard's verdict on each. No
# screenshot, digits masked, nothing clicked and nothing downloaded.
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


def _masked_path(path: str) -> str:
    return re.sub(r"/[0-9A-Za-z_-]*\d{4,}[0-9A-Za-z_-]*", "/#", path or "")


def survey(page, dwell_ms: int = 2000, max_follow: int = 0) -> dict:
    """The invoices page and the shape of every Billing Online answer it
    received, without downloading anything. Nothing is clicked. Values
    never leave, only paths, statuses, field names and types."""
    report = {"accounts": [], "api": {}}
    try:
        answers = capture_answers(page)
        report["api"]["answers"] = [{"path": _masked_path(a["path"]), "status": a["status"],
                                     "shape": _shape(a["body"])} for a in answers[:20]]
        docs = invoices_in(answers)
        report["api"]["invoices"] = {"rows": len(docs),
                                     "with_a_link": sum(1 for d in docs if d["link"])}
    except NeedsPerson as e:
        report["api"]["not_connected"] = str(e)
    except Exception as e:
        report["error"] = str(e)[:200]
    report["page"] = _page_summary(page)
    return report


def collect_documents(page) -> List[RawDoc]:
    """Used only by --diagnose. The same list discovery reads, minus the
    numbers and links."""
    try:
        docs = collect_download_docs(page)
    except Exception:
        return []
    for d in docs:
        d.href = ""
        d.document_id = ""
    return docs


def expand_all(page) -> None:
    """Nothing to expand. The list comes from the page's own answers."""


def scroll_full_page(page, rounds: int = 0, delay_ms: int = 0) -> None:
    """Nothing to scroll. The list comes from the page's own answers."""
