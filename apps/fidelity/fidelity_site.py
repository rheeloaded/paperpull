"""ALL Fidelity Investments selectors, URLs, and page behavior live here.

When fidelity.com changes, repair this file only.

STATUS, mapped 2026-09-18 against a signed-in session.

  Sign-in is on digital.fidelity.com. Documents live in the Document Access
  Hub, an Angular app at digitalservices.fidelity.com/navigate/
  ent-documentcenter/ with three tabs, statements, tax-forms and
  trade-confirmations, a year picker on each, and a Download Document link
  per row that the page turns into a blob. This app never clicks those. It
  makes the same API calls the page makes, from inside the signed-in page,
  so the session cookies never leave the browser.

  THE API, all POST with a JSON body, cookie session, plus four headers the
  page sends and the API refuses without (appid AP160308, appname
  "Document Access Hub", fid-originating-app-id, fid-originating-app-version):
    * accounts   dpservice.fidelity.com/ftgw/dp/customer-am-acctnxt/v2/accounts
                 -> acctDetails[] of {acctNum, acctType ("Brokerage", "WPS"),
                    preferenceDetail.name}. acctType goes into every download.
    * list       digitalservices.fidelity.com/ftgw/dp/retail-am-financialdoc/v1/
                 accounts/communications/financial-documents/statements
                 body {startDate, endDate, docType: "STMT" | "TC",
                       hasCryptoAccount, annuityAccountLookup}
                 -> statement.docDetails.docDetail[] of {id, type, acctNum,
                    periodStartDate, periodEndDate, generatedDate (epoch
                    seconds, midnight Eastern), formatTypes.formatType.isPDF}
                 A window wider than a year answers 400, so one call per year.
    * tax forms  dpservice.fidelity.com/.../financial-documents/taxform
                 body {taxYear} -> taxSeason.taxFormDetails.taxFormDetail[].
                 UNVERIFIED. The account this was mapped against has no tax
                 forms yet, so the row fields are read defensively and the
                 download's docType for a tax form is a guess ("TAX").
    * download   .../financial-documents/download (v2)
                 body {id, formatType: "PDF", docType, acctType}
                 -> document.docDetail.{content (base64), contentType,
                    deflated}. The decoded content starts with %PDF even
                    when deflated says "Y". Both are handled.

  IDENTITY is kind + account + period end date, never the id. The id is
  stored as a hint and looked up fresh from a new listing at download time.

  The workplace plan (a 401(k), acctType WPS) is listed by the accounts call
  but its statements are on NetBenefits, not in this document center, so
  they are not covered here.

SAFETY (this is a brokerage and retirement account):
  Strictly READ-ONLY. Fidelity can buy and sell securities, transfer and
  wire money, take distributions, change beneficiaries and change where
  money is sent. This app must NEVER activate a control that does any of
  those, never submits a form, never confirms a dialog, and never accepts
  terms on the user's behalf. An expired session raises SessionExpired so a
  run stops loudly rather than reporting an empty success.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlsplit

from paperpull_core.controls import SETTINGS_CONTROL_RE, AUTH_CONTROL_RE

# Everything on its way into a diagnostic file goes through here. It
# lives in core because seventeen apps each had their own copy and
# they drifted into three different versions.
from paperpull_core.redact import redact, set_private_words  # noqa: F401

log = logging.getLogger("fidelity_docs.site")

# Every host this app will read from. Anything else is refused.
ALLOWED_HOSTS = ("fidelity.com",)

BASE = "https://digital.fidelity.com"
DOC_CENTER = "https://digitalservices.fidelity.com/navigate/ent-documentcenter/statements?poe=fidcom"
URLS = {
    "home": f"{BASE}/ftgw/digital/portfolio/summary",
    "login": f"{BASE}/prgw/digital/login/full-page",
    "documents": DOC_CENTER,
}
API = {
    "accounts": "https://dpservice.fidelity.com/ftgw/dp/customer-am-acctnxt/v2/accounts",
    "list": "https://digitalservices.fidelity.com/ftgw/dp/retail-am-financialdoc/v1/accounts/communications/financial-documents/statements",
    "taxforms": "https://dpservice.fidelity.com/ftgw/dp/retail-am-financialdoc/v1/accounts/communications/financial-documents/taxform",
    "download": "https://digitalservices.fidelity.com/ftgw/dp/retail-am-financialdoc/v2/accounts/communications/financial-documents/download",
}
# The page's own app identity. Not a credential, the same for every
# customer, and the API answers 400 without it.
APP_HEADERS = {
    "appid": "AP160308",
    "appname": "Document Access Hub",
    "fid-originating-app-id": "AP160308",
    "fid-originating-app-version": "1",
}
# Kinds this app reads, the API's docType for each, and the category it
# files under. Tax forms have their own call and are listed separately.
KINDS = {
    "STMT": ("Statement", "Statement"),
    "TC": ("Trade Confirmation", "Trade Confirmation"),
}
FIRST_YEAR = 2016        # the oldest year the document center's picker offers

LOGIN_URL_MARKERS = ["/login", "/logon", "/signin", "/sign-in", "/mfa",
                     "/verify", "/onboarding"]


class SessionExpired(RuntimeError):
    """Fidelity answered with a sign-in page instead of the thing asked for."""


def is_safe_url(url: str) -> bool:
    """https, on fidelity.com or a subdomain of it, no credentials in the URL."""
    try:
        parts = urlsplit(url or "")
    except ValueError:
        return False
    host = (parts.hostname or "").lower().rstrip(".")
    if parts.scheme != "https" or not host or parts.username or parts.password:
        return False
    if parts.port not in (None, 443):
        return False
    return any(host == h or host.endswith("." + h) for h in ALLOWED_HOSTS)


# ---------------------------------------------------------------------------
# HARD SAFETY GUARD. Tuned for a brokerage. Never trade, never move money,
# never take a distribution, never change who gets the money.
# ---------------------------------------------------------------------------
FORBIDDEN_CONTROL_RE = re.compile(
    r"(\btrade\b(?!\s*confirm)|\bbuy\b|\bsell\b|\border\b|\bexchange\b|\bquote\b|"
    r"transfer\b|\bwire\b|\bdeposit\b|\bwithdraw|distribution|\brmd\b|"
    r"required\s+minimum|rollover|roll\s+over|contribut|\bmove\s+money\b|"
    r"bill\s*pay|\bpay\b|payment|\bcheck\b|\bloan\b|borrow|margin|options?\s+trading|"
    r"beneficiar|\bconvert|recharacteriz|"
    r"direct\s+deposit|bank\s+account|financial\s+institution|routing|link\s+account|"
    # Word boundaries on both sides of the verb stems. "edit" inside
    # "Credit" and "chang" inside "Exchange" are the two that bit before.
    r"\bchang(e|es|ed|ing)\b|\bedit(s|ed|ing)?\b|\bupdat(e|es|ed|ing)\b|"
    r"\bset\s+up\b|enroll|enable|disable|\bdelet|\bremov(e|es|ed|ing|al)\b|"
    r"\bsubmit|\bconfirm\b|\bagree\b|\baccept\b|authoriz|\bapply\b|"
    r"request\b|\bstart\b|\bbegin\b|initiate|\bopen\s+an?\s+account\b|"
    r"log\s*out|logout|sign\s*out|password|username|"
    r"security\s+question|two-?step|contact\s+info|\baddress\b|\bemail\b|\bphone\b|"
    r"go\s+paperless|delivery\s+preferences|e-?delivery)",
    re.I)

# What a document control may look like. A control must match this AND not
# match the blocklist.
SAFE_DOC_CONTROL_RE = re.compile(
    r"(download|\bview\b|\bopen\b|\bprint\b|\bpdf\b|statement|document|"
    r"1099|5498|tax\s+form|tax\s+statement|tax\s+document|confirmation|"
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
    r"^(documents?|statements?|my\s+statements?|tax\s+(forms?|statements?|documents?)|"
    r"messages?|message\s+cent(er|re)|mailbox|inbox|correspondence|"
    r"document\s+history|account\s+history|history)$", re.I)


SECURITY_CHALLENGE_MARKERS = [
    "one-time passcode", "one time passcode", "enter the code", "verification code",
    "we sent a code", "text message", "authenticator", "confirm your identity",
    "verify your identity", "are you a robot", "captcha", "access denied",
    "your session has expired", "session timed out", "signed out",
]

RATE_LIMIT_MARKERS = ["too many requests", "rate limit", "try again later",
                      "temporarily unavailable", "unusual traffic"]


def looks_signed_out(page) -> bool:
    try:
        url = (page.url or "").lower()
    except Exception:
        return False
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
    hay = title + "\n" + body[:2000]
    for m in SECURITY_CHALLENGE_MARKERS:
        if m in hay:
            return f"Security challenge detected: '{m}'"
    for m in RATE_LIMIT_MARKERS:
        if m in hay:
            return f"Possible rate limiting detected: '{m}'"
    return None


def on_documents_page(page) -> bool:
    """The Document Access Hub. Any of its tabs will do for the API."""
    try:
        url = page.url or ""
        return (is_safe_url(url) and "ent-documentcenter" in url
                and not looks_signed_out(page))
    except Exception:
        return False


def goto_documents(page) -> bool:
    if on_documents_page(page):
        return True
    if URLS["documents"] and is_safe_url(URLS["documents"]):
        try:
            page.goto(URLS["documents"], wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            log.info("documents URL failed: %s", e)
    return on_documents_page(page)


def ensure_statements(page) -> bool:
    return goto_documents(page)


# -- documents ----------------------------------------------------------------------

import base64 as _b64
import zlib as _zlib
from datetime import datetime as _dt, timedelta as _td, timezone as _tz


def parse_date(text: str) -> str:
    """'Feb 9, 2026', '02/09/2026' or '2026-02-09' -> '2026-02-09', else ''."""
    s = (text or "").strip()
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return s[:10]
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", s)
    if m:
        return "%s-%02d-%02d" % (m.group(3), int(m.group(1)), int(m.group(2)))
    m = re.match(r"^([A-Z][a-z]{2})[a-z]*\.? (\d{1,2}), (\d{4})$", s)
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    if m and m.group(1) in months:
        return "%s-%02d-%02d" % (m.group(3), months.index(m.group(1)) + 1, int(m.group(2)))
    return ""


def epoch_date(value) -> str:
    """Fidelity's dates are epoch seconds at midnight Eastern. Twelve hours
    on, read as UTC, is that calendar day in either half of the year."""
    try:
        v = int(value)
    except (TypeError, ValueError):
        return ""
    if v > 10 ** 11:           # milliseconds
        v //= 1000
    return (_dt.fromtimestamp(v, _tz.utc) + _td(hours=12)).strftime("%Y-%m-%d")


# Runs inside the page. One POST with the page's own app headers and the
# session cookies the browser already holds. Returns status and the parsed
# body. Nothing about the session enters this process.
_POST_JS = """async ({url, body, headers}) => {
  const target = new URL(url, location.href);
  const host = target.hostname;
  if (target.protocol !== 'https:' || !(host === 'fidelity.com' || host.endsWith('.fidelity.com'))) {
    throw new Error('Refusing an off-host request');
  }
  const h = Object.assign({'Accept': 'application/json', 'Content-Type': 'application/json'}, headers);
  const r = await fetch(url, {method: 'POST', credentials: 'include', headers: h,
                              body: JSON.stringify(body), redirect: 'error'});
  let j = null;
  try { j = await r.json(); } catch (e) {}
  return {status: r.status, json: j};
}"""


def _post(page, url: str, body: dict) -> dict:
    if not is_safe_url(url):
        raise ValueError("refusing an off-host request")
    res = page.evaluate(_POST_JS, {"url": url, "body": body, "headers": APP_HEADERS})
    status = res.get("status")
    if status in (401, 403):
        raise SessionExpired("Fidelity answered %s" % status)
    if status != 200:
        raise RuntimeError("Fidelity answered %s for %s" % (status, url.rsplit("/", 1)[-1]))
    return res.get("json") or {}


def list_accounts(page) -> dict:
    """acctNum -> {"type": acctType, "name": display name}."""
    body = {"acctCategory": "Brokerage,StockPlans,Annuity,Charitable,FidelityCreditCards,"
                            "InternalDigital,BrokerageLending,RegisteredStock,WorkplaceBenefits,"
                            "WorkplaceContributions",
            "filters": {"returnCustomerAttrDetail": True, "returnPreferenceDetail": True,
                        "returnAcctRelAttrDetail": True, "returnAcctIndDetail": True,
                        "returnOrderedAccounts": True, "returnAcctStateDetail": True}}
    j = _post(page, API["accounts"], body)
    out = {}
    for a in j.get("acctDetails") or []:
        num = str(a.get("acctNum") or "")
        if not num:
            continue
        pref = a.get("preferenceDetail") or {}
        name = pref.get("name") or pref.get("defaultAcctName") or a.get("acctSubTypeDesc") or a.get("acctType") or ""
        out[num] = {"type": a.get("acctType") or "Brokerage", "name": str(name).strip()}
    return out


def account_label(num: str, accounts: dict) -> str:
    """'BrokerageLink 1234', never the whole number."""
    info = accounts.get(num) or {}
    tail = num[-4:] if num else ""
    name = info.get("name") or ""
    return (name + " " + tail).strip() if name else tail


def list_kind(page, doc_type: str, year: int) -> List[dict]:
    """One year of one kind, as the API returns it."""
    body = {"startDate": "%d-01-01" % year, "endDate": "%d-12-31" % year,
            "docType": doc_type, "hasCryptoAccount": False,
            "annuityAccountLookup": doc_type == "STMT"}
    j = _post(page, API["list"], body)
    return ((j.get("statement") or {}).get("docDetails") or {}).get("docDetail") or []


def list_tax_year(page, year: int) -> List[dict]:
    j = _post(page, API["taxforms"], {"taxYear": str(year)})
    return ((j.get("taxSeason") or {}).get("taxFormDetails") or {}).get("taxFormDetail") or []


def _first(d: dict, *keys):
    for k in keys:
        v = d.get(k)
        if v not in (None, ""):
            return v
    return ""


def _row(kind: str, category: str, d: dict, accounts: dict, doc_type: str) -> Optional[dict]:
    num = str(d.get("acctNum") or "")
    date = epoch_date(_first(d, "periodEndDate", "generatedDate", "availableDate", "date"))
    if not date:
        date = parse_date(str(_first(d, "periodEndDate", "generatedDate", "availableDate", "date")))
    if not date:
        return None
    label = account_label(num, accounts)
    acct_type = (accounts.get(num) or {}).get("type") or "Brokerage"
    title = kind
    if doc_type == "STMT" and d.get("periodStartDate") and d.get("periodEndDate"):
        # The hub calls every one "PI Monthly/Quarterly Statement". The
        # period says which, and the filename should too.
        try:
            days = (int(d["periodEndDate"]) - int(d["periodStartDate"])) / 86400
            title = "Quarterly Statement" if days > 45 else "Monthly Statement"
        except (TypeError, ValueError):
            pass
    if doc_type == "TAX":
        name = str(_first(d, "formName", "taxFormName", "formType", "type", "description") or "Tax Form")
        title = name
    start = epoch_date(d.get("periodStartDate")) if d.get("periodStartDate") else ""
    return {
        "title": title, "date": date, "account": label, "category": category,
        "item_id": str(_first(d, "id", "docId", "documentId")),
        "client_id": doc_type + "|" + acct_type,        # what the download call needs
        "period_start": start, "href": API["download"],
    }


def collect_documents(page, keep=None, config: Optional[dict] = None) -> List[dict]:
    """Every statement, trade confirmation and tax form the hub lists, one
    year at a time, newest first. `keep` is the run's scope predicate over
    year labels, so a scoped run does not ask for years it will throw away.
    Which kinds are asked for follows document_types in the config."""
    wanted = set((config or {}).get("document_types") or [c for _, c in KINDS.values()])
    accounts = list_accounts(page)
    this_year = _dt.now().year
    years = [y for y in range(this_year, FIRST_YEAR - 1, -1) if keep is None or keep(str(y))]
    rows: List[dict] = []
    for doc_type, (kind, category) in KINDS.items():
        if category not in wanted:
            continue
        for y in years:
            items = list_kind(page, doc_type, y)
            log.info("%s %d: %d", kind, y, len(items))
            for d in items:
                fmt = ((d.get("formatTypes") or {}).get("formatType") or {})
                if fmt and fmt.get("isPDF") is False:
                    continue
                r = _row(kind, category, d, accounts, doc_type)
                if r:
                    rows.append(r)
    if "Tax Document" in wanted:
        for y in years:
            if y >= this_year:
                continue                      # a tax year is listed once it has ended
            try:
                items = list_tax_year(page, y)
            except RuntimeError as e:
                log.info("tax forms %d: %s", y, e)
                continue
            log.info("tax forms %d: %d", y, len(items))
            for d in items:
                r = _row("Tax Form", "Tax Document", d, accounts, "TAX")
                if r:
                    rows.append(r)
    return rows


def resolve_item(page, title: str, date: str, account: str, occurrence: int = 0) -> Optional[dict]:
    """The document's current id, from a fresh listing of its year."""
    year = int(date[:4])
    accounts = list_accounts(page)
    doc_type = next((k for k, (kind, _) in KINDS.items()
                     if kind == title or (k == "STMT" and title.endswith("Statement"))), None)
    if doc_type:
        items = list_kind(page, doc_type, year)
        kind, category = KINDS[doc_type]
    else:
        items = list_tax_year(page, year) if year < _dt.now().year else []
        doc_type, kind, category = "TAX", "Tax Form", "Tax Document"
    matches = [r for r in (_row(kind, category, d, accounts, doc_type) for d in items)
               if r and r["title"] == title and r["date"] == date and r["account"] == account]
    return matches[occurrence] if occurrence < len(matches) else None


