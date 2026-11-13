"""Amazon Visa's own main against a made-up portal, in a browser.

Each run goes through the app's main as the panel starts it, with its real
stores, index and files and a made-up config and output folder. The page is
Playwright's own Chromium on the portal's address, every request answered by
the route below and every name resolved to nowhere. The page offers the
webpack runtime and the client module the app's page script asks for
(module 17724, its export Tz), so that script runs as it does at the portal,
and its listing, numbering, resolve_item and download_document all run.
Every PDF carries the name of the document it is, so a file is known by its
bytes and never by its name.

The answers are the shapes the app was mapped against (amazonvisa_site.py
and tests/test_portal.py). Every contract, id and date is invented.
"""
import io
import json
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

import pytest
from pypdf import PdfWriter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import amazonvisa_docs as docs
import amazonvisa_site as site
from paperpull_core import storage as core_storage
from paperpull_core.run_reporting import ListNotRead

pw_api = pytest.importorskip("playwright.sync_api")

APP = Path(__file__).resolve().parents[1]
CARD = "C0000000001111"
OTHER_CARD = "C0000000002222"
BUCKET = "prod-de-mbgdcs-documents01.s3.eu-west-1.amazonaws.com"

# Playwright's own Chromium, never a browser installed on this computer,
# with every name resolved to nowhere so a request the route does not
# answer cannot leave the machine.
ARGS = ["--disable-extensions", "--disable-sync", "--no-first-run",
        "--disable-background-networking", "--disable-component-update",
        "--no-proxy-server", "--host-resolver-rules=MAP * ~NOTFOUND"]

PAGE = "/amazon/documentation"
# The portal's client as the app's page script finds it, through the
# webpack runtime its chunks are pushed to. Each call goes to a made-up
# address below /api/ on the portal's host and answers [data, meta] as the
# real one does.
PAGE_HTML = """<!doctype html><html><head><title>Dokumente</title></head>
<body><h1>Dokumente</h1><script>
const client = {get: async ({endpoint, pathParams = {}, queryParams = {}}) => {
  const path = endpoint.replace(/:(\\w+)/g, (all, name) => encodeURIComponent(pathParams[name]));
  const query = new URLSearchParams();
  for (const [name, value] of Object.entries(queryParams))
    for (const one of [].concat(value)) query.append(name, String(one));
  const response = await fetch("/api/" + path + (String(query) ? "?" + query : ""));
  const type = response.headers.get("content-type") || "";
  const data = type.includes("json") ? await response.json() : await response.text();
  return [data, {status: response.status}];
}};
window.webpackChunk_openbank_ui_clients = {push: (chunk) =>
  chunk[2]((id) => id === 17724 ? {Tz: client} : undefined)};
</script></body></html>"""

# Every call the portal answers, by the name this file gives it.
ENDPOINTS = ("position", "statements", "categories", "documents", "ticket")


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


def statement(name, day="2031-02-02", version="1"):
    return {"documentId": name, "version": version, "statementDate": day}


def document(name, day="2031-02-02", extension=".pdf"):
    return {"id": name, "date": day, "fileExtension": extension}


