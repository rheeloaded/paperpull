"""ALL Invest529 (Virginia529 / Commonwealth Savers) endpoints and page behavior.

When the site changes, repair this file only.

STATUS, mapped and verified live 2026-10-16 against a signed-in session.

  Sign-in is Okta OIDC (factory.invest529.com/iam-api/sessions/login ->
  login.invest529.com -> back to the account). The account portal is
  Ellucian Banner (myaccount.invest529.com/pls/prod/hwtk*). The two document
  areas are Angular apps whose REST API is factory.invest529.com. This app
  makes the same calls those pages make, from INSIDE the signed-in Banner
  page, so the session cookies never leave the browser. Nothing is clicked.

  AUTH: the browser's own session cookie (credentials:'include') PLUS a
  csrf-token header whose value is the CSRF-COOKIE cookie (Angular XSRF,
  cookieName "CSRF-COOKIE"). A request without the header answers 403
  {"message":"Forbidden"}.

  THE API (all on factory.invest529.com):
    * statements list  GET  /accounts/statements
        -> [{ownerPidm, ownerName, beneficiaries:[{beneficiaryPidm,
            beneficiaryName, accounts:[{accountType, accountDescription,
            minSelectDate, officialStatements:[{seqNo, startDate, endDate}]}]}]}]
    * statement pdf    POST /accounts/statement
        body {seqNo, requestType:"official", endDate, beneficiaryPidm, ownerPidm}
        -> 201 application/pdf (the bytes themselves, not JSON)
    * 1099 list        GET  /customers/1099/list
        -> {data:[{taxYear, accountNumber, correctionIndicator, identifierText}]}
    * 1099 pdf         GET  /customers/1099/{taxYear}/{accountNumber}/{correctionIndicator or "null"}
        -> application/pdf

  IDENTITY is beneficiary + period end date for a statement, and tax year +
  account for a 1099-Q, never the seqNo. The seqNo is a hint, looked up fresh
  from a new listing at download time. (An "adhoc / Create Your Own
  Statement" path exists, requestType "adhoc"; this app takes official
  quarterly statements only.)

SAFETY (this is a 529 college-savings account):
  Strictly READ-ONLY. Invest529 can contribute, withdraw, request a
  distribution, change the investment portfolio or the beneficiary, roll
  funds to a Roth IRA, and change account settings. This app must NEVER
  activate a control that does any of those, never submits a form, never
  confirms a dialog, never accepts terms. It only reads the two document
  APIs and saves the PDFs they return. An expired session raises
  SessionExpired so a run stops loudly rather than reporting empty success.
"""
from __future__ import annotations

import logging
import re
from datetime import date as _date
from pathlib import Path
from typing import List, Optional

from paperpull_core import shared_folder
from paperpull_core import intake
from paperpull_core.controls import SETTINGS_CONTROL_RE, AUTH_CONTROL_RE
from paperpull_core.controls import escape_for_locator
# Everything on its way into a diagnostic file goes through here.
from paperpull_core.redact import redact, set_private_words  # noqa: F401
from paperpull_core.urls import is_safe_url as _host_allows
from paperpull_core.api_census import shape_of as _shape
from paperpull_core.characters import whole_json
from paperpull_core.dates import checked as _checked_date

log = logging.getLogger("invest529_docs.site")

# Every host this app will read from. Anything else is refused.
ALLOWED_HOSTS = ("invest529.com",)

BASE = "https://myaccount.invest529.com"
API_BASE = "https://factory.invest529.com"
STMT_PAGE = BASE + "/pls/prod/hwtkstmt.p_renderpage_account_statement"
TAX_PAGE = BASE + "/pls/prod/hwtk1099.P_RenderPage1099q"
URLS = {
    "home": BASE + "/",
    # login.bat opens this: it begins a fresh supervised Okta sign-in.
    "login": API_BASE + "/iam-api/sessions/login",
    # The in-page API calls all run from a signed-in myaccount page; the
    # statements page is where this app does its work.
    "documents": STMT_PAGE,
    "tax": TAX_PAGE,
}
API = {
    "statements": API_BASE + "/accounts/statements",
    "statement": API_BASE + "/accounts/statement",
    "tax_list": API_BASE + "/customers/1099/list",
    # the 1099 pdf is API_BASE + "/customers/1099/{year}/{account}/{correction}"
}

# Lowercased URL fragments that mean we are on a sign-in page, not the
# signed-in account (looks_signed_out lowercases the URL first).
LOGIN_URL_MARKERS = ["login.invest529.com", "/oauth2/", "p_wwwlogin",
                     "/sessions/login", "/signin", "/authorize"]


class SessionExpired(RuntimeError):
    """Invest529 answered with a sign-in / forbidden page instead of a document."""


