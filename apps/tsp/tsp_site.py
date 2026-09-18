"""ALL Thrift Savings Plan (tsp.gov) selectors, URLs, and page behavior live here.

When My Account changes, repair this file only.

STATUS, read before trusting anything below.

  CONFIRMED from public sources, 2026-09-18:
    * the participant site is My Account, reached from www.tsp.gov, and was
      rebuilt on 1 June 2022 with new credentials for everyone
    * sign-in is username + password + a one-time passcode sent by text,
      voice or email, plus a ThriftLine PIN for phone use. No Login.gov or
      ID.me
    * annual participant statements and the 1099-R are delivered to a secure
      participant mailbox inside My Account, and quarterly statements are
      posted there too
    * the onboarding site is a Salesforce Experience Cloud page
      (onboarding.tsp.gov/onboarding/s/), which suggests My Account is the
      same platform. PG&E's portal is, and its Lightning components needed
      their own handling
    * www.tsp.gov refuses plain HTTP fetches (403), so a real browser is
      the only way in, and possibly a branded one

  NOT YET CONFIRMED, and deliberately not guessed:
    * the hostname and URL of My Account once signed in
    * where the mailbox and statements live, and what the rows look like
    * how a statement PDF is delivered (link, download event, blob, API)
    * whether there is a JSON API behind the pages

  There are NO guessed document URLs here. Until the section below is
  mapped, --discover finds nothing and says so, and --diagnose gathers the
  evidence needed to map it, read only, from tsp.gov pages only, clicking
  nothing that does not pass the guard.

SAFETY (this is a US federal retirement account):
  Strictly READ-ONLY. My Account can move money between funds, change
  contribution allocations, start a withdrawal or an installment, take a
  loan, change beneficiaries and change where money is sent. This app must
  NEVER activate a control that does any of those, never submits a form,
  never confirms a dialog, and never accepts terms on the user's behalf.

  Two further rules for a government system:
    * the user signs in themselves, enters their own passcode, and accepts
      any consent banner themselves. This app does not click through a
      government consent banner.
    * an expired session raises SessionExpired so a run stops loudly rather
      than reporting an empty success.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlsplit

from paperpull_core.controls import SETTINGS_CONTROL_RE, AUTH_CONTROL_RE

log = logging.getLogger("tsp_docs.site")

# Every host this app will read from. Anything else is refused, including
# the government's own single sign-on hosts, which are the user's business.
ALLOWED_HOSTS = ("tsp.gov",)

BASE = "https://www.tsp.gov"
URLS = {
    "home": f"{BASE}/",
    "login": f"{BASE}/login/",
    # Unknown until diagnose has run against a signed-in session. Left empty
    # on purpose, see STATUS above. goto_documents treats any signed-in
    # tsp.gov page as "close enough" until this is filled in.
    "documents": "",
}

LOGIN_URL_MARKERS = ["/login", "/logon", "/signin", "/sign-in", "/mfa",
                     "/verify", "/onboarding"]


class SessionExpired(RuntimeError):
    """My Account answered with a sign-in page instead of the thing asked for."""


def is_safe_url(url: str) -> bool:
    """https, on tsp.gov or a subdomain of it, no credentials in the URL."""
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
# HARD SAFETY GUARD. Tuned for a retirement plan. Never move money between
# funds, never change contributions, never withdraw, never borrow, never
# change who gets the money.
# ---------------------------------------------------------------------------
FORBIDDEN_CONTROL_RE = re.compile(
    r"(interfund|fund\s+transfer|transfer\b|reallocat|realloc\b|allocation\b|"
    r"rebalance|contribution\s+(amount|allocation|election|change)|"
    r"contribut(e|ion\s+percent)|catch-?up|"
    r"withdraw|distribution|installment|annuity\s+purchase|"
    r"\bloan\b|borrow|repay|rollover|roll\s+over|transfer\s+in|"
    r"required\s+minimum|\brmd\b|"
    r"beneficiar|court\s+order|"
    r"direct\s+deposit|bank\s+account|financial\s+institution|routing|"
    r"\bpay\b|payment|"
    # Word boundaries on both sides of the verb stems. "edit" inside
    # "Credit" and "chang" inside "Exchange" are the two that bit before.
    r"\bchang(e|es|ed|ing)\b|\bedit(s|ed|ing)?\b|\bupdat(e|es|ed|ing)\b|"
    r"\bset\s+up\b|enroll|enable|disable|\bdelet|\bremov(e|es|ed|ing|al)\b|"
    r"\bsubmit|\bconfirm\b|\bagree\b|\baccept\b|authoriz|\bapply\b|"
    r"request\b|\bstart\b|\bbegin\b|initiate|"
    r"mutual\s+fund\s+window|\bmfw\b|"
    r"log\s*out|logout|sign\s*out|password|username|thriftline\s+pin|\bpin\b|"
    r"security\s+question|two-?step|contact\s+info|\baddress\b|\bemail\b|\bphone\b)",
    re.I)

# What a document control may look like. A control must match this AND not
# match the blocklist. Message-centre words are here because TSP delivers
# statements and tax forms to a mailbox.
SAFE_DOC_CONTROL_RE = re.compile(
    r"(download|\bview\b|\bopen\b|\bprint\b|\bpdf\b|statement|document|"
    r"1099|tax\s+form|tax\s+statement|letter|notice|correspondence|"
    r"message|mailbox|inbox|history|annual|quarterly)", re.I)


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
    r"^(documents?|statements?|my\s+statements?|tax\s+(forms?|statements?|documents?)|"
    r"messages?|message\s+cent(er|re)|mailbox|inbox|correspondence|"
    r"document\s+history|account\s+history|history)$", re.I)


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
    Visible text only. The page source of a Salesforce site carries every
    string its scripts could ever show."""
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
    """Not known yet. Any signed-in tsp.gov page counts, and that is stated
    in STATUS rather than hidden."""
    try:
        return is_safe_url(page.url or "") and not looks_signed_out(page)
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


# -- what is NOT mapped yet -----------------------------------------------------

DOCUMENT_TYPES: dict = {}   # filled in once diagnose has shown what exists


def collect_documents(page) -> List[dict]:
    """Nothing, until the site is mapped. Says so rather than guessing."""
    log.warning("TSP My Account is not mapped yet. Run diagnose and send the "
                "Diagnostics folder's survey to the maintainer.")
    return []


def download_document(page, document_id: str, out_path: Path) -> bool:
    log.warning("TSP downloads are not mapped yet")
    return False


# -- survey, the evidence diagnose gathers --------------------------------------

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
    """What a signed-in My Account looks like, without downloading anything.

    Records the page, its headings and controls with the guard's verdict on
    each, and every JSON response tsp.gov sends while the page settles. Then
    follows, one at a time and back again, the few links whose text is
    exactly a document or mailbox word, recording the same for each. Bodies
    are recorded as shape only, never values, and any run of six digits is
    masked. No screenshot, a retirement account page shows balances."""
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