class Portal:
    """What the portal answers. `statements` holds each contract's rows and
    `categories` each category's documents. A name in `refuse` answers that
    status, an endpoint by its name in ENDPOINTS or a ticket by its
    document's name. A ticket of a document in `signin` answers a sign-in
    page with 200, a document in `no_link` gets a ticket with no link in
    it, and a document in `not_pdf` an HTML page from the store. Once the
    ticket of the document in `signs_out` is asked for, every call answers
    401 from then on, and that ticket answers `signs_out_as`. `bend` changes
    an endpoint's answer before it goes out. `ids` says how long an id
    lasts, "always" keeps the document's own name and "session" changes it
    with `new_session`."""

    def __init__(self):
        self.cards = [CARD]
        self.statements = {CARD: []}
        self.categories = {}
        self.refuse = {}
        self.signin = set()
        self.no_link = set()
        self.not_pdf = set()
        self.signs_out = None
        self.signs_out_as = 200
        self.bend = {}
        self.ids = "always"
        self.session = 1
        self.asked = []
        self.fetched = []
        self.stored = []

    def new_session(self):
        self.session += 1

    def id_of(self, name: str) -> str:
        return "%s-s%d" % (name, self.session) if self.ids == "session" else name

    def name_of(self, ident: str) -> str:
        return ident.rsplit("-s", 1)[0] if self.ids == "session" else ident

    def answer(self, route):
        request = route.request
        parts = urlsplit(request.url)
        if parts.hostname == BUCKET:
            return self._file(route, unquote(parts.path.lstrip("/")).rsplit(".", 1)[0])
        if parts.path == PAGE:
            return route.fulfill(status=200, content_type="text/html", body=PAGE_HTML)
        if not parts.path.startswith("/api/"):
            return route.fulfill(status=404, content_type="text/plain", body="not found")
        endpoint, ident, how = self._endpoint(unquote(parts.path[len("/api/"):]))
        self.asked.append(endpoint)
        if endpoint == "ticket":
            name = self.name_of(ident)
            self.fetched.append(name)
            if name == self.signs_out:
                self.refuse = {e: 401 for e in ENDPOINTS}
                if self.signs_out_as == 200:
                    return self._sign_in(route)
                return route.fulfill(status=self.signs_out_as, content_type="text/html", body="no")
            if name in self.refuse:
                return route.fulfill(status=self.refuse[name], content_type="text/html", body="no")
            if name in self.signin:
                return self._sign_in(route)
        if endpoint in self.refuse:
            return route.fulfill(status=self.refuse[endpoint], content_type="text/html", body="no")
        data = self._json(endpoint, ident, how, parse_qs(parts.query))
        if endpoint in self.bend:
            data = self.bend[endpoint](data)
        return route.fulfill(status=200, content_type="application/json", body=json.dumps(data))

    @staticmethod
    def _sign_in(route):
        return route.fulfill(status=200, content_type="text/html",
                             body="<html><form><input type=password></form></html>")

    @staticmethod
    def _endpoint(path):
        if path == "cb-api-global-position/v3/global-position":
            return "position", None, None
        m = re.fullmatch(r"cb-api-cards-contra/v1/card-contracts/([^/]+)/statements", path)
        if m:
            return "statements", m.group(1), None
        if path == "cb-api-doc-manager/v4/categories":
            return "categories", None, None
        if path == "cb-api-doc-manager/v4/documents":
            return "documents", None, None
        m = re.fullmatch(r"cb-api-doc-manager/v4/documents/uri/([^/]+)", path)
        if m:
            return "ticket", m.group(1), "uri"
        m = re.fullmatch(r"mb-api-documents/v2/documents/([^/]+)/versions/([^/]+)", path)
        if m:
            return "ticket", m.group(1), "version"
        raise AssertionError("unexpected address %s" % path)

    def _json(self, endpoint, ident, how, query):
        if endpoint == "position":
            return {"resource": {"cardsInfo": {"cards": [{"cardContractId": c}
                                                         for c in self.cards]}}}
        if endpoint == "statements":
            rows = []
            for row in self.statements.get(ident, []):
                row = dict(row)
                if row.get("documentId"):
                    row["documentId"] = self.id_of(row["documentId"])
                rows.append(row)
            return {"elements": rows, "metadata": {"hasPendingRecords": False}}
        if endpoint == "categories":
            return {"categories": list(self.categories)}
        if endpoint == "documents":
            assert query["limit"] == ["100"]
            rows = [dict(row, id=self.id_of(row["id"]))
                    for row in self.categories[query["categories"][0]]]
            return {"documents": rows, "size": len(rows)}
        # A ticket, which holds the store's signed address of the PDF.
        name = self.name_of(ident)
        if name in self.no_link:
            return {}
        signed = "https://%s/%s.pdf?X-Amz-Signature=INVENTED_SIGNATURE" % (BUCKET, ident)
        return {"documentUri": signed} if how == "version" else {"uri": signed}

    def _file(self, route, ident):
        name = self.name_of(ident)
        self.stored.append(name)
        cors = {"Access-Control-Allow-Origin": "*"}
        if name in self.not_pdf:
            return route.fulfill(status=200, content_type="text/html", headers=cors,
                                 body="<html>Anmelden</html>")
        return route.fulfill(status=200, content_type="application/pdf", headers=cors,
                             body=pdf_of(name))


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
        self.bank = Portal()
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
        self.page.goto("https://kunden.openbankpay.com" + PAGE)
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
        self.bank.stored = []
        site._cache = None
        site._summary = {}
        code = docs.main(["--config", str(self.cfg), *flags])
        return code, " ".join(self.capsys.readouterr().out.split())

    def run_all(self, *flags):
        return self.run("--all", "--yes", *flags)

    def stops(self, *flags) -> str:
        """A run that stopped as one that stopped, and what it said."""
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


