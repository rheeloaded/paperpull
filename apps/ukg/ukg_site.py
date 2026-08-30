"""ALL UKG selectors, URL patterns, and page behavior live here.

When UKG changes its site, repair this file only.

WHAT MAKES UKG DIFFERENT FROM THE OTHER PROVIDERS HERE
------------------------------------------------------
1. **There is no single UKG address.** Each employer runs its own tenant, and
   UKG ships several products with different page structures:

       UKG Pro (formerly UltiPro)    https://<tenant>.ultipro.com
       UKG Ready (formerly Kronos
         Workforce Ready)            https://secure<N>.saashr.com
       UKG Workforce Central         https://<host>/wfc/...

   So the base address is read from `config.json` (`base_url`) and handed to
   `configure()` at startup. It is deliberately NOT hardcoded: it varies per
   employer, and it identifies that employer, so it does not belong in a
   public repo. **This file is written against UKG Pro / UltiPro.**

2. **Sign-in varies per employer.** Some companies use a UKG username and
   password; others hand off to corporate SSO (Okta, Entra/Azure AD, Ping)
   with an MFA prompt. The tool does not care which: you sign in, it attaches
   afterwards. There is no login code here.

HOW THE DOCUMENTS ARE FOUND AND FETCHED
---------------------------------------
UKG Pro's pay area is an Angular app built from Ignite web components, and it
is fed by the same JSON API the UKG mobile app uses, proxied through the
tenant so it carries the ordinary session cookie:

    GET {API}/pay/companies
        -> [{companyId, companyName, country}]

    GET {API}/pay/payStatements/{coid}?visibleColumns=payDate
        -> [{payId, coid, companyId, docNumber, payDate, netPay, ...}]

    GET {API}/pay/statements/{coid}/{payId}/pdf
        -> application/pdf

**Nothing is ever clicked.** The list and the PDFs both come from GETs with
the session cookie, so on a site that can also change direct deposit and tax
withholding, this app never activates a control at all. The guard below still
exists because a future repair might reach for one - and on a payroll site it
should have to argue with a blocklist first.

Only PAY STATEMENTS are fetched. W-2s and other tax forms live elsewhere in
UKG (Menu -> Myself -> Pay -> Tax Forms) behind a different endpoint, and are
not read yet. The spec already routes and classifies them, so adding them is
a change to this file alone.

(The UI route is `.../Pay.PayHub.Web/pay-details/{coid}/{payId}`, and its
"more actions" menu offers "Download PDF statement". That menu lives in a
shadow root, which is why plain querySelectorAll finds nothing there. The API
route above is what that menu item ends up calling.)
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from urllib.parse import urlparse
from dataclasses import dataclass
from typing import List, Optional

log = logging.getLogger("ukg_docs.site")

# ---------------------------------------------------------------------------
# Tenant address (set from config at startup - see configure())
# ---------------------------------------------------------------------------

BASE = ""
URLS: dict = {}

PROXY = "/handlers/ExternalServicesProxy.ashx"
API = f"{PROXY}/Ultipro.Api.External/services/mobileapp/api/v1"


def configure(base_url: str) -> None:
    """Point this module at the employer's UKG tenant."""
    global BASE, URLS
    BASE = (base_url or "").rstrip("/")
    URLS = {
        "home": BASE,
        "documents": f"{BASE}/c/hcm/VIEW/PayStatements",
        "pay_overview": f"{BASE}/c/hcm/VIEW/PayOverview",
    }


def is_configured() -> bool:
    return bool(BASE)


def configuration_help() -> str:
    return (
        "No UKG address is configured.\n"
        'Open config.json and set "base_url" to your employer\'s UKG site -\n'
        "the address in your browser once you are signed in, for example\n"
        "  https://yourcompany.ultipro.com      (UKG Pro / UltiPro)\n"
        "Your employer's IT or HR portal links to it if you are unsure.")


def api_url(path: str) -> str:
    return f"{BASE}{API}{path}"


