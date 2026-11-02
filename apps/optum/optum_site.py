"""ALL optumbank.com selectors, URLs, and page behavior live here.

When Optum Bank changes its site, repair this file only.

STATUS: mapped against a signed-in account on 2026-10-09, read-only, with no
control pressed. Everything this app takes is a plain link on the member
site, account.optumbank.com, served inline as a PDF (200, application/pdf,
no redirect), so NOTHING IS EVER CLICKED HERE:

  * Forms & documents (/account/help/forms) carries "Download latest
    statement", a link into /account/products/<product>/statements/<id>.pdf,
    which is how the product ids are learned.
  * Each product's statements page (/account/products/<product>/statements)
    lists the six newest statements as links whose text is the statement
    date, 2026-08-31, and the older ones as the options of a <select
    name="document_id"> whose text is the date and whose value is the PDF
    path. Both are read; the select is never changed and its Download
    button never pressed. The tax documents it lists are links into
    /account/products/<product>/tax_documents/<id>.pdf, titled by Optum
    ("Rendered EOY 5498-SA Notices-2025"); the 1099-SA appears there in a
    year with distributions.
  * A document is fetched by GET of its own path with the session's cookies,
    no redirect followed, only when host and path match exactly.

Sign-in is HealthSafe ID (healthsafe-id.com, onehealthcareid.com). Those
identity hosts are never allowed hosts, never download hosts: a tab that
lands on one reads as signed out and the run stops for the account holder.

SAFETY (this is a health savings account that can pay bills and move money):
  This module is strictly READ-ONLY. It presses nothing. It must NEVER
  activate any control that pays a bill or provider, reimburses,
  contributes, invests, trades, sells, transfers, rolls over, distributes,
  orders or activates a card, files or edits a claim, adds a payee, bank
  account or beneficiary, or edits any setting. FORBIDDEN_CONTROL_RE is the
  guard kept for the survey's verdicts and for any future repair that
  reaches for a control; a control must ALSO look like a document action
  (SAFE_DOC_CONTROL_RE), and the shared core guards are consulted every
  time. There is no code here that closes a banner, submits a form or
  confirms a dialog.

HOSTS: exact, no subdomain wildcard. account.optumbank.com for the
landing, the forms page and each product's statements page, every one
opened by an address this module builds, and for a document's own PDF
path, the only path a document is ever fetched from (is_download_url).
www.optumbank.com only for the sign-in landing.

KNOWN CEILINGS (ponytail: left as they are until a run shows otherwise)
  * Investment earnings reports and contribution summaries on Forms &
    documents are not read; statements and tax forms are the scope.
  * More than one product has not been seen. Product ids are read only
    from links that lead to a product's statements, and a product whose
    statements page says outright that it has none (NO_STATEMENTS_RE, a
    guess at the wording) is read as empty. A page that shows nothing and
    says nothing still stops the list.
  * A tax document is dated December 31 of the last year its title names.
    One whose title names no year stops the list, since its date could
    only be guessed and the download's check (same path, title AND date)
    would never find it again. None exists on the account this was built
    on.
"""
from __future__ import annotations

import logging
import re
import sys
from dataclasses import dataclass
from datetime import date as _date
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import urlsplit

from paperpull_core import intake
from paperpull_core.controls import SETTINGS_CONTROL_RE, AUTH_CONTROL_RE
from paperpull_core.redact import redact, set_private_words  # noqa: F401  (re-exported)
from paperpull_core.urls import is_safe_url as _host_allows
from paperpull_core.dates import last_day as _last_day
from paperpull_core.dates import checked as _checked_date
from paperpull_core.dates import full_year as _full_year
# re-exported: the docs module calls it as site.set_download_dir
from paperpull_core.capture import set_download_dir  # noqa: F401
from paperpull_core.words import words_for as _words_for

log = logging.getLogger("optum_docs.site")


def _words():
    """This app's own words for paperpull_core.words."""
    return _words_for("Optum Bank", sys.modules[__name__])


