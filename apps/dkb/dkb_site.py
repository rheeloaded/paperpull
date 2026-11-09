"""ALL DKB (Deutsche Kreditbank) selectors, URLs, and page behavior live here.

When banking.dkb.de changes, repair this file only.

STATUS, scaffolded 2026-11-08 and the API mapped the same day from a
recording of the signed-in Postfach (the three calls below, their headers
and the shape of their answers). Run end to end the same day on the
contributor's own account, where Discover listed 1001 documents and 611
were saved.

  Sign-in is on banking.dkb.de, the web banking DKB moved every customer to
  in 2023, an Angular single-page app. The person signs in and confirms the
  login in the DKB app themselves. Every document the bank sends lands in
  the Postfach, which filters by six kinds: Kontoauszuege, Kreditkarten-
  abrechnungen, Wertpapierdokumente, Steuerbescheinigungen, Vertrags-
  informationen and Mitteilungen. The Postfach page fetches its list from
  the bank's own JSON:API. This app makes the same calls from inside the
  signed-in page, so the session cookies never leave the browser, and never
  presses a control on the page.

  THE API, cookie session, same origin as the page, every call with the
  headers the page sends: accept, application-name: web-banking, and
  x-xsrf-token, the value of the __Host-xsrf cookie.
    * list       GET /api/documentstorage/documents
                     ?page[limit]=200&page[offset]=N&sort=-creationDate
                 -> data[] of {id, attributes: {contentType, creationDate
                    (ISO timestamp, UTC), documentTypeId (a uuid, not a
                    name), fileName, metadata: {subject, statementDate
                    (YYYY-MM-DD, statements only), iban | depotNumber |
                    portfolio, ...}}}. links holds only self, no next, so
                    the offset is walked until a page comes back short.
    * messages   GET /api/documentstorage/messages
                 -> data[] of {id, attributes: {documentId, documentType,
                    subject, creationDate, read}}, one per document, all of
                    them in one answer. documentType is the readable kind
                    the Postfach filters by (bankAccountStatement,
                    dwpDepotStatement, taxCertification, ...), so it is
                    read for that and nothing else, and never marked read.
    * download   GET /api/documentstorage/documents/{id}
                 with accept: application/pdf -> the PDF.

  THE ARCHIVE, the Postfach's older documents (2017 to 2024 on the account
  this was mapped against, 739 of them, one of which is also in the
  Postfach), mapped from a recording on 2026-11-08:
    * folders    GET /api/documentstorage/folders
                 -> data[] of {id ("1", "2", ...), attributes: {name}}, one
                    folder per Postfach filter plus "Archiv", which holds
                    most of them of every kind.
    * a folder   GET /api/documentstorage/folders/{id}
                     ?page[limit]=200&page[offset]=N
                 -> data.attributes {name, subfolders[], files[] of {id,
                    subject, fileName, creationDate ("YYYY-MM-DDTHH:MMZ"),
                    additionalInformation (an IBAN on Kontoauszuege)}}.
                    Walked like the list, until a page comes back short.
    * a file     GET /api/documentstorage/legacy-documents/{id}
                 -> data.attributes {content (the PDF, base64),
                    contentType, fileName}.
  A folder named for a filter files its documents there. "Archiv" files
  each by its subject. A file also in the Postfach, the same day, the same
  subject and the same account where both name one, is taken from the
  Postfach only.

  WHOLE OR NOT AT ALL. The list is the Postfach, its messages, the folder
  list and every folder. Any of them that does not answer as a readable
  list raises ListStopped, so the listing is never called whole without
  it, and a run that reads it again while it downloads stops once with its
  list unread.

  NEVER sent: the PATCH on /messages/{id} that marks a message read, any
  call that archives or deletes one, and anything outside documentstorage.
  The one in-page request, _GET_JS, is a GET by its own code, and every
  address it is given is one of API's below.

  IDENTITY is kind + account + date + subject, never the id. The id is
  stored as a hint. A download numbers a recent listing as Discover did,
  the stored ids first (keys.told_apart), and takes a row only when that
  surely names the document (resolve_item).

SAFETY (this is a bank account, a credit card and a securities account):
  Strictly READ-ONLY. DKB can transfer money (Ueberweisung, Echtzeit-
  ueberweisung, Dauerauftrag, Lastschrift), buy and sell securities
  (Kauf, Verkauf, Sparplan, Order), change limits, lock cards and change
  personal data. This app never activates a control that does any of
  those, never submits a form, never confirms a dialog and never confirms
  anything in the DKB app. An expired session raises SessionExpired so a
  run stops loudly rather than reporting an empty success.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime as _dt
from pathlib import Path
from typing import List, Optional
import time as _time
from datetime import timedelta as _td, timezone as _tz
from urllib.parse import urljoin, urlsplit

from paperpull_core import intake
from paperpull_core.controls import SETTINGS_CONTROL_RE, AUTH_CONTROL_RE
from paperpull_core.controls import escape_for_locator

# Everything on its way into a diagnostic file goes through here.
from paperpull_core.redact import redact, set_private_words  # noqa: F401
from paperpull_core.urls import is_safe_url as _host_allows
from paperpull_core.api_census import shape_of as _shape
from paperpull_core.dates import checked as _checked_date

log = logging.getLogger("dkb_docs.site")

# Every host this app will read from. Anything else is refused.
ALLOWED_HOSTS = ("dkb.de",)

BASE = "https://banking.dkb.de"
URLS = {
    "home": f"{BASE}/finanzstatus",
    "login": f"{BASE}/login",
    # The Postfach page, confirmed 2026-11-08. Any signed-in page on
    # banking.dkb.de serves the API, this is the one a person expects.
    "documents": f"{BASE}/postbox",
}
API = {
    "folders": f"{BASE}/api/documentstorage/folders",
    "legacy": f"{BASE}/api/documentstorage/legacy-documents/",
    "documents": f"{BASE}/api/documentstorage/documents",
    "messages": f"{BASE}/api/documentstorage/messages",
    "document": f"{BASE}/api/documentstorage/documents/",
}
PAGE_LIMIT = 200         # what the Postfach itself asks for
MAX_PAGES = 50           # 10,000 documents, far beyond the ten years DKB keeps
# The page's own app identity. Not a credential, the same for every customer.
APP_HEADERS = {"application-name": "web-banking"}

# The categories this app files by, one for each filter the Postfach offers:
# Kontoauszuege, Kreditkartenabrechnungen, Wertpapierdokumente, Steuer-
# bescheinigungen, Vertragsinformationen and Mitteilungen. The core knows
# "Statement" and "Tax Document". The folders they file into carry the
# Postfach's German names (storage.py).
ACCOUNT = "Statement"
CARD = "Credit Card Statement"
SECURITIES = "Securities Document"
TAX = "Tax Document"
CONTRACT = "Contract Information"
MESSAGE = "Message"
OTHER = "Other Document"
ALL_CATEGORIES = [ACCOUNT, CARD, SECURITIES, TAX, CONTRACT, MESSAGE]

# The Postfach's own documentType names, as the messages call gives them,
# and the filter each one is listed under. Seen in a recording on
# 2026-11-08, except creditCardStatement, which that account had none of.
DOCUMENT_TYPES = {
    "bankAccountStatement": ACCOUNT,
    "creditCardStatement": CARD,
    "dwpOrderStatement": SECURITIES,
    "dwpRevenueStatement": SECURITIES,
    "dwpDepotStatement": SECURITIES,
    "dwpCorporateActionNotice": SECURITIES,
    "exAnteCostInformation": SECURITIES,
    "taxCertification": TAX,
    "stageDocumentContract": CONTRACT,
    "stageDocumentMessage": MESSAGE,
}

# The archive's folders, by the name DKB gives them, and the filter each
# one is. "Archiv" holds every kind and is sorted by subject instead.
ARCHIVE_FOLDERS = {
    "kontoauszüge": ACCOUNT,
    "kreditkartenabrechnungen": CARD,
    "wertpapierdokumente": SECURITIES,
    "steuerbescheinigungen": TAX,
    "vertragsinformationen": CONTRACT,
    "mitteilungen": MESSAGE,
    "gehaltsabrechnungen": OTHER,
}
LEGACY = "legacy"          # client_id of an archive row, so the download asks the archive

# A documentType not in that table falls back to these, each category
# with the words its documentType, subject or file name carries. Checked in order, the first that matches wins: a Steuer-
# bescheinigung for the depot is a tax document, a Kreditkartenabrechnung
# is not a Kontoauszug, and a Wertpapierabrechnung is not a statement.
# The documentType values are UNVERIFIED and are matched loosely, both
# the API's English names and the Postfach's German ones.
_KIND_RULES = [
    (TAX, re.compile(r"tax|steuer|freistellung|verlustbescheinigung|"
                     r"jahresbescheinigung|ertr(ae|ä)gnis", re.I)),
    (CARD, re.compile(r"credit\s*card|creditcard|kreditkarte|\bvisa\b", re.I)),
    (SECURITIES, re.compile(r"depot|securit|wertpapier|broker|ertragsabrechnung|"
                            r"dividend|aussch(ue|ü)ttung|\b(wertpapier)?(kauf|verkauf)\b|"
                            r"sparplan|kapitalma(ss|ß)nahme|hauptversammlung|"
                            r"kosteninformation|ex-?ante|ex-?post|fonds", re.I)),
    (ACCOUNT, re.compile(r"bank\s*account|bankaccount|account\s*statement|"
                         r"kontoauszug|girokonto|tagesgeld|rechnungsabschluss", re.I)),
    (CONTRACT, re.compile(r"contract|vertrag|bedingungen|preis-?\s*und\s*leistung|"
                          r"vereinbarung|kontoer(oe|ö)ffnung|terms", re.I)),
    (MESSAGE, re.compile(r"message|mitteilung|information|notice|schreiben|brief", re.I)),
]

# /timeout is where DKB sends a tab it signed out for inactivity.
LOGIN_URL_MARKERS = ["/login", "/logout", "/timeout", "/anmeldung", "/abmeldung", "/session-expired"]


class SessionExpired(RuntimeError):
    """DKB answered with a sign-in page or a 401 instead of the thing asked for."""


class NoFile(RuntimeError):
    """DKB lists a document and its description but has no PDF behind it.
    Seen 2026-11-08 on one Wertpapierabrechnung of two the same day, the
    other of which downloaded."""


class ListStopped(Exception):
    """A part of the list did not answer in a way this app can read whole.
    The parts are the Postfach, its messages, the archive's folder list and
    each archive folder. A part read as empty or cut short would leave its
    documents out of a list called whole, and a missing messages answer
    would file every document by its words and so change its key. So any
    of them stops the listing, and a run that reads the list again while it
    downloads stops once with the list unread (listing.read_again_stopped)."""


class NotToldApart(Exception):
    """A fresh listing does not say which row is this document, so nothing
    is fetched for it. The run's loop fails that document and goes on."""


