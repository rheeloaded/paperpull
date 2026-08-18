"""ALL UKG selectors, URL patterns, and page behavior live here.

When UKG changes its site, repair this file only.

TWO THINGS MAKE UKG DIFFERENT FROM EVERY OTHER PROVIDER HERE
------------------------------------------------------------
1. **There is no single UKG address.** Each employer runs its own tenant, and
   UKG ships several products with different page structures:

       UKG Pro (formerly UltiPro)    https://<tenant>.ultipro.com
       UKG Ready (formerly Kronos
         Workforce Ready)            https://secure<N>.saashr.com
       UKG Workforce Central         https://<host>/wfc/...

   So the base address is read from `config.json` (`base_url`) and handed to
   `configure()` at startup. It is deliberately NOT hardcoded: it varies per
   employer and it identifies that employer, so it does not belong in a public
   repo.

2. **Sign-in varies per employer.** Some companies use a UKG username and
   password; others hand off to corporate SSO (Okta, Entra/Azure AD, Ping,
   ...), sometimes with a redirect chain and an MFA prompt. The tool does not
   care which: it opens the tenant address, you sign in however your company
   works, and it attaches to the session afterwards. There is no login code
   here to break, and none that could ever handle your credentials.

WHAT STILL NEEDS FILLING IN
---------------------------
The selectors below are placeholders. The pay-statement list and the download
mechanism (a real download event vs. a blob tab vs. a viewer vs. printToPDF)
have to be read off the live, signed-in page - that is the one unknown for
every new provider. Sign in, then run:

    python ukg_docs.py --diagnose

and repair the FALLBACK entries against the Diagnostics/ output.
"""
from __future__ import annotations

import logging
import re
from typing import List, Optional

log = logging.getLogger("ukg_docs.site")

# ---------------------------------------------------------------------------
# Tenant address (set from config at startup - see configure())
# ---------------------------------------------------------------------------

BASE = ""
URLS: dict = {}


def configure(base_url: str) -> None:
    """Point this module at the employer's UKG tenant.

    Called once by the orchestrator with `config["base_url"]`. Everything that
    navigates goes through URLS, so this is the only place the address enters.
    """
    global BASE, URLS
    BASE = (base_url or "").rstrip("/")
    URLS = {
        "home": BASE or "",
        # Filled in once the live site is explored - different per UKG
        # product, so they are derived from BASE rather than guessed here.
        "pay": BASE,
        "documents": BASE,
    }


def is_configured() -> bool:
    return bool(BASE)


def configuration_help() -> str:
    return (
        "No UKG address is configured.\n"
        "Open config.json and set \"base_url\" to your employer's UKG site -\n"
        "the address in your browser once you are signed in, for example\n"
        "  https://yourcompany.ultipro.com      (UKG Pro / UltiPro)\n"
        "  https://secure6.saashr.com           (UKG Ready)\n"
        "Your employer's IT or HR portal links to it if you are unsure.")


# ---------------------------------------------------------------------------
# Session / safety
# ---------------------------------------------------------------------------

# Sign-in can be UKG's own form or a corporate SSO host, so this stays broad.
LOGIN_URL_MARKERS = ["/login", "/signin", "/sign-in", "/auth", "/sso",
                     "okta.com", "microsoftonline.com", "pingidentity",
                     "adfs", "/idp/", "samlsso"]

SECURITY_CHALLENGE_MARKERS = [
    "verify your identity", "enter the code we sent", "one-time passcode",
    "two-factor", "multi-factor", "approve the request", "check your phone",
]

# Controls that must NEVER be activated. Payroll sites carry genuinely
# destructive actions - direct deposit, tax withholding, address changes -
# so this blocklist matters more here than anywhere else in the project.
FORBIDDEN_CONTROL_RE = re.compile(
    r"(direct\s+deposit|bank\s+account|routing\s+number|"
    r"tax\s+withholding|w-?4|withhold|allowance|"
    r"change\s+(address|name|phone|email|password|beneficiar)|"
    r"update\s+(profile|address|contact|payment)|"
    r"enroll|benefit|open\s+enrollment|life\s+event|"
    r"request\s+(time\s+off|leave)|submit|approve|delete|remove|cancel|"
    r"punch|clock\s+(in|out)|timecard\s+(approve|submit))", re.I)

# Only these may be activated: viewing or downloading a pay document.
SAFE_DOC_CONTROL_RE = re.compile(
    r"(download|view|print|open|pdf|pay\s*statement|pay\s*stub|paystub|"
    r"earnings\s+statement|w-?2|1095|tax\s+form|year[-\s]?end)", re.I)


def is_safe_control(name: str) -> bool:
    """Deny by default: a control must clear the blocklist AND be recognised
    as a document control before anything clicks it."""
    name = (name or "").strip()
    if not name:
        return False
    if FORBIDDEN_CONTROL_RE.search(name):
        return False
    return bool(SAFE_DOC_CONTROL_RE.search(name))


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
# Pay documents  (PLACEHOLDERS - repair after --diagnose on the live site)
# ---------------------------------------------------------------------------

FALLBACK = {
    "pay_row": "[data-automation*='payStatement'], tr[class*='pay'], "
               "[class*='PayStatement'], [class*='paystub']",
    "date_cell": "[data-automation*='date'], td:first-child",
    "download_control": "a[href*='.pdf'], button[title*='Download' i], "
                        "[aria-label*='Download' i]",
    "page_ready": "[data-automation], main, #root",
}

DATE_RE = re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b")


def parse_date(text: str) -> Optional[str]:
    m = DATE_RE.search(text or "")
    if not m:
        return None
    mm, dd, yyyy = m.groups()
    return f"{int(yyyy):04d}-{int(mm):02d}-{int(dd):02d}"


def goto_documents(page) -> bool:
    """Navigate to the pay-statement list. Filled in after exploration."""
    if not is_configured():
        raise SystemExit(configuration_help())
    page.goto(URLS["home"], wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(3000)
    return not looks_signed_out(page)


def collect_documents(page) -> List[dict]:
    """One dict per pay document: date_text, title, and how to fetch it.

    NOT YET IMPLEMENTED - needs the live DOM.
    """
    log.warning("collect_documents is not implemented yet; run --diagnose "
                "against the signed-in site and repair ukg_site.py")
    return []


def download_document(page, doc: dict, out_path) -> bool:
    """Save one document's PDF. NOT YET IMPLEMENTED - needs the live DOM."""
    log.warning("download_document is not implemented yet")
    return False
