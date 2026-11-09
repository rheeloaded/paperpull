"""Fidelity's own main against a made-up Document Access Hub.

Each run goes through the app's main as the panel starts it, with its real
stores, index and files and a made-up config and output folder. Only the
fetch made inside the page is stood in, so the app's own numbering, listing,
resolve_item and fetch_pdf all run. Every PDF carries the id of the document
it is, so a file is known by its bytes and never by its name.

The rows are the shapes the app was mapped against, and for a tax form the
shape in #145's fixtures and text, with docDetail and acctDetails nested. A
tax form's download answer is invented, the same as a statement's, because
nobody has shown one. Every account, id and date is invented too.
"""
import base64
import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from pypdf import PdfWriter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import fidelity_docs as docs
import fidelity_site as site
from paperpull_core import storage as core_storage
from paperpull_core.run_reporting import ListNotRead

APP = Path(__file__).resolve().parents[1]

ONE = {"acctNum": "400000011", "acctType": "Brokerage", "name": "Individual"}
TWO = {"acctNum": "400000022", "acctType": "Brokerage", "name": "Roth"}

MONTH_END = "2031-08-31"
STATEMENT = "Statement:%s:Monthly Statement" % MONTH_END
FORM_DAY = "2031-01-31"
FORM = "Tax Document:%s:2030 Form 1099-R" % FORM_DAY


def pdf_of(document: str) -> bytes:
    """A PDF that opens, with a page, carrying which document it is."""
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.add_metadata({"/Subject": "document %s" % document})
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue().ljust(4000, b" ")


def whose(body: bytes) -> str:
    return body.split(b"(document ", 1)[1].split(b")", 1)[0].decode()


def midnight_eastern(day: str) -> int:
    year, month, date = (int(part) for part in day.split("-"))
    return int(datetime(year, month, date, 4, tzinfo=timezone.utc).timestamp())


def statement(document, account=None, end=MONTH_END, start="2031-08-01", pdf=True):
    return {"document": document, "account": account, "start": start, "end": end, "pdf": pdf}


def form(document, account=None, year=2030, day=FORM_DAY, name="Form 1099-R"):
    return {"document": document, "account": account, "year": year, "day": day, "name": name}