def two_statements(home):
    """A newer and an older statement of one card, the newer asked for first."""
    home.bank.statements = {CARD: [statement("S2", "2031-03-02"), statement("S1")]}


# -- a run that reads everything -------------------------------------------------

def test_discover_then_a_run_saves_every_statement_and_document_with_its_own_bytes(home):
    home.bank.cards = [CARD, OTHER_CARD, CARD]
    home.bank.statements = {CARD: [statement("S1"), statement(None, version=None)],
                            OTHER_CARD: [statement("S3", "2031-01-02")]}
    home.bank.categories = {"cat_contratos": [document("V1", "2029-05-03")],
                            "cat_sonstige": [document("D1"), document("H1", extension=".html"),
                                             document("S1")]}
    code, said = home.run("--discover")
    assert code == 0
    assert home.listed_whole()
    assert sorted(rec["item_id"] for rec in home.store("discovery.json").values()) == [
        "document:D1", "document:V1", "statement:S1:1", "statement:S3:1"]
    assert "1 document(s) are not PDFs" in said
    assert "1 statement(s) have no PDF available yet" in said
    assert home.bank.fetched == []
    code, _said = home.run_all()
    assert code == 0
    assert home.on_disk() == ["D1", "S1", "S3", "V1"]
    assert sorted(home.held().values()) == ["D1", "S1", "S3", "V1"]
    assert "H1" not in home.bank.fetched
    folders = {whose(p.read_bytes()): p.parent.name for p in home.out.rglob("*.pdf")}
    assert folders == {"S1": "Kreditkartenabrechnungen", "S3": "Kreditkartenabrechnungen",
                       "V1": "Vertragsinformationen", "D1": "Sonstige Dokumente"}
    assert "INVENTED_SIGNATURE" not in json.dumps(home.store("progress.json"))


def test_two_cards_statements_of_one_day_are_two_documents(home):
    home.bank.cards = [CARD, OTHER_CARD]
    home.bank.statements = {CARD: [statement("S1")], OTHER_CARD: [statement("S2")]}
    code, _said = home.run_all()
    assert code == 0
    assert home.on_disk() == ["S1", "S2"]
    accounts = {rec["account"] for rec in home.store("discovery.json").values()}
    assert accounts == {"Vertrag 1111", "Vertrag 2222"}


def test_two_statements_alike_are_each_saved_with_their_own_bytes(home):
    home.bank.statements = {CARD: [statement("S1"), statement("S2")]}
    code, _said = home.run_all()
    assert code == 0
    assert home.on_disk() == ["S1", "S2"]
    numbered = {key: rec["item_id"] for key, rec in home.store("discovery.json").items()}
    assert {key: "statement:%s:1" % name for key, name in home.held().items()} == numbered


def test_a_category_document_is_asked_for_by_its_own_ticket(home):
    home.bank.categories = {"cat_contratos": [document("V1")]}
    code, _said = home.run_all()
    assert code == 0
    assert home.on_disk() == ["V1"]
    assert home.bank.fetched == ["V1"]
    assert [p.parent.name for p in home.out.rglob("*.pdf")] == ["Vertragsinformationen"]


def test_an_empty_portal_with_one_card_is_listed_whole(home):
    code, _said = home.run("--discover")
    assert code == 0
    assert home.listed_whole()


def test_a_second_run_skips_what_was_saved(home):
    two_statements(home)
    home.bank.categories = {"cat_contratos": [document("V1")]}
    code, _said = home.run_all()
    assert code == 0
    assert home.on_disk() == ["S1", "S2", "V1"]
    code, said = home.run_all()
    assert code == 0
    assert home.bank.fetched == [] and home.bank.stored == []
    assert said.count("Already downloaded and verified - skipping.") == 3
    assert home.on_disk() == ["S1", "S2", "V1"]


# -- one document that will not download ----------------------------------------

@pytest.mark.parametrize("how", ["ticket_403", "ticket_401", "ticket_500", "sign_in_page",
                                 "no_link", "not_a_pdf"])
