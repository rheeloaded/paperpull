"""ALL PG&E (pge.com) selectors, URLs, and page behavior live here.

When PG&E changes its site, repair this file only.

SAFETY (this is a utility billing account):
  This module is strictly READ-ONLY. It navigates to the billing-history
  area, reads the list of bills, and downloads the PDFs PG&E already
  generated. It must NEVER activate any control that pays a bill, sets up
  AutoPay or a payment plan, adds or changes a bank account or card, starts,
  stops or transfers service, or changes any setting. FORBIDDEN_CONTROL_RE is
  the guard; a control must ALSO look like a document action
  (SAFE_DOC_CONTROL_RE) before it may be clicked. There is no code here that
  submits a form or confirms a dialog.
"""
from __future__ import annotations

import base64
import html as _html
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import urlsplit

log = logging.getLogger("pge_docs.site")

BASE = "https://www.pge.com"
URLS = {
    "home": BASE,
    "login": f"{BASE}/en/site-signin.html",
    "documents": f"{BASE}/en/myaccount/billing-and-payments.html",
    "statements": f"{BASE}/en/myaccount/billing-and-payments.html",
    "documents_alt": f"{BASE}/en/myaccount.html",
}
DOCUMENT_URL_CANDIDATES = [URLS["documents"], URLS["statements"], URLS["documents_alt"]]

LOGIN_URL_MARKERS = [
    "/login", "/signin", "/sign-in", "/site-signin", "/auth", "/mfa",
    "/verification", "/challenge", "sso.pge.com",
]

ALLOWED_HOSTS = [
    "www.pge.com", "pge.com", "myaccount.pge.com", "m.pge.com",
]

# ---------------------------------------------------------------------------
# HARD SAFETY GUARD - never click anything matching this. Tuned for a utility
# billing portal: never pay a bill, change service, or modify the account.
# ---------------------------------------------------------------------------
FORBIDDEN_CONTROL_RE = re.compile(
    r"(pay\b|payment|pay\s+bill|autopay|auto\s*pay|schedule\s+payment|"
    r"one[-\s]?time\s+payment|payment\s+plan|budget\s+billing|paperless|"
    r"bank\b|routing|account\s+number|debit|credit\s+card|\bcard\b|wallet|"
    r"enroll|unenroll|sign\s+up|start\s+service|stop\s+service|"
    r"transfer\s+service|disconnect|reconnect|new\s+service|move\s+service|"
    r"donate|contribution|round\s*up|"
    r"enable|disable|activate|deactivate|change\b|edit\b|update\b|modify|"
    r"set\s+up|delete|remove|cancel|close\s+account|"
    r"password|profile\b|settings|preferences|"
    r"confirm|submit|agree|accept|authorize|enroll|"
    r"save\s+changes|save\s+settings|update\s+settings|change\s+address|"
    r"edit\s+preferences|document\s+removal|loss\s+mitigation|"
    r"manage\s+autopay|turn\s+off|opt\s+out|update\s+beneficiary|"
    r"place\s+order|rebalance|liquidate|buy|sell)", re.I)

SAFE_DOC_CONTROL_RE = re.compile(
    r"(download|view|open|print|pdf|statement|document|bill|invoice|"
    r"report|history)", re.I)


def is_safe_control(label: str) -> bool:
    """Returns True ONLY if label names a document action and no forbidden verb."""
    if not label or not isinstance(label, str):
        return False
    text = label.strip()
    if not text:
        return False
    if FORBIDDEN_CONTROL_RE.search(text):
        return False
    return bool(SAFE_DOC_CONTROL_RE.search(text))


def is_safe_url(url: str) -> bool:
    """Returns True ONLY if url is an HTTPS URL on an allowed PG&E domain."""
    from urllib.parse import urlparse
    try:
        got = urlparse(url or "")
    except ValueError:
        return False
    if got.scheme != "https" or not got.hostname:
        return False
    if got.username or got.password:
        return False
    host = got.hostname.lower().rstrip(".")
    return any(host == h or host.endswith("." + h) for h in ALLOWED_HOSTS)


SECURITY_CHALLENGE_MARKERS = [
    "enter the code", "verification code", "6-digit", "two-factor",
    "two-step", "authenticator", "confirm your identity", "verify your identity",
    "we sent a code", "device approval", "approve this login", "unusual",
    "are you a robot", "captcha", "let's verify", "check your email",
    "check your phone", "your session has expired", "log back in",
]

RATE_LIMIT_MARKERS = [
    "too many requests", "rate limit", "try again later",
    "temporarily unavailable", "http error 429", "unusual traffic",
]

