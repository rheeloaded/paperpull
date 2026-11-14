"""Credit-card statements only. Read the Download controls under statement
section headings, using the heading for account attribution. Sweep the year
picker, including empty years. Re-find rows by accessible labels at download
time; verify PDF bytes and discard incomplete captures.

All requests and navigation must stay on explicitly allowed provider hosts.
"""


from __future__ import annotations

import html as _html
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

from paperpull_core import shared_folder
from paperpull_core import intake
from paperpull_core.controls import SETTINGS_CONTROL_RE, AUTH_CONTROL_RE
from paperpull_core.urls import is_safe_url as _host_allows
from paperpull_core.controls import click_next_page as _click_next_page
from paperpull_core.controls import escape_for_locator
from paperpull_core.dates import last_day as _last_day
from paperpull_core.dates import checked as _checked_date
from paperpull_core.capture import is_document as _is_document
from paperpull_core.characters import whole_json

ALLOWED_HOSTS = {'www.usbank.com', 'onlinebanking.usbank.com'}


def is_safe_url(url: str) -> bool:
    """True only for an https URL on exactly one of this provider's own
    hosts, never a subdomain of one.

    The check itself lives in the core, so all of them answer the same way.
    This app keeps the hosts and its refusal to follow subdomains, which is
    how it has always behaved."""
    return _host_allows(url, ALLOWED_HOSTS, subdomains=False)


log = logging.getLogger("usbank_docs.site")

BASE = "https://onlinebanking.usbank.com"
PUBLIC = "https://www.usbank.com"
URLS = {
    "home": f"{BASE}/",

    "login": f"{PUBLIC}/",


    "documents": f"{BASE}/digital/servicing/shellapp/#/highvolume/edocs/statements",
    "letters": f"{BASE}/digital/servicing/shellapp/#/highvolume/edocs/letters",
    "dashboard": f"{BASE}/digital/servicing/shellapp/#/customer-dashboard",
}
DOCUMENT_URL_CANDIDATES = [URLS["documents"], URLS["dashboard"]]


LOGIN_URL_MARKERS = ["/auth/login", "/logon", "/login.html", "/signin",
                     "/sign-in", "/idp", "/mfa", "/verify-identity",
                     "/authentication", "usbank.com/index.html"]


FORBIDDEN_CONTROL_RE = re.compile(

    r"(transfer|deposit|withdraw|wire\b|move\s+money|send\s+money|zelle|"
    r"pay\b|payment|pay\s+bills?|bill\s*pay|autopay|auto-?pay|schedule\s+payment|"
    r"pay\s+card|make\s+a\s+payment|stop\s+payment|"

    r"balance\s+transfer|cash\s+advance|convenience\s+check|"
    r"credit\s+line|credit\s+limit|extend\s*pay|simple\s+loan|"
    r"overdraft|"


    r"redeem|rewards?\b|points\b|miles\b|flexpoints?|real.?time\s+rewards|"
    r"cash\s*back\s+redeem|offers?\b|deals?\b|"
    r"book\s+travel|travel\s+cent(er|re)|shop\s+and\s+earn|"

    r"apply|open\s+(a|an|another|new)\b[\w\s]{0,24}\baccount\b|"
    r"open\s+\w{0,12}\s*account\b|get\s+(a\s+)?(quote|started|loan|card)|"
    r"add\s+(funds|card|authorized)|authorized\s+user|"
    r"dispute|report\s+(a\s+)?(problem|fraud|lost|stolen)|"
    r"lock\s+card|unlock\s+card|freeze|activate|replace\s+card|close\s+account|"
    r"travel\s+notification|request\b|increase\b|"

    # Word boundaries on the verb stems. Without the leading \b, "edit"
    # matches inside "Credit", and "Credit Card Statement" is the one label a
    # credit-card provider must never refuse. Same fix as core 0.17.1, anthem
    # and capitalone.
    r"\bchang(e|es|ed|ing)\b|\bedit(s|ed|ing)?\b|\bupdat(e|es|ed|ing)\b|"
    r"set\s+up|enroll|enable|disable|delete|remove|"
    r"beneficiar|payee|contact\s+info|password|username|"
    r"paperless|delivery\s+preference|alerts?\s+settings|"

    r"send\b|submit|confirm|continue|next|agree|accept|sign\b|authorize)", re.I)

SAFE_DOC_CONTROL_RE = re.compile(
    r"(download|view|open|save|print|pdf|statement|document|1099|1098|5498|"
    r"tax|e-?statement|year.?end)", re.I)

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


FALLBACK = {
    "doc_row": ("table tbody tr, [role='row'], [class*='statement-row'], "
                "[class*='StatementRow'], [class*='documentRow'], "
                "[data-testid*='statement'], [data-testid*='document'], "
                "li[class*='statement'], li[class*='document']"),
    "doc_link": ("a[href*='.pdf'], a[href*='statement'], a[href*='document'], "
                 "a[download], button[class*='download']"),
    "download_control": ("a[download], a[href$='.pdf'], "
                         "button:has-text('Download'), button:has-text('View')"),
    "page_ready": ("table, [role='row'], [class*='statement'], [class*='document'], "
                   "main, [role='main']"),
    # The statement list's own parts, the ones the download finds a row by
    # (SEL and find_row_control), so a failure file counts each of them. A
    # tester's Pilot gave up on its first statement with no press while every
    # general selector here matched, and nothing said which of these the page
    # lacked (#106). They mirror SEL, and a test holds the two together. They
    # come before the rest because the journal watches only the first twelve
    # (journal.MAX_WATCHED), and these say the most when a row is not found.
    "statement_section": "[data-testid='list-of-statements'] .document-list",
    "statements_heading": "[data-testid='list-of-statements'] .document-list h3",
    "statement_row": "[data-testid='list-of-statements'] .document-list li.download-items",
    "row_download": ("[data-testid='list-of-statements'] .document-list li.download-items "
                     "button[aria-label*='Download' i]"),
    "list_of_statements": "[data-testid='list-of-statements']",
    "account_dropdown": "[data-testid='account-dropdown']",
    "account_select": "select, [role='combobox'], [role='listbox']",
    "year_filter": "[data-testid='year-filter']",
    "next_page": ("a[aria-label*='Next' i], button[aria-label*='Next' i], "
                  ".pagination-next, [class*='next']"),
    "show_more": "button, a",
    "document_view": "[data-testid='document-view']",
}


DATE_PATTERNS = [
    (re.compile(r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
                r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|"
                r"Dec(?:ember)?)\.?\s+(\d{1,2}),?\s+(\d{4})", re.I), "mdY"),
    (re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b"), "mdy_slash"),
    (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})(?!\d)"), "iso"),
]
_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
MONTH_YEAR_RE = re.compile(
    r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
    r"Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    r"\s+(\d{4})", re.I)
QUARTER_RE = re.compile(r"\bQ([1-4])\s*[' ]?\s*(\d{4})\b", re.I)
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
    m = QUARTER_RE.search(text)
    if m:
        q, year = int(m.group(1)), int(m.group(2))
        month = q * 3
        return f"{year:04d}-{month:02d}-{_last_day(year, month):02d}", f"Q{q} {year}"
    m = YEAR_RE.search(text)
    if m:
        year = int(m.group(1) + m.group(2))
        return f"{year:04d}-12-31", str(year)
    return None, ""


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
        if page.locator(FALLBACK["doc_row"]).count() > 2:
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


def dismiss_timeout(page) -> None:
    for pattern in (r"i'?m still here", r"stay (signed|logged) in",
                    r"continue session", r"keep me (signed|logged) in",
                    r"extend (my )?session", r"still (there|here)\?"):
        try:
            c = page.get_by_role("button", name=re.compile(pattern, re.I))
            if c.count() and c.first.is_visible():
                c.first.click()
                page.wait_for_timeout(1000)
                return
        except Exception:
            pass


DOCUMENTS_NAV_RE = re.compile(
    r"^\s*(documents?|statements?\s*(&|and)\s*documents?|"
    r"statements?|e-?statements?|tax\s+forms?)\s*$", re.I)


def on_documents_page(page) -> bool:
    try:
        if page.locator(SEL["doc_view"]).count() > 0:
            return True
        if page.locator(SEL["list"]).count() > 0:
            return True
    except Exception:
        pass
    try:
        return len(collect_documents(page)) > 0
    except Exception:
        return False


def click_documents_nav(page) -> bool:
    for role in ("button", "link"):
        try:
            loc = page.get_by_role(role, name=DOCUMENTS_NAV_RE)
            if loc.count() == 0:
                continue
            for i in range(min(loc.count(), 4)):
                c = loc.nth(i)
                try:
                    if not c.is_visible():
                        continue
                    label = (c.inner_text(timeout=1000) or "").strip()
                except Exception:
                    continue
                if not is_safe_control(label):
                    continue
                c.click()
                page.wait_for_timeout(3500)
                dismiss_timeout(page)
                log.info("clicked %s %r -> %s", role, label, page.url)
                if on_documents_page(page):
                    return True

                for sub in ("statements", "e-statements", "tax forms"):
                    try:
                        s = page.get_by_role("link", name=re.compile(rf"^\s*{sub}\s*$", re.I))
                        if s.count() and s.first.is_visible():
                            s.first.click()
                            page.wait_for_timeout(3000)
                            dismiss_timeout(page)
                            log.info("clicked submenu %r -> %s", sub, page.url)
                            if on_documents_page(page):
                                return True
                    except Exception:
                        pass
        except Exception as e:
            log.info("documents nav (%s) failed: %s", role, e)
    return False


def goto_documents(page) -> bool:
    dismiss_timeout(page)
    if on_documents_page(page):
        return True
    if click_documents_nav(page):
        log.info("documents area reached at %s", page.url)
        return True
    for url in DOCUMENT_URL_CANDIDATES:
        try:
            if not is_safe_url(url):
                continue
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3500)
            dismiss_timeout(page)
            if looks_signed_out(page):
                return False
            try:
                page.wait_for_selector(FALLBACK["page_ready"], timeout=12000)
            except Exception:
                pass
            if on_documents_page(page):
                log.info("documents area reached at %s", page.url)
                return True
        except Exception as e:
            log.info("documents URL %s failed: %s", url, e)
    return on_documents_page(page)


