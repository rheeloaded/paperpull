"""Raisin (Weltsparen) deposit documents, listed and fetched from inside the
signed-in dashboard tab.

UNTESTED. Built 2026-11-20 without an account. Every route here was first
seen in Habeas sources, sources/raisin.json (CC0, marked first-party and
verified 2026-09-30). No outside code was read or copied, only these facts.

  page      https://www.raisin.com/, the dashboard's address carries the
            customer number as its customer_id parameter, BAC_ and digits
  deposits  GET https://api2.weltsparen.de/dbff/v1/public/deposits/dashboard/active
            and .../inactive, with customer_id, locale, sort_by=availability
            and order_by=asc. Each entry's accounting.deposit_id is FDA_
            (a term deposit) or OMA_ (overnight savings) and a token
  documents GET /dds/api/v2/public/documents with customer_id and
            deposit_id, items under "documents" with id, created, title
            and document_type
  file      GET /dds/api/v2/public/documents/{id}?preview=true, a PDF
  auth      a bearer token, the access_token of the JSON in the page's
            localStorage key auth_token. The API uses no cookie

Every call runs INSIDE the page with fetch, which reads the token in the
same expression, so the token never enters this process, is never
logged, never reaches a failure file, Diagnose or the survey, and never
touches disk. The fetch sends no cookie and follows no redirect. The
customer number is read from the tab's address and kept only as a digest
in records. It is handed to the page for the request and never written.

What is not known until a tester's first run, each a named constant a
tester's Diagnose or failure file confirms or repairs:
  DEPOSIT_LIST_KEYS  where the deposits answer keeps its entries
  LOCALE             the locale value the dashboard sends
  ISSUER_WORDS       the name a document prints for who issued it
  DATE_FORMS         how a document prints its own date

SAFETY. This is a savings account that moves money. The dashboard can
open, extend and end deposits, transfer to and from the reference
account and change personal and tax data. This app activates no control,
submits nothing and navigates nowhere. It makes GET requests to three
paths on one host and nothing else.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import date as _date
from hashlib import sha256
from urllib.parse import parse_qs, quote, urlencode, urlsplit

from paperpull_core import identity, intake
from paperpull_core.api_census import shape_of
from paperpull_core.characters import whole_json
from paperpull_core.controls import AUTH_CONTROL_RE, SETTINGS_CONTROL_RE
from paperpull_core.urls import is_safe_url as _host_allows

log = logging.getLogger("raisin_docs.site")

PAGE_HOST = "www.raisin.com"
API_HOST = "api2.weltsparen.de"
PAGE = f"https://{PAGE_HOST}/"
API = f"https://{API_HOST}"
URLS = {"home": PAGE, "login": PAGE, "documents": PAGE}
ALLOWED_HOSTS = (PAGE_HOST, API_HOST)
LOGIN_URL_MARKERS = ("/login", "/signin", "/sign-in", "/anmelden", "/auth")

# The only three things this app ever asks the API for.
ACTIVE_PATH = "/dbff/v1/public/deposits/dashboard/active"
INACTIVE_PATH = "/dbff/v1/public/deposits/dashboard/inactive"
DOCUMENTS_PATH = "/dds/api/v2/public/documents"
FILE_PATH = re.compile(r"^/dds/api/v2/public/documents/[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")

CUSTOMER_ID = re.compile(r"^BAC_[0-9]{1,20}$")
DEPOSIT_ID = re.compile(r"^(FDA|OMA)_[A-Za-z0-9-]{1,64}$")
DOCUMENT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
DEPOSIT_KINDS = {"FDA": "term_deposits", "OMA": "overnight_savings"}
_CREATED = re.compile(
    r"^([0-9]{4}-[0-9]{2}-[0-9]{2})"
    r"(?:[T ][0-9]{2}:[0-9]{2}(?::[0-9]{2}(?:\.[0-9]{1,9})?)?(?:Z|[+-][0-9]{2}:?[0-9]{2})?)?$")

# Unconfirmed. The value the dashboard's own requests send for locale.
LOCALE = "de"
# Unconfirmed. Where the deposits answer keeps its entries, when it is not
# a list itself. Any other shape stops the list, and Diagnose writes the
# answer's shape (field names and types, never a value) for the tester to
# send.
DEPOSIT_LIST_KEYS = ("deposits", "items", "data", "content")

LIST_BYTES = 4_000_000
MAX_DEPOSITS = 500
MAX_DOCUMENTS = 5000

# ---------------------------------------------------------------------------
# HARD SAFETY GUARD. Tuned for a savings marketplace. Never open, extend,
# end or move a deposit, never transfer, never change personal, tax or bank
# data. The app presses nothing at all, so this only serves Record.
# ---------------------------------------------------------------------------
FORBIDDEN_CONTROL_RE = re.compile(
    r"(\b(?:transfer|payout|pay\s*out|withdraw\w*|deposit\s+money|top\s*up|invest\w*|"
    r"open\s+(?:a\s+)?(?:new\s+)?(?:deposit|account)|apply|order|buy|sell|"
    r"extend|prolong\w*|renew\w*|terminat\w*|cancel\w*|close|end\s+deposit|"
    r"confirm|submit|accept|agree|sign\b|change|edit|update|delete|remove|"
    r"reference\s+account|iban|tax\s+(?:id|exemption)|exemption\s+order)\b|"
    r"\b(?:(?:ü|ue)berweis\w*|auszahl\w*|einzahl\w*|anlegen|anlage\s+(?:er(?:ö|oe)ffnen|abschlie(?:ß|ss)en)|"
    r"jetzt\s+anlegen|beantrag\w*|bestell\w*|kaufen|verkaufen|verl(?:ä|ae)nger\w*|"
    r"k(?:ü|ue)ndig\w*|beend\w*|schlie(?:ß|ss)en|best(?:ä|ae)tigen|absenden|senden|"
    r"zustimmen|akzeptieren|unterschreiben|(?:ä|ae)ndern|bearbeiten|l(?:ö|oe)schen|"
    r"entfernen|referenzkonto|freistellungsauftrag\s+(?:erteilen|(?:ä|ae)ndern)|steuer-?id)\b)",
    re.I)
SAFE_DOC_CONTROL_RE = re.compile(
    r"\b(?:documents?|dokumente?|postbox|postfach|download|herunterladen|pdf|"
    r"statements?|kontoausz(?:ü|ue)ge?|anzeigen|view|show|ansehen)\b", re.I)


def is_safe_control(name: str) -> bool:
    name = (name or "").strip()
    if not name:
        return False
    if (FORBIDDEN_CONTROL_RE.search(name) or SETTINGS_CONTROL_RE.search(name)
            or AUTH_CONTROL_RE.search(name)):
        return False
    return bool(SAFE_DOC_CONTROL_RE.search(name))


FALLBACK = {"doc_row": "main a[href*='document'], main button"}
RATE_LIMIT_MARKERS = re.compile(r"too many requests|rate limit|zu viele anfragen", re.I)
CHALLENGE_MARKERS = re.compile(
    r"verify you are human|are you a robot|captcha|access denied|"
    r"sicherheitspr(?:ü|ue)fung|zugriff verweigert", re.I)


class SessionExpired(RuntimeError):
    """Raisin answered as signed out, or the page holds no token."""


class ListStopped(RuntimeError):
    """The deposits or documents list could not be read to its end."""


class Refused(RuntimeError):
    """Raisin did not hand over one document's file."""


