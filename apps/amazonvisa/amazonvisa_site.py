"""Read Amazon Visa documents through the signed-in portal."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
from typing import Optional

from paperpull_core import failure
from paperpull_core import intake
from paperpull_core.controls import SETTINGS_CONTROL_RE, AUTH_CONTROL_RE
# Everything on its way into a diagnostic file goes through here.
from paperpull_core.redact import redact, set_private_words  # noqa: F401
from paperpull_core.urls import is_safe_url as _host_allows

log = logging.getLogger("amazonvisa_docs.site")

# Every host this app will read from. Anything else is refused.
ALLOWED_HOSTS = ("kunden.openbankpay.com",)

BASE = "https://kunden.openbankpay.com"
URLS = {
    "home": BASE + "/amazon/login",
    "login": BASE + "/amazon/login",
    "documents": BASE + "/amazon/documentation",
}

class SessionExpired(RuntimeError):
    """The document API needs the user to sign in again."""


class ListStopped(RuntimeError):
    """A list could not be read whole. A run that reads the list again while
    it downloads stops once with the list unread
    (listing.read_again_stopped), since every document after it reads the
    same list."""


class NoFile(RuntimeError):
    """The portal lists a document and gives no PDF for it, an error for
    that one document's ticket or file, no PDF link, or an answer that is
    not a PDF. Once the list read again still answers, only that document
    fails and the run goes on to the next (download_document)."""


class NotToldApart(RuntimeError):
    """A fresh list cannot uniquely identify a document."""


def is_safe_url(url: str) -> bool:
    """True only for an https URL on one of this provider's own hosts.

    The check itself lives in the core, so all of them answer the same way.
    This app keeps the hosts, which is the part that really is its own."""
    return _host_allows(url, ALLOWED_HOSTS, subdomains=False)


# ---------------------------------------------------------------------------
# HARD SAFETY GUARD. Tuned for a German bank and broker, whose pages may be
# in German or English. Never move money, never pay, never buy, sell or
# place an order, never start, change or pause a savings plan, never open,
# close, lock or replace anything, never take out credit, never change a
# setting.
# ---------------------------------------------------------------------------
FORBIDDEN_CONTROL_RE = re.compile(
    # Money moving, German. "Übertrag" is a depot moved to another bank.
    r"((ue|ü)berweis|(ue|ü)bertrag|\bechtzeit|dauerauftr|lastschrift|\bumbuch|"
    r"\bsenden\b|\bzahl(en|ung)\b|\bbezahl|geld\s+(senden|anfordern)|\bauszahl|"
    r"\beinzahl|\babheb|\bvorlage|\bempf(ae|ä)nger|\bzur(ue|ü)ckbuch|"
    r"widersprech|widerspruch|"
    # Trading, German. Kaufen and Verkaufen are what a trade button says.
    # "Kauf" alone is in the name of every Wertpapierabrechnung, so only a
    # label that is nothing but that word is refused.
    r"\bkaufen\b|\bverkaufen\b|^\s*(ver)?kauf\s*$|\border\b|\bhandel|\bzeichn|"
    r"\blimit|\bstop\b|\bkurs\s*alarm|\bpreis\s*alarm|\bsparplan\s+"
    r"(anlegen|einrichten|erstellen|(ae|ä)ndern|pausieren|aussetzen|l(oe|ö)schen)|"
    # Credit of any kind, Ratenkredit, Wertpapierkredit and a Kreditrahmen
    # included, while "Kreditkarte" passes.
    r"kredit\b|\bdispo|rahmen\b|\bhebel|\bderivat|\bupgrade|"
    # Cards, accounts and the person's own data, German.
    r"\ber(oe|ö)ffn|\bbeantrag|\bantrag\b|\bk(ue|ü)ndig|\bsperr|entsperr|\bpin\b|"
    r"\bfreigeb|\bfreigabe|\bbest(ae|ä)tig|\bzustimm|\bakzeptier|"
    r"\b(ae|ä)nder|\bbearbeit|\bl(oe|ö)sch|\bentfern|\barchivier|\beinricht|"
    r"\baktivier|deaktivier|\babschlie(ss|ß)|\bhinzuf(ue|ü)g|\banlegen\b|"
    r"als\s+gelesen|gelesen\s+markier|\bfreistellungsauftrag\s+(erteilen|anlegen|(ae|ä)ndern)|"
    r"\bkontowecker|\bbenachrichtigung|"
    r"\babmeld|\bpasswort|\bkennwort|\bger(ae|ä)t|\badresse\b|\be-?mail\b|"
    r"\btelefon|\bhandynummer|pers(oe|ö)nliche\s+daten|\beinstellung|"
    # Ordering, requesting, signing, uploading and entering data, German.
    # A loss certificate asked for closes the year's loss pot, and a paper
    # copy or a duplicate can carry a fee. "Papier" at a word's start only,
    # since every Wertpapierabrechnung holds it.
    r"anforder|bestell|unterschreib|unterzeichn|\bsignier|hochlad|aktualisier|"
    r"hinterleg|freischalt|\bbeauftrag|\bper\s+post\b|\bpapier|duplikat|\bkopie|"
    r"zweitschrift|\b\w*(konto|depot)\s+(er)?(oe|ö)ffnen|"
    # Opening anything but a document, requesting, signing, uploading,
    # paper and copies, credit and cards, English.
    r"\bopen\b[\w\s-]{0,30}?\b(accounts?|depots?|portfolios?|cards?|overdraft|"
    r"positions?|loans?|savings|investments?)\b(?!\s+(statements?|documents?))|"
    r"\brequest|\bupload|\bsign\b|\be-?sign|\bpaper\b|\bcop(y|ies)\b|\bduplicate|"
    r"\block\b|\bunlock|\breplac|\bactivat|overdraft|credit\s+(line|limit|increase)|"
    r"\bloans?\b|\bborrow|\bmargin\b|"
    r"\bclose\s+(my\s+|the\s+|this\s+|an?\s+)?(account|depot|portfolio|card)|"
    # Money moving and trading, English
    r"transfer\b|\bwire\b|\bpay\b|payment|\bdeposit|withdraw|\bbuy\b|\bsell\b|"
    r"\btrade\b|savings\s+plan|\bstanding\s+order|direct\s+debit|"
    # Word boundaries on both sides of the verb stems, so "Credit" and
    # "Exchange" stay allowed.
    r"\bchang(e|es|ed|ing)\b|\bedit(s|ed|ing)?\b|\bupdat(e|es|ed|ing)\b|"
    r"\bdelet|\bremov(e|es|ed|ing|al)\b|\bsubmit|\bconfirm\b|\baccept\b|"
    r"\bmark\s+as\s+read\b|\barchive\b|log\s*out|logout|sign\s*out)",
    re.I)

# What a document control may look like. A control must match this AND not
# match the blocklist.
SAFE_DOC_CONTROL_RE = re.compile(
    # "Open", "Öffnen", "View" and "Anzeigen" alone are a document's own
    # button. Beside any other word they need a document's word too, since
    # "Kinderdepot öffnen" and "Open a child account" open an account.
    r"(herunterladen|download|\bpdf\b|^\s*anzeigen\s*$|^\s*(oe|ö)ffnen\s*$|"
    r"^\s*view\s*$|^\s*open\s*$|"
    r"postbox|postfach|mailbox|\binbox\b|dokument|document|kontoauszug|ausz(ue|ü)ge|"
    r"abrechnung|depotauszug|finanzreport|steuer|\btax\b|ertr(ae|ä)gnis|"
    r"verlustbescheinigung|kosteninformation|mitteilung|statement|"
    r"\bconfirmations?\b|\barchiv\b|mehr\s+(anzeigen|laden)|show\s+more|load\s+more)", re.I)


def is_safe_control(name: str) -> bool:
    name = (name or "").strip()
    if not name:
        return False
    if (FORBIDDEN_CONTROL_RE.search(name) or SETTINGS_CONTROL_RE.search(name)
            or AUTH_CONTROL_RE.search(name)):
        return False
    return bool(SAFE_DOC_CONTROL_RE.search(name))


# The phrases of a prompt, never a bare product or menu name, which an
# ordinary signed-in page can show too.
SECURITY_CHALLENGE_MARKERS = [
    # German
    "tan eingeben", "geben sie die tan ein", "bestätigungscode", "sicherheitscode",
    "code eingeben", "geben sie den code ein", "zu viele versuche",
    "sitzung ist abgelaufen", "sitzung abgelaufen", "sie wurden abgemeldet",
    "aus sicherheitsgründen abgemeldet",
    # English
    "one-time code", "one time code", "enter the code", "verification code",
    "we sent a code", "are you a robot", "captcha", "access denied",
    "your session has expired", "session timed out",
]

# Authentication and OAuth callback pages are never a document list.
LOGIN_URL_MARKERS = ["/login", "/logout"]

RATE_LIMIT_MARKERS = ["zu viele anfragen", "später erneut", "too many requests",
                      "rate limit", "try again later", "temporarily unavailable",
                      "unusual traffic", "http error 429"]


def looks_signed_out(page) -> bool:
    """True where the page is a sign-in page by its address, shows a
    password field, or cannot say where it is."""
    try:
        url = (page.url or "").lower()
    except Exception:
        # A page that cannot say where it is is treated as signed out, the
        # safe answer.
        return True
    if not is_safe_url(url) or any(m in url for m in LOGIN_URL_MARKERS):
        return True
    try:
        if page.locator("input[type='password']").count() > 0:
            return True
    except Exception:
        return True
    return False


def detect_security_challenge(page) -> Optional[str]:
    """Names the code, CAPTCHA or throttling prompt on screen, or None.
    Visible text only, and never a reason to think a session is signed in
    when it finds nothing."""
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


def _page_summary(page) -> dict:
    out = {"url": "", "title": ""}
    try:
        url = page.url or ""
        out["on_site"] = is_safe_url(url)
        # The path only. A query string or a fragment can carry a session
        # or an account's id.
        out["url"] = (redact(re.split(r"[?#]", url, maxsplit=1)[0]) if out["on_site"]
                      else "(not on kunden.openbankpay.com)")
    except Exception:
        out["on_site"] = False
    if not out["on_site"]:
        # Nothing is read off a page of another site.
        return out
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
                controls.append({"role": role, "text": redact(text)[:60],
                                 "safe": is_safe_control(text)})
        except Exception:
            pass
    out["controls"] = controls
    try:
        out["password_fields"] = page.locator("input[type='password']").count()
    except Exception:
        pass
    return out


def survey(page, dwell_ms: int = 2000) -> dict:
    """What the page the person left open looks like, without following,
    pressing or downloading anything."""
    report = {"pages": [], "responses": [], "mapped": True}
    try:
        page.wait_for_timeout(dwell_ms)
    except Exception:
        pass
    report["pages"].append(_page_summary(page))
    report["listing_counts"] = dict(_summary)
    return report


_API_JS = r"""// Use the portal's authenticated GET client. Its session and the signed
// download URLs stay in the page. Only metadata and requested PDF bytes
// go back to PaperPull.
async (args) => {
  const portal = "https://kunden.openbankpay.com";
  const bucket = "prod-de-mbgdcs-documents01.s3.eu-west-1.amazonaws.com";
  const root = "cb-api-doc-manager/v4/";
  const stateKey = "__paperpullAmazonVisaV1";
  // How many documents one category is asked for at once.
  const limit = 100;
  // How long one answer of the portal's client is waited for.
  const wait = 30000;
  const fail = (message) => { throw new Error(message); };
  const token = (value) => {
    if (typeof value !== "string" || !/^[a-zA-Z0-9_-]{1,160}$/.test(value))
      fail("Invalid document or contract identifier");
    return value;
  };
  const has = (value, key) => value !== null && typeof value === "object" &&
    Object.prototype.hasOwnProperty.call(value, key);
  try {
    if (location.origin !== portal || !location.pathname.startsWith("/amazon/"))
      fail("Open the Amazon Visa portal");
    if (location.pathname.startsWith("/amazon/login")) fail("SESSION_EXPIRED");

    // The webpack runtime and module ID come from the portal's public
    // documentation chunk. Check the interface before using it so a portal
    // deployment that changes it stops the run with a clear error.
    let requireModule;
    window.webpackChunk_openbank_ui_clients?.push(
      [[Symbol("paperpull-amazonvisa")], {}, (load) => { requireModule = load; }]
    );
    const client = requireModule?.(17724)?.Tz;
    if (typeof client?.get !== "function") fail("Portal document client is unavailable");

    const get = async (endpoint, options = {}) => {
      // The portal's client takes no signal, so an answer that never comes
      // is given up on here rather than hold the run forever.
      let timer;
      const late = new Promise((resolve, reject) => {
        timer = setTimeout(() => reject(new Error("The portal did not answer in time")), wait);
      });
      let answer;
      try {
        answer = await Promise.race([client.get({endpoint, ...options}), late]);
      } finally {
        clearTimeout(timer);
      }
      const [data, meta] = Array.isArray(answer) ? answer : [];
      // A refusal reads as signed out here. For one document's ticket the
      // list read again decides whether it is (download_document).
      if (meta?.status === 401 || meta?.status === 403) fail("SESSION_EXPIRED");
      if (meta?.status !== 200 || !data || typeof data !== "object")
        fail("The portal did not return the requested document data");
      return data;
    };

    if (args.op === "download") {
      const document = window[stateKey]?.items.get(args.id);
      if (!document) fail("List documents again before downloading");
      const {id, version} = document;
      const ticket = version
        ? await get("mb-api-documents/v2/documents/:documentId/versions/:version",
                    {pathParams: {documentId: id, version}})
        : await get(root + "documents/uri/:id", {pathParams: {id}});
      const signed = version ? ticket.documentUri : ticket.uri;
      if (typeof signed !== "string") fail("The portal did not give a PDF link");
      const url = new URL(signed);
      if (url.origin !== "https://" + bucket || url.username || url.password ||
          url.hash || url.pathname === "/" || !url.searchParams.has("X-Amz-Signature"))
        fail("The PDF link is outside the permitted document store");
      const response = await fetch(url, {
        method: "GET", credentials: "omit", redirect: "error", referrerPolicy: "no-referrer",
        signal: AbortSignal.timeout(30000)
      });
      if (!response.ok) fail("The document store did not return the PDF");
      const bytes = await ppRead(response);
      if (String.fromCharCode(...bytes.subarray(0, 5)) !== "%PDF-")
        fail("The download is not a PDF");
      let binary = "";
      for (let at = 0; at < bytes.length; at += 32768)
        binary += String.fromCharCode(...bytes.subarray(at, at + 32768));
      return {ok: true, data: btoa(binary)};
    }

    if (args.op !== "collect") fail("Unknown document operation");
    const items = new Map();
    const rows = [];
    const statementIds = new Set();
    const summary = {contracts: 0, categories: 0, statements: 0, documents: 0, non_pdf: 0, without_pdf: 0};
    const position = await get("cb-api-global-position/v3/global-position");
    const cards = position.resource?.cardsInfo?.cards;
    // Whoever is signed in holds at least one card, so an answer with no
    // card in it is a list that was not read, never a list of nothing.
    if (!Array.isArray(cards) || !cards.length) fail("The portal did not list its cards");
    const contracts = new Set(cards.map(card => token(card?.cardContractId)));
    for (const contract of contracts) {
      const list = await get("cb-api-cards-contra/v1/card-contracts/:cardContractId/statements",
                             {pathParams: {cardContractId: contract}});
      if (!Array.isArray(list.elements) || list.metadata?.hasPendingRecords !== false)
        fail("The portal did not return the whole statement list");
      summary.contracts++;
      for (const row of list.elements) {
        // A statement with no PDF yet may carry both fields empty. A field
        // that is not there at all is an answer this app does not know,
        // and reading it as no PDF would leave a statement out of a list
        // still called whole.
        if (!has(row, "documentId") || !has(row, "version"))
          fail("A listed statement is missing its document fields");
        if (!row.documentId && !row.version) {
          summary.without_pdf++;
          continue;
        }
        const id = token(row.documentId);
        const version = token(row.version);
        const key = "statement:" + id + ":" + version;
        if (items.has(key)) continue;
        items.set(key, {id, version});
        statementIds.add(id);
        rows.push({item_id: key, date: row.statementDate, account: contract.slice(-4),
                   title: "Kreditkartenabrechnung", category: "Credit Card Statement"});
        summary.statements++;
      }
    }
    const available = await get(root + "categories");
    // An answer without its categories is not an empty list of them.
    if (!Array.isArray(available.categories)) fail("The portal did not list its document categories");
    for (const category of new Set(available.categories)) {
      const list = await get(root + "documents", {queryParams: {categories: [token(category)], limit}});
      // Both the documents and their size must be there and agree.
      if (!Array.isArray(list.documents) || !Number.isSafeInteger(list.size) ||
          list.size !== list.documents.length)
        fail("The portal did not return the whole document category");
      // The size may count only the documents that came back, so an answer
      // holding as many as were asked for may have been cut there.
      if (list.documents.length >= limit)
        fail("A document category reached the most one answer holds");
      summary.categories++;
      for (const row of list.documents) {
        if (typeof row.fileExtension !== "string" || !row.fileExtension)
          fail("A listed document has no file type");
        if (!/^\.?pdf$/i.test(row.fileExtension)) {
          summary.non_pdf++;
          continue;
        }
        const id = token(row.id);
        const key = "document:" + id;
        if (items.has(key) || statementIds.has(id)) continue;
        const contract = category === "cat_contratos";
        items.set(key, {id});
        rows.push({item_id: key, date: row.date, kind: category,
                   title: contract ? "Vertragsinformation" : "Dokument"});
        summary.documents++;
      }
    }
    window[stateKey] = {items};
    return {ok: true, rows, summary};
  } catch (error) {
    if (ppRefused(error)) throw error;
    const message = String(error?.message || "");
    // Only our own fixed error messages leave the page. Fetch failures can
    // include a signed address, and the portal can include account details.
    const fixed = [
      "Invalid document or contract identifier", "Open the Amazon Visa portal",
      "Portal document client is unavailable", "The portal did not return the requested document data",
      "List documents again before downloading", "The portal did not give a PDF link",
      "The PDF link is outside the permitted document store", "The document store did not return the PDF",
      "The download is not a PDF", "Unknown document operation", "The portal did not list its cards",
      "The portal did not return the whole statement list", "The portal did not list its document categories",
      "The portal did not return the whole document category", "A listed document has no file type",
      "A listed statement is missing its document fields", "The portal did not answer in time",
      "A document category reached the most one answer holds"
    ];
    return {ok: false, expired: message === "SESSION_EXPIRED",
            error: fixed.includes(message) ? message : "The portal document request failed"};
  }
}
"""
_cache = None
_summary = {}


def _execute(page, operation, stop=ListStopped, **values):
    """The in-page bridge's answer to one operation. A signed-out answer
    raises SessionExpired, and any other failure raises `stop`, ListStopped
    for the list and NoFile for one document's download."""
    if not is_safe_url(page.url or ""):
        raise SessionExpired("Open the signed-in Amazon Visa tab.")
    try:
        result = intake.evaluate(page, _API_JS, {"op": operation, **values})
    except intake.TooLarge:
        if stop is ListStopped:
            raise ListStopped("The portal listing exceeded the size limit") from None
        raise
    except Exception:
        raise stop("the in-page document request did not finish") from None
    if not isinstance(result, dict):
        raise stop("the document API answered in an unexpected shape")
    if result.get("expired"):
        raise SessionExpired("Sign in to Amazon Visa again.")
    if not result.get("ok"):
        raise stop(result.get("error") or "the document API did not answer")
    return result


