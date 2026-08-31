"""ALL Anthem BCBS member-portal selectors, URLs, and page behavior live here.

When the Anthem member portal changes, repair this file only.

STATUS, read before trusting anything below.

  CONFIRMED against dr's live session by deep recon 2026-08-31 (full notes in
  ~/code/misc/paperpull-anthem-recon.md), after a first pilot exposed the wrong
  assumptions:
    * two hosts: the SPA renders on membersecure.anthem.com; the claims/EOB data
      is a tRPC API on membersecure-polaris.anthem.com.
    * the EOB list is  GET /api/claims/trpc/eob.v1.summary?input=<json>
      with input {claimType, start, end, limit, offset}. claimType is one of
      Medical | Pharmacy | Chiropractic. The member is derived server-side.
    * an EOB PDF is GET /api/claims/trpc/eob.v1.download?input=<json> with input
      {claimId, claimType, eobId}, and the PDF comes back base64-encoded at
      result.data.file inside a JSON envelope (NOT as raw bytes).
    * AUTH: both calls require an `authorization: Bearer <token>` header plus a
      set of `x-*` routing headers - the SESSION COOKIE alone is refused
      (401), and sending credentials:'include' cross-origin is CORS-rejected
      (this is what made the first pilot fail with "Network request failed").
      The token is held in memory by the SPA, not in any JS-readable store, so
      it is CAPTURED from the SPA's own request by an in-page XHR/fetch hook and
      kept in window.__eobHeaders. The bearer stays in the page: our fetches
      read window.__eobHeaders, so it never enters this process, is never logged
      and never touches disk. Priming the hook needs one navigation to the EOB
      center (a read-only page).
    * summary row fields: identifier = the download eobId (opaque, per-row);
      claim[0].identifier[*].value = the claim number; created = the EOB date;
      patient.name = the patient; supportingInfo.eobSubType "Reimbursement" =
      an EOB Check, else an EOB; eobSequenceNbr disambiguates. The eobId is
      resolved fresh at download, never stored (myPay transient-Id lesson).
    * DATE WINDOW: the API returns the full history at 24 months but an EMPTY
      list once `start` is older than ~25-27 months, so the window is capped at
      24 months (the 3-year hope is dead; FHIR is the only >24mo route).
    * Akamai Bot Manager is present (the bmak beacon fires) but tolerated recon.

SAFETY (this is Protected Health Information):
  Strictly READ-ONLY. The Anthem member portal can change a PCP, request an ID
  card, enroll in paperless delivery, appeal a claim, refill a prescription and
  message care teams. This app must NEVER activate a control that does any of
  those, never submits a form, never confirms a dialog, and never enrolls the
  member in anything. It DOES navigate to the read-only EOB center (to capture
  the session), but every EOB is then fetched by an in-page tRPC GET; nothing on
  the page is clicked, so there is no control to mis-fire.
"""
from __future__ import annotations

import json as _json
import logging
import re
from pathlib import Path
from typing import List, Optional, Tuple

log = logging.getLogger("anthem_docs.site")

# The member SPA renders here; the claims/EOB data API lives on the -polaris
# sibling host. Both are needed, and BOTH are matched by parsed host equality,
# never by prefix, so a lookalike like membersecure.anthem.com.evil cannot walk
# through.
PAGE_HOST = "membersecure.anthem.com"
DATA_HOST = "membersecure-polaris.anthem.com"
ALLOWED_HOSTS = {PAGE_HOST, DATA_HOST}

BASE = f"https://{PAGE_HOST}"
# The sign-in page is on the public www host, not the member portal: opening the
# member root for a signed-out profile does not land on a usable login form. The
# member authenticates here, and is redirected to membersecure.anthem.com (which
# IS a data host) once signed in - that redirected tab is the one this app then
# attaches to. www.anthem.com is deliberately NOT a data host: nothing is ever
# fetched from it.
LOGIN_URL = "https://www.anthem.com/account-login/"
URLS = {
    "home": f"{BASE}/",
    "login": LOGIN_URL,
    "documents": f"{BASE}/member/claims/eob-center",
}


# Markers of a genuine sign-in / challenge redirect. "account-login" is Anthem's
# own sign-in path, so a session that expires and bounces there is recognised.
LOGIN_URL_MARKERS = ["account-login", "/login", "/logon", "/signin", "/sso",
                     "samlsso", "returnurl=", "sessiontimeout", "/logout",
                     "/loggedout"]

# ---------------------------------------------------------------------------
# HARD SAFETY GUARD - never click anything matching this.
# Tuned for a health-insurance member portal. Verb families include their
# endings: the sibling apps learned that a guard matching only bare stems let
# "Save Changes" and "Document Removal" through, so the same care is taken here.
# The document NOUNS a member wants ("EOB", "Explanation of Benefits", the
# reimbursement "Check") are deliberately NOT in this list; they are allowed by
# SAFE_DOC_CONTROL_RE below. Only action VERBS are forbidden.
# ---------------------------------------------------------------------------
FORBIDDEN_CONTROL_RE = re.compile(
    # care and coverage actions
    r"(find\s+(care|a\s+doctor|care\s+now)|change\s+pcp|select\s+pcp|"
    r"refill|order\s+(a\s+)?(new\s+)?(id\s+)?card|request\s+(a\s+)?card|id\s+card\s+request|"
    r"appeal|grievance|dispute|prior\s+authorization|pre-?authorization|"
    r"start\s+a?\s*chat|message\s+(your|a|us|care|my)|send\s+(a\s+)?message|secure\s+message|"
    r"schedule|book\s+(an?\s+)?appointment|"
    # enrollment / plan / money
    r"enroll|switch\s+plan|change\s+plan|shop\s+plans|renew|"
    r"pay\s+(premium|now|bill)|make\s+a\s+payment|autopay|auto-?pay|"
    r"\bhsa\b|\bfsa\b|contribution|reimbursement\s+request|submit\s+a\s+claim|file\s+a\s+claim|"
    r"go\s+(100%\s+)?digital|go\s+paperless|paperless|manage\s+paperless|set\s+up\s+now|"
    # identity and account settings
    r"social\s*security|\bssn\b|date\s+of\s+birth|"
    r"address|phone|e-?mail|password|user\s*id|\bpin\b|security\s+question|"
    r"correspondence|mailing|contact\s+info|"
    # verb families, endings included
    r"\bchang(e|es|ed|ing)\b|\bedit(s|ed|ing)?\b|\bupdat(e|es|ed|ing)\b|"
    r"set\s+up|enabl|disabl|delet|remov(e|es|ed|ing|al)|start|stop|restart|"
    r"\boptions?\b|\bsettings?\b|\bpreferences?\b|^\s*save\s*$|save\s+(changes?|settings?|preferences?|profile)|manage|"
    r"consent|agree|accept|opt\s*(in|out)|turn\s+(on|off)|"
    r"elect(ion)?\b|authoriz|certif|"
    # generic commit verbs
    r"submit|confirm|continue|\bnext\b|sign\s+(in|out|up)|appl(y|ies|ied|ication)|"
    r"cancel|activat)", re.I)

# A control must ALSO look like a document action before it may be clicked. This
# app fetches EOBs by API and clicks nothing, so this guard exists to satisfy
# the read-only contract and the repo-wide guard test rather than to gate a live
# click. "Check" here is the reimbursement-check NOUN ("EOB Check"), not a verb.
SAFE_DOC_CONTROL_RE = re.compile(
    r"(download|view|open|print|pdf|statement|document|"
    r"explanation\s+of\s+benefits|\beob\b|eob\s+check|claim\s+summary|"
    r"1095|tax\s+(form|statement|document))", re.I)