@dataclass(frozen=True)
class RawDoc:
    document_id: str
    deposit_id: str
    deposit_kind: str
    created: str
    title: str
    document_type: str
    customer: str

    @property
    def key_part(self) -> str:
        return f"{self.deposit_id}:{self.document_id}"


# What the last listing found, kept for the run's downloads and for
# Diagnose. Never a customer number, never a token.
_RUN: dict = {}


def is_safe_url(url: str) -> bool:
    return _host_allows(url, ALLOWED_HOSTS, subdomains=False)


def is_page_url(url: str) -> bool:
    """An address on the dashboard's own host, www.raisin.com."""
    if not is_safe_url(url):
        return False
    return (urlsplit(url).hostname or "").lower() == PAGE_HOST


def customer_of(url: str) -> str:
    """The customer number the tab's own address carries, or "". A second
    customer_id that disagrees, or one of another shape, is none at all."""
    if not is_page_url(url or ""):
        return ""
    try:
        values = parse_qs(urlsplit(url).query, keep_blank_values=True).get("customer_id", [])
    except ValueError:
        return ""
    values = set(values)
    if len(values) != 1:
        return ""
    value = values.pop()
    return value if CUSTOMER_ID.fullmatch(value) else ""


def is_dashboard_url(url: str) -> bool:
    """A www.raisin.com tab whose address names one customer."""
    return bool(customer_of(url))


