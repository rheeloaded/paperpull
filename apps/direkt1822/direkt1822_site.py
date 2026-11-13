"""1822direkt's Postbox, its lists and direct PDFs, through the bank's own
browser API.

Mapped from the account holder's structural capture and the public Angular
client. Only benutzerInfo, the Postbox list calls and the direct PDF
download are used. No control is pressed, and no transaction or setting is
touched. A conversation is never opened, since the one call that opens it
also marks it read at the bank. A row's own PDF is taken, and the
conversations left unopened are counted and said. Tokens are prepared
inside the signed-in page and never returned to Python.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
from typing import Optional

from paperpull_core import failure, intake
from paperpull_core.controls import SETTINGS_CONTROL_RE, AUTH_CONTROL_RE
# Everything on its way into a diagnostic file goes through here.
from paperpull_core.redact import redact, set_private_words  # noqa: F401
from paperpull_core.urls import is_safe_url as _host_allows

log = logging.getLogger("direkt1822_docs.site")

# Every host this app will read from. Anything else is refused.
ALLOWED_HOSTS = ("www.1822direkt-banking.de",)

BASE = "https://www.1822direkt-banking.de"
URLS = {
    "home": BASE + "/ng-banking/",
    "documents": BASE + "/ng-banking/banking/postbox",
    # login.bat opens this, the sign-in address the request names (#174).
    "login": BASE + "/ng-banking/login/eingabe",
}

class SessionExpired(RuntimeError):
    """The Postbox answers as signed out, so the account holder signs in
    again."""


class ListStopped(RuntimeError):
    """The Postbox list could not be read whole. A run that reads the list
    again while it downloads stops once with the list unread
    (listing.read_again_stopped), since every document after it reads the
    same list."""


class NoFile(RuntimeError):
    """The bank lists a document and gives no PDF for it, an HTTP error for
    that one file or an answer that is not a PDF. Only that document fails,
    once the list read again still answers, and the run goes on to the
    next, as Renault Bank direkt's does."""


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

# Authentication routes are never treated as a document list.
LOGIN_URL_MARKERS = ["/login", "/logout", "/anmeldung", "/abmeldung"]

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
                      else "(not on www.1822direkt-banking.de)")
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
        # Those the page draws, which is what looks_signed_out counts (#174).
        out["visible_password_fields"] = page.locator("input[type='password']").count()
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
    return report