class Hub:
    """What the page's fetch answers. A year in `refuse_year` answers that
    status for that kind. A document in `empty` answers no content.

    `ids` says how long an id lasts. "always" keeps the document's own name,
    "session" changes it with `new_session`, and "list" changes it with
    every list given. An id that is no longer good is refused."""

    def __init__(self):
        self.accounts = [ONE, TWO]
        self.statements = []
        self.confirmations = []
        self.forms = []
        self.ids = "always"
        self.session = 1
        self.lists = 0
        self.empty = set()
        self.refuse_year = {}
        self.fetched = []
        self.tax_years_asked = []
        self.shared_id = ""

    def new_session(self):
        self.session += 1

    def id_of(self, document: str) -> str:
        if self.shared_id:
            return self.shared_id
        if self.ids == "session":
            return "%s.s%d" % (document, self.session)
        if self.ids == "list":
            return "%s.l%d" % (document, self.lists)
        return document

    def _statement_row(self, item):
        row = {"id": self.id_of(item["document"]), "type": "PI Monthly/Quarterly Statement",
               "periodStartDate": midnight_eastern(item["start"]),
               "periodEndDate": midnight_eastern(item["end"]),
               "generatedDate": midnight_eastern(item["end"]),
               "formatTypes": {"formatType": {"isPDF": item["pdf"]}}}
        if item["account"]:
            row["acctNum"] = item["account"]["acctNum"]
        return row

    def _form_row(self, item):
        row = {"docName": item["name"],
               "docDetail": {"docId": self.id_of(item["document"]), "docType": "7131",
                             "docPeriodStartDate": midnight_eastern(item["day"]),
                             "docPeriodEndDate": midnight_eastern(item["day"]),
                             "docGeneratedDate": midnight_eastern(item["day"])}}
        if item["account"]:
            row["acctDetails"] = {"acctDetail": [
                {"nickname": "Nick", "acctNum": item["account"]["acctNum"],
                 "acctType": item["account"]["acctType"]}]}
        return row

    def answer(self, page, js, arg=None, limit=None):
        url, body = arg["url"], arg["body"]
        tail = url.rsplit("/", 1)[-1]
        if tail == "accounts":
            return {"status": 200, "json": {"acctDetails": [
                {"acctNum": a["acctNum"], "acctType": a["acctType"],
                 "preferenceDetail": {"name": a["name"]}} for a in self.accounts]}}
        if tail == "statements":
            self.lists += 1
            year = body["startDate"][:4]
            status = self.refuse_year.get(("statements", year))
            if status:
                return {"status": status, "json": None}
            items = self.statements if body["docType"] == "STMT" else self.confirmations
            return {"status": 200, "json": {"statement": {"docDetails": {"docDetail": [
                self._statement_row(i) for i in items if i["end"][:4] == year]}}}}
        if tail == "taxform":
            self.lists += 1
            year = str(body["taxYear"])
            self.tax_years_asked.append(int(year))
            status = self.refuse_year.get(("forms", year))
            if status or not 2016 <= int(year) <= 2031:
                return {"status": status or 400, "json": None}
            return {"status": 200, "json": {"taxSeason": {"taxFormDetails": {"taxFormDetail": [
                self._form_row(i) for i in self.forms if str(i["year"]) == year]}}}}
        assert tail == "download", url
        return self._document(url, body)

    def _document(self, url, body):
        kinds = (("STMT", self.statements), ("TC", self.confirmations), ("TF", self.forms))
        found = [(kind, i["document"]) for kind, items in kinds for i in items
                 if self.id_of(i["document"]) == body["id"]]
        host = url.split("/")[2]
        version = "v1" if "/v1/" in url else "v2"
        self.fetched.append((host, version, body["docType"], body["acctType"], body["id"]))
        if not found:
            return {"status": 400, "json": None}
        kind, document = found[0]
        route = ("dpservice.fidelity.com", "v1") if kind == "TF" else (
            "digitalservices.fidelity.com", "v2")
        if (host, version) != route or body["docType"] != kind:
            return {"status": 400, "json": None}
        if document in self.empty:
            return {"status": 200, "json": {"document": {"docDetail": {}}}}
        content = base64.b64encode(pdf_of(document)).decode()
        return {"status": 200, "json": {"document": {"docDetail": {"content": content,
                                                                   "deflated": "N"}}}}


class Clock(datetime):
    """The hub's clock, so a test's dates stay in the years it names."""

    @classmethod
    def now(cls, tz=None):
        return cls(2031, 11, 7, 12, 0, 0, tzinfo=tz)


class Home:
    def __init__(self, tmp_path, monkeypatch, capsys):
        self.hub = Hub()
        self.capsys = capsys
        self.out = tmp_path / "out"
        self.config = json.loads((APP / "config.example.json").read_text(encoding="utf-8"))
        self.config.update({"owner": "Dana Example", "output_dir": str(self.out),
                            "profile_dir": str(tmp_path / "profile"),
                            "cdp_url": "http://127.0.0.1:9", "delay_min_seconds": 0,
                            "delay_max_seconds": 0, "default_start_date": ""})
        self.cfg = tmp_path / "config.json"
        self.write_config()
        for name in ("_FILENAME_PATTERN", "_PATTERN_OWNER", "_FILENAME_OWNER"):
            monkeypatch.setattr(core_storage, name, getattr(core_storage, name))
        page = SimpleNamespace(url=site.DOC_CENTER)
        monkeypatch.setattr(docs.App, "page", lambda app: page)
        monkeypatch.setattr(docs.App, "_on_its_site", lambda app: page)
        monkeypatch.setattr(docs.App, "check_session", lambda app, *_a, **_kw: None)
        monkeypatch.setattr(site.intake, "evaluate", self.hub.answer)
        monkeypatch.setattr(site, "_dt", Clock)
        monkeypatch.setattr("time.sleep", lambda *_a, **_kw: None)

    def write_config(self, **more):
        self.cfg.write_text(json.dumps(dict(self.config, **more)), encoding="utf-8")

    def run(self, *flags):
        """The app's main and what it said. What it fetched this run is left
        in hub.fetched."""
        self.capsys.readouterr()
        self.hub.fetched = []
        self.hub.tax_years_asked = []
        code = docs.main(["--config", str(self.cfg), *flags])
        return code, " ".join(self.capsys.readouterr().out.split())

    def run_all(self, *flags):
        return self.run("--all", "--yes", *flags)

    def store(self, name: str) -> dict:
        return json.loads((self.out / name).read_text(encoding="utf-8"))

    def put(self, name: str, records: dict) -> None:
        (self.out / name).write_text(json.dumps(records), encoding="utf-8")

    def on_disk(self) -> list:
        """Whose bytes each PDF under the output folder holds."""
        return sorted(whose(p.read_bytes()) for p in self.out.rglob("*.pdf"))

    def held(self) -> dict:
        """Whose bytes each saved record's file holds, by key."""
        return {key: whose(Path(rec["pdf_path"]).read_bytes())
                for key, rec in sorted(self.store("progress.json").items())
                if isinstance(rec, dict) and rec.get("downloaded_ok")}

    def states(self) -> dict:
        return {key: rec["state"] for key, rec in sorted(self.store("progress.json").items())}

    def fetched_ids(self) -> list:
        return [call[-1] for call in self.hub.fetched]

    def as_before_this_change(self) -> None:
        """Both stores as they stood before #145. A statement of several
        accounts kept no account, and no record kept a tax year."""
        for name in ("discovery.json", "progress.json"):
            records = self.store(name)
            for record in records.values():
                record.pop("tax_year", None)
                if record.get("account") == site.COMBINED:
                    record["account"] = ""
            self.put(name, records)


