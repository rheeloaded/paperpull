"""ING (ING-DiBa) page behavior.

Read-only reader of the signed-in Postbox, tested on one account. It reads the
rows the Postbox page shows, the same rows the account holder sees there,
and fetches each PDF from inside that page with the browser's own session.
It presses nothing: no filter, no menu, no further page, no button. A page
it does not recognize stops the list rather than being guessed at.

The addresses and selectors were first taken from public descriptions of
the ING Postbox, then checked on the contributor's own account. A run may
stop where another account's page differs. Diagnose and Record help map
the difference.

It never moves money, trades, changes settings, submits forms or confirms
dialogs. A row the Postbox marks unread is downloaded too unless
include_unread is false, and whether fetching a document marks it read in
ING has not been checked. Record observes the account holder's own
actions, and Diagnose is passive.
"""
from __future__ import annotations

import hashlib
import logging
import re
import secrets
import time as _time
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import unquote, urlsplit

from paperpull_core import intake
from paperpull_core.controls import SETTINGS_CONTROL_RE, AUTH_CONTROL_RE
# Everything on its way into a diagnostic file goes through here.
from paperpull_core.redact import redact, set_private_words  # noqa: F401
from paperpull_core.urls import is_safe_url as _host_allows
from paperpull_core.api_census import shape_of as _shape
from paperpull_core.dates import checked as _checked_date
from paperpull_core.words import Fixed

log = logging.getLogger("ing_docs.site")

# Every host this app will read from. Anything else is refused. Only the
# banking host itself: ING's sign-in and public pages live on other ing.de
# hosts, and a tab on one of those is not a signed-in banking page.
ALLOWED_HOSTS = ("banking.ing.de",)

BASE = "https://banking.ing.de"
# The one host a list or a document is read from.
HOST = "banking.ing.de"
URLS = {
    "home": f"{BASE}/app/obligo",
    "login": f"{BASE}/app/obligo",
    # The Postbox and its archive, as public descriptions of the page name
    # them and the contributor's own account showed them.
    "documents": f"{BASE}/app/postbox/postbox",
    "archive": f"{BASE}/app/postbox/postbox_archiv",
}

# The parts of the page this app looks for, named in a failure report.
FALLBACK = {
    "doc_row": ".ibbr-table-row",
    "doc_link": ".ibbr-table-row a[href]",
    "page_ready": ".ibbr-table-wrapper-postbox, .ibbr-table-body",
}

# The categories a row is filed under. Not every ING document type has been
# checked, so a row's category is read from its words (_KIND_RULES).
ACCOUNT = "Statement"
CARD = "Credit Card Statement"
SECURITIES = "Securities Document"
TAX = "Tax Document"
CONTRACT = "Contract Information"
MESSAGE = "Message"
OTHER = "Other Document"
ALL_CATEGORIES = [ACCOUNT, CARD, SECURITIES, TAX, CONTRACT, MESSAGE]

# A row's category, from the words of its document type and its subject
# (classify). Checked in order, the first that matches wins: a Steuer-
# bescheinigung for the depot is a tax document, a Kreditkartenabrechnung
# is not a Kontoauszug, and a Wertpapierabrechnung is not a statement.
# The words are matched loosely, in German and English. Not all ING document
# types have been checked.


_KIND_RULES = [
    (TAX, re.compile(r"tax|steuer|freistellung|verlustbescheinigung|"
                     r"jahresbescheinigung|\bertr(ae|ä)gnis", re.I)),
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


# Common sign-out paths to reject. ING's expiry behavior is not mapped.
LOGIN_URL_MARKERS = ["/login", "/logout", "/timeout", "/anmeldung", "/abmeldung", "/session-expired"]


class SessionExpired(RuntimeError):
    """ING answered with a sign-in page or a 401 instead of the thing asked for."""


class ListStopped(Exception):
    """The Postbox shows something this app does not read whole, so what it
    read is not called the whole list."""


class NotToldApart(Exception):
    """A fresh listing does not say which row is this document, so nothing
    is fetched for it. The run's loop fails that document and goes on."""


class FetchFailed(RuntimeError):
    """The browser did not finish fetching a document: the connection
    failed, or the link led on to another host, which a same-origin fetch
    does not follow. The document fails, and the run goes on."""


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
    r"postfach|postbox|dokument|kontoauszug|ausz(ue|ü)ge|abrechnung|depotauszug|"
    r"steuerbescheinigung|mitteilung|statement|document)", re.I)


def is_safe_control(name: str) -> bool:
    name = (name or "").strip()
    if not name:
        return False
    if (FORBIDDEN_CONTROL_RE.search(name) or SETTINGS_CONTROL_RE.search(name)
            or AUTH_CONTROL_RE.search(name)):
        return False
    return bool(SAFE_DOC_CONTROL_RE.search(name))


# Document navigation labels highlighted by the passive survey.
SURVEY_LINK_RE = re.compile(
    r"^(postfach|postbox|dokumente|kontoausz(ue|ü)ge|depotausz(ue|ü)ge|"
    r"steuerbescheinigungen?|mitteilungen|documents?|mailbox)$", re.I)


SECURITY_CHALLENGE_MARKERS = [
    # German
    # The phrases of a prompt, never a bare product name: "ING-App" is on
    # ordinary pages (the card settings name it), and stopped a run.
    "bestätige deine anmeldung", "in der ing-app bestätigen", "in deiner ing-app",
    "freigabe in der ing-app", "tan eingeben", "chiptan", "sicherheitscode", "bestätigungscode",
    "zu viele versuche", "sitzung ist abgelaufen", "sitzung abgelaufen",
    "du wurdest abgemeldet", "sie wurden abgemeldet",
    # English
    "verification code", "captcha", "access denied", "your session has expired",
]

