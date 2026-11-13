"""Renault Bank direkt's own main against a made-up Postfach, in a browser.

Each run goes through the app's main as the panel starts it, with its real
stores, index and files and a made-up config and output folder. The page is
Playwright's own Chromium on the bank's address, every request answered by
the route below and every name resolved to nowhere, so the app's own page
script runs as it does at the bank, and its listing, numbering, resolve_item
and download_document all run. Every PDF carries the name of the document
it is, so a file is known by its bytes and never by its name.

The answers are the shapes the app was mapped against (renaultbank_site.py
and tests/test_postfach_api.py). Every IBAN, customer, id and date is
invented.
"""
import base64
import io
import json
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest
from pypdf import PdfWriter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import renaultbank_docs as docs
import renaultbank_site as site
from paperpull_core import storage as core_storage
from paperpull_core.run_reporting import ListNotRead

pw_api = pytest.importorskip("playwright.sync_api")

APP = Path(__file__).resolve().parents[1]
CUSTOMER = "9999"
IBAN = "DE00120300000000001234"
OTHER_IBAN = "DE00120300000000005678"

# Playwright's own Chromium, never a browser installed on this computer,
# with every name resolved to nowhere so a request the route does not
# answer cannot leave the machine.
ARGS = ["--disable-extensions", "--disable-sync", "--no-first-run",
        "--disable-background-networking", "--disable-component-update",
        "--no-proxy-server", "--host-resolver-rules=MAP * ~NOTFOUND"]

POSTFACH = "/services_cloud/portal/webcomp/epostfach/postfach"
PAGE_HTML = """<!doctype html><html><head><title>Postfach</title></head>
<body><h1>Postfach</h1><script>
window.okpGlobal = {portalContext: {getSecurityService: () => ({
  getSessionExpiry: () => Date.now() + 600000,
  ensureTokenForApiCall: () => Promise.resolve(true)})}};
</script></body></html>"""


def pdf_of(document: str) -> bytes:
    """A PDF that opens, with a page, carrying which document it is."""
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    writer.add_metadata({"/Subject": "document %s" % document})
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue().ljust(4000, b" ")


def whose(body: bytes) -> str:
    return body.split(b"(document ", 1)[1].split(b")", 1)[0].decode()


def document(name, title="Kontoauszug 1/2031", day="2031-02-02", kind="Kontoauszug",
             iban=IBAN):
    return {"doc": name, "title": title, "date": day, "kind": kind, "iban": iban}


def message(name, at="2031-03-02T08:00:00Z", subject="Information", files=(), older=()):
    """`files` are (name, file name, extension or None), `older` are the
    thread's older messages."""
    return {"doc": name, "at": at, "subject": subject, "files": list(files),
            "older": list(older)}


