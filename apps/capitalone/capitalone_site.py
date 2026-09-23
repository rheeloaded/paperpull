"""The unified document search lists bank and monthly card documents. Bank PDFs
use the deposits endpoint; monthly card PDFs use rawURL. Quarterly and yearly
card documents use the enterprise dataset API and a multipart PDF response.
Search uses the portal-compatible rolling window. Re-resolve opaque IDs from
fresh metadata, preserving document identity as kind/name/date/account.

All requests and navigation must stay on explicitly allowed provider hosts.
"""

from __future__ import annotations

import base64
import logging
import re
from datetime import date as _date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from paperpull_core.controls import SETTINGS_CONTROL_RE, AUTH_CONTROL_RE
from paperpull_core.urls import is_safe_url as _host_allows
from paperpull_core.dates import checked as _checked_date

ALLOWED_HOSTS = {'verified.capitalone.com', 'myaccounts.capitalone.com'}


def is_safe_url(url: str) -> bool:
    """True only for an https URL on exactly one of this provider's own
    hosts, never a subdomain of one.

    The check itself lives in the core, so all of them answer the same way.
    This app keeps the hosts and its refusal to follow subdomains, which is
    how it has always behaved."""
    return _host_allows(url, ALLOWED_HOSTS, subdomains=False)


log = logging.getLogger("capitalone_docs.site")

BASE = "https://myaccounts.capitalone.com"
URLS = {
    "home": f"{BASE}/accountSummary",
    "login": "https://verified.capitalone.com/auth/signin",
    "documents": f"{BASE}/documentCenter",
}
API = {
    "search": f"{BASE}/web-api/tiger/protected/596222/document-center"
              "/documents/search-documents",
    "doc_center": f"{BASE}/web-api/tiger/protected/596222/document-center",
    "deposits": f"{BASE}/web-api/protected/17818/deposits/accounts",
    "ease_search": f"{BASE}/web-api/enterprise/customer-document-management"
                   "/documents/document-search",
    "ease_datasets": f"{BASE}/web-api/enterprise/customer-document-management"
                     "/datasets",
}
DOCUMENT_URL_CANDIDATES = [URLS["documents"]]


EASE_HEADERS = {
    "accept": "application/json;v=2",
    "content-type": "application/json",
    "api-key": "EASE",
    "external-system-code": "EASE",
}


EASE_DATASETS = {
    "CARD_YEARLY_STATEMENT": (["bd8e025e-affc-42b3-8d62-75ab194fb54b"],
                              ["YEAR_ENDING_STATEMENT_v1"]),
    "CARD_QUARTERLY_STATEMENT": (["ddc90929-61fc-4b02-8f39-279f2f1ff94c"],
                                 ["QUARTER_ENDING_STATEMENT_v1"]),
}


LOGIN_URL_MARKERS = ["verified.capitalone.com", "/auth/signin", "/signin",
                     "/login", "/logon", "/sign-in", "/mfa"]


LOOKBACK_YEARS = 7


FORBIDDEN_CONTROL_RE = re.compile(

    r"(\bpay\b|payment|bill\s*pay|autopay|auto\s*pay|transfer|zelle|"
    r"send\s+money|move\s+money|wire\b|deposit|withdraw|"
    r"automatic\s+savings|direct\s+deposit|"

    r"cash\s+advance|balance\s+transfer|redeem|"
    r"virtual\s+card|lock\s+card|replace\s+card|report\s+(lost|stolen)|"
    r"activate\b|\boffer\b|offers\b|earn\s+now|refer\b|rewards?\s+cash|"

    r"open\s+(a|an|another|new)\b[\w\s]{0,24}\baccount\b|apply|"
    r"close\s+(this\s+)?account|dispute|"
    r"beneficiar|external\s+accounts?|linked\s+accounts?|connected\s+accounts?|"
    r"add\s+(funds|card|authorized|payee)|authorized\s+user|payee|"
    r"get\s+(a\s+)?(quote|started|loan|card)|credit\s*wise|creditwise|"
    r"check\s+order|order\s+checks?|stop\s+(a\s+)?(payment|check)|"

    r"generate\b|request\b|manage\b|"
    # Word boundaries on the verb stems. Without the leading \b, "edit"
    # matches inside "Credit", and "Credit Card Statement" is the one label
    # a credit-card provider must never refuse. Same shape as the core bug
    # fixed in 0.17.1 and the "elect" inside "Select" one in anthem.
    r"\bchang(e|es|ed|ing)\b|\bedit(s|ed|ing)?\b|\bupdat(e|es|ed|ing)\b|"
    r"set\s+up|enroll|enable|disable|delete|remove|"
    r"contact\s+info|\baddress\b|password|username|"
    r"paperless|delivery\s+(preference|option)|alerts?\b|nicknames?|"

    r"send\b|submit|\bconfirm\b|continue(?!\s+session)|next|agree|accept|"
    r"\bsign\b(?!\s*ed)|authorize|i\s+agree|\bdecline\b|log\s*out|logout)", re.I)