def goto_documents(page):
    """Reuse the portal tab the person left open. The list answering, never
    the address, proves a sign-in.

    Reading from the open tab keeps the session the person just opened. A
    tab of the run's own may navigate.
    """
    if is_safe_url(page.url or ""):
        return not looks_signed_out(page)
    try:
        if (page.url or "").split("?", 1)[0].rstrip("/") != URLS["documents"]:
            page.goto(URLS["documents"], wait_until="domcontentloaded", timeout=30000)
        return not looks_signed_out(page)
    except Exception:
        return False


def ensure_statements(page):
    return goto_documents(page)


def answers_its_list(page):
    listed_rows(page, fresh=True)
    return True


def classify(kind, title=""):
    if kind == "cat_contratos":
        return "Contract Information"
    text = str(kind or "") + " " + str(title or "")
    if re.search(r"steuer|tax", text, re.I):
        return "Tax Document"
    if re.search(r"abrechnung|statement", text, re.I):
        return "Credit Card Statement"
    if re.search(r"mitteilung|nachricht|message", text, re.I):
        return "Message"
    return "Other Document"


def filed_category(row):
    return row.get("category") or classify(row.get("kind"), row.get("title"))


def _last_sunday(year: int, month: int) -> int:
    day = 31
    while datetime(year, month, day).weekday() != 6:
        day -= 1
    return day


