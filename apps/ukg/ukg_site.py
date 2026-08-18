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

(The UI route is `.../Pay.PayHub.Web/pay-details/{coid}/{payId}`, and its
"more actions" menu offers "Download PDF statement". That menu lives in a
shadow root, which is why plain querySelectorAll finds nothing there. The API
route above is what that menu item ends up calling.)
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
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
    return bool(SAFE_DOC_CONTROL_RE.search(name))


def is_safe_url(url: str) -> bool:
    """UKG Pro puts the verb in the path. Anything that says EDIT is refused,
    whatever else it claims to be."""
    u = (url or "")
    if re.search(r"/c/hcm/(EDIT|ADD|DELETE)/", u, re.I):
        return False
    return u.startswith(BASE) if BASE else False


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
                pdf_url=api_url(f"/pay/statements/{this_coid}/{pay_id}/pdf"),
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
    url = pdf_url
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
