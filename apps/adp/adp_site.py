"""ALL ADP Workforce Now selectors, URLs, and page behavior live here.

When ADP changes its portal, repair this file only.

How Workforce Now serves pay statements, mapped on 2026-09-21 against a
signed-in employee account (a former employer's, still open):

* Sign-in is at online.adp.com and lands in the Workforce Now shell,
  ``https://workforcenow.adp.com/theme/index.html#/...``. The page the
  requester named (#46), ``#/Myself/PayandAnnualStatements``, is titled
  "Pay & Tax Statements" and shows My Pay (hidden by default behind
  "Hide My Pay") and Tax Statements (a W-2 card with "View statement").
  The whole thing is web components in shadow roots, so nothing here
  reads the DOM for data.
* The page fills itself from ADP's myADP services on my.adp.com, called
  with the session's cookies from inside the WFN page:

      GET https://my.adp.com/myadp_prefix/payroll/v1/workers/<AOID>/pay-statements?adjustments=yes&numberoflastpaydates=160
      GET https://my.adp.com/myadp_prefix/payroll/v1/workers/<AOID>/tax-statements

  The first answers ``payStatements[]`` of {payDate, netPayAmount,
  grossPayAmount, totalHours, payDetailUri, statementImageUri,
  payAdjustmentIndicator}. The second answers ``workerTaxStatements[]``
  of {statementID, statementName "2025 W-2", employerName, form.code,
  statementYear.year, statementUri, statementImageUri}. Each
  ``statementImageUri.href`` is a path under the same prefix and answers
  the PDF itself (``https://my.adp.com/myadp_prefix`` + href, 200,
  application/pdf). VERIFIED, 20 pay statements and one W-2.
* ``<AOID>`` is the worker's associate id, a 16-character token. The page
  knows it and leaves it in two places this app reads without asking
  anything: the addresses of the calls the page already made (the
  performance entries) and localStorage's
  ``myadp-dashboard_pay-dashboard-wfn`` record. VERIFIED.
* The older myADP list, ``/myadp_prefix/v1_0/O/A/payStatements``, also
  answers here without an id, but its image links did not, so the
  payroll/v1 services above are the ones used.
* **A tax statement needs an identity check first.** Pressing "View
  statement" on the Tax Statements card makes the page POST to
  ``/events/core/v1/step-up-myadp-pre-auth``, and ADP then asks the
  person to verify themselves. Until that is done the W-2's PDF address
  answers 403 with a message in ``resourceMessages`` saying so, while
  pay statements answer normally. Verified on two accounts, one of them
  a tester's (#46). This app never answers that check. It reads ADP's
  own words, asks the person to do it in the browser window that is
  already open, and tries again afterward. Asking too often gets the
  account blocked for the session ("too many unsuccessful attempts...
  you must log out and log back in"), so each tax statement is asked for
  once per run, and once blocked the rest are left for the next run.
  Nothing is typed into this app to answer the check. The app presses the
  card's own "View statement", which is what makes ADP show the prompt,
  and then watches the page: the viewer the page opens after a successful
  check fetches the PDF itself, and that answer is the document. So the
  person answers ADP in the browser and the run carries on by itself,
  which matters because the control panel gives an app no keyboard at all.
  One verification covers every tax statement in the session (two W-2s
  from two employers came down after one, verified 2026-09-22).

Discovery is those two calls. Capture is a fetch of each statement's own
PDF from inside the page. Nothing is clicked, and only my.adp.com and
workforcenow.adp.com are ever asked.

SAFETY (this is a payroll account that holds direct-deposit and tax
withholding settings):
  This module is strictly READ-ONLY. It reads two lists and fetches the
  PDFs ADP already generated. It must NEVER activate any control that
  changes direct deposit, tax withholding or a W-4, requests time off,
  edits a timecard, enrolls in a benefit, changes an address or a
  beneficiary, or edits any setting. FORBIDDEN_CONTROL_RE is the guard
  for the diagnostics and the repo-wide tests. There is no code here that
  clicks, submits a form or confirms a dialog.

Site layer verified working against the live site: 2026-09-21
"""

from __future__ import annotations

import base64
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from paperpull_core.controls import SETTINGS_CONTROL_RE, AUTH_CONTROL_RE

# Everything on its way into a diagnostic file goes through here. It
# lives in core because seventeen apps each had their own copy and
# they drifted into three different versions.
from paperpull_core.redact import redact, set_private_words  # noqa: F401
from paperpull_core.urls import is_safe_url as _host_allows
from paperpull_core.api_census import shape_of as _shape
from paperpull_core.dates import last_day as _last_day
# re-exported: this app's docs module calls it as site.set_download_dir
from paperpull_core.capture import set_download_dir  # noqa: F401
from paperpull_core.capture import snapshot as _snapshot
from paperpull_core.capture import take_new_pdf as _take_new_pdf
from paperpull_core.capture import fetch_pdf as _core_fetch_pdf
from paperpull_core.capture import take_new_tab as _core_take_new_tab
from paperpull_core.capture import take_same_tab as _core_take_same_tab
from paperpull_core.controls import control_texts as _control_texts
from paperpull_core.controls import second_step as _core_second_step
from paperpull_core.controls import controls_named as _controls_named
from paperpull_core.dates import checked as _checked_date
from paperpull_core.dates import full_year as _full_year

log = logging.getLogger("adp_docs.site")

