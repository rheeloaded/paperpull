"""Renault Bank direkt's Atruvia Postfach API.

Read-only lists cover every bank customer, Posteingang, Archiv and the PDF
attachments of incoming and sent messages (older correspondence in threads
included). No control is pressed. The bank's separate status, archive and
delete endpoints are never called. A PDF download uses the observed
documentUpload and ticket sequence, which stages an existing document for
download and uploads no file. Business JWTs and tickets are used only
inside the signed-in page.
"""
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

log = logging.getLogger("renaultbank_docs.site")

# Every host this app will read from. Anything else is refused.
ALLOWED_HOSTS = ("banking.renault-bank-direkt.de",)

BASE = "https://banking.renault-bank-direkt.de"
URLS = {
    "home": BASE + "/services_cloud/portal/",
    # login.bat opens this, the sign-in address the request names (#172).
    "login": BASE + "/services_cloud/portal/",
    # The account holder supplied the Postfach's exact route (#172).
    "documents": BASE + "/services_cloud/portal/webcomp/epostfach/postfach",
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
LOGIN_URL_MARKERS = ["/services_auth/", "/portal-oauth/", "/login", "/logout"]

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
                      else "(not on banking.renault-bank-direkt.de)")
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


_API_JS = r"""// Executed inside the signed-in page. Session JWTs and download tickets
// stay here; only document metadata and requested PDF bytes leave the page.
async (args) => {
  const origin = "https://banking.renault-bank-direkt.de";
  const proxy = "/services_cloud/portal/proxy-gateway/serviceproxy/";
  const core = proxy + "epostfach-core-v1/rest/de.fiduciagad.epostfach.core.api.v1.CoreApi/";
  const messages = proxy + "epostfach-kkm-nachricht-v1/rest/de.fiduciagad.epostfach.kkm.nachricht.api.v1.KKMNachrichtApi/";
  const fileRoot = "/services_cloud/portal/datasharing/ticket/download/";
  const stateKey = "__paperpullRenaultDocumentsV1";
  const fail = (reason) => { throw new Error(reason); };
  const segment = (id) => {
    if (typeof id !== "string" || !id || id.length > 2048) fail("invalid identifier");
    return encodeURIComponent(id);
  };
  const allowed = (path, method) => {
    const p = new URL(path, origin);
    if (p.origin !== origin || p.username || p.password || p.hash) return false;
    if (method === "GET") {
      if ([core + "profile/active", core + "liefereBerechtigteKunden",
           core + "datasharing/downloadTicket"].includes(p.pathname)) return true;
      if (p.pathname.startsWith(fileRoot)) return p.pathname.slice(fileRoot.length).length > 0 &&
        !p.pathname.slice(fileRoot.length).includes("/") &&
        [...p.searchParams.keys()].every(k => ["downloadticket", "directDownload", "requester"].includes(k));
      if (p.pathname.startsWith(messages)) return /^(messageThread\/[^/]+|messageAttachmentDownload\/[^/]+\/[^/]+)$/.test(p.pathname.slice(messages.length));
    }
    return method === "POST" && (p.pathname === core + "liefereDokumenteZuKunden" ||
      p.pathname === core + "datasharing/documentUpload" ||
      (p.pathname.startsWith(messages) && /^(messages|messageCount)\/[^/]+$/.test(p.pathname.slice(messages.length))));
  };
  const ask = async (path, body, extra = {}, pdf = false) => {
    const method = body === undefined ? "GET" : "POST";
    if (location.origin !== origin || !allowed(path, method)) fail("refused request outside the document API");
    // Use the same public PortalContext service as the Postfach's own
    // HTTP interceptor. It refreshes an expiring access cookie within the
    // existing session, without exposing a token or attempting a login.
    const security = window.okpGlobal?.portalContext?.getSecurityService?.();
    if (!security?.ensureTokenForApiCall) fail("document session service is unavailable");
    const expiry = security.getSessionExpiry?.();
    if (typeof expiry === "number" && expiry > 0 && expiry <= Date.now()) fail("SESSION_EXPIRED");
    await new Promise((resolve, reject) => {
      const wait = setTimeout(() => reject(new Error("SESSION_EXPIRED")), 30000);
      const ready = () => { clearTimeout(wait); resolve(); };
      const failed = () => { clearTimeout(wait); reject(new Error("SESSION_EXPIRED")); };
      try {
        const result = security.ensureTokenForApiCall();
        if (result?.subscribe) result.subscribe({complete: ready, error: failed});
        else if (result?.then) result.then(ready, failed);
        else failed();
      } catch { failed(); }
    });
    const headers = {"Accept": pdf ? "application/pdf" : "application/json", "X-VP-App-Locale": "de-DE", ...extra};
    if (body !== undefined) headers["Content-Type"] = "application/json";
    const timer = new AbortController();
    const limit = setTimeout(() => timer.abort(), 30000);
    let response;
    try {
      response = await fetch(path, {method, headers, credentials: "same-origin",
        mode: "same-origin", redirect: "error", signal: timer.signal,
        ...(body === undefined ? {} : {body: JSON.stringify(body)})});
      if ([401, 403].includes(response.status)) fail("SESSION_EXPIRED");
      if (!response.ok) fail("document API returned HTTP " + response.status);
      if (pdf) {
        const bytes = await ppRead(response);
        if (bytes.length > 100 * 1024 * 1024) fail("PDF exceeds size limit");
        if (String.fromCharCode(...bytes.slice(0, 5)) !== "%PDF-") fail("download did not return a PDF");
        let binary = "";
        for (let n = 0; n < bytes.length; n += 32768) binary += String.fromCharCode(...bytes.subarray(n, n + 32768));
        return btoa(binary);
      }
      if (!(response.headers.get("content-type") || "").includes("json")) fail("document API did not return JSON");
      return await ppJson(response);
    } finally { clearTimeout(limit); }
  };
  const array = (value, what) => {
    if (!Array.isArray(value)) fail(what + " is not a list");
    return value;
  };
  const count = (value) => {
    if (!Number.isSafeInteger(value) || value < 0) fail("missing or invalid document count");
    return value;
  };
  try {
    if (args.op === "download") {
      const state = window[stateKey];
      const doc = state?.items.get(args.id);
      if (!doc) fail("document session must be listed again");
      let info;
      if (doc.kind === "document") {
        info = await ask(core + "datasharing/documentUpload", {
          dokumentId: doc.id, jwtDokumentListe: doc.jwt});
      } else {
        info = await ask(messages + "messageAttachmentDownload/" + segment(doc.messageId) + "/" +
          segment(btoa(doc.binaryId)), undefined, {jwtDocId: doc.jwt});
        const ticket = await ask(core + "datasharing/downloadTicket");
        info.downloadTicketId = ticket.ticketId;
      }
      if (!info?.uploadId || !info.downloadTicketId) fail("document download ticket is missing");
      const query = new URLSearchParams({downloadticket: info.downloadTicketId,
        directDownload: "true", requester: "epostfach-document-download"});
      const data = await ask(fileRoot + segment(info.uploadId) + "?" + query, undefined, {}, true);
      return {ok: true, data};
    }
    if (args.op !== "collect") fail("unknown operation");
    // Commit the in-page token map only when every list has been read.
    const items = new Map(), rows = [], rowIds = new Set();
    const summary = {documents: 0, messages: 0, attachments: 0, text_only_messages: 0,
                     other_attachments: 0, customers: 0, pages: 0};
    // An attachment is left out, and counted, only when what it says of
    // itself names another type and nothing it says names a PDF (a photo or
    // a Word file, whose download is never a PDF). Either its extension
    // field ("pdf", ".pdf", "application/pdf") or its file name saying PDF
    // takes it, and so does one that says nothing either way. A file taken
    // that is not a PDF fails alone at download, while a PDF left out would
    // be missing from a list called whole.
    const isPdf = (file) => {
      const extension = typeof file.extension === "string" ? file.extension.trim() : "";
      const name = String(file.filename).trim();
      const suffix = (name.match(/\.([a-z][a-z0-9]{1,4})$/i) || [])[1] || "";
      if (/pdf/i.test(extension) || /^pdf$/i.test(suffix)) return true;
      return !extension && !suffix;
    };
    const eligible = await ask(core + "liefereBerechtigteKunden?institut=BANK");
    const customers = array(eligible.kundeMitHauptKategorieZaehlerListe, "customers");
    if (!customers.length || !eligible.jwtKundeListe) fail("no accessible bank postbox was returned");
    const jwtCustomer = eligible.jwtKundeListe;
    const add = (id, row, source) => {
      if (rowIds.has(id)) return;
      rowIds.add(id); rows.push({...row, item_id: id}); items.set(id, source);
    };
    for (const entry of customers) {
      const customer = entry.kunde;
      if (!customer?.kundenId || customer.verbundkunde) fail("unsupported customer or linked-provider postbox");
      // Read as false when missing, it left every message of this customer
      // out of a list still called whole.
      if (typeof customer.nachrichtenBerechtigt !== "boolean") fail("incomplete customer metadata");
      const customerId = String(customer.kundenId);
      summary.customers++;
      for (const category of ["POSTEINGANG", "ARCHIV"]) {
        let offset = "", expected, finished = false;
        const cursors = new Set(), ids = new Set();
        for (let page = 0; page < 200; page++) {
          const result = await ask(core + "liefereDokumenteZuKunden", {
            anzahlDokumente: 100, dokumenteZuKundenListe: [customerId], offset,
            liefereDokumente: true, liefereUnterKategorienMitZaehler: true,
            datumVon: null, datumBis: null, dokumenteZurUnterKategorie: null,
            nurUngeleseneDokumente: false, dokTypCodeListe: null, hauptKategorie: category,
            jwtNextVersion: eligible.jwtNextVersion, jwtKundeListe: jwtCustomer});
          summary.pages++;
          const docs = array(result.dokumentListe, "documents");
          const total = count(result.dokumentenZaehler?.[category === "ARCHIV" ? "anzahlArchivGesamt" : "anzahlPosteingangGesamt"]);
          if (expected !== undefined && expected !== total) fail("document count changed while reading the list");
          expected = total;
          for (const d of docs) {
            if (!d?.dokumentId || !d.dokumentTitel || !d.erstellDatum || !result.jwtDokumentListe) fail("incomplete document metadata");
            const id = String(d.dokumentId);
            if (ids.has(id)) fail("document page repeated an entry");
            ids.add(id);
            add("document:" + id, {title: d.dokumentTitel, date: d.erstellDatum,
              kind: d.roUnterKategorie?.unterKategorieName || "", account: d.zugehoerigesObjekt?.id || customerId,
              account_type: d.zugehoerigesObjekt?.typ || "Kunde", source: category},
              {kind: "document", id, jwt: result.jwtDokumentListe});
            summary.documents++;
          }
          if (ids.size > expected) fail("document count is smaller than its list");
          if (ids.size === expected) { finished = true; break; }
          const next = result.aufsetzpunkt;
          if (!docs.length || typeof next !== "string" || !next || cursors.has(next)) fail("document history stopped before its total");
          cursors.add(next); offset = next;
        }
        if (!finished) fail("document history reached the page limit");
      }
      if (!customer.nachrichtenBerechtigt) continue;
      const visitedMessages = new Set();
      const addMessage = (m, jwt) => {
        if (!m?.docId || !m.receivedTimestamp) fail("incomplete message metadata");
        const id = String(m.docId);
        if (visitedMessages.has(id)) return;
        visitedMessages.add(id); summary.messages++;
        const attachments = array(m.attachments, "message attachments");
        if (m.attachmentCount !== undefined && m.attachmentCount !== attachments.length) fail("message attachment list is incomplete");
        if (!attachments.length) summary.text_only_messages++;
        for (const file of attachments) {
          if (!file?.filename) fail("incomplete attachment metadata");
          if (!isPdf(file)) { summary.other_attachments++; continue; }
          if (!file.binaryDataId || !jwt) fail("incomplete attachment metadata");
          const binaryId = String(file.binaryDataId);
          add("attachment:" + id + ":" + binaryId, {
            title: (m.betreff || "Mitteilung") + " - " + file.filename, date: m.receivedTimestamp,
            kind: "Mitteilung", account: customerId, account_type: "Kunde", source: "Nachrichten"},
            {kind: "attachment", messageId: id, binaryId, jwt});
          summary.attachments++;
        }
      };
      for (const filter of ["EINGANG", "GESENDET"]) {
        const base = {jwtPerson: jwtCustomer, nachrichtenFilter: filter, datumVon: null, datumBis: null};
        const total = count((await ask(messages + "messageCount/" + segment(customerId), base)).count);
        const ids = new Set();
        let offset = 0;
        while (ids.size < total) {
          if (offset >= 20000) fail("message history reached its limit");
          const result = await ask(messages + "messages/" + segment(customerId), {
            ...base, offset, anzahl: 100, sortierung: "ABSTEIGEND"});
          summary.pages++;
          const listed = array(result.korrespondenznachrichten, "messages");
          if (!listed.length || !result.jwt) fail("message history stopped before its total");
          for (const m of listed) {
            const id = String(m.docId || "");
            if (!id || ids.has(id)) fail("message page repeated an entry");
            // Read as one when missing, a thread's older messages were never
            // asked for while the list was still called whole.
            const parts = m.anzahlNachrichtenAusKorrespondenz;
            if (!Number.isSafeInteger(parts) || parts < 0) fail("incomplete message metadata");
            ids.add(id); addMessage(m, result.jwt);
            if (parts > 1) {
              const thread = await ask(messages + "messageThread/" + segment(id), undefined, {jwtDocId: result.jwt});
              const chain = array(thread.korrespondenznachrichten, "message thread");
              if (chain.length < parts) fail("message thread is incomplete");
              for (const part of chain) addMessage(part, thread.jwt);
            }
          }
          offset += listed.length;
          if (ids.size > total) fail("message count is smaller than its list");
        }
        if (count((await ask(messages + "messageCount/" + segment(customerId), base)).count) !== total) fail("message count changed while reading");
      }
    }
    window[stateKey] = {items};
    return {ok: true, rows, summary};
  } catch (error) {
    if (ppRefused(error)) throw error;
    // Return only our fixed messages, never a URL, a payload or a token.
    const message = String(error?.message || "");
    const safe = /^(SESSION_EXPIRED|invalid identifier|refused request|document |message |no accessible|unsupported customer|incomplete |missing or invalid|download did not|PDF exceeds|unknown operation|customers is|messages is)/;
    return {ok: false, expired: message === "SESSION_EXPIRED",
      error: safe.test(message) ? message : "document request failed"};
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
        raise SessionExpired("Open the signed-in Renault Bank direkt tab.")
    try:
        result = intake.evaluate(page, _API_JS, {"op": operation, **values})
    except intake.TooLarge:
        raise
    except Exception:
        raise stop("the in-page document request did not finish") from None
    if not isinstance(result, dict):
        raise stop("the document API answered in an unexpected shape")
    if result.get("expired"):
        raise SessionExpired("Sign in to Renault Bank direkt again.")
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
    """The category a listed row's document is recorded under. The row's
    own, or the one its kind and title name, except that an Other Document
    whose title says it is a statement is recorded as one
    (renaultbank_docs._record_statement_doc), as DKB's is. Discover numbers
    the rows by it and a download finds its row by it, so the two read a
    row as the record holds it. classify reads such a title as a Statement
    already, so only a row that arrives as an Other Document needs this."""
    category = row.get("category") or classify(row.get("kind"), row.get("title"))
    title = re.sub(r"\s+", " ", str(row.get("title") or "")).strip() or "Statement"
    if category == "Other Document" and re.search(r"statement|kontoauszug", title, re.I):
        return "Statement"
    return category


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
        present = page.evaluate("Boolean(window.__paperpullRenaultDocumentsV1?.items)")
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
            # Not surely another document. The bank may have changed the
            # row's title or kind, so this says only what differs.
            raise NotToldApart("Its stored id now names a row of another kind, title, date or account.")
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