_API_JS = r"""
// Read/list/download operations only. Executed inside the signed-in page;
// no session or CSRF token is returned to Python or persisted in run files.
async (args) => {
  const origin = "https://www.1822direkt-banking.de";
  const root = "/JOBa1822Service/api/";
  const box = root + "postboxnachricht/";
  const stateKey = "__paperpull1822PostboxV1";
  const fail = message => { throw new Error(message); };
  const allowed = (path, method) => {
    const u = new URL(path, origin);
    if (u.origin !== origin || u.username || u.password || u.hash) return false;
    // The three folder lists only. The call that opens a conversation marks
    // it read at the bank, so it is never made.
    if (method === "POST") return !u.search &&
      [box + "eingang", box + "ausgang", box + "papierkorb"].includes(u.pathname);
    if (method !== "GET") return false;
    if (u.pathname === root + "benutzerInfo") return [...u.searchParams.keys()].every(k => k === "complete");
    return u.pathname.startsWith(box + "download/") && !u.search &&
      /^[^/]+\/[^/]+$/.test(u.pathname.slice((box + "download/").length));
  };
  let auth;
  const ask = async (path, body, pdf = false) => {
    const method = body === undefined ? "GET" : "POST";
    if (location.origin !== origin || !allowed(path, method)) fail("refused request outside the Postbox API");
    // Match the portal's normal file link. The download controller rejects
    // an application/pdf-only Accept header with HTTP 406.
    const headers = {Accept: pdf ? "*/*" : "application/json"};
    if (auth?.token) headers["X-JOBA-AUTH"] = auth.token;
    if (body !== undefined) {
      headers["Content-Type"] = "application/json";
      if (!auth?.csrfToken) fail("SESSION_EXPIRED");
      headers["X-CSRF-TOKEN"] = auth.csrfToken;
    }
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 30000);
    try {
      const response = await fetch(path, {method, headers,
        credentials: "same-origin", mode: "same-origin", redirect: "error",
        signal: controller.signal, ...(body === undefined ? {} : {body: JSON.stringify(body)})});
      // A 401 or a 403 for one PDF is that file's refusal. benutzerInfo
      // answered just before it, and the list is read again in Python
      // before the document fails alone, so a session that has ended shows
      // there. A bank that refuses one PDF answers every run the same way,
      // and taken as a sign-out it ended every run at that document.
      if ([401, 403].includes(response.status))
        fail(pdf ? "download refused with HTTP " + response.status : "SESSION_EXPIRED");
      if (!response.ok) fail("Postbox returned HTTP " + response.status);
      if (pdf) {
        const bytes = await ppRead(response);
        if (String.fromCharCode(...bytes.slice(0, 5)) !== "%PDF-") fail("download did not return a PDF");
        let binary = "";
        for (let i = 0; i < bytes.length; i += 32768) binary += String.fromCharCode(...bytes.subarray(i, i + 32768));
        return btoa(binary);
      }
      if (!(response.headers.get("content-type") || "").includes("json")) fail("Postbox did not return JSON");
      const data = await ppJson(response);
      if (!Array.isArray(data.jobaMeldungen) || data.jobaMeldungen.length) fail("Postbox returned bank messages instead of a clean answer");
      return data;
    } finally { clearTimeout(timer); }
  };
  const count = value => {
    if (!Number.isSafeInteger(value) || value < 0) fail("invalid Postbox count");
    return value;
  };
  try {
    // The authenticated client also reads benutzerInfo. Only the in-page
    // request header values are retained here, never login credentials.
    auth = (await ask(root + "benutzerInfo?complete=false")).benutzerInfo;
    if (!auth?.token || !auth.csrfToken) fail("SESSION_EXPIRED");
    if (args.op === "download") {
      const document = window[stateKey]?.items.get(args.id);
      if (!document) fail("document must be listed again");
      const data = await ask(box + "download/" + encodeURIComponent(document.id) + "/" +
        encodeURIComponent(document.filename), undefined, true);
      return {ok: true, data};
    }
    if (args.op !== "collect") fail("unknown operation");
    // Read as false and as none when missing, a second customer
    // relationship would be left out of a list still called whole.
    if (typeof auth.hatMehrereKundenverbindungen !== "boolean" || !Array.isArray(auth.stammNrsDisplay))
      fail("incomplete customer metadata");
    if (auth.hatMehrereKundenverbindungen || auth.stammNrsDisplay.length > 1)
      fail("multiple customer relationships require a mapped read-only context switch");
    const items = new Map(), rows = [], unique = new Map();
    // A conversation is opened only by the call that marks it read at the
    // bank, so none is opened. threads_not_opened counts the rows of more
    // than one message, whose further attachments are not read, and
    // messages_not_opened the single messages with no PDF of their own.
    const summary = {pages: 0, listed: 0, pdfs: 0, folders: 0,
      threads_not_opened: 0, messages_not_opened: 0};
    const addPdf = (row, folder) => {
      if (!row.dokumentId || !row.fileName || !row.erhaltenAm) fail("incomplete PDF metadata");
      const id = String(row.dokumentId);
      const title = String(row.inhalt || row.fileName).replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();
      const metadata = {title, date: row.erhaltenAm, kind: row.kategorie || "",
        account: "", source: folder, item_id: id};
      const signature = JSON.stringify([title, row.erhaltenAm, row.kategorie]);
      // One bank download id can be listed in more than one folder, under
      // another subject or date. Its first row is kept.
      if (unique.has(id)) return;
      unique.set(id, signature); rows.push(metadata); items.set(id, {id, filename: String(row.fileName)}); summary.pdfs++;
    };
    const folders = ["eingang", "ausgang", ...(args.include_trash ? ["papierkorb"] : [])];
    for (const folder of folders) {
      let expected, pages, finished = false;
      const ids = new Set();
      summary.folders++;
      for (let page = 0; page < 400; page++) {
        const result = await ask(box + folder, {
          suchKriterien: {markierteNachrichten: []}, anzahlProSeite: 50,
          forceReload: true, orderBy: "erhaltenAm", orderAscending: false, seite: page});
        summary.pages++;
        if (!Array.isArray(result.postboxNachrichtListe)) fail("Postbox answer has no message list");
        const total = count(result.gesamtzahlNachrichten), pageCount = count(result.gesamtzahlSeiten);
        if (result.seite !== page) fail("Postbox returned the wrong page");
        if (expected !== undefined && (expected !== total || pages !== pageCount)) fail("Postbox counts changed while reading");
        expected = total; pages = pageCount;
        if (total > 0 && (pages < 1 || pages > 400)) fail("Postbox page limit is invalid");
        const listed = result.postboxNachrichtListe;
        if (total > 0 && listed.length === 0) fail("Postbox history stopped before its total");
        for (const row of listed) {
          const rowId = String(row?.id || row?.selectionId || "");
          if (!rowId) fail("incomplete message metadata");
          if (ids.has(rowId)) fail("Postbox page repeated an entry");
          // Read as nothing there when missing, a statement whose row had no
          // pdfFile became a message without a PDF, and a thread with no
          // count one message, in a list still called whole.
          const parts = row.anzahlKorrespondenz;
          if (typeof row.pdfFile !== "boolean" || !Number.isSafeInteger(parts) || parts < 0)
            fail("incomplete message metadata");
          ids.add(rowId); summary.listed++;
          if (row.pdfFile) addPdf(row, folder);
          if (parts > 1) summary.threads_not_opened++;
          else if (!row.pdfFile) summary.messages_not_opened++;
        }
        if (ids.size > total) fail("Postbox count is smaller than its list");
        if (page >= Math.max(0, pages - 1)) {
          if (ids.size !== total) fail("Postbox history stopped before its total");
          finished = true; break;
        }
      }
      if (!finished) fail("Postbox history reached the page limit");
    }
    window[stateKey] = {items};
    return {ok: true, rows, summary};
  } catch (error) {
    if (ppRefused(error)) throw error;
    // Return only our fixed messages, never a URL, a payload or a token.
    const message = String(error?.message || "");
    const safe = /^(SESSION_EXPIRED|refused request|Postbox |invalid Postbox|download did not|download refused|document must|unknown operation|multiple customer|incomplete )/;
    return {ok: false, expired: message === "SESSION_EXPIRED",
      error: safe.test(message) ? message : "Postbox request failed"};
  }
}
"""
_cache = None
_summary = {}


