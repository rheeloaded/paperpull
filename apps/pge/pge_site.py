"""ALL PG&E (pge.com) selectors, URLs, and page behavior live here.

When PG&E changes its site, repair this file only.

SAFETY (this is a utility billing account):
  This module is strictly READ-ONLY. It navigates to the billing-history
  area, reads the list of bills, and downloads the PDFs PG&E already
  generated. It must NEVER activate any control that pays a bill, sets up
  AutoPay or a payment plan, adds or changes a bank account or card, starts,
  stops or transfers service, or changes any setting. FORBIDDEN_CONTROL_RE is
  the guard; a control must ALSO look like a document action
  (SAFE_DOC_CONTROL_RE) before it may be clicked. There is no code here that
  submits a form or confirms a dialog.

ROUND FOUR (#33, 2026-09-22). Round three's outline showed the control
plainly: a.pdf-link = "View Bill PDF", inside td > div.align-right, in
the light DOM. And still the row handed over nothing, which means the
selector queries on the row answer empty on this history. The page is a
Salesforce Lightning app, whose synthetic shadow DOM replaces
querySelectorAll on every element with one that hides a component's
children from anything outside the component. A walk over each node's
own children is not patched, which is how the outline saw the link. The
row's controls are now gathered by that walk, anchors and buttons and
anything whose own text reads View Bill PDF, and the rows are waited
for before they are read, since one discovery ran before the table had
drawn and found nothing.

ROUND THREE (#33, 2026-09-22). The tester's third pilot reported two
things. Every bill row read "09/20/2026 Bill Charges View Bill PDF
$xx.xx" and handed over no control, so "View Bill PDF" is not an anchor,
a button or a lightning-button on his history, and whatever element
carries the words was not in the list the app looked through. The row's
controls are now found by their own text, innermost element first,
whatever kind it is, and when a row still hands over nothing the log
prints the row's outline (tags, classes, roles, shadow roots) so the
next round sees it. And the Jump to picker opened without listing its
options, "no option for page 2 in the picker", so after the click the
picker is asked through its own value and change event, the way a
Lightning parent hears it, before giving up.
"""
from __future__ import annotations

import html as _html
import logging
import re
import time
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import urlsplit

from paperpull_core.dates import checked as _checked_date
from paperpull_core.controls import control_labels as _control_labels
from paperpull_core.controls import is_next_control as _core_is_next

log = logging.getLogger("pge_docs.site")

BASE = "https://myaccount.pge.com"
URLS = {
    "home": f"{BASE}/myaccount/s/",
    "login": f"{BASE}/myaccount/s/",
    "documents": f"{BASE}/myaccount/s/bill-and-payment-history",
    "statements": f"{BASE}/myaccount/s/bill-and-payment-history",
    "documents_alt": f"{BASE}/myaccount/s/",
}
# Only the history itself. The home page was on this list once, and landing
# there counted as success, so a run could report zero bills from a page that
# never had any.
DOCUMENT_URL_CANDIDATES = [URLS["documents"]]

LOGIN_URL_MARKERS = [
    "/login", "/signin", "/sign-in", "/site-signin", "/auth", "/mfa",
    "/verification", "/challenge", "sso.pge.com",
]

ALLOWED_HOSTS = [
    "www.pge.com", "pge.com", "myaccount.pge.com", "m.pge.com",
]

# ---------------------------------------------------------------------------
# HARD SAFETY GUARD - never click anything matching this. Tuned for a utility
# billing portal: never pay a bill, change service, or modify the account.
# ---------------------------------------------------------------------------
FORBIDDEN_CONTROL_RE = re.compile(
    r"(pay\b|payment|pay\s+bill|autopay|auto\s*pay|schedule\s+payment|"
    r"one[-\s]?time\s+payment|payment\s+plan|budget\s+billing|paperless|"
    r"bank\b|routing|account\s+number|debit|credit\s+card|\bcard\b|wallet|"
    r"enroll|unenroll|sign\s+up|start\s+service|stop\s+service|"
    r"transfer\s+service|disconnect|reconnect|new\s+service|move\s+service|"
    r"donate|contribution|round\s*up|"
    # Word boundaries on both sides of the verb stems. "edit" with only a
    # trailing boundary matches the end of "Credit", and a bill row that
    # carries a credit is exactly the sort of label this must let through.
    r"enable|disable|activate|deactivate|\bchang(e|es|ed|ing)\b|"
    r"\bedit(s|ed|ing)?\b|\bupdat(e|es|ed|ing)\b|modify|"
    r"set\s+up|delete|remove|cancel|close\s+account|"
    r"password|profile\b|settings|preferences|"
    r"confirm|submit|agree|accept|authorize|enroll|"
    r"save\s+changes|save\s+settings|update\s+settings|change\s+address|"
    r"edit\s+preferences|document\s+removal|loss\s+mitigation|"
    r"manage\s+autopay|turn\s+off|opt\s+out|update\s+beneficiary|"
    r"place\s+order|rebalance|liquidate|buy|sell)", re.I)

