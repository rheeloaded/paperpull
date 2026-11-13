"""Run the production in-page bridge against invented API responses."""
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
import direkt1822_site as site

HARNESS = r"""
const fs=require('fs');
const bridge=eval('('+fs.readFileSync(0,'utf8')+')');
const mode=process.argv[1];
global.window={};global.location={origin:'https://www.1822direkt-banking.de'};
const requests=[];
let sessions=0;
const row=(id,category='MEGA')=>({id:'row-'+id,selectionId:'select-'+id,dokumentId:id,
 fileName:'invented-'+id+'.pdf',inhalt:'Kontoauszug '+id,kategorie:category,
 erhaltenAm:'2026-03-31T12:00:00',pdfFile:true,htmlFile:false,anzahlKorrespondenz:1});
global.fetch=async(path,options)=>{
 if(options.credentials!=='same-origin'||options.redirect!=='error'||options.mode!=='same-origin')throw new Error('unsafe fetch');
 const body=options.body?JSON.parse(options.body):undefined;
 requests.push({path,method:options.method,page:body?.seite,
   authAttached:!!options.headers['X-JOBA-AUTH'],csrfAttached:!!options.headers['X-CSRF-TOKEN']});
 let data={jobaMeldungen:[]};
 if(path.endsWith('benutzerInfo?complete=false')) {
  if(mode==='expired')return {ok:false,status:401};
  sessions++;data.benutzerInfo={token:'PRIVATE_AUTH_'+sessions,csrfToken:'PRIVATE_CSRF_'+sessions,
    hatMehrereKundenverbindungen:mode==='multiple',stammNrsDisplay:[]};
  if(mode==='missing-csrf')delete data.benutzerInfo.csrfToken;
 } else if(path.endsWith('/leseUndVermerkeMitId')){
  if(mode!=='conversation-allowed')throw new Error('read-marking without consent');
  data.konversation={betreff:'Invented correspondence',konversationen:[
   {dokumentId:body.id.replace('row-',''),fileName:'root.pdf',filePDF:true,versandtAm:'2026-03-31'},
   {dokumentId:'child-'+body.id,fileName:'attachment.pdf',filePDF:true,versandtAm:'2026-02-28'}]};
  data.gesendeteDateien=[];
 } else if(options.method==='POST'){
  if(!path.match(/\/postboxnachricht\/(eingang|ausgang|papierkorb)$/))throw new Error('write endpoint');
  if(options.headers['X-JOBA-AUTH']!=='PRIVATE_AUTH_'+sessions||options.headers['X-CSRF-TOKEN']!=='PRIVATE_CSRF_'+sessions)throw new Error('bad session');
  if(body.orderBy!=='erhaltenAm'||Object.keys(body.suchKriterien).join(',')!=='markierteNachrichten')throw new Error('bad filter');
  if(path.endsWith('/eingang')){
   data={...data,gesamtzahlNachrichten:3,gesamtzahlSeiten:2,seite:body.seite,
    postboxNachrichtListe:body.seite===0?[row('d1'),row('d2','JSTB')]:[row('d3','EWJA')]};
   if(mode==='repeated-page'&&body.seite===1)data.postboxNachrichtListe=[row('d1')];
   if(mode==='changed-total'&&body.seite===1)data.gesamtzahlNachrichten=4;
   if(mode==='short-page'&&body.seite===1)data.postboxNachrichtListe=[];
   if(mode==='wrong-page')data.seite=100;
   if(['conversation','conversation-allowed'].includes(mode))data.postboxNachrichtListe[0].anzahlKorrespondenz=2;
   if(mode==='missing-metadata')delete data.postboxNachrichtListe[0].dokumentId;
   if(mode==='bank-error')data.jobaMeldungen=[{text:'PRIVATE BANK CONTENT'}];
  }else{
   data={...data,gesamtzahlNachrichten:1,gesamtzahlSeiten:1,seite:body.seite,
    postboxNachrichtListe:path.endsWith('/ausgang')?[{...row('html'),pdfFile:false,htmlFile:true}]:[row('d4','BRIEF')]};
   if(mode==='same-pdf-other-context'&&path.endsWith('/papierkorb'))data.postboxNachrichtListe=[{...row('d1'),inhalt:'A different conversation subject'}];
  }
 }else if(path.includes('/postboxnachricht/download/')){
  if(options.headers.Accept!=='*/*')return {ok:false,status:406};
  if(options.headers['X-JOBA-AUTH']!=='PRIVATE_AUTH_'+sessions)throw new Error('stale session');
  const bytes=Buffer.from(mode==='not-pdf'?'<html>login</html>':'%PDF-1.4\nINVENTED PDF');
  return {ok:true,status:200,headers:{get:()=> 'application/pdf'},
    arrayBuffer:async()=>bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength)};
 }else throw new Error('unexpected endpoint');
 return {ok:true,status:200,headers:{get:()=> 'application/json'},arrayBuffer:async()=>new TextEncoder().encode(JSON.stringify(data)).buffer};
};
(async()=>{
 const collected=await bridge({op:'collect',include_trash:mode!=='no-trash',open_conversations:mode==='conversation-allowed'});
 let downloaded;
 if(collected.ok&&['download','not-pdf'].includes(mode))downloaded=await bridge({op:'download',id:collected.rows[0].item_id});
 console.log(JSON.stringify({collected,downloaded,requests,sessions}));
})().catch(()=>process.exit(1));
"""


