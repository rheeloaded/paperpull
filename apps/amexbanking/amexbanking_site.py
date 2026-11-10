"""American Express Banking pages, addresses and calls.

When American Express changes its banking site, repair this file only.

Scope is American Express National Bank deposit accounts. Business Checking
has been run, and Personal Checking and Savings have not. American Express
cards are the amex app.

Read-only. This module opens the Documents and Statements page by its
address, hears the document list that page asks for itself, and asks for
each PDF by its own id from inside the signed-in page, the way the page
does. Nothing on any page is pressed, typed into or chosen. It never sends
a payment, moves money, orders checks, opens an account or changes a
setting. FORBIDDEN_CONTROL_RE refuses those words for Diagnose, which reads
the page's controls and presses none of them.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional

from paperpull_core import intake
from paperpull_core.characters import whole_json
from paperpull_core.dates import last_day as _last_day
from paperpull_core.dates import MONTH_NAMES

log = logging.getLogger("amexbanking_docs.site")


URLS = {
    "home": "https://www.americanexpress.com/",
    "login": "https://www.americanexpress.com/en-us/account/login/",
    "documents": ("https://www.americanexpress.com/en-us/banking/business/checking/"
                  "accounts/manage/documents"),
}
DOCUMENTS_URL = URLS["documents"]

# The two calls of the banking API this app knows. The list is heard while
# the Documents and Statements page asks for it, and each PDF is asked for
# at this one address, never at an address taken from the page's traffic.
LIST_URL = "https://functions.americanexpress.com/ReadBankingAccountDocumentList.v1"
DOCUMENT_URL = "https://functions.americanexpress.com/ReadBankingDocument.v1"

LOGIN_URL_MARKERS = [
    "/login", "/logon", "/signin", "/sign-in", "/auth",
    "/mfa", "/verification", "/challenge", "myca/logon"
]

# Never pressed, and never called safe by Diagnose. The app presses nothing
# at all, so this only marks what Diagnose reads off the page. "Rewards
# Checking" is the name of an account, and its statements are documents.
FORBIDDEN_CONTROL_RE = re.compile(
    r"(pay\b|pay\s+bill|payments?\b|autopay|auto\s*pay|"
    r"transfer|wire\b|withdraw|deposit|move\s+money|send\s+money|"
    r"apply|apply\s+now|open\s+(a\s+)?(new\s+)?account|new\s+account|"
    r"link\s+(bank|account)|order\b|give\b|gift|rewards?\b(?!\s+checking)|"
    r"line\s+of\s+credit|download\s+(the\s+)?app|"
    r"close\s+account|lock\b|freeze\b|dispute|report\s+fraud|"
    r"change\s+password|edit\s+profile|update\s+address|manage\b|"
    r"delete|remove|enroll|subscribe|confirm|submit)", re.I
)

# Words that name a document, not words that name an action. "Open" and
# "View" alone also start "Open New Account" and "View All Gift Cards".
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
    for m in RATE_LIMIT_MARKERS:
        if m in hay:
            return f"Possible rate limiting detected: '{m}'"
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


class SessionExpired(Exception):
    """American Express answered the list or a PDF as a session it no
    longer holds, a 401 or a 403, or a redirect where an answer was asked
    for. Every request after it would get the same, so the run stops."""


# ---------------------------------------------------------------------------
# Data models
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
    # The last four digits the page's account switcher showed when this
    # document's list answered, "" when they could not be read.
    account_digits: str = ""
    document_size: str = ""
    row_index: int = 0
    kind: str = "doc"

    def get(self, key: str, default=None):
        if key == "date":
            return self.date_text or default
        if key in ("documentId", "document_id"):
            return self.document_id or default
        return getattr(self, key, default)

    def __getitem__(self, key: str):
        val = self.get(key)
        if val is None:
            raise KeyError(key)
        return val


class Listed(list):
    """The documents a list held. passed_over names each part of it that
    was not read, so the list is not whole when it names any. token is the
    account token the list was asked with and digits the last four the
    account switcher showed, each "" when there is none to read."""
    passed_over: tuple = ()
    token: str = ""
    digits: str = ""


def _listed(items, passed_over=(), token: str = "", digits: str = "") -> Listed:
    out = Listed(items)
    out.passed_over = tuple(sorted(set(passed_over)))
    out.token, out.digits = token, digits
    return out


@dataclass
class ListAnswer:
    """One answer the page's own list call got, as it was heard."""
    token: str
    status: int
    data: Any = None


