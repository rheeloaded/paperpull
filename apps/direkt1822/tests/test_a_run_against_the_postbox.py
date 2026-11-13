"""1822direkt's own main against a made-up Postbox, in a browser.

Each run goes through the app's main as the panel starts it, with its real
stores, index and files and a made-up config and output folder. The page is
Playwright's own Chromium on the bank's address, every request answered by
the route below and every name resolved to nowhere, so the app's own page
script runs as it does at the bank, and its listing, numbering, resolve_item
and download_document all run. Every PDF carries the name of the document
it is, so a file is known by its bytes and never by its name.

The answers are the shapes the app was mapped against (direkt1822_site.py
and tests/test_postbox_api.py). Every customer number, id and date is
invented.
"""
import io
import json
import math
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest
from pypdf import PdfWriter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import direkt1822_docs as docs
import direkt1822_site as site
from paperpull_core import storage as core_storage
from paperpull_core.run_reporting import ListNotRead

pw_api = pytest.importorskip("playwright.sync_api")

APP = Path(__file__).resolve().parents[1]
BASE = "https://www.1822direkt-banking.de"

# Playwright's own Chromium, never a browser installed on this computer,
# with every name resolved to nowhere so a request the route does not
# answer cannot leave the machine.
ARGS = ["--disable-extensions", "--disable-sync", "--no-first-run",
        "--disable-background-networking", "--disable-component-update",
        "--no-proxy-server", "--host-resolver-rules=MAP * ~NOTFOUND"]

POSTBOX = "/ng-banking/banking/postbox"
API = "/JOBa1822Service/api/"
BOX = API + "postboxnachricht/"
FOLDERS = ("eingang", "ausgang", "papierkorb")
PAGE_HTML = """<!doctype html><html><head><title>Postbox</title></head>
<body><h1>Postbox</h1></body></html>"""
GONE = object()


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


def document(name, title="Kontoauszug 1/2031", at="2031-02-02T10:00:00", kind="MEGA",
             parts=1, pdf=True):
    """One row of a folder. `parts` is how many messages its conversation
    holds, and `pdf` whether the row offers a PDF of its own."""
    return {"doc": name, "title": title, "at": at, "kind": kind, "parts": parts, "pdf": pdf}