def tag(value: str) -> str:
    return sha256(("raisin:" + value).encode()).hexdigest()


def customer_tag(page) -> str:
    try:
        customer = customer_of(page.url or "")
    except Exception:
        return ""
    return tag(customer) if customer else ""


def looks_signed_out(page) -> bool:
    try:
        url = page.url or ""
    except Exception:
        # A page that cannot say where it is is not a signed-in page.
        return True
    if not is_safe_url(url):
        return False
    path = urlsplit(url).path.lower()
    if any(path.rstrip("/").endswith(m) or (m + "/") in path for m in LOGIN_URL_MARKERS):
        return True
    try:
        return page.locator("input[type='password']").count() > 0
    except Exception:
        return False


def detect_security_challenge(page):
    try:
        if not is_page_url(page.url or ""):
            return None
        title = page.title() or ""
    except Exception:
        return None
    if RATE_LIMIT_MARKERS.search(title):
        return "Raisin is limiting requests. Try again later."
    if CHALLENGE_MARKERS.search(title):
        return "Raisin is asking for a check in the browser."
    return None


# Runs inside the page. Reads the token in the same expression and makes
# one GET to the API host, with no cookie and no redirect followed. Hands
# back the status and the body (text for a list, base64 for a file), and
# never the token or any header.
_API_JS = r"""async ({url, want}) => {
  if (location.protocol !== 'https:' || location.hostname !== 'www.raisin.com') {
    return {status: 0, where: 'offsite'};
  }
  const target = new URL(url);
  if (target.protocol !== 'https:' || target.hostname !== 'api2.weltsparen.de'
      || target.port !== '' || target.username !== '' || target.password !== '') {
    return {status: 0, where: 'offhost'};
  }
  let token = '';
  try {
    const held = JSON.parse(window.localStorage.getItem('auth_token') || 'null');
    if (held && typeof held.access_token === 'string') token = held.access_token;
  } catch (e) { token = ''; }
  if (!token) return {status: 0, where: 'notoken'};
  let r;
  try {
    r = await fetch(target.href, {
      method: 'GET', credentials: 'omit', redirect: 'error', cache: 'no-store',
      headers: {'Authorization': 'Bearer ' + token,
                'Accept': want === 'pdf' ? 'application/pdf' : 'application/json'}});
  } catch (e) {
    return {status: 0, where: 'network'};
  }
  token = '';
  const ct = (r.headers.get('content-type') || '').toLowerCase();
  if (r.status !== 200) {
    try { if (r.body) await r.body.cancel(); } catch (e) {}
    return {status: r.status, ct};
  }
  if (want === 'pdf') {
    const buf = await ppRead(r);
    let s = '';
    for (let i = 0; i < buf.length; i += 0x8000) {
      s += String.fromCharCode.apply(null, buf.subarray(i, i + 0x8000));
    }
    return {status: 200, ct, b64: btoa(s)};
  }
  return {status: 200, ct, text: await ppText(r)};
}"""


def _allowed(path: str) -> bool:
    return path in (ACTIVE_PATH, INACTIVE_PATH, DOCUMENTS_PATH) or bool(FILE_PATH.fullmatch(path))


def _ask(page, path: str, params: dict, want: str, limit: int) -> dict:
    """One GET from inside the page. Raises ValueError for a request this
    app never makes, before anything is asked."""
    if not _allowed(path):
        raise ValueError("refusing a request this app does not make")
    url = API + path + ("?" + urlencode(params) if params else "")
    if not is_safe_url(url):
        raise ValueError("refusing an off-host request")
    answer = intake.evaluate(page, _API_JS, {"url": url, "want": want}, limit=limit)
    if not isinstance(answer, dict):
        return {"status": 0, "where": "unreadable"}
    return answer


def _note_shape(name: str, value) -> None:
    _RUN.setdefault("shapes", {})[name] = shape_of(value)


