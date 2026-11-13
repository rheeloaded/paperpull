"""Read the BBVA web Postfach and existing PDF attachments."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
from typing import Optional
from urllib.parse import urlsplit


from paperpull_core import failure
from paperpull_core import intake
from paperpull_core.controls import SETTINGS_CONTROL_RE, AUTH_CONTROL_RE
# Everything on its way into a diagnostic file goes through here.
from paperpull_core.redact import redact, set_private_words  # noqa: F401
from paperpull_core.urls import is_safe_url as _host_allows

log = logging.getLogger("bbva_docs.site")

# Every host this app will read from. Anything else is refused.
ALLOWED_HOSTS = ("www.bbva.de", "web.bbva.de")

BASE = "https://web.bbva.de"
URLS = {
    "home": BASE + "/index.html",
    "login": "https://www.bbva.de/nimbus/signin.html",
    "documents": BASE + "/index.html#inbox/messages",
}


class SessionExpired(RuntimeError):
    """The document API needs the user to sign in again."""


class ListStopped(RuntimeError):
    """A list could not be read whole. A run that reads the list again while
    it downloads stops once with the list unread
    (listing.read_again_stopped), since every document after it reads the
    same list."""


class NoFile(RuntimeError):
    """The bank lists a document and gives no PDF for it, an HTTP error for
    that one file, no download ticket, or an answer that is not a PDF. Only
    that document fails, and the run goes on to the next, as DKB's does. It
    was ListStopped, which ended every run at the first such document, and
    since runs go newest first nothing older was ever saved."""


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
LOGIN_URL_MARKERS = ["/nimbus/signin.html", "/login", "/logout"]

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
                      else "(not on web.bbva.de)")
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


_API_JS = r"""// Use the same client as the BBVA Postfach. Only GETs to the observed
// list, message and PDF endpoints are issued. Session headers stay here.
async (args) => {
  const portal = "https://web.bbva.de";
  const api = "https://de-net.bbva.com";
  const listPath = "/notifications/v0/virtual-mails";
  const stateKey = "__paperpullBBVAPostfachV1";
  const segment = value => {
    if (typeof value !== "string" || !/^[A-Za-z0-9_-]{1,160}$/.test(value))
      throw new Error("Invalid document identifier");
    return value;
  };
  const fail = message => { throw new Error(message); };
  try {
    if (location.origin !== portal || location.pathname !== "/index.html")
      fail("Open the signed-in BBVA portal");
    const assets = performance.getEntriesByType("resource").map(entry => new URL(entry.name));
    const module = assets.find(url => url.origin === portal && !url.search &&
      /^\/js\/icon-gr[A-Za-z0-9_-]+\.js$/.test(url.pathname));
    if (!module) fail("The BBVA portal client is unavailable");
    const {r: client, i: init} = await import(module.pathname);
    init();
    if (typeof client?.aso?.request !== "function") fail("The BBVA portal client is unavailable");

    const allowed = url => url.origin === api && !url.username && !url.password && !url.hash &&
      (url.pathname === listPath ||
        (!url.search && /^\/(?:announcements\/V01\/[A-Za-z0-9_-]{1,160}\/(?:pdf\/)?|bankingVirtualMails\/V02\/[A-Za-z0-9_-]{1,160}\/bankingVirtualDocument\/)$/.test(url.pathname)));
    const ask = async (url, isDownload = false) => {
      if (!allowed(url)) fail("The Postfach request is outside the allowed endpoints");
      try {
        const answer = await client.aso.request({url: url.href, method: "GET", isDownload});
        if (answer?.xhr?.status !== 200) fail("The Postfach did not return the requested data");
        return answer.model;
      } catch (error) {
        if ([401, 403].includes(error?.xhr?.status)) fail("SESSION_EXPIRED");
        throw error;
      }
    };
    const readPdf = async model => {
      const blob = model instanceof Blob ? model : model?.tmpFile?.blob;
      if (!(blob instanceof Blob)) fail("The Postfach did not return a PDF");
      const bytes = await ppBlob(blob);
      if (String.fromCharCode(...bytes.subarray(0, 5)) !== "%PDF-")
        fail("The Postfach did not return a PDF");
      let binary = "";
      for (let at = 0; at < bytes.length; at += 32768)
        binary += String.fromCharCode(...bytes.subarray(at, at + 32768));
      return btoa(binary);
    };

    if (args.op === "download") {
      const item = window[stateKey]?.get(args.id);
      if (!item) fail("List the Postfach again before downloading");
      if (item.message) {
        const detail = await ask(new URL("/announcements/V01/" + item.message + "/", api));
        const attachment = detail?.attachments?.[item.index];
        const data = attachment?.contentFile;
        if (attachment?.name !== item.name || typeof data !== "string" || !data.startsWith("JVBERi0"))
          fail("The Postfach did not return a PDF");
        if (data.length > Math.ceil(ppLimit / 3) * 4) throw ppOver(data.length);
        return {ok: true, data};
      }
      return {ok: true, data: await readPdf(await ask(new URL(item.url), true))};
    }
    if (args.op !== "collect") fail("Unknown Postfach operation");
    const observed = assets.find(url => allowed(url) && url.pathname === listPath &&
      url.searchParams.has("customerId"));
    if (!observed) fail("Open the BBVA Postfach and wait for the list");
    const customer = observed.searchParams.get("customerId");
    let url = new URL(listPath, api);
    url.search = new URLSearchParams({customerId: customer, paginationKey: "000000000-0", pageSize: "20"});
    const seen = new Set();
    const messages = new Map();
    for (let n = 0; ; n++) {
      if (n >= 500 || seen.has(url.href)) fail("The Postfach did not return a complete list");
      seen.add(url.href);
      const model = await ask(url);
      if (!Array.isArray(model?.data)) fail("The Postfach did not return a complete list");
      for (const row of model.data) {
        const id = segment(row.id);
        if (messages.has(id)) fail("The Postfach repeated a message");
        messages.set(id, row);
      }
      const next = model.pagination?.nextPage;
      if (!next) break;
      url = new URL(next, api);
      if (url.pathname !== listPath || !allowed(url) ||
          url.searchParams.get("customerId") !== customer ||
          !url.searchParams.get("paginationKey") ||
          [...url.searchParams.keys()].some(key => !["customerId", "paginationKey", "pageSize"].includes(key)))
        fail("The next Postfach page has an unexpected address");
    }
    const items = new Map();
    const rows = [];
    const summary = {without_document: 0};
    for (const [id, row] of messages) {
      if (row.origin === "CORRESPONDENCE") {
        const doc = segment(row.document?.id);
        const key = "document:" + doc;
        if (items.has(key)) continue;
        items.set(key, {url: api + "/bankingVirtualMails/V02/" + doc + "/bankingVirtualDocument/"});
        rows.push({item_id: key, title: row.subject, date: row.sendDate});
      } else if (row.origin === "COMMUNICATION") {
        const detail = await ask(new URL("/announcements/V01/" + id + "/", api));
        if (!detail || (detail.attachments != null && !Array.isArray(detail.attachments)))
          fail("The Postfach did not return the attachments");
        const attachments = detail.attachments || [];
        let found = 0;
        for (const [index, attachment] of attachments.entries()) {
          if (typeof attachment.name !== "string" || !/\.pdf$/i.test(attachment.name)) continue;
          const key = "message:" + id + ":" + index;
          const inline = typeof attachment.contentFile === "string" && attachment.contentFile.startsWith("JVBERi0");
          if (!inline && !attachment.file) fail("A listed PDF has no download");
          const link = attachment.file ? new URL(attachment.file, api) : null;
          if (!inline && (!allowed(link) || !/^\/announcements\/V01\/[A-Za-z0-9_-]+\/pdf\/$/.test(link.pathname)))
            fail("A listed PDF has an unexpected address");
          // Keep only the message id and attachment index for inline
          // PDFs so discovery does not retain the whole archive in memory.
          items.set(key, inline ? {message: id, index, name: attachment.name} : {url: link.href});
          rows.push({item_id: key, title: row.subject + " – " + attachment.name, date: row.sendDate});
          found++;
        }
        if (!found) summary.without_document++;
      } else {
        fail("The Postfach returned an unknown message type");
      }
    }
    window[stateKey] = items;
    return {ok: true, rows, summary};
  } catch (error) {
    if (ppRefused(error)) throw error;
    const message = String(error?.message || "");
    const fixed = [
      "Invalid document identifier", "Open the signed-in BBVA portal", "The BBVA portal client is unavailable",
      "The Postfach request is outside the allowed endpoints", "The Postfach did not return the requested data",
      "The Postfach did not return a PDF", "List the Postfach again before downloading", "Unknown Postfach operation",
      "Open the BBVA Postfach and wait for the list", "The Postfach did not return a complete list",
      "The Postfach repeated a message", "The next Postfach page has an unexpected address",
      "The Postfach did not return the attachments", "A listed PDF has no download",
      "A listed PDF has an unexpected address", "The Postfach returned an unknown message type"
    ];
    return {ok: false, expired: message === "SESSION_EXPIRED",
      error: fixed.includes(message) ? message : "The BBVA Postfach request failed"};
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
        raise SessionExpired("Open the signed-in BBVA tab.")
    try:
        result = intake.evaluate(page, _API_JS, {"op": operation, **values})
    except intake.TooLarge:
        if stop is ListStopped:
            raise ListStopped("The Postfach list exceeded its size limit") from None
        raise
    except Exception:
        raise stop("the in-page document request did not finish") from None
    if not isinstance(result, dict):
        raise stop("the document API answered in an unexpected shape")
    if result.get("expired"):
        raise SessionExpired("Sign in to BBVA again.")
    if not result.get("ok"):
        raise stop(result.get("error") or "the document API did not answer")
    return result


def is_portal(url: str) -> bool:
    return (is_safe_url(url) and urlsplit(url).hostname == "web.bbva.de"
            and urlsplit(url).path == "/index.html")


def goto_documents(page):
    """Use the signed-in BBVA tab. The list request proves the session."""
    try:
        if not is_portal(page.url) or looks_signed_out(page):
            return False
        current = page.url.split("#", 1)[0]
        if page.url.partition("#")[2] != "inbox/messages":
            page.goto(current + "#inbox/messages", wait_until="domcontentloaded", timeout=15000)
        page.wait_for_function(_MAILBOX_READY, timeout=12000)
        return not looks_signed_out(page)
    except Exception:
        return False


_MAILBOX_READY = r"""
() => performance.getEntriesByType("resource").some(entry => {
  const url = new URL(entry.name);
  return url.origin === "https://de-net.bbva.com" &&
    url.pathname === "/notifications/v0/virtual-mails" && url.searchParams.has("customerId");
})
"""


def ensure_statements(page):
    return goto_documents(page)


def answers_its_list(page):
    listed_rows(page, fresh=True)
    return True


def classify(kind, title=""):
    text = str(kind or "") + " " + str(title or "")
    for category, pattern in (
        ("Tax Document", r"steuer|tax|freistellung|verlustbescheinigung|ertr[aä]gnis"),
        ("Credit Card Statement", r"kreditkarte|credit.?card|\bvisa\b"),
        ("Securities Document", r"depot|wertpapier|dividend|fonds|securit"),
        ("Statement", r"kontoausz|statement|tagesgeld|festgeld|zinsabrechnung|rechnungsabschluss"),
        ("Contract Information", r"vertrag|bedingung|vereinbarung|kontoer[öo]ffnung|contract"),
        ("Message", r"mitteilung|nachricht|information|message"),
    ):
        if re.search(pattern, text, re.I):
            return category
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
    an extra package (DKB's own)."""
    u = when.astimezone(timezone.utc)
    start = datetime(u.year, 3, _last_sunday(u.year, 3), 1, tzinfo=timezone.utc)
    end = datetime(u.year, 10, _last_sunday(u.year, 10), 1, tzinfo=timezone.utc)
    return u + timedelta(hours=2 if start <= u < end else 1)


_STAMP_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})[Tt ](\d{2}:\d{2}(?::\d{2})?)(\.\d+)?([Zz]|[+-]\d{2}:?\d{2})$")


def parse_date(value):
    """A day as the bank means it, YYYY-MM-DD, or "" when it names none.

    A message's receivedTimestamp is a UTC moment, and one received after
    midnight in Berlin is the day before in UTC, so a timestamp with a zone
    is read in Berlin time. A plain day is taken as it is."""
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
            "account": "Konto " + account if account else "",
            "category": filed_category(row), "item_id": row["item_id"],
            "client_id": "", "href": URLS["documents"]}