SAFE_DOC_CONTROL_RE = re.compile(
    r"(download|view|open|print|pdf|statement|document|bill|invoice|"
    r"report|history)", re.I)


def is_safe_control(label: str) -> bool:
    """Returns True ONLY if label names a document action and no forbidden verb."""
    if not label or not isinstance(label, str):
        return False
    text = label.strip()
    if not text:
        return False
    if FORBIDDEN_CONTROL_RE.search(text):
        return False
    # The settings and sign-in vocabulary every provider shares lives in core,
    # so a phrasing this list never thought of is still refused.
    from paperpull_core.controls import SETTINGS_CONTROL_RE, AUTH_CONTROL_RE
    if SETTINGS_CONTROL_RE.search(text) or AUTH_CONTROL_RE.search(text):
        return False
    return bool(SAFE_DOC_CONTROL_RE.search(text))


def control_label(el) -> str:
    """What a person would read on this control. Inner text first, then the
    accessible name, then the title, so a bare icon still has a label to be
    judged by and an unlabeled one is refused."""
    for getter in (lambda: el.inner_text(timeout=1500),
                   lambda: el.get_attribute("aria-label"),
                   lambda: el.get_attribute("title")):
        try:
            text = (getter() or "").strip()
        except Exception:
            text = ""
        if text:
            return re.sub(r"\s+", " ", text)
    return ""


def all_labels(el) -> str:
    """Every label a control carries, joined. The page picker's own text is
    the current page number and its purpose is in the aria-label, so a guard
    that reads only one of them cannot judge it."""
    parts = []
    for getter in (lambda: el.inner_text(timeout=1500),
                   lambda: el.get_attribute("aria-label"),
                   lambda: el.get_attribute("title"),
                   lambda: el.get_attribute("label")):
        try:
            text = (getter() or "").strip()
        except Exception:
            text = ""
        if text:
            parts.append(re.sub(r"\s+", " ", text))
    return " | ".join(parts)


def is_page_picker(label: str) -> bool:
    """The history's page selector, and nothing that commits anything."""
    label = (label or "").strip()
    return bool(re.search(r"jump\s+to|page", label, re.I)) and not (
        FORBIDDEN_CONTROL_RE.search(label))


def is_page_option(label: str, target_page: int) -> bool:
    return (label or "").strip() == str(target_page)


def is_safe_url(url: str) -> bool:
    """True only for an https URL on one of this provider's own hosts.

    The check itself lives in the core, so all of them answer the same way.
    This app keeps the hosts, which is the part that really is its own."""
    from paperpull_core.urls import is_safe_url as _host_allows
    return _host_allows(url, ALLOWED_HOSTS)


SECURITY_CHALLENGE_MARKERS = [
    "enter the code", "verification code", "6-digit", "two-factor",
    "two-step", "authenticator", "confirm your identity", "verify your identity",
    # "unusual" on its own is not a marker. A utility tells you your usage
    # is unusually high on the same page as the bills.
    "we sent a code", "device approval", "approve this login", "unusual activity",
    "are you a robot", "captcha", "let's verify", "check your email",
    "check your phone", "your session has expired", "log back in",
]

RATE_LIMIT_MARKERS = [
    "too many requests", "rate limit", "try again later",
    "temporarily unavailable", "http error 429", "unusual traffic",
]