@pytest.fixture
def home(tmp_path, monkeypatch, capsys):
    return Home(tmp_path, monkeypatch, capsys)


# -- the wrong document under a right name -----------------------------------

def test_a_later_accounts_two_forms_each_save_their_own_bytes(home):
    """Numbered across accounts and counted within one, the second account's
    first form took its second's id, so that was saved twice, its first
    never, and all three read Completed."""
    home.hub.forms = [form("A1", ONE), form("B1", TWO), form("B2", TWO)]
    code, _said = home.run_all()
    assert code == 0
    assert home.held() == {FORM: "A1", FORM + "#1": "B1", FORM + "#2": "B2"}
    assert home.on_disk() == ["A1", "B1", "B2"]


def test_combined_rows_behind_an_account_row_each_save_their_own_bytes(home):
    """Combined rows reach resolve_item now that their account is a word,
    and an account row ahead of them moved their count the same way."""
    home.hub.statements = [statement("S0", ONE), statement("C1"), statement("C2")]
    home.run_all()
    assert home.held() == {STATEMENT: "S0", STATEMENT + "#1": "C1", STATEMENT + "#2": "C2"}
    assert home.on_disk() == ["C1", "C2", "S0"]


def test_ids_that_did_not_last_are_numbered_within_the_account_as_the_list_was(home):
    """Resume reads no list of its own, so what Discover stored is a session
    old. Counting the across-accounts number within one account lands on the
    next row or on nothing."""
    home.hub.ids = "session"
    home.hub.forms = [form("A1", ONE), form("B1", TWO), form("B2", TWO)]
    home.run("--discover")
    home.hub.new_session()
    home.run("--resume")
    assert home.held() == {FORM: "A1", FORM + "#1": "B1", FORM + "#2": "B2"}


def test_a_stored_id_the_list_still_shows_beats_the_place(home):
    """The list came back in another order. A place would hand each form
    the other's bytes."""
    home.hub.forms = [form("B1", TWO), form("B2", TWO)]
    home.run("--discover")
    home.hub.forms.reverse()
    home.run("--resume")
    assert home.held() == {FORM: "B1", FORM + "#1": "B2"}


def test_a_listing_in_another_order_leaves_each_number_with_its_document(home):
    """The first saved, the second failed, and the next list reversed. A
    number going by order gave the first's id to the failed record, so the
    first was saved twice and the second never."""
    home.hub.forms = [form("B1", TWO), form("B2", TWO)]
    home.hub.empty = {"B2"}
    home.run_all()
    assert home.on_disk() == ["B1"]
    home.hub.empty = set()
    home.hub.forms.reverse()
    home.run_all()
    assert home.on_disk() == ["B1", "B2"]
    assert home.held() == {FORM: "B1", FORM + "#1": "B2"}