def _error_code(res: dict) -> str:
    errors = (res.get("json") or {}).get("errors") or [{}]
    return str((errors[0] or {}).get("code") or "")


def is_safe_url(url: str) -> bool:
    """True only for an https URL on one of this provider's own hosts."""
    return _host_allows(url, ALLOWED_HOSTS)


# ---------------------------------------------------------------------------
# HARD SAFETY GUARD. Tuned for a German bank with a card and a depot. Never
# move money, never trade, never change a limit, a card or a setting.
# English words stay in, since parts of the page and its labels are English.
# ---------------------------------------------------------------------------
FORBIDDEN_CONTROL_RE = re.compile(
    # Money moving, German
    r"((ue|ü)berweis|\bechtzeit|dauerauftr|lastschrift|\bumbuch|\bsenden\b|"
    r"\bzahl(en|ung)\b|\bbezahl|geld\s+(senden|anfordern)|\bauszahl|\beinzahl|"
    r"\bvorlage|\bempf(ae|ä)nger|\bzur(ue|ü)ckbuch|widersprech|widerspruch|"
    # Trading, German
    # Kaufen and Verkaufen are what a trade button says. "Kauf" alone is in
    # the name of every Wertpapierabrechnung, so only a label that is
    # nothing but that word is refused.
    r"\bkaufen\b|\bverkaufen\b|^\s*(ver)?kauf\s*$|\border\b|\bsparplan\s+(anlegen|einrichten|(ae|ä)ndern)|"
    r"\bhandel|\bzeichn|"
    r"\blimit|\bstop\b|\bkurs\s*alarm|"
    # Cards and accounts, German
    r"\bsperr|entsperr|\bpin\b|\bk(ue|ü)ndig|\ber(oe|ö)ffn|\bbeantrag|\bantrag\b|"
    r"\bkredit\b|dispo|\bfreigeb|\bfreigabe|\bbest(ae|ä)tig|\bzustimm|\bakzeptier|"
    r"\b(ae|ä)nder|\bbearbeit|\bl(oe|ö)sch|\bentfern|\barchivier|\beinricht|"
    r"\baktivier|deaktivier|\babschlie(ss|ß)|"
    r"als\s+gelesen|gelesen\s+markier|"
    r"\babmeld|\bpasswort|\bkennwort|\bger(ae|ä)t|\badresse\b|\be-?mail\b|"
    r"\btelefon|\bhandynummer|\bpersönliche\s+daten|\bpersoenliche\s+daten|"
    # Money moving and trading, English
    r"transfer\b|\bwire\b|\bpay\b|payment|\bbuy\b|\bsell\b|\btrade\b|"
    # Word boundaries on both sides of the verb stems, so "Credit" and
    # "Exchange" stay allowed.
    r"\bchang(e|es|ed|ing)\b|\bedit(s|ed|ing)?\b|\bupdat(e|es|ed|ing)\b|"
    r"\bdelet|\bremov(e|es|ed|ing|al)\b|\bsubmit|\bconfirm\b|\baccept\b|"
    r"\bmark\s+as\s+read\b|\barchive\b|log\s*out|logout|sign\s*out)",
    re.I)