RATE_LIMIT_MARKERS = ["zu viele anfragen", "später erneut", "too many requests",
                      "rate limit", "try again later", "temporarily unavailable"]


def looks_signed_out(page) -> bool:
    try:
        address = page.url or ""
        if not is_safe_url(address) or urlsplit(address).hostname != urlsplit(BASE).hostname:
            return True
        url = address.lower()
    except Exception:
        # A page that cannot say where it is is not a signed-in page.
        return True
    if any(m in url for m in LOGIN_URL_MARKERS):
        return True
    try:
        if page.locator("input[type='password']").count() > 0:
            return True
    except Exception:
        return True
    return False


def detect_security_challenge(page) -> Optional[str]:
    """Names the confirmation, CAPTCHA or throttling prompt on screen, or
    None. Visible text only. A sign-in page is not one: ING's carries a
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
    """A potentially signed-in page on the exact banking host."""
    return not looks_signed_out(page)


def _list_area(address: str) -> Optional[str]:
    """Which list an address shows: "postbox", "archive", or None for any
    other page. Only https on the banking host itself counts. A session id
    in the path and the query say nothing of which page it is."""
    try:
        parts = urlsplit(address or "")
    except ValueError:
        return None
    if parts.scheme != "https" or parts.hostname != HOST or not is_safe_url(address):
        return None
    path = parts.path.split(";", 1)[0].rstrip("/")
    if path in ("/app/postbox", "/app/postbox/postbox"):
        return "postbox"
    if path == "/app/postbox/postbox_archiv":
        return "archive"
    return None


def goto_documents(page) -> bool:
    """Open the Postbox, unless one of its lists is on screen already. A
    sign-in page on ING's banking host is left where it is, for the person
    to sign in. Any other page, a blank tab of the run's own say, is sent to
    the Postbox by its address."""
    signed_out = looks_signed_out(page)
    try:
        address = page.url or ""
    except Exception:
        address = ""
    if not signed_out and _list_area(address):
        return True
    if signed_out and is_safe_url(address) and urlsplit(address).hostname == HOST:
        return False
    try:
        page.goto(URLS["documents"], wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(2500)
    except Exception as e:
        log.info("the Postbox did not open: %s", type(e).__name__)
    return not looks_signed_out(page) and bool(_list_area(page.url or ""))


def ensure_statements(page) -> bool:
    return goto_documents(page)


def _open_area(page, source: str, again: bool = False) -> None:
    """Have `source`'s list on screen, opening its own address when another
    page is shown, and always when `again`. A tab signed out raises
    SessionExpired, and an address that lands anywhere else ListStopped."""
    if looks_signed_out(page):
        raise SessionExpired("ING shows its sign-in page")
    if again or _list_area(page.url or "") != source:
        try:
            page.goto(_AREAS[source], wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(1500)
        except Exception as e:
            log.info("the Postbox did not open: %s", type(e).__name__)
            if looks_signed_out(page):
                raise SessionExpired("ING shows its sign-in page") from None
            raise ListStopped("the Postbox did not open") from None
    if looks_signed_out(page):
        raise SessionExpired("ING shows its sign-in page")
    if _list_area(page.url or "") != source:
        raise ListStopped("the Postbox address opened another page")


# How long ING keeps an idle tab signed in is not measured yet. This app
# does not work around it either way: nothing renews the session, nothing
# reloads the page to keep it, nothing answers a prompt to stay signed in.
# A run that finds itself signed out stops, the person signs in again, and
# Resume carries on.


# -- dates --------------------------------------------------------------------

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


def parse_date(text):
    """The date this provider shows, as YYYY-MM-DD, or '' when it names a
    day that does not exist."""
    return _checked_date(_parse_date_from_page(text), "")


# -- kinds --------------------------------------------------------------------

def filed_category(row: dict) -> str:
    """The category a listed row's document is recorded under. The row's
    own, except that one of no known kind whose subject says it is a
    statement is recorded as one (ing_docs._record_statement_doc). Discover
    numbers the rows by it and a download finds its row by it, so the two
    read a row as the record holds it."""
    category = row.get("category") or ""
    title = re.sub(r"\s+", " ", str(row.get("title") or "")).strip() or "Statement"
    if category == OTHER and re.search(r"statement|kontoauszug", title, re.I):
        return ACCOUNT
    return category


def classify(kind: str, subject: str = "") -> str:
    """The category a row is filed under. Its document type decides when it
    names one; a type that says only that it is a message, or nothing this
    app knows, leaves it to the type and the subject read together."""
    for category, rx in _KIND_RULES:
        if rx.search(kind or ""):
            if category != MESSAGE:
                return category
            break
    hay = " ".join(t for t in (kind, subject) if t)
    for category, rx in _KIND_RULES:
        if rx.search(hay):
            return category
    return OTHER


# -- the Postbox, as its page shows it ----------------------------------------

# The two lists this app reads, and the address of each.
_AREAS = {"postbox": URLS["documents"], "archive": URLS["archive"]}

# What a Postbox row and its parts look like, as public descriptions of the
# page give them. The first row selector that finds anything is the one read.
_PARTS = {
    "rowSelectors": [".ibbr-table-body .ibbr-table-row",
                     ".ibbr-table-wrapper-postbox .ibbr-table-row",
                     ".ibbr-table-row"],
    "header": ".ibbr-table-header",
    "wrapper": ".ibbr-table-wrapper-postbox, .ibbr-table-body",
    "kindCell": ".postbox-grid-left span:not(.postbox-indicator)",
    "subjectCell": ".postbox-grid-description",
    "dateCell": ".postbox-grid-right",
    "unread": "postbox-unread",
    # A download link is one whose words, label or title are only this.
    "linkLabel": r"^(?:download|herunterladen|pdf|pdf herunterladen|dokument herunterladen)$",
    # A control that would show more rows. This app presses none of them,
    # so a list that has one is not read whole, and stops. The words may
    # name what more there is, "Weitere Dokumente laden" or "Ältere
    # Nachrichten anzeigen".
    "pagerLabel": (r"^(?:next|next page|weiter|nächste|nächste seite|naechste|naechste seite|"
                   r"mehr anzeigen|mehr laden|weitere anzeigen|weitere laden|"
                   r"load more|show more|"
                   r"(?:mehr|weitere|ältere|aeltere)\s+(?:dokumente|nachrichten|einträge|"
                   r"eintraege|mitteilungen)\s+(?:anzeigen|laden)|"
                   r"(?:load|show)\s+(?:more|older)\s+(?:documents|messages))$"),
    "pagerBox": ('[class*="pagination"], .pager, nav[aria-label*="seite" i], '
                 'nav[aria-label*="page" i]'),
}
_ROW_LIMIT = 5000
_MAX_LINKS = 4
_READING = {
    # The words of an empty list, which stand for its rows when it has none.
    # They are read only inside the list's own box (wrapper), and only as
    # the sentence ING was seen to show there for an empty archive, "Zu
    # Ihrer Suche können keine Dokumente angezeigt werden", or one like it.
    # A count or "keine neuen Nachrichten" elsewhere on the page, such as a
    # header's unread badge, says nothing of the list, and no new documents
    # is not no documents.
    "emptyText": (r"\bkeine\s+(?:dokumente|nachrichten|einträge|eintraege|mitteilungen)\s+"
                  r"(?:angezeigt|vorhanden|gefunden)|"
                  r"\b(?:postbox|postfach|archiv) ist leer|"
                  r"\bno (?:documents|messages) (?:to display|found|available)"),
    "busy": '[aria-busy="true"]',
    "rounds": 60, "waitRounds": 16, "stableRounds": 3, "pause": 500,
    "limit": _ROW_LIMIT, "maxLinks": _MAX_LINKS,
}

# Reads the Postbox rows in the page, and presses nothing. It waits until
# the rows stop changing and, when asked to, brings the last one into view,
# so a list that loads more as it is scrolled shows them all. Each row comes
# back as its document type, its subject, the one date its date cell shows,
# whether it is marked unread and the addresses of its download links.
_ROWS_JS = r"""async (a) => {
  const sleep = (ms) => new Promise(done => setTimeout(done, ms));
  const flat = (s) => String(s || "").replace(/\s+/g, " ").trim();
  const words = (node) => node ? flat(node.innerText || node.textContent || "") : "";
  const linkLabel = new RegExp(a.linkLabel, "i");
  const pagerLabel = new RegExp(a.pagerLabel, "i");
  const emptyText = new RegExp(a.emptyText, "i");
  const find = () => {
    for (const selector of a.rowSelectors) {
      const found = Array.from(document.querySelectorAll(selector))
        .filter(row => !row.closest(a.header));
      if (found.length) return found;
    }
    return [];
  };
  const names = (el) => [words(el), flat(el.getAttribute("aria-label")),
                         flat(el.getAttribute("title"))];
  const shown = (el) => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  const isDownload = (el) => names(el).some(name => linkLabel.test(name));
  const busy = () => Array.from(document.querySelectorAll(a.busy)).some(shown);
  let settled = false, truncated = false, last = -1, steady = 0;
  for (let round = 0; round < a.rounds; round++) {
    const rows = find();
    const loading = busy();
    if (rows.length > a.limit) { truncated = true; break; }
    if (!rows.length) {
      if (round + 1 >= a.waitRounds) { settled = !loading; break; }
      await sleep(a.pause);
      continue;
    }
    if (rows.length === last && !loading) {
      steady += 1;
      if (steady >= a.stableRounds) { settled = true; break; }
    } else {
      steady = 0;
    }
    last = rows.length;
    if (a.scroll) rows[rows.length - 1].scrollIntoView({block: "end"});
    await sleep(a.pause);
  }
  const all = find();
  if (all.length > a.limit) truncated = true;
  const pagers = Array.from(document.querySelectorAll("a, button, [role=button]"))
    .filter(el => shown(el) && !el.disabled && el.getAttribute("aria-disabled") !== "true" &&
                  names(el).some(name => pagerLabel.test(name))).length;
  const boxes = Array.from(document.querySelectorAll(a.pagerBox))
    .filter(el => shown(el) && el.querySelectorAll("a, button").length > 1).length;
  const anyDownload = Array.from(document.querySelectorAll("a[href]")).some(isDownload);
  const empty = !all.length && !anyDownload &&
                Array.from(document.querySelectorAll(a.wrapper))
                  .some(box => emptyText.test(words(box).slice(0, 50000)));
  const dateOf = (text) => {
    const found = new Set();
    for (const m of text.matchAll(/(?<!\d)\d{1,2}\.\d{1,2}\.\d{4}(?!\d)/g)) found.add(m[0]);
    return found.size === 1 ? Array.from(found)[0] : "";
  };
  const rows = all.slice(0, a.limit).map(row => {
    const hrefs = [];
    const seen = new Set();
    for (const link of row.querySelectorAll("a[href]")) {
      if (!isDownload(link)) continue;
      const raw = flat(link.getAttribute("href"));
      if (!raw || raw.startsWith("#") || /^javascript:/i.test(raw)) continue;
      const href = String(link.href || "");
      if (!href || seen.has(href)) continue;
      seen.add(href);
      hrefs.push(href);
      if (hrefs.length > a.maxLinks) break;
    }
    return {
      kind: words(row.querySelector(a.kindCell)).slice(0, 200),
      subject: words(row.querySelector(a.subjectCell)).slice(0, 300),
      date: dateOf(words(row.querySelector(a.dateCell)).slice(0, 200)),
      unread: row.classList.contains(a.unread) || !!row.querySelector("." + a.unread),
      hrefs,
    };
  });
  return {table_present: !!document.querySelector(a.wrapper), settled, truncated,
          pagination: pagers + boxes, empty, rows};
}"""

_STRANGE = "the Postbox answered in a shape this app does not read"


def _flat(text) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _digest(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def _look(page, scroll: bool) -> dict:
    """The rows on screen as _ROWS_JS reads them, checked for shape. A tab
    gone to sign-in raises SessionExpired, and an answer this app cannot
    read raises ListStopped."""
    try:
        seen = page.evaluate(_ROWS_JS, dict(_PARTS, **_READING, scroll=bool(scroll)))
    except Exception as e:
        log.info("the Postbox rows could not be read: %s", type(e).__name__)
        if looks_signed_out(page):
            raise SessionExpired("ING shows its sign-in page") from None
        raise ListStopped("the Postbox rows could not be read") from None
    flags = ("table_present", "settled", "truncated", "empty")
    if (not isinstance(seen, dict) or any(type(seen.get(k)) is not bool for k in flags)
            or type(seen.get("pagination")) is not int or seen["pagination"] < 0
            or not isinstance(seen.get("rows"), list) or len(seen["rows"]) > _ROW_LIMIT):
        raise ListStopped(_STRANGE)
    rows = []
    for r in seen["rows"]:
        if (not isinstance(r, dict)
                or any(type(r.get(k)) is not str for k in ("kind", "subject", "date"))
                or type(r.get("unread")) is not bool or not isinstance(r.get("hrefs"), list)
                or len(r["hrefs"]) > _MAX_LINKS + 1
                or any(type(h) is not str or not h or len(h) > 8192 for h in r["hrefs"])):
            raise ListStopped(_STRANGE)
        rows.append({"kind": _flat(r["kind"]), "subject": _flat(r["subject"]),
                     "date": _flat(r["date"]), "unread": r["unread"],
                     "hrefs": list(r["hrefs"])})
    out = {k: seen[k] for k in flags}
    out.update(pagination=seen["pagination"], rows=rows)
    return out


# Words an address that changes something would carry. A download link that
# carries any of them is not followed, whatever its label says.
_LINK_REFUSES = ("logout", "signout", "abmeld", "lösch", "loesch", "delete", "remove",
                 "entfern", "archivier", "verschieb", "moveto", "gelesen", "markier",
                 "markasread", "mark-as", "asread", "unread", "überweis", "ueberweis",
                 "transfer", "zahlung", "payment", "einstellung", "setting", "kündig",
                 "kuendig", "sperr")
# Words refused only where they stand alone, as "archive" in an action.
_LINK_REFUSES_ALONE = frozenset(("archive", "move", "read"))


def _safe_download(href: str) -> bool:
    """Whether a row's download address is one to fetch: https on the
    banking host, under /app/, with no word of an address that changes
    something in it, as written or decoded."""
    try:
        parts = urlsplit(href or "")
    except ValueError:
        return False
    if (parts.scheme != "https" or parts.hostname != HOST or parts.username
            or parts.password or not is_safe_url(href) or not parts.path.startswith("/app/")):
        return False
    said = parts.path + "?" + parts.query
    for text in (said, unquote(said)):
        low = text.lower()
        if any(word in low for word in _LINK_REFUSES):
            return False
        if _LINK_REFUSES_ALONE & set(re.split(r"[^a-z0-9]+", low)):
            return False
    return True


# Why a row that might be a document is passed over.
SKIPS = ("unread", "no_link", "unclear", "refused")


def _read_area(page, source: str, config: Optional[dict] = None, navigate: bool = True,
               scroll: bool = True, again: bool = False) -> dict:
    """One list, "postbox" or "archive", read whole or not at all.

    Every row that might be a document comes back among the candidates,
    with why it is passed over if it is: marked unread, no download link,
    more than one, or a link this app does not follow. Rows alike in type,
    subject and date are told apart by their place among those alike
    (rank), which is all the page says of them. The rest, with a date,
    are its documents. Anything not read whole raises ListStopped. With
    `again`, the list is opened by its own address even when it is on
    screen already."""
    if navigate:
        _open_area(page, source, again=again)
    elif looks_signed_out(page):
        raise SessionExpired("ING shows its sign-in page")
    elif _list_area(page.url or "") != source:
        raise ListStopped("the page on screen is not the Postbox")
    seen = _look(page, scroll)
    where = "the Postbox archive" if source == "archive" else "the Postbox"
    if seen["truncated"]:
        raise ListStopped(f"{where} shows more rows than this app reads at once")
    if not seen["settled"]:
        raise ListStopped(f"{where} was still loading its rows")
    if seen["pagination"]:
        raise ListStopped(f"{where} has a further page or a show-more button, "
                          "which this app does not press")
    include_unread = bool((config or {}).get("include_unread", True))
    candidates = []
    for r in seen["rows"]:
        date = parse_date(r["date"]) if r["date"] else ""
        if not r["hrefs"] and not date:
            continue    # a heading, a spacer or a notice, not a document
        if r["unread"] and not include_unread:
            skip = "unread"
        elif not r["hrefs"]:
            skip = "no_link"
        elif len(r["hrefs"]) > 1:
            skip = "unclear"
        elif not _safe_download(r["hrefs"][0]):
            skip = "refused"
        else:
            skip = ""
        candidates.append(dict(r, date=date, date_text=r["date"], skip=skip,
                               sig=_digest(r["kind"], r["subject"], r["date"])[:16]))
    if not candidates and not seen["empty"]:
        raise ListStopped(f"{where} showed no rows this app reads"
                          + (" (read_archive: false leaves the archive out)"
                             if source == "archive" else ""))
    if candidates and not any(c["hrefs"] for c in candidates):
        raise ListStopped(f"{where} shows no download link in its rows, and the link may "
                          "sit in a menu, which this app does not open")
    groups: Dict[str, List[dict]] = {}
    for c in candidates:
        groups.setdefault(c["sig"], []).append(c)
    for alike in groups.values():
        for rank, c in enumerate(alike):
            c["rank"], c["group"] = rank, len(alike)
    passed = dict.fromkeys(SKIPS, 0)
    rows, undated_rows = [], 0
    for c in candidates:
        if c["skip"]:
            passed[c["skip"]] += 1
        elif not c["date"]:
            undated_rows += 1
        else:
            rows.append(c)
    return {"rows": rows, "candidates": candidates, "undated": undated_rows,
            "skipped": passed}


_IBAN_RE = re.compile(r"\bDE\d{2}(?:\s?\d){18}\b")
_MASKED_RE = re.compile(r"[*xX•]{4}[ *xX•]*(\d{4})\b")
_NUMBERED_RE = re.compile(r"(?:konto|depot|karten?)[\s-]*(?:(?:nummer|nr\.?)\s*:?\s*)?(\d{6,})\b",
                          re.I)


def _account(text: str) -> str:
    """The last four digits of the account, depot or card a row names, never
    the whole number, or "" when it names none."""
    m = _IBAN_RE.search(text or "")
    if m:
        return re.sub(r"\s", "", m.group(0))[-4:]
    m = _MASKED_RE.search(text or "")
    if m:
        return m.group(1)
    m = _NUMBERED_RE.search(text or "")
    return m.group(1)[-4:] if m else ""


def _row_of(c: dict, source: str, serial: str) -> dict:
    """A document row as Discover records it. Its title is its subject, with
    its document type ahead of it where the subject does not say it.

    Its id names it within this one listing only. ING's links carry the
    page they were read from, so an id kept from one listing says nothing
    in the next (paperpull_core.keys.told_apart reads ids that way)."""
    kind, subject = c["kind"], c["subject"]
    if kind and subject and kind.lower() not in subject.lower():
        title = f"{kind} - {subject}"
    else:
        title = subject or kind or "Dokument"
    return {
        "title": title,
        "date": c["date"],
        "account": _account(f"{kind} {subject}"),
        "category": classify(kind, subject),
        "item_id": _digest(serial, source, kind, subject, c["date_text"], c["hrefs"][0])[:32],
        "client_id": source,
        "href": _AREAS[source],
        "period_start": "",
        "created": "",
        # This app's own, to find the row again in a fresh look at its list.
        "source": source,
        "sig": c["sig"],
        "rank": c["rank"],
        "group": c["group"],
    }


# One listing serves a run's downloads for a while, rather than the whole
# Postbox and its archive being read again before every document.
LISTING_SECONDS = 600
_listing: dict = {}


def _all_rows(page, config: Optional[dict] = None, fresh: bool = False,
              navigate: bool = True) -> List[dict]:
    """The Postbox, and its archive unless read_archive is false, read whole
    or not at all. A part that cannot be read raises ListStopped (or
    SessionExpired), so no listing missing a part is ever kept or called
    whole. With navigate false only the list on screen is read, as it
    stands, for Diagnose, and nothing is kept for a download.

    A row with no date this app can read cannot be keyed, so it is left out
    and counted (undated), for Discover to say, as are the rows passed over
    (skipped). A list where no row has a date is not read, and stops."""
    config = config or {}
    key = (bool(config.get("include_unread", True)), bool(config.get("read_archive", True)))
    now = _time.monotonic()
    if (navigate and not fresh and _listing.get("rows") is not None
            and _listing.get("key") == key and now - _listing.get("at", 0) < LISTING_SECONDS):
        return _listing["rows"]
    _listing.update(undated=0, skipped=dict.fromkeys(SKIPS, 0))
    if navigate:
        _listing.pop("rows", None)
        sources = ["postbox", "archive"] if key[1] else ["postbox"]
    else:
        if looks_signed_out(page):
            raise SessionExpired("ING shows its sign-in page")
        here = _list_area(page.url or "")
        if not here:
            raise ListStopped("the page on screen is not the Postbox")
        sources = [here]
    serial = secrets.token_hex(8)
    rows: List[dict] = []
    undated_rows = 0
    passed = dict.fromkeys(SKIPS, 0)
    for source in sources:
        # A listing opens each list by its own address, never the view the
        # person left on screen, which may hold a search or a filter of
        # their own (ING's empty notice asks to check "Ihre Suche oder die
        # Filterkriterien"), so a filtered list is never read as the whole.
        area = _read_area(page, source, config, navigate=navigate, scroll=navigate,
                          again=navigate)
        rows += [_row_of(c, source, serial) for c in area["rows"]]
        undated_rows += area["undated"]
        for k, n in area["skipped"].items():
            passed[k] += n
    if undated_rows and not rows:
        raise ListStopped("no document in the list carries a date this app can read")
    if undated_rows:
        log.warning("%d document(s) carry no date this app can read, so they are left out",
                    undated_rows)
    _listing.update(undated=undated_rows, skipped=passed)
    if navigate:
        _listing.update(rows=rows, at=now, key=key)
    return rows


def undated() -> int:
    """How many documents the last listing left out for carrying no date
    this app can read."""
    return int(_listing.get("undated") or 0)


def skipped() -> dict:
    """How many rows the last listing passed over, by why: marked unread
    (include_unread), with no download link, with more than one, or with
    one this app does not follow."""
    return {Fixed(k): int(n) for k, n in (_listing.get("skipped") or {}).items()}


def _wanted(config: Optional[dict]) -> set:
    return set((config or {}).get("document_types") or ALL_CATEGORIES) | {OTHER}


def listed_rows(page, config: Optional[dict] = None, fresh: bool = False,
                navigate: bool = True) -> List[dict]:
    """The rows of the kinds document_types keeps, in the listing's order.
    Discover numbers these, and so does each download's look at a recent
    listing, so the two agree on which row is which document."""
    wanted = _wanted(config)
    return [r for r in _all_rows(page, config, fresh=fresh, navigate=navigate)
            if r["category"] in wanted]


def collect_documents(page, keep=None, config: Optional[dict] = None,
                      navigate: bool = True) -> List[dict]:
    """Every PDF the Postbox and its archive list, newest first. `keep` is
    the run's scope predicate over year labels. Which kinds are kept
    follows document_types in the config. With navigate false only the
    list on screen is read, as Diagnose reads it."""
    rows = [r for r in listed_rows(page, config, fresh=True, navigate=navigate)
            if keep is None or keep(r["date"][:4])]
    rows.sort(key=lambda r: r["date"], reverse=True)
    log.info("Postbox: %d PDF(s)", len(rows))
    return rows


def answers_its_list(page) -> bool:
    """Whether the Postbox shows its list, a table or the words of an empty
    one, so a banking address alone is never taken for a session that
    reads. SessionExpired when ING shows its sign-in page, and ListStopped
    when the Postbox shows neither."""
    if looks_signed_out(page):
        raise SessionExpired("ING shows its sign-in page")
    _open_area(page, "postbox")
    seen = _look(page, scroll=False)
    if seen["table_present"] or seen["empty"]:
        return True
    raise ListStopped("the Postbox showed no list this app knows")


def resolve_item(page, title: str, date: str, account: str, occurrence: int = 0,
                 item_id: str = "", *, category: str, number_rows, twins: int = 1,
                 config: Optional[dict] = None) -> Optional[dict]:
    """The document's own row of a recent listing, or None when the listing
    no longer shows it.

    `number_rows` numbers the listing as Discover numbered it, the stored
    ids first, so a row answers to `occurrence` and no two documents can
    come to one row. Rows are numbered within their kind, so two documents
    alike in all but `category` can both be 0, and a row is its document's
    only when its kind (filed_category) is the document's too. A place
    among the rows alike says nothing once the list comes back in another
    order. A row found by its number and not by `item_id` is taken only
    when the listing shows as many documents alike as the app knows
    (`twins`). Anything less raises NotToldApart rather than guess."""
    rows = listed_rows(page, config)
    numbers = number_rows(rows)
    alike = [i for i, r in enumerate(rows)
             if r["title"] == title and r["date"] == date and r["account"] == account
             and filed_category(r) == category]
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


# -- one document -------------------------------------------------------------

# What each reason a row is passed over says, when it is the row a download
# looks for.
_SKIP_SAID = {
    "unread": "the Postbox marks this document unread, and include_unread is false",
    "no_link": "the Postbox shows this document without a download link",
    "unclear": "the Postbox shows this document with more than one download link",
    "refused": "the Postbox links this document to an address this app does not follow",
}


def _fresh_href(page, row: dict, config: Optional[dict], reload: bool = False) -> str:
    """The download address the Postbox shows now for the document of `row`.
    ING's links carry the page they were read from, so one read in an
    earlier look may no longer lead to the document. The row is found again
    by its type, subject and date and its place among the rows alike, and
    only where the list shows as many alike as it did."""
    source = row["source"]
    if reload:
        _open_area(page, source, again=True)
    area = _read_area(page, source, config)
    alike = [c for c in area["candidates"] if c["sig"] == row["sig"]]
    if not alike:
        raise RuntimeError("the Postbox no longer lists this document")
    if len(alike) != row["group"]:
        raise NotToldApart("The Postbox shows another number of documents alike now")
    mine = alike[row["rank"]]
    if mine["skip"]:
        raise RuntimeError(_SKIP_SAID[mine["skip"]])
    return mine["hrefs"][0]


# Fetches one document from inside the Postbox page, with the browser's own
# session, and only from the banking host the tab is on. Nothing else is
# sent: no form, no button. A PDF, or a ZIP holding one, comes back as its
# bytes. Anything else comes back as what it was, never its words.
_FETCH_JS = r"""async ({url, host}) => {
  if (location.hostname !== host) return {state: "elsewhere"};
  let target;
  try { target = new URL(url, location.href); } catch (e) { return {state: "refused"}; }
  if (target.protocol !== "https:" || target.hostname !== host || target.username ||
      target.password) return {state: "refused"};
  let r;
  try {
    r = await fetch(target.href, {method: "GET", mode: "same-origin",
                                  credentials: "same-origin", redirect: "follow",
                                  cache: "no-store"});
  } catch (e) {
    return {state: "failed"};
  }
  const drop = async () => { try { if (r.body) await r.body.cancel(); } catch (e) {} };
  let landed = "";
  try { landed = new URL(r.url || target.href).hostname; } catch (e) { landed = ""; }
  if (landed !== host) { await drop(); return {state: "moved"}; }
  if (r.status !== 200) { await drop(); return {state: "status", status: r.status}; }
  let bytes;
  try {
    bytes = await ppRead(r);
  } catch (e) {
    if (ppRefused(e)) throw e;
    return {state: "failed"};
  }
  const starts = (head) => bytes.length >= head.length && head.every((b, i) => bytes[i] === b);
  if (starts([0x25, 0x50, 0x44, 0x46]) || starts([0x50, 0x4b, 0x03, 0x04])) {
    let s = "";
    for (let i = 0; i < bytes.length; i += 0x8000) {
      s += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
    }
    const b64 = btoa(s);
    return {state: "file", b64};
  }
  const text = new TextDecoder("utf-8").decode(bytes.subarray(0, 2000000)).toLowerCase();
  return {state: /<html|<!doctype html/.test(text.slice(0, 4096)) ? "page" : "other",
          password: /type\s*=\s*["']?password/.test(text)};
}"""

_FILE_STARTS = (b"%PDF", b"PK\x03\x04")


def _fetch(page, href: str) -> Optional[bytes]:
    """The document at `href`, fetched from inside the Postbox page, or None
    when ING answered with a page of its own, as it may for a link that has
    expired. A sign-in page, a 401 or a 403 raises SessionExpired, a fetch
    the browser did not finish FetchFailed, an answer over the size limit
    intake.TooLarge, and any other answer RuntimeError."""
    try:
        got = intake.evaluate(page, _FETCH_JS, {"url": href, "host": HOST})
    except intake.TooLarge:
        raise
    except Exception as e:
        log.info("the document could not be fetched: %s", type(e).__name__)
        if looks_signed_out(page):
            raise SessionExpired("ING shows its sign-in page") from None
        raise RuntimeError("the page changed while the document was fetched") from None
    state = got.get("state") if isinstance(got, dict) else None
    if state == "file":
        try:
            data = intake.decode(got.get("b64") or "", validate=True)
        except intake.TooLarge:
            raise
        except Exception:
            raise RuntimeError("ING answered with a document this app could not read") from None
        if not data.startswith(_FILE_STARTS):
            raise RuntimeError("ING answered with a document this app could not read")
        return data
    if state == "elsewhere":
        raise SessionExpired("the ING tab is no longer on the banking site")
    if state == "status":
        status = got.get("status")
        if status in (401, 403):
            raise SessionExpired("ING answered as signed out")
        raise RuntimeError("ING answered with status %s"
                           % (status if type(status) is int else "unknown"))
    if state == "page":
        if got.get("password") is True or looks_signed_out(page):
            raise SessionExpired("ING answered with its sign-in page")
        return None
    if state == "failed":
        if looks_signed_out(page):
            raise SessionExpired("ING shows its sign-in page")
        raise FetchFailed("the document could not be fetched. The connection failed, "
                          "or ING sent its link on to another host, which this app "
                          "does not follow")
    if state == "moved":
        raise RuntimeError("ING sent the document link on to another host")
    if state == "refused":
        raise RuntimeError("the document link is not one this app follows")
    raise RuntimeError("ING answered with something other than a document")


def download_document(page, title: str, date: str, out_path: Path, occurrence: int = 0,
                      item_hint: str = "", client_hint: str = "", account: str = "", *,
                      category: str, number_rows, twins: int = 1,
                      config: Optional[dict] = None) -> str:
    """Save one document, and answer the id of the row it came from, or ""
    when it was over the size limit and nothing was saved.

    Its row is found in a recent listing (resolve_item, which raises
    NotToldApart when that cannot be told), and its download link is read
    again from the Postbox as it stands now. The PDF is fetched from inside
    the page. When ING answers with a page instead, or the fetch does not
    finish, the list is opened afresh and the link read and fetched once
    more. Nothing is pressed."""
    row = resolve_item(page, title, date, account, occurrence, item_id=item_hint,
                       category=category, number_rows=number_rows, twins=twins,
                       config=config)
    if row is None:
        raise RuntimeError("the Postbox no longer lists this document")
    for attempt in range(2):
        href = _fresh_href(page, row, config, reload=attempt > 0)
        failed = None
        try:
            data = _fetch(page, href)
        except intake.TooLarge:
            log.warning("a document was over the size limit, so nothing was saved")
            return ""
        except FetchFailed as e:
            data, failed = None, e
        if data:
            out_path = Path(out_path)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(data)
            return row["item_id"]
    if failed is not None:
        raise failed
    raise RuntimeError("ING answered with a page instead of the document, "
                       "so its link may have expired")


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


# -- what Diagnose counts -----------------------------------------------------

_CENSUS_LIMIT = 10000
# Counts the Postbox rows the way _ROWS_JS reads them, and their kinds the
# way classify files them, so a count says what a run would find. Nothing
# from the page leaves it but numbers, and nothing is pressed.
_POSTBOX_CENSUS_JS = r"""(a) => {
  const flat = (s) => String(s || "").replace(/\s+/g, " ").trim();
  const words = (node) => node ? flat(node.innerText || node.textContent || "") : "";
  let found = [];
  for (const selector of a.rowSelectors) {
    found = Array.from(document.querySelectorAll(selector))
      .filter(row => !row.closest(a.header));
    if (found.length) break;
  }
  const rows = found.slice(0, a.limit);
  const linkLabel = new RegExp(a.linkLabel, "i");
  const pagerLabel = new RegExp(a.pagerLabel, "i");
  const rules = a.rules.map(([category, pattern]) => [category, new RegExp(pattern, "i")]);
  const names = (el) => [words(el), flat(el.getAttribute("aria-label")),
                         flat(el.getAttribute("title"))];
  const shown = (el) => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  const has = (row, selector) => !!row.querySelector(selector);
  const kindOf = (row) => words(row.querySelector(a.kindCell)).slice(0, 200);
  const subjectOf = (row) => words(row.querySelector(a.subjectCell)).slice(0, 300);
  const classify = (kind, subject) => {
    const first = rules.find(([, rx]) => rx.test(kind));
    if (first && first[0] !== a.message) return first[0];
    const hay = [kind, subject].filter(Boolean).join(" ");
    const match = rules.find(([, rx]) => rx.test(hay));
    return match ? match[0] : a.other;
  };
  const realDay = (text) => {
    const m = /^(\d{1,2})\.(\d{1,2})\.(\d{4})$/.exec(text);
    if (!m) return false;
    const day = Number(m[1]), month = Number(m[2]), year = Number(m[3]);
    // The year range paperpull_core.dates accepts.
    if (year < 1900 || year > 2200 || month < 1 || month > 12 || day < 1 || day > 31)
      return false;
    const date = new Date(0);
    date.setUTCFullYear(year, month - 1, day);
    return date.getUTCFullYear() === year && date.getUTCMonth() === month - 1 &&
           date.getUTCDate() === day;
  };
  const readableDate = (row) => {
    const text = words(row.querySelector(a.dateCell)).slice(0, 200);
    const seen = new Set();
    for (const m of text.matchAll(/(?<!\d)\d{1,2}\.\d{1,2}\.\d{4}(?!\d)/g)) seen.add(m[0]);
    return seen.size === 1 && realDay(Array.from(seen)[0]);
  };
  const downloads = (row) => Array.from(row.querySelectorAll("a[href]")).some(link => {
    const raw = flat(link.getAttribute("href"));
    return raw && !raw.startsWith("#") && !/^javascript:/i.test(raw) &&
           names(link).some(name => linkLabel.test(name));
  });
  const pagers = Array.from(document.querySelectorAll("a, button, [role=button]"))
    .filter(el => shown(el) && !el.disabled && el.getAttribute("aria-disabled") !== "true" &&
                  names(el).some(name => pagerLabel.test(name))).length;
  const boxes = Array.from(document.querySelectorAll(a.pagerBox))
    .filter(el => shown(el) && el.querySelectorAll("a, button").length > 1).length;
  const categories = rows.map(row => classify(kindOf(row), subjectOf(row)));
  return {
    table_present: !!document.querySelector(a.wrapper),
    filter_present: !!document.querySelector(
      ".account-filters, select[name='erweiterterFilter:dokumentArten']"),
    rows: rows.length,
    truncated: found.length > a.limit,
    rows_with_kind: rows.filter(row => has(row, a.kindCell)).length,
    rows_with_subject: rows.filter(row => has(row, a.subjectCell)).length,
    rows_with_date: rows.filter(row => has(row, a.dateCell)).length,
    rows_with_parseable_date: rows.filter(row => has(row, a.dateCell) && readableDate(row)).length,
    rows_with_download: rows.filter(downloads).length,
    statement_candidates: categories.filter(value => value === a.statement).length,
    tax_candidates: categories.filter(value => value === a.tax).length,
    unread_rows: rows.filter(row => row.classList.contains(a.unread) ||
                                    !!row.querySelector("." + a.unread)).length,
    pagination_controls: Math.min(pagers + boxes, a.limit)
  };
}"""


def postbox_census(page) -> dict:
    """Count the Postbox shapes this app reads and the kinds of its rows,
    without exporting a value from the page or pressing anything.

    The counts describe only the page as it stands, not the whole mailbox.
    """
    address = page.url or ""
    parsed = urlsplit(address)
    if not is_safe_url(address) or parsed.hostname != HOST:
        raise SessionExpired("The Postbox census requires an ING banking page.")
    path = parsed.path.split(";", 1)[0]
    if path != "/app/postbox" and not path.startswith("/app/postbox/"):
        return {Fixed("inspected"): False}

    result = page.evaluate(_POSTBOX_CENSUS_JS, dict(
        _PARTS, limit=_CENSUS_LIMIT,
        rules=[(category, pattern.pattern) for category, pattern in _KIND_RULES],
        message=MESSAGE, other=OTHER, statement=ACCOUNT, tax=TAX))
    counts = ("rows", "rows_with_kind", "rows_with_subject", "rows_with_date",
              "rows_with_parseable_date", "rows_with_download", "statement_candidates",
              "tax_candidates", "unread_rows", "pagination_controls")
    flags = ("table_present", "filter_present", "truncated")
    if not isinstance(result, dict) or any(type(result.get(key)) is not bool for key in flags):
        raise RuntimeError("The Postbox structure could not be read.")
    if any(type(result.get(key)) is not int or not 0 <= result[key] <= _CENSUS_LIMIT
           for key in counts):
        raise RuntimeError("The Postbox structure returned invalid counts.")
    if (any(result[key] > result["rows"] for key in counts[1:-1])
            or result["rows_with_parseable_date"] > result["rows_with_date"]
            or result["statement_candidates"] + result["tax_candidates"] > result["rows"]):
        raise RuntimeError("The Postbox structure returned inconsistent row counts.")

    area = _list_area(address) or "other"
    return {Fixed("inspected"): True, Fixed("area"): Fixed(area),
            **{Fixed(key): result[key] for key in flags + counts}}


def survey(page, dwell_ms: int = 4000) -> dict:
    """Survey the current page and its responses without clicking anything.

    Bodies are recorded as shape only, never values. No screenshot is taken,
    since a bank page shows balances.
    """
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
        report["pages"].append(_page_summary(page))
        report[Fixed("postbox_structure")] = postbox_census(page)
    finally:
        try:
            page.remove_listener("response", on_response)
        except Exception:
            pass
    return report