def test_a_twin_beside_one_saved_fails_when_its_id_did_not_last(home):
    """Which of the two rows is the saved one cannot be told, so guessing
    saves that one twice and the other never."""
    home.hub.ids = "session"
    home.hub.forms = [form("B1", TWO), form("B2", TWO)]
    home.hub.empty = {"B2"}
    home.run_all()
    home.hub.empty = set()
    home.hub.new_session()
    home.hub.forms.reverse()
    code, _said = home.run_all()
    assert code == 1
    assert home.fetched_ids() == []
    assert home.on_disk() == ["B1"]
    assert home.states() == {FORM: "Completed", FORM + "#1": "Failed"}


def test_a_list_holding_more_alike_than_are_known_fails_each_one(home):
    """Two known, three listed, and no id still shown. Neither place still
    names the document it named when the list was numbered."""
    home.hub.ids = "session"
    home.hub.forms = [form("B1", TWO), form("B2", TWO)]
    home.run("--discover")
    home.hub.new_session()
    home.hub.forms.insert(0, form("B0", TWO))
    code, _said = home.run("--resume")
    assert code == 1
    assert home.fetched_ids() == []
    assert set(home.states().values()) == {"Failed"}


def test_two_records_keeping_one_id_take_one_row_once(home):
    """The second record's stored id is shown, on the first's row, and going
    by it saves one form twice under two right names."""
    home.hub.forms = [form("B1", TWO), form("B2", TWO)]
    home.run("--discover")
    records = home.store("discovery.json")
    records[FORM + "#1"]["item_id"] = records[FORM]["item_id"]
    home.put("discovery.json", records)
    home.hub.forms.pop()
    code, _said = home.run("--resume")
    assert code == 1
    assert home.on_disk() == ["B1"]
    assert home.states() == {FORM: "Completed", FORM + "#1": "Failed"}


def test_two_rows_carrying_one_id_are_refused(home):
    """Two rows of one id are one document to the hub, so two records going
    by them are two documents resolved to one row."""
    home.hub.forms = [form("B1", TWO), form("B2", TWO)]
    home.hub.shared_id = "ONE-ID"
    code, _said = home.run_all()
    assert code == 1
    assert home.fetched_ids() == []
    assert set(home.states().values()) == {"Failed"}


def test_a_row_discover_leaves_out_is_left_out_of_the_fresh_listing_too(home):
    """A row with no PDF was numbered by the download and not by Discover,
    so the two counted different lists."""
    home.hub.ids = "session"
    home.hub.statements = [statement("HTML", pdf=False), statement("C1"), statement("C2")]
    home.run("--discover")
    home.hub.new_session()
    home.run("--resume")
    assert home.held() == {STATEMENT: "C1", STATEMENT + "#1": "C2"}


def test_two_twins_are_each_saved_when_ids_last_only_one_list(home):
    """The run saves the first twin, and the second's fresh list says nothing
    of that id. Counted as saved before, the first would stop the second."""
    home.hub.ids = "list"
    home.hub.forms = [form("B1", TWO), form("B2", TWO)]
    code, _said = home.run_all()
    assert code == 0
    assert home.on_disk() == ["B1", "B2"]


def test_a_row_not_told_apart_writes_no_id_over_anything(home):
    """Discover cannot say which of two rows is the one saved, so neither id
    may land on a record, or the next run downloads by it."""
    home.hub.ids = "session"
    home.hub.forms = [form("B1", TWO)]
    home.run_all()
    kept = home.store("discovery.json")[FORM]["item_id"]
    home.hub.new_session()
    home.hub.forms.insert(0, form("B2", TWO))
    home.run("--discover")
    records = home.store("discovery.json")
    assert records[FORM]["item_id"] == kept
    assert records[FORM + "#1"]["item_id"] == ""


@pytest.mark.parametrize("account,name,kept", [("Roth  IRA", "Form 1099-R", "Roth IRA 0022"),
                                               ("Roth", "Form 1099-R ", "Roth 0022"),
                                               ("Roth", "Form  1099-R", "Roth 0022")])
