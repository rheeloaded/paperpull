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

SAFETY (this account moves money):
  Strictly READ-ONLY. This module makes the two requests above and nothing
  else. It never sends or requests money, transfers a balance, applies
  for credit, saves an offer, donates, or edits any setting, and it clicks
  nothing at all. FORBIDDEN_CONTROL_RE and SAFE_DOC_CONTROL_RE are kept so
  the repo-wide guard tests cover this app the same as every other, and
  --diagnose uses them to grade the page's controls.
"""
from __future__ import annotations

import base64
import calendar
import logging
import re
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

# ---------------------------------------------------------------------------
# HARD SAFETY GUARD. Tuned for a wallet that moves money. This app clicks
# nothing, so the guard grades controls for --diagnose and satisfies the
# repo-wide guard tests.
# ---------------------------------------------------------------------------
FORBIDDEN_CONTROL_RE = re.compile(
    r"(\bsend\b|request\s+money|\brequest\b|transfer|withdraw|deposit|add\s+money|"
    r"\bpay\b|payment|pay\s+in\s+4|checkout|\bbuy\b|\bsell\b|crypto|"
    r"donate|charit|fundrais|reload\s+phone|xoom|"
    r"\bapply\b|credit\s+card|cashback|\bcards?\b|\bbanks?\b|link\s+a|"
    r"save\s+offer|\boffers?\b|rewards?\b|redeem|start\s+saving|savings|"
    r"enable|disable|change\b|edit\b|update\b|modify|manage\b|set\s+up|"
    r"delete|remove|cancel|close\s+account|dispute|report\s+a\s+problem|"
    r"custom\s+statement|file\s+taxes|"
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


def collect_download_docs(page) -> List[RawDoc]:
    """Every monthly statement the site lists. `href` is the download
    address, built back from the month so nothing else rides along."""
    if not goto_documents(page, fresh=True):
        raise SessionExpired("PayPal showed a sign-in page")
    return [RawDoc(title=s["title"], date_text=s["date"], href=s["href"],
                   text=f"PayPal {s['title']}")
            for s in list_statements(page)]


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


def collect_documents(page) -> List[RawDoc]:
    """Used only by --diagnose. The same list discovery reads."""
    try:
        return collect_download_docs(page)
    except Exception:
        return []


def expand_all(page) -> None:
    """Nothing to expand. The list comes from the page's own endpoint."""


def scroll_full_page(page, rounds: int = 0, delay_ms: int = 0) -> None:
    """Nothing to scroll. The list comes from the page's own endpoint."""