# What a document control may look like. A control must match this AND not
# match the blocklist.
SAFE_DOC_CONTROL_RE = re.compile(
    r"(herunterladen|download|\bpdf\b|\banzeigen\b|(oe|ö)ffnen|\bview\b|\bopen\b|"
    r"postfach|dokument|kontoauszug|ausz(ue|ü)ge|abrechnung|depotauszug|"
    r"steuerbescheinigung|mitteilung|statement|document)", re.I)


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
    r"^(postfach|dokumente|kontoausz(ue|ü)ge|depotausz(ue|ü)ge|"
    r"steuerbescheinigungen?|mitteilungen|documents?|mailbox)$", re.I)


SECURITY_CHALLENGE_MARKERS = [
    # German
    # The phrases of a prompt, never a bare product name: "DKB-App" is on
    # ordinary pages (the card settings name it), and stopped a run.
    "bestätige deine anmeldung", "in der dkb-app bestätigen", "in deiner dkb-app",
    "freigabe in der dkb-app", "tan eingeben", "chiptan", "sicherheitscode", "bestätigungscode",
    "zu viele versuche", "sitzung ist abgelaufen", "sitzung abgelaufen",
    "du wurdest abgemeldet", "sie wurden abgemeldet",
    # English
    "verification code", "captcha", "access denied", "your session has expired",
]