def is_safe_url(url: str) -> bool:
    """True only for an https URL on one of this provider's own hosts.

    The check itself lives in the core, so all of them answer the same way.
    This app keeps the hosts, which is the part that really is its own."""
    return _host_allows(url, ALLOWED_HOSTS)


# ---------------------------------------------------------------------------
# HARD SAFETY GUARD. Tuned for a 529 savings account. Never contribute, never
# withdraw, never take a distribution, never change the portfolio, the
# beneficiary, or where the money goes.
# ---------------------------------------------------------------------------
FORBIDDEN_CONTROL_RE = re.compile(
    r"(contribut|\bfund\b|\bdeposit\b|withdraw|distribution|\bpayout\b|"
    r"roll\s*over|rollover|\btransfer\b|move\s+(funds|money)|\bexchange\b|"
    r"change\s+investment|reallocat|change\s+(portfolio|allocation|beneficiar)|"
    r"cancel\s+(an?\s+)?account|close\s+account|open\s+an?\s+account|"
    r"direct\s+deposit|bank\s+(account|information)|routing|link\s+account|"
    r"gift|invite|refer\b|"
    # Word boundaries on both sides of the verb stems. "edit" inside "Credit"
    # and "chang" inside "Exchange" are the two that bite.
    r"\bchang(e|es|ed|ing)\b|\bedit(s|ed|ing)?\b|\bupdat(e|es|ed|ing)\b|"
    r"\bset\s+up\b|enroll|enable|disable|\bdelet|\bremov(e|es|ed|ing|al)\b|"
    r"\bsubmit|\bconfirm\b|\bagree\b|\baccept\b|authoriz|\bapply\b|"
    r"request\b|\bstart\b|initiate|"
    r"log\s*out|logout|sign\s*out|\bexit\b|password|username|"
    r"security\s+question|two-?step|contact\s+info|\baddress\b|\bemail\b|\bphone\b|"
    r"go\s+paperless|delivery\s+preferences|e-?delivery|manage\s+other)",
    re.I)

# What a document control may look like. A control must match this AND not
# match the blocklist.
SAFE_DOC_CONTROL_RE = re.compile(
    r"(download|\bview\b|\bopen\b|\bprint\b|\bpdf\b|statement|document|"
    r"1099|tax\s+form|tax\s+statement|tax\s+document|tax\s+information|"
    r"letter|notice|correspondence|history|annual|quarterly|monthly)", re.I)


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
SURVEY_LINK_RE = re.compile(
    r"^(documents?|statements?|account\s+statements?|tax\s+(forms?|statements?|"
    r"documents?|information)|1099.*|messages?|correspondence|history)$", re.I)


SECURITY_CHALLENGE_MARKERS = [
    "one-time passcode", "one time passcode", "enter the code", "verification code",
    "we sent a code", "text message", "authenticator", "confirm your identity",
    "verify your identity", "are you a robot", "captcha", "access denied",
    "your session has expired", "session timed out", "signed out",
    "sign in to your existing account",
]

RATE_LIMIT_MARKERS = ["too many requests", "rate limit", "try again later",
                      "temporarily unavailable", "unusual traffic"]


def looks_signed_out(page) -> bool:
    try:
        url = (page.url or "").lower()
    except Exception:
        # A page that cannot say where it is is treated as signed out, the
        # safe answer safe_selects relies on.
        return True
    if any(m in url for m in LOGIN_URL_MARKERS):
        return True
    try:
        if page.locator("input[type='password']").count() > 0:
            return True
    except Exception:
        pass
    return False