def ensure_statements(page) -> bool:
    dismiss_timeout(page)
    if on_documents_page(page):
        return True
    return goto_documents(page)


def scroll_full_page(page, rounds: int = 6, delay_ms: int = 700) -> None:
    try:
        for _ in range(rounds):
            page.mouse.wheel(0, 2500)
            page.wait_for_timeout(delay_ms)
        page.keyboard.press("End")
        page.wait_for_timeout(delay_ms)
    except Exception:
        pass


def expand_all(page) -> None:
    for _ in range(25):
        clicked = False
        try:
            btn = page.get_by_role("button", name=re.compile(
                r"(show more|load more|view more|see more|view all|older|"
                r"more\s+statements|previous\s+statements)", re.I))
            if btn.count() > 0 and btn.first.is_visible():
                label = btn.first.inner_text(timeout=1000) or ""
                if not FORBIDDEN_CONTROL_RE.search(label):
                    btn.first.click()
                    page.wait_for_timeout(1500)
                    clicked = True
        except Exception:
            pass
        if not clicked:
            break


def next_page(page) -> bool:
    """One page forward, through a control that says it pages forward.

    Judged by an allowlist in the core rather than by FORBIDDEN_CONTROL_RE,
    because that blocklist refuses the word "next". Correctly, since "Next"
    is also what a wizard's commit button says, and fatally here, because it
    meant this could never page forward at all and the run reported success
    having seen only the first page.
    """
    return _click_next_page(page, FALLBACK["next_page"])


@dataclass
class RawDoc:
    title: str
    account: str = ""
    date_text: str = ""
    href: str = ""
    text: str = ""
    row_index: int = -1
    kind: str = "doc"


class Read(list):
    """What a reading of the page found, with what it can say of itself. A
    list, so whatever took the plain list before takes this as it did.

    whole, every account and year there was to read was chosen and read,
    and no account the picker offered was refused. years, the years whose
    list drew under every account. drawn, a statements section was on the
    page. pick_each, the picker is to be set to each account, even one,
    since it may show its placeholder rather than an account. shown, the
    most Download controls for a statement a view showed while nothing was
    read from it. unread, the rows with a Download for a statement whose
    label did not read to a date or clear the guard. heads, each statements
    section's account from its heading. unchosen, the accounts the picker
    offered that could not be chosen. passed_over, each picker a walk could
    not read through, "account picker" or "year picker", so the list is not
    whole however much was read. not_read, why a picker on the page gave
    nothing to walk, in our own words, "" when it answered."""
    whole = False
    years: tuple = ()
    drawn = False
    pick_each = False
    shown = 0
    unread = 0
    heads: tuple = ()
    unchosen = 0
    passed_over: tuple = ()
    not_read = ""


def _read(items=(), **facts) -> Read:
    out = Read(items)
    for name, value in facts.items():
        setattr(out, name, value)
    return out


# A row the page's text is read for holds no picker and no other dated row,
# and shows one date, which is the date it is filed under. A header holding
# the account picker, and a section holding two statements dated with the
# first of them, were each taken for one statement (#106).
_ROW_JS = r"""() => {
  const DATE_RE = /(\d{1,2}\/\d{1,2}\/\d{4})|((Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4})|((Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4})/i;
  const DATES = new RegExp(DATE_RE.source, 'gi');
  const PICKER = "select, [role='combobox'], [role='listbox']";
  const CTRL = "a[href$='.pdf'], a[download], a[aria-label], button[aria-label], a, button";
  const SAFE = /(download|view|open|save|print|pdf|statement|document|1099|1098|5498|tax)/i;
  const rows = new Set();
  for (const sel of ['table tr', "[role='row']", "li", "[class*='statement']", "[class*='document']"]) {
    for (const el of document.querySelectorAll(sel)) rows.add(el);
  }
  const dated = [...rows].filter(el => DATE_RE.test(el.innerText || ''));
  const out = [];
  for (const el of rows) {
    // skip containers that hold other candidate rows (keep the innermost)
    if (el.querySelector("table tr, [role='row']")) continue;
    if (el.querySelector(PICKER)) continue;
    if (dated.some(other => other !== el && el.contains(other))) continue;
    const text = (el.innerText || '').replace(/\s+/g, ' ').trim();
    if (!text || text.length > 400) continue;
    const dates = new Set((text.match(DATES) || []).map(d => d.replace(/\s+/g, ' ').toLowerCase()));
    if (dates.size !== 1) continue;
    const m = text.match(DATE_RE);
    if (!m) continue;
    let ctrl = null;
    for (const c of el.querySelectorAll(CTRL)) {
      const label = ((c.innerText || '') + ' ' + (c.getAttribute('aria-label') || '') +
                     ' ' + (c.getAttribute('href') || '')).trim();
      if (SAFE.test(label)) { ctrl = { label: label.slice(0, 80),
                                       href: c.getAttribute('href') || '',
                                       tag: c.tagName.toLowerCase() }; break; }
    }
    if (!ctrl) continue;
    out.push({ date_text: m[0], text: text.slice(0, 300),
               title: text.replace(m[0], '').replace(/\s+/g, ' ').trim().slice(0, 120),
               ctrl_label: ctrl.label, href: ctrl.href, tag: ctrl.tag });
  }
  return out;
}"""


def collect_documents(page, or_raise: bool = False) -> List[RawDoc]:
    """The page's rows as its text reads them. With `or_raise` a read that
    fails raises RowUnread, since rows that would not be read are not a
    page without rows."""
    docs: List[RawDoc] = []
    seen = set()
    try:
        rows = page.evaluate(_ROW_JS)
    except Exception as e:
        if or_raise:
            raise RowUnread("the page's rows would not answer") from e
        log.info("row scrape failed: %s", e)
        rows = []
    for i, r in enumerate(rows):
        title = _html.unescape(r.get("title", "")).strip() or "Statement"
        date_text = r.get("date_text", "")


        key = (title, date_text, i)
        if key in seen:
            continue
        seen.add(key)
        docs.append(RawDoc(title=title[:200], date_text=date_text,
                           href=r.get("href", ""), text=r.get("text", ""),
                           row_index=i))
    return docs


_ACCOUNT_HINT_RE = re.compile(
    r"(visa|mastercard|american\s+express|amex|card\b|credit|"
    r"checking|savings|money\s*market|\bcd\b|certificate|"
    r"account|x{2,}\d|\*{2,}\d|\.{3}\d{3,}|\d{4}\s*$)", re.I)


MONEY_CONTROL_RE = re.compile(
    r"(from|to|source|destination|target)\s*_?-?account|"
    r"transfer|payment|pay\b|bill|deposit|withdraw|zelle|wire|remit|"
    r"send\s*money|move\s*money|recipient|payee|amount|frequency|schedule|"
    r"extend\s*pay|redeem|rewards?\b", re.I)


_IDENTITY_JS = r"""el => {
  const attrs = ['id','name','aria-label','placeholder','data-testid',
                 'allytmfn','data-allytmfn','data-track-name'];
  const bits = attrs.map(a => el.getAttribute(a) || '');
  const form = el.closest('form');
  if (form) bits.push(form.id || '', form.getAttribute('name') || '',
                      form.getAttribute('aria-label') || '');
  // the nearest labeled section/card this control lives in
  const sect = el.closest("section, [role='region'], [class*='card'], [class*='Card'], " +
                          "[class*='widget'], [class*='Widget'], [class*='module']");
  if (sect) {
    bits.push(sect.getAttribute('aria-label') || '', sect.className || '');
    const h = sect.querySelector('h1,h2,h3,h4,legend');
    if (h) bits.push((h.innerText || '').slice(0, 60));
  }
  const lbl = el.id ? document.querySelector(`label[for="${CSS.escape(el.id)}"]`) : null;
  if (lbl) bits.push((lbl.innerText || '').slice(0, 60));
  return bits.filter(Boolean).join(' | ');
}"""


def control_identity(loc) -> str:
    try:
        return loc.evaluate(_IDENTITY_JS) or ""
    except Exception:
        return ""


def _identity_or_none(loc) -> Optional[str]:
    """control_identity, or None when the control would not answer. The
    money guard refuses a control with no identity, so a picker that did
    not answer read as one refused, and then as no picker at all."""
    try:
        return loc.evaluate(_IDENTITY_JS) or ""
    except Exception:
        return None


def is_money_control(identity: str) -> bool:
    if not identity:
        return True
    return bool(MONEY_CONTROL_RE.search(identity)
                or FORBIDDEN_CONTROL_RE.search(identity))


def _safe_selects(page, limit: int = 12):
    try:
        loc = page.locator("select")
        n = min(loc.count(), limit)
    except Exception:
        return
    for i in range(n):
        s = loc.nth(i)
        identity = control_identity(s)
        if is_money_control(identity):
            log.info("refusing dropdown (money control): %s", identity[:120])
            continue
        yield s, identity


def describe_selects(page, limit: int = 12) -> List[dict]:
    out: List[dict] = []
    try:
        loc = page.locator("select")
        n = min(loc.count(), limit)
    except Exception:
        return out
    for i in range(n):
        s = loc.nth(i)
        identity = control_identity(s)
        try:
            opts = [o.strip() for o in s.locator("option").all_inner_texts()][:12]
        except Exception:
            opts = []
        out.append({"identity": identity[:200],
                    "refused_as_money_control": is_money_control(identity),
                    "option_count": len(opts),

                    "option_sample": [re.sub(r"\$[\d,.]+", "$…", o)[:60] for o in opts[:6]]})
    return out