# ---------------------------------------------------------------------------
# Addresses
# ---------------------------------------------------------------------------
HOME = "https://www.optumbank.com"
BASE = "https://account.optumbank.com"
FORMS_URL = f"{BASE}/account/help/forms"
STATEMENTS_URL = FORMS_URL          # discovery starts here; each product's page follows
TAX_URL = FORMS_URL
BILLING_URL = FORMS_URL
URLS = {
    "home": f"{HOME}/",
    "login": f"{HOME}/",
    "documents": FORMS_URL,
    "statements": FORMS_URL,
    "tax": FORMS_URL,
}

LOGIN_URL_MARKERS = ["/signin", "/sign-in", "/login", "/oauth", "/mfa", "/verify",
                     "/verification", "/challenge", "/sso", "/authorize",
                     "healthsafe-id.com", "onehealthcareid.com", "identity."]

# ---------------------------------------------------------------------------
# HARD SAFETY GUARD. Tuned for an HSA. Every verb stem anchored on both
# sides so "Statements" is not "state" and "Downloads" is not "load".
# ---------------------------------------------------------------------------
FORBIDDEN_CONTROL_RE = re.compile(
    r"(\bpay\b|\bpaying\b|\bpayments?\b|pay\s+(a\s+)?(bill|provider|myself)|\breimburs(e|es|ed|ing|ement)\b|"
    r"\bcontribut(e|es|ed|ing|ion|ions)\b|\binvest(s|ed|ing|ment|ments)?\b|\btrad(e|es|ed|ing)\b|"
    r"\bbuy\b|\bsell\b|\brebalance\b|\btransfer(s|red|ring)?\b|\bwithdraw(al|als|s)?\b|\bdeposit(s|ed)?\b|"
    r"\bmove\s+money\b|\badd\s+(money|funds|a\s+bank|payee|beneficiar)|\bbank\s+account\b|\brouting\b|"
    r"\bcard\b|\bcards\b|\bactivate\b|\border\b|\bpin\b|\bclaims?\b|\bfile\s+a\b|\bexpense\b|\breceipt\s+vault\b|"
    r"\bbeneficiar(y|ies)\b|\bpayee\b|\bautopay\b|\bauto\s*-?\s*pay\b|\brecurring\b|\bschedul(e|es|ed|ing)\b|"
    r"\benroll|\bunenroll|\bsign\s*up\b|\bpaperless\b|\bgo\s+paperless\b|\bdelivery\s+preferences?\b|"
    r"\brequest(s|ed|ing)?\b|\bsubmit\b|\bconfirm\b|\bagree\b|\baccept\b|\bauthori[sz]e\b|\bcontinue\b|"
    r"\bapprov(e|es|ed|ing|al)\b|\bverify\b|\bidentity\b|\bpassword\b|\busername\b|\bsecurity\b|"
    r"\bsettings?\b|\bprofile\b|\bpreferences?\b|\benabl(e|es|ed|ing)\b|\bdisabl(e|es|ed|ing)\b|"
    r"\bchang(e|es|ed|ing)\b|\bedit(s|ed|ing)?\b|\bupdat(e|es|ed|ing)\b|\bdelet(e|es|ed|ing)\b|"
    r"\bremov(e|es|ed|ing)\b|\bcancel\b|\bclose\b|\bexport\b|\bemail\b|\bshare\b|\bchat\b|\bcontact\b|"
    r"\bmessage\b|\bupload\b|\bgenerat(e|es|ed|ing)\b|\bcreat(e|es|ed|ing)\b|\bcustom\b|\bupgrade\b|"
    r"\brollover\b|\broll\s+over\b|\bdistribut(e|es|ed|ing|ion|ions)\b|\bdisburs(e|es|ed|ing|ement|ements)\b|"
    r"\bspend(ing)?\b|\buse\s+(your\s+)?funds\b|\bsend\s+money\b|\bsend\b|\bredeposit\b|\bcorrection\b|\bclosure\b|"
    r"\bname\s+change\b|\binformation\s+release\b|\bdirect\s+deposit\b|\bcsv\b|\bquicken\b)", re.I)