SAFE_DOC_CONTROL_RE = re.compile(
    r"(download|\bview\b|\bopen\b|save|print|pdf|statement|document|"
    r"1099|1098|tax\s+form|letter|notice|search|filter|date\s+range|year\b|"
    r"still\s+here|continue\s+session)", re.I)


MONEY_CONTROL_RE = re.compile(
    r"(pay|payment|payee|autopay|transfer|from\s*account|to\s*account|"
    r"amount|deposit|withdraw|wire|zelle|offer|reward|virtual\s+card)", re.I)

SECURITY_CHALLENGE_MARKERS = [
    "enter the code we sent", "enter your verification code", "verification code",
    "one-time", "one time passcode", "security code", "we sent a code",
    "two-factor", "two-step", "authenticator", "confirm your identity",
    "verify your identity", "we need to verify", "unusual activity",
    "are you a robot", "captcha", "unable to verify", "trouble verifying",
    "your session has expired", "please log in again", "you've been logged out",
    "for your security, we signed you out", "for your security we've signed",
]

RATE_LIMIT_MARKERS = [
    re.compile(r"too many requests", re.I),
    re.compile(r"rate limit(ed|ing)?\b", re.I),
    re.compile(r"unusual traffic", re.I),
    re.compile(r"\b(http\s*)?(error\s*)?429\b", re.I),
    re.compile(r"(site|service|page|system|application)\s+(is\s+)?"
               r"(currently\s+|temporarily\s+)*unavailable", re.I),
    re.compile(r"we'?re\s+(currently\s+)?(experiencing|having)\s+"
               r"(technical\s+)?(difficulties|issues)", re.I),
]


TYPE_BANK_STATEMENT = "BANK_STATEMENT"
TYPE_CARD_STATEMENT = "CARD_STATEMENT"
TYPE_CARD_YEARLY = "CARD_YEARLY_STATEMENT"
TYPE_CARD_QUARTERLY = "CARD_QUARTERLY_STATEMENT"

CATEGORY_STATEMENT = "Statement"
CATEGORY_TAX = "Tax Document"
CATEGORY_LETTER = "Letter"
CATEGORY_OTHER = "Other Document"

CATEGORY_FOR_SEARCH = {"STATEMENT": CATEGORY_STATEMENT,
                       "TAX": CATEGORY_TAX,
                       "LETTER": CATEGORY_LETTER}
SEARCH_CATEGORIES = ["STATEMENT", "TAX", "LETTER"]

TAX_YEAR_RE = re.compile(r"\b((?:19|20)\d{2})\b")
ISO_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")


def _parse_date_from_page(text: str) -> Optional[str]:
    m = ISO_RE.search(text or "")
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None


def parse_date(text):
    """The date this provider's page is showing, as YYYY-MM-DD.

    The reading is below, unchanged. This only refuses to believe a result
    that names a day which does not exist, because a reference number is
    shaped like a date and used to be taken for one."""
    return _checked_date(_parse_date_from_page(text), None)