FALLBACK = {
    "doc_row": ("table tbody tr, [role='row'], [class*='documentRow'], "
                "[class*='DocumentRow'], [class*='row'][class*='document'], "
                "[data-testid*='document'], li[class*='document']"),
    "doc_link": ("a[href*='.pdf'], a[href*='document'], a[href*='statement'], "
                 "a[download], button[class*='download']"),
    "download_control": ("a:has-text('View Bill PDF'), a:has-text('View PDF'), "
                        "button:has-text('View Bill PDF'), a[href$='.pdf'], a[download]"),
    "page_ready": ("table, [role='row'], [class*='document'], [class*='statement'], "
                   "main, [role='main']"),
    "next_page": ("a[aria-label*='Next' i], button[aria-label*='Next' i], "
                  "[class*='next']"),
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
YEAR_RE = re.compile(r"\b(19|20)(\d{2})\b")


def _parse_date_from_page(raw: str) -> str:
    """Parse date text into ISO YYYY-MM-DD or empty string if unparseable."""
    if not raw:
        return ""
    text = _html.unescape(raw).strip()
    for pat, fmt in DATE_PATTERNS:
        m = pat.search(text)
        if m:
            if fmt == "mdY":
                mon_str, day_str, yr_str = m.group(1).lower()[:3], m.group(2), m.group(3)
                mon = _MONTHS.get(mon_str, 0)
                if mon:
                    return f"{int(yr_str):04d}-{mon:02d}-{int(day_str):02d}"
            elif fmt == "mdy_slash":
                mon, day, yr = int(m.group(1)), int(m.group(2)), int(m.group(3))
                return f"{yr:04d}-{mon:02d}-{day:02d}"
            elif fmt == "iso":
                return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return ""


def parse_date(text):
    """The date this provider's page is showing, as YYYY-MM-DD.

    The reading is below, unchanged. This only refuses to believe a result
    that names a day which does not exist, because a reference number is
    shaped like a date and used to be taken for one."""
    return _checked_date(_parse_date_from_page(text), "")


def parse_period_date(raw: str) -> Tuple[str, str]:
    """Parse period string returning (iso_date, confidence)."""
    exact = parse_date(raw)
    if exact:
        return exact, "HIGH"
    m_my = MONTH_YEAR_RE.search(raw)
    if m_my:
        mon_str, yr_str = m_my.group(1).lower()[:3], m_my.group(2)
        mon = _MONTHS.get(mon_str, 0)
        yr = int(yr_str)
        if mon:
            import calendar
            _, last_day = calendar.monthrange(yr, mon)
            return f"{yr:04d}-{mon:02d}-{last_day:02d}", "HIGH"
    m_yr = YEAR_RE.search(raw)
    if m_yr:
        yr = int(m_yr.group(0))
        return f"{yr:04d}-12-31", "MEDIUM"
    return "", "LOW"


def looks_signed_out(page) -> bool:
    """Return True if current page indicates session is logged out."""
    url = page.url.lower()
    return any(marker in url for marker in LOGIN_URL_MARKERS)


def detect_security_challenge(page) -> Optional[str]:
    """Name the 2FA, CAPTCHA or throttling prompt on screen, or None.

    Reads the visible text rather than the page source. The source of a
    Salesforce portal carries every string its scripts might ever show, so
    "verification code" is in there on a perfectly normal day."""
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
    """On the bill history itself, signed in, and not a 404."""
    try:
        url = (page.url or "").lower()
        title = (page.title() or "").lower()
    except Exception:
        return False
    return ("bill-and-payment-history" in url and is_safe_url(url)
            and not looks_signed_out(page)
            and "page not found" not in title and "404" not in title)


def goto_documents(page) -> bool:
    """Land on the bill history.

    The tab the user signed in on is reused. If it already shows the history
    nothing moves. Otherwise the history URL is tried, and if the portal
    answers that with its own 404 page (it has), the tab is left where it was
    so the user can open the history by hand, as login.bat asks them to."""
    if on_documents_page(page):
        return True
    start_url = page.url or ""
    for url in DOCUMENT_URL_CANDIDATES:
        if not is_safe_url(url):
            continue
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=15000)
            for _ in range(10):
                if on_documents_page(page):
                    return True
                page.wait_for_timeout(500)
        except Exception as e:
            log.info("documents URL %s failed: %s", url, e)
    if is_safe_url(start_url) and not looks_signed_out(page) and start_url != page.url:
        try:
            page.goto(start_url, wait_until="domcontentloaded", timeout=15000)
        except Exception:
            pass
    return on_documents_page(page)


def get_pagination_pages(page) -> List[int]:
    """Get list of available page numbers from Jump to combobox."""
    try:
        cb = page.query_selector("lightning-combobox[aria-label='Jump to'], .pagination-block lightning-combobox")
        if cb:
            opts = cb.evaluate("el => (el.options || []).map(o => o.value)")
            if opts:
                return sorted([int(v) for v in opts if str(v).isdigit()])
    except Exception as e:
        log.debug(f"Error getting pagination pages: {e}")
    return [1]