SAFE_DOC_CONTROL_RE = re.compile(
    r"(\bdownload\b|\bview\b|\bopen\b|\bprint\b|\bpdf\b|\bstatements?\b|\bdocuments?\b|"
    r"\btax\b|\b1099\b|\b5498\b|\bform\b|\bhistory\b|"
    r"see\s+(more|all|older)|show\s+(more|all|older)|load\s+more|"
    r"(next|previous|first|last)\s+page|go\s+to\s+(first|last)\s+page)", re.I)

# A control that fetches one document, for the survey.
BILL_CONTROL_RE = re.compile(r"(^\s*download\b|^\s*pdf\b|\b1099\b|\b5498\b|\bview\s+statement\b)", re.I)

SECURITY_CHALLENGE_MARKERS = [
    "enter the code", "verification code", "6-digit", "7-digit", "two-factor",
    "two-step", "authenticator", "confirm your identity", "verify your identity",
    "we sent a code", "device approval", "approve this login",
    "are you a robot", "captcha", "let's verify", "check your email",
    "check your phone", "your session has expired", "log back in",
    "access denied",
]

RATE_LIMIT_MARKERS = [
    "too many requests", "rate limit", "try again later",
    "temporarily unavailable", "http error 429", "unusual traffic",
]

# Fallback selectors (used by --diagnose only). Generic until the survey.
FALLBACK = {
    "doc_row": "main table tr, main [role='row'], main li",
    "doc_link": "a[href*='statement' i], a[href*='document' i], a[href$='.pdf']",
    "download_control": "button:has-text('Download'), a[download], a:has-text('PDF')",
    "page_ready": "main",
    "next_page": "button[aria-label*='next' i], a[aria-label*='next' i]",
}