def lookback_window(today: Optional[_date] = None) -> Tuple[str, str]:
    today = today or _date.today()
    try:
        start = today.replace(year=today.year - LOOKBACK_YEARS)
    except ValueError:
        start = today.replace(year=today.year - LOOKBACK_YEARS, day=28)
    return start.isoformat(), today.isoformat()


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
        if on_documents_page(page):
            return None
    except Exception:
        pass
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
    for rx in RATE_LIMIT_MARKERS:
        m = rx.search(hay)
        if m:
            return f"Possible rate limiting detected: '{m.group(0)}'"
    return None


def is_safe_control(name: str) -> bool:
    name = (name or "").strip()
    if not name:
        return False
    if (FORBIDDEN_CONTROL_RE.search(name) or SETTINGS_CONTROL_RE.search(name)
            or AUTH_CONTROL_RE.search(name)):
        return False
    return bool(SAFE_DOC_CONTROL_RE.search(name))


def is_money_control(identity: str) -> bool:
    identity = (identity or "").strip()
    if not identity:
        return True
    return bool(MONEY_CONTROL_RE.search(identity))


def dismiss_timeout(page) -> None:
    for pattern in (r"continue session", r"i'?m still here",
                    r"stay (signed|logged) in", r"keep me (signed|logged) in",
                    r"extend (my )?session", r"still (there|here)\?"):
        try:
            c = page.get_by_role("button", name=re.compile(pattern, re.I))
            if c.count() and c.first.is_visible():
                c.first.click()
                page.wait_for_timeout(1000)
                return
        except Exception:
            pass


def on_documents_page(page) -> bool:
    try:
        url = (page.url or "").lower()
        if "myaccounts.capitalone.com" not in url:
            return False
        return not looks_signed_out(page)
    except Exception:
        return False


def goto_documents(page) -> bool:
    dismiss_timeout(page)
    for url in DOCUMENT_URL_CANDIDATES:
        try:
            if not is_safe_url(url):
                continue
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(2500)
            dismiss_timeout(page)
            if looks_signed_out(page):
                return False
            if on_documents_page(page):
                log.info("documents area reached at %s", page.url)
                return True
        except Exception as e:
            log.info("documents URL %s failed: %s", url, e)
    return on_documents_page(page)


def ensure_documents(page) -> bool:
    dismiss_timeout(page)
    if on_documents_page(page):
        return True
    return goto_documents(page)


def _evaluate_with_retry(page, js: str, arg, attempts: int = 2):
    last = None
    for i in range(attempts):
        try:
            return page.evaluate(js, arg)
        except Exception as e:
            last = e
            log.info("page fetch attempt %d failed: %s", i + 1, e)
            try:
                page.wait_for_timeout(2000)
            except Exception:
                pass
    raise last


_JSON_FETCH_JS = """async ({url, headers, body}) => {
  const opts = {redirect: 'error', credentials: 'include', headers};
  if (body !== null) { opts.method = 'POST'; opts.body = JSON.stringify(body); }
  const ppTarget = new URL(url, location.href);
  if (ppTarget.protocol !== "https:" || !["myaccounts.capitalone.com", "verified.capitalone.com"].includes(ppTarget.hostname) || ppTarget.username || ppTarget.password || (ppTarget.port && ppTarget.port !== "443")) throw new Error("Refusing an off-host document request");
  const r = await fetch(url, opts);
  const text = await r.text();
  let j = null;
  try { j = JSON.parse(text); } catch (e) {}
  return {status: r.status, body: j, text: j ? '' : text.slice(0, 300)};
}"""

_BYTES_FETCH_JS = """async ({url, headers}) => {
  const ppTarget = new URL(url, location.href);
  if (ppTarget.protocol !== "https:" || !["myaccounts.capitalone.com", "verified.capitalone.com"].includes(ppTarget.hostname) || ppTarget.username || ppTarget.password || (ppTarget.port && ppTarget.port !== "443")) throw new Error("Refusing an off-host document request");
  const r = await fetch(url, {redirect: 'error', credentials: 'include', headers});
  if (r.status !== 200) {
    const text = await r.text();
    return {status: r.status, ct: r.headers.get('content-type') || '',
            b64: '', text: text.slice(0, 300)};
  }
  const buf = await r.arrayBuffer();
  let s = '';
  const bytes = new Uint8Array(buf);
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk)
    s += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
  return {status: r.status, ct: r.headers.get('content-type') || '',
          b64: btoa(s), text: ''};
}"""