# A picker's prompt, "Choose an account", which names no account. Its own
# words match the account hint, so the page's text reading chose it as an
# account and read the page under it (#106).
PLACEHOLDER_RE = re.compile(r"^\W*(choose|select|pick)\b", re.I)

# The options of a dropdown that can be chosen. A turned off one cannot be,
# and choosing it waited out its time and was taken for an account or a
# year that would not take.
_ENABLED_OPTION = "option:not([disabled])"


def account_select(page):
    for s, _identity in _safe_selects(page):
        try:
            opts = [o.strip() for o in s.locator(_ENABLED_OPTION).all_inner_texts()]
        except Exception:
            continue
        accts = [o for o in opts if o and _ACCOUNT_HINT_RE.search(o)
                 and not re.fullmatch(r"20\d{2}", o) and not PLACEHOLDER_RE.match(o)]
        if accts:
            return s, accts
    return None, []


def year_select(page):
    for s, _identity in _safe_selects(page):
        try:
            opts = [o.strip() for o in s.locator(_ENABLED_OPTION).all_inner_texts()]
        except Exception:
            continue
        years = [o for o in opts if re.fullmatch(r"20\d{2}", o)]
        if years:
            return s, years
    return None, []


def _select_option(page, sel, label: str) -> bool:
    identity = control_identity(sel)
    if is_money_control(identity):
        log.warning("REFUSED to set a money-movement control: %s", identity[:160])
        return False
    if FORBIDDEN_CONTROL_RE.search(label or ""):
        log.warning("REFUSED option %r - matches the forbidden list", label)
        return False
    try:
        sel.select_option(label=label, timeout=8000)
        page.wait_for_timeout(2500)
        dismiss_timeout(page)
        return True
    except Exception as e:
        log.info("could not select %r: %s", label, str(e).split("\n")[0])
        return False


def _row_own_date(text: str) -> str:
    """The date a row of the page's text shows, as the row writes it, a day,
    or a month and a year filed on the month's last day as the list files
    one. Never a year alone. A day that does not exist, September 31st, used
    to fall through to its year and was filed on the last day of December,
    a date no row showed (#106)."""
    date, period = parse_period_date(text or "")
    if not date or (period and not MONTH_YEAR_RE.fullmatch(period)):
        return ""
    return date


def usbank_collect(page) -> Read:
    """The page's text read for statements, under each account and year its
    dropdowns offer. A year or an account whose choice did not take was not
    read, and is named in passed_over, where it used to be passed over and
    the list noted whole without it. Rows that would not be read raise
    RowUnread."""
    docs: List[dict] = []
    seen = set()
    passed_over = set()

    def grab(acct: str):
        expand_all(page)
        scroll_full_page(page, rounds=3)
        for r in collect_documents(page, or_raise=True):
            date = _row_own_date(r.date_text)
            if not date:
                continue
            key = (acct, date, r.title)
            if key in seen:
                continue
            seen.add(key)
            docs.append({"account": acct, "date": date,
                         "title": r.title or "Statement"})

    def walk_years(acct: str):
        sel, years = year_select(page)
        if sel is not None and years:
            for y in years:
                if _select_option(page, sel, y):
                    grab(acct)
                else:
                    passed_over.add("year picker")
        else:
            grab(acct)

            for _ in range(30):
                if not next_page(page):
                    break
                grab(acct)

    acct_sel, accounts = account_select(page)
    if acct_sel is not None and accounts:
        # Chosen here with no look at whether the list followed, so the page
        # holds the note of a choice not known to have taken (_note_choice),
        # and select_account opens it again before it chooses on it.
        _note_choice(page, True)
        for a in accounts:
            if FORBIDDEN_CONTROL_RE.search(a):
                # Never chosen (_select_option), and no account whose
                # statements are listed.
                log.info("refusing account option %r", a[:60])
                continue
            if not _select_option(page, acct_sel, a):
                passed_over.add("account picker")
                continue
            walk_years(re.sub(r"\s+", " ", a).strip())
    else:
        walk_years("")
    return _read(docs, passed_over=tuple(sorted(passed_over)))


SEL = {
    "doc_view": "[data-testid='document-view']",
    "account": "[data-testid='account-dropdown']",
    "year_filter": "[data-testid='year-filter']",
    "year_button": "#exp_button_year-filter-select",
    "year_selection": "#year-filter-select .dropdown__btn-selection",
    "list": "[data-testid='list-of-statements']",
    "section": ".document-list",
    "row": "li.download-items",
}


STATEMENT_SECTION_RE = re.compile(r"statements\s*$", re.I)


ROW_DOWNLOAD_ARIA_RE = re.compile(r"^\s*Download\s+(.+?)\s+statement\b", re.I)
ROW_VIEW_ARIA_RE = re.compile(r"^\s*View\s+(.+?)\s+statement\b", re.I)


CARD_RE = re.compile(
    r"\(\s*\.{2,}\s*\d{4}\s*\)"
    r"|\.{3,}\s*\d{4}"
    r"|[*x\u00b7\u2022]{2,}\s*\d{4}"
    r"|ending\s+(?:in\s+)?\d{4}",
    re.I)


CARD_ACTION_RE = re.compile(
    r"\b(pay|paid|paying|redeem\w*|transfer\w*|activat\w*|lock|unlock|"
    r"freeze|unfreeze|replac\w*|clos\w*|open|apply|applying|add|remov\w*|"
    r"delet\w*|chang\w*|edit|updat\w*|manag\w*|enroll\w*|dispute\w*|"
    r"report\w*|request\w*|increas\w*|book|shop|send|deposit|withdraw|"
    r"convert|link|set\s*up|schedul\w*|order)\b", re.I)


def is_card_control(label: str) -> bool:
    label = " ".join((label or "").split())
    if not label or not CARD_RE.search(label):
        return False
    return not CARD_ACTION_RE.search(label)


# How long a page may take to draw its statement list after it opens, and
# the list to come back after another account is chosen. The tester's page
# drew its pickers and its list a moment after it opened, and a Pilot that
# read it before then found no list at all (#106).
LIST_WAIT_MS = 15000
REDRAW_MS = 10000
# How long the year picker may take to draw after the list. A Pilot read
# the page a tenth of a second after it opened, before the year picker was
# there, and walked the current year alone (#116).
YEAR_WAIT_MS = 5000

# The statement list's text, read the same way here and in _REDRAWN_JS, so
# that the two compare.
_LIST_TEXT_JS = r"""(list) => {
  const el = document.querySelector(list);
  return el ? (el.innerText || '').replace(/\s+/g, ' ').trim() : '';
}"""

# The list's sections and rows as they are before a choice, each with its
# text, a row with its buttons' labels too, kept in the page for
# _REDRAWN_JS to compare with.
_MARK_SECTIONS_JS = r"""([list, section, row]) => {
  const norm = t => (t || '').replace(/\s+/g, ' ').trim();
  const sig = r => norm(r.innerText) + '|' + Array.from(r.querySelectorAll('button')).map(
    b => b.getAttribute('aria-label') || '').join('|');
  const el = document.querySelector(list);
  window.__paperpullSections = el ? Array.from(el.querySelectorAll(section)).map(
    s => [s, norm(s.innerText)]) : [];
  window.__paperpullRows = el ? Array.from(el.querySelectorAll(row)).map(r => [r, sig(r)]) : [];
  return window.__paperpullRows.length;
}"""

# The list is no longer the one before. A list that showed no section and
# no row has nothing in it to be taken for the new one's. Otherwise its
# text changed, and when it had rows, either none is left or a row is new
# or changed, since a heading can follow the picker at once while the rows
# under it are still the old account's. When it had sections and no rows,
# either none is left or a section is new or changed. Rows or sections left
# as they were under a loading note drawn beside them are the old list.
_REDRAWN_JS = r"""([list, section, row, before]) => {
  const norm = t => (t || '').replace(/\s+/g, ' ').trim();
  const sig = r => norm(r.innerText) + '|' + Array.from(r.querySelectorAll('button')).map(
    b => b.getAttribute('aria-label') || '').join('|');
  const oldRows = window.__paperpullRows || [];
  const oldSections = window.__paperpullSections || [];
  if (!oldRows.length && !oldSections.length) return true;
  const el = document.querySelector(list);
  if ((el ? norm(el.innerText) : '') === before) return false;
  const changed = (now, old, key) => now.some(n => {
    const was = old.find(o => o[0] === n);
    return !was || key(n) !== was[1];
  });
  if (oldRows.length) {
    const rows = el ? Array.from(el.querySelectorAll(row)) : [];
    return rows.length === 0 || changed(rows, oldRows, sig);
  }
  const now = el ? Array.from(el.querySelectorAll(section)) : [];
  return now.length === 0 || changed(now, oldSections, s => norm(s.innerText));
}"""

# A section of the statement list drew, or a native account picker holding
# accounts sits on its prompt, "Choose an account", which draws no list
# until one is chosen. Told by its words, as PLACEHOLDER_RE tells it, since
# a picker's options need not carry values.
_LIST_OR_PROMPT_JS = r"""([section, picker]) => {
  if (document.querySelector(section)) return true;
  const s = document.querySelector(picker);
  return !!(s && s.options.length > 1 && s.selectedIndex >= 0 &&
            /^\W*(choose|select|pick)\b/i.test(s.options[s.selectedIndex].text || ''));
}"""


def _wait_for_list(page, ms: Optional[int] = None) -> bool:
    """Whether the page drew its statement list, waiting up to `ms` for a
    section of it, or for the account picker to show its prompt. Nothing
    here raises."""
    try:
        page.wait_for_function(_LIST_OR_PROMPT_JS,
                               arg=[f"{SEL['list']} {SEL['section']}", f"{SEL['account']} select"],
                               timeout=LIST_WAIT_MS if ms is None else ms)
        return True
    except Exception:
        return False