class Bank:
    """What the bank answers. A name in `refuse` answers that status, an
    endpoint by its name (liefereDokumenteZuKunden, messages, ...) or a
    file by its document's name. A document in `not_pdf` answers an HTML
    page instead of its PDF, and once the document in `signs_out` is asked
    for, the bank answers as signed out from then on. `ids` says how long an id lasts, "always"
    keeps the document's own name and "session" changes it with
    `new_session`."""

    def __init__(self):
        self.customers = [{"kundenId": CUSTOMER, "nachrichtenBerechtigt": True}]
        self.inbox = []
        self.archive = []
        self.received = []
        self.sent = []
        self.refuse = {}
        self.not_pdf = set()
        self.signs_out = None
        self.ids = "always"
        self.session = 1
        self.asked = []
        self.fetched = []

    def new_session(self):
        self.session += 1

    def id_of(self, name: str) -> str:
        return "%s-s%d" % (name, self.session) if self.ids == "session" else name

    def name_of(self, ident: str) -> str:
        return ident.rsplit("-s", 1)[0] if self.ids == "session" else ident

    def _message(self, m, parts=None):
        files = [{"binaryDataId": self.id_of(f), "filename": filename,
                  **({"extension": ext} if ext else {})} for f, filename, ext in m["files"]]
        return {"docId": self.id_of(m["doc"]), "receivedTimestamp": m["at"],
                "betreff": m["subject"], "attachments": files, "attachmentCount": len(files),
                "anzahlNachrichtenAusKorrespondenz": parts or 1 + len(m["older"])}

    def answer(self, route):
        request = route.request
        path = urlsplit(request.url).path
        if path == POSTFACH:
            return route.fulfill(status=200, content_type="text/html", body=PAGE_HTML)
        body = request.post_data_json if request.method == "POST" else None
        if "CoreApi/" in path:
            endpoint = path.split("CoreApi/", 1)[1].rsplit("/", 1)[-1]
        elif "KKMNachrichtApi/" in path:
            endpoint = path.split("KKMNachrichtApi/", 1)[1].split("/", 1)[0]
        elif "/datasharing/ticket/download/" in path:
            return self._file(route, path.rsplit("/", 1)[-1])
        else:
            return route.fulfill(status=404, content_type="text/plain", body="not found")
        self.asked.append(endpoint)
        if endpoint in self.refuse:
            return route.fulfill(status=self.refuse[endpoint], content_type="text/html", body="no")
        data = self._json(endpoint, path, body)
        return route.fulfill(status=200, content_type="application/json", body=json.dumps(data))

    def _json(self, endpoint, path, body):
        if endpoint == "liefereBerechtigteKunden":
            return {"jwtKundeListe": "INVENTED_CUSTOMER_JWT", "jwtNextVersion": True,
                    "kundeMitHauptKategorieZaehlerListe": [{"kunde": dict(c)} for c in self.customers]}
        if endpoint == "liefereDokumenteZuKunden":
            docs_ = self.archive if body["hauptKategorie"] == "ARCHIV" else self.inbox
            start = int(body["offset"] or 0)
            size = int(body["anzahlDokumente"])
            page = docs_[start:start + size]
            data = {"dokumentListe": [{
                "dokumentId": self.id_of(d["doc"]), "dokumentTitel": d["title"],
                "erstellDatum": d["date"], "roUnterKategorie": {"unterKategorieName": d["kind"]},
                "zugehoerigesObjekt": {"id": d["iban"], "typ": "IBAN"}} for d in page],
                "dokumentenZaehler": {"anzahlPosteingangGesamt": len(self.inbox),
                                      "anzahlArchivGesamt": len(self.archive)},
                "jwtDokumentListe": "INVENTED_DOCUMENT_JWT"}
            if start + size < len(docs_):
                data["aufsetzpunkt"] = str(start + size)
            return data
        listed = self.received if (body or {}).get("nachrichtenFilter") == "EINGANG" else self.sent
        if endpoint == "messageCount":
            return {"count": len(listed)}
        if endpoint == "messages":
            start, size = int(body["offset"]), int(body["anzahl"])
            return {"korrespondenznachrichten": [self._message(m) for m in listed[start:start + size]],
                    "jwt": "INVENTED_MESSAGE_JWT"}
        if endpoint == "messageThread":
            ident = path.rsplit("/", 1)[-1]
            m = next(m for m in self.received + self.sent if self.id_of(m["doc"]) == ident)
            return {"jwt": "INVENTED_THREAD_JWT",
                    "korrespondenznachrichten": [self._message(x) for x in [m, *m["older"]]]}
        if endpoint == "documentUpload":
            assert body["jwtDokumentListe"] == "INVENTED_DOCUMENT_JWT"
            return {"uploadId": "u-" + body["dokumentId"], "downloadTicketId": "INVENTED_TICKET"}
        if endpoint == "messageAttachmentDownload":
            binary = base64.b64decode(unquote(path.rsplit("/", 1)[-1])).decode()
            return {"uploadId": "u-" + binary}
        if endpoint == "downloadTicket":
            return {"ticketId": "INVENTED_TICKET"}
        raise AssertionError("unexpected endpoint %s" % endpoint)

    def _file(self, route, upload):
        name = self.name_of(upload[2:])
        self.fetched.append(name)
        if name in self.refuse:
            return route.fulfill(status=self.refuse[name], content_type="text/html", body="no")
        if name == self.signs_out:
            self.refuse = {endpoint: 401 for endpoint in (
                "liefereBerechtigteKunden", "liefereDokumenteZuKunden", "messageCount",
                "messages", "messageThread", "documentUpload", "messageAttachmentDownload",
                "downloadTicket")}
            return route.fulfill(status=200, content_type="text/html", body="<html>Anmelden</html>")
        if name in self.not_pdf:
            return route.fulfill(status=200, content_type="text/html", body="<html>Anmelden</html>")
        return route.fulfill(status=200, content_type="application/pdf", body=pdf_of(name))


@pytest.fixture(scope="module")
def chromium():
    with pw_api.sync_playwright() as driver:
        browser = driver.chromium.launch(headless=True, args=ARGS)
        try:
            yield browser
        finally:
            browser.close()


