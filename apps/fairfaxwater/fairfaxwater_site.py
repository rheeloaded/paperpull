"""ALL Fairfax Water selectors, URLs, and page behavior live here.

When the customer portal changes, repair this file only.

STATUS, mapped 2026-09-19 against a signed-in session.

  FW Customer (www.fwcustomer.org) is a Mendix app. Its client talks to
  one endpoint, /xas/, in a stateful protocol of GUIDs and change sets
  that is not worth reading, so this app drives the pages the way a person
  does and clicks exactly two kinds of control, both named.

  THE PAGES. The left nav has "Billing & Payment" (a page, not a payment).
  It shows a Billing History grid, one row per bill, newest first, five at
  a time with a "Show More" button, columns Account Number, Invoice Date,
  Invoice Amount, Due Date, Status. The account mapped listed 25 bills back
  to 2022, quarterly. Only the bills of the last year carry a "View"
  button, and only those have a PDF, which is what Fairfax Water's own FAQ
  says ("view bills from the last year"). Older rows are amounts only and
  are not documents here. So the archive grows one bill a quarter, and a
  run every few months is what keeps it whole. "View" opens the bill PDF
  in a new tab at docsight.net, a third-party document host, under a
  signed one-time URL. This app never navigates there itself. It catches
  the tab the site opens, reads the PDF out of that tab's own response,
  and closes it.

  IDENTITY is the invoice date plus the last four digits of the account
  number. The row has no id of its own and the PDF URL is one-time, so
  nothing is stored but the date.

  The dashboard's "View My Bill" and "Account Statement" are the current
  bill and a running statement, not history, and are not used.

SAFETY (this is a utility account that takes payments):
  Strictly READ-ONLY. The portal can pay a bill, set up autopay, store a
  card or bank account, start or stop service, and change the mailing
  address and paperless settings. This app must NEVER activate a control
  that does any of those, never submits a form, never confirms a dialog,
  and never accepts terms on the user's behalf. An expired session raises
  SessionExpired so a run stops loudly rather than reporting an empty
  success.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlsplit

from paperpull_core.controls import SETTINGS_CONTROL_RE, AUTH_CONTROL_RE

log = logging.getLogger("fairfaxwater_docs.site")

# Every host this app will read from. Anything else is refused. docsight.net
# is where the portal's own View button opens each bill PDF. This app never
# navigates there, it only accepts the tab the portal opens.
ALLOWED_HOSTS = ("fwcustomer.org", "fairfaxwater.org", "docsight.net")

BASE = "https://www.fwcustomer.org"
URLS = {
    "home": f"{BASE}/",
    "login": f"{BASE}/",
    "documents": f"{BASE}/",
}

LOGIN_URL_MARKERS = ["/login", "/logon", "/signin", "/sign-in", "/mfa",
                     "/verify", "/onboarding", "login.html"]


class SessionExpired(RuntimeError):
    """Fairfax Water answered with a sign-in page instead of the thing asked for."""


def is_safe_url(url: str) -> bool:
    """https, on fwcustomer.org or a subdomain of it, no credentials in the URL."""
    try:
        parts = urlsplit(url or "")
    except ValueError:
        return False
    host = (parts.hostname or "").lower().rstrip(".")
    if parts.scheme != "https" or not host or parts.username or parts.password:
        return False
    if parts.port not in (None, 443):
        return False
    return any(host == h or host.endswith("." + h) for h in ALLOWED_HOSTS)


# ---------------------------------------------------------------------------
# HARD SAFETY GUARD. Tuned for a utility account. Never pay, never store a
# card or bank account, never start or stop service, never change a setting.
# ---------------------------------------------------------------------------
FORBIDDEN_CONTROL_RE = re.compile(
    r"(\bpay\b|payment|autopay|auto-?pay|\bcard\b|bank\s+account|checking|savings|"
    r"routing|wallet|\benroll|paperless|\bstart\b|\bstop\b|\bmove\b|transfer\s+service|"
    r"connect|disconnect|turn\s+(on|off)|service\s+request|\brequest\b|"
    r"leak|dispute|extension|arrangement|budget\s+billing|"
    # Word boundaries on both sides of the verb stems. "edit" inside
    # "Credit" and "chang" inside "Exchange" are the two that bit before.
    r"\bchang(e|es|ed|ing)\b|\bedit(s|ed|ing)?\b|\bupdat(e|es|ed|ing)\b|"
    r"\bset\s+up\b|enable|disable|\bdelet|\bremov(e|es|ed|ing|al)\b|"
    r"\bsubmit|\bconfirm\b|\bagree\b|\baccept\b|authoriz|\bapply\b|"
    r"\bbegin\b|initiate|\badd\b|register|"
    r"log\s*out|logout|sign\s*out|password|username|"
    r"security\s+question|contact\s+info|\baddress\b|\bemail\b|\bphone\b|"
    r"notification|alert|preference)",
    re.I)

# What a document control may look like. A control must match this AND not
# match the blocklist.
SAFE_DOC_CONTROL_RE = re.compile(
    r"(download|\bview\b|\bopen\b|\bprint\b|\bpdf\b|\bbill\b|bills|billing\s+history|"
    r"bill\s+history|statement|document|invoice|history|usage|show\s+more)", re.I)


# The left nav's page links. "Billing & Payment" opens a page and pays for
# nothing, but the control guard refuses "Payment" on sight, as it should
# for a button. So page links get their own, exact, list.
SAFE_NAV_RE = re.compile(r"^(dashboard|billing\s*&\s*payments?|account\s+statement|usage)$", re.I)


def is_safe_nav(name: str) -> bool:
    return bool(SAFE_NAV_RE.match((name or "").strip()))


def is_safe_control(name: str) -> bool:
    name = (name or "").strip()
    if not name:
        return False
    if (FORBIDDEN_CONTROL_RE.search(name) or SETTINGS_CONTROL_RE.search(name)
            or AUTH_CONTROL_RE.search(name)):
        return False
    return bool(SAFE_DOC_CONTROL_RE.search(name))


# Links diagnose may follow while surveying. Narrower than the guard on
# purpose, since these are followed without a person choosing each one.
SURVEY_LINK_RE = re.compile(
    r"^(bills?|my\s+bills?|bill(ing)?\s+history|view\s+bills?|statements?|documents?|"
    r"history|usage|usage\s+history|account\s+history)$", re.I)


SECURITY_CHALLENGE_MARKERS = [
    "one-time passcode", "one time passcode", "enter the code", "verification code",
    "we sent a code", "text message", "authenticator", "confirm your identity",
    "verify your identity", "are you a robot", "captcha", "access denied",
    "your session has expired", "session timed out", "signed out",
]

RATE_LIMIT_MARKERS = ["too many requests", "rate limit", "try again later",
                      "temporarily unavailable", "unusual traffic"]


def looks_signed_out(page) -> bool:
    try:
        url = (page.url or "").lower()
    except Exception:
        return False
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
    """The Billing & Payments page, told by its Billing History grid."""
    try:
        if not is_safe_url(page.url or "") or looks_signed_out(page):
            return False
        return page.get_by_text(re.compile(r"^\s*Billing History\s*$")).count() > 0 \
            and page.get_by_text(re.compile(r"^\s*Invoice Date\s*$")).count() > 0
    except Exception:
        return False


def _click_nav(page, label: str) -> bool:
    """Open one of the left nav's pages. Named, exact, and checked."""
    if not is_safe_nav(label):
        log.error("refusing nav %r", label)
        return False
    link = page.locator("a.mx-link").filter(has_text=re.compile("^\\s*" + re.escape(label) + "\\s*$")).first
    if link.count() == 0:
        return False
    link.click(timeout=15000)
    page.wait_for_timeout(2500)
    return True