RATE_LIMIT_MARKERS = ["zu viele anfragen", "später erneut", "too many requests",
                      "rate limit", "try again later", "temporarily unavailable"]


def looks_signed_out(page) -> bool:
    try:
        url = (page.url or "").lower()
    except Exception:
        # A page that cannot say where it is is not a signed-in page.
        return True
    if any(m in url for m in LOGIN_URL_MARKERS):
        return True
    try:
        if page.locator("input[type='password']").count() > 0:
            return True
    except Exception:
        pass
    return False


def detect_security_challenge(page) -> Optional[str]:
    """Names the confirmation, CAPTCHA or throttling prompt on screen, or
    None. Visible text only. A sign-in page is not one: DKB's carries a
    "Friendly Captcha" widget, and a tab signed out for inactivity was
    reported as a challenge rather than as signed out."""
    if looks_signed_out(page):
        return None
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
    """A signed-in banking.dkb.de page. The API is same-origin, so any of
    them serves it."""
    try:
        url = page.url or ""
        return (is_safe_url(url) and url.startswith(BASE)
                and not looks_signed_out(page))
    except Exception:
        return False


def goto_documents(page) -> bool:
    if on_documents_page(page) and "/postbox" in (page.url or ""):
        return True
    if URLS["documents"] and is_safe_url(URLS["documents"]):
        try:
            page.goto(URLS["documents"], wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(2500)
        except Exception as e:
            log.info("documents URL failed: %s", e)
    return on_documents_page(page)


def ensure_statements(page) -> bool:
    return goto_documents(page)


# DKB signs a tab out about six minutes after a person's last input. The
# count lives in the page and survives a reload, and the calls this app makes
# are no input. That is the bank's own check that someone is there, and this
# app does not work around it: nothing renews the session, nothing reloads
# the page to keep it, nothing answers the "Banking weiter nutzen?" prompt.
# Tried on 2026-11-08 and taken out again: a reload every three minutes,
# and the page's own POST /api/refresh every four, with and without a
# reload after it. Neither kept the tab signed in. A run stops at /timeout
# as signed out, the person signs in again, and Resume carries on.


# -- dates ----------------------------------------------------------------------

def _parse_date_from_page(text: str) -> str:
    """'2026-02-09', '2026-02-09T10:00:00Z' or '09.02.2026' -> '2026-02-09', else ''."""
    s = (text or "").strip()
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})(?!\d)", s)
    if m:
        return s[:10]
    m = re.match(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})$", s)
    if m:
        return "%s-%02d-%02d" % (m.group(3), int(m.group(2)), int(m.group(1)))
    return ""


def _last_sunday(year: int, month: int) -> int:
    day = 31
    while _dt(year, month, day).weekday() != 6:
        day -= 1
    return day


def _berlin(when):
    """A moment in Berlin time, by the EU rule: summer time from 01:00 UTC
    on the last Sunday of March to 01:00 UTC on the last Sunday of October.
    Worked out here because Windows' Python has no time zone data without
    an extra package."""
    u = when.astimezone(_tz.utc)
    start = _dt(u.year, 3, _last_sunday(u.year, 3), 1, tzinfo=_tz.utc)
    end = _dt(u.year, 10, _last_sunday(u.year, 10), 1, tzinfo=_tz.utc)
    return u + _td(hours=2 if start <= u < end else 1)


def local_date(text: str) -> str:
    """A day as DKB means it. A creationDate is a UTC timestamp, and one
    made late in the evening is the next day in UTC, so a timestamp is read
    in Berlin time. A plain day is taken as it is."""
    s = (text or "").strip()
    m = re.match(r"^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}(?::\d{2})?)(\.\d+)?(Z|[+-]\d{2}:?\d{2})$", s)
    if m:
        try:
            when = _dt.fromisoformat(m.group(1) + "T" + m.group(2)
                                     + ("+00:00" if m.group(4) == "Z" else m.group(4)))
            return _checked_date(_berlin(when).strftime("%Y-%m-%d"), "")
        except ValueError:
            return ""
    return parse_date(s)


