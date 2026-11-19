"""ALL Vanguard selectors, URLs, and page behavior live here.

When Vanguard changes its site, repair this file only.

SAFETY (this is a brokerage):
  This module is strictly READ-ONLY. It navigates to the statements area,
  reads the list of statements, and downloads the PDFs Vanguard already
  generated. It must NEVER activate any control that buys, sells, trades,
  exchanges, rebalances, moves money, changes holdings or changes any
  setting. FORBIDDEN_CONTROL_RE is the guard; every click must ALSO look
  like a document action (SAFE_DOC_CONTROL_RE) before it may be clicked.
  There is no code here that submits a form or confirms a dialog.

  Every press goes through paperpull_core.pressing, never forced, so a
  control is pressed only when it is the thing on top in the middle of the
  window, and otherwise nothing is pressed and the run stops.

Site truth (verified live 2026-09-28 against the signed-in pages):

  - Sign-in lives at https://logon.vanguard.com/logon?site=pi; the portal
    is investor.vanguard.com. Opening investor.vanguard.com/myaccount/
    documents lands on a shell page that spawns the real statements app.
  - The statements app is its own host, statements.web.vanguard.com, with
    sibling apps (confirmations.web..., historical-documents.web...,
    transactions.web..., order-status.web...) reachable from its nav.
  - The list is ONE table (Date | Account | View | Download), every account
    in one list, driven by a native year <select> (2020..2026 observed).
  - Data comes from a JSON API the page itself calls:
      personal1.vanguard.com/usa/api/lah-statements-consumer/
        statements/consumer?year=YYYY
    returning {"statements":[{accountId, accountNumber,
    productAccountData, statementDescription, endDate, processDate,
    frequencyType, statementType, statementId, ...}]}.
  - Each row carries two c11n-icon buttons with NBSP-bearing aria-labels
    ("Download&nbsp;a&nbsp;pdf&nbsp;statement...") — match them by the
    stable title attributes instead: title="View PDF" and
    title="Pdf download icon".
  - Clicking the download icon fires a REAL browser download event
    (verified: suggested filename "2026-08 VG Statement Cash Plus Account
    x1234.pdf", 311 KB, %PDF-). The cleanest capture path in the repo.
"""
# Site layer verified working against the live site: 2026-09-28
from __future__ import annotations

import json
import logging
import re
import sys
from dataclasses import dataclass
from datetime import date as calendar_date
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlencode, urlsplit

from paperpull_core import delivery, identity, intake, pdf_reader, pressing
from paperpull_core.words import words_for as _words_for
from paperpull_core.urls import is_safe_url as _host_allows, join as _join_link
from paperpull_core.dates import checked as _checked_date
from paperpull_core.capture import set_download_dir as _set_download_dir
from paperpull_core.capture import growing as _growing
from paperpull_core.capture import snapshot as _snapshot
from paperpull_core.capture import take_download as _take_download
from paperpull_core.capture import clear_copies as _clear_copies
from paperpull_core.controls import control_identity

log = logging.getLogger("vanguard_docs.site")


def _words():
    """This app's own words for paperpull_core.words, from what its source
    calls it, for saying what covered a control."""
    return _words_for("Vanguard", sys.modules[__name__])


WORKPLACE_HOST = "ownyourfuture.vanguard.com"
WORKPLACE_MANAGE = "/main/manage"
WORKPLACE_STATEMENTS = "/main/manage/statements"
WORKPLACE_STATEMENTS_URL = f"https://{WORKPLACE_HOST}{WORKPLACE_STATEMENTS}"
WORKPLACE_STATEMENT = "Workplace Statement"
WORKPLACE_SERVICE = "https://retirementplans.vanguard.com"
WORKPLACE_LIST = WORKPLACE_SERVICE + "/VGApp/pe/employee/statement"
WORKPLACE_PDF_PATH = "/VGApp/pe/employee/openpdf"

ALLOWED_HOSTS = {'investor.vanguard.com', 'logon.vanguard.com',
                 'statements.web.vanguard.com', 'personal1.vanguard.com',
                 'vanguard.com', 'secure.vanguard.com', WORKPLACE_HOST}


def is_safe_url(url: str) -> bool:
    return _host_allows(url, ALLOWED_HOSTS, subdomains=False)


BASE = "https://investor.vanguard.com"
DOCUMENTS_SHELL = f"{BASE}/myaccount/documents"
URLS = {
    "home": f"{BASE}/",
    "login": "https://logon.vanguard.com/logon?site=pi",
    "documents": "https://statements.web.vanguard.com/",
    "shell": DOCUMENTS_SHELL,
}
DOCUMENT_URL_CANDIDATES = [URLS["documents"], DOCUMENTS_SHELL]

# The JSON API the statements app itself calls while you use it. Captured,
# never called blind (the page issues the calls; we listen).
STATEMENTS_API_RE = re.compile(
    r"personal1\.vanguard\.com/usa/api/lah-statements-consumer"
    r"/statements/consumer", re.I)


