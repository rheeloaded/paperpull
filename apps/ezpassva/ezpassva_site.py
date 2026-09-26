"""ALL ezpassva.com selectors, URLs, and page behavior live here.

When E-ZPass Virginia changes its site, repair this file only.

STATUS: mapped 2026-09-25 against a signed-in session and verified end to
end (list, PDF).

HOW THE SITE WORKS
  The customer portal is myaccount.ezpassva.com, an ASP.NET MVC site.
  Sign-in lands on the home page. Statements & Transactions swaps page
  fragments in with the site's own ReplaceContents(), and "View Online
  Statements" is the fragment at /Statements/Online. This app asks for
  that fragment from inside the signed-in page, the same request the
  link makes, so the session never leaves the browser and nothing on the
  page is clicked.

  The fragment is two small tables, Monthly and Quarterly, each row a
  period and a Download link of the form
      /Statements/Download?sType=<1 monthly, 0 quarterly>&sNum=<month or
      quarter>&sYear=<year>
  which answers the statement itself as an inline application/pdf. The
  site lists about the last twelve months and four quarters. Asking for a
  period it does not list redirects to /Home/Error?code=601, an HTML page
  that must never be saved as a statement.

  IDENTITY is the kind (monthly or quarterly) plus the period. The link's
  three numbers say exactly that and nothing about the account.

NOT COVERED
  Older statements are not online, so run this at least once a year.
  "View Transactions" is a searchable table of the last 365 days, not a
  document, and is left alone. Paper statement subscription is a setting
  and is never touched.

SAFETY (this account holds a prepaid balance and a card that refills it):
  Strictly READ-ONLY. This module asks for the statements fragment and the
  statement PDFs it lists and nothing else. It never pays, replenishes,
  changes the replenishment amount or card, adds or removes a vehicle or
  transponder, subscribes to paper statements, or edits any setting, and
  it clicks nothing at all. FORBIDDEN_CONTROL_RE and SAFE_DOC_CONTROL_RE
  are kept so the repo-wide guard tests cover this app the same as every
  other, and --diagnose uses them to grade the page's controls.
"""
from __future__ import annotations

import base64
import calendar
import html as _html
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import urljoin, urlparse

from paperpull_core.controls import SETTINGS_CONTROL_RE, AUTH_CONTROL_RE

# Everything on its way into a diagnostic file goes through here. It
# lives in core because seventeen apps each had their own copy and
# they drifted into three different versions.
from paperpull_core.redact import redact, set_private_words  # noqa: F401
from paperpull_core.urls import is_safe_url as _host_allows
from paperpull_core.dates import last_day as _last_day
from paperpull_core.dates import checked as _checked_date

log = logging.getLogger("ezpassva_docs.site")

# Every host this app will read from. Anything else is refused.
ALLOWED_HOSTS = {"ezpassva.com"}

BASE = "https://myaccount.ezpassva.com"
HOME_URL = BASE + "/"
STATEMENTS_FRAGMENT = BASE + "/Statements/Online"
DOWNLOAD_PATH = "/Statements/Download"
BILLING_URL = STATEMENTS_FRAGMENT  # the orchestrator records it as each document's source
URLS = {
    "home": HOME_URL,
    "login": HOME_URL,
    "documents": HOME_URL,
    "statements": STATEMENTS_FRAGMENT,
}

# sType in the download link.
MONTHLY, QUARTERLY = "1", "0"

LOGIN_URL_MARKERS = ["/login", "/signin", "/sign-in", "/logon", "/logout",
                     "/timeout", "/account/log"]

# ---------------------------------------------------------------------------
# HARD SAFETY GUARD. Tuned for a prepaid toll account. This app clicks
# nothing, so the guard grades controls for --diagnose and satisfies the
# repo-wide guard tests.
# ---------------------------------------------------------------------------
FORBIDDEN_CONTROL_RE = re.compile(
    r"(\bpay\b|payment|make\s+a\s+payment|replenish|auto\s*pay|autopay|"
    r"top\s*up|add\s+funds|deposit|refund|transfer|withdraw|"
    r"\bvehicles?\b|transponder|\btags?\b|add\s+vehicle|plate|"
    r"\bcards?\b|credit\s+card|bank\s+account|"
    r"close\s+account|open\s+(an?\s+)?account|\bapply\b|"
    r"subscribe|unsubscribe|paper\s+statements?|enroll|unenroll|sign\s+up|"
    r"notifications?\b|alerts?\b|"
    r"enable|disable|change\b|edit\b|update\b|modify|manage\b|"
    r"set\s+up|delete|remove|cancel|dispute|violation|"
    r"password|passcode|username|\bpin\b|profile\b|settings|preferences|"
    r"contact\s+info|\baddress\b|"
    r"confirm|submit|save\b|agree|accept|authorize|\bchat\b|contact\s+us|"
    r"customer\s+service|order\b|request\b)", re.I)