def _fetch_json(page, url: str, headers: Dict[str, str],
                body: Optional[dict] = None):
    return _evaluate_with_retry(page, _JSON_FETCH_JS,
                                {"url": url, "headers": headers, "body": body})


def _fetch_bytes(page, url: str, headers: Dict[str, str]) -> Tuple[int, str, bytes]:
    res = _evaluate_with_retry(page, _BYTES_FETCH_JS,
                               {"url": url, "headers": headers}) or {}
    data = base64.b64decode(res.get("b64") or "")
    if res.get("text"):
        log.info("byte fetch answered %s: %r", res.get("status"), res["text"][:200])
    return int(res.get("status") or 0), res.get("ct") or "", data


def search_documents(page, categories: List[str],
                     from_iso: str = "", to_iso: str = "") -> List[dict]:
    if not from_iso or not to_iso:
        from_iso, to_iso = lookback_window()
    res = _fetch_json(page, API["search"],
                      {"accept": "application/json;v=1",
                       "content-type": "application/json;v=1"},
                      {"documentCategories": categories,
                       "fromDate": from_iso, "toDate": to_iso})
    body = res.get("body")
    if res.get("status") != 200 or not isinstance(body, dict):
        log.info("document search answered %s %r", res.get("status"),
                 (res.get("text") or "")[:120])
        return []
    return [d for d in (body.get("documents") or []) if isinstance(d, dict)]


def ease_search(page, account_ref: str, kind: str,
                from_iso: str = "", to_iso: str = "") -> List[dict]:
    if not from_iso or not to_iso:
        from_iso, to_iso = lookback_window()
    dataset_ids, dataset_aliases = EASE_DATASETS[kind]
    res = _fetch_json(page, API["ease_search"],
                      {**EASE_HEADERS, "accountreferenceid": account_ref},
                      {"searchParameters": [
                          {"fieldName": "documentDate", "fieldType": "dateRange",
                           "fieldValue": {"fromDate": from_iso, "toDate": to_iso}},
                          {"fieldName": "accountReferenceId", "fieldType": "string",
                           "fieldValue": {"searchValue": account_ref},
                           "isPrimaryIdentifierField": True}],
                       "datasetId": dataset_ids,
                       "datasetAlias": dataset_aliases})
    body = res.get("body")
    if res.get("status") != 200 or not isinstance(body, dict):
        log.info("enterprise search (%s) answered %s %r", kind,
                 res.get("status"), (res.get("text") or "")[:120])
        return []
    return [d for d in (body.get("documents") or []) if isinstance(d, dict)]


def ease_metadata(doc: dict) -> Dict[str, str]:
    return {m.get("itemName"): m.get("itemValue")
            for m in (doc.get("documentMetadata") or []) if isinstance(m, dict)}


def account_label(description: str) -> str:
    description = re.sub(r"\s+", " ", description or "").strip()
    m = re.match(r"^(.*?)\s*\.{2,}\s*(\d{2,4})$", description)
    if not m:
        return description or "Account"
    name = m.group(1).strip() or "Account"
    return f"{name} (...{m.group(2)})"


def account_last4(description: str) -> str:
    m = re.search(r"(\d{2,4})\s*$", description or "")
    return m.group(1) if m else ""


def card_accounts_from_docs(docs: List[dict]) -> List[dict]:
    seen: Dict[str, dict] = {}
    for d in docs:
        if (d.get("documentType") or "") != TYPE_CARD_STATEMENT:
            continue
        ref = ((d.get("account") or {}).get("accountReferenceId") or "").strip()
        if not ref or ref in seen:
            continue
        desc = (d.get("description") or "").strip()
        seen[ref] = {"account_ref": ref, "description": desc,
                     "label": account_label(desc), "last4": account_last4(desc)}
    return list(seen.values())


