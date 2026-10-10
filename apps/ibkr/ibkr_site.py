"""ALL Interactive Brokers selectors, URLs, and page behavior live here.

When Interactive Brokers changes its site, repair this file only.

SAFETY (this is a brokerage):
  This module is strictly READ-ONLY. It navigates to the Statements page,
  reads the months that can be asked for, and downloads the PDF Interactive
  Brokers generates for each. It must NEVER activate any control that
  trades, transfers, deposits, withdraws, converts a currency, changes a
  holding or changes any setting. FORBIDDEN_CONTROL_RE is the guard; every
  click must ALSO look like a document action (SAFE_DOC_CONTROL_RE) before
  it may be clicked. There is no code here that submits a form or confirms
  a dialog.

  Every press goes through paperpull_core.pressing, never forced, so a
  control is pressed only when it is the thing on top in the middle of the
  window, and otherwise nothing is pressed and the run stops.

Site truth (read from a signed-in session, 2026-10, nothing downloaded to
learn it except the statements themselves):

  - Sign-in is https://www.interactivebrokers.com/sso/Login, which sends the
    browser to the domain of its region (a UK address lands on a .co.uk
    one). The sign-in takes a second factor approved on the person's phone,
    which stays with the person. The portal, and the Account Management
    pages behind it, are on that same regional host, so every address here
    is built on the host the person was sent to, never on a fixed one.
  - Statements is a page of the Account Management app, reached from the
    portal's own Statements link. Its Default Statements list names each
    kind of statement (Activity Statement, MTM Summary, Realized Summary,
    Trade Confirmation and others). Opening Activity Statement shows a
    dialog with a Period select (Daily, Custom Date Range, Monthly, Annual,
    Month to Date, Year to Date), a Date select, and the buttons Download
    PDF, Download CSV, Download HTML and View Statement.
  - With Period set to Monthly the Date select lists every month the
    account has, newest first ("September, 2026"), back to the month the
    account opened. That list is what this reads. Nothing is computed from
    the account's age.
  - Download PDF fires a real browser download of the statement for the
    month chosen, named <account>_<YYYYMM>_<YYYYMM>.pdf. The dialog closes
    itself afterwards.
  - The page's own requests carry a session value a plain request from
    outside the page does not, and one made that way is refused and ends the
    session. So nothing here asks the statement address directly. The page's
    own button is pressed, as a person would.
  - A session that has ended lands on /AccountManagement/Expire, "Your
    Session Has Expired."

Scope: the monthly Activity Statement, which is the statement of record.
The page also offers tax documents, trade confirmations, flex queries and
third-party reports. Those are not read here, so no folder is made for them.
"""
# Site layer verified working against the live site: 2026-10 (listing and download; see the app's tests for what is pinned)
from __future__ import annotations

import logging
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlsplit

from paperpull_core import pressing
from paperpull_core.words import words_for as _words_for
from paperpull_core.urls import is_safe_url as _host_allows
from paperpull_core.dates import last_day as _last_day
from paperpull_core.capture import set_download_dir as _set_download_dir
from paperpull_core.capture import snapshot as _snapshot
from paperpull_core.capture import take_download as _take_download
from paperpull_core.capture import clear_copies as _clear_copies
from paperpull_core.controls import (AUTH_CONTROL_RE, SETTINGS_CONTROL_RE,
                                     is_forbidden_context as _core_forbidden)
from paperpull_core.controls import escape_for_locator

log = logging.getLogger("ibkr_docs.site")


def _words():
    """This app's own words for paperpull_core.words, from what its source
    calls it, for saying what covered a control."""
    return _words_for("Interactive Brokers", sys.modules[__name__])


# The regional domains seen so far: .com, and the .co.uk and .ie a sign-in was
# sent to from the United Kingdom and from Ireland (a session belongs to the
# domain it was made on, so a tab on one is not signed in on another). A person
# sent to a domain that is not here is told so (see regional_host_problem), and
# it is added once someone confirms it, which is how the other apps grew theirs.
ALLOWED_HOSTS = {"www.interactivebrokers.com", "www.interactivebrokers.co.uk",
                 "www.interactivebrokers.ie"}


