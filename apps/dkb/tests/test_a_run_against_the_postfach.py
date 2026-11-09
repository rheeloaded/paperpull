"""DKB's own main against a made-up Postfach and archive.

Each run goes through the app's main as the panel starts it, with its real
stores, index and files and a made-up config and output folder. Only the
fetch made inside the page is stood in, so the app's own listing, numbering,
resolve_item and fetch_pdf all run. Every PDF carries the name of the
document it is, so a file is known by its bytes and never by its name.

The answers are the shapes the app was mapped against (dkb_site.py, STATUS).
Every IBAN, depot number, WKN, id and date is invented.
"""
import base64
import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from pypdf import PdfWriter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import dkb_docs as docs
import dkb_site as site
from paperpull_core import storage as core_storage
from paperpull_core.run_reporting import ListNotRead

APP = Path(__file__).resolve().parents[1]

DEPOT = "509999999"
IBAN = "DE00120300000000001234"
OTHER_IBAN = "DE00120300000000005678"
COSTS = "Kosteninformation zu Wertpapier EXAMPLE ETF"


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


def cost_note(document: str, day: str = "2031-03-02") -> dict:
    return {"doc": document, "type": "exAnteCostInformation", "subject": COSTS,
            "created": day + "T08:00:00Z", "depotNumber": DEPOT}


def statement(document: str, month: int = 1, iban: str = IBAN) -> dict:
    return {"doc": document, "type": "bankAccountStatement",
            "subject": "Kontoauszug %d/2031" % month, "created": "2031-%02d-02T07:00:00Z" % (month + 1),
            "statementDate": "2031-%02d-28" % month, "iban": iban}


class Bank:
    """What the page's fetch answers. A path in `refuse` answers that status.
    A document in `empty` answers no bytes.

    `ids` says how long an id lasts. "always" keeps the document's own
    name, "session" changes it with `new_session`. An id that is no longer
    good is answered UnknownDocument."""

    def __init__(self):
        self.documents = []
        self.archive = {}
        self.ids = "always"
        self.session = 1
        self.refuse = {}
        self.no_list = set()
        self.empty = set()
        self.fetched = []

    def new_session(self):
        self.session += 1

    def id_of(self, document: str) -> str:
        return "%s-s%d" % (document, self.session) if self.ids == "session" else document

    def _row(self, d):
        meta = {"subject": d["subject"]}
        for field in ("statementDate", "iban", "depotNumber"):
            if d.get(field):
                meta[field] = d[field]
        return {"id": self.id_of(d["doc"]), "type": "document",
                "attributes": {"contentType": "application/pdf", "creationDate": d["created"],
                               "documentTypeId": "00000000-0000-4000-8000-000000000000",
                               "fileName": "%s.pdf" % d["doc"], "metadata": meta}}

    @staticmethod
    def _json(body):
        return {"status": 200, "ct": "application/vnd.api+json", "json": body}

    def answer(self, page, js, arg=None, limit=None):
        url = arg["url"]
        parts = urlsplit(url)
        path, query = parts.path, parse_qs(parts.query)
        offset = int((query.get("page[offset]") or ["0"])[0])
        size = int((query.get("page[limit]") or ["200"])[0])
        if path in self.refuse:
            return {"status": self.refuse[path], "ct": "text/html; charset=utf-8", "b64": ""}
        if path in self.no_list:
            return self._json({"errors": [{"status": "200", "code": "Unexpected"}]})
        if path == "/api/documentstorage/documents":
            rows = [self._row(d) for d in self.documents][offset:offset + size]
            return self._json({"data": rows, "links": {"self": url}})
        if path == "/api/documentstorage/messages":
            return self._json({"data": [
                {"id": "m-" + self.id_of(d["doc"]), "type": "message",
                 "attributes": {"documentId": self.id_of(d["doc"]), "documentType": d["type"],
                                "subject": d["subject"], "read": False}}
                for d in self.documents]})
        if path == "/api/documentstorage/folders":
            return self._json({"data": [{"id": fid, "attributes": {"name": name}}
                                        for fid, (name, _files) in self.archive.items()]})
        if path.startswith("/api/documentstorage/folders/"):
            fid = path.rsplit("/", 1)[-1]
            name, files = self.archive[fid]
            listed = [{"id": self.id_of(f["doc"]), "subject": f["subject"],
                       "fileName": "%s.pdf" % f["doc"], "creationDate": f["created"],
                       "additionalInformation": f.get("iban", "")} for f in files]
            return self._json({"data": {"id": fid, "type": "legacyMailboxFolderContent",
                                        "attributes": {"name": name, "subfolders": [],
                                                       "files": listed[offset:offset + size]}}})
        ident = path.rsplit("/", 1)[-1]
        self.fetched.append(ident)
        if path.startswith("/api/documentstorage/legacy-documents/"):
            found = [f["doc"] for _name, files in self.archive.values() for f in files
                     if self.id_of(f["doc"]) == ident]
            if not found:
                return {"status": 404, "ct": "application/vnd.api+json",
                        "json": {"errors": [{"code": "UnknownDocument"}]}}
            content = "" if found[0] in self.empty else base64.b64encode(pdf_of(found[0])).decode()
            return self._json({"data": {"id": ident, "type": "legacyMailboxFile",
                                        "attributes": {"content": content,
                                                       "contentType": "application/pdf"}}})
        assert path.startswith("/api/documentstorage/documents/"), url
        found = [d["doc"] for d in self.documents if self.id_of(d["doc"]) == ident]
        if not found:
            return {"status": 404, "ct": "application/vnd.api+json",
                    "json": {"errors": [{"code": "UnknownDocument"}]}}
        if found[0] in self.empty:
            return {"status": 200, "ct": "application/pdf", "b64": ""}
        return {"status": 200, "ct": "application/pdf",
                "b64": base64.b64encode(pdf_of(found[0])).decode()}


