"""ALL citi.com selectors, URLs, and page behavior live here.

When Citi changes its site, repair this file only.

STATUS: mapped 2026-09-20 against a signed-in session and verified end to
end (accounts, list, PDF).

HOW THE SITE WORKS
  Citi Online is an Angular app on online.citi.com. Sign-in lands on the
  dashboard. The Account Statements page is /US/nga/accstatement, and it
  is fed by a JSON API the page calls itself. This app makes the same
  calls from inside the signed-in page, so the session never leaves the
  browser and nothing on the page is clicked.

  All four are POST with a JSON body, cookie session, plus the page's own
  app identity headers (APP_HEADERS below, the same for every customer):
    accounts  .../accounts/statementsAndLetters/eligibleAccounts/retrieve
              body {transactionCode: "1079_statements"}
              -> eligibleAccounts.cardAccounts[] of {accountId (an opaque
                 uuid), accountNickname "Costco Anywhere Visa Card by Citi
                 - 1234", accountType "CARDS"}
    list      .../card/accounts/statements/accountsAndStatements/retrieve
              body {accountId}
              -> statementsByYear[] of {displayYearTitle,
                 statementsByMonth[] of {statementDate "MM/DD/YYYY"}},
                 accountOpenDate, archivedStatementsEligibleFlag.
                 The site lists roughly the last two years online.
    pdf       .../card/accounts/statements/recent/retrieve
              body {accountId, statementDate "MM/DD/YYYY",
                    requestType "RECENT STATEMENTS"}
              -> application/pdf, the statement itself.
    requested .../card/accounts/statements/archiveStatements/retrieve
              body {accountId}
              -> archivedStatementRequestStartDate "MM/DD/YYYY",
                 archivedStatementsByMonth[] of {displayDate "Oct 2020",
                 statementDate "202010" (the month alone, no day),
                 statusIndicator "F" for ready, documentExpiryDate
                 "20201204", documentExpirationDateText "Dec, 04"}.
              The same pdf call takes one of them with requestType
              "ARCHIVED STATEMENTS" and the month exactly as listed
              (measured 2026-10-17, #103).

  IDENTITY is the card plus the statement date. There is no document id.
  A requested statement is the card plus its month, dated the month's
  last day, under a title without a day, so its key never meets a
  regular statement's.

REQUESTED STATEMENTS (#103)
  Statements older than what the site lists online sit behind "Request
  Older Statements". The holder asks for them on Citi, and Citi then
  lists them as Requested Statements for a limited time. This app never
  submits that request (it is an account action, and the guard refuses
  "request" as a verb), it only takes what is already listed while it is
  listed. The requested call has twice answered 200 with no start date
  and an empty list while the page showed three, so an answer without
  archivedStatementRequestStartDate is a list NOT read, never "none
  requested".

NOT COVERED
  The Annual Account Summary is a web page, not a PDF, and is left
  alone. Tax forms are not offered for a credit card.

SAFETY (this is a credit card account that can move money):
  Strictly READ-ONLY. This module makes the four calls above and nothing
  else. It never activates a control that pays, transfers, requests a
  credit line change, adds an authorized user, locks or replaces a card,
  redeems points, or edits any setting, and it clicks nothing at all.
  FORBIDDEN_CONTROL_RE and SAFE_DOC_CONTROL_RE are kept so the repo-wide
  guard tests cover this app the same as every other, and --diagnose uses
  them to grade the page's controls.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

from paperpull_core import shared_folder
from paperpull_core import intake
from paperpull_core.controls import SETTINGS_CONTROL_RE, AUTH_CONTROL_RE

# Everything on its way into a diagnostic file goes through here. It
# lives in core because seventeen apps each had their own copy and
# they drifted into three different versions.
from paperpull_core.redact import redact, set_private_words  # noqa: F401
from paperpull_core.urls import is_safe_url as _host_allows
from paperpull_core.api_census import shape_of as _shape
from paperpull_core.dates import last_day as _last_day
from paperpull_core.dates import human_date as _human_date
from paperpull_core.dates import checked as _checked_date

log = logging.getLogger("citi_docs.site")

# Every host this app will read from. Anything else is refused.
ALLOWED_HOSTS = {"citi.com"}

BASE = "https://online.citi.com"
STATEMENTS_PATH = "/US/nga/accstatement"
STATEMENTS_URL = BASE + STATEMENTS_PATH
BILLING_URL = STATEMENTS_URL  # the orchestrator records it as each document's source
URLS = {
    "home": f"{BASE}/US/ag/dashboard/credit-card",
    "login": f"{BASE}/login",
    "documents": STATEMENTS_URL,
    "statements": STATEMENTS_URL,
}
API = f"{BASE}/gcgapi/prod/public/v1/v2/digital"
API_ACCOUNTS = f"{API}/accounts/statementsAndLetters/eligibleAccounts/retrieve"
API_LIST = f"{API}/card/accounts/statements/accountsAndStatements/retrieve"
API_PDF = f"{API}/card/accounts/statements/recent/retrieve"
# The statements the holder asked Citi for, listed for a limited time (#103).
API_REQUESTED = f"{API}/card/accounts/statements/archiveStatements/retrieve"
RECENT = "RECENT STATEMENTS"
ARCHIVED = "ARCHIVED STATEMENTS"
# The status of a requested statement that is ready to download, measured.
# Anything else is left alone.
REQUESTED_READY = "F"
# RawDoc.kind of a requested statement.
REQUESTED = "requested"
# The page's own app identity, sent by the page on every call. Not a
# credential and not personal, the same for every customer.
APP_HEADERS = {
    "accept": "application/json",
    "content-type": "application/json",
    "businesscode": "GCB",
    "countrycode": "US",
    "channelid": "CBOL",
    "client_id": "4a51fb19-a1a7-4247-bc7e-18aa56dd1c40",
}

LOGIN_URL_MARKERS = ["/login", "/signin", "/sign-in", "/auth", "/mfa",
                     "/verification", "/challenge", "/idp/", "/logout", "/timeout"]

# ---------------------------------------------------------------------------
# HARD SAFETY GUARD. Tuned for a credit card. This app clicks nothing, so
# the guard grades controls for --diagnose and satisfies the repo-wide
# guard tests.
# ---------------------------------------------------------------------------
FORBIDDEN_CONTROL_RE = re.compile(
    r"(transfer|zelle|\bwire\b|\bpay\b|payment|bill\s*pay|autopay|auto\s*pay|"
    r"deposit|withdraw|send\s+money|request\s+money|move\s+money|"
    r"\bapply\b|open\s+(an?\s+)?account|close\s+account|\bloan\b|\bborrow|"
    r"\bcard\b|\bcards\b|replace|activate|lock|unlock|\bpin\b|limit|"
    r"overdraft|alerts?\b|\bbudget|\bgoal|\brewards?\b|\boffers?\b|"
    r"enroll|unenroll|sign\s+up|paperless|delivery\s+preference|"
    r"enable|disable|change\b|edit\b|update\b|modify|manage\b|"
    r"set\s+up|delete|remove|cancel|dispute|"
    r"password|passcode|username|profile\b|settings|preferences|contact\s+info|\baddress\b|"
    r"confirm|submit|agree|accept|authorize|\bchat\b|contact\s+us|"
    r"beneficiar|nickname|order\s+checks|stop\s+payment|"
    r"redeem|\bpoints\b|thankyou|credit\s+line|balance\s+transfer|cash\s+advance|"
    r"authorized\s+user|add\s+user|flex\s+(loan|pay)|\bplan\s+it\b|"
    # Asking Citi for a statement is an account action, so "Request" as a
    # verb is refused in any wording, while "Requested", a statement already
    # made available to download, is not (#103).
    r"\brequest(?:s|ing)?\b|spend\s+summary)", re.I)

SAFE_DOC_CONTROL_RE = re.compile(
    r"(download|view|open|print|\bpdf\b|statement|document|\bletter\b|notice|"
    r"1099|1098|tax\s+(form|document)|history|"
    r"see\s+(more|all|older)|show\s+(more|all|older)|load\s+more)", re.I)

SECURITY_CHALLENGE_MARKERS = [
    "enter the code", "verification code", "6-digit", "two-factor",
    "two-step", "authenticator", "confirm your identity", "verify your identity",
    "we sent a code", "device approval", "approve this login", "unusual",
    "are you a robot", "captcha", "let's verify", "check your email",
    "check your phone", "your session has expired", "log back in",
    "access denied", "reference #",
]

RATE_LIMIT_MARKERS = [
    "too many requests", "rate limit", "try again later",
    "temporarily unavailable", "http error 429", "unusual traffic",
]

# What the statements page looks like, for --diagnose only.
FALLBACK = {
    "doc_row": "button.accordion2-button-wrapper",
    "doc_link": "button.statement-link",
    "download_control": "button.statement-link",
    "page_ready": "app-root, main, [role='main']",
    "next_page": "[aria-label*='Next' i]",
}

# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------
_MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July",
                "August", "September", "October", "November", "December"]
_MONTHS = {m[:3].lower(): i + 1 for i, m in enumerate(_MONTH_NAMES)}
DATE_PATTERNS = [
    (re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b"), "mdy_slash"),
    (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})(?!\d)"), "iso"),
    (re.compile(r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
                r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|"
                r"Dec(?:ember)?)\.?\s+(\d{1,2}),?\s+(\d{4})", re.I), "mdY"),
]
MONTH_YEAR_RE = re.compile(
    r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
    r"Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    r"\s+(\d{4})", re.I)
YEAR_RE = re.compile(r"\b(19|20)(\d{2})\b")


def _parse_date_from_page(text: str) -> Optional[str]:
    if not text:
        return None
    for pattern, kind in DATE_PATTERNS:
        m = pattern.search(text)
        if not m:
            continue
        try:
            if kind == "mdy_slash":
                return f"{int(m.group(3)):04d}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
            if kind == "iso":
                return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
            if kind == "mdY":
                return f"{int(m.group(3)):04d}-{_MONTHS[m.group(1)[:3].lower()]:02d}-{int(m.group(2)):02d}"
        except (KeyError, ValueError):
            continue
    return None


def parse_date(text):
    """The date this provider's page is showing, as YYYY-MM-DD.

    The reading is below, unchanged. This only refuses to believe a result
    that names a day which does not exist, because a reference number is
    shaped like a date and used to be taken for one."""
    return _checked_date(_parse_date_from_page(text), None)


def parse_period_date(text: str) -> Tuple[Optional[str], str]:
    text = text or ""
    exact = parse_date(text)
    if exact:
        return exact, ""
    m = MONTH_YEAR_RE.search(text)
    if m:
        month = _MONTHS[m.group(1)[:3].lower()]
        year = int(m.group(2))
        return f"{year:04d}-{month:02d}-{_last_day(year, month):02d}", m.group(0)
    m = YEAR_RE.search(text)
    if m:
        year = int(m.group(1) + m.group(2))
        return f"{year:04d}-12-31", str(year)
    return None, ""


def api_date(iso: str) -> str:
    """2026-09-15 -> 09/15/2026, the form the API takes."""
    y, m, d = iso.split("-")
    return f"{m}/{d}/{y}"


def requested_date(month: str) -> Optional[str]:
    """A requested statement's month as Citi lists it, "202010", as the
    month's last day, "2020-10-31". Citi gives no day for these, so the
    last day is what sorts and names them. None for anything else."""
    m = re.fullmatch(r"((?:19|20)\d{2})(\d{2})", str(month or "").strip())
    if not m:
        return None
    year, mon = int(m.group(1)), int(m.group(2))
    if not 1 <= mon <= 12:
        return None
    return f"{year:04d}-{mon:02d}-{_last_day(year, mon):02d}"


def month_title(month: str) -> str:
    """"202010" -> "October 2020", for a requested statement's title."""
    iso = requested_date(month) or ""
    if not iso:
        return ""
    return f"{_MONTH_NAMES[int(iso[5:7]) - 1]} {iso[:4]}"