def is_safe_url(url: str) -> bool:
    return _host_allows(url, ALLOWED_HOSTS, subdomains=False)


BASE = "https://www.interactivebrokers.com"
STATEMENTS_PATH = ("/AccountManagement/AmAuthentication"
                   "?action=RM_STATEMENTS&service=AM.LOGIN&webaccess=true")
URLS = {
    "home": f"{BASE}/",
    "login": f"{BASE}/sso/Login",
    "portal": f"{BASE}/portal/",
    "documents": f"{BASE}{STATEMENTS_PATH}",
}

LOGIN_URL_MARKERS = ["/sso/login", "/accountmanagement/expire"]
EXPIRED_TITLE = "your session has expired"

SECURITY_CHALLENGE_MARKERS = [
    "open the ibkr notification on your phone",
    "complete two factor authentication",
    "enter the code",
    "security code",
    "verify your identity",
]
RATE_LIMIT_MARKERS = [
    re.compile(r"too many (attempts|requests|login)", re.I),
    re.compile(r"temporarily (locked|unavailable|disabled)", re.I),
]

# ---------------------------------------------------------------- guards

# Anchored stems, none with an exception clause: a word that names a thing
# this app must never press is refused wherever it stands in a label. The
# page this reads sits beside Deposit, Withdraw, Transfer Funds, Orders &
# Trades and a Trade button, and next to a delivery setting for statements.
FORBIDDEN_CONTROL_RE = re.compile(
    r"(\btrad(e|es|ed|ing|er)\b|\border(s|ed|ing)?\b|\bbuy(s|ing)?\b|\bsell(s|ing)?\b|"
    r"\bshort(s|ing)?\b|\bexercis(e|es|ed|ing)\b|\brebalanc(e|es|ed|ing)\b|"
    r"\bconvert(s|ed|ing)?\b|\bconversion\b|\bcurrenc(y|ies)\b|\bforex\b|\bfx\b|"
    r"\btransfer(s|red|ring)?\b|\bdeposit(s|ed|ing)?\b|\bwithdraw(s|n|al|als|ing)?\b|"
    r"\bfund(s|ed|ing)?\b|\bwire\b|\bach\b|\bpay(s|ed|ing|ment|ments)?\b|"
    r"\bmargin\b|\bborrow(s|ed|ing)?\b|\blend(s|ing)?\b|"
    r"\bcancel(s|led|ling)?\b|\bclos(e|es|ed|ing)\b|\bopen\s+(a\s+)?(new\s+)?account\b|"
    r"\badd(s|ed|ing)?\b|\bremov(e|es|ed|ing|al)\b|\bdelet(e|es|ed|ing)\b|"
    r"\bchang(e|es|ed|ing)\b|\bedit(s|ed|ing)?\b|\bupdat(e|es|ed|ing)\b|"
    r"\benabl(e|es|ed|ing)\b|\bdisabl(e|es|ed|ing)\b|\bactivat(e|es|ed|ing)\b|"
    r"\bsubscri(be|bes|bed|bing|ption|ptions)\b|\bunsubscri(be|bes|bed|bing)\b|"
    r"\brequest(s|ed|ing)?\b|\bsubmit(s|ted|ting)?\b|\bconfirm(s|ed|ing)?\b|"
    r"\bapply\b|\bupload(s|ed|ing)?\b|\bdeliver(y|ies|ed)\b|\bsettings?\b|"
    r"\bpreferences?\b|\bnotifications?\b|\balerts?\b|\bsecurity\b|\btokens?\b|"
    r"\bapi\b|\bsso\b)",
    re.I,
)

# The core's tested versions, imported, never rewritten here: a local copy
# once missed "Logon" on a provider whose sign-in host said it.

SAFE_DOC_CONTROL_RE = re.compile(r"(\bdownload\b|\bpdf\b|\bstatements?\b)", re.I)