SAFE_DOC_CONTROL_RE = re.compile(
    r"(download|view|open|print|\bpdf\b|statement|document|history|"
    r"see\s+(more|all|older)|show\s+(more|all|older)|load\s+more)", re.I)

SECURITY_CHALLENGE_MARKERS = [
    "enter the code", "verification code", "6-digit", "two-factor",
    "two-step", "authenticator", "confirm your identity", "verify your identity",
    "we sent a code", "are you a robot", "captcha", "check your email",
    "check your phone", "your session has expired", "session timed out",
    "access denied",
]

RATE_LIMIT_MARKERS = [
    "too many requests", "rate limit", "try again later",
    "temporarily unavailable", "http error 429", "unusual traffic",
]

# What the statements fragment looks like, for --diagnose only.
FALLBACK = {
    "doc_row": "a.btn-monthly-statement",
    "doc_link": "a.btn-monthly-statement",
    "download_control": "a.btn-monthly-statement",
    "page_ready": "body",
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
QUARTER_RE = re.compile(r"\b(?:Q|Quarter\s*)([1-4]),?\s+(\d{4})\b", re.I)
ISO_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})(?!\d)")
YEAR_RE = re.compile(r"\b(19|20)(\d{2})\b")


def parse_date(text):
    """An exact YYYY-MM-DD in the text, or None."""
    m = ISO_RE.search(text or "")
    if not m:
        return None
    return _checked_date(f"{m.group(1)}-{m.group(2)}-{m.group(3)}", None)


def parse_period_date(text: str) -> Tuple[Optional[str], str]:
    """A statement title's period as the last day of it. "Quarterly
    Statement - Q2 2026" -> 2026-06-30, "Monthly Statement - August 2026"
    -> 2026-08-31."""
    text = text or ""
    exact = parse_date(text)
    if exact:
        return exact, ""
    m = QUARTER_RE.search(text)
    if m:
        year, month = int(m.group(2)), int(m.group(1)) * 3
        return f"{year:04d}-{month:02d}-{_last_day(year, month):02d}", m.group(0)
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
    if any(m in url for m in LOGIN_URL_MARKERS):
        return True
    try:
        if page.locator("input[type='password']").count() > 0:
            return True
    except Exception:
        pass
    return False


def on_portal(page) -> bool:
    url = page.url or ""
    return (is_safe_url(url) and urlparse(url).hostname == "myaccount.ezpassva.com"
            and not looks_signed_out(page))


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
    """E-ZPass answered with a sign-in page instead of the thing asked for."""


# ---------------------------------------------------------------------------
# Requests, made from inside the signed-in page
# ---------------------------------------------------------------------------
_FETCH_JS = r"""async ([url, fragment]) => {
  const headers = fragment ? {"X-Requested-With": "XMLHttpRequest"} : {};
  const r = await fetch(url, {credentials: "include", headers});
  const ct = r.headers.get("content-type") || "";
  if (!ct.includes("pdf")) return {status: r.status, ct, url: r.url, text: await r.text()};
  const buf = new Uint8Array(await r.arrayBuffer());
  let s = "";
  for (let i = 0; i < buf.length; i += 0x8000) s += String.fromCharCode.apply(null, buf.subarray(i, i + 0x8000));
  return {status: r.status, ct, url: r.url, b64: btoa(s)};
}"""


def _get(page, url: str, fragment: bool = False) -> dict:
    """One GET from inside the page, as {status, ct, url, text|b64}. A
    sign-in answer raises SessionExpired."""
    if not is_safe_url(url):
        raise ValueError("refusing to fetch off ezpassva.com: %r" % redact(url))
    if not on_portal(page):
        raise SessionExpired("the E-ZPass tab is not on a signed-in myaccount.ezpassva.com page")
    r = page.evaluate(_FETCH_JS, [url, fragment])
    landed = (r.get("url") or "").lower()
    if (r.get("status") in (401, 403) or not is_safe_url(r.get("url") or url)
            or any(m in landed for m in LOGIN_URL_MARKERS)):
        raise SessionExpired("E-ZPass answered %s, which means the session has ended"
                             % r.get("status"))
    return r


def goto_documents(page) -> bool:
    """Be on a signed-in portal page. The fragment is same-origin, so any
    portal page serves it, and the home page is where sign-in lands."""
    try:
        if on_portal(page):
            return True
        page.goto(HOME_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)
    except Exception as e:
        log.info("goto home failed: %s", e)
    return on_portal(page)


_LINK_RE = re.compile(r"""href\s*=\s*["']([^"']*?/Statements/Download\?[^"']*)["']""", re.I)
_PARAMS_RE = re.compile(r"sType=([01])&sNum=(\d{1,2})&sYear=(\d{4})$")


def download_href(kind: str, num: int, year: int) -> str:
    return f"{DOWNLOAD_PATH}?sType={kind}&sNum={int(num)}&sYear={int(year)}"