_EXPIRY_TEXT_RE = re.compile(r"([A-Za-z]{3})[A-Za-z]*\.?,?\s*(\d{1,2})\b")


def expiry_date(raw, text: str = "") -> str:
    """The day a requested statement stops being listed, as YYYY-MM-DD, or
    "" when it cannot be told. Citi sends 8 digits, read as YYYYMMDD, which
    is not confirmed, so when the words beside it ("Dec, 04") name another
    month or day the digits are not believed, and with no day the statement
    stays until a later listing no longer has it."""
    m = re.fullmatch(r"(20\d{2})(\d{2})(\d{2})", str(raw or "").strip())
    if not m:
        return ""
    iso = _checked_date(f"{m.group(1)}-{m.group(2)}-{m.group(3)}", "")
    if not iso:
        return ""
    t = _EXPIRY_TEXT_RE.search(text or "")
    if t:
        mon = _MONTHS.get(t.group(1).lower())
        if mon != int(iso[5:7]) or int(t.group(2)) != int(iso[8:10]):
            return ""
    return iso

def account_label(nickname: str) -> str:
    """The card's name as it goes into a filename. "Costco Anywhere Visa
    Card by Citi - 1234" -> "Costco Anywhere Visa". The last four never
    reach a filename or a record, and the boilerplate tail is dropped."""
    s = (nickname or "").replace("®", "").replace(" ", " ")
    s = re.sub(r"\s*-\s*[x*]*\d{2,4}\s*$", "", s)
    s = re.sub(r"\s+(card\s+)?by\s+citi\s*$", "", s, flags=re.I)
    s = re.sub(r"\s+card\s*$", "", s, flags=re.I)
    s = re.sub(r"\s+", " ", s).strip()
    return s or "Card"


