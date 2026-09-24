"""Read the statements gateway for brokerage and charitable accounts. Gateway
headers distinguish charitable IDs. Documents use descriptor-plus-occurrence
identity because download identifiers are opaque; re-resolve before download.
The page can contain a trade ticket, so document retrieval uses API requests
and does not submit trade forms.

All requests and navigation must stay on explicitly allowed provider hosts.
"""

from __future__ import annotations

import base64
import logging
import re
import time as _time
from datetime import date as _date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from paperpull_core.controls import SETTINGS_CONTROL_RE, AUTH_CONTROL_RE
from paperpull_core.urls import is_safe_url as _host_allows
from paperpull_core.dates import checked as _checked_date

ALLOWED_HOSTS = {'client.schwab.com', 'ausgateway.schwab.com'}


def is_safe_url(url: str) -> bool:
    """True only for an https URL on exactly one of this provider's own
    hosts, never a subdomain of one.

    The check itself lives in the core, so all of them answer the same way.
    This app keeps the hosts and its refusal to follow subdomains, which is
    how it has always behaved."""
    return _host_allows(url, ALLOWED_HOSTS, subdomains=False)


log = logging.getLogger("schwab_docs.site")

BASE = "https://client.schwab.com"
GATEWAY = "https://ausgateway.schwab.com/api/is.StatementsWeb/StatementsInterface/Statements"
URLS = {
    "home": f"{BASE}/app/accounts/summary/",
    "login": f"{BASE}/Areas/Access/Login",
    "documents": f"{BASE}/app/accounts/statements/",
}
API = {
    "token": "/api/auth/authorize/scope/api",
    "accounts": f"{GATEWAY}/accounts",
    "documents": f"{GATEWAY}/brokerage/documents",
    "download": f"{GATEWAY}/download",
}
DOCUMENT_URL_CANDIDATES = [URLS["documents"]]


GATEWAY_HEADERS = {
    "accept": "application/json",
    "schwab-client-appid": "AD00008376",
    "schwab-resource-version": "1",
    "schwab-client-channel": "IO",
}


LOGIN_URL_MARKERS = ["/areas/access/login", "/areas/login/", "sessiontimeout=",
                     "/login", "/logon", "/signin", "/sign-in", "/mfa",
                     "www.schwab.com/"]


LOOKBACK_YEARS = 10


DOCUMENT_TYPE_PARAMS = ["STATEMENTS", "TAXFORMS", "LETTERS",
                        "REPORTS_AND_PLANNING", "CONFIRMS"]


FORBIDDEN_CONTROL_RE = re.compile(

    r"(\btrade\b(?!\s+confirm)|\btrading\b|place\s+order|preview\s+order|"
    r"\border\b(?!\s+(status|history))|\bbuy\b|\bsell\b|short\b|snapticket|"
    r"snap\s+ticket|all.?in.?one\s+trade|option\s+chain|\bexercise\b|"
    r"rebalance|reinvest|"

    r"transfer|wire\b|move\s+money|send\s+money|deposit|withdraw|journal|"
    r"\bpay\b|payment|bill\s*pay|zelle|"
    r"contribut(e|ion)\b(?!.{0,20}(statement|form|5498))|distribut(e|ion)\s+request|"

    r"\bgrant\b|recommend\s+a?\s*grant|donate|gift\b|"

    r"open\s+(a|an|another|new)\b[\w\s]{0,24}\baccount\b|apply|"
    r"get\s+(a\s+)?(quote|started|loan|card)|margin\b|borrow|lending|"
    r"redeem|sweep\s+(choice|election)|"
    r"check\s+order|order\s+checks?|stop\s+(a\s+)?(payment|check)|"
    r"add\s+(funds|card|authorized|payee)|authorized\s+user|payee|"
    r"link(ed)?\s+accounts?|external\s+accounts?|connected\s+accounts?|"
    r"close\s+account|dispute|"


    r"generate\b|request\b|"
    # Word boundaries on the verb stems. Without the leading \b, "edit"
    # matches inside "Credit", and a label like "Line of Credit Statement"
    # would be refused. Same fix as core 0.17.1 and the other providers.
    r"\bchang(e|es|ed|ing)\b|\bedit(s|ed|ing)?\b|\bupdat(e|es|ed|ing)\b|"
    r"set\s+up|enroll|enable|disable|delete|remove|"
    r"beneficiar|contact\s+info|\baddress\b|password|username|"
    r"paperless|delivery\s+(preference|option)|alerts?\b|nicknames?|"
    r"cost\s+basis\s+method|lot\s+selection|tax\s+lot\s+optimizer|"

    r"send\b|submit|\bconfirm\b|continue|next|agree|accept|\bsign\b|authorize|"
    r"i\s+agree|review\b|log\s*out|logout)", re.I)