LOGIN_URL_MARKERS = ["/logon", "/login", "/signin", "/sign-in", "/mfa",
                     "sessiontimeout=", "logon.vanguard.com"]

SECURITY_CHALLENGE_MARKERS = [
    "security challenge", "verify your identity", "we need to verify",
    "enter the code", "one-time passcode", "confirm your identity",
]
RATE_LIMIT_MARKERS = [
    re.compile(r"too many (attempts|requests|sign.?in)", re.I),
    re.compile(r"access (has been |is )?temporarily (locked|unavailable)", re.I),
]

# ---------------------------------------------------------------- guards

FORBIDDEN_CONTROL_RE = re.compile(

    r"(\btrade\b(?!\s+confirm)|\btrading\b|place\s+order|preview\s+order|"
    r"\border\b(?!s?\s+(status|history|details))|\bbuy\b|\bsell\b|short\s+position|"
    r"\bexercise\b|roll\s+over|rebalance|auto\s?invest|"
    r"contribution(?!.*\bstatement\b)|distribution\s+request|"
    r"move\s+money|transfer\s+(money|funds|assets)|withdraw|deposit\s+check|"
    r"wire\b|ach\b|pay\s+bill|payment\s+method|"
    r"open\s+(a\s+)?new\s+account|close\s+account|add\s+(a\s+)?beneficiar(y|ies)|"
    r"update\s+(contact|email|phone|address)|change\s+(password|user ?name|address)|"
    r"opt\s+out|paperless\s+setting|notification\s+setting|"
    r"removal|remove\s+(the\s+)?(document|paperless)|delete\s+(a\s+)?document|"
    r"\bchang(e|es|ed|ing)\b|\bedit(s|ed|ing)?\b|\bupdat(e|es|ed|ing)\b)",
    re.I,
)

# The core's tested versions, imported the way Schwab/USAA/Fidelity/ETRADE
# do it — a provider-local rewrite is measurably weaker (the local AUTH
# pattern missed "Logon", this provider's own sign-in flow) and bypasses
# the guard lessons the core patterns encode.
from paperpull_core.controls import (AUTH_CONTROL_RE, SETTINGS_CONTROL_RE,
                                      is_forbidden_context as _core_forbidden)
from paperpull_core.controls import escape_for_locator
from paperpull_core.characters import whole_json

SAFE_DOC_CONTROL_RE = re.compile(
    r"(download|save|print|pdf|statement|document|"
    r"\bview\b|\bopen\b|historical\s+documents|tax\s+forms|"
    r"confirmations?\b(?!.*\btrade\b)|"
    r"year\b|account\b|show\s+more|sort\s+by)", re.I)

# is_money_control comes from the core (MONEY_CONTROL_RE + AUTH + optional
# provider patterns) — the core version encodes the sign-in-form lesson.


# ---------------------------------------------------------------- session

def looks_signed_out(page) -> bool:
    url = (page.url or "").lower()
    if any(m in url for m in LOGIN_URL_MARKERS):
        if "logon.vanguard.com" in url and "/logon" in url:
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
        body = page.locator("body").inner_text(timeout=4000).lower()
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


def dismiss_timeout(page) -> None:
    for pattern in (r"continue session", r"i'?m still here",
                    r"stay (signed|logged) in", r"keep me (signed|logged) in",
                    r"extend (my )?session", r"still (there|here)\?"):
        try:
            c = page.get_by_role("button", name=re.compile(pattern, re.I))
            if c.count() and c.first.is_visible():
                pressing.click(page, c.first, css=pressing.BUTTONS,
                               what="the button that keeps the session going",
                               words=_words(), step="continue the session")
                page.wait_for_timeout(1000)
                return
        except Exception:
            pass


# ---------------------------------------------------------------- dates

def parse_date(text: str) -> str:
    """Vanguard prints MM/DD/YYYY in rows and YYYY-MM-DD in the API.
    The negative lookaheads refuse a digit after the day: an account
    number is not a date ("2026-03-045" must read as nothing, not
    2026-03-04), while a timestamp still reads as its date."""
    t = (text or "").strip()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})(?!\d)", t)
    if m:
        return _checked_date(f"{m.group(1)}-{m.group(2)}-{m.group(3)}") or ""
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})(?!\d)", t)
    if m:
        return _checked_date(
            f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}") or ""
    return ""


# ---------------------------------------------------------------- navigation

def _brokerage_statements_portal(page) -> bool:
    u = urlsplit(page.url or "")
    return (u.scheme, u.netloc) == ("https", "statements.web.vanguard.com")