class Home:
    def __init__(self, chromium, tmp_path, monkeypatch, capsys):
        self.bank = Bank()
        self.capsys = capsys
        self.out = tmp_path / "out"
        self.config = json.loads((APP / "config.example.json").read_text(encoding="utf-8"))
        self.config.update({"owner": "Dana Example", "output_dir": str(self.out),
                            "profile_dir": str(tmp_path / "profile"),
                            "cdp_url": "http://127.0.0.1:9", "delay_min_seconds": 0,
                            "delay_max_seconds": 0, "default_start_date": ""})
        self.cfg = tmp_path / "config.json"
        self.cfg.write_text(json.dumps(self.config), encoding="utf-8")
        for name in ("_FILENAME_PATTERN", "_PATTERN_OWNER", "_FILENAME_OWNER"):
            monkeypatch.setattr(core_storage, name, getattr(core_storage, name))
        self.context = chromium.new_context()
        self.context.route("**/*", self.bank.answer)
        self.page = self.context.new_page()
        self.page.goto("https://banking.renault-bank-direkt.de" + POSTFACH)
        monkeypatch.setattr(docs.App, "page", lambda app: self.page)
        monkeypatch.setattr(docs.App, "_on_its_site", lambda app: self.page)
        monkeypatch.setattr(docs.App, "close", lambda app: None)
        monkeypatch.setattr("time.sleep", lambda *_a, **_kw: None)
        monkeypatch.setattr(site, "_cache", None)
        monkeypatch.setattr(site, "_summary", {})

    def run(self, *flags):
        """The app's main and what it said, each run as a process of its own
        with no listing kept from the run before. The page and what the
        last listing left in it stay, as the person's tab does."""
        self.capsys.readouterr()
        self.bank.fetched = []
        site._cache = None
        site._summary = {}
        code = docs.main(["--config", str(self.cfg), *flags])
        return code, " ".join(self.capsys.readouterr().out.split())

    def run_all(self, *flags):
        return self.run("--all", "--yes", *flags)

    def store(self, name: str) -> dict:
        path = self.out / name
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def on_disk(self) -> list:
        """Whose bytes each PDF under the output folder holds."""
        return sorted(whose(p.read_bytes()) for p in self.out.rglob("*.pdf"))

    def held(self) -> dict:
        """Whose bytes each saved record's file holds, by key."""
        return {key: whose(Path(rec["pdf_path"]).read_bytes())
                for key, rec in sorted(self.store("progress.json").items())
                if isinstance(rec, dict) and rec.get("downloaded_ok")}

    def states(self) -> dict:
        return {rec["item_id"]: rec["state"] for rec in self.store("progress.json").values()
                if isinstance(rec, dict)}

    def listed_whole(self) -> bool:
        return self.store("last-listing.json").get("complete") is True


@pytest.fixture
def home(chromium, tmp_path, monkeypatch, capsys):
    home = Home(chromium, tmp_path, monkeypatch, capsys)
    try:
        yield home
    finally:
        home.context.close()


def discover_stops(home) -> str:
    """Discover stopped with its list not called whole and nothing recorded,
    and what it said."""
    with pytest.raises(SystemExit) as stop:
        home.run("--discover")
    said = " ".join(home.capsys.readouterr().out.split())
    assert stop.value.code == 1
    assert not home.listed_whole()
    assert home.store("discovery.json") == {}
    return said


# -- a run that reads everything -------------------------------------------------

def test_a_run_saves_the_postfach_the_archive_and_attachments_each_with_its_own_bytes(home):
    home.bank.inbox = [document("P1")]
    home.bank.archive = [document("A1", "Kontoauszug 4/2019", "2019-05-03")]
    home.bank.received = [message("M1", files=[("F1", "Brief.pdf", "pdf"),
                                               ("J1", "foto.jpg", "jpg")],
                                  older=[message("M0", "2031-01-02T08:00:00Z",
                                                 files=[("F0", "Antwort.PDF", None)])]),
                          message("T1")]
    home.bank.sent = [message("S1", files=[("F2", "Unterlagen.pdf", "pdf")])]
    code, said = home.run_all()
    assert code == 0
    assert home.on_disk() == ["A1", "F0", "F1", "F2", "P1"]
    assert sorted(home.held().values()) == ["A1", "F0", "F1", "F2", "P1"]
    assert "J1" not in home.bank.fetched
    assert "1 message attachment(s) are not PDFs" in said
    assert "1 message(s) have no attachment" in said
    assert home.listed_whole()