def classify_document(doc: dict) -> Tuple[str, str, str, str]:
    category = CATEGORY_FOR_SEARCH.get((doc.get("documentCategory") or "").strip(),
                                       CATEGORY_OTHER)
    title = re.sub(r"\s+", " ", doc.get("documentName") or "").strip()
    date = parse_date(doc.get("documentDisplayDate") or "") \
        or parse_date(doc.get("documentDate") or "") or ""
    period = ""
    if category == CATEGORY_TAX:
        m = TAX_YEAR_RE.search(title)
        if m:
            period = m.group(1)
    if not title:
        title = category if category != CATEGORY_OTHER else "Document"
    return category, date, period, title


def classify_ease_document(doc: dict, kind: str) -> Tuple[str, str, str, str]:
    md = ease_metadata(doc)
    title = re.sub(r"\s+", " ", md.get("documentType") or "").strip() \
        or ("Card Yearly Statement" if kind == TYPE_CARD_YEARLY
            else "Card Quarterly Statement")
    date = parse_date(md.get("documentDate") or "") or ""
    period = (md.get("year") or "").strip() if kind == TYPE_CARD_YEARLY else ""
    return CATEGORY_STATEMENT, date, period, title


def document_descriptor(doc_type: str, title: str, date: str,
                        account_desc: str) -> Tuple[str, str, str, str]:
    return (doc_type,
            re.sub(r"\s+", " ", title or "").strip(),
            date or "",
            re.sub(r"\s+", " ", account_desc or "").strip())


def collect_documents(page) -> List[dict]:
    out = []
    seen: Dict[Tuple[str, str, str, str], int] = {}

    def add(doc_type, category, date, period, title, account_desc,
            account_ref, document_id, dataset_id):
        desc = document_descriptor(doc_type, title, date, account_desc)
        occ = seen.get(desc, 0)
        seen[desc] = occ + 1
        out.append({
            "account": account_label(account_desc),
            "account_ref": account_ref, "account_desc": desc[3],
            "doc_type": doc_type, "document_id": document_id,
            "dataset_id": dataset_id, "title": desc[1], "category": category,
            "date": date, "period": period, "occurrence": occ,
        })

    unified = search_documents(page, SEARCH_CATEGORIES)
    log.info("Capital One: unified search returned %d document(s)", len(unified))
    for d in unified:
        category, date, period, title = classify_document(d)
        add((d.get("documentType") or "").strip() or "DOCUMENT",
            category, date, period, title,
            d.get("description") or "",
            ((d.get("account") or {}).get("accountReferenceId") or "").strip(),
            d.get("documentId") or "", d.get("datasetId") or "")

    for acct in card_accounts_from_docs(unified):
        for kind in (TYPE_CARD_YEARLY, TYPE_CARD_QUARTERLY):
            for d in ease_search(page, acct["account_ref"], kind):
                category, date, period, title = classify_ease_document(d, kind)
                add(kind, category, date, period, title, acct["description"],
                    acct["account_ref"], d.get("documentId") or "",
                    d.get("datasetId") or "")
    return out


def _write_if_pdf(data: bytes, out_path: Path) -> bool:
    if not data or not data[:5].startswith(b"%PDF-"):
        return False
    Path(out_path).write_bytes(data)
    return True


def _double_encode(ref: str) -> str:
    from urllib.parse import quote
    return quote(quote(ref, safe=""), safe="")


def _extract_multipart_pdf(data: bytes) -> bytes:
    marker = b"Content-Type: application/pdf"
    i = data.find(marker)
    if i < 0:
        return b""
    head, sep, rest = data[i:].partition(b"\r\n\r\n")
    if not sep:
        return b""
    boundary = data.split(b"\r\n", 1)[0].strip()
    end = rest.find(b"\r\n" + boundary)
    return rest[:end] if end >= 0 else rest


