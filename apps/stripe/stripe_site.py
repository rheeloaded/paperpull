"""ALL stripe.com selectors, URLs, and page behavior live here.

When Stripe changes its Dashboard, repair this file only.

STATUS: UNTESTED. Mapped 2026-09-25 against a signed-in merchant account
that had no invoices, no tax forms and no payouts yet, so every list was
empty. What is known is how each list is asked for and what the Dashboard's
own code reads from an invoice row. What a tax form row holds is not known
yet, so it is read by looking for its fields rather than naming them, and
Diagnose records the shape of both lists for the first person who runs it.

HOW THE SITE WORKS
  The Dashboard is a React app on dashboard.stripe.com, every page under
  /acct_<id>/. It loads its data with same-origin requests that carry the
  session's own headers (a CSRF token, stripe-account, stripe-version, and
  for /v1/ paths an authorization header the page holds in memory). Those
  are not reproducible from outside the page, so this app opens the page
  that shows a list and keeps the answer the page itself receives. Nothing
  on the page is clicked.

    Fee invoices   Settings, Plans and fees, Invoice history
                   /settings/plans-and-fees/invoice-history
                   answer from /v1/settings/plans_and_fees/invoice_history_documents
                   {data[], has_more, total_count}. The page's code reads a
                   row as description, invoiceNumber, periodStartInclusive
                   and periodEndExclusive (unix seconds), created, type
                   (VatInvoice, CfdiInvoice, ...), status, token and link,
                   the address its Download action opens in a new tab.
    Tax forms      Settings, Compliance and documents, My documents
                   /settings/documents
                   answer from /ajax/tax_documents {object list, data[],
                   has_more, total_count}. Row fields unknown.

  More pages than the first are asked for by repeating the page's own
  request, with the headers it sent, adding starting_after the last id.

  IDENTITY is the row's own id or token, which Stripe made up and which
  names no account. Its download link can be a signed address that
  expires, so the link is looked up fresh when the file is fetched.

NOT COVERED
  Payouts, payments and balance reports are data exports, not documents.
  A 1099 can sit behind a step that asks for the account's tax ID. This
  app never answers it. It stops and says to download that form by hand.

SAFETY (this account moves money):
  Strictly READ-ONLY. The Dashboard can pay out funds, refund, charge a
  card, create payments and invoices, change bank accounts, reveal secret
  keys and regenerate invoices. This module opens two settings pages, keeps
  what they receive, and fetches a PDF from a row's own link on a
  stripe.com host. It clicks nothing at all. FORBIDDEN_CONTROL_RE and
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
from urllib.parse import urlencode, urlparse, parse_qsl, urlunparse

from paperpull_core.controls import SETTINGS_CONTROL_RE, AUTH_CONTROL_RE

# Everything on its way into a diagnostic file goes through here. It
# lives in core because seventeen apps each had their own copy and
# they drifted into three different versions.
from paperpull_core.redact import redact, set_private_words  # noqa: F401
from paperpull_core.urls import is_safe_url as _host_allows
from paperpull_core.api_census import shape_of as _shape
from paperpull_core.dates import checked as _checked_date

log = logging.getLogger("stripe_docs.site")

# Every host this app will read from. Anything else is refused.
ALLOWED_HOSTS = {"stripe.com"}

BASE = "https://dashboard.stripe.com"
LOGIN_URL = BASE + "/login"
INVOICES_PATH = "/settings/plans-and-fees/invoice-history"
TAX_PATH = "/settings/documents"
INVOICES_API = "/v1/settings/plans_and_fees/invoice_history_documents"
TAX_API = "/ajax/tax_documents"
BILLING_URL = BASE + INVOICES_PATH  # the orchestrator records it as each document's source
URLS = {
    "home": BASE + "/dashboard",
    "login": LOGIN_URL,
    "documents": BASE + TAX_PATH,
    "statements": BASE + INVOICES_PATH,
}

# The two lists, as (kind, page path, answer path).
LISTS = [("invoice", INVOICES_PATH, INVOICES_API), ("tax", TAX_PATH, TAX_API)]

LOGIN_URL_MARKERS = ["/login", "/register", "/logout", "/reset", "/verify",
                     "/two_factor", "/2fa", "/challenge"]

_ACCOUNT_RE = re.compile(r"^/(acct_[A-Za-z0-9]+)(/|$)")

# How long a looked-up list is trusted before a download looks again.
_FRESH_SECONDS = 240
# Pages of a list asked for at most, ten rows or more each.
MAX_PAGES = 30

# ---------------------------------------------------------------------------
# HARD SAFETY GUARD. Tuned for a merchant account. This app clicks
# nothing, so the guard grades controls for --diagnose and satisfies the
# repo-wide guard tests.
# ---------------------------------------------------------------------------
FORBIDDEN_CONTROL_RE = re.compile(
    r"(pay\s*out|payouts?\b|\bpay\b|payment|refund|charge|capture|"
    r"top[\s-]*ups?|transfer|withdraw|deposit|send\s+money|move\s+money|"
    r"create|new\s+(payment|payout|invoice|customer|product)|\binvoice\s+a\b|"
    r"regenerate|reveal|secret|api\s+keys?|\bkeys?\b|webhook|developers?|"
    r"\bbank\b|external\s+account|\bcards?\b|"
    r"dispute|evidence|close\s+account|deactivate|delete|remove|cancel|"
    r"enable|disable|change\b|edit\b|update\b|modify|manage\b|set\s+up|"
    r"subscribe|unsubscribe|upgrade|plans?\b|"
    r"\btin\b|tax\s+id|\bssn\b|\bein\b|w-?9|w-?8|verify|verification|"
    r"password|passcode|two[\s-]*step|two[\s-]*factor|\b2fa\b|"
    r"profile\b|settings|preferences|team\b|invite|"
    r"confirm|submit|save\b|agree|accept|authorize|\bchat\b|contact\s+(us|support)|"
    r"switch\s+to|sandbox|test\s+mode|live\s+mode|workbench|apps?\b|install)", re.I)

SAFE_DOC_CONTROL_RE = re.compile(
    r"(download|view|open|print|\bpdf\b|statement|document|invoice\s+history|"
    r"tax\s+(form|document)|1099|history|"
    r"see\s+(more|all|older)|show\s+(more|all|older)|load\s+more)", re.I)

SECURITY_CHALLENGE_MARKERS = [
    "enter the code", "verification code", "6-digit", "two-step",
    "two-factor", "authenticator", "confirm your identity", "verify your identity",
    "we sent a code", "are you a robot", "captcha", "check your email",
    "check your phone", "your session has expired", "sign in again",
    "access denied",
]

RATE_LIMIT_MARKERS = [
    "too many requests", "rate limit", "try again later",
    "temporarily unavailable", "http error 429", "unusual traffic",
]

# What the list pages look like, for --diagnose only.
FALLBACK = {
    "doc_row": "table tbody tr",
    "doc_link": "a[href*='pdf'], a[href*='files.stripe.com']",
    "download_control": "button, a",
    "page_ready": "main",
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


def iso_from_unix(value) -> str:
    """Unix seconds as the UTC calendar day, or "" for anything else."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return ""
    if not 946684800 <= value <= 4102444800:  # 2000 to 2100
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