FALLBACK = {
    "doc_row": ("table tbody tr, [role='row'], [class*='documentRow'], "
                "[class*='DocumentRow'], [class*='row'][class*='document'], "
                "[data-testid*='document'], li[class*='document']"),
    "doc_link": ("a[href*='.pdf'], a[href*='document'], a[href*='statement'], "
                 "a[download], button[class*='download']"),
    "download_control": "a[download], a[href$='.pdf'], button:has-text('Download')",
    "page_ready": ("table, [role='row'], [class*='document'], [class*='statement'], "
                   "main, [role='main']"),
    "next_page": ("a[aria-label*='Next' i], button[aria-label*='Next' i], "
                  "[class*='next']"),
}

DATE_PATTERNS = [
    (re.compile(r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
                r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|"
                r"Dec(?:ember)?)\.?\s+(\d{1,2}),?\s+(\d{4})", re.I), "mdY"),
    (re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b"), "mdy_slash"),
    (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"), "iso"),
]
_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
MONTH_YEAR_RE = re.compile(
    r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
    r"Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    r"\s+(\d{4})", re.I)
QUARTER_RE = re.compile(r"\bQ([1-4])\s*[' ]?\s*(\d{4})\b", re.I)
YEAR_RE = re.compile(r"\b(19|20)(\d{2})\b")


def parse_date(raw: str) -> str:
    """Parse date text into ISO YYYY-MM-DD or empty string if unparseable."""
    if not raw:
        return ""
    text = _html.unescape(raw).strip()
    for pat, fmt in DATE_PATTERNS:
        m = pat.search(text)
        if m:
            if fmt == "mdY":
                mon_str, day_str, yr_str = m.group(1).lower()[:3], m.group(2), m.group(3)
                mon = _MONTHS.get(mon_str, 0)
                if mon:
                    return f"{int(yr_str):04d}-{mon:02d}-{int(day_str):02d}"
            elif fmt == "mdy_slash":
                mon, day, yr = int(m.group(1)), int(m.group(2)), int(m.group(3))
                return f"{yr:04d}-{mon:02d}-{day:02d}"
            elif fmt == "iso":
                return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return ""


def parse_period_date(raw: str) -> Tuple[str, str]:
    """Parse period string returning (iso_date, confidence)."""
    exact = parse_date(raw)
    if exact:
        return exact, "HIGH"
    m_my = MONTH_YEAR_RE.search(raw)
    if m_my:
        mon_str, yr_str = m_my.group(1).lower()[:3], m_my.group(2)
        mon = _MONTHS.get(mon_str, 0)
        yr = int(yr_str)
        if mon:
            import calendar
            _, last_day = calendar.monthrange(yr, mon)
            return f"{yr:04d}-{mon:02d}-{last_day:02d}", "HIGH"
    m_yr = YEAR_RE.search(raw)
    if m_yr:
        yr = int(m_yr.group(0))
        return f"{yr:04d}-12-31", "MEDIUM"
    return "", "LOW"


def looks_signed_out(page) -> bool:
    """Return True if current page indicates session is logged out."""
    url = page.url.lower()
    return any(marker in url for marker in LOGIN_URL_MARKERS)


def detect_security_challenge(page) -> bool:
    """Return True if page presents a 2FA or CAPTCHA challenge."""
    try:
        content = page.content().lower()
        return any(m in content for m in SECURITY_CHALLENGE_MARKERS)
    except Exception:
        return False


def goto_documents(page) -> bool:
    """Navigate to PG&E billing/statements area."""
    for url in DOCUMENT_URL_CANDIDATES:
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=15000)
            if not looks_signed_out(page):
                return True
        except Exception:
            continue
    return False


def collect_download_docs(page) -> List[dict]:
    """Collect available billing statements from page DOM."""
    results = []
    try:
        rows = page.query_selector_all(FALLBACK["doc_row"])
        for idx, row in enumerate(rows):
            text = row.inner_text() or ""
            date_str = parse_date(text)
            if date_str:
                results.append({
                    "date_text": date_str,
                    "title": f"Energy Statement - {date_str}",
                    "row_index": idx,
                    "summary": "Energy Statement",
                })
    except Exception as e:
        log.debug(f"Error collecting docs: {e}")
    return results


def download_bill(page, doc: dict, out_path: Path, config: dict) -> bool:
    """Download a bill PDF for specified doc dictionary."""
    try:
        with page.expect_download(timeout=15000) as download_info:
            rows = page.query_selector_all(FALLBACK["doc_row"])
            idx = doc.get("row_index", 0)
            if 0 <= idx < len(rows):
                link = rows[idx].query_selector(FALLBACK["download_control"])
                if link:
                    link.click()
        download = download_info.value
        download.save_as(str(out_path))
        if out_path.exists() and (out_path.stat().st_size == 0 or out_path.read_bytes()[:5] != b"%PDF-"):
            out_path.unlink()
            return False
        return out_path.exists()
    except Exception as e:
        log.debug(f"Download failed: {e}")
        if out_path.exists() and out_path.stat().st_size == 0:
            out_path.unlink()
        return False