def test_one_document_without_a_pdf_fails_alone_and_the_run_goes_on(home, how):
    """A 401 or 403 on one document's ticket read as signed out and stopped
    every run there, and since runs go newest first nothing older was ever
    saved. The list read again still answers, so that one document fails
    and the run goes on."""
    two_statements(home)
    if how.startswith("ticket_"):
        home.bank.refuse = {"S2": int(how[-3:])}
    elif how == "sign_in_page":
        home.bank.signin = {"S2"}
    elif how == "no_link":
        home.bank.no_link = {"S2"}
    else:
        home.bank.not_pdf = {"S2"}
    code, said = home.run_all()
    assert code == 1
    assert home.on_disk() == ["S1"]
    assert home.states() == {"statement:S2:1": "Failed", "statement:S1:1": "Completed"}
    assert "Nothing was saved, and the next run tries it again" in said
    assert "Your session has expired" not in said
    assert home.listed_whole()
    home.bank.refuse, home.bank.signin, home.bank.no_link, home.bank.not_pdf = {}, set(), set(), set()
    code, _said = home.run_all()
    assert code == 0
    assert home.on_disk() == ["S1", "S2"]


@pytest.mark.parametrize("answer", [200, 401, 403])
def test_a_refused_ticket_stops_the_run_when_the_list_answers_signed_out(home, answer):
    """A sign-in page in place of a ticket, or a 401 or 403 on it, after the
    session ended. The list is read again, and its answer as signed out
    stops the run there with nothing recorded against the document, rather
    than fail every document after it one by one."""
    home.bank.statements = {CARD: [statement("S3", "2031-04-02"), statement("S2", "2031-03-02"),
                                   statement("S1")]}
    home.run("--discover")
    home.bank.signs_out, home.bank.signs_out_as = "S3", answer
    said = home.stops("--resume")
    assert "Your session has expired" in said
    assert home.bank.fetched == ["S3"]
    assert home.bank.stored == []
    assert home.on_disk() == []
    assert set(home.states().values()) <= {"Discovered"}


def test_a_document_gone_from_the_list_fails_and_says_so(home):
    home.bank.statements = {CARD: [statement("S1")]}
    home.run("--discover")
    home.bank.statements = {CARD: []}
    code, _said = home.run("--resume")
    assert code == 1
    assert home.bank.fetched == []
    notes = [rec.get("notes", "") for rec in home.store("progress.json").values()]
    assert any("no longer shows this document" in n for n in notes)


# -- each document's own bytes ----------------------------------------------------

def test_a_stored_id_the_list_still_shows_beats_the_place(home):
    """Two statements of one card and one day. The list came back in the
    other order, and a place would hand each the other's bytes."""
    home.bank.statements = {CARD: [statement("S1"), statement("S2")]}
    home.run("--discover")
    numbered = {key: rec["item_id"] for key, rec in home.store("discovery.json").items()}
    assert sorted(numbered.values()) == ["statement:S1:1", "statement:S2:1"]
    home.bank.statements[CARD].reverse()
    home.run("--resume")
    assert {key: "statement:%s:1" % name for key, name in home.held().items()} == numbered


def test_a_listing_in_another_order_leaves_each_number_with_its_document(home):
    """The first saved, the second failed, and the next list reversed. Each
    number stays with the id it was given to (keys.told_apart)."""
    home.bank.statements = {CARD: [statement("S1"), statement("S2")]}
    home.bank.not_pdf = {"S2"}
    home.run_all()
    assert home.on_disk() == ["S1"]
    home.bank.not_pdf = set()
    home.bank.statements[CARD].reverse()
    home.run_all()
    assert home.on_disk() == ["S1", "S2"]
    assert sorted(home.held().values()) == ["S1", "S2"]


def test_a_twin_beside_one_saved_fails_when_its_id_did_not_last(home):
    """Which of the two rows is the saved one cannot be told, so guessing
    would save that one twice and the other never."""
    home.bank.ids = "session"
    home.bank.statements = {CARD: [statement("S1"), statement("S2")]}
    home.bank.not_pdf = {"S2"}
    home.run_all()
    home.bank.not_pdf = set()
    home.bank.new_session()
    home.bank.statements[CARD].reverse()
    code, _said = home.run_all()
    assert code == 1
    assert home.on_disk() == ["S1"]


# -- the list is whole or it is not called whole --------------------------------

def test_a_signed_out_list_stops_discover_as_signed_out(home):
    home.bank.statements = {CARD: [statement("S1")]}
    home.bank.refuse = {"position": 401}
    said = home.stops("--discover")
    assert "answered the list as signed out" in said
    assert not home.listed_whole()
    assert home.store("discovery.json") == {}


@pytest.mark.parametrize("endpoint", ["position", "statements", "categories", "documents"])
def test_a_part_of_the_list_that_answers_500_stops_the_listing(home, endpoint):
    home.bank.statements = {CARD: [statement("S1")]}
    home.bank.categories = {"cat_contratos": [document("V1")]}
    home.bank.refuse = {endpoint: 500}
    discover_stops(home)


