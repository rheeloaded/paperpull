"""American Express Business Banking selectors, URLs, and API handling.

SAFETY:
  This module is strictly READ-ONLY. It navigates to the business checking
  statements/documents area, reads document lists, and downloads PDFs that Amex
  already generated. It must NEVER activate any control that moves money,
  transfers funds, pays bills, makes deposits, requests loans, or changes any
  account setting.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional

from paperpull_core import intake
from paperpull_core.dates import last_day as _last_day
from paperpull_core.dates import MONTH_NAMES
from paperpull_core.words import words_for as _words_for

log = logging.getLogger("amexbanking_docs.site")


def _words():
    return _words_for("American Express Business", sys.modules[__name__])


BASE = "https://business.americanexpress.com"
URLS = {
    "home": "https://www.americanexpress.com/",
    "login": "https://www.americanexpress.com/en-us/account/login/",
    "dashboard": "https://business.americanexpress.com/",
    "documents": "https://business.americanexpress.com/",
    "statements": "https://business.americanexpress.com/",
}

LOGIN_URL_MARKERS = [
    "/login", "/logon", "/signin", "/sign-in", "/auth",
    "/mfa", "/verification", "/challenge", "myca/logon"
]

FORBIDDEN_CONTROL_RE = re.compile(
    r"(pay\b|pay\s+bill|make\s+a?\s*payment|autopay|auto\s*pay|"
    r"transfer|wire\b|withdraw|deposit|move\s+money|send\s+money|"
    r"apply|apply\s+now|open\s+(a\s+)?(new\s+)?account|new\s+account|"
    r"link\s+(bank|account)|order\b|give\b|gift|rewards?\b|line\s+of\s+credit|"
    r"download\s+(the\s+)?app|"
    r"close\s+account|lock\b|freeze\b|dispute|report\s+fraud|"
    r"change\s+password|edit\s+profile|update\s+address|manage\b|"
    r"delete|remove|enroll|subscribe|confirm|submit)", re.I
)

# Words that name a document, not words that name an action: "open" and
# "view" alone also start "Open New Account" and "View All Gift Cards".
SAFE_DOC_CONTROL_RE = re.compile(
    r"(download|print|pdf|statements?\b|documents?\b|summary|"
    r"tax\b|1099|1098)", re.I
)

SECURITY_CHALLENGE_MARKERS = [
    "enter the code", "verification code", "6-digit", "one-time code",
    "two-factor", "two-step", "authenticator", "confirm your identity",
    "verify your identity", "we sent a code", "check your email",
    "check your phone", "your session has expired", "log back in",
    "are you a robot", "captcha", "unusual activity",
]

RATE_LIMIT_MARKERS = [
    "too many requests", "rate limit", "try again later", "temporarily unavailable"
]

ALLOWED_HOSTS = {"americanexpress.com"}


def is_safe_url(url: str) -> bool:
    """True only for an https URL on an allowed American Express host."""
    from paperpull_core.urls import is_safe_url as _host_allows
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


def detect_security_challenge(page) -> Optional[str]:
    try:
        title = (page.title() or "").lower()
    except Exception:
        title = ""
    try:
        body = page.locator("body").inner_text(timeout=3000).lower()
    except Exception:
        body = ""
    hay = title + "\n" + body[:1500]
    for m in SECURITY_CHALLENGE_MARKERS:
        if m in hay:
            return f"Security challenge detected: '{m}'"
    return None


def _forbidden(name: str) -> bool:
    if FORBIDDEN_CONTROL_RE.search(name):
        return True
    try:
        from paperpull_core.controls import SETTINGS_CONTROL_RE, AUTH_CONTROL_RE
        if SETTINGS_CONTROL_RE.search(name) or AUTH_CONTROL_RE.search(name):
            return True
    except Exception:
        pass
    return False


def is_safe_control(name: str) -> bool:
    name = (name or "").strip()
    if not name:
        return False
    if _forbidden(name):
        return False
    return bool(SAFE_DOC_CONTROL_RE.search(name))


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class RawDoc:
    title: str
    date_text: str = ""
    href: str = ""
    text: str = ""
    account: str = ""
    category: str = "Statement"
    tag: str = ""
    document_id: str = ""
    account_token: str = ""
    document_size: str = ""
    row_index: int = 0
    kind: str = "doc"

    def get(self, key: str, default=None):
        if key == "date":
            return self.date_text or default
        if key in ("documentId", "document_id"):
            return self.document_id or self.href or self.tag or default
        return getattr(self, key, default)

    def __getitem__(self, key: str):
        val = self.get(key)
        if val is None:
            raise KeyError(key)
        return val


@dataclass
class BankingSession:
    account_token: str = ""
    account_label: str = ""
    label_configured: bool = False
    list_url: str = ""
    download_url: str = ""
    captured_docs: List[RawDoc] = field(default_factory=list)


SESSION = BankingSession()


# ---------------------------------------------------------------------------
# Document List Parsing
# ---------------------------------------------------------------------------

def _parse_month_num(raw_month: Any) -> Optional[int]:
    """Parse month representation into an integer 1..12."""
    if not raw_month:
        return None
    s = str(raw_month).strip()
    if s.isdigit():
        val = int(s)
        return val if 1 <= val <= 12 else None
    s_lower = s.lower()
    for idx, name in enumerate(MONTH_NAMES, start=1):
        if s_lower == name.lower() or s_lower == name[:3].lower():
            return idx
    return None


def parse_banking_document_list(data: dict, account_label: str = "Business Checking",
                                account_token: str = "") -> List[RawDoc]:
    """Parse ReadBankingAccountDocumentList.v1 JSON response payload."""
    docs: List[RawDoc] = []
    if not isinstance(data, dict):
        return docs

    statements = data.get("statements")
    if not isinstance(statements, list):
        return docs

    for idx, item in enumerate(statements):
        if not isinstance(item, dict):
            continue

        doc_id = str(item.get("documentIdentifier") or item.get("documentId") or item.get("id") or item.get("tag") or "").strip()
        doc_size = str(item.get("documentSize") or "").strip()
        acct_token = str(item.get("accountToken") or account_token).strip()
        tag = str(item.get("tag") or doc_id).strip()

        # 1. Check if it's a tax document
        tax_year = item.get("taxYear")
        tax_form_type = item.get("taxFormType")
        if tax_year and tax_form_type:
            try:
                y = int(str(tax_year).strip())
                date_iso = f"{y:04d}-12-31"
            except Exception:
                date_iso = f"{tax_year}-12-31"

            title = f"{tax_form_type} Tax Form"
            docs.append(RawDoc(
                title=title,
                date_text=date_iso,
                href=doc_id,
                category="Tax Document",
                tag=tag,
                document_id=doc_id,
                account=account_label,
                account_token=acct_token,
                document_size=doc_size,
                row_index=idx,
            ))
            continue

        # 2. Check if it's a monthly statement
        month_raw = item.get("statementMonth")
        year_raw = item.get("statementYear")
        if month_raw and year_raw:
            try:
                m = _parse_month_num(month_raw)
                y = int(str(year_raw).strip())
                if m and 1990 <= y <= 2099:
                    day = _last_day(y, m)
                    date_iso = f"{y:04d}-{m:02d}-{day:02d}"
                else:
                    date_iso = f"{year_raw}-{str(month_raw).zfill(2)}-01"
            except Exception:
                date_iso = f"{year_raw}-{str(month_raw).zfill(2)}-01"

            title = f"{account_label} Statement"
            docs.append(RawDoc(
                title=title,
                date_text=date_iso,
                href=doc_id,
                category="Statement",
                tag=tag,
                document_id=doc_id,
                account=account_label,
                account_token=acct_token,
                document_size=doc_size,
                row_index=idx,
            ))
            continue

    return docs


# ---------------------------------------------------------------------------
# Network Interception
# ---------------------------------------------------------------------------

def _token_of(request) -> str:
    """The accountToken a banking API request was posted with, or ""."""
    try:
        post_data = request.post_data
        if post_data:
            tok = json.loads(post_data).get("accountToken")
            if tok:
                return str(tok)
    except Exception:
        pass
    return ""


_ACCOUNT_URL_RE = re.compile(r"/banking/(business|personal)/(checking|savings)", re.I)
_TOKEN_URL_RE = re.compile(r"/accounts/([a-zA-Z0-9_-]{20,})")


def account_kind_from_url(url: str) -> str:
    """The kind of account a banking page is for, read from its address,
    for when no label is configured or shown: "Business Checking",
    "Business Savings", "Personal Checking" or "Personal Savings"."""
    m = _ACCOUNT_URL_RE.search(url or "")
    if m:
        return f"{m.group(1).title()} {m.group(2).title()}"
    return "American Express Banking"


def attach_banking_listener(page, session: BankingSession = SESSION) -> None:
    """Attach Playwright request/response listener to capture Amex Banking API traffic."""
    if getattr(page, "_banking_listener_attached", False):
        return
    page._banking_listener_attached = True

    def on_request(request):
        url = request.url or ""
        if "ReadBankingAccountDocumentList" in url or "ReadBankingDocument" in url:
            if is_safe_url(url):
                if "ReadBankingAccountDocumentList" in url:
                    session.list_url = url
                elif "ReadBankingDocument" in url:
                    session.download_url = url
                # The page's latest request names the account it is on now,
                # so it replaces whatever an earlier account left here.
                tok = _token_of(request)
                if tok:
                    session.account_token = tok

    def on_response(response):
        url = response.url or ""
        if "ReadBankingAccountDocumentList" in url and is_safe_url(url):
            session.list_url = url
            try:
                if response.status == 200:
                    data = response.json()
                    label = session.account_label or account_kind_from_url(page.url or "")
                    # The token this list was asked for, not the session's,
                    # which another account's request may have changed since.
                    token = _token_of(response.request) or session.account_token
                    new_docs = parse_banking_document_list(data, account_label=label, account_token=token)
                    if new_docs:
                        session.captured_docs.extend(new_docs)
                        log.info("Captured %d documents from banking response", len(new_docs))
            except Exception as e:
                log.debug("Could not parse banking response: %s", e)

    page.on("request", on_request)
    page.on("response", on_response)


# ---------------------------------------------------------------------------
# Page Navigation & Document Collection
# ---------------------------------------------------------------------------

DOCUMENTS_URL = "https://www.americanexpress.com/en-us/banking/business/checking/accounts/manage/documents"

_SWITCHER_COMBOBOX_SEL = "[data-testid='simple_switcher_combobox'], [data-test-id='simple_switcher_combobox']"
_SWITCHER_SELECTED_DISPLAY_SEL = "[data-testid='simple_switcher_selected_option_display'], [data-test-id='simple_switcher_selected_option_display']"
_SWITCHER_NAME_SEL = "[data-testid='simple_switcher_display_name'], [data-test-id='simple_switcher_display_name']"
_SWITCHER_NUM_SEL = "[data-testid='simple_switcher_display_number'], [data-test-id='simple_switcher_display_number']"


def clean_account_name(raw: str) -> str:
    s = re.sub(r"[®™]", "", raw or "")
    return re.sub(r"\s+", " ", s).strip()


def detect_account_label(page) -> str:
    """Read the current account's display name and digits from the switcher or page."""
    try:
        for sel in (_SWITCHER_SELECTED_DISPLAY_SEL, _SWITCHER_COMBOBOX_SEL):
            loc = page.locator(sel)
            if loc.count() > 0 and loc.first.is_visible():
                container = loc.first
                name_el = container.locator(_SWITCHER_NAME_SEL)
                num_el = container.locator(_SWITCHER_NUM_SEL)
                name = clean_account_name(name_el.first.inner_text()) if name_el.count() and name_el.first.is_visible() else ""
                num = num_el.first.inner_text() if num_el.count() and num_el.first.is_visible() else ""
                digits = re.sub(r"\D", "", num)
                if digits and len(digits) >= 4:
                    digits = digits[-4:]
                if name and digits:
                    return f"{name} {digits}"
                if name:
                    return name
    except Exception:
        pass

    try:
        text = page.locator("header, main, [role='main']").first.inner_text()
        m = re.search(r"([A-Za-z0-9\s_-]{2,30})\s*(?:[-–—•\*\.]+|\([•\*\.\s]*)\s*(\d{4,5})\b", text)
        if m:
            c_name = clean_account_name(m.group(1))
            c_digits = m.group(2)[-4:]
            if not any(w in c_name.lower() for w in ("routing", "transit", "swift", "balance", "available", "statement")):
                return f"{c_name} {c_digits}"
    except Exception:
        pass

    return ""