@dataclass
class BankingSession:
    account_label: str = ""
    label_configured: bool = False
    answers: List[ListAnswer] = field(default_factory=list)
    # Each PDF saved this run by a fingerprint of its bytes, with the id it
    # was asked for, so a second document answered with the same bytes is
    # never saved as its own.
    saved: dict = field(default_factory=dict)
    # The tabs whose list answers are heard. Kept here and not on the tab,
    # so a tab off the site is asked nothing to find out.
    heard: list = field(default_factory=list)


SESSION = BankingSession()


# What passed_over names. A list that answered with no documents is what a
# new account shows, and a list that did not load can look the same, so it
# is not noted whole but stops nothing.
EMPTY_LIST = "list that answered with no documents"
NOT_A_LIST = "answer that is not a list of documents"
SHORT_OF_COUNT = "list shorter or longer than its own count"
NO_COUNT = "list that says no count of its own"
NO_ID = "document with no id"
NO_DATE = "document whose date could not be read"
UNKNOWN_KIND = "document of a kind this app does not know"
NO_ANSWER = "list call that did not answer"
NO_TOKEN = "list asked for no account"
SEVERAL_ACCOUNTS = "lists of more than one account"


# ---------------------------------------------------------------------------
# The document list
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


def _year(raw: Any) -> Optional[int]:
    """A year the list names, or None when it is no year."""
    s = str(raw if raw is not None else "").strip()
    if not re.fullmatch(r"\d{4}", s):
        return None
    y = int(s)
    return y if 1990 <= y <= 2099 else None


def _count_of(data: dict) -> Optional[int]:
    """The number of documents the answer says it holds, or None."""
    raw = data.get("totalCount")
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str) and raw.strip().isdigit():
        return int(raw.strip())
    return None


def parse_banking_document_list(data: dict, account_label: str = "Business Checking",
                                account_token: str = "") -> Listed:
    """The documents a ReadBankingAccountDocumentList.v1 answer holds.

    A statement is dated the last day of its month and a tax form Dec 31 of
    its tax year. A document whose id, month or year cannot be read, or of
    a kind this app does not know, is left out and named in passed_over, so
    the list is not whole, and nothing is filed under a date or an id that
    was guessed. So is an answer holding a count its list disagrees with,
    and an answer holding no count, since nothing else says the page asked
    for all of it in one answer."""
    docs: List[RawDoc] = []
    passed_over = set()
    if not isinstance(data, dict) or not isinstance(data.get("statements"), list):
        log.warning("The documents list answered with something that is not a list")
        return _listed(docs, {NOT_A_LIST})

    statements = data["statements"]
    if not statements:
        passed_over.add(EMPTY_LIST)
    count = _count_of(data)
    if count is None:
        log.warning("The documents list says no count of its own, so it is not read as whole")
        passed_over.add(NO_COUNT)
    elif count != len(statements):
        log.warning("The documents list says it holds %d and holds %d", count, len(statements))
        passed_over.add(SHORT_OF_COUNT)

    for idx, item in enumerate(statements):
        if not isinstance(item, dict):
            passed_over.add(NOT_A_LIST)
            continue

        doc_id = str(item.get("documentIdentifier") or item.get("documentId")
                     or item.get("id") or item.get("tag") or "").strip()
        if not doc_id:
            log.warning("Passing over a document the list names with no id")
            passed_over.add(NO_ID)
            continue
        doc_size = str(item.get("documentSize") or "").strip()
        tag = str(item.get("tag") or doc_id).strip()

        tax_year = item.get("taxYear")
        tax_form_type = str(item.get("taxFormType") or "").strip()
        month_raw = item.get("statementMonth")
        year_raw = item.get("statementYear")
        if tax_year and tax_form_type:
            y = _year(tax_year)
            if y is None:
                log.warning("Passing over a tax form whose year could not be read")
                passed_over.add(NO_DATE)
                continue
            docs.append(RawDoc(
                title=f"{tax_form_type} Tax Form",
                date_text=f"{y:04d}-12-31",
                href=doc_id,
                category="Tax Document",
                tag=tag,
                document_id=doc_id,
                account=account_label,
                account_token=account_token,
                document_size=doc_size,
                row_index=idx,
            ))
            continue

        if month_raw and year_raw:
            m, y = _parse_month_num(month_raw), _year(year_raw)
            if not m or y is None:
                log.warning("Passing over a statement whose month could not be read")
                passed_over.add(NO_DATE)
                continue
            docs.append(RawDoc(
                title=f"{account_label} Statement",
                date_text=f"{y:04d}-{m:02d}-{_last_day(y, m):02d}",
                href=doc_id,
                category="Statement",
                tag=tag,
                document_id=doc_id,
                account=account_label,
                account_token=account_token,
                document_size=doc_size,
                row_index=idx,
            ))
            continue

        log.warning("Passing over a document that is neither a statement nor a tax form")
        passed_over.add(UNKNOWN_KIND)

    return _listed(docs, passed_over)