def _without(*keys):
    def bend(data):
        data["elements"] = [{k: v for k, v in row.items() if k not in keys}
                            for row in data["elements"]]
        return data
    return bend


MISSING = {
    # A statement row without the fields that say which PDF it is.
    "statement_without_its_fields": ("statements", _without("documentId", "version")),
    "statement_without_its_id": ("statements", _without("documentId")),
    "statement_without_its_version": ("statements", _without("version")),
    "statements_still_pending": ("statements",
                                 lambda d: dict(d, metadata={"hasPendingRecords": True})),
    "statements_without_their_metadata": ("statements", lambda d: dict(d, metadata={})),
    "statements_without_their_list": ("statements", lambda d: {"metadata": d["metadata"]}),
    # Whoever is signed in holds at least one card.
    "no_card": ("position", lambda d: {"resource": {"cardsInfo": {"cards": []}}}),
    "no_card_list": ("position", lambda d: {"resource": {}}),
    "categories_without_their_list": ("categories", lambda d: {}),
    "category_without_its_documents": ("documents", lambda d: {"size": d["size"]}),
    "category_without_its_size": ("documents", lambda d: {"documents": d["documents"]}),
    "category_whose_size_disagrees": ("documents", lambda d: dict(d, size=d["size"] + 1)),
    "document_without_its_file_type": ("documents", lambda d: dict(
        d, documents=[{"id": r["id"], "date": r["date"]} for r in d["documents"]])),
}


@pytest.mark.parametrize("missing", sorted(MISSING))
def test_a_missing_field_stops_the_listing_rather_than_read_as_nothing_there(home, missing):
    home.bank.statements = {CARD: [statement("S1")]}
    home.bank.categories = {"cat_contratos": [document("V1")]}
    endpoint, bend = MISSING[missing]
    home.bank.bend = {endpoint: bend}
    discover_stops(home)


@pytest.mark.parametrize("count,whole", [(99, True), (100, False)])
def test_a_category_that_fills_the_answer_stops_the_listing(home, count, whole):
    """The size may count only the documents that came back, so an answer
    holding as many as were asked for may have been cut there."""
    home.bank.categories = {"cat_sonstige": [
        document("D%03d" % n, "2031-%02d-%02d" % (1 + n // 28, 1 + n % 28))
        for n in range(count)]}
    if whole:
        code, _said = home.run("--discover")
        assert code == 0
        assert home.listed_whole()
        assert len(home.store("discovery.json")) == count
    else:
        discover_stops(home)


def test_a_list_that_stops_while_documents_download_stops_the_run_once(home):
    """A download reads the list again. When that stops, every document
    after it would read the same list, so the run stops at the first with
    nothing recorded against it, and leaves with its list unread (#124)."""
    two_statements(home)
    home.run("--discover")
    assert home.listed_whole()
    home.bank.refuse = {"statements": 500}
    with pytest.raises(ListNotRead):
        home.run("--resume")
    assert home.bank.fetched == []
    assert home.store("progress.json") == {}
    assert not home.listed_whole()


# -- dates --------------------------------------------------------------------------

@pytest.mark.parametrize("stamp,day", [
    ("2031-02-28T23:30:00Z", "2031-03-01"),
    ("2031-06-30T22:30:00.000+0000", "2031-07-01"),
    ("2031-06-30T21:30:00+00:00", "2031-06-30"),
    ("2031-03-01", "2031-03-01"),
])
def test_a_statement_stamped_after_midnight_in_berlin_is_filed_under_that_day(home, stamp, day):
    home.bank.statements = {CARD: [statement("S1", stamp)]}
    code, _said = home.run_all()
    assert code == 0
    assert {rec["date"] for rec in home.store("discovery.json").values()} == {day}
    assert [p.name[:10] for p in home.out.rglob("*.pdf")] == [day]


# -- the sign-in -----------------------------------------------------------------

@pytest.mark.parametrize("status,claims", [(200, True), (401, False), (500, False)])
def test_login_says_success_only_when_the_list_answers(home, status, claims):
    """A kunden.openbankpay.com address with no sign-in form on it says
    nothing of the session. Only the list answering does."""
    if status != 200:
        home.bank.refuse = {"position": status}
    code, said = home.run("--login")
    assert code == 0
    assert ("Success" in said) is claims