SECURITY_CHALLENGE_MARKERS = [
    # OTP / MFA (specific phrasings - a bare "one-time" matched marketing copy)
    "enter the code we sent", "verification code", "one-time code",
    "one-time passcode", "one time pin", "one-time pin",
    "security code", "we sent a code", "two-factor", "two-step",
    "authenticator", "confirm your identity", "verify your identity",
    "remember this device",
    # session
    "your session has expired", "session timeout", "please log in again",
    "please sign in again",
    # Akamai Bot Manager block pages (confirmed sensor present). The exact
    # strings Akamai serves on a block are "Access Denied" and a "Reference #"
    # correlation id; both go here so a crawl that trips the WAF stops loudly
    # instead of recording an empty success.
    "access denied", "reference #", "reference&nbsp;#",
    "you don't have permission to access", "unusual activity", "are you a robot",
    "captcha",
]

RATE_LIMIT_MARKERS = [
    "too many requests", "rate limit", "try again later",
    "temporarily unavailable", "http error 429", "unusual traffic",
]


# ---------------------------------------------------------------------------
# Date parsing
# ---------------------------------------------------------------------------
DATE_PATTERNS = [
    (re.compile(r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
                r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|"
                r"Dec(?:ember)?)\.?\s+(\d{1,2}),?\s+(\d{4})", re.I), "mdY"),
    (re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b"), "mdy_slash"),
    (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"), "iso"),
]
_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
MONTH_YEAR_RE = re.compile(
    r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
    r"Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    r"\s+(\d{4})", re.I)
YEAR_RE = re.compile(r"\b(19|20)(\d{2})\b")
_LAST_DAY = {1: 31, 2: 28, 3: 31, 4: 30, 5: 31, 6: 30,
             7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31}


def _last_day(year: int, month: int) -> int:
    if month == 2 and (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)):
        return 29
    return _LAST_DAY[month]


def parse_date(text: str) -> Optional[str]:
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


def parse_period_date(text: str) -> Tuple[Optional[str], str]:
    """Date to file a document under, plus a human period label."""
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
        # The signed-in member SPA shows a "Log Out" control; a signed-out page
        # shows a password field. Detected only, never typed into.
        return page.locator("input[type='password']").count() > 0
    except Exception:
        return False


def detect_security_challenge(page) -> Optional[str]:
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


def is_safe_control(name: str) -> bool:
    """A control may be clicked only if it looks like a document action AND
    matches nothing in the forbidden list. Empty or unknown means no.

    This app clicks nothing (EOBs are fetched by API), so the guard is a
    belt-and-braces contract check, not a live gate.
    """
    name = (name or "").strip()
    if not name:
        return False
    if FORBIDDEN_CONTROL_RE.search(name):
        return False
    # The shared core guard is consulted as well as this app's own blocklist, so
    # a settings/auth control refused once in core is refused everywhere.
    try:
        from paperpull_core.controls import SETTINGS_CONTROL_RE, AUTH_CONTROL_RE
        if SETTINGS_CONTROL_RE.search(name) or AUTH_CONTROL_RE.search(name):
            return False
    except Exception:
        pass
    return bool(SAFE_DOC_CONTROL_RE.search(name))


def is_safe_url(url: str) -> bool:
    """On Anthem's own hosts, by parsed comparison, never a string prefix."""
    from urllib.parse import urlparse
    try:
        got = urlparse(url or "")
    except ValueError:
        return False
    if got.scheme != "https" or not got.hostname:
        return False
    if (got.hostname or "").lower() not in ALLOWED_HOSTS:
        return False
    if got.username or got.password:
        return False
    return True


def is_anthem_frame(frame) -> bool:
    """True only for a frame actually loaded from an Anthem host.

    The collector walks every frame of every tab in the attached browser, which
    is the user's ordinary Chrome. Without this it would read from unrelated
    sites.
    """
    try:
        url = frame.url or ""
    except Exception:
        return False
    if not url.startswith("https://"):
        return False
    from urllib.parse import urlparse
    try:
        return (urlparse(url).hostname or "").lower() in ALLOWED_HOSTS
    except ValueError:
        return False


def is_anthem_frame_page(page) -> bool:
    """The page itself is on a data host we may FETCH from (strict)."""
    try:
        return is_safe_url(page.url or "")
    except Exception:
        return False


def is_anthem_owned(url: str) -> bool:
    """An Anthem-owned https page we may operate on and navigate within: any
    host at or under anthem.com. Broader than is_safe_url (which is the strict
    "may fetch from" set of data hosts). The app navigates within Anthem-owned
    pages to reach the member portal, but only ever FETCHES from is_safe_url
    hosts, so a drifted www.anthem.com tab can be steered back to the member
    EOB center without widening what the data layer will call.
    """
    from urllib.parse import urlparse
    try:
        got = urlparse(url or "")
    except ValueError:
        return False
    if got.scheme != "https" or got.username or got.password:
        return False
    host = (got.hostname or "").lower()
    return host == "anthem.com" or host.endswith(".anthem.com")


def is_anthem_owned_page(page) -> bool:
    try:
        return is_anthem_owned(page.url or "")
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Session priming: capture the SPA's own auth headers.
#
# The polaris data API authenticates with an `authorization: Bearer <token>`
# header plus a set of `x-*` routing headers. The token is held IN MEMORY by the
# SPA - it is not in localStorage, sessionStorage, IndexedDB or a cookie - so the
# only way to obtain it is to capture it from the SPA's own request. An in-page
# hook on XMLHttpRequest (the SPA uses XHR) and fetch records those headers into
# window.__eobHeaders when the SPA calls an eob endpoint. Navigating once to the
# EOB center triggers that call. The token stays IN THE PAGE: our own in-page
# fetches read window.__eobHeaders, so the bearer never enters this process, is
# never logged and never touches disk.
# ---------------------------------------------------------------------------

# The member portal has TWO auth regimes, so headers are captured into per-surface
# buckets on window.__hdrs, all kept IN THE PAGE:
#   * eob   - the polaris `eob` microapp (eob.v1.*): its own bearer + x-microapp-*
#   * idcard- the polaris `idcard` microapp (idcard.v1.*): its OWN bearer + x-*
#             (a bearer minted for one microapp is refused by another, so each is
#             captured from its own calls)
#   * ms    - the membersecure host's member APIs (/member/secure/api/tcp/* and
#             /fed/benefits/*): one shared session bearer, no x-microapp headers
# window.__eobHeaders stays populated (mirrors the eob bucket) so the untouched EOB
# summary/download path keeps reading exactly what it always did. The member id is
# also captured in-page (window.__memberId) so member-scoped URLs are built there.
_HOOK_JS = r"""
window.__hdrs = window.__hdrs || {eob:null, idcard:null, ms:null};
window.__eobHeaders = window.__eobHeaders || null;
window.__memberId = window.__memberId || null;
(function(){
  if (window.__eobHookInstalled) return;
  window.__eobHookInstalled = true;
  function keep(h){ const o={}; for(const k in h){ if(/^authorization$|^x-/i.test(k)) o[k]=h[k]; } return o; }
  function bucket(url){
    // The two polaris microapps carry a version tag in the path, matched
    // host-independently. The membersecure member APIs are same-origin, so the
    // SPA calls them with RELATIVE urls (no host) - match on the path alone, or
    // a relative-url XHR would never be captured.
    if(/eob\.v1\.(summary|download)/.test(url)) return 'eob';
    if(/idcard\.v1\./.test(url)) return 'idcard';
    if(/\/member\/secure\/api\/tcp\/|\/fed\/benefits\//.test(url)) return 'ms';
    return null;
  }
  function memberId(url){
    // The member id is a long opaque token (~34 chars). Route segments like
    // "message-center" (14) or "dashboard" (9) also sit at /member/<x>/, so the
    // id is taken only from a sufficiently long token to never mistake a route
    // name for the member id.
    var m = /\/member\/([A-Za-z0-9_-]{24,})(?:\/|$)/.exec(url||'');
    if(m && m[1] && !window.__memberId) window.__memberId = m[1];
  }
  function record(url, k){
    var b = bucket(url); if(!b) return;
    if(!Object.keys(k).some(x=>/authorization/i.test(x))) return;
    window.__hdrs[b] = k; if(b==='eob') window.__eobHeaders = k;
  }
  const of = window.fetch;
  window.fetch = function(input, init){
    try{ const url=(typeof input==='string')?input:(input&&input.url)||'';
      memberId(url);
      if(bucket(url) && init && init.headers){
        let h={}; const s=init.headers;
        if(s instanceof Headers){ for(const e of s.entries()) h[e[0]]=e[1]; }
        else if(Array.isArray(s)){ for(const e of s) h[e[0]]=e[1]; } else h=Object.assign({},s);
        record(url, keep(h));
      } }catch(e){}
    return of.apply(this, arguments);
  };
  const oOpen = XMLHttpRequest.prototype.open;
  const oSet  = XMLHttpRequest.prototype.setRequestHeader;
  XMLHttpRequest.prototype.open = function(m,u){ this.__eobUrl=u; memberId(u); this.__hh={}; return oOpen.apply(this, arguments); };
  XMLHttpRequest.prototype.setRequestHeader = function(k,v){
    try{ if(bucket(this.__eobUrl||'') && /^authorization$|^x-/i.test(k)){
        this.__hh[k]=v; record(this.__eobUrl||'', this.__hh); } }catch(e){}
    return oSet.apply(this, arguments);
  };
})();
"""

# The three EOB categories the EOB Center exposes, each its own summary call. A
# category with no EOBs simply returns an empty list and is skipped.
CLAIM_TYPES = ["Medical", "Pharmacy", "Chiropractic"]

# The two document kinds a single claim can expose. "EOB" is the statement;
# "EOB Check" is the reimbursement-check document some claims also carry. Told
# apart by supportingInfo.eobSubType ("HealthCareSummary" vs "Reimbursement").
DOC_KINDS = ["EOB", "EOB Check"]

# Kept for parity with the sibling apps' diagnose/CSV code, which reads a
# provider "type map". Here the meaningful axis is the claim type.
DOCUMENT_TYPES = {t: f"{t} Explanation of Benefits" for t in CLAIM_TYPES}

# How far back to ask for. CONFIRMED live 2026-08-31: the API returns the full
# history at 24 months but an EMPTY list once `start` is older than ~25-27
# months (30mo and 36mo both returned zero rows). So 24 months is both the max
# the server honours and enough to capture everything it keeps.
DEFAULT_LOOKBACK_DAYS = 24 * 30

# Pages whose XHR/fetch we have already hooked (by id()), so add_init_script is
# registered once per page object rather than stacked on every prime.
_hooked_pages = set()

_SUMMARY_JS = r"""async (a) => {
  const h = window.__eobHeaders;
  if (!h) return {status: 0, noauth: true};
  const input = {claimType: a.claimType, start: a.start, end: a.end,
                 limit: 1000, offset: 0};
  const url = 'https://membersecure-polaris.anthem.com/api/claims/trpc/eob.v1.summary'
            + '?input=' + encodeURIComponent(JSON.stringify(input));
  const r = await fetch(url, {headers: Object.assign({'Accept':'application/json'}, h)});
  const ct = r.headers.get('content-type') || '';
  if (!/json/i.test(ct)) return {status: r.status, html: true};
  return {status: r.status, body: await r.json()};
}"""

_DOWNLOAD_JS = r"""async (a) => {
  const h = window.__eobHeaders;
  if (!h) return {status: 0, noauth: true};
  const input = {claimId: a.claimId, claimType: a.claimType, eobId: a.eobId};
  const url = 'https://membersecure-polaris.anthem.com/api/claims/trpc/eob.v1.download'
            + '?input=' + encodeURIComponent(JSON.stringify(input));
  const r = await fetch(url, {headers: Object.assign({'Accept':'application/json, application/pdf'}, h)});
  const ct = r.headers.get('content-type') || '';
  if (/json/i.test(ct)) {
    const j = await r.json();
    // The PDF arrives base64-encoded at result.data.file.
    let file = null;
    try { file = j && j.result && j.result.data && j.result.data.file; } catch(e){}
    if (file) return {status: r.status, b64: file};
    // Unexpected envelope: hand its keys back so Python can report the shape.
    const keys = (j && typeof j === 'object') ? Object.keys(j) : String(typeof j);
    return {status: r.status, badShape: keys};
  }
  // A raw PDF (not seen live, but handled): base64 it for transport.
  const buf = new Uint8Array(await r.arrayBuffer());
  let s = '';
  for (let i = 0; i < buf.length; i++) s += String.fromCharCode(buf[i]);
  return {status: r.status, b64: btoa(s)};
}"""


class SessionExpired(Exception):
    """The server answered a document request with a sign-in page or 401."""


class ListingIncomplete(Exception):
    """A listing could not be fetched or came back with a server/rate-limit
    error (not an auth failure). Raised rather than returning an empty list, so
    a transient 429/5xx/timeout stops the surface loudly instead of recording an
    empty success and leaving a document silently missing from the archive."""


def _has_headers(page) -> bool:
    try:
        return bool(page.evaluate("() => !!window.__eobHeaders"))
    except Exception:
        return False


def prime_session(page, force: bool = False) -> bool:
    """Ensure window.__eobHeaders holds the SPA's captured auth headers.

    Installs the capture hook (once per page) and navigates to the EOB center to
    trigger the SPA's own authenticated eob call, which the hook records. A
    no-op when the headers are already present and `force` is false. The target
    is this app's own host-checked EOB-center URL - a read-only document page;
    nothing is clicked, submitted or confirmed.
    """
    if not is_anthem_owned_page(page):
        return False
    if not force and _has_headers(page):
        return True
    if id(page) not in _hooked_pages:
        try:
            page.add_init_script(_HOOK_JS)
            _hooked_pages.add(id(page))
        except Exception:
            pass
    # The bare EOB-center route only shows the Medical/Pharmacy/Chiropractic
    # tiles and fires no data call; the "/summary" route is what actually issues
    # eob.v1.summary, which is the request the hook needs to capture.
    target = URLS["documents"] + "/summary?eobType=Medical"
    if not is_safe_url(target):
        return False
    try:
        page.goto(target, wait_until="domcontentloaded", timeout=45000)
    except Exception as e:
        log.info("EOB center did not fully settle: %s",
                 str(e).splitlines()[0][:80])
    # Give the SPA a moment to fire its authenticated eob call.
    for _ in range(15):
        if _has_headers(page):
            return True
        try:
            page.wait_for_timeout(1000)
        except Exception:
            break
    return _has_headers(page)


def goto_documents(page) -> bool:
    """Confirm the session is live and prime the captured auth headers."""
    if not (is_anthem_frame_page(page) and not looks_signed_out(page)):
        return False
    return prime_session(page)


def ensure_statements(page) -> bool:
    """Confirm the session is live on an Anthem host (does not force a prime)."""
    return is_anthem_frame_page(page) and not looks_signed_out(page)


def _iso_from_value(value) -> str:
    """"2025-05-20T00:00:00" or "05/20/2025" -> "2025-05-20", read as a
    calendar date (no timezone shift, so a document never files a day early)."""
    s = str(value or "")
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return m.group(0)
    return parse_date(s) or ""


# The confirmed live schema is used first; the older guessed names are kept as
# fallbacks so a future response reshape degrades rather than breaks.
_CLAIMID_KEYS = ["claimId", "claimNumber", "claimNum", "claimID", "claim_id",
                 "claimReferenceNumber"]
_EOBID_KEYS = ["identifier", "eobId", "eobID", "documentId", "docId", "eobKey",
               "documentKey"]
_DATE_KEYS = ["created", "checkDate", "eobStatementDate", "statementDate",
              "eobDate", "processedDate", "serviceDate", "date"]
_KIND_KEYS = ["documentType", "docType", "eobType", "type", "kind"]
# On a family plan each EOB names its patient (patient.name); captured so the
# patient rides into the filename, keeping members' EOBs distinguishable.
_PATIENT_KEYS = ["patient", "patientName", "memberName", "member", "fullName"]
_FIRST_KEYS = ["patientFirstName", "firstName", "memberFirstName", "givenName"]
_LAST_KEYS = ["patientLastName", "lastName", "memberLastName", "familyName"]

_CLAIMNUM_RE = re.compile(r"[A-Za-z0-9]{8,20}")


def _first_key(d: dict, keys) -> Tuple[str, object]:
    """Return (matched_key, value) for the first present, non-empty key."""
    for k in keys:
        if k in d and d[k] not in (None, "", []):
            return k, d[k]
    return "", None


def _walk_for_list(obj) -> List[dict]:
    """Find the list of EOB row dicts inside the tRPC envelope.

    Confirmed live shape is {"result":{"data":[ ...rows ]}}, but this walks
    generically to the first list-of-dicts so a superjson wrap or a reshape does
    not break discovery.
    """
    if isinstance(obj, list):
        return [d for d in obj if isinstance(d, dict)]
    if isinstance(obj, dict):
        for key in ("result", "data", "json", "eobs", "documents", "items",
                    "claims", "summary", "results"):
            if key in obj:
                found = _walk_for_list(obj[key])
                if found:
                    return found
        for v in obj.values():
            found = _walk_for_list(v)
            if found:
                return found
    return []


def _clean_patient(value) -> str:
    """A patient name with any appended DOB / date or wrapper stripped, so a
    birth date never lands in a filename."""
    s = str(value or "")
    s = re.split(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b|\bDOB\b|[\n\r]", s)[0]
    return re.sub(r"\s+", " ", s).strip()


def _title_name(name: str) -> str:
    """Tidy a patient name's casing for the filename without title-casing the
    claim number (which must stay verbatim). "JANE W DOE" -> "Jane W Doe"; a name
    the API already gave in mixed case is trusted as-is."""
    s = (name or "").strip()
    if not s or not (s == s.upper() or s == s.lower()):
        return s
    return " ".join(w[:1].upper() + w[1:].lower() if w.isalpha() else w
                    for w in s.split())


def _patient_name(row: dict) -> str:
    """Patient name for one summary row, or "". Confirmed path is patient.name;
    older shapes (a bare string, or first/last fields) are fallbacks."""
    for k in _PATIENT_KEYS:
        v = row.get(k)
        if isinstance(v, str) and v.strip():
            return _clean_patient(v)
        if isinstance(v, dict):
            name = _first_key(v, ["name", "fullName", "displayName"])[1]
            if name:
                return _clean_patient(name)
            fn = _first_key(v, ["firstName", "first", "givenName"])[1]
            ln = _first_key(v, ["lastName", "last", "familyName"])[1]
            if fn or ln:
                return _clean_patient(f"{fn or ''} {ln or ''}")
    fn = _first_key(row, _FIRST_KEYS)[1]
    ln = _first_key(row, _LAST_KEYS)[1]
    if fn or ln:
        return _clean_patient(f"{fn or ''} {ln or ''}")
    return ""


def _claim_number(row: dict) -> str:
    """The human claim number. Confirmed path: claim[0].identifier[*].value -
    a FHIR identifier array; the claim number is the entry whose value has both
    letters and digits. Falls back to top-level candidate keys."""
    claim = row.get("claim")
    if isinstance(claim, list) and claim and isinstance(claim[0], dict):
        idents = claim[0].get("identifier")
        if isinstance(idents, list):
            values = [e.get("value") for e in idents
                      if isinstance(e, dict) and e.get("value")]
            for v in values:
                sv = str(v)
                if (_CLAIMNUM_RE.fullmatch(sv) and re.search(r"[A-Za-z]", sv)
                        and re.search(r"\d", sv)):
                    return sv
            if values:
                return str(values[-1])
    _, v = _first_key(row, _CLAIMID_KEYS)
    return str(v).strip() if v else ""


def _doc_kind(row: dict) -> str:
    """"EOB Check" for a reimbursement document, else "EOB". Confirmed signal is
    supportingInfo.eobSubType == "Reimbursement"; a documentType/type carrying
    "check" is a fallback."""
    si = row.get("supportingInfo")
    sub = str(si.get("eobSubType")) if isinstance(si, dict) else ""
    if re.search(r"reimburs|check", sub, re.I):
        return "EOB Check"
    _, kind_val = _first_key(row, _KIND_KEYS)
    return "EOB Check" if re.search(r"check", str(kind_val or ""), re.I) else "EOB"


def _extract_row(row: dict, claim_type: str) -> Optional[dict]:
    """Pull (claimId, eobId, date, docKind, patient, seq) out of one summary row.

    Returns None and logs the row's raw keys if a REQUIRED field (the claim
    number or the eobId token) cannot be found - the signal that the response
    reshaped and the field paths need updating.
    """
    eob_id = row.get("identifier") or _first_key(row, _EOBID_KEYS)[1]
    claim_id = _claim_number(row)
    if not claim_id or not eob_id:
        log.error(
            "An EOB summary row is missing a claim number (%s) or eob id (%s). "
            "Raw keys present: %s. Update the field paths in anthem_site.py.",
            "found" if claim_id else "MISSING",
            "found" if eob_id else "MISSING",
            sorted(row.keys()))
        return None
    _, date_val = _first_key(row, _DATE_KEYS)
    seq = row.get("eobSequenceNbr")
    try:
        seq = int(seq)
    except (TypeError, ValueError):
        seq = 0
    return {
        "claim_id": str(claim_id).strip(),
        "eob_id": str(eob_id),
        "date": _iso_from_value(date_val),
        "doc_kind": _doc_kind(row),
        "claim_type": claim_type,
        "patient": _patient_name(row),
        "seq": seq,
    }


def make_doc_id(claim_type: str, claim_id: str, doc_kind: str,
                seq: int = 0) -> str:
    """The stable identity string for one EOB: claimType|claimId|docKind|seq.

    Built from the human claim number, its kind and its (stable) sequence
    number, never from the opaque eobId (resolved fresh at download)."""
    return f"{claim_type}|{claim_id}|{doc_kind}|{int(seq or 0)}"


def parse_doc_id(doc_id: str):
    """"Medical|1234500AA0001|EOB|0" -> ("Medical","1234500AA0001","EOB",0).

    Returns None if malformed or if the claim type / doc kind are not ones this
    app recognises, so a stored or tampered value cannot steer a request at a
    document type the app does not serve. The claim number is validated to the
    alphanumeric shape Anthem uses, which also refuses any path or query
    metacharacter. A trailing sequence number is optional for backward
    compatibility with identities written before it was added.
    """
    m = re.fullmatch(
        r"(Medical|Pharmacy|Chiropractic)\|([A-Za-z0-9]{6,30})\|(EOB Check|EOB)(?:\|(\d{1,4}))?",
        str(doc_id or "").strip())
    if not m:
        return None
    return m.group(1), m.group(2), m.group(3), int(m.group(4) or 0)


def _summary_rows(page, claim_type: str, start: str, end: str) -> List[dict]:
    """The current session's raw EOB summary rows for one claim type.

    Primes the captured auth headers if missing, and re-primes once if the token
    has gone stale (401). Raises SessionExpired if it still cannot authenticate.
    """
    arg = {"claimType": claim_type, "start": start, "end": end}
    res = page.evaluate(_SUMMARY_JS, arg) or {}
    if res.get("noauth") or res.get("status") in (401, 403):
        if prime_session(page, force=True):
            res = page.evaluate(_SUMMARY_JS, arg) or {}
    status = res.get("status")
    if res.get("noauth") or res.get("html") or status in (401, 403):
        raise SessionExpired(
            "Anthem would not authenticate an EOB listing "
            f"(status {status}); the signed-in session is no longer valid")
    if status != 200:
        log.info("eob.v1.summary for %s returned %s", claim_type, status)
        return []
    return _walk_for_list(res.get("body"))


def _date_window(days: int = DEFAULT_LOOKBACK_DAYS) -> Tuple[str, str]:
    from datetime import date, timedelta
    today = date.today()
    return (today - timedelta(days=days)).isoformat(), today.isoformat()


def collect_documents(page) -> List[dict]:
    """Every EOB Anthem holds, across all three claim types, newest first.

    Returns dicts {title, date, account, href, doc_id}. The identity
    (doc_id = claimType|claimId|docKind|seq) is stable and human-meaningful; the
    opaque eobId is deliberately NOT part of it and is fetched fresh at download.
    """
    rows: List[dict] = []
    seen = set()
    if not is_anthem_owned_page(page):
        log.warning("The open tab is not on Anthem. Sign in at anthem.com and "
                    "leave the member portal tab open.")
        return rows
    if not prime_session(page):
        raise SessionExpired(
            "Could not capture Anthem's session from the EOB center; sign in "
            "again and make sure the member portal tab is open")

    start, end = _date_window()
    for claim_type in CLAIM_TYPES:
        try:
            raw = _summary_rows(page, claim_type, start, end)
        except SessionExpired:
            raise
        except Exception as e:
            log.info("summary for %s failed: %s", claim_type,
                     str(e).splitlines()[0][:80])
            continue
        kept = 0
        for r in raw:
            row = _extract_row(r, claim_type)
            if not row:
                continue
            doc_id = make_doc_id(row["claim_type"], row["claim_id"],
                                 row["doc_kind"], row["seq"])
            if doc_id in seen:
                continue
            seen.add(doc_id)
            kind_label = "" if row["doc_kind"] == "EOB" else " Check"
            title = f"{claim_type} Explanation of Benefits{kind_label}"
            rows.append({
                "title": title,
                "date": row["date"],
                # The patient, claim type and number ride in `account`, which the
                # engine suffixes into the filename summary. The patient keeps one
                # family member's EOBs distinguishable; the claim number keeps two
                # claims that share a date distinct and stable across runs.
                "account": (f"{_title_name(row['patient'])} - " if row["patient"] else "")
                           + f"{claim_type} claim {row['claim_id']}",
                "href": "",          # deliberately empty: never a URL
                "doc_id": doc_id,
            })
            kept += 1
        if kept:
            log.info("%-14s %d EOB document(s)", claim_type, kept)

    rows.sort(key=lambda r: r["date"] or "", reverse=True)
    log.info("Anthem: %d EOB document(s) collected", len(rows))
    return rows


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def _looks_like_login_html(body: bytes) -> bool:
    """A sign-in page returned where a PDF was expected."""
    head = body[:4000].lower()
    if b"<html" not in head and b"<!doctype" not in head:
        return False
    return any(m in head for m in (
        b"type=\"password\"", b"type='password'", b"sign in", b"log in",
        b"session has expired", b"access denied"))


def resolve_eob_id(page, claim_type: str, claim_id: str, doc_kind: str,
                   seq: int = 0) -> Optional[str]:
    """The CURRENT opaque eobId for a (claimType, claimId, docKind, seq) document.

    Looked up fresh every time rather than trusted from storage: the eobId is a
    per-session token, so a stored one would go stale. Matches on the stable
    identity; if the sequence number no longer lines up, falls back to the first
    document of that claim and kind. Returns None if it is no longer listed.
    """
    start, end = _date_window()
    matches = []
    for r in _summary_rows(page, claim_type, start, end):
        row = _extract_row(r, claim_type)
        if not row:
            continue
        if row["claim_id"] == claim_id and row["doc_kind"] == doc_kind:
            matches.append((row["seq"], row["eob_id"]))
    if not matches:
        return None
    for s, eob_id in matches:
        if s == seq:
            return eob_id
    return matches[0][1]


def download_document(page, doc_id: str, out_path) -> bool:
    """Save one EOB by its (claimType, claimId, docKind, seq) identity.

    The identity is validated to a known claim type and doc kind and an
    alphanumeric claim number, so the request cannot be pointed elsewhere. The
    opaque eobId is resolved fresh from a current summary and the PDF is
    base64-decoded from the download envelope's result.data.file. Raises
    SessionExpired when Anthem will not authenticate the request.
    """
    import base64
    parsed = parse_doc_id(doc_id)
    if not parsed:
        log.error("refusing a document identity that is not a known claim type, "
                  "claim number and kind")
        return False
    claim_type, claim_id, doc_kind, seq = parsed
    if not is_anthem_owned_page(page):
        raise SessionExpired("the Anthem tab is no longer open on Anthem")
    if not prime_session(page):
        raise SessionExpired("could not capture Anthem's session for a download")
    eob_id = resolve_eob_id(page, claim_type, claim_id, doc_kind, seq)
    if eob_id is None:
        log.warning("Anthem no longer lists a %s %s for claim %s",
                    claim_type, doc_kind, claim_id)
        return False
    arg = {"claimId": claim_id, "claimType": claim_type, "eobId": eob_id}
    try:
        res = page.evaluate(_DOWNLOAD_JS, arg) or {}
    except Exception as e:
        log.warning("download fetch failed: %s", str(e).splitlines()[0][:100])
        return False
    if res.get("noauth") or res.get("status") in (401, 403):
        if prime_session(page, force=True):
            try:
                res = page.evaluate(_DOWNLOAD_JS, arg) or {}
            except Exception as e:
                log.warning("download retry failed: %s", str(e).splitlines()[0][:100])
                return False
    status = res.get("status")
    if res.get("noauth") or status in (401, 403):
        raise SessionExpired("Anthem refused the document request (%s), which "
                             "means the session has expired" % status)
    if status != 200:
        log.warning("download returned %s", status)
        return False
    if res.get("badShape") is not None:
        log.error("eob.v1.download returned an unexpected envelope (top keys: "
                  "%s); the result.data.file path in anthem_site.py needs "
                  "updating.", res.get("badShape"))
        return False
    try:
        body = base64.b64decode(res.get("b64") or "")
    except Exception:
        log.warning("could not base64-decode the download response")
        return False
    if not body.startswith(b"%PDF"):
        if _looks_like_login_html(body):
            raise SessionExpired(
                "Anthem returned a sign-in page instead of a document")
        log.warning("decoded download was not a PDF (%d bytes)", len(body))
        return False
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(body)
    return True


# ---------------------------------------------------------------------------
# The other three document surfaces: member documents (all coverage years),
# ID cards, and Letters. Each is fetched the same way EOBs are - by the portal's
# own authenticated member API, from inside the signed-in page, with the SPA's
# bearer read in-page from window.__hdrs. NOTHING is clicked, submitted or
# confirmed on any of them; the app only ever navigates to a read-only page to
# capture the session and then GETs the documents the portal already generated.
# ---------------------------------------------------------------------------

DOCUMENTS_URL = f"{BASE}/member/documents"
IDCARD_URL = f"{BASE}/member/idcard"
URLS["member_documents"] = DOCUMENTS_URL
URLS["idcard"] = IDCARD_URL

_MS_API = f"{BASE}/member/secure/api/tcp"
_FED_DOC_BASE = f"{BASE}/fed/benefits/v1/member/coveragePeriod"
_POLARIS_IDCARD = "https://membersecure-polaris.anthem.com/api/idcard/trpc"

# A coverage period id, e.g. "79CB-20260701-20261231-MED-721352C26M": a source
# code, a start and end date (YYYYMMDD), a plan type, and a group id. Validated to
# this shape so a stored or reshaped value cannot steer a request off the member's
# own coverage. The download `origin` and `documentTypeCd` are fixed constants
# confirmed to serve every document type live (plan confirmations, EOC, COCC).
_COVERAGE_KEY_RE = re.compile(r"[0-9A-Za-z]{2,6}-(\d{8})-(\d{8})-[A-Za-z]+-[0-9A-Za-z]{2,20}")
_DOC_ORIGIN = "planDocument"
_DOC_TYPE_CD = "All"


def document_folder_for(label: str) -> str:
    """Route a document's label to a storage folder attr."""
    l = (label or "").lower()
    if re.search(r"\b1095\b|tax\s+(form|document|statement)", l):
        return "tax_documents"
    if re.search(r"authoriz|referral|prior\s+auth", l):
        return "authorizations"
    return "plan_documents"


# The document-type codes the member documents API returns, mapped to the human
# label used in the filename. An unknown code falls back to a spaced-out version
# of the code itself, so a new document still files sensibly (and legibly).
_DOC_TYPE_LABELS = {
    "PPOCONF": "Plan Confirmation",
    "OOCBEN": "Out-of-Combined Benefits",
    "EOC": "Evidence of Coverage",
    "COCC": "Certificate of Coverage",
    "SBC": "Summary of Benefits and Coverage",
    "1095B": "1095-B Health Coverage",
    "1095": "1095-B Health Coverage",
}


def document_label_for(document_type: str) -> str:
    """A readable label for a member-document type code."""
    code = (document_type or "").strip()
    return _DOC_TYPE_LABELS.get(code.upper(), code or "Member Document")


def period_start(coverage_key: str) -> str:
    """The coverage period's start date as YYYY-MM-DD (the document's filing
    date), or "" if the key is not the shape this app recognises."""
    m = _COVERAGE_KEY_RE.fullmatch((coverage_key or "").strip())
    if not m:
        return ""
    s = m.group(1)
    return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"


def period_label(coverage_key: str) -> str:
    """A short human coverage-period label for the filename, e.g. "2025" or
    "2026 H2" when a year holds more than one period."""
    m = _COVERAGE_KEY_RE.fullmatch((coverage_key or "").strip())
    if not m:
        return ""
    start = m.group(1)
    year, month = start[0:4], int(start[4:6])
    return f"{year} H{1 if month <= 6 else 2}"


def valid_coverage_key(coverage_key: str) -> bool:
    return bool(_COVERAGE_KEY_RE.fullmatch((coverage_key or "").strip()))


def member_doc_id(coverage_key: str, document_type: str) -> str:
    """Stable identity for one member document: the coverage period plus the
    document-type code. The period is part of the identity so a 2025 document and
    its 2026 namesake are never confused (and never dedupe each other away)."""
    return f"MemberDoc|{coverage_key}|{document_type}"


def _key_safe(s: str) -> str:
    """A dict-key-safe rendering of an identity string (progress.json keys)."""
    return re.sub(r"[^A-Za-z0-9._:@-]+", "_", str(s or "")).strip("_")


def member_doc_key(coverage_key: str, document_type: str) -> str:
    """Delete-safe progress key for a member document - period-aware."""
    return "memberdoc:" + _key_safe(f"{coverage_key}:{document_type}")[:100]


def letter_key(msg_uid: str) -> str:
    return "letter:" + _key_safe(msg_uid)[:100]


def idcard_key(patient: str, card_type: str) -> str:
    return "idcard:" + _key_safe(f"{patient}:{card_type}")[:100]


def _letter_date(create_dt_time) -> str:
    """A secure message's createDtTime (epoch milliseconds) as a calendar date."""
    try:
        from datetime import datetime, timezone
        ms = int(create_dt_time)
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).date().isoformat()
    except (TypeError, ValueError, OSError):
        return ""


def parse_letters(messages: List[dict]) -> List[dict]:
    """Turn the secure-message list into filing rows. Each carries the subject
    (label), the body (rendered into the PDF), the date and the read flag. No
    message is opened and no read flag is ever changed - the list already holds
    the body, and marking-read is a separate action this app never takes."""
    out = []
    for m in messages or []:
        if not isinstance(m, dict):
            continue
        uid = m.get("msgUid")
        if not uid:
            continue
        subject = re.sub(r"\s+", " ", str(m.get("subject") or "")).strip() or "Message"
        out.append({
            "msg_uid": str(uid),
            "label": subject,
            "body": str(m.get("body") or ""),
            "date": _letter_date(m.get("createDtTime")),
            "is_read": bool(m.get("isRead")),
        })
    return out


def parse_id_card_list(list_json: dict) -> List[dict]:
    """Turn idcard.v1.listIdCard into one row per (patient, card). The patient's
    name rides into the filename so each family member's card is distinguishable;
    the opaque card identifier is NOT stored - it is resolved fresh at download,
    exactly like the EOB eobId."""
    out = []
    try:
        patients = ((list_json or {}).get("result") or {}).get("data", {}).get("patient") or []
    except AttributeError:
        return out
    for p in patients:
        if not isinstance(p, dict):
            continue
        name = p.get("name") or {}
        given = " ".join(name.get("given") or []) if isinstance(name, dict) else ""
        family = name.get("family", "") if isinstance(name, dict) else ""
        patient = _title_name(re.sub(r"\s+", " ", f"{given} {family}").strip())
        for c in (p.get("healthIdentificationCard") or []):
            if not isinstance(c, dict):
                continue
            out.append({
                "patient": patient or "Member",
                "card_type": str(c.get("cardType") or "normal"),
                "date": _iso_from_value(c.get("effectiveDate")),
            })
    return out


# ---------------------------------------------------------------------------
# In-page fetch scripts. Each reads the matching bearer from window.__hdrs and
# performs an authenticated GET; the token never enters this process.
# ---------------------------------------------------------------------------

_MEMBER_DOCS_LIST_JS = r"""async () => {
  const h = window.__hdrs && window.__hdrs.ms; const mid = window.__memberId;
  if (!h) return {noauth: true};
  if (!mid) return {nomember: true};
  const cp = 'https://membersecure.anthem.com/member/secure/api/tcp/benefits/member/'
           + encodeURIComponent(mid) + '/coveragePeriods';
  const cr = await fetch(cp, {headers: Object.assign({'Accept':'application/json'}, h)});
  if (cr.status === 401 || cr.status === 403) return {status: cr.status};
  if (!cr.ok) return {status: cr.status, err: true};
  const cj = await cr.json();
  const keys = [];
  (function w(o){ if(o && typeof o==='object'){ for(const k in o){
    if(k==='coverageKey' && typeof o[k]==='string') keys.push(o[k]); else w(o[k]); } } })(cj);
  const uniq = [...new Set(keys)];
  const base = 'https://membersecure.anthem.com/fed/benefits/v1/member/coveragePeriod/';
  const rows = [];
  const failedPeriods = [];
  for (const key of uniq) {
    try {
      const lr = await fetch(base + encodeURIComponent(key) + '/documents?documentTypeCd=ALL',
                             {headers: Object.assign({'Accept':'application/json'}, h)});
      if (!lr.ok) { failedPeriods.push(key); continue; }
      const lj = await lr.json();
      (function c(o){ if(o && typeof o==='object'){
        if('documentType' in o && ('linkName' in o || 'downloadIdType' in o))
          rows.push({coverageKey: key, documentType: String(o.documentType||'')});
        for(const k in o) c(o[k]); } })(lj);
    } catch(e){ failedPeriods.push(key); }
  }
  return {status: 200, rows, failedPeriods};
}"""

_MEMBER_DOC_DOWNLOAD_JS = r"""async (a) => {
  const h = window.__hdrs && window.__hdrs.ms;
  if (!h) return {noauth: true};
  const base = 'https://membersecure.anthem.com/fed/benefits/v1/member/coveragePeriod/';
  const lr = await fetch(base + encodeURIComponent(a.coverageKey) + '/documents?documentTypeCd=ALL',
                         {headers: Object.assign({'Accept':'application/json'}, h)});
  if (lr.status === 401 || lr.status === 403) return {status: lr.status};
  if (!lr.ok) return {status: lr.status};
  const lj = await lr.json();
  let row = null;
  (function c(o){ if(o && typeof o==='object'){
    if(String(o.documentType||'') === a.documentType && ('linkName' in o || 'downloadIdType' in o) && !row) row = o;
    for(const k in o) c(o[k]); } })(lj);
  if (!row) return {notfound: true};
  // The download id is the row's uuid for a uuid-typed doc, else its type code.
  const downloadId = (row.downloadIdType === 'uuid') ? row.uuid : row.documentType;
  const du = base + encodeURIComponent(a.coverageKey) + '/document?documentTypeCd='
           + encodeURIComponent(a.typeCd) + '&downloadId=' + encodeURIComponent(downloadId)
           + '&origin=' + encodeURIComponent(a.origin);
  const dr = await fetch(du, {headers: Object.assign({'Accept':'application/pdf,*/*'}, h)});
  if (dr.status === 401 || dr.status === 403) return {status: dr.status};
  if (!dr.ok) return {status: dr.status};
  const buf = new Uint8Array(await dr.arrayBuffer());
  let s=''; for(let i=0;i<buf.length;i++) s+=String.fromCharCode(buf[i]);
  return {status: 200, b64: btoa(s)};
}"""

_LETTERS_LIST_JS = r"""async () => {
  const h = window.__hdrs && window.__hdrs.ms; const mid = window.__memberId;
  if (!h) return {noauth: true};
  if (!mid) return {nomember: true};
  // folder=all returns every message (read and unread); the endpoint 400s
  // without a folder. cached=false asks for the live list. This is a plain GET
  // of the list - no message is opened, so no read flag is changed.
  const u = 'https://membersecure.anthem.com/member/secure/api/tcp/securemessage/member/'
          + encodeURIComponent(mid) + '/messages?folder=all&cached=false';
  const r = await fetch(u, {headers: Object.assign({'Accept':'application/json'}, h)});
  if (r.status === 401 || r.status === 403) return {status: r.status};
  if (!r.ok) return {status: r.status};
  const j = await r.json();
  return {status: 200, messages: (j.messages || [])};
}"""

_IDCARD_LIST_JS = r"""async () => {
  const h = window.__hdrs && window.__hdrs.idcard;
  if (!h) return {noauth: true};
  const r = await fetch('https://membersecure-polaris.anthem.com/api/idcard/trpc/idcard.v1.listIdCard',
                        {headers: Object.assign({'Accept':'application/json'}, h)});
  if (r.status === 401 || r.status === 403) return {status: r.status};
  if (!r.ok) return {status: r.status};
  return {status: 200, body: await r.json()};
}"""

_IDCARD_VIEW_JS = r"""async (a) => {
  const h = window.__hdrs && window.__hdrs.idcard;
  if (!h) return {noauth: true};
  const base = 'https://membersecure-polaris.anthem.com/api/idcard/trpc/';
  const lr = await fetch(base + 'idcard.v1.listIdCard', {headers: Object.assign({'Accept':'application/json'}, h)});
  if (!lr.ok) return {status: lr.status};
  const lj = await lr.json();
  const pats = (((lj.result||{}).data||{}).patient) || [];
  let card = null, seen = 0;
  for (const p of pats) {
    const nm = p.name || {};
    const who = ((nm.given||[]).join(' ') + ' ' + (nm.family||'')).replace(/\s+/g,' ').trim().toLowerCase();
    for (const c of (p.healthIdentificationCard||[])) {
      if (who === a.patientKey && String(c.cardType||'') === a.cardType) {
        if (seen === a.ordinal) { card = c; break; }
        seen++;
      }
    }
    if (card) break;
  }
  if (!card) return {notfound: true};
  const idf = (card.identifier || [])[0] || {};
  const vu = base + 'idcard.v1.viewIdCard?input=' + encodeURIComponent(JSON.stringify(
    {identifier: {type: idf.type, value: idf.value}, type: card.cardType}));
  const vr = await fetch(vu, {headers: Object.assign({'Accept':'application/json'}, h)});
  if (vr.status === 401 || vr.status === 403) return {status: vr.status};
  if (!vr.ok) return {status: vr.status};
  const vj = await vr.json();
  const img = (((vj.result||{}).data||{}).image) || {};
  return {status: 200,
          front: (img.front||{}).data, frontMime: (img.front||{}).mimeType,
          back:  (img.back ||{}).data, backMime:  (img.back ||{}).mimeType};
}"""


def _prime_bucket(page, target: str, bucket: str, needs_member: bool = False) -> bool:
    """Install the capture hook and navigate to a read-only member page so the
    SPA fires its own authenticated call, whose bearer the hook records into
    window.__hdrs[bucket]. Navigation only ever targets a host-checked URL."""
    if not is_anthem_owned_page(page):
        return False
    if id(page) not in _hooked_pages:
        try:
            page.add_init_script(_HOOK_JS)
            _hooked_pages.add(id(page))
        except Exception:
            pass

    def ready():
        # One round-trip: the bucket's bearer is present, and (if the surface
        # needs it) the member id too.
        try:
            return bool(page.evaluate(
                "([b, m]) => !!(window.__hdrs && window.__hdrs[b]) && (!m || !!window.__memberId)",
                [bucket, needs_member]))
        except Exception:
            return False

    if ready():
        return True
    if not is_safe_url(target):
        return False
    try:
        page.goto(target, wait_until="domcontentloaded", timeout=45000)
    except Exception as e:
        log.info("prime navigation did not settle: %s", str(e).splitlines()[0][:80])
    for _ in range(15):
        if ready():
            return True
        try:
            page.wait_for_timeout(1000)
        except Exception:
            break
    return ready()


def _prime_and_fetch(page, target: str, bucket: str, js: str, what: str,
                     needs_member: bool = False) -> Optional[dict]:
    """Shared front half of the three list_* collectors: confirm the tab is on
    Anthem, capture the surface's session bearer, run its in-page listing GET,
    and interpret the status. Returns the validated response dict, None when
    there is nothing to list (not on Anthem, or a non-200), and raises
    SessionExpired when the session is no longer valid. The per-surface row
    parsing stays in each collector, where the surfaces genuinely differ."""
    if not is_anthem_owned_page(page):
        log.warning("The open tab is not on Anthem; sign in and open the portal.")
        return None
    if not _prime_bucket(page, target, bucket, needs_member=needs_member):
        raise SessionExpired(f"could not capture Anthem's session for {what}")
    try:
        res = page.evaluate(js) or {}
    except Exception as e:
        # A timeout or a page that went away mid-listing must not read as "no
        # documents"; stop the surface loudly.
        raise ListingIncomplete(
            f"the {what} listing could not be fetched: {str(e).splitlines()[0][:80]}")
    status = res.get("status")
    if res.get("noauth") or status in (401, 403):
        raise SessionExpired(f"Anthem would not authenticate the {what} listing")
    if status != 200:
        # A 429/5xx/other error is a failed listing, not an empty one - raise so
        # the run reports an incomplete archive rather than a false success.
        raise ListingIncomplete(
            f"Anthem returned status {status} for the {what} listing")
    return res


def render_html_to_pdf(page, html: str) -> Optional[bytes]:
    """Render a fragment of HTML to a PDF using the browser's own print-to-PDF,
    on a throwaway blank page with all network blocked (so a letter body cannot
    fetch a tracking pixel or any remote resource). Used to turn a letter's text
    and an ID card's front/back images into filed PDFs."""
    import base64
    from paperpull_core.receipt_pdf import PRINT_TO_PDF_OPTIONS, PDF_MAGIC
    ctx = page.context
    scratch = ctx.new_page()
    try:
        try:
            scratch.route(re.compile(r"^https?://"), lambda r: r.abort())
        except Exception:
            pass
        scratch.set_content(html, wait_until="load")
        sess = ctx.new_cdp_session(scratch)
        res = sess.send("Page.printToPDF", dict(PRINT_TO_PDF_OPTIONS))
        data = base64.b64decode(res.get("data") or "")
        return data if data.startswith(PDF_MAGIC) else None
    except Exception as e:
        log.warning("could not render a PDF: %s", str(e).splitlines()[0][:80])
        return None
    finally:
        try:
            scratch.close()
        except Exception:
            pass


def _b64_pdf(res: dict, what: str) -> Optional[bytes]:
    """Decode a {status, b64} download result into verified PDF bytes."""
    import base64
    status = res.get("status")
    if res.get("noauth") or status in (401, 403):
        raise SessionExpired(f"Anthem refused a {what} request; the session has expired")
    if status != 200 or not res.get("b64"):
        if res.get("notfound"):
            log.info("%s is no longer listed", what)
        else:
            log.warning("%s download returned %s", what, status)
        return None
    try:
        body = base64.b64decode(res["b64"])
    except Exception:
        log.warning("could not decode the %s download", what)
        return None
    if not body.startswith(b"%PDF"):
        if _looks_like_login_html(body):
            raise SessionExpired("Anthem returned a sign-in page instead of a document")
        log.warning("%s was not a PDF (%d bytes)", what, len(body))
        return None
    return body


# ---------------------------------------------------------------------------
# Member documents (all coverage years).
# ---------------------------------------------------------------------------

def list_member_documents(page) -> List[dict]:
    """Every member document across ALL coverage periods (this year and prior
    years), newest period first. Each row is filing metadata only; the PDF is
    fetched on demand by download_member_document. Fetched by the portal's own
    API - nothing is clicked."""
    rows: List[dict] = []
    res = _prime_and_fetch(page, DOCUMENTS_URL, "ms", _MEMBER_DOCS_LIST_JS,
                           "member documents", needs_member=True)
    if res is None:
        return rows
    # A coverage period whose document list failed to load is reported by name,
    # never silently dropped - otherwise a whole year could go missing quietly.
    for key in res.get("failedPeriods") or []:
        log.warning("member documents for coverage period %s could not be "
                    "listed; that period may be incomplete - re-run to retry",
                    period_label(key) or key)
    seen = set()
    for r in res.get("rows") or []:
        key, dtype = r.get("coverageKey", ""), r.get("documentType", "")
        if not valid_coverage_key(key) or not dtype:
            continue
        doc_id = member_doc_id(key, dtype)
        if doc_id in seen:
            continue
        seen.add(doc_id)
        label = document_label_for(dtype)
        rows.append({
            "doc_id": doc_id,
            "key": member_doc_key(key, dtype),
            "label": f"{label} ({period_label(key)})" if period_label(key) else label,
            "folder_attr": document_folder_for(f"{dtype} {label}"),
            "date": period_start(key),
            "coverage_key": key,
            "document_type": dtype,
        })
    rows.sort(key=lambda r: r["date"] or "", reverse=True)
    log.info("Anthem: %d member document(s) across all coverage periods", len(rows))
    return rows


def download_member_document(page, coverage_key: str, document_type: str) -> Optional[bytes]:
    """The PDF bytes for one member document, resolved and fetched fresh. The
    coverage period is validated to its known shape so a stored value cannot be
    pointed off the member's own coverage."""
    if not valid_coverage_key(coverage_key):
        log.error("refusing a document request for an unrecognised coverage period")
        return None
    if not _prime_bucket(page, DOCUMENTS_URL, "ms", needs_member=True):
        raise SessionExpired("could not capture Anthem's session for a document download")
    arg = {"coverageKey": coverage_key, "documentType": document_type,
           "typeCd": _DOC_TYPE_CD, "origin": _DOC_ORIGIN}
    res = page.evaluate(_MEMBER_DOC_DOWNLOAD_JS, arg) or {}
    return _b64_pdf(res, "member document")


# ---------------------------------------------------------------------------
# ID / insurance cards (one PDF per member's card: front + back).
# ---------------------------------------------------------------------------

def list_id_cards(page) -> List[dict]:
    """One row per (member, card). The patient name rides into the filename so
    each family member's card is distinguishable. Fetched by the idcard microapp
    API - nothing is clicked."""
    rows: List[dict] = []
    res = _prime_and_fetch(page, IDCARD_URL, "idcard", _IDCARD_LIST_JS, "ID card")
    if res is None:
        return rows
    ordinals: dict = {}
    for c in parse_id_card_list(res.get("body") or {}):
        patient, card_type = c["patient"], c["card_type"]
        ord_key = (patient.lower(), card_type)
        ordinal = ordinals.get(ord_key, 0)
        ordinals[ord_key] = ordinal + 1
        card_label = "Insurance Card" if card_type == "normal" else f"{card_type.title()} Insurance Card"
        rows.append({
            "doc_id": f"IdCard|{patient}|{card_type}|{ordinal}",
            "key": idcard_key(f"{patient}:{ordinal}", card_type),
            "label": f"{patient} {card_label}".strip(),
            "folder_attr": "id_cards",
            "date": c["date"],
            "patient": patient,
            "card_type": card_type,
            "ordinal": ordinal,
        })
    log.info("Anthem: %d ID card(s)", len(rows))
    return rows


def download_id_card(page, patient: str, card_type: str, ordinal: int = 0) -> Optional[bytes]:
    """The PDF (front then back) for one member's card, resolved fresh: the
    opaque card identifier is looked up from a current listing at download time,
    never stored - the same rule the EOB eobId follows."""
    if not _prime_bucket(page, IDCARD_URL, "idcard"):
        raise SessionExpired("could not capture Anthem's session for an ID card")
    arg = {"patientKey": re.sub(r"\s+", " ", (patient or "")).strip().lower(),
           "cardType": card_type, "ordinal": int(ordinal or 0)}
    res = page.evaluate(_IDCARD_VIEW_JS, arg) or {}
    status = res.get("status")
    if res.get("noauth") or status in (401, 403):
        raise SessionExpired("Anthem refused an ID card request; the session has expired")
    if status != 200:
        if res.get("notfound"):
            log.info("ID card for %s (%s) is no longer listed", patient, card_type)
        else:
            log.warning("ID card view returned %s", status)
        return None
    sides = []
    for key, mime_key, side in (("front", "frontMime", "Front"), ("back", "backMime", "Back")):
        data = res.get(key)
        mime = res.get(mime_key) or "image/png"
        if data:
            sides.append(
                f'<div class="card"><div class="side">{side}</div>'
                f'<img src="data:{mime};base64,{data}"></div>')
    if not sides:
        log.warning("ID card for %s returned no image", patient)
        return None
    html = ("<html><head><style>"
            "body{margin:0;font-family:Arial,Helvetica,sans-serif}"
            ".card{page-break-after:always;padding:24px}"
            ".side{font-size:12px;color:#555;margin-bottom:8px}"
            "img{max-width:100%;border:1px solid #ccc}"
            "</style></head><body>" + "".join(sides) + "</body></html>")
    return render_html_to_pdf(page, html)


# ---------------------------------------------------------------------------
# Letters (secure Message Center). READ-SAFE: the message list already carries
# each message body, so nothing is opened; marking a message read is a separate
# action this app never takes, so fetching never changes a read flag.
# ---------------------------------------------------------------------------

def list_letters(page) -> List[dict]:
    """Every secure message as a filing row (subject, body, date, read flag).
    Fetched by the securemessage API from the captured session; no message is
    opened and no read flag is changed."""
    rows: List[dict] = []
    res = _prime_and_fetch(page, DOCUMENTS_URL, "ms", _LETTERS_LIST_JS,
                           "message", needs_member=True)
    if res is None:
        return rows
    for m in parse_letters(res.get("messages") or []):
        rows.append({
            "doc_id": f"Letter|{m['msg_uid']}",
            "key": letter_key(m["msg_uid"]),
            "label": m["label"],
            "folder_attr": "letters",
            "date": m["date"],
            "body": m["body"],
            "is_read": m["is_read"],
        })
    rows.sort(key=lambda r: r["date"] or "", reverse=True)
    log.info("Anthem: %d letter(s)", len(rows))
    return rows


def render_letter(page, subject: str, body: str, date: str = "") -> Optional[bytes]:
    """Render one secure message (subject + body) to a filed PDF. The body is
    treated as the portal's own HTML/text; all network is blocked during render
    so nothing in it can phone home."""
    import html as _html
    safe_subject = _html.escape(subject or "Message")
    # A body may be HTML already or plain text; if it has no tags, keep its line
    # breaks. Either way it renders with network blocked.
    body = body or ""
    if not re.search(r"<[a-zA-Z]", body):
        body = _html.escape(body).replace("\n", "<br>")
    head = (f'<div class="meta">{_html.escape(date)}</div>' if date else "")
    doc = ("<html><head><meta charset='utf-8'><style>"
           "body{font-family:Arial,Helvetica,sans-serif;margin:0;color:#111}"
           ".meta{color:#666;font-size:12px;margin-bottom:4px}"
           "h1{font-size:18px;margin:0 0 12px}"
           ".body{font-size:13px;line-height:1.5}"
           "</style></head><body>"
           f"{head}<h1>{safe_subject}</h1><div class='body'>{body}</div>"
           "</body></html>")
    return render_html_to_pdf(page, doc)
