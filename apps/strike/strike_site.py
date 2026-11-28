"""ALL Strike (strike.me) URLs, API paths and page behavior live here.

When Strike changes its dashboard, repair this file only.

STATUS, mapped 2026-11-27 against a signed-in personal account.

  The web app is dashboard.strike.me, a Next.js app signed in through
  auth.strike.me. The Documents page (/documents, reached from the user
  menu) has three tabs, Taxes, Statements and Beneficiary, which are
  buttons with no address. Nothing on that page needs pressing, because
  each tab reads a JSON API on the dashboard's own host, and this app asks
  the same API from inside the signed-in tab, as the page's own scripts do.
  page.goto to /documents stays signed in (a cookie session).

  THE API, all GET, nothing clicked:
    * statements list   /api/documents/account-statements
        -> {"items": [{"type": "Month", "year": 2026, "month": 10}, ...,
                      {"type": "Year", "year": 2025}], "count": 13}
        one entry per complete month, newest first, and one "Year" entry
        per complete year, the page's "<YYYY> annual transactions" row.
    * one statement     /api/documents/account-statements/<y>/<m>/download
      a year's entry    /api/documents/account-statements/<y>/download
        with Accept: application/pdf for the PDF, or text/csv for the CSV.
        The page sends nothing else. The PDF answers as
        application/octet-stream, the CSV as text/plain.
    * tax forms list    /api/documents/tax-documents
    * one tax form      /api/documents/tax-documents/<id>/download
        Read from the page's own code: each row carries id, year and
        fileName, and the download is a blob saved under fileName. The
        account this was mapped against had no tax form, so the list's
        exact shape was not seen. A list this cannot read stops the run.

  WHAT IS TAKEN, and why:
    * each monthly statement as its PDF, and its CSV beside it when
      save_statement_csv is on (the default). The PDF prints "Monthly
      Statement" and its period, "October 01 2026  October 31 2026", so
      the core checks the closing day before filing it. The CSV has a fixed
      header and one row per transaction, each dated, so this file checks
      the header and that every row falls in the month (csv_problem).
    * the "Year" entry as its CSV only. The page disables Export as PDF on
      that row. The server answers a PDF anyway, headed "Monthly Statement"
      January to December, whose balance summary did not agree with the
      year's own transactions on the account this was mapped against, so
      it is never asked for.
    * tax forms as the file Strike gives.
  Loan documents and beneficiary agreements are on the same page and are
  not taken.

SAFETY (this account buys, sells and sends bitcoin and moves dollars):
  Strictly READ-ONLY. The dashboard can buy, sell, send, receive, deposit,
  withdraw, set up recurring purchases and target orders, open a loan and
  link bank accounts. This app presses NO control at all. It reads JSON and
  files through GET requests made from inside the page, to the paths above
  and nowhere else (API_PATH_RE), on dashboard.strike.me only, never
  following a redirect. FORBIDDEN_CONTROL_RE and SAFE_DOC_CONTROL_RE still
  guard the one thing that can press, Diagnose's survey, which follows only
  a link whose whole text is a document word.
"""
from __future__ import annotations

import calendar
import csv
import io
import logging
import re
from datetime import datetime
from typing import List, Optional
from urllib.parse import urlsplit

from paperpull_core import intake
from paperpull_core.controls import SETTINGS_CONTROL_RE, AUTH_CONTROL_RE
from paperpull_core.controls import escape_for_locator

# Everything on its way into a diagnostic file goes through here.
from paperpull_core.identity import Identity
from paperpull_core.redact import redact, set_private_words  # noqa: F401
from paperpull_core.urls import is_safe_url as _host_allows
from paperpull_core.api_census import shape_of as _shape
from paperpull_core.dates import checked as _checked_date
from paperpull_core.characters import whole_json

log = logging.getLogger("strike_docs.site")

# The one host this app reads from. auth.strike.me, where the person signs
# in, is theirs, and strike.me itself is the marketing site.
ALLOWED_HOSTS = ("dashboard.strike.me",)

BASE = "https://dashboard.strike.me"
URLS = {
    "home": f"{BASE}/",
    # The dashboard sends a signed-out browser on to auth.strike.me.
    "login": f"{BASE}/",
    "documents": f"{BASE}/documents",
}

STATEMENTS_API = "/api/documents/account-statements"
TAX_API = "/api/documents/tax-documents"

# Every path this app asks for, and nothing else.
API_PATH_RE = re.compile(
    r"^/api/documents/(account-statements(/\d{4}(/(?:[1-9]|1[0-2]))?/download)?"
    r"|tax-documents(/[A-Za-z0-9_-]{1,80}/download)?)$")