def on_documents_page(page) -> bool:
    url = (page.url or "").lower()
    return "/accounts/manage/documents" in url or ("/accounts/" in url and "/documents" in url)


def goto_documents(page, session: BankingSession = SESSION) -> bool:
    """Ensure page is on the Documents and Statements area and documents are fetched."""
    if looks_signed_out(page):
        return False
    attach_banking_listener(page, session)
    if on_documents_page(page):
        log.info("Already on documents page; reloading to trigger document fetch...")
        try:
            page.reload(wait_until="domcontentloaded")
            waited = 0
            while not session.captured_docs and waited < 15000:
                page.wait_for_timeout(500)
                waited += 500
            if session.captured_docs:
                page.wait_for_timeout(1500)
        except Exception as e:
            log.warning("Reload failed: %s", e)
        return bool(session.captured_docs)

    log.info("Navigating to %s...", DOCUMENTS_URL)
    try:
        page.goto(DOCUMENTS_URL, wait_until="domcontentloaded", timeout=30000)
        waited = 0
        while not session.captured_docs and waited < 15000:
            page.wait_for_timeout(500)
            waited += 500
        if session.captured_docs:
            page.wait_for_timeout(1500)
    except Exception as e:
        log.warning("Navigation to documents page failed: %s", e)

    return bool(session.captured_docs)