def parse_date(text):
    """The date this provider shows, as YYYY-MM-DD, or '' when it names a
    day that does not exist."""
    return _checked_date(_parse_date_from_page(text), "")


# -- the API, from inside the page --------------------------------------------

# Runs inside the page. One GET with the session cookies the browser already
# holds and the page's own xsrf header. JSON comes back parsed, anything
# else as base64. Nothing about the session enters this process.
_GET_JS = r"""async ({url, accept, headers}) => {
  const target = new URL(url, location.href);
  const host = target.hostname;
  if (target.protocol !== 'https:' || !(host === 'dkb.de' || host.endsWith('.dkb.de'))) {
    throw new Error('Refusing an off-host request');
  }
  const h = Object.assign({'Accept': accept}, headers);
  const m = document.cookie.match(/(?:^|;\s*)__Host-xsrf=([^;]+)/);
  if (m) h['x-xsrf-token'] = decodeURIComponent(m[1]);
  const r = await fetch(target.href, {method: 'GET', credentials: 'include',
                                      headers: h, redirect: 'error'});
  const ct = r.headers.get('content-type') || '';
  const buf = await ppRead(r);
  if (ct.includes('json')) {
    let j = null;
    try { j = JSON.parse(new TextDecoder().decode(buf)); } catch (e) {}
    return {status: r.status, ct, json: j};
  }
  let s = '';
  for (let i = 0; i < buf.length; i += 0x8000) s += String.fromCharCode.apply(null, buf.subarray(i, i + 0x8000));
  return {status: r.status, ct, b64: btoa(s)};
}"""


def _get(page, url: str, accept: str = "application/vnd.api+json, application/json") -> dict:
    if not is_safe_url(url):
        raise ValueError("refusing an off-host request")
    if not is_safe_url(page.url or "") or looks_signed_out(page):
        raise SessionExpired("the DKB tab is not on a signed-in banking.dkb.de page")
    res = intake.evaluate(page, _GET_JS, {"url": url, "accept": accept,
                                          "headers": dict(APP_HEADERS)})
    status = res.get("status")
    ct = (res.get("ct") or "").lower()
    if isinstance(status, int) and status >= 500:
        # Not a signed-out answer. Seen 2026-11-08 on some archive files,
        # a 500 as an HTML page while the files beside them came back. The
        # run carries on, and Resume asks for the document again.
        raise RuntimeError("DKB answered %s, a fault on DKB's side, for %s"
                           % (status, url.split("?")[0].rsplit("/", 1)[-1]))
    if status in (401, 403) or ct.startswith("text/html"):
        raise SessionExpired("DKB answered %s" % status)
    if status == 404 and _error_code(res) == "UnknownDocument":
        raise NoFile("DKB lists this document but holds no file for it (UnknownDocument). "
                     "Try opening it in the Postfach. If it does not open there either, "
                     "only DKB can fix it. Resume asks for it again.")
    if status != 200:
        raise RuntimeError("DKB answered %s for %s" % (status, url.split("?")[0].rsplit("/", 1)[-1]))
    return res


def _list_answer(page, url: str, what: str) -> dict:
    """One answer of a part of the list, its JSON. A signed-out answer stops
    the run as one. Anything else that is not a readable JSON answer stops
    the listing (ListStopped), since an answer read as empty ends a part
    of the list as if nothing more were in it."""
    try:
        res = _get(page, url)
    except SessionExpired:
        raise
    except Exception as e:
        raise ListStopped("%s could not be read (%s)" % (what, e)) from None
    j = res.get("json")
    if not isinstance(j, dict):
        raise ListStopped("%s did not answer with JSON" % what)
    return j


def _data_list(j: dict, what: str) -> List[dict]:
    """data[] of one JSON:API answer, each entry an object, or ListStopped."""
    data = j.get("data")
    if not isinstance(data, list) or not all(isinstance(d, dict) for d in data):
        raise ListStopped("%s holds no list this app can read" % what)
    return data


def _new_of(items: List[dict], seen: set, what: str) -> List[dict]:
    """The entries of one full or short page not given before. An id given
    again is the same document, so it is kept once. A full page that gives
    nothing new is a page asked for again, and reading on would only ask
    for it again, so the part stops there (ListStopped)."""
    fresh = []
    for d in items:
        ident = str(d.get("id") or "")
        if ident and ident in seen:
            continue
        if ident:
            seen.add(ident)
        fresh.append(d)
    if items and len(items) >= PAGE_LIMIT and not fresh:
        raise ListStopped("%s gave a page it had given already" % what)
    return fresh