SAFE_DOC_CONTROL_RE = re.compile(
    r"(download|\bview\b|\bopen\b|save|print|pdf|statement|document|"
    r"1099|1098|5498|tax\s+form|trade\s+confirms?|confirmation|letter|"
    r"report|search|date\s+range|still\s+here|continue\s+session)", re.I)


MONEY_CONTROL_RE = re.compile(
    r"(pay|payment|payee|transfer|from\s*account|to\s*account|amount|"
    r"\border\b|\btrade\b|\bbuy\b|\bsell\b|symbol|quantity|shares|"
    r"deposit|withdraw|wire|grant|donate)", re.I)

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


TYPE_STATEMENTS = "Statements"
TYPE_TAX = "Tax Forms"
TYPE_LETTERS = "Letters"
TYPE_CONFIRMS = "Trade Confirms"
TYPE_REPORTS = "Reports & Plans"

CATEGORY_STATEMENT = "Statement"
CATEGORY_TAX = "Tax Document"
CATEGORY_LETTER = "Letter"
CATEGORY_CONFIRM = "Trade Confirmation"
CATEGORY_REPORT = "Report"
CATEGORY_OTHER = "Other Document"

CATEGORY_FOR_TYPE = {
    TYPE_STATEMENTS: CATEGORY_STATEMENT,
    TYPE_TAX: CATEGORY_TAX,
    TYPE_LETTERS: CATEGORY_LETTER,
    TYPE_CONFIRMS: CATEGORY_CONFIRM,
    TYPE_REPORTS: CATEGORY_REPORT,
}

TAX_YEAR_RE = re.compile(r"\b((?:19|20)\d{2})\b")


MDY_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
ISO_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})(?!\d)")


def _parse_date_from_page(text: str) -> Optional[str]:
    if not text:
        return None
    m = MDY_RE.search(text)
    if m:
        return f"{int(m.group(3)):04d}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
    m = ISO_RE.search(text)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return None


def parse_date(text):
    """The date this provider's page is showing, as YYYY-MM-DD.

    The reading is below, unchanged. This only refuses to believe a result
    that names a day which does not exist, because a reference number is
    shaped like a date and used to be taken for one."""
    return _checked_date(_parse_date_from_page(text), None)


def mdy(iso: str) -> str:
    m = ISO_RE.fullmatch((iso or "").strip())
    if not m:
        return ""
    return f"{int(m.group(2)):02d}/{int(m.group(3)):02d}/{m.group(1)}"


def lookback_window(today: Optional[_date] = None) -> Tuple[str, str]:
    today = today or _date.today()
    try:
        start = today.replace(year=today.year - LOOKBACK_YEARS)
    except ValueError:
        start = today.replace(year=today.year - LOOKBACK_YEARS, day=28)
    return f"{start.month:02d}/{start.day:02d}/{start.year}", \
           f"{today.month:02d}/{today.day:02d}/{today.year}"


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
        if "/app/accounts/statements" not in url:
            return False
        if looks_signed_out(page):
            return False
        return "statements" in (page.title() or "").lower()
    except Exception:
        return False


def goto_documents(page) -> bool:
    dismiss_timeout(page)
    if on_documents_page(page):
        return True
    for url in DOCUMENT_URL_CANDIDATES:
        try:
            if not is_safe_url(url):
                continue
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            dismiss_timeout(page)
            if looks_signed_out(page):
                return False
            for _ in range(20):
                if on_documents_page(page):
                    log.info("documents area reached at %s", page.url)
                    return True
                page.wait_for_timeout(500)
        except Exception as e:
            log.info("documents URL %s failed: %s", url, e)
    return on_documents_page(page)


def ensure_statements(page) -> bool:
    dismiss_timeout(page)
    if on_documents_page(page):
        return True
    return goto_documents(page)