# ---------------------------------------------------------------------------
# Hearing the page's own list call
# ---------------------------------------------------------------------------

def _token_of(request) -> str:
    """The accountToken a banking API request was posted with, or ""."""
    try:
        post_data = request.post_data
        if post_data:
            tok = whole_json(json.loads(post_data)).get("accountToken")
            if tok:
                return str(tok)
    except Exception:
        pass
    return ""


_ACCOUNT_URL_RE = re.compile(r"/banking/(business|personal)/(checking|savings)", re.I)


def account_kind_from_url(url: str) -> str:
    """The kind of account a banking page is for, read from its address,
    for when no label is configured or shown, "Business Checking",
    "Business Savings", "Personal Checking" or "Personal Savings"."""
    m = _ACCOUNT_URL_RE.search(url or "")
    if m:
        return f"{m.group(1).title()} {m.group(2).title()}"
    return "American Express Banking"


def attach_banking_listener(page, session: Optional[BankingSession] = None) -> None:
    """Hear each answer the page's own list call gets, with the account
    token it was asked with. Nothing is asked here, only heard."""
    session = session or SESSION
    if any(p is page for p in session.heard):
        return
    session.heard.append(page)

    def on_response(response):
        url = response.url or ""
        if "ReadBankingAccountDocumentList" not in url or not is_safe_url(url):
            return
        try:
            status = int(response.status or 0)
        except Exception:
            status = 0
        token = _token_of(response.request)
        data = None
        if status == 200:
            try:
                data = whole_json(response.json())
            except Exception as e:
                log.info("The documents list answer could not be read (%s)", type(e).__name__)
        session.answers.append(ListAnswer(token=token, status=status, data=data))
        log.info("Heard the documents list answer (%s)", status)

    page.on("response", on_response)


# ---------------------------------------------------------------------------
# The Documents and Statements page
# ---------------------------------------------------------------------------

_SWITCHER_COMBOBOX_SEL = "[data-testid='simple_switcher_combobox'], [data-test-id='simple_switcher_combobox']"
_SWITCHER_SELECTED_DISPLAY_SEL = "[data-testid='simple_switcher_selected_option_display'], [data-test-id='simple_switcher_selected_option_display']"
_SWITCHER_NAME_SEL = "[data-testid='simple_switcher_display_name'], [data-test-id='simple_switcher_display_name']"
_SWITCHER_NUM_SEL = "[data-testid='simple_switcher_display_number'], [data-test-id='simple_switcher_display_number']"


def clean_account_name(raw: str) -> str:
    s = re.sub(r"[®™]", "", raw or "")
    return re.sub(r"\s+", " ", s).strip()


