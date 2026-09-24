"""Credit-card statements only. Read the Download controls under statement
section headings, using the heading for account attribution. Sweep the year
picker, including empty years. Re-find rows by accessible labels at download
time; verify PDF bytes and discard incomplete captures.

All requests and navigation must stay on explicitly allowed provider hosts.
"""


from __future__ import annotations

import base64
import html as _html
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from paperpull_core.controls import SETTINGS_CONTROL_RE, AUTH_CONTROL_RE
from paperpull_core.urls import is_safe_url as _host_allows
from paperpull_core.controls import click_next_page as _click_next_page
from paperpull_core.dates import last_day as _last_day
from paperpull_core.dates import checked as _checked_date

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
    "account_select": "select, [role='combobox'], [role='listbox']",
    "next_page": ("a[aria-label*='Next' i], button[aria-label*='Next' i], "
                  ".pagination-next, [class*='next']"),
    "show_more": "button, a",
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


_ROW_JS = r"""() => {
  const DATE_RE = /(\d{1,2}\/\d{1,2}\/\d{4})|((Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4})|((Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4})/i;
  const CTRL = "a[href$='.pdf'], a[download], a[aria-label], button[aria-label], a, button";
  const SAFE = /(download|view|open|save|print|pdf|statement|document|1099|1098|5498|tax)/i;
  const rows = new Set();
  for (const sel of ['table tr', "[role='row']", "li", "[class*='statement']", "[class*='document']"]) {
    for (const el of document.querySelectorAll(sel)) rows.add(el);
  }
  const out = [];
  for (const el of rows) {
    // skip containers that hold other candidate rows (keep the innermost)
    if (el.querySelector("table tr, [role='row']")) continue;
    const text = (el.innerText || '').replace(/\s+/g, ' ').trim();
    if (!text || text.length > 400) continue;
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


def collect_documents(page) -> List[RawDoc]:
    docs: List[RawDoc] = []
    seen = set()
    try:
        rows = page.evaluate(_ROW_JS)
    except Exception as e:
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


def account_select(page):
    for s, _identity in _safe_selects(page):
        try:
            opts = [o.strip() for o in s.locator("option").all_inner_texts()]
        except Exception:
            continue
        accts = [o for o in opts if o and _ACCOUNT_HINT_RE.search(o)
                 and not re.fullmatch(r"20\d{2}", o)]
        if accts:
            return s, accts
    return None, []


def year_select(page):
    for s, _identity in _safe_selects(page):
        try:
            opts = [o.strip() for o in s.locator("option").all_inner_texts()]
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


def usbank_collect(page) -> List[dict]:
    docs: List[dict] = []
    seen = set()

    def grab(acct: str):
        expand_all(page)
        scroll_full_page(page, rounds=3)
        for r in collect_documents(page):
            date, _ = parse_period_date(r.date_text or r.text)
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
            grab(acct)

            for _ in range(30):
                if not next_page(page):
                    break
                grab(acct)

    acct_sel, accounts = account_select(page)
    if acct_sel is not None and accounts:
        for a in accounts:
            if not _select_option(page, acct_sel, a):
                continue
            walk_years(re.sub(r"\s+", " ", a).strip())
    else:
        walk_years("")
    return docs


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


def account_name(page) -> str:
    try:
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


def account_options(page) -> List[str]:
    try:
        holder = page.locator(SEL["account"]).first
        if holder.count() == 0:
            return []
        btn = holder.locator("button[aria-expanded], [role='combobox']")
        if btn.count() == 0:
            one = account_name(page)
            return [one] if one else []
    except Exception:
        return []
    try:
        identity = control_identity(btn.first)
        if is_money_control(identity):
            log.info("refusing account picker (money control): %s", identity[:120])
            return []
        btn.first.click()
        page.wait_for_timeout(1200)
        labels = [" ".join(t.split())
                  for t in page.get_by_role("option").all_inner_texts()]
        page.keyboard.press("Escape")
        page.wait_for_timeout(400)
        out = [x for x in labels if is_card_control(x)]
        for x in labels:
            if x and x not in out:
                log.info("refusing account option %r", x[:60])
        return out
    except Exception as e:
        log.info("account options failed: %s", e)
        one = account_name(page)
        return [one] if one else []


def select_account(page, label: str) -> bool:
    if not label or label == account_name(page):
        return True
    try:
        holder = page.locator(SEL["account"]).first
        btn = holder.locator("button[aria-expanded], [role='combobox']")
        if btn.count() == 0:
            return True
        if is_money_control(control_identity(btn.first)):
            log.warning("REFUSED to set the account picker (money control)")
            return False
        if not is_card_control(label):
            log.warning("REFUSED account option %r - not a card label", label[:60])
            return False
        btn.first.click()
        page.wait_for_timeout(1000)
        opt = page.get_by_role("option", name=re.compile(re.escape(label)))
        if opt.count() == 0:
            page.keyboard.press("Escape")
            log.info("account %r not offered", label[:40])
            return False
        opt.first.click()
        page.wait_for_timeout(3000)
        dismiss_timeout(page)
        return True
    except Exception as e:
        log.info("could not select account %r: %s", label[:40], e)
        return False


def _year_button(page):
    try:
        btn = page.locator(SEL["year_button"])
        if btn.count() == 0:
            return None
    except Exception:
        return None
    try:
        name = " ".join((btn.first.inner_text(timeout=1500) or "").split())
    except Exception:
        name = ""

    if not is_safe_control(name):
        log.info("year filter %r did not clear the guard", name[:60])
        return None
    if is_money_control(control_identity(btn.first)):
        log.info("refusing year filter (money control)")
        return None
    return btn.first


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


def period_options(page) -> List[str]:
    btn = _year_button(page)
    if btn is None:
        sel, years = year_select(page)
        return sorted(set(years), reverse=True) if years else []
    try:
        btn.click()
        page.wait_for_timeout(1200)
        years = sorted({t.strip() for t in page.get_by_role("option").all_inner_texts()
                        if re.fullmatch(r"20\d{2}", t.strip())}, reverse=True)
        page.keyboard.press("Escape")
        page.wait_for_timeout(400)
        return years
    except Exception as e:
        log.info("period options failed: %s", e)
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        return []


def select_period(page, year: str) -> bool:
    year = str(year)
    btn = _year_button(page)
    if btn is None:
        sel, years = year_select(page)
        if sel is not None and years:
            return year in years and _select_option(page, sel, year)
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
    for role in ("link", "button"):
        try:
            loc = page.get_by_role(role, name=SAFE_DOC_CONTROL_RE)
            n = min(loc.count(), limit)
        except Exception:
            continue
        for i in range(n):
            c = loc.nth(i)
            try:
                name = " ".join((c.get_attribute("aria-label") or "").split())
            except Exception:
                name = ""
            if not name:
                try:
                    name = " ".join((c.inner_text(timeout=800) or "").split())
                except Exception:
                    continue
            if name:
                yield c, name


def _rows_generic(page, account: str) -> List[dict]:
    out: List[dict] = []
    for _c, name in _row_controls(page):
        if not is_safe_row_control(name):
            continue
        date, _period = parse_period_date(name)
        if not date:
            continue
        card = card_in_row(name) or account
        out.append({"documentId": "", "date": date,
                    "title": doc_title_in_row(name, card),
                    "account": card, "kind": "statement",
                    "occurrence": 0, "ambiguous": False})
    return out


def read_rows(page, account: str = "") -> List[dict]:
    account = account or account_name(page)
    try:
        have_list = page.locator(f"{SEL['list']} {SEL['section']}").count() > 0
    except Exception:
        have_list = False
    if not have_list:
        log.info("statement list container not found - reading names instead")
        return _rows_generic(page, account)

    out: List[dict] = []
    for row, heading in _statement_rows(page):
        _button, aria = _row_download_button(row)
        if not aria:
            continue
        if not is_safe_row_control(aria):
            log.info("row control %r did not clear the guard", aria[:70])
            continue
        m = ROW_DOWNLOAD_ARIA_RE.match(aria)
        date, _period = parse_period_date(m.group(1))
        if not date:
            log.info("no date in row control %r", aria[:70])
            continue
        out.append({"documentId": "", "date": date, "title": "Statement",

                    "account": account_in_heading(heading) or account,
                    "kind": "statement", "occurrence": 0, "ambiguous": False})
    return out


def read_card_rows(page, label: str) -> List[dict]:
    if not select_account(page, label):
        return []
    return read_rows(page, label)


def card_groups(page) -> List[Tuple[object, str]]:
    return [(None, label) for label in account_options(page)]


def usbank_collect_structured(page, keep=None) -> List[dict]:
    """keep, when given, says which year-picker options a scoped run wants.
    Years it refuses are not selected at all, which is the three seconds a
    year this saves. An unscoped run passes None and walks every year."""
    if not ensure_statements(page):
        log.info("documents page not reachable")
        return []

    accounts = account_options(page) or [account_name(page)]
    periods = period_options(page) or [""]
    if keep is not None:
        wanted = [p for p in periods if keep(p)]
        if len(wanted) < len(periods):
            log.info("U.S. Bank: skipping %d year(s) outside the run's scope",
                     len(periods) - len(wanted))
        periods = wanted or [""]
    log.info("U.S. Bank: %d account(s) x %d year(s)", len(accounts), len(periods))

    found: List[dict] = []
    for acct in accounts:
        if len(accounts) > 1 and not select_account(page, acct):
            continue
        for period in periods:
            if period and not select_period(page, period):
                continue
            rows = read_rows(page, acct)
            log.info("  %s %s: %d statement(s)",
                     (acct or "(account)")[:34], period or "(current)", len(rows))
            found.extend(rows)

    out, seen = [], set()
    for rec in found:
        key = (rec["account"], rec["date"], rec["title"])
        if key in seen:
            continue
        seen.add(key)
        out.append(rec)
    out.sort(key=lambda r: (r["date"], r["account"]), reverse=True)
    return out


_FETCH_AS_B64 = r"""async (u) => {
    const ppTarget = new URL(u, location.href);
    const ppOrigin = ppTarget.protocol === "blob:" ? new URL(u.slice(5)) : ppTarget;
    if (ppOrigin.protocol !== "https:" || !["onlinebanking.usbank.com", "www.usbank.com"].includes(ppOrigin.hostname) || ppOrigin.username || ppOrigin.password || (ppOrigin.port && ppOrigin.port !== "443")) throw new Error("Refusing an off-host document request");
    const r = await fetch(u, {redirect: 'error', credentials: 'include'});
    if (!r.ok) return null;
    const buf = new Uint8Array(await r.arrayBuffer());
    let s = ''; for (let i = 0; i < buf.length; i++) s += String.fromCharCode(buf[i]);
    return btoa(s);
}"""


def _write_if_pdf(data: bytes, out_path: Path) -> bool:
    if not data or b"%PDF-" not in data[:1024]:
        return False
    out_path.write_bytes(data)
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


def usbank_download(page, ctx, account: str, date: str, out_path,
                    occurrence: int = 0, document_id: str = "",
                    title: str = "") -> bool:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    dismiss_timeout(page)
    if not ensure_statements(page):
        log.info("documents page not available for %r %s", account, date)
        return False
    if account and not select_account(page, account):
        log.info("could not select the account %r", account[:40])
        return False
    if not select_period(page, date[:4]):
        log.info("year %s not offered - cannot reach %s %s", date[:4], account, date)
        return False
    return _click_row_and_capture(page, ctx, account, date, out_path)


def _statement_rows(page):
    try:
        sections = page.locator(f"{SEL['list']} {SEL['section']}")
        n = sections.count()
    except Exception:
        return
    for i in range(n):
        sec = sections.nth(i)
        try:
            heading = " ".join((sec.locator("h3").first.inner_text(timeout=2000) or "").split())
        except Exception:
            heading = ""
        if not STATEMENT_SECTION_RE.search(heading):
            continue
        try:
            rows = sec.locator(SEL["row"])
            rn = min(rows.count(), 400)
        except Exception:
            continue
        for j in range(rn):
            yield rows.nth(j), heading


def account_in_heading(heading: str) -> str:
    text = re.sub(r"\s*statements\s*$", "", " ".join((heading or "").split()),
                  flags=re.I).strip()
    return text if is_card_control(text) else ""


def _row_download_button(row):
    try:
        btns = row.locator("button")
        n = min(btns.count(), 4)
    except Exception:
        return None, ""
    for k in range(n):
        b = btns.nth(k)
        try:
            aria = " ".join((b.get_attribute("aria-label") or "").split())
        except Exception:
            continue
        if ROW_DOWNLOAD_ARIA_RE.match(aria):
            return b, aria
    return None, ""


def find_row_control(page, date: str, account: str = ""):


    rx = row_label_re(date)
    for row, heading in _statement_rows(page):
        if account and account_in_heading(heading) not in ("", account):
            continue
        button, aria = _row_download_button(row)
        if button is None or not rx.search(aria):
            continue
        if not is_safe_row_control(aria):
            log.info("row control %r did not clear the guard", aria[:70])
            continue
        return button, aria
    return None, ""


def _click_row_and_capture(page, ctx, account: str, date: str,
                           out_path: Path) -> bool:
    link, label = find_row_control(page, date, account)
    if link is None:
        log.info("no Download control for %s on %s",
                 account[:40] or "(account)", date)
        return False

    before = {id(p) for p in ctx.pages}
    try:
        with page.expect_download(timeout=30000) as dl:
            link.click()
        dl.value.save_as(str(out_path))
        if out_path.exists() and out_path.read_bytes()[:5] == b"%PDF-":
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
        b64 = page.evaluate(_FETCH_AS_B64, url) if url.startswith("blob:") \
            else new_page.evaluate(_FETCH_AS_B64, url)
        if b64:
            ok = _write_if_pdf(base64.b64decode(b64), out_path)
            if ok:
                log.info("captured via new window (%s)", url[:70])
    except Exception as e:
        log.info("window capture failed for %s: %s", date, e)
    try:
        new_page.close()
    except Exception:
        pass
    return ok


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
            raw.extend(_doc_records(r.json()))
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
            data = json.loads(body)
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