# ---------------------------------------------------------------------------
# Session / safety
# ---------------------------------------------------------------------------

def is_safe_url(url: str) -> bool:
    """True only for an https URL on one of this provider's own hosts.

    The check itself lives in the core, so all of them answer the same way.
    This app keeps the hosts, which is the part that really is its own."""
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


def on_statements_page(page) -> bool:
    url = page.url or ""
    return is_safe_url(url) and STATEMENTS_PATH in url and not looks_signed_out(page)


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
    hay = title + "\n" + body[:1500]
    for m in SECURITY_CHALLENGE_MARKERS:
        if m in hay:
            return f"Security challenge detected: '{m}'"
    for m in RATE_LIMIT_MARKERS:
        if m in hay:
            return f"Possible rate limiting detected: '{m}'"
    return None


def is_safe_control(name: str) -> bool:
    name = (name or "").strip()
    if not name:
        return False
    if FORBIDDEN_CONTROL_RE.search(name):
        return False
    if SETTINGS_CONTROL_RE.search(name) or AUTH_CONTROL_RE.search(name):
        return False
    return bool(SAFE_DOC_CONTROL_RE.search(name))


class SessionExpired(RuntimeError):
    """Citi answered with a sign-in page instead of the thing asked for."""


# ---------------------------------------------------------------------------
# The API, called from inside the signed-in page
# ---------------------------------------------------------------------------
_FETCH_JS = r"""async ([url, body, headers]) => {
  const r = await fetch(url, {method: "POST", headers, body: JSON.stringify(body), credentials: "include"});
  const ct = r.headers.get("content-type") || "";
  if (ct.includes("json")) {
    let j = null;
    try { j = await r.json(); } catch (e) { j = null; }
    return {status: r.status, ct, json: j};
  }
  const buf = await ppRead(r);
  let s = "";
  for (let i = 0; i < buf.length; i += 0x8000) s += String.fromCharCode.apply(null, buf.subarray(i, i + 0x8000));
  return {status: r.status, ct, b64: btoa(s)};
}"""