def read_switcher(page):
    """The name and the last four digits of the account the page's account
    switcher shows, each "" when it cannot be read. The page's other text is
    not read for them, since a name and four digits there may be anything."""
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
                digits = digits[-4:] if len(digits) >= 4 else ""
                if name or digits:
                    return name, digits
    except Exception:
        pass
    return "", ""


def detect_account_label(page) -> str:
    """The account the page's account switcher shows, its name and the last
    four of its number, or "" when the switcher cannot be read."""
    name, digits = read_switcher(page)
    return f"{name} {digits}" if name and digits else name


def on_documents_page(page) -> bool:
    url = (page.url or "").lower()
    return is_safe_url(page.url or "") and (
        "/accounts/manage/documents" in url or ("/accounts/" in url and "/documents" in url))


def _wait_for_answers(page, session: BankingSession) -> None:
    waited = 0
    while not session.answers and waited < 15000:
        page.wait_for_timeout(500)
        waited += 500
    if session.answers:
        # A second answer, another part of the list, may follow the first.
        page.wait_for_timeout(1500)


def goto_documents(page, session: Optional[BankingSession] = None) -> bool:
    """Open Documents and Statements by its address, or load it again when
    it is open already, and wait for the list the page asks for. True once
    an answer was heard. Answers heard before are let go first, so a list
    is only ever the one this page load asked for."""
    session = session or SESSION
    if is_safe_url(page.url or "") and looks_signed_out(page):
        return False
    attach_banking_listener(page, session)
    session.answers.clear()
    try:
        if on_documents_page(page):
            log.info("Documents and Statements is open, loading it again for its list")
            page.reload(wait_until="domcontentloaded")
        else:
            log.info("Opening Documents and Statements")
            page.goto(DOCUMENTS_URL, wait_until="domcontentloaded", timeout=30000)
        _wait_for_answers(page, session)
    except Exception as e:
        log.warning("Documents and Statements did not open (%s)", str(e).splitlines()[0][:80])
    return bool(session.answers)


def ensure_statements(page, session: Optional[BankingSession] = None) -> bool:
    """Documents and Statements is open and its list answered, opening it
    when it is not. Nothing on the page is pressed."""
    session = session or SESSION
    if is_safe_url(page.url or "") and looks_signed_out(page):
        return False
    attach_banking_listener(page, session)
    if session.answers and on_documents_page(page):
        return True
    return goto_documents(page, session)


def answers_its_list(page, session: Optional[BankingSession] = None) -> bool:
    """Whether the documents list the page asked for answered as a list,
    which a tab that only sits at the page's address does not show."""
    session = session or SESSION
    return any(a.status == 200 and isinstance(a.data, dict)
               and isinstance(a.data.get("statements"), list) for a in session.answers)


def collect_documents(page, session: Optional[BankingSession] = None) -> Optional[Listed]:
    """Every document the list this page load asked for holds, or None when
    no list answered at all.

    Each document is filed under the account token its own list was asked
    with and under the account the page shows once the list answered. A
    list that answered 401 or 403 raises SessionExpired. One that answered
    anything else, or was asked for no account, and answers for more than
    one account, which this app cannot name apart, leave their documents
    out and are named in passed_over, so the list is not whole."""
    session = session or SESSION
    if not session.answers:
        goto_documents(page, session)
    answers = list(session.answers)
    if not answers:
        return None
    if any(a.status in (401, 403) for a in answers):
        raise SessionExpired("American Express refused the documents list")

    passed_over = set()
    good = []
    for a in answers:
        if a.status != 200 or a.data is None:
            passed_over.add(NO_ANSWER)
        elif not a.token:
            passed_over.add(NO_TOKEN)
        else:
            good.append(a)
    tokens = {a.token for a in good}
    if len(tokens) > 1:
        log.warning("The page asked for the documents lists of %d accounts", len(tokens))
        return _listed([], passed_over | {SEVERAL_ACCOUNTS})
    token = next(iter(tokens), "")

    # The switcher is read even when the config names the account, since its
    # digits are what says which account the page shows.
    name, digits = read_switcher(page)
    if session.label_configured and session.account_label:
        label = session.account_label
    else:
        label = ((f"{name} {digits}" if name and digits else name)
                 or account_kind_from_url(page.url or ""))

    docs, seen = [], set()
    for a in good:
        listed = parse_banking_document_list(a.data, account_label=label, account_token=a.token)
        passed_over.update(listed.passed_over)
        for d in listed:
            if d.document_id not in seen:
                seen.add(d.document_id)
                d.account_digits = digits
                docs.append(d)
    log.info("collect_documents found %d documents", len(docs))
    return _listed(docs, passed_over, token=token, digits=digits)