def _wait_for_year_picker(page, ms: Optional[int] = None) -> bool:
    """Whether the year picker's button is on the page, waiting up to `ms`
    for it. Nothing here raises."""
    try:
        page.wait_for_selector(SEL["year_button"], state="attached",
                               timeout=YEAR_WAIT_MS if ms is None else ms)
        return True
    except Exception:
        return False


def _list_text(page) -> str:
    try:
        return page.evaluate(_LIST_TEXT_JS, SEL["list"]) or ""
    except Exception:
        return ""


def _mark_sections(page) -> None:
    """Note the list's sections before a choice, for _wait_for_redraw."""
    try:
        page.evaluate(_MARK_SECTIONS_JS, [SEL["list"], SEL["section"], SEL["row"]])
    except Exception:
        pass


def _wait_for_redraw(page, before: str) -> bool:
    """Whether the statement list let go of the one before after a choice
    (_mark_sections notes it), then waiting for a section of the new one to
    draw. A list read before it came back is the account before's, read as
    the one just chosen, and a page may keep the old list on show, or draw
    a loading note over it, until the new one comes. False when the old
    list stayed."""
    try:
        page.wait_for_function(_REDRAWN_JS, arg=[SEL["list"], SEL["section"], SEL["row"], before],
                               timeout=REDRAW_MS)
    except Exception:
        return False
    _wait_for_list(page, REDRAW_MS)
    # The three seconds a choice of account was always given, so a list
    # that redraws in parts has drawn them all.
    page.wait_for_timeout(3000)
    return True


_SELECTED_OPTION_JS = r"""s => s.selectedIndex >= 0 ? s.options[s.selectedIndex].text : ''"""

# Each option of a plain picker, its text as the app reads it and its own
# label, which the page matches when it is chosen by label.
_OPTIONS_JS = r"""s => Array.from(s.options, o => [o.innerText || '', o.label || ''])"""

# A choice of account under way or one that did not take, noted in the page
# itself, so a page loaded again, its picker and list drawn afresh, holds
# none.
_NOTE_CHOICE_JS = r"""v => { window.__paperpullChoiceUnsure = v; return v; }"""
_CHOICE_UNSURE_JS = r"""() => window.__paperpullChoiceUnsure === true"""


def _note_choice(page, unsure: bool) -> bool:
    """Note in the page that a choice of account is under way (True), set
    before the picker is touched and left there when the choice does not
    take, or that the list followed the one just made (False). Whether the
    page holds the note. Nothing here raises."""
    try:
        return page.evaluate(_NOTE_CHOICE_JS, bool(unsure)) is bool(unsure)
    except Exception:
        return False


def _choice_unsure(page) -> Optional[bool]:
    """Whether the page holds a choice of account that did not take
    (_note_choice), None when the page would not say."""
    try:
        return bool(page.evaluate(_CHOICE_UNSURE_JS))
    except Exception:
        return None


def _reopen(page) -> bool:
    """Load the statements page again, picker and list drawn afresh, which
    drops the note of a choice that did not take (_note_choice) and any
    list still on its way. Only a page on U.S. Bank's own site, and nothing
    here raises. Whether the page holds no such note after."""
    try:
        if is_safe_url(page.url):
            log.info("the statements page is opened again")
            page.reload(wait_until="domcontentloaded", timeout=60000)
            dismiss_timeout(page)
            _wait_for_list(page)
    except Exception as e:
        log.info("could not open the statements page again: %s", str(e).split("\n")[0])
    return _choice_unsure(page) is False


def _not_taken(page, label: str, why: str) -> bool:
    """A choice of account that did not take, after the picker was touched.
    Its picker can show one account while its list holds another's rows, or
    the list asked for can still come late and be read as the next choice's,
    so the statements page is loaded again (_reopen). A page that will not
    load again keeps its note, and select_account takes no choice on it.
    False always, and nothing here raises."""
    log.info("%s for %r, so it is not taken", why, label[:60])
    _reopen(page)
    return False


def _as_playwright_reads(label: str) -> str:
    """An option's own label as Playwright compares it when it chooses by
    label, which also takes an option whose label matches once white space
    is made plain (normalizeWhiteSpace). Zero-width spaces and soft hyphens
    dropped, the ends trimmed and every run of white space one space. White
    space here is a little wider than Playwright's, so labels it would take
    for one are never counted as two."""
    return re.sub(r"[\s\ufeff]+", " ", re.sub(r"[\u200b\u00ad]", "", label or "")).strip()


class PickerRefused(Exception):
    """The account dropdown holds a <select> that is not to be read or set,
    one the money-control filter refuses, or more than one. The dropdown's
    text is then not read as an account either, since it is every option
    run together."""


def _plain_account_select(page):
    """The account dropdown's own <select>, when the picker is drawn as one,
    or None. Its text is every option run together, so the account on show
    is its chosen option and each account is one option (#106). One that
    reads as a money control is never handed out, so is never set. It, and
    a dropdown holding two, raise PickerRefused, where they used to leave
    the dropdown's whole text to be read as one account."""
    try:
        sel = page.locator(SEL["account"]).first.locator("select")
        n = sel.count()
    except Exception:
        return None
    if n == 0:
        return None
    if n != 1:
        log.info("refusing account picker (%d selects)", n)
        raise PickerRefused()
    if is_money_control(control_identity(sel.first)):
        log.info("refusing account picker (money control)")
        raise PickerRefused()
    return sel.first


def _plain_account_options(sel, or_none: bool = False) -> Optional[List[Tuple[str, str]]]:
    """Each option of a plain picker as (its label as the app reads it, the
    page's own label for it), read at once. Options that would not answer
    are none, or with `or_none` None, which is never a picker without
    options."""
    try:
        return [(" ".join(str(t).split()), str(own))
                for t, own in sel.evaluate(_OPTIONS_JS, timeout=5000)]
    except Exception:
        return None if or_none else []


def _option_index(labels: List[str], label: str) -> int:
    """Which of a plain picker's option labels is the account `label`, as an
    index into labels, or -1 when none is, or when it cannot be told which.
    Only the whole label, spaces aside, is the account: a part of one, such
    as "Visa ...3333" of "Business Visa ...3333", could be another card's,
    and two options of one label are told apart by nothing."""
    want = " ".join((label or "").split())
    hits = [i for i, x in enumerate(labels) if " ".join(x.split()) == want]
    return hits[0] if len(hits) == 1 else -1


def account_name(page) -> str:
    try:
        sel = _plain_account_select(page)
        if sel is not None:
            text = " ".join((sel.evaluate(_SELECTED_OPTION_JS) or "").split())
        else:
            el = page.locator(SEL["account"]).first
            if el.count() == 0:
                return ""
            text = " ".join((el.inner_text(timeout=3000) or "").split())
    except Exception:
        return ""

    text = re.sub(r"^\s*Account\s*", "", text, flags=re.I).strip()
    if not text:
        return ""
    if not is_card_control(text):
        log.info("account label %r did not clear the card guard", text[:60])
        return ""
    return text


# How long an opened picker is given to draw its options, and how long once
# more when it drew none, since options drawn after the first look are not
# a picker without options.
OPTIONS_WAIT_MS = (1200, 3000)


def _picker_labels(page, btn, wanted=bool) -> List[str]:
    """The words of each option the page shows once a picker is opened by
    its button, looked at once more when none is `wanted`, the picker closed
    again after. A plain <select>'s options are options too, the account
    picker's beside the year picker's. Raises what Playwright raises."""
    btn.click()
    labels: List[str] = []
    for wait in OPTIONS_WAIT_MS:
        page.wait_for_timeout(wait)
        labels = [" ".join(t.split()) for t in page.get_by_role("option").all_inner_texts()]
        if any(wanted(t) for t in labels):
            break
    page.keyboard.press("Escape")
    page.wait_for_timeout(400)
    return labels


def account_options(page) -> Read:
    """Every account the picker offers, by its whole label. Whole when they
    came from a plain picker's own options, none but its prompt was refused
    and none is offered twice, so that a walk of them is every account.

    not_read says why when the picker is on the page and did not say which
    accounts it offers, it or its options would not answer or it listed no
    option. Only the account on show could then be read. One the guard
    refuses is not that, since it is never read whatever it says."""
    try:
        holder = page.locator(SEL["account"]).first
        if holder.count() == 0:
            return Read()
        btn = holder.locator("button[aria-expanded], [role='combobox']")
        if btn.count() == 0:
            sel = _plain_account_select(page)
            if sel is not None:
                options = _plain_account_options(sel, or_none=True)
                if not options:
                    return _read(not_read="the account picker did not list its accounts")
                labels = [label for label, _own in options]
                out = [x for x in labels if is_card_control(x)]
                held_back = 0
                for x in labels:
                    if x and x not in out:
                        log.info("refusing account option %r", x[:60])
                        held_back += not PLACEHOLDER_RE.match(x)
                # Set to each in turn, even one, since the picker can show
                # its prompt rather than an account (pick_each).
                return _read(out, whole=bool(out) and not held_back and len(set(out)) == len(out),
                             pick_each=True)
            one = account_name(page)
            return Read([one] if one else [])
    except PickerRefused:
        return Read()
    except Exception:
        return _read(not_read="the account picker would not answer")
    identity = _identity_or_none(btn.first)
    if identity is None:
        return _read(not_read="the account picker would not answer")
    if is_money_control(identity):
        log.info("refusing account picker (money control): %s", identity[:120])
        return Read()
    try:
        labels = _picker_labels(page, btn.first)
    except Exception as e:
        log.info("account options failed: %s", e)
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        one = account_name(page)
        return _read([one] if one else [], not_read="the account picker would not list its accounts")
    if not any(labels):
        one = account_name(page)
        return _read([one] if one else [], not_read="the account picker listed no account")
    out = [x for x in labels if is_card_control(x)]
    for x in labels:
        if x and x not in out:
            log.info("refusing account option %r", x[:60])
    # Never whole. This picker's choice is not read back, nor its list
    # seen to draw again, so a walk of it judges no record (#106).
    return Read(out)