# ---------------------------------------------------------------------------
# Session / safety
# ---------------------------------------------------------------------------

LOGIN_URL_MARKERS = ["/login", "/signin", "/sign-in", "/auth", "/sso",
                     "okta.com", "microsoftonline.com", "pingidentity",
                     "adfs", "/idp/", "samlsso"]

SECURITY_CHALLENGE_MARKERS = [
    "verify your identity", "enter the code we sent", "one-time passcode",
    "two-factor", "multi-factor", "approve the request", "check your phone",
]

# Controls that must NEVER be activated. A payroll site can redirect where
# someone's wages land, so this matters more here than anywhere else in the
# project. UKG Pro helpfully encodes intent in its own URLs too - compare
# /c/hcm/VIEW/PayStatements with /c/hcm/EDIT/EePayrollDirectDepositSummary -
# which is what is_safe_url() below leans on.
FORBIDDEN_CONTROL_RE = re.compile(
    r"(direct\s+deposit|bank\s+account|routing\s+number|"
    r"tax\s+withholding|w-?4\b|withhold|allowance|"
    r"change\s+(address|name|phone|email|password|beneficiar)|"
    r"update\s+(profile|address|contact|payment)|"
    r"enroll|benefit|open\s+enrollment|life\s+event|"
    r"request\s+(time\s+off|leave)|submit|approve|delete|remove|cancel|"
    r"punch|clock\s+(in|out)|timecard)", re.I)

SAFE_DOC_CONTROL_RE = re.compile(
    r"(download|view\s+pay|print|pdf|pay\s*statement|pay\s*stub|paystub|"
    r"earnings\s+statement|w-?2\b|1095|tax\s+form|year[-\s]?end)", re.I)


def is_safe_control(name: str) -> bool:
    """Deny by default: clear the blocklist AND match the document allowlist."""
    name = (name or "").strip()
    if not name:
        return False
    if FORBIDDEN_CONTROL_RE.search(name):
        return False
    # The shared core guard is consulted as well as this app's own blocklist.
    # A repo-wide review found each app had drifted its own way and every one
    # of them let settings controls through ("Save Changes", "Document
    # Removal", "Turn off"). Centralising it means the next gap is fixed once
    # rather than nineteen times.
    try:
        from paperpull_core.controls import SETTINGS_CONTROL_RE, AUTH_CONTROL_RE
        if SETTINGS_CONTROL_RE.search(name) or AUTH_CONTROL_RE.search(name):
            return False
    except Exception:
        pass
    return bool(SAFE_DOC_CONTROL_RE.search(name))


def is_safe_url(url: str) -> bool:
    """Is this a URL we are willing to request?

    Two rules, both of which have to hold:

    * It is on the configured tenant. Compared by parsed HOST, not by string
      prefix - `https://tenant.example.com.evil.test/` and
      `https://tenant.example.com@evil.test/` both *start with* the tenant
      address while pointing somewhere else entirely.
    * Its path does not say EDIT/ADD/DELETE. UKG Pro puts the verb in the
      path, so /c/hcm/EDIT/EePayrollDirectDepositSummary is refused while
      /c/hcm/VIEW/PayStatements is allowed.
    """
    if not BASE:
        return False
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
    # credentials in a URL are never legitimate here and are a classic way to
    # disguise the real host
    if got.username or got.password:
        return False
    if re.search(r"/c/hcm/(EDIT|ADD|DELETE)/", got.path or "", re.I):
        return False
    return True


def looks_signed_out(page) -> bool:
    url = (page.url or "").lower()
    if any(m in url for m in LOGIN_URL_MARKERS):
        return True
    try:
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
# The JSON API
# ---------------------------------------------------------------------------

@dataclass
class RawDoc:
    """One pay statement, in the shape the orchestrator records."""
    title: str
    date_text: str
    pdf_url: str
    doc_number: str = ""