# ---------------------------------------------------------------------------
# Date parsing (verbatim from the Nelnet app)
# ---------------------------------------------------------------------------
DATE_PATTERNS = [
    (re.compile(r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
                r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|"
                r"Dec(?:ember)?)\.?\s+(\d{1,2}),?\s+(\d{4})", re.I), "mdY"),
    (re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b"), "mdy_slash"),
    (re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{2})\b"), "mdy_slash2"),
    (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})(?!\d)"), "iso"),
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


# ---------------------------------------------------------------------------
# Session / safety
# ---------------------------------------------------------------------------

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
    Visible text only. A page that shows a statement row is not a
    challenge, whatever its text says further down."""
    try:
        if page.locator(FALLBACK["doc_row"]).count() > 0:
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
    """Deny by default: an unreadable label is refused, then this app's
    blocklist, then the shared core guards, and only then the document
    allowlist."""
    name = re.sub(r"\s+", " ", name or "").strip()
    if not name:
        return False
    if FORBIDDEN_CONTROL_RE.search(name):
        return False
    if SETTINGS_CONTROL_RE.search(name) or AUTH_CONTROL_RE.search(name):
        return False
    return bool(SAFE_DOC_CONTROL_RE.search(name))


# ---------------------------------------------------------------------------
# Hosts. Exact, parsed, no subdomain wildcard, and a document only from its
# own path on the member host. Identity hosts are in neither set.
# ---------------------------------------------------------------------------
ALLOWED_HOSTS = {"account.optumbank.com", "www.optumbank.com"}
DOWNLOAD_HOSTS = {"account.optumbank.com"}
DOCUMENT_PATH_RE = re.compile(r"^/account/products/(\d+)/(statements|tax_documents)/(\d+)\.pdf$")
PRODUCT_RE = re.compile(r"/account/products/(\d+)(?:/|$)")
# A link that leads to a product's statements, its statements page or one
# of its statements. Only these name a product this app reads.
STATEMENTS_LINK_RE = re.compile(r"^/account/products/(\d+)/statements(?:/\d+\.pdf)?/?$")


def is_safe_url(url: str) -> bool:
    """True only for an https URL on exactly one of this provider's hosts.
    The pages this app opens are named in full by goto_documents and
    _goto_statements, and a document is fetched only through
    is_download_url, which holds the path too."""
    return _host_allows(url, ALLOWED_HOSTS, subdomains=False)


def is_download_url(url: str) -> bool:
    """True only for a document's own PDF path on exactly the member host."""
    if not _host_allows(url, DOWNLOAD_HOSTS, subdomains=False):
        return False
    try:
        return bool(DOCUMENT_PATH_RE.match(urlsplit(url).path or ""))
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# Documents. Read from links and a select's options; nothing is pressed.
# ---------------------------------------------------------------------------

@dataclass
class RawDoc:
    title: str
    account: str = ""
    date_text: str = ""
    href: str = ""
    text: str = ""
    row_index: int = -1
    kind: str = "doc"
    # Empty unless Optum lists a second form under one title, which is then
    # known by its own id (documents_of).
    document_id: str = ""


class ListStopped(Exception):
    """The list has a part this could not read, so what was read is not all
    of it. `docs` holds what was read before it stopped."""

    def __init__(self, why: str, docs=None):
        super().__init__(why)
        self.docs = list(docs or [])


_ISO_RE = re.compile(r"^(?:19|20)\d{2}-\d{2}-\d{2}$")


def valid_iso(text: str) -> bool:
    """A real calendar date written YYYY-MM-DD. "2026-02-30" has the shape
    and is not one, and a statement so dated would be recorded and never
    matched again, so it stops the list instead."""
    t = (text or "").strip()
    if not _ISO_RE.match(t):
        return False
    try:
        return _date.fromisoformat(t).isoformat() == t
    except ValueError:
        return False
_TAX_YEAR_RE = re.compile(r"\b((?:19|20)\d{2})\b")

# Every link and every option of the statements page that points at a
# document path, read without pressing anything.
_DOC_ENTRIES_JS = r"""() => {
  const out = [];
  for (const a of document.querySelectorAll('a[href]'))
    out.push({text: (a.innerText || a.getAttribute('aria-label') || '').replace(/\s+/g, ' ').trim(),
              path: new URL(a.href, location.href).pathname, host: new URL(a.href, location.href).hostname, how: 'link'});
  for (const s of document.querySelectorAll('select[name="document_id"]'))
    for (const o of s.options)
      out.push({text: (o.text || '').replace(/\s+/g, ' ').trim(), path: o.value, host: location.hostname, how: 'option'});
  return out;
}"""


def _wait_for_forms(page, timeout_ms: int = 30000) -> bool:
    """Wait for the forms page's own link to a product's statements, its
    "Download latest statement". A link into a product alone is the site's
    menu, which draws on every signed-in page."""
    try:
        page.wait_for_selector("a[href*='/account/products/'][href*='/statements']", timeout=timeout_ms)
        return True
    except Exception:
        return False


def goto_documents(page) -> bool:
    """Open Forms & documents by its address. No click, no banner handling."""
    here = page.url or ""
    if PRODUCT_RE.search(urlsplit(here).path or "") is None and here.split("?")[0].rstrip("/").endswith("/forms") \
            and is_safe_url(here) and not looks_signed_out(page) and _wait_for_forms(page, 5000):
        return True
    try:
        page.goto(FORMS_URL, wait_until="domcontentloaded", timeout=60000)
    except Exception as e:
        log.info("goto the forms page failed (%s)", type(e).__name__)
        return False
    if looks_signed_out(page):
        return False
    if not is_safe_url(page.url or ""):
        # goto follows redirects; wherever the browser settled has to be an
        # address this app may be at, or nothing is read there.
        log.info("the forms page settled off this app's addresses")
        return False
    return _wait_for_forms(page)


def forms_page_links_statements(page) -> bool:
    """Whether the Forms & documents page opened and its own content links
    a product's latest statement, which only a signed-in page shows. A link
    to a product's statements page may be the site's menu, so only a link
    to a statement's own PDF counts."""
    if not goto_documents(page):
        return False
    try:
        page.wait_for_selector("a[href*='/account/products/'][href*='/statements/'][href$='.pdf']",
                               timeout=15000)
    except Exception:
        return False
    for e in _entries(page):
        m = DOCUMENT_PATH_RE.match(e.get("path") or "")
        if m and m.group(2) == "statements" and e.get("how") == "link" and (e.get("host") or "") == "account.optumbank.com":
            return True
    return False


def scroll_full_page(page, rounds: int = 8, delay_ms: int = 600) -> None:
    try:
        for _ in range(rounds):
            page.mouse.wheel(0, 3000)
            page.wait_for_timeout(delay_ms)
    except Exception:
        pass


def expand_all(page) -> None:
    """Nothing to press: the older statements are a select's options, read
    as they are."""
    return None


def _entries(page) -> list:
    try:
        return page.evaluate(_DOC_ENTRIES_JS) or []
    except Exception:
        return []


def product_ids(entries: list) -> List[str]:
    """Every product id named by a link that leads to that product's
    statements, in the order first seen. A link to a product's overview or
    its settings names a product too, and one with no statements, an FSA,
    an HRA or an investment account, would then have stopped every
    Discover at a statements page it does not have."""
    out: List[str] = []
    for e in entries:
        if e.get("how") != "link" or (e.get("host") or "") != "account.optumbank.com":
            continue
        m = STATEMENTS_LINK_RE.match(e.get("path") or "")
        if m and m.group(1) not in out:
            out.append(m.group(1))
    return out


# What a product's statements page says when it has none. Only a sentence
# that says so outright counts, never a page that merely shows nothing, and
# never one that begins "if" or "when", as help text does. Not yet seen on a
# real account (KNOWN CEILINGS).
NO_STATEMENTS_RE = re.compile(
    r"(?<!\bif )(?<!\bwhen )\b(?:you\s+(?:have\s+no|do\s+not\s+have\s+any|don'?t\s+have\s+any)\s+statements"
    r"|there\s+are\s+no\s+statements"
    r"|no\s+statements\s+(?:are\s+)?(?:available|to\s+(?:show|display)|yet|found))\b", re.I)


def says_no_statements(page) -> bool:
    """True only when the page's own text says the product has no
    statements."""
    try:
        text = page.locator("body").inner_text(timeout=5000) or ""
    except Exception:
        return False
    return bool(NO_STATEMENTS_RE.search(text))


def _names_a_date(text: str) -> bool:
    """Whether an option's text names a date or a year at all."""
    return bool(_TAX_YEAR_RE.search(text or "") or parse_date(text or ""))


def document_id_of(path: str) -> str:
    """The id a document's own path ends in, or an empty string."""
    m = DOCUMENT_PATH_RE.match(path or "")
    return m.group(3) if m else ""


def documents_of(entries: list, pid: str) -> List[RawDoc]:
    """RawDocs for product `pid` from one statements page's entries, a
    statement per distinct date and a tax document per link, each carrying
    the product id as its account. That is part of a document's identity
    whether the forms page links one product or several, so a second
    product appearing later changes nothing about the first one's documents.
    A statement whose text is not a date, two statements with one date, or
    a document path on another host or another product stops the list.

    A tax form linked twice is one form. Two forms under one title, a
    corrected 5498-SA beside the one it corrects, are two. The first keeps
    the key a form of that title always had and the next is known by its
    own id, so neither is dropped and neither is fetched as the other
    (optum_docs.hold_known_forms says which one is the first)."""
    docs: List[RawDoc] = []
    seen_dates: dict = {}
    tax_paths: set = set()
    tax_titles: dict = {}
    for e in entries:
        m = DOCUMENT_PATH_RE.match(e.get("path") or "")
        if not m:
            if e.get("how") == "option":
                value = e.get("path") or ""
                if not value and not _names_a_date(e.get("text") or ""):
                    # A placeholder such as "Select a statement", enabled or
                    # not, with no value and no date.
                    continue
                # A dated option with no value is a statement with no path,
                # and a value that is not a document path, an absolute
                # address, a query or a changed value, cannot be read. Either
                # is a list this cannot read. The page's own words stay out
                # of what is said, since it is printed and logged.
                raise ListStopped("a statement option carries a value this cannot read" if value
                                  else "a dated statement option carries no value")
            continue
        if (e.get("host") or "") != "account.optumbank.com":
            raise ListStopped("a document link points off the member host")
        if m.group(1) != pid:
            raise ListStopped("a document link names another product")
        text = (e.get("text") or "").strip()
        if m.group(2) == "statements":
            if not valid_iso(text):
                raise ListStopped("a statement's date is not a calendar date")
            if text in seen_dates:
                if seen_dates[text] != e["path"]:
                    raise ListStopped("two statements read %s" % text)
                continue   # the same statement, linked and listed as an option
            seen_dates[text] = e["path"]
            title = f"HSA Statement {text}"
            docs.append(RawDoc(title=title, account=pid, date_text=text, href=e["path"],
                               text=f"Optum Bank {title}", row_index=len(docs), kind="statement"))
        else:
            if e["path"] in tax_paths:
                continue   # the same form, linked twice
            tax_paths.add(e["path"])
            if not text:
                raise ListStopped("a tax document link has no title")
            years = _TAX_YEAR_RE.findall(text)
            if not years:
                # Undated, it would be listed and never saved, or passed over
                # unsaid under a start date.
                raise ListStopped("a tax document's title names no year")
            date = f"{years[-1]}-12-31"
            title = text
            first = tax_titles.setdefault(title, e["path"])
            docs.append(RawDoc(title=title, account=pid, date_text=date, href=e["path"],
                               text=f"Optum Bank {title}", row_index=len(docs), kind="tax",
                               document_id="" if first == e["path"] else m.group(3)))
    return docs


def _goto_statements(page, pid: str) -> bool:
    url = f"{BASE}/account/products/{pid}/statements"
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(2000)
    except Exception as e:
        log.info("goto a product's statements page failed: %s", type(e).__name__)
        return False
    if looks_signed_out(page):
        return False
    if not is_safe_url(page.url or "") or PRODUCT_RE.search(urlsplit(page.url).path or "") is None:
        log.info("a product's statements page settled off this app's addresses")
        return False
    try:
        page.wait_for_selector("a[href*='/statements/'], select[name='document_id']", timeout=30000)
    except Exception:
        # Nothing to read after the whole wait. That is a page that opened
        # only when it says outright that the product has no statements.
        return says_no_statements(page)
    return True


def collect_download_docs(page) -> List[RawDoc]:
    """Every statement and tax document of every product, from the forms
    page's product links and each product's statements page. Nothing is
    pressed. Anything unreadable raises ListStopped holding what was read."""
    if not goto_documents(page):
        raise ListStopped("the Forms & documents page did not open")
    pids = product_ids(_entries(page))
    if not pids:
        raise ListStopped("the Forms & documents page links no product's statements")
    docs: List[RawDoc] = []
    for pid in pids:
        if not _goto_statements(page, pid):
            raise ListStopped("a product's statements page did not open", docs)
        try:
            found = documents_of(_entries(page), pid)
        except ListStopped as stop:
            stop.docs = docs + stop.docs
            raise
        if not found:
            if says_no_statements(page):
                continue   # a product that has none yet, which its page says
            raise ListStopped("a product's statements page lists no document", docs)
        docs.extend(found)
    return docs


def _fetch_document(page, path: str, out_path: Path, trace: Optional[list]) -> bool:
    """GET a document's own path on the member host, no redirect, and keep
    it only when it is a PDF."""
    url = BASE + path
    if not is_download_url(url):
        if trace is not None:
            trace.append({"note": "document path refused"})
        return False
    try:
        resp = page.context.request.get(url, max_redirects=0, timeout=60000)
    except Exception as e:
        log.info("fetching the document failed (%s)", type(e).__name__)
        if trace is not None:
            trace.append({"note": "fetch failed", "error": type(e).__name__})
        return False
    if trace is not None:
        trace.append({"note": "fetched", "host": "account.optumbank.com", "status": resp.status,
                      "type": (resp.headers.get("content-type") or "")[:30]})
    try:
        body = intake.body(resp) if resp.ok else b""
    except intake.TooLarge:
        return False
    if body[:5] != b"%PDF-":
        return False
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(body)
    return True


def download_bill(page, dl_dir, iso_date: str, out_path, title: str = "",
                  trace: Optional[list] = None, href: str = "") -> bool:
    """Save the document discovery recorded as `title`, dated `iso_date`, at
    the member-host path `href`. The product's own statements page is read
    again and the document is fetched only when exactly one entry there
    carries that same path, title and date. The path names the product in
    full, so two products' same-day statements cannot be confused. Nothing
    is pressed.

    A product the forms page no longer links, or an entry its statements
    page no longer holds, answers False, so the record goes to review and
    the run goes on. A forms page or statements page that will not open,
    links no product, lists nothing or cannot be read raises ListStopped,
    as it does for discovery, since every document after this one would
    read the same pages."""
    out_path = Path(out_path)
    t = (title or "").strip()
    m = DOCUMENT_PATH_RE.match(href or "")
    if not m:
        log.info("no document path was recorded for %r", t)
        if trace is not None:
            trace.append({"note": "no recorded document path"})
        return False
    pid = m.group(1)
    if not goto_documents(page):
        if looks_signed_out(page):
            # A sign-out, which the next document's session check stops on.
            log.info("the forms page answered as signed out")
            return False
        raise ListStopped("the Forms & documents page did not open")
    pids = product_ids(_entries(page))
    if not pids:
        raise ListStopped("the Forms & documents page links no product's statements")
    if pid not in pids:
        log.info("the recorded product is not on the Forms & documents page")
        return False
    if not _goto_statements(page, pid):
        if looks_signed_out(page):
            log.info("a product's statements page answered as signed out")
            return False
        raise ListStopped("a product's statements page did not open")
    try:
        listed = documents_of(_entries(page), pid)
    except ListStopped as stop:
        log.info("the list stopped while looking for %r: %s", t, stop)
        raise
    if not listed and not says_no_statements(page):
        raise ListStopped("a product's statements page lists no document")
    found = [d for d in listed if d.href == href and d.title == t and d.date_text == (iso_date or "")]
    if len(found) != 1:
        log.info("%d entries match the recorded path, title and date for %r, none taken", len(found), t)
        if trace is not None:
            trace.append({"note": "no single entry matches the record", "matches": len(found)})
        return False
    return _fetch_document(page, found[0].href, out_path, trace)


# ---------------------------------------------------------------------------
# Diagnose. Loose, redacted scrape and a survey of the signed-in pages.
# No screenshot.
# ---------------------------------------------------------------------------
_ROW_JS = r"""() => {
  const out = [];
  for (const tr of document.querySelectorAll('table tr, [role=row], li, [class*="statement" i], [class*="document" i]')) {
    const txt = (tr.innerText || '').trim();
    if (!txt) continue;
    const link = tr.querySelector("a[href]");
    out.push({text: txt.slice(0, 200), href: link ? link.getAttribute('href') : ''});
  }
  return out.slice(0, 200);
}"""

SURVEY_LINK_RE = re.compile(r"^\s*(account\s+statements?|statements?\s*&\s*(tax\s+)?docs?|tax\s+documents?)\s*$", re.I)
def collect_documents(page) -> List[RawDoc]:
    """Loose row scrape used only by --diagnose, digits masked."""
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


def survey(page, dwell_ms: int = 4000, max_follow: int = 0) -> dict:
    """What the signed-in page looks like, without downloading anything.
    Records the page's headings and controls with the guard's verdict.
    Follows nothing and listens to nothing, since this app presses no
    control at all and a survey is not a reason to start. No screenshot."""
    # No response listener. Every document here is a plain link, read from
    # the page, and a listener would count as a capture this app does not
    # make. The page's own summary is the survey.
    report = {"pages": []}
    page.wait_for_timeout(dwell_ms)
    report["pages"].append(_page_summary(page))
    return report