class Home:
    def __init__(self, tmp_path, monkeypatch, capsys):
        self.bank = Bank()
        self.capsys = capsys
        self.monkeypatch = monkeypatch
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
        self.page = SimpleNamespace(url=site.URLS["documents"])
        monkeypatch.setattr(docs.App, "page", lambda app: self.page)
        monkeypatch.setattr(docs.App, "_on_its_site", lambda app: self.page)
        monkeypatch.setattr(docs.App, "check_session", lambda app, *_a, **_kw: None)
        monkeypatch.setattr(docs.App, "close", lambda app: None)
        monkeypatch.setattr(site.intake, "evaluate", self.bank.answer)
        monkeypatch.setattr("time.sleep", lambda *_a, **_kw: None)
        monkeypatch.setattr(site, "_listing", {})

    def run(self, *flags):
        """The app's main and what it said, each run as a process of its own
        with no listing kept from the run before."""
        self.capsys.readouterr()
        self.bank.fetched = []
        site._listing.clear()
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

    def listed_whole(self) -> bool:
        return self.store("last-listing.json").get("complete") is True


@pytest.fixture
def home(tmp_path, monkeypatch, capsys):
    return Home(tmp_path, monkeypatch, capsys)


# -- a run that reads everything -------------------------------------------------

def test_a_run_saves_the_postfach_and_the_archive_each_with_its_own_bytes(home):
    home.bank.documents = [statement("P1", 1), cost_note("P2")]
    home.bank.archive = {"2": ("Kontoauszüge", [
        {"doc": "A1", "subject": "Kontoauszug Nr. 004_2019", "created": "2019-05-03T10:00Z",
         "iban": IBAN}])}
    code, _said = home.run_all()
    assert code == 0
    assert home.on_disk() == ["A1", "P1", "P2"]
    assert sorted(home.held().values()) == ["A1", "P1", "P2"]
    assert home.listed_whole()


# -- the list is whole or it is not called whole --------------------------------

@pytest.mark.parametrize("path", ["/api/documentstorage/folders",
                                  "/api/documentstorage/folders/2",
                                  "/api/documentstorage/messages",
                                  "/api/documentstorage/documents"])
def test_a_part_of_the_list_that_answers_500_stops_the_listing(home, path):
    """The archive was read in a try that logged the failure and went on
    with no archive, and the messages the same, and Discover then called
    the list whole. Without the messages every document is filed by its
    words, so its key changes and it is saved again in another folder."""
    home.bank.documents = [statement("P1", 1)]
    home.bank.archive = {"2": ("Kontoauszüge", [
        {"doc": "A1", "subject": "Kontoauszug Nr. 004_2019", "created": "2019-05-03T10:00Z"}])}
    home.bank.refuse = {path: 500}
    with pytest.raises(SystemExit) as stop:
        home.run("--discover")
    assert stop.value.code == 1
    assert not home.listed_whole()
    assert home.store("discovery.json") == {}
    assert home.on_disk() == []


@pytest.mark.parametrize("path", ["/api/documentstorage/folders",
                                  "/api/documentstorage/folders/2",
                                  "/api/documentstorage/messages",
                                  "/api/documentstorage/documents"])
def test_an_answer_with_no_list_in_it_is_not_an_empty_list(home, path):
    """A JSON answer without its data was read as a page with nothing on
    it, which ends that part of the list as if it had been read to its end."""
    home.bank.documents = [statement("P1", 1)]
    home.bank.archive = {"2": ("Kontoauszüge", [])}
    home.bank.no_list = {path}
    with pytest.raises(SystemExit):
        home.run("--discover")
    assert not home.listed_whole()
    assert home.store("discovery.json") == {}