def select_account(page, label: str) -> bool:
    """Choose the account `label` and say whether it is chosen. The account
    the picker already shows is taken as chosen only on a page holding no
    choice that did not take (_note_choice). A choice whose list took over
    REDRAW_MS to come, or whose picker went back, can leave the picker
    showing this account while the list still holds the rows of the one
    before, and on a list whose headings name no account a row of the same
    date there would be pressed and saved as this account's statement
    (review of 0.56.1). Such a page is opened again (_reopen), here or when
    the choice failed, and no account is chosen on one that would not open
    again, since a list asked for there can still come late and be read as
    the one chosen next."""
    if not label:
        return True
    if _choice_unsure(page) is True and not _reopen(page):
        log.info("the statements page holds a choice of account that did not take and would "
                 "not open again, so %r is not chosen", label[:60])
        return False
    if label == account_name(page) and _choice_unsure(page) is False:
        return True
    try:
        holder = page.locator(SEL["account"]).first
        btn = holder.locator("button[aria-expanded], [role='combobox']")
        if btn.count() == 0:
            sel = _plain_account_select(page)
            if sel is None:
                return True
            return _select_plain_account(page, sel, label)
        if is_money_control(control_identity(btn.first)):
            log.warning("REFUSED to set the account picker (money control)")
            return False
        if not is_card_control(label):
            log.warning("REFUSED account option %r - not a card label", label[:60])
            return False
        btn.first.click()
        page.wait_for_timeout(1000)
        opt = page.get_by_role("option", name=re.compile(escape_for_locator(label)))
        if opt.count() == 0:
            page.keyboard.press("Escape")
            log.info("account %r not offered", label[:40])
            return False
        if not _note_choice(page, True):
            page.keyboard.press("Escape")
            log.info("the page would not hold the note of a choice, so %r is not chosen", label[:40])
            return False
        opt.first.click()
        page.wait_for_timeout(3000)
        dismiss_timeout(page)
        # This picker's choice is not read back, nor its list seen to draw
        # again, as before (account_options), so a click that went through
        # is taken as it always was.
        _note_choice(page, False)
        return True
    except Exception as e:
        log.info("could not select account %r: %s", label[:40], e)
        if _choice_unsure(page) is True:
            return _not_taken(page, label, "the choice stopped on the way")
        return False


def _select_plain_account(page, sel, label: str) -> bool:
    """Choose `label` on a plain <select> picker, and say whether it is the
    account on show after. One the picker does not offer is never taken as
    chosen, where before a picker with no menu button always was (#106).
    `sel` has been through the money-control filter (_plain_account_select).
    The choice is taken only once the list let go of the account before
    (_wait_for_redraw), since a list still showing it could be read or
    pressed as the new account's. A choice that does not take leaves its
    note in the page (_note_choice).

    The option is chosen by the page's own label for it when no other
    option shares that label as Playwright compares labels
    (_as_playwright_reads), which the page matches as it chooses, so an
    option list drawn again in between cannot put another account where
    the one wanted was a moment before. Otherwise by its place, and either
    way the account on show is read back after."""
    if not is_card_control(label):
        log.warning("REFUSED account option %r - not a card label", label[:60])
        return False
    options = _plain_account_options(sel)
    i = _option_index([text for text, _own in options], label)
    if i < 0:
        log.info("account %r not offered", label[:40])
        return False
    own = _as_playwright_reads(options[i][1])
    shared = [_as_playwright_reads(o) for _t, o in options].count(own)
    by = {"label": options[i][1]} if own and shared == 1 else {"index": i}
    before = _list_text(page)
    _mark_sections(page)
    if not _note_choice(page, True):
        log.info("the page would not hold the note of a choice, so %r is not chosen", label[:40])
        return False
    try:
        sel.select_option(timeout=8000, **by)
    except Exception as e:
        log.info("could not select account %r: %s", label[:40], str(e).split("\n")[0])
        return _not_taken(page, label, "the picker would not take the choice")
    if not _wait_for_redraw(page, before):
        return _not_taken(page, label, "the statement list did not draw again")
    dismiss_timeout(page)
    if account_name(page) != label:
        return _not_taken(page, label, "the picker shows another account after the choice")
    _note_choice(page, False)
    return True


def _year_picker(page):
    """The year picker's button, as (button, ""). (None, "") when the page
    shows no such button or the guard refuses it, and (None, why) when it
    shows one that would not answer, which is never a page without one."""
    try:
        btn = page.locator(SEL["year_button"])
        if btn.count() == 0:
            return None, ""
    except Exception:
        return None, "the year picker would not answer"
    try:
        name = " ".join((btn.first.inner_text(timeout=1500) or "").split())
    except Exception:
        return None, "the year picker would not answer"

    if not is_safe_control(name):
        log.info("year filter %r did not clear the guard", name[:60])
        return None, ""
    identity = _identity_or_none(btn.first)
    if identity is None:
        return None, "the year picker would not answer"
    if is_money_control(identity):
        log.info("refusing year filter (money control)")
        return None, ""
    return btn.first, ""


def reset_to_newest_period(page) -> str:
    newest = (period_options(page) or [""])[0]
    if newest and select_period(page, newest):
        return newest
    return current_period(page)


def current_period(page) -> str:
    try:
        el = page.locator(SEL["year_selection"]).first
        if el.count() == 0:
            return ""
        return " ".join((el.inner_text(timeout=1500) or "").split())
    except Exception:
        return ""


_YEAR_OPTION_RE = re.compile(r"20\d{2}")


def period_options(page) -> Read:
    """The years the year picker offers, newest first, and none for a page
    without one. not_read says why when the picker is on the page and gave
    no year, it would not answer, would not list its years or listed none,
    since then only the year on show could be read. One the guard refuses
    is not that, since it is never pressed whatever it says."""
    btn, why = _year_picker(page)
    if why:
        return _read(not_read=why)
    if btn is None:
        sel, years = year_select(page)
        return Read(sorted(set(years), reverse=True) if years else [])
    try:
        labels = _picker_labels(page, btn, wanted=_YEAR_OPTION_RE.fullmatch)
    except Exception as e:
        log.info("period options failed: %s", e)
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        return _read(not_read="the year picker would not list its years")
    years = sorted({t for t in labels if _YEAR_OPTION_RE.fullmatch(t)}, reverse=True)
    if not years:
        return _read(not_read="the year picker listed no year")
    return Read(years)


def select_period(page, year: str, offered: bool = False) -> bool:
    """Choose `year`. True on a page with no year picker, whose list is the
    one on show, unless the year was `offered` by a picker, which is then
    not there to choose it. False when the picker would not answer, which
    was read as no picker, so the year before was read in its place."""
    year = str(year)
    btn, why = _year_picker(page)
    if why:
        log.info("year %s not chosen, %s", year, why)
        return False
    if btn is None:
        sel, years = year_select(page)
        if sel is not None and years:
            return year in years and _select_option(page, sel, year)
        if offered:
            log.info("year %s not chosen, the year picker that offered it is gone", year)
            return False
        return True
    if current_period(page) == year:
        return True
    try:
        btn.click()
        page.wait_for_timeout(1000)


        opt = page.get_by_role("option", name=re.compile(rf"^\s*{year}\b"))
        if opt.count() == 0:
            page.keyboard.press("Escape")
            log.info("year %s not offered by the picker", year)
            return False
        opt.first.click()
        page.wait_for_timeout(3500)
        dismiss_timeout(page)
        if current_period(page) != year:
            log.info("year picker still shows %r after selecting %s",
                     current_period(page), year)
        return True
    except Exception as e:
        log.info("could not select year %s: %s", year, e)
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        return False


_CARD_MASK_RE = re.compile(
    r"(\(\s*\.{2,}\s*\d{4}\s*\)|\.{3,}\s*\d{4}"
    r"|[*x\u00b7\u2022]{2,}\s*\d{4}|ending\s+(?:in\s+)?\d{4})", re.I)


_NOT_CARD_WORD_RE = re.compile(
    r"^(statements?|documents?|e-?statements?|pdf|file|link|download|view|open|"
    r"save|saves|print|opens|tax|form|summary|billing|monthly|annual|year|"
    r"year-end|account|for|the|of|and|on|dated|20\d{2}|\d{1,2}|"
    r"jan\w*|feb\w*|mar\w*|apr\w*|may|jun\w*|jul\w*|aug\w*|sep\w*|oct\w*|"
    r"nov\w*|dec\w*)[,:;.]?$", re.I)

_ROW_NOISE_RE = re.compile(
    r"\b(saves?\s+document|opens?\s+document|download(s|ing)?|view(s|ing)?|"
    r"open(s|ing)?|save(s|ing)?|print(s|ing)?|pdf|link|in\s+a\s+new\s+"
    r"(tab|window)|file)\b", re.I)

_MONTHS_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def card_in_row(name: str) -> str:
    text = " ".join((name or "").split())
    m = _CARD_MASK_RE.search(text)
    if not m:
        return ""
    mask = " ".join(m.group(1).split())
    kept: List[str] = []
    for word in reversed(text[:m.start()].split()):
        if _NOT_CARD_WORD_RE.match(word) or len(kept) >= 8:
            break
        kept.insert(0, word)
    return " ".join(kept + [mask])


def doc_title_in_row(name: str, card: str = "") -> str:
    text = " ".join((name or "").split())
    for pattern, _kind in DATE_PATTERNS:
        text = pattern.sub(" ", text)
    text = MONTH_YEAR_RE.sub(" ", text)
    if card:
        text = text.replace(card, " ")
    text = _CARD_MASK_RE.sub(" ", text)
    text = _ROW_NOISE_RE.sub(" ", text)
    text = re.sub(r"[\-\u2013\u2014,:;|.]+", " ", text)
    text = " ".join(text.split()).strip()
    return text[:120] or "Statement"