def _rows_signature(page) -> tuple:
    """The dates of the rows on the page, in order, so a page that did not
    change can be told from one that did."""
    try:
        rows = page.query_selector_all(FALLBACK["doc_row"])
        return tuple(parse_date(r.inner_text() or "") for r in rows[:12])
    except Exception:
        return ()


def _current_page(page) -> Optional[int]:
    try:
        cb = page.query_selector("lightning-combobox[aria-label='Jump to'], .pagination-block lightning-combobox")
        if cb:
            v = cb.evaluate("el => el.value")
            return int(v) if str(v).isdigit() else None
    except Exception:
        pass
    return None


def goto_page_number(page, target_page: int) -> bool:
    """Navigate the table to `target_page` through the Jump to combobox,
    and say so only once the table shows it. The picker's value has to
    read the target, and the rows have to have changed from what they
    were, before this returns True. Version one clicked the option,
    slept a second and a half, and answered True while the table still
    showed the page before (#33). Discovery then read page 1 seven times
    and filed every bill under page 7."""
    try:
        cb = page.query_selector("lightning-combobox[aria-label='Jump to'], .pagination-block lightning-combobox")
        if not cb:
            return False
        curr_val = cb.evaluate("el => el.value")
        if curr_val == target_page or str(curr_val) == str(target_page):
            return True
        before = _rows_signature(page)
        # The only two clicks outside a bill row. The picker must call itself
        # a page jump, and the option must be nothing but a page number, so a
        # combobox that turned into something else is left alone.
        if not is_page_picker(all_labels(cb)):
            log.info("pagination control is not a page picker: %r", all_labels(cb))
            return False
        cb.click()
        time.sleep(0.4)
        opt = page.query_selector(f"lightning-base-combobox-item[data-value='{target_page}']")
        if not opt:
            opts = page.query_selector_all("[role='option'], lightning-base-combobox-item")
            for o in opts:
                if (o.inner_text() or "").strip() == str(target_page):
                    opt = o
                    break
        if opt and is_page_option(control_label(opt), target_page):
            opt.click()
            if _wait_for_page_change(page, before, target_page, 8):
                return True
            # A Lightning option can swallow a plain click. Once more
            # through the DOM, then the picker is given up on.
            try:
                opt.evaluate("el => el.click()")
            except Exception:
                pass
            if _wait_for_page_change(page, before, target_page, 8):
                return True
            log.info("page %d did not show after the jump (picker reads %s, rows %s)",
                     target_page, _current_page(page),
                     "unchanged" if _rows_signature(page) == before else "changed")
        else:
            log.info("no option for page %d in the picker, asking it by value", target_page)
            try:
                page.keyboard.press("Escape")
            except Exception:
                pass
        # The picker as its parent hears it. A Lightning combobox tells the
        # page about a choice through a change event carrying the value,
        # and the parent's own handler reads event.detail.value. That is
        # the same message a click on the option sends, without needing
        # the option list to have rendered.
        if _jump_by_value(page, cb, target_page) and _wait_for_page_change(page, before, target_page, 8):
            return True
    except Exception as e:
        log.debug(f"goto_page_number {target_page} failed: {e}")
    return False


def _jump_by_value(page, cb, target_page: int) -> bool:
    """Set the page picker's value and tell its parent, the way the
    component itself does after an option is chosen. Only ever the page
    picker, which has already passed is_page_picker."""
    try:
        cb.evaluate("""(el, v) => {
          el.value = v;
          el.dispatchEvent(new CustomEvent('change', {detail: {value: v}, bubbles: true, composed: true}));
        }""", str(target_page))
        return True
    except Exception as e:
        log.info("picker by value: %s", e)
        return False


def _wait_for_page_change(page, before: tuple, target_page: int, seconds: int) -> bool:
    """True once the table shows different rows. The picker reading the
    target is the ideal, but a picker whose value never updates is not
    proof the page did not move, the rows are."""
    for _ in range(seconds * 2):
        page.wait_for_timeout(500)
        sig = _rows_signature(page)
        if sig and sig != before:
            page.wait_for_timeout(500)
            return True
    return False