@pytest.mark.parametrize("path", ["/api/documentstorage/documents",
                                  "/api/documentstorage/folders"])
def test_a_list_that_stops_while_documents_download_stops_the_run_once(home, path):
    """A download reads the list again. When that stops, every document
    after it would read the same list, so the run stops at the first with
    nothing recorded against it, and leaves with its list unread, so the
    panel offers a run that lists rather than Continue (#124)."""
    home.bank.documents = [statement("P1", 1), statement("P2", 2)]
    home.run("--discover")
    assert home.listed_whole()
    home.bank.refuse = {path: 500}
    with pytest.raises(ListNotRead):
        home.run("--resume")
    assert home.bank.fetched == []
    assert home.store("progress.json") == {}
    assert not home.listed_whole()


# -- each document's own bytes ----------------------------------------------------

def test_a_stored_id_the_list_still_shows_beats_the_place(home):
    """Two cost notes of one depot, one day and one subject. The list came
    back in the other order, and a place handed each the other's bytes."""
    home.bank.documents = [cost_note("K1"), cost_note("K2")]
    home.run("--discover")
    numbered = {key: rec["item_id"] for key, rec in home.store("discovery.json").items()}
    assert sorted(numbered.values()) == ["K1", "K2"]
    home.bank.documents.reverse()
    home.run("--resume")
    assert home.held() == numbered


def test_a_listing_in_another_order_leaves_each_number_with_its_document(home):
    """The first saved, the second failed, and the next list reversed. A
    number going by order gave the first's number to the second, so it was
    skipped as done and the first was saved again beside itself."""
    home.bank.documents = [cost_note("K1"), cost_note("K2")]
    home.bank.empty = {"K2"}
    home.run_all()
    assert home.on_disk() == ["K1"]
    home.bank.empty = set()
    home.bank.documents.reverse()
    home.run_all()
    assert home.on_disk() == ["K1", "K2"]
    assert sorted(home.held().values()) == ["K1", "K2"]


def test_a_twin_beside_one_saved_fails_when_its_id_did_not_last(home):
    """Which of the two rows is the saved one cannot be told, so guessing
    saves that one twice and the other never."""
    home.bank.ids = "session"
    home.bank.documents = [cost_note("K1"), cost_note("K2")]
    home.bank.empty = {"K2"}
    home.run_all()
    home.bank.empty = set()
    home.bank.new_session()
    home.bank.documents.reverse()
    code, _said = home.run_all()
    assert code == 1
    assert home.on_disk() == ["K1"]


def test_a_stored_id_another_document_holds_now_is_not_fetched(home):
    """A document the list no longer shows is asked for by its stored id,
    unless the list gives that id to another document."""
    home.bank.documents = [statement("P1", 1)]
    home.run("--discover")
    home.bank.documents = [statement("P1", 2)]          # P1's id, now another month
    code, _said = home.run("--resume")
    assert code == 1
    assert home.bank.fetched == []
    assert home.on_disk() == []


def test_a_capture_that_saved_nothing_is_a_failure_tried_again(home):
    home.bank.documents = [statement("P1", 1)]
    home.bank.empty = {"P1"}
    code, said = home.run_all()
    assert code == 1
    states = {rec["state"] for rec in home.store("progress.json").values()}
    assert states == {"Failed"}
    assert "Nothing was saved, and the next run tries it again" in said
    assert not list((home.out / "Manual Review").glob("*"))
    home.bank.empty = set()
    home.run_all()
    assert home.on_disk() == ["P1"]


# -- the Postfach and the archive ---------------------------------------------------

def test_an_archive_file_of_another_account_is_not_taken_for_the_postfach_one(home):
    """A file in both places is taken from the Postfach, by its day and
    subject. Another account's file of that day and subject is another
    document."""
    home.bank.documents = [statement("P1", 1, iban=IBAN)]
    same_day = {"subject": "Kontoauszug 1/2031", "created": "2031-01-28T10:00Z"}
    home.bank.archive = {"2": ("Kontoauszüge", [
        dict(same_day, doc="A1", iban=IBAN), dict(same_day, doc="A2", iban=OTHER_IBAN)])}
    home.run_all()
    assert home.on_disk() == ["A2", "P1"]


# -- the sign-in -----------------------------------------------------------------

@pytest.mark.parametrize("status,claims", [(200, True), (401, False), (500, False)])
def test_login_says_success_only_when_the_list_answers(home, status, claims):
    """A banking.dkb.de address with no sign-in form on it was taken for a
    session. Only the list answering is."""
    if status != 200:
        home.bank.refuse = {"/api/documentstorage/documents": status}
    code, said = home.run("--login")
    assert code == 0
    assert ("Success" in said) is claims