# ---------------------------------------------------------------------------
# Download
#
# One way only. The PDF is asked for by its own id and its own account's
# token at DOCUMENT_URL, from inside the signed-in page, which carries the
# session cookies. It comes back as base64 in a JSON answer, read only up
# to the limit a document has, and the bytes must hold %PDF- within their
# first 1024 bytes before anything is written.
# ---------------------------------------------------------------------------

# The answer carries the PDF as base64, a third longer than the PDF itself.
ANSWER_BYTES = intake.DOCUMENT_BYTES // 3 * 4 + 1024 * 1024

_DOCUMENT_JS = r"""async ([url, body]) => {
  let r = null;
  try {
    r = await fetch(url, {
      method: 'POST',
      credentials: 'include',
      headers: {'Content-Type': 'application/json', 'Accept': 'application/json'},
      body: JSON.stringify(body)
    });
  } catch (e) {
    return {status: 0};
  }
  if (r.status !== 200) return {status: r.status, redirected: r.redirected};
  // The document itself is in this answer, so it is read only up to the
  // limit a document has (intake.evaluate).
  let data = null;
  try { data = await ppJson(r); } catch (e) { if (ppRefused(e)) throw e; }
  return {status: 200, redirected: r.redirected, data};
}"""


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
                         session: Optional[BankingSession] = None, **kw) -> bool:
    """Save the PDF of `doc`, asked for by its own id with the token of the
    account its list was asked for. A document with either missing is not
    asked for. A 401, a 403 or a redirect raises SessionExpired. A PDF whose
    bytes are those of another document saved this run is not written."""
    session = session or SESSION
    doc_id = getattr(doc, "document_id", "") or ""
    token = getattr(doc, "account_token", "") or ""
    if not doc_id or not token:
        log.warning("Not asking for a %s with no id or no account token",
                    getattr(doc, "category", "document"))
        return False

    body_data = {"accountToken": token, "bankingDocument": {"identifier": doc_id}}
    try:
        got = intake.evaluate(page, _DOCUMENT_JS, [DOCUMENT_URL, body_data],
                              limit=ANSWER_BYTES) or {}
    except intake.TooLarge:
        return False
    except Exception as e:
        log.warning("Asking for the document failed (%s)", type(e).__name__)
        return False
    if not isinstance(got, dict):
        return False
    if got.get("redirected") or got.get("status") in (401, 403):
        raise SessionExpired("American Express refused a document")
    data = got.get("data")
    if got.get("status") != 200 or not isinstance(data, dict):
        log.warning("The document answered %s", got.get("status"))
        return False

    content_str = data.get("documentContent") or ""
    if not isinstance(content_str, str) or not content_str:
        log.warning("The document answer held no PDF")
        return False
    try:
        pdf_bytes = intake.decode(content_str)
    except Exception as e:
        log.warning("The document's PDF could not be decoded (%s)", type(e).__name__)
        return False

    digest = hashlib.sha256(pdf_bytes).hexdigest()
    other = session.saved.get(digest)
    if other is not None and other != doc_id:
        log.warning("The PDF answered for one document is the one saved for another "
                    "this run, so it is not saved")
        return False
    if not _write_if_pdf(pdf_bytes, out_path):
        return False
    session.saved[digest] = doc_id
    return True