def is_next_control(label: str) -> bool:
    """The history's Next page control, and nothing else.

    The allowlist lives in the core now, because eight other apps needed
    one and had been handing this question to their commit blocklist, which
    refuses the word "next" and so refused every Next control they had.
    """
    return _core_is_next(label)


def next_page(page) -> bool:
    """One page forward through the history's Next control, for a picker
    that will not jump. True once the rows changed."""
    before = _rows_signature(page)
    try:
        for cand in page.query_selector_all(FALLBACK["next_page"]):
            # Each label on its own. all_labels joins them for a log line,
            # and a control whose text is "Next" and whose aria-label is
            # "Next page" reads "Next | Next page" joined, which is not
            # what either of them says and matched nothing.
            if not any(is_next_control(part) for part in _control_labels(cand)):
                continue
            try:
                if cand.get_attribute("disabled") is not None or (cand.get_attribute("aria-disabled") or "") == "true":
                    return False
            except Exception:
                pass
            cand.click()
            return _wait_for_page_change(page, before, 0, 8)
    except Exception as e:
        log.debug(f"next_page failed: {e}")
    return False


def collect_download_docs(page) -> List[dict]:
    """Every bill across every page of the history, each with the page and
    row it was seen on. A bill seen twice keeps its first sighting, and a
    page that shows the same rows as the page before it means the jump did
    not take, so the walk stops there and says so rather than reading the
    same page again under a new number."""
    results: List[dict] = []
    seen_dates = set()
    try:
        wait_for_rows(page)
        pages = get_pagination_pages(page)
        last_sig = None
        for p_num in pages:
            if len(pages) > 1 and p_num != pages[0]:
                if not goto_page_number(page, p_num) and not next_page(page):
                    log.info("could not reach page %d of the history, stopping at %d bill(s)",
                             p_num, len(results))
                    break
            sig = _rows_signature(page)
            if sig and sig == last_sig:
                log.info("page %d shows the same rows as the page before, stopping", p_num)
                break
            last_sig = sig
            rows = page.query_selector_all(FALLBACK["doc_row"])
            for idx, row in enumerate(rows):
                text = row.inner_text() or ""
                if "View Bill PDF" in text:
                    date_str = parse_date(text)
                    if date_str and date_str not in seen_dates:
                        seen_dates.add(date_str)
                        results.append({
                            "date_text": date_str,
                            "title": f"Energy Statement - {date_str}",
                            "page_number": p_num,
                            "row_index": idx,
                            "summary": "Energy Statement",
                        })
        if len(pages) > 1:
            goto_page_number(page, pages[0])
    except Exception as e:
        log.debug(f"Error collecting docs: {e}")
    return results


def wait_for_rows(page, seconds: int = 20) -> int:
    """How many bill rows the page shows, once it shows any. The table
    draws a moment after the page, and one discovery ran before it had,
    read nothing, and said so as if the history were empty."""
    for _ in range(seconds * 2):
        try:
            rows = page.query_selector_all(FALLBACK["doc_row"])
            n = sum(1 for r in rows if "View Bill PDF" in (r.inner_text() or ""))
            if n:
                return n
        except Exception:
            pass
        page.wait_for_timeout(500)
    return 0


def _row_for_date(page, want_date: str, idx: int):
    """The bill row dated `want_date` on the page that is open. The row at
    `idx` first, then every row, since rows move as bills post."""
    wait_for_rows(page)
    rows = page.query_selector_all(FALLBACK["doc_row"])
    order = ([rows[idx]] if 0 <= idx < len(rows) else []) + list(rows)
    for row in order:
        try:
            if parse_date(row.inner_text() or "") == want_date:
                return row
        except Exception:
            continue
    return None


def pick_document_control(candidates) -> Optional[object]:
    """The first control in a bill row that reads as a document action and
    nothing else. A bill row also holds Pay, and a plain "first link in the
    row" once pointed at it. Every click on a row goes through here."""
    for el in candidates or []:
        label = control_label(el)
        if is_safe_control(label):
            return el
        if label:
            log.debug("skipping control %r", label)
    return None


_VIEW_PDF_RE = re.compile(r"^\s*view\s+(bill\s+)?pdf\s*$", re.I)

