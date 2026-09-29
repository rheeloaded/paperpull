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

import logging
import os
import re
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from paperpull_core.urls import is_safe_url as _host_allows
from paperpull_core.dates import checked as _checked_date
from paperpull_core.capture import set_download_dir as _set_download_dir
from paperpull_core.capture import UNFINISHED as _UNFINISHED
from paperpull_core.controls import control_identity

log = logging.getLogger("vanguard_docs.site")


ALLOWED_HOSTS = {'investor.vanguard.com', 'logon.vanguard.com',
                 'statements.web.vanguard.com', 'personal1.vanguard.com',
                 'vanguard.com', 'secure.vanguard.com'}


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
                c.first.click()
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

def on_documents_page(page) -> bool:
    try:
        url = (page.url or "").lower()
        if "statements.web.vanguard.com" not in url:
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
    import json as _json
    batches: List[dict] = []

    def on_resp(r):
        try:
            if not STATEMENTS_API_RE.search(r.url or ""):
                return
            data = _json.loads(r.text())
            if isinstance(data, dict) and isinstance(data.get("statements"), list):
                batches.append(data)
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

        walk = years or year_options(page)
        if keep is not None:
            walk = [y for y in walk if keep(y)]
        for yr in walk:
            if not select_year(page, yr):
                continue
            page.wait_for_timeout(1500)
    finally:
        try:
            page.remove_listener("response", on_resp)
        except Exception:
            pass

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
    stmts = collect_statements_json(page, keep=keep)
    out: List[dict] = []
    for s in stmts:
        cat, date_iso, period, title = classify_document(s)
        num = s.get("accountNumber") or ""
        out.append({
            "account": account_label_from_statement(s),
            "account_id": s.get("accountId", ""),
            "last4": num[-4:] if num else "",
            "date": date_iso,
            "period": period,
            "title": title,
            "category": cat,
            "statement_id": s.get("statementId", ""),
            "statement_number": s.get("statementNumber", ""),
            "doc_type": "Statement",
            "occurrence": 0,
            "ambiguous": False,
        })
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
        if (/pdf download/i.test(title)) return true;
      }
    }
  }
  return false;
}"""


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


def _folder_state(dl_dir) -> dict:
    """Each file in the staging folder, by name, with its size and when it
    was last written. A download that reuses a name the folder already
    holds is written over it in place, so a name alone would not show it
    as new."""
    out: dict = {}
    if not dl_dir:
        return out
    try:
        for entry in os.scandir(dl_dir):
            if entry.is_file():
                st = entry.stat()
                out[entry.name] = (st.st_size, st.st_mtime_ns)
    except OSError:
        pass
    return out


def _take_browser_file(dl_dir, before: dict, out_path: Path, prefer: str = "") -> bool:
    """Move the statement the browser saved into `dl_dir` since `before` to
    `out_path`. The file the download event named is taken first, else the
    newest new one. Only a finished file that starts with the PDF marker is
    taken, and nothing else in the folder is touched, since a download the
    person starts in another tab of that browser lands there as well."""
    if not dl_dir:
        return False
    now = _folder_state(dl_dir)
    new = [n for n, st in now.items()
           if before.get(n) != st and not n.lower().endswith(_UNFINISHED)]
    new.sort(key=lambda n: (n != prefer, -now[n][1]))
    for name in new:
        src = Path(dl_dir) / name
        try:
            with src.open("rb") as f:
                if f.read(5) != b"%PDF-":
                    continue
        except OSError:
            continue
        try:
            os.replace(src, out_path)
            return True
        except OSError:
            try:
                shutil.copyfile(src, out_path)
                src.unlink()
                return True
            except OSError:
                continue
    return False


def _event_copy(dl) -> Optional[Path]:
    """Playwright's own copy of a download, when it holds any bytes.

    Measured 2026-09-29 on Chromium 149 to 153 and Edge 154 with Playwright
    1.63, over CDP and in a persistent context alike. Once the browser's
    download folder has been set over DevTools, which download_document
    does, the download event still fires, but Playwright's copy never
    exists and save_as writes an EMPTY file. The browser's own file in that
    folder is then the only copy. Where setting the folder has no effect,
    Playwright's copy holds the whole file."""
    try:
        p = dl.path()
    except Exception:
        return None
    try:
        if p and Path(p).exists() and Path(p).stat().st_size > 0:
            return Path(p)
    except OSError:
        pass
    return None


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
    never into the archive folder. With the folder set, the browser's file
    there is the statement, since save_as then writes an empty file (see
    _event_copy), and it is moved to `out_path`. Where setting the folder
    had no effect, the download event's own copy is saved. Nothing in the
    folder is ever deleted. Without `dl_dir` the browser is left where it
    is and only the download event is taken."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(dl_dir) if dl_dir else None

    if not ensure_statements(page):
        log.info("statements page not available for %s %s", account_id, date)
        return False

    needle = {"account": _row_account_key(title, account_id),
              "dateText": _mdy(date)}
    if not needle["account"]:
        log.info("no account number in title %r", (title or "")[:60])
        return False
    if not page.evaluate(_ROW_JS, needle):
        # The row for this (account, date) is not on the current year's
        # table — select the statement's year and re-check.
        if not select_year(page, (date or "")[:4]):
            log.info("could not select year %s", (date or "")[:4])
            return False
        page.wait_for_timeout(2500)
        if not page.evaluate(_ROW_JS, needle):
            log.info("no row for account %s on %s",
                     needle["account"], needle["dateText"])
            return False

    # Real pointer click on the row's download icon (title-matched: the
    # NBSP aria-labels defeat text locators — verified live). The
    # attached browser is pointed at the app's own staging folder first, so
    # a browser that saves the file itself and raises no event still saves
    # it where it is looked for (the nine-scaffolds lesson; see
    # paperpull_core.capture.set_download_dir).
    if staging:
        _set_download_dir(page, staging)
    before = _folder_state(staging)
    row = page.locator("table tr, [role=row]").filter(
        has_text=re.compile(re.escape(needle["account"])))\
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
    try:
        with page.expect_download(timeout=30000) as dl_info:
            icon.click(force=True)
        dl = dl_info.value
        try:
            dl.failure()   # returns once the download has finished
        except Exception:
            pass
    except Exception as e:
        log.info("no download event for %s (%s)", date,
                 str(e).splitlines()[0][:70])
    how = ""
    if dl is not None and _event_copy(dl) is not None:
        try:
            dl.save_as(str(out_path))
            how = "the download event (%s)" % (dl.suggested_filename or "")[:60]
        except Exception as e:
            log.info("saving the download failed: %s", str(e).splitlines()[0][:70])
    if not how and staging:
        prefer = (dl.suggested_filename or "") if dl is not None else ""
        # A browser that raised no event saves the file itself, so it is
        # given longer to arrive.
        for _ in range(20 if dl is not None else 60):
            if _take_browser_file(staging, before, out_path, prefer):
                how = "the browser's own file"
                break
            page.wait_for_timeout(500)
    if how and out_path.exists() and out_path.read_bytes()[:5] == b"%PDF-":
        log.info("captured via %s", how)
        return True
    log.info("download for %s was not a PDF", date)
    # A failed capture must not leave this app's file behind, empty or not
    # a PDF. Only that file. Nothing in the browser's folder is deleted.
    try:
        if out_path.exists():
            out_path.unlink()
    except OSError:
        pass
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