def test_a_list_longer_than_a_page_is_read_to_its_end(home):
    home.bank.inbox = [document("P%03d" % n, "Mitteilung %d" % n, kind="Mitteilung")
                       for n in range(130)]
    code, _said = home.run("--discover")
    assert code == 0
    assert len(home.store("discovery.json")) == 130
    assert home.bank.asked.count("liefereDokumenteZuKunden") == 3
    assert home.listed_whole()


def test_an_empty_postfach_is_listed_whole(home):
    code, _said = home.run("--discover")
    assert code == 0
    assert home.listed_whole()


def test_a_customer_without_messages_is_not_asked_for_them(home):
    home.bank.customers[0]["nachrichtenBerechtigt"] = False
    home.bank.inbox = [document("P1")]
    code, _said = home.run_all()
    assert code == 0
    assert home.on_disk() == ["P1"]
    assert not {"messageCount", "messages"} & set(home.bank.asked)


# -- one document that will not download ----------------------------------------

@pytest.mark.parametrize("how", ["http_500", "not_a_pdf", "no_ticket"])
def test_one_document_without_a_pdf_fails_alone_and_the_run_goes_on(home, how):
    """Its failure came back as the list stopping, so the run ended at it
    with nothing recorded. Runs go newest first, so every later run stopped
    at the same place and nothing older was ever saved."""
    home.bank.inbox = [document("P2", "Kontoauszug 2/2031", "2031-03-02"), document("P1")]
    if how == "http_500":
        home.bank.refuse = {"P2": 500}
    elif how == "not_a_pdf":
        home.bank.not_pdf = {"P2"}
    else:
        original = home.bank._json

        def no_ticket(endpoint, path, body):
            data = original(endpoint, path, body)
            if endpoint == "documentUpload" and body["dokumentId"] == "P2":
                data.pop("downloadTicketId")
            return data
        home.bank._json = no_ticket
    code, said = home.run_all()
    assert code == 1
    assert home.on_disk() == ["P1"]
    assert home.states() == {"document:P2": "Failed", "document:P1": "Completed"}
    assert "Nothing was saved, and the next run tries it again" in said
    assert home.listed_whole()
    home.bank.refuse, home.bank.not_pdf = {}, set()
    vars(home.bank).pop("_json", None)
    code, _said = home.run_all()
    assert code == 0
    assert home.on_disk() == ["P1", "P2"]


def test_a_signed_out_answer_stops_the_run_with_nothing_recorded_against_it(home):
    home.bank.inbox = [document("P2", "Kontoauszug 2/2031", "2031-03-02"), document("P1")]
    home.run("--discover")
    home.bank.refuse = {"documentUpload": 401}
    with pytest.raises(SystemExit) as stop:
        home.run("--resume")
    assert stop.value.code == 0
    said = " ".join(home.capsys.readouterr().out.split())
    assert "Your session has expired" in said
    assert home.bank.fetched == []
    assert home.on_disk() == []
    assert "Completed" not in home.states().values()


def test_a_sign_in_page_in_place_of_a_pdf_stops_the_run_when_the_list_answers_signed_out(home):
    """A sign-in page served with 200 in place of the PDF says nothing a
    file can tell. The list is read again, and its answer as signed out
    stops the run there, rather than fail every document after it one by
    one."""
    home.bank.inbox = [document("P3", "Kontoauszug 3/2031", "2031-04-02"),
                       document("P2", "Kontoauszug 2/2031", "2031-03-02"), document("P1")]
    home.run("--discover")
    home.bank.signs_out = "P3"
    with pytest.raises(SystemExit) as stop:
        home.run("--resume")
    assert stop.value.code == 0
    said = " ".join(home.capsys.readouterr().out.split())
    assert "Your session has expired" in said
    assert home.bank.fetched == ["P3"]
    assert home.on_disk() == []
    assert set(home.states().values()) <= {"Discovered"}


# -- the list is whole or it is not called whole --------------------------------

@pytest.mark.parametrize("endpoint", ["liefereBerechtigteKunden", "liefereDokumenteZuKunden",
                                      "messageCount", "messages", "messageThread"])
def test_a_part_of_the_list_that_answers_500_stops_the_listing(home, endpoint):
    home.bank.inbox = [document("P1")]
    home.bank.received = [message("M1", files=[("F1", "Brief.pdf", "pdf")],
                                  older=[message("M0", "2031-01-02T08:00:00Z")])]
    home.bank.refuse = {endpoint: 500}
    discover_stops(home)