# The two controls that are pressed, named exactly. The guard above must pass
# them AND they must be these words, so a delivery toggle that also says
# "Activity Statement" ("Monthly Activity Statement") is not mistaken for the row.
ACTIVITY_ROW_RE = re.compile(r"^\s*Activity Statement\s*$", re.I)
DOWNLOAD_PDF_RE = re.compile(r"^\s*Download PDF\s*$", re.I)


def is_safe_control(name: str) -> bool:
    name = (name or "").replace(" ", " ").strip()
    if not name:
        return False
    if (FORBIDDEN_CONTROL_RE.search(name) or SETTINGS_CONTROL_RE.search(name)
            or AUTH_CONTROL_RE.search(name)):
        return False
    return bool(SAFE_DOC_CONTROL_RE.search(name))


def is_money_control(identity: str) -> bool:
    """The core's check: money or auth context, the provider's own
    blocklist, and an empty identity, all fail closed."""
    return _core_forbidden(identity, FORBIDDEN_CONTROL_RE)


# ---------------------------------------------------------------- session

def looks_signed_out(page) -> bool:
    url = (page.url or "").lower()
    if any(m in url for m in LOGIN_URL_MARKERS):
        return True
    try:
        if EXPIRED_TITLE in (page.title() or "").lower():
            return True
    except Exception:
        pass
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


# ---------------------------------------------------------------- dates

_MONTHS = ["january", "february", "march", "april", "may", "june", "july",
           "august", "september", "october", "november", "december"]
MONTH_LABEL_RE = re.compile(
    r"^\s*(January|February|March|April|May|June|July|August|September|"
    r"October|November|December),?\s+((?:19|20)\d{2})\s*$", re.I)
MONTH_CODE_RE = re.compile(r"(?:^|[:_])((?:19|20)\d{2})(0[1-9]|1[0-2])$")


def parse_month_label(text: str) -> Optional[Tuple[int, int]]:
    """'September, 2026' as (2026, 9), or None for anything else."""
    m = MONTH_LABEL_RE.match(text or "")
    if not m:
        return None
    return int(m.group(2)), _MONTHS.index(m.group(1).lower()) + 1


def month_code(year: int, month: int) -> str:
    return f"{year:04d}{month:02d}"


def parse_month_code(text: str) -> Optional[Tuple[int, int]]:
    """'202609' or 'string:202609' as (2026, 9), or None."""
    m = MONTH_CODE_RE.search((text or "").strip())
    return (int(m.group(1)), int(m.group(2))) if m else None


def month_end_iso(year: int, month: int) -> str:
    """The date a monthly statement is filed under: the last day of its month."""
    return f"{year:04d}-{month:02d}-{_last_day(year, month):02d}"


def parse_date(text: str) -> str:
    """YYYY-MM-DD from the text, or ''. Statements here are dated by month, so
    this only reads the ISO dates the app writes itself."""
    m = re.match(r"\s*(\d{4})-(\d{2})-(\d{2})(?!\d)", text or "")
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else ""


# ---------------------------------------------------------------- navigation

REGIONAL_HOST_RE = re.compile(r"(^|\.)interactivebrokers\.[a-z.]+$", re.I)


def regional_host_problem(url: str) -> Optional[str]:
    """A sentence when the address is an Interactive Brokers domain this app
    does not list, and None otherwise. Such a tab is signed in, but not here:
    it would otherwise be passed over for a new one that has no session."""
    try:
        host = urlsplit(url or "").hostname or ""
    except ValueError:
        return None
    if REGIONAL_HOST_RE.search(host) and not is_safe_url(url):
        return ("Interactive Brokers sent you to %s, which this app does not list yet. "
                "Add it to ALLOWED_HOSTS in ibkr_site.py, or open an issue." % host)
    return None


def _origin(page) -> str:
    """scheme://host of the page the person is on when it is one of ours, and
    otherwise the default. The regional host is the one signed in."""
    try:
        url = page.url or ""
        if is_safe_url(url):
            parts = urlsplit(url)
            return f"{parts.scheme}://{parts.hostname}"
    except Exception:
        pass
    return BASE