def _post(page, url: str, body: dict) -> dict:
    """One API call from inside the page. The answer as {status, ct, json}
    or {status, ct, b64} for bytes. A sign-in answer raises SessionExpired."""
    if not is_safe_url(url):
        raise ValueError("refusing to fetch off citi.com: %r" % redact(url))
    if not is_safe_url(page.url or "") or looks_signed_out(page):
        raise SessionExpired("the Citi tab is not on a signed-in citi.com page")
    r = intake.evaluate(page, _FETCH_JS, [url, body, dict(APP_HEADERS)])
    ct = (r.get("ct") or "").lower()
    if r.get("status") in (401, 403) or ct.startswith("text/html"):
        raise SessionExpired("Citi answered %s to %s, which means the session has ended"
                             % (r.get("status"), url.rsplit("/", 2)[-2]))
    return r


def goto_documents(page) -> bool:
    """Be on the Account Statements page. The API is same-origin, so any
    signed-in page would serve it, but the statements page is the one the
    calls were mapped from and the one a person would expect to see."""
    try:
        if on_statements_page(page):
            return True
        page.goto(STATEMENTS_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)
    except Exception as e:
        log.info("goto statements failed: %s", e)
    return on_statements_page(page)


def accounts(page) -> List[dict]:
    """Every card the signed-in person holds, as {id, label}."""
    r = _post(page, API_ACCOUNTS, {"transactionCode": "1079_statements"})
    cards = ((r.get("json") or {}).get("eligibleAccounts") or {}).get("cardAccounts") or []
    return [{"id": c["accountId"],
             "label": account_label(c.get("accountNickname") or c.get("productDesc") or "")}
            for c in cards if c.get("accountId")]