def on_documents_page(page) -> bool:
    try:
        if is_workplace_page(page):
            return bool(workplace_plan(page))
        if not _brokerage_statements_portal(page):
            return False
        # The table is the statements area's structural marker; the page
        # shell renders around it. A year/empty view still shows the table
        # header (the Chase empty-year lesson: never gate on row count).
        return page.locator("table").count() > 0
    except Exception:
        return False


def goto_documents(page) -> bool:
    """Reach the statements app. Direct navigation to the app host works
    when the session cookie carries; the portal shell is the fallback (it
    spawns the app). Verified live: both land on the statements table."""
    if is_workplace_page(page):
        return bool(workplace_plan(page))
    for url in DOCUMENT_URL_CANDIDATES:
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(4000)
            dismiss_timeout(page)
            if looks_signed_out(page):
                return False
            if on_documents_page(page):
                return True
        except Exception as e:
            log.info("documents URL %s failed: %s", url, e)
    return False


def ensure_statements(page) -> bool:
    if on_documents_page(page):
        return True
    return goto_documents(page)


# ---------------------------------------------------------------- collection

class ListStopped(RuntimeError):
    """The page did not return a readable statement list."""


def is_workplace_page(page) -> bool:
    u = urlsplit(page.url or "")
    return u.scheme == "https" and u.netloc == WORKPLACE_HOST


def workplace_plan(page) -> str:
    """Stay with the plan selected in this tab, including after the Statements SPA route."""
    if not is_workplace_page(page):
        return ""
    u = urlsplit(page.url)
    if u.path.rstrip("/") == WORKPLACE_STATEMENTS and not u.query:
        try:
            previous = page.evaluate(
                "() => window.navigation?.entries()[window.navigation.currentEntry.index - 1]?.url || ''")
        except Exception:
            # A tab that moved while it was read has no plan this run can
            # be sure of, and its list is then one that did not answer.
            return ""
        u = urlsplit(previous if isinstance(previous, str) else "")
        if u.path.rstrip("/") != WORKPLACE_MANAGE:
            return ""
    if (u.scheme, u.netloc) != ("https", WORKPLACE_HOST):
        return ""
    if u.path.rstrip("/") not in (WORKPLACE_MANAGE, WORKPLACE_STATEMENTS):
        return ""
    plans = parse_qs(u.query).get("planId", [])
    return plans[0] if len(plans) == 1 and re.fullmatch(r"[0-9]{4,16}", plans[0]) else ""


@dataclass(frozen=True)
class WorkplaceRow:
    start: str
    end: str
    pdf_url: str

    @property
    def document_id(self) -> str:
        return f"workplace-{self.start}-{self.end}"


def _workplace_pdf_url(value) -> str:
    if not isinstance(value, str):
        return ""
    u = urlsplit(_join_link(WORKPLACE_SERVICE, value))
    if (u.scheme, u.netloc, u.path, u.fragment) != (
            "https", "retirementplans.vanguard.com", WORKPLACE_PDF_PATH, ""):
        return ""
    params = parse_qs(u.query, keep_blank_values=True)
    indexes = params.get("index", [])
    if (set(params) != {"documentType", "index"} or params["documentType"] != ["statement"]
            or len(indexes) != 1 or not re.fullmatch(r"[0-9]{1,4}", indexes[0])):
        return ""
    return WORKPLACE_SERVICE + WORKPLACE_PDF_PATH + "?" + urlencode(
        {"documentType": "statement", "index": indexes[0]})


def _workplace_rows(page, plan: str) -> list[WorkplaceRow]:
    """Read the document-list route used by the workplace Statements page."""
    if not plan or workplace_plan(page) != plan:
        raise ListStopped("Open Statements for the selected Vanguard workplace plan")
    response = None
    try:
        response = page.context.request.get(
            WORKPLACE_LIST, params={"SelectedPlanId": plan}, max_redirects=0,
            timeout=20000, headers={"Accept": "application/json"})
        payload = whole_json(json.loads(intake.text_of(response))) if response.status == 200 else {}
        listing = payload["statementData"]
        if str(payload["statementPlan"]["planId"]) != plan or not isinstance(listing, list):
            raise ValueError("workplace plan or statement list did not match")
        rows = []
        seen = set()
        for entry in listing:
            start = calendar_date.fromisoformat(entry["startDate"]).isoformat()
            end = calendar_date.fromisoformat(entry["endDate"]).isoformat()
            pdf_url = _workplace_pdf_url(entry["statementViewPDFURL"])
            row = WorkplaceRow(start, end, pdf_url)
            if not pdf_url or end < start or row.document_id in seen:
                raise ValueError("unrecognized or ambiguous workplace statement")
            seen.add(row.document_id)
            rows.append(row)
        return rows
    except Exception:
        raise ListStopped("Vanguard did not return a readable workplace statement list") from None
    finally:
        if response is not None:
            response.dispose()