def run(mode="collect"):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required to exercise the in-page bridge")
    result = subprocess.run([node, "-e", HARNESS, mode],
                            input=site.intake.reading(site._API_JS),
                            capture_output=True, encoding="utf-8", check=True, timeout=15)
    return json.loads(result.stdout)


def test_all_zero_based_pages_and_folders_are_read_without_opening_messages():
    data = run()
    assert data["collected"]["ok"], data
    assert len(data["collected"]["rows"]) == 4
    assert data["collected"]["summary"]["non_pdf_messages"] == 1
    assert [r["page"] for r in data["requests"] if r["path"].endswith('/eingang')] == [0, 1]
    assert all("leseUndVermerke" not in r["path"] and "markiere" not in r["path"] and
               "update" not in r["path"] for r in data["requests"])
    assert "PRIVATE" not in json.dumps(data)


@pytest.mark.parametrize("mode", ["repeated-page", "changed-total", "short-page", "wrong-page",
                                  "conversation", "missing-metadata", "bank-error", "multiple"])
def test_incomplete_or_unmapped_histories_never_commit_a_partial_list(mode):
    data = run(mode)
    assert not data["collected"]["ok"] and "rows" not in data["collected"]
    assert "PRIVATE" not in json.dumps(data)


@pytest.mark.parametrize("mode", ["expired", "missing-csrf"])
def test_session_failure_stops_before_any_document_list_request(mode):
    data = run(mode)
    assert data["collected"]["expired"]
    assert len(data["requests"]) == 1


def test_direct_pdf_download_refreshes_only_in_page_session_information():
    data = run("download")
    assert data["downloaded"]["ok"]
    assert data["downloaded"]["data"].startswith('JVBERi0')
    assert data["sessions"] == 2
    assert data["requests"][-1]["method"] == "GET"
    assert not data["requests"][-1]["csrfAttached"]
    assert "PRIVATE" not in json.dumps(data)


def test_trash_can_be_excluded_explicitly():
    data = run("no-trash")
    assert len(data["collected"]["rows"]) == 3
    assert not any(r["path"].endswith('/papierkorb') for r in data["requests"])


def test_explicit_conversation_consent_collects_older_pdf_attachments():
    data = run("conversation-allowed")
    assert data["collected"]["ok"], data
    assert any(r["item_id"].startswith('child-') for r in data["collected"]["rows"])
    assert data["collected"]["summary"]["opened_conversations"] >= 1


def test_one_pdf_referenced_under_different_conversation_subjects_is_listed_once():
    data = run("same-pdf-other-context")
    assert data["collected"]["ok"], data
    rows = data["collected"]["rows"]
    assert len(rows) == 3
    assert sum(r["item_id"] == 'd1' for r in rows) == 1
    assert next(r for r in rows if r["item_id"] == 'd1')["title"] == 'Kontoauszug d1'


def test_html_is_never_saved_as_pdf():
    data = run("not-pdf")
    assert not data["downloaded"]["ok"] and "data" not in data["downloaded"]


@pytest.mark.parametrize("code,category", [("MEGA", "Statement"), ("MEKA", "Credit Card Statement"),
    ("EWOM", "Securities Document"), ("EWJA", "Securities Document"), ("JSTB", "Tax Document"),
    ("ADV", "Other Document"), ("INFO", "Message"), ("BRIEF", "Message")])
def test_declared_postbox_category_takes_priority_over_subject_guesses(code, category):
    assert site.classify(code, "A deliberately unrelated invented title") == category


def test_invalid_dates_stop_instead_of_disappearing():
    with pytest.raises(site.ListStopped):
        site._normalise({"item_id":"invented","title":"Kontoauszug","date":"2026-02-30"})


def test_attaching_during_the_account_holders_login_waits_without_clicking_or_reloading():
    class Page:
        url = "https://www.1822direkt-banking.de/ng-banking/login/eingabe"
        waits = 0

        def wait_for_timeout(self, ms):
            self.waits += 1
            if self.waits == 2:
                self.url = "https://www.1822direkt-banking.de/ng-banking/banking/finanzuebersicht"

        def locator(self, selector):
            return type("Locator", (), {"count": lambda self: 0})()

        def goto(self, *args, **kwargs):
            raise AssertionError("do not restart the account holder's navigation")

    page = Page()
    assert site.goto_documents(page)
    assert page.waits == 2


@pytest.mark.parametrize("list_error", [None, site.SessionExpired, site.ListStopped])
def test_a_refused_pdf_is_weighed_against_a_fresh_list(monkeypatch, tmp_path, list_error):
    monkeypatch.setattr(site, "resolve_item", lambda *args, **kwargs: {"item_id": "invented"})

    def refused(*args, **kwargs):
        raise site.intake.TooLarge("invented oversized PDF")

    reads = []

    def relist(page, config, *, fresh):
        reads.append(fresh)
        if list_error:
            raise list_error("invented list error")
        return []

    monkeypatch.setattr(site, "_execute", refused)
    monkeypatch.setattr(site, "listed_rows", relist)
    output = tmp_path / "statement.pdf"

    def download():
        return site.download_document(None, "Statement", "2026-03-31", output,
                                      category="Statement", number_rows=lambda rows: [])

    if list_error:
        with pytest.raises(list_error):
            download()
    else:
        assert download() == ""
    assert reads == [True]
    assert not output.exists()