BASE = "https://workforcenow.adp.com"
API_BASE = "https://my.adp.com/myadp_prefix"
# The Pay & Tax Statements page. Opening it is what makes the session
# call the statement services, which is how the worker id is learned.
BILLING_CANDIDATES = [
    f"{BASE}/theme/index.html#/Myself/PayandAnnualStatements",
]
# The worker's associate id, sixteen characters starting with G, as the
# page's own calls carry it.
AOID_RE = re.compile(r"/workers/(G[0-9A-Z]{15})(?:/|\?|$)")
PAY_STATEMENTS_PATH = "/payroll/v1/workers/{aoid}/pay-statements?adjustments=yes&numberoflastpaydates={n}"
TAX_STATEMENTS_PATH = "/payroll/v1/workers/{aoid}/tax-statements"
PAY_DATES_TO_ASK = 400
DOCS_API_RE = re.compile(r"/pay-statements|/tax-statements", re.I)
BILLING_URL = BILLING_CANDIDATES[0]
URLS = {
    "home": f"{BASE}/theme/index.html#/Myself",
    "login": "https://online.adp.com/signin/v1/?APPID=WFNPortal&productId=80e309c3-7085-bae1-e053-3505430b5495&returnURL=https://workforcenow.adp.com/&callingAppId=WFN",
    "documents": BILLING_URL,
    "statements": BILLING_URL,
}

LOGIN_URL_MARKERS = ["/login", "/signin", "/sign-in", "/auth/", "/mfa",
                     "/verification", "/challenge", "/authenticate"]

# ---------------------------------------------------------------------------
# HARD SAFETY GUARD. Tuned for a payroll portal. Never touch pay, tax,
# time, benefits or a setting.
# ---------------------------------------------------------------------------
FORBIDDEN_CONTROL_RE = re.compile(
    r"(direct\s+deposit|\bdeposit|withholding|\bw-?4\b|tax\s+(elections?|setup|withholding)|"
    r"\bpay\b(?!\s+(statements?|stubs?|history|date))|payment|\bwire\b|transfer|"
    r"time\s*off|\bpto\b|request\s+(time|leave)|timecard|time\s*card|clock\s+(in|out)|punch|"
    r"benefit|enroll|unenroll|open\s+enrollment|\bclaims?\b|dependent|beneficiar|"
    r"\bapply\b|sign\s+up|paperless|delivery\s+preference|consent|"
    r"enable|disable|change\b|edit\b|update\b|modify|manage\b|"
    r"set\s+up|delete|remove|cancel|submit|confirm|agree|accept|authorize|approve|"
    r"password|passcode|username|security\s+questions?|profile\b|settings|preferences|"
    r"contact\s+info|\baddress\b|phone|\bemail\b|emergency\s+contact|"
    r"\bchat\b|contact\s+us|help\s+desk|message\s+(hr|manager)|"
    r"performance|goals?\b|review\b|survey|acknowledge|\bsign\b(?!\s*in)|e-?sign|"
    r"\bloan\b|garnish|401\s*\(?k\)?|retirement|\bhsa\b|\bfsa\b|wisely|earned\s+wage|"
    r"myadp\s+wallet|\bcard\b|\bcards\b|activate|lock|unlock|\bpin\b)", re.I)

SAFE_DOC_CONTROL_RE = re.compile(
    r"(download|view|open|print|\bpdf\b|statement|\bstubs?\b|earnings|\bw-?2c?\b|1095|1099|"
    r"tax\s+(form|document|statement)|annual\s+statement|pay\s+(statement|stub|history|date)|"
    r"see\s+(more|all|older)|show\s+(more|all|older)|load\s+more|previous\s+years?|prior\s+years?)", re.I)

# A control that fetches one document. GUESS at the wording, wide on
# purpose. "View", "Download", "View PDF", "Statement", "1099-INT".
BILL_CONTROL_RE = re.compile(
    r"((download|view|print|open|get)\s*(my\s+|the\s+|this\s+|your\s+)?(statement|document|pdf|tax|letter|notice|1099|1098)|"
    r"(statement|document|tax\s+form|1099|1098|5498)\s*\(?\s*pdf\s*\)?|\bpdf\b|"
    r"^\s*(view|download|open)\s*$)", re.I)

# A link that points straight at a PDF, from a row's href.
PDF_HREF_RE = re.compile(r"\.pdf(\?|$)|/pdf\b|format=pdf|statement.*download|download.*statement|docId|documentId", re.I)

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

# ---------------------------------------------------------------------------
# Fallback selectors (used by --diagnose only)
# ---------------------------------------------------------------------------
FALLBACK = {
    "doc_row": ("table tbody tr, [role='row'], [class*='statement'], [class*='Statement'], "
                "li[class*='document'], [class*='document']"),
    "doc_link": "a[href*='.pdf'], a[download], button[class*='download']",
    "download_control": "a[download], a[href$='.pdf'], button:has-text('Download')",
    "page_ready": "table, [role='row'], [class*='statement'], main, [role='main']",
    "next_page": ("a[aria-label*='Next' i], button[aria-label*='Next' i], "
                  "[class*='next']"),
}