def statement_dates(listing: dict) -> List[str]:
    """The ISO date of every statement in one list answer, newest first."""
    out = []
    for year in (listing or {}).get("statementsByYear") or []:
        for m in year.get("statementsByMonth") or []:
            iso = parse_date(m.get("statementDate") or "")
            if iso:
                out.append(iso)
    return sorted(set(out), reverse=True)


def statements_for(page, account: dict) -> List[dict]:
    """Every statement the site lists online for one card, newest first."""
    r = _post(page, API_LIST, {"accountId": account["id"]})
    return [{"date": iso, "account": account["label"], "account_id": account["id"]}
            for iso in statement_dates(r.get("json") or {})]


def read_requested(answer: dict) -> Optional[List[dict]]:
    """Every entry of one requested-statements answer, as {month, date,
    status, expires}, or None when the answer is not a list that was read.

    Citi has answered 200 with no archivedStatementRequestStartDate and an
    empty list while its own page showed three requested statements, twice
    (measured). So only an answer that carries the start date is a list,
    and one with the start date and no entries is "none requested". An
    entry whose month is not six digits keeps month "" and is never taken.
    """
    j = (answer or {}).get("json")
    if (answer or {}).get("status") != 200 or not isinstance(j, dict):
        return None
    if not str(j.get("archivedStatementRequestStartDate") or "").strip():
        return None
    entries = j.get("archivedStatementsByMonth") or []
    if not isinstance(entries, list):
        return None
    out = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        month = str(e.get("statementDate") or "").strip()
        date = requested_date(month)
        out.append({"month": month if date else "", "date": date or "",
                    "status": str(e.get("statusIndicator") or "").strip().upper(),
                    "expires": expiry_date(e.get("documentExpiryDate"),
                                           str(e.get("documentExpirationDateText") or ""))})
    return out


def requested_for(page, account: dict) -> Optional[List[dict]]:
    """The requested statements Citi lists for one card (read_requested),
    or None when the list was not read. Only a sign-in answer stops the
    run, since the regular statements are already in hand and a list not
    read is said as one (Listing.unread)."""
    try:
        r = _post(page, API_REQUESTED, {"accountId": account["id"]})
    except SessionExpired:
        raise
    except Exception as e:
        log.info("the requested statements list could not be read: %s", type(e).__name__)
        return None
    return read_requested(r)


@dataclass
class RawDoc:
    title: str
    account: str = ""
    date_text: str = ""
    href: str = ""
    text: str = ""
    row_index: int = -1
    kind: str = "statement"
    # A requested statement's month exactly as Citi listed it, "202010",
    # which the download sends back, and the day it stops being listed.
    archived_month: str = ""
    expires: str = ""
    period: str = ""