_TOKEN_TTL_SECONDS = 600
_token_cache: Dict[int, Tuple[str, float]] = {}


def _get_token(page, force: bool = False) -> str:
    key = id(page)
    if not force:
        tok, when = _token_cache.get(key, ("", 0.0))
        if tok and (_time.time() - when) < _TOKEN_TTL_SECONDS:
            return tok
    res = page.evaluate(
        """async (p) => {
             const ppTarget = new URL(p, location.href);
             if (ppTarget.protocol !== "https:" || !["client.schwab.com", "ausgateway.schwab.com"].includes(ppTarget.hostname) || ppTarget.username || ppTarget.password || (ppTarget.port && ppTarget.port !== "443")) throw new Error("Refusing an off-host document request");
             const r = await fetch(p, {redirect: 'error', credentials: 'include',
                                       headers: {'Accept': 'application/json'}});
             let j = null;
             try { j = await r.json(); } catch (e) {}
             return {status: r.status, token: (j && j.token) || ''};
           }""", API["token"])
    tok = (res or {}).get("token") or ""
    if not tok:
        log.info("token endpoint answered %s with no token", (res or {}).get("status"))
        return ""
    _token_cache[key] = (tok, _time.time())
    return tok


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


def _gateway_json(page, url: str, token: str, extra_headers: Dict[str, str],
                  post_body: Optional[dict] = None):
    return _evaluate_with_retry(page,
        """async ({url, headers, body}) => {
             const opts = {headers: headers};
             if (body !== null) {
               opts.method = 'POST';
               opts.headers = {...headers, 'content-type': 'application/json'};
               opts.body = JSON.stringify(body);
             }
             const ppTarget = new URL(url, location.href);
             if (ppTarget.protocol !== "https:" || !["client.schwab.com", "ausgateway.schwab.com"].includes(ppTarget.hostname) || ppTarget.username || ppTarget.password || (ppTarget.port && ppTarget.port !== "443")) throw new Error("Refusing an off-host document request");
             const r = await fetch(url, opts);
             const text = await r.text();
             let j = null;
             try { j = JSON.parse(text); } catch (e) {}
             return {status: r.status, body: j, text: j ? '' : text.slice(0, 300)};
           }""",
        {"url": url,
         "headers": {**GATEWAY_HEADERS, **extra_headers,
                     "authorization": f"Bearer {token}"},
         "body": post_body})


def _gateway_call(page, url: str, extra_headers: Dict[str, str],
                  post_body: Optional[dict] = None):
    token = _get_token(page)
    if not token:
        return {"status": 0, "body": None, "text": "no bearer token"}
    res = _gateway_json(page, url, token, extra_headers, post_body)
    if res.get("status") in (401, 403):
        token = _get_token(page, force=True)
        if token:
            res = _gateway_json(page, url, token, extra_headers, post_body)
    return res


def account_label(nickname: str, last4: str) -> str:
    nickname = re.sub(r"\s+", " ", nickname or "").strip() or "Account"
    last4 = (last4 or "").strip()
    return f"{nickname} (...{last4})" if last4 else nickname


def account_id_from_display(display: str) -> str:
    return re.sub(r"\D", "", display or "")


def list_accounts(page) -> List[dict]:
    res = _gateway_call(page, API["accounts"], {})
    body = res.get("body")
    if res.get("status") != 200 or not isinstance(body, dict):
        log.info("accounts API answered %s %r", res.get("status"),
                 (res.get("text") or "")[:120])
        return []
    rows = (((body.get("accountSelectorData") or {})
             .get("brokerageAccountList") or {})
            .get("brokerageAccounts")) or []
    out = []
    for a in rows:
        if not isinstance(a, dict):
            continue
        acct_id = str(a.get("id") or "")
        nick = a.get("nickName") or a.get("accountType") or "Account"
        out.append({
            "account_id": acct_id,
            "label": account_label(nick, acct_id[-4:]),
            "nickname": nick,
            "last4": acct_id[-4:],
            "account_type": a.get("accountType") or "",
            "charitable": bool(a.get("isCharitable")),
            "closed": bool(a.get("isClosed")),
        })
    return [a for a in out if a["account_id"]]