def _documents_url(n: int) -> str:
    return (API["documents"] + "?page%%5Blimit%%5D=%d&page%%5Boffset%%5D=%d&sort=-creationDate"
            % (PAGE_LIMIT, n * PAGE_LIMIT))


def answers_its_list(page) -> bool:
    """True when DKB answers this tab's first page of the Postfach list as
    a list. That is what proves a session, never a page without a sign-in
    form. Raises SessionExpired for a signed-out answer and ListStopped for
    one that is not the list."""
    _data_list(_list_answer(page, _documents_url(0), "the Postfach list"), "the Postfach list")
    return True


def list_documents(page) -> List[dict]:
    """Every document, newest first, one page of PAGE_LIMIT at a time. The
    answer has no next link, so a page that comes back short is the last."""
    out: List[dict] = []
    seen: set = set()
    for n in range(MAX_PAGES):
        url = _documents_url(n)
        items = _data_list(_list_answer(page, url, "the Postfach list"), "the Postfach list")
        out.extend(_new_of(items, seen, "the Postfach list"))
        if len(items) < PAGE_LIMIT:
            return out
    raise ListStopped("the Postfach list ran past %d pages" % MAX_PAGES)


def _messages_next(j: dict, asked: set) -> str:
    """The address of the next page of messages, or "" at the last. Only the
    messages call itself on banking.dkb.de is followed. Any other next link,
    or one asked for already, stops the listing rather than end it early."""
    links = j.get("links")
    nxt = links.get("next") if isinstance(links, dict) else None
    if not nxt:
        return ""
    nxt = urljoin(BASE + "/", str(nxt))
    parts = urlsplit(nxt)
    if (not is_safe_url(nxt) or parts.netloc != urlsplit(BASE).netloc
            or parts.path != urlsplit(API["messages"]).path or nxt in asked):
        raise ListStopped("the Postfach messages gave a next page this app does not follow")
    return nxt


def list_messages(page) -> dict:
    """document id -> the message's attributes. Only read, never marked read.
    The messages say which kind each document is, so a messages answer that
    cannot be read whole stops the listing (ListStopped)."""
    out: dict = {}
    url = API["messages"]
    asked: set = set()
    for _ in range(MAX_PAGES):
        asked.add(url)
        j = _list_answer(page, url, "the Postfach messages")
        for m in _data_list(j, "the Postfach messages"):
            a = m.get("attributes") or {}
            if not isinstance(a, dict):
                raise ListStopped("a Postfach message could not be read")
            out[str(a.get("documentId") or m.get("id"))] = a
        url = _messages_next(j, asked)
        if not url:
            return out
    raise ListStopped("the Postfach messages ran past %d pages" % MAX_PAGES)


def _first(d: dict, *keys):
    for k in keys:
        v = d.get(k)
        if v not in (None, ""):
            return v
    return ""


def classify(*texts: str) -> str:
    """The Postfach filter a document is listed under. The documentType
    name when it is a known one, the words otherwise."""
    for t in texts:
        if t in DOCUMENT_TYPES:
            return DOCUMENT_TYPES[t]
    hay = " ".join(t for t in texts if t)
    for category, rx in _KIND_RULES:
        if rx.search(hay):
            return category
    return OTHER


def account_label(meta: dict) -> str:
    """The last four of the IBAN, depot or card number, never the whole one."""
    num = str(_first(meta, "iban", "depotNumber", "depotId", "cardId", "maskedPan",
                     "accountNumber", "portfolio", "portfolioId") or "")
    num = re.sub(r"\s+", "", num)
    # Only a number is an account. The portfolio field can hold a word
    # ("DKB"), which named a file "Mitteilung - Dkb".
    return num[-4:] if re.search(r"\d{4}$", num) else ""


def _row(d: dict, messages: dict) -> Optional[dict]:
    a = d.get("attributes") or {}
    meta = a.get("metadata") or {}
    msg = messages.get(str(d.get("id"))) or {}
    ct = str(a.get("contentType") or "application/pdf")
    if "pdf" not in ct.lower():
        return None
    raw_date = str(_first(meta, "statementDate", "date", "documentDate")
                   or _first(a, "creationDate", "date") or _first(msg, "documentDate", "creationDate"))
    date = local_date(raw_date)
    if not date:
        return None
    doc_type = str(_first(a, "documentType") or _first(msg, "documentType"))
    title = str(_first(meta, "subject") or _first(msg, "subject") or a.get("fileName") or doc_type
                or "Dokument")
    title = re.sub(r"\s+", " ", re.sub(r"\.pdf$", "", title, flags=re.I)).strip()
    return {
        "title": title, "date": date, "account": account_label(meta),
        "category": classify(doc_type, title, str(a.get("fileName") or "")),
        "item_id": str(d.get("id") or ""), "client_id": ct,
        "period_start": "", "href": API["document"],
    }