def resolve_document(page, doc_type: str, title: str, date: str,
                     account_desc: str, account_ref: str,
                     occurrence: int = 0) -> Optional[dict]:
    want = document_descriptor(doc_type, title, date, account_desc)
    n = 0
    if doc_type in EASE_DATASETS:
        for d in ease_search(page, account_ref, doc_type):
            _c, d_date, _p, d_title = classify_ease_document(d, doc_type)
            if document_descriptor(doc_type, d_title, d_date, account_desc) == want:
                if n == occurrence:
                    return {"document_id": d.get("documentId") or "",
                            "dataset_id": d.get("datasetId") or ""}
                n += 1
        return None
    categories = ["STATEMENT"] if doc_type in (TYPE_BANK_STATEMENT,
                                               TYPE_CARD_STATEMENT) \
        else ["TAX", "LETTER"]
    for d in search_documents(page, categories):
        if (d.get("documentType") or "").strip() != doc_type:
            continue
        _c, d_date, _p, d_title = classify_document(d)
        if document_descriptor(doc_type, d_title, d_date,
                               d.get("description") or "") == want:
            if n == occurrence:
                return {"document_id": d.get("documentId") or "",
                        "dataset_id": d.get("datasetId") or "",
                        "raw_url": ((d.get("_links") or {}).get("rawURL") or "")}
            n += 1
    return None


def fetch_pdf(page, doc_type: str, account_ref: str, rec: dict) -> Tuple[int, bytes]:
    document_id = rec.get("document_id") or ""
    if doc_type in EASE_DATASETS:
        url = (f"{API['ease_datasets']}/{rec.get('dataset_id')}"
               f"/documents/{document_id}?fileFormat=pdf")
        status, ct, data = _fetch_bytes(page, url, {
            **EASE_HEADERS, "accountreferenceid": account_ref,
            "accept": "application/json;v=2, multipart/form-data;v=2"})
        if status == 200 and "multipart" in ct:
            data = _extract_multipart_pdf(data)
        return status, data
    if doc_type == TYPE_BANK_STATEMENT:
        url = (f"{API['deposits']}/{_double_encode(account_ref)}"
               f"/statement/{document_id}")
        status, _ct, data = _fetch_bytes(page, url,
                                         {"accept": "application/pdf;v=1"})
        return status, data

    raw_url = rec.get("raw_url") or ""
    if not raw_url:
        raw_url = f"/documents/{document_id}/raw?documentType={doc_type}"
        if rec.get("dataset_id"):
            raw_url += f"&datasetId={rec['dataset_id']}"
    status, _ct, data = _fetch_bytes(page, API["doc_center"] + raw_url,
                                     {"accept": "application/pdf;v=1"})
    return status, data


def download_document(page, doc_type: str, title: str, date: str,
                      account_desc: str, account_ref: str, out_path: Path,
                      occurrence: int = 0, document_id_hint: str = "",
                      dataset_id_hint: str = "") -> bool:
    rec = resolve_document(page, doc_type, title, date, account_desc,
                           account_ref, occurrence)
    if rec is None and document_id_hint:
        log.info("document %r (%s %s) not in the fresh list - trying the stored id",
                 title, doc_type, date)
        rec = {"document_id": document_id_hint, "dataset_id": dataset_id_hint}
    if rec is None:
        log.info("document %r (%s %s) could not be resolved", title, doc_type, date)
        return False
    status, data = fetch_pdf(page, doc_type, account_ref, rec)
    if status == 200 and _write_if_pdf(data, out_path):
        return True
    log.info("download answered %s (%d bytes) for %r", status,
             len(data or b""), title)
    return False


_READ_UI_JS = """() => {
  const out = {headings: [], rows: [], buttons: []};
  const visit = (root) => {
    for (const el of root.querySelectorAll('*')) {
      if (el.shadowRoot) visit(el.shadowRoot);
      const t = (el.textContent || '').trim().replace(/\\s+/g, ' ');
      if (/^H[1-3]$/.test(el.tagName) && t && out.headings.length < 10)
        out.headings.push(t.slice(0, 80));
      if (el.tagName === 'BUTTON' && t && t.length < 50)
        out.buttons.push(t);
      if (el.tagName === 'TR' && t && out.rows.length < 30)
        out.rows.push(t.slice(0, 120));
    }
  };
  visit(document);
  return out;
}"""


def read_page_ui(page) -> Optional[dict]:
    try:
        return page.evaluate(_READ_UI_JS)
    except Exception as e:
        log.info("page UI read failed: %s", e)
        return None


def redact_label(text: str) -> str:
    return re.sub(r"\d", "#", text or "")