def is_safe_row_control(name: str) -> bool:
    text = " ".join((name or "").split())
    if not text:
        return False
    card = card_in_row(text)
    if card:
        if not is_card_control(card):
            return False
        text = text.replace(card, " ")
    return is_safe_control(text)


def _row_controls(page, limit: int = 400):
    """Each link and button whose name says it is a document's, with its
    words. Raises RowUnread when they would not be counted or one would not
    give its words, since that one may be a statement, where it used to be
    passed over and the names read whole without it."""
    for role in ("link", "button"):
        try:
            loc = page.get_by_role(role, name=SAFE_DOC_CONTROL_RE)
            n = min(loc.count(), limit)
        except Exception as e:
            raise RowUnread("the statement links would not answer") from e
        for i in range(n):
            c = loc.nth(i)
            try:
                name = " ".join((c.get_attribute("aria-label") or "").split())
                if not name:
                    name = " ".join((c.inner_text(timeout=800) or "").split())
            except Exception as e:
                raise RowUnread("a statement link would not answer") from e
            if name:
                yield c, name


def _rows_generic(page, account: str) -> List[dict]:
    out: List[dict] = []
    for _c, name in _row_controls(page):
        if not is_safe_row_control(name):
            continue
        date = _row_own_date(name)
        if not date:
            continue
        card = card_in_row(name) or account
        out.append({"documentId": "", "date": date,
                    "title": doc_title_in_row(name, card),
                    "account": card, "kind": "statement",
                    "occurrence": 0, "ambiguous": False})
    return out


def read_rows(page, account: str = "") -> Read:
    """The statements the list shows, drawn when a statements section was
    on the page to read them from. A list that would not be counted raises
    RowUnread, where it was read as a page with no list, or as a list with
    nothing in it."""
    account = account or account_name(page)
    try:
        have_list = page.locator(f"{SEL['list']} {SEL['section']}").count() > 0
    except Exception as e:
        raise RowUnread("the statement list would not answer") from e
    if not have_list:
        # Where the statement list or the account picker is on the page, a
        # list with no section is one still drawing or with nothing in it.
        # Reading the page's names there took the year picker, "Statement
        # year 2031", for a statement of December 31st (#106).
        try:
            ours = page.locator(f"{SEL['list']}, {SEL['account']}").count() > 0
        except Exception as e:
            raise RowUnread("the statement list would not answer") from e
        if ours:
            log.info("no statements section in the list")
            return Read()
        log.info("statement list container not found - reading names instead")
        return Read(_rows_generic(page, account))

    out: List[dict] = []
    seen: dict = {}
    unread = 0
    try:
        rows = list(_statement_rows(page, seen))
    except RowUnread as e:
        log.info("the statement list could not be read whole, %s", e)
        raise
    for row, heading in rows:
        _button, aria = _row_download_button(row)
        if not aria:
            continue
        if not is_safe_row_control(aria):
            log.info("row control %r did not clear the guard", aria[:70])
            unread += 1
            continue
        date = row_date(aria)
        if not date:
            log.info("no date in row control %r", aria[:70])
            unread += 1
            continue
        out.append({"documentId": "", "date": date, "title": "Statement",

                    "account": account_in_heading(heading) or account,
                    "kind": "statement", "occurrence": 0, "ambiguous": False})
    return _read(out, drawn=seen.get("statement_sections", 0) > 0, unread=unread,
                 heads=tuple(seen.get("headings", ())))


def _last_four(label: str) -> str:
    found = re.findall(r"\d{4}", label or "")
    return found[-1] if found else ""


def _another_account(account: str, chosen: str, offered=()) -> bool:
    """Whether a row's account, from its section's heading, is another one
    the picker offers than the one chosen, told by the last four digits, so
    that a heading written another way than the picker's label is still the
    same account. False when either names no digits, or when the digits are
    no account the picker offers, a row then kept as the chosen one's."""
    a, c = _last_four(account), _last_four(chosen)
    return bool(a and c and a != c and a in {_last_four(o) for o in offered})


def _the_chosen_account(heads, chosen: str) -> bool:
    """Whether every statements section on show is headed by the account
    chosen or by no account, told by the last four digits."""
    c = _last_four(chosen)
    return all(not _last_four(h) or not c or _last_four(h) == c for h in heads)


def _year_on_show(page) -> str:
    """The year the year picker shows, from its selection or else the one
    year its filter's text names. "" when it shows none to be read."""
    shown = current_period(page)
    if shown:
        return shown
    try:
        text = page.locator(SEL["year_filter"]).first.inner_text(timeout=1500) or ""
    except Exception:
        return ""
    # Digits on either side end it, not words, since its label and its
    # year can run together in the text, "Statement year2031".
    years = set(re.findall(r"(?<!\d)20\d{2}(?!\d)", text))
    return years.pop() if len(years) == 1 else ""


# How many more times, a second apart, the year picker is read after a
# choice that it shows another year for, before the choice is taken not to
# have been made, since its label can be drawn again a moment after it.
CHOICE_LOOKS = 3


def _shows_another_year(page, year: str) -> bool:
    """Whether the year picker shows one year, not `year`, after `year` was
    chosen, at every look. A picker that shows no year to be read, or more
    than one, says nothing either way, and is not taken for one that went
    back."""
    for look in range(CHOICE_LOOKS + 1):
        shown = set(re.findall(r"(?<!\d)20\d{2}(?!\d)", _year_on_show(page)))
        if len(shown) != 1 or shown == {str(year)}:
            return False
        if look < CHOICE_LOOKS:
            page.wait_for_timeout(1000)
    return True


def read_card_rows(page, label: str) -> List[dict]:
    if not select_account(page, label):
        return []
    return read_rows(page, label)


def card_groups(page) -> List[Tuple[object, str]]:
    return [(None, label) for label in account_options(page)]