def _berlin(when):
    """A moment in Berlin time, by the EU rule, summer time from 01:00 UTC
    on the last Sunday of March to 01:00 UTC on the last Sunday of October.
    Worked out here because Windows' Python has no time zone data without
    an extra package."""
    u = when.astimezone(timezone.utc)
    start = datetime(u.year, 3, _last_sunday(u.year, 3), 1, tzinfo=timezone.utc)
    end = datetime(u.year, 10, _last_sunday(u.year, 10), 1, tzinfo=timezone.utc)
    return u + timedelta(hours=2 if start <= u < end else 1)


_STAMP_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})[Tt ](\d{2}:\d{2}(?::\d{2})?)(\.\d+)?([Zz]|[+-]\d{2}:?\d{2})$")


def parse_date(value):
    """A day as the portal means it, YYYY-MM-DD, or "" when it names none.

    A date that comes as a moment with a zone is read as its day in Berlin,
    since one stamped after midnight there is the day before in UTC. The
    day is in each document's identity and its file name. A plain day is
    taken as it is."""
    value = str(value or "").strip()
    stamp = _STAMP_RE.match(value)
    if stamp:
        zone = stamp.group(4)
        if zone in ("Z", "z"):
            zone = "+00:00"
        elif ":" not in zone:
            zone = zone[:3] + ":" + zone[3:]
        try:
            when = datetime.fromisoformat(stamp.group(1) + "T" + stamp.group(2) + zone)
            return _berlin(when).strftime("%Y-%m-%d")
        except (ValueError, OverflowError):
            return ""
    for fmt, pattern in (("%Y-%m-%d", r"^\d{4}-\d{2}-\d{2}(?!\d)"),
                         ("%d.%m.%Y", r"^\d{2}\.\d{2}\.\d{4}(?!\d)"),
                         ("%Y%m%d", r"^\d{8}(?!\d)")):
        match = re.match(pattern, value)
        if not match:
            continue
        try:
            return datetime.strptime(match.group(), fmt).date().isoformat()
        except ValueError:
            continue
    return ""