def list_folders(page) -> List[tuple]:
    """(id, name) of every archive folder. A folder whose id cannot be read
    would go unread, so it stops the listing instead (ListStopped)."""
    j = _list_answer(page, API["folders"], "the archive's folder list")
    out = []
    for f in _data_list(j, "the archive's folder list"):
        fid = str(f.get("id") or "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", fid):
            raise ListStopped("an archive folder carries an id this app cannot read")
        attrs = f.get("attributes")
        out.append((fid, str((attrs.get("name") if isinstance(attrs, dict) else "") or "")))
    return out


def list_folder(page, folder_id: str) -> List[dict]:
    """Every file in one archive folder, a page of PAGE_LIMIT at a time."""
    out: List[dict] = []
    seen: set = set()
    what = "the archive folder %s" % folder_id
    for n in range(MAX_PAGES):
        url = (API["folders"] + "/%s?page%%5Blimit%%5D=%d&page%%5Boffset%%5D=%d"
               % (folder_id, PAGE_LIMIT, n * PAGE_LIMIT))
        data = _list_answer(page, url, what).get("data")
        attrs = data.get("attributes") if isinstance(data, dict) else None
        files = attrs.get("files") if isinstance(attrs, dict) else None
        if not isinstance(files, list) or not all(isinstance(f, dict) for f in files):
            raise ListStopped("%s holds no list of files this app can read" % what)
        out.extend(_new_of(files, seen, what))
        if len(files) < PAGE_LIMIT:
            return out
    raise ListStopped("%s ran past %d pages" % (what, MAX_PAGES))


_ARCHIVE_ACCOUNT_RE = re.compile(
    r"\b(?:konto|depot)\s*(?:nr\.?\s*)?(\d{4,})\b|\d{4}\*{4,}(\d{4})\b", re.I)


def _archive_account(f: dict) -> str:
    """The last four of the IBAN the archive gives a Kontoauszug, or of the
    account, depot or masked card number its subject names, else ''."""
    extra = re.sub(r"\s+", "", str(f.get("additionalInformation") or ""))
    if re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{8,30}", extra):
        return extra[-4:]
    m = _ARCHIVE_ACCOUNT_RE.search(str(f.get("subject") or ""))
    if m:
        return (m.group(1) or m.group(2))[-4:]
    return ""


def _archive_row(f: dict, folder_name: str) -> Optional[dict]:
    fid = str(f.get("id") or "")
    name = str(f.get("fileName") or "")
    if not fid or (name and not name.lower().endswith(".pdf")):
        return None
    date = local_date(str(f.get("creationDate") or ""))
    if not date:
        return None
    title = re.sub(r"\s+", " ", str(f.get("subject") or "") or re.sub(r"\.pdf$", "", name, flags=re.I)).strip()
    category = ARCHIVE_FOLDERS.get(folder_name.strip().lower()) or classify(title, name)
    return {
        "title": title or "Dokument", "date": date, "account": _archive_account(f),
        "category": category, "item_id": fid, "client_id": LEGACY,
        "period_start": "", "href": API["legacy"],
    }


def collect_archive(page) -> List[dict]:
    rows: List[dict] = []
    for fid, name in list_folders(page):
        files = list_folder(page, fid)
        log.info("Archiv %s: %d", name or fid, len(files))
        rows.extend(r for r in (_archive_row(f, name) for f in files) if r)
    return rows


# One listing serves a run's downloads for a while, rather than the whole
# Postfach and archive being asked for again before every document.
LISTING_SECONDS = 600
_listing: dict = {}


def _in_the_postfach(postfach: List[dict]):
    """Whether an archive row is a file the Postfach lists too: the same
    day, the same subject, and the same account where both name one. Two
    accounts' documents of one day and subject are two documents."""
    accounts: dict = {}
    for r in postfach:
        accounts.setdefault((r["date"], r["title"]), set()).add(r["account"])

    def held(r: dict) -> bool:
        there = accounts.get((r["date"], r["title"]))
        if not there:
            return False
        return not r["account"] or "" in there or r["account"] in there
    return held


def _all_rows(page, fresh: bool = False) -> List[dict]:
    """The Postfach and the archive, read whole or not at all. A part that
    cannot be read raises ListStopped (or SessionExpired), so no listing
    missing a part is ever kept or called whole."""
    now = _time.monotonic()
    if not fresh and _listing.get("rows") is not None and now - _listing.get("at", 0) < LISTING_SECONDS:
        return _listing["rows"]
    messages = list_messages(page)
    rows = [r for r in (_row(d, messages) for d in list_documents(page)) if r]
    archive = collect_archive(page)
    # A file in both places is taken from the Postfach.
    held = _in_the_postfach(rows)
    rows += [r for r in archive if not held(r)]
    _listing.update(rows=rows, at=now)
    return rows


def _wanted(config: Optional[dict]) -> set:
    return set((config or {}).get("document_types") or ALL_CATEGORIES) | {OTHER}