LOGIN_URL_MARKERS = ["/login", "/signin", "/sign-in", "/account/login", "/verify",
                     "/onboarding"]

# The header of every statement CSV, in this order.
CSV_COLUMNS = ["Reference", "Date & Time (UTC)", "Transaction Type", "Amount USD",
               "Fee USD", "Amount BTC", "Fee BTC", "BTC Price", "Destination",
               "Description", "Transaction Hash", "Note"]
_CSV_DATE_FORMAT = "%b %d %Y %H:%M:%S"


class SessionExpired(RuntimeError):
    """Strike answered with a sign-in instead of the thing asked for."""


class ListStopped(RuntimeError):
    """A list came back in a shape this app does not know how to read
    whole. The run stops rather than file a part of it as the whole, and
    a list read again while documents are taken (a tax form's id) stops
    the run the same way (listing.read_again_stopped)."""


def is_safe_url(url: str) -> bool:
    """True only for an https URL on Strike's dashboard host."""
    return _host_allows(url, ALLOWED_HOSTS, subdomains=False)


# ---------------------------------------------------------------------------
# HARD SAFETY GUARD. Tuned for a bitcoin and cash account. Never buy, sell,
# send, receive, deposit, withdraw, borrow or change a setting.
# ---------------------------------------------------------------------------
FORBIDDEN_CONTROL_RE = re.compile(
    r"(\bbuy\b|\bsell\b|\bsend\b|\breceive\b|\bdeposit|\bwithdraw|"
    r"\bconvert|\bswap\b|\btrade\b|\border\b|target\s+order|"
    r"recurring|\bstacks?\b|\bdca\b|auto-?(buy|deposit|convert)|"
    r"\bloans?\b|borrow|repay|collateral|"
    r"\btransfer|\bpay\b|payment|payday|\bwire\b|bank\s+account|link\s+(a\s+)?bank|"
    r"routing|\bplaid\b|\bcard\b|"
    r"lightning|invoice|\baddress\b|\bqr\b|"
    r"beneficiar|referr|invite|"
    # Word boundaries on both sides of the verb stems, so "Credit" is not
    # taken for "edit".
    r"\bchang(e|es|ed|ing)\b|\bedit(s|ed|ing)?\b|\bupdat(e|es|ed|ing)\b|"
    r"\bset\s+up\b|enroll|enable|disable|\bdelet|\bremov(e|es|ed|ing|al)\b|"
    r"close\s+account|\bsubmit|\bconfirm\b|\bagree\b|\baccept\b|authoriz|"
    r"\bapply\b|request\b|\bstart\b|\bopen\s+a\b|"
    r"log\s*out|logout|sign\s*out|password|passkey|username|\bpin\b|"
    r"api\s+key|two-?factor|\b2fa\b|security|\bemail\b|\bphone\b)",
    re.I)

# What a document control may look like. A control must match this AND not
# match the blocklist.
SAFE_DOC_CONTROL_RE = re.compile(
    r"(download|export\s+as\s+(pdf|csv)|\bview\b|\bpdf\b|\bcsv\b|statements?\b|"
    r"documents?\b|\btax(es)?\b|1099|annual\s+transactions)", re.I)


def is_safe_control(name: str) -> bool:
    name = (name or "").strip()
    if not name:
        return False
    if (FORBIDDEN_CONTROL_RE.search(name) or SETTINGS_CONTROL_RE.search(name)
            or AUTH_CONTROL_RE.search(name)):
        return False
    return bool(SAFE_DOC_CONTROL_RE.search(name))


# Links diagnose may follow while surveying. Narrower than the guard on
# purpose, since these are followed without a person choosing each one.
SURVEY_LINK_RE = re.compile(r"^(documents?|statements?|tax(es)?|tax\s+documents?)$", re.I)


SECURITY_CHALLENGE_MARKERS = [
    "one-time code", "one time code", "enter the code", "verification code",
    "we sent a code", "text message", "authenticator", "confirm your identity",
    "verify your identity", "are you a robot", "captcha", "access denied",
    "your session has expired", "session expired", "signed out",
]

RATE_LIMIT_MARKERS = ["too many requests", "rate limit", "try again later",
                      "temporarily unavailable", "unusual traffic"]


def looks_signed_out(page) -> bool:
    try:
        url = page.url or ""
    except Exception:
        # A page that cannot say where it is is not a signed-in page.
        return True
    if (urlsplit(url).hostname or "").lower() == "auth.strike.me":
        return True
    if any(m in url.lower() for m in LOGIN_URL_MARKERS):
        return True
    try:
        if page.locator("input[type='password']").count() > 0:
            return True
    except Exception:
        pass
    return False