def ensure_statements(page, session: BankingSession = SESSION) -> bool:
    """Ensure page is on American Express and listener is active."""
    if looks_signed_out(page):
        return False
    attach_banking_listener(page, session)
    # Read the account each time: the switcher may have moved to another one.
    if not session.label_configured:
        detected = detect_account_label(page)
        if detected:
            session.account_label = detected
    m = _TOKEN_URL_RE.search(page.url or "")
    if m:
        session.account_token = m.group(1)
    elif not session.account_token:
        try:
            m_dom = _TOKEN_URL_RE.search(page.content())
            if m_dom:
                session.account_token = m_dom.group(1)
        except Exception:
            pass
    if not session.list_url:
        session.list_url = "https://functions.americanexpress.com/ReadBankingAccountDocumentList.v1"
    if not session.download_url:
        session.download_url = "https://functions.americanexpress.com/ReadBankingDocument.v1"
    return is_safe_url(page.url or "")


def collect_documents(page, session: BankingSession = SESSION) -> List[RawDoc]:
    """Collect all statements and tax documents known for this account."""
    ensure_statements(page, session)

    if not session.captured_docs:
        goto_documents(page, session)

    # Deduplicate and return captured documents
    seen = set()
    deduped = []
    for d in session.captured_docs:
        k = (d.category, d.date_text, d.document_id or d.tag or d.href)
        if k not in seen:
            seen.add(k)
            deduped.append(d)
    log.info("collect_documents found %d documents", len(deduped))
    return deduped