def on_documents_page(page) -> bool:
    """On the Statements page: its Default Statements list is the structural
    marker, and the page can show it with nothing in the list."""
    try:
        if not is_safe_url(page.url or ""):
            return False
        if "/accountmanagement/" not in (page.url or "").lower():
            return False
        return page.get_by_text(re.compile(r"^\s*Default Statements\s*$", re.I)).count() > 0
    except Exception:
        return False


def goto_documents(page) -> bool:
    """Reach the Statements page on the host the person signed in on. The
    portal's own Statements link makes the hand-off to Account Management
    that this address performs, so the address is tried first and the portal
    link second."""
    try:
        for tab in page.context.pages:
            problem = regional_host_problem(tab.url)
            if problem:
                log.warning(problem)
                break
    except Exception:
        pass
    origin = _origin(page)
    for url in (origin + STATEMENTS_PATH,):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(4000)
            if looks_signed_out(page):
                return False
            if _wait_for_statements(page):
                return True
        except Exception as e:
            log.info("statements address failed: %s", str(e).splitlines()[0][:80])
    return False


def _wait_for_statements(page, ms: int = 15000) -> bool:
    waited = 0
    while waited < ms:
        if on_documents_page(page):
            return True
        page.wait_for_timeout(500)
        waited += 500
    return False


def ensure_statements(page) -> bool:
    if on_documents_page(page):
        return True
    return goto_documents(page)


# ---------------------------------------------------------------- the dialog

def _select_options(sel) -> List[str]:
    try:
        return [o.strip() for o in sel.locator("option").all_inner_texts()]
    except Exception:
        return []


def _is_period_options(opts: List[str]) -> bool:
    return "Monthly" in opts and "Annual" in opts


def _is_month_options(opts: List[str]) -> bool:
    return bool(opts) and all(parse_month_label(o) for o in opts[:3])


# What a dropdown in the statement dialog answers to: its own labels, the
# dialog's title and the form it sits in. The core's reading (control_identity)
# also climbs to the nearest page-wide "widget" and takes its heading, and the
# whole portal sits inside one whose heading is an unrelated market-data one
# ("... Display Update"), which put a forbidden word on every dropdown here and
# refused all of them. The dialog is the context that says what a dropdown is.
_DIALOG_IDENTITY_JS = r"""el => {
  const bits = ['aria-label', 'name', 'id', 'title'].map(a => el.getAttribute(a) || '');
  const dlg = el.closest("[role='dialog']");
  if (dlg) {
    bits.push(dlg.getAttribute('aria-label') || '');
    const t = dlg.querySelector('.modal-title');
    if (t) bits.push((t.innerText || '').slice(0, 60));
  }
  const form = el.closest('form, [ng-form]');
  if (form) bits.push(form.id || '', form.getAttribute('name') || '', form.getAttribute('ng-form') || '');
  return bits.filter(Boolean).join(' | ');
}"""


def _select_identity(sel, opts: List[str]) -> str:
    """What a dropdown answers to (see _DIALOG_IDENTITY_JS), and when the page
    gives it no name at all, what it offers. A dropdown whose options are the
    periods, or months, is a period filter whatever its markup calls it, and
    one that offers anything else has no name here and is refused (an empty
    identity is, in the core's check)."""
    try:
        own = sel.evaluate(_DIALOG_IDENTITY_JS) or ""
    except Exception:
        own = ""
    if own:
        return own
    if _is_period_options(opts) or _is_month_options(opts):
        return "statement period " + " ".join(opts[:8])
    return ""


def _find_select(page, wanted):
    """The visible dropdown whose options `wanted` accepts and the guard
    allows, or None. Chosen by what it offers, never by position."""
    try:
        loc = page.locator("select")
        n = min(loc.count(), 12)
    except Exception:
        return None
    for i in range(n):
        sel = loc.nth(i)
        try:
            if not sel.is_visible():
                continue
        except Exception:
            continue
        opts = _select_options(sel)
        if not wanted(opts):
            continue
        identity = _select_identity(sel, opts)
        if is_money_control(identity):
            log.warning("refusing dropdown: %s", identity[:120])
            continue
        return sel
    return None


