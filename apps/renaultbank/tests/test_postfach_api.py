"""Exercise the actual in-page bridge with invented JSON API answers.

No account is accessed. Node provides fetch stand-ins; the production bridge
does all pagination, thread walking, ticketing and PDF checks itself.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
import renaultbank_site as site


HARNESS = r"""
const fs = require('fs');
const bridge = eval('(' + fs.readFileSync(process.argv[1], 'utf8') + ')');
const mode = process.argv[2];
global.window = {};
global.location = {origin: 'https://banking.renault-bank-direkt.de'};
const requests = [];
const doc = (id) => ({dokumentId:id, dokumentTitel:'Kontoauszug ' + id,
 erstellDatum:'2026-03-31', roUnterKategorie:{unterKategorieName:'Kontoauszug'},
 zugehoerigesObjekt:{id:'DE00111122223333444455',typ:'IBAN'}});
const attachment = (id) => ({binaryDataId:id,filename:id+'.pdf',extension:'pdf'});
const message = (id, attachments=[], extra={}) => ({docId:id,
 receivedTimestamp:'2026-02-28T12:00:00Z',betreff:'Information',attachments,
 attachmentCount:attachments.length,anzahlNachrichtenAusKorrespondenz:1,...extra});
global.fetch = async (path, options) => {
 if (options.redirect !== 'error' || options.mode !== 'same-origin' || options.credentials !== 'same-origin')
   throw new Error('unsafe fetch options');
 const body = options.body ? JSON.parse(options.body) : null;
 requests.push({path,method:options.method,offset:body?.offset});
 let data;
 if (path.endsWith('liefereBerechtigteKunden?institut=BANK')) {
  if (mode==='expired') return {status:401,ok:false};
  data={jwtKundeListe:'INVENTED_CUSTOMER_JWT',jwtNextVersion:true,
   kundeMitHauptKategorieZaehlerListe:[{kunde:{kundenId:'9999',nachrichtenBerechtigt:true}}]};
 } else if (path.endsWith('liefereDokumenteZuKunden')) {
  if (body.jwtKundeListe !== 'INVENTED_CUSTOMER_JWT') throw new Error('missing customer token');
  const arch=body.hauptKategorie==='ARCHIV';
  const first=!body.offset;
  data={dokumentListe:[doc(arch?'archived':first?'recent':'older')],
   dokumentenZaehler:{anzahlPosteingangGesamt:2,anzahlArchivGesamt:1},
   jwtDokumentListe:'INVENTED_DOCUMENT_JWT'};
  if (!arch && first && mode!=='missing-cursor') data.aufsetzpunkt='next-page';
  if (!arch && !first && mode==='repeated-page') data.dokumentListe=[doc('recent')];
  if (mode==='bad-date') data.dokumentListe[0].erstellDatum='bad';
 } else if (path.includes('/messageCount/')) data={count:body.nachrichtenFilter==='EINGANG'?2:0};
 else if (path.includes('/messages/')) {
  data={korrespondenznachrichten:body.offset===0 ?
   [message('m1',[attachment('a1')],{anzahlNachrichtenAusKorrespondenz:2})] : [message('m2')],
   jwt:'INVENTED_MESSAGE_JWT'};
 } else if (path.includes('/messageThread/')) {
  if(options.headers.jwtDocId!=='INVENTED_MESSAGE_JWT') throw new Error('missing message token');
  data={jwt:'INVENTED_THREAD_JWT',korrespondenznachrichten:
   [message('m1',[attachment('a1')]),message('old',[attachment('a2')])]};
  if(mode==='short-thread') data.korrespondenznachrichten=[];
 } else if(path.endsWith('datasharing/documentUpload')) {
  if(body.jwtDokumentListe!=='INVENTED_DOCUMENT_JWT') throw new Error('missing document token');
  data={uploadId:'INVENTED_UPLOAD',downloadTicketId:'INVENTED_TICKET'};
 } else if(path.includes('/messageAttachmentDownload/')) {
  if(!options.headers.jwtDocId) throw new Error('missing attachment token');
  data={uploadId:'INVENTED_ATTACHMENT'};
 } else if(path.endsWith('datasharing/downloadTicket')) data={ticketId:'INVENTED_TICKET'};
 else if(path.includes('/ticket/download/')) {
  const bytes=Buffer.from(mode==='not-pdf'?'<html>sign in</html>':'%PDF-1.4\nINVENTED PDF');
  return {status:200,ok:true,headers:{get:()=> 'application/pdf'},
   arrayBuffer:async()=>bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength)};
 } else throw new Error('unexpected endpoint');
 return {status:200,ok:true,headers:{get:()=> 'application/json'},json:async()=>data};
};
(async()=>{
 const collected=await bridge({op:'collect'});
 let downloaded;
 if(collected.ok && ['download','attachment','not-pdf'].includes(mode)){
  const selected=collected.rows.find(r=>r.item_id.startsWith(mode==='attachment'?'attachment:old':'document:'));
  downloaded=await bridge({op:'download',id:selected.item_id});
 }
 console.log(JSON.stringify({collected,downloaded,requests}));
})().catch(()=>process.exit(1));
"""


def run_bridge(mode="collect"):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is needed to exercise the in-page JavaScript")
    result = subprocess.run([node, "-e", HARNESS, str(APP / "renaultbank_api.js"), mode],
                            check=True, text=True, capture_output=True, timeout=15)
    return json.loads(result.stdout)


def test_all_document_pages_archive_and_older_message_attachments_are_read():
    data = run_bridge()
    result = data["collected"]
    assert result["ok"], result
    assert len(result["rows"]) == 5
    assert result["summary"]["documents"] == 3
    assert result["summary"]["attachments"] == 2
    assert result["summary"]["text_only_messages"] == 1
    assert any(r["item_id"].startswith("attachment:old:") for r in result["rows"])
    assert "JWT" not in json.dumps(result)
    assert not any("documentUpload" in r["path"] for r in data["requests"])
    assert not any("/status" in r["path"] or r["method"] in ("PUT", "DELETE", "PATCH")
                   for r in data["requests"])


@pytest.mark.parametrize("mode", ["missing-cursor", "repeated-page", "short-thread"])
def test_incomplete_or_repeated_pages_stop_the_whole_listing(mode):
    result = run_bridge(mode)["collected"]
    assert not result["ok"] and "rows" not in result
    assert "JWT" not in json.dumps(result)


def test_expired_session_is_identified_without_returning_tokens():
    result = run_bridge("expired")["collected"]
    assert result == {"ok": False, "expired": True, "error": "SESSION_EXPIRED"}


@pytest.mark.parametrize("mode", ["download", "attachment"])
def test_existing_pdf_download_uses_browser_ticket_and_stays_on_the_allowlist(mode):
    data = run_bridge(mode)
    assert data["downloaded"]["ok"]
    assert data["downloaded"]["data"].startswith("JVBERi0")
    assert "JWT" not in json.dumps(data["downloaded"])
    assert any("/ticket/download/" in r["path"] for r in data["requests"])
    assert all("directDelete" not in r["path"] for r in data["requests"])


def test_an_html_login_response_is_not_saved_as_a_pdf():
    result = run_bridge("not-pdf")["downloaded"]
    assert not result["ok"]
    assert "data" not in result


def test_invalid_dates_stop_the_listing():
    with pytest.raises(site.ListStopped):
        site._normalise({"item_id": "invented", "title": "Kontoauszug", "date": "2026-02-30"})


def test_normalised_metadata_files_by_kind_and_keeps_only_account_suffix():
    row = site._normalise({"item_id": "invented", "title": "Steuerbescheinigung",
                           "date": "2026-01-31T12:00:00Z", "account": "DE00111122223333444455"})
    assert row["category"] == "Tax Document"
    assert row["date"] == "2026-01-31"
    assert row["account"] == "Konto 4455"
    assert "DE00" not in json.dumps(row)


def test_missing_or_ambiguous_identity_is_not_replaced_with_an_arbitrary_stored_id(monkeypatch):
    monkeypatch.setattr(site, "listed_rows", lambda *a: [])
    with pytest.raises(site.NotToldApart):
        site.resolve_item(None, "Statement", "2026-01-31", "Konto 4455",
                          item_id="old-id", category="Statement", number_rows=lambda rows: [])