def test_a_name_with_spaces_to_tidy_is_still_its_own_records(home, account, name, kept):
    """The record keeps a name tidied and the fresh row was read raw, so a
    doubled or trailing space missed, its id read as another document's,
    and every new document failed. The record keeps the names as main
    writes them."""
    home.hub.accounts = [dict(TWO, name=account)]
    home.hub.forms = [form("F30", home.hub.accounts[0], name=name)]
    code, _said = home.run_all()
    assert code == 0
    assert home.held() == {FORM: "F30"}
    record = home.store("discovery.json")[FORM]
    assert (record["title"], record["account"]) == ("2030 Form 1099-R", kept)


def test_a_record_keeps_the_id_its_bytes_came_from(home):
    """An account renamed while a new form waited. Its download found the new
    form by number and kept the id discovery had given it, the saved form's,
    so the next list gave that id to the saved form and the new one came
    down again under a new number."""
    home.hub.accounts = [dict(ONE)]
    home.hub.forms = [form("X", home.hub.accounts[0])]
    home.run_all()
    home.hub.forms.insert(0, form("Y", home.hub.accounts[0]))
    home.run("--discover")
    home.hub.accounts[0]["name"] = "Trading"
    home.run_all()
    assert home.on_disk() == ["X", "Y"]
    assert {key: rec["item_id"] for key, rec in home.store("progress.json").items()} == {
        FORM: "X", FORM + "#1": "Y"}
    home.run_all()
    assert home.fetched_ids() == []
    assert home.on_disk() == ["X", "Y"]


# -- an archive from before this change --------------------------------------

def test_a_second_accounts_old_statement_resolves_to_its_own_bytes(home):
    """Number 1 of two accounts is the only row of its account. Download
    again in a later session, with the stored ids dead, and Resume listing
    nothing of its own, so only the number can find it."""
    home.hub.ids = "session"
    home.hub.statements = [statement("S1", ONE), statement("S2", TWO)]
    home.run_all()
    home.as_before_this_change()
    home.hub.new_session()
    code, _said = home.run("--resume", "--redownload")
    assert code == 0
    assert home.held() == {STATEMENT: "S1", STATEMENT + "#1": "S2"}
    assert home.on_disk() == ["S1", "S1", "S2", "S2"]


def test_an_old_record_with_no_account_is_the_combined_row(home):
    """download_document skipped resolve_item for an empty account, so such a
    record went by its stored id alone, and that id may not last."""
    home.hub.ids = "session"
    home.hub.statements = [statement("C1")]
    home.run("--discover")
    home.as_before_this_change()
    assert home.store("discovery.json")[STATEMENT]["account"] == ""
    home.hub.new_session()
    home.run("--resume")
    assert home.held() == {STATEMENT: "C1"}


@pytest.mark.parametrize("ids", ["always", "session"])
def test_a_new_account_row_ahead_of_an_old_combined_row_takes_none_of_its_keys(home, ids):
    """A stored empty account never matched Combined, so the new row took
    the saved key and was never saved, and Combined went round again as a
    second copy."""
    home.hub.ids = ids
    home.hub.statements = [statement("C1")]
    home.run_all()
    home.as_before_this_change()
    home.hub.new_session()
    home.hub.statements.insert(0, statement("N1", ONE))
    code, _said = home.run_all()
    assert code == 0
    assert [whose_id.split(".")[0] for whose_id in home.fetched_ids()] == ["N1"]
    assert home.held() == {STATEMENT: "C1", STATEMENT + "#1": "N1"}
    records = home.store("discovery.json")
    assert records[STATEMENT]["account"] == site.COMBINED


@pytest.mark.parametrize("ids", ["always", "session"])
def test_a_new_account_row_ahead_of_two_old_combined_rows_takes_none_of_their_keys(home, ids):
    """Only the first number a document holds used to be kept for it, so the
    new row took the second Combined row's key."""
    home.hub.ids = ids
    home.hub.statements = [statement("C1"), statement("C2")]
    home.run_all()
    home.as_before_this_change()
    home.hub.new_session()
    home.hub.statements.insert(0, statement("N1", ONE))
    home.run_all()
    assert [whose_id.split(".")[0] for whose_id in home.fetched_ids()] == ["N1"]
    assert home.held() == {STATEMENT: "C1", STATEMENT + "#1": "C2", STATEMENT + "#2": "N1"}