def _execute(page, operation, *, stop=ListStopped, **values):
    """The in-page bridge's answer to one operation. A signed-out answer
    raises SessionExpired, and any other failure raises `stop`, ListStopped
    for the list and NoFile for one document's download."""
    if not is_safe_url(page.url or ""):
        raise SessionExpired("Open the signed-in 1822direkt tab.")
    try:
        result = intake.evaluate(page, _API_JS, {"op": operation, **values})
    except intake.TooLarge:
        if stop is ListStopped:
            raise ListStopped("the Postbox listing exceeded the size limit") from None
        raise
    except Exception:
        raise stop("the in-page document request did not finish") from None
    if not isinstance(result, dict):
        raise stop("the document API answered in an unexpected shape")
    if result.get("expired"):
        raise SessionExpired("Sign in to 1822direkt again.")
    if not result.get("ok"):
        raise stop(result.get("error") or "the document API did not answer")
    return result


def goto_documents(page):
    """Reuse the banking tab; the list API, not its URL, proves sign-in.

    Reopening the SPA's deep link can take it through an OAuth callback.
    Reading from the existing tab avoids both that race and discarding the
    session the person just opened. A tab of the run's own may navigate.
    """
    if is_safe_url(page.url or ""):
        # A login just completed by the account holder can still be moving
        # through the authentication route when the CLI attaches.
        for attempt in range(11):
            if not looks_signed_out(page):
                return True
            if attempt < 10:
                page.wait_for_timeout(500)
        return False
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
    categories = {
        "MEGA": "Statement", "MEKA": "Credit Card Statement",
        "EWOM": "Securities Document", "EWJA": "Securities Document",
        "JSTB": "Tax Document", "ADV": "Other Document", "INFO_ADV": "Other Document",
        "ETC": "Message", "INFO": "Message", "MITT": "Message", "BRIEF": "Message",
        "MITT_BRIEF": "Message", "IPAI": "Message",
    }
    if kind in categories:
        return categories[kind]
    text = str(kind or "") + " " + str(title or "")
    for category, pattern in (
        ("Tax Document", r"steuer|tax|freistellung|verlustbescheinigung"),
        ("Credit Card Statement", r"kreditkarte|credit.?card"),
        ("Securities Document", r"depot|wertpapier|dividend|fonds"),
        ("Statement", r"kontoausz|statement|tagesgeld|festgeld|rechnungsabschluss"),
        ("Contract Information", r"vertrag|bedingung|vereinbarung|contract"),
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
    an extra package (Renault Bank direkt's own)."""
    u = when.astimezone(timezone.utc)
    start = datetime(u.year, 3, _last_sunday(u.year, 3), 1, tzinfo=timezone.utc)
    end = datetime(u.year, 10, _last_sunday(u.year, 10), 1, tzinfo=timezone.utc)
    return u + timedelta(hours=2 if start <= u < end else 1)


_STAMP_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})[Tt ](\d{2}:\d{2}(?::\d{2})?)(\.\d+)?([Zz]|[+-]\d{2}:?\d{2})$")