def parse_period_date(title: str):
    """Fallback date parsing. The API already gives an exact date, so this
    only catches a title the API could not date."""
    m = re.search(r"(20\d{2})-(\d{2})-(\d{2})", title or "")
    return (m.group(0) if m else "", "")


def _get_json(page, path):
    """GET a proxied API path using the signed-in session."""
    url = api_url(path)
    if not is_safe_url(url):
        raise RuntimeError(f"refusing to request a non-view URL: {url}")
    resp = page.context.request.get(url)
    if not resp.ok:
        log.warning("API %s returned %s", path, resp.status)
        return None
    return resp.json()


def goto_documents(page) -> bool:
    """Open the pay-statements page.

    The API calls below work on their own, but loading the page first keeps
    the session warm and gives the user something recognisable to look at.
    """
    if not is_configured():
        raise SystemExit(configuration_help())
    page.goto(URLS["documents"], wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(4000)
    return not looks_signed_out(page)


def company_ids(page) -> List[str]:
    data = _get_json(page, "/pay/companies") or []
    ids = [c.get("companyId") for c in data if c.get("companyId")]
    log.info("UKG companies: %d", len(ids))
    return ids


def _iso_from_epoch_ms(value) -> str:
    """Epoch milliseconds -> YYYY-MM-DD, read in UTC.

    UTC is deliberate, not incidental. UKG sends a date-only value as midnight
    UTC, so reading it in local time shifts every pay date back a day for
    anyone west of UTC - a silent, plausible-looking off-by-one across the
    whole archive. Verified against the dates UKG's own UI shows.
    """
    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OSError):
        return ""


def collect_documents(page) -> List[RawDoc]:
    """Every pay statement the account can see, newest first."""
    docs: List[RawDoc] = []
    for coid in company_ids(page):
        rows = _get_json(page, f"/pay/payStatements/{coid}?visibleColumns=payDate") or []
        log.info("company %s: %d pay statement(s)", coid, len(rows))
        for row in rows:
            pay_id = row.get("payId")
            if not pay_id:
                continue
            this_coid = row.get("coid") or coid
            date_text = _iso_from_epoch_ms(row.get("payDate"))
            docs.append(RawDoc(
                # Deliberately no amounts: the index records what a file IS,
                # never what it says. The row also carries netPay, grossPay,
                # taxes and deductions - none of which are kept.
                title=f"Pay Statement {date_text}".strip(),
                date_text=date_text,
                # The PATH only. The full URL would put the employer's tenant
                # into discovery.json, progress.json and the index CSV, and it
                # is not needed there - base_url rebuilds it at download time.
                pdf_url=f"/pay/statements/{this_coid}/{pay_id}/pdf",
                doc_number=str(row.get("docNumber") or "")))
    # A pay date is NOT unique: an off-cycle or bonus run lands on the same
    # date as the regular one, and identical titles would collapse to a single
    # record - silently losing a statement. Disambiguate only the dates that
    # actually repeat, so ordinary titles stay clean.
    seen = {}
    for d in docs:
        seen[d.date_text] = seen.get(d.date_text, 0) + 1
    for d in docs:
        if seen.get(d.date_text, 0) > 1 and d.doc_number:
            d.title = f"{d.title} (#{d.doc_number})"

    docs.sort(key=lambda d: (d.date_text or "", d.doc_number), reverse=True)
    return docs


def download_document(page, pdf_url: str, out_path) -> bool:
    """Save one pay statement's PDF.

    A plain GET with the session cookie - no control is clicked, no print
    dialog, no blob tab.
    """
    from pathlib import Path
    # Records store the API path; older ones may hold a full URL.
    url = pdf_url if "://" in (pdf_url or "") else api_url(pdf_url or "")
    if not is_safe_url(url):
        log.error("refusing to fetch a non-view URL")
        return False
    resp = page.context.request.get(url)
    if not resp.ok:
        log.warning("PDF fetch returned %s", resp.status)
        return False
    body = resp.body()
    if not body.startswith(b"%PDF"):
        log.warning("response was not a PDF")
        return False
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(body)
    return True