def goto_documents(page) -> bool:
    if on_documents_page(page):
        return True
    if not is_safe_url(page.url or ""):
        try:
            page.goto(URLS["home"], wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)
        except Exception as e:
            log.info("home failed: %s", e)
    for _ in range(2):
        if _click_nav(page, "Billing & Payment") and on_documents_page(page):
            return True
        page.wait_for_timeout(2000)
    return on_documents_page(page)


def ensure_statements(page) -> bool:
    return goto_documents(page)


# -- bills ------------------------------------------------------------------------------

ROW_RE = re.compile(
    r"(?P<acct>\d{4,})\s+(?P<invoice>\d{2}/\d{2}/\d{4})\s+\$?\s*(?P<amount>-?[\d,]+\.\d{2})\s+"
    r"(?P<due>\d{2}/\d{2}/\d{4})\s+(?P<status>[A-Za-z ]+?)\s+View\s*$")
ROW_ANCESTOR = ("xpath=ancestor::*[self::tr or contains(@class,'mx-listview-item') or "
                "contains(@class,'mx-templategrid-item') or contains(@class,'row')][1]")
SHOW_MORE_ROUNDS = 40           # 5 rows a click, so 200 bills, fifty years of quarters


def parse_date(text: str) -> str:
    """'02/09/2026' or '2026-02-09' -> '2026-02-09', else ''."""
    s = (text or "").strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}", s):
        return s[:10]
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", s)
    if m:
        return "%s-%02d-%02d" % (m.group(3), int(m.group(1)), int(m.group(2)))
    return ""


