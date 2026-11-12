// Executed inside the signed-in page. Session JWTs and download tickets
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
        const bytes = new Uint8Array(await response.arrayBuffer());
        if (bytes.length > 100 * 1024 * 1024) fail("PDF exceeds size limit");
        if (String.fromCharCode(...bytes.slice(0, 5)) !== "%PDF-") fail("download did not return a PDF");
        let binary = "";
        for (let n = 0; n < bytes.length; n += 32768) binary += String.fromCharCode(...bytes.subarray(n, n + 32768));
        return btoa(binary);
      }
      if (!(response.headers.get("content-type") || "").includes("json")) fail("document API did not return JSON");
      return await response.json();
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
                     customers: 0, pages: 0};
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
          if (!file?.binaryDataId || !file.filename || !jwt) fail("incomplete attachment metadata");
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
            ids.add(id); addMessage(m, result.jwt);
            if (m.anzahlNachrichtenAusKorrespondenz > 1) {
              const thread = await ask(messages + "messageThread/" + segment(id), undefined, {jwtDocId: result.jwt});
              const chain = array(thread.korrespondenznachrichten, "message thread");
              if (chain.length < m.anzahlNachrichtenAusKorrespondenz) fail("message thread is incomplete");
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
    // Return only our fixed messages, never a URL, a payload or a token.
    const message = String(error?.message || "");
    const safe = /^(SESSION_EXPIRED|invalid identifier|refused request|document |message |no accessible|unsupported customer|incomplete |missing or invalid|download did not|PDF exceeds|unknown operation|customers is|messages is)/;
    return {ok: false, expired: message === "SESSION_EXPIRED",
      error: safe.test(message) ? message : "document request failed"};
  }
}