@dataclass
class Listing:
    """What one reading of every card's lists found. `unread` and `read`
    are the labels of the cards whose requested list was not and was read,
    `empty` those of the read ones whose list held nothing, and
    `requested` counts what the requested lists held, by fixed words."""
    docs: List[RawDoc] = field(default_factory=list)
    unread: List[str] = field(default_factory=list)
    read: List[str] = field(default_factory=list)
    empty: List[str] = field(default_factory=list)
    requested: dict = field(default_factory=dict)


def regular_list_read(answer: dict) -> bool:
    """Whether a list answer is one that was read, a 200 JSON body that
    carries statementsByYear. An odd answer reads as no statements, which
    must never let a requested statement of a month the regular list really
    has through as one it lacks."""
    j = (answer or {}).get("json")
    return ((answer or {}).get("status") == 200 and isinstance(j, dict)
            and "statementsByYear" in j)


def collect_listing(page) -> Listing:
    """Every statement across every card, from the API, then each card's
    requested statements. `href` carries the card's opaque account id,
    which the download needs. It is a uuid the site made up, not the card
    number.

    A requested statement is taken only when it is ready (REQUESTED_READY)
    and its month is not one the card's regular list already has, so
    nothing downloads twice. Its list is asked for only after the card's
    regular list was read, since the regular months are what that check
    stands on. Two cards of one name share the name their records are
    keyed by, and a requested statement has only its month to tell it by,
    so such cards' requested statements are left, counted. A card the
    regular list says is not eligible for older statements is not asked."""
    out = Listing(requested={"listed": 0, "ready": 0, "not ready": 0,
                             "on the regular list": 0, "no month": 0,
                             "cards sharing a name": 0, "cards not eligible": 0})
    counts = out.requested
    cards = accounts(page)
    names = [c["label"] for c in cards]
    for acct in cards:
        r = _post(page, API_LIST, {"accountId": acct["id"]})
        j = r.get("json") if isinstance(r.get("json"), dict) else {}
        months = set()
        for iso in statement_dates(j):
            disp = _human_date(iso)
            months.add(iso[:7])
            out.docs.append(RawDoc(title=f"Monthly Statement - {disp}", account=acct["label"],
                                   date_text=iso, href=acct["id"],
                                   text=f"Citi {acct['label']} statement {disp}"))
        if names.count(acct["label"]) > 1:
            counts["cards sharing a name"] += 1
            continue
        if not regular_list_read(r):
            out.unread.append(acct["label"])
            continue
        if j.get("archivedStatementsEligibleFlag") is False:
            counts["cards not eligible"] += 1
            continue
        entries = requested_for(page, acct)
        if entries is None:
            out.unread.append(acct["label"])
            continue
        out.read.append(acct["label"])
        if not entries:
            out.empty.append(acct["label"])
        for e in entries:
            counts["listed"] += 1
            if e["status"] != REQUESTED_READY:
                counts["not ready"] += 1
                continue
            if not e["month"]:
                counts["no month"] += 1
                continue
            if e["date"][:7] in months:
                counts["on the regular list"] += 1
                continue
            counts["ready"] += 1
            disp = month_title(e["month"])
            out.docs.append(RawDoc(title=f"Monthly Statement - {disp}", account=acct["label"],
                                   date_text=e["date"], href=acct["id"],
                                   text=f"Citi {acct['label']} requested statement {disp}",
                                   kind=REQUESTED, archived_month=e["month"],
                                   expires=e["expires"], period=disp))
    return out


def collect_download_docs(page) -> List[RawDoc]:
    """Every statement across every card, requested ones included
    (collect_listing)."""
    return collect_listing(page).docs