def _normalize(row):
    date = parse_date(row.get("date"))
    if not date or not row.get("title") or not row.get("item_id"):
        raise ListStopped("a listed document has no readable date, title or identity")
    account = re.sub(r"\W", "", str(row.get("account") or ""))[-4:]
    return {"title": re.sub(r"\s+", " ", row["title"]).strip(), "date": date,
            "account": "Vertrag " + account if account else "",
            "category": filed_category(row), "item_id": row["item_id"],
            "client_id": "", "href": URLS["documents"]}


def listed_rows(page, config=None, fresh=False):
    global _cache, _summary
    try:
        present = page.evaluate("Boolean(window.__paperpullAmazonVisaV1?.items)")
    except Exception:
        present = False
    if (fresh or not _cache or _cache[0] is not page or not present
            or time.monotonic() - _cache[1] > 120):
        result = _execute(page, "collect")
        raw = result.get("rows")
        if not isinstance(raw, list):
            raise ListStopped("the document list could not be read")
        rows = [_normalize(row) for row in raw]
        if len({r["item_id"] for r in rows}) != len(rows):
            raise ListStopped("the document list repeats an identity")
        _summary = result.get("summary") or {}
        _cache = (page, time.monotonic(), rows)
    wanted = set((config or {}).get("document_types") or storage_categories())
    return [dict(row) for row in _cache[2] if row["category"] in wanted]