class Bank:
    """What the bank answers. A name in `refuse` answers that status, an
    endpoint by its name (benutzerInfo, eingang, ...) or a file by its
    document's name. A document in `not_pdf` answers an HTML page instead
    of its PDF, and once the document in `signs_out` is asked for, the bank
    answers as signed out from then on. `rows` changes a row's fields by
    its document's name (GONE leaves a field out), and `pages` and `user`
    do the same for a folder's page and for benutzerInfo. `ids` says how
    long an id lasts, "always" keeps the document's own name and "session"
    changes it with `new_session`."""

    def __init__(self):
        self.folders = {name: [] for name in FOLDERS}
        self.user = {"token": "INVENTED_TOKEN", "csrfToken": "INVENTED_CSRF",
                     "hatMehrereKundenverbindungen": False, "stammNrsDisplay": ["9999999999"]}
        self.rows = {}
        self.pages = {}
        self.refuse = {}
        self.not_pdf = set()
        self.signs_out = None
        self.ids = "always"
        self.session = 1
        self.asked = []
        self.fetched = []

    @property
    def inbox(self):
        return self.folders["eingang"]

    @inbox.setter
    def inbox(self, value):
        self.folders["eingang"] = value

    def new_session(self):
        self.session += 1

    def id_of(self, name: str) -> str:
        return "%s-s%d" % (name, self.session) if self.ids == "session" else name

    def name_of(self, ident: str) -> str:
        return ident.rsplit("-s", 1)[0] if self.ids == "session" else ident

    @staticmethod
    def changed(data: dict, change: dict) -> dict:
        for key, value in change.items():
            if value is GONE:
                data.pop(key, None)
            else:
                data[key] = value
        return data

    def _row(self, d):
        ident = self.id_of(d["doc"])
        row = {"id": "row-" + ident, "selectionId": "select-" + ident, "dokumentId": ident,
               "fileName": "Dokument %s.pdf" % d["doc"], "inhalt": d["title"],
               "kategorie": d["kind"], "erhaltenAm": d["at"], "pdfFile": d["pdf"],
               "htmlFile": not d["pdf"], "anzahlKorrespondenz": d["parts"]}
        return self.changed(row, self.rows.get(d["doc"], {}))

    def answer(self, route):
        request = route.request
        path = urlsplit(request.url).path
        if path == POSTBOX:
            return route.fulfill(status=200, content_type="text/html", body=PAGE_HTML)
        if path.startswith(BOX + "download/"):
            return self._file(route, path[len(BOX + "download/"):])
        if not path.startswith(API):
            return route.fulfill(status=404, content_type="text/plain", body="not found")
        endpoint = path.rsplit("/", 1)[-1]
        self.asked.append(endpoint)
        if endpoint in self.refuse:
            return route.fulfill(status=self.refuse[endpoint], content_type="text/html", body="no")
        if endpoint == "benutzerInfo" and request.method == "GET":
            data = {"jobaMeldungen": [], "benutzerInfo": dict(self.user)}
        elif endpoint in FOLDERS and request.method == "POST":
            data = self._page(endpoint, request.post_data_json)
        else:
            # leseUndVermerkeMitId, which opens a conversation and marks it
            # read, or anything else. The app must never ask for it.
            return route.fulfill(status=404, content_type="text/plain", body="not found")
        return route.fulfill(status=200, content_type="application/json", body=json.dumps(data))

    def _page(self, folder, body):
        listed = self.folders[folder]
        seite, size = int(body["seite"]), int(body["anzahlProSeite"])
        data = {"jobaMeldungen": [], "gesamtzahlNachrichten": len(listed),
                "gesamtzahlSeiten": math.ceil(len(listed) / size), "seite": seite,
                "postboxNachrichtListe": [self._row(d) for d in listed[seite * size:(seite + 1) * size]]}
        return self.changed(data, self.pages)

    def _file(self, route, rest):
        ident = unquote(rest.split("/", 1)[0])
        name = self.name_of(ident)
        self.fetched.append(name)
        if name in self.refuse:
            return route.fulfill(status=self.refuse[name], content_type="text/html", body="no")
        if name == self.signs_out:
            self.refuse = {"benutzerInfo": 401, **{folder: 401 for folder in FOLDERS}}
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
        self.config.update({"owner": "Erika Musterfrau", "output_dir": str(self.out),
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
        self.page.goto(BASE + POSTBOX)
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

    def stopped(self, *flags) -> str:
        """A run that stopped as signed out, with what it said."""
        with pytest.raises(SystemExit) as stop:
            self.run(*flags)
        assert stop.value.code == 0
        return " ".join(self.capsys.readouterr().out.split())

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

    def summary(self) -> str:
        return " ".join((self.out / "run-summary.txt").read_text(encoding="utf-8").split())


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

def test_discover_then_a_run_saves_every_folder_each_with_its_own_bytes(home):
    home.bank.folders["eingang"] = [document("P1"), document("T1", "Steuerbescheinigung 2030",
                                                             "2031-01-15T09:00:00", "JSTB")]
    home.bank.folders["ausgang"] = [document("S1", "Unterlagen", "2030-11-03T08:00:00", "BRIEF")]
    home.bank.folders["papierkorb"] = [document("A1", "Kontoauszug 4/2019", "2019-05-03T08:00:00")]
    code, _said = home.run("--discover")
    assert code == 0
    assert home.listed_whole()
    assert len(home.store("discovery.json")) == 4
    assert home.bank.fetched == []
    code, _said = home.run_all()
    assert code == 0
    assert home.on_disk() == ["A1", "P1", "S1", "T1"]
    assert sorted(home.held().values()) == ["A1", "P1", "S1", "T1"]
    assert home.listed_whole()


def test_a_second_run_skips_what_was_saved(home):
    home.bank.inbox = [document("P2", "Kontoauszug 2/2031", "2031-03-02T10:00:00"), document("P1")]
    code, _said = home.run_all()
    assert code == 0
    assert home.on_disk() == ["P1", "P2"]
    code, said = home.run_all()
    assert code == 0
    assert home.bank.fetched == []
    assert said.count("Already downloaded and verified - skipping.") == 2
    assert home.on_disk() == ["P1", "P2"]


def test_a_list_longer_than_a_page_is_read_to_its_end(home):
    home.bank.inbox = [document("P%03d" % n, "Mitteilung %d" % n, kind="INFO")
                       for n in range(120)]
    code, _said = home.run("--discover")
    assert code == 0
    assert len(home.store("discovery.json")) == 120
    assert home.bank.asked.count("eingang") == 3
    assert home.listed_whole()


def test_an_empty_postbox_is_listed_whole(home):
    code, _said = home.run("--discover")
    assert code == 0
    assert home.listed_whole()


# -- conversations are never opened ----------------------------------------------

def test_a_thread_and_a_message_without_a_pdf_are_counted_and_nothing_stops(home):
    """A thread stopped the whole list unless the conversation was opened,
    which marks it read at the bank. Its row's own PDF is saved, it and the
    message with no PDF are counted and said, and nothing is opened."""
    home.bank.inbox = [document("T1", "Ihre Anfrage", "2031-03-02T10:00:00", "MITT", parts=3),
                       document("M1", "Information", "2031-02-20T10:00:00", "INFO", pdf=False),
                       document("P1")]
    code, said = home.run_all()
    assert code == 0
    assert home.on_disk() == ["P1", "T1"]
    assert "M1" not in home.bank.fetched
    assert set(home.bank.asked) <= {"benutzerInfo", *FOLDERS}
    told = ("1 conversation(s) of more than one message and 1 message(s) with no PDF of "
            "their own were not opened, since opening one marks it read at the bank.")
    assert told in said
    assert "further attachments in it are not read" in said
    assert "Conversations not opened: 2" in home.summary()
    assert told in home.summary()
    assert home.listed_whole()


def test_login_answers_success_for_an_account_with_threads(home):
    home.bank.inbox = [document("T1", "Ihre Anfrage", parts=2), document("P1")]
    code, said = home.run("--login")
    assert code == 0
    assert "Success" in said


def test_a_run_with_nothing_unopened_says_nothing_of_conversations(home):
    home.bank.inbox = [document("P1")]
    code, said = home.run_all()
    assert code == 0
    assert "not opened" not in said
    assert "Conversations not opened: 0" in home.summary()


# -- a missing field stops the list ------------------------------------------------

@pytest.mark.parametrize("where,change", [
    ("row", {"pdfFile": GONE}),
    ("row", {"pdfFile": "true"}),
    ("row", {"anzahlKorrespondenz": GONE}),
    ("row", {"anzahlKorrespondenz": "2"}),
    ("user", {"hatMehrereKundenverbindungen": GONE}),
    ("user", {"stammNrsDisplay": GONE}),
    ("page", {"gesamtzahlNachrichten": GONE}),
    ("page", {"gesamtzahlSeiten": GONE}),
], ids=lambda value: value if isinstance(value, str) else "-".join(value))
def test_a_missing_field_stops_the_listing_rather_than_read_as_nothing_there(home, where, change):
    """A row with no pdfFile read as a message without a PDF, so three
    statements were lost from a list still called whole."""
    home.bank.inbox = [document("P2", "Kontoauszug 2/2031", "2031-03-02T10:00:00"), document("P1")]
    if where == "row":
        home.bank.rows = {"P2": change}
    elif where == "user":
        Bank.changed(home.bank.user, change)
    else:
        home.bank.pages = change
    discover_stops(home)
    assert home.bank.fetched == []


@pytest.mark.parametrize("endpoint", ["benutzerInfo", "eingang", "ausgang", "papierkorb"])
def test_a_part_of_the_list_that_answers_500_stops_the_listing(home, endpoint):
    home.bank.inbox = [document("P1")]
    home.bank.refuse = {endpoint: 500}
    discover_stops(home)


def test_a_list_that_stops_while_documents_download_stops_the_run_once(home):
    """A download reads the list again. When that stops, every document
    after it would read the same list, so the run stops at the first with
    nothing recorded against it, and leaves with its list unread (#124)."""
    home.bank.inbox = [document("P2", "Kontoauszug 2/2031", "2031-03-02T10:00:00"), document("P1")]
    home.run("--discover")
    assert home.listed_whole()
    home.bank.refuse = {"eingang": 500}
    with pytest.raises(ListNotRead):
        home.run("--resume")
    assert home.bank.fetched == []
    assert home.store("progress.json") == {}
    assert not home.listed_whole()


# -- one document that will not download ----------------------------------------

@pytest.mark.parametrize("how", ["http_403", "http_401", "http_500", "not_a_pdf"])
def test_one_document_without_a_pdf_fails_alone_and_the_run_goes_on(home, how):
    """A 401 or a 403 for one PDF read as a sign-out and stopped every run
    at that document. Runs go newest first, so nothing older was ever saved.
    The list is read again, and while it still answers only that document
    fails."""
    home.bank.inbox = [document("P2", "Kontoauszug 2/2031", "2031-03-02T10:00:00"), document("P1")]
    if how.startswith("http_"):
        home.bank.refuse = {"P2": int(how[5:])}
    else:
        home.bank.not_pdf = {"P2"}
    code, said = home.run_all()
    assert code == 1
    assert home.bank.fetched == ["P2", "P1"]
    assert home.on_disk() == ["P1"]
    assert home.states() == {"P2": "Failed", "P1": "Completed"}
    assert "Nothing was saved, and the next run tries it again" in said
    assert "Your session has expired" not in said
    assert home.listed_whole()
    home.bank.refuse, home.bank.not_pdf = {}, set()
    code, _said = home.run_all()
    assert code == 0
    assert home.on_disk() == ["P1", "P2"]


def test_a_signed_out_answer_stops_the_run_with_nothing_recorded_against_it(home):
    home.bank.inbox = [document("P2", "Kontoauszug 2/2031", "2031-03-02T10:00:00"), document("P1")]
    home.run("--discover")
    home.bank.refuse = {"benutzerInfo": 401}
    said = home.stopped("--resume")
    assert "Your session has expired" in said
    assert home.bank.fetched == []
    assert home.on_disk() == []
    assert "Completed" not in home.states().values()


def test_a_sign_in_page_in_place_of_a_pdf_stops_the_run_when_the_list_answers_signed_out(home):
    """A sign-in page served with 200 in place of the PDF says nothing a
    file can tell. The list is read again, and its answer as signed out
    stops the run there, rather than fail every document after it one by
    one."""
    home.bank.inbox = [document("P3", "Kontoauszug 3/2031", "2031-04-02T10:00:00"),
                       document("P2", "Kontoauszug 2/2031", "2031-03-02T10:00:00"), document("P1")]
    home.run("--discover")
    home.bank.signs_out = "P3"
    said = home.stopped("--resume")
    assert "Your session has expired" in said
    assert home.bank.fetched == ["P3"]
    assert home.on_disk() == []
    assert set(home.states().values()) <= {"Discovered"}


def test_a_403_on_a_pdf_after_the_session_ended_stops_as_signed_out(home):
    """The same refusal with the session really ended. The list read again
    answers signed out too, and that stops the run."""
    home.bank.inbox = [document("P2", "Kontoauszug 2/2031", "2031-03-02T10:00:00"), document("P1")]
    home.run("--discover")
    original = home.bank._file

    def refused_then_signed_out(route, rest):
        home.bank.refuse = {"benutzerInfo": 401, "P2": 403}
        return original(route, rest)
    home.bank._file = refused_then_signed_out
    said = home.stopped("--resume")
    assert "Your session has expired" in said
    assert home.bank.fetched == ["P2"]
    assert home.on_disk() == []


# -- each document's own bytes ----------------------------------------------------

def test_a_stored_id_the_list_still_shows_beats_the_place(home):
    """Two notes of one day and one title. The list came back in the other
    order, and a place would hand each the other's bytes."""
    home.bank.inbox = [document("K1", "Information", kind="INFO"),
                       document("K2", "Information", kind="INFO")]
    home.run("--discover")
    numbered = {key: rec["item_id"] for key, rec in home.store("discovery.json").items()}
    assert sorted(numbered.values()) == ["K1", "K2"]
    home.bank.inbox.reverse()
    home.run("--resume")
    assert home.held() == numbered


def test_a_listing_in_another_order_leaves_each_number_with_its_document(home):
    """The first saved, the second failed, and the next list reversed. Each
    number stays with the id it was given to (keys.told_apart)."""
    home.bank.inbox = [document("K1", "Information", kind="INFO"),
                       document("K2", "Information", kind="INFO")]
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
    home.bank.inbox = [document("K1", "Information", kind="INFO"),
                       document("K2", "Information", kind="INFO")]
    home.bank.not_pdf = {"K2"}
    home.run_all()
    home.bank.not_pdf = set()
    home.bank.new_session()
    home.bank.inbox.reverse()
    code, _said = home.run_all()
    assert code == 1
    assert home.on_disk() == ["K1"]


def test_a_kontoauszug_the_bank_tags_as_another_kind_is_saved_once(home):
    """ADV is an Other Document, and its title says Kontoauszug, so its
    record is a Statement. The download looked for an Other Document, found
    no row, and the document failed on every run, never saved."""
    home.bank.inbox = [document("A1", "Kontoauszug 3/2031", "2031-04-02T10:00:00", "ADV"),
                       document("P1")]
    code, _said = home.run_all()
    assert code == 0
    assert home.on_disk() == ["A1", "P1"]
    assert home.states() == {"A1": "Completed", "P1": "Completed"}
    assert {rec["category"] for rec in home.store("discovery.json").values()} == {"Statement"}
    code, said = home.run_all()
    assert code == 0
    assert home.bank.fetched == []
    assert said.count("Already downloaded and verified - skipping.") == 2
    assert home.on_disk() == ["A1", "P1"]


def test_a_document_gone_from_the_list_fails_and_says_so(home):
    home.bank.inbox = [document("P1")]
    home.run("--discover")
    home.bank.inbox = []
    code, _said = home.run("--resume")
    assert code == 1
    assert home.bank.fetched == []
    notes = [rec.get("notes", "") for rec in home.store("progress.json").values()]
    assert any("no longer shows this document" in n for n in notes)


# -- dates --------------------------------------------------------------------------

def test_a_document_received_after_midnight_in_berlin_is_filed_under_that_day(home):
    home.bank.inbox = [document("P1", at="2031-02-28T23:30:00Z")]
    home.run_all()
    dates = {rec["date"] for rec in home.store("discovery.json").values()}
    assert dates == {"2031-03-01"}
    assert [p.name[:10] for p in home.out.rglob("*.pdf")] == ["2031-03-01"]


def test_a_time_with_no_zone_keeps_the_day_written(home):
    home.bank.inbox = [document("P1", at="2031-02-28T23:30:00")]
    home.run("--discover")
    dates = {rec["date"] for rec in home.store("discovery.json").values()}
    assert dates == {"2031-02-28"}


# -- the sign-in -----------------------------------------------------------------

@pytest.mark.parametrize("status,claims", [(200, True), (401, False), (500, False)])
def test_login_says_success_only_when_the_list_answers(home, status, claims):
    """A www.1822direkt-banking.de address with no sign-in form on it says
    nothing of the session. Only the list answering does."""
    if status != 200:
        home.bank.refuse = {"eingang": status}
    code, said = home.run("--login")
    assert code == 0
    assert ("Success" in said) is claims