def parse_href(href: str) -> Optional[Tuple[str, int, int]]:
    """(kind, number, year) from a download link, or None when it is not
    exactly one of this site's statement links with a sane period."""
    href = _html.unescape(href or "")
    path = urlparse(urljoin(BASE, href))
    if path.path != DOWNLOAD_PATH or not is_safe_url(urljoin(BASE, href)):
        return None
    m = _PARAMS_RE.fullmatch(path.query)
    if not m:
        return None
    kind, num, year = m.group(1), int(m.group(2)), int(m.group(3))
    if (kind == MONTHLY and not 1 <= num <= 12) or (kind == QUARTERLY and not 1 <= num <= 4):
        return None
    return kind, num, year


def title_for(kind: str, num: int, year: int) -> str:
    if kind == QUARTERLY:
        return f"Quarterly Statement - Q{num} {year}"
    return f"Monthly Statement - {_MONTH_NAMES[num - 1]} {year}"


def period_end(kind: str, num: int, year: int) -> str:
    month = num * 3 if kind == QUARTERLY else num
    return f"{year:04d}-{month:02d}-{_last_day(year, month):02d}"


def looks_like_statements(fragment_html: str) -> bool:
    """The fragment, and not a sign-in or error page served in its place."""
    return "View Online Statements" in (fragment_html or "")


def statements_in(fragment_html: str) -> List[dict]:
    """Every statement the fragment links, newest first, as {kind, num,
    year, href, title, date}. A link that does not parse is dropped, one
    listed twice is kept once."""
    seen, out = set(), []
    for raw in _LINK_RE.findall(fragment_html or ""):
        got = parse_href(raw)
        if not got or got in seen:
            continue
        seen.add(got)
        kind, num, year = got
        out.append({"kind": kind, "num": num, "year": year,
                    "href": download_href(kind, num, year),
                    "title": title_for(kind, num, year),
                    "date": period_end(kind, num, year)})
    out.sort(key=lambda s: (s["date"], s["kind"]), reverse=True)
    return out


def list_statements(page) -> List[dict]:
    r = _get(page, STATEMENTS_FRAGMENT, fragment=True)
    text = r.get("text") or ""
    if not looks_like_statements(text):
        raise SessionExpired("E-ZPass answered the statements list with another page")
    return statements_in(text)


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
    """Every statement the site lists. `href` is the download link, built
    back from its three numbers so nothing else the page wrote rides along."""
    return [RawDoc(title=s["title"], date_text=s["date"], href=s["href"],
                   text=f"E-ZPass Virginia {s['title']}")
            for s in list_statements(page)]


def download_bill(page, dl_dir, iso_date: str, out_path, href: str = "",
                  title: str = "") -> bool:
    """Fetch one statement's PDF from inside the page and write it. A
    record with no link (an index written by an older copy, say) gets it
    back from its title. `dl_dir` is unused, kept for the orchestrator."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    got = parse_href(href) if href else None
    if not got and title:
        kind = QUARTERLY if title.lower().startswith("quarterly") else MONTHLY
        q = QUARTER_RE.search(title)
        m = MONTH_YEAR_RE.search(title)
        if kind == QUARTERLY and q:
            got = (kind, int(q.group(1)), int(q.group(2)))
        elif kind == MONTHLY and m:
            got = (kind, _MONTHS[m.group(1)[:3].lower()], int(m.group(2)))
    if not got:
        log.info("no download link for %s", iso_date)
        return False
    if period_end(*got) != iso_date:
        log.info("link %s does not match the record's date %s", got, iso_date)
        return False
    if not goto_documents(page):
        return False
    r = _get(page, BASE + download_href(*got))
    if "pdf" not in (r.get("ct") or "") or not r.get("b64"):
        # A period the site no longer lists redirects to its error page.
        log.info("no PDF for %s: status %s, %s", iso_date, r.get("status"),
                 "error page" if "/home/error" in (r.get("url") or "").lower() else r.get("ct"))
        return False
    body = base64.b64decode(r["b64"])
    if body[:5] != b"%PDF-":
        return False
    out_path.write_bytes(body)
    return True


# ---------------------------------------------------------------------------
# Diagnose. What the fragment lists, as counts, and the page's own
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
    for role in ("link", "button", "tab", "combobox"):
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
    """The portal page and what the statements fragment lists, without
    downloading anything. Nothing is clicked."""
    report = {"page": _page_summary(page), "accounts": [], "api": {}}
    try:
        r = _get(page, STATEMENTS_FRAGMENT, fragment=True)
        text = r.get("text") or ""
        items = statements_in(text)
        report["api"]["statements"] = {
            "status": r.get("status"),
            "looks_like_the_list": looks_like_statements(text),
            "download_links": len(_LINK_RE.findall(text)),
            "monthly": len([s for s in items if s["kind"] == MONTHLY]),
            "quarterly": len([s for s in items if s["kind"] == QUARTERLY]),
            "newest": items[0]["date"] if items else "",
            "oldest": items[-1]["date"] if items else ""}
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
    """Nothing to expand. The list is one page fragment."""


def scroll_full_page(page, rounds: int = 0, delay_ms: int = 0) -> None:
    """Nothing to scroll. The list is one page fragment."""