# Every control in the row, gathered by walking each node's own children
# rather than querySelectorAll, which Lightning's synthetic shadow DOM
# patches to hide a component's children from anything outside it (round
# three's outline saw a.pdf-link that way while every query saw nothing).
# Anchors, buttons and anything whose own text reads View Bill PDF,
# innermost first, so the thing a person clicks comes before its cell.
_ROW_TEXT_CONTROLS_JS = r"""row => {
  const rx = /^\s*view\s+(bill\s+)?pdf\s*$/i;
  const out = [];
  const walk = (el) => {
    const kids = el.shadowRoot ? [...el.shadowRoot.children, ...el.children] : [...el.children];
    for (const c of kids) {
      const tag = c.tagName ? c.tagName.toLowerCase() : '';
      const t = (c.innerText || c.textContent || '').trim();
      const role = c.getAttribute ? (c.getAttribute('role') || '') : '';
      if (tag === 'a' || tag === 'button' || role === 'button' || tag === 'lightning-button' || rx.test(t)) out.push(c);
      walk(c);
    }
  };
  walk(row);
  // innermost first: an element none of the others is inside of
  out.sort((a, b) => (a.contains(b) ? 1 : b.contains(a) ? -1 : 0));
  return out;
}"""


def row_controls(row) -> list:
    """Everything in a bill row that could be its PDF control. Anchors and
    buttons first, then every element whose own text reads View Bill PDF,
    innermost first, whatever it is, shadow roots included, since on the
    tester's history the control was none of the usual kinds (#33)."""
    out = []
    try:
        handles = row.evaluate_handle(_ROW_TEXT_CONTROLS_JS)
        props = handles.get_properties()
        for h in props.values():
            el = h.as_element()
            if el is not None:
                out.append(el)
    except Exception as e:
        log.debug("text controls in row: %s", e)
    # The selector queries too, for a history where they do answer.
    for sel in ("a, button, [role='button']", "lightning-button, lightning-formatted-url"):
        try:
            for el in row.query_selector_all(sel):
                out.append(el)
        except Exception:
            continue
    return out


_ROW_OUTLINE_JS = r"""row => {
  const out = [];
  const walk = (el, d, inShadow) => {
    if (d > 6 || out.length > 60) return;
    const tag = el.tagName ? el.tagName.toLowerCase() : '#';
    const cls = (el.className || '').toString().split(' ').filter(Boolean).slice(0, 2).join('.');
    const role = el.getAttribute ? (el.getAttribute('role') || '') : '';
    const own = Array.from(el.childNodes || []).filter(n => n.nodeType === 3).map(n => n.textContent.trim()).filter(Boolean).join(' ');
    const href = (tag === 'a' && el.getAttribute) ? (el.getAttribute('href') || '') : '';
    out.push('  '.repeat(d) + (inShadow ? '~' : '') + tag + (cls ? '.' + cls : '') + (role ? ' [' + role + ']' : '') + (own ? ' = ' + own.replace(/\d{4,}/g, '####').slice(0, 40) : '') + (href ? ' href=' + href.replace(/\d{4,}/g, '####').slice(0, 60) : '') + (el.shadowRoot ? ' {shadow}' : ''));
    if (el.shadowRoot) for (const c of el.shadowRoot.children) walk(c, d + 1, true);
    for (const c of (el.children || [])) walk(c, d + 1, inShadow);
  };
  walk(row, 0, false);
  return out;
}"""


def _describe_row(row) -> str:
    """What a row holds, digits masked, for the log line that says no
    control was found in it."""
    try:
        text = re.sub(r"\s+", " ", row.inner_text() or "")[:120]
    except Exception:
        text = "?"
    labels = []
    try:
        for el in row.query_selector_all("a, button, [role='button'], lightning-button, span, div"):
            label = control_label(el)
            if label and len(label) < 40 and label not in labels:
                labels.append(label)
            if len(labels) >= 8:
                break
    except Exception:
        pass
    mask = lambda t: re.sub(r"\d{4,}", "####", t)
    try:
        outline = row.evaluate(_ROW_OUTLINE_JS) or []
    except Exception:
        outline = []
    return "row %r controls %s\n  [site] row outline:\n    %s" % (
        mask(text), [mask(x) for x in labels], "\n    ".join(outline))


def _url_shape(url: str) -> str:
    """Enough of an address to say what kind of page it is, and no more.
    This goes in the output a tester copies into an issue."""
    try:
        parts = urlsplit(url or "")
    except ValueError:
        return "a page"
    if (url or "").startswith("blob:"):
        return "a blob"
    tail = (parts.path or "/").rsplit("/", 1)[-1]
    kind = "a PDF" if tail.lower().endswith(".pdf") else "a page"
    return "%s on %s" % (kind, parts.netloc or "this site")


