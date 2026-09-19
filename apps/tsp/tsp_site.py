"""ALL Thrift Savings Plan (tsp.gov) selectors, URLs, and page behavior live here.

When My Account changes, repair this file only.

STATUS, mapped 2026-09-18 against a signed-in My Account.

  My Account is not on tsp.gov's own pages. After sign-in the browser lands
  on api.rk.tsp.gov, an Angular app from the plan's recordkeeper, with
  hash routes under /web/converge/. Statements and tax forms are messages
  in the Secure Mailbox, each with one PDF attached. Thirty messages went
  back to January 2022 on the account this was mapped against.

  THE API, all GET, nothing clicked, nothing navigated:
    * list      /api/channel/personmessages/personMessages/spm
                  ?subcategory=items&pgNum=N&days=0&dlvDtOrdr=DESC
                -> spm.items[] of {mailboxItemId, mailItemSubject,
                   deletionDate, mimeType, unread, clientId, ...} ten a
                   page, spm.unfilteredMsgCount for the total
    * content   the same path
                  ?subcategory=itemContent&itemId=<mailboxItemId>&clientId=<clientId>
                -> spm.itemContent.pdfContent, the PDF as base64

  AUTH: cookies alone answer 401. Two headers are needed,
  alightpersonsessiontoken and alightrequestheader, whose values sit in
  sessionStorage under alightPersonSessionToken and alightRequestHeader.
  Every call runs INSIDE the page with page.evaluate(fetch(...)) and reads
  both in the same expression, so the session token never enters this
  process, is never logged and never touches disk. The PDF comes back as
  base64 from the page.

  IDENTITY is subject + date, never the mailboxItemId. The id is stored as
  a hint and looked up fresh at download time, the lesson from myPay, whose
  ids turned out to die with the session. deletionDate is the field's own
  name and it holds the delivery date (the newest message carried today's
  date), so it is used as the document date.

  ONE SIDE EFFECT, stated plainly. Fetching a message's content is what the
  site itself does when a message is opened, and it marks the message as
  read. The unread count in the mailbox goes down as documents are
  downloaded. Nothing else changes.

  Not every message is a document to keep. Notices such as Payment
  Confirmation, Payment Rights Notice and Rollover Contribution Status are
  classified as Other Document and skipped unless "Other Document" is added
  to document_types in config.json.

SAFETY (this is a US federal retirement account):
  Strictly READ-ONLY. My Account can move money between funds, change
  contribution allocations, start a withdrawal or an installment, take a
  loan, change beneficiaries and change where money is sent. This app must
  NEVER activate a control that does any of those, never submits a form,
  never confirms a dialog, and never accepts terms on the user's behalf.

  Two further rules for a government system:
    * the user signs in themselves, enters their own passcode, and accepts
      any consent banner themselves. This app does not click through a
      government consent banner.
    * an expired session raises SessionExpired so a run stops loudly rather
      than reporting an empty success.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlsplit

from paperpull_core.controls import SETTINGS_CONTROL_RE, AUTH_CONTROL_RE

log = logging.getLogger("tsp_docs.site")

# Every host this app will read from. Anything else is refused, including
# the government's own single sign-on hosts, which are the user's business.
ALLOWED_HOSTS = ("tsp.gov",)

BASE = "https://www.tsp.gov"
MYACCOUNT = "https://api.rk.tsp.gov"
API_BASE = f"{MYACCOUNT}/api/channel/personmessages/personMessages/spm"
URLS = {
    "home": f"{BASE}/",
    "login": f"{BASE}/login/",
    # The mailbox. Any signed-in api.rk.tsp.gov page will do for the API,
    # so this is only navigated to when the tab is somewhere else entirely.
    "documents": f"{MYACCOUNT}/api/angularfirst-app/ah-angular-afirst-web/#/web/converge/gmc?selecttab=1",
}

LOGIN_URL_MARKERS = ["/login", "/logon", "/signin", "/sign-in", "/mfa",
                     "/verify", "/onboarding"]


class SessionExpired(RuntimeError):
    """My Account answered with a sign-in page instead of the thing asked for."""


def is_safe_url(url: str) -> bool:
    """https, on tsp.gov or a subdomain of it, no credentials in the URL."""
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
# HARD SAFETY GUARD. Tuned for a retirement plan. Never move money between
# funds, never change contributions, never withdraw, never borrow, never
# change who gets the money.
# ---------------------------------------------------------------------------
FORBIDDEN_CONTROL_RE = re.compile(
    r"(interfund|fund\s+transfer|transfer\b|reallocat|realloc\b|allocation\b|"
    r"rebalance|contribution\s+(amount|allocation|election|change)|"
    r"contribut(e|ion\s+percent)|catch-?up|"
    r"withdraw|distribution|installment|annuity\s+purchase|"
    r"\bloan\b|borrow|repay|rollover|roll\s+over|transfer\s+in|"
    r"required\s+minimum|\brmd\b|"
    r"beneficiar|court\s+order|"
    r"direct\s+deposit|bank\s+account|financial\s+institution|routing|"
    r"\bpay\b|payment|"
    # Word boundaries on both sides of the verb stems. "edit" inside
    # "Credit" and "chang" inside "Exchange" are the two that bit before.
    r"\bchang(e|es|ed|ing)\b|\bedit(s|ed|ing)?\b|\bupdat(e|es|ed|ing)\b|"
    r"\bset\s+up\b|enroll|enable|disable|\bdelet|\bremov(e|es|ed|ing|al)\b|"
    r"\bsubmit|\bconfirm\b|\bagree\b|\baccept\b|authoriz|\bapply\b|"
    r"request\b|\bstart\b|\bbegin\b|initiate|"
    r"mutual\s+fund\s+window|\bmfw\b|"
    r"log\s*out|logout|sign\s*out|password|username|thriftline\s+pin|\bpin\b|"
    r"security\s+question|two-?step|contact\s+info|\baddress\b|\bemail\b|\bphone\b)",
    re.I)

# What a document control may look like. A control must match this AND not
# match the blocklist. Message-center words are here because TSP delivers
# statements and tax forms to a mailbox.
SAFE_DOC_CONTROL_RE = re.compile(
    r"(download|\bview\b|\bopen\b|\bprint\b|\bpdf\b|statement|document|"
    r"1099|tax\s+form|tax\s+statement|letter|notice|correspondence|"
    r"message|mailbox|inbox|history|annual|quarterly)", re.I)


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
    """Any signed-in page of the My Account app. The API is reachable from
    all of them, since the headers it needs live in sessionStorage."""
    try:
        url = page.url or ""
        return (is_safe_url(url) and urlsplit(url).hostname == "api.rk.tsp.gov"
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


# -- the mailbox API -----------------------------------------------------------

DOCUMENT_TYPES = {"application/pdf": "PDF attachment"}

_DATE_RE = re.compile(r"^([A-Z][a-z]{2}) (\d{1,2}), (\d{4})$")
_MONTHS = {m: i + 1 for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])}


def parse_date(text: str) -> str:
    """'Feb 9, 2026' -> '2026-02-09'. Anything else -> ''."""
    m = _DATE_RE.match((text or "").strip())
    if not m or m.group(1) not in _MONTHS:
        return ""
    return "%s-%02d-%02d" % (m.group(3), _MONTHS[m.group(1)], int(m.group(2)))


# Runs inside the page. Reads the two session headers and makes one GET.
# Returns status and the parsed body, or the base64 content only when asked,
# and never the headers themselves.
_FETCH_JS = """async ({url, want}) => {
  const target = new URL(url, location.href);
  if (target.protocol !== 'https:' || target.hostname !== 'api.rk.tsp.gov') {
    throw new Error('Refusing an off-host request');
  }
  const h = {'Accept': 'application/json', 'Content-Type': 'application/json',
             'alightpersonsessiontoken': sessionStorage.getItem('alightPersonSessionToken') || '',
             'alightrequestheader': sessionStorage.getItem('alightRequestHeader') || ''};
  const r = await fetch(url, {credentials: 'include', headers: h, redirect: 'error'});
  let j = null;
  try { j = await r.json(); } catch (e) {}
  if (want === 'items') {
    const spm = (j && j.spm) || {};
    return {status: r.status, total: spm.unfilteredMsgCount, items: spm.items || null};
  }
  if (want === 'pdf') {
    const ic = j && j.spm && j.spm.itemContent;
    return {status: r.status, mimetype: ic ? ic.mimetype : null, b64: ic ? (ic.pdfContent || '') : ''};
  }
  return {status: r.status};
}"""


def _api(page, url: str, want: str) -> dict:
    if not is_safe_url(url):
        raise ValueError("refusing an off-host request")
    res = page.evaluate(_FETCH_JS, {"url": url, "want": want})
    if res.get("status") in (401, 403):
        raise SessionExpired("My Account answered %s" % res["status"])
    return res


def list_messages(page) -> List[dict]:
    """Every message in the mailbox, newest first, ten a page until the
    count the first page reports is reached."""
    out: List[dict] = []
    page_no = 1
    total = None
    while True:
        res = _api(page, "%s?subcategory=items&pgNum=%d&days=0&dlvDtOrdr=DESC"
                   % (API_BASE, page_no), "items")
        items = res.get("items") or []
        if total is None:
            total = int(res.get("total") or 0)
        out.extend(i for i in items if isinstance(i, dict))
        if not items or len(out) >= total or page_no > 200:
            break
        page_no += 1
    return out


def collect_documents(page) -> List[dict]:
    """The mailbox as document rows. Only messages with a PDF attached."""
    rows = []
    messages = list_messages(page)
    for m in messages:
        if (m.get("mimeType") or "").lower() != "application/pdf":
            continue
        title = re.sub(r"\s+", " ", m.get("mailItemSubject") or "").strip()
        date = parse_date(m.get("deletionDate") or "")
        if not title or not date:
            log.info("skipping a message with no usable subject or date")
            continue
        rows.append({"title": title, "date": date,
                     "item_id": str(m.get("mailboxItemId") or ""),
                     "client_id": str(m.get("clientId") or ""),
                     "unread": bool(m.get("unread"))})
    log.info("TSP mailbox: %d message(s), %d with a PDF", len(messages), len(rows))
    return rows


def resolve_item(page, title: str, date: str, occurrence: int = 0) -> Optional[dict]:
    """Find the message by subject and date in a fresh listing."""
    n = 0
    for row in collect_documents(page):
        if row["title"] == title and row["date"] == date:
            if n == occurrence:
                return row
            n += 1
    return None


def fetch_pdf(page, item_id: str, client_id: str) -> bytes:
    import base64
    from urllib.parse import quote
    if not re.fullmatch(r"[0-9a-f]{24}", item_id or ""):
        raise ValueError("mailboxItemId does not look like one")
    if not re.fullmatch(r"\d{1,8}", client_id or ""):
        raise ValueError("clientId does not look like one")
    url = "%s?subcategory=itemContent&itemId=%s&clientId=%s" % (
        API_BASE, quote(item_id), quote(client_id))
    res = _api(page, url, "pdf")
    if res.get("status") != 200 or not res.get("b64"):
        log.info("content answered %s with %d chars", res.get("status"), len(res.get("b64") or ""))
        return b""
    return strip_print_stream_prefix(base64.b64decode(res["b64"]))


def strip_print_stream_prefix(data: bytes) -> bytes:
    """The 1099-R arrives with a print-stream line in front of the PDF,
    "%%UC_CLIENT_INPUT_FILE_NAME" then a newline, then %PDF-. Statements do
    not. Anything before a %PDF- found in the first kilobyte is dropped.
    Readers rebuild the cross-reference table that the shift puts out by a
    few bytes, and the core's validator does the same. Anything with no
    %PDF- near the front is not a PDF and is refused."""
    if data[:5] == b"%PDF-":
        return data
    i = data.find(b"%PDF-", 0, 1024)
    if i < 0:
        return b""
    log.info("dropping %d bytes of print-stream prefix before the PDF header", i)
    return data[i:]


def download_document(page, title: str, date: str, out_path: Path,
                      item_hint: str = "", client_hint: str = "",
                      occurrence: int = 0) -> bool:
    row = resolve_item(page, title, date, occurrence)
    if row is None and item_hint and client_hint:
        log.info("%r (%s) not in the fresh list, trying the stored id", title, date)
        row = {"item_id": item_hint, "client_id": client_hint}
    if row is None:
        log.info("%r (%s) could not be resolved", title, date)
        return False
    data = fetch_pdf(page, row["item_id"], row["client_id"])
    if not data:
        return False
    Path(out_path).write_bytes(data)
    return True


# -- survey, the evidence diagnose gathers --------------------------------------

_ID_RE = re.compile(r"\d{6,}")


def redact(text: str) -> str:
    """Runs of six or more digits become #, so an account number in a URL,
    a heading or a link never reaches the survey file."""
    return _ID_RE.sub(lambda m: "#" * len(m.group(0)), text or "")


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
    """What a signed-in My Account looks like, without downloading anything.

    Records the page, its headings and controls with the guard's verdict on
    each, and every JSON response tsp.gov sends while the page settles. Then
    follows, one at a time and back again, the few links whose text is
    exactly a document or mailbox word, recording the same for each. Bodies
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