# ---------------------------------------------------------------------------
# Binary Download
# ---------------------------------------------------------------------------

def _write_if_pdf(data: bytes, out_path: Path) -> bool:
    """Atomically write binary data to out_path if it begins with %PDF-."""
    if not data or b"%PDF-" not in data[:1024]:
        return False
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = out_path.with_suffix(f".tmp.{os.getpid()}")
    try:
        tmp_path.write_bytes(data)
        os.replace(tmp_path, out_path)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink()
        raise
    return True


def amexbanking_download(page, doc: RawDoc, out_path: Path,
                          session: BankingSession = SESSION, **kw) -> bool:
    """Download statement PDF via authenticated ReadBankingDocument API."""
    doc_id = getattr(doc, "document_id", "") or getattr(doc, "href", "") or getattr(doc, "tag", "")
    if not doc_id:
        log.warning("No document id provided for %s %s", getattr(doc, "category", ""), getattr(doc, "date_text", ""))
        return False

    download_url = session.download_url or "https://functions.americanexpress.com/ReadBankingDocument.v1"
    token = getattr(doc, "account_token", "") or session.account_token
    if not token:
        m = _TOKEN_URL_RE.search(page.url or "")
        if m:
            token = m.group(1)
            session.account_token = token
        else:
            try:
                m_dom = _TOKEN_URL_RE.search(page.content())
                if m_dom:
                    token = m_dom.group(1)
                    session.account_token = token
            except Exception:
                pass

    if not token:
        log.warning("No accountToken found for downloading %s (%s)", getattr(doc, "title", ""), doc_id)
        return False

    body_data = {
        "accountToken": token,
        "bankingDocument": {"identifier": doc_id}
    }
    # Fetched inside the signed-in page, so its own cookies go with it. The
    # URL and body are passed as arguments, never pasted into the script.
    js = (
        "async ([url, body]) => {"
        "  const res = await fetch(url, {"
        "    method: 'POST',"
        "    credentials: 'include',"
        "    headers: {'Content-Type': 'application/json', 'Accept': 'application/json'},"
        "    body: JSON.stringify(body)"
        "  });"
        "  return await res.json();"
        "}"
    )

    try:
        result = page.evaluate(js, [download_url, body_data])
    except Exception as e:
        log.warning("In-page fetch failed for %s (%s): %s", getattr(doc, "title", ""), doc_id, e)
        return False

    if not isinstance(result, dict):
        log.warning("Document download failed for %s (%s): %s", getattr(doc, "title", ""), doc_id, result)
        return False

    content_str = result.get("documentContent") or ""
    if not content_str:
        log.warning("Empty documentContent received for %s (%s)", getattr(doc, "title", ""), doc_id)
        return False

    try:
        pdf_bytes = intake.decode(content_str)
    except Exception as e:
        log.warning("Could not decode document content for %s: %s", getattr(doc, "title", ""), e)
        return False

    return _write_if_pdf(pdf_bytes, out_path)