def storage_categories():
    return ["Credit Card Statement", "Tax Document", "Contract Information", "Message", "Other Document"]


def collect_documents(page, keep=None, config=None):
    rows = listed_rows(page, config, fresh=True)
    return sorted((r for r in rows if keep is None or keep(r["date"][:4])),
                  key=lambda row: row["date"], reverse=True)


def undated():
    # An unreadable date stops this provider's whole listing.
    return 0


def resolve_item(page, title, date, account, occurrence=0, item_id="", *,
                 category, number_rows, twins=1, config=None):
    """The listed row this document is, by its title, date, contract and
    kind and the number Discover gave it among documents alike. An id the
    list no longer shows is never asked for, since the page holds a
    download's ticket only for the rows it listed."""
    rows = listed_rows(page, config)
    numbers = number_rows(rows)
    alike = [i for i, row in enumerate(rows) if
             (row["title"], row["date"], row["account"], filed_category(row)) ==
             (title, date, account, category)]
    mine = [i for i in alike if numbers[i][0] == occurrence]
    if not mine:
        if item_id and any(row["item_id"] == item_id for row in rows):
            raise NotToldApart("Its stored id is now another document's.")
        raise NotToldApart("The list no longer shows this document.")
    if len(mine) != 1:
        raise NotToldApart("The list does not uniquely identify this document.")
    index = mine[0]
    row = rows[index]
    if not numbers[index][1] or (row["item_id"] != item_id and len(alike) != twins):
        raise NotToldApart("Documents alike cannot be safely matched.")
    return row