def period_select(page):
    return _find_select(page, _is_period_options)


def month_select(page):
    return _find_select(page, _is_month_options)


def dialog_is_open(page) -> bool:
    return period_select(page) is not None


def close_dialog(page) -> None:
    """Close the statement dialog with the Escape key, which presses nothing."""
    for _ in range(2):
        if not dialog_is_open(page):
            return
        try:
            page.keyboard.press("Escape")
            page.wait_for_timeout(800)
        except Exception:
            return


def _activity_run_control(page):
    """The Run control (the arrow at the end of the row) of the row titled
    exactly Activity Statement in the Default Statements list, or None. Read
    from the page: each row is a div with the statement's name in bold and
    two links, Info and Run. Only Run is ever pressed, and only on the row
    whose name is exactly this, so the delivery toggle called Monthly
    Activity Statement and the other statements' rows are not it."""
    try:
        rows = page.locator("div.row").filter(
            has=page.locator("strong", has_text=ACTIVITY_ROW_RE))
        for i in range(min(rows.count(), 6)):
            row = rows.nth(i)
            run = row.locator("a[aria-label='Run']")
            if run.count() == 1 and run.first.is_visible():
                return run.first
    except Exception:
        pass
    return None


# The list of statements is drawn after the page's heading is, and a slower
# machine shows the heading first for a good while.
ROWS_WAIT_MS = 30000


def _wait_for_run_control(page, ms: int = ROWS_WAIT_MS):
    waited = 0
    while waited < ms:
        run = _activity_run_control(page)
        if run is not None:
            return run
        page.wait_for_timeout(500)
        waited += 500
    return None


def _clear_stray_dialog(page) -> None:
    """A dialog left open by an earlier press (the report-being-generated one,
    for instance) sits over the list. It is closed with the Escape key, which
    presses nothing, and only when it is not the statement dialog this is
    about to use."""
    try:
        stray = page.locator("#amModal.show")
        if stray.count() and stray.first.is_visible() and not dialog_is_open(page):
            page.keyboard.press("Escape")
            page.wait_for_timeout(1200)
    except Exception:
        pass


def open_activity_dialog(page) -> bool:
    """Open Activity Statement from the Default Statements list, and leave it
    on Monthly with the month list showing."""
    if not ensure_statements(page):
        return False
    if not dialog_is_open(page):
        _clear_stray_dialog(page)
        run = _wait_for_run_control(page)
        if run is None:
            log.info("no Run control on the Activity Statement row")
            return False
        # The control's own words are just "Run". The row it is on is the
        # document, so the guard is asked about both together.
        label = ((run.get_attribute("aria-label") or "") + " Activity Statement")
        if not is_safe_control(label):
            log.warning("REFUSED row control %r - guard", label[:90])
            return False
        pressing.click(page, run, css=pressing.LINKS,
                       what="the Run control of the Activity Statement row",
                       words=_words(), step="open the Activity Statement dialog")
        for _ in range(20):
            page.wait_for_timeout(500)
            if dialog_is_open(page):
                break
    if not dialog_is_open(page):
        return False
    return choose_monthly(page)


def choose_monthly(page) -> bool:
    sel = period_select(page)
    if sel is None:
        return False
    try:
        if "Monthly" not in (sel.evaluate("s => s.selectedOptions[0] ? s.selectedOptions[0].text : ''") or ""):
            sel.select_option(label="Monthly", timeout=8000)
            page.wait_for_timeout(1500)
    except Exception as e:
        log.info("could not choose Monthly: %s", str(e).splitlines()[0][:80])
        return False
    for _ in range(10):
        if month_select(page) is not None:
            return True
        page.wait_for_timeout(500)
    return False


# ---------------------------------------------------------------- collection

ACCOUNT_ID_RE = re.compile(r"\b((?:DU|U|F|I)\d{6,9})\b")


def read_account_id(page) -> str:
    """The account the Statements page is showing, from the first account
    number in its heading area. Empty when none reads."""
    try:
        text = page.evaluate("() => (document.body.innerText || '').slice(0, 1200)")
    except Exception:
        return ""
    m = ACCOUNT_ID_RE.search(text or "")
    return m.group(1) if m else ""


