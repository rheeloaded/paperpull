"""What the maintainer's review of #57 changed, each held here.

A statement is named for its account once. Discover walks the year picker
once, and Diagnose takes no screenshot of a brokerage page. The download
itself is tested in a real browser, in test_download_in_a_browser.py,
since a fake one passed a version that saved nothing. Every account,
holder and amount is invented."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage
import vanguard_docs as docs
import vanguard_site as site
from paperpull_core import doc_types
from paperpull_core.testkit import sample_pdf

TITLE = "Account Statement - Example Holder — Cash Plus Account — 1234567"
LABEL = ("Download a pdf statement generated on August 31, 2026 with "
         "description Example Holder — Cash Plus Account — 1234567")
PDF = sample_pdf()


# -- names, discovery and Diagnose ------------------------------------------------

class _Store:
    def __init__(self, data=None):
        self.data = dict(data or {})

    def get(self, key):
        return self.data.get(key)

    def update(self, key, value, save=True):
        self.data.setdefault(key, {}).update(value)

    def save(self, backup=False):
        pass


def _app(tmp_path=None):
    app = docs.App.__new__(docs.App)
    app.args = SimpleNamespace(start_date=None, end_date=None, year=None, type=None,
                               account=None, max_docs=None, redownload=False)
    app.config = {"document_types": list(storage.ALL_CATEGORIES), "account_labels": {},
                  "default_start_date": ""}
    app.rules = doc_types.load_rules()
    app.stats = {"skipped_out_of_scope": 0, "discovered": 0}
    app.discovery, app.progress = _Store(), _Store()
    app._journal = app._requests = None
    if tmp_path is not None:
        app.paths = storage.Paths(tmp_path)
        app.paths.ensure()
    return app


def _listed():
    """One statement as list_documents hands it over."""
    return {"account": "Example Holder — Cash Plus Account — 1234567",
            "account_id": "123400000000001", "last4": "4567", "date": "2026-08-31",
            "period": "2026-08", "title": TITLE, "category": "Statement",
            "statement_id": "opaque==", "doc_type": "Statement", "occurrence": 0}


def test_a_statement_is_named_for_its_account_once():
    app = _app()
    assert app._record_vanguard_doc(_listed(), set()) == 1
    [rec] = app.discovery.data.values()
    assert rec["summary"] == TITLE
    assert storage.build_pdf_filename(rec["date"], rec["summary"], "", record=rec).count(
        "Cash Plus Account") == 1


def test_a_statement_saved_under_the_doubled_name_is_given_the_new_one():
    """The name a record carries is what Rename reads, so a file saved under
    the doubled name can take the new one without being downloaded again.
    The key is the title and does not change."""
    app = _app()
    app._record_vanguard_doc(_listed(), set())
    [key] = app.discovery.data
    app.discovery.data[key].update(summary=TITLE + " - Example Holder — Cash Plus "
                                   "Account — 1234567", downloaded_ok=True)
    assert app._record_vanguard_doc(_listed(), set()) == 0
    assert list(app.discovery.data) == [key]
    assert app.discovery.data[key]["summary"] == TITLE
    assert app.discovery.data[key]["downloaded_ok"] is True


def test_rename_moves_a_file_saved_under_the_doubled_name(tmp_path, capsys):
    """What the contributor's own 135 statements need, end to end. Discover
    runs again with this build and Rename then gives every file the name a
    download would give it today, without downloading anything."""
    app = _app(tmp_path)
    app.args.apply = False
    app.config.update(max_path_length=240, min_pdf_bytes=1000)
    app.progress = storage.JsonStore(app.paths.progress_json)
    app.discovery = storage.JsonStore(app.paths.discovery_json)
    app.index_csv = storage.CsvFile(app.paths.document_index_csv,
                                    storage.DOCUMENT_INDEX_COLUMNS)
    app._record_vanguard_doc(_listed(), set())
    [key] = app.discovery.data
    doubled = TITLE + " - Example Holder — Cash Plus Account — 1234567"
    rec = dict(app.discovery.data[key], summary=doubled)
    folder = app.paths.folder_for("Statement")
    old = folder / storage.build_pdf_filename(rec["date"], doubled, "", record=rec)
    old.write_bytes(PDF)
    rec.update(state=docs.State.COMPLETED.value, downloaded_ok=True,
               pdf_filename=old.name, pdf_path=str(old))
    app.progress.update(key, dict(rec))
    app.discovery.update(key, dict(rec))
    app.index_csv.append_rows([{
        "Document Date": rec["date"], "Category": "Statement",
        "Document Summary": doubled, "Document Title": rec["title"],
        "PDF Filename": old.name, "PDF Full Path": str(old),
        "Processing Status": "Completed"}])

    app._record_vanguard_doc(_listed(), set())
    app.args.apply = True
    app.cmd_rename()
    new = storage.build_pdf_filename(rec["date"], TITLE, "", record=app.discovery.get(key))
    assert new.count("Cash Plus Account") == 1
    assert sorted(p.name for p in folder.glob("*.pdf")) == [new]
    assert app.index_csv.read_all()[0]["PDF Filename"] == new
    assert list(app.progress.data) == [key]
    assert app._already_done(docs.Document.from_dict(app.discovery.get(key)))


def test_discover_walks_the_year_picker_once(monkeypatch):
    """list_accounts walked every year of the picker to learn that no account
    is a charitable one, and then the documents were read by a second walk."""
    app = _app()
    page = SimpleNamespace(url="https://statements.web.vanguard.com/")
    app.page = lambda: page
    app.check_session = lambda p: None
    monkeypatch.setattr(site, "ensure_statements", lambda p: True)
    walks = []
    monkeypatch.setattr(site, "list_accounts", lambda p: walks.append("accounts") or [])
    monkeypatch.setattr(site, "collect_documents",
                        lambda p, keep=None: walks.append("documents") or [_listed()])
    assert app.cmd_discover(quiet=True) == 1
    assert walks == ["documents"]


def test_diagnose_takes_no_screenshot_and_reads_what_vanguard_sends(tmp_path, monkeypatch):
    app = _app(tmp_path)

    class _NoPictures:
        url = "https://statements.web.vanguard.com/"

        def title(self):
            return "Statements"

        def screenshot(self, **kw):
            raise AssertionError("Diagnose took a screenshot of a brokerage page")

        def locator(self, sel):
            return SimpleNamespace(count=lambda: 0, inner_text=lambda timeout=0: "")

    page = _NoPictures()
    app.page = lambda: page
    monkeypatch.setattr(site, "goto_documents", lambda p: True)
    stmt = {"accountId": "123400000000001", "accountNumber": "1234567",
            "statementDescription": "Example Holder — Cash Plus Account — 1234567",
            "endDate": "2026-08-31", "frequencyType": "MONTHLY",
            "statementType": "ACCOUNT_GROUP", "statementId": "opaque=="}
    walks = []
    monkeypatch.setattr(site, "collect_statements_json",
                        lambda p, years=None, keep=None: walks.append(1) or [stmt])
    monkeypatch.setattr(site, "list_accounts",
                        lambda p: (_ for _ in ()).throw(AssertionError("a second walk")))
    monkeypatch.setattr(site, "read_page_ui", lambda p: {"years": ["2026", "2025"]})
    app.cmd_diagnose()
    info = json.loads((app.paths.diagnostics / "diagnose-documents.json").read_text(
        encoding="utf-8"))
    assert not info.get("error"), info.get("error")
    assert walks == [1]
    assert info["documents_total"] == 1
    assert info["documents_by_category"] == {"Statement": 1}
    # Dates and years off the page leave as their shape, which still says
    # how Vanguard writes them.
    assert info["samples"][0]["date"] == "9999-99-99"
    assert info["rendered"] == {"years": ["9999", "9999"]}
    assert "1234567" not in json.dumps(info["documents_by_account"])
    assert not list(app.paths.diagnostics.glob("*.png"))