def _pdf_from_here(page) -> Optional[bytes]:
    """The PDF the tab is standing on, or the one inside it.

    PG&E can answer View Bill PDF by moving the tab to its own viewer,
    which is an iframe around the file. Rendering that gives one blank
    sheet, because a viewer is a program and not a document. The file
    itself is fetched through the signed-in session instead, first at the
    address the tab is on and then at whatever its frames hold."""
    seen = []
    url = page.url or ""
    if url and not url.startswith("blob:") and is_safe_url(url):
        seen.append(url)
    try:
        for frame in page.frames:
            f_url = frame.url or ""
            if f_url and f_url not in seen and not f_url.startswith("about:") and is_safe_url(f_url):
                seen.append(f_url)
    except Exception as e:
        log.info("frames: %s", e)
    try:
        for src in page.eval_on_selector_all(
                "iframe, embed, object",
                "els => els.map(e => e.src || e.data || '').filter(Boolean)") or []:
            if src not in seen and is_safe_url(src):
                seen.append(src)
    except Exception as e:
        log.info("embedded sources: %s", e)
    for candidate in seen[:6]:
        try:
            res = page.request.get(candidate, timeout=60000)
            body = res.body() if res.ok else b""
        except Exception as e:
            log.info("fetch %s: %s", _url_shape(candidate), e)
            continue
        if body[:5] == b"%PDF-":
            return body
    return None