def test_a_saved_number_survives_a_history_moved_to_another_computer(home):
    """A move brings progress and no discovery, so the saved form is known
    by its key alone, and read by its place it took number 0 and came again."""
    home.hub.forms = [form("B1", TWO), form("B2", TWO)]
    home.hub.empty = {"B1"}
    home.run_all()
    assert home.held() == {FORM + "#1": "B2"}
    (home.out / "discovery.json").unlink()
    home.hub.forms = [form("B2", TWO)]
    home.run_all()
    assert home.fetched_ids() == []
    assert home.on_disk() == ["B2"]


# -- a tax year that fails ---------------------------------------------------

@pytest.mark.parametrize("kind", ["forms", "statements"])
@pytest.mark.parametrize("status,stop", [(500, RuntimeError), (401, site.SessionExpired)])
def test_a_year_that_fails_leaves_the_list_unread(home, kind, status, stop):
    """A form year was logged and passed over, so a 500 or a 401 left the
    list noted whole, and Resume called the run complete. It now goes as a
    statement year always went."""
    home.hub.forms = [form("F30", ONE), form("F29", ONE, year=2029, day="2030-01-31")]
    home.hub.statements = [statement("S1", ONE)]
    home.run_all()
    assert home.store("last-listing.json")["complete"] is True

    home.hub.refuse_year = {(kind, "2029" if kind == "forms" else "2031"): status}
    with pytest.raises(stop):
        home.run_all()
    assert home.store("last-listing.json")["complete"] is False
    with pytest.raises(ListNotRead):
        home.run("--resume")
    said = home.capsys.readouterr().out
    assert "stopped before it read" in " ".join(said.split())
    assert "everything in scope is complete" not in said


# -- forms dated after their tax year ----------------------------------------

@pytest.mark.parametrize("flags,config,saved,asked", [
    (["--year", "2030"], {}, ["F29", "F30"], [2030, 2029]),
    (["--year", "2031"], {}, ["F30"], [2030]),
    (["--year", "2029"], {}, ["F29"], [2029, 2028]),
    ([], {"default_start_date": "2031-01-01"}, ["F30"], [2030]),
    (["--start-date", "2030-06-01"], {}, ["F30"], [2030, 2029]),
    (["--start-date", "2030-01-01", "--end-date", "2030-12-31"], {}, ["F29", "F30"], [2030, 2029]),
    (["--end-date", "2029-12-31"], {}, ["F29"], list(range(2029, 2015, -1))),
    ([], {}, ["F29", "F30"], list(range(2030, 2015, -1))),
])
def test_a_scope_keeps_a_form_by_its_date_or_its_tax_year(home, flags, config, saved, asked):
    """The listing goes by tax year and the filter went by the form's date,
    so a year, or a floor in the year a form is dated, saved none of them
    and the run ended clean."""
    home.write_config(**config)
    home.hub.forms = [form("F30", ONE), form("F29", ONE, year=2029, day="2030-01-31")]
    code, _said = home.run_all(*flags)
    assert code == 0
    assert home.on_disk() == saved
    assert sorted(set(home.hub.tax_years_asked), reverse=True) == asked


def test_a_form_dated_two_years_late_is_listed_only_by_a_run_with_no_scope(home):
    """As the README and the changelog say. A scoped run asks its years and
    the one before, and no earlier."""
    home.hub.forms = [form("F28", ONE, year=2028, day="2030-06-01")]
    home.run_all("--year", "2030")
    assert home.on_disk() == []
    assert 2028 not in home.hub.tax_years_asked
    home.run_all()
    assert home.on_disk() == ["F28"]


def test_a_form_dated_before_a_floor_inside_its_tax_year_is_kept(home):
    """Its tax year ends after the floor, so the scope keeps it, and the
    listing must not drop it first."""
    home.hub.forms = [form("F30", ONE, day="2030-03-01")]
    home.run_all("--start-date", "2030-06-01")
    assert home.on_disk() == ["F30"]


def test_a_form_outside_a_window_on_both_sides_is_out(home):
    """Dated after the window and of a tax year before it. Each day clears
    one end of the window, and neither is inside it."""
    home.hub.forms = [form("LATE", ONE, year=2029, day="2031-02-01")]
    home.run_all("--start-date", "2030-01-01", "--end-date", "2030-12-31")
    assert home.on_disk() == []