def parse_row(text: str) -> Optional[dict]:
    """One Billing History row's text -> {account, date, amount, due, status}."""
    m = ROW_RE.search(re.sub(r"\s+", " ", text or "").strip())
    if not m:
        return None
    return {"account": m.group("acct")[-4:], "date": parse_date(m.group("invoice")),
            "amount": m.group("amount"), "due": parse_date(m.group("due")),
            "status": m.group("status").strip()}


def _view_buttons(page):
    return page.get_by_role("button", name=re.compile(r"^\s*View\s*$"))


def _guarded_click(control, timeout: int = 10000) -> bool:
    """Click a control only after its own text has cleared the guard. The
    text comes from the element, not from the code that chose it, so a
    selector that landed on the wrong button cannot pay a bill."""
    try:
        text = (control.inner_text(timeout=2000) or "").strip()
    except Exception:
        text = ""
    if not is_safe_control(text):
        log.error("refusing to click %r", text[:40])
        return False
    control.click(timeout=timeout)
    return True


def expand_history(page, until_year: Optional[int] = None) -> int:
    """Click Show More until the grid stops growing, or until the oldest
    row shown is older than the year a scoped run wants. Returns the row
    count. "Show More" is the grid's own paging control, named."""
    count = _view_buttons(page).count()
    for _ in range(SHOW_MORE_ROUNDS):
        if until_year is not None:
            rows = [parse_row(x) for x in _row_texts(page)]
            years = [int(r["date"][:4]) for r in rows if r and r["date"]]
            if years and min(years) < until_year:
                break
        more = page.get_by_role("button", name=re.compile(r"^\s*Show More\s*$")).first
        if more.count() == 0 or not more.is_visible():
            break
        if not _guarded_click(more, timeout=10000):
            break
        page.wait_for_timeout(2500)
        new = _view_buttons(page).count()
        if new <= count:
            break
        count = new
    return count


def _row_texts(page) -> List[str]:
    out = []
    views = _view_buttons(page)
    for i in range(views.count()):
        try:
            out.append(views.nth(i).locator(ROW_ANCESTOR).first.inner_text(timeout=1500))
        except Exception:
            out.append("")
    return out


def collect_documents(page, keep=None, config: Optional[dict] = None) -> List[dict]:
    """Every bill in the Billing History grid, newest first."""
    if not goto_documents(page):
        raise RuntimeError("could not reach the Billing & Payments page")
    until = None
    if keep is not None:
        wanted = [y for y in range(2000, 2100) if keep(str(y))]
        until = min(wanted) if wanted else None
    expand_history(page, until_year=until)
    rows: List[dict] = []
    for text in _row_texts(page):
        r = parse_row(text)
        if not r or not r["date"]:
            continue
        if keep is not None and not keep(r["date"][:4]):
            continue
        rows.append({"title": "Bill", "date": r["date"], "account": "Account " + r["account"],
                     "category": "Statement", "item_id": r["date"], "client_id": r["amount"],
                     "href": URLS["documents"], "period_start": ""})
    return rows


def _row_for(page, date: str, account_tail: str):
    """The View button of the row with this invoice date, or None."""
    views = _view_buttons(page)
    for i in range(views.count()):
        try:
            r = parse_row(views.nth(i).locator(ROW_ANCESTOR).first.inner_text(timeout=1500))
        except Exception:
            continue
        if r and r["date"] == date and (not account_tail or r["account"] == account_tail):
            return views.nth(i)
    return None


