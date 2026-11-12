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
    if (method === "POST") return !u.search &&
      ([box + "eingang", box + "ausgang", box + "papierkorb"].includes(u.pathname) ||
       (args.open_conversations === true && u.pathname === box + "leseUndVermerkeMitId"));
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
      if ([401, 403].includes(response.status)) fail("SESSION_EXPIRED");
      if (!response.ok) fail("Postbox returned HTTP " + response.status);
      if (pdf) {
        const bytes = new Uint8Array(await response.arrayBuffer());
        if (bytes.length > 100 * 1024 * 1024) fail("PDF exceeds size limit");
        if (String.fromCharCode(...bytes.slice(0, 5)) !== "%PDF-") fail("download did not return a PDF");
        let binary = "";
        for (let i = 0; i < bytes.length; i += 32768) binary += String.fromCharCode(...bytes.subarray(i, i + 32768));
        return btoa(binary);
      }
      if (!(response.headers.get("content-type") || "").includes("json")) fail("Postbox did not return JSON");
      const data = await response.json();
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
    if (auth.hatMehrereKundenverbindungen || (auth.stammNrsDisplay?.length || 0) > 1)
      fail("multiple customer relationships require a mapped read-only context switch");
    const items = new Map(), rows = [], unique = new Map(), conversations = [];
    const summary = {pages: 0, listed: 0, pdfs: 0, non_pdf_messages: 0, folders: 0,
      opened_conversations: 0, sent_files_without_download: 0};
    const addPdf = (row, folder) => {
      if (!row.dokumentId || !row.fileName || !row.erhaltenAm) fail("incomplete PDF metadata");
      const id = String(row.dokumentId);
      const title = String(row.inhalt || row.fileName).replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();
      const metadata = {title, date: row.erhaltenAm, kind: row.kategorie || "",
        account: "", source: folder, item_id: id};
      const signature = JSON.stringify([title, row.erhaltenAm, row.kategorie]);
      // The same bank download id can be referenced under different
      // conversation subjects/dates. Keep its first direct list entry.
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
          const rowId = String(row.id || row.selectionId || "");
          if (!rowId || ids.has(rowId)) fail("Postbox page repeated an entry");
          ids.add(rowId); summary.listed++;
          if (row.pdfFile) addPdf(row, folder);
          else summary.non_pdf_messages++;
          if (row.anzahlKorrespondenz > 1 || !row.pdfFile) {
            if (args.open_conversations !== true) {
              if (row.anzahlKorrespondenz > 1) fail("PDF conversation attachments require --allow-mark-read (the bank marks conversations read)");
              continue;
            }
            conversations.push({row, rowId, folder});
          }
        }
        if (ids.size > total) fail("Postbox count is smaller than its list");
        if (page >= Math.max(0, pages - 1)) {
          if (ids.size !== total) fail("Postbox history stopped before its total");
          finished = true; break;
        }
      }
      if (!finished) fail("Postbox history reached the page limit");
    }
    // Prefer direct document metadata even when an earlier conversation
    // also references that PDF. Open conversations only after all root
    // lists have been checked, and only with the explicit opt-in above.
    for (const {row, rowId, folder} of conversations) {
      const detail = await ask(box + "leseUndVermerkeMitId", {id: rowId});
      summary.opened_conversations++;
      if (!Array.isArray(detail.konversation?.konversationen)) fail("Postbox conversation is incomplete");
      if (detail.konversation.konversationen.length < (row.anzahlKorrespondenz || 1)) fail("Postbox conversation is incomplete");
      // The public client renders these as names only, without links.
      if (detail.gesendeteDateien !== undefined && !Array.isArray(detail.gesendeteDateien)) fail("Postbox sent attachment format is not mapped");
      summary.sent_files_without_download += detail.gesendeteDateien?.length || 0;
      for (const part of detail.konversation.konversationen) {
        if (!part.filePDF || unique.has(String(part.dokumentId))) continue;
        addPdf({dokumentId: part.dokumentId, fileName: part.fileName,
          erhaltenAm: part.versandtAm || row.erhaltenAm,
          inhalt: (detail.konversation.betreff || row.inhalt || "Mitteilung") + " - " + part.fileName,
          kategorie: ""}, folder);
      }
    }
    window[stateKey] = {items};
    return {ok: true, rows, summary};
  } catch (error) {
    const message = String(error?.message || "");
    const safe = /^(SESSION_EXPIRED|refused request|Postbox |invalid Postbox|download did not|PDF exceeds|document must|unknown operation|multiple customer|PDF conversation|incomplete PDF|one PDF)/;
    return {ok: false, expired: message === "SESSION_EXPIRED",
      error: safe.test(message) ? message : "Postbox request failed"};
  }
}