def usbank_collect_structured(page, keep=None) -> Read:
    """keep, when given, says which year-picker options a scoped run wants.
    Years it refuses are not selected at all, which is the three seconds a
    year this saves. An unscoped run passes None and walks every year.

    Each account the picker offers is chosen in turn and its years read
    after it, since accounts need not share years. Each statement is listed
    under the account it was read under (listed_under), the one the
    download chooses again. Whole when every account the picker offered
    was read from its options, chosen and walked, and years holds each year
    whose list drew under every account, the part of the history a record
    may be judged by.

    passed_over names each picker the walk could not read through, one
    whose accounts or years it would not list, or a choice of account or
    year that did not take. What was read is kept, and the list is never
    noted whole without the rest (#106 review). The statements page not
    opening again raises RowUnread, since no list on it was read."""
    if not ensure_statements(page):
        raise RowUnread("the statements page did not open again")
    if not _wait_for_list(page):
        log.info("U.S. Bank: no statement list drew in %d s", LIST_WAIT_MS // 1000)
    if not _wait_for_year_picker(page):
        log.info("U.S. Bank: no year picker drew in %d s", YEAR_WAIT_MS // 1000)

    passed_over = set()
    picked = account_options(page)
    if getattr(picked, "not_read", ""):
        log.info("U.S. Bank: %s", picked.not_read)
        passed_over.add("account picker")
    accounts = list(picked) or [account_name(page)]
    whole = bool(getattr(picked, "whole", False))
    pick_each = bool(getattr(picked, "pick_each", False))
    log.info("U.S. Bank: %d account(s)", len(accounts))

    found: List[dict] = []
    years = None
    shown = unchosen = 0
    year_picker_seen = False
    for acct in accounts:
        if (len(accounts) > 1 or pick_each) and not select_account(page, acct):
            log.info("  could not choose the account %r", (acct or "(account)")[:60])
            whole = False
            unchosen += 1
            passed_over.add("account picker")
            continue
        if year_picker_seen:
            # The year picker an account before showed may be drawn again
            # a moment after this one is chosen, as it is when the page
            # opens (#116).
            _wait_for_year_picker(page)
        offered = period_options(page)
        year_picker_seen = year_picker_seen or bool(offered)
        if getattr(offered, "not_read", ""):
            log.info("U.S. Bank: %s", offered.not_read)
            passed_over.add("year picker")
        periods = list(offered) or [""]
        if keep is not None:
            wanted = [p for p in periods if keep(p)]
            if len(wanted) < len(periods):
                log.info("U.S. Bank: skipping %d year(s) outside the run's scope",
                         len(periods) - len(wanted))
            periods = wanted or [""]
        log.info("U.S. Bank: %s x %d year(s)", (acct or "(account)")[:60], len(periods))
        drew = set()
        for period in periods:
            if period and not select_period(page, period, offered=True):
                whole = False
                passed_over.add("year picker")
                continue
            if period and _shows_another_year(page, period):
                # The list on show is another year's, read as that year's
                # rows are always read, and this year was not.
                log.info("  the year picker shows another year after %s was chosen", period)
                passed_over.add("year picker")
            rows = read_rows(page, acct)
            if not rows:
                # An empty list may be one still loading. It is read again
                # once it has had time to settle, and only then taken as
                # empty.
                try:
                    page.wait_for_timeout(2000)
                except Exception:
                    pass
                rows = read_rows(page, acct)
            # A row headed by another account the picker offers is that
            # account's, still on show from before, and is read under its
            # own account when that one is chosen.
            mine = [r for r in rows if not _another_account(r.get("account", ""), acct, accounts)]
            stale = len(rows) - len(mine)
            log.info("  %s %s: %d statement(s)%s",
                     (acct or "(account)")[:60], period or "(current)", len(mine),
                     ", %d of another account passed over" % stale if stale else "")
            for r in mine:
                r["listed_under"] = acct
            found.extend(mine)
            if not mine:
                # Statements this view shows that nothing was read from. The
                # walk ends on whatever view it last chose, often one with no
                # statements, so they are counted here, view by view.
                shown = max(shown, download_controls_shown(page))
            # A year's list drew when the picker shows that year, a
            # statements section was read with every Download in it, every
            # section is headed by the account chosen or by none, and any
            # statement in it is of that year.
            # A list still showing the year before is not this year's.
            if (period and getattr(rows, "drawn", False) and not stale
                    and _the_chosen_account(getattr(rows, "heads", ()), acct)
                    and not getattr(rows, "unread", 0) and _year_on_show(page) == period
                    and (not rows or any(str(r.get("date", ""))[:4] == period for r in rows))):
                drew.add(period)
        years = drew if years is None else years & drew

    out, seen, twins = [], set(), 0
    for rec in found:
        key = (rec["account"], rec["date"], rec["title"])
        if key in seen:
            twins += 1
            continue
        seen.add(key)
        out.append(rec)
    if twins:
        # The same year can be read under more than one picker choice, so a
        # repeat is often the same row. Two rows of one date are told apart
        # by nothing, and the download refuses that date (find_row_control).
        log.info("U.S. Bank: %d listed row(s) repeat another's account and date and are listed once",
                 twins)
    out.sort(key=lambda r: (r["date"], r["account"]), reverse=True)
    return _read(out, whole=whole and bool(years), years=tuple(sorted(years or ())),
                 shown=shown, unchosen=unchosen, passed_over=tuple(sorted(passed_over)))


# A Download control for a statement, a button or a link whose name says
# Download and names a statement or a date.
STATEMENT_DOWNLOAD_RE = re.compile(
    r"^\s*download\b.*(statement|\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d"
    r"|\d{1,2}\/\d{1,2}\/\d{4}|\d{4}-\d{2}-\d{2})", re.I)


def download_controls_shown(page) -> int:
    """How many Download controls for a statement the page shows. A count
    that would not answer is taken as one, since a page that could not be
    counted is not a page without any."""
    n = 0
    for role in ("button", "link"):
        try:
            n += page.get_by_role(role, name=STATEMENT_DOWNLOAD_RE).count()
        except Exception:
            return max(n, 1)
    return n


_FETCH_AS_B64 = r"""async (u) => {
    const ppTarget = new URL(u, location.href);
    const ppOrigin = ppTarget.protocol === "blob:" ? new URL(u.slice(5)) : ppTarget;
    if (ppOrigin.protocol !== "https:" || !["onlinebanking.usbank.com", "www.usbank.com"].includes(ppOrigin.hostname) || ppOrigin.username || ppOrigin.password || (ppOrigin.port && ppOrigin.port !== "443")) throw new Error("Refusing an off-host document request");
    const r = await fetch(u, {redirect: 'error', credentials: 'include'});
    if (!r.ok) return null;
    const buf = await ppRead(r);
    let s = ''; for (let i = 0; i < buf.length; i++) s += String.fromCharCode(buf[i]);
    return btoa(s);
}"""


def _write_if_pdf(data: bytes, out_path: Path) -> bool:
    if not data or b"%PDF-" not in data[:1024]:
        return False
    shared_folder.write_bytes(out_path, data)
    return True


def row_label_re(date: str, account: str = "", action: str = ""):
    year = date[:4]
    month = int(date[5:7])
    day = int(date[8:10])
    mon = _MONTHS_ABBR[month - 1]
    forms = [
        rf"{mon}\w*\.?\s+0?{day}(?!\d),?\s*{year}",
        rf"0?{month}/0?{day}(?!\d)/{year}",
        rf"{year}-{month:02d}-{day:02d}",
    ]
    pattern = "(?:" + "|".join(forms) + ")"
    if account:
        pattern += rf".*{re.escape(account)}"
    if action:
        pattern += rf".*{re.escape(action)}"
    return re.compile(pattern, re.I | re.S)


@dataclass
class Attempt:
    """How a download went, true only when the statement was saved. One
    that saved nothing names the step that stopped it and why, in words of
    our own, and holds what the search for its row counted.

    Every download that came back with nothing was written down as a
    document that would not render, and for three rounds a tester's runs
    were read that way when nothing had been pressed at all (#106)."""
    saved: bool = False
    step: str = ""
    reason: str = ""
    row_search: dict = field(default_factory=dict)

    def __bool__(self) -> bool:
        return bool(self.saved)


def usbank_download(page, ctx, account: str, date: str, out_path,
                    occurrence: int = 0, document_id: str = "",
                    title: str = "", listed_under: str = "") -> Attempt:
    """Choose the account the statement was listed under, then its year,
    then press its row. `account` is the statement's own, which finds its
    row. `listed_under`, the picker's label it was read under, chooses the
    account, `account` when it is not known."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    dismiss_timeout(page)
    if not ensure_statements(page):
        log.info("documents page not available for %r %s", account, date)
        return Attempt(step="open the statements page", reason="the statements page would not open")
    # The page draws its pickers and its list a moment after it opens.
    _wait_for_list(page)
    _wait_for_year_picker(page)
    choice = listed_under or account
    if choice and not select_account(page, choice):
        log.info("could not select the account %r", choice[:60])
        return Attempt(step="choose the account", reason="the account picker did not take it")
    if not select_period(page, date[:4]):
        log.info("year %s not offered - cannot reach %s %s", date[:4], account, date)
        return Attempt(step="choose the year", reason="the year picker did not take it")
    _wait_for_list(page, REDRAW_MS)
    search = row_search(page, date, account)
    if search.button is None:
        log.info("no Download control for %s on %s, %s",
                 account[:60] or "(account)", date, search.reason)
        return Attempt(step="find the statement", reason=search.reason, row_search=search.counts)
    if not _press_and_capture(page, ctx, search.button, search.label, date, out_path):
        return Attempt(step="capture the document", reason="no document came of the press",
                       row_search=search.counts)
    return Attempt(saved=True, step="capture the document", row_search=search.counts)


class RowUnread(Exception):
    """A part of the statement list that would not answer a read, a
    section's heading, its rows or a row's buttons. One that could not be
    read is never taken to be absent, since it may be the very statement
    asked for or its twin (#106)."""


def _statement_rows(page, seen: Optional[dict] = None):
    """Each row of each statements section, with its section's heading.
    Raises RowUnread when a heading or a section's rows would not answer.
    `seen`, when given, is told how many sections there were and how many
    of them were statements sections."""
    try:
        sections = page.locator(f"{SEL['list']} {SEL['section']}")
        n = sections.count()
    except Exception as e:
        raise RowUnread("the statement sections would not answer") from e
    if seen is not None:
        seen["sections"] = n
        seen.setdefault("statement_sections", 0)
    for i in range(n):
        sec = sections.nth(i)
        try:
            headings = sec.locator("h3").count()
        except Exception as e:
            raise RowUnread("a section's heading would not answer") from e
        if not headings:
            # A list with no heading at all is no statements section when it
            # holds no rows either, and is passed over as before. One with
            # rows could be statements under a heading not drawn, so it is
            # not taken as absent.
            try:
                if not sec.locator(SEL["row"]).count():
                    continue
            except Exception as e:
                raise RowUnread("a section's rows would not answer") from e
            raise RowUnread("a section with rows has no heading")
        try:
            heading = " ".join((sec.locator("h3").first.inner_text(timeout=2000) or "").split())
        except Exception as e:
            raise RowUnread("a section's heading would not answer") from e
        if not STATEMENT_SECTION_RE.search(heading):
            continue
        if seen is not None:
            seen["statement_sections"] += 1
            seen.setdefault("headings", []).append(account_in_heading(heading))
        try:
            rows = sec.locator(SEL["row"])
            rn = min(rows.count(), 400)
        except Exception as e:
            raise RowUnread("a section's rows would not answer") from e
        for j in range(rn):
            yield rows.nth(j), heading


def account_in_heading(heading: str) -> str:
    text = re.sub(r"\s*statements\s*$", "", " ".join((heading or "").split()),
                  flags=re.I).strip()
    return text if is_card_control(text) else ""


def _row_download_button(row):
    """A row's Download button and its label, or (None, "") for a row with
    none. Raises RowUnread when the row's buttons would not answer."""
    try:
        btns = row.locator("button")
        n = min(btns.count(), 4)
    except Exception as e:
        raise RowUnread("a row's buttons would not answer") from e
    for k in range(n):
        b = btns.nth(k)
        try:
            aria = " ".join((b.get_attribute("aria-label") or "").split())
        except Exception as e:
            raise RowUnread("a row's button would not answer") from e
        if ROW_DOWNLOAD_ARIA_RE.match(aria):
            return b, aria
    return None, ""


_ORDINAL_RE = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)\b", re.I)


def row_date(aria: str) -> str:
    """The date a row's Download label names, read one way for the list and
    for the download (#106). A day written as an ordinal, "September 15th,
    2031", is read as that day, where before it matched no date and fell
    to the year alone, the last day of December for every such row. A month
    and a year alone is that month's last day. "" for a label naming none."""
    m = ROW_DOWNLOAD_ARIA_RE.match(aria or "")
    if not m:
        return ""
    return parse_period_date(_ORDINAL_RE.sub(r"\1", m.group(1)))[0] or ""


def find_row_control(page, date: str, account: str = ""):
    """The Download button of the statement of `date`, read the way the
    list read it (read_rows), or (None, "").

    The download used to look for the row again with a pattern of its own
    that wanted the exact day, while the list took a statement's date from
    its button's label with parse_period_date, which also reads a month and
    a year alone, and files that statement on the month's last day. On a
    page whose labels name only the month, or write the day another way,
    every statement listed was then not found, and a Pilot stopped on the
    first one before any press, with every part of the list on the page
    (#106). Now a row is this statement's when its label reads to this very
    date the same way (row_date). Two rows reading to one date cannot be told apart,
    so neither is pressed, whether or not the guard would pass the other.
    A heading, a row or a button that would not answer could be this
    statement or its twin, so nothing is pressed then either (RowUnread)."""
    found = row_search(page, date, account)
    if found.button is None:
        return None, ""
    return found.button, found.label


@dataclass
class Search:
    """What the search for a statement's row found and saw. `button` is the
    row's Download button and `label` its name, or None with `reason`
    saying why in words of our own. `counts` holds counts only, for the
    failure file, so it can say whether the page had no list, no row of
    that date, of that month or of that year, or two."""
    button: object = None
    label: str = ""
    reason: str = ""
    counts: dict = field(default_factory=dict)


def _counted(counts: dict, seen: dict) -> None:
    """The section counts _statement_rows saw, into a failure file's counts.
    Only the counts, never the headings it also keeps, which name accounts."""
    for name in ("sections", "statement_sections"):
        counts[name] = int(seen.get(name, 0) or 0)


def row_search(page, date: str, account: str = "") -> Search:
    """The search find_row_control makes, with what it saw."""
    counts = {"sections": 0, "statement_sections": 0, "other_account_rows": 0, "rows": 0,
              "with_download": 0, "this_year": 0, "this_month": 0, "this_date": 0}
    seen: dict = {}
    found = []
    try:
        for row, heading in _statement_rows(page, seen):
            if account and account_in_heading(heading) not in ("", account):
                counts["other_account_rows"] += 1
                continue
            counts["rows"] += 1
            button, aria = _row_download_button(row)
            if button is None:
                continue
            counts["with_download"] += 1
            got = row_date(aria)
            counts["this_year"] += int(bool(got) and got[:4] == date[:4])
            counts["this_month"] += int(bool(got) and got[:7] == date[:7])
            if got == date:
                counts["this_date"] += 1
                found.append((button, aria))
    except RowUnread as e:
        _counted(counts, seen)
        log.info("pressed nothing for %s, %s", date, e)
        return Search(reason="the statement list would not answer", counts=counts)
    _counted(counts, seen)
    if not counts["sections"]:
        return Search(reason="no statement list on the page", counts=counts)
    if len(found) > 1:
        log.info("%d rows read as the statement of %s, so none is pressed", len(found), date)
        return Search(reason="two rows read as this date", counts=counts)
    if not found:
        return Search(reason="no row reads as this date", counts=counts)
    button, aria = found[0]
    if not is_safe_row_control(aria):
        log.info("row control %r did not clear the guard", aria[:70])
        return Search(reason="the row control did not clear the guard", counts=counts)
    return Search(button=button, label=aria, counts=counts)


def _click_row_and_capture(page, ctx, account: str, date: str,
                           out_path: Path) -> bool:
    link, label = find_row_control(page, date, account)
    if link is None:
        log.info("no Download control for %s on %s",
                 account[:40] or "(account)", date)
        return False
    return _press_and_capture(page, ctx, link, label, date, out_path)


def _press_and_capture(page, ctx, link, label: str, date: str, out_path: Path) -> bool:
    """Press a row's Download button and save what comes of it, a download
    or a window on U.S. Bank's own hosts. Every tab the press opened is
    closed, whatever came of it."""
    before = {id(p) for p in ctx.pages}
    try:
        try:
            with page.expect_download(timeout=30000) as dl:
                link.click()
            intake.save_download_as(dl.value, out_path)
            # A tax form that comes as a ZIP holding its PDF is kept for the
            # docs module, which opens it.
            if out_path.exists() and _is_document(out_path.read_bytes()[:5], zip_ok=True):
                log.info("captured via download event (%s)", label[:60])
                return True
        except Exception as e:
            log.info("no download event for %s (%s); trying the View window",
                     date, str(e).splitlines()[0][:60])


        new_page = None
        for _ in range(30):
            page.wait_for_timeout(500)
            dismiss_timeout(page)
            for p in ctx.pages:
                candidate = p.url or ""
                safe = is_safe_url(candidate[5:] if candidate.startswith("blob:") else candidate)
                if id(p) not in before and not p.is_closed() and safe:
                    new_page = p
                    break
            if new_page:
                break
        if new_page is None:
            log.info("nothing opened for %s", date)
            return False

        ok = False
        try:
            new_page.wait_for_load_state("domcontentloaded", timeout=20000)
            url = new_page.url or ""
            b64 = intake.evaluate(page if url.startswith("blob:") else new_page,
                                  _FETCH_AS_B64, url)
            if b64:
                ok = _write_if_pdf(intake.decode(b64), out_path)
                if ok:
                    log.info("captured via new window (%s)", url[:70])
        except Exception as e:
            log.info("window capture failed for %s: %s", date, e)
        return ok
    finally:
        # However the press ended. A window the look above never took, one
        # off U.S. Bank's hosts, was never closed and stayed open in the
        # person's browser, and only the one window read was ever closed, so
        # a second window from the same press stayed open too.
        _close_tabs_opened_since(ctx, before)


def _close_tabs_opened_since(ctx, before) -> None:
    """Close every tab that was not open before the press, `before` holding
    the ids of those that were. The window read, a window never taken for
    its address and a window never looked at are closed alike, and nothing
    on any of them is read. Nothing here raises."""
    try:
        tabs = list(ctx.pages)
    except Exception:
        return
    for tab in tabs:
        if id(tab) in before:
            continue
        try:
            if not tab.is_closed():
                tab.close()
        except Exception:
            pass


_DIGITS_RE = re.compile(r"\d{4,}")


DOCLIST_API_RE = re.compile(
    r"/(document|statement|edocument|estatement|docref)[\w-]*"
    r"(/[\w-]+)*/(list|search|history|index|documents|statements)\b", re.I)


def _redact(value):
    if isinstance(value, str):
        return _DIGITS_RE.sub(lambda m: m.group(0)[:2] + "…" + m.group(0)[-2:], value)
    return value


def _doc_records(payload) -> List[dict]:
    out: List[dict] = []
    if isinstance(payload, list):
        out.extend(x for x in payload if isinstance(x, dict))
    elif isinstance(payload, dict):
        for value in payload.values():
            if isinstance(value, list) and any(isinstance(x, dict) for x in value):
                out.extend(x for x in value if isinstance(x, dict))
    return out


def probe_statements_api(page) -> dict:
    raw: List[dict] = []
    rows: List[dict] = []

    def on_resp(r):
        try:
            if not DOCLIST_API_RE.search(r.url):
                return
            if "json" not in (r.headers.get("content-type", "") or "").lower():
                return
            raw.extend(_doc_records(whole_json(r.json())))
        except Exception:
            pass

    page.on("response", on_resp)
    try:
        ensure_statements(page)
        page.wait_for_timeout(1500)


        newest = (period_options(page) or [""])[0]
        if newest:
            select_period(page, newest)
        accounts = account_options(page)
        if len(accounts) > 1:
            for label in accounts:
                rows.extend(read_card_rows(page, label))
        else:
            rows.extend(read_rows(page))
    except Exception as e:
        log.info("probe_statements_api: %s", e)
    finally:
        try:
            page.remove_listener("response", on_resp)
        except Exception:
            pass

    keys: dict = {}
    for rec in raw:
        for k, v in rec.items():
            info = keys.setdefault(k, {"present": 0, "empty": 0, "distinct": set()})
            info["present"] += 1
            if v in ("", None, [], {}):
                info["empty"] += 1
            elif len(info["distinct"]) < 12:
                info["distinct"].add(str(_redact(v))[:60])

    by_card: dict = {}
    for r in rows:
        by_card[r["account"] or "(no card printed)"] = \
            by_card.get(r["account"] or "(no card printed)", 0) + 1

    return {
        "api_records": len(raw),
        "fields": {k: {"present": v["present"], "empty": v["empty"],
                       "distinct_sample": sorted(v["distinct"])[:12]}
                   for k, v in sorted(keys.items())},
        "rows_shown": len(rows),
        "rows_per_card": {_redact(k): v for k, v in sorted(by_card.items())},
        "note": "UNVERIFIED app: 0 api_records may simply mean U.S. Bank uses "
                "no such endpoint, or that DOCLIST_API_RE does not match its "
                "route - check api_candidates for what it actually called. "
                "Discovery files documents by ROW either way.",
    }


def probe_api(page, seconds: int = 25) -> List[dict]:
    hits: List[dict] = []

    def on_resp(r):
        try:
            ct = (r.headers.get("content-type", "") or "").lower()
            if "json" not in ct:
                return
            body = r.text()
            if len(body) > 400000:
                body = body[:400000]
            low = body.lower()
            if not any(k in low for k in ("statement", "document", "pdf", "taxform")):
                return
            data = whole_json(json.loads(body))
            keys = list(data.keys())[:20] if isinstance(data, dict) else ["<list>"]
            hits.append({"url": r.url.split("?")[0], "status": r.status,
                         "top_keys": keys, "sample": _redact(body[:600])})
        except Exception:
            pass

    page.on("response", on_resp)
    try:
        ensure_statements(page)
        page.wait_for_timeout(3000)
        expand_all(page)
        scroll_full_page(page, rounds=4)
        acct_sel, accounts = account_select(page)
        if acct_sel is not None:
            # As usbank_collect's walk, chosen with no look at the list.
            _note_choice(page, True)
            for a in accounts[:3]:
                _select_option(page, acct_sel, a)
        for p in (period_options(page) or [])[:3]:
            select_period(page, p)
        page.wait_for_timeout(int(seconds * 100))
    except Exception as e:
        log.info("probe_api: %s", e)
    finally:
        try:
            page.remove_listener("response", on_resp)
        except Exception:
            pass


    out, seen = [], set()
    for h in hits:
        if h["url"] in seen:
            continue
        seen.add(h["url"])
        out.append(h)
    return out