def _collect_workplace(page, years, keep) -> List[dict]:
    plan = workplace_plan(page)
    docs = []
    for row in _workplace_rows(page, plan):
        year = row.end[:4]
        if (years and year not in years) or (keep is not None and not keep(year)):
            continue
        docs.append({"accountId": plan, "accountNumber": plan,
                     "statementDescription": f"Vanguard Workplace Plan {plan}",
                     "endDate": row.end, "statementId": row.document_id, "workplace": True})
    return docs


def _year_select(page):
    """The year picker as a native <select> (verified). The chooser is
    identity-checked, fail closed: only a select whose options are all
    4-digit years AND that is not a money control may be returned — a
    redesign that turns the picker into a payment widget must be
    refused here, at the point of choice, not only where it is set."""
    try:
        for s in page.locator("select").all():
            label = (s.get_attribute("aria-label") or ""
                    + " " + (s.get_attribute("id") or "")).lower()
            if "year" in label and _looks_like_year_options(s):
                if not is_money_control(control_identity(s)):
                    return s
                log.warning("refusing year select %r (money control)",
                            control_identity(s)[:120])
    except Exception:
        pass
    return None


def _looks_like_year_options(s) -> bool:
    """Structural identity: every leading option is a bare 4-digit year."""
    try:
        opts = s.locator("option").all_inner_texts()
        return bool(opts) and all(
            re.fullmatch(r"\d{4}", o.strip()) for o in opts[:3])
    except Exception:
        return False


def year_options(page) -> List[str]:
    s = _year_select(page)
    if s is None:
        return []
    try:
        return [o.strip() for o in s.locator("option").all_inner_texts()
                if re.fullmatch(r"\d{4}", o.strip())]
    except Exception:
        return []


def _shown_year(page) -> str:
    """The year the picker shows now, or "" when it cannot be read."""
    s = _year_select(page)
    if s is None:
        return ""
    try:
        shown = s.evaluate("el => (el.options[el.selectedIndex] || {}).text || ''")
    except Exception:
        return ""
    shown = shown.strip() if isinstance(shown, str) else ""
    return shown if re.fullmatch(r"\d{4}", shown) else ""


def select_year(page, year: str) -> bool:
    s = _year_select(page)
    if s is None:
        return False
    # Identity check, fail closed: a year <select> whose options are all
    # 4-digit years is structurally a period filter, but a redesign that
    # turns it into a payment widget must be refused, not driven.
    if is_money_control(control_identity(s)):
        log.warning("REFUSED to set the year picker (money control): %s",
                    control_identity(s)[:120])
        return False
    try:
        s.select_option(label=year, timeout=8000)
        page.wait_for_timeout(2500)
        return True
    except Exception as e:
        log.info("year %s not selectable: %s", year, e)
        return False