def download_document(page, title, date, out_path, occurrence=0, item_hint="",
                      client_hint="", account="", *, category, number_rows,
                      twins=1, config=None):
    """Save one document, and answer the id its bytes came from, or "" when
    the portal gave no PDF for it, which fails that document alone. Which
    row is its own is resolve_item's to say. Whatever the download answers,
    a list that answers as signed out raises SessionExpired and a list that
    cannot be read again ListStopped, since both hold for every document
    after it."""
    row = resolve_item(page, title, date, account, occurrence, item_id=item_hint,
                       category=category, number_rows=number_rows, twins=twins, config=config)
    try:
        result = _execute(page, "download", stop=NoFile, id=row["item_id"])
        data = intake.decode(result["data"], validate=True)
        why = "" if data.startswith(b"%PDF-") else "not a PDF (%d bytes)" % len(data)
    except (NoFile, SessionExpired, intake.TooLarge, ValueError, KeyError, TypeError) as e:
        # By its type and kind, since what an answer or an error says can
        # carry the portal's words.
        why = "%s, %s" % (type(e).__name__, failure.error_kind(e))
    if why:
        log.warning("no PDF for one %s of %s: %s", category, date, why)
        # A 401 or 403 on one document's ticket, a sign-in page served in
        # its place, or a file that is not a PDF says nothing this app can
        # tell of the session, since the portal may refuse one document
        # alone. The list is the proof, so it is read again here, and an
        # answer as signed out (SessionExpired) or a list that stops
        # (ListStopped) ends the run with nothing recorded against this
        # document. Only a list that still answers makes this one
        # document's failure.
        listed_rows(page, config, fresh=True)
        return ""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(data)
    return row["item_id"]