# ---------------------------------------------------------------------------
# Date parsing
# ---------------------------------------------------------------------------
DATE_PATTERNS = [
    (re.compile(r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
                r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|"
                r"Dec(?:ember)?)\.?\s+(\d{1,2}),?\s+(\d{4})", re.I), "mdY"),
    (re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b"), "mdy_slash"),
    (re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{2})\b"), "mdy_slash2"),
    (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"), "iso"),
]
_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
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
            if kind == "mdY":
                return f"{int(m.group(3)):04d}-{_MONTHS[m.group(1)[:3].lower()]:02d}-{int(m.group(2)):02d}"
            if kind == "mdy_slash":
                return f"{int(m.group(3)):04d}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
            if kind == "mdy_slash2":
                return f"{_full_year(m.group(3)):04d}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
            if kind == "iso":
                return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
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


_WORD_VALUE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_ -]{0,23}$")


def _plain_word(v: str) -> bool:
    """"STATEMENT", "LAST_90_DAYS", not an id, a token or a number."""
    return bool(_WORD_VALUE_RE.match(v)) and sum(ch.isdigit() for ch in v) <= 3


def _safe_query(url: str) -> str:
    """A URL's query parameters, names always, values only when they are
    plain words ("docType=STATEMENT", "range=LAST_90_DAYS"). A value with
    a digit, a token, an id, anything long, is "...". This is what a
    repair needs to make the same call with a wider filter, and nothing
    else."""
    from urllib.parse import urlsplit, parse_qsl
    try:
        pairs = parse_qsl(urlsplit(url).query, keep_blank_values=True)
    except ValueError:
        return ""
    out = []
    for k, v in pairs[:20]:
        out.append("%s=%s" % (k[:30], v if _plain_word(v) else "..."))
    return "&".join(out)

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
    """Names the passcode, CAPTCHA or throttling prompt on screen, or None.
    Visible text only. A page's source can carry every string its scripts
    could ever show, "verification code" included, on a normal day."""
    try:
        if _bill_controls(page).count() > 0:
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


# ---------------------------------------------------------------------------
# Downloads from a real Edge or Chrome attached over CDP. The browser saves
# the file itself, into its own Downloads folder, and Playwright's download
# event never fires. So the browser is pointed at a folder of ours and that
# folder is watched after every click. The Verizon app found this first.
# AT&T's fourth round found it again, with a trace that showed a clean
# click and nothing arriving.
# ---------------------------------------------------------------------------


def _take_new_tab(page, new_pages, out_path: Path) -> bool:
    """A PDF a click opened in a new tab. The core does the reading, this
    app's guard decides which addresses it may read."""
    return _core_take_new_tab(page, new_pages, out_path, is_safe_url)


# ---------------------------------------------------------------------------
# Billing page
# ---------------------------------------------------------------------------

def dismiss_overlay(page) -> None:
    """Close a cookie banner, a survey prompt or a promo overlay, the things
    that sit over signed-in pages and intercept clicks. Escape first, then
    only a control that says close or dismiss, never accept."""
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(250)
    except Exception:
        pass
    try:
        cl = page.get_by_role("button", name=re.compile(r"^(close|dismiss|no thanks|not now)\b", re.I))
        for i in range(min(cl.count(), 6)):
            el = cl.nth(i)
            try:
                if el.is_visible():
                    label = el.inner_text(timeout=500) or ""
                    if FORBIDDEN_CONTROL_RE.search(label):
                        continue
                    el.click(timeout=1000)
                    page.wait_for_timeout(250)
            except Exception:
                continue
    except Exception:
        pass


def _bill_controls(page):
    """Every control on the page whose name says it fetches a document.
    The words are this provider's, the rest is the core's."""
    return _controls_named(page, BILL_CONTROL_RE)


def _looks_like_billing(page) -> bool:
    try:
        if _bill_controls(page).count() > 0:
            return True
    except Exception:
        pass
    try:
        body = page.locator("body").inner_text(timeout=5000)
    except Exception:
        return False
    return bool(re.search(r"statements?\s+(and|&)\s+documents|statement\s+(period|date)|tax\s+documents",
                          body, re.I))


def goto_documents(page) -> bool:
    """Open the Pay & Tax Statements page and let it settle, which is
    when the shell calls the statement services and the worker id can be
    read. True unless the session is signed out."""
    if (page.url or "").split("#")[0] == BILLING_URL.split("#")[0] and "PayandAnnualStatements" in (page.url or "") \
            and not looks_signed_out(page) and _aoid_from_page(page):
        return True
    try:
        page.goto(BILLING_URL, wait_until="domcontentloaded", timeout=60000)
    except Exception as e:
        log.info("goto %s failed: %s", BILLING_URL, e)
        return False
    for _ in range(20):
        page.wait_for_timeout(1000)
        if looks_signed_out(page):
            return False
        if _aoid_from_page(page):
            break
    dismiss_overlay(page)
    return not looks_signed_out(page)


# ---------------------------------------------------------------------------
# The statement services
# ---------------------------------------------------------------------------

_AOID_JS = r"""() => {
  const rx = /\/workers\/(G[0-9A-Z]{15})(?:\/|\?|$)/;
  for (const e of performance.getEntriesByType('resource')) {
    const m = (e.name || '').match(rx);
    if (m) return m[1];
  }
  try {
    const raw = localStorage.getItem('myadp-dashboard_pay-dashboard-wfn');
    if (raw) { const j = JSON.parse(raw); if (j && /^G[0-9A-Z]{15}$/.test(j.aoid || '')) return j.aoid; }
  } catch (e) {}
  return null;
}"""


def _aoid_from_page(page) -> str:
    """The worker id the page already used, or ""."""
    try:
        return page.evaluate(_AOID_JS) or ""
    except Exception:
        return ""


def worker_id(page) -> str:
    """The signed-in worker's associate id, from the page's own calls."""
    aoid = _aoid_from_page(page)
    if not aoid and goto_documents(page):
        aoid = _aoid_from_page(page)
    return aoid


_FETCH_JSON_JS = r"""async (url) => {
  const res = await fetch(url, {credentials: 'include', headers: {Accept: 'application/json'}});
  const text = await res.text();
  let body = null;
  try { body = JSON.parse(text); } catch (e) {}
  return {status: res.status, body, size: text.length};
}"""


def _api_get(page, path: str):
    """One statement service, called from inside the signed-in page."""
    url = API_BASE + path
    if not is_safe_url(url):
        return None
    try:
        out = page.evaluate(_FETCH_JSON_JS, url) or {}
    except Exception as e:
        log.warning("statement service %s failed: %s", redact(path)[:80], e)
        return None
    if out.get("status") != 200:
        log.warning("statement service %s answered HTTP %s", redact(path)[:80], out.get("status"))
        return None
    return out.get("body")


def fetch_pay_statements(page, aoid: str) -> list:
    body = _api_get(page, PAY_STATEMENTS_PATH.format(aoid=aoid, n=PAY_DATES_TO_ASK))
    return list((body or {}).get("payStatements") or []) if isinstance(body, dict) else []


def fetch_tax_statements(page, aoid: str) -> list:
    body = _api_get(page, TAX_STATEMENTS_PATH.format(aoid=aoid))
    return list((body or {}).get("workerTaxStatements") or []) if isinstance(body, dict) else []


def _image_url(rec: dict) -> str:
    href = ((rec.get("statementImageUri") or {}).get("href") or "").strip()
    # One leading slash, a path under the prefix, nothing that could be a
    # host of its own.
    if not re.match(r"^/(?!/)[A-Za-z0-9_./~%-]+$", href):
        return ""
    url = API_BASE + href
    return url if is_safe_url(url) else ""


def pay_statement_doc(rec: dict) -> Optional[RawDoc]:
    """A RawDoc for one pay statement record. The title says adjustment
    when ADP does, so two statements on one pay date stay apart."""
    date = str(rec.get("payDate") or "")[:10]
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        return None
    title = "Pay Statement Adjustment" if rec.get("payAdjustmentIndicator") else "Pay Statement"
    return RawDoc(title=title, date_text=date, href=_image_url(rec), kind="statement")


# ADP prints an employer's name in capitals. A filename reads better
# without them, while LLC and its kind stay as they are written.
_KEEP_UPPER = {"LLC", "INC", "LP", "LLP", "PLLC", "LTD", "CO", "PC", "USA", "US", "NA", "LC", "PA"}


def tidy_employer(name: str) -> str:
    name = re.sub(r"[\s,]+", " ", str(name or "")).strip(" ,")
    if not name:
        return ""
    if not re.search(r"[a-z]", name):
        name = " ".join(w if w.strip(".") in _KEEP_UPPER else w.title() for w in name.split())
    return name[:28].strip()


def tax_statement_doc(rec: dict) -> Optional[RawDoc]:
    """A RawDoc for one tax statement. Dated at the tax year's end, and the
    employer's name kept in the title so two employers' forms stay apart."""
    year = str((rec.get("statementYear") or {}).get("year") or "")
    name = str(rec.get("statementName") or "").strip()
    form = str((rec.get("form") or {}).get("code") or "").strip()
    if not re.fullmatch(r"\d{4}", year):
        m = re.search(r"\b(20\d{2})\b", name)
        year = m.group(1) if m else ""
    if not year:
        return None
    title = name or f"{year} {form or 'Tax Statement'}"
    employer = re.sub(r"\s+", " ", str(rec.get("employerName") or "")).strip()
    if employer:
        title = f"{title} {employer}"
    # The employer rides along so the filename can carry it. Two employers
    # in one year would otherwise write the same name twice (#46).
    return RawDoc(title=title, date_text=f"{year}-12-31", href=_image_url(rec),
                  kind="tax", account=tidy_employer(employer))


class StepUpNotDone(Exception):
    """ADP asked the person to verify themselves and the answer never
    came. Carries ADP's own message."""


class TaxAccessBlocked(Exception):
    """ADP has blocked tax statements for this session after too many
    tries. Carries ADP's own message."""


# What ADP says when a tax statement needs the identity check, and when
# it has stopped accepting tries. Read out of the 403's own JSON.
_STEP_UP_MARKERS = ("stepup", "step-up", "step up", "verify your identity",
                    "identity verification", "verification code")
_BLOCKED_MARKERS = ("too many unsuccessful", "block_more_trans",
                    "to_many_unsuccessful", "too_many_unsuccessful")


def refusal_message(body: bytes):
    """(kind, message) from a refusal's JSON body, kind being "blocked",
    "step-up" or "". The message is ADP's own words, for the person."""
    try:
        data = json.loads(body.decode("utf-8", "replace"))
    except Exception:
        return "", ""
    texts, said = [], []

    def walk(o, key=""):
        if isinstance(o, dict):
            for k, v in o.items():
                if k in ("messageTxt", "message", "serviceDevMsg", "errorCode") and isinstance(v, str):
                    texts.append(v)
                    # Only what ADP wrote for the person is ever shown. Its
                    # developer message carries the masked email and phone
                    # the code could be sent to, which is theirs, not ours.
                    if key == "userMessage":
                        said.append(v)
                else:
                    walk(v, k)
        elif isinstance(o, list):
            for v in o:
                walk(v, key)
    walk(data)
    hay = " ".join(texts).lower()
    human = said[0] if said else ""
    if any(m in hay for m in _BLOCKED_MARKERS):
        return "blocked", human
    if any(m in hay for m in _STEP_UP_MARKERS):
        return "step-up", human
    return "", human


# Every document seen this run, by (date, title), so a download can find
# its PDF address without asking the services again. Beside the image
# address the statement's own address is kept, for a tax form whose
# image address does not answer (#46, the tester's 2023 W-2).
_PDF_BY_KEY: dict = {}
_STATEMENT_BY_KEY: dict = {}


def _statement_url(rec: dict) -> str:
    href = ((rec.get("statementUri") or {}).get("href") or "").strip()
    if not re.match(r"^/(?!/)[A-Za-z0-9_./~%-]+$", href):
        return ""
    url = API_BASE + href
    return url if is_safe_url(url) else ""


def scroll_full_page(page, rounds: int = 8, delay_ms: int = 600) -> None:
    try:
        for _ in range(rounds):
            page.mouse.wheel(0, 3000)
            page.wait_for_timeout(delay_ms)
        page.keyboard.press("End")
        page.wait_for_timeout(delay_ms)
    except Exception:
        pass


def expand_all(page) -> None:
    """Click 'See more' / 'Show more' / 'View older statements' repeatedly
    to surface anything the page loads on demand. The label is
    checked against the guard before every click."""
    pat = re.compile(r"^\s*(show|load|view|see)\s+(more|all|older)(\s+(bills?|statements?|documents?))?\s*$|"
                     r"^\s*(older|previous)\s+(bills?|statements?)\s*$", re.I)
    for _ in range(30):
        clicked = False
        for role in ("button", "link"):
            try:
                loc = page.get_by_role(role, name=pat)
                if loc.count() > 0 and loc.first.is_visible():
                    label = loc.first.inner_text(timeout=1000) or ""
                    if is_safe_control(label):
                        loc.first.click()
                        page.wait_for_timeout(1500)
                        clicked = True
                        break
            except Exception:
                continue
        if not clicked:
            break


@dataclass
class RawDoc:
    title: str
    account: str = ""
    date_text: str = ""
    href: str = ""
    text: str = ""
    row_index: int = -1
    kind: str = "doc"


# The date a bill control belongs to. The control's own name first, then
# the nearest enclosing row or card whose text carries a date, up to six
# levels up. Returned with the container's text so a repair can see what
# the row looked like.
_ROW_OF_JS = r"""el => {
  const dateRe = /(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}|\d{1,2}\/\d{1,2}\/\d{2,4}|\d{4}-\d{2}-\d{2}/i;
  let node = el, depth = 0;
  while (node && depth < 6) {
    const txt = (node.innerText || '').trim();
    if (dateRe.test(txt)) return txt.slice(0, 300);
    node = node.parentElement; depth++;
  }
  return '';
}"""


def collect_download_docs(page) -> List[RawDoc]:
    """Every pay statement and tax statement the services list. Nothing on
    the page is read or clicked."""
    aoid = worker_id(page)
    if not aoid:
        log.warning("could not learn the worker id from the page's own calls")
        return []
    docs: List[RawDoc] = []
    for rec in fetch_pay_statements(page, aoid):
        d = pay_statement_doc(rec) if isinstance(rec, dict) else None
        if d:
            docs.append(d)
    for rec in fetch_tax_statements(page, aoid):
        d = tax_statement_doc(rec) if isinstance(rec, dict) else None
        if d:
            docs.append(d)
            if _statement_url(rec):
                _STATEMENT_BY_KEY[(d.date_text, d.title)] = _statement_url(rec)
    for d in docs:
        if d.href:
            _PDF_BY_KEY[(d.date_text, d.title)] = d.href
            _PDF_BY_KEY.setdefault((d.date_text, ""), d.href)
    log.info("statement services: %d pay statement(s), %d tax statement(s)",
             sum(1 for d in docs if d.kind == "statement"), sum(1 for d in docs if d.kind == "tax"))
    return docs


def _control_for(page, iso: str):
    """The control for the document dated `iso`, matched the same way
    discovery found it, or None."""
    ctrls = _bill_controls(page)
    for i in range(ctrls.count()):
        el = ctrls.nth(i)
        try:
            name = (el.get_attribute("aria-label") or el.inner_text(timeout=800) or "").strip()
        except Exception:
            name = ""
        found = parse_date(name)
        if not found:
            try:
                found = parse_date(el.evaluate(_ROW_OF_JS) or "")
            except Exception:
                found = None
        if found == iso:
            return el, name
    return None, ""


def _fetch_pdf(page, href: str) -> Optional[bytes]:
    """A PDF link fetched from inside the signed-in page, cookies and all.
    The fetching is the core's, the hosts are this app's."""
    return _core_fetch_pdf(page, href, is_safe_url)


def _take_same_tab(page, start_url: str, out_path: Path, trace) -> bool:
    """A PDF the click opened in this very tab. The core does the reading,
    this app's guard decides which addresses it may read."""
    return _core_take_same_tab(page, start_url, out_path, trace, is_safe_url)


_SECOND_STEP_RE = re.compile(
    r"^\s*(download|download\s+(pdf|now|file|statement|document)|save|save\s+(as\s+)?pdf|"
    r"(regular|standard|full|detailed)\s+pdf|pdf|view\s*/\s*print\s+pdf|print|open\s+pdf)\s*$", re.I)


def _second_step(page, appeared: set):
    """A control the click revealed whose text says it finishes a download,
    once it has passed the guard, or None. The choosing is the core's, the
    words this provider uses and the guard are this app's."""
    return _core_second_step(page, appeared, _SECOND_STEP_RE, is_safe_control)


def _catch_pdf(page, el, label: str, out_path: Path, trace: Optional[list] = None,
               dl_dir=None) -> bool:
    """Click `el` and save whatever PDF the site produces, a file landing
    in `dl_dir`, a download event, a PDF response, a new tab, this tab
    moving to the document, or a second control the click revealed.
    `trace` collects what happened, the click's own outcome included."""
    ctx = page.context
    got: dict = {}
    downloads: list = []
    start_url = page.url or ""

    def on_download(dl):
        downloads.append(dl)

    def on_response(res):
        try:
            url = res.url or ""
            if not is_safe_url(url):
                return
            ct = (res.headers.get("content-type") or "").lower()
            if trace is not None and ("json" in ct or "pdf" in ct or "octet" in ct):
                trace.append({"status": res.status, "type": ct[:40], "url": redact(url)[:160]})
            if got:
                return
            if "pdf" in ct or "octet" in ct:
                try:
                    body = res.body()
                except Exception:
                    body = b""
                    got["refetch"] = url
                if body[:5] == b"%PDF-":
                    got["body"] = body
        except Exception:
            pass

    ctx.on("response", on_response)
    page.on("download", on_download)
    before = set(ctx.pages)
    seen = _snapshot(dl_dir)
    controls_before = _control_texts(page)

    def landed() -> bool:
        if downloads:
            try:
                from paperpull_core.receipt_pdf import save_download
                save_download(downloads[0], out_path)
                if out_path.exists() and out_path.read_bytes()[:5] == b"%PDF-":
                    return True
            except Exception as e:
                log.info("download event save failed: %s", e)
        if got.get("body"):
            out_path.write_bytes(got["body"])
            return True
        if got.get("refetch"):
            try:
                resp = page.context.request.get(got.pop("refetch"), timeout=60000)
                body = resp.body() if resp.ok else b""
                if body[:5] == b"%PDF-":
                    out_path.write_bytes(body)
                    return True
            except Exception:
                pass
        return _take_new_pdf(dl_dir, seen, out_path)

    def wait_for_pdf(seconds: int) -> bool:
        for _ in range(seconds):
            if landed():
                return True
            page.wait_for_timeout(1000)
        return landed()

    try:
        try:
            el.scroll_into_view_if_needed(timeout=4000)
        except Exception:
            pass
        try:
            el.click(timeout=8000)
            if trace is not None:
                trace.append({"note": "clicked", "control": label[:60]})
        except Exception as e:
            if trace is not None:
                trace.append({"note": "click failed", "control": label[:60], "error": str(e)[:160]})
            try:
                el.evaluate("el => el.click()")
                if trace is not None:
                    trace.append({"note": "clicked through the DOM instead", "control": label[:60]})
            except Exception as e2:
                if trace is not None:
                    trace.append({"note": "DOM click failed too", "error": str(e2)[:160]})
        if wait_for_pdf(10):
            return True
        if _take_same_tab(page, start_url, out_path, trace):
            return True
        if _take_new_tab(page, [p for p in ctx.pages if p not in before], out_path):
            return True
        appeared = _control_texts(page) - controls_before
        if trace is not None:
            trace.append({"note": "after the click", "url": redact(page.url or "")[:160],
                          "appeared": [redact(t) for t in sorted(appeared)[:15]],
                          "new_tabs": len([p for p in ctx.pages if p not in before])})
        step, step_label = _second_step(page, appeared)
        if step is not None:
            try:
                step.click(timeout=8000)
                if trace is not None:
                    trace.append({"note": "second step clicked", "control": step_label[:60]})
            except Exception as e:
                if trace is not None:
                    trace.append({"note": "second step click failed", "control": step_label[:60],
                                  "error": str(e)[:160]})
            if wait_for_pdf(20):
                return True
            if _take_same_tab(page, start_url, out_path, trace) or \
                    _take_new_tab(page, [p for p in ctx.pages if p not in before], out_path):
                return True
        if wait_for_pdf(15):
            return True
        if _take_new_tab(page, [p for p in ctx.pages if p not in before], out_path):
            return True
        log.info("click on %r produced no PDF", label)
        return False
    finally:
        try:
            ctx.remove_listener("response", on_response)
        except Exception:
            pass
        try:
            page.remove_listener("download", on_download)
        except Exception:
            pass
        for extra in [p for p in ctx.pages if p not in before]:
            try:
                extra.close()
            except Exception:
                pass


_FETCH_PDF_B64_JS = r"""async ([url, accept]) => {
  const res = await fetch(url, {credentials: 'include', headers: accept ? {Accept: accept} : {}});
  const buf = await res.arrayBuffer();
  const bytes = new Uint8Array(buf);
  let bin = '';
  for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  // The body comes back whether the answer was yes or no. A refusal's
  // own words are how this app knows ADP wants an identity check.
  return {status: res.status, type: res.headers.get('content-type') || '', size: bytes.length,
          head: String.fromCharCode.apply(null, bytes.subarray(0, 40)), b64: btoa(bin)};
}"""


LAST_REFUSAL: dict = {}


def fetch_statement_pdf(page, url: str, trace: Optional[list] = None, accept: str = "") -> Optional[bytes]:
    """The statement's PDF, fetched from inside the signed-in page the way
    the page's own viewer fetches it. None unless the answer is a PDF, and
    the answer's status, type and first bytes go in the trace either way,
    digits masked."""
    if not is_safe_url(url):
        return None
    try:
        out = page.evaluate(_FETCH_PDF_B64_JS, [url, accept]) or {}
        if trace is not None:
            trace.append({"note": "fetched", "url": redact(url)[:160], "accept": accept or "(none)",
                          "status": out.get("status"), "type": (out.get("type") or "")[:40],
                          "size": out.get("size"), "head": redact(str(out.get("head") or ""))[:40]})
        if out.get("b64"):
            data = base64.b64decode(out["b64"])
            if data[:5] == b"%PDF-":
                LAST_REFUSAL.clear()
                return data
            kind, human = refusal_message(data)
            if kind:
                LAST_REFUSAL.update({"kind": kind, "message": human})
                if trace is not None:
                    trace.append({"note": "ADP refused this document", "kind": kind, "message": human[:300]})
        log.info("statement PDF answered HTTP %s %s", out.get("status"), (out.get("type") or "")[:30])
    except Exception as e:
        log.info("in-page PDF fetch failed: %s", e)
        if trace is not None:
            trace.append({"note": "in-page fetch failed", "url": redact(url)[:160], "error": str(e)[:120]})
    return _fetch_pdf(page, url)


# The tax statement the page's own viewer fetched, caught as it passes.
_TAX_IMAGE_RE = re.compile(r"/tax-statements/[^/]+/images/", re.I)

STEP_UP_WAIT_SECONDS = 300


def wait_for_tax_access(page, url: str, trace: Optional[list] = None,
                        seconds: int = STEP_UP_WAIT_SECONDS) -> Optional[bytes]:
    """ADP has asked for an identity check. Press the tax card's own
    "View statement", which is what shows the prompt, then wait for the
    person to answer it in the browser. The viewer ADP opens afterward
    fetches the statement itself, and that answer is taken as it passes,
    so nothing is typed here and ADP is asked at most once more."""
    ctx = page.context
    caught: dict = {}

    def on_response(res):
        try:
            if caught or not is_safe_url(res.url or "") or not _TAX_IMAGE_RE.search(res.url or ""):
                return
            if "pdf" not in (res.headers.get("content-type") or "").lower():
                return
            body = res.body()
            if body[:5] == b"%PDF-":
                caught["body"] = body
        except Exception:
            pass

    ctx.on("response", on_response)
    try:
        print("\n  >> ADP is showing a security prompt in your browser RIGHT NOW. <<")
        print("  Do not close or dismiss it. It is the identity check ADP asks for")
        print("  before it hands over a tax form, and it is asking how to send you")
        print("  a security code. Choose text, email or a call, then type the code")
        print("  into that window.")
        print("  Nothing needs typing here. This run carries on by itself the moment")
        print("  ADP accepts the code, and waits up to %d minutes for it." % (seconds // 60))
        print("  If the prompt is dismissed or ignored, ADP hands over no tax forms")
        print("  until you sign out of ADP and sign in again. Your pay statements are")
        print("  already saved by this point, so nothing else is held up.")
        if not open_tax_statement_check(page):
            print("  (Could not press the card's View statement, so open the Tax")
            print("   Statements card yourself and press View statement there.)")
        for waited in range(seconds):
            page.wait_for_timeout(1000)
            if caught:
                print("  Verified. The tax statement came down with the page's own viewer.")
                if trace is not None:
                    trace.append({"note": "the page's viewer fetched the statement after the check"})
                return caught["body"]
            if waited and waited % 60 == 0:
                print("  ... still waiting for ADP to accept the code (%d min)" % (waited // 60))
        # The viewer may have opened without this catching it, so ADP is
        # asked once, and only once, before giving up.
        if not step_up_pending(page):
            body = fetch_statement_pdf(page, url, trace)
            if body:
                return body
        if trace is not None:
            trace.append({"note": "the identity check was not completed in time"})
    finally:
        try:
            ctx.remove_listener("response", on_response)
        except Exception:
            pass
    return None


_STEP_UP_ON_PAGE_RE = re.compile(
    r"authorize\s+this\s+transaction|how\s+you\s+want\s+to\s+receive\s+your\s+security\s+code|"
    r"send\s+me\s+(a\s+text|an\s+email)|enter\s+the\s+(security\s+)?code", re.I)


def step_up_pending(page) -> bool:
    """True while ADP's own verification prompt is still on the page."""
    try:
        return bool(_STEP_UP_ON_PAGE_RE.search(page.locator("body").inner_text(timeout=5000)))
    except Exception:
        return False


def open_tax_statement_check(page) -> bool:
    """Press the Tax Statements card's own "View statement", which is
    what starts ADP's identity check, so the person can answer it in the
    window that is already open. The control has passed the guard. True
    when it was pressed."""
    try:
        if not goto_documents(page):
            return False
        pressed = page.evaluate(r"""() => {
          const found = [];
          const walk = (root) => {
            for (const e of root.querySelectorAll('*')) {
              if (e.shadowRoot) walk(e.shadowRoot);
              const t = (e.innerText || '').trim();
              if ((e.tagName === 'SDF-BUTTON' || e.tagName === 'BUTTON') && /^\s*view statement\s*$/i.test(t)) found.push(e);
            }
          };
          walk(document);
          const el = found[found.length - 1];
          if (!el) return false;
          el.scrollIntoView({block: 'center'});
          el.click();
          return true;
        }""")
        return bool(pressed)
    except Exception as e:
        log.info("could not open the tax statement check: %s", e)
        return False


def _pdf_addresses(key, iso_date: str) -> list:
    """Every address worth asking for this document's PDF, the image
    address first, then the same path on the bare host, then the
    statement's own address asked for as a PDF."""
    out = []
    img = _PDF_BY_KEY.get(key) or _PDF_BY_KEY.get((iso_date, ""))
    if img:
        out.append((img, ""))
    # A tax statement is asked for at ONE address and no other. ADP counts
    # every refusal against the account and blocks it after a few, and a
    # refusal there means an identity check is due, not a wrong address
    # (#46). A pay statement has no such check, so a second address is
    # worth trying if the first says nothing useful.
    if key in _STATEMENT_BY_KEY:
        return out
    if img and img.startswith(API_BASE):
        out.append(("https://my.adp.com" + img[len(API_BASE):], ""))
    return out


def download_bill(page, dl_dir, iso_date: str, out_path, title: str = "",
                  trace: Optional[list] = None) -> bool:
    """Save the document dated `iso_date` with this `title`. Its PDF
    address comes from the statement services, remembered from discovery
    or asked for again, and is fetched from inside the page. No control
    is clicked."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    key = (iso_date, title or "")
    addresses = _pdf_addresses(key, iso_date)
    if not addresses:
        if not goto_documents(page):
            if trace is not None:
                trace.append({"note": "statements page not reached"})
            return False
        collect_download_docs(page)
        addresses = _pdf_addresses(key, iso_date)
    if not addresses:
        log.info("no statement listed for %s %r", iso_date, title)
        if trace is not None:
            trace.append({"note": "the statement services list nothing for this date", "date": iso_date})
        return False
    LAST_REFUSAL.clear()
    for url, accept in addresses:
        body = fetch_statement_pdf(page, url, trace, accept)
        if body:
            return _written(out_path, body)
        # A refusal is ADP speaking, not an address to keep guessing at.
        kind = LAST_REFUSAL.get("kind")
        if kind == "blocked":
            raise TaxAccessBlocked(LAST_REFUSAL.get("message", ""))
        if kind == "step-up":
            message = LAST_REFUSAL.get("message", "")
            body = wait_for_tax_access(page, url, trace)
            if body:
                return _written(out_path, body)
            raise StepUpNotDone(message)
    if trace is not None:
        trace.append({"note": "none of the statement's addresses answered with a PDF", "tried": len(addresses)})
    return False


def _written(out_path: Path, body: bytes) -> bool:
    out_path.write_bytes(body)
    return True


# ---------------------------------------------------------------------------
# Diagnose. A survey a tester can attach to an issue. No screenshot, since a
# signed-in page shows names, numbers and amounts. Digit runs are masked and
# JSON bodies are recorded as shape only.
# ---------------------------------------------------------------------------
_ROW_JS = r"""() => {
  const out = [];
  for (const tr of document.querySelectorAll('table tr, [role=row], li, [class*="bill" i]')) {
    const txt = (tr.innerText || '').trim();
    if (!txt) continue;
    const link = tr.querySelector("a[href]");
    out.push({text: txt.slice(0, 200), href: link ? link.getAttribute('href') : ''});
  }
  return out.slice(0, 200);
}"""

SURVEY_LINK_RE = re.compile(
    r"^\s*((see|view|show)\s+)?(pay(\s+(and|&)\s+annual)?\s+statements?|pay\s+stubs?|"
    r"annual\s+statements?|tax\s+(statements?|forms?|documents?)|\bw-?2s?\b|"
    r"statements?|earnings\s+statements?|pay\s+history|myself)\s*$", re.I)


def collect_documents(page) -> List[RawDoc]:
    """Loose row scrape used only by --diagnose. Every row that carries a
    date, a link or the word download, with digits masked."""
    docs: List[RawDoc] = []
    seen = set()
    try:
        rows = page.evaluate(_ROW_JS)
    except Exception:
        rows = []
    for i, r in enumerate(rows):
        text = redact((r.get("text") or "").strip())
        if not text:
            continue
        has_date = parse_date(text) or MONTH_YEAR_RE.search(text)
        href = redact(r.get("href", "") or "")
        if not (has_date or href or "download" in text.lower()):
            continue
        title = text.splitlines()[0][:200]
        date_text = next((ln for ln in text.splitlines()
                          if parse_date(ln) or MONTH_YEAR_RE.search(ln)), "")
        key = (title, date_text, href, text[:60])
        if key in seen:
            continue
        seen.add(key)
        docs.append(RawDoc(title=re.sub(r"\s+", " ", title), date_text=date_text,
                           href=href, text=text[:400], row_index=i))
    # A row with a date is a document row, and those are what a repair
    # wants to see first, ahead of a nav full of links.
    docs.sort(key=lambda d: 0 if d.date_text else 1)
    return docs


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
            for i in range(min(loc.count(), 100)):
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
                                 "bill": bool(BILL_CONTROL_RE.search(text)),
                                 "survey": bool(SURVEY_LINK_RE.match(text.strip()))})
        except Exception:
            pass
    out["controls"] = controls
    out["bill_controls"] = sum(1 for c in controls if c["bill"])
    return out


def survey(page, dwell_ms: int = 4000, max_follow: int = 6) -> dict:
    """What the signed-in documents area looks like, without downloading
    anything. Records each page, its headings and controls with the
    guard's verdict on each, and every JSON or PDF response adp.com sends
    while the page settles. Then follows, one at a time and back again,
    the few links whose text is a documents word. No screenshot."""
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
            try:
                entry["method"] = res.request.method
                body = res.request.post_data or ""
                if body.lstrip().startswith("{"):
                    import json as _json
                    parsed = _json.loads(body)
                    if isinstance(parsed, dict):
                        entry["post_keys"] = sorted(str(k) for k in parsed)[:30]
            except Exception:
                pass
            q = _safe_query(url)
            if q:
                entry["query"] = q[:240]
            if "json" in ct:
                try:
                    entry["shape"] = _shape(res.json())
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
            if followed >= max_follow or c["role"] not in ("link", "button") or not c["survey"]:
                continue
            if not is_safe_control(c["text"]):
                continue
            try:
                link = page.get_by_role(c["role"], name=re.compile(
                    "^" + re.escape(c["text"].replace("#", "")) + "$", re.I)).first
                if link.count() == 0:
                    continue
                before = page.url
                tabs_before = set(page.context.pages)
                link.click(timeout=5000)
                page.wait_for_timeout(dwell_ms)
                # A control that opened a new tab (a document vendor behind
                # a single sign-on, a PDF) is surveyed there, then the tab
                # is closed. Off the provider's hosts it is still recorded,
                # marked, and nothing on it is followed.
                for extra in [p for p in page.context.pages if p not in tabs_before]:
                    try:
                        extra.wait_for_load_state("domcontentloaded", timeout=15000)
                        tab = _page_summary(extra)
                        tab["opened_tab_from"] = c["text"]
                        tab["off_host"] = not is_safe_url(extra.url or "")
                        report["pages"].append(tab)
                    except Exception as e:
                        report.setdefault("notes", []).append(
                            "could not read the tab %r opened: %s" % (c["text"], str(e)[:120]))
                    try:
                        extra.close()
                    except Exception:
                        pass
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


# ---------------------------------------------------------------------------
# Host allowlist. Parsed, never a string prefix, so a lookalike host cannot
# walk through.
# ---------------------------------------------------------------------------
ALLOWED_HOSTS = {"adp.com"}


def is_safe_url(url: str) -> bool:
    """True only for an https URL on one of this provider's own hosts.

    The check itself lives in the core, so all of them answer the same way.
    This app keeps the hosts, which is the part that really is its own."""
    return _host_allows(url, ALLOWED_HOSTS)