def _list_call(page, path: str, params: dict, what: str, name: str):
    """A list answer, parsed. Sign-out, refusal and anything unreadable are
    each raised as what they are."""
    try:
        answer = _ask(page, path, params, "json", LIST_BYTES)
    except intake.TooLarge:
        raise ListStopped(f"Raisin's {what} answer was larger than PaperPull reads") from None
    except ValueError:
        raise
    except Exception as e:
        raise ListStopped(f"Raisin's {what} did not answer ({type(e).__name__})") from None
    status, where = answer.get("status"), answer.get("where", "")
    _RUN.setdefault("statuses", {})[name] = status if isinstance(status, int) else -1
    if where == "notoken":
        _RUN["token"] = False
        raise SessionExpired("the Raisin page holds no sign-in")
    _RUN["token"] = True
    if where == "offsite":
        raise ListStopped("The Raisin tab left www.raisin.com.")
    if status == 401:
        raise SessionExpired(f"Raisin answered the {what} as signed out")
    if status == 403:
        raise ListStopped(f"Raisin refused the {what}.")
    if status == 429:
        raise ListStopped("Raisin is limiting requests. Try again later.")
    if status != 200:
        raise ListStopped(f"Raisin's {what} did not answer.")
    if "json" not in str(answer.get("ct", "")):
        raise ListStopped(f"Raisin's {what} did not answer as a list.")
    try:
        return whole_json(json.loads(answer.get("text") or ""))
    except (TypeError, ValueError):
        raise ListStopped(f"Raisin's {what} did not answer as a list.") from None


def _entries(data) -> list:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        found = [data[k] for k in DEPOSIT_LIST_KEYS if isinstance(data.get(k), list)]
        if len(found) == 1:
            return found[0]
    raise ListStopped("Raisin's deposits answer is not a shape PaperPull knows.")


def _deposits(page, customer: str, which: str) -> list:
    path = ACTIVE_PATH if which == "active" else INACTIVE_PATH
    data = _list_call(page, path, {"customer_id": customer, "locale": LOCALE,
                                   "sort_by": "availability", "order_by": "asc"},
                      f"{which} deposits", f"deposits_{which}")
    _note_shape(f"deposits_{which}", data)
    out = []
    for entry in _entries(data):
        accounting = entry.get("accounting") if isinstance(entry, dict) else None
        deposit = accounting.get("deposit_id") if isinstance(accounting, dict) else None
        if not isinstance(deposit, str) or not DEPOSIT_ID.fullmatch(deposit):
            raise ListStopped("Raisin listed a deposit PaperPull does not recognize.")
        out.append(deposit)
    return out


def created_date(value) -> str:
    """The ISO day a document's created field names, or "" for anything
    that is not an ISO date or timestamp of a real day. The day is the one
    written, before any time or zone."""
    if not isinstance(value, str):
        return ""
    match = _CREATED.fullmatch(value.strip())
    if not match:
        return ""
    try:
        return _date.fromisoformat(match[1]).isoformat()
    except ValueError:
        return ""


def _documents(page, customer: str, deposit: str) -> list:
    data = _list_call(page, DOCUMENTS_PATH, {"customer_id": customer, "deposit_id": deposit},
                      "documents", "documents")
    _note_shape("documents", data)
    items = data.get("documents") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise ListStopped("Raisin's documents answer is not a shape PaperPull knows.")
    out = []
    for item in items:
        if not isinstance(item, dict):
            raise ListStopped("Raisin listed a document PaperPull does not recognize.")
        doc_id, title, kind = item.get("id"), item.get("title"), item.get("document_type")
        if isinstance(doc_id, int) and not isinstance(doc_id, bool):
            doc_id = str(doc_id)
        created = created_date(item.get("created"))
        if (not isinstance(doc_id, str) or not DOCUMENT_ID.fullmatch(doc_id)
                or not isinstance(title, str) or not title.strip()
                or not isinstance(kind, str) or not created):
            raise ListStopped("Raisin listed a document PaperPull does not recognize.")
        out.append((doc_id, created, re.sub(r"\s+", " ", title).strip(), kind.strip()))
    return out