def detect_security_challenge(page) -> Optional[str]:
    """Names the passcode, CAPTCHA or throttling prompt on screen, or None.
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


def on_documents_page(page) -> bool:
    """A signed-in Banner page on this account; any of them can run the API."""
    try:
        url = page.url or ""
        return (is_safe_url(url) and "myaccount.invest529.com/pls/prod" in url
                and not looks_signed_out(page))
    except Exception:
        return False


def goto_documents(page) -> bool:
    if on_documents_page(page):
        return True
    if is_safe_url(STMT_PAGE):
        try:
            page.goto(STMT_PAGE, wait_until="domcontentloaded", timeout=30000)
            # Let Banner set the CSRF-COOKIE cookie and settle.
            page.wait_for_timeout(2500)
        except Exception as e:
            log.info("documents URL failed: %s", e)
    return on_documents_page(page)


def ensure_statements(page) -> bool:
    return goto_documents(page)


def parse_date(text):
    """A YYYY-MM-DD date out of the text, refusing a day that cannot exist."""
    s = (text or "").strip()
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})(?!\d)", s)
    return _checked_date(s[:10] if m else "", "")


# ---------------------------------------------------------------------------
# In-page fetch. One call, with the page's own session cookies and the
# csrf-token the Angular apps send, made from inside the signed-in page.
# Nothing about the session enters this process. PDFs come back base64.
# ---------------------------------------------------------------------------
_FETCH_JS = """async ({url, method, body, want}) => {
  const target = new URL(url, location.href);
  const host = target.hostname;
  if (target.protocol !== 'https:' ||
      !(host === 'invest529.com' || host.endsWith('.invest529.com'))) {
    throw new Error('Refusing an off-host request');
  }
  const csrf = (document.cookie.split(';').map(c => c.trim())
                .find(c => c.startsWith('CSRF-COOKIE=')) || '')
                .split('=').slice(1).join('=');
  const h = {'Accept': want === 'bytes' ? 'application/pdf, */*'
                                        : 'application/json, text/plain, */*'};
  if (csrf) h['csrf-token'] = csrf;
  const opts = {method: method || 'GET', credentials: 'include',
                headers: h, redirect: 'error'};
  if (body !== null && body !== undefined) {
    h['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  const r = await fetch(url, opts);
  if (want === 'bytes') {
    const bytes = await ppRead(r);
    let bin = ''; const CH = 0x8000;
    for (let i = 0; i < bytes.length; i += CH) {
      bin += String.fromCharCode.apply(null, bytes.subarray(i, i + CH));
    }
    return {status: r.status, contentType: r.headers.get('content-type') || '',
            b64: btoa(bin)};
  }
  const raw = await ppRead(r);
  let j = null;
  try { j = JSON.parse(new TextDecoder().decode(raw)); } catch (e) {}
  return {status: r.status, json: j};
}"""


def _call(page, url: str, method: str = "GET", body: Optional[dict] = None,
          want: str = "json"):
    if not is_safe_url(url):
        raise ValueError("refusing an off-host request")
    res = intake.evaluate(page, _FETCH_JS, {"url": url, "method": method,
                                    "body": body, "want": want})
    status = res.get("status")
    if status in (401, 403):
        raise SessionExpired("Invest529 answered %s" % status)
    if status not in (200, 201):
        raise RuntimeError("Invest529 answered %s for %s"
                           % (status, url.rsplit("/", 1)[-1]))
    if want == "bytes":
        b64 = res.get("b64") or ""
        return intake.decode(b64)
    return res.get("json")


# -- listings -----------------------------------------------------------------

def list_statements(page) -> list:
    """The statements tree, one owner per top-level entry."""
    j = _call(page, API["statements"])
    return j if isinstance(j, list) else []


def list_1099(page) -> list:
    """The 1099-Q rows, newest first as the API returns them."""
    j = _call(page, API["tax_list"]) or {}
    return (j.get("data") or []) if isinstance(j, dict) else []


def _statement_title(start: str, end: str) -> str:
    """Official statements are quarterly; the period says which word to use."""
    try:
        days = (_date.fromisoformat(end) - _date.fromisoformat(start)).days
    except (TypeError, ValueError):
        return "Quarterly Statement"
    if days > 200:
        return "Annual Statement"
    if days > 45:
        return "Quarterly Statement"
    return "Monthly Statement"


def _statement_rows(owners: list) -> List[dict]:
    """Flatten the statements tree into one row per official statement, in a
    stable order so a document keeps its occurrence number across runs."""
    rows: List[dict] = []
    for owner in owners or []:
        opid = str(owner.get("ownerPidm") or "")
        for bene in owner.get("beneficiaries") or []:
            bpid = str(bene.get("beneficiaryPidm") or "")
            bname = re.sub(r"\s+", " ", (bene.get("beneficiaryName") or "")).strip()
            for acct in bene.get("accounts") or []:
                for st in acct.get("officialStatements") or []:
                    end = (st.get("endDate") or "").strip()
                    if not end:
                        continue
                    start = (st.get("startDate") or "").strip()
                    seq = str(st.get("seqNo") or "")
                    rows.append({
                        "kind": "statement",
                        "title": _statement_title(start, end),
                        "date": end, "account": bname, "category": "Statement",
                        "seqNo": seq, "endDate": end,
                        "beneficiaryPidm": bpid, "ownerPidm": opid,
                        "period_start": start,
                        "item_id": seq, "client_id": "statement|%s|%s" % (bpid, opid),
                        "href": API["statement"],
                    })
    rows.sort(key=lambda r: (r["account"], r["date"], r["seqNo"]))
    return rows


def _tax_row(d: dict) -> Optional[dict]:
    year = str(d.get("taxYear") or "").strip()
    if not year:
        return None
    acct = str(d.get("accountNumber") or "")
    corr = str(d.get("correctionIndicator") or "")
    return {
        "kind": "tax", "title": "1099-Q", "date": "%s-12-31" % year,
        "account": "", "category": "Tax Document",
        "taxYear": year, "accountNumber": acct,
        "correctionIndicator": corr or "null",
        "item_id": acct, "client_id": "tax|%s" % (corr or "null"),
        "href": API_BASE + "/customers/1099/%s/%s/%s" % (year, acct, corr or "null"),
    }


def collect_documents(page, keep=None, config: Optional[dict] = None) -> List[dict]:
    """Every official statement and 1099-Q the account exposes. `keep` is the
    run's scope predicate over year labels; which kinds are asked for follows
    document_types in the config."""
    wanted = set((config or {}).get("document_types") or ["Statement", "Tax Document"])
    rows: List[dict] = []
    if "Statement" in wanted:
        for r in _statement_rows(list_statements(page)):
            if keep is None or keep(r["date"][:4]):
                rows.append(r)
    if "Tax Document" in wanted:
        for d in list_1099(page):
            r = _tax_row(d)
            if r and (keep is None or keep(r["date"][:4])):
                rows.append(r)
    return rows


def resolve_item(page, title: str, date: str, account: str,
                 occurrence: int = 0) -> Optional[dict]:
    """The document's current download parameters, from a fresh listing."""
    if re.search(r"1099", title or "", re.I):
        year = (date or "")[:4]
        matches = [r for r in (_tax_row(d) for d in list_1099(page))
                   if r and r["date"][:4] == year]
        return matches[occurrence] if occurrence < len(matches) else None
    matches = [r for r in _statement_rows(list_statements(page))
               if r["account"] == account and r["date"] == date and r["title"] == title]
    if occurrence < len(matches):
        return matches[occurrence]
    return matches[0] if matches else None


# -- download -----------------------------------------------------------------

def fetch_statement_pdf(page, seq_no: str, end_date: str,
                        beneficiary_pidm: str, owner_pidm: str) -> bytes:
    return _call(page, API["statement"], method="POST", want="bytes",
                 body={"seqNo": seq_no, "requestType": "official",
                       "endDate": end_date, "beneficiaryPidm": beneficiary_pidm,
                       "ownerPidm": owner_pidm})


def fetch_1099_pdf(page, tax_year: str, account_number: str,
                   correction: str = "null") -> bytes:
    url = API_BASE + "/customers/1099/%s/%s/%s" % (
        tax_year, account_number, correction or "null")
    return _call(page, url, method="GET", want="bytes")


def _fetch_row(page, row: dict) -> bytes:
    if row.get("kind") == "tax":
        return fetch_1099_pdf(page, row["taxYear"], row["accountNumber"],
                              row.get("correctionIndicator") or "null")
    return fetch_statement_pdf(page, row["seqNo"], row["endDate"],
                               row["beneficiaryPidm"], row["ownerPidm"])


def download_document(page, title: str, date: str, out_path: Path,
                      occurrence: int = 0, item_hint: str = "",
                      client_hint: str = "", account: str = "") -> bool:
    """Save one document. Looks it up again by kind, account and period first,
    and falls back to the stored hints only when the listing no longer shows
    it."""
    found = resolve_item(page, title, date, account, occurrence)
    if found:
        data = _fetch_row(page, found)
    elif re.search(r"1099", title or "", re.I) or (client_hint or "").startswith("tax"):
        corr = client_hint.split("|", 1)[1] if "|" in (client_hint or "") else "null"
        if not item_hint:
            log.warning("no 1099 account for %s %s", title, date)
            return False
        data = fetch_1099_pdf(page, (date or "")[:4], item_hint, corr or "null")
    else:
        parts = (client_hint or "").split("|")
        bpid = parts[1] if len(parts) > 1 else ""
        opid = parts[2] if len(parts) > 2 else ""
        if not item_hint:
            log.warning("no seqNo for %s %s", title, date)
            return False
        data = fetch_statement_pdf(page, item_hint, date, bpid, opid)
    if not data or not data.startswith(b"%PDF"):
        log.warning("not a PDF for %s %s (%d bytes)", title, date, len(data or b""))
        return False
    out_path.parent.mkdir(parents=True, exist_ok=True)
    shared_folder.write_bytes(out_path, data)
    return True


# ---------------------------------------------------------------------------
# Diagnose survey. Read-only, invest529.com pages only, no downloads, account
# numbers masked, JSON bodies recorded as shape only, no screenshot.
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


def survey(page, dwell_ms: int = 4000, max_follow: int = 6) -> dict:
    """What the signed-in document pages look like, without downloading anything."""
    seen: list = []

    def on_response(res):
        try:
            url = res.url or ""
            if not is_safe_url(url):
                return
            ct = (res.headers.get("content-type") or "").lower()
            if "json" not in ct and "pdf" not in ct:
                return
            entry = {"url": redact(url)[:200], "status": res.status, "type": ct[:40]}
            if "json" in ct:
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
                    "could not follow %r: %s" % (c["text"], str(e)[:120]))
    finally:
        try:
            page.remove_listener("response", on_response)
        except Exception:
            pass
    return report
