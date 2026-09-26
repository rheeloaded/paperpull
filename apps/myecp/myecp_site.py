"""ALL myecp.com selectors, URLs, and page behavior live here.

When the Exchange Credit Program changes its site, repair this file only.

STATUS: mapped 2026-09-25 against a signed-in MILITARY STAR account and
verified end to end (list, PDF).

HOW THE SITE WORKS
  MyECP (www.myecp.com) is the Exchange Credit Program's site for the
  MILITARY STAR card, an ASP.NET MVC site. Sign-in lands on
  /AccountSummary, which links each card account as
  /AccountHome/Index/<account index> (MILSTAR1, ...). The Statements tab
  loads a fragment,
      GET /AccountHome/Index/<account index>?initialview=Statements
  holding a form with a StatementId dropdown, one option per statement
  labeled by its date ("05 Sep 2026"), and a Download button whose script
  goes to
      GET /AccountStatement/GetStatement/<StatementId>
          ?downloadstatement=true&AccountIndex=<account index>
  which answers the statement as an application/pdf attachment. This app
  makes the same requests from inside the signed-in page, so nothing on
  the page is clicked.

  The StatementId is the statement's POSITION in the dropdown, 1 for the
  newest, so it moves every month. IDENTITY is the statement date, and
  the position is looked up fresh from the dropdown at download time.

NOT COVERED
  The site keeps about three and a half years, and says to contact it for
  anything older. Payment history and rewards activity are tables, not
  documents.

SAFETY (this is a credit card account):
  Strictly READ-ONLY. This module reads the statements fragment and the
  PDFs it names and nothing else. It never pays, sets up a payment,
  changes a card, applies for credit, redeems points, or edits any
  setting, and it clicks nothing at all. FORBIDDEN_CONTROL_RE and
  SAFE_DOC_CONTROL_RE are kept so the repo-wide guard tests cover this app
  the same as every other, and --diagnose uses them to grade the page.
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
from urllib.parse import urlparse

from paperpull_core.controls import SETTINGS_CONTROL_RE, AUTH_CONTROL_RE

# Everything on its way into a diagnostic file goes through here. It
# lives in core because seventeen apps each had their own copy and
# they drifted into three different versions.
from paperpull_core.redact import redact, set_private_words  # noqa: F401
from paperpull_core.urls import is_safe_url as _host_allows
from paperpull_core.dates import checked as _checked_date

log = logging.getLogger("myecp_docs.site")

# Every host this app will read from. Anything else is refused.
ALLOWED_HOSTS = {"myecp.com"}

BASE = "https://www.myecp.com"
SUMMARY_URL = BASE + "/AccountSummary"
BILLING_URL = SUMMARY_URL  # the orchestrator records it as each document's source
URLS = {
    "home": SUMMARY_URL,
    "login": BASE + "/",
    "documents": SUMMARY_URL,
    "statements": SUMMARY_URL,
}
GET_STATEMENT = "/AccountStatement/GetStatement"

LOGIN_URL_MARKERS = ["/account/login", "/account/logon", "/account/logoff", "/login",
                     "/logon", "/signin", "/timeout"]

_ACCOUNT_RE = re.compile(r"/AccountHome/Index/([A-Za-z]{2,20}\d{1,3})\b")
_OPTION_RE = re.compile(r'<option[^>]*value="(\d{1,3})"[^>]*>\s*([^<]*?)\s*</option>', re.I)
_VIEW_URL_RE = re.compile(r'id="statementsViewUrl"[^>]*data-url="([^"]+)"', re.I)

# ---------------------------------------------------------------------------
# HARD SAFETY GUARD. Tuned for a credit card. This app clicks nothing, so
# the guard grades controls for --diagnose and satisfies the repo-wide
# guard tests.
# ---------------------------------------------------------------------------
FORBIDDEN_CONTROL_RE = re.compile(
    r"(\bpay\b|payment|make\s+a?\s*payment|autopay|auto\s*pay|"
    r"\bapply\b|card\s*apply|\bcards?\b|balance\s+transfer|cash\s+advance|"
    r"points|rewards?\b|redeem|promotions?\b|products?\b|"
    r"authorized\s+users?|add\s+user|"
    r"enable|disable|change\b|edit\b|update\b|modify|manage\b|set\s+up|"
    r"delete|remove|cancel|dispute|close\s+account|"
    r"paperless|enroll|unenroll|"
    r"password|profile\b|settings|preferences|log\s*out|log\s*off|"
    r"confirm|submit|save\b|agree|accept|authorize|\bchat\b|contact\s+us)", re.I)

SAFE_DOC_CONTROL_RE = re.compile(
    r"(download|view|open|print|\bpdf\b|statements?|document|history|"
    r"see\s+(more|all|older)|show\s+(more|all|older)|load\s+more)", re.I)

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

# What the Statements tab looks like, for --diagnose only.
FALLBACK = {
    "doc_row": "#StatementId option",
    "doc_link": "#downloadsatement",
    "download_control": "#downloadsatement",
    "page_ready": "body",
    "next_page": "[aria-label*='Next' i]",
}

# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------
_MONTHS = {m[:3].lower(): i + 1 for i, m in enumerate(list(calendar.month_name)[1:])}
DAY_MONTH_YEAR_RE = re.compile(r"\b(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?,?\s+(\d{4})\b", re.I)
ISO_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})(?!\d)")
YEAR_RE = re.compile(r"\b(19|20)(\d{2})\b")


def parse_date(text):
    """"05 Sep 2026" or "2026-09-05" as YYYY-MM-DD, or None."""
    text = text or ""
    m = ISO_RE.search(text)
    if m:
        return _checked_date(f"{m.group(1)}-{m.group(2)}-{m.group(3)}", None)
    m = DAY_MONTH_YEAR_RE.search(text)
    if m:
        iso = f"{int(m.group(3)):04d}-{_MONTHS[m.group(2)[:3].lower()]:02d}-{int(m.group(1)):02d}"
        return _checked_date(iso, None)
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


def on_site(page) -> bool:
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
    """MyECP answered with a sign-in page instead of the thing asked for."""


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
    """One GET from inside the page. A sign-in answer raises SessionExpired."""
    if not is_safe_url(url):
        raise ValueError("refusing to fetch off myecp.com: %r" % redact(url))
    if not on_site(page):
        raise SessionExpired("the MyECP tab is not on a signed-in myecp.com page")
    r = page.evaluate(_FETCH_JS, [url, fragment])
    landed = urlparse(r.get("url") or url).path.lower()
    if (r.get("status") in (401, 403) or not is_safe_url(r.get("url") or url)
            or any(m in landed for m in LOGIN_URL_MARKERS)):
        raise SessionExpired("MyECP answered %s, which means the session has ended"
                             % r.get("status"))
    return r


def goto_documents(page, fresh: bool = False) -> bool:
    """Be on the Account Summary, where sign-in lands and every card
    account is linked. `fresh` loads it again even when the tab already
    shows it, because MyECP idles a session out quickly and a tab left
    on the summary still looks signed in after the session has gone. A
    reload lands on the sign-in page instead, which the run can name."""
    try:
        if not fresh and on_site(page) and "/accountsummary" in (page.url or "").lower():
            return True
        page.goto(SUMMARY_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)
    except Exception as e:
        log.info("goto summary failed: %s", e)
    return on_site(page)


def accounts_in(summary_html: str) -> List[str]:
    """Every card account index the summary links, in order, once each."""
    out = []
    for idx in _ACCOUNT_RE.findall(summary_html or ""):
        if idx not in out:
            out.append(idx)
    return out


def accounts(page) -> List[str]:
    return accounts_in(page.content())


def fragment_url(account: str) -> str:
    return f"{BASE}/AccountHome/Index/{account}?initialview=Statements"


def statements_in(fragment_html: str) -> List[dict]:
    """Every statement the fragment's dropdown lists, as {position, date,
    label}, in the site's order (newest first). An option whose label is
    not a date is dropped."""
    out, seen = [], set()
    for value, label in _OPTION_RE.findall(fragment_html or ""):
        label = _html.unescape(label).strip()
        date = parse_date(label)
        if not date or date in seen:
            continue
        seen.add(date)
        out.append({"position": int(value), "date": date, "label": label})
    return out


def looks_like_statements(fragment_html: str) -> bool:
    return 'name="StatementId"' in (fragment_html or "") and "/AccountStatement" in (fragment_html or "")


def view_url_in(fragment_html: str) -> str:
    m = _VIEW_URL_RE.search(fragment_html or "")
    return _html.unescape(m.group(1)) if m else GET_STATEMENT


def list_statements(page, account: str) -> Tuple[List[dict], str]:
    r = _get(page, fragment_url(account), fragment=True)
    text = r.get("text") or ""
    if not looks_like_statements(text):
        raise SessionExpired("MyECP answered the statements list with another page")
    view = view_url_in(text)
    if not view.startswith("/"):
        view = GET_STATEMENT
    return statements_in(text), view


def statement_url(view: str, position: int, account: str) -> str:
    return f"{BASE}{view}/{int(position)}?downloadstatement=true&AccountIndex={account}"


@dataclass
class RawDoc:
    title: str
    account: str = ""
    date_text: str = ""
    href: str = ""
    text: str = ""
    row_index: int = -1
    kind: str = "statement"


def title_for(date: str) -> str:
    y, m, d = date.split("-")
    return f"Monthly Statement - {calendar.month_name[int(m)]} {int(d)}, {y}"


def collect_download_docs(page) -> List[RawDoc]:
    """Every statement on every card account. `href` carries the account
    index (MILSTAR1), which the download needs. The account label is left
    empty when there is only one account, so filenames stay short."""
    if not goto_documents(page, fresh=True):
        raise SessionExpired("MyECP showed a sign-in page")
    accts = accounts(page)
    docs = []
    for acct in accts:
        items, _view = list_statements(page, acct)
        for s in items:
            docs.append(RawDoc(title=title_for(s["date"]), date_text=s["date"], href=acct,
                               account=acct if len(accts) > 1 else "",
                               text=f"MILITARY STAR statement {s['label']}"))
    return docs


def download_bill(page, dl_dir, iso_date: str, out_path, href: str = "",
                  title: str = "") -> bool:
    """Look the statement's current position up by its date, fetch the PDF
    from inside the page, and write it. `href` is the account index; a
    record without one uses the first account. `dl_dir` is unused."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if not goto_documents(page):
        return False
    account = href if href and re.fullmatch(r"[A-Za-z]{2,20}\d{1,3}", href) else ""
    if not account:
        accts = accounts(page)
        if not accts:
            return False
        account = accts[0]
    items, view = list_statements(page, account)
    match = next((s for s in items if s["date"] == iso_date), None)
    if not match:
        log.info("statement %s is no longer listed", iso_date)
        return False
    r = _get(page, statement_url(view, match["position"], account))
    if "pdf" not in (r.get("ct") or "") or not r.get("b64"):
        log.info("no PDF for %s: status %s, %s", iso_date, r.get("status"), r.get("ct"))
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
    """The summary page and what each account's statements list holds,
    without downloading anything. Nothing is clicked."""
    report = {"page": _page_summary(page), "accounts": [], "api": {}}
    try:
        goto_documents(page)
        accts = accounts(page)
        report["accounts"] = len(accts)
        for n, acct in enumerate(accts, 1):
            r = _get(page, fragment_url(acct), fragment=True)
            text = r.get("text") or ""
            items = statements_in(text)
            report["api"][f"account {n}"] = {
                "status": r.get("status"), "looks_like_the_list": looks_like_statements(text),
                "options": len(_OPTION_RE.findall(text)), "statements": len(items),
                "newest": items[0]["date"] if items else "",
                "oldest": items[-1]["date"] if items else "",
                "view_url_found": bool(_VIEW_URL_RE.search(text))}
    except Exception as e:
        report["error"] = str(e)[:200]
    return report


def collect_documents(page) -> List[RawDoc]:
    """Used only by --diagnose. The same list discovery reads, minus the
    account index."""
    try:
        docs = collect_download_docs(page)
    except Exception:
        return []
    for d in docs:
        d.href = ""
    return docs


def expand_all(page) -> None:
    """Nothing to expand. The list is one page fragment."""


def scroll_full_page(page, rounds: int = 0, delay_ms: int = 0) -> None:
    """Nothing to scroll. The list is one page fragment."""