def collect_documents(page) -> list:
    """Every document of every deposit, active and ended, for the customer
    the tab's address names. Raises unless every list answered whole."""
    _RUN.clear()
    customer = customer_of(page.url or "")
    if not customer:
        raise ListStopped("Open your Raisin dashboard, whose address names your customer number.")
    who = tag(customer)
    deposits = []
    for which in ("active", "inactive"):
        for deposit in _deposits(page, customer, which):
            if deposit not in deposits:
                deposits.append(deposit)
    if len(deposits) > MAX_DEPOSITS:
        raise ListStopped("Raisin listed more deposits than PaperPull reads.")
    _RUN["deposits"] = {kind: sum(d.startswith(prefix + "_") for d in deposits)
                        for prefix, kind in DEPOSIT_KINDS.items()}
    docs: dict = {}
    for deposit in deposits:
        if customer_of(page.url or "") != customer:
            raise ListStopped("The Raisin tab changed to another customer.")
        for doc_id, created, title, kind in _documents(page, customer, deposit):
            raw = RawDoc(doc_id, deposit, DEPOSIT_KINDS[deposit[:3]], created, title, kind, who)
            if raw.key_part in docs and docs[raw.key_part] != raw:
                raise ListStopped("Raisin listed one document twice, differently.")
            docs[raw.key_part] = raw
            if len(docs) > MAX_DOCUMENTS:
                raise ListStopped("Raisin listed more documents than PaperPull reads.")
    if customer_of(page.url or "") != customer:
        raise ListStopped("The Raisin tab changed to another customer.")
    _RUN.update(page=page, customer=who, docs=docs)
    return list(docs.values())


def session_proven(page) -> bool:
    """Whether a signed-in read answered. Both deposit lists, and the
    documents of the first deposit when there is one. Raises what stopped
    it, so Login can say which."""
    customer = customer_of(page.url or "")
    if not customer:
        raise ListStopped("Open your Raisin dashboard, whose address names your customer number.")
    deposits = _deposits(page, customer, "active") + _deposits(page, customer, "inactive")
    if deposits:
        _documents(page, customer, deposits[0])
    return True


def listed_now(page, account: str, deposit_id: str, document_id: str):
    """The document as the dashboard lists it now, or None when it is not
    listed. Read again when this run's list was of another tab or customer.
    A tab of another customer than the one it was listed for stops the run
    before anything is asked."""
    if not account or customer_tag(page) != account:
        raise ListStopped("Reopen the dashboard of the customer this document was listed for.")
    if _RUN.get("page") is not page or _RUN.get("customer") != account:
        collect_documents(page)
    return _RUN["docs"].get(f"{deposit_id}:{document_id}")


def neighbors(rows, index: int, span: int = 3) -> list:
    """The (date, title) rows a document could be confused with, for
    check_text. The rows either side and every row of the same date, as
    paperpull_core.identity.rivals_for picks them, on plain pairs, since
    check_text weighs the date and the title apart."""
    rows = list(rows or ())
    if not (0 <= index < len(rows)):
        return []
    near = set(range(max(0, index - span), min(len(rows), index + span + 1)))
    near.update(n for n, r in enumerate(rows) if r[0] == rows[index][0])
    near.discard(index)
    return [rows[n] for n in sorted(near)]


def last_listing() -> dict:
    """Counts and shapes from the last listing, for Diagnose. Never a value."""
    docs = _RUN.get("docs") or {}
    return {"deposits": dict(_RUN.get("deposits") or {}),
            "documents_total": len(docs),
            "statuses": dict(_RUN.get("statuses") or {}),
            "token_present": _RUN.get("token"),
            "shapes": dict(_RUN.get("shapes") or {})}


# -- the file ------------------------------------------------------------------

def fetch_file(page, document_id: str) -> bytes:
    """One document's PDF, asked for from inside the page. Raises Refused
    for anything that is not a PDF, a sign-out included, which the list
    read again tells apart."""
    if not DOCUMENT_ID.fullmatch(document_id or ""):
        raise Refused("not a document id")
    try:
        answer = _ask(page, DOCUMENTS_PATH + "/" + quote(document_id, safe=""),
                      {"preview": "true"}, "pdf", intake.DOCUMENT_BYTES)
    except intake.TooLarge:
        raise Refused("too large") from None
    except Exception as e:
        raise Refused(type(e).__name__) from None
    status = answer.get("status")
    # A 401 or a page without its token is weighed against the list read
    # again by the caller (paperpull_core.refused), which says whether the
    # session ended or only this document was refused.
    if status != 200 or not answer.get("b64"):
        raise Refused("status %s" % (status if isinstance(status, int) else "none"))
    try:
        data = intake.decode(answer["b64"], limit=intake.DOCUMENT_BYTES)
    except Exception:
        raise Refused("unreadable") from None
    if not data.startswith(b"%PDF-"):
        raise Refused("not a pdf")
    return data


# -- whether a PDF is the document its row says ---------------------------------