def account_path(url: str) -> str:
    """"/acct_123" from a Dashboard address, or "". The id is opaque and is
    only ever used to build the next address, never written anywhere."""
    u = urlparse(url or "")
    if u.hostname != "dashboard.stripe.com":
        return ""
    m = _ACCOUNT_RE.match(u.path or "")
    return "/" + m.group(1) if m else ""


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


def on_dashboard(page) -> bool:
    return bool(account_path(page.url or "")) and not looks_signed_out(page)


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
    """Stripe answered with a sign-in page instead of the thing asked for."""


class NeedsPerson(RuntimeError):
    """Stripe asked for something only the account holder may give, such
    as the tax ID before a 1099. Never answered here."""


def goto_documents(page) -> bool:
    """Be on a signed-in Dashboard page, which is where sign-in lands."""
    try:
        if on_dashboard(page):
            return True
        page.goto(URLS["home"], wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(4000)
    except Exception as e:
        log.info("goto dashboard failed: %s", e)
    return on_dashboard(page)


# ---------------------------------------------------------------------------
# The lists, kept from what the page itself receives
# ---------------------------------------------------------------------------

@dataclass
class Captured:
    """One list answer the page received, and how to ask for the next."""
    url: str = ""
    headers: dict = None
    body: dict = None
    status: int = 0


def _is_answer(url: str, api_path: str) -> bool:
    u = urlparse(url or "")
    return u.hostname == "dashboard.stripe.com" and u.path == api_path


def capture_list(page, page_path: str, api_path: str, wait_ms: int = 20000) -> Captured:
    """Open one settings page and keep the list answer the page receives."""
    acct = account_path(page.url or "")
    if not acct:
        raise SessionExpired("the Stripe tab is not on a signed-in Dashboard page")
    got = Captured()

    def on_response(r):
        if got.body is not None or not _is_answer(r.url, api_path):
            return
        try:
            body = r.json()
        except Exception:
            body = None
        try:
            headers = r.request.all_headers()
        except Exception:
            headers = dict(r.request.headers)
        got.url, got.headers, got.status = r.url, headers, r.status
        got.body = body if isinstance(body, dict) else {}

    page.on("response", on_response)
    try:
        page.goto(BASE + acct + page_path, wait_until="domcontentloaded", timeout=60000)
        waited = 0
        while got.body is None and waited < wait_ms:
            page.wait_for_timeout(500)
            waited += 500
    finally:
        page.remove_listener("response", on_response)
    if looks_signed_out(page):
        raise SessionExpired("Stripe showed a sign-in page")
    if got.status in (401, 403):
        raise SessionExpired("Stripe answered %s, which means the session has ended" % got.status)
    return got


# Headers the page sent that are worth sending again. Browser-managed ones
# (cookie, user-agent, sec-*) are left to the browser.
_KEEP_HEADERS = re.compile(r"^(accept|content-type|authorization|stripe-[a-z-]+|x-stripe-[a-z-]+|"
                           r"x-requested-with|x-request-source|browser-language)$", re.I)

_FETCH_JS = r"""async ([url, headers]) => {
  const r = await fetch(url, {credentials: "include", headers});
  const ct = r.headers.get("content-type") || "";
  if (ct.includes("json")) {
    let j = null;
    try { j = await r.json(); } catch (e) { j = null; }
    return {status: r.status, ct, url: r.url, json: j};
  }
  if (!ct.includes("pdf") && !ct.includes("octet-stream")) return {status: r.status, ct, url: r.url};
  const buf = new Uint8Array(await r.arrayBuffer());
  let s = "";
  for (let i = 0; i < buf.length; i += 0x8000) s += String.fromCharCode.apply(null, buf.subarray(i, i + 0x8000));
  return {status: r.status, ct, url: r.url, b64: btoa(s)};
}"""


def _get(page, url: str, headers: Optional[dict] = None) -> dict:
    if not is_safe_url(url):
        raise ValueError("refusing to fetch off stripe.com: %r" % redact(url))
    if not on_dashboard(page):
        raise SessionExpired("the Stripe tab is not on a signed-in Dashboard page")
    sent = {k: v for k, v in (headers or {}).items() if _KEEP_HEADERS.match(k)}
    r = page.evaluate(_FETCH_JS, [url, sent])
    if r.get("status") in (401, 403) or not is_safe_url(r.get("url") or url):
        raise SessionExpired("Stripe answered %s, which means the session has ended" % r.get("status"))
    return r


def cursor_url(url: str, last_id: str) -> str:
    """The same list address asking for the rows after `last_id`."""
    u = urlparse(url)
    q = [(k, v) for k, v in parse_qsl(u.query, keep_blank_values=True) if k != "starting_after"]
    q.append(("starting_after", last_id))
    return urlunparse(u._replace(query=urlencode(q)))


def all_rows(page, cap: Captured) -> List[dict]:
    """Every row of one list, the first page as the page received it and
    the rest asked for the same way, a page at a time."""
    body = cap.body or {}
    rows = [r for r in body.get("data") or [] if isinstance(r, dict)]
    pages = 1
    while body.get("has_more") and rows and pages < MAX_PAGES:
        last = row_id(rows[-1])
        if not last:
            log.info("a list says it has more but its last row has no id")
            break
        page.wait_for_timeout(1200)
        r = _get(page, cursor_url(cap.url, last), cap.headers)
        body = r.get("json") or {}
        more = [x for x in body.get("data") or [] if isinstance(x, dict)]
        if not more:
            break
        rows.extend(more)
        pages += 1
    return rows


# ---------------------------------------------------------------------------
# Reading a row
# ---------------------------------------------------------------------------

def _first(row: dict, *names):
    for n in names:
        v = row.get(n)
        if v not in (None, "", [], {}):
            return v
    return None


def row_id(row: dict) -> str:
    v = _first(row, "id", "token")
    return v if isinstance(v, str) else ""


_LINK_KEYS = ("link", "pdf", "pdf_url", "pdfUrl", "download_url", "downloadUrl",
              "download_link", "downloadLink", "url", "file_url", "fileUrl")


def row_link(row: dict) -> str:
    """The row's own PDF address on a stripe.com host, or "". A nested
    file object ({"file": {"url": ...}}) is looked into once."""
    for k in _LINK_KEYS:
        v = row.get(k)
        if isinstance(v, str) and is_safe_url(v):
            return v
        if isinstance(v, dict):
            inner = row_link(v)
            if inner:
                return inner
    for k in ("file", "document", "download"):
        v = row.get(k)
        if isinstance(v, dict):
            inner = row_link(v)
            if inner:
                return inner
    return ""


_FORM_RE = re.compile(r"\b(1099[\s-]?[A-Z]{1,4}|1099|1042[\s-]?S|W-?9|W-?8[A-Z-]*|CP[\s-]?2100)\b", re.I)


def tax_form_name(row: dict) -> str:
    """"1099-K" from whatever the row calls its form, or "Tax Form"."""
    for k in ("form_type", "formType", "type", "tax_form", "name", "description", "title"):
        v = row.get(k)
        if isinstance(v, str):
            m = _FORM_RE.search(v.replace("_", "-"))
            if m:
                s = m.group(1).upper().replace(" ", "-")
                return re.sub(r"^1099(?=[A-Z])", "1099-", s)
    return "Tax Form"


def tax_year(row: dict) -> Optional[int]:
    v = _first(row, "tax_year", "taxYear", "year", "period_year")
    try:
        year = int(v)
    except (TypeError, ValueError):
        return None
    return year if 2000 <= year <= 2100 else None


def invoice_doc(row: dict) -> Optional[dict]:
    doc_id = row_id(row)
    if not doc_id:
        return None
    end = _first(row, "period_end_exclusive", "periodEndExclusive")
    date = iso_from_unix(end - 86399) if isinstance(end, (int, float)) else ""
    date = date or iso_from_unix(_first(row, "created", "createdAt"))
    number = _first(row, "invoice_number", "invoiceNumber", "number")
    number = number if isinstance(number, str) and number.strip() else ""
    title = "Fee Invoice" + (f" {number.strip()}" if number else "")
    return {"kind": "invoice", "id": doc_id, "date": date, "title": title,
            "link": row_link(row)}


def tax_doc(row: dict) -> Optional[dict]:
    doc_id = row_id(row)
    if not doc_id:
        return None
    year = tax_year(row)
    date = f"{year}-12-31" if year else iso_from_unix(_first(row, "created", "createdAt"))
    form = tax_form_name(row)
    title = f"{form} Tax Form" + (f" {year}" if year else "")
    return {"kind": "tax", "id": doc_id, "date": date, "title": title,
            "link": row_link(row)}


_READERS = {"invoice": invoice_doc, "tax": tax_doc}
_cache = {"at": 0.0, "docs": []}


def list_documents(page) -> List[dict]:
    """Every fee invoice and tax form the account lists, newest first."""
    docs = []
    for kind, page_path, api_path in LISTS:
        cap = capture_list(page, page_path, api_path)
        if cap.body is None:
            log.info("the %s page never received its list", kind)
            continue
        for row in all_rows(page, cap):
            d = _READERS[kind](row)
            if d:
                docs.append(d)
    docs.sort(key=lambda d: (d["date"], d["id"]), reverse=True)
    _cache.update(at=time.monotonic(), docs=docs)
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
    return [RawDoc(title=d["title"], date_text=d["date"], href=d["link"], kind=d["kind"],
                   document_id=d["id"], text=f"Stripe {d['title']}")
            for d in list_documents(page)]


def _fresh_link(page, document_id: str) -> str:
    if time.monotonic() - _cache["at"] > _FRESH_SECONDS:
        list_documents(page)
    for d in _cache["docs"]:
        if d["id"] == document_id:
            return d["link"]
    return ""


def _fetch_file(page, link: str) -> dict:
    """A file from its own link. From inside the page first. A link on
    another Stripe host (files.stripe.com, say) can be refused to a page
    script, and is then asked for through the browser's own session, the
    same cookies, never leaving the browser profile."""
    try:
        return _get(page, link)
    except (SessionExpired, ValueError):
        raise
    except Exception as e:
        log.info("in-page fetch refused (%s), asking through the session", str(e)[:80])
    resp = page.context.request.get(link, max_redirects=5)
    if not is_safe_url(resp.url or link):
        raise ValueError("the file moved off stripe.com: %r" % redact(resp.url))
    ct = (resp.headers.get("content-type") or "").lower()
    if resp.status in (401, 403):
        raise SessionExpired("Stripe answered %s, which means the session has ended" % resp.status)
    if "json" in ct:
        try:
            return {"status": resp.status, "ct": ct, "url": resp.url, "json": resp.json()}
        except Exception:
            return {"status": resp.status, "ct": ct, "url": resp.url, "json": None}
    body = resp.body()
    return {"status": resp.status, "ct": ct, "url": resp.url,
            "b64": base64.b64encode(body).decode() if body[:5] == b"%PDF-" else ""}


def download_bill(page, dl_dir, iso_date: str, out_path, href: str = "",
                  title: str = "", document_id: str = "") -> bool:
    """Fetch one document's PDF from its own link, from inside the page, and
    write it. The link is looked up again when the one on record may have
    expired. A form with no link at all, which is how a 1099 behind a tax ID
    step would look, raises NeedsPerson. `dl_dir` is unused."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if not goto_documents(page):
        return False
    link = _fresh_link(page, document_id) if document_id else ""
    link = link or (href if is_safe_url(href) else "")
    if not link:
        raise NeedsPerson("Stripe lists %s with no download link" % (title or "a document"))
    r = _fetch_file(page, link)
    if r.get("json") is not None:
        body = r["json"] if isinstance(r["json"], dict) else {}
        words = " ".join(str(k) for k in body).lower() + " " + str(body.get("error", "")).lower()
        if "challenge" in words or "tin" in words.split():
            raise NeedsPerson("Stripe asked for the tax ID before %s" % (title or "this form"))
        # A JSON answer may carry the real file address one level down.
        inner = row_link(body)
        if inner and inner != link:
            r = _fetch_file(page, inner)
    if not r.get("b64"):
        log.info("no PDF for %s: status %s, %s", iso_date, r.get("status"), r.get("ct"))
        return False
    data = base64.b64decode(r["b64"])
    if data[:5] != b"%PDF-":
        return False
    out_path.write_bytes(data)
    return True


# ---------------------------------------------------------------------------
# Diagnose. What each list answer looks like, as shapes, and the page's
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
    """Each list page and the shape of the answer it received, without
    downloading anything. Nothing is clicked. Values never leave, only
    field names, types and counts."""
    report = {"accounts": [], "api": {}}
    for kind, page_path, api_path in LISTS:
        try:
            cap = capture_list(page, page_path, api_path)
            body = cap.body or {}
            rows = [r for r in body.get("data") or [] if isinstance(r, dict)]
            read = [_READERS[kind](r) for r in rows]
            report["api"][kind] = {
                "received": cap.body is not None,
                "status": cap.status,
                "rows": len(rows),
                "has_more": bool(body.get("has_more")),
                "rows_with_an_id": sum(1 for d in read if d),
                "rows_with_a_link": sum(1 for d in read if d and d["link"]),
                "rows_with_a_date": sum(1 for d in read if d and d["date"]),
                "shape": _shape(body),
                "page": _page_summary(page)}
        except Exception as e:
            report["api"][kind] = {"error": str(e)[:200]}
    return report


def collect_documents(page) -> List[RawDoc]:
    """Used only by --diagnose. The same list discovery reads, minus the
    ids and links, which are opaque but still point into an account."""
    try:
        docs = collect_download_docs(page)
    except Exception:
        return []
    for d in docs:
        d.href = ""
        d.document_id = ""
    return docs


def expand_all(page) -> None:
    """Nothing to expand. The lists come from the page's own answers."""


def scroll_full_page(page, rounds: int = 0, delay_ms: int = 0) -> None:
    """Nothing to scroll. The lists come from the page's own answers."""