def listed_rows(page, config=None, fresh=False):
    global _cache, _summary
    try:
        present = page.evaluate("Boolean(window.__paperpullBBVAPostfachV1)")
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
    return ["Statement", "Credit Card Statement", "Securities Document", "Tax Document",
            "Contract Information", "Message", "Other Document"]


def collect_documents(page, keep=None, config=None):
    rows = listed_rows(page, config, fresh=True)
    return sorted((r for r in rows if keep is None or keep(r["date"][:4])),
                  key=lambda row: row["date"], reverse=True)


def undated():
    # An unreadable date stops this provider's whole listing.
    return 0


def resolve_item(page, title, date, account, occurrence=0, item_id="", *,
                 category, number_rows, twins=1, config=None):
    """DKB's identity matching, without falling back to an unlisted id,
    since the page holds a download's tokens only for the rows it listed."""
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
    the bank gave no PDF for it, which fails that document alone. Which row
    is its own is resolve_item's to say. A signed-out answer raises
    SessionExpired and a list that cannot be read again ListStopped, since
    both hold for every document after it."""
    row = resolve_item(page, title, date, account, occurrence, item_id=item_hint,
                       category=category, number_rows=number_rows, twins=twins, config=config)
    try:
        result = _execute(page, "download", stop=NoFile, id=row["item_id"])
        data = intake.decode(result["data"], validate=True)
        why = "" if data.startswith(b"%PDF-") else "not a PDF (%d bytes)" % len(data)
    except (NoFile, intake.TooLarge, ValueError, KeyError, TypeError) as e:
        # By its type and kind, since what an answer or an error says can
        # carry the bank's words.
        why = "%s, %s" % (type(e).__name__, failure.error_kind(e))
    if why:
        log.warning("no PDF for one %s of %s: %s", category, date, why)
        # A sign-in page served in place of the PDF, or a redirect to one,
        # says nothing this app can tell from a file the bank will not give.
        # The list is the proof, so it is read again here, and an answer as
        # signed out (SessionExpired) or a list that stops (ListStopped) ends
        # the run with nothing recorded against this document. Only a list
        # that still answers makes this one document's failure.
        listed_rows(page, config, fresh=True)
        return ""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(data)
    return row["item_id"]