# Unconfirmed. Who a Raisin document says issued it. A deposit's documents
# may come from a partner bank instead, in which case every one is refused
# as unconfirmed until a tester's first run says what they print.
ISSUER_WORDS = ("raisin", "weltsparen")
GERMAN_MONTHS = ("Januar", "Februar", "März", "April", "Mai", "Juni", "Juli",
                 "August", "September", "Oktober", "November", "Dezember")
# Unconfirmed. How a document prints its own date, day first as German
# does, never month first, since 03.05.2026 is the third of May here.
DATE_FORMS = ("DD.MM.YYYY", "D.M.YYYY", "YYYY-MM-DD", "D. Monat YYYY", "DD. Monat YYYY")


def date_forms(iso: str) -> list:
    """Every way DATE_FORMS writes one ISO day, lowercased."""
    try:
        day = _date.fromisoformat(iso)
    except (TypeError, ValueError):
        return []
    month = GERMAN_MONTHS[day.month - 1]
    out = ["%02d.%02d.%04d" % (day.day, day.month, day.year),
           "%d.%d.%04d" % (day.day, day.month, day.year),
           day.isoformat(),
           "%d. %s %04d" % (day.day, month, day.year),
           "%02d. %s %04d" % (day.day, month, day.year)]
    if "ä" in month:
        out += [v.replace("ä", "ae") for v in out[3:5]]
    return list(dict.fromkeys(v.lower() for v in out))


def _shows_date(text_lower: str, iso: str) -> bool:
    return any(identity.on_its_own(v, text_lower) for v in date_forms(iso))


def _shows_words(text_lower: str, words: str) -> bool:
    words = re.sub(r"\s+", " ", (words or "").lower()).strip()
    if len(words) < 3:
        return False
    squashed = re.sub(r"\s+", "", text_lower)
    return words in text_lower or re.sub(r"\s+", "", words) in squashed


def _names_issuer(text_lower: str) -> bool:
    squashed = re.sub(r"\s+", "", text_lower)
    return any(re.search(r"(?<![a-z])" + w + r"(?![a-z])", text_lower) or
               re.search(r"(?<![a-z])" + w + r"(?![a-z])", squashed)
               for w in ISSUER_WORDS)


# What check_text answers, the reason a PDF was not placed, or "".
UNREADABLE = "unreadable"
UNCONFIRMED = "unconfirmed"
WRONG = "wrong"


def check_text(text: str, date: str, title: str, rivals=()) -> tuple:
    """(reason, found) for a PDF's text against its row, and its neighbors
    as (date, title) pairs (neighbors). reason is "" when
    the PDF names the issuer and prints its own date, and, when a
    neighbor shares that date, its own title too. found names the facts
    seen, never their values.

    Refuses rather than guesses. A PDF whose text cannot be read, that
    names no issuer, or that does not print its own date is unconfirmed,
    and one that prints a neighbor's date or title instead of its own is
    wrong."""
    low = (text or "").lower()
    if len(low.strip()) < identity.MIN_TEXT:
        return UNREADABLE, ()
    found = []
    issuer = _names_issuer(low)
    if issuer:
        found.append("issuer")
    own_date = _shows_date(low, date)
    if own_date:
        found.append("date")
    own_title = _shows_words(low, title)
    if own_title:
        found.append("title")
    others = [(d, t) for d, t in rivals or () if (d, t) != (date, title)]
    # Each kind of neighbor apart. A neighbor of another day is told apart
    # by the date, and one of the same day by the title.
    if not own_date:
        if any(_shows_date(low, d) for d, _t in others if d and d != date):
            return WRONG, tuple(found)
        return UNCONFIRMED, tuple(found)
    if not issuer:
        return UNCONFIRMED, tuple(found)
    same_day = [t for d, t in others if d == date and (t or "").lower() != title.lower()]
    if same_day:
        if not own_title:
            if any(_shows_words(low, t) for t in same_day):
                return WRONG, tuple(found)
            return UNCONFIRMED, tuple(found)
    return "", tuple(found)


def identity_for(doc) -> identity.Identity:
    """What delivery checks the bytes against. The title only, as a label.
    The row's date is never handed to the core's check, whose dotted form
    reads month first and would take 03.05.2026 for March 5. The day is
    checked here, day first, by check_text."""
    return identity.Identity(kind=str(getattr(doc, "document_type", "") or ""),
                             label=str(getattr(doc, "title", "") or ""))