def collect_statement_periods(page, keep=None) -> List[dict]:
    """The months the Date select offers under Monthly, as
    {label, code, year, month, account_id}. `keep`, when given, says which
    options a scoped run wants (paperpull_core.scope.period_filter); the
    options it refuses are not returned. The dialog is closed again."""
    if not open_activity_dialog(page):
        return []
    account_id = read_account_id(page)
    out: List[dict] = []
    try:
        sel = month_select(page)
        labels = _select_options(sel) if sel is not None else []
        values = []
        try:
            values = sel.evaluate("s => [...s.options].map(o => o.value)") if sel is not None else []
        except Exception:
            values = []
        for i, label in enumerate(labels):
            ym = parse_month_label(label)
            if not ym:
                continue
            if keep is not None and not keep(label):
                continue
            code = month_code(*ym)
            coded = parse_month_code(values[i]) if i < len(values) else None
            if coded and coded != ym:
                log.info("an option's label and value name different months, skipped")
                continue
            out.append({"label": label.strip(), "code": code, "year": ym[0],
                        "month": ym[1], "account_id": account_id})
    finally:
        close_dialog(page)
    return out


def account_label_from_statement(s: dict) -> str:
    acct = (s.get("account_id") or "").strip()
    return f"Account {acct}" if acct else "Account"


def classify_document(doc: dict) -> Tuple[str, str, str, str]:
    """Engine contract: (category, date, period, title) from a month read off
    the page. A monthly statement is filed under the last day of its month."""
    year, month = int(doc["year"]), int(doc["month"])
    label = account_label_from_statement(doc)
    return ("Statement", month_end_iso(year, month), f"{year:04d}-{month:02d}",
            f"Activity Statement - {label}")


def list_documents(page, keep=None) -> List[dict]:
    """Every month the account offers, shaped for the engine."""
    out: List[dict] = []
    for s in collect_statement_periods(page, keep=keep):
        cat, date_iso, period, title = classify_document(s)
        acct = s.get("account_id") or ""
        out.append({
            "account": account_label_from_statement(s),
            "account_id": acct,
            "last4": acct[-4:] if acct else "",
            "date": date_iso,
            "period": period,
            "title": title,
            "category": cat,
            "document_id": s["code"],
            "doc_type": "Activity Statement",
            "occurrence": 0,
            "ambiguous": False,
        })
    return out


def collect_documents(page, keep=None) -> List[dict]:
    return list_documents(page, keep=keep)


# ---------------------------------------------------------------- download

# How long a press is given to start its download. The statement is built when
# it is asked for, so this is long.
EVENT_WAIT_MS = 90000
NAMED_MONTHS_RE = re.compile(r"_((?:19|20)\d{2}(?:0[1-9]|1[0-2]))_((?:19|20)\d{2}(?:0[1-9]|1[0-2]))\.pdf$", re.I)


def named_month_matches(suggested: str, code: str) -> bool:
    """False only when the file's own name says it is for another month than
    the one asked for. A name in some other shape says nothing and passes."""
    m = NAMED_MONTHS_RE.search(suggested or "")
    if not m:
        return True
    return m.group(1) == code and m.group(2) == code