def download_document(page, title: str, date: str, out_path: Path, occurrence: int = 0,
                      item_hint: str = "", client_hint: str = "", account: str = "") -> bool:
    """Click the row's View, catch the tab the portal opens, read the PDF out
    of that tab's own response, write it, close the tab."""
    if not goto_documents(page):
        return False
    tail = (account or "")[-4:] if account else ""
    view = _row_for(page, date, tail)
    if view is None:
        expand_history(page, until_year=int(date[:4]) - 1)
        view = _row_for(page, date, tail)
    if view is None:
        log.warning("no row for %s %s", title, date)
        return False
    ctx = page.context
    got: dict = {}

    # Listen at the context, not on the new tab. A tab's first response can
    # land before a listener attached on the "page" event is in place, and
    # two of five bills were lost that way on the first pilot. The context
    # sees every page's responses from the start.
    def on_response(res):
        try:
            if got:
                return
            ct = (res.headers or {}).get("content-type", "")
            if "pdf" not in ct and res.request.resource_type != "document":
                return
            if not (is_safe_url(res.url) or res.url.startswith("chrome-extension://")):
                return
            body = res.body()
            if body[:4] == b"%PDF":
                got["body"] = body
                got["url"] = res.url
        except Exception as e:
            log.info("response not readable: %s", str(e)[:80])
    ctx.on("response", on_response)
    before = set(id(p) for p in ctx.pages)
    try:
        if not _guarded_click(view, timeout=15000):
            return False
        for _ in range(40):
            if got:
                break
            page.wait_for_timeout(500)
        if not got:
            # The tab is open on the PDF but its response went by unread.
            # Ask the same signed URL once more, on the session, host checked.
            for p in list(ctx.pages):
                if id(p) not in before and is_safe_url(p.url or "") and "docsight" in (p.url or ""):
                    try:
                        r = ctx.request.get(p.url, timeout=60000)
                        if r.ok and r.body()[:4] == b"%PDF":
                            got["body"] = r.body()
                            got["url"] = p.url
                    except Exception as e:
                        log.info("re-fetch of the PDF tab failed: %s", str(e)[:80])
                    break
    finally:
        try:
            ctx.remove_listener("response", on_response)
        except Exception:
            pass
        for p in list(ctx.pages):
            if id(p) not in before and not p.is_closed():
                # The tab the portal opened for the PDF. Only the site's own
                # document host is expected here; anything else is closed
                # unread, and refused.
                if not is_safe_url(p.url or "") and not (p.url or "").startswith("chrome-extension://"):
                    log.warning("the View tab went to an unexpected host, closed unread")
                    got.clear()
                try:
                    p.close()
                except Exception:
                    pass
    if not got:
        # docsight answers "Document Not Found" for a bill it no longer holds,
        # which happened for the oldest of the five on the account mapped.
        log.warning("no PDF came back for %s %s, the portal's document host may no "
                    "longer hold it", title, date)
        return False
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(got["body"])
    return True


_ID_RE = re.compile(r"\d{6,}")


def redact(text: str) -> str:
    """Runs of six or more digits become #, so an account number in a URL,
    a heading or a link never reaches the survey file."""
    return _ID_RE.sub(lambda m: "#" * len(m.group(0)), text or "")


def _shape(obj, depth=0):
    """The shape of a JSON body, never its values."""
    if depth > 3:
        return "..."
    if isinstance(obj, dict):
        return {k: _shape(v, depth + 1) for k, v in list(obj.items())[:25]}
    if isinstance(obj, list):
        return ["list of %d" % len(obj), _shape(obj[0], depth + 1) if obj else None]
    return type(obj).__name__


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
            for i in range(min(loc.count(), 80)):
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
                                 "survey": bool(SURVEY_LINK_RE.match(text.strip()))})
        except Exception:
            pass
    out["controls"] = controls
    return out


def survey(page, dwell_ms: int = 4000, max_follow: int = 6) -> dict:
    """What the signed-in customer portal looks like, without downloading anything.

    Records the page, its headings and controls with the guard's verdict on
    each, and every JSON response fwcustomer.org sends while the page settles. Then
    follows, one at a time and back again, the few links whose text is
    exactly a document word, recording the same for each. Bodies
    are recorded as shape only, never values, and any run of six digits is
    masked. No screenshot, an account page shows balances."""
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
            if "json" in ct:
                try:
                    body = res.json()
                    entry["shape"] = _shape(body)
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
            if followed >= max_follow or c["role"] != "link" or not c["survey"]:
                continue
            if not is_safe_control(c["text"]):
                continue
            try:
                link = page.get_by_role("link", name=re.compile(
                    "^" + re.escape(c["text"].replace("#", "")) + "$", re.I)).first
                if link.count() == 0:
                    continue
                before = page.url
                link.click(timeout=5000)
                page.wait_for_timeout(dwell_ms)
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