def listed_rows(page, config: Optional[dict] = None, fresh: bool = False) -> List[dict]:
    """The rows of the kinds document_types keeps, in the listing's order.
    Discover numbers these, and so does each download's look at a recent
    listing, so the two agree on which row is which document."""
    wanted = _wanted(config)
    return [r for r in _all_rows(page, fresh=fresh) if r["category"] in wanted]


def collect_documents(page, keep=None, config: Optional[dict] = None) -> List[dict]:
    """Every PDF in the Postfach and its archive, newest first. `keep` is the
    run's scope predicate over year labels. Which kinds are kept follows
    document_types in the config."""
    rows = [r for r in listed_rows(page, config, fresh=True)
            if keep is None or keep(r["date"][:4])]
    rows.sort(key=lambda r: r["date"], reverse=True)
    log.info("Postfach and archive: %d PDF(s)", len(rows))
    return rows


def resolve_item(page, title: str, date: str, account: str, occurrence: int = 0,
                 item_id: str = "", *, number_rows, twins: int = 1,
                 config: Optional[dict] = None) -> Optional[dict]:
    """The document's own row of a recent listing, or None when the listing
    no longer shows it.

    `number_rows` numbers the listing as Discover numbered it, the stored
    ids first, so a row answers to `occurrence` and no two documents can
    come to one row. A place among the rows alike says nothing once the
    list comes back in another order. A row found by its number and not by
    `item_id` is taken only when the listing shows as many documents alike
    as the app knows (`twins`). Anything less raises NotToldApart rather
    than guess."""
    rows = listed_rows(page, config)
    numbers = number_rows(rows)
    alike = [i for i, r in enumerate(rows)
             if r["title"] == title and r["date"] == date and r["account"] == account]
    mine = [i for i in alike if numbers[i][0] == occurrence]
    if not mine:
        # The stored id is left as the way to it, unless another document
        # holds that row now.
        if item_id and any(r["item_id"] == item_id for r in rows):
            raise NotToldApart("Its stored id is now another document's")
        return None
    row, sure = rows[mine[0]], numbers[mine[0]][1]
    if sum(r["item_id"] == row["item_id"] for r in rows) > 1:
        raise NotToldApart("Two rows of the list carry its id")
    if not sure or (row["item_id"] != item_id and len(alike) != twins):
        raise NotToldApart("The list does not say which of the documents alike this is")
    return row


def _checked_id(item_id: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", item_id or ""):
        raise ValueError("refusing a document id that is not one")
    return item_id


def fetch_pdf(page, item_id: str, content_type: str = "application/pdf") -> bytes:
    """The PDF bytes for one document, through the page. An archive file
    comes back as base64 inside JSON, a Postfach document as the PDF."""
    if content_type == LEGACY:
        res = _get(page, API["legacy"] + _checked_id(item_id))
        content = ((((res.get("json") or {}).get("data") or {}).get("attributes")) or {}).get("content")
        b64 = content or ""
    else:
        res = _get(page, API["document"] + _checked_id(item_id), accept=content_type or "application/pdf")
        b64 = res.get("b64") or ""
    if not b64:
        return b""
    try:
        return intake.decode(b64, validate=True)
    except intake.TooLarge:
        return b""


def download_document(page, title: str, date: str, out_path: Path, occurrence: int = 0,
                      item_hint: str = "", client_hint: str = "", account: str = "", *,
                      number_rows, twins: int = 1, config: Optional[dict] = None) -> str:
    """Save one document, and answer the id its bytes came from, or "" when
    nothing was saved. Looks it up again by title, account and date first,
    and falls back to the stored id only when the listing no longer shows
    it. Which row is its own is resolve_item's to say, and it raises
    NotToldApart when that cannot be told."""
    found = resolve_item(page, title, date, account, occurrence, item_id=item_hint,
                         number_rows=number_rows, twins=twins, config=config)
    item_id = (found or {}).get("item_id") or item_hint
    ct = (found or {}).get("client_id") or client_hint or "application/pdf"
    if not item_id:
        log.warning("no id for %s %s", title, date)
        return ""
    data = fetch_pdf(page, item_id, ct)
    if not data.startswith(b"%PDF"):
        log.warning("not a PDF for %s %s (%d bytes)", title, date, len(data))
        return ""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(data)
    return item_id


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
    """What the signed-in DKB banking looks like, without downloading anything.

    Records the page, its headings and controls with the guard's verdict on
    each, and every JSON response banking.dkb.de sends while the page
    settles. Then follows, one at a time and back again, the few links whose
    text is exactly a document word. Bodies are recorded as shape only,
    never values, and any run of six digits is masked. No screenshot, a
    bank page shows balances."""
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
                    body = intake.json_of(res)
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
                    "^" + escape_for_locator(c["text"].replace("#", "")) + "$", re.I)).first
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