def parse_date(value):
    """A day as the bank means it, YYYY-MM-DD, or "" when it names none.

    A timestamp with a zone is a moment, and one after midnight in Berlin
    is the day before in UTC, so it is read in Berlin time. A plain day,
    or a time with no zone, is taken as it is written."""
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


def _with_trash(config) -> bool:
    return bool((config or {}).get("include_trash", True))


def listed_rows(page, config=None, fresh=False):
    global _cache, _summary
    try:
        present = page.evaluate("Boolean(window.__paperpull1822PostboxV1?.items)")
    except Exception:
        present = False
    if (fresh or not _cache or _cache[0] is not page or not present
            or time.monotonic() - _cache[1] > 120 or _cache[3] != _with_trash(config)):
        result = _execute(page, "collect", include_trash=_with_trash(config))
        raw = result.get("rows")
        if not isinstance(raw, list):
            raise ListStopped("the document list could not be read")
        rows = [_normalize(row) for row in raw]
        if len({r["item_id"] for r in rows}) != len(rows):
            raise ListStopped("the document list repeats an identity")
        _summary = result.get("summary") or {}
        _cache = (page, time.monotonic(), rows, _with_trash(config))
    wanted = set((config or {}).get("document_types") or storage_categories())
    return [dict(row) for row in _cache[2] if row["category"] in wanted]


def not_opened() -> tuple:
    """The last listing's conversations this app did not open, as (threads,
    messages). A thread is a row of more than one message, whose own PDF is
    taken and whose further attachments are not read. A message is a single
    one with no PDF of its own. Opening either marks it read at the bank."""
    return (int(_summary.get("threads_not_opened") or 0),
            int(_summary.get("messages_not_opened") or 0))


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
    since the page holds a download's file name only for the rows it
    listed."""
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
    is its own is resolve_item's to say. A list that answers as signed out
    raises SessionExpired and a list that cannot be read again ListStopped,
    since both hold for every document after it."""
    row = resolve_item(page, title, date, account, occurrence, item_id=item_hint,
                       category=category, number_rows=number_rows, twins=twins, config=config)
    try:
        result = _execute(page, "download", stop=NoFile, id=row["item_id"])
        data = intake.decode(result["data"], validate=True)
        why = "" if data.startswith(b"%PDF-") else "not a PDF (%d bytes)" % len(data)
    except (NoFile, intake.TooLarge, ValueError, KeyError, TypeError) as e:
        # By its type and kind, since what an answer or an error says can
        # carry the bank's words. A 401 or a 403 for this one file arrives
        # here as NoFile (the page script's download refused), and
        # benutzerInfo answering as signed out first raises SessionExpired,
        # which stops the run.
        why = "%s, %s" % (type(e).__name__, failure.error_kind(e))
    if why:
        log.warning("no PDF for one %s of %s: %s", category, date, why)
        # A sign-in page served in place of the PDF, or a refusal of it,
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