def fetch_pdf(page, item_id: str, doc_type: str, acct_type: str) -> bytes:
    """The PDF bytes for one document, through the page."""
    j = _post(page, API["download"], {"id": item_id, "formatType": "PDF",
                                      "docType": doc_type, "acctType": acct_type})
    dd = (j.get("document") or {}).get("docDetail") or {}
    content = dd.get("content") or ""
    if not content:
        return b""
    raw = _b64.b64decode(content)
    if raw[:4] != b"%PDF" and str(dd.get("deflated", "")).upper().startswith("Y"):
        for wbits in (15, -15, 31):
            try:
                raw = _zlib.decompress(raw, wbits)
                break
            except _zlib.error:
                continue
    return raw


def download_document(page, title: str, date: str, out_path: Path, occurrence: int = 0,
                      item_hint: str = "", client_hint: str = "", account: str = "") -> bool:
    """Save one document. Looks it up again by kind, account and date
    first, and falls back to the stored id only when the listing no longer
    shows it."""
    found = resolve_item(page, title, date, account, occurrence) if account else None
    item_id = (found or {}).get("item_id") or item_hint
    client = (found or {}).get("client_id") or client_hint or "STMT|Brokerage"
    if not item_id:
        log.warning("no id for %s %s", title, date)
        return False
    doc_type, _, acct_type = client.partition("|")
    data = fetch_pdf(page, item_id, doc_type or "STMT", acct_type or "Brokerage")
    if not data.startswith(b"%PDF"):
        log.warning("not a PDF for %s %s (%d bytes)", title, date, len(data))
        return False
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(data)
    return True
def _shape(obj, depth=0):
    """The shape of a JSON body, never its values."""
    if depth > 3:
        return "..."
    if isinstance(obj, dict):
        return {k: _shape(v, depth + 1) for k, v in list(obj.items())[:25]}
    if isinstance(obj, list):
        return ["list of %d" % len(obj), _shape(obj[0], depth + 1) if obj else None]
    return type(obj).__name__


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
    """What the signed-in Document Access Hub looks like, without downloading anything.

    Records the page, its headings and controls with the guard's verdict on
    each, and every JSON response fidelity.com sends while the page settles. Then
    follows, one at a time and back again, the few links whose text is
    exactly a document word, recording the same for each. Bodies
    are recorded as shape only, never values, and any run of six digits is
    masked. No screenshot, a retirement account page shows balances."""
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
                    body = res.json()
                    entry["shape"] = _shape(body)
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
                    "^" + re.escape(c["text"].replace("#", "")) + "$", re.I)).first
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