def download_bill(page, dl_dir, iso_date: str, out_path, account_id: str = "",
                  account: str = "", archived_month: str = "") -> bool:
    """Fetch one statement's PDF from inside the page and write it. A record
    that carries no account id (an index written by an older copy, say) is
    matched to a card by its label. `dl_dir` is unused, kept for the
    orchestrator.

    A requested statement (#103) is asked for by its month exactly as Citi
    listed it, `archived_month`, with requestType ARCHIVED STATEMENTS, and
    only when that month is the month of the record's date, so a record
    can never save one month's statement under another's."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if archived_month:
        if (requested_date(archived_month) or "")[:7] != (iso_date or "")[:7]:
            log.info("a requested statement's month does not match its record, not asked for")
            return False
        body = {"statementDate": archived_month, "requestType": ARCHIVED}
    else:
        body = {"statementDate": api_date(iso_date), "requestType": RECENT}
    if not goto_documents(page):
        return False
    if not account_id:
        for acct in accounts(page):
            if acct["label"] == account:
                account_id = acct["id"]
                break
    if not account_id:
        log.info("no account id for %s %s", account, iso_date)
        return False
    r = _post(page, API_PDF, dict({"accountId": account_id}, **body))
    # The PDF comes back as the answer's own bytes, application/pdf, for a
    # recent statement and a requested one alike (measured). Anything else,
    # a JSON answer included, is refused, and so are bytes that are not a
    # PDF.
    if "pdf" not in (r.get("ct") or "") or not r.get("b64"):
        if archived_month:
            log.info("no PDF for a requested statement: status %s, %s",
                     r.get("status"), r.get("ct"))
        else:
            log.info("no PDF for %s %s: status %s, %s", account, iso_date, r.get("status"), r.get("ct"))
        return False
    try:
        pdf = intake.decode(r["b64"], validate=True)
    except (ValueError, TypeError):
        return False
    if pdf[:5] != b"%PDF-":
        return False
    shared_folder.write_bytes(out_path, pdf)
    return True


# ---------------------------------------------------------------------------
# Diagnose. What the API lists, as counts and shapes, and the page's own
# controls with the guard's verdict on each. No screenshot, digits masked,
# nothing clicked and nothing downloaded.
# ---------------------------------------------------------------------------

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
    for role in ("link", "button", "tab", "combobox"):
        try:
            loc = page.get_by_role(role)
            for i in range(min(loc.count(), 80)):
                el = loc.nth(i)
                try:
                    text = (el.inner_text(timeout=300) or "").strip() or \
                        (el.get_attribute("aria-label") or "").strip()
                except Exception:
                    text = ""
                if text:
                    controls.append({"role": role, "text": redact(text)[:60],
                                     "safe": is_safe_control(text)})
        except Exception:
            pass
    out["controls"] = controls
    return out


def survey(page, dwell_ms: int = 2000, max_follow: int = 0) -> dict:
    """The statements page and what the API lists for each card, without
    downloading anything. Nothing is clicked."""
    report = {"page": _page_summary(page), "accounts": [], "api": {}}
    try:
        cards = accounts(page)
        for c in cards:
            label = redact(c["label"])
            report["accounts"].append(label)
            r = _post(page, API_LIST, {"accountId": c["id"]})
            j = r.get("json") or {}
            requested = requested_for(page, c)
            report["api"][label] = {
                "years": [(y.get("displayYearTitle"), len(y.get("statementsByMonth") or []))
                          for y in j.get("statementsByYear") or []],
                "archived_eligible": j.get("archivedStatementsEligibleFlag"),
                "shape": _shape(j),
                # Counts only, never a month or an expiry (#103).
                "requested_read": requested is not None,
                "requested_listed": len(requested or []),
                "requested_ready": sum(1 for e in requested or []
                                       if e["status"] == REQUESTED_READY)}
    except Exception as e:
        report["error"] = str(e)[:200]
    return report


def collect_documents(page) -> List[RawDoc]:
    """Used only by --diagnose. The same list discovery reads, minus the
    account id, which is opaque but still names an account and has no
    business in a file that gets attached to an issue."""
    try:
        docs = collect_download_docs(page)
    except Exception:
        return []
    for d in docs:
        d.href = ""
    return docs


def expand_all(page) -> None:
    """Nothing to expand. The list comes from the API."""


def scroll_full_page(page, rounds: int = 0, delay_ms: int = 0) -> None:
    """Nothing to scroll. The list comes from the API."""