def download_bill(page, doc: dict, out_path: Path, config: dict) -> bool:
    """Download a bill PDF for specified doc dictionary handling downloads, popups, fetches, and network responses."""
    try:
        idx = doc.get("row_index", -1)
        target_page = int(doc.get("page_number", 1))
        link = None
        want_date = doc.get("date_text") or doc.get("date") or ""

        # The row is found on the page discovery saw it on, by its date,
        # and when it is not there (the page number was wrong, a bill
        # posted since and everything moved down a page) every page of the
        # history is walked until the date turns up.
        row = None
        pages = get_pagination_pages(page)
        order = [target_page] + [p for p in pages if p != target_page]
        for p_num in order:
            if p_num != (_current_page(page) or pages[0]):
                if not goto_page_number(page, p_num):
                    continue
            row = _row_for_date(page, want_date, idx if p_num == target_page else -1)
            if row is not None:
                if p_num != target_page:
                    log.info("bill %s is on page %d now, not %d", want_date, p_num, target_page)
                target_page = p_num
                break
        if row is not None:
            link = pick_document_control(row_controls(row))
            if not link:
                print("  [site] the row for %s hands over no PDF control: %s" % (want_date, _describe_row(row)))

        # Fallback if the rows moved. Every View Bill PDF control on the page,
        # kept only if the row it sits in carries this bill's date.
        if not link:
            for cand in page.query_selector_all(FALLBACK["download_control"]):
                try:
                    around = cand.evaluate(
                        "el => (el.closest('tr, [role=row], li') || el.parentElement || el).innerText || ''")
                except Exception:
                    around = ""
                if want_date and parse_date(around) != want_date:
                    continue
                link = pick_document_control([cand])
                if link:
                    break

        if not link:
            print(f"  [site] No download link found for doc index {idx} on page {target_page}")
            return False

        print(f"  [site] Found '{control_label(link)}' for index {idx} (page {target_page}). Preparing capture...")

        # Direct href check if present
        try:
            href = link.get_attribute("href") or ""
            if href and ("http" in href or ".pdf" in href):
                target_url = href if href.startswith("http") else (BASE.rstrip("/") + "/" + href.lstrip("/"))
                if is_safe_url(target_url):
                    res = page.request.get(target_url)
                    if res.ok and res.body()[:5] == b"%PDF-":
                        out_path.write_bytes(res.body())
                        print("  [site] Successfully fetched PDF via direct href!")
                        return True
        except Exception as e_href:
            print(f"  [site] Direct href fetch note: {e_href}")

        existing_pages = set(page.context.pages)
        history_url = page.url or ""
        captured_download = [None]
        captured_response_bytes = [None]

        def handle_download(dl):
            captured_download[0] = dl

        def handle_response(res):
            try:
                ct = (res.headers.get("content-type") or "").lower()
                if "application/pdf" in ct or ".pdf" in res.url.lower():
                    b = res.body()
                    if b and b[:5] == b"%PDF-":
                        captured_response_bytes[0] = b
            except Exception:
                pass

        page.on("download", handle_download)
        # On the context, not on this page. A PDF that loads in the tab
        # PG&E opens never reaches a listener on the tab it was opened
        # from, so the answer that carried the bill went unheard.
        page.context.on("response", handle_response)

        popup = None
        blob_url = None
        try:
            try:
                link.scroll_into_view_if_needed(timeout=3000)
            except Exception:
                pass
            print("  [site] Clicking 'View Bill PDF' link...")
            try:
                with page.expect_popup(timeout=6000) as popup_info:
                    link.click(force=True, timeout=4000)
                popup = popup_info.value
            except Exception:
                # Fallback if popup didn't trigger via click
                try:
                    with page.expect_popup(timeout=6000) as popup_info:
                        link.evaluate("el => el.click()")
                    popup = popup_info.value
                except Exception:
                    pass

            blob_url = None
            if popup:
                try:
                    popup.wait_for_url(lambda u: u.startswith("blob:") or ("http" in u and ".pdf" in u), timeout=15000)
                    blob_url = popup.url
                except Exception as e_wait:
                    print(f"  [site] Popup wait note: {e_wait}")
                    if popup.url and popup.url != "about:blank":
                        blob_url = popup.url

            # Wait briefly if direct download or response happened instead
            if not blob_url:
                t_start = time.time()
                while time.time() - t_start < 5.0:
                    if captured_download[0] or captured_response_bytes[0]:
                        break
                    time.sleep(0.3)
        except Exception as e_click:
            print(f"  [site] Link click warning: {e_click}")
        finally:
            page.remove_listener("download", handle_download)
            try:
                page.context.remove_listener("response", handle_response)
            except Exception:
                pass

        # The control need not open a tab at all. It can move THIS one to
        # PG&E's viewer, and then there is no popup, no download and no
        # response this tab was listening for, and the run ends standing on
        # a page where nothing it knows about exists.
        #
        # That is what a tester's failure file showed, a page with one
        # iframe, six inputs, two dialogs and not one of the app's own
        # selectors matching anything at all (#33). So a tab that moved is
        # read where it stands, by asking for the PDF through the session
        # rather than by rendering a viewer, which renders nothing.
        if not (captured_response_bytes[0] or captured_download[0] or blob_url):
            moved = (page.url or "") != history_url
            if moved:
                print("  [site] the tab moved to %s rather than opening one" % _url_shape(page.url))
                body = _pdf_from_here(page)
                if body:
                    captured_response_bytes[0] = body
                    print("  [site] the bill came from the page the tab moved to")
            # and put the tab back on the history either way, or every bill
            # after this one is looked for on a page that does not hold it
            if moved:
                try:
                    page.goto(history_url, wait_until="domcontentloaded", timeout=45000)
                    wait_for_rows(page, seconds=20)
                except Exception as e_back:
                    log.info("could not return to the history: %s", e_back)

        if captured_response_bytes[0]:
            print("  [site] Captured PDF from network response!")
            out_path.write_bytes(captured_response_bytes[0])
        elif captured_download[0]:
            print("  [site] Download event captured!")
            captured_download[0].save_as(str(out_path))
        elif blob_url and is_safe_url(blob_url):
            print(f"  [site] Statement blob ready: {blob_url}. Capturing download...")
            try:
                with page.expect_download(timeout=10000) as dl_info:
                    page.evaluate("""(url) => {
                        const a = document.createElement('a');
                        a.href = url;
                        a.download = 'statement.pdf';
                        document.body.appendChild(a);
                        a.click();
                        document.body.removeChild(a);
                    }""", blob_url)
                dl = dl_info.value
                dl.save_as(str(out_path))
                print("  [site] Statement PDF downloaded and saved!")
            except Exception as e_dl:
                print(f"  [site] Error saving blob download: {e_dl}")

        # Clean up any popup tabs opened by PG&E
        for p in list(page.context.pages):
            if p not in existing_pages and not p.is_closed():
                try:
                    p.close()
                except Exception:
                    pass

        if out_path.exists() and (out_path.stat().st_size == 0 or out_path.read_bytes()[:5] != b"%PDF-"):
            out_path.unlink()
            return False
        return out_path.exists()
    except Exception as e:
        print(f"  [site] Download bill exception: {e}")
        if out_path.exists() and out_path.stat().st_size == 0:
            out_path.unlink()
        return False