def detect_security_challenge(page) -> Optional[str]:
    """Names the code, CAPTCHA or throttling prompt on screen, or None.
    Visible text only."""
    try:
        title = (page.title() or "").lower()
    except Exception:
        title = ""
    try:
        body = page.locator("body").inner_text(timeout=5000).lower()
    except Exception:
        body = ""
    hay = title + "\n" + body[:2000]
    for m in SECURITY_CHALLENGE_MARKERS:
        if m in hay:
            return f"Security challenge detected: '{m}'"
    for m in RATE_LIMIT_MARKERS:
        if m in hay:
            return f"Possible rate limiting detected: '{m}'"
    return None


def on_dashboard(page) -> bool:
    """Any signed-in page of dashboard.strike.me. The API answers from all
    of them, since the session is a cookie."""
    try:
        return is_safe_url(page.url or "") and not looks_signed_out(page)
    except Exception:
        return False


def goto_documents(page) -> bool:
    """On the dashboard, and the statements list answers. Signed in means
    the list itself can be read, never only that no sign-in form showed."""
    if not on_dashboard(page):
        try:
            page.goto(URLS["documents"], wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            log.info("documents URL failed: %s", type(e).__name__)
        if not on_dashboard(page):
            return False
    try:
        return _api(page, STATEMENTS_API, "json").get("status") == 200
    except SessionExpired:
        return False
    except Exception as e:
        log.info("the statements list did not answer: %s", type(e).__name__)
        return False


def ensure_statements(page) -> bool:
    return goto_documents(page)


# -- the documents API ---------------------------------------------------------

DOCUMENT_TYPES = {"Month": "Monthly statement", "Year": "Annual transactions",
                  "Tax": "Tax form"}


def parse_date(text):
    """An ISO day as YYYY-MM-DD, with or without a time after it, checked
    to be a real day, or ''. A digit straight after the day makes it a
    longer number, not a date."""
    m = re.match(r"^\s*(\d{4})-(\d{2})-(\d{2})(?!\d)", text or "")
    return _checked_date("%s-%s-%s" % m.groups() if m else "", "")


def month_end(year: int, month: int) -> str:
    return "%04d-%02d-%02d" % (year, month, calendar.monthrange(year, month)[1])


# Runs inside the page. One GET to a path on the page's own host, with the
# Accept header the page itself sends, no redirect followed. Returns the
# status, the content type, and the body: parsed JSON when asked for json,
# otherwise base64.
_FETCH_JS = """async ({path, accept, want}) => {
  const target = new URL(path, location.href);
  if (target.protocol !== 'https:' || target.hostname !== 'dashboard.strike.me'
      || target.origin !== location.origin) {
    throw new Error('Refusing an off-host request');
  }
  const r = await fetch(target.href, {method: 'GET', credentials: 'same-origin',
                                      headers: {accept}, redirect: 'error'});
  const ct = r.headers.get('content-type') || '';
  const raw = await ppRead(r);
  if (want === 'json') {
    let j = null;
    try { j = JSON.parse(new TextDecoder().decode(raw)); } catch (e) {}
    return {status: r.status, type: ct, json: j};
  }
  let s = '';
  for (let i = 0; i < raw.length; i += 0x8000) {
    s += String.fromCharCode.apply(null, raw.subarray(i, i + 0x8000));
  }
  return {status: r.status, type: ct, b64: btoa(s)};
}"""

_ACCEPT = {"json": "application/json", "pdf": "application/pdf", "csv": "text/csv"}


def _api(page, path: str, want: str) -> dict:
    if not API_PATH_RE.match(path or ""):
        raise ValueError("refusing a path this app does not read")
    if not is_safe_url(page.url or ""):
        raise ValueError("refusing to ask from a tab off dashboard.strike.me")
    res = intake.evaluate(page, _FETCH_JS, {"path": path, "accept": _ACCEPT[want],
                                            "want": "json" if want == "json" else "bytes"})
    if res.get("status") in (401, 403):
        raise SessionExpired("Strike answered %s" % res["status"])
    return res


def _items(body, what: str) -> list:
    """The list in an answer, {"items": [...], "count": n} or a bare list.
    A count that disagrees with the items says there is more than this
    answer holds, which this app has no way to ask for."""
    if isinstance(body, list):
        return body
    if not isinstance(body, dict) or not isinstance(body.get("items"), list):
        raise ListStopped("the %s list came back in a shape this app does not read" % what)
    items = body["items"]
    count = body.get("count")
    if count is not None and count != len(items):
        raise ListStopped("the %s list holds %d of the %s it counts"
                             % (what, len(items), count))
    return items


def statements_from(body, this_year: Optional[int] = None) -> List[dict]:
    """The statement entries in a list answer, as {"type", "year",
    "month"}, newest first. Anything that is not a Month with a real month
    or a Year stops the listing."""
    this_year = this_year or datetime.now().year
    out = []
    for it in _items(body, "statements"):
        if not isinstance(it, dict):
            raise ListStopped("a statement entry is not an object")
        kind, year, month = it.get("type"), it.get("year"), it.get("month")
        if not isinstance(year, int) or isinstance(year, bool) or not 2015 <= year <= this_year:
            raise ListStopped("a statement entry has no year this app can read")
        if kind == "Month" and isinstance(month, int) and 1 <= month <= 12:
            out.append({"type": "Month", "year": year, "month": month})
        elif kind == "Year" and month in (None, 0):
            out.append({"type": "Year", "year": year, "month": None})
        else:
            raise ListStopped("a statement entry of a kind this app does not know")
    keys = [(d["type"], d["year"], d["month"]) for d in out]
    if len(set(keys)) != len(keys):
        raise ListStopped("the statements list names one statement twice")
    return out


def list_statements(page) -> List[dict]:
    res = _api(page, STATEMENTS_API, "json")
    if res.get("status") != 200:
        raise ListStopped("the statements list answered %s" % res.get("status"))
    return statements_from(res.get("json"))


def tax_documents_from(body, this_year: Optional[int] = None) -> List[dict]:
    """The tax forms in a list answer, as {"id", "year", "file_name"}. Its
    shape is read from the page's own code; no form was there to see on the
    account this was mapped against, so anything unexpected stops the
    listing."""
    this_year = this_year or datetime.now().year
    out = []
    for it in _items(body, "tax forms"):
        if not isinstance(it, dict):
            raise ListStopped("a tax form entry is not an object")
        doc_id = "" if it.get("id") is None else str(it.get("id"))
        year, name = it.get("year"), it.get("fileName")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", doc_id):
            raise ListStopped("a tax form has no id this app can read")
        if isinstance(year, str) and year.isdigit():
            year = int(year)
        if not isinstance(year, int) or isinstance(year, bool) or not 2015 <= year <= this_year:
            raise ListStopped("a tax form has no year this app can read")
        if not isinstance(name, str) or not name.strip():
            raise ListStopped("a tax form has no name")
        out.append({"id": doc_id, "year": year,
                    "file_name": re.sub(r"\s+", " ", name).strip()[:120]})
    if len({d["id"] for d in out}) != len(out):
        raise ListStopped("the tax forms list names one form twice")
    return out


def list_tax_documents(page) -> List[dict]:
    res = _api(page, TAX_API, "json")
    if res.get("status") != 200:
        raise ListStopped("the tax forms list answered %s" % res.get("status"))
    return tax_documents_from(res.get("json"))


def statement_path(year: int, month: Optional[int]) -> str:
    if month:
        return "%s/%d/%d/download" % (STATEMENTS_API, int(year), int(month))
    return "%s/%d/download" % (STATEMENTS_API, int(year))


def _bytes(res) -> bytes:
    if res.get("status") != 200 or not res.get("b64"):
        log.info("the download answered %s", res.get("status"))
        return b""
    return intake.decode(res["b64"])


def statement_bytes(page, year: int, month: Optional[int], fmt: str) -> bytes:
    """One statement as the PDF or the CSV, asked for as the page asks.
    Empty when Strike does not answer with one. A Year entry is never asked
    for as a PDF (see STATUS)."""
    if fmt not in ("pdf", "csv"):
        raise ValueError("a statement is a pdf or a csv")
    if fmt == "pdf" and not month:
        raise ValueError("the annual transactions entry is taken as a CSV only")
    data = _bytes(_api(page, statement_path(year, month), fmt))
    if fmt == "pdf" and data[:5] != b"%PDF-":
        return b""
    return data


def tax_bytes(page, doc_id: str) -> bytes:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", doc_id or ""):
        raise ValueError("a tax form id does not look like one")
    return _bytes(_api(page, "%s/%s/download" % (TAX_API, doc_id), "pdf"))


def csv_problem(data: bytes, year: Optional[int] = None,
                month: Optional[int] = None) -> str:
    """Why these bytes are not the statement CSV asked for, or '' when they
    are. The header must be Strike's, every row as wide as it, and every
    row dated within the month, or the year for the annual entry. A month
    with no transactions is a header alone, and is a statement all the
    same."""
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return "it is not text"
    rows = list(csv.reader(io.StringIO(text)))
    if not rows or [c.strip() for c in rows[0]] != CSV_COLUMNS:
        return "its header is not a Strike statement's"
    when = CSV_COLUMNS.index("Date & Time (UTC)")
    for row in rows[1:]:
        if not any(c.strip() for c in row):
            continue
        if len(row) != len(CSV_COLUMNS):
            return "a row is not as wide as the header"
        try:
            day = datetime.strptime(row[when].strip(), _CSV_DATE_FORMAT)
        except ValueError:
            return "a row's date cannot be read"
        if year is not None and day.year != year:
            return "a row is dated in another year"
        if month is not None and day.month != month:
            return "a row is dated in another month"
    return ""


def identity_for(doc) -> Identity:
    """What would prove a saved PDF is this document and not another.

    A monthly statement prints its first and last day, and the last day is
    the document's date, which no other month's statement prints as its
    own closing day, so the date alone is checked. A tax form's row carries
    only a year and a name, neither of which tells one form from another,
    so it is unchecked."""
    if getattr(doc, "kind", "") == "Month":
        return Identity(date=str(getattr(doc, "date", "") or "")[:10],
                        kind="Monthly Statement")
    return Identity(kind=str(getattr(doc, "kind", "") or ""))


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
    for role in ("link", "button", "tab", "menuitem"):
        try:
            loc = page.get_by_role(role)
            for i in range(min(loc.count(), 80)):
                el = loc.nth(i)
                try:
                    text = (el.inner_text(timeout=300) or "").strip()
                except Exception:
                    text = ""
                if not text:
                    try:
                        text = (el.get_attribute("aria-label") or "").strip()
                    except Exception:
                        text = ""
                if not text:
                    continue
                href = ""
                if role == "link":
                    try:
                        href = el.get_attribute("href") or ""
                    except Exception:
                        pass
                controls.append({"role": role, "text": redact(text)[:60],
                                 "href": redact(href)[:120],
                                 "safe": is_safe_control(text),
                                 "survey": bool(SURVEY_LINK_RE.match(text.strip()))})
        except Exception:
            pass
    out["controls"] = controls
    return out


def survey(page, dwell_ms: int = 4000, max_follow: int = 4) -> dict:
    """What a signed-in dashboard looks like, without downloading anything.

    Records the page, its headings and controls with the guard's verdict on
    each, and every JSON response the dashboard sends while the page
    settles, as shape only, never values. Then follows, one at a time and
    back again, the few links whose whole text is a document word. No
    screenshot, the dashboard shows balances."""
    seen: list = []

    def on_response(res):
        try:
            url = res.url or ""
            if not is_safe_url(url):
                return
            ct = (res.headers.get("content-type") or "").lower()
            if "json" not in ct:
                return
            entry = {"url": redact(url.split("?")[0])[:200], "status": res.status,
                     "type": ct[:40]}
            try:
                entry["shape"] = _shape(whole_json(res.json()))
            except Exception:
                entry["shape"] = "unreadable"
            seen.append(entry)
        except Exception:
            pass

    page.on("response", on_response)
    report = {"pages": [], "responses": seen}
    try:
        page.wait_for_timeout(dwell_ms)
        start = _page_summary(page)
        report["pages"].append(start)
        followed = 0
        for c in start["controls"]:
            if followed >= max_follow or c["role"] != "link" or not c["survey"]:
                continue
            if not is_safe_control(c["text"]):
                continue
            try:
                link = page.get_by_role("link", name=re.compile(
                    "^" + escape_for_locator(c["text"].replace("#", "")) + "$", re.I)).first
                if link.count() == 0:
                    continue
                before = page.url
                link.click(timeout=5000)
                page.wait_for_timeout(dwell_ms)
                if not is_safe_url(page.url or ""):
                    page.go_back()
                    continue
                summary = _page_summary(page)
                summary["followed_from"] = c["text"]
                report["pages"].append(summary)
                followed += 1
                if page.url != before:
                    page.go_back(wait_until="domcontentloaded", timeout=15000)
                    page.wait_for_timeout(1500)
            except Exception as e:
                report.setdefault("notes", []).append(
                    "could not follow %r: %s" % (c["text"], type(e).__name__))
    finally:
        try:
            page.remove_listener("response", on_response)
        except Exception:
            pass
    return report