def test_a_scope_reads_a_form_with_no_kept_year_by_its_title(home):
    """A record from before the year was kept, on a Resume that lists
    nothing to give it one."""
    home.hub.forms = [form("F30", ONE)]
    home.run("--discover")
    home.as_before_this_change()
    home.run("--resume", "--year", "2030")
    assert home.on_disk() == ["F30"]


# -- the year of a form ------------------------------------------------------

@pytest.mark.parametrize("title,listed,year", [
    ("1099-R 2029", "", 2029),
    ("2029 Form 5498", "", 2029),
    ("Form 1099-R", "", 0),
    ("2028 Form 5498 2029", "", 0),
    ("Form 2031", "", 0),
    ("Form 1099-R 2029", "2028", 2028),
    ("Form 1099-R", 2029, 2029),
])
def test_the_year_of_a_form(home, title, listed, year):
    assert site.tax_year_of(title, listed) == year


def test_a_year_in_a_statements_title_is_no_tax_year(home):
    """Only a tax form is read by a tax year. A statement is read by its own
    date alone, or a year in its title would widen every scope."""
    record = docs.Document(category="Statement", title="Statement 2030", date=MONTH_END)
    assert docs.App._tax_year(None, record) == 0


def test_a_listed_year_that_is_no_number_is_no_tax_year(home):
    """It would go into a scope as a day that sorts anywhere."""
    row = {"docName": "Form 5498", "taxYear": "n/a",
           "docDetail": {"docId": "F1", "docPeriodEndDate": midnight_eastern(FORM_DAY)}}
    assert site._row("Tax Form", "Tax Document", row, {}, "TAX", year=2030)["tax_year"] == ""


def test_the_listed_year_finds_a_form_whose_title_names_two(home):
    """The form names its own year and the listing another, so the title
    cannot say which list to ask, and the kept year has to."""
    home.hub.ids = "session"
    home.hub.forms = [form("F30", ONE, name="Form 1099-R 2029")]
    home.run("--discover")
    home.hub.new_session()
    home.run("--resume")
    assert home.hub.tax_years_asked == [2030]
    assert home.on_disk() == ["F30"]


@pytest.mark.parametrize("kept_year", [True, False])
def test_a_title_starting_with_its_form_number_asks_for_its_own_year(home, kept_year):
    """"1099-R 2030" read as year 1099, the hub refused that, and the form
    went Failed. Resume, so the row must come from the right year's list."""
    home.hub.ids = "session"
    home.hub.forms = [form("F30", ONE, name="1099-R 2030")]
    home.run("--discover")
    if not kept_year:
        home.as_before_this_change()
    home.hub.new_session()
    code, _said = home.run("--resume")
    assert code == 0
    assert home.hub.tax_years_asked == [2030]
    assert home.on_disk() == ["F30"]


def test_a_form_whose_title_ends_in_statement_is_looked_for_among_the_forms(home):
    """"Tax Reporting Statement" reads like a statement, and among the
    statements no row was ever found for it."""
    home.hub.ids = "session"
    home.hub.forms = [form("F30", ONE, name="Tax Reporting Statement")]
    home.run("--discover")
    home.hub.new_session()
    home.run("--resume")
    assert home.hub.tax_years_asked == [2030]
    assert home.on_disk() == ["F30"]


# -- what a re-discovered document changes -----------------------------------

def test_a_document_that_failed_keeps_its_state_and_is_tried_again(home):
    """Clearing discovery's state changed nothing a person sees, since a run
    decides from progress. An empty answer saves nothing, so it is a failure
    and not a document waiting in Manual Review (#152), and it is tried again."""
    home.hub.ids = "session"
    home.hub.forms = [form("F30", ONE)]
    home.hub.empty = {"F30"}
    home.run_all()
    assert home.states() == {FORM: "Failed"}

    home.hub.empty = set()
    home.hub.new_session()
    home.run("--discover")
    record = home.store("discovery.json")[FORM]
    assert record["item_id"] == home.hub.id_of("F30")
    assert record["state"] == "Failed"

    home.run_all()
    assert home.on_disk() == ["F30"]
    assert home.states() == {FORM: "Completed"}


