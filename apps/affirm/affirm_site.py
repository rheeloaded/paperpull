"""ALL Affirm selectors, URLs, and page behavior live here.

When affirm.com changes, repair this file only.

STATUS, mapped 2026-09-19 against a signed-in session.

  What Affirm has, for a pay-over-time account. There is no monthly
  statement. The "Affirm Loans statement" in Affirm's help center belongs
  to the Affirm Money account and the Affirm Card, which live under the
  Money tab and which the account mapped does not have, so that part is
  not covered here and is noted as such. What every loan does have is its
  loan agreement, the Truth in Lending disclosure with the payment
  schedule, under "Loan terms" in the loan's Details tab. That is the
  document this app keeps, one per loan, dated the day the loan was made.
  The Details tab also offers a "Loan verification document", which is a
  letter written on request with today's date, from a signed S3 link, and
  is a request rather than a record, so it is left alone.

  THE API, all GET, same origin, cookie session, from inside the page:
    * loans    /api/v4/loans/?limit=50&show_confirmed_first_data_loans=true
               -> {count, next, data[] of {id, merchant_name, description,
                  status, loan_type, ...}}, every loan, settled ones too
    * loan     /api/v3/loans/<id> -> {created, status, loan_type, ...}
    * details  /api/purchase-management/loans/<id>
               -> modules.tabs.data.tabs.details.data.modules.disclosures
                  .data.items[], the one named "Loan terms" carries
                  action.data.url = /api/v2/disclosures/<id>/view
    * terms    that URL answers the agreement as an HTML page (it redirects
               to /api/legal/v1/disclosures/<id>/view), which is rendered to
               PDF in a temporary tab of the same browser.
  Nothing on the page is clicked.

  IDENTITY is loan id, and the agreement's date is the loan's created date.
  The merchant's name goes in the filename, the loan id does not.

SAFETY (this is a lender's account):
  Strictly READ-ONLY. The site can make a payment, set up autopay, store a
  card or bank account, take a new loan, and change contact details. This
  app must NEVER activate a control that does any of those, never submits
  a form, never confirms a dialog, and never accepts terms on the user's
  behalf. An expired session raises SessionExpired so a run stops loudly
  rather than reporting an empty success.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import List, Optional

from paperpull_core.controls import SETTINGS_CONTROL_RE, AUTH_CONTROL_RE

# Everything on its way into a diagnostic file goes through here. It
# lives in core because seventeen apps each had their own copy and
# they drifted into three different versions.
from paperpull_core.redact import redact, set_private_words  # noqa: F401
from paperpull_core.urls import is_safe_url as _host_allows

log = logging.getLogger("affirm_docs.site")

# Every host this app will read from. Anything else is refused.
ALLOWED_HOSTS = ("affirm.com",)

BASE = "https://www.affirm.com"
URLS = {
    "home": f"{BASE}/u/",
    "login": f"{BASE}/u/login",
    "documents": f"{BASE}/u/",
}

LOGIN_URL_MARKERS = ["/login", "/logon", "/signin", "/sign-in", "/mfa",
                     "/verify", "/onboarding"]


class SessionExpired(RuntimeError):
    """Affirm answered with a sign-in page instead of the thing asked for."""


def is_safe_url(url: str) -> bool:
    """True only for an https URL on one of this provider's own hosts.

    The check itself lives in the core, so all of them answer the same way.
    This app keeps the hosts, which is the part that really is its own."""
    return _host_allows(url, ALLOWED_HOSTS)


# ---------------------------------------------------------------------------
# HARD SAFETY GUARD. Tuned for a lender. Never pay, never store a card or
# bank account, never take a loan, never change a setting.
# ---------------------------------------------------------------------------
FORBIDDEN_CONTROL_RE = re.compile(
    r"(\bpay\b|payment|autopay|auto-?pay|\bcard\b|bank\s+account|debit|checking|savings|"
    r"routing|wallet|\bapply\b|\bborrow|new\s+loan|prequalif|pre-?approv|\bshop\b|\bbuy\b|"
    r"checkout|virtual\s+card|\brefinanc|\bextend|defer|hardship|dispute|\bclose\b|"
    # Word boundaries on both sides of the verb stems. "edit" inside
    # "Credit" and "chang" inside "Exchange" are the two that bit before.
    r"\bchang(e|es|ed|ing)\b|\bedit(s|ed|ing)?\b|\bupdat(e|es|ed|ing)\b|"
    r"\bset\s+up\b|enable|disable|\bdelet|\bremov(e|es|ed|ing|al)\b|"
    r"\bsubmit|\bconfirm\b|\bagree\b|\baccept\b|authoriz|\badd\b|"
    r"\bstart\b|\bbegin\b|initiate|register|"
    r"log\s*out|logout|sign\s*out|password|username|\bpin\b|"
    r"contact\s+info|\baddress\b|\bemail\b|\bphone\b|notification|preference)",
    re.I)

# What a document control may look like. A control must match this AND not
# match the blocklist.
SAFE_DOC_CONTROL_RE = re.compile(
    r"(download|\bview\b|\bopen\b|\bprint\b|\bpdf\b|statement|document|"
    r"agreement|disclosure|truth\s+in\s+lending|1099|tax\s+form|"
    r"letter|notice|history|activity|monthly)", re.I)


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
    r"^(money|activity|statements?|documents?|loans?|purchases?|history|"
    r"loan\s+details|agreements?|tax\s+(forms?|documents?))$", re.I)


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
    """Any signed-in affirm.com page, until the survey says which one holds the statements."""
    try:
        url = page.url or ""
        return is_safe_url(url) and "/u/" in url and not looks_signed_out(page)
    except Exception:
        return False


def goto_documents(page) -> bool:
    if on_documents_page(page):
        return True
    if URLS["documents"] and is_safe_url(URLS["documents"]):
        try:
            page.goto(URLS["documents"], wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            log.info("documents URL failed: %s", e)
    return on_documents_page(page)


def ensure_statements(page) -> bool:
    return goto_documents(page)


# -- loan agreements ------------------------------------------------------------------

API = {
    "loans": "/api/v4/loans/?limit=50&show_confirmed_first_data_loans=true",
    "loan": "/api/v3/loans/{id}",
    "details": "/api/purchase-management/loans/{id}",
}

_GET_JS = """async (path) => {
  if (location.protocol !== 'https:' || !(location.hostname === 'affirm.com' || location.hostname.endsWith('.affirm.com'))) {
    throw new Error('Refusing to call the API from an off-host page');
  }
  const r = await fetch(path, {credentials: 'include', headers: {'Accept': 'application/json'}, redirect: 'follow'});
  let j = null;
  try { j = await r.json(); } catch (e) {}
  return {status: r.status, json: j, url: r.url};
}"""
_TEXT_JS = """async (url) => {
  const u = new URL(url, location.href);
  if (u.protocol !== 'https:' || !(u.hostname === 'affirm.com' || u.hostname.endsWith('.affirm.com'))) {
    throw new Error('Refusing an off-host request');
  }
  const r = await fetch(u.href, {credentials: 'include', redirect: 'follow'});
  return {status: r.status, ct: r.headers.get('content-type') || '', text: r.status === 200 ? await r.text() : '', url: r.url};
}"""


def parse_date(text: str) -> str:
    """'2025-11-29T23:17:45Z', '02/09/2026' or 'Feb 9, 2026' -> ISO date, else ''."""
    s = (text or "").strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}", s):
        return s[:10]
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", s)
    if m:
        return "%s-%02d-%02d" % (m.group(3), int(m.group(1)), int(m.group(2)))
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    m = re.match(r"^([A-Z][a-z]{2})[a-z]*\.? (\d{1,2}), (\d{4})$", s)
    if m and m.group(1) in months:
        return "%s-%02d-%02d" % (m.group(3), months.index(m.group(1)) + 1, int(m.group(2)))
    return ""


def _get(page, path: str) -> dict:
    res = page.evaluate(_GET_JS, path)
    status = res.get("status")
    if status in (401, 403):
        raise SessionExpired("Affirm answered %s" % status)
    if status != 200:
        raise RuntimeError("Affirm answered %s for %s" % (status, path.split("?")[0]))
    return res.get("json") or {}


def list_loans(page) -> List[dict]:
    """Every loan on the account, settled ones included."""
    out: List[dict] = []
    path = API["loans"]
    for _ in range(20):
        j = _get(page, path)
        out.extend(j.get("data") or [])
        nxt = j.get("next")
        if not nxt:
            break
        path = nxt if str(nxt).startswith("/") else API["loans"] + "&cursor=" + str(nxt)
    return out


def terms_url(page, loan_id: str) -> str:
    """The loan agreement's URL from the loan's Details tab, or ''."""
    j = _get(page, API["details"].format(id=loan_id))
    try:
        items = (j["modules"]["tabs"]["data"]["tabs"]["details"]["data"]["modules"]
                 ["disclosures"]["data"]["items"])
    except (KeyError, TypeError):
        return ""
    for it in items or []:
        label = ((it.get("label") or {}).get("value") or "").strip().lower()
        action = it.get("action") or {}
        if action.get("name") == "OPEN_URL" and re.search(r"loan\s+terms|agreement|disclosure", label):
            url = (action.get("data") or {}).get("url") or ""
            if url.startswith("/"):
                url = BASE + url
            return url if is_safe_url(url) else ""
    return ""


def loan_created(page, loan_id: str) -> str:
    j = _get(page, API["loan"].format(id=loan_id))
    return parse_date(str(j.get("created") or ""))


def merchant_label(loan: dict) -> str:
    name = re.sub(r"\s+", " ", (loan.get("merchant_name") or "").strip())
    return name.title() if name.isupper() else name


def collect_documents(page, keep=None, config: Optional[dict] = None) -> List[dict]:
    """One Loan Agreement per loan, dated the day the loan was made."""
    if not on_documents_page(page):
        raise RuntimeError("not on a signed-in affirm.com page")
    rows: List[dict] = []
    for loan in list_loans(page):
        loan_id = str(loan.get("id") or "")
        if not loan_id:
            continue
        date = loan_created(page, loan_id)
        if not date:
            log.info("loan %s has no created date, skipped", redact(loan_id))
            continue
        if keep is not None and not keep(date[:4]):
            continue
        url = terms_url(page, loan_id)
        if not url:
            log.info("loan %s offers no loan terms document", redact(loan_id))
            continue
        rows.append({"title": "Loan Agreement", "date": date, "account": merchant_label(loan),
                     "category": "Loan Agreement", "item_id": loan_id, "client_id": url,
                     "href": url, "period_start": ""})
    return rows


def download_document(page, title: str, date: str, out_path: Path, occurrence: int = 0,
                      item_hint: str = "", client_hint: str = "", account: str = "") -> bool:
    """Fetch the agreement page through the signed-in page and render it to PDF."""
    from paperpull_core import receipt_pdf
    url = terms_url(page, item_hint) if item_hint else ""
    url = url or client_hint
    if not url or not is_safe_url(url):
        log.warning("no loan terms URL for %s %s", title, date)
        return False
    res = page.evaluate(_TEXT_JS, url)
    if res.get("status") in (401, 403):
        raise SessionExpired("Affirm answered %s" % res["status"])
    html = res.get("text") or ""
    if res.get("status") != 200 or "html" not in (res.get("ct") or "") or len(html) < 2000:
        log.warning("loan terms for %s %s did not come back as a page (%s, %s)",
                    title, date, res.get("status"), res.get("ct"))
        return False
    receipt_pdf.print_html_to_pdf(page, html, out_path)
    return out_path.is_file() and out_path.stat().st_size > 1000
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
    """What the signed-in Affirm account looks like, without downloading anything.

    Records the page, its headings and controls with the guard's verdict on
    each, and every JSON response affirm.com sends while the page settles. Then
    follows, one at a time and back again, the few links whose text is
    exactly a document word, recording the same for each. Bodies
    are recorded as shape only, never values, and any run of six digits is
    masked. No screenshot, a loan page shows balances."""
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