def _id_headers(accounts: List[dict]) -> Dict[str, str]:
    regular = ",".join(a["account_id"] for a in accounts if not a["charitable"])
    charitable = ",".join(a["account_id"] for a in accounts if a["charitable"])
    headers = {}
    if regular:
        headers["schwab-client-ids"] = regular
    if charitable:
        headers["schwab-client-charitable-ids"] = charitable
    return headers


def _documents_url(from_mdy: str, to_mdy: str) -> str:
    params = "&".join(f"documentTypes={t}" for t in DOCUMENT_TYPE_PARAMS)
    return (f"{API['documents']}?{params}&timeFrame=Last10Years"
            f"&fromDate={from_mdy}&toDate={to_mdy}"
            f"&isNonAllianceAccountAvailable=true")


def list_documents(page, accounts: List[dict],
                   from_mdy: str = "", to_mdy: str = "") -> List[dict]:
    if not accounts:
        return []
    if not from_mdy or not to_mdy:
        from_mdy, to_mdy = lookback_window()
    res = _gateway_call(page, _documents_url(from_mdy, to_mdy),
                        _id_headers(accounts))
    body = res.get("body")
    if res.get("status") != 200 or not isinstance(body, dict):
        log.info("documents API answered %s %r", res.get("status"),
                 (res.get("text") or "")[:120])
        return []
    if body.get("nonCharitableSuccess") is False:
        log.warning("documents API: nonCharitableSuccess=false (brokerage list may be partial)")
    if body.get("charitableSuccess") is False:
        log.warning("documents API: charitableSuccess=false (DAF list may be partial)")
    return [d for d in (body.get("documents") or []) if isinstance(d, dict)]


def classify_document(doc: dict) -> Tuple[str, str, str, str]:
    dtype = (doc.get("type") or "").strip()
    title = re.sub(r"\s+", " ", doc.get("documentName") or "").strip()
    date = parse_date(doc.get("date") or "") or ""
    category = CATEGORY_FOR_TYPE.get(dtype, CATEGORY_OTHER)
    period = ""
    if category == CATEGORY_TAX:
        period = (doc.get("taxYear") or "").strip()
        if not period:
            m = TAX_YEAR_RE.search(title)
            if m:
                period = m.group(1)
    if not title:
        title = category if category != CATEGORY_OTHER else (dtype or "Document")
    return category, date, period, title


def document_descriptor(doc: dict) -> Tuple[str, str, str, str]:
    return ((doc.get("type") or "").strip(),
            re.sub(r"\s+", " ", doc.get("documentName") or "").strip(),
            parse_date(doc.get("date") or "") or "",
            (doc.get("accountDisplayName") or "").strip())


def collect_documents(page) -> List[dict]:
    accounts = list_accounts(page)
    if not accounts:
        return []
    label_for_id = {a["account_id"]: a["label"] for a in accounts}
    docs = list_documents(page, accounts)
    log.info("Schwab: %d document(s) across %d account(s)", len(docs), len(accounts))
    out = []
    seen: Dict[Tuple[str, str, str, str], int] = {}
    for doc in docs:
        category, date, period, title = classify_document(doc)
        desc = document_descriptor(doc)
        occ = seen.get(desc, 0)
        seen[desc] = occ + 1
        acct_id = account_id_from_display(desc[3])
        out.append({
            "account": label_for_id.get(acct_id) or account_label("Account", acct_id[-4:]),
            "account_id": acct_id,
            "doc_type": desc[0],
            "on_demand_type": doc.get("onDemandDocumentType") or "",
            "document_id": doc.get("documentId") or "",
            "title": title, "category": category, "date": date,
            "period": period, "occurrence": occ,
        })
    return out


def _write_if_pdf(data: bytes, out_path: Path) -> bool:
    if not data or not data[:5].startswith(b"%PDF-"):
        return False
    Path(out_path).write_bytes(data)
    return True


def resolve_document(page, account_id: str, charitable: bool, doc_type: str,
                     title: str, date: str, occurrence: int = 0) -> Optional[dict]:
    account = {"account_id": account_id, "charitable": charitable}
    day = mdy(date)
    docs = list_documents(page, [account], from_mdy=day, to_mdy=day)
    want_title = re.sub(r"\s+", " ", title or "").strip()
    n = 0
    for doc in docs:
        d_type, d_title, d_date, d_display = document_descriptor(doc)
        if (d_type == doc_type and d_title == want_title and d_date == date
                and account_id_from_display(d_display) == account_id):
            if n == occurrence:
                return doc
            n += 1
    return None


