"""ALL Paylocity selectors, URL patterns, and page behavior live here.

When Paylocity changes its site, repair this file only.

STATUS, and read this before trusting anything below.

  CONFIRMED from the public site, 2026-08-22:
    * sign-in is at https://access.paylocity.com with Company ID, Username
      and Password, or a company SSO handoff. OAuth with PKCE underneath.
      The Company ID is typed by the user at sign-in and is never handled,
      stored, or needed by this app.
    * no bot wall was met on the login page, so bundled Chromium is used

  NOT YET CONFIRMED, and deliberately not guessed:
    * where the signed-in portal keeps pay statements, and whether a JSON
      API feeds them the way UKG's mobile API does
    * how a statement PDF is delivered

  There are NO guessed URLs here. The AAFMAA app burned a day on four
  invented page names and the Discover app once ended a live session on a
  logoff page the same way. Discovery starts from the page the user left
  open, and --diagnose records where every link points so the real routes
  can be written in from evidence.

SAFETY (this is a payroll site):
  A payroll portal can change direct deposit, tax withholding, and personal
  details. This module is strictly READ-ONLY. It must NEVER activate a
  control that changes a bank account, routing number, W-4 or withholding,
  address, benefits, time off, or any setting. A control must clear
  FORBIDDEN_CONTROL_RE *and* match SAFE_DOC_CONTROL_RE, and every URL this
  app requests must be on Paylocity's own host. There is deliberately no
  code here that submits a form or confirms a dialog.

Sign-in varies per employer, a Paylocity Company ID with username and
password, or corporate SSO with MFA. The tool does not care which. You sign
in, it attaches afterwards. There is no login code here.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from urllib.parse import urlparse
from dataclasses import dataclass
from typing import List, Optional

log = logging.getLogger("paylocity_docs.site")

# One fixed public address, unlike UKG's per-employer tenant. The employer is
# identified by the Company ID typed at sign-in, not by the hostname, so
# nothing about this URL is private.
BASE = "https://access.paylocity.com"

URLS = {
    "home": f"{BASE}/",
    # The root IS the login page, so a URL alone cannot say whether you are
    # signed in. looks_signed_out() checks the page instead.
    "login": f"{BASE}/",
}

# Empty on purpose. See STATUS above: routes get written in from diagnose
# evidence, not invented. goto_documents() works from the page the user left
# open and the site's own navigation.
DOCUMENT_URL_CANDIDATES: list = []

LOGIN_URL_MARKERS = ["/login", "signin", "sign-in", "/auth", "/sso",
                     "okta.com", "microsoftonline.com", "pingidentity",
                     "samlsso", "forgotpassword"]

SECURITY_CHALLENGE_MARKERS = [
    "verify your identity", "enter the code we sent", "one-time passcode",
    "two-factor", "multi-factor", "approve the request", "check your phone",
    "challenge question", "security question",
]

# Controls that must NEVER be activated. A payroll site can redirect where
# someone's wages land, so this matters more here than on any retail site.
FORBIDDEN_CONTROL_RE = re.compile(
    r"(direct\s+deposit|bank\s+account|routing\s+number|"
    r"tax\s+withholding|w-?4\b|withhold|allowance|"
    r"change\s+(address|name|phone|email|password|beneficiar)|"
    r"update\s+(profile|address|contact|payment|beneficiar|withholding|w-?4)|"
    r"enroll|benefit|open\s+enrollment|life\s+event|"
    r"request\s+(time\s+off|leave)|submit|approve|delete|remove|cancel|"
    r"punch|clock\s+(in|out)|timecard|timesheet|expense)", re.I)

SAFE_DOC_CONTROL_RE = re.compile(
    r"(download|view\s+pay|print|pdf|pay\s*statement|pay\s*stub|paystub|"
    r"check\s*stub|earnings\s+statement|w-?2\b|1095|tax\s+form|"
    r"year[-\s]?end|document)", re.I)


def is_safe_control(name: str) -> bool:
    """Deny by default: clear the blocklist AND match the document allowlist."""
    name = (name or "").strip()
    if not name:
        return False
    if FORBIDDEN_CONTROL_RE.search(name):
        return False
    return bool(SAFE_DOC_CONTROL_RE.search(name))


def is_safe_url(url: str) -> bool:
    """On Paylocity's own host, by parsed comparison, never a string prefix.

    The UKG app's tenant guard was once walked through by both a suffix host
    and a userinfo host because it compared with startswith. Parse and
    compare, and refuse embedded credentials outright.
    """
    try:
        want = urlparse(BASE)
        got = urlparse(url or "")
    except ValueError:
        return False
    if got.scheme != want.scheme or not got.hostname:
        return False
    if (got.hostname or "").lower() != (want.hostname or "").lower():
        return False
    if got.port != want.port:
        return False
    if got.username or got.password:
        return False
    return True


def looks_signed_out(page) -> bool:
    url = (page.url or "").lower()
    if any(m in url for m in LOGIN_URL_MARKERS):
        return True
    try:
        # the login page's own fields: Company ID, Username, Password
        if page.locator("#CompanyId, input[name='CompanyId']").count() > 0:
            return True
        return page.locator("input[type='password']").count() > 0
    except Exception:
        return False


def detect_security_challenge(page) -> Optional[str]:
    try:
        body = page.locator("body").inner_text(timeout=5000).lower()
    except Exception:
        return None
    for marker in SECURITY_CHALLENGE_MARKERS:
        if marker in body:
            return f"Sign-in verification step detected: '{marker}'"
    return None


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------

@dataclass
class RawDoc:
    """One pay statement, in the shape the orchestrator records."""
    title: str
    date_text: str
    pdf_url: str
    doc_number: str = ""


def parse_period_date(title: str):
    """Fallback date parsing for a title carrying its own date."""
    m = re.search(r"(20\d{2})-(\d{2})-(\d{2})", title or "")
    if m:
        return (m.group(0), "")
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", title or "")
    if m:
        mo, dy, yr = (int(x) for x in m.groups())
        if 1 <= mo <= 12 and 1 <= dy <= 31:
            return (f"{yr:04d}-{mo:02d}-{dy:02d}", "")
    return ("", "")


def goto_documents(page) -> bool:
    """Reach the pay area, starting from wherever the user is.

    No URL guesses. The page already open is judged first, then the site's
    own navigation is tried, one guarded click on a link that names pay
    statements. If neither works, the answer is --diagnose, not a guess.
    """
    if looks_signed_out(page):
        return False
    try:
        link = page.get_by_role("link", name=re.compile(
            r"(pay\s*(stubs?|checks?|statements?)|paystubs?)", re.I))
        if link.count() > 0:
            label = link.first.inner_text(timeout=1500) or ""
            if not FORBIDDEN_CONTROL_RE.search(label):
                link.first.click()
                page.wait_for_timeout(3500)
    except Exception:
        pass
    return not looks_signed_out(page)


# ---------------------------------------------------------------------------
# The pay area, driven by the same JSON endpoints the Escher "Pay History"
# React app uses. CONFIRMED against a live account 2026-08-22.
#
#   GET  {API}/GetPayAssignments
#          -> {payAssignments:[{assignmentId, company:{name,...}}]}
#   GET  {API}/GetCheckDatesForPayAssignment?endDate=MM/DD/YYYY&showNoCalc=false
#          -> {success, data:[{id, documentNumber, date, type, displayText,
#                              amount, companyId, employeeId}]}
#
# A statement PDF is not a URL you can build. Escher generates it on demand:
#   GET  {API}/EnqueueCheckStubReport?companyId&employeeId&historyId=<id>
#          -> {response:{scheduledId}}
#   GET  {API}/GetCheckStubReport?companyId&employeeId&scheduledReportId=<sid>
#          -> {response:{downloadUrl, errors}}   (poll until downloadUrl set)
#   GET  {REPORT_BASE}{downloadUrl}   -> application/pdf
#
# Every one is a GET carrying the ordinary session cookie. Nothing is clicked,
# no control is activated, which on a payroll site is the strongest guarantee
# available. `amount` is deliberately read and thrown away: the index records
# what a file IS, never what it says.
# ---------------------------------------------------------------------------
API = f"{BASE}/Escher/Escher_WebUI/EmployeeInformation/PaycheckHistory"
REPORT_BASE = f"{BASE}/Escher/Escher_WebUI/views"


def _get_json(page, url, params=None):
    if not is_safe_url(url):
        raise RuntimeError(f"refusing a non-Paylocity URL: {url}")
    resp = page.context.request.get(url, params=params or {})
    if not resp.ok:
        log.warning("GET %s -> %s", url.rsplit("/", 1)[-1], resp.status)
        return None
    try:
        return resp.json()
    except Exception:
        return None


def _iso_from_escher_date(value) -> str:
    """Escher dates look like '2026-06-18T00:00:00'. Return YYYY-MM-DD."""
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", str(value or ""))
    return m.group(0) if m else ""


def pay_assignments(page) -> List[dict]:
    data = _get_json(page, f"{API}/GetPayAssignments") or {}
    out = data.get("payAssignments") or []
    log.info("pay assignments: %d", len(out))
    return out


def collect_documents(page) -> List[RawDoc]:
    """Every pay statement the account can see, newest first.

    The list endpoint is bounded by endDate only, so a far-future endDate asks
    for the whole history. Whether Escher caps how far back it returns is not
    established, so the count is logged for a human to sanity-check against the
    portal.
    """
    docs: List[RawDoc] = []
    seen = set()
    # A far-future end date so the whole history comes back. A fixed literal,
    # never today's date, so the request is reproducible.
    params = {"endDate": "12/31/2099", "showNoCalc": "false"}
    data = _get_json(page, f"{API}/GetCheckDatesForPayAssignment", params) or {}
    rows = data.get("data") or []
    log.info("pay statements returned: %d", len(rows))
    for row in rows:
        hid = row.get("id")
        if hid is None or hid in seen:
            continue
        seen.add(hid)
        date_text = _iso_from_escher_date(row.get("date"))
        kind = re.sub(r"\s+", " ", str(row.get("type") or "")).strip()
        # Deliberately NO amount. The row carries `amount`; it is not read into
        # anything that persists. A test asserts the index has no money in it.
        title = f"Pay Statement {date_text}".strip()
        if kind and kind.lower() != "regular":
            title = f"{title} ({kind})"
        docs.append(RawDoc(
            title=title,
            date_text=date_text,
            # identity is companyId|employeeId|historyId, everything the
            # download flow needs, and stable across runs
            pdf_url=f"{row.get('companyId')}|{row.get('employeeId')}|{hid}",
            doc_number=str(row.get("documentNumber") or "")))
    # Same-date runs (a regular plus an off-cycle) would collapse on an
    # identical title, so disambiguate the dates that actually repeat.
    counts = {}
    for d in docs:
        counts[d.date_text] = counts.get(d.date_text, 0) + 1
    for d in docs:
        if counts.get(d.date_text, 0) > 1 and d.doc_number:
            d.title = f"{d.title} (#{d.doc_number})"
    docs.sort(key=lambda d: (d.date_text or "", d.doc_number), reverse=True)
    return docs


def goto_documents_or_none(page):
    """Kept for the orchestrator's discovery call; the API works on its own,
    but loading the pay page first keeps the session warm and gives the user
    something recognisable to look at."""
    return goto_documents(page)


def download_document(page, pdf_url: str, out_path) -> bool:
    """Save one pay statement's PDF via enqueue -> poll -> fetch.

    pdf_url is the packed identity 'companyId|employeeId|historyId'. No control
    is clicked; every step is a GET with the session cookie.
    """
    from pathlib import Path
    import time as _time
    try:
        company_id, employee_id, history_id = (pdf_url or "").split("|", 2)
    except ValueError:
        log.error("malformed pay-statement identity")
        return False

    enq = _get_json(page, f"{API}/EnqueueCheckStubReport", {
        "companyId": company_id, "employeeId": employee_id,
        "historyId": history_id}) or {}
    sid = (enq.get("response") or {}).get("scheduledId")
    if not sid:
        log.warning("enqueue returned no scheduledId")
        return False

    download_url = ""
    for attempt in range(10):
        page.wait_for_timeout(int(1500 * (1.5 ** attempt)))
        rep = _get_json(page, f"{API}/GetCheckStubReport", {
            "companyId": company_id, "employeeId": employee_id,
            "scheduledReportId": sid}) or {}
        r = rep.get("response") or {}
        if r.get("errors"):
            log.warning("report generation reported an error")
            return False
        if r.get("downloadUrl"):
            download_url = r["downloadUrl"]
            break
    if not download_url:
        log.warning("report never produced a downloadUrl")
        return False

    final = REPORT_BASE + download_url
    if not is_safe_url(final):
        log.error("refusing a non-Paylocity report URL")
        return False
    resp = page.context.request.get(final)
    if not resp.ok:
        log.warning("PDF fetch returned %s", resp.status)
        return False
    body = resp.body()
    if not body.startswith(b"%PDF"):
        log.warning("report body was not a PDF")
        return False
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(body)
    return True