def collect_statements_json(page, years: Optional[List[str]] = None,
                            keep=None) -> List[dict]:
    """Capture the page's own statements API calls while walking the year
    select — the same response-capture pattern as the USAA collector. The
    page issues every request; we never call the API blind, so the session
    cookies never leave the browser. Returns the raw statement dicts.

    keep, when given, says which picker options a scoped run wants; years
    it refuses are not selected at all, which is the round trips a scoped
    run should not spend (adding-a-provider.md Tips, the Chase pattern)."""
    if is_workplace_page(page):
        return _collect_workplace(page, years, keep)
    if not _brokerage_statements_portal(page):
        return []
    batches: List[dict] = []
    answered_years: set[str] = set()
    # An answer naming no year that came while the page loaded, before any
    # year was chosen. It is the year the picker shows, which choosing again
    # may not ask for, so it counts for that year once the picker is read,
    # before the walk. One that comes during the walk counts for no year.
    unnamed_on_load = [False]

    def on_resp(r):
        try:
            if not STATEMENTS_API_RE.search(r.url or "") or not r.ok:
                return
            data = whole_json(json.loads(intake.text_of(r)))
            rows = data.get("statements") if isinstance(data, dict) else None
            if isinstance(rows, list) and all(isinstance(row, dict) for row in rows):
                batches.append(data)
                requested = parse_qs(urlsplit(r.url).query).get("year", [])
                if len(requested) == 1:
                    answered_years.add(requested[0])
                elif not requested:
                    unnamed_on_load[0] = True
        except Exception:
            pass

    page.on("response", on_resp)
    try:
        # Force the app to replay its calls (a parked page fires nothing —
        # the USAA already-loaded-page lesson).
        try:
            page.reload(wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            log.info("reload during capture failed (continuing): %s", e)
        page.wait_for_timeout(5000)
        if unnamed_on_load[0]:
            shown = _shown_year(page)
            if shown:
                answered_years.add(shown)

        walk = years or year_options(page)
        if keep is not None:
            walk = [y for y in walk if keep(y)]
        for yr in walk:
            if yr in answered_years:
                continue
            if not select_year(page, yr):
                continue
            page.wait_for_timeout(1500)
        if set(walk) - answered_years:
            # The last answer can arrive after the picker has rendered.
            page.wait_for_timeout(8000)
    finally:
        try:
            page.remove_listener("response", on_resp)
        except Exception:
            pass

    if not batches:
        raise ListStopped("Vanguard did not return a readable statements list")
    if set(walk) - answered_years:
        raise ListStopped("Vanguard did not return a readable list for every requested year")

    by_id: Dict[str, dict] = {}
    for b in batches:
        for s in b.get("statements", []):
            sid = s.get("statementId") or f"{s.get('accountId')}-{s.get('endDate')}"
            if sid and sid not in by_id:
                by_id[sid] = s
    return list(by_id.values())


def account_label_from_statement(s: dict) -> str:
    """'Example Holder — Cash Plus Account — 1234567' from the API's own
    description, or built from accountNumber when absent."""
    desc = (s.get("statementDescription") or "").strip()
    if desc:
        return desc
    num = s.get("accountNumber") or ""
    return f"Vanguard Account {num}" if num else "Vanguard Account"


def account_id_from_display(display: str) -> str:
    m = re.search(r"(\d{4,})(?!.*\d{4,})", display or "")
    return m.group(1) if m else ""


def classify_document(doc: dict) -> Tuple[str, str, str, str]:
    """Engine contract: (category, date, period, title) from a captured
    statement dict. The diagnose path unpacks exactly these four."""
    label = account_label_from_statement(doc)
    end = doc.get("endDate") or doc.get("processDate") or ""
    date_iso = parse_date(end)
    period = end[:7] if end else ""
    kind = "Account Statement"
    return "Statement", date_iso, period, f"{kind} - {label}"


def list_accounts(page) -> List[dict]:
    """Accounts from the captured statements (each carries accountNumber).
    Engine contract: each dict has account_id, label, charitable,
    account_type, closed. Vanguard's retail accounts are neither charitable
    nor closed-shaped, so those are constants; account_id is the API's
    accountId, label the human description ending in the account number."""
    stmts = collect_statements_json(page)
    seen: Dict[str, dict] = {}
    for s in stmts:
        num = s.get("accountNumber") or ""
        if num and num not in seen:
            seen[num] = {
                "account_id": s.get("accountId", ""),
                "account_number": num,
                "label": account_label_from_statement(s),
                "charitable": False,
                "account_type": (s.get("productAccountData") or "VBS").split("|")[-1],
                "closed": False,
            }
    return list(seen.values())


def list_documents(page, accounts: Optional[List[dict]] = None,
                  keep=None) -> List[dict]:
    """Every statement currently known to the app, shaped for the engine:
    {account, account_id, last4, date, period, title, category,
    statement_id, doc_type, occurrence, ambiguous}."""
    if not (is_workplace_page(page) or _brokerage_statements_portal(page)):
        raise ListStopped("Vanguard statements page is no longer open")
    stmts = collect_statements_json(page, keep=keep)
    out: List[dict] = []
    for s in stmts:
        cat, date_iso, period, title = classify_document(s)
        num = s.get("accountNumber") or ""
        doc = {
            "account": account_label_from_statement(s),
            "account_id": s.get("accountId", ""),
            "last4": num[-4:] if num else "",
            "date": date_iso,
            "period": period,
            "title": title,
            "category": cat,
            # Handed over as statement_id, which the record does not read,
            # and not as document_id, the id a record keeps and a file's
            # name can carry. Whether it stays the same from one listing to
            # the next, and ends differently for each statement, has not been
            # seen (tests/test_statement_id.py).
            "statement_id": s.get("statementId", ""),
            "statement_number": s.get("statementNumber", ""),
            "doc_type": "Statement",
            "occurrence": 0,
            "ambiguous": False,
        }
        if s.get("workplace"):
            # Unlike the brokerage API's opaque ID, this identity comes
            # from the period and the plan in the archived record.
            doc.update(doc_type=WORKPLACE_STATEMENT, document_id=s["statementId"])
        out.append(doc)
    return out


def collect_documents(page, keep=None) -> List[dict]:
    return list_documents(page, keep=keep)


def is_safe_control(name: str) -> bool:
    name = (name or "").strip()
    if not name:
        return False
    if (FORBIDDEN_CONTROL_RE.search(name) or SETTINGS_CONTROL_RE.search(name)
            or AUTH_CONTROL_RE.search(name)):
        return False
    return bool(SAFE_DOC_CONTROL_RE.search(name))


def is_money_control(identity: str) -> bool:
    """The core's check: money or auth context, the provider's own
    blocklist, and empty identity — all fail closed."""
    return _core_forbidden(identity, FORBIDDEN_CONTROL_RE)


# ---------------------------------------------------------------- download

_ROW_JS = r"""(needle) => {
  // Find the table row whose text contains the account number + date,
  // then return its download icon's element index for a real click.
  const rows = [...document.querySelectorAll('table tr, [role=row]')];
  for (const row of rows) {
    const t = (row.innerText || '').replace(/\s+/g, ' ');
    if (t.includes(needle.account) && t.includes(needle.dateText)) {
      for (const el of row.querySelectorAll('[title], [role=button]')) {
        const title = el.getAttribute('title') || '';
        if (/pdf download/i.test(title) && el.getClientRects().length) return true;     // drawn, not just in the page's text
      }
    }
  }
  return false;
}"""


# The statements table shows the first rows of a year and keeps the older ones
# behind a "Show More" control. Pressed only when the row asked for is not
# there, one press at a time, each judged by the guard like every other control.
SHOW_MORE_RE = re.compile(r"^\s*show\s+more\s*$", re.I)
SHOW_MORE_PRESSES = 30
# How long one press of Show More is given to draw its rows. A press that
# draws none in that time leaves nothing more to show.
SHOW_MORE_WAIT_MS = 6000

_DRAWN_ROWS_JS = r"""() => [...document.querySelectorAll('table tr, [role=row]')]
  .filter(r => r.getClientRects().length).length"""


def show_more(page) -> bool:
    """Press one visible "Show More" control, if the guard allows its label.
    True when it was pressed and the table then drew more rows. A control
    that stays on the page once every row is shown is pressed once more and
    no further, where it was pressed thirty times for a row not there."""
    for role in ("button", "link"):
        try:
            loc = page.get_by_role(role, name=SHOW_MORE_RE)
            if loc.count() == 0 or not loc.first.is_visible():
                continue
            label = loc.first.inner_text(timeout=1000) or ""
            if not is_safe_control(label):
                continue
            # A list shown in full can leave its control on the page, turned
            # off. Pressing it would not go through and would stop the run,
            # where a row not there leaves only that statement for review.
            if not loc.first.is_enabled(timeout=1000):
                return False
            before = page.evaluate(_DRAWN_ROWS_JS)
            pressing.click(page, loc.first, css="button, a, [role=button], [role=link]",
                           what="the control that shows more statements", words=_words(),
                           step="show more of the list")
        except pressing.Stop:
            raise
        except Exception:
            continue
        return _drew_more(page, before)
    return False


def _drew_more(page, before: int) -> bool:
    """Whether the table drew more rows than `before` after a press, waiting
    for them as long as SHOW_MORE_WAIT_MS."""
    waited = 0
    while waited < SHOW_MORE_WAIT_MS:
        page.wait_for_timeout(250)
        waited += 250
        try:
            if page.evaluate(_DRAWN_ROWS_JS) > before:
                page.wait_for_timeout(400)          # the rest of the batch
                return True
        except Exception:
            return False
    return False


def row_is_shown(page, needle: dict) -> bool:
    """Whether the row for this (account, date) is on the page, pressing
    "Show More" for older rows until it is, or nothing is left to show."""
    if page.evaluate(_ROW_JS, needle):
        return True
    for _ in range(SHOW_MORE_PRESSES):
        if not show_more(page):
            return False
        if page.evaluate(_ROW_JS, needle):
            return True
    return False


def _mdy(iso: str) -> str:
    """'2026-08-31' -> '08/31/2026' (the table's own date format)."""
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", iso or "")
    if not m:
        return iso or ""
    return f"{m.group(2)}/{m.group(3)}/{m.group(1)}"


def _row_account_key(title: str, account_id: str) -> str:
    """The key a table row actually displays. Rows show the account LABEL
    ("Example Holder — Cash Plus Account — 1234567"), never the API's
    internal 15-digit accountId ("123400000000001") — matching rows by
    the internal ID fails for every document (the 2026-09-28 pilot's
    bug). The label rides in the doc title after the category prefix;
    for accounts whose label carries no number (the Individual 401(k)),
    the label text itself is the only row key."""
    t = (title or "").strip()
    for prefix in ("Account Statement - ", "Statement - "):
        if t.startswith(prefix):
            t = t[len(prefix):]
            break
    t = t.strip()
    if t:
        return t
    if account_id and len(account_id) <= 10:
        return account_id
    return ""


# How long a press is given to start its download. A statement answered in
# 62 seconds gave up at 60 and was then taken for the next statement in the
# pre-release review, so the wait is long, and a download that starts later
# than this is the one case left open (see download_document).
EVENT_WAIT_MS = 90000


def _printed_workplace_period(text: str, row: WorkplaceRow) -> bool:
    """Match the printed range, so dates elsewhere cannot validate a different PDF."""
    start = "|".join(map(re.escape, identity.date_variants(row.start)))
    end = "|".join(map(re.escape, identity.date_variants(row.end)))
    separator = r"(?:\s+(?:to|through)\s+|\s*[-–—]\s*)"
    return bool(re.search(rf"(?<!\d)(?:{start}){separator}(?:{end})(?!\d)",
                          " ".join(text.split()), re.I))


def _download_workplace(page, plan: str, end: str, document_id: str, out_path) -> bool:
    # The PDF URL's index is positional. Bind it to the selected plan and
    # exact period in a fresh list, and verify the downloaded file as well.
    row = next((row for row in _workplace_rows(page, plan)
                if row.document_id == document_id and row.end == end), None)
    if row is None:
        # Said in words alone. The plan number and the PDF's address stay
        # out of the log, which a person may attach to a report.
        log.info("workplace statement not in the plan's list now, nothing asked for")
        return False
    response = None
    try:
        response = page.context.request.get(row.pdf_url, max_redirects=0, timeout=25000,
                                            headers={"Accept": "application/pdf"})
        content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if response.status != 200 or content_type != "application/pdf":
            log.info("workplace statement answer was not a PDF (status %s)", response.status)
            return False
        data = intake.body(response)
        if not data.startswith(b"%PDF-"):
            log.info("workplace statement answer was not a PDF")
            return False
        pages = pdf_reader.page_texts(data, pages=2)
    except Exception as e:
        log.info("workplace statement could not be read (%s)", type(e).__name__)
        return False
    finally:
        if response is not None:
            response.dispose()
    if (not pages or not re.search(rf"\b{re.escape(plan)}\b", " ".join(pages))
            or not _printed_workplace_period(pages[0], row)):
        log.info("workplace statement PDF did not print the plan or period it was asked for, not saved")
        return False
    # Staged beside the statement and moved into place whole, so a write
    # that stops half way leaves nothing under the statement's name.
    try:
        placed = delivery.place(data, out_path)
    except OSError as e:
        log.info("workplace statement could not be written (%s)", type(e).__name__)
        return False
    if not placed.ok:
        log.info("workplace statement could not be put in place (%s)", placed.outcome)
        return False
    return True


def download_document(page, account_id: str, charitable: bool,
                      doc_type: str, title: str, date: str, out_path,
                      occurrence: int = 0, document_id_hint: str = "",
                      on_demand_type_hint: str = "", dl_dir=None) -> bool:
    """Download one statement PDF by clicking its row's download icon
    (title='Pdf download icon'). Verified live: the icon fires a real
    download with a descriptive suggested filename. The row is matched by
    the ACCOUNT NUMBER (from the title's trailing digits) and the row's own
    MM/DD/YYYY date text.

    The browser saves into `dl_dir`, a staging folder of the app's own, and
    never into the archive folder, given as a full path, since Chromium and
    Edge on Windows, told a relative one, cancel every download (review of
    0.41.0). With the folder set, the browser's file there is the statement
    in those browsers, since save_as then writes an empty file, and the
    file the download event names is moved to `out_path` by
    capture.take_download, only when it is the one document that arrived.
    Where the event's own copy is whole, as it was in a tester's Chrome on
    macOS, that copy is saved. Nothing is taken when the download failed or
    no download began, and nothing else in the folder is touched, but an
    exact copy of the statement. Without `dl_dir` the browser is left where
    it is and only the download event is taken. A press that brought no
    download at all stops the run (pressing.no_answer), since pressing again,
    here or on the next statement, could do something other than it did. An
    icon the page has turned off is not pressed, and nothing is, and its
    statement is left for review and the next run (pressing.TurnedOff).

    A press whose download begins later than EVENT_WAIT_MS fails, and its
    event can arrive inside the next press's wait. When this press's own
    statement lands as well, the two are different documents and nothing
    is taken. When the late one lands alone, first, it cannot be told from
    this press's, the one case left open here as in every app. No run has
    shown a download that late."""
    if doc_type == WORKPLACE_STATEMENT:
        return _download_workplace(page, account_id, date, document_id_hint, out_path)
    if is_workplace_page(page):
        raise ListStopped("Open the Vanguard brokerage statements for this document")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(dl_dir).resolve() if dl_dir else None

    if not ensure_statements(page):
        log.info("statements page not available for %s %s", account_id, date)
        return False

    needle = {"account": _row_account_key(title, account_id),
              "dateText": _mdy(date)}
    if not needle["account"]:
        log.info("no account number in title %r", (title or "")[:60])
        return False
    if not page.evaluate(_ROW_JS, needle):
        # The row for this (account, date) is not drawn on the table as it
        # stands. The statement's own year is picked first, so Show More is
        # pressed only through the year the row belongs to, never through
        # the whole of another. Without a picker the table as it stands is
        # the one shown more of.
        if select_year(page, (date or "")[:4]):
            page.wait_for_timeout(2500)
        else:
            log.info("could not select year %s", (date or "")[:4])
        if not row_is_shown(page, needle):
            log.info("no row for account %s on %s",
                     needle["account"], needle["dateText"])
            return False

    # Real pointer click on the row's download icon (title-matched: the
    # NBSP aria-labels defeat text locators — verified live). The
    # attached browser is pointed at the app's own staging folder first,
    # and the file the download event names is taken from there (see
    # paperpull_core.capture.set_download_dir). A file that arrives with
    # no event is not taken, since nothing ties it to this press.
    if staging:
        _set_download_dir(page, staging)
    before = _snapshot(staging)
    # A drawn row, as _ROW_JS found it. A copy of the row kept in the page
    # and not drawn has no box to press, and the press would stop the run.
    row = page.locator("table tr:visible, [role=row]:visible").filter(
        has_text=re.compile(escape_for_locator(needle["account"])))\
        .filter(has_text=needle["dateText"]).first
    icon = row.get_by_title("Pdf download icon").first
    # The one real click in this app goes through the guard like every
    # other click, with the element's own label. The icon's aria-label is
    # the document identity ("Download a pdf statement generated on ...")
    # printed with NBSP separators, which are folded to spaces before the
    # label is checked. Fail closed: a label the guard has never seen
    # refuses the download, not the guard.
    label = (icon.get_attribute("aria-label") or
             icon.get_attribute("title") or "").replace("\u00a0", " ")
    if not is_safe_control(label):
        log.warning("REFUSED download control %r - guard", label[:90])
        return False
    dl = None
    failed = ""
    began = False
    try:
        # Never forced. The icon is brought to the middle of the window and
        # pressed only when it is the thing on top there, and otherwise
        # nothing is pressed and the run stops (paperpull_core.pressing).
        # The press is given as long as the download, since Playwright's
        # wait on what a press starts runs on the press's own time.
        with page.expect_download(timeout=EVENT_WAIT_MS) as dl_info:
            pressing.click(page, icon, css="[title]",
                           what="the download icon of the statement dated %s" % date,
                           words=_words(), step="press a download icon",
                           timeout=EVENT_WAIT_MS)
        dl = dl_info.value
        began = True
        try:
            # Once the download has finished, within the time a download is
            # given, and cancelled past it or once it grows past the limit
            # in the folder (intake.failure).
            failed = intake.failure(dl, page, partial=lambda: _growing(staging, before))
        except Exception as e:
            failed = str(e).splitlines()[0][:70] if str(e) else type(e).__name__
    except pressing.TurnedOff:
        # The page has the icon turned off, so nothing was pressed and no
        # download was waited for. The statement is left for review and the
        # next run, and the run goes on.
        log.info("the download icon for %s is turned off, so nothing was pressed", date)
        return False
    except Exception as e:
        log.info("no download began for %s (%s)", date,
                 str(e).splitlines()[0][:70])
    how = ""
    if dl is not None and failed:
        # A download that failed is not taken from anywhere, and whatever
        # else reached the folder meanwhile is not this statement.
        log.info("the download for %s failed (%s)", date, failed[:70])
    elif dl is not None:
        # The event's own copy where setting the folder had no effect, and
        # otherwise the browser's file under the event's name, taken only
        # when it is the one document that arrived (capture.take_download).
        for _ in range(20):
            took = _take_download(dl, staging, before, out_path)
            if took == "event":
                how = "the download event (%s)" % (dl.suggested_filename or "")[:60]
            elif took:
                how = "the browser's own file"
            if how or not staging:
                break
            page.wait_for_timeout(500)
    # An exact copy of the statement left in the folder goes, and nothing
    # else there is touched (capture.clear_copies).
    try:
        _clear_copies(staging, before, out_path)
    except Exception:
        pass
    if how and out_path.exists() and out_path.read_bytes()[:5] == b"%PDF-":
        log.info("captured via %s", how)
        return True
    log.info("nothing was saved for %s", date)
    # A failed capture must not leave this app's file behind, empty or not
    # a PDF. Only that file. Nothing in the browser's folder is deleted.
    try:
        if out_path.exists():
            out_path.unlink()
    except OSError:
        pass
    if not began:
        # The icon was pressed and no download began at all. Pressing it
        # again, or the next statement's icon, could do something other than
        # this press did, so the run stops here, as American Express's does.
        raise pressing.no_answer("download a statement", "no download came",
                                 "The download icon of the statement dated %s was pressed "
                                 "once and no download came." % date)
    return False


# ---------------------------------------------------------------- UI read

def read_page_ui(page) -> Optional[dict]:
    """A small, redactable summary of what the page shows (for Diagnostics)."""
    try:
        years = year_options(page)
        accounts = page.evaluate(
            "() => [...document.querySelectorAll('select option')]"
            ".map(o => o.innerText.trim()).slice(0, 12)")
        return {"years": years, "accounts": accounts,
                "url": (page.url or "")[:120]}
    except Exception:
        return None


def redact_label(text: str) -> str:
    t = re.sub(r"\d{3,}", lambda m: "*" * len(m.group(0)), text or "")
    return t[:80]