_DOWNLOAD_JS = """async ({url, headers, body}) => {
  const ppTarget = new URL(url, location.href);
  if (ppTarget.protocol !== "https:" || !["client.schwab.com", "ausgateway.schwab.com"].includes(ppTarget.hostname) || ppTarget.username || ppTarget.password || (ppTarget.port && ppTarget.port !== "443")) throw new Error("Refusing an off-host document request");
  const r = await fetch(url, {redirect: 'error', method: 'POST',
      headers: {...headers, 'content-type': 'application/json'},
      body: JSON.stringify(body)});
  if (r.status !== 200) return {status: r.status, b64: ''};
  const buf = await r.arrayBuffer();
  let s = '';
  const bytes = new Uint8Array(buf);
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk)
    s += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
  return {status: r.status, b64: btoa(s)};
}"""


def fetch_pdf(page, doc: dict) -> Tuple[int, bytes]:
    body = {
        "documentId": doc.get("documentId") or "",
        "documentName": doc.get("documentName") or "",
        "documentType": doc.get("onDemandDocumentType") or doc.get("type") or "",
        "downloadFileType": "PDF",
    }

    def attempt(token: str):
        return _evaluate_with_retry(page, _DOWNLOAD_JS, {
            "url": API["download"],
            "headers": {**GATEWAY_HEADERS, "authorization": f"Bearer {token}"},
            "body": body})

    token = _get_token(page)
    if not token:
        return 0, b""
    res = attempt(token)
    if (res or {}).get("status") in (401, 403):
        token = _get_token(page, force=True)
        if token:
            res = attempt(token)
    data = base64.b64decode(res.get("b64") or "") if res else b""
    return int((res or {}).get("status") or 0), data


def download_document(page, account_id: str, charitable: bool, doc_type: str,
                      title: str, date: str, out_path: Path,
                      occurrence: int = 0, document_id_hint: str = "",
                      on_demand_type_hint: str = "") -> bool:
    doc = resolve_document(page, account_id, charitable, doc_type, title,
                           date, occurrence)
    if doc is None and document_id_hint:
        log.info("document %r (%s %s) not in the fresh list - trying the stored id",
                 title, doc_type, date)
        doc = {"documentId": document_id_hint, "documentName": title,
               "onDemandDocumentType": on_demand_type_hint, "type": doc_type}
    if doc is None:
        log.info("document %r (%s %s) could not be resolved", title, doc_type, date)
        return False
    status, data = fetch_pdf(page, doc)
    if status == 200 and _write_if_pdf(data, out_path):
        return True
    log.info("download answered %s (%d bytes) for %r", status, len(data or b""), title)
    return False


_READ_UI_JS = """() => {
  const out = {selectedAccount: '', chips: [], dateRange: '', rows: [], buttons: []};
  const visit = (root) => {
    for (const el of root.querySelectorAll('*')) {
      if (el.shadowRoot) visit(el.shadowRoot);
      const t = (el.textContent || '').trim().replace(/\\s+/g, ' ');
      if (el.tagName === 'BUTTON') {
        const id = el.id || '';
        if (id.startsWith('chips-wrapper-chip'))
          out.chips.push({text: t.slice(0, 40),
                          pressed: el.getAttribute('aria-pressed') === 'true'});
        const aria = el.getAttribute('aria-label') || '';
        // the account selector's own button says "Account ending in ..." (or
        // "All Brokerage Accounts"); row buttons say "Click to view document
        // ... account ending in ..."
        if (/account ending in|all brokerage accounts/i.test(aria + t)
            && !/click to/i.test(aria) && !out.selectedAccount)
          out.selectedAccount = (aria || t).slice(0, 80);
        if (aria && /click to (view|download)/i.test(aria) && out.rows.length < 30)
          out.rows.push(aria.slice(0, 120));
        else if (t && t.length < 50) out.buttons.push(t);
      }
      if (el.tagName === 'SELECT' && el.id === 'date-range-select-id')
        out.dateRange = el.value || '';
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