@pytest.mark.parametrize("endpoint", ["liefereDokumenteZuKunden", "messages"])
def test_a_list_that_stops_while_documents_download_stops_the_run_once(home, endpoint):
    """A download reads the list again. When that stops, every document
    after it would read the same list, so the run stops at the first with
    nothing recorded against it, and leaves with its list unread (#124)."""
    home.bank.inbox = [document("P2", "Kontoauszug 2/2031", "2031-03-02"), document("P1")]
    home.bank.received = [message("M1")]
    home.run("--discover")
    assert home.listed_whole()
    home.bank.refuse = {endpoint: 500}
    with pytest.raises(ListNotRead):
        home.run("--resume")
    assert home.bank.fetched == []
    assert home.store("progress.json") == {}
    assert not home.listed_whole()


# -- each document's own bytes ----------------------------------------------------

def test_a_stored_id_the_list_still_shows_beats_the_place(home):
    """Two notes of one account, one day and one title. The list came back
    in the other order, and a place would hand each the other's bytes."""
    home.bank.inbox = [document("K1", "Information", kind="Mitteilung"),
                       document("K2", "Information", kind="Mitteilung")]
    home.run("--discover")
    numbered = {key: rec["item_id"] for key, rec in home.store("discovery.json").items()}
    assert sorted(numbered.values()) == ["document:K1", "document:K2"]
    home.bank.inbox.reverse()
    home.run("--resume")
    assert {key: "document:" + name for key, name in home.held().items()} == numbered


def test_a_listing_in_another_order_leaves_each_number_with_its_document(home):
    """The first saved, the second failed, and the next list reversed. Each
    number stays with the id it was given to (keys.told_apart)."""
    home.bank.inbox = [document("K1", "Information", kind="Mitteilung"),
                       document("K2", "Information", kind="Mitteilung")]
    home.bank.not_pdf = {"K2"}
    home.run_all()
    assert home.on_disk() == ["K1"]
    home.bank.not_pdf = set()
    home.bank.inbox.reverse()
    home.run_all()
    assert home.on_disk() == ["K1", "K2"]
    assert sorted(home.held().values()) == ["K1", "K2"]


def test_a_twin_beside_one_saved_fails_when_its_id_did_not_last(home):
    """Which of the two rows is the saved one cannot be told, so guessing
    would save that one twice and the other never."""
    home.bank.ids = "session"
    home.bank.inbox = [document("K1", "Information", kind="Mitteilung"),
                       document("K2", "Information", kind="Mitteilung")]
    home.bank.not_pdf = {"K2"}
    home.run_all()
    home.bank.not_pdf = set()
    home.bank.new_session()
    home.bank.inbox.reverse()
    code, _said = home.run_all()
    assert code == 1
    assert home.on_disk() == ["K1"]


def test_a_document_gone_from_the_list_fails_and_says_so(home):
    home.bank.inbox = [document("P1")]
    home.run("--discover")
    home.bank.inbox = []
    code, _said = home.run("--resume")
    assert code == 1
    assert home.bank.fetched == []
    notes = [rec.get("notes", "") for rec in home.store("progress.json").values()]
    assert any("no longer shows this document" in n for n in notes)


def test_two_accounts_alike_documents_are_two_documents(home):
    home.bank.inbox = [document("P1", iban=IBAN), document("P2", iban=OTHER_IBAN)]
    code, _said = home.run_all()
    assert code == 0
    assert home.on_disk() == ["P1", "P2"]


# -- dates --------------------------------------------------------------------------

def test_a_message_received_after_midnight_in_berlin_is_filed_under_that_day(home):
    home.bank.received = [message("M1", at="2031-02-28T23:30:00Z",
                                  files=[("F1", "Brief.pdf", "pdf")])]
    home.run_all()
    dates = {rec["date"] for rec in home.store("discovery.json").values()}
    assert dates == {"2031-03-01"}
    assert [p.name[:10] for p in home.out.rglob("*.pdf")] == ["2031-03-01"]


# -- the sign-in -----------------------------------------------------------------

@pytest.mark.parametrize("status,claims", [(200, True), (401, False), (500, False)])
def test_login_says_success_only_when_the_list_answers(home, status, claims):
    """A banking.renault-bank-direkt.de address with no sign-in form on it
    says nothing of the session. Only the list answering does."""
    if status != 200:
        home.bank.refuse = {"liefereDokumenteZuKunden": status}
    code, said = home.run("--login")
    assert code == 0
    assert ("Success" in said) is claims