def download_document(page, account_id: str, doc_type: str, title: str,
                      date: str, out_path, occurrence: int = 0,
                      document_id_hint: str = "", dl_dir=None) -> bool:
    """Download one monthly statement PDF by pressing the dialog's own
    Download PDF button, with the month and Monthly chosen first.

    The month is the code the list gave (document_id_hint), and otherwise the
    date's own month. A file whose name says it is for another month is not
    taken. The browser saves into `dl_dir`, the app's own staging folder, as
    for every app, and the file the download event names is moved to
    `out_path` by capture.take_download. A press that brought no download at
    all stops the run (pressing.no_answer), since pressing again could do
    something other than it did."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(dl_dir).resolve() if dl_dir else None

    ym = parse_month_code(document_id_hint) or parse_month_code(
        (date or "").replace("-", "")[:6])
    if not ym:
        log.info("no month to ask for in %r / %r", document_id_hint, date)
        return False
    code = month_code(*ym)
    label = f"{_MONTH_NAMES[ym[1] - 1]}, {ym[0]}"

    if not open_activity_dialog(page):
        log.info("the statement dialog would not open for %s", code)
        return False
    sel = month_select(page)
    if sel is None:
        return False
    try:
        sel.select_option(label=label, timeout=8000)
        page.wait_for_timeout(800)
    except Exception as e:
        log.info("month %s not selectable: %s", label, str(e).splitlines()[0][:80])
        close_dialog(page)
        return False

    button = page.get_by_role("button", name=DOWNLOAD_PDF_RE)
    if button.count() == 0 or not button.first.is_visible():
        log.info("no Download PDF button for %s", code)
        close_dialog(page)
        return False
    icon = button.first
    # The one real click in this app goes through the guard like every
    # other, with the element's own words. A label the guard has never seen
    # refuses the download, not the guard.
    words = (icon.inner_text(timeout=2000) or icon.get_attribute("aria-label") or "")
    words = words.replace(" ", " ").strip()
    if not (DOWNLOAD_PDF_RE.match(words) and is_safe_control(words)):
        log.warning("REFUSED download control %r - guard", words[:90])
        close_dialog(page)
        return False

    if staging:
        _set_download_dir(page, staging)
    before = _snapshot(staging)
    dl = None
    failed = ""
    began = False
    try:
        with page.expect_download(timeout=EVENT_WAIT_MS) as dl_info:
            pressing.click(page, icon, css=pressing.BUTTONS,
                           what="the Download PDF button for the statement of %s" % label,
                           words=_words(), step="press the download button",
                           timeout=EVENT_WAIT_MS)
        dl = dl_info.value
        began = True
        try:
            failed = dl.failure() or ""
        except Exception as e:
            failed = str(e).splitlines()[0][:70] if str(e) else type(e).__name__
    except pressing.Stop:
        raise
    except Exception as e:
        log.info("no download began for %s (%s)", code, str(e).splitlines()[0][:70])

    how = ""
    if dl is not None and failed:
        log.info("the download for %s failed (%s)", code, failed[:70])
    elif dl is not None and not named_month_matches(dl.suggested_filename or "", code):
        # Another month's file under this month's press. Not taken.
        log.warning("the file named %r is not the statement for %s, not taken",
                    (dl.suggested_filename or "")[:60], code)
    elif dl is not None:
        for _ in range(20):
            took = _take_download(dl, staging, before, out_path)
            if took == "event":
                how = "the download event (%s)" % (dl.suggested_filename or "")[:60]
            elif took:
                how = "the browser's own file"
            if how or not staging:
                break
            page.wait_for_timeout(500)
    try:
        _clear_copies(staging, before, out_path)
    except Exception:
        pass
    close_dialog(page)
    if how and out_path.exists() and out_path.read_bytes()[:5] == b"%PDF-":
        log.info("captured via %s", how)
        return True
    log.info("nothing was saved for %s", code)
    try:
        if out_path.exists():
            out_path.unlink()
    except OSError:
        pass
    if not began:
        raise pressing.no_answer("download a statement", "no download came",
                                 "The Download PDF button for the statement of %s was pressed "
                                 "once and no download came." % label)
    return False


_MONTH_NAMES = [m.capitalize() for m in _MONTHS]


# ---------------------------------------------------------------- UI read

def read_page_ui(page) -> Optional[dict]:
    """A small, redactable summary of what the page shows (for Diagnostics)."""
    try:
        sel = month_select(page)
        labels = _select_options(sel) if sel is not None else []
        years = sorted({ym[0] for ym in map(parse_month_label, labels) if ym}, reverse=True)
        return {"years": [str(y) for y in years], "months": len(labels),
                "url": redact_label(page.url or "")[:120]}
    except Exception:
        return None


def redact_label(text: str) -> str:
    return re.sub(r"\d{3,}", lambda m: "*" * len(m.group(0)), text or "")