def test_a_saved_document_is_cleared_of_nothing(home):
    home.hub.ids = "session"
    home.hub.forms = [form("F30", ONE)]
    home.run_all()
    records = home.store("discovery.json")
    records[FORM]["state"] = "Needs Manual Review"
    home.put("discovery.json", records)
    home.hub.new_session()
    home.run_all()
    assert home.store("discovery.json")[FORM]["state"] == "Needs Manual Review"
    assert home.fetched_ids() == []
    assert home.held() == {FORM: "F30"}


def test_rediscovering_a_saved_document_updates_its_record_and_nothing_else(home):
    """A name changed on the hub and an id that did not last reach the
    record, under the key it had, and its download stays done."""
    home.hub.ids = "session"
    home.hub.accounts = [dict(ONE)]
    home.hub.statements = [statement("S1", home.hub.accounts[0])]
    home.run_all()
    before = home.store("discovery.json")[STATEMENT]
    assert before["account"] == "Individual 0011"

    home.hub.accounts[0].update(name="Trading", acctType="Cash")
    home.hub.new_session()
    home.run("--discover")
    records = home.store("discovery.json")
    assert list(records) == [STATEMENT]
    assert records[STATEMENT]["account"] == "Trading 0011"
    assert records[STATEMENT]["summary"] == "Monthly Statement - Trading 0011"
    assert records[STATEMENT]["item_id"] == home.hub.id_of("S1")
    assert records[STATEMENT]["item_id"] != before["item_id"]
    assert records[STATEMENT]["client_id"] == "STMT|Cash"
    assert home.fetched_ids() == []
    assert home.held() == {STATEMENT: "S1"}


def test_rediscovering_a_form_gives_it_the_year_the_listing_names(home):
    home.hub.forms = [form("F30", ONE)]
    home.run("--discover")
    home.as_before_this_change()
    assert "tax_year" not in home.store("discovery.json")[FORM]
    home.run("--discover")
    assert home.store("discovery.json")[FORM]["tax_year"] == "2030"


# -- where a document is asked for -------------------------------------------

def test_each_kind_goes_to_its_own_download_call(home):
    """A tax form to the v1 download on dpservice with docType TF, as #145
    says, and a statement and a trade confirmation to the v2 one on
    digitalservices with their own. The hub refuses anything else, so a run
    going the wrong way saves nothing."""
    home.hub.forms = [form("F30", ONE)]
    home.hub.statements = [statement("S1", ONE)]
    home.hub.confirmations = [statement("T1", TWO, end="2031-09-15", start="2031-09-15")]
    code, _said = home.run_all()
    assert code == 0
    assert home.on_disk() == ["F30", "S1", "T1"]
    assert sorted(home.hub.fetched) == [
        ("digitalservices.fidelity.com", "v2", "STMT", "Brokerage", "S1"),
        ("digitalservices.fidelity.com", "v2", "TC", "Brokerage", "T1"),
        ("dpservice.fidelity.com", "v1", "TF", "Brokerage", "F30"),
    ]


def test_a_record_kept_with_the_old_tax_word_is_asked_for_as_tf(home):
    """Its stored client says TAX, and with no row to give it a new one the
    download still has to ask as a form does."""
    home.hub.forms = [form("F30", ONE)]
    assert site.fetch_pdf(None, "F30", "TAX", "Brokerage").startswith(b"%PDF")
    assert home.hub.fetched == [("dpservice.fidelity.com", "v1", "TF", "Brokerage", "F30")]


def test_a_form_of_an_account_the_accounts_call_left_out_keeps_its_own_type(home):
    """The nested acctDetail says the type, as in #145's fixture."""
    plan = {"acctNum": "400000044", "acctType": "WPS", "name": ""}
    home.hub.forms = [form("F30", plan)]
    home.run_all()
    assert home.hub.fetched == [("dpservice.fidelity.com", "v1", "TF", "WPS", "F30")]
    assert home.store("discovery.json")[FORM]["client_id"] == "TF|WPS"


def test_a_rerun_downloads_nothing(home):
    home.hub.statements = [statement("S1", ONE), statement("C1")]
    home.hub.forms = [form("A1", ONE), form("B1", TWO), form("B2", TWO)]
    home.run_all()
    home.run_all()
    assert home.fetched_ids() == []
    assert home.on_disk() == ["A1", "B1", "B2", "C1", "S1"]
